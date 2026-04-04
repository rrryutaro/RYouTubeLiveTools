"""
RCommentHub — セッション単位ログ保存
1配信 = 1セッション として保存する。

保存先:
  <base_dir>/logs/sessions/<YYYYMMDD_HHMMSS>_<video_id>/
    session_meta.json   — 配信メタ情報（開始・終了時刻、動画ID、タイトル）
    comments.jsonl      — コメント JSONL（1行1件）
    users_snapshot.json — セッション終了時のユーザー一覧スナップショット（任意）
"""

import json
import os
import datetime


class SessionLogger:
    """セッション単位でコメントログを保存するクラス"""

    def __init__(self, base_dir: str):
        self._base_dir     = base_dir
        self._session_dir  = ""
        self._meta_path    = ""
        self._jsonl_path   = ""
        self._file         = None
        self._video_id     = ""
        self._live_chat_id = ""
        self._title        = ""
        self._start_time: datetime.datetime | None = None

    # ─── セッション開閉 ──────────────────────────────────────────────────────

    def open_session(self, video_id: str, live_chat_id: str,
                     title: str = "") -> str:
        """
        新しいセッションを開始する。
        セッションフォルダの絶対パスを返す。
        """
        self.close()

        self._video_id     = video_id
        self._live_chat_id = live_chat_id
        self._title        = title
        self._start_time   = datetime.datetime.now()

        ts        = self._start_time.strftime("%Y%m%d_%H%M%S")
        safe_vid  = _safe_filename(video_id, max_len=24)
        folder    = f"{ts}_{safe_vid}"

        self._session_dir = os.path.join(
            self._base_dir, "logs", "sessions", folder
        )
        os.makedirs(self._session_dir, exist_ok=True)

        self._meta_path  = os.path.join(self._session_dir, "session_meta.json")
        self._jsonl_path = os.path.join(self._session_dir, "comments.jsonl")

        meta = {
            "video_id":      video_id,
            "live_chat_id":  live_chat_id,
            "title":         title,
            "start_time":    self._start_time.isoformat(),
            "end_time":      None,
        }
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        self._file = open(self._jsonl_path, "a", encoding="utf-8")
        return self._session_dir

    def close(self, user_snapshot: list | None = None):
        """
        セッションを終了する。
        user_snapshot を渡すと users_snapshot.json として保存する。
        """
        if not self._file:
            return

        # メタ情報に終了時刻を追記
        try:
            end_time = datetime.datetime.now()
            with open(self._meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            meta["end_time"] = end_time.isoformat()
            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # ユーザースナップショット保存
        if user_snapshot:
            try:
                snap_path = os.path.join(self._session_dir, "users_snapshot.json")
                with open(snap_path, "w", encoding="utf-8") as f:
                    json.dump(user_snapshot, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        try:
            self._file.close()
        except Exception:
            pass
        self._file = None

    @property
    def is_open(self) -> bool:
        return self._file is not None

    @property
    def session_dir(self) -> str:
        return self._session_dir

    # ─── 書き込み ─────────────────────────────────────────────────────────────

    def write(self, item) -> None:
        """
        CommentItem を 1 行 JSON として追記する。
        失敗しても例外を raise しない。
        """
        if self._file is None:
            return

        recv_local = (item.recv_time.astimezone().isoformat()
                      if item.recv_time else "")
        post_iso   = (item.post_time.isoformat()
                      if item.post_time else "")

        record = {
            "received_at_local":         recv_local,
            "video_id":                  self._video_id,
            "live_chat_id":              self._live_chat_id,
            "message_id":                item.msg_id,
            "message_type":              item.kind,
            "published_at":              post_iso,
            "author_channel_id":         item.channel_id,
            "author_display_name_raw":   item.author_name,
            "author_display_name_tts":   getattr(item, "author_display_name_tts",
                                                  item.author_name),
            "author_channel_url":        item.channel_url,
            "author_profile_image_url":  item.profile_url,
            "is_verified":               item.is_verified,
            "is_chat_owner":             item.is_owner,
            "is_chat_sponsor":           item.is_member,
            "is_chat_moderator":         item.is_moderator,
            "message_text_raw":          item.body,
            "message_text_display":      item.display_msg,
            "filter_match":              getattr(item, "filter_match",    False),
            "filter_rule_ids":           getattr(item, "filter_rule_ids", []),
            "input_source":              getattr(item, "source", "live_youtube"),
        }

        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        except Exception:
            pass


# ─── ユーティリティ ──────────────────────────────────────────────────────────

def _safe_filename(s: str, max_len: int = 32) -> str:
    for ch in r'/\:*?"<>|':
        s = s.replace(ch, "_")
    return (s[:max_len] if s else "unknown")
