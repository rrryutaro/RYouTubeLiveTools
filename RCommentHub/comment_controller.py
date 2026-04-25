"""
RCommentHub — コメントコントローラ

コメント処理の中核。UI 非依存のビジネスロジック層。
v0.2.0: 固定2接続（conn1/conn2）同時表示対応
"""

import datetime
import json
import logging
import threading
import urllib.request

_log = logging.getLogger("comment_controller")

from tts_service import TTSService
from tts_name import make_tts_name
from youtube_client import YouTubeClient
from auth_service import AuthService, AUTH_MODE_OAUTH, AUTH_MODE_API_KEY
from user_manager import UserManager
from filter_rules import FilterRuleManager
from session_logger import SessionLogger
from source_adapter import YouTubeSourceAdapter
from constants import (
    EVENT_TYPE_LABELS, PROC_STATUS_LABELS,
    ROLE_OWNER, ROLE_MODERATOR, ROLE_MEMBER, ROLE_VERIFIED,
    SOURCE_DEFAULT_NAMES, get_profile_color,
    INPUT_SOURCE_DEBUG,
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

        self.source: str          = raw.get("_source", "live_youtube")
        self.source_id: str       = raw.get("_source_id", "conn1")
        self.source_name: str     = raw.get("_source_name", "")
        self.tts_source_name: str = raw.get("_tts_source_name", self.source_name)
        self.is_system_message: bool = raw.get("_is_system_message", False)

        self.author_display_name_tts: str  = make_tts_name(self.author_name)
        self.filter_match:            bool  = False
        self.filter_rule_ids:         list  = []
        self.tts_target:              bool  = False

        # i112: RRoulette送信状態
        self.roulette_send_status: str  = "未判定"   # 未判定/送信中/送信済み/手動送信済み/除外/失敗
        self.roulette_send_reason: str  = ""          # 除外・失敗の理由
        self.roulette_sent_at                = None   # 送信成功時刻 (datetime)
        self.roulette_send_error: str   = ""          # 失敗時のエラー詳細

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
        if self.is_system_message:                 return "system"
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
    v0.3.x: 接続プロファイル配列管理 + SourceAdapter 層 (YouTube / Twitch 対応)
    v0.4.0: dispatch_to_main 注入方式へ変更（Tk 直接依存を排除）
    """
    def __init__(self, dispatch_to_main, settings_mgr, base_dir: str):
        # メインスレッドへのディスパッチ関数（ワーカースレッドからの安全な呼び出し用）
        # Tk: lambda cb: root.after(0, cb)
        # PySide6: _MainThreadDispatcher.dispatch（Signal/Slot QueuedConnection）
        self._dispatch = dispatch_to_main
        self._sm   = settings_mgr

        # データ
        self._comments:    list = []
        self._seq_counter  = 0
        self._msg_id_set:  set  = set()   # "{source_id}:{msg_id}" 形式で重複排除

        # 認証サービス（YouTube OAuth / API キー二系統）
        import os
        self._base_dir = base_dir
        token_path = os.path.join(base_dir, "token.json")
        self._auth_service = AuthService(token_path=token_path)
        # client_secrets.json を base_dir から自動ロード（起動時）
        secrets_loaded = self._auth_service.try_load_client_secrets_from_dir(base_dir)
        self._apply_auth_from_settings()
        if secrets_loaded:
            self._pending_log = "[認証] client_secrets.json をロードしました"
        else:
            self._pending_log = None

        # Twitch 認証サービス
        from twitch_auth_service import TwitchAuthService
        self._twitch_auth = TwitchAuthService(settings_mgr)

        # サービス
        self._user_mgr    = UserManager()
        self._filter_mgr  = FilterRuleManager()
        self._tts         = TTSService()
        self._session_log = SessionLogger(base_dir)
        saved_rules = settings_mgr.get("filter_rules", [])
        if saved_rules:
            self._filter_mgr.from_list(saved_rules)
        # i110: 保存済みユーザーフラグを復元
        saved_flags = settings_mgr.get("user_flags", {})
        if saved_flags:
            self._user_mgr.load_saved_flags(saved_flags)

        # 接続アダプタ（profile_id -> SourceAdapter）
        self._adapters: dict = {}

        # 接続状態（profile_id -> status）
        self._conn_statuses: dict = {}

        # ストリーム情報（profile_id -> {title, video_id, chat_id, source_name}）
        self._stream_infos: dict = {}

        # 旧互換: 最初に接続したプロファイルの情報を反映
        self._stream_status  = "unknown"
        self._video_title    = ""
        self._video_id       = ""
        self._live_chat_id   = ""
        self._last_recv_time = None

        # デバッグ
        self._debug_mode           = False
        self._debug_session_active = False
        # デバッグ用に固定の conn1 ステータスを保持（旧互換）
        self._conn_statuses["conn1"] = "disconnected"

        # UI コールバックリスト
        self._on_comment_added_cbs: list = []   # (item) -> None
        self._on_conn_status_cbs:   list = []   # (status: str) -> None（集約ステータス）
        self._on_source_status_cbs: list = []   # (source_id, status) -> None
        self._on_stream_info_cbs:   list = []   # (title, vid, chat, stream_status) -> None
        self._on_log_cbs:           list = []   # (msg: str) -> None
        self._on_connect_ui_cbs:    list = []   # (conn_en|None, stop_en|None, msg|None, fg|None) -> None
        self._on_debug_mode_cbs:    list = []   # (debug_mode: bool, open_sender: bool) -> None
        self._on_user_cleared_cbs:  list = []   # () -> None
        self._on_roulette_status_cbs: list = [] # i112: (item) -> None

    # プロパティ
    @property
    def auth_service(self) -> AuthService:
        return self._auth_service

    @property
    def twitch_auth(self):
        return self._twitch_auth

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

    def get_profiles(self) -> list:
        """現在の接続プロファイルリストを返す"""
        return self._sm.get_connection_profiles()

    def is_any_connected(self) -> bool:
        """いずれかの接続が active（receiving/connecting/reconnecting）なら True"""
        return any(
            s not in ("disconnected", "error")
            for s in self._conn_statuses.values()
        )

    def is_multi_conn_active(self) -> bool:
        """2つ以上のプロファイルが active なら True"""
        active_count = sum(
            1 for s in self._conn_statuses.values()
            if s not in ("disconnected", "error", "debug")
        )
        return active_count >= 2

    # コールバック登録
    def on_comment_added(self, cb): self._on_comment_added_cbs.append(cb)
    def on_conn_status(self,   cb): self._on_conn_status_cbs.append(cb)
    def on_source_status(self, cb): self._on_source_status_cbs.append(cb)
    def on_stream_info(self,   cb): self._on_stream_info_cbs.append(cb)
    def on_log_message(self,   cb): self._on_log_cbs.append(cb)
    def on_connect_ui(self,    cb): self._on_connect_ui_cbs.append(cb)
    def on_debug_mode(self,    cb): self._on_debug_mode_cbs.append(cb)
    def on_user_cleared(self,  cb): self._on_user_cleared_cbs.append(cb)
    def on_roulette_status(self, cb): self._on_roulette_status_cbs.append(cb)  # i112

    # i113: RRoulette 送信状態ヘルパー
    def _set_roulette_status(self, item, status, *,
                              reason: str = "", error: str = "", sent_at=None) -> None:
        """送信状態を item に設定し、全 UI コールバックへ通知する（メインスレッドから呼ぶこと）。"""
        item.roulette_send_status = status
        item.roulette_send_reason = reason
        item.roulette_send_error  = error
        if sent_at is not None:
            item.roulette_sent_at = sent_at
        for cb in self._on_roulette_status_cbs:
            cb(item)

    def update_roulette_status(self, item, status, *,
                                reason: str = "", error: str = "", sent_at=None) -> None:
        """外部（UI 層）から送信状態を更新してコールバックで通知する。"""
        self._set_roulette_status(item, status, reason=reason, error=error, sent_at=sent_at)

    def build_roulette_payload(self, item, *, matched_rule_name: str = "") -> dict:
        """RRoulette へ送信する payload を生成する（手動・自動送信共用）。"""
        filter_name = matched_rule_name or (
            ", ".join(item.filter_rule_ids) if getattr(item, "filter_rule_ids", None) else ""
        )
        source = getattr(item, "source", "") or ""
        platform = source.replace("live_", "") if source else ""
        return {
            "source_app":        "RCommentHub",
            "platform":          platform,
            "profile_name":      getattr(item, "source_name", "") or "",
            "filter_name":       filter_name,
            "author_name":       getattr(item, "author_name", "") or "",
            "author_channel_id": getattr(item, "channel_id", "") or "",
            "comment_text":      getattr(item, "body", "") or "",
            "message_type":      "filter_match",
            "received_at":       item.recv_time.isoformat() if getattr(item, "recv_time", None) else "",
        }

    # 公開ログメソッド
    def log(self, msg: str): self._notify_log(msg)

    def flush_pending_logs(self):
        """起動直後のペンディングログをログコールバックへ出力する"""
        if self._pending_log:
            self._notify_log(self._pending_log)
            self._pending_log = None

    # 認証設定の適用
    def _resolve_auth_mode(self) -> str:
        """
        設定から認証モードを解決する（移行ロジック込み）。

        優先順位:
          1. 設定に auth_mode が保存済み → その値を使う
          2. 未保存かつ API キーが保存済み → api_key（既存利用者の後方互換）
          3. 未保存かつ API キーも未保存 → oauth（新規利用者向け既定値）
        """
        saved_mode = self._sm.get("auth_mode", None)
        if saved_mode is not None:
            return saved_mode
        if self._sm.api_key:
            return AUTH_MODE_API_KEY
        return AUTH_MODE_OAUTH

    def _apply_auth_from_settings(self):
        """設定から認証モードと認証情報を AuthService に反映する"""
        mode = self._resolve_auth_mode()
        self._auth_service.mode    = mode
        self._auth_service.api_key = self._sm.api_key
        # OAuth モード時: 保存済みトークンをロード
        if mode == AUTH_MODE_OAUTH:
            self._auth_service.load_token()

    def apply_auth_from_settings(self):
        """外部から呼び出し可能な設定再適用メソッド"""
        self._apply_auth_from_settings()

    # サービス委譲
    def verify(self, video_id: str, api_key: str = ""):
        """YouTube 動画IDの確認（後方互換）。AuthService を使用する。"""
        client = YouTubeClient()
        client.set_auth_service(self._auth_service)
        return client.verify(video_id, api_key)

    def verify_target(self, platform: str, url: str) -> dict:
        """
        プラットフォームを指定して接続先を検証する。
        platform: "youtube" | "twitch"
        url: YouTube URL / Twitch チャンネル名 等
        """
        if platform == "youtube":
            return self.verify(_extract_video_id(url))
        elif platform == "twitch":
            from twitch_client import TwitchSourceAdapter
            adapter = TwitchSourceAdapter(self._twitch_auth)
            return adapter.verify_target(url)
        else:
            raise ValueError(f"未対応プラットフォーム: {platform}")

    def speak_item(self, item):
        return self._tts.speak_item(item)

    @property
    def tts_enabled(self) -> bool:
        """TTS が有効かどうかを返す"""
        return self._tts.enabled

    def set_tts_on_speak(self, callback):
        """TTS 読み上げ開始時に呼ばれるコールバックを設定する（Overlay 同期用）"""
        self._tts.set_on_speak(callback)

    def set_tts_on_spoken(self, callback):
        """TTS 読み上げ完了時に呼ばれるコールバックを設定する（Overlay 消去タイマー用）"""
        self._tts.set_on_spoken(callback)

    def get_debug_presets(self) -> list:
        from debug_sender import _DEFAULT_PRESETS
        saved = self._sm.get("debug_presets", None)
        return list(_DEFAULT_PRESETS) if saved is None else saved

    def set_debug_presets(self, presets: list) -> None:
        self._sm.update({"debug_presets": presets})

    # コメント追加（統一入口）
    def add_comment(self, raw: dict):
        _log.info("add_comment: source=%s author=%s body=%.40s",
                  raw.get("_source_id", "?"),
                  raw.get("authorDetails", {}).get("displayName", "?"),
                  raw.get("snippet", {}).get("displayMessage", ""))
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
        # バックログは TTS 対象外
        # システムメッセージは tts_system_message 設定が ON のときのみ読み上げ
        is_backlog  = raw.get("_is_backlog", False)
        is_system   = raw.get("_is_system_message", False)
        if is_backlog:
            item.tts_target = False
        elif is_system:
            tts_sys_enabled = (
                self._tts.enabled
                and bool(self._sm.get("tts_system_message", True))
            )
            if tts_sys_enabled:
                item.tts_target = True
                self._tts.enqueue_comment(item)
            else:
                item.tts_target = False
        else:
            item.tts_target = self._tts.should_read(item)
            self._tts.enqueue_comment(item)
        _log.info("add_comment: is_backlog=%s tts_target=%s author=%s",
                  is_backlog, item.tts_target, item.author_name[:30])
        rule_matches = self._filter_mgr.evaluate(item, self._user_mgr)
        item.filter_rule_ids = rule_matches
        item.filter_match    = bool(rule_matches)
        if item.filter_match:
            item.proc_status = "matched"
        # i111: filter_match に関わらず呼ぶ（関数内でフィルタ状態を判断）
        self._notify_roulette_link(item)
        self._write_session_log(item)
        _log.info("add_comment: UI コールバックへ渡す (cbs=%d)", len(self._on_comment_added_cbs))
        for cb in self._on_comment_added_cbs:
            cb(item)
        return item

    def _notify_roulette_link(self, item) -> None:
        """コメントを RRoulette へ HTTP POST で自動送信する (Phase 1)。

        - 送信先: 127.0.0.1:{port}/api/link-message
        - 送信失敗 (RRoulette 未起動・接続拒否等) は握りつぶして処理続行
        i113: _set_roulette_status() で除外時もUI通知統一。dry_run対応。
              rr_auto_send_debug_enabled ONの場合、デバッグコメントも通常判定へ進む。
              build_roulette_payload() で手動・自動のpayload形式を統一。
        """
        # デバッグコメント判定
        is_debug = getattr(item, 'source', '') == INPUT_SOURCE_DEBUG
        if is_debug:
            debug_enabled = bool(self._sm.get("rr_auto_send_debug_enabled", False))
            if not debug_enabled:
                self._set_roulette_status(item, "除外", reason="デバッグ")
                _log.debug("_notify_roulette_link: skip debug source")
                return
            # debug_enabled=True → 通常判定へ進む

        cfg = self._sm.get("roulette_integration", {})
        if not cfg.get("enabled", False):
            self._set_roulette_status(item, "除外", reason="連携送信OFF")
            return

        auto_mode = self._sm.get("rr_auto_send_mode", "off")
        _log.debug("_notify_roulette_link: author=%s mode=%s filter_match=%s",
                   item.author_name[:20], auto_mode, item.filter_match)
        if auto_mode == "off":
            self._set_roulette_status(item, "除外", reason="自動送信OFF")
            return

        # dry_run チェック（手動送信と統一: roulette_integration.dry_run を参照）
        dry_run = bool(cfg.get("dry_run", False))
        if dry_run:
            self._set_roulette_status(item, "dry-run", reason="dry_run ON")
            _log.info("_notify_roulette_link: dry-run author=%s mode=%s", item.author_name[:20], auto_mode)
            return

        # フィルタ一致チェックは "filter_match" モード専用
        if auto_mode == "filter_match":
            if not item.filter_match:
                self._set_roulette_status(item, "除外", reason="フィルタ不一致")
                _log.debug("_notify_roulette_link: skip filter_match=False in filter_match mode")
                return

        # ブラックリスト最優先除外（全モード共通）
        cid = item.channel_id or item.author_name
        if cid and self._user_mgr.is_blacklisted(cid):
            self._set_roulette_status(item, "除外", reason="ブラック指定")
            _log.debug("_notify_roulette_link: skip blacklisted: %s", (cid or "")[:20])
            return

        # ホワイト/対象者フィルタ
        if auto_mode == "whitelist":
            rec = self._user_mgr.get(cid) if cid else None
            if rec is None or not rec.is_whitelist:
                self._set_roulette_status(item, "除外", reason="ホワイト未指定")
                return
        elif auto_mode == "target":
            rec = self._user_mgr.get(cid) if cid else None
            if rec is None or not rec.is_filter_target:
                self._set_roulette_status(item, "除外", reason="対象者未指定")
                return
        # "all" / "filter_match" (通過済み) はブラック除外のみで通過

        port = int(cfg.get("port", 12345))
        url  = f"http://127.0.0.1:{port}/api/link-message"
        payload = self.build_roulette_payload(item)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # 送信開始をUIへ通知
        self._set_roulette_status(item, "送信中")
        _log.info("_notify_roulette_link: 自動送信 author=%s mode=%s filter=%s port=%d",
                  item.author_name[:20], auto_mode, item.filter_match, port)

        def _post():
            try:
                req = urllib.request.Request(
                    url, data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=1.0):
                    pass
                def _ok():
                    self._set_roulette_status(item, "送信済み",
                                              sent_at=datetime.datetime.now())
                    _log.info("_notify_roulette_link: 送信成功 author=%s", item.author_name[:20])
                self._dispatch(_ok)
            except OSError:
                def _fail_os():
                    self._set_roulette_status(item, "失敗", error="RRoulette未起動")
                    _log.debug("_notify_roulette_link: RRoulette not reachable (port=%d)", port)
                self._dispatch(_fail_os)
            except Exception as e:
                _err = str(e)[:60]
                def _fail_ex():
                    self._set_roulette_status(item, "失敗", error=_err)
                    _log.warning("_notify_roulette_link: error: %s", _err)
                self._dispatch(_fail_ex)

        threading.Thread(target=_post, daemon=True, name="RouletteLinkPost").start()

    def test_roulette_link(self, item) -> None:
        """i112: テスト用 — debug source チェックをバイパスして自動送信経路を通す。
        デバッグコメントで自動送信フローを確認する際に使用する。
        """
        original_source = item.source
        # debug_manual を live_youtube に偽装してルート全体を通す
        item.source = "live_youtube"
        item.roulette_send_status = "未判定"
        item.roulette_send_reason = ""
        item.roulette_send_error  = ""
        try:
            self._notify_roulette_link(item)
        finally:
            item.source = original_source

    def _write_session_log(self, item) -> None:
        if not self._session_log.is_open:
            return
        try:
            self._session_log.write(item)
        except Exception as e:
            self._notify_log(f"[ログ保存エラー] {e}")

    # ─── 接続管理 ─────────────────────────────────────────────────────────────

    def connect_profile(self, profile_id: str, verify_result: dict):
        """
        指定プロファイルの接続を開始する。
        verify_result には title / live_chat_id / video_id 等が含まれる。
        """
        profiles    = self._sm.get_connection_profiles()
        profile     = next((p for p in profiles if p["profile_id"] == profile_id), None)
        platform    = profile.get("platform", "youtube") if profile else "youtube"
        source_name = (
            verify_result.get("_source_name", "")
            or (profile.get("overlay_name", profile.get("display_name", "")) if profile else "")
            or profile_id
        )
        tts_source_name = (
            verify_result.get("_tts_source_name", "")
            or (profile.get("tts_name", profile.get("display_name", "")) if profile else "")
            or source_name
        )
        title    = verify_result.get("title", "")
        video_id = verify_result.get("video_id", verify_result.get("broadcaster_id", ""))
        chat_id  = verify_result.get("live_chat_id", "")

        self._stream_infos[profile_id] = {
            "title": title, "video_id": video_id,
            "chat_id": chat_id, "source_name": source_name,
            "platform": platform,
        }

        # 最初のアクティブ接続の場合はセッションログとストリーム情報を更新
        if not self.is_any_connected():
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

        plat_label = "Twitch" if platform == "twitch" else "YouTube"
        self._notify_log(
            f"[{profile_id}] 接続確認 OK — {title} ({source_name}) [{plat_label}]"
        )
        for cb in self._on_connect_ui_cbs:
            cb(False, True, f"受信中... ({source_name})", "#88FF88")

        self._notify_source_status(profile_id, "connecting")

        # プロファイルに対応するアダプタを生成
        adapter = self._create_adapter(platform)
        adapter.set_verify_result(verify_result) if hasattr(adapter, "set_verify_result") else None
        if platform == "twitch":
            # Twitch は verify_result を直接アダプタに保持させる
            adapter._verify_result = verify_result
        self._adapters[profile_id] = adapter

        def _on_comment(raw, pid=profile_id, sname=source_name, tname=tts_source_name):
            raw["_source_id"]       = pid
            raw["_source_name"]     = sname
            raw["_tts_source_name"] = tname
            self._dispatch(lambda r=raw: self.add_comment(r))

        def _on_status(status, msg, pid=profile_id):
            self._dispatch(lambda: self._on_adapter_status(pid, status, msg))

        def _on_system_message(text, pid=profile_id):
            self._dispatch(lambda: self._inject_system_message(pid, text))

        adapter.connect(
            on_comment=_on_comment,
            on_status=_on_status,
            polling_fallback_allowed=bool(self._sm.get("youtube_polling_fallback_enabled", False)),
            on_system_message=_on_system_message,
            notify_overlay=bool(self._sm.get("youtube_disconnect_notify_overlay", False)),
        )

    def _create_adapter(self, platform: str):
        """プラットフォームに対応するアダプタを生成する"""
        if platform == "twitch":
            from twitch_client import TwitchSourceAdapter
            return TwitchSourceAdapter(self._twitch_auth)
        else:
            return YouTubeSourceAdapter(self._auth_service)

    def connect(self, verify_result: dict, source_id: str = "conn1"):
        """
        後方互換メソッド。source_id を profile_id として connect_profile を呼ぶ。
        """
        self.connect_profile(source_id, verify_result)

    def connect_with_auto_conn2(self, verify_result: dict, source_id: str = "conn1"):
        """
        後方互換メソッド。
        指定プロファイルを接続し、他の enabled プロファイルを自動接続する。
        """
        self.connect_all_enabled_after(verify_result, source_id)

    def connect_all_enabled_after(self, verify_result: dict, profile_id: str):
        """
        指定プロファイルを接続し、他の enabled なプロファイルを自動接続する。
        """
        self.connect_profile(profile_id, verify_result)

        profiles = self._sm.get_connection_profiles()
        for p in profiles:
            pid = p.get("profile_id", "")
            if pid == profile_id:
                continue
            if not p.get("enabled", False):
                continue
            url = p.get("target_url", "").strip()
            if not url:
                continue
            self._auto_connect_profile(p)

    def _auto_connect_profile(self, profile: dict):
        """バックグラウンドで1プロファイルを自動接続する"""
        profile_id = profile["profile_id"]
        platform   = profile.get("platform", "youtube")
        url        = profile.get("target_url", "").strip()
        name     = profile.get("overlay_name", profile.get("display_name", profile_id))
        tts_name = profile.get("tts_name",    profile.get("display_name", name))
        self._notify_log(f"[{profile_id}] 自動接続を開始します: {url} ({platform})")

        def _work():
            try:
                result = self.verify_target(platform, url)
                result["_source_name"]    = name
                result["_tts_source_name"] = tts_name
                self._dispatch(lambda r=result: self.connect_profile(profile_id, r))
            except Exception as e:
                self._dispatch(
                    lambda msg=str(e): self._notify_log(f"[{profile_id}] 自動接続失敗: {msg}")
                )

        threading.Thread(target=_work, daemon=True).start()

    def disconnect(self):
        """全接続のアダプタを停止する"""
        for adapter in self._adapters.values():
            try:
                adapter.disconnect()
            except Exception:
                pass
        self._notify_log("[停止] 全接続の受信停止リクエスト送信")

    def _on_adapter_status(self, profile_id: str, status: str, message: str):
        """アダプタからの状態変化通知を処理する（メインスレッドで実行）"""
        self._notify_source_status(profile_id, status)
        self._notify_log(f"[{profile_id}] {message}")

        if status in ("disconnected", "error"):
            color = "#FF6666" if status == "error" else "#AAAAAA"
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
                cb(None, None, f"[{profile_id}] {message}", "#FFCC44")
        elif status == "receiving":
            for cb in self._on_connect_ui_cbs:
                cb(None, None, f"[{profile_id}] 受信中", "#88FF88")

    # ─── システムメッセージ注入 ───────────────────────────────────────────────

    def _inject_system_message(self, profile_id: str, text: str):
        """
        切断通知などのシステムメッセージをコメントリストへ注入する（メインスレッドで呼ぶ）。
        TTS 対象外、バックログ扱い外。Overlay への表示は呼び出し元設定で制御する。
        """
        import time as _time
        raw = {
            "id": f"_sys_{int(_time.time() * 1000)}",
            "_source_id":         profile_id,
            "_source_name":       "System",
            "_tts_source_name":   "",
            "_is_system_message": True,
            "_is_backlog":        False,
            "snippet": {
                "type":           "systemMessageEvent",
                "displayMessage": text,
                "publishedAt":    datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            "authorDetails": {
                "displayName":    "[System]",
                "channelId":      "_system",
                "channelUrl":     "",
                "profileImageUrl": "",
                "isChatOwner":    False,
                "isChatModerator": False,
                "isChatSponsor":  False,
                "isVerified":     False,
            },
        }
        self.add_comment(raw)

    # ─── fallback 許可確認（後方互換保持・現在は connect_profile から呼ばれない） ──

    def _ask_fallback_permission(self, reason: str) -> bool:
        """
        streamList 失敗時に list fallback を許可するかをユーザーへ確認する。
        ワーカースレッドから呼ばれ、ユーザーが応答するまでブロックする。
        """
        import tkinter.messagebox as mb

        reason_text = {
            "stream_completed": "接続が終了",
            "stream_failed":    "接続失敗",
        }.get(reason, reason)

        event  = threading.Event()
        result = [False]

        def _show_dialog():
            answer = mb.askyesno(
                title="streamList 継続受信に失敗",
                message=(
                    f"streamList による継続受信に失敗しました（{reason_text}）。\n\n"
                    "今回のみ list 方式へ切り替えますか？"
                ),
            )
            result[0] = bool(answer)
            event.set()

        self._dispatch(_show_dialog)
        event.wait(timeout=60)   # 60秒応答なし → 拒否扱い
        return result[0]

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

    # ─── 設定反映 ─────────────────────────────────────────────────────────────

    def apply_tts_from_settings(self):
        sm = self._sm
        self._tts.enabled            = sm.get("tts_enabled",          False)
        self._tts.volume             = sm.get("tts_volume",            100)
        self._tts.simplify_name      = sm.get("tts_simplify_name",    True)
        self._tts.read_source_name   = sm.get("tts_read_source_name", False)
        self._tts.interval_sec       = float(sm.get("tts_interval_sec", 0))
        self._tts.speed              = int(sm.get("tts_speed",         0))
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
        for adapter in self._adapters.values():
            try:
                adapter.disconnect()
            except Exception:
                pass
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
