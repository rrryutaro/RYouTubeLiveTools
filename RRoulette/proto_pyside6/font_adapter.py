"""
PySide6 プロトタイプ — フォントアダプター

既存の layout_search.py は tkinter.font.Font のインターフェースに依存:
  - font.measure(text) → テキスト幅 (px)
  - font.metrics("linespace") → 行高さ (px)

このモジュールは QFontMetrics で同等の機能を提供するアダプタークラスを提供し、
layout_search.py を PySide6 環境で利用可能にする。
"""

from PySide6.QtGui import QFont, QFontMetrics


class QtFontAdapter:
    """tkinter.font.Font 互換のインターフェースを QFontMetrics で実装する。

    layout_search.py の _make_font() が返すオブジェクトと同じメソッドを提供:
      - .measure(text) → int  テキスト幅（ピクセル）
      - .metrics(key)  → int  フォントメトリクス（"linespace" のみ対応）
    """

    def __init__(self, family: str, size: int, weight: str = "bold"):
        qweight = QFont.Weight.Bold if weight == "bold" else QFont.Weight.Normal
        self._qfont = QFont(family, size, qweight)
        self._metrics = QFontMetrics(self._qfont)

    def measure(self, text: str) -> int:
        """テキストの水平方向の幅をピクセル単位で返す。"""
        if not text:
            return 0
        return self._metrics.horizontalAdvance(text)

    def metrics(self, key: str) -> int:
        """フォントメトリクスを返す。layout_search.py は "linespace" のみ使用。"""
        if key == "linespace":
            return self._metrics.lineSpacing()
        if key == "ascent":
            return self._metrics.ascent()
        if key == "descent":
            return self._metrics.descent()
        raise KeyError(f"Unknown font metric: {key}")

    @property
    def qfont(self) -> QFont:
        """内部の QFont オブジェクトを返す（QPainter での描画用）。"""
        return self._qfont


def make_qt_font(family: str, size: int) -> QtFontAdapter:
    """layout_search.py の _make_font() を置き換えるファクトリー関数。"""
    return QtFontAdapter(family, size, "bold")
