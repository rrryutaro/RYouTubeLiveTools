"""
sequential_spin_dialog.py — 被りなし連続抽選 専用パネル

i021: 被りなし連続抽選機能の専用 UI。
i026: QDialog（別ウィンドウ）から QWidget（同一ウィンドウ内 child widget）へ変更。
i027: _PanelDragBar を追加しドラッグ移動を可能にする。
      マウスイベント伝播を遮断して RoulettePanel / MainWindow へのドラッグ誤伝播を防ぐ。
i028: WA_StyledBackground で不透明背景を確保。
      実行回数上限を ON 項目数 - 1 に修正。
      update_target() でパターン変更時の即時更新に対応。

機能:
  - 対象ルーレット / パターン / ON 項目数の表示
  - 実行回数・結果表示秒数の入力
  - 実行 / 中断ボタン
  - 進捗表示
  - 最終抽選順リストの表示（§4-5）

設計:
  - メインウィンドウの centralWidget を parent とした child widget
  - _PanelDragBar による移動（上部ドラッグバーのみで移動）
  - mousePressEvent 等を override してマウスイベントが親へ伝播しないよう遮断
  - close() / hide() で UI を隠す（実行中なら abort 通知）
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QDoubleSpinBox,
    QPushButton, QProgressBar, QTextEdit, QGroupBox, QMessageBox, QScrollArea,
)
from panel_widgets import _PanelDragBar, _PanelGrip, install_panel_context_menu


class SequentialSpinDialog(QWidget):
    """被りなし連続抽選の専用 UI パネル（メインウィンドウ内 child widget）。

    i026: QDialog から QWidget に変更。同一ウィンドウ内に描画されるため
          OBS のウィンドウキャプチャに映る。
    i027: _PanelDragBar 追加。マウスイベント遮断で親側誤伝播を防ぐ。

    Signals:
        start_requested(int, float): 開始要求 (n, hold_sec)
        abort_requested():           中断要求
    """

    start_requested = Signal(int, float)
    abort_requested = Signal()
    geometry_changed = Signal()          # i038: 他パネルと同形式（位置保存・前面化用）

    def __init__(self, roulette_label: str, pattern_label: str,
                 max_n: int, design=None, parent=None):
        super().__init__(parent)
        # i051: _bring_panel_to_front が参照する panel 契約属性
        self.pinned_front = False
        # i035: 最小サイズ（PanelInputFilter のリサイズで縮めすぎない下限）
        self.setMinimumSize(360, 250)
        # i026: ウィンドウフラグを設定しない（child widget として描画）
        # i028: WA_StyledBackground を立てることで stylesheet の background-color を描画する。
        #       これがないと MainWindow の WA_TranslucentBackground が透過して見える。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # i036: PanelInputFilter による hover cursor プレビューを有効にする
        self.setMouseTracking(True)
        self._is_running = False
        self._design = design
        self._drag_bar_changed_handler = None  # i038: open 時に外部から設定される
        self._build_ui(roulette_label, pattern_label, max_n)
        if design is not None:
            self._apply_design(design)

    # ================================================================
    #  UI 構築
    # ================================================================

    def _build_ui(self, roulette_label: str, pattern_label: str, max_n: int):
        # i038: 外枠レイアウトは spacing=0・margin=0 で、drag bar + inner content の構成にする
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # i038: 上部ドラッグバー（他パネルと同形式）
        if self._design is not None:
            self._drag_bar = _PanelDragBar(self, self._design, parent=self)
            layout.addWidget(self._drag_bar)
            install_panel_context_menu(
                self, self._drag_bar, "実行パネル設定",
                on_drag_bar_changed=self._on_drag_bar_changed,
            )
        else:
            self._drag_bar = None

        # i038: 内側コンテンツ領域（底辺マージンを outer から移動）
        inner = QVBoxLayout()
        inner.setSpacing(10)
        inner.setContentsMargins(14, 8, 14, 14)
        layout.addLayout(inner, stretch=1)

        # ── 対象表示 ──────────────────────────────────────────
        tg = QGroupBox("対象")
        tg_v = QVBoxLayout(tg)
        tg_v.setSpacing(4)
        self._lbl_roulette = QLabel(f"ルーレット: {roulette_label}")
        self._lbl_pattern = QLabel(f"パターン:　 {pattern_label}")
        self._lbl_on_count = QLabel(f"ON 項目数:  {max_n}")
        for w in (self._lbl_roulette, self._lbl_pattern, self._lbl_on_count):
            tg_v.addWidget(w)
        inner.addWidget(tg)

        # ── 設定 ──────────────────────────────────────────────
        cg = QGroupBox("設定")
        cg_v = QVBoxLayout(cg)
        cg_v.setSpacing(6)

        row_n = QHBoxLayout()
        row_n.addWidget(QLabel("実行回数:"))
        self._spin_n = QSpinBox()
        # i028: 上限は ON 項目数 - 1（最後の 1 件は残す仕様）
        max_exec = max(1, max_n - 1)
        self._spin_n.setRange(1, max_exec)
        self._spin_n.setValue(min(max_exec, 5))
        self._spin_n.setSuffix(" 回")
        row_n.addWidget(self._spin_n)
        row_n.addStretch()
        cg_v.addLayout(row_n)

        row_h = QHBoxLayout()
        row_h.addWidget(QLabel("結果表示:"))
        self._spin_hold = QDoubleSpinBox()
        self._spin_hold.setRange(0.5, 30.0)
        self._spin_hold.setValue(3.0)
        self._spin_hold.setSingleStep(0.5)
        self._spin_hold.setSuffix(" 秒")
        row_h.addWidget(self._spin_hold)
        row_h.addStretch()
        cg_v.addLayout(row_h)
        inner.addWidget(cg)

        # ── 状態 / 進捗 ──────────────────────────────────────
        self._lbl_status = QLabel("待機中")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(self._lbl_status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        inner.addWidget(self._progress)

        # ── 項目一覧（常時表示・実行中は状態を追従） ──────────
        # i034: 実行前から全件表示し、確率・ON/OFF・当選状態を表示する
        # i035: stretch=1 でダイアログ高さ変化に追従する
        self._items_group = QGroupBox("項目一覧")
        _ig_layout = QVBoxLayout(self._items_group)
        _ig_layout.setContentsMargins(8, 4, 8, 4)
        _ig_layout.setSpacing(2)

        _items_scroll = QScrollArea()
        _items_scroll.setWidgetResizable(True)
        # i035: 最大高制限を撤廃してダイアログリサイズで拡張できるようにする
        _items_scroll.setMinimumHeight(80)
        _items_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _items_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._items_container = QWidget()
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(2, 2, 2, 2)
        self._items_layout.setSpacing(1)
        self._items_layout.addStretch()
        _items_scroll.setWidget(self._items_container)
        _ig_layout.addWidget(_items_scroll, stretch=1)
        inner.addWidget(self._items_group, stretch=1)

        # ── 結果リスト（完了 / 中断後に展開） ────────────────
        self._result_box = QTextEdit()
        self._result_box.setReadOnly(True)
        self._result_box.setMinimumHeight(100)
        self._result_box.setMaximumHeight(200)
        self._result_box.hide()
        inner.addWidget(self._result_box)

        # ── ボタン行 ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("開始")
        self._btn_abort = QPushButton("中断")
        self._btn_abort.setEnabled(False)
        self._btn_close = QPushButton("閉じる")
        for b in (self._btn_start, self._btn_abort, self._btn_close):
            btn_row.addWidget(b)
        inner.addLayout(btn_row)

        self._btn_start.clicked.connect(self._on_start_clicked)
        self._btn_abort.clicked.connect(self.abort_requested)
        self._btn_close.clicked.connect(self.close)

        # i038: 右下リサイズグリップ（他パネルと同形式）
        if self._design is not None:
            self._resize_grip = _PanelGrip(
                self, self._design, mode="panel",
                min_w=self.minimumWidth(), min_h=self.minimumHeight(),
                parent=self,
            )
        else:
            self._resize_grip = None

    def _apply_design(self, design):
        """デザイン設定に合わせてスタイルを適用する。"""
        d = design
        self.setStyleSheet(f"""
            SequentialSpinDialog {{
                background-color: {d.panel};
            }}
            QGroupBox {{
                color: {d.text};
                font-family: Meiryo;
                font-size: 10pt;
                border: 1px solid {d.separator};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
            }}
            QGroupBox::title {{
                color: {d.text};
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
            QLabel, QSpinBox, QDoubleSpinBox, QTextEdit, QProgressBar {{
                color: {d.text};
                background-color: {d.panel};
                font-family: Meiryo;
                font-size: 10pt;
            }}
            QSpinBox, QDoubleSpinBox {{
                border: 1px solid {d.separator};
                border-radius: 3px;
                padding: 2px 4px;
            }}
            QTextEdit {{
                border: 1px solid {d.separator};
                border-radius: 3px;
            }}
            QPushButton {{
                color: {d.text};
                background-color: {d.panel};
                border: 1px solid {d.separator};
                border-radius: 4px;
                padding: 5px 12px;
                font-family: Meiryo;
                font-size: 10pt;
            }}
            QPushButton:hover {{
                background-color: {d.separator};
            }}
            QPushButton:disabled {{
                color: gray;
            }}
        """)

    # ================================================================
    #  公開 API（SequentialSpinMixin から呼ばれる）
    # ================================================================

    def update_target(self, pattern_label: str, on_count: int, max_exec: int):
        """パターン変更時の表示を更新する（i028）。

        Args:
            pattern_label: 新しいパターン名
            on_count:      新しい ON 項目数
            max_exec:      新しい最大実行回数（= on_count - 1）
        """
        self._lbl_pattern.setText(f"パターン:　 {pattern_label}")
        self._lbl_on_count.setText(f"ON 項目数:  {on_count}")
        safe_max = max(1, max_exec)
        self._spin_n.setRange(1, safe_max)
        # 現在値が新上限を超えていればクランプ
        self._spin_n.setValue(min(self._spin_n.value(), safe_max))

    def set_running(self, running: bool, step: int = 0, total: int = 0):
        """実行状態に合わせて UI を切り替える。"""
        self._is_running = running
        self._btn_start.setEnabled(not running)
        self._btn_abort.setEnabled(running)
        self._spin_n.setEnabled(not running)
        self._spin_hold.setEnabled(not running)
        if running:
            self._progress.setRange(0, total if total > 0 else 1)
            self._progress.setValue(step)
            self._lbl_status.setText(f"実行中... {step}/{total}")
        else:
            if step == 0:
                self._lbl_status.setText("待機中")

    def update_items(self, items: list):
        """項目一覧を更新する（実行前・実行中どちらからも呼ばれる）。

        i034: 全項目を名前・確率・状態で表示する。

        Args:
            items: [(text, prob_pct, is_on, is_won), ...]
                   - prob_pct: 現時点の確率(%)。is_on=False なら 0.0。
                   - is_on: True = 有効（まだ当選していない）
                   - is_won: True = 当選済（一時 OFF）
        """
        # 既存行を全消去（末尾の stretch を除く）
        layout = self._items_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        d = self._design
        _col_won  = d.text_sub if d else "gray"
        _col_on   = d.text if d else "white"
        _col_off  = d.text_sub if d else "gray"

        for text, prob_pct, is_on, is_won in items:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(2, 1, 2, 1)
            row_layout.setSpacing(6)

            name_lbl = QLabel(text)
            name_lbl.setFont(QFont("Meiryo", 9))

            if is_won:
                name_lbl.setStyleSheet(
                    f"color: {_col_won}; text-decoration: line-through;"
                )
                state_lbl = QLabel("✓")
                state_lbl.setFont(QFont("Meiryo", 8))
                state_lbl.setStyleSheet(f"color: {_col_won};")
                prob_lbl = QLabel("—")
                prob_lbl.setFont(QFont("Meiryo", 8))
                prob_lbl.setStyleSheet(f"color: {_col_won};")
            elif is_on:
                name_lbl.setStyleSheet(f"color: {_col_on};")
                state_lbl = QLabel("ON")
                state_lbl.setFont(QFont("Meiryo", 8))
                state_lbl.setStyleSheet(f"color: {_col_on};")
                prob_lbl = QLabel(f"{prob_pct:.1f}%")
                prob_lbl.setFont(QFont("Meiryo", 8))
                prob_lbl.setStyleSheet(f"color: {_col_on};")
            else:
                # 最初から OFF の項目
                name_lbl.setStyleSheet(f"color: {_col_off};")
                state_lbl = QLabel("OFF")
                state_lbl.setFont(QFont("Meiryo", 8))
                state_lbl.setStyleSheet(f"color: {_col_off};")
                prob_lbl = QLabel("0.0%")
                prob_lbl.setFont(QFont("Meiryo", 8))
                prob_lbl.setStyleSheet(f"color: {_col_off};")

            row_layout.addWidget(name_lbl, stretch=1)
            row_layout.addWidget(state_lbl)
            row_layout.addWidget(prob_lbl)
            layout.insertWidget(layout.count() - 1, row)

        self._items_container.adjustSize()

    def update_step(self, step: int, total: int):
        """進捗を更新する（各 spin 完了時）。"""
        self._progress.setRange(0, total)
        self._progress.setValue(step)
        self._lbl_status.setText(f"実行中... {step}/{total}")

    def show_results(self, results: list, aborted: bool = False):
        """最終結果リストを表示する（§4-5）。

        Args:
            results: [(step, winner), ...]
            aborted: 中断の場合は True
        """
        lines = ["＝ 抽選結果 ＝"]
        for step, winner in results:
            lines.append(f"  {step}回目: {winner}")
        if aborted:
            lines.append("  （中断）")
        self._result_box.setPlainText("\n".join(lines))
        self._result_box.show()
        self._lbl_status.setText("中断" if aborted else "完了")
        if results:
            self._progress.setValue(len(results))

    def reset_after_run(self, items: list):
        """実行完了/中断後に項目一覧を初期状態へ戻し、結果表示を隠す（i035）。

        Args:
            items: 初期状態の項目リスト [(text, prob_pct, is_on, is_won), ...]
        """
        self._result_box.hide()
        self._result_box.clear()
        self._lbl_status.setText("待機中")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self.update_items(items)

    def show_error(self, msg: str):
        """エラーメッセージをダイアログ表示する。"""
        QMessageBox.warning(self, "被りなし連続抽選", msg)

    def update_design(self, design):
        """デザインを更新する。"""
        self._design = design
        self._apply_design(design)
        if hasattr(self, '_drag_bar') and self._drag_bar is not None:
            self._drag_bar.update_design(design)
        if hasattr(self, '_resize_grip') and self._resize_grip is not None:
            self._resize_grip.update_design(design)

    # ================================================================
    #  geometry イベント（i038: 他パネルと同形式）
    # ================================================================

    def moveEvent(self, event):
        """パネル移動時に通知する。"""
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        """リサイズグリップを右下に追従させ、位置変化を通知する。"""
        super().resizeEvent(event)
        if hasattr(self, '_resize_grip') and self._resize_grip is not None:
            self._resize_grip.reposition()
        self.geometry_changed.emit()

    def _on_drag_bar_changed(self, visible: bool):
        """移動バー表示変更をハンドラ経由で通知する。

        _drag_bar_changed_handler が設定されていれば呼び出す。
        SequentialSpinMixin._open_sequential_spin_dialog で設定される。
        """
        if self._drag_bar_changed_handler is not None:
            self._drag_bar_changed_handler(visible)

    # ================================================================
    #  マウスイベント遮断（i027）
    # ================================================================
    # child widget のマウスイベントがデフォルトで親へ伝播すると、
    # RoulettePanel のドラッグ判定や MainWindow のウィンドウドラッグが
    # 誤作動する。このパネル自体のクライアント領域クリックは
    # ここで消費して親へ伝播させない。
    # （ドラッグ移動は _drag_bar が専用に担当する）

    def mousePressEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    # ================================================================
    #  内部イベント
    # ================================================================

    def _on_start_clicked(self):
        self.start_requested.emit(self._spin_n.value(), self._spin_hold.value())

    def closeEvent(self, event):
        """閉じる / hide 時: 実行中なら中断要求を emit する。"""
        if self._is_running:
            self.abort_requested.emit()
        super().closeEvent(event)
