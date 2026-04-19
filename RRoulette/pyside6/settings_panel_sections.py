"""
PySide6 — SettingsPanel セクションビルダーミックス

内容:
  アプリ設定セクションの _build_* メソッドとそのイベントハンドラ、
  スタイルヘルパーを _SectionsMixin として提供する。
  SettingsPanel はこの mixin を継承することで各 build メソッドを利用できる。
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QScrollArea, QWidget,
    QDoubleSpinBox, QSpinBox, QLineEdit, QStackedWidget, QSlider,
    QFileDialog, QMessageBox, QMenu,
)

from panel_widgets import _SectionHeader, CollapsibleSection, _PlaceholderSection

from bridge import (
    SIDEBAR_W, SIZE_PROFILES, DesignSettings,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
)
from app_settings import AppSettings
from item_entry import ItemEntry
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME
from dark_theme import dark_checkbox_style, dark_spinbox_style, get_header_colors


class _SectionsMixin:
    """アプリ設定セクションビルダー・イベントハンドラ・スタイルヘルパーの mixin。

    SettingsPanel に多重継承される。
    シグナルは SettingsPanel 側で定義されるため、この mixin 内で Signal() の定義は不要。
    """

    def _emit_collapsed_state(self):
        """現在の折りたたみ状態を保存フローへ送出する。"""
        state = {
            name: cs.is_collapsed
            for name, cs in self._collapsible_map.items()
        }
        self.setting_changed.emit("collapsed_sections", state)

    def _build_quick_settings_bar(self, outer_layout: QVBoxLayout,
                                   settings: AppSettings,
                                   design: DesignSettings):
        """常設のクイック設定行を組み立てる。

        v0.4.4 cfg_panel の「ウィンドウ表示」グループに相当。
        透過 (ウィンドウ / ルーレット個別) と常に最前面を、折りたたみ
        セクションの外に常設で配置する。
        """
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {design.panel};"
            f"  border-bottom: 1px solid {design.separator};"
            f"}}"
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(10)

        # ウィンドウ透過 (メインウィンドウ自体)
        self._window_transparent_cb = QCheckBox("ウィンドウ透過")
        self._window_transparent_cb.setFont(QFont("Meiryo", 8))
        self._window_transparent_cb.setStyleSheet(f"color: {design.text};")
        self._window_transparent_cb.setChecked(settings.window_transparent)
        self._window_transparent_cb.setToolTip(
            "メインウィンドウ自体の背景を透過する"
        )
        self._window_transparent_cb.toggled.connect(
            lambda v: self.setting_changed.emit("window_transparent", v)
        )
        bar_layout.addWidget(self._window_transparent_cb)

        # ルーレット透過 (ルーレットパネル単独)
        self._roulette_transparent_cb = QCheckBox("ルーレット透過")
        self._roulette_transparent_cb.setFont(QFont("Meiryo", 8))
        self._roulette_transparent_cb.setStyleSheet(f"color: {design.text};")
        self._roulette_transparent_cb.setChecked(settings.roulette_transparent)
        self._roulette_transparent_cb.setToolTip(
            "ルーレットパネル (ホイール領域) の背景を透過する"
        )
        self._roulette_transparent_cb.toggled.connect(
            lambda v: self.setting_changed.emit("roulette_transparent", v)
        )
        bar_layout.addWidget(self._roulette_transparent_cb)

        # 常に最前面
        self._aot_cb = QCheckBox("最前面")
        self._aot_cb.setFont(QFont("Meiryo", 8))
        self._aot_cb.setStyleSheet(f"color: {design.text};")
        self._aot_cb.setChecked(settings.always_on_top)
        self._aot_cb.setToolTip("メインウィンドウを常に最前面に表示")
        self._aot_cb.toggled.connect(
            lambda v: self.setting_changed.emit("always_on_top", v)
        )
        bar_layout.addWidget(self._aot_cb)

        # i468: 設定パネル独立化トグルボタン（項目パネルと同スタイル）
        _sp_float_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 5px;"
            f"  min-width: 22px; font-size: 8pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
            f"QPushButton:checked {{ background-color: {design.accent}; }}"
        )
        self._settings_float_btn = QPushButton("独")
        self._settings_float_btn.setFont(QFont("Meiryo", 8))
        self._settings_float_btn.setCheckable(True)
        self._settings_float_btn.setChecked(settings.settings_panel_float)
        self._settings_float_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_float_btn.setStyleSheet(_sp_float_btn_style)
        self._settings_float_btn.setToolTip(
            "独立化: 設定パネルをメインウィンドウから独立した\n"
            "フローティングウィンドウにします"
        )
        self._settings_float_btn.toggled.connect(
            lambda v: self.setting_changed.emit("settings_panel_float", v)
        )
        bar_layout.addWidget(self._settings_float_btn)

        bar_layout.addStretch(1)

        # 設定全体 export / import ボタン (i356)
        _cfg_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 22px; max-width: 22px; font-size: 9pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._cfg_export_btn = QPushButton("↑")
        self._cfg_export_btn.setFont(QFont("Meiryo", 9))
        self._cfg_export_btn.setStyleSheet(_cfg_btn_style)
        self._cfg_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cfg_export_btn.setToolTip("設定をエクスポート（設定値一式をJSONに書き出す）")
        self._cfg_export_btn.clicked.connect(self.settings_export_requested.emit)
        bar_layout.addWidget(self._cfg_export_btn)

        self._cfg_import_btn = QPushButton("↓")
        self._cfg_import_btn.setFont(QFont("Meiryo", 9))
        self._cfg_import_btn.setStyleSheet(_cfg_btn_style)
        self._cfg_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cfg_import_btn.setToolTip("設定をインポート（JSONから設定値一式を読み込む）")
        self._cfg_import_btn.clicked.connect(self.settings_import_requested.emit)
        bar_layout.addWidget(self._cfg_import_btn)

        outer_layout.addWidget(bar)
        self._quick_bar = bar

    def _on_section_toggled(self, toggled_name: str, collapsed: bool):
        """いずれかのセクションが開閉されたとき、排他開閉＋状態保存を行う。"""
        if not collapsed:
            # 開いた場合: 他の展開中セクションを閉じる
            for name, cs in self._collapsible_map.items():
                if name != toggled_name and not cs.is_collapsed:
                    # 外部化された項目 / パターンセクションは閉じない
                    if name == "items" and self._items_external:
                        continue
                    if name == "pattern" and self._pattern_external:
                        continue
                    cs.set_expanded(False)
        self._emit_collapsed_state()

    def pop_pattern_section(self) -> QWidget:
        """パターン (グループ) セクションを SettingsPanel から取り外して返す。

        ItemPanel など別フレームへ載せ替えるためのフック。
        - 親レイアウトから取り外す
        - 外部化フラグを立てて、排他開閉の対象から除外する
        - toggled シグナルを切断
        """
        if self._pattern_external:
            return self._pattern_collapsible

        self._layout.removeWidget(self._pattern_collapsible)
        # i289 t07: setParent(None) は top-level HWND を生成して起動時フラッシュの
        # 原因になるため廃止。レイアウトから外すだけにし、addWidget 側で再ペアレントさせる。
        try:
            self._pattern_collapsible.toggled.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._pattern_external = True
        return self._pattern_collapsible

    def pop_items_section(self) -> QWidget:
        """項目セクションを SettingsPanel から取り外して返す。

        ItemPanel など別フレームへ載せ替えるためのフック。
        - 親レイアウトから取り外す
        - 外部化フラグを立てて、排他開閉の対象から除外する
        - toggled シグナルを切断し、別パネル内での開閉が SettingsPanel
          の他セクションを誤って閉じないようにする
        - 戻り値は `_items_collapsible` (CollapsibleSection)。
          呼び出し側で新しい親へ addWidget することを想定する。
        """
        if self._items_external:
            return self._items_collapsible

        self._layout.removeWidget(self._items_collapsible)
        # i289 t07: setParent(None) は top-level HWND を生成して起動時フラッシュの
        # 原因になるため廃止。レイアウトから外すだけにし、addWidget 側で再ペアレントさせる。
        try:
            self._items_collapsible.toggled.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._items_external = True
        return self._items_collapsible

    # ================================================================
    #  セクション 1: スピン操作（実装済み）
    # ================================================================

    def _build_spin_section(self, settings: AppSettings,
                            design: DesignSettings):
        # スピンセクション全体をコンテナで囲む（ctrl_box_visible で一括制御用）
        self._spin_collapsible = CollapsibleSection("スピン", design, expanded=True, theme_mode=settings.theme_mode)
        self._spin_section = self._spin_collapsible
        spin_layout = self._spin_collapsible.content_layout

        # spin ボタン
        self._spin_btn = QPushButton("▶  スピン開始")
        self._spin_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._spin_btn.setMinimumHeight(36)
        self._spin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_spin_btn_style(design)
        self._spin_btn.clicked.connect(self.spin_requested.emit)
        spin_layout.addWidget(self._spin_btn)

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

        spin_layout.addLayout(preset_row)

        # スピン時間
        dur_row = QHBoxLayout()
        dur_row.setSpacing(4)

        dur_lbl = QLabel("スピン時間:")
        dur_lbl.setFont(QFont("Meiryo", 8))
        dur_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dur_lbl = dur_lbl
        dur_row.addWidget(dur_lbl)

        self._dur_spin = QDoubleSpinBox()
        self._dur_spin.setFont(QFont("Meiryo", 8))
        self._dur_spin.setRange(1.0, 30.0)
        self._dur_spin.setSingleStep(1.0)
        self._dur_spin.setDecimals(1)
        self._dur_spin.setSuffix(" 秒")
        self._dur_spin.setValue(settings.spin_duration)
        self._dur_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._dur_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("spin_duration", v)
        )
        dur_row.addWidget(self._dur_spin, stretch=1)

        spin_layout.addLayout(dur_row)

        # スピンモード選択
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)

        mode_lbl = QLabel("モード:")
        mode_lbl.setFont(QFont("Meiryo", 8))
        mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._mode_lbl = mode_lbl
        mode_row.addWidget(mode_lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._mode_combo, design)
        self._mode_combo.addItems(["シングル", "ダブル", "トリプル"])
        self._mode_combo.setCurrentIndex(settings.spin_mode)
        self._mode_combo.currentIndexChanged.connect(self._on_spin_mode_changed)
        mode_row.addWidget(self._mode_combo, stretch=1)

        spin_layout.addLayout(mode_row)

        # ダブルスピン時間
        dbl_row = QHBoxLayout()
        dbl_row.setSpacing(4)

        dbl_lbl = QLabel("ダブル時間:")
        dbl_lbl.setFont(QFont("Meiryo", 8))
        dbl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._dbl_lbl = dbl_lbl
        dbl_row.addWidget(dbl_lbl)

        self._dbl_spin = QDoubleSpinBox()
        self._dbl_spin.setFont(QFont("Meiryo", 8))
        self._dbl_spin.setRange(1.0, 30.0)
        self._dbl_spin.setSingleStep(1.0)
        self._dbl_spin.setDecimals(1)
        self._dbl_spin.setSuffix(" 秒")
        self._dbl_spin.setValue(settings.double_duration)
        self._dbl_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._dbl_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("double_duration", v)
        )
        dbl_row.addWidget(self._dbl_spin, stretch=1)

        self._dbl_row_widget = QWidget(self._spin_collapsible._container)  # i289 t09
        dbl_row_container = QHBoxLayout(self._dbl_row_widget)
        dbl_row_container.setContentsMargins(0, 0, 0, 0)
        dbl_row_container.setSpacing(4)
        dbl_row_container.addWidget(self._dbl_lbl)
        dbl_row_container.addWidget(self._dbl_spin, stretch=1)
        spin_layout.addWidget(self._dbl_row_widget)

        # トリプルスピン時間
        self._tpl_row_widget = QWidget(self._spin_collapsible._container)  # i289 t09
        tpl_row_container = QHBoxLayout(self._tpl_row_widget)
        tpl_row_container.setContentsMargins(0, 0, 0, 0)
        tpl_row_container.setSpacing(4)

        tpl_lbl = QLabel("トリプル時間:")
        tpl_lbl.setFont(QFont("Meiryo", 8))
        tpl_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tpl_lbl = tpl_lbl
        tpl_row_container.addWidget(tpl_lbl)

        self._tpl_spin = QDoubleSpinBox()
        self._tpl_spin.setFont(QFont("Meiryo", 8))
        self._tpl_spin.setRange(1.0, 30.0)
        self._tpl_spin.setSingleStep(1.0)
        self._tpl_spin.setDecimals(1)
        self._tpl_spin.setSuffix(" 秒")
        self._tpl_spin.setValue(settings.triple_duration)
        self._tpl_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._tpl_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("triple_duration", v)
        )
        tpl_row_container.addWidget(self._tpl_spin, stretch=1)
        spin_layout.addWidget(self._tpl_row_widget)

        # 初期表示: モードに応じて duration 行の表示/非表示
        self._update_duration_rows_visibility(settings.spin_mode)

        self._layout.addWidget(self._spin_collapsible)

    def _on_spin_mode_changed(self, index: int):
        """スピンモード変更時のハンドラ。"""
        self._update_duration_rows_visibility(index)
        self.setting_changed.emit("spin_mode", index)

    def _update_duration_rows_visibility(self, mode: int):
        """スピンモードに応じて duration 行の表示を切り替える。"""
        # シングル: 通常スピン時間のみ表示
        # ダブル: ダブル時間のみ表示（通常時間は非表示）
        # トリプル: トリプル時間のみ表示（通常時間は非表示）
        self._dur_lbl.setVisible(mode == 0)
        self._dur_spin.setVisible(mode == 0)
        self._dbl_row_widget.setVisible(mode == 1)
        self._tpl_row_widget.setVisible(mode == 2)

    # ================================================================
    #  セクション 2: 表示設定（実装済み）
    # ================================================================

    def _build_display_section(self, settings: AppSettings,
                               design: DesignSettings):
        self._display_section = CollapsibleSection("表示", design, expanded=True, theme_mode=settings.theme_mode)
        sec = self._display_section.content_layout
        self._layout.addWidget(self._display_section)

        # テーマモード
        theme_row = QHBoxLayout()
        theme_row.setSpacing(4)
        theme_lbl = QLabel("テーマ:")
        theme_lbl.setFont(QFont("Meiryo", 8))
        theme_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._theme_lbl = theme_lbl
        theme_row.addWidget(theme_lbl)

        self._theme_combo = QComboBox()
        self._theme_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._theme_combo, design)
        self._theme_combo.addItems(["ダーク", "ライト", "システム"])
        _theme_idx_map = {"dark": 0, "light": 1, "system": 2, "auto": 2}
        self._theme_combo.setCurrentIndex(
            _theme_idx_map.get(settings.theme_mode, 0)
        )
        _theme_val_map = ["dark", "light", "system"]
        self._theme_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit(
                "theme_mode", _theme_val_map[idx] if idx < len(_theme_val_map) else "dark"
            )
        )
        theme_row.addWidget(self._theme_combo, stretch=1)
        sec.addLayout(theme_row)

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
        sec.addLayout(text_row)

        # ドーナツ穴
        self._donut_cb = QCheckBox("ドーナツ穴")
        self._donut_cb.setFont(QFont("Meiryo", 8))
        self._donut_cb.setStyleSheet(f"color: {design.text};")
        self._donut_cb.setChecked(settings.donut_hole)
        self._donut_cb.toggled.connect(
            lambda v: self.setting_changed.emit("donut_hole", v)
        )
        sec.addWidget(self._donut_cb)

        # 透過モード はクイック設定バー（パネル上部）に常設化したため
        # ここには配置しない。

        # インスタンス番号表示
        self._instance_label_cb = QCheckBox("インスタンス番号表示")
        self._instance_label_cb.setFont(QFont("Meiryo", 8))
        self._instance_label_cb.setStyleSheet(f"color: {design.text};")
        self._instance_label_cb.setChecked(settings.float_win_show_instance)
        self._instance_label_cb.toggled.connect(
            lambda v: self.setting_changed.emit("float_win_show_instance", v)
        )
        sec.addWidget(self._instance_label_cb)

        # i468: 設定パネル独立化はクイック設定バーの「独」ボタンに移動済み

        # サイズプロファイル（アクティブなルーレットパネルのサイズを即時変更）
        prof_row = QHBoxLayout()
        prof_row.setSpacing(4)
        prof_lbl = QLabel("ルーレットサイズ:")
        prof_lbl.setFont(QFont("Meiryo", 8))
        prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        prof_lbl.setToolTip("アクティブなルーレットパネルのサイズを変更します。")
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
        sec.addLayout(prof_row)

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
        sec.addLayout(tdir_row)

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
        sec.addLayout(sdir_row)

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
        sec.addLayout(ptr_row)

        # i289: 項目削除確認（項目パネルから移動）
        self._confirm_item_delete_cb = QCheckBox("項目削除時に確認する")
        self._confirm_item_delete_cb.setFont(QFont("Meiryo", 8))
        self._confirm_item_delete_cb.setStyleSheet(f"color: {design.text};")
        self._confirm_item_delete_cb.setChecked(settings.confirm_item_delete)
        self._confirm_item_delete_cb.setToolTip(
            "ON: 項目削除前に確認ダイアログを表示する\n"
            "OFF: 確認なしで即時削除する"
        )
        self._confirm_item_delete_cb.toggled.connect(
            lambda v: self.setting_changed.emit("confirm_item_delete", v)
        )
        sec.addWidget(self._confirm_item_delete_cb)

        # i289: 配置方向（項目パネルから移動）
        arr_row = QHBoxLayout()
        arr_row.setSpacing(4)
        arr_lbl = QLabel("配置方向:")
        arr_lbl.setFont(QFont("Meiryo", 8))
        arr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._arr_lbl = arr_lbl
        arr_row.addWidget(arr_lbl)
        self._arr_combo = QComboBox()
        self._arr_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._arr_combo, design)
        for name in ["時計回り", "反時計回り"]:
            self._arr_combo.addItem(name)
        self._arr_combo.setCurrentIndex(settings.arrangement_direction)
        self._arr_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("arrangement_direction", idx)
        )
        arr_row.addWidget(self._arr_combo, stretch=1)
        sec.addLayout(arr_row)

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
    #  セクション: デザイン設定
    # ================================================================

    def _build_design_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._design_collapsible = CollapsibleSection("デザイン", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._design_collapsible.content_layout
        self._layout.addWidget(self._design_collapsible)

        self._design_editor_btn = QPushButton("デザインエディタを開く")
        self._design_editor_btn.setFont(QFont("Meiryo", 9))
        self._design_editor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._design_editor_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 6px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._design_editor_btn.clicked.connect(
            self.design_editor_requested.emit
        )
        sec.addWidget(self._design_editor_btn)

    # ================================================================
    #  セクション 3: 結果表示設定（実装済み）
    # ================================================================

    def _build_result_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._result_collapsible = CollapsibleSection("結果表示", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._result_collapsible.content_layout
        self._layout.addWidget(self._result_collapsible)

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
        sec.addLayout(mode_row)

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
        sec.addLayout(sec_row)

        # 再生時保持秒数（チェックボックスで通常保持の継承/個別設定を切替）
        macro_cb_row = QHBoxLayout()
        macro_cb_row.setSpacing(4)
        self._macro_hold_cb = QCheckBox("マクロ再生時の保持を個別設定")
        self._macro_hold_cb.setFont(QFont("Meiryo", 8))
        self._macro_hold_cb.setStyleSheet(f"color: {design.text_sub};")
        macro_cb_row.addWidget(self._macro_hold_cb)
        sec.addLayout(macro_cb_row)

        macro_sec_row = QHBoxLayout()
        macro_sec_row.setSpacing(4)
        self._macro_sec_lbl = QLabel("  マクロ時:")
        self._macro_sec_lbl.setFont(QFont("Meiryo", 8))
        self._macro_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        macro_sec_row.addWidget(self._macro_sec_lbl)

        self._macro_sec_spin = QDoubleSpinBox()
        self._macro_sec_spin.setFont(QFont("Meiryo", 8))
        self._macro_sec_spin.setRange(0.5, 30.0)
        self._macro_sec_spin.setSingleStep(0.5)
        self._macro_sec_spin.setDecimals(1)
        self._macro_sec_spin.setSuffix(" 秒")
        self._macro_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )

        is_custom = settings.macro_hold_sec is not None
        self._macro_hold_cb.setChecked(is_custom)
        if is_custom:
            self._macro_sec_spin.setValue(settings.macro_hold_sec)
        else:
            self._macro_sec_spin.setValue(settings.result_hold_sec)
        self._macro_sec_spin.setEnabled(is_custom)
        self._macro_sec_lbl.setEnabled(is_custom)

        self._macro_hold_cb.toggled.connect(self._on_macro_hold_toggled)
        self._macro_sec_spin.valueChanged.connect(self._on_macro_hold_value_changed)

        macro_sec_row.addWidget(self._macro_sec_spin, stretch=1)
        sec.addLayout(macro_sec_row)

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

    def _on_macro_hold_toggled(self, checked: bool):
        """再生時保持の個別設定チェックボックス切替。"""
        self._macro_sec_spin.setEnabled(checked)
        self._macro_sec_lbl.setEnabled(checked)
        if checked:
            self.setting_changed.emit("macro_hold_sec",
                                      self._macro_sec_spin.value())
        else:
            # 未設定に戻す: 表示を通常保持の現在値に追従させる
            self._macro_sec_spin.blockSignals(True)
            self._macro_sec_spin.setValue(self._result_sec_spin.value())
            self._macro_sec_spin.blockSignals(False)
            self.setting_changed.emit("macro_hold_sec", None)

    def _on_macro_hold_value_changed(self, value: float):
        """再生時保持のスピンボックス値変更。"""
        if self._macro_hold_cb.isChecked():
            self.setting_changed.emit("macro_hold_sec", value)

    # ================================================================
    #  セクション 3b: サウンド設定（AppSettings 側）
    # ================================================================

    def _build_sound_section(self, settings: AppSettings,
                             design: DesignSettings):
        self._sound_collapsible = CollapsibleSection("サウンド", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._sound_collapsible.content_layout
        self._layout.addWidget(self._sound_collapsible)

        # tick 音 ON/OFF
        self._sound_tick_cb = QCheckBox("スピン音")
        self._sound_tick_cb.setFont(QFont("Meiryo", 8))
        self._sound_tick_cb.setStyleSheet(f"color: {design.text};")
        self._sound_tick_cb.setChecked(settings.sound_tick_enabled)
        self._sound_tick_cb.toggled.connect(
            lambda v: self.setting_changed.emit("sound_tick_enabled", v)
        )
        sec.addWidget(self._sound_tick_cb)

        # result 音 ON/OFF
        self._sound_result_cb = QCheckBox("決定音")
        self._sound_result_cb.setFont(QFont("Meiryo", 8))
        self._sound_result_cb.setStyleSheet(f"color: {design.text};")
        self._sound_result_cb.setChecked(settings.sound_result_enabled)
        self._sound_result_cb.toggled.connect(
            lambda v: self.setting_changed.emit("sound_result_enabled", v)
        )
        sec.addWidget(self._sound_result_cb)

        # tick 音量スライダー
        tick_vol_row = QHBoxLayout()
        tick_vol_row.setSpacing(4)
        tick_vol_lbl = QLabel("スピン音量:")
        tick_vol_lbl.setFont(QFont("Meiryo", 8))
        tick_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tick_vol_lbl = tick_vol_lbl
        tick_vol_row.addWidget(tick_vol_lbl)

        self._tick_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._tick_vol_slider.setRange(0, 100)
        self._tick_vol_slider.setValue(settings.tick_volume)
        self._tick_vol_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{"
            f"  background: {design.separator}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {design.accent}; width: 12px; margin: -4px 0;"
            f"  border-radius: 6px;"
            f"}}"
        )
        self._tick_vol_slider.valueChanged.connect(
            lambda v: self.setting_changed.emit("tick_volume", v)
        )
        tick_vol_row.addWidget(self._tick_vol_slider, stretch=1)

        self._tick_vol_val = QLabel(f"{settings.tick_volume}%")
        self._tick_vol_val.setFont(QFont("Meiryo", 7))
        self._tick_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._tick_vol_val.setFixedWidth(32)
        self._tick_vol_slider.valueChanged.connect(
            lambda v: self._tick_vol_val.setText(f"{v}%")
        )
        tick_vol_row.addWidget(self._tick_vol_val)
        sec.addLayout(tick_vol_row)

        # result 音量スライダー
        win_vol_row = QHBoxLayout()
        win_vol_row.setSpacing(4)
        win_vol_lbl = QLabel("決定音量:")
        win_vol_lbl.setFont(QFont("Meiryo", 8))
        win_vol_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_lbl = win_vol_lbl
        win_vol_row.addWidget(win_vol_lbl)

        self._win_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._win_vol_slider.setRange(0, 100)
        self._win_vol_slider.setValue(settings.win_volume)
        self._win_vol_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{"
            f"  background: {design.separator}; height: 4px; border-radius: 2px;"
            f"}}"
            f"QSlider::handle:horizontal {{"
            f"  background: {design.accent}; width: 12px; margin: -4px 0;"
            f"  border-radius: 6px;"
            f"}}"
        )
        self._win_vol_slider.valueChanged.connect(
            lambda v: self.setting_changed.emit("win_volume", v)
        )
        win_vol_row.addWidget(self._win_vol_slider, stretch=1)

        self._win_vol_val = QLabel(f"{settings.win_volume}%")
        self._win_vol_val.setFont(QFont("Meiryo", 7))
        self._win_vol_val.setStyleSheet(f"color: {design.text_sub};")
        self._win_vol_val.setFixedWidth(32)
        self._win_vol_slider.valueChanged.connect(
            lambda v: self._win_vol_val.setText(f"{v}%")
        )
        win_vol_row.addWidget(self._win_vol_val)
        sec.addLayout(win_vol_row)

        # tick 音パターン選択
        from sound_manager import TICK_PATTERN_NAMES, WIN_PATTERN_NAMES
        self._TICK_CUSTOM_IDX = len(TICK_PATTERN_NAMES) - 1
        self._WIN_CUSTOM_IDX = len(WIN_PATTERN_NAMES) - 1

        tick_pat_row = QHBoxLayout()
        tick_pat_row.setSpacing(4)
        tick_pat_lbl = QLabel("スピン音:")
        tick_pat_lbl.setFont(QFont("Meiryo", 8))
        tick_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tick_pat_lbl = tick_pat_lbl
        tick_pat_row.addWidget(tick_pat_lbl)

        self._tick_pat_combo = QComboBox()
        self._tick_pat_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._tick_pat_combo, design)
        for name in TICK_PATTERN_NAMES:
            self._tick_pat_combo.addItem(name)
        self._tick_pat_combo.setCurrentIndex(
            min(settings.tick_pattern, len(TICK_PATTERN_NAMES) - 1)
        )
        self._tick_pat_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("tick_pattern", idx)
        )
        tick_pat_row.addWidget(self._tick_pat_combo, stretch=1)

        small_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        self._tick_file_btn = QPushButton("📁")
        self._tick_file_btn.setFont(QFont("Meiryo", 8))
        self._tick_file_btn.setStyleSheet(small_btn_style)
        self._tick_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tick_file_btn.setToolTip("カスタムスピン音ファイルを選択")
        self._tick_file_btn.clicked.connect(self._on_tick_custom_browse)
        tick_pat_row.addWidget(self._tick_file_btn)

        self._tick_test_btn = QPushButton("♪")
        self._tick_test_btn.setFont(QFont("Meiryo", 8))
        self._tick_test_btn.setStyleSheet(small_btn_style)
        self._tick_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tick_test_btn.setToolTip("スピン音をテスト再生")
        self._tick_test_btn.clicked.connect(self.preview_tick_requested.emit)
        tick_pat_row.addWidget(self._tick_test_btn)

        sec.addLayout(tick_pat_row)

        # result 音パターン選択
        win_pat_row = QHBoxLayout()
        win_pat_row.setSpacing(4)
        win_pat_lbl = QLabel("決定音:")
        win_pat_lbl.setFont(QFont("Meiryo", 8))
        win_pat_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._win_pat_lbl = win_pat_lbl
        win_pat_row.addWidget(win_pat_lbl)

        self._win_pat_combo = QComboBox()
        self._win_pat_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._win_pat_combo, design)
        for name in WIN_PATTERN_NAMES:
            self._win_pat_combo.addItem(name)
        self._win_pat_combo.setCurrentIndex(
            min(settings.win_pattern, len(WIN_PATTERN_NAMES) - 1)
        )
        self._win_pat_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("win_pattern", idx)
        )
        win_pat_row.addWidget(self._win_pat_combo, stretch=1)

        self._win_file_btn = QPushButton("📁")
        self._win_file_btn.setFont(QFont("Meiryo", 8))
        self._win_file_btn.setStyleSheet(small_btn_style)
        self._win_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._win_file_btn.setToolTip("カスタム決定音ファイルを選択")
        self._win_file_btn.clicked.connect(self._on_win_custom_browse)
        win_pat_row.addWidget(self._win_file_btn)

        self._win_test_btn = QPushButton("♪")
        self._win_test_btn.setFont(QFont("Meiryo", 8))
        self._win_test_btn.setStyleSheet(small_btn_style)
        self._win_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._win_test_btn.setToolTip("決定音をテスト再生")
        self._win_test_btn.clicked.connect(self.preview_win_requested.emit)
        win_pat_row.addWidget(self._win_test_btn)

        sec.addLayout(win_pat_row)

    def _on_tick_custom_browse(self):
        """カスタムtick音ファイル選択ダイアログ。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "スピン音ファイルを選択", "",
            "音声ファイル (*.wav *.mp3 *.ogg);;全てのファイル (*)"
        )
        if path:
            self._tick_pat_combo.blockSignals(True)
            self._tick_pat_combo.setCurrentIndex(self._TICK_CUSTOM_IDX)
            self._tick_pat_combo.blockSignals(False)
            self.setting_changed.emit("tick_pattern", self._TICK_CUSTOM_IDX)
            self.custom_tick_file_changed.emit(path)

    def _on_win_custom_browse(self):
        """カスタムresult音ファイル選択ダイアログ。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "決定音ファイルを選択", "",
            "音声ファイル (*.wav *.mp3 *.ogg);;全てのファイル (*)"
        )
        if path:
            self._win_pat_combo.blockSignals(True)
            self._win_pat_combo.setCurrentIndex(self._WIN_CUSTOM_IDX)
            self._win_pat_combo.blockSignals(False)
            self.setting_changed.emit("win_pattern", self._WIN_CUSTOM_IDX)
            self.custom_win_file_changed.emit(path)

    # ================================================================
    #  セクション 3d: ログオーバーレイ
    # ================================================================

    def _build_log_section(self, settings: AppSettings,
                           design: DesignSettings):
        self._log_collapsible = CollapsibleSection("ログ", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._log_collapsible.content_layout
        self._layout.addWidget(self._log_collapsible)

        # i342: ログ表示 ON/OFF (log_overlay_show) を明示的に持たせる。
        self._log_show_cb = QCheckBox("ログ表示")
        self._log_show_cb.setFont(QFont("Meiryo", 8))
        self._log_show_cb.setStyleSheet(f"color: {design.text};")
        self._log_show_cb.setChecked(settings.log_overlay_show)
        self._log_show_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_overlay_show", v)
        )
        sec.addWidget(self._log_show_cb)

        self._log_ts_cb = QCheckBox("タイムスタンプ表示")
        self._log_ts_cb.setFont(QFont("Meiryo", 8))
        self._log_ts_cb.setStyleSheet(f"color: {design.text};")
        self._log_ts_cb.setChecked(settings.log_timestamp)
        self._log_ts_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_timestamp", v)
        )
        sec.addWidget(self._log_ts_cb)

        self._log_border_cb = QCheckBox("枠線表示")
        self._log_border_cb.setFont(QFont("Meiryo", 8))
        self._log_border_cb.setStyleSheet(f"color: {design.text};")
        self._log_border_cb.setChecked(settings.log_box_border)
        self._log_border_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_box_border", v)
        )
        sec.addWidget(self._log_border_cb)

        self._log_on_top_cb = QCheckBox("ログ前面表示")
        self._log_on_top_cb.setFont(QFont("Meiryo", 8))
        self._log_on_top_cb.setStyleSheet(f"color: {design.text};")
        self._log_on_top_cb.setChecked(settings.log_on_top)
        self._log_on_top_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_on_top", v)
        )
        sec.addWidget(self._log_on_top_cb)

        self._log_all_patterns_cb = QCheckBox("全パターンのログを表示")
        self._log_all_patterns_cb.setFont(QFont("Meiryo", 8))
        self._log_all_patterns_cb.setStyleSheet(f"color: {design.text};")
        self._log_all_patterns_cb.setChecked(settings.log_history_all_patterns)
        self._log_all_patterns_cb.setToolTip(
            "ON: 全パターンのログを表示\nOFF（既定）: 選択中パターンのログのみ表示"
        )
        self._log_all_patterns_cb.toggled.connect(
            lambda v: self.setting_changed.emit("log_history_all_patterns", v)
        )
        sec.addWidget(self._log_all_patterns_cb)

        # リセット確認
        self._confirm_reset_cb = QCheckBox("リセット確認")
        self._confirm_reset_cb.setFont(QFont("Meiryo", 8))
        self._confirm_reset_cb.setStyleSheet(f"color: {design.text};")
        self._confirm_reset_cb.setChecked(settings.confirm_reset)
        self._confirm_reset_cb.toggled.connect(
            lambda v: self.setting_changed.emit("confirm_reset", v)
        )
        sec.addWidget(self._confirm_reset_cb)

        # ログ操作ボタン行
        log_btn_row = QHBoxLayout()
        log_btn_row.setSpacing(4)

        self._log_export_btn = QPushButton("エクスポート")
        self._log_export_btn.setFont(QFont("Meiryo", 8))
        self._log_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_export_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._log_export_btn.clicked.connect(self.log_export_requested.emit)
        log_btn_row.addWidget(self._log_export_btn)

        self._log_import_btn = QPushButton("インポート")
        self._log_import_btn.setFont(QFont("Meiryo", 8))
        self._log_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_import_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._log_import_btn.clicked.connect(self.log_import_requested.emit)
        log_btn_row.addWidget(self._log_import_btn)

        self._log_clear_btn = QPushButton("履歴クリア")
        self._log_clear_btn.setFont(QFont("Meiryo", 8))
        self._log_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_clear_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._log_clear_btn.clicked.connect(self.log_clear_requested.emit)
        log_btn_row.addWidget(self._log_clear_btn)

        self._graph_btn = QPushButton("グラフ")
        self._graph_btn.setFont(QFont("Meiryo", 8))
        self._graph_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._graph_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._graph_btn.clicked.connect(self.graph_requested.emit)
        log_btn_row.addWidget(self._graph_btn)

        sec.addLayout(log_btn_row)

    # ================================================================
    #  セクション: リプレイ
    # ================================================================

    def _build_replay_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._replay_collapsible = CollapsibleSection("リプレイ", design, expanded=False, theme_mode=settings.theme_mode)
        sec = self._replay_collapsible.content_layout
        self._layout.addWidget(self._replay_collapsible)

        # リプレイ件数表示 + 再生/中断ボタン
        replay_row = QHBoxLayout()
        replay_row.setSpacing(4)

        self._replay_count_lbl = QLabel("記録: 0件")
        self._replay_count_lbl.setFont(QFont("Meiryo", 8))
        self._replay_count_lbl.setStyleSheet(f"color: {design.text_sub};")
        replay_row.addWidget(self._replay_count_lbl)

        replay_row.addStretch(1)

        self._replay_play_btn = QPushButton("最新を再生")
        self._replay_play_btn.setFont(QFont("Meiryo", 8))
        self._replay_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._replay_play_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._replay_play_btn.clicked.connect(self.replay_play_requested.emit)
        replay_row.addWidget(self._replay_play_btn)

        self._replay_stop_btn = QPushButton("中断")
        self._replay_stop_btn.setFont(QFont("Meiryo", 8))
        self._replay_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._replay_stop_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._replay_stop_btn.setEnabled(False)
        self._replay_stop_btn.clicked.connect(self.replay_stop_requested.emit)
        replay_row.addWidget(self._replay_stop_btn)

        self._replay_mgr_btn = QPushButton("管理...")
        self._replay_mgr_btn.setFont(QFont("Meiryo", 8))
        self._replay_mgr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._replay_mgr_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._replay_mgr_btn.clicked.connect(
            self.replay_manager_requested.emit
        )
        replay_row.addWidget(self._replay_mgr_btn)

        sec.addLayout(replay_row)

        # 設定行: 保存上限
        max_row = QHBoxLayout()
        max_row.setSpacing(4)

        max_lbl = QLabel("保存上限:")
        max_lbl.setFont(QFont("Meiryo", 8))
        max_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._replay_max_lbl = max_lbl
        max_row.addWidget(max_lbl)

        self._replay_max_spin = QSpinBox()
        self._replay_max_spin.setFont(QFont("Meiryo", 8))
        self._replay_max_spin.setRange(1, 20)
        self._replay_max_spin.setValue(settings.replay_max_count)
        self._replay_max_spin.setStyleSheet(
            f"QSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._replay_max_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("replay_max_count", v)
        )
        max_row.addWidget(self._replay_max_spin)

        max_row.addStretch(1)

        sec.addLayout(max_row)

        # 設定行: 再生中表示
        self._replay_indicator_cb = QCheckBox("再生中表示")
        self._replay_indicator_cb.setFont(QFont("Meiryo", 8))
        self._replay_indicator_cb.setStyleSheet(f"color: {design.text};")
        self._replay_indicator_cb.setChecked(settings.replay_show_indicator)
        self._replay_indicator_cb.toggled.connect(
            lambda v: self.setting_changed.emit("replay_show_indicator", v)
        )
        sec.addWidget(self._replay_indicator_cb)

    def set_replay_count(self, count: int):
        """リプレイ件数表示を更新する。"""
        self._replay_count_lbl.setText(f"記録: {count}件")
        self._replay_play_btn.setEnabled(count > 0)

    def set_replay_playing(self, playing: bool):
        """リプレイ再生中の UI 状態を設定する。"""
        self._replay_play_btn.setEnabled(not playing)
        self._replay_stop_btn.setEnabled(playing)

    # ================================================================
    #  セクション 3c: パターン管理
    # ================================================================

    def _build_pattern_section(self, design: DesignSettings):
        """パターン選択・追加・削除セクションを構築する。"""
        self._pattern_collapsible = CollapsibleSection("パターン", design, expanded=False, theme_mode=self._settings.theme_mode)
        sec = self._pattern_collapsible.content_layout
        self._layout.addWidget(self._pattern_collapsible)

        # パターン選択行: [コンボ] [✎] [＋] [－] [↑] [↓]
        pat_row = QHBoxLayout()
        pat_row.setSpacing(4)

        self._pattern_combo = QComboBox()
        self._pattern_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._pattern_combo, design)
        for name in self._pattern_names:
            self._pattern_combo.addItem(name)
        self._pattern_combo.setCurrentText(self._current_pattern)
        self._pattern_combo.currentTextChanged.connect(self._on_pattern_switched)
        pat_row.addWidget(self._pattern_combo, stretch=1)

        btn_font = QFont("Meiryo", 8)
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        # i403: 名前変更ボタンをコンボの直後に配置
        self._pattern_rename_btn = QPushButton("✎")
        self._pattern_rename_btn.setFont(btn_font)
        self._pattern_rename_btn.setStyleSheet(btn_style)
        self._pattern_rename_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_rename_btn.setToolTip("パターン名を変更")
        self._pattern_rename_btn.clicked.connect(self._on_pattern_rename_btn)
        pat_row.addWidget(self._pattern_rename_btn)

        self._pattern_add_btn = QPushButton("＋")
        self._pattern_add_btn.setFont(btn_font)
        self._pattern_add_btn.setStyleSheet(btn_style)
        self._pattern_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_add_btn.setToolTip("新しいパターンを追加")
        self._pattern_add_btn.clicked.connect(self._on_pattern_add)
        pat_row.addWidget(self._pattern_add_btn)

        del_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 6px;"
            f"  min-width: 24px; max-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        self._pattern_del_btn = QPushButton("－")
        self._pattern_del_btn.setFont(btn_font)
        self._pattern_del_btn.setStyleSheet(del_btn_style)
        self._pattern_del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_del_btn.setToolTip("現在のパターンを削除")
        self._pattern_del_btn.clicked.connect(self._on_pattern_delete)
        pat_row.addWidget(self._pattern_del_btn)

        self._pattern_export_btn = QPushButton("↑")
        self._pattern_export_btn.setFont(btn_font)
        self._pattern_export_btn.setStyleSheet(btn_style)
        self._pattern_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_export_btn.setToolTip("現在のパターンをエクスポート")
        self._pattern_export_btn.clicked.connect(self.pattern_export_requested.emit)
        pat_row.addWidget(self._pattern_export_btn)

        self._pattern_import_btn = QPushButton("↓")
        self._pattern_import_btn.setFont(btn_font)
        self._pattern_import_btn.setStyleSheet(btn_style)
        self._pattern_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pattern_import_btn.setToolTip("パターンをインポート")
        self._pattern_import_btn.clicked.connect(self.pattern_import_requested.emit)
        pat_row.addWidget(self._pattern_import_btn)

        sec.addLayout(pat_row)
        self._update_pattern_del_enabled()

    def _on_pattern_switched(self, name: str):
        """パターン選択変更時。"""
        if name and name != self._current_pattern:
            self._current_pattern = name
            self.pattern_switched.emit(name)

    def revert_pattern_to(self, name: str):
        """パターンコンボを指定名に戻す（シグナルなし）。

        i340: 項目名編集中にパターン切替が来た場合に呼ばれる。
        """
        self._pattern_combo.blockSignals(True)
        self._pattern_combo.setCurrentText(name)
        self._current_pattern = name
        self._pattern_combo.blockSignals(False)

    def set_pattern_switching_enabled(self, enabled: bool):
        """パターン切替 UI の有効/無効を切り替える。

        i341: 項目名編集中は False にしてコンボボックスを操作不能にする。
        編集確定またはキャンセル後に True で復元する。
        """
        if not hasattr(self, '_pattern_combo'):
            return
        self._pattern_combo.setEnabled(enabled)
        if not enabled:
            # 既に popup が開いていたら閉じる
            try:
                self._pattern_combo.hidePopup()
            except Exception:
                pass

    def _on_pattern_add(self):
        """パターン追加ボタン押下。"""
        # 既存名と被らない名前を自動生成
        base = "パターン"
        idx = 1
        while True:
            name = f"{base}{idx}"
            if name not in self._pattern_names:
                break
            idx += 1
        self._pattern_names.append(name)
        self._pattern_combo.blockSignals(True)
        self._pattern_combo.addItem(name)
        self._pattern_combo.setCurrentText(name)
        self._pattern_combo.blockSignals(False)
        self._current_pattern = name
        self._update_pattern_del_enabled()
        self.pattern_added.emit(name)

    def _on_pattern_delete(self):
        """パターン削除ボタン押下。confirm_reset=ON なら確認ダイアログ。"""
        if len(self._pattern_names) <= 1:
            return
        if self._settings.confirm_reset:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "確認",
                f"パターン「{self._current_pattern}」を削除しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        name = self._current_pattern
        self._pattern_names.remove(name)
        self._pattern_combo.blockSignals(True)
        idx = self._pattern_combo.findText(name)
        if idx >= 0:
            self._pattern_combo.removeItem(idx)
        self._pattern_combo.blockSignals(False)
        # 新しい current を先頭に
        self._current_pattern = self._pattern_combo.currentText()
        self._update_pattern_del_enabled()
        self.pattern_deleted.emit(name)

    def _update_pattern_del_enabled(self):
        """パターンが1件のみなら削除ボタンを無効化。"""
        self._pattern_del_btn.setEnabled(len(self._pattern_names) > 1)

    def _on_pattern_rename_btn(self):
        """パターン名変更: 専用ダイアログ (QDialog + QLineEdit) を開く。"""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QMessageBox,
        )
        from PySide6.QtCore import Qt as _Qt
        old_name = self._current_pattern

        # --- ダイアログ構築 ---
        dlg = QDialog(self)
        dlg.setWindowTitle("パターン名の変更")
        dlg.setWindowFlags(
            dlg.windowFlags() & ~_Qt.WindowType.WindowContextHelpButtonHint
        )
        dlg.setMinimumWidth(280)

        vlay = QVBoxLayout(dlg)
        vlay.setSpacing(8)
        vlay.addWidget(QLabel(f"現在の名前: {old_name}"))

        edit = QLineEdit(old_name)
        edit.selectAll()
        vlay.addWidget(edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        cancel_btn = QPushButton("キャンセル")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        vlay.addLayout(btn_row)

        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)

        edit.returnPressed.connect(dlg.accept)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = edit.text().strip()
        if not new_name or new_name == old_name:
            return
        if new_name in self._pattern_names:
            QMessageBox.warning(
                self, "エラー", f"パターン名 '{new_name}' は既に使用されています。"
            )
            return

        # UI を先に更新してからシグナルを発火
        idx = self._pattern_combo.findText(old_name)
        if idx >= 0:
            self._pattern_combo.blockSignals(True)
            self._pattern_combo.setItemText(idx, new_name)
            self._pattern_combo.setCurrentText(new_name)
            self._pattern_combo.blockSignals(False)
        self._pattern_names[self._pattern_names.index(old_name)] = new_name
        self._current_pattern = new_name
        self.pattern_renamed.emit(old_name, new_name)

    def set_spin_section_visible(self, visible: bool):
        """スピンセクション（操作ボックス相当）の表示/非表示を切り替える。"""
        self._spin_section.setVisible(visible)

    def set_pattern_list(self, names: list[str], current: str):
        """外部からパターン一覧と選択を更新する。"""
        self._pattern_names = list(names)
        self._current_pattern = current
        self._pattern_combo.blockSignals(True)
        self._pattern_combo.clear()
        for name in names:
            self._pattern_combo.addItem(name)
        self._pattern_combo.setCurrentText(current)
        self._pattern_combo.blockSignals(False)
        self._update_pattern_del_enabled()


    @staticmethod
    def _apply_scroll_style(scroll: QScrollArea, design: DesignSettings):
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {design.panel}; }}"
            f"QScrollBar:vertical {{ width: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:vertical {{ background: {design.separator}; border-radius: 3px; }}"
            f"QScrollBar:horizontal {{ height: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:horizontal {{ background: {design.separator}; border-radius: 3px; }}"
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
    def _dark_checkbox_style(design: DesignSettings) -> str:
        return dark_checkbox_style(design)

    @staticmethod
    def _dark_spinbox_style(design: DesignSettings) -> str:
        return dark_spinbox_style(design)

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

