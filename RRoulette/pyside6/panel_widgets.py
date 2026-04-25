"""
RRoulette PySide6 — 共通パネル UI 部品

settings_panel.py から分離した再利用可能な UI ウィジェット群。
SettingsPanel / ItemPanel / ManagePanel に依存しない独立コンポーネント。

含まれるクラス・関数:
  _SectionHeader         — セクション見出しラベル
  CollapsibleSection     — 折りたたみ可能セクション
  _PanelGrip             — パネルリサイズグリップ
  _PanelDragBar          — パネル移動バー
  install_panel_context_menu — パネル右クリックメニュー登録
  _PlaceholderSection    — 未実装セクション用プレースホルダー
  ConfirmOverlay         — OBS 可視・汎用確認オーバーレイ（i067）
  ItemSelectOverlay      — OBS 可視・項目選択オーバーレイ（i077）
"""

from PySide6.QtCore import Qt, Signal, QPoint, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QFontMetrics, QCursor, QPainter, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QMenu, QWidget,
    QApplication, QPushButton, QScrollArea, QListWidget, QListWidgetItem,
    QAbstractScrollArea, QAbstractItemView, QGroupBox, QTabWidget,
)

from design_models import DesignSettings
from dark_theme import get_header_colors


# i341: メインウィンドウ移動バー（進入禁止領域）の高さ
# _MainWindowDragBar._BAR_HEIGHT と同値。循環インポートを避けるため定数として持つ。
_MW_DRAG_BAR_H = 20


# ================================================================
#  セクション UI 部品
# ================================================================

