"""
RCommentHub — 詳細/管理ウィンドウ（補助画面）

コメント一覧・詳細パネル・フィルタ管理・ログエリアを提供する管理用サブウィンドウ。
コメントビュー（CommentWindow）が主画面であり、本ウィンドウは補助的な管理画面。
"""

import ctypes
import ctypes.wintypes
import datetime
import json
import re
import tkinter as tk
from tkinter import ttk, scrolledtext

from constants import (
    DEFAULT_WIDTH, DEFAULT_HEIGHT, MIN_WIDTH, MIN_HEIGHT,
    FILTER_TYPE_GROUPS, PROC_STATUS_LABELS,
    CONN_STATUS_LABELS, CONN_STATUS_COLORS, STREAM_STATUS_LABELS,
    LIST_COLUMNS, ROW_COLORS, UI_COLORS,
    FONT_FAMILY, FONT_SIZE_S, FONT_SIZE_M, FONT_SIZE_L, FONT_SIZE_LOG,
)

GWL_EXSTYLE      = -20
WS_EX_APPWINDOW  = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080


def _is_on_any_monitor(x, y, w=1, h=1):
    try:
        MONITOR_DEFAULTTONULL = 0
        pt = ctypes.wintypes.POINT(x + w // 2, y + h // 2)
        return ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONULL) != 0
    except Exception:
        return True


