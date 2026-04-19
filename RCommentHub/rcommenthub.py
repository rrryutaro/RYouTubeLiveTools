"""
RCommentHub — YouTube Live コメントハブ  v0.3.1
メインエントリポイントおよびアプリコーディネーター
v0.2.0: 固定2接続（conn1/conn2）同時表示対応
v0.3.0: OAuth 認証 / streamList 継続受信 / fallback 許可制
v0.3.1: Twitch 認証/受信・マルチソース・プロファイル名分離・Overlay OBS 非表示・TTS-Overlay 同期
"""

import tkinter as tk
import datetime
import logging
import os
import sys

from constants import (
    VERSION, WINDOW_TITLE, DEFAULT_WIDTH, DEFAULT_HEIGHT,
    CONFIG_FILENAME, apply_theme, UI_COLORS,
    SOURCE_DEFAULT_NAMES,
)
from comment_controller import CommentController
from comment_window import CommentWindow
from detail_window import DetailWindow
from overlay_window import OverlayWindow
from settings_manager import SettingsManager
from connect_dialog import ConnectDialog
from settings_window import SettingsWindow
from debug_sender import DebugSenderWindow

def _resolve_runtime_base_dir() -> str:
    """
    ランタイム基準ディレクトリを返す。
    exe 実行 / Python 実行どちらでも dist/ を基準とする。

    - frozen (exe 実行): sys.executable の存在フォルダ = dist/
    - Python 実行 (ランチャー含む): __file__ の親 / dist/
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
    return os.path.normpath(base)


BASE_DIR = _resolve_runtime_base_dir()
os.makedirs(BASE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

# ─── 経路判定用ログファイル (route_check.log) ────────────────────────────────
_route_log_dir  = os.path.join(BASE_DIR, "logs")
os.makedirs(_route_log_dir, exist_ok=True)
ROUTE_LOG_PATH  = os.path.join(_route_log_dir, "route_check.log")

_route_fh = logging.FileHandler(ROUTE_LOG_PATH, encoding="utf-8")
_route_fh.setLevel(logging.INFO)
_route_fh.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_route_logger = logging.getLogger("route_check")
_route_logger.addHandler(_route_fh)
_route_logger.propagate = True   # コンソール出力も兼ねる

_route_logger.info(
    "[route-check] session_start ts=%s",
    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
)

# ─── YouTube 接続異常解析用ログファイル (youtube_error.log) ─────────────────
YT_ERROR_LOG_PATH = os.path.join(_route_log_dir, "youtube_error.log")

_yt_error_fh = logging.FileHandler(YT_ERROR_LOG_PATH, encoding="utf-8")
_yt_error_fh.setLevel(logging.INFO)
_yt_error_fh.setFormatter(logging.Formatter(
    "%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_yt_error_logger = logging.getLogger("youtube_error")
_yt_error_logger.addHandler(_yt_error_fh)
_yt_error_logger.propagate = False  # route_check.log への混入を防ぐ

# ─── API 使用量診断ログ (youtube_api_usage.log) ─────────────────────────────
YT_API_USAGE_LOG_PATH = os.path.join(_route_log_dir, "youtube_api_usage.log")

_yt_api_usage_fh = logging.FileHandler(YT_API_USAGE_LOG_PATH, encoding="utf-8")
_yt_api_usage_fh.setLevel(logging.INFO)
_yt_api_usage_fh.setFormatter(logging.Formatter(
    "%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_yt_api_usage_logger = logging.getLogger("youtube_api_usage")
_yt_api_usage_logger.addHandler(_yt_api_usage_fh)
_yt_api_usage_logger.propagate = False  # route_check.log への混入を防ぐ
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

CONFIG_FILE = os.path.join(BASE_DIR, CONFIG_FILENAME)

DEFAULT_CONFIG = {
    # 詳細ウィンドウ位置・サイズ
    "x": 100, "y": 100,
    "width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT,
    "sash_filter_list": 200,
    "sash_list_detail": 650,
    "sash_main_log":    560,
    "font_size_name":   9,
    "font_size_body":   9,
    "cw_grip_visible":  True,
    # コメントビュー位置・サイズ（_on_configure で更新、shutdown で保存）
    "cw_x": 100, "cw_y": 100,
    "cw_width": 440, "cw_height": 680,
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

        # 接続ダイアログ（マルチプラットフォーム対応）
        self._connect_dialog = ConnectDialog(
            master=root,
            extract_fn=_extract_video_id,
            verify_fn=self._ctrl.verify_target,
            connect_fn=self._on_connect_fn,
            api_key_getter=lambda: self._sm.api_key,
            topmost_getter=_topmost_getter,
            pos_getter=lambda: self._sm.get("cd_pos", None),
            pos_setter=lambda pos: self._sm.update({"cd_pos": pos}),
            url_getter=self._get_first_profile_url,
            url_saver=self._save_first_profile_url,
            auth_checker=lambda: self._ctrl.auth_service.is_authenticated(),
            auth_mode_getter=lambda: self._sm.get("auth_mode", "api_key"),
            profiles_getter=lambda: self._ctrl.get_profiles(),
            twitch_auth_checker=lambda: self._ctrl.twitch_auth.is_authenticated(),
        )

        # 設定ウィンドウ
        self._settings_win = SettingsWindow(
            master=root,
            settings_mgr=self._sm,
            on_settings_changed=self._on_settings_changed,
            topmost_getter=_topmost_getter,
            pos_getter=lambda: self._sm.get("sw_pos", None),
            pos_setter=lambda pos: self._sm.update({"sw_pos": pos}),
            auth_service_getter=lambda: self._ctrl.auth_service,
            twitch_auth_getter=lambda: self._ctrl.twitch_auth,
            overlay_placement_cb=lambda: self._overlay_win.toggle_placement_mode(),
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
            sources_getter=self._get_active_sources,
        )

        # Overlay ウィンドウ（配信用簡易表示）
        self._overlay_win = OverlayWindow(
            master=root,
            settings_mgr=self._sm,
            topmost_getter=_topmost_getter,
        )

        # 詳細ウィンドウ（補助画面）
        self._detail_win = DetailWindow(
            root=root,
            controller=self._ctrl,
            settings_mgr=self._sm,
            cfg=self.cfg,
            comment_window_getter=lambda: self._comment_window,
            open_connect_cb=self._open_connect_dialog,
            open_settings_cb=self._open_settings_window,
            debug_win_opener=self._debug_win.open,
            base_dir=BASE_DIR,
        )

        # コントローラ → コーディネーター間のコールバック登録
        self._ctrl.on_conn_status(self._on_ctrl_conn_status)
        self._ctrl.on_stream_info(self._on_ctrl_stream_info)
        self._ctrl.on_user_cleared(self._on_ctrl_user_cleared)
        self._ctrl.on_debug_mode(self._on_ctrl_debug_mode)
        self._ctrl.on_comment_added(self._on_ctrl_comment_added)
        self._ctrl.on_comment_added(self._on_ctrl_comment_for_overlay)
        # per-source 状態変化 → マルチ接続モード切替
        self._ctrl.on_source_status(self._on_ctrl_source_status)

        # TTS 初期化 + Overlay 同期コールバック登録
        self._ctrl.apply_tts_from_settings()
        self._ctrl.set_tts_on_speak(self._on_tts_speak_item)
        self._ctrl.set_tts_on_spoken(self._on_tts_spoken_item)

        # 起動時にコメントビューを自動表示
        root.after(100, self._comment_window.open)
        root.after(200, self._ctrl.flush_pending_logs)
        self._ctrl.log(f"RCommentHub v{VERSION} 起動完了")

    def _detail_window_open(self):
        """コメントビューからの詳細ウィンドウ表示要求"""
        self._detail_win.open()

    def _open_connect_dialog(self):
        self._connect_dialog.open()

    def _open_settings_window(self):
        self._settings_win.open()

    def _get_first_profile_url(self) -> str:
        """接続ダイアログのプリフィル用: 最初のプロファイルの URL を返す"""
        profiles = self._ctrl.get_profiles()
        if profiles:
            return profiles[0].get("target_url", "")
        return self._sm.get("conn1_url", "")

    def _save_first_profile_url(self, url: str):
        """接続ダイアログの確認後: 最初のプロファイルの URL を保存する"""
        profiles = self._ctrl.get_profiles()
        if profiles:
            profiles[0]["target_url"] = url
            self._sm.save_connection_profiles(profiles)
        else:
            self._sm.update({"conn1_url": url})

    def _on_connect_fn(self, profile_id: str, verify_result: dict):
        """ConnectDialog から呼ばれる接続開始（指定プロファイル + 他の有効プロファイルを自動接続）"""
        self._ctrl.connect_all_enabled_after(verify_result, profile_id)

    def _get_active_sources(self) -> list:
        """
        デバッグ送信ウィンドウ用: 送信先として使える接続の一覧を返す。

        - デバッグモード中: 設定で「有効」になっているプロファイルを全て返す
        - 通常接続中: 実際に receiving/connecting/reconnecting なプロファイルのみ返す
        """
        profiles = self._ctrl.get_profiles()
        result   = []

        def _oname(p):
            return p.get("overlay_name", p.get("display_name", p.get("profile_id", "接続")))

        def _tname(p):
            return p.get("tts_name", _oname(p))

        if self._ctrl.debug_mode:
            for p in profiles:
                if p.get("enabled", True):
                    result.append((p["profile_id"], _oname(p), p.get("platform", "youtube"), _tname(p)))
        else:
            statuses = self._ctrl.get_conn_statuses()
            for p in profiles:
                pid = p["profile_id"]
                if statuses.get(pid, "disconnected") not in ("disconnected", "error"):
                    result.append((pid, _oname(p), p.get("platform", "youtube"), _tname(p)))

        if not result and profiles:
            first = profiles[0]
            return [(first["profile_id"], _oname(first), first.get("platform", "youtube"), _tname(first))]
        return result if result else [("profile_0", "接続1", "youtube", "接続1")]

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
        """デバッグモード変化 → デバッグ送信ウィンドウを開く・接続元ラベル切替"""
        if open_sender:
            self._debug_win.open()
        self._update_source_visible()

    def _on_ctrl_comment_added(self, item):
        """コントローラからのコメント追加通知 → CommentWindow に反映"""
        if self._comment_window and self._comment_window.is_open:
            self._comment_window.add_comment(item)

    def _on_ctrl_comment_for_overlay(self, item):
        """
        コントローラからのコメント追加通知 → Overlay に反映。
        TTS が有効な場合は TTS の読み上げタイミングで Overlay を更新するため、
        ここでは TTS が無効のときのみ即時表示する。
        システムメッセージは設定 youtube_disconnect_notify_overlay が OFF の場合は Overlay に出さない。
        """
        if item.is_system_message:
            if not self._sm.get("youtube_disconnect_notify_overlay", False):
                return
        if self._overlay_win and not self._ctrl.tts_enabled:
            self._overlay_win.show_comment(item)

    def _on_tts_speak_item(self, item):
        """TTS が読み上げを開始するときに Overlay を更新する（TTS-Overlay 同期）"""
        if self._overlay_win:
            self._root.after(0, lambda: self._overlay_win.show_comment(item, suppress_auto_hide=True))

    def _on_tts_spoken_item(self, item):
        """TTS 読み上げ完了後に Overlay の消去タイマーを起動する（TTS-Overlay 同期）"""
        if self._overlay_win:
            self._root.after(0, self._overlay_win.notify_tts_spoken)

    def _on_ctrl_source_status(self, source_id: str, status: str):
        """per-source 接続状態変化 → マルチ接続モードの切替判定"""
        if self._comment_window is None:
            return
        self._update_source_visible()

    def _compute_show_source(self) -> bool:
        """接続元ラベルを表示すべきかを返す。
        ユーザー設定で常時 ON、2プロファイル以上 active、または
        デバッグモードで有効プロファイルが2件以上の場合に True。"""
        if self._sm.get("cw_show_source", False):
            return True
        if self._ctrl.is_multi_conn_active():
            return True
        if self._ctrl.debug_mode:
            profiles = self._ctrl.get_profiles()
            enabled  = sum(1 for p in profiles if p.get("enabled", True))
            return enabled >= 2
        return False

    def _update_source_visible(self):
        """接続元ラベルの表示/非表示を評価し、変化があれば CommentWindow を更新する"""
        if self._comment_window is None:
            return
        show = self._compute_show_source()
        was  = self._comment_window._show_source
        if show != was:
            self._comment_window.set_source_visible(show)
            if self._comment_window.is_open:
                self._comment_window.reload_cards(self._ctrl.comments)
                title = self._ctrl.video_title if self._ctrl.conn_status == "receiving" else ""
                self._comment_window.set_conn_status(self._ctrl.conn_status, title)

    # --- 設定変更 ---

    def _on_settings_changed(self):
        self._ctrl.apply_auth_from_settings()
        self._ctrl.apply_tts_from_settings()
        if self._overlay_win:
            self._overlay_win.on_settings_changed()

        old_display_rows  = self._comment_window._cfg.get("display_rows", 2) if self._comment_window else 2
        old_icon_visible  = self._comment_window._cfg.get("icon_visible", True) if self._comment_window else True
        old_font_size_name = self._comment_window._cfg.get("font_size_name", 9) if self._comment_window else 9
        old_font_size_body = self._comment_window._cfg.get("font_size_body", 9) if self._comment_window else 9

        new_theme    = self._sm.get("color_theme", "ダーク (デフォルト)")
        theme_changed = (new_theme != self._current_theme)
        apply_theme(new_theme)
        self._current_theme = new_theme

        if self._comment_window:
            # 表示設定を CommentWindow の cfg に同期
            self._comment_window._cfg["display_rows"]    = self._sm.get("display_rows", 2)
            self._comment_window._cfg["icon_visible"]    = self._sm.get("icon_visible", True)
            self._comment_window._cfg["font_size_name"]  = self._sm.get("font_size_name", 9)
            self._comment_window._cfg["font_size_body"]  = self._sm.get("font_size_body", 9)
            self._comment_window.topmost_var.set(self._sm.get("cw_topmost", False))
            self._comment_window._cfg["cw_comment_alpha"] = self._sm.get("cw_comment_alpha", 100)
            self._comment_window.apply_transparency(self._sm.get("cw_transparent", False))
            display_changed = (
                self._sm.get("display_rows", 2) != old_display_rows or
                self._sm.get("icon_visible", True) != old_icon_visible
            )
            font_changed = (
                self._sm.get("font_size_name", 9) != old_font_size_name or
                self._sm.get("font_size_body", 9) != old_font_size_body
            )
            if (theme_changed or display_changed or font_changed) and self._comment_window.is_open:
                self._comment_window.reload_cards(self._ctrl.comments)
                self._comment_window.refresh_user_tree()
                self._comment_window.refresh_rule_tree()
                title = self._ctrl.video_title if self._ctrl.conn_status == "receiving" else ""
                self._comment_window.set_conn_status(self._ctrl.conn_status, title)

        self._update_source_visible()
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
        # DEFAULT_CONFIG のキーのみを shutdown に渡す。
        # self.cfg には起動時に self._sm.load() で混入した全設定値が含まれており、
        # そのまま渡すと auth_mode 等の設定が起動時の古い値で上書きされるため。
        cfg_layout = {k: v for k, v in self.cfg.items() if k in DEFAULT_CONFIG}
        self._ctrl.shutdown(cfg_layout)
        if self._comment_window:
            self._comment_window.close()
        if self._overlay_win:
            self._overlay_win.close()
        self._root.destroy()


def main():
    # 隠しルート（アプリライフサイクルアンカー、UI なし）
    root = tk.Tk()
    root.withdraw()
    app = RCommentHubApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
