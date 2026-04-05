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
                 topmost_getter=None, pos_getter=None, pos_setter=None,
                 auth_service_getter=None):
        """
        settings_mgr:        SettingsManager インスタンス
        on_settings_changed: 設定保存後に呼ばれるコールバック
        auth_service_getter: () -> AuthService  認証サービスを返す関数（省略可）
        """
        self._master              = master
        self._sm                  = settings_mgr
        self._on_changed          = on_settings_changed
        self._topmost_getter      = topmost_getter or (lambda: False)
        self._pos_getter          = pos_getter or (lambda: None)
        self._pos_setter          = pos_setter or (lambda pos: None)
        self._auth_service_getter = auth_service_getter or (lambda: None)
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
        win.resizable(True, True)
        win.minsize(580, 500)
        pos = self._pos_getter()
        if pos:
            win.geometry(f"640x700+{pos[0]}+{pos[1]}")
        else:
            win.geometry("640x700")
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

        tab_api     = tk.Frame(nb, bg=C["bg_main"])
        tab_conn    = tk.Frame(nb, bg=C["bg_main"])
        tab_display = tk.Frame(nb, bg=C["bg_main"])
        tab_tts     = tk.Frame(nb, bg=C["bg_main"])
        nb.add(tab_api,     text="API")
        nb.add(tab_conn,    text="接続設定")
        nb.add(tab_display, text="表示設定")
        nb.add(tab_tts,     text="読み上げ")

        self._build_api_tab(tab_api)
        self._build_conn_tab(tab_conn)
        self._build_display_tab(tab_display)
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

        # ── 認証方式の選択 ─────────────────────────────────────────────────────
        self._section(parent, "認証方式")

        mode_frame = tk.Frame(parent, bg=C["bg_main"])
        mode_frame.pack(fill=tk.X, padx=14, pady=4)

        current_mode = self._sm.get("auth_mode", "api_key")
        self._auth_mode_var = tk.StringVar(value=current_mode)

        # OAuth ラジオボタン
        oauth_row = tk.Frame(mode_frame, bg=C["bg_main"])
        oauth_row.pack(anchor=tk.W, pady=2)
        tk.Radiobutton(
            oauth_row, text="Google アカウントで認証（OAuth 2.0）— 標準",
            variable=self._auth_mode_var, value="oauth",
            command=self._on_auth_mode_changed,
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_main"], bg=C["bg_main"],
            activebackground=C["bg_main"], selectcolor=C["bg_list"],
        ).pack(side=tk.LEFT)

        # API キーラジオボタン
        apikey_row = tk.Frame(mode_frame, bg=C["bg_main"])
        apikey_row.pack(anchor=tk.W, pady=2)
        tk.Radiobutton(
            apikey_row, text="API キー（補助モード / 簡易利用・検証用）",
            variable=self._auth_mode_var, value="api_key",
            command=self._on_auth_mode_changed,
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_main"], bg=C["bg_main"],
            activebackground=C["bg_main"], selectcolor=C["bg_list"],
        ).pack(side=tk.LEFT)

        # ── OAuth セクション ───────────────────────────────────────────────────
        self._section(parent, "OAuth 2.0 認証")

        oauth_frame = tk.Frame(parent, bg=C["bg_main"])
        oauth_frame.pack(fill=tk.X, padx=14, pady=4)

        # 認証状態ラベル
        auth_svc = self._auth_service_getter()
        status_text = auth_svc.status_label() if auth_svc else "（認証サービス未接続）"
        self._oauth_status_var = tk.StringVar(value=status_text)
        status_lbl = tk.Label(
            oauth_frame, textvariable=self._oauth_status_var,
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg="#88DDAA", bg=C["bg_main"], anchor=tk.W,
        )
        status_lbl.pack(anchor=tk.W, pady=(0, 4))

        btn_row = tk.Frame(oauth_frame, bg=C["bg_main"])
        btn_row.pack(anchor=tk.W)

        tk.Button(
            btn_row, text="Googleアカウントで認証する",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#2A4A2A", fg="#AAFFAA", activebackground="#3A6A3A",
            relief=tk.FLAT, padx=12, pady=3,
            command=self._on_oauth_authenticate,
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            btn_row, text="認証を解除",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["bg_list"], fg=C["fg_label"],
            relief=tk.FLAT, padx=8, pady=3,
            command=self._on_oauth_revoke,
        ).pack(side=tk.LEFT)

        # client_secrets.json のロード状態
        auth_svc = self._auth_service_getter()
        if auth_svc and auth_svc.has_client_config():
            secrets_text = f"client_secrets.json: ロード済み"
            secrets_color = "#88DDAA"
        else:
            secrets_text = "client_secrets.json: 未ロード（OAuth 認証ボタンは使用不可）"
            secrets_color = "#FFAA44"
        self._secrets_status_var = tk.StringVar(value=secrets_text)
        tk.Label(
            oauth_frame, textvariable=self._secrets_status_var,
            font=(FONT_FAMILY, FONT_SIZE_S - 1),
            fg=secrets_color, bg=C["bg_main"], anchor=tk.W,
        ).pack(anchor=tk.W, pady=(4, 0))

        tk.Label(
            oauth_frame,
            text="※ 認証情報はこの PC 内にのみ保存されます。開発者サーバーへは送信しません。\n"
                 "※ OAuth 認証には client_secrets.json をアプリと同フォルダに配置してください。",
            font=(FONT_FAMILY, FONT_SIZE_S - 1),
            fg=C["fg_label"], bg=C["bg_main"], wraplength=480, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

        # ── API キーセクション（補助モード） ─────────────────────────────────
        self._section(parent, "API キー（補助モード）")

        api_outer = tk.Frame(parent, bg=C["bg_main"])
        api_outer.pack(fill=tk.X, padx=14, pady=4)

        tk.Label(
            api_outer,
            text="API キー（補助モード）: 公開データ・検証・小規模デモ向け",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_main"],
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

        tk.Label(
            api_outer,
            text="※ 設定ファイルには平文では保存されません（DPAPI 暗号化）。\n"
                 "※ API キーはリポジトリや共有ファイルに含めないでください。",
            font=(FONT_FAMILY, FONT_SIZE_S - 1),
            fg=C["fg_label"], bg=C["bg_main"], wraplength=480, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

    def _toggle_key_visibility(self):
        self._api_entry.config(show="" if self._show_key_var.get() else "*")

    def _on_auth_mode_changed(self):
        """認証モードのラジオボタン変更時の即時処理（UI 更新のみ）"""
        # 保存は _apply_settings で行う
        pass

    def _on_oauth_authenticate(self):
        """OAuth 認証フローを実行する"""
        auth_svc = self._auth_service_getter()
        if auth_svc is None:
            messagebox.showerror("エラー", "認証サービスが初期化されていません。", parent=self._win)
            return
        if not auth_svc.has_client_config():
            messagebox.showinfo(
                "client_secrets.json が必要",
                "OAuth 認証にはクライアント設定ファイル (client_secrets.json) が必要です。\n"
                "アプリと同じフォルダに配置してから再試行してください。",
                parent=self._win,
            )
            return
        self._oauth_status_var.set("認証中... ブラウザを確認してください")
        if self._win:
            self._win.update()
        success = auth_svc.run_oauth_flow()
        self._oauth_status_var.set(auth_svc.status_label())
        if success:
            messagebox.showinfo("認証完了", "Google アカウントでの認証が完了しました。", parent=self._win)
        else:
            messagebox.showerror("認証失敗", "認証に失敗しました。client_secrets.json を確認してください。", parent=self._win)

    def _on_oauth_revoke(self):
        """OAuth トークンを失効させる"""
        auth_svc = self._auth_service_getter()
        if auth_svc is None:
            return
        if messagebox.askyesno("確認", "認証を解除してよいですか？\n次回接続時に再認証が必要になります。",
                               parent=self._win):
            auth_svc.revoke()
            self._oauth_status_var.set(auth_svc.status_label())

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

    # ── 統合表示設定タブ（監視用 / 配信用 サイドバイサイド比較） ─────────────

    def _build_display_tab(self, parent):
        """
        表示設定の正式タブ。監視用 / 配信用を3カラム（項目名・監視用・配信用）で
        サイドバイサイド比較できる構成。全表示変数をここで初期化する。

        セクション:
          全体設定  — テーマ・Overlay有効
          3-1. ウィンドウ設定
          3-2. 表示要素
          3-3. 文字サイズ
          コピー操作
        """
        C = UI_COLORS

        # ── スクロールコンテナ ───────────────────────────────────────────
        sc = tk.Canvas(parent, bg=C["bg_main"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=sc.yview)
        sc.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(sc, bg=C["bg_main"])
        iw_id = sc.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: sc.configure(scrollregion=sc.bbox("all")))
        sc.bind("<Configure>", lambda e: sc.itemconfig(iw_id, width=e.width))

        # ── 変数初期化（監視用） ────────────────────────────────────────
        self._theme_var = tk.StringVar(value=self._sm.get("color_theme", "ダーク (デフォルト)"))
        self._topmost_var = tk.BooleanVar(value=self._sm.get("cw_topmost", False))
        self._transparent_mode_for_display_var = tk.BooleanVar(
            value=self._sm.get("cw_transparent", False))
        self._comment_alpha_var = tk.StringVar(
            value=str(self._sm.get("cw_comment_alpha", 100)))
        self._display_rows_var = tk.StringVar(
            value=str(self._sm.get("display_rows", 1)))
        self._icon_var = tk.BooleanVar(value=self._sm.get("icon_visible", True))
        self._cw_show_source_var = tk.BooleanVar(value=self._sm.get("cw_show_source", False))
        self._time_var = tk.BooleanVar(value=self._sm.get("time_visible", True))
        self._time_mode_var = tk.StringVar(value=self._sm.get("time_mode", "実時間"))
        self._font_name_var = tk.StringVar(value=str(self._sm.get("font_size_name", 9)))
        self._font_body_var = tk.StringVar(value=str(self._sm.get("font_size_body", 9)))

        # ── 変数初期化（配信用） ────────────────────────────────────────
        self._overlay_enabled_var = tk.BooleanVar(
            value=self._sm.get("overlay_enabled", False))
        self._overlay_topmost_var = tk.BooleanVar(
            value=self._sm.get("overlay_topmost", True))
        self._overlay_transparent_var = tk.BooleanVar(
            value=self._sm.get("overlay_transparent", False))
        self._overlay_mode_var = tk.StringVar(
            value=self._sm.get("overlay_display_mode", "timed"))
        self._overlay_duration_var = tk.StringVar(
            value=str(self._sm.get("overlay_duration_sec",
                                   self._sm.get("overlay_duration", 5))))
        self._overlay_show_icon_var = tk.BooleanVar(
            value=self._sm.get("overlay_show_icon", True))
        self._overlay_show_source_var = tk.BooleanVar(
            value=self._sm.get("overlay_show_source", False))
        self._ov_fn_var = tk.StringVar(
            value=str(self._sm.get("overlay_font_size_name", 9)))
        self._ov_fb_var = tk.StringVar(
            value=str(self._sm.get("overlay_font_size_body", 11)))

        # ── ローカルヘルパー ────────────────────────────────────────────
        COL_W = (3, 2, 2)   # weight: 項目名, 監視用, 配信用
        COL_MIN = (150, 110, 110)

        def _apply_cols(fr):
            for i, (w, m) in enumerate(zip(COL_W, COL_MIN)):
                fr.columnconfigure(i, weight=w, minsize=m)

        def grid_row(label, mon_fn, ov_fn):
            fr = tk.Frame(inner, bg=C["bg_main"])
            fr.pack(fill=tk.X, padx=12, pady=1)
            _apply_cols(fr)
            tk.Label(fr, text=label, font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_main"], anchor=tk.W
                     ).grid(row=0, column=0, sticky=tk.EW, padx=(4, 8))
            mon_fn(fr).grid(row=0, column=1, sticky=tk.W, padx=4)
            ov_fn(fr).grid(row=0, column=2, sticky=tk.W, padx=4)

        def chk(parent, var):
            return tk.Checkbutton(parent, variable=var,
                                  bg=C["bg_main"], activebackground=C["bg_main"],
                                  selectcolor=C["bg_list"])

        def dash(parent):
            return tk.Label(parent, text="—", font=(FONT_FAMILY, FONT_SIZE_S),
                            fg=C["fg_label"], bg=C["bg_main"])

        def spn(parent, var, lo=7, hi=72, width=4, inc=1):
            f = tk.Frame(parent, bg=C["bg_main"])
            ttk.Spinbox(f, textvariable=var, from_=lo, to=hi, increment=inc,
                        width=width, font=(FONT_FAMILY, FONT_SIZE_S)).pack(side=tk.LEFT)
            return f

        def cmb(parent, var, values, width=8):
            f = tk.Frame(parent, bg=C["bg_main"])
            ttk.Combobox(f, textvariable=var, values=values, state="readonly",
                         width=width, font=(FONT_FAMILY, FONT_SIZE_S)).pack(side=tk.LEFT)
            return f

        def sec(text):
            tk.Label(inner, text=text, font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                     fg=C["fg_label"], bg=C["bg_main"]
                     ).pack(anchor=tk.W, padx=14, pady=(10, 2))
            tk.Frame(inner, bg=C["border"], height=1).pack(fill=tk.X, padx=12, pady=2)

        # ── 全体設定 ──────────────────────────────────────────────────────
        sec("全体設定")
        r_theme = self._labeled_row(inner, "カラーテーマ:")
        ttk.Combobox(r_theme, textvariable=self._theme_var,
                     values=list(COLOR_THEMES.keys()), state="readonly", width=20,
                     font=(FONT_FAMILY, FONT_SIZE_S)
                     ).pack(side=tk.LEFT, padx=4)

        tk.Checkbutton(inner, text="配信用 Overlay を有効にする",
                       variable=self._overlay_enabled_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]
                       ).pack(anchor=tk.W, padx=18, pady=2)
        tk.Label(inner, text="※ Overlay は監視用コメントビューとは独立した配信用ウィンドウです。",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"],
                 wraplength=560, justify=tk.LEFT
                 ).pack(anchor=tk.W, padx=18, pady=(0, 4))

        # ── 3カラムヘッダ ──────────────────────────────────────────────────
        tk.Frame(inner, bg=C["border"], height=1).pack(fill=tk.X, padx=12, pady=(4, 0))
        hdr = tk.Frame(inner, bg=C["bg_panel"])
        hdr.pack(fill=tk.X, padx=12, pady=0)
        _apply_cols(hdr)
        for col, text in enumerate(["設定項目", "監視用", "配信用 (Overlay)"]):
            tk.Label(hdr, text=text, font=(FONT_FAMILY, FONT_SIZE_S, "bold"),
                     fg=C["fg_label"], bg=C["bg_panel"], anchor=tk.W
                     ).grid(row=0, column=col, sticky=tk.EW, padx=4, pady=3)
        tk.Frame(inner, bg=C["border"], height=1).pack(fill=tk.X, padx=12, pady=0)

        # ── 3-1. ウィンドウ設定 ──────────────────────────────────────────
        sec("3-1. ウィンドウ設定")

        grid_row("最前面表示",
                 lambda p: chk(p, self._topmost_var),
                 lambda p: chk(p, self._overlay_topmost_var))

        grid_row("透過モード",
                 lambda p: chk(p, self._transparent_mode_for_display_var),
                 lambda p: chk(p, self._overlay_transparent_var))

        def _mon_alpha(p):
            f = tk.Frame(p, bg=C["bg_main"])
            ttk.Spinbox(f, textvariable=self._comment_alpha_var,
                        from_=10, to=100, increment=5, width=5,
                        font=(FONT_FAMILY, FONT_SIZE_S)).pack(side=tk.LEFT)
            tk.Label(f, text="%", font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_main"]).pack(side=tk.LEFT, padx=(2, 0))
            return f
        grid_row("透過率 (監視用)", _mon_alpha, dash)

        grid_row("表示行数 (監視用)",
                 lambda p: cmb(p, self._display_rows_var, ["1", "2"], width=4),
                 dash)

        grid_row("表示モード (配信用)",
                 dash,
                 lambda p: cmb(p, self._overlay_mode_var, ["timed", "always"], width=8))

        def _ov_dur(p):
            f = tk.Frame(p, bg=C["bg_main"])
            ttk.Spinbox(f, textvariable=self._overlay_duration_var,
                        from_=1, to=120, width=4,
                        font=(FONT_FAMILY, FONT_SIZE_S)).pack(side=tk.LEFT)
            tk.Label(f, text="秒", font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_main"]).pack(side=tk.LEFT, padx=(2, 0))
            return f
        grid_row("表示秒数 / timed (配信用)", dash, _ov_dur)

        # ── 3-2. 表示要素 ────────────────────────────────────────────────
        sec("3-2. 表示要素")

        grid_row("アイコン表示",
                 lambda p: chk(p, self._icon_var),
                 lambda p: chk(p, self._overlay_show_icon_var))

        grid_row("接続先名表示",
                 lambda p: chk(p, self._cw_show_source_var),
                 lambda p: chk(p, self._overlay_show_source_var))

        grid_row("時刻表示 (監視用)",
                 lambda p: chk(p, self._time_var),
                 dash)

        grid_row("時刻方式 (監視用)",
                 lambda p: cmb(p, self._time_mode_var,
                               ["実時間", "経過時間"], width=8),
                 dash)

        # ── 3-3. 文字サイズ ──────────────────────────────────────────────
        sec("3-3. 文字サイズ")

        grid_row("投稿者名フォントサイズ",
                 lambda p: spn(p, self._font_name_var),
                 lambda p: spn(p, self._ov_fn_var))

        grid_row("本文フォントサイズ",
                 lambda p: spn(p, self._font_body_var),
                 lambda p: spn(p, self._ov_fb_var))

        # ── コピー操作 ────────────────────────────────────────────────────
        tk.Frame(inner, bg=C["border"], height=1).pack(fill=tk.X, padx=12, pady=(12, 4))
        btn_row = tk.Frame(inner, bg=C["bg_main"])
        btn_row.pack(anchor=tk.W, padx=12, pady=4)
        tk.Button(btn_row, text="監視用 → 配信用へコピー",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_main"],
                  relief=tk.FLAT, padx=8, pady=2,
                  command=self._copy_monitor_to_overlay
                  ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="配信用 → 監視用へコピー",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_main"],
                  relief=tk.FLAT, padx=8, pady=2,
                  command=self._copy_overlay_to_monitor
                  ).pack(side=tk.LEFT)
        tk.Label(inner,
                 text="※ 配信用透過モード: 透過時はドラッグ帯が非表示になります。"
                      "位置・サイズは事前に確定させてください。",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"],
                 wraplength=560, justify=tk.LEFT
                 ).pack(anchor=tk.W, padx=14, pady=(4, 8))

    def _copy_monitor_to_overlay(self):
        """監視用の設定を配信用へコピーする"""
        try:
            self._ov_fn_var.set(self._font_name_var.get())
            self._ov_fb_var.set(self._font_body_var.get())
            self._overlay_show_icon_var.set(self._icon_var.get())
            self._overlay_show_source_var.set(self._cw_show_source_var.get())
            self._overlay_topmost_var.set(self._topmost_var.get())
        except Exception:
            pass

    def _copy_overlay_to_monitor(self):
        """配信用の設定を監視用へコピーする"""
        try:
            self._font_name_var.set(self._ov_fn_var.get())
            self._font_body_var.set(self._ov_fb_var.get())
            self._icon_var.set(self._overlay_show_icon_var.get())
            self._cw_show_source_var.set(self._overlay_show_source_var.get())
            self._topmost_var.set(self._overlay_topmost_var.get())
        except Exception:
            pass

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

        # 音量
        vol_row = tk.Frame(parent, bg=C["bg_main"])
        vol_row.pack(anchor=tk.W, padx=18, pady=2)
        tk.Label(vol_row, text="音量:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)
        self._tts_volume_var = tk.IntVar(value=self._sm.get("tts_volume", 100))
        tk.Scale(vol_row, variable=self._tts_volume_var,
                 from_=0, to=100, orient=tk.HORIZONTAL, length=160,
                 resolution=1, showvalue=True,
                 bg=C["bg_main"], fg=C["fg_main"],
                 troughcolor=C["bg_list"], activebackground=C["accent"],
                 highlightthickness=0, bd=0,
                 font=(FONT_FAMILY, FONT_SIZE_S)
                 ).pack(side=tk.LEFT, padx=(4, 0))

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

        # 読み上げ速度・間隔
        self._section(parent, "読み上げ速度・間隔")

        r_speed = self._labeled_row(parent, "読み上げ速度 (SAPI Rate, -10〜10):")
        self._tts_speed_var = tk.StringVar(value=str(self._sm.get("tts_speed", 0)))
        ttk.Spinbox(r_speed, textvariable=self._tts_speed_var,
                    from_=-10, to=10, increment=1, width=5,
                    font=(FONT_FAMILY, FONT_SIZE_S)
                    ).pack(side=tk.LEFT, padx=4)
        tk.Label(r_speed, text="(0=標準  正=速い  負=遅い)",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)

        r_intv = self._labeled_row(parent, "コメント間インターバル:")
        self._tts_interval_var = tk.StringVar(
            value=str(self._sm.get("tts_interval_sec", 0.0)))
        ttk.Spinbox(r_intv, textvariable=self._tts_interval_var,
                    from_=0.0, to=10.0, increment=0.5, width=5,
                    font=(FONT_FAMILY, FONT_SIZE_S)
                    ).pack(side=tk.LEFT, padx=4)
        tk.Label(r_intv, text="秒  (0=なし)",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)

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
            "auth_mode": self._auth_mode_var.get(),
            "display_rows":       int(self._display_rows_var.get()),
            "font_size_name":     int(self._font_name_var.get()),
            "font_size_body":     int(self._font_body_var.get()),
            "icon_visible":       self._icon_var.get(),
            "time_visible":       self._time_var.get(),
            "time_mode":          self._time_mode_var.get(),
            "color_theme":        self._theme_var.get(),
            "cw_topmost":         self._topmost_var.get(),
            "cw_transparent":     self._transparent_mode_for_display_var.get(),
            "cw_show_source":     self._cw_show_source_var.get(),
            "cw_comment_alpha":   int(self._comment_alpha_var.get()),
            "tts_enabled":        self._tts_enabled_var.get(),
            "tts_volume":         self._tts_volume_var.get(),
            "tts_normal":         self._tts_normal_var.get(),
            "tts_superchat":      self._tts_sc_var.get(),
            "tts_owner":          self._tts_owner_var.get(),
            "tts_mod":            self._tts_mod_var.get(),
            "tts_member":         self._tts_member_var.get(),
            "tts_simplify_name":  self._tts_simplify_var.get(),
            "tts_read_source_name": self._tts_read_source_var.get(),
            "tts_speed":          int(self._tts_speed_var.get()),
            "tts_interval_sec":   float(self._tts_interval_var.get()),
            # 接続設定
            "conn1_enabled":      self._conn1_enabled_var.get(),
            "conn1_name":         self._conn1_name_var.get().strip(),
            "conn1_url":          self._conn1_url_var.get().strip(),
            "conn2_enabled":      self._conn2_enabled_var.get(),
            "conn2_name":         self._conn2_name_var.get().strip(),
            "conn2_url":          self._conn2_url_var.get().strip(),
            # Overlay
            "overlay_enabled":         self._overlay_enabled_var.get(),
            "overlay_display_mode":    self._overlay_mode_var.get(),
            "overlay_duration_sec":    int(self._overlay_duration_var.get()),
            "overlay_topmost":         self._overlay_topmost_var.get(),
            "overlay_transparent":     self._overlay_transparent_var.get(),
            "overlay_show_source":     self._overlay_show_source_var.get(),
            "overlay_show_icon":       self._overlay_show_icon_var.get(),
            "overlay_font_size_name":  int(self._ov_fn_var.get()),
            "overlay_font_size_body":  int(self._ov_fb_var.get()),
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
        self._auth_mode_var.set(self._sm.get("auth_mode", "api_key"))
        auth_svc = self._auth_service_getter()
        if auth_svc and hasattr(self, "_oauth_status_var"):
            self._oauth_status_var.set(auth_svc.status_label())
        if auth_svc and hasattr(self, "_secrets_status_var"):
            if auth_svc.has_client_config():
                self._secrets_status_var.set("client_secrets.json: ロード済み")
            else:
                self._secrets_status_var.set("client_secrets.json: 未ロード（OAuth 認証ボタンは使用不可）")
        self._theme_var.set(self._sm.get("color_theme", "ダーク (デフォルト)"))
        self._display_rows_var.set(str(self._sm.get("display_rows", 1)))
        self._font_name_var.set(str(self._sm.get("font_size_name", 9)))
        self._font_body_var.set(str(self._sm.get("font_size_body", 9)))
        self._icon_var.set(self._sm.get("icon_visible", True))
        self._time_var.set(self._sm.get("time_visible", True))
        self._time_mode_var.set(self._sm.get("time_mode", "実時間"))
        self._topmost_var.set(self._sm.get("cw_topmost", False))
        self._transparent_mode_for_display_var.set(self._sm.get("cw_transparent", False))
        self._cw_show_source_var.set(self._sm.get("cw_show_source", False))
        self._comment_alpha_var.set(str(self._sm.get("cw_comment_alpha", 100)))
        self._tts_enabled_var.set(self._sm.get("tts_enabled", False))
        self._tts_volume_var.set(self._sm.get("tts_volume", 100))
        self._tts_normal_var.set(self._sm.get("tts_normal", True))
        self._tts_sc_var.set(self._sm.get("tts_superchat", True))
        self._tts_owner_var.set(self._sm.get("tts_owner", True))
        self._tts_mod_var.set(self._sm.get("tts_mod", True))
        self._tts_member_var.set(self._sm.get("tts_member", False))
        self._tts_simplify_var.set(self._sm.get("tts_simplify_name", True))
        self._tts_read_source_var.set(self._sm.get("tts_read_source_name", False))
        self._tts_speed_var.set(str(self._sm.get("tts_speed", 0)))
        self._tts_interval_var.set(str(self._sm.get("tts_interval_sec", 0.0)))
        # Overlay
        self._overlay_enabled_var.set(self._sm.get("overlay_enabled", False))
        self._overlay_mode_var.set(self._sm.get("overlay_display_mode", "timed"))
        self._overlay_duration_var.set(str(self._sm.get("overlay_duration_sec",
                                           self._sm.get("overlay_duration", 5))))
        self._overlay_topmost_var.set(self._sm.get("overlay_topmost", True))
        self._overlay_transparent_var.set(self._sm.get("overlay_transparent", False))
        self._overlay_show_source_var.set(self._sm.get("overlay_show_source", False))
        self._overlay_show_icon_var.set(self._sm.get("overlay_show_icon", True))
        self._ov_fn_var.set(str(self._sm.get("overlay_font_size_name", 9)))
        self._ov_fb_var.set(str(self._sm.get("overlay_font_size_body", 11)))
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

    def _labeled_row_in(self, parent, label_text: str) -> tk.Frame:
        """スクロール inner フレーム内用（_labeled_row と同一だが parent を直接受ける）"""
        return self._labeled_row(parent, label_text)
