"""
RCommentHub — YouTube Live Chat API クライアント

取得方式:
  主軸: liveChatMessages.streamList（gRPC server-streaming / 公式準拠実装）
        サービス: /youtube.api.v3.V3DataLiveChatMessageService/StreamList
        エンドポイント: dns:///youtube.googleapis.com:443
        実装: youtube_stream_grpc_client.YouTubeStreamGrpcClient
  補助: なし（list ポーリングは廃止）

  【退避中・削除予定】
  旧実装: liveChatMessages.stream（httpx HTTP/2 / REST streaming endpoint）
          _try_stream_loop() および _read_stream_responses_httpx() に残存。
          gRPC 実装の接続成功確認後に物理削除予定。

認証方式:
  標準: OAuth 2.0 (AuthService 経由)
  補助: API キー (AuthService 経由 / gRPC は x-goog-api-key をサポート)

接続フロー:
  1. liveChatId を取得（videos.list / REST）
  2. gRPC StreamList で server-streaming 接続を確立
  3. 接続切断時は next_page_token で resume 再接続
  4. 配信終了（CHAT_ENDED_EVENT / offline_at）で正常停止

別スレッドで動作。UI コールバックはメインスレッド側で root.after() して使うこと。
"""

import datetime
import json
import logging
import threading
import time
import requests
import httpx  # 退避中（削除予定）: 旧 REST streaming 実装で使用

from auth_service import AuthService, AUTH_MODE_OAUTH, AUTH_MODE_API_KEY
from youtube_stream_grpc_client import YouTubeStreamGrpcClient

_logger   = logging.getLogger(__name__)
_route    = logging.getLogger("route_check")       # 経路判定用（route_check.log へ出力）
_yt_error = logging.getLogger("youtube_error")     # YouTube 接続異常解析用（youtube_error.log へ出力）
_api_usage = logging.getLogger("youtube_api_usage")  # API 使用量診断用（youtube_api_usage.log へ出力）

# ─── YouTube Data API v3 エンドポイント ─────────────────────────────────────
_API_BASE = "https://www.googleapis.com/youtube/v3"

# ─── 接続状態定数 ────────────────────────────────────────────────────────────
STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTING   = "connecting"
STATUS_RECEIVING    = "receiving"
STATUS_RECONNECTING = "reconnecting"
STATUS_ERROR        = "error"

# ─── ポーリング / ストリーム設定 ─────────────────────────────────────────────
MAX_RETRIES       = 5
RETRY_BASE_DELAY  = 2.0    # 秒（指数バックオフのベース）
POLL_DEFAULT_MS   = 5000   # デフォルトポーリング間隔（ms）
POLL_WAIT_STEP    = 0.25   # stop_event チェック間隔（秒）

# streamList 接続タイムアウト（秒）
STREAM_CONNECT_TIMEOUT = 15
STREAM_READ_TIMEOUT    = 60

# streamList 一時切断時の再試行設定
STREAM_MAX_RETRIES_ON_FAILURE = 5    # 再試行回数（固定）
STREAM_RETRY_DELAY            = 3.0  # 再試行間隔（秒）

# streamList 再接続前の最短待機時間
# pollingIntervalMillis が 0 や None でも即時再接続しないためのフロア値
STREAM_RECONNECT_MIN_WAIT = 1.0  # 秒

# 疑似ポーリング検知: 再接続間隔がpollingIntervalMillisの何割未満なら警告するか
_POLLING_DETECT_RATIO = 0.5


class YouTubeClientError(Exception):
    """API エラーや接続失敗を表す例外"""
    pass


