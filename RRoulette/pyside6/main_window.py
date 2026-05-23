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
from collections import deque

from app_constants import SIZE_PROFILES, MIN_W, MIN_H, VERSION
from design_models import (
    DesignSettings, DESIGN_PRESET_NAMES, DESIGN_PRESETS,
    DesignPresetManager, load_design,
)
from config_io import load_config
from segment_builder import build_segments_from_config
from item_data_io import load_all_item_entries, save_item_entries
from pattern_store import (
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
from ticket_panel import TicketPanel
from link_panel import LinkPanel
from external_listener import ExternalListener
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
from sequential_spin_mixin import SequentialSpinMixin
from log_shuffle_mixin import LogShuffleMixin
from settings_io_mixin import SettingsIOMixin
from package_io_mixin import PackageIOMixin
from ui_toggle_mixin import UIToggleMixin
from context_menu_mixin import ContextMenuMixin
from window_frame_mixin import WindowFrameMixin
from action_dispatch_mixin import ActionDispatchMixin
from save_load_mixin import SaveLoadMixin
from accessor_helper_mixin import AccessorHelperMixin
from main_window_helpers import _SpaceSpinFilter, _TabRouletteFilter, _MainWindowDragBar, _IdleResetFilter

import logging
_log = logging.getLogger(__name__)

_LINK_SPIN_QUEUE_MAX = 10  # i114: 連携スピンキューの最大件数



class MainWindow(AccessorHelperMixin, SaveLoadMixin, ActionDispatchMixin, WindowFrameMixin, ContextMenuMixin, UIToggleMixin, PackageIOMixin, SettingsIOMixin, LogShuffleMixin, MacroFlowMixin, SequentialSpinMixin, DesignGraphMixin, ReplayManagementMixin, PatternManagementMixin, ItemEntriesMixin, SettingsDispatchMixin, SpinFlowMixin, RouletteLifecycleMixin, PanelGeometryMixin, QMainWindow):
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
    _EDGE_LEFT = 4   # i099: 左エッジ
    _EDGE_TOP = 8    # i099: 上エッジ

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
        self._init_ticket_panel(central)
        self._init_link_panel(central)
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
        self._settings = AppSettings.load(self._config)
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
        self._sound.set_effect_volume(self._settings.effect_volume / 100.0)
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
        self._settings_panel.preview_effect_requested.connect(self._on_preview_effect)
        self._settings_panel.preview_full_effect_requested.connect(self._on_preview_full_effect)
        # v0.6.1: 主要セクションの「初期化」要求
        self._settings_panel.section_reset_requested.connect(self._on_section_reset_requested)
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
            ticket_visible=self._settings.ticket_panel_visible,
            seq_visible=False,  # i051: seq dialog は起動時常に非表示
            on_drag_bar_changed=lambda vis: self._on_manage_panel_drag_bar_changed(vis),
            roulette_only_show_selection_handle=self._settings.roulette_only_show_selection_handle,
            roulette_only_show_title_plate=self._settings.roulette_only_show_title_plate,
            roulette_only_show_graph_btn=self._settings.roulette_only_show_graph_btn,
            roulette_only_show_grip=self._settings.roulette_only_show_grip,
            roulette_only_show_log=self._settings.roulette_only_show_log,
            roulette_only_show_manage_panel=self._settings.roulette_only_show_manage_panel,
            roulette_only_show_items_panel=self._settings.roulette_only_show_items_panel,
            roulette_only_show_settings_panel=self._settings.roulette_only_show_settings_panel,
            roulette_only_show_execution_panel=self._settings.roulette_only_show_execution_panel,
            roulette_only_show_ticket_panel=self._settings.roulette_only_show_ticket_panel,
            link_visible=self._settings.link_panel_visible,
            roulette_only_show_link_panel=self._settings.roulette_only_show_link_panel,
            manage_panel_float=self._settings.manage_panel_float,
            auto_hide_enabled=self._settings.auto_hide_enabled,
            auto_hide_seconds=self._settings.auto_hide_seconds,
            auto_hide_fade_enabled=self._settings.auto_hide_fade_enabled,
            auto_hide_fade_seconds=self._settings.auto_hide_fade_seconds,
            auto_hide_only_in_roulette_only_mode=self._settings.auto_hide_only_in_roulette_only_mode,
            auto_hide_after_spin_after_restore=self._settings.auto_hide_after_spin_after_restore,
            link_integration_enabled=self._settings.link_integration_enabled,
            link_integration_port=self._settings.link_integration_port,
            link_integration_max_hold=self._settings.link_integration_max_hold,
            link_panel_show_time=self._settings.link_panel_show_time,
            settings=self._settings,
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

    def _init_ticket_panel(self, central: QWidget):
        """TicketPanel の生成・初期状態設定・パネル一覧への追加 (i050)。"""
        self._ticket_panel = TicketPanel(
            self._design,
            on_drag_bar_changed=lambda vis: self._on_ticket_panel_drag_bar_changed(vis),
            parent=central,
        )
        self._ticket_panel.hide()
        if not self._settings.ticket_panel_drag_bar_visible:
            self._ticket_panel._drag_bar.setVisible(False)
        # 初期データ: active roulette のチケットデータをセット
        ctx = self._active_context
        self._ticket_panel.set_active_data(
            self._manager.active_id,
            list(ctx.ticket_holdings),
            list(ctx.ticket_history),
            list(ctx.ticket_templates),
        )
        self._ticket_panel.data_changed.connect(self._on_ticket_data_changed)
        # i069: pointer_move チケット使用要求
        self._ticket_panel.pointer_move_requested.connect(self._on_pointer_move_requested)
        # i076: set_item_enabled チケット使用要求
        # i076/i077: set_item_enabled チケット使用要求（使用時選択型）
        self._ticket_panel.set_item_enabled_requested.connect(self._on_set_item_enabled_requested)
        # i086: set_weight チケット使用要求（使用時選択型）
        self._ticket_panel.set_item_weight_requested.connect(self._on_set_item_weight_requested)
        # i087: 確率指定系チケット使用要求（使用時選択型）
        self._ticket_panel.set_prob_effect_requested.connect(self._on_set_prob_effect_requested)
        self._panels.append(self._ticket_panel)

    def _on_ticket_panel_drag_bar_changed(self, vis: bool):
        self._settings.ticket_panel_drag_bar_visible = vis
        self._save_config()

    def _init_link_panel(self, central: QWidget):
        """LinkPanel の生成・初期化・外部連携リスナー起動 (Phase 1/2)。"""
        self._link_panel = LinkPanel(
            self._design,
            max_hold=self._settings.link_integration_max_hold,
            show_time=self._settings.link_panel_show_time,
            auto_analyze=self._settings.link_auto_analyze,
            auto_execute=self._settings.link_auto_execute,
            on_drag_bar_changed=lambda vis: self._on_link_panel_drag_bar_changed(vis),
            parent=central,
        )
        self._link_panel.hide()
        if not self._settings.link_panel_drag_bar_visible:
            self._link_panel._drag_bar.setVisible(False)
        self._panels.append(self._link_panel)

        # i109: シグナル接続
        self._link_panel.spin_requested.connect(self._on_link_spin_requested)
        self._link_panel.ticket_add_requested.connect(self._on_link_ticket_add_requested)
        self._link_panel.auto_analyze_changed.connect(self._on_link_auto_analyze_changed)
        self._link_panel.auto_execute_changed.connect(self._on_link_auto_execute_changed)
        # i114: 連携スピンキュー
        self._link_spin_queue: deque[int] = deque()
        self._link_panel.queue_clear_requested.connect(self._on_link_queue_clear)

        # 外部連携リスナー
        self._external_listener = ExternalListener(self)
        self._external_listener.message_received.connect(self._on_link_message_received)
        self._external_listener.status_changed.connect(self._on_link_listener_status_changed)
        if self._settings.link_integration_enabled:
            ok = self._external_listener.start(self._settings.link_integration_port)
            if not ok:
                import logging
                logging.getLogger(__name__).warning(
                    "ExternalListener: failed to start on port %d",
                    self._settings.link_integration_port,
                )

    def _apply_link_listener(self):
        """設定変更時: リスナーを停止→必要なら再起動する。"""
        import logging
        _log = logging.getLogger(__name__)
        if self._external_listener.is_running:
            self._external_listener.stop()
        if self._settings.link_integration_enabled:
            ok = self._external_listener.start(self._settings.link_integration_port)
            if not ok:
                _log.warning(
                    "ExternalListener: failed to restart on port %d",
                    self._settings.link_integration_port,
                )

    def _on_link_listener_status_changed(self, status: str):
        """リスナー状態変化を管理パネルの状態ラベルへ反映する (i099)。"""
        _mp = getattr(self, "_manage_panel", None)
        if _mp is not None:
            _mp.set_link_listener_status(status)

    def _on_manage_link_enabled_changed(self, enabled: bool):
        """ManagePanel から: 連携受信 ON/OFF を切り替える (i099)。"""
        self._settings.link_integration_enabled = enabled
        self._apply_link_listener()
        self._save_config()

    def _on_manage_link_port_changed(self, port: int):
        """ManagePanel から: 連携受信ポートを変更する (i099)。"""
        self._settings.link_integration_port = port
        self._apply_link_listener()
        self._save_config()

    def _on_manage_link_max_hold_changed(self, max_hold: int):
        """ManagePanel から: 連携メッセージ保持件数を変更する (i099)。"""
        self._settings.link_integration_max_hold = max_hold
        _lp = getattr(self, "_link_panel", None)
        if _lp is not None:
            _lp.set_max_hold(max_hold)
        self._save_config()

    def _on_manage_link_show_time_changed(self, show: bool):
        """ManagePanel から: 連携パネル時刻列表示を切り替える (i100)。"""
        self._settings.link_panel_show_time = show
        _lp = getattr(self, "_link_panel", None)
        if _lp is not None:
            _lp.set_show_time(show)
        self._save_config()

    def _on_link_panel_drag_bar_changed(self, vis: bool):
        self._settings.link_panel_drag_bar_visible = vis
        self._save_config()

    def _on_link_message_received(self, data: dict):
        """外部連携メッセージを受信したとき link_panel へ追加する。"""
        self._link_panel.add_message(data)
        # link_panel が非表示なら表示する（オプション: 非表示のまま蓄積）
        # Phase 1: 表示状態に関わらず蓄積のみ行う（表示は手動）

    # ── i109: 連携パネル Phase 2 シグナルハンドラ ───────────────────────

    def _link_spin_is_busy(self) -> bool:
        """アクティブルーレットがスピン中かどうかを返す (i114)。"""
        mgr = getattr(self, '_manager', None)
        ctx = mgr.active if mgr else None
        sc  = getattr(getattr(ctx, 'panel', None), 'spin_ctrl', None)
        return bool(sc and sc.is_spinning)

    def _on_link_spin_requested(self, row: int) -> None:
        """連携パネルから spin 要求を受け取る (i109/i114)。キューで管理する。"""
        panel = self._link_panel
        # v0.6.1: 連携メッセージから投稿者名を取得して保持
        # （結果オーバーレイで「投稿者: xxx」として表示するため）
        author = self._fetch_link_author(row)
        if not self._link_spin_is_busy():
            # スピン中でなければ即実行
            # _start_spin が冒頭で result_overlay の link_author をクリアするため、
            # クリアの後に再セットする順序にする
            self._start_spin()
            self._apply_link_author_to_active(author)
            panel.set_row_status(row, "実行済")
            return
        # スピン中: キュー追加
        if len(self._link_spin_queue) >= _LINK_SPIN_QUEUE_MAX:
            panel.set_row_status(row, "未実行: キュー満杯")
            _log.warning("[MainWindow] link spin queue full, dropping row=%d", row)
            return
        # v0.6.1: キューイング時は author も併せて保存
        self._link_spin_queue.append((row, author))
        panel.set_row_status(row, "キュー待ち")
        panel.update_queue_display(len(self._link_spin_queue))
        _log.info("[MainWindow] link spin queued row=%d, queue_len=%d",
                  row, len(self._link_spin_queue))

    def _fetch_link_author(self, row: int) -> str:
        """v0.6.1: 連携パネルテーブルの指定行から投稿者名を取得する。"""
        try:
            from link_panel import _COL_AUTHOR
            tbl = getattr(self._link_panel, "_table", None)
            if tbl is None:
                return ""
            item = tbl.item(row, _COL_AUTHOR)
            return item.text().strip() if item is not None else ""
        except Exception:
            return ""

    def _apply_link_author_to_active(self, author: str) -> None:
        """v0.6.1: 取得した連携投稿者名を active panel の result_overlay へ設定する。
        次のスピン結果表示で「投稿者: xxx」として併記される。"""
        try:
            ctx = self._active_context
            if ctx is not None and ctx.panel is not None:
                ctx.panel.result_overlay.set_link_author(author)
        except Exception:
            pass

    def _process_link_spin_queue(self) -> None:
        """スピン完了後に連携スピンキューの次の要求を処理する (i114)。"""
        if not self._link_spin_queue:
            return
        if self._link_spin_is_busy():
            return
        # v0.6.1: キュー要素は (row, author) のタプル
        item = self._link_spin_queue.popleft()
        if isinstance(item, tuple):
            row, author = item
        else:
            row, author = int(item), ""
        self._link_panel.update_queue_display(len(self._link_spin_queue))
        self._start_spin()
        self._apply_link_author_to_active(author)
        self._link_panel.set_row_status(row, "実行済")
        _log.info("[MainWindow] link spin queue processed row=%d, remaining=%d",
                  row, len(self._link_spin_queue))

    def _on_link_queue_clear(self) -> None:
        """連携スピンキューをクリアする (i114)。"""
        count = len(self._link_spin_queue)
        self._link_spin_queue.clear()
        self._link_panel.update_queue_display(0)
        _log.info("[MainWindow] link spin queue cleared (%d items)", count)

    def _on_link_ticket_add_requested(
        self,
        name: str,
        issuer: str,
        effect: str,
        qty: int,
        effect_type: str,
        effect_params: dict,
    ) -> None:
        """連携パネルからチケット追加要求を受け取る (i109)。"""
        _tp = getattr(self, "_ticket_panel", None)
        if _tp is not None:
            _tp.add_ticket_from_link(
                name, issuer, effect, qty,
                effect_type=effect_type,
                effect_params=effect_params,
            )

    def _on_link_auto_analyze_changed(self, enabled: bool) -> None:
        """連携パネルの自動解析 ON/OFF 変更を設定に保存する (i109)。"""
        self._settings.link_auto_analyze = enabled
        self._save_config()

    def _on_link_auto_execute_changed(self, enabled: bool) -> None:
        """連携パネルの自動実行 ON/OFF 変更を設定に保存する (i109)。"""
        self._settings.link_auto_execute = enabled
        self._save_config()

    def _toggle_link_panel(self):
        """F6: 連携パネルの表示 / 非表示。"""
        new_visible = not self._link_panel.isVisible()
        if new_visible:
            self._link_panel.show()
            self._link_panel.raise_()
        else:
            self._link_panel.hide()
        self._settings.link_panel_visible = new_visible
        self._sync_manage_panel_checks()
        self._save_config()

    def _on_manage_link_toggled(self, visible: bool):
        """ManagePanel から: 連携パネルの表示状態を切り替える。"""
        if visible:
            self._link_panel.show()
            self._link_panel.raise_()
        else:
            self._link_panel.hide()
        self._settings.link_panel_visible = visible
        self._sync_manage_panel_checks()
        self._save_config()

    def _on_ticket_data_changed(self):
        """チケットパネルのデータが変わったとき、active context に反映して保存。"""
        rid = self._manager.active_id
        ctx = self._manager.get(rid)
        if ctx is not None:
            ctx.ticket_holdings  = self._ticket_panel.get_current_holdings()
            ctx.ticket_history   = self._ticket_panel.get_current_history()
            ctx.ticket_templates = self._ticket_panel.get_current_templates()
        self._save_config()

    def _on_pointer_move_committed(self, roulette_id: str, winner: str) -> None:
        """pointer_move drag release 時に記録済みの winner を差し替え、成功/ドブ選択を出す (i070/i071/i072)。

        i071: 即時記録済みの old_winner と異なる場合のみ、
        win_history / wheel log / 勝利数表示を書き換える。
        i072: 差し替え後に成功/ドブ選択オーバーレイを表示する。
        """
        if not hasattr(self, '_pending_spin_results'):
            return
        pending = self._pending_spin_results.get(roulette_id)
        if pending is None:
            return
        old_winner = pending["winner"]

        pattern_id    = pending["pattern_id"]
        rid           = roulette_id or "default"
        win_record_id = pending.get("win_record_id", "")
        ctx           = pending["ctx"]

        if winner != old_winner:
            # win_history を差し替える
            if win_record_id:
                self._win_history.replace_record_text(win_record_id, winner)
            self._win_history.save()

            # wheel ログを差し替える
            if ctx:
                ctx.panel.wheel.replace_log_entry(old_winner, pattern_id, winner)
                ctx.panel.wheel.save_log(self._roulette_log_path(roulette_id))

            # 当選回数表示を更新
            self._update_win_counts()

            # pending の winner も更新（2回目 commit 防止）
            pending["winner"] = winner
            print(f"[dev] pointer_move committed: '{old_winner}' → '{winner}'")
        else:
            print(f"[dev] pointer_move committed: same winner '{winner}', no rewrite")

        # i073: 成功/ドブ選択オーバーレイを TicketPanel 上に表示（800ms 後）
        ticket_info = pending.get("pm_ticket_info")
        if ticket_info:
            _name   = ticket_info.get("name", "")
            _issuer = ticket_info.get("issuer", "")
            _effect = ticket_info.get("effect", "")
            QTimer.singleShot(800, lambda: self._ticket_panel.show_pointer_move_result_selection(
                _name, _issuer, _effect
            ))

    def _on_pointer_move_requested(self, roulette_id: str, max_deg: float,
                                    name: str, issuer: str, effect: str,
                                    ticket_id: str = "") -> None:
        """TicketPanel から pointer_move チケット使用要求を受け取る (i069/i070)。

        使用条件:
          - 対象ルーレットが結果表示中（暫定結果あり）
          - まだポインター操作モードに入っていない
          - この結果表示に対して pending result が存在する
        """
        ctx = self._manager.get(roulette_id) if roulette_id else self._manager.active
        if ctx is None:
            return
        panel = ctx.panel
        # 結果表示中かチェック
        if not panel.result_overlay.isVisible():
            return
        # 既にポインター操作モード中なら拒否
        if panel.pointer_move_mode_active:
            return
        # pending result が存在するかチェック（seq スピン中は対象外）
        pending_key = roulette_id
        if not hasattr(self, '_pending_spin_results'):
            return
        if pending_key not in self._pending_spin_results:
            return
        # i070: ticket_id も渡してチケットを消費（同名チケット識別）
        # i072: 履歴は drag release + 成功/ドブ選択後に finalize_pointer_move_ticket() で記録
        self._ticket_panel.consume_ticket_pointer_move(name, issuer, effect,
                                                       ticket_id=ticket_id)
        # i072: pending dict にチケット情報を保存（成功/ドブ選択時に使用）
        pending = self._pending_spin_results.get(pending_key)
        if pending is not None:
            pending["pm_ticket_info"] = {
                "name": name, "issuer": issuer, "effect": effect,
            }
        # ポインター操作モードへ移行
        panel.enter_pointer_move_mode(max_deg)
        print(f"[dev] pointer_move mode entered: roulette='{roulette_id}', max_deg={max_deg}")

    def _on_set_item_enabled_requested(self, roulette_id: str, name: str,
                                        issuer: str, effect: str,
                                        ticket_id: str) -> None:
        """set_item_enabled チケット使用要求を処理する (i076/i077)。

        i077: 使用時選択型。対象項目はこのメソッド内で OBS 可視オーバーレイを経由して選ぶ。

        事前バリデーション:
          - 有効項目が 1 件以下 → チケット不消費・警告
        選択後バリデーション（on_selected 内）:
          - 対象項目が見つからない → 中断（チケット消費済みを避けるため消費前に選択させる）
          - OFF にして有効項目 0 件になる → 中断
        適用先は常に active roulette / current pattern のみ。
        """
        from PySide6.QtWidgets import QMessageBox as _QMB
        ctx = self._manager.get(roulette_id) if roulette_id else self._manager.active
        if ctx is None:
            return
        if ctx is not self._manager.active:
            _QMB.warning(self, "チケット適用エラー",
                         "非アクティブなルーレットには適用できません。\nチケットは消費されません。")
            return

        # 現在 enabled の項目のみを候補とする（使用時点の最新状態）
        enabled_entries = [(e.item_id, e.text) for e in ctx.item_entries if e.enabled]
        if len(enabled_entries) <= 1:
            _QMB.warning(self, "チケット適用エラー",
                         "有効項目が1件以下のため非表示にできません。\nチケットは消費されません。")
            print(f"[dev] set_item_enabled: enabled_count={len(enabled_entries)}, aborted")
            return

        # 選択後コールバック
        def on_selected(item_id: str) -> None:
            # 選択時点でも ctx / entry を再取得（状態変化に対する保険）
            ctx2 = self._manager.get(roulette_id) if roulette_id else self._manager.active
            if ctx2 is None or ctx2 is not self._manager.active:
                return
            entries = ctx2.item_entries
            target_idx = next(
                (i for i, e in enumerate(entries) if e.item_id == item_id), None
            )
            if target_idx is None:
                print(f"[dev] set_item_enabled: item_id={item_id!r} not found at apply time")
                return
            # OFF にして有効項目が 0 件にならないか確認
            if entries[target_idx].enabled:
                enabled_count = sum(1 for e in entries if e.enabled)
                if enabled_count <= 1:
                    print(f"[dev] set_item_enabled: would zero out enabled items, aborted")
                    return
            # チケット消費（バリデーション通過後に消費）
            # i083: 使用時に選んだ項目名を渡して履歴詳細に記録
            if not self._ticket_panel.consume_ticket_set_item_enabled(
                    name, issuer, effect, ticket_id=ticket_id,
                    target_item_text=entries[target_idx].text):
                return
            # i079: 一時非表示（永続変更ではない）
            entries[target_idx].enabled = False
            rid = roulette_id or self._manager.active_id
            self._update_items_by_action(rid, list(entries))
            # 項目リスト UI への即時反映
            self._settings_panel.set_active_entries(list(ctx2.item_entries))
            if hasattr(self, "_item_panel"):
                self._item_panel._refresh_simple_list()
            print(f"[dev] set_item_enabled: temp OFF item_id={item_id!r}, "
                  f"text='{entries[target_idx].text}'")

            # i079: 結果表示が消えたタイミングで元の ON 状態へ自動復帰
            result_ov = ctx2.panel.result_overlay

            def _on_result_closed():
                # 一度だけ実行・切断
                try:
                    result_ov.closed.disconnect(_on_result_closed)
                except Exception:
                    pass
                ctx3 = self._manager.get(rid)
                if ctx3 is None:
                    return
                entries3 = ctx3.item_entries
                target3 = next((e for e in entries3 if e.item_id == item_id), None)
                if target3 is None:
                    print(f"[dev] set_item_enabled restore: item_id={item_id!r} not found")
                    return
                target3.enabled = True
                self._update_items_by_action(rid, list(entries3))
                self._settings_panel.set_active_entries(list(ctx3.item_entries))
                if hasattr(self, "_item_panel"):
                    self._item_panel._refresh_simple_list()
                print(f"[dev] set_item_enabled restore: ON restored item_id={item_id!r}")

            result_ov.closed.connect(_on_result_closed)

        def on_cancelled() -> None:
            print("[dev] set_item_enabled: cancelled, ticket not consumed")

        # OBS 可視の選択オーバーレイを表示（チケット消費はキャンセル不可の選択後）
        self._ticket_panel.show_item_hide_select_overlay(
            enabled_entries, on_selected, on_cancelled
        )

    def _on_set_item_weight_requested(self, roulette_id: str, name: str,
                                       issuer: str, effect: str,
                                       ticket_id: str) -> None:
        """set_weight チケット使用要求を処理する (i086)。

        使用時選択型。対象項目はこのメソッド内で OBS 可視オーバーレイを経由して選ぶ。
        係数値はチケットの effect_params["weight_value"] から取得する。

        事前バリデーション:
          - 有効項目が存在しない → チケット不消費・警告
          - 係数値が現在の有効項目数ルール上で不正 → チケット不消費・警告
        適用先は常に active roulette / current pattern のみ。
        効果は一時上書き（結果表示が消えたら元に戻す）。
        """
        from PySide6.QtWidgets import QMessageBox as _QMB
        ctx = self._manager.get(roulette_id) if roulette_id else self._manager.active
        if ctx is None:
            return
        if ctx is not self._manager.active:
            _QMB.warning(self, "チケット適用エラー",
                         "非アクティブなルーレットには適用できません。\nチケットは消費されません。")
            return

        # チケットの effect_params から係数値を取得
        holdings = self._ticket_panel.get_current_holdings()
        h_match = next(
            (h for h in holdings
             if (ticket_id and h.get("ticket_id") == ticket_id)
             or (not ticket_id and h.get("ticket_name") == name
                 and h.get("issuer") == issuer and h.get("effect") == effect)),
            {}
        )
        weight_value = float(h_match.get("effect_params", {}).get("weight_value", 1.0))

        # 現在 enabled の項目のみを候補とする
        enabled_entries = [e for e in ctx.item_entries if e.enabled]
        n = len(enabled_entries)
        if n == 0:
            _QMB.warning(self, "チケット適用エラー",
                         "有効項目がありません。\nチケットは消費されません。")
            print(f"[dev] set_weight: no enabled items, aborted")
            return

        # 係数値が現在の有効項目数に対して有効範囲かチェック
        # _build_weight_candidates(n) の最大値は n なので weight_value > n は範囲外
        if weight_value > n:
            _QMB.warning(self, "チケット適用エラー",
                         f"指定された係数 ×{weight_value:g} は現在の有効項目数 {n} に対して"
                         f"適用できません（最大 ×{n:g}）。\nチケットは消費されません。")
            print(f"[dev] set_weight: weight_value={weight_value} > n={n}, aborted")
            return

        # 表示テキスト生成（項目名 / 現在係数 / 現在確率）
        from settings_panel_items import _calc_item_probs
        probs = _calc_item_probs(ctx.item_entries)
        all_entries = ctx.item_entries
        items_for_overlay: list[tuple[str, str]] = []
        for e in enabled_entries:
            gi = next((i for i, x in enumerate(all_entries) if x.item_id == e.item_id), None)
            if gi is None:
                continue
            prob = probs[gi]
            prob_str = f"{prob:.1f}%" if prob is not None else "—"
            if e.prob_mode == "weight" and e.prob_value is not None:
                w_str = f"×{e.prob_value:g}"
            elif e.prob_mode == "fixed":
                w_str = f"固定 {e.prob_value:g}%"
            else:
                w_str = "×1"
            display = f"{e.text}  /  係数 {w_str}  /  {prob_str}"
            items_for_overlay.append((e.item_id, display))

        # 選択後コールバック
        def on_selected(item_id: str) -> None:
            ctx2 = self._manager.get(roulette_id) if roulette_id else self._manager.active
            if ctx2 is None or ctx2 is not self._manager.active:
                return
            entries = ctx2.item_entries
            target_idx = next(
                (i for i, e in enumerate(entries) if e.item_id == item_id), None
            )
            if target_idx is None:
                print(f"[dev] set_weight: item_id={item_id!r} not found at apply time")
                return

            # チケット消費（バリデーション通過後）
            target_text = entries[target_idx].text
            if not self._ticket_panel.consume_ticket_set_weight(
                    name, issuer, effect, ticket_id=ticket_id):
                return

            # 元の prob_mode / prob_value を保存してから一時上書き
            orig_mode = entries[target_idx].prob_mode
            orig_value = entries[target_idx].prob_value

            entries[target_idx].prob_mode = "weight"
            entries[target_idx].prob_value = weight_value

            rid = roulette_id or self._manager.active_id
            self._update_items_by_action(rid, list(entries))
            # 項目リスト UI への即時反映
            self._settings_panel.set_active_entries(list(ctx2.item_entries))
            if hasattr(self, "_item_panel"):
                self._item_panel._refresh_simple_list()
            print(f"[dev] set_weight: temp weight ×{weight_value:g} applied to item_id={item_id!r}, "
                  f"text='{target_text}'")

            # 結果表示が消えたタイミングで元の状態へ自動復帰
            result_ov = ctx2.panel.result_overlay
            eparams_hist = {"weight_value": weight_value, "target_item": target_text}

            def _on_result_closed():
                try:
                    result_ov.closed.disconnect(_on_result_closed)
                except Exception:
                    pass
                ctx3 = self._manager.get(rid)
                if ctx3 is None:
                    return
                entries3 = ctx3.item_entries
                target3 = next((e for e in entries3 if e.item_id == item_id), None)
                if target3 is None:
                    # i088: リセット等で item_id が消えた場合は結果不明で記録
                    print(f"[dev] set_weight restore: item_id={item_id!r} not found after reset")
                    self._ticket_panel.finalize_ticket_with_result(
                        name, issuer, effect, "none",
                        effect_type="set_weight", effect_params=eparams_hist)
                    return
                target3.prob_mode = orig_mode
                target3.prob_value = orig_value
                self._update_items_by_action(rid, list(entries3))
                self._settings_panel.set_active_entries(list(ctx3.item_entries))
                if hasattr(self, "_item_panel"):
                    self._item_panel._refresh_simple_list()
                print(f"[dev] set_weight restore: item_id={item_id!r} reverted to "
                      f"mode={orig_mode!r}, value={orig_value!r}")
                # i088: 結果選択オーバーレイを表示して成功 / ドブを記録
                def _on_chosen(value: str) -> None:
                    result_val = value if value != "__cancel__" else "none"
                    self._ticket_panel.finalize_ticket_with_result(
                        name, issuer, effect, result_val,
                        effect_type="set_weight", effect_params=eparams_hist)
                self._ticket_panel.show_result_selection_overlay(name, effect, _on_chosen)

            result_ov.closed.connect(_on_result_closed)

        def on_cancelled() -> None:
            print("[dev] set_weight: cancelled, ticket not consumed")

        # OBS 可視の選択オーバーレイを表示（チケット消費はキャンセル不可の選択後）
        self._ticket_panel.show_weight_select_overlay(
            weight_value, items_for_overlay, on_selected, on_cancelled
        )

    def _on_set_prob_effect_requested(self, roulette_id: str, name: str,
                                       issuer: str, effect: str,
                                       ticket_id: str) -> None:
        """固定確率指定・追加確率指定チケット使用要求を処理する (i087)。

        effect_type（"set_fixed_prob" / "add_prob"）は holdings の effect_params から取得。
        使用時選択型。対象項目はこのメソッド内で OBS 可視オーバーレイを経由して選ぶ。

        固定確率指定:
          - prob_value をそのまま固定確率として適用。
        追加確率指定:
          - 使用時点の現在確率に prob_value を加算して固定確率として適用。

        バリデーション（非消費条件）:
          - 有効項目が存在しない
          - 適用後確率が 0% 以下または 100% 以上
          - 他 ON 項目の固定確率合計 + 適用後確率 >= 100%（残余不足）
          - キャンセル
        """
        from PySide6.QtWidgets import QMessageBox as _QMB
        ctx = self._manager.get(roulette_id) if roulette_id else self._manager.active
        if ctx is None:
            return
        if ctx is not self._manager.active:
            _QMB.warning(self, "チケット適用エラー",
                         "非アクティブなルーレットには適用できません。\nチケットは消費されません。")
            return

        # チケットの effect_type と prob_value を取得
        holdings = self._ticket_panel.get_current_holdings()
        h_match = next(
            (h for h in holdings
             if (ticket_id and h.get("ticket_id") == ticket_id)
             or (not ticket_id and h.get("ticket_name") == name
                 and h.get("issuer") == issuer and h.get("effect") == effect)),
            {}
        )
        effect_type = h_match.get("effect_type", "")
        prob_value = float(h_match.get("effect_params", {}).get("prob_value", 10.0))

        # 有効項目チェック
        enabled_entries = [e for e in ctx.item_entries if e.enabled]
        if not enabled_entries:
            _QMB.warning(self, "チケット適用エラー",
                         "有効項目がありません。\nチケットは消費されません。")
            return

        # 表示テキスト生成（項目名 / 現在係数 / 現在確率）
        from settings_panel_items import _calc_item_probs
        all_entries = ctx.item_entries
        probs = _calc_item_probs(all_entries)
        items_for_overlay: list[tuple[str, str]] = []
        for e in enabled_entries:
            gi = next((i for i, x in enumerate(all_entries) if x.item_id == e.item_id), None)
            if gi is None:
                continue
            prob = probs[gi]
            prob_str = f"{prob:.1f}%" if prob is not None else "—"
            if e.prob_mode == "weight" and e.prob_value is not None:
                w_str = f"×{e.prob_value:g}"
            elif e.prob_mode == "fixed":
                w_str = f"固定 {e.prob_value:g}%"
            else:
                w_str = "×1"
            display = f"{e.text}  /  係数 {w_str}  /  {prob_str}"
            items_for_overlay.append((e.item_id, display))

        # ダイアログタイトル
        if effect_type == "set_fixed_prob":
            dialog_title = f"固定確率 {prob_value:g}% を適用する項目を選んでください"
        else:
            dialog_title = f"確率 +{prob_value:g}% を加算する項目を選んでください"

        def on_selected(item_id: str) -> None:
            ctx2 = self._manager.get(roulette_id) if roulette_id else self._manager.active
            if ctx2 is None or ctx2 is not self._manager.active:
                return
            entries = ctx2.item_entries
            target_idx = next(
                (i for i, e in enumerate(entries) if e.item_id == item_id), None
            )
            if target_idx is None:
                print(f"[dev] set_prob: item_id={item_id!r} not found at apply time")
                return

            # 現在確率の再取得（選択時点）
            probs2 = _calc_item_probs(entries)
            gi2 = target_idx
            current_prob = probs2[gi2] if probs2[gi2] is not None else 0.0

            # 適用後確率の決定
            if effect_type == "set_fixed_prob":
                applied_prob = prob_value
            else:
                applied_prob = round(current_prob + prob_value, 1)

            # バリデーション
            if applied_prob <= 0.0 or applied_prob >= 100.0:
                _QMB.warning(self, "チケット適用エラー",
                             f"適用後の確率 {applied_prob:.1f}% は無効です（0%〜100%の範囲外）。\n"
                             "チケットは消費されません。")
                return

            # 他 ON 固定確率の合計（対象項目が固定確率なら除外して計算）
            other_fixed_sum = sum(
                e.prob_value for e in entries
                if e.enabled and e.item_id != item_id and e.prob_mode == "fixed"
                and e.prob_value is not None
            )
            other_weight_count = sum(
                1 for e in entries
                if e.enabled and e.item_id != item_id and e.prob_mode != "fixed"
            )
            # other_fixed_sum + applied_prob が 100 以上だと残余不足（weight 項目がある場合）
            # または全て固定でも合計超過
            if other_weight_count > 0 and other_fixed_sum + applied_prob >= 100.0:
                _QMB.warning(self, "チケット適用エラー",
                             f"他の固定確率の合計 {other_fixed_sum:.1f}% に "
                             f"{applied_prob:.1f}% を加えると残余確率が不足します。\n"
                             "チケットは消費されません。")
                return
            if other_weight_count == 0 and other_fixed_sum + applied_prob > 100.0:
                _QMB.warning(self, "チケット適用エラー",
                             f"確率の合計が 100% を超えます "
                             f"（他固定 {other_fixed_sum:.1f}% + 適用 {applied_prob:.1f}%）。\n"
                             "チケットは消費されません。")
                return

            # チケット消費
            target_text = entries[target_idx].text
            if not self._ticket_panel.consume_ticket_set_prob(
                    name, issuer, effect, ticket_id=ticket_id):
                return

            # 元の prob_mode / prob_value を保存して一時上書き
            orig_mode = entries[target_idx].prob_mode
            orig_value = entries[target_idx].prob_value

            entries[target_idx].prob_mode = "fixed"
            entries[target_idx].prob_value = applied_prob

            rid = roulette_id or self._manager.active_id
            self._update_items_by_action(rid, list(entries))
            self._settings_panel.set_active_entries(list(ctx2.item_entries))
            if hasattr(self, "_item_panel"):
                self._item_panel._refresh_simple_list()
            print(f"[dev] set_prob({effect_type}): applied_prob={applied_prob:.1f}% to "
                  f"item_id={item_id!r}, text='{target_text}'")

            # 結果表示が消えたタイミングで自動復帰
            result_ov = ctx2.panel.result_overlay
            eparams_hist = {
                "prob_value": prob_value,
                "target_item": target_text,
                "applied_prob": applied_prob,
            }

            def _on_result_closed():
                try:
                    result_ov.closed.disconnect(_on_result_closed)
                except Exception:
                    pass
                ctx3 = self._manager.get(rid)
                if ctx3 is None:
                    return
                entries3 = ctx3.item_entries
                target3 = next((e for e in entries3 if e.item_id == item_id), None)
                if target3 is None:
                    # i088: リセット等で item_id が消えた場合は結果不明で記録
                    print(f"[dev] set_prob restore: item_id={item_id!r} not found after reset")
                    self._ticket_panel.finalize_ticket_with_result(
                        name, issuer, effect, "none",
                        effect_type=effect_type, effect_params=eparams_hist)
                    return
                target3.prob_mode = orig_mode
                target3.prob_value = orig_value
                self._update_items_by_action(rid, list(entries3))
                self._settings_panel.set_active_entries(list(ctx3.item_entries))
                if hasattr(self, "_item_panel"):
                    self._item_panel._refresh_simple_list()
                print(f"[dev] set_prob restore: item_id={item_id!r} reverted to "
                      f"mode={orig_mode!r}, value={orig_value!r}")
                # i088: 結果選択オーバーレイを表示して成功 / ドブを記録
                def _on_chosen(value: str) -> None:
                    result_val = value if value != "__cancel__" else "none"
                    self._ticket_panel.finalize_ticket_with_result(
                        name, issuer, effect, result_val,
                        effect_type=effect_type, effect_params=eparams_hist)
                self._ticket_panel.show_result_selection_overlay(name, effect, _on_chosen)

            result_ov.closed.connect(_on_result_closed)

        def on_cancelled() -> None:
            print(f"[dev] set_prob({effect_type}): cancelled, ticket not consumed")

        self._ticket_panel.show_prob_select_overlay(
            dialog_title, items_for_overlay, on_selected, on_cancelled
        )

    def _toggle_ticket_panel(self):
        """チケットパネルの表示 / 非表示。"""
        new_visible = not self._ticket_panel.isVisible()
        if new_visible:
            self._ticket_panel.show()
            self._ticket_panel.raise_()
        else:
            self._ticket_panel.hide()
        self._settings.ticket_panel_visible = new_visible
        self._sync_manage_panel_checks()
        self._save_config()

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
        # v0.6.1: 「全ルーレットに適用」CB は設定パネル側へ移動
        self._settings_panel.apply_to_all_changed.connect(
            self._on_manage_apply_to_all_changed
        )
        # v0.6.1: 設定パネルから移動したアプリ全体設定の変更
        self._manage_panel.app_setting_changed.connect(self._on_setting_changed)
        # v0.6.1: 全体初期化要求 + グループ単位の初期化要求
        self._manage_panel.global_reset_requested.connect(self._on_global_reset_requested)
        self._manage_panel.ro_only_reset_requested.connect(self._on_ro_only_reset_requested)
        self._manage_panel.app_settings_reset_requested.connect(self._on_app_settings_reset_requested)
        self._manage_panel.app_subgroup_reset_requested.connect(self._on_app_subgroup_reset_requested)
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
        self._manage_panel.auto_hide_enabled_changed.connect(  # i485
            self._on_auto_hide_enabled_changed
        )
        self._manage_panel.auto_hide_seconds_changed.connect(  # i485
            self._on_auto_hide_seconds_changed
        )
        self._manage_panel.auto_hide_fade_changed.connect(  # i486
            self._on_auto_hide_fade_changed
        )
        self._manage_panel.auto_hide_fade_seconds_changed.connect(  # i487
            self._on_auto_hide_fade_seconds_changed
        )
        self._manage_panel.auto_hide_only_roulette_only_changed.connect(  # i098
            self._on_auto_hide_only_roulette_only_changed
        )
        self._manage_panel.auto_hide_after_spin_restore_changed.connect(  # i098
            self._on_auto_hide_after_spin_restore_changed
        )
        self._manage_panel.roulette_reorder_requested.connect(
            self._on_manage_roulette_reorder
        )
        self._manage_panel.roulette_rename_requested.connect(  # i047
            self._on_manage_roulette_rename
        )
        self._manage_panel.ticket_panel_toggled.connect(  # i051
            self._on_manage_ticket_toggled
        )
        self._manage_panel.seq_panel_toggled.connect(  # i051
            self._on_manage_seq_toggled
        )
        self._manage_panel.link_panel_toggled.connect(  # Phase1
            self._on_manage_link_toggled
        )
        self._manage_panel.link_enabled_changed.connect(  # i099
            self._on_manage_link_enabled_changed
        )
        self._manage_panel.link_port_changed.connect(  # i099
            self._on_manage_link_port_changed
        )
        self._manage_panel.link_max_hold_changed.connect(  # i099
            self._on_manage_link_max_hold_changed
        )
        self._manage_panel.link_show_time_changed.connect(  # i100
            self._on_manage_link_show_time_changed
        )

    def _on_manage_ticket_toggled(self, visible: bool):
        """ManagePanel のチケットパネルチェックボックスに応答する。"""
        if visible:
            self._ticket_panel.show()
            self._ticket_panel.raise_()
        else:
            self._ticket_panel.hide()
        self._settings.ticket_panel_visible = visible
        self._save_config()

    def _on_manage_seq_toggled(self, visible: bool):
        """ManagePanel の実行パネルチェックボックスに応答する。"""
        if visible:
            self._open_sequential_spin_dialog()
        else:
            if self._seq_dialog is not None:
                self._seq_dialog.hide()
            self._sync_manage_panel_checks()

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
        # ticket panel
        self._ticket_panel.geometry_changed.connect(self._panel_save_timer.start)
        # link panel (i099)
        self._link_panel.geometry_changed.connect(
            lambda: self._bring_panel_to_front(self._link_panel)
        )
        self._link_panel.geometry_changed.connect(self._panel_save_timer.start)

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
                self._ticket_panel,
                self._link_panel,  # i099: 連携パネルを追加
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

        # i485: アイドル検出フィルタ（全ユーザー操作でアイドルタイマーをリセット）
        self._idle_reset_filter = _IdleResetFilter(self._reset_idle_timer)
        QApplication.instance().installEventFilter(self._idle_reset_filter)

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

        # --- i069: スピン結果遅延確定用 ---
        self._pending_spin_results: dict = {}

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

        # --- 全面非表示状態 (i485) ---
        self._is_all_hidden = False
        self._all_hidden_saved_panels = {}

        # --- 自動全面非表示タイマー (i485) ---
        # i486: フェードアウト状態フラグと参照
        self._auto_hide_fading = False
        self._auto_hide_anim_group = None

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        # i486: タイマー満了時はフェード経由（フェード無効時は _start_auto_hide_fade が即 _hide_all を呼ぶ）
        self._idle_timer.timeout.connect(self._start_auto_hide_fade)
        # _idle_reset_filter は _init_input_filters で既にインストール済みのため
        # ここでタイマーを開始する
        self._reset_idle_timer()

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


