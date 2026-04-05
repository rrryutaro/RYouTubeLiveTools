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
  2. streamList で接続を試みる
  3. streamList が利用できない場合 list ポーリングへ自動フォールバック
  4. nextPageToken を保持し、再接続時に pageToken として再利用する

別スレッドで動作。UI コールバックはメインスレッド側で root.after() して使うこと。
"""

import logging
import threading
import time
import requests

from auth_service import AuthService, AUTH_MODE_OAUTH, AUTH_MODE_API_KEY

_logger = logging.getLogger(__name__)
_route  = logging.getLogger("route_check")   # 経路判定用（route_check.log へ出力）

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
        self._on_fallback_confirm    = None   # (reason: str) -> bool | None
        self._is_first_fetch: bool   = True   # 初回取得（バックログ）判定用
        self._use_stream: bool       = True   # True: streamList 試行, False: list のみ

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

        try:
            resp = requests.get(url, params=base_params, timeout=10, **kwargs)
        except requests.RequestException as e:
            raise YouTubeClientError(f"通信エラー: {e}")

        self._raise_for_status(resp)

        data  = resp.json()
        items = data.get("items", [])
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
              on_comment=None, on_status=None, on_fallback_confirm=None):
        """
        コメント受信を別スレッドで開始する。

        on_comment(raw: dict)            — コメント1件ごと（ワーカースレッド文脈）
        on_status(status: str, msg: str) — 状態変化時（ワーカースレッド文脈）
        on_fallback_confirm(reason: str) -> bool
            — streamList 失敗時に list fallback を許可するか確認するコールバック。
              ワーカースレッドから呼ばれる（内部でブロック待機を行うこと）。
              True: 今回のみ list fallback を許可、False/None: 拒否（停止）。
              未指定時は常に拒否（自動 fallback しない）。

        呼び出し元は root.after(0, ...) で UI スレッドへ転送すること。
        """
        if self._thread and self._thread.is_alive():
            return

        self._live_chat_id      = live_chat_id
        self._next_token        = None
        self._on_comment        = on_comment
        self._on_status         = on_status
        self._on_fallback_confirm = on_fallback_confirm
        self._stop_event.clear()
        self._is_first_fetch    = True

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

    # ─── fallback 許可確認 ───────────────────────────────────────────────────

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
          現時点での実装: HTTP streaming (chunked transfer) として試みる。
          応答形式が公式と一致しない場合は自動的に list フォールバックに移行する。
        """
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
            # stream_result: "completed"（ストリーム終了） / "stopped"（停止指示） / "fallback"（失敗）
            if stream_result == "stopped":
                return

            # streamList が終了 / 失敗 → 自動 fallback は行わず、ユーザーへ確認
            fallback_reason = (
                "stream_completed" if stream_result == "completed"
                else "stream_failed"
            )
            if self._request_fallback_permission(fallback_reason):
                _route.info("[route-check] fallback_allowed_by_user")
                _route.info("[route-check] effective_route=list_fallback reason=user_allowed")
                self._notify_status(STATUS_CONNECTING, "list 方式で継続中...")
            else:
                _route.info("[route-check] fallback_denied_by_user")
                _route.info("[route-check] effective_route=stopped reason=user_denied_fallback")
                self._notify_status(
                    STATUS_DISCONNECTED,
                    "streamList 継続受信に失敗しました。list 方式への切替は未許可のため停止します。",
                )
                return

        self._poll_loop()

    def _try_stream_loop(self) -> str:
        """
        liveChatMessages.streamList による接続を試みる。

        戻り値:
          "completed" — ストリームが正常に終了した（ライブ終了など）
          "stopped"   — 停止指示により中断した
          "fallback"  — 接続失敗または非対応。list フォールバックへ移行すべき状態

        公式仕様に沿った実装方針:
          - streamList は低レイテンシのサーバーストリーミング接続
          - 各レスポンスに nextPageToken が含まれる（切断/再接続時の再開用）
          - 現実装: resp.json() で全体を一括取得して処理（i045 で iter_lines から変更）
          - 応答が空・形式不一致・接続断の場合は "fallback" を返す

        実機確認結果（i044〜i047）:
          - レスポンスは application/json の標準 JSON 形式（即時レスポンス型）
          - resp.json() で全体取得後、nextPageToken を使ってループ継続（i047）
          - list fallback への自動切替は廃止済み（i046）
        """

        url              = f"{_API_BASE}/liveChat/messages"
        first_msg_logged = False
        reconnect_count  = 0
        is_first         = self._is_first_fetch

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

            if reconnect_count > 0:
                _route.info("[route-check] stream_reconnect_start attempt=%d", reconnect_count)

            # ─── HTTP リクエスト ──────────────────────────────────────────────
            try:
                resp = requests.get(
                    url, params=base_params,
                    timeout=(STREAM_CONNECT_TIMEOUT, STREAM_READ_TIMEOUT),
                    stream=True,
                    **kwargs,
                )
            except requests.RequestException as e:
                _route.info("[route-check] stream_fallback reason=connection_error detail=%s", e)
                return "fallback"

            if resp.status_code == 404:
                _route.info("[route-check] stream_fallback reason=http_404")
                return "fallback"
            if resp.status_code == 403:
                try:
                    reason_403 = (resp.json()
                                  .get("error", {})
                                  .get("errors", [{}])[0]
                                  .get("reason", ""))
                except Exception:
                    reason_403 = ""
                if reason_403 == "rateLimitExceeded":
                    # 一時的なレートリミット — fallback ではなく再試行
                    backoff_secs = 5.0
                    _route.info("[route-check] stream_rate_limited reason=rateLimitExceeded")
                    _route.info("[route-check] stream_retry_backoff_seconds=%.1f", backoff_secs)
                    self._wait(backoff_secs)
                    continue
                # forbidden / liveChatEnded / liveChatDisabled 等 → fallback へ
                _route.info("[route-check] stream_fallback reason=%s status=403",
                            reason_403 or "forbidden")
                return "fallback"
            if resp.status_code not in (200, 206):
                _route.info("[route-check] stream_fallback reason=http_error status=%d",
                            resp.status_code)
                return "fallback"

            ct = resp.headers.get("Content-Type", "")
            if "json" not in ct and "event-stream" not in ct and "octet-stream" not in ct:
                _route.info("[route-check] stream_fallback reason=content_type_mismatch ct=%s", ct)
                resp.close()
                return "fallback"

            # 接続確認ログ
            if reconnect_count == 0:
                _route.info("[route-check] stream_started ct=%s", ct)
            else:
                _route.info("[route-check] stream_reconnect_success attempt=%d", reconnect_count)

            self._notify_status(STATUS_RECEIVING, "コメント受信中 (streamList)")

            if self._stop_event.is_set():
                return "stopped"

            # ─── レスポンス解析 ───────────────────────────────────────────────
            try:
                data = resp.json()
            except Exception as e:
                _route.info("[route-check] stream_fallback reason=json_parse_error detail=%s", e)
                return "fallback"

            items     = data.get("items", [])
            has_token = "nextPageToken" in data
            _route.info(
                "[route-check] stream_response_parsed items=%d has_token=%s attempt=%d",
                len(items), "yes" if has_token else "no", reconnect_count,
            )

            if has_token:
                self._next_token = data["nextPageToken"]

            # ─── メッセージ処理 ───────────────────────────────────────────────
            if items:
                if not first_msg_logged:
                    _route.info("[route-check] stream_first_message_received")
                    _route.info("[route-check] effective_route=streamList")
                    first_msg_logged = True
                for raw_item in items:
                    if self._stop_event.is_set():
                        return "stopped"
                    if is_first:
                        raw_item["_is_backlog"] = True
                    if self._on_comment:
                        self._on_comment(raw_item)
                if is_first:
                    self._is_first_fetch = False
                    is_first = False

            # ─── 継続判断 ─────────────────────────────────────────────────────
            if not has_token:
                # nextPageToken なし → ストリーム終了
                if not first_msg_logged:
                    _route.info("[route-check] stream_completed_no_data")
                if self._stop_event.is_set():
                    return "stopped"
                self._notify_status(STATUS_DISCONNECTED, "ストリーム終了")
                return "completed"

            # nextPageToken あり → streamList 継続
            reconnect_count += 1
            _route.info("[route-check] stream_continues_waiting attempt=%d", reconnect_count)

            # pollingIntervalMillis をそのまま待機時間に使用。
            # items 件数による短縮は行わない（0.5s 短縮が 403 の原因だったため廃止）。
            polling_ms = data.get("pollingIntervalMillis")
            if polling_ms is not None:
                wait_secs = polling_ms / 1000.0
                _route.info("[route-check] stream_polling_interval_ms=%d", int(polling_ms))
            else:
                wait_secs = 3.0  # API から取得できない場合の安全固定値
            self._wait(wait_secs)

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

        try:
            resp = requests.get(url, params=base_params, timeout=15, **kwargs)
        except requests.RequestException as e:
            raise YouTubeClientError(f"通信エラー: {e}")

        if resp.status_code == 403:
            try:
                reason = (resp.json()
                          .get("error", {})
                          .get("errors", [{}])[0]
                          .get("reason", ""))
            except Exception:
                reason = ""
            if reason == "liveChatEnded":
                raise YouTubeClientError("liveChatEnded")
            raise YouTubeClientError(f"権限エラー (403): {reason or 'forbidden'}")

        if resp.status_code == 404:
            raise YouTubeClientError(
                "liveChatId が見つかりません (404)。配信が終了した可能性があります。"
            )

        if resp.status_code != 200:
            raise YouTubeClientError(f"API エラー: HTTP {resp.status_code}")

        return resp.json()

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
