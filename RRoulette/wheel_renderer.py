"""
RRoulette — ホイール描画 Mixin
  - _redraw: ルーレットホイール・ポインターの Canvas 描画
  - _seg_at_pointer: ポインターが指しているセグメント番号
  - ポインター操作ヘルパー (_pointer_pos, _pointer_hit, _apply_pointer_preset)
  - _on_cv_motion: ポインター上でカーソル変更
  - _on_canvas_resize: Canvas サイズ変化時のホイール再計算
"""

import math

from constants import (
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES, MIN_R, TRANSPARENT_KEY,
    WHEEL_OUTER_MARGIN, DONUT_DRAW_RADIUS,
)


class WheelRendererMixin:

    # ════════════════════════════════════════════════════════════════
    #  キャンバスサイズ変化時のホイール再計算
    # ════════════════════════════════════════════════════════════════
    def _on_canvas_resize(self, event):
        # サイドバー幅 / 設定パネル幅のドラッグ中は描画をスキップ（軽量プレビュー）
        if getattr(self, "_sashing", False) or getattr(self, "_cfg_resizing", False):
            return
        cw, ch = event.width, event.height
        # ポインターが縁から POINTER_OVERHANG px 飛び出すため WHEEL_OUTER_MARGIN px 確保
        r = max(MIN_R, min(cw, ch) // 2 - WHEEL_OUTER_MARGIN)
        self.CX = cw // 2
        self.CY = ch // 2
        self.R  = r
        # ウィンドウ縮小でサイドバーが溢れないようクランプ
        self._clamp_sidebar_w()
        # グリップドラッグ中: 軽量ホイール描画（セグメント色・外周・ポインター）
        if getattr(self, "_resizing", False):
            if self._resize_redraw_id:
                self.root.after_cancel(self._resize_redraw_id)
                self._resize_redraw_id = None
            self._redraw_simple()
            return
        # 連続 Configure をデバウンス（50ms）
        if self._resize_redraw_id:
            self.root.after_cancel(self._resize_redraw_id)
        self._resize_redraw_id = self.root.after(50, self._redraw)

    # ════════════════════════════════════════════════════════════════
    #  新レイアウトエンジン: キャッシュ構築
    # ════════════════════════════════════════════════════════════════
    def _rebuild_layout_cache(self):
        """新レイアウトエンジン用のレイアウトキャッシュを構築する。"""
        from layout_search import build_all_sector_layouts
        donut_r = float(DONUT_DRAW_RADIUS) if getattr(self, '_donut_hole', False) else 0.0
        _wf = self._design.fonts.wheel
        mode = self._text_size_mode

        # WheelFontSettings のモード別基準サイズを実接続する
        # mode 0 (省略): omit_base_size = 固定描画サイズ（収まらない場合は省略記号）
        # mode 1 (収める): fit_base_size = 探索上限（この値まで大きく置こうとする）
        # mode 2 (縮小): shrink_base_size = 初期基準サイズ（収まらない場合のみ縮小）
        _min = _wf.min_size
        _max = _wf.max_size
        if mode == 0:   # 省略
            fixed_size   = max(_min, min(_max, _wf.omit_base_size))
            effective_max = _max
        elif mode == 1: # 収める
            fixed_size   = max(_min, min(_max, _wf.fit_base_size))
            effective_max = max(_min, min(_max, _wf.fit_base_size))
        else:           # 縮小
            fixed_size   = max(_min, min(_max, _wf.shrink_base_size))
            effective_max = _max

        self._layout_cache = build_all_sector_layouts(
            items=self.items,
            wheel_cx=self.CX,
            wheel_cy=self.CY,
            R=self.R,
            text_size_mode=mode,
            text_direction=self._text_direction,
            font_family=_wf.family,
            fixed_font_size=fixed_size,
            min_size=_min,
            max_size=effective_max,
            donut_r=donut_r,
            segments=getattr(self, 'current_segments', None),
        )
        self._layout_cache_key = (
            tuple(self.items),
            tuple(int(seg.arc * 100) for seg in getattr(self, 'current_segments', [])),
            self.R, mode, self._text_direction,
            self._donut_hole,
            _wf.family, _wf.omit_base_size, _wf.fit_base_size, _wf.shrink_base_size,
            _wf.min_size, _wf.max_size,
        )

    # ════════════════════════════════════════════════════════════════
    #  リサイズ中簡略描画（セグメント色・外周・ポインターのみ、テキスト/ログなし）
    # ════════════════════════════════════════════════════════════════
    def _redraw_simple(self):
        """リサイズドラッグ中の軽量表示。レイアウト再計算なし。"""
        self.cv.delete("all")
        cx, cy, r = self.CX, self.CY, self.R
        segs = getattr(self, 'current_segments', [])
        d = self._design
        if segs:
            for seg in segs:
                seg_start = 90 - self.angle + seg.start_angle
                color = d.segment.color_for(seg.item_index)
                self.cv.create_arc(
                    cx - r, cy - r, cx + r, cy + r,
                    start=seg_start, extent=seg.arc,
                    fill=color, outline=d.wheel.segment_outline_color,
                    width=d.wheel.segment_outline_width,
                )
        self.cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                            fill="", outline=d.wheel.outline_color,
                            width=d.wheel.outline_width)
        if getattr(self, "_donut_hole", False):
            hole_fill = TRANSPARENT_KEY if getattr(self, "_transparent", False) else d.bg
            self.cv.create_oval(cx - 13, cy - 13, cx + 13, cy + 13,
                                fill=hole_fill, outline=d.wheel.hole_outline_color,
                                width=d.wheel.hole_outline_width)
        t = math.radians(self._pointer_angle)
        st, ct = math.sin(t), math.cos(t)
        tip_x = cx + st * (r - 12)
        tip_y = cy - ct * (r - 12)
        bl_x  = cx + st * (r + 28) - ct * 14
        bl_y  = cy - ct * (r + 28) - st * 14
        br_x  = cx + st * (r + 28) + ct * 14
        br_y  = cy - ct * (r + 28) + st * 14
        self.cv.create_polygon(
            bl_x, bl_y, br_x, br_y, tip_x, tip_y,
            fill=d.pointer.fill_color, outline=d.pointer.outline_color,
            width=d.pointer.outline_width,
        )

    # ════════════════════════════════════════════════════════════════
    #  ホイール描画
    # ════════════════════════════════════════════════════════════════
    def _redraw(self):
        self._resize_redraw_id = None
        # フラッシュアニメーション中は result_overlay / log_overlay を
        # 上書きしないようスキップする
        if getattr(self, "_flashing", False):
            return
        self.cv.delete("all")
        cx, cy, r = self.CX, self.CY, self.R
        n = len(self.items)

        # _log_on_top=False のときログをホイールより先に描画（ホイールが前面）
        # _log_on_top=True  のときログをホイールより後に描画（ログが前面）
        # donut_hole=True かつ transparent=True の場合、ログが背面でも穴部分の
        # ログ pixels は hole 描画（TRANSPARENT_KEY）で上書きされるため、
        # 穴からログが透けて見えることはない。
        log_on_top = getattr(self, "_log_on_top", False)
        if not log_on_top:
            self._draw_log_overlay()

        segs = getattr(self, 'current_segments', [])
        n = len(segs)

        _d = self._design
        if n == 0:
            self.cv.create_text(cx, cy, text="項目を追加してください",
                                fill=_d.wheel.text_color, font=("Meiryo", 13),
                                tags=("wheel_text", "wheel_all"))
        else:
            # ── 新レイアウトエンジン: キャッシュ確認・再構築 ─────────────
            _cache_valid = True
            _wf_key = self._design.fonts.wheel
            _cache_key = (
                tuple(self.items),
                tuple(int(seg.arc * 100) for seg in segs),
                self.R, self._text_size_mode, self._text_direction,
                self._donut_hole,
                _wf_key.family, _wf_key.omit_base_size, _wf_key.fit_base_size,
                _wf_key.shrink_base_size, _wf_key.min_size, _wf_key.max_size,
            )
            if getattr(self, '_layout_cache_key', None) != _cache_key:
                _drag = (getattr(self, '_resizing', False)
                         or getattr(self, '_sashing', False)
                         or getattr(self, '_cfg_resizing', False))
                if not self.spinning and not _drag:
                    self._rebuild_layout_cache()
                else:
                    _cache_valid = False
            if _cache_valid and (
                not getattr(self, '_layout_cache', None)
                or len(self._layout_cache) != n
            ):
                _cache_valid = False

            for i, seg in enumerate(segs):
                seg_start = 90 - self.angle + seg.start_angle
                seg_arc   = seg.arc
                color = _d.segment.color_for(seg.item_index)

                self.cv.create_arc(
                    cx - r, cy - r, cx + r, cy + r,
                    start=seg_start, extent=seg_arc,
                    fill=color, outline=_d.wheel.segment_outline_color,
                    width=_d.wheel.segment_outline_width,
                    tags=("wheel_sector", "wheel_all"),
                )

                mid_deg = seg_start + seg_arc / 2
                mid_rad = math.radians(mid_deg)

                if not _cache_valid:
                    continue

                # ── 新レイアウトエンジン描画 ──────────────────────────
                _lay = self._layout_cache[i]
                _draw_font = (_lay.font_family, _lay.font_size, "bold")

                if _lay.direction == 4:
                    # 縦表示3（常に垂直・直立縦積み）: center_r 位置に angle=0 で単一 create_text
                    _lx = cx + _lay.center_r * math.cos(mid_rad)
                    _ly = cy - _lay.center_r * math.sin(mid_rad)
                    self.cv.create_text(
                        _lx, _ly, text=_lay.lines[0].text, fill=_d.wheel.text_color,
                        font=_draw_font, angle=0,
                        tags=("wheel_text", "wheel_all"),
                    )
                elif _lay.direction == 1:
                    # 横表示2（常に水平）: center_r 位置を基点として垂直方向に各行を積む
                    _base_x = cx + _lay.center_r * math.cos(mid_rad)
                    _base_y = cy - _lay.center_r * math.sin(mid_rad)
                    for _lp in _lay.lines:
                        self.cv.create_text(
                            _base_x, _base_y + _lp.stack_offset,
                            text=_lp.text, fill=_d.wheel.text_color,
                            font=_draw_font, angle=0,
                            tags=("wheel_text", "wheel_all"),
                        )
                elif _lay.direction == 0:
                    # 横表示1（内→外）: 行ごとの放射方向中心から接線方向に変位
                    # LinePlacement.radial_center >= 0 なら行個別の放射中心を使用（外周端基準）
                    # キャンバス座標系(Y下向き)での接線方向単位ベクトル:
                    #   radial = (cos, -sin),  tangential = (sin, cos)
                    _cos_m  = math.cos(mid_rad)
                    _sin_m  = math.sin(mid_rad)
                    _tan_x  = _sin_m
                    _tan_y  = _cos_m
                    for _lp in _lay.lines:
                        _r = _lp.radial_center if _lp.radial_center >= 0 else _lay.center_r
                        _bx = cx + _r * _cos_m
                        _by = cy - _r * _sin_m
                        _s  = _lp.stack_offset
                        _lx = _bx + _s * _tan_x
                        _ly = _by + _s * _tan_y
                        self.cv.create_text(
                            _lx, _ly, text=_lp.text, fill=_d.wheel.text_color,
                            font=_draw_font, angle=mid_deg,
                            tags=("wheel_text", "wheel_all"),
                        )
                else:
                    # 縦表示1/2: stack_offset=放射方向, extra_offset=接線方向（複数列）
                    # center_r + stack_offset が各文字の実際の半径
                    # 接線方向単位ベクトル（canvas Y下向き）: (sin, cos)
                    _angle = mid_deg - 90 if _lay.direction == 2 else mid_deg + 90
                    _tan_x = math.sin(mid_rad)
                    _tan_y = math.cos(mid_rad)
                    for _lp in _lay.lines:
                        _r  = _lay.center_r + _lp.stack_offset
                        _lx = cx + _r * math.cos(mid_rad) + _lp.extra_offset * _tan_x
                        _ly = cy - _r * math.sin(mid_rad) + _lp.extra_offset * _tan_y
                        self.cv.create_text(
                            _lx, _ly, text=_lp.text, fill=_d.wheel.text_color,
                            font=_draw_font, angle=_angle,
                            tags=("wheel_text", "wheel_all"),
                        )

        self.cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                            fill="", outline=_d.wheel.outline_color,
                            width=_d.wheel.outline_width,
                            tags=("wheel_outline", "wheel_all"))
        if getattr(self, "_donut_hole", False):
            hole_fill = TRANSPARENT_KEY if getattr(self, "_transparent", False) else _d.bg
            self.cv.create_oval(cx - 13, cy - 13, cx + 13, cy + 13,
                                fill=hole_fill, outline=_d.wheel.hole_outline_color,
                                width=_d.wheel.hole_outline_width,
                                tags=("wheel_hole", "wheel_all"))
        t   = math.radians(self._pointer_angle)
        st, ct = math.sin(t), math.cos(t)
        tip_x  = cx + st * (r - 12)
        tip_y  = cy - ct * (r - 12)
        bl_x   = cx + st * (r + 28) - ct * 14
        bl_y   = cy - ct * (r + 28) - st * 14
        br_x   = cx + st * (r + 28) + ct * 14
        br_y   = cy - ct * (r + 28) + st * 14
        self.cv.create_polygon(
            bl_x, bl_y, br_x, br_y, tip_x, tip_y,
            fill=_d.pointer.fill_color, outline=_d.pointer.outline_color,
            width=_d.pointer.outline_width,
            tags=("pointer", "wheel_all"),
        )

        if log_on_top:
            self._draw_log_overlay()

        # リプレイ中表示（_replaying 中は毎フレーム再描画）
        if getattr(self, "_replaying", False):
            self._replay_show_indicator()

    # ════════════════════════════════════════════════════════════════
    #  ログオーバーレイ描画
    # ════════════════════════════════════════════════════════════════
    def _draw_log_overlay(self):
        """履歴をキャンバス左端に描画する。新しいログが上、古いログが下。
        描画は 3 フェーズに分け、tag_lower を使わず描画順で z-order を制御する。
          Phase 1: 仮テキストで位置・bbox を確定（即削除）
          Phase 2: ボックス枠を描画（後続テキストより下になる）
          Phase 3: シャドウ＋本体テキストを描画
        """
        self._log_item_rects = []

        if not getattr(self, "_log_overlay_show", True) or not self._history:
            return

        PAD_X      = 10
        PAD_Y      = 10
        LINE_H     = 18
        BOX_PAD    = 4
        ENTRY_GAP  = 3
        MAX_ENT    = 20
        _ld        = self._design.log
        FONT       = (self._design.fonts.log_family, _ld.font_size)
        COL_FG     = _ld.text_color
        COL_SHD    = _ld.shadow_color
        COL_BOX    = _ld.box_outline_color
        COL_BOX_BG = _ld.box_bg_color

        log_box = getattr(self, "_log_box_border", False)
        entries = self._history[-MAX_ENT:][::-1]

        # ── Phase 1: 各エントリーのテキスト・座標・bbox を確定 ──────────
        layout = []   # (i, entry, text, tx, y, bbox)
        y = PAD_Y
        for i, entry in enumerate(entries):
            if self._log_timestamp:
                ts   = entry["timestamp"][11:19]
                text = f"{ts}  {entry['result']}"
            else:
                text = entry["result"]

            tx = PAD_X + (BOX_PAD if log_box else 0)

            # 仮テキストで bbox を取得してすぐ削除
            tmp = self.cv.create_text(tx, y, text=text, anchor="nw", font=FONT)
            bbox = self.cv.bbox(tmp)
            self.cv.delete(tmp)

            if bbox:
                layout.append((i, entry, text, tx, y, bbox))
                entry_h = bbox[3] - bbox[1]
                y += entry_h + ENTRY_GAP + (BOX_PAD * 2 if log_box else 0)
            else:
                n_lines = text.count("\n") + 1
                y += n_lines * LINE_H + ENTRY_GAP

        # ── Phase 2: ボックス枠（テキストより先に描画 → z-order で後ろ）──
        if log_box:
            for i, entry, text, tx, y_pos, bbox in layout:
                self.cv.create_rectangle(
                    PAD_X - BOX_PAD, y_pos - BOX_PAD,
                    bbox[2] + BOX_PAD, bbox[3] + BOX_PAD,
                    outline=COL_BOX, fill=COL_BOX_BG, width=1,
                    tags="log_overlay",
                )

        # ── Phase 3: シャドウ＋本体テキスト（ボックスより後に描画 → 前面）─
        for i, entry, text, tx, y_pos, bbox in layout:
            self.cv.create_text(
                tx + 1, y_pos + 1, text=text, anchor="nw",
                font=FONT, fill=COL_SHD, tags="log_overlay",
            )
            self.cv.create_text(
                tx, y_pos, text=text, anchor="nw",
                font=FONT, fill=COL_FG,
                tags=("log_overlay", f"log_item_{i}"),
            )
            self._log_item_rects.append((bbox, entry))

    # ════════════════════════════════════════════════════════════════
    #  ポインターが指しているセグメント番号
    # ════════════════════════════════════════════════════════════════
    def _seg_at_pointer(self) -> int:
        segs = getattr(self, 'current_segments', None)
        if not segs:
            return -1
        offset = (self.angle - self._pointer_angle) % 360
        cumulative = 0.0
        for i, seg in enumerate(segs):
            cumulative += seg.arc
            if offset < cumulative:
                return i
        return len(segs) - 1

    # ════════════════════════════════════════════════════════════════
    #  ポインター操作ヘルパー
    # ════════════════════════════════════════════════════════════════
    def _pointer_pos(self):
        """ポインター中心のキャンバス座標を返す"""
        t = math.radians(self._pointer_angle)
        return (self.CX + math.sin(t) * (self.R + 8),
                self.CY - math.cos(t) * (self.R + 8))

    def _pointer_hit(self, cv_x: float, cv_y: float) -> bool:
        """キャンバス座標がポインター上かどうか（ヒット半径 26px）"""
        mx, my = self._pointer_pos()
        return math.hypot(cv_x - mx, cv_y - my) < 26

    # ════════════════════════════════════════════════════════════════
    #  ログホバー キャンバス内ポップアップ（OBS対応）
    # ════════════════════════════════════════════════════════════════
    def _show_log_popup(self, entry: dict, mx: int, my: int):
        """ログエントリーのホバー情報をキャンバス上に直接描画する。"""
        self.cv.delete("log_popup_overlay")

        _pd       = self._design
        _log_fam  = _pd.fonts.log_family
        FONT_BOLD = (_log_fam, 9, "bold")
        FONT_NORM = (_log_fam, 9)
        PAD       = 8
        GAP       = 4
        PER_ROW   = 5

        items  = entry["items"]
        result = entry["result"]

        # 当選を★でマークした項目行を構築
        marked = [f"★{it}" if it == result else f"  {it}" for it in items]
        item_rows = []
        for i in range(0, len(marked), PER_ROW):
            item_rows.append("  ".join(marked[i : i + PER_ROW]))
        items_text = "\n".join(item_rows)
        group_text = f"グループ: {entry['group']}"

        # サイズ計測（仮描画 → bbox → 即削除）
        g_id = self.cv.create_text(0, 0, text=group_text, font=FONT_BOLD, anchor="nw")
        i_id = self.cv.create_text(0, 0, text=items_text, font=FONT_NORM, anchor="nw")
        gb   = self.cv.bbox(g_id)
        ib   = self.cv.bbox(i_id)
        self.cv.delete(g_id)
        self.cv.delete(i_id)

        gw = gb[2] - gb[0];  gh = gb[3] - gb[1]
        iw = ib[2] - ib[0];  ih = ib[3] - ib[1]
        total_w = max(gw, iw)
        total_h = gh + GAP * 2 + 1 + GAP + ih   # グループ行 + セパ + 項目行

        # ポップアップ位置（キャンバス端でクランプ）
        cw = self.cv.winfo_width()
        ch = self.cv.winfo_height()
        px = mx + 14
        py = my + 14
        if px + total_w + PAD * 2 > cw:
            px = mx - total_w - PAD * 2 - 14
        if py + total_h + PAD * 2 > ch:
            py = my - total_h - PAD * 2 - 14
        px = max(PAD, px)
        py = max(PAD, py)

        # 背景矩形
        self.cv.create_rectangle(
            px - PAD, py - PAD,
            px + total_w + PAD, py + total_h + PAD,
            fill=_pd.panel, outline=_pd.accent, width=2,
            tags="log_popup_overlay",
        )
        # グループ名（gold + bold）
        self.cv.create_text(
            px, py, text=group_text, anchor="nw",
            font=FONT_BOLD, fill=_pd.gold,
            tags="log_popup_overlay",
        )
        # セパレータ線
        sep_y = py + gh + GAP
        self.cv.create_line(
            px - PAD + 2, sep_y,
            px + total_w + PAD - 2, sep_y,
            fill=_pd.separator, width=1,
            tags="log_popup_overlay",
        )
        # 項目テキスト（当選は★付き）
        self.cv.create_text(
            px, sep_y + GAP, text=items_text, anchor="nw",
            font=FONT_NORM, fill=_pd.text,
            tags="log_popup_overlay",
        )

    def _hide_log_popup(self):
        """キャンバス上のホバーポップアップを消去する。"""
        self.cv.delete("log_popup_overlay")
        self._log_hover_idx = -1

    def _apply_pointer_preset(self, preset: int):
        """プリセット(0=上,1=右,2=下,3=左,4=任意)を適用"""
        self._pointer_preset = preset
        if preset < 4:
            self._pointer_angle = _POINTER_PRESET_ANGLES[preset]
        if self._pointer_preset_var is not None:
            self._pointer_preset_var.set(POINTER_PRESET_NAMES[preset])
        self._save_config()
        self._redraw()

    def _on_cv_motion(self, event):
        """ポインター上でカーソルを hand2 に変更（スピン中ロック時は変更しない）"""
        if getattr(self, "_flashing", False):
            return
        if self._dragging_pointer:
            return
        if self.spinning and self._pointer_lock_while_spinning:
            self.cv.config(cursor="")
            self._hide_log_popup()
            self._log_hover_idx = -1
            return
        if self._pointer_hit(event.x, event.y):
            self.cv.config(cursor="hand2")
            self._hide_log_popup()
            self._log_hover_idx = -1
            return
        else:
            self.cv.config(cursor="")

        # ── ログオーバーレイ ホバー判定 ──────────────────────
        if getattr(self, "_log_overlay_show", True) and self._log_item_rects:
            hit_idx = -1
            for idx, (bbox, _entry) in enumerate(self._log_item_rects):
                x1, y1, x2, y2 = bbox
                if x1 - 4 <= event.x <= x2 + 4 and y1 - 2 <= event.y <= y2 + 4:
                    hit_idx = idx
                    break

            if hit_idx != self._log_hover_idx:
                self._hide_log_popup()
                self._log_hover_idx = hit_idx
                if hit_idx >= 0:
                    _, entry = self._log_item_rects[hit_idx]
                    self._show_log_popup(entry, event.x, event.y)
        else:
            if self._log_hover_idx >= 0:
                self._hide_log_popup()
                self._log_hover_idx = -1
