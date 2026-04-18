"""
design_graph_mixin.py — グラフ / デザインエディタ Mixin

i443: main_window.py から分離。
責務:
  - テーマ適用 (_apply_app_theme, _check_os_theme_change)
  - デザインプリセット適用 (_apply_design_preset)
  - デザインエディタ (_open_design_editor, _on_design_editor_changed, _on_design_editor_closed)
  - グラフダイアログ (_open_graph, _on_graph_closed, _on_graph_orientation_changed)
  - パネルグラフ (_on_panel_graph_requested, _on_in_panel_graph_opened,
                  _refresh_in_panel_graphs, _refresh_in_panel_graph_for)
  - グラフ更新 (_refresh_graph)

使用側:
  class MainWindow(DesignGraphMixin, ReplayManagementMixin, ..., QMainWindow)
"""

from PySide6.QtWidgets import QApplication

from bridge import DESIGN_PRESETS, DesignSettings, get_current_pattern_name
from dark_theme import get_app_stylesheet, resolve_theme_mode
from roulette_actions import SetActiveRoulette


class DesignGraphMixin:
    """グラフダイアログ / デザインエディタ表示・更新の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ------------------------------------------------------------------
    #  テーマ適用
    # ------------------------------------------------------------------

    def _apply_app_theme(self, design: DesignSettings):
        """QApplication 全体にテーマを適用する。"""
        app = QApplication.instance()
        if app:
            app.setStyleSheet(
                get_app_stylesheet(self._settings.theme_mode, design)
            )

    def _check_os_theme_change(self):
        """OS テーマの変化を検知し、system モード時にテーマを再適用する。"""
        if self._settings.theme_mode not in ("system", "auto"):
            return
        current = resolve_theme_mode("system")
        if current != self._last_os_theme:
            self._last_os_theme = current
            self._apply_app_theme(self._design)
            self._settings_panel.set_panel_theme_mode(self._settings.theme_mode)

    # ------------------------------------------------------------------
    #  デザインプリセット適用
    # ------------------------------------------------------------------

    def _apply_design_preset(self, name: str):
        preset = DESIGN_PRESETS.get(name)
        if preset is None:
            return
        self._design = DesignSettings.from_dict(preset.to_dict())
        self._design.preset_name = name
        self._settings.design_preset_name = name

        self._apply_app_theme(self._design)
        self._active_panel.update_design(self._design)
        self._apply_central_background(self._settings.window_transparent)
        self._settings_panel.update_design(self._design)
        if hasattr(self, "_item_panel") and self._item_panel:
            self._item_panel.update_design(self._design)
        if hasattr(self, "_mw_drag_bar"):
            self._mw_drag_bar.update_design(self._design)
        self._save_config()

    # ------------------------------------------------------------------
    #  デザインエディタ
    # ------------------------------------------------------------------

    def _open_design_editor(self):
        """デザインエディタダイアログを開く（非モーダル）。"""
        from design_editor_dialog import DesignEditorDialog
        if self._design_editor is not None:
            self._design_editor.raise_()
            self._design_editor.activateWindow()
            return
        self._design_editor = DesignEditorDialog(
            self._design, self._preset_mgr, parent=self
        )
        self._design_editor.design_changed.connect(
            self._on_design_editor_changed
        )
        self._design_editor.finished.connect(self._on_design_editor_closed)
        self._design_editor.set_item_count(len(self._active_entries))
        self._design_editor.show()

    def _on_design_editor_changed(self, design: DesignSettings):
        """デザインエディタからの変更を即時反映する。"""
        self._design = DesignSettings.from_dict(design.to_dict())
        self._settings.design_preset_name = design.preset_name
        self._apply_app_theme(self._design)
        self._active_panel.update_design(self._design)
        self._apply_central_background(self._settings.window_transparent)
        self._settings_panel.update_design(self._design)
        if hasattr(self, "_item_panel") and self._item_panel:
            self._item_panel.update_design(self._design)
        if hasattr(self, "_mw_drag_bar"):
            self._mw_drag_bar.update_design(self._design)
        self._save_config()

    def _on_design_editor_closed(self):
        """デザインエディタが閉じられた。"""
        self._design_editor = None

    # ------------------------------------------------------------------
    #  グラフダイアログ
    # ------------------------------------------------------------------

    def _open_graph(self):
        """勝利履歴グラフダイアログを開く（非モーダル）。"""
        from graph_dialog import GraphDialog
        if self._graph_dialog is not None:
            self._graph_dialog.raise_()
            self._graph_dialog.activateWindow()
            self._refresh_graph()
            return
        self._graph_dialog = GraphDialog(
            self._design, parent=self,
            initial_orientation=self._settings.graph_orientation,  # i386
        )
        self._graph_dialog.finished.connect(self._on_graph_closed)
        self._graph_dialog.orientation_changed.connect(  # i386
            self._on_graph_orientation_changed
        )
        self._refresh_graph()
        self._graph_dialog.show()

    def _on_graph_closed(self):
        """グラフダイアログが閉じられた。"""
        self._graph_dialog = None

    def _on_graph_orientation_changed(self, orientation: str):
        """グラフ向き変更時に設定へ保存する（i386）。"""
        self._settings.graph_orientation = orientation
        self._save_config()

    def _on_panel_graph_requested(self, roulette_id: str):
        """ルーレットパネル上のグラフボタンからグラフを開く（後方互換）。

        i389: パネルのグラフボタンは _toggle_graph_panel() 経由になったため、
        このハンドラは設定パネルのグラフボタンや外部からの呼び出し用として残す。
        """
        if self._manager.active_id != roulette_id:
            self.apply_action(SetActiveRoulette(roulette_id))
        self._open_graph()

    # ------------------------------------------------------------------
    #  パネル内グラフ
    # ------------------------------------------------------------------

    def _on_in_panel_graph_opened(self, roulette_id: str):
        """i389: ルーレットパネルの in-panel グラフが表示された。

        向き設定を反映し、グラフデータを初期ロードする。
        """
        ctx = self._manager.get(roulette_id)
        if ctx is None:
            return
        gw = ctx.panel.in_panel_graph_widget
        if gw is None:
            return
        # 向き設定を反映（シグナルを emit しない set_orientation を使用）
        gw.set_orientation(self._settings.graph_orientation)
        # orientation_changed を保存ハンドラへ接続（重複接続を避ける）
        try:
            gw.orientation_changed.disconnect(self._on_graph_orientation_changed)
        except RuntimeError:
            pass
        gw.orientation_changed.connect(self._on_graph_orientation_changed)
        # グラフデータ初期ロード
        self._refresh_in_panel_graph_for(ctx)

    def _refresh_in_panel_graphs(self):
        """i389: 全ルーレットパネルの in-panel グラフを更新する。"""
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx is None:
                continue
            self._refresh_in_panel_graph_for(ctx)

    def _refresh_in_panel_graph_for(self, ctx):
        """i389: 指定コンテキストのパネルの in-panel グラフを更新する。

        グラフウィジェットが存在し、かつ表示中の場合のみ更新する。
        各パネルは自身の roulette_id に対応するデータを表示する。

        i392: in-panel グラフは現在有効な item_entries のみを表示対象とする。
        「有効項目に含まれない過去の結果も追加」はしない。
        これにより、現在の項目パターン外の履歴が混入しない。
        """
        panel = ctx.panel
        gw = panel.in_panel_graph_widget
        if gw is None or not gw.isVisible():
            return
        _igp_pid = self._get_current_pattern_id(ctx)
        _igp_name = ctx.current_pattern or get_current_pattern_name(self._config)
        roulette_id = ctx.roulette_id
        counts = self._win_history.count_by_item(_igp_pid, roulette_id=roulette_id)
        total = self._win_history.total_count(_igp_pid, roulette_id=roulette_id)
        # i392: 現在有効な項目のみ。パターン外の過去履歴は混ぜない。
        items = []
        for entry in ctx.item_entries:
            if entry.enabled:
                name = entry.text
                items.append((name, len(items), counts.get(name, 0)))
        panel.update_in_panel_graph(items, total, _igp_name)

    # ------------------------------------------------------------------
    #  グラフ更新
    # ------------------------------------------------------------------

    def _refresh_graph(self):
        """グラフダイアログが開いていればデータを更新する。"""
        if self._graph_dialog is None:
            return
        ctx = self._active_context
        pattern = ctx.current_pattern or get_current_pattern_name(self._config)
        _rg_pid = self._get_current_pattern_id(ctx)
        roulette_id = ctx.roulette_id
        counts = self._win_history.count_by_item(_rg_pid, roulette_id=roulette_id)
        total = self._win_history.total_count(_rg_pid, roulette_id=roulette_id)
        # 現在の有効項目リスト順で項目データを構成
        items = []
        for entry in ctx.item_entries:
            if entry.enabled:
                name = entry.text
                items.append((name, len(items), counts.get(name, 0)))
        # カウントが0より大きい項目のみ（有効項目に含まれない過去の結果も追加）
        shown_names = {name for name, _, _ in items}
        for name, count in counts.items():
            if name not in shown_names:
                items.append((name, len(items), count))
        self._graph_dialog.update_graph(items, total, pattern)
        # i381: ウィンドウタイトルに現在のルーレット / パターンを表示する
        ids = self._manager.ids()
        if len(ids) > 1:
            idx = ids.index(roulette_id) if roulette_id in ids else 0
            title = f"勝利履歴グラフ — #{idx + 1} / {pattern}"
        else:
            title = f"勝利履歴グラフ — {pattern}"
        self._graph_dialog.setWindowTitle(title)
