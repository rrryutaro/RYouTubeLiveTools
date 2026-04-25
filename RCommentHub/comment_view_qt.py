"""
RCommentHub — CommentView（QAbstractScrollArea + QPainter 全自前描画）

QListWidget + delegate ベース構成から脱却した新しいコメント表示ウィジェット。
描画タイミング・スクロール・行高を完全自前制御することで、
リサイズ時のちらつきを根本回避する。

外部向け API:
  add_row(header, body, author, bg_color, fg_color)  コメント行を追加
  apply_settings(display_rows, font_size_name, font_size_body, icon_visible)  設定反映
  clear()  全コメントを消去
  scroll_to_bottom()  末尾にスクロール
"""

import hashlib
import logging

from PySide6.QtWidgets import QAbstractScrollArea, QSizePolicy
from PySide6.QtCore import Qt, QRect, QRectF, QEvent, QUrl
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

_log = logging.getLogger("comment_view_qt")


# ─── 定数 ─────────────────────────────────────────────────────────────────────
_ICON_SIZE     = 24     # アイコン辺長 (px)
_ICON_MARGIN   = 6      # アイコン右側マージン (px)
_VPAD          = 4      # 行の上下パディング (px)
_NAME_BODY_GAP = 2      # 2行モード: 名前行と本文行の間隔 (px)
_BG_BASE       = QColor("#0D0D1A")   # ベース背景色
_SEP_COLOR     = QColor("#1A1A30")   # 行区切り線
_SEL_COLOR     = QColor("#2A3A5A")   # 選択行ハイライト色


# ─── 行データ ─────────────────────────────────────────────────────────────────

class _RowData:
    """
    コメント行の表示用データ。

    header: 1行目テキスト（1行モード=全体、2行モード=時刻+投稿者名）
    body:   2行目テキスト（本文。1行モードや空の場合は ""）
    author: 投稿者名（アイコン描画用。システムメッセージは None）
    bg_color: 行背景色（None=ベース背景）
    fg_color: 前景色
    cached_h: 計算済み行高（-1=未計算）
    """
    __slots__ = ('header', 'body', 'author', 'bg_color', 'fg_color', 'cached_h', 'profile_url')

    def __init__(self, header: str, body: str,
                 author, bg_color, fg_color: QColor, profile_url: str = ""):
        self.header      = header
        self.body        = body
        self.author      = author       # str | None
        self.bg_color    = bg_color     # QColor | None
        self.fg_color    = fg_color
        self.cached_h    = -1           # 未計算
        self.profile_url = profile_url  # プロフィール画像 URL（空文字 = なし）


# ─── CommentView ──────────────────────────────────────────────────────────────

