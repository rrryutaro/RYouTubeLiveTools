"""
RRoulette PySide6 — translucent screen region selector.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class ScreenCaptureSelector(QWidget):
    """Full-desktop overlay for selecting a capture rectangle."""

    captured = Signal(QImage)
    canceled = Signal()

    _MIN_SIZE = 8

    def __init__(self, parent=None, capture_method: str = "qt"):
        super().__init__(parent)
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selection = QRect()
        self._capture_method = capture_method

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        desktop = QRect()
        for screen in QApplication.screens():
            desktop = desktop.united(screen.geometry()) if not desktop.isNull() else screen.geometry()
        if desktop.isNull():
            desktop = QApplication.primaryScreen().geometry()
        self.setGeometry(desktop)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 96))

        if not self._selection.isNull():
            local_rect = self._selection.translated(-self.geometry().topLeft())
            painter.fillRect(local_rect, QColor(255, 255, 255, 32))
            pen = QPen(QColor(80, 180, 255), 2)
            painter.setPen(pen)
            painter.drawRect(local_rect.adjusted(1, 1, -1, -1))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._origin = event.globalPosition().toPoint()
        self._current = self._origin
        self._selection = QRect(self._origin, self._current).normalized()
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is None:
            event.ignore()
            return
        self._current = event.globalPosition().toPoint()
        self._selection = QRect(self._origin, self._current).normalized()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            event.ignore()
            return
        self._current = event.globalPosition().toPoint()
        self._selection = QRect(self._origin, self._current).normalized()
        event.accept()

        if (self._selection.width() < self._MIN_SIZE
                or self._selection.height() < self._MIN_SIZE):
            self.hide()
            self.canceled.emit()
            self.deleteLater()
            return

        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(80, self._capture_selection)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self.hide()
            self.canceled.emit()
            self.deleteLater()
            return
        super().keyPressEvent(event)

    def _capture_selection(self):
        rect = self._selection
        if self._capture_method == "gdi":
            image = self._capture_selection_gdi(rect)
            self.captured.emit(image)
            self.deleteLater()
            return
        screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
        pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        self.captured.emit(pixmap.toImage())
        self.deleteLater()

    def _capture_selection_gdi(self, rect: QRect) -> QImage:
        """Capture a screen rectangle with Windows GDI into memory."""
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        width = max(1, rect.width())
        height = max(1, rect.height())
        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

        try:
            SRCCOPY = 0x00CC0020
            CAPTUREBLT = 0x40000000
            if not gdi32.BitBlt(
                mem_dc, 0, 0, width, height,
                screen_dc, rect.x(), rect.y(),
                SRCCOPY | CAPTUREBLT,
            ):
                return QImage()

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", ctypes.c_uint32),
                    ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32),
                    ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32),
                    ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

            BI_RGB = 0
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB

            buffer_size = width * height * 4
            buffer = ctypes.create_string_buffer(buffer_size)
            lines = gdi32.GetDIBits(
                mem_dc, bitmap, 0, height, buffer,
                ctypes.byref(info), 0,
            )
            if lines == 0:
                return QImage()
            image = QImage(
                buffer.raw,
                width,
                height,
                width * 4,
                QImage.Format.Format_ARGB32,
            )
            return image.copy()
        finally:
            gdi32.SelectObject(mem_dc, old_bitmap)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(None, screen_dc)
