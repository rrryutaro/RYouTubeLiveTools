"""
RRoulette — ウィンドウ管理 Mixin
  - ドラッグ移動 (_drag_start / _drag_move)
  - リサイズグリップ (_build_resize_grip / _resize_start / _resize_move / _toggle_grip)
  - サイドバー幅リサイズ (_sash_start / _sash_move / _sidebar_max_w / _clamp_sidebar_w)
  - Alt+Tab スタイル・最小化 (_set_appwindow / _minimize)
  - コンテキストメニュー (_build_context_menu / _show_context_menu / _popup_menu)
  - パネル表示切替 (_toggle_settings / _toggle_topmost / _toggle_transparent / _toggle_grip)
  - サイズプロファイル (_apply_profile / _set_profile)
"""

import ctypes
import tkinter as tk

from constants import (
    BG, PANEL, DARK2, WHITE,
    GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW,
    CFG_PANEL_W, SIZE_PROFILES, TRANSPARENT_KEY, MAIN_PANEL_PAD,
    MAIN_MIN_W, MAIN_MIN_H, SIDEBAR_MIN_W,
)
from config_utils import _is_on_any_monitor, _parse_geometry

# 浮動ウィンドウの最小サイズ（px）
_FLOAT_WIN_MIN_W = 150
_FLOAT_WIN_MIN_H = 100