class _SectionHeader(QLabel):
    """セクション見出し用ラベル。"""

    def __init__(self, text: str, design: DesignSettings, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._apply_style(design)

    def _apply_style(self, design: DesignSettings):
        self.setStyleSheet(
            f"color: {design.text}; "
            f"padding: 4px 0 2px 0; "
            f"border-bottom: 1px solid {design.separator};"
        )


class CollapsibleSection(QWidget):
    """折りたたみ可能なセクション。

    ヘッダークリックでコンテンツの表示/非表示を切り替える。
    再利用可能な UI 部品として、任意のセクションに適用できる。
    """

    _ANIM_DURATION = 150  # アニメーション時間 (ms)

    toggled = Signal(bool)  # 開閉切替時に collapsed 状態を通知

    def __init__(self, title: str, design: DesignSettings,
                 expanded: bool = True, theme_mode: str = "dark",
                 parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self._title = title
        self._design = design
        self._theme_mode = theme_mode
        self._animating = False

        # ヘッダー上の click/drag 状態
        self._header_press_pos: QPoint | None = None
        self._header_pressed = False
        self._header_dragging = False
        self._drag_target: QWidget | None = None
        self._drag_start_pos: QPoint = QPoint()
        self._DRAG_THRESHOLD = 6  # px (manhattan)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # クリック / ドラッグ両対応のヘッダー
        self._header = QLabel(self._format_title(expanded), self)  # i289 t10
        self._header.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        # mousePress は記録だけ。toggle はリリース時にドラッグ判定とあわせて行う。
        self._header.mousePressEvent = self._header_mouse_press
        self._header.mouseMoveEvent = self._header_mouse_move
        self._header.mouseReleaseEvent = self._header_mouse_release
        self._apply_header_style(design)
        layout.addWidget(self._header)

        # コンテンツ領域
        self._container = QWidget(self)  # i289 t09: 親なし HWND フラッシュ防止
        self._container.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._container)
        self._content_layout.setContentsMargins(4, 6, 4, 2)
        self._content_layout.setSpacing(8)
        self._container.setVisible(expanded)
        if not expanded:
            self._container.setMaximumHeight(0)
        layout.addWidget(self._container)

        # アニメーション
        self._anim = QPropertyAnimation(self._container, b"maximumHeight")
        self._anim.setDuration(self._ANIM_DURATION)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

    def _format_title(self, expanded: bool) -> str:
        arrow = "\u25bc" if expanded else "\u25b6"
        return f"{arrow} {self._title}"

    # ----------------------------------------------------------------
    #  ヘッダー click / drag 分離ハンドラ
    # ----------------------------------------------------------------

    def _header_mouse_press(self, ev):
        """ヘッダー上のマウス押下: 記録のみ。トグルはリリース時に判定。"""
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        self._header_press_pos = ev.globalPosition().toPoint()
        self._header_pressed = True
        self._header_dragging = False
        # 親 (SettingsPanel など) のうち、ドラッグハンドルを備えた最初の祖先を探す
        self._drag_target = self._find_drag_target()
        if self._drag_target is not None:
            parent = self._drag_target.parentWidget()
            if parent is None:
                self._drag_start_pos = (
                    self._drag_target.frameGeometry().topLeft()
                )
            else:
                self._drag_start_pos = self._drag_target.pos()
            # クリックした祖先パネルを最前面へ
            self._drag_target.raise_()
        ev.accept()

    def _header_mouse_move(self, ev):
        """ヘッダー上のマウス移動: しきい値を超えたらパネルドラッグへ昇格。"""
        if not self._header_pressed:
            ev.ignore()
            return
        if self._header_press_pos is None or self._drag_target is None:
            ev.accept()
            return
        delta = ev.globalPosition().toPoint() - self._header_press_pos
        if not self._header_dragging:
            if (abs(delta.x()) + abs(delta.y())) > self._DRAG_THRESHOLD:
                self._header_dragging = True
        if self._header_dragging:
            target = self._drag_target
            new_pos = self._drag_start_pos + delta
            parent = target.parentWidget()
            if parent is not None:
                # 埋め込み: 親内クランプ
                new_x = max(0, min(new_pos.x(),
                                   parent.width() - target.width()))
                new_y = max(0, min(new_pos.y(),
                                   parent.height() - target.height()))
                target.move(new_x, new_y)
            else:
                # フローティング: 利用可能スクリーンでクランプ
                screen = QApplication.primaryScreen()
                if screen:
                    sg = screen.availableGeometry()
                    min_vis = 60
                    new_x = max(sg.x() - target.width() + min_vis,
                                min(new_pos.x(),
                                    sg.x() + sg.width() - min_vis))
                    new_y = max(sg.y(),
                                min(new_pos.y(),
                                    sg.y() + sg.height() - 30))
                    target.move(new_x, new_y)
                else:
                    target.move(new_pos)
        ev.accept()

    def _header_mouse_release(self, ev):
        """ヘッダー上のマウスリリース: ドラッグしていなければクリック扱いで toggle。

        i278: release の position がヘッダー領域外なら toggle しない。
        これは「グローバルドラッグフィルタが drag 検出時に画面外位置の
        合成 release を送ってヘッダーの press 状態をキャンセルする」
        パターンに対応するための判定。通常クリック時は内側で release
        されるので従来通り toggle する。
        """
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        was_dragging = self._header_dragging
        self._header_pressed = False
        self._header_dragging = False
        self._header_press_pos = None
        self._drag_target = None
        # release 位置が header 内かをチェック
        try:
            pos = ev.position().toPoint()
        except Exception:
            pos = None
        inside = (pos is not None
                  and self._header.rect().contains(pos))
        if not was_dragging and inside:
            self.toggle()
        ev.accept()

    def _find_drag_target(self) -> QWidget | None:
        """ヘッダーから上を辿って、ドラッグ対象となる祖先パネルを返す。"""
        w = self.parentWidget()
        while w is not None:
            if hasattr(w, "_drag_bar"):
                return w
            w = w.parentWidget()
        return None

    @property
    def content_layout(self) -> QVBoxLayout:
        """コンテンツ側のレイアウトを返す。"""
        return self._content_layout

    @property
    def is_collapsed(self) -> bool:
        return not self._expanded

    def set_expanded(self, expanded: bool):
        """外部から展開/折りたたみ状態を設定する（シグナルなし、即座）。"""
        self._anim.stop()
        self._animating = False
        self._expanded = expanded
        self._container.setVisible(expanded)
        self._container.setMaximumHeight(
            16777215 if expanded else 0
        )
        self._header.setText(self._format_title(expanded))
        self._apply_header_style(self._design)

    def toggle(self):
        if self._animating:
            return
        self._expanded = not self._expanded
        self._header.setText(self._format_title(self._expanded))
        self._apply_header_style(self._design)
        self.toggled.emit(not self._expanded)  # collapsed を通知
        self._start_animation(self._expanded)

    def _start_animation(self, expanding: bool):
        self._anim.stop()
        self._animating = True
        if expanding:
            self._container.setVisible(True)
            self._container.setMaximumHeight(0)
            target_h = self._container.sizeHint().height()
            self._anim.setStartValue(0)
            self._anim.setEndValue(target_h)
        else:
            current_h = self._container.height()
            self._anim.setStartValue(current_h)
            self._anim.setEndValue(0)
        self._anim.start()

    def _on_anim_finished(self):
        self._animating = False
        if self._expanded:
            # 展開完了: 最大高さ制限を解除
            self._container.setMaximumHeight(16777215)
        else:
            # 折りたたみ完了: 非表示化
            self._container.setVisible(False)

    def _apply_header_style(self, design: DesignSettings):
        c = get_header_colors(self._theme_mode, design)
        bg = c["bg_expanded"] if self._expanded else c["bg_collapsed"]
        self._header.setStyleSheet(
            f"QLabel {{"
            f"  color: {c['text']};"
            f"  background-color: {bg};"
            f"  padding: 5px 8px;"
            f"  border-radius: 3px;"
            f"  margin-top: 2px;"
            f"}}"
            f"QLabel:hover {{"
            f"  background-color: {c['hover']};"
            f"}}"
        )

    def set_anim_duration(self, ms: int):
        """アニメーション時間を変更する (ms)。0 で無効化。"""
        self._anim.setDuration(max(ms, 0))

    def set_theme_mode(self, theme_mode: str):
        """テーマモードを更新してヘッダーを再描画する。"""
        self._theme_mode = theme_mode
        self._apply_header_style(self._design)

    def apply_design(self, design: DesignSettings):
        self._design = design
        self._apply_header_style(design)


class _PanelGrip(QWidget):
    """パネル右下に配置するリサイズグリップ。

    ドラッグで対象パネルのサイズを拡大・縮小する。
    パネル幅は常に setFixedWidth で管理し、ウィンドウも連動リサイズする。

    mode:
      "panel" — 設定/項目パネル用。ドラッグでパネル幅を変え、ウィンドウ幅も連動。
      "wheel" — ルーレット側用。ドラッグでウィンドウサイズを変える（パネル幅は保持）。
    """

    _GRIP_SIZE = 16

    def __init__(self, target: QWidget, design, mode: str = "panel",
                 min_w: int = 200, min_h: int = 200, parent=None):
        super().__init__(parent or target)
        self._target = target
        self._design = design
        self._mode = mode
        self._min_w = min_w
        self._min_h = min_h
        self._dragging = False
        self._drag_start = QPoint()
        self._start_target_w = 0
        self._start_target_h = 0
        self._start_win_w = 0
        self._start_win_h = 0
        self._skip_parent_clamp = False  # roulette_only_mode 時に親サイズ制限をスキップ
        self.setFixedSize(self._GRIP_SIZE, self._GRIP_SIZE)
        self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        self.raise_()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._design.text_sub)
        color.setAlpha(160)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        s = self._GRIP_SIZE
        # 右下三角形パターン: 行が下がるほどドットが多い（右下方向を示唆）
        for r in range(3):
            for c in range(r + 1):
                x = s - (r + 1 - c) * 5
                y = s - (3 - r) * 5
                p.drawEllipse(x, y, 3, 3)
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._drag_start = event.globalPosition().toPoint()
        self._start_target_w = self._target.width()
        self._start_target_h = self._target.height()
        win = self._target.window()
        if win:
            self._start_win_w = win.width()
            self._start_win_h = win.height()
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        win = self._target.window()
        if not win:
            return

        if self._mode == "panel":
            # パネルのみリサイズ（位置固定、右下方向に拡縮）
            new_w = max(self._min_w, self._start_target_w + delta.x())
            new_h = max(self._min_h, self._start_target_h + delta.y())
            # _skip_parent_clamp が False の場合のみ親ウィンドウ幅に制限する。
            # roulette_only_mode 中は親＝ウィンドウと同サイズのため制限をスキップし、
            # ウィンドウ側が後追いでリサイズする。
            if not self._skip_parent_clamp:
                parent = self._target.parentWidget()
                if parent:
                    max_w = parent.width() - self._target.x()
                    max_h = parent.height() - self._target.y()
                    new_w = min(new_w, max_w)
                    new_h = min(new_h, max_h)
            self._target.resize(new_w, new_h)
        else:
            # wheel 側: ウィンドウをリサイズ（パネル幅は保持）
            new_win_w = max(win.minimumWidth(), self._start_win_w + delta.x())
            new_win_h = max(win.minimumHeight(), self._start_win_h + delta.y())
            win.resize(new_win_w, new_win_h)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()

    def update_design(self, design):
        self._design = design
        self.update()

    def reposition(self):
        """親ウィジェット右下に位置を合わせる。"""
        parent = self.parentWidget()
        if parent:
            self.move(
                parent.width() - self._GRIP_SIZE,
                parent.height() - self._GRIP_SIZE,
            )
            self.raise_()


