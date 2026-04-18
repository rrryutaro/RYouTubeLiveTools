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

    def _show_context_menu(self, pos):
        d = self._design
        s = self._settings
        menu = QMenu(self)
        menu.setStyleSheet(f"""
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
        """)

        # ルーレット以外非表示
        ro_mark = "\u25cf" if s.roulette_only_mode else "  "
        action = menu.addAction(f"{ro_mark} ルーレット以外非表示    ")
        action.triggered.connect(self._toggle_roulette_only_mode)

        # 常に最前面
        aot_mark = "\u25cf" if s.always_on_top else "  "
        action = menu.addAction(f"{aot_mark} 常に最前面    ")
        action.triggered.connect(self._toggle_always_on_top)

        # リサイズグリップ表示
        grip_mark = "\u25cf" if s.grip_visible else "  "
        action = menu.addAction(f"{grip_mark} リサイズグリップ表示    ")
        action.triggered.connect(self._toggle_grip_visible)

        menu.addSeparator()

        menu.addAction("  終了    ").triggered.connect(self.close)

        menu.exec(self.mapToGlobal(pos))

    # ================================================================
    #  設定変更アクション（コンテキストメニュー経由）
    # ================================================================

    def _set_profile(self, idx: int, w: int, h: int):
        self._settings.profile_idx = idx
        self._wheel_base_w = w
        self._wheel_base_h = h
        self.resize(w, h)
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
