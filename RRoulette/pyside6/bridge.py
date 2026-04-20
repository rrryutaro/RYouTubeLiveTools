"""
bridge.py — 既存ロジック橋渡し層（互換層）

既存 RRoulette のロジック資産（layout_search 等）と PySide6 UI 層を接続する。

bridge の残る責務:
  - 後方互換のための各種 re-export のみ
  - 実装はすべて専用モジュールへ切り出し済み

切り出し済みの専用モジュール:
  - app_constants.py          — 純定数（SIZE_PROFILES / MIN_W / ITEM_MAX_* 等）
  - app_settings.py           — AppSettings dataclass / AppSettings.load() ラッパー
  - design_models.py          — デザイン設定クラス / プリセット / load_design
  - wheel_geometry.py         — 幾何関数（SafeSector / polar_to_canvas 等）
  - config_io.py              — load_config / save_config
  - pattern_store.py          — パターン管理純ロジック
  - item_data_io.py           — 項目データ I/O（load_item_entries 等）
  - segment_builder.py        — セグメント構築純ロジック
  - layout_search_adapter.py  — tkinter.font monkey-patch + layout_search 接続層

データの流れ（2系統）:

  【アプリ設定】AppSettings — 表示・スピン・デザイン等のアプリ全体設定
    config file → load_config() → raw dict
                                    ├→ AppSettings.load() → AppSettings
                                    └→ load_design()      → DesignSettings

  【項目データ】ItemEntry — 各項目固有のテキスト・確率・分割等
    config file → load_config() → raw dict
                                    ├→ load_item_entries()            → list[ItemEntry]
                                    ├→ load_items()                   → list[str]
                                    └→ build_segments_from_config()   → list[Segment]

  【保存】
    AppSettings → to_config_patch() → config dict merge → save_config()
    ItemEntry   → save_item_entries(config, entries) → config dict update → save_config()
"""

import sys
import os

# ── 既存モジュールへのパスを通す ─────────────────────────────────
_RROULETTE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..")
)
if _RROULETTE_DIR not in sys.path:
    sys.path.append(_RROULETTE_DIR)

# ── 後方互換 re-export: 純定数 / 設定 / geometry ─────────────────
# 各専用モジュールから切り出し済み。bridge 経由での参照は後方互換のみ。
from constants import (
    SEGMENT_COLORS, BG, PANEL, ACCENT, DARK2, WHITE, GOLD,
    SIZE_PROFILES, MIN_W, MIN_H, MIN_R,
    SIDEBAR_W, CFG_PANEL_W, SIDEBAR_MIN_W,
    MAIN_PANEL_PAD, POINTER_OVERHANG, WHEEL_OUTER_MARGIN,
    MAIN_MIN_W, MAIN_MIN_H,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
    ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES,
    DONUT_DRAW_RADIUS, DONUT_HIT_RADIUS,
    Segment, VERSION,
)
from design_settings import (
    DesignSettings, DesignPresetManager,
    GlobalColors, WheelDesign, SegmentDesign, PointerDesign,
    LogDesign, FontSettings, WheelFontSettings, ResultDesign,
    DESIGN_PRESETS, DESIGN_PRESET_NAMES,
    SEGMENT_COLOR_PRESETS, SEGMENT_PRESET_NAMES,
)
# geometry は wheel_geometry.py へ切り出し済み。後方互換のため残す。
from geometry import (
    SafeSector, get_sector_safe_area,
    get_radial_width_at_tangential_offset,
    polar_to_canvas, normalize_angle_deg,
)
from config_io import load_config, save_config
from pattern_store import (
    get_pattern_names, get_current_pattern_name, set_current_pattern,
    add_pattern, delete_pattern, rename_pattern,
    get_pattern_ids, get_pattern_id, ensure_pattern_ids,
)
from item_data_io import (
    load_items, load_item_entries, load_all_item_entries,
    load_weights_from_config, save_item_entries,
)
from segment_builder import build_segments_from_entries, build_segments_from_config

# ── layout_search 系: layout_search_adapter.py へ切り出し済み ────────
# tkinter.font monkey-patch + layout_search 接続は layout_search_adapter.py が担う。
# bridge では後方互換のため re-export のみ残す。
from layout_search_adapter import (
    build_all_sector_layouts,
    LayoutResult, LinePlacement,
)


# ── 設定 / 項目 ──────────────────────────────────────────────────

from app_settings import AppSettings
from item_entry import ItemEntry