# ================================================================
#  パネル背景透過ヘルパー (i107)
# ================================================================

_TRANS_ORIG_SS  = "_transp_orig_ss"   # 元 stylesheet 保存キー
_TRANS_ORIG_ALT = "_transp_orig_alt"  # 元 alternatingRowColors 保存キー


def apply_transparent_to_widget_tree(root: QWidget, enabled: bool) -> None:
    """root 配下のスクロール領域・アイテムビューに透過スタイルを適用/復元する。

    enabled=True: QAbstractScrollArea (QTableWidget / QListWidget 等) の
      背景・viewport・行背景を透過スタイルへ切り替える。
      QScrollArea の場合は setWidget() で設定したコンテンツ widget も対象にする。
    enabled=False: 保存済みの元スタイルを復元する。
    """
    for sa in root.findChildren(QAbstractScrollArea):
        if enabled:
            if sa.property(_TRANS_ORIG_SS) is None:
                sa.setProperty(_TRANS_ORIG_SS, sa.styleSheet())
            cls = type(sa).__name__
            sa.setStyleSheet(
                f"{cls} {{ background: transparent; }}"
                f"{cls}::item {{ background: transparent; }}"
                f"{cls}::item:alternate {{ background: transparent; }}"
                f"QHeaderView::section {{ background: transparent; "
                f"  border-bottom: 1px solid rgba(128,128,128,0.4); }}"
                f"QScrollBar:vertical {{ background: transparent; }}"
                f"QScrollBar:horizontal {{ background: transparent; }}"
            )
            if isinstance(sa, QAbstractItemView):
                if sa.property(_TRANS_ORIG_ALT) is None:
                    sa.setProperty(_TRANS_ORIG_ALT, sa.alternatingRowColors())
                sa.setAlternatingRowColors(False)
            vp = sa.viewport()
            if vp and vp.property(_TRANS_ORIG_SS) is None:
                vp.setProperty(_TRANS_ORIG_SS, vp.styleSheet())
                vp.setStyleSheet("background: transparent;")
            # i108: QScrollArea の場合、setWidget() で設定したコンテンツ widget も透過する。
            # ManagePanel の body / SettingsPanel の _content / ItemPanel の _rows_content
            # などの中間コンテナが solid background を保持したままになる問題を解消する。
            if isinstance(sa, QScrollArea):
                cw = sa.widget()
                if cw is not None and cw.property(_TRANS_ORIG_SS) is None:
                    cw.setProperty(_TRANS_ORIG_SS, cw.styleSheet())
                    cw.setStyleSheet("background-color: transparent;")
        else:
            orig = sa.property(_TRANS_ORIG_SS)
            if orig is not None:
                sa.setStyleSheet(orig)
                sa.setProperty(_TRANS_ORIG_SS, None)
            if isinstance(sa, QAbstractItemView):
                orig_alt = sa.property(_TRANS_ORIG_ALT)
                if orig_alt is not None:
                    sa.setAlternatingRowColors(bool(orig_alt))
                    sa.setProperty(_TRANS_ORIG_ALT, None)
            vp = sa.viewport()
            if vp:
                orig_vp = vp.property(_TRANS_ORIG_SS)
                if orig_vp is not None:
                    vp.setStyleSheet(orig_vp)
                    vp.setProperty(_TRANS_ORIG_SS, None)
            # i108: QScrollArea コンテンツ widget を復元する
            if isinstance(sa, QScrollArea):
                cw = sa.widget()
                if cw is not None:
                    orig_cw = cw.property(_TRANS_ORIG_SS)
                    if orig_cw is not None:
                        cw.setStyleSheet(orig_cw)
                        cw.setProperty(_TRANS_ORIG_SS, None)

    for gb in root.findChildren(QGroupBox):
        if enabled:
            if gb.property(_TRANS_ORIG_SS) is None:
                gb.setProperty(_TRANS_ORIG_SS, gb.styleSheet())
            gb.setStyleSheet("QGroupBox { background: transparent; }")
        else:
            orig = gb.property(_TRANS_ORIG_SS)
            if orig is not None:
                gb.setStyleSheet(orig)
                gb.setProperty(_TRANS_ORIG_SS, None)

    # i108: QTabWidget::pane はデフォルトで solid background を持つため透過対象に追加する。
    # TicketPanel など QTabWidget を使うパネルでタブペイン背景を透過する。
    for tw in root.findChildren(QTabWidget):
        if enabled:
            orig_ss = tw.property(_TRANS_ORIG_SS)
            if orig_ss is None:
                orig_ss = tw.styleSheet()
                tw.setProperty(_TRANS_ORIG_SS, orig_ss)
            # 保存済みの元スタイルに透過ルールを上乗せ（タブバーのスタイルは維持）
            tw.setStyleSheet(
                orig_ss
                + " QTabWidget::pane { background: transparent; }"
            )
        else:
            orig = tw.property(_TRANS_ORIG_SS)
            if orig is not None:
                tw.setStyleSheet(orig)
                tw.setProperty(_TRANS_ORIG_SS, None)


