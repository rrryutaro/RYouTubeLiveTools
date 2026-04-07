"""
PySide6 プロトタイプ — メインウィンドウ

責務（アプリ骨格に集中）:
  - 全体レイアウト管理（wheel 領域 + 設定パネル）
  - 既存設定の読み込みと各コンポーネントへの配布
  - パネル表示 / 非表示（F1）
  - キーボードショートカット
  - コンテキストメニュー（表示系の設定）
  - サイズプロファイル
  - コンポーネント間のオーケストレーション

データの流れ（2系統）:
  bridge.load_config() → config dict
    【アプリ設定】→ load_app_settings() → AppSettings → 各コンポーネント
                 → load_design()       → DesignSettings → 各コンポーネント
    【項目データ】→ load_item_entries()            → list[ItemEntry] → SettingsPanel
                 → build_segments_from_config()   → list[Segment]  → WheelWidget

設定変更の通知:
  SettingsPanel.setting_changed(key, value) → MainWindow._on_setting_changed()
    → AppSettings 更新 → 該当コンポーネント更新
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout,
    QMenu, QSizePolicy, QApplication,
)

from bridge import (
    SIZE_PROFILES, SIDEBAR_W, MIN_W, MIN_H, VERSION,
    DesignSettings, DESIGN_PRESET_NAMES, DESIGN_PRESETS,
    load_config, load_design, load_items, load_item_entries,
    load_app_settings, build_segments_from_config,
    save_config, save_item_entries,
)
from app_settings import AppSettings
from wheel_widget import WheelWidget
from settings_panel import SettingsPanel
from spin_controller import SpinController
from result_overlay import ResultOverlay
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME
from sound_manager import SoundManager


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
        self._settings = load_app_settings(self._config)
        self._design = load_design(self._config)
        self._segments, self._items = build_segments_from_config(self._config)
        self._item_entries = load_item_entries(self._config)  # 項目データ（設定とは別管理）

        self.setWindowTitle(f"RRoulette (PySide6 Proto) v{VERSION}")
        self.setMinimumSize(MIN_W, MIN_H)

        # サイズプロファイル適用（パネル非表示 = wheel のみ）
        prof_idx = min(self._settings.profile_idx, len(SIZE_PROFILES) - 1)
        _, main_w, h = SIZE_PROFILES[prof_idx]
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
        self._apply_settings_to_wheel()

        # ============================================================
        #  サウンド（既存 SoundManager を再利用）
        # ============================================================

        self._sound = SoundManager()

        # ============================================================
        #  スピン制御（SpinController に委譲）
        # ============================================================

        self._spin_ctrl = SpinController(
            self._wheel, sound_manager=self._sound, parent=self
        )
        self._spin_ctrl.set_sound_tick_enabled(self._settings.sound_tick_enabled)
        self._spin_ctrl.set_sound_result_enabled(self._settings.sound_result_enabled)
        self._spin_ctrl.spin_finished.connect(self._on_spin_finished)
        if self._settings.spin_preset_name:
            self._spin_ctrl.set_spin_preset(self._settings.spin_preset_name)

        # ============================================================
        #  結果オーバーレイ（ResultOverlay に委譲）
        # ============================================================

        self._result_overlay = ResultOverlay(self._wheel_container)
        self._result_overlay.apply_style(self._design)
        self._result_overlay.set_close_mode(self._settings.result_close_mode)
        self._result_overlay.set_hold_sec(self._settings.result_hold_sec)

        # ============================================================
        #  操作・設定パネル（デフォルト非表示）
        # ============================================================

        self._settings_panel = SettingsPanel(
            self._item_entries, self._settings, self._design
        )
        self._settings_panel_visible = False
        self._settings_panel.hide()

        self._settings_panel.spin_requested.connect(self._start_spin)
        self._settings_panel.preset_changed.connect(self._on_preset_changed)
        self._settings_panel.setting_changed.connect(self._on_setting_changed)
        self._settings_panel.item_entries_changed.connect(
            self._on_item_entries_changed
        )

        # ============================================================
        #  レイアウト組み立て
        # ============================================================

        main_layout.addWidget(self._wheel_container, stretch=1)
        main_layout.addWidget(self._settings_panel, stretch=0)

        # --- ドラッグ状態 ---
        self._dragging_pointer = False

        # --- コンテキストメニュー（右クリック専用） ---
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ================================================================
    #  設定配布ヘルパー
    # ================================================================

    def _apply_settings_to_wheel(self):
        """AppSettings と DesignSettings を WheelWidget に一括配布する。"""
        s = self._settings
        self._wheel.set_design(self._design)
        self._wheel.set_text_mode(s.text_size_mode, s.text_direction)
        self._wheel.set_donut_hole(s.donut_hole)
        self._wheel.set_pointer_angle(s.pointer_angle)
        self._wheel.set_segments(self._segments)
        self._wheel._spin_direction = s.spin_direction

    # ================================================================
    #  保存ヘルパー
    #
    #  保存経路:
    #    【アプリ設定】AppSettings → to_config_patch() → config merge → save_config()
    #    【項目データ】ItemEntry   → save_item_entries(config, entries) → save_config()
    #    【デザイン】  DesignSettings → to_dict() → config["design"] → save_config()
    # ================================================================

    def _save_config(self):
        """アプリ設定・デザイン設定を config に書き戻して保存する。

        項目データの保存は _save_item_entries() を使う。
        """
        self._config.update(self._settings.to_config_patch())
        if self._design:
            self._config["design"] = self._design.to_dict()
        save_config(self._config)

    def _save_item_entries(self):
        """項目データを config に書き戻して保存する。"""
        save_item_entries(self._config, self._item_entries)

    # ================================================================
    #  初期表示・リサイズ — wheel と overlay の同期
    # ================================================================

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_wheel_container)

    def resizeEvent(self, event):
        super().resizeEvent(event)
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
        c = self._wheel_container
        w, h = c.width(), c.height()
        self._wheel.setGeometry(0, 0, w, h)
        self._result_overlay.update_position()

    # ================================================================
    #  Spin
    # ================================================================

    def _start_spin(self):
        if self._spin_ctrl.is_spinning:
            return
        self._result_overlay.dismiss()
        self._settings_panel.set_spinning(True)
        self._spin_ctrl.start_spin()

    def _on_spin_finished(self, winner: str, seg_idx: int):
        self._settings_panel.set_spinning(False)
        self._result_overlay.show_result(winner)

    def _on_preset_changed(self, name: str):
        self._spin_ctrl.set_spin_preset(name)
        self._settings.spin_preset_name = name
        self._save_config()

    # ================================================================
    #  設定変更ハンドラ（SettingsPanel → MainWindow → コンポーネント）
    # ================================================================

    def _on_setting_changed(self, key: str, value):
        """SettingsPanel からの設定変更を受けて各コンポーネントに反映する。

        設定更新の集約ポイント。将来設定を追加する場合は、
        ここに elif ブランチを足すだけで経路が通る。
        変更後に自動保存する（pointer_angle はドラッグ終了時に保存）。
        """
        # AppSettings を更新
        if hasattr(self._settings, key):
            setattr(self._settings, key, value)

        # 該当コンポーネントを更新
        if key == "text_size_mode":
            self._wheel.set_text_mode(value, self._settings.text_direction)
        elif key == "text_direction":
            self._wheel.set_text_mode(self._settings.text_size_mode, value)
        elif key == "donut_hole":
            self._wheel.set_donut_hole(value)
        elif key == "pointer_angle":
            self._wheel.set_pointer_angle(value)
            return  # ドラッグ中に大量発火するため、保存は mouseReleaseEvent で行う
        elif key == "spin_direction":
            self._wheel._spin_direction = value
        # サイズプロファイル
        elif key == "profile_idx":
            idx = min(value, len(SIZE_PROFILES) - 1)
            _, w, h = SIZE_PROFILES[idx]
            self._wheel_base_w = w
            self._wheel_base_h = h
            total_w = w
            if self._settings_panel_visible:
                total_w += SIDEBAR_W
            self.resize(total_w, h)
        # 結果表示設定
        elif key == "result_close_mode":
            self._result_overlay.set_close_mode(value)
        elif key == "result_hold_sec":
            self._result_overlay.set_hold_sec(value)
        # サウンド設定
        elif key == "sound_tick_enabled":
            self._spin_ctrl.set_sound_tick_enabled(value)
        elif key == "sound_result_enabled":
            self._spin_ctrl.set_sound_result_enabled(value)

        # 自動保存（pointer_angle 以外）
        self._save_config()

    # ================================================================
    #  項目データ変更ハンドラ
    # ================================================================

    def _on_item_entries_changed(self, entries: list):
        """SettingsPanel からの項目データ変更を受けて反映・保存する。

        将来の項目編集 UI が item_entries_changed を emit した際の経路。
        """
        from item_entry import ItemEntry
        self._item_entries = entries
        # segments を再構築
        self._segments, self._items = build_segments_from_config(self._config)
        self._wheel.set_segments(self._segments)
        # 項目データを保存
        self._save_item_entries()

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
        s = self._settings
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
            marker = "\u25cf" if idx == s.profile_idx else "  "
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
            marker = "\u25cf" if m == s.text_size_mode else "  "
            action = menu.addAction(f"{marker} テキスト: {name}")
            action.triggered.connect(
                lambda checked, mm=m: self._set_text_size_mode(mm)
            )

        menu.addSeparator()

        # ドーナツ穴
        donut_mark = "\u25cf" if s.donut_hole else "  "
        action = menu.addAction(f"{donut_mark} ドーナツ穴")
        action.triggered.connect(self._toggle_donut)

        menu.addSeparator()

        # 終了
        menu.addAction("  終了").triggered.connect(self.close)

        menu.exec(self.mapToGlobal(pos))

    # ================================================================
    #  設定変更アクション（コンテキストメニュー経由）
    # ================================================================

    def _set_profile(self, idx: int, w: int, h: int):
        self._settings.profile_idx = idx
        self._wheel_base_w = w
        self._wheel_base_h = h
        total_w = w
        if self._settings_panel_visible:
            total_w += SIDEBAR_W
        self.resize(total_w, h)
        self._settings_panel.update_setting("profile_idx", idx)
        self._save_config()

    def _apply_design_preset(self, name: str):
        preset = DESIGN_PRESETS.get(name)
        if preset is None:
            return
        self._design = DesignSettings.from_dict(preset.to_dict())
        self._design.preset_name = name
        self._settings.design_preset_name = name

        self._wheel.set_design(self._design)
        self.centralWidget().setStyleSheet(f"background-color: {self._design.bg};")
        self._settings_panel.update_design(self._design)
        self._result_overlay.apply_style(self._design)
        self._save_config()

    def _set_text_size_mode(self, mode: int):
        self._settings.text_size_mode = mode
        self._wheel.set_text_mode(mode, self._settings.text_direction)
        self._settings_panel.update_setting("text_size_mode", mode)
        self._save_config()

    def _toggle_donut(self):
        self._settings.donut_hole = not self._settings.donut_hole
        self._wheel.set_donut_hole(self._settings.donut_hole)
        self._settings_panel.update_setting("donut_hole", self._settings.donut_hole)
        self._save_config()

    # ================================================================
    #  入力操作（一覧）
    #
    #  ┌──────────────────────────────────┬──────────────────────────┐
    #  │ 入力                             │ 動作                     │
    #  ├──────────────────────────────────┼──────────────────────────┤
    #  │ ホイール上左クリック              │ spin 開始                │
    #  │ ポインター上左ドラッグ            │ pointer 角度変更         │
    #  │ ホイール外左クリック              │ 無視（super に委譲）     │
    #  │ スピン中のクリック/ドラッグ       │ 無視                     │
    #  │ 結果 overlay 表示中の左クリック   │ overlay 側で閉じ判定     │
    #  │ マウスホイール回転                │ 無効化（誤操作防止）     │
    #  │ 右クリック                        │ コンテキストメニュー     │
    #  │ Space                            │ spin 開始                │
    #  │ F1                               │ 設定パネル開閉           │
    #  │ Escape                           │ アプリ終了               │
    #  └──────────────────────────────────┴──────────────────────────┘
    #
    #  将来の変更ポイント:
    #    - スピン中 pointer 移動許可: mousePressEvent 内の
    #      `if not self._spin_ctrl.is_spinning` 条件を外し、
    #      pointer_hit 分岐のみ独立させる
    #    - マウスホイールに機能割り当て: wheelEvent を用途に応じて実装
    # ================================================================

    # ── キーボード ──

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_F1:
            self._toggle_settings_panel()
        elif event.key() == Qt.Key.Key_Space:
            self._start_spin()
        super().keyPressEvent(event)

    # ── マウスクリック・ドラッグ ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # overlay 表示中は overlay 側で処理
            if self._result_overlay.isVisible():
                super().mousePressEvent(event)
                return
            # wheel 領域内の判定
            local_pos = self._wheel_container.mapFrom(self, event.pos())
            if self._wheel_container.rect().contains(local_pos):
                wheel_pos = self._wheel.mapFrom(self._wheel_container, local_pos)
                if not self._spin_ctrl.is_spinning:
                    # ポインター上 → ドラッグ開始（spin より優先）
                    if self._wheel.pointer_hit(wheel_pos.x(), wheel_pos.y()):
                        self._dragging_pointer = True
                        return
                    # ポインター以外のホイール内クリック → spin 開始
                    self._start_spin()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_pointer:
            local_pos = self._wheel_container.mapFrom(self, event.pos())
            wheel_pos = self._wheel.mapFrom(self._wheel_container, local_pos)
            angle = self._wheel.angle_from_pos(wheel_pos.x(), wheel_pos.y())
            self._settings.pointer_angle = angle
            self._wheel.set_pointer_angle(angle)
            self._settings_panel.update_setting("pointer_angle", angle)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_pointer:
            self._dragging_pointer = False
            self._save_config()  # ドラッグ完了時に pointer_angle を保存
            return
        super().mouseReleaseEvent(event)

    # ── マウスホイール ──

    def wheelEvent(self, event):
        """ホイール領域でのマウスホイール回転を無効化する。

        現時点ではマウスホイールに割り当てる操作がなく、
        意図しないスクロールや誤操作を防ぐため明示的に無効化する。
        SettingsPanel 内のスクロールは QScrollArea が独自に処理するため影響なし。

        将来マウスホイールに機能を割り当てる場合はここに実装する。
        """
        # SettingsPanel 上ではスクロールを許可
        panel_pos = self._settings_panel.mapFrom(self, event.position().toPoint())
        if self._settings_panel_visible and self._settings_panel.rect().contains(panel_pos):
            super().wheelEvent(event)
            return
        # それ以外（ホイール領域等）では無効化
        event.accept()
