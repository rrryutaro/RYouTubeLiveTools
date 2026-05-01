"""
ui_toggle_mixin.py — ウィンドウ透過・ルーレットのみモード・UI トグル Mixin

i448: main_window.py から分離。
責務:
  - ウィンドウ/ルーレット透過適用 (_apply_window_transparent, _apply_roulette_transparent)
  - ルーレット以外非表示モード (_toggle_roulette_only_mode, _apply_roulette_only_mode,
      _sidebar_panel_entries)
  - 常に最前面 / グリップ / ドラッグバー / コントロールボックス / インスタンス表示 トグル
  - 設定パネルフローティング切替 (_toggle_settings_panel_float,
      _apply_settings_panel_float)
  - grip / ctrl_box 表示適用 (_apply_grip_visible, _apply_ctrl_box_visible)
  - 設定パネル表示トグル (_toggle_settings_panel)

使用側:
  class MainWindow(UIToggleMixin, PackageIOMixin, SettingsIOMixin, ..., QMainWindow)
"""

import ctypes

from PySide6.QtCore import Qt, QPoint, QVariantAnimation
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QApplication, QWidget


# ---------------------------------------------------------------------------
#  OBS 向けキャンバスフェードオーバーレイ (i066)
# ---------------------------------------------------------------------------

