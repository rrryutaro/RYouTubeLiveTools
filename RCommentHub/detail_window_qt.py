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

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QPlainTextEdit, QSplitter, QHeaderView, QLineEdit,
    QFrame, QSizePolicy,
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
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._row_items.append(item)

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

        # 最下部へスクロール
        self._table.scrollToBottom()

        # 統計更新
        total = self._table.rowCount()
        self._hdr_count_lbl.setText(f"受信: {total}件")

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
        if current_row < 0 or current_row >= len(self._row_items):
            self._detail_text.clear()
            return
        item = self._row_items[current_row]
        self._show_detail(item)

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

    def closeEvent(self, event):
        """X ボタンで閉じると非表示になるだけ（アプリは終了しない）。"""
        event.ignore()
        self.hide()
