"""
RCommentHub — コメントコントローラ

コメント処理の中核。UI 非依存のビジネスロジック層。
v0.2.0: 固定2接続（conn1/conn2）同時表示対応
"""

import datetime
import threading

from tts_service import TTSService
from tts_name import make_tts_name
from youtube_client import YouTubeClient
from user_manager import UserManager
from filter_rules import FilterRuleManager
from session_logger import SessionLogger
from constants import (
    EVENT_TYPE_LABELS, PROC_STATUS_LABELS,
    ROLE_OWNER, ROLE_MODERATOR, ROLE_MEMBER, ROLE_VERIFIED,
    SOURCE_DEFAULT_NAMES,
)


# ════════════════════════════════════════════════════════════════════════════
#  URL から動画ID を抽出するユーティリティ（rcommenthub.py と同じロジック）
# ════════════════════════════════════════════════════════════════════════════

def _extract_video_id(text: str) -> str:
    import urllib.parse
    text = text.strip()
    if not text:
        return text
    if "youtube.com" not in text and "youtu.be" not in text:
        return text
    try:
        parsed     = urllib.parse.urlparse(text)
        path_parts = [p for p in parsed.path.split("/") if p]
        if "live" in path_parts:
            idx = path_parts.index("live")
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
        if parsed.netloc in ("youtu.be", "www.youtu.be") and path_parts:
            return path_parts[0]
    except Exception:
        pass
    return text


# ════════════════════════════════════════════════════════════════════════════
#  コメントデータモデル
# ════════════════════════════════════════════════════════════════════════════

class CommentItem:
    """受信したコメント1件を表す内部データ構造"""

    def __init__(self, seq_no: int, raw: dict):
        self.seq_no    = seq_no
        self.raw       = raw
        self.recv_time = datetime.datetime.now()
        self.proc_status = "unprocessed"
        self.matched_filters: list = []
        self.sent_to: list = []

        snippet = raw.get("snippet", {})
        author  = raw.get("authorDetails", {})

        self.msg_id      = raw.get("id", "")
        self.kind        = snippet.get("type", "unknown")
        self.post_time   = self._parse_time(snippet.get("publishedAt", ""))
        self.channel_id  = author.get("channelId", "")
        self.author_name = author.get("displayName", "")
        self.channel_url = author.get("channelUrl", "")
        self.profile_url = author.get("profileImageUrl", "")

        self.is_owner     = author.get("isChatOwner",     False)
        self.is_moderator = author.get("isChatModerator", False)
        self.is_member    = author.get("isChatSponsor",   False)
        self.is_verified  = author.get("isVerified",      False)

        self.has_display  = snippet.get("hasDisplayContent", False)
        self.display_msg  = snippet.get("displayMessage", "")
        self.live_chat_id = snippet.get("liveChatId", "")

        self.body = self._extract_body(snippet)

        self.source: str      = raw.get("_source", "live_youtube")
        self.source_id: str   = raw.get("_source_id", "conn1")
        self.source_name: str = raw.get("_source_name", "")

        self.author_display_name_tts: str  = make_tts_name(self.author_name)
        self.filter_match:            bool  = False
        self.filter_rule_ids:         list  = []
        self.tts_target:              bool  = False

    def _parse_time(self, s: str):
        if not s:
            return None
        try:
            return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def _extract_body(self, snippet: dict) -> str:
        kind = snippet.get("type", "")
        if kind == "textMessageEvent":
            return snippet.get("textMessageDetails", {}).get("messageText", "")
        if kind == "superChatEvent":
            d   = snippet.get("superChatDetails", {})
            amt = d.get("amountDisplayString", "")
            msg = d.get("userComment", "")
            return f"{amt}  {msg}".strip()
        if kind == "superStickerEvent":
            return snippet.get("superStickerDetails", {}).get("amountDisplayString", "")
        if kind == "memberMilestoneChatEvent":
            return snippet.get("memberMilestoneChatDetails", {}).get("userComment", "")
        if kind == "membershipGiftingEvent":
            d = snippet.get("membershipGiftingDetails", {})
            return f"ギフトメンバー ×{d.get('giftMembershipsCount', '')}"
        if kind == "giftMembershipReceivedEvent":
            return "ギフトメンバーシップ受取"
        if kind == "pollEvent":
            return snippet.get("pollDetails", {}).get("prompt", "投票")
        if kind == "messageDeletedEvent":
            return "[コメント削除]"
        if kind == "userBannedEvent":
            d = snippet.get("userBannedDetails", {})
            name = d.get("bannedUserDetails", {}).get("displayName", "")
            return f"[BAN: {name}]"
        return snippet.get("displayMessage", "")

    def roles_str(self) -> str:
        parts = []
        if self.is_owner:     parts.append(ROLE_OWNER)
        if self.is_moderator: parts.append(ROLE_MODERATOR)
        if self.is_member:    parts.append(ROLE_MEMBER)
        if self.is_verified:  parts.append(ROLE_VERIFIED)
        return "/".join(parts)

    def kind_label(self) -> str:
        return EVENT_TYPE_LABELS.get(self.kind, self.kind)

    def recv_time_str(self) -> str:
        return self.recv_time.strftime("%H:%M:%S") if self.recv_time else ""

    def post_time_str(self) -> str:
        if self.post_time is None:
            return ""
        return self.post_time.astimezone().strftime("%H:%M:%S")

    def status_label(self) -> str:
        return PROC_STATUS_LABELS.get(self.proc_status, self.proc_status)

    def body_short(self, max_len: int = 60) -> str:
        b = self.body
        return (b[:max_len] + "…") if len(b) > max_len else b

    def row_tag(self) -> str:
        if self.is_owner:                          return "owner"
        if self.is_moderator:                      return "moderator"
        if self.kind == "superChatEvent":          return "superchat"
        if self.kind == "superStickerEvent":       return "supersticker"
        if self.kind == "messageDeletedEvent":     return "deleted"
        if self.kind == "userBannedEvent":         return "banned"
        if self.filter_match:                      return "matched"
        if self.is_member:                         return "member"
        return "default"


