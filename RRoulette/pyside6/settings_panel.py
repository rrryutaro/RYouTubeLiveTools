"""
PySide6 プロトタイプ — 操作・設定パネル

右側パネルの責務:
  - spin 操作（開始ボタン、プリセット切替）
  - 表示設定（テキストモード、ドーナツ穴 等）
  - 項目データ表示（ItemEntry リスト）
  - 将来機能の受け皿セクション（プレースホルダー）

設定変更の通知フロー:
  SettingsPanel → setting_changed(key, value) → MainWindow → 各コンポーネント

セクション構成（2系統で整理）:

  【アプリ設定セクション】AppSettings 側
    1. スピン操作 — 実装済み
    2. 表示設定 — 実装済み
    3. 結果表示 — 実装済み

  【項目データセクション】ItemEntry 側
    4. 項目リスト — 実装済み（編集可能）
    5. 確率変更 — プレースホルダー（項目データの編集）
    6. 分割 — プレースホルダー（項目データの編集）
    7. 配置 — プレースホルダー（項目データの編集）
    8. 常時ランダム — プレースホルダー（spin 前の配置制御）
"""

from PySide6.QtCore import Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve, QEvent, QSize, QRect
from PySide6.QtGui import QFont, QCursor, QPainter, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QScrollArea, QWidget,
    QDoubleSpinBox, QSpinBox, QLineEdit, QStackedWidget, QSlider,
    QFileDialog, QPlainTextEdit, QStackedLayout, QMenu, QListWidget, QListWidgetItem,
    QMessageBox, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication,
)

from item_text_helpers import serialize_items_text, parse_items_text, enforce_item_limits
from panel_widgets import (
    _SectionHeader, CollapsibleSection, _PanelGrip, _PanelDragBar,
    install_panel_context_menu, _PlaceholderSection, _MW_DRAG_BAR_H,
)
from manage_panel import ManagePanel

from bridge import (
    SIDEBAR_W, SIZE_PROFILES, DesignSettings,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
    ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES,
)

from app_settings import AppSettings
from item_entry import ItemEntry
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME
from dark_theme import dark_checkbox_style, dark_spinbox_style, get_header_colors
from settings_panel_sections import _SectionsMixin
from settings_panel_items import (
    _ItemsMixin,
    _build_weight_candidates,  # re-exported for item_panel.py
    _populate_weight_combo,    # re-exported for item_panel.py
    _calc_item_probs,          # re-exported for item_panel.py
)


