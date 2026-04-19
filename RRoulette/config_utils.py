import ctypes
import re as _re
import sys
import os

# ─── パス設定 ────────────────────────────────────────────────────────
# EXE実行時・Python実行時ともに dist/ フォルダを正規の保存先とする。
# これにより roulette_settings.json の保存先が1か所に統一される。
if getattr(sys, "frozen", False):
    # EXE実行時: EXEと同じフォルダ (dist/)
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Python実行時: スクリプトの隣の dist/ サブフォルダ
    # ※ EXE実行時と同じ dist/ を指すため、設定ファイルを共有できる
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")

os.makedirs(BASE_DIR, exist_ok=True)

# ─── 起動インスタンス番号の決定 ────────────────────────────────────────
# Windows Named Mutex でインスタンス番号(1始まり)を決定する。
# CreateMutex は原子的に動作するため、同時起動でも番号が衝突しない。
# ハンドルはプロセス終了時に OS が自動解放するため残存状態が残らない。
#
# 注意: ctypes.windll 経由で GetLastError() を呼ぶと ctypes 内部処理が
#       エラー値を上書きする場合がある。use_last_error=True の WinDLL と
#       ctypes.get_last_error() を使うことで確実にエラー値を取得できる。
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.c_void_p   # HANDLE はポインタサイズ
_kernel32.CloseHandle.restype  = ctypes.c_int


_INSTANCE_MUTEXES: list = []  # GC回避のためハンドルをモジュール変数で保持

def _acquire_instance_number(max_instances: int = 9) -> int:
    """起動中のインスタンス番号を1始まりで返す。"""
    ERROR_ALREADY_EXISTS = 183
    for n in range(1, max_instances + 1):
        handle = _kernel32.CreateMutexW(None, False, f"RRoulette_Instance_{n}")
        err = ctypes.get_last_error()   # use_last_error=True で安全に取得
        if handle and err != ERROR_ALREADY_EXISTS:
            _INSTANCE_MUTEXES.append(handle)
            return n
        if handle:
            _kernel32.CloseHandle(handle)
    return max_instances + 1  # フォールバック（上限超え）

INSTANCE_NUM: int = _acquire_instance_number()

# ─── 設定ファイル名 ──────────────────────────────────────────────────
# i463: 単一起動前提のためインスタンス番号によるファイル分岐を廃止する。
# 常に固定ファイル名を使用する。
CONFIG_FILE = os.path.join(BASE_DIR, "roulette_settings.json")

# ─── エクスポート保存先 ───────────────────────────────────────────────
# Python/EXE共通で BASE_DIR（dist/）を使う
EXPORT_DIR = BASE_DIR

# ─── 自動保存ログファイル ──────────────────────────────────────────────
# i463: 単一起動前提のため固定名を使用する。
AUTO_LOG_FILE = os.path.join(EXPORT_DIR, "roulette_autosave_log.json")

# ─── レガシー設定ファイルの1回移行 ────────────────────────────────────
# Python実行時の旧保存先（RRoulette/roulette_settings.json）が存在し、
# 新保存先（dist/roulette_settings.json）がまだない場合のみ1回だけ移行する。
# 新保存先が既に存在する場合はレガシーファイルを無視する。
# geometry 系キーは環境依存で壊れている可能性があるため移行しない。
_LEGACY_GEO_KEYS = ("geometry", "item_list_float_geo", "cfg_panel_float_geo")

if not getattr(sys, "frozen", False):
    _legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roulette_settings.json")
    if os.path.exists(_legacy) and not os.path.exists(CONFIG_FILE):
        try:
            import json as _json
            with open(_legacy, encoding="utf-8") as _f:
                _data = _json.load(_f)
            for _k in _LEGACY_GEO_KEYS:
                _data.pop(_k, None)
            with open(CONFIG_FILE, "w", encoding="utf-8") as _f:
                _json.dump(_data, _f)
        except Exception:
            pass
    del _legacy


def _is_on_any_monitor(x, y, w=1, h=1):
    """ウィンドウ中心がいずれかのモニター上にあるか確認"""
    try:
        cx = x + w // 2
        cy = y + h // 2
        _gm = ctypes.windll.user32.GetSystemMetrics
        sx = _gm(76)   # SM_XVIRTUALSCREEN
        sy = _gm(77)   # SM_YVIRTUALSCREEN
        sw = _gm(78)   # SM_CXVIRTUALSCREEN
        sh = _gm(79)   # SM_CYVIRTUALSCREEN
        return sx <= cx < sx + sw and sy <= cy < sy + sh
    except Exception:
        return True


def _parse_geometry(geo_str):
    """'WxH+X+Y' を (w, h, x, y) にパース。失敗時は None。
    Tkinter on Windows は画面外座標で '+-N' を返す場合があるため '-N' に正規化する。
    """
    geo_str = _re.sub(r'\+-', '-', geo_str)
    m = _re.match(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', geo_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return None
