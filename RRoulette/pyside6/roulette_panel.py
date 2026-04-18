"""
PySide6 プロトタイプ — ルーレットパネル

ルーレット描画と操作を一体化した独立パネル。
メインウィンドウ内で自由に移動・リサイズできる。

将来のマルチルーレット化では、このクラスを複数インスタンス化する。
各 RoulettePanel は自身の segments、spin 状態を持ち、
項目設定パネルは「アクティブな RoulettePanel」を編集する形にする。

責務:
  - WheelWidget の表示管理
  - SpinController の保持・制御
  - ResultOverlay の管理
  - パネル内マウス操作（spin 開始、ポインタードラッグ、パネル移動）
  - パネルリサイズ（右下つまみ）

マウス操作の優先順位:
  1. ポインター上 → ポインタードラッグ
  2. ホイール円内 → spin 開始
  3. それ以外の空き領域 → パネル移動
"""

from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QSize, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QFontMetrics
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from bridge import (
    DesignSettings, WHEEL_OUTER_MARGIN, MIN_R, POINTER_OVERHANG,
)
from wheel_widget import WheelWidget
from spin_controller import SpinController
from result_overlay import ResultOverlay
from panel_widgets import _PanelGrip


# ホイール + ポインター + 余白を含むパネル最小サイズ
# = 2 * (MIN_R + WHEEL_OUTER_MARGIN) + grip余白
_ROULETTE_MIN = 2 * (MIN_R + WHEEL_OUTER_MARGIN) + _PanelGrip._GRIP_SIZE
_ROULETTE_MIN_W = max(280, _ROULETTE_MIN)
_ROULETTE_MIN_H = max(280, _ROULETTE_MIN)

# i341: メインウィンドウ移動バー（進入禁止領域）の高さ
# _MainWindowDragBar._BAR_HEIGHT と同値。循環インポートを避けるため定数として持つ。
_MW_DRAG_BAR_H = 20


class _LogOverlay(QWidget):
    """ログ前面表示オーバーレイ（RoulettePanel の子として最前面に配置）。

    WheelWidget の内部描画ではなく、RoulettePanel のウィジェット階層で最前面に
    ログを描画することで、インスタンスラベルや選択ハンドルよりも前面に見せる。
    i343: ログ前面表示 ON のとき使用する。
    """

    _LOG_MARGIN_X = 8
    _LOG_MARGIN_Y = 30  # i347: i346 の誤修正を戻す。z-order は raise_() で管理

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # i346: システム背景が塗り潰されないよう明示的に抑止する
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._entries: list[tuple[str, str]] = []
        self._timestamp: bool = False
        self._design = None
        self.hide()

    def refresh(self, entries, timestamp: bool, design, visible: bool, on_top: bool):
        """ログ状態に合わせて表示を更新する。"""
        self._entries = list(entries)
        self._timestamp = timestamp
        self._design = design
        show = visible and on_top and bool(entries)
        self.setVisible(show)
        if show:
            # raise_() 不要: 作成順で z-order 確定 (i348)
            self.update()

    def paintEvent(self, event):
        if not self._entries or self._design is None:
            return
        d = self._design
        log_font = QFont(d.fonts.log_family or "Meiryo", d.log.font_size)
        fm = QFontMetrics(log_font)
        line_h = fm.height() + 2
        padding = 6
        mx = self._LOG_MARGIN_X
        my = self._LOG_MARGIN_Y

        lines = []
        for ts, text in self._entries:
            if self._timestamp:
                lines.append(f"[{ts}] {text}")
            else:
                lines.append(text)

        max_w = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
        box_w = max_w + padding * 2
        box_h = line_h * len(lines) + padding * 2

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(d.log.box_bg_color)
        bg.setAlpha(180)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(mx, my, box_w, box_h), 4, 4)

        painter.setFont(log_font)
        text_color = QColor(d.log.text_color)
        shadow_color = QColor(d.log.shadow_color)
        for i, ln in enumerate(lines):
            y = my + padding + (i + 1) * line_h - fm.descent()
            x = mx + padding
            painter.setPen(shadow_color)
            painter.drawText(QPointF(x + 1, y + 1), ln)
            painter.setPen(text_color)
            painter.drawText(QPointF(x, y), ln)

        painter.end()


