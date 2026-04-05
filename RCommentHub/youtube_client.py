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

import threading
import time
import requests

from auth_service import AuthService, AUTH_MODE_OAUTH, AUTH_MODE_API_KEY

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
              on_comment=None, on_status=None):
        """
        コメント受信を別スレッドで開始する。

        on_comment(raw: dict)            — コメント1件ごと（ワーカースレッド文脈）
        on_status(status: str, msg: str) — 状態変化時（ワーカースレッド文脈）

        呼び出し元は root.after(0, ...) で UI スレッドへ転送すること。
        """
        if self._thread and self._thread.is_alive():
            return

        self._live_chat_id   = live_chat_id
        self._next_token     = None
        self._on_comment     = on_comment
        self._on_status      = on_status
        self._stop_event.clear()
        self._is_first_fetch = True

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

        if should_try_stream:
            stream_result = self._try_stream_loop()
            # stream_result: "completed"（ストリーム終了） / "stopped"（停止指示） / "fallback"（失敗）
            if stream_result == "stopped":
                return
            # "completed" → ストリーム終了後も list ポーリングで継続（OAuth 実機確認用フォールバック含む）
            # "fallback"  → 非対応・接続失敗、list ポーリングへ
            if stream_result == "completed":
                self._notify_status(STATUS_CONNECTING, "ストリーム終了、ポーリング方式で継続中 (list)...")
            else:
                self._notify_status(STATUS_CONNECTING, "ポーリング方式で再接続中 (list)...")

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
          - 現実装: HTTP streaming (iter_lines) で試みる
          - 応答が空・形式不一致・接続断の場合は "fallback" を返す

        注意:
          streamList の実際の HTTP レスポンス形式（改行区切り JSON / SSE / gRPC）は
          実機確認が必要。形式が一致しない場合は fallback 扱いとする。
        """
        import json as _json

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
            resp = requests.get(
                url, params=base_params,
                timeout=(STREAM_CONNECT_TIMEOUT, STREAM_READ_TIMEOUT),
                stream=True,
                **kwargs,
            )
        except requests.RequestException:
            return "fallback"

        # 接続可能なステータスコードでなければフォールバック
        if resp.status_code == 404:
            return "fallback"
        if resp.status_code not in (200, 206):
            return "fallback"

        # Content-Type が JSON / event-stream でなければ形式不一致としてフォールバック
        ct = resp.headers.get("Content-Type", "")
        if "json" not in ct and "event-stream" not in ct and "octet-stream" not in ct:
            # 形式が想定外の場合はフォールバックへ
            resp.close()
            return "fallback"

        self._notify_status(STATUS_RECEIVING, "コメント受信中 (streamList)")
        is_first    = self._is_first_fetch
        got_any     = False

        try:
            for line in resp.iter_lines(chunk_size=None):
                if self._stop_event.is_set():
                    return "stopped"
                if not line:
                    continue

                # SSE 形式の場合は "data: " プレフィックスを除去
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="ignore")
                if line.startswith("data:"):
                    line = line[5:].strip()

                try:
                    data = _json.loads(line)
                except Exception:
                    continue

                got_any = True

                if "nextPageToken" in data:
                    self._next_token = data["nextPageToken"]

                for raw_item in data.get("items", []):
                    if self._stop_event.is_set():
                        return "stopped"
                    if is_first:
                        raw_item["_is_backlog"] = True
                    if self._on_comment:
                        self._on_comment(raw_item)

                is_first = False
                self._is_first_fetch = False

        except Exception:
            if not got_any:
                # 一度もデータが来ずに例外 → fallback
                return "fallback"

        if self._stop_event.is_set():
            self._notify_status(STATUS_DISCONNECTED, "受信停止")
            return "stopped"

        self._notify_status(STATUS_DISCONNECTED, "ストリーム終了")
        return "completed"

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
