"""
RCommentHub — PySide6 エントリポイント  v0.4.0

起動構成（v0.3.2 相当）:
  - CommentWindowQt が正規メインウィンドウ（起動時前面表示）
  - DetailWindowQt   が補助画面（詳細ボタンから開く）
  - OverlayWindowQt  が配信用OBS画面（コメント受信時に自動表示）
  - SettingsWindowQt が設定補助画面（設定ボタンから開く）
  - ConnectDialogQt  が接続ダイアログ（接続ボタンから開く）
  - 隠れメインウィンドウ（RCommentHubMainWindow）は廃止
"""

import ctypes
import os
import sys
import logging

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, QObject, Signal, Qt

from constants import VERSION, CONFIG_FILENAME
from comment_controller import CommentController
from settings_manager import SettingsManager
from connect_dialog_qt import ConnectDialogQt
from comment_window_qt import CommentWindowQt
from settings_window_qt import SettingsWindowQt
from detail_window_qt import DetailWindowQt
from overlay_window_qt import OverlayWindowQt


# ════════════════════════════════════════════════════════════════════════════
#  メインスレッドディスパッチャ（ワーカースレッド → Qt メインスレッド）
# ════════════════════════════════════════════════════════════════════════════

class _MainThreadDispatcher(QObject):
    """
    ワーカースレッドから Qt メインスレッドへ callable を安全にディスパッチする。

    Signal/Slot の queued 接続を使うことで、emit したスレッドに関わらず
    slot (_invoke) は常にメインスレッドで実行される。
    QTimer.singleShot(0, ...) はワーカースレッドから呼ぶと Qt が保証しないため使わない。
    """
    _sig = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 明示的に QueuedConnection を指定（ワーカースレッドからの emit を確実にキュー化）
        self._sig.connect(self._invoke, Qt.ConnectionType.QueuedConnection)

    def dispatch(self, cb):
        """任意のスレッドから呼び出し可能。cb はメインスレッドのイベントループで実行される。"""
        self._sig.emit(cb)

    def _invoke(self, cb):
        cb()


# ════════════════════════════════════════════════════════════════════════════
#  単一起動制御（Windows Named Mutex）
# ════════════════════════════════════════════════════════════════════════════

_SINGLE_INSTANCE_MUTEX: list = []  # GC 回避のためモジュール変数で保持

# Local\ プレフィックスで同一セッション内に限定。v2 サフィックスで旧実装との衝突を回避
_MUTEX_NAME = "Local\\RCommentHub_SingleInstance_v2"


def _acquire_single_instance() -> bool:
    """
    True  : このインスタンスが唯一の起動 → 続行可。
    False : すでに起動済みのインスタンスが存在 → 終了すべき。

    Windows Named Mutex 方式。
    ハンドルはプロセス終了時（正常・異常問わず）に OS が自動解放する。

    失敗時の方針（安全側）:
      CreateMutexW が 0/None を返した（API 失敗）場合は単一起動チェック不能として
      起動を継続する。理由: 二重起動を誤検出して起動不能になるより、
      起動できる方が切り分けしやすいため。
    """
    _log.info("Mutex 名: %s", _MUTEX_NAME)
    _ERROR_ALREADY_EXISTS = 183
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.restype  = ctypes.c_void_p
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _kernel32.CloseHandle.argtypes  = [ctypes.c_void_p]

    handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    err    = ctypes.get_last_error()
    _log.info("CreateMutexW → handle=%s  last_error=%d", handle, err)

    if not handle:
        # API 失敗: 単一起動チェック不能 → 安全側として起動継続
        _log.warning("CreateMutexW が失敗 (handle=0) → 単一起動チェックをスキップして起動継続")
        return True

    if err == _ERROR_ALREADY_EXISTS:
        # handle は取得できたが既存 Mutex が存在 → 二重起動
        _log.info("handle 取得済み + last_error=183 (ERROR_ALREADY_EXISTS) → 既存起動ありと判定")
        _kernel32.CloseHandle(handle)
        return False

    # 新規 Mutex 作成成功
    _log.info("Mutex 新規作成成功 (last_error=%d) → 単一起動確認 OK", err)
    _SINGLE_INSTANCE_MUTEX.append(handle)
    return True


