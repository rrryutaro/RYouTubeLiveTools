"""
RCommentHub — YouTube Live Chat API クライアント
  - requests のみ使用（google-api-python-client 不要）
  - API キー方式（read-only）
  - liveChatMessages.list + nextPageToken によるポーリング
  - 別スレッドで動作。UI コールバックはメインスレッド側で root.after() して使うこと
"""

import threading
import time
import requests

# ─── YouTube Data API v3 エンドポイント ─────────────────────────────────────
_API_BASE = "https://www.googleapis.com/youtube/v3"

# ─── 接続状態定数 ────────────────────────────────────────────────────────────
STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTING   = "connecting"
STATUS_RECEIVING    = "receiving"
STATUS_RECONNECTING = "reconnecting"
STATUS_ERROR        = "error"

# ─── ポーリング設定 ──────────────────────────────────────────────────────────
MAX_RETRIES       = 5
RETRY_BASE_DELAY  = 2.0    # 秒（指数バックオフのベース）
POLL_DEFAULT_MS   = 5000   # デフォルトポーリング間隔（ms）
POLL_WAIT_STEP    = 0.25   # stop_event チェック間隔（秒）


class YouTubeClientError(Exception):
    """API エラーや接続失敗を表す例外"""
    pass


class YouTubeClient:
    """YouTube Live Chat API クライアント"""

    def __init__(self):
        self._api_key: str       = ""
        self._live_chat_id: str  = ""
        self._next_token: str | None = None
        self._stop_event         = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_comment         = None   # (raw: dict) -> None
        self._on_status          = None   # (status: str, message: str) -> None

    # ─── 接続確認（同期。呼び出し元スレッドでブロックする）──────────────────

    def verify(self, video_id: str, api_key: str) -> dict:
        """
        動画 ID からライブチャット情報を取得する（同期）。

        成功時の戻り値:
            {
                "live_chat_id": str,
                "title": str,
                "video_id": str,
                "stream_status": "live",
            }

        失敗時は YouTubeClientError を raise する。
        """
        url = f"{_API_BASE}/videos"
        params = {
            "id":   video_id.strip(),
            "part": "liveStreamingDetails,snippet",
            "key":  api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            raise YouTubeClientError(f"通信エラー: {e}")

        if resp.status_code == 400:
            raise YouTubeClientError("リクエストが不正です。API キーと動画 ID を確認してください。")
        if resp.status_code == 403:
            raise YouTubeClientError("API キーが無効または権限が不足しています (403)。")
        if resp.status_code != 200:
            raise YouTubeClientError(f"API エラー: HTTP {resp.status_code}")

        data  = resp.json()
        items = data.get("items", [])
        if not items:
            raise YouTubeClientError(
                "動画が見つかりません。動画 ID を確認してください。"
            )

        item  = items[0]
        title = item.get("snippet", {}).get("title", "")
        lsd   = item.get("liveStreamingDetails", {})
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
            "title": title,
            "video_id": video_id.strip(),
            "stream_status": "live",
        }

    # ─── ポーリング開始 ──────────────────────────────────────────────────────

    def start(self, live_chat_id: str, api_key: str,
              on_comment, on_status):
        """
        コメント受信ポーリングを別スレッドで開始する。

        on_comment(raw: dict) — コメント1件ごとに呼ばれる（ワーカースレッド文脈）
        on_status(status: str, message: str) — 状態変化時（ワーカースレッド文脈）

        呼び出し元は root.after(0, ...) でUIスレッドへ転送すること。
        """
        if self._thread and self._thread.is_alive():
            return

        self._api_key      = api_key
        self._live_chat_id = live_chat_id
        self._next_token   = None
        self._on_comment   = on_comment
        self._on_status    = on_status
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """ポーリングを停止する（ブロックしない）"""
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ─── ポーリングループ（ワーカースレッド） ────────────────────────────────

    def _poll_loop(self):
        self._notify_status(STATUS_RECEIVING, "コメント受信中")
        retry_count   = 0
        poll_interval = POLL_DEFAULT_MS / 1000.0

        while not self._stop_event.is_set():
            try:
                result = self._fetch_messages()
                retry_count   = 0
                poll_interval = result.get("pollingIntervalMillis",
                                           POLL_DEFAULT_MS) / 1000.0

                for raw_item in result.get("items", []):
                    if self._stop_event.is_set():
                        break
                    if self._on_comment:
                        self._on_comment(raw_item)

                self._next_token = result.get("nextPageToken")

            except YouTubeClientError as e:
                msg = str(e)

                # ライブ終了の判定
                if "liveChatEnded" in msg:
                    self._notify_status(STATUS_DISCONNECTED,
                                        "ライブ配信が終了しました")
                    return

                retry_count += 1
                if retry_count > MAX_RETRIES:
                    self._notify_status(STATUS_ERROR,
                                        f"再接続上限 ({MAX_RETRIES} 回) に達しました: {msg}")
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

    def _fetch_messages(self) -> dict:
        """liveChatMessages.list を呼び出してレスポンス dict を返す"""
        url = f"{_API_BASE}/liveChat/messages"
        params = {
            "liveChatId": self._live_chat_id,
            "part":       "id,snippet,authorDetails",
            "key":        self._api_key,
        }
        if self._next_token:
            params["pageToken"] = self._next_token

        try:
            resp = requests.get(url, params=params, timeout=15)
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

    def _wait(self, seconds: float):
        """stop_event を監視しながら待機"""
        waited = 0.0
        while waited < seconds and not self._stop_event.is_set():
            time.sleep(POLL_WAIT_STEP)
            waited += POLL_WAIT_STEP

    def _notify_status(self, status: str, message: str):
        if self._on_status:
            self._on_status(status, message)
