"""
PySide6 プロトタイプ — ルーレットコンテキスト

マルチルーレット化のためのデータ構造。
1つのルーレットに紐づく状態（パネル・項目データ・セグメント）を束ねる。

現時点ではまだ本格利用しない。将来 RouletteManager が管理する単位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roulette_panel import RoulettePanel
    from item_entry import ItemEntry
    from bridge import Segment


@dataclass
class RouletteContext:
    """1つのルーレットに紐づくコンテキスト。

    Attributes:
        roulette_id: 一意識別子
        panel: 対応する RoulettePanel インスタンス
        item_entries: 項目データ（全件、disabled 含む）
        segments: 構築済みセグメントリスト
    """

    roulette_id: str
    panel: RoulettePanel
    item_entries: list[ItemEntry] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
