"""
main_window.py — MainWindow 初期化オーケストレーター

責務:
  - MainWindow クラスの定義と初期化シーケンスの管理
  - 各 mixin / 補助モジュールの組み合わせ

アーキテクチャ概要:
  機能的な責務の大部分は mixin クラス群へ委譲されている。
  main_window.py 本体は「どの順序で何を初期化するか」を管理する
  オーケストレーターとして機能する。

主な mixin / 補助モジュール:
  AccessorHelperMixin    — active roulette 参照 accessor + パスヘルパー
  SaveLoadMixin          — 設定保存 / 同期
  ActionDispatchMixin    — アクション適用・ディスパッチ・タイトル更新
  WindowFrameMixin       — frameless ウィンドウ操作・エッジリサイズ・イベントハンドラ
  ContextMenuMixin       — コンテキストメニュー
  UIToggleMixin          — roulette-only モード・パネル表示切替
  PackageIOMixin         — ルーレットパッケージ export/import
  SettingsIOMixin        — 設定 export/import・ログ import
  LogShuffleMixin        — ログ操作・shuffle / reset
  MacroFlowMixin         — マクロ再生・分岐実行
  DesignGraphMixin       — デザインエディタ・グラフダイアログ
  ReplayManagementMixin  — リプレイ管理
  PatternManagementMixin — パターン管理
  ItemEntriesMixin       — 項目データ変更
  SettingsDispatchMixin  — 設定変更ディスパッチ
  SpinFlowMixin          — スピン開始 / 終了 / 結果反映
  RouletteLifecycleMixin — ルーレットのライフサイクル（生成・削除・復元）
  PanelGeometryMixin     — パネルジオメトリ復元・保存
  main_window_helpers    — _SpaceSpinFilter, _MainWindowDragBar

パネル構成:
  RoulettePanel  — ルーレット描画・操作（独立パネル、複数インスタンス対応）
  SettingsPanel  — 項目設定・表示設定
  ItemPanel      — 項目リスト・パターン管理
  ManagePanel    — マルチルーレット管理
  各パネルは独立に移動・リサイズ可能。
"""

from PySide6.QtCore import Qt, QTimer, QPoint, QRect
from PySide6.QtWidgets import QMainWindow, QWidget, QApplication

import os

from bridge import (
    SIZE_PROFILES, MIN_W, MIN_H, VERSION,
    DesignSettings, DESIGN_PRESET_NAMES, DESIGN_PRESETS,
    DesignPresetManager,
    load_config, load_design,
    load_all_item_entries, load_app_settings,
    build_segments_from_config,
    save_item_entries,
    get_pattern_names, get_current_pattern_name,
    set_current_pattern, add_pattern, delete_pattern, rename_pattern,
    get_pattern_id, ensure_pattern_ids,
)
from config_utils import BASE_DIR
from app_settings import AppSettings
from win_history import WinHistory
from replay_manager_pyside6 import ReplayManager
from roulette_manager import RouletteManager
from per_roulette_settings import PerRouletteSettings
from roulette_actions import LastSpinResult
from roulette_action_recorder import ActionRecorder
from roulette_macro_session import MacroPlaybackSession
from settings_panel import SettingsPanel
from item_panel import ItemPanel, _ItemPanelAPI
from manage_panel import ManagePanel
from panel_widgets import _PanelGrip
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME
from sound_manager import SoundManager
from dark_theme import get_app_stylesheet, resolve_theme_mode
from panel_input_filter import PanelInputFilter
from panel_geometry_mixin import PanelGeometryMixin
from roulette_lifecycle_mixin import RouletteLifecycleMixin
from spin_flow_mixin import SpinFlowMixin
from settings_dispatch_mixin import SettingsDispatchMixin
from item_entries_mixin import ItemEntriesMixin
from pattern_management_mixin import PatternManagementMixin
from replay_management_mixin import ReplayManagementMixin
from design_graph_mixin import DesignGraphMixin
from macro_flow_mixin import MacroFlowMixin
from log_shuffle_mixin import LogShuffleMixin
from settings_io_mixin import SettingsIOMixin
from package_io_mixin import PackageIOMixin
from ui_toggle_mixin import UIToggleMixin
from context_menu_mixin import ContextMenuMixin
from window_frame_mixin import WindowFrameMixin
from action_dispatch_mixin import ActionDispatchMixin
from save_load_mixin import SaveLoadMixin
from accessor_helper_mixin import AccessorHelperMixin
from main_window_helpers import _SpaceSpinFilter, _TabRouletteFilter, _MainWindowDragBar



