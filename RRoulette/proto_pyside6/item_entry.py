"""
PySide6 プロトタイプ — 項目データ構造

ルーレットの各項目（テキスト・確率・分割等）を型付きで保持する。
AppSettings（アプリ設定）とは明確に分離された「項目データ」側の責務。

責務:
  - 項目テキスト・有効フラグ・確率・分割数の保持
  - config dict との相互変換
  - 将来の項目編集 UI のデータモデル

設計方針:
  - AppSettings はアプリ全体の設定（表示・スピン・デザイン等）を保持
  - ItemEntry は個々の項目固有のデータを保持
  - 両者は config.json 内では別キーに格納される:
      AppSettings → config 直下のキー群
      ItemEntry   → config["item_patterns"][パターン名] 内
"""

from dataclasses import dataclass


@dataclass
class ItemEntry:
    """ルーレット項目の1エントリ。

    Attributes:
        text: 表示テキスト
        enabled: 有効フラグ（load 時に False はフィルタ済み）
        split_count: 分割数（1 = 分割なし）
        prob_mode: 確率モード (None / "fixed" / "weight")
        prob_value: 確率値（prob_mode に応じた意味）
    """

    text: str
    enabled: bool = True
    split_count: int = 1
    prob_mode: str | None = None
    prob_value: float | None = None

    @classmethod
    def from_config_entry(cls, entry) -> "ItemEntry | None":
        """config の項目エントリ（str or dict）から ItemEntry を構築する。

        無効な項目（enabled=False / 空テキスト）は None を返す。
        """
        if isinstance(entry, str):
            if entry.strip():
                return cls(text=entry)
            return None
        if isinstance(entry, dict):
            if not entry.get("enabled", True):
                return None
            text = entry.get("text", "")
            if not text.strip():
                return None
            return cls(
                text=text,
                enabled=True,
                split_count=entry.get("split_count", 1),
                prob_mode=entry.get("prob_mode"),
                prob_value=entry.get("prob_value"),
            )
        return None

    def to_dict(self) -> dict:
        """config 保存用の dict 表現を返す。"""
        return {
            "text": self.text,
            "enabled": self.enabled,
            "split_count": self.split_count,
            "prob_mode": self.prob_mode,
            "prob_value": self.prob_value,
        }
