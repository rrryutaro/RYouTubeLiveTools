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

# サーバー側正常クローズ後の最小待機（急激なループを防ぐ）
GRPC_SERVER_CLOSE_MIN_WAIT = 1.0  # 秒

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
    # proto2 optional message fields: accessing returns default empty message if not set
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

    # textMessageEvent の場合 textMessageDetails を追加
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

    接続が切れた場合は next_page_token で resume しながら再接続する。
    配信終了（CHAT_ENDED_EVENT または offline_at）を検出した場合は停止する。

    コールバック仕様:
      on_comment(raw: dict)            — CommentItem が解釈する REST 互換 dict
      on_status(status: str, msg: str) — YouTubeClient 既存の STATUS_* 定数と同形式
      on_system_message(text: str)     — システムメッセージ文字列
    """

    def __init__(self, auth_service: AuthService):
        self._auth_service = auth_service
        # gRPC ストリーミング統計（run() 実行後に youtube_client.py が読み取る）
        self.stats: dict = {
            "grpc_stream_calls":         0,
            "grpc_server_close_resumes": 0,
            "grpc_failure_reconnects":   0,
            "grpc_total_responses":      0,
            "grpc_total_items":          0,
            "grpc_zero_responses":       0,
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
            # リフレッシュ試行
            self._auth_service.refresh_if_needed()
            kwargs = self._auth_service.get_request_kwargs()
            auth_header = kwargs.get("headers", {}).get("Authorization", "")
            if auth_header.startswith("Bearer "):
                # gRPC メタデータはヘッダ名を小文字にする（HTTP/2 仕様）
                return (("authorization", auth_header),)
            _logger.warning("_build_metadata: OAuth mode but no Bearer token")
            return ()

        # API キーモード（gRPC は x-goog-api-key をサポート）
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

        サーバーが接続を切った場合は next_page_token で resume し再接続する。
        配信終了または stop_event を検出した時点で返る。

        戻り値:
          "completed"  — ストリームが正常終了（配信終了など）
          "stopped"    — stop_event により停止
          "fallback"   — 一時失敗の再試行上限到達
          "permanent"  — 永続的な失敗（認証エラー・クォータ超過など）
          "normal_end" — 配信終了・削除による正常終了
        """
        next_page_token: str | None = None
        reconnect_count          = 0
        failure_count            = 0
        is_first                 = is_first_fetch
        stream_connected         = False
        was_transient_reconnect  = False  # True = 直前の再接続がエラー起因（サーバークローズ resume は False）

        _route.info("[route-check] grpc_stream_attempt live_chat_id=%s", live_chat_id)

        # TLS チャンネル認証情報（接続ごとに再利用可能）
        tls_creds = grpc.ssl_channel_credentials()

        while not stop_event.is_set():

            # ─── 再接続ログ ──────────────────────────────────────────────────
            if reconnect_count > 0:
                _route.info(
                    "[route-check] grpc_reconnect_start attempt=%d next_token=%s",
                    reconnect_count, "yes" if next_page_token else "no",
                )

            # ─── 認証メタデータ構築（毎回再構築してトークンリフレッシュに対応）──
            metadata = self._build_metadata()
            if not metadata:
                _yt_error.warning(
                    "EVENT grpc_no_metadata route=grpc attempt=%d notify_overlay=%s",
                    reconnect_count, notify_overlay,
                )
                on_status("disconnected", "認証情報を取得できませんでした")
                on_system_message("[YouTube] 認証情報が取得できませんでした。再認証が必要です。")
                return "permanent"

            # ─── gRPC リクエスト構築 ─────────────────────────────────────────
            request = stream_list_pb2.LiveChatMessageListRequest(
                live_chat_id=live_chat_id,
                max_results=500,
            )
            request.part.extend(_GRPC_PARTS)
            if next_page_token:
                request.page_token = next_page_token

            # ─── gRPC 接続・ストリーム受信 ────────────────────────────────────
            t0 = time.monotonic()
            try:
                with grpc.secure_channel(_GRPC_ENDPOINT, tls_creds) as channel:
                    stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)
                    call = stub.StreamList(request, metadata=metadata)
                    self.stats["grpc_stream_calls"] += 1

                    conn_responses   = 0
                    t_conn_start     = time.monotonic()
                    chat_ended       = False
                    normal_stream_end = False

                    _route.info(
                        "[route-check] grpc_connected attempt=%d next_token=%s",
                        reconnect_count, "yes" if next_page_token else "no",
                    )

                    try:
                        for response in call:
                            if stop_event.is_set():
                                call.cancel()
                                return "stopped"

                            conn_responses += 1

                            # ─── 接続成立ログ（初回のみ）────────────────────
                            if not stream_connected:
                                stream_connected = True
                                failure_count    = 0
                                on_status("receiving", "コメント受信中 (gRPC streamList)")
                                _route.info(
                                    "[route-check] grpc_stream_started "
                                    "effective_route=grpc_streamList"
                                )
                            elif reconnect_count > 0 and conn_responses == 1:
                                if was_transient_reconnect:
                                    # エラー起因の再接続成功 → 状態を receiving に戻してユーザー通知
                                    _route.info(
                                        "[route-check] grpc_reconnect_success attempt=%d",
                                        reconnect_count,
                                    )
                                    on_status("receiving", "コメント受信中 (gRPC streamList)")
                                    on_system_message("再接続に成功しました")
                                else:
                                    # サーバークローズ後の通常 resume → サイレント（ユーザー通知不要）
                                    _route.info(
                                        "[route-check] grpc_resume_success attempt=%d",
                                        reconnect_count,
                                    )
                                was_transient_reconnect = False

                            # ─── next_page_token 更新 ────────────────────────
                            if response.next_page_token:
                                if response.next_page_token != next_page_token:
                                    _route.info(
                                        "[route-check] grpc_next_page_token_updated "
                                        "conn_responses=%d",
                                        conn_responses,
                                    )
                                next_page_token = response.next_page_token

                            # ─── offline_at（配信終了）検出 ──────────────────
                            if response.offline_at:
                                _route.info(
                                    "[route-check] grpc_offline_at=%s conn_responses=%d",
                                    response.offline_at, conn_responses,
                                )
                                chat_ended = True

                            item_count = len(response.items)
                            self.stats["grpc_total_responses"] += 1
                            self.stats["grpc_total_items"] += item_count
                            if item_count == 0:
                                self.stats["grpc_zero_responses"] += 1
                            _route.info(
                                "[route-check] grpc_response_received items=%d "
                                "conn_responses=%d attempt=%d next_token=%s offline=%s",
                                item_count, conn_responses, reconnect_count,
                                "yes" if response.next_page_token else "no",
                                response.offline_at or "-",
                            )

                            # ─── メッセージ処理 ──────────────────────────────
                            for item_proto in response.items:
                                if stop_event.is_set():
                                    call.cancel()
                                    return "stopped"

                                # CHAT_ENDED_EVENT の検出
                                if item_proto.snippet.type == _CHAT_ENDED_TYPE:
                                    _route.info(
                                        "[route-check] grpc_chat_ended_event "
                                        "conn_responses=%d", conn_responses,
                                    )
                                    chat_ended = True

                                raw = _grpc_message_to_raw_dict(item_proto)

                                # バックログ判定
                                if is_first:
                                    pub = raw["snippet"].get("publishedAt", "")
                                    if self._is_backlog(pub, connect_time):
                                        raw["_is_backlog"] = True

                                _api_usage.info(
                                    "GRPC_MESSAGE attempt=%d type=%s id=%.20s "
                                    "author=%.30s backlog=%s",
                                    reconnect_count,
                                    raw["snippet"].get("type", "?"),
                                    raw.get("id", "?"),
                                    raw["authorDetails"].get("displayName", "?"),
                                    raw.get("_is_backlog", False),
                                )

                                if on_comment:
                                    on_comment(raw)

                            # is_first は最初のバッチ処理後に解除
                            if is_first and item_count > 0:
                                is_first = False

                        # for ループ正常終了（サーバーがストリームを閉じた）
                        normal_stream_end = True

                    except grpc.RpcError as e:
                        code   = e.code()
                        detail = e.details() or ""
                        conn_duration_ms = int((time.monotonic() - t_conn_start) * 1000)

                        _yt_error.info(
                            "EVENT grpc_rpc_error route=grpc attempt=%d "
                            "conn_responses=%d status_code=%s detail=%.200s "
                            "conn_duration_ms=%d notify_overlay=%s",
                            reconnect_count, conn_responses,
                            code.name, detail, conn_duration_ms, notify_overlay,
                        )

                        # ─ クライアントによるキャンセル ─
                        if code == grpc.StatusCode.CANCELLED:
                            return "stopped"

                        # ─ liveChatId が見つからない（永続的失敗） ─
                        if code == grpc.StatusCode.NOT_FOUND:
                            if stream_connected:
                                on_status("disconnected", "配信が削除されたため接続を終了しました")
                                on_system_message("配信が削除されたため接続を終了しました")
                                return "normal_end"
                            on_status("disconnected", "接続に失敗しました（ライブチャットが見つかりません）")
                            on_system_message("接続に失敗しました（ライブチャットが見つかりません）")
                            return "permanent"

                        # ─ 権限エラー ─
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

                        # ─ クォータ超過 ─
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

                        # ─ 認証エラー ─
                        if code == grpc.StatusCode.UNAUTHENTICATED:
                            on_status("disconnected", "認証エラー (UNAUTHENTICATED) — 再認証が必要です")
                            on_system_message("[YouTube] 認証エラー — 再認証してください。")
                            return "permanent"

                        # ─ UNAVAILABLE / DEADLINE_EXCEEDED / その他 → 一時失敗 ─
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
                        self.stats["grpc_failure_reconnects"] += 1
                        reconnect_count += 1
                        continue  # while ループへ戻る

            except Exception as e:
                # gRPC チャンネル生成・その他の予期しないエラー
                failure_count += 1
                _yt_error.info(
                    "EVENT grpc_unexpected_error route=grpc attempt=%d "
                    "exception_type=%s exception_msg=%.200s notify_overlay=%s",
                    reconnect_count, type(e).__name__, str(e), notify_overlay,
                )
                if failure_count >= GRPC_MAX_RETRIES_ON_FAILURE:
                    on_status("disconnected", "接続に失敗しました")
                    on_system_message("[YouTube] 予期しないエラーで接続に失敗しました。")
                    return "fallback"
                _wait_interruptible(stop_event, GRPC_RETRY_DELAY)
                if stop_event.is_set():
                    return "stopped"
                reconnect_count += 1
                continue

            # ─── ストリーム正常終了の処理 ─────────────────────────────────────
            if normal_stream_end:
                conn_duration_ms = int((time.monotonic() - t_conn_start) * 1000)
                _route.info(
                    "[route-check] grpc_stream_server_close attempt=%d "
                    "conn_responses=%d conn_duration_ms=%d chat_ended=%s",
                    reconnect_count, conn_responses, conn_duration_ms, chat_ended,
                )

                if chat_ended:
                    # 配信終了イベントを受信 → 正常終了
                    on_status("disconnected", "配信が終了したため接続を終了しました")
                    on_system_message("配信が終了したため接続を終了しました")
                    return "normal_end"

                if stop_event.is_set():
                    return "stopped"

                # 配信終了でない正常クローズ → next_page_token で resume 再接続
                # gRPC では pollingIntervalMillis がないため、最小待機のみ入れる
                failure_count = 0
                was_transient_reconnect = False  # サーバークローズ起因の resume はエラー扱いしない
                self.stats["grpc_server_close_resumes"] += 1
                reconnect_count += 1
                _route.info(
                    "[route-check] grpc_server_close_resume reconnect_count=%d",
                    reconnect_count,
                )
                _wait_interruptible(stop_event, GRPC_SERVER_CLOSE_MIN_WAIT)
                if stop_event.is_set():
                    return "stopped"

        # stop_event により停止
        return "stopped"


def _wait_interruptible(stop_event: threading.Event, seconds: float):
    """stop_event を監視しながら待機する。"""
    waited = 0.0
    while waited < seconds and not stop_event.is_set():
        time.sleep(_STOP_CHECK_INTERVAL)
        waited += _STOP_CHECK_INTERVAL