class MainWindow(AccessorHelperMixin, SaveLoadMixin, ActionDispatchMixin, WindowFrameMixin, ContextMenuMixin, UIToggleMixin, PackageIOMixin, SettingsIOMixin, LogShuffleMixin, MacroFlowMixin, DesignGraphMixin, ReplayManagementMixin, PatternManagementMixin, ItemEntriesMixin, SettingsDispatchMixin, SpinFlowMixin, RouletteLifecycleMixin, PanelGeometryMixin, QMainWindow):
    """PySide6 プロトタイプのメインウィンドウ。

    独立パネル群（RoulettePanel, SettingsPanel）を載せる土台。
    パネル同士は互いの geometry に干渉しない。
    """

    # エッジリサイズ定数
    _EDGE_SIZE = 6
    _EDGE_NONE = 0
    _EDGE_RIGHT = 1
    _EDGE_BOTTOM = 2
    _EDGE_CORNER = 3  # right + bottom

    # 初回起動時の横長デフォルトサイズ（ルーレット正方形 + 項目パネル）
    # 高さ 700px → ルーレット正方形領域 = 696×696 (= 700 - 4px margin)
    # 幅 1080px → ルーレット 696 + gap 12 + 項目パネル 360 + margin 12
    # i317: ルーレット正方形を大きく表示するため高さを 600→700 に拡張
    #   rp_size = min(1080, 700) - 4 = 696
    #   ip_x = 696 + 4 + 8 = 708, ip_w = 1080 - 708 - 12 = 360 (i316の幅を維持)
    _INITIAL_W = 980
    _INITIAL_H = 600

    def __init__(self):
        super().__init__()

        # --- frameless ウィンドウ（フラグは _apply_window_flags で設定） ---
        self.setMouseTracking(True)
        # 初期化中のフラグ（debounce save 等を init 中に発火させない）
        self._init_complete = False

        self._init_config_and_design()
        self._init_window_shell()
        central = self._init_central_widget()
        self._init_core_managers()
        self._init_roulette_panel(central)
        self._init_settings_panel(central)
        self._init_item_panel(central)
        self._init_manage_panel(central)
        self._connect_panel_geometry_signals()
        self._init_input_filters()
        self._init_runtime_state(central)

        # 初期化完了フラグを立て、以後の geometry_changed で
        # _persist_panel_positions が走るようにする。
        self._init_complete = True

    # ================================================================
    #  __init__ 補助 — 責務別 private initializer 群 (i453)
    # ================================================================

    def _init_config_and_design(self):
        """設定・デザイン・プリセット・マネージャー・パネル一覧の初期化。"""
        # --- 既存設定の読み込み ---
        self._config = load_config()
        self._settings = load_app_settings(self._config)
        self._design = load_design(self._config)

        # --- デザインプリセットマネージャー ---
        self._preset_mgr = DesignPresetManager.from_dict(
            self._config.get("design_presets", {})
        )
        self._design_editor = None  # DesignEditorDialog (遅延生成)
        self._graph_dialog = None   # GraphDialog (遅延生成)
        self._replay_dialog = None  # ReplayDialog (遅延生成)
        # i352: 同時実行リプレイのセッション管理（{roulette_id, panel, saved_*} のリスト）
        self._replay_sessions: list[dict] = []
        self._replay_group_remaining: int = 0

        # --- ルーレットマネージャー・パネル一覧 ---
        self._manager = RouletteManager(parent=self)
        self._manager.active_changed.connect(self._on_active_changed)
        self._panels: list[QWidget] = []

    def _init_window_shell(self):
        """タイトル・最小サイズ・ウィンドウフラグ・透過基盤・サイズプロファイル・位置復元。"""
        self.setWindowTitle(self._base_window_title())
        # メインウィンドウ最小サイズ:
        # ルーレットパネル最小描画領域 (約 272x272) ＋ ポインター描画余白を
        # 確保するため 320x320 に設定する。これより小さくすると描画破綻が
        # 発生する。v0.4.4 とほぼ同等で、過剰に大きくはしていない。
        self.setMinimumSize(320, 320)

        # frameless + always_on_top
        self._apply_window_flags()

        # 透過モード基盤を常時有効化する。
        # WA_TranslucentBackground は **show 前に必ず立てておく** のが
        # Windows 上で安定動作する条件で、show 後に setAttribute だけで
        # 切り替えるのは native window 再生成を伴うため不安定になる。
        # 実際の見た目の透過/不透明は centralWidget の背景塗りで切り替える。
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_NoSystemBackground, True
        )
        self.setStyleSheet(
            "QMainWindow { background: transparent; }"
        )

        # サイズプロファイル（保存値が無い場合のデフォルト）
        prof_idx = min(self._settings.profile_idx, len(SIZE_PROFILES) - 1)
        _, default_w, default_h = SIZE_PROFILES[prof_idx]
        self._wheel_base_w = default_w
        self._wheel_base_h = default_h

        # ウィンドウサイズ・位置の復元
        self._restore_window_geometry(default_w, default_h)

    def _init_central_widget(self) -> QWidget:
        """中央ウィジェットの生成・背景適用・テーマ適用。central を返す。"""
        # --- 中央ウィジェット（レイアウトなし — パネルを手動配置） ---
        # 注意: centralWidget には WA_TranslucentBackground を立てない。
        # 立てると stylesheet の background-color が描画されなくなり、
        # 「不透明モード」のときに solid bg が出なくなる。
        # QMainWindow 側だけ WA_TranslucentBackground=True にしてあるので、
        # centralWidget の bg を transparent にすればウィンドウ全体が透ける。
        central = QWidget()
        central.setAutoFillBackground(False)
        central.setMouseTracking(True)
        self.setCentralWidget(central)
        self._apply_central_background(self._settings.window_transparent)

        # --- ダークテーマ適用 ---
        self._apply_app_theme(self._design)

        return central

    def _init_core_managers(self):
        """ActionRecorder / マクロ状態 / サウンド / 履歴 / リプレイ管理の初期化。"""
        # ============================================================
        #  アクション記録バッファ
        # ============================================================

        self._recorder = ActionRecorder()
        self._macro_session = MacroPlaybackSession()

        # ============================================================
        #  マクロ自動進行状態（spin 完了待ち → 自動再開）
        # ============================================================

        self._macro_auto_advancing: bool = False
        self._macro_waiting_spin: bool = False
        self._macro_waiting_roulette_id: str | None = None
        self._macro_viewer = None  # MacroActionViewer 参照（表示中のみ）

        # 直前当選結果（manual / macro 共通）
        self._last_spin_result: LastSpinResult | None = None

        # ============================================================
        #  サウンド
        # ============================================================

        self._sound = SoundManager()
        self._log_autosave_path = os.path.join(BASE_DIR, "roulette_autosave_log.json")
        self._win_history = WinHistory(
            os.path.join(BASE_DIR, "roulette_win_history.json")
        )
        self._win_history.load()
        ensure_pattern_ids(self._config)
        # i351: ルーレットごとに個別の ReplayManager を保持する辞書。
        # _create_roulette でルーレット追加時に生成し、_remove_roulette で削除する。
        self._replay_mgrs: dict[str, ReplayManager] = {}
        self._sound.set_tick_volume(self._settings.tick_volume / 100.0)
        self._sound.set_win_volume(self._settings.win_volume / 100.0)
        self._sound.set_tick_pattern(self._settings.tick_pattern)
        self._sound.set_win_pattern(self._settings.win_pattern)
        if self._settings.tick_custom_file:
            self._sound.load_tick_custom(self._settings.tick_custom_file)
        if self._settings.win_custom_file:
            self._sound.load_win_custom(self._settings.win_custom_file)

    def _init_roulette_panel(self, central: QWidget):
        """デフォルトルーレットパネルの生成・ログ復元・パターン初期設定。"""
        # ============================================================
        #  ルーレットパネル（独立パネル）
        # ============================================================

        self._roulette_panel = self._create_roulette("default", central)

        # ログ履歴復元
        self._roulette_panel.wheel.load_log(self._log_autosave_path)
        # i405: load_log 直後に _current_pattern を設定する。
        # _sync_settings_to_active は __init__ 内で呼ばれないため、
        # ここで明示設定しないと起動直後のログが _current_pattern="" のまま表示されない。
        _init_pat = get_current_pattern_name(self._config)
        _init_pid = get_pattern_id(self._config, _init_pat)
        self._roulette_panel.wheel.set_current_pattern(_init_pat, _init_pid)

    def _init_settings_panel(self, central: QWidget):
        """SettingsPanel の生成・初期状態設定・grip/ctrlbox/ドラッグバー・タイマー初期化。"""
        # ============================================================
        #  項目設定パネル（メインウィンドウ内の内部パネル / i277）
        # ============================================================

        # i277: SettingsPanel は centralWidget の child widget。
        # OBS が取り込めるようにするには別ウィンドウではなく
        # メインウィンドウの内部要素である必要がある。
        self._settings_panel = SettingsPanel(
            self._active_context.item_entries, self._settings, self._design,
            pattern_names=get_pattern_names(self._config),
            current_pattern=get_current_pattern_name(self._config),
            on_drag_bar_changed=lambda vis: self._on_settings_panel_drag_bar_changed(vis),
            parent=central,
        )
        self._settings_panel._floating = False
        self._settings_panel_visible = False
        self._settings_panel.hide()
        self._roulette_only_saved_visibility: dict = {}  # roulette_only_mode 前の状態保存

        self._connect_settings_panel_signals()

        # i277: SettingsPanel は内部パネルへ戻したため、ここでは事前 restore
        # を行わない (`_restore_all_panel_geometries` で 3 パネルまとめて
        # 復元する)。

        # --- grip / ctrl_box の初期状態適用 ---
        if not self._settings.grip_visible:
            self._apply_grip_visible(False)
        if not self._settings.ctrl_box_visible:
            self._apply_ctrl_box_visible(False)

        # --- 移動バー表示状態の復元 (E: i294) ---
        if not self._settings.settings_panel_drag_bar_visible:
            self._settings_panel._drag_bar.setVisible(False)

        # --- パネル位置の保存を間引くためのデバウンスタイマー ---
        # geometry_changed が連続発火しても、最後の値だけを 500ms 後に書き出す
        self._panel_save_timer = QTimer(self)
        self._panel_save_timer.setSingleShot(True)
        self._panel_save_timer.setInterval(500)
        self._panel_save_timer.timeout.connect(self._persist_panel_positions)

        # --- パネル一覧（Z オーダー管理対象）に SettingsPanel を追加 ---
        # geometry_changed 接続は _connect_panel_geometry_signals() で一括処理
        self._panels.append(self._settings_panel)

    def _connect_settings_panel_signals(self):
        """SettingsPanel の全シグナルを接続する。"""
        self._settings_panel.spin_requested.connect(self._start_spin)
        self._settings_panel.preset_changed.connect(self._on_preset_changed)
        self._settings_panel.setting_changed.connect(self._on_setting_changed)
        self._settings_panel.item_entries_changed.connect(
            self._on_item_entries_changed
        )
        self._settings_panel.pattern_switched.connect(self._on_pattern_switched)
        self._settings_panel.pattern_added.connect(self._on_pattern_added)
        self._settings_panel.pattern_deleted.connect(self._on_pattern_deleted)
        self._settings_panel.pattern_renamed.connect(self._on_pattern_renamed)  # i400
        self._settings_panel.preview_tick_requested.connect(self._on_preview_tick)
        self._settings_panel.preview_win_requested.connect(self._on_preview_win)
        self._settings_panel.custom_tick_file_changed.connect(self._on_custom_tick_file)
        self._settings_panel.custom_win_file_changed.connect(self._on_custom_win_file)
        self._settings_panel.log_clear_requested.connect(self._on_log_clear)
        self._settings_panel.shuffle_once_requested.connect(self._on_shuffle_once)
        # i284: 並びリセット / 項目一括リセット
        self._settings_panel.arrangement_reset_requested.connect(
            self._on_arrangement_reset
        )
        self._settings_panel.items_reset_requested.connect(
            self._on_items_reset
        )
        self._settings_panel.pattern_export_requested.connect(self._on_pattern_export)
        self._settings_panel.pattern_import_requested.connect(self._on_pattern_import)
        self._settings_panel.log_export_requested.connect(self._on_log_export)
        self._settings_panel.log_import_requested.connect(self._on_log_import)
        self._settings_panel.settings_export_requested.connect(self._on_settings_export)
        self._settings_panel.settings_import_requested.connect(self._on_settings_import)
        self._settings_panel.design_editor_requested.connect(
            self._open_design_editor
        )
        self._settings_panel.graph_requested.connect(self._open_graph)
        self._settings_panel.replay_play_requested.connect(
            lambda: self._start_replay(0)
        )
        self._settings_panel.replay_stop_requested.connect(self._cancel_replay)
        self._settings_panel.replay_manager_requested.connect(
            self._open_replay_manager
        )

    def _init_item_panel(self, central: QWidget):
        """ItemPanel の生成・初期状態設定・パネル一覧への追加。"""
        # --- 項目パネル（メインウィンドウ内の内部パネル / i277）---
        # SettingsPanel から項目セクションとパターン (グループ) セクションを
        # 取り外し、ItemPanel に載せ替える。**centralWidget の child widget**。
        items_widget = self._settings_panel.pop_items_section()
        pattern_widget = self._settings_panel.pop_pattern_section()
        self._item_panel = ItemPanel(
            self._design,
            items_widget=items_widget,
            pattern_widget=pattern_widget,
            api=_ItemPanelAPI(self._settings_panel),
            on_drag_bar_changed=lambda vis: self._on_item_panel_drag_bar_changed(vis),
            items_panel_float=self._settings.items_panel_float,
            parent=central,
        )
        self._item_panel.items_panel_float_changed.connect(
            self._toggle_items_panel_float
        )
        self._item_panel.hide()  # restore で表示判定する
        # 移動バー表示状態の復元 (E: i294)
        if not self._settings.items_panel_drag_bar_visible:
            self._item_panel._drag_bar.setVisible(False)
        # geometry_changed 接続は _connect_panel_geometry_signals() で一括処理
        self._panels.append(self._item_panel)

    def _init_manage_panel(self, central: QWidget):
        """ManagePanel の生成・初期状態設定・追加ルーレット復元。"""
        # --- 全体管理パネル (F1) — 内部パネル ---
        self._manage_panel = ManagePanel(
            self._design,
            items_visible=self._settings.items_panel_visible,
            settings_visible=self._settings.settings_panel_visible,
            on_drag_bar_changed=lambda vis: self._on_manage_panel_drag_bar_changed(vis),
            roulette_only_show_selection_handle=self._settings.roulette_only_show_selection_handle,
            roulette_only_show_title_plate=self._settings.roulette_only_show_title_plate,
            roulette_only_show_graph_btn=self._settings.roulette_only_show_graph_btn,
            roulette_only_show_grip=self._settings.roulette_only_show_grip,
            roulette_only_show_log=self._settings.roulette_only_show_log,
            manage_panel_float=self._settings.manage_panel_float,
            parent=central,
        )

        self._connect_manage_panel_signals()

        # i279: 親 (centralWidget) が show されると child は既定で
        # visible になるため、ここで明示的に hide しておく。表示は
        # `_restore_all_panel_geometries` で manage_panel_visible に
        # 従って判断する。これを忘れると、保存値が False でも起動時に
        # 管理パネルだけが表示される不具合になる。
        self._manage_panel.hide()
        # 移動バー表示状態の復元 (E: i294)
        if not self._settings.manage_panel_drag_bar_visible:
            self._manage_panel._drag_bar.setVisible(False)
        self._manage_panel_visible = False
        # i333: 表示中のルーレット ID セット（デフォルトは "default" のみ）
        self._roulette_visible_ids: set[str] = {"default"}

        # i336: 追加ルーレットを config から復元（_roulette_visible_ids 初期化後に実行）
        self._roulette_saved_geometries: dict[str, tuple] = {}
        self._restore_extra_roulettes(central)

    def _connect_manage_panel_signals(self):
        """ManagePanel の全シグナルを接続する。"""
        self._manage_panel.items_panel_toggled.connect(
            self._on_manage_items_toggled
        )
        self._manage_panel.settings_panel_toggled.connect(
            self._on_manage_settings_toggled
        )
        self._manage_panel.reset_positions_requested.connect(
            self._reset_panel_positions
        )
        self._manage_panel.roulette_add_requested.connect(
            self._on_manage_roulette_add
        )
        self._manage_panel.roulette_activate_requested.connect(
            self._on_manage_roulette_activate
        )
        self._manage_panel.roulette_visibility_toggled.connect(
            self._on_manage_roulette_visibility
        )
        self._manage_panel.roulette_delete_requested.connect(
            self._on_manage_roulette_delete
        )
        self._manage_panel.apply_to_all_changed.connect(  # i347
            self._on_manage_apply_to_all_changed
        )
        self._manage_panel.roulette_pkg_export_requested.connect(  # i419
            self._on_roulette_pkg_export
        )
        self._manage_panel.roulette_pkg_import_requested.connect(  # i419
            self._on_roulette_pkg_import
        )
        self._manage_panel.roulette_only_hide_changed.connect(  # i463
            self._on_roulette_only_hide_changed
        )
        self._manage_panel.manage_panel_float_changed.connect(  # i465
            self._toggle_manage_panel_float
        )

    def _connect_panel_geometry_signals(self):
        """全パネルの geometry_changed と panel_save_timer を接続する。

        i318: ルーレットパネルは _create_roulette 時にタイマー未生成のため
        _init_settings_panel でタイマー生成後にここで接続する。
        全パネルの接続を一括管理することで接続漏れを防ぐ。
        """
        # roulette panel
        self._roulette_panel.geometry_changed.connect(self._panel_save_timer.start)
        # settings panel
        self._settings_panel.geometry_changed.connect(
            lambda: self._bring_panel_to_front(self._settings_panel)
        )
        self._settings_panel.geometry_changed.connect(self._panel_save_timer.start)
        # item panel
        self._item_panel.geometry_changed.connect(
            lambda: self._bring_panel_to_front(self._item_panel)
        )
        self._item_panel.geometry_changed.connect(self._panel_save_timer.start)
        # manage panel
        self._manage_panel.geometry_changed.connect(self._panel_save_timer.start)

    def _init_input_filters(self):
        """PanelInputFilter / SpaceSpinFilter を QApplication にインストール。"""
        # i278/i280: 統一マウスフィルタ (focus + drag + resize) を
        # QApplication 全体にインストール。
        # i280: ルーレットパネルは自前の mousePressEvent に内蔵の
        # ドラッグ/クリック判定があるため、フィルタの drag/focus 対象には
        # 含めない (focus_only_panels も空)。
        self._focused_panel = self._active_panel
        self._panel_input_filter = PanelInputFilter(self)
        self._panel_input_filter.set_panels(
            drag_panels=[
                self._settings_panel,
                self._item_panel,
                self._manage_panel,
            ],
            focus_only_panels=[],
        )
        QApplication.instance().installEventFilter(self._panel_input_filter)

        # i344: Space キー同時スピン用フィルタ（QApplication 全体にインストール）
        self._space_spin_filter = _SpaceSpinFilter(self)
        QApplication.instance().installEventFilter(self._space_spin_filter)

        # i462: Tab キーでルーレット以外非表示を切り替えるフィルタ
        self._tab_roulette_filter = _TabRouletteFilter(self)
        QApplication.instance().installEventFilter(self._tab_roulette_filter)

        # i346: 設定適用先（False = 選択中のみ / True = 全ルーレット）
        self._apply_to_all: bool = False

    def _init_runtime_state(self, central: QWidget):
        """panels_restored / 勝利数 / ドラッグ状態 / コンテキストメニュー / テーマタイマー / ドラッグバー。"""
        # i279: 復元は showEvent (初回) で行う。
        # __init__ 時点では centralWidget の layout が未活性で、stale な
        # 既定サイズ (640x480) を返すため、ユーザー保存値が小さく
        # クランプされる事故が起きていた。
        # ここでは復元せず、各パネルは hide() のままにしておく。
        self._panels_restored = False

        # --- 初期勝利数表示 ---
        self._update_win_counts()
        _init_rp_mgr = self._replay_mgrs.get(self._manager.active_id)
        self._settings_panel.set_replay_count(_init_rp_mgr.count() if _init_rp_mgr else 0)

        # --- ドラッグ・リサイズ状態 ---
        self._dragging_window = False
        self._window_drag_start = QPoint()
        self._window_drag_start_pos = QPoint()
        self._resizing_edge = self._EDGE_NONE
        self._resize_start = QPoint()
        self._resize_start_rect = QRect()

        # --- コンテキストメニュー ---
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # --- OS テーマ変更の定期監視 (system モード用) ---
        self._last_os_theme = resolve_theme_mode("system")
        self._os_theme_timer = QTimer(self)
        self._os_theme_timer.setInterval(3000)  # 3秒ごと
        self._os_theme_timer.timeout.connect(self._check_os_theme_change)
        if self._settings.theme_mode in ("system", "auto"):
            self._os_theme_timer.start()

        # --- メインウィンドウ移動バー ---
        # centralWidget の最前面に配置し、ドラッグでウィンドウ全体を移動する。
        self._mw_drag_bar = _MainWindowDragBar(self, self._design, parent=central)
        self._mw_drag_bar.setGeometry(0, 0, self.width(), _MainWindowDragBar._BAR_HEIGHT)
        self._mw_drag_bar.raise_()


