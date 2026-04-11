"""
RCommentHub — Overlay ウィンドウ（配信用独立表示）v2

監視用コメントビューとは完全に独立した配信用 Overlay。
- Canvas ベースで描画（透過モード対応）
- ドラッグ移動・リサイズグリップ
- 位置・サイズを設定として保存・復元
- 表示モード: timed（一定秒後消去）/ always（常時表示）

設定キー (overlay_* 系):
  overlay_enabled          bool   False
  overlay_display_mode     str    "timed" | "always"
  overlay_duration_sec     int    5
  overlay_x                int    (画面下部中央)
  overlay_y                int    (画面下部中央)
  overlay_width            int    560
  overlay_height           int    110
  overlay_topmost          bool   True
  overlay_transparent      bool   False
  overlay_show_source      bool   False
  overlay_show_icon        bool   True
  overlay_font_size_name   int    9
  overlay_font_size_body   int    11
"""

import ctypes
import io
import threading
import tkinter as tk
import urllib.request

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from constants import FONT_FAMILY, TRANSPARENT_KEY, SOURCE_COLORS, SOURCE_DEFAULT_NAMES, get_source_color
from display_utils import normalize_display_text

# ─── カラー定数 ───────────────────────────────────────────────────────────────
_BG_DARK    = "#0D0D1A"
_BG_HEADER  = "#1A1A30"
_FG_HEADER  = "#555577"
_FG_SOURCE  = "#FFAA44"
_FG_AUTHOR  = "#88CCFF"
_FG_BODY    = "#FFFFFF"
_FG_GRIP    = "#444466"
_ICON_SIZE  = 36
_ICON_PAD   = 8
_HEADER_H   = 14    # 上部ドラッグ帯の高さ
_GRIP_SIZE  = 16
_DEF_W      = 560
_DEF_H      = 110
_DEF_MARGIN = 80    # 画面下端からのデフォルト距離

# ─── Windows スタイル定数 ────────────────────────────────────────────────────
GWL_EXSTYLE      = -20
WS_EX_APPWINDOW  = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080


# ─── アイコン生成ユーティリティ ──────────────────────────────────────────────

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
    try:
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
        draw.text(((size - tw) / 2, (size - th) / 2 - 1), initial,
                  fill="#FFFFFF", font=font)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


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
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        img.putalpha(mask)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
#  OverlayWindow
# ════════════════════════════════════════════════════════════════════════════

