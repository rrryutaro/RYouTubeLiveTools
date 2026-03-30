"""
RTokei — デジタル時計アプリ
  - 1段目: 日付 + 曜日
  - 2段目: 時刻 (書式選択可)
  - 右クリックメニューで各種設定
  - 設定は rtokei_settings.json に自動保存
"""

VERSION = "0.1.0"

import tkinter as tk
from tkinter import font as tkfont, colorchooser, ttk
import json, os, sys, datetime, ctypes, ctypes.wintypes

# ─── ウィンドウスタイル定数 ──────────────────────────────────────────
GWL_EXSTYLE      = -20
WS_EX_APPWINDOW  = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

MIN_W, MIN_H = 180, 50


def _is_on_any_monitor(x, y, w=1, h=1):
    """ウィンドウ中心がいずれかのモニター上にあるか確認"""
    try:
        MONITOR_DEFAULTTONULL = 0
        pt = ctypes.wintypes.POINT(x + w // 2, y + h // 2)
        return ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONULL) != 0
    except Exception:
        return True


# ─── パス設定 ───────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "rtokei_settings.json")

WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

SIZE_PRESETS = {
    "極小": {"width": 220, "height": 70,  "date_fs": 13, "time_fs": 24},
    "小":   {"width": 290, "height": 90,  "date_fs": 16, "time_fs": 32},
    "中":   {"width": 360, "height": 112, "date_fs": 20, "time_fs": 40},
    "大":   {"width": 480, "height": 148, "date_fs": 26, "time_fs": 54},
    "極大": {"width": 640, "height": 196, "date_fs": 34, "time_fs": 72},
}

# 時刻表示フォーマット（表示名 → strftime書式）
TIME_FORMATS = {
    "HH:MM:SS":     "%H:%M:%S",
    "HH:MM":        "%H:%M",
    "HH時MM分SS秒": "%H時%M分%S秒",
    "HH時MM分":     "%H時%M分",
    "MM:SS":        "%M:%S",
}

DEFAULT_CONFIG = {
    "x": 100, "y": 100,
    "width": 290, "height": 90,
    "topmost": True,
    "transparent_bg": False,
    "show_titlebar": False,
    "font_family": "メイリオ",
    "date_font_size": 16,
    "time_font_size": 32,
    "font_bold": True,
    "font_italic": False,
    "text_color": "#E8F4F8",
    "date_color": "#90B8C8",
    "bg_color": "#0D1B2A",
    "accent_color": "#1E3A4A",
    "size_preset": "小",
    "show_date": True,
    "show_time": True,
    "time_format": "HH:MM:SS",
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                merged = DEFAULT_CONFIG.copy()
                merged.update(json.load(f))
                return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"設定保存エラー: {e}")


