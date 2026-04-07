"""
RRoulette — 履歴管理 Mixin
  - _record_result: スピン結果を履歴に追記（常に日時を保持）
  - _make_log_record: 完全なレコード dict を生成する（自動保存・詳細出力共通）
  - _export_log_simple: シンプルリスト形式（テキスト）でログ出力
  - _export_log_detailed: グループ名・項目構成付き詳細形式（JSON）でログ出力
  - _do_export_log: ファイル保存ダイアログ経由でエクスポート

  self._log_timestamp (bool): True=日時を「結果のみ出力」に含める / False=含めない
  注意: 詳細ログ（JSON）は _log_timestamp 設定に関係なく、常に全フィールドを保持する。
"""

import datetime
import json
import tkinter.filedialog as _filedialog
import tkinter.messagebox as _msgbox

from config_utils import EXPORT_DIR, AUTO_LOG_FILE
from constants import VERSION


def _make_entries_snapshot(item_entries: list) -> list | None:
    """item_entries のデフォルト差分スナップショットを生成する。
    デフォルト値（enabled=True, prob_mode=null, prob_value=null, split_count=1）と
    同じ項目・フィールドは省略し、変更がある項目だけを index ベースで出力する。
    全項目がデフォルトなら None を返す（出力自体を省略できる）。
    """
    result = []
    for i, e in enumerate(item_entries):
        diff: dict = {"index": i}
        if not e.get("enabled", True):
            diff["enabled"] = False
        if e.get("prob_mode") is not None:
            diff["prob_mode"] = e["prob_mode"]
            if e.get("prob_value") is not None:
                diff["prob_value"] = e["prob_value"]
        if (e.get("split_count") or 1) != 1:
            diff["split_count"] = e["split_count"]
        if len(diff) > 1:   # "index" 以外に変更あり
            result.append(diff)
    return result if result else None


class HistoryManagerMixin:

    # ════════════════════════════════════════════════════════════════
    #  結果記録
    # ════════════════════════════════════════════════════════════════
    def _record_result(self, winner: str):
        """スピン結果を履歴リストに追記する。
        日時は常にメモリ上に保持し、出力時に _log_timestamp で制御する。
        items は項目リストUI順の本体テキストリスト（セグメント列ではない）。
        """
        entry = {
            "timestamp":   datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result":      winner,
            "group":       self._current_pattern,
            "items":       [e["text"] for e in self._item_entries],
            "app_version": VERSION,
            "item_entries_snapshot": _make_entries_snapshot(self._item_entries),
        }
        self._history.append(entry)

    # ════════════════════════════════════════════════════════════════
    #  レコード生成（共通）
    # ════════════════════════════════════════════════════════════════
    def _make_log_record(self, e: dict) -> dict:
        """ログエントリから完全なレコード dict を生成する。
        自動保存ログと詳細ログ出力で共通利用し、フィールド定義を一元管理する。
        app_version を先頭に置くことで人がテキストで読みやすくする。
        item_entries_snapshot は差分が存在する場合のみ含める。
        """
        record = {
            "app_version": e.get("app_version"),
            "timestamp":   e["timestamp"],
            "result":      e["result"],
            "group":       e["group"],
            "items":       e["items"],
        }
        snap = e.get("item_entries_snapshot")
        if snap is not None:
            record["item_entries_snapshot"] = snap
        return record

    # ════════════════════════════════════════════════════════════════
    #  ログ出力
    # ════════════════════════════════════════════════════════════════
    def _export_log_simple(self, path: str):
        """結果のみのシンプルリストをテキストファイルに書き出す。

        _log_timestamp=True:
            2026-03-29 12:34:56  項目A
            2026-03-29 12:35:10  項目C

        _log_timestamp=False:
            項目A
            項目C
        """
        if self._log_timestamp:
            lines = [f"{e['timestamp']}  {e['result']}" for e in self._history]
        else:
            lines = [e["result"] for e in self._history]

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            if lines:
                f.write("\n")

    def _export_log_detailed(self, path: str):
        """グループ名・項目構成付き詳細ログをJSON形式で書き出す。

        _log_timestamp 設定に関係なく、常に全フィールドを保持する。
        （_log_timestamp は「結果のみ出力」の簡易テキスト形式にのみ影響する）

        出力形式:
        {
          "exported_at": "2026-03-29 12:40:00",
          "results": [
            {
              "timestamp": "2026-03-29 12:34:56",
              "result": "項目A",
              "group": "デフォルト",
              "items": ["項目A", "項目B", "項目C"],
              "app_version": "0.4.4",
              "item_entries_snapshot": [...]
            },
            ...
          ]
        }
        """
        data = {
            "exported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "results": [self._make_log_record(e) for e in self._history],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ════════════════════════════════════════════════════════════════
    #  自動保存 / 自動読み込み
    # ════════════════════════════════════════════════════════════════
    def _auto_save_log(self):
        """終了時にログを固定ファイルへ自動保存する。
        _make_log_record で詳細ログ出力と同一のレコード構造を使用する。
        """
        data = {
            "exported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "results": [self._make_log_record(e) for e in self._history],
        }
        try:
            with open(AUTO_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _auto_load_log(self):
        """起動時に前回の自動保存ログを読み込む。"""
        try:
            with open(AUTO_LOG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("results", []):
                self._history.append({
                    "timestamp":   entry.get("timestamp", ""),
                    "result":      entry.get("result", ""),
                    "group":       entry.get("group", ""),
                    "items":       entry.get("items", []),
                    "app_version": entry.get("app_version", None),
                    "item_entries_snapshot": entry.get("item_entries_snapshot", None),
                })
        except Exception:
            pass

    def _clear_log(self):
        """ログを全件削除する。"""
        if not self._history:
            _msgbox.showinfo("ログ削除", "削除するログがありません。", parent=self.root)
            return
        if not _msgbox.askyesno(
            "ログ削除",
            f"ログ {len(self._history)} 件をすべて削除します。\nよろしいですか？",
            parent=self.root,
        ):
            return
        self._history.clear()
        self._redraw()

    def _do_export_log(self, fmt: str):
        """ファイル保存ダイアログを開いてログを出力する。

        Args:
            fmt: "simple"（テキスト）または "detailed"（JSON）
        """
        if not self._history:
            _msgbox.showinfo("ログ出力", "まだ結果が記録されていません。", parent=self.root)
            return

        dt = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "simple":
            initial = f"roulette_log_simple_{dt}.txt"
            filetypes = [("テキストファイル", "*.txt"), ("すべてのファイル", "*.*")]
            defext = ".txt"
        else:
            initial = f"roulette_log_detailed_{dt}.json"
            filetypes = [("JSONファイル", "*.json"), ("すべてのファイル", "*.*")]
            defext = ".json"

        path = _filedialog.asksaveasfilename(
            parent=self.root,
            title="ログを保存",
            initialdir=EXPORT_DIR,
            initialfile=initial,
            defaultextension=defext,
            filetypes=filetypes,
        )
        if not path:
            return

        try:
            if fmt == "simple":
                self._export_log_simple(path)
            else:
                self._export_log_detailed(path)
            _msgbox.showinfo("ログ出力", f"保存しました:\n{path}", parent=self.root)
        except Exception as ex:
            _msgbox.showerror("ログ出力エラー", str(ex), parent=self.root)
