"""
PySide6 プロトタイプ — 操作・設定パネル

右側パネルの責務:
  - spin 操作（開始ボタン、プリセット切替）
  - 表示設定（テキストモード、ドーナツ穴 等）
  - 現在の項目リスト表示
  - 将来機能の受け皿セクション（プレースホルダー）

設定変更の通知フロー:
  SettingsPanel → setting_changed(key, value) → MainWindow → 各コンポーネント

セクション構成（今後の追加先が明確）:
  1. スピン操作 — 実装済み
  2. 表示設定 — 実装済み
  3. 項目リスト — 実装済み（読み取り専用）
  4. 確率変更 — プレースホルダー
  5. 分割 — プレースホルダー
  6. 配置 — プレースホルダー
  7. 常時ランダム — プレースホルダー
  8. 結果表示 — プレースホルダー
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QScrollArea, QWidget,
    QDoubleSpinBox,
)

from bridge import (
    SIDEBAR_W, SIZE_PROFILES, DesignSettings,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
)
from app_settings import AppSettings
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME


# ================================================================
#  セクション UI 部品
# ================================================================

class _SectionHeader(QLabel):
    """セクション見出し用ラベル。"""

    def __init__(self, text: str, design: DesignSettings, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._apply_style(design)

    def _apply_style(self, design: DesignSettings):
        self.setStyleSheet(
            f"color: {design.text}; "
            f"padding: 4px 0 2px 0; "
            f"border-bottom: 1px solid {design.separator};"
        )


class _PlaceholderSection(QFrame):
    """未実装セクションのプレースホルダー。

    将来機能を本実装する際は、このクラスを専用セクションに差し替える。
    差し替え時の手順:
      1. 専用セクションクラスを作成（_PlaceholderSection と同じ位置に追加可能）
      2. SettingsPanel._build_future_sections() 内で差し替え
      3. setting_changed シグナル経由で MainWindow に通知
    """

    def __init__(self, title: str, description: str,
                 design: DesignSettings, parent=None):
        super().__init__(parent)
        self._header = _SectionHeader(title, design)
        self._desc = QLabel(description)
        self._desc.setFont(QFont("Meiryo", 8))
        self._desc.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)
        layout.addWidget(self._header)
        layout.addWidget(self._desc)

        self._apply_style(design)

    def _apply_style(self, design: DesignSettings):
        self._header._apply_style(design)
        self._desc.setStyleSheet(f"color: {design.text_sub};")


# ================================================================
#  メインパネル
# ================================================================

class SettingsPanel(QFrame):
    """操作・設定パネル。

    Signals:
        spin_requested: spin 開始が要求された
        preset_changed(str): spin プリセットが変更された
        setting_changed(str, object): 設定値が変更された (key, value)
            key は AppSettings のフィールド名に対応する。
            MainWindow はこのシグナルを受けて該当コンポーネントを更新する。
    """

    spin_requested = Signal()
    preset_changed = Signal(str)
    setting_changed = Signal(str, object)

    def __init__(self, items: list[str], settings: AppSettings,
                 design: DesignSettings, parent=None):
        super().__init__(parent)
        self._design = design
        self._settings = settings
        self.setFixedWidth(SIDEBAR_W)
        self.setStyleSheet(f"background-color: {design.panel};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # スクロール領域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._apply_scroll_style(design)

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {design.panel};")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)

        # --- セクション構築 ---
        self._build_spin_section(design)
        self._build_display_section(settings, design)
        self._build_result_section(settings, design)
        self._build_items_section(items, design)
        self._build_future_sections(design)

        self._layout.addStretch()

        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    # ================================================================
    #  セクション 1: スピン操作（実装済み）
    # ================================================================

    def _build_spin_section(self, design: DesignSettings):
        self._spin_header = _SectionHeader("スピン", design)
        self._layout.addWidget(self._spin_header)

        # spin ボタン
        self._spin_btn = QPushButton("▶  スピン開始")
        self._spin_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._spin_btn.setMinimumHeight(36)
        self._spin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_spin_btn_style(design)
        self._spin_btn.clicked.connect(self.spin_requested.emit)
        self._layout.addWidget(self._spin_btn)

        # プリセット選択
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)

        preset_lbl = QLabel("プリセット:")
        preset_lbl.setFont(QFont("Meiryo", 8))
        preset_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._preset_lbl = preset_lbl
        preset_row.addWidget(preset_lbl)

        self._preset_combo = QComboBox()
        self._preset_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._preset_combo, design)
        for name in SPIN_PRESET_NAMES:
            self._preset_combo.addItem(name)
        self._preset_combo.setCurrentText(DEFAULT_PRESET_NAME)
        self._preset_combo.currentTextChanged.connect(self.preset_changed.emit)
        preset_row.addWidget(self._preset_combo, stretch=1)

        self._layout.addLayout(preset_row)

    # ================================================================
    #  セクション 2: 表示設定（実装済み）
    # ================================================================

    def _build_display_section(self, settings: AppSettings,
                               design: DesignSettings):
        self._display_header = _SectionHeader("表示", design)
        self._layout.addWidget(self._display_header)

        # テキスト表示モード
        text_row = QHBoxLayout()
        text_row.setSpacing(4)
        text_lbl = QLabel("テキスト:")
        text_lbl.setFont(QFont("Meiryo", 8))
        text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._text_lbl = text_lbl
        text_row.addWidget(text_lbl)

        self._text_mode_combo = QComboBox()
        self._text_mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._text_mode_combo, design)
        for name in ["省略", "収める", "縮小"]:
            self._text_mode_combo.addItem(name)
        self._text_mode_combo.setCurrentIndex(settings.text_size_mode)
        self._text_mode_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("text_size_mode", idx)
        )
        text_row.addWidget(self._text_mode_combo, stretch=1)
        self._layout.addLayout(text_row)

        # ドーナツ穴
        self._donut_cb = QCheckBox("ドーナツ穴")
        self._donut_cb.setFont(QFont("Meiryo", 8))
        self._donut_cb.setStyleSheet(f"color: {design.text};")
        self._donut_cb.setChecked(settings.donut_hole)
        self._donut_cb.toggled.connect(
            lambda v: self.setting_changed.emit("donut_hole", v)
        )
        self._layout.addWidget(self._donut_cb)

        # サイズプロファイル
        prof_row = QHBoxLayout()
        prof_row.setSpacing(4)
        prof_lbl = QLabel("サイズ:")
        prof_lbl.setFont(QFont("Meiryo", 8))
        prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._prof_lbl = prof_lbl
        prof_row.addWidget(prof_lbl)

        self._prof_combo = QComboBox()
        self._prof_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._prof_combo, design)
        for label, w, h in SIZE_PROFILES:
            self._prof_combo.addItem(f"{label}  ({w}x{h})")
        prof_idx = min(settings.profile_idx, len(SIZE_PROFILES) - 1)
        self._prof_combo.setCurrentIndex(prof_idx)
        self._prof_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("profile_idx", idx)
        )
        prof_row.addWidget(self._prof_combo, stretch=1)
        self._layout.addLayout(prof_row)

        # テキスト方向
        tdir_row = QHBoxLayout()
        tdir_row.setSpacing(4)
        tdir_lbl = QLabel("テキスト方向:")
        tdir_lbl.setFont(QFont("Meiryo", 8))
        tdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tdir_lbl = tdir_lbl
        tdir_row.addWidget(tdir_lbl)

        self._tdir_combo = QComboBox()
        self._tdir_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._tdir_combo, design)
        for name in ["横(回転)", "横(水平)", "縦上", "縦下", "縦直立"]:
            self._tdir_combo.addItem(name)
        self._tdir_combo.setCurrentIndex(settings.text_direction)
        self._tdir_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("text_direction", idx)
        )
        tdir_row.addWidget(self._tdir_combo, stretch=1)
        self._layout.addLayout(tdir_row)

        # スピン回転方向
        sdir_row = QHBoxLayout()
        sdir_row.setSpacing(4)
        sdir_lbl = QLabel("回転方向:")
        sdir_lbl.setFont(QFont("Meiryo", 8))
        sdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._sdir_lbl = sdir_lbl
        sdir_row.addWidget(sdir_lbl)

        self._sdir_combo = QComboBox()
        self._sdir_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._sdir_combo, design)
        for name in ["反時計回り", "時計回り"]:
            self._sdir_combo.addItem(name)
        self._sdir_combo.setCurrentIndex(settings.spin_direction)
        self._sdir_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("spin_direction", idx)
        )
        sdir_row.addWidget(self._sdir_combo, stretch=1)
        self._layout.addLayout(sdir_row)

        # ポインター位置
        ptr_row = QHBoxLayout()
        ptr_row.setSpacing(4)
        ptr_lbl = QLabel("ポインター:")
        ptr_lbl.setFont(QFont("Meiryo", 8))
        ptr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._ptr_lbl = ptr_lbl
        ptr_row.addWidget(ptr_lbl)

        self._ptr_combo = QComboBox()
        self._ptr_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._ptr_combo, design)
        for name in POINTER_PRESET_NAMES:
            self._ptr_combo.addItem(name)
        # 現在の pointer_angle からプリセットインデックスを逆引き
        ptr_preset_idx = self._angle_to_preset_idx(settings.pointer_angle)
        self._ptr_combo.setCurrentIndex(ptr_preset_idx)
        self._ptr_combo.currentIndexChanged.connect(self._on_pointer_preset_changed)
        ptr_row.addWidget(self._ptr_combo, stretch=1)
        self._layout.addLayout(ptr_row)

    @staticmethod
    def _angle_to_preset_idx(angle: float) -> int:
        """pointer_angle からプリセットインデックスを逆引きする。"""
        for i, a in enumerate(_POINTER_PRESET_ANGLES):
            if abs(angle - a) < 1.0:
                return i
        return len(POINTER_PRESET_NAMES) - 1  # 任意

    def _on_pointer_preset_changed(self, idx: int):
        """ポインタープリセット変更時のハンドラ。"""
        if idx < len(_POINTER_PRESET_ANGLES):
            angle = _POINTER_PRESET_ANGLES[idx]
            self.setting_changed.emit("pointer_angle", angle)

    # ================================================================
    #  セクション 3: 結果表示設定（実装済み）
    # ================================================================

    def _build_result_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._result_header = _SectionHeader("結果表示", design)
        self._layout.addWidget(self._result_header)

        # 閉じ方モード
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_lbl = QLabel("閉じ方:")
        mode_lbl.setFont(QFont("Meiryo", 8))
        mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_mode_lbl = mode_lbl
        mode_row.addWidget(mode_lbl)

        self._result_mode_combo = QComboBox()
        self._result_mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._result_mode_combo, design)
        for name in ["クリック", "自動", "両方"]:
            self._result_mode_combo.addItem(name)
        self._result_mode_combo.setCurrentIndex(settings.result_close_mode)
        self._result_mode_combo.currentIndexChanged.connect(
            self._on_result_mode_changed
        )
        mode_row.addWidget(self._result_mode_combo, stretch=1)
        self._layout.addLayout(mode_row)

        # 保持秒数
        sec_row = QHBoxLayout()
        sec_row.setSpacing(4)
        sec_lbl = QLabel("保持秒数:")
        sec_lbl.setFont(QFont("Meiryo", 8))
        sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_sec_lbl = sec_lbl
        sec_row.addWidget(sec_lbl)

        self._result_sec_spin = QDoubleSpinBox()
        self._result_sec_spin.setFont(QFont("Meiryo", 8))
        self._result_sec_spin.setRange(0.5, 30.0)
        self._result_sec_spin.setSingleStep(0.5)
        self._result_sec_spin.setDecimals(1)
        self._result_sec_spin.setSuffix(" 秒")
        self._result_sec_spin.setValue(settings.result_hold_sec)
        self._result_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._result_sec_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("result_hold_sec", v)
        )
        sec_row.addWidget(self._result_sec_spin, stretch=1)
        self._layout.addLayout(sec_row)

        # 保持秒数の有効/無効を閉じ方モードに連動
        self._update_hold_sec_enabled()

    def _on_result_mode_changed(self, idx: int):
        """閉じ方モード変更時のハンドラ。"""
        self.setting_changed.emit("result_close_mode", idx)
        self._update_hold_sec_enabled()

    def _update_hold_sec_enabled(self):
        """保持秒数の入力を閉じ方モードに応じて有効/無効化する。"""
        mode = self._result_mode_combo.currentIndex()
        enabled = mode in (1, 2)  # 自動 or 両方
        self._result_sec_spin.setEnabled(enabled)

    # ================================================================
    #  セクション 4: 項目リスト（読み取り専用）
    # ================================================================

    def _build_items_section(self, items: list[str], design: DesignSettings):
        self._items_header = _SectionHeader("項目リスト", design)
        self._layout.addWidget(self._items_header)

        self._item_labels: list[QLabel] = []

        if not items:
            empty = QLabel("  （項目なし）")
            empty.setFont(QFont("Meiryo", 9))
            empty.setStyleSheet(f"color: {design.text_sub};")
            self._layout.addWidget(empty)
            self._item_labels.append(empty)
            return

        for item in items[:20]:
            card = QLabel(f"  {item}")
            card.setFont(QFont("Meiryo", 9))
            card.setStyleSheet(
                f"color: {design.text}; background-color: {design.separator}; "
                f"padding: 5px; border-radius: 3px;"
            )
            self._layout.addWidget(card)
            self._item_labels.append(card)

        if len(items) > 20:
            more = QLabel(f"  ... 他 {len(items) - 20} 件")
            more.setFont(QFont("Meiryo", 8))
            more.setStyleSheet(f"color: {design.text_sub};")
            self._layout.addWidget(more)
            self._item_labels.append(more)

    # ================================================================
    #  セクション 4-8: 将来機能（プレースホルダー）
    #
    #  本実装時の手順:
    #    1. _PlaceholderSection を専用クラスに差し替え
    #    2. setting_changed.emit("key", value) で MainWindow に通知
    #    3. AppSettings に対応フィールドを追加（既にスロットあり）
    # ================================================================

    def _build_future_sections(self, design: DesignSettings):
        self._future_sections: list[_PlaceholderSection] = []

        sections = [
            ("確率変更", "各項目の当選確率を変更（未実装）"),
            ("分割", "項目の分割数を変更（未実装）"),
            ("配置", "segment の並び順を変更（未実装）"),
            ("常時ランダム", "spin ごとに配置をランダム化（未実装）"),
        ]
        for title, desc in sections:
            section = _PlaceholderSection(title, desc, design)
            self._layout.addWidget(section)
            self._future_sections.append(section)

    # ================================================================
    #  内部ヘルパー
    # ================================================================

    def _apply_scroll_style(self, design: DesignSettings):
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {design.panel}; }}"
            f"QScrollBar:vertical {{ width: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:vertical {{ background: {design.separator}; border-radius: 3px; }}"
        )

    def _apply_spin_btn_style(self, design: DesignSettings):
        self._spin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.accent}; color: {design.text};"
            f"  border: none; border-radius: 6px; padding: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.separator}; }}"
            f"QPushButton:disabled {{ background-color: {design.separator}; color: {design.text_sub}; }}"
        )

    @staticmethod
    def _apply_combo_style(combo: QComboBox, design: DesignSettings):
        combo.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 3px 6px;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 16px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )

    # ================================================================
    #  公開 API
    # ================================================================

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

    def update_design(self, design: DesignSettings):
        """デザイン変更時にパネル全体の配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._content.setStyleSheet(f"background-color: {design.panel};")
        self._apply_scroll_style(design)
        self._apply_combo_style(self._preset_combo, design)
        self._apply_combo_style(self._text_mode_combo, design)
        self._apply_combo_style(self._prof_combo, design)
        self._apply_combo_style(self._tdir_combo, design)
        self._apply_combo_style(self._sdir_combo, design)
        self._apply_combo_style(self._ptr_combo, design)
        self._apply_spin_btn_style(design)

        # セクションヘッダー
        for header in [self._spin_header, self._display_header,
                       self._result_header, self._items_header]:
            header._apply_style(design)

        # ラベル
        self._preset_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._sdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._ptr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._donut_cb.setStyleSheet(f"color: {design.text};")
        self._result_mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._result_mode_combo, design)
        self._result_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )

        # 項目カード
        for lbl in self._item_labels:
            if lbl.text().startswith("  （") or lbl.text().startswith("  ..."):
                lbl.setStyleSheet(f"color: {design.text_sub};")
            else:
                lbl.setStyleSheet(
                    f"color: {design.text}; background-color: {design.separator}; "
                    f"padding: 5px; border-radius: 3px;"
                )

        # プレースホルダーセクション
        for section in self._future_sections:
            section._apply_style(design)
