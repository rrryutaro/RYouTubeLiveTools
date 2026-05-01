"""
RCommentHub — Qt版 CommentWindow（v0.3.2相当 4タブ統合UI）

Tk版 comment_window.py の4タブ構成を PySide6 QMainWindow で再実装。

4タブ構成:
  tab_all       : 全メッセージ（CommentView）
  tab_filter    : フィルタ一致メッセージ（CommentView + リングバッファ）
  tab_users     : ユーザー一覧（QTableWidget + WL/BL/対象フラグ操作）
  tab_fsettings : フィルタ設定（FilterRuleManager CRUD）

i146 で実装した操作性（全辺リサイズ・背景ドラッグ・画面内復帰）を維持。
"""

import ctypes
import ctypes.wintypes
import json
import logging
import threading
import uuid
from collections import deque
from datetime import datetime
from urllib import request as _url_request
from urllib.error import URLError

_log = logging.getLogger("comment_window_qt")

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSizePolicy, QPushButton, QScrollBar,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QLineEdit, QCheckBox,
    QFormLayout, QSplitter, QAbstractItemView, QAbstractScrollArea, QMenu,
)
from PySide6.QtCore import Qt, QEvent, QPoint, QTimer
from PySide6.QtGui import QColor, QGuiApplication

from constants import CONN_STATUS_LABELS
from comment_view_qt import CommentView
from filter_rules import FilterRule, MATCH_TYPES


# ─── 接続状態ごとの表示色（Tk版 CONN_STATUS_COLORS に準拠）─────────────────────
_STATUS_COLORS = {
    "disconnected": "#888888",
    "connecting":   "#FFCC44",
    "receiving":    "#44FF44",
    "reconnecting": "#FF8844",
    "error":        "#FF4444",
    "debug":        "#AA88FF",
}

# ─── コメント種別ごとの行色（最小版）────────────────────────────────────────────
_KIND_BG_COLORS = {
    "superChatEvent":              "#2A1A00",
    "superStickerEvent":           "#1A1A00",
    "memberMilestoneChatEvent":    "#001A2A",
    "membershipGiftingEvent":      "#001A2A",
    "giftMembershipReceivedEvent": "#001A2A",
    "messageDeletedEvent":         "#2A0A0A",
    "userBannedEvent":             "#2A0A0A",
}

# ─── QTabWidget スタイル ─────────────────────────────────────────────────────
_TAB_STYLE = (
    # タブバー余白域（タブが無い右側など）の白背景を防ぐ
    "QTabWidget { background: #1A1A2A; }"
    "QTabWidget::pane { border: none; background: #0D0D1A; }"
    "QTabWidget::tab-bar { background: #1A1A2A; }"
    "QTabBar { background: #1A1A2A; }"
    "QTabBar::scroller { background: #1A1A2A; }"
    "QTabBar::tab {"
    "  background: #1A1A2A; color: #888888;"
    "  padding: 3px 10px; border: none;"
    "  border-bottom: 2px solid transparent;"
    "}"
    "QTabBar::tab:selected {"
    "  color: #CCCCCC; background: #0D0D1A;"
    "  border-bottom: 2px solid #4466AA;"
    "}"
    "QTabBar::tab:hover:!selected { color: #AAAAAA; background: #252535; }"
)

# ─── テーブルスタイル ─────────────────────────────────────────────────────────
_TABLE_STYLE = (
    "QTableWidget {"
    "  background: #0D0D1A; color: #CCCCCC;"
    "  gridline-color: #1A1A30; border: none; font-size: 9pt;"
    "}"
    "QTableWidget::item:selected { background: #2A2A4A; color: #FFFFFF; }"
    "QHeaderView::section {"
    "  background: #1A1A2A; color: #888888;"
    "  border: none; padding: 2px 4px; font-size: 8pt;"
    "}"
    "QScrollBar:vertical {"
    "  background: #0D0D1A; width: 8px; margin: 0;"
    "}"
    "QScrollBar::handle:vertical {"
    "  background: #2A2A4A; border-radius: 4px; min-height: 16px;"
    "}"
)

# ─── フォームスタイル（フィルタ設定タブ）────────────────────────────────────
_FORM_STYLE = (
    "QWidget { background: #0D0D1A; color: #CCCCCC; font-size: 9pt; }"
    "QLineEdit {"
    "  background: #1A1A2A; color: #CCCCCC;"
    "  border: 1px solid #2A2A4A; padding: 2px 4px;"
    "}"
    "QComboBox {"
    "  background: #1A1A2A; color: #CCCCCC;"
    "  border: 1px solid #2A2A4A; padding: 2px 4px;"
    "}"
    "QComboBox QAbstractItemView {"
    "  background: #1A1A2A; color: #CCCCCC; selection-background-color: #2A2A4A;"
    "}"
    "QCheckBox { color: #CCCCCC; }"
    "QCheckBox::indicator { width: 13px; height: 13px; }"
    "QCheckBox::indicator:checked { background: #4466AA; border: 1px solid #6688CC; }"
    "QCheckBox::indicator:unchecked { background: #1A1A2A; border: 1px solid #2A2A4A; }"
    "QPushButton {"
    "  background: #252535; color: #CCCCCC;"
    "  border: none; padding: 2px 8px; font-size: 9pt;"
    "}"
    "QPushButton:hover { background: #3A3A5A; }"
    "QPushButton:pressed { background: #1A1A3A; }"
    "QLabel { color: #888888; }"
)

# ─── リングバッファサイズ ─────────────────────────────────────────────────────
_FILTER_BUF_SIZE = 500

# ─── RRoulette 外部連携 API（PoC）────────────────────────────────────────────
_RR_API_URL_DEFAULT = "http://127.0.0.1:18765/api/v1/rcommenthub/filter-match"
_RR_TIMEOUT  = 5  # 秒

# settings_mgr のキー名
_RR_KEY_ENDPOINT  = "rr_endpoint_url"   # 送信先 URL
_RR_KEY_DRY_RUN   = "rr_dry_run"        # True = 送信せずにログ出力のみ（デフォルト True）


