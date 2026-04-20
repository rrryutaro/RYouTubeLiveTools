"""
app_constants.py — PySide6 側から直接参照できる純定数層

RRoulette ルート (../constants.py) の定数を PySide6 側に提供する。
tkinter / PySide6 ウィジェットに依存しない純データのみ。

bridge.py を経由せずに定数を参照したい PySide6 モジュールはこちらを使う。
bridge.py がまだ re-export しているものとの二重参照は問題なく共存できる
（どちらも RRoulette ルートの同一 constants.py を読む）。

bridge.py が先に import されている場合は sys.path 設定は no-op になる。
"""

import sys
import os

# ── RRoulette ルートを sys.path に追加 ───────────────────────────────
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

# ── constants.py から re-export ──────────────────────────────────────
from constants import (
    # カラー
    SEGMENT_COLORS,
    BG, PANEL, ACCENT, DARK2, WHITE, GOLD,

    # サイズプロファイル・最小サイズ
    SIZE_PROFILES,
    MIN_W, MIN_H, MIN_R,

    # パネル幅
    SIDEBAR_W, CFG_PANEL_W, SIDEBAR_MIN_W,

    # レイアウト余白
    MAIN_PANEL_PAD, POINTER_OVERHANG, WHEEL_OUTER_MARGIN,
    MAIN_MIN_W, MAIN_MIN_H,

    # ポインタープリセット
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,

    # 項目制限値
    ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES,

    # ドーナツ穴
    DONUT_DRAW_RADIUS, DONUT_HIT_RADIUS,

    # データクラス・バージョン
    Segment,
    VERSION,
)
