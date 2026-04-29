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

from PySide6.QtCore import Qt, Signal, QTimer, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QWidget

from design_models import DesignSettings

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

    # フラッシュ設定
    _FLASH_COUNT = 3       # 点滅回数
    _FLASH_ON_MS = 60      # 表示時間 (ms)
    _FLASH_OFF_MS = 60     # 非表示時間 (ms)

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

        # --- フラッシュアニメーション ---
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._on_flash_tick)
        self._flash_step: int = 0       # 現在のフラッシュステップ
        self._flash_total: int = 0      # 総ステップ数
        self._flashing: bool = False     # フラッシュ中フラグ

        # --- テキストアウトライン描画 ---
        self._text_color = QColor("#ffd700")       # テキスト塗り色（gold）
        self._outline_color = QColor("#000000")    # アウトライン色
        self._outline_width: float = 2.0           # アウトライン幅

        # i022: 被りなし連続抽選用 prefix ("N/M回目: " など)
        self._result_prefix: str = ""

        # 連続抽選全結果サマリー表示モード
        self._summary_mode: bool = False
        self._base_stylesheet: str = ""

        # i069: ポインター操作モード
        self._pointer_move_mode: bool = False
        self._current_winner: str = ""

        # v0.6.1: 連携実行時の投稿者名（結果表示にのみ併記、空なら非表示）
        self._link_author: str = ""

    # ================================================================
    #  公開 API
    # ================================================================

    def set_result_prefix(self, prefix: str):
        """次の show_result に付加するプレフィックスを設定する。

        i022: 被りなし連続抽選で "N/M回目: " のような前置きを表示するために使用。
        空文字列を設定するとプレフィックスなし（通常状態）に戻る。
        """
        self._result_prefix = prefix

    def show_result(self, winner: str):
        """結果テキストを表示し、安定表示する。"""
        self._stop_auto_timer()
        self._stop_flash()
        self._current_winner = winner
        self._update_text()
        # v0.6.1: 内容に合わせて widget サイズを設定（中央再配置含む）
        self._fit_to_content()
        self.show()
        self.raise_()
        self._start_auto_timer_if_needed()

    def update_provisional(self, winner: str):
        """ポインター操作中に仮結果テキストを更新する（タイマーはリセットしない）。"""
        if winner == self._current_winner:
            return
        self._current_winner = winner
        self._update_text()
        self._fit_to_content()

    def set_pointer_move_mode(self, active: bool):
        """ポインター操作モードの状態を保持する（i069/i070: 表示には影響しない）。"""
        self._pointer_move_mode = active

    def set_link_author(self, author: str):
        """v0.6.1: 連携実行時の投稿者名を結果表示に併記する。
        空文字なら表示なし。"""
        self._link_author = (author or "").strip()
        if self.isVisible():
            self._update_text()
            self._fit_to_content()

    def _fit_to_content(self):
        """v0.6.1: 内容に合わせた widget サイズを設定し、親の中央へ配置する。

        手順:
        1. 文字列を計測し、最長 1 行が収まる必要幅を計算
        2. 親 (RoulettePanel) 幅 - 余白 を上限としてキャップ
        3. その幅で word-wrap した行数分の高さを確保
        4. resize() で widget サイズを上書き
        5. move() で親の中央へ直接配置（update_position は使わない）
        """
        text = self.text()
        if not text:
            return
        parent = self.parentWidget()
        if parent is None:
            return
        fm = QFontMetrics(self.font())
        m = self.contentsMargins()

        pw, ph = parent.width(), parent.height()
        max_panel_w = max(160, pw - 24)
        inner_max_w = max_panel_w - m.left() - m.right() - 16

        # 行ごとに wrap
        wrapped: list[str] = []
        for raw in text.split("\n"):
            if fm.horizontalAdvance(raw) <= inner_max_w:
                wrapped.append(raw)
            else:
                wrapped.extend(self._wrap_text_to_width(raw, fm, inner_max_w))

        # 必要幅 = 最長 wrap 行 + 余白、ただし上限は max_panel_w
        longest = max((fm.horizontalAdvance(l) for l in wrapped), default=0)
        new_w = min(max_panel_w, longest + m.left() + m.right() + 16)
        new_h = fm.height() * len(wrapped) + m.top() + m.bottom() + 8

        # サイズを直接設定し、中央配置
        self.resize(new_w, new_h)
        lx = max(0, (pw - new_w) // 2)
        ly = max(10, (ph - new_h) // 2)
        self.move(lx, ly)

    def _update_text(self):
        """現在の winner に基づいてテキストを更新する（i070: 操作中表示は不要）。"""
        display = (self._result_prefix + self._current_winner
                   if self._result_prefix else self._current_winner)
        if self._link_author:
            # v0.6.1: 連携投稿者がいる場合は 2 段表示
            # 1 段目: 投稿者名 / 2 段目: 通常結果
            # 表示幅は親 (RoulettePanel) のほぼ全幅まで広げ、
            # 見切れる場合のみ改行する
            self.setWordWrap(True)
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            parent = self.parentWidget()
            if parent is not None:
                margin = 24  # 左右の余白
                self.setMaximumWidth(max(160, parent.width() - margin))
            self.setText(
                f"  {self._link_author}  \n"
                f"  \U0001f3af {display}  "
            )
        else:
            self.setWordWrap(False)
            # 既定はサイズ自動調整（最大幅制限を解除）
            self.setMaximumWidth(16777215)
            self.setText(f"  \U0001f3af {display}  ")

    def show_summary(self, results: list):
        """連続抽選の全結果サマリーをオーバーレイに表示する（最終回完了時に使用）。

        results: [(step, winner), ...] 形式のリスト。
        """
        self._stop_auto_timer()
        self._stop_flash()
        self._summary_mode = True
        lines = ["\U0001f3c6 全結果:"]
        for step, winner in results:
            lines.append(f"  {step}回目: {winner}")
        self.setText("\n".join(lines))
        self.setWordWrap(True)
        self.setStyleSheet(
            f"color: {self._text_color.name()}; "
            f"background-color: rgba(0, 0, 0, 200); "
            f"border-radius: 8px; padding: 10px 18px;"
        )
        self.show()
        self.raise_()
        self.update_position()
        self._start_auto_timer_if_needed()

    def dismiss(self):
        """overlay を確実に閉じる。タイマーも停止する。

        spin 開始時に RoulettePanel から呼ばれ、残留を防止する。
        パネル面クリックで閉じた場合も closed を emit する。
        """
        self._stop_flash()
        self._stop_auto_timer()
        self._force_auto_close = False
        self._force_hold_sec = None
        self._pointer_move_mode = False
        self._current_winner = ""
        if self._summary_mode:
            self._summary_mode = False
            self.setWordWrap(False)
            if self._base_stylesheet:
                self.setStyleSheet(self._base_stylesheet)
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
        if self._summary_mode:
            # サマリーモード: 幅を固定してワードラップで高さを計算
            lw = min(int(cw * 0.75), 420)
            lh = self.heightForWidth(lw) + 24
            if lh <= 24:
                lh = 120  # fallback
            lx = (cw - lw) // 2
            ly = max(10, (ch - lh) // 2)
            self.setGeometry(lx, ly, lw, lh)
        else:
            # v0.6.1: 通常結果は _fit_to_content() でサイズ確定済みのため、
            # サイズは触らず中央配置のみ更新する（adjustSize で上書きしない）
            self._fit_to_content()

    def apply_style(self, design: DesignSettings):
        """デザイン連動の配色を適用する。"""
        # テキスト色は transparent にし、paintEvent でアウトライン付き描画する
        self._text_color = QColor(design.gold)
        self._base_stylesheet = (
            f"color: transparent; "
            f"background-color: rgba(0, 0, 0, 180); "
            f"border-radius: 8px; padding: 8px 16px;"
        )
        self.setStyleSheet(self._base_stylesheet)

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
    #  フラッシュアニメーション
    # ================================================================

    def _start_flash(self):
        """フラッシュ演出を開始する。

        ON/OFF を _FLASH_COUNT 回繰り返し、最後に安定表示 + 自動クローズ開始。
        ステップ: 0=OFF, 1=ON, 2=OFF, 3=ON, 4=OFF, 5=ON(最終) → 安定表示
        総ステップ = _FLASH_COUNT * 2
        偶数ステップ=OFF、奇数ステップ=ON、最終ステップ(奇数)=安定表示へ遷移
        """
        self._flash_step = 0
        self._flash_total = self._FLASH_COUNT * 2
        self._flashing = True
        # 最初のステップ: 一瞬消す
        self.setVisible(False)
        self._flash_timer.start(self._FLASH_OFF_MS)

    def _stop_flash(self):
        """フラッシュ演出を中断する。"""
        if self._flash_timer.isActive():
            self._flash_timer.stop()
        self._flashing = False
        self._flash_step = 0

    def _on_flash_tick(self):
        """フラッシュの1ステップを処理する。"""
        self._flash_step += 1
        if self._flash_step >= self._flash_total:
            # フラッシュ完了 → 安定表示
            self._flashing = False
            self.setVisible(True)
            self.raise_()
            self._start_auto_timer_if_needed()
            return
        # 偶数=OFF、奇数=ON
        if self._flash_step % 2 == 0:
            self.setVisible(False)
            self._flash_timer.start(self._FLASH_OFF_MS)
        else:
            self.setVisible(True)
            self.raise_()
            self._flash_timer.start(self._FLASH_ON_MS)

    # ================================================================
    #  描画（テキストアウトライン）
    # ================================================================

    @staticmethod
    def _wrap_text_to_width(line: str, fm: QFontMetrics, max_w: float) -> list[str]:
        """v0.6.1: 1 行を最大幅で文字単位 wrap する（日本語混在対応）。"""
        if max_w <= 0 or fm.horizontalAdvance(line) <= max_w:
            return [line]
        out: list[str] = []
        cur = ""
        for ch in line:
            test = cur + ch
            if fm.horizontalAdvance(test) > max_w and cur:
                out.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            out.append(cur)
        return out

    def _compute_wrapped_lines(self) -> list[str]:
        """現在の text と width から改行 + word-wrap した行リストを返す。"""
        text = self.text()
        if not text:
            return []
        fm = QFontMetrics(self.font())
        margins = self.contentsMargins()
        max_w = max(0.0, self.width() - margins.left() - margins.right() - 16)
        wrapped: list[str] = []
        for raw in text.split("\n"):
            wrapped.extend(self._wrap_text_to_width(raw, fm, max_w))
        return wrapped

    def paintEvent(self, event):
        """QLabel の描画後にアウトライン付きテキストを重ねて描画する。"""
        # QLabel のデフォルト描画（背景・ボーダー。テキストは transparent で見えない）
        super().paintEvent(event)

        # サマリーモードでは stylesheet の色で QLabel がそのまま描画するため、path 処理不要
        if self._summary_mode:
            return

        text = self.text()
        if not text:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # テキスト描画領域（padding を考慮）
        margins = self.contentsMargins()
        rect = QRectF(
            margins.left(), margins.top(),
            self.width() - margins.left() - margins.right(),
            self.height() - margins.top() - margins.bottom(),
        )

        # v0.6.1: 改行対応 + 自動 word-wrap
        # _fit_to_content() で widget サイズが内容に合わせ済みのため、
        # 描画は上端からシンプルに開始する（中央配置にしない）
        font = self.font()
        fm = QFontMetrics(font)
        lines = self._compute_wrapped_lines()
        line_h = fm.height()

        # 1 行目のベースライン y = padding 上端 + ascent
        y_top = rect.y() + fm.ascent() + 2

        outline_pen = QPen(
            self._outline_color, self._outline_width,
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )

        for i, line in enumerate(lines):
            if not line:
                continue
            text_width = fm.horizontalAdvance(line)
            x = rect.x() + (rect.width() - text_width) / 2.0
            y = y_top + i * line_h

            path = QPainterPath()
            path.addText(x, y, font, line)

            # アウトライン（黒縁）
            p.setPen(outline_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            # 塗り（テキスト色）
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._text_color)
            p.drawPath(path)

        p.end()

    # ================================================================
    #  イベント
    # ================================================================

    def mousePressEvent(self, event: QMouseEvent):
        """左クリック -> close_mode に応じて閉じる。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._close_mode in (CLOSE_CLICK, CLOSE_BOTH):
                self._stop_flash()
                self._stop_auto_timer()
                self._force_auto_close = False
                self._force_hold_sec = None
                self.hide()
                self.closed.emit()
