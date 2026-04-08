"""
PySide6 プロトタイプ — マクロアクション閲覧・最小編集ダイアログ

macro action リストビューに、フラット action の追加・削除・詳細編集を最小導入。
action_summary() による1行表示と、選択 action の詳細確認を提供する。

責務:
  - action 列の一覧表示
  - 選択 action の主要フィールド詳細表示（読み取り専用）
  - 保存時 validation 結果の表示
  - フラット action の追加・削除・詳細編集（BranchOnWinner は対象外）

正式 macro エディタの前段として、表示責務と最小編集導線を固定する目的。
"""

from __future__ import annotations

import json
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QTextEdit,
    QLabel, QPushButton, QSplitter, QWidget,
    QMenu, QLineEdit, QCheckBox, QMessageBox,
    QFileDialog, QComboBox,
)

from roulette_actions import (
    RouletteAction,
    AddRoulette, RemoveRoulette, SetActiveRoulette,
    SpinRoulette, UpdateItemEntries, UpdateSettings,
    BranchOnWinner,
)
from roulette_action_codec import action_summary, validate_action_for_save


# action の追加メニュー定義
_ACTION_TEMPLATES: list[tuple[str, type]] = [
    ("SpinRoulette", SpinRoulette),
    ("SetActiveRoulette", SetActiveRoulette),
    ("AddRoulette", AddRoulette),
    ("RemoveRoulette", RemoveRoulette),
    ("UpdateSettings", UpdateSettings),
    ("UpdateItemEntries", UpdateItemEntries),
    ("BranchOnWinner", BranchOnWinner),
]


def _create_default_action(cls: type, active_roulette_id: str) -> RouletteAction:
    """action をデフォルト初期値で生成する。

    初期値方針:
      - roulette_id を持つ action: active_roulette_id を使用
      - SpinRoulette: 空文字（= active 対象）
      - AddRoulette: activate=True
      - UpdateSettings: key/value 空（validation NG になるが構造は分かる）
      - UpdateItemEntries: 空 entries
      - BranchOnWinner: source_roulette_id=active, winner_text 空, then/else 空
    """
    if cls is SpinRoulette:
        return SpinRoulette()
    elif cls is SetActiveRoulette:
        return SetActiveRoulette(roulette_id=active_roulette_id)
    elif cls is AddRoulette:
        return AddRoulette(activate=True)
    elif cls is RemoveRoulette:
        return RemoveRoulette(roulette_id=active_roulette_id)
    elif cls is UpdateSettings:
        return UpdateSettings()
    elif cls is UpdateItemEntries:
        return UpdateItemEntries(roulette_id=active_roulette_id)
    elif cls is BranchOnWinner:
        return BranchOnWinner(source_roulette_id=active_roulette_id)
    return cls()


# ================================================================
#  ActionEditDialog — action 詳細編集ダイアログ
# ================================================================

