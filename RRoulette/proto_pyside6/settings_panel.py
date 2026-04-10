"""
PySide6 プロトタイプ — 操作・設定パネル

右側パネルの責務:
  - spin 操作（開始ボタン、プリセット切替）
  - 表示設定（テキストモード、ドーナツ穴 等）
  - 項目データ表示（ItemEntry リスト）
  - 将来機能の受け皿セクション（プレースホルダー）

設定変更の通知フロー:
  SettingsPanel → setting_changed(key, value) → MainWindow → 各コンポーネント

セクション構成（2系統で整理）:

  【アプリ設定セクション】AppSettings 側
    1. スピン操作 — 実装済み
    2. 表示設定 — 実装済み
    3. 結果表示 — 実装済み

  【項目データセクション】ItemEntry 側
    4. 項目リスト — 実装済み（編集可能）
    5. 確率変更 — プレースホルダー（項目データの編集）
    6. 分割 — プレースホルダー（項目データの編集）
    7. 配置 — プレースホルダー（項目データの編集）
    8. 常時ランダム — プレースホルダー（spin 前の配置制御）
"""

from PySide6.QtCore import Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QCursor, QPainter, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QScrollArea, QWidget,
    QDoubleSpinBox, QSpinBox, QLineEdit, QStackedWidget, QSlider,
    QFileDialog, QPlainTextEdit, QStackedLayout, QMenu,
)

from bridge import (
    SIDEBAR_W, SIZE_PROFILES, DesignSettings,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
    ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES,
)


# ================================================================
#  項目テキスト直接編集ヘルパー (v0.4.4 item_list 由来)
# ================================================================

def serialize_items_text(items: list[str]) -> str:
    """項目リストをテキストエリア用の文字列に変換する。

    改行を含む項目はクォートブロックで囲む。通常項目はそのまま出力。
    （v0.4.4 `item_list._serialize_items` を移植）
    """
    parts = []
    for item in items:
        if "\n" in item:
            content_lines = item.split("\n")
            esc = []
            for ln in content_lines:
                if ln.endswith('"') and not ln.endswith('""'):
                    ln += '"'
                esc.append(ln)
            esc[0] = '"' + esc[0]
            last = esc[-1]
            if last.endswith('"'):
                esc.append('"')
            else:
                esc[-1] += '"'
            parts.append("\n".join(esc))
        else:
            parts.append(item)
    return "\n".join(parts)


def parse_items_text(raw: str) -> list[str]:
    """テキストをパースして項目リストを返す。

    書式:
      - 通常行: 各行が 1 項目
      - クォートブロック: 行頭 `"` で開始 → 行末 `"` で 1 項目に確定
      - `""` エスケープ: ブロック内で行末 `"` を含めたいとき
    （v0.4.4 `item_list._parse_items` を移植）
    """
    items: list[str] = []
    buf: list[str] | None = None

    def _flush_pending():
        if buf:
            items.append('"' + buf[0])
            for ln in buf[1:]:
                if ln.strip():
                    items.append(ln.strip())

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if buf is not None:
            if s == '"':
                item = '\n'.join(buf).strip('\n').replace('""', '"')
                if item:
                    items.append(item)
                buf = None
            elif s[0] == '"':
                _flush_pending()
                rest = s[1:]
                if rest and rest[-1] == '"' and not rest.endswith('""'):
                    item = rest[:-1].replace('""', '"')
                    if item:
                        items.append(item)
                    buf = None
                else:
                    buf = [rest] if rest else []
            elif s[-1] == '"' and not s.endswith('""'):
                buf.append(s[:-1])
                item = '\n'.join(buf).strip('\n').replace('""', '"')
                if item:
                    items.append(item)
                buf = None
            else:
                buf.append(s)
        else:
            if s[0] == '"':
                rest = s[1:]
                if rest and rest[-1] == '"' and not rest.endswith('""'):
                    item = rest[:-1].replace('""', '"')
                    if item:
                        items.append(item)
                elif rest:
                    buf = [rest]
                else:
                    items.append('"')
            else:
                items.append(s)
    _flush_pending()
    return items


def enforce_item_limits(items: list[str]) -> tuple[list[str], bool, str]:
    """項目数 / 行数 / 文字数の上限を強制する。

    Returns: (trimmed_items, was_changed, warn_message)
    （v0.4.4 `item_list._enforce_limits` を移植）
    """
    warnings: list[str] = []
    changed = False
    if len(items) > ITEM_MAX_COUNT:
        items = items[:ITEM_MAX_COUNT]
        warnings.append(f"項目数を上限（{ITEM_MAX_COUNT}）に制限")
        changed = True
    trimmed: list[str] = []
    for item in items:
        lines = item.split("\n")
        if len(lines) > ITEM_MAX_LINES:
            lines = lines[:ITEM_MAX_LINES]
            warnings.append(f"1項目{ITEM_MAX_LINES}行に制限")
            changed = True
        new_lines: list[str] = []
        for ln in lines:
            if len(ln) > ITEM_MAX_LINE_CHARS:
                new_lines.append(ln[:ITEM_MAX_LINE_CHARS])
                warnings.append(f"1行{ITEM_MAX_LINE_CHARS}文字に制限")
                changed = True
            else:
                new_lines.append(ln)
        trimmed.append("\n".join(new_lines))
    seen: set[str] = set()
    unique: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return trimmed, changed, " / ".join(unique)
from app_settings import AppSettings
from item_entry import ItemEntry
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME
from dark_theme import dark_checkbox_style, dark_spinbox_style, get_header_colors


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
        self._header = QLabel(self._format_title(expanded))
        self._header.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        # mousePress は記録だけ。toggle はリリース時にドラッグ判定とあわせて行う。
        self._header.mousePressEvent = self._header_mouse_press
        self._header.mouseMoveEvent = self._header_mouse_move
        self._header.mouseReleaseEvent = self._header_mouse_release
        self._apply_header_style(design)
        layout.addWidget(self._header)

        # コンテンツ領域
        self._container = QWidget()
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
                from PySide6.QtWidgets import QApplication
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


def install_panel_context_menu(panel: QWidget, drag_bar: QWidget,
                                title: str = "パネル設定"):
    """パネル用の右クリックコンテキストメニューをインストールする。

    含まれるアイテム:
      - 「移動バーを表示」チェック (drag_bar.setVisible)
    """
    panel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _show_menu(pos):
        menu = QMenu(panel)
        toggle_text = (
            "✔ 移動バーを表示"
            if drag_bar.isVisible()
            else "  移動バーを表示"
        )
        action = menu.addAction(toggle_text)
        action.triggered.connect(
            lambda: drag_bar.setVisible(not drag_bar.isVisible())
        )
        global_pos = panel.mapToGlobal(pos)
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
            new_y = max(0, min(new_pos.y(), max(0, parent.height() - th)))
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


