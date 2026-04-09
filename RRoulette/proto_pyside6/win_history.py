"""
PySide6 プロトタイプ — 勝利数集計用の完全履歴管理

WheelWidget._log_entries（表示用簡易ログ、最新8件）とは別に、
勝利数の正確な集計に必要な全件履歴を管理する。

責務:
  - スピン結果の全件記録（テキスト・時刻・パターン名）
  - パターン別の項目勝利数集計
  - 履歴の保存・復元（JSON ファイル）
  - 履歴クリア
"""

import json
import os
from datetime import datetime


class WinHistory:
    """勝利数集計用の完全履歴。

    各レコード: {"text": str, "ts": str, "pattern": str}
    全件保持し、パターン別に集計可能。
    """

    def __init__(self, save_path: str = ""):
        self._records: list[dict] = []
        self._save_path = save_path

    def record(self, winner_text: str, pattern_name: str):
        """スピン結果を記録する。"""
        self._records.append({
            "text": winner_text,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pattern": pattern_name,
        })

    def count_by_item(self, pattern_name: str) -> dict[str, int]:
        """指定パターンの項目別勝利数を返す。

        Returns:
            {項目テキスト: 当選回数} の辞書
        """
        counts: dict[str, int] = {}
        for rec in self._records:
            if rec["pattern"] == pattern_name:
                name = rec["text"]
                counts[name] = counts.get(name, 0) + 1
        return counts

    def total_count(self, pattern_name: str) -> int:
        """指定パターンの合計スピン回数を返す。"""
        return sum(1 for r in self._records if r["pattern"] == pattern_name)

    def clear(self):
        """全履歴をクリアする。"""
        self._records.clear()

    def save(self):
        """履歴をファイルに保存する。"""
        if not self._save_path:
            return
        try:
            data = {"records": self._records}
            with open(self._save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load(self):
        """履歴をファイルから復元する。"""
        if not self._save_path or not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("records", [])
            self._records = [
                {
                    "text": r.get("text", ""),
                    "ts": r.get("ts", ""),
                    "pattern": r.get("pattern", ""),
                }
                for r in records
                if isinstance(r, dict) and r.get("text")
            ]
        except Exception:
            pass

    @property
    def records(self) -> list[dict]:
        """全レコードのコピーを返す。"""
        return list(self._records)
