"""
updater.py — RRoulette 自動アップデートのロジック層（UI非依存）

仕様: 自動アップデート機能 設計仕様（Option A: manifest差分）

本モジュールの責務（P1: チェック層）:
  - 配布形態の判定（source / onefile / folder）
  - バージョン文字列の解析・比較
  - GitHub Releases API から RRoulette の最新リリースを取得

ダウンロード・差分適用（ヘルパー起動）は後続フェーズ（P2/P3）で追加する。
外部依存は増やさない（stdlib の urllib/json/ssl のみ）。
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request

# constants は RRoulette ルートにあり sys.path 経由で解決される。
# import 経路に依存しないようフォールバック値も用意する。
try:
    from constants import (
        GITHUB_OWNER, GITHUB_REPO, RELEASE_TAG_PREFIX, VERSION, DEV_BUILD,
    )
except Exception:  # pragma: no cover - 通常経路では発生しない
    GITHUB_OWNER = "rrryutaro"
    GITHUB_REPO = "RYouTubeLiveTools"
    RELEASE_TAG_PREFIX = "RRoulette-v"
    VERSION = "0.0.0"
    DEV_BUILD = None

API_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
USER_AGENT = "RRoulette-Updater"

# ─── ファイル名・資産名 ──────────────────────────────────────────────
APP_EXE_NAME = "RRoulette.exe"          # ディスク上の本体 exe 名（onefile/folder 共通）
ASSET_ONEFILE = "RRoulette.exe"         # onefile 版（フル）
ASSET_FOLDER_EXE = "RRoulette-folder.exe"  # folder 版の差分用 exe（約8MB）
ASSET_FULL_ZIP = "RRoulette.zip"        # folder 版フル（依存変化時）
MANIFEST_NAME = "manifest.json"         # 差分判定用マニフェスト
_NEW_EXE_NAME = "RRoulette_new.exe"     # ステージング中の新 exe
_OLD_EXE_NAME = "RRoulette_old.exe"     # 差し替え時の旧 exe バックアップ
_NEW_MANIFEST_NAME = "manifest_new.json"  # ステージング中の新 manifest
_UPDATE_TMP_DIRNAME = "RRoulette_update"  # %TEMP% 配下の作業ディレクトリ名
_HELPER_BAT_NAME = "apply_update.bat"


def update_temp_dir() -> str:
    """更新作業用の一時ディレクトリ（%TEMP%\\RRoulette_update）。"""
    return os.path.join(tempfile.gettempdir(), _UPDATE_TMP_DIRNAME)


# ---------------------------------------------------------------------------
#  配布形態の判定
# ---------------------------------------------------------------------------

def detect_distribution() -> str:
    """現在の実行形態を返す。

    Returns:
        'source'  : Python から run.py 等で直接実行（frozen でない）→ 更新対象外
        'onefile' : 単一 exe（全依存を exe に内包）
        'folder'  : onedir（exe と同階層に _internal/ 依存フォルダ）

    判定は PyInstaller の `sys._MEIPASS`（展開先）で行う:
      - onedir : _MEIPASS が exe と同じ場所（_internal）配下
      - onefile: _MEIPASS が %TEMP%\\_MEIxxxx（exe とは無関係の場所）
    これにより「単一exe を _internal フォルダの隣で実行」しても folder と
    誤判定しない（実機で単一exe が folder 扱いされる不具合の対策）。
    """
    if not getattr(sys, "frozen", False):
        return "source"
    exe_d = os.path.dirname(os.path.abspath(sys.executable))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass = os.path.abspath(meipass)
        if meipass == exe_d or meipass.startswith(exe_d + os.sep):
            return "folder"
        return "onefile"
    # フォールバック（_MEIPASS 不明時）: 従来の _internal 有無で判定
    if os.path.isdir(os.path.join(exe_d, "_internal")):
        return "folder"
    return "onefile"


def exe_dir() -> str:
    """frozen 時の exe 配置ディレクトリ。source 時はスクリプト基準の便宜値。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
#  バージョン解析・比較
# ---------------------------------------------------------------------------

