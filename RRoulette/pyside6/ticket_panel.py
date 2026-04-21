"""
ticket_panel.py — チケット管理パネル (v0.5.2 改善第2段)

責務:
  - 保有チケットの追加・個数管理（折りたたみ式フォーム・テンプレート）
  - 使用 / 削除の履歴管理（ドブクリックで復活）
  - チケット名 / 発行者 / 効果ごとの集計（主軸 / 内訳軸切替）
  - チケットデータの export / import

設計方針:
  - active roulette 前提。切替時に set_active_data() でデータを差し替える。
  - 保有チケットは (ticket_name, issuer, effect) の組合せで一意管理（個数制）。
  - 履歴: ドブの復活は既存履歴行の result_type を "revived" へ更新（別行追加なし）。
  - テンプレートはルーレット単位で管理（active roulette 単位の最小安全実装）。
"""

from __future__ import annotations

import datetime
import json
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QPlainTextEdit, QTabWidget, QWidget,
    QScrollArea, QMessageBox, QDialog, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QAbstractItemView, QComboBox,
)

from design_models import DesignSettings
from panel_widgets import _PanelDragBar, _PanelGrip, install_panel_context_menu


# ---------------------------------------------------------------------------
#  定数
# ---------------------------------------------------------------------------

_ACTION_USE = "use"
_ACTION_DELETE = "delete"

_RESULT_SUCCESS = "success"
_RESULT_DOBU = "dobu"
_RESULT_REVIVED = "revived"
_RESULT_NONE = "none"

_LABEL_ACTION = {
    _ACTION_USE: "使用",
    _ACTION_DELETE: "削除",
    "revive": "復活(旧)",  # 旧フォーマット後方互換
}
_LABEL_RESULT = {
    _RESULT_SUCCESS: "成功",
    _RESULT_DOBU: "ドブ",
    _RESULT_REVIVED: "復活済み",
    _RESULT_NONE: "—",
}

# 集計軸
_AXIS_LABELS = ["チケット名", "発行者", "チケット効果"]
_AXIS_KEYS   = ["ticket_name", "issuer", "effect"]


# ---------------------------------------------------------------------------
#  使用結果選択ダイアログ
# ---------------------------------------------------------------------------

