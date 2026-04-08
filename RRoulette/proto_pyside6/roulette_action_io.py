"""
PySide6 プロトタイプ — アクション列 JSON 保存/読込

recorder snapshot と codec を使って action 列を JSON ファイルと
往復する最小 I/O 層。

責務分離:
  - codec: action 1件の dict ↔ object 変換
  - recorder: メモリ内保持と ON/OFF
  - io（本モジュール）: action 列と JSON ファイルの入出力

保存形式:
  {
    "format": "rroulette_actions",
    "version": 1,
    "actions": [ {...}, {...}, ... ]
  }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

from roulette_actions import RouletteAction
from roulette_action_codec import (
    action_to_dict,
    action_from_dict,
    ActionCodecError,
)

# 保存形式定数
FORMAT_ID = "rroulette_actions"
FORMAT_VERSION = 1


class ActionIOError(Exception):
    """保存/読込で発生するエラー。"""


# ================================================================
#  メモリ上変換: action 列 ↔ dict
# ================================================================

def actions_to_json_data(actions: Sequence[RouletteAction]) -> dict:
    """action 列を JSON 互換の dict へ変換する。

    Args:
        actions: 変換対象のアクション列。

    Returns:
        {"format": ..., "version": ..., "actions": [...]} 形式の dict。
    """
    return {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "actions": [action_to_dict(a) for a in actions],
    }


def actions_from_json_data(data: Mapping[str, object]) -> list[RouletteAction]:
    """dict から action 列を復元する。

    Args:
        data: {"format": ..., "version": ..., "actions": [...]} 形式の dict。

    Returns:
        復元された action object のリスト。

    Raises:
        ActionIOError: format/version 不一致、actions 型不正、個別 action の復元失敗。
    """
    if not isinstance(data, Mapping):
        raise ActionIOError(f"expected dict, got {type(data).__name__}")

    fmt = data.get("format")
    if fmt != FORMAT_ID:
        raise ActionIOError(f"unknown format: {fmt!r} (expected {FORMAT_ID!r})")

    ver = data.get("version")
    if ver != FORMAT_VERSION:
        raise ActionIOError(
            f"unsupported version: {ver!r} (expected {FORMAT_VERSION})"
        )

    raw_actions = data.get("actions")
    if not isinstance(raw_actions, list):
        raise ActionIOError(
            f"actions: expected list, got {type(raw_actions).__name__}"
        )

    result: list[RouletteAction] = []
    for i, item in enumerate(raw_actions):
        try:
            result.append(action_from_dict(item))
        except ActionCodecError as e:
            raise ActionIOError(f"actions[{i}]: {e}") from e
    return result


# ================================================================
#  ファイル I/O
# ================================================================

def save_actions_json(path: Path | str,
                      actions: Sequence[RouletteAction]) -> None:
    """action 列を JSON ファイルへ保存する。

    Args:
        path: 保存先パス。
        actions: 保存対象のアクション列。

    Raises:
        ActionIOError: 書き込み失敗。
    """
    data = actions_to_json_data(actions)
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        raise ActionIOError(f"save failed: {e}") from e


def load_actions_json(path: Path | str) -> list[RouletteAction]:
    """JSON ファイルから action 列を読み込む。

    Args:
        path: 読み込みパス。

    Returns:
        復元された action object のリスト。

    Raises:
        ActionIOError: ファイル不在、JSON parse error、format/version 不一致等。
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ActionIOError(f"file not found: {path}") from e
    except OSError as e:
        raise ActionIOError(f"read failed: {e}") from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ActionIOError(f"JSON parse error: {e}") from e

    return actions_from_json_data(data)
