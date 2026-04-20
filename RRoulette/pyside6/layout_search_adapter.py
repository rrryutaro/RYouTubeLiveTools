"""
layout_search_adapter.py — layout_search PySide6 接続層

layout_search.py は import 時に `import tkinter.font as tkfont` を実行するため、
このモジュールが tkinter.font のモックを sys.modules へ挿入してから
layout_search を import し、_make_font を Qt 実装に差し替える。

責務:
  - tkinter.font モンキーパッチ（sys.modules へのモック挿入）
  - layout_search._make_font を make_qt_font (QtFontAdapter) で置き換え
  - build_all_sector_layouts / LayoutResult / LinePlacement の re-export

font 計測境界:
  layout_search.py が呼ぶ font インターフェースは次の 2 メソッドのみ:
    font.measure(text: str)   → int  テキスト幅 (px)
    font.metrics("linespace") → int  行高さ (px)
  これらは font_adapter.py の QtFontAdapter が Qt (QFontMetrics) で実装する。
  この境界より外側（layout_search ロジック本体）は font 実装に依存しない。

PySide6 側のコードは bridge を経由せず、このモジュールを直接使うこと。
"""

import sys
import os
import types

# ── RRoulette ルートを sys.path に追加 ───────────────────────────────
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

# ── font_adapter: Qt 計測実装 ────────────────────────────────────────
from font_adapter import make_qt_font, QtFontAdapter

# ── tkinter.font モック挿入（layout_search の import 前に必須） ──────
# layout_search は module-level で `import tkinter.font as tkfont` を実行する。
# tkinter 本体も未ロードの場合があるため両方モックする。
if "tkinter" not in sys.modules:
    _mock_tk = types.ModuleType("tkinter")
    sys.modules["tkinter"] = _mock_tk
if "tkinter.font" not in sys.modules:
    _mock_tkfont = types.ModuleType("tkinter.font")
    _mock_tkfont.Font = QtFontAdapter  # 形式的な代替（直接は使われない）
    sys.modules["tkinter.font"] = _mock_tkfont

# ── layout_search を import し _make_font を Qt 実装に差し替え ────────
import layout_search
layout_search._make_font = make_qt_font

# ── re-export ────────────────────────────────────────────────────────
from layout_search import (
    build_all_sector_layouts,
    LayoutResult,
    LinePlacement,
)
