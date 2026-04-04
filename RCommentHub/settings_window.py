"""
RCommentHub — 設定ウィンドウ
API キー・表示設定・読み上げ設定をまとめて編集する
"""

import tkinter as tk
from tkinter import ttk, messagebox

from constants import UI_COLORS, FONT_FAMILY, FONT_SIZE_S, FONT_SIZE_M, COLOR_THEMES


class SettingsWindow:
    """アプリ設定ウィンドウ（Toplevel）"""

    def __init__(self, master: tk.Tk, settings_mgr, on_settings_changed=None,
                 topmost_getter=None, pos_getter=None, pos_setter=None):
        """
        settings_mgr: SettingsManager インスタンス
        on_settings_changed: 設定保存後に呼ばれるコールバック
        """
        self._master         = master
        self._sm             = settings_mgr
        self._on_changed     = on_settings_changed
        self._topmost_getter = topmost_getter or (lambda: False)
        self._pos_getter     = pos_getter or (lambda: None)
        self._pos_setter     = pos_setter or (lambda pos: None)
        self._win: tk.Toplevel | None = None

    def open(self):
        if self._win is not None:
            try:
                self._load_values()
                self._win.deiconify()
                self._win.lift()
                self._win.focus_force()
                return
            except (tk.TclError, AttributeError):
                self._win = None

        C = UI_COLORS
        win = tk.Toplevel(self._master)
        self._win = win
        win.title("RCommentHub — 設定")
        win.configure(bg=C["bg_main"])
        win.resizable(False, True)
        pos = self._pos_getter()
        if pos:
            win.geometry(f"460x620+{pos[0]}+{pos[1]}")
        else:
            win.geometry("460x620")
        win.wm_attributes("-topmost", self._topmost_getter())
        win.bind("<Configure>", self._on_configure)

        # ── タブ ──────────────────────────────────────────────────────────────
        style = ttk.Style()
        style.configure("Settings.TNotebook",
                        background=C["bg_main"], tabmargins=[2, 2, 0, 0])
        style.configure("Settings.TNotebook.Tab",
                        background=C["bg_panel"], foreground=C["fg_label"],
                        font=(FONT_FAMILY, FONT_SIZE_S), padding=[10, 3])
        style.map("Settings.TNotebook.Tab",
                  background=[("selected", C["accent"])],
                  foreground=[("selected", "#FFFFFF")])
        style.map("TCombobox",
                  fieldbackground=[("readonly", C["bg_list"]),
                                   ("disabled", C["bg_panel"])],
                  foreground=[("readonly", C["fg_main"]),
                               ("disabled", C["fg_label"])],
                  selectbackground=[("readonly", C["accent"])],
                  selectforeground=[("readonly", "#FFFFFF")])

        nb = ttk.Notebook(win, style="Settings.TNotebook")
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        tab_api  = tk.Frame(nb, bg=C["bg_main"])
        tab_conn = tk.Frame(nb, bg=C["bg_main"])
        tab_view = tk.Frame(nb, bg=C["bg_main"])
        tab_tts  = tk.Frame(nb, bg=C["bg_main"])
        nb.add(tab_api,  text="API")
        nb.add(tab_conn, text="接続設定")
        nb.add(tab_view, text="表示")
        nb.add(tab_tts,  text="読み上げ")

        self._build_api_tab(tab_api)
        self._build_conn_tab(tab_conn)
        self._build_view_tab(tab_view)
        self._build_tts_tab(tab_tts)

        # ── ボタン行 ──────────────────────────────────────────────────────────
        btn_frame = tk.Frame(win, bg=C["bg_main"])
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        tk.Button(btn_frame, text="保存して閉じる",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["accent"], fg="#FFFFFF", activebackground="#4A6A9A",
                  relief=tk.FLAT, padx=12, pady=4,
                  command=self._on_save
                  ).pack(side=tk.RIGHT)

        tk.Button(btn_frame, text="適用",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_main"],
                  relief=tk.FLAT, padx=12, pady=4,
                  command=self._on_apply
                  ).pack(side=tk.RIGHT, padx=(0, 4))

        tk.Button(btn_frame, text="キャンセル",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_label"],
                  relief=tk.FLAT, padx=12, pady=4,
                  command=self._close
                  ).pack(side=tk.RIGHT, padx=(0, 4))

        win.protocol("WM_DELETE_WINDOW", self._close)

    # ── API タブ ──────────────────────────────────────────────────────────────

    def _build_api_tab(self, parent):
        C = UI_COLORS

        self._section(parent, "YouTube Data API キー")

        api_outer = tk.Frame(parent, bg=C["bg_main"])
        api_outer.pack(fill=tk.X, padx=14, pady=4)
        tk.Label(api_outer, text="API キー (DPAPI 暗号化で保存されます):",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(anchor=tk.W)

        entry_row = tk.Frame(api_outer, bg=C["bg_main"])
        entry_row.pack(fill=tk.X, pady=2)
        self._api_key_var = tk.StringVar(value=self._sm.api_key)
        self._api_entry = tk.Entry(
            entry_row, textvariable=self._api_key_var,
            show="*", bg=C["bg_list"], fg=C["fg_main"],
            insertbackground=C["fg_main"],
            font=(FONT_FAMILY, FONT_SIZE_S), relief=tk.FLAT,
        )
        self._api_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._show_key_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            entry_row, text="表示",
            variable=self._show_key_var,
            command=self._toggle_key_visibility,
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_main"],
            activebackground=C["bg_main"],
            selectcolor=C["bg_list"],
        ).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(api_outer,
                 text="※ 設定ファイルには平文では保存されません。同じ PC でのみ復号できます。",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"], wraplength=380,
                 justify=tk.LEFT
                 ).pack(anchor=tk.W, pady=(4, 0))

    def _toggle_key_visibility(self):
        self._api_entry.config(show="" if self._show_key_var.get() else "*")

    # ── 接続設定タブ ──────────────────────────────────────────────────────────

    def _build_conn_tab(self, parent):
        C = UI_COLORS

        # スクロール対応フレーム
        canvas = tk.Canvas(parent, bg=C["bg_main"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas, bg=C["bg_main"])
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            inner_id, width=e.width))

        def _conn_block(parent, conn_id, label_text):
            self._section(parent, label_text)
            pad = {"padx": 18, "pady": 2}

            # 有効/無効
            en_default = True if conn_id == "conn1" else False
            en_var = tk.BooleanVar(value=self._sm.get(f"{conn_id}_enabled", en_default))
            setattr(self, f"_{conn_id}_enabled_var", en_var)
            tk.Checkbutton(parent, text="有効", variable=en_var,
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_main"],
                           activebackground=C["bg_main"],
                           selectcolor=C["bg_list"]
                           ).pack(anchor=tk.W, **pad)

            # 表示名
            r_name = self._labeled_row(parent, "表示名:")
            name_default = "接続1" if conn_id == "conn1" else "接続2"
            name_var = tk.StringVar(value=self._sm.get(f"{conn_id}_name", name_default))
            setattr(self, f"_{conn_id}_name_var", name_var)
            tk.Entry(r_name, textvariable=name_var, width=20,
                     bg=C["bg_list"], fg=C["fg_main"],
                     insertbackground=C["fg_main"],
                     font=(FONT_FAMILY, FONT_SIZE_S), relief=tk.FLAT
                     ).pack(side=tk.LEFT, padx=4)

            # URL / 動画ID
            tk.Label(parent, text="YouTube URL または 動画ID:",
                     font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_main"]
                     ).pack(anchor=tk.W, padx=18, pady=(4, 0))
            url_var = tk.StringVar(value=self._sm.get(f"{conn_id}_url", ""))
            setattr(self, f"_{conn_id}_url_var", url_var)
            tk.Entry(parent, textvariable=url_var,
                     bg=C["bg_list"], fg=C["fg_main"],
                     insertbackground=C["fg_main"],
                     font=(FONT_FAMILY, FONT_SIZE_S), relief=tk.FLAT
                     ).pack(fill=tk.X, padx=18, pady=(0, 4))

        _conn_block(inner, "conn1", "接続1（メイン）")
        tk.Label(inner, text="※ 接続1は「接続」ダイアログからも URL を入力できます。",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"], wraplength=380, justify=tk.LEFT
                 ).pack(anchor=tk.W, padx=18, pady=(0, 6))

        _conn_block(inner, "conn2", "接続2（サブ）")
        tk.Label(inner, text="※ 接続2は接続1が開始されると自動的に接続を試みます。",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"], wraplength=380, justify=tk.LEFT
                 ).pack(anchor=tk.W, padx=18, pady=(0, 6))

    # ── 表示タブ ──────────────────────────────────────────────────────────────

    def _build_view_tab(self, parent):
        C = UI_COLORS

        # テーマ選択（最初に配置）
        self._section(parent, "テーマ")
        r_theme = self._labeled_row(parent, "カラーテーマ:")
        self._theme_var = tk.StringVar(
            value=self._sm.get("color_theme", "ダーク (デフォルト)"))
        ttk.Combobox(r_theme, textvariable=self._theme_var,
                     values=list(COLOR_THEMES.keys()), state="readonly", width=18,
                     font=(FONT_FAMILY, FONT_SIZE_S)
                     ).pack(side=tk.LEFT, padx=4)

        self._section(parent, "コメント表示")

        # 表示行数
        row = self._labeled_row(parent, "表示行数:")
        self._display_rows_var = tk.StringVar(
            value=str(self._sm.get("display_rows", 1)))
        ttk.Combobox(row, textvariable=self._display_rows_var,
                     values=["1", "2"], state="readonly", width=4,
                     font=(FONT_FAMILY, FONT_SIZE_S)
                     ).pack(side=tk.LEFT, padx=4)

        # フォントサイズ
        for label_text, attr, cfg_key, default in [
            ("ユーザー名フォントサイズ:", "_font_name_var", "font_size_name", 9),
            ("本文フォントサイズ:",       "_font_body_var", "font_size_body", 9),
        ]:
            r = self._labeled_row(parent, label_text)
            var = tk.StringVar(value=str(self._sm.get(cfg_key, default)))
            ttk.Spinbox(r, textvariable=var, from_=7, to=24, width=4,
                        font=(FONT_FAMILY, FONT_SIZE_S)).pack(side=tk.LEFT, padx=4)
            setattr(self, attr, var)

        # ON/OFF チェックボックス
        for attr, cfg_key, default, label in [
            ("_icon_var",  "icon_visible",  True,  "アイコン表示"),
            ("_time_var",  "time_visible",  True,  "時刻表示"),
        ]:
            var = tk.BooleanVar(value=self._sm.get(cfg_key, default))
            setattr(self, attr, var)
            tk.Checkbutton(parent, text=label, variable=var,
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_main"],
                           activebackground=C["bg_main"],
                           selectcolor=C["bg_list"]
                           ).pack(anchor=tk.W, padx=18, pady=1)

        # 時刻方式
        r2 = self._labeled_row(parent, "時刻方式:")
        self._time_mode_var = tk.StringVar(value=self._sm.get("time_mode", "実時間"))
        ttk.Combobox(r2, textvariable=self._time_mode_var,
                     values=["実時間", "経過時間"], state="readonly", width=8,
                     font=(FONT_FAMILY, FONT_SIZE_S)
                     ).pack(side=tk.LEFT, padx=4)

        self._section(parent, "その他")
        self._topmost_var = tk.BooleanVar(value=self._sm.get("cw_topmost", False))
        tk.Checkbutton(parent, text="コメントビュー最前面表示",
                       variable=self._topmost_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(anchor=tk.W, padx=18, pady=4)

        # コメント透過率（透過モード時の -alpha 値）
        r4 = self._labeled_row(parent, "ウィンドウ透過率 (%):")
        self._comment_alpha_var = tk.StringVar(
            value=str(self._sm.get("cw_comment_alpha", 100)))
        ttk.Spinbox(r4, textvariable=self._comment_alpha_var,
                    from_=10, to=100, increment=5, width=5,
                    font=(FONT_FAMILY, FONT_SIZE_S)
                    ).pack(side=tk.LEFT, padx=4)
        tk.Label(r4, text="(透過モード時に適用。コメントを含む全体に影響 / 最小10%)",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)

    # ── 読み上げタブ ──────────────────────────────────────────────────────────

    def _build_tts_tab(self, parent):
        C = UI_COLORS

        # 読み上げ全般
        self._section(parent, "読み上げ全般")
        self._tts_enabled_var = tk.BooleanVar(value=self._sm.get("tts_enabled", False))
        tk.Checkbutton(parent, text="読み上げを有効にする", variable=self._tts_enabled_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(anchor=tk.W, padx=18, pady=2)

        # 読み上げるコメント種別
        self._section(parent, "読み上げるコメント種別")
        for attr, cfg_key, default, label in [
            ("_tts_normal_var", "tts_normal",    True,  "通常コメント"),
            ("_tts_sc_var",     "tts_superchat", True,  "Super Chat / Super Sticker"),
        ]:
            var = tk.BooleanVar(value=self._sm.get(cfg_key, default))
            setattr(self, attr, var)
            tk.Checkbutton(parent, text=label, variable=var,
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_main"],
                           activebackground=C["bg_main"],
                           selectcolor=C["bg_list"]
                           ).pack(anchor=tk.W, padx=18, pady=1)

        # 読み上げる投稿者属性
        self._section(parent, "読み上げる投稿者属性")
        for attr, cfg_key, default, label in [
            ("_tts_owner_var",  "tts_owner",  True,  "配信者 (Owner) のコメント"),
            ("_tts_mod_var",    "tts_mod",    True,  "Mod のコメント"),
            ("_tts_member_var", "tts_member", False, "Member のコメント"),
        ]:
            var = tk.BooleanVar(value=self._sm.get(cfg_key, default))
            setattr(self, attr, var)
            tk.Checkbutton(parent, text=label, variable=var,
                           font=(FONT_FAMILY, FONT_SIZE_S),
                           fg=C["fg_main"], bg=C["bg_main"],
                           activebackground=C["bg_main"],
                           selectcolor=C["bg_list"]
                           ).pack(anchor=tk.W, padx=18, pady=1)

        # オプション
        self._section(parent, "オプション")
        self._tts_simplify_var = tk.BooleanVar(value=self._sm.get("tts_simplify_name", True))
        tk.Checkbutton(parent, text="投稿者名を簡略化して読み上げる（英数字のみの名前を省略）",
                       variable=self._tts_simplify_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(anchor=tk.W, padx=18, pady=2)
        self._tts_read_source_var = tk.BooleanVar(value=self._sm.get("tts_read_source_name", False))
        tk.Checkbutton(parent, text="接続先名を先頭で読み上げる（マルチ接続時の識別用）",
                       variable=self._tts_read_source_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(anchor=tk.W, padx=18, pady=2)

    # ── 保存 ─────────────────────────────────────────────────────────────────

    def _apply_settings(self) -> bool:
        """設定を保存してコールバックを呼ぶ（共通処理）。成功時 True を返す。"""
        api_key = self._api_key_var.get().strip()
        if api_key != self._sm.api_key:
            try:
                self._sm.set_api_key(api_key)
            except Exception as e:
                messagebox.showerror("エラー", f"API キーの保存に失敗しました:\n{e}",
                                     parent=self._win)
                return False

        updates = {
            "display_rows":       int(self._display_rows_var.get()),
            "font_size_name":     int(self._font_name_var.get()),
            "font_size_body":     int(self._font_body_var.get()),
            "icon_visible":       self._icon_var.get(),
            "time_visible":       self._time_var.get(),
            "time_mode":          self._time_mode_var.get(),
            "color_theme":        self._theme_var.get(),
            "cw_topmost":         self._topmost_var.get(),
            "cw_comment_alpha":   int(self._comment_alpha_var.get()),
            "tts_enabled":        self._tts_enabled_var.get(),
            "tts_normal":         self._tts_normal_var.get(),
            "tts_superchat":      self._tts_sc_var.get(),
            "tts_owner":          self._tts_owner_var.get(),
            "tts_mod":            self._tts_mod_var.get(),
            "tts_member":         self._tts_member_var.get(),
            "tts_simplify_name":  self._tts_simplify_var.get(),
            "tts_read_source_name": self._tts_read_source_var.get(),
            # 接続設定
            "conn1_enabled":      self._conn1_enabled_var.get(),
            "conn1_name":         self._conn1_name_var.get().strip(),
            "conn1_url":          self._conn1_url_var.get().strip(),
            "conn2_enabled":      self._conn2_enabled_var.get(),
            "conn2_name":         self._conn2_name_var.get().strip(),
            "conn2_url":          self._conn2_url_var.get().strip(),
        }
        self._sm.update(updates)

        if self._on_changed:
            self._on_changed()
        return True

    def _on_apply(self):
        """設定を保存してコメントビューに即時反映（ウィンドウは閉じない）"""
        self._apply_settings()

    def _on_save(self):
        """設定を保存して閉じる"""
        if self._apply_settings():
            self._close()

    def _on_configure(self, event):
        if self._win and event.widget is self._win:
            self._pos_setter([self._win.winfo_x(), self._win.winfo_y()])

    def _close(self):
        """設定ウィンドウを非表示にする（destroy せず withdraw で保持）"""
        if self._win:
            try:
                self._win.withdraw()
            except tk.TclError:
                pass

    def _load_values(self):
        """_sm から設定値を読み込んで UI 変数に反映する（再表示時に呼ぶ）"""
        self._api_key_var.set(self._sm.api_key)
        self._theme_var.set(self._sm.get("color_theme", "ダーク (デフォルト)"))
        self._display_rows_var.set(str(self._sm.get("display_rows", 1)))
        self._font_name_var.set(str(self._sm.get("font_size_name", 9)))
        self._font_body_var.set(str(self._sm.get("font_size_body", 9)))
        self._icon_var.set(self._sm.get("icon_visible", True))
        self._time_var.set(self._sm.get("time_visible", True))
        self._time_mode_var.set(self._sm.get("time_mode", "実時間"))
        self._topmost_var.set(self._sm.get("cw_topmost", False))
        self._comment_alpha_var.set(str(self._sm.get("cw_comment_alpha", 100)))
        self._tts_enabled_var.set(self._sm.get("tts_enabled", False))
        self._tts_normal_var.set(self._sm.get("tts_normal", True))
        self._tts_sc_var.set(self._sm.get("tts_superchat", True))
        self._tts_owner_var.set(self._sm.get("tts_owner", True))
        self._tts_mod_var.set(self._sm.get("tts_mod", True))
        self._tts_member_var.set(self._sm.get("tts_member", False))
        self._tts_simplify_var.set(self._sm.get("tts_simplify_name", True))
        self._tts_read_source_var.set(self._sm.get("tts_read_source_name", False))
        # 接続設定
        self._conn1_enabled_var.set(self._sm.get("conn1_enabled", True))
        self._conn1_name_var.set(self._sm.get("conn1_name", "接続1"))
        self._conn1_url_var.set(self._sm.get("conn1_url", ""))
        self._conn2_enabled_var.set(self._sm.get("conn2_enabled", False))
        self._conn2_name_var.set(self._sm.get("conn2_name", "接続2"))
        self._conn2_url_var.set(self._sm.get("conn2_url", ""))

    # ── ヘルパー ──────────────────────────────────────────────────────────────

    def _section(self, parent, text: str):
        C = UI_COLORS
        tk.Label(parent, text=text,
                 font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(anchor=tk.W, padx=14, pady=(10, 2))
        tk.Frame(parent, bg=C["border"], height=1).pack(fill=tk.X, padx=14)

    def _labeled_row(self, parent, label_text: str) -> tk.Frame:
        C = UI_COLORS
        row = tk.Frame(parent, bg=C["bg_main"])
        row.pack(anchor=tk.W, padx=18, pady=2)
        tk.Label(row, text=label_text,
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)
        return row
