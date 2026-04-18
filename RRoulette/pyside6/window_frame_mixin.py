"""
window_frame_mixin.py — frameless ウィンドウ helper + イベントハンドラ Mixin

i450: main_window.py から分離。
責務:
  - ウィンドウフラグ適用 (_apply_window_flags)
  - Windows DWM ボーダーレス設定 (_dwm_set_borderless)
  - centralWidget 背景塗り切替 (_apply_central_background)
  - エッジリサイズ検出 (_edge_at, _update_edge_cursor)
  - mouse / keyboard / wheel イベントハンドラ
      keyPressEvent, mousePressEvent, mouseMoveEvent,
      mouseReleaseEvent, wheelEvent

使用側:
  class MainWindow(WindowFrameMixin, ContextMenuMixin, UIToggleMixin, ..., QMainWindow)
"""

import ctypes

from PySide6.QtCore import Qt

from roulette_actions import AddRoulette, RemoveRoulette, SetActiveRoulette


class WindowFrameMixin:
    """frameless ウィンドウ操作ロジックとイベントハンドラの責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    _EDGE_SIZE / _EDGE_NONE / _EDGE_RIGHT / _EDGE_BOTTOM / _EDGE_CORNER は
    MainWindow クラス変数として定義されており、self.* 経由で解決される。
    """

    # ================================================================
    #  window / frame helpers
    # ================================================================

    def _apply_window_flags(self):
        """always_on_top の設定に基づいてウィンドウフラグを適用する。"""
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if self._settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    @staticmethod
    def _dwm_set_borderless(hwnd: int, enabled: bool):
        """Windows DWM レベルで外周枠・角丸・影を完全除去する。

        Windows 11 では FramelessWindowHint + NoDropShadowWindowHint だけでは
        DWM が 1px ボーダーと角丸を描画し続ける。
        DwmSetWindowAttribute で直接属性を書き換えることで完全に除去できる。

        Args:
            hwnd: ウィンドウハンドル（winId() の整数値）
            enabled: True = 枠なし状態にする / False = デフォルト値に戻す
        """
        try:
            dwmapi = ctypes.windll.dwmapi
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33
            # DWMWCP_DONOTROUND = 1, DWMWCP_DEFAULT = 0
            corner_val = 1 if enabled else 0
            dwmapi.DwmSetWindowAttribute(
                hwnd, 33,
                ctypes.byref(ctypes.c_uint(corner_val)),
                ctypes.sizeof(ctypes.c_uint),
            )
            # DWMWA_BORDER_COLOR = 35
            # DWMWA_COLOR_NONE = 0xFFFFFFFE, DWMWA_COLOR_DEFAULT = 0xFFFFFFFF
            border_val = 0xFFFFFFFE if enabled else 0xFFFFFFFF
            dwmapi.DwmSetWindowAttribute(
                hwnd, 35,
                ctypes.byref(ctypes.c_uint(border_val)),
                ctypes.sizeof(ctypes.c_uint),
            )
        except Exception:
            pass  # Windows 以外 / 非対応バージョン

    def _apply_central_background(self, transparent: bool):
        """centralWidget の塗りつぶしのみを切り替える。

        QMainWindow 自身は常時 WA_TranslucentBackground 状態。実際の
        透過/不透明は centralWidget の stylesheet の background-color で
        切り替える。これなら native window 再生成が不要なので、
        実行時トグルが安定して反映される。
        """
        central = self.centralWidget()
        if not central:
            return
        if transparent:
            central.setStyleSheet("background-color: transparent;")
        else:
            central.setStyleSheet(
                f"background-color: {self._design.bg};"
            )

    # ================================================================
    #  frameless ウィンドウ — エッジリサイズ
    # ================================================================

    def _edge_at(self, pos) -> int:
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        edge = self._EDGE_NONE
        if x >= w - self._EDGE_SIZE:
            edge |= self._EDGE_RIGHT
        if y >= h - self._EDGE_SIZE:
            edge |= self._EDGE_BOTTOM
        return edge

    def _update_edge_cursor(self, pos):
        edge = self._edge_at(pos)
        if edge == self._EDGE_CORNER:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge == self._EDGE_RIGHT:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == self._EDGE_BOTTOM:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    # ================================================================
    #  入力操作
    #
    #  パネル内のクリックは各パネルが自身で処理する。
    #  MainWindow に届くのは:
    #    - エッジ領域（リサイズ）
    #    - 背景領域（ウィンドウドラッグ移動）
    #    - キーボードイベント
    # ================================================================

    def keyPressEvent(self, event):
        mods = event.modifiers()
        ctrl_shift = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
        )

        if event.key() == Qt.Key.Key_Escape:
            # テキスト編集モード中ならキャンセル（ESC でのアプリ終了は廃止）
            if (hasattr(self, '_item_panel')
                    and self._item_panel.is_text_edit_mode()):
                self._item_panel.cancel_text_edit()
        elif event.key() == Qt.Key.Key_F1:
            self._toggle_manage_panel()
        elif event.key() == Qt.Key.Key_F2:
            self._toggle_item_panel()
        elif event.key() == Qt.Key.Key_F3:
            self._toggle_settings_panel_v2()
        # Space は _SpaceSpinFilter (QApplication レベル) が処理するため
        # ここには届かない。keyPressEvent での処理は廃止 (i344)。
        # --- 開発用ショートカット（アクション経由） ---
        elif event.key() == Qt.Key.Key_N and (mods & ctrl_shift) == ctrl_shift:
            self.apply_action(AddRoulette())
        elif event.key() == Qt.Key.Key_W and (mods & ctrl_shift) == ctrl_shift:
            self.apply_action(RemoveRoulette(self._manager.active_id))
        elif event.key() == Qt.Key.Key_Period and (mods & ctrl_shift) == ctrl_shift:
            nxt = self._manager.next_id(self._manager.active_id)
            if nxt:
                self.apply_action(SetActiveRoulette(nxt))
        elif event.key() == Qt.Key.Key_Comma and (mods & ctrl_shift) == ctrl_shift:
            prv = self._manager.prev_id(self._manager.active_id)
            if prv:
                self.apply_action(SetActiveRoulette(prv))
        # --- 開発用ショートカット（記録） ---
        elif event.key() == Qt.Key.Key_R and (mods & ctrl_shift) == ctrl_shift:
            self._toggle_recording()
        elif event.key() == Qt.Key.Key_L and (mods & ctrl_shift) == ctrl_shift:
            self._dump_recording()
        # --- 開発用ショートカット（保存/読込/再生） ---
        elif event.key() == Qt.Key.Key_S and (mods & ctrl_shift) == ctrl_shift:
            self._dev_save_recording()
        elif event.key() == Qt.Key.Key_O and (mods & ctrl_shift) == ctrl_shift:
            self._dev_load_to_session()
        elif event.key() == Qt.Key.Key_P and (mods & ctrl_shift) == ctrl_shift:
            self._dev_step_action()
        elif event.key() == Qt.Key.Key_K and (mods & ctrl_shift) == ctrl_shift:
            self._dev_clear_session()
        elif event.key() == Qt.Key.Key_G and (mods & ctrl_shift) == ctrl_shift:
            self._dev_run_until_pause()
        elif event.key() == Qt.Key.Key_V and (mods & ctrl_shift) == ctrl_shift:
            self._dev_show_action_viewer()
        else:
            super().keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()

            # エッジリサイズ
            edge = self._edge_at(pos)
            if edge:
                self._resizing_edge = edge
                self._resize_start = event.globalPosition().toPoint()
                self._resize_start_rect = self.geometry()
                event.accept()
                return

            # 背景ドラッグ → ウィンドウ移動
            self._dragging_window = True
            self._window_drag_start = event.globalPosition().toPoint()
            self._window_drag_start_pos = self.pos()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing_edge:
            delta = event.globalPosition().toPoint() - self._resize_start
            rect = self._resize_start_rect
            new_w = rect.width()
            new_h = rect.height()
            if self._resizing_edge & self._EDGE_RIGHT:
                new_w = max(self.minimumWidth(), rect.width() + delta.x())
            if self._resizing_edge & self._EDGE_BOTTOM:
                new_h = max(self.minimumHeight(), rect.height() + delta.y())
            self.resize(new_w, new_h)
            event.accept()
            return

        if self._dragging_window:
            delta = event.globalPosition().toPoint() - self._window_drag_start
            self.move(self._window_drag_start_pos + delta)
            event.accept()
            return

        # ボタン非押下時: エッジカーソル更新
        if not event.buttons():
            self._update_edge_cursor(event.pos())
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resizing_edge:
                self._resizing_edge = self._EDGE_NONE
                event.accept()
                return
            if self._dragging_window:
                self._dragging_window = False
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """パネル外でのマウスホイール回転を無効化する。"""
        event.accept()