class YouTubeClient:
    """
    YouTube Live Chat API クライアント。

    AuthService を介して OAuth / API キーの両方に対応する。
    取得方式は streamList を主軸とし、list をフォールバックとして使用する。
    """

    def __init__(self):
        self._auth_service: AuthService | None = None
        self._live_chat_id: str      = ""
        self._next_token: str | None = None
        self._stop_event             = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_comment             = None   # (raw: dict) -> None
        self._on_status              = None   # (status: str, message: str) -> None
        self._on_fallback_confirm    = None   # (reason: str) -> bool | None（後方互換保持、内部では未使用）
        self._on_system_message      = None   # (text: str) -> None  切断通知など
        self._is_first_fetch: bool   = True   # 初回取得（バックログ）判定用
        self._connect_time = datetime.datetime.now(datetime.timezone.utc)  # 接続開始時刻（backlog 判定の基準）
        self._use_stream: bool       = True   # True: streamList 試行, False: list のみ
        self._polling_fallback_allowed: bool = False   # streamList 失敗時に list へ切替許可するか
        self._notify_overlay: bool   = False  # youtube_error.log 記録用（コントローラから設定）
        self._stream_connected: bool = False  # streamList で一度でも応答受信したか（終了判定用）
        # セッション追跡（API 使用量ログ用）
        self._session_id: str   = ""
        self._session_seq: int  = 0
        self._session_stats: dict = {}
        self._reset_session_stats()  # verify() 呼び出し時も _log_api_call() が安全に動作するよう初期化

    # ─── 認証サービス設定 ────────────────────────────────────────────────────

    def set_auth_service(self, auth_service: AuthService):
        """AuthService を設定する。connect() 前に呼ぶこと。"""
        self._auth_service = auth_service

    # ─── 接続確認（同期。呼び出し元スレッドでブロックする）──────────────────

    def verify(self, video_id: str, api_key: str = "") -> dict:
        """
        動画 ID からライブチャット情報を取得する（同期）。

        auth_service が設定されていれば OAuth / API キーを自動選択する。
        api_key を直接渡した場合は後方互換のため API キーとして使用する。

        成功時の戻り値:
            {
                "live_chat_id": str,
                "title": str,
                "video_id": str,
                "stream_status": "live",
            }

        失敗時は YouTubeClientError を raise する。
        """
        url    = f"{_API_BASE}/videos"
        kwargs = self._build_request_kwargs(api_key)

        # params の構築（認証 params と合わせる）
        base_params = {
            "id":   video_id.strip(),
            "part": "liveStreamingDetails,snippet",
        }
        # API キーモードでは "key" が kwargs["params"] に入っている
        if "params" in kwargs:
            base_params.update(kwargs.pop("params"))

        seq = self._next_api_seq()
        t0  = time.monotonic()
        try:
            resp = requests.get(url, params=base_params, timeout=10, **kwargs)
        except requests.RequestException as e:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self._log_api_call(
                method="videos.list", route="verify",
                seq=seq, reconnect_seq=0,
                page_token=False, next_page_token=False,
                http_status=0, api_reason="connection_error",
                items=0, polling_ms=None, elapsed_ms=elapsed_ms,
            )
            raise YouTubeClientError(f"通信エラー: {e}")

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self._raise_for_status(resp)

        data  = resp.json()
        items = data.get("items", [])
        self._log_api_call(
            method="videos.list", route="verify",
            seq=seq, reconnect_seq=0,
            page_token=False, next_page_token=False,
            http_status=resp.status_code, api_reason="-",
            items=len(items), polling_ms=None, elapsed_ms=elapsed_ms,
        )

        if not items:
            raise YouTubeClientError(
                "動画が見つかりません。動画 ID を確認してください。"
            )

        item    = items[0]
        title   = item.get("snippet", {}).get("title", "")
        lsd     = item.get("liveStreamingDetails", {})
        chat_id = lsd.get("activeLiveChatId", "")

        if not chat_id:
            if lsd.get("actualEndTime"):
                raise YouTubeClientError("この配信はすでに終了しています。")
            elif not lsd:
                raise YouTubeClientError("この動画はライブ配信ではありません。")
            else:
                raise YouTubeClientError(
                    "ライブチャットが無効、または配信がまだ開始されていません。"
                )

        return {
            "live_chat_id": chat_id,
            "title":        title,
            "video_id":     video_id.strip(),
            "stream_status": "live",
        }

    # ─── 受信開始 ────────────────────────────────────────────────────────────

    def start(self, live_chat_id: str, api_key: str = "",
              on_comment=None, on_status=None, on_fallback_confirm=None,
              polling_fallback_allowed: bool = False,
              on_system_message=None,
              notify_overlay: bool = False):
        """
        コメント受信を別スレッドで開始する。

        on_comment(raw: dict)            — コメント1件ごと（ワーカースレッド文脈）
        on_status(status: str, msg: str) — 状態変化時（ワーカースレッド文脈）
        on_fallback_confirm              — 後方互換のため保持。内部では未使用。
        polling_fallback_allowed: bool   — streamList 失敗時に list へ自動切替を許可するか
                                           設定「YouTube ポーリング切替許可」に対応。デフォルト False。
        on_system_message(text: str)     — 切断通知などのシステムメッセージコールバック
        notify_overlay: bool             — youtube_error.log 記録用フラグ（配信用通知設定の ON/OFF）

        呼び出し元は root.after(0, ...) で UI スレッドへ転送すること。
        """
        if self._thread and self._thread.is_alive():
            return

        self._live_chat_id              = live_chat_id
        self._next_token                = None
        self._on_comment                = on_comment
        self._on_status                 = on_status
        self._on_fallback_confirm       = on_fallback_confirm   # 後方互換保持
        self._on_system_message         = on_system_message
        self._polling_fallback_allowed  = polling_fallback_allowed
        self._notify_overlay            = notify_overlay
        self._stop_event.clear()
        self._is_first_fetch            = True
        self._connect_time              = datetime.datetime.now(datetime.timezone.utc)
        self._stream_connected          = False
        self._reset_session_stats()

        # API キーを直接渡された場合の後方互換処理
        if api_key and self._auth_service is None:
            from auth_service import AuthService
            svc = AuthService(token_path="")
            svc.api_key = api_key
            self._auth_service = svc

        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """受信を停止する（ブロックしない）"""
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ─── バックログ判定 ──────────────────────────────────────────────────────

    def _is_backlog_item(self, raw_item: dict) -> bool:
        """
        publishedAt と接続開始時刻を比較してバックログアイテムか判定する。
        publishedAt が connect_time より前なら True（バックログ扱い）。
        publishedAt が取得できない場合は True（安全側: バックログ扱い）。
        """
        published = raw_item.get("snippet", {}).get("publishedAt", "")
        if not published:
            return True
        try:
            dt = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
            result = dt < self._connect_time
            _logger.debug(
                "_is_backlog_item: publishedAt=%s connect_time=%s => backlog=%s",
                published, self._connect_time.isoformat(), result,
            )
            return result
        except Exception:
            return True

    # ─── システムメッセージ通知 ──────────────────────────────────────────────

    def _notify_system_message(self, text: str):
        """切断通知などのシステムメッセージをコントローラへ通知する（ワーカースレッドから呼ぶ）"""
        if self._on_system_message:
            self._on_system_message(text)

    # ─── fallback 許可確認（後方互換保持・現在は内部未使用） ─────────────────

    def _request_fallback_permission(self, reason: str) -> bool:
        """
        list fallback への切替許可をユーザーへ確認する。
        on_fallback_confirm コールバックが未設定の場合は常に拒否（自動 fallback しない）。

        ワーカースレッドから呼ばれる。コールバック内でブロック待機すること。
        戻り値: True=許可, False=拒否
        """
        _route.info("[route-check] fallback_prompt_shown reason=%s", reason)
        if self._on_fallback_confirm is None:
            _route.info("[route-check] fallback_denied_by_user reason=no_callback")
            return False
        try:
            result = self._on_fallback_confirm(reason)
            return bool(result)
        except Exception:
            return False

    # ─── セッション統計 ──────────────────────────────────────────────────────

    def _reset_session_stats(self):
        """セッション統計カウンターをリセットし、新しいセッションIDを発行する"""
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self._session_id  = f"{ts}_{id(self) & 0xFFFF:04X}"
        self._session_seq = 0
        self._session_stats = {
            "total_calls":    0,
            "videos_list":    0,
            "streamList":     0,
            "list_polling":   0,
            "reconnects":     0,
            "zero_items":     0,
            "http_403":       0,
            "http_404":       0,
            "http_5xx":       0,
            "rate_limited":   0,
            "quota_exceeded": 0,
            # gRPC ストリーミング集計（YouTubeStreamGrpcClient.stats からマージ）
            # 注意: grpc_stream_calls と YouTube Data API quota の対応は公式未公開。
            # quota 実測には Google Cloud Console の確認が必要。
            "grpc_channel_creates":  0,
            "grpc_stream_calls":     0,
            "grpc_resume_count":     0,
            "grpc_error_reconnects": 0,
            "grpc_rpc_errors":       0,
            "grpc_total_responses":  0,
            "grpc_total_items":      0,
            "grpc_zero_responses":   0,
        }

    def _next_api_seq(self) -> int:
        """セッション内の API 呼び出しシーケンス番号を発行する"""
        self._session_seq += 1
        return self._session_seq

    def _log_api_call(self, *, method: str, route: str, seq: int, reconnect_seq: int,
                      page_token: bool, next_page_token: bool,
                      http_status: int, api_reason: str,
                      items: int, polling_ms, elapsed_ms: int):
        """API 呼び出し1回分を youtube_api_usage.log に記録し、セッション統計を更新する"""
        s = self._session_stats
        s["total_calls"] += 1
        if method == "videos.list":
            s["videos_list"] += 1
        elif method == "liveChatMessages.streamList":
            s["streamList"] += 1
        elif method == "liveChatMessages.list":
            s["list_polling"] += 1
        if http_status == 403:
            s["http_403"] += 1
        elif http_status == 404:
            s["http_404"] += 1
        elif http_status >= 500:
            s["http_5xx"] += 1
        if api_reason == "rateLimitExceeded":
            s["rate_limited"] += 1
        elif api_reason == "quotaExceeded":
            s["quota_exceeded"] += 1
        if items == 0 and method != "videos.list":
            s["zero_items"] += 1

        _api_usage.info(
            "API_CALL method=%s route=%s session=%s seq=%d reconnect_seq=%d "
            "page_token=%s next_page_token=%s http_status=%d api_reason=%s "
            "items=%d polling_ms=%s elapsed_ms=%d",
            method, route, self._session_id, seq, reconnect_seq,
            "yes" if page_token else "no",
            "yes" if next_page_token else "no",
            http_status, api_reason, items,
            str(int(polling_ms)) if polling_ms is not None else "-",
            elapsed_ms,
        )

    def _emit_session_summary(self):
        """接続停止時のセッション集計を youtube_api_usage.log に出力する"""
        if not self._session_id:
            return
        s = self._session_stats
        # 推定 quota（2026-04-24 実測に基づく推定値。公式未公開）
        # StreamList 1 RPC ≈ 5 units, videos.list 1 ≈ 1 unit, liveChatMessages.list 1 ≈ 5 units
        # rest_estimated_quota_units: REST API 分（videos.list + list_polling）
        # grpc_estimated_quota_units: gRPC StreamList RPC 分
        # estimated_total_quota_units: 両者の合計
        rest_estimated_quota_units = (
            s.get("videos_list", 0) * 1
            + s.get("list_polling", 0) * 5
        )
        grpc_estimated_quota_units = s.get("grpc_stream_calls", 0) * 5
        estimated_total_quota_units = rest_estimated_quota_units + grpc_estimated_quota_units
        _api_usage.info(
            "SESSION_SUMMARY session=%s total_calls=%d videos_list=%d "
            "streamList=%d list_polling=%d reconnects=%d zero_items=%d "
            "http_403=%d http_404=%d http_5xx=%d rate_limited=%d quota_exceeded=%d "
            "grpc_channel_creates=%d grpc_stream_calls=%d grpc_resume_count=%d "
            "grpc_error_reconnects=%d grpc_rpc_errors=%d "
            "grpc_total_responses=%d grpc_total_items=%d grpc_zero_responses=%d "
            "rest_estimated_quota_units=%d grpc_estimated_quota_units=%d estimated_total_quota_units=%d",
            self._session_id,
            s.get("total_calls", 0),    s.get("videos_list", 0),
            s.get("streamList", 0),     s.get("list_polling", 0),
            s.get("reconnects", 0),     s.get("zero_items", 0),
            s.get("http_403", 0),       s.get("http_404", 0),
            s.get("http_5xx", 0),       s.get("rate_limited", 0),
            s.get("quota_exceeded", 0),
            s.get("grpc_channel_creates", 0),
            s.get("grpc_stream_calls", 0),
            s.get("grpc_resume_count", 0),
            s.get("grpc_error_reconnects", 0),
            s.get("grpc_rpc_errors", 0),
            s.get("grpc_total_responses", 0),
            s.get("grpc_total_items", 0),
            s.get("grpc_zero_responses", 0),
            rest_estimated_quota_units,
            grpc_estimated_quota_units,
            estimated_total_quota_units,
        )

    # ─── ストリーミング JSON パーサー ──────────────────────────────────────────

    def _read_stream_responses(self, resp):
        """
        ストリーミング接続から完全な JSON オブジェクトをジェネレーターで返す。

        iter_content() で HTTP 接続を維持したまま、サーバーから送られるデータを
        逐次処理する。json.JSONDecoder.raw_decode を使うことで、
        単一行 JSON・複数行 JSON・複数オブジェクト連続のいずれにも対応する。

        接続が閉じられると（iter_content が尽きると）ジェネレーターが終了する。
        呼び出し元は requests.exceptions.ReadTimeout を別途処理すること。
        """
        decoder = json.JSONDecoder()
        buffer  = ""
        for chunk in resp.iter_content(chunk_size=65536, decode_unicode=True):
            if not chunk:
                continue
            buffer += chunk
            # バッファ内の完全な JSON オブジェクトをすべて抽出する
            while True:
                stripped = buffer.lstrip()
                if not stripped:
                    buffer = ""
                    break
                try:
                    obj, idx = decoder.raw_decode(stripped)
                    buffer   = stripped[idx:]
                    yield obj
                except json.JSONDecodeError:
                    break  # 不完全な JSON → 次のチャンクを待つ

    def _read_stream_responses_httpx(self, resp):
        """
        【退避中・削除予定】旧 REST httpx 実装のストリーム JSON パーサー。
        _try_stream_loop からのみ呼ばれる。gRPC 移行後に削除予定。

        httpx ストリーミング接続から完全な JSON オブジェクト（dict）をジェネレーターで返す。

        Google の REST streaming endpoint (/stream) は Streaming JSON 形式を使用する。
        レスポンス全体が JSON 配列 [ {dict1} , {dict2} , ... ] として送られてくるため、
        外側の '[' / ',' / ']' を読み飛ばして内側の dict を逐次 yield する。

        応答形式の自動判定:
          先頭文字が '[' → streaming array モード（外側ラッパーを剥がして yield）
          先頭文字が '{' → NDJSON モード（各 dict を直接 yield）

        接続が閉じられると（iter_text が尽きると）ジェネレーターが終了する。
        呼び出し元は httpx.ReadTimeout を別途処理すること。
        """
        decoder          = json.JSONDecoder()
        buffer           = ""
        stream_array     = None  # None=未判定, True=配列ラッパーあり, False=NDJSON

        for chunk in resp.iter_text():
            if not chunk:
                continue
            buffer += chunk

            # 先頭文字でレスポンス形式を判定（初回のみ）
            if stream_array is None:
                head = buffer.lstrip()
                if not head:
                    continue
                if head[0] == "[":
                    stream_array = True
                    buffer = head[1:]  # '[' を消費
                    _logger.debug("_read_stream_responses_httpx: streaming array mode")
                else:
                    stream_array = False
                    _logger.debug("_read_stream_responses_httpx: NDJSON mode")

            # バッファ内の完全な JSON オブジェクトをすべて抽出する
            while True:
                stripped = buffer.lstrip()
                if not stripped:
                    buffer = ""
                    break

                # 配列モード: ',' セパレータと末尾 ']' を読み飛ばす
                if stream_array:
                    if stripped[0] == "]":
                        buffer = stripped[1:]
                        # ']' = 配列ラッパーの終端。接続は閉じていない。
                        # outer の iter_text() ループに戻り、続くチャンクを待つ。
                        # サーバーが接続を維持している場合はここでブロックする。
                        _logger.debug(
                            "_read_stream_responses_httpx: array_end_bracket encountered "
                            "— returning to iter_text loop (connection may still be open)"
                        )
                        break  # 配列終端
                    if stripped[0] == ",":
                        buffer = stripped[1:]
                        continue  # セパレータを消費して次の要素へ

                try:
                    obj, idx = decoder.raw_decode(stripped)
                    buffer   = stripped[idx:]
                    if isinstance(obj, dict):
                        yield obj
                    elif isinstance(obj, list):
                        # フォールバック: ネストした配列が来た場合
                        _logger.debug(
                            "_read_stream_responses_httpx: unexpected list of %d items", len(obj)
                        )
                        for item in obj:
                            if isinstance(item, dict):
                                yield item
                    else:
                        _logger.warning(
                            "_read_stream_responses_httpx: unexpected type=%s, skipping",
                            type(obj).__name__,
                        )
                except json.JSONDecodeError:
                    break  # 不完全な JSON → 次のチャンクを待つ

        # iter_text() が尽きた = サーバーが接続を閉じた（HTTP/2 END_STREAM もしくは TCP close）
        # 例外なくここに到達した場合は server-initiated close と判断できる。
        _logger.debug(
            "_read_stream_responses_httpx: iter_text exhausted "
            "buffer_remaining=%d — generator returning (server closed connection)",
            len(buffer),
        )

    # ─── 受信ループ（ワーカースレッド） ──────────────────────────────────────

    def _receive_loop(self):
        """
        受信経路の選択:
          OAuth 認証済み: streamList を試みてから、失敗時に list フォールバック
          API キーモード: 直接 list ポーリング（streamList は OAuth 必須のため）

        streamList の公式仕様:
          https://developers.google.com/youtube/v3/live/docs/liveChatMessages/streamList
          - サーバーストリーミング接続（低レイテンシ）
          - 各レスポンスに nextPageToken が含まれる
          - pageToken を指定して再開可能
          実装: iter_content() で HTTP 接続を保ち、複数レスポンスを逐次処理する。
          接続が実際に閉じられた時のみ再接続する（疑似ポーリング防止）。
        """
        try:
            self._receive_loop_inner()
        finally:
            self._emit_session_summary()

    def _receive_loop_inner(self):
        self._notify_status(STATUS_CONNECTING, "接続中...")

        # gRPC StreamList は OAuth / API キー両方をサポート
        # ただし API キーモードの場合は認証情報が正しく設定されているか確認する
        has_auth = self._auth_service is not None and (
            (self._auth_service.is_oauth_mode() and self._auth_service.is_authenticated())
            or (not self._auth_service.is_oauth_mode()
                and bool(getattr(self._auth_service, "_api_key", "")
                         or getattr(self._auth_service, "api_key", "")))
        )
        should_try_stream = self._use_stream and has_auth

        auth_mode = (
            "oauth"
            if (self._auth_service and self._auth_service.is_oauth_mode())
            else "api_key"
        )
        initial_route = "grpc_streamList" if should_try_stream else "stopped"
        _route.info(
            "[route-check] session_connect mode=%s initial=%s", auth_mode, initial_route
        )

        if not should_try_stream:
            _route.info("[route-check] effective_route=stopped reason=no_auth")
            self._notify_status(
                STATUS_DISCONNECTED,
                "YouTube streamList の認証情報がありません",
            )
            self._notify_system_message(
                "[YouTube] 認証情報がありません。OAuth 認証または API キーを設定してください。"
            )
            return

        # ─── gRPC ストリームループ（本線） ────────────────────────────────────
        stream_result = self._try_grpc_stream_loop()
        # stream_result: "completed" / "stopped" / "fallback" / "permanent" / "normal_end"

        if stream_result in ("stopped", "completed", "normal_end"):
            return

        if stream_result == "permanent":
            _yt_error.info(
                "EVENT grpc_fatal_error source=youtube route=grpc_streamList "
                "reason=permanent_failure notify_overlay=%s",
                self._notify_overlay,
            )
            return

        # stream_result == "fallback": 一時失敗の再試行上限到達
        _route.info("[route-check] effective_route=stopped reason=grpc_failed_no_fallback")
        _yt_error.info(
            "EVENT grpc_fatal_error source=youtube route=grpc_streamList "
            "reason=retry_exhausted notify_overlay=%s",
            self._notify_overlay,
        )
        self._notify_status(STATUS_DISCONNECTED, "接続に失敗しました")
        self._notify_system_message("接続に失敗しました")

    # ─── gRPC ストリームループ（本線・公式準拠実装） ───────────────────────────

    def _try_grpc_stream_loop(self) -> str:
        """
        Google 公式 gRPC server-streaming RPC (StreamList) による接続を実行する。

        YouTubeStreamGrpcClient に処理を委譲し、既存の callback 形式で結果を通知する。

        戻り値: "completed" / "stopped" / "fallback" / "permanent" / "normal_end"
        """
        client = YouTubeStreamGrpcClient(self._auth_service)
        result = client.run(
            live_chat_id=self._live_chat_id,
            stop_event=self._stop_event,
            on_comment=self._on_comment,
            on_status=self._notify_status,
            on_system_message=self._notify_system_message,
            connect_time=self._connect_time,
            notify_overlay=self._notify_overlay,
            is_first_fetch=self._is_first_fetch,
        )
        # gRPC 統計をセッション集計にマージ
        for key, val in client.stats.items():
            self._session_stats[key] = self._session_stats.get(key, 0) + val
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # 【退避中・削除予定】旧 REST httpx 実装
    # gRPC 実装（_try_grpc_stream_loop）の接続成功確認後に削除する。
    # _receive_loop_inner からは呼ばれなくなっている。
    # ─────────────────────────────────────────────────────────────────────────

    def _try_stream_loop(self) -> str:
        """
        【退避中・削除予定】
        liveChatMessages.streamList による接続（httpx HTTP/2 / REST endpoint）。

        旧実装。_receive_loop_inner からは _try_grpc_stream_loop に切り替え済み。
        gRPC 実装の接続成功確認後に物理削除する。

        接続維持方式:
          httpx.Client(http2=True) を使い HTTP/2 でストリーミング接続を確立する。
          HTTP/2 ではサーバーがストリームを開いたまま新規メッセージを push できる。
          _read_stream_responses_httpx() で接続を保ったまま JSON を逐次処理する。
          接続が実際に閉じられた時だけ再接続する（疑似ポーリング防止）。
          nextPageToken は切断後の再開用として使用し、
          正常継続中の新規 GET は発行しない。

          【重要】HTTP/1.1（requests）では YouTube サーバーが streamList に対し
          1 JSON レスポンスを返して即時クローズするため実質ポーリングになっていた。
          HTTP/2 ではサーバーが接続を維持して後続メッセージを push できる。

        戻り値:
          "completed"   — ストリームが正常に終了した（ライブ終了など）
          "stopped"     — 停止指示により中断した
          "fallback"    — 接続失敗（再試行上限到達）
          "permanent"   — 永続的な失敗（quotaExceeded / forbidden 等）
          "normal_end"  — 配信終了・配信削除による正常終了（エラー扱いしない）
        """

        url              = f"{_API_BASE}/liveChat/messages/stream"
        first_msg_logged = False
        reconnect_count  = 0    # 実際の再接続回数（サーバー側の接続close時のみカウント）
        failure_count    = 0    # 一時失敗の連続カウント（5回で上限）
        is_first         = self._is_first_fetch
        last_polling_ms: float | None = None  # 最後に受信した pollingIntervalMillis

        _route.info("[route-check] stream_attempt")

        # 各イテレーションで新規クライアントを生成するため、ループ外では None で初期化する。
        # httpx.Client(http2=True) を使い回すと、YouTube サーバーが HTTP/2 接続を閉じた後に
        # stale な接続状態が残り LocalProtocolError を誘発するため、毎回生成して解消する。
        _stream_client: httpx.Client | None = None
        while not self._stop_event.is_set():

            # 前イテレーションのクライアントを閉じてから新規生成する
            # （stale な HTTP/2 接続状態を持ち越さないようにするため）
            if _stream_client is not None:
                try:
                    _stream_client.close()
                except Exception:
                    pass
            _stream_client = httpx.Client(
                http2=True,
                timeout=httpx.Timeout(STREAM_READ_TIMEOUT, connect=STREAM_CONNECT_TIMEOUT),
            )

            # ─── HTTP リクエスト構築（ループ毎に再構築してトークン更新に対応）───
            kwargs      = self._build_request_kwargs()
            req_headers = kwargs.get("headers", {})
            base_params = {
                "liveChatId": self._live_chat_id,
                "part":       "id,snippet,authorDetails",
            }
            if "params" in kwargs:
                base_params.update(kwargs["params"])
            if self._next_token:
                base_params["pageToken"] = self._next_token

            if reconnect_count > 0 and failure_count == 0:
                _route.info("[route-check] stream_reconnect_start attempt=%d", reconnect_count)

            # ─── HTTP リクエスト ──────────────────────────────────────────────
            seq = self._next_api_seq()
            t0  = time.monotonic()
            try:
                _req = _stream_client.build_request(
                    "GET", url, params=base_params, headers=req_headers,
                )
                resp = _stream_client.send(_req, stream=True)
            except httpx.TransportError as e:
                elapsed_ms    = int((time.monotonic() - t0) * 1000)
                failure_count += 1
                _route_label  = "stream_reconnect" if reconnect_count > 0 else "streamList"
                self._log_api_call(
                    method="liveChatMessages.streamList", route=_route_label,
                    seq=seq, reconnect_seq=reconnect_count,
                    page_token=bool(self._next_token), next_page_token=False,
                    http_status=0, api_reason="connection_error",
                    items=0, polling_ms=None, elapsed_ms=elapsed_ms,
                )
                _route.info("[route-check] stream_transient_error fc=%d/%d reason=connection_error detail=%s",
                            failure_count, STREAM_MAX_RETRIES_ON_FAILURE, e)
                _yt_error.info(
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=%d/%d reason=connection_error http_status=- api_reason=- "
                    "exception_type=%s exception_msg=%s offline_at=- "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE,
                    type(e).__name__, str(e)[:200],
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                if failure_count >= STREAM_MAX_RETRIES_ON_FAILURE:
                    _yt_error.info(
                        "EVENT stream_retry_exhausted source=youtube route=streamList "
                        "retry_count=%d/%d reason=connection_error "
                        "polling_fallback=%s notify_overlay=%s",
                        failure_count, STREAM_MAX_RETRIES_ON_FAILURE,
                        self._polling_fallback_allowed, self._notify_overlay,
                    )
                    self._notify_status(
                        STATUS_DISCONNECTED,
                        f"YouTube 接続エラー — 再試行上限 ({STREAM_MAX_RETRIES_ON_FAILURE}回) に達しました",
                    )
                    self._notify_system_message(
                        f"[YouTube] 接続が切れました。再試行 {STREAM_MAX_RETRIES_ON_FAILURE} 回に達したため停止します。"
                    )
                    return "fallback"
                self._notify_status(
                    STATUS_RECONNECTING,
                    f"YouTube 接続切断 — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})...",
                )
                self._notify_system_message(
                    f"[YouTube] 接続が切れました — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})"
                )
                self._wait(STREAM_RETRY_DELAY)
                continue

            connect_elapsed_ms = int((time.monotonic() - t0) * 1000)
            _route_label       = "stream_reconnect" if reconnect_count > 0 else "streamList"

            # ─── HTTP ステータス確認 ─────────────────────────────────────────

            if resp.status_code == 404:
                self._log_api_call(
                    method="liveChatMessages.streamList", route=_route_label,
                    seq=seq, reconnect_seq=reconnect_count,
                    page_token=bool(self._next_token), next_page_token=False,
                    http_status=404, api_reason="liveChatNotFound",
                    items=0, polling_ms=None, elapsed_ms=connect_elapsed_ms,
                )
                resp.close()
                if self._stream_connected:
                    # 接続成立後の 404 = 配信削除 → 正常終了扱い
                    _route.info("[route-check] stream_normal_end reason=liveChatNotFound_after_connected")
                    _yt_error.info(
                        "EVENT stream_normal_end source=youtube route=streamList "
                        "reason=liveChatNotFound_after_connected http_status=404 "
                        "notify_overlay=%s", self._notify_overlay,
                    )
                    self._notify_status(STATUS_DISCONNECTED, "配信が削除されたため接続を終了しました")
                    self._notify_system_message("配信が削除されたため接続を終了しました")
                    return "normal_end"
                else:
                    # 未接続時の 404 = 無効な liveChatId → 永続的失敗
                    _route.info("[route-check] stream_fatal_error reason=liveChatNotFound_initial")
                    _yt_error.info(
                        "EVENT stream_fatal_error source=youtube route=streamList "
                        "reason=liveChatNotFound_initial http_status=404 "
                        "notify_overlay=%s", self._notify_overlay,
                    )
                    self._notify_status(STATUS_DISCONNECTED, "接続に失敗しました（ライブチャットが見つかりません）")
                    self._notify_system_message("接続に失敗しました（ライブチャットが見つかりません）")
                    return "permanent"

            if resp.status_code == 403:
                try:
                    resp.read()
                    err_body   = resp.json()
                    reason_403 = (err_body.get("error", {})
                                  .get("errors", [{}])[0]
                                  .get("reason", ""))
                    offline_at = (err_body.get("error", {})
                                  .get("details", [{}])[0]
                                  .get("offlineAt", "-")
                                  if err_body.get("error", {}).get("details") else "-")
                except Exception:
                    reason_403 = ""
                    offline_at = "-"

                self._log_api_call(
                    method="liveChatMessages.streamList", route=_route_label,
                    seq=seq, reconnect_seq=reconnect_count,
                    page_token=bool(self._next_token), next_page_token=False,
                    http_status=403, api_reason=reason_403 or "forbidden",
                    items=0, polling_ms=None, elapsed_ms=connect_elapsed_ms,
                )

                if reason_403 == "rateLimitExceeded":
                    # 一時的なレートリミット — failure_count に含めず再試行
                    backoff_secs = 5.0
                    _route.info("[route-check] stream_rate_limited reason=rateLimitExceeded")
                    _route.info("[route-check] stream_retry_backoff_seconds=%.1f", backoff_secs)
                    _yt_error.info(
                        "EVENT stream_rate_limited source=youtube route=streamList "
                        "retry_count=%d/%d reason=rateLimitExceeded "
                        "http_status=403 api_reason=rateLimitExceeded backoff_seconds=%.1f "
                        "polling_fallback=%s notify_overlay=%s",
                        failure_count, STREAM_MAX_RETRIES_ON_FAILURE, backoff_secs,
                        self._polling_fallback_allowed, self._notify_overlay,
                    )
                    resp.close()
                    self._wait(backoff_secs)
                    continue

                if reason_403 == "quotaExceeded":
                    # クォータ超過 — liveChatEnded 等と区別して明示
                    _route.warning("[route-check] stream_permanent reason=quotaExceeded status=403")
                    _yt_error.warning(
                        "EVENT quota_exceeded source=youtube route=streamList "
                        "api_reason=quotaExceeded http_status=403 "
                        "polling_fallback=%s notify_overlay=%s",
                        self._polling_fallback_allowed, self._notify_overlay,
                    )
                    self._notify_status(
                        STATUS_DISCONNECTED,
                        "YouTube クォータ超過 — 本日の API 使用量が上限に達しました",
                    )
                    self._notify_system_message(
                        "[YouTube] クォータ超過 (quotaExceeded) — 本日の API 使用量が上限に達しました。翌日まで接続できません。"
                    )
                    resp.close()
                    return "permanent"

                # liveChatEnded → 配信終了（正常終了）
                if reason_403 == "liveChatEnded":
                    _route.info("[route-check] stream_normal_end reason=liveChatEnded status=403")
                    _yt_error.info(
                        "EVENT stream_normal_end source=youtube route=streamList "
                        "reason=liveChatEnded http_status=403 offline_at=%s "
                        "notify_overlay=%s", offline_at, self._notify_overlay,
                    )
                    self._notify_status(STATUS_DISCONNECTED, "配信が終了したため接続を終了しました")
                    self._notify_system_message("配信が終了したため接続を終了しました")
                    resp.close()
                    return "normal_end"

                # liveChatNotFound (403 版) → 接続成立後は正常終了、初回は fatal
                if reason_403 == "liveChatNotFound":
                    resp.close()
                    if self._stream_connected:
                        _route.info("[route-check] stream_normal_end reason=liveChatNotFound_after_connected status=403")
                        _yt_error.info(
                            "EVENT stream_normal_end source=youtube route=streamList "
                            "reason=liveChatNotFound_after_connected http_status=403 "
                            "notify_overlay=%s", self._notify_overlay,
                        )
                        self._notify_status(STATUS_DISCONNECTED, "配信が削除されたため接続を終了しました")
                        self._notify_system_message("配信が削除されたため接続を終了しました")
                        return "normal_end"
                    else:
                        _route.info("[route-check] stream_fatal_error reason=liveChatNotFound_initial status=403")
                        _yt_error.info(
                            "EVENT stream_fatal_error source=youtube route=streamList "
                            "reason=liveChatNotFound_initial http_status=403 "
                            "notify_overlay=%s", self._notify_overlay,
                        )
                        self._notify_status(STATUS_DISCONNECTED, "接続に失敗しました（ライブチャットが見つかりません）")
                        self._notify_system_message("接続に失敗しました（ライブチャットが見つかりません）")
                        return "permanent"

                # forbidden / liveChatDisabled / その他の 403 → 非再試行エラー
                _route.info("[route-check] stream_fatal_error reason=%s status=403",
                            reason_403 or "forbidden")
                _yt_error.info(
                    "EVENT stream_fatal_error source=youtube route=streamList "
                    "reason=%s http_status=403 api_reason=%s offline_at=%s "
                    "notify_overlay=%s",
                    reason_403 or "forbidden", reason_403 or "forbidden",
                    offline_at, self._notify_overlay,
                )
                self._notify_status(STATUS_DISCONNECTED, "接続に失敗しました")
                self._notify_system_message("接続に失敗しました")
                resp.close()
                return "permanent"

            if resp.status_code >= 500:
                # サーバーエラー（5xx）: 一時失敗として再試行
                failure_count += 1
                self._log_api_call(
                    method="liveChatMessages.streamList", route=_route_label,
                    seq=seq, reconnect_seq=reconnect_count,
                    page_token=bool(self._next_token), next_page_token=False,
                    http_status=resp.status_code, api_reason="-",
                    items=0, polling_ms=None, elapsed_ms=connect_elapsed_ms,
                )
                _route.info("[route-check] stream_transient_error fc=%d/%d reason=http_5xx status=%d",
                            failure_count, STREAM_MAX_RETRIES_ON_FAILURE, resp.status_code)
                _yt_error.info(
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=%d/%d reason=http_5xx http_status=%d api_reason=- "
                    "exception_type=- exception_msg=- offline_at=- "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE, resp.status_code,
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                if failure_count >= STREAM_MAX_RETRIES_ON_FAILURE:
                    _yt_error.info(
                        "EVENT stream_retry_exhausted source=youtube route=streamList "
                        "retry_count=%d/%d reason=http_5xx http_status=%d "
                        "polling_fallback=%s notify_overlay=%s",
                        failure_count, STREAM_MAX_RETRIES_ON_FAILURE, resp.status_code,
                        self._polling_fallback_allowed, self._notify_overlay,
                    )
                    self._notify_status(
                        STATUS_DISCONNECTED,
                        f"YouTube サーバーエラー (HTTP {resp.status_code}) — 再試行上限 ({STREAM_MAX_RETRIES_ON_FAILURE}回) に達しました",
                    )
                    self._notify_system_message(
                        f"[YouTube] サーバーエラー (HTTP {resp.status_code}) — 再試行 {STREAM_MAX_RETRIES_ON_FAILURE} 回に達したため停止します。"
                    )
                    resp.close()
                    return "fallback"
                self._notify_status(
                    STATUS_RECONNECTING,
                    f"YouTube サーバーエラー (HTTP {resp.status_code}) — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})...",
                )
                self._notify_system_message(
                    f"[YouTube] サーバーエラー (HTTP {resp.status_code}) — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})"
                )
                resp.close()
                self._wait(STREAM_RETRY_DELAY)
                continue

            if resp.status_code not in (200, 206):
                # その他の 4xx 等 → 永続的失敗
                self._log_api_call(
                    method="liveChatMessages.streamList", route=_route_label,
                    seq=seq, reconnect_seq=reconnect_count,
                    page_token=bool(self._next_token), next_page_token=False,
                    http_status=resp.status_code, api_reason="-",
                    items=0, polling_ms=None, elapsed_ms=connect_elapsed_ms,
                )
                _route.info("[route-check] stream_permanent reason=http_error status=%d",
                            resp.status_code)
                _yt_error.info(
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=0/%d reason=http_error http_status=%d api_reason=- "
                    "exception_type=- exception_msg=- offline_at=- "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    STREAM_MAX_RETRIES_ON_FAILURE, resp.status_code,
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                resp.close()
                return "permanent"

            ct = resp.headers.get("Content-Type", "")
            if "json" not in ct and "event-stream" not in ct and "octet-stream" not in ct:
                self._log_api_call(
                    method="liveChatMessages.streamList", route=_route_label,
                    seq=seq, reconnect_seq=reconnect_count,
                    page_token=bool(self._next_token), next_page_token=False,
                    http_status=200, api_reason="content_type_mismatch",
                    items=0, polling_ms=None, elapsed_ms=connect_elapsed_ms,
                )
                _route.info("[route-check] stream_permanent reason=content_type_mismatch ct=%s", ct)
                _yt_error.info(
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=0/%d reason=content_type_mismatch http_status=200 api_reason=- "
                    "exception_type=- exception_msg=- offline_at=- "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    STREAM_MAX_RETRIES_ON_FAILURE,
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                resp.close()
                return "permanent"

            # ─── 接続確認ログ ─────────────────────────────────────────────────
            # HTTP バージョン・主要ヘッダを記録（公式仕様との照合・server close 断定のための材料）
            _route.info(
                "[route-check] stream_http_info http_version=%s ct=%s "
                "transfer_encoding=%s connection=%s",
                getattr(resp, "http_version", "-"),
                resp.headers.get("content-type", "-"),
                resp.headers.get("transfer-encoding", "-"),
                resp.headers.get("connection", "-"),
            )
            if reconnect_count == 0 and failure_count == 0:
                _route.info("[route-check] stream_started ct=%s", ct)
            elif failure_count > 0:
                # 一時失敗からの回復
                _yt_error.info(
                    "EVENT stream_retry_success source=youtube route=streamList "
                    "retry_count=%d/%d polling_fallback=%s notify_overlay=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE,
                    self._polling_fallback_allowed, self._notify_overlay,
                )
                self._notify_system_message("再接続に成功しました")
                failure_count = 0
                _route.info("[route-check] stream_retry_success attempt=%d", reconnect_count)
            else:
                _route.info("[route-check] stream_reconnect_success attempt=%d", reconnect_count)

            self._notify_status(STATUS_RECEIVING, "コメント受信中 (streamList)")
            self._stream_connected = True  # 一度でも応答受信 → 接続成立フラグ

            if self._stop_event.is_set():
                resp.close()
                return "stopped"

            # ─── ストリーム読み取り（接続維持） ──────────────────────────────
            # HTTP 接続を閉じずに、サーバーから送られる JSON を逐次処理する。
            # 新しい HTTP GET は接続が実際に閉じられた時のみ発行する。
            conn_responses   = 0
            stream_completed = False
            _iter_normal_exit = False  # for ループが例外なく自然終了したか（= server close の証拠）
            t_conn_start     = time.monotonic()

            try:
                for data in self._read_stream_responses_httpx(resp):
                    if self._stop_event.is_set():
                        resp.close()
                        return "stopped"

                    conn_responses += 1

                    # 型ガード: _read_stream_responses_httpx が dict を返すはずだが念のため防衛
                    if not isinstance(data, dict):
                        _route.warning(
                            "[route-check] stream_parse_type_error type=%s conn_responses=%d "
                            "— skipping non-dict response",
                            type(data).__name__, conn_responses,
                        )
                        continue

                    items      = data.get("items", [])
                    has_token  = "nextPageToken" in data
                    polling_ms = data.get("pollingIntervalMillis")
                    if polling_ms is not None:
                        if polling_ms != last_polling_ms:
                            _route.info(
                                "[route-check] stream_polling_interval polling_ms=%d "
                                "(prev=%s) conn_responses=%d",
                                int(polling_ms),
                                str(int(last_polling_ms)) if last_polling_ms is not None else "none",
                                conn_responses,
                            )
                        last_polling_ms = polling_ms

                    if has_token:
                        self._next_token = data["nextPageToken"]
                    else:
                        # nextPageToken なし: keys を診断ログに記録（原因特定用）
                        _route.info(
                            "[route-check] stream_no_token keys=%s conn_responses=%d",
                            list(data.keys()), conn_responses,
                        )

                    _route.info(
                        "[route-check] stream_response_parsed items=%d has_token=%s "
                        "attempt=%d conn_responses=%d",
                        len(items), "yes" if has_token else "no",
                        reconnect_count, conn_responses,
                    )

                    # API 使用量ログ（接続ごと1回目は実際のelapsed、以降は0を記録）
                    self._log_api_call(
                        method="liveChatMessages.streamList", route=_route_label,
                        seq=seq, reconnect_seq=reconnect_count,
                        page_token=bool(base_params.get("pageToken")),
                        next_page_token=has_token,
                        http_status=200, api_reason="-",
                        items=len(items), polling_ms=polling_ms,
                        elapsed_ms=connect_elapsed_ms if conn_responses == 1 else 0,
                    )
                    seq = self._next_api_seq()  # 次レスポンス用のシーケンス番号

                    # ─── メッセージ処理 ──────────────────────────────────────
                    if items:
                        if not first_msg_logged:
                            _route.info("[route-check] stream_first_message_received")
                            _route.info("[route-check] effective_route=streamList")
                            first_msg_logged = True
                        for raw_item in items:
                            if self._stop_event.is_set():
                                resp.close()
                                return "stopped"
                            if is_first and self._is_backlog_item(raw_item):
                                raw_item["_is_backlog"] = True
                            if self._on_comment:
                                self._on_comment(raw_item)
                        if is_first:
                            self._is_first_fetch = False
                            is_first = False

                    # ─── 継続判断 ────────────────────────────────────────────
                    if not has_token:
                        # nextPageToken なし → ストリーム自然終了
                        stream_completed = True
                        break

                    # nextPageToken あり → 接続継続。新規 GET は発行しない。
                    _route.info(
                        "[route-check] stream_continues_waiting attempt=%d conn_responses=%d",
                        reconnect_count, conn_responses,
                    )

                # for ループ正常終了（例外なし）= iter_text() が尽きた
                _iter_normal_exit = True

            except httpx.ReadTimeout:
                # 接続は保たれていたがデータが来なかった（正常な待機タイムアウト）
                # reconnect_count を増やし、nextPageToken で続きから接続し直す
                _route.info(
                    "[route-check] stream_read_timeout reconnect_count=%d conn_responses=%d",
                    reconnect_count, conn_responses,
                )

            except (httpx.RemoteProtocolError, httpx.LocalProtocolError,
                    httpx.ConnectError, httpx.ReadError) as e:
                # ストリーム読み取り中に接続が切れた（一時失敗）
                # LocalProtocolError: 前回の HTTP/2 接続残骸による状態不整合（毎回新規 Client 生成で抑制済み）
                failure_count += 1
                _route.info(
                    "[route-check] stream_transient_error fc=%d/%d reason=stream_error detail=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE, e,
                )
                _yt_error.info(
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=%d/%d reason=stream_read_error http_status=200 api_reason=- "
                    "exception_type=%s exception_msg=%s offline_at=- "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE,
                    type(e).__name__, str(e)[:200],
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                if failure_count >= STREAM_MAX_RETRIES_ON_FAILURE:
                    _yt_error.info(
                        "EVENT stream_retry_exhausted source=youtube route=streamList "
                        "retry_count=%d/%d reason=stream_read_error "
                        "polling_fallback=%s notify_overlay=%s",
                        failure_count, STREAM_MAX_RETRIES_ON_FAILURE,
                        self._polling_fallback_allowed, self._notify_overlay,
                    )
                    self._notify_status(STATUS_DISCONNECTED, "接続に失敗しました")
                    self._notify_system_message("接続に失敗しました")
                    try:
                        resp.close()
                    except Exception:
                        pass
                    return "fallback"
                self._notify_status(STATUS_RECONNECTING, "接続が切れたため再接続します")
                self._notify_system_message("接続が切れたため再接続します")
                try:
                    resp.close()
                except Exception:
                    pass
                self._wait(STREAM_RETRY_DELAY)
                continue

            except Exception as e:
                # 予期しないエラー（JSON 解析失敗等）: 一時失敗扱い
                failure_count += 1
                _route.info(
                    "[route-check] stream_transient_error fc=%d/%d reason=unexpected detail=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE, e,
                )
                _yt_error.info(
                    "EVENT stream_retryable_error source=youtube route=streamList "
                    "retry_count=%d/%d reason=unexpected_error http_status=200 api_reason=- "
                    "exception_type=%s exception_msg=%s "
                    "notify_overlay=%s has_token=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE,
                    type(e).__name__, str(e)[:200],
                    self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                if failure_count >= STREAM_MAX_RETRIES_ON_FAILURE:
                    self._notify_status(STATUS_DISCONNECTED, "接続に失敗しました")
                    self._notify_system_message("接続に失敗しました")
                    try:
                        resp.close()
                    except Exception:
                        pass
                    return "fallback"
                self._notify_status(STATUS_RECONNECTING, "接続が切れたため再接続します")
                self._notify_system_message("接続が切れたため再接続します")
                try:
                    resp.close()
                except Exception:
                    pass
                self._wait(STREAM_RETRY_DELAY)
                continue

            finally:
                try:
                    resp.close()
                except Exception:
                    pass

            # ─── iter_text 終了理由の記録 ────────────────────────────────────
            # _iter_normal_exit=True の場合、例外なく iter_text() が尽きた = server-initiated close
            # または HTTP/2 END_STREAM フラグによる接続終端。
            # ReadTimeout / protocol error の場合は _iter_normal_exit=False（それぞれの except で処理済み）。
            if _iter_normal_exit and not stream_completed:
                _route.info(
                    "[route-check] stream_iter_exhausted conn_responses=%d "
                    "— iter_text ended without exception: server closed connection (END_STREAM or TCP close)",
                    conn_responses,
                )

            # ─── ストリーム自然終了 ───────────────────────────────────────────
            if stream_completed:
                if not first_msg_logged:
                    _route.info("[route-check] stream_completed_no_data")
                _yt_error.info(
                    "EVENT stream_natural_end source=youtube route=streamList "
                    "reason=no_next_token polling_fallback=%s notify_overlay=%s",
                    self._polling_fallback_allowed, self._notify_overlay,
                )
                if self._stop_event.is_set():
                    return "stopped"
                self._notify_status(STATUS_DISCONNECTED, "ストリーム終了")
                return "completed"

            if self._stop_event.is_set():
                return "stopped"

            # ─── 実際の再接続（サーバー側で接続が閉じられた場合のみここに到達）─
            reconnect_count += 1
            self._session_stats["reconnects"] += 1

            conn_duration_ms = int((time.monotonic() - t_conn_start) * 1000)
            _route.info(
                "[route-check] stream_server_close reconnect_count=%d "
                "conn_responses=%d conn_duration_ms=%d polling_ms=%s",
                reconnect_count, conn_responses, conn_duration_ms,
                str(int(last_polling_ms)) if last_polling_ms is not None else "none",
            )

            # ─── 異常検知: 短周期での再接続（疑似ポーリング兆候）────────────
            if reconnect_count > 3 and conn_responses > 0 and last_polling_ms is not None:
                if conn_duration_ms < last_polling_ms * _POLLING_DETECT_RATIO:
                    _route.warning(
                        "EVENT streamlist_suspected_polling reconnect_count=%d "
                        "conn_duration_ms=%d expected_ms=%d",
                        reconnect_count, conn_duration_ms, int(last_polling_ms),
                    )

            # pollingIntervalMillis を待ってから再接続
            # STREAM_RECONNECT_MIN_WAIT を下限として設定し、
            # 0ms 応答や None の場合でも即時再接続ループを防ぐ
            if last_polling_ms is not None:
                wait_secs = max(last_polling_ms / 1000.0, STREAM_RECONNECT_MIN_WAIT)
            else:
                wait_secs = 3.0
            _route.info(
                "[route-check] stream_reconnect_wait wait_secs=%.1f polling_ms=%s",
                wait_secs,
                str(int(last_polling_ms)) if last_polling_ms is not None else "none",
            )
            self._wait(wait_secs)

        # stop_event によって停止
        if _stream_client is not None:
            try:
                _stream_client.close()
            except Exception:
                pass
        self._notify_status(STATUS_DISCONNECTED, "受信停止")
        return "stopped"

    # ─── ポーリングループ（list 方式・フォールバック） ────────────────────────

    def _poll_loop(self):
        """
        liveChatMessages.list によるポーリング（フォールバック経路）。
        pollingIntervalMillis に従って間隔を守る。
        """
        self._notify_status(STATUS_RECEIVING, "コメント受信中 (list)")
        retry_count   = 0
        poll_interval = POLL_DEFAULT_MS / 1000.0

        while not self._stop_event.is_set():
            try:
                result        = self._fetch_messages_list()
                retry_count   = 0
                poll_interval = result.get("pollingIntervalMillis",
                                           POLL_DEFAULT_MS) / 1000.0

                is_first_poll = self._is_first_fetch
                self._is_first_fetch = False

                for raw_item in result.get("items", []):
                    if self._stop_event.is_set():
                        break
                    if is_first_poll and self._is_backlog_item(raw_item):
                        raw_item["_is_backlog"] = True
                    if self._on_comment:
                        self._on_comment(raw_item)

                self._next_token = result.get("nextPageToken")

            except YouTubeClientError as e:
                msg = str(e)

                if "liveChatEnded" in msg:
                    self._notify_status(STATUS_DISCONNECTED, "ライブ配信が終了しました")
                    return

                if "quotaExceeded" in msg:
                    _yt_error.warning(
                        "EVENT quota_exceeded source=youtube route=list_polling "
                        "api_reason=quotaExceeded http_status=403 "
                        "polling_fallback=%s notify_overlay=%s",
                        self._polling_fallback_allowed, self._notify_overlay,
                    )
                    self._notify_status(
                        STATUS_DISCONNECTED,
                        "YouTube クォータ超過 — 本日の API 使用量が上限に達しました",
                    )
                    self._notify_system_message(
                        "[YouTube] クォータ超過 (quotaExceeded) — 本日の API 使用量が上限に達しました。翌日まで接続できません。"
                    )
                    return

                retry_count += 1
                if retry_count > MAX_RETRIES:
                    self._notify_status(
                        STATUS_ERROR,
                        f"再接続上限 ({MAX_RETRIES} 回) に達しました: {msg}",
                    )
                    return

                delay = RETRY_BASE_DELAY * (2 ** (retry_count - 1))
                self._notify_status(
                    STATUS_RECONNECTING,
                    f"再接続中 ({retry_count}/{MAX_RETRIES}) — {delay:.0f}秒後リトライ: {msg}",
                )
                self._wait(delay)
                if not self._stop_event.is_set():
                    self._notify_status(STATUS_RECEIVING, "コメント受信中（再接続）")
                continue

            except Exception as e:
                self._notify_status(STATUS_ERROR, f"予期しないエラー: {e}")
                return

            self._wait(poll_interval)

        self._notify_status(STATUS_DISCONNECTED, "受信停止")

    def _fetch_messages_list(self) -> dict:
        """liveChatMessages.list を呼び出す"""
        url    = f"{_API_BASE}/liveChat/messages"
        kwargs = self._build_request_kwargs()

        base_params = {
            "liveChatId": self._live_chat_id,
            "part":       "id,snippet,authorDetails",
        }
        if "params" in kwargs:
            base_params.update(kwargs.pop("params"))
        if self._next_token:
            base_params["pageToken"] = self._next_token

        seq = self._next_api_seq()
        t0  = time.monotonic()
        try:
            resp = requests.get(url, params=base_params, timeout=15, **kwargs)
        except requests.RequestException as e:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self._log_api_call(
                method="liveChatMessages.list", route="list_polling",
                seq=seq, reconnect_seq=0,
                page_token=bool(self._next_token), next_page_token=False,
                http_status=0, api_reason="connection_error",
                items=0, polling_ms=None, elapsed_ms=elapsed_ms,
            )
            raise YouTubeClientError(f"通信エラー: {e}")

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code == 403:
            try:
                reason = (resp.json()
                          .get("error", {})
                          .get("errors", [{}])[0]
                          .get("reason", ""))
            except Exception:
                reason = ""
            self._log_api_call(
                method="liveChatMessages.list", route="list_polling",
                seq=seq, reconnect_seq=0,
                page_token=bool(self._next_token), next_page_token=False,
                http_status=403, api_reason=reason or "forbidden",
                items=0, polling_ms=None, elapsed_ms=elapsed_ms,
            )
            if reason == "liveChatEnded":
                raise YouTubeClientError("liveChatEnded")
            if reason == "quotaExceeded":
                raise YouTubeClientError("quotaExceeded")
            raise YouTubeClientError(f"権限エラー (403): {reason or 'forbidden'}")

        if resp.status_code == 404:
            self._log_api_call(
                method="liveChatMessages.list", route="list_polling",
                seq=seq, reconnect_seq=0,
                page_token=bool(self._next_token), next_page_token=False,
                http_status=404, api_reason="-",
                items=0, polling_ms=None, elapsed_ms=elapsed_ms,
            )
            raise YouTubeClientError(
                "liveChatId が見つかりません (404)。配信が終了した可能性があります。"
            )

        if resp.status_code != 200:
            self._log_api_call(
                method="liveChatMessages.list", route="list_polling",
                seq=seq, reconnect_seq=0,
                page_token=bool(self._next_token), next_page_token=False,
                http_status=resp.status_code, api_reason="-",
                items=0, polling_ms=None, elapsed_ms=elapsed_ms,
            )
            raise YouTubeClientError(f"API エラー: HTTP {resp.status_code}")

        data = resp.json()
        self._log_api_call(
            method="liveChatMessages.list", route="list_polling",
            seq=seq, reconnect_seq=0,
            page_token=bool(self._next_token),
            next_page_token="nextPageToken" in data,
            http_status=200, api_reason="-",
            items=len(data.get("items", [])),
            polling_ms=data.get("pollingIntervalMillis"),
            elapsed_ms=elapsed_ms,
        )
        return data

    # ─── 共通ユーティリティ ─────────────────────────────────────────────────

    def _build_request_kwargs(self, api_key: str = "") -> dict:
        """
        AuthService の状態に基づいて requests 用の kwargs を構築する。
        api_key が直接渡された場合は API キーモードで処理（後方互換）。
        """
        if self._auth_service:
            return dict(self._auth_service.get_request_kwargs())
        if api_key:
            return {"params": {"key": api_key}}
        return {}

    def _raise_for_status(self, resp):
        """共通のステータスコードチェック"""
        if resp.status_code == 400:
            raise YouTubeClientError("リクエストが不正です。認証情報と動画 ID を確認してください。")
        if resp.status_code == 401:
            raise YouTubeClientError("認証エラー (401)。再認証が必要です。")
        if resp.status_code == 403:
            try:
                reason = (resp.json()
                          .get("error", {})
                          .get("errors", [{}])[0]
                          .get("reason", ""))
            except Exception:
                reason = ""
            raise YouTubeClientError(f"権限エラー (403): {reason or 'forbidden'}")
        if resp.status_code != 200:
            raise YouTubeClientError(f"API エラー: HTTP {resp.status_code}")

    def _wait(self, seconds: float):
        """stop_event を監視しながら待機"""
        waited = 0.0
        while waited < seconds and not self._stop_event.is_set():
            time.sleep(POLL_WAIT_STEP)
            waited += POLL_WAIT_STEP

    def _notify_status(self, status: str, message: str):
        if self._on_status:
            self._on_status(status, message)
