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

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QSizePolicy,
    QStyle, QStyledItemDelegate,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QFontMetrics

from constants import CONN_STATUS_LABELS, VERSION


# ─── 接続状態ごとの表示色（Tk版 CONN_STATUS_COLORS に準拠）────────────────────
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


class _CommentItemDelegate(QStyledItemDelegate):
    """
    コメントアイテムの描画デリゲート（Phase 5-6 更新）。

    display_rows=1（\\n なし）: font_size_name を option.font に設定して super().paint() に委ねる。
    display_rows=2（\\n あり）: header 行を font_size_name、body 行を font_size_body で独自描画。
    get_name_size / get_body_size は最新値を返す callable（CommentWindowQt のフィールド参照）。
    """

    def __init__(self, parent, get_name_size, get_body_size):
        super().__init__(parent)
        self._get_name_size = get_name_size
        self._get_body_size = get_body_size

    def _make_fonts(self, base_font):
        fn = QFont(base_font)
        fn.setPointSize(max(7, self._get_name_size()))
        fb = QFont(base_font)
        fb.setPointSize(max(7, self._get_body_size()))
        return fn, fb

    def sizeHint(self, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if "\n" not in text:
            # 1行アイテム: font_size_name を option.font に設定してから super() に委ねる
            option = option.__class__(option)   # shallow copy（元を汚さない）
            option.font.setPointSize(max(7, self._get_name_size()))
            return super().sizeHint(option, index)
        header, body = text.split("\n", 1)
        fn, fb = self._make_fonts(option.font)
        fm_n = QFontMetrics(fn)
        fm_b = QFontMetrics(fb)
        w = max(option.rect.width() - 16, 200)
        body_h = fm_b.boundingRect(
            0, 0, w, 10000,
            int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap),
            body,
        ).height()
        return QSize(option.rect.width(), fm_n.height() + body_h + 14)

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if "\n" not in text:
            # 1行アイテム: font_size_name を option.font に設定してから super() に委ねる
            option = option.__class__(option)   # shallow copy（元を汚さない）
            option.font.setPointSize(max(7, self._get_name_size()))
            super().paint(painter, option, index)
            return

        header, body = text.split("\n", 1)
        self.initStyleOption(option, index)

        painter.save()

        # 背景描画（選択状態など）
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )

        # アイテム背景色（SuperChat など）
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg:
            painter.fillRect(option.rect, bg)

        # 前景色
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        fg_color = (fg.color() if fg else
                    option.palette.color(
                        option.palette.ColorRole.HighlightedText
                        if int(option.state) & int(QStyle.StateFlag.State_Selected)
                        else option.palette.ColorRole.Text
                    ))

        fn, fb = self._make_fonts(option.font)
        fm_n   = QFontMetrics(fn)
        rect   = option.rect.adjusted(8, 4, -8, -4)

        painter.setPen(fg_color)

        # header 行（投稿者名）— font_size_name で描画
        painter.setFont(fn)
        painter.drawText(rect.left(), rect.top() + fm_n.ascent(), header)

        # body 行（本文）— font_size_body で描画
        painter.setFont(fb)
        body_rect = rect.adjusted(0, fm_n.height() + 2, 0, 0)
        painter.drawText(
            body_rect,
            int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignTop) |
            int(Qt.TextFlag.TextWordWrap),
            body,
        )

        painter.restore()


