"""
PySide6 — 項目編集パネル

内容:
  _SimpleItemDelegate  — シンプルモード項目リスト用デリゲート
  _SimpleItemList      — ダブルクリック制御付き QListWidget
  _ItemPanelAPI        — ItemPanel → SettingsPanel 内部への直接アクセスを遥断するブリッジ
  ItemPanel            — 項目編集専用パネル
"""

from PySide6.QtCore import Qt, Signal, QPoint, QEvent, QRect
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QScrollArea, QWidget,
    QDoubleSpinBox, QSpinBox, QLineEdit, QStackedWidget,
    QPlainTextEdit, QMessageBox,
    QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication,
)

from item_text_helpers import serialize_items_text, parse_items_text, enforce_item_limits
from panel_widgets import _PanelGrip, _PanelDragBar, install_panel_context_menu
from settings_panel import _calc_item_probs, _populate_weight_combo

from bridge import DesignSettings
from app_settings import AppSettings
from item_entry import ItemEntry


class _ItemPanelAPI:
    """ItemPanel が SettingsPanel の内部実装に直接触れないための公開インターフェース。

    SettingsPanel インスタンスをラップし、ItemPanel が必要とする操作のみを公開する。
    これにより ItemPanel から SettingsPanel の内部実装への直接連結を需としなくなる。
    """

    def __init__(self, sp):
        self._sp = sp

    # ─── エントリアクセス ───
    @property
    def entries(self):
        return self._sp._item_entries

    @entries.setter
    def entries(self, v):
        self._sp._item_entries = v

    # ─── 設定アクセス ───
    @property
    def settings(self):
        return self._sp._settings

    # ─── メソッドフォワード ───
    def notify_changed(self):
        self._sp.notify_entries_changed_from_simple()

    def replace_from_texts(self, texts):
        return self._sp.replace_entries_from_texts(texts)

    def live_update(self, texts):
        self._sp._live_update_from_text_entries(texts)

    def set_active(self, entries):
        self._sp.set_active_entries(entries)

    def update_win_counts(self, counts):
        self._sp.update_win_counts(counts)

    def set_pattern_switching(self, enabled):
        self._sp.set_pattern_switching_enabled(enabled)

    # ─── シグナル参照 ───
    @property
    def setting_changed(self):
        return self._sp.setting_changed

    @property
    def shuffle_once_requested(self):
        return self._sp.shuffle_once_requested

    @property
    def arrangement_reset_requested(self):
        return self._sp.arrangement_reset_requested

    @property
    def items_reset_requested(self):
        return self._sp.items_reset_requested

    @property
    def item_entries_changed(self):
        return self._sp.item_entries_changed

    # ─── ヒントボタン dict ───
    def hint_buttons(self) -> dict:
        sp = self._sp
        return {
            sp._add_item_btn:          "項目を 1 行追加する",
            sp._shuffle_once_btn:      "項目をランダムに並び替える（1回）",
            sp._arrangement_reset_btn: "ランダム配置前の並び順に戻す",
            sp._items_reset_btn:       "全項目の確率・分割設定をデフォルトに戻す",
            sp._pattern_add_btn:       "新しいパターンを追加する",
            sp._pattern_del_btn:       "現在のパターンを削除する",
            sp._pattern_export_btn:    "現在のパターンをエクスポートする",
            sp._pattern_import_btn:    "パターンをインポートする",
        }


class _SimpleItemDelegate(QStyledItemDelegate):
    """シンプルモード項目リスト用 delegate。

    項目名を左に、確率（PROB_ROLE）と当選回数（WIN_ROLE）を右固定列として描画する。
    背景・選択・チェックボックスは Qt 標準描画を再利用し、その上にテキストを追加する。
    """

    PROB_ROLE = Qt.ItemDataRole.UserRole        # str: "12.3%" or ""
    WIN_ROLE  = Qt.ItemDataRole.UserRole + 1   # str: "3" or ""

    _PROB_W   = 46   # 確率列幅 (px) — "100.0%" 相当
    _WIN_W    = 24   # 当選回数列幅 (px) — 数字 1〜3 桁
    _COL_GAP  = 4    # 列間余白 (px)
    _R_MARGIN = 4    # 右端余白 (px)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        prob_str = index.data(self.PROB_ROLE) or ""
        win_str  = index.data(self.WIN_ROLE)  or ""

        # 右列の総幅を計算
        right_w = self._R_MARGIN
        if win_str:
            right_w += self._WIN_W + self._COL_GAP
        if prob_str:
            right_w += self._PROB_W + self._COL_GAP

        # text を空にして標準描画（背景・選択・チェックボックス・focus rect のみ）
        opt.text = ""
        style = QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, self.parent())

        # テキスト色（選択状態で切替）
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        color = opt.palette.highlightedText().color() if selected else opt.palette.text().color()

        # 標準テキスト矩形（チェックボックス・アイコン分を除外済み）
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, self.parent()
        )
        name_rect = QRect(
            text_rect.left(), text_rect.top(),
            max(0, text_rect.width() - right_w),
            text_rect.height(),
        )

        painter.save()
        painter.setPen(color)
        painter.setFont(opt.font)

        # 項目名（左寄せ・長い場合は省略）
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        elided = painter.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, max(0, name_rect.width())
        )
        painter.drawText(
            name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided
        )

        # 右固定列（右端から逆順に配置）
        right_x = opt.rect.right() - self._R_MARGIN
        if win_str:
            win_rect = QRect(right_x - self._WIN_W, opt.rect.top(), self._WIN_W, opt.rect.height())
            painter.drawText(
                win_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, win_str
            )
            right_x -= self._WIN_W + self._COL_GAP
        if prob_str:
            prob_rect = QRect(right_x - self._PROB_W, opt.rect.top(), self._PROB_W, opt.rect.height())
            painter.drawText(
                prob_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, prob_str
            )

        painter.restore()


