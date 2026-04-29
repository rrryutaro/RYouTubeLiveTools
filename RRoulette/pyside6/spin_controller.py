"""
RRoulette — スピン制御 (4段階モデル対応版)

spin_preset.py の 4段階モデル (push/cruise/decel/landing) を使い、
時刻ベースの解析積分で角度を駆動する。

旧実装との主な変更点:
  - フレームごとの速度減衰 → 経過時間から回転数を解析計算
  - プリセット選択: 9秒/15秒 → プロファイル (x/y/z) + スピン時間
  - ランダム化 4 層 (プロファイル/秒数/秒数微振動/フェーズ内振動)
  - マルチスピン (ダブル/トリプル) と既存機能は維持

責務:
  - spin 開始 / 停止の状態管理
  - 4段階モデルによる角度計算 (time.perf_counter ベース)
  - 結果セグメントの事前決定
  - spin_finished シグナルの発行
"""

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

from spin_preset import (
    PhaseTimes,
    build_phase_times,
    rotations_at,
    PRESET_DURATIONS_MS,
    PRESET_PROFILES_LIST,
)
from effect_scheduler import EffectScheduler
from spin_effect_settings import SpinEffectSettings, default_spin_effect_settings


class SpinController(QObject):
    """スピンの状態と角度計算を管理する。

    WheelWidget への依存は最小限:
      - wheel.angle        (現在角度の取得)
      - wheel.set_angle()  (角度の更新)
      - wheel.seg_at_pointer() (結果判定)
      - wheel._segments    (セグメント情報)
      - wheel._pointer_angle
      - wheel._spin_direction

    Signals:
        spin_started: spin が開始された
        spin_finished(str, int): spin 完了時に (winner_text, seg_index) を emit
    """

    spin_started = Signal()
    spin_finished = Signal(str, int)

    def __init__(self, wheel, sound_manager=None, parent=None):
        super().__init__(parent)
        self._wheel = wheel
        self._sound = sound_manager

        # ── spin 状態 ──────────────────────────────────────────────
        self._spinning: bool = False
        self._spin_sign: int = 1

        # ── 4段階モデル用スピン状態 ─────────────────────────────────
        self._spin_start_time: float = 0.0   # perf_counter (秒)
        self._spin_start_angle: float = 0.0  # 開始角度 (度)
        self._spin_end_angle: float = 0.0    # 終了角度 (度)
        self._spin_times: PhaseTimes | None = None
        self._spin_angle_scale: float = 1.0

        # ── tick 音用 ────────────────────────────────────────────────
        self._prev_seg_idx: int = -1

        # ── 音設定 ───────────────────────────────────────────────────
        self._sound_tick_enabled: bool = True
        self._sound_result_enabled: bool = True
        self._tick_pattern: int = 0
        self._win_pattern: int = 0

        # ── スピン設定 ───────────────────────────────────────────────
        self._spin_duration: float = 5.0          # 秒
        self._spin_profile: str = 'z'              # 'x'/'y'/'z'
        self._spin_preset_random: bool = False
        self._spin_duration_random: bool = False
        self._spin_duration_random_ratio: float = 0.0  # 0-0.5
        self._spin_phase_randomize: float = 0.0         # 0-1
        self._spin_phase_overrides: dict | None = None

        # ── リプレイ記録 ─────────────────────────────────────────────
        self._replay_mgr = None
        self._replay_group_id: str = ""

        # ── マルチスピン ─────────────────────────────────────────────
        self._spin_mode: int = 0
        self._double_duration: float = 5.0
        self._triple_duration: float = 5.0
        self._multi_phase: int = 0
        self._multi_total: int = 1
        self._multi_delay_timer: QTimer = QTimer(self)
        self._multi_delay_timer.setSingleShot(True)
        self._multi_delay_timer.setInterval(800)
        self._multi_delay_timer.timeout.connect(self._start_next_phase)

        # ── 特殊演出 ─────────────────────────────────────────────────
        self._effect_scheduler = EffectScheduler()
        self._effect_settings: SpinEffectSettings = default_spin_effect_settings()
        self._effect_callbacks: dict = {}  # EffectKey → Callable[[int], None]
        self._replay_record_effects: bool = True   # v0.6.1: リプレイに演出記録するか

        # ── フレームタイマー ─────────────────────────────────────────
        self._spin_timer: QTimer = QTimer(self)
        self._spin_timer.setInterval(16)  # ~60fps
        self._spin_timer.timeout.connect(self._spin_frame)

    # ================================================================
    #  公開 API
    # ================================================================

    @property
    def is_spinning(self) -> bool:
        return self._spinning or self._multi_delay_timer.isActive()

    # ── スピン設定 setter ────────────────────────────────────────────

    def set_spin_duration(self, duration: float):
        """通常スピン時間を設定する（秒）。"""
        self._spin_duration = max(1.0, float(duration))

    def set_spin_profile(self, profile: str):
        """スピンプロファイルを設定する ('x'/'y'/'z')。"""
        if profile in PRESET_PROFILES_LIST:
            self._spin_profile = profile

    def set_spin_preset_random(self, enabled: bool):
        """毎スピンでプロファイルをランダム抽選するか。"""
        self._spin_preset_random = bool(enabled)

    def set_spin_duration_random(self, enabled: bool):
        """毎スピンで秒数をランダム抽選するか。"""
        self._spin_duration_random = bool(enabled)

    def set_spin_duration_random_ratio(self, ratio: float):
        """終了時間ランダム化割合 (0-0.5)。"""
        self._spin_duration_random_ratio = max(0.0, min(0.5, float(ratio)))

    def set_spin_phase_randomize(self, intensity: float):
        """スピン詳細ランダム化強度 (0-1)。"""
        self._spin_phase_randomize = max(0.0, min(1.0, float(intensity)))

    def set_spin_phase_overrides(self, overrides: dict | None):
        """フェーズ詳細上書き値を設定する。"""
        self._spin_phase_overrides = overrides

    # 後方互換: 旧コードが呼んでいた set_spin_preset を無害化
    def set_spin_preset(self, name: str):
        pass

    def set_spin_mode(self, mode: int):
        self._spin_mode = max(0, min(2, mode))

    def set_double_duration(self, duration: float):
        self._double_duration = max(1.0, float(duration))

    def set_triple_duration(self, duration: float):
        self._triple_duration = max(1.0, float(duration))

    def set_replay_manager(self, mgr):
        self._replay_mgr = mgr

    def set_replay_group_id(self, group_id: str):
        self._replay_group_id = group_id

    def set_sound_tick_enabled(self, enabled: bool):
        self._sound_tick_enabled = enabled

    def set_sound_result_enabled(self, enabled: bool):
        self._sound_result_enabled = enabled

    def set_tick_pattern(self, idx: int):
        self._tick_pattern = idx

    def set_win_pattern(self, idx: int):
        self._win_pattern = idx

    def set_effect_settings(self, settings: "SpinEffectSettings") -> None:
        """特殊演出設定を更新する。"""
        self._effect_settings = settings

    def set_effect_callbacks(self, callbacks: dict) -> None:
        """演出発火コールバックを設定する (EffectKey → Callable[[int], None])。"""
        self._effect_callbacks = callbacks

    def _wrap_callbacks_for_replay(self, callbacks: dict) -> dict:
        """v0.6.1: 演出 callback を replay_record_effects 対応にラップする。

        replay_mgr が記録中かつ replay_record_effects が ON のときに限り、
        発火時に record_effect(key, variant) を挟んでから本体 callback を呼ぶ。
        """
        if self._replay_mgr is None or not getattr(self._replay_mgr, "is_recording", False):
            return callbacks
        # AppSettings.replay_record_effects のフラグは _replay_record_effects 経由で参照
        if not getattr(self, "_replay_record_effects", True):
            return callbacks
        wrapped: dict = {}
        for key, cb in callbacks.items():
            def make_wrapper(k=key, c=cb):
                def wrapper(variant):
                    try:
                        if self._replay_mgr is not None:
                            self._replay_mgr.record_effect(k, variant)
                    except Exception:
                        pass
                    c(variant)
                return wrapper
            wrapped[key] = make_wrapper()
        return wrapped

    def set_replay_record_effects(self, enabled: bool) -> None:
        """v0.6.1: 特殊演出をリプレイに記録するかを設定する。"""
        self._replay_record_effects = bool(enabled)

    def play_result_sound(self):
        """結果SE（win音）を鳴らす（外部から呼ぶ用）。"""
        if self._sound_result_enabled and self._sound:
            self._sound.play_win(self._win_pattern)

    # ================================================================
    #  スピン開始
    # ================================================================

    def start_spin(self, duration: float | None = None):
        """spin を開始する（4段階モデル）。

        マルチスピンモード時は複数回連続実行する。
        着地位置は開始時に事前決定。
        """
        if self._spinning:
            return
        segs = self._wheel._segments
        if len(segs) < 2:
            return

        # マルチスピン初期化 (外部 start_spin 呼び出し時のみ)
        if self._multi_phase == 0:
            if self._spin_mode == 0:
                self._multi_total = 1
            elif self._spin_mode == 1:
                self._multi_total = 2
            else:
                self._multi_total = 3
            if self._replay_mgr is not None:
                grp = self._replay_group_id
                self._replay_group_id = ""
                self._replay_mgr.start_recording(
                    self._wheel._segments,
                    self._wheel._pointer_angle,
                    self._wheel._spin_direction,
                    group_id=grp,
                )

        self._spinning = True
        self.spin_started.emit()

        # ── 当選セグメントを確率比例で事前決定 ──────────────────────
        total_arc = sum(seg.arc for seg in segs)
        r_val = random.uniform(0, total_arc)
        cumulative = 0.0
        target_seg_idx = len(segs) - 1
        for i, seg in enumerate(segs):
            cumulative += seg.arc
            if r_val < cumulative:
                target_seg_idx = i
                break

        target_seg = segs[target_seg_idx]
        seg_arc    = target_seg.arc
        # セグメント内のランダム位置 (端を避けて 15%〜85%)
        seg_offset = target_seg.start_angle + seg_arc * random.uniform(0.15, 0.85)
        # ポインター角度に合わせた目標角度 (度)
        target_angle = (self._wheel._pointer_angle + seg_offset) % 360.0

        # ── スピン方向 ───────────────────────────────────────────────
        spin_sign = 1 if self._wheel._spin_direction == 1 else -1
        current_angle = self._wheel._angle

        if spin_sign == 1:
            needed_residual = (target_angle - current_angle) % 360.0
        else:
            needed_residual = (current_angle - target_angle) % 360.0
        if needed_residual < 18.0:  # 最低 5% の着地余白
            needed_residual += 360.0

        # ── PhaseTimes 生成 (ランダム化含む) ─────────────────────────
        if duration is None:
            duration = self._duration_for_current_phase()

        times = build_phase_times(
            duration_ms=duration * 1000.0,
            profile=self._spin_profile,
            overrides=self._spin_phase_overrides,
            duration_random_ratio=self._spin_duration_random_ratio,
            phase_randomize=self._spin_phase_randomize,
            preset_random=self._spin_preset_random,
            duration_random=self._spin_duration_random,
        )

        # ── 総角度計算 ────────────────────────────────────────────────
        natural_total_deg = rotations_at(times.total_ms, times) * 360.0
        N = max(1, round((natural_total_deg - needed_residual) / 360.0))
        total_deg = N * 360.0 + needed_residual
        angle_scale = (total_deg / natural_total_deg) if natural_total_deg > 0 else 1.0

        # ── スピン状態を保存して開始 ──────────────────────────────────
        self._spin_times       = times
        self._spin_angle_scale = angle_scale
        self._spin_sign        = spin_sign
        self._spin_start_angle = current_angle
        self._spin_end_angle   = current_angle + spin_sign * total_deg

        self._prev_seg_idx   = self._wheel.seg_at_pointer()
        self._spin_start_time = time.perf_counter()

        # ── 特殊演出スケジュール (最終フェーズのみ) ───────────────────
        if self._multi_phase == self._multi_total - 1:
            winner_role = getattr(target_seg, "special_role", None)
            # 通常項目が当選したが、隣接セグメントに target がある場合は期待度演出候補
            if winner_role is None and len(segs) >= 2:
                n = len(segs)
                prev_role = getattr(segs[(target_seg_idx - 1) % n], "special_role", None)
                next_role = getattr(segs[(target_seg_idx + 1) % n], "special_role", None)
                if prev_role == "target" or next_role == "target":
                    winner_role = "expect_candidate"
            if self._effect_callbacks:
                # v0.6.1: リプレイ記録 ON ならコールバックをラップして発火時に record
                cb_dict = self._wrap_callbacks_for_replay(self._effect_callbacks)
                self._effect_scheduler.schedule(
                    winner_role,
                    self._effect_settings,
                    times.total_ms,
                    cb_dict,
                )

        self._spin_timer.start()

    # ================================================================
    #  フレーム更新
    # ================================================================

    def _spin_frame(self):
        """毎フレームの角度更新。経過時間から解析的に角度を計算する。"""
        if self._spin_times is None:
            return

        elapsed_ms = (time.perf_counter() - self._spin_start_time) * 1000.0
        times      = self._spin_times

        if elapsed_ms >= times.total_ms:
            # スピン完了: 終了角度に正確にスナップ
            new_angle = self._spin_end_angle % 360.0
            self._wheel.set_angle(new_angle)
            if self._replay_mgr is not None:
                self._replay_mgr.record_frame(new_angle)
            self._spin_finish()
            return

        # 解析積分で現在角度を算出
        revolutions = rotations_at(elapsed_ms, times)
        new_angle = (
            self._spin_start_angle
            + self._spin_sign * revolutions * 360.0 * self._spin_angle_scale
        ) % 360.0
        self._wheel.set_angle(new_angle)

        if self._replay_mgr is not None:
            self._replay_mgr.record_frame(new_angle)

        # tick 音: セグメント境界を越えたら鳴らす
        if self._sound_tick_enabled and self._sound:
            cur_seg = self._wheel.seg_at_pointer()
            if cur_seg != self._prev_seg_idx:
                self._sound.play_tick(self._tick_pattern)
                self._prev_seg_idx = cur_seg
                if self._replay_mgr is not None:
                    self._replay_mgr.record_sound("tick")

    # ================================================================
    #  内部ヘルパー
    # ================================================================

    def _duration_for_current_phase(self) -> float:
        """現在のマルチスピンフェーズに応じたスピン時間（秒）を返す。"""
        if self._multi_total == 1:
            return self._spin_duration
        elif self._multi_total == 2:
            return self._double_duration
        else:
            return self._triple_duration

    def _start_next_phase(self):
        """マルチスピンの次フェーズを開始する。"""
        self.start_spin()

    def _spin_finish(self):
        """スピン停止・結果確定。"""
        self._spin_timer.stop()
        self._spinning = False
        self._spin_times = None

        self._multi_phase += 1

        # マルチスピン途中フェーズ: 決定音を鳴らして次フェーズへ
        if self._multi_phase < self._multi_total:
            if self._sound_result_enabled and self._sound:
                self._sound.play_win(self._win_pattern)
                if self._replay_mgr is not None:
                    self._replay_mgr.record_sound("win")
            self._multi_delay_timer.start()
            return

        # 最終フェーズ: 結果確定
        self._multi_phase = 0

        if self._sound_result_enabled and self._sound:
            self._sound.play_win(self._win_pattern)
            if self._replay_mgr is not None:
                self._replay_mgr.record_sound("win")

        seg_idx = self._wheel.seg_at_pointer()
        segs = self._wheel._segments
        if 0 <= seg_idx < len(segs):
            winner = segs[seg_idx].item_text
        else:
            winner = ""

        if self._replay_mgr is not None:
            self._replay_mgr.finish_recording(
                winner, seg_idx, self._wheel._angle
            )

        self.spin_finished.emit(winner, seg_idx)
