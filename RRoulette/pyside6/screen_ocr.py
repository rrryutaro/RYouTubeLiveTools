"""
RRoulette PySide6 — screen capture OCR helpers.

Windows.Media.Ocr is used through the ``winsdk`` package so the feature can use
the OCR engine bundled with Windows instead of requiring Tesseract.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QColor


class ScreenOcrError(RuntimeError):
    """Raised when screen OCR cannot be performed."""


@dataclass(frozen=True)
class OcrImageOptions:
    """Image adjustment options applied before OCR."""

    scale_percent: int = 100
    brightness: int = 0
    contrast: int = 0
    threshold: int = -1
    invert: bool = False


def check_ocr_runtime() -> tuple[bool, str]:
    """Return whether Windows OCR dependencies are available in this Python."""
    try:
        from winsdk.windows.globalization import Language  # noqa: F401
        from winsdk.windows.graphics.imaging import BitmapDecoder  # noqa: F401
        from winsdk.windows.media.ocr import OcrEngine  # noqa: F401
        from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream  # noqa: F401
    except ImportError as exc:
        return False, str(exc)
    return True, ""


_CJK_RE = (
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\u3400-\u9fff"  # CJK ideographs
    r"\uf900-\ufaff"  # CJK compatibility ideographs
)


def prepare_ocr_image(image: QImage, options: OcrImageOptions | None = None) -> QImage:
    """Return an OCR-friendly copy of the capture image."""
    if image.isNull():
        raise ScreenOcrError("キャプチャ画像が空です。")

    options = options or OcrImageOptions()
    prepared = image.convertToFormat(QImage.Format.Format_RGB32)
    largest_side = max(prepared.width(), prepared.height())
    base_scale = 1.0
    if largest_side < 1800:
        base_scale = min(3.0, 1800 / max(largest_side, 1))
    user_scale = max(50, min(300, options.scale_percent)) / 100.0
    scale = base_scale * user_scale
    if abs(scale - 1.0) > 0.01:
        prepared = prepared.scaled(
            int(prepared.width() * scale),
            int(prepared.height() * scale),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return apply_ocr_adjustments(prepared, options)


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def apply_ocr_adjustments(image: QImage, options: OcrImageOptions | None = None) -> QImage:
    """Apply brightness/contrast/threshold adjustments to an image."""
    options = options or OcrImageOptions()
    adjusted = image.convertToFormat(QImage.Format.Format_RGB32)
    if (options.brightness == 0 and options.contrast == 0
            and options.threshold < 0 and not options.invert):
        return adjusted

    contrast = max(-100, min(100, options.contrast)) * 2.55
    factor = 259 * (contrast + 255) / (255 * (259 - contrast))
    brightness = max(-100, min(100, options.brightness)) * 2.55
    threshold = options.threshold

    for y in range(adjusted.height()):
        for x in range(adjusted.width()):
            color = adjusted.pixelColor(x, y)
            red = _clamp_channel(factor * (color.red() - 128) + 128 + brightness)
            green = _clamp_channel(factor * (color.green() - 128) + 128 + brightness)
            blue = _clamp_channel(factor * (color.blue() - 128) + 128 + brightness)
            if threshold >= 0:
                gray = int(red * 0.299 + green * 0.587 + blue * 0.114)
                value = 255 if gray >= threshold else 0
                if options.invert:
                    value = 255 - value
                adjusted.setPixelColor(x, y, QColor(value, value, value))
                continue
            if options.invert:
                red = 255 - red
                green = 255 - green
                blue = 255 - blue
            adjusted.setPixelColor(x, y, QColor(red, green, blue))
    return adjusted


def qimage_to_png_bytes(image: QImage, options: OcrImageOptions | None = None) -> bytes:
    """Encode a QImage as PNG bytes for the Windows bitmap decoder."""
    image = prepare_ocr_image(image, options)

    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ScreenOcrError("画像バッファを作成できませんでした。")
    try:
        if not image.save(buffer, "PNG"):
            raise ScreenOcrError("キャプチャ画像をPNGに変換できませんでした。")
    finally:
        buffer.close()
    return bytes(data)


def normalize_ocr_text(text: str) -> str:
    """Clean OCR text into a paste-friendly item list."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.replace("\u3000", " ").strip()
        line = re.sub(r"[ \t]+", " ", line)
        # Windows OCR often inserts spaces between Japanese characters.
        while re.search(fr"([{_CJK_RE}]) ([{_CJK_RE}])", line):
            line = re.sub(fr"([{_CJK_RE}]) ([{_CJK_RE}])", r"\1\2", line)
        # Trim common list markers while keeping the item text itself.
        line = re.sub(r"^\s*[\-*\u2022\u30fb]+\s*", "", line)
        line = re.sub(r"^\s*[\(\[]?\d{1,2}[\)\].:：、]\s*", "", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


async def _recognize_png_bytes_async(png_bytes: bytes) -> str:
    try:
        from winsdk.windows.globalization import Language
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except ImportError as exc:
        raise ScreenOcrError(
            "OCR機能を使うには winsdk パッケージが必要です。\n"
            "開発環境では `pip install -r RRoulette\\requirements.txt` を実行してください。\n"
            "リリースEXEでは winsdk を同梱してビルドする必要があります。"
        ) from exc

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = None
    for language_tag in ("ja-JP", "ja"):
        language = Language(language_tag)
        if OcrEngine.is_language_supported(language):
            engine = OcrEngine.try_create_from_language(language)
            if engine is not None:
                break
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        for language_tag in ("en-US", "en"):
            language = Language(language_tag)
            if not OcrEngine.is_language_supported(language):
                continue
            engine = OcrEngine.try_create_from_language(Language(language_tag))
            if engine is not None:
                break
    if engine is None:
        raise ScreenOcrError("Windows OCRエンジンを初期化できませんでした。")

    result = await engine.recognize_async(bitmap)
    lines = [line.text.strip() for line in result.lines if line.text.strip()]
    return normalize_ocr_text("\n".join(lines))


def recognize_qimage(image: QImage, options: OcrImageOptions | None = None) -> str:
    """Run OCR for a captured QImage and return one item candidate per line."""
    png_bytes = qimage_to_png_bytes(image, options)
    try:
        return asyncio.run(_recognize_png_bytes_async(png_bytes))
    except ScreenOcrError:
        raise
    except Exception as exc:
        raise ScreenOcrError(f"OCRに失敗しました: {exc}") from exc
