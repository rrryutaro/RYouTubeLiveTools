"""
spin_flow_mixin.py — Spin フロー Mixin

i438: main_window.py から分離。
責務:
  - アクション経由 spin 開始 (_spin_by_action)
  - 手動 / 全体 spin 開始 (_start_spin, _start_all_visible_spin)
  - spin 完了後の結果反映 (_on_spin_finished)
  - ポインタ角度変更 (_on_pointer_angle_changed, _on_pointer_angle_committed)
  - pattern_id 解決ヘルパー (_get_current_pattern_id, _get_pattern_id_for_ctx)

使用側: class MainWindow(SpinFlowMixin, RouletteLifecycleMixin, PanelGeometryMixin, QMainWindow)
"""

import random
import uuid as _uuid_mod

from bridge import (
    build_segments_from_entries,
    get_current_pattern_name,
    get_pattern_id,
)
from roulette_actions import LastSpinResult, SpinRoulette


class SpinFlowMixin:
    """Spin 開始・終了・結果反映の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ------------------------------------------------------------------
    #  アクション経由 spin
    # ------------------------------------------------------------------

    def _spin_by_action(self, roulette_id: str) -> bool:
        """アクション経由の spin 開始。

        Args:
            roulette_id: 対象 ID。空文字なら active を対象にする。

        Returns:
            spin を開始できたら True。
        """
        if roulette_id:
            ctx = self._manager.get(roulette_id)
        else:
            ctx = self._manager.active
        if ctx is None:
            return False
        panel = ctx.panel
        if panel.spin_ctrl.is_spinning:
            return False
        # i351: そのルーレット専用の ReplayManager が再生中なら spin 不可
        _spin_rp_mgr = self._replay_mgrs.get(ctx.roulette_id)
        if _spin_rp_mgr and _spin_rp_mgr.is_playing:
            return False
        # i465: auto_shuffle: スピン前にセグメントをランダム化（item_index保持で色維持）
        # v0.4.4 同様、entries ではなく segments を直接シャッフルする
        if self._settings.auto_shuffle and ctx.segments:
            segs = list(ctx.segments)
            random.shuffle(segs)
            angle = 0.0
            for seg in segs:
                seg.start_angle = angle
                angle += seg.arc
            ctx.segments = segs
            panel.set_segments(ctx.segments)
        self._settings_panel.set_spinning(True)
        panel.start_spin()
        return True

    # ------------------------------------------------------------------
    #  手動 / 全体 spin 開始
    # ------------------------------------------------------------------

    def _start_spin(self):
        # 手動 spin → auto advance を安全側で停止
        if self._macro_auto_advancing:
            print("[dev] auto advance stopped — manual spin requested")
            self._stop_auto_advance()
        self.apply_action(SpinRoulette())

    def _start_all_visible_spin(self):
        """表示中のすべてのルーレットを同時スピンする（Space キー用）。

        - 対象: 現在 isVisible() == True のルーレットパネルのみ
        - いずれかがすでに回転中なら再押下を無視する

        i352: 複数ルーレットを同時スピンするとき、group_id を全 spin_ctrl に付与する。
        group_id により replay 再生時に同時実行として再現できる。
        """
        targets = [
            ctx
            for rid in self._manager.ids()
            for ctx in [self._manager.get(rid)]
            if ctx and ctx.panel.isVisible()
        ]
        if not targets:
            return
        # いずれかが回転中なら無視
        if any(ctx.panel.spin_ctrl.is_spinning for ctx in targets):
            return
        if self._macro_auto_advancing:
            self._stop_auto_advance()
        # i352: 2台以上同時スピンの場合のみ group_id を付与する
        if len(targets) >= 2:
            group_id = _uuid_mod.uuid4().hex[:12]
            for ctx in targets:
                ctx.panel.spin_ctrl.set_replay_group_id(group_id)
        for ctx in targets:
            ctx.panel.start_spin()

    # ------------------------------------------------------------------
    #  pattern_id 解決ヘルパー
    # ------------------------------------------------------------------

    def _get_current_pattern_id(self, ctx) -> str:
        """指定コンテキストの現在パターン UUID を返す。

        i407: pattern_id が未設定の場合はその場で生成して登録する。
        non-default ルーレットは ctx.pattern_id_map を使い、
        default ルーレットは config["pattern_ids"] を使う。
        """
        if ctx is None:
            name = get_current_pattern_name(self._config)
            return get_pattern_id(self._config, name)
        if ctx.current_pattern_id:
            return ctx.current_pattern_id
        name = ctx.current_pattern or get_current_pattern_name(self._config)
        if ctx.item_patterns is not None:
            # non-default roulette: ctx.pattern_id_map を使う
            if name not in ctx.pattern_id_map:
                ctx.pattern_id_map[name] = str(_uuid_mod.uuid4())
            ctx.current_pattern_id = ctx.pattern_id_map[name]
            return ctx.current_pattern_id
        return get_pattern_id(self._config, name)

    def _get_pattern_id_for_ctx(self, ctx, pattern_name: str) -> str:
        """指定コンテキストの指定パターン名のUUIDを返す。

        i407: 存在しない場合はその場で生成して登録する。
        """
        if ctx.item_patterns is not None:
            if pattern_name not in ctx.pattern_id_map:
                ctx.pattern_id_map[pattern_name] = str(_uuid_mod.uuid4())
            return ctx.pattern_id_map[pattern_name]
        return get_pattern_id(self._config, pattern_name)

    # ------------------------------------------------------------------
    #  spin 完了後の結果反映
    # ------------------------------------------------------------------

    def _on_spin_finished(self, winner: str, seg_idx: int,
                          roulette_id: str = ""):
        self._settings_panel.set_spinning(False)
        # 直前当選結果を更新（manual / macro 共通の唯一の更新地点）
        self._last_spin_result = LastSpinResult(
            roulette_id=roulette_id,
            winner_text=winner,
            seg_index=seg_idx,
        )
        print(f"[dev] last_spin_result: roulette='{roulette_id}', "
              f"winner='{winner}', seg={seg_idx}")
        # ログオーバーレイに追加 + 自動保存
        if winner:
            ctx = self._manager.get(roulette_id) if roulette_id else self._manager.active
            # i407: pattern_id（UUID）ベースでログ記録する
            pattern_id = self._get_current_pattern_id(ctx)
            pattern_name = (ctx.current_pattern if ctx and ctx.current_pattern
                            else get_current_pattern_name(self._config))
            if ctx:
                ctx.panel.wheel.add_log_entry(winner, pattern_id)  # i407: UUID 渡し
                # i345: ルーレットごとに独立したログファイルへ保存し、
                # #3 のスピン結果が #1 のログファイルを上書きしないようにする
                ctx.panel.wheel.save_log(self._roulette_log_path(roulette_id))
            # 勝利数集計用履歴に記録
            self._win_history.record(winner, pattern_id, roulette_id or "default",
                                     pattern_name=pattern_name)
            self._win_history.save()
            self._update_win_counts()
            # i351: スピン完了後、active ルーレットのリプレイ件数を表示更新する
            if roulette_id == self._manager.active_id:
                _spin_fin_mgr = self._replay_mgrs.get(roulette_id)
                self._settings_panel.set_replay_count(
                    _spin_fin_mgr.count() if _spin_fin_mgr else 0
                )
            self._refresh_replay_dialog()
        # auto advance の再開は ResultOverlay.closed で行う（spin_finished 直後ではなく
        # 結果表示の hold 完了後に再開するため）

    # ------------------------------------------------------------------
    #  ポインタ角度
    # ------------------------------------------------------------------

    def _on_pointer_angle_changed(self, angle: float):
        # i369: pointer_angle は per-roulette 設定 → ctx.settings に書く
        self._active_context.settings.pointer_angle = angle
        self._settings_panel.update_setting("pointer_angle", angle)

    def _on_pointer_angle_committed(self):
        self._save_config()
