"""
settings_io_mixin.py — 設定 / ログ ファイルI/O Mixin

i446: main_window.py から分離。
責務:
  - ログアーカイブ復元 (_on_log_import)
  - 設定テンプレート export (_on_settings_export)
  - 設定テンプレート import (_on_settings_import)
  - import 補助: v1 形式 (_import_settings_template_v1)
  - import 補助: active への適用 (_import_per_roulette_to_active)
  - per-roulette 設定を ctx へ直接適用 (_apply_per_roulette_settings_to_ctx)

使用側:
  class MainWindow(SettingsIOMixin, LogShuffleMixin, MacroFlowMixin, ..., QMainWindow)
"""

import os

from per_roulette_settings import PER_ROULETTE_KEYS


class SettingsIOMixin:
    """設定テンプレートおよびログのファイルI/O操作の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  ログ import
    # ================================================================

    def _on_log_import(self):
        """ログアーカイブを同一 roulette へ復元する。

        i414: ログアーカイブは同一 roulette 専用。
        アーカイブ内の source_roulette_id が active roulette と一致する場合のみ取り込む。
        一致しない場合は取り込まずにメッセージを表示して終了する。
        cross-roulette merge（pid_remap 依存）はこの経路では行わない。
        """
        import json as _json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from config_utils import EXPORT_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "ログアーカイブを復元", EXPORT_DIR,
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return

        # i414: ファイルを読んで source_roulette_id を確認する
        try:
            with open(path, encoding="utf-8") as _f:
                _archive = _json.load(_f)
        except Exception:
            QMessageBox.warning(self, "インポート失敗",
                                "ログファイルの読み込みに失敗しました。\n"
                                "エクスポートで出力した JSON ファイルを指定してください。")
            return

        active_rid = self._manager.active_id
        if isinstance(_archive, dict):
            source_rid = _archive.get("source_roulette_id")
            if source_rid is None:
                # 旧形式フォールバック: records の roulette_id から推定
                _recs = _archive.get("records", [])
                _rids = {r.get("roulette_id", "default")
                         for r in _recs if isinstance(r, dict)}
                source_rid = next(iter(_rids)) if len(_rids) == 1 else None
        else:
            source_rid = None

        if source_rid is not None and source_rid != active_rid:
            QMessageBox.warning(self, "インポートできません",
                                "別のルーレットのログアーカイブです。\n"
                                "このアーカイブは取り込めません。\n\n"
                                "同じルーレットで作成したログアーカイブを選択してください。")
            return

        # i414: 同一 roulette の復元 — roulette_id 上書き・pid_remap 不要
        added = self._win_history.import_from_json(path)
        if added < 0:
            QMessageBox.warning(self, "インポート失敗",
                                "ログファイルの読み込みに失敗しました。\n"
                                "エクスポートで出力した JSON ファイルを指定してください。")
            return
        self._win_history.save()
        self._update_win_counts()
        # i415: WinHistory 更新後、ルーレットパネルのログ表示も即時再構築する。
        # WheelWidget._log_entries は WinHistory と独立した in-memory ストアのため、
        # import 後に明示的に再構築しないとパネル側が空のままになる。
        _wheel = self._active_panel.wheel
        _recent = [
            r for r in self._win_history.records
            if r.get("roulette_id", "default") == active_rid
        ]
        _recent.sort(key=lambda r: r.get("ts", ""), reverse=True)
        _wheel._log_entries = [
            (r.get("ts", ""), r.get("text", ""), r.get("pattern_id", ""))
            for r in _recent[:_wheel._log_max]
        ]
        _wheel.save_log(self._roulette_log_path(active_rid))
        _wheel.update()           # i416: wheel 本体の再描画をスケジュール（log_on_top=OFF の内部描画用）
        _wheel.log_changed.emit()  # i415: overlay 更新シグナル（log_on_top=ON 用）
        QMessageBox.information(self, "インポート完了",
                                f"{added} 件のログを復元しました。"
                                if added > 0
                                else "新規レコードはありませんでした（重複のためスキップ）。")

    # ================================================================
    #  設定テンプレート export / import (i356/i376)
    # ================================================================
    # export / import の意味: 単一ルーレットの設定テンプレート書き出し / 読み込み。
    # - export: 現在選択中ルーレットの個別設定（PER_ROULETTE_KEYS）をファイルへ書き出す。
    # - import: 現在選択中ルーレットを適用先とし、ファイル内設定を上書き適用する。
    #           ファイル内の source roulette id / active 情報で選択先を変えない。
    # 全体設定（音量・テーマ等）はこの export / import の対象外。

    def _on_settings_export(self):
        """現在選択中ルーレットの個別設定をテンプレートとしてエクスポートする。i356/i376

        i376: フォーマットを roulette_template_v1 に変更。
        対象は PER_ROULETTE_KEYS（20項目）のみ。全体設定は含まない。
        デフォルトパスは EXPORT_DIR（dist/ または EXE 配置フォルダ）。
        """
        import json
        import datetime
        from PySide6.QtWidgets import QFileDialog
        from config_utils import EXPORT_DIR

        ctx = self._active_context
        if ctx is None:
            return

        dt = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(EXPORT_DIR, f"roulette_template_{dt}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "設定テンプレートをエクスポート",
            default_path,
            "JSONファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return

        # active ルーレットの個別設定を ctx.settings から直接読む（実値保証）
        s = ctx.settings
        settings_data = {
            k: getattr(s, k)
            for k in PER_ROULETTE_KEYS
            if hasattr(s, k)
        }

        data = {
            "_format": "roulette_template_v1",
            "_exported_at": dt,
            "_source_roulette_id": self._manager.active_id or "",  # metadata のみ、import では使わない
            "settings": settings_data,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "エクスポートエラー", str(ex))

    def _on_settings_import(self):
        """設定テンプレートを現在選択中ルーレットへ適用する。i356/i358/i361/i376

        i376: 適用先は常に現在選択中ルーレット（active）。
        ファイル内の source roulette id で選択先は変えない。
        フォーマット検出:
          roulette_template_v1 → _import_settings_template_v1()
          旧フラット形式（i376以前の単一ルーレット export）→ PER_ROULETTE_KEYS のみ抽出して適用
          multi_v1（i375の誤った形式）→ エラーダイアログで拒否
        """
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from config_utils import EXPORT_DIR

        default_dir = EXPORT_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "設定テンプレートをインポート", default_dir,
            "JSONファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as ex:
            QMessageBox.warning(self, "インポートエラー", f"ファイルを読み込めませんでした:\n{ex}")
            return
        if not isinstance(data, dict):
            QMessageBox.warning(self, "インポートエラー",
                                "ファイル形式が正しくありません。\n"
                                "設定エクスポートで作成したJSONファイルを使用してください。")
            return

        fmt = data.get("_format", "")
        if fmt == "roulette_template_v1":
            self._import_settings_template_v1(data)
        elif fmt == "multi_v1":
            # i376: multi_v1（i375の全体保存形式）はこの UI では扱えない
            QMessageBox.warning(
                self, "インポートエラー",
                "このファイルは旧バージョンのワークスペース保存形式（multi_v1）です。\n"
                "現在の設定テンプレート形式では読み込めません。\n"
                "再度エクスポートしてください。"
            )
        else:
            # 旧フラット形式（i375以前のシングルルーレット export）との後方互換
            # PER_ROULETTE_KEYS のみ抽出して active ルーレットに適用する
            per_roulette = {k: data[k] for k in PER_ROULETTE_KEYS if k in data}
            if not per_roulette:
                QMessageBox.warning(self, "インポートエラー",
                                    "ファイルから適用できる設定が見つかりませんでした。\n"
                                    "設定エクスポートで作成したJSONファイルを使用してください。")
                return
            self._import_per_roulette_to_active(per_roulette)
            QMessageBox.information(
                self, "インポート完了",
                f"設定を読み込みました（{len(per_roulette)} 項目）。\n"
                f"※旧形式ファイルとして読み込みました。"
            )

    def _import_settings_template_v1(self, data: dict):
        """roulette_template_v1 形式を現在選択中ルーレットへ適用する。i376

        適用先は常に active ルーレット。source_roulette_id は使わない。
        """
        from PySide6.QtWidgets import QMessageBox

        per_roulette = data.get("settings", {})
        if not isinstance(per_roulette, dict) or not per_roulette:
            QMessageBox.warning(self, "インポートエラー",
                                "ファイル内に有効な設定データが見つかりませんでした。")
            return

        applied = self._import_per_roulette_to_active(per_roulette)
        QMessageBox.information(
            self, "インポート完了",
            f"設定を読み込みました（{applied} 項目適用）。"
        )

    def _import_per_roulette_to_active(self, per_roulette: dict) -> int:
        """per-roulette 設定を現在の active ルーレットへ適用し、SettingsPanel を同期する。i376

        適用先は常に active ルーレット。active 切替は行わない。
        """
        ctx = self._active_context
        if ctx is None:
            return 0
        applied = self._apply_per_roulette_settings_to_ctx(ctx, per_roulette)
        # active ルーレットの SettingsPanel 表示を同期（spin_preset_name の combo も含む）
        self._sync_settings_to_active()
        self._save_config()
        return applied

    def _apply_per_roulette_settings_to_ctx(self, ctx, per_roulette: dict) -> int:
        """per-roulette 設定を指定 ctx の ctx.settings と runtime に直接適用する。i375

        _apply_setting_to_all_panels と同等のロジックを任意の ctx に対して実行する。
        text_size_mode / text_direction の相互参照を正確にするため、
        パス 1 で全値を ctx.settings に書き込んでからパス 2 で runtime に反映する。

        Returns:
            適用した設定項目数
        """
        applied = 0
        p = ctx.panel

        # パス 1: ctx.settings を先に全更新（text_size_mode/text_direction 連動対策）
        for key in PER_ROULETTE_KEYS:
            if key not in per_roulette:
                continue
            try:
                setattr(ctx.settings, key, per_roulette[key])
                applied += 1
            except Exception:
                pass

        # パス 2: runtime に反映（_apply_setting_to_all_panels と同じロジック）
        for key in PER_ROULETTE_KEYS:
            if key not in per_roulette:
                continue
            value = per_roulette[key]
            try:
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
                    # ctx.settings.text_direction はパス 1 で更新済み
                    p.wheel.set_text_mode(value, ctx.settings.text_direction)
                elif key == "text_direction":
                    # ctx.settings.text_size_mode はパス 1 で更新済み
                    p.wheel.set_text_mode(ctx.settings.text_size_mode, value)
                elif key == "spin_preset_name":
                    p.spin_ctrl.set_spin_preset(value)
                elif key == "tick_pattern":
                    p.spin_ctrl.set_tick_pattern(value)
                elif key == "win_pattern":
                    p.spin_ctrl.set_win_pattern(value)
            except Exception:
                pass

        return applied
