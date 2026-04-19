"""
ui_toggle_mixin.py — ウィンドウ透過・ルーレットのみモード・UI トグル Mixin

i448: main_window.py から分離。
責務:
  - ウィンドウ/ルーレット透過適用 (_apply_window_transparent, _apply_roulette_transparent)
  - ルーレット以外非表示モード (_toggle_roulette_only_mode, _apply_roulette_only_mode,
      _apply_roulette_only_mode_single, _apply_roulette_only_mode_multi,
      _recalc_multi_roulette_only_bounds)
  - roulette_only 時のウィンドウドラッグ/リサイズ転送 (_on_roulette_window_drag,
      _on_roulette_window_resize)
  - 常に最前面 / グリップ / ドラッグバー / コントロールボックス / インスタンス表示 トグル
  - 設定パネルフローティング切替 (_toggle_settings_panel_float,
      _apply_settings_panel_float)
  - grip / ctrl_box 表示適用 (_apply_grip_visible, _apply_ctrl_box_visible)
  - 設定パネル表示トグル (_toggle_settings_panel)

使用側:
  class MainWindow(UIToggleMixin, PackageIOMixin, SettingsIOMixin, ..., QMainWindow)
"""

from PySide6.QtCore import Qt, QPoint


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

    # ================================================================
    #  ルーレット以外非表示モード
    # ================================================================

    def _toggle_roulette_only_mode(self):
        """ルーレット以外非表示モードの ON/OFF を切り替える。"""
        self._settings.roulette_only_mode = not self._settings.roulette_only_mode
        self._apply_roulette_only_mode(self._settings.roulette_only_mode)
        self._save_config()

    def _apply_roulette_only_mode(self, enabled: bool):
        """ルーレット以外非表示モードを適用する。

        i334: single / multi で挙動を分岐する。
          single (roulette 1件): 従来どおりウィンドウ操作に委譲。
          multi  (roulette 2件以上): 非ルーレット系パネルのみ非表示にし、
            各 roulette は現在位置のまま保持。ウィンドウを全 roulette の
            最小包含矩形へ追従させる。
        """
        if self._manager.count > 1:
            self._apply_roulette_only_mode_multi(enabled)
        else:
            self._apply_roulette_only_mode_single(enabled)

    def _apply_roulette_only_mode_single(self, enabled: bool):
        """single 時の `ルーレット以外非表示` 処理（従来ロジックを維持）。"""
        panel = self._active_panel
        if enabled:
            # ON 前の状態を保存（可視性・パネル位置・ウィンドウサイズ・透過状態）
            self._roulette_only_saved_visibility = {
                "item": self._item_panel.isVisible(),
                "settings": self._settings_panel.isVisible(),
                "manage": self._manage_panel.isVisible(),
                "window_transparent": self._settings.window_transparent,
                "roulette_transparent": self._settings.roulette_transparent,
                "panel_pos": QPoint(panel.pos()),
                "panel_size": panel.size(),
                "window_size": self.size(),
                "panel_offsets": {
                    "item":     (self._item_panel.x(),     self._item_panel.y()),
                    "settings": (self._settings_panel.x(), self._settings_panel.y()),
                    "manage":   (self._manage_panel.x(),   self._manage_panel.y()),
                },
                # i462: ルーレットパネル内の補助 UI 表示状態を保存
                "rp_selection_handle": panel._selection_handle.isVisible(),
                "rp_title_plate": panel._title_plate.isVisible(),
                "rp_graph_btn": panel._graph_btn.isVisible(),
                "rp_grip": panel._grip.isVisible(),
            }
            # パネルを非表示
            self._item_panel.hide()
            self._settings_panel.hide()
            self._settings_panel_visible = False
            self._manage_panel.hide()
            # ドラッグバーを非表示
            if hasattr(self, "_mw_drag_bar"):
                self._mw_drag_bar.hide()
            # i462/i463/i464/i465: ルーレットパネル内の補助 UI を設定に従い非表示
            # show=True → 表示維持、show=False → 非表示
            _s = self._settings
            if not _s.roulette_only_show_selection_handle:
                panel._selection_handle.hide()
            if not _s.roulette_only_show_title_plate:
                panel._title_plate.hide()
            if not _s.roulette_only_show_graph_btn:
                panel._graph_btn.hide()
            if not _s.roulette_only_show_grip:
                panel._grip.hide()
            # ウィンドウ背景とルーレットパネルを透過
            self._apply_window_transparent(True)
            self._apply_roulette_transparent(True)
            # ルーレットパネルをウィンドウ左上に寄せてウィンドウをパネルサイズへ
            panel.roulette_only_mode = True
            panel._grip._skip_parent_clamp = True
            panel.move(0, 0)
            self.resize(panel.width(), panel.height())
            # i469: roulette_only_active/log_show フラグを設定して _refresh_log_overlay で一括判定。
            # show() → resizeEvent → _sync_wheel() → _refresh_log_overlay() の流れで
            # visible_eff が正しく計算されるよう、show() 前にフラグを立てておく。
            panel._roulette_only_active = True
            panel._roulette_only_log_show = _s.roulette_only_show_log
            # ウィンドウから外枠・影を OS/Qt レベルで完全に除去
            was_visible = self.isVisible()
            flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
                     | Qt.WindowType.NoDropShadowWindowHint)
            if self._settings.always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            if was_visible:
                self.show()
            self._dwm_set_borderless(int(self.winId()), True)
        else:
            saved = self._roulette_only_saved_visibility
            was_visible = self.isVisible()
            self._apply_window_flags()
            if was_visible:
                self.show()
            self._dwm_set_borderless(int(self.winId()), False)
            panel.roulette_only_mode = False
            panel._grip._skip_parent_clamp = False
            dw = panel.width()  - saved["panel_size"].width()
            dh = panel.height() - saved["panel_size"].height()
            if "panel_pos" in saved:
                panel.move(saved["panel_pos"])
            if "window_size" in saved:
                new_w = saved["window_size"].width()  + max(0, dw)
                new_h = saved["window_size"].height() + max(0, dh)
                self.resize(new_w, new_h)
            if hasattr(self, "_mw_drag_bar"):
                self._mw_drag_bar.setGeometry(
                    0, 0, self.width(), self._mw_drag_bar._BAR_HEIGHT
                )
                self._mw_drag_bar.show()
                self._mw_drag_bar.raise_()
            self._apply_window_transparent(saved.get("window_transparent", False))
            self._apply_roulette_transparent(saved.get("roulette_transparent", False))
            old_rp_right  = saved["panel_pos"].x() + saved["panel_size"].width()
            old_rp_bottom = saved["panel_pos"].y() + saved["panel_size"].height()
            offsets = saved.get("panel_offsets", {})
            panel_entries = [
                ("item",     self._item_panel,     saved.get("item",     False)),
                ("settings", self._settings_panel, saved.get("settings", False)),
                ("manage",   self._manage_panel,   saved.get("manage",   False)),
            ]
            for key, sp, was_visible_panel in panel_entries:
                if not was_visible_panel:
                    continue
                sp.show()
                ox, oy = offsets.get(key, (sp.x(), sp.y()))
                shift_x = dw if ox >= old_rp_right  else 0
                shift_y = dh if oy >= old_rp_bottom else 0
                new_x, new_y = self._clamp_to_client(
                    ox + shift_x, oy + shift_y, sp.width(), sp.height()
                )
                sp.move(new_x, new_y)
            if saved.get("settings", False):
                self._settings_panel_visible = True
            # i462/i463: ルーレットパネル内の補助 UI を復元
            if saved.get("rp_selection_handle", True):
                panel._selection_handle.show()
            if saved.get("rp_title_plate", True):
                panel._title_plate.show()
            if saved.get("rp_graph_btn", True):
                panel._graph_btn.show()
            if saved.get("rp_grip", True):
                panel._grip.show()
            # i469: roulette_only 状態をリセットしてからログオーバーレイを復元
            panel._roulette_only_active = False
            panel._roulette_only_log_show = True
            panel._refresh_log_overlay()

    def _apply_roulette_only_mode_multi(self, enabled: bool):
        """multi 時の `ルーレット以外非表示` 処理。

        i335 修正:
          ON:  非ルーレット系パネルのみ非表示。各 roulette は現在位置のまま。
               roulette の移動は OFF 時と同様にメインウィンドウ内の通常移動とする。
               ウィンドウサイズの動的追従は行わない。
          OFF: 可視状態を ON 前に復元。roulette の位置/サイズは維持。
        """
        if enabled:
            # ON 前の状態を保存
            # i462: 各ルーレットパネルの補助 UI 表示状態も保存する
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
                "item": self._item_panel.isVisible(),
                "settings": self._settings_panel.isVisible(),
                "manage": self._manage_panel.isVisible(),
                "window_transparent": self._settings.window_transparent,
                "roulette_transparent": self._settings.roulette_transparent,
                "window_size": self.size(),
                "rp_ui": _rp_ui_saved,
            }
            # 非ルーレット系パネルのみ非表示
            self._item_panel.hide()
            self._settings_panel.hide()
            self._settings_panel_visible = False
            self._manage_panel.hide()
            if hasattr(self, "_mw_drag_bar"):
                self._mw_drag_bar.hide()
            # i462/i463/i464/i465: 各ルーレットパネル内の補助 UI を設定に従い非表示
            # show=True → 表示維持、show=False → 非表示
            _s = self._settings
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
                    if not _s.roulette_only_show_grip:
                        _p._grip.hide()
            # ウィンドウ・ルーレットを透過
            self._apply_window_transparent(True)
            self._apply_roulette_transparent(True)
            # i469: roulette_only_active/log_show フラグを設定（single と同様）
            for _rid_log in self._manager.ids():
                _ctx_log = self._manager.get(_rid_log)
                if _ctx_log and _ctx_log.panel:
                    _p_log = _ctx_log.panel
                    _p_log._roulette_only_active = True
                    _p_log._roulette_only_log_show = _s.roulette_only_show_log
            # ウィンドウフラグ: 外枠・影を除去
            was_visible = self.isVisible()
            flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
                     | Qt.WindowType.NoDropShadowWindowHint)
            if self._settings.always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            if was_visible:
                self.show()
            self._dwm_set_borderless(int(self.winId()), True)
            # 各 roulette は roulette_only_mode = False のまま。
            # ウィンドウ内の通常移動（OFF 時と同様）で扱う。
        else:
            saved = self._roulette_only_saved_visibility
            was_visible = self.isVisible()
            self._apply_window_flags()
            if was_visible:
                self.show()
            self._dwm_set_borderless(int(self.winId()), False)
            # ウィンドウサイズを復元
            if "window_size" in saved:
                self.resize(saved["window_size"])
            if hasattr(self, "_mw_drag_bar"):
                self._mw_drag_bar.setGeometry(
                    0, 0, self.width(), self._mw_drag_bar._BAR_HEIGHT
                )
                self._mw_drag_bar.show()
                self._mw_drag_bar.raise_()
            self._apply_window_transparent(saved.get("window_transparent", False))
            self._apply_roulette_transparent(saved.get("roulette_transparent", False))
            # 可視パネルを復元
            panel_entries = [
                ("item",     self._item_panel),
                ("settings", self._settings_panel),
                ("manage",   self._manage_panel),
            ]
            for key, sp in panel_entries:
                if saved.get(key, False):
                    sp.show()
            if saved.get("settings", False):
                self._settings_panel_visible = True
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
                    if _ui.get("grip", True):
                        _p._grip.show()
                    # i469: roulette_only 状態をリセットしてからログオーバーレイを復元
                    _p._roulette_only_active = False
                    _p._roulette_only_log_show = True
                    _p._refresh_log_overlay()

    def _recalc_multi_roulette_only_bounds(self):
        """i335: multi 時の動的ウィンドウ境界追従は無効化。

        i334 で実装した包含矩形追従ロジックは移動不具合を引き起こすため
        i335 で撤回。geometry_changed からの接続は残るが、何もしない。
        """
        return

    def _on_roulette_window_drag(self, delta):
        """roulette_only_mode 時のルーレットドラッグをウィンドウ移動に変換する。"""
        self.move(self.pos() + delta)

    def _on_roulette_window_resize(self, new_size):
        """roulette_only_mode 時のルーレットリサイズをウィンドウリサイズに反映する。"""
        self.resize(new_size)

    # ================================================================
    #  UI トグル / apply 系
    # ================================================================

    def _toggle_always_on_top(self):
        """常に最前面の ON/OFF を切り替える。"""
        self._settings.always_on_top = not self._settings.always_on_top
        was_visible = self.isVisible()
        self._apply_window_flags()
        if was_visible:
            self.show()  # setWindowFlags 後に再表示が必要
        # クイック設定バーのチェックボックスを同期
        self._settings_panel.update_setting(
            "always_on_top", self._settings.always_on_top
        )
        self._save_config()

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
            # i469: Tool は OS レベルでメインウィンドウに owned され z-order が下になる。
            # Window にして真の独立トップレベルウィンドウにする。
            mp.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            )
            mp._floating = True
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
            # i469: Tool → Window（manage パネルと同様の理由）
            ip.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            )
            ip._floating = True
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
            # i469: Tool → Window（manage パネルと同様の理由）
            sp.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            )
            sp._floating = True
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

    def _apply_grip_visible(self, visible: bool):
        """全パネルのリサイズグリップの表示状態を反映する。"""
        self._active_panel._grip.setVisible(visible)
        self._settings_panel._resize_grip.setVisible(visible)

    def _apply_ctrl_box_visible(self, visible: bool):
        """コントロールボックス相当UIの表示状態を反映する。

        PySide6 側では v0.4.4 のコントロールボックス（最小化/閉じるボタン群）に
        直接対応するUIがない。ここでは SettingsPanel のスピンセクション
        （スピンボタン + プリセット選択行）を「操作ボックス」相当とみなし、
        その表示/非表示を制御する。
        """
        self._settings_panel.set_spin_section_visible(visible)

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
