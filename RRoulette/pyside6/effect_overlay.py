"""
effect_overlay.py — 特殊演出オーバーレイウィジェット

PWA の CSS アニメーション (flash / CHANCE! テキスト) を
PySide6 の QWidget + QTimer ベースアニメーションで再実装する。

ホイールグロー (wheelGlow) は WheelWidget 側の
set_glow_variant() / clear_glow() で制御するため、ここには含まない。

クラス:
  FlashOverlay   — 画面フラッシュ演出 (5 バリエーション)
  ChanceTextOverlay — CHANCE! テキスト演出 (5 バリエーション)

いずれも RoulettePanel の直接子として setParent + show/hide する前提。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QTimer, QPointF, Qt, QRectF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QPainterPath, QColor, QRadialGradient, QFont, QPen
from PySide6.QtWidgets import QWidget, QLabel


# ════════════════════════════════════════════════════════════════
#  FlashOverlay
# ════════════════════════════════════════════════════════════════

class FlashOverlay(QWidget):
    """画面フラッシュ演出。5 バリエーション。

    parent (RoulettePanel) の上に透明な全面オーバーレイを張り、
    QTimer ベースのフレームアニメーションで色を変えて点滅する。

    variant 1: ゴールド放射グラデーション (0.9s)
    variant 2: 純白フラッシュ (0.5s, 強烈・瞬間)
    variant 3: 赤フラッシュ (0.9s)
    variant 4: 虹色フラッシュ (1.0s, 色相回転)
    variant 5: パルス (1.0s, 2回点滅)
    """

    # バリアント別パラメータ: (duration_ms, base_color_rgba, hue_rotate)
    _VARIANT_PARAMS = {
        1: {"dur": 900,  "color": (255, 215, 0,  0), "style": "radial_gold"},
        2: {"dur": 500,  "color": (255, 255, 255, 0), "style": "white"},
        3: {"dur": 900,  "color": (255, 30,  30,  0), "style": "radial_red"},
        4: {"dur": 1000, "color": (255, 80,  80,  0), "style": "rainbow"},
        5: {"dur": 1000, "color": (255, 200, 0,  0), "style": "pulse"},
    }

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        # v0.6.1: setWindowFlags はトップレベル化を招くため削除
        self.hide()

        self._opacity: float = 0.0
        self._variant: int = 1
        self._elapsed: int = 0
        self._duration: int = 900
        self._hue_shift: float = 0.0
        self._phase: int = 0  # パルス用

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60fps
        self._timer.timeout.connect(self._tick)

    def fire(self, variant: int) -> None:
        """演出を開始する。"""
        self._timer.stop()
        v = max(1, min(5, variant))
        p = self._VARIANT_PARAMS[v]
        self._variant = v
        self._elapsed = 0
        self._duration = p["dur"]
        self._opacity = 0.0
        self._hue_shift = 0.0
        self._phase = 0
        self.resize(self.parent().size())
        self.raise_()
        self.show()
        self._timer.start()

    def _tick(self) -> None:
        self._elapsed += 16
        t = self._elapsed / self._duration  # 0.0 → 1.0

        if t >= 1.0:
            self._timer.stop()
            self.hide()
            return

        v = self._variant
        if v == 1:  # gold radial
            if t < 0.08:
                self._opacity = t / 0.08 * 0.85
            else:
                self._opacity = 0.85 * (1.0 - t) / 0.92
        elif v == 2:  # white
            if t < 0.05:
                self._opacity = t / 0.05
            elif t < 0.20:
                self._opacity = 1.0 - (t - 0.05) / 0.15 * 0.5
            else:
                self._opacity = 0.5 * (1.0 - t) / 0.80
        elif v == 3:  # red
            if t < 0.10:
                self._opacity = t / 0.10 * 0.85
            else:
                self._opacity = 0.85 * (1.0 - t) / 0.90
        elif v == 4:  # rainbow
            if t < 0.10:
                self._opacity = t / 0.10 * 0.85
            else:
                self._opacity = 0.85 * (1.0 - t) / 0.90
            self._hue_shift = t * 360.0
        elif v == 5:  # pulse
            # 0〜30%: 0, 10%: 0.85; 30〜60%: 0, 40%: 0.85; 60〜100%: 0
            def _pulse(tp):
                if 0.0 <= tp < 0.10:
                    return tp / 0.10 * 0.85
                elif 0.10 <= tp < 0.30:
                    return 0.85 * (0.30 - tp) / 0.20
                elif 0.30 <= tp < 0.40:
                    return (tp - 0.30) / 0.10 * 0.85
                elif 0.40 <= tp < 0.60:
                    return 0.85 * (0.60 - tp) / 0.20
                return 0.0
            self._opacity = _pulse(t)

        self.update()

    def paintEvent(self, event):
        if self._opacity <= 0.001:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # v0.6.1: ホイール内の円形のみに描画する
        # 親 (RoulettePanel) の wheel ウィジェット幾何を取得
        wheel = getattr(self.parent(), "wheel", None)
        if wheel is not None:
            wg = wheel.geometry()  # parent 内座標
            wcx = wg.x() + wg.width() / 2.0
            wcy = wg.y() + wg.height() / 2.0
            # WHEEL_OUTER_MARGIN ≒ 20px。ホイール円外の余白を除外
            try:
                from app_constants import WHEEL_OUTER_MARGIN as _WOM
            except Exception:
                _WOM = 20
            r = max(10.0, min(wg.width(), wg.height()) / 2.0 - float(_WOM))
            from PySide6.QtGui import QPainterPath
            clip_path = QPainterPath()
            clip_path.addEllipse(wcx - r, wcy - r, r * 2, r * 2)
            painter.setClipPath(clip_path)
            cx, cy = wcx, wcy
            grad_r = r
            fill_rect = QRectF(wcx - r, wcy - r, r * 2, r * 2)
        else:
            w, h = self.width(), self.height()
            cx, cy = w / 2, h / 2
            grad_r = math.sqrt(cx ** 2 + cy ** 2)
            fill_rect = QRectF(self.rect())

        v = self._variant

        if v == 1:  # gold radial
            grad = QRadialGradient(QPointF(cx, cy), grad_r)
            grad.setColorAt(0.0, QColor(255, 215, 0,  int(self._opacity * 235)))
            grad.setColorAt(1.0, QColor(255, 120, 0,  int(self._opacity * 140)))
            painter.fillRect(fill_rect, grad)

        elif v == 2:  # white
            painter.fillRect(fill_rect, QColor(255, 255, 255, int(self._opacity * 242)))

        elif v == 3:  # red
            grad = QRadialGradient(QPointF(cx, cy), grad_r)
            grad.setColorAt(0.0, QColor(255, 30,  30, int(self._opacity * 242)))
            grad.setColorAt(1.0, QColor(180,  0,   0, int(self._opacity * 153)))
            painter.fillRect(fill_rect, grad)

        elif v == 4:  # rainbow
            hue = int(self._hue_shift) % 360
            base = QColor.fromHsv(hue, 255, 255)
            grad = QRadialGradient(QPointF(cx, cy), grad_r)
            grad.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(),
                                        int(self._opacity * 217)))
            grad.setColorAt(1.0, QColor(255, 255, 80, int(self._opacity * 100)))
            painter.fillRect(fill_rect, grad)

        elif v == 5:  # pulse
            grad = QRadialGradient(QPointF(cx, cy), grad_r)
            grad.setColorAt(0.0, QColor(255, 200, 0, int(self._opacity * 235)))
            grad.setColorAt(1.0, QColor(255, 80,  0, int(self._opacity * 128)))
            painter.fillRect(fill_rect, grad)

        painter.end()

    def resizeEvent(self, event):
        if self.parent():
            self.resize(self.parent().size())


# ════════════════════════════════════════════════════════════════
#  ChanceTextOverlay
# ════════════════════════════════════════════════════════════════

class ChanceTextOverlay(QWidget):
    """「CHANCE!」テキスト演出。5 バリエーション。

    variant 1: ポップアップ (scale 0.4 → 1.15 → 1 → fade)
    variant 2: 上から落下
    variant 3: 振動シェイク
    variant 4: 拡大グロー
    variant 5: 下からスライド
    """

    _DURATION = {1: 1600, 2: 1600, 3: 1600, 4: 1600, 5: 1600}

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.hide()

        self._opacity: float = 0.0
        self._scale: float = 1.0
        self._offset_y: float = 0.0
        self._offset_x: float = 0.0
        self._variant: int = 1
        self._elapsed: int = 0
        self._duration: int = 1600
        self._glow_radius: float = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def fire(self, variant: int) -> None:
        self._timer.stop()
        v = max(1, min(5, variant))
        self._variant = v
        self._elapsed = 0
        self._duration = self._DURATION.get(v, 1600)
        self._opacity = 0.0
        self._scale = 0.4
        self._offset_y = 0.0
        self._offset_x = 0.0
        self._glow_radius = 0.0
        self.resize(self.parent().size())
        self.raise_()
        self.show()
        self._timer.start()

    @staticmethod
    def _ease_out(t: float, e: float = 2.0) -> float:
        return 1.0 - (1.0 - t) ** e

    @staticmethod
    def _ease_in(t: float, e: float = 2.0) -> float:
        return t ** e

    def _tick(self) -> None:
        self._elapsed += 16
        t = self._elapsed / self._duration
        if t >= 1.0:
            self._timer.stop()
            self.hide()
            return

        v = self._variant
        h = self.height()

        if v == 1:  # pop
            if t < 0.18:
                self._opacity = min(1.0, t / 0.10)
                self._scale = 0.4 + self._ease_out(t / 0.18) * 0.75
            elif t < 0.30:
                self._scale = 1.15 - (t - 0.18) / 0.12 * 0.15
                self._opacity = 1.0
            elif t < 0.72:
                self._scale = 1.0
                self._opacity = 1.0
            else:
                self._opacity = max(0.0, 1.0 - (t - 0.72) / 0.28)
                self._scale = 1.0 - (t - 0.72) / 0.28 * 0.15
                self._offset_y = -(t - 0.72) / 0.28 * 24
            self._offset_x = 0.0

        elif v == 2:  # drop
            if t < 0.25:
                self._opacity = min(1.0, t / 0.15)
                self._scale = 1.3 - self._ease_out(t / 0.25) * 0.4
                self._offset_y = -h * 0.5 + self._ease_out(t / 0.25) * h * 0.5 * 0.92
            elif t < 0.35:
                self._scale = 0.9 + (t - 0.25) / 0.10 * 0.2
                self._offset_y = -h * 0.5 * 0.08 + (t - 0.25) / 0.10 * h * 0.5 * 0.08
                self._opacity = 1.0
            elif t < 0.45:
                self._scale = 1.1 - (t - 0.35) / 0.10 * 0.1
                self._offset_y = 0.0
                self._opacity = 1.0
            elif t < 0.80:
                self._scale = 1.0
                self._offset_y = 0.0
                self._opacity = 1.0
            else:
                self._opacity = max(0.0, 1.0 - (t - 0.80) / 0.20)
                self._scale = 1.0 + (t - 0.80) / 0.20 * 0.6
                self._offset_y = 0.0
            self._offset_x = 0.0

        elif v == 3:  # shake
            if t < 0.15:
                self._opacity = min(1.0, t / 0.08)
                self._scale = 0.4 + self._ease_out(t / 0.15) * 0.8
                self._offset_x = 0.0
            elif t < 0.30:
                self._scale = 1.2 - (t - 0.15) / 0.15 * 0.2
                # shake cycle
                cycles = (t - 0.15) / 0.15 * 4
                self._offset_x = math.sin(cycles * math.pi * 2) * 12
                self._opacity = 1.0
            elif t < 0.80:
                self._scale = 1.0
                self._offset_x = 0.0
                self._opacity = 1.0
            else:
                self._opacity = max(0.0, 1.0 - (t - 0.80) / 0.20)
                self._scale = 1.0 - (t - 0.80) / 0.20 * 0.3
                self._offset_x = 0.0
            self._offset_y = 0.0

        elif v == 4:  # glow
            if t < 0.25:
                self._opacity = min(1.0, t / 0.12)
                self._scale = self._ease_out(t / 0.25) * 1.3
                self._glow_radius = self._scale * 30.0
            elif t < 0.40:
                self._scale = 1.3 - (t - 0.25) / 0.15 * 0.3
                self._glow_radius = self._scale * 20.0
                self._opacity = 1.0
            elif t < 0.80:
                self._scale = 1.0
                self._glow_radius = 18.0
                self._opacity = 1.0
            else:
                self._opacity = max(0.0, 1.0 - (t - 0.80) / 0.20)
                self._scale = 1.0
                self._glow_radius = self._opacity * 18.0
            self._offset_x = 0.0
            self._offset_y = 0.0

        elif v == 5:  # slide from bottom
            if t < 0.20:
                self._opacity = min(1.0, t / 0.12)
                self._scale = 1.0 + (1.0 - self._ease_out(t / 0.20)) * 0.3
                self._offset_y = h * 0.4 * (1.0 - self._ease_out(t / 0.20))
            elif t < 0.75:
                self._scale = 1.0
                self._offset_y = 0.0
                self._opacity = 1.0
            else:
                self._opacity = max(0.0, 1.0 - (t - 0.75) / 0.25)
                self._offset_y = -(t - 0.75) / 0.25 * 30
                self._scale = 1.0
            self._offset_x = 0.0

        self.update()

    def paintEvent(self, event):
        if self._opacity <= 0.001:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()
        cx = w / 2 + self._offset_x
        cy = h / 2 + self._offset_y

        text = "CHANCE!"
        font_size = max(24, min(56, int(w * 0.10)))
        font = QFont("Arial Black", font_size, QFont.Black)
        if not font.exactMatch():
            font.setBold(True)
        painter.setFont(font)

        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text)
        th = fm.ascent()

        painter.save()
        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)

        # 外枠（黒アウトライン）
        path = QPainterPath()
        path.addText(QPointF(-tw / 2, th / 2), font, text)

        # グロー (v4)
        if self._glow_radius > 0:
            glow_color = QColor(255, 170, 0, int(self._opacity * 160))
            pen = QPen(glow_color, self._glow_radius)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.strokePath(path, pen)

        # 黒縁取り
        painter.setPen(QPen(QColor(0, 0, 0, int(self._opacity * 230)), 4,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)

        # 本文（金色）
        painter.fillPath(path, QColor(255, 215, 0, int(self._opacity * 255)))

        painter.restore()
        painter.end()

    def resizeEvent(self, event):
        if self.parent():
            self.resize(self.parent().size())
