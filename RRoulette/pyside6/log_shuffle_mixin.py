"""
log_shuffle_mixin.py — ログ操作・シャッフル/リセット Mixin

i445: main_window.py から分離。
責務:
  - シャッフル (_on_shuffle_once)
  - 並び順リセット (_on_arrangement_reset)
  - 項目一括リセット (_on_items_reset)
  - ログクリア (_on_log_clear)
  - ログエクスポート (_on_log_export)

使用側:
  class MainWindow(LogShuffleMixin, MacroFlowMixin, DesignGraphMixin, ..., QMainWindow)
"""

import os

from bridge import build_segments_from_entries
from config_utils import EXPORT_DIR


class LogShuffleMixin:
    """ログ操作・シャッフル/リセット操作の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  シャッフル / リセット
    # ================================================================

    def _on_shuffle_once(self):
        """単発ランダム再配置。item_entries をシャッフルしてセグメント再構築。

        i284: シャッフル直前のエントリ並びをスナップショットとして
        ctx に保持し、`_on_arrangement_reset` から復元できるようにする。
        既にスナップショットがある場合は上書きしない（複数回シャッフルしても
        最初の標準並びを記憶しておくため）。
        """
        import random
        ctx = self._active_context
        # i284: 並びリセット用スナップショット
        if getattr(ctx, "_pre_shuffle_entries", None) is None:
            ctx._pre_shuffle_entries = list(ctx.item_entries)
        entries = list(ctx.item_entries)
        random.shuffle(entries)
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._save_item_entries()

    def _on_arrangement_reset(self):
        """i284: 並びリセット。

        v0.4.4 の「標準配置に戻す」相当。直前のシャッフル前 snapshot へ
        並び順を戻す。snapshot が無い（一度もシャッフルしていない）場合は何もしない。
        """
        ctx = self._active_context
        snap = getattr(ctx, "_pre_shuffle_entries", None)
        if snap is None:
            return
        ctx.item_entries = list(snap)
        ctx._pre_shuffle_entries = None
        ctx.segments, _ = build_segments_from_entries(
            ctx.item_entries, self._config
        )
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(ctx.item_entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._save_item_entries()

    def _on_items_reset(self):
        """i284: 項目一括リセット（v0.4.4 「一括リセット」相当）。

        全項目の prob_mode / prob_value / split_count をデフォルトに戻す。
        項目名・enabled は維持する。`confirm_reset` ON 時は確認ダイアログ。
        """
        if self._settings.confirm_reset:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "項目一括リセット",
                "全項目の確率・分割設定をデフォルトに戻します。\n"
                "（項目名・有効/無効はそのまま）\nよろしいですか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        ctx = self._active_context
        from item_entry import ItemEntry as _IE
        new_entries = [
            _IE(text=e.text, enabled=e.enabled,
                prob_mode=None, prob_value=None, split_count=1)
            for e in ctx.item_entries
        ]
        ctx.item_entries = new_entries
        ctx.segments, _ = build_segments_from_entries(
            new_entries, self._config
        )
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(new_entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._save_item_entries()

    # ================================================================
    #  ログ操作
    # ================================================================

    def _on_log_clear(self):
        """ログ履歴クリア。confirm_reset=ON なら確認ダイアログを表示。"""
        if self._settings.confirm_reset:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "確認", "ログ履歴をクリアしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._active_panel.wheel.clear_log()
        # i345: active roulette のログファイルをクリア
        self._active_panel.wheel.save_log(
            self._roulette_log_path(self._manager.active_id)
        )
        # i380: active ルーレットの履歴のみクリア（他ルーレットの履歴は保持）
        self._win_history.clear(roulette_id=self._manager.active_id)
        self._win_history.save()
        self._update_win_counts()
        _log_clr_mgr = self._active_replay_mgr
        self._settings_panel.set_replay_count(_log_clr_mgr.count() if _log_clr_mgr else 0)

    def _on_log_export(self):
        """ログ履歴を JSON ファイルにエクスポートする（import との対）。

        i393: WinHistory の全件履歴から書き出す。
        - 既定は選択中パターン + active ルーレット限定
        - log_history_all_patterns=True の場合は全パターン・全ルーレットを書き出す
        - 保存先初期ディレクトリは EXPORT_DIR（固定ルール準拠）
        """
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime
        ctx = self._active_context
        roulette_id = ctx.roulette_id if ctx else None
        # i407: フィルタは pattern_id（UUID）基準
        export_pattern_id = self._get_current_pattern_id(ctx)

        # i404: グローバル設定ではなく active ルーレットの per-roulette 設定を基準にする。
        # multi 時に roulette ごとに log_all_patterns が異なる場合でも、
        # その時点の active roulette の設定どおりに export 対象が決まる。
        # ctx は _active_context で常に存在するが、万一 None のときはグローバルにフォールバック。
        all_patterns = (
            ctx.settings.log_all_patterns if ctx
            else self._settings.log_history_all_patterns
        )
        # i408: roulette_id は常に active roulette に限定する（全パターンモードでも他 roulette を混ぜない）
        # pattern_id は全パターンモードなら絞り込みなし
        _export_pid = None if all_patterns else export_pattern_id
        export_rid = roulette_id

        # 対象レコード件数を確認
        records = self._win_history.records
        if _export_pid is not None:
            records = [r for r in records if r.get("pattern_id", "") == _export_pid]
        if export_rid is not None:
            records = [r for r in records
                       if r.get("roulette_id", "default") == export_rid]
        if not records:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "エクスポート", "エクスポートするログがありません。")
            return

        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"roulette_log_{dt}.json"
        default_path = os.path.join(EXPORT_DIR, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "ログをエクスポート", default_path,
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return
        self._win_history.export_to_json(path,
                                          pattern_id=_export_pid,
                                          roulette_id=export_rid)