class _SimpleItemList(QListWidget):
    """シンプル表示専用 QListWidget。

    i301: mouseDoubleClickEvent をオーバーライドしてテキスト編集モードへ切り替える。
    チェックボックス領域（左端 _CHECKBOX_WIDTH px 以内）でのダブルクリックは
    通常の Qt 処理に委ねる（チェック操作を壊さない）。
    """

    # Qt デフォルトスタイルのチェックボックス幅 + 余裕 (px)
    _CHECKBOX_WIDTH = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dbl_click_handler = None  # () -> None

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._dbl_click_handler is not None):
            pos = event.position().toPoint()
            item = self.itemAt(pos)
            # 空白領域 (item=None) または項目上でチェックボックス外ならテキスト編集へ
            if item is None or pos.x() > self._CHECKBOX_WIDTH:
                self._dbl_click_handler()
                return  # super() 呼ばない → Qt の activated 等を抑制
        super().mouseDoubleClickEvent(event)


class ItemPanel(QFrame):
    """項目編集専用パネル。

    SettingsPanel から取り外したパターン (グループ) セクションと項目セクションを
    載せ替え、v0.4.4 と同じ「項目編集の主役パネル」として扱う。

    構成 (i289 改訂):
      - 上部ドラッグバー
      - パターン (グループ) 行
      - タイトルバー (アイコン群 + OBS 向けヒント表示)
      - 表示モードスタック
          0: 詳細表示ページ（既存行 UI）
          1: シンプル表示ページ（1 行リスト + 下部編集エリア）
          2: テキスト編集ページ
      - 右下リサイズグリップ

    SettingsPanel 側のロジック (`_item_rows` / `set_active_entries` /
    `replace_entries_from_texts`) は変更なくそのまま流用する。
    """

    geometry_changed = Signal()

    # シンプルモード用確率モード定数（SettingsPanel と同値）
    _PROB_MODE_LABELS = ["変更なし", "重み係数", "固定確率"]
    _PROB_MODE_VALUES = [None, "weight", "fixed"]

    def __init__(self, design: DesignSettings, items_widget: QWidget,
                 pattern_widget: QWidget,
                 api: "_ItemPanelAPI",
                 *, on_drag_bar_changed=None, parent=None):
        super().__init__(parent)
        self._design = design
        self._floating = False
        self.pinned_front = False
        self._api = api
        self._items_widget = items_widget
        self._pattern_widget = pattern_widget
        self._text_edit_mode = False
        # 表示モード: 0=詳細, 1=シンプル
        self._display_mode = getattr(api.settings, "item_panel_display_mode", 0)
        # シンプルモードで選択中の項目インデックス (-1=未選択)
        self._simple_selected_idx = -1
        # ホバー → ヒント表示マップ {button: description}
        self._hint_map: dict = {}
        # シンプルモード用当選回数キャッシュ
        self._simple_win_counts: dict = {}
        # notify_entries_changed_from_simple 起因の _on_entries_changed でフルリビルドしないフラグ
        self._skip_simple_rebuild: bool = False
        # テキスト編集モード開始時のスナップショット（キャンセル時ロールバック用）
        self._text_edit_snapshot: list | None = None

        self.setStyleSheet(f"background-color: {design.panel};")
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 上部ドラッグバー ──
        self._drag_bar = _PanelDragBar(self, design, parent=self)
        outer.addWidget(self._drag_bar)
        install_panel_context_menu(self, self._drag_bar,
                                   on_drag_bar_changed=on_drag_bar_changed)

        # ── パターン (グループ) セクション ──
        if pattern_widget is not None:
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

        # ── タイトルバー（アイコン群）──
        self._title_bar = QFrame()
        self._title_bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {design.panel};"
            f"  border-bottom: 1px solid {design.separator};"
            f"}}"
        )
        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(8, 3, 8, 3)
        title_layout.setSpacing(4)

        self._items_title_lbl = QLabel("項目", self._title_bar)  # i289 t09
        self._items_title_lbl.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._items_title_lbl.setStyleSheet(f"color: {design.text};")
        title_layout.addWidget(self._items_title_lbl)
        title_layout.addStretch(1)

        # アイコンボタン共通スタイル
        icon_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 5px;"
            f"  min-width: 22px; font-size: 8pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
            f"QPushButton:checked {{ background-color: {design.accent}; }}"
        )

        settings = api.settings

        # 確率表示アイコン
        self._show_prob_btn = QPushButton("確")
        self._show_prob_btn.setFont(QFont("Meiryo", 8))
        self._show_prob_btn.setCheckable(True)
        self._show_prob_btn.setChecked(settings.show_item_prob)
        self._show_prob_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._show_prob_btn.setStyleSheet(icon_btn_style)
        self._show_prob_btn.toggled.connect(
            lambda v: self._api.setting_changed.emit("show_item_prob", v)
        )
        self._register_hint(self._show_prob_btn,
                            "確率表示: 各項目の当選確率（%）を表示／非表示")
        title_layout.addWidget(self._show_prob_btn)

        # 当選回数アイコン
        self._show_win_btn = QPushButton("勝")
        self._show_win_btn.setFont(QFont("Meiryo", 8))
        self._show_win_btn.setCheckable(True)
        self._show_win_btn.setChecked(settings.show_item_win_count)
        self._show_win_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._show_win_btn.setStyleSheet(icon_btn_style)
        self._show_win_btn.toggled.connect(
            lambda v: self._api.setting_changed.emit("show_item_win_count", v)
        )
        self._register_hint(self._show_win_btn,
                            "当選回数表示: 各項目の当選回数を表示／非表示")
        title_layout.addWidget(self._show_win_btn)

        # テキスト編集アイコン
        self._text_edit_btn = QPushButton("✎")
        self._text_edit_btn.setFont(QFont("Meiryo", 8))
        self._text_edit_btn.setCheckable(True)
        self._text_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text_edit_btn.setStyleSheet(icon_btn_style)
        self._text_edit_btn.toggled.connect(self._on_text_edit_toggled)
        self._register_hint(self._text_edit_btn,
                            "テキスト編集: 全項目を一括テキスト編集する")
        title_layout.addWidget(self._text_edit_btn)

        # 表示モード切替アイコン
        _mode_init_checked = (self._display_mode == 1)
        self._mode_btn = QPushButton("シ" if not _mode_init_checked else "詳")
        self._mode_btn.setFont(QFont("Meiryo", 8))
        self._mode_btn.setCheckable(True)
        self._mode_btn.setChecked(_mode_init_checked)
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setStyleSheet(icon_btn_style)
        self._mode_btn.toggled.connect(self._on_mode_btn_toggled)
        self._register_hint(self._mode_btn,
                            "表示モード: シンプル表示 ⇄ 詳細表示を切り替える")
        title_layout.addWidget(self._mode_btn)

        outer.addWidget(self._title_bar)

        # SettingsPanel ボタンへのヒント登録
        for btn, hint_text in api.hint_buttons().items():
            self._register_hint(btn, hint_text)

        # ── OBS 向けヒント: レイアウト外のフローティングラベル ──
        # レイアウト内に置くと表示/非表示で項目リストがチラつくため
        # ItemPanel の直接 child として配置し move() で位置管理する。
        self._popup_hint = QLabel("", self)
        self._popup_hint.setFont(QFont("Meiryo", 8))
        self._popup_hint.setStyleSheet(
            f"QLabel {{ color: {design.text}; background-color: {design.panel};"
            f" border: 1px solid {design.separator}; border-radius: 3px;"
            f" padding: 3px 8px; }}"
        )
        self._popup_hint.setWordWrap(False)
        self._popup_hint.hide()

        # ── 表示モードスタック ──
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(
            f"QStackedWidget {{ background-color: {design.panel}; }}"
        )
        outer.addWidget(self._stack, stretch=1)

        # ── スタック 0: 詳細表示ページ（既存行 UI）──
        self._rows_scroll = QScrollArea()
        self._rows_scroll.setWidgetResizable(True)
        self._rows_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._apply_scroll_style(self._rows_scroll, design)
        self._rows_content = QWidget(self)  # i289 t09
        self._rows_content.setStyleSheet(f"background-color: {design.panel};")
        self._rows_layout = QVBoxLayout(self._rows_content)
        self._rows_layout.setContentsMargins(8, 4, 8, 8)
        self._rows_layout.setSpacing(4)

        if items_widget is not None:
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
        self._stack.addWidget(self._rows_scroll)   # index 0

        # ── スタック 1: シンプル表示ページ ──
        self._simple_page = self._build_simple_page(design)
        self._stack.addWidget(self._simple_page)   # index 1

        # ── スタック 2: テキスト編集ページ ──
        self._text_container = QWidget(self)  # i289 t09
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
        self._text_edit.textChanged.connect(self._on_text_edit_changed_live)
        text_v.addWidget(self._text_edit, stretch=1)

        self._text_warn_lbl = QLabel("", self._text_container)  # i289 t09
        self._text_warn_lbl.setFont(QFont("Meiryo", 8))
        self._text_warn_lbl.setStyleSheet(f"color: {design.gold}; padding: 2px 0;")
        self._text_warn_lbl.setWordWrap(True)
        self._text_warn_lbl.setVisible(False)
        text_v.addWidget(self._text_warn_lbl)

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
        self._stack.addWidget(self._text_container)  # index 2

        # 初期スタックページ
        self._stack.setCurrentIndex(0 if self._display_mode == 0 else 1)

        # 最小サイズ
        self.setMinimumWidth(260)
        self.setMinimumHeight(260)

        # 右下リサイズグリップ
        self._resize_grip = _PanelGrip(
            self, design, mode="panel",
            min_w=260, min_h=260, parent=self,
        )

        # シンプルモードで起動した場合はリスト初期化
        if self._display_mode == 1:
            self._refresh_simple_list()

        # 項目変更シグナルを監視してシンプルリストを更新
        self._api.item_entries_changed.connect(self._on_entries_changed)

    # ----------------------------------------------------------------
    #  ヒント表示 (OBS 向け)
    # ----------------------------------------------------------------

    def _register_hint(self, widget, text: str):
        """アイコンにホバーヒントを登録する。"""
        self._hint_map[widget] = text
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        # i341: 項目名 QLineEdit のフォーカス変化でパターンコンボを有効/無効化
        if hasattr(self, '_simple_name_edit') and obj is self._simple_name_edit:
            if event.type() == QEvent.Type.FocusIn:
                self._api.set_pattern_switching(False)
            elif event.type() == QEvent.Type.FocusOut:
                self._api.set_pattern_switching(True)
        if event.type() == QEvent.Type.Enter:
            hint = self._hint_map.get(obj)
            if hint and isinstance(obj, QWidget):
                self._popup_hint.setText(hint)
                self._popup_hint.adjustSize()
                # アイコンボタンの直下に出す（パネル相対座標）
                btn_bottom = obj.mapToGlobal(QPoint(0, obj.height() + 2))
                popup_pos = self.mapFromGlobal(btn_bottom)
                px = min(popup_pos.x(), self.width() - self._popup_hint.width() - 4)
                px = max(4, px)
                self._popup_hint.move(px, popup_pos.y())
                self._popup_hint.raise_()
                self._popup_hint.show()
        elif event.type() == QEvent.Type.Leave:
            if obj in self._hint_map:
                self._popup_hint.hide()
        return super().eventFilter(obj, event)

    # ----------------------------------------------------------------
    #  表示モード切替
    # ----------------------------------------------------------------

    def _on_mode_btn_toggled(self, checked: bool):
        """モードボタン操作: checked=True→シンプル, False→詳細。"""
        new_mode = 1 if checked else 0
        self._mode_btn.setText("詳" if checked else "シ")
        # AppSettings 経由で永続化 + 全体反映
        self._api.setting_changed.emit("item_panel_display_mode", new_mode)
        self.set_display_mode(new_mode)

    def set_display_mode(self, mode: int):
        """表示モードを外部から適用する (0=詳細, 1=シンプル)。"""
        if mode == self._display_mode and self._stack.currentIndex() == mode:
            return
        # テキスト編集中なら終了
        if self._stack.currentIndex() == 2:
            self._exit_text_edit_mode()
        if mode == 1:
            self._refresh_simple_list()
            self._stack.setCurrentIndex(1)
        else:
            # 詳細モードへ戻るとき行 UI を同期
            self._api.set_active(
                list(self._api.entries)
            )
            # 当選回数を再反映（set_active_entries で行が再構築されるため）
            self._api.update_win_counts(self._simple_win_counts)
            self._stack.setCurrentIndex(0)
        self._display_mode = mode
        self._mode_btn.blockSignals(True)
        self._mode_btn.setChecked(mode == 1)
        self._mode_btn.setText("詳" if mode == 1 else "シ")
        self._mode_btn.blockSignals(False)

    def update_setting(self, key: str, value):
        """ItemPanel の設定を外部から更新する。"""
        if key == "show_item_prob":
            self._show_prob_btn.blockSignals(True)
            self._show_prob_btn.setChecked(bool(value))
            self._show_prob_btn.blockSignals(False)
            if self._display_mode == 1:
                self._simple_prob_disp_lbl.setVisible(bool(value))
                self._update_simple_labels()
        elif key == "show_item_win_count":
            self._show_win_btn.blockSignals(True)
            self._show_win_btn.setChecked(bool(value))
            self._show_win_btn.blockSignals(False)
            if self._display_mode == 1:
                self._simple_win_disp_lbl.setVisible(bool(value))
                self._update_simple_labels()
        elif key == "item_panel_display_mode":
            self.set_display_mode(int(value))

    def _on_entries_changed(self, entries: list):
        """SettingsPanel からの項目変更通知: シンプルリストを更新する。

        _skip_simple_rebuild=True の場合はシンプルモード内部からの通知なので
        フルリビルドをスキップする（ラベル更新は _update_simple_labels() が担う）。
        """
        if self._skip_simple_rebuild:
            return
        if self._display_mode == 1 and self._stack.currentIndex() == 1:
            self._refresh_simple_list()

    # ----------------------------------------------------------------
    #  シンプル表示ページ
    # ----------------------------------------------------------------

    def _build_simple_page(self, design: DesignSettings) -> QWidget:
        """シンプル表示ページを構築して返す。"""
        page = QWidget(self)  # i289 t09
        page.setStyleSheet(f"background-color: {design.panel};")
        page_v = QVBoxLayout(page)
        page_v.setContentsMargins(0, 0, 0, 0)
        page_v.setSpacing(0)

        # 1 行リスト（i297: _SimpleItemList サブクラスを使用してダブルクリック編集を制御）
        self._simple_list = _SimpleItemList()
        self._simple_list.setFont(QFont("Meiryo", 9))
        self._simple_list.setStyleSheet(
            f"QListWidget {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  border: none; outline: none;"
            f"}}"
            f"QListWidget::item {{ padding: 0px 2px; }}"
            f"QListWidget::item:selected {{"
            f"  background-color: {design.accent}; color: {design.text};"
            f"}}"
            f"QListWidget::item:hover {{ background-color: {design.separator}; }}"
        )
        self._simple_list.setItemDelegate(_SimpleItemDelegate(self._simple_list))
        self._simple_list.currentRowChanged.connect(self._on_simple_row_changed)
        self._simple_list.itemChanged.connect(self._on_simple_item_changed)
        self._simple_list._dbl_click_handler = self._on_simple_dbl_click
        page_v.addWidget(self._simple_list, stretch=1)

        # 下部アクション行 (常時ランダム / 今すぐランダム / 並びリセット / 項目リセット)
        action_frame = QFrame()
        action_frame.setStyleSheet(
            f"QFrame {{ background-color: {design.panel};"
            f" border-top: 1px solid {design.separator}; }}"
        )
        action_v = QVBoxLayout(action_frame)
        action_v.setContentsMargins(6, 4, 6, 4)
        action_v.setSpacing(3)

        rand_row = QHBoxLayout()
        rand_row.setSpacing(4)
        self._simple_shuffle_cb = QCheckBox("常時ランダム")
        self._simple_shuffle_cb.setFont(QFont("Meiryo", 8))
        self._simple_shuffle_cb.setStyleSheet(f"color: {design.text};")
        self._simple_shuffle_cb.setChecked(
            getattr(self._api.settings, "auto_shuffle", False)
        )
        self._simple_shuffle_cb.toggled.connect(
            lambda v: self._api.setting_changed.emit("auto_shuffle", v)
        )
        rand_row.addWidget(self._simple_shuffle_cb)
        rand_row.addStretch(1)
        self._simple_shuffle_once_btn = QPushButton("🔀 今すぐ")
        self._simple_shuffle_once_btn.setFont(QFont("Meiryo", 8))
        self._simple_shuffle_once_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._simple_shuffle_once_btn.setStyleSheet(
            f"QPushButton {{ background-color: {design.separator}; color: {design.text};"
            f" border: none; border-radius: 3px; padding: 2px 6px; }}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._simple_shuffle_once_btn.clicked.connect(
            self._api.shuffle_once_requested.emit
        )
        rand_row.addWidget(self._simple_shuffle_once_btn)
        action_v.addLayout(rand_row)

        reset_row = QHBoxLayout()
        reset_row.setSpacing(4)
        reset_btn_style = (
            f"QPushButton {{ background-color: {design.separator}; color: {design.text};"
            f" border: none; border-radius: 3px; padding: 2px 6px; }}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._simple_arr_reset_btn = QPushButton("↺ 並びリセット")
        self._simple_arr_reset_btn.setFont(QFont("Meiryo", 8))
        self._simple_arr_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._simple_arr_reset_btn.setStyleSheet(reset_btn_style)
        self._simple_arr_reset_btn.clicked.connect(
            self._api.arrangement_reset_requested.emit
        )
        reset_row.addWidget(self._simple_arr_reset_btn)
        self._simple_items_reset_btn = QPushButton("⟲ 項目リセット")
        self._simple_items_reset_btn.setFont(QFont("Meiryo", 8))
        self._simple_items_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._simple_items_reset_btn.setStyleSheet(reset_btn_style)
        self._simple_items_reset_btn.clicked.connect(
            self._api.items_reset_requested.emit
        )
        reset_row.addWidget(self._simple_items_reset_btn)
        reset_row.addStretch(1)
        action_v.addLayout(reset_row)

        page_v.addWidget(action_frame)

        # 下部編集エリア（選択時に表示）
        self._simple_edit_frame = QFrame()
        self._simple_edit_frame.setStyleSheet(
            f"QFrame {{ background-color: {design.panel};"
            f" border-top: 1px solid {design.separator}; }}"
        )
        edit_v = QVBoxLayout(self._simple_edit_frame)
        edit_v.setContentsMargins(8, 4, 8, 4)
        edit_v.setSpacing(2)

        # 上段: [有効CB] [名前LineEdit] [確率表示lbl] [当選数lbl] [▲][▼][×]
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(2)

        self._simple_enabled_cb = QCheckBox()
        self._simple_enabled_cb.setStyleSheet(f"color: {design.text};")
        self._simple_enabled_cb.toggled.connect(self._on_simple_enabled_changed)
        top_row.addWidget(self._simple_enabled_cb)

        self._simple_name_edit = QLineEdit()
        self._simple_name_edit.setFont(QFont("Meiryo", 8))
        self._simple_name_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {design.separator}; color: {design.text};"
            f" border: 1px solid {design.separator}; border-radius: 3px; padding: 2px 4px; }}"
        )
        self._simple_name_edit.editingFinished.connect(self._on_simple_name_changed)
        self._simple_name_edit.textChanged.connect(self._on_simple_name_live)  # i306: 入力途中即時反映
        # i341: フォーカス変化でパターンコンボの有効/無効を切り替えるためフィルタ登録
        self._simple_name_edit.installEventFilter(self)
        top_row.addWidget(self._simple_name_edit, stretch=1)

        # 確率・当選数表示ラベル（read-only、詳細モードと同スタイル）
        self._simple_prob_disp_lbl = QLabel("", self._simple_edit_frame)  # i289 t09
        self._simple_prob_disp_lbl.setFont(QFont("Meiryo", 7))
        self._simple_prob_disp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._simple_prob_disp_lbl.setMinimumWidth(40)
        self._simple_prob_disp_lbl.setStyleSheet(
            f"color: {design.text_sub}; background-color: transparent;"
        )
        self._simple_prob_disp_lbl.setToolTip("当選確率（％）")
        self._simple_prob_disp_lbl.setVisible(self._api.settings.show_item_prob)
        top_row.addWidget(self._simple_prob_disp_lbl)

        self._simple_win_disp_lbl = QLabel("", self._simple_edit_frame)  # i289 t09
        self._simple_win_disp_lbl.setFont(QFont("Meiryo", 7))
        self._simple_win_disp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._simple_win_disp_lbl.setFixedWidth(28)
        self._simple_win_disp_lbl.setStyleSheet(
            f"color: {design.gold}; background-color: transparent;"
        )
        self._simple_win_disp_lbl.setToolTip("当選回数")
        self._simple_win_disp_lbl.setVisible(self._api.settings.show_item_win_count)
        top_row.addWidget(self._simple_win_disp_lbl)

        # 操作ボタン (詳細モードと同サイズ・スタイル)
        btn_font = QFont("Meiryo", 8)
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._simple_up_btn = QPushButton("▲")
        self._simple_up_btn.setFont(btn_font)
        self._simple_up_btn.setStyleSheet(btn_style)
        self._simple_up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._simple_up_btn.clicked.connect(lambda: self._on_simple_move(-1))
        top_row.addWidget(self._simple_up_btn)

        self._simple_down_btn = QPushButton("▼")
        self._simple_down_btn.setFont(btn_font)
        self._simple_down_btn.setStyleSheet(btn_style)
        self._simple_down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._simple_down_btn.clicked.connect(lambda: self._on_simple_move(1))
        top_row.addWidget(self._simple_down_btn)

        self._simple_delete_btn = QPushButton("×")
        self._simple_delete_btn.setFont(btn_font)
        self._simple_delete_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._simple_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._simple_delete_btn.clicked.connect(self._on_simple_delete)
        top_row.addWidget(self._simple_delete_btn)

        edit_v.addLayout(top_row)

        # 下段: 確率設定 (詳細モードと同スタイル・構成)
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
        prob_row = QHBoxLayout()
        prob_row.setContentsMargins(20, 0, 0, 0)
        prob_row.setSpacing(4)

        self._simple_mode_combo = QComboBox()
        self._simple_mode_combo.setFont(QFont("Meiryo", 7))
        self._simple_mode_combo.setStyleSheet(combo_style)
        self._simple_mode_combo.addItems(self._PROB_MODE_LABELS)
        self._simple_mode_combo.currentIndexChanged.connect(self._on_simple_mode_changed)
        prob_row.addWidget(self._simple_mode_combo)

        # 値ウィジェット (QStackedWidget: page0=空, page1=重み係数, page2=固定確率)
        self._simple_value_stack = QStackedWidget()

        empty_lbl = QLabel("")
        self._simple_value_stack.addWidget(empty_lbl)  # page 0

        n = len(self._api.entries) or 1
        self._simple_weight_combo = QComboBox()
        self._simple_weight_combo.setFont(QFont("Meiryo", 7))
        self._simple_weight_combo.setStyleSheet(combo_style)
        _populate_weight_combo(self._simple_weight_combo, n)
        self._simple_weight_combo.currentIndexChanged.connect(self._on_simple_weight_changed)
        self._simple_value_stack.addWidget(self._simple_weight_combo)  # page 1

        self._simple_fixed_spin = QDoubleSpinBox()
        self._simple_fixed_spin.setFont(QFont("Meiryo", 7))
        self._simple_fixed_spin.setRange(0.1, 99.9)
        self._simple_fixed_spin.setSingleStep(0.5)
        self._simple_fixed_spin.setDecimals(1)
        self._simple_fixed_spin.setSuffix(" %")
        self._simple_fixed_spin.setValue(10.0)
        self._simple_fixed_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
        )
        self._simple_fixed_spin.valueChanged.connect(self._on_simple_fixed_changed)  # i307: editingFinished → valueChanged で即時反映
        self._simple_value_stack.addWidget(self._simple_fixed_spin)  # page 2

        prob_row.addWidget(self._simple_value_stack, stretch=1)

        split_lbl = QLabel("分割:")
        split_lbl.setFont(QFont("Meiryo", 7))
        split_lbl.setStyleSheet(f"color: {design.text_sub};")
        prob_row.addWidget(split_lbl)

        self._simple_split_spin = QSpinBox()
        self._simple_split_spin.setFont(QFont("Meiryo", 7))
        self._simple_split_spin.setRange(1, 10)
        self._simple_split_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"  min-width: 36px; max-width: 48px;"
            f"}}"
        )
        self._simple_split_spin.valueChanged.connect(self._on_simple_split_changed)
        prob_row.addWidget(self._simple_split_spin)

        edit_v.addLayout(prob_row)

        self._simple_edit_frame.setVisible(False)
        page_v.addWidget(self._simple_edit_frame)

        return page

    def _refresh_simple_list(self):
        """シンプルリストを _item_entries からテキスト+チェックボックスで再構築する。

        t05: setItemWidget / 独自 row QWidget を廃止し、QListWidgetItem のみで構成。
        カスタムウィジェット生成・installEventFilter をなくすことで起動安定性を確保。
        i302: 確率/当選数を UserRole データとして保持し、delegate で右固定列として描画する。
        """
        entries = self._api.entries
        probs = _calc_item_probs(list(entries))

        self._simple_list.blockSignals(True)
        prev_row = self._simple_list.currentRow()
        self._simple_list.clear()

        s = self._api.settings
        for i, entry in enumerate(entries):
            prob_val = probs[i] if i < len(probs) else None
            name = entry.text.replace("\r\n", " ").replace("\n", " ")
            item = QListWidgetItem(name)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                Qt.CheckState.Checked if entry.enabled else Qt.CheckState.Unchecked
            )
            prob_str = f"{prob_val:.1f}%" if s.show_item_prob and prob_val is not None else ""
            win_count = self._simple_win_counts.get(entry.text, 0)
            win_str = str(win_count) if s.show_item_win_count and win_count > 0 else ""
            item.setData(_SimpleItemDelegate.PROB_ROLE, prob_str)
            item.setData(_SimpleItemDelegate.WIN_ROLE, win_str)
            self._simple_list.addItem(item)

        # 選択復元
        new_count = self._simple_list.count()
        if prev_row >= 0 and prev_row < new_count:
            self._simple_list.setCurrentRow(prev_row)
        elif self._simple_selected_idx >= 0 and self._simple_selected_idx < new_count:
            self._simple_list.setCurrentRow(self._simple_selected_idx)
        self._simple_list.blockSignals(False)

        # 編集エリア更新
        idx = self._simple_list.currentRow()
        if 0 <= idx < len(entries):
            self._simple_selected_idx = idx
            self._populate_simple_edit(idx)
        else:
            self._simple_edit_frame.setVisible(False)

    def _update_simple_labels(self):
        """既存の QListWidgetItem テキストとチェック状態のみ差し替える（フルリビルドなし）。

        t05: setItemWidget 廃止後はテキストアイテムを直接編集する。
        項目の追加・削除・並び替え後は _refresh_simple_list() を使うこと。
        i302: 確率/当選数を UserRole データとして更新し、delegate が再描画する。
        """
        entries = self._api.entries
        probs = _calc_item_probs(list(entries))

        s = self._api.settings
        self._simple_list.blockSignals(True)
        for i in range(self._simple_list.count()):
            if i >= len(entries):
                break
            item = self._simple_list.item(i)
            entry = entries[i]
            prob_val = probs[i] if i < len(probs) else None
            prob_str = f"{prob_val:.1f}%" if s.show_item_prob and prob_val is not None else ""
            win_count = self._simple_win_counts.get(entry.text, 0)
            win_str = str(win_count) if s.show_item_win_count and win_count > 0 else ""
            item.setData(_SimpleItemDelegate.PROB_ROLE, prob_str)
            item.setData(_SimpleItemDelegate.WIN_ROLE, win_str)
            item.setCheckState(
                Qt.CheckState.Checked if entry.enabled else Qt.CheckState.Unchecked
            )
        self._simple_list.blockSignals(False)

        # 編集エリアの表示ラベルも更新
        idx = self._simple_selected_idx
        if 0 <= idx < len(entries):
            entry = entries[idx]
            pv = probs[idx] if idx < len(probs) else None
            self._simple_prob_disp_lbl.setText(f"{pv:.1f}%" if pv is not None else "")
            win_count = self._simple_win_counts.get(entry.text, 0)
            self._simple_win_disp_lbl.setText(str(win_count) if win_count > 0 else "")

    def _on_simple_row_changed(self, row: int):
        """シンプルリストで行選択が変わった。"""
        entries = self._api.entries
        if 0 <= row < len(entries):
            self._simple_selected_idx = row
            self._populate_simple_edit(row)
        else:
            self._simple_edit_frame.setVisible(False)

    def _on_simple_dbl_click(self):
        """シンプルリストのダブルクリック: テキスト編集モードへ突入。

        i301: テキスト編集アイコン押下と同じ動作を再利用する。
        """
        if not self._text_edit_btn.isChecked():
            self._text_edit_btn.setChecked(True)

    def _populate_simple_edit(self, idx: int):
        """指定インデックスの項目データを編集エリアへ反映する。"""
        entries = self._api.entries
        if idx < 0 or idx >= len(entries):
            self._simple_edit_frame.setVisible(False)
            return

        self._simple_selected_idx = idx  # i292: 常に内部選択を同期
        entry = entries[idx]
        # シグナルを一時停止してUIを更新
        for w in (self._simple_name_edit, self._simple_enabled_cb,
                  self._simple_mode_combo, self._simple_weight_combo,
                  self._simple_fixed_spin, self._simple_split_spin):
            w.blockSignals(True)

        self._simple_name_edit.setText(entry.text.replace("\r\n", " ").replace("\n", " "))
        self._simple_enabled_cb.setChecked(entry.enabled)

        mode_idx = 0
        if entry.prob_mode == "weight":
            mode_idx = 1
        elif entry.prob_mode == "fixed":
            mode_idx = 2
        self._simple_mode_combo.setCurrentIndex(mode_idx)

        # 重み係数コンボを有効項目数に応じて再構築してから選択
        n = len(entries)
        _populate_weight_combo(self._simple_weight_combo, n)
        if entry.prob_mode == "weight":
            val = float(entry.prob_value) if entry.prob_value is not None else 1.0
            best = 0
            best_diff = float("inf")
            for ci in range(self._simple_weight_combo.count()):
                cv = self._simple_weight_combo.itemData(ci)
                if cv is not None and abs(float(cv) - val) < best_diff:
                    best_diff = abs(float(cv) - val)
                    best = ci
            self._simple_weight_combo.setCurrentIndex(best)

        # 固定確率スピン
        if entry.prob_mode == "fixed":
            v = float(entry.prob_value) if entry.prob_value is not None else 10.0
            self._simple_fixed_spin.setValue(v)

        self._simple_value_stack.setCurrentIndex(mode_idx)
        self._simple_split_spin.setValue(entry.split_count if entry.split_count else 1)

        for w in (self._simple_name_edit, self._simple_enabled_cb,
                  self._simple_mode_combo, self._simple_weight_combo,
                  self._simple_fixed_spin, self._simple_split_spin):
            w.blockSignals(False)

        # 確率・当選数ラベル更新
        entries_list = list(entries)
        probs = _calc_item_probs(entries_list)
        pv = probs[idx] if idx < len(probs) else None
        self._simple_prob_disp_lbl.setText(f"{pv:.1f}%" if pv is not None else "")
        win_count = self._simple_win_counts.get(entry.text, 0)
        self._simple_win_disp_lbl.setText(str(win_count) if win_count > 0 else "")

        # A: 現在の設定値に基づいてラベル可視性を明示的に再適用
        s = self._api.settings
        self._simple_prob_disp_lbl.setVisible(s.show_item_prob)
        self._simple_win_disp_lbl.setVisible(s.show_item_win_count)

        # 上下ボタンの有効化
        self._simple_up_btn.setEnabled(idx > 0)
        self._simple_down_btn.setEnabled(idx < len(entries) - 1)

        self._simple_edit_frame.setVisible(True)

    def _on_simple_mode_changed(self, idx: int):
        """確率モード変更。"""
        self._simple_value_stack.setCurrentIndex(idx)
        self._apply_simple_entry_change()

    def _on_simple_name_changed(self):
        """項目名確定（editingFinished）。"""
        self._apply_simple_entry_change()

    def _on_simple_name_live(self, text: str):
        """項目名入力途中の即時反映（i306）。"""
        idx = self._simple_selected_idx
        entries = self._api.entries
        if idx < 0 or idx >= len(entries):
            return
        name = text.strip()
        if not name:
            return
        entries[idx].text = name
        # リストのその行の表示テキストを更新
        item = self._simple_list.item(idx)
        if item is not None:
            self._simple_list.blockSignals(True)
            item.setText(name)
            self._simple_list.blockSignals(False)
        # セグメント反映（フルリビルドを防ぐ）
        self._skip_simple_rebuild = True
        try:
            self._api.notify_changed()
        finally:
            self._skip_simple_rebuild = False

    def _on_simple_enabled_changed(self, checked: bool):
        """有効/無効変更。"""
        self._apply_simple_entry_change()

    def _on_simple_weight_changed(self, idx: int):
        """重み係数コンボ変更。"""
        self._apply_simple_entry_change()

    def _on_simple_fixed_changed(self, value: float):
        """固定確率スピン変更。"""
        self._apply_simple_entry_change()

    def _on_simple_item_changed(self, item: QListWidgetItem):
        """チェックボックス操作 → entry.enabled 更新（フルリビルドなし）。

        t05: setItemWidget 廃止後は itemChanged シグナルで ON/OFF を受け取る。
        """
        row = self._simple_list.row(item)
        entries = self._api.entries
        if 0 <= row < len(entries):
            entries[row].enabled = (item.checkState() == Qt.CheckState.Checked)
            # 選択中の行なら編集エリアの CB も同期
            if row == self._simple_selected_idx:
                self._simple_enabled_cb.blockSignals(True)
                self._simple_enabled_cb.setChecked(entries[row].enabled)
                self._simple_enabled_cb.blockSignals(False)
            # この行を選択状態にする
            if self._simple_list.currentRow() != row:
                self._simple_list.setCurrentRow(row)
            # フルリビルドを防ぎつつ通知（確率再計算 + ルーレット反映）
            self._skip_simple_rebuild = True
            try:
                self._api.notify_changed()
            finally:
                self._skip_simple_rebuild = False
            # テキスト + チェック状態のみ差し替え（有効状態変化で確率が変わる）
            self._update_simple_labels()

    def _on_simple_split_changed(self, value: int):
        """分割数変更。"""
        self._apply_simple_entry_change()

    def _apply_simple_entry_change(self):
        """編集エリアの値を _item_entries へ反映して通知する。"""
        idx = self._simple_selected_idx
        entries = self._api.entries
        if idx < 0 or idx >= len(entries):
            return

        entry = entries[idx]
        entry.text = self._simple_name_edit.text().strip() or entry.text
        entry.enabled = self._simple_enabled_cb.isChecked()
        mode_idx = self._simple_mode_combo.currentIndex()
        entry.prob_mode = self._PROB_MODE_VALUES[mode_idx]
        if entry.prob_mode is None:
            entry.prob_value = None
        elif entry.prob_mode == "weight":
            entry.prob_value = self._simple_weight_combo.currentData()
        else:  # "fixed"
            entry.prob_value = self._simple_fixed_spin.value()
        entry.split_count = self._simple_split_spin.value()

        # フルリビルドを防ぎつつ通知（確率再計算 + ルーレット反映）
        self._skip_simple_rebuild = True
        try:
            self._api.notify_changed()
        finally:
            self._skip_simple_rebuild = False
        # ラベルのみ更新（名前・確率・当選数）
        self._update_simple_labels()

    def _on_simple_move(self, direction: int):
        """選択項目を上(-1)または下(+1)へ移動する。"""
        idx = self._simple_selected_idx
        entries = list(self._api.entries)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(entries):
            return
        entries[idx], entries[new_idx] = entries[new_idx], entries[idx]
        self._api.entries = entries
        self._simple_selected_idx = new_idx
        self._api.notify_changed()
        # リスト再構築後に選択位置を更新
        self._simple_list.blockSignals(True)
        self._simple_list.setCurrentRow(new_idx)
        self._simple_list.blockSignals(False)
        self._populate_simple_edit(new_idx)

    def _on_simple_delete(self):
        """選択項目を削除する。"""
        idx = self._simple_selected_idx
        entries = list(self._api.entries)
        if idx < 0 or idx >= len(entries) or len(entries) <= 1:
            return
        settings = self._api.settings
        if getattr(settings, "confirm_item_delete", True):
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self,
                "削除確認",
                f"「{entries[idx].text}」を削除しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        entries.pop(idx)
        self._api.entries = entries
        # 選択を調整
        self._simple_selected_idx = min(idx, len(entries) - 1)
        self._api.notify_changed()

    # ----------------------------------------------------------------
    #  テキスト編集モード
    # ----------------------------------------------------------------

    def _on_text_edit_toggled(self, on: bool):
        if on:
            entries = self._api.entries
            # i305: 開始時スナップショット保存（キャンセル時ロールバック用）
            self._text_edit_snapshot = list(entries)
            text = serialize_items_text([e.text for e in entries])
            self._text_edit.blockSignals(True)
            self._text_edit.setPlainText(text)
            self._text_edit.blockSignals(False)
            self._text_warn_lbl.setVisible(False)
            self._stack.setCurrentIndex(2)
            self._text_edit.setFocus()
            # i341: テキスト編集開始 → パターンコンボ無効化
            self._api.set_pattern_switching(False)
        else:
            self._stack.setCurrentIndex(self._display_mode)

    def is_text_edit_mode(self) -> bool:
        """テキスト編集モード中かどうか。MainWindow の ESC 処理から参照。"""
        return self._stack.currentIndex() == 2

    def is_item_name_editing(self) -> bool:
        """項目名のインライン編集中かどうか。

        i340: テキスト編集モード（textarea）または項目名 QLineEdit にフォーカスが
        ある場合に True を返す。パターン切替禁止判定に使用する。
        """
        if self.is_text_edit_mode():
            return True
        if hasattr(self, '_simple_name_edit') and self._simple_name_edit.hasFocus():
            return True
        return False

    def cancel_text_edit(self):
        """テキスト編集をキャンセルする。MainWindow の ESC 処理から呼ばれる。"""
        self._on_text_cancel()

    def _exit_text_edit_mode(self):
        """テキスト編集モードを終了して元の表示モードへ戻る。"""
        self._text_edit_btn.blockSignals(True)
        self._text_edit_btn.setChecked(False)
        self._text_edit_btn.blockSignals(False)
        self._stack.setCurrentIndex(self._display_mode)
        # i341: テキスト編集終了 → パターンコンボ再有効化
        self._api.set_pattern_switching(True)

    def _on_text_save(self):
        raw = self._text_edit.toPlainText()
        parsed = parse_items_text(raw)
        if not parsed:
            self._text_warn_lbl.setText("項目が 0 件になるため保存しません")
            self._text_warn_lbl.setVisible(True)
            return
        changed, warn = self._api.replace_from_texts(parsed)
        if changed and warn:
            self._text_warn_lbl.setText(warn)
            self._text_warn_lbl.setVisible(True)
            new_entries = self._api.entries
            self._text_edit.blockSignals(True)
            self._text_edit.setPlainText(
                serialize_items_text([e.text for e in new_entries])
            )
            self._text_edit.blockSignals(False)
        else:
            self._text_warn_lbl.setVisible(False)
        self._text_edit_snapshot = None  # i305: 保存確定 → スナップショット破棄
        self._exit_text_edit_mode()
        # i304: 保存通知が届いた時点ではスタックがテキスト編集ページ(2)だったため
        # _on_entries_changed の条件(currentIndex==1)を満たせずリビルドされなかった。
        # モード終了後に明示的に再同期する。
        if self._display_mode == 1:
            self._refresh_simple_list()

    def _on_text_cancel(self):
        # i305: スナップショットへロールバック（live preview で変わっていた状態も戻す）
        if self._text_edit_snapshot is not None:
            self._api.entries = list(self._text_edit_snapshot)
            self._api.notify_changed()
            self._text_edit_snapshot = None
        self._exit_text_edit_mode()
        if self._display_mode == 1:
            self._refresh_simple_list()

    def _on_text_edit_changed_live(self):
        """i305: テキスト編集モードでの入力途中即時プレビュー反映（live update 復活）。

        キャンセル / ESC では _on_text_cancel によりスナップショットへ巻き戻しされる。
        """
        raw = self._text_edit.toPlainText()
        parsed = parse_items_text(raw)
        if not parsed:
            return
        trimmed, _changed, _warn = enforce_item_limits(list(parsed))
        if not trimmed:
            return
        self._api.live_update(trimmed)

    # ----------------------------------------------------------------
    #  ドラッグ吸収
    # ----------------------------------------------------------------

    def mousePressEvent(self, event):
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
    def _apply_scroll_style(scroll: QScrollArea, design: DesignSettings):
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

    def update_win_counts(self, counts: dict):
        """当選回数キャッシュを更新し、テキストアイテムのみ差し替える（フルリビルドなし）。"""
        self._simple_win_counts = counts
        if self._display_mode == 1 and self._stack.currentIndex() == 1:
            self._update_simple_labels()
        # 編集エリアの当選数ラベルも更新（モードに関わらず）
        if self._simple_selected_idx >= 0:
            entries = self._api.entries
            if self._simple_selected_idx < len(entries):
                entry = entries[self._simple_selected_idx]
                win_count = counts.get(entry.text, 0)
                self._simple_win_disp_lbl.setText(str(win_count) if win_count > 0 else "")

    def update_design(self, design: DesignSettings):
        """デザイン変更時に配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._rows_content.setStyleSheet(f"background-color: {design.panel};")
        self._apply_scroll_style(self._rows_scroll, design)
        self._resize_grip.update_design(design)
        self._drag_bar.update_design(design)
        # タイトルバー
        self._title_bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {design.panel};"
            f"  border-bottom: 1px solid {design.separator};"
            f"}}"
        )
        self._items_title_lbl.setStyleSheet(f"color: {design.text};")
        self._popup_hint.setStyleSheet(
            f"QLabel {{ color: {design.text}; background-color: {design.panel};"
            f" border: 1px solid {design.separator}; border-radius: 3px;"
            f" padding: 3px 8px; }}"
        )
        icon_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 5px;"
            f"  min-width: 22px; font-size: 8pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
            f"QPushButton:checked {{ background-color: {design.accent}; }}"
        )
        for btn in (self._show_prob_btn, self._show_win_btn,
                    self._text_edit_btn, self._mode_btn):
            btn.setStyleSheet(icon_btn_style)
        # シンプルリストを再構築してデザイン反映
        if self._display_mode == 1:
            self._refresh_simple_list()