class _GraphButton(QWidget):
    """グラフボタン（左下コーナー）。クリックで graph_requested を発火する。"""

    _W = 42
    _H = 16

    def __init__(self, panel: "RoulettePanel", parent=None):
        super().__init__(parent)
        self._panel = panel
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 70))
        painter.drawRoundedRect(0, 0, self._W, self._H, 3, 3)
        painter.setPen(QColor(255, 255, 255, 210))
        painter.setFont(QFont("Meiryo", 7))
        painter.drawText(0, 0, self._W, self._H,
                         Qt.AlignmentFlag.AlignCenter, "グラフ")
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._panel._toggle_graph_panel()  # i389: in-panel グラフ切替
            event.accept()
        else:
            event.ignore()


class _SelectionHandle(QWidget):
    """小さな選択ハンドル（クリックで active 切替、ドラッグでパネル移動）。

    RoulettePanel の左上コーナーに配置する。
    クリック → activate_requested を発火（スピンしない）
    ドラッグ → パネル全体を移動
    """
    _SIZE = 20

    def __init__(self, panel: QFrame, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._drag_start = QPoint()
        self._panel_start = QPoint()
        self._dragging = False
        self._drag_pending = False
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        # i427: active 時はアクティブカラー（水色）で強調
        is_active = getattr(self._panel, "_is_active", False)
        color = QColor(79, 195, 247, 220) if is_active else QColor(255, 255, 255, 120)
        painter.setBrush(color)
        # 3x3 グリッドの点を描画
        dot_r = 2
        for row in range(3):
            for col in range(3):
                cx = 4 + col * 6
                cy = 4 + row * 6
                painter.drawEllipse(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._panel.activate_requested.emit(self._panel.roulette_id)
            self._drag_start = event.globalPosition().toPoint()
            self._panel_start = self._panel.pos()
            self._drag_pending = True
            self._dragging = False
            # i343: 非入力領域クリック後に Space が前チェックボックスへ入るのを防ぐ
            w = self.window()
            if w:
                w.setFocus(Qt.FocusReason.MouseFocusReason)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pending or self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            if self._drag_pending and (abs(delta.x()) > 4 or abs(delta.y()) > 4):
                self._dragging = True
                self._drag_pending = False
            if self._dragging:
                new_pos = self._panel_start + delta
                parent = self._panel.parentWidget()
                if parent:
                    new_x = max(0, min(new_pos.x(), parent.width() - self._panel.width()))
                    # i341: 移動バー領域（_MW_DRAG_BAR_H より上）への侵入禁止
                    new_y = max(_MW_DRAG_BAR_H, min(new_pos.y(), parent.height() - self._panel.height()))
                    self._panel.move(new_x, new_y)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pending = False
        self._dragging = False
        event.accept()


class _TitlePlate(QWidget):
    """タイトルプレート（multi 時のルーレット名表示と選択/移動導線）。

    i427: クリックで active 切替、ドラッグでパネル移動。
    active 状態に合わせて背景色を変化させる。
    title plate 非表示時でも _SelectionHandle が選択導線を担保する。
    """

    _H = 18

    def __init__(self, panel: "RoulettePanel", parent=None):
        super().__init__(parent)
        self._panel = panel
        self._text = ""
        self._drag_start = QPoint()
        self._panel_start = QPoint()
        self._dragging = False
        self._drag_pending = False
        self.setFixedHeight(self._H)
        self.setMinimumWidth(60)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.hide()

    def set_text(self, text: str):
        """表示テキストを設定し、幅を自動調整する。"""
        self._text = text
        fm = QFontMetrics(QFont("Meiryo", 8))
        w = max(60, fm.horizontalAdvance(text) + 16)
        self.setFixedWidth(w)
        self.update()

    def paintEvent(self, event):
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_active = getattr(self._panel, "_is_active", False)
        bg = QColor(79, 195, 247, 180) if is_active else QColor(0, 0, 0, 150)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(0, 0, self.width(), self._H, 4, 4)
        painter.setFont(QFont("Meiryo", 8))
        painter.setPen(QColor(255, 255, 255, 230))
        painter.drawText(0, 0, self.width(), self._H,
                         Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._panel.activate_requested.emit(self._panel.roulette_id)
            self._drag_start = event.globalPosition().toPoint()
            self._panel_start = self._panel.pos()
            self._drag_pending = True
            self._dragging = False
            w = self.window()
            if w:
                w.setFocus(Qt.FocusReason.MouseFocusReason)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pending or self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            if self._drag_pending and (abs(delta.x()) > 4 or abs(delta.y()) > 4):
                self._dragging = True
                self._drag_pending = False
            if self._dragging:
                new_pos = self._panel_start + delta
                parent = self._panel.parentWidget()
                if parent:
                    new_x = max(0, min(new_pos.x(), parent.width() - self._panel.width()))
                    new_y = max(_MW_DRAG_BAR_H, min(new_pos.y(), parent.height() - self._panel.height()))
                    self._panel.move(new_x, new_y)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pending = False
        self._dragging = False
        event.accept()


class RoulettePanel(QFrame):
    """独立パネルとしてのルーレット。

    Signals:
        spin_requested: spin 開始が要求された
        spin_finished(str, int): spin が完了した (winner, seg_idx)
        pointer_angle_changed(float): ポインター角度がドラッグ中に変更された
        pointer_angle_committed: ポインタードラッグ完了（保存タイミング）
        geometry_changed: パネルの位置/サイズが変わった
    """

    spin_requested = Signal()
    spin_finished = Signal(str, int)
    pointer_angle_changed = Signal(float)
    pointer_angle_committed = Signal()
    geometry_changed = Signal()
    activate_requested = Signal(str)
    graph_requested = Signal(str)        # (roulette_id): グラフを開く要求（後方互換）
    in_panel_graph_opened = Signal(str)  # i389: in-panel グラフ表示時に emit
    window_drag_delta = Signal(QPoint)   # roulette_only_mode: ウィンドウ移動要求
    window_resize_needed = Signal(QSize) # roulette_only_mode: ウィンドウリサイズ要求

    _MIN_W = _ROULETTE_MIN_W
    _MIN_H = _ROULETTE_MIN_H

    def __init__(self, design: DesignSettings, sound_manager, *,
                 roulette_id: str = "default", parent=None):
        super().__init__(parent)
        self._roulette_id = roulette_id
        self._design = design
        self._transparent = False
        self._apply_panel_background()
        self.setMinimumSize(self._MIN_W, self._MIN_H)

        # ── WheelWidget（パネル全体に配置） ──
        self._wheel = WheelWidget(self)

        # ── ログ前面オーバーレイ（i348: _result_overlay より先に作成して z-order 確定）──
        # 作成順 = z-order: _wheel < _log_overlay < _result_overlay
        # _log_overlay は wheel の上・result の下に固定。raise_() は不要。
        self._log_overlay = _LogOverlay(self)
        self._wheel.log_changed.connect(self._refresh_log_overlay)

        # ── スピン制御 ──
        self._spin_ctrl = SpinController(
            self._wheel, sound_manager=sound_manager, parent=self
        )
        self._spin_ctrl.spin_finished.connect(self._on_spin_finished)

        # ── 結果オーバーレイ（i348: _log_overlay より後に作成 → 常に上に位置）──
        self._result_overlay = ResultOverlay(self)
        self._result_overlay.apply_style(design)

        # ── リサイズグリップ ──
        self._grip = _PanelGrip(
            self, design, mode="panel",
            min_w=self._MIN_W, min_h=self._MIN_H,
            parent=self,
        )

        # ── インスタンス番号ラベル（マルチ時のみ表示） ──
        self._instance_label = QLabel(self)
        self._instance_label.setFont(QFont("Meiryo", 8, QFont.Weight.Bold))
        self._instance_label.setStyleSheet(
            f"color: {design.text}; background-color: rgba(0, 0, 0, 120);"
            f" border-radius: 3px; padding: 1px 4px;"
        )
        self._instance_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._instance_label.hide()  # 単窓時は非表示

        # ── パネル前後関係 ──
        self.pinned_front = False  # True: 通常パネルより常に上に表示

        # ── ドラッグ状態 ──
        self._dragging_pointer = False
        self._dragging_panel = False
        self._drag_pending = False      # press 後、drag か click かの判定待ち
        self._press_zone = "outside"    # press 時のヒットゾーン
        self._panel_drag_start = QPoint()
        self._panel_start_pos = QPoint()

        # ── ルーレット以外非表示モード ──
        self._roulette_only_mode: bool = False

        # ── アクティブ状態 ──
        self._is_active = False

        # ── 選択ハンドル（左上コーナー） ──
        self._selection_handle = _SelectionHandle(self, parent=self)
        self._selection_handle.move(2, 2)
        self._selection_handle.show()

        # ── タイトルプレート（multi 時のルーレット名 / 選択・移動導線）──
        # i427: デフォルト非表示。set_title() で表示制御する。
        self._title_plate = _TitlePlate(self, parent=self)

        # ── グラフボタン（左下コーナー） ──
        self._graph_btn = _GraphButton(self, parent=self)
        self._graph_btn.show()

        # ── in-panel グラフ（i389: 遅延生成） ──
        self._graph_panel = None  # type: GraphWidget | None

        # ── インスタンス番号の記憶（i391: グラフ非表示後の復帰用） ──
        self._instance_label_number: int | None = None

    # ================================================================
    #  公開プロパティ
    # ================================================================

    @property
    def roulette_id(self) -> str:
        return self._roulette_id

    @property
    def wheel(self) -> WheelWidget:
        return self._wheel

    @property
    def spin_ctrl(self) -> SpinController:
        return self._spin_ctrl

    @property
    def result_overlay(self) -> ResultOverlay:
        return self._result_overlay

    @property
    def roulette_only_mode(self) -> bool:
        return self._roulette_only_mode

    @roulette_only_mode.setter
    def roulette_only_mode(self, value: bool):
        self._roulette_only_mode = value

    # ================================================================
    #  設定適用
    # ================================================================

    def apply_settings(self, settings, design):
        """AppSettings と DesignSettings を WheelWidget に一括配布する。"""
        self._wheel.set_design(design)
        self._wheel.set_text_mode(settings.text_size_mode, settings.text_direction)
        self._wheel.set_donut_hole(settings.donut_hole)
        self._wheel.set_pointer_angle(settings.pointer_angle)
        self._wheel._spin_direction = settings.spin_direction

    def set_segments(self, segments):
        """ルーレットのセグメントを設定する。"""
        self._wheel.set_segments(segments)

    def set_instance_label(self, number: int | None):
        """インスタンス番号ラベルを設定する。

        Args:
            number: 表示する番号。None または 0 以下なら非表示。
        """
        self._instance_label_number = number  # i391: 復帰用に記憶
        if number is not None and number > 0:
            self._instance_label.setText(f"#{number}")
            self._instance_label.adjustSize()
            self._instance_label.move(6, 6)
            # i391: グラフ表示中は見え残りを避けるため show しない
            if self._graph_panel is None or not self._graph_panel.isVisible():
                self._instance_label.show()
                self._instance_label.raise_()
            # _log_overlay.raise_() 削除: z-order は作成順で管理 (i348)
        else:
            self._instance_label.hide()

    def update_design(self, design: DesignSettings):
        """デザイン変更時にパネル全体の配色を更新する。"""
        self._design = design
        self._apply_panel_background()
        self._wheel.set_design(design)
        self._result_overlay.apply_style(design)
        self._grip.update_design(design)
        self._instance_label.setStyleSheet(
            f"color: {design.text}; background-color: rgba(0, 0, 0, 120);"
            f" border-radius: 3px; padding: 1px 4px;"
        )

    def set_active(self, is_active: bool):
        """アクティブ状態を設定する。視覚的な強調表示を更新する。"""
        if self._is_active == is_active:
            return
        self._is_active = is_active
        self.update()
        # i427: ハンドル・タイトルプレートの外観も追従する
        self._selection_handle.update()
        self._title_plate.update()

    def set_title(self, label: str | None):
        """タイトルプレートの表示テキストを設定する（i427）。

        multi 時に呼ばれ、ルーレット名をパネル上部中央に表示する。
        None または空文字なら非表示にする。
        """
        if label:
            self._title_plate.set_text(label)
            self._title_plate.show()
            self._reposition_title_plate()
            self._title_plate.raise_()
        else:
            self._title_plate.hide()

    def _reposition_title_plate(self):
        """タイトルプレートをパネル上部中央に配置する（i427）。"""
        if not self._title_plate.isVisible():
            return
        tw = self._title_plate.width()
        # 選択ハンドル（左上 _SIZE×_SIZE）と重ならない最小 x
        min_x = _SelectionHandle._SIZE + 4
        x = (self.width() - tw) // 2
        x = max(min_x, x)
        x = min(x, max(min_x, self.width() - tw - 2))
        self._title_plate.move(x, 2)

    def set_transparent(self, enabled: bool):
        """透過モードを設定する。

        パネル自身の背景描画と、内部 WheelWidget の透過モードを連動させる。
        透過 ON のときはパネル QFrame 自身の背景を transparent にし、
        WheelWidget も背景を描かなくなるため、メインウィンドウの
        WA_TranslucentBackground と組み合わせて OBS 透過が成立する。
        """
        self._transparent = enabled
        self._apply_panel_background()
        self._wheel.set_transparent(enabled)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._is_active:
            painter = QPainter(self)
            pen = QPen(QColor(79, 195, 247))  # アクティブカラー（水色）
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(1, 1, self.width() - 2, self.height() - 2)

    def _apply_panel_background(self):
        """現在の透過状態に合わせてパネル背景の StyleSheet を設定する。"""
        if self._transparent:
            # QFrame フレーム描画を無効化し、セレクターなし（インライン相当）で
            # 透明スタイルを設定する。setFrameStyle(NoFrame) は stylesheet の
            # border: none より確実にフレーム枠を消す。
            self.setFrameStyle(QFrame.Shape.NoFrame)
            self.setStyleSheet("background-color: transparent; border: none;")
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        else:
            self.setStyleSheet(
                f"QFrame {{ background-color: {self._design.bg}; }}"
            )
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)

    # ================================================================
    #  スピン
    # ================================================================

    def start_spin(self):
        """スピンを開始する。"""
        if self._spin_ctrl.is_spinning:
            return
        self._result_overlay.dismiss()
        self._spin_ctrl.start_spin()

    def _on_spin_finished(self, winner: str, seg_idx: int):
        # i391: グラフ表示中は結果オーバーレイをグラフ上に重ねない
        if self._graph_panel is None or not self._graph_panel.isVisible():
            self._result_overlay.show_result(winner)
        self.spin_finished.emit(winner, seg_idx)

    # ================================================================
    #  ジオメトリ同期・クランプ
    # ================================================================

    def _sync_wheel(self):
        """パネルサイズに WheelWidget を合わせる。"""
        self._wheel.setGeometry(0, 0, self.width(), self.height())
        self._result_overlay.update_position()
        # i348: ログオーバーレイをパネル全面に広げる。raise_() 不要（作成順で z-order 確定）
        self._log_overlay.setGeometry(0, 0, self.width(), self.height())
        self._refresh_log_overlay()  # i344: ジオメトリ確定後に表示状態を同期
        self._graph_btn.move(2, self.height() - _GraphButton._H - 2)
        self._graph_btn.raise_()
        # i427: タイトルプレートをパネル幅に合わせて再配置
        self._reposition_title_plate()
        # i389/i390: in-panel グラフが表示中なら追従リサイズ + z-order 再整頓
        if self._graph_panel is not None and self._graph_panel.isVisible():
            self._graph_panel.setGeometry(0, 0, self.width(), self.height())
            self._graph_panel.raise_()
            self._grip.raise_()
            self._selection_handle.raise_()
            self._title_plate.raise_()
            self._graph_btn.raise_()

    def _refresh_log_overlay(self):
        """WheelWidget のログ状態をオーバーレイに反映する。"""
        w = self._wheel
        self._log_overlay.refresh(
            entries=w.get_log_entries(),  # i393: フィルタ済み (ts, text) リスト
            timestamp=w._log_timestamp,
            design=w._design,
            visible=w._log_visible,
            on_top=w._log_on_top,
        )

    # ================================================================
    #  in-panel グラフ（i389）
    # ================================================================

    def _toggle_graph_panel(self):
        """in-panel グラフ表示をトグルする。

        初回呼び出し時にグラフウィジェットを遅延生成する。
        表示中なら非表示（ホイール復帰）、非表示なら表示（グラフ前面）。
        """
        from graph_dialog import GraphWidget
        if self._graph_panel is None:
            self._graph_panel = GraphWidget(
                self._design, show_close_btn=True, parent=self
            )
            self._graph_panel.close_requested.connect(self._toggle_graph_panel)
            self._graph_panel.setGeometry(0, 0, self.width(), self.height())
            self._graph_panel.hide()

        if self._graph_panel.isVisible():
            # ── グラフを閉じてホイールへ戻る ──
            self._graph_panel.hide()
            self._wheel.show()
            # i390: ログオーバーレイを元の状態へ復帰させる
            self._refresh_log_overlay()
            # i391: インスタンス番号ラベルを記憶状態で復帰させる
            self.set_instance_label(self._instance_label_number)
        else:
            # ── グラフを表示してホイール側 UI を整理する ──
            # i390: 残留している結果オーバーレイを明示的に退場させる
            self._result_overlay.dismiss()
            # i390: ログオーバーレイを明示的に非表示にする（z-order 依存を解消）
            self._log_overlay.hide()
            # i391: インスタンス番号ラベルを明示的に非表示にする
            self._instance_label.hide()
            # ホイールを非表示
            self._wheel.hide()
            # グラフを全面展開
            self._graph_panel.setGeometry(0, 0, self.width(), self.height())
            self._graph_panel.show()
            self._graph_panel.raise_()
            # i390: リサイズグリップを最前面へ（グラフ表示中もリサイズ可能に）
            self._grip.raise_()
            # 選択ハンドル・グラフボタンを最前面へ
            self._selection_handle.raise_()
            self._graph_btn.raise_()
            self.activate_requested.emit(self._roulette_id)
            self.in_panel_graph_opened.emit(self._roulette_id)

    @property
    def in_panel_graph_widget(self):
        """in-panel グラフウィジェットを返す（未生成の場合は None）。"""
        return self._graph_panel

    def update_in_panel_graph(self, items: list[tuple[str, int, int]],
                               total: int, pattern_name: str):
        """in-panel グラフが表示中ならデータを更新する。"""
        if self._graph_panel is not None and self._graph_panel.isVisible():
            self._graph_panel.update_graph(items, total, pattern_name)

    def _clamp_to_parent(self):
        """パネルをメインウィンドウのクライアント領域内にクランプする。"""
        parent = self.parentWidget()
        if not parent:
            return
        x = max(0, min(self.x(), parent.width() - self.width()))
        # i341: 移動バー領域（_MW_DRAG_BAR_H より上）への侵入禁止
        y = max(_MW_DRAG_BAR_H, min(self.y(), parent.height() - self.height()))
        if x != self.x() or y != self.y():
            self.move(x, y)

    # ================================================================
    #  イベント
    # ================================================================

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_wheel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_wheel()
        self._grip.reposition()
        self._graph_btn.move(2, self.height() - _GraphButton._H - 2)
        self._reposition_title_plate()  # i427: リサイズ追従
        # roulette_only_mode 中はウィンドウが後追いでリサイズするため
        # クランプを先に実行すると位置がずれる。ウィンドウ側で吸収する。
        if not self._roulette_only_mode:
            self._clamp_to_parent()
        self.geometry_changed.emit()
        # roulette_only_mode 時はウィンドウリサイズも要求する
        if self._roulette_only_mode:
            self.window_resize_needed.emit(event.size())

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def mousePressEvent(self, event):
        """パネル内マウス押下。クリックしたパネルを最前面へ。

        ドラッグ挙動:
          - ポインター上でドラッグ開始 → ポインター移動
          - それ以外でドラッグ開始 → パネル全体の移動
        クリック挙動（ドラッグなし、press 位置で判定）:
          - 結果表示中 → 結果表示を閉じる（spin より優先）
          - wheel_face → spin 開始
          - pointer / outside → 何もしない
        """
        self.raise_()
        self.activate_requested.emit(self._roulette_id)
        # i343: 非入力領域クリック後 Space が前のチェックボックスへ入るのを防ぐ
        w = self.window()
        if w:
            w.setFocus(Qt.FocusReason.MouseFocusReason)

        if event.button() == Qt.MouseButton.LeftButton:
            wheel_pos = self._wheel.mapFrom(self, event.pos())
            zone = self._wheel.hit_zone(wheel_pos.x(), wheel_pos.y())

            # ポインター上 → ポインタードラッグ（最優先）
            if not self._spin_ctrl.is_spinning and zone == "pointer":
                self._dragging_pointer = True
                event.accept()
                return

            # それ以外 → ドラッグ待ち（閾値超でパネル移動、未満でクリック判定）
            self._drag_pending = True
            self._dragging_panel = False
            self._press_zone = zone
            self._panel_drag_start = event.globalPosition().toPoint()
            self._panel_start_pos = self.pos()
            event.accept()
            return

        event.accept()

    def mouseMoveEvent(self, event):
        # ポインタードラッグ中
        if self._dragging_pointer:
            wheel_pos = self._wheel.mapFrom(self, event.pos())
            angle = self._wheel.angle_from_pos(wheel_pos.x(), wheel_pos.y())
            self._wheel.set_pointer_angle(angle)
            self.pointer_angle_changed.emit(angle)
            event.accept()
            return

        # パネル移動の判定・実行
        if self._drag_pending or self._dragging_panel:
            delta = event.globalPosition().toPoint() - self._panel_drag_start
            # 閾値を超えたらドラッグ確定
            if self._drag_pending and (abs(delta.x()) > 4 or abs(delta.y()) > 4):
                self._dragging_panel = True
                self._drag_pending = False
                # roulette_only_mode では _panel_start_pos を毎ステップ更新するため
                # ここで起点を現在グローバル位置にリセットする
                if self._roulette_only_mode:
                    self._panel_drag_start = event.globalPosition().toPoint()
            if self._dragging_panel:
                if self._roulette_only_mode:
                    # ウィンドウ移動として委譲
                    cur = event.globalPosition().toPoint()
                    move_delta = cur - self._panel_drag_start
                    self._panel_drag_start = cur
                    self.window_drag_delta.emit(move_delta)
                else:
                    new_pos = self._panel_start_pos + delta
                    parent = self.parentWidget()
                    if parent:
                        new_x = max(0, min(new_pos.x(), parent.width() - self.width()))
                        # i341: 移動バー領域（_MW_DRAG_BAR_H より上）への侵入禁止
                        new_y = max(_MW_DRAG_BAR_H, min(new_pos.y(), parent.height() - self.height()))
                        self.move(new_x, new_y)
            event.accept()
            return

        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # ポインタードラッグ完了
            if self._dragging_pointer:
                self._dragging_pointer = False
                self.pointer_angle_committed.emit()
                event.accept()
                return

            # クリック判定（閾値内で離された = ドラッグにならなかった）
            if self._drag_pending:
                self._drag_pending = False
                zone = self._press_zone
                # 結果表示中 → 閉じる（spin より優先）
                if self._result_overlay.isVisible():
                    self._result_overlay.dismiss()
                # wheel_face クリック → spin 開始
                elif zone == "wheel_face" and not self._spin_ctrl.is_spinning:
                    self.spin_requested.emit()
                # pointer / outside → 何もしない
                event.accept()
                return

            # パネル移動完了
            if self._dragging_panel:
                self._dragging_panel = False
                event.accept()
                return

        event.accept()

    def wheelEvent(self, event):
        """ホイール内のマウスホイール回転を無効化する。"""
        event.accept()
