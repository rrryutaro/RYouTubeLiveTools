"""
RCommentHub — コメントビューウィンドウ（主画面）
  - 4タブ構成: 全メッセージ / フィルタメッセージ / ユーザー一覧 / フィルタ設定
  - 接続状態バー（上部）
  - Pillow でアイコン表示
"""

import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import urllib.request
import io
import hashlib

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from constants import (
    UI_COLORS, FONT_FAMILY, FONT_SIZE_S, FONT_SIZE_M,
    ROW_COLORS, EVENT_TYPE_LABELS, CONN_STATUS_COLORS, TRANSPARENT_KEY,
)
from filter_rules import FilterRule, FilterRuleManager, MATCH_TYPES

# ─── Windows スタイル定数 ────────────────────────────────────────────────────
GWL_EXSTYLE      = -20
WS_EX_APPWINDOW  = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

# ─── アイコンサイズ ───────────────────────────────────────────────────────────
ICON_SIZE  = 36
ICON_PAD   = 6
CARD_PAD_X = 8
CARD_PAD_Y = 4

# ─── 種別ごとの表示スタイル ──────────────────────────────────────────────────
KIND_STYLES = {
    "textMessageEvent":          {"bg": UI_COLORS["bg_panel"], "border": UI_COLORS["border"],  "label": None},
    "superChatEvent":            {"bg": "#2A1A00",             "border": "#CC8800",             "label": "Super Chat"},
    "superStickerEvent":         {"bg": "#1A1A00",             "border": "#AA8800",             "label": "Super Sticker"},
    "memberMilestoneChatEvent":  {"bg": "#001A2A",             "border": "#0088CC",             "label": "メンバー継続"},
    "membershipGiftingEvent":    {"bg": "#001A2A",             "border": "#0088CC",             "label": "メンバーギフト"},
    "giftMembershipReceivedEvent":{"bg": "#001A2A",            "border": "#0088CC",             "label": "ギフト受取"},
    "messageDeletedEvent":       {"bg": "#2A0A0A",             "border": "#883333",             "label": "削除"},
    "userBannedEvent":           {"bg": "#3A0000",             "border": "#CC2222",             "label": "BAN"},
}
_DEFAULT_STYLE = {"bg": UI_COLORS["bg_panel"], "border": UI_COLORS["border"], "label": None}

# ─── 属性バッジ ───────────────────────────────────────────────────────────────
BADGE_DEFS = [
    ("is_owner",     "配信者", "#FFD700", "#1A1A00"),
    ("is_moderator", "Mod",    "#80FFCC", "#003322"),
    ("is_member",    "Mbr",    "#80CCFF", "#001833"),
    ("is_verified",  "Ver",    "#AAAAAA", "#1A1A1A"),
]

_PLACEHOLDER_COLORS = [
    "#4A90D9", "#7B68EE", "#50C878", "#FF7F50",
    "#DA70D6", "#40E0D0", "#F4A460", "#87CEEB",
]


def _placeholder_color(name: str) -> str:
    idx = sum(ord(c) for c in (name or "?")) % len(_PLACEHOLDER_COLORS)
    return _PLACEHOLDER_COLORS[idx]


