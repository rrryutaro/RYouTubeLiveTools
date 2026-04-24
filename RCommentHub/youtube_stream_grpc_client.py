"""
RCommentHub — YouTube Live Chat gRPC ストリーミングクライアント

Google 公式仕様に基づく gRPC server-streaming 実装。
出典: https://developers.google.com/youtube/v3/live/streaming-live-chat

接続方式:
  gRPC server-streaming RPC
  サービス: /youtube.api.v3.V3DataLiveChatMessageService/StreamList
  エンドポイント: dns:///youtube.googleapis.com:443 (TLS)

認証:
  OAuth 2.0: gRPC メタデータ ("authorization", "Bearer <access_token>")
  API キー:  gRPC メタデータ ("x-goog-api-key", "<key>")

生成済みスタブ（proto/stream_list.proto より生成）:
  stream_list_pb2.py
  stream_list_pb2_grpc.py

依存:
  grpcio >= 1.80.0

gRPC channel と StreamList RPC stream の寿命:
  gRPC channel は接続セッション中に1回だけ作成し、維持する。
  StreamList RPC stream は YouTube API 側の既知挙動（Issue 476293143）により
  約10秒で OK status / clean EOF 終了する。その場合は同一 channel / stub 上で
  StreamList を再実行し、nextPageToken を維持して resume する。
"""

import datetime
import logging
import threading
import time

import grpc

import stream_list_pb2
import stream_list_pb2_grpc
from auth_service import AuthService, AUTH_MODE_OAUTH

_logger    = logging.getLogger(__name__)
_route     = logging.getLogger("route_check")
_yt_error  = logging.getLogger("youtube_error")
_api_usage = logging.getLogger("youtube_api_usage")

# ─── 定数 ───────────────────────────────────────────────────────────────────

# Google 公式 gRPC エンドポイント
_GRPC_ENDPOINT = "dns:///youtube.googleapis.com:443"

# リクエストで要求する part パラメーター
_GRPC_PARTS = ["id", "snippet", "authorDetails"]

# 一時失敗時の再試行設定
GRPC_MAX_RETRIES_ON_FAILURE = 5
GRPC_RETRY_DELAY            = 3.0  # 秒

# StreamList clean EOF / OK 終了後の最小待機（急激なタイトループを防ぐ最低限のフロア）
# 実測: YouTube は約10秒ごとに StreamList RPC を clean EOF 終了させる（Issue 476293143）
# backoff は入れない。公式 nextPageToken resume 方針に従い、短周期再実行を許容する。
GRPC_STREAM_RESUME_MIN_WAIT = 0.5  # 秒

# stop_event チェック間隔
_STOP_CHECK_INTERVAL = 0.25

# TypeWrapper.Type enum → REST API 互換の type 文字列
# on_comment の raw dict は既存の CommentItem が解釈するため REST 形式に合わせる
_SNIPPET_TYPE_MAP: dict[int, str] = {
    0:  "unknownType",
    1:  "textMessageEvent",
    2:  "tombstone",
    3:  "fanFundingEvent",
    4:  "chatEndedEvent",
    5:  "sponsorOnlyModeStartedEvent",
    6:  "sponsorOnlyModeEndedEvent",
    7:  "newSponsorEvent",
    8:  "messageDeletedEvent",
    9:  "messageRetractedEvent",
    10: "userBannedEvent",
    15: "superChatEvent",
    16: "superStickerEvent",
    17: "memberMilestoneChatEvent",
    18: "membershipGiftingEvent",
    19: "giftMembershipReceivedEvent",
    20: "pollEvent",
    21: "giftEvent",
}

# CHAT_ENDED_EVENT の type 番号（配信終了シグナル）
_CHAT_ENDED_TYPE = 4


# ─── proto → dict 変換 ──────────────────────────────────────────────────────

