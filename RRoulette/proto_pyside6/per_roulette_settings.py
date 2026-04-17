"""
PySide6 プロトタイプ — ルーレット個別設定データモデル

i368: AppSettings からルーレット個別設定を分離した専用データクラス。
各 RouletteContext が独立したインスタンスを保持する。

責務:
  - ルーレット個別設定のフィールド定義とデフォルト値管理
  - config["roulettes"][*] との相互変換
  - AppSettings から初期値を取り込むファクトリ

持たせないもの:
  - QWidget / RoulettePanel / runtime オブジェクトへの参照
  - 保存トリガー・UI 更新ロジック

アプリ全体共通設定（volume, theme, window_state 等）は AppSettings 側に残す。
"""

from __future__ import annotations

from dataclasses import dataclass

# i369: PerRouletteSettings が管理するキーのセット。
# main_window._update_setting_by_action で「global か per-roulette か」を判定するために使う。
PER_ROULETTE_KEYS: frozenset = frozenset({
    "spin_duration",
    "spin_preset_name",
    "spin_mode",
    "double_duration",
    "triple_duration",
    "sound_tick_enabled",
    "sound_result_enabled",
    "tick_pattern",         # i370: スピン音の種類（per-roulette）
    "win_pattern",          # i370: 決定音の種類（per-roulette）
    "spin_direction",
    "donut_hole",
    "pointer_angle",
    "text_size_mode",
    "text_direction",
    "log_overlay_show",
    "log_on_top",
    "log_timestamp",
    "log_box_border",
    "log_all_patterns",     # i395: 全パターン表示（per-roulette）
    "result_close_mode",
    "result_hold_sec",
})