class _UseResultDialog(QDialog):
    """「成功 / ドブ」を選択するシンプルダイアログ。"""

    def __init__(self, ticket_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用結果")
        self.setModal(True)
        self._result: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        msg = QLabel(f"チケット「{ticket_name}」の使用結果を選択してください。")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btn_row = QHBoxLayout()
        for text, val in [("成功", _RESULT_SUCCESS), ("ドブ", _RESULT_DOBU)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _, v=val: self._select(v))
            btn_row.addWidget(b)
        btn_cancel = QPushButton("キャンセル")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _select(self, result: str):
        self._result = result
        self.accept()

    def result_type(self) -> Optional[str]:
        return self._result


# ---------------------------------------------------------------------------
#  TicketPanel
# ---------------------------------------------------------------------------

class TicketPanel(QFrame):
    """チケット管理パネル。

    Signals:
        geometry_changed(): パネルの位置・サイズが変わった
        data_changed(): 保有/履歴/テンプレートデータが変わった（外部保存トリガー用）
    """

    geometry_changed = Signal()
    data_changed = Signal()

    _MIN_W = 380
    _MIN_H = 300

    def __init__(self, design: DesignSettings, *,
                 on_drag_bar_changed=None,
                 parent=None):
        super().__init__(parent)
        self._design = design
        self._on_drag_bar_changed = on_drag_bar_changed

        self._active_roulette_id: str = ""
        self._holdings_store:  dict[str, list[dict]] = {}
        self._history_store:   dict[str, list[dict]] = {}
        self._templates_store: dict[str, list[dict]] = {}

        self.pinned_front = False

        self.setMinimumSize(self._MIN_W, self._MIN_H)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._apply_style()
        self._build_ui()
        self._connect_signals()

    # ================================================================
    #  スタイル
    # ================================================================

    def _apply_style(self):
        d = self._design
        self.setStyleSheet(
            f"TicketPanel {{ background: {d.panel}; "
            f"border: 1px solid {d.separator}; border-radius: 4px; }}"
        )

    # ================================================================
    #  UI 構築
    # ================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 4)
        root.setSpacing(0)

        # ドラッグバー
        self._drag_bar = _PanelDragBar(self, self._design, parent=self)
        root.addWidget(self._drag_bar)
        install_panel_context_menu(self, self._drag_bar,
                                   on_drag_bar_changed=self._on_drag_bar_visibility)

        # タブ
        self._tabs = QTabWidget()
        self._apply_tab_style()
        root.addWidget(self._tabs, 1)

        self._tabs.addTab(self._build_holdings_tab(), "保有チケット")
        self._tabs.addTab(self._build_history_tab(), "履歴")
        self._tabs.addTab(self._build_summary_tab(), "集計")

        # タブバー右端コーナー: [↑書出し][↓読込み][全クリア]
        d = self._design
        _corner_btn_style = (
            f"QPushButton {{ background: {d.separator}; color: {d.text}; "
            f"border: none; border-radius: 2px; padding: 2px 6px; font-size: 8pt; }}"
            f"QPushButton:hover {{ background: {d.accent}; }}"
        )
        _corner_clear_style = (
            f"QPushButton {{ background: {d.separator}; color: {d.text}; "
            f"border: none; border-radius: 2px; padding: 2px 6px; font-size: 8pt; }}"
            f"QPushButton:hover {{ background: #884444; color: #fff; }}"
        )

        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 4, 0)
        corner_layout.setSpacing(4)

        self._btn_export = QPushButton("↑ 書出し")
        self._btn_export.setFont(QFont("Meiryo", 8))
        self._btn_export.setStyleSheet(_corner_btn_style)
        self._btn_export.setToolTip("現在のルーレットのチケットデータをファイルに書き出します")
        corner_layout.addWidget(self._btn_export)

        self._btn_import = QPushButton("↓ 読込み")
        self._btn_import.setFont(QFont("Meiryo", 8))
        self._btn_import.setStyleSheet(_corner_btn_style)
        self._btn_import.setToolTip("ファイルからチケットデータを読み込みます（現在のデータを置き換えます）")
        corner_layout.addWidget(self._btn_import)

        self._btn_clear_all = QPushButton("全クリア")
        self._btn_clear_all.setFont(QFont("Meiryo", 8))
        self._btn_clear_all.setStyleSheet(_corner_clear_style)
        self._btn_clear_all.setToolTip("保有・履歴・テンプレートをすべてクリアします")
        corner_layout.addWidget(self._btn_clear_all)

        self._tabs.setCornerWidget(corner_widget, Qt.Corner.TopRightCorner)

        # リサイズグリップ（絶対位置配置）
        self._grip = _PanelGrip(self, self._design, min_w=self._MIN_W, min_h=self._MIN_H)

    def _apply_tab_style(self):
        d = self._design
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: none; background: {d.panel}; }}"
            f"QTabBar::tab {{ background: {d.panel}; color: {d.text}; "
            f"padding: 4px 10px; border: 1px solid {d.separator}; "
            f"border-bottom: none; border-radius: 3px 3px 0 0; }}"
            f"QTabBar::tab:selected {{ background: {d.accent}; color: {d.text}; }}"
            f"QTabBar::tab:hover {{ background: {d.separator}; }}"
        )

    # ── タブ1: 保有チケット ──────────────────────────────────────

    def _build_holdings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)
        d = self._design

        # --- 折りたたみ式追加フォーム ---
        self._form_toggle_btn = QPushButton("▶ チケット追加")
        self._form_toggle_btn.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._form_toggle_btn.setCheckable(True)
        self._form_toggle_btn.setChecked(False)
        self._form_toggle_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {d.text}; "
            f"border: none; text-align: left; padding: 2px 0; }}"
            f"QPushButton:hover {{ color: {d.accent}; }}"
        )
        self._form_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._form_toggle_btn)

        # フォームコンテンツ（折りたたみ対象）
        self._form_content = QWidget()
        form_content_layout = QVBoxLayout(self._form_content)
        form_content_layout.setContentsMargins(0, 2, 0, 2)
        form_content_layout.setSpacing(4)

        form_frame = QFrame()
        form_frame.setFrameShape(QFrame.Shape.StyledPanel)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(6, 4, 6, 6)
        form_layout.setSpacing(4)
        form_frame.setStyleSheet(
            f"QFrame {{ background: {d.panel}; border: 1px solid {d.separator}; "
            f"border-radius: 3px; }}"
            f"QLabel {{ color: {d.text}; border: none; }}"
            f"QLineEdit, QPlainTextEdit {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 2px; padding: 2px 4px; }}"
        )

        # テンプレート行
        tmpl_row = QHBoxLayout()
        tmpl_row.setSpacing(4)
        tmpl_lbl = QLabel("テンプレ:")
        tmpl_lbl.setFont(QFont("Meiryo", 8))
        self._tmpl_combo = QComboBox()
        self._tmpl_combo.setFont(QFont("Meiryo", 8))
        self._tmpl_combo.setStyleSheet(
            f"QComboBox {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 2px; padding: 2px 4px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {d.panel}; color: {d.text}; }}"
        )
        self._tmpl_combo.addItem("— 選択 —")
        self._btn_save_tmpl = QPushButton("保存")
        self._btn_save_tmpl.setFont(QFont("Meiryo", 8))
        self._btn_save_tmpl.setFixedHeight(24)
        self._btn_save_tmpl.setStyleSheet(
            f"QPushButton {{ background: {d.separator}; color: {d.text}; "
            f"border: none; border-radius: 2px; padding: 2px 8px; }}"
            f"QPushButton:hover {{ background: {d.accent}; }}"
        )
        tmpl_row.addWidget(tmpl_lbl)
        tmpl_row.addWidget(self._tmpl_combo, 1)
        tmpl_row.addWidget(self._btn_save_tmpl)
        form_layout.addLayout(tmpl_row)

        # 入力フィールド
        lbl_name = QLabel("チケット名 *")
        lbl_name.setFont(QFont("Meiryo", 8))
        self._inp_name = QLineEdit()
        self._inp_name.setPlaceholderText("チケット名（必須）")

        lbl_issuer = QLabel("発行者")
        lbl_issuer.setFont(QFont("Meiryo", 8))
        self._inp_issuer = QLineEdit()
        self._inp_issuer.setPlaceholderText("発行者（任意）")

        lbl_effect = QLabel("チケット効果")
        lbl_effect.setFont(QFont("Meiryo", 8))
        self._inp_effect = QPlainTextEdit()
        self._inp_effect.setPlaceholderText("チケット効果（任意）\n複数行入力可")
        self._inp_effect.setMaximumHeight(68)  # 約3行

        self._btn_add = QPushButton("追加")
        self._btn_add.setFont(QFont("Meiryo", 9))
        self._btn_add.setFixedHeight(28)
        self._btn_add.setStyleSheet(
            f"QPushButton {{ background: {d.accent}; color: {d.text}; "
            f"border: none; border-radius: 3px; }}"
            f"QPushButton:hover {{ background: {d.separator}; }}"
        )

        form_layout.addWidget(lbl_name)
        form_layout.addWidget(self._inp_name)
        form_layout.addWidget(lbl_issuer)
        form_layout.addWidget(self._inp_issuer)
        form_layout.addWidget(lbl_effect)
        form_layout.addWidget(self._inp_effect)
        form_layout.addWidget(self._btn_add)

        form_content_layout.addWidget(form_frame)
        self._form_content.setVisible(False)
        layout.addWidget(self._form_content)

        # --- 選択詳細 / 同内容追加 ---
        self._detail_frame = QFrame()
        detail_layout = QHBoxLayout(self._detail_frame)
        detail_layout.setContentsMargins(6, 4, 6, 4)
        detail_layout.setSpacing(8)
        self._detail_frame.setStyleSheet(
            f"QFrame {{ background: {d.bg}; border: 1px solid {d.separator}; "
            f"border-radius: 3px; }}"
            f"QLabel {{ color: {d.text}; border: none; }}"
        )
        self._detail_lbl = QLabel("一覧から行を選択すると内容を表示します")
        self._detail_lbl.setFont(QFont("Meiryo", 8))
        self._detail_lbl.setWordWrap(True)
        detail_layout.addWidget(self._detail_lbl, 1)

        self._btn_add_same = QPushButton("同内容で追加")
        self._btn_add_same.setFont(QFont("Meiryo", 8))
        self._btn_add_same.setFixedHeight(26)
        self._btn_add_same.setEnabled(False)
        self._btn_add_same.setStyleSheet(
            f"QPushButton {{ background: {d.separator}; color: {d.text}; "
            f"border: none; border-radius: 3px; padding: 2px 8px; }}"
            f"QPushButton:hover {{ background: {d.accent}; }}"
            f"QPushButton:disabled {{ color: {d.text_sub}; }}"
        )
        detail_layout.addWidget(self._btn_add_same)
        layout.addWidget(self._detail_frame)

        # 一覧ラベル
        lbl_list = QLabel("保有チケット一覧")
        lbl_list.setFont(QFont("Meiryo", 8, QFont.Weight.Bold))
        lbl_list.setStyleSheet(f"color: {d.text};")
        layout.addWidget(lbl_list)

        # 保有一覧テーブル
        self._holdings_table = QTableWidget()
        self._holdings_table.setColumnCount(6)
        self._holdings_table.setHorizontalHeaderLabels(
            ["チケット名", "発行者", "効果", "個数", "使用", "削除"]
        )
        hh = self._holdings_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._holdings_table.setColumnWidth(4, 50)
        self._holdings_table.setColumnWidth(5, 50)
        self._holdings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._holdings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._holdings_table.verticalHeader().setVisible(False)
        self._holdings_table.setAlternatingRowColors(True)
        self._apply_table_style(self._holdings_table)
        layout.addWidget(self._holdings_table, 1)

        return w

    # ── タブ2: 履歴 ─────────────────────────────────────────────

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)
        d = self._design

        lbl = QLabel("履歴一覧  ※「ドブ」をクリックすると保有に復活できます")
        lbl.setFont(QFont("Meiryo", 8))
        lbl.setStyleSheet(f"color: {d.text};")
        layout.addWidget(lbl)

        self._history_table = QTableWidget()
        self._history_table.setColumnCount(5)
        self._history_table.setHorizontalHeaderLabels(
            ["チケット名", "発行者", "効果", "操作", "結果"]
        )
        hh = self._history_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setAlternatingRowColors(True)
        self._apply_table_style(self._history_table)
        layout.addWidget(self._history_table, 1)

        return w

    # ── タブ3: 集計 ─────────────────────────────────────────────

    def _build_summary_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(6)
        d = self._design

        # 軸選択行
        axis_row = QHBoxLayout()
        axis_row.setSpacing(8)

        _combo_style = (
            f"QComboBox {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 3px; padding: 2px 4px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {d.panel}; color: {d.text}; }}"
        )

        lbl_primary = QLabel("主軸:")
        lbl_primary.setFont(QFont("Meiryo", 9))
        lbl_primary.setStyleSheet(f"color: {d.text};")
        axis_row.addWidget(lbl_primary)

        self._summary_primary_combo = QComboBox()
        self._summary_primary_combo.setFont(QFont("Meiryo", 9))
        self._summary_primary_combo.setStyleSheet(_combo_style)
        for label in _AXIS_LABELS:
            self._summary_primary_combo.addItem(label)
        axis_row.addWidget(self._summary_primary_combo)

        lbl_sub = QLabel("内訳軸:")
        lbl_sub.setFont(QFont("Meiryo", 9))
        lbl_sub.setStyleSheet(f"color: {d.text};")
        axis_row.addWidget(lbl_sub)

        self._summary_sub_combo = QComboBox()
        self._summary_sub_combo.setFont(QFont("Meiryo", 9))
        self._summary_sub_combo.setStyleSheet(_combo_style)
        self._summary_sub_combo.addItem("なし")
        for label in _AXIS_LABELS:
            self._summary_sub_combo.addItem(label)
        axis_row.addWidget(self._summary_sub_combo)
        axis_row.addStretch()

        layout.addLayout(axis_row)

        # 集計テーブル
        self._summary_table = QTableWidget()
        self._summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._summary_table.verticalHeader().setVisible(False)
        self._summary_table.setAlternatingRowColors(True)
        self._apply_table_style(self._summary_table)
        layout.addWidget(self._summary_table, 1)

        return w

    def _apply_table_style(self, tbl: QTableWidget):
        d = self._design
        tbl.setStyleSheet(
            f"QTableWidget {{ background: {d.bg}; color: {d.text}; "
            f"gridline-color: {d.separator}; border: none; font-size: 12px; }}"
            f"QTableWidget::item {{ padding: 2px 4px; }}"
            f"QTableWidget::item:selected {{ background: {d.accent}; }}"
            f"QHeaderView::section {{ background: {d.panel}; color: {d.text}; "
            f"border: 1px solid {d.separator}; padding: 3px; font-size: 11px; }}"
            f"QTableWidget::item:alternate {{ background: {d.panel}; }}"
        )

    # ================================================================
    #  シグナル接続
    # ================================================================

    def _connect_signals(self):
        self._btn_add.clicked.connect(self._on_add_ticket)
        self._btn_add_same.clicked.connect(self._on_add_same_ticket)
        self._btn_save_tmpl.clicked.connect(self._on_save_template)
        self._tmpl_combo.activated.connect(self._on_template_selected)
        self._form_toggle_btn.toggled.connect(self._on_form_toggle)
        self._holdings_table.itemSelectionChanged.connect(self._on_holding_selection_changed)
        self._history_table.cellClicked.connect(self._on_history_cell_clicked)
        self._btn_export.clicked.connect(self._on_export_tickets)
        self._btn_import.clicked.connect(self._on_import_tickets)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._summary_primary_combo.currentIndexChanged.connect(self._on_axis_changed)
        self._summary_sub_combo.currentIndexChanged.connect(self._on_axis_changed)
        self._btn_clear_all.clicked.connect(self._on_clear_all)

    # ================================================================
    #  外部 API — アクティブルーレット切替
    # ================================================================

    def set_active_data(self, roulette_id: str,
                        holdings: list[dict],
                        history: list[dict],
                        templates: list[dict] | None = None) -> None:
        """アクティブルーレットのデータをセットしてUIを更新する。

        MainWindow から active_changed 時に呼び出す。
        templates=None のときはテンプレートを変更しない。
        """
        self._active_roulette_id = roulette_id
        self._holdings_store[roulette_id] = list(holdings)
        self._history_store[roulette_id] = list(history)
        if templates is not None:
            self._templates_store[roulette_id] = list(templates)

        self._refresh_holdings_table()
        self._refresh_history_table()
        self._refresh_summary()
        self._refresh_template_combo()

    def get_current_holdings(self) -> list[dict]:
        return list(self._holdings_store.get(self._active_roulette_id, []))

    def get_current_history(self) -> list[dict]:
        return list(self._history_store.get(self._active_roulette_id, []))

    def get_current_templates(self) -> list[dict]:
        return list(self._templates_store.get(self._active_roulette_id, []))

    # ================================================================
    #  内部ヘルパー — データ操作
    # ================================================================

    def _current_holdings(self) -> list[dict]:
        return self._holdings_store.setdefault(self._active_roulette_id, [])

    def _current_history(self) -> list[dict]:
        return self._history_store.setdefault(self._active_roulette_id, [])

    def _current_templates(self) -> list[dict]:
        return self._templates_store.setdefault(self._active_roulette_id, [])

    def _find_holding_index(self, name: str, issuer: str, effect: str) -> int:
        for i, h in enumerate(self._current_holdings()):
            if (h.get("ticket_name", "") == name
                    and h.get("issuer", "") == issuer
                    and h.get("effect", "") == effect):
                return i
        return -1

    def _add_holding(self, name: str, issuer: str, effect: str, qty: int = 1) -> None:
        idx = self._find_holding_index(name, issuer, effect)
        holdings = self._current_holdings()
        if idx >= 0:
            holdings[idx]["quantity"] = holdings[idx].get("quantity", 0) + qty
        else:
            holdings.append({
                "ticket_name": name,
                "issuer": issuer,
                "effect": effect,
                "quantity": qty,
            })

    def _remove_one_holding(self, name: str, issuer: str, effect: str) -> bool:
        idx = self._find_holding_index(name, issuer, effect)
        if idx < 0:
            return False
        holdings = self._current_holdings()
        holdings[idx]["quantity"] = holdings[idx].get("quantity", 1) - 1
        if holdings[idx]["quantity"] <= 0:
            del holdings[idx]
        return True

    def _append_history(self, name: str, issuer: str, effect: str,
                        action_type: str, result_type: str) -> None:
        entry = {
            "ticket_name": name,
            "issuer": issuer,
            "effect": effect,
            "action_type": action_type,
            "result_type": result_type,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        self._current_history().append(entry)

    # ================================================================
    #  UI 更新
    # ================================================================

    def _refresh_holdings_table(self) -> None:
        holdings = self._current_holdings()
        tbl = self._holdings_table
        tbl.setRowCount(0)
        for row_idx, h in enumerate(holdings):
            tbl.insertRow(row_idx)
            effect_display = h.get("effect", "").replace("\n", " ")
            tbl.setItem(row_idx, 0, self._make_cell(h.get("ticket_name", "")))
            tbl.setItem(row_idx, 1, self._make_cell(h.get("issuer", "")))
            tbl.setItem(row_idx, 2, self._make_cell(effect_display))
            tbl.setItem(row_idx, 3, self._make_cell(
                str(h.get("quantity", 0)), center=True))

            btn_use = QPushButton("使用")
            btn_use.setFixedHeight(22)
            btn_use.setFont(QFont("Meiryo", 8))
            self._style_action_btn(btn_use, "use")
            btn_use.clicked.connect(lambda _, i=row_idx: self._on_use_ticket(i))
            tbl.setCellWidget(row_idx, 4, btn_use)

            btn_del = QPushButton("削除")
            btn_del.setFixedHeight(22)
            btn_del.setFont(QFont("Meiryo", 8))
            self._style_action_btn(btn_del, "delete")
            btn_del.clicked.connect(lambda _, i=row_idx: self._on_delete_ticket(i))
            tbl.setCellWidget(row_idx, 5, btn_del)

        tbl.resizeRowsToContents()
        # 選択状態リセット
        self._btn_add_same.setEnabled(False)
        self._detail_lbl.setText("一覧から行を選択すると内容を表示します")

    def _refresh_history_table(self) -> None:
        history = self._current_history()
        tbl = self._history_table
        tbl.setRowCount(0)

        for row_idx, h in enumerate(reversed(history)):
            orig_idx = len(history) - 1 - row_idx
            tbl.insertRow(row_idx)

            effect_display = h.get("effect", "").replace("\n", " ")
            tbl.setItem(row_idx, 0, self._make_cell(h.get("ticket_name", "")))
            tbl.setItem(row_idx, 1, self._make_cell(h.get("issuer", "")))
            tbl.setItem(row_idx, 2, self._make_cell(effect_display))

            action_type = h.get("action_type", "")
            action_label = _LABEL_ACTION.get(action_type, action_type)
            tbl.setItem(row_idx, 3, self._make_cell(action_label, center=True))

            # 結果セル — ドブは橙色でクリック可能
            result_type = h.get("result_type", "")
            result_label = _LABEL_RESULT.get(result_type, result_type)
            result_item = self._make_cell(result_label, center=True)

            if result_type == _RESULT_DOBU:
                result_item.setForeground(QColor("#FF8C00"))
                result_item.setToolTip("クリックで復活（保有に1個戻します）")
                result_item.setData(Qt.ItemDataRole.UserRole, orig_idx)
            elif result_type == _RESULT_REVIVED:
                result_item.setForeground(QColor("#888888"))
                result_item.setToolTip("クリックで復活取り消し（保有から1個差し引きます）")
                result_item.setData(Qt.ItemDataRole.UserRole, orig_idx)

            tbl.setItem(row_idx, 4, result_item)

        tbl.resizeRowsToContents()

    def _refresh_summary(self) -> None:
        primary_idx = self._summary_primary_combo.currentIndex()
        sub_idx = self._summary_sub_combo.currentIndex()

        primary_key = _AXIS_KEYS[primary_idx]
        sub_key = _AXIS_KEYS[sub_idx - 1] if sub_idx > 0 else None

        # i053: 削除は集計対象外
        cols = ["使用成功", "ドブ", "復活"]

        def _zero():
            return {c: 0 for c in cols}

        pivot: dict[str, dict] = {}

        for h in self._current_history():
            action = h.get("action_type", "")
            result = h.get("result_type", "")

            # 旧フォーマット (action_type="revive") 後方互換
            if action == "revive":
                field = "復活"
            elif action == _ACTION_USE:
                if result == _RESULT_SUCCESS:
                    field = "使用成功"
                elif result == _RESULT_DOBU:
                    field = "ドブ"
                elif result == _RESULT_REVIVED:
                    field = "復活"
                else:
                    continue
            else:
                continue

            p_val = h.get(primary_key, "") or "—"
            if sub_key and sub_key != primary_key:
                s_val = h.get(sub_key, "") or "—"
                row_key = f"{p_val}  /  {s_val}"
            else:
                row_key = p_val

            if row_key not in pivot:
                pivot[row_key] = _zero()
            pivot[row_key][field] += 1

        # テーブル再構築
        tbl = self._summary_table
        tbl.setRowCount(0)

        primary_label = _AXIS_LABELS[primary_idx]
        if sub_key and sub_key != primary_key:
            header_label = f"{primary_label} / {_AXIS_LABELS[sub_idx - 1]}"
        else:
            header_label = primary_label

        tbl.setColumnCount(len(cols) + 1)
        tbl.setHorizontalHeaderLabels([header_label] + cols)
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for ci in range(1, len(cols) + 1):
            hh.setSectionResizeMode(ci, QHeaderView.ResizeMode.ResizeToContents)

        for ri, (row_key, counts) in enumerate(sorted(pivot.items())):
            tbl.insertRow(ri)
            tbl.setItem(ri, 0, self._make_cell(row_key))
            for ci, col in enumerate(cols):
                tbl.setItem(ri, ci + 1,
                            self._make_cell(str(counts.get(col, 0)), center=True))

        tbl.resizeRowsToContents()

    def _refresh_template_combo(self) -> None:
        templates = self._current_templates()
        self._tmpl_combo.blockSignals(True)
        self._tmpl_combo.clear()
        self._tmpl_combo.addItem("— 選択 —")
        for tmpl in templates:
            self._tmpl_combo.addItem(tmpl.get("ticket_name", "(名前なし)"))
        self._tmpl_combo.setCurrentIndex(0)
        self._tmpl_combo.blockSignals(False)

    def _style_action_btn(self, btn: QPushButton, kind: str):
        d = self._design
        color = {
            "use":    d.accent,
            "delete": "#884444",
        }.get(kind, d.separator)
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: {d.text}; "
            f"border: none; border-radius: 2px; }}"
        )

    @staticmethod
    def _make_cell(text: str, center: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    # ================================================================
    #  ボタン・操作ハンドラ
    # ================================================================

    def _on_form_toggle(self, checked: bool):
        self._form_content.setVisible(checked)
        self._form_toggle_btn.setText(
            "▼ チケット追加" if checked else "▶ チケット追加"
        )

    def _on_add_ticket(self) -> None:
        name   = self._inp_name.text().strip()
        issuer = self._inp_issuer.text().strip()
        effect = self._inp_effect.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "入力エラー", "チケット名は必須です。")
            return

        self._add_holding(name, issuer, effect, qty=1)
        self._inp_name.clear()
        self._inp_issuer.clear()
        self._inp_effect.clear()
        self._inp_name.setFocus()

        self._refresh_holdings_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()

    def _on_add_same_ticket(self) -> None:
        """選択中の行と同じ内容でチケットを1個追加。"""
        rows = self._holdings_table.selectionModel().selectedRows()
        if not rows:
            return
        row_idx = rows[0].row()
        holdings = self._current_holdings()
        if row_idx >= len(holdings):
            return
        h = holdings[row_idx]
        self._add_holding(
            h.get("ticket_name", ""),
            h.get("issuer", ""),
            h.get("effect", ""),
            qty=1,
        )
        self._refresh_holdings_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()

    def _on_holding_selection_changed(self) -> None:
        rows = self._holdings_table.selectionModel().selectedRows()
        if not rows:
            self._detail_lbl.setText("一覧から行を選択すると内容を表示します")
            self._btn_add_same.setEnabled(False)
            return
        row_idx = rows[0].row()
        holdings = self._current_holdings()
        if row_idx >= len(holdings):
            return
        h = holdings[row_idx]
        name   = h.get("ticket_name", "")
        issuer = h.get("issuer", "") or "—"
        qty    = h.get("quantity", 0)
        effect = h.get("effect", "") or "—"
        self._detail_lbl.setText(
            f"【{name}】  発行者: {issuer}  個数: {qty}\n効果: {effect}"
        )
        self._btn_add_same.setEnabled(True)

    def _on_save_template(self) -> None:
        name = self._inp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "テンプレ保存", "チケット名が入力されていません。")
            return
        issuer = self._inp_issuer.text().strip()
        effect = self._inp_effect.toPlainText().strip()
        tmpl = {"ticket_name": name, "issuer": issuer, "effect": effect}
        templates = self._current_templates()
        # 同名テンプレートは上書き
        for i, t in enumerate(templates):
            if t.get("ticket_name") == name:
                templates[i] = tmpl
                self._refresh_template_combo()
                self.data_changed.emit()
                return
        templates.append(tmpl)
        self._refresh_template_combo()
        self.data_changed.emit()

    def _on_template_selected(self, index: int) -> None:
        if index <= 0:
            return
        templates = self._current_templates()
        tmpl_idx = index - 1
        if tmpl_idx >= len(templates):
            return
        tmpl = templates[tmpl_idx]
        self._inp_name.setText(tmpl.get("ticket_name", ""))
        self._inp_issuer.setText(tmpl.get("issuer", ""))
        self._inp_effect.setPlainText(tmpl.get("effect", ""))
        # フォームが閉じていれば開く
        if not self._form_toggle_btn.isChecked():
            self._form_toggle_btn.setChecked(True)

    def _on_use_ticket(self, row: int) -> None:
        holdings = self._current_holdings()
        if row >= len(holdings):
            return
        h = holdings[row]
        name   = h.get("ticket_name", "")
        issuer = h.get("issuer", "")
        effect = h.get("effect", "")

        dlg = _UseResultDialog(name, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        result = dlg.result_type()
        if result is None:
            return

        self._remove_one_holding(name, issuer, effect)
        self._append_history(name, issuer, effect, _ACTION_USE, result)

        self._refresh_holdings_table()
        self._refresh_history_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()

    def _on_delete_ticket(self, row: int) -> None:
        holdings = self._current_holdings()
        if row >= len(holdings):
            return
        h = holdings[row]
        name   = h.get("ticket_name", "")
        issuer = h.get("issuer", "")
        effect = h.get("effect", "")

        # i053: 削除は保有から取り除くのみ（履歴・集計に記録しない）
        self._remove_one_holding(name, issuer, effect)

        self._refresh_holdings_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()

    def _on_history_cell_clicked(self, row: int, col: int) -> None:
        """履歴テーブルの結果セルクリック: ドブ → 復活 / 復活済み → 復活取り消し。"""
        if col != 4:
            return
        item = self._history_table.item(row, col)
        if item is None:
            return

        orig_idx = item.data(Qt.ItemDataRole.UserRole)
        if orig_idx is None:
            return

        history = self._current_history()
        if orig_idx >= len(history):
            return
        h = history[orig_idx]
        result_type = h.get("result_type")
        name   = h.get("ticket_name", "")
        issuer = h.get("issuer", "")
        effect = h.get("effect", "")

        if result_type == _RESULT_DOBU:
            # i053: 確認ダイアログ付き復活
            ans = QMessageBox.question(
                self,
                "復活確認",
                f"チケット「{name}」を保有に1個戻しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            history[orig_idx]["result_type"] = _RESULT_REVIVED
            self._add_holding(name, issuer, effect, qty=1)

        elif result_type == _RESULT_REVIVED:
            # i059: 保有の存在確認（保有がなければ取り消し不可）
            if self._find_holding_index(name, issuer, effect) < 0:
                QMessageBox.warning(
                    self,
                    "取り消し不可",
                    f"チケット「{name}」が保有に見つかりません。\n"
                    "手動で削除済みの可能性があります。復活取り消しはできません。",
                )
                return
            # i053: 復活取り消し（保有から1個引いて履歴をドブに戻す）
            ans = QMessageBox.question(
                self,
                "復活取り消し確認",
                f"チケット「{name}」の復活を取り消しますか？\n保有から1個差し引きます。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            history[orig_idx]["result_type"] = _RESULT_DOBU
            self._remove_one_holding(name, issuer, effect)

        else:
            return

        self._refresh_holdings_table()
        self._refresh_history_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()

    def _on_clear_all(self) -> None:
        """保有・履歴・テンプレートをすべてクリアする。"""
        ans = QMessageBox.question(
            self,
            "全クリア確認",
            "保有チケット・履歴・テンプレートをすべて削除します。\n"
            "この操作は取り消せません。続行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        rid = self._active_roulette_id
        self._holdings_store[rid]  = []
        self._history_store[rid]   = []
        self._templates_store[rid] = []
        self._refresh_holdings_table()
        self._refresh_history_table()
        self._refresh_summary()
        self._refresh_template_combo()
        self.data_changed.emit()

    def _on_export_tickets(self) -> None:
        rid = self._active_roulette_id or "default"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "チケットデータを書き出す",
            f"ticket_{rid}.json",
            "JSON ファイル (*.json);;すべてのファイル (*)",
        )
        if not filename:
            return
        data = {
            "roulette_id":      rid,
            "ticket_holdings":  self.get_current_holdings(),
            "ticket_history":   self.get_current_history(),
            "ticket_templates": self.get_current_templates(),
        }
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "書き出しエラー", str(e))

    def _on_import_tickets(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "チケットデータを読み込む",
            "",
            "JSON ファイル (*.json);;すべてのファイル (*)",
        )
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "読み込みエラー", str(e))
            return

        ans = QMessageBox.question(
            self,
            "チケット読み込み確認",
            "現在のチケットデータを読み込んだデータで置き換えます。\n"
            "この操作は取り消せません。続行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        rid = self._active_roulette_id
        self._holdings_store[rid]  = list(data.get("ticket_holdings", []))
        self._history_store[rid]   = list(data.get("ticket_history", []))
        self._templates_store[rid] = list(data.get("ticket_templates", []))

        self._refresh_holdings_table()
        self._refresh_history_table()
        self._refresh_summary()
        self._refresh_template_combo()
        self.data_changed.emit()

    def _on_tab_changed(self, index: int) -> None:
        if index == 2:
            self._refresh_summary()

    def _on_axis_changed(self, _index: int) -> None:
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()

    def _on_drag_bar_visibility(self, visible: bool) -> None:
        if self._on_drag_bar_changed:
            self._on_drag_bar_changed(visible)

    # ================================================================
    #  ジオメトリイベント
    # ================================================================

    def mousePressEvent(self, event):
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._grip.reposition()
        self.geometry_changed.emit()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()
