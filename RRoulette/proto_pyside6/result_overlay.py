"""
PySide6 プロトタイプ — 結果表示オーバーレイ

spin 結果を wheel 上に重ねて表示するウィジェット。
MainWindow から分離し、見た目や挙動の管理を集約する。

責務:
  - overlay の生成・表示・非表示
  - クリック時の閉じ処理
  - デザイン連動のスタイル適用
  - コンテナ内の中央配置

今後の拡張ポイント:
  - 表示アニメーション（フラッシュ等）
  - 自動クローズタイマー
  - テキスト表示モード（省略 / 縮小）
  - 背景色モード（デザイン色 / セグメント色）
  - フォント / パディング / 角丸の設定化
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget

from bridge import DesignSettings


class ResultOverlay(QLabel):
    """spin 結果を表示するオーバーレイラベル。

    parent（wheel_container）の中央に配置され、
    クリックで閉じる。

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

    # ================================================================
    #  公開 API
    # ================================================================

    def show_result(self, winner: str):
        """結果テキストを表示し、中央に配置する。"""
        self.setText(f"  \U0001f3af {winner}  ")
        self.show()
        self.raise_()
        self.update_position()

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
    #  イベント
    # ================================================================

    def mousePressEvent(self, event: QMouseEvent):
        """左クリック -> overlay を閉じるだけ（spin しない）。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.hide()
            self.closed.emit()
