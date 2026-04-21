"""
item_data_io.py — 項目データの純 I/O 層

bridge.py から切り出した ItemEntry 読み書き責務。
tkinter / UI 非依存。config_io を通じてファイル永続化する。

公開 API:
  load_items(config)           → list[str]          有効項目テキスト一覧
  load_item_entries(config)    → list[ItemEntry]     有効項目エントリ一覧
  load_all_item_entries(config)→ list[ItemEntry]     全項目（disabled 含む）
  load_weights_from_config(c)  → list[float]         split_count ベース重み
  save_item_entries(config, entries, pattern_name)   → None
"""

from config_io import load_config, save_config
from item_entry import ItemEntry

_DEFAULT_ITEMS = [
    {"text": "項目A", "enabled": True, "split_count": 1, "prob_mode": None, "prob_value": None},
    {"text": "項目B", "enabled": True, "split_count": 1, "prob_mode": None, "prob_value": None},
    {"text": "項目C", "enabled": True, "split_count": 1, "prob_mode": None, "prob_value": None},
    {"text": "項目D", "enabled": True, "split_count": 1, "prob_mode": None, "prob_value": None},
    {"text": "項目E", "enabled": True, "split_count": 1, "prob_mode": None, "prob_value": None},
    {"text": "項目F", "enabled": True, "split_count": 1, "prob_mode": None, "prob_value": None},
]


def _get_current_pattern_items(config: dict) -> list:
    """config dict から現在のパターンの raw 項目リストを取得する。"""
    patterns = config.get("item_patterns", {})
    current = config.get("current_pattern", "デフォルト")
    raw_items = patterns.get(current, [])
    if not raw_items:
        for v in patterns.values():
            if v:
                raw_items = v
                break
    if not raw_items:
        return list(_DEFAULT_ITEMS)
    return raw_items


def _extract_item_text(entry) -> str | None:
    """項目エントリからテキストを抽出する。
    既存の設定形式では項目は dict（{'text': ..., 'enabled': ..., ...}）で保存されている。
    enabled=False の項目は None を返す（ホイールに表示しない）。
    """
    if isinstance(entry, str):
        return entry if entry.strip() else None
    if isinstance(entry, dict):
        if not entry.get("enabled", True):
            return None
        return entry.get("text", "")
    return None


def load_items(config: dict | None = None) -> list[str]:
    """設定辞書から現在の有効な項目テキストリストを取得する。"""
    if config is None:
        config = load_config()
    raw_items = _get_current_pattern_items(config)
    items = []
    for entry in raw_items:
        text = _extract_item_text(entry)
        if text is not None and text.strip():
            items.append(text)
    return items


def load_item_entries(config: dict | None = None) -> list[ItemEntry]:
    """設定辞書から現在の有効な項目エントリを ItemEntry リストで返す。

    Returns:
        有効な項目の ItemEntry リスト（enabled=False はフィルタ済み）
    """
    if config is None:
        config = load_config()
    raw_items = _get_current_pattern_items(config)
    entries = []
    for raw in raw_items:
        item = ItemEntry.from_config_entry(raw)
        if item is not None:
            entries.append(item)
    return entries


def load_all_item_entries(config: dict | None = None) -> list[ItemEntry]:
    """設定辞書から全項目エントリ（disabled 含む）を返す。

    編集 UI 用。enabled=False の項目も含めて返す。
    """
    if config is None:
        config = load_config()
    raw_items = _get_current_pattern_items(config)
    entries = []
    for raw in raw_items:
        item = ItemEntry.from_config_entry(raw, keep_disabled=True)
        if item is not None:
            entries.append(item)
    return entries


def load_weights_from_config(config: dict | None = None) -> list[float]:
    """設定辞書から項目の重み（split_count ベース）を取得する。"""
    if config is None:
        config = load_config()
    raw_items = _get_current_pattern_items(config)
    weights = []
    for entry in raw_items:
        text = _extract_item_text(entry)
        if text is not None and text.strip():
            if isinstance(entry, dict):
                weights.append(float(entry.get("split_count", 1) or 1))
            else:
                weights.append(1.0)
    return weights


def save_item_entries(config: dict, entries: list[ItemEntry],
                      pattern_name: str | None = None) -> None:
    """ItemEntry リストを config dict の item_patterns に書き戻す。

    Args:
        config: 現在の config dict（直接変更される）
        entries: 保存する ItemEntry リスト
        pattern_name: 対象パターン名（None = current_pattern）

    保存フロー:
        ItemEntry.to_dict() → config["item_patterns"][pattern] → save_config()
    """
    if pattern_name is None:
        pattern_name = config.get("current_pattern", "デフォルト")
    if "item_patterns" not in config:
        config["item_patterns"] = {}
    config["item_patterns"][pattern_name] = [e.to_dict() for e in entries]
    save_config(config)
