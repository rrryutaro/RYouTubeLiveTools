"""
PySide6 プロトタイプ — アプリケーション設定データ構造

既存の config dict から抽出した設定値を型付きで保持する。
各コンポーネント（WheelWidget / SpinController / ResultOverlay / SettingsPanel）
への設定配布と、将来設定の追加を整理するための中間層。

責務:
  - 既存設定の型安全な保持
  - デフォルト値の一元管理
  - 将来設定のスロット確保（実装前は None やデフォルト）
  - config dict との相互変換

設計方針:
  - 「既に動いている設定」と「将来追加される設定」をグループで明示
  - 各フィールドにはコメントで対応コンポーネントを記載
  - 今後の設定追加時はここにフィールドを足すだけで受け皿ができる
"""

from dataclasses import dataclass, field


@dataclass
class AppSettings:
    """アプリケーション全体の設定値。

    グループ:
      - display: 表示系（テキスト・ドーナツ穴・ポインター・プロファイル）
      - spin: スピン制御系
      - design: デザイン系
      - future: 将来機能用（現時点ではデフォルト値のみ）
    """

    # ============================================================
    #  display — 表示系設定
    #    対応: WheelWidget, MainWindow
    # ============================================================

    text_size_mode: int = 1        # 0=省略, 1=収める, 2=縮小
    text_direction: int = 0        # 0=横(回転), 1=横(水平), 2=縦上, 3=縦下, 4=縦直立
    donut_hole: bool = True        # ドーナツ穴表示（デフォルト: あり）
    pointer_angle: float = 90.0    # ポインター角度（デフォルト: 右）
    profile_idx: int = 1           # サイズプロファイル (0=S, 1=M, 2=L)

    # ============================================================
    #  spin — スピン制御設定
    #    対応: SpinController, WheelWidget
    # ============================================================

    spin_direction: int = 1        # 0=反時計回り, 1=時計回り（デフォルト: 時計回り）
    spin_preset_name: str = ""     # スピンプリセット名（空 = デフォルト）
    spin_duration: float = 9.0     # 通常スピン時間（秒）
    spin_mode: int = 0             # 0=シングル, 1=ダブル, 2=トリプル
    double_duration: float = 9.0   # ダブルスピン時の1回あたり時間（秒）
    triple_duration: float = 9.0   # トリプルスピン時の1回あたり時間（秒）

    # ============================================================
    #  design — デザイン設定
    #    対応: MainWindow (配布), 各コンポーネント (受信)
    # ============================================================

    design_preset_name: str = ""   # デザインプリセット名（空 = デフォルト）

    # ============================================================
    #  future — 将来機能用設定スロット
    #    現時点ではデフォルト値のみ。本実装時にここへ追加。
    # ============================================================

    # 確率変更: 各項目の確率モード・値は item_patterns 内に保持
    # 分割: 各項目の split_count は item_patterns 内に保持
    # 配置:
    arrangement_direction: int = 0  # 0=逆順, 1=順
    # 常時ランダム:
    auto_shuffle: bool = False      # spin 前に配置ランダム化

    # サウンド:
    sound_tick_enabled: bool = True   # スピン中 tick 音
    sound_result_enabled: bool = True # 結果確定音
    tick_volume: int = 100            # tick音量 (0-100)
    win_volume: int = 100             # result音量 (0-100)
    tick_pattern: int = 0             # tick音パターン (0-5, 6=カスタム)
    win_pattern: int = 0              # result音パターン (0-5, 6=カスタム)
    tick_custom_file: str = ""        # カスタムtick音ファイルパス
    win_custom_file: str = ""         # カスタムresult音ファイルパス

    # 結果 overlay:
    result_close_mode: int = 0      # 0=クリックのみ, 1=自動のみ, 2=両方
    result_hold_sec: float = 5.0    # 自動クローズまでの秒数
    macro_hold_sec: float | None = None  # マクロ再生時 hold 秒（None = result_hold_sec と同じ）

    # ログオーバーレイ:
    log_overlay_show: bool = True    # ホイール上のログ表示
    log_timestamp: bool = False      # ログにタイムスタンプ表示
    log_box_border: bool = False     # ログボックス枠線表示
    log_on_top: bool = False         # ログ前面表示（ホイール装飾より上）

    # リセット確認:
    confirm_reset: bool = True       # リセット操作前に確認ダイアログを表示
    confirm_item_delete: bool = True  # 項目削除前に確認ダイアログを表示 (i286)

    # 項目パネル表示 (i283):
    show_item_prob: bool = True       # 各項目行の確率/分割 UI を表示
    show_item_win_count: bool = True  # 各項目行の当選回数ラベルを表示

    # 項目パネル表示モード (i289): 0=詳細表示, 1=シンプル表示
    item_panel_display_mode: int = 1  # i315: デフォルトはシンプルモード

    # リプレイ:
    replay_max_count: int = 5        # リプレイ保存上限
    replay_show_indicator: bool = True  # リプレイ中インジケーター表示

    # ============================================================
    #  window_state — ウィンドウ / パネル配置状態
    #    対応: MainWindow
    #    None = 未保存（初回起動 or キー欠落時はデフォルト動作）
    # ============================================================

    window_x: int | None = None
    window_y: int | None = None
    window_width: int | None = None
    window_height: int | None = None
    roulette_panel_x: int | None = None
    roulette_panel_y: int | None = None
    roulette_panel_width: int | None = None
    roulette_panel_height: int | None = None
    # 設定パネル (右側のアプリ設定パネル) の保存位置
    # 旧キー `item_panel_*` を保持していた値はこちらへ移行する
    settings_panel_x: int | None = None
    settings_panel_y: int | None = None
    settings_panel_width: int | None = None
    settings_panel_height: int | None = None
    settings_panel_visible: bool = False
    # 項目パネル (新 ItemPanel) の保存位置・表示状態
    items_panel_x: int | None = None
    items_panel_y: int | None = None
    items_panel_width: int | None = None
    items_panel_height: int | None = None
    items_panel_visible: bool = True
    # 全体管理パネル (i275 ManagePanel) の保存位置・表示状態
    manage_panel_x: int | None = None
    manage_panel_y: int | None = None
    manage_panel_width: int | None = None
    manage_panel_height: int | None = None
    manage_panel_visible: bool = False
    always_on_top: bool = True         # メインウィンドウ常に最前面（デフォルト: ON）
    # 透過フラグは window / roulette を独立に持つ
    # 旧 `transparent` キーは互換のため from_config 側でフォールバック読込
    window_transparent: bool = False   # メインウィンドウ背景透過
    roulette_transparent: bool = False # ルーレットパネル背景透過
    grip_visible: bool = True          # リサイズグリップ表示
    ctrl_box_visible: bool = True      # コントロールボックス（ドラッグバー）表示
    float_win_show_instance: bool = True  # インスタンス番号表示
    settings_panel_float: bool = False   # 設定パネルフローティング独立化
    roulette_only_mode: bool = False     # ルーレット以外非表示モード

    # 各パネルの移動バー表示状態 (E: i294)
    items_panel_drag_bar_visible: bool = True
    settings_panel_drag_bar_visible: bool = True
    manage_panel_drag_bar_visible: bool = True

    # 設定パネル折りたたみ状態 (セクション名 → True=折りたたみ)
    collapsed_sections: dict = field(default_factory=dict)
    collapse_anim_ms: int = 150        # 折りたたみアニメーション時間 (ms, 0=無効)
    theme_mode: str = "dark"           # テーマモード ("light" / "dark")

    # グラフ UI 設定:
    graph_orientation: str = "horizontal"  # グラフ向き ("horizontal" / "vertical")

    # ログ履歴表示設定:
    log_history_all_patterns: bool = False  # False=選択中パターンのみ, True=全パターン表示

    # ============================================================
    #  ファクトリ
    # ============================================================

    @classmethod
    def from_config(cls, config: dict) -> "AppSettings":
        """既存の config dict から AppSettings を構築する。"""
        from spin_preset import DEFAULT_PRESET_NAME
        return cls(
            text_size_mode=config.get("text_size_mode", 1),
            text_direction=config.get("text_direction", 0),
            donut_hole=config.get("donut_hole", True),
            pointer_angle=config.get("pointer_angle", 90.0),
            profile_idx=config.get("profile_idx", 1),
            spin_direction=config.get("spin_direction", 1),
            spin_preset_name=config.get("spin_preset_name", DEFAULT_PRESET_NAME),
            spin_duration=config.get("spin_duration", 9.0),
            spin_mode=config.get("spin_mode", 0),
            double_duration=config.get("double_duration", 9.0),
            triple_duration=config.get("triple_duration", 9.0),
            design_preset_name=config.get("design", {}).get("preset_name", "")
                if isinstance(config.get("design"), dict) else "",
            arrangement_direction=config.get("arrangement_direction", 0),
            auto_shuffle=config.get("auto_shuffle", False),
            sound_tick_enabled=config.get("sound_tick_enabled", True),
            sound_result_enabled=config.get("sound_result_enabled", True),
            tick_volume=config.get("tick_volume", 100),
            win_volume=config.get("win_volume", 100),
            tick_pattern=config.get("tick_pattern", 0),
            win_pattern=config.get("win_pattern", 0),
            tick_custom_file=config.get("tick_custom_file", ""),
            win_custom_file=config.get("win_custom_file", ""),
            result_close_mode=config.get("result_close_mode", 0),
            result_hold_sec=config.get("result_hold_sec", 5.0),
            macro_hold_sec=config.get("macro_hold_sec",
                                      config.get("replay_hold_sec")),
            window_x=config.get("window_x"),
            window_y=config.get("window_y"),
            window_width=config.get("window_width"),
            window_height=config.get("window_height"),
            roulette_panel_x=config.get("roulette_panel_x"),
            roulette_panel_y=config.get("roulette_panel_y"),
            roulette_panel_width=config.get("roulette_panel_width"),
            roulette_panel_height=config.get("roulette_panel_height"),
            # 設定パネル: 新キー優先、旧 item_panel_* 互換
            settings_panel_x=config.get(
                "settings_panel_x", config.get("item_panel_x")
            ),
            settings_panel_y=config.get(
                "settings_panel_y", config.get("item_panel_y")
            ),
            settings_panel_width=config.get(
                "settings_panel_width", config.get("item_panel_width")
            ),
            settings_panel_height=config.get(
                "settings_panel_height", config.get("item_panel_height")
            ),
            settings_panel_visible=config.get(
                "settings_panel_visible",
                config.get("item_panel_visible", False),
            ),
            items_panel_x=config.get("items_panel_x"),
            items_panel_y=config.get("items_panel_y"),
            items_panel_width=config.get("items_panel_width"),
            items_panel_height=config.get("items_panel_height"),
            items_panel_visible=config.get("items_panel_visible", True),
            manage_panel_x=config.get("manage_panel_x"),
            manage_panel_y=config.get("manage_panel_y"),
            manage_panel_width=config.get("manage_panel_width"),
            manage_panel_height=config.get("manage_panel_height"),
            manage_panel_visible=config.get("manage_panel_visible", False),
            always_on_top=config.get("always_on_top", True),
            # 透過: 新キー優先、旧 transparent 互換 (両方に同じ値)
            window_transparent=config.get(
                "window_transparent", config.get("transparent", False)
            ),
            roulette_transparent=config.get(
                "roulette_transparent", config.get("transparent", False)
            ),
            grip_visible=config.get("grip_visible", True),
            ctrl_box_visible=config.get("ctrl_box_visible", True),
            float_win_show_instance=config.get("float_win_show_instance", True),
            settings_panel_float=config.get("settings_panel_float", False),
            roulette_only_mode=config.get("roulette_only_mode", False),
            items_panel_drag_bar_visible=config.get("items_panel_drag_bar_visible", True),
            settings_panel_drag_bar_visible=config.get("settings_panel_drag_bar_visible", True),
            manage_panel_drag_bar_visible=config.get("manage_panel_drag_bar_visible", True),
            collapsed_sections=config.get("collapsed_sections", {}),
            collapse_anim_ms=config.get("collapse_anim_ms", 150),
            theme_mode=config.get("theme_mode", "dark"),
            graph_orientation=config.get("graph_orientation", "horizontal"),
            log_history_all_patterns=config.get("log_history_all_patterns", False),
            log_overlay_show=config.get("log_overlay_show", True),
            log_timestamp=config.get("log_timestamp", False),
            log_box_border=config.get("log_box_border", False),
            log_on_top=config.get("log_on_top", False),
            confirm_reset=config.get("confirm_reset", True),
            confirm_item_delete=config.get("confirm_item_delete", True),
            replay_max_count=config.get("replay_max_count", 5),
            replay_show_indicator=config.get("replay_show_indicator", True),
            show_item_prob=config.get("show_item_prob", True),
            show_item_win_count=config.get("show_item_win_count", True),
            item_panel_display_mode=config.get("item_panel_display_mode", 1),
        )

    def to_config_patch(self) -> dict:
        """AppSettings の値を config dict にマージ可能な差分として返す。

        将来の設定保存時に config dict を更新するためのユーティリティ。
        """
        return {
            "text_size_mode": self.text_size_mode,
            "text_direction": self.text_direction,
            "donut_hole": self.donut_hole,
            "pointer_angle": self.pointer_angle,
            "profile_idx": self.profile_idx,
            "spin_direction": self.spin_direction,
            "spin_preset_name": self.spin_preset_name,
            "spin_duration": self.spin_duration,
            "spin_mode": self.spin_mode,
            "double_duration": self.double_duration,
            "triple_duration": self.triple_duration,
            "arrangement_direction": self.arrangement_direction,
            "auto_shuffle": self.auto_shuffle,
            "sound_tick_enabled": self.sound_tick_enabled,
            "sound_result_enabled": self.sound_result_enabled,
            "tick_volume": self.tick_volume,
            "win_volume": self.win_volume,
            "tick_pattern": self.tick_pattern,
            "win_pattern": self.win_pattern,
            "tick_custom_file": self.tick_custom_file,
            "win_custom_file": self.win_custom_file,
            "result_close_mode": self.result_close_mode,
            "result_hold_sec": self.result_hold_sec,
            "macro_hold_sec": self.macro_hold_sec,
            "window_x": self.window_x,
            "window_y": self.window_y,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "roulette_panel_x": self.roulette_panel_x,
            "roulette_panel_y": self.roulette_panel_y,
            "roulette_panel_width": self.roulette_panel_width,
            "roulette_panel_height": self.roulette_panel_height,
            "settings_panel_x": self.settings_panel_x,
            "settings_panel_y": self.settings_panel_y,
            "settings_panel_width": self.settings_panel_width,
            "settings_panel_height": self.settings_panel_height,
            "settings_panel_visible": self.settings_panel_visible,
            "items_panel_x": self.items_panel_x,
            "items_panel_y": self.items_panel_y,
            "items_panel_width": self.items_panel_width,
            "items_panel_height": self.items_panel_height,
            "items_panel_visible": self.items_panel_visible,
            "manage_panel_x": self.manage_panel_x,
            "manage_panel_y": self.manage_panel_y,
            "manage_panel_width": self.manage_panel_width,
            "manage_panel_height": self.manage_panel_height,
            "manage_panel_visible": self.manage_panel_visible,
            "always_on_top": self.always_on_top,
            "window_transparent": self.window_transparent,
            "roulette_transparent": self.roulette_transparent,
            "grip_visible": self.grip_visible,
            "ctrl_box_visible": self.ctrl_box_visible,
            "float_win_show_instance": self.float_win_show_instance,
            "settings_panel_float": self.settings_panel_float,
            "roulette_only_mode": self.roulette_only_mode,
            "items_panel_drag_bar_visible": self.items_panel_drag_bar_visible,
            "settings_panel_drag_bar_visible": self.settings_panel_drag_bar_visible,
            "manage_panel_drag_bar_visible": self.manage_panel_drag_bar_visible,
            "collapsed_sections": self.collapsed_sections,
            "collapse_anim_ms": self.collapse_anim_ms,
            "theme_mode": self.theme_mode,
            "graph_orientation": self.graph_orientation,
            "log_history_all_patterns": self.log_history_all_patterns,
            "log_overlay_show": self.log_overlay_show,
            "log_timestamp": self.log_timestamp,
            "log_box_border": self.log_box_border,
            "log_on_top": self.log_on_top,
            "confirm_reset": self.confirm_reset,
            "confirm_item_delete": self.confirm_item_delete,
            "replay_max_count": self.replay_max_count,
            "replay_show_indicator": self.replay_show_indicator,
            "show_item_prob": self.show_item_prob,
            "show_item_win_count": self.show_item_win_count,
            "item_panel_display_mode": self.item_panel_display_mode,
        }
