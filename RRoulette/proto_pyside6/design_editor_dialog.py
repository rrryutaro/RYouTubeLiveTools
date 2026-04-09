"""
PySide6 プロトタイプ — デザインエディタダイアログ

独立したデザインエディタウィンドウ。
色・フォント・セグメントカラーの編集とプリセット管理を提供する。

責務:
  - GlobalColors の色編集（bg, panel, accent, text, text_sub, gold, separator）
  - WheelDesign の色編集（text_color, outline_color, segment_outline_color）
  - PointerDesign の色編集（fill_color, outline_color）
  - ResultDesign の色編集（bg_color, outline_color, text_color）
  - FontSettings の編集（wheel font family, ui_family, log_family, result_family）
  - SegmentDesign の配色プリセット切替とカスタム色編集
  - デザインプリセットの選択・複製・名前変更・削除・リセット

通知フロー:
  DesignEditorDialog → design_changed(DesignSettings) → MainWindow → 各コンポーネント
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QWidget, QColorDialog, QTabWidget,
    QLineEdit, QInputDialog, QMessageBox, QFontComboBox,
    QGridLayout,
)

from design_settings import (
    DesignSettings, DesignPresetManager,
    GlobalColors, WheelDesign, PointerDesign, ResultDesign,
    FontSettings, WheelFontSettings,
    SEGMENT_COLOR_PRESETS, SEGMENT_PRESET_NAMES,
    DESIGN_PRESETS,
)


class _ColorButton(QPushButton):
    """クリックで色選択ダイアログを開くボタン。"""

    color_changed = Signal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(32, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self.clicked.connect(self._pick_color)

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, color: str):
        self._color = color
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(
            f"background-color: {self._color};"
            f"border: 1px solid #888; border-radius: 3px;"
        )

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c.name()
            self._update_style()
            self.color_changed.emit(self._color)


class DesignEditorDialog(QDialog):
    """デザインエディタダイアログ。

    非モーダルの Tool ウィンドウとして動作する。
    色・フォント編集の結果は即時 design_changed シグナルで通知される。
    """

    design_changed = Signal(DesignSettings)

    def __init__(self, design: DesignSettings,
                 preset_manager: DesignPresetManager,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("デザインエディタ")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(420, 500)
        self.resize(460, 620)

        self._design = DesignSettings.from_dict(design.to_dict())
        self._preset_mgr = preset_manager

        self._building = False
        self._build_ui()

    def _build_ui(self):
        self._building = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        bg = self._design.bg
        panel = self._design.panel
        text = self._design.text
        text_sub = self._design.text_sub
        sep = self._design.separator
        accent = self._design.accent

        self.setStyleSheet(
            f"QDialog {{ background-color: {panel}; color: {text}; }}"
            f"QLabel {{ color: {text}; }}"
            f"QTabWidget::pane {{ border: 1px solid {sep}; background: {bg}; }}"
            f"QTabBar::tab {{ background: {sep}; color: {text}; padding: 6px 12px; }}"
            f"QTabBar::tab:selected {{ background: {accent}; }}"
            f"QPushButton {{ background-color: {sep}; color: {text}; border: none;"
            f"  border-radius: 3px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ background-color: {accent}; }}"
            f"QComboBox {{ background-color: {sep}; color: {text};"
            f"  border: 1px solid {sep}; border-radius: 3px; padding: 2px 4px; }}"
            f"QLineEdit {{ background-color: {sep}; color: {text};"
            f"  border: 1px solid {sep}; border-radius: 3px; padding: 2px 4px; }}"
        )

        # --- プリセット管理バー ---
        preset_bar = QHBoxLayout()
        preset_bar.setSpacing(4)

        preset_lbl = QLabel("プリセット:")
        preset_lbl.setFont(QFont("Meiryo", 9))
        preset_bar.addWidget(preset_lbl)

        self._preset_combo = QComboBox()
        self._preset_combo.setFont(QFont("Meiryo", 9))
        self._refresh_preset_combo()
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        preset_bar.addWidget(self._preset_combo, stretch=1)

        dup_btn = QPushButton("複製")
        dup_btn.setFont(QFont("Meiryo", 8))
        dup_btn.clicked.connect(self._duplicate_preset)
        preset_bar.addWidget(dup_btn)

        rename_btn = QPushButton("名前変更")
        rename_btn.setFont(QFont("Meiryo", 8))
        rename_btn.clicked.connect(self._rename_preset)
        preset_bar.addWidget(rename_btn)

        del_btn = QPushButton("削除")
        del_btn.setFont(QFont("Meiryo", 8))
        del_btn.clicked.connect(self._delete_preset)
        preset_bar.addWidget(del_btn)

        reset_btn = QPushButton("リセット")
        reset_btn.setFont(QFont("Meiryo", 8))
        reset_btn.setToolTip("組み込みプリセットを初期値に戻す")
        reset_btn.clicked.connect(self._reset_preset)
        preset_bar.addWidget(reset_btn)

        layout.addLayout(preset_bar)

        # --- タブウィジェット ---
        self._tabs = QTabWidget()
        self._tabs.setFont(QFont("Meiryo", 9))

        self._tabs.addTab(self._build_colors_tab(), "色")
        self._tabs.addTab(self._build_font_tab(), "フォント")
        self._tabs.addTab(self._build_segment_tab(), "セグメント")

        layout.addWidget(self._tabs)
        self._building = False

    # ================================================================
    #  色タブ
    # ================================================================

    def _build_colors_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(6)

        self._color_buttons = {}
        row = 0

        def add_section(title):
            nonlocal row
            lbl = QLabel(title)
            lbl.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {self._design.gold};")
            grid.addWidget(lbl, row, 0, 1, 2)
            row += 1

        def add_color(label, group, key, color):
            nonlocal row
            lbl = QLabel(label)
            lbl.setFont(QFont("Meiryo", 8))
            grid.addWidget(lbl, row, 0)
            btn = _ColorButton(color)
            btn.color_changed.connect(
                lambda c, g=group, k=key: self._on_color_changed(g, k, c)
            )
            grid.addWidget(btn, row, 1)
            self._color_buttons[(group, key)] = btn
            row += 1

        gc = self._design.global_colors
        add_section("全体カラー")
        add_color("背景色", "global", "bg", gc.bg)
        add_color("パネル色", "global", "panel", gc.panel)
        add_color("アクセント色", "global", "accent", gc.accent)
        add_color("文字色", "global", "text", gc.text)
        add_color("補助文字色", "global", "text_sub", gc.text_sub)
        add_color("ゴールド", "global", "gold", gc.gold)
        add_color("セパレーター", "global", "separator", gc.separator)

        wd = self._design.wheel
        add_section("ホイール")
        add_color("文字色", "wheel", "text_color", wd.text_color)
        add_color("外周線", "wheel", "outline_color", wd.outline_color)
        add_color("セグメント線", "wheel", "segment_outline_color",
                  wd.segment_outline_color)

        pd = self._design.pointer
        add_section("ポインター")
        add_color("塗りつぶし", "pointer", "fill_color", pd.fill_color)
        add_color("輪郭線", "pointer", "outline_color", pd.outline_color)

        rd = self._design.result
        add_section("結果表示")
        add_color("背景色", "result", "bg_color", rd.bg_color)
        add_color("枠線色", "result", "outline_color", rd.outline_color)
        add_color("文字色", "result", "text_color", rd.text_color)

        grid.setRowStretch(row, 1)
        scroll.setWidget(content)
        return scroll

    # ================================================================
    #  フォントタブ
    # ================================================================

    def _build_font_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._font_combos = {}

        def add_font_row(label, key, current_family):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label)
            lbl.setFont(QFont("Meiryo", 9))
            lbl.setMinimumWidth(100)
            row.addWidget(lbl)

            combo = QFontComboBox()
            combo.setFont(QFont("Meiryo", 8))
            combo.setCurrentFont(QFont(current_family))
            combo.currentFontChanged.connect(
                lambda f, k=key: self._on_font_changed(k, f.family())
            )
            row.addWidget(combo, stretch=1)
            self._font_combos[key] = combo
            layout.addLayout(row)

        fonts = self._design.fonts
        add_font_row("ホイール文字:", "wheel_family", fonts.wheel.family)
        add_font_row("UI:", "ui_family", fonts.ui_family)
        add_font_row("ログ:", "log_family", fonts.log_family)
        add_font_row("結果表示:", "result_family", fonts.result_family)

        layout.addStretch(1)
        return content

    # ================================================================
    #  セグメントカラータブ
    # ================================================================

    def _build_segment_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # セグメント配色プリセット選択
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        lbl = QLabel("配色プリセット:")
        lbl.setFont(QFont("Meiryo", 9))
        preset_row.addWidget(lbl)

        self._seg_preset_combo = QComboBox()
        self._seg_preset_combo.setFont(QFont("Meiryo", 8))
        for name in self._preset_mgr.all_segment_names():
            self._seg_preset_combo.addItem(name)
        self._seg_preset_combo.setCurrentText(
            self._design.segment.preset_name
        )
        self._seg_preset_combo.currentTextChanged.connect(
            self._on_segment_preset_changed
        )
        preset_row.addWidget(self._seg_preset_combo, stretch=1)
        layout.addLayout(preset_row)

        # カスタム色編集グリッド
        lbl2 = QLabel("色をクリックして編集:")
        lbl2.setFont(QFont("Meiryo", 8))
        lbl2.setStyleSheet(f"color: {self._design.text_sub};")
        layout.addWidget(lbl2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._seg_grid_container = QWidget()
        self._seg_grid = QGridLayout(self._seg_grid_container)
        self._seg_grid.setContentsMargins(4, 4, 4, 4)
        self._seg_grid.setSpacing(4)

        self._seg_color_buttons: list[_ColorButton] = []
        self._rebuild_segment_grid()

        scroll.setWidget(self._seg_grid_container)
        layout.addWidget(scroll, stretch=1)

        # 色の追加/削除ボタン
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        add_btn = QPushButton("＋ 色追加")
        add_btn.setFont(QFont("Meiryo", 8))
        add_btn.clicked.connect(self._add_segment_color)
        btn_row.addWidget(add_btn)

        del_btn = QPushButton("－ 末尾削除")
        del_btn.setFont(QFont("Meiryo", 8))
        del_btn.clicked.connect(self._remove_segment_color)
        btn_row.addWidget(del_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        return content

    def _rebuild_segment_grid(self):
        """セグメントカラーボタングリッドを再構築する。"""
        for btn in self._seg_color_buttons:
            btn.deleteLater()
        self._seg_color_buttons.clear()

        # 既存のアイテムをクリア
        while self._seg_grid.count():
            item = self._seg_grid.takeAt(0)
            w = item.widget()
            if w and w not in self._seg_color_buttons:
                w.deleteLater()

        colors = self._design.segment.resolve_colors()
        cols = 5
        for i, color in enumerate(colors):
            r, c = divmod(i, cols)

            idx_lbl = QLabel(f"{i+1}")
            idx_lbl.setFont(QFont("Meiryo", 7))
            idx_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._seg_grid.addWidget(idx_lbl, r * 2, c)

            btn = _ColorButton(color)
            btn.color_changed.connect(
                lambda clr, idx=i: self._on_segment_color_changed(idx, clr)
            )
            self._seg_grid.addWidget(btn, r * 2 + 1, c)
            self._seg_color_buttons.append(btn)

    # ================================================================
    #  色変更ハンドラ
    # ================================================================

    def _on_color_changed(self, group: str, key: str, color: str):
        if group == "global":
            setattr(self._design.global_colors, key, color)
        elif group == "wheel":
            setattr(self._design.wheel, key, color)
        elif group == "pointer":
            setattr(self._design.pointer, key, color)
        elif group == "result":
            setattr(self._design.result, key, color)
        self._emit_change()

    def _on_font_changed(self, key: str, family: str):
        if key == "wheel_family":
            self._design.fonts.wheel.family = family
        elif key == "ui_family":
            self._design.fonts.ui_family = family
        elif key == "log_family":
            self._design.fonts.log_family = family
        elif key == "result_family":
            self._design.fonts.result_family = family
        self._emit_change()

    def _on_segment_preset_changed(self, name: str):
        self._preset_mgr.apply_segment_to_design(name, self._design)
        self._rebuild_segment_grid()
        self._emit_change()

    def _on_segment_color_changed(self, idx: int, color: str):
        colors = list(self._design.segment.resolve_colors())
        if idx < len(colors):
            colors[idx] = color
        self._design.segment.custom_colors = colors
        self._emit_change()

    def _add_segment_color(self):
        colors = list(self._design.segment.resolve_colors())
        colors.append("#888888")
        self._design.segment.custom_colors = colors
        self._rebuild_segment_grid()
        self._emit_change()

    def _remove_segment_color(self):
        colors = list(self._design.segment.resolve_colors())
        if len(colors) > 2:
            colors.pop()
            self._design.segment.custom_colors = colors
            self._rebuild_segment_grid()
            self._emit_change()

    # ================================================================
    #  プリセット管理
    # ================================================================

    def _refresh_preset_combo(self):
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for name in self._preset_mgr.all_design_names():
            self._preset_combo.addItem(name)
        self._preset_combo.setCurrentText(self._design.preset_name)
        self._preset_combo.blockSignals(False)

    def _on_preset_selected(self, name: str):
        if self._building or not name:
            return
        ds = self._preset_mgr.get_design(name)
        self._design = ds
        self._refresh_color_buttons()
        self._refresh_font_combos()
        self._refresh_segment_ui()
        self._emit_change()

    def _duplicate_preset(self):
        current = self._preset_combo.currentText()
        name, ok = QInputDialog.getText(
            self, "プリセット複製",
            "新しいプリセット名:",
            text=f"{current} のコピー"
        )
        if ok and name and name.strip():
            name = name.strip()
            # 現在の編集状態を保存してから複製
            self._preset_mgr.save_design(current, self._design)
            ds = self._preset_mgr.duplicate_design(current, name)
            self._design = ds
            self._refresh_preset_combo()
            self._emit_change()

    def _rename_preset(self):
        current = self._preset_combo.currentText()
        if self._preset_mgr.is_builtin_design(current):
            QMessageBox.information(
                self, "名前変更",
                "組み込みプリセットの名前は変更できません。"
            )
            return
        name, ok = QInputDialog.getText(
            self, "プリセット名変更",
            "新しい名前:", text=current
        )
        if ok and name and name.strip() and name.strip() != current:
            name = name.strip()
            self._preset_mgr.rename_design(current, name)
            self._design.preset_name = name
            self._refresh_preset_combo()
            self._emit_change()

    def _delete_preset(self):
        current = self._preset_combo.currentText()
        if self._preset_mgr.is_builtin_design(current):
            QMessageBox.information(
                self, "削除",
                "組み込みプリセットは削除できません。"
            )
            return
        reply = QMessageBox.question(
            self, "プリセット削除",
            f"プリセット「{current}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._preset_mgr.delete_design(current)
            self._design = self._preset_mgr.get_design("デフォルト")
            self._refresh_preset_combo()
            self._refresh_color_buttons()
            self._refresh_font_combos()
            self._refresh_segment_ui()
            self._emit_change()

    def _reset_preset(self):
        current = self._preset_combo.currentText()
        if not self._preset_mgr.is_builtin_design(current):
            QMessageBox.information(
                self, "リセット",
                "ユーザー作成プリセットはリセットできません。\n"
                "削除して組み込みプリセットから再複製してください。"
            )
            return
        reply = QMessageBox.question(
            self, "プリセットリセット",
            f"プリセット「{current}」を初期値に戻しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            ds = self._preset_mgr.reset_design(current)
            self._design = ds
            self._refresh_color_buttons()
            self._refresh_font_combos()
            self._refresh_segment_ui()
            self._emit_change()

    # ================================================================
    #  UI 同期ヘルパー
    # ================================================================

    def _refresh_color_buttons(self):
        gc = self._design.global_colors
        wd = self._design.wheel
        pd = self._design.pointer
        rd = self._design.result
        mapping = {
            ("global", "bg"): gc.bg,
            ("global", "panel"): gc.panel,
            ("global", "accent"): gc.accent,
            ("global", "text"): gc.text,
            ("global", "text_sub"): gc.text_sub,
            ("global", "gold"): gc.gold,
            ("global", "separator"): gc.separator,
            ("wheel", "text_color"): wd.text_color,
            ("wheel", "outline_color"): wd.outline_color,
            ("wheel", "segment_outline_color"): wd.segment_outline_color,
            ("pointer", "fill_color"): pd.fill_color,
            ("pointer", "outline_color"): pd.outline_color,
            ("result", "bg_color"): rd.bg_color,
            ("result", "outline_color"): rd.outline_color,
            ("result", "text_color"): rd.text_color,
        }
        for key, color in mapping.items():
            btn = self._color_buttons.get(key)
            if btn:
                btn.blockSignals(True)
                btn.set_color(color)
                btn.blockSignals(False)

    def _refresh_font_combos(self):
        fonts = self._design.fonts
        mapping = {
            "wheel_family": fonts.wheel.family,
            "ui_family": fonts.ui_family,
            "log_family": fonts.log_family,
            "result_family": fonts.result_family,
        }
        for key, family in mapping.items():
            combo = self._font_combos.get(key)
            if combo:
                combo.blockSignals(True)
                combo.setCurrentFont(QFont(family))
                combo.blockSignals(False)

    def _refresh_segment_ui(self):
        self._seg_preset_combo.blockSignals(True)
        self._seg_preset_combo.setCurrentText(
            self._design.segment.preset_name
        )
        self._seg_preset_combo.blockSignals(False)
        self._rebuild_segment_grid()

    # ================================================================
    #  変更通知
    # ================================================================

    def _emit_change(self):
        if not self._building:
            # 現在のプリセットの編集状態を保存
            name = self._design.preset_name
            self._preset_mgr.save_design(name, self._design)
            self.design_changed.emit(self._design)

    def get_design(self) -> DesignSettings:
        """現在のデザイン設定を返す。"""
        return self._design
