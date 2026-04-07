"""
RRoulette — 設定パネル Mixin
  - _build_cfg_panel: 右側設定パネルの構築（スクロール可能・グループ折りたたみ対応）
  - _apply_right_panel_layout: 右側パネル配置順の制御
  - _toggle_cfg_panel: 設定パネル表示/非表示切替
  - _reset_cfg_settings: 設定をデフォルト値にリセット
  - _import_cfg_settings: 設定をJSONからインポート（設定項目のみ）
  - _export_cfg_settings: 設定をJSONにエクスポート（設定項目のみ）
  - _save_cfg_settings_now: 設定を即時保存
"""

import json
import os
import sys
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as _filedialog
import tkinter.font as _tkfont
import tkinter.messagebox as _msgbox

from config_utils import EXPORT_DIR
from constants import (
    CFG_PANEL_W, MIN_W, POINTER_PRESET_NAMES, VERSION,
)
from sound_manager import TICK_PATTERN_NAMES, WIN_PATTERN_NAMES
from tooltip_utils import _SimpleTooltip
from design_settings import DesignSettings, DESIGN_PRESET_NAMES, SEGMENT_PRESET_NAMES, DESIGN_PRESETS


# ─── 設定項目キー・デフォルト値 ─────────────────────────────────────────
_SETTINGS_KEYS = [
    "spin_duration", "double_duration", "triple_duration",
    "tick_volume", "win_volume", "tick_pattern", "win_pattern",
    "tick_custom_file", "win_custom_file",
    "text_direction", "text_size_mode", "donut_hole",
    "pointer_preset", "pointer_angle",
    "log_timestamp", "log_overlay_show", "log_box_border", "log_on_top",
    "auto_shuffle", "arrangement_direction", "spin_direction",
    "confirm_reset",
    "float_win_show_instance",
    "result_close_mode", "result_hold_sec",
    "replay_max_count", "replay_show_indicator",
]

_SETTINGS_DEFAULTS = {
    "spin_duration": 9,
    "double_duration": 3,
    "triple_duration": 0,
    "tick_volume": 100,
    "win_volume": 100,
    "tick_pattern": 0,
    "win_pattern": 0,
    "tick_custom_file": "",
    "win_custom_file": "",
    "text_direction": 0,
    "text_size_mode": 1,
    "donut_hole": True,
    "pointer_preset": 1,
    "pointer_angle": 90.0,
    "log_timestamp": False,
    "log_overlay_show": True,
    "log_box_border": False,
    "log_on_top": False,
    "auto_shuffle": False,
    "arrangement_direction": 0,
    "spin_direction": 0,
    "confirm_reset": True,
    "float_win_show_instance": True,
    "result_close_mode": 2,   # 0=クリック, 1=自動, 2=両方
    "result_hold_sec":   5.0,
    "replay_max_count":      5,
    "replay_show_indicator": True,
}