class _CanvasFadeOverlay(QWidget):
    """自動非表示フェードアウト用オーバーレイ（OBS 可視対応）。

    setWindowOpacity は OS レベルの透明度変化のため OBS に映らない。
    代わりに、親ウィンドウ内にキャンバス描画として背景色を塗り広げることで
    アプリ内の描画変化として OBS にも映るフェードを実現する。
    """

    def __init__(self, parent: QWidget, bg_color: str) -> None:
        super().__init__(parent)
        self._bg = QColor(bg_color)
        self._alpha = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()

    def set_alpha(self, a: int) -> None:
        self._alpha = max(0, min(255, int(a)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        c = QColor(self._bg)
        c.setAlpha(self._alpha)
        p.fillRect(self.rect(), c)


class UIToggleMixin:
    """ウィンドウ透過・ルーレットのみモード・UI トグル操作の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  ウィンドウ透過
    # ================================================================

    def _apply_window_transparent(self, enabled: bool):
        """メインウィンドウ自体の透過モードを適用する。

        QMainWindow / centralWidget は init 時から常に
        WA_TranslucentBackground 構成にしてあるので、実行時切替では
        centralWidget の背景塗り (transparent / design.bg) だけを
        差し替える。`hide → setWindowFlags → show` のような重い処理は
        不要で、即時反映される。
        """
        self._settings.window_transparent = enabled
        self._apply_central_background(enabled)
        # 念のため再描画
        if self.isVisible():
            self.update()
            central = self.centralWidget()
            if central:
                central.update()

    def _apply_roulette_transparent(self, enabled: bool):
        """ルーレットパネル側の透過モードを適用する。

        メインウィンドウ自体は触らない。各 RoulettePanel 自身の背景塗り
        (`set_transparent`) と内部 WheelWidget の塗りを切り替える。
        """
        self._settings.roulette_transparent = enabled
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx and ctx.panel:
                ctx.panel.set_transparent(enabled)

    def _apply_panels_transparent(self, enabled: bool):
        """ルーレット以外の全パネル背景の透過モードを切り替える（実験的）。

        検証B 用: UI 項目以外のパネル余白・背景領域を透過させる。
        window_transparent=True と組み合わせると、埋め込みパネルの背景が
        デスクトップまで透過する。フローティングパネルは WA_TranslucentBackground
        が未設定のため実質透過にならない点に注意。
        """
        for panel in (
            getattr(self, '_item_panel',     None),
            getattr(self, '_settings_panel', None),
            getattr(self, '_manage_panel',   None),
            getattr(self, '_ticket_panel',   None),
            getattr(self, '_link_panel',     None),
        ):
            if panel is not None and hasattr(panel, 'set_transparent'):
                panel.set_transparent(enabled)

    # ================================================================
    #  ルーレット以外非表示モード
    # ================================================================

    def _toggle_roulette_only_mode(self):
        """ルーレット以外非表示モードの ON/OFF を切り替える。"""
        self._settings.roulette_only_mode = not self._settings.roulette_only_mode
        self._apply_roulette_only_mode(self._settings.roulette_only_mode)
        self._save_config()

    def _sidebar_panel_entries(self) -> list:
        """roulette_only で表示/非表示を切り替えるサイドパネルの一覧。

        i038: 新しいパネルを追加する場合はここにエントリを追加するだけでよい。

        Returns:
            list of (key, panel, show_setting)
              key:          saved visibility dict のキー
              panel:        パネルウィジェット
              show_setting: roulette_only ON 時に表示を維持する場合 True の設定値
        """
        _s = self._settings
        entries = [
            ("item",     self._item_panel,     _s.roulette_only_show_items_panel),
            ("settings", self._settings_panel, _s.roulette_only_show_settings_panel),
            ("manage",   self._manage_panel,   _s.roulette_only_show_manage_panel),
        ]
        _seq = getattr(self, '_seq_dialog', None)
        if _seq is not None:
            entries.append(("seq", _seq, _s.roulette_only_show_execution_panel))
        _ticket = getattr(self, '_ticket_panel', None)
        if _ticket is not None:
            entries.append(("ticket", _ticket, _s.roulette_only_show_ticket_panel))
        _link = getattr(self, '_link_panel', None)
        if _link is not None:
            entries.append(("link", _link, _s.roulette_only_show_link_panel))
        return entries

    def _apply_roulette_only_mode(self, enabled: bool, *, _preset_snapshot: dict | None = None):
        """ルーレット以外非表示モードを適用する。

        i039: single/multi の分岐を廃止し、単一モードに統一。
          ON:  サイドパネルを設定に従い非表示。ルーレットパネル・ウィンドウは現在位置のまま保持。
               ウィンドウのリサイズ・ルーレットパネルの移動は行わない。
          OFF: ON 前の可視状態・ウィンドウサイズを復元。

        i058: _preset_snapshot を指定すると、現在の UI 状態からのスナップショット取得を
              スキップして指定値をそのまま使用する。起動時に使用し、パネルの一時表示を回避する。
        """
        if enabled:
            _s = self._settings
            # サイドパネル一覧をループで処理
            _entries = self._sidebar_panel_entries()

            if _preset_snapshot is not None:
                # i058: 起動時専用 — 呼び出し元が設定値から事前構築したスナップショットを使用。
                # パネルを通常状態で一時表示せずに roulette_only モードを適用できる。
                self._roulette_only_saved_visibility = _preset_snapshot
            else:
                _offsets = {key: (p.x(), p.y()) for key, p, _ in _entries}
                _vis_save = {key: p.isVisible() for key, p, _ in _entries}
                # 各ルーレットパネルの補助 UI 表示状態を保存
                _rp_ui_saved = {}
                for _rid in self._manager.ids():
                    _ctx = self._manager.get(_rid)
                    if _ctx and _ctx.panel:
                        _p = _ctx.panel
                        _rp_ui_saved[_rid] = {
                            "selection_handle": _p._selection_handle.isVisible(),
                            "title_plate": _p._title_plate.isVisible(),
                            "graph_btn": _p._graph_btn.isVisible(),
                            "grip": _p._grip.isVisible(),
                        }
                self._roulette_only_saved_visibility = {
                    **_vis_save,
                    "settings_panel_visible": self._settings_panel_visible,
                    "window_transparent": _s.window_transparent,
                    "roulette_transparent": _s.roulette_transparent,
                    "window_size": self.size(),
                    "panel_offsets": _offsets,
                    "rp_ui": _rp_ui_saved,
                }

            # サイドパネルを設定に従い条件付きで非表示（ループ処理）
            for key, p, show in _entries:
                if not show and p.isVisible():
                    p.hide()
                    if key == "settings":
                        self._settings_panel_visible = False
            # i034: ドラッグバーを透過化（hide せずスペース維持 → 位置ずれ防止）
            if hasattr(self, "_mw_drag_bar"):
                self._mw_drag_bar.set_roulette_only(True)
            # i462/i463/i464/i465: 各ルーレットパネル内の補助 UI を設定に従い非表示
            for _rid in self._manager.ids():
                _ctx = self._manager.get(_rid)
                if _ctx and _ctx.panel:
                    _p = _ctx.panel
                    if not _s.roulette_only_show_selection_handle:
                        _p._selection_handle.hide()
                    if not _s.roulette_only_show_title_plate:
                        _p._title_plate.hide()
                    if not _s.roulette_only_show_graph_btn:
                        _p._graph_btn.hide()
            # ウィンドウ・ルーレットを透過
            self._apply_window_transparent(True)
            self._apply_roulette_transparent(True)
            # i469: roulette_only_active/log_show フラグを設定
            for _rid_log in self._manager.ids():
                _ctx_log = self._manager.get(_rid_log)
                if _ctx_log and _ctx_log.panel:
                    _p_log = _ctx_log.panel
                    _p_log._roulette_only_active = True
                    _p_log._roulette_only_log_show = _s.roulette_only_show_log
            # i058: ウィンドウフラグが変化した場合のみ setWindowFlags → show を実行する。
            # 起動時は _apply_window_flags() が既に NoDropShadowWindowHint を含むため
            # フラグが一致し、ネイティブウィンドウ再生成フラッシュを回避できる。
            flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
                     | Qt.WindowType.NoDropShadowWindowHint)
            if self._settings.always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            if self.windowFlags() != flags:
                _win_pos = self.pos()
                was_visible = self.isVisible()
                self.setWindowFlags(flags)
                if was_visible:
                    self.show()
                self.move(_win_pos)  # 位置を復元
            self._dwm_set_borderless(int(self.winId()), True)
        else:
            saved = self._roulette_only_saved_visibility
            # setWindowFlags+show による OS 位置ずれを防ぐため事前に画面位置を保存
            _win_pos = self.pos()
            was_visible = self.isVisible()
            self._apply_window_flags()
            if was_visible:
                self.show()
            self._dwm_set_borderless(int(self.winId()), False)
            self.move(_win_pos)  # 位置を復元
            # ウィンドウサイズを復元
            if "window_size" in saved:
                self.resize(saved["window_size"])
            # i034: ドラッグバーを通常表示に戻す（set_roulette_only で管理）
            if hasattr(self, "_mw_drag_bar"):
                self._mw_drag_bar.set_roulette_only(False)
                self._mw_drag_bar.setGeometry(
                    0, 0, self.width(), self._mw_drag_bar._BAR_HEIGHT
                )
                self._mw_drag_bar.raise_()
            self._apply_window_transparent(saved.get("window_transparent", False))
            self._apply_roulette_transparent(saved.get("roulette_transparent", False))
            # サイドパネルをループで復元（seq_dialog を含む）
            offsets = saved.get("panel_offsets", {})
            for key, sp, _ in self._sidebar_panel_entries():
                if not saved.get(key, False):
                    continue
                sp.show()
                ox, oy = offsets.get(key, (sp.x(), sp.y()))
                new_x, new_y = self._clamp_to_client(ox, oy, sp.width(), sp.height())
                sp.move(new_x, new_y)
            if saved.get("settings", False):
                self._settings_panel_visible = saved.get("settings_panel_visible", True)
            # i462/i463/i465: 各ルーレットパネルの補助 UI を復元
            _rp_ui_saved = saved.get("rp_ui", {})
            for _rid in self._manager.ids():
                _ctx = self._manager.get(_rid)
                if _ctx and _ctx.panel:
                    _p = _ctx.panel
                    _ui = _rp_ui_saved.get(_rid, {})
                    if _ui.get("selection_handle", True):
                        _p._selection_handle.show()
                    if _ui.get("title_plate", True):
                        _p._title_plate.show()
                    if _ui.get("graph_btn", True):
                        _p._graph_btn.show()
                    # i469: roulette_only 状態をリセットしてからログオーバーレイを復元
                    _p._roulette_only_active = False
                    _p._roulette_only_log_show = True
                    _p._refresh_log_overlay()

        # i120: グリップ表示状態を現在設定から再計算して全ルーレットへ同期する。
        # 局所的な show/hide による状態ズレを防ぐため、ON/OFF どちらの経路でも
        # 最終状態を _effective_roulette_grip_visible() から一元決定する。
        self._sync_roulette_grips_visible()
        # i101: roulette_only_mode の ON/OFF 変更時にアイドルタイマーを再評価する。
        # auto_hide_only_in_roulette_only_mode = ON の場合、
        # roulette_only_mode = ON でタイマー起動、OFF でタイマー停止の切り替えが
        # _reset_idle_timer() によって行われる。
        self._reset_idle_timer()

    def _recalc_multi_roulette_only_bounds(self):
        """i335 以降: 動的ウィンドウ境界追従は無効。geometry_changed 接続先として残す。"""
        return

    def _on_roulette_window_drag(self, delta):
        """roulette_only_mode 時のルーレットドラッグをウィンドウ移動に変換する。

        i039: roulette_only_mode は使用しないため実質未呼出。接続先として残す。
        """
        self.move(self.pos() + delta)

    def _on_roulette_window_resize(self, new_size):
        """roulette_only_mode 時のルーレットリサイズをウィンドウリサイズに反映する。

        i039: roulette_only_mode は使用しないため実質未呼出。接続先として残す。
        """
        self.resize(new_size)

    # ================================================================
    #  UI トグル / apply 系
    # ================================================================

    def _toggle_always_on_top(self):
        """常に最前面の ON/OFF を切り替える。

        v0.6.1: setWindowFlags 後の show だけでは Windows で即時反映されない
        ことがあるため、raise_() + activateWindow() で確実に前面化する。
        """
        self._apply_always_on_top(not self._settings.always_on_top)

    def _apply_always_on_top(self, enabled: bool):
        """常に最前面の設定値をメインウィンドウへ即時反映する。"""
        self._settings.always_on_top = bool(enabled)
        was_visible = self.isVisible()
        self._apply_window_flags()
        if was_visible:
            self.show()
            self._apply_native_topmost(self._settings.always_on_top)
            if self._settings.always_on_top:
                self.raise_()
                self.activateWindow()
        # i471: floating 中の全パネルにも always_on_top を同期する
        self._reapply_floating_panel_flags()
        # v0.6.1: 管理パネル側のチェックボックスを同期
        if hasattr(self, "_manage_panel") and hasattr(
            self._manage_panel, "update_app_setting"
        ):
            self._manage_panel.update_app_setting(
                "always_on_top", self._settings.always_on_top
            )
        self._save_config()

    def _apply_native_topmost(self, enabled: bool, widget=None):
        """Apply topmost state immediately on Windows."""
        try:
            target = widget if widget is not None else self
            hwnd = int(target.winId())
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST if enabled else HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def _floating_panel_flags(self):
        """独立化パネルに適用する windowFlags を返す。always_on_top と同期する。

        i471: メインウィンドウが WindowStaysOnTopHint を持つ場合、
        独立化パネルも同じ hint を持たないとメインウィンドウの裏に隠れる。
        """
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self._settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def _reapply_floating_panel_flags(self):
        """floating 中の全パネルの windowFlags を always_on_top と同期する。

        i471: _toggle_always_on_top 時に呼び出す。
        hide → setWindowFlags → show の手順を踏むことで flags が確実に反映される。
        """
        flags = self._floating_panel_flags()
        for panel in (self._manage_panel, self._item_panel):
            if getattr(panel, '_floating', False):
                was_vis = panel.isVisible()
                panel.hide()
                panel.setWindowFlags(flags)
                if was_vis:
                    panel.show()
                    self._apply_native_topmost(self._settings.always_on_top, panel)
                    panel.raise_()
        # 設定パネルは _settings_panel_visible で可視状態を管理する
        sp = self._settings_panel
        if getattr(sp, '_floating', False):
            was_vis = self._settings_panel_visible
            sp.hide()
            sp.setWindowFlags(flags)
            if was_vis:
                sp.show()
                self._apply_native_topmost(self._settings.always_on_top, sp)
                sp.raise_()

    def _toggle_grip_visible(self):
        """リサイズグリップの表示/非表示を切り替える。"""
        new_val = not self._settings.grip_visible
        self._settings.grip_visible = new_val
        self._apply_grip_visible(new_val)
        self._settings_panel.update_setting("grip_visible", new_val)
        self._save_config()

    # ----------------------------------------------------------------
    #  移動バー表示状態の保存ハンドラ (E: i294)
    # ----------------------------------------------------------------

    def _on_item_panel_drag_bar_changed(self, visible: bool):
        self._settings.items_panel_drag_bar_visible = visible
        self._save_config()

    def _on_settings_panel_drag_bar_changed(self, visible: bool):
        self._settings.settings_panel_drag_bar_visible = visible
        self._save_config()

    def _on_manage_panel_drag_bar_changed(self, visible: bool):
        self._settings.manage_panel_drag_bar_visible = visible
        self._save_config()

    def _toggle_ctrl_box_visible(self):
        """コントロールボックスの表示/非表示を切り替える。"""
        new_val = not self._settings.ctrl_box_visible
        self._settings.ctrl_box_visible = new_val
        self._apply_ctrl_box_visible(new_val)
        self._settings_panel.update_setting("ctrl_box_visible", new_val)
        self._save_config()

    def _toggle_show_instance(self):
        """インスタンス番号表示の ON/OFF を切り替える。"""
        new_val = not self._settings.float_win_show_instance
        self._settings.float_win_show_instance = new_val
        self._update_instance_labels()
        self._settings_panel.update_setting("float_win_show_instance", new_val)
        self._save_config()

    def _toggle_settings_panel_float(self):
        """設定パネルのフローティング独立化を切り替える。"""
        new_val = not self._settings.settings_panel_float
        self._settings.settings_panel_float = new_val
        self._apply_settings_panel_float(new_val)
        self._settings_panel.update_setting("settings_panel_float", new_val)
        self._save_config()

    def _toggle_manage_panel_float(self):
        """管理パネルのフローティング独立化を切り替える。"""
        new_val = not self._settings.manage_panel_float
        self._settings.manage_panel_float = new_val
        self._apply_manage_panel_float(new_val)
        self._manage_panel.set_manage_float(new_val)
        self._save_config()

    def _apply_manage_panel_float(self, floating: bool):
        """管理パネルの埋め込み/フローティングを切り替える。"""
        mp = self._manage_panel
        was_visible = mp.isVisible()

        cur_w, cur_h = mp.width(), mp.height()
        if floating:
            global_pos = mp.mapToGlobal(QPoint(0, 0))
            cur_x, cur_y = global_pos.x(), global_pos.y()
        else:
            parent = self.centralWidget()
            if parent:
                local_pos = parent.mapFromGlobal(mp.pos())
                cur_x, cur_y = local_pos.x(), local_pos.y()
            else:
                cur_x, cur_y = mp.x(), mp.y()

        mp.hide()

        if floating:
            mp.setParent(None)
            # i471: always_on_top と同期した flags を適用する（WindowStaysOnTopHint を含む）
            mp.setWindowFlags(self._floating_panel_flags())
            mp._floating = True
            mp.setWindowTitle("RRoulette - 管理パネル")
            mp.setGeometry(cur_x, cur_y, cur_w, cur_h)
        else:
            central = self.centralWidget()
            mp.setParent(central)
            mp.setWindowFlags(Qt.WindowType.Widget)
            mp._floating = False
            pw = central.width() if central else self.width()
            ph = central.height() if central else self.height()
            cur_x = max(0, min(cur_x, pw - cur_w))
            cur_y = max(0, min(cur_y, ph - cur_h))
            mp.setGeometry(cur_x, cur_y, cur_w, cur_h)

        if was_visible:
            mp.show()
            if floating:
                mp.raise_()
                mp.activateWindow()
            else:
                mp.raise_()

    def _toggle_items_panel_float(self):
        """項目パネルのフローティング独立化を切り替える。"""
        new_val = not self._settings.items_panel_float
        self._settings.items_panel_float = new_val
        self._apply_items_panel_float(new_val)
        self._item_panel.set_items_float(new_val)
        self._save_config()

    def _apply_items_panel_float(self, floating: bool):
        """項目パネルの埋め込み/フローティングを切り替える。"""
        ip = self._item_panel
        was_visible = ip.isVisible()

        cur_w, cur_h = ip.width(), ip.height()
        if floating:
            global_pos = ip.mapToGlobal(QPoint(0, 0))
            cur_x, cur_y = global_pos.x(), global_pos.y()
        else:
            parent = self.centralWidget()
            if parent:
                local_pos = parent.mapFromGlobal(ip.pos())
                cur_x, cur_y = local_pos.x(), local_pos.y()
            else:
                cur_x, cur_y = ip.x(), ip.y()

        ip.hide()

        if floating:
            ip.setParent(None)
            # i471: always_on_top と同期した flags を適用する
            ip.setWindowFlags(self._floating_panel_flags())
            ip._floating = True
            ip.setWindowTitle("RRoulette - 項目パネル")
            ip.setGeometry(cur_x, cur_y, cur_w, cur_h)
        else:
            central = self.centralWidget()
            ip.setParent(central)
            ip.setWindowFlags(Qt.WindowType.Widget)
            ip._floating = False
            pw = central.width() if central else self.width()
            ph = central.height() if central else self.height()
            cur_x = max(0, min(cur_x, pw - cur_w))
            cur_y = max(0, min(cur_y, ph - cur_h))
            ip.setGeometry(cur_x, cur_y, cur_w, cur_h)

        if was_visible:
            ip.show()
            if floating:
                ip.raise_()
                ip.activateWindow()
            else:
                ip.raise_()

    def _apply_settings_panel_float(self, floating: bool):
        """設定パネルの埋め込み/フローティングを切り替える。"""
        sp = self._settings_panel
        was_visible = self._settings_panel_visible

        # 現在の位置・サイズを保存
        if was_visible:
            cur_w, cur_h = sp.width(), sp.height()
            if floating:
                # 埋め込み→フローティング: 親内座標→スクリーン座標に変換
                global_pos = sp.mapToGlobal(QPoint(0, 0))
                cur_x, cur_y = global_pos.x(), global_pos.y()
            else:
                # フローティング→埋め込み: スクリーン座標→親内座標に変換
                parent = self.centralWidget()
                if parent:
                    local_pos = parent.mapFromGlobal(sp.pos())
                    cur_x, cur_y = local_pos.x(), local_pos.y()
                else:
                    cur_x, cur_y = sp.x(), sp.y()
        else:
            cur_w = getattr(self, '_last_sp_w', sp._panel_min_w)
            cur_h = getattr(self, '_last_sp_h', 400)
            cur_x = getattr(self, '_last_sp_x', 0)
            cur_y = getattr(self, '_last_sp_y', 0)

        # 一旦隠す
        sp.hide()

        if floating:
            # フローティング化: 親から切り離し
            sp.setParent(None)
            # i471: always_on_top と同期した flags を適用する
            sp.setWindowFlags(self._floating_panel_flags())
            sp._floating = True
            sp.setWindowTitle("RRoulette - 設定パネル")
            # スクリーン座標で配置
            sp.setGeometry(cur_x, cur_y, cur_w, cur_h)
        else:
            # 埋め込み化: 親に戻す
            central = self.centralWidget()
            sp.setParent(central)
            sp.setWindowFlags(Qt.WindowType.Widget)
            sp._floating = False
            # 親内座標で配置（クランプ）
            pw = central.width() if central else self.width()
            ph = central.height() if central else self.height()
            cur_x = max(0, min(cur_x, pw - cur_w))
            cur_y = max(0, min(cur_y, ph - cur_h))
            sp.setGeometry(cur_x, cur_y, cur_w, cur_h)

        # 表示復元
        if was_visible:
            sp.show()
            if floating:
                sp.raise_()
                sp.activateWindow()
            else:
                sp.raise_()

        # 保存座標を更新
        self._last_sp_w = cur_w
        self._last_sp_h = cur_h
        self._last_sp_x = cur_x
        self._last_sp_y = cur_y

    def _effective_roulette_grip_visible(self) -> bool:
        """ルーレットパネルのグリップ実効表示状態を返す。

        grip_visible と roulette_only_mode / roulette_only_show_grip の組み合わせで
        一意に決まる。
        """
        return bool(
            self._settings.grip_visible
            and (
                not self._settings.roulette_only_mode
                or self._settings.roulette_only_show_grip
            )
        )

    def _sync_roulette_grips_visible(self) -> None:
        """全ルーレットパネルのグリップ表示状態を現在設定から再計算して同期する。

        局所的な show/hide の積み重ねによる状態ズレを防ぐため、
        常に設定値から算出した実効状態を全パネルへ適用する。
        """
        visible = self._effective_roulette_grip_visible()
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx is None or ctx.panel is None:
                continue
            grip = getattr(ctx.panel, "_grip", None)
            if grip is not None:
                grip.setVisible(visible)
                if visible:
                    grip.reposition()
                    grip.raise_()

    def _apply_grip_visible(self, visible: bool):
        """全パネルのリサイズグリップの表示状態を反映する。"""
        self._settings.grip_visible = bool(visible)
        self._sync_roulette_grips_visible()
        if hasattr(self._settings_panel, "_resize_grip"):
            self._settings_panel._resize_grip.setVisible(bool(visible))

    def _apply_ctrl_box_visible(self, visible: bool):
        """コントロールボックス相当UIの表示状態を反映する。

        PySide6 側では v0.4.4 のコントロールボックス（最小化/閉じるボタン群）に
        直接対応するUIがない。ここでは SettingsPanel のスピンセクション
        （スピンボタン + プリセット選択行）を「操作ボックス」相当とみなし、
        その表示/非表示を制御する。
        """
        self._settings_panel.set_spin_section_visible(visible)

    # ================================================================
    #  継続操作判定ヘルパー
    # ================================================================

    def _is_operation_active(self) -> bool:
        """自動全面非表示を抑止すべき継続操作中かを返す。

        スピン中（is_spinning）のみ True を返す。
        結果表示中や連続抽選 runner 実行中はアイドルカウント継続扱い。
        """
        return self._is_any_spinning()

    # ================================================================
    #  全面非表示 (i485)
    # ================================================================

    def _hide_all(self):
        """RRoulette 全体を全面非表示にする（手動 Esc・自動アイドル共通）。

        メインウィンドウを最小化し（タスクバーに残る）、フローティング中の
        パネルは hide する。再アクティブ化（showNormal / changeEvent）で復元。
        フェード完了後から呼ばれる場合は opacity はすでに 0 になっているが、
        minimize/hide 後に復元時に 1.0 に戻す。
        """
        if getattr(self, '_is_all_hidden', False):
            return
        # フェード中フラグをクリア（フェード完了後の呼び出しに備える）
        self._auto_hide_fading = False
        # フローティングパネルの可視状態を保存して hide
        saved = {}
        for panel in (self._settings_panel, self._item_panel, self._manage_panel):
            if getattr(panel, '_floating', False) and panel.isVisible():
                saved[id(panel)] = panel
                panel.hide()
        self._all_hidden_saved_panels = saved
        self._is_all_hidden = True
        # アイドルタイマーを停止
        if hasattr(self, '_idle_timer'):
            self._idle_timer.stop()
        # メインウィンドウを最小化（タスクバー・Alt+Tab から復帰可能）
        self.showMinimized()

    def _restore_all(self):
        """全面非表示を復元する（changeEvent での WindowStateChange 復帰時に呼ぶ）。

        メインウィンドウは既に showNormal になった後に呼ばれる前提。
        hide していたフローティングパネルを再表示し、opacity を 1.0 に戻す。
        """
        if not getattr(self, '_is_all_hidden', False):
            return
        self._is_all_hidden = False
        # i066: キャンバスオーバーレイを破棄（フェード中断後に残留している場合に備える）
        self._destroy_auto_hide_overlay()
        # フローティングパネル復元
        for panel in (self._settings_panel, self._item_panel, self._manage_panel):
            if id(panel) in getattr(self, '_all_hidden_saved_panels', {}):
                panel.show()
                panel.raise_()
        self._all_hidden_saved_panels = {}
        # i098: 再表示後スピン後に有効オプション — スピン待機フラグを立てる
        if self._settings.auto_hide_after_spin_after_restore:
            self._auto_hide_waiting_spin_after_restore = True
        # i102: roulette_only_mode 中に最小化復帰した場合、DWM ボーダーレス属性を再適用する
        # (Windows は minimize/restore で DWM 属性をリセットする場合がある)
        if self._settings.roulette_only_mode:
            self._dwm_set_borderless(int(self.winId()), True)
        # アイドルタイマー再開
        self._reset_idle_timer()

    def _should_auto_hide_timer_run(self) -> bool:
        """自動全面非表示タイマーを起動すべきか判定する。

        i102: 複数ヶ所に散らばっていた条件判定を一箇所に集約する。
        Returns:
            True: タイマーを起動すべき / False: タイマーを停止すべき
        """
        if not self._settings.auto_hide_enabled:
            return False
        if self._settings.auto_hide_seconds <= 0:
            return False
        # ルーレット以外非表示時のみ有効: roulette_only_mode が OFF なら無効
        if (self._settings.auto_hide_only_in_roulette_only_mode
                and not self._settings.roulette_only_mode):
            return False
        # 再表示後スピン後に有効: スピン待機中はタイマーを起動しない
        if (self._settings.auto_hide_after_spin_after_restore
                and getattr(self, '_auto_hide_waiting_spin_after_restore', False)):
            return False
        return True

    def _reset_idle_timer(self):
        """アイドルタイマーをリセットする（ユーザー操作・復元時に呼ぶ）。

        フェード中であれば中断して opacity を復元する。
        全面非表示中・auto_hide_enabled=False・seconds<=0 のときはタイマー停止のみ。
        """
        if not hasattr(self, '_idle_timer'):
            return
        if getattr(self, '_is_all_hidden', False):
            return
        # フェード中なら中断して opacity を元に戻す
        if getattr(self, '_auto_hide_fading', False):
            self._cancel_auto_hide_fade()
        if self._should_auto_hide_timer_run():
            self._idle_timer.start(self._settings.auto_hide_seconds * 1000)
        else:
            self._idle_timer.stop()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """ウィンドウリサイズ時にフェードオーバーレイのサイズを追従させる。"""
        super().resizeEvent(event)
        overlay = getattr(self, '_auto_hide_overlay', None)
        if overlay is not None:
            overlay.setGeometry(self.rect())

    def _start_auto_hide_fade(self):
        """自動全面非表示のフェードアウトを開始する（アイドルタイマー満了時に呼ぶ）。

        フェード有効時: キャンバス描画ベースのオーバーレイでフェード → `_hide_all()`。
        setWindowOpacity は OBS に映らないため、ウィンドウ内の描画変化で代替する (i066)。
        フェード無効時: 即座に `_hide_all()`。
        スピン中の場合はアイドルタイマーを再セットして非表示を保留する。
        """
        if getattr(self, '_is_all_hidden', False):
            return
        if getattr(self, '_auto_hide_fading', False):
            return

        # モーダルダイアログ（QFileDialog 等）表示中は発火させずタイマーを再セット
        # QApplication.activeModalWidget() はモーダルウィンドウが開いている間 None 以外を返す
        if QApplication.activeModalWidget() is not None:
            if self._settings.auto_hide_enabled and self._settings.auto_hide_seconds > 0:
                self._idle_timer.start(self._settings.auto_hide_seconds * 1000)
            return

        # 継続操作中（スピン中・結果表示中・連続抽選実行中）は非表示へ進まずタイマーを再セット
        if self._is_operation_active():
            if self._settings.auto_hide_enabled and self._settings.auto_hide_seconds > 0:
                self._idle_timer.start(self._settings.auto_hide_seconds * 1000)
            return

        if not self._settings.auto_hide_fade_enabled:
            self._hide_all()
            return

        self._auto_hide_fading = True
        # フェード時間: 設定値（秒）をミリ秒に変換。範囲は 100〜2000ms にクランプ
        fade_ms = int(max(0.1, min(10.0, self._settings.auto_hide_fade_seconds)) * 1000)

        # i066: キャンバス描画ベースのオーバーレイ（OBS に映る）
        bg_color = getattr(self._design, 'bg', '#000000')
        overlay = _CanvasFadeOverlay(self, bg_color)
        self._auto_hide_overlay = overlay

        anim = QVariantAnimation(self)
        anim.setStartValue(0)
        anim.setEndValue(255)
        anim.setDuration(fade_ms)
        anim.valueChanged.connect(lambda v: overlay.set_alpha(int(v)))
        anim.finished.connect(self._on_auto_hide_fade_done)
        self._auto_hide_anim = anim  # GC 防止のため参照保持
        anim.start()

    def _on_auto_hide_fade_done(self):
        """フェード完了コールバック — 全面非表示処理へ移行する。"""
        self._auto_hide_anim = None
        self._destroy_auto_hide_overlay()
        # 二重呼び出し防止（_hide_all 内でフラグをクリア）
        self._hide_all()

    def _cancel_auto_hide_fade(self):
        """フェード中断 — アニメーションを止めてオーバーレイを破棄する。"""
        self._auto_hide_fading = False
        anim = getattr(self, '_auto_hide_anim', None)
        if anim is not None:
            anim.stop()
            self._auto_hide_anim = None
        self._destroy_auto_hide_overlay()

    def _destroy_auto_hide_overlay(self) -> None:
        """フェードオーバーレイを破棄する（存在しない場合は何もしない）。"""
        overlay = getattr(self, '_auto_hide_overlay', None)
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()
            self._auto_hide_overlay = None

    def _on_auto_hide_fade_changed(self, enabled: bool):
        """管理パネルのフェードアウト ON/OFF 変更を受け取る。"""
        self._settings.auto_hide_fade_enabled = enabled
        self._save_config()

    def _on_auto_hide_fade_seconds_changed(self, seconds: float):
        """管理パネルのフェードアウト時間変更を受け取る。"""
        self._settings.auto_hide_fade_seconds = max(0.1, min(10.0, seconds))
        self._save_config()

    def _on_auto_hide_enabled_changed(self, enabled: bool):
        """管理パネルの自動全面非表示 ON/OFF 変更を受け取る。"""
        self._settings.auto_hide_enabled = enabled
        self._reset_idle_timer()
        self._save_config()

    def _on_auto_hide_seconds_changed(self, seconds: int):
        """管理パネルの自動全面非表示秒数変更を受け取る。"""
        self._settings.auto_hide_seconds = max(1, seconds)
        self._reset_idle_timer()
        self._save_config()

    def _on_auto_hide_only_roulette_only_changed(self, enabled: bool):
        """管理パネルのルーレット以外非表示時のみ有効オプション変更を受け取る (i098)。"""
        self._settings.auto_hide_only_in_roulette_only_mode = enabled
        self._reset_idle_timer()
        self._save_config()

    def _on_auto_hide_after_spin_restore_changed(self, enabled: bool):
        """管理パネルの再表示後スピン後に有効オプション変更を受け取る (i098)。"""
        self._settings.auto_hide_after_spin_after_restore = enabled
        if not enabled:
            # OFF にしたら待機フラグをクリアして通常に戻す
            self._auto_hide_waiting_spin_after_restore = False
            self._reset_idle_timer()
        self._save_config()

    def _toggle_settings_panel(self):
        if self._settings_panel_visible:
            sp = self._settings_panel
            self._last_sp_w = sp.width()
            self._last_sp_h = sp.height()
            self._last_sp_x = sp.x()
            self._last_sp_y = sp.y()
            self._settings_panel.hide()
            self._settings_panel_visible = False
        else:
            self._show_settings_panel_at_saved_or_default()
