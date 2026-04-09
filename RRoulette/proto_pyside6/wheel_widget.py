"""
PySide6 プロトタイプ — ホイール描画ウィジェット

QPainter ベースで wheel を描画する QWidget。
親コンテナの実寸を基準に中心・半径を算出し、
resizeEvent で同期的に再計算する。

責務:
  - wheel セグメントの描画（色・テキスト・外周線）
  - ポインター描画
  - ドーナツ穴描画
  - テキストレイアウトキャッシュ管理
  - 角度・ポインター角度の管理

スピン物理は SpinController に委譲済み。

既存ロジック接続:
  - constants.py: MIN_R, WHEEL_OUTER_MARGIN, POINTER_OVERHANG, Segment
  - design_settings.py: DesignSettings（色・フォント設定）
  - geometry.py: SafeSector, get_sector_safe_area
  - layout_search.py: build_all_sector_layouts, LayoutResult
"""

import math
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget

# 既存ロジックは bridge 経由で import
from bridge import (
    MIN_R, WHEEL_OUTER_MARGIN, POINTER_OVERHANG,
    DONUT_DRAW_RADIUS, DONUT_HIT_RADIUS,
    Segment, DesignSettings,
    build_all_sector_layouts, LayoutResult,
)


class WheelWidget(QWidget):
    """ルーレットホイール描画ウィジェット。

    親レイアウト内の実サイズを基準に描画する。
    tkinter 版の WheelRendererMixin._on_canvas_resize + _redraw に相当。

    スピン制御は SpinController が担当し、
    set_angle() 経由で角度を更新する。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)

        # --- 描画状態 ---
        self._items: list[str] = []
        self._segments: list[Segment] = []
        self._design: DesignSettings = DesignSettings()
        self._angle: float = 0.0
        self._pointer_angle: float = 0.0
        self._text_size_mode: int = 1
        self._text_direction: int = 0
        self._donut_hole: bool = False

        # --- ログオーバーレイ ---
        self._log_entries: list[tuple[str, str]] = []  # (時刻, テキスト) 新しい順
        self._log_max: int = 8             # 最大表示件数
        self._log_visible: bool = True     # 表示ON/OFF
        self._log_timestamp: bool = False  # タイムスタンプ表示
        self._log_box_border: bool = False # 枠線表示
        self._log_on_top: bool = False     # 前面表示

        # --- 透過モード ---
        self._transparent: bool = False
        self._spin_direction: int = 1  # 0=反時計回り, 1=時計回り（デフォルト: 時計回り）

        # --- 描画パラメータ ---
        self._cx: float = 0.0
        self._cy: float = 0.0
        self._r: float = MIN_R

        # --- レイアウトキャッシュ ---
        self._layout_cache: list[LayoutResult] | None = None
        self._layout_cache_key: tuple | None = None

        self._update_geometry()

    # ================================================================
    #  公開 API
    # ================================================================

    def set_items(self, items: list[str]):
        """セグメント項目を簡易設定する（テスト用、均等配分）。"""
        n = len(items)
        if n == 0:
            self._items = []
            self._segments = []
        else:
            arc = 360.0 / n
            self._segments = [
                Segment(item_text=t, item_index=i, arc=arc, start_angle=i * arc)
                for i, t in enumerate(items)
            ]
            self._items = list(items)
        self._layout_cache_key = None
        self.update()

    def set_segments(self, segments: list):
        """既存ロジックで構築済みのセグメントリストを直接設定する。"""
        self._segments = list(segments)
        self._items = [seg.item_text for seg in segments]
        self._layout_cache_key = None
        self.update()

    def set_design(self, design: DesignSettings):
        """デザイン設定を適用する。"""
        self._design = design
        self._layout_cache_key = None
        self.update()

    def set_angle(self, angle: float):
        """wheel の回転角度を設定する。SpinController から呼ばれる。"""
        self._angle = angle % 360.0
        self.update()

    def set_pointer_angle(self, angle: float):
        self._pointer_angle = angle % 360.0
        self.update()

    def set_text_mode(self, size_mode: int, direction: int):
        """テキスト表示モードを設定する。"""
        self._text_size_mode = size_mode
        self._text_direction = direction
        self._layout_cache_key = None
        self.update()

    def set_donut_hole(self, enabled: bool):
        self._donut_hole = enabled
        self._layout_cache_key = None
        self.update()

    # ── ログオーバーレイ ──

    def add_log_entry(self, text: str):
        """履歴エントリを先頭に追加する（時刻付き）。"""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_entries.insert(0, (ts, text))
        if len(self._log_entries) > self._log_max:
            self._log_entries = self._log_entries[:self._log_max]
        self.update()

    def set_log_visible(self, visible: bool):
        """ログオーバーレイの表示ON/OFFを設定する。"""
        self._log_visible = visible
        self.update()

    def set_log_timestamp(self, enabled: bool):
        """ログタイムスタンプ表示ON/OFFを設定する。"""
        self._log_timestamp = enabled
        self.update()

    def set_log_box_border(self, enabled: bool):
        """ログボックス枠線表示ON/OFFを設定する。"""
        self._log_box_border = enabled
        self.update()

    def set_log_on_top(self, enabled: bool):
        """ログ前面表示ON/OFFを設定する。"""
        self._log_on_top = enabled
        self.update()

    def get_log_entries(self) -> list[tuple[str, str]]:
        """ログ履歴を返す（新しい順の (時刻, テキスト) リスト）。"""
        return list(self._log_entries)

    def save_log(self, path: str):
        """ログ履歴をJSONファイルに保存する。"""
        import json
        # 古い順で保存
        data = [{"ts": ts, "text": text} for ts, text in reversed(self._log_entries)]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_log(self, path: str):
        """JSONファイルからログ履歴を復元する。"""
        import json
        import os
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return
            # 古い順で保存されている → 新しい順に変換
            entries = []
            for item in data:
                if isinstance(item, dict) and "ts" in item and "text" in item:
                    entries.append((item["ts"], item["text"]))
            self._log_entries = list(reversed(entries[-self._log_max:]))
            self.update()
        except Exception:
            pass

    def clear_log(self):
        """ログ履歴をクリアする。"""
        self._log_entries.clear()
        self.update()

    def set_transparent(self, enabled: bool):
        """透過モードを設定する。"""
        self._transparent = enabled
        self.update()

    def seg_at_pointer(self) -> int:
        """pointer が指しているセグメント番号を返す。"""
        segs = self._segments
        if not segs:
            return -1
        offset = (self._angle - self._pointer_angle) % 360
        cumulative = 0.0
        for i, seg in enumerate(segs):
            cumulative += seg.arc
            if offset < cumulative:
                return i
        return len(segs) - 1

    def result_at_pointer(self) -> str | None:
        """pointer が指しているセグメントのテキストを返す。"""
        idx = self.seg_at_pointer()
        if idx < 0 or idx >= len(self._segments):
            return None
        return self._segments[idx].item_text

    def wheel_hit(self, local_x: float, local_y: float) -> bool:
        """ローカル座標がホイール円内かどうか。"""
        return math.hypot(local_x - self._cx, local_y - self._cy) <= self._r

    def hit_zone(self, local_x: float, local_y: float) -> str:
        """ローカル座標のヒットゾーンを判定する。

        Returns:
            "pointer"    — ポインター上
            "wheel_face" — 有効なホイール面（ドーナツ穴 ON 時はリング部分のみ）
            "outside"    — ホイール外またはドーナツ穴内
        """
        if self.pointer_hit(local_x, local_y):
            return "pointer"
        dist = math.hypot(local_x - self._cx, local_y - self._cy)
        if dist > self._r:
            return "outside"
        if self._donut_hole and dist < DONUT_HIT_RADIUS:
            return "outside"
        return "wheel_face"

    def pointer_hit(self, local_x: float, local_y: float) -> bool:
        """ローカル座標がポインター上かどうか（ヒット半径 26px）。"""
        t = math.radians(self._pointer_angle)
        st, ct = math.sin(t), math.cos(t)
        px = self._cx + st * (self._r + 8)
        py = self._cy - ct * (self._r + 8)
        return math.hypot(local_x - px, local_y - py) < 26

    def angle_from_pos(self, local_x: float, local_y: float) -> float:
        """ローカル座標から wheel 中心基準の角度（度）を算出する。"""
        dx = local_x - self._cx
        dy = local_y - self._cy
        return math.degrees(math.atan2(dx, -dy)) % 360

    # ================================================================
    #  描画パラメータ計算
    # ================================================================

    def _update_geometry(self):
        """ウィジェットの実サイズから中心・半径を算出する。"""
        w = self.width()
        h = self.height()
        self._cx = w / 2.0
        self._cy = h / 2.0
        self._r = max(MIN_R, min(w, h) / 2.0 - WHEEL_OUTER_MARGIN)

    def _build_cache_key(self) -> tuple:
        """レイアウトキャッシュキーを構築する。"""
        _wf = self._design.fonts.wheel
        return (
            tuple(self._items),
            tuple(int(seg.arc * 100) for seg in self._segments),
            self._cx, self._cy, self._r,
            self._text_size_mode, self._text_direction,
            self._donut_hole,
            _wf.family, _wf.omit_base_size, _wf.fit_base_size,
            _wf.shrink_base_size, _wf.min_size, _wf.max_size,
        )

    def _rebuild_layout_cache(self):
        """既存の layout_search エンジンを使ってテキスト配置を計算する。"""
        donut_r = float(DONUT_DRAW_RADIUS) if self._donut_hole else 0.0
        _wf = self._design.fonts.wheel
        mode = self._text_size_mode

        _min = _wf.min_size
        _max = _wf.max_size
        if mode == 0:
            fixed_size = max(_min, min(_max, _wf.omit_base_size))
            effective_max = _max
        elif mode == 1:
            fixed_size = max(_min, min(_max, _wf.fit_base_size))
            effective_max = max(_min, min(_max, _wf.fit_base_size))
        else:
            fixed_size = max(_min, min(_max, _wf.shrink_base_size))
            effective_max = _max

        self._layout_cache = build_all_sector_layouts(
            items=self._items,
            wheel_cx=self._cx,
            wheel_cy=self._cy,
            R=self._r,
            text_size_mode=mode,
            text_direction=self._text_direction,
            font_family=_wf.family,
            fixed_font_size=fixed_size,
            min_size=_min,
            max_size=effective_max,
            donut_r=donut_r,
            segments=self._segments if self._segments else None,
        )
        self._layout_cache_key = self._build_cache_key()

    # ================================================================
    #  Qt イベント
    # ================================================================

    def resizeEvent(self, event):
        self._update_geometry()
        self._layout_cache_key = None  # サイズ変更でキャッシュ無効化
        super().resizeEvent(event)

    def paintEvent(self, event):
        """ホイール全体を QPainter で描画する。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        d = self._design
        if self._transparent:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        else:
            painter.fillRect(self.rect(), QColor(d.bg))

        cx, cy, r = self._cx, self._cy, self._r
        segs = self._segments

        if not segs:
            painter.setPen(QColor(d.wheel.text_color))
            painter.setFont(QFont("Meiryo", 13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "項目を追加してください")
            painter.end()
            return

        # --- レイアウトキャッシュ更新 ---
        cache_key = self._build_cache_key()
        if self._layout_cache_key != cache_key:
            self._rebuild_layout_cache()
        cache_valid = (
            self._layout_cache is not None
            and len(self._layout_cache) == len(segs)
        )

        # --- セグメント描画 ---
        bbox = QRectF(cx - r, cy - r, r * 2, r * 2)

        for i, seg in enumerate(segs):
            seg_start = 90.0 - self._angle + seg.start_angle
            color = QColor(d.segment.color_for(seg.item_index))

            start_16 = int(seg_start * 16)
            arc_16 = int(seg.arc * 16)

            painter.setPen(QPen(QColor(d.wheel.segment_outline_color),
                                d.wheel.segment_outline_width))
            painter.setBrush(QBrush(color))
            painter.drawPie(bbox, start_16, arc_16)

            # --- テキスト描画（layout_search エンジン使用）---
            if not cache_valid:
                continue

            self._draw_sector_text(painter, i, seg_start, seg.arc, cx, cy)

        # --- ログオーバーレイ（背面モード: ホイール装飾の後ろ） ---
        if self._log_visible and self._log_entries and not self._log_on_top:
            self._draw_log_overlay(painter, d)

        # --- 外周線 ---
        painter.setPen(QPen(QColor(d.wheel.outline_color), d.wheel.outline_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(bbox)

        # --- ドーナツ穴 ---
        if self._donut_hole:
            hole_r = DONUT_DRAW_RADIUS
            painter.setPen(QPen(QColor(d.wheel.hole_outline_color),
                                d.wheel.hole_outline_width))
            hole_fill = QColor(0, 0, 0, 0) if self._transparent else QColor(d.bg)
            painter.setBrush(QBrush(hole_fill))
            painter.drawEllipse(QRectF(cx - hole_r, cy - hole_r,
                                       hole_r * 2, hole_r * 2))

        # --- ポインター ---
        self._draw_pointer(painter, cx, cy, r, d)

        # --- ログオーバーレイ（前面モード: ポインターの上） ---
        if self._log_visible and self._log_entries and self._log_on_top:
            self._draw_log_overlay(painter, d)

        painter.end()

    def _draw_sector_text(self, painter: QPainter, i: int,
                          seg_start: float, seg_arc: float,
                          cx: float, cy: float):
        """1セクターのテキストを layout_search の結果に基づいて描画する。"""
        lay = self._layout_cache[i]
        d = self._design
        text_color = QColor(d.wheel.text_color)
        draw_font = QFont(lay.font_family, lay.font_size, QFont.Weight.Bold)

        mid_deg = seg_start + seg_arc / 2.0
        mid_rad = math.radians(mid_deg)

        painter.setPen(text_color)
        painter.setFont(draw_font)

        if lay.direction == 4:
            # 縦表示3（常に垂直・直立縦積み）
            lx = cx + lay.center_r * math.cos(mid_rad)
            ly = cy - lay.center_r * math.sin(mid_rad)
            fm = QFontMetrics(draw_font)
            text = lay.lines[0].text
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            painter.drawText(QRectF(lx - tw / 2, ly - th / 2, tw, th),
                             Qt.AlignmentFlag.AlignCenter, text)

        elif lay.direction == 1:
            # 横表示2（常に水平）
            base_x = cx + lay.center_r * math.cos(mid_rad)
            base_y = cy - lay.center_r * math.sin(mid_rad)
            fm = QFontMetrics(draw_font)
            for lp in lay.lines:
                text = lp.text
                tw = fm.horizontalAdvance(text)
                th = fm.height()
                painter.drawText(
                    QRectF(base_x - tw / 2, base_y + lp.stack_offset - th / 2, tw, th),
                    Qt.AlignmentFlag.AlignCenter, text,
                )

        elif lay.direction == 0:
            # 横表示1（内→外、回転）
            cos_m = math.cos(mid_rad)
            sin_m = math.sin(mid_rad)
            tan_x = sin_m
            tan_y = cos_m
            fm = QFontMetrics(draw_font)
            for lp in lay.lines:
                _r = lp.radial_center if lp.radial_center >= 0 else lay.center_r
                bx = cx + _r * cos_m
                by = cy - _r * sin_m
                s = lp.stack_offset
                lx = bx + s * tan_x
                ly = by + s * tan_y
                text = lp.text
                tw = fm.horizontalAdvance(text)
                th = fm.height()

                painter.save()
                painter.translate(lx, ly)
                painter.rotate(-mid_deg)
                painter.drawText(QRectF(-tw / 2, -th / 2, tw, th),
                                 Qt.AlignmentFlag.AlignCenter, text)
                painter.restore()

        else:
            # 縦表示1/2
            angle = -mid_deg + 90 if lay.direction == 2 else -mid_deg - 90
            tan_x = math.sin(mid_rad)
            tan_y = math.cos(mid_rad)
            fm = QFontMetrics(draw_font)
            for lp in lay.lines:
                _r = lay.center_r + lp.stack_offset
                lx = cx + _r * math.cos(mid_rad) + lp.extra_offset * tan_x
                ly = cy - _r * math.sin(mid_rad) + lp.extra_offset * tan_y
                text = lp.text
                tw = fm.horizontalAdvance(text)
                th = fm.height()

                painter.save()
                painter.translate(lx, ly)
                painter.rotate(angle)
                painter.drawText(QRectF(-tw / 2, -th / 2, tw, th),
                                 Qt.AlignmentFlag.AlignCenter, text)
                painter.restore()

    def _draw_pointer(self, painter: QPainter, cx: float, cy: float,
                      r: float, d: DesignSettings):
        """ポインターを描画する。"""
        t = math.radians(self._pointer_angle)
        st, ct = math.sin(t), math.cos(t)

        tip_x = cx + st * (r - 12)
        tip_y = cy - ct * (r - 12)
        bl_x = cx + st * (r + POINTER_OVERHANG) - ct * 14
        bl_y = cy - ct * (r + POINTER_OVERHANG) - st * 14
        br_x = cx + st * (r + POINTER_OVERHANG) + ct * 14
        br_y = cy - ct * (r + POINTER_OVERHANG) + st * 14

        pointer = [QPointF(bl_x, bl_y), QPointF(br_x, br_y), QPointF(tip_x, tip_y)]

        painter.setPen(QPen(QColor(d.pointer.outline_color), d.pointer.outline_width))
        painter.setBrush(QBrush(QColor(d.pointer.fill_color)))
        painter.drawPolygon(pointer)

    def _draw_log_overlay(self, painter: QPainter, d: DesignSettings):
        """ログオーバーレイを左下に描画する。"""
        log_font = QFont(d.fonts.log_family or "Meiryo", d.log.font_size)
        fm = QFontMetrics(log_font)
        line_h = fm.height() + 2
        padding = 6
        margin = 8

        entries = self._log_entries
        n = len(entries)
        if n == 0:
            return

        # 表示文字列を構築
        show_ts = self._log_timestamp
        lines = []
        for i, (ts, text) in enumerate(entries):
            num = f"{n - i}."
            if show_ts:
                lines.append(f"{num} [{ts}] {text}")
            else:
                lines.append(f"{num} {text}")

        # テキスト幅の最大値を算出
        max_text_w = 0
        for line in lines:
            w = fm.horizontalAdvance(line)
            if w > max_text_w:
                max_text_w = w

        box_w = max_text_w + padding * 2
        box_h = line_h * n + padding * 2

        # 左下に配置
        box_x = margin
        box_y = self.height() - margin - box_h

        # 背景ボックス
        bg_color = QColor(d.log.box_bg_color)
        bg_color.setAlpha(180)
        if self._log_box_border:
            painter.setPen(QPen(QColor(d.log.box_outline_color), 1))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(QRectF(box_x, box_y, box_w, box_h), 4, 4)

        # テキスト描画
        painter.setFont(log_font)
        text_color = QColor(d.log.text_color)
        shadow_color = QColor(d.log.shadow_color)

        for i, line in enumerate(lines):
            y = box_y + padding + (i + 1) * line_h - fm.descent()
            x = box_x + padding
            # 影
            painter.setPen(shadow_color)
            painter.drawText(QPointF(x + 1, y + 1), line)
            # 本体
            painter.setPen(text_color)
            painter.drawText(QPointF(x, y), line)