@dataclass
class PerRouletteSettings:
    """1ルーレットに固有の設定値。

    各 RouletteContext がこのインスタンスを独立して保持することで、
    ルーレット間の設定干渉を防ぐ。

    Attributes:
        spin_duration: 通常スピン時間（秒）
        spin_preset_name: スピンプリセット名（空 = デフォルト）
        spin_mode: 0=シングル, 1=ダブル, 2=トリプル
        double_duration: ダブルスピン 1回あたり時間（秒）
        triple_duration: トリプルスピン 1回あたり時間（秒）
        sound_tick_enabled: スピン中 tick 音 ON/OFF
        sound_result_enabled: 結果確定音 ON/OFF
        spin_direction: 0=反時計回り, 1=時計回り
        donut_hole: ドーナツ穴表示
        pointer_angle: ポインター角度（度）
        text_size_mode: 0=省略, 1=収める, 2=縮小
        text_direction: 0=横(回転), 1=横(水平), 2=縦上, 3=縦下, 4=縦直立
        log_overlay_show: ホイール上のログ表示 ON/OFF
        log_on_top: ログ前面表示（ホイール装飾より上）
        log_timestamp: ログにタイムスタンプ表示
        log_box_border: ログボックス枠線表示
        result_close_mode: 0=クリックのみ, 1=自動のみ, 2=両方
        result_hold_sec: 自動クローズまでの秒数
    """

    # スピン系
    spin_duration: float = 9.0
    spin_preset_name: str = ""
    spin_mode: int = 0
    double_duration: float = 9.0
    triple_duration: float = 9.0

    # サウンド ON/OFF（音量はアプリ共通 → AppSettings 側）
    sound_tick_enabled: bool = True
    sound_result_enabled: bool = True
    # i370: 音の種類（per-roulette）。音量・カスタムファイルはアプリ共通のまま
    tick_pattern: int = 0
    win_pattern: int = 0

    # 表示系
    spin_direction: int = 1
    donut_hole: bool = True
    pointer_angle: float = 90.0
    text_size_mode: int = 1
    text_direction: int = 0

    # ログオーバーレイ系
    log_overlay_show: bool = True
    log_on_top: bool = False
    log_timestamp: bool = False
    log_box_border: bool = False
    log_all_patterns: bool = False  # i395: 全パターン表示（per-roulette）

    # 結果 overlay
    result_close_mode: int = 0
    result_hold_sec: float = 5.0

    # =========================================================
    #  ファクトリ
    # =========================================================

    @classmethod
    def from_app_settings(cls, s: object) -> "PerRouletteSettings":
        """AppSettings のインスタンスから per-roulette 部分を取り込む。

        新規ルーレット生成時のデフォルト初期化に使う。
        AppSettings が持つ同名フィールドを優先し、無ければクラスデフォルト値を使う。

        Args:
            s: AppSettings インスタンス（型ヒントは循環参照回避のため object）

        Returns:
            PerRouletteSettings の新規インスタンス
        """
        def _g(key, default):
            return getattr(s, key, default)

        return cls(
            spin_duration=_g("spin_duration", 9.0),
            spin_preset_name=_g("spin_preset_name", ""),
            spin_mode=_g("spin_mode", 0),
            double_duration=_g("double_duration", 9.0),
            triple_duration=_g("triple_duration", 9.0),
            sound_tick_enabled=_g("sound_tick_enabled", True),
            sound_result_enabled=_g("sound_result_enabled", True),
            tick_pattern=_g("tick_pattern", 0),
            win_pattern=_g("win_pattern", 0),
            spin_direction=_g("spin_direction", 1),
            donut_hole=_g("donut_hole", True),
            pointer_angle=_g("pointer_angle", 90.0),
            text_size_mode=_g("text_size_mode", 1),
            text_direction=_g("text_direction", 0),
            log_overlay_show=_g("log_overlay_show", True),
            log_on_top=_g("log_on_top", False),
            log_timestamp=_g("log_timestamp", False),
            log_box_border=_g("log_box_border", False),
            log_all_patterns=_g("log_history_all_patterns", False),
            result_close_mode=_g("result_close_mode", 0),
            result_hold_sec=_g("result_hold_sec", 5.0),
        )

    @classmethod
    def from_config_entry(
        cls,
        entry: dict,
        fallback: "PerRouletteSettings | None" = None,
    ) -> "PerRouletteSettings":
        """config["roulettes"][*] エントリから復元する。

        キーが存在しない場合は fallback の値（なければクラスデフォルト）を使う。
        旧形式 config への後方互換を維持するため、全キーを任意扱いにする。

        Args:
            entry: config["roulettes"][*] の 1 エントリ dict
            fallback: キー欠落時の補完値。None の場合はクラスデフォルト値を使う。

        Returns:
            PerRouletteSettings の新規インスタンス
        """
        fb = fallback if fallback is not None else cls()

        def _get(key: str, default):
            return entry.get(key, getattr(fb, key, default))

        return cls(
            spin_duration=_get("spin_duration", 9.0),
            spin_preset_name=_get("spin_preset_name", ""),
            spin_mode=_get("spin_mode", 0),
            double_duration=_get("double_duration", 9.0),
            triple_duration=_get("triple_duration", 9.0),
            sound_tick_enabled=_get("sound_tick_enabled", True),
            sound_result_enabled=_get("sound_result_enabled", True),
            tick_pattern=_get("tick_pattern", 0),
            win_pattern=_get("win_pattern", 0),
            spin_direction=_get("spin_direction", 1),
            donut_hole=_get("donut_hole", True),
            pointer_angle=_get("pointer_angle", 90.0),
            text_size_mode=_get("text_size_mode", 1),
            text_direction=_get("text_direction", 0),
            log_overlay_show=_get("log_overlay_show", True),
            log_on_top=_get("log_on_top", False),
            log_timestamp=_get("log_timestamp", False),
            log_box_border=_get("log_box_border", False),
            log_all_patterns=_get("log_all_patterns", False),
            result_close_mode=_get("result_close_mode", 0),
            result_hold_sec=_get("result_hold_sec", 5.0),
        )

    def apply_to_panel(self, panel) -> None:
        """保持している設定を panel の runtime オブジェクトへ適用する。

        i369: active 切替後の UI 同期で ctx.settings → runtime への一括適用に使う。
        log_overlay_show / log_on_top は set_log_visible / set_log_on_top で適用する。
        """
        sc = panel.spin_ctrl
        w  = panel.wheel
        ro = panel.result_overlay
        if self.spin_preset_name:
            sc.set_spin_preset(self.spin_preset_name)
        sc.set_spin_duration(self.spin_duration)
        sc.set_spin_mode(self.spin_mode)
        sc.set_double_duration(self.double_duration)
        sc.set_triple_duration(self.triple_duration)
        sc.set_sound_tick_enabled(self.sound_tick_enabled)
        sc.set_sound_result_enabled(self.sound_result_enabled)
        sc.set_tick_pattern(self.tick_pattern)
        sc.set_win_pattern(self.win_pattern)
        w._spin_direction = self.spin_direction
        w.set_donut_hole(self.donut_hole)
        w.set_pointer_angle(self.pointer_angle)
        w.set_text_mode(self.text_size_mode, self.text_direction)
        w.set_log_visible(self.log_overlay_show)
        w.set_log_on_top(self.log_on_top)
        w.set_log_timestamp(self.log_timestamp)
        w.set_log_box_border(self.log_box_border)
        w.set_log_all_patterns(self.log_all_patterns)  # i395
        ro.set_close_mode(self.result_close_mode)
        ro.set_hold_sec(self.result_hold_sec)

    def to_config_entry(self) -> dict:
        """per-roulette 設定を config["roulettes"][*] エントリ用の dict に変換する。

        geometry・item_patterns など他フィールドは呼び出し側が管理するため含めない。

        Returns:
            per-roulette 設定のみを含む dict
        """
        return {
            "spin_duration":        self.spin_duration,
            "spin_preset_name":     self.spin_preset_name,
            "spin_mode":            self.spin_mode,
            "double_duration":      self.double_duration,
            "triple_duration":      self.triple_duration,
            "sound_tick_enabled":   self.sound_tick_enabled,
            "sound_result_enabled": self.sound_result_enabled,
            "tick_pattern":         self.tick_pattern,
            "win_pattern":          self.win_pattern,
            "spin_direction":       self.spin_direction,
            "donut_hole":           self.donut_hole,
            "pointer_angle":        self.pointer_angle,
            "text_size_mode":       self.text_size_mode,
            "text_direction":       self.text_direction,
            "log_overlay_show":     self.log_overlay_show,
            "log_on_top":           self.log_on_top,
            "log_timestamp":        self.log_timestamp,
            "log_box_border":       self.log_box_border,
            "log_all_patterns":     self.log_all_patterns,
            "result_close_mode":    self.result_close_mode,
            "result_hold_sec":      self.result_hold_sec,
        }