def install_panel_context_menu(panel: QWidget, drag_bar: QWidget,
                                title: str = "パネル設定",
                                on_drag_bar_changed=None):
    """パネル用の右クリックコンテキストメニューをインストールする。

    メインウィンドウが _show_context_menu_for_panel を持つ場合、
    共通アプリメニュー（パネル表示・透過設定・終了等）を表示する。
    持たない場合は移動バートグルのみのフォールバックメニューを表示する。

    Args:
        on_drag_bar_changed: 移動バーの表示状態が変化したときに呼ばれる
            callable[[bool], None]。省略時は None（E: i294）。
    """
    panel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _show_menu(pos):
        global_pos = panel.mapToGlobal(pos)
        main_win = panel.window()
        if hasattr(main_win, '_show_context_menu_for_panel'):
            main_win._show_context_menu_for_panel(global_pos, drag_bar, on_drag_bar_changed)
            return
        # フォールバック: 移動バートグルのみ
        menu = QMenu(panel)
        menu.setStyleSheet(
            "QMenu { padding: 2px; }"
            "QMenu::item { padding: 4px 24px 4px 20px; }"
        )
        toggle_text = (
            "✔ 移動バーを表示"
            if drag_bar.isVisible()
            else "  移動バーを表示"
        )
        action = menu.addAction(toggle_text)

        def _toggle():
            new_vis = not drag_bar.isVisible()
            drag_bar.setVisible(new_vis)
            if on_drag_bar_changed is not None:
                on_drag_bar_changed(new_vis)

        action.triggered.connect(_toggle)
        menu.exec(global_pos)

    panel.customContextMenuRequested.connect(_show_menu)