class ActionEditDialog(QDialog):
    """action の詳細編集ダイアログ。

    action type ごとにフォームを生成し、確定時に新しい frozen dataclass を返す。

    編集方式:
      - str fields: QLineEdit
      - bool fields: QCheckBox
      - UpdateSettings.value: raw JSON 文字列入力（QLineEdit）
      - UpdateItemEntries.entries: raw JSON 文字列入力（QTextEdit）
      - BranchOnWinner: source_roulette_id / winner_text のみ編集可能
        then_actions / else_actions は既存値を維持（編集対象外）
    """

    def __init__(self, action: RouletteAction, parent=None):
        super().__init__(parent)
        self._original = action
        self._result: RouletteAction | None = None
        self._fields: dict[str, QWidget] = {}

        type_name = type(action).__name__
        self.setWindowTitle(f"Edit: {type_name}")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # type 表示（編集不可）
        type_label = QLabel(f"type: {type_name}")
        type_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(type_label)

        # フォーム
        form = QFormLayout()
        self._build_form(action, form)
        layout.addLayout(form)

        # エラー表示ラベル
        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: red;")
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        # OK / Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    @property
    def result_action(self) -> RouletteAction | None:
        """編集確定後の action を返す。Cancel 時は None。"""
        return self._result

    def _build_form(self, action: RouletteAction, form: QFormLayout):
        """action type に応じたフォームを生成する。"""
        if isinstance(action, SpinRoulette):
            self._add_line("roulette_id", action.roulette_id, form,
                           placeholder="空文字 = active 対象")

        elif isinstance(action, SetActiveRoulette):
            self._add_line("roulette_id", action.roulette_id, form)

        elif isinstance(action, AddRoulette):
            self._add_check("activate", action.activate, form)

        elif isinstance(action, RemoveRoulette):
            self._add_line("roulette_id", action.roulette_id, form)

        elif isinstance(action, UpdateSettings):
            self._add_line("key", action.key, form)
            self._add_line("value (JSON)", self._value_to_json(action.value), form,
                           key="value_json")

        elif isinstance(action, UpdateItemEntries):
            self._add_line("roulette_id", action.roulette_id, form)
            self._add_text("entries (JSON)", self._entries_to_json(action.entries), form,
                           key="entries_json")

        elif isinstance(action, BranchOnWinner):
            self._add_line("source_roulette_id", action.source_roulette_id, form)
            self._add_line("winner_text", action.winner_text, form)
            # then/else は read-only 情報として表示
            info = QLabel(f"then_actions: {len(action.then_actions)} 件  /  "
                          f"else_actions: {len(action.else_actions)} 件")
            info.setStyleSheet("color: gray;")
            form.addRow("子 actions:", info)

    def _add_line(self, label: str, value: str, form: QFormLayout, *,
                  key: str = "", placeholder: str = ""):
        field_key = key or label
        edit = QLineEdit(value)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        self._fields[field_key] = edit
        form.addRow(label + ":", edit)

    def _add_check(self, label: str, value: bool, form: QFormLayout):
        cb = QCheckBox()
        cb.setChecked(value)
        self._fields[label] = cb
        form.addRow(label + ":", cb)

    def _add_text(self, label: str, value: str, form: QFormLayout, *,
                  key: str = ""):
        field_key = key or label
        edit = QTextEdit()
        edit.setPlainText(value)
        edit.setMaximumHeight(120)
        self._fields[field_key] = edit
        form.addRow(label + ":", edit)

    def _on_ok(self):
        """OK 押下時: 入力値から新 action を生成する。"""
        self._error_label.setText("")
        try:
            new_action = self._build_action()
        except _EditError as e:
            self._error_label.setText(str(e))
            return
        self._result = new_action
        self.accept()

    def _build_action(self) -> RouletteAction:
        """入力値から新しい action を構築する。parse エラー時は _EditError。"""
        action = self._original

        if isinstance(action, SpinRoulette):
            return SpinRoulette(
                roulette_id=self._get_text("roulette_id"),
            )
        elif isinstance(action, SetActiveRoulette):
            return SetActiveRoulette(
                roulette_id=self._get_text("roulette_id"),
            )
        elif isinstance(action, AddRoulette):
            return AddRoulette(
                activate=self._get_bool("activate"),
            )
        elif isinstance(action, RemoveRoulette):
            return RemoveRoulette(
                roulette_id=self._get_text("roulette_id"),
            )
        elif isinstance(action, UpdateSettings):
            key = self._get_text("key")
            value = self._parse_json_value(self._get_text("value_json"), "value")
            return UpdateSettings(key=key, value=value)

        elif isinstance(action, UpdateItemEntries):
            rid = self._get_text("roulette_id")
            entries_raw = self._parse_json_value(
                self._get_multiline_text("entries_json"), "entries"
            )
            if not isinstance(entries_raw, list):
                raise _EditError("entries: JSON の値は配列 ([...]) である必要があります")
            return UpdateItemEntries(roulette_id=rid, entries=tuple(entries_raw))

        elif isinstance(action, BranchOnWinner):
            return BranchOnWinner(
                source_roulette_id=self._get_text("source_roulette_id"),
                winner_text=self._get_text("winner_text"),
                match_mode=action.match_mode,
                regex_ignore_case=action.regex_ignore_case,
                numeric_operator=action.numeric_operator,
                numeric_value=action.numeric_value,
                compound_logic=action.compound_logic,
                cond2_match_mode=action.cond2_match_mode,
                cond2_winner_text=action.cond2_winner_text,
                cond2_regex_ignore_case=action.cond2_regex_ignore_case,
                cond2_numeric_operator=action.cond2_numeric_operator,
                cond2_numeric_value=action.cond2_numeric_value,
                then_actions=action.then_actions,
                else_actions=action.else_actions,
            )

        raise _EditError(f"未対応の action type: {type(action).__name__}")

    def _get_text(self, key: str) -> str:
        w = self._fields[key]
        if isinstance(w, QLineEdit):
            return w.text()
        return ""

    def _get_bool(self, key: str) -> bool:
        w = self._fields[key]
        if isinstance(w, QCheckBox):
            return w.isChecked()
        return False

    def _get_multiline_text(self, key: str) -> str:
        w = self._fields[key]
        if isinstance(w, QTextEdit):
            return w.toPlainText()
        return ""

    @staticmethod
    def _parse_json_value(text: str, field_name: str) -> object:
        """JSON 文字列を parse する。失敗時は _EditError。"""
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise _EditError(f"{field_name}: JSON parse エラー — {e}")

    @staticmethod
    def _value_to_json(value: object) -> str:
        """value を JSON 文字列に変換する。"""
        if value is None:
            return ""
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _entries_to_json(entries: tuple) -> str:
        """entries を JSON 文字列に変換する。"""
        if not entries:
            return "[]"
        return json.dumps(list(entries), ensure_ascii=False, indent=2)


class _EditError(Exception):
    """編集ダイアログ内の入力エラー。"""


