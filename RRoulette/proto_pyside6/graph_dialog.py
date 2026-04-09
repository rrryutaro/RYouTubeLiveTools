"""
PySide6 プロトタイプ — 勝利履歴グラフダイアログ

現在パターンの項目別勝利数を横棒グラフで表示する独立ウィンドウ。
WinHistory の集計結果を描画源泉とする。

責務:
  - 項目別勝利数の横棒グラフ描画
  - 履歴なし時の空状態表示
  - 外部からの更新呼び出し（スピン完了・パターン切替・クリア）
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget

from design_settings import DesignSettings


class _GraphCanvas(QWidget):
    """勝利数棒グラフを描画するキャンバス。"""

    def __init__(self, design: DesignSettings, parent=None):
        super().__init__(parent)
        self._design = design
        self._items: list[tuple[str, int, int]] = []  # (name, item_idx, count)
        self._total = 0
        self._pattern_name = ""
        self.setMinimumHeight(100)

    def set_data(self, items: list[tuple[str, int, int]],
                 total: int, pattern_name: str):
        """グラフデータを設定して再描画する。

        Args:
            items: [(項目名, item_index, 当選回数), ...]
            total: 合計スピン回数
            pattern_name: パターン名（表示用）
        """
        self._items = items
        self._total = total
        self._pattern_name = pattern_name
        self.update()

    def set_design(self, design: DesignSettings):
        self._design = design
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        d = self._design
        w = self.width()
        h = self.height()

        # 背景
        painter.fillRect(0, 0, w, h, QColor(d.bg))

        if not self._items:
            painter.setPen(QColor(d.text_sub))
            painter.setFont(QFont(d.fonts.ui_family, 11))
            msg = f"「{self._pattern_name}」のデータがありません"
            painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, msg)
            painter.end()
            return

        n = len(self._items)
        max_count = max(c for _, _, c in self._items) if self._items else 1

        PAD_L = 8
        PAD_R = 8
        PAD_T = 10
        PAD_B = 10
        LABEL_W = min(140, max(60, int(w * 0.28)))
        VALUE_W = 90
        bar_area_w = max(10, w - PAD_L - LABEL_W - VALUE_W - PAD_R)

        avail_h = h - PAD_T - PAD_B
        bar_unit = avail_h / n if n > 0 else avail_h
        bar_h = max(4, bar_unit * 0.72)

        font_label = QFont(d.fonts.ui_family, 9)
        font_value = QFont(d.fonts.ui_family, 8)

        for i, (name, item_idx, count) in enumerate(self._items):
            from design_settings import SegmentDesign, SEGMENT_COLOR_PRESETS
            color = QColor(d.segment.color_for(item_idx))
            y_center = PAD_T + (i + 0.5) * bar_unit
            y0 = y_center - bar_h / 2
            y1 = y_center + bar_h / 2

            # 項目名ラベル（右揃え）
            painter.setPen(QColor(d.text))
            painter.setFont(font_label)
            label_rect = painter.boundingRect(
                PAD_L, int(y0), LABEL_W - 4, int(bar_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                name,
            )
            painter.drawText(
                PAD_L, int(y_center - label_rect.height() / 2),
                LABEL_W - 4, label_rect.height(),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

            # バー
            bw = bar_area_w * count / max_count if max_count > 0 else 0
            bx0 = PAD_L + LABEL_W
            painter.setPen(QPen(QColor(d.wheel.outline_color), 1))
            painter.setBrush(QBrush(color))
            painter.drawRect(int(bx0), int(y0), int(bw), int(bar_h))

            # 件数 + 割合
            pct = count / self._total * 100 if self._total > 0 else 0
            painter.setPen(QColor(d.text))
            painter.setFont(font_value)
            painter.drawText(
                int(bx0 + bw + 4), int(y_center - 8), VALUE_W, 16,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{count} ({pct:.1f}%)",
            )

        painter.end()


class GraphDialog(QDialog):
    """勝利履歴グラフダイアログ。

    非モーダルの Tool ウィンドウとして動作する。
    """

    def __init__(self, design: DesignSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("勝利履歴グラフ")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(400, 300)
        self.resize(500, 400)

        self._design = design

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._canvas = _GraphCanvas(design)
        layout.addWidget(self._canvas)

        self._apply_style()

    def _apply_style(self):
        d = self._design
        self.setStyleSheet(
            f"QDialog {{ background-color: {d.bg}; }}"
        )

    def update_graph(self, items: list[tuple[str, int, int]],
                     total: int, pattern_name: str):
        """グラフデータを更新する。

        Args:
            items: [(項目名, item_index, 当選回数), ...]
            total: 合計スピン回数
            pattern_name: パターン名
        """
        self._canvas.set_data(items, total, pattern_name)

    def update_design(self, design: DesignSettings):
        self._design = design
        self._canvas.set_design(design)
        self._apply_style()
