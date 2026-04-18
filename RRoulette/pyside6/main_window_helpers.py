"""
main_window_helpers.py — MainWindow 用内部ヘルパークラス

i456: main_window.py から分離。
責務:
  - _SpaceSpinFilter  : Space キー同時スピン用 QApplication レベルイベントフィルタ
  - _MainWindowDragBar: メインウィンドウ上部のドラッグバー（ウィンドウ全体の移動）

どちらも MainWindow を直接 import せず、コンストラクタ引数で参照を受け取る。
"""

from PySide6.QtCore import Qt, QPoint, QObject, QEvent
from PySide6.QtGui import QCursor, QPainter, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
)


class _SpaceSpinFilter(QObject):
    """i344: Space キー同時スピン用 QApplication レベルイベントフィルタ。

    QApplication 全体にインストールし、フォーカスウィジェットに関係なく
    Space キーを捕捉する。テキスト入力系ウィジェットにフォーカスがある場合は
    素通しし、それ以外は _start_all_visible_spin() を呼んでイベントを消費する。

    keyPressEvent (QMainWindow) への依存を廃止することで、ルーレットパネルや
    選択ハンドルをクリック後も Space が確実に発火する。
    """

    _TEXT_INPUT_TYPES = (
        QLineEdit, QPlainTextEdit, QTextEdit,
        QSpinBox, QDoubleSpinBox,
    )

    def __init__(self, main_window):
        super().__init__(main_window)
        self._mw = main_window

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Space
                and not event.isAutoRepeat()):
            fw = QApplication.focusWidget()
            if isinstance(fw, self._TEXT_INPUT_TYPES):
                return False  # テキスト入力系はスルー
            self._mw._start_all_visible_spin()
            return True  # イベント消費
        return False


class _MainWindowDragBar(QWidget):
    """メインウィンドウ上部のドラッグバー。ドラッグでウィンドウ全体を移動する。"""

    _BAR_HEIGHT = 20

    def __init__(self, main_window: QMainWindow, design, parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._design = design
        self._dragging = False
        self._drag_start = QPoint()
        self._start_pos = QPoint()
        self.setFixedHeight(self._BAR_HEIGHT)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._design.separator))
        color = QColor(self._design.text_sub)
        color.setAlpha(140)
        p.setPen(color)
        cx = self.width() // 2
        cy = self._BAR_HEIGHT // 2
        for i in range(-3, 4):
            p.drawPoint(cx + i * 4, cy - 2)
            p.drawPoint(cx + i * 4, cy + 2)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
            self._start_pos = self._mw.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        self._mw.move(self._start_pos + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()

    def update_design(self, design):
        self._design = design
        self.update()
