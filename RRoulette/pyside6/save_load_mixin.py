"""
save_load_mixin.py — 設定保存 / 読込 / 同期 Mixin

i452: main_window.py から分離。
責務:
  - アプリ設定保存 (_save_config)
  - per-roulette 設定の config への書き戻し (_flush_per_roulette_settings_to_config)
  - SettingsPanel / ItemPanel / DesignEditorDialog をアクティブコンテキストに同期
      (_sync_settings_to_active)

使用側:
  class MainWindow(SaveLoadMixin, ActionDispatchMixin, WindowFrameMixin, ..., QMainWindow)
"""

from PySide6.QtWidgets import QApplication

from bridge import save_config, get_pattern_names, get_current_pattern_name


class SaveLoadMixin:
    """設定の保存・同期責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  保存ヘルパー
    # ================================================================

    def _save_config(self):
        """アプリ設定・デザイン設定を config に書き戻して保存する。

        i281: offscreen QPA では (smoke test 等) ディスク書き込みを抑止する。
        本物の Windows / Linux / Mac セッションでは通常通り保存する。
        """
        try:
            if QApplication.platformName() == "offscreen":
                return
        except Exception:
            pass
        self._config.update(self._settings.to_config_patch())
        if self._design:
            self._config["design"] = self._design.to_dict()
        self._config["design_presets"] = self._preset_mgr.to_dict()
        # i366: per-roulette 実設定を設定変更のたびに config["roulettes"] へ反映する。
        # close 時の _save_window_state のみに頼ると、旧形式 config や初回起動後に
        # per-roulette エントリが存在せず、再起動時に全ルーレットがグローバル値へ
        # 引きずられる問題（他ルーレットへの波及）を防ぐ。
        self._flush_per_roulette_settings_to_config()
        save_config(self._config)

    def _flush_per_roulette_settings_to_config(self) -> None:
        """全ルーレットの per-roulette 実設定を self._config["roulettes"] に書き戻す。

        i366: _save_config() から呼び出し、設定変更のたびに per-roulette 設定を
        config に反映する。geometry 等の非設定フィールドは上書きしない。

        i368: per-roulette 設定の書き出し元を ctx.settings 経由に変更。
        ctx.settings への書き込みは現在も _update_setting_by_action / _sync_settings_to_active
        が担っているため、実値は runtime オブジェクトから ctx.settings へ同期した上でここに来る。
        移行過渡期として、ctx.settings の更新が済んでいない項目は panel runtime から直接読む。
        第2段階で ctx.settings を source-of-truth にした後、runtime 直読みを廃止する。
        """
        if not getattr(self, "_init_complete", False):
            return
        manager = getattr(self, "_manager", None)
        if manager is None:
            return
        # 既存エントリを id でインデックス化（geometry や item_patterns を保持）
        existing: dict[str, dict] = {}
        for e in self._config.get("roulettes", []):
            rid = e.get("id")
            if rid:
                existing[rid] = e
        for rid in manager.ids():
            ctx = manager.get(rid)
            if ctx is None:
                continue
            p = ctx.panel
            entry = existing.get(rid, {"id": rid})
            # i368: ctx.settings から per-roulette 設定を取り出して書き戻す。
            # ただし ctx.settings は現時点で第2段階以降の source-of-truth 移行前のため、
            # runtime オブジェクトの実値で ctx.settings を先に同期してから書き出す。
            # （active ルーレットは _sync_settings_to_active / _update_setting_by_action
            #   で随時更新されているが、非 active ルーレットは runtime が正）
            s = ctx.settings
            s.spin_preset_name     = p.spin_ctrl.preset_name
            s.spin_duration        = p.spin_ctrl._spin_duration
            s.spin_mode            = p.spin_ctrl._spin_mode
            s.double_duration      = p.spin_ctrl._double_duration
            s.triple_duration      = p.spin_ctrl._triple_duration
            s.sound_tick_enabled   = p.spin_ctrl._sound_tick_enabled
            s.sound_result_enabled = p.spin_ctrl._sound_result_enabled
            s.tick_pattern         = p.spin_ctrl._tick_pattern
            s.win_pattern          = p.spin_ctrl._win_pattern
            s.spin_direction       = p.wheel._spin_direction
            s.donut_hole           = p.wheel._donut_hole
            s.pointer_angle        = p.wheel._pointer_angle
            s.text_size_mode       = p.wheel._text_size_mode
            s.text_direction       = p.wheel._text_direction
            s.log_overlay_show     = p.wheel._log_visible
            s.log_on_top           = p.wheel._log_on_top
            s.log_timestamp        = p.wheel._log_timestamp
            s.log_box_border       = p.wheel._log_box_border
            s.result_close_mode    = p.result_overlay._close_mode
            s.result_hold_sec      = p.result_overlay._hold_sec
            # ctx.settings を config エントリへ書き出す（geometry・item_patterns は維持）
            entry.update(s.to_config_entry())
            existing[rid] = entry
        # 元の順序を保ちつつ新規 ID も末尾に追加してリストを再構築
        seen: set[str] = set()
        new_list: list[dict] = []
        for e in self._config.get("roulettes", []):
            rid = e.get("id")
            if rid and rid in existing:
                new_list.append(existing[rid])
                seen.add(rid)
        for rid in manager.ids():
            if rid not in seen and rid in existing:
                new_list.append(existing[rid])
        self._config["roulettes"] = new_list

    # ================================================================
    #  アクティブコンテキスト同期
    # ================================================================

    def _sync_settings_to_active(self):
        """SettingsPanel / ItemPanel / DesignEditorDialog の表示をアクティブコンテキストに同期する。

        i334: set_active_entries は SettingsPanel 内の詳細ビュー(item_rows)を
        再構築するが、ItemPanel のシンプルリストは item_entries_changed シグナル
        経由でしか更新されない。active 切替時に即時反映させるため、
        set_active_entries の後で明示的に ItemPanel のリスト再構築を呼ぶ。
        i338: SettingsPanel のパターン一覧も active ルーレット専用に切り替える。
        i422: DesignEditorDialog が開いていれば active ルーレットの項目数を反映する。
        """
        ctx = self._active_context
        entries = ctx.item_entries
        self._settings_panel.set_active_entries(entries)
        # i338: パターン表示を active ルーレットに合わせて切替
        if hasattr(self, "_settings_panel"):
            if ctx.item_patterns is not None:
                # non-default ルーレット: per-roulette パターン
                self._settings_panel.set_pattern_list(
                    list(ctx.item_patterns.keys()),
                    ctx.current_pattern or "デフォルト",
                )
            else:
                # default ルーレット: グローバル config のパターン
                self._settings_panel.set_pattern_list(
                    get_pattern_names(self._config),
                    get_current_pattern_name(self._config),
                )
        # ItemPanel のシンプルリストを即時更新
        if hasattr(self, "_item_panel"):
            self._item_panel._refresh_simple_list()
        # i363/i369: active ルーレットの個別設定を SettingsPanel 表示に反映する。
        #
        # i369 変更: 個別設定の読み出し元を「runtime オブジェクト」から「ctx.settings」に変更。
        #   - ctx.settings は _update_setting_by_action / _restore_per_panel_from_entry で
        #     常に最新値に保たれるため、active 切替時の信頼できる source-of-truth となる。
        #   - self._settings へ個別設定を逆書きしない（他ルーレットへの波及経路を断つ）。
        #   - SettingsPanel UI への反映だけを行う。
        #
        # update_setting は blockSignals を使うためシグナルの再入なし。
        if hasattr(self, "_settings_panel"):
            s = ctx.settings  # per-roulette 設定の source-of-truth
            _per_settings = {
                "spin_duration":        s.spin_duration,
                "spin_mode":            s.spin_mode,
                "double_duration":      s.double_duration,
                "triple_duration":      s.triple_duration,
                "sound_tick_enabled":   s.sound_tick_enabled,
                "sound_result_enabled": s.sound_result_enabled,
                "tick_pattern":         s.tick_pattern,
                "win_pattern":          s.win_pattern,
                "spin_direction":       s.spin_direction,
                "donut_hole":           s.donut_hole,
                "pointer_angle":        s.pointer_angle,
                "text_size_mode":       s.text_size_mode,
                "text_direction":       s.text_direction,
                "log_overlay_show":       s.log_overlay_show,
                "log_on_top":             s.log_on_top,
                "log_timestamp":          s.log_timestamp,
                "log_box_border":         s.log_box_border,
                "log_history_all_patterns": s.log_all_patterns,  # i395: active 切替時に UI 反映
                "result_close_mode":      s.result_close_mode,
                "result_hold_sec":        s.result_hold_sec,
            }
            for _k, _v in _per_settings.items():
                # i369: self._settings には書かない（global 側に個別設定を逆流させない）
                self._settings_panel.update_setting(_k, _v)
            # spin_preset_name は update_setting 未対応のため個別更新
            try:
                self._settings_panel._preset_combo.blockSignals(True)
                self._settings_panel._preset_combo.setCurrentText(s.spin_preset_name)
                self._settings_panel._preset_combo.blockSignals(False)
            except AttributeError:
                pass
        # i407: active ルーレットのホイールにログフィルタ用パターン（UUID）を反映する
        _pat_for_wheel = ctx.current_pattern or get_current_pattern_name(self._config)
        _pid_for_wheel = self._get_current_pattern_id(ctx)
        ctx.panel.wheel.set_current_pattern(_pat_for_wheel, _pid_for_wheel)
        # 行ウィジェット再構築後のマウストラッキング再適用
        if getattr(self, "_init_complete", False):
            self._refresh_panel_tracking()
            self._update_win_counts()
        # i351: active 切替時にリプレイ件数表示を active のものに更新する
        if hasattr(self, "_settings_panel") and getattr(self, "_init_complete", False):
            _sync_rp_mgr = self._active_replay_mgr
            self._settings_panel.set_replay_count(_sync_rp_mgr.count() if _sync_rp_mgr else 0)
        # i352: 管理ダイアログが開いていれば active に即時追従させる
        if getattr(self, "_init_complete", False):
            self._refresh_replay_dialog()
        # i422: デザインエディタが開いていれば active ルーレットの項目数を反映する
        if self._design_editor is not None:
            self._design_editor.set_item_count(len(entries))
