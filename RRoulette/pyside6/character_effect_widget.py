"""
character_effect_widget.py — キャラクター演出ウィジェット

PWA の MiniCharacterEffect / CharacterEffect (SVG + CSS アニメーション) を
PySide6 の QSvgRenderer + QTimer アニメーションで再実装する。

クラス:
  MiniCharEffect  — ホイール周辺を横切るミニキャラ (ドラゴン/ウサギ/ゴースト)
  CutInEffect     — 上下黒帯式カットイン演出 (フルウィンドウオーバーレイ)

キャラクター SVG は PWA の MiniCharacterEffect.svelte / CharacterEffect.svelte
のインライン SVG データをそのまま流用。
"""

from __future__ import annotations

import math
from io import BytesIO

from PySide6.QtCore import QTimer, Qt, QRectF, QByteArray
from PySide6.QtGui import QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget


# ── SVG データ (PWA MiniCharacterEffect.svelte のインラインSVG と同一) ────────

_SVG_DRAGON_MINI = b"""<svg viewBox="0 0 64 56" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="34" cy="36" rx="22" ry="11" fill="#2d8f3f"/>
  <path d="M28,28 Q18,8 6,16 Q18,22 26,30" fill="#3db05b" opacity="0.92"/>
  <circle cx="52" cy="28" r="9" fill="#2d8f3f"/>
  <ellipse cx="58" cy="31" rx="5" ry="3.5" fill="#3db05b"/>
  <circle cx="50" cy="24" r="3.5" fill="#ff8800"/>
  <circle cx="51" cy="23" r="2" fill="#1a1a00"/>
  <circle cx="52" cy="22" r="0.8" fill="white"/>
  <polygon points="50,16 47,7 53,16" fill="#1a6b2a"/>
  <rect x="20" y="44" width="5" height="9" rx="2.5" fill="#1a6b2a"/>
  <rect x="33" y="45" width="5" height="9" rx="2.5" fill="#1a6b2a"/>
  <rect x="44" y="44" width="5" height="9" rx="2.5" fill="#1a6b2a"/>
  <path d="M12,38 Q4,46 10,52 Q6,42 18,40" fill="#1a6b2a"/>
  <polygon points="26,26 28,18 30,26" fill="#1a6b2a"/>
  <polygon points="36,25 38,16 40,25" fill="#1a6b2a"/>
</svg>"""

_SVG_RABBIT_MINI = b"""<svg viewBox="0 0 48 64" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="16" cy="14" rx="5" ry="13" fill="#f0f0f0"/>
  <ellipse cx="16" cy="14" rx="3" ry="11" fill="#ffb3c8"/>
  <ellipse cx="32" cy="14" rx="5" ry="13" fill="#f0f0f0"/>
  <ellipse cx="32" cy="14" rx="3" ry="11" fill="#ffb3c8"/>
  <circle cx="24" cy="30" r="13" fill="#f0f0f0"/>
  <circle cx="14" cy="33" r="3.5" fill="#ffb3c8" opacity="0.55"/>
  <circle cx="34" cy="33" r="3.5" fill="#ffb3c8" opacity="0.55"/>
  <circle cx="19" cy="27" r="2.8" fill="#cc2255"/>
  <circle cx="29" cy="27" r="2.8" fill="#cc2255"/>
  <circle cx="20" cy="26" r="1.3" fill="#220011"/>
  <circle cx="30" cy="26" r="1.3" fill="#220011"/>
  <ellipse cx="24" cy="33" rx="2" ry="1.3" fill="#ff88aa"/>
  <ellipse cx="24" cy="50" rx="14" ry="12" fill="#f0f0f0"/>
  <ellipse cx="14" cy="60" rx="5" ry="3" fill="#f0f0f0"/>
  <ellipse cx="34" cy="60" rx="5" ry="3" fill="#f0f0f0"/>
</svg>"""

