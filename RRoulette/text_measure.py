"""
RRoulette — テキストブロック計測
  tkinter.font を使って複数行テキストブロックのサイズを計測する
"""
import tkinter.font as tkfont
from dataclasses import dataclass, field
from typing import List


@dataclass
class TextBlockMetrics:
    lines: List[str]
    font_family: str
    font_size: int
    line_height: int
    line_widths: List[int]
    block_width: int
    block_height: int


def measure_text_block(font_family: str, font_size: int, lines: List[str]) -> TextBlockMetrics:
    """指定フォントで複数行テキストブロックを計測する。"""
    font = tkfont.Font(family=font_family, size=font_size, weight="bold")
    line_height = max(1, font.metrics("linespace"))
    line_widths = [max(1, font.measure(line)) for line in lines]
    return TextBlockMetrics(
        lines=lines,
        font_family=font_family,
        font_size=font_size,
        line_height=line_height,
        line_widths=line_widths,
        block_width=max(line_widths) if line_widths else 1,
        block_height=line_height * len(lines),
    )
