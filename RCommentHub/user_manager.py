"""
RCommentHub — ユーザー状態管理
配信セッション中のユーザー情報をトラッキングする
"""

import datetime


class UserRecord:
    """1ユーザーの状態を保持"""

    def __init__(self, channel_id: str, display_name: str):
        self.channel_id       = channel_id
        self.display_name     = display_name
        self.comment_count    = 0
        self.last_comment_time: datetime.datetime | None = None
        self.is_whitelist     = False
        self.is_blacklist     = False
        self.is_filter_target = True   # フィルタ対象に含めるか

    @property
    def elapsed_str(self) -> str:
        if self.last_comment_time is None:
            return "—"
        delta = datetime.datetime.now() - self.last_comment_time
        secs  = int(delta.total_seconds())
        if secs < 0:
            return "—"
        if secs < 60:
            return f"{secs}秒前"
        if secs < 3600:
            return f"{secs // 60}分前"
        return f"{secs // 3600}時間前"

    @property
    def last_time_str(self) -> str:
        if self.last_comment_time is None:
            return "—"
        return self.last_comment_time.strftime("%H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "channel_id":        self.channel_id,
            "display_name":      self.display_name,
            "comment_count":     self.comment_count,
            "last_comment_time": (self.last_comment_time.isoformat()
                                  if self.last_comment_time else None),
            "is_whitelist":      self.is_whitelist,
            "is_blacklist":      self.is_blacklist,
            "is_filter_target":  self.is_filter_target,
        }


class UserManager:
    """配信セッション中のユーザー一覧を管理する"""

    def __init__(self):
        self._users: dict[str, UserRecord] = {}   # channel_id -> UserRecord
        self._on_updated = None   # (UserRecord) -> None

    def set_update_callback(self, cb):
        self._on_updated = cb

    def on_comment(self, item) -> UserRecord:
        """コメント受信時にユーザー情報を集計更新する"""
        cid  = item.channel_id or item.author_name
        name = item.author_name

        if cid not in self._users:
            rec = UserRecord(cid, name)
            self._users[cid] = rec
        else:
            rec = self._users[cid]
            if name:
                rec.display_name = name

        rec.comment_count += 1
        rec.last_comment_time = item.recv_time or datetime.datetime.now()

        if self._on_updated:
            self._on_updated(rec)

        return rec

    def get(self, channel_id: str) -> "UserRecord | None":
        return self._users.get(channel_id)

    def all_users(self) -> list:
        return list(self._users.values())

    def count(self) -> int:
        return len(self._users)

    def is_blacklisted(self, channel_id: str) -> bool:
        rec = self._users.get(channel_id)
        return rec.is_blacklist if rec else False

    def clear(self):
        self._users.clear()

    def snapshot(self) -> list:
        return [r.to_dict() for r in self._users.values()]