class _PanelDragBar(QWidget):
    """パネル上部のドラッグバー。ドラッグでパネルを親ウィジェット内で移動する。"""

    _BAR_HEIGHT = 20

    def __init__(self, target: QWidget, design: DesignSettings, parent=None):
        super().__init__(parent or target)
        self._target = target
        self._design = design
        self._dragging = False
        self._drag_start = QPoint()
        self._start_pos = QPoint()
        self.setFixedHeight(self._BAR_HEIGHT)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._design.separator))
        # 中央にグリップパターンを描画
        color = QColor(self._design.text_sub)
        color.setAlpha(140)
        p.setPen(color)
        cx = self.width() // 2
        cy = self._BAR_HEIGHT // 2
        for i in range(-3, 4):
            p.drawPoint(cx + i * 4, cy - 2)
            p.drawPoint(cx + i * 4, cy + 2)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # クリックしたパネルを最前面へ
            self._target.raise_()
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
            self._start_pos = self._target.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        new_pos = self._start_pos + delta
        # i277: パネルは centralWidget の child widget。pos() / move() は
        # 親内 (client) 座標。親領域内に完全に収まるようクランプする。
        parent = self._target.parentWidget()
        if parent:
            tw = self._target.width()
            th = self._target.height()
            new_x = max(0, min(new_pos.x(), max(0, parent.width() - tw)))
            # i341: 移動バー領域（_MW_DRAG_BAR_H より上）への侵入禁止
            new_y = max(_MW_DRAG_BAR_H, min(new_pos.y(), max(_MW_DRAG_BAR_H, parent.height() - th)))
            self._target.move(new_x, new_y)
        else:
            self._target.move(new_pos)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()

    def update_design(self, design: DesignSettings):
        self._design = design
        self.update()


