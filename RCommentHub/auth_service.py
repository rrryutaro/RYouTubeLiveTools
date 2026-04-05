"""
RCommentHub — 認証サービス

OAuth 2.0 (InstalledAppFlow) / API キーの二系統を管理する。

方針:
  - OAuth 2.0 が正式標準。新規利用者への案内はこちらを基本とする。
  - API キーは補助モード（公開データ向け・検証・小規模デモ用途）として残す。
  - クライアント設定（client_id/secret）の供給方法は外部から差し替えられる構造にする。
  - リポジトリに実クレデンシャルを含めない。
  - token.json はローカルにのみ保存。
"""

import json
import os
import threading

# ─── 認証モード定数 ───────────────────────────────────────────────────────────

AUTH_MODE_OAUTH   = "oauth"
AUTH_MODE_API_KEY = "api_key"

# YouTube readonly スコープ（ライブチャット取得に必要）
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly"
]


class AuthServiceError(Exception):
    """認証関連のエラー"""
    pass


class AuthService:
    """
    OAuth 2.0 / API キーの二系統認証を管理するサービスクラス。

    OAuth モード:
        InstalledAppFlow (PKCE + ローカルサーバー) を使用。
        トークンは token_path に保存し、リフレッシュを自動で行う。
        client_config は外部から供給する（リポジトリに含めない）。

    API キーモード（補助モード）:
        公開データ向け・検証・小規模デモ用途として残す。
        推奨の主経路にはしない。
    """

    def __init__(self, token_path: str):
        self._mode: str        = AUTH_MODE_API_KEY  # 既定値は API キー補助モード
        self._api_key: str     = ""
        self._token_path: str  = token_path
        self._credentials      = None  # google.oauth2.credentials.Credentials
        self._client_config    = None  # dict: OAuth クライアント設定（外部から供給）
        self._lock             = threading.Lock()

    # ─── モード ──────────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value in (AUTH_MODE_OAUTH, AUTH_MODE_API_KEY):
            self._mode = value

    def is_oauth_mode(self) -> bool:
        return self._mode == AUTH_MODE_OAUTH

    def is_api_key_mode(self) -> bool:
        return self._mode == AUTH_MODE_API_KEY

    # ─── API キー（補助モード） ───────────────────────────────────────────────

    @property
    def api_key(self) -> str:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str):
        self._api_key = value or ""

    # ─── クライアント設定供給 ─────────────────────────────────────────────────

    def set_client_config(self, config: dict):
        """
        OAuth クライアント設定を dict で供給する。
        google-auth-oauthlib が期待する "installed" キー付きの形式。
        リポジトリには含めない。
        """
        self._client_config = config

    def load_client_config_from_file(self, path: str) -> bool:
        """
        client_secrets.json ファイルからクライアント設定を読み込む。
        成功なら True を返す。
        """
        try:
            with open(path, encoding="utf-8") as f:
                self._client_config = json.load(f)
            return True
        except Exception:
            return False

    def has_client_config(self) -> bool:
        return bool(self._client_config)

    def try_load_client_secrets_from_dir(self, dirpath: str) -> bool:
        """
        指定ディレクトリから client_secrets.json または client_secret_*.json を
        自動検索してロードする。
        最初に見つかったファイルを使用する。
        成功なら True を返す。
        """
        import glob as _glob
        candidates = [os.path.join(dirpath, "client_secrets.json")]
        candidates += sorted(_glob.glob(os.path.join(dirpath, "client_secret_*.json")))
        for path in candidates:
            if os.path.exists(path):
                if self.load_client_config_from_file(path):
                    return True
        return False

    def client_config_source(self) -> str:
        """ロード済みクライアント設定の由来情報（ログ・UI表示用）"""
        if not self._client_config:
            return "未ロード"
        info = self._client_config.get("installed", self._client_config.get("web", {}))
        return info.get("client_id", "ロード済み（client_id不明）")

    # ─── 認証状態 ─────────────────────────────────────────────────────────────

    def is_authenticated(self) -> bool:
        """現在のモードで認証済み（利用可能）状態かどうか"""
        if self._mode == AUTH_MODE_API_KEY:
            return bool(self._api_key)
        creds = self._credentials
        if creds is None:
            return False
        if creds.valid:
            return True
        # 期限切れでもリフレッシュトークンがあれば更新可能
        return bool(getattr(creds, "refresh_token", None))

    def status_label(self) -> str:
        """UIに表示する認証状態の短いラベル"""
        if self._mode == AUTH_MODE_API_KEY:
            if self._api_key:
                return "APIキー設定済み（補助モード）"
            return "APIキー未設定（補助モード）"
        # OAuth
        creds = self._credentials
        if creds is None:
            return "未認証"
        if creds.valid:
            return "認証済み (OAuth)"
        if getattr(creds, "refresh_token", None):
            return "要更新 (OAuth)"
        return "認証期限切れ"

    # ─── トークン管理 ─────────────────────────────────────────────────────────

    def load_token(self) -> bool:
        """
        保存済みの token.json をロードする。
        成功なら True を返す。
        """
        if not os.path.exists(self._token_path):
            return False
        try:
            from google.oauth2.credentials import Credentials
            self._credentials = Credentials.from_authorized_user_file(
                self._token_path, YOUTUBE_SCOPES
            )
            return True
        except Exception:
            self._credentials = None
            return False

    def refresh_if_needed(self) -> bool:
        """
        アクセストークンが期限切れなら更新する。
        成功なら True を返す。
        """
        if self._credentials is None:
            return False
        if self._credentials.valid:
            return True
        if not getattr(self._credentials, "refresh_token", None):
            return False
        try:
            from google.auth.transport.requests import Request
            self._credentials.refresh(Request())
            self._save_token()
            return True
        except Exception:
            return False

    def _save_token(self):
        """トークンをファイルに保存する"""
        if self._credentials is None:
            return
        try:
            dirpath = os.path.dirname(self._token_path)
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)
            with open(self._token_path, "w", encoding="utf-8") as f:
                f.write(self._credentials.to_json())
        except Exception:
            pass

    # ─── OAuth フロー ─────────────────────────────────────────────────────────

    def run_oauth_flow(self) -> bool:
        """
        OAuth 認証フローをブロッキングで実行する。
        ブラウザが開き、利用者が Google アカウントで認証する。
        成功なら True、失敗なら False を返す。

        前提: set_client_config() または load_client_config_from_file() で
              クライアント設定が供給済みであること。
        """
        if not self._client_config:
            return False
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_config(
                self._client_config, YOUTUBE_SCOPES
            )
            # PKCE + ローカルサーバー (ループバック) フロー
            creds = flow.run_local_server(port=0, open_browser=True)
            self._credentials = creds
            self._save_token()
            return True
        except Exception:
            return False

    def revoke(self):
        """トークンを失効させ、保存ファイルを削除する"""
        try:
            if self._credentials and getattr(self._credentials, "token", None):
                import requests as _req
                _req.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": self._credentials.token},
                    timeout=5,
                )
        except Exception:
            pass
        self._credentials = None
        try:
            if os.path.exists(self._token_path):
                os.remove(self._token_path)
        except Exception:
            pass

    # ─── リクエスト用ヘルパー ─────────────────────────────────────────────────

    def get_request_kwargs(self) -> dict:
        """
        requests.get() / requests.post() に追加で渡す kwargs を返す。

        OAuth モード:
            headers に Authorization: Bearer {token} を設定。
            トークンの自動リフレッシュを試みる。
        API キーモード（補助モード）:
            params に key を設定。
        """
        if self._mode == AUTH_MODE_OAUTH:
            if self.refresh_if_needed() and self._credentials:
                return {"headers": {"Authorization": f"Bearer {self._credentials.token}"}}
            return {}
        else:
            if self._api_key:
                return {"params": {"key": self._api_key}}
            return {}
