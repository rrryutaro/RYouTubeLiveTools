"""
PySide6 プロトタイプ — 結果表示オーバーレイ

spin 結果を wheel 上に重ねて表示するウィジェット。
MainWindow から分離し、見た目や挙動の管理を集約する。

責務:
  - overlay の生成・表示・非表示
  - クリック時の閉じ処理
  - 自動クローズタイマー管理
  - デザイン連動のスタイル適用
  - コンテナ内の中央配置

設定:
  - close_mode: 0=クリックのみ, 1=自動のみ, 2=両方
  - hold_sec: 自動クローズまでの秒数

今後の拡張ポイント:
  - 表示アニメーション（フラッシュ等）
  - テキスト表示モード（省略 / 縮小）
  - 背景色モード（デザイン色 / セグメント色）
  - フォント / パディング / 角丸の設定化
"""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget

from bridge import DesignSettings

# close_mode 定数
CLOSE_CLICK = 0    # クリックで閉じる
CLOSE_AUTO = 1     # 自動で閉じる
CLOSE_BOTH = 2     # クリックでも自動でも閉じる


class ResultOverlay(QLabel):
    """spin 結果を表示するオーバーレイラベル。

    parent（wheel_container）の中央に配置され、
    close_mode に応じてクリックまたは自動タイマーで閉じる。

    Signals:
        closed: overlay が閉じられた
    """

    closed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__("", parent)
        self.setFont(QFont("Meiryo", 18, QFont.Weight.Bold))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        self.hide()

        # --- 設定 ---
        self._close_mode: int = CLOSE_CLICK
        self._hold_sec: float = 5.0

        # --- macro playback 用一時フラグ ---
        self._force_auto_close: bool = False
        self._force_hold_sec: float | None = None

        # --- 自動クローズタイマー ---
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._on_auto_close)

    # ================================================================
    #  公開 API
    # ================================================================

    def show_result(self, winner: str):
        """結果テキストを表示し、中央に配置する。"""
        self._stop_auto_timer()
        self.setText(f"  \U0001f3af {winner}  ")
        self.show()
        self.raise_()
        self.update_position()
        self._start_auto_timer_if_needed()

    def dismiss(self):
        """overlay を確実に閉じる。タイマーも停止する。

        spin 開始時に RoulettePanel から呼ばれ、残留を防止する。
        パネル面クリックで閉じた場合も closed を emit する。
        """
        self._stop_auto_timer()
        self._force_auto_close = False
        self._force_hold_sec = None
        if self.isVisible():
            self.hide()
            self.closed.emit()

    def set_close_mode(self, mode: int):
        """閉じ方モードを設定する。"""
        self._close_mode = mode

    def set_hold_sec(self, sec: float):
        """自動クローズまでの秒数を設定する。"""
        self._hold_sec = max(0.5, sec)

    def set_force_auto_close(self, enabled: bool,
                             hold_sec: float | None = None):
        """次の show_result 1回分だけ自動クローズを強制する。

        macro playback 中に close_mode が CLOSE_CLICK でも
        hold_sec 後に自動で閉じるようにするための一時フラグ。
        ユーザー設定の close_mode は変更しない。

        Args:
            enabled: 強制自動クローズを有効にするか
            hold_sec: macro playback 用の hold 秒。None なら通常の hold_sec を使う。
        """
        self._force_auto_close = enabled
        self._force_hold_sec = hold_sec

    def update_position(self):
        """親コンテナの中央にオーバーレイを配置する。"""
        if not self.isVisible():
            return
        container = self.parentWidget()
        if container is None:
            return
        cw, ch = container.width(), container.height()
        self.adjustSize()
        lw = min(self.sizeHint().width() + 32, int(cw * 0.8))
        lh = self.sizeHint().height() + 16
        lx = (cw - lw) // 2
        ly = (ch - lh) // 2
        self.setGeometry(lx, ly, lw, lh)

    def apply_style(self, design: DesignSettings):
        """デザイン連動の配色を適用する。"""
        self.setStyleSheet(
            f"color: {design.gold}; "
            f"background-color: rgba(0, 0, 0, 180); "
            f"border-radius: 8px; padding: 8px 16px;"
        )

    # ================================================================
    #  自動クローズタイマー
    # ================================================================

    def _start_auto_timer_if_needed(self):
        """close_mode または force_auto_close に応じて自動クローズタイマーを開始する。"""
        if self._close_mode in (CLOSE_AUTO, CLOSE_BOTH) or self._force_auto_close:
            if self._force_auto_close and self._force_hold_sec is not None:
                sec = max(0.5, self._force_hold_sec)
            else:
                sec = self._hold_sec
            self._auto_timer.start(int(sec * 1000))

    def _stop_auto_timer(self):
        """タイマーが動いていれば停止する。"""
        if self._auto_timer.isActive():
            self._auto_timer.stop()

    def _on_auto_close(self):
        """タイマー満了時のハンドラ。"""
        self._force_auto_close = False
        self._force_hold_sec = None
        if self.isVisible():
            self.hide()
            self.closed.emit()

    # ================================================================
    #  イベント
    # ================================================================

    def mousePressEvent(self, event: QMouseEvent):
        """左クリック -> close_mode に応じて閉じる。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._close_mode in (CLOSE_CLICK, CLOSE_BOTH):
                self._stop_auto_timer()
                self._force_auto_close = False
                self._force_hold_sec = None
                self.hide()
                self.closed.emit()
