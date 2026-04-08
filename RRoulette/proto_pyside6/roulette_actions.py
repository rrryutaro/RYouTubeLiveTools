"""
PySide6 プロトタイプ — ルーレットアクション定義

マクロ向け最小アクション層。
ユーザー操作を「操作名 + 引数」の frozen dataclass で表現する。

将来のマクロ記録・再生では、このアクションのリストをそのまま
記録列として扱えることを想定している。

現時点で定義するアクション:
  - AddRoulette: 新規ルーレット追加（自動採番）
  - RemoveRoulette: 指定 ID のルーレット削除
  - SetActiveRoulette: アクティブルーレット切替
  - SpinRoulette: spin 開始（開始のみ、結果待ちは含まない）
  - UpdateItemEntries: 項目データ全件置換
  - UpdateSettings: 設定変更（key/value 単位）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


class ActionOrigin(Enum):
    """アクション実行の起点を表す。

    USER: ユーザー操作（UI / ショートカット）由来。recorder 記録対象。
    MACRO: マクロ再生由来。recorder へ再記録しない。
    """
    USER = auto()
    MACRO = auto()


@dataclass(frozen=True)
class AddRoulette:
    """新規ルーレットを追加する。

    Attributes:
        activate: 追加後にアクティブにするか（デフォルト True）
    """
    activate: bool = True


@dataclass(frozen=True)
class RemoveRoulette:
    """指定 ID のルーレットを削除する。

    Attributes:
        roulette_id: 削除対象の ID
    """
    roulette_id: str = ""


@dataclass(frozen=True)
class SetActiveRoulette:
    """アクティブなルーレットを切り替える。

    Attributes:
        roulette_id: 切替先の ID
    """
    roulette_id: str = ""


@dataclass(frozen=True)
class SpinRoulette:
    """spin を開始する（開始のみ。結果待ちや分岐は含まない）。

    Attributes:
        roulette_id: 対象の ID。空文字なら active を対象にする。
    """
    roulette_id: str = ""


@dataclass(frozen=True)
class UpdateItemEntries:
    """項目データを全件置換する。

    1回の項目編集確定を表すアクション。
    個別 item の追加・削除・編集の細分化は将来課題。

    Attributes:
        roulette_id: 対象の ID。空文字なら active を対象にする。
        entries: 置換後の項目データ。frozen 互換のため tuple で保持する。
                 既存コード（list 前提）との境界で変換する。
    """
    roulette_id: str = ""
    entries: tuple = ()


@dataclass(frozen=True)
class UpdateSettings:
    """設定を1件変更する。

    1回の設定変更確定を表すアクション。
    key は既存の設定キー文字列をそのまま使用する。

    Attributes:
        key: 設定キー名（例: "donut_hole", "spin_direction"）
        value: 設定値（型は key に依存）
    """
    key: str = ""
    value: object = None


@dataclass(frozen=True)
class BranchOnWinner:
    """直前 spin の当選結果で分岐する。

    source_roulette_id で指定した roulette の直前結果に対して、
    match_mode に従い winner_text と比較する。
    一致時は then_actions、不一致時は else_actions へ進む。

    評価元 roulette_id が未設定または不一致の場合は安全側停止する。

    Attributes:
        source_roulette_id: 評価元の roulette ID（どの roulette の結果を見るか）
        winner_text: 比較する当選テキスト
        match_mode: 比較方式。"exact"（完全一致）または "contains"（部分一致）
        then_actions: 一致時に実行する action 列
        else_actions: 不一致時に実行する action 列
    """
    source_roulette_id: str = ""
    winner_text: str = ""
    match_mode: str = "exact"
    then_actions: tuple = ()
    else_actions: tuple = ()


# 現時点でディスパッチ対象となるアクション型の Union
RouletteAction = Union[
    AddRoulette, RemoveRoulette, SetActiveRoulette,
    SpinRoulette, UpdateItemEntries, UpdateSettings,
    BranchOnWinner,
]


@dataclass(frozen=True)
class LastSpinResult:
    """直前の spin 完了で確定した当選結果。

    将来の分岐マクロ再生で branch 条件に使うための最小保持構造。
    ディスパッチ対象ではなく、状態参照用。

    Attributes:
        roulette_id: spin が完了した roulette の ID
        winner_text: 当選セグメントのテキスト
        seg_index: 当選セグメントの index（-1 = 不明）
    """
    roulette_id: str
    winner_text: str
    seg_index: int = -1
