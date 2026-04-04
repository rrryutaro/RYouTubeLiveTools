"""
RCommentHub — JSONL コメントログ書き込み

受信コメントを JSON Lines 形式（1メッセージ1行）で追記保存する。
保存先: <base_dir>/logs/<YYYY-MM-DD>/<video_id>_livechat.jsonl

失敗時はアプリを落とさず、呼び出し元が内部ログに残すことを前提とする。
"""

import json
import os
import datetime


class CommentLogger:
    """JSONL コメントログ書き込みクラス"""

    def __init__(self, base_dir: str):
        self._base_dir  = base_dir
        self._file      = None
        self._path      = ""
        self._video_id  = ""
        self._chat_id   = ""

    # ─── 開閉 ───────────────────────────────────────────────────────────────

    def open(self, video_id: str, live_chat_id: str) -> str:
        """
        ログファイルを開く（既存なら追記）。
        成功時はファイルパスを返す。失敗時は例外を raise する。
        """
        self.close()  # 前のファイルが開いていれば閉じる

        self._video_id = video_id
        self._chat_id  = live_chat_id

        date_str = datetime.date.today().strftime("%Y-%m-%d")
        log_dir  = os.path.join(self._base_dir, "logs", date_str)
        os.makedirs(log_dir, exist_ok=True)

        safe_vid   = _safe_filename(video_id)
        self._path = os.path.join(log_dir, f"{safe_vid}_livechat.jsonl")

        self._file = open(self._path, "a", encoding="utf-8")
        return self._path

    def close(self):
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    @property
    def is_open(self) -> bool:
        return self._file is not None

    @property
    def path(self) -> str:
        return self._path

    # ─── 書き込み ────────────────────────────────────────────────────────────

    def write(self, item) -> None:
        """
        CommentItem を 1 行 JSON として追記する。
        失敗しても例外を raise しない（呼び出し元でキャッチして内部ログへ）。
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
            "live_chat_id":              self._chat_id,
            "message_id":                item.msg_id,
            "message_type":              item.kind,
            "published_at":              post_iso,
            "author_channel_id":         item.channel_id,
            "author_display_name_raw":   item.author_name,
            "author_display_name_tts":   getattr(item, "author_display_name_tts", item.author_name),
            "author_channel_url":        item.channel_url,
            "author_profile_image_url":  item.profile_url,
            "is_verified":               item.is_verified,
            "is_chat_owner":             item.is_owner,
            "is_chat_sponsor":           item.is_member,
            "is_chat_moderator":         item.is_moderator,
            "message_text_raw":          item.body,
            "message_text_display":      item.display_msg,
            "filter_match":              getattr(item, "filter_match", False),
            "filter_rule_ids":           getattr(item, "filter_rule_ids", []),
        }

        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        except Exception:
            pass


# ─── ユーティリティ ──────────────────────────────────────────────────────────

def _safe_filename(s: str, max_len: int = 64) -> str:
    """ファイル名に使えない文字を置換する"""
    for ch in r'/\:*?"<>|':
        s = s.replace(ch, "_")
    return s[:max_len] if s else "unknown"
