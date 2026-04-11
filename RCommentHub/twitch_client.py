"""
RCommentHub — Twitch コメント取得クライアント + アダプタ

Twitch EventSub WebSocket を使ってチャットコメントを取得する。

規約準拠:
  - Twitch 公式 EventSub WebSocket を使用
  - 公式 Helix API のみ使用（スクレイピング・非公式 API は使用しない）
  - OAuth ユーザーアクセストークンを正規経路で取得・使用する

接続フロー:
  1. wss://eventsub.wss.twitch.tv/ws に WebSocket 接続
  2. session_welcome メッセージから session_id を取得
  3. Helix API で channel.chat.message を購読
  4. notification メッセージからコメントを受信
  5. session_reconnect / revocation を適切に処理
"""

import datetime
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_logger = logging.getLogger(__name__)

# ─── エンドポイント ────────────────────────────────────────────────────────────
HELIX_USERS_URL       = "https://api.twitch.tv/helix/users"
HELIX_STREAMS_URL     = "https://api.twitch.tv/helix/streams"
HELIX_EVENTSUB_URL    = "https://api.twitch.tv/helix/eventsub/subscriptions"
EVENTSUB_WS_URL       = "wss://eventsub.wss.twitch.tv/ws"

# ─── 接続状態定数 ─────────────────────────────────────────────────────────────
STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTING   = "connecting"
STATUS_RECEIVING    = "receiving"
STATUS_RECONNECTING = "reconnecting"
STATUS_ERROR        = "error"

# keepalive タイムアウト（秒）: Twitch は 10 秒ごとに keepalive を送る
KEEPALIVE_TIMEOUT = 30


class TwitchClientError(Exception):
    pass


