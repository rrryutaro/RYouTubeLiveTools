"""
RCommentHub — ソースアダプタ

YouTube / Twitch 等の各プラットフォームを統一インターフェースで扱う抽象層。

各アダプタの責務:
  - verify_target(url):  接続先の検証（同期）
  - connect(...):        コメント受信開始（非同期）
  - disconnect():        受信停止
  - is_running:          受信中か

コメント正規化:
  Twitch 等のプラットフォーム固有イベントを CommentItem が読める dict 形式に変換する。
  YouTube API レスポンス形式（snippet / authorDetails 構造）を共通フォーマットとして採用する。
"""

import datetime
import logging
from abc import ABC, abstractmethod

_logger = logging.getLogger(__name__)


class SourceAdapterError(Exception):
    """アダプタ操作中のエラー"""
    pass


class SourceAdapter(ABC):
    """
    コメントソースの共通インターフェース（抽象基底クラス）。

    各プラットフォーム固有の実装がこのクラスを継承する。
    """

    @abstractmethod
    def verify_target(self, url: str) -> dict:
        """
        接続先を検証する（同期実行）。

        成功時: {"title": str, ...} を含む dict を返す
        失敗時: SourceAdapterError を raise する

        サブクラスは verify_target の結果を内部に保持し、
        後続の connect() で使用できるようにすること。
        """

    @abstractmethod
    def connect(self, on_comment, on_status, **kwargs):
        """
        コメント受信を開始する（非同期・別スレッドで実行）。

        on_comment(raw: dict)            — コメント1件ごとに呼ばれる（ワーカースレッド）
        on_status(status: str, msg: str) — 状態変化時に呼ばれる（ワーカースレッド）
        **kwargs                         — プラットフォーム固有の追加引数
        """

    @abstractmethod
    def disconnect(self):
        """受信を停止する（ブロックしない）"""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """受信中なら True"""

    def normalize_comment(self, raw_event: dict) -> dict:
        """
        プラットフォーム固有イベントを CommentItem 用の共通 dict に変換する。
        デフォルト実装はそのまま返す（YouTube はすでに共通形式）。
        """
        return raw_event


# ─── YouTube アダプタ ─────────────────────────────────────────────────────────

class YouTubeSourceAdapter(SourceAdapter):
    """
    YouTube Live Chat API アダプタ。

    既存の YouTubeClient をラップして SourceAdapter インターフェースを提供する。
    既存動作を維持しながら段階的に移行できるよう設計する。
    """

    def __init__(self, auth_service):
        from youtube_client import YouTubeClient
        self._client       = YouTubeClient()
        self._auth_service = auth_service
        self._live_chat_id: str  = ""
        self._verify_result: dict = {}

    def verify_target(self, url: str) -> dict:
        """
        YouTube URL または動画IDから接続情報を取得する。
        成功時は {"live_chat_id", "title", "video_id", "stream_status"} を返す。
        """
        from comment_controller import _extract_video_id
        video_id = _extract_video_id(url)
        self._client.set_auth_service(self._auth_service)
        result = self._client.verify(video_id)
        self._live_chat_id  = result.get("live_chat_id", "")
        self._verify_result = result
        return result

    def set_verify_result(self, result: dict):
        """外部から verify 結果を設定する（CommentController からの直接呼び出し用）"""
        self._live_chat_id  = result.get("live_chat_id", "")
        self._verify_result = result

    def connect(self, on_comment, on_status, on_fallback_confirm=None, **kwargs):
        self._client.set_auth_service(self._auth_service)
        self._client.start(
            live_chat_id=self._live_chat_id,
            on_comment=on_comment,
            on_status=on_status,
            on_fallback_confirm=on_fallback_confirm,
        )

    def disconnect(self):
        self._client.stop()

    @property
    def is_running(self) -> bool:
        return self._client.is_running
