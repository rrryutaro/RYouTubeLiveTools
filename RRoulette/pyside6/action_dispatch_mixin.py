"""
action_dispatch_mixin.py — アクションディスパッチ Mixin

i451: main_window.py から分離。
責務:
  - アクション受付・記録条件制御 (apply_action)
  - アクション種別振り分け (_dispatch_action)
  - アクティブルーレット切替補助 (_set_active_roulette)
  - active_changed シグナルハンドラ (_on_active_changed)
  - ウィンドウタイトル管理 (_base_window_title, _update_title_active_id)
  - スピン中チェック (_is_any_spinning)

使用側:
  class MainWindow(ActionDispatchMixin, WindowFrameMixin, ContextMenuMixin, ..., QMainWindow)
"""

from roulette_actions import (
    RouletteAction, ActionOrigin,
    AddRoulette, RemoveRoulette, SetActiveRoulette,
    SpinRoulette, UpdateItemEntries, UpdateSettings,
)


class ActionDispatchMixin:
    """アクションの受付・振り分け・タイトル管理の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  アクションディスパッチャ（マクロ向け共通入口）
    # ================================================================

    def apply_action(self, action: RouletteAction, *,
                     origin: ActionOrigin = ActionOrigin.USER) -> bool:
        """アクションを実行する。

        マクロ記録・再生の共通入口。
        USER 起点の成功アクションのみ recorder へ記録する。
        MACRO 起点の成功アクションは記録しない。

        Args:
            action: 実行するアクション。
            origin: 実行起点。デフォルトは USER。

        Returns:
            操作が成功したら True、失敗（制約違反等）なら False。
        """
        ok = self._dispatch_action(action)
        if ok and origin == ActionOrigin.USER:
            self._recorder.record(action)
            if self._recorder.is_recording:
                self._update_title_active_id()
        return ok

    def _dispatch_action(self, action: RouletteAction) -> bool:
        """アクションを各ハンドラへ振り分ける。"""
        if isinstance(action, AddRoulette):
            return self._add_new_roulette(activate=action.activate) is not None
        elif isinstance(action, RemoveRoulette):
            return self._remove_roulette(action.roulette_id)
        elif isinstance(action, SetActiveRoulette):
            old_id = self._manager.active_id
            self._set_active_roulette(action.roulette_id)
            return self._manager.active_id != old_id
        elif isinstance(action, SpinRoulette):
            return self._spin_by_action(action.roulette_id)
        elif isinstance(action, UpdateItemEntries):
            return self._update_items_by_action(
                action.roulette_id, list(action.entries),
            )
        elif isinstance(action, UpdateSettings):
            return self._update_setting_by_action(action.key, action.value)
        return False

    def _set_active_roulette(self, roulette_id: str):
        """アクティブなルーレットを切り替え、SettingsPanel を追従させる。

        将来の複数ルーレット切替の統一入口。
        manager の set_active → SettingsPanel 同期をまとめる。
        """
        old_id = self._manager.active_id
        self._manager.set_active(roulette_id)
        # set_active は同一 ID では何もしないので、
        # 実際に変わった場合のみ同期する
        if self._manager.active_id != old_id:
            self._sync_settings_to_active()

    def _on_active_changed(self, roulette_id: str):
        """manager の active_changed シグナルに応答する。

        manager.set_active() が外部から呼ばれた場合にも
        SettingsPanel が追従するようにする。
        """
        self._sync_settings_to_active()
        # i333: 全ルーレットパネルのアクティブ表示を更新
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx and ctx.panel:
                ctx.panel.set_active(rid == roulette_id)
        # i333: 管理パネルのルーレット一覧を更新
        self._update_roulette_manage_panel()
        # 開発確認用: ウィンドウタイトルに active ID を反映
        self._update_title_active_id()

    def _base_window_title(self) -> str:
        """基本ウィンドウタイトルを返す。

        i462: 複数起動を廃止したためインスタンス番号は不要。
        常に "RRoulette" を返す。
        """
        return "RRoulette"

    def _update_title_active_id(self):
        """ウィンドウタイトルに recording / playback 状態のみを反映する。

        v0.4.4 と同じく、通常時は `RRoulette` (または `RRoulette #N`) のみを
        表示する。開発確認用の active ID は冗長なので含めない。
        REC / PLAY は実操作で意味のある情報なので、状態がある場合だけ
        末尾に付加する。
        """
        base = self._base_window_title()
        parts = []
        if self._recorder.is_recording:
            parts.append(f"REC:{self._recorder.count}")
        if self._macro_session.total_count > 0:
            play_label = f"PLAY:{self._macro_session.current_index}/{self._macro_session.total_count}"
            if self._macro_waiting_spin:
                play_label += " WAIT"
            elif self._macro_auto_advancing:
                play_label += " AUTO"
            parts.append(play_label)
        if parts:
            self.setWindowTitle(f"{base} [{', '.join(parts)}]")
        else:
            self.setWindowTitle(base)

    def _is_any_spinning(self) -> bool:
        """いずれかの roulette が spinning 中かを返す。"""
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx and ctx.panel.spin_ctrl.is_spinning:
                return True
        return False