class _PlaceholderSection(QFrame):
    """未実装セクションのプレースホルダー。

    将来機能を本実装する際は、このクラスを専用セクションに差し替える。
    差し替え時の手順:
      1. 専用セクションクラスを作成（_PlaceholderSection と同じ位置に追加可能）
      2. SettingsPanel._build_future_sections() 内で差し替え
      3. setting_changed シグナル経由で MainWindow に通知
    """

    def __init__(self, title: str, description: str,
                 design: DesignSettings, parent=None):
        super().__init__(parent)
        self._header = _SectionHeader(title, design)
        self._desc = QLabel(description)
        self._desc.setFont(QFont("Meiryo", 8))
        self._desc.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)
        layout.addWidget(self._header)
        layout.addWidget(self._desc)

        self._apply_style(design)

    def _apply_style(self, design: DesignSettings):
        self._header._apply_style(design)
        self._desc.setStyleSheet(f"color: {design.text_sub};")


# ================================================================
#  汎用確認オーバーレイ（OBS 可視）
# ================================================================

class ConfirmOverlay(QWidget):
    """親ウィジェット全面を覆う汎用確認オーバーレイ (i067)。

    OBS に映ることを目的とし、QDialog / QMessageBox（別 HWND）の代わりに
    親パネルの子ウィジェットとして描画する。

    使い方::

        _BTN_OK   = "ok"
        _BTN_CANCEL = "cancel"

        overlay = ConfirmOverlay(
            title   = "確認",
            body    = "本当に続行しますか？",
            buttons = [
                ("続行する", _BTN_OK,     "primary"),
                ("キャンセル", _BTN_CANCEL, "cancel"),
            ],
            design  = self._design,
            parent  = self,
        )
        overlay.chosen.connect(lambda v: ...)

    Parameters
    ----------
    title:
        オーバーレイのタイトルテキスト。
    body:
        本文テキスト（チケット名・説明など）。
    buttons:
        ``(label, value, style_hint)`` のリスト。
        * ``style_hint`` は ``"primary"`` / ``"danger"`` / ``"cancel"`` のいずれか。
    design:
        デザイン設定。
    parent:
        オーバーレイを配置する親ウィジェット（必須）。
        ``parent.rect()`` 全面を覆う。

    Signals
    -------
    chosen(str):
        ボタン押下時に ``value`` を渡す。
    """

    chosen: Signal = Signal(str)

    # style_hint → CSS
    _BTN_STYLES: dict[str, str] = {
        "primary": (
            "QPushButton { background: #28a745; color: #ffffff; "
            "border: none; border-radius: 6px; padding: 6px 16px; }"
            "QPushButton:hover { background: #34c759; }"
            "QPushButton:pressed { background: #1e8035; }"
        ),
        "danger": (
            "QPushButton { background: #dc3545; color: #ffffff; "
            "border: none; border-radius: 6px; padding: 6px 16px; }"
            "QPushButton:hover { background: #e84545; }"
            "QPushButton:pressed { background: #b02030; }"
        ),
    }

    def __init__(
        self,
        title: str,
        body: str,
        buttons: list[tuple[str, str, str]],
        design: DesignSettings,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setGeometry(parent.rect())
        self.raise_()
        self.setStyleSheet("background-color: rgba(0, 0, 0, 160);")

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.setContentsMargins(16, 16, 16, 16)

        # 内側カード
        card = QFrame(self)
        card.setStyleSheet(
            f"QFrame {{ background-color: {design.panel}; "
            f"border: 2px solid {design.separator}; border-radius: 8px; }}"
            f"QLabel {{ border: none; }}"
        )
        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(20, 16, 20, 16)
        card_v.setSpacing(12)

        # タイトル
        title_lbl = QLabel(title, card)
        title_lbl.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {design.text}; background: transparent;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setWordWrap(True)
        card_v.addWidget(title_lbl)

        # 本文
        if body:
            body_lbl = QLabel(body[:200], card)
            body_lbl.setFont(QFont("Meiryo", 9))
            body_lbl.setStyleSheet(
                f"color: {design.text_sub}; background: transparent;"
            )
            body_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body_lbl.setWordWrap(True)
            card_v.addWidget(body_lbl)

        # ボタン行（cancel 以外）
        main_btns = [(lbl, val, hint) for lbl, val, hint in buttons
                     if hint != "cancel"]
        cancel_btns = [(lbl, val, hint) for lbl, val, hint in buttons
                       if hint == "cancel"]

        if main_btns:
            btn_row = QHBoxLayout()
            btn_row.setSpacing(16)
            for lbl, val, hint in main_btns:
                b = QPushButton(lbl, card)
                b.setFont(QFont("Meiryo", 12, QFont.Weight.Bold))
                b.setMinimumHeight(52)
                b.setMinimumWidth(120)
                b.setStyleSheet(self._BTN_STYLES.get(hint, self._BTN_STYLES["primary"]))
                b.clicked.connect(lambda _, v=val: self.chosen.emit(v))
                btn_row.addWidget(b)
            card_v.addLayout(btn_row)

        for lbl, val, _ in cancel_btns:
            cb = QPushButton(lbl, card)
            cb.setFont(QFont("Meiryo", 8))
            cb.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {design.text_sub}; "
                f"border: none; text-decoration: underline; padding: 2px; }}"
                f"QPushButton:hover {{ color: {design.text}; }}"
            )
            cb.clicked.connect(lambda _, v=val: self.chosen.emit(v))
            card_v.addWidget(cb, 0, Qt.AlignmentFlag.AlignHCenter)

        outer.addWidget(card)
        self.show()