class CommentView(QAbstractScrollArea):
    """
    QAbstractScrollArea + QPainter ベースのコメント表示ウィジェット。

    QListWidget + delegate ベース構成の限界（リサイズ時ちらつき、
    doItemsLayout 制御不能）を根本回避するために新設。
    描画・スクロール・行高キャッシュをすべて自前制御する。
    """

    MAX_ROWS = 500  # 最大保持件数（超過時は先頭から削除）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # viewport の自動塗りつぶしを無効化（自前で全ピクセルを塗る）
        self.viewport().setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        # コメント行データ
        self._rows: list = []  # list[_RowData]

        # 表示設定（apply_settings() で更新）
        self._display_rows   = 1
        self._font_size_name = 9
        self._font_size_body = 9
        self._icon_visible   = True

        # 前回計算時の viewport 幅（幅が変わったら全高無効化）
        self._last_vp_width = -1

        # 自動スクロール（末尾追従）
        # ユーザーがスクロールバーを操作したら一時停止し、末尾近くで再開する
        self._auto_scroll = True
        self.verticalScrollBar().sliderPressed.connect(self._on_slider_pressed)
        self.verticalScrollBar().sliderReleased.connect(self._on_slider_released)

        # 行選択（None=未選択、int=選択中行インデックス）
        self._selected_row: int | None = None
        # 選択行変更コールバック（外部からセット可能）: f(index: int | None) -> None
        self.on_row_selected = None

        # プロフィール画像キャッシュ（URL → QPixmap または None=ロード済み失敗/読込中）
        self._icon_pixmap_cache: dict = {}
        self._nam = QNetworkAccessManager(self)

        self.setStyleSheet(
            "QAbstractScrollArea { background: #0D0D1A; border: none; }"
            "QScrollBar:vertical { background: #1A1A2A; width: 8px; }"
            "QScrollBar::handle:vertical { background: #444466; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

    # ─── 外部向け API ──────────────────────────────────────────────────────────

    def add_row(self, header: str, body: str,
                author, bg_color, fg_color: QColor,
                profile_url: str = "") -> None:
        """
        コメント行を追加する。

        header:      表示テキスト 1行目（2行モードでは投稿者名+時刻、1行モードでは全体）
        body:        表示テキスト 2行目の本文（1行モード時や空の場合は ""）
        author:      投稿者名（str）または None（システムメッセージ）
        bg_color:    行背景色（QColor または None）
        fg_color:    前景色（QColor）
        profile_url: プロフィール画像 URL（空文字=なし → 頭文字プレースホルダー）
        """
        _log.info("add_row: author=%s url=%s", author, profile_url[:40] if profile_url else "")
        row = _RowData(header, body, author, bg_color, fg_color, profile_url)
        self._rows.append(row)

        # プロフィール画像を非同期フェッチ（未キャッシュの場合のみ）
        if profile_url and self._icon_visible:
            self._fetch_icon(profile_url)

        # 最大件数を超えたら先頭から削除（残行の cached_h は有効のまま）
        while len(self._rows) > self.MAX_ROWS:
            self._rows.pop(0)

        self._update_scrollbar()
        if self._auto_scroll:
            self.scroll_to_bottom()
        # 1件目は即時描画（repaint）、以降はバッチ処理（update）
        if len(self._rows) == 1:
            self.viewport().repaint()
        else:
            self.viewport().update()

    def apply_settings(self, display_rows: int, font_size_name: int,
                       font_size_body: int, icon_visible: bool) -> None:
        """表示設定を更新し、必要なら行高キャッシュを無効化して再描画する。"""
        changed = (
            self._display_rows   != display_rows   or
            self._font_size_name != font_size_name or
            self._font_size_body != font_size_body or
            self._icon_visible   != icon_visible
        )
        self._display_rows   = display_rows
        self._font_size_name = font_size_name
        self._font_size_body = font_size_body
        self._icon_visible   = icon_visible
        if changed:
            self._invalidate_heights()
            self._update_scrollbar()
            self.viewport().update()

    def clear(self) -> None:
        """全コメントを消去する。"""
        self._rows.clear()
        self._update_scrollbar()
        self.viewport().update()

    def scroll_to_bottom(self) -> None:
        """垂直スクロールバーを末尾に移動する。"""
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ─── Qt イベント ───────────────────────────────────────────────────────────

    def viewportEvent(self, event):
        """viewport への Paint・クリックイベントを処理する。"""
        if event.type() == QEvent.Type.Paint:
            painter = QPainter(self.viewport())
            try:
                self._paint_content(painter)
            finally:
                painter.end()
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                idx = self._row_at_y(int(event.position().y()))
                self._selected_row = idx
                self.viewport().update()
                if self.on_row_selected is not None:
                    self.on_row_selected(idx)
            return False
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx, dy):
        """スクロール時に viewport を再描画する（座標変換は自前で行うため）。"""
        self.viewport().update()

    def resizeEvent(self, event):
        """viewport 幅が変わった場合に行高キャッシュを無効化し、スクロールバーを更新する。"""
        super().resizeEvent(event)
        new_w = self.viewport().width()
        if new_w != self._last_vp_width:
            self._invalidate_heights()
            self._last_vp_width = new_w
        self._update_scrollbar()

    def wheelEvent(self, event):
        """マウスホイールスクロール後、末尾近くなら自動スクロールを再開する。"""
        super().wheelEvent(event)
        sb = self.verticalScrollBar()
        self._auto_scroll = (sb.value() >= sb.maximum() - 4)

    # ─── スクロール制御 ────────────────────────────────────────────────────────

    def _on_slider_pressed(self):
        """ユーザーがスクロールバーをドラッグ開始 → 自動スクロールを停止。"""
        self._auto_scroll = False

    def _on_slider_released(self):
        """ユーザーがスクロールバーを離したとき、末尾近くなら自動スクロールを再開。"""
        sb = self.verticalScrollBar()
        if sb.value() >= sb.maximum() - 4:
            self._auto_scroll = True

    # ─── 高さキャッシュ ───────────────────────────────────────────────────────

    def _invalidate_heights(self) -> None:
        """全行の行高キャッシュを無効化する。"""
        for row in self._rows:
            row.cached_h = -1

    def _make_name_font(self) -> QFont:
        f = QFont()
        f.setPointSize(max(7, self._font_size_name))
        return f

    def _make_body_font(self) -> QFont:
        f = QFont()
        f.setPointSize(max(7, self._font_size_body))
        return f

    def _icon_offset(self, author) -> int:
        """アイコン描画時の左オフセット。icon_visible=False またはシステムメッセージなら 0。"""
        return (_ICON_SIZE + _ICON_MARGIN) if (self._icon_visible and author) else 0

    def _compute_row_height(self, row: _RowData, vp_width: int) -> int:
        """行の高さを返す（キャッシュ済みなら直接返す、未計算なら計算してキャッシュする）。"""
        if row.cached_h >= 0:
            return row.cached_h

        icon_off = self._icon_offset(row.author)
        inner_w  = max(vp_width - 16 - icon_off, 100)  # 左右マージン + アイコン幅を除いた幅

        if self._display_rows >= 2 and row.body:
            fn   = self._make_name_font()
            fb   = self._make_body_font()
            fm_n = QFontMetrics(fn)
            fm_b = QFontMetrics(fb)
            name_h = fm_n.height()
            body_h = fm_b.boundingRect(
                0, 0, inner_w, 10000,
                int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap),
                row.body,
            ).height()
            h = name_h + _NAME_BODY_GAP + body_h + _VPAD * 2
        else:
            fb = self._make_body_font()
            h  = QFontMetrics(fb).height() + _VPAD * 2

        if icon_off:
            h = max(h, _ICON_SIZE + _VPAD * 2)

        row.cached_h = h
        return h

    def _total_height(self, vp_width: int) -> int:
        return sum(self._compute_row_height(r, vp_width) for r in self._rows)

    def _row_at_y(self, click_y: int) -> int | None:
        """viewport 座標 click_y 位置の行インデックスを返す（なければ None）。"""
        vp_w     = self.viewport().width()
        scroll_y = self.verticalScrollBar().value()
        y = 0
        for i, row in enumerate(self._rows):
            row_h  = self._compute_row_height(row, vp_w)
            draw_y = y - scroll_y
            if draw_y <= click_y < draw_y + row_h:
                return i
            y += row_h
        return None

    @property
    def selected_row_index(self) -> int | None:
        """現在選択中の行インデックス（未選択なら None）。"""
        return self._selected_row

    def deselect(self) -> None:
        """選択を解除する。"""
        self._selected_row = None
        self.viewport().update()

    def _update_scrollbar(self) -> None:
        vp_h  = self.viewport().height()
        vp_w  = self.viewport().width()
        total = self._total_height(vp_w)
        sb    = self.verticalScrollBar()
        sb.setRange(0, max(0, total - vp_h))
        sb.setPageStep(vp_h)
        sb.setSingleStep(max(1, vp_h // 10))

    # ─── プロフィール画像フェッチ ─────────────────────────────────────────────

    def _fetch_icon(self, url: str) -> None:
        """プロフィール画像を非同期でダウンロードする（未フェッチの場合のみ）。"""
        if url in self._icon_pixmap_cache:
            return  # 既にキャッシュ済み（成功/失敗問わず）
        self._icon_pixmap_cache[url] = None  # フェッチ中マーク（None = ロード待ち）
        req = QNetworkRequest(QUrl(url))
        reply = self._nam.get(req)
        reply.finished.connect(lambda r=reply, u=url: self._on_icon_reply(r, u))

    def _on_icon_reply(self, reply: QNetworkReply, url: str) -> None:
        """画像ダウンロード完了 → キャッシュに格納して再描画をトリガーする。"""
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                pm = QPixmap()
                if pm.loadFromData(reply.readAll()) and not pm.isNull():
                    self._icon_pixmap_cache[url] = pm
                    self.viewport().update()  # アイコン差し替えのための再描画
        except Exception:
            pass
        finally:
            reply.deleteLater()

    # ─── 描画 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _author_icon_color(author: str) -> QColor:
        """著者名から決定論的に色を生成する（同じ名前 → 常に同じ色）。"""
        digest = hashlib.md5(author.encode("utf-8", errors="replace")).digest()
        hue    = int.from_bytes(digest[:2], "big") % 360
        return QColor.fromHsv(hue, 140, 170)

    def _draw_icon(self, painter: QPainter, rect: QRect,
                   author: str, profile_url: str = "") -> None:
        """
        プロフィール画像アイコンを描画する。

        profile_url が指定されてキャッシュ済み QPixmap がある場合は円形クリップで描画。
        未取得またはロード失敗の場合は著者名の頭文字プレースホルダーにフォールバック。
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── プロフィール画像（キャッシュ済みの場合）──────────────────────────
        if profile_url:
            pm = self._icon_pixmap_cache.get(profile_url)
            if pm is not None and not pm.isNull():
                # 正方形にクロップしてからアイコンサイズへスケール
                src_size = min(pm.width(), pm.height())
                dx = (pm.width()  - src_size) // 2
                dy = (pm.height() - src_size) // 2
                pm_sq = pm.copy(dx, dy, src_size, src_size)
                pm_sc = pm_sq.scaled(
                    rect.width(), rect.height(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                # 円形クリップパスを適用してから描画
                clip_path = QPainterPath()
                clip_path.addEllipse(QRectF(rect))
                painter.setClipPath(clip_path)
                painter.drawPixmap(rect, pm_sc)
                painter.restore()
                return

        # ── フォールバック: 頭文字プレースホルダー ─────────────────────────────
        color = self._author_icon_color(author)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)
        initial = (author[:1] or "?").upper()
        painter.setPen(QColor("#FFFFFF"))
        icon_font = QFont()
        icon_font.setPointSize(max(7, rect.height() // 2))
        icon_font.setBold(True)
        painter.setFont(icon_font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initial)
        painter.restore()

    def _paint_content(self, painter: QPainter) -> None:
        """viewport の全コンテンツを描画する（visible 範囲のみ実描画）。"""
        vp       = self.viewport()
        vp_w     = vp.width()
        vp_h     = vp.height()
        scroll_y = self.verticalScrollBar().value()

        # ベース背景を塗りつぶす
        painter.fillRect(0, 0, vp_w, vp_h, _BG_BASE)

        if not self._rows:
            return

        # paint 呼び出し単位でフォント・FM を一度だけ生成（行ごとの再生成を避ける）
        fn   = self._make_name_font()
        fb   = self._make_body_font()
        fm_n = QFontMetrics(fn)
        fm_b = QFontMetrics(fb)

        y = 0  # 全体座標系での各行 top
        for i, row in enumerate(self._rows):
            row_h  = self._compute_row_height(row, vp_w)
            draw_y = y - scroll_y  # viewport 座標系での top

            if draw_y + row_h < 0:
                # viewport より上にある行はスキップ
                y += row_h
                continue
            if draw_y > vp_h:
                # viewport より下に出たら以降は描画不要
                break

            # ── 行背景 ─────────────────────────────────────────────────────
            if i == self._selected_row:
                painter.fillRect(0, draw_y, vp_w, row_h, _SEL_COLOR)
            elif row.bg_color:
                painter.fillRect(0, draw_y, vp_w, row_h, row.bg_color)

            # ── 行区切り線 ─────────────────────────────────────────────────
            painter.setPen(_SEP_COLOR)
            painter.drawLine(0, draw_y + row_h - 1, vp_w, draw_y + row_h - 1)

            # ── アイコン ───────────────────────────────────────────────────
            icon_off = self._icon_offset(row.author)
            if icon_off and row.author:
                icon_y = draw_y + max(0, (row_h - _ICON_SIZE) // 2)
                self._draw_icon(
                    painter,
                    QRect(4, icon_y, _ICON_SIZE, _ICON_SIZE),
                    row.author,
                    row.profile_url,
                )

            # ── テキスト ───────────────────────────────────────────────────
            painter.setPen(row.fg_color)
            text_x   = 8 + icon_off
            text_w   = vp_w - text_x - 8
            text_top = draw_y + _VPAD

            if self._display_rows >= 2 and row.body:
                # 2行モード: header（時刻+投稿者名）を 1行目、body を 2行目
                painter.setFont(fn)
                painter.drawText(text_x, text_top + fm_n.ascent(), row.header)

                painter.setFont(fb)
                body_rect = QRect(
                    text_x,
                    text_top + fm_n.height() + _NAME_BODY_GAP,
                    text_w,
                    row_h - fm_n.height() - _NAME_BODY_GAP - _VPAD * 2,
                )
                painter.drawText(
                    body_rect,
                    int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignTop) |
                    int(Qt.TextFlag.TextWordWrap),
                    row.body,
                )
            else:
                # 1行モード: header に body が含まれている（または body が空）
                display = row.header if not row.body else f"{row.header}: {row.body}"
                painter.setFont(fb)
                painter.drawText(
                    text_x,
                    draw_y + (row_h - fm_b.height()) // 2 + fm_b.ascent(),
                    display,
                )

            y += row_h
