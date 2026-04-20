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
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QDoubleSpinBox,
    QPushButton, QProgressBar, QTextEdit, QGroupBox, QMessageBox,
)


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

    def __init__(self, roulette_label: str, pattern_label: str,
                 max_n: int, design=None, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(360)
        # i026: ウィンドウフラグを設定しない（child widget として描画）
        # i028: WA_StyledBackground を立てることで stylesheet の background-color を描画する。
        #       これがないと MainWindow の WA_TranslucentBackground が透過して見える。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._is_running = False
        self._design = design   # i027: _build_ui より前に保持（_PanelDragBar 生成に使用）
        self._drag_bar = None
        self._build_ui(roulette_label, pattern_label, max_n)
        if design is not None:
            self._apply_design(design)

    # ================================================================
    #  UI 構築
    # ================================================================

    def _build_ui(self, roulette_label: str, pattern_label: str, max_n: int):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 14)

        # ── i027: 上部ドラッグバー ─────────────────────────────
        # _PanelDragBar はドラッグ時に self（SequentialSpinDialog）を
        # parentWidget()（centralWidget）内で move() する。
        if self._design is not None:
            from panel_widgets import _PanelDragBar
            self._drag_bar = _PanelDragBar(self, self._design, parent=self)
            layout.addWidget(self._drag_bar)

        inner = QVBoxLayout()
        inner.setSpacing(10)
        inner.setContentsMargins(14, 0, 14, 0)
        layout.addLayout(inner)

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
        self.adjustSize()

    def show_error(self, msg: str):
        """エラーメッセージをダイアログ表示する。"""
        QMessageBox.warning(self, "被りなし連続抽選", msg)

    def update_design(self, design):
        """デザインを更新する。"""
        self._design = design
        self._apply_design(design)
        if self._drag_bar is not None:
            self._drag_bar.update_design(design)

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
