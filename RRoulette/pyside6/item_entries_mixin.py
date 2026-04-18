"""
item_entries_mixin.py — 項目データ変更 Mixin

i440: main_window.py から分離。
責務:
  - 項目データ変更シグナル受信 (_on_item_entries_changed)
  - アクション経由の項目データ全件置換 (_update_items_by_action)
  - 項目データ保存 (_save_item_entries)
  - 勝利数集計・UI反映 (_update_win_counts)

使用側:
  class MainWindow(ItemEntriesMixin, SettingsDispatchMixin, SpinFlowMixin,
                   RouletteLifecycleMixin, PanelGeometryMixin, QMainWindow)
"""

from bridge import build_segments_from_entries, save_item_entries
from roulette_actions import UpdateItemEntries


class ItemEntriesMixin:
    """項目データ更新・勝利数表示反映の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ------------------------------------------------------------------
    #  項目データ変更シグナル受信
    # ------------------------------------------------------------------

    def _on_item_entries_changed(self, entries: list):
        self.apply_action(UpdateItemEntries(entries=tuple(entries)))

    # ------------------------------------------------------------------
    #  アクション経由の項目データ全件置換
    # ------------------------------------------------------------------

    def _update_items_by_action(self, roulette_id: str,
                                entries: list) -> bool:
        """アクション経由の項目データ全件置換。

        Args:
            roulette_id: 対象 ID。空文字なら active を対象にする。
            entries: 置換後の項目データ（list）。

        Returns:
            置換できたら True。
        """
        if roulette_id:
            ctx = self._manager.get(roulette_id)
        else:
            ctx = self._manager.active
        if ctx is None:
            return False
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(
            entries, self._config
        )
        ctx.panel.set_segments(ctx.segments)
        self._save_item_entries()
        # i289 t07: _refresh_panel_tracking はここでは呼ばない。
        # 新規行ウィジェットを追加する set_active_entries 呼び出し元で行う。
        return True

    # ------------------------------------------------------------------
    #  項目データ保存
    # ------------------------------------------------------------------

    def _save_item_entries(self):
        """項目データを config に書き戻して保存する。

        i338: default ルーレットはグローバル config に保存。
        それ以外は RouletteContext.item_patterns に在メモリ保存
        （_save_window_state で一括ディスク書き込み）。
        """
        ctx = self._active_context
        if ctx.item_patterns is not None:
            # non-default ルーレット: per-roulette パターンにフラッシュ
            pat = ctx.current_pattern or "デフォルト"
            ctx.item_patterns[pat] = [e.to_dict() for e in ctx.item_entries]
        else:
            # default ルーレット: グローバル config に書き込み
            save_item_entries(self._config, ctx.item_entries)

    # ------------------------------------------------------------------
    #  勝利数集計・UI 反映
    # ------------------------------------------------------------------

    def _update_win_counts(self):
        """勝利数集計を SettingsPanel / ItemPanel とグラフに反映する。"""
        ctx = self._active_context
        pattern_id = self._get_current_pattern_id(ctx)
        counts = self._win_history.count_by_item(pattern_id, roulette_id=ctx.roulette_id)
        self._settings_panel.update_win_counts(counts)
        self._item_panel.update_win_counts(counts)
        self._refresh_graph()
        self._refresh_in_panel_graphs()  # i389: 全 in-panel グラフを更新
