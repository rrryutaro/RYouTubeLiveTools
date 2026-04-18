"""
macro_flow_mixin.py — マクロ実行フロー Mixin

i444: main_window.py から分離。
責務:
  - マクロ記録操作 (_toggle_recording, _dump_recording, _dev_save_recording,
                    _dev_load_to_session)
  - マクロセッション操作 (_dev_step_action, _dev_clear_session,
                          _dev_show_action_viewer, _show_recording_preview)
  - 自動進行 (_dev_run_until_pause, _stop_auto_advance)
  - 分岐評価 (_handle_branch_on_winner, _eval_single_condition)
  - viewer / overlay 連携 (_notify_macro_viewer, _on_result_overlay_closed,
                            _try_resume_macro_after_overlay)

使用側:
  class MainWindow(MacroFlowMixin, DesignGraphMixin, ..., QMainWindow)
"""

import re

from roulette_actions import BranchOnWinner, ActionOrigin, SpinRoulette


class MacroFlowMixin:
    """マクロ実行フローと分岐評価の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # 開発確認用の固定保存パス
    _DEV_MACRO_PATH = "dev_macro.json"

    # ================================================================
    #  マクロ記録操作
    # ================================================================

    def _toggle_recording(self):
        """開発確認用: recording ON/OFF を切り替える。"""
        if self._recorder.is_recording:
            self._recorder.stop()
        else:
            self._recorder.clear()
            self._recorder.start()
        self._update_title_active_id()

    def _dump_recording(self):
        """開発確認用: 記録済みアクションを標準出力にダンプする。"""
        from roulette_action_codec import action_to_dict
        actions = self._recorder.snapshot()
        print(f"--- recording snapshot ({len(actions)} actions) ---")
        for i, a in enumerate(actions):
            print(f"  [{i}] {action_to_dict(a)}")
        print("--- end ---")

    def _dev_save_recording(self):
        """開発確認用: snapshot を固定パスへ JSON 保存する。"""
        from roulette_action_io import save_actions_json, ActionIOError
        actions = self._recorder.snapshot()
        if not actions:
            print("[dev] no actions to save")
            return
        try:
            save_actions_json(self._DEV_MACRO_PATH, actions)
            print(f"[dev] saved {len(actions)} actions to {self._DEV_MACRO_PATH}")
        except ActionIOError as e:
            print(f"[dev] save error: {e}")

    def _dev_load_to_session(self):
        """開発確認用: 固定パスから JSON 読込して macro session へセットする。"""
        from roulette_action_io import load_actions_json, ActionIOError
        try:
            actions = load_actions_json(self._DEV_MACRO_PATH)
            self._macro_session.load(actions)
            print(f"[dev] loaded {len(actions)} actions to session from {self._DEV_MACRO_PATH}")
            self._update_title_active_id()
        except ActionIOError as e:
            print(f"[dev] load error: {e}")

    # ================================================================
    #  マクロセッション操作
    # ================================================================

    def _dev_step_action(self) -> tuple[bool, str]:
        """開発確認用: session から次の1件を取り出して apply_action する。

        Returns:
            (成功フラグ, エラー詳細)。成功時は (True, "")。
        """
        from roulette_action_codec import action_summary as _summary

        if not self._macro_session.has_next():
            print("[dev] no more actions to step")
            return (False, "session が空です")
        action = self._macro_session.pop_next()

        # BranchOnWinner は apply_action に渡さず直接処理
        if isinstance(action, BranchOnWinner):
            ok = self._handle_branch_on_winner(action)
            if not ok:
                print("[dev] step branch FAILED — stopped")
            self._update_title_active_id()
            if ok:
                return (True, "")
            return (False, f"branch 評価失敗: {_summary(action)}")

        from roulette_action_codec import action_to_dict
        print(f"[dev] step [{self._macro_session.current_index}/{self._macro_session.total_count}] {action_to_dict(action)}")
        ok = self.apply_action(action, origin=ActionOrigin.MACRO)
        if not ok:
            self._macro_session.rewind_one()
            print(f"[dev] step FAILED — index rewound to {self._macro_session.current_index}")
        self._update_title_active_id()
        if ok:
            return (True, "")
        return (False, f"実行失敗: {_summary(action)}")

    def _dev_clear_session(self):
        """開発確認用: macro session をクリアする。"""
        if self._macro_auto_advancing:
            print("[dev] auto advance stopped — session cleared")
            self._stop_auto_advance()
        self._macro_session.clear()
        self._last_spin_result = None
        print("[dev] session cleared (last_spin_result cleared)")
        self._update_title_active_id()

    def _dev_show_action_viewer(self):
        """開発確認用: 現在の session / recorder の action 列を閲覧ダイアログで表示する。"""
        from macro_action_viewer import MacroActionViewer

        # session に action がある場合はそちらを表示、なければ recorder snapshot
        if self._macro_session.total_count > 0:
            actions = []
            for i in range(self._macro_session.total_count):
                if i < len(self._macro_session._actions):
                    actions.append(self._macro_session._actions[i])
            source = "session"
        else:
            actions = self._recorder.snapshot()
            source = "recorder"

        print(f"[dev] viewer: showing {len(actions)} actions from {source}")

        def apply_to_session(new_actions):
            self._macro_session.load(new_actions)
            print(f"[dev] viewer: applied {len(new_actions)} actions to session")
            self._update_title_active_id()

        viewer = MacroActionViewer(
            actions,
            active_roulette_id=self._manager.active_id,
            on_session_apply=apply_to_session,
            on_step=self._dev_step_action,
            on_run=self._dev_run_until_pause,
            session=self._macro_session,
            get_auto_advancing=lambda: self._macro_auto_advancing,
            parent=self,
        )
        viewer.setWindowTitle(f"マクロエディタ — {source}: {len(actions)} actions")
        self._macro_viewer = viewer
        viewer.exec()
        self._macro_viewer = None
        self._update_title_active_id()

    def _show_recording_preview(self):
        """記録中のアクション一覧をプレビュー表示する。"""
        from macro_action_viewer import MacroActionViewer

        actions = self._recorder.snapshot()
        if not actions:
            return

        viewer = MacroActionViewer(
            actions,
            active_roulette_id=self._manager.active_id,
            parent=self,
        )
        rec_status = "記録中" if self._recorder.is_recording else "記録済み"
        viewer.setWindowTitle(f"マクロエディタ — {rec_status}: {len(actions)} actions")
        viewer.exec()

    # ================================================================
    #  自動進行
    # ================================================================

    def _dev_run_until_pause(self) -> tuple[bool, str]:
        """開発確認用: session を安全に進められる範囲まで連続実行する。

        SpinRoulette 成功時は待機状態に入り、spin 完了後に自動再開する。

        停止条件:
          1. session が空になった
          2. apply_action() が False を返した
          3. SpinRoulette を成功実行した直後 → 待機状態に入って return
          4. いずれかの roulette が spinning 中

        Returns:
            (成功フラグ, エラー詳細)。成功時は (True, "")。
        """
        if not self._macro_session.has_next():
            print("[dev] run: no actions in session")
            self._stop_auto_advance()
            return (True, "")
        if self._is_any_spinning():
            print("[dev] run: blocked — spinning in progress")
            return (True, "")

        # auto advance 開始
        self._macro_auto_advancing = True

        from roulette_action_codec import action_to_dict, action_summary as _summary
        executed = 0
        error_detail = ""

        while self._macro_session.has_next():
            # auto advance が外部から停止された場合
            if not self._macro_auto_advancing:
                print(f"[dev] run: stopped by external ({executed} executed)")
                break

            action = self._macro_session.pop_next()

            # BranchOnWinner: apply_action に渡さず、ここで直接処理
            if isinstance(action, BranchOnWinner):
                branch_ok = self._handle_branch_on_winner(action)
                if not branch_ok:
                    self._stop_auto_advance()
                    error_detail = f"branch 評価失敗: {_summary(action)}"
                    break
                executed += 1
                print(f"[dev] run: [{self._macro_session.current_index}/{self._macro_session.total_count}] "
                      f"branch_on_winner('{action.winner_text}')")
                continue

            ok = self.apply_action(action, origin=ActionOrigin.MACRO)

            if not ok:
                self._macro_session.rewind_one()
                print(f"[dev] run: FAILED at [{self._macro_session.current_index}/{self._macro_session.total_count}] "
                      f"{action_to_dict(action)} — stopped")
                self._stop_auto_advance()
                error_detail = f"実行失敗: {_summary(action)}"
                break

            executed += 1
            print(f"[dev] run: [{self._macro_session.current_index}/{self._macro_session.total_count}] "
                  f"{action_to_dict(action)}")

            # SpinRoulette 成功後は待機状態に入る
            if isinstance(action, SpinRoulette):
                rid = action.roulette_id or self._manager.active_id
                # auto advance 中は overlay を macro_hold_sec 後に自動クローズさせる
                ctx = self._manager.get(rid)
                if ctx:
                    ctx.panel.result_overlay.set_force_auto_close(
                        True, self._settings.macro_hold_sec
                    )
                self._macro_waiting_spin = True
                self._macro_waiting_roulette_id = rid
                print(f"[dev] run: waiting for spin completion on '{rid}' ({executed} executed)")
                self._update_title_active_id()
                self._notify_macro_viewer()
                return (True, "")  # ResultOverlay.closed で _try_resume_macro_after_overlay が呼ばれる

            # spinning が始まっていたら安全側で停止
            if self._is_any_spinning():
                print(f"[dev] run: paused — spinning detected ({executed} executed)")
                self._stop_auto_advance()
                break
        else:
            print(f"[dev] run: completed all ({executed} executed)")
            self._stop_auto_advance()

        self._update_title_active_id()
        return (not bool(error_detail), error_detail)

    def _stop_auto_advance(self):
        """auto advance 状態を全てクリアする。"""
        self._macro_auto_advancing = False
        self._macro_waiting_spin = False
        self._macro_waiting_roulette_id = None
        self._notify_macro_viewer()

    # ================================================================
    #  分岐評価
    # ================================================================

    def _handle_branch_on_winner(self, branch: BranchOnWinner) -> bool:
        """BranchOnWinner を評価し、適切な action 列を session に挿入する。

        安全側停止条件:
          - _last_spin_result が None
          - source_roulette_id が未設定（空文字）
          - _last_spin_result.roulette_id が source_roulette_id と不一致

        Returns:
            処理成功なら True。安全側停止すべき場合は False。
        """
        result = self._last_spin_result
        if result is None:
            print("[dev] branch: STOPPED — no last spin result")
            return False

        if not branch.source_roulette_id:
            print("[dev] branch: STOPPED — source_roulette_id is empty")
            return False

        if result.roulette_id != branch.source_roulette_id:
            print(f"[dev] branch: STOPPED — roulette mismatch: "
                  f"result='{result.roulette_id}' vs source='{branch.source_roulette_id}'")
            return False

        # 第1条件を評価
        cond1 = self._eval_single_condition(
            result.winner_text, branch.match_mode, branch.winner_text,
            branch.regex_ignore_case, branch.numeric_operator, branch.numeric_value)
        if cond1 is None:
            return False  # 安全側停止（invalid regex 等）

        # compound_logic に応じて第2条件を評価
        logic = branch.compound_logic
        if logic in ("and", "or"):
            cond2 = self._eval_single_condition(
                result.winner_text, branch.cond2_match_mode, branch.cond2_winner_text,
                branch.cond2_regex_ignore_case, branch.cond2_numeric_operator,
                branch.cond2_numeric_value)
            if cond2 is None:
                return False
            if logic == "and":
                matched = cond1 and cond2
            else:
                matched = cond1 or cond2
        else:
            matched = cond1

        if matched:
            chosen = branch.then_actions
            label = "then"
        else:
            chosen = branch.else_actions
            label = "else"

        print(f"[dev] branch: source='{branch.source_roulette_id}' "
              f"winner='{result.winner_text}' vs condition='{branch.winner_text}' "
              f"mode={mode} → {label} ({len(chosen)} actions)")

        if chosen:
            self._macro_session.insert_actions(chosen)
        return True

    @staticmethod
    def _eval_single_condition(winner_text: str, mode: str, cond_text: str,
                               regex_ic: bool, num_op: str, num_val: str) -> bool | None:
        """単一条件を評価する。True/False または None（安全側停止）を返す。"""
        mode = mode or "exact"
        if mode == "numeric":
            try:
                wn = float(winner_text)
                cn = float(num_val)
            except (ValueError, TypeError):
                return False
            ops = {"==": wn == cn, "!=": wn != cn, ">": wn > cn,
                   ">=": wn >= cn, "<": wn < cn, "<=": wn <= cn}
            return ops.get(num_op, False)
        elif mode == "regex":
            try:
                flags = re.IGNORECASE if regex_ic else 0
                return bool(re.search(cond_text, winner_text, flags))
            except re.error:
                return None
        elif mode == "contains":
            return cond_text in winner_text
        else:
            return winner_text == cond_text

    # ================================================================
    #  viewer / overlay 連携
    # ================================================================

    def _notify_macro_viewer(self):
        """macro viewer が表示中であれば実行状態表示を更新する。"""
        if self._macro_viewer is not None:
            self._macro_viewer._update_execution_status()

    def _on_result_overlay_closed(self, roulette_id: str):
        """ResultOverlay が閉じられた時のハンドラ。

        auto advance 待機中であれば再開を試みる。
        """
        self._try_resume_macro_after_overlay(roulette_id)

    def _try_resume_macro_after_overlay(self, closed_roulette_id: str):
        """ResultOverlay 閉じ通知を受けて、安全条件を満たせば auto advance を再開する。

        再開条件（全て満たす場合のみ再開）:
          1. auto advance 実行中であること
          2. spin 完了待ち中であること
          3. 閉じた roulette が待機対象と一致すること
          4. 他の roulette が spinning 中でないこと
        """
        if not self._macro_auto_advancing:
            return
        if not self._macro_waiting_spin:
            return
        if closed_roulette_id != self._macro_waiting_roulette_id:
            print(f"[dev] resume: ignored — overlay closed '{closed_roulette_id}' "
                  f"!= waiting '{self._macro_waiting_roulette_id}'")
            return
        if self._is_any_spinning():
            print("[dev] resume: blocked — roulette still spinning")
            return

        # 待機状態を解除して再開
        self._macro_waiting_spin = False
        self._macro_waiting_roulette_id = None
        print(f"[dev] resume: overlay closed on '{closed_roulette_id}', resuming macro")
        self._dev_run_until_pause()
