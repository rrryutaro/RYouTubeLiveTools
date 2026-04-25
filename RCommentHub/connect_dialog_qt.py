"""
RCommentHub — Qt版 ConnectDialog（Phase 2）

Tk版 connect_dialog.py の責務を PySide6 QDialog で再実装。
Phase 2 時点では Tk版と並存し、既存ロジック（verify_fn / connect_fn 等）を共用する。

責務（Tk版と同等）:
  プロファイル選択 → プラットフォーム表示 → URL/ID 入力
  → 認証確認 → 確認（verify, 非同期） → 接続開始（connect）
"""

import logging
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont

from constants import PLATFORM_LABELS

_log = logging.getLogger("connect_dialog_qt")

# ─── ダークテーマ定義 ─────────────────────────────────────────────────────────
_DIALOG_STYLE = """
QDialog {
    background: #1A1A2E;
    color: #CCCCCC;
}
QLabel {
    color: #CCCCCC;
    background: transparent;
}
QLineEdit {
    background: #252540;
    color: #FFFFFF;
    border: 1px solid #333355;
    border-radius: 2px;
    padding: 4px 6px;
    selection-background-color: #3A3A7A;
}
QLineEdit:focus {
    border: 1px solid #5555AA;
}
QComboBox {
    background: #252540;
    color: #CCCCCC;
    border: 1px solid #333355;
    border-radius: 2px;
    padding: 3px 6px;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background: #1E1E38;
    color: #CCCCCC;
    border: 1px solid #333355;
    selection-background-color: #3A3A7A;
}
QPushButton {
    background: #252535;
    color: #CCCCCC;
    border: none;
    padding: 5px 14px;
    border-radius: 2px;
}
QPushButton:hover {
    background: #3A3A5A;
}
QPushButton:pressed {
    background: #1A1A3A;
}
QPushButton:disabled {
    background: #1A1A2E;
    color: #555566;
}
"""

_BTN_VERIFY           = "background:#2A4A2A; color:#AAFFAA; padding:5px 16px; border-radius:2px;"
_BTN_CONNECT          = "background:#2A2A4A; color:#AAAAFF; padding:5px 16px; border-radius:2px;"
_BTN_CONNECT_DISABLED = "background:#1A1A2E; color:#555566; padding:5px 16px; border-radius:2px;"


