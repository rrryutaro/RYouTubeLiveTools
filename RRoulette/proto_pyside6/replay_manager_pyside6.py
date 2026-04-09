"""
PySide6 プロトタイプ — リプレイ記録・再生管理

スピンの全フレームを記録し、QTimer ベースで再生する。
WinHistory（勝利数集計用）とは別の責務。

責務:
  - スピン記録の開始・フレーム蓄積・完了
  - 記録一覧の管理（件数上限・keep 保護・削除・名前変更）
  - JSON ファイルへの保存・復元
  - QTimer ベースの再生（フレーム角度再現・音イベント再生）

記録単位:
  single / double / triple 全体を 1 replay 記録として扱う。
  途中フェーズの delay も含め、開始から最終結果確定までの
  全フレーム・全音イベントを 1 シーケンスに記録する。
"""

import json
import os
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal


REPLAY_MAX_COUNT_DEFAULT = 5


class ReplayManager(QObject):
    """リプレイ記録の管理クラス。

    記録データ構造:
        {
            "name": str,
            "created_at": str (ISO 8601),
            "keep": bool,
            "start_snapshot": {
                "segments": [{item_text, item_index, arc, start_angle}, ...],
                "pointer_angle": float,
                "spin_direction": int,
            },
            "frames": [{"t": float_ms, "angle": float}, ...],
            "sounds": [{"t": float_ms, "type": str}, ...],
            "result": {
                "winner": str,
                "winner_item_index": int,
                "final_angle": float,
            },
        }
    """

    # 再生完了シグナル: (winner_text, winner_item_index)
    playback_finished = Signal(str, int)

    def __init__(self, save_path: str = "", max_count: int = REPLAY_MAX_COUNT_DEFAULT,
                 parent=None):
        super().__init__(parent)
        self._records: list[dict] = []
        self._save_path = save_path
        self._max_count = max(1, max_count)
        self._recording: bool = False
        self._rec: dict | None = None
        self._start_time: float = 0.0

        # --- 再生状態 ---
        self._playing: bool = False
        self._play_timer: QTimer = QTimer(self)
        self._play_timer.setSingleShot(True)
        self._play_timer.timeout.connect(self._play_step)
        self._play_rec: dict | None = None
        self._play_frame_idx: int = 0
        self._play_sound_idx: int = 0
        self._play_wheel = None      # WheelWidget
        self._play_sound_mgr = None  # SoundManager

    @property
    def records(self) -> list[dict]:
        return self._records

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_playing(self) -> bool:
        return self._playing

    def set_max_count(self, count: int):
        self._max_count = max(1, count)
        self._enforce_limit()

    # ================================================================
    #  記録
    # ================================================================

    def start_recording(self, segments: list, pointer_angle: float,
                        spin_direction: int):
        """スピン開始時に記録を開始する。

        Args:
            segments: 現在のセグメントリスト (Segment オブジェクト)
            pointer_angle: ポインター角度
            spin_direction: 回転方向 (0 or 1)
        """
        self._start_time = time.perf_counter()
        self._rec = {
            "name": "",
            "created_at": datetime.now().isoformat(),
            "keep": False,
            "start_snapshot": {
                "segments": [
                    {
                        "item_text": s.item_text,
                        "item_index": s.item_index,
                        "arc": s.arc,
                        "start_angle": s.start_angle,
                    }
                    for s in segments
                ],
                "pointer_angle": pointer_angle,
                "spin_direction": spin_direction,
            },
            "frames": [],
            "sounds": [],
            "result": None,
        }
        self._recording = True

    def record_frame(self, angle: float):
        """各フレームの角度を記録する。"""
        if not self._recording or self._rec is None:
            return
        t = (time.perf_counter() - self._start_time) * 1000
        self._rec["frames"].append({"t": t, "angle": angle})

    def record_sound(self, sound_type: str):
        """音イベントを記録する（tick / win）。"""
        if not self._recording or self._rec is None:
            return
        t = (time.perf_counter() - self._start_time) * 1000
        self._rec["sounds"].append({"t": t, "type": sound_type})

    def finish_recording(self, winner: str, winner_item_index: int,
                         final_angle: float):
        """スピン完了で記録を確定し、records に追加する。"""
        if not self._recording or self._rec is None:
            return
        self._rec["result"] = {
            "winner": winner,
            "winner_item_index": winner_item_index,
            "final_angle": final_angle,
        }
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._rec["name"] = f"{ts} - {winner}" if winner else ts
        self._records.insert(0, self._rec)
        self._rec = None
        self._recording = False
        self._enforce_limit()
        self.save()

    def cancel_recording(self):
        """進行中の記録を破棄する。"""
        self._rec = None
        self._recording = False

    # ================================================================
    #  一覧管理
    # ================================================================

    def count(self) -> int:
        return len(self._records)

    def get(self, idx: int) -> dict | None:
        if 0 <= idx < len(self._records):
            return self._records[idx]
        return None

    def rename(self, idx: int, new_name: str):
        if 0 <= idx < len(self._records):
            self._records[idx]["name"] = new_name
            self.save()

    def delete(self, idx: int):
        if 0 <= idx < len(self._records):
            del self._records[idx]
            self.save()

    def set_keep(self, idx: int, keep: bool):
        if 0 <= idx < len(self._records):
            self._records[idx]["keep"] = keep
            self.save()

    def _enforce_limit(self):
        """件数上限を適用。keep=True は除外対象。"""
        non_keep = [i for i, r in enumerate(self._records) if not r.get("keep")]
        excess = len(non_keep) - self._max_count
        if excess > 0:
            to_remove = set(non_keep[-excess:])
            self._records = [
                r for i, r in enumerate(self._records) if i not in to_remove
            ]

    # ================================================================
    #  保存・復元
    # ================================================================

    def save(self):
        if not self._save_path:
            return
        try:
            data = {"replays": self._records}
            with open(self._save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def load(self):
        if not self._save_path or not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("replays"), list):
                self._records = data["replays"]
            else:
                self._records = []
        except Exception:
            self._records = []
        self._enforce_limit()

    # ================================================================
    #  Export / Import
    # ================================================================

    def export_record(self, idx: int, path: str) -> bool:
        """指定インデックスの replay を JSON ファイルへ export する。

        Returns:
            成功したら True
        """
        rec = self.get(idx)
        if rec is None:
            return False
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def export_records(self, indices: list[int], path: str) -> bool:
        """複数の replay を {"replays": [...]} 形式の JSON ファイルへ export する。

        Returns:
            成功したら True
        """
        records = []
        for idx in indices:
            rec = self.get(idx)
            if rec is not None:
                records.append(rec)
        if not records:
            return False
        try:
            data = {"replays": records}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def import_record(self, path: str) -> int:
        """JSON ファイルから replay を import し、records の先頭に追加する。

        自動判別:
          - {"replays": [...]} 形式: 配列内の有効な各レコードを追加
          - {"frames": [...], ...} 形式: 1件レコードとして追加

        各レコードは最低限 frames (非空リスト) が必要。
        不正な要素はスキップする。

        Returns:
            取り込んだ件数（0 = 失敗）
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return 0

        if not isinstance(data, dict):
            return 0

        # {"replays": [...]} 形式の判定
        if isinstance(data.get("replays"), list):
            imported = 0
            for rec in data["replays"]:
                if (isinstance(rec, dict)
                        and isinstance(rec.get("frames"), list)
                        and rec["frames"]):
                    self._records.insert(imported, rec)
                    imported += 1
            if imported > 0:
                self._enforce_limit()
                self.save()
            return imported

        # 単体レコード形式
        if not isinstance(data.get("frames"), list) or not data["frames"]:
            return 0

        self._records.insert(0, data)
        self._enforce_limit()
        self.save()
        return 1

    # ================================================================
    #  再生
    # ================================================================

    def start_playback(self, idx: int, wheel, sound_mgr=None) -> bool:
        """指定インデックスの replay を再生開始する。

        Args:
            idx: records のインデックス（0=最新）
            wheel: WheelWidget（角度・セグメント設定先）
            sound_mgr: SoundManager（音再生用、省略可）

        Returns:
            再生を開始できたら True
        """
        if self._playing or self._recording:
            return False
        rec = self.get(idx)
        if rec is None or not rec.get("frames"):
            return False

        self._play_rec = rec
        self._play_wheel = wheel
        self._play_sound_mgr = sound_mgr
        self._play_frame_idx = 0
        self._play_sound_idx = 0
        self._playing = True

        # スナップショットを適用
        snap = rec["start_snapshot"]
        from constants import Segment
        replay_segments = [
            Segment(
                item_text=s["item_text"],
                item_index=s["item_index"],
                arc=s["arc"],
                start_angle=s["start_angle"],
            )
            for s in snap["segments"]
        ]
        wheel.set_segments(replay_segments)
        wheel.set_pointer_angle(snap["pointer_angle"])
        wheel._spin_direction = snap["spin_direction"]

        # 最初のフレームを即時適用
        first = rec["frames"][0]
        wheel.set_angle(first["angle"])

        # 再生開始
        self._schedule_next_frame()
        return True

    def stop_playback(self):
        """再生を中断する。"""
        if not self._playing:
            return
        self._play_timer.stop()
        self._playing = False
        self._play_rec = None
        self._play_wheel = None
        self._play_sound_mgr = None

    def _schedule_next_frame(self):
        """次のフレームをタイマーでスケジュールする。"""
        rec = self._play_rec
        if rec is None:
            return
        frames = rec["frames"]
        fi = self._play_frame_idx

        if fi + 1 >= len(frames):
            # 最終フレーム到達
            self._on_playback_finish()
            return

        current_t = frames[fi]["t"]
        next_t = frames[fi + 1]["t"]
        delay = max(1, int(next_t - current_t))
        self._play_timer.start(delay)

    def _play_step(self):
        """再生の1ステップ: 次のフレームを適用する。"""
        if not self._playing or self._play_rec is None:
            return

        self._play_frame_idx += 1
        frames = self._play_rec["frames"]
        fi = self._play_frame_idx

        if fi >= len(frames):
            self._on_playback_finish()
            return

        fr = frames[fi]
        wheel = self._play_wheel
        if wheel is not None:
            wheel.set_angle(fr["angle"])

        # この時刻以前の音イベントを再生
        sounds = self._play_rec.get("sounds", [])
        while (self._play_sound_idx < len(sounds) and
               sounds[self._play_sound_idx]["t"] <= fr["t"]):
            sev = sounds[self._play_sound_idx]
            if self._play_sound_mgr is not None:
                if sev["type"] == "tick":
                    self._play_sound_mgr.play_tick()
                elif sev["type"] == "win":
                    self._play_sound_mgr.play_win()
            self._play_sound_idx += 1

        self._schedule_next_frame()

    def _on_playback_finish(self):
        """再生完了処理。"""
        rec = self._play_rec
        if rec is None:
            self._playing = False
            return

        # 残りの音イベントを再生（最終フレーム以降の win 音など）
        sounds = rec.get("sounds", [])
        while self._play_sound_idx < len(sounds):
            sev = sounds[self._play_sound_idx]
            if self._play_sound_mgr is not None:
                if sev["type"] == "tick":
                    self._play_sound_mgr.play_tick()
                elif sev["type"] == "win":
                    self._play_sound_mgr.play_win()
            self._play_sound_idx += 1

        # 最終角度を適用
        result = rec.get("result", {})
        if result and self._play_wheel is not None:
            self._play_wheel.set_angle(result.get("final_angle", 0.0))

        winner = result.get("winner", "") if result else ""
        winner_idx = result.get("winner_item_index", -1) if result else -1

        self._playing = False
        self._play_rec = None
        wheel = self._play_wheel
        self._play_wheel = None
        self._play_sound_mgr = None

        self.playback_finished.emit(winner, winner_idx)