def parse_version(text) -> tuple:
    """バージョン文字列を数値タプルに変換する。

    'RRoulette-v0.6.5' / 'v0.6.5' / '0.6.5' → (0, 6, 5)
    数値以外（'b' 等のサフィックス）が現れた時点でその要素以降は打ち切る。
    解析不能なら空タプル ()（比較上は最小）。
    """
    if not text:
        return ()
    s = str(text).strip()
    if s.startswith(RELEASE_TAG_PREFIX):
        s = s[len(RELEASE_TAG_PREFIX):]
    s = s.lstrip("vV")
    parts = []
    for token in s.split("."):
        num = ""
        for ch in token:
            if ch.isdigit():
                num += ch
            else:
                break
        if num == "":
            break
        parts.append(int(num))
    return tuple(parts)


def is_newer(latest, current) -> bool:
    """latest が current より新しければ True。"""
    return parse_version(latest) > parse_version(current)


def current_version() -> str:
    """比較に使う現在バージョン文字列（例 '0.6.5'）。

    検証用途に限り、環境変数 `RROULETTE_UPDATE_FAKE_CURRENT`（例 '0.6.0'）で
    現在バージョンを上書きできる。未設定なら constants.VERSION を返す。
    ※ 表示用の現在版ラベルは APP_VERSION（実バージョン）を使うため影響しない。
    """
    return os.environ.get("RROULETTE_UPDATE_FAKE_CURRENT") or VERSION


def is_dev_build() -> bool:
    """開発ビルド（DEV_BUILD が None でない）か。開発中は更新チェックを行わない。"""
    return DEV_BUILD is not None


def update_checks_enabled() -> bool:
    """このプロセスで更新チェックを行える状態か。

    通常は source（Python 実行）・開発ビルドでは無効（False）。
    検証用途に限り、環境変数 `RROULETTE_UPDATE_ALLOW_SOURCE=1` を立てると
    source/開発ビルドでも強制的に有効化できる（実 GitHub 相手に UI/ワーカー/
    ダイアログを通しで確認するため）。本番では環境変数を設定しないこと。
    """
    if os.environ.get("RROULETTE_UPDATE_ALLOW_SOURCE") == "1":
        return True
    return detect_distribution() != "source" and not is_dev_build()


# ---------------------------------------------------------------------------
#  GitHub Releases 取得
# ---------------------------------------------------------------------------

class AssetInfo:
    """リリース資産1件。"""

    __slots__ = ("name", "url", "size")

    def __init__(self, name, url, size):
        self.name = name
        self.url = url
        self.size = size

    def __repr__(self):
        return f"AssetInfo(name={self.name!r}, size={self.size})"


class ReleaseInfo:
    """RRoulette の1リリース。"""

    __slots__ = ("version", "tag", "body", "assets")

    def __init__(self, version, tag, body, assets):
        self.version = version          # '0.6.5'
        self.tag = tag                  # 'RRoulette-v0.6.5'
        self.body = body or ""          # リリースノート本文
        self.assets = assets            # dict[name -> AssetInfo]

    def asset(self, name) -> "AssetInfo | None":
        return self.assets.get(name)

    def __repr__(self):
        return f"ReleaseInfo(version={self.version!r}, assets={list(self.assets)})"