# ════════════════════════════════════════════════════════════════════════════
#  コメントコントローラ
# ════════════════════════════════════════════════════════════════════════════

class CommentController:
    """
    コメント処理の中核。UI 非依存のビジネスロジック層。
    v0.2.0: 固定2接続（conn1/conn2）対応。単一接続互換を維持。
    """
    def __init__(self, root, settings_mgr, base_dir: str):
        self._root = root   # tk.Tk: root.after() によるスレッドセーフ実行用
        self._sm   = settings_mgr

        # データ
        self._comments:    list = []
        self._seq_counter  = 0
        self._msg_id_set:  set  = set()   # "{source_id}:{msg_id}" 形式で重複排除

        # サービス
        self._user_mgr    = UserManager()
        self._filter_mgr  = FilterRuleManager()
        self._tts         = TTSService()
        self._session_log = SessionLogger(base_dir)
        saved_rules = settings_mgr.get("filter_rules", [])
        if saved_rules:
            self._filter_mgr.from_list(saved_rules)

        # 接続クライアント（固定2枠）
        self._yt_clients: dict = {
            "conn1": YouTubeClient(),
            "conn2": YouTubeClient(),
        }

        # 接続状態（per-source）
        self._conn_statuses: dict = {
            "conn1": "disconnected",
            "conn2": "disconnected",
        }
        self._stream_infos: dict = {}   # source_id -> {title, video_id, chat_id, source_name}

        # 旧互換: 単一接続時に参照される情報（conn1 の値を反映）
        self._stream_status  = "unknown"
        self._video_title    = ""
        self._video_id       = ""
        self._live_chat_id   = ""
        self._last_recv_time = None

        # デバッグ
        self._debug_mode           = False
        self._debug_session_active = False

        # UI コールバックリスト
        self._on_comment_added_cbs: list = []   # (item) -> None
        self._on_conn_status_cbs:   list = []   # (status: str) -> None（集約ステータス）
        self._on_source_status_cbs: list = []   # (source_id, status) -> None
        self._on_stream_info_cbs:   list = []   # (title, vid, chat, stream_status) -> None
        self._on_log_cbs:           list = []   # (msg: str) -> None
        self._on_connect_ui_cbs:    list = []   # (conn_en|None, stop_en|None, msg|None, fg|None) -> None
        self._on_debug_mode_cbs:    list = []   # (debug_mode: bool, open_sender: bool) -> None
        self._on_user_cleared_cbs:  list = []   # () -> None

    # プロパティ
    @property
    def user_mgr(self): return self._user_mgr
    @property
    def filter_mgr(self): return self._filter_mgr
    @property
    def comments(self) -> list: return self._comments
    @property
    def conn_status(self) -> str:
        return self._aggregate_conn_status()
    @property
    def video_title(self) -> str: return self._video_title
    @property
    def debug_mode(self) -> bool: return self._debug_mode
    @property
    def last_recv_time(self): return self._last_recv_time
    @property
    def session_log(self): return self._session_log

    def get_conn_statuses(self) -> dict:
        """per-source 接続状態を返す"""
        return dict(self._conn_statuses)

    def is_any_connected(self) -> bool:
        """いずれかの接続が active（receiving/connecting/reconnecting）なら True"""
        return any(
            s not in ("disconnected", "error")
            for s in self._conn_statuses.values()
        )

    def is_multi_conn_active(self) -> bool:
        """2接続とも active なら True"""
        return all(
            self._conn_statuses[sid] not in ("disconnected", "error")
            for sid in ("conn1", "conn2")
        )

    # コールバック登録
    def on_comment_added(self, cb): self._on_comment_added_cbs.append(cb)
    def on_conn_status(self,   cb): self._on_conn_status_cbs.append(cb)
    def on_source_status(self, cb): self._on_source_status_cbs.append(cb)
    def on_stream_info(self,   cb): self._on_stream_info_cbs.append(cb)
    def on_log_message(self,   cb): self._on_log_cbs.append(cb)
    def on_connect_ui(self,    cb): self._on_connect_ui_cbs.append(cb)
    def on_debug_mode(self,    cb): self._on_debug_mode_cbs.append(cb)
    def on_user_cleared(self,  cb): self._on_user_cleared_cbs.append(cb)

    # 公開ログメソッド
    def log(self, msg: str): self._notify_log(msg)

    # サービス委譲
    def verify(self, video_id: str, api_key: str):
        return self._yt_clients["conn1"].verify(video_id, api_key)

    def speak_item(self, item):
        return self._tts.speak_item(item)

    def get_debug_presets(self) -> list:
        from debug_sender import _DEFAULT_PRESETS
        saved = self._sm.get("debug_presets", None)
        return list(_DEFAULT_PRESETS) if saved is None else saved

    def set_debug_presets(self, presets: list) -> None:
        self._sm.update({"debug_presets": presets})

    # コメント追加（統一入口）
    def add_comment(self, raw: dict):
        source_id = raw.get("_source_id", "conn1")
        msg_id    = raw.get("id", "")
        composite_key = f"{source_id}:{msg_id}" if msg_id else ""
        if composite_key and composite_key in self._msg_id_set:
            return None
        if composite_key:
            self._msg_id_set.add(composite_key)

        self._seq_counter += 1
        item = CommentItem(self._seq_counter, raw)
        self._comments.append(item)
        self._last_recv_time = item.recv_time
        self._user_mgr.on_comment(item)
        self.apply_tts_from_settings()
        item.tts_target = self._tts.should_read(item)
        self._tts.enqueue_comment(item)
        rule_matches = self._filter_mgr.evaluate(item, self._user_mgr)
        item.filter_rule_ids = rule_matches
        item.filter_match    = bool(rule_matches)
        if item.filter_match:
            item.proc_status = "matched"
        self._write_session_log(item)
        for cb in self._on_comment_added_cbs:
            cb(item)
        return item

    def _write_session_log(self, item) -> None:
        if not self._session_log.is_open:
            return
        try:
            self._session_log.write(item)
        except Exception as e:
            self._notify_log(f"[ログ保存エラー] {e}")

    # ─── 接続管理 ─────────────────────────────────────────────────────────────

    def connect(self, verify_result: dict, source_id: str = "conn1"):
        """
        1つの接続を開始する。
        verify_result には live_chat_id / title / video_id が含まれる。
        _source_name が含まれていればそれを source_name として使用。
        """
        chat_id     = verify_result["live_chat_id"]
        title       = verify_result.get("title", "")
        video_id    = verify_result.get("video_id", "")
        source_name = (
            verify_result.get("_source_name", "")
            or self._sm.get(f"{source_id}_name", "")
            or SOURCE_DEFAULT_NAMES.get(source_id, source_id)
        )

        self._stream_infos[source_id] = {
            "title": title, "video_id": video_id,
            "chat_id": chat_id, "source_name": source_name,
        }

        # conn1 の場合は旧互換フィールドも更新し、ストリーム情報を通知
        if source_id == "conn1":
            self._debug_session_active = False
            self._notify_stream_info(title, video_id, chat_id, "live")
            try:
                session_dir = self._session_log.open_session(
                    video_id=video_id, live_chat_id=chat_id, title=title
                )
                self._notify_log(f"[セッションログ] 保存先: {session_dir}")
            except Exception as e:
                self._notify_log(f"[セッションログ] 開始失敗（ログなしで続行）: {e}")
            self._user_mgr.clear()
            for cb in self._on_user_cleared_cbs:
                cb()

        self._notify_log(f"[{source_id}] 接続確認 OK — {title} ({source_name}) / chatID: {chat_id}")
        for cb in self._on_connect_ui_cbs:
            cb(False, True, f"受信中... ({source_name})", "#88FF88")

        self._notify_source_status(source_id, "connecting")
        self._yt_clients[source_id].start(
            live_chat_id=chat_id,
            api_key=self._sm.api_key,
            on_comment=lambda raw, sid=source_id, sname=source_name: self._on_yt_comment(raw, sid, sname),
            on_status=lambda status, msg, sid=source_id: self._on_yt_status(sid, status, msg),
        )

    def connect_with_auto_conn2(self, verify_result: dict, source_id: str = "conn1"):
        """
        conn1 を接続した後、conn2 が設定済みなら自動でバックグラウンド接続も試みる。
        rcommenthub.py から呼ばれる。
        """
        self.connect(verify_result, source_id)

        other_id      = "conn2" if source_id == "conn1" else "conn1"
        other_url     = self._sm.get(f"{other_id}_url", "").strip()
        other_enabled = self._sm.get(f"{other_id}_enabled", False)

        if not (other_enabled and other_url):
            return

        other_name = (
            self._sm.get(f"{other_id}_name", "")
            or SOURCE_DEFAULT_NAMES.get(other_id, other_id)
        )
        self._notify_log(f"[{other_id}] 自動接続を開始します: {other_url}")

        def _auto_connect():
            try:
                video_id = _extract_video_id(other_url)
                result = self._yt_clients["conn1"].verify(video_id, self._sm.api_key)
                result["_source_name"] = other_name
                self._root.after(0, lambda r=result: self.connect(r, other_id))
            except Exception as e:
                self._root.after(
                    0,
                    lambda msg=str(e): self._notify_log(f"[{other_id}] 自動接続失敗: {msg}")
                )

        threading.Thread(target=_auto_connect, daemon=True).start()

    def disconnect(self):
        """全接続のポーリングを停止する"""
        for client in self._yt_clients.values():
            client.stop()
        self._notify_log("[停止] 全接続の受信停止リクエスト送信")

    def _on_yt_comment(self, raw: dict, source_id: str, source_name: str):
        raw["_source_id"]   = source_id
        raw["_source_name"] = source_name
        self._root.after(0, lambda r=raw: self.add_comment(r))

    def _on_yt_status(self, source_id: str, status: str, message: str):
        def _apply():
            self._notify_source_status(source_id, status)
            self._notify_log(f"[{source_id}] {message}")

            if status in ("disconnected", "error"):
                color = "#FF6666" if status == "error" else "#AAAAAA"
                # 他のすべての接続も非active になったらUIを停止状態にする
                all_done = all(
                    s in ("disconnected", "error")
                    for s in self._conn_statuses.values()
                )
                if all_done:
                    for cb in self._on_connect_ui_cbs:
                        cb(True, False, message, color)
                    if self._session_log.is_open:
                        self._session_log.close(user_snapshot=self._user_mgr.snapshot())
                        self._notify_log("[セッションログ] 保存完了")
            elif status == "reconnecting":
                for cb in self._on_connect_ui_cbs:
                    cb(None, None, f"[{source_id}] {message}", "#FFCC44")
            elif status == "receiving":
                for cb in self._on_connect_ui_cbs:
                    cb(None, None, f"[{source_id}] 受信中", "#88FF88")
        self._root.after(0, _apply)

    # ─── デバッグモード ───────────────────────────────────────────────────────

    def toggle_debug_mode(self):
        self._debug_mode = not self._debug_mode
        open_sender = self._debug_mode
        if self._debug_mode:
            if not self._session_log.is_open:
                self.start_debug_session()
        else:
            if self._debug_session_active:
                self._session_log.close(user_snapshot=self._user_mgr.snapshot())
                self._debug_session_active = False
                self._notify_log("[デバッグ] セッション終了")
            if self.conn_status == "debug":
                self._notify_source_status("conn1", "disconnected")
        for cb in self._on_debug_mode_cbs:
            cb(self._debug_mode, open_sender)

    def start_debug_session(self):
        try:
            session_dir = self._session_log.open_session(
                video_id="debug", live_chat_id="debug", title="[デバッグセッション]",
            )
            self._debug_session_active = True
            self._notify_log(f"[デバッグ] セッション開始: {session_dir}")
            self._notify_source_status("conn1", "debug")
        except Exception as e:
            self._notify_log(f"[デバッグ] セッション開始失敗: {e}")

    # ─── TTS ─────────────────────────────────────────────────────────────────

    def apply_tts_from_settings(self):
        sm = self._sm
        self._tts.enabled            = sm.get("tts_enabled",          False)
        self._tts.simplify_name      = sm.get("tts_simplify_name",    True)
        self._tts.read_source_name   = sm.get("tts_read_source_name", False)
        self._tts.set_filter(
            normal    = sm.get("tts_normal",    True),
            superchat = sm.get("tts_superchat", True),
            owner     = sm.get("tts_owner",     True),
            moderator = sm.get("tts_mod",       True),
            member    = sm.get("tts_member",    False),
        )

    # ─── シャットダウン ───────────────────────────────────────────────────────

    def shutdown(self, cfg: dict):
        self._sm.update({"filter_rules": self._filter_mgr.to_list()})
        if self._session_log.is_open:
            self._session_log.close(user_snapshot=self._user_mgr.snapshot())
        for client in self._yt_clients.values():
            client.stop()
        self._sm.update(cfg)

    # ─── 内部通知 ─────────────────────────────────────────────────────────────

    def _aggregate_conn_status(self) -> str:
        statuses = list(self._conn_statuses.values())
        if "receiving"    in statuses: return "receiving"
        if "connecting"   in statuses: return "connecting"
        if "reconnecting" in statuses: return "reconnecting"
        if "debug"        in statuses: return "debug"
        if "error"        in statuses: return "error"
        return "disconnected"

    def _notify_source_status(self, source_id: str, status: str):
        self._conn_statuses[source_id] = status
        for cb in self._on_source_status_cbs:
            cb(source_id, status)
        agg = self._aggregate_conn_status()
        for cb in self._on_conn_status_cbs:
            cb(agg)

    def _notify_stream_info(self, title, video_id, chat_id, stream_status):
        self._video_title   = title
        self._video_id      = video_id
        self._live_chat_id  = chat_id
        self._stream_status = stream_status
        for cb in self._on_stream_info_cbs:
            cb(title, video_id, chat_id, stream_status)

    def _notify_log(self, msg: str):
        for cb in self._on_log_cbs:
            cb(msg)
