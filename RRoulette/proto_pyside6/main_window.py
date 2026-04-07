"""
PySide6 プロトタイプ — メインウィンドウ

責務（アプリ骨格に集中）:
  - 全体レイアウト管理（wheel 領域 + 設定パネル）
  - 既存設定の読み込みと各コンポーネントへの配布
  - パネル表示 / 非表示（F1）
  - キーボードショートカット
  - コンテキストメニュー（表示系の設定）
  - サイズプロファイル

スピン制御は SpinController、結果表示は ResultOverlay に委譲。

既存ロジック接続:
  - constants.py: SIZE_PROFILES, SIDEBAR_W, MIN_W, MIN_H, VERSION
  - design_settings.py: DesignSettings, DESIGN_PRESET_NAMES
  - config_utils.py: CONFIG_FILE -> 設定読み込み
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout,
    QMenu, QSizePolicy, QApplication,
)

from bridge import (
    SIZE_PROFILES, SIDEBAR_W, MIN_W, MIN_H, VERSION,
    DesignSettings, DESIGN_PRESET_NAMES, DESIGN_PRESETS,
    load_config, load_design, load_items, build_segments_from_config,
)
from wheel_widget import WheelWidget
from settings_panel import SettingsPanel
from spin_controller import SpinController
from result_overlay import ResultOverlay
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME


class MainWindow(QMainWindow):
    """PySide6 プロトタイプのメインウィンドウ。

    責務:
      - 全体レイアウトの管理（wheel 領域 + 設定パネル）
      - 既存設定の読み込みと各コンポーネントへの配布
      - コンテキストメニュー（表示系の設定）
      - キーボード操作
      - コンポーネント間の接続（オーケストレーション）
    """

    def __init__(self):
        super().__init__()

        # --- 既存設定の読み込み ---
        self._config = load_config()
        self._design = load_design(self._config)
        self._segments, self._items = build_segments_from_config(self._config)

        # 既存設定からの復元
        self._pointer_angle = self._config.get("pointer_angle", 0.0)
        self._text_size_mode = self._config.get("text_size_mode", 1)
        self._text_direction = self._config.get("text_direction", 0)
        self._donut_hole = self._config.get("donut_hole", False)
        self._profile_idx = self._config.get("profile_idx", 1)
        self._spin_direction = self._config.get("spin_direction", 0)

        self.setWindowTitle(f"RRoulette (PySide6 Proto) v{VERSION}")
        self.setMinimumSize(MIN_W, MIN_H)

        # サイズプロファイル適用（パネル非表示 = wheel のみ）
        _, main_w, h = SIZE_PROFILES[min(self._profile_idx, len(SIZE_PROFILES) - 1)]
        self._wheel_base_w = main_w
        self._wheel_base_h = h
        self.resize(main_w, h)

        # --- 中央ウィジェット ---
        central = QWidget()
        central.setStyleSheet(f"background-color: {self._design.bg};")
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(0)

        # ============================================================
        #  wheel 表示領域
        # ============================================================

        self._wheel_container = QWidget()
        self._wheel_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._wheel = WheelWidget(self._wheel_container)
        self._wheel.set_design(self._design)
        self._wheel.set_text_mode(self._text_size_mode, self._text_direction)
        self._wheel.set_donut_hole(self._donut_hole)
        self._wheel.set_pointer_angle(self._pointer_angle)
        self._wheel.set_segments(self._segments)
        self._wheel._spin_direction = self._spin_direction

        # ============================================================
        #  スピン制御（SpinController に委譲）
        # ============================================================

        self._spin_ctrl = SpinController(self._wheel, parent=self)
        self._spin_ctrl.spin_finished.connect(self._on_spin_finished)

        # ============================================================
        #  結果オーバーレイ（ResultOverlay に委譲）
        # ============================================================

        self._result_overlay = ResultOverlay(self._wheel_container)
        self._result_overlay.apply_style(self._design)

        # ============================================================
        #  操作・設定パネル（デフォルト非表示）
        # ============================================================

        display_items = load_items(self._config)
        self._settings_panel = SettingsPanel(display_items, self._design)
        self._settings_panel_visible = False
        self._settings_panel.hide()

        self._settings_panel.spin_requested.connect(self._start_spin)
        self._settings_panel.preset_changed.connect(self._on_preset_changed)

        # ============================================================
        #  レイアウト組み立て
        # ============================================================

        main_layout.addWidget(self._wheel_container, stretch=1)
        main_layout.addWidget(self._settings_panel, stretch=0)

        # --- コンテキストメニュー（右クリック専用） ---
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ================================================================
    #  初期表示・リサイズ — wheel と overlay の同期
    # ================================================================

    def showEvent(self, event):
        """初回表示時に wheel をウィンドウ全体へフィットさせる。"""
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_wheel_container)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Shift 押下中は正方形を維持
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            size = max(event.size().width(), event.size().height())
            if self._settings_panel_visible:
                size = max(size - SIDEBAR_W, MIN_W) + SIDEBAR_W
            self.blockSignals(True)
            if not self._settings_panel_visible:
                self.resize(size, size)
            else:
                wheel_side = size - SIDEBAR_W
                self.resize(size, wheel_side)
            self.blockSignals(False)
        self._sync_wheel_container()

    def _sync_wheel_container(self):
        """wheel_container 内の wheel と結果 overlay の位置・サイズを同期する。"""
        c = self._wheel_container
        w, h = c.width(), c.height()
        self._wheel.setGeometry(0, 0, w, h)
        self._result_overlay.update_position()

    # ================================================================
    #  Spin（左クリック / Space / ボタン で開始）
    # ================================================================

    def _start_spin(self):
        """spin を開始する。"""
        if self._spin_ctrl.is_spinning:
            return
        self._result_overlay.hide()
        self._settings_panel.set_spinning(True)
        self._spin_ctrl.start_spin()

    def _on_spin_finished(self, winner: str, seg_idx: int):
        """spin 完了時のハンドラ。"""
        self._settings_panel.set_spinning(False)
        self._result_overlay.show_result(winner)

    def _on_preset_changed(self, name: str):
        """プリセット切替ハンドラ。"""
        self._spin_ctrl.set_spin_preset(name)

    # ================================================================
    #  パネル開閉（F1 でトグル、ウィンドウ幅を連動）
    # ================================================================

    def _toggle_settings_panel(self):
        if self._settings_panel_visible:
            self._settings_panel.hide()
            self._settings_panel_visible = False
            self.resize(self.width() - SIDEBAR_W, self.height())
        else:
            self._settings_panel.show()
            self._settings_panel_visible = True
            self.resize(self.width() + SIDEBAR_W, self.height())

    # ================================================================
    #  コンテキストメニュー（右クリック専用）
    # ================================================================

    def _show_context_menu(self, pos):
        d = self._design
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {d.panel};
                color: {d.text};
                font-family: Meiryo;
                font-size: 10pt;
                border: 1px solid {d.separator};
            }}
            QMenu::item:selected {{
                background-color: {d.separator};
            }}
        """)

        # スピン
        spin_action = menu.addAction("  スピン開始 (Space)")
        spin_action.triggered.connect(self._start_spin)
        if self._spin_ctrl.is_spinning:
            spin_action.setEnabled(False)

        menu.addSeparator()

        # パネル開閉
        panel_mark = "\u25cf" if self._settings_panel_visible else "  "
        action = menu.addAction(f"{panel_mark} 設定パネルを表示 (F1)")
        action.triggered.connect(self._toggle_settings_panel)

        menu.addSeparator()

        # サイズプロファイル
        for idx, (label, w, h) in enumerate(SIZE_PROFILES):
            marker = "\u25cf" if idx == self._profile_idx else "  "
            action = menu.addAction(f"{marker} サイズ {label}  ({w} x {h})")
            action.triggered.connect(
                lambda checked, i=idx, ww=w, hh=h: self._set_profile(i, ww, hh)
            )

        menu.addSeparator()

        # デザインプリセット
        current_preset = self._design.preset_name
        for name in DESIGN_PRESET_NAMES:
            marker = "\u25cf" if name == current_preset else "  "
            action = menu.addAction(f"{marker} デザイン: {name}")
            action.triggered.connect(
                lambda checked, n=name: self._apply_design_preset(n)
            )

        menu.addSeparator()

        # テキスト表示モード
        mode_names = ["省略", "収める", "縮小"]
        for m, name in enumerate(mode_names):
            marker = "\u25cf" if m == self._text_size_mode else "  "
            action = menu.addAction(f"{marker} テキスト: {name}")
            action.triggered.connect(
                lambda checked, mm=m: self._set_text_size_mode(mm)
            )

        menu.addSeparator()

        # ドーナツ穴
        donut_mark = "\u25cf" if self._donut_hole else "  "
        action = menu.addAction(f"{donut_mark} ドーナツ穴")
        action.triggered.connect(self._toggle_donut)

        menu.addSeparator()

        # 終了
        menu.addAction("  終了").triggered.connect(self.close)

        menu.exec(self.mapToGlobal(pos))

    # ================================================================
    #  設定変更ハンドラ
    # ================================================================

    def _set_profile(self, idx: int, w: int, h: int):
        self._profile_idx = idx
        self._wheel_base_w = w
        self._wheel_base_h = h
        total_w = w
        if self._settings_panel_visible:
            total_w += SIDEBAR_W
        self.resize(total_w, h)

    def _apply_design_preset(self, name: str):
        preset = DESIGN_PRESETS.get(name)
        if preset is None:
            return
        self._design = DesignSettings.from_dict(preset.to_dict())
        self._design.preset_name = name

        self._wheel.set_design(self._design)
        self.centralWidget().setStyleSheet(f"background-color: {self._design.bg};")
        self._settings_panel.update_design(self._design)
        self._result_overlay.apply_style(self._design)

    def _set_text_size_mode(self, mode: int):
        self._text_size_mode = mode
        self._wheel.set_text_mode(mode, self._text_direction)

    def _toggle_donut(self):
        self._donut_hole = not self._donut_hole
        self._wheel.set_donut_hole(self._donut_hole)

    # ================================================================
    #  キーボード
    # ================================================================

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_F1:
            self._toggle_settings_panel()
        elif event.key() == Qt.Key.Key_Space:
            self._start_spin()
        super().keyPressEvent(event)

    # ================================================================
    #  マウス操作（左クリック = spin）
    # ================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # overlay 表示中は spin しない（overlay 側で処理される）
            if self._result_overlay.isVisible():
                super().mousePressEvent(event)
                return
            # wheel 領域の左クリックで spin 開始
            local_pos = self._wheel_container.mapFrom(self, event.pos())
            if self._wheel_container.rect().contains(local_pos):
                if not self._spin_ctrl.is_spinning:
                    self._start_spin()
                    return
        super().mousePressEvent(event)
