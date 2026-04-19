"""
RCommentHub — YouTube Live Chat API クライアント

取得方式:
  主軸: liveChatMessages.streamList（公式推奨・低レイテンシ）
  補助: liveChatMessages.list（ポーリング・フォールバック）

認証方式:
  標準: OAuth 2.0 (AuthService 経由)
  補助: API キー (AuthService 経由)

接続フロー:
  1. liveChatId を取得（videos.list）
  2. streamList で接続を試みる（接続維持方式: iter_content でサーバーからのJSONを逐次処理）
  3. streamList が利用できない場合 list ポーリングへ自動フォールバック
  4. nextPageToken は切断後の再開用として保持し、正常継続中の新規GETトリガにはしない

別スレッドで動作。UI コールバックはメインスレッド側で root.after() して使うこと。
"""

import datetime
import json
import logging
import threading
import time
import requests

from auth_service import AuthService, AUTH_MODE_OAUTH, AUTH_MODE_API_KEY

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
        self._use_stream: bool       = True   # True: streamList 試行, False: list のみ
        self._polling_fallback_allowed: bool = False   # streamList 失敗時に list へ切替許可するか
        self._notify_overlay: bool   = False  # youtube_error.log 記録用（コントローラから設定）
        # セッション追跡（API 使用量ログ用）
        self._session_id: str  = ""
        self._session_seq: int = 0
        self._session_stats: dict = {}

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
        _api_usage.info(
            "SESSION_SUMMARY session=%s total_calls=%d videos_list=%d "
            "streamList=%d list_polling=%d reconnects=%d zero_items=%d "
            "http_403=%d http_404=%d http_5xx=%d rate_limited=%d quota_exceeded=%d",
            self._session_id,
            s.get("total_calls", 0),    s.get("videos_list", 0),
            s.get("streamList", 0),     s.get("list_polling", 0),
            s.get("reconnects", 0),     s.get("zero_items", 0),
            s.get("http_403", 0),       s.get("http_404", 0),
            s.get("http_5xx", 0),       s.get("rate_limited", 0),
            s.get("quota_exceeded", 0),
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

        # OAuth 認証済みの場合のみ streamList を試みる
        # API キーモードでは streamList は利用不可のため list に直行
        should_try_stream = (
            self._use_stream
            and self._auth_service is not None
            and self._auth_service.is_oauth_mode()
            and self._auth_service.is_authenticated()
        )

        auth_mode = (
            "oauth"
            if (self._auth_service and self._auth_service.is_oauth_mode())
            else "api_key"
        )
        initial_route = "streamList" if should_try_stream else "list_fallback"
        _route.info("[route-check] session_connect mode=%s initial=%s", auth_mode, initial_route)

        if not should_try_stream:
            # API キーモード等: streamList を試みず直接 list（許可確認不要）
            _route.info("[route-check] effective_route=list_fallback reason=no_stream_attempt")

        if should_try_stream:
            stream_result = self._try_stream_loop()
            # stream_result: "completed" / "stopped" / "fallback" / "permanent"

            if stream_result == "stopped":
                return

            if stream_result == "completed":
                # 自然なストリーム終了 — _try_stream_loop 内で DISCONNECTED 通知済み
                return

            if stream_result == "permanent":
                # 永続的な失敗（liveChatEnded / liveChatDisabled / quotaExceeded / 404 等）
                # → ポーリング設定に関わらず停止
                self._notify_status(STATUS_DISCONNECTED, "YouTube 接続が終了しました")
                self._notify_system_message(
                    "[YouTube] 接続が終了しました（liveChatEnded / liveChatDisabled / quotaExceeded 等）"
                )
                _yt_error.info(
                    "EVENT stream_stopped source=youtube route=streamList "
                    "reason=permanent_failure polling_fallback=%s notify_overlay=%s",
                    self._polling_fallback_allowed, self._notify_overlay,
                )
                return

            # stream_result == "fallback": 一時失敗の再試行上限到達
            if self._polling_fallback_allowed:
                _route.info("[route-check] fallback_allowed_by_setting")
                _route.info("[route-check] effective_route=list_fallback reason=stream_failed")
                self._notify_status(STATUS_CONNECTING, "list 方式で継続中...")
                self._notify_system_message(
                    f"[YouTube] streamList 失敗 — list ポーリングへ切り替えます"
                )
                _yt_error.info(
                    "EVENT stream_polling_fallback source=youtube route=list_polling "
                    "reason=retry_exhausted polling_fallback=True notify_overlay=%s",
                    self._notify_overlay,
                )
            else:
                _route.info("[route-check] fallback_denied_by_setting")
                _route.info("[route-check] effective_route=stopped reason=stream_failed_no_fallback")
                # _try_stream_loop 内で DISCONNECTED 通知・システムメッセージ発行済み
                _yt_error.info(
                    "EVENT stream_stopped source=youtube route=streamList "
                    "reason=retry_exhausted polling_fallback=False notify_overlay=%s",
                    self._notify_overlay,
                )
                return

        self._poll_loop()

    def _try_stream_loop(self) -> str:
        """
        liveChatMessages.streamList による接続を試みる。

        接続維持方式:
          _read_stream_responses() で HTTP 接続を保ったまま、サーバーから
          流れる JSON を逐次処理する。
          接続が実際に閉じられた時だけ再接続する（疑似ポーリング防止）。
          nextPageToken は切断後の再開用として使用し、
          正常継続中の新規 HTTP GET トリガにはしない。

        戻り値:
          "completed" — ストリームが正常に終了した（ライブ終了など）
          "stopped"   — 停止指示により中断した
          "fallback"  — 接続失敗または非対応。list フォールバックへ移行すべき状態
          "permanent" — 永続的な失敗（liveChatEnded / quotaExceeded / 404 等）
        """

        url              = f"{_API_BASE}/liveChat/messages"
        first_msg_logged = False
        reconnect_count  = 0    # 実際の再接続回数（サーバー側の接続close時のみカウント）
        failure_count    = 0    # 一時失敗の連続カウント（5回で上限）
        is_first         = self._is_first_fetch
        last_polling_ms: float | None = None  # 最後に受信した pollingIntervalMillis

        _route.info("[route-check] stream_attempt")

        while not self._stop_event.is_set():

            # ─── HTTP リクエスト構築（ループ毎に再構築してトークン更新に対応）───
            kwargs      = self._build_request_kwargs()
            base_params = {
                "liveChatId": self._live_chat_id,
                "part":       "id,snippet,authorDetails",
            }
            if "params" in kwargs:
                base_params.update(kwargs.pop("params"))
            if self._next_token:
                base_params["pageToken"] = self._next_token

            if reconnect_count > 0 and failure_count == 0:
                _route.info("[route-check] stream_reconnect_start attempt=%d", reconnect_count)

            # ─── HTTP リクエスト ──────────────────────────────────────────────
            seq = self._next_api_seq()
            t0  = time.monotonic()
            try:
                resp = requests.get(
                    url, params=base_params,
                    timeout=(STREAM_CONNECT_TIMEOUT, STREAM_READ_TIMEOUT),
                    stream=True,
                    **kwargs,
                )
            except requests.RequestException as e:
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
                    http_status=404, api_reason="-",
                    items=0, polling_ms=None, elapsed_ms=connect_elapsed_ms,
                )
                _route.info("[route-check] stream_permanent reason=http_404")
                _yt_error.info(
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=0/%d reason=http_404 http_status=404 api_reason=- "
                    "exception_type=- exception_msg=- offline_at=- "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    STREAM_MAX_RETRIES_ON_FAILURE,
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                resp.close()
                return "permanent"

            if resp.status_code == 403:
                try:
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

                # liveChatEnded / liveChatDisabled / forbidden 等 → 永続的失敗
                _route.info("[route-check] stream_permanent reason=%s status=403",
                            reason_403 or "forbidden")
                _yt_error.info(
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=0/%d reason=http_403 http_status=403 api_reason=%s "
                    "exception_type=- exception_msg=- offline_at=%s "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    STREAM_MAX_RETRIES_ON_FAILURE,
                    reason_403 or "forbidden", offline_at,
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
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
                self._notify_system_message("[YouTube] 接続を回復しました")
                failure_count = 0
                _route.info("[route-check] stream_retry_success attempt=%d", reconnect_count)
            else:
                _route.info("[route-check] stream_reconnect_success attempt=%d", reconnect_count)

            self._notify_status(STATUS_RECEIVING, "コメント受信中 (streamList)")

            if self._stop_event.is_set():
                resp.close()
                return "stopped"

            # ─── ストリーム読み取り（接続維持） ──────────────────────────────
            # HTTP 接続を閉じずに、サーバーから送られる JSON を逐次処理する。
            # 新しい HTTP GET は接続が実際に閉じられた時のみ発行する。
            conn_responses   = 0
            stream_completed = False
            t_conn_start     = time.monotonic()

            try:
                for data in self._read_stream_responses(resp):
                    if self._stop_event.is_set():
                        resp.close()
                        return "stopped"

                    conn_responses += 1
                    items      = data.get("items", [])
                    has_token  = "nextPageToken" in data
                    polling_ms = data.get("pollingIntervalMillis")
                    if polling_ms is not None:
                        last_polling_ms = polling_ms

                    if has_token:
                        self._next_token = data["nextPageToken"]

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
                            if is_first:
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

            except requests.exceptions.ReadTimeout:
                # 接続は保たれていたがデータが来なかった（正常な待機タイムアウト）
                # reconnect_count を増やし、nextPageToken で続きから接続し直す
                _route.info(
                    "[route-check] stream_read_timeout reconnect_count=%d conn_responses=%d",
                    reconnect_count, conn_responses,
                )

            except (requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ConnectionError) as e:
                # ストリーム読み取り中に接続が切れた（一時失敗）
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
                    self._notify_status(
                        STATUS_DISCONNECTED,
                        f"YouTube 接続エラー — 再試行上限 ({STREAM_MAX_RETRIES_ON_FAILURE}回) に達しました",
                    )
                    self._notify_system_message(
                        f"[YouTube] 接続が切れました。再試行 {STREAM_MAX_RETRIES_ON_FAILURE} 回に達したため停止します。"
                    )
                    try:
                        resp.close()
                    except Exception:
                        pass
                    return "fallback"
                self._notify_status(
                    STATUS_RECONNECTING,
                    f"YouTube 接続切断 — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})...",
                )
                self._notify_system_message(
                    f"[YouTube] 接続が切れました — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})"
                )
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
                    "EVENT stream_disconnect_detected source=youtube route=streamList "
                    "retry_count=%d/%d reason=unexpected_error http_status=200 api_reason=- "
                    "exception_type=%s exception_msg=%s offline_at=- "
                    "polling_fallback=%s notify_overlay=%s has_token=%s",
                    failure_count, STREAM_MAX_RETRIES_ON_FAILURE,
                    type(e).__name__, str(e)[:200],
                    self._polling_fallback_allowed, self._notify_overlay,
                    "yes" if self._next_token else "no",
                )
                if failure_count >= STREAM_MAX_RETRIES_ON_FAILURE:
                    self._notify_status(
                        STATUS_DISCONNECTED,
                        f"YouTube エラー — 再試行上限 ({STREAM_MAX_RETRIES_ON_FAILURE}回) に達しました",
                    )
                    self._notify_system_message(
                        f"[YouTube] エラーが連続しました。再試行 {STREAM_MAX_RETRIES_ON_FAILURE} 回に達したため停止します。"
                    )
                    try:
                        resp.close()
                    except Exception:
                        pass
                    return "fallback"
                self._notify_status(
                    STATUS_RECONNECTING,
                    f"YouTube エラー — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})...",
                )
                self._notify_system_message(
                    f"[YouTube] エラーが発生しました — 再接続試行中 ({failure_count}/{STREAM_MAX_RETRIES_ON_FAILURE})"
                )
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
                "conn_responses=%d conn_duration_ms=%d",
                reconnect_count, conn_responses, conn_duration_ms,
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
            # （サーバーが即時応答して閉じた場合のレート制御）
            if last_polling_ms is not None:
                self._wait(last_polling_ms / 1000.0)
            else:
                self._wait(3.0)

        # stop_event によって停止
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

                is_backlog = self._is_first_fetch
                self._is_first_fetch = False

                for raw_item in result.get("items", []):
                    if self._stop_event.is_set():
                        break
                    if is_backlog:
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