class SettingsPanel(_SectionsMixin, _ItemsMixin, QFrame):
    """操作・設定パネル。

    Signals:
        spin_requested: spin 開始が要求された
        preset_changed(str): spin プリセットが変更された
        setting_changed(str, object): 設定値が変更された (key, value)
            key は AppSettings のフィールド名に対応する。
            MainWindow はこのシグナルを受けて該当コンポーネントを更新する。
        item_entries_changed(list): 項目データが変更された
            MainWindow はこのシグナルを受けて segments 再構築・保存を行う。
    """

    spin_requested = Signal()
    preset_changed = Signal(str)
    setting_changed = Signal(str, object)
    item_entries_changed = Signal(list)
    pattern_switched = Signal(str)      # パターン切替 (新パターン名)
    pattern_added = Signal(str)         # パターン追加 (新パターン名)
    pattern_deleted = Signal(str)       # パターン削除 (削除パターン名)
    pattern_renamed = Signal(str, str)  # パターン名変更 (旧名, 新名)
    preview_tick_requested = Signal()   # tick音テスト再生
    preview_win_requested = Signal()    # result音テスト再生
    log_clear_requested = Signal()     # 履歴クリア
    log_export_requested = Signal()    # ログエクスポート
    log_import_requested = Signal()    # ログインポート
    shuffle_once_requested = Signal()  # 単発ランダム再配置
    arrangement_reset_requested = Signal()  # i284: 並びリセット (v0.4.4 標準配置)
    items_reset_requested = Signal()        # i284: 項目一括リセット (v0.4.4 一括リセット)
    pattern_export_requested = Signal()  # パターンエクスポート
    pattern_import_requested = Signal()  # パターンインポート
    custom_tick_file_changed = Signal(str)  # カスタムtick音ファイル変更
    custom_win_file_changed = Signal(str)   # カスタムresult音ファイル変更
    design_editor_requested = Signal()       # デザインエディタ起動
    graph_requested = Signal()               # 勝利履歴グラフ起動
    replay_play_requested = Signal()         # 最新リプレイ再生
    replay_stop_requested = Signal()         # リプレイ中断
    replay_manager_requested = Signal()      # リプレイ管理ウィンドウ起動
    settings_export_requested = Signal()     # i356: 設定全体エクスポート
    settings_import_requested = Signal()     # i356: 設定全体インポート
    geometry_changed = Signal()

    def __init__(self, item_entries: list[ItemEntry], settings: AppSettings,
                 design: DesignSettings, *,
                 pattern_names: list[str] | None = None,
                 current_pattern: str = "デフォルト",
                 on_drag_bar_changed=None,
                 parent=None):
        """操作・設定パネル。

        Args:
            item_entries: 項目データ（bridge.load_item_entries() の戻り値）。
                設定データ（AppSettings）とは別管理。各項目のテキスト・
                確率・分割等を保持する ItemEntry のリスト。
            settings: アプリ設定データ（AppSettings）。
            design: デザイン設定。
            pattern_names: パターン名一覧（None なら ["デフォルト"]）。
            current_pattern: 現在選択中のパターン名。
        """
        super().__init__(parent)
        self._design = design
        self._settings = settings
        self._item_entries = item_entries
        self.setStyleSheet(f"background-color: {design.panel};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 上部ドラッグバー（パネルを掴んで移動するための常時有効ハンドル）──
        # 折りたたみセクション展開中はクライアント領域全面が widgets で
        # 埋まりドラッグ起点が無くなるため、常時表示のドラッグバーを置く。
        self._drag_bar = _PanelDragBar(self, design, parent=self)
        outer.addWidget(self._drag_bar)
        # 右クリック → 移動バー表示/非表示
        install_panel_context_menu(self, self._drag_bar,
                                   on_drag_bar_changed=on_drag_bar_changed)

        # ── 常設クイック設定行（透過 / 常に最前面）──
        # v0.4.4 cfg_panel の「ウィンドウ表示」グループ相当。
        # 折りたたみセクションの中ではなく、常時見える場所に置くことで
        # 「OBS透過モード」がユーザーから辿りやすい状態にする。
        self._build_quick_settings_bar(outer, settings, design)

        # ── 1つのスクロール領域にアプリ設定 + 項目リストを縦並び ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._apply_scroll_style(self._scroll, design)

        self._content = QWidget(self._scroll)  # i289 t09
        self._content.setStyleSheet(
            f"background-color: {design.panel};"
        )
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)

        # ── アプリ設定セクション ──
        self._build_spin_section(settings, design)
        self._build_display_section(settings, design)
        self._build_design_section(settings, design)
        self._build_result_section(settings, design)
        self._build_sound_section(settings, design)
        self._build_log_section(settings, design)
        self._build_replay_section(settings, design)

        # ── パターン管理セクション ──
        self._pattern_names = list(pattern_names or ["デフォルト"])
        self._current_pattern = current_pattern
        self._build_pattern_section(design)

        # ── 項目データセクション ──
        self._build_items_section(item_entries, design)
        self._build_item_edit_sections(design)

        # ── 折りたたみ状態の復元とシグナル接続 ──
        self._collapsible_map: dict[str, CollapsibleSection] = {
            "spin": self._spin_collapsible,
            "display": self._display_section,
            "design": self._design_collapsible,
            "result": self._result_collapsible,
            "sound": self._sound_collapsible,
            "log": self._log_collapsible,
            "replay": self._replay_collapsible,
            "pattern": self._pattern_collapsible,
            "items": self._items_collapsible,
        }
        # アニメーション時間の初期適用
        for cs in self._collapsible_map.values():
            cs.set_anim_duration(settings.collapse_anim_ms)
        saved = settings.collapsed_sections
        if saved:
            for name, cs in self._collapsible_map.items():
                if name in saved:
                    cs.set_expanded(not saved[name])
        # 排他開閉の正規化: 展開セクションが2個以上なら最初の1個だけ残す
        expanded = [n for n, cs in self._collapsible_map.items()
                    if not cs.is_collapsed]
        self._sections_normalized = len(expanded) > 1
        if self._sections_normalized:
            for name in expanded[1:]:
                self._collapsible_map[name].set_expanded(False)
        for name, cs in self._collapsible_map.items():
            cs.toggled.connect(
                lambda collapsed, _n=name: self._on_section_toggled(_n, collapsed)
            )
        # 正規化で変更があった場合、保存フローへ反映
        if self._sections_normalized:
            self._emit_collapsed_state()

        self._layout.addStretch()

        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

        # ── 最小幅: contentsMargins + スクロールバー幅 + つまみ逃がし ──
        scrollbar_w = self._scroll.verticalScrollBar().sizeHint().width()
        content_margins = self._layout.contentsMargins()
        margins_total = content_margins.left() + content_margins.right()
        # SIDEBAR_W をベースに、スクロールバーとマージンを加味
        self._panel_min_w = max(SIDEBAR_W, 200 + margins_total + scrollbar_w + 20)

        # ── 右下リサイズグリップ（パネル幅変更用） ──
        self._resize_grip = _PanelGrip(
            self, design, mode="panel", min_w=self._panel_min_w, parent=self
        )

        # パネル最小幅
        self.setMinimumWidth(self._panel_min_w)

        # ── パネル前後関係 ──
        self.pinned_front = False  # True: 通常パネルより常に上に表示

        # ── フローティング独立化状態 ──
        self._floating = False

        # ── パネルドラッグ状態 ──
        self._dragging_panel = False
        self._panel_drag_start = QPoint()
        self._panel_start_pos = QPoint()

        # ── 項目 / パターンセクションの外部化フラグ ──
        # ItemPanel に reparent されたあと、settings 側の排他開閉などで
        # これらのセクションを誤って閉じないようスキップする目印。
        self._items_external = False
        self._pattern_external = False

    # ================================================================
    #  折りたたみ状態の保存
    # ================================================================

    def mousePressEvent(self, event):
        """i277: 空きクライアント領域でのクリックは「前面化のみ」扱い。

        - 背面パネルを前面化する (raise_)
        - パネル本体のドラッグはここでは始めない (上部の `_drag_bar` か
          各セクションヘッダのドラッグ拡張で行う)
        - 本来動作 (たとえばボタン押下) もここでは発火しない
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.raise_()
            self._dragging_panel = False
        event.accept()

    def mouseMoveEvent(self, event):
        # i277: 空きクライアント領域からのドラッグ移動は禁止 (前面化のみ)。
        # 移動はドラッグバーまたは折りたたみヘッダから行う。
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def moveEvent(self, event):
        """パネル移動時に通知する。"""
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        """リサイズグリップを右下に追従させる。"""
        super().resizeEvent(event)
        self._resize_grip.reposition()
        # i275: top-level Tool window 化に伴い、_clamp_to_parent は使わない。
        # 親内クランプは自身の geometry をリサイズのたびに動かしてしまい、
        # メインウィンドウ最小化や resize で位置が崩れる原因になっていた。
        self.geometry_changed.emit()

    def replace_entries_from_texts(self, texts: list[str]) -> tuple[bool, str]:
        """テキスト直接編集モードからの結果を反映する。

        - 既存 entries とテキストを順位ごとに突き合わせ、enabled / 確率設定 等は
          可能な範囲で引き継ぐ
        - 上限超過は enforce_item_limits でカット
        - 新しい行を `set_active_entries` で再構築
        - `item_entries_changed` シグナルで MainWindow へ通知

        Returns:
            (changed_by_limit, warn_message): 上限により切り詰められたかどうかと
            ユーザーへのメッセージ。
        """
        trimmed, changed, warn = enforce_item_limits(list(texts))
        old_entries = list(self._item_entries)
        new_entries: list[ItemEntry] = []
        for j, text in enumerate(trimmed):
            if j < len(old_entries) and old_entries[j].text == text:
                new_entries.append(old_entries[j])
            else:
                # 既存の enabled 状態は同じ位置から引き継ぐ
                if j < len(old_entries):
                    base = old_entries[j]
                    entry = ItemEntry(
                        text=text,
                        enabled=base.enabled,
                        prob_mode=base.prob_mode,
                        prob_value=base.prob_value,
                        split_count=base.split_count,
                    )
                else:
                    entry = ItemEntry(
                        text=text, enabled=True,
                        prob_mode=None, prob_value=None,
                        split_count=1,
                    )
                new_entries.append(entry)
        self.set_active_entries(new_entries)
        self.item_entries_changed.emit(new_entries)
        return changed, warn

    def _live_update_from_text_entries(self, texts: list[str]) -> None:
        """i284: テキスト編集モードからの即時プレビュー反映。

        `replace_entries_from_texts` は行 UI を再構築するためフォーカスや
        スクロール位置を壊してしまう（テキスト編集モード中であっても
        裏側で QLineEdit 群が作り直される）。
        ここでは ItemEntry のリストだけを更新し、シグナルだけ発火する。
        既存の prob_mode / prob_value / split_count / enabled は同位置の
        旧エントリから引き継ぎ、新規行はデフォルトを与える。
        """
        old_entries = list(self._item_entries)
        new_entries: list[ItemEntry] = []
        for j, text in enumerate(texts):
            if j < len(old_entries) and old_entries[j].text == text:
                new_entries.append(old_entries[j])
                continue
            if j < len(old_entries):
                base = old_entries[j]
                new_entries.append(ItemEntry(
                    text=text,
                    enabled=base.enabled,
                    prob_mode=base.prob_mode,
                    prob_value=base.prob_value,
                    split_count=base.split_count,
                ))
            else:
                new_entries.append(ItemEntry(
                    text=text, enabled=True,
                    prob_mode=None, prob_value=None,
                    split_count=1,
                ))
        self._item_entries = new_entries
        self.item_entries_changed.emit(list(new_entries))

    def set_active_entries(self, entries: list[ItemEntry]):
        """アクティブなルーレットの項目データを差し替える。

        将来のマルチルーレット切替時に、編集対象の item_entries を
        外部から一括で入れ替えるための入口。
        既存の項目行 UI を全て再構築する。
        """
        # 既存行を全て削除
        for row in list(self._item_rows):
            self._item_rows_layout.removeWidget(row)
            row.deleteLater()
        self._item_rows.clear()

        # 新しいエントリで行を再構築
        self._item_entries = entries
        for entry in entries:
            self._add_item_row(entry, self._design)

        self._refresh_all_weight_combos()
        # i284: 確率ラベルを反映
        self._refresh_prob_labels()

        # 検索・フィルターをリセット
        self._search_edit.clear()
        self._filter_combo.setCurrentIndex(0)

    def update_win_counts(self, counts: dict[str, int]):
        """各項目行の勝利数ラベルを更新する。

        Args:
            counts: {項目テキスト: 当選回数} の辞書
        """
        for row in self._item_rows:
            text = row._edit.text().strip()
            n = counts.get(text, 0)
            row._win_lbl.setText(str(n) if n > 0 else "0")

    def set_spinning(self, spinning: bool):
        """spin 状態に応じてボタンを有効/無効にする。"""
        self._spin_btn.setEnabled(not spinning)
        self._spin_btn.setText("⏳  スピン中..." if spinning else "▶  スピン開始")

    def set_preset(self, name: str):
        """プリセット表示を外部から更新する。"""
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(name)
        self._preset_combo.blockSignals(False)

    def update_setting(self, key: str, value):
        """外部からの設定変更を UI に反映する（シグナルを出さない）。"""
        if key == "text_size_mode":
            self._text_mode_combo.blockSignals(True)
            self._text_mode_combo.setCurrentIndex(value)
            self._text_mode_combo.blockSignals(False)
        elif key == "donut_hole":
            self._donut_cb.blockSignals(True)
            self._donut_cb.setChecked(value)
            self._donut_cb.blockSignals(False)
        elif key == "profile_idx":
            self._prof_combo.blockSignals(True)
            self._prof_combo.setCurrentIndex(value)
            self._prof_combo.blockSignals(False)
        elif key == "text_direction":
            self._tdir_combo.blockSignals(True)
            self._tdir_combo.setCurrentIndex(value)
            self._tdir_combo.blockSignals(False)
        elif key == "spin_direction":
            self._sdir_combo.blockSignals(True)
            self._sdir_combo.setCurrentIndex(value)
            self._sdir_combo.blockSignals(False)
        elif key == "pointer_angle":
            idx = self._angle_to_preset_idx(value)
            self._ptr_combo.blockSignals(True)
            self._ptr_combo.setCurrentIndex(idx)
            self._ptr_combo.blockSignals(False)
        elif key == "result_close_mode":
            self._result_mode_combo.blockSignals(True)
            self._result_mode_combo.setCurrentIndex(value)
            self._result_mode_combo.blockSignals(False)
            self._update_hold_sec_enabled()
        elif key == "result_hold_sec":
            self._result_sec_spin.blockSignals(True)
            self._result_sec_spin.setValue(value)
            self._result_sec_spin.blockSignals(False)
            # 未設定時は再生時保持表示を通常保持に追従させる
            if not self._macro_hold_cb.isChecked():
                self._macro_sec_spin.blockSignals(True)
                self._macro_sec_spin.setValue(value)
                self._macro_sec_spin.blockSignals(False)
        elif key == "macro_hold_sec":
            is_custom = value is not None
            self._macro_hold_cb.blockSignals(True)
            self._macro_hold_cb.setChecked(is_custom)
            self._macro_hold_cb.blockSignals(False)
            self._macro_sec_spin.blockSignals(True)
            if is_custom:
                self._macro_sec_spin.setValue(value)
            self._macro_sec_spin.setEnabled(is_custom)
            self._macro_sec_lbl.setEnabled(is_custom)
            self._macro_sec_spin.blockSignals(False)
        elif key == "sound_tick_enabled":
            self._sound_tick_cb.blockSignals(True)
            self._sound_tick_cb.setChecked(value)
            self._sound_tick_cb.blockSignals(False)
        elif key == "sound_result_enabled":
            self._sound_result_cb.blockSignals(True)
            self._sound_result_cb.setChecked(value)
            self._sound_result_cb.blockSignals(False)
        elif key == "log_overlay_show":
            self._log_show_cb.blockSignals(True)
            self._log_show_cb.setChecked(value)
            self._log_show_cb.blockSignals(False)
        elif key == "spin_duration":
            self._dur_spin.blockSignals(True)
            self._dur_spin.setValue(value)
            self._dur_spin.blockSignals(False)
        elif key == "spin_mode":
            self._mode_combo.blockSignals(True)
            self._mode_combo.setCurrentIndex(value)
            self._mode_combo.blockSignals(False)
            self._update_duration_rows_visibility(value)
        elif key == "double_duration":
            self._dbl_spin.blockSignals(True)
            self._dbl_spin.setValue(value)
            self._dbl_spin.blockSignals(False)
        elif key == "triple_duration":
            self._tpl_spin.blockSignals(True)
            self._tpl_spin.setValue(value)
            self._tpl_spin.blockSignals(False)
        elif key == "auto_shuffle":
            self._shuffle_cb.blockSignals(True)
            self._shuffle_cb.setChecked(value)
            self._shuffle_cb.blockSignals(False)
        elif key == "arrangement_direction":
            self._arr_combo.blockSignals(True)
            self._arr_combo.setCurrentIndex(value)
            self._arr_combo.blockSignals(False)
        elif key == "window_transparent":
            self._window_transparent_cb.blockSignals(True)
            self._window_transparent_cb.setChecked(value)
            self._window_transparent_cb.blockSignals(False)
        elif key == "roulette_transparent":
            self._roulette_transparent_cb.blockSignals(True)
            self._roulette_transparent_cb.setChecked(value)
            self._roulette_transparent_cb.blockSignals(False)
        elif key == "tick_volume":
            self._tick_vol_slider.blockSignals(True)
            self._tick_vol_slider.setValue(value)
            self._tick_vol_slider.blockSignals(False)
            self._tick_vol_val.setText(f"{value}%")
        elif key == "win_volume":
            self._win_vol_slider.blockSignals(True)
            self._win_vol_slider.setValue(value)
            self._win_vol_slider.blockSignals(False)
            self._win_vol_val.setText(f"{value}%")
        elif key == "tick_pattern":
            self._tick_pat_combo.blockSignals(True)
            self._tick_pat_combo.setCurrentIndex(value)
            self._tick_pat_combo.blockSignals(False)
        elif key == "win_pattern":
            self._win_pat_combo.blockSignals(True)
            self._win_pat_combo.setCurrentIndex(value)
            self._win_pat_combo.blockSignals(False)
        elif key == "log_timestamp":
            self._log_ts_cb.blockSignals(True)
            self._log_ts_cb.setChecked(value)
            self._log_ts_cb.blockSignals(False)
        elif key == "log_box_border":
            self._log_border_cb.blockSignals(True)
            self._log_border_cb.setChecked(value)
            self._log_border_cb.blockSignals(False)
        elif key == "log_on_top":
            self._log_on_top_cb.blockSignals(True)
            self._log_on_top_cb.setChecked(value)
            self._log_on_top_cb.blockSignals(False)
        elif key == "log_history_all_patterns":
            if hasattr(self, "_log_all_patterns_cb"):
                self._log_all_patterns_cb.blockSignals(True)
                self._log_all_patterns_cb.setChecked(value)
                self._log_all_patterns_cb.blockSignals(False)
        elif key == "confirm_reset":
            self._confirm_reset_cb.blockSignals(True)
            self._confirm_reset_cb.setChecked(value)
            self._confirm_reset_cb.blockSignals(False)
        elif key == "confirm_item_delete":
            # i286: 項目削除確認設定の外部変更反映
            self._settings.confirm_item_delete = bool(value)
            if hasattr(self, "_confirm_item_delete_cb"):
                self._confirm_item_delete_cb.blockSignals(True)
                self._confirm_item_delete_cb.setChecked(bool(value))
                self._confirm_item_delete_cb.blockSignals(False)
        elif key == "replay_max_count":
            self._replay_max_spin.blockSignals(True)
            self._replay_max_spin.setValue(value)
            self._replay_max_spin.blockSignals(False)
        elif key == "replay_show_indicator":
            self._replay_indicator_cb.blockSignals(True)
            self._replay_indicator_cb.setChecked(value)
            self._replay_indicator_cb.blockSignals(False)
        elif key == "grip_visible":
            self._grip_visible_cb.blockSignals(True)
            self._grip_visible_cb.setChecked(value)
            self._grip_visible_cb.blockSignals(False)
        elif key == "ctrl_box_visible":
            self._ctrl_box_visible_cb.blockSignals(True)
            self._ctrl_box_visible_cb.setChecked(value)
            self._ctrl_box_visible_cb.blockSignals(False)
        elif key == "float_win_show_instance":
            self._instance_label_cb.blockSignals(True)
            self._instance_label_cb.setChecked(value)
            self._instance_label_cb.blockSignals(False)
        elif key == "settings_panel_float":
            self._float_panel_cb.blockSignals(True)
            self._float_panel_cb.setChecked(value)
            self._float_panel_cb.blockSignals(False)
        elif key == "always_on_top":
            self._aot_cb.blockSignals(True)
            self._aot_cb.setChecked(value)
            self._aot_cb.blockSignals(False)
        elif key == "show_item_prob":
            # i283: 確率/分割 UI の表示 ON/OFF
            self._settings.show_item_prob = bool(value)
            if hasattr(self, "_show_item_prob_cb"):
                self._show_item_prob_cb.blockSignals(True)
                self._show_item_prob_cb.setChecked(bool(value))
                self._show_item_prob_cb.blockSignals(False)
            self._refresh_item_rows_visibility()
        elif key == "show_item_win_count":
            # i283: 当選回数ラベルの表示 ON/OFF
            self._settings.show_item_win_count = bool(value)
            if hasattr(self, "_show_item_win_cb"):
                self._show_item_win_cb.blockSignals(True)
                self._show_item_win_cb.setChecked(bool(value))
                self._show_item_win_cb.blockSignals(False)
            self._refresh_item_rows_visibility()
        elif key == "item_panel_display_mode":
            # i289: 項目パネル表示モード変更。ItemPanel 側で処理するため pass。
            pass

    def set_panel_theme_mode(self, theme_mode: str):
        """テーマモード変更時に全折りたたみセクションのヘッダーを更新する。"""
        for cs in self._collapsible_map.values():
            cs.set_theme_mode(theme_mode)

    def update_design(self, design: DesignSettings):
        """デザイン変更時にパネル全体の配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._content.setStyleSheet(f"background-color: {design.panel};")
        self._apply_scroll_style(self._scroll, design)
        self._resize_grip.update_design(design)
        self._drag_bar.update_design(design)
        self._apply_combo_style(self._preset_combo, design)
        self._apply_combo_style(self._text_mode_combo, design)
        self._apply_combo_style(self._prof_combo, design)
        self._apply_combo_style(self._tdir_combo, design)
        self._apply_combo_style(self._sdir_combo, design)
        self._apply_combo_style(self._ptr_combo, design)
        self._apply_spin_btn_style(design)

        # パターンセクション
        self._apply_combo_style(self._pattern_combo, design)
        pat_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._pattern_add_btn.setStyleSheet(pat_btn_style)
        self._pattern_del_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._pattern_export_btn.setStyleSheet(pat_btn_style)
        self._pattern_import_btn.setStyleSheet(pat_btn_style)

        # 折りたたみセクション
        for cs in [self._spin_collapsible, self._display_section,
                   self._design_collapsible, self._result_collapsible,
                   self._sound_collapsible, self._log_collapsible,
                   self._replay_collapsible, self._pattern_collapsible,
                   self._items_collapsible]:
            cs.apply_design(design)

        # デザインエディタボタン
        self._design_editor_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 6px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        # ダークテーマ共通スタイル
        sb_style = self._dark_spinbox_style(design)
        cb_style = self._dark_checkbox_style(design)

        # スピン時間
        self._dur_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dur_spin.setStyleSheet(sb_style)

        # スピンモード / ダブル・トリプル時間
        self._mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._mode_combo, design)
        self._dbl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dbl_spin.setStyleSheet(sb_style)
        self._tpl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tpl_spin.setStyleSheet(sb_style)

        # ラベル
        self._preset_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._theme_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._theme_combo, design)
        self._text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._sdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._ptr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._anim_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._anim_spin.setStyleSheet(sb_style)
        self._donut_cb.setStyleSheet(cb_style)
        self._window_transparent_cb.setStyleSheet(cb_style)
        self._roulette_transparent_cb.setStyleSheet(cb_style)
        self._aot_cb.setStyleSheet(cb_style)
        self._grip_visible_cb.setStyleSheet(cb_style)
        self._ctrl_box_visible_cb.setStyleSheet(cb_style)
        self._instance_label_cb.setStyleSheet(cb_style)
        self._float_panel_cb.setStyleSheet(cb_style)
        self._sound_tick_cb.setStyleSheet(cb_style)
        self._sound_result_cb.setStyleSheet(cb_style)
        slider_style = (
            f"QSlider::groove:horizontal {{"
            f"  background: {design.separator}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {design.accent}; width: 12px; margin: -4px 0;"
            f"  border-radius: 6px;"
            f"}}"
        )
        self._tick_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tick_vol_slider.setStyleSheet(slider_style)
        self._tick_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_slider.setStyleSheet(slider_style)
        self._win_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._tick_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._tick_pat_combo, design)
        self._win_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._win_pat_combo, design)
        small_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._tick_file_btn.setStyleSheet(small_btn_style)
        self._tick_test_btn.setStyleSheet(small_btn_style)
        self._win_file_btn.setStyleSheet(small_btn_style)
        self._win_test_btn.setStyleSheet(small_btn_style)
        self._log_show_cb.setStyleSheet(cb_style)
        self._log_ts_cb.setStyleSheet(cb_style)
        self._log_border_cb.setStyleSheet(cb_style)
        self._log_on_top_cb.setStyleSheet(cb_style)
        if hasattr(self, "_log_all_patterns_cb"):
            self._log_all_patterns_cb.setStyleSheet(cb_style)
        self._confirm_reset_cb.setStyleSheet(cb_style)
        if hasattr(self, "_confirm_item_delete_cb"):
            self._confirm_item_delete_cb.setStyleSheet(cb_style)
        _log_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._log_export_btn.setStyleSheet(_log_btn_style)
        if hasattr(self, "_log_import_btn"):
            self._log_import_btn.setStyleSheet(_log_btn_style)
        self._log_clear_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._graph_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._shuffle_cb.setStyleSheet(cb_style)
        self._arr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._arr_combo, design)
        self._shuffle_once_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._result_mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._result_mode_combo, design)
        self._result_sec_spin.setStyleSheet(sb_style)
        self._macro_hold_cb.setStyleSheet(cb_style)
        self._macro_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._macro_sec_spin.setStyleSheet(sb_style)
        self._replay_indicator_cb.setStyleSheet(cb_style)
        self._replay_max_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._replay_max_spin.setStyleSheet(sb_style)
        self._replay_count_lbl.setStyleSheet(f"color: {design.text_sub};")

        # 設定全体 export / import ボタン (i356)
        _cfg_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 22px; max-width: 22px; font-size: 9pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._cfg_export_btn.setStyleSheet(_cfg_btn_style)
        self._cfg_import_btn.setStyleSheet(_cfg_btn_style)

        # クイックバー background
        self._quick_bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {design.panel};"
            f"  border-bottom: 1px solid {design.separator};"
            f"}}"
        )
        self._window_transparent_cb.setStyleSheet(f"color: {design.text};")
        self._roulette_transparent_cb.setStyleSheet(f"color: {design.text};")
        self._aot_cb.setStyleSheet(f"color: {design.text};")

        # 検索・フィルター
        self._search_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._apply_combo_style(self._filter_combo, design)

        # 項目編集行
        self._update_item_rows_design(design)
        self._apply_add_btn_style(self._add_item_btn, design)

        # 項目編集プレースホルダーセクション
        for section in self._item_edit_sections:
            section._apply_style(design)