def _http_get_json(url, timeout=10):
    """GitHub API を GET して JSON を返す。例外は呼び出し側で処理する。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,               # GitHub API は UA 必須
            "Accept": "application/vnd.github+json",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def parse_releases_payload(releases) -> "ReleaseInfo | None":
    """GitHub /releases のレスポンス（list）から RRoulette の最新を選ぶ。

    ネットワークから切り離した純ロジック（テスト用途）。
    - タグが RELEASE_TAG_PREFIX で始まるものだけ対象
    - draft / prerelease は除外
    - セムバー比較で最大を「最新」とする
    """
    best = None
    best_ver = ()
    for rel in releases or []:
        tag = rel.get("tag_name", "") or ""
        if not tag.startswith(RELEASE_TAG_PREFIX):
            continue
        if rel.get("draft") or rel.get("prerelease"):
            continue
        ver = parse_version(tag)
        if ver > best_ver:
            best_ver = ver
            best = rel
    if best is None:
        return None
    assets = {}
    for a in best.get("assets", []) or []:
        name = a.get("name")
        if not name:
            continue
        assets[name] = AssetInfo(
            name=name,
            url=a.get("browser_download_url"),
            size=a.get("size"),
        )
    return ReleaseInfo(
        version=".".join(str(x) for x in best_ver),
        tag=best.get("tag_name", ""),
        body=best.get("body", ""),
        assets=assets,
    )


def get_latest_release(timeout=10) -> "ReleaseInfo | None":
    """RRoulette-v* の最新リリースを取得する。失敗時は None。"""
    releases = _http_get_json(API_RELEASES_URL, timeout=timeout)
    return parse_releases_payload(releases)


def check_for_update(timeout=10) -> "ReleaseInfo | None":
    """更新があれば ReleaseInfo、無ければ None を返す。

    - source（Python 実行）/ 開発ビルドは None（チェックしない）。
      ただし検証時は update_checks_enabled() の環境変数で強制有効化できる。
    - 取得失敗時は例外を送出（呼び出し側で握って UI 反映する）。
    """
    if not update_checks_enabled():
        return None
    latest = get_latest_release(timeout=timeout)
    if latest is None:
        return None
    if is_newer(latest.version, current_version()):
        return latest
    return None


# ---------------------------------------------------------------------------
#  ハッシュ・ダウンロード（P2/P3）
# ---------------------------------------------------------------------------

class CancelledError(Exception):
    """ダウンロードがユーザーによりキャンセルされた。"""


def sha256_file(path, _bufsize=1024 * 1024) -> str:
    """ファイルの sha256 を16進小文字で返す。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_cancelled(cancel) -> bool:
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    try:
        return bool(cancel())
    except TypeError:
        return bool(cancel)


def download(url, dest, progress_cb=None, cancel=None,
             expected_sha256=None, expected_size=None, timeout=60) -> str:
    """url を dest にダウンロードする。

    - progress_cb(downloaded:int, total:int|None) を随時呼ぶ（任意）。
    - cancel: callable()->bool / .is_set() を持つオブジェクト（任意）。True で中断。
    - expected_size / expected_sha256 が指定されれば検証し、不一致なら削除して例外。
    一時ファイル(.part)へ書き出し、検証成功後に dest へ原子的に置換する。
    """
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context()
    tmp = dest + ".part"
    downloaded = 0
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        total = expected_size
        if total is None:
            clen = resp.headers.get("Content-Length")
            if clen is not None:
                try:
                    total = int(clen)
                except (TypeError, ValueError):
                    total = None
        with open(tmp, "wb") as f:
            while True:
                if _is_cancelled(cancel):
                    raise CancelledError("ダウンロードがキャンセルされました")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb is not None:
                    progress_cb(downloaded, total)
    # 検証
    actual_size = os.path.getsize(tmp)
    if expected_size is not None and actual_size != expected_size:
        _safe_remove(tmp)
        raise ValueError(f"サイズ不一致: 期待 {expected_size} / 実際 {actual_size}")
    if expected_sha256:
        actual = sha256_file(tmp)
        if actual.lower() != str(expected_sha256).lower():
            _safe_remove(tmp)
            raise ValueError(f"sha256 不一致: 期待 {expected_sha256} / 実際 {actual}")
    os.replace(tmp, dest)
    return dest


def _safe_remove(path):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
#  マニフェスト（差分判定）
# ---------------------------------------------------------------------------

def _iter_files(base_dir):
    """base_dir 配下の (絶対パス, base_dir 相対パス[/区切り]) を決定的順序で返す。"""
    for root, dirs, files in os.walk(base_dir):
        dirs.sort()
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, base_dir).replace("\\", "/")
            yield full, rel


