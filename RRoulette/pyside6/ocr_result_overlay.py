"""
RRoulette PySide6 — OBS-visible OCR result overlay.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from design_models import DesignSettings
from screen_ocr import OcrImageOptions, ScreenOcrError, apply_ocr_adjustments, recognize_qimage


class CropImageView(QWidget):
    """Preview widget with OBS-like drag selection for OCR crop area."""

    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("rr_ocr_interactive", True)
        self._image = None
        self._zoom_percent = 100
        self._selection = QRect()
        self._drag_start = QPoint()
        self._drag_start_selection = QRect()
        self._drag_mode = ""
        self._dragging = False
        self._image_rect = QRect()
        self.setMinimumSize(260, 180)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, image):
        old_size = self._image.size() if self._image is not None and not self._image.isNull() else None
        self._image = image
        if old_size != image.size():
            self._selection = image.rect() if image is not None and not image.isNull() else QRect()
        self._update_size()
        self.update()

    def set_zoom_percent(self, value: int):
        self._zoom_percent = max(25, min(400, int(value)))
        self._update_size()
        self.update()

    def clear_selection(self):
        self._selection = QRect()
        self.selection_changed.emit()
        self.update()

    def selection_rect(self):
        return QRect(self._selection)

    def _update_size(self):
        if self._image is None or self._image.isNull():
            return
        w = max(1, int(self._image.width() * self._zoom_percent / 100))
        h = max(1, int(self._image.height() * self._zoom_percent / 100))
        self.setFixedSize(QSize(w + 24, h + 24))

    def _screen_to_image(self, pos: QPoint) -> QPoint:
        if self._image is None or self._image.isNull() or self._image_rect.isNull():
            return QPoint()
        x = (pos.x() - self._image_rect.x()) * self._image.width() / self._image_rect.width()
        y = (pos.y() - self._image_rect.y()) * self._image.height() / self._image_rect.height()
        return QPoint(
            max(0, min(self._image.width() - 1, int(x))),
            max(0, min(self._image.height() - 1, int(y))),
        )

    def _image_to_screen_rect(self, rect: QRect) -> QRect:
        if rect.isNull() or self._image is None or self._image.isNull():
            return QRect()
        sx = self._image_rect.width() / self._image.width()
        sy = self._image_rect.height() / self._image.height()
        return QRect(
            self._image_rect.x() + int(rect.x() * sx),
            self._image_rect.y() + int(rect.y() * sy),
            max(1, int(rect.width() * sx)),
            max(1, int(rect.height() * sy)),
        )

    def _selection_hit(self, pos: QPoint) -> str:
        if self._selection.isNull():
            return ""
        sel = self._image_to_screen_rect(self._selection.normalized())
        if not sel.adjusted(-10, -10, 10, 10).contains(pos):
            return ""
        edge = 10
        left = abs(pos.x() - sel.left()) <= edge
        right = abs(pos.x() - sel.right()) <= edge
        top = abs(pos.y() - sel.top()) <= edge
        bottom = abs(pos.y() - sel.bottom()) <= edge
        if top and left:
            return "top-left"
        if top and right:
            return "top-right"
        if bottom and left:
            return "bottom-left"
        if bottom and right:
            return "bottom-right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        if sel.contains(pos):
            return "move"
        return ""

    def _cursor_for_hit(self, hit: str):
        if hit == "move":
            return Qt.CursorShape.SizeAllCursor
        if hit in ("top-left", "bottom-right"):
            return Qt.CursorShape.SizeFDiagCursor
        if hit in ("top-right", "bottom-left"):
            return Qt.CursorShape.SizeBDiagCursor
        if hit in ("left", "right"):
            return Qt.CursorShape.SizeHorCursor
        if hit in ("top", "bottom"):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.CrossCursor

    def _clamp_selection(self, rect: QRect) -> QRect:
        if self._image is None or self._image.isNull():
            return QRect()
        r = rect.normalized()
        r = r.intersected(self._image.rect())
        if r.width() < 1 or r.height() < 1:
            return QRect()
        return r

    def _move_selection(self, current: QPoint) -> QRect:
        delta = current - self._drag_start
        r = QRect(self._drag_start_selection)
        r.translate(delta)
        if self._image is None or self._image.isNull():
            return r
        if r.left() < 0:
            r.moveLeft(0)
        if r.top() < 0:
            r.moveTop(0)
        if r.right() >= self._image.width():
            r.moveRight(self._image.width() - 1)
        if r.bottom() >= self._image.height():
            r.moveBottom(self._image.height() - 1)
        return r

    def _resize_selection(self, current: QPoint) -> QRect:
        r = QRect(self._drag_start_selection)
        mode = self._drag_mode
        if "left" in mode:
            r.setLeft(current.x())
        if "right" in mode:
            r.setRight(current.x())
        if "top" in mode:
            r.setTop(current.y())
        if "bottom" in mode:
            r.setBottom(current.y())
        return self._clamp_selection(r)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101820"))
        if self._image is None or self._image.isNull():
            painter.end()
            return

        display_w = max(1, int(self._image.width() * self._zoom_percent / 100))
        display_h = max(1, int(self._image.height() * self._zoom_percent / 100))
        x = max(12, (self.width() - display_w) // 2)
        y = max(12, (self.height() - display_h) // 2)
        self._image_rect = QRect(x, y, display_w, display_h)

        painter.drawImage(self._image_rect, self._image)
        painter.setPen(QPen(QColor("#5f6884"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(self._image_rect.adjusted(0, 0, -1, -1))

        if not self._selection.isNull():
            sel = self._image_to_screen_rect(self._selection.normalized())
            painter.fillRect(sel, QColor(80, 180, 255, 45))
            painter.setPen(QPen(QColor("#50b4ff"), 2))
            painter.drawRect(sel.adjusted(1, 1, -1, -1))
            overlay = QBrush(QColor(0, 0, 0, 95))
            for r in (
                QRect(self._image_rect.left(), self._image_rect.top(), self._image_rect.width(), sel.top() - self._image_rect.top()),
                QRect(self._image_rect.left(), sel.bottom(), self._image_rect.width(), self._image_rect.bottom() - sel.bottom()),
                QRect(self._image_rect.left(), sel.top(), sel.left() - self._image_rect.left(), sel.height()),
                QRect(sel.right(), sel.top(), self._image_rect.right() - sel.right(), sel.height()),
            ):
                painter.fillRect(r, overlay)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        pos = event.position().toPoint()
        hit = self._selection_hit(pos)
        if hit:
            self._dragging = True
            self._drag_mode = hit
            self._drag_start = self._screen_to_image(pos)
            self._drag_start_selection = QRect(self._selection)
            self.setCursor(self._cursor_for_hit(hit))
            event.accept()
            return
        if not self._selection.isNull():
            event.accept()
            return
        if not self._image_rect.contains(pos):
            event.accept()
            return
        self._dragging = True
        self._drag_mode = "create"
        self._drag_start = self._screen_to_image(event.position().toPoint())
        self._selection = QRect(self._drag_start, self._drag_start)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._drag_mode = ""
            if self._selection.width() < 4 or self._selection.height() < 4:
                self._selection = QRect()
            self.selection_changed.emit()
            self.update()
            event.accept()
            return
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            hit = self._selection_hit(event.position().toPoint())
            self.setCursor(self._cursor_for_hit(hit))
            event.accept()
            return
        current = self._screen_to_image(event.position().toPoint())
        if self._drag_mode == "move":
            self._selection = self._move_selection(current)
        elif self._drag_mode == "create":
            self._selection = self._clamp_selection(QRect(self._drag_start, current))
        else:
            self._selection = self._resize_selection(current)
        self.update()
        event.accept()


class OcrResultOverlay(QWidget):
    """Temporary child overlay that shows captured OCR text and copy controls."""

    closed = Signal()

    def __init__(
            self, text: str, design: DesignSettings, parent: QWidget, image=None,
            capture_method: str = "qt", capture_method_changed=None):
        super().__init__(parent)
        self._design = design
        self._source_image = image
        self._capture_method_changed = capture_method_changed
        self._scale_slider = None
        self._brightness_slider = None
        self._contrast_slider = None
        self._threshold_slider = None
        self._invert_cb = None
        self._preview_label = None
        self._status_lbl = None
        self._tabs = None
        self._card = None
        self._crop_view = None
        self._preview_image = None
        self._display_zoom_slider = None
        self._resizing = False
        self._moving_card = False
        self._resize_edge = ""
        self._resize_start = QPoint()
        self._resize_start_size = None
        self._resize_start_geometry = QRect()
        self._move_start = QPoint()
        self._move_start_pos = QPoint()
        self._resize_override_cursor = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setGeometry(parent.rect())
        self.raise_()
        self.setProperty("rr_ocr_interactive", True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 150);")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        card = QFrame(self)
        card.setProperty("rr_ocr_interactive", True)
        self._card = card
        card.setFixedSize(
            min(max(560, parent.width() // 2), max(320, parent.width() - 28)),
            min(max(420, parent.height() // 2), max(280, parent.height() - 28)),
        )
        card.setStyleSheet(
            f"QFrame {{ background-color: {design.panel}; "
            f"border: 2px solid {design.separator}; border-radius: 8px; }}"
            "QLabel { border: none; background: transparent; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        title = QLabel("OCR取り込み結果", card)
        title.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {design.text};")
        layout.addWidget(title)

        tabs = QTabWidget(card)
        self._tabs = tabs
        tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {design.separator}; }}"
            f"QTabBar::tab {{ background: {design.separator}; color: {design.text}; "
            "padding: 5px 10px; border-top-left-radius: 3px; border-top-right-radius: 3px; }"
            f"QTabBar::tab:selected {{ background: {design.accent}; }}"
        )

        result_page = QWidget(tabs)
        result_layout = QVBoxLayout(result_page)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(8)

        self._text_edit = QPlainTextEdit(result_page)
        self._text_edit.setPlainText(text)
        self._text_edit.selectAll()
        self._text_edit.setFont(QFont("Meiryo", 10))
        self._text_edit.setMinimumHeight(140)
        self._text_edit.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {design.bg}; color: {design.text}; "
            f"border: 1px solid {design.separator}; border-radius: 4px; padding: 6px; }}"
        )
        result_layout.addWidget(self._text_edit)

        hint = QLabel("内容を確認してコピーし、任意の項目リストへ貼り付けてください。", result_page)
        hint.setFont(QFont("Meiryo", 8))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {design.text_sub};")
        result_layout.addWidget(hint)
        tabs.addTab(result_page, "結果")

        if image is not None and not image.isNull():
            adjust_page = self._build_adjust_page(tabs)
            tabs.addTab(adjust_page, "画像調整")
        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        capture_lbl = QLabel("OCRキャプチャ:", card)
        capture_lbl.setFont(QFont("Meiryo", 8))
        capture_lbl.setStyleSheet(f"color: {design.text_sub};")
        btn_row.addWidget(capture_lbl)
        self._capture_method_combo = QComboBox(card)
        self._capture_method_combo.setProperty("rr_ocr_interactive", True)
        self._capture_method_combo.setFont(QFont("Meiryo", 8))
        self._capture_method_combo.addItems(["標準", "Windows GDI"])
        self._capture_method_values = ["qt", "gdi"]
        self._capture_method_combo.setCurrentIndex(
            self._capture_method_values.index(capture_method)
            if capture_method in self._capture_method_values else 0
        )
        self._capture_method_combo.setMinimumWidth(120)
        self._capture_method_combo.setStyleSheet(
            f"QComboBox {{ background-color: {design.separator}; color: {design.text}; "
            f"border: 1px solid {design.separator}; border-radius: 3px; padding: 3px 6px; }}"
            "QComboBox::drop-down { border: none; width: 16px; }"
        )
        self._capture_method_combo.currentIndexChanged.connect(self._on_capture_method_changed)
        btn_row.addWidget(self._capture_method_combo)
        btn_row.addStretch(1)

        close_btn = QPushButton("閉じる", card)
        close_btn.setFont(QFont("Meiryo", 8))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {design.text_sub}; "
            "border: none; text-decoration: underline; padding: 5px 8px; }"
            f"QPushButton:hover {{ color: {design.text}; }}"
        )
        close_btn.clicked.connect(self._close)
        btn_row.addWidget(close_btn)

        copy_btn = QPushButton("コピー", card)
        copy_btn.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(
            f"QPushButton {{ background-color: {design.accent}; color: {design.text}; "
            "border: none; border-radius: 4px; padding: 6px 18px; }"
            f"QPushButton:hover {{ background-color: {design.separator}; }}"
        )
        copy_btn.clicked.connect(self._copy_text)
        btn_row.addWidget(copy_btn)

        layout.addLayout(btn_row)
        self._install_card_event_filter(card)
        self._center_card()

        self.show()
        self._text_edit.setFocus()
        self._update_preview()

    def _copy_text(self):
        QApplication.clipboard().setText(self._text_edit.toPlainText())

    def _on_capture_method_changed(self, index: int):
        if self._capture_method_changed is None:
            return
        value = self._capture_method_values[index] if index < len(self._capture_method_values) else "qt"
        self._capture_method_changed(value)

    def _build_adjust_page(self, parent):
        page = QWidget(parent)
        page.setProperty("rr_ocr_interactive", True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._preview_label = QLabel(page)
        self._preview_label.setVisible(False)
        self._crop_view = CropImageView(page)
        self._crop_view.setProperty("rr_ocr_interactive", True)
        self._crop_view.selection_changed.connect(self._update_status_for_selection)

        scroll = QScrollArea(page)
        scroll.setWidgetResizable(False)
        scroll.setMinimumHeight(150)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setWidget(self._crop_view)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {self._design.bg}; }}")
        layout.addWidget(scroll, stretch=1)

        self._display_zoom_slider = self._add_slider(layout, "表示倍率", 25, 300, 100, "%")
        self._scale_slider = self._add_slider(layout, "拡大", 50, 300, 100, "%")
        self._brightness_slider = self._add_slider(layout, "明るさ", -100, 100, 0, "")
        self._contrast_slider = self._add_slider(layout, "コントラスト", -100, 100, 0, "")
        self._threshold_slider = self._add_slider(layout, "しきい値", -1, 255, -1, "")

        self._invert_cb = QCheckBox("白黒反転", page)
        self._invert_cb.setFont(QFont("Meiryo", 8))
        self._invert_cb.setStyleSheet(f"color: {self._design.text};")
        self._invert_cb.toggled.connect(self._update_preview)
        layout.addWidget(self._invert_cb)

        self._status_lbl = QLabel("", page)
        self._status_lbl.setFont(QFont("Meiryo", 8))
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"color: {self._design.text_sub};")
        layout.addWidget(self._status_lbl)

        action_row = QHBoxLayout()
        action_row.addStretch(1)

        reset_btn = QPushButton("リセット", page)
        reset_btn.setFont(QFont("Meiryo", 8))
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_adjustments)
        reset_btn.setStyleSheet(self._secondary_btn_style())
        action_row.addWidget(reset_btn)

        clear_crop_btn = QPushButton("範囲解除", page)
        clear_crop_btn.setFont(QFont("Meiryo", 8))
        clear_crop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_crop_btn.clicked.connect(self._clear_crop_selection)
        clear_crop_btn.setStyleSheet(self._secondary_btn_style())
        action_row.addWidget(clear_crop_btn)

        retry_btn = QPushButton("再認識", page)
        retry_btn.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        retry_btn.clicked.connect(self._recognize_again)
        retry_btn.setStyleSheet(self._primary_btn_style())
        action_row.addWidget(retry_btn)

        layout.addLayout(action_row)
        return page

    def _add_slider(self, layout, label_text, minimum, maximum, value, suffix):
        row = QHBoxLayout()
        label = QLabel("", self)
        label.setFont(QFont("Meiryo", 8))
        label.setMinimumWidth(94)
        label.setStyleSheet(f"color: {self._design.text};")

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(minimum, maximum)
        slider.setValue(value)

        def _update_label(v):
            shown = "OFF" if label_text == "しきい値" and v < 0 else f"{v}{suffix}"
            label.setText(f"{label_text}: {shown}")
            self._update_preview()

        slider.valueChanged.connect(_update_label)
        shown = "OFF" if label_text == "しきい値" and value < 0 else f"{value}{suffix}"
        label.setText(f"{label_text}: {shown}")
        row.addWidget(label)
        row.addWidget(slider, stretch=1)
        layout.addLayout(row)
        return slider

    def _current_options(self):
        if (self._scale_slider is None or self._brightness_slider is None
                or self._contrast_slider is None or self._threshold_slider is None
                or self._invert_cb is None):
            return OcrImageOptions()
        return OcrImageOptions(
            scale_percent=self._scale_slider.value(),
            brightness=self._brightness_slider.value(),
            contrast=self._contrast_slider.value(),
            threshold=self._threshold_slider.value(),
            invert=self._invert_cb.isChecked(),
        )

    def _current_ocr_source_image(self):
        if self._source_image is None:
            return None
        if self._preview_image is None:
            self._preview_image = apply_ocr_adjustments(self._source_image, self._current_options())
        if self._crop_view is None:
            return self._preview_image
        rect = self._crop_view.selection_rect()
        if rect.isNull():
            return self._preview_image
        clipped = rect.intersected(self._preview_image.rect())
        if clipped.isNull() or clipped.width() < 1 or clipped.height() < 1:
            return self._preview_image
        return self._preview_image.copy(clipped)

    def _update_preview(self):
        if self._source_image is None or self._crop_view is None:
            return
        self._preview_image = apply_ocr_adjustments(self._source_image, self._current_options())
        self._crop_view.set_image(self._preview_image)
        if self._display_zoom_slider is not None:
            self._crop_view.set_zoom_percent(self._display_zoom_slider.value())
        self._update_status_for_selection()

    def _recognize_again(self):
        source = self._current_ocr_source_image()
        if source is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        if self._status_lbl is not None:
            self._status_lbl.setText("再認識中...")
        QApplication.processEvents()
        try:
            text = recognize_qimage(source, OcrImageOptions(scale_percent=self._scale_slider.value() if self._scale_slider is not None else 100))
            if not text.strip():
                text = "テキストを認識できませんでした。"
            self._text_edit.setPlainText(text)
            if self._status_lbl is not None:
                self._status_lbl.setText("再認識しました。結果タブで確認できます。")
            if self._tabs is not None:
                self._tabs.setCurrentIndex(0)
        except ScreenOcrError as exc:
            if self._status_lbl is not None:
                self._status_lbl.setText(f"OCRに失敗しました: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

    def _reset_adjustments(self):
        for slider, value in (
                (self._scale_slider, 100),
                (self._brightness_slider, 0),
                (self._contrast_slider, 0),
                (self._threshold_slider, -1)):
            if slider is not None:
                slider.setValue(value)
        if self._invert_cb is not None:
            self._invert_cb.setChecked(False)
        self._update_preview()

    def _clear_crop_selection(self):
        if self._crop_view is not None:
            self._crop_view.clear_selection()

    def _update_status_for_selection(self):
        if self._status_lbl is None or self._source_image is None:
            return
        rect = self._crop_view.selection_rect() if self._crop_view is not None else QRect()
        if rect.isNull():
            self._status_lbl.setText("画像をドラッグすると、再認識に使う範囲を選択できます。")
        else:
            self._status_lbl.setText(
                f"選択範囲: {rect.width()} x {rect.height()} px。再認識はこの範囲だけを使います。"
            )

    def _primary_btn_style(self):
        return (
            f"QPushButton {{ background-color: {self._design.accent}; color: {self._design.text}; "
            "border: none; border-radius: 4px; padding: 6px 18px; }"
            f"QPushButton:hover {{ background-color: {self._design.separator}; }}"
        )

    def _secondary_btn_style(self):
        return (
            f"QPushButton {{ background: transparent; color: {self._design.text_sub}; "
            f"border: 1px solid {self._design.separator}; border-radius: 4px; padding: 6px 12px; }}"
            f"QPushButton:hover {{ color: {self._design.text}; }}"
        )

    def _close(self):
        self.closed.emit()
        self.deleteLater()

    def _install_card_event_filter(self, widget):
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)
            child.setProperty("rr_ocr_interactive", True)

    def _is_interactive_child(self, obj):
        p = obj
        for _ in range(16):
            if isinstance(
                p,
                (QPushButton, QSlider, QCheckBox, QComboBox, QPlainTextEdit,
                 QScrollArea, QTabWidget, QTabBar, CropImageView),
            ):
                return True
            try:
                if p.property("rr_ocr_control"):
                    return True
            except Exception:
                pass
            if not hasattr(p, "parentWidget"):
                break
            p = p.parentWidget()
            if p is None:
                break
        return False

    def _center_card(self):
        if self._card is None:
            return
        x = max(0, (self.width() - self._card.width()) // 2)
        y = max(0, (self.height() - self._card.height()) // 2)
        self._card.move(x, y)

    def _clamp_card_pos(self, pos: QPoint) -> QPoint:
        if self._card is None:
            return pos
        return QPoint(
            max(0, min(pos.x(), max(0, self.width() - self._card.width()))),
            max(0, min(pos.y(), max(0, self.height() - self._card.height()))),
        )

    def _resize_edge_at(self, global_pos):
        if self._card is None:
            return ""
        pos = self._card.mapFromGlobal(global_pos)
        x = pos.x()
        y = pos.y()
        w = self._card.width()
        h = self._card.height()
        edge_size = 8
        if x < 0 or y < 0 or x >= w or y >= h:
            return ""
        left = x < edge_size
        right = x >= w - edge_size
        top = y < edge_size
        bottom = y >= h - edge_size
        if top and left:
            return "top-left"
        if top and right:
            return "top-right"
        if bottom and left:
            return "bottom-left"
        if bottom and right:
            return "bottom-right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return ""

    def _cursor_for_edge(self, edge):
        if edge in ("top-left", "bottom-right"):
            return Qt.CursorShape.SizeFDiagCursor
        if edge in ("top-right", "bottom-left"):
            return Qt.CursorShape.SizeBDiagCursor
        if edge in ("left", "right"):
            return Qt.CursorShape.SizeHorCursor
        if edge in ("top", "bottom"):
            return Qt.CursorShape.SizeVerCursor
        return None

    def _set_resize_cursor(self, edge):
        cursor = self._cursor_for_edge(edge)
        if cursor == self._resize_override_cursor:
            return
        if self._resize_override_cursor is not None:
            QApplication.restoreOverrideCursor()
            self._resize_override_cursor = None
        if cursor is not None:
            QApplication.setOverrideCursor(cursor)
            self._resize_override_cursor = cursor

    def _start_resize(self, edge, global_pos):
        self._resizing = True
        self._resize_edge = edge
        self._resize_start = global_pos
        self._resize_start_size = self._card.size()
        self._resize_start_geometry = self._card.geometry()
        self._card.setFixedSize(self._card.size())

    def _apply_resize(self, global_pos):
        if not self._resizing or self._card is None or self._resize_start_size is None:
            return
        delta = global_pos - self._resize_start
        start = QRect(self._resize_start_geometry)
        min_w = 320
        min_h = 260
        max_w = max(min_w, self.width())
        max_h = max(min_h, self.height())
        new_x = start.x()
        new_y = start.y()
        new_w = start.width()
        new_h = start.height()
        if "left" in self._resize_edge or "right" in self._resize_edge:
            if "left" in self._resize_edge:
                proposed_left = max(0, min(start.right() - min_w + 1, start.x() + delta.x()))
                new_w = max(min_w, start.right() - proposed_left + 1)
                new_x = start.right() - new_w + 1
            else:
                proposed_right = max(start.x() + min_w - 1, min(self.width() - 1, start.right() + delta.x()))
                new_w = max(min_w, proposed_right - start.x() + 1)
        if "top" in self._resize_edge or "bottom" in self._resize_edge:
            if "top" in self._resize_edge:
                proposed_top = max(0, min(start.bottom() - min_h + 1, start.y() + delta.y()))
                new_h = max(min_h, start.bottom() - proposed_top + 1)
                new_y = start.bottom() - new_h + 1
            else:
                proposed_bottom = max(start.y() + min_h - 1, min(self.height() - 1, start.bottom() + delta.y()))
                new_h = max(min_h, proposed_bottom - start.y() + 1)
        new_w = min(new_w, max_w)
        new_h = min(new_h, max_h)
        self._card.setFixedSize(new_w, new_h)
        self._card.move(self._clamp_card_pos(QPoint(new_x, new_y)))
        self._update_preview()

    def _end_resize(self):
        if self._resizing:
            self._resizing = False
            self._resize_edge = ""
            self._resize_start_size = None
            self._resize_start_geometry = QRect()
        self._set_resize_cursor("")

    def _start_move_card(self, global_pos):
        if self._card is None:
            return
        self._moving_card = True
        self._move_start = global_pos
        self._move_start_pos = self._card.pos()

    def _apply_move_card(self, global_pos):
        if not self._moving_card or self._card is None:
            return
        delta = global_pos - self._move_start
        self._card.move(self._clamp_card_pos(self._move_start_pos + delta))

    def _end_move_card(self):
        self._moving_card = False

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.MouseMove:
            try:
                global_pos = event.globalPosition().toPoint()
            except Exception:
                return super().eventFilter(obj, event)
            if self._resizing:
                self._apply_resize(global_pos)
                event.accept()
                return True
            if self._moving_card:
                self._apply_move_card(global_pos)
                event.accept()
                return True
            try:
                if event.buttons() == Qt.MouseButton.NoButton:
                    self._set_resize_cursor(self._resize_edge_at(global_pos))
            except Exception:
                pass
            return super().eventFilter(obj, event)
        if et == QEvent.Type.MouseButtonPress:
            try:
                if event.button() != Qt.MouseButton.LeftButton:
                    return super().eventFilter(obj, event)
                global_pos = event.globalPosition().toPoint()
            except Exception:
                return super().eventFilter(obj, event)
            edge = self._resize_edge_at(global_pos)
            if edge:
                self._start_resize(edge, global_pos)
                event.accept()
                return True
            if not self._is_interactive_child(obj):
                self._start_move_card(global_pos)
                event.accept()
                return True
            return super().eventFilter(obj, event)
        if et == QEvent.Type.MouseButtonRelease:
            if self._resizing:
                self._end_resize()
                event.accept()
                return True
            if self._moving_card:
                self._end_move_card()
                event.accept()
                return True
            if not self._is_interactive_child(obj):
                event.accept()
                return True
            return super().eventFilter(obj, event)
        if et == QEvent.Type.Leave and not self._resizing:
            self._set_resize_cursor("")
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self._close()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._card is not None:
            self._card.move(self._clamp_card_pos(self._card.pos()))

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
