"""
PySide6 プロトタイプ — ルーレットパネル

ルーレット描画と操作を一体化した独立パネル。
メインウィンドウ内で自由に移動・リサイズできる。

将来のマルチルーレット化では、このクラスを複数インスタンス化する。
各 RoulettePanel は自身の segments、spin 状態を持ち、
項目設定パネルは「アクティブな RoulettePanel」を編集する形にする。

責務:
  - WheelWidget の表示管理
  - SpinController の保持・制御
  - ResultOverlay の管理
  - パネル内マウス操作（spin 開始、ポインタードラッグ、パネル移動）
  - パネルリサイズ（右下つまみ）

マウス操作の優先順位:
  1. ポインター上 → ポインタードラッグ
  2. ホイール円内 → spin 開始
  3. それ以外の空き領域 → パネル移動
"""

from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from bridge import (
    DesignSettings, WHEEL_OUTER_MARGIN, MIN_R, POINTER_OVERHANG,
)
from wheel_widget import WheelWidget
from spin_controller import SpinController
from result_overlay import ResultOverlay
from settings_panel import _PanelGrip


# ホイール + ポインター + 余白を含むパネル最小サイズ
# = 2 * (MIN_R + WHEEL_OUTER_MARGIN) + grip余白
_ROULETTE_MIN = 2 * (MIN_R + WHEEL_OUTER_MARGIN) + _PanelGrip._GRIP_SIZE
_ROULETTE_MIN_W = max(280, _ROULETTE_MIN)
_ROULETTE_MIN_H = max(280, _ROULETTE_MIN)