class CommentWindowQt(QMainWindow):
    """
    Qt版 コメントビューウィンドウ — v0.3.2相当 4タブ統合UI。

    タブ1 全メッセージ: 受信コメントを全件表示（CommentView）
    タブ2 フィルタ:    filter_match=True のコメントのみ表示（CommentView + deque バッファ）
    タブ3 ユーザー:    UserManager のユーザー一覧（QTableWidget）
    タブ4 フィルタ設定: FilterRuleManager CRUD UI

    frameless / topmost / transparent は i146 実装を継承。
    """

    # frameless リサイズ感知幅 (px)
    _EDGE_SIZE = 8
    # ステータスバー高さ（_build_ui の status_bar.setFixedHeight と一致させること）
    _STATUS_BAR_H = 28
    # ドラッグ移動開始の閾値 (px, マンハッタン距離)
    # クリックとドラッグを分離するための遊び幅。Qt 標準 startDragDistance() の代わりに固定値を使用。
    _DRAG_THRESHOLD = 5

    def __init__(self, controller, settings_mgr, parent=None, *,
                 open_connect_cb=None,
                 open_settings_cb=None,
                 open_detail_cb=None,
                 on_quit_cb=None):
        super().__init__(parent)
        self._ctrl = controller
        self._sm   = settings_mgr
        self._open_flag = False

        self._open_connect  = open_connect_cb  or (lambda: None)
        self._open_settings = open_settings_cb or (lambda: None)
        self._open_detail   = open_detail_cb   or (lambda: None)
        self._on_quit       = on_quit_cb        or (lambda: None)

        # 初期化完了フラグ（False の間は moveEvent / resizeEvent の geometry 保存を抑制）
        self._init_complete = False
        # showEvent での位置復元済みフラグ（初回 show 時のみ _restore_pos を実行する）
        self._pos_restored  = False

        # フィルタ一致コメントのリングバッファ（将来の外部連携用）
        self._filter_buffer: deque = deque(maxlen=_FILTER_BUF_SIZE)

        # i112: フィルタビュー行ヘッダーベース文字列（seq_no → ヘッダー）
        self._filter_base_headers: dict = {}
        # i112: 手動送信中のitem参照（_on_rr_result でステータス更新用）
        self._rr_manual_item = None
        self._rr_manual_items: dict[str, object] = {}

        # i113: 全メッセージビューの行追跡（seq_no → 全時通算インデックス）
        self._all_row_count: int = 0
        self._all_seq_to_abs_idx: dict = {}   # seq_no → 追加時の全時通算インデックス
        self._all_base_headers: dict = {}     # seq_no → ベースヘッダー文字列
        self._all_buffer: deque = deque(maxlen=CommentView.MAX_ROWS)

        # フィルタ設定タブで現在選択中のルール ID
        self._current_rule_id: str | None = None

        # ドラッグ移動 (Method B: 手動 self.move())
        self._drag_start_pos: QPoint | None = None   # press 時のグローバル座標
        self._dragging: bool = False                 # 閾値超過後の drag 中フラグ
        self._drag_win_offset: QPoint | None = None  # window.pos() - cursor_pos at drag start

        self.setWindowTitle("RCommentHub - コメントビュー")
        self.resize(
            int(self._sm.get("cw_width",  440)),
            int(self._sm.get("cw_height", 680)),
        )
        self.setMinimumSize(200, 150)

        # geometry 保存デバウンスタイマー（moveEvent / resizeEvent）
        self._geom_save_timer = QTimer(self)
        self._geom_save_timer.setSingleShot(True)
        self._geom_save_timer.setInterval(400)
        self._geom_save_timer.timeout.connect(self._flush_geometry)

        # topmost フラグの現在値
        self._current_topmost: bool | None = None

        # 表示設定キャッシュ
        self._time_visible   = True
        self._time_mode      = "実時間"
        self._icon_visible   = True
        self._show_source    = False
        self._display_rows   = 1
        self._font_size_name = 9
        self._font_size_body = 9
        self._session_start_time: datetime | None = None

        # frameless 化（show() より前に確定）
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        # 透過基盤（show() より前に必ず設定）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._build_ui()

        # ユーザーリスト更新デバウンスタイマー（_build_ui 後に初期化）
        self._user_refresh_timer = QTimer(self)
        self._user_refresh_timer.setSingleShot(True)
        self._user_refresh_timer.setInterval(1000)
        self._user_refresh_timer.timeout.connect(self._refresh_user_list)

        # i112: RRoulette送信状態変化コールバック登録
        if hasattr(self._ctrl, "on_roulette_status"):
            self._ctrl.on_roulette_status(self._on_roulette_status)

        self.apply_display_settings()

        # 初期化完了
        self._init_complete = True

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet("QMainWindow { background: transparent; }")

        central = QWidget()
        self.setCentralWidget(central)
        central.setObjectName("cwCentral")
        central.setStyleSheet("QWidget#cwCentral { background: #0D0D1A; }")
        central.setAutoFillBackground(False)
        central.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 接続状態バー ────────────────────────────────────────────────────
        status_bar = QWidget()
        status_bar.setFixedHeight(self._STATUS_BAR_H)
        status_bar.setStyleSheet("background: #1A1A2A;")
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(10, 2, 10, 2)

        self._status_lbl = QLabel("未接続")
        self._status_lbl.setStyleSheet(
            f"color: {_STATUS_COLORS['disconnected']}; font-weight: bold;"
        )
        sb_layout.addWidget(self._status_lbl)

        self._title_lbl = QLabel("")
        self._title_lbl.setStyleSheet("color: #AAAAAA;")
        self._title_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._title_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        sb_layout.addWidget(self._title_lbl)

        _btn_style = (
            "QPushButton {"
            "  background: #252535; color: #CCCCCC;"
            "  border: none; padding: 1px 7px; font-size: 9pt;"
            "}"
            "QPushButton:hover { background: #3A3A5A; }"
            "QPushButton:pressed { background: #1A1A3A; }"
        )
        for label, callback in [
            ("接続", self._open_connect),
            ("詳細", self._open_detail),
            ("設定", self._open_settings),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setStyleSheet(_btn_style)
            btn.clicked.connect(callback)
            sb_layout.addWidget(btn)

        # i110: 切断ボタン（受信中のみ有効）
        self._btn_disconnect = QPushButton("切断")
        self._btn_disconnect.setFixedHeight(22)
        self._btn_disconnect.setStyleSheet(
            "QPushButton {"
            "  background: #3A2020; color: #FFAAAA;"
            "  border: none; padding: 1px 7px; font-size: 9pt;"
            "}"
            "QPushButton:hover { background: #662222; color: #FFFFFF; }"
            "QPushButton:disabled { background: #1A1A2A; color: #444444; }"
        )
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        sb_layout.addWidget(self._btn_disconnect)

        btn_close = QPushButton("×")
        btn_close.setFixedSize(22, 22)
        btn_close.setStyleSheet(
            "QPushButton { background: #3A2020; color: #FFAAAA; border: none; font-size: 11pt; }"
            "QPushButton:hover { background: #882222; color: #FFFFFF; }"
        )
        btn_close.clicked.connect(self._on_quit)
        sb_layout.addWidget(btn_close)

        root.addWidget(status_bar)

        # ── 4タブ QTabWidget ─────────────────────────────────────────────────
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(_TAB_STYLE)
        self._tab_widget.setDocumentMode(True)

        # タブ1: 全メッセージ
        self._comment_view = CommentView()
        self._comment_view.on_context_menu_requested = self._on_all_context_menu
        self._tab_widget.addTab(self._comment_view, "全メッセージ")

        # タブ2: フィルタ一致
        self._tab_widget.addTab(self._build_filter_tab(), "フィルタ")

        # タブ3: ユーザー一覧
        self._tab_widget.addTab(self._build_user_tab(), "ユーザー")

        # タブ4: フィルタ設定
        self._tab_widget.addTab(self._build_filter_settings_tab(), "フィルタ設定")

        # タブ切替時: ユーザー一覧・フィルタ設定を最新状態に更新
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        root.addWidget(self._tab_widget)

        # ── ドラッグ追跡: central widget 配下を再帰的に登録 ─────────────────
        self._install_drag_filters_recursive(central)

    def _build_filter_tab(self) -> QWidget:
        """タブ2: フィルタ一致 UI（CommentView + 送信ツールバー）を構築して返す。"""
        widget = QWidget()
        widget.setStyleSheet("background: #0D0D1A;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # CommentView
        self._filter_view = CommentView()
        self._filter_view.set_rr_marker_column_visible(True)
        self._filter_view.on_row_selected = self._on_filter_row_selected
        self._filter_view.on_send_requested = self._send_to_rroulette
        layout.addWidget(self._filter_view)

        # ── 送信ツールバー ────────────────────────────────────────────────
        _btn_style = (
            "QPushButton {"
            "  background: #2A3A5A; color: #CCCCCC;"
            "  border: none; padding: 2px 10px; font-size: 9pt;"
            "}"
            "QPushButton:hover { background: #3A4A6A; }"
            "QPushButton:pressed { background: #1A2A4A; }"
            "QPushButton:disabled { background: #1A1A2A; color: #555555; }"
        )
        tb = QWidget()
        tb.setFixedHeight(28)
        tb.setStyleSheet("background: #1A1A2A;")
        tb_layout = QHBoxLayout(tb)
        tb_layout.setContentsMargins(6, 3, 6, 3)
        tb_layout.setSpacing(6)

        self._rr_send_btn = QPushButton("RRouletteへ送信")
        self._rr_send_btn.setFixedHeight(22)
        self._rr_send_btn.setStyleSheet(_btn_style)
        self._rr_send_btn.setEnabled(False)
        self._rr_send_btn.clicked.connect(self._send_to_rroulette)
        tb_layout.addWidget(self._rr_send_btn)

        # i113: 連携送信 ON/OFF チェックボックス（設定画面の同名設定と同期）
        _rr_cfg_init = self._sm.get("roulette_integration", {})
        self._rr_enabled_cb = QCheckBox("連携送信")
        self._rr_enabled_cb.setChecked(bool(_rr_cfg_init.get("enabled", False)))
        self._rr_enabled_cb.setStyleSheet(
            "QCheckBox { color: #AAAAAA; font-size: 8pt; }"
            "QCheckBox::indicator { width: 12px; height: 12px; }"
            "QCheckBox::indicator:checked { background: #4466AA; border: 1px solid #6688CC; }"
            "QCheckBox::indicator:unchecked { background: #1A1A2A; border: 1px solid #2A2A4A; }"
        )
        self._rr_enabled_cb.setToolTip(
            "RRoulette 連携送信を有効にする（設定画面の同名設定と連動）"
        )
        self._rr_enabled_cb.clicked.connect(self._on_rr_enabled_changed)
        tb_layout.addWidget(self._rr_enabled_cb)

        # i111: 自動送信モードを手動送信と同じ行に配置（i110の専用バーを廃止）
        _auto_lbl = QLabel("自動送信:")
        _auto_lbl.setStyleSheet("color: #888888; font-size: 8pt;")
        tb_layout.addWidget(_auto_lbl)

        self._rr_auto_mode_combo = QComboBox()
        self._rr_auto_mode_combo.setFixedHeight(22)
        self._rr_auto_mode_combo.setStyleSheet(
            "QComboBox { background: #1A1A2A; color: #CCCCCC; border: 1px solid #2A2A4A;"
            "  padding: 1px 4px; font-size: 8pt; }"
            "QComboBox QAbstractItemView { background: #1A1A2A; color: #CCCCCC; }"
        )
        # 自動送信モード: off / all / no_black / whitelist / target
        for label in ["OFF", "全て", "ブラック以外全て", "ホワイトのみ", "対象ユーザーのみ"]:
            self._rr_auto_mode_combo.addItem(label)
        saved_mode = self._sm.get("rr_auto_send_mode", "off")
        if saved_mode == "filter_match":
            saved_mode = "all"
        _mode_idx = {"off": 0, "all": 1, "no_black": 2, "whitelist": 3, "target": 4}.get(saved_mode, 0)
        self._rr_auto_mode_combo.setCurrentIndex(_mode_idx)
        self._rr_auto_mode_combo.currentIndexChanged.connect(self._on_rr_auto_mode_changed)
        tb_layout.addWidget(self._rr_auto_mode_combo)

        self._rr_selected_lbl = QLabel("（行を選択してください）")
        self._rr_selected_lbl.setStyleSheet("color: #555555; font-size: 8pt;")
        self._rr_selected_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        tb_layout.addWidget(self._rr_selected_lbl)

        layout.addWidget(tb)

        # i112: RR送信状態バー（ツールバーの下段）
        sb = QWidget()
        sb.setFixedHeight(22)
        sb.setStyleSheet("background: #141428;")
        sb_layout = QHBoxLayout(sb)
        sb_layout.setContentsMargins(6, 2, 6, 2)
        sb_layout.setSpacing(6)

        self._rr_status_lbl = QLabel("RR: [未判定]")
        self._rr_status_lbl.setStyleSheet("color: #666688; font-size: 8pt;")
        self._rr_status_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        sb_layout.addWidget(self._rr_status_lbl)

        # i113: デバッグコメント試験設定
        self._rr_debug_cb = QCheckBox("デバッグも対象（試験）")
        self._rr_debug_cb.setChecked(bool(self._sm.get("rr_auto_send_debug_enabled", False)))
        self._rr_debug_cb.setStyleSheet(
            "QCheckBox { color: #666688; font-size: 8pt; }"
            "QCheckBox::indicator { width: 11px; height: 11px; }"
            "QCheckBox::indicator:checked { background: #334466; border: 1px solid #446688; }"
            "QCheckBox::indicator:unchecked { background: #0D0D1A; border: 1px solid #1A1A30; }"
        )
        self._rr_debug_cb.setToolTip(
            "ONにするとデバッグコメントも自動送信対象になります（試験用・通常配信ではOFFのままにしてください）"
        )
        self._rr_debug_cb.clicked.connect(self._on_rr_debug_changed)
        sb_layout.addWidget(self._rr_debug_cb)

        # テスト経路ボタン（フィルタタブ行を選択して自動送信経路を手動確認）
        _test_btn_style = (
            "QPushButton {"
            "  background: #1A2A3A; color: #8888AA;"
            "  border: none; padding: 1px 6px; font-size: 8pt;"
            "}"
            "QPushButton:hover { background: #2A3A4A; color: #AAAACC; }"
            "QPushButton:disabled { background: #0A0A1A; color: #333344; }"
        )
        self._rr_test_btn = QPushButton("テスト経路")
        self._rr_test_btn.setFixedHeight(18)
        self._rr_test_btn.setStyleSheet(_test_btn_style)
        self._rr_test_btn.setEnabled(False)
        self._rr_test_btn.setToolTip(
            "選択行を自動送信経路でテスト送信"
        )
        self._rr_test_btn.clicked.connect(self._test_auto_send)
        sb_layout.addWidget(self._rr_test_btn)

        layout.addWidget(sb)
        return widget

    def _on_rr_auto_mode_changed(self, index: int) -> None:
        """自動送信モードをコンボ選択に合わせて設定に保存する。"""
        modes = ["off", "all", "no_black", "whitelist", "target"]
        mode = modes[index] if index < len(modes) else "off"
        self._sm.update({"rr_auto_send_mode": mode})

    def _on_rr_enabled_changed(self, checked: bool) -> None:
        """i113: 連携送信 ON/OFF チェックボックスの変更を設定に保存する。"""
        cfg = dict(self._sm.get("roulette_integration", {}))
        cfg["enabled"] = checked
        self._sm.update({"roulette_integration": cfg})
        if not checked and hasattr(self, "_rr_selected_lbl"):
            self._rr_selected_lbl.setText("連携送信OFFのため自動送信されません")
            self._rr_selected_lbl.setStyleSheet("color: #888844; font-size: 8pt;")

    def _on_rr_debug_changed(self, checked: bool) -> None:
        """i113: デバッグコメント試験設定の変更を保存する。"""
        self._sm.update({"rr_auto_send_debug_enabled": checked})

    def _on_filter_row_selected(self, index: int | None) -> None:
        """フィルタビューで行が選択されたときのコールバック。"""
        selected_indices = getattr(self._filter_view, "selected_row_indices", []) or []
        if not selected_indices:
            self._rr_send_btn.setEnabled(False)
            self._rr_test_btn.setEnabled(False)
            self._rr_selected_lbl.setText("（行を選択してください）")
            self._rr_selected_lbl.setStyleSheet("color: #555555; font-size: 8pt;")
            self._rr_status_lbl.setText("RR: [未判定]")
            self._rr_status_lbl.setStyleSheet("color: #666688; font-size: 8pt;")
        else:
            index = selected_indices[-1]
            if index >= len(self._filter_buffer):
                return
            item = list(self._filter_buffer)[index]
            text = getattr(item, "body", "") or ""
            preview = text[:30] + ("…" if len(text) > 30 else "")
            selected_count = len(selected_indices)
            self._rr_send_btn.setEnabled(True)
            self._rr_test_btn.setEnabled(True)
            self._rr_selected_lbl.setText(
                f"{selected_count}件選択" if selected_count > 1 else preview
            )
            self._rr_selected_lbl.setStyleSheet("color: #AAAAAA; font-size: 8pt;")
            self._update_rr_status_for_item(item)

    def _rr_status_text(self, item) -> str:
        """i112: CommentItemのRRoulette送信状態を短い文字列で返す。"""
        status = getattr(item, "roulette_send_status", "未判定")
        reason = getattr(item, "roulette_send_reason", "")
        error  = getattr(item, "roulette_send_error",  "")
        sent_at = getattr(item, "roulette_sent_at", None)
        if reason:
            s = f"{status}: {reason}"
        elif error:
            s = f"{status}: {error}"
        else:
            s = status
        if sent_at is not None:
            s += f" ({sent_at.strftime('%H:%M:%S')})"
        return s

    def _update_rr_status_for_item(self, item) -> None:
        """i112: _rr_status_lbl を指定itemのRR状態で更新する（選択行と一致している場合）。"""
        if not hasattr(self, "_rr_status_lbl"):
            return
        text = self._rr_status_text(item)
        status = getattr(item, "roulette_send_status", "未判定")
        if status == "送信済み" or status == "手動送信済み":
            color = "#44CC88"
        elif status.startswith("失敗"):
            color = "#FF6666"
        elif status == "除外":
            color = "#888844"
        elif status == "送信中" or status == "送信中(手動)":
            color = "#4488FF"
        else:
            color = "#666688"
        self._rr_status_lbl.setText(f"RR: [{text}]")
        self._rr_status_lbl.setStyleSheet(f"color: {color}; font-size: 8pt;")

    def _rr_marker_for_status(self, item):
        status = getattr(item, "roulette_send_status", "未判定")
        if status in ("送信済み", "手動送信済み"):
            return "✓", QColor("#44CC88")
        if status in ("送信中", "送信中(手動)"):
            return "…", QColor("#4488FF")
        if status.startswith("失敗"):
            return "!", QColor("#FF6666")
        if status == "dry-run":
            return "D", QColor("#8888CC")
        return "", QColor("#666688")

    def _update_filter_row_header(self, item) -> None:
        """フィルタビューの対応行左端へRR状態マーカーを反映する。"""
        if not hasattr(self, "_filter_view"):
            return
        buf_list = list(self._filter_buffer)
        try:
            idx = next(i for i, x in enumerate(buf_list) if x is item)
        except StopIteration:
            return
        seq_no = getattr(item, "seq_no", None)
        base = self._filter_base_headers.get(seq_no, "") if seq_no is not None else ""
        if not base:
            return
        self._filter_view.update_row_header(idx, base)
        marker, color = self._rr_marker_for_status(item)
        self._filter_view.update_row_marker(idx, marker, color)

    def _update_all_row_header(self, item) -> None:
        """全メッセージビューの対応行左端へRR状態マーカーを反映する。"""
        if not hasattr(self, "_comment_view"):
            return
        seq_no = getattr(item, "seq_no", None)
        if seq_no is None or seq_no not in self._all_seq_to_abs_idx:
            return
        abs_idx = self._all_seq_to_abs_idx[seq_no]
        from comment_view_qt import CommentView as _CV
        pruned = max(0, self._all_row_count - _CV.MAX_ROWS)
        current_idx = abs_idx - pruned
        if current_idx < 0:
            return   # 行が既に削除済み
        base = self._all_base_headers.get(seq_no, "")
        if not base:
            return
        self._comment_view.update_row_header(current_idx, base)
        marker, color = self._rr_marker_for_status(item)
        self._comment_view.update_row_marker(current_idx, marker, color)

    def _on_roulette_status(self, item) -> None:
        """i112/i113: RRoulette送信状態変化コールバック（メインスレッドで実行）。"""
        # フィルタビューの行ヘッダーを更新
        self._update_filter_row_header(item)
        # 全メッセージビューの行ヘッダーを更新（i113）
        self._update_all_row_header(item)
        # 現在選択行が変化したitemなら状態ラベルも更新
        idx = self._filter_view.selected_row_index
        if idx is not None:
            buf_list = list(self._filter_buffer)
            if 0 <= idx < len(buf_list) and buf_list[idx] is item:
                self._update_rr_status_for_item(item)

    def _test_auto_send(self) -> None:
        """i112: テスト経路ボタン — 選択行を自動送信経路でテスト送信する。
        debug source チェックをバイパスするので、デバッグコメントでも確認可能。
        """
        if not hasattr(self._ctrl, "test_roulette_link"):
            return
        for item in self._selected_filter_items():
            self._ctrl.test_roulette_link(item)
            self._update_rr_status_for_item(item)

    def _selected_filter_items(self) -> list:
        indices = getattr(self._filter_view, "selected_row_indices", []) or []
        buf = list(self._filter_buffer)
        return [buf[i] for i in indices if 0 <= i < len(buf)]

    def _on_all_context_menu(self, index: int | None, global_pos: QPoint) -> None:
        indices = getattr(self._comment_view, "selected_row_indices", []) or []
        if index is not None and index not in indices:
            indices = [index]
        buf = list(self._all_buffer)
        items = [
            buf[i] for i in indices
            if 0 <= i < len(buf) and not getattr(buf[i], "is_system_message", False)
        ]
        menu = QMenu(self)
        send_action = menu.addAction(
            "RRouletteへ送信" if len(items) <= 1 else f"RRouletteへ送信 ({len(items)}件)"
        )
        send_action.setEnabled(bool(items))
        action = menu.exec(global_pos)
        if action == send_action and items:
            self._rr_send_btn.setEnabled(False)
            for item in items:
                self._send_one_to_rroulette(item)

    def _send_to_rroulette(self) -> None:
        """選択中フィルタ行を外部（RRoulette 等）へ送信する（dry-run / HTTP POST）。

        RCommentHub の責務は「フィルタ済みコメントを送信する」ことのみ。
        RRoulette 側の動作（候補追加・スピン等）はすべて受信側が判断する。
        """
        items = self._selected_filter_items()
        if not items:
            return
        self._rr_send_btn.setEnabled(False)
        for item in items:
            self._send_one_to_rroulette(item)

    def _send_one_to_rroulette(self, item) -> None:
        """フィルタ行1件を外部（RRoulette 等）へ送信する。"""

        text        = getattr(item, "body", "") or ""
        author_name = getattr(item, "author_name", "") or ""
        message_id  = getattr(item, "message_id", "") or str(uuid.uuid4())
        source_id   = getattr(item, "source_id", "")
        if "youtube" in source_id.lower():
            source = "youtube"
        elif "twitch" in source_id.lower():
            source = "twitch"
        else:
            source = "unknown"

        # フィルタ一致ルール情報（複数ある場合は先頭を使用）
        rule_ids        = getattr(item, "filter_rule_ids", [])
        matched_rule_id = rule_ids[0] if rule_ids else ""
        matched_rule_name = ""
        if matched_rule_id:
            _fmgr = getattr(self._ctrl, "filter_mgr", None)
            if _fmgr:
                _rule = _fmgr.get_rule(matched_rule_id)
                matched_rule_name = _rule.name if _rule else ""

        # 設定読み込み（Phase 1: roulette_integration dict 経由）
        _rr_cfg     = self._sm.get("roulette_integration", {})
        dry_run     = bool(_rr_cfg.get("dry_run", False))
        port        = int(_rr_cfg.get("port", 12345))
        endpoint_url = f"http://127.0.0.1:{port}/api/link-message"

        # i113: コントローラの build_roulette_payload() で手動・自動送信のpayloadを統一
        if hasattr(self._ctrl, "build_roulette_payload"):
            payload = self._ctrl.build_roulette_payload(item, matched_rule_name=matched_rule_name)
        else:
            # フォールバック（後方互換）
            author_channel_id = getattr(item, "channel_id", "") or ""
            payload = {
                "source_app":        "RCommentHub",
                "platform":          source,
                "profile_name":      "",
                "filter_name":       matched_rule_name,
                "author_name":       author_name,
                "author_channel_id": author_channel_id,
                "comment_text":      text,
                "message_type":      "filter_match",
                "received_at":       "",
            }

        # i112: 手動送信中のitem参照を保持してステータス更新に使う
        send_id = str(uuid.uuid4())
        self._rr_manual_item = item
        self._rr_manual_items[send_id] = item
        item.roulette_send_status = "送信中(手動)"
        self._update_filter_row_header(item)
        self._update_all_row_header(item)

        if dry_run:
            # dry-run: HTTP 送信せず JSON をログに出す
            _log.info("[dry-run] link-message payload: %s",
                      json.dumps(payload, ensure_ascii=False))
            self._on_rr_result(
                {"ok": True,
                 "message": "[dry-run] 送信しませんでした（dry_run=True）",
                 "reason": "dry_run"},
                text, None, send_id,
            )
            return

        threading.Thread(
            target=self._do_send_http,
            args=(payload, text, endpoint_url, send_id),
            daemon=True,
        ).start()

    @staticmethod
    def _rr_response_ok(resp: dict | None) -> bool:
        if not resp:
            return False
        return bool(resp.get("ok")) or str(resp.get("status", "")).lower() == "ok"

    def _do_send_http(self, payload: dict, text: str, url: str, send_id: str) -> None:
        """HTTP POST を別スレッドで実行し、結果を Qt メインスレッドへ渡す。"""
        def done(resp, err):
            dispatch = getattr(self._ctrl, "_dispatch", None)
            if callable(dispatch):
                dispatch(lambda: self._on_rr_result(resp, text, err, send_id))
            else:
                QTimer.singleShot(0, lambda: self._on_rr_result(resp, text, err, send_id))

        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req  = _url_request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with _url_request.urlopen(req, timeout=_RR_TIMEOUT) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace").strip()
                resp_body = json.loads(raw_body) if raw_body else {"status": "ok"}
        except URLError as e:
            reason = str(e.reason) if hasattr(e, "reason") else str(e)
            done(None, reason)
            return
        except Exception as e:
            done(None, str(e))
            return
        done(resp_body, None)

    def _on_rr_result(self, resp: dict | None, text: str, error: str | None, send_id: str | None = None) -> None:
        """HTTP 結果をメインスレッドで受け取り、システムメッセージとして表示する。"""
        if not getattr(self, "_rr_manual_items", {}):
            self._rr_send_btn.setEnabled(True)

        if error is not None:
            msg = f"RRouletteへの送信に失敗しました: {error}"
        elif resp is None:
            msg = "RRouletteへの送信に失敗しました: 不明なエラー"
        elif resp.get("reason") == "dry_run":
            msg = resp.get("message", "[dry-run]")
        elif not self._rr_response_ok(resp):
            msg = f"RRouletteへの送信に失敗しました: {resp.get('message', '?')}"
        else:
            preview = text[:20] + ("…" if len(text) > 20 else "")
            msg = f"RRouletteへ送信しました: {preview}"

        # i112/i113: 手動送信アイテムのステータス更新（update_roulette_status でUI通知統一）
        if send_id is not None:
            manual_item = self._rr_manual_items.pop(send_id, None)
        else:
            manual_item = self._rr_manual_item
        if not self._rr_manual_items:
            self._rr_send_btn.setEnabled(True)
        if manual_item is self._rr_manual_item:
            self._rr_manual_item = None
        if manual_item is not None:
            if error is not None or (resp is not None and not self._rr_response_ok(resp)
                                     and resp.get("reason") != "dry_run"):
                _err_str = error if error is not None else (resp.get("message", "?") if resp else "?")
                if hasattr(self._ctrl, "update_roulette_status"):
                    self._ctrl.update_roulette_status(manual_item, "失敗(手動)", error=_err_str)
                else:
                    manual_item.roulette_send_status = "失敗(手動)"
                    manual_item.roulette_send_error  = _err_str
                    self._update_rr_status_for_item(manual_item)
                    self._update_filter_row_header(manual_item)
            elif resp is not None and resp.get("reason") == "dry_run":
                if hasattr(self._ctrl, "update_roulette_status"):
                    self._ctrl.update_roulette_status(manual_item, "dry-run")
                else:
                    manual_item.roulette_send_status = "dry-run"
                    self._update_rr_status_for_item(manual_item)
                    self._update_filter_row_header(manual_item)
            else:
                if hasattr(self._ctrl, "update_roulette_status"):
                    self._ctrl.update_roulette_status(manual_item, "手動送信済み",
                                                      sent_at=datetime.now())
                else:
                    manual_item.roulette_send_status = "手動送信済み"
                    manual_item.roulette_sent_at     = datetime.now()
                    self._update_rr_status_for_item(manual_item)
                    self._update_filter_row_header(manual_item)

        if error is None and resp is not None and self._rr_response_ok(resp):
            return

        try:
            import time as _time
            raw = {
                "id": f"_rr_{int(_time.time() * 1000)}",
                "_source_id":         "_rr_api",
                "_source_name":       "RRoulette",
                "_tts_source_name":   "",
                "_is_system_message": True,
                "_is_backlog":        True,   # TTS 対象外: 外部連携の内部フィードバックは読み上げ不要
                "snippet": {
                    "type":           "systemMessageEvent",
                    "displayMessage": msg,
                    "publishedAt":    datetime.now().isoformat(),
                },
                "authorDetails": {
                    "displayName":      "[RRoulette]",
                    "channelId":        "_rr",
                    "channelUrl":       "",
                    "profileImageUrl":  "",
                    "isChatOwner":      False,
                    "isChatModerator":  False,
                    "isChatSponsor":    False,
                    "isVerified":       False,
                },
            }
            # controller 経由で追加（seq_no 割り当て・フィルタ評価・UI コールバック一括）
            self._ctrl.add_comment(raw)
        except Exception as exc:
            _log.warning("_on_rr_result: failed to create system message: %s", exc)

    def _build_user_tab(self) -> QWidget:
        """タブ3: ユーザー一覧 UI を構築して返す"""
        widget = QWidget()
        widget.setStyleSheet("background: #0D0D1A;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ツールバー
        tb = QHBoxLayout()
        tb.setSpacing(4)
        btn_refresh = QPushButton("更新")
        btn_refresh.setFixedHeight(22)
        btn_refresh.setStyleSheet(_FORM_STYLE)
        btn_refresh.clicked.connect(self._refresh_user_list)
        tb.addWidget(btn_refresh)

        self._user_count_lbl = QLabel("0 人")
        self._user_count_lbl.setStyleSheet("color: #888888; font-size: 8pt;")
        tb.addWidget(self._user_count_lbl)
        tb.addStretch()
        layout.addLayout(tb)

        # ユーザーテーブル（列: 表示名 / 回数 / 最終発言 / WL / BL / 対象）
        self._user_table = QTableWidget()
        self._user_table.setStyleSheet(_TABLE_STYLE)
        self._user_table.setColumnCount(6)
        self._user_table.setHorizontalHeaderLabels(
            ["表示名", "回数", "最終発言", "WL", "BL", "対象"]
        )
        self._user_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._user_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._user_table.setAlternatingRowColors(False)
        self._user_table.verticalHeader().setVisible(False)
        self._user_table.verticalHeader().setDefaultSectionSize(20)
        hdr = self._user_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._user_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._user_table.customContextMenuRequested.connect(
            self._user_context_menu
        )
        # i110: WL/BL/対象列クリックでON/OFF切り替え
        self._user_table.cellClicked.connect(self._on_user_cell_clicked)
        layout.addWidget(self._user_table)
        return widget

    def _build_filter_settings_tab(self) -> QWidget:
        """タブ4: フィルタ設定 UI を構築して返す"""
        widget = QWidget()
        widget.setStyleSheet(_FORM_STYLE)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── ツールバー ──────────────────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setSpacing(4)
        for label, slot in [
            ("＋", self._add_filter_rule),
            ("削除", self._delete_filter_rule),
            ("↑", self._move_filter_rule_up),
            ("↓", self._move_filter_rule_down),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.clicked.connect(slot)
            tb.addWidget(btn)
        tb.addStretch()
        layout.addLayout(tb)

        # ── 縦分割: ルール一覧 (上) + 編集フォーム (下) ────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #1A1A30; height: 4px; }"
        )

        # ルール一覧テーブル（列: ON / 名前 / テキスト / 一致種別）
        self._rule_table = QTableWidget()
        self._rule_table.setStyleSheet(_TABLE_STYLE)
        self._rule_table.setColumnCount(4)
        self._rule_table.setHorizontalHeaderLabels(["ON", "名前", "テキスト", "一致"])
        self._rule_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._rule_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._rule_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._rule_table.verticalHeader().setVisible(False)
        self._rule_table.verticalHeader().setDefaultSectionSize(20)
        rhdr = self._rule_table.horizontalHeader()
        rhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        rhdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        rhdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        rhdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._rule_table.selectionModel().selectionChanged.connect(
            self._on_rule_selected
        )
        splitter.addWidget(self._rule_table)

        # 編集フォーム
        form_container = QWidget()
        form_container.setStyleSheet(_FORM_STYLE)
        form_layout = QFormLayout(form_container)
        form_layout.setContentsMargins(6, 6, 6, 6)
        form_layout.setSpacing(6)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._rule_enabled_cb  = QCheckBox("有効")
        self._rule_name_edit   = QLineEdit()
        self._rule_name_edit.setPlaceholderText("ルール名")
        # i111: テキスト入力とキーワード条件 (AND/OR) を同じ行に配置
        self._rule_text_edit   = QLineEdit()
        self._rule_text_edit.setPlaceholderText("キーワード（カンマ区切りで複数指定可）")
        self._rule_kw_cond_combo = QComboBox()
        self._rule_kw_cond_combo.addItems(["OR", "AND"])
        self._rule_kw_cond_combo.setToolTip(
            "OR: いずれかのキーワードを含む\n"
            "AND: すべてのキーワードを含む"
        )
        _kw_widget = QWidget()
        _kw_layout = QHBoxLayout(_kw_widget)
        _kw_layout.setContentsMargins(0, 0, 0, 0)
        _kw_layout.setSpacing(4)
        _kw_layout.addWidget(self._rule_text_edit, 1)
        _kw_layout.addWidget(self._rule_kw_cond_combo)
        self._rule_match_combo = QComboBox()
        self._rule_match_combo.addItems(MATCH_TYPES)
        self._rule_field_combo = QComboBox()
        self._rule_field_combo.addItems(["本文", "投稿者名"])

        # 種別チェック
        kind_w = QWidget()
        kind_l = QHBoxLayout(kind_w)
        kind_l.setContentsMargins(0, 0, 0, 0)
        kind_l.setSpacing(8)
        self._cb_kind_normal = QCheckBox("通常")
        self._cb_kind_sc     = QCheckBox("SC")
        self._cb_kind_other  = QCheckBox("その他")
        for cb in (self._cb_kind_normal, self._cb_kind_sc, self._cb_kind_other):
            kind_l.addWidget(cb)
        kind_l.addStretch()

        # 属性チェック
        role_w = QWidget()
        role_l = QHBoxLayout(role_w)
        role_l.setContentsMargins(0, 0, 0, 0)
        role_l.setSpacing(8)
        self._cb_role_owner    = QCheckBox("配信者")
        self._cb_role_mod      = QCheckBox("Mod")
        self._cb_role_member   = QCheckBox("Mbr")
        self._cb_role_verified = QCheckBox("Ver")
        for cb in (self._cb_role_owner, self._cb_role_mod,
                   self._cb_role_member, self._cb_role_verified):
            role_l.addWidget(cb)
        role_l.addStretch()

        # ユーザー連動
        self._cb_excl_bl      = QCheckBox("BL除外")
        self._cb_filter_tgt   = QCheckBox("対象ユーザーのみ")

        # 適用ボタン
        btn_apply = QPushButton("変更を適用")
        btn_apply.setFixedHeight(24)
        btn_apply.clicked.connect(self._apply_filter_edit)

        form_layout.addRow("", self._rule_enabled_cb)
        form_layout.addRow("名前:", self._rule_name_edit)
        form_layout.addRow("テキスト:", _kw_widget)
        form_layout.addRow("一致:", self._rule_match_combo)
        form_layout.addRow("対象:", self._rule_field_combo)
        form_layout.addRow("種別:", kind_w)
        form_layout.addRow("属性:", role_w)
        form_layout.addRow("", self._cb_excl_bl)
        form_layout.addRow("", self._cb_filter_tgt)
        form_layout.addRow("", btn_apply)

        splitter.addWidget(form_container)
        splitter.setSizes([160, 260])

        layout.addWidget(splitter)
        self._set_filter_form_enabled(False)
        return widget

    # ─── タブ切替ハンドラ ──────────────────────────────────────────────────────

    def _on_tab_changed(self, index: int):
        """タブ切替時: ユーザー一覧・フィルタ設定を最新状態へ更新する"""
        if index == 2:   # ユーザー一覧
            self._refresh_user_list()
        elif index == 3:  # フィルタ設定
            self._refresh_filter_list()

    # ─── 公開 API ──────────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._open_flag and self.isVisible()

    def apply_display_settings(self) -> None:
        """settings_mgr から表示設定を読み込んで反映する。"""
        # ── 最前面表示 ────────────────────────────────────────────────────────
        topmost = bool(self._sm.get("cw_topmost", False))
        if topmost != self._current_topmost:
            self._current_topmost = topmost
            self._apply_topmost(topmost)

        # ── 表示設定 ─────────────────────────────────────────────────────────
        self._time_visible   = bool(self._sm.get("time_visible", True))
        self._time_mode      = str(self._sm.get("time_mode", "実時間"))
        self._icon_visible   = bool(self._sm.get("icon_visible", True))
        self._show_source    = bool(self._sm.get("cw_show_source", False))
        self._display_rows   = max(1, min(2, int(self._sm.get("display_rows", 1))))
        self._font_size_body = max(7, int(self._sm.get("font_size_body", 9)))
        self._font_size_name = max(7, int(self._sm.get("font_size_name", 9)))

        settings = dict(
            display_rows   = self._display_rows,
            font_size_name = self._font_size_name,
            font_size_body = self._font_size_body,
            icon_visible   = self._icon_visible,
        )
        self._comment_view.apply_settings(**settings)
        self._filter_view.apply_settings(**settings)

        # ── 透過設定 ──────────────────────────────────────────────────────────
        transparent = bool(self._sm.get("cw_transparent", False))
        if transparent:
            alpha_pct = max(10, min(100, int(self._sm.get("cw_comment_alpha", 100))))
            self.setWindowOpacity(alpha_pct / 100.0)
        else:
            self.setWindowOpacity(1.0)

        # i113: 連携送信 ON/OFF チェックボックスを設定と同期（設定画面保存後の反映用）
        if hasattr(self, "_rr_enabled_cb"):
            _rr_cfg_sync = self._sm.get("roulette_integration", {})
            _enabled_sync = bool(_rr_cfg_sync.get("enabled", False))
            self._rr_enabled_cb.blockSignals(True)
            self._rr_enabled_cb.setChecked(_enabled_sync)
            self._rr_enabled_cb.blockSignals(False)

    def open(self):
        """ウィンドウを表示する。すでに開いていれば前面に出す。"""
        self._open_flag = True
        self.apply_display_settings()
        self.show()
        self.raise_()
        self.activateWindow()

    def close(self):
        """ウィンドウを非表示にする（アプリ終了ではなく hide）。"""
        self._open_flag = False
        super().hide()

    # ─── コメント受信 ──────────────────────────────────────────────────────────

    def _elapsed_str(self, recv_time: datetime) -> str:
        if self._session_start_time is None:
            return "00:00"
        delta = recv_time - self._session_start_time
        total_sec = max(0, int(delta.total_seconds()))
        h, rem = divmod(total_sec, 3600)
        m, s   = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def _make_row_data(self, item):
        """item から CommentView.add_row 引数を生成して返す（tuple）"""
        recv_time = getattr(item, "recv_time", None)
        if self._time_mode == "経過時間" and recv_time is not None:
            time_str = self._elapsed_str(recv_time)
        else:
            time_str = item.recv_time_str() if hasattr(item, "recv_time_str") else ""
        author    = getattr(item, "author_name", "—") or "—"
        body      = getattr(item, "body", "") or ""
        kind      = getattr(item, "kind", "")
        is_system = getattr(item, "is_system_message", False)

        source_pfx = ""
        if not is_system and self._show_source:
            sid   = getattr(item, "source_id",   "conn1")
            sname = getattr(item, "source_name", "") or sid
            if sname:
                source_pfx = f"[{sname}] "

        if is_system:
            header_line = f"[{time_str}] {body}" if self._time_visible else body
            body_text   = ""
            row_author  = None
        else:
            header_line = (f"[{time_str}] {source_pfx}{author}" if self._time_visible
                           else f"{source_pfx}{author}")
            body_text   = body
            row_author  = author

        # 背景色
        bg_color = QColor(_KIND_BG_COLORS[kind]) if (not is_system and kind in _KIND_BG_COLORS) else None

        # 前景色
        if is_system:
            fg_color = QColor("#888888")
        elif kind in _KIND_BG_COLORS:
            fg_color = QColor("#FFD080")
        elif getattr(item, "is_owner", False):
            fg_color = QColor("#FFDD44")
        elif getattr(item, "is_moderator", False):
            fg_color = QColor("#44AAFF")
        elif getattr(item, "filter_match", False):
            fg_color = QColor("#FF88AA")
        else:
            fg_color = QColor("#CCCCCC")

        profile_url = getattr(item, "profile_url", "") or ""
        return header_line, body_text, row_author, bg_color, fg_color, profile_url

    def add_comment(self, item) -> None:
        """
        コメント1件をビューに追加する（コントローラの on_comment_added コールバック用）。
        メインスレッドから呼ばれる前提（dispatch_to_main 経由）。
        filter_match=True の場合はフィルタビューにも追加しリングバッファに保持する。
        """
        _log.info("add_comment: author=%s body=%.40s",
                  getattr(item, "author_name", "?"), getattr(item, "body", ""))
        row = self._make_row_data(item)
        header, body_text, author, bg_color, fg_color, profile_url = row

        # タブ1: 全メッセージ
        self._all_buffer.append(item)
        self._comment_view.add_row(
            header, body_text, author, bg_color, fg_color,
            profile_url=profile_url,
        )
        # i113: 全メッセージビューの行インデックスを記録（RR状態更新用）
        _seq_no = getattr(item, "seq_no", None)
        if _seq_no is not None and not getattr(item, "is_system_message", False):
            self._all_seq_to_abs_idx[_seq_no] = self._all_row_count
            self._all_base_headers[_seq_no] = header
        self._all_row_count += 1

        # タブ2: フィルタ一致（filter_match=True のみ）
        if getattr(item, "filter_match", False):
            self._filter_buffer.append(item)
            self._filter_view.add_row(
                header, body_text, author, bg_color, fg_color,
                profile_url=profile_url,
            )
            # i112: ベースヘッダーを記録（RRステータス更新時に参照）
            seq_no = getattr(item, "seq_no", None)
            if seq_no is not None:
                self._filter_base_headers[seq_no] = header
            # フィルタタブのラベルに件数を反映
            self._tab_widget.setTabText(1, f"フィルタ({len(self._filter_buffer)})")

        # ユーザー一覧タブを開いている場合はデバウンス更新
        if self._tab_widget.currentIndex() == 2:
            if not self._user_refresh_timer.isActive():
                self._user_refresh_timer.start()

    def set_conn_status(self, status: str, title: str = "") -> None:
        """接続状態を更新する（コントローラの on_conn_status コールバック用）。"""
        label = CONN_STATUS_LABELS.get(status, status)
        color = _STATUS_COLORS.get(status, "#888888")
        self._status_lbl.setText(label)
        self._status_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._title_lbl.setText(title)
        if status == "receiving" and self._session_start_time is None:
            self._session_start_time = datetime.now()
        if status in ("disconnected", "error"):
            self._session_start_time = None
        if title:
            self.setWindowTitle(f"RCommentHub - {title}")
        else:
            self.setWindowTitle("RCommentHub - コメントビュー")
        # i110: 受信中のみ切断ボタンを有効化
        if hasattr(self, "_btn_disconnect"):
            self._btn_disconnect.setEnabled(status == "receiving")

    def _on_disconnect(self) -> None:
        """i110: 切断ボタン押下 → コントローラに切断を要求する。"""
        self._btn_disconnect.setEnabled(False)
        try:
            self._ctrl.disconnect()
        except Exception as e:
            _log.warning("_on_disconnect: %s", e)

    # ─── ユーザー一覧タブ ──────────────────────────────────────────────────────

    def _refresh_user_list(self):
        """ユーザーテーブルを UserManager の現在状態で更新する"""
        if not hasattr(self, "_user_table"):
            return
        user_mgr = getattr(self._ctrl, "user_mgr", None)
        if user_mgr is None:
            return
        users = sorted(user_mgr.all_users(),
                       key=lambda r: r.comment_count, reverse=True)
        self._user_table.setRowCount(len(users))
        self._user_count_lbl.setText(f"{len(users)} 人")
        for row_idx, rec in enumerate(users):
            def _item(text, align=Qt.AlignmentFlag.AlignLeft):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                return it
            center = Qt.AlignmentFlag.AlignHCenter

            self._user_table.setItem(row_idx, 0, _item(rec.display_name))
            self._user_table.setItem(row_idx, 1, _item(rec.comment_count, center))
            self._user_table.setItem(row_idx, 2, _item(rec.elapsed_str))
            self._user_table.setItem(row_idx, 3, _item("✓" if rec.is_whitelist  else "", center))
            self._user_table.setItem(row_idx, 4, _item("✓" if rec.is_blacklist  else "", center))
            self._user_table.setItem(row_idx, 5, _item("✓" if rec.is_filter_target else "", center))
            # channel_id をヘッダーデータとして保持（右クリックメニュー用）
            self._user_table.item(row_idx, 0).setData(Qt.ItemDataRole.UserRole, rec.channel_id)

    def _user_context_menu(self, pos):
        """ユーザーテーブルの右クリックメニュー（WL/BL/対象フラグ操作）"""
        row = self._user_table.rowAt(pos.y())
        if row < 0:
            return
        name_item = self._user_table.item(row, 0)
        if name_item is None:
            return
        channel_id = name_item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        user_mgr = getattr(self._ctrl, "user_mgr", None)
        if user_mgr is None:
            return
        rec = user_mgr.get(channel_id)
        if rec is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1A1A2A; color: #CCCCCC; border: 1px solid #2A2A4A; }"
            "QMenu::item:selected { background: #2A2A4A; }"
        )
        wl_action = menu.addAction(f"ホワイトリスト {'OFF' if rec.is_whitelist else 'ON'}")
        bl_action = menu.addAction(f"ブラックリスト {'OFF' if rec.is_blacklist else 'ON'}")
        tgt_action = menu.addAction(f"フィルタ対象 {'OFF' if rec.is_filter_target else 'ON'}")

        action = menu.exec(self._user_table.viewport().mapToGlobal(pos))
        if action == wl_action:
            rec.is_whitelist = not rec.is_whitelist
        elif action == bl_action:
            rec.is_blacklist = not rec.is_blacklist
        elif action == tgt_action:
            rec.is_filter_target = not rec.is_filter_target
        else:
            return
        self._save_user_flags()
        self._refresh_user_list()

    def _on_user_cell_clicked(self, row: int, col: int) -> None:
        """i110: WL(3) / BL(4) / 対象(5) 列クリックでフラグをトグルする。"""
        if col not in (3, 4, 5):
            return
        name_item = self._user_table.item(row, 0)
        if name_item is None:
            return
        channel_id = name_item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        user_mgr = getattr(self._ctrl, "user_mgr", None)
        if user_mgr is None:
            return
        rec = user_mgr.get(channel_id)
        if rec is None:
            return
        if col == 3:
            rec.is_whitelist = not rec.is_whitelist
        elif col == 4:
            rec.is_blacklist = not rec.is_blacklist
        elif col == 5:
            rec.is_filter_target = not rec.is_filter_target
        self._save_user_flags()
        self._refresh_user_list()

    def _save_user_flags(self) -> None:
        """i110: UserManager のホワイト/ブラック/対象フラグを設定に保存する。"""
        user_mgr = getattr(self._ctrl, "user_mgr", None)
        if user_mgr is None:
            return
        flags = {
            rec.channel_id: {
                "display_name":     rec.display_name,
                "is_whitelist":     rec.is_whitelist,
                "is_blacklist":     rec.is_blacklist,
                "is_filter_target": rec.is_filter_target,
            }
            for rec in user_mgr.all_users()
        }
        self._sm.update({"user_flags": flags})

    # ─── フィルタ設定タブ ──────────────────────────────────────────────────────

    def _refresh_filter_list(self):
        """フィルタルールテーブルを FilterRuleManager の現在状態で更新する"""
        if not hasattr(self, "_rule_table"):
            return
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr is None:
            return
        rules = filter_mgr.rules
        # 現在の選択ルール ID を保持して復元する
        prev_id = self._current_rule_id
        self._rule_table.blockSignals(True)
        self._rule_table.setRowCount(len(rules))
        restore_row = -1
        for row_idx, rule in enumerate(rules):
            def _it(text, align=Qt.AlignmentFlag.AlignLeft):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                it.setData(Qt.ItemDataRole.UserRole, rule.rule_id)
                return it
            center = Qt.AlignmentFlag.AlignHCenter
            self._rule_table.setItem(row_idx, 0, _it("✓" if rule.enabled else "", center))
            self._rule_table.setItem(row_idx, 1, _it(rule.name))
            self._rule_table.setItem(row_idx, 2, _it(rule.target_text))
            self._rule_table.setItem(row_idx, 3, _it(rule.match_type, center))
            if rule.rule_id == prev_id:
                restore_row = row_idx
        self._rule_table.blockSignals(False)

        if restore_row >= 0:
            self._rule_table.selectRow(restore_row)
        elif len(rules) > 0:
            self._rule_table.selectRow(0)
        else:
            self._current_rule_id = None
            self._set_filter_form_enabled(False)

    def _on_rule_selected(self):
        """ルールテーブルの選択変更時: 編集フォームに選択ルールの内容をロードする"""
        rows = self._rule_table.selectedItems()
        if not rows:
            self._current_rule_id = None
            self._set_filter_form_enabled(False)
            return
        rule_id = rows[0].data(Qt.ItemDataRole.UserRole)
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr is None:
            return
        rule = filter_mgr.get_rule(rule_id)
        if rule is None:
            return
        self._current_rule_id = rule_id
        self._set_filter_form_enabled(True)
        self._load_rule_into_form(rule)

    def _load_rule_into_form(self, rule: FilterRule):
        """FilterRule の内容を編集フォームにセットする"""
        self._rule_enabled_cb.setChecked(rule.enabled)
        self._rule_name_edit.setText(rule.name)
        self._rule_text_edit.setText(rule.target_text)
        # i111: キーワード条件 (AND/OR)
        kw_cond = getattr(rule, 'keyword_condition', 'OR')
        self._rule_kw_cond_combo.setCurrentIndex(1 if kw_cond == "AND" else 0)
        idx = MATCH_TYPES.index(rule.match_type) if rule.match_type in MATCH_TYPES else 0
        self._rule_match_combo.setCurrentIndex(idx)
        self._rule_field_combo.setCurrentIndex(0 if rule.target_field == "本文" else 1)
        self._cb_kind_normal.setChecked(rule.kind_normal)
        self._cb_kind_sc.setChecked(rule.kind_superchat)
        self._cb_kind_other.setChecked(rule.kind_other)
        self._cb_role_owner.setChecked(rule.role_owner)
        self._cb_role_mod.setChecked(rule.role_mod)
        self._cb_role_member.setChecked(rule.role_member)
        self._cb_role_verified.setChecked(rule.role_verified)
        self._cb_excl_bl.setChecked(rule.exclude_blacklist)
        self._cb_filter_tgt.setChecked(rule.filter_target_only)

    def _apply_filter_edit(self):
        """編集フォームの内容を選択中のルールに反映し、設定に保存する"""
        if not self._current_rule_id:
            return
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr is None:
            return
        rule = filter_mgr.get_rule(self._current_rule_id)
        if rule is None:
            return
        rule.enabled           = self._rule_enabled_cb.isChecked()
        rule.name              = self._rule_name_edit.text().strip()
        rule.target_text       = self._rule_text_edit.text()
        # i111: キーワード条件 (AND/OR)
        rule.keyword_condition = "AND" if self._rule_kw_cond_combo.currentIndex() == 1 else "OR"
        rule.match_type        = self._rule_match_combo.currentText()
        rule.target_field     = self._rule_field_combo.currentText()
        rule.kind_normal      = self._cb_kind_normal.isChecked()
        rule.kind_superchat   = self._cb_kind_sc.isChecked()
        rule.kind_other       = self._cb_kind_other.isChecked()
        rule.role_owner       = self._cb_role_owner.isChecked()
        rule.role_mod         = self._cb_role_mod.isChecked()
        rule.role_member      = self._cb_role_member.isChecked()
        rule.role_verified    = self._cb_role_verified.isChecked()
        rule.exclude_blacklist  = self._cb_excl_bl.isChecked()
        rule.filter_target_only = self._cb_filter_tgt.isChecked()
        self._save_filter_rules()
        self._refresh_filter_list()

    def _add_filter_rule(self):
        """フィルタルールを追加して編集フォームを新ルールにフォーカスする"""
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr is None:
            return
        new_rule = filter_mgr.add_rule()
        self._current_rule_id = new_rule.rule_id
        self._save_filter_rules()
        self._refresh_filter_list()

    def _delete_filter_rule(self):
        """選択中のフィルタルールを削除する"""
        if not self._current_rule_id:
            return
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr is None:
            return
        filter_mgr.remove_rule(self._current_rule_id)
        self._current_rule_id = None
        self._save_filter_rules()
        self._refresh_filter_list()

    def _move_filter_rule_up(self):
        """選択中のルールを1つ上へ移動する"""
        if not self._current_rule_id:
            return
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr:
            filter_mgr.move_up(self._current_rule_id)
            self._save_filter_rules()
            self._refresh_filter_list()

    def _move_filter_rule_down(self):
        """選択中のルールを1つ下へ移動する"""
        if not self._current_rule_id:
            return
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr:
            filter_mgr.move_down(self._current_rule_id)
            self._save_filter_rules()
            self._refresh_filter_list()

    def _save_filter_rules(self):
        """FilterRuleManager の現在状態を settings_mgr に即時保存する"""
        filter_mgr = getattr(self._ctrl, "filter_mgr", None)
        if filter_mgr is not None:
            self._sm.update({"filter_rules": filter_mgr.to_list()})

    def _set_filter_form_enabled(self, enabled: bool):
        """編集フォームの全コントロールの有効/無効を切り替える"""
        for w in (self._rule_enabled_cb, self._rule_name_edit,
                  self._rule_text_edit, self._rule_kw_cond_combo,  # i111
                  self._rule_match_combo,
                  self._rule_field_combo, self._cb_kind_normal,
                  self._cb_kind_sc, self._cb_kind_other,
                  self._cb_role_owner, self._cb_role_mod,
                  self._cb_role_member, self._cb_role_verified,
                  self._cb_excl_bl, self._cb_filter_tgt):
            w.setEnabled(enabled)

    # ─── 位置保存・復元 ────────────────────────────────────────────────────────

    def _restore_pos(self):
        """保存済み位置・サイズを復元し、現在の画面に収まるよう補正する。"""
        saved_x = self._sm.get("cw_x", None)
        saved_y = self._sm.get("cw_y", None)
        w = self.width()
        h = self.height()

        target_x = int(saved_x) if saved_x is not None else self.x()
        target_y = int(saved_y) if saved_y is not None else self.y()

        center = QPoint(target_x + w // 2, target_y + h // 2)
        screen = QGuiApplication.screenAt(center)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()

        new_w = min(w, avail.width())
        new_h = min(h, avail.height())
        if new_w != w or new_h != h:
            self.resize(new_w, new_h)
            w, h = new_w, new_h

        margin = self._STATUS_BAR_H + self._EDGE_SIZE
        new_x = max(avail.left() - w + margin,
                    min(target_x, avail.right() - margin))
        new_y = max(avail.top(),
                    min(target_y, avail.bottom() - margin))

        self.move(new_x, new_y)

    def _flush_geometry(self):
        """デバウンスタイマーで遅延呼び出し: 位置・サイズを一括保存する。"""
        if not self._init_complete:
            return
        self._sm.update({
            "cw_x": self.x(), "cw_y": self.y(),
            "cw_width": self.width(), "cw_height": self.height(),
        })

    # ─── Win32 補助 ────────────────────────────────────────────────────────────

    def _apply_topmost(self, topmost: bool):
        """Win32 SetWindowPos でトップモスト状態を切り替える。"""
        if not self.isVisible():
            return
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_uint,
            ]
            HWND_TOPMOST   = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE     = 0x0001
            SWP_NOMOVE     = 0x0002
            SWP_NOACTIVATE = 0x0010
            hwnd    = int(self.winId())
            z_order = HWND_TOPMOST if topmost else HWND_NOTOPMOST
            user32.SetWindowPos(hwnd, z_order, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _apply_dwm_borderless(self):
        """Windows DWM レベルで外周枠・角丸・影を除去する。"""
        try:
            hwnd = int(self.winId())
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmSetWindowAttribute(
                hwnd, 33,
                ctypes.byref(ctypes.c_uint(1)),
                ctypes.sizeof(ctypes.c_uint),
            )
            dwmapi.DwmSetWindowAttribute(
                hwnd, 35,
                ctypes.byref(ctypes.c_uint(0xFFFFFFFE)),
                ctypes.sizeof(ctypes.c_uint),
            )
        except Exception:
            pass

    # ─── ドラッグ判定 (Method B: 手動 self.move()) ────────────────────────────

    def _install_drag_filters_recursive(self, widget):
        """widget とその全子孫 QWidget に eventFilter を再帰的に登録する。

        ルール:
          - QScrollBar: スクロール操作優先のためスキップ
          - QAbstractScrollArea: 本体ではなく viewport() に登録
            （viewport は子として再帰処理されるので本体はスキップ）
          - それ以外の QWidget: 直接登録
        """
        if isinstance(widget, QScrollBar):
            return  # スクロールバーはスキップ
        if not isinstance(widget, QAbstractScrollArea):
            widget.installEventFilter(self)
            _log.debug("drag filter installed: %s (id=%s)",
                       type(widget).__name__, id(widget))
        # 子を再帰処理（QAbstractScrollArea の子には viewport や scrollbar が含まれる）
        for child in widget.children():
            if isinstance(child, QWidget):
                self._install_drag_filters_recursive(child)

    def _in_combobox(self, widget) -> bool:
        """widget またはその祖先（self まで）に QComboBox があれば True。
        編集可能な QComboBox の内部 QLineEdit も含めて除外するために使用。
        """
        w = widget
        while w is not None and w is not self:
            if isinstance(w, QComboBox):
                return True
            w = w.parent()
        return False

    def eventFilter(self, watched, event):
        """
        central widget 配下の全 QWidget にインストールしたイベントフィルタ。

        動作仕様:
          - MouseButtonPress : グローバル座標を記録（リサイズ領域・QComboBox は除外）、伝播
          - MouseMove (ドラッグ未開始): 閾値超過でドラッグ開始、self.move() 開始、消費
          - MouseMove (ドラッグ中): self.move() でウィンドウ追従、消費
          - MouseButtonRelease (ドラッグ中): 状態リセット、消費
          - MouseButtonRelease (クリック): 状態リセット、伝播 → 通常クリック成立

        QScrollBar は登録対象外のためスクロール操作に影響しない。
        QComboBox はドロップダウン操作優先のためドラッグ追跡を開始しない。
        閾値: _DRAG_THRESHOLD px (マンハッタン距離)
        """
        ev_type = event.type()
        if ev_type == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                # QComboBox（または内部 QLineEdit 等）はドラッグ対象外
                if self._in_combobox(watched):
                    return False
                # リサイズ領域ではドラッグ追跡を開始しない
                local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
                lx, ly = local_pos.x(), local_pos.y()
                e = self._EDGE_SIZE
                in_resize = (lx < e or lx >= self.width() - e
                             or ly < e or ly >= self.height() - e)
                if not in_resize:
                    self._drag_start_pos = event.globalPosition().toPoint()
                    _log.debug("drag: press on %s at %s",
                               type(watched).__name__, self._drag_start_pos)
            return False  # 常に伝播

        elif ev_type == QEvent.Type.MouseMove:
            if self._dragging:
                cursor_pos = event.globalPosition().toPoint()
                self.move(cursor_pos + self._drag_win_offset)
                return True  # ドラッグ中は消費
            elif (self._drag_start_pos is not None
                  and event.buttons() & Qt.MouseButton.LeftButton):
                delta = event.globalPosition().toPoint() - self._drag_start_pos
                if delta.manhattanLength() >= self._DRAG_THRESHOLD:
                    cursor_pos = event.globalPosition().toPoint()
                    self._drag_win_offset = self.pos() - cursor_pos
                    self._dragging = True
                    _log.debug("drag: start (threshold exceeded on %s)",
                               type(watched).__name__)
                    self.move(cursor_pos + self._drag_win_offset)
                    return True
            return False

        elif ev_type == QEvent.Type.MouseButtonRelease:
            if self._dragging:
                _log.debug("drag: end (drag completed) on %s",
                           type(watched).__name__)
                self._dragging = False
                self._drag_start_pos = None
                self._drag_win_offset = None
                return True  # ドラッグ完了 release は消費
            if self._drag_start_pos is not None:
                _log.debug("drag: release without drag (click) on %s",
                           type(watched).__name__)
            self._drag_start_pos = None
            return False  # クリック release は伝播

        return super().eventFilter(watched, event)

    # ─── nativeEvent（frameless リサイズ・ステータスバードラッグ）──────────────

    def nativeEvent(self, event_type, message):
        """WM_NCHITTEST をインターセプトして frameless リサイズを実現する。

        全辺・四隅リサイズ（i146 実装継承）。
        コメントビュー・フィルタビュー・タブページでのドラッグ移動は
        eventFilter + 手動 self.move() で実現（閾値判定によりクリックと両立）。

        リサイズ判定（端から _EDGE_SIZE px 以内）:
          HTTOPLEFT(13) / HTTOPRIGHT(14) / HTBOTTOMLEFT(16) / HTBOTTOMRIGHT(17)
          HTLEFT(10) / HTRIGHT(11) / HTTOP(12) / HTBOTTOM(15)

        ドラッグ移動（HTCAPTION=2）:
          - ステータスバー域（ボタン上を除く）のみ HTCAPTION を返す（即時移動）
        """
        if event_type == b'windows_generic_MSG':
            msg = ctypes.wintypes.MSG.from_address(int(message))
            WM_NCHITTEST       = 0x0084
            WM_NCLBUTTONDBLCLK = 0x00A3

            if msg.message == WM_NCHITTEST:
                lp = int(msg.lParam)
                sx = ctypes.c_short(lp & 0xFFFF).value
                sy = ctypes.c_short((lp >> 16) & 0xFFFF).value
                pos = self.mapFromGlobal(QPoint(sx, sy))
                x, y = pos.x(), pos.y()
                w, h = self.width(), self.height()
                e = self._EDGE_SIZE

                # 四隅・各辺のリサイズ判定（リサイズ領域が最優先）
                on_left   = x < e
                on_right  = x >= w - e
                on_top    = y < e
                on_bottom = y >= h - e

                if on_top    and on_left:  return True, 13  # HTTOPLEFT
                if on_top    and on_right: return True, 14  # HTTOPRIGHT
                if on_bottom and on_left:  return True, 16  # HTBOTTOMLEFT
                if on_bottom and on_right: return True, 17  # HTBOTTOMRIGHT
                if on_left:                return True, 10  # HTLEFT
                if on_right:               return True, 11  # HTRIGHT
                if on_top:                 return True, 12  # HTTOP
                if on_bottom:              return True, 15  # HTBOTTOM

                # ステータスバー域 → HTCAPTION（ボタン上は Qt に渡す）
                if y <= self._STATUS_BAR_H:
                    child = self.childAt(pos)
                    if isinstance(child, QPushButton):
                        return super().nativeEvent(event_type, message)
                    return True, 2  # HTCAPTION

            if msg.message == WM_NCLBUTTONDBLCLK:
                return True, 0

        return super().nativeEvent(event_type, message)

    # ─── Qt イベントハンドラ ───────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_dwm_borderless()
        if self._current_topmost is not None:
            self._apply_topmost(self._current_topmost)
        if not self._pos_restored:
            self._pos_restored = True
            QTimer.singleShot(0, self._restore_pos)

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._init_complete:
            return
        self._geom_save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._init_complete:
            self._geom_save_timer.start()

    def closeEvent(self, event):
        """Alt+F4 等のシステム close もアプリ全体終了へ。"""
        event.ignore()
        self._on_quit()
