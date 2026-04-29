"""
effect_scheduler.py — 特殊演出スケジューラ

RRoulettePWA v0.9.1 の EffectScheduler を Python に移植。
スピン開始時に当選項目の role を受け取り、演出を totalMs × timing 後に QTimer で発火する。

抽選ロジック:
  1) enabled + role 一致 + probability 抽選通過 → 候補列挙
  2) 候補から 1 つだけランダム抽選
  3) selectedVariant (0=ランダム 1〜5, 1〜5=固定) で variant 決定
  4) timing を timingRange / timingRandom で決定
  5) QTimer.singleShot(delay_ms, callback) で発火

使用側:
  scheduler = EffectScheduler()
  scheduler.schedule(winner_role, settings, total_ms, callbacks)
  # スピン中断時は cancel()
  scheduler.cancel()
"""

from __future__ import annotations

import random
from typing import Callable

from PySide6.QtCore import QTimer

from spin_effect_settings import SpinEffectSettings, EFFECT_KEYS, EFFECT_TRIGGERS


class EffectScheduler:
    """演出のスケジューリングと発火を担う。

    Qt メインスレッドで動作することを前提とする（QTimer.singleShot 使用）。
    """

    # v0.6.1: 各演出のおおよそのアニメーション時間 (ms)。
    # delay + duration > total_ms となる場合、結果表示までに収まらないため
    # 演出を抑止する判定に使う。値は各 fire() 実装の最大値を採用。
    _EFFECT_DURATIONS_MS: dict[str, int] = {
        "soundConfirm":   1500,
        "soundExpect":    1500,
        "soundNgConfirm": 1500,
        "miniCharTarget": 2000,
        "miniCharExpect": 2000,
        "miniCharNg":     2000,
        "cutInTarget":    1700,
        "cutInExpect":    1700,
        "cutInNg":        1700,
        "flashConfirm":   1000,
        "wheelGlow":      1000,
        "textChance":     1600,
    }
    # 結果表示までに完了させるための安全マージン（ms）
    _RESULT_MARGIN_MS: int = 100

    def __init__(self):
        self._timers: list[QTimer] = []

    # ------------------------------------------------------------------
    #  スケジュール
    # ------------------------------------------------------------------

    def schedule(
        self,
        winner_role: str | None,
        settings: SpinEffectSettings,
        total_ms: float,
        callbacks: dict[str, Callable[[int], None]],
    ) -> None:
        """演出を totalMs × timing 後に発火するようスケジュールする。

        Args:
            winner_role: "target" / "avoid" / "expect_candidate" / None。None なら何もしない。
            settings: 演出設定。enabled=False なら何もしない。
            total_ms: スピン総時間（ms）
            callbacks: EffectKey → コールバック(variant: int)。
                       variant 引数に 1〜5 の整数を渡す。
        """
        self.cancel()
        if not settings.enabled or winner_role not in ("target", "avoid", "expect_candidate"):
            return

        if settings.all_random:
            # all_random モード: 有効+role 一致の演出から 1 つ選択 → 確率/timing/variant を全ランダム
            # 各演出が独立に確率ロールすると発火確率がほぼ 100% になるため、
            # 1 本抽選方式（eligible から 1 選 → 1 回だけ確率ロール）で発火確率を約 50% に抑える。
            eligible = [
                key for key in EFFECT_KEYS
                if (cfg_ := settings.effects.get(key))
                and cfg_.enabled
                and winner_role in EFFECT_TRIGGERS.get(key, [])
            ]
            if not eligible:
                return
            chosen = random.choice(eligible)
            cfg = settings.effects[chosen]
            # 確率ロール: ランダム確率 p を生成し、独立ロールで通過判定 → 約 50% で発火
            if random.random() > random.random():
                return
            variant = random.randint(1, 5)
            timing = random.random()
        else:
            # 通常モード: 各演出が個別設定に基づき独立に確率抽選
            # 1) 候補列挙
            candidates: list[str] = []
            for key in EFFECT_KEYS:
                cfg = settings.effects.get(key)
                if not cfg or not cfg.enabled:
                    continue
                if winner_role not in EFFECT_TRIGGERS.get(key, []):
                    continue
                if cfg.probability_random:
                    probability = random.random()
                else:
                    lo, hi = cfg.probability_range
                    probability = lo + random.random() * (hi - lo)
                if random.random() > probability:
                    continue
                candidates.append(key)

            if not candidates:
                return

            # 2) 候補から 1 つだけランダム抽選
            chosen = random.choice(candidates)
            cfg = settings.effects[chosen]

            # 3) variant 決定
            sv = cfg.selected_variant
            variant = sv if 1 <= sv <= 5 else random.randint(1, 5)

            # 4) timing 決定
            if cfg.timing_random:
                timing = random.random()
            else:
                lo, hi = cfg.timing_range
                timing = lo + random.random() * (hi - lo)

        cb = callbacks.get(chosen)
        if not cb:
            return

        delay_ms = max(0, int(total_ms * timing))

        # v0.6.1: 演出が結果表示までに収まらない場合の制御
        # delay + duration > total_ms - margin ならスキップする
        eff_dur = self._EFFECT_DURATIONS_MS.get(chosen, 1000)
        latest_finish = delay_ms + eff_dur
        max_allowed = max(0, int(total_ms) - self._RESULT_MARGIN_MS)
        if latest_finish > max_allowed:
            # delay を前倒しして収まるなら前倒し、不可能ならスキップ
            shifted_delay = max_allowed - eff_dur
            if shifted_delay >= 0:
                delay_ms = shifted_delay
            else:
                # 演出時間が長すぎてどう前倒しても収まらない → スキップ
                return

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda v=variant, c=cb: c(v))
        self._timers.append(timer)
        timer.start(delay_ms)

    # ------------------------------------------------------------------
    #  キャンセル
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """スケジュール済みの全タイマーを停止・解放する。"""
        for t in self._timers:
            t.stop()
        self._timers.clear()
