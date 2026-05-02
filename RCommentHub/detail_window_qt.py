"""
RCommentHub — Qt版 DetailWindow（詳細/管理ウィンドウ）

v0.3.2 Tk版 detail_window.py の役割を PySide6 QMainWindow で再実装。

役割（v0.3.2 相当）:
  コメント一覧（全件）/ 詳細パネル / ログエリアを提供する補助管理画面。
  コメントビューが主画面。本ウィンドウは X で閉じてもアプリは終了しない。

構成:
  ─ ヘッダー（接続状態・タイトル・統計・ボタン）
  ─ ツールバー（接続・停止・状態表示）
  ─ 中央スプリッター（水平）
      左: フィルタ/管理パネル（文字列絞り込み）
      中: コメント一覧（QTableWidget）
      右: 詳細パネル（選択コメントの全フィールド）
  ─ ログエリア（下部 QPlainTextEdit）
"""

import datetime
import json
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QPlainTextEdit, QSplitter, QHeaderView, QLineEdit,
    QFrame, QSizePolicy, QListWidget,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

from constants import (
    CONN_STATUS_LABELS, CONN_STATUS_COLORS,
    LIST_COLUMNS, ROW_COLORS,
)
from debug_sender_qt import DebugSenderWindowQt

# 行カラー（種別・権限による色分け）
_ROW_COLORS = {
    "owner":       (QColor("#2A3A6A"), QColor("#FFD700")),
    "moderator":   (QColor("#1E3A3A"), QColor("#80FFCC")),
    "member":      (QColor("#1E2A3A"), QColor("#80CCFF")),
    "superchat":   (QColor("#3A2A10"), QColor("#FFB347")),
    "supersticker":(QColor("#2A2A10"), QColor("#FFD080")),
    "deleted":     (QColor("#3A1A1A"), QColor("#FF8080")),
    "banned":      (QColor("#4A0000"), QColor("#FF6060")),
    "matched":     (QColor("#1A3A1A"), QColor("#80FF80")),
    "default":     (QColor("#1A1A2E"), QColor("#C8C8D8")),
    "alt":         (QColor("#1E1E36"), QColor("#C8C8D8")),
}

# コメント一覧カラム定義（id, 表示名, 幅）
_COLUMNS = [(col_id, heading, width) for col_id, heading, width, _ in LIST_COLUMNS]

_STATUS_COLORS = {
    "disconnected": "#888888",
    "connecting":   "#FFCC44",
    "receiving":    "#44FF44",
    "reconnecting": "#FF8844",
    "error":        "#FF4444",
    "debug":        "#AA88FF",
}