class ItemSelectOverlay(QWidget):
    """保有チケット使用時に項目を1つ選ぶ OBS 可視オーバーレイ (i077)。

    有効項目（enabled=True）を QListWidget で列挙し、クリックした項目の
    item_id を ``chosen`` シグナルで通知する。
    キャンセル時は空文字列を通知する。

    Parameters
    ----------
    title:
        オーバーレイのタイトルテキスト。
    items:
        ``(item_id, display_text)`` のリスト。選択候補の項目群。
    design:
        デザイン設定。
    parent:
        オーバーレイを配置する親ウィジェット（必須）。
        ``parent.rect()`` 全面を覆う。

    Signals
    -------
    chosen(str):
        項目クリック時に item_id を渡す。キャンセル時は ``""``。
    """

    chosen: Signal = Signal(str)

    def __init__(
        self,
        title: str,
        items: list[tuple[str, str]],
        design: DesignSettings,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setGeometry(parent.rect())
        self.raise_()
        self.setStyleSheet("background-color: rgba(0, 0, 0, 160);")

        # i085: コンテンツ量ベースのサイズ計算 (i084 継承・省略表示修正・フッター分離)
        # ─────────────────────────────────────────────────────────
        # 行高さ: QFontMetrics 実測値ベース (固定値廃止)
        # 横幅: 最長項目名の必要幅を算出し、パネル内最大まで広げる
        # 省略: setTextElideMode(ElideNone) で ... を完全無効化
        # 縦高さ: 全件収まるならスクロールなし、超過時のみ縦スクロール
        # フッター: キャンセルをリスト領域と分離した独立フッター (i085)
        # ─────────────────────────────────────────────────────────

        item_font = QFont("Meiryo", 10)
        fm = QFontMetrics(item_font)

        # 行高さ: フォント実高さ + CSS padding(6px×2) + 下ボーダー(1px)
        _ROW_H = fm.height() + 13

        # フッター高さ: キャンセルボタン行 + セパレーター(1px) + 上下padding(10px×2)
        _footer_h = fm.height() + 25

        # オーバーヘッド: OV外余白(40) + カード枠(4) + カード上余白(12)
        #                + タイトル行(fm高さ+8) + spacing(8) + フッター
        _OVERHEAD_H = 40 + 4 + 12 + (fm.height() + 8) + 8 + _footer_h

        # 高さ: 全件表示に必要な高さ vs パネル内利用可能高さ
        natural_list_h   = max(len(items), 1) * _ROW_H + 4
        available_list_h = parent.height() - _OVERHEAD_H

        if natural_list_h <= available_list_h:
            list_h = natural_list_h
            v_scroll = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        else:
            list_h = max(available_list_h, _ROW_H * 2)
            v_scroll = Qt.ScrollBarPolicy.ScrollBarAsNeeded

        # 横幅: 最長項目名を1行表示するための必要幅
        # カード左右余白(16×2) + リスト左右padding(12×2) + スクロールバー余裕(18)
        _H_PADDING = 32 + 24 + 18
        max_text_w = max((fm.horizontalAdvance(text) for _, text in items), default=0)
        natural_card_w = max_text_w + _H_PADDING
        # パネル内最大幅(左右余白40を除く)を上限、最小220pxを下限
        max_card_w = parent.width() - 40
        card_w = max(220, min(natural_card_w, max_card_w))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        # 内側カード: コンテンツ量ベースの幅（パネル内最大まで広げる）
        card = QFrame(self)
        card.setFixedWidth(card_w)
        card.setStyleSheet(
            f"QFrame {{ background-color: {design.panel}; "
            f"border: 2px solid {design.separator}; border-radius: 8px; }}"
            f"QLabel {{ border: none; }}"
        )
        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(16, 12, 16, 0)  # 下余白はフッターが担う
        card_v.setSpacing(8)

        # タイトル
        title_lbl = QLabel(title, card)
        title_lbl.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {design.text}; background: transparent;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setWordWrap(True)
        card_v.addWidget(title_lbl)

        # i079: QListWidget ベース（QPushButton.setWordWrap は PySide6 非対応）
        # i085: setTextElideMode(ElideNone) で ... 省略表示を完全無効化
        list_widget = QListWidget(card)
        list_widget.setFixedHeight(list_h)
        list_widget.setVerticalScrollBarPolicy(v_scroll)
        list_widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)
        list_widget.setFont(item_font)
        list_widget.setStyleSheet(
            f"QListWidget {{ background: {design.bg}; color: {design.text}; "
            f"border: 1px solid {design.separator}; border-radius: 4px; "
            f"outline: none; }}"
            f"QListWidget::item {{ padding: 6px 12px; "
            f"border-bottom: 1px solid {design.separator}; }}"
            f"QListWidget::item:hover {{ background: {design.accent}; }}"
            f"QListWidget::item:selected {{ background: #4a6380; color: #ffffff; }}"
            f"QScrollBar:vertical {{ width: 8px; }}"
            f"QScrollBar:horizontal {{ height: 8px; }}"
        )
        for item_id, text in items:
            lw_item = QListWidgetItem(text)
            lw_item.setData(Qt.ItemDataRole.UserRole, item_id)
            lw_item.setSizeHint(QSize(1, _ROW_H))
            list_widget.addItem(lw_item)
        list_widget.itemClicked.connect(
            lambda it: self.chosen.emit(it.data(Qt.ItemDataRole.UserRole))
        )
        card_v.addWidget(list_widget)

        # i085: フッター — キャンセルをリスト領域と分離した独立フッター
        # セパレーターラベルで視覚的に区切り、余白付きでキャンセルを配置
        sep_lbl = QLabel(card)
        sep_lbl.setFixedHeight(1)
        sep_lbl.setStyleSheet(f"background: {design.separator}; border: none;")
        card_v.addWidget(sep_lbl)

        footer = QWidget(card)
        footer.setStyleSheet("background: transparent;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 10, 8, 10)

        cancel_btn = QPushButton("キャンセル", footer)
        cancel_btn.setFont(QFont("Meiryo", 8))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {design.text_sub}; "
            f"border: none; text-decoration: underline; padding: 2px; }}"
            f"QPushButton:hover {{ color: {design.text}; }}"
        )
        cancel_btn.clicked.connect(lambda: self.chosen.emit(""))
        footer_layout.addWidget(cancel_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        card_v.addWidget(footer)

        # カードを中央配置（ストレッチさせない）
        outer.addStretch(1)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self.show()
