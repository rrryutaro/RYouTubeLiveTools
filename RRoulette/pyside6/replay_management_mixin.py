"""
replay_management_mixin.py — リプレイ管理 Mixin

i442: main_window.py から分離。
責務:
  - replay 再生 (_start_replay, _start_constituent_replay)
  - replay 完了処理 (_on_replay_finished, _on_replay_panel_restored)
  - replay 強制中断 (_cancel_replay, _replay_restore_state)
  - replay 管理ダイアログ (_open_replay_manager, _on_replay_dialog_*)
  - replay dialog 更新 (_refresh_replay_dialog)

使用側:
  class MainWindow(ReplayManagementMixin, PatternManagementMixin, ..., QMainWindow)
"""

import os

from PySide6.QtWidgets import QMessageBox


class ReplayManagementMixin:
    """リプレイ再生・管理ダイアログ操作の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  Replay 再生
    # ================================================================

    def _start_replay(self, idx: int = 0):
        """指定インデックスの replay を再生する。

        i352: group_id を持つレコードは全ルーレット同時再生（同時実行再現）。
        group_id がない場合は active ルーレット単独再生。

        Args:
            idx: 基点となる replay records のインデックス（active mgr 基準）
        """
        replay_mgr = self._active_replay_mgr
        if replay_mgr is None:
            return
        if replay_mgr.count() == 0:
            return

        rec = replay_mgr.get(idx)
        if rec is None:
            return

        group_id = rec.get("group_id", "")

        # 再生対象を構築: (roulette_id, mgr, rec_idx, panel)
        # i353: 非表示パネルは対象に含めない（結果表示が残って再生が詰まる問題の防止）
        targets: list[tuple] = []
        if group_id:
            # グループ再生: 全ルーレットから同じ group_id を持つ「表示中」レコードを探す
            for rid, mgr in self._replay_mgrs.items():
                grp_idxs = mgr.find_by_group_id(group_id)
                if grp_idxs:
                    ctx = self._manager.get(rid)
                    if ctx and ctx.panel.isVisible():
                        targets.append((rid, mgr, grp_idxs[0], ctx.panel))
            # 表示中のグループメンバーが1件もなければ単独再生にフォールバック
            if not targets:
                ctx = self._manager.active
                if ctx and ctx.panel.isVisible():
                    targets.append((self._manager.active_id, replay_mgr, idx, ctx.panel))
        else:
            # 単独再生: active ルーレットのみ（表示中かどうかに関係なく active を優先）
            ctx = self._manager.active
            if ctx:
                targets.append((self._manager.active_id, replay_mgr, idx, ctx.panel))

        if not targets:
            return

        # 再生中・記録中・スピン中のものがあれば中断
        for rid, mgr, rec_idx, panel in targets:
            if mgr.is_playing or mgr.is_recording or panel.spin_ctrl.is_spinning:
                return

        # セッション情報を保存
        self._replay_sessions = [
            {
                "roulette_id": rid,
                "panel": panel,
                "saved_segments": list(panel.wheel._segments),
                "saved_angle": panel.wheel._angle,
                "saved_pointer": panel.wheel._pointer_angle,
                "saved_direction": panel.wheel._spin_direction,
            }
            for rid, mgr, rec_idx, panel in targets
        ]
        self._replay_group_remaining = len(targets)

        # UI ロック
        self._settings_panel.set_spinning(True)
        self._settings_panel.set_replay_playing(True)

        # 各パネルで再生開始
        failed = False
        started_panels = []
        for rid, mgr, rec_idx, panel in targets:
            if self._settings.replay_show_indicator:
                panel.wheel.set_replay_indicator(True)
            ok = mgr.start_playback(rec_idx, panel.wheel, self._sound)
            if ok:
                started_panels.append(panel)
            else:
                failed = True

        if failed:
            # いずれかが失敗した場合は全停止してロール解除
            for rid, mgr, rec_idx, panel in targets:
                if mgr.is_playing:
                    mgr.stop_playback()
                panel.wheel.set_replay_indicator(False)
            self._replay_sessions = []
            self._replay_group_remaining = 0
            self._settings_panel.set_spinning(False)
            self._settings_panel.set_replay_playing(False)

    def _on_replay_finished(self, winner: str, winner_idx: int, roulette_id: str = ""):
        """replay 再生完了時の処理。

        i352: roulette_id でセッションを特定し、そのパネルで結果表示・復元を行う。
        全パネルが完了したときのみ UI ロックを解除する。
        i353: セッション未発見時はカウンタを操作しない（不整合な decrement を防止）。
        """
        session = next(
            (s for s in self._replay_sessions if s["roulette_id"] == roulette_id),
            None,
        )
        if session is None:
            # i353: セッション対象外（非表示フィルタ等で targets に入らなかった mgr の
            # playback_finished が稀に発火する場合）。カウンタに触れず無視する。
            return

        panel = session["panel"]

        # 結果表示（win_history / log には記録しない）
        if winner and panel.isVisible():
            # i353: 表示中パネルのみ結果オーバーレイを表示し、クローズ後に復元する
            panel.result_overlay.show_result(winner)

            def _on_overlay_closed(rid=roulette_id):
                try:
                    panel.result_overlay.closed.disconnect(_on_overlay_closed)
                except RuntimeError:
                    pass
                self._on_replay_panel_restored(rid)

            panel.result_overlay.closed.connect(_on_overlay_closed)
        else:
            # 非表示パネル or winner なし: オーバーレイを介さず即時復元
            self._on_replay_panel_restored(roulette_id)

    def _on_replay_panel_restored(self, roulette_id: str):
        """1パネルのリプレイ後処理（オーバーレイ消去・状態復元）。

        i352: グループの全パネルが完了したときのみ UI ロックを解除する。
        """
        # 対象セッションを復元
        session = next(
            (s for s in self._replay_sessions if s["roulette_id"] == roulette_id),
            None,
        )
        if session:
            panel = session["panel"]
            panel.wheel.set_replay_indicator(False)
            panel.wheel.set_segments(session["saved_segments"])
            panel.wheel.set_angle(session["saved_angle"])
            panel.wheel.set_pointer_angle(session["saved_pointer"])
            panel.wheel._spin_direction = session["saved_direction"]
        else:
            # i353: セッション不明でもカウンタだけデクリメントして詰まらせない
            self._replay_group_remaining = max(0, self._replay_group_remaining - 1)
            if self._replay_group_remaining <= 0:
                self._replay_sessions = []
                self._replay_group_remaining = 0
                self._settings_panel.set_spinning(False)
                self._settings_panel.set_replay_playing(False)
                if self._replay_dialog is not None:
                    self._replay_dialog.set_playing(False)
            return

        self._replay_group_remaining = max(0, self._replay_group_remaining - 1)
        if self._replay_group_remaining <= 0:
            self._replay_sessions = []
            self._replay_group_remaining = 0
            self._settings_panel.set_spinning(False)
            self._settings_panel.set_replay_playing(False)
            if self._replay_dialog is not None:
                self._replay_dialog.set_playing(False)
            self._refresh_replay_dialog()

    def _replay_restore_state(self):
        """replay 強制中断時に全セッションをまとめて復元する。"""
        for session in self._replay_sessions:
            panel = session["panel"]
            panel.wheel.set_replay_indicator(False)
            panel.wheel.set_segments(session["saved_segments"])
            panel.wheel.set_angle(session["saved_angle"])
            panel.wheel.set_pointer_angle(session["saved_pointer"])
            panel.wheel._spin_direction = session["saved_direction"]
        self._replay_sessions = []
        self._replay_group_remaining = 0
        self._settings_panel.set_spinning(False)
        self._settings_panel.set_replay_playing(False)
        if self._replay_dialog is not None:
            self._replay_dialog.set_playing(False)
        self._refresh_replay_dialog()

    def _cancel_replay(self):
        """進行中の replay を中断する。"""
        stopped = False
        for _rp_mgr_c in self._replay_mgrs.values():
            if _rp_mgr_c.is_playing:
                _rp_mgr_c.stop_playback()
                stopped = True
        if stopped:
            self._replay_restore_state()

    # ================================================================
    #  Replay 管理ダイアログ
    # ================================================================

    def _open_replay_manager(self):
        """リプレイ管理ダイアログを開く（非モーダル）。

        i352: ダイアログは active roulette に即時追従する。
        """
        from replay_dialog import ReplayDialog
        if self._replay_dialog is not None:
            self._replay_dialog.raise_()
            self._replay_dialog.activateWindow()
            self._refresh_replay_dialog()
            return
        mgr = self._active_replay_mgr
        self._replay_dialog = ReplayDialog(self._design, parent=self)
        self._replay_dialog.play_requested.connect(self._on_replay_dialog_play)
        self._replay_dialog.delete_requested.connect(
            self._on_replay_dialog_delete
        )
        self._replay_dialog.rename_requested.connect(
            self._on_replay_dialog_rename
        )
        self._replay_dialog.keep_requested.connect(
            self._on_replay_dialog_keep
        )
        self._replay_dialog.export_requested.connect(
            self._on_replay_dialog_export
        )
        self._replay_dialog.export_multi_requested.connect(
            self._on_replay_dialog_export_multi
        )
        self._replay_dialog.import_requested.connect(
            self._on_replay_dialog_import
        )
        self._replay_dialog.constituent_play_requested.connect(
            self._on_replay_dialog_constituent_play
        )
        self._replay_dialog.finished.connect(self._on_replay_dialog_closed)
        self._replay_dialog.refresh_list(mgr.records if mgr else [])
        self._replay_dialog.show()

    def _on_replay_dialog_play(self, idx: int):
        """管理ダイアログからの再生リクエスト。"""
        self._start_replay(idx)
        if self._replay_dialog is not None:
            mgr = self._active_replay_mgr
            self._replay_dialog.set_playing(bool(mgr and mgr.is_playing))

    def _on_replay_dialog_constituent_play(self, idx: int):
        """管理ダイアログからの個別再生リクエスト（multi記録をactive単独で再生）。i354"""
        self._start_constituent_replay(idx)
        if self._replay_dialog is not None:
            mgr = self._active_replay_mgr
            self._replay_dialog.set_playing(bool(mgr and mgr.is_playing))

    def _start_constituent_replay(self, idx: int):
        """multi記録をgroup_idを無視してactive roulette 1台だけで再生する。i354"""
        replay_mgr = self._active_replay_mgr
        if replay_mgr is None or replay_mgr.count() == 0:
            return
        rec = replay_mgr.get(idx)
        if rec is None:
            return
        ctx = self._manager.active
        if ctx is None:
            return
        # 既に再生中・記録中・スピン中なら何もしない
        if replay_mgr.is_playing or replay_mgr.is_recording or ctx.panel.spin_ctrl.is_spinning:
            return
        # group_id を無視して active 単独を targets にする
        self._replay_sessions = [{
            "roulette_id": self._manager.active_id,
            "panel": ctx.panel,
            "saved_segments": list(ctx.panel.wheel._segments),
            "saved_angle": ctx.panel.wheel._angle,
            "saved_pointer": ctx.panel.wheel._pointer_angle,
            "saved_direction": ctx.panel.wheel._spin_direction,
        }]
        self._replay_group_remaining = 1
        self._settings_panel.set_spinning(True)
        self._settings_panel.set_replay_playing(True)
        if self._settings.replay_show_indicator:
            ctx.panel.wheel.set_replay_indicator(True)
        ok = replay_mgr.start_playback(idx, ctx.panel.wheel, self._sound)
        if not ok:
            self._replay_sessions = []
            self._replay_group_remaining = 0
            self._settings_panel.set_spinning(False)
            self._settings_panel.set_replay_playing(False)
            ctx.panel.wheel.set_replay_indicator(False)

    def _on_replay_dialog_delete(self, idx: int):
        """管理ダイアログからの削除リクエスト。"""
        mgr = self._active_replay_mgr
        if mgr is None:
            return
        mgr.delete(idx)
        self._settings_panel.set_replay_count(mgr.count())
        if self._replay_dialog is not None:
            self._replay_dialog.refresh_list(mgr.records)

    def _on_replay_dialog_rename(self, idx: int, new_name: str):
        """管理ダイアログからの名称変更リクエスト。"""
        mgr = self._active_replay_mgr
        if mgr is None:
            return
        mgr.rename(idx, new_name)
        if self._replay_dialog is not None:
            self._replay_dialog.refresh_list(mgr.records)

    def _on_replay_dialog_keep(self, idx: int, keep: bool):
        """管理ダイアログからの保持フラグ変更リクエスト。"""
        mgr = self._active_replay_mgr
        if mgr is None:
            return
        mgr.set_keep(idx, keep)
        if self._replay_dialog is not None:
            self._replay_dialog.refresh_list(mgr.records)

    def _on_replay_dialog_export(self, idx: int, path: str):
        """管理ダイアログからの書き出しリクエスト。"""
        from PySide6.QtWidgets import QMessageBox
        mgr = self._active_replay_mgr
        if mgr is None:
            return
        ok = mgr.export_record(idx, path)
        if self._replay_dialog is not None:
            if ok:
                QMessageBox.information(
                    self._replay_dialog, "書き出し完了",
                    "リプレイを書き出しました。",
                )
            else:
                QMessageBox.warning(
                    self._replay_dialog, "書き出し失敗",
                    "リプレイの書き出しに失敗しました。",
                )

    def _on_replay_dialog_export_multi(self, indices: list, path: str):
        """管理ダイアログからの複数書き出しリクエスト。"""
        from PySide6.QtWidgets import QMessageBox
        mgr = self._active_replay_mgr
        if mgr is None:
            return
        ok = mgr.export_records(indices, path)
        if self._replay_dialog is not None:
            if ok:
                QMessageBox.information(
                    self._replay_dialog, "書き出し完了",
                    f"{len(indices)}件のリプレイを書き出しました。",
                )
            else:
                QMessageBox.warning(
                    self._replay_dialog, "書き出し失敗",
                    "リプレイの書き出しに失敗しました。",
                )

    def _on_replay_dialog_import(self, paths: list):
        """管理ダイアログからの読み込みリクエスト（複数ファイル対応）。"""
        from PySide6.QtWidgets import QMessageBox
        mgr = self._active_replay_mgr
        if mgr is None:
            return
        total_imported = 0
        failed_files = []
        for path in paths:
            count = mgr.import_record(path)
            if count > 0:
                total_imported += count
            else:
                import os
                failed_files.append(os.path.basename(path))

        if self._replay_dialog is not None:
            if total_imported > 0:
                self._settings_panel.set_replay_count(mgr.count())
                self._replay_dialog.refresh_list(mgr.records)
            if total_imported > 0 and not failed_files:
                if total_imported > 1 or len(paths) > 1:
                    QMessageBox.information(
                        self._replay_dialog, "読み込み完了",
                        f"{total_imported}件のリプレイを読み込みました。",
                    )
            elif total_imported > 0 and failed_files:
                QMessageBox.information(
                    self._replay_dialog, "読み込み完了",
                    f"{total_imported}件を読み込みました。\n"
                    f"失敗: {', '.join(failed_files)}",
                )
            else:
                QMessageBox.warning(
                    self._replay_dialog, "読み込み失敗",
                    "リプレイの読み込みに失敗しました。\n"
                    "ファイル形式を確認してください。",
                )

    def _on_replay_dialog_closed(self):
        """リプレイ管理ダイアログが閉じられた。"""
        self._replay_dialog = None

    def _refresh_replay_dialog(self):
        """リプレイ管理ダイアログが開いていれば、active roulette の一覧を更新する。

        i352: 常に active mgr のレコードを表示する（active 切替に即時追従）。
        """
        if self._replay_dialog is None:
            return
        mgr = self._active_replay_mgr
        self._replay_dialog.refresh_list(mgr.records if mgr else [])

