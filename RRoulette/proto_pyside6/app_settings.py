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
    donut_hole: bool = False       # ドーナツ穴表示
    pointer_angle: float = 0.0     # ポインター角度
    profile_idx: int = 1           # サイズプロファイル (0=S, 1=M, 2=L)

    # ============================================================
    #  spin — スピン制御設定
    #    対応: SpinController, WheelWidget
    # ============================================================

    spin_direction: int = 0        # 0=反時計回り, 1=時計回り
    spin_preset_name: str = ""     # スピンプリセット名（空 = デフォルト）

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

    # 結果 overlay:
    result_close_mode: int = 0      # 0=クリックのみ, 1=自動のみ, 2=両方
    result_hold_sec: float = 5.0    # 自動クローズまでの秒数

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
            donut_hole=config.get("donut_hole", False),
            pointer_angle=config.get("pointer_angle", 0.0),
            profile_idx=config.get("profile_idx", 1),
            spin_direction=config.get("spin_direction", 0),
            spin_preset_name=config.get("spin_preset_name", DEFAULT_PRESET_NAME),
            design_preset_name=config.get("design", {}).get("preset_name", "")
                if isinstance(config.get("design"), dict) else "",
            arrangement_direction=config.get("arrangement_direction", 0),
            auto_shuffle=config.get("auto_shuffle", False),
            result_close_mode=config.get("result_close_mode", 0),
            result_hold_sec=config.get("result_hold_sec", 5.0),
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
            "arrangement_direction": self.arrangement_direction,
            "auto_shuffle": self.auto_shuffle,
            "result_close_mode": self.result_close_mode,
            "result_hold_sec": self.result_hold_sec,
        }
