"""
PySide6 プロトタイプ — spin プリセット定義

6段階のフェーズ構造:
  1. START      — spin 開始直後の初期挙動
  2. ACCEL      — 高速域へ乗るまでの加速
  3. CRUISE     — 主回転区間（高速維持）
  4. DECEL      — 明確に減速へ入る区間
  5. LINGER     — 低速で尾を引く余韻区間
  6. STOP       — 結果確定して止まる区間

現時点では、各段階を「速度閾値 + 減衰率」で表現する。
CRUISE フェーズの減衰率のみ実行時に逆算（総距離・総時間を合わせるため）。
それ以下のフェーズは固定パラメータ。

将来的には各段階を UI から個別編集できるように拡張する想定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# 全プリセット共通の停止閾値
V_STOP = 0.06


@dataclass
class SpinPhase:
    """1 フェーズのパラメータ。

    Attributes:
        name: フェーズ名（表示・デバッグ用）
        v_threshold: この速度以下でこのフェーズに入る（CRUISE は上限なし）
        decel: 減衰率（1.0 に近いほど緩やか）。CRUISE は実行時に逆算。
    """
    name: str
    v_threshold: float
    decel: float


@dataclass
class SpinPreset:
    """spin プリセット。

    phases は CRUISE（最高速）→ STOP 方向に、v_threshold 降順で並べる。
    phases[0] は CRUISE 相当で、decel は実行時に逆算される（ここの値は初期参考値）。

    Attributes:
        name: プリセット表示名
        duration: 総時間（秒）
        phases: フェーズリスト（v_threshold 降順）
        v_ref: 回転数算出の基準速度（低いほどピーク速度が下がる）
    """
    name: str
    duration: float
    phases: list[SpinPhase] = field(default_factory=list)
    v_ref: float = 25.0

    @property
    def cruise_phase(self) -> SpinPhase:
        """最高速フェーズ（phases[0]）を返す。"""
        return self.phases[0]

    @property
    def fixed_phases(self) -> list[SpinPhase]:
        """CRUISE 以下の固定フェーズを返す。"""
        return self.phases[1:]

    def fixed_phases_stats(self) -> tuple[int, float]:
        """固定フェーズ群の合計フレーム数・合計距離を計算する。

        Returns:
            (total_frames, total_distance)
        """
        total_frames = 0
        total_dist = 0.0

        for i, phase in enumerate(self.fixed_phases):
            v_enter = phase.v_threshold
            # 次フェーズの閾値、なければ V_STOP
            if i + 1 < len(self.fixed_phases):
                v_exit = self.fixed_phases[i + 1].v_threshold
            else:
                v_exit = V_STOP

            if v_enter <= v_exit or phase.decel >= 1.0:
                continue

            frames = max(1, math.ceil(
                math.log(v_exit / v_enter) / math.log(phase.decel)
            ))
            dist = 0.0
            v = v_enter
            for _ in range(frames):
                dist += v
                v *= phase.decel

            total_frames += frames
            total_dist += dist

        return total_frames, total_dist

    def decel_for_velocity(self, velocity: float, cruise_decel: float) -> float:
        """現在の速度に対応する減衰率を返す。

        fixed_phases は v_threshold 降順。velocity が閾値以下なら
        そのフェーズの decel を候補にし、超えた時点で確定する。

        Args:
            velocity: 現在の速度
            cruise_decel: 実行時に逆算された CRUISE 用減衰率

        Returns:
            適用すべき減衰率
        """
        result = cruise_decel
        for phase in self.fixed_phases:
            if velocity <= phase.v_threshold:
                result = phase.decel
            else:
                break
        return result


# ====================================================================
#  プリセット定義
# ====================================================================

PRESET_9S = SpinPreset(
    name="9秒 (Standard)",
    duration=9.0,
    phases=[
        # CRUISE — 高速主回転（decel は実行時に逆算）
        SpinPhase(name="cruise",  v_threshold=999.0, decel=0.992),
        # LINGER — 停止余韻
        SpinPhase(name="linger",  v_threshold=1.0,   decel=0.985),
    ],
)

PRESET_15S = SpinPreset(
    name="15秒 (Dramatic)",
    duration=15.0,
    phases=[
        # CRUISE — 短めの高速回転（decel は実行時に逆算、~3-4秒）
        SpinPhase(name="cruise",      v_threshold=999.0, decel=0.996),
        # DECEL — 早めに入る緩やかな減速（~7-8秒、tail-heavy の主区間）
        SpinPhase(name="decel_start", v_threshold=5.0,   decel=0.996),
        # LINGER — 低速で長く這う余韻（~2-3秒）
        SpinPhase(name="linger",      v_threshold=0.8,   decel=0.992),
        # CREEP — 最終停止直前の微速（~2秒、微粘り強化）
        SpinPhase(name="creep",       v_threshold=0.2,   decel=0.989),
    ],
    v_ref=18.0,  # ピーク速度を抑える（デフォルト25.0より低い）
)

# 利用可能プリセット一覧
SPIN_PRESETS: dict[str, SpinPreset] = {
    PRESET_9S.name: PRESET_9S,
    PRESET_15S.name: PRESET_15S,
}

SPIN_PRESET_NAMES: list[str] = list(SPIN_PRESETS.keys())

DEFAULT_PRESET_NAME: str = PRESET_9S.name
