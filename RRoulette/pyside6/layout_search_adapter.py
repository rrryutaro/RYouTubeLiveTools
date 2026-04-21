"""
layout_search_adapter.py — layout_search PySide6 接続層

layout_search.py は font 計測実装を外部から注入する設計になっている。
このモジュールが Qt 実装（QtFontAdapter）を _make_font として差し込む。

tkinter.font mock は layout_search.py が tkinter.font を直接 import しなくなった
（s06_i010）ため不要。

責務:
  - layout_search._make_font を make_qt_font (QtFontAdapter) で設定
  - build_all_sector_layouts / LayoutResult / LinePlacement の re-export

font 計測境界（FontAdapter Protocol）:
  layout_search.py が要求するインターフェースは次の 2 メソッドのみ:
    font.measure(text: str)   → int  テキスト幅 (px)
    font.metrics("linespace") → int  行高さ (px)
  QtFontAdapter が Qt (QFontMetrics) でこのインターフェースを実装する。

PySide6 側のコードはこのモジュールを直接使うこと。
"""

import sys
import os

# ── RRoulette ルートを sys.path に追加 ───────────────────────────────
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

# ── font_adapter: Qt 計測実装 ────────────────────────────────────────
from font_adapter import make_qt_font

# ── layout_search を import し _make_font を Qt 実装に差し替え ────────
# layout_search._make_font はデフォルトで RuntimeError を発生させるスタブ。
# ここで QtFontAdapter ファクトリーを注入する。
import layout_search
layout_search._make_font = make_qt_font

# ── re-export ────────────────────────────────────────────────────────
from layout_search import (
    build_all_sector_layouts,
    LayoutResult,
    LinePlacement,
)
