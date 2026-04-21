"""
sequential_spin_mixin.py — 被りなし連続抽選 Mixin

i021: MainWindow に組み込み、被りなし連続抽選機能を提供する。
i022: OBS 表示対応 / 色維持 / ログチャンク対応を追加。

責務:
  - 専用ダイアログの開閉管理 (_open_sequential_spin_dialog)
  - SequentialSpinRunner のライフサイクル管理
  - spin 完了通知の受け渡し (_notify_seq_spin_finished)
    → spin_flow_mixin._on_spin_finished から呼ばれる
  - 実行 / 中断シグナルの処理
  - i022: RoulettePanel 内に OBS キャプチャ対象の進行状態を表示
  - i022: 完了後に連続抽選結果をログチャンクとして記録

連携ポイント:
  - spin_flow_mixin._start_spin:
      runner 実行中は手動 spin をブロック（spin_flow_mixin 側で guard）
  - spin_flow_mixin._on_spin_finished:
      完了 winner を runner に渡す (_notify_seq_spin_finished を呼ぶ)
      連続抽選中は個別ログエントリ追加を抑制（spin_flow_mixin 側で guard）
  - item_entries_mixin._update_items_by_action:
      項目編集が来たら runner を abort する（item_entries_mixin 側で guard）

使用側:
  class MainWindow(SequentialSpinMixin, MacroFlowMixin, ..., QMainWindow)
"""


