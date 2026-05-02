"""
RCommentHub — デバッグコメント送信ウィンドウ

YouTube 未接続でも手動でコメントを流すためのデバッグ入力基盤。
送信したコメントは本番コメントと同じ処理パス（フィルタ・ユーザー更新・TTS・ログ保存）を通る。
"""

import tkinter as tk
from tkinter import ttk, messagebox
import datetime
import uuid

from constants import (
    INPUT_SOURCE_DEBUG, INPUT_SOURCE_TWITCH,
    UI_COLORS, FONT_FAMILY, FONT_SIZE_S, FONT_SIZE_M,
)

# ─── メッセージ種別オプション ────────────────────────────────────────────────
_MSG_TYPE_OPTIONS = [
    ("通常コメント",              "textMessageEvent"),
    ("Super Chat",                "superChatEvent"),
    ("Super Sticker",             "superStickerEvent"),
    ("メンバー記念チャット",      "memberMilestoneChatEvent"),
    ("ギフトメンバー送信",        "membershipGiftingEvent"),
    ("ギフトメンバー受取",        "giftMembershipReceivedEvent"),
    ("投票",                      "pollEvent"),
]
_MSG_TYPE_LABELS  = [label for label, _ in _MSG_TYPE_OPTIONS]
_MSG_TYPE_BY_LABEL = {label: kind for label, kind in _MSG_TYPE_OPTIONS}

# ─── デフォルトプリセット ─────────────────────────────────────────────────────
_DEFAULT_PRESETS = [
    {
        "name":         "視聴者A",
        "channel_id":   "debug_viewer_a",
        "is_owner":     False,
        "is_moderator": False,
        "is_member":    False,
        "is_verified":  False,
    },
    {
        "name":         "配信者（Owner）",
        "channel_id":   "debug_owner",
        "is_owner":     True,
        "is_moderator": False,
        "is_member":    False,
        "is_verified":  False,
    },
    {
        "name":         "Moderator",
        "channel_id":   "debug_mod",
        "is_owner":     False,
        "is_moderator": True,
        "is_member":    False,
        "is_verified":  False,
    },
    {
        "name":         "Member",
        "channel_id":   "debug_member",
        "is_owner":     False,
        "is_moderator": False,
        "is_member":    True,
        "is_verified":  False,
    },
    # ── Twitch 擬似プリセット ──────────────────────────────────────────────
    {
        "name":         "[Twitch] 視聴者",
        "channel_id":   "twitch_viewer",
        "is_owner":     False,
        "is_moderator": False,
        "is_member":    False,
        "is_verified":  False,
    },
    {
        "name":         "[Twitch] チャンネル主",
        "channel_id":   "twitch_broadcaster",
        "is_owner":     True,
        "is_moderator": False,
        "is_member":    False,
        "is_verified":  False,
    },
    {
        "name":         "[Twitch] モデレーター",
        "channel_id":   "twitch_moderator",
        "is_owner":     False,
        "is_moderator": True,
        "is_member":    False,
        "is_verified":  False,
    },
    {
        "name":         "[Twitch] サブスクライバー",
        "channel_id":   "twitch_subscriber",
        "is_owner":     False,
        "is_moderator": False,
        "is_member":    True,
        "is_verified":  False,
    },
]


def _build_debug_raw(preset: dict, body: str,
                     source_id: str = "conn1", source_name: str = "",
                     source_type: str = INPUT_SOURCE_DEBUG,
                     tts_source_name: str = "",
                     msg_type: str = "textMessageEvent",
                     sc_amount: str = "¥500",
                     gift_count: int = 1) -> dict:
    """デバッグコメント用の YouTube API 形式 raw dict を生成する"""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if msg_type == "superChatEvent":
        snippet_extra = {"superChatDetails": {"amountDisplayString": sc_amount, "userComment": body}}
    elif msg_type == "superStickerEvent":
        snippet_extra = {"superStickerDetails": {"amountDisplayString": sc_amount}}
    elif msg_type == "memberMilestoneChatEvent":
        snippet_extra = {"memberMilestoneChatDetails": {"userComment": body}}
    elif msg_type == "membershipGiftingEvent":
        snippet_extra = {"membershipGiftingDetails": {"giftMembershipsCount": gift_count}}
    elif msg_type == "giftMembershipReceivedEvent":
        snippet_extra = {}
    elif msg_type == "pollEvent":
        snippet_extra = {"pollDetails": {"prompt": body}}
    else:  # textMessageEvent
        snippet_extra = {"textMessageDetails": {"messageText": body}}

    return {
        "id":                f"debug_{uuid.uuid4().hex[:12]}",
        "_source":           source_type,
        "_source_id":        source_id,
        "_source_name":      source_name,
        "_tts_source_name":  tts_source_name or source_name,
        "snippet": {
            "type":              msg_type,
            "publishedAt":       now_iso,
            "displayMessage":    body,
            "hasDisplayContent": True,
            "liveChatId":        "",
            **snippet_extra,
        },
        "authorDetails": {
            "channelId":        preset.get("channel_id", "debug_unknown"),
            "displayName":      preset.get("name", "DEBUG"),
            "channelUrl":       "",
            "profileImageUrl":  "",
            "isChatOwner":      preset.get("is_owner",     False),
            "isChatModerator":  preset.get("is_moderator", False),
            "isChatSponsor":    preset.get("is_member",    False),
            "isVerified":       preset.get("is_verified",  False),
        },
    }


