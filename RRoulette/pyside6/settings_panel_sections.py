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

from panel_widgets import (
    _SectionHeader, CollapsibleSection, _PlaceholderSection,
    NoWheelSlider, NoWheelSpinBox, NoWheelDoubleSpinBox, NoWheelComboBox,
)

from app_constants import (
    SIDEBAR_W, SIZE_PROFILES,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
)
from design_models import DesignSettings
from app_settings import AppSettings
from item_entry import ItemEntry
from spin_preset import PRESET_DURATIONS_MS, PRESET_PROFILES_LIST, get_preset_phase_times, get_effective_phase_times
from spin_effect_settings import (
    EFFECT_KEYS, EFFECT_DISPLAY_NAMES, SpinEffectSettings,
    default_spin_effect_settings, EffectConfig,
)
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

    def _attach_section_reset(self, section: "CollapsibleSection",
                               section_name: str, design: DesignSettings,
                               tooltip: str = ""):
        """折り畳みセクションのヘッダー右側に「初期化」ボタンを追加する。

        ボタン押下で section_reset_requested(section_name) を発火する。
        """
        btn = QPushButton("初期化")
        btn.setFont(QFont("Meiryo", 7))
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text_sub};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 6px; font-family: Meiryo; font-size: 7pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: #c0392b; color: white; border-color: #c0392b;"
            f"}}"
        )
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            btn.setToolTip(tooltip)
        else:
            btn.setToolTip(f"{section_name} を初期値に戻す")
        btn.clicked.connect(
            lambda _chk=False, n=section_name: self.section_reset_requested.emit(n)
        )
        section.add_header_widget(btn)

    def _build_quick_settings_bar(self, outer_layout: QVBoxLayout,
                                   settings: AppSettings,
                                   design: DesignSettings):
        """常設のクイック設定行を組み立てる。

        v0.4.4 cfg_panel の「ウィンドウ表示」グループに相当。
        透過 (ウィンドウ / ルーレット個別) と常に最前面を、折りたたみ
        セクションの外に常設で配置する。
        """
        bar = QFrame(self)  # i068: 親なし HWND フラッシュ防止
        bar.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {design.panel};"
            f"  border-bottom: 1px solid {design.separator};"
            f"}}"
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(10)

        # v0.6.1: ウィンドウ透過 / ルーレット透過 / パネル透過 / 最前面 は
        # 管理パネルへ移動済み。

        # v0.6.1: 「全ルーレットに適用」CB（管理パネルから移動）
        self._apply_all_cb = QCheckBox("全ルーレットに適用")
        self._apply_all_cb.setFont(QFont("Meiryo", 8))
        self._apply_all_cb.setStyleSheet(f"color: {design.text};")
        self._apply_all_cb.setChecked(False)
        self._apply_all_cb.setToolTip(
            "ON: 設定パネルの変更を全ルーレットに一括適用\n"
            "OFF: 選択中ルーレットのみに適用"
        )
        self._apply_all_cb.toggled.connect(self.apply_to_all_changed.emit)
        bar_layout.addWidget(self._apply_all_cb)

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

        # v0.6.1: 全体初期化ボタン（クイック設定バー最右）
        self._all_reset_btn = QPushButton("全体初期化")
        self._all_reset_btn.setFont(QFont("Meiryo", 8))
        self._all_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._all_reset_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.accent}; border-radius: 3px;"
            f"  padding: 2px 8px; font-size: 8pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; "
            f"  border-color: #c0392b; }}"
        )
        self._all_reset_btn.setToolTip(
            "このルーレットの全設定を新規ルーレット作成時の状態に戻す。\n"
            "「全ルーレットに適用」ON 時は全ルーレット対象。"
        )
        self._all_reset_btn.clicked.connect(
            lambda: self.section_reset_requested.emit("all")
        )
        bar_layout.addWidget(self._all_reset_btn)

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
        self._spin_collapsible = CollapsibleSection("スピン", design, expanded=True, theme_mode=settings.theme_mode)
        self._spin_section = self._spin_collapsible
        spin_layout = self._spin_collapsible.content_layout

        lbl_style = f"color: {design.text_sub};"
        profile_btn_base = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px; font-family: Meiryo; font-size: 8pt;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background-color: {design.accent}; color: white;"
            f"  border: 1px solid {design.accent};"
            f"}}"
        )
        dur_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 3px; font-family: Meiryo; font-size: 7pt;"
            f"}}"
        )

        # ── プロファイル選択 (z=バランス型 / y=緩急強調 / x=AIお勧め) ──
        profile_lbl = QLabel("プロファイル:")
        profile_lbl.setFont(QFont("Meiryo", 8))
        profile_lbl.setStyleSheet(lbl_style)
        spin_layout.addWidget(profile_lbl)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(3)
        self._profile_btns: dict[str, QPushButton] = {}
        _profile_labels = [('z', 'バランス型'), ('y', '緩急強調'), ('x', 'AIお勧め')]
        for key, label in _profile_labels:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(profile_btn_base)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._on_profile_btn_clicked(k))
            profile_row.addWidget(btn, stretch=1)
            self._profile_btns[key] = btn
        cur_profile = getattr(settings, "spin_preset_profile", 'z')
        self._profile_btns.get(cur_profile, self._profile_btns['z']).setChecked(True)
        spin_layout.addLayout(profile_row)

        # プロファイルランダム抽選
        self._profile_random_cb = QCheckBox("毎スピンでプロファイルをランダム抽選")
        self._profile_random_cb.setFont(QFont("Meiryo", 8))
        self._profile_random_cb.setStyleSheet(dark_checkbox_style(design))
        self._profile_random_cb.setChecked(getattr(settings, "spin_preset_random", False))
        self._profile_random_cb.toggled.connect(
            lambda v: self.setting_changed.emit("spin_preset_random", v)
        )
        spin_layout.addWidget(self._profile_random_cb)

        # ── スピン時間スライダー (1.0〜15.0 秒) ─────────────────────
        dur_val_sec = float(getattr(settings, "spin_duration", 5.0))
        dur_slider_val = max(10, min(150, int(round(dur_val_sec * 10))))
        self._dur_lbl = QLabel(f"スピン時間: {dur_slider_val / 10:.1f} 秒")
        self._dur_lbl.setFont(QFont("Meiryo", 8))
        self._dur_lbl.setStyleSheet(lbl_style)
        spin_layout.addWidget(self._dur_lbl)

        self._dur_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self._dur_slider.setRange(10, 150)   # value / 10 = 秒 (1.0〜15.0)
        self._dur_slider.setSingleStep(1)
        self._dur_slider.setValue(dur_slider_val)
        self._dur_slider.valueChanged.connect(self._on_dur_slider_changed)
        spin_layout.addWidget(self._dur_slider)

        # プリセット秒数クイックボタン [1秒][3秒][5秒][7秒][9秒][12秒]
        # PWA 同等: スライダー値が一致するボタンをアクティブ表示する
        dur_preset_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 3px; font-family: Meiryo; font-size: 7pt;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background-color: {design.accent}; color: white;"
            f"  border: 1px solid {design.accent};"
            f"}}"
        )
        dur_btn_row = QHBoxLayout()
        dur_btn_row.setSpacing(2)
        self._dur_preset_btns: list[tuple[int, QPushButton]] = []
        for ms in PRESET_DURATIONS_MS:
            sec = ms // 1000
            btn = QPushButton(f"{sec}秒")
            btn.setCheckable(True)
            btn.setAutoExclusive(False)
            btn.setStyleSheet(dur_preset_btn_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, s=float(sec): self._on_dur_preset_clicked(s))
            dur_btn_row.addWidget(btn, stretch=1)
            self._dur_preset_btns.append((ms, btn))
        spin_layout.addLayout(dur_btn_row)
        # 初期同期（スライダー値とプリセットの一致を反映）
        self._sync_dur_preset_btns(int(round(dur_val_sec * 1000)))

        # 秒数ランダム抽選
        self._dur_random_cb = QCheckBox("毎スピンで秒数をランダム抽選 (1/3/5/7/9/12秒)")
        self._dur_random_cb.setFont(QFont("Meiryo", 8))
        self._dur_random_cb.setStyleSheet(dark_checkbox_style(design))
        self._dur_random_cb.setChecked(getattr(settings, "spin_duration_random", False))
        self._dur_random_cb.toggled.connect(
            lambda v: self.setting_changed.emit("spin_duration_random", v)
        )
        spin_layout.addWidget(self._dur_random_cb)

        # ── 終了時間ランダム化スライダー ──────────────────────────────
        dur_rand_ratio = float(getattr(settings, "spin_duration_random_ratio", 0.0))
        dur_rand_pct = max(0, min(50, int(round(dur_rand_ratio * 100))))
        self._dur_rand_lbl = QLabel(f"終了時間ランダム化: ±{dur_rand_pct}%")
        self._dur_rand_lbl.setFont(QFont("Meiryo", 8))
        self._dur_rand_lbl.setStyleSheet(lbl_style)
        spin_layout.addWidget(self._dur_rand_lbl)

        self._dur_rand_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self._dur_rand_slider.setRange(0, 50)
        self._dur_rand_slider.setValue(dur_rand_pct)
        self._dur_rand_slider.valueChanged.connect(self._on_dur_rand_slider_changed)
        spin_layout.addWidget(self._dur_rand_slider)

        # ── スピン詳細ランダム化スライダー ────────────────────────────
        phase_rand = float(getattr(settings, "spin_phase_randomize", 0.0))
        phase_rand_pct = max(0, min(100, int(round(phase_rand * 100))))
        self._phase_rand_lbl = QLabel(f"スピン詳細ランダム化: {phase_rand_pct}%")
        self._phase_rand_lbl.setFont(QFont("Meiryo", 8))
        self._phase_rand_lbl.setStyleSheet(lbl_style)
        spin_layout.addWidget(self._phase_rand_lbl)

        self._phase_rand_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self._phase_rand_slider.setRange(0, 100)
        self._phase_rand_slider.setValue(phase_rand_pct)
        self._phase_rand_slider.valueChanged.connect(self._on_phase_rand_slider_changed)
        spin_layout.addWidget(self._phase_rand_slider)

        # ── スピン詳細（4段階個別調整）───────────────────────────────
        self._build_spin_detail_subsection(settings, design, spin_layout)

        self._layout.addWidget(self._spin_collapsible)
        # v0.6.1: ヘッダー右に「初期化」ボタン
        self._attach_section_reset(self._spin_collapsible, "spin", design)

    def _on_profile_btn_clicked(self, profile: str):
        """プロファイルボタンが押されたとき、排他選択にして設定を emit する。"""
        for key, btn in self._profile_btns.items():
            btn.setChecked(key == profile)
        # スピン詳細のデフォルト値を再計算（未上書き項目のスライダー値を更新）
        self._recompute_spin_detail_defaults(profile_override=profile)
        self.setting_changed.emit("spin_preset_profile", profile)

    def _on_dur_slider_changed(self, value: int):
        """スピン時間スライダー変更。"""
        sec = value / 10.0
        self._dur_lbl.setText(f"スピン時間: {sec:.1f} 秒")
        # プリセットボタンのアクティブ状態を同期
        self._sync_dur_preset_btns(int(round(sec * 1000)))
        # スピン詳細のデフォルト値を再計算（未上書き項目のスライダー値を更新）
        self._recompute_spin_detail_defaults()
        self.setting_changed.emit("spin_duration", sec)

    def _on_dur_preset_clicked(self, sec: float):
        """クイック秒数ボタン押下: スピン時間スライダーを更新（valueChanged 経由で emit）。"""
        slider_val = max(10, min(150, int(round(sec * 10))))
        self._dur_slider.setValue(slider_val)

    def _sync_dur_preset_btns(self, current_ms: int):
        """スライダー現在値（ms）に一致するプリセットボタンのみ checked にする。"""
        if not hasattr(self, "_dur_preset_btns"):
            return
        for preset_ms, btn in self._dur_preset_btns:
            btn.blockSignals(True)
            btn.setChecked(preset_ms == current_ms)
            btn.blockSignals(False)

    def _on_dur_rand_slider_changed(self, value: int):
        """終了時間ランダム化スライダー変更。"""
        ratio = value / 100.0  # 0-50 → 0.0-0.5
        self._dur_rand_lbl.setText(f"終了時間ランダム化: ±{value}%")
        self.setting_changed.emit("spin_duration_random_ratio", ratio)

    def _on_phase_rand_slider_changed(self, value: int):
        """スピン詳細ランダム化スライダー変更。"""
        intensity = value / 100.0  # 0-100 → 0.0-1.0
        self._phase_rand_lbl.setText(f"スピン詳細ランダム化: {value}%")
        self.setting_changed.emit("spin_phase_randomize", intensity)

    # ================================================================
    #  スピン詳細（4段階個別調整）サブセクション
    # ================================================================

    def _build_spin_detail_subsection(self, settings: AppSettings,
                                       design: DesignSettings,
                                       parent_layout) -> None:
        """スピン詳細（4段階個別調整）折りたたみサブセクションを構築する。"""
        self._spin_detail_collapsible = CollapsibleSection(
            "スピン詳細（4段階個別調整）", design, expanded=False,
            theme_mode=settings.theme_mode, nested=True,
        )
        sec = self._spin_detail_collapsible.content_layout
        parent_layout.addWidget(self._spin_detail_collapsible)

        lbl_style = f"color: {design.text_sub};"
        curve_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 3px; font-family: Meiryo; font-size: 7pt;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background-color: {design.accent}; color: white;"
            f"  border: 1px solid {design.accent};"
            f"}}"
        )
        x_btn_style = (
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text_sub};"
            f"  border: none; padding: 0px 2px; font-size: 9pt;"
            f"}}"
            f"QPushButton:hover {{ color: #c0392b; }}"
        )
        action_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 3px 8px;"
            f"  font-family: Meiryo; font-size: 8pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
            f"QPushButton:disabled {{ color: {design.text_sub}; }}"
        )

        # デフォルトフェーズタイムを取得（初期スライダー値に使用）
        dur_ms = max(1000, int(round(float(getattr(settings, "spin_duration", 5.0)) * 1000)))
        profile = getattr(settings, "spin_preset_profile", 'z')
        try:
            pt = get_preset_phase_times(dur_ms, profile)
            _def = {
                "push_end_ms":  int(pt.push_end_ms),
                "cruise_end_ms": int(pt.cruise_end_ms),
                "decel_end_ms": int(pt.decel_end_ms),
                "push_end_rps":  pt.v1,
                "cruise_end_rps": pt.v2,
                "decel_end_rps": pt.v3,
                "push_curve":    pt.push_curve,
                "cruise_curve":  pt.cruise_curve,
                "decel_curve":   pt.decel_curve,
                "landing_curve": pt.landing_curve,
            }
        except Exception:
            _def = {
                "push_end_ms": 1000, "cruise_end_ms": 3000, "decel_end_ms": 4500,
                "push_end_rps": 12.0, "cruise_end_rps": 15.0, "decel_end_rps": 3.0,
                "push_curve": "easeOut", "cruise_curve": "linear",
                "decel_curve": "easeIn", "landing_curve": "easeInOut",
            }

        curve_opts = [("linear", "一定"), ("easeOut", "減速"), ("easeIn", "加速"), ("easeInOut", "S字")]
        curve_keys = [k for k, _ in curve_opts]

        phases_def = [
            ("push",    "① 加速", True),
            ("cruise",  "② 巡航", True),
            ("decel",   "③ 減速", True),
            ("landing", "④ 着地", False),
        ]

        self._phase_widgets: dict[str, dict] = {}
        self._spin_detail_dirty = False
        # PWA: local.spinPhaseOverrides 相当（dict、明示的に上書きされたフィールドのみ持つ）
        _init_ovr = getattr(settings, "spin_phase_overrides", None)
        self._local_overrides: dict = dict(_init_ovr) if isinstance(_init_ovr, dict) else {}
        self._spin_detail_saved_overrides: dict = dict(self._local_overrides)

        for phase_key, phase_label, has_end in phases_def:
            hdr = QLabel(phase_label)
            hdr.setFont(QFont("Meiryo", 8, QFont.Weight.Bold))
            hdr.setStyleSheet(f"color: {design.text}; margin-top: 4px;")
            sec.addWidget(hdr)

            pw: dict = {}

            if has_end:
                def_end_ms  = _def[f"{phase_key}_end_ms"]
                def_end_rps = _def[f"{phase_key}_end_rps"]

                # 終了時刻スライダー
                end_ms_row = QHBoxLayout()
                end_ms_row.setSpacing(4)
                end_ms_lbl = QLabel(f"終了時刻: {def_end_ms / 1000:.2f} 秒")
                end_ms_lbl.setFont(QFont("Meiryo", 7))
                end_ms_lbl.setStyleSheet(lbl_style)
                end_ms_row.addWidget(end_ms_lbl, stretch=1)
                end_ms_reset = QPushButton("×")
                end_ms_reset.setFont(QFont("Meiryo", 8))
                end_ms_reset.setFixedSize(20, 18)
                end_ms_reset.setStyleSheet(x_btn_style)
                end_ms_reset.setCursor(Qt.CursorShape.PointingHandCursor)
                end_ms_reset.setToolTip("初期値に戻す")
                end_ms_row.addWidget(end_ms_reset)
                sec.addLayout(end_ms_row)

                end_ms_slider = NoWheelSlider(Qt.Orientation.Horizontal)
                end_ms_slider.setRange(30, 14970)
                end_ms_slider.setSingleStep(10)
                end_ms_slider.setValue(max(30, min(14970, def_end_ms)))
                sec.addWidget(end_ms_slider)

                # 終了速度スライダー
                end_rps_row = QHBoxLayout()
                end_rps_row.setSpacing(4)
                end_rps_lbl = QLabel(f"終了速度: {def_end_rps:.1f} RPS")
                end_rps_lbl.setFont(QFont("Meiryo", 7))
                end_rps_lbl.setStyleSheet(lbl_style)
                end_rps_row.addWidget(end_rps_lbl, stretch=1)
                end_rps_reset = QPushButton("×")
                end_rps_reset.setFont(QFont("Meiryo", 8))
                end_rps_reset.setFixedSize(20, 18)
                end_rps_reset.setStyleSheet(x_btn_style)
                end_rps_reset.setCursor(Qt.CursorShape.PointingHandCursor)
                end_rps_reset.setToolTip("初期値に戻す")
                end_rps_row.addWidget(end_rps_reset)
                sec.addLayout(end_rps_row)

                end_rps_slider = NoWheelSlider(Qt.Orientation.Horizontal)
                end_rps_slider.setRange(0, 250)   # value / 10 = RPS
                end_rps_slider.setSingleStep(1)
                end_rps_slider.setValue(max(0, min(250, int(round(def_end_rps * 10)))))
                sec.addWidget(end_rps_slider)

                pw.update({
                    "end_ms_lbl":    end_ms_lbl,
                    "end_ms_slider": end_ms_slider,
                    "end_ms_reset":  end_ms_reset,
                    "def_end_ms":    def_end_ms,
                    "end_rps_lbl":   end_rps_lbl,
                    "end_rps_slider": end_rps_slider,
                    "end_rps_reset": end_rps_reset,
                    "def_end_rps":   def_end_rps,
                })

            # 曲線選択ボタン
            curve_row = QHBoxLayout()
            curve_row.setSpacing(2)
            curve_lbl_w = QLabel("曲線:")
            curve_lbl_w.setFont(QFont("Meiryo", 7))
            curve_lbl_w.setStyleSheet(lbl_style)
            curve_row.addWidget(curve_lbl_w)
            curve_btns: list[QPushButton] = []
            for c_key, c_label in curve_opts:
                cb_btn = QPushButton(c_label)
                cb_btn.setCheckable(True)
                cb_btn.setStyleSheet(curve_btn_style)
                cb_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                cb_btn.clicked.connect(
                    lambda _chk=False, pk=phase_key, ck=c_key:
                    self._on_spin_detail_curve_clicked(pk, ck)
                )
                curve_row.addWidget(cb_btn, stretch=1)
                curve_btns.append(cb_btn)
            def_curve = _def[f"{phase_key}_curve"]
            cur_curve_idx = curve_keys.index(def_curve) if def_curve in curve_keys else 0
            curve_btns[cur_curve_idx].setChecked(True)
            curve_reset = QPushButton("×")
            curve_reset.setFont(QFont("Meiryo", 8))
            curve_reset.setFixedSize(20, 18)
            curve_reset.setStyleSheet(x_btn_style)
            curve_reset.setCursor(Qt.CursorShape.PointingHandCursor)
            curve_reset.setToolTip("初期値に戻す")
            curve_row.addWidget(curve_reset)
            sec.addLayout(curve_row)

            pw.update({
                "curve_btns":  curve_btns,
                "curve_keys":  curve_keys,
                "def_curve":   def_curve,
                "curve_reset": curve_reset,
            })
            self._phase_widgets[phase_key] = pw

        # アクションボタン行
        action_row = QHBoxLayout()
        action_row.setSpacing(4)

        self._detail_save_btn = QPushButton("保存")
        self._detail_save_btn.setFont(QFont("Meiryo", 8))
        self._detail_save_btn.setEnabled(False)
        self._detail_save_btn.setStyleSheet(action_btn_style)
        self._detail_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_save_btn.clicked.connect(self._on_spin_detail_save)
        action_row.addWidget(self._detail_save_btn)

        self._detail_cancel_btn = QPushButton("キャンセル")
        self._detail_cancel_btn.setFont(QFont("Meiryo", 8))
        self._detail_cancel_btn.setEnabled(False)
        self._detail_cancel_btn.setStyleSheet(action_btn_style)
        self._detail_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_cancel_btn.clicked.connect(self._on_spin_detail_cancel)
        action_row.addWidget(self._detail_cancel_btn)

        self._detail_reset_btn = QPushButton("初期化")
        self._detail_reset_btn.setFont(QFont("Meiryo", 8))
        self._detail_reset_btn.setStyleSheet(action_btn_style)
        self._detail_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_reset_btn.setToolTip("フェーズ詳細をデフォルト値に戻す")
        self._detail_reset_btn.clicked.connect(self._on_spin_detail_reset)
        action_row.addWidget(self._detail_reset_btn)
        sec.addLayout(action_row)

        # シグナル接続（PWA reactive 構造）
        for pk, pw in self._phase_widgets.items():
            if "end_ms_slider" in pw:
                pw["end_ms_slider"].valueChanged.connect(
                    lambda v, _pk=pk: self._on_detail_ms_slider_changed(_pk, v)
                )
                pw["end_rps_slider"].valueChanged.connect(
                    lambda v, _pk=pk: self._on_detail_rps_slider_changed(_pk, v)
                )
                pw["end_ms_reset"].clicked.connect(
                    lambda _chk=False, _pk=pk: self._on_detail_reset_phase_ms(_pk)
                )
                pw["end_rps_reset"].clicked.connect(
                    lambda _chk=False, _pk=pk: self._on_detail_reset_phase_rps(_pk)
                )
            pw["curve_reset"].clicked.connect(
                lambda _chk=False, _pk=pk: self._on_detail_reset_phase_curve(_pk)
            )

        # 初期表示: 全 phase の effTimes を計算してスライダー値・range を設定
        self._refresh_spin_detail_ui()

    # ── PWA 互換: local.spinPhaseOverrides を更新して全 phase 再計算 ──

    def _on_detail_ms_slider_changed(self, phase_key: str, value: int):
        # PWA: setNumericOverride('pushEndMs', val) → effTimes 再計算
        self._local_overrides[f"{phase_key}_end_ms"] = float(value)
        self._refresh_spin_detail_ui()
        self._mark_spin_detail_dirty()

    def _on_detail_rps_slider_changed(self, phase_key: str, value: int):
        self._local_overrides[f"{phase_key}_end_rps"] = value / 10.0
        self._refresh_spin_detail_ui()
        self._mark_spin_detail_dirty()

    def _on_spin_detail_curve_clicked(self, phase_key: str, curve_key: str):
        self._local_overrides[f"{phase_key}_curve"] = curve_key
        self._refresh_spin_detail_ui()
        self._mark_spin_detail_dirty()

    def _on_detail_reset_phase_ms(self, phase_key: str):
        # PWA: clearOverride('pushEndMs') → そのフィールドだけ override から削除
        self._local_overrides.pop(f"{phase_key}_end_ms", None)
        self._refresh_spin_detail_ui()
        self._mark_spin_detail_dirty()

    def _on_detail_reset_phase_rps(self, phase_key: str):
        self._local_overrides.pop(f"{phase_key}_end_rps", None)
        self._refresh_spin_detail_ui()
        self._mark_spin_detail_dirty()

    def _on_detail_reset_phase_curve(self, phase_key: str):
        self._local_overrides.pop(f"{phase_key}_curve", None)
        self._refresh_spin_detail_ui()
        self._mark_spin_detail_dirty()

    def _mark_spin_detail_dirty(self):
        if not getattr(self, "_spin_detail_dirty", False):
            self._spin_detail_dirty = True
            self._detail_save_btn.setEnabled(True)
            self._detail_cancel_btn.setEnabled(True)

    def _refresh_spin_detail_ui(self):
        """PWA: effTimes = $derived(getEffectivePhaseTimes(...)) 相当。

        現在のスピン時間 + プロファイル + _local_overrides から実効フェーズ値を計算し、
        全スライダー value, range, 曲線ボタンの checked 状態を更新する。
        cruise の min は push 終了+0.05秒、decel の min は cruise 終了+0.05秒、
        など PWA と同じ依存関係でスライダー range も再設定する。
        """
        if not hasattr(self, "_phase_widgets") or not self._phase_widgets:
            return
        try:
            dur_ms = max(1000, int(round(self._dur_slider.value() * 100)))
        except Exception:
            return
        profile = 'z'
        for k, b in getattr(self, "_profile_btns", {}).items():
            if b.isChecked():
                profile = k
                break
        ovr = self._local_overrides if self._local_overrides else None
        try:
            pt = get_effective_phase_times(dur_ms, ovr, profile)
        except Exception:
            return

        total_ms = pt.total_ms
        push_end_ms = pt.push_end_ms
        cruise_end_ms = pt.cruise_end_ms
        decel_end_ms = pt.decel_end_ms

        # phase ごとの (実効値ms, 実効RPS, 曲線, msスライダーmin, msスライダーmax)
        # min/max は PWA と同じ依存式で動的決定
        phases_data = {
            "push": (
                int(round(push_end_ms)), pt.v1, pt.push_curve,
                50, max(51, int(round(total_ms - 150))),
            ),
            "cruise": (
                int(round(cruise_end_ms)), pt.v2, pt.cruise_curve,
                max(51, int(round(push_end_ms + 50))),
                max(52, int(round(total_ms - 100))),
            ),
            "decel": (
                int(round(decel_end_ms)), pt.v3, pt.decel_curve,
                max(52, int(round(cruise_end_ms + 50))),
                max(53, int(round(total_ms - 50))),
            ),
            "landing": (0, 0.0, pt.landing_curve, 0, 0),
        }

        for phase_key, pw in self._phase_widgets.items():
            eff_ms, eff_rps, eff_curve, ms_min, ms_max = phases_data.get(
                phase_key, (0, 0.0, "linear", 0, 0)
            )
            if "end_ms_slider" in pw:
                # range を依存関係で更新
                ms_min = max(30, min(14970, ms_min))
                ms_max = max(ms_min + 1, min(14970, ms_max))
                ms_val = max(ms_min, min(ms_max, int(round(eff_ms))))
                pw["end_ms_slider"].blockSignals(True)
                pw["end_ms_slider"].setRange(ms_min, ms_max)
                pw["end_ms_slider"].setValue(ms_val)
                pw["end_ms_lbl"].setText(f"終了時刻: {ms_val / 1000:.2f} 秒")
                pw["end_ms_slider"].blockSignals(False)

                rps_val = max(0, min(250, int(round(eff_rps * 10))))
                pw["end_rps_slider"].blockSignals(True)
                pw["end_rps_slider"].setValue(rps_val)
                pw["end_rps_lbl"].setText(f"終了速度: {rps_val / 10:.1f} RPS")
                pw["end_rps_slider"].blockSignals(False)

            curve_keys = pw.get("curve_keys", [])
            for i, btn in enumerate(pw.get("curve_btns", [])):
                btn.blockSignals(True)
                btn.setChecked(curve_keys[i] == eff_curve)
                btn.blockSignals(False)

    # 後方互換: 旧シグネチャ呼び出しを reactive 版に転送
    def _recompute_spin_detail_defaults(self, profile_override: str | None = None):
        self._refresh_spin_detail_ui()

    def _on_spin_detail_save(self):
        # PWA: saveDetailNow()
        overrides = dict(self._local_overrides) if self._local_overrides else None
        self._spin_detail_saved_overrides = (
            dict(self._local_overrides) if self._local_overrides else {}
        )
        self._spin_detail_dirty = False
        self._detail_save_btn.setEnabled(False)
        self._detail_cancel_btn.setEnabled(False)
        self.setting_changed.emit("spin_phase_overrides", overrides)

    def _on_spin_detail_cancel(self):
        # PWA: cancelDetail() — snapshot に戻す
        self._local_overrides = (
            dict(self._spin_detail_saved_overrides)
            if self._spin_detail_saved_overrides else {}
        )
        self._refresh_spin_detail_ui()
        self._spin_detail_dirty = False
        self._detail_save_btn.setEnabled(False)
        self._detail_cancel_btn.setEnabled(False)

    def _on_spin_detail_reset(self):
        # PWA: resetDetailToPreset() — overrides を空に
        self._local_overrides = {}
        self._spin_detail_saved_overrides = {}
        self._refresh_spin_detail_ui()
        self._spin_detail_dirty = False
        self._detail_save_btn.setEnabled(False)
        self._detail_cancel_btn.setEnabled(False)
        self.setting_changed.emit("spin_phase_overrides", None)

    def _update_spin_detail_ui(self, overrides: dict | None):
        """外部からの設定変更（update_setting）を UI に反映する。"""
        if not hasattr(self, "_phase_widgets"):
            return
        self._local_overrides = dict(overrides) if isinstance(overrides, dict) else {}
        self._spin_detail_saved_overrides = dict(self._local_overrides)
        self._spin_detail_dirty = False
        if hasattr(self, "_detail_save_btn"):
            self._detail_save_btn.setEnabled(False)
            self._detail_cancel_btn.setEnabled(False)
        self._refresh_spin_detail_ui()

    # ================================================================
    #  セクション 2: 表示設定（実装済み）
    # ================================================================

    def _build_display_section(self, settings: AppSettings,
                               design: DesignSettings):
        self._display_section = CollapsibleSection("表示", design, expanded=True, theme_mode=settings.theme_mode)
        sec = self._display_section.content_layout
        self._layout.addWidget(self._display_section)
        # v0.6.1: ヘッダー右に「初期化」ボタン
        self._attach_section_reset(self._display_section, "display", design)

        # v0.6.1: テーマは管理パネルへ移動済み

        # テキスト表示モード
        text_row = QHBoxLayout()
        text_row.setSpacing(4)
        text_lbl = QLabel("テキスト:")
        text_lbl.setFont(QFont("Meiryo", 8))
        text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._text_lbl = text_lbl
        text_row.addWidget(text_lbl)

        self._text_mode_combo = NoWheelComboBox()
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

        # v0.6.1: インスタンス番号表示は管理パネルへ移動済み

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

        self._prof_combo = NoWheelComboBox()
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

        self._tdir_combo = NoWheelComboBox()
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

        self._sdir_combo = NoWheelComboBox()
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

        self._ptr_combo = NoWheelComboBox()
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
        # v0.6.1: 項目削除時確認は管理パネルへ移動済み

        # i289: 配置方向（項目パネルから移動）
        arr_row = QHBoxLayout()
        arr_row.setSpacing(4)
        arr_lbl = QLabel("配置方向:")
        arr_lbl.setFont(QFont("Meiryo", 8))
        arr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._arr_lbl = arr_lbl
        arr_row.addWidget(arr_lbl)
        self._arr_combo = NoWheelComboBox()
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
        """デザインセクション（折り畳み式に戻す。初期化ボタンは設置しない）。"""
        self._design_collapsible = CollapsibleSection(
            "デザイン", design, expanded=False, theme_mode=settings.theme_mode
        )
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
        self._attach_section_reset(self._result_collapsible, "result", design)

        # 閉じ方モード
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_lbl = QLabel("閉じ方:")
        mode_lbl.setFont(QFont("Meiryo", 8))
        mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_mode_lbl = mode_lbl
        mode_row.addWidget(mode_lbl)

        self._result_mode_combo = NoWheelComboBox()
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

        self._result_sec_spin = NoWheelDoubleSpinBox()
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

        self._macro_sec_spin = NoWheelDoubleSpinBox()
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
        self._attach_section_reset(self._sound_collapsible, "sound", design)

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

        # v0.6.1: スピン音量・決定音量は管理パネルへ移動済み

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

        self._tick_pat_combo = NoWheelComboBox()
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

        self._win_pat_combo = NoWheelComboBox()
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
        self._attach_section_reset(self._log_collapsible, "log", design)
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
        # v0.6.1: リセット確認は管理パネルへ移動済み

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
        # v0.6.1: リプレイ履歴クリアは管理画面で行うもののため、初期化ボタンは設置しない

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

        # v0.6.1: 保存上限・再生中表示は管理パネルへ移動済み

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

        self._pattern_combo = NoWheelComboBox()
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

    # ================================================================
    #  特殊演出セクション (テスト版) — グループ別レイアウト
    # ================================================================

    _SOUND_EFFECT_KEYS = {"soundConfirm", "soundExpect", "soundNgConfirm"}
    _SOUND_EFFECT_SND_KEY = {
        "soundConfirm": "confirm",
        "soundExpect": "expect",
        "soundNgConfirm": "ng",
    }
    _EFFECT_GROUPS = [
        ("音系",        ["soundConfirm", "soundExpect", "soundNgConfirm"]),
        ("ミニキャラ系", ["miniCharTarget", "miniCharExpect", "miniCharNg"]),
        ("カットイン系", ["cutInTarget", "cutInExpect", "cutInNg"]),
        ("その他",      ["flashConfirm", "wheelGlow", "textChance"]),
    ]

    def _build_effects_section(self, settings: AppSettings, design: DesignSettings):
        """特殊演出設定セクション（PWA SettingsSheet と 1:1 対応）。"""
        self._effects_collapsible = CollapsibleSection(
            "特殊演出（テスト版）", design, expanded=False, theme_mode=settings.theme_mode
        )
        sec = self._effects_collapsible.content_layout
        self._layout.addWidget(self._effects_collapsible)
        self._attach_section_reset(self._effects_collapsible, "effects", design)

        lbl_style = f"color: {design.text_sub};"
        var_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px; font-family: Meiryo; font-size: 8pt; min-width: 24px;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background-color: {design.accent}; color: white;"
            f"  border: 1px solid {design.accent};"
            f"}}"
            f"QPushButton:disabled {{ color: {design.text_sub}; }}"
        )
        preview_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px; font-family: Meiryo; font-size: 8pt; min-width: 24px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; color: white; }}"
        )
        mode_active_style = (
            f"QPushButton {{"
            f"  background-color: {design.accent}; color: white;"
            f"  border: 1px solid {design.accent}; border-radius: 3px;"
            f"  padding: 3px 10px; font-family: Meiryo; font-size: 8pt;"
            f"}}"
        )
        mode_inactive_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 3px 10px; font-family: Meiryo; font-size: 8pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; color: white; }}"
        )
        grp_reset_style = (
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text_sub};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 6px; font-family: Meiryo; font-size: 7pt;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; border-color: #c0392b; }}"
        )

        # 1) 演出マスター ON/OFF + 全てランダム
        master_row = QHBoxLayout()
        self._effects_master_cb = QCheckBox("演出マスター ON/OFF")
        self._effects_master_cb.setFont(QFont("Meiryo", 8))
        self._effects_master_cb.setStyleSheet(f"color: {design.text};")
        self._effects_master_cb.setChecked(False)
        self._effects_master_cb.toggled.connect(self._on_effect_changed)
        master_row.addWidget(self._effects_master_cb)

        self._effects_all_random_cb = QCheckBox("全てランダム")
        self._effects_all_random_cb.setFont(QFont("Meiryo", 8))
        self._effects_all_random_cb.setStyleSheet(f"color: {design.text};")
        self._effects_all_random_cb.setChecked(False)
        self._effects_all_random_cb.setToolTip(
            "ON の演出のバリアントを各項目の設定に関わらず毎回ランダムで選択する"
        )
        self._effects_all_random_cb.toggled.connect(self._on_effect_changed)
        master_row.addWidget(self._effects_all_random_cb)

        master_row.addStretch(1)
        sec.addLayout(master_row)

        # v0.6.1: グループ内の「演出設定を初期値に戻す」は廃止
        # （セクションヘッダー右の「初期化」ボタンと役割が重複するため）
        # 演出音量は管理パネル「アプリ設定」の音量グループへ移動済み

        # 4) モード切替: 演出選択 / 演出確認
        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)
        self._effects_select_btn = QPushButton("演出選択")
        self._effects_select_btn.setFont(QFont("Meiryo", 8))
        self._effects_select_btn.setStyleSheet(mode_active_style)
        self._effects_select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._effects_select_btn.clicked.connect(lambda: self._set_effects_mode("select"))
        mode_row.addWidget(self._effects_select_btn)
        self._effects_confirm_btn = QPushButton("演出確認")
        self._effects_confirm_btn.setFont(QFont("Meiryo", 8))
        self._effects_confirm_btn.setStyleSheet(mode_inactive_style)
        self._effects_confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._effects_confirm_btn.clicked.connect(lambda: self._set_effects_mode("confirm"))
        mode_row.addWidget(self._effects_confirm_btn)
        mode_row.addStretch(1)
        sec.addLayout(mode_row)

        self._effects_mode_hint = QLabel("各演出のバリエーション・確率・タイミングを設定します。")
        self._effects_mode_hint.setFont(QFont("Meiryo", 7))
        self._effects_mode_hint.setStyleSheet(lbl_style)
        self._effects_mode_hint.setWordWrap(True)
        sec.addWidget(self._effects_mode_hint)

        self._effects_mode = "select"
        self._effects_mode_styles = {"active": mode_active_style, "inactive": mode_inactive_style}

        self._effect_rows: dict[str, dict] = {}

        # 5) グループ別に演出行を構築。各グループは折り畳み可能で、
        #    ヘッダー（折り畳みボタン同行）の右側に「初期化」ボタンを配置。
        self._effect_group_sections: dict[str, CollapsibleSection] = {}
        for group_name, group_keys in self._EFFECT_GROUPS:
            grp_section = CollapsibleSection(
                group_name, design, expanded=True,
                theme_mode=settings.theme_mode, nested=True,
            )
            grp_reset_btn = QPushButton("初期化")
            grp_reset_btn.setFont(QFont("Meiryo", 7))
            grp_reset_btn.setStyleSheet(grp_reset_style)
            grp_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            grp_reset_btn.setToolTip(f"{group_name}の演出設定を初期値に戻す")
            grp_reset_btn.clicked.connect(
                lambda _chk=False, gk=group_keys: self._on_effects_group_reset(gk)
            )
            grp_section.add_header_widget(grp_reset_btn)
            grp_layout = grp_section.content_layout
            for key in group_keys:
                self._build_effect_item_widget(grp_layout, key, design,
                                               var_btn_style, preview_btn_style)
            sec.addWidget(grp_section)
            self._effect_group_sections[group_name] = grp_section

    def _build_effect_item_widget(self, sec, key: str, design: DesignSettings,
                                   var_btn_style: str, preview_btn_style: str):
        """演出1項目のウィジェットを構築して sec に追加する（PWA 1:1）。

        演出選択モード:
          - 1行目: [enabled CB] [表示名] [1][2][3][4][5][🎲]
          - 2行目: 確率: [値テキスト] [🎲ランダムトグル]
          - 3行目: [min slider][max slider] (プログレスバー風配置)
          - 4行目: タイミング: [値テキスト] [🎲ランダムトグル]
          - 5行目: [min slider][max slider]
        演出確認モード:
          - 1行目: [表示名] [1][2][3][4][5][🎲]
        """
        lbl_style = f"color: {design.text_sub};"
        rand_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text_sub};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 3px; font-size: 8pt; min-width: 22px;"
            f"}}"
            f"QPushButton:checked {{"
            f"  background-color: {design.accent}; color: white;"
            f"  border: 1px solid {design.accent};"
            f"}}"
        )

        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(4, 2, 4, 4)
        c_layout.setSpacing(2)

        # ── 演出選択モード用 ──────────────────────────────────────
        select_widget = QWidget()
        sel_layout = QVBoxLayout(select_widget)
        sel_layout.setContentsMargins(0, 0, 0, 0)
        sel_layout.setSpacing(2)

        # 1行目: CB + 名前 + バリエーション [1][2][3][4][5][🎲]
        sel_top = QHBoxLayout()
        sel_top.setSpacing(4)
        cb = QCheckBox()
        cb.setChecked(True)
        cb.setStyleSheet(f"color: {design.text};")
        cb.toggled.connect(self._on_effect_changed)
        sel_top.addWidget(cb)
        name_lbl = QLabel(EFFECT_DISPLAY_NAMES.get(key, key))
        name_lbl.setFont(QFont("Meiryo", 7))
        name_lbl.setStyleSheet(f"color: {design.text};")
        sel_top.addWidget(name_lbl, stretch=1)
        var_btns: list[QPushButton] = []
        # PWA 順序: [1][2][3][4][5][🎲] (🎲 は末尾)
        _var_labels = ["1", "2", "3", "4", "5", "🎲"]
        _var_data   = [1,   2,   3,   4,   5,   0]
        for v_lbl, v_dat in zip(_var_labels, _var_data):
            vb = QPushButton(v_lbl)
            vb.setCheckable(True)
            vb.setStyleSheet(var_btn_style)
            vb.setCursor(Qt.CursorShape.PointingHandCursor)
            if v_dat == 0:
                vb.setToolTip("毎スピン 1〜5 からランダム抽選")
            else:
                vb.setToolTip(f"バリエーション {v_dat}")
            vb.clicked.connect(
                lambda _chk=False, k=key, vd=v_dat: self._on_effect_variant_clicked(k, vd)
            )
            sel_top.addWidget(vb)
            var_btns.append(vb)
        var_btns[5].setChecked(True)  # 既定: 🎲 (ランダム)
        sel_layout.addLayout(sel_top)

        # 2行目: 確率: 値テキスト + 🎲トグル
        prob_hdr = QHBoxLayout()
        prob_hdr.setSpacing(4)
        prob_text_lbl = QLabel("確率: 1% 〜 10%")
        prob_text_lbl.setFont(QFont("Meiryo", 7))
        prob_text_lbl.setStyleSheet(lbl_style)
        prob_hdr.addWidget(prob_text_lbl, stretch=1)
        prob_rand_btn = QPushButton("🎲")
        prob_rand_btn.setCheckable(True)
        prob_rand_btn.setStyleSheet(rand_btn_style)
        prob_rand_btn.setFixedWidth(28)
        prob_rand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        prob_rand_btn.setToolTip("完全ランダム（毎スピン 0〜100% から抽選）")
        prob_rand_btn.toggled.connect(self._on_effect_changed)
        prob_hdr.addWidget(prob_rand_btn)
        sel_layout.addLayout(prob_hdr)

        # 3行目: 確率 min/max スライダー（PWA は 2 input を縦に並べる）
        prob_min_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        prob_min_slider.setRange(0, 100)
        prob_min_slider.setValue(1)
        sel_layout.addWidget(prob_min_slider)
        prob_max_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        prob_max_slider.setRange(0, 100)
        prob_max_slider.setValue(10)
        sel_layout.addWidget(prob_max_slider)

        # 4行目: タイミング: 値テキスト + 🎲トグル
        timing_hdr = QHBoxLayout()
        timing_hdr.setSpacing(4)
        timing_text_lbl = QLabel("タイミング: 40% 〜 60%")
        timing_text_lbl.setFont(QFont("Meiryo", 7))
        timing_text_lbl.setStyleSheet(lbl_style)
        timing_hdr.addWidget(timing_text_lbl, stretch=1)
        timing_rand_btn = QPushButton("🎲")
        timing_rand_btn.setCheckable(True)
        timing_rand_btn.setStyleSheet(rand_btn_style)
        timing_rand_btn.setFixedWidth(28)
        timing_rand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        timing_rand_btn.setToolTip("完全ランダムタイミング")
        timing_rand_btn.toggled.connect(self._on_effect_changed)
        timing_hdr.addWidget(timing_rand_btn)
        sel_layout.addLayout(timing_hdr)

        timing_min_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        timing_min_slider.setRange(0, 100)
        timing_min_slider.setValue(40)
        sel_layout.addWidget(timing_min_slider)
        timing_max_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        timing_max_slider.setRange(0, 100)
        timing_max_slider.setValue(60)
        sel_layout.addWidget(timing_max_slider)

        c_layout.addWidget(select_widget)

        # ── 演出確認モード用 ──────────────────────────────────────
        # PWA: [表示名] [1][2][3][4][5][🎲] のみ
        confirm_widget = QWidget()
        conf_layout = QHBoxLayout(confirm_widget)
        conf_layout.setContentsMargins(0, 0, 0, 0)
        conf_layout.setSpacing(4)
        conf_name_lbl = QLabel(EFFECT_DISPLAY_NAMES.get(key, key))
        conf_name_lbl.setFont(QFont("Meiryo", 7))
        conf_name_lbl.setStyleSheet(f"color: {design.text};")
        conf_layout.addWidget(conf_name_lbl, stretch=1)
        prev_btns: list[QPushButton] = []
        for v_label, v_dat in zip(["1", "2", "3", "4", "5", "🎲"], [1, 2, 3, 4, 5, 0]):
            pb = QPushButton(v_label)
            pb.setFont(QFont("Meiryo", 8))
            pb.setStyleSheet(preview_btn_style)
            pb.setCursor(Qt.CursorShape.PointingHandCursor)
            if v_dat == 0:
                pb.setToolTip(f"バリエーション 1〜5 からランダム試聴")
            else:
                pb.setToolTip(f"バリエーション {v_dat} を試聴")
            # 全演出タイプを試聴するため preview_full_effect_requested を使う
            pb.clicked.connect(
                lambda _chk=False, ek=key, vd=v_dat:
                self.preview_full_effect_requested.emit(ek, vd)
            )
            prev_btns.append(pb)
            conf_layout.addWidget(pb)
        confirm_widget.setVisible(False)
        c_layout.addWidget(confirm_widget)

        sec.addWidget(container)

        # シグナル接続
        prob_min_slider.valueChanged.connect(
            lambda v, k=key: self._on_prob_min_changed(k, v)
        )
        prob_max_slider.valueChanged.connect(
            lambda v, k=key: self._on_prob_max_changed(k, v)
        )
        timing_min_slider.valueChanged.connect(
            lambda v, k=key: self._on_timing_min_changed(k, v)
        )
        timing_max_slider.valueChanged.connect(
            lambda v, k=key: self._on_timing_max_changed(k, v)
        )

        self._effect_rows[key] = {
            "cb":                cb,
            "var_btns":          var_btns,
            "selected_variant":  0,
            "prob_rand_btn":     prob_rand_btn,
            "prob_min_slider":   prob_min_slider,
            "prob_max_slider":   prob_max_slider,
            "prob_text_lbl":     prob_text_lbl,
            "timing_rand_btn":   timing_rand_btn,
            "timing_min_slider": timing_min_slider,
            "timing_max_slider": timing_max_slider,
            "timing_text_lbl":   timing_text_lbl,
            "select_widget":     select_widget,
            "confirm_widget":    confirm_widget,
            "prev_btns":         prev_btns,
        }

    # ── 演出モード切替 ──────────────────────────────────────────────

    def _set_effects_mode(self, mode: str):
        self._effects_mode = mode
        styles = getattr(self, "_effects_mode_styles", {})
        self._effects_select_btn.setStyleSheet(
            styles.get("active" if mode == "select" else "inactive", "")
        )
        self._effects_confirm_btn.setStyleSheet(
            styles.get("active" if mode == "confirm" else "inactive", "")
        )
        for row in self._effect_rows.values():
            row["select_widget"].setVisible(mode == "select")
            row["confirm_widget"].setVisible(mode == "confirm")
        if hasattr(self, "_effects_mode_hint"):
            self._effects_mode_hint.setText(
                "各演出のバリエーション・確率・タイミングを設定します。"
                if mode == "select"
                else "項目をタップすると、選択中のバリエーションでその場で試聴/視聴します。"
            )

    # ── バリアント・確率・タイミングハンドラ ───────────────────────

    def _on_effect_variant_clicked(self, key: str, variant: int):
        row = self._effect_rows.get(key)
        if row is None:
            return
        _var_data = [1, 2, 3, 4, 5, 0]  # PWA順序: [1][2][3][4][5][🎲]
        for i, btn in enumerate(row["var_btns"]):
            btn.setChecked(_var_data[i] == variant)
        row["selected_variant"] = variant
        self._on_effect_changed()

    def _update_prob_text(self, key: str):
        row = self._effect_rows.get(key)
        if row is None:
            return
        if row["prob_rand_btn"].isChecked():
            row["prob_text_lbl"].setText("確率: 0〜100% (完全ランダム)")
        else:
            row["prob_text_lbl"].setText(
                f"確率: {row['prob_min_slider'].value()}% 〜 {row['prob_max_slider'].value()}%"
            )

    def _update_timing_text(self, key: str):
        row = self._effect_rows.get(key)
        if row is None:
            return
        if row["timing_rand_btn"].isChecked():
            row["timing_text_lbl"].setText("タイミング: 0〜100% (完全ランダム)")
        else:
            row["timing_text_lbl"].setText(
                f"タイミング: {row['timing_min_slider'].value()}% 〜 {row['timing_max_slider'].value()}%"
            )

    def _on_prob_min_changed(self, key: str, value: int):
        row = self._effect_rows.get(key)
        if row is None:
            return
        # PWA: newMin = Math.min(v, max) — クランプ
        if value > row["prob_max_slider"].value():
            row["prob_min_slider"].blockSignals(True)
            row["prob_min_slider"].setValue(row["prob_max_slider"].value())
            row["prob_min_slider"].blockSignals(False)
        self._update_prob_text(key)
        self._on_effect_changed()

    def _on_prob_max_changed(self, key: str, value: int):
        row = self._effect_rows.get(key)
        if row is None:
            return
        if value < row["prob_min_slider"].value():
            row["prob_max_slider"].blockSignals(True)
            row["prob_max_slider"].setValue(row["prob_min_slider"].value())
            row["prob_max_slider"].blockSignals(False)
        self._update_prob_text(key)
        self._on_effect_changed()

    def _on_timing_min_changed(self, key: str, value: int):
        row = self._effect_rows.get(key)
        if row is None:
            return
        if value > row["timing_max_slider"].value():
            row["timing_min_slider"].blockSignals(True)
            row["timing_min_slider"].setValue(row["timing_max_slider"].value())
            row["timing_min_slider"].blockSignals(False)
        self._update_timing_text(key)
        self._on_effect_changed()

    def _on_timing_max_changed(self, key: str, value: int):
        row = self._effect_rows.get(key)
        if row is None:
            return
        if value < row["timing_min_slider"].value():
            row["timing_max_slider"].blockSignals(True)
            row["timing_max_slider"].setValue(row["timing_min_slider"].value())
            row["timing_max_slider"].blockSignals(False)
        self._update_timing_text(key)
        self._on_effect_changed()

    # ── グループ・全体リセット ─────────────────────────────────────

    def _on_effects_group_reset(self, group_keys: list[str]):
        from spin_effect_settings import default_effect_config
        for key in group_keys:
            self._apply_effect_config_to_ui(key, default_effect_config(key))
        self._on_effect_changed()

    def _on_effects_global_reset(self):
        from spin_effect_settings import default_effect_config
        master_state = self._effects_master_cb.isChecked()
        for key in EFFECT_KEYS:
            self._apply_effect_config_to_ui(key, default_effect_config(key))
        self._effects_master_cb.blockSignals(True)
        self._effects_master_cb.setChecked(master_state)
        self._effects_master_cb.blockSignals(False)
        self._on_effect_changed()

    def _apply_effect_config_to_ui(self, key: str, cfg: EffectConfig):
        """EffectConfig を UI に反映する（シグナルなし）。"""
        row = self._effect_rows.get(key)
        if row is None:
            return
        row["cb"].blockSignals(True)
        row["cb"].setChecked(cfg.enabled)
        row["cb"].blockSignals(False)
        _var_data = [1, 2, 3, 4, 5, 0]  # PWA順序: [1][2][3][4][5][🎲]
        for i, btn in enumerate(row["var_btns"]):
            btn.blockSignals(True)
            btn.setChecked(_var_data[i] == cfg.selected_variant)
            btn.blockSignals(False)
        row["selected_variant"] = cfg.selected_variant
        prob_min = max(0, min(100, int(round(cfg.probability_range[0] * 100))))
        prob_max = max(0, min(100, int(round(cfg.probability_range[1] * 100))))
        row["prob_min_slider"].blockSignals(True)
        row["prob_min_slider"].setValue(prob_min)
        row["prob_min_slider"].blockSignals(False)
        row["prob_max_slider"].blockSignals(True)
        row["prob_max_slider"].setValue(prob_max)
        row["prob_max_slider"].blockSignals(False)
        row["prob_rand_btn"].blockSignals(True)
        row["prob_rand_btn"].setChecked(cfg.probability_random)
        row["prob_rand_btn"].blockSignals(False)
        self._update_prob_text(key)
        timing_min = max(0, min(100, int(round(cfg.timing_range[0] * 100))))
        timing_max = max(0, min(100, int(round(cfg.timing_range[1] * 100))))
        row["timing_min_slider"].blockSignals(True)
        row["timing_min_slider"].setValue(timing_min)
        row["timing_min_slider"].blockSignals(False)
        row["timing_max_slider"].blockSignals(True)
        row["timing_max_slider"].setValue(timing_max)
        row["timing_max_slider"].blockSignals(False)
        row["timing_rand_btn"].blockSignals(True)
        row["timing_rand_btn"].setChecked(cfg.timing_random)
        row["timing_rand_btn"].blockSignals(False)
        self._update_timing_text(key)

    # ── collect / update ──────────────────────────────────────────

    def _collect_effects_settings(self) -> SpinEffectSettings:
        """現在の演出 UI 状態から SpinEffectSettings を構築する。"""
        from spin_effect_settings import default_effect_config
        enabled = self._effects_master_cb.isChecked()
        all_random = self._effects_all_random_cb.isChecked()
        effects = {}
        for key in EFFECT_KEYS:
            row = self._effect_rows.get(key)
            if row is None:
                effects[key] = default_effect_config(key)
                continue
            effects[key] = EffectConfig(
                enabled=row["cb"].isChecked(),
                probability_range=(
                    row["prob_min_slider"].value() / 100.0,
                    row["prob_max_slider"].value() / 100.0,
                ),
                probability_random=row["prob_rand_btn"].isChecked(),
                timing_range=(
                    row["timing_min_slider"].value() / 100.0,
                    row["timing_max_slider"].value() / 100.0,
                ),
                timing_random=row["timing_rand_btn"].isChecked(),
                selected_variant=row.get("selected_variant", 0),
            )
        return SpinEffectSettings(enabled=enabled, all_random=all_random, effects=effects)

    def _on_effect_changed(self):
        """演出設定変更時: SpinEffectSettings を構築してシグナルを発火。"""
        if not hasattr(self, "_effect_rows"):
            return
        self.setting_changed.emit("spin_effects", self._collect_effects_settings())

    def _update_effects_ui(self, s: SpinEffectSettings):
        """SpinEffectSettings から演出 UI を更新する（シグナルなし）。"""
        if not hasattr(self, "_effects_master_cb"):
            return
        self._effects_master_cb.blockSignals(True)
        self._effects_master_cb.setChecked(s.enabled)
        self._effects_master_cb.blockSignals(False)
        if hasattr(self, "_effects_all_random_cb"):
            self._effects_all_random_cb.blockSignals(True)
            self._effects_all_random_cb.setChecked(s.all_random)
            self._effects_all_random_cb.blockSignals(False)
        for key in EFFECT_KEYS:
            cfg = s.effects.get(key)
            if cfg is not None:
                self._apply_effect_config_to_ui(key, cfg)

