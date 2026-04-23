"""
RCommentHub — Qt版 OverlayWindow（配信用OBS表示ウィンドウ）

v0.3.2 Tk版 overlay_window.py の役割を PySide6 QWidget で再実装。

役割（v0.3.2 相当）:
  OBS 用の最前面独立ウィンドウ。最新コメント 1 件を表示する。
  コメントビューが主画面。本ウィンドウは X で閉じてもアプリは終了しない。

設定キー（overlay_* 系）:
  overlay_enabled          bool   False
  overlay_display_mode     str    "timed" | "always"
  overlay_duration_sec     int    5
  overlay_x                int    (画面下部中央)
  overlay_y                int    (画面下部中央)
  overlay_width            int    560
  overlay_height           int    110
  overlay_topmost          bool   True
  overlay_transparent      bool   False
  overlay_show_source      bool   False
  overlay_font_size_name   int    9
  overlay_font_size_body   int    11
"""

from PySide6.QtWidgets import QWidget, QSizeGrip, QApplication
from PySide6.QtCore import Qt, QTimer, QPoint, QRect
from PySide6.QtGui import QPainter, QColor, QFont

from constants import SOURCE_DEFAULT_NAMES, get_source_color

# ─── カラー定数 ───────────────────────────────────────────────────────────────
_BG_DARK    = QColor(0x0D, 0x0D, 0x1A, 230)   # 半透明ダーク（非透過モード）
_BG_HEADER  = QColor(0x1A, 0x1A, 0x30, 230)   # ヘッダー帯
_FG_HEADER  = QColor("#555577")
_FG_AUTHOR  = QColor("#88CCFF")
_FG_BODY    = QColor("#FFFFFF")

_HEADER_H   = 14    # 上部ドラッグ帯の高さ（px）
_GRIP_SIZE  = 16    # リサイズグリップのサイズ
_DEF_W      = 560   # デフォルト幅
_DEF_H      = 110   # デフォルト高さ
_DEF_MARGIN = 80    # 画面下端からのデフォルト余白

_FONT_FAMILY = "メイリオ"


