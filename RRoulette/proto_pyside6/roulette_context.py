"""
PySide6 プロトタイプ — ルーレットコンテキスト

マルチルーレット化のためのデータ構造。
1つのルーレットに紐づく状態（パネル・項目データ・セグメント）を束ねる。

現時点ではまだ本格利用しない。将来 RouletteManager が管理する単位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from per_roulette_settings import PerRouletteSettings

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
        settings: ルーレット個別設定（i368: PerRouletteSettings）
    """

    roulette_id: str
    panel: RoulettePanel
    item_entries: list[ItemEntry] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    # i338: per-roulette pattern state.
    # None = use global config (for "default" roulette only).
    # dict = {"パターン名": [raw_item_dict, ...]} (for additional roulettes).
    item_patterns: dict | None = field(default=None)
    current_pattern: str | None = field(default=None)
    # i407: パターン名 → 不変UUID のマップ（non-default ルーレット用）
    # default ルーレットは config["pattern_ids"] を使う。
    pattern_id_map: dict = field(default_factory=dict)
    # i407: 現在選択中パターンの UUID。ログフィルタの基準。
    current_pattern_id: str = ""
    # i368: ルーレット個別設定。各ルーレットが独立したインスタンスを保持する。
    # source-of-truth への移行は第2段階以降で行う。
    settings: PerRouletteSettings = field(default_factory=PerRouletteSettings)
    # i412: pattern import 時に記録した source_pattern_id → dest_pattern_id のマップ。
    # log import 時に pattern_id を destination 側に再マップするために使う（セッション内のみ保持）。
    imported_pattern_id_map: dict = field(default_factory=dict)