def _make_placeholder_image(name: str, size: int):
    if not _PIL_OK:
        return None
    initial = (name or "?")[0].upper()
    color   = _placeholder_color(name)
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size - 1, size - 1], fill=color)
    try:
        font = ImageFont.truetype("arial.ttf", size // 2)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), initial, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 1), initial, fill="#FFFFFF", font=font)
    return ImageTk.PhotoImage(img)


def _load_url_image(url: str, size: int):
    if not _PIL_OK or not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        img  = Image.open(io.BytesIO(data)).convert("RGBA")
        img  = img.resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        from PIL import ImageDraw as _ID
        _ID.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        img.putalpha(mask)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def _bind_recursive(widget, event, callback):
    widget.bind(event, callback)
    for child in widget.winfo_children():
        _bind_recursive(child, event, callback)


# ════════════════════════════════════════════════════════════════════════════
#  コメントカード
# ════════════════════════════════════════════════════════════════════════════

class CommentCard(tk.Frame):
    """1コメント1ブロックのウィジェット"""

    def __init__(self, parent, item, icon_cache: dict, icon_loader,
                 speak_cb=None, rows=2, icon_visible=True, **kwargs):
        style = KIND_STYLES.get(item.kind, _DEFAULT_STYLE)
        bg    = style["bg"]
        super().__init__(parent, bg=bg, pady=CARD_PAD_Y, padx=CARD_PAD_X,
                         highlightthickness=1,
                         highlightbackground=style["border"],
                         **kwargs)
        self._icon_ref = None
        self._icon_visible = icon_visible

        # ── アイコン領域 ──
        if icon_visible:
            icon_frame = tk.Frame(self, bg=bg,
                                  width=ICON_SIZE + ICON_PAD * 2,
                                  height=ICON_SIZE + ICON_PAD * 2)
            icon_frame.pack(side=tk.LEFT, anchor=tk.N, padx=(0, 6), pady=2)
            icon_frame.pack_propagate(False)
            self._icon_label = tk.Label(icon_frame, bg=bg, bd=0)
            self._icon_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

            ph = icon_cache.get("__ph__" + item.author_name)
            if ph is None:
                ph = _make_placeholder_image(item.author_name, ICON_SIZE)
                icon_cache["__ph__" + item.author_name] = ph
            if ph:
                self._icon_label.config(image=ph)
                self._icon_ref = ph

            key = item.channel_id or item.author_name
            if item.profile_url and key not in icon_cache:
                icon_cache[key] = None
                threading.Thread(
                    target=icon_loader,
                    args=(item.profile_url, key, self._on_icon_loaded),
                    daemon=True,
                ).start()
            elif key in icon_cache and icon_cache[key] is not None:
                self._icon_ref = icon_cache[key]
                self._icon_label.config(image=self._icon_ref)
        else:
            self._icon_label = None

        # ── テキスト領域 ──
        right = tk.Frame(self, bg=bg)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        if rows == 1:
            # コンパクト1行表示: 名前: 本文
            name_part = item.author_name or ""
            body_part = item.body or ""
            if name_part and body_part:
                compact_text = f"{name_part}: {body_part}"
            elif name_part:
                compact_text = name_part
            else:
                compact_text = body_part or "—"
            compact_lbl = tk.Label(right, text=compact_text,
                                    font=(FONT_FAMILY, FONT_SIZE_S),
                                    fg=UI_COLORS["fg_main"], bg=bg,
                                    anchor=tk.W, justify=tk.LEFT,
                                    wraplength=0)
            compact_lbl.pack(anchor=tk.W, fill=tk.X)
            self._body_label = compact_lbl
        else:
            # 2行表示（標準）
            kind_label = style["label"]
            if kind_label:
                tk.Label(right, text=kind_label,
                         font=(FONT_FAMILY, FONT_SIZE_S - 1, "bold"),
                         fg=style["border"], bg=bg, anchor=tk.W).pack(anchor=tk.W)

            top_row = tk.Frame(right, bg=bg)
            top_row.pack(anchor=tk.W, fill=tk.X)
            tk.Label(top_row, text=item.author_name or "—",
                     font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                     fg=UI_COLORS["fg_header"], bg=bg, anchor=tk.W
                     ).pack(side=tk.LEFT)
            for attr, label, fg_b, bg_b in BADGE_DEFS:
                if getattr(item, attr, False):
                    tk.Label(top_row, text=label,
                             font=(FONT_FAMILY, FONT_SIZE_S - 1),
                             fg=fg_b, bg=bg_b, padx=3, pady=0,
                             relief=tk.FLAT).pack(side=tk.LEFT, padx=(3, 0))
            tk.Label(top_row, text=item.post_time_str(),
                     font=(FONT_FAMILY, FONT_SIZE_S - 1),
                     fg=UI_COLORS["fg_label"], bg=bg, anchor=tk.E
                     ).pack(side=tk.RIGHT, padx=(4, 0))

            if item.kind == "superChatEvent":
                sc  = item.raw.get("snippet", {}).get("superChatDetails", {})
                amt = sc.get("amountDisplayString", "")
                if amt:
                    tk.Label(right, text=amt,
                             font=(FONT_FAMILY, FONT_SIZE_M, "bold"),
                             fg="#FFD700", bg=bg, anchor=tk.W).pack(anchor=tk.W)

            body = item.body
            if body:
                tk.Label(right, text=body,
                         font=(FONT_FAMILY, FONT_SIZE_S),
                         fg=UI_COLORS["fg_main"], bg=bg,
                         anchor=tk.W, justify=tk.LEFT,
                         wraplength=0).pack(anchor=tk.W, fill=tk.X)
                self._body_label = right.winfo_children()[-1]
            else:
                self._body_label = None

        self.bind("<Configure>", self._on_resize)
        if speak_cb is not None:
            _bind_recursive(self, "<Double-Button-1>",
                            lambda e, i=item: speak_cb(i))

    def _on_resize(self, event):
        if self._body_label:
            icon_w = (ICON_SIZE + ICON_PAD * 2 + 6) if self._icon_visible else 0
            wrap = max(100, self.winfo_width() - icon_w - CARD_PAD_X * 2 - 16)
            self._body_label.config(wraplength=wrap)

    def _on_icon_loaded(self, photo):
        if photo and self._icon_label is not None:
            try:
                self._icon_label.config(image=photo)
                self._icon_ref = photo
            except tk.TclError:
                pass


# ════════════════════════════════════════════════════════════════════════════
#  コメントビューウィンドウ（主画面）
# ════════════════════════════════════════════════════════════════════════════

class CommentWindow:
    """4タブのコメント管理ウィンドウ（主画面相当）"""

    DEFAULT_WIDTH  = 440
    DEFAULT_HEIGHT = 680

    def __init__(self, master: tk.Tk, cfg: dict,
                 on_close_cb=None, speak_cb=None,
                 user_manager=None, filter_rule_mgr=None,
                 open_connect_cb=None, open_settings_cb=None,
                 open_detail_cb=None, open_debug_cb=None):
        self._master         = master
        self._cfg            = cfg
        self._on_close       = on_close_cb
        self._speak_cb       = speak_cb
        self._user_mgr       = user_manager
        self._filter_mgr     = filter_rule_mgr
        self._open_connect   = open_connect_cb
        self._open_settings  = open_settings_cb
        self._open_detail    = open_detail_cb
        self._open_debug     = open_debug_cb
        self._win: tk.Toplevel | None = None

        # ドラッグ移動用
        self._drag_x = 0
        self._drag_y = 0

        self._icon_cache: dict = {}

        # TTS 設定 UI 変数（外部から参照）
        self.tts_enabled_var       = tk.BooleanVar(master, value=False)
        self.tts_normal_var        = tk.BooleanVar(master, value=True)
        self.tts_superchat_var     = tk.BooleanVar(master, value=True)
        self.tts_owner_var         = tk.BooleanVar(master, value=True)
        self.tts_mod_var           = tk.BooleanVar(master, value=True)
        self.tts_member_var        = tk.BooleanVar(master, value=False)
        self.tts_simplify_name_var = tk.BooleanVar(master, value=True)

        self.topmost_var = tk.BooleanVar(master, value=cfg.get("cw_topmost", False))

        # ユーザー一覧 Treeview の定期更新用タスク ID
        self._user_refresh_id = None

    # ─── 開閉 ────────────────────────────────────────────────────────────────

    def open(self):
        if self._win is not None:
            try:
                self._win.lift()
                self._win.focus_force()
                return
            except tk.TclError:
                self._win = None

        self._win = tk.Toplevel(self._master)
        self._win.title("RCommentHub — コメントビュー")
        self._win.configure(bg=UI_COLORS["bg_main"])
        self._win.overrideredirect(True)

        x = self._cfg.get("cw_x", 100)
        y = self._cfg.get("cw_y", 100)
        w = self._cfg.get("cw_width",  self.DEFAULT_WIDTH)
        h = self._cfg.get("cw_height", self.DEFAULT_HEIGHT)
        self._win.geometry(f"{w}x{h}+{x}+{y}")
        self._win.minsize(320, 400)
        self._win.wm_attributes("-topmost", self.topmost_var.get())

        # 透過設定を適用
        self._apply_transparency(self._cfg.get("cw_transparent", False))

        self._build_ui()
        self._win.bind("<Configure>", self._on_configure)

        # Alt+Tab に表示されるよう適用（overrideredirect 後は少し遅延が必要）
        self._win.after(50, self._set_appwindow)

        # ユーザー一覧の定期更新開始
        self._schedule_user_refresh()

    def close(self):
        if self._user_refresh_id and self._win:
            try:
                self._win.after_cancel(self._user_refresh_id)
            except Exception:
                pass
        self._user_refresh_id = None
        if self._win:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None

    @property
    def is_open(self) -> bool:
        return self._win is not None

    # ─── UI 構築 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        win = self._win
        C   = UI_COLORS

        # ── 接続状態バー ──
        self._status_bar = tk.Frame(win, bg=C["bg_header"], pady=4)
        self._status_bar.pack(fill=tk.X, side=tk.TOP)

        # 接続状態ドット + ラベル
        self._lbl_conn_dot = tk.Label(
            self._status_bar, text="■",
            font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
            fg=CONN_STATUS_COLORS["disconnected"], bg=C["bg_header"]
        )
        self._lbl_conn_dot.pack(side=tk.LEFT, padx=(8, 2))
        self._lbl_conn_text = tk.Label(
            self._status_bar, text="未接続",
            font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
            fg=CONN_STATUS_COLORS["disconnected"], bg=C["bg_header"]
        )
        self._lbl_conn_text.pack(side=tk.LEFT)

        # 配信タイトル（中央）
        self._lbl_title = tk.Label(
            self._status_bar, text="",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_header"]
        )
        self._lbl_title.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        # 右側ボタン群（右から順に: ×、設定、詳細、接続）
        self._btn_close = tk.Button(
            self._status_bar, text="×",
            font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
            bg=C["bg_header"], fg="#FF6060", activebackground="#8A2020",
            relief=tk.FLAT, padx=6, pady=1, bd=0,
            command=self._on_window_close,
        )
        self._btn_close.pack(side=tk.RIGHT, padx=(0, 4))

        if self._open_settings:
            tk.Button(
                self._status_bar, text="設定",
                font=(FONT_FAMILY, FONT_SIZE_S),
                bg=C["bg_list"], fg=C["fg_label"],
                relief=tk.FLAT, padx=6, pady=1,
                command=self._open_settings,
            ).pack(side=tk.RIGHT, padx=(0, 2))

        if self._open_detail:
            tk.Button(
                self._status_bar, text="詳細",
                font=(FONT_FAMILY, FONT_SIZE_S),
                bg=C["bg_list"], fg=C["fg_label"],
                relief=tk.FLAT, padx=6, pady=1,
                command=self._open_detail,
            ).pack(side=tk.RIGHT, padx=(0, 2))

        if self._open_connect:
            tk.Button(
                self._status_bar, text="接続",
                font=(FONT_FAMILY, FONT_SIZE_S),
                bg="#2A4A2A", fg="#AAFFAA", activebackground="#3A6A3A",
                relief=tk.FLAT, padx=6, pady=1,
                command=self._open_connect,
            ).pack(side=tk.RIGHT, padx=(0, 4))

        if self._open_debug:
            tk.Button(
                self._status_bar, text="🐛",
                font=(FONT_FAMILY, FONT_SIZE_S),
                bg=C["bg_header"], fg="#FF8C00",
                activebackground="#3A2A00",
                relief=tk.FLAT, padx=6, pady=1,
                command=self._open_debug,
            ).pack(side=tk.RIGHT, padx=(0, 2))

        # ── 4タブ Notebook ──
        style = ttk.Style()
        style.configure("CV.TNotebook",
                        background=C["bg_main"], tabmargins=[2, 2, 0, 0])
        style.configure("CV.TNotebook.Tab",
                        background=C["bg_panel"], foreground=C["fg_label"],
                        font=(FONT_FAMILY, FONT_SIZE_S), padding=[8, 3])
        style.map("CV.TNotebook.Tab",
                  background=[("selected", C["accent"])],
                  foreground=[("selected", "#FFFFFF")])

        self._notebook = ttk.Notebook(win, style="CV.TNotebook")
        self._notebook.pack(fill=tk.BOTH, expand=True)

        tab_all     = tk.Frame(self._notebook, bg=C["bg_main"])
        tab_filter  = tk.Frame(self._notebook, bg=C["bg_main"])
        tab_users   = tk.Frame(self._notebook, bg=C["bg_main"])
        tab_fsettings = tk.Frame(self._notebook, bg=C["bg_main"])

        self._notebook.add(tab_all,       text="全メッセージ")
        self._notebook.add(tab_filter,    text="フィルタメッセージ")
        self._notebook.add(tab_users,     text="ユーザー一覧")
        self._notebook.add(tab_fsettings, text="フィルタ設定")

        self._canvas_all,    self._cards_all    = self._make_scroll_area(tab_all)
        self._canvas_filter, self._cards_filter = self._make_scroll_area(tab_filter)
        self._build_user_tab(tab_users)
        self._build_filter_settings_tab(tab_fsettings)

        # ── 透過モード専用フレーム（GDI 直接描画で child HWND を使わない） ──
        self._trans_outer = tk.Frame(win, bg=C["bg_main"])
        # 単一 Canvas: ハンドル帯 + テキストを create_text/create_rectangle で描画
        # ※ tk.Label/tk.Frame は child HWND のため -transparentcolor が効かない
        self._trans_canvas = tk.Canvas(
            self._trans_outer, bg=C["bg_main"],
            highlightthickness=0, borderwidth=0,
        )
        self._trans_canvas.pack(fill=tk.BOTH, expand=True)
        self._trans_canvas.bind("<Configure>", lambda e: self._redraw_trans_overlay())
        self._trans_canvas.bind("<Button-3>", self._show_context_menu, add="+")
        self._trans_text_list: list = []  # 表示中のコメント文字列リスト

        # ── コンテキストメニュー ──
        self._ctx_menu = tk.Menu(win, tearoff=0,
                                  bg=C["bg_panel"], fg=C["fg_main"],
                                  activebackground=C["accent"],
                                  activeforeground="#FFFFFF",
                                  font=(FONT_FAMILY, FONT_SIZE_S))
        self._transparent_mode_var = tk.BooleanVar(value=False)
        self._ctx_menu.add_checkbutton(
            label="コメント以外透過して非表示",
            variable=self._transparent_mode_var,
            command=self._toggle_transparent_mode,
        )
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="最小化", command=self._minimize)
        self._ctx_menu.add_command(label="閉じる", command=self._on_window_close)

        win.bind("<Button-3>", self._show_context_menu)

        # ── ドラッグをウィンドウ全体に適用 ──
        self._bind_drag_to_all(win)

    # ─── スクロールエリア ──────────────────────────────────────────────────────

    def _make_scroll_area(self, parent):
        C = UI_COLORS
        container = tk.Frame(parent, bg=C["bg_main"])
        container.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(container, bg=C["bg_main"], highlightthickness=0)
        vsb    = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cards_frame = tk.Frame(canvas, bg=C["bg_main"])
        cw_id = canvas.create_window((0, 0), window=cards_frame, anchor="nw")
        cards_frame.bind("<Configure>",
                         lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e, c=canvas, w=cw_id: c.itemconfig(w, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e, c=canvas: c.yview_scroll(-1 * (e.delta // 120), "units"))
        return canvas, cards_frame

    # ─── ユーザー一覧タブ ─────────────────────────────────────────────────────

    def _build_user_tab(self, parent):
        C = UI_COLORS

        # ツールバー
        bar = tk.Frame(parent, bg=C["bg_panel"], pady=2)
        bar.pack(fill=tk.X)
        self._lbl_user_count = tk.Label(
            bar, text="ユーザー: 0人",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_panel"]
        )
        self._lbl_user_count.pack(side=tk.LEFT, padx=8)

        # Treeview
        cols = ("name", "count", "last_time", "elapsed", "wl", "bl", "filter")
        tree_frame = tk.Frame(parent, bg=C["bg_list"])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self._user_tree = ttk.Treeview(tree_frame, columns=cols,
                                        show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                             command=self._user_tree.yview)
        self._user_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._user_tree.pack(fill=tk.BOTH, expand=True)

        headings = [
            ("name",    "表示名",       140, True),
            ("count",   "回数",          50, False),
            ("last_time","最終発言",      70, False),
            ("elapsed", "経過",          70, False),
            ("wl",      "WL",            32, False),
            ("bl",      "BL",            32, False),
            ("filter",  "対象",          40, False),
        ]
        for col, heading, width, stretch in headings:
            self._user_tree.heading(col, text=heading)
            self._user_tree.column(col, width=width, minwidth=30, stretch=stretch)

        # 右クリックメニュー（ホワイトリスト/ブラックリスト切替）
        self._user_menu = tk.Menu(self._win, tearoff=0,
                                   bg=C["bg_panel"], fg=C["fg_main"],
                                   activebackground=C["accent"])
        self._user_menu.add_command(label="ホワイトリスト ON/OFF",
                                     command=self._toggle_whitelist)
        self._user_menu.add_command(label="ブラックリスト ON/OFF",
                                     command=self._toggle_blacklist)
        self._user_menu.add_separator()
        self._user_menu.add_command(label="フィルタ対象 ON/OFF",
                                     command=self._toggle_filter_target)
        self._user_tree.bind("<Button-3>", self._on_user_right_click)

    def _build_filter_settings_tab(self, parent):
        C = UI_COLORS

        # 上部ツールバー
        bar = tk.Frame(parent, bg=C["bg_panel"], pady=3)
        bar.pack(fill=tk.X)
        tk.Button(bar, text="+ ルール追加",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["accent"], fg="#FFFFFF",
                  relief=tk.FLAT, padx=6, pady=1,
                  command=self._on_add_filter_rule
                  ).pack(side=tk.LEFT, padx=6)
        tk.Button(bar, text="選択ルール削除",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg="#5A2A2A", fg="#FFFFFF",
                  relief=tk.FLAT, padx=6, pady=1,
                  command=self._on_remove_filter_rule
                  ).pack(side=tk.LEFT, padx=2)
        tk.Button(bar, text="↑", font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_label"],
                  relief=tk.FLAT, padx=6, pady=1,
                  command=self._on_move_rule_up
                  ).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(bar, text="↓", font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_label"],
                  relief=tk.FLAT, padx=6, pady=1,
                  command=self._on_move_rule_down
                  ).pack(side=tk.LEFT, padx=2)

        # ルール一覧 Treeview（上部）
        list_frame = tk.Frame(parent, bg=C["bg_list"])
        list_frame.pack(fill=tk.X, padx=2, pady=(2, 0))
        cols = ("enabled", "name", "match", "text", "field")
        self._rule_tree = ttk.Treeview(list_frame, columns=cols,
                                        show="headings", selectmode="browse",
                                        height=6)
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                             command=self._rule_tree.yview)
        self._rule_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._rule_tree.pack(fill=tk.X)
        for col, heading, width, stretch in [
            ("enabled", "ON",  36, False),
            ("name",    "名前", 120, True),
            ("match",   "一致", 70, False),
            ("text",    "テキスト", 120, True),
            ("field",   "対象", 60, False),
        ]:
            self._rule_tree.heading(col, text=heading)
            self._rule_tree.column(col, width=width, minwidth=30, stretch=stretch)
        self._rule_tree.bind("<<TreeviewSelect>>", self._on_rule_select)

        # ルール編集フォーム（下部）
        self._rule_edit_frame = tk.Frame(parent, bg=C["bg_main"])
        self._rule_edit_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self._build_rule_edit_form(self._rule_edit_frame)
        self._set_edit_form_enabled(False)
        self._selected_rule_id: str | None = None

    def _build_rule_edit_form(self, parent):
        """ルール編集フォームを構築する"""
        C = UI_COLORS

        def lbl(text, row_frame):
            tk.Label(row_frame, text=text,
                     font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_main"],
                     width=14, anchor=tk.W
                     ).pack(side=tk.LEFT)

        def row():
            f = tk.Frame(parent, bg=C["bg_main"])
            f.pack(fill=tk.X, pady=1)
            return f

        # ルール名
        r = row()
        lbl("ルール名:", r)
        self._edit_name_var = tk.StringVar()
        tk.Entry(r, textvariable=self._edit_name_var,
                 bg=C["bg_list"], fg=C["fg_main"],
                 insertbackground=C["fg_main"],
                 font=(FONT_FAMILY, FONT_SIZE_S), relief=tk.FLAT
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ON/OFF
        r = row()
        lbl("", r)
        self._edit_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r, text="このルールを有効にする",
                       variable=self._edit_enabled_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(side=tk.LEFT)

        # テキスト
        r = row()
        lbl("テキスト:", r)
        self._edit_text_var = tk.StringVar()
        tk.Entry(r, textvariable=self._edit_text_var,
                 bg=C["bg_list"], fg=C["fg_main"],
                 insertbackground=C["fg_main"],
                 font=(FONT_FAMILY, FONT_SIZE_S), relief=tk.FLAT
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 一致方式 + 対象フィールド
        r = row()
        lbl("一致方式:", r)
        self._edit_match_var = tk.StringVar(value="部分一致")
        ttk.Combobox(r, textvariable=self._edit_match_var,
                     values=MATCH_TYPES, state="readonly", width=8,
                     font=(FONT_FAMILY, FONT_SIZE_S)
                     ).pack(side=tk.LEFT)
        tk.Label(r, text="  対象:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)
        self._edit_field_var = tk.StringVar(value="本文")
        ttk.Combobox(r, textvariable=self._edit_field_var,
                     values=["本文", "投稿者名"], state="readonly", width=6,
                     font=(FONT_FAMILY, FONT_SIZE_S)
                     ).pack(side=tk.LEFT, padx=(2, 0))

        # 種別条件
        r = row()
        lbl("種別:", r)
        self._edit_kind_normal_var = tk.BooleanVar(value=True)
        self._edit_kind_sc_var     = tk.BooleanVar(value=True)
        self._edit_kind_other_var  = tk.BooleanVar(value=True)
        for var, text in [
            (self._edit_kind_normal_var, "通常"),
            (self._edit_kind_sc_var,     "SC/Sticker"),
            (self._edit_kind_other_var,  "その他"),
        ]:
            tk.Checkbutton(r, text=text, variable=var,
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_main"],
                           activebackground=C["bg_main"],
                           selectcolor=C["bg_list"]
                           ).pack(side=tk.LEFT, padx=(0, 4))

        # 投稿者属性
        r = row()
        lbl("属性:", r)
        self._edit_role_owner_var    = tk.BooleanVar(value=False)
        self._edit_role_mod_var      = tk.BooleanVar(value=False)
        self._edit_role_member_var   = tk.BooleanVar(value=False)
        self._edit_role_verified_var = tk.BooleanVar(value=False)
        for var, text in [
            (self._edit_role_owner_var,    "配信者"),
            (self._edit_role_mod_var,      "Mod"),
            (self._edit_role_member_var,   "Mbr"),
            (self._edit_role_verified_var, "Ver"),
        ]:
            tk.Checkbutton(r, text=text, variable=var,
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_main"],
                           activebackground=C["bg_main"],
                           selectcolor=C["bg_list"]
                           ).pack(side=tk.LEFT, padx=(0, 4))

        # ユーザー管理連動
        r = row()
        lbl("ユーザー:", r)
        self._edit_excl_bl_var      = tk.BooleanVar(value=False)
        self._edit_filter_only_var  = tk.BooleanVar(value=False)
        tk.Checkbutton(r, text="BL除外", variable=self._edit_excl_bl_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Checkbutton(r, text="対象のみ", variable=self._edit_filter_only_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(side=tk.LEFT)

        # 保存ボタン
        save_row = tk.Frame(parent, bg=C["bg_main"])
        save_row.pack(anchor=tk.E, pady=(4, 0))
        self._btn_rule_save = tk.Button(
            save_row, text="ルール保存",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["accent"], fg="#FFFFFF",
            relief=tk.FLAT, padx=8, pady=2,
            command=self._on_save_rule,
        )
        self._btn_rule_save.pack(side=tk.RIGHT)

        self._edit_widgets = [w for w in parent.winfo_children()]

    def _set_edit_form_enabled(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in self._rule_edit_frame.winfo_children():
            try:
                w.config(state=state)
            except Exception:
                pass
            for c in w.winfo_children():
                try:
                    c.config(state=state)
                except Exception:
                    pass

    # ─── コメント追加・一括ロード ─────────────────────────────────────────────

    def add_comment(self, item):
        """新着コメントを末尾に追加"""
        if self._win is None:
            return
        try:
            self._add_card(self._cards_all, self._canvas_all, item)
            if getattr(item, "filter_match", False):
                self._add_card(self._cards_filter, self._canvas_filter, item)
            # 透過モード用テキスト追加
            self._add_trans_text(item)
        except tk.TclError:
            pass

    def load_all(self, items):
        """既存コメントを一括ロード"""
        if self._win is None:
            return
        rows = self._cfg.get("display_rows", 2)
        icon_visible = self._cfg.get("icon_visible", True)
        for item in items:
            card = CommentCard(self._cards_all, item,
                               self._icon_cache, self._load_icon_bg,
                               speak_cb=self._speak_cb,
                               rows=rows, icon_visible=icon_visible)
            card.pack(fill=tk.X, pady=1, padx=2)
            if getattr(item, "filter_match", False):
                card2 = CommentCard(self._cards_filter, item,
                                    self._icon_cache, self._load_icon_bg,
                                    speak_cb=self._speak_cb,
                                    rows=rows, icon_visible=icon_visible)
                card2.pack(fill=tk.X, pady=1, padx=2)
            self._add_trans_text(item)
        self._win.after(100, lambda: self._scroll_to_bottom(self._canvas_all))

    def reload_cards(self, items):
        """ウィンドウを維持したままカードパネルのみ再構築する（設定変更時に使用）"""
        if self._win is None:
            return
        for w in self._cards_all.winfo_children():
            w.destroy()
        for w in self._cards_filter.winfo_children():
            w.destroy()
        self._trans_text_list.clear()
        self._trans_canvas.delete("all")
        self.load_all(items)

    def rebuild_filter_tab(self, items):
        """フィルタ結果タブを再構築（条件変更時）"""
        if self._win is None:
            return
        try:
            for w in self._cards_filter.winfo_children():
                w.destroy()
            for item in items:
                if getattr(item, "filter_match", False):
                    card = CommentCard(self._cards_filter, item,
                                       self._icon_cache, self._load_icon_bg,
                                       speak_cb=self._speak_cb)
                    card.pack(fill=tk.X, pady=1, padx=2)
            self._win.after(100, lambda: self._scroll_to_bottom(self._canvas_filter))
        except tk.TclError:
            pass

    # ─── ユーザー一覧 ─────────────────────────────────────────────────────────

    def refresh_user_tree(self):
        """ユーザー一覧 Treeview を最新状態に更新する"""
        if self._win is None or self._user_mgr is None:
            return
        try:
            users = self._user_mgr.all_users()
            self._user_tree.delete(*self._user_tree.get_children())
            for rec in sorted(users, key=lambda r: r.comment_count, reverse=True):
                self._user_tree.insert("", "end",
                    iid=rec.channel_id,
                    values=(
                        rec.display_name,
                        rec.comment_count,
                        rec.last_time_str,
                        rec.elapsed_str,
                        "✓" if rec.is_whitelist else "",
                        "✓" if rec.is_blacklist else "",
                        "✓" if rec.is_filter_target else "",
                    ))
            count = self._user_mgr.count()
            self._lbl_user_count.config(text=f"ユーザー: {count}人")
        except Exception:
            pass

    def _schedule_user_refresh(self):
        """30秒ごとにユーザー一覧を自動更新する"""
        if self._win is None:
            return
        self.refresh_user_tree()
        self._user_refresh_id = self._win.after(30000, self._schedule_user_refresh)

    # ─── フィルタ設定タブ ─────────────────────────────────────────────────────

    def refresh_rule_tree(self):
        """ルール一覧 Treeview を最新状態に更新する"""
        if self._win is None or self._filter_mgr is None:
            return
        try:
            self._rule_tree.delete(*self._rule_tree.get_children())
            for rule in self._filter_mgr.rules:
                self._rule_tree.insert("", "end",
                    iid=rule.rule_id,
                    values=(
                        "ON" if rule.enabled else "off",
                        rule.name,
                        rule.match_type,
                        rule.target_text,
                        rule.target_field,
                    ))
        except Exception:
            pass

    def _on_rule_select(self, event):
        sel = self._rule_tree.selection()
        if not sel:
            self._set_edit_form_enabled(False)
            self._selected_rule_id = None
            return
        rule_id = sel[0]
        if self._filter_mgr is None:
            return
        rule = self._filter_mgr.get_rule(rule_id)
        if rule is None:
            return
        self._selected_rule_id = rule_id
        self._load_rule_to_form(rule)
        self._set_edit_form_enabled(True)

    def _load_rule_to_form(self, rule: FilterRule):
        self._edit_name_var.set(rule.name)
        self._edit_enabled_var.set(rule.enabled)
        self._edit_text_var.set(rule.target_text)
        self._edit_match_var.set(rule.match_type)
        self._edit_field_var.set(rule.target_field)
        self._edit_kind_normal_var.set(rule.kind_normal)
        self._edit_kind_sc_var.set(rule.kind_superchat)
        self._edit_kind_other_var.set(rule.kind_other)
        self._edit_role_owner_var.set(rule.role_owner)
        self._edit_role_mod_var.set(rule.role_mod)
        self._edit_role_member_var.set(rule.role_member)
        self._edit_role_verified_var.set(rule.role_verified)
        self._edit_excl_bl_var.set(rule.exclude_blacklist)
        self._edit_filter_only_var.set(rule.filter_target_only)

    def _on_save_rule(self):
        if self._selected_rule_id is None or self._filter_mgr is None:
            return
        rule = self._filter_mgr.get_rule(self._selected_rule_id)
        if rule is None:
            return
        rule.name               = self._edit_name_var.get()
        rule.enabled            = self._edit_enabled_var.get()
        rule.target_text        = self._edit_text_var.get()
        rule.match_type         = self._edit_match_var.get()
        rule.target_field       = self._edit_field_var.get()
        rule.kind_normal        = self._edit_kind_normal_var.get()
        rule.kind_superchat     = self._edit_kind_sc_var.get()
        rule.kind_other         = self._edit_kind_other_var.get()
        rule.role_owner         = self._edit_role_owner_var.get()
        rule.role_mod           = self._edit_role_mod_var.get()
        rule.role_member        = self._edit_role_member_var.get()
        rule.role_verified      = self._edit_role_verified_var.get()
        rule.exclude_blacklist  = self._edit_excl_bl_var.get()
        rule.filter_target_only = self._edit_filter_only_var.get()
        self.refresh_rule_tree()

    def _on_add_filter_rule(self):
        if self._filter_mgr is None:
            return
        rule = self._filter_mgr.add_rule()
        self.refresh_rule_tree()
        # 新しいルールを選択状態にする
        try:
            self._rule_tree.selection_set(rule.rule_id)
            self._rule_tree.see(rule.rule_id)
            self._on_rule_select(None)
        except Exception:
            pass

    def _on_remove_filter_rule(self):
        if self._selected_rule_id is None or self._filter_mgr is None:
            return
        self._filter_mgr.remove_rule(self._selected_rule_id)
        self._selected_rule_id = None
        self._set_edit_form_enabled(False)
        self.refresh_rule_tree()

    def _on_move_rule_up(self):
        if self._selected_rule_id and self._filter_mgr:
            self._filter_mgr.move_up(self._selected_rule_id)
            self.refresh_rule_tree()
            try:
                self._rule_tree.selection_set(self._selected_rule_id)
            except Exception:
                pass

    def _on_move_rule_down(self):
        if self._selected_rule_id and self._filter_mgr:
            self._filter_mgr.move_down(self._selected_rule_id)
            self.refresh_rule_tree()
            try:
                self._rule_tree.selection_set(self._selected_rule_id)
            except Exception:
                pass

    # ─── ユーザー右クリックメニュー ───────────────────────────────────────────

    def _on_user_right_click(self, event):
        iid = self._user_tree.identify_row(event.y)
        if iid:
            self._user_tree.selection_set(iid)
            self._user_menu.post(event.x_root, event.y_root)

    def _get_selected_user(self):
        sel = self._user_tree.selection()
        if not sel or self._user_mgr is None:
            return None
        return self._user_mgr.get(sel[0])

    def _toggle_whitelist(self):
        rec = self._get_selected_user()
        if rec:
            rec.is_whitelist = not rec.is_whitelist
            self.refresh_user_tree()

    def _toggle_blacklist(self):
        rec = self._get_selected_user()
        if rec:
            rec.is_blacklist = not rec.is_blacklist
            self.refresh_user_tree()

    def _toggle_filter_target(self):
        rec = self._get_selected_user()
        if rec:
            rec.is_filter_target = not rec.is_filter_target
            self.refresh_user_tree()

    # ─── 接続状態更新 ─────────────────────────────────────────────────────────

    def set_conn_status(self, status: str, title: str = ""):
        """接続状態バーを更新する（UI スレッドから呼ぶこと）"""
        if self._win is None:
            return
        color = CONN_STATUS_COLORS.get(status, CONN_STATUS_COLORS["disconnected"])
        from constants import CONN_STATUS_LABELS
        label = CONN_STATUS_LABELS.get(status, status)
        try:
            self._lbl_conn_dot.config(fg=color)
            self._lbl_conn_text.config(text=label, fg=color)
            if title:
                self._lbl_title.config(text=title)
        except tk.TclError:
            pass

    # ─── カード追加（内部） ───────────────────────────────────────────────────

    def _add_card(self, cards_frame, canvas, item):
        was_at_bottom = self._is_at_bottom(canvas)
        rows = self._cfg.get("display_rows", 2)
        icon_visible = self._cfg.get("icon_visible", True)
        card = CommentCard(cards_frame, item,
                           self._icon_cache, self._load_icon_bg,
                           speak_cb=self._speak_cb,
                           rows=rows, icon_visible=icon_visible)
        card.pack(fill=tk.X, pady=1, padx=2)
        if was_at_bottom:
            self._win.after(50, lambda c=canvas: self._scroll_to_bottom(c))

    def _add_trans_text(self, item):
        """透過モード用: コメント本文をリストに追加し Canvas を再描画する"""
        if self._win is None or not item.body:
            return
        try:
            self._trans_text_list.append(item.body)
            if len(self._trans_text_list) > 10:
                self._trans_text_list.pop(0)
            is_trans = self._transparent_mode_var.get() if hasattr(self, "_transparent_mode_var") else False
            if is_trans:
                self._redraw_trans_overlay()
        except tk.TclError:
            pass

    def _redraw_trans_overlay(self):
        """透過モード Canvas を再描画する（ハンドル帯 + コメントテキスト）"""
        if self._win is None:
            return
        c = self._trans_canvas
        c.delete("all")
        w = max(c.winfo_width(), 100)
        # ── ハンドル帯（非透過: #3A3A5A） ─────────────────────────────────
        c.create_rectangle(0, 0, w, 16, fill="#3A3A5A", outline="")
        c.create_text(6, 8, text="■ コメントビュー", fill="#8888BB",
                      anchor="w", font=(FONT_FAMILY, FONT_SIZE_S - 1))
        # ── コメントテキスト ───────────────────────────────────────────────
        y = 22
        wrap_w = max(80, w - 12)
        for text in self._trans_text_list:
            tid = c.create_text(6, y, text=text, fill=UI_COLORS["fg_main"],
                                anchor="nw", font=(FONT_FAMILY, FONT_SIZE_S),
                                width=wrap_w)
            bbox = c.bbox(tid)
            y = (bbox[3] + 4) if bbox else (y + 20)

    # ─── アイコンロード ──────────────────────────────────────────────────────

    def _load_icon_bg(self, url: str, key: str, callback):
        photo = _load_url_image(url, ICON_SIZE)
        if photo:
            self._icon_cache[key] = photo
        if self._win:
            try:
                self._win.after(0, lambda: callback(photo))
            except tk.TclError:
                pass

    # ─── スクロール制御 ──────────────────────────────────────────────────────

    def _is_at_bottom(self, canvas) -> bool:
        try:
            _, bot = canvas.yview()
            return bot >= 0.95
        except Exception:
            return True

    def _scroll_to_bottom(self, canvas):
        try:
            canvas.yview_moveto(1.0)
        except Exception:
            pass

    # ─── ドラッグ移動 ────────────────────────────────────────────────────────

    # ボタン類などドラッグを除外するウィジェット型
    _DRAG_EXCLUDE = (tk.Button, ttk.Button, ttk.Combobox, ttk.Spinbox,
                     tk.Entry, tk.Checkbutton, ttk.Checkbutton,
                     ttk.Scrollbar, ttk.Treeview, tk.Scrollbar)

    def _bind_drag_to_all(self, widget):
        """ボタン等を除いた全ウィジェットにドラッグバインドを再帰的に設定する"""
        if not isinstance(widget, self._DRAG_EXCLUDE):
            widget.bind("<ButtonPress-1>", self._drag_start, add="+")
            widget.bind("<B1-Motion>",      self._drag_move, add="+")
        for child in widget.winfo_children():
            self._bind_drag_to_all(child)

    def _drag_start(self, event):
        if self._win is None:
            return
        self._drag_x = event.x_root - self._win.winfo_x()
        self._drag_y = event.y_root - self._win.winfo_y()

    def _drag_move(self, event):
        if self._win is None:
            return
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._win.geometry(f"+{x}+{y}")

    # ─── コンテキストメニュー ────────────────────────────────────────────────

    def _show_context_menu(self, event):
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    # ─── 透過モード ──────────────────────────────────────────────────────────

    def _toggle_transparent_mode(self):
        on = self._transparent_mode_var.get()
        if self._win is None:
            return

        if on:
            # 通常UIを非表示
            self._status_bar.pack_forget()
            self._notebook.pack_forget()
            # Canvas を透過キー色に変更して描画
            self._trans_canvas.configure(bg=TRANSPARENT_KEY)
            self._trans_outer.configure(bg=TRANSPARENT_KEY)
            self._trans_outer.pack(fill=tk.BOTH, expand=True)
            # ウィンドウを透過設定
            # 注意: -alpha を後から設定すると LWA_COLORKEY がクリアされるため使用禁止
            self._win.configure(bg=TRANSPARENT_KEY)
            self._win.wm_attributes("-alpha", 1.0)          # alpha をリセットしてから
            self._win.wm_attributes("-transparentcolor", TRANSPARENT_KEY)  # colorkey のみ適用
            # pack が確定してからサイズ取得して描画
            self._win.after(50, self._redraw_trans_overlay)
        else:
            # 透過モードフレームを非表示
            self._trans_outer.pack_forget()
            # Canvas / ウィンドウを通常色に戻す
            self._trans_canvas.configure(bg=UI_COLORS["bg_main"])
            self._trans_outer.configure(bg=UI_COLORS["bg_main"])
            self._win.configure(bg=UI_COLORS["bg_main"])
            self._win.wm_attributes("-transparentcolor", "")
            self._win.wm_attributes("-alpha", 1.0)
            # 通常UIを再表示
            self._status_bar.pack(fill=tk.X, side=tk.TOP)
            self._notebook.pack(fill=tk.BOTH, expand=True)

    # ─── Alt+Tab 登録 / 最小化 ───────────────────────────────────────────────

    def _set_appwindow(self):
        """overrideredirect 時も Alt+Tab に表示されるようスタイルを修正"""
        if self._win is None:
            return
        try:
            hwnd  = ctypes.windll.user32.GetParent(self._win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _minimize(self):
        if self._win is None:
            return
        self._win.overrideredirect(False)
        self._win.iconify()

        def on_restore(event):
            self._win.overrideredirect(True)
            self._win.after(10, self._set_appwindow)
            self._win.unbind("<Map>")

        self._win.bind("<Map>", on_restore)

    # ─── 背景透過 ────────────────────────────────────────────────────────────

    def _apply_transparency(self, transparent: bool):
        if self._win is None:
            return
        if transparent:
            self._win.configure(bg=TRANSPARENT_KEY)
            self._win.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        else:
            self._win.configure(bg=UI_COLORS["bg_main"])
            self._win.wm_attributes("-transparentcolor", "")

    def apply_transparency(self, transparent: bool):
        """外部から透過設定を変更する（設定変更時などに使用）"""
        self._cfg["cw_transparent"] = transparent
        self._apply_transparency(transparent)

    # ─── イベントハンドラ ─────────────────────────────────────────────────────

    def _on_configure(self, event):
        if event.widget is self._win:
            self._cfg["cw_x"]      = self._win.winfo_x()
            self._cfg["cw_y"]      = self._win.winfo_y()
            self._cfg["cw_width"]  = self._win.winfo_width()
            self._cfg["cw_height"] = self._win.winfo_height()

    def _on_topmost_toggle(self):
        val = self.topmost_var.get()
        self._cfg["cw_topmost"] = val
        if self._win:
            self._win.wm_attributes("-topmost", val)

    def _on_window_close(self):
        if self._user_refresh_id and self._win:
            try:
                self._win.after_cancel(self._user_refresh_id)
            except Exception:
                pass
        self._user_refresh_id = None
        if self._win:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None
        # コメントビューを閉じたらアプリ終了
        if self._on_close:
            self._on_close()
