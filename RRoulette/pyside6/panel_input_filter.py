"""
panel_input_filter.py — パネル入力フィルタ

i436: main_window.py から分離。
責務: パネルのドラッグ移動・リサイズ・フォーカス管理用 QApplication レベルフィルタ。

PANEL_BAR_HEIGHT はメインウィンドウのドラッグバー高さと一致させる必要がある。
変更する場合は _MainWindowDragBar._BAR_HEIGHT も合わせて変更すること。
"""

from PySide6.QtCore import Qt, QPoint, QPointF, QObject, QEvent
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
    QSlider, QScrollBar, QAbstractItemView,
)

from panel_widgets import _PanelGrip

# メインウィンドウドラッグバーの高さ。
# _MainWindowDragBar._BAR_HEIGHT と同値に保つこと。
PANEL_BAR_HEIGHT = 20


class PanelInputFilter(QObject):
    """i278/i279/i280: メインウィンドウ内パネル用の統一マウスフィルタ。

    QApplication 全体に install され、対象パネル (settings / item / manage)
    およびその子ウィジェットへ届く左マウス操作を以下のルールで扱う。

    i280 改訂のポイント:
    - **非アクティブパネル上の UI クリックを 1 回で通す**: press を吸収せず、
      focus を立てた上で素通しする。これによりインアクティブパネル上の
      ボタン/チェック/コンボ等が初回クリックでそのまま動作する。
    - **リサイズ判定をドラッグより優先**: panel の右端 / 下端 / 右下角の
      RESIZE_EDGE 内で press された場合、ドラッグ昇格判定に入る前に
      リサイズトラッキングを開始する。
    - **カーソルプレビュー**: press されていない状態で対象パネルの
      右端 / 下端 / 角にホバーしたら resize cursor を表示する。
    - **ルーレットパネルはフィルタ非対象**: ルーレットパネルは自前の
      mousePressEvent に内蔵のドラッグ/クリック判定があるため、フィルタは
      触らない (focus_only 登録もしない)。

    各イベントの扱い:

    1. **MouseMove (no button)**: press 中でない時は、対象パネル背景上に
       いる場合のみ resize cursor のプレビューを行う。

    2. **MouseButtonPress**:
       a. 対象パネルでなければ素通し。
       b. _PanelGrip 上ならフィルタは触らない (grip 自身が処理)。
       c. 入力系 (QLineEdit/QSpinBox 等) なら focus だけ立てて素通し。
       d. 右端 / 下端 / 角にいたら、focus を立ててリサイズトラッキング開始
          (press は吸収して return True)。
       e. それ以外は focus を立てて、ドラッグ追跡を開始しつつ press を
          素通し (return False)。

    3. **MouseMove (button held)**:
       - リサイズ中: 開始時の geometry + delta から resize() を適用。
       - ドラッグ追跡中: 移動量が DRAG_THRESHOLD を超えたら、
         元 target へ画面外 release を sendEvent して press 状態をキャンセル
         し、popup を hide してパネル移動へ昇格する。

    4. **MouseButtonRelease**:
       - リサイズ中: トラッキング終了。
       - ドラッグ済: 吸収してクリックを発火させない。
       - ドラッグ未昇格: 素通し → 元のウィジェットの通常クリック動作。

    5. **テキスト入力系**: QLineEdit / QPlainTextEdit / QSpinBox 等は
       「press + 移動」を本来動作で使うため、ドラッグ追跡対象外。
       focus は更新するが、press はそのまま素通しする。

    6. **_PanelGrip**: パネル右下の corner グリップ。自前のドラッグ resize
       を持つため、フィルタは press / move / release のいずれも触らない。
    """

    DRAG_THRESHOLD = 6  # manhattan px
    RESIZE_EDGE = 6     # px from right/bottom for resize hit zone

    # ドラッグ追跡から除外する widget 型
    EXEMPT_TYPES = (
        QLineEdit, QPlainTextEdit, QTextEdit,
        QSpinBox, QDoubleSpinBox,
        QSlider, QScrollBar,
        QAbstractItemView,
    )

    def __init__(self, main_window):
        super().__init__(main_window)
        self._mw = main_window
        self._drag_panels: list[QWidget] = []
        self._focus_only_panels: list[QWidget] = []
        # press 追跡状態
        self._press_panel: QWidget | None = None
        self._press_global = QPoint()
        self._press_panel_pos = QPoint()
        self._press_target: QWidget | None = None
        self._dragging = False
        self._cancelling = False  # 同期 sendEvent の再入防止
        # i280: リサイズトラッキング状態
        self._resize_panel: QWidget | None = None
        self._resize_edge = ""  # 'right' / 'bottom' / 'corner' / ''
        self._resize_start_global = QPoint()
        self._resize_start_geom = None  # QRect
        # i282: 現在 push 中の override cursor の種類
        self._active_override_edge = ""

    def set_panels(self, drag_panels, focus_only_panels=()):
        """監視対象パネルを設定する。

        Args:
            drag_panels: drag-from-anywhere + focus-first-click 対象。
            focus_only_panels: focus-first-click のみ対象 (i280 では空でよい)。
        """
        self._drag_panels = list(drag_panels)
        self._focus_only_panels = list(focus_only_panels)
        # i280/i281: 対象パネル+全子ウィジェットで mouseTracking を有効化。
        # これによりボタン/コンボ/スクロール等の上にホバーしている時も
        # MouseMove (no button) が発火し、フィルタが resize cursor を
        # プレビューできる (非アクティブパネルでも有効)。
        for p in self._drag_panels:
            self._enable_tracking_recursive(p)

    @staticmethod
    def _enable_tracking_recursive(widget):
        """widget とその全子孫 QWidget で setMouseTracking(True) を呼ぶ。"""
        try:
            widget.setMouseTracking(True)
        except Exception:
            pass
        try:
            for child in widget.findChildren(QWidget):
                try:
                    child.setMouseTracking(True)
                except Exception:
                    pass
        except Exception:
            pass

    def _find_panel(self, obj) -> tuple[QWidget | None, bool]:
        """obj が監視対象パネルか祖先かを判定。

        Returns:
            (panel, has_drag) — panel が見つからなければ (None, False)。
            has_drag は drag-from-anywhere を許可するかどうか。
        """
        if not isinstance(obj, QWidget):
            return None, False
        w = obj
        depth = 0
        while w is not None and depth < 64:
            if w in self._drag_panels:
                return w, True
            if w in self._focus_only_panels:
                return w, False
            w = w.parentWidget()
            depth += 1
        return None, False

    def _is_exempt(self, obj) -> bool:
        """obj が drag 追跡から除外されるべき型か判定する。

        obj 自身またはその直近の祖先 (3 段) のいずれかが除外型なら True。
        QComboBox の中の QLineEdit などもケアする。
        """
        if isinstance(obj, self.EXEMPT_TYPES):
            return True
        p = obj
        for _ in range(3):
            if p is None:
                break
            if isinstance(p, self.EXEMPT_TYPES):
                return True
            p = p.parentWidget()
        return False

    def _is_grip(self, obj) -> bool:
        """obj 自身またはその祖先に _PanelGrip があるか判定する。

        i280: パネル右下の grip 上での press はフィルタを介さず grip 自身の
        mousePressEvent に処理させたい (corner サイズ変更用)。
        """
        p = obj
        for _ in range(3):
            if p is None:
                break
            if isinstance(p, _PanelGrip):
                return True
            p = p.parentWidget()
        return False

    def _hit_resize_edge(self, panel, global_pos) -> str:
        """global_pos が panel の右端 / 下端 / 角の resize 領域にいるか判定。

        Returns:
            'right' / 'bottom' / 'corner' / '' (none)
        """
        try:
            local = panel.mapFromGlobal(global_pos)
        except Exception:
            return ""
        x = local.x()
        y = local.y()
        w = panel.width()
        h = panel.height()
        if x < 0 or y < 0 or x >= w or y >= h:
            return ""
        in_right = x >= w - self.RESIZE_EDGE
        in_bottom = y >= h - self.RESIZE_EDGE
        if in_right and in_bottom:
            return "corner"
        if in_right:
            return "right"
        if in_bottom:
            return "bottom"
        return ""

    def _update_override_cursor(self, edge: str):
        """edge に応じて QApplication の override cursor を push/pop する。

        i282: panel.setCursor() は子ウィジェット (QScrollBar, QPushButton 等)
        が自前で setCursor 済みの場合に上書きできず、非アクティブパネルの
        外枠ホバー時にカーソルがアロー表示のままになる不具合の原因だった。
        QApplication.setOverrideCursor は全ウィジェットのカーソルを強制的に
        上書きするため、子ウィジェットの上でも resize cursor が確実に出る。

        edge:
            'right' / 'bottom' / 'corner' / '' (空 = 解除)
        """
        current = getattr(self, "_active_override_edge", "")
        if edge == current:
            return  # 変化なし
        # 直前の override を解除
        if current:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self._active_override_edge = ""
        # 新しい override を push
        if edge:
            shape_map = {
                "right": Qt.CursorShape.SizeHorCursor,
                "bottom": Qt.CursorShape.SizeVerCursor,
                "corner": Qt.CursorShape.SizeFDiagCursor,
            }
            try:
                QApplication.setOverrideCursor(QCursor(shape_map[edge]))
                self._active_override_edge = edge
            except Exception:
                pass

    def _apply_resize(self, global_pos):
        """進行中の resize に対し、現在マウス位置から panel をリサイズする。"""
        panel = self._resize_panel
        edge = self._resize_edge
        geom = self._resize_start_geom
        if panel is None or geom is None:
            return
        delta = global_pos - self._resize_start_global
        new_w = geom.width()
        new_h = geom.height()
        min_w = panel.minimumWidth() or 200
        min_h = panel.minimumHeight() or 200
        if edge in ("right", "corner"):
            new_w = max(min_w, geom.width() + delta.x())
        if edge in ("bottom", "corner"):
            new_h = max(min_h, geom.height() + delta.y())
        # 親領域内にクランプ
        parent = panel.parentWidget()
        if parent is not None:
            max_w = max(min_w, parent.width() - geom.x())
            max_h = max(min_h, parent.height() - geom.y())
            new_w = min(new_w, max_w)
            new_h = min(new_h, max_h)
        panel.resize(new_w, new_h)

    def _close_active_popup(self):
        """直前 press でコントロールが開いた popup (combobox 等) を閉じる。

        i279: アクティブパネル上のコンボボックスからドラッグ開始した時、
        ドラッグ移行直後にもポップアップが浮いたまま残る不具合を防ぐ。
        QApplication.activePopupWidget() で取得できれば hide する。
        加えて、target 自体が QComboBox 系なら hidePopup() も呼ぶ。
        """
        try:
            popup = QApplication.activePopupWidget()
            if popup is not None:
                popup.hide()
        except Exception:
            pass
        try:
            target = self._press_target
            if target is not None:
                # target 自身またはその祖先で hidePopup を持つものを閉じる
                w = target
                for _ in range(4):
                    if w is None:
                        break
                    if hasattr(w, "hidePopup"):
                        try:
                            w.hidePopup()
                        except Exception:
                            pass
                        break
                    w = w.parentWidget()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if self._cancelling:
            return False

        et = event.type()
        # マウス系 3 種以外は早期 return
        if et not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        ):
            return False

        # ============================================================
        # MouseMove (no button) — i280/i282: resize cursor のホバープレビュー
        # ============================================================
        if (et == QEvent.Type.MouseMove
                and self._press_panel is None
                and self._resize_panel is None):
            try:
                if event.buttons() != Qt.MouseButton.NoButton:
                    return False
            except Exception:
                return False
            panel, has_drag = self._find_panel(obj)
            if panel is None or not has_drag:
                # 対象パネル外: 直前の override があれば解除
                self._update_override_cursor("")
                return False
            # i282: grip 上は grip 自身の cursor (SizeFDiagCursor) に任せる
            if self._is_grip(obj):
                self._update_override_cursor("")
                return False
            try:
                global_pos = event.globalPosition().toPoint()
            except Exception:
                return False
            # i282: exempt (QScrollBar / QLineEdit / QSpinBox 等) の上でも
            # resize edge にいるなら override cursor を出す。これがないと
            # スクロールバーが右端に貼り付いている設定パネルで非アクティブ時
            # の resize cursor が表示されない。
            edge = self._hit_resize_edge(panel, global_pos)
            self._update_override_cursor(edge)
            return False

        # press 状態が無いときは Press 以外は全部スルー
        if (self._press_panel is None
                and self._resize_panel is None
                and et != QEvent.Type.MouseButtonPress):
            return False

        # ============================================================
        # MouseButtonPress
        # ============================================================
        if et == QEvent.Type.MouseButtonPress:
            try:
                if event.button() != Qt.MouseButton.LeftButton:
                    return False
            except Exception:
                return False

            panel, has_drag = self._find_panel(obj)
            if panel is None:
                return False

            # i280: _PanelGrip 上は完全にフィルタを抜ける (grip 自身が処理)
            if self._is_grip(obj):
                return False

            is_focused = self._mw._is_panel_focused(panel)

            # focus-only パネルは focus だけ更新して素通し
            if not has_drag:
                if not is_focused:
                    self._mw._set_panel_focused(panel)
                return False

            # i280: リサイズ判定 (ドラッグより優先)
            try:
                global_pos = event.globalPosition().toPoint()
            except Exception:
                global_pos = None
            if global_pos is not None:
                edge = self._hit_resize_edge(panel, global_pos)
                if edge:
                    if not is_focused:
                        self._mw._set_panel_focused(panel)
                    self._resize_panel = panel
                    self._resize_edge = edge
                    self._resize_start_global = global_pos
                    self._resize_start_geom = panel.geometry()
                    return True  # press を吸収

            # 入力系: focus を立てて素通し (press は本来動作)
            if self._is_exempt(obj):
                if not is_focused:
                    self._mw._set_panel_focused(panel)
                return False

            # i280: drag tracking — focus + press 素通し
            # 非アクティブでも press は吸収しない。これにより、ボタンや
            # コンボ等の UI コントロールが「単純クリック」で初回から
            # 通常動作する。ドラッグへ昇格した際は別途 press キャンセルを送る。
            if not is_focused:
                self._mw._set_panel_focused(panel)
            self._press_panel = panel
            self._press_global = event.globalPosition().toPoint()
            self._press_panel_pos = panel.pos()
            self._press_target = obj
            self._dragging = False
            return False  # press を素通し

        # ============================================================
        # MouseMove (button held) — resize / drag
        # ============================================================
        if et == QEvent.Type.MouseMove:
            # i280: リサイズ進行中
            if self._resize_panel is not None:
                try:
                    global_pos = event.globalPosition().toPoint()
                except Exception:
                    return True
                self._apply_resize(global_pos)
                return True

            if self._press_panel is None:
                return False
            try:
                cur_global = event.globalPosition().toPoint()
            except Exception:
                return False
            delta = cur_global - self._press_global
            if not self._dragging:
                if (abs(delta.x()) + abs(delta.y())) > self.DRAG_THRESHOLD:
                    self._dragging = True
                    # 元 press をキャンセルし、popup を閉じる
                    target = self._press_target
                    if target is not None:
                        self._cancelling = True
                        try:
                            cancel_ev = QMouseEvent(
                                QEvent.Type.MouseButtonRelease,
                                QPointF(-1000.0, -1000.0),
                                event.globalPosition(),
                                Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier,
                            )
                            QApplication.sendEvent(target, cancel_ev)
                        except Exception:
                            pass
                        finally:
                            self._cancelling = False
                    self._close_active_popup()
            if self._dragging:
                panel = self._press_panel
                new_x = self._press_panel_pos.x() + delta.x()
                new_y = self._press_panel_pos.y() + delta.y()
                parent = panel.parentWidget()
                if parent is not None:
                    pw = panel.width()
                    ph = panel.height()
                    new_x = max(0, min(new_x, max(0, parent.width() - pw)))
                    # i340: 移動バー領域（bar_h より上）への侵入を禁止する
                    bar_h = PANEL_BAR_HEIGHT
                    new_y = max(bar_h, min(new_y, max(bar_h, parent.height() - ph)))
                panel.move(new_x, new_y)
                return True
            return False

        # ============================================================
        # MouseButtonRelease
        # ============================================================
        if et == QEvent.Type.MouseButtonRelease:
            try:
                if event.button() != Qt.MouseButton.LeftButton:
                    return False
            except Exception:
                return False

            # i280: リサイズ終了
            if self._resize_panel is not None:
                self._resize_panel = None
                self._resize_edge = ""
                self._resize_start_geom = None
                return True

            if self._press_panel is None:
                return False
            was_dragging = self._dragging
            self._press_panel = None
            self._press_global = QPoint()
            self._press_panel_pos = QPoint()
            self._press_target = None
            self._dragging = False
            if was_dragging:
                # ドラッグ後の release はクリックを発火させない
                return True
            return False  # 素通し → 通常クリックとして発火

        return False