_SVG_GHOST_MINI = b"""<svg viewBox="0 0 56 64" xmlns="http://www.w3.org/2000/svg">
  <path d="M8,38 Q8,10 28,10 Q48,10 48,38 L48,54 Q43,49 38,54 Q33,47 28,54 Q23,47 18,54 Q13,49 8,54 Z"
    fill="#8ec8e8" opacity="0.88"/>
  <ellipse cx="20" cy="32" rx="4.5" ry="6" fill="white"/>
  <ellipse cx="36" cy="32" rx="4.5" ry="6" fill="white"/>
  <circle cx="21" cy="34" r="3" fill="#1a3a5c"/>
  <circle cx="37" cy="34" r="3" fill="#1a3a5c"/>
  <circle cx="22" cy="32" r="1.2" fill="white"/>
  <circle cx="38" cy="32" r="1.2" fill="white"/>
  <path d="M18,46 Q22,52 28,46 Q34,52 38,46" stroke="#1a3a5c" stroke-width="2" fill="none" stroke-linecap="round"/>
</svg>"""

# カットイン用 (大きめ)
_SVG_DRAGON_CUTIN = b"""<svg viewBox="-5 -10 145 85" xmlns="http://www.w3.org/2000/svg">
  <path d="M5,42 Q-6,55 3,60 Q-2,50 12,46" fill="#1a6b2a"/>
  <ellipse cx="63" cy="48" rx="52" ry="18" fill="#2d8f3f"/>
  <path d="M52,33 Q32,2 8,14 Q28,22 48,34" fill="#3db05b" opacity="0.92"/>
  <path d="M68,33 Q72,4 90,8 Q78,20 70,34" fill="#3db05b" opacity="0.75"/>
  <ellipse cx="108" cy="40" rx="11" ry="13" fill="#2d8f3f"/>
  <circle cx="118" cy="28" r="11" fill="#2d8f3f"/>
  <ellipse cx="126" cy="32" rx="6" ry="4" fill="#3db05b"/>
  <circle cx="116" cy="23" r="4.5" fill="#ff8800"/>
  <circle cx="117" cy="22" r="2.5" fill="#1a1a00"/>
  <circle cx="118" cy="21" r="1" fill="white"/>
  <polygon points="116,16 112,5 120,16" fill="#1a6b2a"/>
  <rect x="32" y="64" width="8" height="14" rx="4" fill="#1a6b2a"/>
  <rect x="50" y="65" width="8" height="14" rx="4" fill="#1a6b2a"/>
  <rect x="70" y="65" width="8" height="14" rx="4" fill="#1a6b2a"/>
  <rect x="88" y="64" width="8" height="14" rx="4" fill="#1a6b2a"/>
  <polygon points="42,31 45,19 48,31" fill="#1a6b2a"/>
  <polygon points="57,28 60,14 63,28" fill="#1a6b2a"/>
  <polygon points="72,28 75,14 78,28" fill="#1a6b2a"/>
</svg>"""

_SVG_RABBIT_CUTIN = b"""<svg viewBox="0 0 64 96" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="20" cy="22" rx="8" ry="22" fill="#f0f0f0"/>
  <ellipse cx="20" cy="22" rx="5" ry="19" fill="#ffb3c8"/>
  <ellipse cx="44" cy="22" rx="8" ry="22" fill="#f0f0f0"/>
  <ellipse cx="44" cy="22" rx="5" ry="19" fill="#ffb3c8"/>
  <circle cx="32" cy="42" r="20" fill="#f0f0f0"/>
  <circle cx="20" cy="46" r="6" fill="#ffb3c8" opacity="0.55"/>
  <circle cx="44" cy="46" r="6" fill="#ffb3c8" opacity="0.55"/>
  <circle cx="25" cy="38" r="4.5" fill="#cc2255"/>
  <circle cx="39" cy="38" r="4.5" fill="#cc2255"/>
  <circle cx="26" cy="37" r="2.2" fill="#220011"/>
  <circle cx="40" cy="37" r="2.2" fill="#220011"/>
  <ellipse cx="32" cy="47" rx="3.5" ry="2.5" fill="#ff88aa"/>
  <ellipse cx="32" cy="74" rx="22" ry="20" fill="#f0f0f0"/>
  <ellipse cx="18" cy="88" rx="9" ry="5" fill="#f0f0f0"/>
  <ellipse cx="46" cy="88" rx="9" ry="5" fill="#f0f0f0"/>
  <circle cx="52" cy="68" r="5" fill="white"/>
</svg>"""

