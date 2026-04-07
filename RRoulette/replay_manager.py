"""
RRoulette — リプレイ管理 Mixin (Phase 2)

  フレーム記録方式でスピンを保持し、再生・永続保存・管理を行う。

  記録内容:
    - name            : リプレイ名（自動生成 or ユーザー任意）
    - created_at      : 作成日時（ISO 8601）
    - start_snapshot  : スピン開始時のセグメント配置・ポインター角度・方向
    - frames          : 各フレームの経過時刻(ms)と angle
    - events          : 操作イベント（start / double_stop / triple_stop）
    - sounds          : 音イベント（tick / win）と経過時刻
    - result          : winner・当選インデックス・最終角度・セグメント色

  スピンエンジン側のフック（spin_engine.py 参照）:
    _replay_record_start  → _start_spin() から呼ばれる
    _replay_record_frame  → _frame() から呼ばれる
    _replay_record_event  → _handle_action() から呼ばれる
    _replay_record_finish → _finish() から呼ばれる
"""

import json
import os
import time
from datetime import datetime


REPLAY_MAX_COUNT_DEFAULT = 5
REPLAY_MAX_COUNT_MIN = 1
REPLAY_MAX_COUNT_MAX = 20


def _replay_file_path():
    """永続保存ファイルパスを返す。"""
    from config_utils import BASE_DIR, INSTANCE_NUM
    if INSTANCE_NUM == 1:
        return os.path.join(BASE_DIR, "roulette_replay.json")
    return os.path.join(BASE_DIR, f"roulette_replay_{INSTANCE_NUM}.json")


