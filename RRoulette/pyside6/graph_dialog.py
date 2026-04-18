"""
PySide6 プロトタイプ — 勝利履歴グラフ

現在パターンの項目別勝利数を棒グラフで表示する。
WinHistory の集計結果を描画源泉とする。

責務:
  - 項目別勝利数の棒グラフ描画（横/縦）
  - 履歴なし時の空状態表示
  - 外部からの更新呼び出し（スピン完了・パターン切替・クリア）
  - ソート機能（項目順 / 回数順 / 名前順）— i382
  - 縦/横向き切替 — i383
  - in-panel 表示と別ウィンドウ双方に対応 — i389
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QFontMetrics
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QToolTip, QWidget,
)

from dark_theme import build_dialog_stylesheet
from design_settings import DesignSettings


class _GraphCanvas(QWidget):
    """勝利数棒グラフを描画するキャンバス。横/縦向きに対応。"""

    def __init__(self, design: DesignSettings, parent=None):
        super().__init__(parent)
        self._design = design
        self._items: list[tuple[str, int, int]] = []  # (name, item_idx, count)
        self._total = 0
        self._pattern_name = ""
        self._orientation: str = "horizontal"  # "horizontal" or "vertical"
        self.setMinimumHeight(100)
        self.setMouseTracking(True)  # i385: ツールチップ用

    def set_data(self, items: list[tuple[str, int, int]],
                 total: int, pattern_name: str):
        """グラフデータを設定して再描画する。"""
        self._items = items
        self._total = total
        self._pattern_name = pattern_name
        self.update()

    def set_design(self, design: DesignSettings):
        self._design = design
        self.update()

    def set_orientation(self, orientation: str):
        """向きを設定して再描画する。'horizontal' or 'vertical'"""
        self._orientation = orientation
        self.update()

    # ----------------------------------------------------------------
    #  i385: マウスホバー → ツールチップで完全名称表示
    # ----------------------------------------------------------------

    def mouseMoveEvent(self, event):
        name = self._hit_test(event.pos().x(), event.pos().y())
        if name:
            QToolTip.showText(event.globalPosition().toPoint(), name, self)
        else:
            QToolTip.hideText()
        event.accept()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def _hit_test(self, mx: int, my: int) -> str | None:
        """マウス座標に対応する項目の完全名称を返す。ヒットなしは None。"""
        if not self._items:
            return None
        n = len(self._items)
        w = self.width()
        h = self.height()

        if self._orientation == "vertical":
            PAD_L = 8
            PAD_R = 8
            bar_area_w = max(10, w - PAD_L - PAD_R)
            bar_unit = bar_area_w / n if n > 0 else bar_area_w
            # ベースライン以下（ラベル領域）もヒット対象に含める
            idx = int((mx - PAD_L) / bar_unit) if bar_unit > 0 else -1
            if 0 <= idx < n and mx >= PAD_L:
                return self._items[idx][0]
        else:
            PAD_T = 10
            PAD_B = 10
            avail_h = h - PAD_T - PAD_B
            bar_unit = avail_h / n if n > 0 else avail_h
            idx = int((my - PAD_T) / bar_unit) if bar_unit > 0 else -1
            if 0 <= idx < n and my >= PAD_T:
                return self._items[idx][0]
        return None

    # ----------------------------------------------------------------
    #  paintEvent ディスパッチ
    # ----------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        d = self._design
        w = self.width()
        h = self.height()

        painter.fillRect(0, 0, w, h, QColor(d.bg))

        if not self._items:
            painter.setPen(QColor(d.text_sub))
            painter.setFont(QFont(d.fonts.ui_family, 11))
            msg = f"「{self._pattern_name}」のデータがありません"
            painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, msg)
            painter.end()
            return

        if self._orientation == "vertical":
            self._paint_vertical(painter, w, h)
        else:
            self._paint_horizontal(painter, w, h)

        painter.end()

    # ----------------------------------------------------------------
    #  横棒グラフ（horizontal）
    # ----------------------------------------------------------------

    def _paint_horizontal(self, painter: QPainter, w: int, h: int):
        d = self._design
        n = len(self._items)
        max_count = max(c for _, _, c in self._items) if self._items else 1

        PAD_L = 8
        PAD_R = 8
        PAD_T = 10
        PAD_B = 10
        LABEL_W = min(140, max(60, int(w * 0.28)))
        VALUE_W = 90

        avail_h = h - PAD_T - PAD_B
        bar_unit = avail_h / n if n > 0 else avail_h
        bar_h = max(4, bar_unit * 0.72)

        # i387: 密度が高い場合は値ラベルを抑制してバー領域を広げる
        show_values = bar_unit >= 14
        effective_value_w = VALUE_W if show_values else 0
        bar_area_w = max(10, w - PAD_L - LABEL_W - effective_value_w - PAD_R)

        font_label = QFont(d.fonts.ui_family, 9)
        font_value = QFont(d.fonts.ui_family, 8)
        fm_label = QFontMetrics(font_label)  # i387: elidedText 用

        for i, (name, item_idx, count) in enumerate(self._items):
            color = QColor(d.segment.color_for(item_idx))
            y_center = PAD_T + (i + 0.5) * bar_unit
            y0 = y_center - bar_h / 2

            # 項目名ラベル（右揃え）— i387: elidedText で省略
            display_name = fm_label.elidedText(
                name, Qt.TextElideMode.ElideRight, LABEL_W - 8
            )
            painter.setPen(QColor(d.text))
            painter.setFont(font_label)
            painter.drawText(
                PAD_L, int(y_center - fm_label.height() / 2),
                LABEL_W - 4, fm_label.height(),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                display_name,
            )

            # バー
            bw = bar_area_w * count / max_count if max_count > 0 else 0
            bx0 = PAD_L + LABEL_W
            painter.setPen(QPen(QColor(d.wheel.outline_color), 1))
            painter.setBrush(QBrush(color))
            painter.drawRect(int(bx0), int(y0), int(bw), int(bar_h))

            # 件数 + 割合 — i387: 密度が高い場合は非表示
            if show_values:
                pct = count / self._total * 100 if self._total > 0 else 0
                painter.setPen(QColor(d.text))
                painter.setFont(font_value)
                painter.drawText(
                    int(bx0 + bw + 4), int(y_center - 8), VALUE_W, 16,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"{count} ({pct:.1f}%)",
                )

    # ----------------------------------------------------------------
    #  縦棒グラフ（vertical）
    # ----------------------------------------------------------------

    def _paint_vertical(self, painter: QPainter, w: int, h: int):
        d = self._design
        n = len(self._items)
        max_count = max(c for _, _, c in self._items) if self._items else 1

        font_label = QFont(d.fonts.ui_family, 8)
        font_value = QFont(d.fonts.ui_family, 7)
        fm_label = QFontMetrics(font_label)

        # i384: 固定 PAD_B を使い、そこから逆算して最大ラベル表示幅を決める。
        # PAD_B = 60px 固定。45 度回転時の水平進行距離 = PAD_B / sin(45°) ≈ PAD_B * 1.414
        # ただし「余白ギリギリまで使う」と隣と重なるため 0.9 係数で少し抑える。
        PAD_L = 8
        PAD_R = 8
        PAD_T = 4
        PAD_B = 60            # i384: 固定余白（文字列長に依存しない）

        # 45度回転で PAD_B 内に収まる最大テキスト幅（px）
        _SIN45 = 0.7071
        max_label_draw_px = max(20, int(PAD_B / _SIN45 * 0.9))

        bar_area_w = max(10, w - PAD_L - PAD_R)
        bar_unit = bar_area_w / n if n > 0 else bar_area_w
        bar_w = max(4, bar_unit * 0.72)

        # i387: 密度が高い場合はバー上部の値ラベルを抑制してバー領域を広げる
        show_values = bar_unit >= 20
        VALUE_H = 20 if show_values else 0

        bar_area_h = max(20, h - PAD_T - PAD_B - VALUE_H)
        baseline_y = PAD_T + VALUE_H + bar_area_h

        for i, (name, item_idx, count) in enumerate(self._items):
            color = QColor(d.segment.color_for(item_idx))
            x_center = PAD_L + (i + 0.5) * bar_unit

            bh = int(bar_area_h * count / max_count) if max_count > 0 else 0
            bar_x = int(x_center - bar_w / 2)
            bar_y = int(baseline_y - bh)

            # バー描画
            painter.setPen(QPen(QColor(d.wheel.outline_color), 1))
            painter.setBrush(QBrush(color))
            if bh > 0:
                painter.drawRect(bar_x, bar_y, int(bar_w), bh)

            # 件数 + 割合（バー上部）— i387: 密度が高い場合は非表示
            if show_values:
                pct = count / self._total * 100 if self._total > 0 else 0
                painter.setPen(QColor(d.text))
                painter.setFont(font_value)
                painter.drawText(
                    bar_x - 4, int(baseline_y - bar_area_h) - VALUE_H,
                    int(bar_w) + 8, VALUE_H,
                    Qt.AlignmentFlag.AlignCenter,
                    f"{count}({pct:.0f}%)",
                )

            # i384: 項目ラベル — 45度回転 + elidedText で省略表示
            # max_label_draw_px を超える名前は末尾を "…" で切り詰める
            display_name = fm_label.elidedText(
                name, Qt.TextElideMode.ElideRight, max_label_draw_px
            )
            painter.save()
            painter.setPen(QColor(d.text))
            painter.setFont(font_label)
            painter.translate(x_center, baseline_y + 4)
            painter.rotate(45)
            painter.drawText(
                0, -fm_label.height() // 2,
                max_label_draw_px + 4, fm_label.height(),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                display_name,
            )
            painter.restore()


# ----------------------------------------------------------------
#  ソートモード定義（i382）
# ----------------------------------------------------------------

_SORT_MODES: list[tuple[str, str]] = [
    ("default",    "項目順"),
    ("count_desc", "回数順"),
    ("name_asc",   "名前順"),
]

# i383: 向きモード定義
_ORIENT_MODES: list[tuple[str, str]] = [
    ("horizontal", "横"),
    ("vertical",   "縦"),
]


class GraphWidget(QWidget):
    """グラフコントロール + キャンバスの複合ウィジェット。

    in-panel 表示・別ウィンドウ双方で再利用できる共有コンポーネント。

    i389: GraphDialog と in-panel（RoulettePanel 埋め込み）の共有グラフ本体。
    """

    orientation_changed = Signal(str)  # i386: 向き変更時に emit
    close_requested = Signal()         # i389: in-panel 閉じる要求（show_close_btn=True 時に使用）

    def __init__(self, design: DesignSettings, *,
                 initial_orientation: str = "horizontal",
                 show_close_btn: bool = False,
                 parent=None):
        super().__init__(parent)
        self._design = design

        # ソート状態・向き状態・生データ
        self._sort_mode: str = "default"
        self._orientation: str = initial_orientation
        self._raw_items: list[tuple[str, int, int]] = []
        self._raw_total: int = 0
        self._raw_pattern: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # コントロール行（ソートボタン + セパレータ + 向きボタン [+ 閉じるボタン]）
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(4)

        # ソートボタン
        self._sort_btns: dict[str, QPushButton] = {}
        for mode, label in _SORT_MODES:
            btn = QPushButton(label)
            btn.setFont(QFont("Meiryo", 8))
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, m=mode: self._on_sort_clicked(m)
            )
            ctrl_row.addWidget(btn)
            self._sort_btns[mode] = btn

        ctrl_row.addStretch()

        # 向きボタン（i383）
        self._orient_btns: dict[str, QPushButton] = {}
        for orient, label in _ORIENT_MODES:
            btn = QPushButton(label)
            btn.setFont(QFont("Meiryo", 8))
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, o=orient: self._on_orient_clicked(o)
            )
            ctrl_row.addWidget(btn)
            self._orient_btns[orient] = btn

        # 閉じるボタン（i389: in-panel 用）
        if show_close_btn:
            ctrl_row.addSpacing(6)
            close_btn = QPushButton("×")
            close_btn.setFont(QFont("Meiryo", 9))
            close_btn.setFixedSize(22, 22)
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            close_btn.setToolTip("グラフを閉じる")
            close_btn.clicked.connect(self.close_requested.emit)
            ctrl_row.addWidget(close_btn)

        layout.addLayout(ctrl_row)

        self._canvas = _GraphCanvas(design)
        self._canvas.set_orientation(self._orientation)
        layout.addWidget(self._canvas, 1)

        self._apply_style()

    # ----------------------------------------------------------------
    #  スタイル
    # ----------------------------------------------------------------

    def _apply_style(self):
        self.setStyleSheet(build_dialog_stylesheet(self._design))
        self._update_btn_styles()

    def _update_btn_styles(self):
        """ソート・向きボタンのアクティブ状態を反映する。"""
        d = self._design
        active_style = (
            f"QPushButton {{"
            f"  background-color: {d.accent}; color: {d.bg};"
            f"  border: none; border-radius: 3px; padding: 2px 8px;"
            f"}}"
        )
        inactive_style = (
            f"QPushButton {{"
            f"  background-color: {d.separator}; color: {d.text};"
            f"  border: none; border-radius: 3px; padding: 2px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {d.accent}; color: {d.bg}; }}"
        )
        for mode, btn in self._sort_btns.items():
            btn.setStyleSheet(active_style if mode == self._sort_mode else inactive_style)
        for orient, btn in self._orient_btns.items():
            btn.setStyleSheet(active_style if orient == self._orientation else inactive_style)

    # ----------------------------------------------------------------
    #  ソート操作（i382）
    # ----------------------------------------------------------------

    def _on_sort_clicked(self, mode: str):
        self._sort_mode = mode
        self._update_btn_styles()
        self._apply_sort_and_draw()

    # ----------------------------------------------------------------
    #  向き操作（i383）
    # ----------------------------------------------------------------

    def _on_orient_clicked(self, orientation: str):
        self._orientation = orientation
        self._canvas.set_orientation(orientation)
        self._update_btn_styles()
        self._apply_sort_and_draw()
        self.orientation_changed.emit(orientation)  # i386: 永続化用

    def set_orientation(self, orientation: str):
        """向きを外部から設定する（永続化設定ロード時など）。

        i386 / i389: シグナルは emit しない（設定の読み込みなので保存不要）。
        """
        if self._orientation == orientation:
            return
        self._orientation = orientation
        self._canvas.set_orientation(orientation)
        self._update_btn_styles()
        self._apply_sort_and_draw()

    # ----------------------------------------------------------------
    #  描画
    # ----------------------------------------------------------------

    def _apply_sort_and_draw(self):
        """ソートモードに従って items を並び替えてキャンバスに描画する。"""
        items = list(self._raw_items)
        if self._sort_mode == "count_desc":
            items.sort(key=lambda x: x[2], reverse=True)
        elif self._sort_mode == "name_asc":
            items.sort(key=lambda x: x[0])
        self._canvas.set_data(items, self._raw_total, self._raw_pattern)

    # ----------------------------------------------------------------
    #  公開 API
    # ----------------------------------------------------------------

    def update_graph(self, items: list[tuple[str, int, int]],
                     total: int, pattern_name: str):
        """グラフデータを更新する。

        Args:
            items: [(項目名, item_index, 当選回数), ...]  ※ item_entries 順
            total: 合計スピン回数
            pattern_name: パターン名
        """
        self._raw_items = items
        self._raw_total = total
        self._raw_pattern = pattern_name
        self._apply_sort_and_draw()

    def update_design(self, design: DesignSettings):
        self._design = design
        self._canvas.set_design(design)
        self._apply_style()


class GraphDialog(QDialog):
    """勝利履歴グラフダイアログ。

    非モーダルの Tool ウィンドウとして動作する。
    i389: GraphWidget のダイアログラッパー。描画ロジックは GraphWidget が担う。
    """

    orientation_changed = Signal(str)  # i386: 向き変更時に emit

    def __init__(self, design: DesignSettings, parent=None,
                 initial_orientation: str = "horizontal"):
        super().__init__(parent)
        self.setWindowTitle("勝利履歴グラフ")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(400, 300)
        self.resize(500, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._widget = GraphWidget(
            design,
            initial_orientation=initial_orientation,
            show_close_btn=False,
            parent=self,
        )
        self._widget.orientation_changed.connect(self.orientation_changed)
        layout.addWidget(self._widget)

    # ----------------------------------------------------------------
    #  公開 API（GraphWidget へ委譲）
    # ----------------------------------------------------------------

    def update_graph(self, items: list[tuple[str, int, int]],
                     total: int, pattern_name: str):
        """グラフデータを更新する（呼び出し元インターフェース不変）。"""
        self._widget.update_graph(items, total, pattern_name)

    def update_design(self, design: DesignSettings):
        self._widget.update_design(design)
