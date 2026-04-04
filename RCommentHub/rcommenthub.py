"""
RCommentHub — YouTube Live コメントハブ  v0.2.0
メインエントリポイントおよびアプリコーディネーター
"""

import tkinter as tk
import os
import sys

from constants import (
    VERSION, WINDOW_TITLE, DEFAULT_WIDTH, DEFAULT_HEIGHT,
    CONFIG_FILENAME, apply_theme, UI_COLORS,
)
from comment_controller import CommentController
from comment_window import CommentWindow
from detail_window import DetailWindow
from settings_manager import SettingsManager
from connect_dialog import ConnectDialog
from settings_window import SettingsWindow
from debug_sender import DebugSenderWindow

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, CONFIG_FILENAME)

DEFAULT_CONFIG = {
    "x": 100, "y": 100,
    "width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT,
    "sash_filter_list": 200,
    "sash_list_detail": 650,
    "sash_main_log":    560,
}

def _extract_video_id(text: str) -> str:
    """YouTube URL または動画 ID 文字列から動画 ID を抽出する"""
    import urllib.parse
    text = text.strip()
    if not text:
        return text
    if "youtube.com" not in text and "youtu.be" not in text:
        return text
    try:
        parsed     = urllib.parse.urlparse(text)
        path_parts = [p for p in parsed.path.split("/") if p]
        if "live" in path_parts:
            idx = path_parts.index("live")
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
        if parsed.netloc in ("youtu.be", "www.youtu.be") and path_parts:
            return path_parts[0]
    except Exception:
        pass
    return text


