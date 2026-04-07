"""
RRoulette — デザインエディタ (v0.4.2)

UI 構造:
  ┌─────────────────────────────────────────────────────┐
  │  [デザインプリセット tab] [セグメント配色 tab]       │ ← 最上部タブ
  ├─────────────────────────────────────────────────────┤
  │  〈デザインプリセットタブ〉                          │
  │   ツールバー: Combobox 新規 複製 名前変更 削除       │
  │                リセット インポート エクスポート       │
  │   サブNotebook: 全体色/ホイール/ポインター/ログ/Font  │
  │  〈セグメント配色タブ〉                              │
  │   ツールバー: Combobox 新規 複製 名前変更 削除       │
  │                リセット インポート エクスポート       │
  │   カラーグリッド（スクロール可）                     │
  ├─────────────────────────────────────────────────────┤
  │  [✓即時反映] [今すぐ反映] [保存]  ステータス [閉じる] │ ← 下部固定バー
  └─────────────────────────────────────────────────────┘

方針:
  - 下部固定バーを先にpack(side=BOTTOM)して常時表示を保証
  - デザインプリセットとセグメント配色を同格・同型UIのタブとして提示
  - 起動時 lift() + focus_force() で前面表示
  - 本体 _topmost 設定に合わせてエディタも前面属性を同期
"""

import json
import os
import tkinter as tk
import tkinter.colorchooser as _colorchooser
import tkinter.filedialog as _filedialog
import tkinter.font as _tkfont
import tkinter.messagebox as _msgbox
import tkinter.ttk as ttk

from config_utils import EXPORT_DIR
from design_settings import (
    DesignPresetManager,
    DesignSettings,
    DESIGN_PRESETS,
    SEGMENT_COLOR_PRESETS,
)


# ────────────────────────────────────────────────────────────────────
#  ユーティリティ
# ────────────────────────────────────────────────────────────────────

def _is_valid_color(color: str) -> bool:
    if not color:
        return False
    if color.startswith("#") and len(color) in (4, 7):
        try:
            int(color[1:], 16)
            return True
        except ValueError:
            pass
    return False


def _ask_name(parent: tk.Toplevel, title: str, prompt: str, initial: str = "") -> str:
    """簡易テキスト入力ダイアログ"""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()
    try:
        x = parent.winfo_x() + parent.winfo_width() // 2 - 150
        y = parent.winfo_y() + parent.winfo_height() // 2 - 60
        dialog.geometry(f"300x120+{x}+{y}")
    except Exception:
        dialog.geometry("300x120")
    try:
        d = parent._app._design
        bg, fg, sep = d.panel, d.text, d.separator
    except Exception:
        bg, fg, sep = "#16213e", "#ffffff", "#44446a"
    dialog.configure(bg=bg)
    tk.Label(dialog, text=prompt, bg=bg, fg=fg, font=("Meiryo", 9)).pack(padx=12, pady=(12, 4))
    var = tk.StringVar(value=initial)
    entry = tk.Entry(dialog, textvariable=var, bg=sep, fg=fg,
                     insertbackground=fg, font=("Meiryo", 9), relief=tk.FLAT)
    entry.pack(padx=12, fill=tk.X)
    entry.select_range(0, tk.END)
    entry.focus_set()
    result = [None]

    def _ok(e=None):
        result[0] = var.get().strip()
        dialog.destroy()

    def _cancel(e=None):
        dialog.destroy()

    btn_row = tk.Frame(dialog, bg=bg)
    btn_row.pack(pady=8)
    tk.Button(btn_row, text="OK", command=_ok,
              bg=sep, fg=fg, font=("Meiryo", 9), relief=tk.FLAT, padx=12).pack(side=tk.LEFT, padx=4)
    tk.Button(btn_row, text="キャンセル", command=_cancel,
              bg=sep, fg=fg, font=("Meiryo", 9), relief=tk.FLAT, padx=12).pack(side=tk.LEFT, padx=4)
    dialog.bind("<Return>", _ok)
    dialog.bind("<Escape>", _cancel)
    dialog.wait_window()
    return result[0]


# ────────────────────────────────────────────────────────────────────
#  スクロール可能フレーム
# ────────────────────────────────────────────────────────────────────

class _ScrollFrame(tk.Frame):
    def __init__(self, parent, bg: str, **kw):
        super().__init__(parent, bg=bg, **kw)
        scr = tk.Scrollbar(self, orient=tk.VERTICAL, bg=bg)
        scr.pack(side=tk.RIGHT, fill=tk.Y)
        cv = tk.Canvas(self, bg=bg, highlightthickness=0, yscrollcommand=scr.set)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.config(command=cv.yview)
        self.inner = tk.Frame(cv, bg=bg)
        _win = cv.create_window((0, 0), window=self.inner, anchor="nw")

        def _on_configure(e):
            cv.configure(scrollregion=cv.bbox("all"))

        def _on_canvas_resize(e):
            cv.itemconfig(_win, width=e.width)

        def _on_mousewheel(e):
            cv.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self.inner.bind("<Configure>", _on_configure)
        cv.bind("<Configure>", _on_canvas_resize)
        cv.bind("<MouseWheel>", _on_mousewheel)
        self.inner.bind("<MouseWheel>", _on_mousewheel)


# ────────────────────────────────────────────────────────────────────
#  デザインエディタ本体
# ────────────────────────────────────────────────────────────────────