class CfgPanelMixin:

    # ════════════════════════════════════════════════════════════════
    #  右側パネル配置（設定 → 項目リスト → メイン の順を維持）
    # ════════════════════════════════════════════════════════════════
    def _apply_right_panel_layout(self):
        """可視状態に応じて右側パネルを正しい順序で再配置する。"""
        self._clamp_sidebar_w()
        # 埋め込みウィジェットのみ pack_forget（浮動は Toplevel 内なので触らない）
        if not self._cfg_panel_float:
            for w in (self.cfg_panel, self._cfg_sash_right):
                if w is not None:
                    try:
                        w.pack_forget()
                    except Exception:
                        pass
        if not self._item_list_float:
            for w in (self.sidebar, self._sash):
                if w is not None:
                    try:
                        w.pack_forget()
                    except Exception:
                        pass
        if not self._cfg_panel_float and self._cfg_panel_visible:
            self.cfg_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)
            self._cfg_sash_right.pack(side=tk.RIGHT, fill=tk.Y, pady=8)
        if not self._item_list_float and self._settings_visible:
            self.sidebar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)
            self._sash.pack(side=tk.RIGHT, fill=tk.Y, pady=8)

    # ════════════════════════════════════════════════════════════════
    #  右設定パネル 構築
    # ════════════════════════════════════════════════════════════════
    def _build_cfg_panel(self):
        if self._cfg_panel_float:
            self._cfg_panel_toplevel = self._open_float_win(
                "設定", self._cfg_panel_float_geo
            )
            self._cfg_panel_toplevel.protocol(
                "WM_DELETE_WINDOW", self._toggle_cfg_panel_float
            )
            self._cfg_panel_toplevel.minsize(CFG_PANEL_W, 400)
            self.cfg_panel = tk.Frame(self._cfg_panel_toplevel, bg=self._design.panel)
            self.cfg_panel.pack(fill=tk.BOTH, expand=True)
            self.cfg_panel.pack_propagate(False)
            self._cfg_sash_right = None
            # 非表示処理は widget 構築完了後に行う（destroy はウィジェット生成後でないとエラーになるため）
        else:
            self._cfg_panel_toplevel = None
            self.cfg_panel = tk.Frame(self.content, bg=self._design.panel, width=self._cfg_panel_w)
            self.cfg_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)
            self.cfg_panel.pack_propagate(False)

            self._cfg_sash_right = tk.Frame(self.content, bg=self._design.separator, width=4)
            self._cfg_sash_right.pack(side=tk.RIGHT, fill=tk.Y, pady=8)
            self._cfg_sash_right.pack_propagate(False)

        # ── スクロール可能コンテナ ───────────────────────────
        _scr = tk.Scrollbar(self.cfg_panel, orient=tk.VERTICAL, bg=self._design.panel)
        _scr.pack(side=tk.RIGHT, fill=tk.Y)
        _scv = tk.Canvas(self.cfg_panel, bg=self._design.panel, highlightthickness=0,
                         yscrollcommand=_scr.set)
        _scv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _scr.config(command=_scv.yview)

        p = tk.Frame(_scv, bg=self._design.panel)
        _win = _scv.create_window((0, 0), window=p, anchor="nw")

        def _update_scroll(e=None):
            _scv.configure(scrollregion=_scv.bbox("all"))
        def _fit_width(e):
            _scv.itemconfig(_win, width=e.width)
        p.bind("<Configure>", _update_scroll)
        _scv.bind("<Configure>", _fit_width)

        def _on_wheel(e):
            _scv.yview_scroll(int(-1 * (e.delta / 120)), "units")
        _scv.bind("<MouseWheel>", _on_wheel)
        p.bind("<MouseWheel>", _on_wheel)

        def _bind_wheel(widget):
            widget.bind("<MouseWheel>", _on_wheel)
            for child in widget.winfo_children():
                _bind_wheel(child)
        self.root.after(100, lambda: _bind_wheel(p))

        _scv.bind("<ButtonPress-1>", self._drag_start, add="+")
        _scv.bind("<B1-Motion>",     self._drag_move,  add="+")

        def _bind_drag(widget):
            _SKIP = (tk.Entry, tk.Scale, tk.Checkbutton, tk.Button, tk.Spinbox,
                     ttk.Entry, ttk.Combobox, ttk.Scale, ttk.Checkbutton, ttk.Button, ttk.Spinbox,
                     tk.Scrollbar, ttk.Scrollbar)
            if not isinstance(widget, _SKIP):
                widget.bind("<ButtonPress-1>", self._drag_start, add="+")
                widget.bind("<B1-Motion>",     self._drag_move,  add="+")
            for child in widget.winfo_children():
                _bind_drag(child)
        self.root.after(200, lambda: _bind_drag(p))

        # ── 設定パネル幅リサイズグリップ（右下角）─────────────────
        # 独立ウィンドウ時は埋め込み用グリップ不要（OS標準リサイズを使用）
        if not self._cfg_panel_float:
            _cg = tk.Canvas(self.cfg_panel, width=16, height=16,
                            bg=self._design.panel, highlightthickness=0, cursor="sb_h_double_arrow")
            for _i in range(3):
                _x = 4 + _i * 4
                _cg.create_line(_x, 3, _x, 13, fill="#555577", width=1)
            _cg.bind("<ButtonPress-1>",   self._cfg_resize_start)
            _cg.bind("<B1-Motion>",       self._cfg_resize_move)
            _cg.bind("<ButtonRelease-1>", self._cfg_resize_end)
            _cg.place(relx=1.0, rely=1.0, anchor="se")

        # ── グループ開閉状態の永続化辞書（再構築をまたいで保持）────
        if not hasattr(self, '_cfg_group_states'):
            self._cfg_group_states = {}

        # ── 折りたたみグループヘルパー ────────────────────────
        def make_group(parent, title, expanded=False):
            """折りたたみ可能なグループを作成する。
            再構築時は _cfg_group_states に保存された開閉状態を優先する。
            Returns: content_frame（ウィジェットを追加するフレーム）
            """
            # 保存済み状態があればそれを使う（初回はデフォルト値を使用）
            is_expanded = self._cfg_group_states.get(title, expanded)

            container = tk.Frame(parent, bg=self._design.panel)
            container.pack(fill=tk.X, pady=(2, 0))

            header = tk.Frame(container, bg=self._design.separator, cursor="hand2")
            header.pack(fill=tk.X)

            arrow_var = tk.StringVar(value="▼" if is_expanded else "▶")
            arrow_lbl = tk.Label(
                header, textvariable=arrow_var,
                bg=self._design.separator, fg=self._design.gold,
                font=("Meiryo", 9, "bold"),
                padx=6, pady=4,
            )
            arrow_lbl.pack(side=tk.LEFT)

            title_lbl = tk.Label(
                header, text=title,
                bg=self._design.separator, fg=self._design.text,
                font=("Meiryo", 10, "bold"),
                pady=4,
            )
            title_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            content = tk.Frame(container, bg=self._design.panel)
            if is_expanded:
                content.pack(fill=tk.X)

            def toggle(e=None):
                if content.winfo_ismapped():
                    content.pack_forget()
                    arrow_var.set("▶")
                    self._cfg_group_states[title] = False
                else:
                    content.pack(fill=tk.X)
                    arrow_var.set("▼")
                    self._cfg_group_states[title] = True
                _update_scroll()

            header.bind("<Button-1>", toggle)
            arrow_lbl.bind("<Button-1>", toggle)
            title_lbl.bind("<Button-1>", toggle)

            return content

        # ── タイトル行（リセット・インポート・エクスポート・保存ボタン） ─────
        title_row = tk.Frame(p, bg=self._design.panel)
        title_row.pack(fill=tk.X, padx=8, pady=(10, 4))

        tk.Label(title_row, text="設定", bg=self._design.panel, fg=self._design.gold,
                 font=("Meiryo", 11, "bold")).pack(side=tk.LEFT, padx=(4, 0))

        _BTN = dict(
            bg=self._design.separator, fg=self._design.text,
            font=("Meiryo", 10),
            relief=tk.FLAT, cursor="hand2",
            padx=5, pady=1, bd=0,
        )

        btn_save = tk.Button(title_row, text="✔", command=self._save_cfg_settings_now, **_BTN)
        btn_save.pack(side=tk.RIGHT, padx=(2, 0))
        _SimpleTooltip(btn_save, "設定を今すぐ保存", self.root)

        btn_exp = tk.Button(title_row, text="↑", command=self._export_cfg_settings, **_BTN)
        btn_exp.pack(side=tk.RIGHT, padx=(2, 0))
        _SimpleTooltip(btn_exp, "設定をエクスポート", self.root)

        btn_imp = tk.Button(title_row, text="↓", command=self._import_cfg_settings, **_BTN)
        btn_imp.pack(side=tk.RIGHT, padx=(2, 0))
        _SimpleTooltip(btn_imp, "設定をインポート", self.root)

        btn_rst = tk.Button(title_row, text="↺", command=self._reset_cfg_settings, **_BTN)
        btn_rst.pack(side=tk.RIGHT, padx=(2, 0))
        _SimpleTooltip(btn_rst, "設定をリセット", self.root)

        # 独立表示 / メインに戻す
        _cfg_float_lbl = "メインに戻す" if self._cfg_panel_float else "独立表示"
        _cfg_float_tip = "設定パネルをメインに組み込む" if self._cfg_panel_float else "設定パネルを独立ウィンドウにする"
        btn_float = tk.Button(title_row, text=_cfg_float_lbl,
                              command=self._toggle_cfg_panel_float, **_BTN)
        btn_float.pack(side=tk.RIGHT, padx=(2, 4))
        _SimpleTooltip(btn_float, _cfg_float_tip, self.root)

        # ════════════════════════════════════════════════
        #  ウィンドウ表示グループ
        # ════════════════════════════════════════════════
        g_winvis = make_group(p, "ウィンドウ表示")

        # 最前面
        self._cfg_topmost_var = tk.BooleanVar(value=self._topmost)

        def on_topmost():
            if self._cfg_topmost_var.get() != self._topmost:
                self._toggle_topmost()

        tk.Checkbutton(
            g_winvis, text="最前面",
            variable=self._cfg_topmost_var, command=on_topmost,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            activebackground=self._design.panel, activeforeground=self._design.text,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=12, pady=(6, 2))

        # 背景透過
        self._cfg_transparent_var = tk.BooleanVar(value=self._transparent)

        def on_transparent():
            if self._cfg_transparent_var.get() != self._transparent:
                self._toggle_transparent()

        tk.Checkbutton(
            g_winvis, text="背景透過",
            variable=self._cfg_transparent_var, command=on_transparent,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            activebackground=self._design.panel, activeforeground=self._design.text,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=12, pady=(0, 2))

        # 独立ウィンドウにインスタンス番号を含める
        self._cfg_float_show_inst_var = tk.BooleanVar(value=self._float_win_show_instance)

        def on_float_win_show_instance():
            self._float_win_show_instance = self._cfg_float_show_inst_var.get()
            self._apply_float_win_titles()
            self._save_config()

        tk.Checkbutton(
            g_winvis, text="独立ウィンドウにインスタンス番号を表示する",
            variable=self._cfg_float_show_inst_var, command=on_float_win_show_instance,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            activebackground=self._design.panel, activeforeground=self._design.text,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=12, pady=(0, 6))

        # ════════════════════════════════════════════════
        #  ルーレット文字表示グループ
        # ════════════════════════════════════════════════
        g_txt = make_group(p, "ルーレット文字表示")

        DIR_NAMES = [
            "横表示1（内→外）",
            "横表示2（常に水平）",
            "縦表示1（外→内）",
            "縦表示2（内→外）",
            "縦表示3（常に垂直）",
        ]
        SIZE_NAMES = [
            "省略（…で省略）",
            "収める（改行/拡大縮小）",
            "縮小（全体を縮小）",
        ]

        tk.Label(g_txt, text="表示方向", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(6, 0))
        self._cfg_dir_cb = ttk.Combobox(g_txt, values=DIR_NAMES, state="readonly",
                                        font=("Meiryo", 9))
        self._cfg_dir_cb.current(self._text_direction)
        self._cfg_dir_cb.pack(fill=tk.X, padx=12, pady=(0, 4))

        def on_dir(e=None):
            self._text_direction = self._cfg_dir_cb.current()
            self._save_config()
            self._redraw()

        self._cfg_dir_cb.bind("<<ComboboxSelected>>", on_dir)

        tk.Label(g_txt, text="文字サイズの扱い", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(4, 0))
        self._cfg_size_cb = ttk.Combobox(g_txt, values=SIZE_NAMES, state="readonly",
                                         font=("Meiryo", 9))
        self._cfg_size_cb.current(self._text_size_mode)
        self._cfg_size_cb.pack(fill=tk.X, padx=12, pady=(0, 4))

        def on_size(e=None):
            self._text_size_mode = self._cfg_size_cb.current()
            self._save_config()
            self._redraw()

        self._cfg_size_cb.bind("<<ComboboxSelected>>", on_size)

        self._cfg_donut_var = tk.BooleanVar(value=self._donut_hole)

        def on_donut_hole():
            self._donut_hole = self._cfg_donut_var.get()
            self._save_config()
            self._redraw()

        tk.Checkbutton(
            g_txt, text="中心に穴を表示する（透過時は透明）",
            variable=self._cfg_donut_var, command=on_donut_hole,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            activebackground=self._design.panel, activeforeground=self._design.text,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=12, pady=(4, 4))

        # ── ルーレット文字フォント設定 ──────────────────────────────────
        tk.Label(
            g_txt, text="── フォント設定 ──",
            bg=self._design.panel, fg=self._design.text_sub,
            font=("Meiryo", 8),
        ).pack(anchor="w", padx=16, pady=(2, 0))

        tk.Label(g_txt, text="フォントファミリー", bg=self._design.panel,
                 fg=self._design.text, font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(2, 0))
        _wf_cfg = self._design.fonts.wheel
        # システムで使用可能なフォント一覧（重複除去・ソート・空文字除去）
        _all_fonts = sorted(set(f for f in _tkfont.families(root=self.root) if f))
        _cur_family = _wf_cfg.family
        # 保存済みの family が一覧にない場合は先頭に追加して見えるようにする
        if _cur_family not in _all_fonts:
            _all_fonts = [_cur_family] + _all_fonts
        self._cfg_font_fam_var = tk.StringVar(value=_cur_family)
        _cfg_font_fam_cb = ttk.Combobox(
            g_txt, textvariable=self._cfg_font_fam_var,
            values=_all_fonts, state="readonly",
            font=("Meiryo", 9),
        )
        _cfg_font_fam_cb.pack(fill=tk.X, padx=12, pady=(0, 4))

        def _on_font_family(e=None):
            v = self._cfg_font_fam_var.get().strip()
            if v:
                self._design.fonts.wheel.family = v
                self._save_config()
                self._redraw()

        _cfg_font_fam_cb.bind("<<ComboboxSelected>>", _on_font_family)

        def _make_font_size_row(parent, label, getter, setter):
            """フォントサイズ設定行（ラベル＋Spinbox）を作成する。"""
            row = tk.Frame(parent, bg=self._design.panel)
            row.pack(fill=tk.X, padx=12, pady=(0, 2))
            tk.Label(row, text=label, bg=self._design.panel, fg=self._design.text,
                     font=("Meiryo", 9), width=14, anchor="w").pack(side=tk.LEFT)
            var = tk.IntVar(value=getter())
            sb = tk.Spinbox(
                row, textvariable=var, from_=1, to=200, width=5,
                font=("Meiryo", 9),
                bg=self._design.separator, fg=self._design.text,
                buttonbackground=self._design.separator,
                insertbackground=self._design.text,
                relief=tk.FLAT,
            )
            sb.pack(side=tk.RIGHT)

            def _apply(*_):
                try:
                    v = int(var.get())
                except (ValueError, tk.TclError):
                    return
                v = max(1, min(200, v))
                var.set(v)
                setter(v)
                self._save_config()
                self._redraw()

            sb.config(command=_apply)
            sb.bind("<Return>", _apply)
            sb.bind("<FocusOut>", _apply)

        self._cfg_font_omit_var = _make_font_size_row(
            g_txt, "省略基準サイズ",
            lambda: self._design.fonts.wheel.omit_base_size,
            lambda v: setattr(self._design.fonts.wheel, "omit_base_size", v),
        )
        self._cfg_font_fit_var = _make_font_size_row(
            g_txt, "収める基準サイズ",
            lambda: self._design.fonts.wheel.fit_base_size,
            lambda v: setattr(self._design.fonts.wheel, "fit_base_size", v),
        )
        self._cfg_font_shrink_var = _make_font_size_row(
            g_txt, "縮小基準サイズ",
            lambda: self._design.fonts.wheel.shrink_base_size,
            lambda v: setattr(self._design.fonts.wheel, "shrink_base_size", v),
        )
        self._cfg_font_min_var = _make_font_size_row(
            g_txt, "最小サイズ",
            lambda: self._design.fonts.wheel.min_size,
            lambda v: setattr(self._design.fonts.wheel, "min_size", v),
        )
        self._cfg_font_max_var = _make_font_size_row(
            g_txt, "最大サイズ",
            lambda: self._design.fonts.wheel.max_size,
            lambda v: setattr(self._design.fonts.wheel, "max_size", v),
        )

        tk.Frame(g_txt, bg=self._design.panel, height=4).pack()

        # ════════════════════════════════════════════════
        #  ポインター位置グループ
        # ════════════════════════════════════════════════
        g_mrk = make_group(p, "ポインター位置")

        tk.Label(g_mrk, text="基準位置（ドラッグでも変更可）", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(6, 0))
        self._pointer_preset_var = tk.StringVar(
            value=POINTER_PRESET_NAMES[self._pointer_preset])
        pointer_cb = ttk.Combobox(
            g_mrk, textvariable=self._pointer_preset_var,
            values=POINTER_PRESET_NAMES, state="readonly",
            font=("Meiryo", 9))
        pointer_cb.current(self._pointer_preset)
        pointer_cb.pack(fill=tk.X, padx=12, pady=(0, 4))

        def on_pointer_preset(e=None):
            self._apply_pointer_preset(pointer_cb.current())

        pointer_cb.bind("<<ComboboxSelected>>", on_pointer_preset)

        lock_var = tk.BooleanVar(value=False)
        lock_cb = tk.Checkbutton(
            g_mrk, text="スピン中の操作を有効にする",
            variable=lock_var, state=tk.DISABLED,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            disabledforeground="#aaaacc",
            activebackground=self._design.panel,
            font=("Meiryo", 9),
        )
        lock_cb.pack(anchor="w", padx=12, pady=(0, 6))

        # ════════════════════════════════════════════════
        #  デザイングループ
        # ════════════════════════════════════════════════
        g_design = make_group(p, "デザイン")

        tk.Label(g_design, text="デザインプリセット", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(6, 0))
        self._cfg_design_preset_var = tk.StringVar(value=self._design.preset_name)
        _design_cb = ttk.Combobox(
            g_design, textvariable=self._cfg_design_preset_var,
            values=self._design_preset_mgr.all_design_names(), state="readonly",
            font=("Meiryo", 9),
        )
        _design_cb.pack(fill=tk.X, padx=12, pady=(0, 4))
        self._cfg_design_cb = _design_cb

        def on_design_preset(e=None):
            name = self._cfg_design_preset_var.get()
            # apply_preset() は組み込みプリセットのみ対応のため、
            # DesignPresetManager.get_design() を使ってユーザー作成プリセットにも対応する
            ds = self._design_preset_mgr.get_design(name)
            self._design.preset_name = name
            self._design.global_colors = ds.global_colors
            self._design.wheel = ds.wheel
            self._design.pointer = ds.pointer
            self._design.log = ds.log
            # segment / fonts は維持（apply_preset と同じ方針）
            self._save_config()
            self.root.after(0, self._apply_design_to_all)

        _design_cb.bind("<<ComboboxSelected>>", on_design_preset)

        tk.Label(g_design, text="セグメント配色", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(4, 0))
        self._cfg_seg_preset_var = tk.StringVar(value=self._design.segment.preset_name)
        _seg_cb = ttk.Combobox(
            g_design, textvariable=self._cfg_seg_preset_var,
            values=self._design_preset_mgr.all_segment_names(), state="readonly",
            font=("Meiryo", 9),
        )
        _seg_cb.pack(fill=tk.X, padx=12, pady=(0, 4))
        self._cfg_seg_cb = _seg_cb

        def on_seg_preset(e=None):
            name = self._cfg_seg_preset_var.get()
            self._design_preset_mgr.apply_segment_to_design(name, self._design)
            self._save_config()
            self._redraw()

        _seg_cb.bind("<<ComboboxSelected>>", on_seg_preset)

        tk.Button(
            g_design, text="デザインエディタを開く",
            command=self._open_design_editor,
            bg=self._design.separator, fg=self._design.text,
            font=("Meiryo", 9), relief=tk.FLAT, cursor="hand2",
            padx=6, pady=3,
        ).pack(fill=tk.X, padx=12, pady=(4, 6))

        # ════════════════════════════════════════════════
        #  ログ設定グループ
        # ════════════════════════════════════════════════
        g_log = make_group(p, "ログ設定")

        self._cfg_ts_var = tk.BooleanVar(value=self._log_timestamp)

        def on_log_timestamp():
            self._log_timestamp = self._cfg_ts_var.get()
            self._save_config()

        tk.Checkbutton(
            g_log, text="日時をログに記録する",
            variable=self._cfg_ts_var, command=on_log_timestamp,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            activebackground=self._design.panel, activeforeground=self._design.text,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=12, pady=(6, 2))

        self._cfg_box_border_var = tk.BooleanVar(value=self._log_box_border)

        def on_log_box_border():
            self._log_box_border = self._cfg_box_border_var.get()
            self._save_config()
            self._redraw()

        tk.Checkbutton(
            g_log, text="ログ項目を四角で囲む",
            variable=self._cfg_box_border_var, command=on_log_box_border,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            activebackground=self._design.panel, activeforeground=self._design.text,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=12, pady=(0, 2))

        self._cfg_log_on_top_var = tk.BooleanVar(value=self._log_on_top)

        def on_log_on_top():
            self._log_on_top = self._cfg_log_on_top_var.get()
            self._save_config()
            self._redraw()

        tk.Checkbutton(
            g_log, text="結果表示時にログを前面に表示する",
            variable=self._cfg_log_on_top_var, command=on_log_on_top,
            bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
            activebackground=self._design.panel, activeforeground=self._design.text,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=12, pady=(0, 4))

        _BTN_ROW = dict(bg=self._design.separator, fg=self._design.text, font=("Meiryo", 9),
                        relief=tk.FLAT, cursor="hand2", padx=6, pady=2)

        tk.Button(g_log, text="ログ出力（結果のみ）",
                  command=lambda: self._do_export_log("simple"), **_BTN_ROW
                  ).pack(fill=tk.X, padx=12, pady=(4, 2))

        tk.Button(g_log, text="ログ出力（グループ・項目付き）",
                  command=lambda: self._do_export_log("detailed"), **_BTN_ROW
                  ).pack(fill=tk.X, padx=12, pady=(0, 2))

        tk.Button(g_log, text="ログ削除",
                  command=self._clear_log, **_BTN_ROW
                  ).pack(fill=tk.X, padx=12, pady=(0, 6))

        # ════════════════════════════════════════════════
        #  リプレイグループ
        # ════════════════════════════════════════════════
        g_replay = make_group(p, "リプレイ")

        tk.Label(
            g_replay,
            text="直近のスピンをその場で再生します",
            bg=self._design.panel, fg=self._design.text, font=("Meiryo", 9),
        ).pack(anchor="w", padx=16, pady=(6, 4))

        tk.Button(
            g_replay, text="直前のスピンをリプレイ",
            command=lambda: self._replay_play(0), **_BTN_ROW
        ).pack(fill=tk.X, padx=12, pady=(0, 2))

        tk.Button(
            g_replay, text="リプレイ管理...",
            command=self._open_replay_dialog, **_BTN_ROW
        ).pack(fill=tk.X, padx=12, pady=(0, 4))

        # 保存件数
        max_row = tk.Frame(g_replay, bg=self._design.panel)
        max_row.pack(fill=tk.X, padx=12, pady=(2, 0))
        tk.Label(max_row, text="保存件数", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(side=tk.LEFT)
        self._cfg_replay_max_var = tk.IntVar(value=getattr(self, "_replay_max_count", 5))
        self._cfg_replay_max_lbl = tk.Label(
            max_row, text=f"{self._cfg_replay_max_var.get()} 件",
            bg=self._design.panel, fg=self._design.gold, font=("Meiryo", 10), width=6,
        )
        self._cfg_replay_max_lbl.pack(side=tk.RIGHT)

        def on_replay_max(val):
            v = int(val)
            self._replay_max_count = v
            self._cfg_replay_max_lbl.config(text=f"{v} 件")
            self._replay_enforce_limit()
            self._save_config()

        tk.Scale(g_replay, variable=self._cfg_replay_max_var, from_=1, to=20,
                 orient=tk.HORIZONTAL, resolution=1, showvalue=False,
                 bg=self._design.panel, fg=self._design.text,
                 troughcolor=self._design.separator,
                 highlightthickness=0, bd=0, sliderlength=14,
                 command=on_replay_max).pack(fill=tk.X, padx=12, pady=(0, 4))

        # リプレイ中表示 ON/OFF
        self._cfg_replay_indicator_var = tk.BooleanVar(
            value=getattr(self, "_replay_show_indicator_flag", True)
        )
        def on_replay_indicator():
            self._replay_show_indicator_flag = self._cfg_replay_indicator_var.get()
            self._save_config()
        tk.Checkbutton(
            g_replay, text="リプレイ中表示",
            variable=self._cfg_replay_indicator_var, command=on_replay_indicator,
            bg=self._design.panel, fg=self._design.text,
            selectcolor=self._design.separator, activebackground=self._design.panel,
            font=("Meiryo", 9),
        ).pack(anchor="w", padx=16, pady=(0, 6))

        # ════════════════════════════════════════════════
        #  音量グループ
        # ════════════════════════════════════════════════
        g_vol = make_group(p, "音量")

        # スピン音量
        tick_vol_row = tk.Frame(g_vol, bg=self._design.panel)
        tick_vol_row.pack(fill=tk.X, padx=12, pady=(6, 0))
        tk.Label(tick_vol_row, text="スピン音", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(side=tk.LEFT)
        self._cfg_tick_vol_lbl = tk.Label(tick_vol_row, text=f"{self._tick_volume} %",
                                          bg=self._design.panel, fg=self._design.gold, font=("Meiryo", 10), width=6)
        self._cfg_tick_vol_lbl.pack(side=tk.RIGHT)
        self._cfg_tick_vol_var = tk.IntVar(value=self._tick_volume)

        def on_tick_vol(val):
            v = int(val)
            self._tick_volume = v
            self._cfg_tick_vol_lbl.config(text=f"{v} %")
            self.snd.set_tick_volume(v / 100)
            self._save_config()

        tk.Scale(g_vol, variable=self._cfg_tick_vol_var, from_=0, to=100, orient=tk.HORIZONTAL,
                 resolution=1, showvalue=False,
                 bg=self._design.panel, fg=self._design.text, troughcolor=self._design.separator,
                 highlightthickness=0, bd=0, sliderlength=14,
                 command=on_tick_vol).pack(fill=tk.X, padx=12, pady=(0, 4))

        # 決定音量
        win_vol_row = tk.Frame(g_vol, bg=self._design.panel)
        win_vol_row.pack(fill=tk.X, padx=12, pady=(2, 0))
        tk.Label(win_vol_row, text="決定音", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(side=tk.LEFT)
        self._cfg_win_vol_lbl = tk.Label(win_vol_row, text=f"{self._win_volume} %",
                                         bg=self._design.panel, fg=self._design.gold, font=("Meiryo", 10), width=6)
        self._cfg_win_vol_lbl.pack(side=tk.RIGHT)
        self._cfg_win_vol_var = tk.IntVar(value=self._win_volume)

        def on_win_vol(val):
            v = int(val)
            self._win_volume = v
            self._cfg_win_vol_lbl.config(text=f"{v} %")
            self.snd.set_win_volume(v / 100)
            self._save_config()

        tk.Scale(g_vol, variable=self._cfg_win_vol_var, from_=0, to=100, orient=tk.HORIZONTAL,
                 resolution=1, showvalue=False,
                 bg=self._design.panel, fg=self._design.text, troughcolor=self._design.separator,
                 highlightthickness=0, bd=0, sliderlength=14,
                 command=on_win_vol).pack(fill=tk.X, padx=12, pady=(0, 6))

        # ════════════════════════════════════════════════
        #  スピン音 / 決定音グループ
        # ════════════════════════════════════════════════
        g_snd = make_group(p, "スピン音 / 決定音")

        _APP_DIR = (os.path.dirname(sys.executable)
                    if getattr(sys, 'frozen', False)
                    else os.path.dirname(os.path.abspath(__file__)))
        _CUSTOM_IDX_TICK = len(TICK_PATTERN_NAMES) - 1
        _CUSTOM_IDX_WIN  = len(WIN_PATTERN_NAMES) - 1

        patterns_row = tk.Frame(g_snd, bg=self._design.panel)
        patterns_row.pack(fill=tk.X, padx=12, pady=(6, 6))
        patterns_row.columnconfigure(0, weight=1, uniform="snd_col")
        patterns_row.columnconfigure(2, weight=1, uniform="snd_col")

        # ── スピン音 列 ──────────────────────────────
        tick_col = tk.Frame(patterns_row, bg=self._design.panel)
        tick_col.grid(row=0, column=0, sticky="nsew")
        tk.Label(tick_col, text="スピン音", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9, "bold")).pack(anchor="w", pady=(2, 1))
        self._cfg_tick_var = tk.IntVar(value=self._tick_pattern)
        self._cfg_tick_btns = []
        self._cfg_tick_custom_lbl = tk.Label(
            tick_col, text="", bg=self._design.panel, fg=self._design.gold,
            font=("Meiryo", 7), wraplength=90, justify=tk.LEFT)

        def _pick_tick_custom():
            init_dir = (os.path.dirname(self._tick_custom_file)
                        if self._tick_custom_file and os.path.dirname(self._tick_custom_file)
                        else _APP_DIR)
            path = _filedialog.askopenfilename(
                parent=self.root,
                title="スピン音ファイルを選択",
                initialdir=init_dir,
                filetypes=[
                    ("サウンドファイル", "*.wav *.mp3 *.ogg *.WAV *.MP3 *.OGG"),
                    ("すべてのファイル", "*.*"),
                ],
            )
            if path:
                self._tick_custom_file = path
                self.snd.load_tick_custom(path)
                for j, b in enumerate(self._cfg_tick_btns):
                    b.config(bg=self._design.accent if j == _CUSTOM_IDX_TICK else self._design.separator)
                self._cfg_tick_var.set(_CUSTOM_IDX_TICK)
                self._tick_pattern = _CUSTOM_IDX_TICK
                self.snd.set_tick_pattern(_CUSTOM_IDX_TICK)
                self._cfg_tick_custom_lbl.config(text=os.path.basename(path))
                self._save_config()

        def on_tick_btn(idx):
            if idx == _CUSTOM_IDX_TICK:
                _pick_tick_custom()
                return
            for j, b in enumerate(self._cfg_tick_btns):
                b.config(bg=self._design.accent if j == idx else self._design.separator)
            self._cfg_tick_var.set(idx)
            self._tick_pattern = idx
            self.snd.set_tick_pattern(idx)
            self._save_config()

        for i, name in enumerate(TICK_PATTERN_NAMES):
            btn = tk.Button(
                tick_col, text=name,
                bg=self._design.accent if self._tick_pattern == i else self._design.separator,
                fg=self._design.text, font=("Meiryo", 9),
                relief=tk.FLAT, cursor="hand2", padx=4, pady=2,
                command=lambda i=i: on_tick_btn(i),
            )
            btn.pack(fill=tk.X, pady=1)
            self._cfg_tick_btns.append(btn)

        if self._tick_custom_file:
            self._cfg_tick_custom_lbl.config(text=os.path.basename(self._tick_custom_file))
        self._cfg_tick_custom_lbl.pack(anchor="w", pady=(1, 0))

        tk.Button(tick_col, text="試聴",
                  command=lambda: self.snd.preview_tick(self._cfg_tick_var.get()),
                  bg=self._design.separator, fg=self._design.text, font=("Meiryo", 8),
                  relief=tk.FLAT, cursor="hand2", padx=6
                  ).pack(anchor="w", pady=(4, 2))

        tk.Frame(patterns_row, bg=self._design.separator, width=1).grid(row=0, column=1, sticky="ns", padx=8)

        # ── 決定音 列 ──────────────────────────────
        win_col = tk.Frame(patterns_row, bg=self._design.panel)
        win_col.grid(row=0, column=2, sticky="nsew")
        tk.Label(win_col, text="決定音", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9, "bold")).pack(anchor="w", pady=(2, 1))
        self._cfg_win_var = tk.IntVar(value=self._win_pattern)
        self._cfg_win_btns = []
        self._cfg_win_custom_lbl = tk.Label(
            win_col, text="", bg=self._design.panel, fg=self._design.gold,
            font=("Meiryo", 7), wraplength=90, justify=tk.LEFT)

        def _pick_win_custom():
            init_dir = (os.path.dirname(self._win_custom_file)
                        if self._win_custom_file and os.path.dirname(self._win_custom_file)
                        else _APP_DIR)
            path = _filedialog.askopenfilename(
                parent=self.root,
                title="決定音ファイルを選択",
                initialdir=init_dir,
                filetypes=[
                    ("サウンドファイル", "*.wav *.mp3 *.ogg *.WAV *.MP3 *.OGG"),
                    ("すべてのファイル", "*.*"),
                ],
            )
            if path:
                self._win_custom_file = path
                self.snd.load_win_custom(path)
                for j, b in enumerate(self._cfg_win_btns):
                    b.config(bg=self._design.accent if j == _CUSTOM_IDX_WIN else self._design.separator)
                self._cfg_win_var.set(_CUSTOM_IDX_WIN)
                self._win_pattern = _CUSTOM_IDX_WIN
                self.snd.set_win_pattern(_CUSTOM_IDX_WIN)
                self._cfg_win_custom_lbl.config(text=os.path.basename(path))
                self._save_config()

        def on_win_btn(idx):
            if idx == _CUSTOM_IDX_WIN:
                _pick_win_custom()
                return
            for j, b in enumerate(self._cfg_win_btns):
                b.config(bg=self._design.accent if j == idx else self._design.separator)
            self._cfg_win_var.set(idx)
            self._win_pattern = idx
            self.snd.set_win_pattern(idx)
            self._save_config()

        for i, name in enumerate(WIN_PATTERN_NAMES):
            btn = tk.Button(
                win_col, text=name,
                bg=self._design.accent if self._win_pattern == i else self._design.separator,
                fg=self._design.text, font=("Meiryo", 9),
                relief=tk.FLAT, cursor="hand2", padx=4, pady=2,
                command=lambda i=i: on_win_btn(i),
            )
            btn.pack(fill=tk.X, pady=1)
            self._cfg_win_btns.append(btn)

        if self._win_custom_file:
            self._cfg_win_custom_lbl.config(text=os.path.basename(self._win_custom_file))
        self._cfg_win_custom_lbl.pack(anchor="w", pady=(1, 0))

        tk.Button(win_col, text="試聴",
                  command=lambda: self.snd.preview_win(self._cfg_win_var.get()),
                  bg=self._design.separator, fg=self._design.text, font=("Meiryo", 8),
                  relief=tk.FLAT, cursor="hand2", padx=6
                  ).pack(anchor="w", pady=(4, 2))

        # ════════════════════════════════════════════════
        #  操作設定グループ
        # ════════════════════════════════════════════════
        g_op = make_group(p, "操作設定")

        def fmt_sec(v):
            return "即時" if v == 0 else f"{v} 秒"

        def make_slider_row(label, val):
            row = tk.Frame(g_op, bg=self._design.panel)
            row.pack(fill=tk.X, padx=12, pady=(2, 0))
            tk.Label(row, text=label, bg=self._design.panel, fg=self._design.text,
                     font=("Meiryo", 9)).pack(side=tk.LEFT)
            lbl = tk.Label(row, text=fmt_sec(val), bg=self._design.panel, fg=self._design.gold,
                           font=("Meiryo", 9), width=5)
            lbl.pack(side=tk.RIGHT)
            return lbl

        self._cfg_spin_lbl   = make_slider_row("▶  スピン開始（通常）", self._spin_duration)
        self._cfg_spin_var   = tk.IntVar(value=self._spin_duration)
        self._cfg_spin_sc    = tk.Scale(g_op, variable=self._cfg_spin_var, from_=1, to=30,
                                        orient=tk.HORIZONTAL, resolution=1, showvalue=False,
                                        bg=self._design.panel, fg=self._design.text, troughcolor=self._design.separator,
                                        highlightthickness=0, bd=0, sliderlength=14)
        self._cfg_spin_sc.pack(fill=tk.X, padx=12, pady=(0, 2))

        self._cfg_double_lbl = make_slider_row("✕2  ダブル停止", self._double_duration)
        self._cfg_double_var = tk.IntVar(value=self._double_duration)
        self._cfg_double_sc  = tk.Scale(g_op, variable=self._cfg_double_var, from_=0, to=30,
                                        orient=tk.HORIZONTAL, resolution=1, showvalue=False,
                                        bg=self._design.panel, fg=self._design.text, troughcolor=self._design.separator,
                                        highlightthickness=0, bd=0, sliderlength=14)
        self._cfg_double_sc.pack(fill=tk.X, padx=12, pady=(0, 2))

        self._cfg_triple_lbl = make_slider_row("✕3  トリプル停止", self._triple_duration)
        self._cfg_triple_var = tk.IntVar(value=self._triple_duration)
        self._cfg_triple_sc  = tk.Scale(g_op, variable=self._cfg_triple_var, from_=0, to=30,
                                        orient=tk.HORIZONTAL, resolution=1, showvalue=False,
                                        bg=self._design.panel, fg=self._design.text, troughcolor=self._design.separator,
                                        highlightthickness=0, bd=0, sliderlength=14)
        self._cfg_triple_sc.pack(fill=tk.X, padx=12, pady=(0, 6))

        def on_spin(val):
            v = int(val)
            self._spin_duration = v
            self._cfg_spin_lbl.config(text=fmt_sec(v))
            if self._cfg_double_var.get() > v:
                self._cfg_double_var.set(v)
                on_double(v)
            self._save_config()

        def on_double(val):
            v = int(val)
            if v > self._cfg_spin_var.get():
                v = self._cfg_spin_var.get()
                self._cfg_double_var.set(v)
            if self._cfg_triple_var.get() > v:
                self._cfg_triple_var.set(v)
                on_triple(v)
            self._double_duration = v
            self._cfg_double_lbl.config(text=fmt_sec(v))
            self._cfg_double_sc.config(to=self._cfg_spin_var.get())
            self._save_config()

        def on_triple(val):
            v = int(val)
            if v > self._cfg_double_var.get():
                v = self._cfg_double_var.get()
                self._cfg_triple_var.set(v)
            self._triple_duration = v
            self._cfg_triple_lbl.config(text=fmt_sec(v))
            self._cfg_triple_sc.config(to=self._cfg_double_var.get())
            self._save_config()

        self._cfg_spin_sc.config(command=on_spin)
        self._cfg_double_sc.config(command=on_double)
        self._cfg_triple_sc.config(command=on_triple)
        self._cfg_double_sc.config(to=self._spin_duration)
        self._cfg_triple_sc.config(to=self._double_duration)

        # ════════════════════════════════════════════════
        #  結果表示設定グループ
        # ════════════════════════════════════════════════
        g_result = make_group(p, "結果表示")

        _RESULT_CLOSE_NAMES = ["クリックで閉じる", "自動で閉じる", "クリック + 自動"]
        tk.Label(g_result, text="閉じ方", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(4, 0))
        self._cfg_result_close_cb = ttk.Combobox(
            g_result, values=_RESULT_CLOSE_NAMES, state="readonly", font=("Meiryo", 9))
        self._cfg_result_close_cb.current(getattr(self, '_result_close_mode', 2))
        self._cfg_result_close_cb.pack(fill=tk.X, padx=12, pady=(2, 4))

        def on_result_close(e=None):
            self._result_close_mode = self._cfg_result_close_cb.current()
            self._save_config()

        self._cfg_result_close_cb.bind("<<ComboboxSelected>>", on_result_close)

        def _fmt_hold(v):
            v = float(v)
            return f"{v:.0f} 秒" if v == int(v) else f"{v:.1f} 秒"

        _hold_row = tk.Frame(g_result, bg=self._design.panel)
        _hold_row.pack(fill=tk.X, padx=12, pady=(2, 0))
        tk.Label(_hold_row, text="自動クローズ時間", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(side=tk.LEFT)
        self._cfg_result_hold_lbl = tk.Label(
            _hold_row, text=_fmt_hold(getattr(self, '_result_hold_sec', 5.0)),
            bg=self._design.panel, fg=self._design.gold, font=("Meiryo", 9), width=6)
        self._cfg_result_hold_lbl.pack(side=tk.RIGHT)
        self._cfg_result_hold_var = tk.DoubleVar(value=getattr(self, '_result_hold_sec', 5.0))
        self._cfg_result_hold_sc = tk.Scale(
            g_result, variable=self._cfg_result_hold_var,
            from_=0.5, to=30.0, orient=tk.HORIZONTAL, resolution=0.5, showvalue=False,
            bg=self._design.panel, fg=self._design.text, troughcolor=self._design.separator,
            highlightthickness=0, bd=0, sliderlength=14)
        self._cfg_result_hold_sc.pack(fill=tk.X, padx=12, pady=(0, 6))

        def on_result_hold(val):
            v = float(val)
            self._result_hold_sec = v
            self._cfg_result_hold_lbl.config(text=_fmt_hold(v))
            self._save_config()

        self._cfg_result_hold_sc.config(command=on_result_hold)

        # ════════════════════════════════════════════════
        #  配置設定グループ
        # ════════════════════════════════════════════════
        g_arr = make_group(p, "配置設定")

        # 全リセット確認
        self._cfg_confirm_reset_var = tk.BooleanVar(
            value=getattr(self, '_confirm_reset', True))

        def on_confirm_reset():
            self._confirm_reset = self._cfg_confirm_reset_var.get()
            self._save_config()

        tk.Checkbutton(g_arr, text="一括リセット前に確認ダイアログを表示",
                       variable=self._cfg_confirm_reset_var, command=on_confirm_reset,
                       bg=self._design.panel, fg=self._design.text, selectcolor=self._design.separator,
                       activebackground=self._design.panel, activeforeground=self._design.text,
                       font=("Meiryo", 9)).pack(anchor="w", padx=12, pady=(4, 0))
        tk.Label(g_arr, text="※ OFF にすると確認なしで即実行されます",
                 bg=self._design.panel, fg="#667788", font=("Meiryo", 8),
                 ).pack(anchor="w", padx=24, pady=(0, 4))

        _ARR_DIR_NAMES  = ["時計回り", "反時計回り"]
        _SPIN_DIR_NAMES = ["時計回り", "反時計回り"]

        tk.Label(g_arr, text="項目配置順方向", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(6, 0))
        self._cfg_arr_dir_cb = ttk.Combobox(g_arr, values=_ARR_DIR_NAMES, state="readonly",
                                             font=("Meiryo", 9))
        self._cfg_arr_dir_cb.current(getattr(self, '_arrangement_direction', 0))
        self._cfg_arr_dir_cb.pack(fill=tk.X, padx=12, pady=(0, 4))

        def on_arr_dir(e=None):
            self._arrangement_direction = self._cfg_arr_dir_cb.current()
            self._rebuild_segments()
            self._save_config()
            self._redraw()

        self._cfg_arr_dir_cb.bind("<<ComboboxSelected>>", on_arr_dir)

        tk.Label(g_arr, text="ルーレット回転方向", bg=self._design.panel, fg=self._design.text,
                 font=("Meiryo", 9)).pack(anchor="w", padx=16, pady=(4, 0))
        self._cfg_spin_dir_cb = ttk.Combobox(g_arr, values=_SPIN_DIR_NAMES, state="readonly",
                                              font=("Meiryo", 9))
        self._cfg_spin_dir_cb.current(getattr(self, '_spin_direction', 0))
        self._cfg_spin_dir_cb.pack(fill=tk.X, padx=12, pady=(0, 6))

        def on_spin_dir(e=None):
            self._spin_direction = self._cfg_spin_dir_cb.current()
            self._save_config()

        self._cfg_spin_dir_cb.bind("<<ComboboxSelected>>", on_spin_dir)

        # バージョン表示
        tk.Label(p, text=f"Version: v{VERSION}",
                 bg=self._design.panel, fg=self._design.text_sub,
                 font=("Meiryo", 8)).pack(anchor="e", padx=12, pady=(8, 2))

        # 末尾の余白
        tk.Frame(p, bg=self._design.panel, height=8).pack()

        # スピン中ロック対象ウィジェットを収集（Button / Scale / Checkbutton / Combobox）
        self._lockable_cfg_widgets = []
        def _collect(w):
            if type(w).__name__ in ("Button", "Scale", "Checkbutton", "Combobox"):
                self._lockable_cfg_widgets.append(w)
            for c in w.winfo_children():
                _collect(c)
        _collect(p)

        # ── 浮動ウィンドウの非表示処理（widget 構築完了後に実行） ───────────────
        if self._cfg_panel_float and not self._cfg_panel_visible:
            if not getattr(self, "_float_win_show_instance", True):
                # OBS 用: ウィジェット構築完了後に destroy（OS 上に同名ウィンドウを残さない）
                self._cfg_panel_float_geo = self._cfg_panel_toplevel.geometry()
                self._cfg_panel_toplevel.destroy()
                self._cfg_panel_toplevel = None
            else:
                self._cfg_panel_toplevel.withdraw()
            self.root.focus_set()  # 非表示 Toplevel にフォーカスを奪われないよう root に戻す

    # ════════════════════════════════════════════════════════════════
    #  リプレイ管理ダイアログ
    # ════════════════════════════════════════════════════════════════
    def _open_replay_dialog(self):
        from replay_dialog import ReplayDialog
        win = getattr(self, "_replay_dialog_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_set()
                    win._refresh_list()
                    return
            except Exception:
                pass
        self._replay_dialog_win = ReplayDialog(self)

    # ════════════════════════════════════════════════════════════════
    #  スピン中 UI ロック
    # ════════════════════════════════════════════════════════════════
    def set_cfg_spin_lock(self, locked: bool):
        """スピン中は設定パネルのすべての操作ウィジェットを無効化する。"""
        for w in getattr(self, "_lockable_cfg_widgets", []):
            try:
                if not w.winfo_exists():
                    continue
                if locked:
                    w.config(state=tk.DISABLED)
                else:
                    if isinstance(w, ttk.Combobox):
                        w.config(state="readonly")
                    else:
                        w.config(state=tk.NORMAL)
            except tk.TclError:
                pass

    # ════════════════════════════════════════════════════════════════
    #  設定 UI への反映（リセット・インポート後に呼び出す）
    # ════════════════════════════════════════════════════════════════
    def _apply_cfg_to_ui(self):
        """self._ 属性の値を設定パネルの UI コントロールに反映する。"""
        def _fmt(v):
            return "即時" if v == 0 else f"{v} 秒"

        # スライダー（to 上限を先に更新してから値をセット）
        self._cfg_double_sc.config(to=self._spin_duration)
        self._cfg_triple_sc.config(to=self._double_duration)
        self._cfg_spin_var.set(self._spin_duration)
        self._cfg_spin_lbl.config(text=_fmt(self._spin_duration))
        self._cfg_double_var.set(self._double_duration)
        self._cfg_double_lbl.config(text=_fmt(self._double_duration))
        self._cfg_triple_var.set(self._triple_duration)
        self._cfg_triple_lbl.config(text=_fmt(self._triple_duration))
        # 音量
        self._cfg_tick_vol_var.set(self._tick_volume)
        self._cfg_tick_vol_lbl.config(text=f"{self._tick_volume} %")
        self.snd.set_tick_volume(self._tick_volume / 100)
        self._cfg_win_vol_var.set(self._win_volume)
        self._cfg_win_vol_lbl.config(text=f"{self._win_volume} %")
        self.snd.set_win_volume(self._win_volume / 100)
        # 音パターン（ボタン選択状態更新）
        self._cfg_tick_var.set(self._tick_pattern)
        for _j, _b in enumerate(self._cfg_tick_btns):
            _b.config(bg=self._design.accent if _j == self._tick_pattern else self._design.separator)
        self.snd.set_tick_pattern(self._tick_pattern)
        self._cfg_tick_custom_lbl.config(
            text=os.path.basename(self._tick_custom_file) if self._tick_custom_file else "")
        self._cfg_win_var.set(self._win_pattern)
        for _j, _b in enumerate(self._cfg_win_btns):
            _b.config(bg=self._design.accent if _j == self._win_pattern else self._design.separator)
        self.snd.set_win_pattern(self._win_pattern)
        self._cfg_win_custom_lbl.config(
            text=os.path.basename(self._win_custom_file) if self._win_custom_file else "")
        # 表示
        self._cfg_dir_cb.current(self._text_direction)
        self._cfg_size_cb.current(self._text_size_mode)
        self._cfg_donut_var.set(self._donut_hole)
        # ポインター
        if 0 <= self._pointer_preset < len(POINTER_PRESET_NAMES):
            self._pointer_preset_var.set(POINTER_PRESET_NAMES[self._pointer_preset])
        # ウィンドウ表示系
        if hasattr(self, '_cfg_topmost_var'):
            self._cfg_topmost_var.set(self._topmost)
        if hasattr(self, '_cfg_transparent_var'):
            self._cfg_transparent_var.set(self._transparent)
        if hasattr(self, '_cfg_ctrl_box_var'):
            self._cfg_ctrl_box_var.set(self._ctrl_box_visible)
        if hasattr(self, '_cfg_grip_var'):
            self._cfg_grip_var.set(self._grip_visible)
        if hasattr(self, '_cfg_overlay_var'):
            self._cfg_overlay_var.set(self._log_overlay_show)
        if hasattr(self, '_cfg_items_vis_var'):
            self._cfg_items_vis_var.set(self._settings_visible)
        # ウィンドウ表示（独立ウィンドウ番号付与）
        if hasattr(self, '_cfg_float_show_inst_var'):
            self._cfg_float_show_inst_var.set(self._float_win_show_instance)
        # ログ設定
        self._cfg_ts_var.set(self._log_timestamp)
        self._cfg_box_border_var.set(self._log_box_border)
        self._cfg_log_on_top_var.set(self._log_on_top)
        if hasattr(self, '_cfg_arr_dir_cb'):
            self._cfg_arr_dir_cb.current(self._arrangement_direction)
        if hasattr(self, '_cfg_spin_dir_cb'):
            self._cfg_spin_dir_cb.current(self._spin_direction)
        # デザイン・フォント系 UI 反映
        if hasattr(self, '_cfg_design_preset_var'):
            self._cfg_design_preset_var.set(self._design.preset_name)
        if hasattr(self, '_cfg_seg_preset_var'):
            self._cfg_seg_preset_var.set(self._design.segment.preset_name)
        _wf = self._design.fonts.wheel
        if hasattr(self, '_cfg_font_fam_var'):
            self._cfg_font_fam_var.set(_wf.family)
        if hasattr(self, '_cfg_font_omit_var'):
            self._cfg_font_omit_var.set(_wf.omit_base_size)
        if hasattr(self, '_cfg_font_fit_var'):
            self._cfg_font_fit_var.set(_wf.fit_base_size)
        if hasattr(self, '_cfg_font_shrink_var'):
            self._cfg_font_shrink_var.set(_wf.shrink_base_size)
        if hasattr(self, '_cfg_font_min_var'):
            self._cfg_font_min_var.set(_wf.min_size)
        if hasattr(self, '_cfg_font_max_var'):
            self._cfg_font_max_var.set(_wf.max_size)
        # 結果表示
        if hasattr(self, '_cfg_result_close_cb'):
            self._cfg_result_close_cb.current(getattr(self, '_result_close_mode', 2))
        if hasattr(self, '_cfg_result_hold_var'):
            _v = getattr(self, '_result_hold_sec', 5.0)
            self._cfg_result_hold_var.set(_v)
            self._cfg_result_hold_lbl.config(
                text=(f"{_v:.0f} 秒" if _v == int(_v) else f"{_v:.1f} 秒"))
        # リプレイ設定
        if hasattr(self, '_cfg_replay_max_var'):
            self._cfg_replay_max_var.set(self._replay_max_count)
            self._cfg_replay_max_lbl.config(text=f"{self._replay_max_count} 件")
        if hasattr(self, '_cfg_replay_indicator_var'):
            self._cfg_replay_indicator_var.set(self._replay_show_indicator_flag)

    # ════════════════════════════════════════════════════════════════
    #  設定リセット
    # ════════════════════════════════════════════════════════════════
    def _reset_cfg_settings(self):
        """設定項目をデフォルト値にリセットする。"""
        if not _msgbox.askyesno(
            "設定リセット",
            "設定をすべてデフォルト値に戻しますか？\n（項目リストは変更されません）",
            parent=self.root,
        ):
            return
        d = _SETTINGS_DEFAULTS
        self._spin_duration    = d["spin_duration"]
        self._double_duration  = d["double_duration"]
        self._triple_duration  = d["triple_duration"]
        self._tick_volume      = d["tick_volume"]
        self._win_volume       = d["win_volume"]
        self._tick_pattern     = d["tick_pattern"]
        self._win_pattern      = d["win_pattern"]
        self._tick_custom_file = d["tick_custom_file"]
        self._win_custom_file  = d["win_custom_file"]
        self.snd.load_tick_custom(self._tick_custom_file)
        self.snd.load_win_custom(self._win_custom_file)
        self._text_direction   = d["text_direction"]
        self._text_size_mode   = d["text_size_mode"]
        self._donut_hole       = d["donut_hole"]
        self._pointer_preset   = d["pointer_preset"]
        self._pointer_angle    = d["pointer_angle"]
        self._log_timestamp    = d["log_timestamp"]
        self._log_overlay_show = d["log_overlay_show"]
        self._log_box_border   = d["log_box_border"]
        self._log_on_top       = d["log_on_top"]
        self._auto_shuffle          = d.get("auto_shuffle", False)
        self._arrangement_direction = d.get("arrangement_direction", 0)
        self._spin_direction        = d.get("spin_direction", 0)
        self._float_win_show_instance = d.get("float_win_show_instance", True)
        self._result_close_mode = int(d["result_close_mode"])
        self._result_hold_sec   = float(d["result_hold_sec"])
        self._replay_max_count         = int(d.get("replay_max_count", 5))
        self._replay_show_indicator_flag = bool(d.get("replay_show_indicator", True))
        self._replay_enforce_limit()
        # デザイン設定もデフォルトへ戻す
        self._design = DesignSettings()
        self._apply_pointer_preset(self._pointer_preset)
        self._rebuild_segments()
        self._apply_float_win_titles()
        self._save_config()
        # パネル全体を再構築してデザイン・フォント UI を含めてすべて反映する
        self._apply_design_to_all()

    # ════════════════════════════════════════════════════════════════
    #  設定インポート（設定項目のみ）
    # ════════════════════════════════════════════════════════════════
    def _import_cfg_settings(self):
        """JSONファイルから設定項目を読み込む（項目リスト・UI状態は変更しない）。"""
        path = _filedialog.askopenfilename(
            parent=self.root,
            title="設定をインポート",
            initialdir=EXPORT_DIR,
            defaultextension=".json",
            filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as ex:
            _msgbox.showerror("インポートエラー", f"ファイルを読み込めませんでした:\n{ex}",
                              parent=self.root)
            return
        if not isinstance(data, dict):
            _msgbox.showerror(
                "インポートエラー",
                "ファイルの形式が正しくありません。\n"
                "設定エクスポートで作成したJSONファイルを使用してください。",
                parent=self.root,
            )
            return
        # 既存デフォルトをベースに有効なキーのみ上書き適用
        d = _SETTINGS_DEFAULTS.copy()
        for k in _SETTINGS_KEYS:
            if k in data:
                d[k] = data[k]
        self._spin_duration    = int(d["spin_duration"])
        self._double_duration  = int(d["double_duration"])
        self._triple_duration  = int(d["triple_duration"])
        self._tick_volume      = int(d["tick_volume"])
        self._win_volume       = int(d["win_volume"])
        self._tick_pattern     = int(d["tick_pattern"])
        self._win_pattern      = int(d["win_pattern"])
        self._tick_custom_file = str(d.get("tick_custom_file", ""))
        self._win_custom_file  = str(d.get("win_custom_file", ""))
        self.snd.load_tick_custom(self._tick_custom_file)
        self.snd.load_win_custom(self._win_custom_file)
        self._text_direction   = int(d["text_direction"])
        self._text_size_mode   = int(d["text_size_mode"])
        self._donut_hole       = bool(d["donut_hole"])
        self._pointer_preset   = int(d["pointer_preset"])
        self._pointer_angle    = float(d["pointer_angle"])
        self._log_timestamp    = bool(d["log_timestamp"])
        self._log_overlay_show = bool(d["log_overlay_show"])
        self._log_box_border   = bool(d["log_box_border"])
        self._log_on_top       = bool(d["log_on_top"])
        self._auto_shuffle          = bool(d.get("auto_shuffle", False))
        self._arrangement_direction = int(d.get("arrangement_direction", 0))
        self._spin_direction        = int(d.get("spin_direction", 0))
        self._float_win_show_instance = bool(d.get("float_win_show_instance", True))
        self._result_close_mode = int(d.get("result_close_mode", 2))
        self._result_hold_sec   = float(d.get("result_hold_sec", 5.0))
        self._replay_max_count         = int(d.get("replay_max_count", 5))
        self._replay_show_indicator_flag = bool(d.get("replay_show_indicator", True))
        self._replay_enforce_limit()
        # design キーが含まれていれば design 設定も復元する
        _has_design = "design" in data
        if _has_design:
            self._design = DesignSettings.from_dict(data["design"])
        self._apply_pointer_preset(self._pointer_preset)
        self._rebuild_segments()
        self._apply_float_win_titles()
        self._save_config()
        if _has_design:
            # デザイン含む場合はパネル全体を再構築して全 UI を反映する
            self._apply_design_to_all()
        else:
            self._apply_cfg_to_ui()
            self._redraw()
        _msgbox.showinfo("インポート完了", "設定を読み込みました。", parent=self.root)

    # ════════════════════════════════════════════════════════════════
    #  設定エクスポート（設定項目のみ）
    # ════════════════════════════════════════════════════════════════
    def _export_cfg_settings(self):
        """現在の設定項目をJSONファイルに書き出す（項目リスト・UI状態は含まない）。"""
        path = _filedialog.asksaveasfilename(
            parent=self.root,
            title="設定をエクスポート",
            initialdir=EXPORT_DIR,
            initialfile="roulette_settings_export.json",
            defaultextension=".json",
            filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        data = {k: getattr(self, f"_{k}") for k in _SETTINGS_KEYS}
        # design 設定も含める（将来のデザイン専用 import/export とは "design" キーで区別）
        data["design"] = self._design.to_dict()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _msgbox.showinfo("エクスポート完了", f"保存しました:\n{path}", parent=self.root)
        except Exception as ex:
            _msgbox.showerror("エクスポートエラー", str(ex), parent=self.root)

    # ════════════════════════════════════════════════════════════════
    #  設定を即時保存
    # ════════════════════════════════════════════════════════════════
    def _save_cfg_settings_now(self):
        """設定を即時保存する（ボタン押下時）。"""
        self._save_config()
        _msgbox.showinfo("保存完了", "設定を保存しました。", parent=self.root)

    # ════════════════════════════════════════════════════════════════
    #  右設定パネル 表示/非表示
    # ════════════════════════════════════════════════════════════════
    def _toggle_cfg_panel(self):
        if self._cfg_panel_float:
            if self._cfg_panel_visible:
                # 非表示にする
                self._cfg_panel_visible = False
                if not getattr(self, "_float_win_show_instance", True):
                    # OBS 用: destroy して同名ウィンドウを残さない
                    if self._cfg_panel_toplevel and self._cfg_panel_toplevel.winfo_exists():
                        self._cfg_panel_float_geo = self._cfg_panel_toplevel.geometry()
                        self._cfg_panel_toplevel.destroy()
                        self._cfg_panel_toplevel = None
                else:
                    if self._cfg_panel_toplevel and self._cfg_panel_toplevel.winfo_exists():
                        self._cfg_panel_toplevel.withdraw()
                        self.root.focus_set()
            else:
                # 再表示する
                self._cfg_panel_visible = True
                if not getattr(self, "_float_win_show_instance", True):
                    # OBS 用: hide 時に destroy 済みなので常に再生成
                    self._rebuild_cfg_panel_float_win()
                else:
                    if self._cfg_panel_toplevel and self._cfg_panel_toplevel.winfo_exists():
                        self._cfg_panel_toplevel.deiconify()
                    else:
                        # Toplevel が存在しない場合は再生成
                        self._rebuild_cfg_panel_float_win()
            self._save_config()
            return
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        total = self._cfg_panel_w + 4 + 8
        if self._cfg_panel_visible:
            self._cfg_panel_visible = False
            self.root.geometry(f"{max(MIN_W, w - total)}x{h}")
        else:
            self._cfg_panel_visible = True
            self.root.geometry(f"{w + total}x{h}")
        self._apply_right_panel_layout()
        self._save_config()