class OverlayWindowQt(QWidget):
    """
    Qt版 配信用OBSオーバーレイウィンドウ。
    X で閉じると非表示になるだけでアプリは終了しない。
    """

    def __init__(self, controller, settings_mgr):
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self._ctrl = controller
        self._sm   = settings_mgr

        # 透過対応
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._current_item: object | None = None
        self._drag_pos:     QPoint | None = None

        # 自動非表示タイマー（timed モード）
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_overlay)

        # ジオメトリ保存デバウンスタイマー
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_geometry)

        # リサイズグリップ（右下）
        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(_GRIP_SIZE, _GRIP_SIZE)

        # ジオメトリ復元
        screen = QApplication.primaryScreen().geometry()
        w = max(200, int(self._sm.get("overlay_width",  _DEF_W)))
        h = max(60,  int(self._sm.get("overlay_height", _DEF_H)))
        x = int(self._sm.get("overlay_x", (screen.width()  - w) // 2))
        y = int(self._sm.get("overlay_y",  screen.height() - h - _DEF_MARGIN))
        self.setGeometry(x, y, w, h)

        self.setWindowTitle("RCommentHub - 配信用")

    # ─── 公開 API ──────────────────────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return bool(self._sm.get("overlay_enabled", False))

    def show_comment(self, item, suppress_auto_hide: bool = False) -> None:
        """
        コメントを Overlay に表示する。無効時（overlay_enabled=False）は何もしない。

        suppress_auto_hide=True のとき消去タイマーをセットしない。
        TTS 読み上げ中に消えないよう、TTS 経路から呼ぶ際に使用する。
        """
        if not self.is_enabled:
            return
        self._current_item = item
        self._hide_timer.stop()
        self.show()
        self.raise_()
        self.update()

        if (not suppress_auto_hide
                and self._sm.get("overlay_display_mode", "timed") == "timed"):
            duration = max(1, int(self._sm.get("overlay_duration_sec", 5)))
            self._hide_timer.start(duration * 1000)

    def notify_tts_spoken(self) -> None:
        """
        TTS 読み上げ完了時に呼ぶ。timed モードの場合 5 秒後に非表示にする。
        always モード時は何もしない。
        """
        if self._sm.get("overlay_display_mode", "timed") != "timed":
            return
        self._hide_timer.stop()
        self._hide_timer.start(5000)

    def on_settings_changed(self) -> None:
        """設定変更後に呼び出す（topmost / 透過などを再適用）"""
        topmost = bool(self._sm.get("overlay_topmost", True))
        flags   = self.windowFlags()
        if topmost:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        # setWindowFlags は hide → show が必要（Windows）
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self.update()

    # ─── Qt イベントオーバーライド ─────────────────────────────────────────────

    def closeEvent(self, event):
        """X で閉じても非表示にするだけでアプリは終了しない"""
        event.ignore()
        self.hide()

    def paintEvent(self, event):
        """コメント内容を描画する"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        transparent = bool(self._sm.get("overlay_transparent", False))

        if transparent:
            # 完全透明背景（コンテンツのみ描画）
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))
        else:
            # ダーク背景
            painter.fillRect(0, 0, w, h, _BG_DARK)
            # ヘッダー帯（ドラッグ領域インジケーター）
            painter.fillRect(0, 0, w, _HEADER_H, _BG_HEADER)
            hdr_font = QFont(_FONT_FAMILY, 7)
            painter.setFont(hdr_font)
            painter.setPen(_FG_HEADER)
            painter.drawText(6, _HEADER_H - 2, "RCommentHub Overlay")

        if self._current_item is None:
            painter.end()
            return

        item = self._current_item
        fn   = max(7, int(self._sm.get("overlay_font_size_name", 9)))
        fb   = max(7, int(self._sm.get("overlay_font_size_body", 11)))
        show_source = bool(self._sm.get("overlay_show_source", False))

        text_x = 10
        y_cur  = _HEADER_H + fn + 4   # テキスト開始 Y（ベースライン基準）

        # 接続元名（show_source=True の場合のみ）
        if show_source:
            sid   = getattr(item, "source_id",   "conn1")
            sname = getattr(item, "source_name", "") or SOURCE_DEFAULT_NAMES.get(sid, sid)
            if sname:
                sc = QColor(get_source_color(sid))
                src_font = QFont(_FONT_FAMILY, max(7, fn - 1))
                src_font.setBold(True)
                painter.setFont(src_font)
                painter.setPen(sc)
                painter.drawText(text_x, y_cur, f"[{sname}]")
                y_cur += fn + 2

        # 投稿者名
        name_font = QFont(_FONT_FAMILY, fn)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(_FG_AUTHOR)
        author = item.author_name or "—"
        painter.drawText(text_x, y_cur, author)
        y_cur += fn + 4

        # 本文（折り返しあり）
        body = item.body or ""
        if body:
            body_font = QFont(_FONT_FAMILY, fb)
            painter.setFont(body_font)
            painter.setPen(_FG_BODY)
            body_rect = QRect(text_x, y_cur - fb, w - text_x - _GRIP_SIZE, h - y_cur)
            painter.drawText(body_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, body)

        painter.end()

    def resizeEvent(self, event):
        """リサイズ時にグリップを右下へ移動"""
        super().resizeEvent(event)
        self._grip.move(self.width() - _GRIP_SIZE, self.height() - _GRIP_SIZE)
        self._save_timer.start(400)

    def mousePressEvent(self, event):
        """ドラッグ移動の開始（左クリック）"""
        if event.button() == Qt.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        """ドラッグ移動"""
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        """ドラッグ終了 → ジオメトリ保存スケジュール"""
        self._drag_pos = None
        self._save_timer.start(400)

    # ─── 内部 ─────────────────────────────────────────────────────────────────

    def _hide_overlay(self) -> None:
        """timed モードの自動非表示タイマーで呼ばれる"""
        self.hide()

    def _save_geometry(self) -> None:
        """位置・サイズを settings_mgr に保存（デバウンス後）"""
        try:
            self._sm.update({
                "overlay_x":      self.x(),
                "overlay_y":      self.y(),
                "overlay_width":  self.width(),
                "overlay_height": self.height(),
            })
        except Exception:
            pass
