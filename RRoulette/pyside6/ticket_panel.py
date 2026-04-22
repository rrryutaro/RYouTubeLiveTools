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
import uuid as _uuid_mod
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QPlainTextEdit, QTabWidget, QWidget,
    QScrollArea, QMessageBox, QDialog, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QAbstractItemView, QComboBox, QDoubleSpinBox, QSpinBox,
)

from design_models import DesignSettings
from panel_widgets import _PanelDragBar, _PanelGrip, install_panel_context_menu, ConfirmOverlay, ItemSelectOverlay


# ---------------------------------------------------------------------------
#  定数
# ---------------------------------------------------------------------------

_ACTION_USE = "use"
_ACTION_DELETE = "delete"

_RESULT_SUCCESS = "success"
_RESULT_DOBU = "dobu"
_RESULT_REVIVED = "revived"
_RESULT_NONE = "none"

# i069: チケット効果タイプ
_EFFECT_NONE = "none"
_EFFECT_POINTER_MOVE = "pointer_move"
# i076: 項目非表示
_EFFECT_SET_ITEM_ENABLED = "set_item_enabled"
# i078: 表示名称を単一定数で管理
_LABEL_SET_ITEM_ENABLED = "項目非表示"
# i086: 重み係数指定（i088: 「項目」を除いた名称に統一）
_EFFECT_SET_WEIGHT = "set_weight"
_LABEL_SET_WEIGHT = "重み係数指定"
# i087: 固定確率指定 / 追加確率指定
_EFFECT_SET_FIXED_PROB = "set_fixed_prob"
_LABEL_SET_FIXED_PROB = "固定確率指定"
_EFFECT_ADD_PROB = "add_prob"
_LABEL_ADD_PROB = "追加確率指定"

_EFFECT_TYPE_LABELS = [
    "なし", "ポインター移動", _LABEL_SET_ITEM_ENABLED,
    _LABEL_SET_WEIGHT, _LABEL_SET_FIXED_PROB, _LABEL_ADD_PROB,
]
_EFFECT_TYPE_VALUES = [
    _EFFECT_NONE, _EFFECT_POINTER_MOVE, _EFFECT_SET_ITEM_ENABLED,
    _EFFECT_SET_WEIGHT, _EFFECT_SET_FIXED_PROB, _EFFECT_ADD_PROB,
]

# i086: 重み係数スピンボックスのデフォルト値
_DEFAULT_WEIGHT_VALUE = 1.0
_WEIGHT_VALUE_MIN = 0.25
_WEIGHT_VALUE_MAX = 99.0
_WEIGHT_VALUE_STEP = 0.25

# i087: 確率スピンボックスの範囲
_DEFAULT_PROB_VALUE = 10.0
_PROB_VALUE_MIN = 0.1
_PROB_VALUE_MAX = 99.9
_PROB_VALUE_STEP = 0.1