class DebugSenderWindow:
    """
    デバッグコメント送信ウィンドウ。

    Parameters
    ----------
    master              : tk ルートウィジェット
    add_comment_cb      : コメントを追加するコールバック。raw dict を引数に取る。
    presets_getter      : 現在のプリセットリストを返すコールバック
    presets_setter      : プリセットリストを保存するコールバック
    mode_enabled_getter : デバッグモードが ON かどうかを返すコールバック（省略時は常に True）
    sources_getter      : アクティブな [(source_id, source_name), ...] を返すコールバック
    """

    def __init__(self, master, add_comment_cb, presets_getter, presets_setter,
                 mode_enabled_getter=None, topmost_getter=None,
                 pos_getter=None, pos_setter=None, sources_getter=None):
        self._master              = master
        self._add_comment         = add_comment_cb
        self._get_presets         = presets_getter
        self._set_presets         = presets_setter
        self._mode_enabled_getter = mode_enabled_getter or (lambda: True)
        self._topmost_getter      = topmost_getter or (lambda: False)
        self._pos_getter          = pos_getter or (lambda: None)
        self._pos_setter          = pos_setter or (lambda pos: None)
        # sources_getter: () -> [(source_id, source_name), ...]
        self._sources_getter      = sources_getter or (lambda: [("conn1", "接続1")])
        self._win: tk.Toplevel | None = None

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
        self._win.title("RCommentHub — デバッグ送信")
        self._win.configure(bg=UI_COLORS["bg_main"])
        self._win.resizable(True, True)
        self._win.minsize(380, 360)
        pos = self._pos_getter()
        if pos:
            self._win.geometry(f"+{pos[0]}+{pos[1]}")
        self._win.wm_attributes("-topmost", self._topmost_getter())
        self._win.bind("<Configure>", self._on_configure)
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        # Combobox 可読性確保（ttk スタイルを明示）
        style = ttk.Style()
        style.map("TCombobox",
                  fieldbackground=[("readonly", UI_COLORS["bg_list"])],
                  foreground=[("readonly", UI_COLORS["fg_main"])],
                  selectbackground=[("readonly", UI_COLORS["accent"])],
                  selectforeground=[("readonly", "#FFFFFF")])

    def close(self):
        if self._win:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None

    def _on_configure(self, event):
        if self._win and event.widget is self._win:
            self._pos_setter([self._win.winfo_x(), self._win.winfo_y()])

    def _on_close(self):
        self.close()

    @property
    def is_open(self) -> bool:
        return self._win is not None

    # ─── UI 構築 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        C   = UI_COLORS
        win = self._win

        # ── 説明ラベル ──
        tk.Label(
            win, text="デバッグコメント送信（YouTube 未接続でも動作）",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg="#FF8C00", bg=C["bg_main"],
        ).pack(anchor=tk.W, padx=8, pady=(8, 0))

        tk.Frame(win, bg=C["border"], height=1).pack(fill=tk.X, padx=8, pady=(4, 8))

        # ── 送信者プリセット選択 ──
        frame_top = tk.Frame(win, bg=C["bg_main"])
        frame_top.pack(fill=tk.X, padx=8, pady=(0, 4))

        tk.Label(frame_top, text="送信者プリセット:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).grid(row=0, column=0, sticky=tk.W, pady=2)

        self._preset_var = tk.StringVar()
        self._preset_cb  = ttk.Combobox(
            frame_top, textvariable=self._preset_var,
            state="readonly", font=(FONT_FAMILY, FONT_SIZE_S), width=26,
        )
        self._preset_cb.grid(row=0, column=1, sticky=tk.EW, padx=(4, 0))
        frame_top.columnconfigure(1, weight=1)

        # ── プリセット操作ボタン ──
        btn_frame = tk.Frame(win, bg=C["bg_main"])
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 6))

        for text, cmd in [
            ("新規",   self._new_preset),
            ("編集",   self._edit_preset),
            ("削除",   self._delete_preset),
        ]:
            tk.Button(
                btn_frame, text=text,
                font=(FONT_FAMILY, FONT_SIZE_S),
                bg=C["bg_list"], fg=C["fg_main"],
                relief=tk.FLAT, padx=8, pady=2,
                command=cmd,
            ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Frame(win, bg=C["border"], height=1).pack(fill=tk.X, padx=8, pady=(2, 6))

        # ── プリセット詳細表示 ──
        detail_frame = tk.Frame(win, bg=C["bg_panel"], bd=0,
                                highlightthickness=1,
                                highlightbackground=C["border"])
        detail_frame.pack(fill=tk.X, padx=8, pady=(0, 6))

        self._lbl_detail = tk.Label(
            detail_frame,
            text="← プリセットを選択",
            font=(FONT_FAMILY, FONT_SIZE_S),
            fg=C["fg_label"], bg=C["bg_panel"],
            justify=tk.LEFT, anchor=tk.W,
        )
        self._lbl_detail.pack(fill=tk.X, padx=8, pady=4)

        # ── メッセージ種別 ──
        type_frame = tk.Frame(win, bg=C["bg_main"])
        type_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Label(type_frame, text="メッセージ種別:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)
        self._msg_type_var = tk.StringVar(value=_MSG_TYPE_LABELS[0])
        self._msg_type_cb = ttk.Combobox(
            type_frame, textvariable=self._msg_type_var,
            values=_MSG_TYPE_LABELS,
            state="readonly", font=(FONT_FAMILY, FONT_SIZE_S), width=22,
        )
        self._msg_type_cb.pack(side=tk.LEFT, padx=(6, 0))
        self._msg_type_cb.bind("<<ComboboxSelected>>", lambda _: self._on_type_change())

        # ── 種別追加フィールド（金額 / ギフト数）──
        extra_frame = tk.Frame(win, bg=C["bg_main"])
        extra_frame.pack(fill=tk.X, padx=8, pady=(0, 2))

        # 金額行
        self._amount_row = tk.Frame(extra_frame, bg=C["bg_main"])
        tk.Label(self._amount_row, text="金額:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)
        self._amount_var = tk.StringVar(value="¥500")
        tk.Entry(self._amount_row, textvariable=self._amount_var,
                 bg=C["bg_list"], fg=C["fg_main"], insertbackground=C["fg_main"],
                 relief=tk.FLAT, font=(FONT_FAMILY, FONT_SIZE_S), width=12,
                 ).pack(side=tk.LEFT, padx=(6, 0))

        # ギフト数行
        self._gift_row = tk.Frame(extra_frame, bg=C["bg_main"])
        tk.Label(self._gift_row, text="ギフト数:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)
        self._gift_var = tk.StringVar(value="1")
        tk.Spinbox(self._gift_row, from_=1, to=999, textvariable=self._gift_var,
                   bg=C["bg_list"], fg=C["fg_main"], insertbackground=C["fg_main"],
                   relief=tk.FLAT, font=(FONT_FAMILY, FONT_SIZE_S), width=6,
                   ).pack(side=tk.LEFT, padx=(6, 0))

        # ── コメント本文 ──
        self._lbl_body = tk.Label(win, text="コメント本文:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"])
        self._lbl_body.pack(anchor=tk.W, padx=8)

        self._body_text = tk.Text(
            win, height=4,
            font=(FONT_FAMILY, FONT_SIZE_M),
            bg=C["bg_list"], fg=C["fg_main"],
            insertbackground=C["fg_main"],
            relief=tk.FLAT, padx=4, pady=4,
        )
        self._body_text.pack(fill=tk.X, padx=8, pady=(2, 6))
        self._body_text.bind("<Return>",   self._on_enter_key)
        self._body_text.bind("<KP_Enter>", self._on_enter_key)

        # 初期状態を反映
        self._on_type_change()

        # ── 接続先セレクタ ──
        src_frame = tk.Frame(win, bg=C["bg_main"])
        src_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Label(src_frame, text="送信先接続:",
                 font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]
                 ).pack(side=tk.LEFT)
        self._source_var = tk.StringVar(value="conn1")
        self._source_cb  = ttk.Combobox(
            src_frame, textvariable=self._source_var,
            state="readonly", font=(FONT_FAMILY, FONT_SIZE_S), width=16,
        )
        self._source_cb.pack(side=tk.LEFT, padx=(6, 0))
        self._refresh_source_list()

        # ── 送信ボタン ──
        tk.Button(
            win, text="▶ 送信",
            font=(FONT_FAMILY, FONT_SIZE_M, "bold"),
            bg="#3A5A2A", fg="#AAFFAA",
            activebackground="#4A7A3A",
            relief=tk.FLAT, padx=16, pady=4,
            command=self._send,
        ).pack(pady=(0, 8))

        # 初期データ投入
        self._reload_presets()
        self._preset_cb.bind("<<ComboboxSelected>>", lambda _: self._update_detail())

    def _on_type_change(self):
        """メッセージ種別が変わったとき、追加フィールドと本文欄を切り替える"""
        kind = _MSG_TYPE_BY_LABEL.get(self._msg_type_var.get(), "textMessageEvent")
        # 金額フィールド: SC / SuperSticker
        if kind in ("superChatEvent", "superStickerEvent"):
            self._amount_row.pack(fill=tk.X, pady=(2, 0))
        else:
            self._amount_row.pack_forget()
        # ギフト数フィールド: membershipGiftingEvent
        if kind == "membershipGiftingEvent":
            self._gift_row.pack(fill=tk.X, pady=(2, 0))
        else:
            self._gift_row.pack_forget()
        # 本文欄ラベルと有効/無効
        body_needed = kind not in ("superStickerEvent", "membershipGiftingEvent", "giftMembershipReceivedEvent")
        if kind == "pollEvent":
            self._lbl_body.config(text="投票テキスト:")
        elif kind in ("superChatEvent", "memberMilestoneChatEvent"):
            self._lbl_body.config(text="コメント本文 (任意):")
        else:
            self._lbl_body.config(text="コメント本文:")
        state = tk.NORMAL if body_needed else tk.DISABLED
        self._body_text.config(state=state)
        if not body_needed:
            self._body_text.config(bg=UI_COLORS["bg_panel"])
        else:
            self._body_text.config(bg=UI_COLORS["bg_list"])

    def _reload_presets(self):
        presets = self._get_presets()
        names   = [p["name"] for p in presets]
        self._preset_cb["values"] = names
        if names:
            current = self._preset_var.get()
            if current not in names:
                self._preset_var.set(names[0])
            self._update_detail()
        else:
            self._preset_var.set("")
            self._lbl_detail.config(text="プリセットなし")

    def _refresh_source_list(self):
        """接続先リストを最新の sources_getter から更新する"""
        sources = self._sources_getter()
        if not sources:
            sources = [("conn1", "接続1", "youtube", "接続1")]
        # sources は (source_id, source_name, platform) または (source_id, source_name, platform, tts_name) のいずれか
        labels = []
        self._source_map = {}
        for entry in sources:
            sid, name = entry[0], entry[1]
            platform     = entry[2] if len(entry) > 2 else "youtube"
            tts_name     = entry[3] if len(entry) > 3 else name
            label = f"{name} ({sid})"
            labels.append(label)
            self._source_map[label] = (sid, name, platform, tts_name)
        self._source_cb["values"] = labels
        cur = self._source_var.get()
        if cur not in self._source_map:
            self._source_var.set(labels[0])

    def _update_detail(self):
        preset = self._current_preset()
        if not preset:
            self._lbl_detail.config(text="← プリセットを選択")
            return
        flags = []
        if preset.get("is_owner"):     flags.append("配信者")
        if preset.get("is_moderator"): flags.append("Mod")
        if preset.get("is_member"):    flags.append("Mbr")
        if preset.get("is_verified"):  flags.append("Ver")
        flag_str = f"[{', '.join(flags)}]" if flags else "[一般]"
        text = (
            f"表示名:  {preset['name']}\n"
            f"ch_id:   {preset.get('channel_id', '')}\n"
            f"属性:    {flag_str}"
        )
        self._lbl_detail.config(text=text)

    def _current_preset(self) -> dict | None:
        name    = self._preset_var.get()
        presets = self._get_presets()
        return next((p for p in presets if p["name"] == name), None)

    # ─── 送信 ────────────────────────────────────────────────────────────────

    def _on_enter_key(self, event):
        if event.state & 0x4:  # Ctrl+Enter
            self._send()
            return "break"

    def _send(self):
        if not self._mode_enabled_getter():
            messagebox.showwarning(
                "デバッグモード OFF",
                "デバッグモードが OFF です。\n"
                "接続バーの「🐛 DEBUG OFF」ボタンで ON にしてから送信してください。",
                parent=self._win,
            )
            return
        preset = self._current_preset()
        if not preset:
            messagebox.showwarning("送信エラー", "送信者プリセットを選択してください。",
                                   parent=self._win)
            return
        kind = _MSG_TYPE_BY_LABEL.get(self._msg_type_var.get(), "textMessageEvent")
        body_needed = kind not in ("superStickerEvent", "membershipGiftingEvent", "giftMembershipReceivedEvent")
        body = self._body_text.get("1.0", tk.END).strip()
        if body_needed and not body and kind not in ("superChatEvent", "memberMilestoneChatEvent"):
            messagebox.showwarning("送信エラー", "コメント本文を入力してください。",
                                   parent=self._win)
            return

        # 金額
        sc_amount = self._amount_var.get().strip() if kind in ("superChatEvent", "superStickerEvent") else "¥500"
        if kind in ("superChatEvent", "superStickerEvent") and not sc_amount:
            messagebox.showwarning("送信エラー", "金額を入力してください。", parent=self._win)
            return

        # ギフト数
        try:
            gift_count = int(self._gift_var.get()) if kind == "membershipGiftingEvent" else 1
        except ValueError:
            gift_count = 1

        # 接続先を解決
        self._refresh_source_list()
        src_label = self._source_var.get()
        entry = self._source_map.get(src_label, ("conn1", "接続1", "youtube", "接続1"))
        source_id    = entry[0]
        source_name  = entry[1]
        platform     = entry[2] if len(entry) > 2 else "youtube"
        tts_name     = entry[3] if len(entry) > 3 else source_name
        source_type  = INPUT_SOURCE_TWITCH if platform == "twitch" else INPUT_SOURCE_DEBUG

        raw = _build_debug_raw(preset, body, source_id=source_id, source_name=source_name,
                               source_type=source_type, tts_source_name=tts_name,
                               msg_type=kind, sc_amount=sc_amount, gift_count=gift_count)
        self._add_comment(raw)

        # 送信後に本文クリア
        self._body_text.delete("1.0", tk.END)
        self._body_text.focus_set()

    # ─── プリセット CRUD ─────────────────────────────────────────────────────

    def _new_preset(self):
        _PresetEditDialog(
            self._win,
            title="新規プリセット",
            initial={},
            on_ok=self._on_preset_save_new,
        )

    def _edit_preset(self):
        preset = self._current_preset()
        if not preset:
            messagebox.showwarning("編集エラー", "プリセットを選択してください。",
                                   parent=self._win)
            return
        _PresetEditDialog(
            self._win,
            title=f"プリセット編集: {preset['name']}",
            initial=preset,
            on_ok=lambda data: self._on_preset_save_edit(preset["name"], data),
        )

    def _delete_preset(self):
        preset = self._current_preset()
        if not preset:
            messagebox.showwarning("削除エラー", "プリセットを選択してください。",
                                   parent=self._win)
            return
        if not messagebox.askyesno(
            "削除確認",
            f"「{preset['name']}」を削除しますか？",
            parent=self._win
        ):
            return
        presets = self._get_presets()
        presets = [p for p in presets if p["name"] != preset["name"]]
        self._set_presets(presets)
        self._reload_presets()

    def _on_preset_save_new(self, data: dict):
        presets = self._get_presets()
        # 重複名チェック
        if any(p["name"] == data["name"] for p in presets):
            messagebox.showerror("保存エラー",
                                 f"「{data['name']}」はすでに存在します。",
                                 parent=self._win)
            return
        presets.append(data)
        self._set_presets(presets)
        self._preset_var.set(data["name"])
        self._reload_presets()

    def _on_preset_save_edit(self, old_name: str, data: dict):
        presets = self._get_presets()
        # 名前変更時の重複チェック
        if data["name"] != old_name and any(p["name"] == data["name"] for p in presets):
            messagebox.showerror("保存エラー",
                                 f"「{data['name']}」はすでに存在します。",
                                 parent=self._win)
            return
        for i, p in enumerate(presets):
            if p["name"] == old_name:
                presets[i] = data
                break
        self._set_presets(presets)
        self._preset_var.set(data["name"])
        self._reload_presets()


# ════════════════════════════════════════════════════════════════════════════
#  プリセット編集ダイアログ
# ════════════════════════════════════════════════════════════════════════════

class _PresetEditDialog:
    """送信者プリセットの新規作成 / 編集ダイアログ"""

    def __init__(self, parent, title: str, initial: dict, on_ok):
        self._on_ok = on_ok
        C   = UI_COLORS

        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.configure(bg=C["bg_main"])
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(parent)
        self._dlg = dlg

        pad = {"padx": 8, "pady": 3}

        # 表示名
        tk.Label(dlg, text="表示名:", font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]).grid(row=0, column=0, sticky=tk.W, **pad)
        self._name_var = tk.StringVar(value=initial.get("name", ""))
        tk.Entry(dlg, textvariable=self._name_var,
                 bg=C["bg_list"], fg=C["fg_main"], insertbackground=C["fg_main"],
                 relief=tk.FLAT, font=(FONT_FAMILY, FONT_SIZE_S), width=24
                 ).grid(row=0, column=1, sticky=tk.EW, **pad)

        # channel_id
        tk.Label(dlg, text="channel_id:", font=(FONT_FAMILY, FONT_SIZE_S),
                 fg=C["fg_label"], bg=C["bg_main"]).grid(row=1, column=0, sticky=tk.W, **pad)
        self._chid_var = tk.StringVar(value=initial.get("channel_id", ""))
        tk.Entry(dlg, textvariable=self._chid_var,
                 bg=C["bg_list"], fg=C["fg_main"], insertbackground=C["fg_main"],
                 relief=tk.FLAT, font=(FONT_FAMILY, FONT_SIZE_S), width=24
                 ).grid(row=1, column=1, sticky=tk.EW, **pad)

        # フラグ
        self._owner_var = tk.BooleanVar(value=initial.get("is_owner",     False))
        self._mod_var   = tk.BooleanVar(value=initial.get("is_moderator", False))
        self._mbr_var   = tk.BooleanVar(value=initial.get("is_member",    False))
        self._ver_var   = tk.BooleanVar(value=initial.get("is_verified",  False))

        for row, (label, var) in enumerate([
            ("配信者 (Owner)",  self._owner_var),
            ("Moderator",       self._mod_var),
            ("Member",          self._mbr_var),
            ("Verified",        self._ver_var),
        ], start=2):
            ttk.Checkbutton(dlg, text=label, variable=var
                            ).grid(row=row, column=0, columnspan=2, sticky=tk.W,
                                   padx=8, pady=2)

        # ボタン
        btn_frame = tk.Frame(dlg, bg=C["bg_main"])
        btn_frame.grid(row=6, column=0, columnspan=2, pady=(8, 8))
        tk.Button(btn_frame, text="OK",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["accent"], fg="#FFFFFF", relief=tk.FLAT,
                  padx=16, pady=2, command=self._on_ok_click
                  ).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="キャンセル",
                  font=(FONT_FAMILY, FONT_SIZE_S),
                  bg=C["bg_list"], fg=C["fg_main"], relief=tk.FLAT,
                  padx=8, pady=2, command=dlg.destroy
                  ).pack(side=tk.LEFT, padx=4)

        dlg.columnconfigure(1, weight=1)
        dlg.wait_window()

    def _on_ok_click(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("入力エラー", "表示名を入力してください。",
                                   parent=self._dlg)
            return
        data = {
            "name":         name,
            "channel_id":   self._chid_var.get().strip() or f"debug_{name}",
            "is_owner":     self._owner_var.get(),
            "is_moderator": self._mod_var.get(),
            "is_member":    self._mbr_var.get(),
            "is_verified":  self._ver_var.get(),
        }
        self._dlg.destroy()
        self._on_ok(data)