class RCommentHubApp:
    """
    アプリコーディネーター。
    CommentController / CommentWindow / DetailWindow / ダイアログ類を生成して接続する。
    """

    def __init__(self, root: tk.Tk):
        self._root = root

        # 設定
        self._sm  = SettingsManager(CONFIG_FILE)
        self.cfg  = {**DEFAULT_CONFIG, **self._sm.load()}

        # テーマ適用
        saved_theme = self._sm.get("color_theme", "ダーク (デフォルト)")
        apply_theme(saved_theme)
        self._current_theme = saved_theme

        # Combobox ドロップダウンリストの色をテーマに合わせる
        root.option_add("*TCombobox*Listbox.background", UI_COLORS["bg_list"])
        root.option_add("*TCombobox*Listbox.foreground", UI_COLORS["fg_main"])
        root.option_add("*TCombobox*Listbox.selectBackground", UI_COLORS["accent"])
        root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

        # コントローラ（処理の中核）
        self._ctrl = CommentController(root, self._sm, BASE_DIR)

        _topmost_getter = lambda: bool(self._sm.get("cw_topmost", False))

        # コメントビュー（主画面）
        self._comment_window = CommentWindow(
            root, self.cfg,
            on_close_cb=self._on_close,
            speak_cb=self._ctrl.speak_item,
            user_manager=self._ctrl.user_mgr,
            filter_rule_mgr=self._ctrl.filter_mgr,
            open_connect_cb=self._open_connect_dialog,
            open_settings_cb=self._open_settings_window,
            open_detail_cb=self._detail_window_open,
            open_debug_cb=self._ctrl.toggle_debug_mode,
        )

        # 表示設定を CommentWindow の cfg に反映
        self._comment_window._cfg["display_rows"] = self._sm.get("display_rows", 2)
        self._comment_window._cfg["icon_visible"] = self._sm.get("icon_visible", True)

        # 接続ダイアログ
        self._connect_dialog = ConnectDialog(
            master=root,
            extract_fn=_extract_video_id,
            verify_fn=self._ctrl.verify,
            connect_fn=self._ctrl.connect,
            api_key_getter=lambda: self._sm.api_key,
            topmost_getter=_topmost_getter,
            pos_getter=lambda: self._sm.get("cd_pos", None),
            pos_setter=lambda pos: self._sm.update({"cd_pos": pos}),
        )

        # 設定ウィンドウ
        self._settings_win = SettingsWindow(
            master=root,
            settings_mgr=self._sm,
            on_settings_changed=self._on_settings_changed,
            topmost_getter=_topmost_getter,
            pos_getter=lambda: self._sm.get("sw_pos", None),
            pos_setter=lambda pos: self._sm.update({"sw_pos": pos}),
        )

        # デバッグ送信ウィンドウ
        self._debug_win = DebugSenderWindow(
            master=root,
            add_comment_cb=lambda raw: root.after(0, lambda r=raw: self._ctrl.add_comment(r)),
            presets_getter=self._ctrl.get_debug_presets,
            presets_setter=self._ctrl.set_debug_presets,
            mode_enabled_getter=lambda: self._ctrl.debug_mode,
            topmost_getter=_topmost_getter,
            pos_getter=lambda: self._sm.get("ds_pos", None),
            pos_setter=lambda pos: self._sm.update({"ds_pos": pos}),
        )

        # 詳細ウィンドウ（補助画面）- DetailWindow の参照を保持してから CommentWindow に渡す
        self._detail_win = DetailWindow(
            root=root,
            controller=self._ctrl,
            settings_mgr=self._sm,
            cfg=self.cfg,
            comment_window_getter=lambda: self._comment_window,
            open_connect_cb=self._open_connect_dialog,
            open_settings_cb=self._open_settings_window,
            debug_win_opener=self._debug_win.open,
        )

        # コントローラ → コーディネーター間のコールバック登録
        self._ctrl.on_conn_status(self._on_ctrl_conn_status)
        self._ctrl.on_stream_info(self._on_ctrl_stream_info)
        self._ctrl.on_user_cleared(self._on_ctrl_user_cleared)
        self._ctrl.on_debug_mode(self._on_ctrl_debug_mode)
        # コメント追加通知 → CommentWindow へ反映
        self._ctrl.on_comment_added(self._on_ctrl_comment_added)

        # TTS 初期化
        self._ctrl.apply_tts_from_settings()

        # 起動時にコメントビューを自動表示
        root.after(100, self._comment_window.open)
        self._ctrl.log("RCommentHub 起動完了")

    def _detail_window_open(self):
        """コメントビューからの詳細ウィンドウ表示要求"""
        self._detail_win.open()

    def _open_connect_dialog(self):
        self._connect_dialog.open()

    def _open_settings_window(self):
        self._settings_win.open()

    # --- コントローラ → コーディネーター コールバック ---

    def _on_ctrl_conn_status(self, status: str):
        """接続状態変化 → コメントビューへ同期"""
        if self._comment_window:
            title = self._ctrl.video_title if status == "receiving" else ""
            self._comment_window.set_conn_status(status, title)

    def _on_ctrl_stream_info(self, title, video_id, chat_id, stream_status):
        """ストリーム情報変化 → コメントビューへ同期"""
        if self._comment_window and stream_status != "unknown":
            conn = "receiving" if stream_status == "live" else "disconnected"
            self._comment_window.set_conn_status(conn, title)

    def _on_ctrl_user_cleared(self):
        """ユーザー情報クリア → コメントビューのユーザー一覧更新"""
        if self._comment_window and self._comment_window.is_open:
            self._comment_window.refresh_user_tree()

    def _on_ctrl_debug_mode(self, debug_mode: bool, open_sender: bool):
        """デバッグモード変化 → デバッグ送信ウィンドウを開く"""
        if open_sender:
            self._debug_win.open()

    def _on_ctrl_comment_added(self, item):
        """コントローラからのコメント追加通知 → CommentWindow に反映"""
        if self._comment_window and self._comment_window.is_open:
            self._comment_window.add_comment(item)

    # --- 設定変更 ---

    def _on_settings_changed(self):
        self._ctrl.apply_tts_from_settings()

        old_display_rows = self._comment_window._cfg.get("display_rows", 2) if self._comment_window else 2
        old_icon_visible = self._comment_window._cfg.get("icon_visible", True) if self._comment_window else True

        new_theme    = self._sm.get("color_theme", "ダーク (デフォルト)")
        theme_changed = (new_theme != self._current_theme)
        apply_theme(new_theme)
        self._current_theme = new_theme

        if self._comment_window:
            # 表示設定を CommentWindow の cfg に同期
            self._comment_window._cfg["display_rows"] = self._sm.get("display_rows", 2)
            self._comment_window._cfg["icon_visible"] = self._sm.get("icon_visible", True)
            self._comment_window.topmost_var.set(self._sm.get("cw_topmost", False))
            self._comment_window._cfg["cw_comment_alpha"] = self._sm.get("cw_comment_alpha", 100)
            display_changed = (
                self._sm.get("display_rows", 2) != old_display_rows or
                self._sm.get("icon_visible", True) != old_icon_visible
            )
            if (theme_changed or display_changed) and self._comment_window.is_open:
                # close+open せずカードのみ再構築（ウィンドウ維持でちらつきなし）
                self._comment_window.reload_cards(self._ctrl.comments)
                self._comment_window.refresh_user_tree()
                self._comment_window.refresh_rule_tree()
                title = self._ctrl.video_title if self._ctrl.conn_status == "receiving" else ""
                self._comment_window.set_conn_status(self._ctrl.conn_status, title)

        self._apply_topmost_all()
        self._sm.update({"filter_rules": self._ctrl.filter_mgr.to_list()})
        self._ctrl.log("[設定] 保存完了")

    def _apply_topmost_all(self):
        val = bool(self._sm.get("cw_topmost", False))
        for obj in [self._settings_win, self._connect_dialog, self._debug_win]:
            try:
                if obj._win:
                    obj._win.wm_attributes("-topmost", val)
            except Exception:
                pass
        if self._comment_window:
            try:
                if self._comment_window._win:
                    self._comment_window._win.wm_attributes("-topmost", val)
            except Exception:
                pass
        try:
            if self._detail_win._win:
                self._detail_win._win.wm_attributes("-topmost", val)
        except Exception:
            pass

    # --- 終了 ---

    def _on_close(self):
        """コメントビューが閉じられたらアプリ終了"""
        self._ctrl.shutdown(self.cfg)
        if self._comment_window:
            self._comment_window.close()
        self._root.destroy()


def main():
    # 隠しルート（アプリライフサイクルアンカー、UI なし）
    root = tk.Tk()
    root.withdraw()
    app = RCommentHubApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