def _grpc_message_to_raw_dict(msg: stream_list_pb2.LiveChatMessage) -> dict:
    """
    gRPC proto LiveChatMessage を on_comment コールバックが期待する dict に変換する。

    CommentItem が参照するキー:
      id, snippet.type, snippet.publishedAt, snippet.hasDisplayContent,
      snippet.displayMessage, snippet.liveChatId,
      authorDetails.channelId, authorDetails.displayName,
      authorDetails.channelUrl, authorDetails.profileImageUrl,
      authorDetails.isChatOwner, authorDetails.isChatModerator,
      authorDetails.isChatSponsor, authorDetails.isVerified
    """
    snip = msg.snippet
    auth = msg.author_details

    type_int = snip.type
    type_str = _SNIPPET_TYPE_MAP.get(type_int, f"unknownType_{type_int}")

    raw: dict = {
        "id":   msg.id,
        "kind": msg.kind or "youtube#liveChatMessage",
        "snippet": {
            "type":              type_str,
            "liveChatId":        snip.live_chat_id,
            "publishedAt":       snip.published_at,
            "hasDisplayContent": snip.has_display_content,
            "displayMessage":    snip.display_message,
        },
        "authorDetails": {
            "channelId":        auth.channel_id,
            "displayName":      auth.display_name,
            "channelUrl":       auth.channel_url,
            "profileImageUrl":  auth.profile_image_url,
            "isChatOwner":      auth.is_chat_owner,
            "isChatModerator":  auth.is_chat_moderator,
            "isChatSponsor":    auth.is_chat_sponsor,
            "isVerified":       auth.is_verified,
        },
    }

    if type_int == 1 and snip.HasField("text_message_details"):
        raw["snippet"]["textMessageDetails"] = {
            "messageText": snip.text_message_details.message_text,
        }

    return raw


# ─── gRPC クライアント ────────────────────────────────────────────────────────

