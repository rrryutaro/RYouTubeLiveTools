"""
pattern_management_mixin.py — パターン管理 Mixin

i441: main_window.py から分離。
責務:
  - パターン切替 (_on_pattern_switched)
  - パターン追加 (_on_pattern_added)
  - パターン削除 (_on_pattern_deleted)
  - パターン名変更 (_on_pattern_renamed)
  - パターン export / import (_on_pattern_export, _on_pattern_import)

使用側:
  class MainWindow(PatternManagementMixin, ItemEntriesMixin, SettingsDispatchMixin,
                   SpinFlowMixin, RouletteLifecycleMixin, PanelGeometryMixin, QMainWindow)
"""

import json
import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from bridge import (
    build_segments_from_entries,
    get_current_pattern_name,
    get_pattern_names,
    load_all_item_entries,
    set_current_pattern,
    add_pattern,
    delete_pattern,
    rename_pattern,
    save_item_entries,
    ItemEntry,
)
from config_utils import EXPORT_DIR


class PatternManagementMixin:
    """パターン切替・追加・削除・改名・export/import の責務を持つ Mixin。

    MainWindow の self.* にアクセスする前提で設計されている。
    単独では動作しない。
    """

    # ------------------------------------------------------------------
    #  パターン切替
    # ------------------------------------------------------------------

    def _on_pattern_switched(self, name: str):
        """パターン切替: 項目を切り替えてホイールを更新する。"""
        # i340: 項目名編集中はパターン切替を拒否してコンボを元に戻す
        if hasattr(self, "_item_panel") and self._item_panel.is_item_name_editing():
            ctx = self._active_context
            if ctx.item_patterns is not None:
                old_name = ctx.current_pattern or "デフォルト"
            else:
                old_name = get_current_pattern_name(self._config)
            self._settings_panel.revert_pattern_to(old_name)
            return
        # 現在のパターンの項目を保存してから切替
        self._save_item_entries()
        ctx = self._active_context
        if ctx.item_patterns is not None:
            # i338: non-default ルーレット — per-roulette パターンで切替
            ctx.current_pattern = name
            raw_items = ctx.item_patterns.get(name, [])
            entries = [ItemEntry.from_config_entry(r, keep_disabled=True) for r in raw_items]
            entries = [e for e in entries if e is not None]
        else:
            set_current_pattern(self._config, name)
            entries = load_all_item_entries(self._config)
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i407: パターン切替時にホイールのログフィルタ対象（UUID）を更新する
        _sw_pid = self._get_pattern_id_for_ctx(ctx, name)
        ctx.current_pattern_id = _sw_pid
        ctx.panel.wheel.set_current_pattern(name, _sw_pid)
        # i339: ItemPanel シンプルリストをパターン切替後に即時更新する
        if hasattr(self, "_item_panel"):
            self._item_panel._refresh_simple_list()
        self._refresh_panel_tracking()
        self._update_win_counts()

    # ------------------------------------------------------------------
    #  パターン追加
    # ------------------------------------------------------------------

    def _on_pattern_added(self, name: str):
        """パターン追加: 空パターンを作成し、切り替える。"""
        # 現在のパターンの項目を保存
        self._save_item_entries()
        ctx = self._active_context
        if ctx.item_patterns is not None:
            # i338: non-default ルーレット — per-roulette パターン追加
            if name not in ctx.item_patterns:
                ctx.item_patterns[name] = []
            ctx.current_pattern = name
            # i407: 新パターンに UUID を割り当てる
            _add_pid = self._get_pattern_id_for_ctx(ctx, name)
            ctx.current_pattern_id = _add_pid
            entries = []
            self._settings_panel.set_pattern_list(list(ctx.item_patterns.keys()), name)
        else:
            add_pattern(self._config, name)
            set_current_pattern(self._config, name)
            entries = []
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i339: ItemPanel シンプルリストをパターン追加後に即時更新する
        if hasattr(self, "_item_panel"):
            self._item_panel._refresh_simple_list()
        self._refresh_panel_tracking()

    # ------------------------------------------------------------------
    #  パターン削除
    # ------------------------------------------------------------------

    def _on_pattern_deleted(self, name: str):
        """パターン削除: 削除後に残りの先頭パターンに切り替える。"""
        # 現在のパターンを保存してから削除
        self._save_item_entries()
        ctx = self._active_context
        if ctx.item_patterns is not None:
            # i338: non-default ルーレット — per-roulette パターン削除
            if name in ctx.item_patterns and len(ctx.item_patterns) > 1:
                del ctx.item_patterns[name]
                ctx.pattern_id_map.pop(name, None)  # i407: UUID も削除
            # SettingsPanel は既に新 current を選択済み
            new_current = self._settings_panel._current_pattern
            if new_current not in ctx.item_patterns:
                new_current = next(iter(ctx.item_patterns))
            ctx.current_pattern = new_current
            ctx.current_pattern_id = ctx.pattern_id_map.get(new_current, "")
            raw_items = ctx.item_patterns.get(new_current, [])
            entries = [ItemEntry.from_config_entry(r, keep_disabled=True) for r in raw_items]
            entries = [e for e in entries if e is not None]
            self._settings_panel.set_pattern_list(list(ctx.item_patterns.keys()), new_current)
        else:
            delete_pattern(self._config, name)
            new_current = get_current_pattern_name(self._config)
            entries = load_all_item_entries(self._config)
            self._settings_panel.set_pattern_list(get_pattern_names(self._config), new_current)
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i339: ItemPanel シンプルリストをパターン削除後に即時更新する
        if hasattr(self, "_item_panel"):
            self._item_panel._refresh_simple_list()
        self._refresh_panel_tracking()

    # ------------------------------------------------------------------
    #  パターン名変更
    # ------------------------------------------------------------------

    def _on_pattern_renamed(self, old_name: str, new_name: str):
        """パターン名変更: データ層のキーをリネームしてホイール表示を更新する。

        i407: pattern_id（UUID）は変わらない。表示名だけを更新する。
        rename_log_pattern は不要になった（ログはIDベースのため名前変更の影響なし）。
        """
        # i400: SettingsPanel 側は既に UI を更新済み。データ層だけ追随する。
        ctx = self._active_context
        if ctx.item_patterns is not None:
            # non-default ルーレット — per-roulette パターンをリネーム
            ctx.item_patterns = {
                (new_name if k == old_name else k): v
                for k, v in ctx.item_patterns.items()
            }
            # i407: pattern_id_map のキーも更新（UUID は維持）
            if old_name in ctx.pattern_id_map:
                ctx.pattern_id_map[new_name] = ctx.pattern_id_map.pop(old_name)
            if ctx.current_pattern == old_name:
                ctx.current_pattern = new_name
            self._settings_panel.set_pattern_list(
                list(ctx.item_patterns.keys()), ctx.current_pattern
            )
        else:
            rename_pattern(self._config, old_name, new_name)
            self._settings_panel.set_pattern_list(
                get_pattern_names(self._config),
                get_current_pattern_name(self._config),
            )
        # i407: UUID ベースなのでログエントリの更新は不要。
        # ログフィルタ対象のパターン名を更新する（UUID は変わらないので current_pattern_id はそのまま）
        ctx.panel.wheel.set_current_pattern(new_name, ctx.current_pattern_id)
        self._update_win_counts()

    # ------------------------------------------------------------------
    #  パターン export / import
    # ------------------------------------------------------------------

    def _on_pattern_export(self):
        """現在のパターンをJSONファイルにエクスポートする。"""
        ctx = self._active_context
        # i410: non-default ルーレットは ctx.current_pattern を使う
        if ctx.item_patterns is not None:
            pattern_name = ctx.current_pattern or "デフォルト"
        else:
            pattern_name = get_current_pattern_name(self._config)
        entries = [e.to_dict() for e in ctx.item_entries]
        if not entries:
            return
        default_name = f"{pattern_name}.json"
        # i408: 既定フォルダを EXPORT_DIR に統一
        default_path = os.path.join(EXPORT_DIR, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "パターンをエクスポート", default_path,
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return
        # i411: pattern_id を export に含めて識別情報を保持する
        pattern_id = self._get_pattern_id_for_ctx(ctx, pattern_name)
        data = {
            "pattern_name": pattern_name,
            "pattern_id": pattern_id,
            "entries": entries,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _on_pattern_import(self):
        """JSONファイルからパターンをインポートする。"""
        # i408: 既定フォルダを EXPORT_DIR に統一
        path, _ = QFileDialog.getOpenFileName(
            self, "パターンをインポート", EXPORT_DIR,
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return
        # ファイル読み込み
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.warning(self, "インポートエラー",
                                f"ファイルを読み込めませんでした。\n{e}")
            return
        # バリデーション: トップレベル構造
        if not isinstance(data, dict):
            QMessageBox.warning(self, "インポートエラー",
                                "不正な形式です。JSON オブジェクトが必要です。")
            return
        pattern_name = data.get("pattern_name")
        entries_raw = data.get("entries")
        # i412: source 側 pattern_id を読み取る（log import 時の再マップに使用）
        source_pattern_id = data.get("pattern_id", "")
        if not isinstance(pattern_name, str) or not pattern_name.strip():
            QMessageBox.warning(self, "インポートエラー",
                                "pattern_name が見つからないか不正です。")
            return
        if not isinstance(entries_raw, list):
            QMessageBox.warning(self, "インポートエラー",
                                "entries が見つからないか不正です。")
            return
        # バリデーション: 各エントリ
        for i, entry in enumerate(entries_raw):
            if not isinstance(entry, dict):
                QMessageBox.warning(self, "インポートエラー",
                                    f"entries[{i}] が不正な形式です。")
                return
            if "text" not in entry:
                QMessageBox.warning(self, "インポートエラー",
                                    f"entries[{i}] に text キーがありません。")
                return
        # 同名パターン衝突時: 連番付き別名で追加
        pattern_name = pattern_name.strip()
        # i410: non-default ルーレットは ctx.item_patterns を使う
        ctx = self._active_context
        if ctx.item_patterns is not None:
            existing = list(ctx.item_patterns.keys())
        else:
            existing = get_pattern_names(self._config)
        final_name = pattern_name
        if final_name in existing:
            suffix = 1
            while f"{pattern_name}_{suffix}" in existing:
                suffix += 1
            final_name = f"{pattern_name}_{suffix}"
        # 現在のパターンを保存してからインポート
        self._save_item_entries()
        # ItemEntry に変換
        imported_entries = []
        for raw in entries_raw:
            item = ItemEntry.from_config_entry(raw, keep_disabled=True)
            if item is not None:
                imported_entries.append(item)
        # i410: パターン追加 + エントリ書き込み + current 切替 をルーレット種別で分岐
        if ctx.item_patterns is not None:
            # non-default ルーレット: in-memory パターンに書き込む
            ctx.item_patterns[final_name] = [e.to_dict() for e in imported_entries]
            ctx.current_pattern = final_name
            _pid = self._get_pattern_id_for_ctx(ctx, final_name)
            ctx.current_pattern_id = _pid
            ctx.panel.wheel.set_current_pattern(final_name, _pid)
            self._settings_panel.set_pattern_list(list(ctx.item_patterns.keys()), final_name)
        else:
            # default ルーレット: グローバル config に書き込む
            add_pattern(self._config, final_name)
            save_item_entries(self._config, imported_entries, pattern_name=final_name)
            set_current_pattern(self._config, final_name)
            _pid = self._get_current_pattern_id(ctx)
            ctx.panel.wheel.set_current_pattern(final_name, _pid)
            self._settings_panel.set_pattern_list(get_pattern_names(self._config), final_name)
        # i412: source_pattern_id → dest _pid のマッピングを保存（log import 時の再マップ用）
        # 同一 source pattern を複数回 import した場合は「最後の import」が有効になる
        if source_pattern_id:
            ctx.imported_pattern_id_map[source_pattern_id] = _pid
        ctx.item_entries = imported_entries
        ctx.segments, _ = build_segments_from_entries(imported_entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(imported_entries)
        if hasattr(self, "_item_panel"):
            self._item_panel._refresh_simple_list()
        self._refresh_panel_tracking()
        self._update_win_counts()
