"""
RCommentHub — Qt版 ConnectDialog（Phase 2）

Tk版 connect_dialog.py の責務を PySide6 QDialog で再実装。
Phase 2 時点では Tk版と並存し、既存ロジック（verify_fn / connect_fn 等）を共用する。

責務（Tk版と同等）:
  プロファイル選択 → プラットフォーム表示 → URL/ID 入力
  → 認証確認 → 確認（verify, 非同期） → 接続開始（connect）
"""

import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from constants import PLATFORM_LABELS


class ConnectDialogQt(QDialog):
    """
    Qt版 接続ダイアログ（Phase 2）。

    Tk版 ConnectDialog と同じコールバック群を受け取る設計。
    既存の controller.verify_target / connect_all_enabled_after を再利用する。

    verify_fn:           (platform: str, url: str) -> dict   接続確認（失敗時は例外）
    connect_fn:          (profile_id: str, verify_result: dict) -> None  接続開始
    profiles_getter:     () -> list[dict]                    接続プロファイル一覧
    auth_checker:        () -> bool                          YouTube 認証済みか
    auth_mode_getter:    () -> str                           YouTube 認証モード
    twitch_auth_checker: () -> bool                          Twitch 認証済みか
    url_getter:          () -> str                           初期 URL プリフィル
    url_saver:           (url: str) -> None                  URL 保存
    pos_getter:          () -> list | None                   ウィンドウ位置復元
    pos_setter:          (pos: list) -> None                 ウィンドウ位置保存
    """

    def __init__(self, parent=None, *,
                 verify_fn,
                 connect_fn,
                 profiles_getter=None,
                 auth_checker=None,
                 auth_mode_getter=None,
                 twitch_auth_checker=None,
                 url_getter=None,
                 url_saver=None,
                 pos_getter=None,
                 pos_setter=None):
        super().__init__(parent)
        self._verify_fn           = verify_fn
        self._connect_fn          = connect_fn
        self._profiles_getter     = profiles_getter     or (lambda: [])
        self._auth_checker        = auth_checker        or (lambda: True)
        self._auth_mode_getter    = auth_mode_getter    or (lambda: "api_key")
        self._twitch_auth_checker = twitch_auth_checker or (lambda: False)
        self._url_getter          = url_getter          or (lambda: "")
        self._url_saver           = url_saver           or (lambda url: None)
        self._pos_getter          = pos_getter          or (lambda: None)
        self._pos_setter          = pos_setter          or (lambda pos: None)

        self._verify_result: dict | None = None
        self._profile_map:   dict        = {}   # display_name -> profile dict

        self._build_ui()
        self._load_profiles()
        self._restore_pos()

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("配信に接続")
        self.setMinimumWidth(520)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # タイトル
        title_lbl = QLabel("接続先を入力してください")
        f = QFont()
        f.setBold(True)
        f.setPointSize(10)
        title_lbl.setFont(f)
        root.addWidget(title_lbl)

        # プロファイル行
        prof_row = QHBoxLayout()
        prof_row.setSpacing(8)
        prof_row.addWidget(QLabel("接続プロファイル:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(160)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        prof_row.addWidget(self._profile_combo)
        self._platform_lbl = QLabel("")
        prof_row.addWidget(self._platform_lbl)
        prof_row.addStretch()
        root.addLayout(prof_row)

        # URL 入力
        self._url_label = QLabel("URL / ID:")
        root.addWidget(self._url_label)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("YouTube URL / 動画ID または Twitch チャンネル名")
        self._url_edit.returnPressed.connect(self._on_verify)
        root.addWidget(self._url_edit)

        # 結果ラベル
        self._result_lbl = QLabel("")
        self._result_lbl.setWordWrap(True)
        root.addWidget(self._result_lbl)

        # ボタン行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_verify = QPushButton("確認")
        self._btn_verify.clicked.connect(self._on_verify)
        btn_row.addWidget(self._btn_verify)

        self._btn_connect = QPushButton("接続開始")
        self._btn_connect.setEnabled(False)
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
                mode = self._auth_mode_getter()
                msg = (
                    "Google アカウントで認証されていません。設定ウィンドウから認証してください。"
                    if mode == "oauth" else
                    "API キーが未設定です（補助モード）。設定ウィンドウから登録してください。"
                )
                self._set_result(msg, "error")
                return

        self._verify_result = None
        self._set_result("確認中...", "info")
        self._btn_verify.setEnabled(False)
        self._btn_connect.setEnabled(False)

        def _work():
            try:
                result = self._verify_fn(platform, text)
                QTimer.singleShot(0, lambda r=result, u=text: self._on_verify_ok(r, platform, u))
            except Exception as e:
                QTimer.singleShot(0, lambda msg=str(e): self._on_verify_fail(msg))

        threading.Thread(target=_work, daemon=True).start()

    def _on_verify_ok(self, result: dict, platform: str, url: str):
        self._verify_result = result
        title = result.get("title", result.get("display_name", ""))
        self._set_result(f"✓ 確認OK: {title}", "ok")
        self._btn_verify.setEnabled(True)
        self._btn_connect.setEnabled(True)
        if platform == "youtube":
            self._url_saver(url)

    def _on_verify_fail(self, msg: str):
        self._verify_result = None
        self._set_result(f"✗ エラー: {msg}", "error")
        self._btn_verify.setEnabled(True)
        self._btn_connect.setEnabled(False)

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
            "info":    "#AAAAAA",
            "ok":      "#44CC44",
            "warning": "#FFAA44",
            "error":   "#FF4444",
        }
        self._result_lbl.setText(text)
        self._result_lbl.setStyleSheet(f"color: {_colors.get(kind, '#AAAAAA')};")

    def _restore_pos(self):
        pos = self._pos_getter()
        if pos and len(pos) >= 2:
            self.move(int(pos[0]), int(pos[1]))

    def moveEvent(self, event):
        super().moveEvent(event)
        self._pos_setter([self.x(), self.y()])

    def open(self):
        """Tk版 ConnectDialog との API 互換メソッド。既存コーディネーターから呼び出せる。"""
        self._load_profiles()
        if not self._url_edit.text():
            self._url_edit.setText(self._url_getter())
        self._result_lbl.setText("")
        self._verify_result = None
        self._btn_connect.setEnabled(False)
        self.show()
        self.raise_()
        self.activateWindow()
