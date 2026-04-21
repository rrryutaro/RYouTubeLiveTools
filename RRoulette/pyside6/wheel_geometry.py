"""
wheel_geometry.py — PySide6 側から直接参照できる幾何計算層

RRoulette ルート (../geometry.py) の純幾何関数・型を PySide6 側に提供する。
tkinter / PySide6 ウィジェットに依存しない純数値ロジックのみ。

PySide6 モジュールは幾何関数をこのモジュールから直接参照すること。

公開 API:
  データクラス:
    SafeSector — 扇形の安全描画領域
  関数:
    get_sector_safe_area(...)          → SafeSector
    get_radial_width_at_tangential_offset(...) → float
    polar_to_canvas(cx, cy, r, deg)    → (float, float)
    normalize_angle_deg(angle)         → float
"""

import sys
import os

# ── RRoulette ルートを sys.path に追加 ───────────────────────────────
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

# ── geometry.py から re-export ───────────────────────────────────────
from geometry import (
    SafeSector,
    get_sector_safe_area,
    get_radial_width_at_tangential_offset,
    polar_to_canvas,
    normalize_angle_deg,
)
