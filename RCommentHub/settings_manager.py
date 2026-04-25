"""
RCommentHub — 設定管理・API キー暗号化
Windows DPAPI によるシークレット保護
"""

import json
import os
import ctypes
import ctypes.wintypes
import base64


# ─── DPAPI 構造体 ─────────────────────────────────────────────────────────────

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi_encrypt(plaintext: str) -> str:
    """DPAPI で文字列を暗号化し、Base64 文字列を返す"""
    data = plaintext.encode("utf-8")
    buf  = ctypes.create_string_buffer(data)
    in_blob  = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise RuntimeError("DPAPI 暗号化に失敗しました")
    size      = out_blob.cbData
    ptr       = ctypes.cast(out_blob.pbData, ctypes.POINTER(ctypes.c_ubyte * size))
    encrypted = bytes(ptr.contents)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def _dpapi_decrypt(b64_data: str) -> str:
    """Base64 文字列を DPAPI で復号し、プレーンテキストを返す"""
    data = base64.b64decode(b64_data)
    buf  = ctypes.create_string_buffer(data)
    in_blob  = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise RuntimeError("DPAPI 復号に失敗しました")
    size      = out_blob.cbData
    ptr       = ctypes.cast(out_blob.pbData, ctypes.POINTER(ctypes.c_ubyte * size))
    decrypted = bytes(ptr.contents)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return decrypted.decode("utf-8")


# ─── 設定マネージャ ───────────────────────────────────────────────────────────

class SettingsManager:
    """設定ファイルの読み書き + API キー DPAPI 暗号化管理"""

    _API_KEY_DPAPI = "_api_key_dpapi"   # JSON に保存するフィールド名
    _API_KEY_PLAIN = "api_key"          # 旧フィールド名（移行用）

    def __init__(self, config_path: str):
        self._path              = config_path
        self._data: dict        = {}
        self._api_key_cache: str = ""    # 復号済みキャッシュ（メモリ内のみ）

    # ─── ロード / セーブ ─────────────────────────────────────────────────────

    def load(self) -> dict:
        """ファイルから設定を読み込む。ファイルがなければ空 dict を返す"""
        try:
            with open(self._path, encoding="utf-8") as f:
                self._data = json.load(f)
        except FileNotFoundError:
            self._data = {}
        except Exception:
            self._data = {}

        # 旧フォーマット（api_key 平文）からの移行
        if self._API_KEY_PLAIN in self._data and self._API_KEY_DPAPI not in self._data:
            plain = self._data.pop(self._API_KEY_PLAIN, "")
            if plain:
                try:
                    self._data[self._API_KEY_DPAPI] = _dpapi_encrypt(plain)
                except Exception:
                    pass
            self._flush()

        # API キーを復号してキャッシュ
        self._api_key_cache = self._decrypt_api_key()

        return dict(self._data)

    def save(self, data: dict):
        """設定を保存する（平文 api_key は保存しない）"""
        self._data = {k: v for k, v in data.items() if k != self._API_KEY_PLAIN}
        self._flush()

    def _flush(self):
        """_data の内容をファイルに書き出す（平文 api_key は除外）"""
        to_save = {k: v for k, v in self._data.items() if k != self._API_KEY_PLAIN}
        dirpath = os.path.dirname(self._path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)

    # ─── API キー ─────────────────────────────────────────────────────────────

    @property
    def api_key(self) -> str:
        return self._api_key_cache

    def set_api_key(self, plaintext: str):
        """API キーを DPAPI 暗号化して設定ファイルに保存する"""
        if plaintext:
            try:
                self._data[self._API_KEY_DPAPI] = _dpapi_encrypt(plaintext)
                self._api_key_cache = plaintext
            except Exception as e:
                raise RuntimeError(f"API キーの暗号化に失敗: {e}")
        else:
            self._data.pop(self._API_KEY_DPAPI, None)
            self._api_key_cache = ""
        self._flush()

    def _decrypt_api_key(self) -> str:
        encrypted = self._data.get(self._API_KEY_DPAPI, "")
        if not encrypted:
            return ""
        try:
            return _dpapi_decrypt(encrypted)
        except Exception:
            return ""

    # ─── Twitch トークン（DPAPI 暗号化） ──────────────────────────────────────

    _TWITCH_ACCESS_KEY  = "_twitch_access_token_dpapi"
    _TWITCH_REFRESH_KEY = "_twitch_refresh_token_dpapi"

    def get_twitch_access_token(self) -> str:
        """Twitch アクセストークンを復号して返す"""
        encrypted = self._data.get(self._TWITCH_ACCESS_KEY, "")
        if not encrypted:
            return ""
        try:
            return _dpapi_decrypt(encrypted)
        except Exception:
            return ""

    def set_twitch_access_token(self, plaintext: str):
        """Twitch アクセストークンを DPAPI 暗号化して保存する"""
        if plaintext:
            try:
                self._data[self._TWITCH_ACCESS_KEY] = _dpapi_encrypt(plaintext)
            except Exception:
                pass
        else:
            self._data.pop(self._TWITCH_ACCESS_KEY, None)
        self._flush()

    def get_twitch_refresh_token(self) -> str:
        """Twitch リフレッシュトークンを復号して返す"""
        encrypted = self._data.get(self._TWITCH_REFRESH_KEY, "")
        if not encrypted:
            return ""
        try:
            return _dpapi_decrypt(encrypted)
        except Exception:
            return ""

    def set_twitch_refresh_token(self, plaintext: str):
        """Twitch リフレッシュトークンを DPAPI 暗号化して保存する"""
        if plaintext:
            try:
                self._data[self._TWITCH_REFRESH_KEY] = _dpapi_encrypt(plaintext)
            except Exception:
                pass
        else:
            self._data.pop(self._TWITCH_REFRESH_KEY, None)
        self._flush()

    # ─── 接続プロファイル管理 ──────────────────────────────────────────────────

    def get_connection_profiles(self) -> list:
        """
        接続プロファイルリストを返す。

        新形式（connection_profiles キー）が存在すればそれを返す。
        旧形式（conn1_* / conn2_* キー）のみの場合は自動マイグレーションする。
        いずれの場合も、旧「display_name」のみの場合は 3 名称フィールドへ自動補完する。
        """
        profiles = self._data.get("connection_profiles", None)
        if profiles is not None:
            result = list(profiles)
        else:
            # ─── 旧形式からマイグレーション ──────────────────────────────────
            result = []
            for i, conn_id in enumerate(("conn1", "conn2")):
                default_en   = (conn_id == "conn1")
                default_name = "接続1" if conn_id == "conn1" else "接続2"
                result.append({
                    "profile_id":   f"profile_{i}",
                    "platform":     "youtube",
                    "display_name": self._data.get(f"{conn_id}_name", default_name),
                    "enabled":      self._data.get(f"{conn_id}_enabled", default_en),
                    "target_url":   self._data.get(f"{conn_id}_url", ""),
                })

        # ─── 名称フィールドの自動補完（旧 display_name のみの場合） ────────────
        for p in result:
            if "profile_name" not in p:
                dn = p.get("display_name", p.get("profile_id", "接続"))
                p["profile_name"] = dn
                p.setdefault("overlay_name", dn)
                p.setdefault("tts_name",     dn)

        return result

    def save_connection_profiles(self, profiles: list):
        """接続プロファイルリストを保存する"""
        self._data["connection_profiles"] = profiles
        self._flush()

    # ─── 汎用アクセサ ────────────────────────────────────────────────────────

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._flush()

    def update(self, data: dict):
        for k, v in data.items():
            if k != self._API_KEY_PLAIN:
                self._data[k] = v
        self._flush()