_SVG_GHOST_CUTIN = b"""<svg viewBox="0 0 72 90" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="36" cy="45" rx="34" ry="44" fill="#7ab8e0" opacity="0.18"/>
  <path d="M10,50 Q10,14 36,14 Q62,14 62,50 L62,72 Q56,65 50,72 Q44,63 36,72 Q28,63 22,72 Q16,65 10,72 Z"
    fill="#8ec8e8" opacity="0.88"/>
  <ellipse cx="24" cy="44" rx="7" ry="9" fill="white"/>
  <ellipse cx="48" cy="44" rx="7" ry="9" fill="white"/>
  <circle cx="26" cy="46" r="5" fill="#1a3a5c"/>
  <circle cx="50" cy="46" r="5" fill="#1a3a5c"/>
  <circle cx="27" cy="44" r="2" fill="white"/>
  <circle cx="51" cy="44" r="2" fill="white"/>
  <path d="M22,60 Q27,68 36,60 Q45,68 50,60" stroke="#1a3a5c" stroke-width="2.5" fill="none" stroke-linecap="round"/>
  <path d="M17,34 Q24,28 31,34" stroke="#1a3a5c" stroke-width="2" fill="none" stroke-linecap="round"/>
  <path d="M41,34 Q48,28 55,34" stroke="#1a3a5c" stroke-width="2" fill="none" stroke-linecap="round"/>
</svg>"""

_MINI_SVG: dict[str, bytes] = {
    "dragon": _SVG_DRAGON_MINI,
    "rabbit": _SVG_RABBIT_MINI,
    "ghost":  _SVG_GHOST_MINI,
}
_CUTIN_SVG: dict[str, bytes] = {
    "dragon": _SVG_DRAGON_CUTIN,
    "rabbit": _SVG_RABBIT_CUTIN,
    "ghost":  _SVG_GHOST_CUTIN,
}


def _make_renderer(svg_bytes: bytes) -> QSvgRenderer:
    return QSvgRenderer(QByteArray(svg_bytes))


# ════════════════════════════════════════════════════════════════
#  MiniCharEffect
# ════════════════════════════════════════════════════════════════

