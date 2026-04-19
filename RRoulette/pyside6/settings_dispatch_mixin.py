"""
settings_dispatch_mixin.py — 設定変更ディスパッチ Mixin

i439: main_window.py から分離。
責務:
  - 設定変更シグナル受信 (_on_setting_changed)
  - アクション経由の設定変更・各コンポーネントへの反映 (_update_setting_by_action)
  - 全ルーレットへの一括設定適用 (_apply_setting_to_all_panels)
  - spin プリセット切替 (_on_preset_changed)
  - 音プレビュー (_on_preview_tick, _on_preview_win)
  - カスタム音ファイル変更 (_on_custom_tick_file, _on_custom_win_file)

使用側:
  class MainWindow(SettingsDispatchMixin, SpinFlowMixin,
                   RouletteLifecycleMixin, PanelGeometryMixin, QMainWindow)
"""

from bridge import SIZE_PROFILES, build_segments_from_entries
from dark_theme import resolve_theme_mode
from per_roulette_settings import PER_ROULETTE_KEYS
from roulette_actions import UpdateSettings


class SettingsDispatchMixin:
    """設定変更を各 UI / panel / sound / config へ反映する Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ------------------------------------------------------------------
    #  設定変更シグナル受信
    # ------------------------------------------------------------------

    def _on_setting_changed(self, key: str, value):
        """SettingsPanel からの設定変更を受けてアクション経由で反映する。"""
        self.apply_action(UpdateSettings(key=key, value=value))

    # ------------------------------------------------------------------
    #  アクション経由の設定変更
    # ------------------------------------------------------------------

    def _update_setting_by_action(self, key: str, value) -> bool:
        """アクション経由の設定変更。

        i369: per-roulette キー（PER_ROULETTE_KEYS）は active の ctx.settings に書く。
        global キーは self._settings に書く。これにより「全ルーレットに適用 OFF」時に
        他ルーレットへ個別設定が波及しない。

        Args:
            key: 設定キー名
            value: 設定値

        Returns:
            設定キーが有効なら True。
        """
        if not key:
            return False

        ctx = self._active_context
        rp = ctx.panel  # = self._active_panel

        # i369: 書き込み先を per-roulette / global で振り分ける。
        # per-roulette キー → active の ctx.settings（他ルーレットに波及しない）
        # global キー      → self._settings
        if key in PER_ROULETTE_KEYS:
            setattr(ctx.settings, key, value)
        elif hasattr(self._settings, key):
            setattr(self._settings, key, value)

        if key == "text_size_mode":
            # i369: 対になる text_direction は ctx.settings から読む（self._settings ではなく）
            rp.wheel.set_text_mode(value, ctx.settings.text_direction)
        elif key == "text_direction":
            # i369: 対になる text_size_mode は ctx.settings から読む
            rp.wheel.set_text_mode(ctx.settings.text_size_mode, value)
        elif key == "donut_hole":
            rp.wheel.set_donut_hole(value)
        elif key == "pointer_angle":
            rp.wheel.set_pointer_angle(value)
            return True
        elif key == "spin_direction":
            rp.wheel._spin_direction = value
        elif key == "profile_idx":
            idx = min(value, len(SIZE_PROFILES) - 1)
            _, w, h = SIZE_PROFILES[idx]
            self._wheel_base_w = w
            self._wheel_base_h = h
            # i467: アクティブなルーレットパネルを即時リサイズする。
            # roulette_only_mode 中はパネルがウィンドウ全体を占めているため除外。
            if not self._settings.roulette_only_mode:
                rp.resize(w, h)
        elif key == "result_close_mode":
            rp.result_overlay.set_close_mode(value)
        elif key == "result_hold_sec":
            rp.result_overlay.set_hold_sec(value)
        elif key == "sound_tick_enabled":
            rp.spin_ctrl.set_sound_tick_enabled(value)
        elif key == "sound_result_enabled":
            rp.spin_ctrl.set_sound_result_enabled(value)
        elif key == "tick_volume":
            self._sound.set_tick_volume(value / 100.0)
        elif key == "win_volume":
            self._sound.set_win_volume(value / 100.0)
        elif key == "tick_pattern":
            # i370: per-roulette — active パネルの SpinController に設定する
            rp.spin_ctrl.set_tick_pattern(value)
        elif key == "win_pattern":
            # i370: per-roulette — active パネルの SpinController に設定する
            rp.spin_ctrl.set_win_pattern(value)
        elif key == "log_overlay_show":
            # i342: ログ表示 ON/OFF をアクティブパネルに反映する。
            rp.wheel.set_log_visible(value)
        elif key == "log_timestamp":
            rp.wheel.set_log_timestamp(value)
        elif key == "log_box_border":
            rp.wheel.set_log_box_border(value)
        elif key == "log_on_top":
            rp.wheel.set_log_on_top(value)
        elif key == "log_history_all_patterns":
            # i395: active roulette 単位で記録・反映する（他ルーレットに波及しない）
            ctx.settings.log_all_patterns = value
            rp.wheel.set_log_all_patterns(value)
        elif key == "spin_duration":
            rp.spin_ctrl.set_spin_duration(value)
        elif key == "spin_mode":
            rp.spin_ctrl.set_spin_mode(value)
        elif key == "double_duration":
            rp.spin_ctrl.set_double_duration(value)
        elif key == "triple_duration":
            rp.spin_ctrl.set_triple_duration(value)
        elif key == "replay_max_count":
            # i351: 全ルーレットの ReplayManager に上限を適用する
            for _rp_mgr_v in self._replay_mgrs.values():
                _rp_mgr_v.set_max_count(value)
            _act_rp_mgr = self._active_replay_mgr
            self._settings_panel.set_replay_count(
                _act_rp_mgr.count() if _act_rp_mgr else 0
            )
        elif key == "replay_show_indicator":
            pass  # 値は AppSettings に保存済み。再生開始時に参照
        elif key == "window_transparent":
            self._apply_window_transparent(value)
        elif key == "roulette_transparent":
            self._apply_roulette_transparent(value)
        elif key == "always_on_top":
            if value != self._settings.always_on_top:
                self._toggle_always_on_top()
        elif key == "arrangement_direction":
            # 配置方向変更: config 更新 → セグメント再構築
            self._config["arrangement_direction"] = value
            ctx = self._active_context
            ctx.segments, _ = build_segments_from_entries(
                ctx.item_entries, self._config
            )
            rp.set_segments(ctx.segments)
        elif key == "grip_visible":
            self._apply_grip_visible(value)
        elif key == "ctrl_box_visible":
            self._apply_ctrl_box_visible(value)
        elif key == "float_win_show_instance":
            self._update_instance_labels()
        elif key == "settings_panel_float":
            self._apply_settings_panel_float(value)
        elif key == "show_item_prob":
            # i283: 項目行の確率行表示 ON/OFF。AppSettings に保存し、
            # SettingsPanel / ItemPanel 側にも反映を依頼する。
            self._settings.show_item_prob = bool(value)
            self._settings_panel.update_setting("show_item_prob", value)
            self._item_panel.update_setting("show_item_prob", value)
        elif key == "show_item_win_count":
            # i283: 項目行の当選回数表示 ON/OFF。
            self._settings.show_item_win_count = bool(value)
            self._settings_panel.update_setting("show_item_win_count", value)
            self._item_panel.update_setting("show_item_win_count", value)
        elif key == "item_panel_display_mode":
            # i289: 項目パネル表示モード切替。
            self._settings.item_panel_display_mode = int(value)
            self._item_panel.update_setting("item_panel_display_mode", value)
        elif key == "theme_mode":
            self._apply_app_theme(self._design)
            self._settings_panel.set_panel_theme_mode(value)
            # system モード時のみ OS テーマ監視を有効化
            if value in ("system", "auto"):
                self._last_os_theme = resolve_theme_mode("system")
                if not self._os_theme_timer.isActive():
                    self._os_theme_timer.start()
            else:
                self._os_theme_timer.stop()

        # i346: 全ルーレット一括適用（active パネルへの適用は上記で完了済み）
        if getattr(self, "_apply_to_all", False):
            self._apply_setting_to_all_panels(key, value)

        self._save_config()
        return True

    # ------------------------------------------------------------------
    #  全ルーレットへの一括設定適用
    # ------------------------------------------------------------------

    def _apply_setting_to_all_panels(self, key: str, value) -> None:
        """i346: active 以外の全ルーレットパネルに設定を一括適用する。

        active パネルへの適用は呼び出し元 (_update_setting_by_action) で済み。
        per-roulette な設定キーのみを扱い、グローバル設定は対象外。

        i369: runtime への適用と同時に ctx.settings も更新する。
        これにより active 切替時の _sync_settings_to_active が正しい値を読める。
        """
        if key not in PER_ROULETTE_KEYS:
            return  # グローバル系は対象外（早期リターン）

        for rid in self._manager.ids():
            if rid == self._manager.active_id:
                continue  # active は呼び出し元で適用済み（ctx.settings も済み）
            ctx = self._manager.get(rid)
            if ctx is None:
                continue
            p = ctx.panel
            # i369: ctx.settings を先に更新（runtime と同期を保つ）
            setattr(ctx.settings, key, value)
            # runtime への適用
            if key == "log_overlay_show":
                p.wheel.set_log_visible(value)
            elif key == "log_on_top":
                p.wheel.set_log_on_top(value)
            elif key == "log_timestamp":
                p.wheel.set_log_timestamp(value)
            elif key == "log_box_border":
                p.wheel.set_log_box_border(value)
            elif key == "spin_duration":
                p.spin_ctrl.set_spin_duration(value)
            elif key == "spin_mode":
                p.spin_ctrl.set_spin_mode(value)
            elif key == "double_duration":
                p.spin_ctrl.set_double_duration(value)
            elif key == "triple_duration":
                p.spin_ctrl.set_triple_duration(value)
            elif key == "sound_tick_enabled":
                p.spin_ctrl.set_sound_tick_enabled(value)
            elif key == "sound_result_enabled":
                p.spin_ctrl.set_sound_result_enabled(value)
            elif key == "result_close_mode":
                p.result_overlay.set_close_mode(value)
            elif key == "result_hold_sec":
                p.result_overlay.set_hold_sec(value)
            elif key == "donut_hole":
                p.wheel.set_donut_hole(value)
            elif key == "spin_direction":
                p.wheel._spin_direction = value
            elif key == "pointer_angle":
                p.wheel.set_pointer_angle(value)
            elif key == "text_size_mode":
                # 対になる text_direction は ctx.settings から読む（runtime ではなく）
                p.wheel.set_text_mode(value, ctx.settings.text_direction)
            elif key == "text_direction":
                # 対になる text_size_mode は ctx.settings から読む
                p.wheel.set_text_mode(ctx.settings.text_size_mode, value)
            elif key == "spin_preset_name":
                p.spin_ctrl.set_spin_preset(value)
            elif key == "tick_pattern":
                p.spin_ctrl.set_tick_pattern(value)
            elif key == "win_pattern":
                p.spin_ctrl.set_win_pattern(value)

    # ------------------------------------------------------------------
    #  spin プリセット切替
    # ------------------------------------------------------------------

    def _on_preset_changed(self, name: str):
        from spin_preset import SPIN_PRESETS
        ctx = self._active_context
        ctx.panel.spin_ctrl.set_spin_preset(name)
        # i369: spin_preset_name / spin_duration は per-roulette 設定 → ctx.settings に書く
        ctx.settings.spin_preset_name = name
        # プリセット切替時、そのプリセットの duration で spin_duration を連動更新
        if name in SPIN_PRESETS:
            dur = SPIN_PRESETS[name].duration
            ctx.settings.spin_duration = dur
            ctx.panel.spin_ctrl.set_spin_duration(dur)
            self._settings_panel.update_setting("spin_duration", dur)
        self._save_config()

    # ------------------------------------------------------------------
    #  音プレビュー
    # ------------------------------------------------------------------

    def _on_preview_tick(self):
        """tick音テスト再生。"""
        # i370: active ルーレットの per-roulette パターンを使う
        self._sound.preview_tick(self._active_context.settings.tick_pattern)

    def _on_preview_win(self):
        """result音テスト再生。"""
        # i370: active ルーレットの per-roulette パターンを使う
        self._sound.preview_win(self._active_context.settings.win_pattern)

    # ------------------------------------------------------------------
    #  カスタム音ファイル変更
    # ------------------------------------------------------------------

    def _on_custom_tick_file(self, path: str):
        """カスタムtick音ファイル変更。"""
        self._settings.tick_custom_file = path
        self._sound.load_tick_custom(path)
        self._save_config()

    def _on_custom_win_file(self, path: str):
        """カスタムresult音ファイル変更。"""
        self._settings.win_custom_file = path
        self._sound.load_win_custom(path)
        self._save_config()
