"""
bridge.py — 既存ロジック橋渡し層（互換層）

既存 RRoulette のロジック資産（constants, design_settings, geometry,
layout_search, config_utils）と PySide6 UI 層を接続する。

責務:
  - sys.path を通して既存モジュールを import 可能にする
  - layout_search の tkinter.font 依存を QtFontAdapter でモンキーパッチ
  - デザイン設定クラス / geometry 関数 / レイアウト検索の re-export
  - 設定読み込みラッパー（load_app_settings / load_design）
  - 後方互換のための定数 re-export（純定数は app_constants.py を優先）

切り出し済みの専用モジュール:
  - app_constants.py   — 純定数（SIZE_PROFILES / MIN_W / ITEM_MAX_* 等）
  - config_io.py       — load_config / save_config
  - pattern_store.py   — パターン管理純ロジック
  - item_data_io.py    — 項目データ I/O（load_item_entries 等）
  - segment_builder.py — セグメント構築純ロジック

bridge に残る主な責務:
  - layout_search の tkinter.font モンキーパッチ（PySide6 互換化）
  - DesignSettings / DesignPresetManager / design_settings 系の re-export
  - geometry 関数の re-export（SafeSector / polar_to_canvas 等）
  - build_all_sector_layouts / LayoutResult（monkey-patch 後に有効）
  - load_app_settings / load_design（AppSettings 構築ラッパー）
  - 後方互換のための純定数 re-export（SIZE_PROFILES 等）

データの流れ（2系統）:

  【アプリ設定】AppSettings — 表示・スピン・デザイン等のアプリ全体設定
    config file → load_config() → raw dict
                                    ├→ load_app_settings() → AppSettings
                                    └→ load_design()       → DesignSettings

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

# ── 既存モジュールの import ───────────────────────────────────────
# tkinter 非依存モジュール: そのまま import
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
from geometry import (
    SafeSector, get_sector_safe_area,
    get_radial_width_at_tangential_offset,
    polar_to_canvas, normalize_angle_deg,
)
# ── 設定 I/O / パターン管理 / 項目データ — 専用モジュールから re-export ──
# これらは bridge から切り出し済み。後方互換のため bridge 経由でも参照可能。
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

# ── layout_search の tkinter.font 依存をモンキーパッチ ─────────────
# layout_search は import 時に `import tkinter.font as tkfont` を実行するため、
# import 前にモックモジュールを挿入して回避し、_make_font を差し替える。
from font_adapter import make_qt_font, QtFontAdapter

# tkinter.font のモックを sys.modules に挿入
import types
_mock_tkfont = types.ModuleType("tkinter.font")
_mock_tkfont.Font = QtFontAdapter  # 形式的な代替（直接は使われない）
if "tkinter" not in sys.modules:
    _mock_tk = types.ModuleType("tkinter")
    sys.modules["tkinter"] = _mock_tk
if "tkinter.font" not in sys.modules:
    sys.modules["tkinter.font"] = _mock_tkfont

# これで layout_search を import 可能に
import layout_search
from layout_search import (
    build_all_sector_layouts,
    LayoutResult, LinePlacement,
)

# _make_font を QtFontAdapter 版に差し替え
layout_search._make_font = make_qt_font


# ── 設定 / 項目 ──────────────────────────────────────────────────

from app_settings import AppSettings
from item_entry import ItemEntry


def load_app_settings(config: dict | None = None) -> AppSettings:
    """config dict から型付き AppSettings を構築する。

    MainWindow は raw config dict ではなくこの関数経由で設定を取得する。
    将来設定の追加時は AppSettings.from_config() のみ修正すればよい。
    """
    if config is None:
        config = load_config()
    return AppSettings.from_config(config)


def load_design(config: dict | None = None) -> DesignSettings:
    """設定辞書からデザイン設定を復元する。"""
    if config is None:
        config = load_config()
    return DesignSettings.from_dict(config.get("design", {}))


