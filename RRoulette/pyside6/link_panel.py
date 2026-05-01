"""
link_panel.py — 連携メッセージパネル (Phase 2 — i109)

責務:
  - RCommentHub から受け取った連携メッセージを表示・保持する
  - 受信メッセージを簡易分析し spin / ticket_add / unknown を判定する (i109)
  - 自動解析 ON/OFF / 自動実行 ON/OFF を切り替える (i109)
  - 手動実行ボタンで spin / チケット追加を要求する (i109)

設計方針:
  - 既存パネル群 (TicketPanel 等) の実装パターンに準拠
  - _PanelDragBar / _PanelGrip を使用
  - 連携メッセージは QTableWidget で表示
  - 解析結果 (ParsedLinkAction) を各行の UserRole データとして保持
  - spin_requested / ticket_add_requested シグナルで MainWindow へ通知
"""

from __future__ import annotations

import datetime
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QWidget, QCheckBox,
    QComboBox, QMenu, QMessageBox,
)

from design_models import DesignSettings
from panel_widgets import _PanelDragBar, _PanelGrip, install_panel_context_menu, apply_transparent_to_widget_tree
from link_message_analyzer import (
    ParsedLinkAction, analyze_link_message, action_type_label,
    EFFECT_NONE,
)

_log = logging.getLogger(__name__)

# 処理状態
_STATUS_RECEIVED   = "received"
_STATUS_FAILED     = "failed"
_STATUS_EXECUTED   = "実行済"
_STATUS_REGISTERED = "登録済"
_STATUS_IGNORED    = "無視"
_STATUS_QUEUED     = "キュー待ち"       # i114: キューに追加済み
_STATUS_QUEUE_FULL = "未実行: キュー満杯"  # i114: キュー上限超過

# テーブル列定義
_COL_TIME      = 0
_COL_PLATFORM  = 1
_COL_PROFILE   = 2
_COL_AUTHOR    = 3
_COL_TEXT      = 4
_COL_ACTION    = 5   # 判定 (spin / 追加 / 不明)
_COL_CANDIDATE = 6   # 候補 (チケット名 / 理由)
_COL_STATUS    = 7
_COL_COUNT     = 8

_COL_HEADERS = ["時刻", "platform", "接続", "投稿者", "テキスト", "判定", "候補", "状態"]

_DEFAULT_MAX_HOLD = 200

# 判定ラベルの色
_ACTION_COLORS = {
    "spin":       "#5bc85b",
    "ticket_add": "#5b9ec8",
    "unknown":    "#888888",
}

_MANUAL_REASON = "右クリックメニューで手動判定"


