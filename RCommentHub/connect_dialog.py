"""
RCommentHub — 接続ダイアログ
URL / チャンネル名を入力してライブ配信に接続するダイアログ。
YouTube / Twitch のプラットフォーム選択に対応。
"""

import threading
import tkinter as tk
from tkinter import ttk

from constants import UI_COLORS, FONT_FAMILY, FONT_SIZE_S, FONT_SIZE_M, PLATFORM_LABELS


class ConnectDialog:
    """
    プラットフォーム・プロファイル選択 → 接続確認 → 接続開始 の流れを提供するダイアログ。

    profiles_getter:  () -> list[dict]           接続プロファイル一覧を返す
    verify_fn:        (platform, url) -> dict    接続確認（失敗時は例外）
    connect_fn:       (profile_id, verify_result) -> None  接続開始
    auth_checker:     () -> bool                 YouTube 認証済みかどうか
    auth_mode_getter: () -> str                  YouTube 認証モード
    twitch_auth_checker: () -> bool              Twitch 認証済みかどうか
    """

    def __init__(self, master: tk.Tk, extract_fn, verify_fn, connect_fn,
                 api_key_getter=None, topmost_getter=None, pos_getter=None, pos_setter=None,
                 url_getter=None, url_saver=None,
                 auth_checker=None, auth_mode_getter=None,
                 profiles_getter=None, twitch_auth_checker=None):
        self._master             = master
        self._extract_fn         = extract_fn         # YouTube URL → video_id (後方互換)
        self._verify_fn          = verify_fn          # (platform, url) -> dict
        self._connect_fn         = connect_fn         # (profile_id, verify_result) -> None
        self._api_key_getter     = api_key_getter or (lambda: "")
        self._topmost_getter     = topmost_getter or (lambda: False)
        self._pos_getter         = pos_getter or (lambda: None)
        self._pos_setter         = pos_setter or (lambda pos: None)
        self._url_getter         = url_getter or (lambda: "")
        self._url_saver          = url_saver or (lambda url: None)
        self._auth_checker       = auth_checker or (lambda: True)
        self._auth_mode_getter   = auth_mode_getter or (lambda: "api_key")
        self._profiles_getter    = profiles_getter or (lambda: [])
        self._twitch_auth_checker = twitch_auth_checker or (lambda: False)
        self._verify_result      = None
        self._win: tk.Toplevel | None = None

    def open(self):
        if self._win is not None:
            try:
                self._win.lift()
                self._win.focus_force()
                return
            except tk.TclError:
                self._win = None

        C = UI_COLORS
        win = tk.Toplevel(self._master)
        self._win = win
        win.title("配信に接続")
        win.configure(bg=C["bg_main"])
        win.resizable(False, False)
        pos = self._pos_getter()
        if pos:
            win.geometry(f"540x280+{pos[0]}+{pos[1]}")
        else:
            win.geometry("540x280")
        win.wm_attributes("-topmost", self._topmost_getter())
        win.bind("<Configure>", self._on_configure)

        # タイトルラベル
        tk.Label(win, text="接続先を入力してください",
                 font=(FONT_FAMILY, FONT_SIZE_M, "bold"),
                 fg=C["fg_header"], bg=C["bg_main"]
                 ).pack(pady=(14, 6))

        # ── プロファイル選択 ──────────────────────────────────────────────────
        prof_row = tk.Frame(win, bg=C["bg_main"])
        prof_row.pack(fill=tk.X, padx=20, pady=2)
        tk.Label(prof_row, text="接続プロファイル:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT, padx=(0, 8))

        profiles = self._profiles_getter()
        self._profile_choices = {
            p.get("display_name", p["profile_id"]): p
            for p in profiles
        }
        default_name = profiles[0].get("display_name", "") if profiles else "接続1"
        self._profile_var = tk.StringVar(value=default_name)
        self._profile_cb  = ttk.Combobox(
            prof_row, textvariable=self._profile_var,
            values=list(self._profile_choices.keys()),
            state="readonly" if profiles else "disabled",
            width=20,
            font=(FONT_FAMILY, FONT_SIZE_S),
        )
        self._profile_cb.pack(side=tk.LEFT)
        self._profile_cb.bind("<<ComboboxSelected>>", self._on_profile_changed)

        # ── プラットフォーム表示（選択プロファイルから自動設定）────────────────
        self._platform_label_var = tk.StringVar(value="")
        tk.Label(prof_row, textvariable=self._platform_label_var,
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT, padx=(8, 0))

        # ── 入力欄 ───────────────────────────────────────────────────────────
        input_frame = tk.Frame(win, bg=C["bg_main"])
        input_frame.pack(fill=tk.X, padx=20, pady=2)

        self._url_label_var = tk.StringVar(value="URL / ID:")
        tk.Label(input_frame, textvariable=self._url_label_var,
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(anchor=tk.W)

        self._url_var = tk.StringVar(value=self._url_getter())
        entry = tk.Entry(input_frame, textvariable=self._url_var,
                         bg=C["bg_list"], fg=C["fg_main"],
                         insertbackground=C["fg_main"],
                         font=(FONT_FAMILY, FONT_SIZE_S),
                         relief=tk.FLAT)
        entry.pack(fill=tk.X, pady=3)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._on_verify())

        # 結果ラベル
        self._result_var = tk.StringVar(value="")
        self._result_lbl = tk.Label(win, textvariable=self._result_var,
                                    font=(FONT_FAMILY, FONT_SIZE_S),
                                    fg=C["fg_label"], bg=C["bg_main"],
                                    wraplength=500, anchor=tk.W, justify=tk.LEFT)
        self._result_lbl.pack(padx=20, pady=(2, 0), anchor=tk.W)

        # ボタン行
        btn_frame = tk.Frame(win, bg=C["bg_main"])
        btn_frame.pack(pady=10)

        self._btn_verify = tk.Button(
            btn_frame, text="確認",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg="#2A4A2A", fg="#AAFFAA", activebackground="#3A6A3A",
            relief=tk.FLAT, padx=14, pady=4,
            command=self._on_verify,
        )
        self._btn_verify.pack(side=tk.LEFT, padx=4)

        self._btn_connect = tk.Button(
            btn_frame, text="接続開始",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["accent"], fg="#FFFFFF", activebackground="#4A6A9A",
            relief=tk.FLAT, padx=14, pady=4,
            state=tk.DISABLED,
            command=self._on_connect,
        )
        self._btn_connect.pack(side=tk.LEFT, padx=4)

        tk.Button(
            btn_frame, text="キャンセル",
            font=(FONT_FAMILY, FONT_SIZE_S),
            bg=C["bg_list"], fg=C["fg_label"],
            relief=tk.FLAT, padx=14, pady=4,
            command=self._close,
        ).pack(side=tk.LEFT, padx=4)

        win.protocol("WM_DELETE_WINDOW", self._close)

        # 初期プロファイル反映
        self._update_ui_for_profile()

    # ─── プロファイル変更 ──────────────────────────────────────────────────────

    def _on_profile_changed(self, event=None):
        self._verify_result = None
        self._result_var.set("")
        self._btn_connect.config(state=tk.DISABLED)
        self._update_ui_for_profile()

    def _current_profile(self) -> dict | None:
        name = self._profile_var.get()
        return self._profile_choices.get(name)

    def _current_platform(self) -> str:
        p = self._current_profile()
        return p.get("platform", "youtube") if p else "youtube"

    def _update_ui_for_profile(self):
        """選択プロファイルに合わせて UI を更新する"""
        p        = self._current_profile()
        platform = p.get("platform", "youtube") if p else "youtube"
        plat_label = PLATFORM_LABELS.get(platform, platform)
        self._platform_label_var.set(f"[{plat_label}]")

        if platform == "twitch":
            self._url_label_var.set("Twitch URL またはチャンネル名:")
            # プロファイルの URL をプリフィル
            if p and p.get("target_url"):
                self._url_var.set(p["target_url"])
        else:
            self._url_label_var.set("YouTube URL または 動画ID:")
            if p and p.get("target_url"):
                self._url_var.set(p["target_url"])
            else:
                self._url_var.set(self._url_getter())

    # ─── 接続確認 ─────────────────────────────────────────────────────────────

    def _on_verify(self):
        text     = self._url_var.get().strip()
        platform = self._current_platform()

        if not text:
            self._set_result("URL または ID を入力してください", "warning")
            return

        # 認証確認
        if platform == "twitch":
            if not self._twitch_auth_checker():
                self._set_result(
                    "Twitch 認証が必要です。設定ウィンドウから認証してください。", "error")
                return
        else:
            if not self._auth_checker():
                mode = self._auth_mode_getter()
                if mode == "oauth":
                    self._set_result(
                        "Google アカウントで認証されていません。設定ウィンドウから認証してください。",
                        "error")
                else:
                    self._set_result(
                        "API キーが未設定です（補助モード）。設定ウィンドウから登録してください。",
                        "error")
                return

        self._verify_result = None
        self._set_result("確認中...", "info")
        self._btn_verify.config(state=tk.DISABLED)
        self._btn_connect.config(state=tk.DISABLED)

        def _work():
            try:
                result = self._verify_fn(platform, text)
                if self._win:
                    self._win.after(0, lambda r=result: self._on_verify_ok(r, platform, text))
            except Exception as e:
                if self._win:
                    self._win.after(0, lambda msg=str(e): self._on_verify_fail(msg))

        threading.Thread(target=_work, daemon=True).start()

    def _on_verify_ok(self, result: dict, platform: str, url: str):
        self._verify_result = result
        title = result.get("title", result.get("display_name", ""))
        self._set_result(f"✓ 確認OK: {title}", "ok")
        self._btn_verify.config(state=tk.NORMAL)
        self._btn_connect.config(state=tk.NORMAL)
        # YouTube の場合のみ URL を保存（旧互換）
        if platform == "youtube":
            self._url_saver(url)

    def _on_verify_fail(self, msg: str):
        self._verify_result = None
        self._set_result(f"✗ エラー: {msg}", "error")
        self._btn_verify.config(state=tk.NORMAL)
        self._btn_connect.config(state=tk.DISABLED)

    def _on_connect(self):
        if not self._verify_result:
            return
        profile  = self._current_profile()
        profile_id = profile["profile_id"] if profile else "profile_0"
        result   = self._verify_result
        self._close()
        self._connect_fn(profile_id, result)

    # ─── ユーティリティ ────────────────────────────────────────────────────────

    def _on_configure(self, event):
        if self._win and event.widget is self._win:
            self._pos_setter([self._win.winfo_x(), self._win.winfo_y()])

    def _close(self):
        if self._win:
            try:
                self._win.grab_release()
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None

    def _set_result(self, text: str, kind: str = "info"):
        _colors = {
            "info":    UI_COLORS["fg_label"],
            "ok":      "#44CC44",
            "warning": "#FFAA44",
            "error":   "#FF4444",
        }
        self._result_var.set(text)
        self._result_lbl.config(fg=_colors.get(kind, UI_COLORS["fg_label"]))