def _auto_name(result: dict | None) -> str:
    """自動リプレイ名を生成する。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    winner = ""
    if result and result.get("winner"):
        winner = f" - {result['winner']}"
    return f"{ts}{winner}"


class ReplayManagerMixin:

    # ════════════════════════════════════════════════════════════════
    #  初期化
    # ════════════════════════════════════════════════════════════════
    def _replay_init(self):
        """初期化。RouletteApp.__init__ から呼ぶ。"""
        self._replay_records: list[dict] = []
        self._replaying: bool = False
        self._replay_rec: dict | None = None
        self._replay_spin_start: float = 0.0
        self._replay_restore_fn = None
        self._replay_dialog_win = None  # 管理画面参照
        # 永続保存から読み込み
        self._replay_load()

    # ════════════════════════════════════════════════════════════════
    #  永続保存・読込
    # ════════════════════════════════════════════════════════════════
    def _replay_save(self):
        """現在の replay_records を JSON ファイルに保存する。"""
        path = _replay_file_path()
        try:
            data = {"replays": self._replay_records}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _replay_load(self):
        """JSON ファイルから replay_records を読み込む。"""
        path = _replay_file_path()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("replays"), list):
                self._replay_records = data["replays"]
            else:
                self._replay_records = []
        except Exception:
            self._replay_records = []
        # 上限を適用（keep=true は除外）
        self._replay_enforce_limit()

    def _replay_enforce_limit(self):
        """保存件数上限を適用し、保持されていない古い replay から削除する。
        保持(keep)された replay は自動削除対象から除外する。
        """
        max_count = getattr(self, "_replay_max_count", REPLAY_MAX_COUNT_DEFAULT)
        # 保持されていない replay の数をカウント
        non_keep = [i for i, r in enumerate(self._replay_records) if not r.get("keep")]
        excess = len(non_keep) - max_count
        if excess > 0:
            # 古いものから削除（non_keep のインデックスは降順=最古が末尾）
            to_remove = set(non_keep[-excess:])
            self._replay_records = [
                r for i, r in enumerate(self._replay_records) if i not in to_remove
            ]
            self._replay_save()

    # ════════════════════════════════════════════════════════════════
    #  記録フック（SpinEngineMixin から呼ばれる）
    # ════════════════════════════════════════════════════════════════
    def _replay_record_start(self, source: str = "unknown"):
        """スピン開始時スナップショットを記録する。"""
        self._replay_spin_start = time.perf_counter()
        self._replay_rec = {
            "name": "",
            "created_at": datetime.now().isoformat(),
            "start_snapshot": {
                "segments": [
                    {
                        "item_text":   s.item_text,
                        "item_index":  s.item_index,
                        "arc":         s.arc,
                        "start_angle": s.start_angle,
                    }
                    for s in self.current_segments
                ],
                "pointer_angle":  self._pointer_angle,
                "spin_direction": getattr(self, "_spin_direction", 0),
            },
            "frames": [],
            "sounds": [],
            "events": [{"t": 0.0, "type": "start", "source": source}],
            "result": None,
        }

    def _replay_record_frame(self, angle: float):
        """各フレームの角度を記録する。"""
        if self._replay_rec is None:
            return
        t = (time.perf_counter() - self._replay_spin_start) * 1000  # ms
        self._replay_rec["frames"].append({"t": t, "angle": angle})

    def _replay_record_sound(self, sound_type: str):
        """音イベントを記録する（tick / win）。"""
        if self._replay_rec is None:
            return
        t = (time.perf_counter() - self._replay_spin_start) * 1000
        self._replay_rec["sounds"].append({"t": t, "type": sound_type})

    def _replay_record_event(self, event_type: str, source: str = "unknown"):
        """操作イベントを記録する（double_stop / triple_stop）。"""
        if self._replay_rec is None:
            return
        t = (time.perf_counter() - self._replay_spin_start) * 1000
        self._replay_rec["events"].append({"t": t, "type": event_type, "source": source})

    def _replay_record_finish(self, winner: str, winner_item_index: int,
                               final_angle: float, seg_color: str):
        """スピン完了情報を記録して records へ保存する。"""
        if self._replay_rec is None:
            return
        self._replay_rec["result"] = {
            "winner":            winner,
            "winner_item_index": winner_item_index,
            "final_angle":       final_angle,
            "seg_color":         seg_color,
        }
        # 自動名を設定
        self._replay_rec["name"] = _auto_name(self._replay_rec["result"])
        self._replay_rec["keep"] = False
        # 先頭に挿入（最新が先頭）
        self._replay_records.insert(0, self._replay_rec)
        self._replay_rec = None
        # 上限適用 & 永続保存
        self._replay_enforce_limit()
        self._replay_save()
        # 管理画面が開いていれば即時反映
        self._replay_notify_dialog()

    # ════════════════════════════════════════════════════════════════
    #  リプレイ名変更
    # ════════════════════════════════════════════════════════════════
    def _replay_rename(self, idx: int, new_name: str):
        """指定インデックスのリプレイ名を変更する。"""
        if 0 <= idx < len(self._replay_records):
            self._replay_records[idx]["name"] = new_name
            self._replay_save()

    # ════════════════════════════════════════════════════════════════
    #  リプレイ削除
    # ════════════════════════════════════════════════════════════════
    def _replay_delete(self, idx: int):
        """指定インデックスのリプレイを削除する。"""
        if 0 <= idx < len(self._replay_records):
            del self._replay_records[idx]
            self._replay_save()

    # ════════════════════════════════════════════════════════════════
    #  管理画面通知
    # ════════════════════════════════════════════════════════════════
    def _replay_notify_dialog(self):
        """開いている管理画面の一覧を更新する。"""
        win = getattr(self, "_replay_dialog_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win._refresh_list()
            except Exception:
                self._replay_dialog_win = None

    # ════════════════════════════════════════════════════════════════
    #  import / export
    # ════════════════════════════════════════════════════════════════
    def _replay_export(self, idx: int, path: str) -> bool:
        """指定インデックスのリプレイを JSON ファイルに書き出す。"""
        if idx < 0 or idx >= len(self._replay_records):
            return False
        rec = self._replay_records[idx]
        try:
            data = {"rroulette_replay": rec}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _replay_import(self, path: str) -> str | None:
        """JSON ファイルからリプレイを読み込んで追加する。
        成功時は None、失敗時はエラーメッセージを返す。"""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as ex:
            return f"ファイルを読み込めませんでした:\n{ex}"

        if not isinstance(data, dict):
            return "ファイルの形式が正しくありません。"

        rec = data.get("rroulette_replay")
        if not isinstance(rec, dict):
            return "リプレイデータが見つかりませんでした。"

        # 最低限の構造チェック
        required = ("start_snapshot", "frames", "result")
        for key in required:
            if key not in rec:
                return f"必須フィールド '{key}' がありません。"

        # name 重複時は (import) を付与
        existing_names = {r.get("name", "") for r in self._replay_records}
        name = rec.get("name", "import")
        if name in existing_names:
            base = name
            suffix = 1
            while f"{base} (import{'' if suffix == 1 else ' ' + str(suffix)})" in existing_names:
                suffix += 1
            name = f"{base} (import{'' if suffix == 1 else ' ' + str(suffix)})"
        rec["name"] = name

        # created_at がなければ現在時刻
        if "created_at" not in rec:
            rec["created_at"] = datetime.now().isoformat()

        # events / sounds がなければ空リスト
        rec.setdefault("events", [])
        rec.setdefault("sounds", [])
        # keep フラグを維持（export 時に含まれていれば反映）
        rec.setdefault("keep", False)

        # 先頭に挿入
        self._replay_records.insert(0, rec)
        self._replay_enforce_limit()
        self._replay_save()
        self._replay_notify_dialog()
        return None

    # ════════════════════════════════════════════════════════════════
    #  再生
    # ════════════════════════════════════════════════════════════════
    def _replay_play(self, idx: int = 0):
        """指定インデックス（0=最新）の記録を再生する。
        再生中は通常スピン・操作をブロックし、_record_result は呼ばない。
        """
        import tkinter.messagebox as _msgbox
        from constants import Segment

        if self._replaying or self.spinning or self._flashing:
            return
        if idx >= len(self._replay_records):
            _msgbox.showinfo("リプレイ", "リプレイ記録がありません。\nスピンを行うと記録されます。",
                             parent=self.root)
            return

        rec = self._replay_records[idx]
        frames = rec["frames"]
        sounds = rec.get("sounds", [])
        events = rec["events"]
        result = rec["result"]
        snap   = rec["start_snapshot"]

        if not frames:
            _msgbox.showinfo("リプレイ", "再生できる記録がありません。", parent=self.root)
            return

        # ── 現在の描画状態を退避 ─────────────────────────────────────
        saved_segments       = self.current_segments
        saved_angle          = self.angle
        saved_pointer_angle  = self._pointer_angle
        saved_spin_direction = getattr(self, "_spin_direction", 0)

        # ── スナップショットを適用 ────────────────────────────────────
        self.current_segments = [
            Segment(
                item_text   = s["item_text"],
                item_index  = s["item_index"],
                arc         = s["arc"],
                start_angle = s["start_angle"],
            )
            for s in snap["segments"]
        ]
        self._pointer_angle  = snap["pointer_angle"]
        self._spin_direction = snap["spin_direction"]
        self.angle = frames[0]["angle"]

        self._replaying = True
        self.set_item_spin_lock(True)
        self.set_cfg_spin_lock(True)
        self.cv.delete("result_overlay")

        # リプレイ中表示
        self._replay_show_indicator()

        # 操作イベントを時刻順にリスト化（start 以外）
        op_events = sorted(
            [ev for ev in events if ev["type"] != "start"],
            key=lambda x: x["t"],
        )
        # 音イベントを時刻順にリスト化
        snd_events = sorted(sounds, key=lambda x: x["t"])
        next_ev_idx  = [0]
        next_snd_idx = [0]
        frame_idx    = [0]
        total_frames = len(frames)

        # ── 状態復元クロージャ ────────────────────────────────────────
        def _restore():
            self._replaying = False
            self.current_segments = saved_segments
            self.angle            = saved_angle
            self._pointer_angle   = saved_pointer_angle
            self._spin_direction  = saved_spin_direction
            self.set_item_spin_lock(False)
            self.set_cfg_spin_lock(False)
            self.cv.delete("replay_event_label")
            self.cv.delete("result_overlay")
            self._replay_hide_indicator()
            self._redraw()

        self._replay_restore_fn = _restore

        def _show_event_label(ev_type: str):
            label_map = {
                "double_stop": "\u25c4\u25c4 \u30c0\u30d6\u30eb\u505c\u6b62",   # ◄◄ ダブル停止
                "triple_stop": "\u25c4\u25c4\u25c4 \u5373\u6642\u505c\u6b62",   # ◄◄◄ 即時停止
            }
            text = label_map.get(ev_type, ev_type)
            self.cv.delete("replay_event_label")
            self.cv.create_text(
                self.CX, self.CY - int(self.R * 0.65),
                text=text,
                fill="#ffff88", font=("Meiryo", 11, "bold"),
                tags="replay_event_label",
            )
            self.root.after(700, lambda: self.cv.delete("replay_event_label"))

        def _on_finish():
            # 最終フレーム以降に記録された音イベント（win 音など）を消化する
            while next_snd_idx[0] < len(snd_events):
                sev = snd_events[next_snd_idx[0]]
                if sev["type"] == "tick":
                    self.snd.play_tick()
                elif sev["type"] == "win":
                    self.snd.play_win()
                next_snd_idx[0] += 1
            if result:
                self.angle = result["final_angle"]
                self._replay_flash(4, result["winner"], result.get("seg_color", "#888888"))
            else:
                _restore()

        def _step():
            fi = frame_idx[0]
            if fi >= total_frames:
                _on_finish()
                return

            fr = frames[fi]
            self.angle = fr["angle"]
            frame_idx[0] += 1

            # この時刻以前の音イベントを再生
            while (next_snd_idx[0] < len(snd_events) and
                   snd_events[next_snd_idx[0]]["t"] <= fr["t"]):
                sev = snd_events[next_snd_idx[0]]
                if sev["type"] == "tick":
                    self.snd.play_tick()
                elif sev["type"] == "win":
                    self.snd.play_win()
                next_snd_idx[0] += 1

            # この時刻以前の操作イベントを表示
            while (next_ev_idx[0] < len(op_events) and
                   op_events[next_ev_idx[0]]["t"] <= fr["t"]):
                _show_event_label(op_events[next_ev_idx[0]]["type"])
                next_ev_idx[0] += 1

            self._redraw()

            if fi + 1 < total_frames:
                nxt = frames[fi + 1]
                delay = max(1, int(nxt["t"] - fr["t"]))
                self.root.after(delay, _step)
            else:
                self.root.after(16, _on_finish)

        self._redraw()
        _step()

    def _replay_flash(self, times: int, winner: str, seg_color: str):
        """リプレイ用フラッシュ。_record_result を呼ばない。
        win 音イベントは _on_finish で消化済み。
        点滅完了後は result_overlay を保持し、overlay 消去時に _restore() で復元する。
        フラッシュ完了時点で cfg/item spin lock は解除する（通常 _flash と同等）。
        """
        self._flashing = False
        self._redraw()
        self._flashing = True
        self._draw_result_overlay(winner, times, seg_color)
        if times > 0:
            self.root.after(220, lambda: self._replay_flash(times - 1, winner, seg_color))
        else:
            # 点滅完了 — ロック解除（結果確定後は設定操作可能にする）
            self._flashing = False
            self.set_item_spin_lock(False)
            self.set_cfg_spin_lock(False)
            # overlay 消去時に描画状態を復元する
            restore = self._replay_restore_fn
            self._replay_restore_fn = None
            def _finish_replay():
                if restore:
                    restore()
            self._result_close_fn = _finish_replay
            self._result_showing = True
            hold = getattr(self, '_result_hold_sec', 5.0)
            ms = max(500, int(hold * 1000))
            self._result_auto_timer = self.root.after(ms, self._close_result_overlay)

    def _replay_cancel(self):
        """進行中のリプレイを強制キャンセルする。"""
        if not self._replaying:
            return
        self._flashing = False
        # 結果表示タイマーもキャンセル
        self._result_showing = False
        self._result_overlay_rect = None
        if getattr(self, '_result_auto_timer', None):
            self.root.after_cancel(self._result_auto_timer)
            self._result_auto_timer = None
        self._result_close_fn = None
        restore = self._replay_restore_fn
        self._replay_restore_fn = None
        if restore:
            restore()

    # ════════════════════════════════════════════════════════════════
    #  リプレイ中表示
    # ════════════════════════════════════════════════════════════════
    def _replay_show_indicator(self):
        """リプレイ中表示をキャンバスに描画する。"""
        if not getattr(self, "_replay_show_indicator_flag", True):
            return
        self.cv.delete("replay_indicator")
        # ホイール左上に小さく表示
        x = self.CX - self.R + 10
        y = self.CY - self.R + 10
        self.cv.create_text(
            x, y,
            text="リプレイ中",
            fill="#ff9900", font=("Meiryo", 10, "bold"),
            anchor="nw",
            tags="replay_indicator",
        )

    def _replay_hide_indicator(self):
        """リプレイ中表示を消す。"""
        self.cv.delete("replay_indicator")
