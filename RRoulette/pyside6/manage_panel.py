"""
RRoulette PySide6 — 全体管理パネル

settings_panel.py から分離した ManagePanel クラス。
SettingsPanel / ItemPanel に依存せず、独立して動作する。

責務:
  - 各パネル（項目パネル / 設定パネル）の表示/非表示制御
  - ルーレット一覧の表示と操作（追加 / アクティブ切替 / 表示切替 / 削除）
  - 設定一括適用フラグの管理
  - パネル位置初期化リクエストの発行
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QScrollArea, QWidget,
    QSizePolicy, QSpinBox, QDoubleSpinBox,
    QLineEdit, QStackedWidget, QComboBox, QSlider,
)

from app_constants import APP_VERSION
from design_models import DesignSettings
from panel_widgets import (
    _PanelDragBar, install_panel_context_menu, apply_transparent_to_widget_tree,
    NoWheelSlider, NoWheelSpinBox, NoWheelDoubleSpinBox, NoWheelComboBox,
    CollapsibleSection,
)


class _RouletteNameBtn(QPushButton):
    """ルーレット名ボタン。ダブルクリックを単独シグナルで通知する。"""
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        # 親クラスは呼ばない（クリックシグナルを抑制するため）


class _RenameLineEdit(QLineEdit):
    """ルーレット名インライン編集用 QLineEdit。Esc でキャンセルを通知する。"""
    escape_pressed = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
        else:
            super().keyPressEvent(event)


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
    roulette_add_requested = Signal()
    roulette_activate_requested = Signal(str)
    roulette_visibility_toggled = Signal(str, bool)
    roulette_delete_requested = Signal(str)
    apply_to_all_changed = Signal(bool)  # i347: 一括適用フラグ
    roulette_pkg_export_requested = Signal()  # i419: ルーレット package エクスポート
    roulette_pkg_import_requested = Signal()  # i419: ルーレット package インポート
    roulette_only_hide_changed = Signal(str, bool)  # i463: key, value
    manage_panel_float_changed = Signal(bool)        # i465: 管理パネル独立化
    auto_hide_enabled_changed = Signal(bool)         # i485: 自動全面非表示 ON/OFF
    auto_hide_seconds_changed = Signal(int)          # i485: 自動非表示秒数
    auto_hide_fade_changed = Signal(bool)            # i486: 自動非表示フェードアウト ON/OFF
    auto_hide_fade_seconds_changed = Signal(float)   # i487: フェードアウト時間（秒）
    auto_hide_only_roulette_only_changed = Signal(bool)   # i098: ルーレット以外非表示時のみ有効
    auto_hide_after_spin_restore_changed = Signal(bool)   # i098: 再表示後スピン後に有効
    link_enabled_changed = Signal(bool)           # i099: 連携受信 ON/OFF
    link_port_changed = Signal(int)               # i099: 連携受信ポート
    link_max_hold_changed = Signal(int)           # i099: 連携メッセージ保持件数
    link_show_time_changed = Signal(bool)         # i100: 連携パネル時刻列表示
    roulette_rename_requested = Signal(str, str)  # roulette_id, new_name
    ticket_panel_toggled = Signal(bool)   # i051: チケットパネル表示切替
    seq_panel_toggled = Signal(bool)      # i051: 実行パネル表示切替
    link_panel_toggled = Signal(bool)     # Phase1: 連携メッセージパネル表示切替
    # v0.6.1: 設定パネルから移動したアプリ全体設定の変更通知 (key, value)
    app_setting_changed = Signal(str, object)
    # v0.6.1: 全体初期化要求
    global_reset_requested = Signal()
    # v0.6.1: グループ単位の初期化要求
    ro_only_reset_requested = Signal()       # ルーレット以外非表示時
    app_settings_reset_requested = Signal()  # アプリ設定（全サブグループ）
    # v0.6.1: アプリ設定内サブグループ単位の初期化要求 (subgroup_key)
    app_subgroup_reset_requested = Signal(str)

    def __init__(self, design: DesignSettings, *,
                 items_visible: bool = True,
                 settings_visible: bool = False,
                 ticket_visible: bool = False,
                 seq_visible: bool = False,
                 on_drag_bar_changed=None,
                 roulette_only_show_selection_handle: bool = True,
                 roulette_only_show_title_plate: bool = True,
                 roulette_only_show_graph_btn: bool = True,
                 roulette_only_show_grip: bool = True,
                 roulette_only_show_log: bool = True,
                 roulette_only_show_manage_panel: bool = False,
                 roulette_only_show_items_panel: bool = False,
                 roulette_only_show_settings_panel: bool = False,
                 roulette_only_show_execution_panel: bool = True,
                 roulette_only_show_ticket_panel: bool = False,
                 link_visible: bool = False,
                 roulette_only_show_link_panel: bool = False,
                 manage_panel_float: bool = False,
                 auto_hide_enabled: bool = True,
                 auto_hide_seconds: int = 10,
                 auto_hide_fade_enabled: bool = True,
                 auto_hide_fade_seconds: float = 0.6,
                 auto_hide_only_in_roulette_only_mode: bool = False,
                 auto_hide_after_spin_after_restore: bool = False,
                 link_integration_enabled: bool = False,
                 link_integration_port: int = 12345,
                 link_integration_max_hold: int = 200,
                 link_panel_show_time: bool = False,
                 settings: "AppSettings | None" = None,
                 parent=None):
        super().__init__(parent)
        self._design = design
        self._settings = settings
        self.pinned_front = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 上部ドラッグバー (パネル移動の起点)
        self._drag_bar = _PanelDragBar(self, design, parent=self)
        outer.addWidget(self._drag_bar)
        # 右クリック → 移動バー表示/非表示
        install_panel_context_menu(self, self._drag_bar,
                                   on_drag_bar_changed=on_drag_bar_changed)

        # コンテンツ
        body = QFrame(self)  # i068: 親なし HWND フラッシュ防止
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)

        # i053: 3グループ 折りたたみ式
        _grp_toggle_style = (
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text};"
            f"  border: none; text-align: left; padding: 2px 0px; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ color: {design.accent}; }}"
        )
        _float_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 5px;"
            f"  min-width: 22px; font-size: 8pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
            f"QPushButton:checked {{ background-color: {design.accent}; }}"
        )

        # ── Group 1: パネル管理（初期: 開く） ──────────────────────
        _panel_grp_hdr = QHBoxLayout()
        _panel_grp_hdr.setContentsMargins(0, 0, 0, 0)
        _panel_grp_hdr.setSpacing(4)

        self._panel_grp_btn = QPushButton("▼ パネル管理")
        self._panel_grp_btn.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._panel_grp_btn.setCheckable(True)
        self._panel_grp_btn.setChecked(True)
        self._panel_grp_btn.setStyleSheet(_grp_toggle_style)
        self._panel_grp_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._panel_grp_btn.toggled.connect(self._on_panel_grp_toggle)
        _panel_grp_hdr.addWidget(self._panel_grp_btn, stretch=1)

        self._manage_float_btn = QPushButton("独")
        self._manage_float_btn.setFont(QFont("Meiryo", 8))
        self._manage_float_btn.setCheckable(True)
        self._manage_float_btn.setChecked(manage_panel_float)
        self._manage_float_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manage_float_btn.setStyleSheet(_float_btn_style)
        self._manage_float_btn.setToolTip(
            "独立化: 管理パネルをメインウィンドウから独立した\n"
            "フローティングウィンドウにします"
        )
        self._manage_float_btn.toggled.connect(self.manage_panel_float_changed.emit)
        _panel_grp_hdr.addWidget(self._manage_float_btn)

        body_layout.addLayout(_panel_grp_hdr)

        self._panel_grp_content = QWidget(body)  # i068: 親なし HWND フラッシュ防止
        _pgc = QVBoxLayout(self._panel_grp_content)
        _pgc.setContentsMargins(0, 4, 0, 4)
        _pgc.setSpacing(4)

        _mp_hint = QLabel("管理パネル（このウィンドウ） — F1 で開閉")
        _mp_hint.setFont(QFont("Meiryo", 8))
        _mp_hint.setStyleSheet(f"color: {design.text_sub};")
        _pgc.addWidget(_mp_hint)

        self._items_cb = QCheckBox("項目パネルを表示 (F2)")
        self._items_cb.setFont(QFont("Meiryo", 9))
        self._items_cb.setStyleSheet(f"color: {design.text};")
        self._items_cb.setChecked(items_visible)
        self._items_cb.toggled.connect(self.items_panel_toggled.emit)
        _pgc.addWidget(self._items_cb)

        self._settings_cb = QCheckBox("設定パネルを表示 (F3)")
        self._settings_cb.setFont(QFont("Meiryo", 9))
        self._settings_cb.setStyleSheet(f"color: {design.text};")
        self._settings_cb.setChecked(settings_visible)
        self._settings_cb.toggled.connect(self.settings_panel_toggled.emit)
        _pgc.addWidget(self._settings_cb)

        self._ticket_cb = QCheckBox("チケットパネルを表示 (F4)")
        self._ticket_cb.setFont(QFont("Meiryo", 9))
        self._ticket_cb.setStyleSheet(f"color: {design.text};")
        self._ticket_cb.setChecked(ticket_visible)
        self._ticket_cb.toggled.connect(self.ticket_panel_toggled.emit)
        _pgc.addWidget(self._ticket_cb)

        self._seq_cb = QCheckBox("実行パネルを表示 (F5)")
        self._seq_cb.setFont(QFont("Meiryo", 9))
        self._seq_cb.setStyleSheet(f"color: {design.text};")
        self._seq_cb.setChecked(seq_visible)
        self._seq_cb.toggled.connect(self.seq_panel_toggled.emit)
        _pgc.addWidget(self._seq_cb)

        self._link_cb = QCheckBox("連携パネルを表示 (F6)")
        self._link_cb.setFont(QFont("Meiryo", 9))
        self._link_cb.setStyleSheet(f"color: {design.text};")
        self._link_cb.setChecked(link_visible)
        self._link_cb.toggled.connect(self.link_panel_toggled.emit)
        _pgc.addWidget(self._link_cb)

        _pgc.addSpacing(4)

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
        _pgc.addWidget(self._reset_btn)

        self._panel_grp_content.setVisible(True)
        body_layout.addWidget(self._panel_grp_content)

        # ── Group 2: ルーレット管理（初期: 開く） ──────────────────
        _roulette_grp_hdr = QHBoxLayout()
        _roulette_grp_hdr.setContentsMargins(0, 0, 0, 0)
        _roulette_grp_hdr.setSpacing(2)

        self._roulette_grp_btn = QPushButton("▼ ルーレット管理")
        self._roulette_grp_btn.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._roulette_grp_btn.setCheckable(True)
        self._roulette_grp_btn.setChecked(True)
        self._roulette_grp_btn.setStyleSheet(_grp_toggle_style)
        self._roulette_grp_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._roulette_grp_btn.toggled.connect(self._on_roulette_grp_toggle)
        _roulette_grp_hdr.addWidget(self._roulette_grp_btn, stretch=1)

        _pkg_icon_style = (
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text};"
            f"  border: none; padding: 1px 4px;"
            f"  font-size: 10pt; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ color: {design.accent}; }}"
        )
        self._pkg_export_btn = QPushButton("↑")
        self._pkg_export_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._pkg_export_btn.setStyleSheet(_pkg_icon_style)
        self._pkg_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pkg_export_btn.setToolTip(
            "active ルーレットを書き出す\n（他者共有・移行用）"
        )
        self._pkg_export_btn.clicked.connect(self.roulette_pkg_export_requested.emit)
        _roulette_grp_hdr.addWidget(self._pkg_export_btn)

        self._pkg_import_btn = QPushButton("↓")
        self._pkg_import_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._pkg_import_btn.setStyleSheet(_pkg_icon_style)
        self._pkg_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pkg_import_btn.setToolTip(
            "ルーレットを読み込む\n（ファイルから新規追加）"
        )
        self._pkg_import_btn.clicked.connect(self.roulette_pkg_import_requested.emit)
        _roulette_grp_hdr.addWidget(self._pkg_import_btn)

        body_layout.addLayout(_roulette_grp_hdr)

        self._roulette_grp_content = QWidget(body)  # i068: 親なし HWND フラッシュ防止
        _rgc = QVBoxLayout(self._roulette_grp_content)
        _rgc.setContentsMargins(0, 4, 0, 4)
        _rgc.setSpacing(4)

        # ルーレット一覧（動的に更新）
        self._roulette_list_layout = QVBoxLayout()
        self._roulette_list_layout.setSpacing(4)
        self._roulette_list_layout.setContentsMargins(0, 0, 0, 0)
        _rgc.addLayout(self._roulette_list_layout)
        self._roulette_rows: dict[str, QWidget] = {}

        # 追加ボタン
        self._add_roulette_btn = QPushButton("+ ルーレットを追加")
        self._add_roulette_btn.setFont(QFont("Meiryo", 9))
        self._add_roulette_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_roulette_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 4px; padding: 5px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._add_roulette_btn.clicked.connect(self.roulette_add_requested.emit)
        _rgc.addWidget(self._add_roulette_btn)

        self._roulette_grp_content.setVisible(True)
        body_layout.addWidget(self._roulette_grp_content)

        # v0.6.1: 「設定適用」グループは削除し、「全ルーレットに適用」CB は
        # 設定パネルのクイック設定バーへ移動した。

        body_layout.addSpacing(8)

        # i463/i464: ルーレット以外非表示時の個別表示設定（折りたたみ式）
        # セクションヘッダ（トグルボタン）
        self._ro_only_toggle_btn = QPushButton("▶ ルーレット以外非表示時")
        self._ro_only_toggle_btn.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._ro_only_toggle_btn.setCheckable(True)
        self._ro_only_toggle_btn.setChecked(False)  # デフォルト: 折りたたみ
        self._ro_only_toggle_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text};"
            f"  border: none; text-align: left; padding: 2px 0px;"
            f"}}"
            f"QPushButton:hover {{ color: {design.accent}; }}"
        )
        self._ro_only_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ro_only_toggle_btn.toggled.connect(self._on_ro_only_toggle)
        # v0.6.1: トグルボタンの右に「初期化」ボタンを配置するため HBox でラップ
        self._add_grp_header_with_reset(
            body_layout, self._ro_only_toggle_btn,
            self.ro_only_reset_requested.emit, design,
        )

        # 折りたたみコンテンツ — パネル群 / ルーレットパネル群の2グループ
        self._ro_only_content = QWidget(body)  # i068: 親なし HWND フラッシュ防止
        _ro_content_layout = QVBoxLayout(self._ro_only_content)
        _ro_content_layout.setContentsMargins(8, 2, 0, 2)
        _ro_content_layout.setSpacing(3)

        _cb_style = f"color: {design.text};"

        # i034: サブグループ折りたたみトグルボタン共通スタイル
        _sub_toggle_style = (
            f"QPushButton {{ background-color: transparent; color: {design.text_sub};"
            f"  border: none; text-align: left; padding: 1px 0px; font-size: 8pt; }}"
            f"QPushButton:hover {{ color: {design.text}; }}"
        )

        def _make_cb(text, checked, key, tooltip):
            cb = QCheckBox(text)
            cb.setFont(QFont("Meiryo", 9))
            cb.setStyleSheet(_cb_style)
            cb.setChecked(checked)
            cb.setToolTip(tooltip)
            # i034: TAB フォーカス対象外にして _TabRouletteFilter が確実に捕捉できるようにする
            cb.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            cb.toggled.connect(lambda v, k=key: self.roulette_only_hide_changed.emit(k, v))
            return cb

        # ── パネル グループ（折りたたみ可能） ────────────────────
        self._ro_panels_toggle_btn = QPushButton("▶ パネル")
        self._ro_panels_toggle_btn.setFont(QFont("Meiryo", 8))
        self._ro_panels_toggle_btn.setCheckable(True)
        self._ro_panels_toggle_btn.setChecked(False)
        self._ro_panels_toggle_btn.setStyleSheet(_sub_toggle_style)
        self._ro_panels_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ro_panels_toggle_btn.toggled.connect(self._on_ro_panels_toggle)
        _ro_content_layout.addWidget(self._ro_panels_toggle_btn)

        self._ro_panels_content = QWidget(body)  # i068: 親なし HWND フラッシュ防止
        _ro_panels_layout = QVBoxLayout(self._ro_panels_content)
        _ro_panels_layout.setContentsMargins(12, 0, 0, 2)
        _ro_panels_layout.setSpacing(2)

        self._ro_show_manage_panel_cb = _make_cb(
            "管理パネル", roulette_only_show_manage_panel, "manage_panel",
            "ONにすると、ルーレット以外非表示中も管理パネルを表示します"
        )
        _ro_panels_layout.addWidget(self._ro_show_manage_panel_cb)

        self._ro_show_items_panel_cb = _make_cb(
            "項目パネル", roulette_only_show_items_panel, "items_panel",
            "ONにすると、ルーレット以外非表示中も項目パネルを表示します"
        )
        _ro_panels_layout.addWidget(self._ro_show_items_panel_cb)

        self._ro_show_settings_panel_cb = _make_cb(
            "設定パネル", roulette_only_show_settings_panel, "settings_panel",
            "ONにすると、ルーレット以外非表示中も設定パネルを表示します"
        )
        _ro_panels_layout.addWidget(self._ro_show_settings_panel_cb)

        self._ro_show_execution_panel_cb = _make_cb(
            "実行パネル（連続抽選）", roulette_only_show_execution_panel, "execution_panel",
            "ONにすると、ルーレット以外非表示中も被りなし連続抽選パネルを表示します"
        )
        _ro_panels_layout.addWidget(self._ro_show_execution_panel_cb)

        self._ro_show_ticket_panel_cb = _make_cb(
            "チケットパネル", roulette_only_show_ticket_panel, "ticket_panel",
            "ONにすると、ルーレット以外非表示中もチケットパネルを表示します"
        )
        _ro_panels_layout.addWidget(self._ro_show_ticket_panel_cb)

        self._ro_show_link_panel_cb = _make_cb(
            "連携パネル", roulette_only_show_link_panel, "link_panel",
            "ONにすると、ルーレット以外非表示中も連携パネルを表示します"
        )
        _ro_panels_layout.addWidget(self._ro_show_link_panel_cb)

        self._ro_panels_content.setVisible(False)  # デフォルト折りたたみ
        _ro_content_layout.addWidget(self._ro_panels_content)

        # ── ルーレットパネル グループ（折りたたみ可能） ──────────
        self._ro_rp_toggle_btn = QPushButton("▶ ルーレットパネル")
        self._ro_rp_toggle_btn.setFont(QFont("Meiryo", 8))
        self._ro_rp_toggle_btn.setCheckable(True)
        self._ro_rp_toggle_btn.setChecked(False)
        self._ro_rp_toggle_btn.setStyleSheet(_sub_toggle_style)
        self._ro_rp_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ro_rp_toggle_btn.toggled.connect(self._on_ro_rp_toggle)
        _ro_content_layout.addWidget(self._ro_rp_toggle_btn)

        self._ro_rp_content = QWidget(body)  # i068: 親なし HWND フラッシュ防止
        _ro_rp_layout = QVBoxLayout(self._ro_rp_content)
        _ro_rp_layout.setContentsMargins(12, 0, 0, 2)
        _ro_rp_layout.setSpacing(2)

        self._ro_show_selection_handle_cb = _make_cb(
            "選択つまみ", roulette_only_show_selection_handle, "selection_handle",
            "ONにすると、ルーレット以外非表示中も左上の選択つまみを表示します"
        )
        _ro_rp_layout.addWidget(self._ro_show_selection_handle_cb)

        self._ro_show_title_plate_cb = _make_cb(
            "タイトル", roulette_only_show_title_plate, "title_plate",
            "ONにすると、ルーレット以外非表示中もタイトルを表示します"
        )
        _ro_rp_layout.addWidget(self._ro_show_title_plate_cb)

        self._ro_show_graph_btn_cb = _make_cb(
            "グラフ", roulette_only_show_graph_btn, "graph_btn",
            "ONにすると、ルーレット以外非表示中もグラフボタンを表示します"
        )
        _ro_rp_layout.addWidget(self._ro_show_graph_btn_cb)

        self._ro_show_grip_cb = _make_cb(
            "リサイズグリップ", roulette_only_show_grip, "grip",
            "ONにすると、ルーレット以外非表示中もリサイズグリップを表示します"
        )
        _ro_rp_layout.addWidget(self._ro_show_grip_cb)

        self._ro_show_log_cb = _make_cb(
            "ログ", roulette_only_show_log, "log",
            "ONにすると、ルーレット以外非表示中もログオーバーレイを表示します"
        )
        _ro_rp_layout.addWidget(self._ro_show_log_cb)

        self._ro_rp_content.setVisible(False)  # デフォルト折りたたみ
        _ro_content_layout.addWidget(self._ro_rp_content)

        self._ro_only_content.setVisible(False)  # デフォルト折りたたみ
        body_layout.addWidget(self._ro_only_content)

        # i485: アプリ設定セクション（折りたたみ式）
        self._app_settings_toggle_btn = QPushButton("▶ アプリ設定")
        self._app_settings_toggle_btn.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._app_settings_toggle_btn.setCheckable(True)
        self._app_settings_toggle_btn.setChecked(False)
        self._app_settings_toggle_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text};"
            f"  border: none; text-align: left; padding: 2px 0px;"
            f"}}"
            f"QPushButton:hover {{ color: {design.accent}; }}"
        )
        self._app_settings_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._app_settings_toggle_btn.toggled.connect(self._on_app_settings_toggle)
        # v0.6.1: トグルボタンの右に「初期化」ボタンを配置
        self._add_grp_header_with_reset(
            body_layout, self._app_settings_toggle_btn,
            self.app_settings_reset_requested.emit, design,
        )

        self._app_settings_content = QWidget(body)  # i068: 親なし HWND フラッシュ防止
        _app_content_layout = QVBoxLayout(self._app_settings_content)
        _app_content_layout.setContentsMargins(12, 2, 0, 2)
        _app_content_layout.setSpacing(6)

        # v0.6.1: 設定パネルから移動した項目（透過/テーマ/動作/音量/リプレイ）
        # を「アプリ設定」グループの先頭に統合配置
        self._build_app_settings_group_content(_app_content_layout, design)

        # ── サブグループ 5: 自動全面非表示 ─────────────────────────
        _auto_hide_layout = self._app_make_subgroup(
            "自動全面非表示", "auto_hide", expanded=False
        )
        # Esc キー案内ラベル
        _esc_hint = QLabel("Esc キー: 全面非表示")
        _esc_hint.setFont(QFont("Meiryo", 8))
        _esc_hint.setStyleSheet(f"color: {design.text_sub};")
        _esc_hint.setToolTip("Esc キーを押すと RRoulette 全体を非表示にします\nタスクバーや Alt+Tab で再表示されます")
        _auto_hide_layout.addWidget(_esc_hint)

        # 自動全面非表示チェックボックス
        self._auto_hide_cb = QCheckBox("自動全面非表示")
        self._auto_hide_cb.setFont(QFont("Meiryo", 9))
        self._auto_hide_cb.setStyleSheet(f"color: {design.text};")
        self._auto_hide_cb.setChecked(auto_hide_enabled)
        self._auto_hide_cb.setToolTip("ON: 無操作が続くと自動で全面非表示にします")
        self._auto_hide_cb.toggled.connect(self.auto_hide_enabled_changed.emit)
        _auto_hide_layout.addWidget(self._auto_hide_cb)

        # 秒数設定行
        _sec_row = QHBoxLayout()
        _sec_row.setContentsMargins(0, 0, 0, 0)
        _sec_row.setSpacing(6)
        _sec_lbl = QLabel("非表示まで")
        _sec_lbl.setFont(QFont("Meiryo", 9))
        _sec_lbl.setStyleSheet(f"color: {design.text};")
        _sec_row.addWidget(_sec_lbl)

        self._auto_hide_spin = NoWheelSpinBox()
        self._auto_hide_spin.setFont(QFont("Meiryo", 9))
        self._auto_hide_spin.setRange(1, 300)
        self._auto_hide_spin.setValue(max(1, auto_hide_seconds))
        self._auto_hide_spin.setSuffix(" 秒")
        self._auto_hide_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 60px;"
            f"}}"
        )
        self._auto_hide_spin.setToolTip("無操作の経過秒数で全面非表示にします (1〜300秒)")
        self._auto_hide_spin.valueChanged.connect(self.auto_hide_seconds_changed.emit)
        _sec_row.addWidget(self._auto_hide_spin)
        _sec_row.addStretch()
        _auto_hide_layout.addLayout(_sec_row)

        # フェードアウト ON/OFF チェックボックス (i486)
        self._auto_hide_fade_cb = QCheckBox("自動非表示時にフェードアウト")
        self._auto_hide_fade_cb.setFont(QFont("Meiryo", 9))
        self._auto_hide_fade_cb.setStyleSheet(f"color: {design.text};")
        self._auto_hide_fade_cb.setChecked(auto_hide_fade_enabled)
        self._auto_hide_fade_cb.setToolTip("ON: 自動全面非表示時にゆっくりフェードアウトします")
        self._auto_hide_fade_cb.toggled.connect(self._on_fade_cb_toggled)
        _auto_hide_layout.addWidget(self._auto_hide_fade_cb)

        # フェード時間スピンボックス (i487)
        _fade_sec_row = QHBoxLayout()
        _fade_sec_row.setContentsMargins(12, 0, 0, 0)
        _fade_sec_row.setSpacing(6)
        _fade_sec_lbl = QLabel("フェード時間")
        _fade_sec_lbl.setFont(QFont("Meiryo", 9))
        _fade_sec_lbl.setStyleSheet(f"color: {design.text};")
        _fade_sec_row.addWidget(_fade_sec_lbl)

        self._auto_hide_fade_spin = NoWheelDoubleSpinBox()
        self._auto_hide_fade_spin.setFont(QFont("Meiryo", 9))
        self._auto_hide_fade_spin.setRange(0.1, 10.0)
        self._auto_hide_fade_spin.setSingleStep(0.1)
        self._auto_hide_fade_spin.setDecimals(1)
        _fade_sec = max(0.1, min(10.0, auto_hide_fade_seconds))
        self._auto_hide_fade_spin.setValue(_fade_sec)
        self._auto_hide_fade_spin.setSuffix(" 秒")
        self._auto_hide_fade_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 65px;"
            f"}}"
        )
        self._auto_hide_fade_spin.setToolTip("フェードアウトにかける時間 (0.1〜10.0秒)")
        self._auto_hide_fade_spin.setEnabled(auto_hide_fade_enabled)
        self._auto_hide_fade_spin.valueChanged.connect(self.auto_hide_fade_seconds_changed.emit)
        _fade_sec_row.addWidget(self._auto_hide_fade_spin)
        _fade_sec_row.addStretch()
        _auto_hide_layout.addLayout(_fade_sec_row)

        # ルーレット以外非表示時のみ有効 (i098)
        self._auto_hide_roulette_only_cb = QCheckBox("ルーレット以外非表示時のみ有効")
        self._auto_hide_roulette_only_cb.setFont(QFont("Meiryo", 9))
        self._auto_hide_roulette_only_cb.setStyleSheet(f"color: {design.text};")
        self._auto_hide_roulette_only_cb.setChecked(auto_hide_only_in_roulette_only_mode)
        self._auto_hide_roulette_only_cb.setToolTip(
            "ON: ルーレット以外非表示モード中のみ自動全面非表示を有効にします\n"
            "OFF: 通常状態でも自動全面非表示を有効にします"
        )
        self._auto_hide_roulette_only_cb.toggled.connect(
            self.auto_hide_only_roulette_only_changed.emit
        )
        _auto_hide_layout.addWidget(self._auto_hide_roulette_only_cb)

        # 再表示後、次にルーレットを回した後に有効 (i098)
        self._auto_hide_after_spin_restore_cb = QCheckBox("再表示後、次のスピン後に有効")
        self._auto_hide_after_spin_restore_cb.setFont(QFont("Meiryo", 9))
        self._auto_hide_after_spin_restore_cb.setStyleSheet(f"color: {design.text};")
        self._auto_hide_after_spin_restore_cb.setChecked(auto_hide_after_spin_after_restore)
        self._auto_hide_after_spin_restore_cb.setToolTip(
            "ON: 全面非表示から復帰した直後は自動非表示カウントを無効にします\n"
            "    次にスピンを開始したら自動非表示カウントを再度有効にします\n"
            "OFF: 復帰後もすぐに自動非表示カウントを開始します"
        )
        self._auto_hide_after_spin_restore_cb.toggled.connect(
            self.auto_hide_after_spin_restore_changed.emit
        )
        _auto_hide_layout.addWidget(self._auto_hide_after_spin_restore_cb)

        # ── サブグループ 6: 外部連携 (アプリ設定の最後に配置) ─────────
        # 既存の独立「外部連携設定」グループを CollapsibleSection サブグループに移動
        _lic_layout = self._app_make_subgroup("外部連携", "link", expanded=False)

        # 有効/無効
        self._link_int_enabled_cb = QCheckBox("連携受信を有効にする (RCommentHub)")
        self._link_int_enabled_cb.setFont(QFont("Meiryo", 9))
        self._link_int_enabled_cb.setStyleSheet(f"color: {design.text};")
        self._link_int_enabled_cb.setChecked(link_integration_enabled)
        self._link_int_enabled_cb.setToolTip(
            "RCommentHub からのフィルタ一致通知を受信する。\n変更後は即時反映されます。"
        )
        self._link_int_enabled_cb.toggled.connect(self.link_enabled_changed.emit)
        _lic_layout.addWidget(self._link_int_enabled_cb)

        # ポート
        _port_row = QHBoxLayout()
        _port_row.setSpacing(4)
        _port_lbl = QLabel("受信ポート:")
        _port_lbl.setFont(QFont("Meiryo", 9))
        _port_lbl.setStyleSheet(f"color: {design.text_sub};")
        _port_row.addWidget(_port_lbl)
        self._link_int_port_spin = NoWheelSpinBox()
        self._link_int_port_spin.setFont(QFont("Meiryo", 9))
        self._link_int_port_spin.setRange(1024, 65535)
        self._link_int_port_spin.setValue(link_integration_port)
        self._link_int_port_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"}}"
        )
        self._link_int_port_spin.setToolTip("RCommentHub側と同じポートにすること。変更後は即時反映。")
        self._link_int_port_spin.valueChanged.connect(self.link_port_changed.emit)
        _port_row.addWidget(self._link_int_port_spin)
        _port_row.addStretch()
        _lic_layout.addLayout(_port_row)

        # 保持件数
        _hold_row = QHBoxLayout()
        _hold_row.setSpacing(4)
        _hold_lbl = QLabel("保持件数上限:")
        _hold_lbl.setFont(QFont("Meiryo", 9))
        _hold_lbl.setStyleSheet(f"color: {design.text_sub};")
        _hold_row.addWidget(_hold_lbl)
        self._link_int_max_hold_spin = NoWheelSpinBox()
        self._link_int_max_hold_spin.setFont(QFont("Meiryo", 9))
        self._link_int_max_hold_spin.setRange(1, 1000)
        self._link_int_max_hold_spin.setValue(link_integration_max_hold)
        self._link_int_max_hold_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"}}"
        )
        self._link_int_max_hold_spin.valueChanged.connect(self.link_max_hold_changed.emit)
        _hold_row.addWidget(self._link_int_max_hold_spin)
        _hold_row.addStretch()
        _lic_layout.addLayout(_hold_row)

        # 時刻列表示
        self._link_int_show_time_cb = QCheckBox("連携パネルに時刻を表示")
        self._link_int_show_time_cb.setFont(QFont("Meiryo", 9))
        self._link_int_show_time_cb.setStyleSheet(f"color: {design.text};")
        self._link_int_show_time_cb.setChecked(link_panel_show_time)
        self._link_int_show_time_cb.setToolTip("連携パネルの時刻列の表示/非表示を切り替えます。")
        self._link_int_show_time_cb.toggled.connect(self.link_show_time_changed.emit)
        _lic_layout.addWidget(self._link_int_show_time_cb)

        # 状態表示
        self._link_int_status_lbl = QLabel("状態: 停止中")
        self._link_int_status_lbl.setFont(QFont("Meiryo", 9))
        self._link_int_status_lbl.setStyleSheet(f"color: {design.text_sub};")
        _lic_layout.addWidget(self._link_int_status_lbl)

        # v0.6.1: 「アプリ設定」全体の表示制御
        self._app_settings_content.setVisible(False)
        body_layout.addWidget(self._app_settings_content)

        body_layout.addSpacing(4)

        # i467: バージョン表示（管理パネル下部）
        _ver_lbl = QLabel(f"RRoulette  v{APP_VERSION}")
        _ver_lbl.setFont(QFont("Meiryo", 8))
        _ver_lbl.setStyleSheet(f"color: {design.text_sub};")
        _ver_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        body_layout.addWidget(_ver_lbl)

        # i462: 高さ変更時に項目間が伸びないよう末尾にストレッチを追加する
        body_layout.addStretch(1)

        body.setStyleSheet(f"background-color: {design.panel};")

        # i348: コンテンツをスクロール領域で包む（高さ不足でも潰れない）
        self._scroll = QScrollArea(self)  # i068: 親なし HWND フラッシュ防止
        self._scroll.setWidget(body)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(f"background-color: {design.panel};")
        outer.addWidget(self._scroll, stretch=1)

        self._transparent = False
        self.setStyleSheet(f"background-color: {design.panel};")
        self.setMinimumSize(240, 280)

    # ----------------------------------------------------------------
    #  公開 API
    # ----------------------------------------------------------------

    def set_items_visible(self, visible: bool):
        """項目パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._items_cb.blockSignals(True)
        self._items_cb.setChecked(visible)
        self._items_cb.blockSignals(False)

    def _on_panel_grp_toggle(self, expanded: bool):
        """パネル管理グループの展開/折りたたみ。"""
        self._panel_grp_content.setVisible(expanded)
        self._panel_grp_btn.setText("▼ パネル管理" if expanded else "▶ パネル管理")

    def _on_roulette_grp_toggle(self, expanded: bool):
        """ルーレット管理グループの展開/折りたたみ。"""
        self._roulette_grp_content.setVisible(expanded)
        self._roulette_grp_btn.setText("▼ ルーレット管理" if expanded else "▶ ルーレット管理")

    # v0.6.1: _on_apply_grp_toggle / set_apply_to_all は廃止
    # 「全ルーレットに適用」CB は設定パネル側へ移動

    # =====================================================================
    #  v0.6.1: 設定パネルから移動したアプリ全体設定グループ
    # =====================================================================

    def _add_grp_header_with_reset(self, parent_layout, toggle_btn,
                                     on_reset_callable, design):
        """v0.6.1: グループのトグルボタン (QPushButton) を HBox でラップして
        右側に「初期化」ボタンを配置する共通ヘルパー。

        background が透明な QFrame でラップして親パネルの背景色を維持する。
        """
        wrapper = QFrame()
        wrapper.setStyleSheet("QFrame { background: transparent; }")
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(toggle_btn, stretch=1)

        reset_btn = QPushButton("初期化")
        reset_btn.setFont(QFont("Meiryo", 7))
        reset_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text_sub};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 6px; font-family: Meiryo; font-size: 7pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: #c0392b; color: white; border-color: #c0392b;"
            f"}}"
        )
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setToolTip("このグループの設定を新規ルーレット作成時の状態に戻す")
        reset_btn.clicked.connect(lambda _chk=False: on_reset_callable())
        row.addWidget(reset_btn)

        parent_layout.addWidget(wrapper)

    def _build_app_settings_group_content(self, parent_layout, design):
        """v0.6.1: 既存の「アプリ設定」グループ（i485）の content_layout に
        透過/最前面/テーマ/動作/音量/リプレイ系のウィジェットを追加する。

        独自グループは作らず、既存グループへ統合する形。
        """
        s = self._settings  # AppSettings (None の可能性あり)

        def _g(key, default):
            return getattr(s, key, default) if s is not None else default

        cb_style = f"color: {design.text};"
        lbl_style = f"color: {design.text_sub};"
        combo_style = (
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 16px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )
        spin_style = (
            f"QSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        slider_style = (
            f"QSlider::groove:horizontal {{"
            f"  background: {design.separator}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {design.accent}; width: 12px; margin: -4px 0;"
            f"  border-radius: 6px;"
            f"}}"
        )

        emit = lambda k, v: self.app_setting_changed.emit(k, v)
        theme_mode_init = _g("theme_mode", "dark")

        def _make_subgroup(title: str, sub_key: str, expanded: bool = False):
            """サブグループの CollapsibleSection を作成し、ヘッダー右に
            「初期化」ボタンを配置して content_layout を返す。"""
            sec = CollapsibleSection(title, design, expanded=expanded,
                                      theme_mode=theme_mode_init, nested=True)
            rb = QPushButton("初期化")
            rb.setFont(QFont("Meiryo", 7))
            rb.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: transparent; color: {design.text_sub};"
                f"  border: 1px solid {design.separator}; border-radius: 3px;"
                f"  padding: 1px 6px; font-family: Meiryo; font-size: 7pt;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: #c0392b; color: white; border-color: #c0392b;"
                f"}}"
            )
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            rb.setToolTip(f"「{title}」を新規ルーレット作成時の状態に戻す")
            rb.clicked.connect(
                lambda _chk=False, k=sub_key: self.app_subgroup_reset_requested.emit(k)
            )
            sec.add_header_widget(rb)
            parent_layout.addWidget(sec)
            return sec.content_layout

        # === サブグループ 1: ウィンドウ表示 ===
        win_layout = _make_subgroup("ウィンドウ表示", "window_display", expanded=False)

        self._mp_window_transparent_cb = QCheckBox("メインウィンドウ透過")
        self._mp_window_transparent_cb.setFont(QFont("Meiryo", 8))
        self._mp_window_transparent_cb.setStyleSheet(cb_style)
        self._mp_window_transparent_cb.setChecked(_g("window_transparent", False))
        self._mp_window_transparent_cb.toggled.connect(
            lambda v: emit("window_transparent", v)
        )
        win_layout.addWidget(self._mp_window_transparent_cb)

        self._mp_roulette_transparent_cb = QCheckBox("ルーレット透過")
        self._mp_roulette_transparent_cb.setFont(QFont("Meiryo", 8))
        self._mp_roulette_transparent_cb.setStyleSheet(cb_style)
        self._mp_roulette_transparent_cb.setChecked(_g("roulette_transparent", False))
        self._mp_roulette_transparent_cb.toggled.connect(
            lambda v: emit("roulette_transparent", v)
        )
        win_layout.addWidget(self._mp_roulette_transparent_cb)

        self._mp_panels_transparent_cb = QCheckBox("パネル透過(試験)")
        self._mp_panels_transparent_cb.setFont(QFont("Meiryo", 8))
        self._mp_panels_transparent_cb.setStyleSheet(cb_style)
        self._mp_panels_transparent_cb.setChecked(_g("panels_transparent", False))
        self._mp_panels_transparent_cb.toggled.connect(
            lambda v: emit("panels_transparent", v)
        )
        win_layout.addWidget(self._mp_panels_transparent_cb)

        self._mp_aot_cb = QCheckBox("常に最前面")
        self._mp_aot_cb.setFont(QFont("Meiryo", 8))
        self._mp_aot_cb.setStyleSheet(cb_style)
        self._mp_aot_cb.setChecked(_g("always_on_top", False))
        self._mp_aot_cb.toggled.connect(lambda v: emit("always_on_top", v))
        win_layout.addWidget(self._mp_aot_cb)

        # === サブグループ 2: OCR ===
        ocr_layout = _make_subgroup("OCR", "ocr", expanded=False)
        ocr_row = QHBoxLayout()
        ocr_row.setSpacing(4)
        ocr_lbl = QLabel("キャプチャ:")
        ocr_lbl.setFont(QFont("Meiryo", 8))
        ocr_lbl.setStyleSheet(lbl_style)
        ocr_row.addWidget(ocr_lbl)
        self._mp_ocr_capture_combo = NoWheelComboBox()
        self._mp_ocr_capture_combo.setFont(QFont("Meiryo", 8))
        self._mp_ocr_capture_combo.setStyleSheet(combo_style)
        self._mp_ocr_capture_combo.addItems(["標準", "Windows GDI"])
        _ocr_values = ["qt", "gdi"]
        _ocr_current = _g("ocr_capture_method", "qt")
        self._mp_ocr_capture_combo.setCurrentIndex(
            _ocr_values.index(_ocr_current) if _ocr_current in _ocr_values else 0
        )
        self._mp_ocr_capture_combo.currentIndexChanged.connect(
            lambda i: emit("ocr_capture_method", _ocr_values[i] if i < len(_ocr_values) else "qt")
        )
        ocr_row.addWidget(self._mp_ocr_capture_combo, stretch=1)
        ocr_layout.addLayout(ocr_row)

        # === サブグループ 3: テーマ・動作 ===
        theme_layout = _make_subgroup("テーマ・動作", "theme_action", expanded=False)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(4)
        theme_lbl = QLabel("テーマ:")
        theme_lbl.setFont(QFont("Meiryo", 8))
        theme_lbl.setStyleSheet(lbl_style)
        theme_row.addWidget(theme_lbl)
        self._mp_theme_combo = NoWheelComboBox()
        self._mp_theme_combo.setFont(QFont("Meiryo", 8))
        self._mp_theme_combo.setStyleSheet(combo_style)
        self._mp_theme_combo.addItems(["ダーク", "ライト", "システム"])
        _theme_idx = {"dark": 0, "light": 1, "system": 2, "auto": 2}
        self._mp_theme_combo.setCurrentIndex(_theme_idx.get(_g("theme_mode", "dark"), 0))
        _theme_val = ["dark", "light", "system"]
        self._mp_theme_combo.currentIndexChanged.connect(
            lambda i: emit("theme_mode", _theme_val[i] if i < len(_theme_val) else "dark")
        )
        theme_row.addWidget(self._mp_theme_combo, stretch=1)
        theme_layout.addLayout(theme_row)

        self._mp_confirm_item_delete_cb = QCheckBox("項目削除時に確認する")
        self._mp_confirm_item_delete_cb.setFont(QFont("Meiryo", 8))
        self._mp_confirm_item_delete_cb.setStyleSheet(cb_style)
        self._mp_confirm_item_delete_cb.setChecked(_g("confirm_item_delete", True))
        self._mp_confirm_item_delete_cb.toggled.connect(
            lambda v: emit("confirm_item_delete", v)
        )
        theme_layout.addWidget(self._mp_confirm_item_delete_cb)

        self._mp_instance_label_cb = QCheckBox("インスタンス番号表示")
        self._mp_instance_label_cb.setFont(QFont("Meiryo", 8))
        self._mp_instance_label_cb.setStyleSheet(cb_style)
        self._mp_instance_label_cb.setChecked(_g("float_win_show_instance", False))
        self._mp_instance_label_cb.toggled.connect(
            lambda v: emit("float_win_show_instance", v)
        )
        theme_layout.addWidget(self._mp_instance_label_cb)

        self._mp_confirm_reset_cb = QCheckBox("リセット確認")
        self._mp_confirm_reset_cb.setFont(QFont("Meiryo", 8))
        self._mp_confirm_reset_cb.setStyleSheet(cb_style)
        self._mp_confirm_reset_cb.setChecked(_g("confirm_reset", True))
        self._mp_confirm_reset_cb.toggled.connect(
            lambda v: emit("confirm_reset", v)
        )
        theme_layout.addWidget(self._mp_confirm_reset_cb)

        # === サブグループ 3: 音量 ===
        vol_layout = _make_subgroup("音量", "volume", expanded=False)

        def _make_vol_row(label_text, key, init_val, parent):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setFont(QFont("Meiryo", 8))
            lbl.setStyleSheet(lbl_style)
            lbl.setFixedWidth(72)
            row.addWidget(lbl)
            sl = NoWheelSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(int(init_val))
            sl.setStyleSheet(slider_style)
            sl.valueChanged.connect(lambda v, k=key: emit(k, v))
            row.addWidget(sl, stretch=1)
            val_lbl = QLabel(f"{int(init_val)}%")
            val_lbl.setFont(QFont("Meiryo", 7))
            val_lbl.setStyleSheet(lbl_style)
            val_lbl.setFixedWidth(32)
            sl.valueChanged.connect(lambda v: val_lbl.setText(f"{v}%"))
            row.addWidget(val_lbl)
            parent.addLayout(row)
            return sl, val_lbl

        self._mp_tick_vol_slider, self._mp_tick_vol_val = _make_vol_row(
            "スピン音量:", "tick_volume", _g("tick_volume", 50), vol_layout,
        )
        self._mp_win_vol_slider, self._mp_win_vol_val = _make_vol_row(
            "決定音量:", "win_volume", _g("win_volume", 50), vol_layout,
        )
        self._mp_effect_vol_slider, self._mp_effect_vol_val = _make_vol_row(
            "演出音量:", "effect_volume", _g("effect_volume", 50), vol_layout,
        )

        # === サブグループ 4: リプレイ ===
        replay_layout = _make_subgroup("リプレイ", "replay", expanded=False)

        max_row = QHBoxLayout()
        max_row.setSpacing(4)
        max_lbl = QLabel("保存上限:")
        max_lbl.setFont(QFont("Meiryo", 8))
        max_lbl.setStyleSheet(lbl_style)
        max_row.addWidget(max_lbl)
        self._mp_replay_max_spin = NoWheelSpinBox()
        self._mp_replay_max_spin.setFont(QFont("Meiryo", 8))
        self._mp_replay_max_spin.setRange(1, 20)
        self._mp_replay_max_spin.setValue(int(_g("replay_max_count", 10)))
        self._mp_replay_max_spin.setStyleSheet(spin_style)
        self._mp_replay_max_spin.valueChanged.connect(
            lambda v: emit("replay_max_count", v)
        )
        max_row.addWidget(self._mp_replay_max_spin)
        max_row.addStretch(1)
        replay_layout.addLayout(max_row)

        self._mp_replay_indicator_cb = QCheckBox("再生中表示")
        self._mp_replay_indicator_cb.setFont(QFont("Meiryo", 8))
        self._mp_replay_indicator_cb.setStyleSheet(cb_style)
        self._mp_replay_indicator_cb.setChecked(_g("replay_show_indicator", True))
        self._mp_replay_indicator_cb.toggled.connect(
            lambda v: emit("replay_show_indicator", v)
        )
        replay_layout.addWidget(self._mp_replay_indicator_cb)

        self._mp_replay_record_effects_cb = QCheckBox("特殊演出も再現する")
        self._mp_replay_record_effects_cb.setFont(QFont("Meiryo", 8))
        self._mp_replay_record_effects_cb.setStyleSheet(cb_style)
        self._mp_replay_record_effects_cb.setChecked(_g("replay_record_effects", True))
        self._mp_replay_record_effects_cb.setToolTip(
            "ON: スピン中の特殊演出もリプレイに記録し再生時に再現\n"
            "OFF: 角度フレームのみ再現（演出は発火しない）"
        )
        self._mp_replay_record_effects_cb.toggled.connect(
            lambda v: emit("replay_record_effects", v)
        )
        replay_layout.addWidget(self._mp_replay_record_effects_cb)

        # v0.6.1: 「自動全面非表示」「外部連携」サブグループは __init__ 末尾で
        # 既存ウィジェットを CollapsibleSection に再ペアレントする形で組み込む。
        # ここではサブグループ用 layout を確保するための placeholder 関数を保存。
        self._app_make_subgroup = _make_subgroup
        self._app_settings_parent_layout = parent_layout

    def update_app_setting(self, key: str, value):
        """外部からの設定変更を ManagePanel UI に反映する（シグナルなし）。"""
        widget_map = {
            "window_transparent":   ("_mp_window_transparent_cb", "setChecked"),
            "roulette_transparent": ("_mp_roulette_transparent_cb", "setChecked"),
            "panels_transparent":   ("_mp_panels_transparent_cb", "setChecked"),
            "always_on_top":        ("_mp_aot_cb", "setChecked"),
            "confirm_item_delete":  ("_mp_confirm_item_delete_cb", "setChecked"),
            "float_win_show_instance": ("_mp_instance_label_cb", "setChecked"),
            "confirm_reset":        ("_mp_confirm_reset_cb", "setChecked"),
            "replay_show_indicator": ("_mp_replay_indicator_cb", "setChecked"),
            "replay_record_effects": ("_mp_replay_record_effects_cb", "setChecked"),
        }
        if key in widget_map:
            attr, _ = widget_map[key]
            w = getattr(self, attr, None)
            if w is not None:
                w.blockSignals(True)
                w.setChecked(bool(value))
                w.blockSignals(False)
            return
        if key == "theme_mode":
            _theme_idx = {"dark": 0, "light": 1, "system": 2, "auto": 2}
            self._mp_theme_combo.blockSignals(True)
            self._mp_theme_combo.setCurrentIndex(_theme_idx.get(value, 0))
            self._mp_theme_combo.blockSignals(False)
        elif key == "ocr_capture_method":
            _ocr_idx = {"qt": 0, "gdi": 1}
            self._mp_ocr_capture_combo.blockSignals(True)
            self._mp_ocr_capture_combo.setCurrentIndex(_ocr_idx.get(value, 0))
            self._mp_ocr_capture_combo.blockSignals(False)
        elif key in ("tick_volume", "win_volume", "effect_volume"):
            sl_attr = {
                "tick_volume":   "_mp_tick_vol_slider",
                "win_volume":    "_mp_win_vol_slider",
                "effect_volume": "_mp_effect_vol_slider",
            }[key]
            v_attr = {
                "tick_volume":   "_mp_tick_vol_val",
                "win_volume":    "_mp_win_vol_val",
                "effect_volume": "_mp_effect_vol_val",
            }[key]
            sl = getattr(self, sl_attr, None)
            vl = getattr(self, v_attr, None)
            if sl is not None:
                sl.blockSignals(True)
                sl.setValue(int(value))
                sl.blockSignals(False)
            if vl is not None:
                vl.setText(f"{int(value)}%")
        elif key == "replay_max_count":
            self._mp_replay_max_spin.blockSignals(True)
            self._mp_replay_max_spin.setValue(int(value))
            self._mp_replay_max_spin.blockSignals(False)

    def _on_ro_only_toggle(self, expanded: bool):
        """ルーレット以外非表示時セクションの展開/折りたたみ。"""
        self._ro_only_content.setVisible(expanded)
        self._ro_only_toggle_btn.setText(
            ("▼ ルーレット以外非表示時" if expanded else "▶ ルーレット以外非表示時")
        )

    def _on_ro_panels_toggle(self, expanded: bool):
        """パネルサブグループの展開/折りたたみ（i034）。"""
        self._ro_panels_content.setVisible(expanded)
        self._ro_panels_toggle_btn.setText(
            "▼ パネル" if expanded else "▶ パネル"
        )

    def _on_ro_rp_toggle(self, expanded: bool):
        """ルーレットパネルサブグループの展開/折りたたみ（i034）。"""
        self._ro_rp_content.setVisible(expanded)
        self._ro_rp_toggle_btn.setText(
            "▼ ルーレットパネル" if expanded else "▶ ルーレットパネル"
        )

    def _on_app_settings_toggle(self, expanded: bool):
        """アプリ設定セクションの展開/折りたたみ。"""
        self._app_settings_content.setVisible(expanded)
        self._app_settings_toggle_btn.setText(
            ("▼ アプリ設定" if expanded else "▶ アプリ設定")
        )

    def _on_link_int_toggle(self, expanded: bool):
        """v0.6.1: 「外部連携」はアプリ設定内サブグループへ移動済み。
        後方互換のための no-op。"""
        pass

    def _on_fade_cb_toggled(self, enabled: bool):
        """フェードアウト ON/OFF — シグナル発火 + スピンボックス有効/無効切替。"""
        self._auto_hide_fade_spin.setEnabled(enabled)
        self.auto_hide_fade_changed.emit(enabled)

    def set_settings_visible(self, visible: bool):
        """設定パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._settings_cb.blockSignals(True)
        self._settings_cb.setChecked(visible)
        self._settings_cb.blockSignals(False)

    def set_ticket_visible(self, visible: bool):
        """チケットパネルチェック状態を外部から同期する (シグナルなし)。"""
        self._ticket_cb.blockSignals(True)
        self._ticket_cb.setChecked(visible)
        self._ticket_cb.blockSignals(False)

    def set_link_visible(self, visible: bool):
        """連携パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._link_cb.blockSignals(True)
        self._link_cb.setChecked(visible)
        self._link_cb.blockSignals(False)

    def set_seq_visible(self, visible: bool):
        """実行パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._seq_cb.blockSignals(True)
        self._seq_cb.setChecked(visible)
        self._seq_cb.blockSignals(False)

    def set_link_listener_status(self, status: str) -> None:
        """連携リスナーの状態ラベルを更新する (i099)。"""
        lbl = getattr(self, "_link_int_status_lbl", None)
        if lbl is None:
            return
        if status.startswith("started:"):
            port = status.split(":", 1)[1]
            lbl.setText(f"状態: 受信中 (ポート {port})")
        elif status == "stopped":
            lbl.setText("状態: 停止中")
        elif status.startswith("error:"):
            msg = status.split(":", 1)[1]
            lbl.setText(f"状態: エラー ({msg})")
        else:
            lbl.setText(f"状態: {status}")

    def set_roulette_list(self, entries: list) -> None:
        """ルーレット一覧を更新する。

        Args:
            entries: list of dicts with keys:
                - 'id': str
                - 'label': str (表示名)
                - 'active': bool
                - 'visible': bool
        """
        # 既存行をクリア
        for row in self._roulette_rows.values():
            self._roulette_list_layout.removeWidget(row)
            row.deleteLater()
        self._roulette_rows.clear()

        total = len(entries)
        for entry in entries:
            rid = entry["id"]
            row = self._make_roulette_row(entry, total_count=total)
            self._roulette_list_layout.addWidget(row)
            self._roulette_rows[rid] = row

    def _make_roulette_row(self, entry: dict, *, total_count: int = 2) -> QWidget:
        """ルーレット1件の行ウィジェットを作成する。"""
        rid = entry["id"]
        is_active = entry["active"]
        is_visible = entry.get("visible", True)
        label_text = entry.get("label", rid)

        row = QWidget(self)  # i068: 親なし HWND フラッシュ防止
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        # i047: ルーレット名 — 通常時ボタン / ダブルクリックでインライン編集
        btn_label = f"▶ {label_text}" if is_active else label_text
        name_btn = _RouletteNameBtn(btn_label)
        name_btn.setFont(QFont("Meiryo", 9))
        name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_active:
            name_btn.setStyleSheet(
                f"QPushButton {{ background-color: {self._design.accent}; color: {self._design.text};"
                f" border: none; border-radius: 4px; padding: 4px 8px; text-align: left; }}"
                f"QPushButton:hover {{ opacity: 0.8; }}"
            )
            name_btn.setToolTip("現在の編集対象\nクリックで再選択 / ダブルクリックで名前変更")
        else:
            name_btn.setStyleSheet(
                f"QPushButton {{ background-color: {self._design.separator}; color: {self._design.text};"
                f" border: none; border-radius: 4px; padding: 4px 8px; text-align: left; }}"
                f"QPushButton:hover {{ background-color: {self._design.accent}; }}"
            )
            name_btn.setToolTip("クリックで編集対象を切り替え / ダブルクリックで名前変更")
        name_btn.clicked.connect(lambda checked=False, r=rid: self.roulette_activate_requested.emit(r))

        name_edit = _RenameLineEdit(label_text)
        name_edit.setFont(QFont("Meiryo", 9))
        name_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {self._design.separator}; color: {self._design.text};"
            f" border: 1px solid {self._design.accent}; border-radius: 4px; padding: 3px 7px; }}"
        )

        name_stack = QStackedWidget(row)  # i068: 親なし HWND フラッシュ防止
        name_stack.addWidget(name_btn)   # index 0: 通常表示
        name_stack.addWidget(name_edit)  # index 1: 編集中
        name_stack.setCurrentIndex(0)
        row_layout.addWidget(name_stack, stretch=1)

        # ダブルクリック → 編集開始
        _editing = [False]

        def _start_rename(stack=name_stack, edit=name_edit):
            _editing[0] = True
            edit.setText(label_text)
            edit.selectAll()
            stack.setCurrentIndex(1)
            edit.setFocus()

        def _confirm_rename(stack=name_stack, btn=name_btn, edit=name_edit):
            if not _editing[0]:
                return
            _editing[0] = False
            new_name = edit.text().strip()
            stack.setCurrentIndex(0)
            if new_name:
                btn.setText(f"▶ {new_name}" if is_active else new_name)
                self.roulette_rename_requested.emit(rid, new_name)

        def _cancel_rename(stack=name_stack):
            if not _editing[0]:
                return
            _editing[0] = False
            stack.setCurrentIndex(0)

        name_btn.double_clicked.connect(_start_rename)
        name_edit.returnPressed.connect(_confirm_rename)
        name_edit.editingFinished.connect(_confirm_rename)
        name_edit.escape_pressed.connect(_cancel_rename)

        # 表示/非表示トグル
        vis_btn = QPushButton("👁" if is_visible else "🚫")
        vis_btn.setFont(QFont("Meiryo", 9))
        vis_btn.setFixedSize(28, 28)
        vis_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        vis_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self._design.separator}; color: {self._design.text};"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: {self._design.accent}; }}"
        )
        # i423: 現在状態に合わせたツールチップで操作結果を案内
        vis_btn.setToolTip("表示中 → クリックで非表示" if is_visible else "非表示 → クリックで表示")
        current_visible = is_visible
        vis_btn.clicked.connect(
            lambda checked=False, r=rid, b=vis_btn, cv=current_visible:
            self._on_vis_btn_clicked(r, b, cv)
        )
        row_layout.addWidget(vis_btn)

        # i338: 削除ボタン（最後の1個は無効）
        del_btn = QPushButton("✕")
        del_btn.setFont(QFont("Meiryo", 9))
        del_btn.setFixedSize(28, 28)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self._design.separator}; color: {self._design.text};"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: #E53935; color: #FFFFFF; }}"
            f"QPushButton:disabled {{ opacity: 0.3; }}"
        )
        del_btn.setToolTip("このルーレットを削除")
        del_btn.setEnabled(total_count > 1)
        del_btn.clicked.connect(lambda checked=False, r=rid: self.roulette_delete_requested.emit(r))
        row_layout.addWidget(del_btn)

        return row

    def _on_vis_btn_clicked(self, roulette_id: str, btn: QPushButton, current_visible: bool):
        """表示/非表示ボタンのクリック処理。"""
        new_visible = not current_visible
        btn.setText("👁" if new_visible else "🚫")
        # i423: ツールチップも切替後の状態に更新する
        btn.setToolTip("表示中 → クリックで非表示" if new_visible else "非表示 → クリックで表示")
        # ボタンのクロージャの cv を更新するため、clicked を再接続する
        try:
            btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        btn.clicked.connect(
            lambda checked=False, r=roulette_id, b=btn, cv=new_visible:
            self._on_vis_btn_clicked(r, b, cv)
        )
        self.roulette_visibility_toggled.emit(roulette_id, new_visible)

    def update_active_roulette(self, active_id: str) -> None:
        """アクティブなルーレット ID だけを更新（一覧全再構築を避ける）。

        実際には set_roulette_list を呼んで全再構築する。
        """
        # 現在の実装では set_roulette_list で全更新する方が簡単なため、
        # 呼び出し元から set_roulette_list を使ってもらう。
        pass

    def set_apply_to_all(self, value: bool) -> None:
        """v0.6.1: 「全ルーレットに適用」CB は設定パネル側へ移動済み。
        後方互換のために no-op を残す。
        """
        pass

    def update_roulette_only_hide(self, key: str, value: bool) -> None:
        """ルーレット以外非表示時の個別設定チェックボックスを外部から同期する（シグナルなし）。"""
        cb_map = {
            "selection_handle": self._ro_show_selection_handle_cb,
            "title_plate": self._ro_show_title_plate_cb,
            "graph_btn": self._ro_show_graph_btn_cb,
            "grip": self._ro_show_grip_cb,
            "log": self._ro_show_log_cb,
            "manage_panel": self._ro_show_manage_panel_cb,
            "items_panel": self._ro_show_items_panel_cb,
            "settings_panel": self._ro_show_settings_panel_cb,
            "execution_panel": self._ro_show_execution_panel_cb,
            "ticket_panel": self._ro_show_ticket_panel_cb,
            "link_panel": self._ro_show_link_panel_cb,
        }
        cb = cb_map.get(key)
        if cb:
            cb.blockSignals(True)
            cb.setChecked(value)
            cb.blockSignals(False)

    def set_manage_float(self, value: bool) -> None:
        """管理パネル独立化ボタン状態を外部から同期する（シグナルなし）。"""
        self._manage_float_btn.blockSignals(True)
        self._manage_float_btn.setChecked(value)
        self._manage_float_btn.blockSignals(False)

    def set_auto_hide(self, enabled: bool, seconds: int,
                      fade_enabled: bool = True,
                      fade_seconds: float = 0.6) -> None:
        """自動全面非表示設定を外部から同期する（シグナルなし）。"""
        self._auto_hide_cb.blockSignals(True)
        self._auto_hide_cb.setChecked(enabled)
        self._auto_hide_cb.blockSignals(False)
        self._auto_hide_spin.blockSignals(True)
        self._auto_hide_spin.setValue(max(1, seconds))
        self._auto_hide_spin.blockSignals(False)
        self._auto_hide_fade_cb.blockSignals(True)
        self._auto_hide_fade_cb.setChecked(fade_enabled)
        self._auto_hide_fade_cb.blockSignals(False)
        self._auto_hide_fade_spin.blockSignals(True)
        self._auto_hide_fade_spin.setValue(max(0.1, min(10.0, fade_seconds)))
        self._auto_hide_fade_spin.setEnabled(fade_enabled)
        self._auto_hide_fade_spin.blockSignals(False)

    def update_design(self, design: DesignSettings):
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._drag_bar.update_design(design)
        self._scroll.setStyleSheet(f"background-color: {design.panel};")
        # v0.6.1: _apply_all_cb は設定パネル側へ移動済み
        _pkg_icon_style = (
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text};"
            f"  border: none; padding: 1px 4px;"
            f"  font-size: 10pt; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ color: {design.accent}; }}"
        )
        self._pkg_export_btn.setStyleSheet(_pkg_icon_style)
        self._pkg_import_btn.setStyleSheet(_pkg_icon_style)

    # ----------------------------------------------------------------
    #  イベント
    # ----------------------------------------------------------------

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.geometry_changed.emit()

    def set_transparent(self, enabled: bool):
        """パネル背景の透過モードを切り替える（実験的）。"""
        self._transparent = enabled
        d = self._design
        if enabled:
            # i108: クラス名修飾セレクタを使うことで QFrame 自身の背景塗りを確実に透過する。
            self.setStyleSheet("ManagePanel { background-color: transparent; }")
        else:
            self.setStyleSheet(f"background-color: {d.panel};")
        apply_transparent_to_widget_tree(self, enabled)

    def mousePressEvent(self, event):
        # クリックは吸収。ドラッグはドラッグバーからのみ。
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()
