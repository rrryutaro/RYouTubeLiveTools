"""
PySide6 プロトタイプ — アクション直列化 Codec

現時点の6アクション（RouletteAction）を dict へ直列化し、
dict から action object へ復元する最小 codec。

将来のマクロ記録・保存の土台として使用する。

対応アクション:
  - AddRoulette
  - RemoveRoulette
  - SetActiveRoulette
  - SpinRoulette
  - UpdateItemEntries
  - UpdateSettings
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from roulette_actions import (
    RouletteAction,
    AddRoulette,
    RemoveRoulette,
    SetActiveRoulette,
    SpinRoulette,
    UpdateItemEntries,
    UpdateSettings,
    BranchOnWinner,
)


class ActionCodecError(Exception):
    """codec の直列化/復元で発生するエラー。"""


# ================================================================
#  type 識別子 ↔ action class のマッピング
# ================================================================

_TYPE_TO_CLASS: dict[str, type] = {
    "add_roulette": AddRoulette,
    "remove_roulette": RemoveRoulette,
    "set_active_roulette": SetActiveRoulette,
    "spin_roulette": SpinRoulette,
    "update_item_entries": UpdateItemEntries,
    "update_settings": UpdateSettings,
    "branch_on_winner": BranchOnWinner,
}

_CLASS_TO_TYPE: dict[type, str] = {v: k for k, v in _TYPE_TO_CLASS.items()}


# ================================================================
#  直列化: action → dict
# ================================================================

def action_to_dict(action: RouletteAction) -> dict:
    """action object を JSON 互換の dict へ変換する。

    Args:
        action: 変換対象のアクション。

    Returns:
        {"type": "...", ...payload} 形式の dict。

    Raises:
        ActionCodecError: 未知のアクション型の場合。
    """
    cls = type(action)
    type_id = _CLASS_TO_TYPE.get(cls)
    if type_id is None:
        raise ActionCodecError(f"unknown action class: {cls.__name__}")

    payload = asdict(action)

    # UpdateItemEntries.entries: tuple → list（JSON 互換）
    if isinstance(action, UpdateItemEntries):
        payload["entries"] = list(action.entries)

    # BranchOnWinner: ネストした action 列を再帰的に直列化
    if isinstance(action, BranchOnWinner):
        payload["then_actions"] = [action_to_dict(a) for a in action.then_actions]
        payload["else_actions"] = [action_to_dict(a) for a in action.else_actions]

    return {"type": type_id, **payload}


# ================================================================
#  復元: dict → action
# ================================================================

def action_from_dict(data: Mapping[str, object]) -> RouletteAction:
    """dict から action object を復元する。

    Args:
        data: {"type": "...", ...payload} 形式の dict。

    Returns:
        復元された action object。

    Raises:
        ActionCodecError: type 不明、必須フィールド不足、型不正の場合。
    """
    if not isinstance(data, Mapping):
        raise ActionCodecError(f"expected dict, got {type(data).__name__}")

    type_id = data.get("type")
    if not isinstance(type_id, str):
        raise ActionCodecError(f"missing or invalid 'type' field: {type_id!r}")

    cls = _TYPE_TO_CLASS.get(type_id)
    if cls is None:
        raise ActionCodecError(f"unknown action type: {type_id!r}")

    # type を除いた payload を抽出
    payload = {k: v for k, v in data.items() if k != "type"}

    # UpdateItemEntries.entries: list → tuple（frozen dataclass 互換）
    if cls is UpdateItemEntries and "entries" in payload:
        entries = payload["entries"]
        if not isinstance(entries, (list, tuple)):
            raise ActionCodecError(
                f"UpdateItemEntries.entries: expected list, got {type(entries).__name__}"
            )
        payload["entries"] = tuple(entries)

    # BranchOnWinner: ネストした action 列を再帰的に復元
    if cls is BranchOnWinner:
        for key in ("then_actions", "else_actions"):
            raw = payload.get(key, [])
            if not isinstance(raw, (list, tuple)):
                raise ActionCodecError(
                    f"BranchOnWinner.{key}: expected list, got {type(raw).__name__}"
                )
            payload[key] = tuple(action_from_dict(item) for item in raw)

    try:
        return cls(**payload)
    except TypeError as e:
        raise ActionCodecError(f"failed to construct {cls.__name__}: {e}") from e


# ================================================================
#  1行要約: action → 表示用文字列
# ================================================================

def action_summary(action: RouletteAction) -> str:
    """action の1行要約文字列を返す。GUI リスト表示用。

    各アクション型に対し、種別とキーパラメータを含む短い文字列を返す。
    BranchOnWinner はネスト数のみ表示し、内容の展開は詳細編集に委ねる。
    """
    if isinstance(action, AddRoulette):
        s = "ルーレット追加"
        if action.activate:
            s += " (activate)"
        return s
    elif isinstance(action, RemoveRoulette):
        return f"ルーレット削除: {action.roulette_id or '(未設定)'}"
    elif isinstance(action, SetActiveRoulette):
        return f"アクティブ切替: {action.roulette_id or '(未設定)'}"
    elif isinstance(action, SpinRoulette):
        return f"スピン: {action.roulette_id or '(active)'}"
    elif isinstance(action, UpdateItemEntries):
        rid = action.roulette_id or "(active)"
        return f"項目更新: {rid} ({len(action.entries)}件)"
    elif isinstance(action, UpdateSettings):
        return f"設定変更: {action.key} = {action.value}"
    elif isinstance(action, BranchOnWinner):
        src = action.source_roulette_id or "(未設定)"
        return (f"分岐: source={src} "
                f"winner='{action.winner_text}' "
                f"→ then:{len(action.then_actions)} / else:{len(action.else_actions)}")
    return f"(unknown: {type(action).__name__})"


# ================================================================
#  保存時バリデーション
# ================================================================

def validate_action_for_save(action: RouletteAction) -> list[str]:
    """保存前の構造的バリデーションを行い、問題があればメッセージのリストを返す。

    ここでは action 単体の構造的な正しさのみ検証する。
    実行時の文脈依存チェック（roulette が存在するか、spinning 中か等）は
    MainWindow._handle_branch_on_winner / apply_action 側の責務とする。

    Returns:
        問題がなければ空リスト。問題があればエラーメッセージのリスト。
    """
    errors: list[str] = []

    if isinstance(action, BranchOnWinner):
        if not action.source_roulette_id:
            errors.append("source_roulette_id が未設定")
        if not action.winner_text:
            errors.append("winner_text が未設定")
        for i, a in enumerate(action.then_actions):
            for e in validate_action_for_save(a):
                errors.append(f"then[{i}]: {e}")
        for i, a in enumerate(action.else_actions):
            for e in validate_action_for_save(a):
                errors.append(f"else[{i}]: {e}")
    elif isinstance(action, RemoveRoulette):
        if not action.roulette_id:
            errors.append("roulette_id が未設定")
    elif isinstance(action, SetActiveRoulette):
        if not action.roulette_id:
            errors.append("roulette_id が未設定")

    return errors