class SequentialSpinMixin:
    """被りなし連続抽選の制御責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # SequentialSpinRunner / ダイアログ（遅延生成、None=未生成）
    _seq_runner = None
    _seq_dialog = None
    _seq_runner_roulette_id: str = ""

    # ================================================================
    #  ヘルパー
    # ================================================================

    def _get_seq_panel(self):
        """連続抽選対象の RoulettePanel を返す。未設定なら None。"""
        if not self._seq_runner_roulette_id:
            return None
        ctx = self._manager.get(self._seq_runner_roulette_id)
        return ctx.panel if ctx else None

    # ================================================================
    #  ダイアログ起動
    # ================================================================

    def _toggle_sequential_spin_dialog(self):
        """被りなし連続抽選パネルのトグル（F5 用）。

        表示中なら hide、非表示なら open する。
        """
        if self._seq_dialog is not None and self._seq_dialog.isVisible():
            self._seq_dialog.hide()
            self._sync_manage_panel_checks()
        else:
            self._open_sequential_spin_dialog()

    def _open_sequential_spin_dialog(self):
        """被りなし連続抽選パネルを開く（重複起動防止）。

        右クリックメニューからの起動を想定。
        アクティブルーレットと現在パターンを対象として表示する。

        i026: QDialog（別ウィンドウ）から centralWidget 内 child widget へ変更。
              OBS のウィンドウキャプチャに映る。
        """
        # 既にパネルが開いていれば前面に出すだけ
        if self._seq_dialog is not None and self._seq_dialog.isVisible():
            self._seq_dialog.raise_()
            return

        ctx = self._manager.active
        if ctx is None:
            return

        max_n = sum(1 for e in ctx.item_entries if e.enabled)
        if max_n <= 1:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "被りなし連続抽選",
                                "ON 状態の項目が2つ以上必要です。")
            return

        # Runner を遅延生成（初回のみ）
        if self._seq_runner is None:
            self._init_seq_runner()

        roulette_label = ctx.roulette_id
        pattern_label = ctx.current_pattern or "デフォルト"

        # i026: centralWidget を parent にすることで同一ウィンドウ内 child widget になる
        central = self.centralWidget()
        from sequential_spin_dialog import SequentialSpinDialog

        # i036: 古いダイアログを PanelInputFilter から除去してから新規生成
        _pif = getattr(self, '_panel_input_filter', None)
        if _pif is not None and self._seq_dialog is not None:
            _pif.remove_drag_panel(self._seq_dialog)

        dlg = SequentialSpinDialog(
            roulette_label, pattern_label, max_n,
            design=self._design, parent=central,
        )
        dlg.start_requested.connect(self._on_seq_start_requested)
        dlg.abort_requested.connect(self._on_seq_abort_requested)
        self._seq_dialog = dlg

        # i036: PanelInputFilter の共通対象へ登録（右端/下端/角リサイズ・drag-anywhere）
        if _pif is not None:
            _pif.add_drag_panel(dlg)

        # i038: geometry_changed を保存タイマーと前面化ハンドラに接続
        if hasattr(self, '_panel_save_timer'):
            dlg.geometry_changed.connect(self._panel_save_timer.start)
        dlg.geometry_changed.connect(lambda: self._bring_panel_to_front(dlg))

        # i038: 移動バー表示設定を反映し、変更時に設定保存
        _drag_bar_vis = getattr(self._settings, 'seq_panel_drag_bar_visible', True)
        if dlg._drag_bar is not None:
            dlg._drag_bar.setVisible(_drag_bar_vis)

        def _on_seq_drag_bar_changed(visible: bool):
            self._settings.seq_panel_drag_bar_visible = visible
            self._save_config()
        dlg._drag_bar_changed_handler = _on_seq_drag_bar_changed

        # i034: ダイアログ表示前に初期項目一覧を設定（実行前状態で確率付き表示）
        dlg.update_items(self._build_initial_seq_items(ctx))

        # i038: 保存済み位置があれば復元、なければ右上付近のデフォルト配置
        dlg.adjustSize()
        _s = self._settings
        if _s.seq_panel_x is not None and _s.seq_panel_y is not None:
            _sw = _s.seq_panel_width or dlg.width()
            _sh = _s.seq_panel_height or dlg.height()
            # centralWidget 内にクランプして配置
            _pw = central.width()
            _ph = central.height()
            from panel_widgets import _MW_DRAG_BAR_H
            _cx = max(0, min(_s.seq_panel_x, _pw - _sw))
            _cy = max(_MW_DRAG_BAR_H, min(_s.seq_panel_y, _ph - _sh))
            dlg.resize(_sw, _sh)
            dlg.move(_cx, _cy)
        else:
            # デフォルト: centralWidget 内の右上付近
            margin = 10
            from panel_widgets import _MW_DRAG_BAR_H
            x = central.width() - dlg.width() - margin
            y = _MW_DRAG_BAR_H + margin  # 20 + 10 = 30px から開始
            dlg.move(max(0, x), y)
        dlg.show()
        dlg.raise_()
        self._sync_manage_panel_checks()

    # ================================================================
    #  Runner 初期化
    # ================================================================

    def _init_seq_runner(self):
        """SequentialSpinRunner を生成してシグナルを接続する（初回のみ）。"""
        from sequential_spin_runner import SequentialSpinRunner
        self._seq_runner = SequentialSpinRunner(parent=self)
        self._seq_runner.step_completed.connect(self._on_seq_step_completed)
        self._seq_runner.run_finished.connect(self._on_seq_run_finished)
        self._seq_runner.run_aborted.connect(self._on_seq_run_aborted)
        self._seq_runner.run_error.connect(self._on_seq_run_error)
        self._seq_runner.next_spin_needed.connect(self._on_seq_next_spin_needed)
        self._seq_runner.state_changed.connect(self._on_seq_state_changed)
        self._seq_runner.items_updated.connect(self._on_seq_items_updated)

    # ================================================================
    #  開始 / 中断
    # ================================================================

    def _on_seq_start_requested(self, n: int, hold_sec: float):
        """ダイアログの「開始」ボタンから呼ばれる。"""
        if self._seq_runner is None:
            return
        ctx = self._manager.active
        if ctx is None:
            return
        if self._is_any_spinning():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._seq_dialog, "被りなし連続抽選",
                                "スピン中のため開始できません。")
            return

        self._seq_runner_roulette_id = ctx.roulette_id
        err = self._seq_runner.start(ctx, self._config, n, hold_sec)
        if err:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._seq_dialog, "開始不可", err)
            return

        # i022: 1回目のスピン前に result prefix / OBS ステータスを設定
        ctx.panel.result_overlay.set_result_prefix(f"1/{n}回目: ")
        ctx.panel.update_seq_status(f"被りなし連続抽選  1/{n}回目")

        # 1回目のスピンを開始
        ok = self._spin_by_action(ctx.roulette_id)
        if not ok:
            # スピン開始失敗 → 中断して状態を戻す
            self._seq_runner.abort()

    def _on_seq_abort_requested(self):
        """ダイアログの「中断」ボタン / ×ボタンから呼ばれる。"""
        if self._seq_runner is not None and self._seq_runner.is_running:
            self._seq_runner.abort()

    # ================================================================
    #  spin_flow_mixin から呼ばれるフック
    # ================================================================

    def _notify_seq_spin_finished(self, winner: str, roulette_id: str):
        """spin_flow_mixin._on_spin_finished から呼ばれる。

        アクティブな sequential spin が対象ルーレットの spin を待っていた場合、
        runner に winner を渡して次ステップの制御を委ねる。
        """
        if (self._seq_runner is not None
                and self._seq_runner.is_running
                and roulette_id == self._seq_runner_roulette_id):
            self._seq_runner.on_spin_finished(winner)

    # ================================================================
    #  Runner シグナルハンドラ
    # ================================================================

    def _on_seq_next_spin_needed(self):
        """runner が次のスピン開始を要求した。"""
        panel = self._get_seq_panel()
        if panel is not None and self._seq_runner is not None:
            next_step = self._seq_runner.current_step + 1
            total = self._seq_runner.total_steps
            # i022: result prefix と OBS ステータスを次のステップ番号に更新
            panel.result_overlay.set_result_prefix(f"{next_step}/{total}回目: ")
            panel.update_seq_status(f"被りなし連続抽選  {next_step}/{total}回目")

        ok = self._spin_by_action(self._seq_runner_roulette_id)
        if not ok and self._seq_runner is not None:
            self._seq_runner.abort()

    def _on_seq_step_completed(self, step: int, winner: str):
        """1回の抽選完了時にダイアログ進捗を更新する。"""
        if self._seq_dialog is not None and self._seq_runner is not None:
            self._seq_dialog.update_step(step, self._seq_runner.total_steps)

    def _on_seq_run_finished(self, results: list):
        """全回完了時の処理。"""
        # i022: ログチャンクを追加・保存
        self._add_seq_chunk_log(results, aborted=False)
        # i022: OBS ステータスと result prefix をクリア
        panel = self._get_seq_panel()
        if panel is not None:
            panel.update_seq_status("")
            panel.result_overlay.set_result_prefix("")

        if self._seq_dialog is not None:
            self._seq_dialog.set_running(False, len(results), len(results))
            self._seq_dialog.show_results(results, aborted=False)

        # 最終結果をホイール側にも全結果サマリーとして表示する。
        # roulette_only で連続抽選パネルが非表示の場合でも、ホイールだけで確認できるようにする。
        if panel is not None and results:
            panel.result_overlay.show_summary(results)

        # i035: 項目一覧を実行前の初期状態へ戻す（ルーレット本体と同期）
        if self._seq_dialog is not None and self._seq_runner_roulette_id:
            ctx = self._manager.get(self._seq_runner_roulette_id)
            if ctx is not None:
                self._seq_dialog.reset_after_run(self._build_initial_seq_items(ctx))

    def _on_seq_run_aborted(self, results: list):
        """中断時の処理。"""
        # i022: 途中結果をログチャンクとして追加（中断フラグあり）
        if results:
            self._add_seq_chunk_log(results, aborted=True)
        # i022: OBS ステータスと result prefix をクリア
        panel = self._get_seq_panel()
        if panel is not None:
            panel.update_seq_status("")
            panel.result_overlay.set_result_prefix("")

        if self._seq_dialog is not None:
            total = (self._seq_runner.total_steps
                     if self._seq_runner is not None else 0)
            self._seq_dialog.set_running(False, len(results), total)
            self._seq_dialog.show_results(results, aborted=True)

        # i035: 項目一覧を実行前の初期状態へ戻す
        if self._seq_dialog is not None and self._seq_runner_roulette_id:
            ctx = self._manager.get(self._seq_runner_roulette_id)
            if ctx is not None:
                self._seq_dialog.reset_after_run(self._build_initial_seq_items(ctx))

    def _on_seq_run_error(self, msg: str):
        """実行中エラー（候補不足等）の通知。"""
        if self._seq_dialog is not None:
            self._seq_dialog.show_error(msg)

    def _on_seq_state_changed(self):
        """runner 状態変更時にダイアログ全体の表示を同期する。"""
        if self._seq_dialog is not None and self._seq_runner is not None:
            self._seq_dialog.set_running(
                self._seq_runner.is_running,
                self._seq_runner.current_step,
                self._seq_runner.total_steps,
            )

    def _on_seq_items_updated(self, items: list):
        """項目一覧の更新をダイアログへ転送する（i034: 新フォーマット対応）。"""
        if self._seq_dialog is not None:
            self._seq_dialog.update_items(items)

    # ================================================================
    #  項目一覧の即時更新（i035）
    # ================================================================

    def _refresh_seq_dialog_items(self):
        """項目パネル編集後に実行パネルの項目一覧を即時更新する（i035）。

        実行中は runner の items_updated シグナルが管理するため更新しない。
        item_entries_mixin._update_items_by_action() から getattr 経由で呼ばれる。
        """
        dlg = self._seq_dialog
        if dlg is None or not dlg.isVisible():
            return
        if self._seq_runner is not None and self._seq_runner.is_running:
            return
        if self._seq_runner_roulette_id:
            ctx = self._manager.get(self._seq_runner_roulette_id)
        else:
            ctx = self._manager.active
        if ctx is None:
            return
        dlg.update_items(self._build_initial_seq_items(ctx))

    # ================================================================
    #  初期項目一覧構築（i034）
    # ================================================================

    def _build_initial_seq_items(self, ctx) -> list:
        """ダイアログ開時の初期項目一覧を構築する。

        実行前状態（全項目 is_won=False）で確率付きリストを返す。
        フォーマット: [(text, prob_pct, is_on, is_won), ...]
        """
        from segment_builder import build_segments_from_entries
        entries = ctx.item_entries
        enabled = [e for e in entries if e.enabled]
        if enabled:
            segs, _ = build_segments_from_entries(enabled, self._config)
            prob_map: dict[str, float] = {}
            for seg in segs:
                prob_map[seg.item_text] = (
                    prob_map.get(seg.item_text, 0.0) + seg.arc / 360.0 * 100.0
                )
        else:
            prob_map = {}
        items = []
        for entry in entries:
            is_on = entry.enabled
            prob_pct = prob_map.get(entry.text, 0.0) if is_on else 0.0
            items.append((entry.text, prob_pct, is_on, False))
        return items

    # ================================================================
    #  ログチャンク記録（i022）
    # ================================================================

    def _add_seq_chunk_log(self, results: list, aborted: bool):
        """連続抽選の結果を 1 チャンクとして WheelWidget に記録する。

        i022: 個別ログが抑制されていた分を、全結果まとめて 1 チャンクで追記する。
        完了 / 中断どちらの場合も記録する（中断時はヘッダーに「中断」を追記）。
        """
        if not self._seq_runner_roulette_id:
            return
        ctx = self._manager.get(self._seq_runner_roulette_id)
        if ctx is None:
            return
        n = len(results)
        if n == 0:
            return
        total = (self._seq_runner.total_steps
                 if self._seq_runner is not None else n)
        suffix = "（中断）" if aborted else ""
        header = f"被りなし連続抽選 {n}/{total}回{suffix}"
        pattern_id = self._get_current_pattern_id(ctx)
        ctx.panel.wheel.add_log_chunk(header, results, pattern_id)
        ctx.panel.wheel.save_log(self._roulette_log_path(self._seq_runner_roulette_id))

    # ================================================================
    #  パターン変更追従（i028）
    # ================================================================

    def _sync_seq_panel_to_active_pattern(self):
        """アクティブパターンが変わったとき、連続抽選パネルの表示を更新する。

        i028: パターン変更時に対象パターン名・ON 項目数・実行回数上限を即時反映する。
        実行中は現在の連続抽選対象を固定するため更新しない。
        """
        dlg = self._seq_dialog
        if dlg is None or not dlg.isVisible():
            return
        # 実行中は対象をブラさないため更新しない
        if self._seq_runner is not None and self._seq_runner.is_running:
            return
        ctx = self._manager.active
        if ctx is None:
            return
        on_count = sum(1 for e in ctx.item_entries if e.enabled)
        max_exec = on_count - 1  # i028: 上限は ON 項目数 - 1
        pattern_label = ctx.current_pattern or "デフォルト"
        dlg.update_target(pattern_label, on_count, max_exec)
        # i034: パターン変更時に項目一覧も更新する（確率再計算）
        dlg.update_items(self._build_initial_seq_items(ctx))