class OverlayWindow:
    """配信用 Overlay ウィンドウ（監視用ビューとは独立した Toplevel）"""

    def __init__(self, master: tk.Tk, settings_mgr, topmost_getter=None):
        self._master         = master
        self._sm             = settings_mgr
        self._topmost_getter = topmost_getter or (lambda: True)

        self._win:    tk.Toplevel | None = None
        self._canvas: tk.Canvas   | None = None
        self._grip:   tk.Label    | None = None

        self._hide_job  = None
        self._save_job  = None
        self._current_item = None

        # アイコンキャッシュ（channel_id → PhotoImage | None）
        self._icon_cache: dict = {}
        # Canvas 内の画像参照（GC 防止）
        self._img_refs: list = []

        # ドラッグ用
        self._drag_ox = 0
        self._drag_oy = 0

        # リサイズ用
        self._rz_x0 = 0
        self._rz_y0 = 0
        self._rz_w0 = 0
        self._rz_h0 = 0

        # 配置確認モード
        self._placement_mode    = False
        self._placement_btn:    tk.Button | None = None

    # ─── 公開 API ──────────────────────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return bool(self._sm.get("overlay_enabled", False))

    def show_comment(self, item) -> None:
        """コメントを Overlay に表示する。無効時は何もしない。"""
        if not self.is_enabled:
            return
        self._ensure_window()
        if not self._win_ok():
            return

        self._current_item = item
        self._cancel_hide()

        # ウィンドウ表示
        try:
            self._win.deiconify()
            self._win.lift()
        except Exception:
            return

        # 内容描画
        self._draw(item)

        # 消去スケジュール（timed モード）
        if self._sm.get("overlay_display_mode", "timed") == "timed":
            duration = max(1, int(self._sm.get("overlay_duration_sec",
                                               self._sm.get("overlay_duration", 5))))
            self._hide_job = self._win.after(duration * 1000, self._hide)

    def on_settings_changed(self) -> None:
        """設定変更後に呼び出す（topmost / 透過 などを再適用）"""
        if not self._win_ok():
            return
        try:
            topmost = bool(self._sm.get("overlay_topmost", True))
            self._win.wm_attributes("-topmost", topmost)
            self._apply_transparency()
            # 現在表示中なら再描画
            if self._current_item:
                self._draw(self._current_item)
        except Exception:
            pass

    def toggle_placement_mode(self) -> None:
        """配置確認モードを切り替える"""
        if self._placement_mode:
            self._exit_placement_mode()
        else:
            self._enter_placement_mode()

    @property
    def placement_mode(self) -> bool:
        return self._placement_mode

    def _enter_placement_mode(self) -> None:
        """配置確認モードに入る: 常に可視化してドラッグ・リサイズできるよう表示する"""
        self._placement_mode = True
        self._ensure_window()
        if not self._win_ok():
            return
        # 透過を一時解除して可視化
        try:
            self._win.configure(bg="#1A2A3A")
            if self._canvas:
                self._canvas.configure(bg="#1A2A3A")
            try:
                self._win.wm_attributes("-transparentcolor", "")
            except Exception:
                pass
        except Exception:
            pass
        # 配置確認ボタンを配置
        self._place_placement_btn()
        # 配置確認コンテンツを描画
        self._draw_placement_guide()
        try:
            self._win.deiconify()
            self._win.lift()
        except Exception:
            pass

    def _exit_placement_mode(self) -> None:
        """配置確認モードを終了し、通常の透過設定に戻す"""
        self._placement_mode = False
        # ボタン削除
        if self._placement_btn:
            try:
                self._placement_btn.destroy()
            except Exception:
                pass
            self._placement_btn = None
        if not self._win_ok():
            return
        # 通常表示に戻す
        self._apply_transparency()
        # 表示中のコメントがなければ隠す
        if not self._current_item:
            self._hide()
        else:
            self._draw(self._current_item)

    def _place_placement_btn(self) -> None:
        """配置確認終了ボタンをウィンドウ右上に配置する"""
        if not self._win_ok():
            return
        if self._placement_btn:
            try:
                self._placement_btn.destroy()
            except Exception:
                pass
        self._placement_btn = tk.Button(
            self._win,
            text="配置確認終了",
            font=("メイリオ", 8, "bold"),
            bg="#AA2222", fg="#FFFFFF",
            activebackground="#CC4444",
            relief=tk.FLAT,
            padx=6, pady=2,
            command=self._exit_placement_mode,
        )
        self._win.after(50, self._reposition_placement_btn)

    def _reposition_placement_btn(self) -> None:
        if not self._win_ok() or self._placement_btn is None:
            return
        try:
            w = self._win.winfo_width()
            self._placement_btn.place(x=w - 90, y=2)
            self._placement_btn.lift()
        except Exception:
            pass

    def _draw_placement_guide(self) -> None:
        """配置確認モード用のガイド表示を Canvas に描画する"""
        if not self._win_ok() or self._canvas is None:
            return
        c = self._canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1:
            self._win.after(80, self._draw_placement_guide)
            return
        c.delete("all")
        self._img_refs.clear()
        # 背景
        c.create_rectangle(0, 0, w, h, fill="#1A2A3A", outline="")
        # 枠線
        c.create_rectangle(2, 2, w - 2, h - 2, fill="", outline="#44AAFF", width=2)
        # ヘッダー帯
        c.create_rectangle(0, 0, w, _HEADER_H, fill="#0A1A2A", outline="")
        c.create_text(6, _HEADER_H // 2,
                      text="RCommentHub Overlay — 配置確認モード",
                      font=("メイリオ", 7), fill="#44AAFF", anchor=tk.W)
        # ガイドテキスト
        cy = h // 2 - 10
        c.create_text(w // 2, cy,
                      text="ドラッグして位置を調整  /  右下◢でリサイズ",
                      font=("メイリオ", 9), fill="#88CCFF", anchor=tk.CENTER)
        c.create_text(w // 2, cy + 20,
                      text="「配置確認終了」で本番表示に戻ります",
                      font=("メイリオ", 8), fill="#6699BB", anchor=tk.CENTER)

    def close(self) -> None:
        """ウィンドウを破棄する（アプリ終了時）"""
        self._placement_mode = False
        self._cancel_hide()
        self._cancel_save()
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None

    # ─── 内部: ウィンドウ生成 ──────────────────────────────────────────────────

    def _win_ok(self) -> bool:
        try:
            return self._win is not None and self._win.winfo_exists()
        except Exception:
            return False

    def _ensure_window(self) -> None:
        if not self._win_ok():
            self._create_window()

    def _create_window(self) -> None:
        try:
            win = tk.Toplevel(self._master)
        except Exception:
            return

        self._win = win
        win.title("RCommentHub Overlay")
        win.overrideredirect(True)

        # ジオメトリ復元
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        w = max(200, int(self._sm.get("overlay_width",  _DEF_W)))
        h = max(60,  int(self._sm.get("overlay_height", _DEF_H)))
        x = int(self._sm.get("overlay_x", (sw - w) // 2))
        y = int(self._sm.get("overlay_y", sh - h - _DEF_MARGIN))
        win.geometry(f"{w}x{h}+{x}+{y}")

        topmost = bool(self._sm.get("overlay_topmost", True))
        win.wm_attributes("-topmost", topmost)

        # ── Canvas（唯一の子ウィジェット）──
        self._canvas = tk.Canvas(win, highlightthickness=0, borderwidth=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # 透過適用
        self._apply_transparency()

        # ── ドラッグバインド（Canvas 全体） ──
        self._canvas.bind("<ButtonPress-1>",  self._drag_start)
        self._canvas.bind("<B1-Motion>",      self._drag_move)

        # ── リサイズグリップ ──
        self._grip = tk.Label(
            win, text="◢", cursor="size_nw_se",
            bg=_BG_HEADER, fg=_FG_GRIP,
            font=(FONT_FAMILY, 8), padx=1, pady=0,
        )
        self._grip.bind("<ButtonPress-1>",   self._resize_start)
        self._grip.bind("<B1-Motion>",       self._resize_move)
        win.after(100, self._place_grip)

        # ── Canvas リサイズ追従 ──
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # ── ジオメトリ保存 ──
        win.bind("<Configure>", self._on_win_configure, add="+")

        # ── Alt+Tab に表示（OBS でウィンドウを選びやすくするため） ──
        win.after(60, self._set_appwindow)

        win.withdraw()  # 初期状態は非表示

    def _apply_transparency(self) -> None:
        if not self._win_ok() or self._canvas is None:
            return
        transparent = bool(self._sm.get("overlay_transparent", False))
        try:
            if transparent:
                self._win.configure(bg=TRANSPARENT_KEY)
                self._canvas.configure(bg=TRANSPARENT_KEY)
                self._win.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
            else:
                self._win.configure(bg=_BG_DARK)
                self._canvas.configure(bg=_BG_DARK)
                try:
                    self._win.wm_attributes("-transparentcolor", "")
                except Exception:
                    pass
        except Exception:
            pass

    # ─── 内部: 描画 ───────────────────────────────────────────────────────────

    def _draw(self, item) -> None:
        """Canvas にコメント内容を描画する"""
        if not self._win_ok() or self._canvas is None or item is None:
            return

        c = self._canvas
        w = c.winfo_width()
        h = c.winfo_height()

        # ウィンドウがまだ描画されていない場合は遅延実行
        if w <= 1 or h <= 1:
            self._win.after(80, lambda i=item: self._draw(i))
            return

        c.delete("all")
        self._img_refs.clear()

        transparent = bool(self._sm.get("overlay_transparent", False))
        bg = TRANSPARENT_KEY if transparent else _BG_DARK

        show_source   = bool(self._sm.get("overlay_show_source",    False))
        show_icon     = bool(self._sm.get("overlay_show_icon",      True))
        fn            = max(7, int(self._sm.get("overlay_font_size_name", 9)))
        fb            = max(7, int(self._sm.get("overlay_font_size_body", 11)))

        # 背景塗り（非透過時）
        if not transparent:
            c.create_rectangle(0, 0, w, h, fill=_BG_DARK, outline="")
            # 上部ドラッグ帯
            c.create_rectangle(0, 0, w, _HEADER_H, fill=_BG_HEADER, outline="")
            c.create_text(6, _HEADER_H // 2, text="RCommentHub Overlay",
                          font=(FONT_FAMILY, 7), fill=_FG_HEADER, anchor=tk.W)

        # アイコン領域
        icon_x = _ICON_PAD
        icon_y = _HEADER_H + _ICON_PAD
        if show_icon:
            text_x = _ICON_SIZE + _ICON_PAD * 2
        else:
            text_x = _ICON_PAD

        y_cur = _HEADER_H + 6

        # 接続元名
        if show_source:
            sid   = getattr(item, "source_id",   "conn1")
            sname = getattr(item, "source_name", "") or SOURCE_DEFAULT_NAMES.get(sid, sid)
            if sname:
                sc = get_source_color(sid)
                c.create_text(text_x, y_cur, text=f"[{sname}]",
                              font=(FONT_FAMILY, max(7, fn - 1), "bold"),
                              fill=sc, anchor=tk.NW)
                y_cur += fn + 2

        # 投稿者名
        author = item.author_name or "—"
        c.create_text(text_x, y_cur, text=author,
                      font=(FONT_FAMILY, fn, "bold"),
                      fill=_FG_AUTHOR, anchor=tk.NW)
        y_cur += fn + 4

        # 本文（normalize_display_text で NBSP 置換 → 監視用と改行結果を統一）
        body = item.body or ""
        if body:
            wrap_w = max(80, w - text_x - 10)
            c.create_text(text_x, y_cur, text=normalize_display_text(body),
                          font=(FONT_FAMILY, fb),
                          fill=_FG_BODY, anchor=tk.NW,
                          width=wrap_w)

        # アイコン（PIL 必須）
        if show_icon and _PIL_OK:
            key = item.channel_id or item.author_name
            if key in self._icon_cache and self._icon_cache[key] is not None:
                photo = self._icon_cache[key]
                c.create_image(icon_x, icon_y, image=photo, anchor=tk.NW)
                self._img_refs.append(photo)
            else:
                # プレースホルダ
                ph = _make_placeholder_image(item.author_name, _ICON_SIZE)
                if ph:
                    c.create_image(icon_x, icon_y, image=ph, anchor=tk.NW)
                    self._img_refs.append(ph)
                # 未取得なら非同期ロード開始
                if key not in self._icon_cache and item.profile_url:
                    self._icon_cache[key] = None  # ロード中マーク
                    threading.Thread(
                        target=self._load_icon_bg,
                        args=(item.profile_url, key),
                        daemon=True,
                    ).start()

    def _load_icon_bg(self, url: str, key: str) -> None:
        """バックグラウンドでアイコン画像をロードし、再描画をスケジュール"""
        photo = _load_url_image(url, _ICON_SIZE)
        self._icon_cache[key] = photo
        # 現在表示中アイテムのアイコンなら再描画
        if self._current_item:
            cur_key = (getattr(self._current_item, "channel_id", "")
                       or getattr(self._current_item, "author_name", ""))
            if cur_key == key:
                self._master.after(0, lambda: self._draw(self._current_item))

    # ─── 内部: 消去 ───────────────────────────────────────────────────────────

    def _hide(self) -> None:
        self._hide_job = None
        if self._win_ok():
            try:
                self._win.withdraw()
            except Exception:
                pass

    def _cancel_hide(self) -> None:
        if self._hide_job is not None:
            try:
                if self._win_ok():
                    self._win.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _cancel_save(self) -> None:
        if self._save_job is not None:
            try:
                if self._win_ok():
                    self._win.after_cancel(self._save_job)
            except Exception:
                pass
            self._save_job = None

    # ─── 内部: ドラッグ ───────────────────────────────────────────────────────

    def _drag_start(self, event) -> None:
        if not self._win_ok():
            return
        self._drag_ox = event.x_root - self._win.winfo_x()
        self._drag_oy = event.y_root - self._win.winfo_y()

    def _drag_move(self, event) -> None:
        if not self._win_ok():
            return
        x = event.x_root - self._drag_ox
        y = event.y_root - self._drag_oy
        self._win.geometry(f"+{x}+{y}")

    # ─── 内部: リサイズ ───────────────────────────────────────────────────────

    def _resize_start(self, event) -> None:
        if not self._win_ok():
            return
        self._rz_x0 = event.x_root
        self._rz_y0 = event.y_root
        self._rz_w0 = self._win.winfo_width()
        self._rz_h0 = self._win.winfo_height()

    def _resize_move(self, event) -> None:
        if not self._win_ok():
            return
        dx = event.x_root - self._rz_x0
        dy = event.y_root - self._rz_y0
        nw = max(200, self._rz_w0 + dx)
        nh = max(60,  self._rz_h0 + dy)
        self._win.geometry(f"{nw}x{nh}")

    def _place_grip(self) -> None:
        if not self._win_ok() or self._grip is None:
            return
        w = self._win.winfo_width()
        h = self._win.winfo_height()
        self._grip.place(x=w - _GRIP_SIZE, y=h - _GRIP_SIZE)
        self._grip.lift()

    # ─── 内部: イベントハンドラ ───────────────────────────────────────────────

    def _on_canvas_configure(self, event) -> None:
        """Canvas リサイズ時にグリップ再配置・内容再描画"""
        self._place_grip()
        if self._placement_mode:
            self._reposition_placement_btn()
            self._draw_placement_guide()
        elif self._current_item:
            self._draw(self._current_item)

    def _on_win_configure(self, event) -> None:
        """ウィンドウ移動・リサイズ時にジオメトリをデバウンス保存"""
        if not self._win_ok() or event.widget is not self._win:
            return
        self._cancel_save()
        self._save_job = self._win.after(400, self._save_geometry)

    def _save_geometry(self) -> None:
        self._save_job = None
        if not self._win_ok():
            return
        try:
            self._sm.update({
                "overlay_x":      self._win.winfo_x(),
                "overlay_y":      self._win.winfo_y(),
                "overlay_width":  self._win.winfo_width(),
                "overlay_height": self._win.winfo_height(),
            })
        except Exception:
            pass

    def _set_appwindow(self) -> None:
        """overrideredirect 時も Alt+Tab / OBS ウィンドウリストに表示されるよう設定"""
        if not self._win_ok():
            return
        try:
            hwnd  = ctypes.windll.user32.GetParent(self._win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass
