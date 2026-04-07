"""
PySide6 プロトタイプ — 操作・設定パネル

右側パネルの責務:
  - spin 操作（開始ボタン、プリセット切替）
  - 将来機能の受け皿セクション
  - 現在の状態表示

将来追加予定:
  - 項目 / segment 管理
  - 確率変更
  - 分割設定
  - 配置設定
  - 常時ランダム
  - デザイン設定
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QScrollArea, QWidget,
    QGroupBox, QSizePolicy,
)

from bridge import SIDEBAR_W, DesignSettings
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME


class _SectionHeader(QLabel):
    """セクション見出し用ラベル。"""

    def __init__(self, text: str, design: DesignSettings, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self.setStyleSheet(
            f"color: {design.text}; "
            f"padding: 4px 0 2px 0; "
            f"border-bottom: 1px solid {design.separator};"
        )


class _PlaceholderSection(QFrame):
    """未実装セクションのプレースホルダー。"""

    def __init__(self, title: str, description: str,
                 design: DesignSettings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)

        layout.addWidget(_SectionHeader(title, design))

        desc_lbl = QLabel(description)
        desc_lbl.setFont(QFont("Meiryo", 8))
        desc_lbl.setStyleSheet(f"color: {design.text_sub};")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)


class SettingsPanel(QFrame):
    """操作・設定パネル。

    Signals:
        spin_requested: spin 開始が要求された
        preset_changed(str): spin プリセットが変更された
    """

    spin_requested = Signal()
    preset_changed = Signal(str)

    def __init__(self, items: list[str], design: DesignSettings, parent=None):
        super().__init__(parent)
        self._design = design
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

        # === spin 操作セクション ===
        self._build_spin_section(design)

        # === 項目リストセクション ===
        self._build_items_section(items, design)

        # === 将来機能セクション（プレースホルダー） ===
        self._layout.addWidget(_PlaceholderSection(
            "確率変更", "各項目の当選確率を変更（未実装）", design,
        ))
        self._layout.addWidget(_PlaceholderSection(
            "分割", "項目の分割数を変更（未実装）", design,
        ))
        self._layout.addWidget(_PlaceholderSection(
            "配置", "segment の並び順を変更（未実装）", design,
        ))
        self._layout.addWidget(_PlaceholderSection(
            "常時ランダム", "spin ごとに配置をランダム化（未実装）", design,
        ))

        self._layout.addStretch()

        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    # ----------------------------------------------------------------
    #  spin 操作セクション
    # ----------------------------------------------------------------

    def _build_spin_section(self, design: DesignSettings):
        self._layout.addWidget(_SectionHeader("スピン", design))

        # spin ボタン
        self._spin_btn = QPushButton("▶  スピン開始")
        self._spin_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._spin_btn.setMinimumHeight(36)
        self._spin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._spin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.accent}; color: {design.text};"
            f"  border: none; border-radius: 6px; padding: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.separator}; }}"
            f"QPushButton:disabled {{ background-color: {design.separator}; color: {design.text_sub}; }}"
        )
        self._spin_btn.clicked.connect(self.spin_requested.emit)
        self._layout.addWidget(self._spin_btn)

        # プリセット選択
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)

        preset_lbl = QLabel("プリセット:")
        preset_lbl.setFont(QFont("Meiryo", 8))
        preset_lbl.setStyleSheet(f"color: {design.text_sub};")
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

    # ----------------------------------------------------------------
    #  項目リストセクション
    # ----------------------------------------------------------------

    def _build_items_section(self, items: list[str], design: DesignSettings):
        self._layout.addWidget(_SectionHeader("項目リスト", design))

        if not items:
            empty = QLabel("  （項目なし）")
            empty.setFont(QFont("Meiryo", 9))
            empty.setStyleSheet(f"color: {design.text_sub};")
            self._layout.addWidget(empty)
            return

        for item in items[:20]:
            card = QLabel(f"  {item}")
            card.setFont(QFont("Meiryo", 9))
            card.setStyleSheet(
                f"color: {design.text}; background-color: {design.separator}; "
                f"padding: 5px; border-radius: 3px;"
            )
            self._layout.addWidget(card)

        if len(items) > 20:
            more = QLabel(f"  ... 他 {len(items) - 20} 件")
            more.setFont(QFont("Meiryo", 8))
            more.setStyleSheet(f"color: {design.text_sub};")
            self._layout.addWidget(more)

    # ----------------------------------------------------------------
    #  内部ヘルパー
    # ----------------------------------------------------------------

    def _apply_scroll_style(self, design: DesignSettings):
        """スクロール領域にデザイン連動の配色を適用する。"""
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {design.panel}; }}"
            f"QScrollBar:vertical {{ width: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:vertical {{ background: {design.separator}; border-radius: 3px; }}"
        )

    @staticmethod
    def _apply_combo_style(combo: QComboBox, design: DesignSettings):
        """ComboBox にデザイン連動の配色を適用する。"""
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

    # ----------------------------------------------------------------
    #  公開 API
    # ----------------------------------------------------------------

    def set_spinning(self, spinning: bool):
        """spin 状態に応じてボタンを有効/無効にする。"""
        self._spin_btn.setEnabled(not spinning)
        self._spin_btn.setText("⏳  スピン中..." if spinning else "▶  スピン開始")

    def set_preset(self, name: str):
        """プリセット表示を外部から更新する。"""
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(name)
        self._preset_combo.blockSignals(False)

    def update_design(self, design: DesignSettings):
        """デザイン変更時にパネル全体の配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._content.setStyleSheet(f"background-color: {design.panel};")
        self._apply_scroll_style(design)
        self._apply_combo_style(self._preset_combo, design)
        self._spin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.accent}; color: {design.text};"
            f"  border: none; border-radius: 6px; padding: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.separator}; }}"
            f"QPushButton:disabled {{ background-color: {design.separator}; color: {design.text_sub}; }}"
        )
