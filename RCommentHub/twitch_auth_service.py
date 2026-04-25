"""
RCommentHub — Twitch 認証サービス

Twitch OAuth 2.0 Device Code Grant Flow を実装する。

方針:
  - Device Code Grant Flow を使用（public client / client_secret 不要）
  - ユーザーは Twitch の activation ページでコードを入力して承認する
  - access_token / refresh_token は Windows DPAPI で暗号化保存
  - user_id はトークン検証時に取得し、EventSub 購読に使用する
  - 規約準拠: 公式 OAuth / EventSub のみ使用
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

_logger = logging.getLogger(__name__)

# ─── Twitch OAuth エンドポイント ──────────────────────────────────────────────
TWITCH_DEVICE_URL   = "https://id.twitch.tv/oauth2/device"
TWITCH_TOKEN_URL    = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
TWITCH_REVOKE_URL   = "https://id.twitch.tv/oauth2/revoke"

# Device Code Grant の grant_type 値
TWITCH_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# チャット読み取りに必要なスコープ
TWITCH_SCOPES = ["user:read:chat"]


class TwitchAuthError(Exception):
    """Twitch 認証関連エラー"""
    pass


class TwitchAuthService:
    """
    Twitch OAuth 2.0 認証サービス。

    Device Code Grant Flow を使用する（client_secret 不要 / public client）。
    SettingsManager を使ってトークンを DPAPI 暗号化保存する。
    """

    def __init__(self, settings_mgr):
        self._sm = settings_mgr
        self._client_id:     str = ""
        self._access_token:  str = ""
        self._refresh_token: str = ""
        self._user_id:       str = ""
        self._user_login:    str = ""
        self._load_from_settings()

    # ─── 初期化 ────────────────────────────────────────────────────────────────

    def _load_from_settings(self):
        """設定からクライアントIDとトークンを読み込む"""
        self._client_id     = self._sm.get("twitch_client_id", "")
        self._access_token  = self._sm.get_twitch_access_token()
        self._refresh_token = self._sm.get_twitch_refresh_token()
        self._user_id       = self._sm.get("twitch_user_id", "")
        self._user_login    = self._sm.get("twitch_user_login", "")

    # ─── プロパティ ─────────────────────────────────────────────────────────────

    @property
    def client_id(self) -> str:
        return self._client_id

    @client_id.setter
    def client_id(self, value: str):
        self._client_id = value or ""
        self._sm.update({"twitch_client_id": self._client_id})

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def user_login(self) -> str:
        return self._user_login

    def has_client_id(self) -> bool:
        return bool(self._client_id)

    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def status_label(self) -> str:
        if not self._client_id:
            return "クライアントID未設定"
        if not self._access_token:
            return "未認証"
        if self._user_login:
            return f"認証済み (@{self._user_login})"
        return "認証済み"

    def get_request_kwargs(self) -> dict:
        """requests 用の認証ヘッダーを返す"""
        if not self._access_token or not self._client_id:
            return {}
        return {
            "headers": {
                "Authorization": f"Bearer {self._access_token}",
                "Client-Id": self._client_id,
            }
        }

    def get_helix_headers(self) -> dict:
        """Helix API 用ヘッダーを返す（urllib 用）"""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Client-Id": self._client_id,
            "Content-Type": "application/json",
        }

    # ─── Device Code Grant Flow ───────────────────────────────────────────────

    def run_device_code_flow(self, on_status=None, on_device_code=None,
                             stop_event=None) -> bool:
        """
        Device Code Grant Flow を実行する（public client / client_secret 不要）。

        on_status(msg: str)                    : 進捗通知（ワーカースレッド文脈）
        on_device_code(user_code, verify_url)  : コード表示通知（ワーカースレッド文脈）
        stop_event: threading.Event            : セットされたら polling を中止する

        成功なら True、失敗なら TwitchAuthError を raise する。
        """
        if not self._client_id:
            raise TwitchAuthError("Twitch クライアントIDが未設定です")

        # ── Step 1: デバイスコード発行 ─────────────────────────────────────────
        if on_status:
            on_status("デバイスコードを取得中...")

        req_data = urllib.parse.urlencode({
            "client_id": self._client_id,
            "scopes":    " ".join(TWITCH_SCOPES),
        }).encode("utf-8")
        req = urllib.request.Request(
            TWITCH_DEVICE_URL, data=req_data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                device_data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            raise TwitchAuthError(f"デバイスコードの取得に失敗しました (HTTP {e.code}): {body[:200]}")
        except Exception as e:
            raise TwitchAuthError(f"デバイスコードの取得に失敗しました: {e}")

        device_code  = device_data.get("device_code", "")
        user_code    = device_data.get("user_code", "")
        verify_uri   = device_data.get("verification_uri",
                                       "https://www.twitch.tv/activate")
        verify_uri_c = device_data.get("verification_uri_complete", verify_uri)
        expires_in   = int(device_data.get("expires_in", 300))
        interval     = int(device_data.get("interval", 5))

        if not device_code or not user_code:
            raise TwitchAuthError(
                f"デバイスコードを取得できませんでした。レスポンス: {device_data}")

        _logger.info("[TwitchAuth] device_code 取得: user_code=%s verify_uri=%s",
                     user_code, verify_uri_c)

        # ── Step 2: ユーザーへコードと URL を通知してブラウザを開く ───────────
        if on_status:
            on_status(f"ブラウザで認証: コード [{user_code}]  待機中...")
        if on_device_code:
            on_device_code(user_code, verify_uri_c)
        webbrowser.open(verify_uri_c)

        # ── Step 3: token を polling で取得 ────────────────────────────────────
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline:
            # キャンセルチェック
            if stop_event is not None and stop_event.is_set():
                raise TwitchAuthError("認証がキャンセルされました")

            time.sleep(interval)

            poll_data = urllib.parse.urlencode({
                "client_id":   self._client_id,
                "scopes":      " ".join(TWITCH_SCOPES),
                "device_code": device_code,
                "grant_type":  TWITCH_DEVICE_GRANT,
            }).encode("utf-8")
            poll_req = urllib.request.Request(
                TWITCH_TOKEN_URL, data=poll_data, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                with urllib.request.urlopen(poll_req, timeout=15) as resp:
                    token_data = json.loads(resp.read())

                access_token  = token_data.get("access_token", "")
                refresh_token = token_data.get("refresh_token", "")
                if not access_token:
                    raise TwitchAuthError("アクセストークンが空です")

                self._access_token  = access_token
                self._refresh_token = refresh_token
                self._sm.set_twitch_access_token(access_token)
                if refresh_token:
                    self._sm.set_twitch_refresh_token(refresh_token)

                self._fetch_user_info()

                if on_status:
                    label = (f"認証完了 (@{self._user_login})"
                             if self._user_login else "認証完了")
                    on_status(label)
                return True

            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8")
                except Exception:
                    pass
                try:
                    msg = json.loads(body).get("message", body)
                except Exception:
                    msg = body

                if "authorization_pending" in msg:
                    _logger.debug("[TwitchAuth] polling: authorization_pending")
                    continue
                elif "slow_down" in msg:
                    interval = min(interval + 5, 30)
                    _logger.debug("[TwitchAuth] polling: slow_down → interval=%d", interval)
                    continue
                elif "access_denied" in msg:
                    raise TwitchAuthError("ユーザーにより認証が拒否されました")
                elif "expired_token" in msg:
                    raise TwitchAuthError("デバイスコードの有効期限が切れました。再度お試しください")
                else:
                    raise TwitchAuthError(f"トークン取得失敗: {msg or str(e)}")
            except TwitchAuthError:
                raise
            except Exception as e:
                raise TwitchAuthError(f"通信エラー: {e}")

        raise TwitchAuthError("認証タイムアウト。再度お試しください")

    # ─── ユーザー情報・トークン検証 ────────────────────────────────────────────

    def _fetch_user_info(self):
        """トークン検証エンドポイントからユーザー情報を取得する"""
        if not self._access_token:
            return
        req = urllib.request.Request(
            TWITCH_VALIDATE_URL,
            headers={"Authorization": f"OAuth {self._access_token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            self._user_id    = data.get("user_id", "")
            self._user_login = data.get("login", "")
            self._sm.update({
                "twitch_user_id":    self._user_id,
                "twitch_user_login": self._user_login,
            })
        except Exception:
            pass

    def validate_token(self) -> bool:
        """
        トークンの有効性を確認する。
        無効なら refresh を試みる。
        成功なら True を返す。
        """
        if not self._access_token:
            return False
        req = urllib.request.Request(
            TWITCH_VALIDATE_URL,
            headers={"Authorization": f"OAuth {self._access_token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            self._user_id    = data.get("user_id", "")
            self._user_login = data.get("login", "")
            return True
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return self._refresh_access_token()
            return False
        except Exception:
            return False

    def _refresh_access_token(self) -> bool:
        """リフレッシュトークンでアクセストークンを更新する"""
        if not self._refresh_token or not self._client_id:
            return False
        token_data = urllib.parse.urlencode({
            "client_id":     self._client_id,
            "grant_type":    "refresh_token",
            "refresh_token": self._refresh_token,
        }).encode("utf-8")
        req = urllib.request.Request(
            TWITCH_TOKEN_URL, data=token_data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            access_token  = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            if not access_token:
                return False
            self._access_token = access_token
            if refresh_token:
                self._refresh_token = refresh_token
            self._sm.set_twitch_access_token(access_token)
            if refresh_token:
                self._sm.set_twitch_refresh_token(refresh_token)
            return True
        except Exception:
            return False

    # ─── 認証解除 ──────────────────────────────────────────────────────────────

    def revoke(self):
        """トークンを失効させ、設定から削除する"""
        if self._access_token and self._client_id:
            try:
                data = urllib.parse.urlencode({
                    "client_id": self._client_id,
                    "token":     self._access_token,
                }).encode("utf-8")
                req = urllib.request.Request(
                    TWITCH_REVOKE_URL, data=data, method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
        self._access_token  = ""
        self._refresh_token = ""
        self._user_id       = ""
        self._user_login    = ""
        self._sm.set_twitch_access_token("")
        self._sm.set_twitch_refresh_token("")
        self._sm.update({"twitch_user_id": "", "twitch_user_login": ""})