class DetailWindow:
    """
    詳細/管理ウィンドウ（補助画面）。
    CommentController からコールバックで更新を受け取る。
    X ボタンで閉じても非表示になるだけでアプリは終了しない。
    """

    def __init__(self, root: tk.Tk, controller, settings_mgr, cfg: dict,
                 comment_window_getter=None,
                 open_connect_cb=None,
                 open_settings_cb=None,
                 debug_win_opener=None):
        self._root               = root
        self._ctrl               = controller
        self._sm                 = settings_mgr
        self.cfg                 = cfg
        self._get_comment_window = comment_window_getter or (lambda: None)
        self._open_connect       = open_connect_cb  or (lambda: None)
        self._open_settings      = open_settings_cb or (lambda: None)
        self._debug_win_opener   = debug_win_opener or (lambda: None)
        self._appwindow_set      = False

        # Toplevel 作成（起動直後は非表示）
        self._win = tk.Toplevel(root)
        self._win.withdraw()
        self._setup_window()
        self._build_ui()
        self._apply_row_tags()
        self._load_sash_positions()

        self._win.protocol("WM_DELETE_WINDOW", self._win.withdraw)
        self._win.bind("<Configure>", self._on_configure)

        # コントローラからの通知を受け取るコールバックを登録
        controller.on_comment_added(self._on_comment_added)
        controller.on_conn_status(self._on_conn_status_changed)
        controller.on_stream_info(self._on_stream_info_changed)
        controller.on_log_message(self._log)
        controller.on_connect_ui(self._on_connect_ui_update)
        controller.on_debug_mode(self._on_debug_mode_changed)

    def open(self):
        """詳細ウィンドウを前面表示する"""
        try:
            self._win.deiconify()
            self._win.lift()
            self._win.focus_force()
            if not self._appwindow_set:
                self._win.after(50, self._set_appwindow)
        except tk.TclError:
            pass

    def _set_appwindow(self):
        self._appwindow_set = True
        try:
            hwnd  = ctypes.windll.user32.GetParent(self._win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    # --- ウィンドウ設定 ---

    def _setup_window(self):
        self._win.title("RCommentHub — 詳細")
        x = self.cfg.get("x", 100)
        y = self.cfg.get("y", 100)
        w = self.cfg.get("width",  DEFAULT_WIDTH)
        h = self.cfg.get("height", DEFAULT_HEIGHT)
        if not _is_on_any_monitor(x, y, w, h):
            x, y = 100, 100
        self._win.geometry(f"{w}x{h}+{x}+{y}")
        self._win.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._win.configure(bg=UI_COLORS["bg_main"])
        self._setup_style()

    def _setup_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        bg  = UI_COLORS["bg_list"]
        fg  = UI_COLORS["fg_main"]
        acc = UI_COLORS["accent"]
        s.configure("Treeview", background=bg, foreground=fg,
                     fieldbackground=bg, rowheight=22, font=(FONT_FAMILY, FONT_SIZE_S))
        s.configure("Treeview.Heading", background=UI_COLORS["bg_header"],
                     foreground=UI_COLORS["fg_header"], font=(FONT_FAMILY, FONT_SIZE_S, "bold"))
        s.map("Treeview", background=[("selected", acc)], foreground=[("selected", "#FFFFFF")])
        s.configure("Vertical.TScrollbar",   background=UI_COLORS["bg_panel"],
                     troughcolor=UI_COLORS["bg_main"], arrowcolor=UI_COLORS["fg_label"])
        s.configure("Horizontal.TScrollbar", background=UI_COLORS["bg_panel"],
                     troughcolor=UI_COLORS["bg_main"], arrowcolor=UI_COLORS["fg_label"])
        s.configure("TPanedwindow", background=UI_COLORS["border"])
        s.configure("TCheckbutton", background=UI_COLORS["bg_panel"],
                     foreground=UI_COLORS["fg_main"], font=(FONT_FAMILY, FONT_SIZE_S))
        s.map("TCheckbutton",
              background=[("active", UI_COLORS["bg_panel"])],
              foreground=[("active", UI_COLORS["fg_main"])])
        s.configure("TCombobox", fieldbackground=UI_COLORS["bg_panel"],
                     background=UI_COLORS["bg_panel"], foreground=UI_COLORS["fg_main"],
                     selectbackground=acc, font=(FONT_FAMILY, FONT_SIZE_S))
        s.map("TCombobox",
              fieldbackground=[("readonly", UI_COLORS["bg_panel"]),
                               ("disabled", UI_COLORS["bg_panel"])],
              foreground=[("readonly", UI_COLORS["fg_main"]),
                          ("disabled", UI_COLORS["fg_label"])],
              selectbackground=[("readonly", UI_COLORS["accent"])],
              selectforeground=[("readonly", "#FFFFFF")])

    # --- UI 構築 ---

    def _build_ui(self):
        self._paned_main = tk.PanedWindow(
            self._win, orient=tk.VERTICAL,
            bg=UI_COLORS["border"], sashwidth=4, sashrelief=tk.FLAT
        )
        self._paned_main.pack(fill=tk.BOTH, expand=True)

        top_frame = tk.Frame(self._paned_main, bg=UI_COLORS["bg_main"])
        self._paned_main.add(top_frame, minsize=300)

        log_frame = self._build_log_area(self._paned_main)
        self._paned_main.add(log_frame, minsize=60)

        self._paned_h = tk.PanedWindow(
            top_frame, orient=tk.HORIZONTAL,
            bg=UI_COLORS["border"], sashwidth=4, sashrelief=tk.FLAT
        )
        self._paned_h.pack(fill=tk.BOTH, expand=True)

        header   = self._build_header(top_frame)
        header.pack(fill=tk.X, side=tk.TOP)
        conn_bar = self._build_conn_bar(top_frame)
        conn_bar.pack(fill=tk.X, side=tk.TOP)

        filter_frame = self._build_filter_area(self._paned_h)
        list_frame   = self._build_list_area(self._paned_h)
        detail_frame = self._build_detail_area(self._paned_h)

        self._paned_h.add(filter_frame, minsize=160)
        self._paned_h.add(list_frame,   minsize=300)
        self._paned_h.add(detail_frame, minsize=200)

    # ── ヘッダー ─────────────────────────────────────────────────────────────

    def _build_header(self, parent) -> tk.Frame:
        C = UI_COLORS
        frame = tk.Frame(parent, bg=C["bg_header"], padx=8, pady=4)

        lf = tk.Frame(frame, bg=C["bg_header"])
        lf.pack(side=tk.LEFT)

        self._lbl_conn = tk.Label(
            lf, text="■ 未接続",
            font=(FONT_FAMILY, FONT_SIZE_M, "bold"),
            fg=CONN_STATUS_COLORS["disconnected"], bg=C["bg_header"]
        )
        self._lbl_conn.pack(side=tk.LEFT, padx=(0, 12))

        self._lbl_stream = tk.Label(
            lf, text="",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_header"]
        )
        self._lbl_stream.pack(side=tk.LEFT)

        mf = tk.Frame(frame, bg=C["bg_header"])
        mf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12)

        self._lbl_title = tk.Label(
            mf, text="— 配信なし —",
            font=(FONT_FAMILY, FONT_SIZE_L, "bold"),
            fg=C["fg_header"], bg=C["bg_header"]
        )
        self._lbl_title.pack(side=tk.TOP, anchor=tk.W)

        sub_frame = tk.Frame(mf, bg=C["bg_header"])
        sub_frame.pack(side=tk.TOP, anchor=tk.W)
        for attr, label in [("_lbl_video_id", "動画ID:"), ("_lbl_chat_id", "chatID:")]:
            tk.Label(sub_frame, text=label,
                     font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_header"]).pack(side=tk.LEFT)
            lbl = tk.Label(sub_frame, text="—",
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_header"])
            lbl.pack(side=tk.LEFT, padx=(0, 12))
            setattr(self, attr, lbl)

        rf = tk.Frame(frame, bg=C["bg_header"])
        rf.pack(side=tk.RIGHT)

        for attr, label in [
            ("_lbl_total",    "総受信:"),
            ("_lbl_shown",    "表示中:"),
            ("_lbl_lastrecv", "最終受信:"),
        ]:
            tk.Label(rf, text=label,
                     font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_header"]).pack(side=tk.LEFT)
            lbl = tk.Label(rf, text="—",
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_header"])
            lbl.pack(side=tk.LEFT, padx=(0, 10))
            setattr(self, attr, lbl)

        # 設定ボタン
        tk.Button(
            rf, text="⚙ 設定",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["bg_list"], fg=C["fg_label"],
            relief=tk.FLAT, padx=8, pady=2,
            command=self._open_settings,
        ).pack(side=tk.LEFT, padx=(4, 0))

        # コメントビューボタン
        self._btn_comment_view = tk.Button(
            rf, text="💬 コメントビュー",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#2A3A2A", fg="#80FF80", activebackground="#3A5A3A",
            relief=tk.FLAT, padx=8, pady=2,
            command=self._open_comment_window_btn,
        )
        self._btn_comment_view.pack(side=tk.LEFT, padx=(4, 0))

        return frame

    # ── 接続バー ──────────────────────────────────────────────────────────────

    def _build_conn_bar(self, parent) -> tk.Frame:
        C = UI_COLORS
        frame = tk.Frame(parent, bg=C["bg_panel"], padx=8, pady=4)

        # 接続ボタン
        self._btn_connect = tk.Button(
            frame, text="▶ 接続",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#2A4A2A", fg="#AAFFAA", activebackground="#3A6A3A",
            relief=tk.FLAT, padx=10, pady=2,
            command=self._open_connect,
        )
        self._btn_connect.pack(side=tk.LEFT, padx=(0, 4))

        # 停止ボタン
        self._btn_stop = tk.Button(
            frame, text="■ 停止",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#5A2A2A", fg="#FFFFFF", activebackground="#8A3A3A",
            relief=tk.FLAT, padx=10, pady=2,
            state=tk.DISABLED,
            command=self._ctrl.disconnect,
        )
        self._btn_stop.pack(side=tk.LEFT, padx=(0, 4))

        # 状態ラベル
        self._lbl_conn_detail = tk.Label(
            frame, text="",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_panel"]
        )
        self._lbl_conn_detail.pack(side=tk.LEFT, padx=(8, 0))

        # デバッグモードトグルボタン
        self._btn_debug = tk.Button(
            frame, text="🐛 DEBUG OFF",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["bg_list"], fg="#666666",
            activebackground="#2A2A2A",
            relief=tk.FLAT, padx=8, pady=2,
            command=self._ctrl.toggle_debug_mode,
        )
        self._btn_debug.pack(side=tk.RIGHT, padx=(0, 0))

        return frame

    # ── フィルタエリア（管理補助パネル）─────────────────────────────────────

    def _build_filter_area(self, parent) -> tk.Frame:
        C = UI_COLORS
        outer = tk.Frame(parent, bg=C["bg_panel"], bd=0)

        tk.Label(outer, text="フィルタ / 管理",
                 font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                 fg=C["fg_label"], bg=C["bg_panel"]
                 ).pack(anchor=tk.W, padx=6, pady=(6, 2))

        canvas = tk.Canvas(outer, bg=C["bg_panel"], highlightthickness=0)
        vsb    = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner       = tk.Frame(canvas, bg=C["bg_panel"])
        canvas_win  = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_win, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        def section(label):
            tk.Label(inner, text=label,
                     font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                     fg=C["fg_label"], bg=C["bg_panel"]
                     ).pack(anchor=tk.W, padx=6, pady=(8, 2))
            tk.Frame(inner, bg=C["border"], height=1).pack(fill=tk.X, padx=6)

        # 種別フィルタ（一覧表示用）
        self._filter_vars: dict = {}
        section("種別")
        for label in FILTER_TYPE_GROUPS:
            var = tk.BooleanVar(value=True)
            self._filter_vars[label] = var
            ttk.Checkbutton(inner, text=label, variable=var,
                            command=self._on_filter_changed
                            ).pack(anchor=tk.W, padx=10)

        # 投稿者属性フィルタ
        self._filter_roles: dict = {}
        section("投稿者属性")
        for label in ["配信者のみ", "モデレーターのみ", "メンバーのみ", "認証済みのみ"]:
            var = tk.BooleanVar(value=False)
            self._filter_roles[label] = var
            ttk.Checkbutton(inner, text=label, variable=var,
                            command=self._on_filter_changed
                            ).pack(anchor=tk.W, padx=10)

        # 文字列フィルタ
        self._filter_text_var = tk.StringVar()
        self._filter_mode_var = tk.StringVar(value="部分一致")
        section("文字列")
        tk.Entry(inner, textvariable=self._filter_text_var,
                 bg=C["bg_list"], fg=C["fg_main"],
                 insertbackground=C["fg_main"],
                 relief=tk.FLAT, font=(FONT_FAMILY, FONT_SIZE_S)
                 ).pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Combobox(inner, textvariable=self._filter_mode_var,
                     values=["部分一致", "完全一致", "前方一致", "後方一致", "正規表現"],
                     state="readonly", font=(FONT_FAMILY, FONT_SIZE_S)
                     ).pack(fill=tk.X, padx=6, pady=(0, 2))
        self._filter_text_var.trace_add("write", lambda *_: self._on_filter_changed())

        tk.Button(inner, text="絞り込み適用",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["accent"], fg="#FFFFFF", relief=tk.FLAT, pady=2,
                  command=self._apply_filter
                  ).pack(fill=tk.X, padx=6, pady=(2, 0))
        tk.Button(inner, text="フィルタ解除",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_label"], relief=tk.FLAT, pady=2,
                  command=self._clear_filter
                  ).pack(fill=tk.X, padx=6, pady=(2, 0))

        # 状態フィルタ
        self._filter_status_vars: dict = {}
        section("状態")
        for key, label in PROC_STATUS_LABELS.items():
            var = tk.BooleanVar(value=True)
            self._filter_status_vars[key] = var
            ttk.Checkbutton(inner, text=label, variable=var,
                            command=self._on_filter_changed
                            ).pack(anchor=tk.W, padx=10)

        # 読み上げフィルタ
        self._filter_tts_only_var = tk.BooleanVar(value=False)
        section("読み上げ")
        ttk.Checkbutton(inner, text="読み上げ対象のみ",
                        variable=self._filter_tts_only_var,
                        command=self._on_filter_changed
                        ).pack(anchor=tk.W, padx=10)

        # フィルタルール情報
        section("フィルタルール")
        self._lbl_rule_count = tk.Label(
            inner, text=f"ルール: {len(self._ctrl.filter_mgr.rules)}件",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_panel"])
        self._lbl_rule_count.pack(anchor=tk.W, padx=10)
        tk.Button(inner, text="コメントビューで編集",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_label"], relief=tk.FLAT, pady=2,
                  command=self._open_comment_window_filter_tab
                  ).pack(fill=tk.X, padx=6, pady=(2, 0))

        return outer

    # ── コメント一覧 ──────────────────────────────────────────────────────────

    def _build_list_area(self, parent) -> tk.Frame:
        C = UI_COLORS
        frame = tk.Frame(parent, bg=C["bg_list"])
        tk.Label(frame, text="コメント一覧（全件）",
                 font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                 fg=C["fg_label"], bg=C["bg_list"]
                 ).pack(anchor=tk.W, padx=6, pady=(4, 0))

        tree_frame = tk.Frame(frame, bg=C["bg_list"])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        cols = [c[0] for c in LIST_COLUMNS]
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                   selectmode="browse")
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)

        for col_id, heading, width, stretch in LIST_COLUMNS:
            self._tree.heading(col_id, text=heading,
                               command=lambda c=col_id: self._on_sort(c))
            self._tree.column(col_id, width=width, minwidth=40, stretch=stretch)

        self._tree.bind("<<TreeviewSelect>>", self._on_comment_select)
        self._tree.bind("<Button-3>", self._on_list_right_click)
        return frame

    def _apply_row_tags(self):
        for tag, colors in ROW_COLORS.items():
            self._tree.tag_configure(tag,
                                     background=colors["bg"],
                                     foreground=colors["fg"])

    # ── 詳細ペイン ─────────────────────────────────────────────────────────

    def _build_detail_area(self, parent) -> tk.Frame:
        C = UI_COLORS
        outer = tk.Frame(parent, bg=C["bg_detail"])
        tk.Label(outer, text="詳細",
                 font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                 fg=C["fg_label"], bg=C["bg_detail"]
                 ).pack(anchor=tk.W, padx=6, pady=(4, 0))
        self._detail_text = scrolledtext.ScrolledText(
            outer, bg=C["bg_detail"], fg=C["fg_main"],
            insertbackground=C["fg_main"],
            font=(FONT_FAMILY, FONT_SIZE_S),
            relief=tk.FLAT, state=tk.DISABLED,
            wrap=tk.WORD, padx=6, pady=4
        )
        self._detail_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._detail_text.tag_configure("section",
                                         font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                                         foreground="#8888FF")
        self._detail_text.tag_configure("key",   foreground="#88AACC")
        self._detail_text.tag_configure("value", foreground=C["fg_main"])
        self._detail_text.tag_configure("raw",
                                         font=("Courier New", FONT_SIZE_S),
                                         foreground="#AAAAAA")
        return outer

    # ── ログエリア ────────────────────────────────────────────────────────────

    def _build_log_area(self, parent) -> tk.Frame:
        C = UI_COLORS
        frame = tk.Frame(parent, bg=C["bg_log"])
        tk.Label(frame, text="ログ",
                 font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                 fg=C["fg_label"], bg=C["bg_log"]
                 ).pack(anchor=tk.W, padx=6, pady=(2, 0))
        self._log_text = scrolledtext.ScrolledText(
            frame, bg=C["bg_log"], fg="#AAAAAA",
            insertbackground="#AAAAAA",
            font=("Courier New", FONT_SIZE_LOG),
            relief=tk.FLAT, state=tk.DISABLED,
            wrap=tk.WORD, height=5
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        return frame

    # ─── コントローラ コールバックハンドラ ───────────────────────────────────

    def _on_comment_added(self, item):
        self._insert_tree_row(item)
        self._update_header_stats()

    def _on_conn_status_changed(self, status: str):
        label = CONN_STATUS_LABELS.get(status, status)
        color = CONN_STATUS_COLORS.get(status, "#888888")
        self._lbl_conn.config(text=f"■ {label}", fg=color)

    def _on_stream_info_changed(self, title, video_id, chat_id, stream_status):
        self._lbl_title.config(text=title or "— 配信なし —")
        self._lbl_video_id.config(text=video_id or "—")
        self._lbl_chat_id.config(text=chat_id or "—")
        self._lbl_stream.config(text=STREAM_STATUS_LABELS.get(stream_status, stream_status))

    def _on_connect_ui_update(self, conn_enabled, stop_enabled, msg, fg):
        if conn_enabled is not None:
            self._btn_connect.config(state=tk.NORMAL if conn_enabled else tk.DISABLED)
        if stop_enabled is not None:
            self._btn_stop.config(state=tk.NORMAL if stop_enabled else tk.DISABLED)
        if msg is not None:
            self._lbl_conn_detail.config(text=msg)
        if fg is not None:
            self._lbl_conn_detail.config(fg=fg)

    def _on_debug_mode_changed(self, debug_mode: bool, open_sender: bool):
        try:
            if debug_mode:
                self._btn_debug.config(text="🐛 DEBUG ON", bg="#3A2A00", fg="#FF8C00",
                                       activebackground="#5A3A00")
            else:
                self._btn_debug.config(text="🐛 DEBUG OFF", bg=UI_COLORS["bg_list"],
                                       fg="#666666", activebackground="#2A2A2A")
        except tk.TclError:
            pass

    def _log(self, msg: str):
        ts   = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, line)
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    # ─── コメント一覧操作 ─────────────────────────────────────────────────────

    def _insert_tree_row(self, item):
        vals = (item.seq_no, item.recv_time_str(), item.post_time_str(), item.kind_label(),
                item.author_name, item.body_short(), item.channel_id, item.roles_str(),
                item.msg_id, item.status_label())
        tag  = item.row_tag()
        tags = (tag,) if tag != "default" else (
            ("default", "alt") if item.seq_no % 2 == 0 else ("default",)
        )
        self._tree.insert("", tk.END, iid=str(item.seq_no), values=vals, tags=tags)
        self._tree.see(str(item.seq_no))

    # ─── フィルタ（一覧表示用） ────────────────────────────────────────────

    def _passes_display_filter(self, item) -> bool:
        """一覧表示用フィルタ（管理ペイン左側のチェックボックスによる）"""
        # 種別フィルタ
        matched_group = False
        for group_label, kinds in FILTER_TYPE_GROUPS.items():
            if item.kind in kinds:
                if self._filter_vars.get(group_label, tk.BooleanVar(value=True)).get():
                    matched_group = True
                break
        else:
            if self._filter_vars.get("その他イベント", tk.BooleanVar(value=True)).get():
                matched_group = True
        if not matched_group:
            return False

        # 投稿者属性フィルタ
        role_filters = {k: v.get() for k, v in self._filter_roles.items()}
        if any(role_filters.values()):
            ok = (
                (role_filters.get("配信者のみ")      and item.is_owner) or
                (role_filters.get("モデレーターのみ") and item.is_moderator) or
                (role_filters.get("メンバーのみ")     and item.is_member) or
                (role_filters.get("認証済みのみ")     and item.is_verified)
            )
            if not ok:
                return False

        # 状態フィルタ
        if not self._filter_status_vars.get(
                item.proc_status, tk.BooleanVar(value=True)).get():
            return False

        # 文字列フィルタ
        text = self._filter_text_var.get().strip()
        if text:
            mode = self._filter_mode_var.get()
            body = item.body
            try:
                if   mode == "部分一致": ok = text in body
                elif mode == "完全一致": ok = text == body
                elif mode == "前方一致": ok = body.startswith(text)
                elif mode == "後方一致": ok = body.endswith(text)
                elif mode == "正規表現": ok = bool(re.search(text, body))
                else: ok = True
            except re.error:
                ok = False
            if not ok:
                return False

        # 読み上げ
        if self._filter_tts_only_var.get() and not item.tts_target:
            return False

        return True

    def _on_filter_changed(self):
        self._apply_filter()

    def _apply_filter(self):
        self._tree.delete(*self._tree.get_children())
        for item in self._ctrl.comments:
            if self._passes_display_filter(item):
                self._insert_tree_row(item)
        self._update_header_stats()
        cw = self._get_comment_window()
        if cw and cw.is_open:
            cw.rebuild_filter_tab(self._ctrl.comments)

    def _clear_filter(self):
        for var in self._filter_vars.values():        var.set(True)
        for var in self._filter_roles.values():       var.set(False)
        for var in self._filter_status_vars.values(): var.set(True)
        self._filter_text_var.set("")
        self._filter_tts_only_var.set(False)
        self._apply_filter()

    # ─── ヘッダー更新 ─────────────────────────────────────────────────────────

    def _update_header_stats(self):
        total = len(self._ctrl.comments)
        shown = len(self._tree.get_children())
        self._lbl_total.config(text=str(total))
        self._lbl_shown.config(text=str(shown))
        if self._ctrl.last_recv_time:
            self._lbl_lastrecv.config(text=self._ctrl.last_recv_time.strftime("%H:%M:%S"))

    # ─── 詳細表示 ─────────────────────────────────────────────────────────────

    def _on_comment_select(self, event):
        sel = self._tree.selection()
        if not sel:
            return
        try:
            seq = int(sel[0])
        except ValueError:
            return
        item = next((c for c in self._ctrl.comments if c.seq_no == seq), None)
        if item:
            self._show_detail(item)

    def _show_detail(self, item):
        t = self._detail_text
        t.config(state=tk.NORMAL)
        t.delete("1.0", tk.END)

        def h(text):
            t.insert(tk.END, f"\n{'─'*2} {text} {'─'*20}\n", "section")

        def kv(key, val):
            t.insert(tk.END, f"  {key:<22}", "key")
            t.insert(tk.END, f"{val}\n", "value")

        h("A. 基本情報")
        kv("受信No",             item.seq_no)
        kv("メッセージID",        item.msg_id)
        kv("種別",               item.kind_label())
        kv("投稿時刻",           item.post_time_str())
        kv("受信時刻",           item.recv_time_str())
        kv("hasDisplayContent",  item.has_display)
        kv("displayMessage",     item.display_msg or "—")
        kv("liveChatId",         item.live_chat_id or "—")

        h("B. 投稿者情報")
        kv("displayName",        item.author_name)
        kv("channelId",          item.channel_id)
        kv("channelUrl",         item.channel_url or "—")
        kv("profileImageUrl",    item.profile_url or "—")
        kv("isChatOwner",        item.is_owner)
        kv("isChatModerator",    item.is_moderator)
        kv("isChatSponsor",      item.is_member)
        kv("isVerified",         item.is_verified)

        h("C. 種別別詳細")
        snippet = item.raw.get("snippet", {})
        kind    = item.kind
        if kind == "textMessageEvent":
            kv("messageText", snippet.get("textMessageDetails", {}).get("messageText", "—"))
        elif kind == "superChatEvent":
            d = snippet.get("superChatDetails", {})
            for k in ["amountMicros", "amountDisplayString", "currency", "userComment", "tier"]:
                kv(k, d.get(k, "—"))
        elif kind == "superStickerEvent":
            d = snippet.get("superStickerDetails", {})
            for k in ["amountMicros", "amountDisplayString", "currency", "tier"]:
                kv(k, d.get(k, "—"))
        elif kind == "memberMilestoneChatEvent":
            d = snippet.get("memberMilestoneChatDetails", {})
            kv("userComment", d.get("userComment", "—"))
            kv("memberMonth",  d.get("memberMonth",  "—"))
        elif kind == "membershipGiftingEvent":
            d = snippet.get("membershipGiftingDetails", {})
            kv("giftMembershipsCount",     d.get("giftMembershipsCount", "—"))
            kv("giftMembershipsLevelName", d.get("giftMembershipsLevelName", "—"))
        elif kind == "userBannedEvent":
            d  = snippet.get("userBannedDetails", {})
            bd = d.get("bannedUserDetails", {})
            kv("bannedUser.channelId",   bd.get("channelId", "—"))
            kv("bannedUser.displayName", bd.get("displayName", "—"))
            kv("banType",                d.get("banType", "—"))
        else:
            t.insert(tk.END, "  (種別固有フィールドなし)\n", "value")

        h("D. 内部処理情報")
        kv("処理状態",     item.status_label())
        kv("一致ルール",   ", ".join(item.filter_rule_ids) or "—")
        kv("連携送信先",   ", ".join(item.sent_to) or "—")

        h("E. Raw JSON")
        t.insert(tk.END, json.dumps(item.raw, ensure_ascii=False, indent=2) + "\n", "raw")
        t.config(state=tk.DISABLED)

    # ─── ソート・右クリック ───────────────────────────────────────────────────

    def _on_sort(self, col: str):
        self._ctrl.log(f"[ソート] 列: {col}（未実装）")

    def _on_list_right_click(self, event):
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        self._tree.selection_set(iid)
        menu = tk.Menu(self._win, tearoff=0,
                       bg=UI_COLORS["bg_panel"], fg=UI_COLORS["fg_main"],
                       activebackground=UI_COLORS["accent"],
                       activeforeground="#FFFFFF")
        menu.add_command(label="メッセージIDをコピー",
                         command=lambda: self._copy_field(iid, "msg_id"))
        menu.add_command(label="本文をコピー",
                         command=lambda: self._copy_field(iid, "body"))
        menu.add_command(label="Raw JSONをコピー",
                         command=lambda: self._copy_raw_json(iid))
        menu.add_separator()
        menu.add_command(label="🐛 デバッグコメント送信",
                         command=self._open_debug_sender)
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_field(self, iid, field):
        try:
            seq  = int(iid)
            item = next(c for c in self._ctrl.comments if c.seq_no == seq)
            val  = str(getattr(item, field, ""))
            self._win.clipboard_clear()
            self._win.clipboard_append(val)
            self._ctrl.log(f"[コピー] {field}: {val[:50]}")
        except Exception as e:
            self._ctrl.log(f"[コピーエラー] {e}")

    def _copy_raw_json(self, iid):
        try:
            seq  = int(iid)
            item = next(c for c in self._ctrl.comments if c.seq_no == seq)
            val  = json.dumps(item.raw, ensure_ascii=False, indent=2)
            self._win.clipboard_clear()
            self._win.clipboard_append(val)
            self._ctrl.log(f"[コピー] Raw JSON (seq={seq})")
        except Exception as e:
            self._ctrl.log(f"[コピーエラー] {e}")

    # ─── コメントビュー連携 ───────────────────────────────────────────────────

    def _open_comment_window_btn(self):
        cw = self._get_comment_window()
        if cw is None:
            return
        if not cw.is_open:
            cw.open()
            cw.load_all(self._ctrl.comments)
            cw.refresh_user_tree()
            cw.refresh_rule_tree()
        else:
            cw._win.lift()
        self._ctrl.log("[コメントビュー] 表示")

    def _open_comment_window_filter_tab(self):
        cw = self._get_comment_window()
        if cw is None:
            return
        if not cw.is_open:
            cw.open()
            cw.load_all(self._ctrl.comments)
            cw.refresh_user_tree()
            cw.refresh_rule_tree()
        else:
            cw._win.lift()
        try:
            cw._notebook.select(3)
        except Exception:
            pass

    def _open_debug_sender(self):
        self._debug_win_opener()

    # ─── ウィンドウ位置保存・復元 ─────────────────────────────────────────────

    def _on_configure(self, event):
        if event.widget is self._win:
            self.cfg["x"]      = self._win.winfo_x()
            self.cfg["y"]      = self._win.winfo_y()
            self.cfg["width"]  = self._win.winfo_width()
            self.cfg["height"] = self._win.winfo_height()
            try:
                self.cfg["sash_main_log"]    = self._paned_main.sash_coord(0)[1]
                self.cfg["sash_filter_list"] = self._paned_h.sash_coord(0)[0]
                self.cfg["sash_list_detail"] = self._paned_h.sash_coord(1)[0]
            except Exception:
                pass

    def _load_sash_positions(self):
        self._win.update_idletasks()
        try:
            self._paned_main.sash_place(0, 1, self.cfg.get("sash_main_log", 560))
            self._paned_h.sash_place(0, self.cfg.get("sash_filter_list", 200), 1)
            self._paned_h.sash_place(1, self.cfg.get("sash_list_detail", 650), 1)
        except Exception:
            pass