class DetailWindowQt(QMainWindow):
    """
    Qt版 詳細/管理ウィンドウ（補助画面）。
    X ボタンで閉じると非表示になるだけでアプリは終了しない。
    """

    def __init__(self, controller, settings_mgr, parent=None, *,
                 open_connect_cb=None,
                 open_comment_win_cb=None,
                 open_settings_cb=None):
        super().__init__(parent)
        self._ctrl               = controller
        self._sm                 = settings_mgr
        self._open_connect       = open_connect_cb      or (lambda: None)
        self._open_comment_win   = open_comment_win_cb  or (lambda: None)
        self._open_settings      = open_settings_cb     or (lambda: None)

        # 行インデックス → item（詳細表示用）
        self._row_items: list = []

        # 過去ログ閲覧モード
        self._past_log_mode: bool = False
        self._past_sessions: list = []          # [(folder, dir_path, meta), ...]
        self._past_log_records: dict = {}       # {row_index: record_dict}

        self.setWindowTitle("RCommentHub - 詳細")
        self.resize(
            int(self._sm.get("dw_width",  1200)),
            int(self._sm.get("dw_height",  700)),
        )

        # 位置保存デバウンス
        self._geom_save_timer = QTimer(self)
        self._geom_save_timer.setSingleShot(True)
        self._geom_save_timer.setInterval(400)
        self._geom_save_timer.timeout.connect(self._flush_geometry)

        self._build_ui()
        self._restore_pos()

        # ── デバッグ送信ウィンドウ（DEBUG ON 時に開く）────────────────────────
        self._debug_sender_win = DebugSenderWindowQt(
            parent=None,
            controller=self._ctrl,
            settings_mgr=self._sm,
        )

        # コントローラからのコールバック登録
        self._ctrl.on_comment_added(self._on_comment_added)
        self._ctrl.on_conn_status(self._on_conn_status)
        self._ctrl.on_log_message(self._on_log_message)
        self._ctrl.on_debug_mode(self._on_debug_mode_changed)

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #0D0D1A;
                color: #C8C8D8;
            }
            QTableWidget {
                background: #1A1A2E;
                gridline-color: #2A2A4A;
                selection-background-color: #3A5A8A;
            }
            QTableWidget::item { padding: 2px 4px; }
            QHeaderView::section {
                background: #0A0A1E;
                color: #E0E0F0;
                border: 1px solid #2A2A4A;
                padding: 3px;
                font-weight: bold;
            }
            QPlainTextEdit {
                background: #0A0A14;
                color: #AAAAAA;
                border: none;
            }
            QPushButton {
                background: #1E3A4A; color: #C9D1E0;
                border: none; padding: 3px 10px;
            }
            QPushButton:hover  { background: #2E5068; }
            QPushButton:pressed { background: #1A2A3A; }
            QLineEdit {
                background: #1A1A2E; color: #C8C8D8;
                border: 1px solid #2A2A4A; padding: 3px;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── ヘッダー ─────────────────────────────────────────────────────────
        root.addWidget(self._build_header())

        # ── ツールバー ────────────────────────────────────────────────────────
        root.addWidget(self._build_toolbar())

        # ── メイン垂直スプリッター（上段: 一覧+詳細 / 下段: ログ） ───────────
        v_split = QSplitter(Qt.Orientation.Vertical)

        # 中央水平スプリッター（左: フィルタ / 中: 一覧 / 右: 詳細）
        h_split = QSplitter(Qt.Orientation.Horizontal)
        h_split.addWidget(self._build_filter_panel())
        h_split.addWidget(self._build_list_area())
        h_split.addWidget(self._build_detail_area())
        h_split.setSizes([180, 620, 300])

        v_split.addWidget(h_split)
        v_split.addWidget(self._build_log_area())
        v_split.setSizes([560, 120])

        root.addWidget(v_split)

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet("background: #0A0A1E;")
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(12)

        self._hdr_conn_lbl = QLabel("■ 未接続")
        self._hdr_conn_lbl.setStyleSheet(f"color: {_STATUS_COLORS['disconnected']}; font-weight: bold;")
        lay.addWidget(self._hdr_conn_lbl)

        self._hdr_title_lbl = QLabel("— 配信なし —")
        f = QFont()
        f.setBold(True)
        f.setPointSize(10)
        self._hdr_title_lbl.setFont(f)
        self._hdr_title_lbl.setStyleSheet("color: #E0E0F0;")
        self._hdr_title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._hdr_title_lbl)

        self._hdr_count_lbl = QLabel("受信: 0件")
        self._hdr_count_lbl.setStyleSheet("color: #888888; font-size: 9pt;")
        lay.addWidget(self._hdr_count_lbl)

        btn_cw = QPushButton("コメントビュー")
        btn_cw.setStyleSheet("background:#2A3A2A; color:#80FF80;")
        btn_cw.clicked.connect(self._open_comment_win)
        lay.addWidget(btn_cw)

        btn_set = QPushButton("設定")
        btn_set.clicked.connect(self._open_settings)
        lay.addWidget(btn_set)

        return hdr

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(34)
        bar.setStyleSheet("background: #141428;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(6)

        self._btn_connect = QPushButton("▶ 接続")
        self._btn_connect.setStyleSheet("background:#2A4A2A; color:#AAFFAA;")
        self._btn_connect.clicked.connect(self._open_connect)
        lay.addWidget(self._btn_connect)

        self._btn_stop = QPushButton("■ 停止")
        self._btn_stop.setStyleSheet("background:#4A2A2A; color:#FFFFFF;")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._ctrl.disconnect)
        lay.addWidget(self._btn_stop)

        self._btn_debug = QPushButton("🐛 DEBUG OFF")
        self._btn_debug.setStyleSheet(
            "QPushButton { background:#1E1E2E; color:#888888; }"
            "QPushButton:hover { background:#2A2A3A; }"
        )
        self._btn_debug.clicked.connect(self._ctrl.toggle_debug_mode)
        lay.addWidget(self._btn_debug)

        self._toolbar_status_lbl = QLabel("")
        self._toolbar_status_lbl.setStyleSheet("color: #888888; font-size: 9pt;")
        lay.addWidget(self._toolbar_status_lbl)

        lay.addStretch()
        return bar

    def _build_filter_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(160)
        panel.setMaximumWidth(260)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lbl = QLabel("フィルタ / 管理")
        lbl.setStyleSheet("color: #8888AA; font-weight: bold;")
        lay.addWidget(lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2A2A4A;")
        lay.addWidget(sep)

        lbl2 = QLabel("文字列絞り込み:")
        lbl2.setStyleSheet("color: #8888AA; font-size: 9pt;")
        lay.addWidget(lbl2)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("投稿者名・本文を絞り込み")
        self._filter_edit.textChanged.connect(self._apply_list_filter)
        lay.addWidget(self._filter_edit)

        btn_clear = QPushButton("フィルタ解除")
        btn_clear.clicked.connect(lambda: self._filter_edit.clear())
        lay.addWidget(btn_clear)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #2A2A4A;")
        lay.addWidget(sep2)

        # ── 過去ログ閲覧トグル ──
        self._btn_past_log = QPushButton("📋 過去ログ閲覧")
        self._btn_past_log.clicked.connect(self._toggle_past_log_mode)
        lay.addWidget(self._btn_past_log)

        # ── セッション選択パネル（トグル時のみ表示）──
        self._past_log_panel = QWidget()
        past_lay = QVBoxLayout(self._past_log_panel)
        past_lay.setContentsMargins(0, 2, 0, 0)
        past_lay.setSpacing(4)

        self._session_list = QListWidget()
        self._session_list.setStyleSheet(
            "QListWidget { background:#1A1A2E; color:#CCCCCC; border:1px solid #2A2A4A; }"
            "QListWidget::item:selected { background:#3A3A6A; }"
        )
        self._session_list.setMaximumHeight(150)
        self._session_list.currentRowChanged.connect(self._on_past_session_select)
        past_lay.addWidget(self._session_list)

        btn_refresh = QPushButton("一覧を更新")
        btn_refresh.clicked.connect(self._refresh_past_sessions)
        past_lay.addWidget(btn_refresh)

        self._session_info_lbl = QLabel("")
        self._session_info_lbl.setStyleSheet("color: #8888AA; font-size: 8pt;")
        self._session_info_lbl.setWordWrap(True)
        past_lay.addWidget(self._session_info_lbl)

        lay.addWidget(self._past_log_panel)
        self._past_log_panel.setVisible(False)

        lay.addStretch()
        return panel

    def _build_list_area(self) -> QWidget:
        frame = QWidget()
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        hdr_row = QHBoxLayout()
        lbl = QLabel("コメント一覧")
        lbl.setStyleSheet("color: #8888AA; font-weight: bold; padding: 4px 6px;")
        hdr_row.addWidget(lbl)
        self._list_mode_lbl = QLabel("【現在セッション】")
        self._list_mode_lbl.setStyleSheet("color: #88FF88; font-weight: bold;")
        hdr_row.addWidget(self._list_mode_lbl)
        hdr_row.addStretch()
        lay.addLayout(hdr_row)

        self._table = QTableWidget()
        col_ids = [c[0] for c in _COLUMNS]
        col_labels = [c[1] for c in _COLUMNS]
        col_widths  = [c[2] for c in _COLUMNS]

        self._table.setColumnCount(len(col_ids))
        self._table.setHorizontalHeaderLabels(col_labels)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.setAlternatingRowColors(False)

        for i, w in enumerate(col_widths):
            self._table.setColumnWidth(i, w)
        # 本文（index 5）と投稿者名（index 4）を伸長
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch)

        self._table.currentCellChanged.connect(self._on_row_selected)
        lay.addWidget(self._table)
        return frame

    def _build_detail_area(self) -> QWidget:
        frame = QWidget()
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        lbl = QLabel("詳細")
        lbl.setStyleSheet("color: #8888AA; font-weight: bold;")
        lay.addWidget(lbl)

        self._detail_text = QPlainTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("Courier New", 9))
        self._detail_text.setStyleSheet("background: #141428; color: #C8C8D8;")
        lay.addWidget(self._detail_text)
        return frame

    def _build_log_area(self) -> QWidget:
        frame = QWidget()
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(2)

        lbl = QLabel("ログ")
        lbl.setStyleSheet("color: #8888AA; font-weight: bold;")
        lay.addWidget(lbl)

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(500)
        self._log_text.setFont(QFont("Courier New", 9))
        self._log_text.setStyleSheet("background: #0A0A14; color: #AAAAAA;")
        lay.addWidget(self._log_text)
        return frame

    # ─── 公開 API ──────────────────────────────────────────────────────────────

    def open(self):
        """詳細ウィンドウを前面表示する（X で閉じても再度開ける）。"""
        self.show()
        self.raise_()
        self.activateWindow()

    # ─── コントローラ コールバック ─────────────────────────────────────────────

    def _on_comment_added(self, item):
        """コントローラからのコメント追加 → 一覧に追加する。"""
        self._row_items.append(item)
        if self._past_log_mode:
            return
        self._append_item_to_table(item)
        self._table.scrollToBottom()
        self._hdr_count_lbl.setText(f"受信: {len(self._row_items)}件")

    def _append_item_to_table(self, item):
        """CommentItem を一覧テーブルの末尾に追加する。"""
        row = self._table.rowCount()
        self._table.insertRow(row)
        vals = [
            str(getattr(item, "seq_no", row + 1)),
            item.recv_time_str() if hasattr(item, "recv_time_str") else "",
            item.post_time_str() if hasattr(item, "post_time_str") else "",
            item.kind_label()    if hasattr(item, "kind_label")    else "",
            getattr(item, "author_name", ""),
            item.body_short()    if hasattr(item, "body_short")    else getattr(item, "body", ""),
            getattr(item, "channel_id", ""),
            item.roles_str()     if hasattr(item, "roles_str")     else "",
            getattr(item, "msg_id", ""),
            item.status_label()  if hasattr(item, "status_label")  else "",
        ]
        tag = item.row_tag() if hasattr(item, "row_tag") else "default"
        bg, fg = _ROW_COLORS.get(tag, _ROW_COLORS["default"])
        for col, val in enumerate(vals):
            cell = QTableWidgetItem(val)
            cell.setBackground(bg)
            cell.setForeground(fg)
            self._table.setItem(row, col, cell)

    def _on_conn_status(self, status: str):
        """接続状態変化 → ヘッダー更新。"""
        label = CONN_STATUS_LABELS.get(status, status)
        color = _STATUS_COLORS.get(status, "#888888")
        self._hdr_conn_lbl.setText(f"■ {label}")
        self._hdr_conn_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

        # 停止ボタンの有効化
        active = status in ("receiving", "connecting", "reconnecting", "debug")
        self._btn_stop.setEnabled(active)

    def _on_debug_mode_changed(self, debug_mode: bool, open_sender: bool):
        """デバッグモード切り替え → DEBUG ボタンの表示更新、送信画面の開閉。"""
        if debug_mode:
            self._btn_debug.setText("🐛 DEBUG ON")
            self._btn_debug.setStyleSheet(
                "QPushButton { background:#3A2A00; color:#FF8C00; }"
                "QPushButton:hover { background:#4A3A00; }"
            )
            if open_sender:
                self._debug_sender_win.open()
        else:
            self._btn_debug.setText("🐛 DEBUG OFF")
            self._btn_debug.setStyleSheet(
                "QPushButton { background:#1E1E2E; color:#888888; }"
                "QPushButton:hover { background:#2A2A3A; }"
            )
            self._debug_sender_win.hide()

    def _on_log_message(self, msg: str):
        """コントローラからのログメッセージ → ログエリアへ追記。"""
        ts   = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._log_text.appendPlainText(line)

    # ─── 行選択 → 詳細パネル更新 ──────────────────────────────────────────────

    def _on_row_selected(self, current_row: int, *_):
        if current_row < 0:
            self._detail_text.clear()
            return
        if self._past_log_mode:
            rec = self._past_log_records.get(current_row)
            if rec:
                self._show_past_log_detail(rec)
            return
        if current_row >= len(self._row_items):
            self._detail_text.clear()
            return
        self._show_detail(self._row_items[current_row])

    def _show_detail(self, item):
        lines = []
        lines.append("── コメント詳細 " + "─" * 40)
        for attr, label in [
            ("seq_no",      "No"),
            ("author_name", "投稿者名"),
            ("channel_id",  "チャンネルID"),
            ("msg_id",      "メッセージID"),
        ]:
            lines.append(f"  {label}: {getattr(item, attr, '—')}")

        if hasattr(item, "recv_time_str"):
            lines.append(f"  受信時刻: {item.recv_time_str()}")
        if hasattr(item, "post_time_str"):
            lines.append(f"  投稿時刻: {item.post_time_str()}")
        if hasattr(item, "kind_label"):
            lines.append(f"  種別: {item.kind_label()}")
        if hasattr(item, "roles_str"):
            lines.append(f"  権限: {item.roles_str()}")
        if hasattr(item, "status_label"):
            lines.append(f"  状態: {item.status_label()}")

        lines.append("")
        lines.append("── 本文 " + "─" * 45)
        lines.append(getattr(item, "body", "") or "（本文なし）")

        self._detail_text.setPlainText("\n".join(lines))

    # ─── 一覧フィルタ（文字列絞り込み） ────────────────────────────────────────

    def _apply_list_filter(self, text: str):
        """投稿者名・本文に対して部分一致で行の表示/非表示を切り替える。"""
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            if not text:
                self._table.setRowHidden(row, False)
                continue
            author = (self._table.item(row, 4) or QTableWidgetItem("")).text().lower()
            body   = (self._table.item(row, 5) or QTableWidgetItem("")).text().lower()
            match  = text in author or text in body
            self._table.setRowHidden(row, not match)

    # ─── 位置・サイズ保存・復元 ────────────────────────────────────────────────

    def _restore_pos(self):
        x = self._sm.get("dw_x", None)
        y = self._sm.get("dw_y", None)
        if x is not None and y is not None:
            self.move(int(x), int(y))

    def _flush_geometry(self):
        self._sm.update({
            "dw_x": self.x(), "dw_y": self.y(),
            "dw_width": self.width(), "dw_height": self.height(),
        })

    def moveEvent(self, event):
        super().moveEvent(event)
        self._geom_save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._geom_save_timer.start()

    # ─── 過去ログ閲覧 ─────────────────────────────────────────────────────────

    def _toggle_past_log_mode(self):
        if self._past_log_mode:
            self._exit_past_log_mode()
        else:
            self._enter_past_log_mode()

    def _enter_past_log_mode(self):
        self._past_log_mode = True
        self._btn_past_log.setText("▶ ライブモードに戻る")
        self._btn_past_log.setStyleSheet("background:#3A1A3A; color:#FF88FF;")
        self._past_log_panel.setVisible(True)
        self._list_mode_lbl.setText("【過去ログ閲覧 — 読み取り専用】")
        self._list_mode_lbl.setStyleSheet("color: #FF8888; font-weight: bold;")
        self._table.setRowCount(0)
        self._past_log_records.clear()
        self._detail_text.clear()
        self._refresh_past_sessions()

    def _exit_past_log_mode(self):
        self._past_log_mode = False
        self._past_log_records.clear()
        self._btn_past_log.setText("📋 過去ログ閲覧")
        self._btn_past_log.setStyleSheet("")
        self._past_log_panel.setVisible(False)
        self._list_mode_lbl.setText("【現在セッション】")
        self._list_mode_lbl.setStyleSheet("color: #88FF88; font-weight: bold;")
        self._detail_text.clear()
        self._restore_live_table()

    def _restore_live_table(self):
        """ライブモードへ戻る際、蓄積済みの _row_items をテーブルに再描画する。"""
        self._table.setRowCount(0)
        for item in self._row_items:
            self._append_item_to_table(item)
        self._hdr_count_lbl.setText(f"受信: {len(self._row_items)}件")
        self._table.scrollToBottom()

    def _refresh_past_sessions(self):
        """セッションログ一覧を読み込んでリストに表示する。"""
        base_dir = getattr(self._ctrl, "_base_dir", "")
        sessions_dir = os.path.join(base_dir, "logs", "sessions")
        self._past_sessions = []
        self._session_list.blockSignals(True)
        self._session_list.clear()
        self._session_info_lbl.setText("")
        try:
            if not os.path.isdir(sessions_dir):
                self._session_list.addItem("（セッションなし）")
                return
            entries = sorted(os.listdir(sessions_dir), reverse=True)
            for folder in entries:
                d = os.path.join(sessions_dir, folder)
                meta_path = os.path.join(d, "session_meta.json")
                if not os.path.isfile(meta_path):
                    continue
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    continue
                start = meta.get("start_time", "")
                try:
                    dt = datetime.datetime.fromisoformat(start)
                    date_str = dt.strftime("%Y/%m/%d %H:%M")
                except Exception:
                    date_str = start[:16] if start else folder
                title = meta.get("title") or meta.get("video_id", "")
                short = (title[:18] + "…") if len(title) > 18 else title
                self._past_sessions.append((folder, d, meta))
                self._session_list.addItem(f"{date_str}  {short}")
            if not self._past_sessions:
                self._session_list.addItem("（セッションなし）")
        except Exception as e:
            self._session_list.addItem(f"[エラー] {e}")
        finally:
            self._session_list.blockSignals(False)

    def _on_past_session_select(self, idx: int):
        if idx < 0 or idx >= len(self._past_sessions):
            return
        folder, session_dir, meta = self._past_sessions[idx]
        start = meta.get("start_time", "")
        try:
            dt = datetime.datetime.fromisoformat(start)
            start_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            start_str = start[:16]
        self._session_info_lbl.setText(
            f"{start_str}\n{meta.get('title', '—')}\n"
            f"video_id: {meta.get('video_id', '—')}"
        )
        self._load_session_comments(session_dir, meta)

    def _load_session_comments(self, session_dir: str, meta: dict):
        """セッションの comments.jsonl を読み込んでテーブルに展開する。"""
        self._table.setRowCount(0)
        self._past_log_records.clear()
        self._detail_text.clear()

        jsonl_path = os.path.join(session_dir, "comments.jsonl")
        if not os.path.isfile(jsonl_path):
            self._on_log_message(f"[過去ログ] comments.jsonl が見つかりません: {session_dir}")
            return

        count = 0
        try:
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue

                    recv_raw = rec.get("received_at_local", "")
                    post_raw = rec.get("published_at", "")
                    def _fmt_time(s):
                        try:
                            return datetime.datetime.fromisoformat(s).strftime("%H:%M:%S")
                        except Exception:
                            return s[:8] if s else ""

                    flags = []
                    if rec.get("is_chat_owner"):     flags.append("O")
                    if rec.get("is_chat_moderator"):  flags.append("M")
                    if rec.get("is_chat_sponsor"):    flags.append("S")
                    if rec.get("is_verified"):        flags.append("V")

                    body_raw = rec.get("message_text_raw", "") or ""
                    body_s = (body_raw[:48] + "…") if len(body_raw) > 48 else body_raw

                    vals = [
                        str(count + 1),
                        _fmt_time(recv_raw),
                        _fmt_time(post_raw),
                        rec.get("message_type", ""),
                        rec.get("author_display_name_raw", ""),
                        body_s,
                        rec.get("author_channel_id", ""),
                        "/".join(flags),
                        rec.get("message_id", ""),
                        "保存済",
                    ]
                    row = self._table.rowCount()
                    self._table.insertRow(row)
                    msg_type = rec.get("message_type", "")
                    if msg_type == "superChatEvent":
                        bg, fg = _ROW_COLORS["superchat"]
                    elif msg_type == "superStickerEvent":
                        bg, fg = _ROW_COLORS["supersticker"]
                    elif rec.get("is_chat_owner"):
                        bg, fg = _ROW_COLORS["owner"]
                    elif rec.get("is_chat_moderator"):
                        bg, fg = _ROW_COLORS["moderator"]
                    else:
                        bg, fg = _ROW_COLORS["alt"] if count % 2 else _ROW_COLORS["default"]
                    for col, val in enumerate(vals):
                        cell = QTableWidgetItem(val)
                        cell.setBackground(bg)
                        cell.setForeground(fg)
                        self._table.setItem(row, col, cell)

                    self._past_log_records[count] = rec
                    count += 1
                    if count >= 5000:
                        break
        except Exception as e:
            self._on_log_message(f"[過去ログ] 読み込みエラー: {e}")
            return

        self._hdr_count_lbl.setText(f"ログ: {count}件")
        self._on_log_message(f"[過去ログ] {count}件 読み込みました")

    def _show_past_log_detail(self, rec: dict):
        """過去ログレコードの詳細をパネルに表示する。"""
        lines = ["▼ 保存済みログ — 読み取り専用 ▼", "─" * 44, ""]
        lines.append("【A. 基本情報】")
        for k, label in [
            ("message_id",    "message_id"),
            ("message_type",  "message_type"),
            ("published_at",  "published_at"),
            ("received_at_local", "received_at_local"),
            ("video_id",      "video_id"),
            ("live_chat_id",  "live_chat_id"),
            ("input_source",  "input_source"),
        ]:
            lines.append(f"  {label}: {rec.get(k, '—')}")
        lines.append("")
        lines.append("【B. 投稿者情報】")
        for k, label in [
            ("author_display_name_raw", "表示名"),
            ("author_display_name_tts", "TTS名"),
            ("author_channel_id",       "channel_id"),
            ("author_channel_url",      "channel_url"),
        ]:
            lines.append(f"  {label}: {rec.get(k, '—')}")
        lines.append(f"  owner={rec.get('is_chat_owner',False)}  "
                     f"mod={rec.get('is_chat_moderator',False)}  "
                     f"member={rec.get('is_chat_sponsor',False)}  "
                     f"verified={rec.get('is_verified',False)}")
        lines.append("")
        lines.append("【C. メッセージ内容】")
        lines.append(f"  message_text_raw:     {rec.get('message_text_raw', '—')}")
        lines.append(f"  message_text_display: {rec.get('message_text_display', '—')}")
        lines.append(f"  filter_match: {rec.get('filter_match', '—')}")
        lines.append(f"  filter_rule_ids: {rec.get('filter_rule_ids', '—')}")
        lines.append("")
        lines.append("【D. Raw JSON】")
        try:
            lines.append(json.dumps(rec, ensure_ascii=False, indent=2))
        except Exception:
            lines.append(str(rec))
        self._detail_text.setPlainText("\n".join(lines))

    # ─── 位置・サイズ保存・復元 ────────────────────────────────────────────────

    def closeEvent(self, event):
        """X ボタンで閉じると非表示になるだけ（アプリは終了しない）。"""
        event.ignore()
        self.hide()