class WindowManagerMixin:

    # ════════════════════════════════════════════════════════════════
    #  リサイズグリップ（右下コーナー）
    # ════════════════════════════════════════════════════════════════
    def _build_resize_grip(self):
        grip = tk.Canvas(self.main_frame, width=16, height=16,
                         bg=BG, highlightthickness=0, cursor="size_nw_se")
        for i in range(3):
            offset = 4 + i * 4
            grip.create_line(16, offset, offset, 16, fill="#555577", width=1)
        grip.bind("<ButtonPress-1>", self._resize_start)
        grip.bind("<B1-Motion>",     self._resize_move)
        grip.bind("<ButtonRelease-1>", self._resize_end)
        self._resize_grip = grip
        if self._grip_visible:
            grip.place(relx=1.0, rely=1.0, anchor="se")

    # ════════════════════════════════════════════════════════════════
    #  コンテキストメニュー
    # ════════════════════════════════════════════════════════════════
    def _build_context_menu(self):
        self._ctx = tk.Menu(
            self.root, tearoff=0,
            bg=PANEL, fg=WHITE,
            activebackground=DARK2, activeforeground=WHITE,
            font=("Meiryo", 10), relief=tk.FLAT, bd=1,
        )

    def _show_context_menu(self, event):
        self._ctx.delete(0, tk.END)

        # ── A. 表示 ──────────────────────────────────────
        ctrl_mark = "●" if self._ctrl_box_visible else "  "
        self._ctx.add_command(
            label=f"{ctrl_mark} コントロールボックスを表示",
            command=self._toggle_ctrl_box,
        )

        grip_mark = "●" if self._grip_visible else "  "
        self._ctx.add_command(
            label=f"{grip_mark} リサイズグリップを表示",
            command=self._toggle_grip,
        )

        log_mark = "●" if self._log_overlay_show else "  "
        self._ctx.add_command(
            label=f"{log_mark} ログを表示",
            command=self._toggle_log_overlay,
        )

        self._ctx.add_separator()

        # ── B. サイズ ─────────────────────────────────────
        for i, (name, w, h) in enumerate(SIZE_PROFILES):
            marker = "●" if i == self._profile_idx else "  "
            self._ctx.add_command(
                label=f"{marker} サイズ {name}  ({w} × {h})",
                command=lambda idx=i: self._set_profile(idx),
            )

        self._ctx.add_separator()

        # ── C. 終了 ───────────────────────────────────────
        self._ctx.add_command(label="  終了", command=self._on_close)

        x, y = event.x_root, event.y_root
        self.root.focus_force()
        self.root.after(1, lambda: self._popup_menu(x, y))

    def _popup_menu(self, x, y):
        try:
            self._ctx.tk_popup(x, y)
        finally:
            self._ctx.grab_release()

    # ════════════════════════════════════════════════════════════════
    #  ドラッグ移動
    # ════════════════════════════════════════════════════════════════
    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()
        self._click_start_x = event.x_root
        self._click_start_y = event.y_root
        cv_x = event.x_root - self.cv.winfo_rootx()
        cv_y = event.y_root - self.cv.winfo_rooty()
        on_pointer = self._pointer_hit(cv_x, cv_y)
        if self.spinning and self._pointer_lock_while_spinning:
            self._dragging_pointer     = False
            self._suppress_window_drag = on_pointer
        else:
            self._dragging_pointer     = on_pointer
            self._suppress_window_drag = False

    def _drag_move(self, event):
        if self._dragging_pointer:
            import math as _math
            cv_x = event.x_root - self.cv.winfo_rootx()
            cv_y = event.y_root - self.cv.winfo_rooty()
            dx = cv_x - self.CX
            dy = cv_y - self.CY
            self._pointer_angle = _math.degrees(_math.atan2(dx, -dy)) % 360
            if self._pointer_preset != 4:
                self._pointer_preset = 4
                if self._pointer_preset_var is not None:
                    from constants import POINTER_PRESET_NAMES
                    self._pointer_preset_var.set(POINTER_PRESET_NAMES[4])
            self._save_config()
            self._redraw()
            return
        if self._suppress_window_drag:
            return
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # ════════════════════════════════════════════════════════════════
    #  リサイズ
    # ════════════════════════════════════════════════════════════════
    def _resize_start(self, event):
        if self.spinning or self._flashing:
            self._resizing = False
            return
        self._resizing = True
        self._resize_frame_pending = False
        lb = getattr(self, '_lb_canvas', None)
        if lb and lb.winfo_exists():
            lb._resize_pause = True
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_start_w = self.root.winfo_width()
        self._resize_start_h = self.root.winfo_height()
        self._resize_pending_w = self._resize_start_w
        self._resize_pending_h = self._resize_start_h

    def _resize_move(self, event):
        if not getattr(self, "_resizing", False):
            return
        dw = event.x_root - self._resize_start_x
        dh = event.y_root - self._resize_start_y
        self._resize_pending_w = max(self._root_min_w(), self._resize_start_w + dw)
        self._resize_pending_h = max(MAIN_MIN_H, self._resize_start_h + dh)
        # geometry 適用を ~30fps にスロットル（マウスイベントが密集しても重くしない）
        if not self._resize_frame_pending:
            self._resize_frame_pending = True
            self.root.after(33, self._apply_resize_frame)

    def _apply_resize_frame(self):
        """スロットルされた geometry 適用。"""
        self._resize_frame_pending = False
        if getattr(self, "_resizing", False):
            self.root.geometry(f"{self._resize_pending_w}x{self._resize_pending_h}")

    def _resize_end(self, event):
        if not getattr(self, "_resizing", False):
            return
        self._resizing = False
        self._resize_frame_pending = False
        lb = getattr(self, '_lb_canvas', None)
        if lb and lb.winfo_exists():
            lb._resize_pause = False
        # ドラッグ中に保留されたサイズが残っていれば確定適用
        if hasattr(self, "_resize_pending_w"):
            self.root.geometry(f"{self._resize_pending_w}x{self._resize_pending_h}")
        self._save_config()
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  サイドバー幅リサイズ（サッシュドラッグ）
    # ════════════════════════════════════════════════════════════════
    def _sash_start(self, event):
        if self.spinning or self._flashing:
            self._sashing = False
            return
        self._sashing = True
        self._sash_start_x = event.x_root
        self._sash_start_w = self._sidebar_w
        self._sash_start_root_w = self.root.winfo_width()

    def _sash_move(self, event):
        if not getattr(self, "_sashing", False):
            return
        delta = event.x_root - self._sash_start_x
        new_w = max(SIDEBAR_MIN_W, self._sash_start_w + delta)
        self._sidebar_w = new_w
        # ドラッグ中は widget 幅のみ更新（root.geometry は ButtonRelease 時に確定）
        self.sidebar.configure(width=new_w)

    def _sash_end(self, _event):
        if not getattr(self, "_sashing", False):
            return
        self._sashing = False
        # メインパネルサイズを維持するため root 幅を確定適用
        diff = self._sidebar_w - self._sash_start_w
        cur_h = self.root.winfo_height()
        self.root.geometry(f"{max(self._root_min_w(), self._sash_start_root_w + diff)}x{cur_h}")
        self._save_config()
        self._redraw()

    def _main_to_root_extra_w(self) -> int:
        """メインパネル幅 → ウィンドウ全体幅の差分（右パネル + main_frame padding）"""
        extra = MAIN_PANEL_PAD * 2  # main_frame padx 左右合計
        if not self._item_list_float and self._settings_visible:
            extra += self._sidebar_w + 4 + 8      # sash(4) + padx right(8)
        if not self._cfg_panel_float and self._cfg_panel_visible:
            extra += self._cfg_panel_w + 4 + 8    # sash(4) + padx right(8)
        return extra

    def _root_min_w(self) -> int:
        """表示中のパネル構成に基づくルートウィンドウの最小幅。
        メインパネル最小幅 + 表示中の右パネル幅の合計を返す。"""
        w = MAIN_MIN_W
        if not self._item_list_float and self._settings_visible:
            w += self._sidebar_w + 4 + 8   # sash(4) + padx右(8)
        if not self._cfg_panel_float and self._cfg_panel_visible:
            w += self._cfg_panel_w + 4 + 8
        return w

    def _sidebar_max_w(self) -> int:
        """現在のウィンドウ幅に基づくサイドバーの最大幅を返す（_clamp_sidebar_w 用）。
        root_w = canvas_w + sidebar_w + 20 の関係から
        sidebar_max = root_w - cfg_extra - 12 - MAIN_MIN_W"""
        win_w = self.root.winfo_width()
        cfg_extra = (self._cfg_panel_w + 4 + 8) if (
            self._cfg_panel_visible and not self._cfg_panel_float
        ) else 0
        return max(SIDEBAR_MIN_W, win_w - cfg_extra - 12 - MAIN_MIN_W)

    # ════════════════════════════════════════════════════════════════
    #  設定パネル幅リサイズ
    # ════════════════════════════════════════════════════════════════
    def _cfg_resize_start(self, event):
        if self.spinning or self._flashing:
            self._cfg_resizing = False
            return
        self._cfg_resizing = True
        self._cfg_resize_start_x = event.x_root
        self._cfg_resize_start_w = self._cfg_panel_w
        self._cfg_resize_start_root_w = self.root.winfo_width()

    def _cfg_resize_move(self, event):
        if not getattr(self, "_cfg_resizing", False):
            return
        delta = event.x_root - self._cfg_resize_start_x
        new_w = max(120, self._cfg_resize_start_w + delta)
        self._cfg_panel_w = new_w
        # ドラッグ中は widget 幅のみ更新（root.geometry は ButtonRelease 時に確定）
        self.cfg_panel.configure(width=new_w)

    def _cfg_resize_end(self, _event):
        if not getattr(self, "_cfg_resizing", False):
            return
        self._cfg_resizing = False
        # メインパネルサイズを維持するため root 幅を確定適用
        diff = self._cfg_panel_w - self._cfg_resize_start_w
        cur_h = self.root.winfo_height()
        self.root.geometry(f"{max(self._root_min_w(), self._cfg_resize_start_root_w + diff)}x{cur_h}")
        self._save_config()
        self._redraw()

    def _clamp_sidebar_w(self):
        """ウィンドウ縮小時にサイドバー幅を上限に収める。"""
        if not self._settings_visible or self._item_list_float:
            return
        win_w = self.root.winfo_width()
        if win_w <= 1:
            return
        max_w = self._sidebar_max_w()
        if self._sidebar_w > max_w:
            self._sidebar_w = max(SIDEBAR_MIN_W, max_w)
            self.sidebar.configure(width=self._sidebar_w)

    # ════════════════════════════════════════════════════════════════
    #  Alt+Tab スタイル設定・最小化
    # ════════════════════════════════════════════════════════════════
    def _set_appwindow(self):
        """overrideredirect 時も Alt+Tab に表示されるようスタイルを修正"""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()

        def on_restore(event):
            self.root.overrideredirect(True)
            self.root.after(10, self._set_appwindow)
            self.root.unbind("<Map>")

        self.root.bind("<Map>", on_restore)

    # ════════════════════════════════════════════════════════════════
    #  項目リスト 表示/非表示
    # ════════════════════════════════════════════════════════════════
    def _toggle_settings(self):
        if self._item_list_float:
            if self._sidebar_toplevel and self._sidebar_toplevel.winfo_exists():
                if self._settings_visible:
                    self._sidebar_toplevel.withdraw()
                    self._settings_visible = False
                else:
                    self._sidebar_toplevel.deiconify()
                    self._settings_visible = True
            self._save_config()
            return
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        total = self._sidebar_w + 4 + 8
        if self._settings_visible:
            self._settings_visible = False
            # サイドバー非表示後: min は MAIN_MIN_W（+ 他のパネル分）
            self.root.geometry(f"{max(self._root_min_w(), w - total)}x{h}")
        else:
            self._settings_visible = True
            self.root.geometry(f"{w + total}x{h}")
        self._apply_right_panel_layout()
        self._save_config()

    # ════════════════════════════════════════════════════════════════
    #  最前面表示トグル
    # ════════════════════════════════════════════════════════════════
    def _toggle_topmost(self):
        self._topmost = not self._topmost
        self.root.attributes("-topmost", self._topmost)
        for win in (self._sidebar_toplevel, self._cfg_panel_toplevel):
            if win and win.winfo_exists():
                win.attributes("-topmost", self._topmost)
        if hasattr(self, "_cfg_topmost_var"):
            self._cfg_topmost_var.set(self._topmost)
        self._save_config()

    # ════════════════════════════════════════════════════════════════
    #  背景透過トグル
    # ════════════════════════════════════════════════════════════════
    def _toggle_transparent(self):
        self._transparent = not self._transparent
        self._apply_transparency()
        if hasattr(self, "_cfg_transparent_var"):
            self._cfg_transparent_var.set(self._transparent)
        self._save_config()

    def _apply_transparency(self):
        """透過状態を root / content / canvas / resize_grip に反映する。"""
        if self._transparent:
            key = TRANSPARENT_KEY
            self.root.configure(bg=key)
            self.content.configure(bg=key)
            self.main_frame.configure(bg=key)
            self.cv.configure(bg=key)
            self.root.wm_attributes("-transparentcolor", key)
            # リサイズグリップだけは非透過色を維持して掴めるようにする
            self._resize_grip.configure(bg=DARK2)
        else:
            self.root.configure(bg=BG)
            self.content.configure(bg=BG)
            self.main_frame.configure(bg=BG)
            self.cv.configure(bg=BG)
            self.root.wm_attributes("-transparentcolor", "")
            self._resize_grip.configure(bg=BG)
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  リサイズグリップ 表示/非表示
    # ════════════════════════════════════════════════════════════════
    def _toggle_grip(self):
        self._grip_visible = not self._grip_visible
        if self._grip_visible:
            self._resize_grip.place(relx=1.0, rely=1.0, anchor="se")
        else:
            self._resize_grip.place_forget()
        if hasattr(self, "_cfg_grip_var"):
            self._cfg_grip_var.set(self._grip_visible)
        self._save_config()

    # ════════════════════════════════════════════════════════════════
    #  コントロールボックス 表示/非表示
    # ════════════════════════════════════════════════════════════════
    def _toggle_ctrl_box(self):
        self._ctrl_box_visible = not self._ctrl_box_visible
        if hasattr(self, "_ctrl_box"):
            if self._ctrl_box_visible:
                self._ctrl_box.place(relx=1.0, rely=0.0, anchor="ne", x=-4, y=4)
            else:
                self._ctrl_box.place_forget()
        if hasattr(self, "_cfg_ctrl_box_var"):
            self._cfg_ctrl_box_var.set(self._ctrl_box_visible)
        self._save_config()

    # ════════════════════════════════════════════════════════════════
    #  ログ表示トグル
    # ════════════════════════════════════════════════════════════════
    def _toggle_log_overlay(self):
        self._log_overlay_show = not self._log_overlay_show
        if hasattr(self, "_cfg_overlay_var"):
            self._cfg_overlay_var.set(self._log_overlay_show)
        self._save_config()
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  最大化 / 元に戻す
    # ════════════════════════════════════════════════════════════════
    def _maximize_restore(self):
        if getattr(self, "_maximized", False):
            if hasattr(self, "_pre_maximize_geo"):
                self.root.geometry(self._pre_maximize_geo)
            self._maximized = False
        else:
            self._pre_maximize_geo = self.root.geometry()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"{sw}x{sh}+0+0")
            self._maximized = True
        if hasattr(self, "_ctrl_max_btn"):
            self._ctrl_max_btn.config(text="❐" if self._maximized else "□")
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  浮動ウィンドウ管理
    # ════════════════════════════════════════════════════════════════
    def _open_float_win(self, title, saved_geo=None):
        """モードレスの浮動ウィンドウを作成して返す。"""
        win = tk.Toplevel(self.root)
        win.title(f"RRoulette — {title}")
        win.configure(bg=PANEL)
        win.resizable(True, True)
        win.attributes("-topmost", self._topmost)
        if saved_geo:
            try:
                parsed = _parse_geometry(saved_geo)
                if (parsed
                        and parsed[0] >= _FLOAT_WIN_MIN_W
                        and parsed[1] >= _FLOAT_WIN_MIN_H
                        and _is_on_any_monitor(parsed[2], parsed[3], parsed[0], parsed[1])):
                    win.geometry(saved_geo)
            except Exception:
                pass
        return win

    def _toggle_item_list_float(self):
        """項目リストの埋め込み／浮動ウィンドウを切り替える。"""
        before_extra = self._main_to_root_extra_w()
        if self._sidebar_toplevel and self._sidebar_toplevel.winfo_exists():
            self._item_list_float_geo = self._sidebar_toplevel.geometry()
            self._sidebar_toplevel.destroy()
            self._sidebar_toplevel = None
        self.sidebar.destroy()
        if self._sash is not None:
            self._sash.destroy()
            self._sash = None
        self._item_list_float = not self._item_list_float
        self._build_sidebar()
        self._apply_right_panel_layout()
        after_extra = self._main_to_root_extra_w()
        diff = after_extra - before_extra
        if diff != 0:
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            self.root.geometry(f"{max(self._root_min_w(), cur_w + diff)}x{cur_h}")
        self._save_config()

    def _toggle_cfg_panel_float(self):
        """設定パネルの埋め込み／浮動ウィンドウを切り替える。"""
        before_extra = self._main_to_root_extra_w()
        if self._cfg_panel_toplevel and self._cfg_panel_toplevel.winfo_exists():
            self._cfg_panel_float_geo = self._cfg_panel_toplevel.geometry()
            self._cfg_panel_toplevel.destroy()
            self._cfg_panel_toplevel = None
        self.cfg_panel.destroy()
        if self._cfg_sash_right is not None:
            self._cfg_sash_right.destroy()
            self._cfg_sash_right = None
        self._cfg_panel_float = not self._cfg_panel_float
        self._build_cfg_panel()
        self._apply_right_panel_layout()
        after_extra = self._main_to_root_extra_w()
        diff = after_extra - before_extra
        if diff != 0:
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            self.root.geometry(f"{max(self._root_min_w(), cur_w + diff)}x{cur_h}")
        self._save_config()

    # ════════════════════════════════════════════════════════════════
    #  サイズプロファイル
    # ════════════════════════════════════════════════════════════════
    def _apply_profile(self, idx: int):
        _, main_w, h = SIZE_PROFILES[idx]
        total_w = main_w + self._main_to_root_extra_w()
        self.root.geometry(f"{total_w}x{h}")

    def _set_profile(self, idx: int):
        self._profile_idx = idx
        self._apply_profile(idx)
        self._save_config()
