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
import uuid
from datetime import datetime


class WinHistory:
    """勝利数集計用の完全履歴。

    各レコード: {
        "id": str,          # レコード固有UUID（重複判定用）
        "text": str,        # 当選テキスト
        "ts": str,          # タイムスタンプ
        "pattern_id": str,  # i407: パターン不変UUID（フィルタ基準）
        "pattern": str,     # i407: パターン表示名（参照用・変更されても無害）
        "roulette_id": str, # ルーレットID
    }
    全件保持し、pattern_id 別に集計可能。
    id フィールドは UUID で、export/import の重複判定に使う。
    """

    def __init__(self, save_path: str = ""):
        self._records: list[dict] = []
        self._save_path = save_path

    def record(self, winner_text: str, pattern_id: str,
               roulette_id: str = "default", pattern_name: str = ""):
        """スピン結果を記録する。

        i407: pattern_id（UUID）を基準として記録する。
        pattern_name は表示参照用として保持するが、フィルタには使わない。

        Args:
            winner_text: 当選テキスト
            pattern_id: パターンの不変UUID
            roulette_id: ルーレットID
            pattern_name: パターン表示名（参照用、省略可）
        """
        self._records.append({
            "id": str(uuid.uuid4()),
            "text": winner_text,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pattern_id": pattern_id,
            "pattern": pattern_name,
            "roulette_id": roulette_id,
        })

    def count_by_item(self, pattern_id: str,
                      roulette_id: str | None = None) -> dict[str, int]:
        """指定パターン（UUID）の項目別勝利数を返す。

        i407: フィルタは pattern_id（UUID）基準。
        - pattern_id が空の場合は空辞書を返す（曖昧データ混入防止）。
        - roulette_id が空文字列の場合は空辞書を返す（未確定IDは除外）。
        - roulette_id=None は全ルーレット集計（フィルタなし）として使える。

        Args:
            pattern_id: パターンの不変UUID（空文字列は不可）
            roulette_id: ルーレットID。None = 全ルーレット。空文字は除外。

        Returns:
            {項目テキスト: 当選回数} の辞書
        """
        if not pattern_id:
            # i407: 空 pattern_id は曖昧データ混入防止のため返さない
            return {}
        if roulette_id is not None and not roulette_id:
            return {}
        counts: dict[str, int] = {}
        for rec in self._records:
            if rec.get("pattern_id", "") != pattern_id:
                continue
            if roulette_id is not None:
                if rec.get("roulette_id", "default") != roulette_id:
                    continue
            name = rec["text"]
            counts[name] = counts.get(name, 0) + 1
        return counts

    def total_count(self, pattern_id: str,
                    roulette_id: str | None = None) -> int:
        """指定パターン（UUID）の合計スピン回数を返す。

        i407: count_by_item と同じ pattern_id ベースのガードを適用する。
        """
        if not pattern_id:
            return 0
        if roulette_id is not None and not roulette_id:
            return 0
        count = 0
        for r in self._records:
            if r.get("pattern_id", "") != pattern_id:
                continue
            if roulette_id is not None:
                if r.get("roulette_id", "default") != roulette_id:
                    continue
            count += 1
        return count

    def clear(self, roulette_id: str | None = None):
        """履歴をクリアする。

        Args:
            roulette_id: 指定した場合は該当ルーレットの履歴のみ削除する。
                         None（デフォルト）の場合は全件削除。
                         roulette_id を持たない旧レコードは "default" 扱い。
        """
        if roulette_id is None:
            self._records.clear()
        else:
            self._records = [
                r for r in self._records
                if r.get("roulette_id", "default") != roulette_id
            ]

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
        """履歴をファイルから復元する。

        i407: 保存データ正規化ポリシー
        - pattern_id が存在しないレコードは旧フォーマットとして除外する（安全側初期化）。
          旧フォーマット（pattern キーのみ）は pattern_id との一致が取れないため除外し、
          クリーンな状態から再スタートする。
        - text が空のレコードは除外する（表示できないため）。
        - id が欠如 → "" として保持（import_from_json で複合キーにフォールバック）。
        - roulette_id が欠如 → "default" に正規化（旧形式互換）。
        """
        if not self._save_path or not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("records", [])
            loaded = []
            for r in records:
                if not isinstance(r, dict) or not r.get("text"):
                    continue
                pid = r.get("pattern_id", "")
                if not pid:
                    # i407: pattern_id なし = 旧フォーマット → 安全側で除外
                    continue
                loaded.append({
                    "id": r.get("id", ""),
                    "text": r.get("text", ""),
                    "ts": r.get("ts", ""),
                    "pattern_id": pid,
                    "pattern": r.get("pattern", ""),
                    "roulette_id": r.get("roulette_id", "default"),
                })
            self._records = loaded
        except Exception:
            pass

    def export_to_json(self, path: str,
                       pattern_id: str | None = None,
                       roulette_id: str | None = None):
        """履歴を JSON ファイルへエクスポートする。

        i407: フィルタは pattern_id（UUID）基準。

        Args:
            path: 保存先ファイルパス
            pattern_id: 指定時はその pattern_id のみ書き出す。None = 全パターン。
            roulette_id: 指定時はそのルーレットのみ書き出す。None = 全ルーレット。
        """
        records = self._records
        if pattern_id is not None:
            records = [r for r in records if r.get("pattern_id", "") == pattern_id]
        if roulette_id is not None:
            records = [r for r in records
                       if r.get("roulette_id", "default") == roulette_id]
        # i414: source_roulette_id をヘッダに含める（同一 roulette 専用の import チェック用）
        data = {"version": 2, "source_roulette_id": roulette_id,
                "records": list(records)}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_from_json(self, path: str,
                         target_roulette_id: str | None = None,
                         pid_remap: dict | None = None) -> int:
        """JSON ファイルから履歴を取り込む（追記・重複除外マージ）。

        i407: pattern_id がないレコードは旧フォーマットとして除外する。
        id フィールドがあるレコードは id で重複判定する。
        id がないレコードは (ts, text, pattern_id, roulette_id) の複合キーで判定する。

        i408: target_roulette_id を指定すると、取り込み対象の全レコードの
        roulette_id をその値で上書きする。
        これにより #1 から export したログを #2 に import する際に
        元の roulette_id が混入するのを防ぐ。

        i412: pid_remap を指定すると、source 側 pattern_id を destination 側の
        pattern_id へ変換してから保存する。
        {source_pattern_id: dest_pattern_id} の辞書。
        これにより #1 pattern import → #1 log import した際に、
        destination 側の表示フィルタと pattern_id が一致するようになる。

        Args:
            path: インポートするファイルパス
            target_roulette_id: 上書きするルーレットID。None = 元の roulette_id を保持。
            pid_remap: {source_pid: dest_pid} の変換マップ。None = 変換なし。

        Returns:
            追加されたレコード数
        """
        if not os.path.exists(path):
            return -1
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return -1

        # version 2 形式 or {"records": [...]} 形式に対応
        if isinstance(data, dict):
            incoming = data.get("records", [])
        elif isinstance(data, list):
            incoming = data
        else:
            return -1

        # 既存レコードのキーセットを構築（重複判定用）
        # i411: target_roulette_id 指定時は対象 roulette のレコードのみで判定する。
        # 他 roulette の既存レコードが同じ id を持っていても import をブロックしない。
        # （#1 export → #2 import 時に #1 側の既存 id が誤衝突するのを防ぐ）
        _dedup_base = (
            [r for r in self._records
             if r.get("roulette_id", "default") == target_roulette_id]
            if target_roulette_id is not None
            else self._records
        )
        existing_keys: set = {
            ("id", r["id"]) if r.get("id") else
            ("c", r.get("ts", ""), r.get("text", ""),
             r.get("pattern_id", ""), r.get("roulette_id", "default"))
            for r in _dedup_base
        }

        added = 0
        for r in incoming:
            if not isinstance(r, dict) or not r.get("text"):
                continue
            pid = r.get("pattern_id", "")
            if not pid:
                # i407: pattern_id なし = 旧フォーマット → 除外
                continue
            # i412: pid_remap が指定された場合は source_pid を dest_pid へ変換する
            if pid_remap:
                pid = pid_remap.get(pid, pid)
            # i408: target_roulette_id が指定された場合は上書きして active roulette に帰属させる
            rid = target_roulette_id if target_roulette_id is not None \
                else r.get("roulette_id", "default")
            key = (
                ("id", r["id"]) if r.get("id") else
                ("c", r.get("ts", ""), r.get("text", ""), pid, rid)
            )
            if key in existing_keys:
                continue
            self._records.append({
                "id": r.get("id", ""),
                "text": r.get("text", ""),
                "ts": r.get("ts", ""),
                "pattern_id": pid,
                "pattern": r.get("pattern", ""),
                "roulette_id": rid,
            })
            existing_keys.add(key)
            added += 1

        # ts 昇順に整列して時系列を保つ
        self._records.sort(key=lambda r: r.get("ts", ""))
        return added

    def import_from_records(self, records: list[dict],
                             target_roulette_id: str | None = None) -> int:
        """レコードリストから履歴を取り込む（追記・重複除外マージ）。

        i418: roulette package import 専用。ファイル経由せずメモリ上のリストを直接受け取る。
        import_from_json と同じ重複除外・roulette_id 上書きロジックを適用する。

        Args:
            records: 取り込むレコードリスト
            target_roulette_id: 全レコードの roulette_id をこの値で上書きする。

        Returns:
            追加されたレコード数
        """
        _dedup_base = (
            [r for r in self._records
             if r.get("roulette_id", "default") == target_roulette_id]
            if target_roulette_id is not None
            else self._records
        )
        existing_keys: set = {
            ("id", r["id"]) if r.get("id") else
            ("c", r.get("ts", ""), r.get("text", ""),
             r.get("pattern_id", ""), r.get("roulette_id", "default"))
            for r in _dedup_base
        }

        added = 0
        for r in records:
            if not isinstance(r, dict) or not r.get("text"):
                continue
            pid = r.get("pattern_id", "")
            if not pid:
                continue
            rid = target_roulette_id if target_roulette_id is not None \
                else r.get("roulette_id", "default")
            key = (
                ("id", r["id"]) if r.get("id") else
                ("c", r.get("ts", ""), r.get("text", ""), pid, rid)
            )
            if key in existing_keys:
                continue
            self._records.append({
                "id": r.get("id", ""),
                "text": r.get("text", ""),
                "ts": r.get("ts", ""),
                "pattern_id": pid,
                "pattern": r.get("pattern", ""),
                "roulette_id": rid,
            })
            existing_keys.add(key)
            added += 1
        return added

    @property
    def records(self) -> list[dict]:
        """全レコードのコピーを返す。"""
        return list(self._records)
