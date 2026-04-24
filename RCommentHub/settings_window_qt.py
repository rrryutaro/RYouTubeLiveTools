"""
RCommentHub — Qt版 SettingsWindow（Phase 4）

Tk版 settings_window.py の責務を PySide6 QDialog で再実装。
Phase 4 時点では 4 タブ（API / 接続設定 / 表示設定 / 読み上げ）の最小骨格。

責務（Tk版と同等）:
  API キー・OAuth 認証 / Twitch 認証 → API タブ
  接続プロファイル管理 / YouTube オプション → 接続設定タブ
  表示設定（監視用・Overlay）→ 表示設定タブ
  読み上げ設定 → 読み上げタブ

Phase 4 で未対応にしたもの（Phase 5 以降）:
  プロファイル編集サブダイアログの完全再現
  Overlay 配置確認モードボタン
  監視用↔配信用コピーボタン（表示設定タブ）
"""

import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox,
    QTabWidget, QWidget, QListWidget, QListWidgetItem,
    QComboBox, QSpinBox, QDoubleSpinBox, QScrollArea,
    QSizePolicy, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from constants import PLATFORM_LABELS, COLOR_THEMES, VERSION


class SettingsWindowQt(QDialog):
    """
    Qt版 設定ウィンドウ（Phase 4）。

    Tk版 SettingsWindow と同じコールバック群を受け取る設計。
    既存の SettingsManager / AuthService / TwitchAuthService を再利用する。

    on_settings_changed: () -> None           設定保存後コールバック
    auth_service_getter: () -> AuthService    YouTube 認証サービス
    twitch_auth_getter:  () -> TwitchAuth     Twitch 認証サービス
    pos_getter:          () -> list|None      位置復元
    pos_setter:          (list) -> None       位置保存
    """

    def __init__(self, parent=None, *,
                 settings_mgr,
                 on_settings_changed=None,
                 auth_service_getter=None,
                 twitch_auth_getter=None,
                 pos_getter=None,
                 pos_setter=None):
        super().__init__(parent)
        self._sm                  = settings_mgr
        self._on_changed          = on_settings_changed
        self._auth_service_getter = auth_service_getter or (lambda: None)
        self._twitch_auth_getter  = twitch_auth_getter  or (lambda: None)
        self._pos_getter          = pos_getter or (lambda: None)
        self._pos_setter          = pos_setter or (lambda pos: None)

        # OAuth 試行 ID（古い試行の完了通知を無視する）
        self._oauth_attempt_id        = 0
        self._twitch_oauth_attempt_id = 0

        # 接続プロファイル編集データ
        self._profile_edit_data: list = []

        self.setWindowTitle("RCommentHub - 設定")
        self.setMinimumSize(640, 580)
        self.resize(680, 660)

        # 位置保存デバウンス（moveEvent ごとのディスク書き込みを防ぐ）
        self._pos_save_timer = QTimer(self)
        self._pos_save_timer.setSingleShot(True)
        self._pos_save_timer.setInterval(400)
        self._pos_save_timer.timeout.connect(
            lambda: self._pos_setter([self.x(), self.y()])
        )

        self._build_ui()
        self._load_values()
        self._restore_pos()

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── ダークテーマ（v0.3.2 相当の落ち着いた印象へ） ────────────────────
        self.setStyleSheet("""
            QDialog {
                background: #1A1A2E;
                color: #CCCCCC;
            }
            QWidget {
                background: #1A1A2E;
                color: #CCCCCC;
            }
            QTabWidget::pane {
                border: 1px solid #333355;
                background: #1A1A2E;
            }
            QTabBar::tab {
                background: #14141E;
                color: #888899;
                padding: 5px 14px;
                border: 1px solid #222233;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #1A1A2E;
                color: #CCCCDD;
                border-top: 2px solid #5555AA;
            }
            QTabBar::tab:hover:!selected {
                background: #1E1E30;
                color: #AAAACC;
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
                padding: 3px 5px;
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
                padding: 2px 5px;
            }
            QComboBox QAbstractItemView {
                background: #1E1E38;
                color: #CCCCCC;
                border: 1px solid #333355;
                selection-background-color: #3A3A7A;
            }
            QCheckBox {
                color: #CCCCCC;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
                border: 1px solid #555577;
                background: #252535;
            }
            QCheckBox::indicator:checked {
                background: #4444AA;
                border: 1px solid #6666CC;
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
            QListWidget {
                background: #14141E;
                color: #CCCCCC;
                border: 1px solid #333355;
                selection-background-color: #2A2A5A;
            }
            QSpinBox, QDoubleSpinBox {
                background: #252540;
                color: #FFFFFF;
                border: 1px solid #333355;
                border-radius: 2px;
                padding: 2px 4px;
            }
            QScrollArea {
                background: #1A1A2E;
                border: none;
            }
            QScrollBar:vertical {
                background: #14141E;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: #333355;
                min-height: 20px;
            }
            QFrame[frameShape="4"] {
                color: #2A2A4A;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # タブウィジェット
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        tab_api     = QWidget()
        tab_conn    = QWidget()
        tab_display = QWidget()
        tab_tts     = QWidget()

        self._tabs.addTab(tab_api,     "API")
        self._tabs.addTab(tab_conn,    "接続設定")
        self._tabs.addTab(tab_display, "表示設定")
        self._tabs.addTab(tab_tts,     "読み上げ")

        self._build_api_tab(tab_api)
        self._build_conn_tab(tab_conn)
        self._build_display_tab(tab_display)
        self._build_tts_tab(tab_tts)

        # ボタン行
        btn_row = QHBoxLayout()
        ver_lbl = QLabel(f"RCommentHub v{VERSION}")
        ver_lbl.setStyleSheet("color: #555577; font-size: 8pt;")
        btn_row.addWidget(ver_lbl)
        btn_row.addStretch()

        btn_cancel = QPushButton("キャンセル")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_apply = QPushButton("適用")
        btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(btn_apply)

        btn_save = QPushButton("保存して閉じる")
        btn_save.setDefault(True)
        btn_save.setStyleSheet(
            "background:#2A2A4A; color:#AAAAFF; padding:5px 16px; border-radius:2px;"
            "QPushButton:hover { background:#3A3A6A; }"
        )
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)

        root.addLayout(btn_row)

    # ─── API タブ ──────────────────────────────────────────────────────────────

    def _build_api_tab(self, parent):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        outer = QVBoxLayout(parent)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # ── OAuth 2.0 認証 ────────────────────────────────────────────────────
        self._section(layout, "OAuth 2.0 認証")

        auth_svc = self._auth_service_getter()
        status_text = auth_svc.status_label() if auth_svc else "（認証サービス未接続）"
        self._oauth_status_lbl = QLabel(status_text)
        self._oauth_status_lbl.setStyleSheet("color: #88DDAA;")
        layout.addWidget(self._oauth_status_lbl)

        oauth_btns = QHBoxLayout()
        self._oauth_btn = QPushButton("Googleアカウントで認証する")
        self._oauth_btn.setStyleSheet(
            "background:#2A4A2A; color:#AAFFAA; padding:4px 12px;")
        self._oauth_btn.clicked.connect(self._on_oauth_authenticate)
        oauth_btns.addWidget(self._oauth_btn)

        self._oauth_revoke_btn = QPushButton("認証を解除")
        self._oauth_revoke_btn.clicked.connect(self._on_oauth_revoke)
        oauth_btns.addWidget(self._oauth_revoke_btn)

        self._oauth_cancel_btn = QPushButton("認証をキャンセル")
        self._oauth_cancel_btn.setEnabled(False)
        self._oauth_cancel_btn.setStyleSheet("color:#FFAA66;")
        self._oauth_cancel_btn.clicked.connect(self._on_oauth_cancel)
        oauth_btns.addWidget(self._oauth_cancel_btn)

        oauth_btns.addStretch()
        layout.addLayout(oauth_btns)

        # client_secrets.json 状態
        if auth_svc and auth_svc.has_client_config():
            secrets_text  = "client_secrets.json: ロード済み"
            secrets_color = "#88DDAA"
        else:
            secrets_text  = "client_secrets.json: 未ロード（OAuth 認証ボタンは使用不可）"
            secrets_color = "#FFAA44"
        self._secrets_lbl = QLabel(secrets_text)
        self._secrets_lbl.setStyleSheet(f"color: {secrets_color}; font-size: 8pt;")
        layout.addWidget(self._secrets_lbl)

        note_oauth = QLabel(
            "※ 認証情報はこの PC 内にのみ保存されます。開発者サーバーへは送信しません。\n"
            "※ OAuth 認証には client_secrets.json をアプリと同フォルダに配置してください。"
        )
        note_oauth.setStyleSheet("color: #888888; font-size: 8pt;")
        note_oauth.setWordWrap(True)
        layout.addWidget(note_oauth)

        # ── Twitch 認証 ───────────────────────────────────────────────────────
        self._section(layout, "Twitch 認証")

        layout.addWidget(QLabel("Twitch クライアントID:"))
        self._twitch_id_edit = QLineEdit()
        self._twitch_id_edit.setPlaceholderText("Twitch クライアントIDを入力")
        layout.addWidget(self._twitch_id_edit)

        tw_auth = self._twitch_auth_getter()
        tw_status = tw_auth.status_label() if tw_auth else "（Twitch 認証サービス未接続）"
        self._twitch_status_lbl = QLabel(tw_status)
        self._twitch_status_lbl.setStyleSheet("color: #FFAA66;")
        layout.addWidget(self._twitch_status_lbl)

        tw_btns = QHBoxLayout()
        self._twitch_auth_btn = QPushButton("Twitch アカウントで認証する")
        self._twitch_auth_btn.setStyleSheet(
            "background:#2A2A4A; color:#AAAAFF; padding:4px 12px;")
        self._twitch_auth_btn.clicked.connect(self._on_twitch_authenticate)
        tw_btns.addWidget(self._twitch_auth_btn)

        self._twitch_revoke_btn = QPushButton("認証を解除")
        self._twitch_revoke_btn.clicked.connect(self._on_twitch_revoke)
        tw_btns.addWidget(self._twitch_revoke_btn)

        tw_btns.addStretch()
        layout.addLayout(tw_btns)

        note_tw = QLabel(
            "※ Twitch 開発者ポータル (dev.twitch.tv) でアプリ登録し、クライアントIDを取得してください。\n"
            "※ 認証は Device Code Grant Flow を使用します（redirect URI 登録不要）。\n"
            "※ トークンはこの PC 内にのみ保存されます（DPAPI 暗号化）。"
        )
        note_tw.setStyleSheet("color: #888888; font-size: 8pt;")
        note_tw.setWordWrap(True)
        layout.addWidget(note_tw)

        layout.addStretch()

    # ─── 接続設定タブ ──────────────────────────────────────────────────────────

    def _build_conn_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # ── YouTube 接続オプション ─────────────────────────────────────────────
        self._section(layout, "YouTube 接続オプション")

        self._yt_notify_overlay_chk = QCheckBox(
            "YouTube 切断通知を配信用 Overlay にも表示する（デフォルト OFF）")
        layout.addWidget(self._yt_notify_overlay_chk)

        note_yt = QLabel(
            "※ 切断通知はアプリ内コメントリスト・ログへは常に表示されます。\n"
            "※ Overlay への表示はデフォルト OFF です。"
        )
        note_yt.setStyleSheet("color: #888888; font-size: 8pt;")
        note_yt.setWordWrap(True)
        layout.addWidget(note_yt)

        # ── 接続プロファイル ───────────────────────────────────────────────────
        self._section(layout, "接続プロファイル")

        layout.addWidget(QLabel(
            "接続先を「プロファイル」として複数登録できます。\n"
            "有効なプロファイルは接続開始時に自動接続されます（2件目以降）。"
        ))

        self._profile_listbox = QListWidget()
        self._profile_listbox.setFixedHeight(160)
        self._profile_listbox.itemDoubleClicked.connect(lambda: self._on_profile_edit())
        layout.addWidget(self._profile_listbox)

        prof_btns = QHBoxLayout()
        btn_add = QPushButton("追加")
        btn_add.setStyleSheet("background:#2A4A2A; color:#AAFFAA; padding:3px 10px;")
        btn_add.clicked.connect(self._on_profile_add)
        prof_btns.addWidget(btn_add)

        btn_edit = QPushButton("編集")
        btn_edit.clicked.connect(self._on_profile_edit)
        prof_btns.addWidget(btn_edit)

        btn_del = QPushButton("削除")
        btn_del.setStyleSheet("background:#4A2A2A; color:#FFAAAA; padding:3px 10px;")
        btn_del.clicked.connect(self._on_profile_delete)
        prof_btns.addWidget(btn_del)

        prof_btns.addStretch()
        layout.addLayout(prof_btns)

        layout.addWidget(QLabel(
            "※ 接続ダイアログからも接続できます。\n"
            "※ 2件目以降の有効プロファイルは自動接続されます。"
        ))

        layout.addStretch()

    # ─── 表示設定タブ ──────────────────────────────────────────────────────────

    def _build_display_tab(self, parent):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        outer = QVBoxLayout(parent)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # ── 全体設定 ──────────────────────────────────────────────────────────
        self._section(layout, "全体設定")

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("カラーテーマ:"))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(list(COLOR_THEMES.keys()))
        self._theme_combo.setMinimumWidth(180)
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        self._overlay_enabled_chk = QCheckBox("配信用 Overlay を有効にする")
        layout.addWidget(self._overlay_enabled_chk)

        # ── ウィンドウ設定（監視用） ────────────────────────────────────────
        self._section(layout, "ウィンドウ設定（監視用）")

        self._cw_topmost_chk = QCheckBox("最前面表示")
        layout.addWidget(self._cw_topmost_chk)

        self._cw_transparent_chk = QCheckBox("透過モード")
        layout.addWidget(self._cw_transparent_chk)

        alpha_row = QHBoxLayout()
        alpha_row.addWidget(QLabel("透過率:"))
        self._cw_alpha_spin = QSpinBox()
        self._cw_alpha_spin.setRange(10, 100)
        self._cw_alpha_spin.setSingleStep(5)
        self._cw_alpha_spin.setSuffix(" %")
        alpha_row.addWidget(self._cw_alpha_spin)
        alpha_row.addStretch()
        layout.addLayout(alpha_row)

        rows_row = QHBoxLayout()
        rows_row.addWidget(QLabel("表示行数:"))
        self._display_rows_combo = QComboBox()
        self._display_rows_combo.addItems(["1", "2"])
        rows_row.addWidget(self._display_rows_combo)
        rows_row.addStretch()
        layout.addLayout(rows_row)

        # ── 表示要素（監視用） ────────────────────────────────────────────────
        self._section(layout, "表示要素（監視用）")

        self._icon_chk      = QCheckBox("アイコン表示")
        self._show_src_chk  = QCheckBox("接続先名表示")
        self._time_chk      = QCheckBox("時刻表示")
        for w in (self._icon_chk, self._show_src_chk, self._time_chk):
            layout.addWidget(w)

        time_mode_row = QHBoxLayout()
        time_mode_row.addWidget(QLabel("時刻方式:"))
        self._time_mode_combo = QComboBox()
        self._time_mode_combo.addItems(["実時間", "経過時間"])
        time_mode_row.addWidget(self._time_mode_combo)
        time_mode_row.addStretch()
        layout.addLayout(time_mode_row)

        # ── 文字サイズ ────────────────────────────────────────────────────────
        self._section(layout, "文字サイズ（監視用）")

        fn_row = QHBoxLayout()
        fn_row.addWidget(QLabel("投稿者名フォントサイズ:"))
        self._font_name_spin = QSpinBox()
        self._font_name_spin.setRange(7, 72)
        fn_row.addWidget(self._font_name_spin)
        fn_row.addStretch()
        layout.addLayout(fn_row)

        fb_row = QHBoxLayout()
        fb_row.addWidget(QLabel("本文フォントサイズ:"))
        self._font_body_spin = QSpinBox()
        self._font_body_spin.setRange(7, 72)
        fb_row.addWidget(self._font_body_spin)
        fb_row.addStretch()
        layout.addLayout(fb_row)

        # ── 配信用 Overlay 設定 ────────────────────────────────────────────────
        self._section(layout, "配信用 Overlay 設定")

        self._ov_topmost_chk     = QCheckBox("Overlay 最前面表示")
        self._ov_transparent_chk = QCheckBox("Overlay 透過モード")
        self._ov_show_icon_chk   = QCheckBox("Overlay アイコン表示")
        self._ov_show_src_chk    = QCheckBox("Overlay 接続先名表示")
        for w in (self._ov_topmost_chk, self._ov_transparent_chk,
                  self._ov_show_icon_chk, self._ov_show_src_chk):
            layout.addWidget(w)

        ov_mode_row = QHBoxLayout()
        ov_mode_row.addWidget(QLabel("表示モード:"))
        self._ov_mode_combo = QComboBox()
        self._ov_mode_combo.addItems(["timed", "always"])
        ov_mode_row.addWidget(self._ov_mode_combo)
        ov_mode_row.addStretch()
        layout.addLayout(ov_mode_row)

        ov_dur_row = QHBoxLayout()
        ov_dur_row.addWidget(QLabel("表示秒数 (timed):"))
        self._ov_duration_spin = QSpinBox()
        self._ov_duration_spin.setRange(1, 120)
        self._ov_duration_spin.setSuffix(" 秒")
        ov_dur_row.addWidget(self._ov_duration_spin)
        ov_dur_row.addStretch()
        layout.addLayout(ov_dur_row)

        ov_fn_row = QHBoxLayout()
        ov_fn_row.addWidget(QLabel("Overlay 投稿者名フォントサイズ:"))
        self._ov_fn_spin = QSpinBox()
        self._ov_fn_spin.setRange(7, 72)
        ov_fn_row.addWidget(self._ov_fn_spin)
        ov_fn_row.addStretch()
        layout.addLayout(ov_fn_row)

        ov_fb_row = QHBoxLayout()
        ov_fb_row.addWidget(QLabel("Overlay 本文フォントサイズ:"))
        self._ov_fb_spin = QSpinBox()
        self._ov_fb_spin.setRange(7, 72)
        ov_fb_row.addWidget(self._ov_fb_spin)
        ov_fb_row.addStretch()
        layout.addLayout(ov_fb_row)

        layout.addStretch()

    # ─── 読み上げタブ ──────────────────────────────────────────────────────────

    def _build_tts_tab(self, parent):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        outer = QVBoxLayout(parent)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # ── 読み上げ全般 ───────────────────────────────────────────────────────
        self._section(layout, "読み上げ全般")

        self._tts_enabled_chk = QCheckBox("読み上げを有効にする")
        layout.addWidget(self._tts_enabled_chk)

        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("音量:"))
        self._tts_volume_spin = QSpinBox()
        self._tts_volume_spin.setRange(0, 100)
        self._tts_volume_spin.setSuffix(" %")
        vol_row.addWidget(self._tts_volume_spin)
        vol_row.addStretch()
        layout.addLayout(vol_row)

        # ── 読み上げるコメント種別 ─────────────────────────────────────────────
        self._section(layout, "読み上げるコメント種別")

        self._tts_normal_chk = QCheckBox("通常コメント")
        self._tts_sc_chk     = QCheckBox("Super Chat / Super Sticker")
        for w in (self._tts_normal_chk, self._tts_sc_chk):
            layout.addWidget(w)

        # ── 読み上げる投稿者属性 ───────────────────────────────────────────────
        self._section(layout, "読み上げる投稿者属性")

        self._tts_owner_chk  = QCheckBox("配信者 (Owner) のコメント")
        self._tts_mod_chk    = QCheckBox("Mod のコメント")
        self._tts_member_chk = QCheckBox("Member のコメント")
        for w in (self._tts_owner_chk, self._tts_mod_chk, self._tts_member_chk):
            layout.addWidget(w)

        # ── オプション ────────────────────────────────────────────────────────
        self._section(layout, "オプション")

        self._tts_simplify_chk   = QCheckBox(
            "投稿者名を簡略化して読み上げる（英数字のみの名前を省略）")
        self._tts_read_src_chk   = QCheckBox(
            "接続先名を先頭で読み上げる（マルチ接続時の識別用）")
        for w in (self._tts_simplify_chk, self._tts_read_src_chk):
            layout.addWidget(w)

        # ── 読み上げ速度・間隔 ─────────────────────────────────────────────────
        self._section(layout, "読み上げ速度・間隔")

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("読み上げ速度 (SAPI Rate, -10〜10):"))
        self._tts_speed_spin = QSpinBox()
        self._tts_speed_spin.setRange(-10, 10)
        speed_row.addWidget(self._tts_speed_spin)
        speed_row.addWidget(QLabel("(0=標準  正=速い  負=遅い)"))
        speed_row.addStretch()
        layout.addLayout(speed_row)

        intv_row = QHBoxLayout()
        intv_row.addWidget(QLabel("コメント間インターバル:"))
        self._tts_interval_spin = QDoubleSpinBox()
        self._tts_interval_spin.setRange(0.0, 10.0)
        self._tts_interval_spin.setSingleStep(0.5)
        self._tts_interval_spin.setDecimals(1)
        self._tts_interval_spin.setSuffix(" 秒")
        intv_row.addWidget(self._tts_interval_spin)
        intv_row.addStretch()
        layout.addLayout(intv_row)

        layout.addStretch()

    # ─── 公開 API ──────────────────────────────────────────────────────────────

    def open(self):
        """Tk版 SettingsWindow との API 互換メソッド。"""
        self._load_values()
        self.show()
        self.raise_()
        self.activateWindow()

    # ─── 設定値 ロード ─────────────────────────────────────────────────────────

    def _load_values(self):
        """settings_mgr から設定値を読み込んで UI に反映する。"""
        sm = self._sm

        # Twitch クライアントID
        self._twitch_id_edit.setText(sm.get("twitch_client_id", ""))

        # OAuth 状態
        auth_svc = self._auth_service_getter()
        if auth_svc and hasattr(self, "_oauth_status_lbl"):
            self._oauth_status_lbl.setText(auth_svc.status_label())
            if auth_svc.has_client_config():
                self._secrets_lbl.setText("client_secrets.json: ロード済み")
                self._secrets_lbl.setStyleSheet("color: #88DDAA; font-size: 8pt;")
            else:
                self._secrets_lbl.setText("client_secrets.json: 未ロード（OAuth 認証ボタンは使用不可）")
                self._secrets_lbl.setStyleSheet("color: #FFAA44; font-size: 8pt;")

        # Twitch 状態
        tw_auth = self._twitch_auth_getter()
        if tw_auth and hasattr(self, "_twitch_status_lbl"):
            self._twitch_status_lbl.setText(tw_auth.status_label())

        # YouTube 接続オプション
        self._yt_notify_overlay_chk.setChecked(
            sm.get("youtube_disconnect_notify_overlay", False))

        # 接続プロファイル
        self._refresh_profile_list()

        # 表示設定
        theme = sm.get("color_theme", "ダーク (デフォルト)")
        idx = self._theme_combo.findText(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        self._overlay_enabled_chk.setChecked(sm.get("overlay_enabled", False))
        self._cw_topmost_chk.setChecked(sm.get("cw_topmost", False))
        self._cw_transparent_chk.setChecked(sm.get("cw_transparent", False))
        self._cw_alpha_spin.setValue(int(sm.get("cw_comment_alpha", 100)))

        rows_val = str(sm.get("display_rows", 1))
        ridx = self._display_rows_combo.findText(rows_val)
        if ridx >= 0:
            self._display_rows_combo.setCurrentIndex(ridx)

        self._icon_chk.setChecked(sm.get("icon_visible", True))
        self._show_src_chk.setChecked(sm.get("cw_show_source", False))
        self._time_chk.setChecked(sm.get("time_visible", True))

        time_mode = sm.get("time_mode", "実時間")
        tidx = self._time_mode_combo.findText(time_mode)
        if tidx >= 0:
            self._time_mode_combo.setCurrentIndex(tidx)

        self._font_name_spin.setValue(int(sm.get("font_size_name", 9)))
        self._font_body_spin.setValue(int(sm.get("font_size_body", 9)))

        self._ov_topmost_chk.setChecked(sm.get("overlay_topmost", True))
        self._ov_transparent_chk.setChecked(sm.get("overlay_transparent", False))
        self._ov_show_icon_chk.setChecked(sm.get("overlay_show_icon", True))
        self._ov_show_src_chk.setChecked(sm.get("overlay_show_source", False))

        ov_mode = sm.get("overlay_display_mode", "timed")
        oidx = self._ov_mode_combo.findText(ov_mode)
        if oidx >= 0:
            self._ov_mode_combo.setCurrentIndex(oidx)

        self._ov_duration_spin.setValue(
            int(sm.get("overlay_duration_sec", sm.get("overlay_duration", 5))))
        self._ov_fn_spin.setValue(int(sm.get("overlay_font_size_name", 9)))
        self._ov_fb_spin.setValue(int(sm.get("overlay_font_size_body", 11)))

        # 読み上げ
        self._tts_enabled_chk.setChecked(sm.get("tts_enabled", False))
        self._tts_volume_spin.setValue(int(sm.get("tts_volume", 100)))
        self._tts_normal_chk.setChecked(sm.get("tts_normal", True))
        self._tts_sc_chk.setChecked(sm.get("tts_superchat", True))
        self._tts_owner_chk.setChecked(sm.get("tts_owner", True))
        self._tts_mod_chk.setChecked(sm.get("tts_mod", True))
        self._tts_member_chk.setChecked(sm.get("tts_member", False))
        self._tts_simplify_chk.setChecked(sm.get("tts_simplify_name", True))
        self._tts_read_src_chk.setChecked(sm.get("tts_read_source_name", False))
        self._tts_speed_spin.setValue(int(sm.get("tts_speed", 0)))
        self._tts_interval_spin.setValue(float(sm.get("tts_interval_sec", 0.0)))

    # ─── 設定値 保存 ───────────────────────────────────────────────────────────

    def _apply_settings(self) -> bool:
        """設定を保存してコールバックを呼ぶ。成功時 True。"""
        sm = self._sm

        # Twitch クライアントID
        twitch_id = self._twitch_id_edit.text().strip()
        tw_auth = self._twitch_auth_getter()
        if tw_auth is not None and twitch_id != tw_auth.client_id:
            tw_auth.client_id = twitch_id

        updates = {
            # YouTube 接続オプション
            "youtube_disconnect_notify_overlay": self._yt_notify_overlay_chk.isChecked(),
            # 表示設定
            "color_theme":        self._theme_combo.currentText(),
            "overlay_enabled":    self._overlay_enabled_chk.isChecked(),
            "cw_topmost":         self._cw_topmost_chk.isChecked(),
            "cw_transparent":     self._cw_transparent_chk.isChecked(),
            "cw_comment_alpha":   self._cw_alpha_spin.value(),
            "display_rows":       int(self._display_rows_combo.currentText()),
            "icon_visible":       self._icon_chk.isChecked(),
            "cw_show_source":     self._show_src_chk.isChecked(),
            "time_visible":       self._time_chk.isChecked(),
            "time_mode":          self._time_mode_combo.currentText(),
            "font_size_name":     self._font_name_spin.value(),
            "font_size_body":     self._font_body_spin.value(),
            # Overlay
            "overlay_topmost":        self._ov_topmost_chk.isChecked(),
            "overlay_transparent":    self._ov_transparent_chk.isChecked(),
            "overlay_show_icon":      self._ov_show_icon_chk.isChecked(),
            "overlay_show_source":    self._ov_show_src_chk.isChecked(),
            "overlay_display_mode":   self._ov_mode_combo.currentText(),
            "overlay_duration_sec":   self._ov_duration_spin.value(),
            "overlay_font_size_name": self._ov_fn_spin.value(),
            "overlay_font_size_body": self._ov_fb_spin.value(),
            # 読み上げ
            "tts_enabled":          self._tts_enabled_chk.isChecked(),
            "tts_volume":           self._tts_volume_spin.value(),
            "tts_normal":           self._tts_normal_chk.isChecked(),
            "tts_superchat":        self._tts_sc_chk.isChecked(),
            "tts_owner":            self._tts_owner_chk.isChecked(),
            "tts_mod":              self._tts_mod_chk.isChecked(),
            "tts_member":           self._tts_member_chk.isChecked(),
            "tts_simplify_name":    self._tts_simplify_chk.isChecked(),
            "tts_read_source_name": self._tts_read_src_chk.isChecked(),
            "tts_speed":            self._tts_speed_spin.value(),
            "tts_interval_sec":     self._tts_interval_spin.value(),
        }
        sm.update(updates)

        if self._on_changed:
            self._on_changed()
        return True

    def _on_apply(self):
        self._apply_settings()

    def _on_save(self):
        if self._apply_settings():
            self.accept()

    # ─── OAuth ハンドラ ────────────────────────────────────────────────────────

    def _on_oauth_authenticate(self):
        auth_svc = self._auth_service_getter()
        if auth_svc is None:
            QMessageBox.critical(self, "エラー", "認証サービスが初期化されていません。")
            return
        if not auth_svc.has_client_config():
            QMessageBox.information(
                self, "client_secrets.json が必要",
                "OAuth 認証にはクライアント設定ファイル (client_secrets.json) が必要です。\n"
                "アプリと同じフォルダに配置してから再試行してください。"
            )
            return

        self._oauth_attempt_id += 1
        attempt_id = self._oauth_attempt_id

        self._oauth_status_lbl.setText("認証中... ブラウザを確認してください")
        self._set_oauth_buttons(authenticating=True)

        def _do_flow():
            try:
                success = auth_svc.run_oauth_flow()
            except Exception:
                success = False
            QTimer.singleShot(
                0, lambda: self._on_oauth_done(attempt_id, success, auth_svc))

        threading.Thread(target=_do_flow, daemon=True).start()

    def _on_oauth_done(self, attempt_id: int, success: bool, auth_svc):
        if attempt_id != self._oauth_attempt_id:
            return
        self._set_oauth_buttons(authenticating=False)
        try:
            self._oauth_status_lbl.setText(auth_svc.status_label())
            # ラベル更新を即時描画に反映させる（ブラウザ操作後に描画キューが溜まっている場合の対策）
            self._oauth_status_lbl.repaint()
        except Exception:
            pass
        # ブラウザ操作後にウィンドウを前面に出してから完了ダイアログを表示する
        self.raise_()
        self.activateWindow()
        if success:
            QMessageBox.information(self, "認証完了", "Google アカウントでの認証が完了しました。")
        else:
            QMessageBox.critical(
                self, "認証失敗",
                "認証に失敗しました（キャンセルまたはエラー）。\n"
                "client_secrets.json を確認してから再試行してください。"
            )

    def _on_oauth_cancel(self):
        self._oauth_attempt_id += 1
        self._set_oauth_buttons(authenticating=False)
        self._oauth_status_lbl.setText("認証キャンセル済み — 再度ボタンを押して再試行できます")

    def _set_oauth_buttons(self, authenticating: bool):
        self._oauth_btn.setEnabled(not authenticating)
        self._oauth_revoke_btn.setEnabled(not authenticating)
        self._oauth_cancel_btn.setEnabled(authenticating)

    def _on_oauth_revoke(self):
        auth_svc = self._auth_service_getter()
        if auth_svc is None:
            return
        reply = QMessageBox.question(
            self, "確認",
            "認証を解除してよいですか？\n次回接続時に再認証が必要になります。"
        )
        if reply == QMessageBox.StandardButton.Yes:
            auth_svc.revoke()
            self._oauth_status_lbl.setText(auth_svc.status_label())

    # ─── Twitch 認証ハンドラ ───────────────────────────────────────────────────

    def _on_twitch_authenticate(self):
        tw_auth = self._twitch_auth_getter()
        if tw_auth is None:
            QMessageBox.critical(self, "エラー", "Twitch 認証サービスが初期化されていません。")
            return

        client_id = self._twitch_id_edit.text().strip()
        if not client_id:
            QMessageBox.critical(self, "エラー", "Twitch クライアントIDを入力してください。")
            return
        tw_auth.client_id = client_id

        self._twitch_oauth_attempt_id += 1
        attempt_id = self._twitch_oauth_attempt_id

        import threading as _threading
        stop_event = _threading.Event()
        self._twitch_stop_event = stop_event

        self._twitch_status_lbl.setText("デバイスコードを取得中...")
        self._twitch_auth_btn.setEnabled(False)
        self._twitch_revoke_btn.setEnabled(False)

        def _on_status(msg):
            QTimer.singleShot(0, lambda m=msg: self._twitch_status_lbl.setText(m))

        def _on_device_code(user_code, verify_url):
            def _show():
                QMessageBox.information(
                    self,
                    "Twitch 認証 — コードを入力してください",
                    f"ブラウザが開きます。以下のコードを入力して承認してください。\n\n"
                    f"  認証コード : {user_code}\n"
                    f"  認証 URL   : {verify_url}\n\n"
                    f"ブラウザが自動で開かない場合は上記 URL をコピーして開いてください。"
                )
            QTimer.singleShot(0, _show)

        def _do_flow():
            try:
                tw_auth.run_device_code_flow(
                    on_status=_on_status,
                    on_device_code=_on_device_code,
                    stop_event=stop_event,
                )
                success, err_msg = True, ""
            except Exception as e:
                success, err_msg = False, str(e)
            QTimer.singleShot(
                0, lambda: self._on_twitch_auth_done(attempt_id, success, err_msg, tw_auth))

        threading.Thread(target=_do_flow, daemon=True).start()

    def _on_twitch_auth_done(self, attempt_id: int, success: bool, err_msg: str, tw_auth):
        if attempt_id != self._twitch_oauth_attempt_id:
            return
        self._twitch_auth_btn.setEnabled(True)
        self._twitch_revoke_btn.setEnabled(True)
        try:
            self._twitch_status_lbl.setText(tw_auth.status_label())
        except Exception:
            pass
        if success:
            QMessageBox.information(self, "認証完了", "Twitch アカウントでの認証が完了しました。")
        else:
            QMessageBox.critical(self, "認証失敗", f"Twitch 認証に失敗しました:\n{err_msg}")

    def _on_twitch_revoke(self):
        tw_auth = self._twitch_auth_getter()
        if tw_auth is None:
            return
        reply = QMessageBox.question(self, "確認", "Twitch 認証を解除してよいですか？")
        if reply == QMessageBox.StandardButton.Yes:
            tw_auth.revoke()
            try:
                self._twitch_status_lbl.setText(tw_auth.status_label())
            except Exception:
                pass

    # ─── 接続プロファイル ───────────────────────────────────────────────────────

    def _refresh_profile_list(self):
        self._profile_edit_data = self._sm.get_connection_profiles()
        self._profile_listbox.clear()
        for p in self._profile_edit_data:
            plat  = PLATFORM_LABELS.get(p.get("platform", "youtube"), "YouTube")
            en    = "✓" if p.get("enabled", True) else "　"
            name  = p.get("profile_name", p.get("display_name", ""))
            url   = p.get("target_url", "")
            url_s = url[:40] + "…" if len(url) > 40 else url
            self._profile_listbox.addItem(f"[{en}] [{plat}] {name}  — {url_s}")

    def _on_profile_add(self):
        new_id   = f"profile_{len(self._profile_edit_data)}"
        def_name = f"接続{len(self._profile_edit_data) + 1}"
        new_p    = {
            "profile_id":   new_id,
            "platform":     "youtube",
            "profile_name": def_name,
            "overlay_name": def_name,
            "tts_name":     def_name,
            "display_name": def_name,
            "enabled":      True,
            "target_url":   "",
        }
        result = self._open_profile_edit_dialog(new_p)
        if result is not None:
            self._profile_edit_data.append(result)
            self._sm.save_connection_profiles(self._profile_edit_data)
            self._refresh_profile_list()

    def _on_profile_edit(self):
        row = self._profile_listbox.currentRow()
        if row < 0 or row >= len(self._profile_edit_data):
            return
        result = self._open_profile_edit_dialog(dict(self._profile_edit_data[row]))
        if result is not None:
            self._profile_edit_data[row] = result
            self._sm.save_connection_profiles(self._profile_edit_data)
            self._refresh_profile_list()
            self._profile_listbox.setCurrentRow(row)

    def _on_profile_delete(self):
        row = self._profile_listbox.currentRow()
        if row < 0 or row >= len(self._profile_edit_data):
            return
        p    = self._profile_edit_data[row]
        name = p.get("profile_name", p.get("display_name", ""))
        reply = QMessageBox.question(self, "確認", f"「{name}」を削除しますか？")
        if reply == QMessageBox.StandardButton.Yes:
            self._profile_edit_data.pop(row)
            self._sm.save_connection_profiles(self._profile_edit_data)
            self._refresh_profile_list()

    def _open_profile_edit_dialog(self, profile: dict) -> "dict | None":
        """プロファイル編集ダイアログ（モーダル）"""
        dlg = QDialog(self)
        dlg.setWindowTitle("接続プロファイルを編集")
        dlg.setMinimumWidth(480)
        dlg.resize(520, 340)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setColumnMinimumWidth(0, 110)
        grid.setColumnStretch(1, 1)

        def add_row(label, widget, row):
            grid.addWidget(QLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(widget, row, 1)

        # プラットフォーム
        plat_combo = QComboBox()
        plat_combo.addItems(list(PLATFORM_LABELS.keys()))
        pidx = plat_combo.findText(profile.get("platform", "youtube"))
        if pidx >= 0:
            plat_combo.setCurrentIndex(pidx)
        add_row("プラットフォーム:", plat_combo, 0)

        # プロファイル名
        pname_edit = QLineEdit(profile.get("profile_name", profile.get("display_name", "")))
        add_row("プロファイル名:", pname_edit, 1)

        # 配信用表示名
        oname_edit = QLineEdit(profile.get("overlay_name", profile.get("display_name", "")))
        add_row("配信用表示名:", oname_edit, 2)

        # 読み上げ名
        tname_edit = QLineEdit(profile.get("tts_name", profile.get("display_name", "")))
        add_row("読み上げ名:", tname_edit, 3)

        # 接続先 URL
        url_edit = QLineEdit(profile.get("target_url", ""))
        add_row("接続先 URL:", url_edit, 4)

        # 有効
        en_chk = QCheckBox("有効（自動接続対象）")
        en_chk.setChecked(profile.get("enabled", True))
        grid.addWidget(en_chk, 5, 1)

        layout.addLayout(grid)

        # ボタン行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("キャンセル")
        btn_ok     = QPushButton("OK")
        btn_ok.setDefault(True)
        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        pname = pname_edit.text().strip() or "接続"
        return {
            "profile_id":   profile.get("profile_id", "profile_new"),
            "platform":     plat_combo.currentText(),
            "profile_name": pname,
            "overlay_name": oname_edit.text().strip() or pname,
            "tts_name":     tname_edit.text().strip() or pname,
            "display_name": pname,
            "enabled":      en_chk.isChecked(),
            "target_url":   url_edit.text().strip(),
        }

    # ─── 位置保存・復元 ────────────────────────────────────────────────────────

    def _restore_pos(self):
        pos = self._pos_getter()
        if pos and len(pos) >= 2:
            self.move(int(pos[0]), int(pos[1]))

    def moveEvent(self, event):
        super().moveEvent(event)
        self._pos_save_timer.start()

    def closeEvent(self, event):
        """X ボタンでは非表示にするだけ（reject と同じ動作）"""
        event.accept()

    # ─── ヘルパー ──────────────────────────────────────────────────────────────

    def _section(self, layout, text: str):
        if layout.count() > 0:
            spacer = QWidget()
            spacer.setFixedHeight(6)
            layout.addWidget(spacer)
        lbl = QLabel(text)
        f   = QFont()
        f.setBold(True)
        lbl.setFont(f)
        lbl.setStyleSheet("color: #AAAACC;")
        layout.addWidget(lbl)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #333355;")
        layout.addWidget(line)

