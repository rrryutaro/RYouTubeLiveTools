"""
pattern_store.py — パターン管理の純ロジック層

bridge.py から切り出したパターン管理責務。
tkinter / UI 非依存。config_io を通じてファイル永続化する。
"""

import uuid as _uuid

from config_io import save_config


def get_pattern_names(config: dict) -> list[str]:
    """config dict からパターン名の一覧を返す。"""
    patterns = config.get("item_patterns", {})
    if not patterns:
        return ["デフォルト"]
    return list(patterns.keys())


def get_current_pattern_name(config: dict) -> str:
    """config dict から現在のパターン名を返す。"""
    return config.get("current_pattern", "デフォルト")


def set_current_pattern(config: dict, pattern_name: str) -> None:
    """現在パターンを切り替えて保存する。"""
    patterns = config.get("item_patterns", {})
    if pattern_name not in patterns:
        return
    config["current_pattern"] = pattern_name
    save_config(config)


def add_pattern(config: dict, pattern_name: str) -> bool:
    """新しい空パターンを追加する。既に同名があれば False を返す。"""
    if "item_patterns" not in config:
        config["item_patterns"] = {}
    if pattern_name in config["item_patterns"]:
        return False
    config["item_patterns"][pattern_name] = []
    if "pattern_ids" not in config:
        config["pattern_ids"] = {}
    if pattern_name not in config["pattern_ids"]:
        config["pattern_ids"][pattern_name] = str(_uuid.uuid4())
    save_config(config)
    return True


def delete_pattern(config: dict, pattern_name: str) -> bool:
    """指定パターンを削除する。最後の1件は削除不可。

    削除後、current_pattern が削除対象だった場合は残りの先頭に切り替える。
    Returns:
        削除できたら True。
    """
    patterns = config.get("item_patterns", {})
    if pattern_name not in patterns:
        return False
    if len(patterns) <= 1:
        return False
    del patterns[pattern_name]
    if config.get("current_pattern") == pattern_name:
        config["current_pattern"] = next(iter(patterns))
    config.get("pattern_ids", {}).pop(pattern_name, None)
    save_config(config)
    return True


def rename_pattern(config: dict, old_name: str, new_name: str) -> bool:
    """パターン名を変更する。UUID は保持する（i407: 不変ID方針）。

    辞書キーの順序を保持したまま old_name を new_name に置換する。
    Returns:
        変更できたら True。old_name が存在しない / new_name が既存なら False。
    """
    patterns = config.get("item_patterns", {})
    if old_name not in patterns:
        return False
    if new_name in patterns and new_name != old_name:
        return False
    config["item_patterns"] = {
        (new_name if k == old_name else k): v
        for k, v in patterns.items()
    }
    if config.get("current_pattern") == old_name:
        config["current_pattern"] = new_name
    pid_map = config.get("pattern_ids", {})
    if old_name in pid_map:
        pid_map[new_name] = pid_map.pop(old_name)
    save_config(config)
    return True


def get_pattern_ids(config: dict) -> dict:
    """config からパターン名 → UUID のマップを返す。"""
    return config.get("pattern_ids", {})


def get_pattern_id(config: dict, pattern_name: str) -> str:
    """指定パターン名の UUID を返す。存在しなければ生成して登録・保存する。

    Args:
        config: config dict
        pattern_name: パターン名
    Returns:
        そのパターンの不変 UUID 文字列
    """
    if "pattern_ids" not in config:
        config["pattern_ids"] = {}
    pid_map = config["pattern_ids"]
    if pattern_name not in pid_map:
        pid_map[pattern_name] = str(_uuid.uuid4())
        save_config(config)
    return pid_map[pattern_name]


def ensure_pattern_ids(config: dict) -> dict:
    """全パターンに pattern_id が付いていることを保証する。

    旧フォーマット（pattern_ids なし）から呼ばれた場合、全パターンに UUID を生成して保存する。
    Returns:
        {pattern_name: uuid} の dict
    """
    patterns = config.get("item_patterns", {})
    if "pattern_ids" not in config:
        config["pattern_ids"] = {}
    pid_map = config["pattern_ids"]
    changed = False
    for name in patterns:
        if name not in pid_map:
            pid_map[name] = str(_uuid.uuid4())
            changed = True
    if not patterns and "デフォルト" not in pid_map:
        pid_map["デフォルト"] = str(_uuid.uuid4())
        changed = True
    if changed:
        save_config(config)
    return pid_map
