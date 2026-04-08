"""
PySide6 プロトタイプ — 操作・設定パネル

右側パネルの責務:
  - spin 操作（開始ボタン、プリセット切替）
  - 表示設定（テキストモード、ドーナツ穴 等）
  - 項目データ表示（ItemEntry リスト）
  - 将来機能の受け皿セクション（プレースホルダー）

設定変更の通知フロー:
  SettingsPanel → setting_changed(key, value) → MainWindow → 各コンポーネント

セクション構成（2系統で整理）:

  【アプリ設定セクション】AppSettings 側
    1. スピン操作 — 実装済み
    2. 表示設定 — 実装済み
    3. 結果表示 — 実装済み

  【項目データセクション】ItemEntry 側
    4. 項目リスト — 実装済み（編集可能）
    5. 確率変更 — プレースホルダー（項目データの編集）
    6. 分割 — プレースホルダー（項目データの編集）
    7. 配置 — プレースホルダー（項目データの編集）
    8. 常時ランダム — プレースホルダー（spin 前の配置制御）
"""

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QFont, QCursor, QPainter, QColor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QScrollArea, QWidget,
    QDoubleSpinBox, QLineEdit, QStackedWidget,
)

from bridge import (
    SIDEBAR_W, SIZE_PROFILES, DesignSettings,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
)
from app_settings import AppSettings
from item_entry import ItemEntry
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME


# ================================================================
#  セクション UI 部品
# ================================================================

class _SectionHeader(QLabel):
    """セクション見出し用ラベル。"""

    def __init__(self, text: str, design: DesignSettings, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont("Meiryo", 9, QFont.Weight.Bold))
        self._apply_style(design)

    def _apply_style(self, design: DesignSettings):
        self.setStyleSheet(
            f"color: {design.text}; "
            f"padding: 4px 0 2px 0; "
            f"border-bottom: 1px solid {design.separator};"
        )


class _PanelGrip(QWidget):
    """パネル右下に配置するリサイズグリップ。

    ドラッグで対象パネルのサイズを拡大・縮小する。
    パネル幅は常に setFixedWidth で管理し、ウィンドウも連動リサイズする。

    mode:
      "panel" — 設定/項目パネル用。ドラッグでパネル幅を変え、ウィンドウ幅も連動。
      "wheel" — ルーレット側用。ドラッグでウィンドウサイズを変える（パネル幅は保持）。
    """

    _GRIP_SIZE = 16

    def __init__(self, target: QWidget, design, mode: str = "panel",
                 min_w: int = 200, min_h: int = 200, parent=None):
        super().__init__(parent or target)
        self._target = target
        self._design = design
        self._mode = mode
        self._min_w = min_w
        self._min_h = min_h
        self._dragging = False
        self._drag_start = QPoint()
        self._start_target_w = 0
        self._start_target_h = 0
        self._start_win_w = 0
        self._start_win_h = 0
        self.setFixedSize(self._GRIP_SIZE, self._GRIP_SIZE)
        self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        self.raise_()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._design.text_sub)
        color.setAlpha(160)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        s = self._GRIP_SIZE
        # 右下三角形パターン: 行が下がるほどドットが多い（右下方向を示唆）
        for r in range(3):
            for c in range(r + 1):
                x = s - (r + 1 - c) * 5
                y = s - (3 - r) * 5
                p.drawEllipse(x, y, 3, 3)
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._drag_start = event.globalPosition().toPoint()
        self._start_target_w = self._target.width()
        self._start_target_h = self._target.height()
        win = self._target.window()
        if win:
            self._start_win_w = win.width()
            self._start_win_h = win.height()
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        win = self._target.window()
        if not win:
            return

        if self._mode == "panel":
            # パネルのみリサイズ（位置固定、右下方向に拡縮）
            new_w = max(self._min_w, self._start_target_w + delta.x())
            new_h = max(self._min_h, self._start_target_h + delta.y())
            parent = self._target.parentWidget()
            if parent:
                max_w = parent.width() - self._target.x()
                max_h = parent.height() - self._target.y()
                new_w = min(new_w, max_w)
                new_h = min(new_h, max_h)
            self._target.resize(new_w, new_h)
        else:
            # wheel 側: ウィンドウをリサイズ（パネル幅は保持）
            new_win_w = max(win.minimumWidth(), self._start_win_w + delta.x())
            new_win_h = max(win.minimumHeight(), self._start_win_h + delta.y())
            win.resize(new_win_w, new_win_h)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()

    def update_design(self, design):
        self._design = design
        self.update()

    def reposition(self):
        """親ウィジェット右下に位置を合わせる。"""
        parent = self.parentWidget()
        if parent:
            self.move(
                parent.width() - self._GRIP_SIZE,
                parent.height() - self._GRIP_SIZE,
            )
            self.raise_()


class _PanelDragBar(QWidget):
    """パネル上部のドラッグバー。ドラッグでパネルを親ウィジェット内で移動する。"""

    _BAR_HEIGHT = 20

    def __init__(self, target: QWidget, design: DesignSettings, parent=None):
        super().__init__(parent or target)
        self._target = target
        self._design = design
        self._dragging = False
        self._drag_start = QPoint()
        self._start_pos = QPoint()
        self.setFixedHeight(self._BAR_HEIGHT)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._design.separator))
        # 中央にグリップパターンを描画
        color = QColor(self._design.text_sub)
        color.setAlpha(140)
        p.setPen(color)
        cx = self.width() // 2
        cy = self._BAR_HEIGHT // 2
        for i in range(-3, 4):
            p.drawPoint(cx + i * 4, cy - 2)
            p.drawPoint(cx + i * 4, cy + 2)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
            self._start_pos = self._target.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        new_pos = self._start_pos + delta
        parent = self._target.parentWidget()
        if parent:
            min_visible = 60
            new_x = max(-self._target.width() + min_visible,
                        min(new_pos.x(), parent.width() - min_visible))
            new_y = max(0, min(new_pos.y(), parent.height() - self._BAR_HEIGHT))
            self._target.move(new_x, new_y)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()

    def update_design(self, design: DesignSettings):
        self._design = design
        self.update()


