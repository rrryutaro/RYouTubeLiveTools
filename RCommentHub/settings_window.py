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
                 auth_service_getter=None, twitch_auth_getter=None,
                 overlay_placement_cb=None):
        """
        settings_mgr:        SettingsManager インスタンス
        on_settings_changed: 設定保存後に呼ばれるコールバック
        auth_service_getter: () -> AuthService         YouTube 認証サービスを返す関数（省略可）
        twitch_auth_getter:  () -> TwitchAuthService   Twitch 認証サービスを返す関数（省略可）
        """
        self._master               = master
        self._sm                   = settings_mgr
        self._on_changed           = on_settings_changed
        self._topmost_getter       = topmost_getter or (lambda: False)
        self._pos_getter           = pos_getter or (lambda: None)
        self._pos_setter           = pos_setter or (lambda pos: None)
        self._auth_service_getter  = auth_service_getter or (lambda: None)
        self._twitch_auth_getter   = twitch_auth_getter or (lambda: None)
        self._overlay_placement_cb = overlay_placement_cb
        self._win: tk.Toplevel | None = None
        self._win_ready: bool = False     # 位置保存ガード（初期Configure イベントを無視）
        # OAuth 試行 ID: 認証開始ごとにインクリメントし、古い試行の完了通知を無視するために使う
        self._oauth_attempt_id: int = 0
        self._twitch_oauth_attempt_id: int = 0
        # 接続プロファイル編集用の内部状態
        self._profile_edit_data: list = []   # 編集中のプロファイルリスト（conn tab 用）

    def open(self):
        if self._win is not None:
            try:
                self._load_values()
                self._win_ready = False
                self._win.deiconify()
                self._win.after(300, self._mark_win_ready)
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
        self._win_ready = False
        win.after(300, self._mark_win_ready)
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

        current_mode = self._resolve_display_auth_mode()
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

        self._oauth_btn = tk.Button(
            btn_row, text="Googleアカウントで認証する",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#2A4A2A", fg="#AAFFAA", activebackground="#3A6A3A",
            relief=tk.FLAT, padx=12, pady=3,
            command=self._on_oauth_authenticate,
        )
        self._oauth_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._oauth_revoke_btn = tk.Button(
            btn_row, text="認証を解除",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["bg_list"], fg=C["fg_label"],
            relief=tk.FLAT, padx=8, pady=3,
            command=self._on_oauth_revoke,
        )
        self._oauth_revoke_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._oauth_cancel_btn = tk.Button(
            btn_row, text="認証をキャンセル",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["bg_list"], fg="#FFAA66",
            relief=tk.FLAT, padx=8, pady=3,
            command=self._on_oauth_cancel,
            state=tk.DISABLED,
        )
        self._oauth_cancel_btn.pack(side=tk.LEFT)

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

        # ── Twitch 認証セクション ──────────────────────────────────────────────
        self._section(parent, "Twitch 認証")

        tw_frame = tk.Frame(parent, bg=C["bg_main"])
        tw_frame.pack(fill=tk.X, padx=14, pady=4)

        # クライアントID
        tk.Label(tw_frame, text="Twitch クライアントID:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]).pack(anchor=tk.W)
        self._twitch_client_id_var = tk.StringVar(
            value=self._sm.get("twitch_client_id", ""))
        tw_id_row = tk.Frame(tw_frame, bg=C["bg_main"])
        tw_id_row.pack(fill=tk.X, pady=2)
        self._twitch_id_entry = tk.Entry(
            tw_id_row, textvariable=self._twitch_client_id_var,
            bg=C["bg_list"], fg=C["fg_main"],
            insertbackground=C["fg_main"],
            font=(FONT_FAMILY, FONT_SIZE_S), relief=tk.FLAT,
        )
        self._twitch_id_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 認証状態ラベル
        tw_auth = self._twitch_auth_getter()
        tw_status_text = tw_auth.status_label() if tw_auth else "（Twitch 認証サービス未接続）"
        self._twitch_status_var = tk.StringVar(value=tw_status_text)
        tk.Label(tw_frame, textvariable=self._twitch_status_var,
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg="#FFAA66", bg=C["bg_main"], anchor=tk.W,
                 ).pack(anchor=tk.W, pady=(4, 2))

        tw_btn_row = tk.Frame(tw_frame, bg=C["bg_main"])
        tw_btn_row.pack(anchor=tk.W)

        self._twitch_auth_btn = tk.Button(
            tw_btn_row, text="Twitch アカウントで認証する",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#2A2A4A", fg="#AAAAFF", activebackground="#3A3A6A",
            relief=tk.FLAT, padx=12, pady=3,
            command=self._on_twitch_authenticate,
        )
        self._twitch_auth_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._twitch_revoke_btn = tk.Button(
            tw_btn_row, text="認証を解除",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["bg_list"], fg=C["fg_label"],
            relief=tk.FLAT, padx=8, pady=3,
            command=self._on_twitch_revoke,
        )
        self._twitch_revoke_btn.pack(side=tk.LEFT)

        tk.Label(
            tw_frame,
            text="※ Twitch 開発者ポータル (dev.twitch.tv) でアプリ登録し、\n"
                 "   クライアントIDを取得してください。スコープ: user:read:chat\n"
                 "※ 認証は Device Code Grant Flow を使用します（redirect URI 登録不要）。\n"
                 "※ トークンはこの PC 内にのみ保存されます（DPAPI 暗号化）。",
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
        """OAuth 認証フローを非同期で実行する（ブロッキング回避）"""
        import threading as _threading
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

        # 試行 ID をインクリメントして現在の認証試行を識別する
        self._oauth_attempt_id += 1
        attempt_id = self._oauth_attempt_id

        # 認証中 UI: 認証ボタン・解除ボタン無効化、キャンセルボタン有効化
        self._oauth_status_var.set("認証中... ブラウザを確認してください")
        self._set_oauth_buttons(authenticating=True)

        def _do_flow():
            try:
                success = auth_svc.run_oauth_flow()
            except Exception:
                success = False
            if self._win:
                try:
                    self._win.after(0, lambda: self._on_oauth_done(attempt_id, success, auth_svc))
                except Exception:
                    pass

        _threading.Thread(target=_do_flow, daemon=True).start()

    def _on_oauth_done(self, attempt_id: int, success: bool, auth_svc):
        """認証フロー完了後の UI 更新（メインスレッドで呼ばれる）。
        attempt_id が現在の有効試行と一致しない場合（キャンセル済み等）は無視する。"""
        if attempt_id != self._oauth_attempt_id:
            # 古い試行の通知 — キャンセル後または再試行開始後のため無視
            return
        self._set_oauth_buttons(authenticating=False)
        try:
            self._oauth_status_var.set(auth_svc.status_label())
        except Exception:
            pass
        if success:
            messagebox.showinfo("認証完了", "Google アカウントでの認証が完了しました。", parent=self._win)
        else:
            messagebox.showerror(
                "認証失敗",
                "認証に失敗しました（キャンセルまたはエラー）。\n"
                "client_secrets.json を確認してから再試行してください。",
                parent=self._win,
            )

    def _on_oauth_cancel(self):
        """OAuth 認証試行をキャンセルする（UI を即時リセットし再試行可能にする）。
        バックグラウンドスレッドは timeout まで残るが、完了通知は attempt_id 不一致で無視される。"""
        # 試行 ID を更新して古い試行の完了通知を無効化
        self._oauth_attempt_id += 1
        self._set_oauth_buttons(authenticating=False)
        self._oauth_status_var.set("認証キャンセル済み — 再度ボタンを押して再試行できます")

    def _set_oauth_buttons(self, authenticating: bool):
        """OAuth ボタン群の有効/無効を一括切り替えする"""
        auth_state   = tk.DISABLED if authenticating else tk.NORMAL
        cancel_state = tk.NORMAL   if authenticating else tk.DISABLED
        try:
            self._oauth_btn.configure(state=auth_state)
            self._oauth_revoke_btn.configure(state=auth_state)
            self._oauth_cancel_btn.configure(state=cancel_state)
        except Exception:
            pass

    def _on_oauth_revoke(self):
        """OAuth トークンを失効させる"""
        auth_svc = self._auth_service_getter()
        if auth_svc is None:
            return
        if messagebox.askyesno("確認", "認証を解除してよいですか？\n次回接続時に再認証が必要になります。",
                               parent=self._win):
            auth_svc.revoke()
            self._oauth_status_var.set(auth_svc.status_label())

    # ── Twitch 認証ハンドラ ────────────────────────────────────────────────────

    def _on_twitch_authenticate(self):
        """Twitch Device Code Grant Flow を非同期で実行する"""
        import threading as _threading
        tw_auth = self._twitch_auth_getter()
        if tw_auth is None:
            messagebox.showerror("エラー", "Twitch 認証サービスが初期化されていません。",
                                 parent=self._win)
            return

        # クライアントIDを保存してから認証
        client_id = self._twitch_client_id_var.get().strip()
        if not client_id:
            messagebox.showerror("エラー", "Twitch クライアントIDを入力してください。",
                                 parent=self._win)
            return
        tw_auth.client_id = client_id

        self._twitch_oauth_attempt_id += 1
        attempt_id = self._twitch_oauth_attempt_id

        # stop_event: 再認証ボタン押下時に前回の polling を中断する
        stop_event = _threading.Event()
        self._twitch_stop_event = stop_event

        self._twitch_status_var.set("デバイスコードを取得中...")
        try:
            self._twitch_auth_btn.configure(state=tk.DISABLED)
            self._twitch_revoke_btn.configure(state=tk.DISABLED)
        except Exception:
            pass

        def _on_status(msg):
            """ワーカースレッドから状態ラベルを更新する"""
            if self._win:
                try:
                    self._win.after(0, lambda m=msg: self._twitch_status_var.set(m))
                except Exception:
                    pass

        def _on_device_code(user_code, verify_url):
            """ワーカースレッドからデバイスコードダイアログを表示する"""
            if self._win:
                try:
                    self._win.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Twitch 認証 — コードを入力してください",
                            f"ブラウザが開きます。以下のコードを入力して承認してください。\n\n"
                            f"  認証コード : {user_code}\n"
                            f"  認証 URL  : {verify_url}\n\n"
                            f"ブラウザが自動で開かない場合は上記 URL をコピーして開いてください。",
                            parent=self._win,
                        ),
                    )
                except Exception:
                    pass

        def _do_flow():
            try:
                tw_auth.run_device_code_flow(
                    on_status=_on_status,
                    on_device_code=_on_device_code,
                    stop_event=stop_event,
                )
                success = True
                err_msg = ""
            except Exception as e:
                success = False
                err_msg = str(e)
            if self._win:
                try:
                    self._win.after(
                        0, lambda: self._on_twitch_auth_done(attempt_id, success, err_msg, tw_auth)
                    )
                except Exception:
                    pass

        _threading.Thread(target=_do_flow, daemon=True).start()

    def _on_twitch_auth_done(self, attempt_id: int, success: bool, err_msg: str, tw_auth):
        """Twitch 認証完了後の UI 更新"""
        if attempt_id != self._twitch_oauth_attempt_id:
            return
        try:
            self._twitch_auth_btn.configure(state=tk.NORMAL)
            self._twitch_revoke_btn.configure(state=tk.NORMAL)
        except Exception:
            pass
        try:
            self._twitch_status_var.set(tw_auth.status_label())
        except Exception:
            pass
        if success:
            messagebox.showinfo("認証完了", "Twitch アカウントでの認証が完了しました。",
                                parent=self._win)
        else:
            messagebox.showerror("認証失敗",
                                 f"Twitch 認証に失敗しました:\n{err_msg}",
                                 parent=self._win)

    def _on_twitch_revoke(self):
        """Twitch トークンを失効させる"""
        tw_auth = self._twitch_auth_getter()
        if tw_auth is None:
            return
        if messagebox.askyesno("確認", "Twitch 認証を解除してよいですか？",
                               parent=self._win):
            tw_auth.revoke()
            try:
                self._twitch_status_var.set(tw_auth.status_label())
            except Exception:
                pass

    # ── 接続設定タブ（プロファイルリスト管理） ────────────────────────────────

    def _build_conn_tab(self, parent):
        C = UI_COLORS

        self._section(parent, "接続プロファイル")

        tk.Label(
            parent,
            text="接続先を「プロファイル」として複数登録できます。\n"
                 "有効なプロファイルは接続開始時に自動接続されます（2件目以降）。",
            font=(FONT_FAMILY, FONT_SIZE_S - 1),
            fg=C["fg_label"], bg=C["bg_main"], justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=14, pady=(4, 0))

        # ── プロファイルリスト ────────────────────────────────────────────────
        list_frame = tk.Frame(parent, bg=C["bg_main"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        self._profile_listbox = tk.Listbox(
            list_frame,
            bg=C["bg_list"], fg=C["fg_main"],
            selectbackground=C["accent"], selectforeground="#FFFFFF",
            font=(FONT_FAMILY, FONT_SIZE_S),
            relief=tk.FLAT, height=8,
            activestyle="none",
        )
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                           command=self._profile_listbox.yview)
        self._profile_listbox.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._profile_listbox.bind("<Double-Button-1>", lambda e: self._on_profile_edit())

        # ── ボタン行 ─────────────────────────────────────────────────────────
        btn_row = tk.Frame(parent, bg=C["bg_main"])
        btn_row.pack(anchor=tk.W, padx=14, pady=(0, 4))

        tk.Button(
            btn_row, text="追加",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#2A4A2A", fg="#AAFFAA", activebackground="#3A6A3A",
            relief=tk.FLAT, padx=10, pady=3,
            command=self._on_profile_add,
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            btn_row, text="編集",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["accent"], fg="#FFFFFF", activebackground="#4A6A9A",
            relief=tk.FLAT, padx=10, pady=3,
            command=self._on_profile_edit,
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            btn_row, text="削除",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#4A2A2A", fg="#FFAAAA", activebackground="#6A3A3A",
            relief=tk.FLAT, padx=10, pady=3,
            command=self._on_profile_delete,
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Label(
            parent,
            text="※ 接続ダイアログからも接続できます。\n"
                 "※ 2件目以降の有効プロファイルは自動接続されます。",
            font=(FONT_FAMILY, FONT_SIZE_S - 1),
            fg=C["fg_label"], bg=C["bg_main"], justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=14, pady=(0, 6))

        # 初期データ読み込み
        self._refresh_profile_list()

    def _refresh_profile_list(self):
        """プロファイルリストボックスを設定から再描画する"""
        from constants import PLATFORM_LABELS
        self._profile_edit_data = self._sm.get_connection_profiles()
        lb = self._profile_listbox
        lb.delete(0, tk.END)
        for p in self._profile_edit_data:
            plat   = PLATFORM_LABELS.get(p.get("platform", "youtube"), "YouTube")
            en     = "✓" if p.get("enabled", True) else "　"
            name   = p.get("profile_name", p.get("display_name", ""))
            url    = p.get("target_url", "")
            url_sh = url[:40] + "…" if len(url) > 40 else url
            lb.insert(tk.END, f"[{en}] [{plat}] {name}  — {url_sh}")

    def _on_profile_add(self):
        """新規プロファイルを追加する"""
        from constants import PLATFORM_LABELS
        new_id = f"profile_{len(self._profile_edit_data)}"
        default_name = f"接続{len(self._profile_edit_data) + 1}"
        new_profile = {
            "profile_id":   new_id,
            "platform":     "youtube",
            "profile_name": default_name,
            "overlay_name": default_name,
            "tts_name":     default_name,
            "display_name": default_name,
            "enabled":      True,
            "target_url":   "",
        }
        result = self._open_profile_edit_dialog(new_profile)
        if result is not None:
            self._profile_edit_data.append(result)
            self._save_profile_list()
            self._refresh_profile_list()

    def _on_profile_edit(self):
        """選択中のプロファイルを編集する"""
        sel = self._profile_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._profile_edit_data):
            return
        profile = dict(self._profile_edit_data[idx])
        result  = self._open_profile_edit_dialog(profile)
        if result is not None:
            self._profile_edit_data[idx] = result
            self._save_profile_list()
            self._refresh_profile_list()
            self._profile_listbox.selection_set(idx)

    def _on_profile_delete(self):
        """選択中のプロファイルを削除する"""
        sel = self._profile_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._profile_edit_data):
            return
        p    = self._profile_edit_data[idx]
        name = p.get("profile_name", p.get("display_name", ""))
        if not messagebox.askyesno("確認", f"「{name}」を削除しますか？",
                                   parent=self._win):
            return
        self._profile_edit_data.pop(idx)
        self._save_profile_list()
        self._refresh_profile_list()

    def _save_profile_list(self):
        """編集中のプロファイルリストを設定に保存する"""
        self._sm.save_connection_profiles(self._profile_edit_data)

    def _open_profile_edit_dialog(self, profile: dict) -> dict | None:
        """
        プロファイル編集ダイアログを開く。
        OK なら更新済みプロファイル dict を返す。キャンセルなら None。
        """
        from constants import PLATFORM_LABELS
        C = UI_COLORS

        dlg = tk.Toplevel(self._win or self._master)
        dlg.title("接続プロファイルを編集")
        dlg.configure(bg=C["bg_main"])
        dlg.resizable(False, False)
        # 位置を復元する（初回はデフォルト位置）
        pos = self._sm.get("profile_edit_pos", None)
        if pos and len(pos) == 2 and pos[0] > 0 and pos[1] > 0:
            dlg.geometry(f"540x380+{pos[0]}+{pos[1]}")
        else:
            dlg.geometry("540x380")
        dlg.grab_set()

        result_holder: list = [None]

        def _save_pos():
            """close 直前に geometry 文字列から位置を保存する（全経路共通）"""
            try:
                import re as _re
                m = _re.match(r'\d+x\d+([+-]\d+)([+-]\d+)', dlg.geometry())
                if m:
                    x, y = int(m.group(1)), int(m.group(2))
                    if x >= 0 and y >= 0:
                        self._sm.update({"profile_edit_pos": [x, y]})
            except Exception:
                pass

        def _labeled(parent, text):
            tk.Label(parent, text=text,
                     font=(FONT_FAMILY, FONT_SIZE_S),
                     fg=C["fg_label"], bg=C["bg_main"],
                     width=14, anchor=tk.E).pack(side=tk.LEFT, padx=(0, 6))

        def _row(parent):
            f = tk.Frame(parent, bg=C["bg_main"])
            f.pack(fill=tk.X, padx=16, pady=4)
            return f

        def _entry(parent, var, width=26):
            tk.Entry(parent, textvariable=var,
                     bg=C["bg_list"], fg=C["fg_main"],
                     insertbackground=C["fg_main"],
                     font=(FONT_FAMILY, FONT_SIZE_S), relief=tk.FLAT, width=width
                     ).pack(side=tk.LEFT)

        # プラットフォーム
        r1 = _row(dlg)
        _labeled(r1, "プラットフォーム:")
        plat_var = tk.StringVar(value=profile.get("platform", "youtube"))
        plat_cb = ttk.Combobox(
            r1, textvariable=plat_var,
            values=list(PLATFORM_LABELS.keys()),
            state="readonly", width=12,
            font=(FONT_FAMILY, FONT_SIZE_S),
        )
        plat_cb.pack(side=tk.LEFT)
        plat_label_var = tk.StringVar(
            value=PLATFORM_LABELS.get(profile.get("platform", "youtube"), "YouTube"))
        tk.Label(r1, textvariable=plat_label_var,
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]).pack(side=tk.LEFT, padx=4)

        def _on_plat_change(*_):
            plat_label_var.set(PLATFORM_LABELS.get(plat_var.get(), plat_var.get()))
            url_hint.set("YouTube URL または 動画ID" if plat_var.get() == "youtube"
                         else "Twitch URL またはチャンネル名")
        plat_var.trace_add("write", _on_plat_change)

        # ─── 名称 3 分離 ──────────────────────────────────────────────────────
        r_pname = _row(dlg)
        _labeled(r_pname, "プロファイル名:")
        pname_var = tk.StringVar(value=profile.get("profile_name",
                                                    profile.get("display_name", "")))
        _entry(r_pname, pname_var)
        tk.Label(r_pname, text="管理用",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"]).pack(side=tk.LEFT, padx=(6, 0))

        r_oname = _row(dlg)
        _labeled(r_oname, "配信用表示名:")
        oname_var = tk.StringVar(value=profile.get("overlay_name",
                                                    profile.get("display_name", "")))
        _entry(r_oname, oname_var)
        tk.Label(r_oname, text="配信用Overlay・接続元ラベル",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"]).pack(side=tk.LEFT, padx=(6, 0))

        r_tname = _row(dlg)
        _labeled(r_tname, "読み上げ名:")
        tname_var = tk.StringVar(value=profile.get("tts_name",
                                                    profile.get("display_name", "")))
        _entry(r_tname, tname_var)
        tk.Label(r_tname, text="TTS 接続元名読み上げ",
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"]).pack(side=tk.LEFT, padx=(6, 0))

        # 有効/無効
        r3 = _row(dlg)
        _labeled(r3, "")
        en_var = tk.BooleanVar(value=profile.get("enabled", True))
        tk.Checkbutton(r3, text="有効（自動接続対象）",
                       variable=en_var,
                       font=(FONT_FAMILY, FONT_SIZE_S),
                       fg=C["fg_main"], bg=C["bg_main"],
                       activebackground=C["bg_main"],
                       selectcolor=C["bg_list"]).pack(side=tk.LEFT)

        # URL
        r4 = _row(dlg)
        url_hint = tk.StringVar(
            value="YouTube URL または 動画ID" if profile.get("platform", "youtube") == "youtube"
            else "Twitch URL またはチャンネル名")
        _labeled(r4, "接続先 URL:")
        url_var = tk.StringVar(value=profile.get("target_url", ""))
        _entry(r4, url_var, width=36)

        # ヒントラベル
        tk.Label(dlg, textvariable=url_hint,
                 font=(FONT_FAMILY, FONT_SIZE_S - 1),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(anchor=tk.W, padx=16 + 14 * 7, pady=(0, 4))

        # ボタン行
        btn_row = tk.Frame(dlg, bg=C["bg_main"])
        btn_row.pack(pady=10)

        def _ok():
            pname = pname_var.get().strip() or "接続"
            result_holder[0] = {
                "profile_id":   profile.get("profile_id", "profile_new"),
                "platform":     plat_var.get(),
                "profile_name": pname,
                "overlay_name": oname_var.get().strip() or pname,
                "tts_name":     tname_var.get().strip() or pname,
                "display_name": pname,   # 後方互換
                "enabled":      en_var.get(),
                "target_url":   url_var.get().strip(),
            }
            _save_pos()
            dlg.destroy()

        def _cancel():
            _save_pos()
            dlg.destroy()

        # × ボタンでも最終位置を保存する
        dlg.protocol("WM_DELETE_WINDOW", _cancel)

        tk.Button(btn_row, text="OK",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["accent"], fg="#FFFFFF",
                  relief=tk.FLAT, padx=16, pady=4,
                  command=_ok).pack(side=tk.LEFT, padx=4)

        tk.Button(btn_row, text="キャンセル",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_label"],
                  relief=tk.FLAT, padx=12, pady=4,
                  command=_cancel).pack(side=tk.LEFT, padx=4)

        dlg.wait_window()
        return result_holder[0]

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
                 ).pack(anchor=tk.W, padx=14, pady=(4, 4))

        # ── 配信用 Overlay 配置確認モード ────────────────────────────────────
        if self._overlay_placement_cb:
            placement_row = tk.Frame(inner, bg=C["bg_main"])
            placement_row.pack(anchor=tk.W, padx=14, pady=(0, 8))
            tk.Button(
                placement_row,
                text="配信用 Overlay — 配置確認モード",
                font=(FONT_FAMILY, FONT_SIZE_S),
                bg="#2A4A5A", fg="#88CCFF",
                activebackground="#3A5A7A",
                relief=tk.FLAT, padx=10, pady=3,
                command=self._overlay_placement_cb,
            ).pack(side=tk.LEFT)
            tk.Label(
                placement_row,
                text="※ 一時的に可視化します。本番配信には影響しません。",
                font=(FONT_FAMILY, FONT_SIZE_S - 1),
                fg=C["fg_label"], bg=C["bg_main"],
            ).pack(side=tk.LEFT, padx=(8, 0))

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

        # Twitch クライアントID 保存
        twitch_id = self._twitch_client_id_var.get().strip()
        tw_auth = self._twitch_auth_getter()
        if tw_auth is not None and twitch_id != tw_auth.client_id:
            tw_auth.client_id = twitch_id

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

    def _mark_win_ready(self):
        """初期 Configure イベントを無視するためのフラグをセット"""
        self._win_ready = True

    def _on_configure(self, event):
        if self._win and self._win_ready and event.widget is self._win:
            self._pos_setter([self._win.winfo_x(), self._win.winfo_y()])

    def _close(self):
        """設定ウィンドウを非表示にする（destroy せず withdraw で保持）"""
        if self._win:
            try:
                # withdraw() が <Configure> を発火させるため、先にガードを解除する
                self._win_ready = False
                self._win.withdraw()
            except tk.TclError:
                pass

    def _load_values(self):
        """_sm から設定値を読み込んで UI 変数に反映する（再表示時に呼ぶ）"""
        self._api_key_var.set(self._sm.api_key)
        self._auth_mode_var.set(self._resolve_display_auth_mode())
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
        # Twitch クライアントID
        if hasattr(self, "_twitch_client_id_var"):
            self._twitch_client_id_var.set(self._sm.get("twitch_client_id", ""))
        # 接続設定プロファイルリスト
        if hasattr(self, "_profile_listbox"):
            self._refresh_profile_list()

    # ── ヘルパー ──────────────────────────────────────────────────────────────

    def _resolve_display_auth_mode(self) -> str:
        """
        表示用の認証モードを解決する。
        CommentController._resolve_auth_mode() と同じ優先順位を使う。
          1. auth_service.mode（CommentController が起動時に解決済み）が最優先
          2. 設定ファイルの auth_mode
          3. API キーが保存済みなら api_key
          4. それ以外（新規）は oauth
        """
        auth_svc = self._auth_service_getter()
        if auth_svc is not None:
            return auth_svc.mode
        saved = self._sm.get("auth_mode", None)
        if saved is not None:
            return saved
        if self._sm.api_key:
            return "api_key"
        return "oauth"

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