def compute_runtime_fingerprint(internal_dir) -> str:
    """_internal/ 配下（＝依存＋データ）の相対パス+sha256 を連結した1個のハッシュ。

    依存が同じなら現地とリモートで一致する。internal_dir が無ければ空文字。
    """
    if not os.path.isdir(internal_dir):
        return ""
    h = hashlib.sha256()
    for full, rel in _iter_files(internal_dir):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(sha256_file(full).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def build_manifest(install_dir, version) -> dict:
    """install_dir（onedir の dist/RRoulette/）から manifest dict を生成する。

    files には配布物（RRoulette.exe と _internal/ 配下）の sha256 を格納する。
    ユーザーデータ（roulette_settings.json 等）は対象外（触れないため）。
    """
    files = {}
    internal = os.path.join(install_dir, "_internal")
    fp = hashlib.sha256()
    exe = os.path.join(install_dir, APP_EXE_NAME)
    if os.path.isfile(exe):
        files[APP_EXE_NAME] = sha256_file(exe)
    if os.path.isdir(internal):
        for full, rel_internal in _iter_files(internal):
            digest = sha256_file(full)
            files["_internal/" + rel_internal] = digest
            fp.update(rel_internal.encode("utf-8"))
            fp.update(b"\0")
            fp.update(digest.encode("ascii"))
            fp.update(b"\n")
    return {
        "version": version,
        "runtime_fingerprint": fp.hexdigest(),
        "files": files,
    }


def fetch_remote_manifest(url, timeout=10) -> "dict | None":
    """リモート manifest.json（資産）を取得。失敗時は None。"""
    try:
        return _http_get_json(url, timeout=timeout)
    except Exception:
        return None


def load_local_manifest(install_dir) -> "dict | None":
    """現地の manifest.json を読む。無ければ None。"""
    p = os.path.join(install_dir, MANIFEST_NAME)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  更新プラン
# ---------------------------------------------------------------------------

class UpdatePlan:
    """更新の適用方法。

    mode:
      'onefile_full'      : onefile 版。RRoulette.exe をフル DL して差し替え。
      'folder_exe_only'   : folder 版・依存不変。RRoulette-folder.exe のみ差し替え。
      'folder_full_manual': folder 版・依存変化 or manifest 欠落。自動非対応
                            （v0.6.5 はリリースページ案内にフォールバック）。
      'unsupported'       : 対象外。
    can_auto: True ならアプリ内で自動差し替え可能（exe 差し替え）。
    """

    __slots__ = ("mode", "asset_name", "asset_url", "asset_size",
                 "asset_sha256", "can_auto", "reason")

    def __init__(self, mode, *, asset_name=None, asset_url=None, asset_size=None,
                 asset_sha256=None, can_auto=False, reason=""):
        self.mode = mode
        self.asset_name = asset_name
        self.asset_url = asset_url
        self.asset_size = asset_size
        self.asset_sha256 = asset_sha256
        self.can_auto = can_auto
        self.reason = reason

    def __repr__(self):
        return (f"UpdatePlan(mode={self.mode!r}, asset={self.asset_name!r}, "
                f"can_auto={self.can_auto})")


def plan_update(dist, release, remote_manifest=None, local_manifest=None) -> "UpdatePlan":
    """配布形態＋manifest から更新プランを決める。

    - onefile: 常に onefile_full（RRoulette.exe をフル DL）。
    - folder : remote/local manifest が揃い runtime_fingerprint 一致 → folder_exe_only。
               不一致 or manifest 欠落 → folder_full_manual（自動非対応）。
    """
    if dist == "onefile":
        a = release.asset(ASSET_ONEFILE)
        if a is None or not a.url:
            return UpdatePlan("onefile_full", can_auto=False,
                              reason="RRoulette.exe 資産が見つかりません")
        return UpdatePlan("onefile_full", asset_name=a.name, asset_url=a.url,
                          asset_size=a.size, asset_sha256=None, can_auto=True)

    if dist == "folder":
        if not remote_manifest or not local_manifest:
            # manifest が取得/読込できない（旧版からの更新や通信失敗など）
            return UpdatePlan("folder_full_manual", can_auto=False,
                              reason="更新情報(manifest)を取得できませんでした")
        rf = remote_manifest.get("runtime_fingerprint")
        lf = local_manifest.get("runtime_fingerprint")
        if rf and lf and rf == lf:
            a = release.asset(ASSET_FOLDER_EXE)
            sha = (remote_manifest.get("files") or {}).get(APP_EXE_NAME)
            if a is not None and a.url:
                return UpdatePlan("folder_exe_only", asset_name=a.name,
                                  asset_url=a.url, asset_size=a.size,
                                  asset_sha256=sha, can_auto=True)
            return UpdatePlan("folder_full_manual", can_auto=False,
                              reason="差分用の RRoulette-folder.exe が見つかりません")
        # fingerprint 不一致 = 依存が更新された（フル更新が必要）
        return UpdatePlan("folder_full_manual", can_auto=False,
                          reason="依存関係が更新されているためフル更新が必要です")

    return UpdatePlan("unsupported", can_auto=False,
                      reason="この配布形態は更新対象外です")


# ---------------------------------------------------------------------------
#  ステージング（ダウンロード＋検証して差し替え素材を配置）
# ---------------------------------------------------------------------------

def stage_update(plan, release, install_dir, progress_cb=None, cancel=None,
                 timeout=120) -> dict:
    """自動差し替え用の素材を install_dir に配置する。

    exe 差し替え系（onefile_full / folder_exe_only）のみ対応。
    戻り値: {"new_exe": <path>, "new_manifest": <path|None>}
    """
    if not plan.can_auto:
        raise ValueError(plan.reason or "自動更新に対応していないプランです")
    new_exe = os.path.join(install_dir, _NEW_EXE_NAME)
    download(plan.asset_url, new_exe, progress_cb=progress_cb, cancel=cancel,
             expected_sha256=plan.asset_sha256, expected_size=plan.asset_size,
             timeout=timeout)
    staged = {"new_exe": new_exe, "new_manifest": None}
    if plan.mode == "folder_exe_only":
        ma = release.asset(MANIFEST_NAME)
        if ma is not None and ma.url:
            new_manifest = os.path.join(install_dir, _NEW_MANIFEST_NAME)
            download(ma.url, new_manifest, cancel=cancel,
                     expected_size=ma.size, timeout=timeout)
            staged["new_manifest"] = new_manifest
    return staged


# ---------------------------------------------------------------------------
#  ヘルパー（バッチ）生成・起動
# ---------------------------------------------------------------------------

def generate_helper_bat(pid, install_dir) -> str:
    """差し替え用バッチの内容を返す（テスト容易化のため文字列生成を分離）。

    処理: アプリ(PID)終了待ち → exe のロック解放までリトライしつつ差し替え →
          （あれば）新 manifest を反映 → 再起動 → バッチ自己削除。

    重要（実機バグ対応）:
    - デタッチ起動（コンソールなし）では `timeout` が使えないため、待機は `ping` で行う。
    - アプリ終了直後は OS が exe を掴んでいることがある（特に onefile は
      ブートローダが握る）。差し替えは**成功するまでリトライ**する。
    - 進捗を install_dir\\update_helper.log に記録して事後解析できるようにする。
    差し替え失敗時は .old から復旧を試みる（ユーザーデータには一切触れない）。
    """
    exe = os.path.join(install_dir, APP_EXE_NAME)
    new_exe = os.path.join(install_dir, _NEW_EXE_NAME)
    old_exe = os.path.join(install_dir, _OLD_EXE_NAME)
    new_manifest = os.path.join(install_dir, _NEW_MANIFEST_NAME)
    manifest = os.path.join(install_dir, MANIFEST_NAME)
    log = os.path.join(install_dir, "update_helper.log")
    lines = [
        "@echo off",
        "setlocal enableextensions",
        f'set "APP={exe}"',
        f'set "NEW={new_exe}"',
        f'set "OLD={old_exe}"',
        f'set "NEWMAN={new_manifest}"',
        f'set "MAN={manifest}"',
        f'set "LOG={log}"',
        'echo [helper] start %DATE% %TIME%> "%LOG%"',
        # アプリが exe のロックを解放する（＝終了する）まで move をリトライする。
        # ※ tasklist/find のパイプは使わない（デタッチ環境でハングし、コンソール窓も
        #    出てしまう不具合があったため）。「exe を move できた＝アプリ終了」で判定する。
        "set /a _r=0",
        ":retry",
        'move /Y "%APP%" "%OLD%" >NUL 2>NUL',
        'if not exist "%APP%" goto putnew',
        "set /a _r+=1",
        "if %_r% GEQ 150 goto failed",
        "ping -n 2 127.0.0.1 >NUL",
        "goto retry",
        ":putnew",
        'echo [helper] exe unlocked (retries=%_r%), swapping>> "%LOG%"',
        'move /Y "%NEW%" "%APP%" >NUL 2>>"%LOG%"',
        'if exist "%NEWMAN%" move /Y "%NEWMAN%" "%MAN%" >NUL 2>>"%LOG%"',
        'echo [helper] swap ok>> "%LOG%"',
        "goto launch",
        ":failed",
        'echo [helper] swap FAILED (exe still locked after retries)>> "%LOG%"',
        ":launch",
        # 差し替え失敗などで本体が無ければ旧 exe から復旧
        'if not exist "%APP%" if exist "%OLD%" move /Y "%OLD%" "%APP%" >NUL 2>>"%LOG%"',
        # 旧プロセスが完全終了して単一起動ミューテックスを解放するまで少し待つ
        # （特に onefile はロック解放後もプロセス終了に一瞬ラグがあり、直後に
        #  再起動すると「すでに起動しています」になるため）。
        "ping -n 4 127.0.0.1 >NUL",
        'echo [helper] launching>> "%LOG%"',
        # --rr-updated: 更新直後の再起動であることを新プロセスへ伝える
        # （ミューテックスを数秒リトライして確実に取得させるため）。
        'start "" "%APP%" --rr-updated',
        'del "%~f0"',
    ]
    return "\r\n".join(lines) + "\r\n"


def write_helper_and_launch(pid, install_dir) -> str:
    """差し替えバッチを生成し、デタッチ起動する。呼び出し後にアプリを終了する。

    戻り値: 生成したバッチのパス。
    """
    tmp = update_temp_dir()
    os.makedirs(tmp, exist_ok=True)
    bat_path = os.path.join(tmp, _HELPER_BAT_NAME)
    # bat は cmd の既定コードページ（日本語環境では cp932）で解釈されるため mbcs で書く
    with open(bat_path, "w", encoding="mbcs", newline="") as f:
        f.write(generate_helper_bat(pid, install_dir))
    # PyInstaller の実行時環境変数を除去した環境を用意する。
    # onefile 実行中のプロセスは `_MEIPASS2` / `_PYI_*` に「展開先(_MEIxxxx)」を
    # 持っており、これを子（ヘルパー）→孫（再起動する新 exe）へ継承させると、
    # 新しい onefile が「もう展開済み」と誤認し、既に削除された旧展開先から
    # python311.dll を読もうとして失敗する（"Failed to load Python DLL ... _MEIxxxx"）。
    # そのため子プロセスへ渡す環境からこれらを取り除く。
    child_env = {
        k: v for k, v in os.environ.items()
        if not (k.startswith("_MEIPASS") or k.startswith("_PYI") or k == "_MEI2")
    }
    # CREATE_NO_WINDOW: コンソール窓を出さずに実行する（DETACHED_PROCESS だと
    # コンソールアプリ用の窓が新規に出てしまうため不可）。子プロセスは親（本体）
    # 終了後も生き続け、exe のロック解放を待って差し替え→再起動する。
    _CREATE_NO_WINDOW = 0x08000000
    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        [os.environ.get("COMSPEC", "cmd.exe"), "/c", bat_path],
        creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        cwd=install_dir,
        env=child_env,
    )
    return bat_path


# ---------------------------------------------------------------------------
#  起動時クリーンアップ・権限チェック
# ---------------------------------------------------------------------------

def cleanup_leftovers(install_dir) -> None:
    """前回更新の残骸（.old / 未適用 new / 一時領域）を掃除する（起動時に呼ぶ）。

    新版が正常起動したこの時点で旧版バックアップを削除する（設計 §6.4/§7）。
    失敗は握りつぶす（次回起動で再試行される）。
    """
    for name in (_OLD_EXE_NAME, _NEW_EXE_NAME, _NEW_MANIFEST_NAME):
        _safe_remove(os.path.join(install_dir, name))
    try:
        import shutil
        tmp = update_temp_dir()
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass


def has_write_permission(directory) -> bool:
    """directory に書き込めるか（exe 差し替えに必要）。"""
    try:
        probe = os.path.join(directory, ".rr_write_test.tmp")
        with open(probe, "w", encoding="ascii") as f:
            f.write("t")
        os.remove(probe)
        return True
    except OSError:
        return False