class MiniCharEffect(QWidget):
    """ホイール中央付近を横切るミニキャラ演出。

    parent は RoulettePanel の wheel widget。
    ホイール幅の 25% のキャラが variant に応じたパスで横切る。

    variant 1: 左→右 3ホップ (1.8s)
    variant 2: 高速直線 (1.0s)
    variant 3: 中央でジャンプ&ストップ (1.8s)
    variant 4: ジグザグ (1.6s)
    variant 5: 回転横切り (2.0s)
    """

    _DURATIONS = {1: 1800, 2: 1000, 3: 1800, 4: 1600, 5: 2000}

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.hide()

        self._renderer: QSvgRenderer | None = None
        self._opacity: float = 0.0
        self._tx: float = 0.0   # ホイール幅に対する割合 (-2.5 〜 +2.5)
        self._ty: float = 0.0   # 同上 (高さ方向)
        self._scale: float = 1.0
        self._angle: float = 0.0
        self._variant: int = 1
        self._elapsed: int = 0
        self._duration: int = 1800

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def fire(self, char_type: str, variant: int) -> None:
        """演出を開始する。"""
        self._timer.stop()
        svg = _MINI_SVG.get(char_type, _MINI_SVG["dragon"])
        self._renderer = _make_renderer(svg)
        v = max(1, min(5, variant))
        self._variant = v
        self._elapsed = 0
        self._duration = self._DURATIONS.get(v, 1800)
        self._opacity = 0.0
        self._scale = 1.0
        self._angle = 0.0
        self.resize(self.parent().size())
        self.raise_()
        self.show()
        self._timer.start()

    @staticmethod
    def _ease_io(t: float) -> float:
        """ease-in-out (S字)"""
        return t * t * (3 - 2 * t)

    def _tick(self) -> None:
        self._elapsed += 16
        t = self._elapsed / self._duration
        if t >= 1.0:
            self._timer.stop()
            self.hide()
            return

        v = self._variant

        if v == 1:  # 3ホップ
            # tx: -2.2 → -1.8@10% → ... → 2.4@100%
            tx_keyframes = [(0, -2.2), (0.10, -1.8), (0.25, -1.0), (0.40, -0.3),
                            (0.55, 0.4), (0.70, 1.1), (0.85, 1.8), (1.0, 2.4)]
            ty_keyframes = [(0, 0), (0.10, 0), (0.25, -0.5), (0.40, 0),
                            (0.55, -0.5), (0.70, 0), (0.85, -0.3), (1.0, 0)]
            self._tx = _interp(t, tx_keyframes)
            self._ty = _interp(t, ty_keyframes)
            self._opacity = min(1.0, t / 0.10) if t < 0.85 else max(0.0, (1.0 - t) / 0.15)
            self._scale = 1.0
            self._angle = 0.0

        elif v == 2:  # 高速直線
            self._tx = -2.2 + t * 4.4
            self._ty = 0.0
            self._opacity = min(1.0, t / 0.10) if t < 0.90 else max(0.0, (1.0 - t) / 0.10)
            self._scale = 0.8 + min(t / 0.10, 1.0) * 0.2
            if t > 0.90:
                self._scale = 0.8 + (1.0 - t) / 0.10 * 0.2
            self._angle = 0.0

        elif v == 3:  # 中央ジャンプ&ストップ
            if t < 0.20:
                self._tx = -2.2 + self._ease_io(t / 0.20) * (-0.5 + 2.2)
                self._ty = -0.8 * math.sin(math.pi * t / 0.20)
                self._opacity = min(1.0, t / 0.10)
                self._scale = 0.5 + self._ease_io(t / 0.20) * 0.8
            elif t < 0.35:
                self._tx = 0.0
                self._ty = 0.0
                self._opacity = 1.0
                self._scale = 1.3
            elif t < 0.65:
                self._tx = 0.0
                self._ty = 0.0
                self._opacity = 1.0
                self._scale = 1.3
            elif t < 0.80:
                self._ty = -(t - 0.65) / 0.15 * 0.3
                self._scale = 1.3 - (t - 0.65) / 0.15 * 0.2
                self._opacity = 1.0 - (t - 0.65) / 0.15 * 0.3
                self._tx = 0.0
            else:
                self._ty = -0.3 - (t - 0.80) / 0.20 * 1.2
                self._scale = 1.1 - (t - 0.80) / 0.20 * 0.5
                self._opacity = 0.7 - (t - 0.80) / 0.20 * 0.7
                self._tx = 0.0
            self._angle = 0.0

        elif v == 4:  # ジグザグ
            self._tx = -2.2 + t * 4.6
            ty_keys = [(0, 0), (0.08, -0.8), (0.23, 0.6), (0.38, -0.8),
                       (0.53, 0.6), (0.68, -0.8), (0.83, 0.6), (1.0, 0)]
            self._ty = _interp(t, ty_keys)
            self._opacity = min(1.0, t / 0.08) if t < 0.95 else max(0.0, (1.0 - t) / 0.05)
            self._scale = 1.0
            self._angle = 0.0

        elif v == 5:  # 回転横切り
            if t < 0.25:
                self._tx = -2.2 + self._ease_io(t / 0.25) * (-0.5 + 2.2)
                self._angle = self._ease_io(t / 0.25) * 360
                self._scale = self._ease_io(t / 0.25) * 1.2
                self._opacity = min(1.0, t / 0.10)
            elif t < 0.40:
                self._tx = 0.0
                self._angle = 360 + (t - 0.25) / 0.15 * 180
                self._scale = 1.2
                self._opacity = 1.0
            elif t < 0.65:
                self._tx = 0.0
                self._angle = 540
                self._scale = 1.2
                self._opacity = 1.0
            elif t < 0.80:
                self._tx = (t - 0.65) / 0.15 * 0.8
                self._angle = 540 + (t - 0.65) / 0.15 * 180
                self._scale = 1.1
                self._opacity = 0.7
            else:
                self._tx = 0.8 + (t - 0.80) / 0.20 * 1.6
                self._angle = 720 + (t - 0.80) / 0.20 * 180
                self._scale = 1.1 - (t - 0.80) / 0.20 * 1.1
                self._opacity = max(0.0, 0.7 - (t - 0.80) / 0.20 * 0.7)
            self._ty = 0.0

        self.update()

    def paintEvent(self, event):
        if not self._renderer or self._opacity <= 0.001:
            return
        w, h = self.width(), self.height()
        # キャラサイズ = ホイール幅の 25%
        char_size = w * 0.25
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._opacity)

        # 中央を基準に tx * (char_size) だけずらす
        cx = w / 2 + self._tx * char_size
        cy = h / 2 + self._ty * char_size

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        painter.scale(self._scale, self._scale)

        rect = QRectF(-char_size / 2, -char_size / 2, char_size, char_size)
        self._renderer.render(painter, rect)

        painter.restore()
        painter.end()

    def resizeEvent(self, event):
        if self.parent():
            self.resize(self.parent().size())