class DesignEditor(tk.Toplevel):
    """デザインエディタ — 独立 Toplevel ウィンドウ"""

    def __init__(self, app):
        super().__init__(app.root)
        self._app = app
        self._mgr: DesignPresetManager = app._design_preset_mgr

        self._current_design_name: str = app._design.preset_name
        self._editing_design: DesignSettings = None
        self._current_seg_name: str = app._design.segment.preset_name
        self._live_preview_var = tk.BooleanVar(value=True)

        self._setup_window()
        self._build_ui()
        self._load_design_preset(self._current_design_name)
        self._refresh_seg_grid()

    # ── ウィンドウ設定 ──────────────────────────────────────────────

    def _setup_window(self):
        d = self._app._design
        self.title("RRoulette — デザインエディタ")
        self.configure(bg=d.panel)
        self.resizable(True, True)
        self.minsize(600, 460)
        try:
            x = self._app.root.winfo_x() + self._app.root.winfo_width() + 10
            y = self._app.root.winfo_y()
            self.geometry(f"700x680+{x}+{y}")
        except Exception:
            self.geometry("700x680")
        # 本体が最前面設定ならエディタも前面属性を合わせる
        if getattr(self._app, '_topmost', False):
            self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self._app._design_editor = None
        self.destroy()

    # ── UI 構築 ─────────────────────────────────────────────────────

    def _build_ui(self):
        d = self._app._design

        # ── 下部固定バー（先に pack して常時表示を保証）──────────
        bot = tk.Frame(self, bg=d.panel, bd=0)
        bot.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 8))

        tk.Checkbutton(
            bot, text="即時反映",
            variable=self._live_preview_var,
            bg=d.panel, fg=d.text, selectcolor=d.separator,
            activebackground=d.panel, activeforeground=d.text,
            font=("Meiryo", 9),
        ).pack(side=tk.LEFT, padx=(6, 2))

        tk.Button(bot, text="今すぐ反映", command=self._apply_now,
                  bg=d.separator, fg=d.text, font=("Meiryo", 9),
                  relief=tk.FLAT, cursor="hand2", padx=6, pady=2,
                  ).pack(side=tk.LEFT, padx=3)

        tk.Button(bot, text="保存", command=self._do_save,
                  bg=d.separator, fg=d.text, font=("Meiryo", 9),
                  relief=tk.FLAT, cursor="hand2", padx=6, pady=2,
                  ).pack(side=tk.LEFT, padx=3)

        tk.Button(bot, text="閉じる", command=self._on_close,
                  bg=d.separator, fg=d.text, font=("Meiryo", 9),
                  relief=tk.FLAT, cursor="hand2", padx=8, pady=2,
                  ).pack(side=tk.RIGHT, padx=6)

        self._status_lbl = tk.Label(bot, text="", bg=d.panel, fg=d.text_sub,
                                    font=("Meiryo", 8))
        self._status_lbl.pack(side=tk.LEFT, padx=8)

        # ── 区切り線 ──────────────────────────────────────────────
        tk.Frame(self, bg=d.separator, height=1).pack(
            side=tk.BOTTOM, fill=tk.X, padx=0)

        # ── 最上部タブ（デザインプリセット / セグメント配色）──────
        self._main_nb = ttk.Notebook(self)
        self._main_nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        # タブ 1: デザインプリセット
        self._design_tab = tk.Frame(self._main_nb, bg=d.panel)
        self._main_nb.add(self._design_tab, text="  デザインプリセット  ")
        self._build_design_tab()

        # タブ 2: セグメント配色
        self._seg_tab = tk.Frame(self._main_nb, bg=d.panel)
        self._main_nb.add(self._seg_tab, text="  セグメント配色  ")
        self._build_seg_tab()

    # ── ツールバービルダー（両タブ共通パターン）────────────────────

    def _build_toolbar(self, parent, label: str, cb_var, cb_values,
                       cb_bind, buttons):
        """Combobox + ボタン群のツールバーを構築して Combobox を返す"""
        d = self._app._design
        _BTN = dict(font=("Meiryo", 9), relief=tk.FLAT, cursor="hand2", padx=4, pady=2)

        tb = tk.Frame(parent, bg=d.separator)
        tb.pack(fill=tk.X, padx=0, pady=(0, 4))

        tk.Label(tb, text=label, bg=d.separator, fg=d.text,
                 font=("Meiryo", 9)).pack(side=tk.LEFT, padx=(8, 2), pady=4)

        cb = ttk.Combobox(tb, textvariable=cb_var, values=cb_values,
                          state="readonly", font=("Meiryo", 9), width=12)
        cb.pack(side=tk.LEFT, padx=(0, 6), pady=4)
        cb.bind("<<ComboboxSelected>>", cb_bind)

        for text, cmd in buttons:
            tk.Button(tb, text=text, command=cmd,
                      bg=d.panel, fg=d.text, **_BTN).pack(side=tk.LEFT, padx=1, pady=4)

        return cb

    # ── デザインプリセットタブ ──────────────────────────────────────

    def _build_design_tab(self):
        d = self._app._design
        self._preset_var = tk.StringVar(value=self._current_design_name)
        self._preset_cb = self._build_toolbar(
            self._design_tab,
            label="プリセット:",
            cb_var=self._preset_var,
            cb_values=self._mgr.all_design_names(),
            cb_bind=self._on_preset_change,
            buttons=[
                ("新規", self._new_preset),
                ("複製", self._duplicate_preset),
                ("名前変更", self._rename_preset),
                ("削除", self._delete_preset),
                ("リセット", self._reset_preset),
                ("インポート", self._import_design),
                ("エクスポート", self._export_design),
            ],
        )

        # サブ Notebook（デザイン詳細タブ）
        self._sub_nb = ttk.Notebook(self._design_tab)
        self._sub_nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self._tab_global = _ScrollFrame(self._sub_nb, bg=d.panel)
        self._tab_wheel = _ScrollFrame(self._sub_nb, bg=d.panel)
        self._tab_pointer = _ScrollFrame(self._sub_nb, bg=d.panel)
        self._tab_log = _ScrollFrame(self._sub_nb, bg=d.panel)
        self._tab_fonts = _ScrollFrame(self._sub_nb, bg=d.panel)
        self._tab_result = _ScrollFrame(self._sub_nb, bg=d.panel)

        self._sub_nb.add(self._tab_global, text="全体色")
        self._sub_nb.add(self._tab_wheel, text="ホイール")
        self._sub_nb.add(self._tab_pointer, text="ポインター")
        self._sub_nb.add(self._tab_log, text="ログ")
        self._sub_nb.add(self._tab_fonts, text="フォント")
        self._sub_nb.add(self._tab_result, text="結果表示")

    # ── セグメント配色タブ ──────────────────────────────────────────

    def _build_seg_tab(self):
        d = self._app._design
        self._seg_var = tk.StringVar(value=self._current_seg_name)
        self._seg_cb = self._build_toolbar(
            self._seg_tab,
            label="配色:",
            cb_var=self._seg_var,
            cb_values=self._mgr.all_segment_names(),
            cb_bind=self._on_seg_preset_change,
            buttons=[
                ("新規", self._new_seg_preset),
                ("複製", self._duplicate_seg_preset),
                ("名前変更", self._rename_seg_preset),
                ("削除", self._delete_seg_preset),
                ("リセット", self._reset_seg_preset),
                ("インポート", self._import_seg),
                ("エクスポート", self._export_seg),
            ],
        )

        # 色追加・説明 行
        act = tk.Frame(self._seg_tab, bg=d.panel)
        act.pack(fill=tk.X, padx=4, pady=(0, 4))
        tk.Button(act, text="色を追加", command=self._add_seg_color,
                  bg=d.separator, fg=d.text, font=("Meiryo", 9),
                  relief=tk.FLAT, cursor="hand2", padx=6, pady=2,
                  ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(act, text="各スロット: クリックで色変更 / × で削除",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(side=tk.LEFT)

        self._seg_scroll = _ScrollFrame(self._seg_tab, bg=d.panel)
        self._seg_scroll.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

    def _refresh_seg_grid(self):
        """セグメント配色グリッドを現在の _current_seg_name で再描画（可変長対応）"""
        gf = self._seg_scroll.inner
        for w in gf.winfo_children():
            w.destroy()
        d = self._app._design
        colors = self._mgr.get_segment_colors(self._current_seg_name)
        cols = 5

        def _make_edit(idx, swatch, lbl):
            def _edit(e=None):
                cur_colors = list(self._mgr.get_segment_colors(self._current_seg_name))
                cur = cur_colors[idx] if idx < len(cur_colors) else "#ffffff"
                res = _colorchooser.askcolor(
                    color=cur if _is_valid_color(cur) else "#ffffff",
                    parent=self, title=f"スロット {idx + 1} の色を選択",
                )
                if res and res[1]:
                    new_col = res[1].lower()
                    cur_colors[idx] = new_col
                    self._mgr.save_segment(self._current_seg_name, cur_colors)
                    try:
                        swatch.configure(bg=new_col)
                    except Exception:
                        pass
                    lbl.config(text=new_col)
                    self._on_seg_value_changed()
            return _edit

        def _make_delete(idx):
            def _delete(e=None):
                self._del_seg_color_at(idx)
            return _delete

        for i, color in enumerate(colors):
            r, c = divmod(i, cols)
            cell = tk.Frame(gf, bg=d.panel)
            cell.grid(row=r, column=c, padx=5, pady=3, sticky="w")

            # 番号 + × 削除ボタン
            top_row = tk.Frame(cell, bg=d.panel)
            top_row.pack(fill=tk.X)
            tk.Label(top_row, text=f"{i + 1:2d}", bg=d.panel, fg=d.text_sub,
                     font=("Courier", 8)).pack(side=tk.LEFT)
            del_lbl = tk.Label(top_row, text="×", bg=d.panel, fg=d.text_sub,
                               font=("Meiryo", 7), cursor="hand2")
            del_lbl.pack(side=tk.RIGHT)
            del_lbl.bind("<Button-1>", _make_delete(i))

            sw = tk.Canvas(cell, width=44, height=28, highlightthickness=1,
                           highlightbackground=d.separator, cursor="hand2")
            try:
                sw.configure(bg=color)
            except Exception:
                sw.configure(bg="#888888")
            sw.pack()
            hex_lbl = tk.Label(cell, text=color, bg=d.panel, fg=d.text_sub,
                               font=("Courier", 7), width=8)
            hex_lbl.pack()
            sw.bind("<Button-1>", _make_edit(i, sw, hex_lbl))

    def _add_seg_color(self):
        """セグメント配色に新しい色スロットを追加する"""
        colors = list(self._mgr.get_segment_colors(self._current_seg_name))
        colors.append("#888888")
        self._mgr.save_segment(self._current_seg_name, colors)
        self._refresh_seg_grid()
        self._on_seg_value_changed()

    def _del_seg_color_at(self, idx: int):
        """指定インデックスの色スロットを削除する（最低1色を保持）"""
        colors = list(self._mgr.get_segment_colors(self._current_seg_name))
        if len(colors) <= 1:
            _msgbox.showwarning("削除不可", "最低 1 色は残す必要があります。", parent=self)
            return
        colors.pop(idx)
        self._mgr.save_segment(self._current_seg_name, colors)
        self._refresh_seg_grid()
        self._on_seg_value_changed()

    # ── デザイン詳細タブ リフレッシュ ──────────────────────────────

    def _refresh_design_tabs(self):
        self._refresh_tab_global()
        self._refresh_tab_wheel()
        self._refresh_tab_pointer()
        self._refresh_tab_log()
        self._refresh_tab_fonts()
        self._refresh_tab_result()

    def _make_color_row(self, parent: tk.Frame, label: str, getter, setter):
        d = self._app._design
        row = tk.Frame(parent, bg=d.panel)
        row.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(row, text=label, bg=d.panel, fg=d.text,
                 font=("Meiryo", 9), width=26, anchor="w").pack(side=tk.LEFT)
        swatch = tk.Canvas(row, width=22, height=16, highlightthickness=1,
                           highlightbackground=d.separator, cursor="hand2")
        swatch.pack(side=tk.LEFT, padx=(0, 4))
        hex_lbl = tk.Label(row, text=getter(), bg=d.panel, fg=d.text_sub,
                           font=("Courier", 9), width=9)
        hex_lbl.pack(side=tk.LEFT)

        def _update():
            c = getter()
            try:
                swatch.configure(bg=c)
            except Exception:
                swatch.configure(bg="#888888")

        _update()

        def _edit(e=None):
            cur = getter()
            res = _colorchooser.askcolor(
                color=cur if _is_valid_color(cur) else "#ffffff",
                parent=self, title=label,
            )
            if res and res[1]:
                col = res[1].lower()
                setter(col)
                hex_lbl.config(text=col)
                _update()
                self._on_design_value_changed()

        swatch.bind("<Button-1>", _edit)
        tk.Button(row, text="…", command=_edit,
                  bg=d.separator, fg=d.text, font=("Meiryo", 8),
                  relief=tk.FLAT, cursor="hand2", padx=3, pady=0,
                  ).pack(side=tk.LEFT, padx=2)

    def _make_int_row(self, parent: tk.Frame, label: str, getter, setter,
                      min_v: int = 0, max_v: int = 200):
        d = self._app._design
        row = tk.Frame(parent, bg=d.panel)
        row.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(row, text=label, bg=d.panel, fg=d.text,
                 font=("Meiryo", 9), width=26, anchor="w").pack(side=tk.LEFT)
        var = tk.IntVar(value=getter())

        def _on_change(*_):
            try:
                v = var.get()
                if min_v <= v <= max_v:
                    setter(v)
                    self._on_design_value_changed()
            except Exception:
                pass

        sb = tk.Spinbox(row, textvariable=var, from_=min_v, to=max_v, width=6,
                        font=("Meiryo", 9),
                        bg=d.separator, fg=d.text,
                        buttonbackground=d.separator, insertbackground=d.text,
                        relief=tk.FLAT, command=_on_change)
        sb.pack(side=tk.LEFT)
        sb.bind("<FocusOut>", _on_change)
        sb.bind("<Return>", _on_change)

    def _refresh_tab_global(self):
        p = self._tab_global.inner
        for w in p.winfo_children():
            w.destroy()
        d = self._app._design
        gc = self._editing_design.global_colors
        tk.Label(p, text="全体共通カラートークン",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 4))
        for label, attr in [
            ("背景 (bg)", "bg"),
            ("パネル (panel)", "panel"),
            ("アクセント (accent)", "accent"),
            ("テキスト (text)", "text"),
            ("サブテキスト (text_sub)", "text_sub"),
            ("ゴールド (gold)", "gold"),
            ("セパレーター (separator)", "separator"),
        ]:
            self._make_color_row(p, label,
                                 lambda a=attr: getattr(gc, a),
                                 lambda v, a=attr: setattr(gc, a, v))

    def _refresh_tab_wheel(self):
        p = self._tab_wheel.inner
        for w in p.winfo_children():
            w.destroy()
        d = self._app._design
        wd = self._editing_design.wheel
        tk.Label(p, text="ホイール描画設定",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 4))
        for label, attr in [
            ("文字色 (text_color)", "text_color"),
            ("外周線色 (outline_color)", "outline_color"),
            ("セグメント間線色 (segment_outline_color)", "segment_outline_color"),
            ("中央穴枠色 (hole_outline_color)", "hole_outline_color"),
        ]:
            self._make_color_row(p, label,
                                 lambda a=attr: getattr(wd, a),
                                 lambda v, a=attr: setattr(wd, a, v))
        for label, attr, lo, hi in [
            ("外周線幅 (outline_width)", "outline_width", 0, 20),
            ("セグメント間線幅 (segment_outline_width)", "segment_outline_width", 0, 20),
            ("中央穴枠幅 (hole_outline_width)", "hole_outline_width", 0, 20),
        ]:
            self._make_int_row(p, label,
                               lambda a=attr: getattr(wd, a),
                               lambda v, a=attr: setattr(wd, a, v), lo, hi)

    def _refresh_tab_pointer(self):
        p = self._tab_pointer.inner
        for w in p.winfo_children():
            w.destroy()
        d = self._app._design
        pd = self._editing_design.pointer
        tk.Label(p, text="ポインター描画設定",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 4))
        for label, attr in [
            ("塗り色 (fill_color)", "fill_color"),
            ("枠線色 (outline_color)", "outline_color"),
        ]:
            self._make_color_row(p, label,
                                 lambda a=attr: getattr(pd, a),
                                 lambda v, a=attr: setattr(pd, a, v))
        self._make_int_row(p, "枠線幅 (outline_width)",
                           lambda: pd.outline_width, lambda v: setattr(pd, "outline_width", v), 0, 20)

    def _refresh_tab_log(self):
        p = self._tab_log.inner
        for w in p.winfo_children():
            w.destroy()
        d = self._app._design
        ld = self._editing_design.log
        tk.Label(p, text="ログオーバーレイ設定",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 4))
        for label, attr in [
            ("テキスト色 (text_color)", "text_color"),
            ("シャドウ色 (shadow_color)", "shadow_color"),
            ("ボックス枠色 (box_outline_color)", "box_outline_color"),
            ("ボックス背景色 (box_bg_color)", "box_bg_color"),
        ]:
            self._make_color_row(p, label,
                                 lambda a=attr: getattr(ld, a),
                                 lambda v, a=attr: setattr(ld, a, v))
        self._make_int_row(p, "フォントサイズ (font_size)",
                           lambda: ld.font_size, lambda v: setattr(ld, "font_size", v), 6, 72)

    def _refresh_tab_fonts(self):
        p = self._tab_fonts.inner
        for w in p.winfo_children():
            w.destroy()
        d = self._app._design
        fnt = self._editing_design.fonts
        wf = fnt.wheel
        tk.Label(p, text="フォント設定",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 4))
        _all_fonts = sorted(set(f for f in _tkfont.families(root=self._app.root) if f))

        def _make_font_row(label: str, getter, setter):
            row = tk.Frame(p, bg=d.panel)
            row.pack(fill=tk.X, padx=12, pady=3)
            tk.Label(row, text=label, bg=d.panel, fg=d.text,
                     font=("Meiryo", 9), width=26, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=getter())
            cb = ttk.Combobox(row, textvariable=var, values=_all_fonts,
                              state="readonly", font=("Meiryo", 9), width=20)
            cb.pack(side=tk.LEFT)

            def _on_sel(e=None):
                v = var.get().strip()
                if v:
                    setter(v)
                    self._on_design_value_changed()

            cb.bind("<<ComboboxSelected>>", _on_sel)

        _make_font_row("ホイール文字", lambda: wf.family, lambda v: setattr(wf, "family", v))
        _make_font_row("UI フォント", lambda: fnt.ui_family, lambda v: setattr(fnt, "ui_family", v))
        _make_font_row("ログフォント", lambda: fnt.log_family, lambda v: setattr(fnt, "log_family", v))
        _make_font_row("結果フォント（result_family）", lambda: fnt.result_family, lambda v: setattr(fnt, "result_family", v))

        tk.Label(p, text="── ホイールフォントサイズ ──",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 2))
        for label, attr, lo, hi in [
            ("省略基準サイズ (omit_base_size)", "omit_base_size", 1, 200),
            ("収める基準サイズ (fit_base_size)", "fit_base_size", 1, 200),
            ("縮小基準サイズ (shrink_base_size)", "shrink_base_size", 1, 200),
            ("最小サイズ (min_size)", "min_size", 1, 200),
            ("最大サイズ (max_size)", "max_size", 1, 200),
        ]:
            self._make_int_row(p, label,
                               lambda a=attr: getattr(wf, a),
                               lambda v, a=attr: setattr(wf, a, v), lo, hi)

    def _refresh_tab_result(self):
        p = self._tab_result.inner
        for w in p.winfo_children():
            w.destroy()
        d = self._app._design
        rd = self._editing_design.result
        fnt = self._editing_design.fonts
        _all_fonts = sorted(set(f for f in _tkfont.families(root=self._app.root) if f))

        tk.Label(p, text="結果表示オーバーレイ設定",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 4))

        # 色設定
        for label, attr in [
            ("背景色 (bg_color)", "bg_color"),
            ("枠線色 (outline_color)", "outline_color"),
            ("文字色 (text_color)", "text_color"),
        ]:
            self._make_color_row(p, label,
                                 lambda a=attr: getattr(rd, a),
                                 lambda v, a=attr: setattr(rd, a, v))

        # 数値設定
        for label, attr, lo, hi in [
            ("枠線幅 (outline_width)", "outline_width", 0, 20),
            ("角丸量 (corner_radius)", "corner_radius", 0, 50),
            ("内側余白 (padding)", "padding", 0, 40),
        ]:
            self._make_int_row(p, label,
                               lambda a=attr: getattr(rd, a),
                               lambda v, a=attr: setattr(rd, a, v), lo, hi)

        # フォント設定
        tk.Label(p, text="── フォント設定 ──",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 2))

        _font_row = tk.Frame(p, bg=d.panel)
        _font_row.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(_font_row, text="フォントファミリー", bg=d.panel, fg=d.text,
                 font=("Meiryo", 9), width=26, anchor="w").pack(side=tk.LEFT)
        _font_var = tk.StringVar(value=fnt.result_family)
        _font_cb = ttk.Combobox(_font_row, textvariable=_font_var, values=_all_fonts,
                                state="readonly", font=("Meiryo", 9), width=20)
        _font_cb.pack(side=tk.LEFT)

        def _on_font_sel(e=None):
            v = _font_var.get().strip()
            if v:
                fnt.result_family = v
                self._on_design_value_changed()

        _font_cb.bind("<<ComboboxSelected>>", _on_font_sel)

        # 文字表示方式
        tk.Label(p, text="── 文字表示方式 ──",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 ).pack(anchor="w", padx=12, pady=(8, 2))

        _FIT_NAMES = ["省略（…で省略）", "収める（縮小して全文表示）"]
        _fit_row = tk.Frame(p, bg=d.panel)
        _fit_row.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(_fit_row, text="文字表示方式", bg=d.panel, fg=d.text,
                 font=("Meiryo", 9), width=26, anchor="w").pack(side=tk.LEFT)
        _fit_cb = ttk.Combobox(_fit_row, values=_FIT_NAMES, state="readonly",
                               font=("Meiryo", 9), width=20)
        _fit_cb.current(getattr(rd, "text_fit_mode", 0))
        _fit_cb.pack(side=tk.LEFT)

        def _on_fit(e=None):
            rd.text_fit_mode = _fit_cb.current()
            self._on_design_value_changed()

        _fit_cb.bind("<<ComboboxSelected>>", _on_fit)

        # 定常表示の配色モード
        _STEADY_NAMES = ["デザイン色を使う", "当選セグメント色を維持する"]
        _steady_row = tk.Frame(p, bg=d.panel)
        _steady_row.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(_steady_row, text="定常表示の配色モード", bg=d.panel, fg=d.text,
                 font=("Meiryo", 9), width=26, anchor="w").pack(side=tk.LEFT)
        _steady_cb = ttk.Combobox(_steady_row, values=_STEADY_NAMES, state="readonly",
                                  font=("Meiryo", 9), width=20)
        _steady_cb.current(getattr(rd, "steady_color_mode", 0))
        _steady_cb.pack(side=tk.LEFT)

        def _on_steady(e=None):
            rd.steady_color_mode = _steady_cb.current()
            self._on_design_value_changed()

        _steady_cb.bind("<<ComboboxSelected>>", _on_steady)

        tk.Label(p,
                 text="※ フォントサイズはホイールサイズに連動して自動計算されます\n"
                      "（フォントファミリーは「フォント」タブでも変更できます）",
                 bg=d.panel, fg=d.text_sub, font=("Meiryo", 8),
                 justify=tk.LEFT,
                 ).pack(anchor="w", padx=12, pady=(4, 8))

    # ── プリセット読み込み / 反映 ───────────────────────────────────

    def _load_design_preset(self, name: str):
        self._current_design_name = name
        self._preset_var.set(name)
        ds = self._mgr.get_design(name)
        self._editing_design = ds
        self._apply_design_to_app(ds)
        self._refresh_design_tabs()
        self._update_status()

    def _apply_design_to_app(self, ds: DesignSettings):
        """editing_design を app._design に反映して全 UI を更新する（即時反映ON時 or 今すぐ反映）。
        _redraw() はホイールキャンバスのみ更新するため、背景・パネル色などの反映漏れを防ぐため
        _apply_design_to_all() を使用する。設定パネルのグループ開閉状態は _cfg_group_states で保護済み。"""
        app = self._app
        d = app._design
        d.preset_name = self._current_design_name
        d.global_colors = ds.global_colors
        d.wheel = ds.wheel
        d.pointer = ds.pointer
        d.log = ds.log
        d.fonts = ds.fonts
        d.result = ds.result
        app._apply_design_to_all()

    def _apply_now(self):
        """今すぐ反映 — 即時反映 ON/OFF を問わず強制反映"""
        if self._editing_design is not None:
            self._apply_design_to_app(self._editing_design)
        self._mgr.apply_segment_to_design(self._current_seg_name, self._app._design)
        self._app._redraw()
        self._app._save_config()

    def _do_save(self):
        """保存ボタン — 現在の編集内容を config へ書き出す"""
        if self._editing_design is not None:
            self._mgr.save_design(self._current_design_name, self._editing_design)
        self._app._save_config()
        self._update_status()

    # ── 値変更コールバック ───────────────────────────────────────────

    def _on_design_value_changed(self):
        """設計値変更時: 即時反映ONなら本体へ反映。OFFはエディタ内に保持。"""
        self._mgr.save_design(self._current_design_name, self._editing_design)
        if self._live_preview_var.get():
            self._apply_design_to_app(self._editing_design)
        self._app._save_config()
        self._update_status()

    def _on_seg_value_changed(self):
        """配色値変更時: 即時反映ONなら本体へ反映。OFFはエディタ内に保持。"""
        if self._live_preview_var.get():
            self._mgr.apply_segment_to_design(self._current_seg_name, self._app._design)
            self._app._redraw()
        self._app._save_config()
        self._sync_cfg_panel_combos()

    # ── ステータス更新 ───────────────────────────────────────────────

    def _update_status(self):
        name = self._current_design_name
        is_builtin = self._mgr.is_builtin_design(name)
        kind = "組み込み" if is_builtin else "ユーザー作成"
        edited = "（編集済み）" if (is_builtin and name in self._mgr._user_design) else ""
        live = "即時ON" if self._live_preview_var.get() else "即時OFF"
        try:
            self._status_lbl.config(text=f"{name} [{kind}{edited}] {live}")
        except Exception:
            pass

    # ── 設定パネル Combobox 同期 ─────────────────────────────────────

    def _sync_cfg_panel_combos(self):
        app = self._app
        if hasattr(app, '_cfg_design_preset_var'):
            try:
                app._cfg_design_preset_var.set(app._design.preset_name)
            except Exception:
                pass
        if hasattr(app, '_cfg_design_cb'):
            try:
                app._cfg_design_cb.config(values=self._mgr.all_design_names())
            except Exception:
                pass
        if hasattr(app, '_cfg_seg_preset_var'):
            try:
                app._cfg_seg_preset_var.set(app._design.segment.preset_name)
            except Exception:
                pass
        if hasattr(app, '_cfg_seg_cb'):
            try:
                app._cfg_seg_cb.config(values=self._mgr.all_segment_names())
            except Exception:
                pass

    # ── デザインプリセット操作 ───────────────────────────────────────

    def _on_preset_change(self, e=None):
        if self._editing_design is not None:
            self._mgr.save_design(self._current_design_name, self._editing_design)
        name = self._preset_var.get()
        self._load_design_preset(name)
        self._sync_cfg_panel_combos()

    def _new_preset(self):
        name = _ask_name(self, "新規デザインプリセット", "プリセット名を入力してください:", "新しいプリセット")
        if not name:
            return
        if name in self._mgr.all_design_names():
            _msgbox.showwarning("重複", f"「{name}」は既に存在します。", parent=self)
            return
        if self._editing_design is not None:
            self._mgr.save_design(self._current_design_name, self._editing_design)
        self._mgr.create_design(name, "デフォルト")
        self._preset_cb.config(values=self._mgr.all_design_names())
        self._load_design_preset(name)
        self._sync_cfg_panel_combos()

    def _duplicate_preset(self):
        src = self._current_design_name
        name = _ask_name(self, "プリセットを複製", "新しいプリセット名を入力してください:", f"{src} のコピー")
        if not name:
            return
        if name in self._mgr.all_design_names():
            _msgbox.showwarning("重複", f"「{name}」は既に存在します。", parent=self)
            return
        if self._editing_design is not None:
            self._mgr.save_design(src, self._editing_design)
        self._mgr.duplicate_design(src, name)
        self._preset_cb.config(values=self._mgr.all_design_names())
        self._load_design_preset(name)
        self._sync_cfg_panel_combos()

    def _rename_preset(self):
        name = self._current_design_name
        if self._mgr.is_builtin_design(name):
            _msgbox.showinfo("変更不可", "組み込みプリセットの名前変更はできません。", parent=self)
            return
        new_name = _ask_name(self, "名前変更", "新しい名前を入力してください:", name)
        if not new_name or new_name == name:
            return
        if new_name in self._mgr.all_design_names():
            _msgbox.showwarning("重複", f"「{new_name}」は既に存在します。", parent=self)
            return
        self._mgr.rename_design(name, new_name)
        if self._app._design.preset_name == name:
            self._app._design.preset_name = new_name
        self._current_design_name = new_name
        self._preset_cb.config(values=self._mgr.all_design_names())
        self._preset_var.set(new_name)
        self._update_status()
        self._sync_cfg_panel_combos()
        self._app._save_config()

    def _delete_preset(self):
        name = self._current_design_name
        if self._mgr.is_builtin_design(name):
            _msgbox.showinfo("削除不可", "組み込みプリセットは削除できません。", parent=self)
            return
        if not _msgbox.askyesno("確認", f"「{name}」を削除しますか？", parent=self):
            return
        self._mgr.delete_design(name)
        names = self._mgr.all_design_names()
        self._preset_cb.config(values=names)
        self._load_design_preset(names[0] if names else "デフォルト")
        self._sync_cfg_panel_combos()
        self._app._save_config()

    def _reset_preset(self):
        name = self._current_design_name
        msg = (f"「{name}」をリセットしますか？\n"
               "組み込みプリセットはコード基準値に戻ります。\n"
               "ユーザー作成プリセットはデフォルト基準に戻ります。")
        if not _msgbox.askyesno("確認", msg, parent=self):
            return
        if self._mgr.is_builtin_design(name):
            ds = self._mgr.reset_design(name)
        else:
            ds = self._mgr.get_design("デフォルト")
            ds.preset_name = name
            self._mgr.save_design(name, ds)
        self._editing_design = ds
        self._apply_design_to_app(ds)
        self._refresh_design_tabs()
        self._app._save_config()
        self._update_status()

    def _import_design(self):
        path = _filedialog.askopenfilename(
            parent=self, title="デザインプリセットをインポート",
            filetypes=[("JSON ファイル", "*.json"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            _msgbox.showerror("エラー", f"読み込みに失敗しました:\n{e}", parent=self)
            return
        if "global_colors" in data or "preset_name" in data:
            ds = DesignSettings.from_dict(data)
            name = ds.preset_name or "インポートプリセット"
            if name in self._mgr.all_design_names():
                if not _msgbox.askyesno("上書き確認",
                                        f"「{name}」は既に存在します。上書きしますか？", parent=self):
                    return
            self._mgr.save_design(name, ds)
            self._preset_cb.config(values=self._mgr.all_design_names())
            self._load_design_preset(name)
            self._sync_cfg_panel_combos()
        else:
            _msgbox.showerror("エラー", "デザインプリセットデータが見つかりません。", parent=self)
            return
        self._app._save_config()

    def _export_design(self):
        name = self._current_design_name
        if self._editing_design is not None:
            self._mgr.save_design(name, self._editing_design)
        ds = self._mgr.get_design(name)
        data = ds.to_dict()
        try:
            os.makedirs(EXPORT_DIR, exist_ok=True)
        except Exception:
            pass
        safe = name.replace("/", "_").replace("\\", "_").replace(":", "_")
        path = _filedialog.asksaveasfilename(
            parent=self, title="デザインプリセットをエクスポート",
            initialfile=os.path.join(EXPORT_DIR, f"design_{safe}.json"),
            defaultextension=".json",
            filetypes=[("JSON ファイル", "*.json"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _msgbox.showinfo("完了", f"エクスポート完了:\n{path}", parent=self)
        except Exception as e:
            _msgbox.showerror("エラー", f"保存に失敗しました:\n{e}", parent=self)

    # ── セグメント配色プリセット操作 ─────────────────────────────────

    def _on_seg_preset_change(self, e=None):
        name = self._seg_var.get()
        self._current_seg_name = name
        self._mgr.apply_segment_to_design(name, self._app._design)
        self._refresh_seg_grid()
        if self._live_preview_var.get():
            self._app._redraw()
        self._app._save_config()
        self._sync_cfg_panel_combos()

    def _new_seg_preset(self):
        name = _ask_name(self, "新規配色プリセット", "プリセット名を入力してください:", "新しい配色")
        if not name:
            return
        if name in self._mgr.all_segment_names():
            _msgbox.showwarning("重複", f"「{name}」は既に存在します。", parent=self)
            return
        self._mgr.create_segment(name, "デフォルト")
        self._current_seg_name = name
        self._seg_cb.config(values=self._mgr.all_segment_names())
        self._seg_var.set(name)
        self._mgr.apply_segment_to_design(name, self._app._design)
        self._refresh_seg_grid()
        if self._live_preview_var.get():
            self._app._redraw()
        self._app._save_config()
        self._sync_cfg_panel_combos()

    def _duplicate_seg_preset(self):
        src = self._current_seg_name
        name = _ask_name(self, "配色プリセットを複製", "新しいプリセット名を入力してください:", f"{src} のコピー")
        if not name:
            return
        if name in self._mgr.all_segment_names():
            _msgbox.showwarning("重複", f"「{name}」は既に存在します。", parent=self)
            return
        self._mgr.duplicate_segment(src, name)
        self._current_seg_name = name
        self._seg_cb.config(values=self._mgr.all_segment_names())
        self._seg_var.set(name)
        self._mgr.apply_segment_to_design(name, self._app._design)
        self._refresh_seg_grid()
        if self._live_preview_var.get():
            self._app._redraw()
        self._app._save_config()
        self._sync_cfg_panel_combos()

    def _rename_seg_preset(self):
        name = self._current_seg_name
        if self._mgr.is_builtin_segment(name):
            _msgbox.showinfo("変更不可", "組み込みセグメント配色の名前変更はできません。", parent=self)
            return
        new_name = _ask_name(self, "名前変更", "新しい名前を入力してください:", name)
        if not new_name or new_name == name:
            return
        if new_name in self._mgr.all_segment_names():
            _msgbox.showwarning("重複", f"「{new_name}」は既に存在します。", parent=self)
            return
        self._mgr.rename_segment(name, new_name)
        if self._app._design.segment.preset_name == name:
            self._app._design.segment.preset_name = new_name
        self._current_seg_name = new_name
        self._seg_cb.config(values=self._mgr.all_segment_names())
        self._seg_var.set(new_name)
        self._sync_cfg_panel_combos()
        self._app._save_config()

    def _delete_seg_preset(self):
        name = self._current_seg_name
        if self._mgr.is_builtin_segment(name):
            _msgbox.showinfo("削除不可", "組み込みセグメント配色は削除できません。", parent=self)
            return
        if not _msgbox.askyesno("確認", f"「{name}」を削除しますか？", parent=self):
            return
        self._mgr.delete_segment(name)
        all_names = self._mgr.all_segment_names()
        fallback = all_names[0] if all_names else "デフォルト"
        self._current_seg_name = fallback
        self._seg_cb.config(values=all_names)
        self._seg_var.set(fallback)
        self._mgr.apply_segment_to_design(fallback, self._app._design)
        self._refresh_seg_grid()
        if self._live_preview_var.get():
            self._app._redraw()
        self._app._save_config()
        self._sync_cfg_panel_combos()

    def _reset_seg_preset(self):
        name = self._current_seg_name
        if not _msgbox.askyesno("確認", f"「{name}」をリセットしますか？", parent=self):
            return
        self._mgr.reset_segment(name)
        self._mgr.apply_segment_to_design(name, self._app._design)
        self._refresh_seg_grid()
        if self._live_preview_var.get():
            self._app._redraw()
        self._app._save_config()

    def _import_seg(self):
        path = _filedialog.askopenfilename(
            parent=self, title="セグメント配色をインポート",
            filetypes=[("JSON ファイル", "*.json"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            _msgbox.showerror("エラー", f"読み込みに失敗しました:\n{e}", parent=self)
            return
        if "segment_colors" not in data:
            _msgbox.showerror("エラー", "segment_colors キーが見つかりません。", parent=self)
            return
        colors = data["segment_colors"]
        if not isinstance(colors, list) or not colors:
            _msgbox.showerror("エラー", "segment_colors の形式が不正です。", parent=self)
            return
        name = data.get("name", "インポート配色")
        if name in self._mgr.all_segment_names():
            if not _msgbox.askyesno("上書き確認",
                                    f"「{name}」は既に存在します。上書きしますか？", parent=self):
                return
        self._mgr.save_segment(name, colors)
        self._current_seg_name = name
        self._seg_cb.config(values=self._mgr.all_segment_names())
        self._seg_var.set(name)
        self._mgr.apply_segment_to_design(name, self._app._design)
        self._refresh_seg_grid()
        if self._live_preview_var.get():
            self._app._redraw()
        self._app._save_config()
        self._sync_cfg_panel_combos()

    def _export_seg(self):
        name = self._current_seg_name
        colors = self._mgr.get_segment_colors(name)
        data = {"name": name, "segment_colors": colors}
        try:
            os.makedirs(EXPORT_DIR, exist_ok=True)
        except Exception:
            pass
        safe = name.replace("/", "_").replace("\\", "_").replace(":", "_")
        path = _filedialog.asksaveasfilename(
            parent=self, title="セグメント配色をエクスポート",
            initialfile=os.path.join(EXPORT_DIR, f"segment_{safe}.json"),
            defaultextension=".json",
            filetypes=[("JSON ファイル", "*.json"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _msgbox.showinfo("完了", f"エクスポート完了:\n{path}", parent=self)
        except Exception as e:
            _msgbox.showerror("エラー", f"保存に失敗しました:\n{e}", parent=self)
