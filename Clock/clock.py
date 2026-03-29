"""
デジタル時計アプリ
  - 1段目: 日付 + 曜日
  - 2段目: 時刻 (HH:MM:SS)
  - 右クリックメニューで各種設定
  - 設定は clock_settings.json に自動保存
"""

import tkinter as tk
from tkinter import font as tkfont, colorchooser
import json, os, sys, datetime, ctypes

# ─── パス設定 ───────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "clock_settings.json")

WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

SIZE_PRESETS = {
    "極小": {"width": 220, "height": 70,  "date_fs": 13, "time_fs": 24},
    "小":   {"width": 290, "height": 90,  "date_fs": 16, "time_fs": 32},
    "中":   {"width": 360, "height": 112, "date_fs": 20, "time_fs": 40},
    "大":   {"width": 480, "height": 148, "date_fs": 26, "time_fs": 54},
    "極大": {"width": 640, "height": 196, "date_fs": 34, "time_fs": 72},
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
        self._build()
        self.update_idletasks()
        self.geometry(f"+{master.winfo_x()+20}+{master.winfo_y()+20}")

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

        # フォント
        row = self._section("フォント", row)

        self._lbl("フォント名", row)
        self.font_var = tk.StringVar(value=self.cfg["font_family"])
        tk.Entry(self, textvariable=self.font_var, width=22,
                 bg=self.ITEM, fg=self.FG, insertbackground=self.FG,
                 relief="flat", font=("メイリオ", 10), bd=4
                 ).grid(row=row, column=1, sticky="w", padx=10, pady=4)
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

    def _apply(self):
        p = SIZE_PRESETS[self.preset_var.get()]
        self.cfg.update({
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
        self.cfg = load_config()
        self.root = tk.Tk()
        self._setup_window()
        self._build_ui()
        self._apply_settings(self.cfg, first_run=True)
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _setup_window(self):
        self.root.title("時計")
        cfg = self.cfg
        self.root.geometry(f"{cfg['width']}x{cfg['height']}+{cfg['x']}+{cfg['y']}")
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

        for w in (self.root, self.canvas, self.date_label, self.time_label):
            w.bind("<Button-3>",      self._show_menu)
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>",     self._on_drag)

    def _build_menu(self):
        M = "#1C1C2E"; FG = "#C9D1E0"; HL = "#2E2E46"
        self.menu = tk.Menu(self.root, tearoff=0,
                            bg=M, fg=FG, activebackground=HL,
                            activeforeground=FG, font=("メイリオ", 10), bd=0)
        self.menu.add_command(label="⚙  設定を開く", command=self._open_settings)

        pm = tk.Menu(self.menu, tearoff=0, bg=M, fg=FG,
                     activebackground=HL, activeforeground=FG, font=("メイリオ", 10))
        for name in SIZE_PRESETS:
            pm.add_command(label=name, command=lambda n=name: self._apply_preset(n))
        self.menu.add_cascade(label="📐  サイズ", menu=pm)
        self.menu.add_separator()

        self.topmost_var  = tk.BooleanVar(value=self.cfg["topmost"])
        self.trans_var    = tk.BooleanVar(value=self.cfg["transparent_bg"])
        self.titlebar_var = tk.BooleanVar(value=self.cfg["show_titlebar"])

        self.menu.add_checkbutton(label="📌  常に最前面",
                                  variable=self.topmost_var,  command=self._toggle_topmost)
        self.menu.add_checkbutton(label="💧  背景透過",
                                  variable=self.trans_var,    command=self._toggle_transparent)
        self.menu.add_checkbutton(label="🔲  タイトルバー",
                                  variable=self.titlebar_var, command=self._toggle_titlebar)
        self.menu.add_separator()
        self.menu.add_command(label="✖  終了", command=self._on_close)

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

        self.topmost_var.set(cfg["topmost"])
        self.trans_var.set(cfg["transparent_bg"])
        self.titlebar_var.set(cfg.get("show_titlebar", False))

        self._relayout()
        save_config(cfg)

    def _relayout(self):
        w = self.cfg["width"]
        h = self.cfg["height"]
        self.canvas.place(x=0, y=0, width=w, height=h)
        mid = h * 0.52
        self.canvas.delete("sep")
        self.canvas.create_line(w*0.06, mid, w*0.94, mid,
                                fill=self.cfg.get("accent_color", "#1E3A4A"),
                                width=1, tags="sep")
        self.date_label.place(relx=0.5, rely=0.27, anchor="center", width=w-16)
        self.time_label.place(relx=0.5, rely=0.73, anchor="center", width=w-16)

    def _apply_preset(self, name):
        p = SIZE_PRESETS[name]
        self.cfg.update({
            "size_preset": name, "width": p["width"], "height": p["height"],
            "date_font_size": p["date_fs"], "time_font_size": p["time_fs"],
        })
        self._apply_settings(self.cfg)

    def _toggle_topmost(self):
        self.cfg["topmost"] = self.topmost_var.get()
        self.root.attributes("-topmost", self.cfg["topmost"])
        if self.cfg["topmost"]:
            self.root.lift()
            self.root.after(50, lambda: self.root.attributes("-topmost", True))
        save_config(self.cfg)

    def _toggle_transparent(self):
        self.cfg["transparent_bg"] = self.trans_var.get()
        if self.cfg["transparent_bg"]:
            try: self.root.attributes("-transparentcolor", self.cfg["bg_color"])
            except Exception: pass
        else:
            try: self.root.attributes("-transparentcolor", "")
            except Exception: pass
        save_config(self.cfg)

    def _toggle_titlebar(self):
        self.cfg["show_titlebar"] = self.titlebar_var.get()
        self.root.overrideredirect(not self.cfg["show_titlebar"])
        self.root.after(100, lambda: self.root.attributes("-topmost", self.cfg["topmost"]))
        save_config(self.cfg)

    def _open_settings(self, event=None):
        SettingsWindow(self.root, self.cfg, self._apply_settings)

    def _show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def _tick(self):
        now = datetime.datetime.now()
        wd  = WEEKDAYS[now.weekday()]
        self.date_label.configure(text=now.strftime(f"%Y/%m/%d（{wd}）"))
        self.time_label.configure(text=now.strftime("%H:%M:%S"))
        ms = 1000 - now.microsecond // 1000
        self.root.after(ms, self._tick)

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

    def _on_close(self):
        self.cfg["x"] = self.root.winfo_x()
        self.cfg["y"] = self.root.winfo_y()
        self.cfg["width"]  = self.root.winfo_width()
        self.cfg["height"] = self.root.winfo_height()
        save_config(self.cfg)
        self.root.destroy()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    ClockApp()