class LinkPanel(QFrame):
    """連携メッセージパネル (Phase 2: 受信・分析・実行)。

    Signals:
        geometry_changed(): パネルの位置・サイズが変わった
        spin_requested(): spin 実行要求（MainWindow が受け取り _start_spin() を呼ぶ）
        ticket_add_requested(name, issuer, effect, qty, effect_type, effect_params):
            チケット追加要求（MainWindow が受け取り TicketPanel.add_ticket_from_link() を呼ぶ）
        auto_analyze_changed(enabled): 自動解析 ON/OFF 変更通知
        auto_execute_changed(enabled): 自動実行 ON/OFF 変更通知
    """

    geometry_changed   = Signal()
    spin_requested     = Signal(int)    # row: スピン要求行番号 (i114)
    queue_clear_requested = Signal()    # i114: キュー消去要求
    ticket_add_requested = Signal(str, str, str, int, str, dict)  # name, issuer, effect, qty, effect_type, effect_params
    auto_analyze_changed = Signal(bool)
    auto_execute_changed = Signal(bool)

    _MIN_W = 520
    _MIN_H = 200

    def __init__(
        self,
        design: DesignSettings,
        *,
        max_hold: int = _DEFAULT_MAX_HOLD,
        show_time: bool = False,
        auto_analyze: bool = True,
        auto_execute: bool = False,
        on_drag_bar_changed=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.pinned_front = False
        self._floating = False
        self._design = design
        self._transparent = False
        self._max_hold = max_hold
        self._show_time = show_time
        self._auto_analyze = auto_analyze
        self._auto_execute = auto_execute
        self._on_drag_bar_changed_cb = on_drag_bar_changed
        # i111: 連携パネルフィルタ状態
        self._filter_mode: str = "すべて"

        self.setMinimumSize(self._MIN_W, self._MIN_H)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._apply_style()
        self._build_ui()
        self._apply_column_visibility()

    # ================================================================
    #  スタイル
    # ================================================================

    def _apply_style(self) -> None:
        d = self._design
        if getattr(self, '_transparent', False):
            self.setStyleSheet(
                f"LinkPanel {{ background: transparent; "
                f"border: 1px solid {d.separator}; border-radius: 4px; }}"
            )
        else:
            self.setStyleSheet(
                f"LinkPanel {{ background: {d.panel}; "
                f"border: 1px solid {d.separator}; border-radius: 4px; }}"
            )

    def set_transparent(self, enabled: bool):
        """パネル背景の透過モードを切り替える（実験的）。"""
        self._transparent = enabled
        self._apply_style()
        apply_transparent_to_widget_tree(self, enabled)

    # ================================================================
    #  UI 構築
    # ================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 4)
        root.setSpacing(0)

        # ドラッグバー
        self._drag_bar = _PanelDragBar(self, self._design, parent=self)
        root.addWidget(self._drag_bar)
        install_panel_context_menu(
            self, self._drag_bar,
            on_drag_bar_changed=self._on_drag_bar_visibility,
        )

        # ヘッダ行: タイトル + クリアボタン
        d = self._design
        hdr = QWidget()
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(8, 2, 8, 2)
        hdr_layout.setSpacing(4)

        self._title_label = QLabel("連携パネル")
        self._title_label.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {d.text};")
        hdr_layout.addWidget(self._title_label, 1)

        self._count_label = QLabel("0 件")
        self._count_label.setFont(QFont("Meiryo", 8))
        self._count_label.setStyleSheet(f"color: {d.subtext if hasattr(d, 'subtext') else d.text};")
        hdr_layout.addWidget(self._count_label)

        _btn_style = (
            f"QPushButton {{ background: {d.separator}; color: {d.text}; "
            f"border: none; border-radius: 2px; padding: 2px 6px; font-size: 8pt; }}"
            f"QPushButton:hover {{ background: #884444; color: #fff; }}"
        )
        self._btn_clear = QPushButton("クリア")
        self._btn_clear.setFont(QFont("Meiryo", 8))
        self._btn_clear.setStyleSheet(_btn_style)
        self._btn_clear.setToolTip("受信した連携メッセージをすべてクリアします")
        self._btn_clear.clicked.connect(self._on_clear)
        hdr_layout.addWidget(self._btn_clear)

        root.addWidget(hdr)

        # ── コントロール行 (i109): 自動解析 / 自動実行 / 手動実行 ──
        ctrl = QWidget()
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(8, 2, 8, 2)
        ctrl_layout.setSpacing(8)

        _chk_style = f"QCheckBox {{ color: {d.text}; font-size: 8pt; }}"

        self._chk_auto_analyze = QCheckBox("自動解析")
        self._chk_auto_analyze.setFont(QFont("Meiryo", 8))
        self._chk_auto_analyze.setStyleSheet(_chk_style)
        self._chk_auto_analyze.setChecked(self._auto_analyze)
        self._chk_auto_analyze.setToolTip("受信メッセージを自動的に解析します")
        self._chk_auto_analyze.toggled.connect(self._on_auto_analyze_toggled)
        ctrl_layout.addWidget(self._chk_auto_analyze)

        self._chk_auto_execute = QCheckBox("自動実行")
        self._chk_auto_execute.setFont(QFont("Meiryo", 8))
        self._chk_auto_execute.setStyleSheet(_chk_style)
        self._chk_auto_execute.setChecked(self._auto_execute)
        self._chk_auto_execute.setToolTip(
            "解析結果が明確な場合に自動実行します（初期OFF推奨）"
        )
        self._chk_auto_execute.toggled.connect(self._on_auto_execute_toggled)
        ctrl_layout.addWidget(self._chk_auto_execute)

        ctrl_layout.addStretch(1)

        _exec_btn_style = (
            f"QPushButton {{ background: {d.accent}; color: {d.text}; "
            f"border: none; border-radius: 2px; padding: 2px 8px; font-size: 8pt; }}"
            f"QPushButton:hover {{ background: {d.separator}; }}"
            f"QPushButton:disabled {{ background: {d.separator}; color: #666; }}"
        )
        self._btn_analyze = QPushButton("再解析")
        self._btn_analyze.setFont(QFont("Meiryo", 8))
        self._btn_analyze.setStyleSheet(_exec_btn_style)
        self._btn_analyze.setToolTip("選択中のメッセージを再解析します")
        self._btn_analyze.setEnabled(False)
        self._btn_analyze.clicked.connect(self._on_reanalyze)
        ctrl_layout.addWidget(self._btn_analyze)

        # i111: 個別削除ボタン
        _del_btn_style = (
            f"QPushButton {{ background: #663333; color: {d.text}; "
            f"border: none; border-radius: 2px; padding: 2px 8px; font-size: 8pt; }}"
            f"QPushButton:hover {{ background: #884444; color: #fff; }}"
            f"QPushButton:disabled {{ background: {d.separator}; color: #666; }}"
        )
        self._btn_delete = QPushButton("削除")
        self._btn_delete.setFont(QFont("Meiryo", 8))
        self._btn_delete.setStyleSheet(_del_btn_style)
        self._btn_delete.setToolTip("選択中のメッセージを削除します")
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(self._on_delete_selected)
        ctrl_layout.addWidget(self._btn_delete)

        self._btn_execute = QPushButton("実行")
        self._btn_execute.setFont(QFont("Meiryo", 8))
        self._btn_execute.setStyleSheet(_exec_btn_style)
        self._btn_execute.setToolTip(
            "選択中のメッセージの解析結果を実行します\n"
            "spin→スピン開始 / ticket_add→チケット追加"
        )
        self._btn_execute.setEnabled(False)
        self._btn_execute.clicked.connect(self._on_execute_selected)
        ctrl_layout.addWidget(self._btn_execute)

        root.addWidget(ctrl)

        # i111: フィルタ・一括操作バー
        flt = QWidget()
        flt_layout = QHBoxLayout(flt)
        flt_layout.setContentsMargins(8, 2, 8, 2)
        flt_layout.setSpacing(6)

        _flt_lbl = QLabel("表示:")
        _flt_lbl.setFont(QFont("Meiryo", 8))
        _flt_lbl.setStyleSheet(f"color: {d.subtext if hasattr(d, 'subtext') else d.text};")
        flt_layout.addWidget(_flt_lbl)

        self._filter_combo = QComboBox()
        self._filter_combo.setFont(QFont("Meiryo", 8))
        self._filter_combo.addItems([
            "すべて", "未処理", "適用済み", "未適用", "判定不能", "spin", "ticket_add"
        ])
        self._filter_combo.setToolTip(
            "すべて: 全件表示\n"
            "未処理: 受信済みで未実行\n"
            "適用済み: 実行済み・登録済み\n"
            "未適用: 解析済みだが未実行\n"
            "判定不能: 解析不可・要確認"
        )
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        flt_layout.addWidget(self._filter_combo)
        flt_layout.addStretch(1)

        self._btn_bulk_apply = QPushButton("一括適用")
        self._btn_bulk_apply.setFont(QFont("Meiryo", 8))
        self._btn_bulk_apply.setStyleSheet(_exec_btn_style)
        self._btn_bulk_apply.setToolTip(
            "表示中の未適用メッセージを一括適用します\n"
            "unknown/要確認は除外。spin は最初の1件のみ。"
        )
        self._btn_bulk_apply.clicked.connect(self._on_bulk_apply)
        flt_layout.addWidget(self._btn_bulk_apply)

        self._btn_bulk_delete = QPushButton("一括削除")
        self._btn_bulk_delete.setFont(QFont("Meiryo", 8))
        self._btn_bulk_delete.setStyleSheet(_del_btn_style)
        self._btn_bulk_delete.setToolTip("表示中のメッセージを一括削除します（取り消し不可）")
        self._btn_bulk_delete.clicked.connect(self._on_bulk_delete)
        flt_layout.addWidget(self._btn_bulk_delete)

        # i114: キューステータス表示 + 消去ボタン
        _sep = QLabel("|")
        _sep.setFont(QFont("Meiryo", 8))
        _sep.setStyleSheet(f"color: {d.separator if hasattr(d, 'separator') else '#555'};")
        flt_layout.addWidget(_sep)

        self._queue_label = QLabel("キュー: 0")
        self._queue_label.setFont(QFont("Meiryo", 8))
        self._queue_label.setStyleSheet(
            f"color: {d.subtext if hasattr(d, 'subtext') else d.text};"
        )
        self._queue_label.setToolTip("連携スピン待機キューの件数（最大10件）")
        flt_layout.addWidget(self._queue_label)

        self._btn_queue_clear = QPushButton("キュー消去")
        self._btn_queue_clear.setFont(QFont("Meiryo", 8))
        self._btn_queue_clear.setStyleSheet(_del_btn_style)
        self._btn_queue_clear.setToolTip("待機中の連携スピン要求をすべて取り消します")
        self._btn_queue_clear.setEnabled(False)
        self._btn_queue_clear.clicked.connect(lambda: self.queue_clear_requested.emit())
        flt_layout.addWidget(self._btn_queue_clear)

        root.addWidget(flt)

        # テーブル
        self._table = QTableWidget(0, _COL_COUNT)
        self._table.setHorizontalHeaderLabels(_COL_HEADERS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(False)
        # 列幅設定
        self._table.setColumnWidth(_COL_TIME,      90)
        self._table.setColumnWidth(_COL_PLATFORM,  70)
        self._table.setColumnWidth(_COL_PROFILE,   80)
        self._table.setColumnWidth(_COL_AUTHOR,    80)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_TEXT, QHeaderView.ResizeMode.Stretch
        )
        self._table.setColumnWidth(_COL_ACTION,    46)
        self._table.setColumnWidth(_COL_CANDIDATE, 100)
        self._table.setColumnWidth(_COL_STATUS,    60)
        self._apply_table_style()
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        # i111: 右クリックメニュー（削除）
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)
        root.addWidget(self._table, 1)

        # リサイズグリップ
        self._grip = _PanelGrip(self, self._design, min_w=self._MIN_W, min_h=self._MIN_H)

    def _apply_table_style(self) -> None:
        d = self._design
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {d.panel}; color: {d.text}; "
            f"  gridline-color: {d.separator}; border: none; font-size: 8pt; }}"
            f"QTableWidget::item:selected {{ background: {d.accent}; color: {d.text}; }}"
            f"QHeaderView::section {{ background: {d.separator}; color: {d.text}; "
            f"  padding: 2px 4px; font-size: 8pt; border: none; }}"
            f"QTableWidget::item:alternate {{ background: {d.separator}; }}"
        )

    # ================================================================
    #  公開API — 設定適用
    # ================================================================

    def set_auto_analyze(self, enabled: bool) -> None:
        """自動解析 ON/OFF を設定する（外部からの設定適用用）。"""
        self._auto_analyze = enabled
        self._chk_auto_analyze.setChecked(enabled)

    def set_auto_execute(self, enabled: bool) -> None:
        """自動実行 ON/OFF を設定する（外部からの設定適用用）。"""
        self._auto_execute = enabled
        self._chk_auto_execute.setChecked(enabled)

    # ================================================================
    #  公開API — メッセージ追加
    # ================================================================

    def add_message(self, data: dict, status: str = _STATUS_RECEIVED) -> None:
        """連携メッセージを先頭行に追加する。

        最大保持件数を超えた場合、末尾（最古）行を削除する。
        自動解析 ON 時は受信直後に解析を実行する。

        Args:
            data:   受信した JSON dict（外部送信仕様に準拠）
            status: 処理状態（"received" / "failed"）
        """
        recv_time          = datetime.datetime.now().strftime("%H:%M:%S")
        platform           = str(data.get("platform", ""))
        profile            = str(data.get("profile_name", ""))
        author             = str(data.get("author_name", ""))
        author_channel_id  = str(data.get("author_channel_id", ""))  # i110
        text               = str(data.get("comment_text", ""))

        # 解析実行
        parsed: ParsedLinkAction | None = None
        action_lbl = ""
        candidate_lbl = ""

        if self._auto_analyze and status == _STATUS_RECEIVED and text:
            parsed = analyze_link_message(text)
            action_lbl = action_type_label(parsed.action_type)
            candidate_lbl = _candidate_text(parsed)

        self._table.insertRow(0)
        for col, val in [
            (_COL_TIME,      recv_time),
            (_COL_PLATFORM,  platform),
            (_COL_PROFILE,   profile),
            (_COL_AUTHOR,    author),
            (_COL_TEXT,      text),
            (_COL_ACTION,    action_lbl),
            (_COL_CANDIDATE, candidate_lbl),
            (_COL_STATUS,    status),
        ]:
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col == _COL_STATUS and status == _STATUS_FAILED:
                item.setForeground(QColor("#ff6666"))
            if col == _COL_ACTION and parsed is not None:
                color = _ACTION_COLORS.get(parsed.action_type, "#888888")
                item.setForeground(QColor(color))
            self._table.setItem(0, col, item)

        # ParsedLinkAction を行データとして保持
        if parsed is not None:
            self._table.item(0, _COL_TEXT).setData(Qt.ItemDataRole.UserRole, parsed)

        # i110: author_channel_id を _COL_AUTHOR セルの UserRole に保存
        if author_channel_id:
            author_item = self._table.item(0, _COL_AUTHOR)
            if author_item:
                author_item.setData(Qt.ItemDataRole.UserRole, author_channel_id)

        self._table.setRowHeight(0, 20)

        # 保持件数超過時: 末尾行を削除（最古）
        while self._table.rowCount() > self._max_hold:
            self._table.removeRow(self._table.rowCount() - 1)

        self._update_count_label()

        # i111: 現在のフィルタに合わせて新規行の表示/非表示を判定
        if self._filter_mode != "すべて":
            if not self._row_matches_filter(0, self._filter_mode):
                self._table.setRowHidden(0, True)

        # 自動実行
        if parsed is not None and self._auto_execute and status == _STATUS_RECEIVED:
            self._try_auto_execute(parsed, row=0)

    def add_failed_message(self, data: dict, error: str = "") -> None:
        """受信失敗を記録する。data に error_text を付加して add_message を呼ぶ。"""
        data = dict(data)
        if error:
            data["comment_text"] = f"[ERROR: {error}]"
        self.add_message(data, status=_STATUS_FAILED)

    def clear_messages(self) -> None:
        """全メッセージをクリアする。"""
        self._table.setRowCount(0)
        self._update_count_label()

    def message_count(self) -> int:
        return self._table.rowCount()

    # ================================================================
    #  最大保持件数・列表示の更新
    # ================================================================

    def set_max_hold(self, n: int) -> None:
        self._max_hold = max(1, n)
        while self._table.rowCount() > self._max_hold:
            self._table.removeRow(self._table.rowCount() - 1)
        self._update_count_label()

    def set_show_time(self, show: bool) -> None:
        """時刻列の表示/非表示を切り替える。"""
        self._show_time = show
        self._table.setColumnHidden(_COL_TIME, not show)

    def _apply_column_visibility(self) -> None:
        self._table.setColumnHidden(_COL_TIME,     not self._show_time)
        self._table.setColumnHidden(_COL_PLATFORM, True)
        self._table.setColumnHidden(_COL_PROFILE,  True)

    # ================================================================
    #  内部: 自動実行
    # ================================================================

    def _try_auto_execute(self, parsed: ParsedLinkAction, row: int) -> None:
        """自動実行条件を満たす場合にシグナルを発行する。"""
        if parsed.action_type == "spin" and not parsed.needs_review and parsed.confidence >= 0.7:
            # i114: 行ステータス更新は MainWindow 側（キュー管理）に委譲
            self.spin_requested.emit(row)
            _log.info("[LinkPanel] 自動実行: spin")

        elif (parsed.action_type == "ticket_add"
              and not parsed.needs_review
              and parsed.confidence >= 0.7
              and parsed.ticket_name
              and parsed.effect_type != EFFECT_NONE):
            self._emit_ticket_add(parsed, row=row)
            self._update_row_status(row, _STATUS_REGISTERED)
            _log.info("[LinkPanel] 自動実行: ticket_add %s", parsed.ticket_name)

    def _emit_ticket_add(self, parsed: ParsedLinkAction, row: int = -1) -> None:
        """ticket_add_requested シグナルを発行する。

        i110: row を受け取り、_COL_AUTHOR から発行者名を取得して issuer に設定する。
        i110: effect は raw_text をそのまま使用し、定型文プレフィックスを付けない。
        """
        name   = parsed.ticket_name or "連携チケット"
        # i110: 発行者をテーブルの著者列から取得（表示名が空の場合はchannel_idをフォールバック）
        issuer = ""
        if row >= 0:
            author_item = self._table.item(row, _COL_AUTHOR)
            if author_item:
                issuer = author_item.text().strip()
                if not issuer:
                    channel_id = author_item.data(Qt.ItemDataRole.UserRole)
                    if channel_id:
                        issuer = str(channel_id)
        # i110: raw_text をそのままメモに使用（定型文プレフィックスなし）
        effect = parsed.raw_text
        qty    = 1
        effect_type   = parsed.effect_type or EFFECT_NONE
        effect_params = dict(parsed.effect_params)
        self.ticket_add_requested.emit(name, issuer, effect, qty, effect_type, effect_params)

    def _update_row_status(self, row: int, status: str) -> None:
        item = self._table.item(row, _COL_STATUS)
        if item is not None:
            item.setText(status)
        # i111: 状態変化後にフィルタ再適用（例: 適用済みが非表示になるフィルタ）
        if self._filter_mode != "すべて":
            self._table.setRowHidden(row, not self._row_matches_filter(row, self._filter_mode))

    # i114: MainWindow からのステータス更新・キュー表示 -------------------

    def set_row_status(self, row: int, status: str) -> None:
        """MainWindow からキュー管理に基づいて行ステータスを更新する (i114)。"""
        self._update_row_status(row, status)

    def update_queue_display(self, queue_len: int) -> None:
        """キュー件数ラベルと消去ボタンを更新する (i114)。"""
        self._queue_label.setText(f"キュー: {queue_len}")
        self._btn_queue_clear.setEnabled(queue_len > 0)

    # ================================================================
    #  内部: UI操作
    # ================================================================

    def _update_count_label(self) -> None:
        cnt = self._table.rowCount()
        self._count_label.setText(f"{cnt} 件")

    def _on_clear(self) -> None:
        self.clear_messages()
        self._btn_analyze.setEnabled(False)
        self._btn_execute.setEnabled(False)

    def _on_drag_bar_visibility(self, visible: bool) -> None:
        if self._on_drag_bar_changed_cb:
            self._on_drag_bar_changed_cb(visible)

    def _on_auto_analyze_toggled(self, checked: bool) -> None:
        self._auto_analyze = checked
        self.auto_analyze_changed.emit(checked)

    def _on_auto_execute_toggled(self, checked: bool) -> None:
        self._auto_execute = checked
        self.auto_execute_changed.emit(checked)

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        has_sel = bool(rows)
        self._btn_analyze.setEnabled(has_sel)
        self._btn_delete.setEnabled(has_sel)  # i111
        if has_sel:
            row = rows[0].row()
            parsed = self._get_parsed(row)
            can_exec = (parsed is not None and parsed.action_type != "unknown")
            self._btn_execute.setEnabled(can_exec)
        else:
            self._btn_execute.setEnabled(False)

    def _get_parsed(self, row: int) -> ParsedLinkAction | None:
        """行から ParsedLinkAction を取得する。"""
        item = self._table.item(row, _COL_TEXT)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_reanalyze(self) -> None:
        """選択行を再解析する。"""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        text_item = self._table.item(row, _COL_TEXT)
        if text_item is None:
            return
        text = text_item.text()
        if not text:
            return

        parsed = analyze_link_message(text)
        self._apply_parsed_to_row(row, parsed)

    def _on_execute_selected(self) -> None:
        """選択行の解析結果を手動実行する。"""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        parsed = self._get_parsed(row)

        if parsed is None:
            # 未解析なら解析してから実行
            text_item = self._table.item(row, _COL_TEXT)
            if text_item is None:
                return
            parsed = analyze_link_message(text_item.text())
            self._apply_parsed_to_row(row, parsed)

        if parsed.action_type == "spin":
            # i114: 行ステータス更新は MainWindow 側（キュー管理）に委譲
            self.spin_requested.emit(row)
            _log.info("[LinkPanel] 手動実行: spin")

        elif parsed.action_type == "ticket_add":
            self._emit_ticket_add(parsed, row=row)
            self._update_row_status(row, _STATUS_REGISTERED)
            _log.info("[LinkPanel] 手動実行: ticket_add %s", parsed.ticket_name)

    # ================================================================
    #  i111: フィルタ・削除・一括操作
    # ================================================================

    def _on_filter_changed(self, mode: str) -> None:
        """フィルタコンボ変更 → 行の表示/非表示を更新する。"""
        self._filter_mode = mode
        self._apply_filter()

    def _apply_filter(self) -> None:
        """現在の _filter_mode に従って全行の表示/非表示を更新する。"""
        mode = self._filter_mode
        for row in range(self._table.rowCount()):
            self._table.setRowHidden(row, not self._row_matches_filter(row, mode))

    def _row_matches_filter(self, row: int, mode: str) -> bool:
        """指定行が現在のフィルタ条件に一致するか判定する。"""
        if mode == "すべて":
            return True
        status_item = self._table.item(row, _COL_STATUS)
        status = status_item.text() if status_item else ""
        parsed = self._get_parsed(row)
        action_type = parsed.action_type if parsed else "unknown"

        if mode == "未処理":
            return status == _STATUS_RECEIVED
        if mode == "適用済み":
            return status in (_STATUS_EXECUTED, _STATUS_REGISTERED)
        if mode == "未適用":
            return status == _STATUS_RECEIVED and action_type != "unknown"
        if mode == "判定不能":
            return parsed is None or action_type == "unknown"
        if mode == "spin":
            return action_type == "spin"
        if mode == "ticket_add":
            return action_type == "ticket_add"
        return True

    def _on_delete_selected(self) -> None:
        """選択中の行を削除する。"""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        for model_idx in sorted(rows, key=lambda x: x.row(), reverse=True):
            self._table.removeRow(model_idx.row())
        self._btn_delete.setEnabled(False)
        self._btn_analyze.setEnabled(False)
        self._btn_execute.setEnabled(False)
        self._update_count_label()

    def _on_table_context_menu(self, pos) -> None:
        """テーブルの右クリックメニューを表示する。"""
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        self._table.selectRow(row)
        menu = QMenu(self)
        verdict_menu = menu.addMenu("判定を設定")
        act_set_spin = verdict_menu.addAction("spin")
        act_set_ticket = verdict_menu.addAction("チケット追加")
        act_set_unknown = verdict_menu.addAction("不明")
        menu.addSeparator()
        act_reanalyze = menu.addAction("再解析")
        act_delete = menu.addAction("削除")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == act_set_spin:
            self._set_manual_verdict(row, "spin")
        elif action == act_set_ticket:
            self._set_manual_verdict(row, "ticket_add")
        elif action == act_set_unknown:
            self._set_manual_verdict(row, "unknown")
        elif action == act_reanalyze:
            self._reanalyze_row(row)
        elif action == act_delete:
            self._table.removeRow(row)
            self._btn_delete.setEnabled(False)
            self._btn_analyze.setEnabled(False)
            self._btn_execute.setEnabled(False)
            self._update_count_label()

    def _reanalyze_row(self, row: int) -> None:
        """指定行を再解析する。コンテキストメニュー用。"""
        text_item = self._table.item(row, _COL_TEXT)
        if text_item is None:
            return
        text = text_item.text()
        if not text:
            return
        self._apply_parsed_to_row(row, analyze_link_message(text))

    def _set_manual_verdict(self, row: int, action_type: str) -> None:
        """右クリックメニューから行の判定を手動設定する。"""
        text_item = self._table.item(row, _COL_TEXT)
        if text_item is None:
            return
        raw_text = text_item.text()
        if action_type == "spin":
            parsed = ParsedLinkAction(
                action_type="spin",
                confidence=1.0,
                reason=_MANUAL_REASON,
                raw_text=raw_text,
                needs_review=False,
            )
        elif action_type == "ticket_add":
            parsed = ParsedLinkAction(
                action_type="ticket_add",
                confidence=1.0,
                reason=_MANUAL_REASON,
                raw_text=raw_text,
                ticket_name="連携チケット",
                ticket_description=f"連携メッセージから手動作成: {raw_text}",
                effect_type=EFFECT_NONE,
                effect_params={},
                needs_review=False,
            )
        else:
            parsed = ParsedLinkAction(
                action_type="unknown",
                confidence=0.0,
                reason=_MANUAL_REASON,
                raw_text=raw_text,
            )
        self._apply_parsed_to_row(row, parsed)

    def _apply_parsed_to_row(self, row: int, parsed: ParsedLinkAction) -> None:
        """解析/手動判定の結果をテーブル行とボタン状態へ反映する。"""
        text_item = self._table.item(row, _COL_TEXT)
        if text_item is None:
            return
        text_item.setData(Qt.ItemDataRole.UserRole, parsed)

        action_lbl = action_type_label(parsed.action_type)
        cand_lbl = _candidate_text(parsed)
        color = _ACTION_COLORS.get(parsed.action_type, "#888888")

        action_item = self._table.item(row, _COL_ACTION)
        if action_item:
            action_item.setText(action_lbl)
            action_item.setForeground(QColor(color))

        cand_item = self._table.item(row, _COL_CANDIDATE)
        if cand_item:
            cand_item.setText(cand_lbl)

        self._btn_analyze.setEnabled(True)
        self._btn_delete.setEnabled(True)
        self._btn_execute.setEnabled(parsed.action_type != "unknown")
        if self._filter_mode != "すべて":
            self._table.setRowHidden(row, not self._row_matches_filter(row, self._filter_mode))

    def _on_bulk_apply(self) -> None:
        """表示中のメッセージを一括適用する。

        除外条件:
          - 適用済み (実行済/登録済)
          - action_type == "unknown"
          - needs_review == True
          - confidence < 0.7
          - spin は最初の1件のみ実行
        """
        visible_rows = [r for r in range(self._table.rowCount())
                        if not self._table.isRowHidden(r)]
        if not visible_rows:
            return

        spin_applied = False
        apply_count  = 0
        skip_count   = 0

        for row in visible_rows:
            status_item = self._table.item(row, _COL_STATUS)
            status = status_item.text() if status_item else ""
            if status in (_STATUS_EXECUTED, _STATUS_REGISTERED):
                skip_count += 1
                continue

            parsed = self._get_parsed(row)
            if parsed is None or parsed.action_type == "unknown" or parsed.needs_review:
                skip_count += 1
                continue

            if parsed.action_type == "spin":
                if not spin_applied and parsed.confidence >= 0.7:
                    # i114: 行ステータス更新は MainWindow 側（キュー管理）に委譲
                    self.spin_requested.emit(row)
                    spin_applied = True
                    apply_count += 1
                    _log.info("[LinkPanel] 一括適用: spin")
                else:
                    skip_count += 1

            elif parsed.action_type == "ticket_add":
                if (parsed.confidence >= 0.7 and parsed.ticket_name
                        and parsed.effect_type != EFFECT_NONE):
                    self._emit_ticket_add(parsed, row=row)
                    self._update_row_status(row, _STATUS_REGISTERED)
                    apply_count += 1
                    _log.info("[LinkPanel] 一括適用: ticket_add %s", parsed.ticket_name)
                else:
                    skip_count += 1

        _log.info("[LinkPanel] 一括適用完了: %d 件適用, %d 件スキップ", apply_count, skip_count)

    def _on_bulk_delete(self) -> None:
        """表示中のメッセージを一括削除する（確認ダイアログあり）。"""
        visible_rows = [r for r in range(self._table.rowCount())
                        if not self._table.isRowHidden(r)]
        count = len(visible_rows)
        if count == 0:
            return

        reply = QMessageBox.question(
            self,
            "一括削除の確認",
            f"表示中の {count} 件を削除します。\n"
            f"取り消しはできません。実行しますか？\n"
            f"（作成済みチケット・実行済みspinは取り消しません）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # index がずれないよう下から削除
        for row in sorted(visible_rows, reverse=True):
            self._table.removeRow(row)

        self._btn_delete.setEnabled(False)
        self._btn_analyze.setEnabled(False)
        self._btn_execute.setEnabled(False)
        self._update_count_label()

    # ================================================================
    #  イベント — geometry_changed
    # ================================================================

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_grip"):
            self._grip.reposition()
        self.geometry_changed.emit()


# ================================================================
#  ヘルパー
# ================================================================

def _candidate_text(parsed: ParsedLinkAction) -> str:
    """解析結果から「候補」列の表示文字列を生成する。"""
    if parsed.action_type == "spin":
        return "スピン"
    if parsed.action_type == "ticket_add":
        parts = []
        if parsed.ticket_name:
            parts.append(parsed.ticket_name)
        if parsed.needs_review:
            parts.append("要確認")
        return " ".join(parts) if parts else "追加"
    return parsed.reason[:20] if parsed.reason else ""
