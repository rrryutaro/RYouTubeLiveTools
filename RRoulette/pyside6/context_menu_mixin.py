"""
context_menu_mixin.py — 右クリックコンテキストメニュー Mixin

i449: main_window.py から分離。
責務:
  - 右クリックコンテキストメニューの構築・表示 (_show_context_menu)
  - コンテキストメニュー経由の設定変更アクション
      _set_profile, _set_text_size_mode, _toggle_donut

使用側:
  class MainWindow(ContextMenuMixin, UIToggleMixin, PackageIOMixin, ..., QMainWindow)
"""

from PySide6.QtWidgets import QMenu


class ContextMenuMixin:
    """右クリックコンテキストメニューの構築・表示責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  コンテキストメニュー
    # ================================================================

    def _menu_stylesheet(self) -> str:
        d = self._design
        return f"""
            QMenu {{
                background-color: {d.panel};
                color: {d.text};
                font-family: Meiryo;
                font-size: 10pt;
                border: 1px solid {d.separator};
            }}
            QMenu::item {{
                padding-top: 4px;
                padding-bottom: 4px;
                padding-left: 4px;
                padding-right: 32px;
            }}
            QMenu::item:selected {{
                background-color: {d.separator};
            }}
        """

    def _build_common_menu(self, menu) -> None:
        """パネル表示サブメニュー・各種トグル・終了 を menu に追加する。

        _show_context_menu と _show_context_menu_for_panel で共通利用。
        """
        s = self._settings
        _submenu_style = menu.styleSheet()

        # i462: パネル表示（最上段・サブメニュー）
        panel_menu = menu.addMenu("  パネル表示    ")
        panel_menu.setStyleSheet(_submenu_style)

        mp_mark = "\u25cf" if self._manage_panel.isVisible() else "  "
        a = panel_menu.addAction(f"{mp_mark} 管理パネル (F1)")
        a.triggered.connect(self._toggle_manage_panel)

        ip_mark = "\u25cf" if self._item_panel.isVisible() else "  "
        a = panel_menu.addAction(f"{ip_mark} 項目パネル (F2)")
        a.triggered.connect(self._toggle_item_panel)

        sp_mark = "\u25cf" if self._settings_panel_visible else "  "
        a = panel_menu.addAction(f"{sp_mark} 設定パネル (F3)")
        a.triggered.connect(self._toggle_settings_panel_v2)

        tp_mark = "\u25cf" if self._ticket_panel.isVisible() else "  "
        a = panel_menu.addAction(f"{tp_mark} チケットパネル (F4)")
        a.triggered.connect(self._toggle_ticket_panel)

        seq_visible = (self._seq_dialog is not None and self._seq_dialog.isVisible())
        seq_mark = "\u25cf" if seq_visible else "  "
        a = panel_menu.addAction(f"{seq_mark} 実行パネル (F5)")
        a.triggered.connect(self._toggle_sequential_spin_dialog)

        lp_visible = hasattr(self, '_link_panel') and self._link_panel.isVisible()
        lp_mark = "\u25cf" if lp_visible else "  "
        a = panel_menu.addAction(f"{lp_mark} 連携パネル (F6)")
        a.triggered.connect(self._toggle_link_panel)

        menu.addSeparator()

        # 常に最前面 (i463: ルーレット以外非表示より上に配置)
        aot_mark = "\u25cf" if s.always_on_top else "  "
        action = menu.addAction(f"{aot_mark} 常に最前面    ")
        action.triggered.connect(self._toggle_always_on_top)

        # ルーレット以外非表示 (Tab キー) — i463: 括弧付き表記に統一
        ro_mark = "\u25cf" if s.roulette_only_mode else "  "
        action = menu.addAction(f"{ro_mark} ルーレット以外非表示 (Tab)")
        action.triggered.connect(self._toggle_roulette_only_mode)

        # i463: リサイズグリップ表示項目を削除（管理パネル側で個別設定可能になったため）

        menu.addSeparator()

        menu.addAction("  終了    ").triggered.connect(self.close)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_stylesheet())
        self._build_common_menu(menu)
        menu.exec(self.mapToGlobal(pos))

    def _show_context_menu_for_panel(self, global_pos, drag_bar, on_drag_bar_changed=None):
        """パネル上の右クリックメニューを表示する (i107)。

        移動バーON/OFF（対象パネル依存）を先頭に追加し、
        以降は _show_context_menu と同じ共通メニューを表示する。
        """
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_stylesheet())

        # 移動バートグル（右クリックしたパネル専用）
        toggle_text = "✔ 移動バーを表示" if drag_bar.isVisible() else "  移動バーを表示"
        action = menu.addAction(toggle_text)

        def _toggle():
            new_vis = not drag_bar.isVisible()
            drag_bar.setVisible(new_vis)
            if on_drag_bar_changed is not None:
                on_drag_bar_changed(new_vis)

        action.triggered.connect(_toggle)
        menu.addSeparator()

        self._build_common_menu(menu)
        menu.exec(global_pos)

    # ================================================================
    #  設定変更アクション（コンテキストメニュー経由）
    # ================================================================

    def _set_profile(self, idx: int, w: int, h: int):
        self._settings.profile_idx = idx
        self._wheel_base_w = w
        self._wheel_base_h = h
        # i467: アクティブなルーレットパネルを即時リサイズする。
        if not self._settings.roulette_only_mode:
            self._active_panel.resize(w, h)
        self._settings_panel.update_setting("profile_idx", idx)
        self._save_config()

    def _set_text_size_mode(self, mode: int):
        self._settings.text_size_mode = mode
        self._active_panel.wheel.set_text_mode(mode, self._settings.text_direction)
        self._settings_panel.update_setting("text_size_mode", mode)
        self._save_config()

    def _toggle_donut(self):
        self._settings.donut_hole = not self._settings.donut_hole
        self._active_panel.wheel.set_donut_hole(self._settings.donut_hole)
        self._settings_panel.update_setting("donut_hole", self._settings.donut_hole)
        self._save_config()