class RoulettePanel(QFrame):
    """独立パネルとしてのルーレット。

    Signals:
        spin_requested: spin 開始が要求された
        spin_finished(str, int): spin が完了した (winner, seg_idx)
        pointer_angle_changed(float): ポインター角度がドラッグ中に変更された
        pointer_angle_committed: ポインタードラッグ完了（保存タイミング）
        geometry_changed: パネルの位置/サイズが変わった
    """

    spin_requested = Signal()
    spin_finished = Signal(str, int)
    pointer_angle_changed = Signal(float)
    pointer_angle_committed = Signal()
    geometry_changed = Signal()
    activate_requested = Signal(str)

    _MIN_W = _ROULETTE_MIN_W
    _MIN_H = _ROULETTE_MIN_H

    def __init__(self, design: DesignSettings, sound_manager, *,
                 roulette_id: str = "default", parent=None):
        super().__init__(parent)
        self._roulette_id = roulette_id
        self._design = design
        self.setStyleSheet(f"background-color: {design.bg};")
        self.setMinimumSize(self._MIN_W, self._MIN_H)

        # ── WheelWidget（パネル全体に配置） ──
        self._wheel = WheelWidget(self)

        # ── スピン制御 ──
        self._spin_ctrl = SpinController(
            self._wheel, sound_manager=sound_manager, parent=self
        )
        self._spin_ctrl.spin_finished.connect(self._on_spin_finished)

        # ── 結果オーバーレイ ──
        self._result_overlay = ResultOverlay(self)
        self._result_overlay.apply_style(design)

        # ── リサイズグリップ ──
        self._grip = _PanelGrip(
            self, design, mode="panel",
            min_w=self._MIN_W, min_h=self._MIN_H,
            parent=self,
        )

        # ── パネル前後関係 ──
        self.pinned_front = False  # True: 通常パネルより常に上に表示

        # ── ドラッグ状態 ──
        self._dragging_pointer = False
        self._dragging_panel = False
        self._drag_pending = False      # press 後、drag か click かの判定待ち
        self._press_zone = "outside"    # press 時のヒットゾーン
        self._panel_drag_start = QPoint()
        self._panel_start_pos = QPoint()

    # ================================================================
    #  公開プロパティ
    # ================================================================

    @property
    def roulette_id(self) -> str:
        return self._roulette_id

    @property
    def wheel(self) -> WheelWidget:
        return self._wheel

    @property
    def spin_ctrl(self) -> SpinController:
        return self._spin_ctrl

    @property
    def result_overlay(self) -> ResultOverlay:
        return self._result_overlay

    # ================================================================
    #  設定適用
    # ================================================================

    def apply_settings(self, settings, design):
        """AppSettings と DesignSettings を WheelWidget に一括配布する。"""
        self._wheel.set_design(design)
        self._wheel.set_text_mode(settings.text_size_mode, settings.text_direction)
        self._wheel.set_donut_hole(settings.donut_hole)
        self._wheel.set_pointer_angle(settings.pointer_angle)
        self._wheel._spin_direction = settings.spin_direction

    def set_segments(self, segments):
        """ルーレットのセグメントを設定する。"""
        self._wheel.set_segments(segments)

    def update_design(self, design: DesignSettings):
        """デザイン変更時にパネル全体の配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.bg};")
        self._wheel.set_design(design)
        self._result_overlay.apply_style(design)
        self._grip.update_design(design)

    # ================================================================
    #  スピン
    # ================================================================

    def start_spin(self):
        """スピンを開始する。"""
        if self._spin_ctrl.is_spinning:
            return
        self._result_overlay.dismiss()
        self._spin_ctrl.start_spin()

    def _on_spin_finished(self, winner: str, seg_idx: int):
        self._result_overlay.show_result(winner)
        self.spin_finished.emit(winner, seg_idx)

    # ================================================================
    #  ジオメトリ同期・クランプ
    # ================================================================

    def _sync_wheel(self):
        """パネルサイズに WheelWidget を合わせる。"""
        self._wheel.setGeometry(0, 0, self.width(), self.height())
        self._result_overlay.update_position()

    def _clamp_to_parent(self):
        """パネルをメインウィンドウのクライアント領域内にクランプする。"""
        parent = self.parentWidget()
        if not parent:
            return
        x = max(0, min(self.x(), parent.width() - self.width()))
        y = max(0, min(self.y(), parent.height() - self.height()))
        if x != self.x() or y != self.y():
            self.move(x, y)

    # ================================================================
    #  イベント
    # ================================================================

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_wheel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_wheel()
        self._grip.reposition()
        self._clamp_to_parent()
        self.geometry_changed.emit()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def mousePressEvent(self, event):
        """パネル内マウス押下。クリックしたパネルを最前面へ。

        ドラッグ挙動:
          - ポインター上でドラッグ開始 → ポインター移動
          - それ以外でドラッグ開始 → パネル全体の移動
        クリック挙動（ドラッグなし、press 位置で判定）:
          - 結果表示中 → 結果表示を閉じる（spin より優先）
          - wheel_face → spin 開始
          - pointer / outside → 何もしない
        """
        self.raise_()
        self.activate_requested.emit(self._roulette_id)

        if event.button() == Qt.MouseButton.LeftButton:
            wheel_pos = self._wheel.mapFrom(self, event.pos())
            zone = self._wheel.hit_zone(wheel_pos.x(), wheel_pos.y())

            # ポインター上 → ポインタードラッグ（最優先）
            if not self._spin_ctrl.is_spinning and zone == "pointer":
                self._dragging_pointer = True
                event.accept()
                return

            # それ以外 → ドラッグ待ち（閾値超でパネル移動、未満でクリック判定）
            self._drag_pending = True
            self._dragging_panel = False
            self._press_zone = zone
            self._panel_drag_start = event.globalPosition().toPoint()
            self._panel_start_pos = self.pos()
            event.accept()
            return

        event.accept()

    def mouseMoveEvent(self, event):
        # ポインタードラッグ中
        if self._dragging_pointer:
            wheel_pos = self._wheel.mapFrom(self, event.pos())
            angle = self._wheel.angle_from_pos(wheel_pos.x(), wheel_pos.y())
            self._wheel.set_pointer_angle(angle)
            self.pointer_angle_changed.emit(angle)
            event.accept()
            return

        # パネル移動の判定・実行
        if self._drag_pending or self._dragging_panel:
            delta = event.globalPosition().toPoint() - self._panel_drag_start
            # 閾値を超えたらドラッグ確定
            if self._drag_pending and (abs(delta.x()) > 4 or abs(delta.y()) > 4):
                self._dragging_panel = True
                self._drag_pending = False
            if self._dragging_panel:
                new_pos = self._panel_start_pos + delta
                parent = self.parentWidget()
                if parent:
                    new_x = max(0, min(new_pos.x(), parent.width() - self.width()))
                    new_y = max(0, min(new_pos.y(), parent.height() - self.height()))
                    self.move(new_x, new_y)
            event.accept()
            return

        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # ポインタードラッグ完了
            if self._dragging_pointer:
                self._dragging_pointer = False
                self.pointer_angle_committed.emit()
                event.accept()
                return

            # クリック判定（閾値内で離された = ドラッグにならなかった）
            if self._drag_pending:
                self._drag_pending = False
                zone = self._press_zone
                # 結果表示中 → 閉じる（spin より優先）
                if self._result_overlay.isVisible():
                    self._result_overlay.dismiss()
                # wheel_face クリック → spin 開始
                elif zone == "wheel_face" and not self._spin_ctrl.is_spinning:
                    self.spin_requested.emit()
                # pointer / outside → 何もしない
                event.accept()
                return

            # パネル移動完了
            if self._dragging_panel:
                self._dragging_panel = False
                event.accept()
                return

        event.accept()

    def wheelEvent(self, event):
        """ホイール内のマウスホイール回転を無効化する。"""
        event.accept()