class TwitchClient:
    """
    Twitch EventSub WebSocket クライアント。

    別スレッドで動作する。UI コールバックは呼び出し元で root.after() して使うこと。
    """

    def __init__(self, auth_service):
        """
        auth_service: TwitchAuthService インスタンス
        """
        self._auth   = auth_service
        self._stop_event   = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_comment   = None
        self._on_status    = None
        self._broadcaster_id:    str = ""
        self._broadcaster_login: str = ""
        self._broadcaster_name:  str = ""

    # ─── 接続確認（同期） ─────────────────────────────────────────────────────

    def verify(self, url: str) -> dict:
        """
        Twitch URL またはチャンネル名から接続情報を取得する（同期）。

        対応入力:
          - https://www.twitch.tv/<login>
          - https://twitch.tv/<login>
          - <login>

        成功時:
          {
            "title":          str,     # 配信タイトル（オフライン時は空）
            "broadcaster_id": str,     # ユーザーID
            "login":          str,     # ログイン名
            "display_name":   str,     # 表示名
            "is_live":        bool,    # ライブ中か
          }

        失敗時は TwitchClientError を raise する。
        """
        if not self._auth.is_authenticated():
            raise TwitchClientError("Twitch の認証が必要です。設定ウィンドウから認証してください。")

        login = self._extract_login(url)
        if not login:
            raise TwitchClientError("Twitch チャンネル名を取得できませんでした。")

        # ユーザー情報取得
        user_info = self._fetch_user(login)
        broadcaster_id    = user_info["id"]
        broadcaster_login = user_info["login"]
        broadcaster_name  = user_info["display_name"]

        # ライブ状態確認
        stream_info = self._fetch_stream(broadcaster_id)
        is_live = stream_info is not None
        title   = stream_info["title"] if is_live else ""

        if not is_live:
            raise TwitchClientError(
                f"@{broadcaster_login} はただいまオフラインです。ライブ中の配信に接続してください。"
            )

        return {
            "title":          title,
            "broadcaster_id": broadcaster_id,
            "login":          broadcaster_login,
            "display_name":   broadcaster_name,
            "is_live":        True,
            # CommentController との互換用
            "live_chat_id":   broadcaster_id,
            "video_id":       broadcaster_id,
        }

    @staticmethod
    def _extract_login(url: str) -> str:
        """Twitch URL またはチャンネル名からログイン名を抽出する"""
        url = url.strip()
        if not url:
            return ""
        # URL 形式
        if "twitch.tv/" in url:
            try:
                parsed = urllib.parse.urlparse(url)
                parts  = [p for p in parsed.path.split("/") if p]
                if parts:
                    return parts[0].lower()
            except Exception:
                pass
        # ログイン名直接入力（英数字 + _）
        if url.replace("_", "").replace("-", "").isalnum():
            return url.lower()
        return ""

    def _fetch_user(self, login: str) -> dict:
        """Helix Users API でユーザー情報を取得する"""
        kwargs = self._auth.get_request_kwargs()
        url    = HELIX_USERS_URL + "?" + urllib.parse.urlencode({"login": login})
        req    = urllib.request.Request(url, headers=kwargs.get("headers", {}))
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise TwitchClientError(f"Twitch API エラー (HTTP {e.code}): {e.reason}")
        except Exception as e:
            raise TwitchClientError(f"通信エラー: {e}")

        users = data.get("data", [])
        if not users:
            raise TwitchClientError(f"Twitch チャンネル「{login}」が見つかりません。")
        return users[0]

    def _fetch_stream(self, user_id: str) -> dict | None:
        """Helix Streams API でライブ状態を確認する。オフライン時は None を返す"""
        kwargs = self._auth.get_request_kwargs()
        url    = HELIX_STREAMS_URL + "?" + urllib.parse.urlencode({"user_id": user_id})
        req    = urllib.request.Request(url, headers=kwargs.get("headers", {}))
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception:
            return None
        streams = data.get("data", [])
        return streams[0] if streams else None

    # ─── 受信開始 ─────────────────────────────────────────────────────────────

    def start(self, broadcaster_id: str, broadcaster_login: str, broadcaster_name: str,
              on_comment=None, on_status=None):
        """
        コメント受信を別スレッドで開始する。
        on_comment(raw: dict): コメント1件ごと（ワーカースレッド文脈）
        on_status(status, msg): 状態変化時（ワーカースレッド文脈）
        """
        if self._thread and self._thread.is_alive():
            return
        self._broadcaster_id    = broadcaster_id
        self._broadcaster_login = broadcaster_login
        self._broadcaster_name  = broadcaster_name
        self._on_comment = on_comment
        self._on_status  = on_status
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """受信を停止する（ブロックしない）"""
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ─── 受信ループ（ワーカースレッド） ──────────────────────────────────────

    def _receive_loop(self):
        """WebSocket 接続 → EventSub 購読 → メッセージ処理ループ"""
        self._notify_status(STATUS_CONNECTING, "Twitch に接続中...")

        # トークン検証（期限切れなら更新）
        if not self._auth.validate_token():
            self._notify_status(STATUS_ERROR, "Twitch トークンが無効です。再認証してください。")
            return

        reconnect_url: str | None = None
        retry_count   = 0

        while not self._stop_event.is_set():
            ws_url = reconnect_url or EVENTSUB_WS_URL
            reconnect_url = None
            try:
                result = self._ws_session(ws_url)
            except Exception as e:
                _logger.error("Twitch WebSocket エラー: %s", e)
                result = ("error", str(e))

            action, detail = result

            if action == "stopped":
                break
            elif action == "reconnect":
                reconnect_url = detail
                self._notify_status(STATUS_RECONNECTING, "Twitch サーバー指示で再接続中...")
                continue
            elif action == "error":
                retry_count += 1
                if retry_count > 5:
                    self._notify_status(STATUS_ERROR, f"再接続上限に達しました: {detail}")
                    return
                wait = min(2 ** retry_count, 30)
                self._notify_status(STATUS_RECONNECTING, f"再接続中 ({retry_count}/5) — {wait}秒後: {detail}")
                self._wait(wait)
            elif action == "completed":
                break

        self._notify_status(STATUS_DISCONNECTED, "Twitch 受信停止")

    def _ws_session(self, ws_url: str) -> tuple:
        """
        WebSocket セッション 1回分を処理する。

        戻り値: ("stopped"|"reconnect"|"error"|"completed", detail_str)
        """
        try:
            import websocket
        except ImportError:
            return ("error", "websocket-client パッケージが必要です: pip install websocket-client")

        session_id: str  = ""
        subscription_done = False
        last_keepalive    = time.monotonic()

        def _on_message(ws, message):
            nonlocal session_id, subscription_done, last_keepalive
            try:
                msg  = json.loads(message)
                meta = msg.get("metadata", {})
                mtype = meta.get("message_type", "")

                if mtype == "session_welcome":
                    session_id = msg["payload"]["session"]["id"]
                    _logger.info("[Twitch] session_welcome: %s", session_id)
                    # EventSub 購読を別スレッドで実行
                    threading.Thread(
                        target=self._subscribe_eventsub,
                        args=(session_id,),
                        daemon=True,
                    ).start()

                elif mtype == "session_keepalive":
                    last_keepalive = time.monotonic()

                elif mtype == "notification":
                    if not subscription_done:
                        subscription_done = True
                        self._notify_status(STATUS_RECEIVING, "Twitch コメント受信中")
                    last_keepalive = time.monotonic()
                    sub_type = msg["payload"].get("subscription", {}).get("type", "")
                    if sub_type == "channel.chat.message":
                        event = msg["payload"].get("event", {})
                        raw   = self._normalize_event(event)
                        if self._on_comment:
                            self._on_comment(raw)

                elif mtype == "session_reconnect":
                    new_url = msg["payload"]["session"].get("reconnect_url", EVENTSUB_WS_URL)
                    ws.close()
                    _ws_result[0] = ("reconnect", new_url)

                elif mtype == "revocation":
                    _ws_result[0] = ("error", "EventSub 購読が取り消されました")
                    ws.close()

            except Exception as e:
                _logger.error("[Twitch] メッセージ処理エラー: %s", e)

        def _on_error(ws, error):
            _logger.error("[Twitch] WebSocket エラー: %s", error)

        def _on_close(ws, code, msg):
            _logger.info("[Twitch] WebSocket 切断: %s %s", code, msg)

        def _on_open(ws):
            _logger.info("[Twitch] WebSocket 接続確立")

        _ws_result: list = [None]

        ws_app = websocket.WebSocketApp(
            ws_url,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
            on_open=_on_open,
        )

        ws_thread = threading.Thread(
            target=lambda: ws_app.run_forever(ping_interval=10, ping_timeout=5),
            daemon=True,
        )
        ws_thread.start()

        # keepalive タイムアウト監視ループ
        while not self._stop_event.is_set():
            time.sleep(1)
            if _ws_result[0] is not None:
                ws_app.close()
                return _ws_result[0]
            if not ws_thread.is_alive():
                if _ws_result[0]:
                    return _ws_result[0]
                return ("error", "WebSocket スレッド終了")
            # keepalive タイムアウトチェック
            if session_id and time.monotonic() - last_keepalive > KEEPALIVE_TIMEOUT:
                ws_app.close()
                return ("error", "keepalive タイムアウト")

        ws_app.close()
        return ("stopped", "")

    def _subscribe_eventsub(self, session_id: str):
        """Helix API で channel.chat.message を購読する"""
        user_id = self._auth.user_id
        if not user_id:
            self._notify_status(STATUS_ERROR, "Twitch ユーザーIDが不明です。再認証してください。")
            return

        payload = json.dumps({
            "type":    "channel.chat.message",
            "version": "1",
            "condition": {
                "broadcaster_user_id": self._broadcaster_id,
                "user_id":             user_id,
            },
            "transport": {
                "method":     "websocket",
                "session_id": session_id,
            },
        }).encode("utf-8")

        headers = self._auth.get_helix_headers()
        req = urllib.request.Request(
            HELIX_EVENTSUB_URL,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data   = json.loads(resp.read())
                status = data.get("data", [{}])[0].get("status", "")
                _logger.info("[Twitch] EventSub 購読: status=%s", status)
                self._notify_status(STATUS_RECEIVING, "Twitch コメント受信中")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            _logger.error("[Twitch] EventSub 購読失敗 HTTP %d: %s", e.code, body)
            self._notify_status(STATUS_ERROR, f"EventSub 購読失敗 (HTTP {e.code}): {body[:120]}")
        except Exception as e:
            _logger.error("[Twitch] EventSub 購読例外: %s", e)
            self._notify_status(STATUS_ERROR, f"EventSub 購読エラー: {e}")

    # ─── コメント正規化 ───────────────────────────────────────────────────────

    def _normalize_event(self, event: dict) -> dict:
        """
        Twitch channel.chat.message イベントを CommentItem 共通 dict に変換する。

        CommentItem は snippet/authorDetails 構造を読むため、
        Twitch イベントを YouTube API レスポンス互換形式に正規化する。
        """
        msg_id     = event.get("message_id", "")
        body       = event.get("message", {}).get("text", "")
        chatter_id = event.get("chatter_user_id", "")
        chatter_lg = event.get("chatter_user_login", "")
        chatter_nm = event.get("chatter_user_name", "") or chatter_lg
        broadcaster_id = event.get("broadcaster_user_id", "")
        now_iso    = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # バッジ解析
        badges   = event.get("badges", [])
        badge_ids = {b.get("set_id", "") for b in badges}
        is_owner = chatter_id == broadcaster_id or "broadcaster" in badge_ids
        is_mod   = "moderator" in badge_ids
        is_sub   = "subscriber" in badge_ids or "founder" in badge_ids

        return {
            "id": msg_id,
            "snippet": {
                "type":         "textMessageEvent",
                "publishedAt":  now_iso,
                "textMessageDetails": {"messageText": body},
                "liveChatId":   broadcaster_id,
                "hasDisplayContent": bool(body),
                "displayMessage": body,
            },
            "authorDetails": {
                "channelId":        chatter_id,
                "displayName":      chatter_nm,
                "channelUrl":       f"https://twitch.tv/{chatter_lg}",
                "profileImageUrl":  "",
                "isChatOwner":      is_owner,
                "isChatModerator":  is_mod,
                "isChatSponsor":    is_sub,
                "isVerified":       False,
            },
            "_source": "live_twitch",
        }

    # ─── ヘルパー ─────────────────────────────────────────────────────────────

    def _wait(self, seconds: float):
        """stop_event を監視しながら待機"""
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._stop_event.is_set():
            time.sleep(0.25)

    def _notify_status(self, status: str, message: str):
        if self._on_status:
            self._on_status(status, message)


# ─── Twitch ソースアダプタ ────────────────────────────────────────────────────

class TwitchSourceAdapter:
    """
    Twitch コメント取得アダプタ（SourceAdapter インターフェース準拠）。

    TwitchClient をラップして source_adapter.SourceAdapter の
    インターフェースを提供する。
    """

    def __init__(self, auth_service):
        self._client        = TwitchClient(auth_service)
        self._verify_result = {}

    def verify_target(self, url: str) -> dict:
        """
        Twitch URL またはチャンネル名から接続情報を取得する（同期）。
        成功時は dict を返す。失敗時は TwitchClientError を raise する。
        """
        result = self._client.verify(url)
        self._verify_result = result
        return result

    def connect(self, on_comment, on_status, **kwargs):
        r = self._verify_result
        self._client.start(
            broadcaster_id    = r.get("broadcaster_id", r.get("live_chat_id", "")),
            broadcaster_login = r.get("login", ""),
            broadcaster_name  = r.get("display_name", ""),
            on_comment        = on_comment,
            on_status         = on_status,
        )

    def disconnect(self):
        self._client.stop()

    @property
    def is_running(self) -> bool:
        return self._client.is_running

    def normalize_comment(self, raw_event: dict) -> dict:
        """Twitch イベントはすでに TwitchClient 内で正規化済みのためそのまま返す"""
        return raw_event