class SettingsWindow(tk.Toplevel):
    BG   = "#12121E"
    FG   = "#C9D1E0"
    FG2  = "#7A8899"
    ITEM = "#252538"
    ACC  = "#4A90D9"

    def __init__(self, master, cfg, on_apply):
        super().__init__(master)
        self.cfg = dict(cfg)
        self.on_apply = on_apply
        self.title("設定")
        self.configure(bg=self.BG)
        self.resizable(False, False)
        self.grab_set()
        self.attributes("-topmost", True)
        self._setup_ttk_style()
        self._build()
        self.update_idletasks()
        self.geometry(f"+{master.winfo_x()+20}+{master.winfo_y()+20}")

    def _setup_ttk_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
            fieldbackground=self.ITEM,
            background=self.ITEM,
            foreground=self.FG,
            selectbackground=self.ACC,
            selectforeground="#ffffff",
            arrowcolor=self.FG2,
            bordercolor="#2A2A3E",
            lightcolor="#2A2A3E",
            darkcolor="#2A2A3E",
        )
        style.map("Dark.TCombobox",
            fieldbackground=[("readonly", self.ITEM)],
            foreground=[("readonly", self.FG)],
        )

    def _section(self, text, row):
        tk.Frame(self, bg="#2A2A3E", height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=(12, 0))
        tk.Label(self, text=f"  {text}", bg=self.BG, fg=self.FG2,
                 font=("メイリオ", 9)).grid(row=row+1, column=0, columnspan=2,
                                            sticky="w", padx=14, pady=(2, 4))
        return row + 2

    def _lbl(self, text, row):
        tk.Label(self, text=text, bg=self.BG, fg=self.FG,
                 font=("メイリオ", 10), anchor="w", width=14
                 ).grid(row=row, column=0, sticky="w", padx=(14, 6), pady=4)

    @staticmethod
    def _contrast(hx):
        try:
            r, g, b = int(hx[1:3],16), int(hx[3:5],16), int(hx[5:7],16)
            return "#000000" if (r*299+g*587+b*114)/1000 > 128 else "#ffffff"
        except Exception:
            return "#ffffff"

    def _build(self):
        self.columnconfigure(1, weight=1)
        row = 0

        # 表示設定
        row = self._section("表示設定", row)

        self._lbl("表示項目", row)
        vf = tk.Frame(self, bg=self.BG)
        vf.grid(row=row, column=1, sticky="w", padx=10, pady=4)
        self.show_date_var = tk.BooleanVar(value=self.cfg.get("show_date", True))
        self.show_time_var = tk.BooleanVar(value=self.cfg.get("show_time", True))
        tk.Checkbutton(vf, text="日付", variable=self.show_date_var,
                       command=self._on_show_date_change,
                       bg=self.BG, fg=self.FG, selectcolor=self.ITEM,
                       activebackground=self.BG, font=("メイリオ", 10)
                       ).pack(side="left", padx=4)
        tk.Checkbutton(vf, text="時刻", variable=self.show_time_var,
                       command=self._on_show_time_change,
                       bg=self.BG, fg=self.FG, selectcolor=self.ITEM,
                       activebackground=self.BG, font=("メイリオ", 10)
                       ).pack(side="left", padx=4)
        row += 1

        self._lbl("時刻の形式", row)
        ff = tk.Frame(self, bg=self.BG)
        ff.grid(row=row, column=1, sticky="w", padx=10, pady=4)
        self.time_format_var = tk.StringVar(value=self.cfg.get("time_format", "HH:MM:SS"))
        for name in TIME_FORMATS:
            tk.Radiobutton(ff, text=name, variable=self.time_format_var, value=name,
                           bg=self.BG, fg=self.FG, selectcolor=self.ITEM,
                           activebackground=self.BG, font=("メイリオ", 10)
                           ).pack(side="left", padx=3)
        row += 1

        # フォント
        row = self._section("フォント", row)

        self._lbl("フォント名", row)
        self.font_var = tk.StringVar(value=self.cfg["font_family"])
        font_list = sorted(
            [f for f in tkfont.families() if not f.startswith("@")],
            key=str.lower
        )
        cb = ttk.Combobox(self, textvariable=self.font_var, values=font_list,
                          width=24, style="Dark.TCombobox",
                          font=("メイリオ", 10), state="normal")
        cb.grid(row=row, column=1, sticky="w", padx=10, pady=4)
        row += 1

        self._lbl("フォントサイズ", row)
        f = tk.Frame(self, bg=self.BG)
        f.grid(row=row, column=1, sticky="w", padx=10, pady=4)
        self.date_fs_var = tk.IntVar(value=self.cfg["date_font_size"])
        self.time_fs_var = tk.IntVar(value=self.cfg["time_font_size"])
        for lbl, var in [("日付", self.date_fs_var), ("時刻", self.time_fs_var)]:
            tk.Label(f, text=lbl, bg=self.BG, fg=self.FG2,
                     font=("メイリオ", 9)).pack(side="left")
            tk.Spinbox(f, from_=8, to=200, textvariable=var, width=5,
                       bg=self.ITEM, fg=self.FG, buttonbackground="#1C1C2E",
                       relief="flat", font=("メイリオ", 10)
                       ).pack(side="left", padx=(2, 12))
        row += 1

        self._lbl("スタイル", row)
        f2 = tk.Frame(self, bg=self.BG)
        f2.grid(row=row, column=1, sticky="w", padx=10, pady=4)
        self.bold_var   = tk.BooleanVar(value=self.cfg["font_bold"])
        self.italic_var = tk.BooleanVar(value=self.cfg["font_italic"])
        for text, var in [("太字", self.bold_var), ("斜体", self.italic_var)]:
            tk.Checkbutton(f2, text=text, variable=var,
                           bg=self.BG, fg=self.FG, selectcolor=self.ITEM,
                           activebackground=self.BG, font=("メイリオ", 10)
                           ).pack(side="left", padx=4)
        row += 1

        # カラー
        row = self._section("カラー", row)

        self._date_color = self.cfg["date_color"]
        self._text_color = self.cfg["text_color"]
        self._bg_color   = self.cfg["bg_color"]

        for attr, label, title in [
            ("_date_color", "日付の色",  "日付の文字色"),
            ("_text_color", "時刻の色",  "時刻の文字色"),
            ("_bg_color",   "背景色",    "背景色"),
        ]:
            self._lbl(label, row)
            c = getattr(self, attr)
            btn = tk.Button(self, text=c, width=12, bg=c,
                            fg=self._contrast(c), relief="flat",
                            font=("メイリオ", 9), cursor="hand2")
            btn.grid(row=row, column=1, sticky="w", padx=10, pady=4)

            def make_pick(a=attr, b=btn, t=title):
                def pick():
                    new = colorchooser.askcolor(
                        color=getattr(self, a), title=t, parent=self)[1]
                    if new:
                        setattr(self, a, new)
                        b.config(bg=new, text=new, fg=self._contrast(new))
                return pick
            btn.config(command=make_pick())
            row += 1

        # サイズプリセット
        row = self._section("サイズプリセット", row)

        self._lbl("プリセット", row)
        pf = tk.Frame(self, bg=self.BG)
        pf.grid(row=row, column=1, sticky="w", padx=10, pady=4)
        self.preset_var = tk.StringVar(value=self.cfg.get("size_preset", "小"))
        for name in SIZE_PRESETS:
            tk.Radiobutton(pf, text=name, variable=self.preset_var, value=name,
                           bg=self.BG, fg=self.FG, selectcolor=self.ITEM,
                           activebackground=self.BG, font=("メイリオ", 10)
                           ).pack(side="left", padx=3)
        row += 1

        # ウィンドウ
        row = self._section("ウィンドウ", row)

        self._lbl("オプション", row)
        wf = tk.Frame(self, bg=self.BG)
        wf.grid(row=row, column=1, sticky="w", padx=10, pady=4)
        self.topmost_var  = tk.BooleanVar(value=self.cfg["topmost"])
        self.trans_var    = tk.BooleanVar(value=self.cfg["transparent_bg"])
        self.titlebar_var = tk.BooleanVar(value=self.cfg["show_titlebar"])
        for text, var in [("常に最前面",   self.topmost_var),
                          ("背景透過",     self.trans_var),
                          ("タイトルバー", self.titlebar_var)]:
            tk.Checkbutton(wf, text=text, variable=var,
                           bg=self.BG, fg=self.FG, selectcolor=self.ITEM,
                           activebackground=self.BG, font=("メイリオ", 10)
                           ).pack(side="left", padx=4)
        row += 1

        # ボタン
        tk.Frame(self, bg="#2A2A3E", height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        row += 1
        bf = tk.Frame(self, bg=self.BG)
        bf.grid(row=row, column=0, columnspan=2, pady=14)
        for text, cmd, bg in [("  適用  ", self._apply, self.ACC),
                               ("  キャンセル  ", self.destroy, self.ITEM)]:
            tk.Button(bf, text=text, command=cmd, bg=bg, fg=self.FG,
                      relief="flat", font=("メイリオ", 10), cursor="hand2",
                      activebackground=bg, padx=4, pady=4
                      ).pack(side="left", padx=8)

    def _on_show_date_change(self):
        if not self.show_date_var.get() and not self.show_time_var.get():
            self.show_time_var.set(True)

    def _on_show_time_change(self):
        if not self.show_time_var.get() and not self.show_date_var.get():
            self.show_date_var.set(True)

    def _apply(self):
        p = SIZE_PRESETS[self.preset_var.get()]
        self.cfg.update({
            "show_date":      self.show_date_var.get(),
            "show_time":      self.show_time_var.get(),
            "time_format":    self.time_format_var.get(),
            "font_family":    self.font_var.get(),
            "date_font_size": int(self.date_fs_var.get()),
            "time_font_size": int(self.time_fs_var.get()),
            "font_bold":      self.bold_var.get(),
            "font_italic":    self.italic_var.get(),
            "date_color":     self._date_color,
            "text_color":     self._text_color,
            "bg_color":       self._bg_color,
            "topmost":        self.topmost_var.get(),
            "transparent_bg": self.trans_var.get(),
            "show_titlebar":  self.titlebar_var.get(),
            "size_preset":    self.preset_var.get(),
            "width":          p["width"],
            "height":         p["height"],
        })
        self.on_apply(self.cfg)
        self.destroy()


class ClockApp:
    def __init__(self):
        self._closing = False
        self.cfg = load_config()
        self.root = tk.Tk()
        self._resize_start_x = 0
        self._resize_start_y = 0
        self._resize_start_w = 0
        self._resize_start_h = 0
        self._setup_window()
        self._build_ui()
        self._apply_settings(self.cfg, first_run=True)
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(10, self._set_appwindow)
        self.root.mainloop()

    def _setup_window(self):
        self.root.title("RTokei")
        cfg = self.cfg
        x, y = cfg['x'], cfg['y']
        if not _is_on_any_monitor(x, y, cfg['width'], cfg['height']):
            x, y = 100, 100
        self.root.geometry(f"{cfg['width']}x{cfg['height']}+{x}+{y}")
        self.root.bind("<ButtonPress-1>", self._start_drag)
        self.root.bind("<B1-Motion>",     self._on_drag)

    def _build_ui(self):
        cfg = self.cfg
        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.date_label = tk.Label(
            self.root, text="---- / -- / -- (--)",
            bg=cfg["bg_color"], fg=cfg.get("date_color", "#90B8C8"), anchor="center")

        self.time_label = tk.Label(
            self.root, text="--:--:--",
            bg=cfg["bg_color"], fg=cfg["text_color"], anchor="center")

        self._build_menu()
        self._build_resize_grip()

        for w in (self.root, self.canvas, self.date_label, self.time_label):
            w.bind("<Button-3>",      self._show_menu)
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>",     self._on_drag)

    # メニュー項目インデックス
    _IDX_SHOW_DATE = 3
    _IDX_SHOW_TIME = 4
    _IDX_TOPMOST   = 6
    _IDX_TRANS     = 7
    _IDX_TITLEBAR  = 8

    def _menu_label(self, base, state):
        return base + ("  ✔" if state else "")

    def _build_menu(self):
        M = "#1C1C2E"; FG = "#C9D1E0"; HL = "#2E2E46"
        self.menu = tk.Menu(self.root, tearoff=0,
                            bg=M, fg=FG, activebackground=HL,
                            activeforeground=FG, font=("メイリオ", 10), bd=0)
        self.menu.add_command(label="⚙  設定を開く", command=self._open_settings)  # 0

        self.size_menu = tk.Menu(self.menu, tearoff=0, bg=M, fg=FG,
                     activebackground=HL, activeforeground=FG, font=("メイリオ", 10))
        for name in SIZE_PRESETS:
            self.size_menu.add_command(label=name, command=lambda n=name: self._apply_preset(n))
        self.menu.add_cascade(label="📐  サイズ", menu=self.size_menu)  # 1
        self.menu.add_separator()                                          # 2

        cfg = self.cfg
        self.menu.add_command(
            label=self._menu_label("📅  日付を表示", cfg.get("show_date", True)),
            command=self._toggle_show_date)                                # 3
        self.menu.add_command(
            label=self._menu_label("🕐  時刻を表示", cfg.get("show_time", True)),
            command=self._toggle_show_time)                                # 4
        self.menu.add_separator()                                          # 5

        self.menu.add_command(
            label=self._menu_label("📌  常に最前面", cfg["topmost"]),
            command=self._toggle_topmost)                                  # 6
        self.menu.add_command(
            label=self._menu_label("💧  背景透過", cfg["transparent_bg"]),
            command=self._toggle_transparent)                              # 7
        self.menu.add_command(
            label=self._menu_label("🔲  タイトルバー", cfg.get("show_titlebar", False)),
            command=self._toggle_titlebar)                                 # 8
        self.menu.add_separator()                                          # 9
        self.menu.add_command(label="─  最小化", command=self._minimize)  # 10
        self.menu.add_command(label="✖  終了", command=self._on_close)    # 11

    def _update_size_menu_labels(self):
        current = self.cfg.get("size_preset", "小")
        for i, name in enumerate(SIZE_PRESETS):
            label = name + ("  ✔" if name == current else "")
            self.size_menu.entryconfig(i, label=label)

    def _apply_settings(self, cfg, first_run=False):
        self.cfg = cfg
        self.root.geometry(f"{cfg['width']}x{cfg['height']}")
        self.root.overrideredirect(not cfg.get("show_titlebar", False))
        self.root.attributes("-topmost", cfg["topmost"])

        if cfg["transparent_bg"]:
            try: self.root.attributes("-transparentcolor", cfg["bg_color"])
            except Exception: pass
        else:
            try: self.root.attributes("-transparentcolor", "")
            except Exception: pass

        bg = cfg["bg_color"]
        self.root.configure(bg=bg)
        self.canvas.configure(bg=bg)
        self.date_label.configure(bg=bg, fg=cfg.get("date_color", "#90B8C8"))
        self.time_label.configure(bg=bg, fg=cfg["text_color"])

        weight = "bold"   if cfg["font_bold"]   else "normal"
        slant  = "italic" if cfg["font_italic"]  else "roman"
        fam    = cfg["font_family"]

        try:
            self.date_label.configure(
                font=tkfont.Font(family=fam, size=cfg["date_font_size"],
                                 weight=weight, slant=slant))
        except Exception:
            self.date_label.configure(font=("TkDefaultFont", cfg["date_font_size"]))
        try:
            self.time_label.configure(
                font=tkfont.Font(family=fam, size=cfg["time_font_size"],
                                 weight=weight, slant=slant))
        except Exception:
            self.time_label.configure(font=("TkDefaultFont", cfg["time_font_size"]))

        self.menu.entryconfig(self._IDX_SHOW_DATE, label=self._menu_label("📅  日付を表示", cfg.get("show_date", True)))
        self.menu.entryconfig(self._IDX_SHOW_TIME, label=self._menu_label("🕐  時刻を表示", cfg.get("show_time", True)))
        self.menu.entryconfig(self._IDX_TOPMOST,   label=self._menu_label("📌  常に最前面", cfg["topmost"]))
        self.menu.entryconfig(self._IDX_TRANS,     label=self._menu_label("💧  背景透過", cfg["transparent_bg"]))
        self.menu.entryconfig(self._IDX_TITLEBAR,  label=self._menu_label("🔲  タイトルバー", cfg.get("show_titlebar", False)))

        self._relayout()
        self._update_size_menu_labels()
        save_config(cfg)

    def _relayout(self):
        w = self.cfg["width"]
        h = self.cfg["height"]
        self.canvas.place(x=0, y=0, width=w, height=h)
        self.canvas.delete("sep")
        show_date = self.cfg.get("show_date", True)
        show_time = self.cfg.get("show_time", True)
        if show_date and show_time:
            mid = h * 0.52
            self.canvas.create_line(w*0.06, mid, w*0.94, mid,
                                    fill=self.cfg.get("accent_color", "#1E3A4A"),
                                    width=1, tags="sep")
            self.date_label.place(relx=0.5, rely=0.27, anchor="center", width=w-16)
            self.time_label.place(relx=0.5, rely=0.73, anchor="center", width=w-16)
        elif show_date:
            self.date_label.place(relx=0.5, rely=0.5, anchor="center", width=w-16)
            self.time_label.place_forget()
        else:
            self.time_label.place(relx=0.5, rely=0.5, anchor="center", width=w-16)
            self.date_label.place_forget()

    def _apply_preset(self, name):
        p = SIZE_PRESETS[name]
        self.cfg.update({
            "size_preset": name, "width": p["width"], "height": p["height"],
            "date_font_size": p["date_fs"], "time_font_size": p["time_fs"],
        })
        self._apply_settings(self.cfg)

    def _toggle_show_date(self):
        new_val = not self.cfg.get("show_date", True)
        if not new_val and not self.cfg.get("show_time", True):
            return  # 両方非表示にはできない
        self.cfg["show_date"] = new_val
        self.menu.entryconfig(self._IDX_SHOW_DATE, label=self._menu_label("📅  日付を表示", new_val))
        self._relayout()
        save_config(self.cfg)

    def _toggle_show_time(self):
        new_val = not self.cfg.get("show_time", True)
        if not new_val and not self.cfg.get("show_date", True):
            return  # 両方非表示にはできない
        self.cfg["show_time"] = new_val
        self.menu.entryconfig(self._IDX_SHOW_TIME, label=self._menu_label("🕐  時刻を表示", new_val))
        self._relayout()
        save_config(self.cfg)

    def _toggle_topmost(self):
        self.cfg["topmost"] = not self.cfg["topmost"]
        self.root.attributes("-topmost", self.cfg["topmost"])
        if self.cfg["topmost"]:
            self.root.lift()
            self.root.after(50, lambda: self.root.attributes("-topmost", True))
        self.menu.entryconfig(self._IDX_TOPMOST, label=self._menu_label("📌  常に最前面", self.cfg["topmost"]))
        save_config(self.cfg)

    def _toggle_transparent(self):
        self.cfg["transparent_bg"] = not self.cfg["transparent_bg"]
        if self.cfg["transparent_bg"]:
            try: self.root.attributes("-transparentcolor", self.cfg["bg_color"])
            except Exception: pass
        else:
            try: self.root.attributes("-transparentcolor", "")
            except Exception: pass
        self.menu.entryconfig(self._IDX_TRANS, label=self._menu_label("💧  背景透過", self.cfg["transparent_bg"]))
        save_config(self.cfg)

    def _toggle_titlebar(self):
        self.cfg["show_titlebar"] = not self.cfg.get("show_titlebar", False)
        self.root.overrideredirect(not self.cfg["show_titlebar"])
        if not self.cfg["show_titlebar"]:
            self.root.after(10, self._set_appwindow)
        self.root.after(100, lambda: self.root.attributes("-topmost", self.cfg["topmost"]))
        self.menu.entryconfig(self._IDX_TITLEBAR, label=self._menu_label("🔲  タイトルバー", self.cfg["show_titlebar"]))
        save_config(self.cfg)

    def _open_settings(self, event=None):
        SettingsWindow(self.root, self.cfg, self._apply_settings)

    def _show_menu(self, event):
        if self._closing:
            return
        x, y = event.x_root, event.y_root
        self.root.focus_force()
        self.root.after(1, lambda: self._popup_menu(x, y))

    def _popup_menu(self, x, y):
        try:
            self.menu.tk_popup(x, y)
        except Exception:
            pass

    def _tick(self):
        now = datetime.datetime.now()
        if self.cfg.get("show_date", True):
            wd = WEEKDAYS[now.weekday()]
            self.date_label.configure(text=now.strftime(f"%Y/%m/%d（{wd}）"))
        if self.cfg.get("show_time", True):
            fmt_key = self.cfg.get("time_format", "HH:MM:SS")
            fmt = TIME_FORMATS.get(fmt_key, "%H:%M:%S")
            self.time_label.configure(text=now.strftime(fmt))
        ms = 1000 - now.microsecond // 1000
        self._tick_id = self.root.after(ms, self._tick)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y
        self.root.bind("<ButtonRelease-1>", self._on_drag_end)

    def _on_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _on_drag_end(self, event):
        """ドロップ時にモニター端へスナップ（吸着距離 20px）"""
        SNAP = 20

        win_x = self.root.winfo_x()
        win_y = self.root.winfo_y()
        win_w = self.root.winfo_width()
        win_h = self.root.winfo_height()

        try:
            import ctypes.wintypes
            SM_XVIRTUALSCREEN  = 76
            SM_YVIRTUALSCREEN  = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79

            class RECT(ctypes.Structure):
                _fields_ = [("left",   ctypes.c_long), ("top",    ctypes.c_long),
                             ("right",  ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize",    ctypes.c_ulong),
                             ("rcMonitor", RECT), ("rcWork", RECT),
                             ("dwFlags",   ctypes.c_ulong)]

            cx = win_x + win_w // 2
            cy = win_y + win_h // 2
            MONITOR_DEFAULTTONEAREST = 2
            pt = ctypes.wintypes.POINT(cx, cy)
            hmon = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)

            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))

            scr_x = mi.rcWork.left
            scr_y = mi.rcWork.top
            scr_r = mi.rcWork.right
            scr_b = mi.rcWork.bottom

        except Exception:
            scr_x, scr_y = 0, 0
            scr_r = self.root.winfo_screenwidth()
            scr_b = self.root.winfo_screenheight()

        snap_x, snap_y = win_x, win_y

        # 左端・右端
        if abs(win_x - scr_x) <= SNAP:
            snap_x = scr_x
        elif abs((win_x + win_w) - scr_r) <= SNAP:
            snap_x = scr_r - win_w

        # 上端・下端
        if abs(win_y - scr_y) <= SNAP:
            snap_y = scr_y
        elif abs((win_y + win_h) - scr_b) <= SNAP:
            snap_y = scr_b - win_h

        if snap_x != win_x or snap_y != win_y:
            self.root.geometry(f"+{snap_x}+{snap_y}")

    def _set_appwindow(self):
        """overrideredirect 時も Alt+Tab に表示されるようスタイルを修正"""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _build_resize_grip(self):
        grip = tk.Canvas(self.root, width=16, height=16,
                         bg=self.cfg["bg_color"], highlightthickness=0,
                         cursor="size_nw_se")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        for i in range(3):
            offset = 4 + i * 4
            grip.create_line(16, offset, offset, 16, fill="#334455", width=1)
        grip.bind("<ButtonPress-1>", self._resize_start)
        grip.bind("<B1-Motion>",     self._resize_move)
        self._grip = grip

    def _resize_start(self, event):
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_start_w = self.root.winfo_width()
        self._resize_start_h = self.root.winfo_height()

    def _resize_move(self, event):
        dw = event.x_root - self._resize_start_x
        dh = event.y_root - self._resize_start_y
        new_w = max(MIN_W, self._resize_start_w + dw)
        new_h = max(MIN_H, self._resize_start_h + dh)
        self.cfg["width"]  = new_w
        self.cfg["height"] = new_h
        self.root.geometry(f"{new_w}x{new_h}")
        self._relayout()

    def _minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()

        def on_restore(event):
            self.root.overrideredirect(not self.cfg.get("show_titlebar", False))
            self.root.after(10, self._set_appwindow)
            self.root.unbind("<Map>")

        self.root.bind("<Map>", on_restore)

    def _on_close(self):
        self._closing = True
        if hasattr(self, "_tick_id"):
            self.root.after_cancel(self._tick_id)
        self.cfg["x"] = self.root.winfo_x()
        self.cfg["y"] = self.root.winfo_y()
        self.cfg["width"]  = self.root.winfo_width()
        self.cfg["height"] = self.root.winfo_height()
        save_config(self.cfg)
        try:
            self.menu.unpost()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    ClockApp()