class CommentWindowQt(QMainWindow):
    """
    Qt版 コメントビューウィンドウ（Phase 3 最小骨格）。

    接続成功後に RCommentHubQtApp から開かれる。
    add_comment(item) / set_conn_status(status, title) を提供し、
    コントローラのコールバックと接続できる。
    """

    def __init__(self, controller, settings_mgr, parent=None):
        super().__init__(parent)
        self._ctrl = controller
        self._sm   = settings_mgr
        self._open_flag = False

        self.setWindowTitle(f"RCommentHub v{VERSION} — コメント [Qt Phase 3]")
        self.resize(
            int(self._sm.get("cw_width",  440)),
            int(self._sm.get("cw_height", 680)),
        )

        self._time_visible  = True  # settings の time_visible に連動（apply_display_settings で更新）
        self._show_source   = False # settings の cw_show_source に連動（apply_display_settings で更新）
        self._display_rows  = 1    # settings の display_rows に連動（apply_display_settings で更新）
        self._font_size_name = 9   # settings の font_size_name に連動（apply_display_settings で更新）
        self._font_size_body = 9   # settings の font_size_body に連動（apply_display_settings で更新）

        self._build_ui()
        self._restore_pos()
        self.apply_display_settings()

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
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

        root.addWidget(status_bar)

        # ── フェーズ注記 ─────────────────────────────────────────────────────
        note_lbl = QLabel(
            "Phase 3 最小骨格 — フィルタ・ユーザー管理・アイコン表示は Phase 4 以降"
        )
        note_lbl.setStyleSheet("color: #555577; font-size: 9px; padding: 2px 10px;")
        note_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(note_lbl)

        # ── コメントリスト ────────────────────────────────────────────────────
        self._comment_list = QListWidget()
        self._comment_list.setStyleSheet(
            "QListWidget { background: #0D0D1A; color: #CCCCCC; border: none; }"
            "QListWidget::item { padding: 4px 8px; border-bottom: 1px solid #1A1A30; }"
            "QListWidget::item:selected { background: #2A2A44; }"
        )
        self._comment_list.setWordWrap(True)
        # display_rows=2 の2行アイテム用デリゲート（1行アイテムは super() に委ねる）
        self._comment_list.setItemDelegate(
            _CommentItemDelegate(
                self._comment_list,
                get_name_size=lambda: self._font_size_name,
                get_body_size=lambda: self._font_size_body,
            )
        )
        root.addWidget(self._comment_list)

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
        """
        # ── 最前面表示 ────────────────────────────────────────────────────────
        topmost = bool(self._sm.get("cw_topmost", False))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, topmost)
        if self.isVisible():
            # setWindowFlag は再表示が必要
            self.show()

        # ── 時刻表示 ─────────────────────────────────────────────────────────
        self._time_visible = bool(self._sm.get("time_visible", True))

        # ── 接続元ラベル表示（マルチ接続識別用） ─────────────────────────────
        self._show_source = bool(self._sm.get("cw_show_source", False))

        # ── 表示行数（1=1行コンパクト / 2=2行標準） ───────────────────────────
        self._display_rows = max(1, min(2, int(self._sm.get("display_rows", 1))))

        # ── コメントリスト フォントサイズ ─────────────────────────────────────
        # _font_size_body: リスト全体のデフォルトフォント（1行アイテム） + デリゲートの body 行
        # _font_size_name: デリゲートの header 行（display_rows=2 の投稿者名行）
        self._font_size_body = max(7, int(self._sm.get("font_size_body", 9)))
        self._font_size_name = max(7, int(self._sm.get("font_size_name", 9)))
        font = self._comment_list.font()
        font.setPointSize(self._font_size_body)
        self._comment_list.setFont(font)
        # デリゲートのキャッシュを無効化して再描画させる
        self._comment_list.update()

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

    def add_comment(self, item) -> None:
        """
        コメント1件をリストに追加する（コントローラの on_comment_added コールバック用）。
        メインスレッドから呼ばれる前提（dispatch_to_main 経由）。
        """
        # 表示テキスト生成
        time_str   = item.recv_time_str() if hasattr(item, "recv_time_str") else ""
        author     = getattr(item, "author_name", "—") or "—"
        body       = getattr(item, "body", "") or ""
        kind       = getattr(item, "kind", "")
        is_system  = getattr(item, "is_system_message", False)

        # 接続元プレフィックス（cw_show_source=True かつ通常コメントのみ）
        source_pfx = ""
        if not is_system and self._show_source:
            sid   = getattr(item, "source_id",   "conn1")
            sname = getattr(item, "source_name", "") or sid
            if sname:
                source_pfx = f"[{sname}] "

        if is_system:
            display = f"[{time_str}] {body}" if self._time_visible else body
        elif self._display_rows >= 2:
            # 2行標準: 1行目=時刻+接続元+投稿者名、2行目=本文
            header = f"[{time_str}] {source_pfx}{author}" if self._time_visible else f"{source_pfx}{author}"
            display = f"{header}\n{body}"
        else:
            # 1行コンパクト（デフォルト）
            author_str = f"{source_pfx}{author}"
            display = (f"[{time_str}] {author_str}: {body}" if self._time_visible
                       else f"{author_str}: {body}")

        list_item = QListWidgetItem(display)

        # 種別ごとの背景色
        if is_system:
            list_item.setForeground(QColor("#888888"))
        elif kind in _KIND_BG_COLORS:
            list_item.setBackground(QColor(_KIND_BG_COLORS[kind]))
            list_item.setForeground(QColor("#FFD080"))
        else:
            # ロール別テキスト色
            if getattr(item, "is_owner", False):
                list_item.setForeground(QColor("#FFDD44"))
            elif getattr(item, "is_moderator", False):
                list_item.setForeground(QColor("#44AAFF"))
            elif getattr(item, "filter_match", False):
                list_item.setForeground(QColor("#FF88AA"))
            else:
                list_item.setForeground(QColor("#CCCCCC"))

        self._comment_list.addItem(list_item)
        self._comment_list.scrollToBottom()

        # 最大表示件数（設定値があれば使用、なければ 500）
        max_items = 500
        while self._comment_list.count() > max_items:
            self._comment_list.takeItem(0)

    def set_conn_status(self, status: str, title: str = "") -> None:
        """
        接続状態を更新する（コントローラの on_conn_status コールバック用）。
        """
        label = CONN_STATUS_LABELS.get(status, status)
        color = _STATUS_COLORS.get(status, "#888888")
        self._status_lbl.setText(label)
        self._status_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._title_lbl.setText(title)
        # 受信開始時にウィンドウタイトルも更新
        if title:
            self.setWindowTitle(f"RCommentHub — {title} [Qt]")
        else:
            self.setWindowTitle(f"RCommentHub v{VERSION} — コメント [Qt]")

    # ─── 位置保存・復元 ────────────────────────────────────────────────────────

    def _restore_pos(self):
        x = self._sm.get("cw_x", None)
        y = self._sm.get("cw_y", None)
        if x is not None and y is not None:
            self.move(int(x), int(y))

    def moveEvent(self, event):
        super().moveEvent(event)
        self._sm.update({"cw_x": self.x(), "cw_y": self.y()})

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sm.update({"cw_width": self.width(), "cw_height": self.height()})

    def closeEvent(self, event):
        """X ボタンで閉じても非表示にするだけ（アプリ終了しない）"""
        self._open_flag = False
        event.ignore()
        self.hide()
