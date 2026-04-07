"""
PySide6 プロトタイプ — スピン制御

WheelWidget のスピン物理（開始・フレーム更新・停止）を分離したコントローラー。
WheelWidget は描画に専念し、SpinController が角度を駆動する。

責務:
  - spin 開始 / 停止の状態管理
  - 多段階減速の物理演算（プリセットベース）
  - 結果セグメントの事前決定
  - spin_finished シグナルの発行

今後の拡張ポイント:
  - ダブルタップ / トリプルタップ停止
  - リプレイ記録フック
  - 常時ランダム配置との連携
"""

import random
from PySide6.QtCore import QObject, QTimer, Signal

from spin_preset import (
    SpinPreset, SPIN_PRESETS, DEFAULT_PRESET_NAME, V_STOP,
)


class SpinController(QObject):
    """スピンの物理演算と状態を管理する。

    WheelWidget への依存は最小限:
      - wheel.angle (現在角度の取得)
      - wheel.set_angle() (角度の更新)
      - wheel.seg_at_pointer() (結果判定)
      - wheel.segments (セグメント情報)

    Signals:
        spin_started: spin が開始された
        spin_finished(str, int): spin 完了時に (winner_text, seg_index) を emit
    """

    spin_started = Signal()
    spin_finished = Signal(str, int)

    def __init__(self, wheel, parent=None):
        super().__init__(parent)
        self._wheel = wheel

        # --- spin 状態 ---
        self._spinning: bool = False
        self._velocity: float = 0.0
        self._spin_sign: int = 1
        self._cruise_decel: float = 1.0

        # --- プリセット ---
        self._spin_preset: SpinPreset = SPIN_PRESETS[DEFAULT_PRESET_NAME]

        # --- タイマー ---
        self._spin_timer: QTimer = QTimer(self)
        self._spin_timer.setInterval(16)  # ~60fps
        self._spin_timer.timeout.connect(self._spin_frame)

    # ================================================================
    #  公開 API
    # ================================================================

    @property
    def is_spinning(self) -> bool:
        return self._spinning

    @property
    def preset_name(self) -> str:
        return self._spin_preset.name

    def set_spin_preset(self, preset_name: str):
        """spin プリセットを切り替える。"""
        if preset_name in SPIN_PRESETS:
            self._spin_preset = SPIN_PRESETS[preset_name]

    def start_spin(self, duration: float | None = None):
        """spin を開始する（プリセットベース多段階減速）。

        着地位置は事前計算で確定済み。
        """
        if self._spinning:
            return
        segs = self._wheel._segments
        if len(segs) < 2:
            return

        self._spinning = True
        self.spin_started.emit()

        preset = self._spin_preset
        if duration is None:
            duration = preset.duration

        target_frames = max(1, duration * 1000 / 16)

        # 結果を先行決定（確率比例ランダム）
        r_val = random.uniform(0, 360)
        cumulative = 0.0
        target_seg = len(segs) - 1
        for i, seg in enumerate(segs):
            cumulative += seg.arc
            if r_val < cumulative:
                target_seg = i
                break
        seg_start = cumulative - segs[target_seg].arc
        seg_arc = segs[target_seg].arc
        target_offset = seg_start + seg_arc * random.uniform(0.15, 0.85)
        target_angle = (self._wheel._pointer_angle + target_offset) % 360

        # --- 固定フェーズの合計フレーム・距離を事前計算 ---
        fixed_frames, fixed_dist = preset.fixed_phases_stats()

        # CRUISE フェーズのフレーム予算
        cruise_frames = max(1, target_frames - fixed_frames)

        # CRUISE -> 最初の固定フェーズの入口速度
        if preset.fixed_phases:
            v_cruise_exit = preset.fixed_phases[0].v_threshold
        else:
            v_cruise_exit = V_STOP

        # 回転数の基準を計算
        v_ref = preset.v_ref
        d_ref = (v_cruise_exit / v_ref) ** (1.0 / cruise_frames)
        if d_ref < 1.0:
            ref_cruise_dist = v_ref * (1.0 - d_ref ** cruise_frames) / (1.0 - d_ref)
        else:
            ref_cruise_dist = v_ref * cruise_frames
        ref_total = ref_cruise_dist + fixed_dist
        base_rots = max(3, int(ref_total / 360))

        spin_sign = -1 if self._wheel._spin_direction == 1 else 1
        current_angle = self._wheel._angle
        if spin_sign == 1:
            needed_residual = (target_angle - current_angle) % 360
        else:
            needed_residual = (current_angle - target_angle) % 360
        adjusted_total = base_rots * 360 + needed_residual

        # CRUISE フェーズで必要な距離
        cruise_dist_needed = adjusted_total - fixed_dist

        # v0 を二分探索（CRUISE 距離を合わせる）
        def cruise_total_for_v(v0):
            d = (v_cruise_exit / v0) ** (1.0 / cruise_frames)
            if d >= 1.0:
                return v0 * cruise_frames
            return v0 * (1.0 - d ** cruise_frames) / (1.0 - d)

        lo, hi = v_cruise_exit + 0.01, 300.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if cruise_total_for_v(mid) < cruise_dist_needed:
                lo = mid
            else:
                hi = mid
        self._velocity = (lo + hi) / 2
        self._cruise_decel = (v_cruise_exit / self._velocity) ** (1.0 / cruise_frames)
        self._spin_sign = spin_sign

        self._spin_timer.start()

    # ================================================================
    #  内部フレーム更新
    # ================================================================

    def _spin_frame(self):
        """毎フレームの回転更新（プリセットベース多段階減速）。"""
        new_angle = (self._wheel._angle + self._spin_sign * self._velocity) % 360
        self._wheel.set_angle(new_angle)

        decel = self._spin_preset.decel_for_velocity(
            self._velocity, self._cruise_decel
        )
        self._velocity *= decel

        if self._velocity < V_STOP:
            self._spin_finish()

    def _spin_finish(self):
        """spin 停止・結果確定。"""
        self._spin_timer.stop()
        self._spinning = False

        seg_idx = self._wheel.seg_at_pointer()
        segs = self._wheel._segments
        if 0 <= seg_idx < len(segs):
            winner = segs[seg_idx].item_text
        else:
            winner = ""
        self.spin_finished.emit(winner, seg_idx)