class _PlaceholderSection(QFrame):
    """未実装セクションのプレースホルダー。

    将来機能を本実装する際は、このクラスを専用セクションに差し替える。
    差し替え時の手順:
      1. 専用セクションクラスを作成（_PlaceholderSection と同じ位置に追加可能）
      2. SettingsPanel._build_future_sections() 内で差し替え
      3. setting_changed シグナル経由で MainWindow に通知
    """

    def __init__(self, title: str, description: str,
                 design: DesignSettings, parent=None):
        super().__init__(parent)
        self._header = _SectionHeader(title, design)
        self._desc = QLabel(description)
        self._desc.setFont(QFont("Meiryo", 8))
        self._desc.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)
        layout.addWidget(self._header)
        layout.addWidget(self._desc)

        self._apply_style(design)

    def _apply_style(self, design: DesignSettings):
        self._header._apply_style(design)
        self._desc.setStyleSheet(f"color: {design.text_sub};")


# ================================================================
#  メインパネル
# ================================================================

class SettingsPanel(QFrame):
    """操作・設定パネル。

    Signals:
        spin_requested: spin 開始が要求された
        preset_changed(str): spin プリセットが変更された
        setting_changed(str, object): 設定値が変更された (key, value)
            key は AppSettings のフィールド名に対応する。
            MainWindow はこのシグナルを受けて該当コンポーネントを更新する。
        item_entries_changed(list): 項目データが変更された
            MainWindow はこのシグナルを受けて segments 再構築・保存を行う。
    """

    spin_requested = Signal()
    preset_changed = Signal(str)
    setting_changed = Signal(str, object)
    item_entries_changed = Signal(list)
    geometry_changed = Signal()

    def __init__(self, item_entries: list[ItemEntry], settings: AppSettings,
                 design: DesignSettings, parent=None):
        """操作・設定パネル。

        Args:
            item_entries: 項目データ（bridge.load_item_entries() の戻り値）。
                設定データ（AppSettings）とは別管理。各項目のテキスト・
                確率・分割等を保持する ItemEntry のリスト。
            settings: アプリ設定データ（AppSettings）。
            design: デザイン設定。
        """
        super().__init__(parent)
        self._design = design
        self._settings = settings
        self._item_entries = item_entries
        self.setStyleSheet(f"background-color: {design.panel};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 1つのスクロール領域にアプリ設定 + 項目リストを縦並び ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._apply_scroll_style(self._scroll, design)

        self._content = QWidget()
        self._content.setStyleSheet(
            f"background-color: {design.panel};"
        )
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)

        # ── アプリ設定セクション ──
        self._build_spin_section(design)
        self._build_display_section(settings, design)
        self._build_result_section(settings, design)
        self._build_sound_section(settings, design)

        # ── 項目データセクション ──
        self._build_items_section(item_entries, design)
        self._build_item_edit_sections(design)

        self._layout.addStretch()

        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

        # ── 最小幅: contentsMargins + スクロールバー幅 + つまみ逃がし ──
        scrollbar_w = self._scroll.verticalScrollBar().sizeHint().width()
        content_margins = self._layout.contentsMargins()
        margins_total = content_margins.left() + content_margins.right()
        # SIDEBAR_W をベースに、スクロールバーとマージンを加味
        self._panel_min_w = max(SIDEBAR_W, 200 + margins_total + scrollbar_w + 20)

        # ── 右下リサイズグリップ（パネル幅変更用） ──
        self._resize_grip = _PanelGrip(
            self, design, mode="panel", min_w=self._panel_min_w, parent=self
        )

        # パネル最小幅
        self.setMinimumWidth(self._panel_min_w)

        # ── パネル前後関係 ──
        self.pinned_front = False  # True: 通常パネルより常に上に表示

        # ── パネルドラッグ状態 ──
        self._dragging_panel = False
        self._panel_drag_start = QPoint()
        self._panel_start_pos = QPoint()

    # ================================================================
    #  セクション 1: スピン操作（実装済み）
    # ================================================================

    def _build_spin_section(self, design: DesignSettings):
        self._spin_header = _SectionHeader("スピン", design)
        self._layout.addWidget(self._spin_header)

        # spin ボタン
        self._spin_btn = QPushButton("▶  スピン開始")
        self._spin_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._spin_btn.setMinimumHeight(36)
        self._spin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_spin_btn_style(design)
        self._spin_btn.clicked.connect(self.spin_requested.emit)
        self._layout.addWidget(self._spin_btn)

        # プリセット選択
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)

        preset_lbl = QLabel("プリセット:")
        preset_lbl.setFont(QFont("Meiryo", 8))
        preset_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._preset_lbl = preset_lbl
        preset_row.addWidget(preset_lbl)

        self._preset_combo = QComboBox()
        self._preset_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._preset_combo, design)
        for name in SPIN_PRESET_NAMES:
            self._preset_combo.addItem(name)
        self._preset_combo.setCurrentText(DEFAULT_PRESET_NAME)
        self._preset_combo.currentTextChanged.connect(self.preset_changed.emit)
        preset_row.addWidget(self._preset_combo, stretch=1)

        self._layout.addLayout(preset_row)

    # ================================================================
    #  セクション 2: 表示設定（実装済み）
    # ================================================================

    def _build_display_section(self, settings: AppSettings,
                               design: DesignSettings):
        self._display_header = _SectionHeader("表示", design)
        self._layout.addWidget(self._display_header)

        # テキスト表示モード
        text_row = QHBoxLayout()
        text_row.setSpacing(4)
        text_lbl = QLabel("テキスト:")
        text_lbl.setFont(QFont("Meiryo", 8))
        text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._text_lbl = text_lbl
        text_row.addWidget(text_lbl)

        self._text_mode_combo = QComboBox()
        self._text_mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._text_mode_combo, design)
        for name in ["省略", "収める", "縮小"]:
            self._text_mode_combo.addItem(name)
        self._text_mode_combo.setCurrentIndex(settings.text_size_mode)
        self._text_mode_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("text_size_mode", idx)
        )
        text_row.addWidget(self._text_mode_combo, stretch=1)
        self._layout.addLayout(text_row)

        # ドーナツ穴
        self._donut_cb = QCheckBox("ドーナツ穴")
        self._donut_cb.setFont(QFont("Meiryo", 8))
        self._donut_cb.setStyleSheet(f"color: {design.text};")
        self._donut_cb.setChecked(settings.donut_hole)
        self._donut_cb.toggled.connect(
            lambda v: self.setting_changed.emit("donut_hole", v)
        )
        self._layout.addWidget(self._donut_cb)

        # サイズプロファイル
        prof_row = QHBoxLayout()
        prof_row.setSpacing(4)
        prof_lbl = QLabel("サイズ:")
        prof_lbl.setFont(QFont("Meiryo", 8))
        prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._prof_lbl = prof_lbl
        prof_row.addWidget(prof_lbl)

        self._prof_combo = QComboBox()
        self._prof_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._prof_combo, design)
        for label, w, h in SIZE_PROFILES:
            self._prof_combo.addItem(f"{label}  ({w}x{h})")
        prof_idx = min(settings.profile_idx, len(SIZE_PROFILES) - 1)
        self._prof_combo.setCurrentIndex(prof_idx)
        self._prof_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("profile_idx", idx)
        )
        prof_row.addWidget(self._prof_combo, stretch=1)
        self._layout.addLayout(prof_row)

        # テキスト方向
        tdir_row = QHBoxLayout()
        tdir_row.setSpacing(4)
        tdir_lbl = QLabel("テキスト方向:")
        tdir_lbl.setFont(QFont("Meiryo", 8))
        tdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tdir_lbl = tdir_lbl
        tdir_row.addWidget(tdir_lbl)

        self._tdir_combo = QComboBox()
        self._tdir_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._tdir_combo, design)
        for name in ["横(回転)", "横(水平)", "縦上", "縦下", "縦直立"]:
            self._tdir_combo.addItem(name)
        self._tdir_combo.setCurrentIndex(settings.text_direction)
        self._tdir_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("text_direction", idx)
        )
        tdir_row.addWidget(self._tdir_combo, stretch=1)
        self._layout.addLayout(tdir_row)

        # スピン回転方向
        sdir_row = QHBoxLayout()
        sdir_row.setSpacing(4)
        sdir_lbl = QLabel("回転方向:")
        sdir_lbl.setFont(QFont("Meiryo", 8))
        sdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._sdir_lbl = sdir_lbl
        sdir_row.addWidget(sdir_lbl)

        self._sdir_combo = QComboBox()
        self._sdir_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._sdir_combo, design)
        for name in ["反時計回り", "時計回り"]:
            self._sdir_combo.addItem(name)
        self._sdir_combo.setCurrentIndex(settings.spin_direction)
        self._sdir_combo.currentIndexChanged.connect(
            lambda idx: self.setting_changed.emit("spin_direction", idx)
        )
        sdir_row.addWidget(self._sdir_combo, stretch=1)
        self._layout.addLayout(sdir_row)

        # ポインター位置
        ptr_row = QHBoxLayout()
        ptr_row.setSpacing(4)
        ptr_lbl = QLabel("ポインター:")
        ptr_lbl.setFont(QFont("Meiryo", 8))
        ptr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._ptr_lbl = ptr_lbl
        ptr_row.addWidget(ptr_lbl)

        self._ptr_combo = QComboBox()
        self._ptr_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._ptr_combo, design)
        for name in POINTER_PRESET_NAMES:
            self._ptr_combo.addItem(name)
        # 現在の pointer_angle からプリセットインデックスを逆引き
        ptr_preset_idx = self._angle_to_preset_idx(settings.pointer_angle)
        self._ptr_combo.setCurrentIndex(ptr_preset_idx)
        self._ptr_combo.currentIndexChanged.connect(self._on_pointer_preset_changed)
        ptr_row.addWidget(self._ptr_combo, stretch=1)
        self._layout.addLayout(ptr_row)

    @staticmethod
    def _angle_to_preset_idx(angle: float) -> int:
        """pointer_angle からプリセットインデックスを逆引きする。"""
        for i, a in enumerate(_POINTER_PRESET_ANGLES):
            if abs(angle - a) < 1.0:
                return i
        return len(POINTER_PRESET_NAMES) - 1  # 任意

    def _on_pointer_preset_changed(self, idx: int):
        """ポインタープリセット変更時のハンドラ。"""
        if idx < len(_POINTER_PRESET_ANGLES):
            angle = _POINTER_PRESET_ANGLES[idx]
            self.setting_changed.emit("pointer_angle", angle)

    # ================================================================
    #  セクション 3: 結果表示設定（実装済み）
    # ================================================================

    def _build_result_section(self, settings: AppSettings,
                              design: DesignSettings):
        self._result_header = _SectionHeader("結果表示", design)
        self._layout.addWidget(self._result_header)

        # 閉じ方モード
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_lbl = QLabel("閉じ方:")
        mode_lbl.setFont(QFont("Meiryo", 8))
        mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_mode_lbl = mode_lbl
        mode_row.addWidget(mode_lbl)

        self._result_mode_combo = QComboBox()
        self._result_mode_combo.setFont(QFont("Meiryo", 8))
        self._apply_combo_style(self._result_mode_combo, design)
        for name in ["クリック", "自動", "両方"]:
            self._result_mode_combo.addItem(name)
        self._result_mode_combo.setCurrentIndex(settings.result_close_mode)
        self._result_mode_combo.currentIndexChanged.connect(
            self._on_result_mode_changed
        )
        mode_row.addWidget(self._result_mode_combo, stretch=1)
        self._layout.addLayout(mode_row)

        # 保持秒数
        sec_row = QHBoxLayout()
        sec_row.setSpacing(4)
        sec_lbl = QLabel("保持秒数:")
        sec_lbl.setFont(QFont("Meiryo", 8))
        sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_sec_lbl = sec_lbl
        sec_row.addWidget(sec_lbl)

        self._result_sec_spin = QDoubleSpinBox()
        self._result_sec_spin.setFont(QFont("Meiryo", 8))
        self._result_sec_spin.setRange(0.5, 30.0)
        self._result_sec_spin.setSingleStep(0.5)
        self._result_sec_spin.setDecimals(1)
        self._result_sec_spin.setSuffix(" 秒")
        self._result_sec_spin.setValue(settings.result_hold_sec)
        self._result_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        self._result_sec_spin.valueChanged.connect(
            lambda v: self.setting_changed.emit("result_hold_sec", v)
        )
        sec_row.addWidget(self._result_sec_spin, stretch=1)
        self._layout.addLayout(sec_row)

        # 再生時保持秒数（チェックボックスで通常保持の継承/個別設定を切替）
        macro_cb_row = QHBoxLayout()
        macro_cb_row.setSpacing(4)
        self._macro_hold_cb = QCheckBox("マクロ再生時の保持を個別設定")
        self._macro_hold_cb.setFont(QFont("Meiryo", 8))
        self._macro_hold_cb.setStyleSheet(f"color: {design.text_sub};")
        macro_cb_row.addWidget(self._macro_hold_cb)
        self._layout.addLayout(macro_cb_row)

        macro_sec_row = QHBoxLayout()
        macro_sec_row.setSpacing(4)
        self._macro_sec_lbl = QLabel("  マクロ時:")
        self._macro_sec_lbl.setFont(QFont("Meiryo", 8))
        self._macro_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        macro_sec_row.addWidget(self._macro_sec_lbl)

        self._macro_sec_spin = QDoubleSpinBox()
        self._macro_sec_spin.setFont(QFont("Meiryo", 8))
        self._macro_sec_spin.setRange(0.5, 30.0)
        self._macro_sec_spin.setSingleStep(0.5)
        self._macro_sec_spin.setDecimals(1)
        self._macro_sec_spin.setSuffix(" 秒")
        self._macro_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )

        is_custom = settings.macro_hold_sec is not None
        self._macro_hold_cb.setChecked(is_custom)
        if is_custom:
            self._macro_sec_spin.setValue(settings.macro_hold_sec)
        else:
            self._macro_sec_spin.setValue(settings.result_hold_sec)
        self._macro_sec_spin.setEnabled(is_custom)
        self._macro_sec_lbl.setEnabled(is_custom)

        self._macro_hold_cb.toggled.connect(self._on_macro_hold_toggled)
        self._macro_sec_spin.valueChanged.connect(self._on_macro_hold_value_changed)

        macro_sec_row.addWidget(self._macro_sec_spin, stretch=1)
        self._layout.addLayout(macro_sec_row)

        # 保持秒数の有効/無効を閉じ方モードに連動
        self._update_hold_sec_enabled()

    def _on_result_mode_changed(self, idx: int):
        """閉じ方モード変更時のハンドラ。"""
        self.setting_changed.emit("result_close_mode", idx)
        self._update_hold_sec_enabled()

    def _update_hold_sec_enabled(self):
        """保持秒数の入力を閉じ方モードに応じて有効/無効化する。"""
        mode = self._result_mode_combo.currentIndex()
        enabled = mode in (1, 2)  # 自動 or 両方
        self._result_sec_spin.setEnabled(enabled)

    def _on_macro_hold_toggled(self, checked: bool):
        """再生時保持の個別設定チェックボックス切替。"""
        self._macro_sec_spin.setEnabled(checked)
        self._macro_sec_lbl.setEnabled(checked)
        if checked:
            self.setting_changed.emit("macro_hold_sec",
                                      self._macro_sec_spin.value())
        else:
            # 未設定に戻す: 表示を通常保持の現在値に追従させる
            self._macro_sec_spin.blockSignals(True)
            self._macro_sec_spin.setValue(self._result_sec_spin.value())
            self._macro_sec_spin.blockSignals(False)
            self.setting_changed.emit("macro_hold_sec", None)

    def _on_macro_hold_value_changed(self, value: float):
        """再生時保持のスピンボックス値変更。"""
        if self._macro_hold_cb.isChecked():
            self.setting_changed.emit("macro_hold_sec", value)

    # ================================================================
    #  セクション 3b: サウンド設定（AppSettings 側）
    # ================================================================

    def _build_sound_section(self, settings: AppSettings,
                             design: DesignSettings):
        self._sound_header = _SectionHeader("サウンド", design)
        self._layout.addWidget(self._sound_header)

        # tick 音 ON/OFF
        self._sound_tick_cb = QCheckBox("スピン音")
        self._sound_tick_cb.setFont(QFont("Meiryo", 8))
        self._sound_tick_cb.setStyleSheet(f"color: {design.text};")
        self._sound_tick_cb.setChecked(settings.sound_tick_enabled)
        self._sound_tick_cb.toggled.connect(
            lambda v: self.setting_changed.emit("sound_tick_enabled", v)
        )
        self._layout.addWidget(self._sound_tick_cb)

        # result 音 ON/OFF
        self._sound_result_cb = QCheckBox("決定音")
        self._sound_result_cb.setFont(QFont("Meiryo", 8))
        self._sound_result_cb.setStyleSheet(f"color: {design.text};")
        self._sound_result_cb.setChecked(settings.sound_result_enabled)
        self._sound_result_cb.toggled.connect(
            lambda v: self.setting_changed.emit("sound_result_enabled", v)
        )
        self._layout.addWidget(self._sound_result_cb)

    # ================================================================
    #  セクション 4: 項目リスト（編集可能・ItemEntry 側）
    # ================================================================

    def _build_items_section(self, entries: list[ItemEntry],
                             design: DesignSettings):
        """項目データセクションを構築する。

        各行: [有効CB] [テキスト入力] [▲] [▼] [×]
        末尾に「＋追加」ボタン。
        """
        self._items_header = _SectionHeader("項目リスト", design)
        self._layout.addWidget(self._items_header)

        # 行ウィジェットを格納するコンテナ
        self._item_rows_container = QWidget()
        self._item_rows_layout = QVBoxLayout(self._item_rows_container)
        self._item_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._item_rows_layout.setSpacing(2)
        self._layout.addWidget(self._item_rows_container)

        self._item_rows: list[QWidget] = []

        for entry in entries:
            self._add_item_row(entry, design)

        # 追加ボタン
        self._add_item_btn = QPushButton("＋ 追加")
        self._add_item_btn.setFont(QFont("Meiryo", 8))
        self._add_item_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_add_btn_style(self._add_item_btn, design)
        self._add_item_btn.clicked.connect(self._on_add_item)
        self._layout.addWidget(self._add_item_btn)

    # ── 確率変更ヘルパー ──

    # 確率モードの UI 表示名と内部値の対応
    _PROB_MODE_LABELS = ["変更なし", "重み係数", "固定確率"]
    _PROB_MODE_VALUES = [None, "weight", "fixed"]

    @staticmethod
    def _build_weight_candidates(n: int) -> list[float]:
        """重み係数の選択肢を生成する。

        Args:
            n: 現在の有効項目数

        Returns:
            [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, ..., n] の候補リスト
        """
        candidates = [0.25, 0.5, 0.75, 1.0]
        v = 1.5
        while v <= n:
            candidates.append(v)
            v += 0.5
        return candidates

    def _get_enabled_count(self) -> int:
        """現在の有効項目数 N を返す。"""
        return sum(1 for r in self._item_rows if r._cb.isChecked())

    def _add_item_row(self, entry: ItemEntry, design: DesignSettings,
                      index: int = -1) -> QWidget:
        """1項目分の編集行を作成し、コンテナに追加する。

        行構成（2段）:
          上段: [CB] [テキスト] [▲] [▼] [×]
          下段: [確率モード] [値ウィジェット（weight combo / fixed spin）]
        """
        row = QWidget()
        outer_layout = QVBoxLayout(row)
        outer_layout.setContentsMargins(0, 1, 0, 1)
        outer_layout.setSpacing(1)

        # ── 上段: テキスト + 操作ボタン ──
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(2)

        # 有効/無効チェックボックス
        cb = QCheckBox()
        cb.setChecked(entry.enabled)
        cb.setStyleSheet(f"color: {design.text};")
        cb.toggled.connect(lambda _: self._on_item_toggled())
        top_row.addWidget(cb)

        # テキスト入力
        edit = QLineEdit(entry.text)
        edit.setFont(QFont("Meiryo", 8))
        edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        edit.editingFinished.connect(self._on_item_text_edited)
        top_row.addWidget(edit, stretch=1)

        # ボタン共通スタイル
        btn_font = QFont("Meiryo", 8)
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

        # 上へ
        up_btn = QPushButton("▲")
        up_btn.setFont(btn_font)
        up_btn.setStyleSheet(btn_style)
        up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        up_btn.clicked.connect(lambda: self._on_move_item(row, -1))
        top_row.addWidget(up_btn)

        # 下へ
        down_btn = QPushButton("▼")
        down_btn.setFont(btn_font)
        down_btn.setStyleSheet(btn_style)
        down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        down_btn.clicked.connect(lambda: self._on_move_item(row, 1))
        top_row.addWidget(down_btn)

        # 削除
        del_btn = QPushButton("×")
        del_btn.setFont(btn_font)
        del_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self._on_delete_item(row))
        top_row.addWidget(del_btn)

        outer_layout.addLayout(top_row)

        # ── 下段: 確率変更 UI ──
        prob_row = QHBoxLayout()
        prob_row.setContentsMargins(20, 0, 0, 0)  # 左インデント
        prob_row.setSpacing(4)

        combo_style = (
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 14px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )

        # 確率モード選択
        mode_combo = QComboBox()
        mode_combo.setFont(QFont("Meiryo", 7))
        mode_combo.setStyleSheet(combo_style)
        for label in self._PROB_MODE_LABELS:
            mode_combo.addItem(label)
        prob_row.addWidget(mode_combo)

        # 値ウィジェット（QStackedWidget で切替）
        value_stack = QStackedWidget()

        # page 0: 変更なし — 空ラベル
        empty_label = QLabel("")
        value_stack.addWidget(empty_label)

        # page 1: 重み係数 — QComboBox
        n = self._get_enabled_count() if self._item_rows else max(1, len(self._item_entries))
        weight_combo = QComboBox()
        weight_combo.setFont(QFont("Meiryo", 7))
        weight_combo.setStyleSheet(combo_style)
        self._populate_weight_combo(weight_combo, n)
        weight_combo.currentIndexChanged.connect(
            lambda _: self._on_prob_value_changed()
        )
        value_stack.addWidget(weight_combo)

        # page 2: 固定確率 — QDoubleSpinBox
        fixed_spin = QDoubleSpinBox()
        fixed_spin.setFont(QFont("Meiryo", 7))
        fixed_spin.setRange(0.1, 99.9)
        fixed_spin.setSingleStep(0.5)
        fixed_spin.setDecimals(1)
        fixed_spin.setSuffix(" %")
        fixed_spin.setValue(10.0)
        fixed_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
        )
        fixed_spin.editingFinished.connect(self._on_prob_value_changed)
        value_stack.addWidget(fixed_spin)

        prob_row.addWidget(value_stack, stretch=1)
        outer_layout.addLayout(prob_row)

        # モード切替で表示切替
        mode_combo.currentIndexChanged.connect(
            lambda idx: self._on_prob_mode_changed(row, idx)
        )

        # 行にウィジェット参照を保持
        row._cb = cb
        row._edit = edit
        row._mode_combo = mode_combo
        row._value_stack = value_stack
        row._weight_combo = weight_combo
        row._fixed_spin = fixed_spin

        # 既存データから確率モード/値を復元
        self._restore_prob_ui(row, entry)

        if index < 0:
            self._item_rows_layout.addWidget(row)
            self._item_rows.append(row)
        else:
            self._item_rows_layout.insertWidget(index, row)
            self._item_rows.insert(index, row)

        return row

    @staticmethod
    def _populate_weight_combo(combo: QComboBox, n: int):
        """重み係数 QComboBox の選択肢を N に基づいて再構築する。"""
        combo.blockSignals(True)
        current_text = combo.currentText()
        combo.clear()
        candidates = SettingsPanel._build_weight_candidates(n)
        for v in candidates:
            combo.addItem(f"×{v:g}", v)
        # 以前の選択を復元（可能なら）
        for i in range(combo.count()):
            if combo.itemText(i) == current_text:
                combo.setCurrentIndex(i)
                break
        combo.blockSignals(False)

    def _restore_prob_ui(self, row: QWidget, entry: ItemEntry):
        """ItemEntry の prob_mode/prob_value から UI を復元する。"""
        if entry.prob_mode == "weight":
            row._mode_combo.setCurrentIndex(1)  # 重み係数
            row._value_stack.setCurrentIndex(1)
            # 値を weight_combo から探す
            val = entry.prob_value if entry.prob_value is not None else 1.0
            for i in range(row._weight_combo.count()):
                if abs(row._weight_combo.itemData(i) - val) < 0.001:
                    row._weight_combo.setCurrentIndex(i)
                    break
        elif entry.prob_mode == "fixed":
            row._mode_combo.setCurrentIndex(2)  # 固定確率
            row._value_stack.setCurrentIndex(2)
            val = entry.prob_value if entry.prob_value is not None else 10.0
            val = max(0.1, min(99.9, val))
            row._fixed_spin.setValue(val)
        else:
            row._mode_combo.setCurrentIndex(0)  # 変更なし
            row._value_stack.setCurrentIndex(0)

    def _on_prob_mode_changed(self, row: QWidget, idx: int):
        """確率モード切替時: 表示切替 + 通知。"""
        row._value_stack.setCurrentIndex(idx)
        self._emit_entries_changed()

    def _refresh_all_weight_combos(self):
        """全行の重み係数候補を現在の N に基づいて再構築する。

        N が変わると上限が変わるため、全行を更新する。
        保持していた値が新 N では上限超過の場合、最大値にクランプする。
        """
        n = self._get_enabled_count()
        n = max(n, 1)
        for row in self._item_rows:
            combo = row._weight_combo
            # 現在の値を保持
            old_idx = combo.currentIndex()
            old_val = combo.itemData(old_idx) if old_idx >= 0 else 1.0
            self._populate_weight_combo(combo, n)
            # 旧値を復元（上限超過はクランプ）
            best_idx = 0
            for i in range(combo.count()):
                if combo.itemData(i) is not None and combo.itemData(i) <= old_val:
                    best_idx = i
            combo.setCurrentIndex(best_idx)

    def _on_prob_value_changed(self):
        """確率値変更時: 通知。"""
        self._emit_entries_changed()

    def _collect_entries(self) -> list[ItemEntry]:
        """現在の UI 行から ItemEntry リストを収集する。"""
        entries = []
        for row in self._item_rows:
            text = row._edit.text().strip()
            if not text:
                continue
            mode_idx = row._mode_combo.currentIndex()
            prob_mode = self._PROB_MODE_VALUES[mode_idx]
            prob_value = None
            if prob_mode == "weight":
                idx = row._weight_combo.currentIndex()
                if idx >= 0:
                    prob_value = row._weight_combo.itemData(idx)
            elif prob_mode == "fixed":
                prob_value = row._fixed_spin.value()
            entries.append(ItemEntry(
                text=text,
                enabled=row._cb.isChecked(),
                prob_mode=prob_mode,
                prob_value=prob_value,
            ))
        return entries

    def _emit_entries_changed(self):
        """項目変更を通知する。"""
        self._item_entries = self._collect_entries()
        self.item_entries_changed.emit(list(self._item_entries))

    def _on_add_item(self):
        """追加ボタン押下: 新しい空行を追加する。"""
        entry = ItemEntry(text="新しい項目", enabled=True)
        self._add_item_row(entry, self._design)
        self._refresh_all_weight_combos()
        self._emit_entries_changed()

    def _on_delete_item(self, row: QWidget):
        """削除ボタン押下: 指定行を削除する。"""
        if row in self._item_rows:
            self._item_rows.remove(row)
            self._item_rows_layout.removeWidget(row)
            row.deleteLater()
            self._refresh_all_weight_combos()
            self._emit_entries_changed()

    def _on_move_item(self, row: QWidget, direction: int):
        """上下ボタン押下: 指定行を移動する。"""
        if row not in self._item_rows:
            return
        idx = self._item_rows.index(row)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._item_rows):
            return
        # リストの入れ替え
        self._item_rows[idx], self._item_rows[new_idx] = (
            self._item_rows[new_idx], self._item_rows[idx]
        )
        # レイアウトから一旦除去して再挿入
        self._item_rows_layout.removeWidget(row)
        self._item_rows_layout.insertWidget(new_idx, row)
        self._emit_entries_changed()

    def _on_item_toggled(self):
        """有効/無効チェックボックス変更時。N 変化に伴い重み候補を再構築。"""
        self._refresh_all_weight_combos()
        self._emit_entries_changed()

    def _on_item_text_edited(self):
        """テキスト編集完了（editingFinished）時。"""
        self._emit_entries_changed()

    @staticmethod
    def _apply_add_btn_style(btn: QPushButton, design):
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 4px 8px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )

    def _update_item_rows_design(self, design: DesignSettings):
        """項目編集行のデザインを更新する。"""
        edit_style = (
            f"QLineEdit {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        del_btn_style = (
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 3px; padding: 2px 4px;"
            f"  min-width: 20px; max-width: 20px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
        )
        combo_style = (
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 14px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )
        spin_style = (
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 1px 4px; font-size: 8pt;"
            f"}}"
        )
        for row in self._item_rows:
            row._cb.setStyleSheet(f"color: {design.text};")
            row._edit.setStyleSheet(edit_style)
            # 上段のボタン（上段レイアウトの index 2,3,4）
            top_layout = row.layout().itemAt(0).layout()
            for i in range(2, 5):
                btn = top_layout.itemAt(i).widget()
                if i == 4:  # 削除ボタン
                    btn.setStyleSheet(del_btn_style)
                else:
                    btn.setStyleSheet(btn_style)
            # 確率 UI
            row._mode_combo.setStyleSheet(combo_style)
            row._weight_combo.setStyleSheet(combo_style)
            row._fixed_spin.setStyleSheet(spin_style)

    # ================================================================
    #  セクション 5-8: 項目編集系（ItemEntry 側の将来拡張）
    #
    #  これらは項目データ（ItemEntry）に対する編集 UI。
    #  AppSettings 側のセクションとは責務が異なる。
    #
    #  本実装時の手順:
    #    1. _PlaceholderSection を専用セクションクラスに差し替え
    #    2. 編集 UI で self._item_entries を変更
    #    3. self.item_entries_changed.emit(self._item_entries) で通知
    #    4. MainWindow が受信 → segments 再構築 → WheelWidget 更新 → 保存
    #
    #  保存経路:
    #    SettingsPanel.item_entries_changed
    #      → MainWindow._on_item_entries_changed()
    #        → self._item_entries = entries
    #        → segments 再構築 → WheelWidget.set_segments()
    #        → save_item_entries(config, entries)
    # ================================================================

    def _build_item_edit_sections(self, design: DesignSettings):
        """項目データに関する将来の編集セクション（プレースホルダー）。

        確率変更は各項目行に統合済み（i079）。
        """
        self._item_edit_sections: list[_PlaceholderSection] = []

        sections = [
            ("分割", "項目の分割数を変更（未実装）"),
            ("配置", "segment の並び順を変更（未実装）"),
            ("常時ランダム", "spin ごとに配置をランダム化（未実装）"),
        ]
        for title, desc in sections:
            section = _PlaceholderSection(title, desc, design)
            self._layout.addWidget(section)
            self._item_edit_sections.append(section)

    # ================================================================
    #  内部ヘルパー
    # ================================================================

    @staticmethod
    def _apply_scroll_style(scroll: QScrollArea, design: DesignSettings):
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {design.panel}; }}"
            f"QScrollBar:vertical {{ width: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:vertical {{ background: {design.separator}; border-radius: 3px; }}"
            f"QScrollBar:horizontal {{ height: 6px; background: {design.panel}; }}"
            f"QScrollBar::handle:horizontal {{ background: {design.separator}; border-radius: 3px; }}"
        )


    def _apply_spin_btn_style(self, design: DesignSettings):
        self._spin_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.accent}; color: {design.text};"
            f"  border: none; border-radius: 6px; padding: 6px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.separator}; }}"
            f"QPushButton:disabled {{ background-color: {design.separator}; color: {design.text_sub}; }}"
        )

    @staticmethod
    def _apply_combo_style(combo: QComboBox, design: DesignSettings):
        combo.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 3px 6px;"
            f"}}"
            f"QComboBox::drop-down {{ border: none; width: 16px; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {design.panel}; color: {design.text};"
            f"  selection-background-color: {design.separator};"
            f"  selection-color: {design.text};"
            f"  border: 1px solid {design.separator};"
            f"}}"
        )

    # ================================================================
    #  公開 API
    # ================================================================

    def mousePressEvent(self, event):
        """空きクライアント領域ドラッグでパネル移動。クリックで最前面へ。"""
        self.raise_()
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_panel = True
            self._panel_drag_start = event.globalPosition().toPoint()
            self._panel_start_pos = self.pos()
        event.accept()

    def mouseMoveEvent(self, event):
        if getattr(self, '_dragging_panel', False):
            delta = event.globalPosition().toPoint() - self._panel_drag_start
            new_pos = self._panel_start_pos + delta
            parent = self.parentWidget()
            if parent:
                new_x = max(0, min(new_pos.x(), parent.width() - self.width()))
                new_y = max(0, min(new_pos.y(), parent.height() - self.height()))
                self.move(new_x, new_y)
            event.accept()
            return
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_panel = False
        event.accept()

    def moveEvent(self, event):
        """パネル移動時に通知する。"""
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        """リサイズグリップを右下に追従させる。"""
        super().resizeEvent(event)
        self._resize_grip.reposition()
        self._clamp_to_parent()
        self.geometry_changed.emit()

    def _clamp_to_parent(self):
        """パネルをメインウィンドウ内にクランプする。"""
        parent = self.parentWidget()
        if not parent:
            return
        x = max(0, min(self.x(), parent.width() - self.width()))
        y = max(0, min(self.y(), parent.height() - self.height()))
        if x != self.x() or y != self.y():
            self.move(x, y)

    def set_active_entries(self, entries: list[ItemEntry]):
        """アクティブなルーレットの項目データを差し替える。

        将来のマルチルーレット切替時に、編集対象の item_entries を
        外部から一括で入れ替えるための入口。
        既存の項目行 UI を全て再構築する。
        """
        # 既存行を全て削除
        for row in list(self._item_rows):
            self._item_rows_layout.removeWidget(row)
            row.deleteLater()
        self._item_rows.clear()

        # 新しいエントリで行を再構築
        self._item_entries = entries
        for entry in entries:
            self._add_item_row(entry, self._design)

        self._refresh_all_weight_combos()

    def set_spinning(self, spinning: bool):
        """spin 状態に応じてボタンを有効/無効にする。"""
        self._spin_btn.setEnabled(not spinning)
        self._spin_btn.setText("⏳  スピン中..." if spinning else "▶  スピン開始")

    def set_preset(self, name: str):
        """プリセット表示を外部から更新する。"""
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(name)
        self._preset_combo.blockSignals(False)

    def update_setting(self, key: str, value):
        """外部からの設定変更を UI に反映する（シグナルを出さない）。"""
        if key == "text_size_mode":
            self._text_mode_combo.blockSignals(True)
            self._text_mode_combo.setCurrentIndex(value)
            self._text_mode_combo.blockSignals(False)
        elif key == "donut_hole":
            self._donut_cb.blockSignals(True)
            self._donut_cb.setChecked(value)
            self._donut_cb.blockSignals(False)
        elif key == "profile_idx":
            self._prof_combo.blockSignals(True)
            self._prof_combo.setCurrentIndex(value)
            self._prof_combo.blockSignals(False)
        elif key == "text_direction":
            self._tdir_combo.blockSignals(True)
            self._tdir_combo.setCurrentIndex(value)
            self._tdir_combo.blockSignals(False)
        elif key == "spin_direction":
            self._sdir_combo.blockSignals(True)
            self._sdir_combo.setCurrentIndex(value)
            self._sdir_combo.blockSignals(False)
        elif key == "pointer_angle":
            idx = self._angle_to_preset_idx(value)
            self._ptr_combo.blockSignals(True)
            self._ptr_combo.setCurrentIndex(idx)
            self._ptr_combo.blockSignals(False)
        elif key == "result_close_mode":
            self._result_mode_combo.blockSignals(True)
            self._result_mode_combo.setCurrentIndex(value)
            self._result_mode_combo.blockSignals(False)
            self._update_hold_sec_enabled()
        elif key == "result_hold_sec":
            self._result_sec_spin.blockSignals(True)
            self._result_sec_spin.setValue(value)
            self._result_sec_spin.blockSignals(False)
            # 未設定時は再生時保持表示を通常保持に追従させる
            if not self._macro_hold_cb.isChecked():
                self._macro_sec_spin.blockSignals(True)
                self._macro_sec_spin.setValue(value)
                self._macro_sec_spin.blockSignals(False)
        elif key == "macro_hold_sec":
            is_custom = value is not None
            self._macro_hold_cb.blockSignals(True)
            self._macro_hold_cb.setChecked(is_custom)
            self._macro_hold_cb.blockSignals(False)
            self._macro_sec_spin.blockSignals(True)
            if is_custom:
                self._macro_sec_spin.setValue(value)
            self._macro_sec_spin.setEnabled(is_custom)
            self._macro_sec_lbl.setEnabled(is_custom)
            self._macro_sec_spin.blockSignals(False)
        elif key == "sound_tick_enabled":
            self._sound_tick_cb.blockSignals(True)
            self._sound_tick_cb.setChecked(value)
            self._sound_tick_cb.blockSignals(False)
        elif key == "sound_result_enabled":
            self._sound_result_cb.blockSignals(True)
            self._sound_result_cb.setChecked(value)
            self._sound_result_cb.blockSignals(False)

    def update_design(self, design: DesignSettings):
        """デザイン変更時にパネル全体の配色を更新する。"""
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._content.setStyleSheet(f"background-color: {design.panel};")
        self._apply_scroll_style(self._scroll, design)
        self._resize_grip.update_design(design)
        self._apply_combo_style(self._preset_combo, design)
        self._apply_combo_style(self._text_mode_combo, design)
        self._apply_combo_style(self._prof_combo, design)
        self._apply_combo_style(self._tdir_combo, design)
        self._apply_combo_style(self._sdir_combo, design)
        self._apply_combo_style(self._ptr_combo, design)
        self._apply_spin_btn_style(design)

        # セクションヘッダー
        for header in [self._spin_header, self._display_header,
                       self._result_header, self._sound_header,
                       self._items_header]:
            header._apply_style(design)

        # ラベル
        self._preset_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._text_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._prof_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._tdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._sdir_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._ptr_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._donut_cb.setStyleSheet(f"color: {design.text};")
        self._sound_tick_cb.setStyleSheet(f"color: {design.text};")
        self._sound_result_cb.setStyleSheet(f"color: {design.text};")
        self._result_mode_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._result_sec_lbl.setStyleSheet(f"color: {design.text_sub};")
        self._apply_combo_style(self._result_mode_combo, design)
        self._result_sec_spin.setStyleSheet(
            f"QDoubleSpinBox {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: 1px solid {design.separator}; border-radius: 3px;"
            f"  padding: 2px 4px;"
            f"}}"
        )

        # 項目編集行
        self._update_item_rows_design(design)
        self._apply_add_btn_style(self._add_item_btn, design)

        # 項目編集プレースホルダーセクション
        for section in self._item_edit_sections:
            section._apply_style(design)