# child action で許可する action types（BranchOnWinner を含む）
_CHILD_ACTION_TEMPLATES: list[tuple[str, type]] = [
    ("SpinRoulette", SpinRoulette),
    ("SetActiveRoulette", SetActiveRoulette),
    ("AddRoulette", AddRoulette),
    ("RemoveRoulette", RemoveRoulette),
    ("UpdateSettings", UpdateSettings),
    ("UpdateItemEntries", UpdateItemEntries),
    ("BranchOnWinner", BranchOnWinner),
]


# ================================================================
#  _ChildActionPanel — then/else 子 action 編集パネル
# ================================================================

class _ChildActionPanel(QWidget):
    """then_actions / else_actions 1側分の子 action 編集パネル。

    QListWidget + 追加/削除/編集/↑↓ ボタンを内包する。
    """

    def __init__(self, label: str, actions: list[RouletteAction],
                 active_roulette_id: str, parent=None):
        super().__init__(parent)
        self._actions = actions
        self._active_roulette_id = active_roulette_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel(f"{label}:")
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._update_btn_states)
        layout.addWidget(self._list)

        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("+")
        self._add_btn.setFixedWidth(28)
        self._add_btn.clicked.connect(self._on_add)
        btn_layout.addWidget(self._add_btn)

        self._del_btn = QPushButton("-")
        self._del_btn.setFixedWidth(28)
        self._del_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(self._del_btn)

        self._edit_btn = QPushButton("...")
        self._edit_btn.setFixedWidth(28)
        self._edit_btn.setToolTip("編集")
        self._edit_btn.clicked.connect(self._on_edit)
        btn_layout.addWidget(self._edit_btn)

        self._up_btn = QPushButton("↑")
        self._up_btn.setFixedWidth(28)
        self._up_btn.clicked.connect(self._on_move_up)
        btn_layout.addWidget(self._up_btn)

        self._down_btn = QPushButton("↓")
        self._down_btn.setFixedWidth(28)
        self._down_btn.clicked.connect(self._on_move_down)
        btn_layout.addWidget(self._down_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._refresh_list()

    def get_actions(self) -> tuple:
        """現在の action 列を tuple で返す。"""
        return tuple(self._actions)

    def _refresh_list(self, *, select_row: int = -1):
        self._list.clear()
        for i, a in enumerate(self._actions):
            self._list.addItem(f"[{i}] {action_summary(a)}")
        if self._actions:
            row = select_row if 0 <= select_row < len(self._actions) else 0
            self._list.setCurrentRow(row)
        self._update_btn_states()

    def _update_btn_states(self):
        row = self._list.currentRow()
        count = len(self._actions)
        has_sel = 0 <= row < count
        self._del_btn.setEnabled(has_sel)
        self._edit_btn.setEnabled(has_sel)
        self._up_btn.setEnabled(has_sel and row > 0)
        self._down_btn.setEnabled(has_sel and row < count - 1)

    def _on_add(self):
        menu = QMenu(self)
        for label, cls in _CHILD_ACTION_TEMPLATES:
            act = menu.addAction(label)
            act.setData(cls)
        chosen = menu.exec(self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft()))
        if chosen is None:
            return
        cls = chosen.data()
        new_action = _create_default_action(cls, self._active_roulette_id)
        self._actions.append(new_action)
        self._refresh_list(select_row=len(self._actions) - 1)

    def _on_delete(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._actions):
            return
        del self._actions[row]
        self._refresh_list(select_row=min(row, len(self._actions) - 1))

    def _on_edit(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._actions):
            return
        action = self._actions[row]
        if isinstance(action, BranchOnWinner):
            dlg = BranchEditDialog(
                action,
                active_roulette_id=self._active_roulette_id,
                parent=self,
            )
        else:
            dlg = ActionEditDialog(action, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_action is not None:
            self._actions[row] = dlg.result_action
            self._refresh_list(select_row=row)

    def _on_move_up(self):
        row = self._list.currentRow()
        if row <= 0 or row >= len(self._actions):
            return
        self._actions[row - 1], self._actions[row] = self._actions[row], self._actions[row - 1]
        self._refresh_list(select_row=row - 1)

    def _on_move_down(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._actions) - 1:
            return
        self._actions[row], self._actions[row + 1] = self._actions[row + 1], self._actions[row]
        self._refresh_list(select_row=row + 1)


# ================================================================
#  BranchEditDialog — BranchOnWinner 専用編集ダイアログ
# ================================================================

class BranchEditDialog(QDialog):
    """BranchOnWinner の編集ダイアログ。

    source_roulette_id / winner_text を編集し、
    then_actions / else_actions を子 action パネルで追加・削除・編集・並べ替えできる。
    """

    def __init__(self, action: BranchOnWinner, *,
                 active_roulette_id: str = "", parent=None):
        super().__init__(parent)
        self._original = action
        self._result: BranchOnWinner | None = None
        self.setWindowTitle("Edit: BranchOnWinner")
        self.setMinimumSize(500, 400)
        self.resize(560, 480)

        layout = QVBoxLayout(self)

        # type 表示
        type_label = QLabel("type: BranchOnWinner")
        type_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(type_label)

        # source / winner フォーム
        form = QFormLayout()
        self._source_edit = QLineEdit(action.source_roulette_id)
        form.addRow("source_roulette_id:", self._source_edit)
        self._winner_edit = QLineEdit(action.winner_text)
        form.addRow("winner_text:", self._winner_edit)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("完全一致 (exact)", "exact")
        self._mode_combo.addItem("部分一致 (contains)", "contains")
        self._mode_combo.addItem("正規表現 (regex)", "regex")
        self._mode_combo.addItem("数値比較 (numeric)", "numeric")
        current_mode = action.match_mode or "exact"
        idx = self._mode_combo.findData(current_mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        form.addRow("match_mode:", self._mode_combo)
        self._ignore_case_cb = QCheckBox("大文字小文字を区別しない")
        self._ignore_case_cb.setChecked(action.regex_ignore_case)
        self._ignore_case_cb.setEnabled(current_mode == "regex")
        form.addRow("regex option:", self._ignore_case_cb)
        # numeric 用 UI
        self._numeric_op_combo = QComboBox()
        for op in ("==", "!=", ">", ">=", "<", "<="):
            self._numeric_op_combo.addItem(op, op)
        op_idx = self._numeric_op_combo.findData(action.numeric_operator or "==")
        if op_idx >= 0:
            self._numeric_op_combo.setCurrentIndex(op_idx)
        self._numeric_op_combo.setEnabled(current_mode == "numeric")
        form.addRow("numeric operator:", self._numeric_op_combo)
        self._numeric_value_edit = QLineEdit(action.numeric_value)
        self._numeric_value_edit.setPlaceholderText("比較値 (数値)")
        self._numeric_value_edit.setEnabled(current_mode == "numeric")
        form.addRow("numeric value:", self._numeric_value_edit)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addLayout(form)

        # --- compound logic ---
        compound_form = QFormLayout()
        self._logic_combo = QComboBox()
        self._logic_combo.addItem("なし (単一条件)", "")
        self._logic_combo.addItem("AND", "and")
        self._logic_combo.addItem("OR", "or")
        logic_idx = self._logic_combo.findData(action.compound_logic or "")
        if logic_idx >= 0:
            self._logic_combo.setCurrentIndex(logic_idx)
        compound_form.addRow("複合条件:", self._logic_combo)

        # 第2条件
        self._cond2_winner_edit = QLineEdit(action.cond2_winner_text)
        compound_form.addRow("cond2 winner_text:", self._cond2_winner_edit)
        self._cond2_mode_combo = QComboBox()
        self._cond2_mode_combo.addItem("完全一致 (exact)", "exact")
        self._cond2_mode_combo.addItem("部分一致 (contains)", "contains")
        self._cond2_mode_combo.addItem("正規表現 (regex)", "regex")
        self._cond2_mode_combo.addItem("数値比較 (numeric)", "numeric")
        c2_mode = action.cond2_match_mode or "exact"
        c2_idx = self._cond2_mode_combo.findData(c2_mode)
        if c2_idx >= 0:
            self._cond2_mode_combo.setCurrentIndex(c2_idx)
        compound_form.addRow("cond2 match_mode:", self._cond2_mode_combo)
        self._cond2_ignore_case_cb = QCheckBox("大文字小文字を区別しない")
        self._cond2_ignore_case_cb.setChecked(action.cond2_regex_ignore_case)
        compound_form.addRow("cond2 regex option:", self._cond2_ignore_case_cb)
        self._cond2_numeric_op_combo = QComboBox()
        for op in ("==", "!=", ">", ">=", "<", "<="):
            self._cond2_numeric_op_combo.addItem(op, op)
        c2_op_idx = self._cond2_numeric_op_combo.findData(action.cond2_numeric_operator or "==")
        if c2_op_idx >= 0:
            self._cond2_numeric_op_combo.setCurrentIndex(c2_op_idx)
        compound_form.addRow("cond2 numeric op:", self._cond2_numeric_op_combo)
        self._cond2_numeric_value_edit = QLineEdit(action.cond2_numeric_value)
        self._cond2_numeric_value_edit.setPlaceholderText("比較値 (数値)")
        compound_form.addRow("cond2 numeric value:", self._cond2_numeric_value_edit)
        layout.addLayout(compound_form)

        # compound UI の有効/無効連動
        self._logic_combo.currentIndexChanged.connect(self._on_logic_changed)
        self._cond2_mode_combo.currentIndexChanged.connect(self._on_cond2_mode_changed)
        self._on_logic_changed()

        # then / else パネル（横並び）
        panels_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._then_panel = _ChildActionPanel(
            "then_actions", list(action.then_actions),
            active_roulette_id, parent=self,
        )
        panels_splitter.addWidget(self._then_panel)
        self._else_panel = _ChildActionPanel(
            "else_actions", list(action.else_actions),
            active_roulette_id, parent=self,
        )
        panels_splitter.addWidget(self._else_panel)
        layout.addWidget(panels_splitter)

        # OK / Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    @property
    def result_action(self) -> BranchOnWinner | None:
        return self._result

    def _on_mode_changed(self):
        current = self._mode_combo.currentData()
        is_regex = current == "regex"
        is_numeric = current == "numeric"
        self._ignore_case_cb.setEnabled(is_regex)
        if not is_regex:
            self._ignore_case_cb.setChecked(False)
        self._numeric_op_combo.setEnabled(is_numeric)
        self._numeric_value_edit.setEnabled(is_numeric)

    def _on_logic_changed(self):
        enabled = self._logic_combo.currentData() in ("and", "or")
        self._cond2_winner_edit.setEnabled(enabled)
        self._cond2_mode_combo.setEnabled(enabled)
        self._cond2_ignore_case_cb.setEnabled(enabled)
        self._cond2_numeric_op_combo.setEnabled(enabled)
        self._cond2_numeric_value_edit.setEnabled(enabled)
        if enabled:
            self._on_cond2_mode_changed()

    def _on_cond2_mode_changed(self):
        c2_mode = self._cond2_mode_combo.currentData()
        is_compound = self._logic_combo.currentData() in ("and", "or")
        self._cond2_ignore_case_cb.setEnabled(is_compound and c2_mode == "regex")
        self._cond2_numeric_op_combo.setEnabled(is_compound and c2_mode == "numeric")
        self._cond2_numeric_value_edit.setEnabled(is_compound and c2_mode == "numeric")

    def _on_ok(self):
        self._result = BranchOnWinner(
            source_roulette_id=self._source_edit.text(),
            winner_text=self._winner_edit.text(),
            match_mode=self._mode_combo.currentData() or "exact",
            regex_ignore_case=self._ignore_case_cb.isChecked(),
            numeric_operator=self._numeric_op_combo.currentData() or "==",
            numeric_value=self._numeric_value_edit.text(),
            compound_logic=self._logic_combo.currentData() or "",
            cond2_match_mode=self._cond2_mode_combo.currentData() or "exact",
            cond2_winner_text=self._cond2_winner_edit.text(),
            cond2_regex_ignore_case=self._cond2_ignore_case_cb.isChecked(),
            cond2_numeric_operator=self._cond2_numeric_op_combo.currentData() or "==",
            cond2_numeric_value=self._cond2_numeric_value_edit.text(),
            then_actions=self._then_panel.get_actions(),
            else_actions=self._else_panel.get_actions(),
        )
        self.accept()


# ================================================================
#  MacroActionViewer
# ================================================================

class MacroActionViewer(QDialog):
    """macro action 一覧ダイアログ（閲覧 + フラット action 追加・削除・編集）。"""

    def __init__(self, actions: Sequence[RouletteAction], *,
                 active_roulette_id: str = "",
                 on_session_apply=None,
                 on_step=None,
                 on_run=None,
                 session=None,
                 get_auto_advancing=None,
                 parent=None):
        """
        Args:
            actions: 表示する action 列。
            active_roulette_id: 新規 action の初期値に使う active roulette ID。
            on_session_apply: session 反映コールバック。
                呼び出し形式: on_session_apply(actions: list[RouletteAction]) -> None
                None の場合は「Session反映」ボタンを無効化する。
            on_step: step 実行コールバック。呼び出し形式: on_step() -> None
            on_run: run 実行コールバック。呼び出し形式: on_run() -> None
            session: MacroPlaybackSession 参照（実行状態表示用）。
            get_auto_advancing: auto advance 状態取得コールバック。
                呼び出し形式: get_auto_advancing() -> bool
            parent: 親ウィジェット。
        """
        super().__init__(parent)
        self.setWindowTitle("Macro Action Viewer (dev)")
        self.setMinimumSize(600, 400)
        self.resize(720, 480)

        self._actions = list(actions)
        self._active_roulette_id = active_roulette_id
        self._on_session_apply = on_session_apply
        self._on_step = on_step
        self._on_run = on_run
        self._session = session
        self._get_auto_advancing = get_auto_advancing
        self._init_ui()
        self._populate_list()
        self._update_validation_status()
        self._update_execution_status()

    @property
    def actions(self) -> list[RouletteAction]:
        """現在の action 列を返す（外部から取得用）。"""
        return list(self._actions)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # --- 件数 + validation ステータス ---
        status_layout = QHBoxLayout()
        self._count_label = QLabel()
        status_layout.addWidget(self._count_label)
        status_layout.addStretch()
        self._validation_label = QLabel()
        status_layout.addWidget(self._validation_label)
        layout.addLayout(status_layout)

        # --- 実行状態ステータス ---
        self._exec_status_label = QLabel()
        self._exec_status_label.setStyleSheet("color: #555;")
        layout.addWidget(self._exec_status_label)

        # --- メイン: リスト（左） + 詳細（右） ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左: action 一覧
        self._list_widget = QListWidget()
        self._list_widget.currentRowChanged.connect(self._on_row_changed)
        splitter.addWidget(self._list_widget)

        # 右: 詳細表示
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        splitter.addWidget(self._detail_text)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

        # --- ボタン行: 追加 / 削除 / 編集 / ↑↓ / 閉じる ---
        btn_layout = QHBoxLayout()

        self._add_btn = QPushButton("追加...")
        self._add_btn.clicked.connect(self._on_add_clicked)
        btn_layout.addWidget(self._add_btn)

        self._delete_btn = QPushButton("削除")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        btn_layout.addWidget(self._delete_btn)

        self._edit_btn = QPushButton("編集...")
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        btn_layout.addWidget(self._edit_btn)

        self._up_btn = QPushButton("↑")
        self._up_btn.setFixedWidth(30)
        self._up_btn.clicked.connect(self._on_move_up)
        btn_layout.addWidget(self._up_btn)

        self._down_btn = QPushButton("↓")
        self._down_btn.setFixedWidth(30)
        self._down_btn.clicked.connect(self._on_move_down)
        btn_layout.addWidget(self._down_btn)

        btn_layout.addStretch()

        self._apply_btn = QPushButton("Session反映")
        self._apply_btn.clicked.connect(self._on_apply_to_session)
        if self._on_session_apply is None:
            self._apply_btn.setEnabled(False)
            self._apply_btn.setToolTip("session 反映コールバックが未設定です")
        btn_layout.addWidget(self._apply_btn)

        self._step_btn = QPushButton("Step")
        self._step_btn.clicked.connect(self._on_step_clicked)
        if self._on_step is None:
            self._step_btn.setEnabled(False)
        btn_layout.addWidget(self._step_btn)

        self._run_btn = QPushButton("Run")
        self._run_btn.clicked.connect(self._on_run_clicked)
        if self._on_run is None:
            self._run_btn.setEnabled(False)
        btn_layout.addWidget(self._run_btn)

        self._load_btn = QPushButton("読込...")
        self._load_btn.clicked.connect(self._on_load_clicked)
        btn_layout.addWidget(self._load_btn)

        self._save_btn = QPushButton("保存...")
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self._save_btn)

        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    # ================================================================
    #  追加
    # ================================================================

    def _on_add_clicked(self):
        """追加ボタン: フラット action type を選ぶメニューを表示する。"""
        menu = QMenu(self)
        for label, cls in _ACTION_TEMPLATES:
            action = menu.addAction(label)
            action.setData(cls)
        chosen = menu.exec(self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft()))
        if chosen is None:
            return
        cls = chosen.data()
        new_action = _create_default_action(cls, self._active_roulette_id)
        self._actions.append(new_action)
        self._refresh_after_change(select_row=len(self._actions) - 1)

    # ================================================================
    #  削除
    # ================================================================

    def _on_delete_clicked(self):
        """削除ボタン: 選択中の action を削除する。"""
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._actions):
            return
        del self._actions[row]
        next_row = min(row, len(self._actions) - 1)
        self._refresh_after_change(select_row=next_row)

    # ================================================================
    #  編集
    # ================================================================

    def _on_edit_clicked(self):
        """編集ボタン: 選択中の action の詳細編集ダイアログを開く。"""
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._actions):
            return
        action = self._actions[row]

        if isinstance(action, BranchOnWinner):
            dlg = BranchEditDialog(
                action,
                active_roulette_id=self._active_roulette_id,
                parent=self,
            )
        else:
            dlg = ActionEditDialog(action, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_action is not None:
            self._actions[row] = dlg.result_action
            self._refresh_after_change(select_row=row)

    # ================================================================
    #  保存
    # ================================================================

    def _on_save_clicked(self):
        """保存ボタン: validation → ファイル選択 → JSON 保存。"""
        # 1. validation ゲート
        all_errors: list[str] = []
        for i, action in enumerate(self._actions):
            for e in validate_action_for_save(action):
                all_errors.append(f"[{i}] {e}")

        if all_errors:
            msg = "Validation NG のため保存できません。\n\n"
            msg += "\n".join(all_errors[:10])
            if len(all_errors) > 10:
                msg += f"\n... 他 {len(all_errors) - 10} 件"
            QMessageBox.warning(self, "保存不可", msg)
            return

        if not self._actions:
            QMessageBox.information(self, "保存", "保存する action がありません。")
            return

        # 2. ファイル選択
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Macro Action を JSON 保存",
            "macro.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        # 3. 保存
        from roulette_action_io import save_actions_json, ActionIOError
        try:
            save_actions_json(path, self._actions)
        except ActionIOError as e:
            QMessageBox.critical(self, "保存エラー", f"保存に失敗しました。\n\n{e}")
            return

        QMessageBox.information(
            self, "保存完了",
            f"{len(self._actions)} 件の action を保存しました。\n{path}",
        )

    # ================================================================
    #  Session 反映
    # ================================================================

    def _on_apply_to_session(self):
        """Session反映ボタン: viewer の action 列を current macro session へ反映する。

        validation NG でも反映を許可する。
        理由: 読込（i135）と同様に、構造上有効な action 列はそのまま session に
        セットし、実行時の safety check で安全側停止する方針を維持するため。
        保存時のみ validation ゲートをかける（i134）。
        """
        if self._on_session_apply is None:
            return
        if not self._actions:
            QMessageBox.information(self, "Session反映", "反映する action がありません。")
            return

        self._on_session_apply(list(self._actions))
        self.setWindowTitle("Macro Action Viewer (dev) — session (反映済み)")
        QMessageBox.information(
            self, "Session反映完了",
            f"{len(self._actions)} 件の action を session へ反映しました。",
        )

    # ================================================================
    #  Step / Run
    # ================================================================

    def _ensure_session_applied(self):
        """step/run 実行前に session 反映を行う。"""
        if self._on_session_apply is None:
            return False
        if not self._actions:
            return False
        self._on_session_apply(list(self._actions))
        self.setWindowTitle("Macro Action Viewer (dev) — session (反映済み)")
        self._update_execution_status()
        return True

    def _on_step_clicked(self):
        """Stepボタン: session 反映後に step を実行する。"""
        if self._on_step is None:
            return
        self._ensure_session_applied()
        self._on_step()
        self._update_execution_status()

    def _on_run_clicked(self):
        """Runボタン: session 反映後に run を実行する。"""
        if self._on_run is None:
            return
        self._ensure_session_applied()
        self._on_run()
        self._update_execution_status()

    # ================================================================
    #  実行状態表示
    # ================================================================

    def _update_execution_status(self):
        """session の実行状態をステータスラベルとリストハイライトに反映する。"""
        if self._session is None:
            self._exec_status_label.setText("Session: (未接続)")
            self._exec_status_label.setStyleSheet("color: #999;")
            return

        idx = self._session.current_index
        total = self._session.total_count
        remaining = self._session.remaining_count()

        # auto advancing 状態
        is_running = False
        if self._get_auto_advancing is not None:
            is_running = self._get_auto_advancing()

        if total == 0:
            status = "Session: 空"
            style = "color: #999;"
        elif is_running:
            status = f"Session: 実行中 [{idx}/{total}] (残り {remaining})"
            style = "color: #0070c0; font-weight: bold;"
        elif remaining == 0:
            status = f"Session: 完了 [{idx}/{total}]"
            style = "color: green; font-weight: bold;"
        else:
            status = f"Session: 待機 [{idx}/{total}] (残り {remaining})"
            style = "color: #555;"

        self._exec_status_label.setText(status)
        self._exec_status_label.setStyleSheet(style)

        # リスト上で実行位置をハイライト
        self._highlight_execution_position(idx, total)

    def _highlight_execution_position(self, exec_index: int, exec_total: int):
        """リスト上で実行済み / 次の実行対象 / 未実行をハイライトする。"""
        from PySide6.QtGui import QColor, QBrush
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is None:
                continue
            if exec_total == 0:
                item.setBackground(QBrush())
                item.setForeground(QBrush())
                continue
            if i < exec_index:
                # 実行済み: 薄いグレー
                item.setForeground(QBrush(QColor(160, 160, 160)))
                item.setBackground(QBrush())
            elif i == exec_index:
                # 次の実行対象: 背景ハイライト
                item.setForeground(QBrush())
                item.setBackground(QBrush(QColor(220, 235, 255)))
            else:
                # 未実行: デフォルト
                item.setForeground(QBrush())
                item.setBackground(QBrush())

    # ================================================================
    #  読込
    # ================================================================

    def _on_load_clicked(self):
        """読込ボタン: JSON ファイルを選択し、action 列を差し替える。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Macro Action JSON を読込",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        from roulette_action_io import load_actions_json, ActionIOError
        try:
            actions = load_actions_json(path)
        except ActionIOError as e:
            QMessageBox.critical(self, "読込エラー", f"読込に失敗しました。\n\n{e}")
            return

        self._actions = actions
        import os
        filename = os.path.basename(path)
        self.setWindowTitle(f"Macro Action Viewer (dev) — file: {filename}")
        self._refresh_after_change(select_row=0)
        QMessageBox.information(
            self, "読込完了",
            f"{len(actions)} 件の action を読み込みました。\n{path}",
        )

    # ================================================================
    #  並べ替え
    # ================================================================

    def _on_move_up(self):
        """↑ボタン: 選択中の action を1つ上へ移動する。"""
        row = self._list_widget.currentRow()
        if row <= 0 or row >= len(self._actions):
            return
        self._actions[row - 1], self._actions[row] = (
            self._actions[row], self._actions[row - 1]
        )
        self._refresh_after_change(select_row=row - 1)

    def _on_move_down(self):
        """↓ボタン: 選択中の action を1つ下へ移動する。"""
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._actions) - 1:
            return
        self._actions[row], self._actions[row + 1] = (
            self._actions[row + 1], self._actions[row]
        )
        self._refresh_after_change(select_row=row + 1)

    # ================================================================
    #  表示更新
    # ================================================================

    def _refresh_after_change(self, *, select_row: int = -1):
        """action 列変更後に一覧・詳細・validation を一括更新する。"""
        self._populate_list(select_row=select_row)
        self._update_validation_status()
        self._update_btn_states()

    def _populate_list(self, *, select_row: int = -1):
        """action 列をリストに表示する。"""
        self._list_widget.clear()
        for i, action in enumerate(self._actions):
            summary = action_summary(action)
            item = QListWidgetItem(f"[{i}] {summary}")
            self._list_widget.addItem(item)

        self._count_label.setText(f"Actions: {len(self._actions)}")

        if self._actions:
            row = select_row if 0 <= select_row < len(self._actions) else 0
            self._list_widget.setCurrentRow(row)
        else:
            self._detail_text.setPlainText("(action なし)")
            self._update_btn_states()

    def _on_row_changed(self, row: int):
        """リスト選択変更時に詳細を更新する。"""
        if row < 0 or row >= len(self._actions):
            self._detail_text.setPlainText("")
            self._update_btn_states()
            return
        action = self._actions[row]
        self._detail_text.setPlainText(self._format_detail(action))
        self._update_btn_states()

    def _update_btn_states(self):
        """選択状態に応じて削除/編集/↑↓ボタンの有効/無効を切り替える。"""
        row = self._list_widget.currentRow()
        count = len(self._actions)

        if row < 0 or row >= count:
            self._delete_btn.setEnabled(False)
            self._delete_btn.setToolTip("")
            self._edit_btn.setEnabled(False)
            self._edit_btn.setToolTip("")
            self._up_btn.setEnabled(False)
            self._down_btn.setEnabled(False)
            return

        self._delete_btn.setEnabled(True)
        self._delete_btn.setToolTip("")
        self._edit_btn.setEnabled(True)
        self._edit_btn.setToolTip("")

        self._up_btn.setEnabled(row > 0)
        self._down_btn.setEnabled(row < count - 1)

    def _format_detail(self, action: RouletteAction) -> str:
        """action の読み取り専用詳細テキストを生成する。"""
        lines: list[str] = []
        type_name = type(action).__name__
        lines.append(f"type: {type_name}")
        lines.append("")

        if isinstance(action, AddRoulette):
            lines.append(f"activate: {action.activate}")

        elif isinstance(action, RemoveRoulette):
            lines.append(f"roulette_id: {action.roulette_id!r}")

        elif isinstance(action, SetActiveRoulette):
            lines.append(f"roulette_id: {action.roulette_id!r}")

        elif isinstance(action, SpinRoulette):
            lines.append(f"roulette_id: {action.roulette_id!r}")
            if not action.roulette_id:
                lines.append("  → active roulette を対象にする")

        elif isinstance(action, UpdateItemEntries):
            lines.append(f"roulette_id: {action.roulette_id!r}")
            lines.append(f"entries: {len(action.entries)} 件")
            if action.entries:
                lines.append("")
                lines.append("entries 内容:")
                for j, entry in enumerate(action.entries):
                    if isinstance(entry, dict):
                        label = entry.get("label", entry.get("text", str(entry)))
                    else:
                        label = str(entry)
                    lines.append(f"  [{j}] {label}")
                    if j >= 19:
                        lines.append(f"  ... (残り {len(action.entries) - 20} 件)")
                        break

        elif isinstance(action, UpdateSettings):
            lines.append(f"key: {action.key!r}")
            lines.append(f"value: {action.value!r}")

        elif isinstance(action, BranchOnWinner):
            lines.append(f"source_roulette_id: {action.source_roulette_id!r}")
            lines.append(f"winner_text: {action.winner_text!r}")
            lines.append(f"then_actions: {len(action.then_actions)} 件")
            lines.append(f"else_actions: {len(action.else_actions)} 件")
            if action.then_actions:
                lines.append("")
                lines.append("then_actions:")
                for j, a in enumerate(action.then_actions):
                    lines.append(f"  [{j}] {action_summary(a)}")
            if action.else_actions:
                lines.append("")
                lines.append("else_actions:")
                for j, a in enumerate(action.else_actions):
                    lines.append(f"  [{j}] {action_summary(a)}")

        # validation
        errors = validate_action_for_save(action)
        if errors:
            lines.append("")
            lines.append("--- validation errors ---")
            for e in errors:
                lines.append(f"  NG: {e}")
        else:
            lines.append("")
            lines.append("--- validation: OK ---")

        return "\n".join(lines)

    def _update_validation_status(self):
        """action 列全体の validation 結果をステータスに表示する。"""
        all_errors: list[str] = []
        for i, action in enumerate(self._actions):
            for e in validate_action_for_save(action):
                all_errors.append(f"[{i}] {e}")

        if not self._actions:
            self._validation_label.setText("Validation: -")
            self._validation_label.setStyleSheet("")
        elif all_errors:
            self._validation_label.setText(
                f"Validation: NG ({len(all_errors)} error{'s' if len(all_errors) > 1 else ''})"
            )
            self._validation_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            self._validation_label.setText("Validation: OK")
            self._validation_label.setStyleSheet("color: green; font-weight: bold;")
