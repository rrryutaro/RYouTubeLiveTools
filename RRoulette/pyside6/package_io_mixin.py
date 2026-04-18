"""
package_io_mixin.py — ルーレット package I/O Mixin

i447: main_window.py から分離。
責務:
  - ルーレット package エクスポート (_on_roulette_pkg_export)
  - ルーレット package インポート (_on_roulette_pkg_import)

使用側:
  class MainWindow(PackageIOMixin, SettingsIOMixin, LogShuffleMixin, ..., QMainWindow)
"""

import os

from bridge import (
    build_segments_from_entries,
    get_pattern_names, get_pattern_id,
    ItemEntry,
)
from per_roulette_settings import PER_ROULETTE_KEYS


class PackageIOMixin:
    """ルーレット package の export / import 操作の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ================================================================
    #  ルーレット package export / import (i418)
    # ================================================================
    # 責務:
    #   export: active roulette を自己完結した package ファイルとして書き出す。
    #           roulette 固有設定・pattern 群・ログを含む。AppConfig は含まない。
    #   import: package ファイルから「新しいルーレット」として追加する。
    #           既存 roulette には merge しない。新 roulette_id を採番する。

    def _on_roulette_pkg_export(self):
        """active roulette を roulette package ファイルにエクスポートする。i418

        含める: roulette 固有設定, pattern 群, current_pattern, logs,
                source metadata (roulette_name / roulette_id)
        含めない: AppConfig, メインウィンドウ位置, 共通パネル状態,
                  active roulette 選択状態, 他 roulette データ, ローカル絶対パス
        """
        import json
        import datetime
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from config_utils import EXPORT_DIR

        ctx = self._active_context
        if ctx is None:
            return

        # i419: export 前に現在の item_entries を item_patterns へフラッシュする。
        # non-default ルーレットは ctx.item_patterns[current_pattern] が
        # item_entries と乖離している場合があるため、同期してから収集する。
        self._save_item_entries()

        rid = ctx.roulette_id

        # --- roulette 表示名を決定 ---
        if rid == "default":
            roulette_name = "ルーレット 1"
        elif rid.startswith("roulette_"):
            try:
                n = int(rid[len("roulette_"):])
                roulette_name = f"ルーレット {n}"
            except ValueError:
                roulette_name = rid
        else:
            roulette_name = rid

        # --- patterns 収集 ---
        if ctx.item_patterns is not None:
            # non-default ルーレット: per-roulette の item_patterns を使う
            patterns_data = []
            for pname, raw_entries in ctx.item_patterns.items():
                pid = ctx.pattern_id_map.get(pname, "")
                patterns_data.append({
                    "pattern_name": pname,
                    "pattern_id": pid,
                    "entries": list(raw_entries),
                })
            current_pattern_id = ctx.current_pattern_id or ""
        else:
            # default ルーレット: グローバル config から収集
            patterns_data = []
            for pname in get_pattern_names(self._config):
                pid = get_pattern_id(self._config, pname)
                raw_entries = self._config.get("item_patterns", {}).get(pname, [])
                patterns_data.append({
                    "pattern_name": pname,
                    "pattern_id": pid,
                    "entries": list(raw_entries),
                })
            current_pattern_id = self._get_current_pattern_id(ctx)

        # --- per-roulette 設定収集 ---
        s = ctx.settings
        settings_data = {k: getattr(s, k) for k in PER_ROULETTE_KEYS if hasattr(s, k)}

        # --- logs 収集 (このルーレット分のみ) ---
        log_records = [
            r for r in self._win_history.records
            if r.get("roulette_id", "default") == rid
        ]

        # --- package 構築 ---
        dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        package = {
            "version": 1,
            "package_type": "roulette_package",
            "exported_at": dt,
            "source": {
                "roulette_id": rid,
                "roulette_name": roulette_name,
            },
            "roulette": {
                "name": roulette_name,
                "settings": settings_data,
                "patterns": patterns_data,
                "current_pattern_id": current_pattern_id,
            },
            "history": {
                "records": log_records,
            },
        }

        # --- ファイル保存 ---
        dt_file = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join(EXPORT_DIR, f"roulette_package_{dt_file}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "ルーレット package をエクスポート",
            default_path,
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(package, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            QMessageBox.warning(self, "エクスポートエラー", str(ex))

    def _on_roulette_pkg_import(self):
        """roulette package ファイルを新しいルーレットとして追加する。i418

        既存 roulette には merge しない。
        import 時に新しい roulette_id を採番し、
        package 内の pattern / settings / logs を新 roulette として復元する。
        """
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from config_utils import EXPORT_DIR

        path, _ = QFileDialog.getOpenFileName(
            self, "ルーレット package をインポート", EXPORT_DIR,
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return

        try:
            with open(path, encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception as ex:
            QMessageBox.warning(self, "インポートエラー",
                                f"ファイルを読み込めませんでした:\n{ex}")
            return

        if not isinstance(pkg, dict):
            QMessageBox.warning(self, "インポートエラー",
                                "ファイル形式が正しくありません。\n"
                                "roulette package エクスポートで作成したファイルを使用してください。")
            return

        if pkg.get("package_type") != "roulette_package":
            QMessageBox.warning(self, "インポートエラー",
                                "このファイルは roulette package ではありません。\n"
                                f"(package_type: {pkg.get('package_type', '不明')})\n\n"
                                "ルーレット package エクスポートで作成したファイルを指定してください。")
            return

        roulette_data = pkg.get("roulette", {})
        patterns_raw = roulette_data.get("patterns", [])
        settings_raw = roulette_data.get("settings", {})
        current_pattern_id_pkg = roulette_data.get("current_pattern_id", "")
        history_raw = pkg.get("history", {})
        log_records = history_raw.get("records", [])
        source_name = pkg.get("source", {}).get("roulette_name", "インポート")

        if not patterns_raw:
            QMessageBox.warning(self, "インポートエラー",
                                "package にパターン情報が含まれていません。\n"
                                "正しい roulette package ファイルを指定してください。")
            return

        # --- 新しい roulette_id を採番 ---
        new_rid = self._next_roulette_id()

        # --- 同名ルーレットの命名: roulette_id 連番採番のみのため競合なし ---

        # --- 新規ルーレットを生成 ---
        panel = self._add_roulette(new_rid, activate=False)
        if panel is None:
            QMessageBox.warning(self, "インポートエラー",
                                "ルーレットの生成に失敗しました。")
            return

        ctx = self._manager.get(new_rid)
        if ctx is None:
            return

        # --- patterns を復元 ---
        new_item_patterns: dict = {}
        new_pattern_id_map: dict = {}
        current_pattern_name: str | None = None

        for p in patterns_raw:
            if not isinstance(p, dict):
                continue
            pname = p.get("pattern_name", "")
            pid = p.get("pattern_id", "")
            entries = p.get("entries", [])
            if not pname:
                continue
            new_item_patterns[pname] = list(entries)
            if pid:
                new_pattern_id_map[pname] = pid
            # current_pattern_id でパターン名を特定
            if pid and pid == current_pattern_id_pkg:
                current_pattern_name = pname

        # current_pattern が特定できなかった場合は先頭を使う
        if current_pattern_name is None and new_item_patterns:
            current_pattern_name = next(iter(new_item_patterns))

        current_pid = new_pattern_id_map.get(current_pattern_name or "", "")

        # --- ctx に patterns を設定 ---
        ctx.item_patterns = new_item_patterns
        ctx.pattern_id_map = new_pattern_id_map
        ctx.current_pattern = current_pattern_name
        ctx.current_pattern_id = current_pid

        # --- 現在パターンの item_entries を構築 ---
        raw_entries = new_item_patterns.get(current_pattern_name or "", [])
        new_entries = []
        for raw in raw_entries:
            entry = ItemEntry.from_config_entry(raw, keep_disabled=True)
            if entry is not None:
                new_entries.append(entry)

        ctx.item_entries = new_entries
        ctx.segments, _ = build_segments_from_entries(new_entries, self._config)
        ctx.panel.set_segments(ctx.segments)

        # current_pattern をパネルのホイールに反映
        if current_pattern_name and current_pid:
            ctx.panel.wheel.set_current_pattern(current_pattern_name, current_pid)

        # --- per-roulette 設定を復元 ---
        if settings_raw:
            self._apply_per_roulette_settings_to_ctx(ctx, settings_raw)

        # --- logs を復元 (新 roulette_id に書き換えてマージ) ---
        added = self._win_history.import_from_records(log_records,
                                                       target_roulette_id=new_rid)
        if added > 0:
            self._win_history.save()
        # i420: import_from_records の戻り値は dedup で 0 になる場合があるため、
        # win_history から実際のレコード件数を集計して報告に使う。
        # （同一 roulette_id が再利用された場合のデータが既に保存ファイルに残っている場合など）
        _actual_log_count = sum(
            1 for r in self._win_history.records
            if r.get("roulette_id", "default") == new_rid
        )

        # --- wheel のインメモリログを再構築 ---
        _wheel = ctx.panel.wheel
        _recent = [
            r for r in self._win_history.records
            if r.get("roulette_id", "default") == new_rid
        ]
        _recent.sort(key=lambda r: r.get("ts", ""), reverse=True)
        _wheel._log_entries = [
            (r.get("ts", ""), r.get("text", ""), r.get("pattern_id", ""))
            for r in _recent[:_wheel._log_max]
        ]
        _wheel.save_log(self._roulette_log_path(new_rid))
        _wheel.update()
        _wheel.log_changed.emit()

        # --- active roulette を新 roulette に切り替え ---
        self._set_active_roulette(new_rid)
        self._sync_settings_to_active()

        QMessageBox.information(
            self, "インポート完了",
            f"ルーレット package をインポートしました。\n\n"
            f"ソース: {source_name}\n"
            f"パターン数: {len(new_item_patterns)}\n"
            f"ログ件数: {_actual_log_count}"
        )