class ItemPanel(QFrame):
    """項目編集専用パネル。

    SettingsPanel から取り外したパターン (グループ) セクションと項目セクションを
    載せ替え、v0.4.4 と同じ「項目編集の主役パネル」として扱う。

    構成:
      - 上部ドラッグバー（パネル移動の唯一の起点）
      - パターン (グループ) 行
      - テキスト編集トグルバー
      - 項目リスト本体（折りたたみヘッダーは隠して常時表示）
      - 右下リサイズグリップ

    SettingsPanel 側のロジック (`_item_rows` / `set_active_entries` /
    `replace_entries_from_texts`) は変更なくそのまま流用する。
    """

    geometry_changed = Signal()

    def __init__(self, design: DesignSettings, items_widget: QWidget,
                 pattern_widget: QWidget,
                 settings_panel: "SettingsPanel",
                 *, parent=None):
        super().__init__(parent)
        self._design = design
        self._floating = False
        self.pinned_front = False
        self._settings_panel = settings_panel
        self._items_widget = items_widget
        self._pattern_widget = pattern_widget
        self._text_edit_mode = False
        self.setStyleSheet(f"background-color: {design.panel};")
        # 子クライアント領域からのクリックを QMainWindow まで伝播させない
        # （ItemPanel 上を掴んだつもりがメインウィンドウのドラッグになる事故防止）
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 上部ドラッグバー（唯一の移動起点）
        self._drag_bar = _PanelDragBar(self, design, parent=self)
        outer.addWidget(self._drag_bar)
        # 右クリック → 移動バー表示/非表示
        install_panel_context_menu(self, self._drag_bar)

        # パターン (グループ) セクションを隠さず常設表示する
        if pattern_widget is not None:
            # CollapsibleSection を渡された場合はヘッダーを隠して常時展開
            if hasattr(pattern_widget, "_header"):
                try:
                    pattern_widget._header.setVisible(False)
                except Exception:
                    pass
                try:
                    pattern_widget.set_expanded(True)
                except Exception:
                    pass
            outer.addWidget(pattern_widget)

        # テキスト編集トグル行
        edit_bar = QFrame()
        edit_bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {design.panel};"
            f"  border-bottom: 1px solid {design.separator};"
            f"}}"
        )
        edit_bar_layout = QHBoxLayout(edit_bar)
        edit_bar_layout.setContentsMargins(8, 4, 8, 4)
        edit_bar_layout.setSpacing(6)

        title_lbl = QLabel("項目")
        title_lbl.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {design.text};")
        edit_bar_layout.addWidget(title_lbl)

        edit_bar_layout.addStretch(1)

        self._text_edit_btn = QPushButton("テキスト編集")
        self._text_edit_btn.setFont(QFont("Meiryo", 8))
        self._text_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text_edit_btn.setCheckable(True)
        self._text_edit_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 3px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
            f"QPushButton:checked {{ background-color: {design.accent}; }}"
        )
        self._text_edit_btn.toggled.connect(self._on_text_edit_toggled)
        self._text_edit_btn.setToolTip(
            "1 行 1 項目のテキストとしてまとめて編集する\n"
            "改行を含めたい項目は \" でブロックを囲む"
        )
        edit_bar_layout.addWidget(self._text_edit_btn)

        outer.addWidget(edit_bar)
        self._edit_bar = edit_bar

        # 中央: 行 UI と テキスト編集 UI を切り替えるスタック
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(
            f"QStackedWidget {{ background-color: {design.panel}; }}"
        )
        outer.addWidget(self._stack, stretch=1)

        # ── 行 UI 側（既存の items_widget をスクロールに包む）──
        self._rows_scroll = QScrollArea()
        self._rows_scroll.setWidgetResizable(True)
        self._rows_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._apply_scroll_style(self._rows_scroll, design)
        self._rows_content = QWidget()
        self._rows_content.setStyleSheet(
            f"background-color: {design.panel};"
        )
        self._rows_layout = QVBoxLayout(self._rows_content)
        self._rows_layout.setContentsMargins(8, 4, 8, 8)
        self._rows_layout.setSpacing(4)

        if items_widget is not None:
            # CollapsibleSection を渡された場合はヘッダーを隠して常時表示
            if hasattr(items_widget, "_header"):
                try:
                    items_widget._header.setVisible(False)
                except Exception:
                    pass
                try:
                    items_widget.set_expanded(True)
                except Exception:
                    pass
            self._rows_layout.addWidget(items_widget)

        self._rows_layout.addStretch()
        self._rows_scroll.setWidget(self._rows_content)
        self._stack.addWidget(self._rows_scroll)

        # ── テキスト編集 UI 側 ──
        self._text_container = QWidget()
        text_v = QVBoxLayout(self._text_container)
        text_v.setContentsMargins(8, 4, 8, 8)
        text_v.setSpacing(4)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setFont(QFont("Meiryo", 9))
        self._text_edit.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 4px;"
            f"}}"
        )
        self._text_edit.setPlaceholderText(
            "1 行 1 項目で入力。改行を含む項目は \"…\" のように \" で囲む"
        )
        # i284: テキスト編集モードでも入力途中でルーレットへ即時反映
        self._text_edit.textChanged.connect(self._on_text_edit_changed_live)
        text_v.addWidget(self._text_edit, stretch=1)

        # ヘルパー: 警告ラベル
        self._text_warn_lbl = QLabel("")
        self._text_warn_lbl.setFont(QFont("Meiryo", 8))
        self._text_warn_lbl.setStyleSheet(
            f"color: {design.gold}; padding: 2px 0;"
        )
        self._text_warn_lbl.setWordWrap(True)
        self._text_warn_lbl.setVisible(False)
        text_v.addWidget(self._text_warn_lbl)

        # 操作ボタン行
        text_btn_row = QHBoxLayout()
        text_btn_row.setSpacing(6)
        text_btn_row.addStretch(1)

        self._text_cancel_btn = QPushButton("キャンセル")
        self._text_cancel_btn.setFont(QFont("Meiryo", 8))
        self._text_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text_cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._text_cancel_btn.clicked.connect(self._on_text_cancel)
        text_btn_row.addWidget(self._text_cancel_btn)

        self._text_save_btn = QPushButton("保存")
        self._text_save_btn.setFont(QFont("Meiryo", 8, QFont.Weight.Bold))
        self._text_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text_save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.accent}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.separator}; }}"
        )
        self._text_save_btn.clicked.connect(self._on_text_save)
        text_btn_row.addWidget(self._text_save_btn)

        text_v.addLayout(text_btn_row)
        self._stack.addWidget(self._text_container)
        self._stack.setCurrentIndex(0)  # 行 UI を初期表示

        # 最小サイズ
        self.setMinimumWidth(260)
        self.setMinimumHeight(220)

        # 右下リサイズグリップ
        self._resize_grip = _PanelGrip(
            self, design, mode="panel",
            min_w=260, min_h=220, parent=self,
        )

    # ----------------------------------------------------------------
    #  テキスト編集モード
    # ----------------------------------------------------------------

    def _on_text_edit_toggled(self, on: bool):
        if on:
            # 行 UI → テキスト編集
            entries = self._settings_panel._item_entries
            text = serialize_items_text([e.text for e in entries])
            self._text_edit.blockSignals(True)
            self._text_edit.setPlainText(text)
            self._text_edit.blockSignals(False)
            self._text_warn_lbl.setVisible(False)
            self._stack.setCurrentIndex(1)
            self._text_edit.setFocus()
        else:
            # テキスト編集 → 行 UI（保存せずに戻る）
            self._stack.setCurrentIndex(0)

    def _on_text_save(self):
        raw = self._text_edit.toPlainText()
        parsed = parse_items_text(raw)
        if not parsed:
            # 全削除はしない（v0.4.4 互換）
            self._text_warn_lbl.setText("項目が 0 件になるため保存しません")
            self._text_warn_lbl.setVisible(True)
            return
        changed, warn = self._settings_panel.replace_entries_from_texts(parsed)
        if changed and warn:
            self._text_warn_lbl.setText(warn)
            self._text_warn_lbl.setVisible(True)
            # 上限切り詰め後の正規化テキストを再表示
            new_entries = self._settings_panel._item_entries
            self._text_edit.blockSignals(True)
            self._text_edit.setPlainText(
                serialize_items_text([e.text for e in new_entries])
            )
            self._text_edit.blockSignals(False)
        else:
            self._text_warn_lbl.setVisible(False)
        # 行 UI へ戻る
        self._text_edit_btn.blockSignals(True)
        self._text_edit_btn.setChecked(False)
        self._text_edit_btn.blockSignals(False)
        self._stack.setCurrentIndex(0)

    def _on_text_cancel(self):
        # 編集破棄して行 UI へ戻る
        self._text_edit_btn.blockSignals(True)
        self._text_edit_btn.setChecked(False)
        self._text_edit_btn.blockSignals(False)
        self._stack.setCurrentIndex(0)

    def _on_text_edit_changed_live(self):
        """i284: テキスト編集モードでの入力途中即時反映。

        - QPlainTextEdit の textChanged を受け、parse_items_text で解析した
          一覧をそのまま SettingsPanel の item_entries へ反映する。
        - enforce_item_limits で上限超過は黙ってカット（プレビュー中は警告
          ラベルを出さず、保存時にのみ警告する）。
        - 0 件は反映しない（v0.4.4 互換: 全削除はしない）。
        - 行 UI は再構築しない（テキスト編集モード中はスタックが切り替わって
          いるため、行 UI は隠れたまま）。
        """
        raw = self._text_edit.toPlainText()
        parsed = parse_items_text(raw)
        if not parsed:
            return
        trimmed, _changed, _warn = enforce_item_limits(list(parsed))
        if not trimmed:
            return
        self._settings_panel._live_update_from_text_entries(trimmed)

    # ----------------------------------------------------------------
    #  ドラッグ吸収（パネル外への伝播を防ぐ）
    # ----------------------------------------------------------------

    def mousePressEvent(self, event):
        # クリックしたパネルを最前面へ。ドラッグはバーからのみ。
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    # ----------------------------------------------------------------
    #  共通
    # ----------------------------------------------------------------

    @staticmethod
    def _apply_scroll_style(scroll: QScrollArea,
                            design: DesignSettings):
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {design.panel}; }}"
            f"QScrollBar:vertical {{ width: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:vertical {{ background: {design.separator}; border-radius: 3px; }}"
            f"QScrollBar:horizontal {{ height: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:horizontal {{ background: {design.separator}; border-radius: 3px; }}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_grip.reposition()
        self.geometry_changed.emit()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def update_design(self, design: DesignSettings):
        """デザイン変更時に配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._rows_content.setStyleSheet(
            f"background-color: {design.panel};"
        )
        self._apply_scroll_style(self._rows_scroll, design)
        self._resize_grip.update_design(design)
        self._drag_bar.update_design(design)


class ManagePanel(QFrame):
    """全体管理パネル (F1)。

    各パネルを見失わずに管理するための最小ハブ。トップレベル Tool window として
    生成し、メインウィンドウ最小化時にも独立して位置が保たれる。

    機能:
      - 項目パネル表示 / 非表示 (チェックボックス)
      - 設定パネル表示 / 非表示 (チェックボックス)
      - パネル位置初期化ボタン
      - F1/F2/F3 ショートカット案内
    """

    items_panel_toggled = Signal(bool)
    settings_panel_toggled = Signal(bool)
    reset_positions_requested = Signal()
    geometry_changed = Signal()

    def __init__(self, design: DesignSettings, *,
                 items_visible: bool = True,
                 settings_visible: bool = False,
                 parent=None):
        super().__init__(parent)
        self._design = design
        self.pinned_front = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 上部ドラッグバー (パネル移動の起点)
        self._drag_bar = _PanelDragBar(self, design, parent=self)
        outer.addWidget(self._drag_bar)
        # 右クリック → 移動バー表示/非表示
        install_panel_context_menu(self, self._drag_bar)

        # コンテンツ
        body = QFrame()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)

        title = QLabel("パネル管理")
        title.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {design.text};")
        body_layout.addWidget(title)

        self._items_cb = QCheckBox("項目パネルを表示 (F2)")
        self._items_cb.setFont(QFont("Meiryo", 9))
        self._items_cb.setStyleSheet(f"color: {design.text};")
        self._items_cb.setChecked(items_visible)
        self._items_cb.toggled.connect(self.items_panel_toggled.emit)
        body_layout.addWidget(self._items_cb)

        self._settings_cb = QCheckBox("設定パネルを表示 (F3)")
        self._settings_cb.setFont(QFont("Meiryo", 9))
        self._settings_cb.setStyleSheet(f"color: {design.text};")
        self._settings_cb.setChecked(settings_visible)
        self._settings_cb.toggled.connect(self.settings_panel_toggled.emit)
        body_layout.addWidget(self._settings_cb)

        body_layout.addSpacing(4)

        self._reset_btn = QPushButton("パネル位置を初期化")
        self._reset_btn.setFont(QFont("Meiryo", 9))
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 4px; padding: 6px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._reset_btn.clicked.connect(self.reset_positions_requested.emit)
        body_layout.addWidget(self._reset_btn)

        # i276: ショートカット説明はユーザー要請により削除。
        # 将来ヘルプを追加する余地を残してあるが、本セッションでは追加しない。

        body_layout.addStretch(1)

        body.setStyleSheet(f"background-color: {design.panel};")
        outer.addWidget(body, stretch=1)

        self.setStyleSheet(f"background-color: {design.panel};")
        self.setMinimumSize(220, 160)

    # ----------------------------------------------------------------
    #  公開 API
    # ----------------------------------------------------------------

    def set_items_visible(self, visible: bool):
        """項目パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._items_cb.blockSignals(True)
        self._items_cb.setChecked(visible)
        self._items_cb.blockSignals(False)

    def set_settings_visible(self, visible: bool):
        """設定パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._settings_cb.blockSignals(True)
        self._settings_cb.setChecked(visible)
        self._settings_cb.blockSignals(False)

    def update_design(self, design: DesignSettings):
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._drag_bar.update_design(design)

    # ----------------------------------------------------------------
    #  イベント
    # ----------------------------------------------------------------

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.geometry_changed.emit()

    def mousePressEvent(self, event):
        # クリックは吸収。ドラッグはドラッグバーからのみ。
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()


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
#  メインパネル
# ================================================================

class SettingsPanel(QFrame):
    """操作・設定パネル。

    Signals:
        spin_requested: spin 開始が要求された
        preset_changed(str): spin プリセットが変更された
        setting_changed(str, object): 設定値が変更された (key, value)
            key は AppSettings のフィールド名に対応する。
            MainWindow はこのシグナルを受けて該当コンポーネントを更新する。
        item_entries_changed(list): 項目データが変更された
            MainWindow はこのシグナルを受けて segments 再構築・保存を行う。
    """

    spin_requested = Signal()
    preset_changed = Signal(str)
    setting_changed = Signal(str, object)
    item_entries_changed = Signal(list)
    pattern_switched = Signal(str)      # パターン切替 (新パターン名)
    pattern_added = Signal(str)         # パターン追加 (新パターン名)
    pattern_deleted = Signal(str)       # パターン削除 (削除パターン名)
    preview_tick_requested = Signal()   # tick音テスト再生
    preview_win_requested = Signal()    # result音テスト再生
    log_clear_requested = Signal()     # 履歴クリア
    log_export_requested = Signal()    # ログエクスポート
    shuffle_once_requested = Signal()  # 単発ランダム再配置
    arrangement_reset_requested = Signal()  # i284: 並びリセット (v0.4.4 標準配置)
    items_reset_requested = Signal()        # i284: 項目一括リセット (v0.4.4 一括リセット)
    pattern_export_requested = Signal()  # パターンエクスポート
    pattern_import_requested = Signal()  # パターンインポート
    custom_tick_file_changed = Signal(str)  # カスタムtick音ファイル変更
    custom_win_file_changed = Signal(str)   # カスタムresult音ファイル変更
    design_editor_requested = Signal()       # デザインエディタ起動
    graph_requested = Signal()               # 勝利履歴グラフ起動
    replay_play_requested = Signal()         # 最新リプレイ再生
    replay_stop_requested = Signal()         # リプレイ中断
    replay_manager_requested = Signal()      # リプレイ管理ウィンドウ起動
    geometry_changed = Signal()

    def __init__(self, item_entries: list[ItemEntry], settings: AppSettings,
                 design: DesignSettings, *,
                 pattern_names: list[str] | None = None,
                 current_pattern: str = "デフォルト",
                 parent=None):
        """操作・設定パネル。

        Args:
            item_entries: 項目データ（bridge.load_item_entries() の戻り値）。
                設定データ（AppSettings）とは別管理。各項目のテキスト・
                確率・分割等を保持する ItemEntry のリスト。
            settings: アプリ設定データ（AppSettings）。
            design: デザイン設定。
            pattern_names: パターン名一覧（None なら ["デフォルト"]）。
            current_pattern: 現在選択中のパターン名。
        """
        super().__init__(parent)
        self._design = design
        self._settings = settings
        self._item_entries = item_entries
        self.setStyleSheet(f"background-color: {design.panel};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 上部ドラッグバー（パネルを掴んで移動するための常時有効ハンドル）──
        # 折りたたみセクション展開中はクライアント領域全面が widgets で
        # 埋まりドラッグ起点が無くなるため、常時表示のドラッグバーを置く。
        self._drag_bar = _PanelDragBar(self, design, parent=self)
        outer.addWidget(self._drag_bar)
        # 右クリック → 移動バー表示/非表示
        install_panel_context_menu(self, self._drag_bar)

        # ── 常設クイック設定行（透過 / 常に最前面）──
        # v0.4.4 cfg_panel の「ウィンドウ表示」グループ相当。
        # 折りたたみセクションの中ではなく、常時見える場所に置くことで
        # 「OBS透過モード」がユーザーから辿りやすい状態にする。
        self._build_quick_settings_bar(outer, settings, design)

        # ── 1つのスクロール領域にアプリ設定 + 項目リストを縦並び ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._apply_scroll_style(self._scroll, design)

        self._content = QWidget()
        self._content.setStyleSheet(
            f"background-color: {design.panel};"
        )
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)

        # ── アプリ設定セクション ──
        self._build_spin_section(settings, design)
        self._build_display_section(settings, design)
        self._build_design_section(settings, design)
        self._build_result_section(settings, design)
        self._build_sound_section(settings, design)
        self._build_log_section(settings, design)
        self._build_replay_section(settings, design)

        # ── パターン管理セクション ──
        self._pattern_names = list(pattern_names or ["デフォルト"])
        self._current_pattern = current_pattern
        self._build_pattern_section(design)

        # ── 項目データセクション ──
        self._build_items_section(item_entries, design)
        self._build_item_edit_sections(design)

        # ── 折りたたみ状態の復元とシグナル接続 ──
        self._collapsible_map: dict[str, CollapsibleSection] = {
            "spin": self._spin_collapsible,
            "display": self._display_section,
            "design": self._design_collapsible,
            "result": self._result_collapsible,
            "sound": self._sound_collapsible,
            "log": self._log_collapsible,
            "replay": self._replay_collapsible,
            "pattern": self._pattern_collapsible,
            "items": self._items_collapsible,
        }
        # アニメーション時間の初期適用
        for cs in self._collapsible_map.values():
            cs.set_anim_duration(settings.collapse_anim_ms)
        saved = settings.collapsed_sections
        if saved:
            for name, cs in self._collapsible_map.items():
                if name in saved:
                    cs.set_expanded(not saved[name])
        # 排他開閉の正規化: 展開セクションが2個以上なら最初の1個だけ残す
        expanded = [n for n, cs in self._collapsible_map.items()
                    if not cs.is_collapsed]
        self._sections_normalized = len(expanded) > 1
        if self._sections_normalized:
            for name in expanded[1:]:
                self._collapsible_map[name].set_expanded(False)
        for name, cs in self._collapsible_map.items():
            cs.toggled.connect(
                lambda collapsed, _n=name: self._on_section_toggled(_n, collapsed)
            )
        # 正規化で変更があった場合、保存フローへ反映
        if self._sections_normalized:
            self._emit_collapsed_state()

        self._layout.addStretch()

        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

        # ── 最小幅: contentsMargins + スクロールバー幅 + つまみ逃がし ──
        scrollbar_w = self._scroll.verticalScrollBar().sizeHint().width()
        content_margins = self._layout.contentsMargins()
        margins_total = content_margins.left() + content_margins.right()
        # SIDEBAR_W をベースに、スクロールバーとマージンを加味
        self._panel_min_w = max(SIDEBAR_W, 200 + margins_total + scrollbar_w + 20)

        # ── 右下リサイズグリップ（パネル幅変更用） ──
        self._resize_grip = _PanelGrip(
            self, design, mode="panel", min_w=self._panel_min_w, parent=self
        )

        # パネル最小幅
        self.setMinimumWidth(self._panel_min_w)

        # ── パネル前後関係 ──
        self.pinned_front = False  # True: 通常パネルより常に上に表示

        # ── フローティング独立化状態 ──
        self._floating = False

        # ── パネルドラッグ状態 ──
        self._dragging_panel = False
        self._panel_drag_start = QPoint()
        self._panel_start_pos = QPoint()

        # ── 項目 / パターンセクションの外部化フラグ ──
        # ItemPanel に reparent されたあと、settings 側の排他開閉などで
        # これらのセクションを誤って閉じないようスキップする目印。
        self._items_external = False
        self._pattern_external = False

    # ================================================================
    #  折りたたみ状態の保存
    # ================================================================

    def _emit_collapsed_state(self):
        """現在の折りたたみ状態を保存フローへ送出する。"""
        state = {
            name: cs.is_collapsed
            for name, cs in self._collapsible_map.items()
        }
        self.setting_changed.emit("collapsed_sections", state)

    def _build_quick_settings_bar(self, outer_layout: QVBoxLayout,
                                   settings: AppSettings,
                                   design: DesignSettings):
        """常設のクイック設定行を組み立てる。

        v0.4.4 cfg_panel の「ウィンドウ表示」グループに相当。
        透過 (ウィンドウ / ルーレット個別) と常に最前面を、折りたたみ
        セクションの外に常設で配置する。
        """
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {design.panel};"
            f"  border-bottom: 1px solid {design.separator};"
            f"}}"
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(10)

        # ウィンドウ透過 (メインウィンドウ自体)
        self._window_transparent_cb = QCheckBox("ウィンドウ透過")
        self._window_transparent_cb.setFont(QFont("Meiryo", 8))
        self._window_transparent_cb.setStyleSheet(f"color: {design.text};")
        self._window_transparent_cb.setChecked(settings.window_transparent)
        self._window_transparent_cb.setToolTip(
            "メインウィンドウ自体の背景を透過する"
        )
        self._window_transparent_cb.toggled.connect(
            lambda v: self.setting_changed.emit("window_transparent", v)
        )
        bar_layout.addWidget(self._window_transparent_cb)

        # ルーレット透過 (ルーレットパネル単独)
        self._roulette_transparent_cb = QCheckBox("ルーレット透過")
        self._roulette_transparent_cb.setFont(QFont("Meiryo", 8))
        self._roulette_transparent_cb.setStyleSheet(f"color: {design.text};")
        self._roulette_transparent_cb.setChecked(settings.roulette_transparent)
        self._roulette_transparent_cb.setToolTip(
            "ルーレットパネル (ホイール領域) の背景を透過する"
        )
        self._roulette_transparent_cb.toggled.connect(
            lambda v: self.setting_changed.emit("roulette_transparent", v)
        )
        bar_layout.addWidget(self._roulette_transparent_cb)

        # 常に最前面
        self._aot_cb = QCheckBox("最前面")
        self._aot_cb.setFont(QFont("Meiryo", 8))
        self._aot_cb.setStyleSheet(f"color: {design.text};")
        self._aot_cb.setChecked(settings.always_on_top)
        self._aot_cb.setToolTip("メインウィンドウを常に最前面に表示")
        self._aot_cb.toggled.connect(
            lambda v: self.setting_changed.emit("always_on_top", v)
        )
        bar_layout.addWidget(self._aot_cb)

        bar_layout.addStretch(1)

        outer_layout.addWidget(bar)
        self._quick_bar = bar

    def _on_section_toggled(self, toggled_name: str, collapsed: bool):
        """いずれかのセクションが開閉されたとき、排他開閉＋状態保存を行う。"""
        if not collapsed:
            # 開いた場合: 他の展開中セクションを閉じる
            for name, cs in self._collapsible_map.items():
                if name != toggled_name and not cs.is_collapsed:
                    # 外部化された項目 / パターンセクションは閉じない
                    if name == "items" and self._items_external:
                        continue
                    if name == "pattern" and self._pattern_external:
                        continue
                    cs.set_expanded(False)
        self._emit_collapsed_state()

    def pop_pattern_section(self) -> QWidget:
        """パターン (グループ) セクションを SettingsPanel から取り外して返す。

        ItemPanel など別フレームへ載せ替えるためのフック。
        - 親レイアウトから取り外す
        - 外部化フラグを立てて、排他開閉の対象から除外する
        - toggled シグナルを切断
        """
        if self._pattern_external:
            return self._pattern_collapsible

        self._layout.removeWidget(self._pattern_collapsible)
        self._pattern_collapsible.setParent(None)
        try:
            self._pattern_collapsible.toggled.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._pattern_external = True
        return self._pattern_collapsible

    def pop_items_section(self) -> QWidget:
        """項目セクションを SettingsPanel から取り外して返す。

        ItemPanel など別フレームへ載せ替えるためのフック。
        - 親レイアウトから取り外す
        - 外部化フラグを立てて、排他開閉の対象から除外する
        - toggled シグナルを切断し、別パネル内での開閉が SettingsPanel
          の他セクションを誤って閉じないようにする
        - 戻り値は `_items_collapsible` (CollapsibleSection)。
          呼び出し側で新しい親へ addWidget することを想定する。
        """
        if self._items_external:
            return self._items_collapsible

        self._layout.removeWidget(self._items_collapsible)
        self._items_collapsible.setParent(None)
        try:
            self._items_collapsible.toggled.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._items_external = True
        return self._items_collapsible

    # ================================================================
    #  セクション 1: スピン操作（実装済み）
    # ================================================================

    def _build_spin_section(self, settings: AppSettings,
                            design: DesignSettings):
        # スピンセクション全体をコンテナで囲む（ctrl_box_visible で一括制御用）
        self._spin_collapsible = CollapsibleSection("スピン", design, expanded=True, theme_mode=settings.theme_mode)
        self._spin_section = self._spin_collapsible
        spin_layout = self._spin_collapsible.content_layout

        # spin ボタン
        self._spin_btn = QPushButton("▶  スピン開始")
        self._spin_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._spin_btn.setMinimumHeight(36)
        self._spin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_spin_btn_style(design)
        self._spin_btn.clicked.connect(self.spin_requested.emit)
        spin_layout.addWidget(self._spin_btn)

        # プリセット選択
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)

        preset_lbl = QLabel("プリセット:")
        preset_lbl.setFont(QFont("Meiryo", 8))
        preset_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._preset_lbl = preset_lbl
        preset_row.addWidget(preset_lbl)

        self._preset_combo = QComboBox()
        self._preset_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._preset_combo, design)
        for name in SPIN_PRESET_NAMES:
            self._preset_combo.addItem(name)
        self._preset_combo.setCurrentText(DEFAULT_PRESET_NAME)
        self._preset_combo.currentTextChanged.connect(self.preset_changed.emit)
        preset_row.addWidget(self._preset_combo, stretch=1)

        spin_layout.addLayout(preset_row)

        # スピン時間
        dur_row = QHBoxLayout()
        dur_row.setSpacing(4)

        dur_lbl = QLabel("スピン時間:")
        dur_lbl.setFont(QFont("Meiryo", 8))
        dur_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dur_lbl = dur_lbl
        dur_row.addWidget(dur_lbl)

        self._dur_spin = QDoubleSpinBox()
        self._dur_spin.setFont(QFont("Meiryo", 8))
        self._dur_spin.setRange(1.0, 30.0)
        self._dur_spin.setSingleStep(1.0)
        self._dur_spin.setDecimals(1)
        self._dur_spin.setSuffix(" 秒")
        self._dur_spin.setValue(settings.spin_duration)
        self._dur_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._dur_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("spin_duration", v)
        )
        dur_row.addWidget(self._dur_spin, stretch=1)

        spin_layout.addLayout(dur_row)

        # スピンモード選択
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)

        mode_lbl = QLabel("モード:")
        mode_lbl.setFont(QFont("Meiryo", 8))
        mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._mode_lbl = mode_lbl
        mode_row.addWidget(mode_lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._mode_combo, design)
        self._mode_combo.addItems(["シングル", "ダブル", "トリプル"])
        self._mode_combo.setCurrentIndex(settings.spin_mode)
        self._mode_combo.currentIndexChanged.connect(self._on_spin_mode_changed)
        mode_row.addWidget(self._mode_combo, stretch=1)

        spin_layout.addLayout(mode_row)

        # ダブルスピン時間
        dbl_row = QHBoxLayout()
        dbl_row.setSpacing(4)

        dbl_lbl = QLabel("ダブル時間:")
        dbl_lbl.setFont(QFont("Meiryo", 8))
        dbl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dbl_lbl = dbl_lbl
        dbl_row.addWidget(dbl_lbl)

        self._dbl_spin = QDoubleSpinBox()
        self._dbl_spin.setFont(QFont("Meiryo", 8))
        self._dbl_spin.setRange(1.0, 30.0)
        self._dbl_spin.setSingleStep(1.0)
        self._dbl_spin.setDecimals(1)
        self._dbl_spin.setSuffix(" 秒")
        self._dbl_spin.setValue(settings.double_duration)
        self._dbl_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._dbl_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("double_duration", v)
        )
        dbl_row.addWidget(self._dbl_spin, stretch=1)

        self._dbl_row_widget = QWidget()
        dbl_row_container = QHBoxLayout(self._dbl_row_widget)
        dbl_row_container.setContentsMargins(0, 0, 0, 0)
        dbl_row_container.setSpacing(4)
        dbl_row_container.addWidget(self._dbl_lbl)
        dbl_row_container.addWidget(self._dbl_spin, stretch=1)
        spin_layout.addWidget(self._dbl_row_widget)

        # トリプルスピン時間
        self._tpl_row_widget = QWidget()
        tpl_row_container = QHBoxLayout(self._tpl_row_widget)
        tpl_row_container.setContentsMargins(0, 0, 0, 0)
        tpl_row_container.setSpacing(4)

        tpl_lbl = QLabel("トリプル時間:")
        tpl_lbl.setFont(QFont("Meiryo", 8))
        tpl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tpl_lbl = tpl_lbl
        tpl_row_container.addWidget(tpl_lbl)

        self._tpl_spin = QDoubleSpinBox()
        self._tpl_spin.setFont(QFont("Meiryo", 8))
        self._tpl_spin.setRange(1.0, 30.0)
        self._tpl_spin.setSingleStep(1.0)
        self._tpl_spin.setDecimals(1)
        self._tpl_spin.setSuffix(" 秒")
        self._tpl_spin.setValue(settings.triple_duration)
        self._tpl_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._tpl_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("triple_duration", v)
        )
        tpl_row_container.addWidget(self._tpl_spin, stretch=1)
        spin_layout.addWidget(self._tpl_row_widget)

        # 初期表示: モードに応じて duration 行の表示/非表示
        self._update_duration_rows_visibility(settings.spin_mode)

        self._layout.addWidget(self._spin_collapsible)

    def _on_spin_mode_changed(self, index: int):
        """スピンモード変更時のハンドラ。"""
        self._update_duration_rows_visibility(index)
        self.setting_changed.emit("spin_mode", index)

    def _update_duration_rows_visibility(self, mode: int):
        """スピンモードに応じて duration 行の表示を切り替える。"""
        # シングル: 通常スピン時間のみ表示
        # ダブル: ダブル時間のみ表示（通常時間は非表示）
        # トリプル: トリプル時間のみ表示（通常時間は非表示）
        self._dur_lbl.setVisible(mode == 0)
        self._dur_spin.setVisible(mode == 0)
        self._dbl_row_widget.setVisible(mode == 1)
        self._tpl_row_widget.setVisible(mode == 2)

    # ================================================================
    #  セクション 2: 表示設定（実装済み）
    # ================================================================

    def _build_display_section(self, settings: AppSettings,
                               design: DesignSettings):
        self._display_section = CollapsibleSection("表示", design, expanded=True, theme_mode=settings.theme_mode)
        sec = self._display_section.content_layout
        self._layout.addWidget(self._display_section)

        # テーマモード
        theme_row = QHBoxLayout()
        theme_row.setSpacing(4)
        theme_lbl = QLabel("テーマ:")
        theme_lbl.setFont(QFont("Meiryo", 8))
        theme_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._theme_lbl = theme_lbl
        theme_row.addWidget(theme_lbl)

        self._theme_combo = QComboBox()
        self._theme_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._theme_combo, design)
        self._theme_combo.addItems(["ダーク", "ライト", "システム"])
        _theme_idx_map = {"dark": 0, "light": 1, "system": 2, "auto": 2}
        self._theme_combo.setCurrentIndex(
            _theme_idx_map.get(settings.theme_mode, 0)
        )
        _theme_val_map = ["dark", "light", "system"]
        self._theme_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit(
                "theme_mode", _theme_val_map[idx] if idx < len(_theme_val_map) else "dark"
            )
        )
        theme_row.addWidget(self._theme_combo, stretch=1)
        sec.addLayout(theme_row)

        # テキスト表示モード
        text_row = QHBoxLayout()
        text_row.setSpacing(4)
        text_lbl = QLabel("テキスト:")
        text_lbl.setFont(QFont("Meiryo", 8))
        text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._text_lbl = text_lbl
        text_row.addWidget(text_lbl)

        self._text_mode_combo = QComboBox()
        self._text_mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._text_mode_combo, design)
        for name in ["省略", "収める", "縮小"]:
            self._text_mode_combo.addItem(name)
        self._text_mode_combo.setCurrentIndex(settings.text_size_mode)
        self._text_mode_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("text_size_mode", idx)
        )
        text_row.addWidget(self._text_mode_combo, stretch=1)
        sec.addLayout(text_row)

        # ドーナツ穴
        self._donut_cb = QCheckBox("ドーナツ穴")
        self._donut_cb.setFont(QFont("Meiryo", 8))
        self._donut_cb.setStyleSheet(f"color: {design.text};")
        self._donut_cb.setChecked(settings.donut_hole)
        self._donut_cb.toggled.connect(
            lambda v: self.setting_changed.emit("donut_hole", v)
        )
        sec.addWidget(self._donut_cb)

        # 透過モード はクイック設定バー（パネル上部）に常設化したため
        # ここには配置しない。

        # リサイズグリップ表示
        self._grip_visible_cb = QCheckBox("リサイズグリップ表示")
        self._grip_visible_cb.setFont(QFont("Meiryo", 8))
        self._grip_visible_cb.setStyleSheet(f"color: {design.text};")
        self._grip_visible_cb.setChecked(settings.grip_visible)
        self._grip_visible_cb.toggled.connect(
            lambda v: self.setting_changed.emit("grip_visible", v)
        )
        sec.addWidget(self._grip_visible_cb)

        # コントロールボックス表示（ドラッグバー）
        self._ctrl_box_visible_cb = QCheckBox("コントロールボックス表示")
        self._ctrl_box_visible_cb.setFont(QFont("Meiryo", 8))
        self._ctrl_box_visible_cb.setStyleSheet(f"color: {design.text};")
        self._ctrl_box_visible_cb.setChecked(settings.ctrl_box_visible)
        self._ctrl_box_visible_cb.toggled.connect(
            lambda v: self.setting_changed.emit("ctrl_box_visible", v)
        )
        sec.addWidget(self._ctrl_box_visible_cb)

        # インスタンス番号表示
        self._instance_label_cb = QCheckBox("インスタンス番号表示")
        self._instance_label_cb.setFont(QFont("Meiryo", 8))
        self._instance_label_cb.setStyleSheet(f"color: {design.text};")
        self._instance_label_cb.setChecked(settings.float_win_show_instance)
        self._instance_label_cb.toggled.connect(
            lambda v: self.setting_changed.emit("float_win_show_instance", v)
        )
        sec.addWidget(self._instance_label_cb)

        # 設定パネルフローティング
        self._float_panel_cb = QCheckBox("設定パネル独立化")
        self._float_panel_cb.setFont(QFont("Meiryo", 8))
        self._float_panel_cb.setStyleSheet(f"color: {design.text};")
        self._float_panel_cb.setChecked(settings.settings_panel_float)
        self._float_panel_cb.toggled.connect(
            lambda v: self.setting_changed.emit("settings_panel_float", v)
        )
        sec.addWidget(self._float_panel_cb)

        # サイズプロファイル
        prof_row = QHBoxLayout()
        prof_row.setSpacing(4)
        prof_lbl = QLabel("サイズ:")
        prof_lbl.setFont(QFont("Meiryo", 8))
        prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._prof_lbl = prof_lbl
        prof_row.addWidget(prof_lbl)

        self._prof_combo = QComboBox()
        self._prof_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._prof_combo, design)
        for label, w, h in SIZE_PROFILES:
            self._prof_combo.addItem(f"{label}  ({w}x{h})")
        prof_idx = min(settings.profile_idx, len(SIZE_PROFILES) - 1)
        self._prof_combo.setCurrentIndex(prof_idx)
        self._prof_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("profile_idx", idx)
        )
        prof_row.addWidget(self._prof_combo, stretch=1)
        sec.addLayout(prof_row)

        # テキスト方向
        tdir_row = QHBoxLayout()
        tdir_row.setSpacing(4)
        tdir_lbl = QLabel("テキスト方向:")
        tdir_lbl.setFont(QFont("Meiryo", 8))
        tdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tdir_lbl = tdir_lbl
        tdir_row.addWidget(tdir_lbl)

        self._tdir_combo = QComboBox()
        self._tdir_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._tdir_combo, design)
        for name in ["横(回転)", "横(水平)", "縦上", "縦下", "縦直立"]:
            self._tdir_combo.addItem(name)
        self._tdir_combo.setCurrentIndex(settings.text_direction)
        self._tdir_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("text_direction", idx)
        )
        tdir_row.addWidget(self._tdir_combo, stretch=1)
        sec.addLayout(tdir_row)

        # スピン回転方向
        sdir_row = QHBoxLayout()
        sdir_row.setSpacing(4)
        sdir_lbl = QLabel("回転方向:")
        sdir_lbl.setFont(QFont("Meiryo", 8))
        sdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._sdir_lbl = sdir_lbl
        sdir_row.addWidget(sdir_lbl)

        self._sdir_combo = QComboBox()
        self._sdir_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._sdir_combo, design)
        for name in ["反時計回り", "時計回り"]:
            self._sdir_combo.addItem(name)
        self._sdir_combo.setCurrentIndex(settings.spin_direction)
        self._sdir_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("spin_direction", idx)
        )
        sdir_row.addWidget(self._sdir_combo, stretch=1)
        sec.addLayout(sdir_row)

        # ポインター位置
        ptr_row = QHBoxLayout()
        ptr_row.setSpacing(4)
        ptr_lbl = QLabel("ポインター:")
        ptr_lbl.setFont(QFont("Meiryo", 8))
        ptr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._ptr_lbl = ptr_lbl
        ptr_row.addWidget(ptr_lbl)

        self._ptr_combo = QComboBox()
        self._ptr_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._ptr_combo, design)
        for name in POINTER_PRESET_NAMES:
            self._ptr_combo.addItem(name)
        # 現在の pointer_angle からプリセットインデックスを逆引き
        ptr_preset_idx = self._angle_to_preset_idx(settings.pointer_angle)
        self._ptr_combo.setCurrentIndex(ptr_preset_idx)
        self._ptr_combo.currentIndexChanged.connect(self._on_pointer_preset_changed)
        ptr_row.addWidget(self._ptr_combo, stretch=1)
        sec.addLayout(ptr_row)

        # 折りたたみアニメーション時間
        anim_row = QHBoxLayout()
        anim_row.setSpacing(4)
        anim_lbl = QLabel("アニメ速度:")
        anim_lbl.setFont(QFont("Meiryo", 8))
        anim_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._anim_lbl = anim_lbl
        anim_row.addWidget(anim_lbl)

        self._anim_spin = QSpinBox()
        self._anim_spin.setFont(QFont("Meiryo", 8))
        self._anim_spin.setRange(0, 500)
        self._anim_spin.setSingleStep(50)
        self._anim_spin.setSuffix(" ms")
        self._anim_spin.setValue(settings.collapse_anim_ms)
        self._anim_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._anim_spin.valueChanged.connect(self._on_anim_duration_changed)
        anim_row.addWidget(self._anim_spin, stretch=1)
        sec.addLayout(anim_row)

    def _on_anim_duration_changed(self, value: int):
        """アニメーション時間変更時: 全セクションへ即時反映 + 保存。"""
        for cs in self._collapsible_map.values():
            cs.set_anim_duration(value)
        self.setting_changed.emit("collapse_anim_ms", value)

    @staticmethod
    def _angle_to_preset_idx(angle: float) -> int:
        """pointer_angle からプリセットインデックスを逆引きする。"""
        for i, a in enumerate(_POINTER_PRESET_ANGLES):
            if abs(angle - a) < 1.0:
                return i
        return len(POINTER_PRESET_NAMES) - 1  # 任意

    def _on_pointer_preset_changed(self, idx: int):
        """ポインタープリセット変更時のハンドラ。"""
        if idx < len(_POINTER_PRESET_ANGLES):
            angle = _POINTER_PRESET_ANGLES[idx]
            self.setting_changed.emit("pointer_angle", angle)

    # ================================================================
    #  セクション: デザイン設定
    # ================================================================

    def _build_design_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._design_collapsible = CollapsibleSection("デザイン", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._design_collapsible.content_layout
        self._layout.addWidget(self._design_collapsible)

        self._design_editor_btn = QPushButton("デザインエディタを開く")
        self._design_editor_btn.setFont(QFont("Meiryo", 9))
        self._design_editor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._design_editor_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 6px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._design_editor_btn.clicked.connect(
            self.design_editor_requested.emit
        )
        sec.addWidget(self._design_editor_btn)

    # ================================================================
    #  セクション 3: 結果表示設定（実装済み）
    # ================================================================

    def _build_result_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._result_collapsible = CollapsibleSection("結果表示", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._result_collapsible.content_layout
        self._layout.addWidget(self._result_collapsible)

        # 閉じ方モード
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_lbl = QLabel("閉じ方:")
        mode_lbl.setFont(QFont("Meiryo", 8))
        mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_mode_lbl = mode_lbl
        mode_row.addWidget(mode_lbl)

        self._result_mode_combo = QComboBox()
        self._result_mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._result_mode_combo, design)
        for name in ["クリック", "自動", "両方"]:
            self._result_mode_combo.addItem(name)
        self._result_mode_combo.setCurrentIndex(settings.result_close_mode)
        self._result_mode_combo.currentIndexChanged.connect(
            self._on_result_mode_changed
        )
        mode_row.addWidget(self._result_mode_combo, stretch=1)
        sec.addLayout(mode_row)

        # 保持秒数
        sec_row = QHBoxLayout()
        sec_row.setSpacing(4)
        sec_lbl = QLabel("保持秒数:")
        sec_lbl.setFont(QFont("Meiryo", 8))
        sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_sec_lbl = sec_lbl
        sec_row.addWidget(sec_lbl)

        self._result_sec_spin = QDoubleSpinBox()
        self._result_sec_spin.setFont(QFont("Meiryo", 8))
        self._result_sec_spin.setRange(0.5, 30.0)
        self._result_sec_spin.setSingleStep(0.5)
        self._result_sec_spin.setDecimals(1)
        self._result_sec_spin.setSuffix(" 秒")
        self._result_sec_spin.setValue(settings.result_hold_sec)
        self._result_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._result_sec_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("result_hold_sec", v)
        )
        sec_row.addWidget(self._result_sec_spin, stretch=1)
        sec.addLayout(sec_row)

        # 再生時保持秒数（チェックボックスで通常保持の継承/個別設定を切替）
        macro_cb_row = QHBoxLayout()
        macro_cb_row.setSpacing(4)
        self._macro_hold_cb = QCheckBox("マクロ再生時の保持を個別設定")
        self._macro_hold_cb.setFont(QFont("Meiryo", 8))
        self._macro_hold_cb.setStyleSheet(f"color: {design.text_sub};")
        macro_cb_row.addWidget(self._macro_hold_cb)
        sec.addLayout(macro_cb_row)

        macro_sec_row = QHBoxLayout()
        macro_sec_row.setSpacing(4)
        self._macro_sec_lbl = QLabel("  マクロ時:")
        self._macro_sec_lbl.setFont(QFont("Meiryo", 8))
        self._macro_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        macro_sec_row.addWidget(self._macro_sec_lbl)

        self._macro_sec_spin = QDoubleSpinBox()
        self._macro_sec_spin.setFont(QFont("Meiryo", 8))
        self._macro_sec_spin.setRange(0.5, 30.0)
        self._macro_sec_spin.setSingleStep(0.5)
        self._macro_sec_spin.setDecimals(1)
        self._macro_sec_spin.setSuffix(" 秒")
        self._macro_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )

        is_custom = settings.macro_hold_sec is not None
        self._macro_hold_cb.setChecked(is_custom)
        if is_custom:
            self._macro_sec_spin.setValue(settings.macro_hold_sec)
        else:
            self._macro_sec_spin.setValue(settings.result_hold_sec)
        self._macro_sec_spin.setEnabled(is_custom)
        self._macro_sec_lbl.setEnabled(is_custom)

        self._macro_hold_cb.toggled.connect(self._on_macro_hold_toggled)
        self._macro_sec_spin.valueChanged.connect(self._on_macro_hold_value_changed)

        macro_sec_row.addWidget(self._macro_sec_spin, stretch=1)
        sec.addLayout(macro_sec_row)

        # 保持秒数の有効/無効を閉じ方モードに連動
        self._update_hold_sec_enabled()

    def _on_result_mode_changed(self, idx: int):
        """閉じ方モード変更時のハンドラ。"""
        self.setting_changed.emit("result_close_mode", idx)
        self._update_hold_sec_enabled()

    def _update_hold_sec_enabled(self):
        """保持秒数の入力を閉じ方モードに応じて有効/無効化する。"""
        mode = self._result_mode_combo.currentIndex()
        enabled = mode in (1, 2)  # 自動 or 両方
        self._result_sec_spin.setEnabled(enabled)

    def _on_macro_hold_toggled(self, checked: bool):
        """再生時保持の個別設定チェックボックス切替。"""
        self._macro_sec_spin.setEnabled(checked)
        self._macro_sec_lbl.setEnabled(checked)
        if checked:
            self.setting_changed.emit("macro_hold_sec",
                                      self._macro_sec_spin.value())
        else:
            # 未設定に戻す: 表示を通常保持の現在値に追従させる
            self._macro_sec_spin.blockSignals(True)
            self._macro_sec_spin.setValue(self._result_sec_spin.value())
            self._macro_sec_spin.blockSignals(False)
            self.setting_changed.emit("macro_hold_sec", None)

    def _on_macro_hold_value_changed(self, value: float):
        """再生時保持のスピンボックス値変更。"""
        if self._macro_hold_cb.isChecked():
            self.setting_changed.emit("macro_hold_sec", value)

    # ================================================================
    #  セクション 3b: サウンド設定（AppSettings 側）
    # ================================================================

    def _build_sound_section(self, settings: AppSettings,
                             design: DesignSettings):
        self._sound_collapsible = CollapsibleSection("サウンド", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._sound_collapsible.content_layout
        self._layout.addWidget(self._sound_collapsible)

        # tick 音 ON/OFF
        self._sound_tick_cb = QCheckBox("スピン音")
        self._sound_tick_cb.setFont(QFont("Meiryo", 8))
        self._sound_tick_cb.setStyleSheet(f"color: {design.text};")
        self._sound_tick_cb.setChecked(settings.sound_tick_enabled)
        self._sound_tick_cb.toggled.connect(
            lambda v: self.setting_changed.emit("sound_tick_enabled", v)
        )
        sec.addWidget(self._sound_tick_cb)

        # result 音 ON/OFF
        self._sound_result_cb = QCheckBox("決定音")
        self._sound_result_cb.setFont(QFont("Meiryo", 8))
        self._sound_result_cb.setStyleSheet(f"color: {design.text};")
        self._sound_result_cb.setChecked(settings.sound_result_enabled)
        self._sound_result_cb.toggled.connect(
            lambda v: self.setting_changed.emit("sound_result_enabled", v)
        )
        sec.addWidget(self._sound_result_cb)

        # tick 音量スライダー
        tick_vol_row = QHBoxLayout()
        tick_vol_row.setSpacing(4)
        tick_vol_lbl = QLabel("スピン音量:")
        tick_vol_lbl.setFont(QFont("Meiryo", 8))
        tick_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tick_vol_lbl = tick_vol_lbl
        tick_vol_row.addWidget(tick_vol_lbl)

        self._tick_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._tick_vol_slider.setRange(0, 100)
        self._tick_vol_slider.setValue(settings.tick_volume)
        self._tick_vol_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{"
            f"  background: {design.separator}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {design.accent}; width: 12px; margin: -4px 0;"
            f"  border-radius: 6px;"
            f"}}"
        )
        self._tick_vol_slider.valueChanged.connect(
            lambda v: self.setting_changed.emit("tick_volume", v)
        )
        tick_vol_row.addWidget(self._tick_vol_slider, stretch=1)

        self._tick_vol_val = QLabel(f"{settings.tick_volume}%")
        self._tick_vol_val.setFont(QFont("Meiryo", 7))
        self._tick_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._tick_vol_val.setFixedWidth(32)
        self._tick_vol_slider.valueChanged.connect(
            lambda v: self._tick_vol_val.setText(f"{v}%")
        )
        tick_vol_row.addWidget(self._tick_vol_val)
        sec.addLayout(tick_vol_row)

        # result 音量スライダー
        win_vol_row = QHBoxLayout()
        win_vol_row.setSpacing(4)
        win_vol_lbl = QLabel("決定音量:")
        win_vol_lbl.setFont(QFont("Meiryo", 8))
        win_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_lbl = win_vol_lbl
        win_vol_row.addWidget(win_vol_lbl)

        self._win_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._win_vol_slider.setRange(0, 100)
        self._win_vol_slider.setValue(settings.win_volume)
        self._win_vol_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{"
            f"  background: {design.separator}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {design.accent}; width: 12px; margin: -4px 0;"
            f"  border-radius: 6px;"
            f"}}"
        )
        self._win_vol_slider.valueChanged.connect(
            lambda v: self.setting_changed.emit("win_volume", v)
        )
        win_vol_row.addWidget(self._win_vol_slider, stretch=1)

        self._win_vol_val = QLabel(f"{settings.win_volume}%")
        self._win_vol_val.setFont(QFont("Meiryo", 7))
        self._win_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_val.setFixedWidth(32)
        self._win_vol_slider.valueChanged.connect(
            lambda v: self._win_vol_val.setText(f"{v}%")
        )
        win_vol_row.addWidget(self._win_vol_val)
        sec.addLayout(win_vol_row)

        # tick 音パターン選択
        from sound_manager import TICK_PATTERN_NAMES, WIN_PATTERN_NAMES
        self._TICK_CUSTOM_IDX = len(TICK_PATTERN_NAMES) - 1
        self._WIN_CUSTOM_IDX = len(WIN_PATTERN_NAMES) - 1

        tick_pat_row = QHBoxLayout()
        tick_pat_row.setSpacing(4)
        tick_pat_lbl = QLabel("スピン音:")
        tick_pat_lbl.setFont(QFont("Meiryo", 8))
        tick_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tick_pat_lbl = tick_pat_lbl
        tick_pat_row.addWidget(tick_pat_lbl)

        self._tick_pat_combo = QComboBox()
        self._tick_pat_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._tick_pat_combo, design)
        for name in TICK_PATTERN_NAMES:
            self._tick_pat_combo.addItem(name)
        self._tick_pat_combo.setCurrentIndex(
            min(settings.tick_pattern, len(TICK_PATTERN_NAMES) - 1)
        )
        self._tick_pat_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("tick_pattern", idx)
        )
        tick_pat_row.addWidget(self._tick_pat_combo, stretch=1)

        small_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        self._tick_file_btn = QPushButton("📁")
        self._tick_file_btn.setFont(QFont("Meiryo", 8))
        self._tick_file_btn.setStyleSheet(small_btn_style)
        self._tick_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tick_file_btn.setToolTip("カスタムスピン音ファイルを選択")
        self._tick_file_btn.clicked.connect(self._on_tick_custom_browse)
        tick_pat_row.addWidget(self._tick_file_btn)

        self._tick_test_btn = QPushButton("♪")
        self._tick_test_btn.setFont(QFont("Meiryo", 8))
        self._tick_test_btn.setStyleSheet(small_btn_style)
        self._tick_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tick_test_btn.setToolTip("スピン音をテスト再生")
        self._tick_test_btn.clicked.connect(self.preview_tick_requested.emit)
        tick_pat_row.addWidget(self._tick_test_btn)

        sec.addLayout(tick_pat_row)

        # result 音パターン選択
        win_pat_row = QHBoxLayout()
        win_pat_row.setSpacing(4)
        win_pat_lbl = QLabel("決定音:")
        win_pat_lbl.setFont(QFont("Meiryo", 8))
        win_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._win_pat_lbl = win_pat_lbl
        win_pat_row.addWidget(win_pat_lbl)

        self._win_pat_combo = QComboBox()
        self._win_pat_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._win_pat_combo, design)
        for name in WIN_PATTERN_NAMES:
            self._win_pat_combo.addItem(name)
        self._win_pat_combo.setCurrentIndex(
            min(settings.win_pattern, len(WIN_PATTERN_NAMES) - 1)
        )
        self._win_pat_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("win_pattern", idx)
        )
        win_pat_row.addWidget(self._win_pat_combo, stretch=1)

        self._win_file_btn = QPushButton("📁")
        self._win_file_btn.setFont(QFont("Meiryo", 8))
        self._win_file_btn.setStyleSheet(small_btn_style)
        self._win_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._win_file_btn.setToolTip("カスタム決定音ファイルを選択")
        self._win_file_btn.clicked.connect(self._on_win_custom_browse)
        win_pat_row.addWidget(self._win_file_btn)

        self._win_test_btn = QPushButton("♪")
        self._win_test_btn.setFont(QFont("Meiryo", 8))
        self._win_test_btn.setStyleSheet(small_btn_style)
        self._win_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._win_test_btn.setToolTip("決定音をテスト再生")
        self._win_test_btn.clicked.connect(self.preview_win_requested.emit)
        win_pat_row.addWidget(self._win_test_btn)

        sec.addLayout(win_pat_row)

    def _on_tick_custom_browse(self):
        """カスタムtick音ファイル選択ダイアログ。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "スピン音ファイルを選択", "",
            "音声ファイル (*.wav *.mp3 *.ogg);;全てのファイル (*)"
        )
        if path:
            self._tick_pat_combo.blockSignals(True)
            self._tick_pat_combo.setCurrentIndex(self._TICK_CUSTOM_IDX)
            self._tick_pat_combo.blockSignals(False)
            self.setting_changed.emit("tick_pattern", self._TICK_CUSTOM_IDX)
            self.custom_tick_file_changed.emit(path)

    def _on_win_custom_browse(self):
        """カスタムresult音ファイル選択ダイアログ。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "決定音ファイルを選択", "",
            "音声ファイル (*.wav *.mp3 *.ogg);;全てのファイル (*)"
        )
        if path:
            self._win_pat_combo.blockSignals(True)
            self._win_pat_combo.setCurrentIndex(self._WIN_CUSTOM_IDX)
            self._win_pat_combo.blockSignals(False)
            self.setting_changed.emit("win_pattern", self._WIN_CUSTOM_IDX)
            self.custom_win_file_changed.emit(path)

    # ================================================================
    #  セクション 3d: ログオーバーレイ
    # ================================================================

    def _build_log_section(self, settings: AppSettings,
                           design: DesignSettings):
        self._log_collapsible = CollapsibleSection("ログ", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._log_collapsible.content_layout
        self._layout.addWidget(self._log_collapsible)

        # i274: 「ログオーバーレイ表示」は廃止。残すのは「ログ前面表示」のみ。
        # ここではタイムスタンプ表示を最初の項目として配置する。
        self._log_ts_cb = QCheckBox("タイムスタンプ表示")
        self._log_ts_cb.setFont(QFont("Meiryo", 8))
        self._log_ts_cb.setStyleSheet(f"color: {design.text};")
        self._log_ts_cb.setChecked(settings.log_timestamp)
        self._log_ts_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_timestamp", v)
        )
        sec.addWidget(self._log_ts_cb)

        self._log_border_cb = QCheckBox("枠線表示")
        self._log_border_cb.setFont(QFont("Meiryo", 8))
        self._log_border_cb.setStyleSheet(f"color: {design.text};")
        self._log_border_cb.setChecked(settings.log_box_border)
        self._log_border_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_box_border", v)
        )
        sec.addWidget(self._log_border_cb)

        self._log_on_top_cb = QCheckBox("ログ前面表示")
        self._log_on_top_cb.setFont(QFont("Meiryo", 8))
        self._log_on_top_cb.setStyleSheet(f"color: {design.text};")
        self._log_on_top_cb.setChecked(settings.log_on_top)
        self._log_on_top_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_on_top", v)
        )
        sec.addWidget(self._log_on_top_cb)

        # リセット確認
        self._confirm_reset_cb = QCheckBox("リセット確認")
        self._confirm_reset_cb.setFont(QFont("Meiryo", 8))
        self._confirm_reset_cb.setStyleSheet(f"color: {design.text};")
        self._confirm_reset_cb.setChecked(settings.confirm_reset)
        self._confirm_reset_cb.toggled.connect(
            lambda v: self.setting_changed.emit("confirm_reset", v)
        )
        sec.addWidget(self._confirm_reset_cb)

        # ログ操作ボタン行
        log_btn_row = QHBoxLayout()
        log_btn_row.setSpacing(4)

        self._log_export_btn = QPushButton("エクスポート")
        self._log_export_btn.setFont(QFont("Meiryo", 8))
        self._log_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_export_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._log_export_btn.clicked.connect(self.log_export_requested.emit)
        log_btn_row.addWidget(self._log_export_btn)

        self._log_clear_btn = QPushButton("履歴クリア")
        self._log_clear_btn.setFont(QFont("Meiryo", 8))
        self._log_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_clear_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._log_clear_btn.clicked.connect(self.log_clear_requested.emit)
        log_btn_row.addWidget(self._log_clear_btn)

        self._graph_btn = QPushButton("グラフ")
        self._graph_btn.setFont(QFont("Meiryo", 8))
        self._graph_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._graph_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._graph_btn.clicked.connect(self.graph_requested.emit)
        log_btn_row.addWidget(self._graph_btn)

        sec.addLayout(log_btn_row)

    # ================================================================
    #  セクション: リプレイ
    # ================================================================

    def _build_replay_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._replay_collapsible = CollapsibleSection("リプレイ", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._replay_collapsible.content_layout
        self._layout.addWidget(self._replay_collapsible)

        # リプレイ件数表示 + 再生/中断ボタン
        replay_row = QHBoxLayout()
        replay_row.setSpacing(4)

        self._replay_count_lbl = QLabel("記録: 0件")
        self._replay_count_lbl.setFont(QFont("Meiryo", 8))
        self._replay_count_lbl.setStyleSheet(f"color: {design.text_sub};")
        replay_row.addWidget(self._replay_count_lbl)

        replay_row.addStretch(1)

        self._replay_play_btn = QPushButton("最新を再生")
        self._replay_play_btn.setFont(QFont("Meiryo", 8))
        self._replay_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._replay_play_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._replay_play_btn.clicked.connect(self.replay_play_requested.emit)
        replay_row.addWidget(self._replay_play_btn)

        self._replay_stop_btn = QPushButton("中断")
        self._replay_stop_btn.setFont(QFont("Meiryo", 8))
        self._replay_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._replay_stop_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._replay_stop_btn.setEnabled(False)
        self._replay_stop_btn.clicked.connect(self.replay_stop_requested.emit)
        replay_row.addWidget(self._replay_stop_btn)

        self._replay_mgr_btn = QPushButton("管理...")
        self._replay_mgr_btn.setFont(QFont("Meiryo", 8))
        self._replay_mgr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._replay_mgr_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._replay_mgr_btn.clicked.connect(
            self.replay_manager_requested.emit
        )
        replay_row.addWidget(self._replay_mgr_btn)

        sec.addLayout(replay_row)

        # 設定行: 保存上限
        max_row = QHBoxLayout()
        max_row.setSpacing(4)

        max_lbl = QLabel("保存上限:")
        max_lbl.setFont(QFont("Meiryo", 8))
        max_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._replay_max_lbl = max_lbl
        max_row.addWidget(max_lbl)

        self._replay_max_spin = QSpinBox()
        self._replay_max_spin.setFont(QFont("Meiryo", 8))
        self._replay_max_spin.setRange(1, 20)
        self._replay_max_spin.setValue(settings.replay_max_count)
        self._replay_max_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._replay_max_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("replay_max_count", v)
        )
        max_row.addWidget(self._replay_max_spin)

        max_row.addStretch(1)

        sec.addLayout(max_row)

        # 設定行: 再生中表示
        self._replay_indicator_cb = QCheckBox("再生中表示")
        self._replay_indicator_cb.setFont(QFont("Meiryo", 8))
        self._replay_indicator_cb.setStyleSheet(f"color: {design.text};")
        self._replay_indicator_cb.setChecked(settings.replay_show_indicator)
        self._replay_indicator_cb.toggled.connect(
            lambda v: self.setting_changed.emit("replay_show_indicator", v)
        )
        sec.addWidget(self._replay_indicator_cb)

    def set_replay_count(self, count: int):
        """リプレイ件数表示を更新する。"""
        self._replay_count_lbl.setText(f"記録: {count}件")
        self._replay_play_btn.setEnabled(count > 0)

    def set_replay_playing(self, playing: bool):
        """リプレイ再生中の UI 状態を設定する。"""
        self._replay_play_btn.setEnabled(not playing)
        self._replay_stop_btn.setEnabled(playing)

    # ================================================================
    #  セクション 3c: パターン管理
    # ================================================================

    def _build_pattern_section(self, design: DesignSettings):
        """パターン選択・追加・削除セクションを構築する。"""
        self._pattern_collapsible = CollapsibleSection("パターン", design, expanded=False, theme_mode=self._settings.theme_mode)
        sec = self._pattern_collapsible.content_layout
        self._layout.addWidget(self._pattern_collapsible)

        # パターン選択行: [コンボ] [＋] [－]
        pat_row = QHBoxLayout()
        pat_row.setSpacing(4)

        self._pattern_combo = QComboBox()
        self._pattern_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._pattern_combo, design)
        for name in self._pattern_names:
            self._pattern_combo.addItem(name)
        self._pattern_combo.setCurrentText(self._current_pattern)
        self._pattern_combo.currentTextChanged.connect(self._on_pattern_switched)
        pat_row.addWidget(self._pattern_combo, stretch=1)

        btn_font = QFont("Meiryo", 8)
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        self._pattern_add_btn = QPushButton("＋")
        self._pattern_add_btn.setFont(btn_font)
        self._pattern_add_btn.setStyleSheet(btn_style)
        self._pattern_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_add_btn.setToolTip("新しいパターンを追加")
        self._pattern_add_btn.clicked.connect(self._on_pattern_add)
        pat_row.addWidget(self._pattern_add_btn)

        del_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._pattern_del_btn = QPushButton("－")
        self._pattern_del_btn.setFont(btn_font)
        self._pattern_del_btn.setStyleSheet(del_btn_style)
        self._pattern_del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_del_btn.setToolTip("現在のパターンを削除")
        self._pattern_del_btn.clicked.connect(self._on_pattern_delete)
        pat_row.addWidget(self._pattern_del_btn)

        self._pattern_export_btn = QPushButton("↑")
        self._pattern_export_btn.setFont(btn_font)
        self._pattern_export_btn.setStyleSheet(btn_style)
        self._pattern_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_export_btn.setToolTip("現在のパターンをエクスポート")
        self._pattern_export_btn.clicked.connect(self.pattern_export_requested.emit)
        pat_row.addWidget(self._pattern_export_btn)

        self._pattern_import_btn = QPushButton("↓")
        self._pattern_import_btn.setFont(btn_font)
        self._pattern_import_btn.setStyleSheet(btn_style)
        self._pattern_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_import_btn.setToolTip("パターンをインポート")
        self._pattern_import_btn.clicked.connect(self.pattern_import_requested.emit)
        pat_row.addWidget(self._pattern_import_btn)

        sec.addLayout(pat_row)
        self._update_pattern_del_enabled()

    def _on_pattern_switched(self, name: str):
        """パターン選択変更時。"""
        if name and name != self._current_pattern:
            self._current_pattern = name
            self.pattern_switched.emit(name)

    def _on_pattern_add(self):
        """パターン追加ボタン押下。"""
        # 既存名と被らない名前を自動生成
        base = "パターン"
        idx = 1
        while True:
            name = f"{base}{idx}"
            if name not in self._pattern_names:
                break
            idx += 1
        self._pattern_names.append(name)
        self._pattern_combo.blockSignals(True)
        self._pattern_combo.addItem(name)
        self._pattern_combo.setCurrentText(name)
        self._pattern_combo.blockSignals(False)
        self._current_pattern = name
        self._update_pattern_del_enabled()
        self.pattern_added.emit(name)

    def _on_pattern_delete(self):
        """パターン削除ボタン押下。confirm_reset=ON なら確認ダイアログ。"""
        if len(self._pattern_names) <= 1:
            return
        if self._settings.confirm_reset:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "確認",
                f"パターン「{self._current_pattern}」を削除しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        name = self._current_pattern
        self._pattern_names.remove(name)
        self._pattern_combo.blockSignals(True)
        idx = self._pattern_combo.findText(name)
        if idx >= 0:
            self._pattern_combo.removeItem(idx)
        self._pattern_combo.blockSignals(False)
        # 新しい current を先頭に
        self._current_pattern = self._pattern_combo.currentText()
        self._update_pattern_del_enabled()
        self.pattern_deleted.emit(name)

    def _update_pattern_del_enabled(self):
        """パターンが1件のみなら削除ボタンを無効化。"""
        self._pattern_del_btn.setEnabled(len(self._pattern_names) > 1)

    def set_spin_section_visible(self, visible: bool):
        """スピンセクション（操作ボックス相当）の表示/非表示を切り替える。"""
        self._spin_section.setVisible(visible)

    def set_pattern_list(self, names: list[str], current: str):
        """外部からパターン一覧と選択を更新する。"""
        self._pattern_names = list(names)
        self._current_pattern = current
        self._pattern_combo.blockSignals(True)
        self._pattern_combo.clear()
        for name in names:
            self._pattern_combo.addItem(name)
        self._pattern_combo.setCurrentText(current)
        self._pattern_combo.blockSignals(False)
        self._update_pattern_del_enabled()

    # ================================================================
    #  セクション 4: 項目リスト（編集可能・ItemEntry 側）
    # ================================================================

    def _build_items_section(self, entries: list[ItemEntry],
                             design: DesignSettings):
        """項目データセクションを構築する。

        各行: [有効CB] [テキスト入力] [▲] [▼] [×]
        末尾に「＋追加」ボタン。
        """
        self._items_collapsible = CollapsibleSection("項目リスト", design, expanded=True, theme_mode=self._settings.theme_mode)
        sec = self._items_collapsible.content_layout
        self._layout.addWidget(self._items_collapsible)

        # ── 検索・フィルター行 ──
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(4)

        self._search_edit = QLineEdit()
        self._search_edit.setFont(QFont("Meiryo", 8))
        self._search_edit.setPlaceholderText("検索...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._search_edit.textChanged.connect(self._apply_item_filter)
        filter_bar.addWidget(self._search_edit, stretch=1)

        self._filter_combo = QComboBox()
        self._filter_combo.setFont(QFont("Meiryo", 8))
        self._filter_combo.addItems(["全件", "ONのみ", "OFFのみ"])
        self._apply_combo_style(self._filter_combo, design)
        self._filter_combo.currentIndexChanged.connect(
            lambda _: self._apply_item_filter()
        )
        filter_bar.addWidget(self._filter_combo)

        sec.addLayout(filter_bar)

        # 行ウィジェットを格納するコンテナ
        self._item_rows_container = QWidget()
        self._item_rows_layout = QVBoxLayout(self._item_rows_container)
        self._item_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._item_rows_layout.setSpacing(2)
        sec.addWidget(self._item_rows_container)

        self._item_rows: list[QWidget] = []

        for entry in entries:
            self._add_item_row(entry, design)

        # i284: 初期構築時の確率ラベル反映
        self._refresh_prob_labels()

        # 追加ボタン
        self._add_item_btn = QPushButton("＋ 追加")
        self._add_item_btn.setFont(QFont("Meiryo", 8))
        self._add_item_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_add_btn_style(self._add_item_btn, design)
        self._add_item_btn.clicked.connect(self._on_add_item)
        sec.addWidget(self._add_item_btn)

    # ── 確率変更ヘルパー ──

    # 確率モードの UI 表示名と内部値の対応
    _PROB_MODE_LABELS = ["変更なし", "重み係数", "固定確率"]
    _PROB_MODE_VALUES = [None, "weight", "fixed"]

    @staticmethod
    def _build_weight_candidates(n: int) -> list[float]:
        """重み係数の選択肢を生成する。

        Args:
            n: 現在の有効項目数

        Returns:
            [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, ..., n] の候補リスト
        """
        candidates = [0.25, 0.5, 0.75, 1.0]
        v = 1.5
        while v <= n:
            candidates.append(v)
            v += 0.5
        return candidates

    def _get_enabled_count(self) -> int:
        """現在の有効項目数 N を返す。"""
        return sum(1 for r in self._item_rows if r._cb.isChecked())

    def _add_item_row(self, entry: ItemEntry, design: DesignSettings,
                      index: int = -1) -> QWidget:
        """1項目分の編集行を作成し、コンテナに追加する。

        行構成（2段）:
          上段: [CB] [テキスト] [▲] [▼] [×]
          下段: [確率モード] [値ウィジェット（weight combo / fixed spin）]
        """
        row = QWidget()
        outer_layout = QVBoxLayout(row)
        outer_layout.setContentsMargins(0, 1, 0, 1)
        outer_layout.setSpacing(1)

        # ── 上段: テキスト + 操作ボタン ──
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(2)

        # 有効/無効チェックボックス
        cb = QCheckBox()
        cb.setChecked(entry.enabled)
        cb.setStyleSheet(f"color: {design.text};")
        cb.toggled.connect(lambda _: self._on_item_toggled())
        top_row.addWidget(cb)

        # テキスト入力
        # i283: QLineEdit は改行を保持できないため、改行を含む項目テキストは
        # 表示用にスペースへ畳んで表示し、original_text として保持する。
        # ユーザーが触らないかぎり、保存時に元の改行入りテキストへ復元する。
        display_text = entry.text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        edit = QLineEdit()
        edit.setFont(QFont("Meiryo", 8))
        edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        edit.setText(display_text)  # connect 前に setText して signal を発火させない
        # i283: 即時反映 — 入力途中で textChanged → 行ベースの反映へ
        edit.textChanged.connect(
            lambda _t, r=row: self._on_item_text_changed_live(r)
        )
        top_row.addWidget(edit, stretch=1)

        # i284: 計算済み当選確率ラベル（全項目向けトグルで表示／非表示）
        prob_pct_lbl = QLabel("")
        prob_pct_lbl.setFont(QFont("Meiryo", 7))
        prob_pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prob_pct_lbl.setMinimumWidth(40)
        prob_pct_lbl.setStyleSheet(
            f"color: {design.text_sub}; background-color: transparent;"
        )
        prob_pct_lbl.setToolTip("当選確率（％）")
        top_row.addWidget(prob_pct_lbl)

        # 勝利数ラベル
        win_lbl = QLabel("0")
        win_lbl.setFont(QFont("Meiryo", 7))
        win_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        win_lbl.setFixedWidth(28)
        win_lbl.setStyleSheet(
            f"color: {design.gold}; background-color: transparent;"
        )
        win_lbl.setToolTip("当選回数")
        top_row.addWidget(win_lbl)

        # ボタン共通スタイル
        btn_font = QFont("Meiryo", 8)
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        # 上へ
        up_btn = QPushButton("▲")
        up_btn.setFont(btn_font)
        up_btn.setStyleSheet(btn_style)
        up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        up_btn.clicked.connect(lambda: self._on_move_item(row, -1))
        top_row.addWidget(up_btn)

        # 下へ
        down_btn = QPushButton("▼")
        down_btn.setFont(btn_font)
        down_btn.setStyleSheet(btn_style)
        down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        down_btn.clicked.connect(lambda: self._on_move_item(row, 1))
        top_row.addWidget(down_btn)

        # 削除
        del_btn = QPushButton("×")
        del_btn.setFont(btn_font)
        del_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self._on_delete_item(row))
        top_row.addWidget(del_btn)

        outer_layout.addLayout(top_row)

        # ── 下段: 確率変更 UI ──
        prob_row = QHBoxLayout()
        prob_row.setContentsMargins(20, 0, 0, 0)  # 左インデント
        prob_row.setSpacing(4)

        combo_style = (
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 14px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )

        # 確率モード選択
        mode_combo = QComboBox()
        mode_combo.setFont(QFont("Meiryo", 7))
        mode_combo.setStyleSheet(combo_style)
        for label in self._PROB_MODE_LABELS:
            mode_combo.addItem(label)
        prob_row.addWidget(mode_combo)

        # 値ウィジェット（QStackedWidget で切替）
        value_stack = QStackedWidget()

        # page 0: 変更なし — 空ラベル
        empty_label = QLabel("")
        value_stack.addWidget(empty_label)

        # page 1: 重み係数 — QComboBox
        n = self._get_enabled_count() if self._item_rows else max(1, len(self._item_entries))
        weight_combo = QComboBox()
        weight_combo.setFont(QFont("Meiryo", 7))
        weight_combo.setStyleSheet(combo_style)
        self._populate_weight_combo(weight_combo, n)
        weight_combo.currentIndexChanged.connect(
            lambda _: self._on_prob_value_changed()
        )
        value_stack.addWidget(weight_combo)

        # page 2: 固定確率 — QDoubleSpinBox
        fixed_spin = QDoubleSpinBox()
        fixed_spin.setFont(QFont("Meiryo", 7))
        fixed_spin.setRange(0.1, 99.9)
        fixed_spin.setSingleStep(0.5)
        fixed_spin.setDecimals(1)
        fixed_spin.setSuffix(" %")
        fixed_spin.setValue(10.0)
        fixed_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
        )
        fixed_spin.editingFinished.connect(self._on_prob_value_changed)
        value_stack.addWidget(fixed_spin)

        prob_row.addWidget(value_stack, stretch=1)

        # 分割数
        split_lbl = QLabel("分割:")
        split_lbl.setFont(QFont("Meiryo", 7))
        split_lbl.setStyleSheet(f"color: {design.text_sub};")
        prob_row.addWidget(split_lbl)

        split_spin = QSpinBox()
        split_spin.setFont(QFont("Meiryo", 7))
        split_spin.setRange(1, 10)
        split_spin.setValue(max(1, min(10, entry.split_count)))
        split_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"  min-width: 36px; max-width: 48px;"
            f"}}"
        )
        split_spin.valueChanged.connect(lambda _: self._emit_entries_changed())
        prob_row.addWidget(split_spin)

        outer_layout.addLayout(prob_row)

        # モード切替で表示切替
        mode_combo.currentIndexChanged.connect(
            lambda idx: self._on_prob_mode_changed(row, idx)
        )

        # 行にウィジェット参照を保持
        row._cb = cb
        row._edit = edit
        row._win_lbl = win_lbl
        row._prob_pct_lbl = prob_pct_lbl  # i284
        row._mode_combo = mode_combo
        row._value_stack = value_stack
        row._weight_combo = weight_combo
        row._fixed_spin = fixed_spin
        row._split_lbl = split_lbl
        row._split_spin = split_spin
        # i283: 改行入りテキストの保持と、ユーザー編集判定
        row._original_text = entry.text
        row._user_edited = False
        # i284: 表示トグルは prob_pct_lbl と win_lbl だけを対象にする
        # （i283 で誤って確率編集 UI を隠していたのを取り消し）
        # 現在の表示設定を反映
        self._apply_item_row_visibility(row)

        # 既存データから確率モード/値を復元
        self._restore_prob_ui(row, entry)

        if index < 0:
            self._item_rows_layout.addWidget(row)
            self._item_rows.append(row)
        else:
            self._item_rows_layout.insertWidget(index, row)
            self._item_rows.insert(index, row)

        return row

    @staticmethod
    def _populate_weight_combo(combo: QComboBox, n: int):
        """重み係数 QComboBox の選択肢を N に基づいて再構築する。"""
        combo.blockSignals(True)
        current_text = combo.currentText()
        combo.clear()
        candidates = SettingsPanel._build_weight_candidates(n)
        for v in candidates:
            combo.addItem(f"×{v:g}", v)
        # 以前の選択を復元（可能なら）
        for i in range(combo.count()):
            if combo.itemText(i) == current_text:
                combo.setCurrentIndex(i)
                break
        combo.blockSignals(False)

    def _restore_prob_ui(self, row: QWidget, entry: ItemEntry):
        """ItemEntry の prob_mode/prob_value から UI を復元する。

        i285: mode_combo / weight_combo のシグナルを遮断してから setCurrentIndex を
        呼ぶ。これにより、_add_item_row 内（行が _item_rows に追加される前）で
        _on_prob_mode_changed → _emit_entries_changed → item_entries_changed が
        空リスト / 不完全リストで発火するのを防ぐ。
        value_stack の切替は _restore_prob_ui 内で明示的に行うため、
        _on_prob_mode_changed を経由しなくても正しく反映される。
        """
        row._mode_combo.blockSignals(True)
        row._weight_combo.blockSignals(True)
        try:
            if entry.prob_mode == "weight":
                row._mode_combo.setCurrentIndex(1)  # 重み係数
                row._value_stack.setCurrentIndex(1)
                # 値を weight_combo から探す
                val = entry.prob_value if entry.prob_value is not None else 1.0
                for i in range(row._weight_combo.count()):
                    if abs(row._weight_combo.itemData(i) - val) < 0.001:
                        row._weight_combo.setCurrentIndex(i)
                        break
            elif entry.prob_mode == "fixed":
                row._mode_combo.setCurrentIndex(2)  # 固定確率
                row._value_stack.setCurrentIndex(2)
                val = entry.prob_value if entry.prob_value is not None else 10.0
                val = max(0.1, min(99.9, val))
                row._fixed_spin.setValue(val)
            else:
                row._mode_combo.setCurrentIndex(0)  # 変更なし
                row._value_stack.setCurrentIndex(0)
        finally:
            row._mode_combo.blockSignals(False)
            row._weight_combo.blockSignals(False)

    def _on_prob_mode_changed(self, row: QWidget, idx: int):
        """確率モード切替時: 表示切替 + 通知。"""
        row._value_stack.setCurrentIndex(idx)
        self._emit_entries_changed()

    def _refresh_all_weight_combos(self):
        """全行の重み係数候補を現在の N に基づいて再構築する。

        N が変わると上限が変わるため、全行を更新する。
        保持していた値が新 N では上限超過の場合、最大値にクランプする。
        """
        n = self._get_enabled_count()
        n = max(n, 1)
        for row in self._item_rows:
            combo = row._weight_combo
            # 現在の値を保持
            old_idx = combo.currentIndex()
            old_val = combo.itemData(old_idx) if old_idx >= 0 else 1.0
            self._populate_weight_combo(combo, n)
            # 旧値を復元（上限超過はクランプ）
            best_idx = 0
            for i in range(combo.count()):
                if combo.itemData(i) is not None and combo.itemData(i) <= old_val:
                    best_idx = i
            combo.setCurrentIndex(best_idx)

    def _on_prob_value_changed(self):
        """確率値変更時: 通知。"""
        self._emit_entries_changed()

    def _collect_entries(self) -> list[ItemEntry]:
        """現在の UI 行から ItemEntry リストを収集する。"""
        entries = []
        for row in self._item_rows:
            # i283: ユーザーがこの行のテキストに触れていない場合、改行を含む
            # 元テキストをそのまま保持する。触れた場合は QLineEdit の値を採用。
            if getattr(row, "_user_edited", False):
                text = row._edit.text().strip()
            else:
                text = getattr(row, "_original_text", row._edit.text()).strip()
            if not text:
                continue
            mode_idx = row._mode_combo.currentIndex()
            prob_mode = self._PROB_MODE_VALUES[mode_idx]
            prob_value = None
            if prob_mode == "weight":
                idx = row._weight_combo.currentIndex()
                if idx >= 0:
                    prob_value = row._weight_combo.itemData(idx)
            elif prob_mode == "fixed":
                prob_value = row._fixed_spin.value()
            entries.append(ItemEntry(
                text=text,
                enabled=row._cb.isChecked(),
                split_count=row._split_spin.value(),
                prob_mode=prob_mode,
                prob_value=prob_value,
            ))
        return entries

    def _emit_entries_changed(self):
        """項目変更を通知する。"""
        self._item_entries = self._collect_entries()
        # i284: 計算済み確率ラベルを更新（表示中なら反映、非表示なら次回 ON 時に効く）
        self._refresh_prob_labels()
        self.item_entries_changed.emit(list(self._item_entries))

    def _on_add_item(self):
        """追加ボタン押下: 新しい空行を追加する。"""
        entry = ItemEntry(text="新しい項目", enabled=True)
        self._add_item_row(entry, self._design)
        self._refresh_all_weight_combos()
        self._emit_entries_changed()
        self._apply_item_filter()

    def _on_delete_item(self, row: QWidget):
        """削除ボタン押下: 指定行を削除する。

        i286: confirm_item_delete=ON のとき確認ダイアログを表示する。
        ダイアログ内に「今後この確認を表示しない」チェックを持つ。
        チェックを ON にして「削除」を選んだ場合のみ設定を変更する
        （キャンセルした場合はチェック状態に関わらず設定を変えない）。
        """
        if row not in self._item_rows:
            return
        if getattr(self._settings, "confirm_item_delete", True):
            from PySide6.QtWidgets import (
                QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                QPushButton, QCheckBox as _QCB,
            )
            item_text = row._edit.text().strip() or "（空）"
            dlg = QDialog(self)
            dlg.setWindowTitle("項目の削除")
            dlg.setModal(True)
            vlay = QVBoxLayout(dlg)
            vlay.setSpacing(8)
            vlay.setContentsMargins(16, 16, 16, 12)

            msg_lbl = QLabel(f"項目「{item_text}」を削除しますか？")
            msg_lbl.setFont(QFont("Meiryo", 9))
            vlay.addWidget(msg_lbl)

            no_confirm_cb = _QCB("今後この確認を表示しない")
            no_confirm_cb.setFont(QFont("Meiryo", 8))
            no_confirm_cb.setChecked(False)
            vlay.addWidget(no_confirm_cb)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(6)
            btn_row.addStretch(1)

            cancel_btn = QPushButton("キャンセル")
            cancel_btn.setFont(QFont("Meiryo", 8))
            cancel_btn.clicked.connect(dlg.reject)
            btn_row.addWidget(cancel_btn)

            ok_btn = QPushButton("削除")
            ok_btn.setFont(QFont("Meiryo", 8))
            ok_btn.setDefault(True)
            ok_btn.clicked.connect(dlg.accept)
            btn_row.addWidget(ok_btn)

            vlay.addLayout(btn_row)

            accepted = (dlg.exec() == QDialog.DialogCode.Accepted)
            if not accepted:
                return
            # 削除確定時のみ「今後表示しない」チェックを反映する
            if no_confirm_cb.isChecked():
                self._settings.confirm_item_delete = False
                self.setting_changed.emit("confirm_item_delete", False)
                if hasattr(self, "_confirm_item_delete_cb"):
                    self._confirm_item_delete_cb.blockSignals(True)
                    self._confirm_item_delete_cb.setChecked(False)
                    self._confirm_item_delete_cb.blockSignals(False)
        if row in self._item_rows:
            self._item_rows.remove(row)
            self._item_rows_layout.removeWidget(row)
            row.deleteLater()
            self._refresh_all_weight_combos()
            self._emit_entries_changed()

    def _on_move_item(self, row: QWidget, direction: int):
        """上下ボタン押下: 指定行を移動する。"""
        if row not in self._item_rows:
            return
        idx = self._item_rows.index(row)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._item_rows):
            return
        # リストの入れ替え
        self._item_rows[idx], self._item_rows[new_idx] = (
            self._item_rows[new_idx], self._item_rows[idx]
        )
        # レイアウトから一旦除去して再挿入
        self._item_rows_layout.removeWidget(row)
        self._item_rows_layout.insertWidget(new_idx, row)
        self._emit_entries_changed()

    def _on_item_toggled(self):
        """有効/無効チェックボックス変更時。N 変化に伴い重み候補を再構築。"""
        self._refresh_all_weight_combos()
        self._emit_entries_changed()
        self._apply_item_filter()

    def _apply_item_filter(self, _text=None):
        """検索・フィルター条件に基づいて項目行の表示/非表示を切り替える。"""
        search = self._search_edit.text().strip().lower()
        filter_mode = self._filter_combo.currentIndex()  # 0=全件, 1=ONのみ, 2=OFFのみ

        for row in self._item_rows:
            text = row._edit.text().lower()
            enabled = row._cb.isChecked()

            # 検索条件: 部分一致（大文字小文字無視）
            match_search = (not search) or (search in text)

            # フィルター条件
            if filter_mode == 1:
                match_filter = enabled
            elif filter_mode == 2:
                match_filter = not enabled
            else:
                match_filter = True

            row.setVisible(match_search and match_filter)

    def _on_item_text_edited(self):
        """テキスト編集完了（editingFinished）時。

        i283 以降は textChanged で即時反映するため呼び出し元はないが、
        外部から呼ばれる可能性に備えて互換のため残す。
        """
        self._emit_entries_changed()

    def _on_item_text_changed_live(self, row: QWidget):
        """i283: 入力途中のテキスト変更を即時通知する。

        - 該当行のユーザー編集フラグを立てる（保持していた改行を破棄して、
          以後は QLineEdit の値を採用するようにする）
        - 検索フィルター・項目変更通知を即時発火する
        """
        if row in self._item_rows:
            row._user_edited = True
        self._emit_entries_changed()
        self._apply_item_filter()

    def _apply_item_row_visibility(self, row: QWidget):
        """i284: 項目行内の当選確率ラベル / 当選回数ラベルを表示設定に従って ON/OFF する。

        i283 では確率の編集 UI（mode_combo / split_spin 等）を隠していたが、
        ユーザーフィードバックで「項目の設定が消えてしまう」となったため、
        i284 では表示用ラベル（_prob_pct_lbl / _win_lbl）だけを対象にする。
        """
        show_prob = bool(getattr(self._settings, "show_item_prob", True))
        show_win = bool(getattr(self._settings, "show_item_win_count", True))
        if hasattr(row, "_prob_pct_lbl"):
            row._prob_pct_lbl.setVisible(show_prob)
        if hasattr(row, "_win_lbl"):
            row._win_lbl.setVisible(show_win)

    def _refresh_item_rows_visibility(self):
        """全行に表示 ON/OFF を反映する。"""
        for row in self._item_rows:
            self._apply_item_row_visibility(row)

    @staticmethod
    def _calc_item_probs(entries: list[ItemEntry]) -> list[float | None]:
        """i284: 各項目の当選確率（%）を計算する。

        v0.4.4 `_calc_all_probs` 相当のロジックを ItemEntry に合わせて移植。
        無効項目は None。
        重み係数 / 固定確率 / split_count を考慮する必要はない（split は
        セグメント分割のためのもので、項目の総当選確率には影響しない）。
        """
        if not entries:
            return []
        enabled_idx = [i for i, e in enumerate(entries) if e.enabled]
        if not enabled_idx:
            return [None] * len(entries)
        n = len(enabled_idx)
        fixed_idx_loc: list[int] = []
        nonfixed_idx_loc: list[int] = []
        for k, gi in enumerate(enabled_idx):
            if entries[gi].prob_mode == "fixed":
                fixed_idx_loc.append(k)
            else:
                nonfixed_idx_loc.append(k)

        sum_fixed = 0.0
        for k in fixed_idx_loc:
            v = entries[enabled_idx[k]].prob_value or 0.0
            sum_fixed += float(v)
        if sum_fixed > 99.999:
            sum_fixed = 99.999
        remaining = 100.0 - sum_fixed

        weights: list[float] = []
        for k in nonfixed_idx_loc:
            e = entries[enabled_idx[k]]
            if e.prob_mode == "weight" and e.prob_value is not None:
                weights.append(max(0.0001, float(e.prob_value)))
            else:
                weights.append(1.0)
        total_w = sum(weights) or 1.0

        probs_local = [0.0] * n
        for k in fixed_idx_loc:
            probs_local[k] = float(entries[enabled_idx[k]].prob_value or 0.0)
        for j, k in enumerate(nonfixed_idx_loc):
            probs_local[k] = remaining * weights[j] / total_w

        out: list[float | None] = [None] * len(entries)
        for k, gi in enumerate(enabled_idx):
            out[gi] = probs_local[k]
        return out

    def _refresh_prob_labels(self):
        """i284: 全行の当選確率ラベルを再計算して反映する。

        _add_item_row 中の _restore_prob_ui で部分的に collect が走るタイミングが
        あるため、ここでは self._item_entries に頼らず必ず collect_entries で
        その時点の行 UI から再構築する。
        """
        if not self._item_rows:
            return
        entries = self._collect_entries()
        probs = self._calc_item_probs(entries)
        for i, row in enumerate(self._item_rows):
            if not hasattr(row, "_prob_pct_lbl"):
                continue
            if i < len(probs) and probs[i] is not None:
                row._prob_pct_lbl.setText(f"{probs[i]:.1f}%")
            else:
                row._prob_pct_lbl.setText("—")

    @staticmethod
    def _apply_add_btn_style(btn: QPushButton, design):
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

    def _update_item_rows_design(self, design: DesignSettings):
        """項目編集行のデザインを更新する。"""
        edit_style = (
            f"QLineEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        del_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        combo_style = (
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 14px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )
        spin_style = (
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
        )
        for row in self._item_rows:
            row._cb.setStyleSheet(f"color: {design.text};")
            row._edit.setStyleSheet(edit_style)
            row._win_lbl.setStyleSheet(
                f"color: {design.gold}; background-color: transparent;"
            )
            # 上段のボタン（上段レイアウトの index 3,4,5 — win_lbl が index 2）
            top_layout = row.layout().itemAt(0).layout()
            for i in range(3, 6):
                btn = top_layout.itemAt(i).widget()
                if i == 5:  # 削除ボタン
                    btn.setStyleSheet(del_btn_style)
                else:
                    btn.setStyleSheet(btn_style)
            # 確率 UI
            row._mode_combo.setStyleSheet(combo_style)
            row._weight_combo.setStyleSheet(combo_style)
            row._fixed_spin.setStyleSheet(spin_style)
            # 分割数 UI
            row._split_lbl.setStyleSheet(f"color: {design.text_sub};")
            row._split_spin.setStyleSheet(
                f"QSpinBox {{"
                f"  background-color: {design.separator}; color: {design.text};"
                f"  border: 1px solid {design.separator}; border-radius: 3px;"
                f"  padding: 1px 4px; font-size: 8pt;"
                f"  min-width: 36px; max-width: 48px;"
                f"}}"
            )

    # ================================================================
    #  セクション 5-8: 項目編集系（ItemEntry 側の将来拡張）
    #
    #  これらは項目データ（ItemEntry）に対する編集 UI。
    #  AppSettings 側のセクションとは責務が異なる。
    #
    #  本実装時の手順:
    #    1. _PlaceholderSection を専用セクションクラスに差し替え
    #    2. 編集 UI で self._item_entries を変更
    #    3. self.item_entries_changed.emit(self._item_entries) で通知
    #    4. MainWindow が受信 → segments 再構築 → WheelWidget 更新 → 保存
    #
    #  保存経路:
    #    SettingsPanel.item_entries_changed
    #      → MainWindow._on_item_entries_changed()
    #        → self._item_entries = entries
    #        → segments 再構築 → WheelWidget.set_segments()
    #        → save_item_entries(config, entries)
    # ================================================================

    def _build_item_edit_sections(self, design: DesignSettings):
        """項目データに関する編集系セクション。

        確率変更・分割数は各項目行に統合済み。
        常時ランダム / ランダム配置 / 並びリセット / 一括リセット は
        ここでまとめて配置する（i284 統一）。
        """
        self._item_edit_sections: list[_PlaceholderSection] = []
        sec = self._items_collapsible.content_layout

        # i284: 全項目向け表示トグル（個別設定ではなく全項目一括）
        self._show_item_prob_cb = QCheckBox("全項目に当選確率（％）を表示")
        self._show_item_prob_cb.setFont(QFont("Meiryo", 8))
        self._show_item_prob_cb.setStyleSheet(f"color: {design.text};")
        self._show_item_prob_cb.setChecked(self._settings.show_item_prob)
        self._show_item_prob_cb.setToolTip(
            "各項目に現在の当選確率（％）を一括で表示／非表示する"
        )
        self._show_item_prob_cb.toggled.connect(
            lambda v: self.setting_changed.emit("show_item_prob", v)
        )
        sec.addWidget(self._show_item_prob_cb)

        self._show_item_win_cb = QCheckBox("全項目に当選回数を表示")
        self._show_item_win_cb.setFont(QFont("Meiryo", 8))
        self._show_item_win_cb.setStyleSheet(f"color: {design.text};")
        self._show_item_win_cb.setChecked(self._settings.show_item_win_count)
        self._show_item_win_cb.setToolTip(
            "各項目に当選回数を一括で表示／非表示する"
        )
        self._show_item_win_cb.toggled.connect(
            lambda v: self.setting_changed.emit("show_item_win_count", v)
        )
        sec.addWidget(self._show_item_win_cb)

        # i287: 項目削除確認（ログセクションから項目リストセクションへ移動）
        # 項目操作の設定として自然な位置に配置する
        self._confirm_item_delete_cb = QCheckBox("項目削除時に確認する")
        self._confirm_item_delete_cb.setFont(QFont("Meiryo", 8))
        self._confirm_item_delete_cb.setStyleSheet(f"color: {design.text};")
        self._confirm_item_delete_cb.setChecked(self._settings.confirm_item_delete)
        self._confirm_item_delete_cb.setToolTip(
            "ON: 項目削除前に確認ダイアログを表示する\n"
            "OFF: 確認なしで即時削除する"
        )
        self._confirm_item_delete_cb.toggled.connect(
            lambda v: self.setting_changed.emit("confirm_item_delete", v)
        )
        sec.addWidget(self._confirm_item_delete_cb)

        # i284: 「常時ランダム」と「ランダム配置（単発）」を同じ行にまとめて
        # 関連機能としての一体感を出す。
        rand_row = QHBoxLayout()
        rand_row.setSpacing(6)

        self._shuffle_cb = QCheckBox("常時ランダム")
        self._shuffle_cb.setFont(QFont("Meiryo", 8))
        self._shuffle_cb.setStyleSheet(f"color: {design.text};")
        self._shuffle_cb.setChecked(self._settings.auto_shuffle)
        self._shuffle_cb.setToolTip("スピン開始ごとに項目順をランダム配置する")
        self._shuffle_cb.toggled.connect(
            lambda v: self.setting_changed.emit("auto_shuffle", v)
        )
        rand_row.addWidget(self._shuffle_cb)

        rand_row.addStretch(1)

        self._shuffle_once_btn = QPushButton("🔀 今すぐランダム配置")
        self._shuffle_once_btn.setFont(QFont("Meiryo", 8))
        self._shuffle_once_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._shuffle_once_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._shuffle_once_btn.setToolTip(
            "今すぐ項目の並び順をランダムに入れ替える（1回のみ）"
        )
        self._shuffle_once_btn.clicked.connect(self.shuffle_once_requested.emit)
        rand_row.addWidget(self._shuffle_once_btn)

        sec.addLayout(rand_row)

        # 配置方向
        arr_row = QHBoxLayout()
        arr_row.setSpacing(4)
        arr_lbl = QLabel("配置方向:")
        arr_lbl.setFont(QFont("Meiryo", 8))
        arr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._arr_lbl = arr_lbl
        arr_row.addWidget(arr_lbl)

        self._arr_combo = QComboBox()
        self._arr_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._arr_combo, design)
        # i284: CW/CCW の略語と「順/逆順」表記をやめ、日本語の直感表記に統一。
        # index 0 = 時計回り, index 1 = 反時計回り（実際の回転方向と一致）
        for name in ["時計回り", "反時計回り"]:
            self._arr_combo.addItem(name)
        self._arr_combo.setCurrentIndex(self._settings.arrangement_direction)
        self._arr_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("arrangement_direction", idx)
        )
        arr_row.addWidget(self._arr_combo, stretch=1)

        sec.addLayout(arr_row)

        # i284: 並びリセット / 一括リセット（v0.4.4 相当の復元）
        reset_row = QHBoxLayout()
        reset_row.setSpacing(6)

        reset_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        self._arrangement_reset_btn = QPushButton("↺ 並びリセット")
        self._arrangement_reset_btn.setFont(QFont("Meiryo", 8))
        self._arrangement_reset_btn.setStyleSheet(reset_btn_style)
        self._arrangement_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arrangement_reset_btn.setToolTip(
            "ランダム配置前の並び順に戻す（v0.4.4 の「標準配置に戻す」相当）"
        )
        self._arrangement_reset_btn.clicked.connect(
            self.arrangement_reset_requested.emit
        )
        reset_row.addWidget(self._arrangement_reset_btn)

        self._items_reset_btn = QPushButton("⟲ 項目全リセット")
        self._items_reset_btn.setFont(QFont("Meiryo", 8))
        self._items_reset_btn.setStyleSheet(reset_btn_style)
        self._items_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._items_reset_btn.setToolTip(
            "全項目の確率・分割設定をデフォルトに戻す\n"
            "（項目名・有効/無効はそのまま。v0.4.4 の「一括リセット」相当）"
        )
        self._items_reset_btn.clicked.connect(
            self.items_reset_requested.emit
        )
        reset_row.addWidget(self._items_reset_btn)

        reset_row.addStretch(1)

        sec.addLayout(reset_row)

    # ================================================================
    #  内部ヘルパー
    # ================================================================

    @staticmethod
    def _apply_scroll_style(scroll: QScrollArea, design: DesignSettings):
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {design.panel}; }}"
            f"QScrollBar:vertical {{ width: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:vertical {{ background: {design.separator}; border-radius: 3px; }}"
            f"QScrollBar:horizontal {{ height: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:horizontal {{ background: {design.separator}; border-radius: 3px; }}"
        )


    def _apply_spin_btn_style(self, design: DesignSettings):
        self._spin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.accent}; color: {design.text};"
            f"  border: none; border-radius: 6px; padding: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.separator}; }}"
            f"QPushButton:disabled {{ background-color: {design.separator}; color: {design.text_sub}; }}"
        )

    @staticmethod
    def _dark_checkbox_style(design: DesignSettings) -> str:
        return dark_checkbox_style(design)

    @staticmethod
    def _dark_spinbox_style(design: DesignSettings) -> str:
        return dark_spinbox_style(design)

    @staticmethod
    def _apply_combo_style(combo: QComboBox, design: DesignSettings):
        combo.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 3px 6px;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 16px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )

    # ================================================================
    #  公開 API
    # ================================================================

    def mousePressEvent(self, event):
        """i277: 空きクライアント領域でのクリックは「前面化のみ」扱い。

        - 背面パネルを前面化する (raise_)
        - パネル本体のドラッグはここでは始めない (上部の `_drag_bar` か
          各セクションヘッダのドラッグ拡張で行う)
        - 本来動作 (たとえばボタン押下) もここでは発火しない
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.raise_()
            self._dragging_panel = False
        event.accept()

    def mouseMoveEvent(self, event):
        # i277: 空きクライアント領域からのドラッグ移動は禁止 (前面化のみ)。
        # 移動はドラッグバーまたは折りたたみヘッダから行う。
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def moveEvent(self, event):
        """パネル移動時に通知する。"""
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        """リサイズグリップを右下に追従させる。"""
        super().resizeEvent(event)
        self._resize_grip.reposition()
        # i275: top-level Tool window 化に伴い、_clamp_to_parent は使わない。
        # 親内クランプは自身の geometry をリサイズのたびに動かしてしまい、
        # メインウィンドウ最小化や resize で位置が崩れる原因になっていた。
        self.geometry_changed.emit()

    def replace_entries_from_texts(self, texts: list[str]) -> tuple[bool, str]:
        """テキスト直接編集モードからの結果を反映する。

        - 既存 entries とテキストを順位ごとに突き合わせ、enabled / 確率設定 等は
          可能な範囲で引き継ぐ
        - 上限超過は enforce_item_limits でカット
        - 新しい行を `set_active_entries` で再構築
        - `item_entries_changed` シグナルで MainWindow へ通知

        Returns:
            (changed_by_limit, warn_message): 上限により切り詰められたかどうかと
            ユーザーへのメッセージ。
        """
        trimmed, changed, warn = enforce_item_limits(list(texts))
        old_entries = list(self._item_entries)
        new_entries: list[ItemEntry] = []
        for j, text in enumerate(trimmed):
            if j < len(old_entries) and old_entries[j].text == text:
                new_entries.append(old_entries[j])
            else:
                # 既存の enabled 状態は同じ位置から引き継ぐ
                if j < len(old_entries):
                    base = old_entries[j]
                    entry = ItemEntry(
                        text=text,
                        enabled=base.enabled,
                        prob_mode=base.prob_mode,
                        prob_value=base.prob_value,
                        split_count=base.split_count,
                    )
                else:
                    entry = ItemEntry(
                        text=text, enabled=True,
                        prob_mode=None, prob_value=None,
                        split_count=1,
                    )
                new_entries.append(entry)
        self.set_active_entries(new_entries)
        self.item_entries_changed.emit(new_entries)
        return changed, warn

    def _live_update_from_text_entries(self, texts: list[str]) -> None:
        """i284: テキスト編集モードからの即時プレビュー反映。

        `replace_entries_from_texts` は行 UI を再構築するためフォーカスや
        スクロール位置を壊してしまう（テキスト編集モード中であっても
        裏側で QLineEdit 群が作り直される）。
        ここでは ItemEntry のリストだけを更新し、シグナルだけ発火する。
        既存の prob_mode / prob_value / split_count / enabled は同位置の
        旧エントリから引き継ぎ、新規行はデフォルトを与える。
        """
        old_entries = list(self._item_entries)
        new_entries: list[ItemEntry] = []
        for j, text in enumerate(texts):
            if j < len(old_entries) and old_entries[j].text == text:
                new_entries.append(old_entries[j])
                continue
            if j < len(old_entries):
                base = old_entries[j]
                new_entries.append(ItemEntry(
                    text=text,
                    enabled=base.enabled,
                    prob_mode=base.prob_mode,
                    prob_value=base.prob_value,
                    split_count=base.split_count,
                ))
            else:
                new_entries.append(ItemEntry(
                    text=text, enabled=True,
                    prob_mode=None, prob_value=None,
                    split_count=1,
                ))
        self._item_entries = new_entries
        self.item_entries_changed.emit(list(new_entries))

    def set_active_entries(self, entries: list[ItemEntry]):
        """アクティブなルーレットの項目データを差し替える。

        将来のマルチルーレット切替時に、編集対象の item_entries を
        外部から一括で入れ替えるための入口。
        既存の項目行 UI を全て再構築する。
        """
        # 既存行を全て削除
        for row in list(self._item_rows):
            self._item_rows_layout.removeWidget(row)
            row.deleteLater()
        self._item_rows.clear()

        # 新しいエントリで行を再構築
        self._item_entries = entries
        for entry in entries:
            self._add_item_row(entry, self._design)

        self._refresh_all_weight_combos()
        # i284: 確率ラベルを反映
        self._refresh_prob_labels()

        # 検索・フィルターをリセット
        self._search_edit.clear()
        self._filter_combo.setCurrentIndex(0)

    def update_win_counts(self, counts: dict[str, int]):
        """各項目行の勝利数ラベルを更新する。

        Args:
            counts: {項目テキスト: 当選回数} の辞書
        """
        for row in self._item_rows:
            text = row._edit.text().strip()
            n = counts.get(text, 0)
            row._win_lbl.setText(str(n) if n > 0 else "0")

    def set_spinning(self, spinning: bool):
        """spin 状態に応じてボタンを有効/無効にする。"""
        self._spin_btn.setEnabled(not spinning)
        self._spin_btn.setText("⏳  スピン中..." if spinning else "▶  スピン開始")

    def set_preset(self, name: str):
        """プリセット表示を外部から更新する。"""
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(name)
        self._preset_combo.blockSignals(False)

    def update_setting(self, key: str, value):
        """外部からの設定変更を UI に反映する（シグナルを出さない）。"""
        if key == "text_size_mode":
            self._text_mode_combo.blockSignals(True)
            self._text_mode_combo.setCurrentIndex(value)
            self._text_mode_combo.blockSignals(False)
        elif key == "donut_hole":
            self._donut_cb.blockSignals(True)
            self._donut_cb.setChecked(value)
            self._donut_cb.blockSignals(False)
        elif key == "profile_idx":
            self._prof_combo.blockSignals(True)
            self._prof_combo.setCurrentIndex(value)
            self._prof_combo.blockSignals(False)
        elif key == "text_direction":
            self._tdir_combo.blockSignals(True)
            self._tdir_combo.setCurrentIndex(value)
            self._tdir_combo.blockSignals(False)
        elif key == "spin_direction":
            self._sdir_combo.blockSignals(True)
            self._sdir_combo.setCurrentIndex(value)
            self._sdir_combo.blockSignals(False)
        elif key == "pointer_angle":
            idx = self._angle_to_preset_idx(value)
            self._ptr_combo.blockSignals(True)
            self._ptr_combo.setCurrentIndex(idx)
            self._ptr_combo.blockSignals(False)
        elif key == "result_close_mode":
            self._result_mode_combo.blockSignals(True)
            self._result_mode_combo.setCurrentIndex(value)
            self._result_mode_combo.blockSignals(False)
            self._update_hold_sec_enabled()
        elif key == "result_hold_sec":
            self._result_sec_spin.blockSignals(True)
            self._result_sec_spin.setValue(value)
            self._result_sec_spin.blockSignals(False)
            # 未設定時は再生時保持表示を通常保持に追従させる
            if not self._macro_hold_cb.isChecked():
                self._macro_sec_spin.blockSignals(True)
                self._macro_sec_spin.setValue(value)
                self._macro_sec_spin.blockSignals(False)
        elif key == "macro_hold_sec":
            is_custom = value is not None
            self._macro_hold_cb.blockSignals(True)
            self._macro_hold_cb.setChecked(is_custom)
            self._macro_hold_cb.blockSignals(False)
            self._macro_sec_spin.blockSignals(True)
            if is_custom:
                self._macro_sec_spin.setValue(value)
            self._macro_sec_spin.setEnabled(is_custom)
            self._macro_sec_lbl.setEnabled(is_custom)
            self._macro_sec_spin.blockSignals(False)
        elif key == "sound_tick_enabled":
            self._sound_tick_cb.blockSignals(True)
            self._sound_tick_cb.setChecked(value)
            self._sound_tick_cb.blockSignals(False)
        elif key == "sound_result_enabled":
            self._sound_result_cb.blockSignals(True)
            self._sound_result_cb.setChecked(value)
            self._sound_result_cb.blockSignals(False)
        elif key == "log_overlay_show":
            # i274: 廃止された設定。互換のため受け流すだけで何もしない。
            pass
        elif key == "spin_duration":
            self._dur_spin.blockSignals(True)
            self._dur_spin.setValue(value)
            self._dur_spin.blockSignals(False)
        elif key == "spin_mode":
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(value)
            self._mode_combo.blockSignals(False)
            self._update_duration_rows_visibility(value)
        elif key == "double_duration":
            self._dbl_spin.blockSignals(True)
            self._dbl_spin.setValue(value)
            self._dbl_spin.blockSignals(False)
        elif key == "triple_duration":
            self._tpl_spin.blockSignals(True)
            self._tpl_spin.setValue(value)
            self._tpl_spin.blockSignals(False)
        elif key == "auto_shuffle":
            self._shuffle_cb.blockSignals(True)
            self._shuffle_cb.setChecked(value)
            self._shuffle_cb.blockSignals(False)
        elif key == "arrangement_direction":
            self._arr_combo.blockSignals(True)
            self._arr_combo.setCurrentIndex(value)
            self._arr_combo.blockSignals(False)
        elif key == "window_transparent":
            self._window_transparent_cb.blockSignals(True)
            self._window_transparent_cb.setChecked(value)
            self._window_transparent_cb.blockSignals(False)
        elif key == "roulette_transparent":
            self._roulette_transparent_cb.blockSignals(True)
            self._roulette_transparent_cb.setChecked(value)
            self._roulette_transparent_cb.blockSignals(False)
        elif key == "tick_volume":
            self._tick_vol_slider.blockSignals(True)
            self._tick_vol_slider.setValue(value)
            self._tick_vol_slider.blockSignals(False)
            self._tick_vol_val.setText(f"{value}%")
        elif key == "win_volume":
            self._win_vol_slider.blockSignals(True)
            self._win_vol_slider.setValue(value)
            self._win_vol_slider.blockSignals(False)
            self._win_vol_val.setText(f"{value}%")
        elif key == "tick_pattern":
            self._tick_pat_combo.blockSignals(True)
            self._tick_pat_combo.setCurrentIndex(value)
            self._tick_pat_combo.blockSignals(False)
        elif key == "win_pattern":
            self._win_pat_combo.blockSignals(True)
            self._win_pat_combo.setCurrentIndex(value)
            self._win_pat_combo.blockSignals(False)
        elif key == "log_timestamp":
            self._log_ts_cb.blockSignals(True)
            self._log_ts_cb.setChecked(value)
            self._log_ts_cb.blockSignals(False)
        elif key == "log_box_border":
            self._log_border_cb.blockSignals(True)
            self._log_border_cb.setChecked(value)
            self._log_border_cb.blockSignals(False)
        elif key == "log_on_top":
            self._log_on_top_cb.blockSignals(True)
            self._log_on_top_cb.setChecked(value)
            self._log_on_top_cb.blockSignals(False)
        elif key == "confirm_reset":
            self._confirm_reset_cb.blockSignals(True)
            self._confirm_reset_cb.setChecked(value)
            self._confirm_reset_cb.blockSignals(False)
        elif key == "confirm_item_delete":
            # i286: 項目削除確認設定の外部変更反映
            self._settings.confirm_item_delete = bool(value)
            if hasattr(self, "_confirm_item_delete_cb"):
                self._confirm_item_delete_cb.blockSignals(True)
                self._confirm_item_delete_cb.setChecked(bool(value))
                self._confirm_item_delete_cb.blockSignals(False)
        elif key == "replay_max_count":
            self._replay_max_spin.blockSignals(True)
            self._replay_max_spin.setValue(value)
            self._replay_max_spin.blockSignals(False)
        elif key == "replay_show_indicator":
            self._replay_indicator_cb.blockSignals(True)
            self._replay_indicator_cb.setChecked(value)
            self._replay_indicator_cb.blockSignals(False)
        elif key == "grip_visible":
            self._grip_visible_cb.blockSignals(True)
            self._grip_visible_cb.setChecked(value)
            self._grip_visible_cb.blockSignals(False)
        elif key == "ctrl_box_visible":
            self._ctrl_box_visible_cb.blockSignals(True)
            self._ctrl_box_visible_cb.setChecked(value)
            self._ctrl_box_visible_cb.blockSignals(False)
        elif key == "float_win_show_instance":
            self._instance_label_cb.blockSignals(True)
            self._instance_label_cb.setChecked(value)
            self._instance_label_cb.blockSignals(False)
        elif key == "settings_panel_float":
            self._float_panel_cb.blockSignals(True)
            self._float_panel_cb.setChecked(value)
            self._float_panel_cb.blockSignals(False)
        elif key == "always_on_top":
            self._aot_cb.blockSignals(True)
            self._aot_cb.setChecked(value)
            self._aot_cb.blockSignals(False)
        elif key == "show_item_prob":
            # i283: 確率/分割 UI の表示 ON/OFF
            self._settings.show_item_prob = bool(value)
            if hasattr(self, "_show_item_prob_cb"):
                self._show_item_prob_cb.blockSignals(True)
                self._show_item_prob_cb.setChecked(bool(value))
                self._show_item_prob_cb.blockSignals(False)
            self._refresh_item_rows_visibility()
        elif key == "show_item_win_count":
            # i283: 当選回数ラベルの表示 ON/OFF
            self._settings.show_item_win_count = bool(value)
            if hasattr(self, "_show_item_win_cb"):
                self._show_item_win_cb.blockSignals(True)
                self._show_item_win_cb.setChecked(bool(value))
                self._show_item_win_cb.blockSignals(False)
            self._refresh_item_rows_visibility()

    def set_panel_theme_mode(self, theme_mode: str):
        """テーマモード変更時に全折りたたみセクションのヘッダーを更新する。"""
        for cs in self._collapsible_map.values():
            cs.set_theme_mode(theme_mode)

    def update_design(self, design: DesignSettings):
        """デザイン変更時にパネル全体の配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._content.setStyleSheet(f"background-color: {design.panel};")
        self._apply_scroll_style(self._scroll, design)
        self._resize_grip.update_design(design)
        self._drag_bar.update_design(design)
        self._apply_combo_style(self._preset_combo, design)
        self._apply_combo_style(self._text_mode_combo, design)
        self._apply_combo_style(self._prof_combo, design)
        self._apply_combo_style(self._tdir_combo, design)
        self._apply_combo_style(self._sdir_combo, design)
        self._apply_combo_style(self._ptr_combo, design)
        self._apply_spin_btn_style(design)

        # パターンセクション
        self._apply_combo_style(self._pattern_combo, design)
        pat_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._pattern_add_btn.setStyleSheet(pat_btn_style)
        self._pattern_del_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._pattern_export_btn.setStyleSheet(pat_btn_style)
        self._pattern_import_btn.setStyleSheet(pat_btn_style)

        # 折りたたみセクション
        for cs in [self._spin_collapsible, self._display_section,
                   self._design_collapsible, self._result_collapsible,
                   self._sound_collapsible, self._log_collapsible,
                   self._replay_collapsible, self._pattern_collapsible,
                   self._items_collapsible]:
            cs.apply_design(design)

        # デザインエディタボタン
        self._design_editor_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 6px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        # ダークテーマ共通スタイル
        sb_style = self._dark_spinbox_style(design)
        cb_style = self._dark_checkbox_style(design)

        # スピン時間
        self._dur_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dur_spin.setStyleSheet(sb_style)

        # スピンモード / ダブル・トリプル時間
        self._mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._mode_combo, design)
        self._dbl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dbl_spin.setStyleSheet(sb_style)
        self._tpl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tpl_spin.setStyleSheet(sb_style)

        # ラベル
        self._preset_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._theme_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._theme_combo, design)
        self._text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._sdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._ptr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._anim_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._anim_spin.setStyleSheet(sb_style)
        self._donut_cb.setStyleSheet(cb_style)
        self._window_transparent_cb.setStyleSheet(cb_style)
        self._roulette_transparent_cb.setStyleSheet(cb_style)
        self._aot_cb.setStyleSheet(cb_style)
        self._grip_visible_cb.setStyleSheet(cb_style)
        self._ctrl_box_visible_cb.setStyleSheet(cb_style)
        self._instance_label_cb.setStyleSheet(cb_style)
        self._float_panel_cb.setStyleSheet(cb_style)
        self._sound_tick_cb.setStyleSheet(cb_style)
        self._sound_result_cb.setStyleSheet(cb_style)
        slider_style = (
            f"QSlider::groove:horizontal {{"
            f"  background: {design.separator}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {design.accent}; width: 12px; margin: -4px 0;"
            f"  border-radius: 6px;"
            f"}}"
        )
        self._tick_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tick_vol_slider.setStyleSheet(slider_style)
        self._tick_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_slider.setStyleSheet(slider_style)
        self._win_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._tick_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._tick_pat_combo, design)
        self._win_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._win_pat_combo, design)
        small_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._tick_file_btn.setStyleSheet(small_btn_style)
        self._tick_test_btn.setStyleSheet(small_btn_style)
        self._win_file_btn.setStyleSheet(small_btn_style)
        self._win_test_btn.setStyleSheet(small_btn_style)
        # log_show_cb は i274 で廃止されたため、ここでは更新しない
        self._log_ts_cb.setStyleSheet(cb_style)
        self._log_border_cb.setStyleSheet(cb_style)
        self._log_on_top_cb.setStyleSheet(cb_style)
        self._confirm_reset_cb.setStyleSheet(cb_style)
        if hasattr(self, "_confirm_item_delete_cb"):
            self._confirm_item_delete_cb.setStyleSheet(cb_style)
        self._log_export_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._log_clear_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._graph_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._shuffle_cb.setStyleSheet(cb_style)
        self._arr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._arr_combo, design)
        self._shuffle_once_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._result_mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._result_mode_combo, design)
        self._result_sec_spin.setStyleSheet(sb_style)
        self._macro_hold_cb.setStyleSheet(cb_style)
        self._macro_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._macro_sec_spin.setStyleSheet(sb_style)
        self._replay_indicator_cb.setStyleSheet(cb_style)
        self._replay_max_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._replay_max_spin.setStyleSheet(sb_style)
        self._replay_count_lbl.setStyleSheet(f"color: {design.text_sub};")

        # 検索・フィルター
        self._search_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._apply_combo_style(self._filter_combo, design)

        # 項目編集行
        self._update_item_rows_design(design)
        self._apply_add_btn_style(self._add_item_btn, design)

        # 項目編集プレースホルダーセクション
        for section in self._item_edit_sections:
            section._apply_style(design)