def _resolve_runtime_base_dir() -> str:
    """
    ランタイム基準ディレクトリを返す。
    exe 実行 / Python 実行どちらでも dist/ を基準とする。
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
    return os.path.normpath(base)


BASE_DIR    = _resolve_runtime_base_dir()
CONFIG_FILE = os.path.join(BASE_DIR, CONFIG_FILENAME)

os.makedirs(BASE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)


def _setup_file_logging(base_dir: str):
    """
    Tk 版相当のファイルログ出力設定を復元する。
    route_check / youtube_api_usage / youtube_error の各ロガーに FileHandler を追加する。
    出力先: base_dir/logs/<logger_name>.log
    """
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    _file_log_targets = [
        ("route_check",       "route_check.log"),
        ("youtube_api_usage", "youtube_api_usage.log"),
        ("youtube_error",     "youtube_error.log"),
    ]
    fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for logger_name, filename in _file_log_targets:
        log_path = os.path.join(logs_dir, filename)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(fmt)
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = True  # basicConfig の stdout ハンドラへも引き続き出力


_setup_file_logging(BASE_DIR)


# ════════════════════════════════════════════════════════════════════════════
#  Qt アプリコーディネーター
# ════════════════════════════════════════════════════════════════════════════

class RCommentHubQtApp:
    """
    PySide6 版アプリコーディネーター。

    画面役割（v0.3.2 相当）:
      CommentWindowQt  … 正規メインウィンドウ（コメントビュー）
      DetailWindowQt   … 補助画面（詳細・管理）
      OverlayWindowQt  … 配信用OBS画面（最前面）
      SettingsWindowQt … 設定補助画面
      ConnectDialogQt  … 接続ダイアログ

    ライフサイクル:
      setQuitOnLastWindowClosed(False) で手動終了制御。
      × ボタン → _quit_app() → _ctrl.shutdown() + app.quit()
    """

    def __init__(self, app: QApplication):
        self._app = app
        # 最後のウィンドウが閉じてもイベントループを継続（手動終了制御）
        self._app.setQuitOnLastWindowClosed(False)

        self._sm  = SettingsManager(CONFIG_FILE)
        self._sm.load()

        # dispatch_to_main: Signal/Slot queued 接続でワーカースレッドからメインスレッドへ安全に戻す
        self._dispatcher = _MainThreadDispatcher(self._app)
        self._ctrl = CommentController(
            dispatch_to_main=self._dispatcher.dispatch,
            settings_mgr=self._sm,
            base_dir=BASE_DIR,
        )

        # ── 補助画面・ダイアログ（コメントビューより先に生成）──────────────────

        # SettingsWindow
        self._settings_win = SettingsWindowQt(
            parent=None,
            settings_mgr=self._sm,
            on_settings_changed=self._on_settings_changed,
            auth_service_getter=lambda: self._ctrl.auth_service,
            twitch_auth_getter=lambda: self._ctrl.twitch_auth,
            pos_getter=lambda: self._sm.get("sw_pos", None),
            pos_setter=lambda pos: self._sm.update({"sw_pos": pos}),
        )

        # ConnectDialog
        self._connect_dialog = ConnectDialogQt(
            parent=None,
            verify_fn=self._ctrl.verify_target,
            connect_fn=self._on_connect_fn,
            profiles_getter=self._ctrl.get_profiles,
            auth_checker=lambda: self._ctrl.auth_service.is_authenticated(),
            twitch_auth_checker=lambda: self._ctrl.twitch_auth.is_authenticated(),
            url_getter=self._get_first_profile_url,
            url_saver=self._save_first_profile_url,
            pos_getter=lambda: self._sm.get("cd_pos", None),
            pos_setter=lambda pos: self._sm.update({"cd_pos": pos}),
            log_fn=self._ctrl.log,
        )

        # DetailWindow（補助画面）
        self._detail_win = DetailWindowQt(
            controller=self._ctrl,
            settings_mgr=self._sm,
            open_connect_cb=self._open_connect_dialog,
            open_comment_win_cb=self._open_comment_window,
            open_settings_cb=self._open_settings_window,
        )

        # OverlayWindow（配信用OBS画面）
        self._overlay_win = OverlayWindowQt(
            controller=self._ctrl,
            settings_mgr=self._sm,
        )

        # ── 正規メインウィンドウ（CommentWindowQt）────────────────────────────
        self._comment_win = CommentWindowQt(
            controller=self._ctrl,
            settings_mgr=self._sm,
            open_connect_cb=self._open_connect_dialog,
            open_settings_cb=self._open_settings_window,
            open_detail_cb=self._open_detail_window,
            on_quit_cb=self._quit_app,
        )

        # ── コントローラ → 各ウィンドウ コールバック登録 ──────────────────────
        self._ctrl.on_comment_added(self._on_comment_added)
        self._ctrl.on_conn_status(self._on_conn_status)

        # ── 起動: コメントビュー（正規メイン）を前面表示 ──────────────────────
        self._comment_win.open()

        # ── ペンディングログ（起動時に生成されたログ）を UI へフラッシュ ──────
        self._ctrl.flush_pending_logs()
        self._ctrl.log(f"RCommentHub v{VERSION} 起動完了")

    # ─── ConnectDialog 操作 ───────────────────────────────────────────────────

    def _open_connect_dialog(self):
        self._connect_dialog.open()

    def _on_connect_fn(self, profile_id: str, verify_result: dict):
        """ConnectDialogQt から呼ばれる接続開始コールバック。"""
        self._ctrl.connect_all_enabled_after(verify_result, profile_id)
        self._open_comment_window()

    # ─── SettingsWindow 操作 ──────────────────────────────────────────────────

    def _open_settings_window(self):
        self._settings_win.open()

    def _on_settings_changed(self):
        """設定保存後に各ウィンドウへ反映する"""
        self._ctrl.log("設定が更新されました")
        self._comment_win.apply_display_settings()
        self._overlay_win.on_settings_changed()

    # ─── DetailWindow 操作（補助画面） ────────────────────────────────────────

    def _open_detail_window(self):
        """詳細画面（補助画面）を開く。"""
        self._detail_win.open()

    # ─── アプリ終了 ───────────────────────────────────────────────────────────

    def _quit_app(self):
        """
        コメントビューの × ボタンから呼ばれるアプリ終了処理。
        コントローラをシャットダウンしてイベントループを終了する。
        """
        try:
            self._ctrl.shutdown({})
        except Exception:
            pass
        self._app.quit()

    # ─── CommentWindow 操作 ───────────────────────────────────────────────────

    def _open_comment_window(self):
        self._comment_win.open()

    # ─── コントローラ → 各ウィンドウ コールバック ────────────────────────────

    def _on_comment_added(self, item):
        """コントローラからのコメント追加通知 → CommentWindowQt / OverlayWindowQt に反映"""
        if self._comment_win.is_open:
            self._comment_win.add_comment(item)
        self._overlay_win.show_comment(item)

    def _on_conn_status(self, status: str):
        """接続状態変化 → CommentWindowQt のステータスバーに反映"""
        _log.info("接続状態更新コールバックが UI 側へ届いた: status=%s", status)
        title = self._ctrl.video_title if status == "receiving" else ""
        self._comment_win.set_conn_status(status, title)

    # ─── 設定補助 ─────────────────────────────────────────────────────────────

    def _get_first_profile_url(self) -> str:
        profiles = self._ctrl.get_profiles()
        if profiles:
            return profiles[0].get("target_url", "")
        return self._sm.get("conn1_url", "")

    def _save_first_profile_url(self, url: str):
        profiles = self._ctrl.get_profiles()
        if profiles:
            profiles[0]["target_url"] = url
            self._sm.save_connection_profiles(profiles)
        else:
            self._sm.update({"conn1_url": url})


# ════════════════════════════════════════════════════════════════════════════
#  エントリポイント
# ════════════════════════════════════════════════════════════════════════════

_log = logging.getLogger("rcommenthub")


def main():
    app = QApplication(sys.argv)

    # ── 単一起動チェック（Windows Named Mutex） ─────────────────────────────
    _log.info("単一起動チェック開始")
    if not _acquire_single_instance():
        _log.info("既に起動中と判定 → 二重起動として終了")
        QMessageBox.information(
            None,
            "RCommentHub",
            "RCommentHub はすでに起動しています。",
        )
        sys.exit(0)

    # ── メインウィンドウ生成 ──────────────────────────────────────────────
    _log.info("単一起動確認 OK → メインウィンドウ生成開始")
    _qt_app = RCommentHubQtApp(app)  # noqa: F841  アプリライフサイクルアンカー
    _log.info("メインウィンドウ生成完了 → イベントループ開始")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
