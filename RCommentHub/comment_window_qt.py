"""
RCommentHub — Qt版 CommentWindow（Phase 3 最小骨格）

Tk版 comment_window.py の責務を PySide6 QMainWindow で再実装。
Phase 3 時点では接続後の「コメント受信中」を示す最小 UI のみ。
フィルタ・ユーザー管理・アイコン・カスタム描画等の完全移植は Phase 4 以降。

Phase 3 で維持する責務:
  - 接続状態の表示（set_conn_status）
  - 受信コメントのリスト表示（add_comment）
  - ウィンドウのopen / close / is_open
  - コントローラのコールバック経路（on_comment_added / on_conn_status）と接続できる形

今回対象外（Phase 4 以降）:
  - フィルタタブ・ユーザータブ・フィルタ設定タブ
  - カードスタイルのカスタム描画
  - アイコン取得・表示
  - Overlay / TTS 連携
  - OBS 映り込み制御・透過・最前面
"""

import ctypes
import ctypes.wintypes
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSizePolicy, QPushButton,
)
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QColor

from constants import CONN_STATUS_LABELS
from comment_view_qt import CommentView


# ─── 接続状態ごとの表示色（Tk版 CONN_STATUS_COLORS に準拠）─────────────────────
_STATUS_COLORS = {
    "disconnected": "#888888",
    "connecting":   "#FFCC44",
    "receiving":    "#44FF44",
    "reconnecting": "#FF8844",
    "error":        "#FF4444",
    "debug":        "#AA88FF",
}

# ─── コメント種別ごとの行色（最小版）────────────────────────────────────────────
_KIND_BG_COLORS = {
    "superChatEvent":           "#2A1A00",
    "superStickerEvent":        "#1A1A00",
    "memberMilestoneChatEvent": "#001A2A",
    "membershipGiftingEvent":   "#001A2A",
    "giftMembershipReceivedEvent": "#001A2A",
    "messageDeletedEvent":      "#2A0A0A",
    "userBannedEvent":          "#2A0A0A",
}