# ════════════════════════════════════════════════════════════════
#  CutInEffect
# ════════════════════════════════════════════════════════════════

class CutInEffect(QWidget):
    """上下黒帯式カットイン演出。フルウィンドウ（MainWindow）上に表示。

    variant 1: 黒帯スライド + キャラ左から登場 (1.6s)
    variant 2: 集中線 + キャラポップ (1.7s)
    variant 3: 斜め黒帯 + キャラ突進 (1.5s)
    variant 4: ストロボ + キャラシェイク (1.6s)
    variant 5: 縦帯 + キャラズーム (1.6s)
    """

    _DURATIONS = {1: 1600, 2: 1700, 3: 1500, 4: 1600, 5: 1600}

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        # v0.6.1: setWindowFlags(FramelessWindowHint) はトップレベル化を招く
        # ため削除。子ウィジェットとして parent (RoulettePanel) の範囲内に閉じる。
        self.hide()

        self._renderer: QSvgRenderer | None = None
        self._variant: int = 1
        self._elapsed: int = 0
        self._duration: int = 1600

        # アニメーション状態
        self._bar_top_y: float = -1.0     # 上黒帯の top (割合, parent高さ比)
        self._bar_bot_y: float = 2.0      # 下黒帯の top (割合)
        self._bar_opacity: float = 1.0
        self._char_tx: float = -2.0       # キャラの tx (parent幅比)
        self._char_ty: float = 0.0
        self._char_scale: float = 1.0
        self._char_opacity: float = 0.0
        self._char_angle: float = 0.0
        self._char_skew_x: float = 0.0
        self._deco_opacity: float = 0.0
        self._deco_scale: float = 0.4
        self._deco_angle: float = 0.0
        self._bar_height: float = 0.14   # 帯高さ (parent高さ比)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def fire(self, char_type: str, variant: int) -> None:
        self._timer.stop()
        svg = _CUTIN_SVG.get(char_type, _CUTIN_SVG["dragon"])
        self._renderer = _make_renderer(svg)
        v = max(1, min(5, variant))
        self._variant = v
        self._elapsed = 0
        self._duration = self._DURATIONS.get(v, 1600)
        self.resize(self.parent().size())
        self.raise_()
        self.show()
        self._timer.start()

    @staticmethod
    def _cubic_bezier_approx(t: float, p1: float, p2: float) -> float:
        """CSS cubic-bezier(0.2, 0.6, 0.4, 1) の近似"""
        # 簡易: ease-out 的に
        return 1.0 - (1.0 - t) ** 2.5

    def _tick(self) -> None:
        self._elapsed += 16
        t = self._elapsed / self._duration
        if t >= 1.0:
            self._timer.stop()
            self.hide()
            return

        v = self._variant
        ease = self._cubic_bezier_approx

        if v == 1:  # 標準
            # 上帯: 上から降りてくる
            if t < 0.20:
                self._bar_top_y = -0.14 + ease(t / 0.20) * 0.14
            elif t < 0.80:
                self._bar_top_y = 0.0
            else:
                self._bar_top_y = 0.0 - ease((t - 0.80) / 0.20) * 0.14
            # 下帯
            if t < 0.20:
                self._bar_bot_y = 0.86 + (1.0 - ease(t / 0.20)) * 0.14
            elif t < 0.80:
                self._bar_bot_y = 0.86
            else:
                self._bar_bot_y = 0.86 + ease((t - 0.80) / 0.20) * 0.14
            # キャラ: 左から右へ
            if t < 0.25:
                self._char_tx = -1.5 + ease(t / 0.25) * 1.5
                self._char_opacity = min(1.0, t / 0.10)
                self._char_scale = 0.7 + ease(t / 0.25) * 0.3
            elif t < 0.75:
                self._char_tx = 0.0
                self._char_opacity = 1.0
                self._char_scale = 1.0
            else:
                self._char_tx = (t - 0.75) / 0.25 * 1.5
                self._char_opacity = max(0.0, 1.0 - (t - 0.75) / 0.25)
                self._char_scale = 1.0
            self._char_ty = 0.0
            self._char_angle = 0.0
            self._deco_opacity = 0.0
            self._bar_height = 0.14

        elif v == 2:  # 集中線
            if t < 0.20:
                self._bar_top_y = -0.14 + ease(t / 0.20) * 0.14
                self._bar_bot_y = 0.86 + (1.0 - ease(t / 0.20)) * 0.14
            elif t < 0.80:
                self._bar_top_y = 0.0
                self._bar_bot_y = 0.86
            else:
                self._bar_top_y = -ease((t - 0.80) / 0.20) * 0.14
                self._bar_bot_y = 0.86 + ease((t - 0.80) / 0.20) * 0.14
            # 集中線
            if t < 0.25:
                self._deco_opacity = ease(t / 0.25) * 0.9
                self._deco_scale = 0.4 + ease(t / 0.25) * 0.6
                self._deco_angle = ease(t / 0.25) * 20
            elif t < 0.75:
                self._deco_opacity = 0.7
                self._deco_scale = 1.1
                self._deco_angle = 40
            else:
                self._deco_opacity = max(0.0, 0.7 - ease((t - 0.75) / 0.25) * 0.7)
                self._deco_scale = 1.1 + ease((t - 0.75) / 0.25) * 0.2
                self._deco_angle = 60
            # キャラ (ポップ)
            if t < 0.25:
                self._char_scale = ease(t / 0.25) * 1.2
                self._char_opacity = min(1.0, t / 0.10)
            elif t < 0.35:
                self._char_scale = 1.2 - (t - 0.25) / 0.10 * 0.2
                self._char_opacity = 1.0
            elif t < 0.75:
                self._char_scale = 1.0
                self._char_opacity = 1.0
            else:
                self._char_scale = 1.0 - ease((t - 0.75) / 0.25) * 0.2
                self._char_opacity = max(0.0, 1.0 - ease((t - 0.75) / 0.25) * 0.3)
                self._char_ty = -ease((t - 0.75) / 0.25) * 0.1
            self._char_tx = 0.0
            self._char_angle = 0.0
            self._bar_height = 0.14

        elif v == 3:  # 斜め帯
            self._bar_height = 0.16
            if t < 0.18:
                self._bar_top_y = -0.16 + ease(t / 0.18) * 0.16
                self._bar_bot_y = 0.84 + (1.0 - ease(t / 0.18)) * 0.16
            elif t < 0.82:
                self._bar_top_y = 0.0
                self._bar_bot_y = 0.84
            else:
                self._bar_top_y = -ease((t - 0.82) / 0.18) * 0.16
                self._bar_bot_y = 0.84 + ease((t - 0.82) / 0.18) * 0.16
            # キャラ (左から突進)
            if t < 0.20:
                self._char_tx = -1.8 + ease(t / 0.20) * 1.8
                self._char_opacity = min(1.0, t / 0.10)
                self._char_skew_x = -15 * (1.0 - ease(t / 0.20))
            elif t < 0.70:
                self._char_tx = 0.0
                self._char_opacity = 1.0
                self._char_skew_x = 0.0
            else:
                self._char_tx = ease((t - 0.70) / 0.30) * 1.8
                self._char_opacity = max(0.0, 1.0 - ease((t - 0.70) / 0.30))
                self._char_skew_x = 15 * ease((t - 0.70) / 0.30)
            self._char_ty = 0.0
            self._char_scale = 1.0
            self._char_angle = 0.0
            self._deco_opacity = 0.0

        elif v == 4:  # ストロボ
            if t < 0.10:
                self._bar_top_y = -0.14 + ease(t / 0.10) * 0.14
                self._bar_bot_y = 0.86 + (1.0 - ease(t / 0.10)) * 0.14
            elif t < 0.85:
                self._bar_top_y = 0.0
                self._bar_bot_y = 0.86
                # ストロボ点滅
                cycles = (t - 0.10) / 0.30
                self._bar_opacity = 0.7 + 0.3 * abs(math.sin(cycles * math.pi * 3))
            else:
                self._bar_top_y = -ease((t - 0.85) / 0.15) * 0.14
                self._bar_bot_y = 0.86 + ease((t - 0.85) / 0.15) * 0.14
                self._bar_opacity = 1.0
            # キャラ (シェイク)
            if t < 0.20:
                self._char_tx = -1.5 + ease(t / 0.20) * 1.5
                self._char_opacity = min(1.0, t / 0.10)
                self._char_scale = 0.6 + ease(t / 0.20) * 0.6
            elif t < 0.40:
                cycles = (t - 0.20) / 0.20 * 4
                self._char_tx = math.sin(cycles * math.pi) * 0.06
                self._char_scale = 1.0 + abs(math.sin(cycles * math.pi)) * 0.2
                self._char_opacity = 1.0
            elif t < 0.80:
                self._char_tx = 0.0
                self._char_scale = 1.0
                self._char_opacity = 1.0
            else:
                self._char_tx = ease((t - 0.80) / 0.20) * 1.5
                self._char_opacity = max(0.0, 1.0 - ease((t - 0.80) / 0.20))
                self._char_scale = 1.0
            self._char_ty = 0.0
            self._char_angle = 0.0
            self._deco_opacity = 0.0
            self._bar_height = 0.14

        elif v == 5:  # 縦帯
            self._bar_height = 1.0  # 縦帯: 高さ = 全体
            if t < 0.20:
                self._bar_top_y = 0.0
                self._bar_bot_y = 0.75  # right bar left edge
                # 縦帯のアニメーションは _bar_top_y を使わず幅を制御
                self._deco_scale = ease(t / 0.20)  # 帯幅 (0→0.25)
            elif t < 0.80:
                self._deco_scale = 1.0
            else:
                self._deco_scale = max(0.0, 1.0 - ease((t - 0.80) / 0.20))
            # キャラ (ズーム)
            if t < 0.25:
                self._char_scale = ease(t / 0.25) * 1.3
                self._char_angle = -30 * (1.0 - ease(t / 0.25))
                self._char_opacity = min(1.0, t / 0.10)
            elif t < 0.35:
                self._char_scale = 1.3 - (t - 0.25) / 0.10 * 0.3
                self._char_angle = 0.0
                self._char_opacity = 1.0
            elif t < 0.75:
                self._char_scale = 1.0
                self._char_angle = 0.0
                self._char_opacity = 1.0
            else:
                self._char_scale = 1.0 + ease((t - 0.75) / 0.25) * 1.0
                self._char_angle = 0.0
                self._char_opacity = max(0.0, 1.0 - ease((t - 0.75) / 0.25))
            self._char_tx = 0.0
            self._char_ty = 0.0
            self._deco_opacity = 0.0

        self.update()

    def paintEvent(self, event):
        if not self._renderer:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        v = self._variant
        bh = int(h * self._bar_height)

        if v == 5:
            # 縦帯
            bar_w = int(w * 0.25 * self._deco_scale)
            if bar_w > 0:
                # 左帯
                painter.fillRect(0, 0, bar_w, h, QColor(10, 10, 10))
                # 右帯
                painter.fillRect(w - bar_w, 0, bar_w, h, QColor(10, 10, 10))
        else:
            # 上帯
            top_y = int(h * self._bar_top_y)
            painter.setOpacity(getattr(self, '_bar_opacity', 1.0))
            painter.fillRect(0, top_y, w, bh, QColor(10, 10, 10))
            # 下帯
            bot_y = int(h * self._bar_bot_y)
            painter.fillRect(0, bot_y, w, bh, QColor(10, 10, 10))
            painter.setOpacity(1.0)

        # 集中線 (v2)
        if v == 2 and self._deco_opacity > 0.001:
            import math as _math
            cx, cy_mid = w / 2, h / 2
            stage_top = h * self._bar_top_y + bh
            stage_h = h * self._bar_bot_y - stage_top
            cy_stage = stage_top + stage_h / 2
            r = _math.sqrt((w / 2) ** 2 + (stage_h / 2) ** 2) * 1.5
            # 放射状線
            from PySide6.QtGui import QPen
            painter.save()
            painter.translate(cx, cy_stage)
            painter.rotate(self._deco_angle)
            painter.scale(self._deco_scale, self._deco_scale)
            painter.setOpacity(self._deco_opacity)
            pen = QPen(QColor(255, 255, 255, 140), 1.5)
            painter.setPen(pen)
            for angle in range(0, 360, 8):
                rad = math.radians(angle)
                painter.drawLine(0, 0, int(math.cos(rad) * r), int(math.sin(rad) * r))
            painter.restore()
            painter.setOpacity(1.0)

        # キャラ
        if self._renderer and self._char_opacity > 0.001:
            stage_top = max(0, int(h * self._bar_top_y) + bh) if v != 5 else bh
            stage_bot = min(h, int(h * self._bar_bot_y)) if v != 5 else h - bh
            stage_h = max(60, stage_bot - stage_top)
            char_h = int(stage_h * 0.8)
            aspect = self._renderer.viewBoxF()
            if aspect.height() > 0:
                char_w = int(char_h * aspect.width() / aspect.height())
            else:
                char_w = char_h
            cx = w / 2 + self._char_tx * w
            cy_stage = stage_top + stage_h / 2 + self._char_ty * h

            painter.save()
            painter.translate(cx, cy_stage)
            painter.rotate(self._char_angle)
            if self._char_skew_x != 0.0:
                from PySide6.QtGui import QTransform
                tr = painter.transform()
                skew = QTransform(1, math.tan(math.radians(self._char_skew_x)), 0, 1, 0, 0)
                painter.setTransform(tr * skew)
            painter.scale(self._char_scale, self._char_scale)
            painter.setOpacity(self._char_opacity)
            rect = QRectF(-char_w / 2, -char_h / 2, char_w, char_h)
            self._renderer.render(painter, rect)
            painter.restore()

        painter.end()

    def resizeEvent(self, event):
        if self.parent():
            self.resize(self.parent().size())


# ── ユーティリティ ─────────────────────────────────────────────

def _interp(t: float, keyframes: list[tuple[float, float]]) -> float:
    """キーフレームリストを線形補間して値を返す。"""
    if t <= keyframes[0][0]:
        return keyframes[0][1]
    if t >= keyframes[-1][0]:
        return keyframes[-1][1]
    for i in range(len(keyframes) - 1):
        t0, v0 = keyframes[i]
        t1, v1 = keyframes[i + 1]
        if t0 <= t <= t1:
            alpha = (t - t0) / (t1 - t0)
            return v0 + alpha * (v1 - v0)
    return keyframes[-1][1]
