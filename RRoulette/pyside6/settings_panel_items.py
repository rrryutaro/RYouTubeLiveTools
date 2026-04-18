"""
PySide6 — SettingsPanel 項目行ロジックモジュール

内容:
  モジュールレベル純関数:
    _build_weight_candidates — 重み係数候補生成
    _populate_weight_combo   — 重み係数コンボ再構築
    _calc_item_probs         — 当選確率計算
  _ItemsMixin:
    項目行 UI 構築・イベントハンドラ・確率表示・フィルタ
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QScrollArea, QWidget,
    QDoubleSpinBox, QSpinBox, QLineEdit, QStackedWidget, QMenu,
)

from item_text_helpers import serialize_items_text, parse_items_text, enforce_item_limits
from panel_widgets import _SectionHeader, CollapsibleSection, _PlaceholderSection

from bridge import (
    DesignSettings,
    ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES,
)
from app_settings import AppSettings
from item_entry import ItemEntry
from dark_theme import dark_checkbox_style, dark_spinbox_style, get_header_colors


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



def _populate_weight_combo(combo: QComboBox, n: int):
    """重み係数 QComboBox の選択肢を N に基づいて再構築する。"""
    combo.blockSignals(True)
    current_text = combo.currentText()
    combo.clear()
    candidates = _build_weight_candidates(n)
    for v in candidates:
        combo.addItem(f"×{v:g}", v)
    # 以前の選択を復元（可能なら）
    for i in range(combo.count()):
        if combo.itemText(i) == current_text:
            combo.setCurrentIndex(i)
            break
    combo.blockSignals(False)



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


class _ItemsMixin:
    """項目行 UI 構築・イベントハンドラ・確率表示・フィルタの mixin。

    SettingsPanel に多重継承される。
    属性 (_item_rows, _settings, _design 等) は SettingsPanel.__init__ で初期化される。
    """

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
        self._item_rows_container = QWidget(self._items_collapsible._container)  # i289 t09
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
        row = QWidget(self._item_rows_container)  # i289 t09
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
        prob_pct_lbl = QLabel("", row)  # i289 t10
        prob_pct_lbl.setFont(QFont("Meiryo", 7))
        prob_pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prob_pct_lbl.setMinimumWidth(40)
        prob_pct_lbl.setStyleSheet(
            f"color: {design.text_sub}; background-color: transparent;"
        )
        prob_pct_lbl.setToolTip("当選確率（％）")
        top_row.addWidget(prob_pct_lbl)

        # 勝利数ラベル
        win_lbl = QLabel("0", row)  # i289 t10
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
        _populate_weight_combo(weight_combo, n)
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
            _populate_weight_combo(combo, n)
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

    def notify_entries_changed_from_simple(self):
        """i289: シンプル表示モードからの項目変更通知（行 UI 再構築なし）。

        シンプル表示側で _item_entries を直接編集した後に呼ぶ。
        行 UI は再構築しないため、詳細表示へ切り替えるときに
        set_active_entries で同期すること。
        """
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

    def _refresh_prob_labels(self):
        """i284: 全行の当選確率ラベルを再計算して反映する。

        _add_item_row 中の _restore_prob_ui で部分的に collect が走るタイミングが
        あるため、ここでは self._item_entries に頼らず必ず collect_entries で
        その時点の行 UI から再構築する。
        """
        if not self._item_rows:
            return
        entries = self._collect_entries()
        probs = _calc_item_probs(entries)
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

        # i289: show_item_prob / show_item_win_count は ItemPanel のアイコンに移動。
        # confirm_item_delete / arrangement_direction は表示セクションへ移動済み。

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

