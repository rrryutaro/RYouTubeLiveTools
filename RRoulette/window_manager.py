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
    CFG_PANEL_W, MIN_W, MIN_H, SIZE_PROFILES, TRANSPARENT_KEY,
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

        if self._settings_visible:
            self._ctx.add_command(label="  項目リストを非表示", command=self._toggle_settings)
        else:
            self._ctx.add_command(label="  項目リストを表示", command=self._toggle_settings)

        if self._item_list_float:
            self._ctx.add_command(
                label="● 項目リストを独立ウィンドウにする",
                command=self._toggle_item_list_float,
            )
        else:
            self._ctx.add_command(
                label="  項目リストを独立ウィンドウにする",
                command=self._toggle_item_list_float,
            )

        self._ctx.add_separator()

        for i, (name, w, h) in enumerate(SIZE_PROFILES):
            marker = "●" if i == self._profile_idx else "  "
            self._ctx.add_command(
                label=f"{marker} サイズ {name}  ({w} × {h})",
                command=lambda idx=i: self._set_profile(idx),
            )

        self._ctx.add_separator()

        topmost_mark = "●" if self._topmost else "  "
        self._ctx.add_command(
            label=f"{topmost_mark} 最前面に表示",
            command=self._toggle_topmost,
        )

        trans_mark = "●" if self._transparent else "  "
        self._ctx.add_command(
            label=f"{trans_mark} 背景を透過",
            command=self._toggle_transparent,
        )

        grip_mark = "●" if self._grip_visible else "  "
        self._ctx.add_command(
            label=f"{grip_mark} リサイズグリップを表示",
            command=self._toggle_grip,
        )

        self._ctx.add_separator()
        cfg_label = "  設定パネルを非表示" if self._cfg_panel_visible else "  設定を表示"
        self._ctx.add_command(label=cfg_label, command=self._toggle_cfg_panel)

        if self._cfg_panel_float:
            self._ctx.add_command(
                label="● 設定を独立ウィンドウにする",
                command=self._toggle_cfg_panel_float,
            )
        else:
            self._ctx.add_command(
                label="  設定を独立ウィンドウにする",
                command=self._toggle_cfg_panel_float,
            )

        self._ctx.add_separator()
        self._ctx.add_command(
            label="  ログ出力（結果のみ）",
            command=lambda: self._do_export_log("simple"),
        )
        self._ctx.add_command(
            label="  ログ出力（グループ・項目付き）",
            command=lambda: self._do_export_log("detailed"),
        )
        self._ctx.add_command(
            label="  ログ削除",
            command=self._clear_log,
        )
        self._ctx.add_separator()
        self._ctx.add_command(label="  最小化", command=self._minimize)
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
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_start_w = self.root.winfo_width()
        self._resize_start_h = self.root.winfo_height()

    def _resize_move(self, event):
        if not getattr(self, "_resizing", False):
            return
        dw = event.x_root - self._resize_start_x
        dh = event.y_root - self._resize_start_y
        new_w = max(MIN_W, self._resize_start_w + dw)
        new_h = max(MIN_H, self._resize_start_h + dh)
        self.root.geometry(f"{new_w}x{new_h}")

    def _resize_end(self, event):
        if not getattr(self, "_resizing", False):
            return
        self._resizing = False
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
        new_w = max(120, self._sash_start_w + delta)
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
        self.root.geometry(f"{max(MIN_W, self._sash_start_root_w + diff)}x{cur_h}")
        self._save_config()
        self._redraw()

    def _main_to_root_extra_w(self) -> int:
        """メインパネル幅 → ウィンドウ全体幅の差分（右パネル + main_frame padding）"""
        extra = 16  # main_frame padx=8 × 2
        if not self._item_list_float and self._settings_visible:
            extra += self._sidebar_w + 4 + 8      # sash(4) + padx right(8)
        if not self._cfg_panel_float and self._cfg_panel_visible:
            extra += self._cfg_panel_w + 4 + 8    # sash(4) + padx right(8)
        return extra

    def _sidebar_max_w(self) -> int:
        """現在のウィンドウ幅に基づくサイドバーの最大幅を返す（_clamp_sidebar_w 用）。"""
        win_w = self.root.winfo_width()
        cfg_extra = (self._cfg_panel_w + 4 + 8) if (
            self._cfg_panel_visible and not self._cfg_panel_float
        ) else 0
        return max(120, win_w - cfg_extra - 4 - 8 - 16 - 200)

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
        self.root.geometry(f"{max(MIN_W, self._cfg_resize_start_root_w + diff)}x{cur_h}")
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
            self._sidebar_w = max(120, max_w)
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
            self.root.geometry(f"{max(MIN_W, w - total)}x{h}")
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
        self._save_config()

    # ════════════════════════════════════════════════════════════════
    #  背景透過トグル
    # ════════════════════════════════════════════════════════════════
    def _toggle_transparent(self):
        self._transparent = not self._transparent
        self._apply_transparency()
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
        self._save_config()

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
        self._save_config()

    def _toggle_cfg_panel_float(self):
        """設定パネルの埋め込み／浮動ウィンドウを切り替える。"""
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
