"""Local retention for YouTube API data persisted by RCommentHub.

Session folders also contain Twitch data in mixed sessions, so the documented
29-day session-history limit applies to the whole app-managed folder.
"""

import datetime
import os
from pathlib import Path
import re
import shutil


RETENTION_DAYS = 29
_SESSION_NAME = re.compile(r"^\d{8}_\d{6}_.+")


def _local_now(now=None):
    value = now or datetime.datetime.now()
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value


def purge_expired_sessions(base_dir, now=None):
    """Delete only old, app-named session folders; return the deletion count."""
    root = Path(base_dir) / "logs" / "sessions"
    if root.is_symlink() or not root.is_dir():
        return 0
    cutoff = _local_now(now) - datetime.timedelta(days=RETENTION_DAYS)
    root_resolved = root.resolve()
    deleted = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not _SESSION_NAME.fullmatch(entry.name):
            continue
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            continue
        if not entry.is_dir() or entry.resolve().parent != root_resolved:
            continue
        try:
            created = datetime.datetime.strptime(entry.name[:15], "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        if created > cutoff:
            continue
        try:
            shutil.rmtree(entry)
            deleted += 1
        except OSError:
            # A locked or inaccessible session will be retried on next cleanup.
            pass
    return deleted


def fresh_user_flags(flags, now=None):
    """Discard undated legacy API identifiers and flags aged 29 days or more."""
    if not isinstance(flags, dict):
        return {}
    current = _local_now(now)
    cutoff = current - datetime.timedelta(days=RETENTION_DAYS)
    retained = {}
    for channel_id, value in flags.items():
        if not isinstance(value, dict):
            continue
        try:
            stored = datetime.datetime.fromisoformat(value["stored_at"])
            stored = _local_now(stored)
        except (KeyError, TypeError, ValueError):
            continue
        if cutoff < stored <= current + datetime.timedelta(minutes=5):
            retained[channel_id] = value
    return retained


def flags_from_records(records, now=None):
    """Save viewer flags only while their API-derived identity is fresh."""
    flags = {}
    for record in records:
        seen = getattr(record, 'last_comment_time', None)
        if not seen or not record.channel_id:
            continue
        flags[record.channel_id] = {
            'stored_at': seen.isoformat(),
            'display_name': record.display_name,
            'is_whitelist': record.is_whitelist,
            'is_blacklist': record.is_blacklist,
            'is_filter_target': record.is_filter_target,
        }
    return fresh_user_flags(flags, now)
