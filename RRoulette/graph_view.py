"""
RRoulette — グラフ表示 Mixin
  - _build_graph_view: グラフ表示フレームの構築（初期は非表示）
  - _toggle_graph_view: ルーレット/グラフ表示切り替え
  - _toggle_graph_orientation: 横/縦棒グラフ切り替え（ctrl_box ボタンから呼ばれる）
  - _redraw_graph: 現在グループのログから棒グラフを描画
"""

import tkinter as tk

from constants import BG
from tooltip_utils import _SimpleTooltip



class GraphViewMixin:

    # ════════════════════════════════════════════════════════════════
    #  構築
    # ════════════════════════════════════════════════════════════════
    def _build_graph_view(self):
        """グラフ表示フレームを main_frame 内に構築する（初期は非表示）。"""
        self._graph_visible     = False
        self._graph_orientation = "horizontal"   # "horizontal" | "vertical"
        self._graph_orient_btn  = None           # ctrl_box 側で設定される
        self._graph_orient_wrap = None           # ctrl_box 側で設定される
        self._graph_sort_mode   = "list"         # "list" | "desc" | "asc"
        self._graph_sort_btn    = None           # ctrl_box 側で設定される

        self._graph_frame = tk.Frame(self.main_frame, bg=BG)

        # ctrl_box が main_frame 右上に place で重なるため上端を空ける
        _ctrl_spacer = tk.Frame(self._graph_frame, bg=BG, height=36)
        _ctrl_spacer.pack(fill=tk.X)
        _ctrl_spacer.pack_propagate(False)

        self._graph_cv = tk.Canvas(self._graph_frame, bg=BG, highlightthickness=0)
        self._graph_cv.pack(fill=tk.BOTH, expand=True)

        self._graph_cv.bind("<Configure>", lambda _e: self._redraw_graph())

        # グラフ表示中もウィンドウドラッグが効くよう直接バインド
        # （tkinter はデフォルトで子→親にイベントを伝播させないため必要）
        for _w in (self._graph_frame, self._graph_cv):
            _w.bind("<ButtonPress-1>", self._drag_start)
            _w.bind("<B1-Motion>",     self._drag_move)

    # ════════════════════════════════════════════════════════════════
    #  _redraw フック（グラフ表示中も最新状態を反映）
    # ════════════════════════════════════════════════════════════════
    def _redraw(self):
        super()._redraw()
        if getattr(self, "_graph_visible", False) and not getattr(self, "spinning", False):
            self._redraw_graph()

    # ════════════════════════════════════════════════════════════════
    #  表示切り替え
    # ════════════════════════════════════════════════════════════════
    def _toggle_graph_view(self):
        """ルーレット表示 ↔ グラフ表示を切り替える。"""
        if self._graph_visible:
            self._graph_frame.pack_forget()
            self.cv.pack(fill=tk.BOTH, expand=True)
            self._graph_visible = False
            if self._graph_orient_wrap:
                self._graph_orient_wrap.pack_forget()
            self._redraw()
        else:
            self.cv.pack_forget()
            self._graph_frame.pack(fill=tk.BOTH, expand=True)
            self._graph_visible = True
            if self._graph_orient_wrap and getattr(self, "_b_graph", None):
                self._graph_orient_wrap.pack(side=tk.LEFT, before=self._b_graph)
            self._graph_cv.after(10, self._redraw_graph)

    def _toggle_graph_orientation(self):
        """横棒 ↔ 縦棒を切り替える。"""
        if self._graph_orientation == "horizontal":
            self._graph_orientation = "vertical"
            if self._graph_orient_btn:
                self._graph_orient_btn.config(text="⇅")
        else:
            self._graph_orientation = "horizontal"
            if self._graph_orient_btn:
                self._graph_orient_btn.config(text="⇄")
        self._redraw_graph()

    _SORT_CYCLE = ["list", "desc", "asc"]
    _SORT_LABEL = {"list": "順", "desc": "↓多", "asc": "↑少"}

    def _toggle_graph_sort(self):
        """並び順モードを list → 多い順 → 少ない順 と巡回する。"""
        idx = self._SORT_CYCLE.index(self._graph_sort_mode)
        self._graph_sort_mode = self._SORT_CYCLE[(idx + 1) % 3]
        if self._graph_sort_btn:
            self._graph_sort_btn.config(text=self._SORT_LABEL[self._graph_sort_mode])
        self._redraw_graph()

    # ════════════════════════════════════════════════════════════════
    #  グラフ描画
    # ════════════════════════════════════════════════════════════════
    def _redraw_graph(self):
        """現在グループのログから棒グラフを描画する。"""
        if not getattr(self, "_graph_visible", False):
            return
        cv = self._graph_cv
        cv.delete("all")
        cw = cv.winfo_width()
        ch = cv.winfo_height()
        if cw <= 1 or ch <= 1:
            return

        # 現在の項目リスト順・インデックスを取得（ON の項目のみ）
        current_items = [
            (e.get("text", ""), idx)
            for idx, e in enumerate(self._item_entries)
            if e.get("text", "") and e.get("enabled", True)
        ]

        # 現在グループの結果を集計（同名単純カウント）
        counts: dict[str, int] = {}
        for entry in self._history:
            if entry.get("group") == self._current_pattern:
                name = entry.get("result", "")
                if name:
                    counts[name] = counts.get(name, 0) + 1

        # 現在リスト順・現在リスト内項目のみ・ヒットあり
        items = [
            (name, idx, counts[name])
            for name, idx in current_items
            if name in counts
        ]

        # 並び順モードに応じてソート（同値時はリスト順=idx で安定化）
        sort_mode = getattr(self, "_graph_sort_mode", "list")
        if sort_mode == "desc":
            items.sort(key=lambda x: (-x[2], x[1]))
        elif sort_mode == "asc":
            items.sort(key=lambda x: (x[2], x[1]))
        # "list" はそのまま（current_items がリスト順）

        if not items:
            cv.create_text(
                cw // 2, ch // 2,
                text=f"「{self._current_pattern}」のデータがありません",
                fill=self._design.text, font=(self._design.fonts.ui_family, 12),
            )
            return

        total     = sum(c for _, _, c in items)
        max_count = max(c for _, _, c in items)

        if self._graph_orientation == "horizontal":
            self._draw_bar_horizontal(cv, items, total, max_count, cw, ch)
        else:
            self._draw_bar_vertical(cv, items, total, max_count, cw, ch)

    # ────────────────────────────────────────────────────────────────
    #  横棒グラフ
    # ────────────────────────────────────────────────────────────────
    def _draw_bar_horizontal(self, cv, items, total, max_count, cw, ch):
        n = len(items)
        PAD_L   = 8
        PAD_R   = 8
        PAD_T   = 36
        PAD_B   = 10
        LABEL_W = min(140, max(60, int(cw * 0.28)))
        VALUE_W = 90
        bar_area_w = max(10, cw - PAD_L - LABEL_W - VALUE_W - PAD_R)

        avail_h  = ch - PAD_T - PAD_B
        bar_unit = avail_h / n if n > 0 else avail_h
        bar_h    = max(4, bar_unit * 0.72)

        for i, (name, item_idx, count) in enumerate(items):
            color  = self._design.segment.color_for(item_idx)
            border = self._design.wheel.outline_color
            y_center = PAD_T + (i + 0.5) * bar_unit
            y0 = y_center - bar_h / 2
            y1 = y_center + bar_h / 2

            # 項目名ラベル（右揃え）
            cv.create_text(
                PAD_L + LABEL_W - 4, y_center,
                text=name, fill=self._design.text, font=(self._design.fonts.ui_family, 9),
                anchor="e", width=LABEL_W - 4,
            )

            # バー（枠線付き）
            bw  = bar_area_w * count / max_count if max_count > 0 else 0
            bx0 = PAD_L + LABEL_W
            bx1 = bx0 + bw
            cv.create_rectangle(bx0, y0, bx1, y1, fill=color, outline=border, width=1)

            # 件数 + 割合
            pct = count / total * 100
            cv.create_text(
                bx1 + 4, y_center,
                text=f"{count} ({pct:.1f}%)",
                fill=self._design.text, font=(self._design.fonts.ui_family, 8), anchor="w",
            )

    # ────────────────────────────────────────────────────────────────
    #  縦棒グラフ
    # ────────────────────────────────────────────────────────────────
    def _draw_bar_vertical(self, cv, items, total, max_count, cw, ch):
        n = len(items)
        PAD_L  = 10
        PAD_R  = 10
        PAD_T  = 44
        PAD_B  = 46
        bar_area_h = max(10, ch - PAD_T - PAD_B)

        avail_w  = cw - PAD_L - PAD_R
        bar_unit = avail_w / n if n > 0 else avail_w
        bar_w    = max(4, bar_unit * 0.72)

        for i, (name, item_idx, count) in enumerate(items):
            color  = self._design.segment.color_for(item_idx)
            border = self._design.wheel.outline_color
            x_center = PAD_L + (i + 0.5) * bar_unit
            x0 = x_center - bar_w / 2
            x1 = x_center + bar_w / 2

            # バー（枠線付き）
            bh  = bar_area_h * count / max_count if max_count > 0 else 0
            by0 = ch - PAD_B - bh
            by1 = ch - PAD_B
            cv.create_rectangle(x0, by0, x1, by1, fill=color, outline=border, width=1)

            # 件数ラベル（バー上）
            pct = count / total * 100
            label_count = (
                f"{count}\n({pct:.1f}%)" if bar_unit >= 52 else str(count)
            )
            cv.create_text(
                x_center, by0 - 3,
                text=label_count,
                fill=self._design.text, font=(self._design.fonts.ui_family, 7), anchor="s",
            )

            # 項目名ラベル（バー下）
            short = name if len(name) <= 5 else name[:4] + "…"
            cv.create_text(
                x_center, ch - PAD_B + 4,
                text=short, fill=self._design.text, font=(self._design.fonts.ui_family, 8),
                anchor="n", width=max(bar_unit - 2, 8),
            )
