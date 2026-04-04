"""
RCommentHub — 接続ダイアログ
URL または動画ID を入力して接続を開始する簡易ダイアログ
"""

import threading
import tkinter as tk
from tkinter import ttk

from constants import UI_COLORS, FONT_FAMILY, FONT_SIZE_S, FONT_SIZE_M


class ConnectDialog:
    """
    URL / 動画ID 入力 → 接続確認 → 接続開始 の流れを提供するダイアログ。

    extract_fn:   (text: str) -> str          URL から動画 ID を抽出
    verify_fn:    (video_id, api_key) -> dict 接続確認（失敗時は例外）
    connect_fn:   (verify_result: dict) -> None 接続確認後に接続開始
    url_getter:   () -> str                   設定から conn1 URL を取得（プリフィル用）
    url_saver:    (url: str) -> None          接続確認後に conn1 URL を保存
    """

    def __init__(self, master: tk.Tk, extract_fn, verify_fn, connect_fn,
                 api_key_getter, topmost_getter=None, pos_getter=None, pos_setter=None,
                 url_getter=None, url_saver=None):
        self._master         = master
        self._extract_fn     = extract_fn
        self._verify_fn      = verify_fn
        self._connect_fn     = connect_fn
        self._api_key_getter = api_key_getter   # () -> str
        self._topmost_getter = topmost_getter or (lambda: False)
        self._pos_getter     = pos_getter or (lambda: None)
        self._pos_setter     = pos_setter or (lambda pos: None)
        self._url_getter     = url_getter or (lambda: "")
        self._url_saver      = url_saver or (lambda url: None)
        self._verify_result  = None
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
            win.geometry(f"500x210+{pos[0]}+{pos[1]}")
        else:
            win.geometry("500x210")
        win.wm_attributes("-topmost", self._topmost_getter())
        win.bind("<Configure>", self._on_configure)

        # タイトルラベル
        tk.Label(win, text="接続先を入力してください",
                 font=(FONT_FAMILY, FONT_SIZE_M, "bold"),
                 fg=C["fg_header"], bg=C["bg_main"]
                 ).pack(pady=(14, 6))

        # 入力欄
        input_frame = tk.Frame(win, bg=C["bg_main"])
        input_frame.pack(fill=tk.X, padx=20, pady=2)
        tk.Label(input_frame, text="YouTube URL または 動画ID:",
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
                                    wraplength=460, anchor=tk.W, justify=tk.LEFT)
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

    # ─── 内部処理 ─────────────────────────────────────────────────────────────

    def _on_verify(self):
        text = self._url_var.get().strip()
        if not text:
            self._set_result("URL または 動画ID を入力してください", "warning")
            return

        video_id = self._extract_fn(text)
        if not video_id:
            self._set_result("動画ID を取得できませんでした", "error")
            return

        api_key = self._api_key_getter()
        if not api_key:
            self._set_result("API キーが未設定です。設定ウィンドウから登録してください。", "error")
            return

        self._verify_result = None
        self._set_result("確認中...", "info")
        self._btn_verify.config(state=tk.DISABLED)
        self._btn_connect.config(state=tk.DISABLED)

        def _work():
            try:
                result = self._verify_fn(video_id, api_key)
                if self._win:
                    self._win.after(0, lambda r=result: self._on_verify_ok(r))
            except Exception as e:
                if self._win:
                    self._win.after(0, lambda msg=str(e): self._on_verify_fail(msg))

        threading.Thread(target=_work, daemon=True).start()

    def _on_verify_ok(self, result: dict):
        self._verify_result = result
        title = result.get("title", "")
        self._set_result(f"✓ 確認OK: {title}", "ok")
        self._btn_verify.config(state=tk.NORMAL)
        self._btn_connect.config(state=tk.NORMAL)
        # 確認できた URL を設定に保存しておく
        self._url_saver(self._url_var.get().strip())

    def _on_verify_fail(self, msg: str):
        self._verify_result = None
        self._set_result(f"✗ エラー: {msg}", "error")
        self._btn_verify.config(state=tk.NORMAL)
        self._btn_connect.config(state=tk.DISABLED)

    def _on_connect(self):
        if self._verify_result:
            result = self._verify_result
            self._close()
            self._connect_fn(result)

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
