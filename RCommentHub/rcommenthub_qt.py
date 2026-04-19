"""
RCommentHub — PySide6 エントリポイント（Phase 4）

Tk 版 rcommenthub.py は維持したまま、PySide6 側の起動口として追加。
今後の GUI 移行において、このファイルを拡張していく。

Phase 4 時点の状態:
  - QApplication / QMainWindow の最小骨格（Phase 1）
  - CommentController への dispatch_to_main 注入（QTimer.singleShot）
  - ConnectDialogQt を MainWindow から開ける導線（Phase 2）
  - 接続成功後に CommentWindowQt を開く導線（Phase 3）
  - SettingsWindowQt を MainWindow から開ける導線（Phase 4）
  - DetailWindow / DebugSenderWindow / OverlayWindow の移植は Phase 5 以降
"""

import os
import sys
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton,
)
from PySide6.QtCore import Qt, QTimer

from constants import VERSION, CONFIG_FILENAME
from comment_controller import CommentController
from settings_manager import SettingsManager
from connect_dialog_qt import ConnectDialogQt
from comment_window_qt import CommentWindowQt
from settings_window_qt import SettingsWindowQt


def _resolve_runtime_base_dir() -> str:
    """
    ランタイム基準ディレクトリを返す（rcommenthub.py と同ロジック）。
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


# ════════════════════════════════════════════════════════════════════════════
#  Main Window（Phase 3: CommentWindow 導線追加）
# ════════════════════════════════════════════════════════════════════════════

class RCommentHubMainWindow(QMainWindow):
    """
    RCommentHub Qt版 メインウィンドウ（Phase 4）。

    Phase 2: ConnectDialog を開く導線
    Phase 3: CommentWindow を開く導線を追加
    Phase 4: SettingsWindow を開く導線を追加
    Phase 5 以降で DetailWindow / OverlayWindow 等を組み込む。
    """

    def __init__(self, controller: CommentController,
                 open_connect_cb=None,
                 open_comment_cb=None,
                 open_settings_cb=None):
        super().__init__()
        self._ctrl            = controller
        self._open_connect    = open_connect_cb  or (lambda: None)
        self._open_comment    = open_comment_cb  or (lambda: None)
        self._open_settings   = open_settings_cb or (lambda: None)

        self.setWindowTitle(f"RCommentHub v{VERSION} [Qt — Phase 4]")
        self.resize(560, 300)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        info_lbl = QLabel(
            f"RCommentHub  v{VERSION}  —  Qt 版 Phase 4\n\n"
            "・Phase 0: CommentController dispatch_to_main 抽象化済み\n"
            "・Phase 1: QApplication / QMainWindow 骨格追加済み\n"
            "・Phase 2: ConnectDialog Qt版 追加済み\n"
            "・Phase 3: CommentWindow Qt版 追加済み（接続成功後に自動表示）\n"
            "・Phase 4: SettingsWindow Qt版 追加済み\n\n"
            "Phase 5 以降で DetailWindow / OverlayWindow 等が組み込まれます。"
        )
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        info_lbl.setWordWrap(True)
        root.addWidget(info_lbl)

        # ボタン行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_connect = QPushButton("接続（ConnectDialog）")
        btn_connect.setMinimumHeight(32)
        btn_connect.clicked.connect(self._open_connect)
        btn_row.addWidget(btn_connect)

        btn_comment = QPushButton("コメントビュー")
        btn_comment.setMinimumHeight(32)
        btn_comment.clicked.connect(self._open_comment)
        btn_row.addWidget(btn_comment)

        btn_settings = QPushButton("設定")
        btn_settings.setMinimumHeight(32)
        btn_settings.clicked.connect(self._open_settings)
        btn_row.addWidget(btn_settings)

        btn_row.addStretch()
        root.addLayout(btn_row)

    def closeEvent(self, event):
        """ウィンドウ閉鎖時にコントローラをシャットダウン"""
        try:
            self._ctrl.shutdown({})
        except Exception:
            pass
        event.accept()


# ════════════════════════════════════════════════════════════════════════════
#  Qt アプリコーディネーター（Phase 3）
# ════════════════════════════════════════════════════════════════════════════

class RCommentHubQtApp:
    """
    PySide6 版アプリコーディネーター（Phase 4）。

    Phase 0 で抽象化済みの dispatch_to_main に QTimer.singleShot を注入。
    Phase 3 では接続成功後に CommentWindowQt を開き、
    コントローラのコールバックを CommentWindowQt に接続する。
    Phase 4 では SettingsWindowQt を追加し MainWindow に「設定」ボタンを接続する。

    Phase 5 以降では DetailWindow / OverlayWindow 等を追加する。
    """

    def __init__(self, app: QApplication):
        self._app = app
        self._sm  = SettingsManager(CONFIG_FILE)

        # dispatch_to_main: QTimer.singleShot(0, cb) でメインスレッドへディスパッチ
        self._ctrl = CommentController(
            dispatch_to_main=lambda cb: QTimer.singleShot(0, cb),
            settings_mgr=self._sm,
            base_dir=BASE_DIR,
        )

        # CommentWindow（Qt版）— 接続成功後に開かれるコメントビュー
        self._comment_win = CommentWindowQt(
            controller=self._ctrl,
            settings_mgr=self._sm,
        )

        # コントローラ → CommentWindowQt コールバック登録
        self._ctrl.on_comment_added(self._on_comment_added)
        self._ctrl.on_conn_status(self._on_conn_status)

        # SettingsWindow（Qt版）
        self._settings_win = SettingsWindowQt(
            parent=None,
            settings_mgr=self._sm,
            on_settings_changed=self._on_settings_changed,
            auth_service_getter=lambda: self._ctrl.auth_service,
            twitch_auth_getter=lambda: self._ctrl.twitch_auth,
            pos_getter=lambda: self._sm.get("sw_pos", None),
            pos_setter=lambda pos: self._sm.update({"sw_pos": pos}),
        )

        # ConnectDialog（Qt版）
        self._connect_dialog = ConnectDialogQt(
            parent=None,
            verify_fn=self._ctrl.verify_target,
            connect_fn=self._on_connect_fn,
            profiles_getter=self._ctrl.get_profiles,
            auth_checker=lambda: self._ctrl.auth_service.is_authenticated(),
            auth_mode_getter=lambda: self._sm.get("auth_mode", "api_key"),
            twitch_auth_checker=lambda: self._ctrl.twitch_auth.is_authenticated(),
            url_getter=self._get_first_profile_url,
            url_saver=self._save_first_profile_url,
            pos_getter=lambda: self._sm.get("cd_pos", None),
            pos_setter=lambda pos: self._sm.update({"cd_pos": pos}),
        )

        # MainWindow（ConnectDialog / CommentWindow / SettingsWindow を開く導線付き）
        self._main_win = RCommentHubMainWindow(
            controller=self._ctrl,
            open_connect_cb=self._open_connect_dialog,
            open_comment_cb=self._open_comment_window,
            open_settings_cb=self._open_settings_window,
        )
        self._main_win.show()

        self._ctrl.log(f"RCommentHub v{VERSION} Qt Phase 4 起動完了")

    # ─── ConnectDialog 操作 ───────────────────────────────────────────────────

    def _open_connect_dialog(self):
        self._connect_dialog.open()

    def _on_connect_fn(self, profile_id: str, verify_result: dict):
        """
        ConnectDialogQt から呼ばれる接続開始コールバック。
        接続を開始し、CommentWindowQt を開く（Phase 3 の要）。
        """
        self._ctrl.connect_all_enabled_after(verify_result, profile_id)
        # 接続成功後にコメントビューを前面に表示
        self._open_comment_window()

    # ─── SettingsWindow 操作 ──────────────────────────────────────────────────

    def _open_settings_window(self):
        self._settings_win.open()

    def _on_settings_changed(self):
        """設定保存後に Qt 側ウィンドウへ反映する（Phase 5-1）"""
        self._ctrl.log("設定が更新されました（Qt版）")
        self._comment_win.apply_display_settings()

    # ─── CommentWindow 操作 ───────────────────────────────────────────────────

    def _open_comment_window(self):
        self._comment_win.open()

    # ─── コントローラ → CommentWindowQt コールバック ─────────────────────────

    def _on_comment_added(self, item):
        """コントローラからのコメント追加通知 → CommentWindowQt に反映"""
        if self._comment_win.is_open:
            self._comment_win.add_comment(item)

    def _on_conn_status(self, status: str):
        """接続状態変化 → CommentWindowQt のステータスバーに反映"""
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

def main():
    app = QApplication(sys.argv)
    _qt_app = RCommentHubQtApp(app)  # noqa: F841  アプリライフサイクルアンカー
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