class CommentWindowQt(QMainWindow):
    """
    Qt版 コメントビューウィンドウ（Phase 3 最小骨格）。

    接続成功後に RCommentHubQtApp から開かれる。
    add_comment(item) / set_conn_status(status, title) を提供し、
    コントローラのコールバックと接続できる。
    """

    # frameless リサイズ検出：右下コーナーの感知幅 (px)
    _EDGE_SIZE = 8
    # ステータスバー高さ（_build_ui の status_bar.setFixedHeight と一致させること）
    _STATUS_BAR_H = 28

    def __init__(self, controller, settings_mgr, parent=None, *,
                 open_connect_cb=None,
                 open_settings_cb=None,
                 open_detail_cb=None,
                 on_quit_cb=None):
        super().__init__(parent)
        self._ctrl = controller
        self._sm   = settings_mgr
        self._open_flag = False

        self._open_connect  = open_connect_cb  or (lambda: None)
        self._open_settings = open_settings_cb or (lambda: None)
        self._open_detail   = open_detail_cb   or (lambda: None)
        self._on_quit       = on_quit_cb        or (lambda: None)

        # 初期化完了フラグ（False の間は moveEvent / resizeEvent の geometry 保存を抑制）
        # RRoulette PySide6 の _init_complete と同方針
        self._init_complete = False

        # showEvent での位置復元済みフラグ（初回 show 時のみ _restore_pos を実行する）
        self._pos_restored = False

        self.setWindowTitle("RCommentHub - コメントビュー")
        self.resize(
            int(self._sm.get("cw_width",  440)),
            int(self._sm.get("cw_height", 680)),
        )

        # ジオメトリ保存デバウンス（moveEvent / resizeEvent ごとのディスク書き込みを防ぐ）
        self._geom_save_timer = QTimer(self)
        self._geom_save_timer.setSingleShot(True)
        self._geom_save_timer.setInterval(400)  # 最後の操作から 400ms 後に保存
        self._geom_save_timer.timeout.connect(self._flush_geometry)

        # topmost フラグの現在値（変化があった時のみ show() を呼ぶ）
        self._current_topmost: bool | None = None

        self._time_visible   = True       # settings の time_visible に連動（apply_display_settings で更新）
        self._time_mode      = "実時間"   # settings の time_mode に連動（apply_display_settings で更新）
        self._icon_visible   = True       # settings の icon_visible に連動（apply_display_settings で更新）
        self._show_source    = False      # settings の cw_show_source に連動（apply_display_settings で更新）
        self._display_rows   = 1          # settings の display_rows に連動（apply_display_settings で更新）
        self._font_size_name = 9          # settings の font_size_name に連動（apply_display_settings で更新）
        self._font_size_body = 9          # settings の font_size_body に連動（apply_display_settings で更新）
        self._session_start_time: datetime | None = None  # 経過時間モード用（receiving 開始時にセット）

        # ── frameless 化（show() より前に確定）────────────────────────────────────
        # FramelessWindowHint を WA_TranslucentBackground より先に設定する
        # （Windows では FramelessWindowHint がないと TranslucentBackground が
        #   正常に機能しないため）。
        # Window を明示することで Alt+Tab に表示される。
        # topmost トグルは apply_display_settings で setWindowFlag(WindowStaysOnTopHint)
        # が個別変更するため FramelessWindowHint は維持される。
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )

        # ── 透過基盤（show() より前に必ず設定）──────────────────────────────────
        # WA_TranslucentBackground を show() 後に変更すると Windows が native window を
        # 再生成してフラッシュするため、__init__ でのみ設定する。
        # QMainWindow 自体を透明にして背景塗りは centralWidget の stylesheet に集約する
        # （RRoulette の _init_window_shell() と同じ方針）。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._build_ui()
        # _restore_pos() は showEvent + singleShot(0) で遅延実行する
        # （Qt レイアウト確定後に正しい座標で復元するため）
        self.apply_display_settings()

        # 初期化完了。以降の moveEvent / resizeEvent で geometry 保存が有効になる
        self._init_complete = True

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        # QMainWindow 自体は透明（WA_TranslucentBackground で DWM レベルの白フラッシュを防ぐ）
        # 背景塗りは centralWidget の stylesheet に集約する（RRoulette と同方針）
        self.setStyleSheet("QMainWindow { background: transparent; }")

        central = QWidget()
        self.setCentralWidget(central)
        # centralWidget に暗色背景を設定する。
        # objectName セレクタで自ウィジェットのみに適用し、子への意図しないカスケードを防ぐ。
        central.setObjectName("cwCentral")
        central.setStyleSheet("QWidget#cwCentral { background: #0D0D1A; }")
        # Qt の自動パレット塗りを無効化（RRoulette と同方針）
        central.setAutoFillBackground(False)
        # WA_OpaquePaintEvent: central は全ピクセルを自前で塗る → Qt が親背景を先に塗らなくてよい
        central.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 接続状態バー ────────────────────────────────────────────────────
        status_bar = QWidget()
        status_bar.setFixedHeight(28)
        status_bar.setStyleSheet("background: #1A1A2A;")
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(10, 2, 10, 2)

        self._status_lbl = QLabel("未接続")
        self._status_lbl.setStyleSheet(f"color: {_STATUS_COLORS['disconnected']}; font-weight: bold;")
        sb_layout.addWidget(self._status_lbl)

        self._title_lbl = QLabel("")
        self._title_lbl.setStyleSheet("color: #AAAAAA;")
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sb_layout.addWidget(self._title_lbl)

        # ── ステータスバー右端ボタン群（v0.3.2 相当: 接続・詳細・設定） ────────
        _btn_style = (
            "QPushButton {"
            "  background: #252535; color: #CCCCCC;"
            "  border: none; padding: 1px 7px; font-size: 9pt;"
            "}"
            "QPushButton:hover { background: #3A3A5A; }"
            "QPushButton:pressed { background: #1A1A3A; }"
        )
        for label, callback in [
            ("接続", self._open_connect),
            ("詳細", self._open_detail),
            ("設定", self._open_settings),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setStyleSheet(_btn_style)
            btn.clicked.connect(callback)
            sb_layout.addWidget(btn)

        btn_close = QPushButton("×")
        btn_close.setFixedSize(22, 22)
        btn_close.setStyleSheet(
            "QPushButton { background: #3A2020; color: #FFAAAA; border: none; font-size: 11pt; }"
            "QPushButton:hover { background: #882222; color: #FFFFFF; }"
        )
        btn_close.clicked.connect(self._on_quit)
        sb_layout.addWidget(btn_close)

        root.addWidget(status_bar)

        # ── コメントビュー（QAbstractScrollArea + QPainter 全自前描画）────────
        self._comment_view = CommentView()
        root.addWidget(self._comment_view)

    # ─── 公開 API ──────────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._open_flag and self.isVisible()

    def apply_display_settings(self) -> None:
        """
        settings_mgr から表示設定を読み込んで反映する。
        開いているウィンドウへの即時反映・open() 時の再適用 両方で呼ばれる。

        反映対象（Phase 5-5 時点で CommentWindowQt が持つ要素の範囲）:
          cw_topmost       → WindowStaysOnTopHint フラグ
          time_visible     → add_comment の時刻表示 ON/OFF
          font_size_body   → コメントリスト本文フォントサイズ / デリゲートの body フォント
          font_size_name   → デリゲートの header フォント（display_rows=2 時の投稿者名行）
          cw_transparent   → ウィンドウ透過モード ON/OFF
          cw_comment_alpha → 透過時の不透明度 % (10〜100)
          cw_show_source   → add_comment の接続元ラベル表示 ON/OFF
          display_rows     → add_comment の表示行数（1=1行コンパクト / 2=2行標準）
          time_mode        → 時刻表示形式（"実時間" = HH:MM:SS / "経過時間" = MM:SS 経過）
          icon_visible     → アイコン表示 ON/OFF（Phase 4 以降で実描画。フラグのみ保持）
        """
        # ── 最前面表示 ────────────────────────────────────────────────────────
        # setWindowFlag(WindowStaysOnTopHint) + show() はネイティブウィンドウを
        # 再生成して背面落ち・フラッシュを引き起こすため、Win32 SetWindowPos で制御する。
        # ウィンドウ未表示時は _apply_topmost がスキップし showEvent で再適用される。
        topmost = bool(self._sm.get("cw_topmost", False))
        if topmost != self._current_topmost:
            self._current_topmost = topmost
            self._apply_topmost(topmost)

        # ── 時刻表示 ─────────────────────────────────────────────────────────
        self._time_visible = bool(self._sm.get("time_visible", True))
        self._time_mode    = str(self._sm.get("time_mode", "実時間"))

        # ── アイコン表示（Phase 4 以降で実描画。フラグのみ保持） ──────────────
        self._icon_visible = bool(self._sm.get("icon_visible", True))

        # ── 接続元ラベル表示（マルチ接続識別用） ─────────────────────────────
        self._show_source = bool(self._sm.get("cw_show_source", False))

        # ── 表示行数（1=1行コンパクト / 2=2行標準） ───────────────────────────
        self._display_rows = max(1, min(2, int(self._sm.get("display_rows", 1))))

        # ── コメントビュー 設定反映 ────────────────────────────────────────────
        self._font_size_body = max(7, int(self._sm.get("font_size_body", 9)))
        self._font_size_name = max(7, int(self._sm.get("font_size_name", 9)))
        self._comment_view.apply_settings(
            display_rows   = self._display_rows,
            font_size_name = self._font_size_name,
            font_size_body = self._font_size_body,
            icon_visible   = self._icon_visible,
        )

        # ── 透過設定 ──────────────────────────────────────────────────────────
        # QWidget.setWindowOpacity() は Qt ネイティブで動作するため ctypes 不要。
        # cw_transparent=True のとき cw_comment_alpha (10〜100) をそのまま不透明度 % として使用。
        # cw_transparent=False のときは不透明度 100% (完全不透明) に戻す。
        transparent = bool(self._sm.get("cw_transparent", False))
        if transparent:
            alpha_pct = max(10, min(100, int(self._sm.get("cw_comment_alpha", 100))))
            self.setWindowOpacity(alpha_pct / 100.0)
        else:
            self.setWindowOpacity(1.0)

    def open(self):
        """ウィンドウを表示する。すでに開いていれば前面に出す。"""
        self._open_flag = True
        self.apply_display_settings()   # 開く直前に最新設定を適用
        self.show()
        self.raise_()
        self.activateWindow()

    def close(self):
        """ウィンドウを非表示にする（アプリ終了ではなく hide）。"""
        self._open_flag = False
        super().hide()

    def _elapsed_str(self, recv_time: datetime) -> str:
        """recv_time から接続開始時刻（_session_start_time）までの経過時間を文字列で返す。"""
        if self._session_start_time is None:
            return "00:00"
        delta = recv_time - self._session_start_time
        total_sec = max(0, int(delta.total_seconds()))
        h, rem = divmod(total_sec, 3600)
        m, s   = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def add_comment(self, item) -> None:
        """
        コメント1件をビューに追加する（コントローラの on_comment_added コールバック用）。
        メインスレッドから呼ばれる前提（dispatch_to_main 経由）。
        """
        recv_time = getattr(item, "recv_time", None)
        if self._time_mode == "経過時間" and recv_time is not None:
            time_str = self._elapsed_str(recv_time)
        else:
            time_str = item.recv_time_str() if hasattr(item, "recv_time_str") else ""
        author    = getattr(item, "author_name", "—") or "—"
        body      = getattr(item, "body", "") or ""
        kind      = getattr(item, "kind", "")
        is_system = getattr(item, "is_system_message", False)

        # 接続元プレフィックス（cw_show_source=True かつ通常コメントのみ）
        source_pfx = ""
        if not is_system and self._show_source:
            sid   = getattr(item, "source_id",   "conn1")
            sname = getattr(item, "source_name", "") or sid
            if sname:
                source_pfx = f"[{sname}] "

        # header: 名前+時刻行 / body: 本文（CommentView が display_rows に応じて使い分ける）
        if is_system:
            header_line = f"[{time_str}] {body}" if self._time_visible else body
            body_text   = ""
            row_author  = None
        else:
            header_line = (f"[{time_str}] {source_pfx}{author}" if self._time_visible
                           else f"{source_pfx}{author}")
            body_text   = body
            row_author  = author

        # 背景色
        if is_system or kind not in _KIND_BG_COLORS:
            bg_color = None
        else:
            bg_color = QColor(_KIND_BG_COLORS[kind])

        # 前景色
        if is_system:
            fg_color = QColor("#888888")
        elif kind in _KIND_BG_COLORS:
            fg_color = QColor("#FFD080")
        elif getattr(item, "is_owner", False):
            fg_color = QColor("#FFDD44")
        elif getattr(item, "is_moderator", False):
            fg_color = QColor("#44AAFF")
        elif getattr(item, "filter_match", False):
            fg_color = QColor("#FF88AA")
        else:
            fg_color = QColor("#CCCCCC")

        self._comment_view.add_row(header_line, body_text, row_author, bg_color, fg_color)

    def set_conn_status(self, status: str, title: str = "") -> None:
        """
        接続状態を更新する（コントローラの on_conn_status コールバック用）。
        """
        label = CONN_STATUS_LABELS.get(status, status)
        color = _STATUS_COLORS.get(status, "#888888")
        self._status_lbl.setText(label)
        self._status_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._title_lbl.setText(title)
        # 受信開始時: セッション開始時刻を記録（経過時間モード用）
        if status == "receiving" and self._session_start_time is None:
            self._session_start_time = datetime.now()

        # 切断・停止時: セッション開始時刻をリセット
        if status in ("disconnected", "error"):
            self._session_start_time = None

        # 受信開始時にウィンドウタイトルも更新
        if title:
            self.setWindowTitle(f"RCommentHub - {title}")
        else:
            self.setWindowTitle("RCommentHub - コメントビュー")

    # ─── 位置保存・復元 ────────────────────────────────────────────────────────

    def _restore_pos(self):
        x = self._sm.get("cw_x", None)
        y = self._sm.get("cw_y", None)
        if x is not None and y is not None:
            self.move(int(x), int(y))

    def _flush_geometry(self):
        """デバウンスタイマーで遅延呼び出し: 位置・サイズを一括保存する。"""
        if not self._init_complete:
            return
        self._sm.update({
            "cw_x": self.x(), "cw_y": self.y(),
            "cw_width": self.width(), "cw_height": self.height(),
        })

    def _apply_topmost(self, topmost: bool):
        """
        Win32 SetWindowPos でトップモスト状態を切り替える。

        Qt の setWindowFlag(WindowStaysOnTopHint) + show() はネイティブウィンドウを
        再生成して背面落ち・フラッシュを引き起こすため使わない。
        ウィンドウが未表示（isVisible() == False）のときは何もせず返る。
        showEvent で _current_topmost を参照して再適用する。
        """
        if not self.isVisible():
            return
        try:
            user32 = ctypes.windll.user32
            # argtypes を明示して HWND_TOPMOST(-1) をポインタサイズで正しく渡す
            user32.SetWindowPos.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_uint,
            ]
            HWND_TOPMOST   = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE     = 0x0001
            SWP_NOMOVE     = 0x0002
            SWP_NOACTIVATE = 0x0010
            hwnd    = int(self.winId())
            z_order = HWND_TOPMOST if topmost else HWND_NOTOPMOST
            user32.SetWindowPos(hwnd, z_order, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _apply_dwm_borderless(self):
        """Windows DWM レベルで外周枠・角丸・影を除去する（RRoulette と同方針）。

        Windows 11 では FramelessWindowHint だけでは DWM が 1px ボーダーと
        角丸を描画し続けるため、DwmSetWindowAttribute で直接除去する。
        native window 再生成後（topmost トグル等）も showEvent から再呼び出しする。
        """
        try:
            hwnd = int(self.winId())
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DONOTROUND = 1
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmSetWindowAttribute(
                hwnd, 33,
                ctypes.byref(ctypes.c_uint(1)),
                ctypes.sizeof(ctypes.c_uint),
            )
            # DWMWA_BORDER_COLOR = 35, DWMWA_COLOR_NONE = 0xFFFFFFFE
            dwmapi.DwmSetWindowAttribute(
                hwnd, 35,
                ctypes.byref(ctypes.c_uint(0xFFFFFFFE)),
                ctypes.sizeof(ctypes.c_uint),
            )
        except Exception:
            pass  # Windows 以外 / 非対応バージョン

    def nativeEvent(self, event_type, message):
        """WM_NCHITTEST をインターセプトして frameless ドラッグ・リサイズを実現する。

        RRoulette の Python-side mousePressEvent 方式は、CommentWindowQt では
        QListWidget がマウスイベントを消費するため使えない。
        代わりに Windows が WM_NCHITTEST に基づいてドラッグ・リサイズを
        ネイティブ処理する仕組みを使う。これで QListWidget のスクロールと
        ウィンドウ操作が干渉しない。

        HTCAPTION (2)      : ステータスバー域 → ドラッグ移動（Windows が処理）
        HTBOTTOMRIGHT (17) : 右下コーナー → リサイズ（Windows が処理）
        """
        if event_type == b'windows_generic_MSG':
            msg = ctypes.wintypes.MSG.from_address(int(message))
            WM_NCHITTEST      = 0x0084
            WM_NCLBUTTONDBLCLK = 0x00A3

            if msg.message == WM_NCHITTEST:
                lp = int(msg.lParam)
                sx = ctypes.c_short(lp & 0xFFFF).value
                sy = ctypes.c_short((lp >> 16) & 0xFFFF).value
                pos = self.mapFromGlobal(QPoint(sx, sy))
                # 右下コーナー → リサイズ（Windows がカーソル・ドラッグを制御）
                if (pos.x() >= self.width()  - self._EDGE_SIZE and
                        pos.y() >= self.height() - self._EDGE_SIZE):
                    return True, 17  # HTBOTTOMRIGHT
                # ステータスバー域 → ドラッグ移動
                # ただしボタン上（QPushButton）は HTCLIENT として Qt にクリックを渡す
                if pos.y() <= self._STATUS_BAR_H:
                    child = self.childAt(pos)
                    if isinstance(child, QPushButton):
                        # ボタン上: Qt 側のクリック処理に渡す（HTCAPTION にしない）
                        return super().nativeEvent(event_type, message)
                    return True, 2   # HTCAPTION（ドラッグ移動）

            if msg.message == WM_NCLBUTTONDBLCLK:
                # HTCAPTION ダブルクリックによる意図しない最大化を抑制
                return True, 0

        return super().nativeEvent(event_type, message)

    def showEvent(self, event):
        """show のたびに DWM borderless と topmost 状態を再適用し、初回のみ位置を遅延復元する。

        Win32 SetWindowPos でトップモスト管理するため、Qt の WindowStaysOnTopHint に
        依存しなくなった。代わりに showEvent 時点で _current_topmost を再適用して
        ネイティブウィンドウ表示後も状態を維持する。
        位置復元は Qt レイアウト確定後（singleShot 0ms）に 1 回だけ行う
        （RRoulette PySide6 の showEvent + singleShot(0) 遅延復元と同方針）。
        """
        super().showEvent(event)
        self._apply_dwm_borderless()
        # topmost 状態を再適用（show 直後は isVisible() == True なので即時実行できる）
        if self._current_topmost is not None:
            self._apply_topmost(self._current_topmost)
        if not self._pos_restored:
            self._pos_restored = True
            QTimer.singleShot(0, self._restore_pos)

    def moveEvent(self, event):
        """ドラッグ中の連続ファイル書き込みを防ぐため、タイマーで 400ms デバウンスする。
        _init_complete が False の間（初期化中）は保存をスキップする。"""
        super().moveEvent(event)
        if not self._init_complete:
            return
        self._geom_save_timer.start()

    def resizeEvent(self, event):
        """リサイズ中の連続ファイル書き込みを防ぐため、タイマーで 400ms デバウンスする。
        _init_complete が False の間（初期化中）は geometry 保存をスキップする。
        CommentView.resizeEvent が行高キャッシュ無効化・スクロールバー更新を行う。"""
        super().resizeEvent(event)
        if self._init_complete:
            self._geom_save_timer.start()

    def closeEvent(self, event):
        """
        コメントビュー（正規メインウィンドウ）の close イベント。
        Alt+F4 等のシステム close も含め、アプリ全体を終了する。
        """
        event.ignore()
        self._on_quit()
