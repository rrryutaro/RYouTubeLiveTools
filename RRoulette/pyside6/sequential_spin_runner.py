"""
sequential_spin_runner.py — 被りなし連続抽選ランナー

i021: マクロ機能の初回実用化として実装する被りなし連続抽選の制御クラス。

動作フロー:
  1. start() → ON/OFFスナップショット取得・実行開始
  2. on_spin_finished(winner) → 当選項目を一時OFF・セグメント再構築・hold タイマー開始
  3. hold タイマー満了 → オーバーレイ dismiss → 次ステップへ
  4. 全回完了 / 中断 → ON/OFF状態を復元して run_finished / run_aborted を emit

設計方針 (§3):
  - 保存済みパターンデータは変更しない（メモリ内の一時変更のみ）
  - 既存の spin / result 導線をそのまま使う（新規乱数ロジック不要）
  - 統計・グラフ機能には広げない
"""

from PySide6.QtCore import QObject, Signal, QTimer

from segment_builder import build_segments_from_entries


class SequentialSpinRunner(QObject):
    """被りなし連続抽選の制御クラス。

    SequentialSpinMixin から利用される。MainWindow の子として生成し、
    spin 完了通知 (on_spin_finished) を受け取って連続制御を行う。

    Signals:
        step_completed(int, str): 1回の抽選完了 (1-indexed step, winner_text)
        run_finished(list):       全回完了 [(step, winner), ...]
        run_aborted(list):        中断 [(step, winner), ...] (途中まで)
        run_error(str):           実行中エラーメッセージ
        next_spin_needed():       次のスピン開始を mixin に要求
        state_changed():          状態変更通知（ダイアログ UI 更新用）
    """

    step_completed = Signal(int, str)
    run_finished = Signal(list)
    run_aborted = Signal(list)
    run_error = Signal(str)
    next_spin_needed = Signal()
    state_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running: bool = False
        self._total: int = 0
        self._hold_sec: float = 3.0
        self._step: int = 0
        self._results: list[tuple[int, str]] = []
        self._ctx = None           # RouletteContext
        self._config: dict = {}
        self._snapshot: list[bool] | None = None  # 実行前の enabled フラグ列

        # 結果表示 hold タイマー（各回の結果を指定秒数だけ保持する）
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._on_hold_timeout)

    # ================================================================
    #  プロパティ
    # ================================================================

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_step(self) -> int:
        return self._step

    @property
    def total_steps(self) -> int:
        return self._total

    # ================================================================
    #  公開 API
    # ================================================================

    def start(self, ctx, config: dict, n: int, hold_sec: float) -> str | None:
        """連続抽選を開始する。

        Args:
            ctx:      RouletteContext（対象ルーレット）
            config:   アプリ設定 dict (build_segments_from_entries 用)
            n:        実行回数
            hold_sec: 各回の結果表示秒数

        Returns:
            エラーメッセージ。成功時は None。
        """
        if self._running:
            return "既に実行中です"

        enabled_count = sum(1 for e in ctx.item_entries if e.enabled)
        if n <= 0:
            return "実行回数は1以上を指定してください"
        if enabled_count == 0:
            return "ON状態の項目がありません"
        if n > enabled_count:
            return f"実行回数 {n} がON項目数 {enabled_count} を超えています"

        self._ctx = ctx
        self._config = config
        self._total = n
        self._hold_sec = max(0.5, hold_sec)
        self._step = 0
        self._results = []
        # 実行前の enabled 状態をスナップショット（インデックス順）
        self._snapshot = [e.enabled for e in ctx.item_entries]
        self._running = True
        self.state_changed.emit()
        return None

    def on_spin_finished(self, winner: str):
        """spin 完了時に SequentialSpinMixin から呼ばれる。

        当選項目を一時 OFF にしてセグメントを再構築し、
        hold_sec 後に次ステップへ進む hold タイマーを開始する。
        """
        if not self._running:
            return

        self._step += 1
        self._results.append((self._step, winner))

        # 当選項目の一時 OFF（同名の最初の ON 項目のみ）
        for entry in self._ctx.item_entries:
            if entry.enabled and entry.text == winner:
                entry.enabled = False
                break

        # セグメント再構築（次回 spin 用の wheel 表示更新）
        segs, _ = build_segments_from_entries(self._ctx.item_entries, self._config)
        self._ctx.segments = segs
        self._ctx.panel.set_segments(segs)

        self.step_completed.emit(self._step, winner)
        self.state_changed.emit()

        # hold_sec 後に次ステップへ
        self._hold_timer.start(int(self._hold_sec * 1000))

    def abort(self):
        """連続抽選を中断し、ON/OFF 状態を復元する。"""
        if not self._running:
            return
        self._hold_timer.stop()
        # オーバーレイが表示中であれば閉じる
        if self._ctx is not None and self._ctx.panel is not None:
            self._ctx.panel.result_overlay.dismiss()
        results = list(self._results)
        self._restore()
        self._running = False
        self.state_changed.emit()
        self.run_aborted.emit(results)

    # ================================================================
    #  内部処理
    # ================================================================

    def _on_hold_timeout(self):
        """hold タイマー満了 → オーバーレイを閉じて次ステップへ進む。"""
        if not self._running:
            return
        # オーバーレイが残っていれば閉じる（closed シグナルも emit される）
        if self._ctx is not None and self._ctx.panel is not None:
            self._ctx.panel.result_overlay.dismiss()
        self._proceed()

    def _proceed(self):
        """次ステップへ or 全回完了処理。"""
        if not self._running:
            return

        if self._step >= self._total:
            self._do_finish()
            return

        # 次回 spin のために ON 項目が残っているか確認
        enabled = sum(1 for e in self._ctx.item_entries if e.enabled)
        if enabled == 0:
            self.run_error.emit(
                f"{self._step}回完了後、ON状態の候補が尽きました。\n"
                f"ここまでの結果で終了します。"
            )
            self._do_finish()
            return

        self.next_spin_needed.emit()

    def _do_finish(self):
        """全回完了処理。状態復元して run_finished を emit する。"""
        results = list(self._results)
        self._restore()
        self._running = False
        self.state_changed.emit()
        self.run_finished.emit(results)

    def _restore(self):
        """実行前の ON/OFF 状態を復元し、セグメントを再構築する。"""
        if self._snapshot is None or self._ctx is None:
            return
        for i, entry in enumerate(self._ctx.item_entries):
            if i < len(self._snapshot):
                entry.enabled = self._snapshot[i]
        segs, _ = build_segments_from_entries(self._ctx.item_entries, self._config)
        self._ctx.segments = segs
        self._ctx.panel.set_segments(segs)
        self._snapshot = None
        self._ctx = None
