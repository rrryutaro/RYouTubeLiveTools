"""
accessor_helper_mixin.py — アクティブルーレット参照アクセサ + パスヘルパー Mixin

i454: main_window.py から分離。
責務:
  - アクティブ roulette の context / panel / entries / segments / replay_mgr への参照 property 群
  - ルーレットごとのリプレイ・ログ保存パス helper

使用側:
  class MainWindow(AccessorHelperMixin, ..., QMainWindow)
"""

import os

from roulette_context import RouletteContext
from roulette_panel import RoulettePanel
from replay_manager_pyside6 import ReplayManager


class AccessorHelperMixin:
    """アクティブルーレット参照と保存パス helper を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  アクティブルーレット参照（manager 経由）
    # ================================================================

    @property
    def _active_context(self) -> RouletteContext:
        """アクティブな RouletteContext を返す。"""
        return self._manager.active

    @property
    def _active_panel(self) -> RoulettePanel:
        """アクティブな RoulettePanel を返す。"""
        return self._manager.active.panel

    @property
    def _active_entries(self) -> list:
        """アクティブなルーレットの item_entries を返す。"""
        return self._manager.active.item_entries

    @property
    def _active_segments(self) -> list:
        """アクティブなルーレットの segments を返す。"""
        return self._manager.active.segments

    @property
    def _active_replay_mgr(self) -> ReplayManager | None:
        """アクティブなルーレットの ReplayManager を返す。"""
        return self._replay_mgrs.get(self._manager.active_id)

    # ================================================================
    #  ルーレットごとの保存パス helper
    # ================================================================

    def _roulette_replay_path(self, roulette_id: str) -> str:
        """i351: ルーレットごとのリプレイ保存パスを返す。

        "default" は後方互換のため旧パス（roulette_replay.json）を使う。
        それ以外は roulette_replay_{id}.json を使い、ルーレット間の
        リプレイ保存ファイルを分離する。
        """
        from config_utils import BASE_DIR
        if not roulette_id or roulette_id == "default":
            return os.path.join(BASE_DIR, "roulette_replay.json")
        safe_id = roulette_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return os.path.join(BASE_DIR, f"roulette_replay_{safe_id}.json")

    def _roulette_log_path(self, roulette_id: str) -> str:
        """i345: ルーレットごとのログ自動保存パスを返す。

        "default" は後方互換のため旧パス（roulette_autosave_log.json）を使う。
        それ以外は roulette_autosave_log_{id}.json を使い、ルーレット間の
        ログ自動保存ファイルを分離する。
        """
        if not roulette_id or roulette_id == "default":
            return self._log_autosave_path
        from config_utils import BASE_DIR
        safe_id = roulette_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return os.path.join(BASE_DIR, f"roulette_autosave_log_{safe_id}.json")