# pointer_move デフォルト移動量（度数）
_DEFAULT_MAX_DEG = 15.0
_MAX_DEG_LIMIT   = 180.0

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
    # i069: pointer_move チケット使用要求 (roulette_id, max_deg, name, issuer, effect, ticket_id)
    pointer_move_requested = Signal(str, float, str, str, str, str)
    # i076/i077: set_item_enabled チケット使用要求 (roulette_id, name, issuer, effect, ticket_id)
    # i077: 対象項目は使用時に選択するため、シグナルには含めない
    set_item_enabled_requested = Signal(str, str, str, str, str)
    # i086: set_weight チケット使用要求 (roulette_id, name, issuer, effect, ticket_id)
    # 対象項目・係数値は使用時選択・effect_params から取得するため、シグナルには含めない
    set_item_weight_requested = Signal(str, str, str, str, str)
    # i087: 固定確率指定・追加確率指定 共通シグナル (roulette_id, name, issuer, effect, ticket_id)
    # effect_type は holdings の effect_type を参照して区別する
    set_prob_effect_requested = Signal(str, str, str, str, str)

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

        # i073: pointer_move チケット使用時の効果情報（履歴記録用に一時保存）
        self._pm_pending_effect_type: str = _EFFECT_NONE
        self._pm_pending_effect_params: dict = {}


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
        self._form_content = QWidget(w)  # i066: 親なし HWND フラッシュ防止
        form_content_layout = QVBoxLayout(self._form_content)
        form_content_layout.setContentsMargins(0, 2, 0, 2)
        form_content_layout.setSpacing(4)

        form_frame = QFrame(self._form_content)  # i066: 親なし HWND フラッシュ防止
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

        lbl_effect = QLabel("効果メモ（任意）")
        lbl_effect.setFont(QFont("Meiryo", 8))
        self._inp_effect = QPlainTextEdit()
        self._inp_effect.setPlaceholderText("効果メモ（任意）\n複数行入力可")
        self._inp_effect.setMaximumHeight(68)  # 約3行

        # i069: 効果タイプ選択
        lbl_effect_type = QLabel("効果タイプ")
        lbl_effect_type.setFont(QFont("Meiryo", 8))
        _combo_style_inner = (
            f"QComboBox {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 2px; padding: 2px 4px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {d.panel}; color: {d.text}; }}"
        )
        self._effect_type_combo = QComboBox()
        self._effect_type_combo.setFont(QFont("Meiryo", 8))
        self._effect_type_combo.setStyleSheet(_combo_style_inner)
        for label in _EFFECT_TYPE_LABELS:
            self._effect_type_combo.addItem(label)

        # pointer_move 時だけ表示する最大移動量入力（自由入力 i070）
        self._max_deg_row = QWidget()
        _md_row_layout = QHBoxLayout(self._max_deg_row)
        _md_row_layout.setContentsMargins(0, 0, 0, 0)
        _md_row_layout.setSpacing(4)
        lbl_max_deg = QLabel("最大移動量")
        lbl_max_deg.setFont(QFont("Meiryo", 8))
        self._max_deg_spinbox = QDoubleSpinBox()
        self._max_deg_spinbox.setFont(QFont("Meiryo", 8))
        self._max_deg_spinbox.setMinimum(0.5)
        self._max_deg_spinbox.setMaximum(_MAX_DEG_LIMIT)
        self._max_deg_spinbox.setSingleStep(1.0)
        self._max_deg_spinbox.setValue(_DEFAULT_MAX_DEG)
        self._max_deg_spinbox.setSuffix("°")
        self._max_deg_spinbox.setDecimals(1)
        self._max_deg_spinbox.setStyleSheet(
            f"QDoubleSpinBox {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 2px; padding: 2px 4px; }}"
        )
        _md_row_layout.addWidget(lbl_max_deg)
        _md_row_layout.addWidget(self._max_deg_spinbox, 1)
        self._max_deg_row.setVisible(False)

        # i077: set_item_enabled はチケット作成時にパラメータなし（使用時選択型）
        # _set_item_row は廃止済み

        # i086: set_weight 時だけ表示する係数値入力行
        self._weight_value_row = QWidget()
        _wv_row_layout = QHBoxLayout(self._weight_value_row)
        _wv_row_layout.setContentsMargins(0, 0, 0, 0)
        _wv_row_layout.setSpacing(4)
        lbl_weight_val = QLabel("係数値")
        lbl_weight_val.setFont(QFont("Meiryo", 8))
        self._weight_value_spinbox = QDoubleSpinBox()
        self._weight_value_spinbox.setFont(QFont("Meiryo", 8))
        self._weight_value_spinbox.setMinimum(_WEIGHT_VALUE_MIN)
        self._weight_value_spinbox.setMaximum(_WEIGHT_VALUE_MAX)
        self._weight_value_spinbox.setSingleStep(_WEIGHT_VALUE_STEP)
        self._weight_value_spinbox.setValue(_DEFAULT_WEIGHT_VALUE)
        self._weight_value_spinbox.setPrefix("×")
        self._weight_value_spinbox.setDecimals(2)
        self._weight_value_spinbox.setStyleSheet(
            f"QDoubleSpinBox {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 2px; padding: 2px 4px; }}"
        )
        _wv_row_layout.addWidget(lbl_weight_val)
        _wv_row_layout.addWidget(self._weight_value_spinbox, 1)
        self._weight_value_row.setVisible(False)

        # i087: set_fixed_prob 時だけ表示する固定確率入力行
        self._fixed_prob_row = QWidget()
        _fp_row_layout = QHBoxLayout(self._fixed_prob_row)
        _fp_row_layout.setContentsMargins(0, 0, 0, 0)
        _fp_row_layout.setSpacing(4)
        lbl_fixed_prob = QLabel("固定確率")
        lbl_fixed_prob.setFont(QFont("Meiryo", 8))
        self._fixed_prob_spinbox = QDoubleSpinBox()
        self._fixed_prob_spinbox.setFont(QFont("Meiryo", 8))
        self._fixed_prob_spinbox.setMinimum(_PROB_VALUE_MIN)
        self._fixed_prob_spinbox.setMaximum(_PROB_VALUE_MAX)
        self._fixed_prob_spinbox.setSingleStep(_PROB_VALUE_STEP)
        self._fixed_prob_spinbox.setValue(_DEFAULT_PROB_VALUE)
        self._fixed_prob_spinbox.setSuffix("%")
        self._fixed_prob_spinbox.setDecimals(1)
        self._fixed_prob_spinbox.setStyleSheet(
            f"QDoubleSpinBox {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 2px; padding: 2px 4px; }}"
        )
        _fp_row_layout.addWidget(lbl_fixed_prob)
        _fp_row_layout.addWidget(self._fixed_prob_spinbox, 1)
        self._fixed_prob_row.setVisible(False)

        # i087: add_prob 時だけ表示する追加確率入力行
        self._add_prob_row = QWidget()
        _ap_row_layout = QHBoxLayout(self._add_prob_row)
        _ap_row_layout.setContentsMargins(0, 0, 0, 0)
        _ap_row_layout.setSpacing(4)
        lbl_add_prob = QLabel("追加確率")
        lbl_add_prob.setFont(QFont("Meiryo", 8))
        self._add_prob_spinbox = QDoubleSpinBox()
        self._add_prob_spinbox.setFont(QFont("Meiryo", 8))
        self._add_prob_spinbox.setMinimum(_PROB_VALUE_MIN)
        self._add_prob_spinbox.setMaximum(_PROB_VALUE_MAX)
        self._add_prob_spinbox.setSingleStep(_PROB_VALUE_STEP)
        self._add_prob_spinbox.setValue(_DEFAULT_PROB_VALUE)
        self._add_prob_spinbox.setSuffix("%")
        self._add_prob_spinbox.setDecimals(1)
        self._add_prob_spinbox.setStyleSheet(
            f"QDoubleSpinBox {{ background: {d.bg}; color: {d.text}; "
            f"border: 1px solid {d.separator}; border-radius: 2px; padding: 2px 4px; }}"
        )
        _ap_row_layout.addWidget(lbl_add_prob)
        _ap_row_layout.addWidget(self._add_prob_spinbox, 1)
        self._add_prob_row.setVisible(False)

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
        form_layout.addWidget(lbl_effect_type)
        form_layout.addWidget(self._effect_type_combo)
        form_layout.addWidget(self._max_deg_row)
        form_layout.addWidget(self._weight_value_row)
        form_layout.addWidget(self._fixed_prob_row)
        form_layout.addWidget(self._add_prob_row)
        form_layout.addWidget(self._btn_add)

        form_content_layout.addWidget(form_frame)
        self._form_content.setVisible(False)
        layout.addWidget(self._form_content)

        # --- 選択詳細 / 同内容追加 ---
        self._detail_frame = QFrame(w)  # i066: 親なし HWND フラッシュ防止
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
        self._history_table.selectionModel().selectionChanged.connect(
            self._on_history_selection_changed
        )
        layout.addWidget(self._history_table, 1)

        # i083: 選択行の詳細表示ラベル
        self._history_detail_lbl = QLabel("一覧から行を選択すると詳細を表示します", w)
        self._history_detail_lbl.setFont(QFont("Meiryo", 8))
        self._history_detail_lbl.setStyleSheet(
            f"color: {d.text}; background: {d.panel}; "
            f"border: 1px solid {d.separator}; border-radius: 3px; padding: 4px 6px;"
        )
        self._history_detail_lbl.setWordWrap(True)
        layout.addWidget(self._history_detail_lbl)

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
        self._effect_type_combo.currentIndexChanged.connect(self._on_effect_type_changed)
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
        i070: ticket_id がないレコードには読み込み時に補完する。
        """
        self._active_roulette_id = roulette_id
        # i070: 古いデータに ticket_id がなければ補完
        padded_holdings = []
        for h in holdings:
            if not h.get("ticket_id"):
                h = dict(h)
                h["ticket_id"] = str(_uuid_mod.uuid4())
            padded_holdings.append(h)
        self._holdings_store[roulette_id] = padded_holdings
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

    def _find_holding_index(self, name: str, issuer: str, effect: str,
                            ticket_id: str = "") -> int:
        """保有チケットのインデックスを返す。

        i070: ticket_id が指定されていれば ID 優先で検索。
        なければ (name, issuer, effect) の後方互換検索。
        """
        holdings = self._current_holdings()
        if ticket_id:
            for i, h in enumerate(holdings):
                if h.get("ticket_id") == ticket_id:
                    return i
        for i, h in enumerate(holdings):
            if (h.get("ticket_name", "") == name
                    and h.get("issuer", "") == issuer
                    and h.get("effect", "") == effect):
                return i
        return -1

    def _add_holding(self, name: str, issuer: str, effect: str, qty: int = 1,
                     effect_type: str = _EFFECT_NONE,
                     effect_params: dict | None = None) -> None:
        # i070: ticket_id ベースで識別。同名でも effect_params が異なれば別チケット。
        # 既存の同一 (name, issuer, effect, effect_type, effect_params) チケットは数量加算。
        holdings = self._current_holdings()
        # 完全一致チェック（name + issuer + effect + effect_type + effect_params）
        ep = effect_params or {}
        for h in holdings:
            if (h.get("ticket_name") == name
                    and h.get("issuer") == issuer
                    and h.get("effect") == effect
                    and h.get("effect_type", _EFFECT_NONE) == effect_type
                    and h.get("effect_params", {}) == ep):
                h["quantity"] = h.get("quantity", 0) + qty
                return
        holdings.append({
            "ticket_id":    str(_uuid_mod.uuid4()),  # i070: 一意識別子
            "ticket_name":  name,
            "issuer":       issuer,
            "effect":       effect,
            "effect_type":  effect_type,
            "effect_params": ep,
            "quantity":     qty,
        })

    def _remove_one_holding(self, name: str, issuer: str, effect: str,
                            ticket_id: str = "") -> bool:
        idx = self._find_holding_index(name, issuer, effect, ticket_id=ticket_id)
        if idx < 0:
            return False
        holdings = self._current_holdings()
        holdings[idx]["quantity"] = holdings[idx].get("quantity", 1) - 1
        if holdings[idx]["quantity"] <= 0:
            del holdings[idx]
        return True

    def _append_history(self, name: str, issuer: str, effect: str,
                        action_type: str, result_type: str,
                        effect_type: str = "", effect_params: dict | None = None) -> None:
        """履歴エントリを追加する。

        i073: 復活時に効果タイプを正しく復元できるよう effect_type / effect_params を保存する。
        """
        entry = {
            "ticket_name": name,
            "issuer": issuer,
            "effect": effect,
            "action_type": action_type,
            "result_type": result_type,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "effect_type": effect_type or _EFFECT_NONE,
            "effect_params": dict(effect_params) if effect_params else {},
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
        # i084: 判定なし系（set_item_enabled等）は使用成功側で統一カウント
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
                elif result == _RESULT_NONE:
                    field = "使用成功"  # i084: 判定なし系は使用成功として統一カウント
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

        effect_type, effect_params = self._read_effect_from_ui()
        self._add_holding(name, issuer, effect, qty=1,
                          effect_type=effect_type, effect_params=effect_params)
        self._inp_name.clear()
        self._inp_issuer.clear()
        self._inp_effect.clear()
        self._effect_type_combo.setCurrentIndex(0)
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
        # i071: effect_type / effect_params を引き継ぐ。ticket_id は _add_holding で新規発行。
        self._add_holding(
            h.get("ticket_name", ""),
            h.get("issuer", ""),
            h.get("effect", ""),
            qty=1,
            effect_type=h.get("effect_type", _EFFECT_NONE),
            effect_params=h.get("effect_params", {}),
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
        name        = h.get("ticket_name", "")
        issuer      = h.get("issuer", "") or "—"
        qty         = h.get("quantity", 0)
        effect_memo = h.get("effect", "") or "—"
        effect_type = h.get("effect_type", _EFFECT_NONE)
        effect_params = h.get("effect_params", {})
        # i070: 効果タイプ・パラメータを表示
        if effect_type == _EFFECT_POINTER_MOVE:
            max_deg = effect_params.get("max_move_deg", _DEFAULT_MAX_DEG)
            effect_type_disp = f"ポインター移動（最大 {max_deg}°）"
        elif effect_type == _EFFECT_SET_ITEM_ENABLED:
            # i077: 使用時選択型のため、チケット保存時点では対象項目なし
            effect_type_disp = f"{_LABEL_SET_ITEM_ENABLED}（使用時選択）"
        elif effect_type == _EFFECT_SET_WEIGHT:
            # i086: 係数値はチケット作成時に固定、対象は使用時選択
            wv = effect_params.get("weight_value", _DEFAULT_WEIGHT_VALUE)
            effect_type_disp = f"{_LABEL_SET_WEIGHT}（係数 ×{wv:g}・対象は使用時選択）"
        elif effect_type == _EFFECT_SET_FIXED_PROB:
            pv = effect_params.get("prob_value", _DEFAULT_PROB_VALUE)
            effect_type_disp = f"{_LABEL_SET_FIXED_PROB}（{pv:g}%・対象は使用時選択）"
        elif effect_type == _EFFECT_ADD_PROB:
            pv = effect_params.get("prob_value", _DEFAULT_PROB_VALUE)
            effect_type_disp = f"{_LABEL_ADD_PROB}（+{pv:g}%・対象は使用時選択）"
        else:
            effect_type_disp = "なし"
        self._detail_lbl.setText(
            f"【{name}】  発行者: {issuer}  個数: {qty}\n"
            f"効果タイプ: {effect_type_disp}\n"
            f"メモ: {effect_memo}"
        )
        self._btn_add_same.setEnabled(True)

    def _on_history_selection_changed(self) -> None:
        """i083: 履歴テーブルの選択行切替 → 詳細ラベル更新。"""
        if not hasattr(self, "_history_detail_lbl"):
            return
        rows = self._history_table.selectionModel().selectedRows()
        if not rows:
            self._history_detail_lbl.setText("一覧から行を選択すると詳細を表示します")
            return
        row_idx = rows[0].row()
        history = self._current_history()
        # 表示は新しい順（reversed）なので orig_idx を逆算
        orig_idx = len(history) - 1 - row_idx
        if orig_idx < 0 or orig_idx >= len(history):
            return
        h = history[orig_idx]
        name         = h.get("ticket_name", "") or "—"
        issuer       = h.get("issuer", "") or "—"
        effect_memo  = h.get("effect", "") or "—"
        effect_type  = h.get("effect_type", _EFFECT_NONE)
        effect_params = h.get("effect_params", {})
        result_type  = h.get("result_type", "")

        if effect_type == _EFFECT_POINTER_MOVE:
            max_deg = effect_params.get("max_move_deg", _DEFAULT_MAX_DEG)
            etype_disp = f"ポインター移動（最大 {max_deg}°）"
        elif effect_type == _EFFECT_SET_ITEM_ENABLED:
            target = effect_params.get("target_item", "")
            etype_disp = (
                f"{_LABEL_SET_ITEM_ENABLED}（対象: {target}）"
                if target else f"{_LABEL_SET_ITEM_ENABLED}（使用時選択）"
            )
        elif effect_type == _EFFECT_SET_WEIGHT:
            wv = effect_params.get("weight_value", _DEFAULT_WEIGHT_VALUE)
            target = effect_params.get("target_item", "")
            etype_disp = (
                f"{_LABEL_SET_WEIGHT}（係数 ×{wv:g}・対象: {target}）"
                if target else f"{_LABEL_SET_WEIGHT}（係数 ×{wv:g}・対象は使用時選択）"
            )
        elif effect_type == _EFFECT_SET_FIXED_PROB:
            pv = effect_params.get("prob_value", _DEFAULT_PROB_VALUE)
            target = effect_params.get("target_item", "")
            etype_disp = (
                f"{_LABEL_SET_FIXED_PROB}（{pv:g}%・対象: {target}）"
                if target else f"{_LABEL_SET_FIXED_PROB}（{pv:g}%・対象は使用時選択）"
            )
        elif effect_type == _EFFECT_ADD_PROB:
            pv = effect_params.get("prob_value", _DEFAULT_PROB_VALUE)
            target = effect_params.get("target_item", "")
            etype_disp = (
                f"{_LABEL_ADD_PROB}（+{pv:g}%・対象: {target}）"
                if target else f"{_LABEL_ADD_PROB}（+{pv:g}%・対象は使用時選択）"
            )
        else:
            etype_disp = "なし"

        result_disp = _LABEL_RESULT.get(result_type, result_type or "—")
        lines = [
            f"【{name}】  発行者: {issuer}  結果: {result_disp}",
            f"効果タイプ: {etype_disp}",
            f"メモ: {effect_memo}",
        ]
        self._history_detail_lbl.setText("\n".join(lines))

    def _on_save_template(self) -> None:
        name = self._inp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "テンプレ保存", "チケット名が入力されていません。")
            return
        issuer = self._inp_issuer.text().strip()
        effect = self._inp_effect.toPlainText().strip()
        effect_type, effect_params = self._read_effect_from_ui()
        tmpl = {"ticket_name": name, "issuer": issuer, "effect": effect,
                "effect_type": effect_type, "effect_params": effect_params}
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
        self._set_effect_to_ui(
            tmpl.get("effect_type", _EFFECT_NONE),
            tmpl.get("effect_params", {}),
        )
        # フォームが閉じていれば開く
        if not self._form_toggle_btn.isChecked():
            self._form_toggle_btn.setChecked(True)

    def _on_use_ticket(self, row: int) -> None:
        holdings = self._current_holdings()
        if row >= len(holdings):
            return
        h = holdings[row]
        name        = h.get("ticket_name", "")
        issuer      = h.get("issuer", "")
        effect      = h.get("effect", "")
        effect_type = h.get("effect_type", _EFFECT_NONE)
        effect_params = h.get("effect_params", {})

        # i069: pointer_move チケットは別フロー（MainWindow に委譲）
        if effect_type == _EFFECT_POINTER_MOVE:
            max_deg = float(effect_params.get("max_move_deg", _DEFAULT_MAX_DEG))
            ticket_id = h.get("ticket_id", "")
            self.pointer_move_requested.emit(
                self._active_roulette_id, max_deg, name, issuer, effect, ticket_id
            )
            return

        # i076/i077: set_item_enabled チケットは別フロー（MainWindow に委譲）
        # i077: 対象項目は使用時選択のため target_item_id / enabled は送らない
        if effect_type == _EFFECT_SET_ITEM_ENABLED:
            ticket_id = h.get("ticket_id", "")
            self.set_item_enabled_requested.emit(
                self._active_roulette_id, name, issuer, effect, ticket_id
            )
            return

        # i086: set_weight チケットは別フロー（MainWindow に委譲）
        # 対象項目は使用時選択のため ticket_id と基本情報のみ送る
        if effect_type == _EFFECT_SET_WEIGHT:
            ticket_id = h.get("ticket_id", "")
            self.set_item_weight_requested.emit(
                self._active_roulette_id, name, issuer, effect, ticket_id
            )
            return

        # i087: set_fixed_prob / add_prob チケットは別フロー（MainWindow に委譲）
        if effect_type in (_EFFECT_SET_FIXED_PROB, _EFFECT_ADD_PROB):
            ticket_id = h.get("ticket_id", "")
            self.set_prob_effect_requested.emit(
                self._active_roulette_id, name, issuer, effect, ticket_id
            )
            return

        # i066/i067: ConfirmOverlay（OBS 可視・汎用確認 UI）を使用
        effect_body = (effect or "").strip()[:120]
        overlay = ConfirmOverlay(
            title   = f"チケット「{name}」の使用結果",
            body    = effect_body,
            buttons = [
                ("✓  成功", _RESULT_SUCCESS, "primary"),
                ("✗  ドブ", _RESULT_DOBU,    "danger"),
                ("キャンセル", "__cancel__",  "cancel"),
            ],
            design  = self._design,
            parent  = self,
        )

        def _on_chosen(value: str) -> None:
            overlay.hide()
            overlay.deleteLater()
            if value == "__cancel__":
                return
            # i071: ticket_id を使って ID ベースで削除（同名チケット誤削除防止）
            _tid = h.get("ticket_id", "")
            self._remove_one_holding(name, issuer, effect, ticket_id=_tid)
            # i073: effect_type / effect_params も履歴に保存（復活時の復元に使用）
            self._append_history(name, issuer, effect, _ACTION_USE, value,
                                 effect_type=h.get("effect_type", _EFFECT_NONE),
                                 effect_params=h.get("effect_params", {}))
            self._refresh_holdings_table()
            self._refresh_history_table()
            if self._tabs.currentIndex() == 2:
                self._refresh_summary()
            self.data_changed.emit()

        overlay.chosen.connect(_on_chosen)

    def _on_delete_ticket(self, row: int) -> None:
        holdings = self._current_holdings()
        if row >= len(holdings):
            return
        h = holdings[row]
        name      = h.get("ticket_name", "")
        issuer    = h.get("issuer", "")
        effect    = h.get("effect", "")
        # i071: ticket_id を明示的に渡して ID ベースで削除する（同名チケット誤削除防止）
        ticket_id = h.get("ticket_id", "")

        # i053: 削除は保有から取り除くのみ（履歴・集計に記録しない）
        self._remove_one_holding(name, issuer, effect, ticket_id=ticket_id)

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
            # i067: QMessageBox → ConfirmOverlay（OBS 可視）
            effect_body = (effect or "").strip()[:120]
            overlay = ConfirmOverlay(
                title   = f"チケット「{name}」を復活しますか？",
                body    = effect_body,
                buttons = [
                    ("復活する", "__revive__", "primary"),
                    ("キャンセル", "__cancel__", "cancel"),
                ],
                design  = self._design,
                parent  = self,
            )

            def _on_revive_chosen(value: str, _orig=orig_idx,
                                  _n=name, _iss=issuer, _eff=effect,
                                  _etype=h.get("effect_type", _EFFECT_NONE),
                                  _eparams=dict(h.get("effect_params", {}))) -> None:
                overlay.hide()
                overlay.deleteLater()
                if value == "__cancel__":
                    return
                _hist = self._current_history()
                if _orig < len(_hist):
                    _hist[_orig]["result_type"] = _RESULT_REVIVED
                # i073: effect_type / effect_params を履歴から復元して保有に戻す
                self._add_holding(_n, _iss, _eff, qty=1,
                                  effect_type=_etype, effect_params=_eparams)
                self._refresh_holdings_table()
                self._refresh_history_table()
                if self._tabs.currentIndex() == 2:
                    self._refresh_summary()
                self.data_changed.emit()

            overlay.chosen.connect(_on_revive_chosen)
            return  # 非同期で処理

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
            # i067: QMessageBox → ConfirmOverlay（OBS 可視）
            effect_body = (effect or "").strip()[:120]
            overlay = ConfirmOverlay(
                title   = f"「{name}」の復活を取り消しますか？",
                body    = (effect_body + "\n" if effect_body else "") + "保有から1個差し引きます。",
                buttons = [
                    ("取り消す", "__undo__",   "danger"),
                    ("キャンセル", "__cancel__", "cancel"),
                ],
                design  = self._design,
                parent  = self,
            )

            def _on_undo_chosen(value: str, _orig=orig_idx,
                                _n=name, _iss=issuer, _eff=effect) -> None:
                overlay.hide()
                overlay.deleteLater()
                if value == "__cancel__":
                    return
                _hist = self._current_history()
                if _orig < len(_hist):
                    _hist[_orig]["result_type"] = _RESULT_DOBU
                self._remove_one_holding(_n, _iss, _eff)
                self._refresh_holdings_table()
                self._refresh_history_table()
                if self._tabs.currentIndex() == 2:
                    self._refresh_summary()
                self.data_changed.emit()

            overlay.chosen.connect(_on_undo_chosen)
            return  # 非同期で処理

        # result_type が成功 / none 等は何もしない

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

    def _on_effect_type_changed(self, index: int) -> None:
        """効果タイプ変更時: pointer_move / set_weight のみ追加入力行を表示する。
        i077: set_item_enabled はチケット作成時にパラメータなし（使用時選択型）。
        i086: set_weight はチケット作成時に係数値のみ保持（対象項目は使用時選択型）。
        """
        etype = _EFFECT_TYPE_VALUES[index] if index < len(_EFFECT_TYPE_VALUES) else _EFFECT_NONE
        self._max_deg_row.setVisible(etype == _EFFECT_POINTER_MOVE)
        self._weight_value_row.setVisible(etype == _EFFECT_SET_WEIGHT)
        self._fixed_prob_row.setVisible(etype == _EFFECT_SET_FIXED_PROB)
        self._add_prob_row.setVisible(etype == _EFFECT_ADD_PROB)

    def _read_effect_from_ui(self) -> tuple[str, dict]:
        """フォームから effect_type と effect_params を読み取る。
        i077: set_item_enabled はパラメータなし（対象項目は使用時に選択）。
        i086: set_weight は係数値のみ保持（対象項目は使用時に選択）。
        """
        idx = self._effect_type_combo.currentIndex()
        etype = _EFFECT_TYPE_VALUES[idx] if idx < len(_EFFECT_TYPE_VALUES) else _EFFECT_NONE
        if etype == _EFFECT_POINTER_MOVE:
            deg = max(0.5, min(_MAX_DEG_LIMIT, self._max_deg_spinbox.value()))
            return etype, {"max_move_deg": deg}
        if etype == _EFFECT_SET_WEIGHT:
            wv = max(_WEIGHT_VALUE_MIN, min(_WEIGHT_VALUE_MAX, self._weight_value_spinbox.value()))
            return etype, {"weight_value": round(wv, 2)}
        if etype == _EFFECT_SET_FIXED_PROB:
            pv = max(_PROB_VALUE_MIN, min(_PROB_VALUE_MAX, self._fixed_prob_spinbox.value()))
            return etype, {"prob_value": round(pv, 1)}
        if etype == _EFFECT_ADD_PROB:
            pv = max(_PROB_VALUE_MIN, min(_PROB_VALUE_MAX, self._add_prob_spinbox.value()))
            return etype, {"prob_value": round(pv, 1)}
        return etype, {}

    def _set_effect_to_ui(self, effect_type: str, effect_params: dict) -> None:
        """効果タイプと効果パラメータをフォームに反映する。"""
        idx = _EFFECT_TYPE_VALUES.index(effect_type) if effect_type in _EFFECT_TYPE_VALUES else 0
        self._effect_type_combo.setCurrentIndex(idx)
        if effect_type == _EFFECT_POINTER_MOVE:
            max_deg = float(effect_params.get("max_move_deg", _DEFAULT_MAX_DEG))
            self._max_deg_spinbox.setValue(max(0.5, min(_MAX_DEG_LIMIT, max_deg)))
        elif effect_type == _EFFECT_SET_WEIGHT:
            wv = float(effect_params.get("weight_value", _DEFAULT_WEIGHT_VALUE))
            self._weight_value_spinbox.setValue(max(_WEIGHT_VALUE_MIN, min(_WEIGHT_VALUE_MAX, wv)))
        elif effect_type == _EFFECT_SET_FIXED_PROB:
            pv = float(effect_params.get("prob_value", _DEFAULT_PROB_VALUE))
            self._fixed_prob_spinbox.setValue(max(_PROB_VALUE_MIN, min(_PROB_VALUE_MAX, pv)))
        elif effect_type == _EFFECT_ADD_PROB:
            pv = float(effect_params.get("prob_value", _DEFAULT_PROB_VALUE))
            self._add_prob_spinbox.setValue(max(_PROB_VALUE_MIN, min(_PROB_VALUE_MAX, pv)))

    # ================================================================
    #  公開 API — pointer_move チケット使用確定（MainWindow から呼ばれる）
    # ================================================================

    def consume_ticket_pointer_move(self, name: str, issuer: str, effect: str,
                                     ticket_id: str = "") -> bool:
        """pointer_move チケットを保有から取り除く (i070/i072/i073)。

        i072: 履歴への記録は drag release + 成功/ドブ選択後に
        finalize_pointer_move_ticket() で行う。ここでは保有削除のみ。
        i073: 削除前に effect_type / effect_params を一時保存（履歴記録時に使用）。

        i070: ticket_id を渡すことで同名チケットの識別が可能。
        MainWindow が pointer_move mode への移行を確認してから呼ぶ。
        """
        # i073: 削除前に効果情報を一時保存
        holdings = self._current_holdings()
        h_match = next(
            (h for h in holdings
             if (ticket_id and h.get("ticket_id") == ticket_id)
             or (not ticket_id and h.get("ticket_name") == name
                 and h.get("issuer") == issuer and h.get("effect") == effect)),
            {}
        )
        self._pm_pending_effect_type = h_match.get("effect_type", _EFFECT_NONE)
        self._pm_pending_effect_params = dict(h_match.get("effect_params", {}))

        if not self._remove_one_holding(name, issuer, effect, ticket_id=ticket_id):
            return False
        self._refresh_holdings_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()
        return True

    # ================================================================
    #  公開 API — set_item_enabled チケット使用確定（MainWindow から呼ばれる）
    # ================================================================

    def consume_ticket_set_item_enabled(self, name: str, issuer: str, effect: str,
                                         ticket_id: str = "",
                                         target_item_text: str = "") -> bool:
        """set_item_enabled チケットを消費して履歴（success）に記録する (i076).

        バリデーションは MainWindow 側で完了済みのため、ここでは削除と記録のみ。
        ticket_id を渡すことで同名チケットの誤削除を防ぐ。
        i083: target_item_text を effect_params に保存して履歴詳細で確認できるようにする。
        """
        holdings = self._current_holdings()
        h_match = next(
            (h for h in holdings
             if (ticket_id and h.get("ticket_id") == ticket_id)
             or (not ticket_id and h.get("ticket_name") == name
                 and h.get("issuer") == issuer and h.get("effect") == effect)),
            {}
        )
        etype = h_match.get("effect_type", _EFFECT_NONE)
        eparams = dict(h_match.get("effect_params", {}))
        # i083: 使用時に選んだ対象項目名を記録
        if target_item_text:
            eparams["target_item"] = target_item_text

        if not self._remove_one_holding(name, issuer, effect, ticket_id=ticket_id):
            return False
        self._append_history(name, issuer, effect, _ACTION_USE, _RESULT_SUCCESS,
                             effect_type=etype, effect_params=eparams)
        self._refresh_holdings_table()
        self._refresh_history_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()
        return True

    # ================================================================
    #  公開 API — 項目重み係数指定チケット使用確定（MainWindow から呼ばれる）
    # ================================================================

    def consume_ticket_set_weight(self, name: str, issuer: str, effect: str,
                                   ticket_id: str = "") -> bool:
        """set_weight チケットを保有から削除する (i086/i088).

        i088: 結果判定化のため、履歴記録はここでは行わない。
        MainWindow 側で結果選択後に finalize_ticket_with_result() で記録する。
        ticket_id を渡すことで同名チケットの誤削除を防ぐ。
        """
        if not self._remove_one_holding(name, issuer, effect, ticket_id=ticket_id):
            return False
        self._refresh_holdings_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()
        return True

    # ================================================================
    #  公開 API — 確率指定チケット使用確定（MainWindow から呼ばれる）
    # ================================================================

    def consume_ticket_set_prob(self, name: str, issuer: str, effect: str,
                                 ticket_id: str = "") -> bool:
        """set_fixed_prob / add_prob チケットを保有から削除する (i087/i088).

        i088: 結果判定化のため、履歴記録はここでは行わない。
        MainWindow 側で結果選択後に finalize_ticket_with_result() で記録する。
        ticket_id を渡すことで同名チケットの誤削除を防ぐ。
        """
        if not self._remove_one_holding(name, issuer, effect, ticket_id=ticket_id):
            return False
        self._refresh_holdings_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()
        return True

    def finalize_ticket_with_result(self, name: str, issuer: str, effect: str,
                                     result_value: str,
                                     effect_type: str = "",
                                     effect_params: dict | None = None) -> None:
        """重み係数・固定確率・追加確率チケットの使用結果を履歴に記録する (i088).

        MainWindow 側で結果選択（成功 / ドブ）後に呼ぶ。
        result_value: "success" / "dobu" / "none"（結果不明・リセット後など）
        """
        self._append_history(name, issuer, effect, _ACTION_USE, result_value,
                             effect_type=effect_type or _EFFECT_NONE,
                             effect_params=effect_params or {})
        self._refresh_history_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()

    def show_result_selection_overlay(self, ticket_name: str, effect: str,
                                       on_chosen) -> None:
        """ルーレット結果表示後の成功 / ドブ選択オーバーレイを表示する (i088).

        on_chosen(value: str) に "success" / "dobu" / "__cancel__" を渡す。
        """
        overlay = ConfirmOverlay(
            title=f"チケット「{ticket_name}」の使用結果",
            body=(effect or "").strip()[:120],
            buttons=[
                ("✓  成功", _RESULT_SUCCESS, "primary"),
                ("✗  ドブ", _RESULT_DOBU,    "danger"),
                ("キャンセル", "__cancel__",  "cancel"),
            ],
            design=self._design,
            parent=self,
        )

        def _on_button(value: str) -> None:
            overlay.hide()
            overlay.deleteLater()
            on_chosen(value)

        overlay.chosen.connect(_on_button)

    def show_prob_select_overlay(
        self,
        title: str,
        items: list[tuple[str, str]],
        on_selected,
        on_cancelled,
    ) -> None:
        """確率指定チケット使用時の選択オーバーレイを表示する (i087)。

        Args:
            title: ダイアログタイトル（係数値・追加値を含む呼び出し側で整形する）。
            items: [(item_id, display_text), ...] の ON 項目リスト。
            on_selected: 項目選択時のコールバック (item_id: str)。
            on_cancelled: キャンセル時のコールバック。
        """
        overlay = ItemSelectOverlay(
            title=title,
            items=items,
            design=self._design,
            parent=self,
        )

        def _on_chosen(item_id: str) -> None:
            overlay.hide()
            overlay.deleteLater()
            if item_id:
                on_selected(item_id)
            else:
                on_cancelled()

        overlay.chosen.connect(_on_chosen)

    # ================================================================
    #  公開 API — 項目非表示チケット使用時選択オーバーレイ（MainWindow から呼ばれる）
    # ================================================================

    def show_item_hide_select_overlay(
        self,
        items: list[tuple[str, str]],
        on_selected,
        on_cancelled,
    ) -> None:
        """項目非表示チケット使用時の選択オーバーレイを表示する (i077)。

        OBS に映る ItemSelectOverlay を TicketPanel 上に表示し、
        選択 / キャンセルをコールバックで通知する。

        Args:
            items: [(item_id, display_text), ...] の有効（enabled=True）項目リスト。
            on_selected: 項目ボタン押下時のコールバック (item_id: str)。
            on_cancelled: キャンセル時のコールバック。
        """
        overlay = ItemSelectOverlay(
            title="非表示にする項目を選んでください",
            items=items,
            design=self._design,
            parent=self,
        )

        def _on_chosen(item_id: str) -> None:
            overlay.hide()
            overlay.deleteLater()
            if item_id:
                on_selected(item_id)
            else:
                on_cancelled()

        overlay.chosen.connect(_on_chosen)

    def show_weight_select_overlay(
        self,
        weight_value: float,
        items: list[tuple[str, str]],
        on_selected,
        on_cancelled,
    ) -> None:
        """重み係数指定チケット使用時の選択オーバーレイを表示する (i086)。

        OBS に映る ItemSelectOverlay を TicketPanel 上に表示し、
        選択 / キャンセルをコールバックで通知する。

        Args:
            weight_value: 適用する重み係数値（タイトル表示用）。
            items: [(item_id, display_text), ...] の ON 項目リスト。
                   display_text は「項目名 / 係数 X / Y.Y%」の形式で呼び出し側が整形する。
            on_selected: 項目ボタン押下時のコールバック (item_id: str)。
            on_cancelled: キャンセル時のコールバック。
        """
        overlay = ItemSelectOverlay(
            title=f"重み係数 ×{weight_value:g} を適用する項目を選んでください",
            items=items,
            design=self._design,
            parent=self,
        )

        def _on_chosen(item_id: str) -> None:
            overlay.hide()
            overlay.deleteLater()
            if item_id:
                on_selected(item_id)
            else:
                on_cancelled()

        overlay.chosen.connect(_on_chosen)

    def finalize_pointer_move_ticket(self, name: str, issuer: str, effect: str,
                                      result_value: str) -> None:
        """pointer_move チケットの使用結果（成功 / ドブ）を履歴に記録する (i072/i073)。

        drag release → 成功/ドブ選択後に show_pointer_move_result_selection の
        コールバック (i073) から呼ばれる。

        Args:
            name: チケット名
            issuer: 発行者
            effect: 効果メモ
            result_value: "success" または "dobu"
        """
        self._append_history(name, issuer, effect, _ACTION_USE, result_value,
                             effect_type=self._pm_pending_effect_type,
                             effect_params=self._pm_pending_effect_params)
        self._refresh_history_table()
        if self._tabs.currentIndex() == 2:
            self._refresh_summary()
        self.data_changed.emit()

    def show_pointer_move_result_selection(self, name: str, issuer: str,
                                           effect: str) -> None:
        """pointer_move drag release 後の成功/ドブ選択オーバーレイを TicketPanel 上に表示する (i073)。

        ConfirmOverlay を TicketPanel 上に表示し、選択結果を
        finalize_pointer_move_ticket() に渡す。
        """
        overlay = ConfirmOverlay(
            title=f"チケット「{name}」の使用結果",
            body=(effect or "").strip()[:120],
            buttons=[
                ("✓  成功", "success", "primary"),
                ("✗  ドブ", "dobu",    "danger"),
                ("キャンセル", "__cancel__", "cancel"),
            ],
            design=self._design,
            parent=self,
        )

        def _on_chosen(value: str) -> None:
            overlay.hide()
            overlay.deleteLater()
            if value == "__cancel__":
                return
            self.finalize_pointer_move_ticket(name, issuer, effect, value)

        overlay.chosen.connect(_on_chosen)

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