class YouTubeStreamGrpcClient:
    """
    YouTube Live Chat gRPC ストリーミングクライアント。

    Google 公式の server-streaming RPC (StreamList) を使用して
    ライブチャットのコメントをリアルタイムで受信する。

    gRPC channel は接続セッション中に維持する。
    StreamList RPC stream が clean EOF / OK 終了した場合は、同一 channel / stub 上で
    StreamList を再実行し nextPageToken で resume する。
    配信終了（CHAT_ENDED_EVENT または offline_at）を検出した場合は停止する。

    コールバック仕様:
      on_comment(raw: dict)            — CommentItem が解釈する REST 互換 dict
      on_status(status: str, msg: str) — YouTubeClient 既存の STATUS_* 定数と同形式
      on_system_message(text: str)     — システムメッセージ文字列
    """

    def __init__(self, auth_service: AuthService):
        self._auth_service = auth_service
        # gRPC ストリーミング統計（run() 実行後に youtube_client.py が読み取る）
        # grpc_stream_calls と YouTube Data API quota の対応:
        #   実測値: StreamList 1 RPC ≈ 5 quota units（2026-04-24 Google Cloud Console 実測）
        #   公式には未公開。SESSION_SUMMARY の estimated_quota_units は推定値。
        self.stats: dict = {
            "grpc_channel_creates":  0,  # gRPC channel 作成回数（通常1セッション1回）
            "grpc_stream_calls":     0,  # StreamList RPC 実行回数
            "grpc_resume_count":     0,  # clean EOF / OK 終了後の StreamList 再実行回数
            "grpc_error_reconnects": 0,  # RpcError 等エラー起因の再試行回数
            "grpc_rpc_errors":       0,  # grpc.RpcError 発生回数（一時・永続含む）
            "grpc_total_responses":  0,  # 全 StreamList 通算の response 受信回数
            "grpc_total_items":      0,  # 全 StreamList 通算の item 受信合計数
            "grpc_zero_responses":   0,  # items=0 だった response 回数
        }

    # ─── 認証 ───────────────────────────────────────────────────────────────

    def _build_metadata(self) -> tuple:
        """
        gRPC メタデータ（認証情報）を構築して返す。

        OAuth モード:
          トークンをリフレッシュし ("authorization", "Bearer <token>") を返す。
        API キーモード:
          ("x-goog-api-key", "<key>") を返す。

        認証情報が取得できない場合は空タプルを返す。
        """
        if not self._auth_service:
            return ()

        if (self._auth_service.is_oauth_mode()
                and self._auth_service.is_authenticated()):
            self._auth_service.refresh_if_needed()
            kwargs = self._auth_service.get_request_kwargs()
            auth_header = kwargs.get("headers", {}).get("Authorization", "")
            if auth_header.startswith("Bearer "):
                return (("authorization", auth_header),)
            _logger.warning("_build_metadata: OAuth mode but no Bearer token")
            return ()

        api_key = (getattr(self._auth_service, "_api_key", "")
                   or getattr(self._auth_service, "api_key", ""))
        if api_key:
            return (("x-goog-api-key", api_key),)

        return ()

    # ─── バックログ判定 ──────────────────────────────────────────────────────

    def _is_backlog(self, published_at: str, connect_time: datetime.datetime) -> bool:
        """published_at が connect_time より前なら True（バックログ扱い）。"""
        if not published_at:
            return True
        try:
            dt = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            return dt < connect_time
        except Exception:
            return True

    # ─── ストリーミングループ ────────────────────────────────────────────────

    def run(
        self,
        live_chat_id:   str,
        stop_event:     threading.Event,
        on_comment,
        on_status,
        on_system_message,
        connect_time:   datetime.datetime,
        notify_overlay: bool = False,
        is_first_fetch: bool = True,
    ) -> str:
        """
        gRPC ストリーミングループをブロッキングで実行する（ワーカースレッドから呼ぶ）。

        gRPC channel は接続セッション中に維持する。
        StreamList RPC stream が clean EOF / OK 終了した場合は、
        同一 channel / stub 上で StreamList を再実行する（nextPageToken を維持）。

        StreamList が約10秒で clean EOF 終了するのは YouTube API 側の既知挙動であり
        （Google Issue Tracker 476293143）、RCommentHub の不具合ではない。

        戻り値:
          "completed"  — ストリームが正常終了（配信終了など）
          "stopped"    — stop_event により停止
          "fallback"   — 一時失敗の再試行上限到達
          "permanent"  — 永続的な失敗（認証エラー・クォータ超過など）
          "normal_end" — 配信終了・削除による正常終了
        """
        next_page_token: str | None = None
        stream_call_count        = 0   # このセッションでの StreamList RPC 実行回数
        failure_count            = 0
        is_first                 = is_first_fetch
        stream_connected         = False
        was_transient_reconnect  = False

        _route.info("[route-check] grpc_stream_attempt live_chat_id=%s", live_chat_id)

        # ─── gRPC channel / stub 作成（接続セッション中に維持） ─────────────
        tls_creds = grpc.ssl_channel_credentials()
        try:
            channel = grpc.secure_channel(_GRPC_ENDPOINT, tls_creds)
            self.stats["grpc_channel_creates"] += 1
            _route.info("[route-check] grpc_channel_created channel_creates=%d",
                        self.stats["grpc_channel_creates"])
        except Exception as e:
            _yt_error.info(
                "EVENT grpc_channel_create_failed route=grpc exception_type=%s "
                "exception_msg=%.200s notify_overlay=%s",
                type(e).__name__, str(e), notify_overlay,
            )
            on_status("disconnected", "gRPC チャンネルの作成に失敗しました")
            on_system_message("[YouTube] gRPC チャンネルの作成に失敗しました。")
            return "permanent"

        stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)

        try:
            # ─── StreamList ループ（同一 channel / stub を維持して繰り返す） ─
            while not stop_event.is_set():

                # ─── resume / reconnect ログ ──────────────────────────────
                if stream_call_count > 0:
                    if was_transient_reconnect:
                        _route.info(
                            "[route-check] grpc_error_reconnect_start attempt=%d "
                            "next_token=%s",
                            stream_call_count, "yes" if next_page_token else "no",
                        )
                    else:
                        # clean EOF / OK 終了後の通常 resume
                        _route.info(
                            "[route-check] grpc_resume_start attempt=%d next_token=%s "
                            "reason=clean_eof_ok known_youtube_issue=476293143",
                            stream_call_count, "yes" if next_page_token else "no",
                        )

                # ─── 認証メタデータ構築（毎回再構築してトークンリフレッシュに対応）
                metadata = self._build_metadata()
                if not metadata:
                    _yt_error.warning(
                        "EVENT grpc_no_metadata route=grpc attempt=%d notify_overlay=%s",
                        stream_call_count, notify_overlay,
                    )
                    on_status("disconnected", "認証情報を取得できませんでした")
                    on_system_message("[YouTube] 認証情報が取得できませんでした。再認証が必要です。")
                    return "permanent"

                # ─── gRPC リクエスト構築 ─────────────────────────────────
                request = stream_list_pb2.LiveChatMessageListRequest(
                    live_chat_id=live_chat_id,
                    max_results=500,
                )
                request.part.extend(_GRPC_PARTS)
                if next_page_token:
                    request.page_token = next_page_token

                # ─── StreamList RPC 実行（同一 channel / stub を再利用） ──
                t0 = time.monotonic()
                try:
                    call = stub.StreamList(request, metadata=metadata)
                    self.stats["grpc_stream_calls"] += 1
                    stream_call_count += 1
                    _api_usage.info(
                        "GRPC_STREAM_CALL attempt=%d page_token=%s "
                        "estimated_quota_units=5 channel_reused=%s",
                        stream_call_count - 1,
                        "yes" if next_page_token else "no",
                        stream_call_count > 1,
                    )

                    conn_responses    = 0
                    t_conn_start      = time.monotonic()
                    chat_ended        = False
                    normal_stream_end = False

                    _route.info(
                        "[route-check] grpc_connected attempt=%d next_token=%s "
                        "channel_creates=%d",
                        stream_call_count - 1,
                        "yes" if next_page_token else "no",
                        self.stats["grpc_channel_creates"],
                    )

                    try:
                        for response in call:
                            if stop_event.is_set():
                                call.cancel()
                                return "stopped"

                            conn_responses += 1

                            # ─── 接続成立ログ（初回のみ） ────────────────
                            if not stream_connected:
                                stream_connected = True
                                failure_count    = 0
                                on_status("receiving", "コメント受信中 (gRPC streamList)")
                                _route.info(
                                    "[route-check] grpc_stream_started "
                                    "effective_route=grpc_streamList"
                                )
                            elif stream_call_count > 1 and conn_responses == 1:
                                if was_transient_reconnect:
                                    _route.info(
                                        "[route-check] grpc_error_reconnect_success "
                                        "attempt=%d",
                                        stream_call_count - 1,
                                    )
                                    on_status("receiving", "コメント受信中 (gRPC streamList)")
                                    on_system_message("再接続に成功しました")
                                else:
                                    # clean EOF resume 成功 → サイレント継続
                                    _route.info(
                                        "[route-check] grpc_resume_success attempt=%d",
                                        stream_call_count - 1,
                                    )
                                was_transient_reconnect = False

                            # ─── next_page_token 更新 ────────────────────
                            if response.next_page_token:
                                if response.next_page_token != next_page_token:
                                    _route.info(
                                        "[route-check] grpc_next_page_token_updated "
                                        "conn_responses=%d",
                                        conn_responses,
                                    )
                                next_page_token = response.next_page_token

                            # ─── offline_at（配信終了）検出 ──────────────
                            if response.offline_at:
                                _route.info(
                                    "[route-check] grpc_offline_at=%s conn_responses=%d",
                                    response.offline_at, conn_responses,
                                )
                                chat_ended = True

                            item_count = len(response.items)
                            self.stats["grpc_total_responses"] += 1
                            self.stats["grpc_total_items"]     += item_count
                            if item_count == 0:
                                self.stats["grpc_zero_responses"] += 1
                            _route.info(
                                "[route-check] grpc_response_received items=%d "
                                "conn_responses=%d attempt=%d next_token=%s offline=%s",
                                item_count, conn_responses, stream_call_count - 1,
                                "yes" if response.next_page_token else "no",
                                response.offline_at or "-",
                            )

                            # ─── メッセージ処理 ──────────────────────────
                            for item_proto in response.items:
                                if stop_event.is_set():
                                    call.cancel()
                                    return "stopped"

                                if item_proto.snippet.type == _CHAT_ENDED_TYPE:
                                    _route.info(
                                        "[route-check] grpc_chat_ended_event "
                                        "conn_responses=%d", conn_responses,
                                    )
                                    chat_ended = True

                                raw = _grpc_message_to_raw_dict(item_proto)

                                if is_first:
                                    pub = raw["snippet"].get("publishedAt", "")
                                    if self._is_backlog(pub, connect_time):
                                        raw["_is_backlog"] = True

                                _api_usage.info(
                                    "GRPC_MESSAGE attempt=%d type=%s id=%.20s "
                                    "author=%.30s backlog=%s",
                                    stream_call_count - 1,
                                    raw["snippet"].get("type", "?"),
                                    raw.get("id", "?"),
                                    raw["authorDetails"].get("displayName", "?"),
                                    raw.get("_is_backlog", False),
                                )

                                if on_comment:
                                    on_comment(raw)

                            if is_first and item_count > 0:
                                is_first = False

                        # for ループ正常終了（サーバーが StreamList stream を clean EOF / OK 終了）
                        normal_stream_end = True

                    except grpc.RpcError as e:
                        code   = e.code()
                        detail = e.details() or ""
                        conn_duration_ms = int((time.monotonic() - t_conn_start) * 1000)

                        self.stats["grpc_rpc_errors"] += 1
                        _yt_error.info(
                            "EVENT grpc_rpc_error route=grpc attempt=%d "
                            "conn_responses=%d status_code=%s detail=%.200s "
                            "conn_duration_ms=%d notify_overlay=%s",
                            stream_call_count - 1, conn_responses,
                            code.name, detail, conn_duration_ms, notify_overlay,
                        )

                        if code == grpc.StatusCode.CANCELLED:
                            return "stopped"

                        if code == grpc.StatusCode.NOT_FOUND:
                            if stream_connected:
                                on_status("disconnected", "配信が削除されたため接続を終了しました")
                                on_system_message("配信が削除されたため接続を終了しました")
                                return "normal_end"
                            on_status("disconnected", "接続に失敗しました（ライブチャットが見つかりません）")
                            on_system_message("接続に失敗しました（ライブチャットが見つかりません）")
                            return "permanent"

                        if code == grpc.StatusCode.PERMISSION_DENIED:
                            if "liveChatEnded" in detail:
                                on_status("disconnected", "配信が終了したため接続を終了しました")
                                on_system_message("配信が終了したため接続を終了しました")
                                return "normal_end"
                            on_status("disconnected", "接続に失敗しました（権限エラー）")
                            on_system_message(
                                f"[YouTube] 権限エラー (PERMISSION_DENIED): {detail[:100]}"
                            )
                            return "permanent"

                        if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
                            on_status(
                                "disconnected",
                                "YouTube クォータ超過 — 本日の API 使用量が上限に達しました",
                            )
                            on_system_message(
                                "[YouTube] クォータ超過 (RESOURCE_EXHAUSTED) "
                                "— 翌日まで接続できません。"
                            )
                            return "permanent"

                        if code == grpc.StatusCode.UNAUTHENTICATED:
                            on_status("disconnected", "認証エラー (UNAUTHENTICATED) — 再認証が必要です")
                            on_system_message("[YouTube] 認証エラー — 再認証してください。")
                            return "permanent"

                        # UNAVAILABLE / DEADLINE_EXCEEDED / その他 → 一時失敗（同一 channel で再試行）
                        failure_count += 1
                        _route.info(
                            "[route-check] grpc_transient_error fc=%d/%d code=%s",
                            failure_count, GRPC_MAX_RETRIES_ON_FAILURE, code.name,
                        )
                        if failure_count >= GRPC_MAX_RETRIES_ON_FAILURE:
                            on_status(
                                "disconnected",
                                f"接続に失敗しました — 再試行上限 "
                                f"({GRPC_MAX_RETRIES_ON_FAILURE} 回) に達しました",
                            )
                            on_system_message(
                                f"[YouTube] gRPC 接続エラー — 再試行 "
                                f"{GRPC_MAX_RETRIES_ON_FAILURE} 回に達したため停止します。"
                            )
                            return "fallback"

                        on_status(
                            "reconnecting",
                            f"接続が切れたため再接続します "
                            f"({failure_count}/{GRPC_MAX_RETRIES_ON_FAILURE})",
                        )
                        on_system_message(
                            f"[YouTube] 接続が切れました — 再接続試行中 "
                            f"({failure_count}/{GRPC_MAX_RETRIES_ON_FAILURE})"
                        )
                        _wait_interruptible(stop_event, GRPC_RETRY_DELAY)
                        if stop_event.is_set():
                            return "stopped"
                        was_transient_reconnect = True
                        self.stats["grpc_error_reconnects"] += 1
                        continue  # 同一 channel で StreamList を再実行

                except Exception as e:
                    # stub.StreamList() その他の予期しないエラー（channel は維持）
                    failure_count += 1
                    self.stats["grpc_error_reconnects"] += 1
                    _yt_error.info(
                        "EVENT grpc_unexpected_error route=grpc attempt=%d "
                        "exception_type=%s exception_msg=%.200s notify_overlay=%s",
                        stream_call_count - 1, type(e).__name__, str(e), notify_overlay,
                    )
                    if failure_count >= GRPC_MAX_RETRIES_ON_FAILURE:
                        on_status("disconnected", "接続に失敗しました")
                        on_system_message("[YouTube] 予期しないエラーで接続に失敗しました。")
                        return "fallback"
                    _wait_interruptible(stop_event, GRPC_RETRY_DELAY)
                    if stop_event.is_set():
                        return "stopped"
                    was_transient_reconnect = True
                    continue

                # ─── StreamList stream 正常終了（clean EOF / OK）の処理 ──
                if normal_stream_end:
                    conn_duration_ms = int((time.monotonic() - t_conn_start) * 1000)
                    _route.info(
                        "[route-check] grpc_stream_iterator_completed attempt=%d "
                        "conn_responses=%d conn_duration_ms=%d chat_ended=%s "
                        "stream_end_reason=clean_eof_ok known_youtube_issue=476293143",
                        stream_call_count - 1, conn_responses,
                        conn_duration_ms, chat_ended,
                    )

                    if chat_ended:
                        on_status("disconnected", "配信が終了したため接続を終了しました")
                        on_system_message("配信が終了したため接続を終了しました")
                        return "normal_end"

                    if stop_event.is_set():
                        return "stopped"

                    # clean EOF / OK → 同一 channel / stub で StreamList を再実行
                    failure_count = 0
                    was_transient_reconnect = False
                    self.stats["grpc_resume_count"] += 1
                    _route.info(
                        "[route-check] grpc_resume_queued resume_count=%d "
                        "next_token=%s channel_creates=%d",
                        self.stats["grpc_resume_count"],
                        "yes" if next_page_token else "no",
                        self.stats["grpc_channel_creates"],
                    )
                    _wait_interruptible(stop_event, GRPC_STREAM_RESUME_MIN_WAIT)
                    if stop_event.is_set():
                        return "stopped"

            # stop_event により停止
            return "stopped"

        finally:
            # 接続セッション終了時に channel を閉じる
            try:
                channel.close()
                _route.info(
                    "[route-check] grpc_channel_closed stream_calls=%d resume_count=%d",
                    self.stats["grpc_stream_calls"],
                    self.stats["grpc_resume_count"],
                )
            except Exception:
                pass


def _wait_interruptible(stop_event: threading.Event, seconds: float):
    """stop_event を監視しながら待機する。"""
    waited = 0.0
    while waited < seconds and not stop_event.is_set():
        time.sleep(_STOP_CHECK_INTERVAL)
        waited += _STOP_CHECK_INTERVAL