class ConnectDialogQt(QDialog):
    """
    Qt版 接続ダイアログ（Phase 2）。

    Tk版 ConnectDialog と同じコールバック群を受け取る設計。
    既存の controller.verify_target / connect_all_enabled_after を再利用する。

    verify ワーカースレッドからメインスレッドへの通知は Signal/Slot で行う。
    QTimer.singleShot(0, ...) はワーカースレッドから呼ぶと Qt が保証しないため使わない。

    verify_fn:           (platform: str, url: str) -> dict   接続確認（失敗時は例外）
    connect_fn:          (profile_id: str, verify_result: dict) -> None  接続開始
    profiles_getter:     () -> list[dict]                    接続プロファイル一覧
    auth_checker:        () -> bool                          YouTube 認証済みか（OAuth）
    twitch_auth_checker: () -> bool                          Twitch 認証済みか
    url_getter:          () -> str                           初期 URL プリフィル
    url_saver:           (url: str) -> None                  URL 保存
    pos_getter:          () -> list | None                   ウィンドウ位置復元
    pos_setter:          (pos: list) -> None                 ウィンドウ位置保存
    """

    # ワーカースレッドから emit → メインスレッドで slot 実行（自動 QueuedConnection）
    _sig_verify_ok   = Signal(object, str, str)  # result dict, platform, url
    _sig_verify_fail = Signal(str)               # error message

    def __init__(self, parent=None, *,
                 verify_fn,
                 connect_fn,
                 profiles_getter=None,
                 auth_checker=None,
                 twitch_auth_checker=None,
                 url_getter=None,
                 url_saver=None,
                 pos_getter=None,
                 pos_setter=None,
                 log_fn=None):
        super().__init__(parent)
        self._verify_fn           = verify_fn
        self._connect_fn          = connect_fn
        self._profiles_getter     = profiles_getter     or (lambda: [])
        self._auth_checker        = auth_checker        or (lambda: True)
        self._twitch_auth_checker = twitch_auth_checker or (lambda: False)
        self._url_getter          = url_getter          or (lambda: "")
        self._url_saver           = url_saver           or (lambda url: None)
        self._pos_getter          = pos_getter          or (lambda: None)
        self._pos_setter          = pos_setter          or (lambda pos: None)
        # UI ログ表示コールバック（DetailWindowQt のログエリアへ転送）
        self._log_fn              = log_fn              or (lambda msg: None)

        self._verify_result: dict | None = None
        self._profile_map:   dict        = {}   # display_name -> profile dict

        # verify 完了 → メインスレッドへの Signal/Slot 接続
        self._sig_verify_ok.connect(self._on_verify_ok)
        self._sig_verify_fail.connect(self._on_verify_fail)

        # 位置保存デバウンス（moveEvent ごとのディスク書き込みを防ぐ）
        self._pos_save_timer = QTimer(self)
        self._pos_save_timer.setSingleShot(True)
        self._pos_save_timer.setInterval(400)
        self._pos_save_timer.timeout.connect(
            lambda: self._pos_setter([self.x(), self.y()])
        )

        self._build_ui()
        self._load_profiles()
        self._restore_pos()

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("RCommentHub - 接続")
        # v0.3.2 相当: 固定幅・コンパクト高さ・リサイズ不可
        self.setFixedWidth(540)
        self.setSizeGripEnabled(False)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
        # ダークテーマ適用
        self.setStyleSheet(_DIALOG_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # ── タイトルラベル ─────────────────────────────────────────────────────
        title_lbl = QLabel("接続先を入力してください")
        f = QFont()
        f.setBold(True)
        f.setPointSize(10)
        title_lbl.setFont(f)
        title_lbl.setStyleSheet("color: #DDDDEE;")
        root.addWidget(title_lbl)

        # ── プロファイル行 ─────────────────────────────────────────────────────
        prof_row = QHBoxLayout()
        prof_row.setSpacing(8)
        prof_lbl = QLabel("接続プロファイル:")
        prof_lbl.setStyleSheet("color: #AAAACC;")
        prof_row.addWidget(prof_lbl)
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(160)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        prof_row.addWidget(self._profile_combo)
        self._platform_lbl = QLabel("")
        self._platform_lbl.setStyleSheet("color: #88AACC; font-weight: bold;")
        prof_row.addWidget(self._platform_lbl)
        prof_row.addStretch()
        root.addLayout(prof_row)

        # ── URL 入力 ────────────────────────────────────────────────────────────
        self._url_label = QLabel("YouTube URL または 動画ID:")
        self._url_label.setStyleSheet("color: #AAAACC;")
        root.addWidget(self._url_label)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "YouTube URL / 動画ID または Twitch チャンネル名")
        self._url_edit.returnPressed.connect(self._on_verify)
        root.addWidget(self._url_edit)

        # ── 結果ラベル ──────────────────────────────────────────────────────────
        self._result_lbl = QLabel("")
        self._result_lbl.setWordWrap(True)
        self._result_lbl.setMinimumHeight(20)
        root.addWidget(self._result_lbl)

        # ── ボタン行 ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_verify = QPushButton("確認")
        self._btn_verify.setStyleSheet(_BTN_VERIFY)
        self._btn_verify.clicked.connect(self._on_verify)
        btn_row.addWidget(self._btn_verify)

        self._btn_connect = QPushButton("接続開始")
        self._btn_connect.setEnabled(False)
        self._btn_connect.setStyleSheet(_BTN_CONNECT_DISABLED)
        self._btn_connect.clicked.connect(self._on_connect)
        btn_row.addWidget(self._btn_connect)

        btn_cancel = QPushButton("キャンセル")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()
        root.addLayout(btn_row)

    # ─── プロファイル ──────────────────────────────────────────────────────────

    def _load_profiles(self):
        profiles = self._profiles_getter()
        self._profile_map = {
            p.get("display_name", p["profile_id"]): p for p in profiles
        }
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for name in self._profile_map:
            self._profile_combo.addItem(name)
        self._profile_combo.setEnabled(bool(self._profile_map))
        self._profile_combo.blockSignals(False)
        self._on_profile_changed()

    def _on_profile_changed(self):
        self._verify_result = None
        self._result_lbl.setText("")
        self._btn_connect.setEnabled(False)
        self._btn_connect.setStyleSheet(_BTN_CONNECT_DISABLED)

        p        = self._current_profile()
        platform = p.get("platform", "youtube") if p else "youtube"
        self._platform_lbl.setText(f"[{PLATFORM_LABELS.get(platform, platform)}]")

        if platform == "twitch":
            self._url_label.setText("Twitch URL またはチャンネル名:")
        else:
            self._url_label.setText("YouTube URL または 動画ID:")

        if p and p.get("target_url"):
            self._url_edit.setText(p["target_url"])
        else:
            self._url_edit.setText(self._url_getter())

    def _current_profile(self) -> dict | None:
        return self._profile_map.get(self._profile_combo.currentText())

    def _current_platform(self) -> str:
        p = self._current_profile()
        return p.get("platform", "youtube") if p else "youtube"

    # ─── 確認（非同期）────────────────────────────────────────────────────────

    def _on_verify(self):
        text     = self._url_edit.text().strip()
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
                self._set_result(
                    "Google アカウントで認証されていません。設定ウィンドウから認証してください。",
                    "error")
                return

        self._verify_result = None
        self._set_result("確認中...", "info")
        self._btn_verify.setEnabled(False)
        self._btn_connect.setEnabled(False)
        self._btn_connect.setStyleSheet(_BTN_CONNECT_DISABLED)
        self._log_fn(f"[verify 開始] platform={platform} url={text[:60]}")

        def _work():
            _log.info("verify ワーカースレッド開始: platform=%s", platform)
            try:
                result = self._verify_fn(platform, text)
                _log.info("verify 成功: title=%s", result.get("title", result.get("display_name", "")))
                _log.info("verify 完了通知をメインスレッドへポスト")
                self._sig_verify_ok.emit(result, platform, text)
            except Exception as e:
                _log.info("verify 失敗: %s", e)
                _log.info("verify 失敗通知をメインスレッドへポスト")
                self._sig_verify_fail.emit(str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _on_verify_ok(self, result: dict, platform: str, url: str):
        _log.info("verify 成功通知: メインスレッドで UI 反映")
        self._verify_result = result
        title = result.get("title", result.get("display_name", ""))
        self._log_fn(f"[verify 成功] {title}")
        self._set_result(f"✓ 確認OK: {title}", "ok")
        self._btn_verify.setEnabled(True)
        self._btn_connect.setEnabled(True)
        self._btn_connect.setStyleSheet(_BTN_CONNECT)
        if platform == "youtube":
            self._url_saver(url)

    def _on_verify_fail(self, msg: str):
        _log.info("verify 失敗通知: メインスレッドで UI 反映: %s", msg)
        self._log_fn(f"[verify 失敗] {msg}")
        self._verify_result = None
        self._set_result(f"✗ エラー: {msg}", "error")
        self._btn_verify.setEnabled(True)
        self._btn_connect.setEnabled(False)
        self._btn_connect.setStyleSheet(_BTN_CONNECT_DISABLED)

    # ─── 接続開始 ──────────────────────────────────────────────────────────────

    def _on_connect(self):
        if not self._verify_result:
            return
        profile    = self._current_profile()
        profile_id = profile["profile_id"] if profile else "profile_0"
        result     = self._verify_result
        self.accept()
        self._connect_fn(profile_id, result)

    # ─── ユーティリティ ────────────────────────────────────────────────────────

    def _set_result(self, text: str, kind: str = "info"):
        _colors = {
            "info":    "#888899",
            "ok":      "#44CC44",
            "warning": "#FFAA44",
            "error":   "#FF4444",
        }
        self._result_lbl.setText(text)
        self._result_lbl.setStyleSheet(f"color: {_colors.get(kind, '#888899')};")

    def _restore_pos(self):
        pos = self._pos_getter()
        if pos and len(pos) >= 2:
            self.move(int(pos[0]), int(pos[1]))

    def moveEvent(self, event):
        super().moveEvent(event)
        self._pos_save_timer.start()

    def open(self):
        """Tk版 ConnectDialog との API 互換メソッド。既存コーディネーターから呼び出せる。"""
        self._load_profiles()
        if not self._url_edit.text():
            self._url_edit.setText(self._url_getter())
        self._result_lbl.setText("")
        self._verify_result = None
        self._btn_connect.setEnabled(False)
        self._btn_connect.setStyleSheet(_BTN_CONNECT_DISABLED)
        self.show()
        self.raise_()
        self.activateWindow()
