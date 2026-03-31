import ctypes
import ctypes.wintypes as _wintypes
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

CONFIG_FILE = os.path.join(BASE_DIR, "roulette_settings.json")

# ─── エクスポート保存先 ───────────────────────────────────────────────
# Python/EXE共通で BASE_DIR（dist/）を使う
EXPORT_DIR = BASE_DIR

# ─── 自動保存ログファイル ──────────────────────────────────────────────
AUTO_LOG_FILE = os.path.join(EXPORT_DIR, "roulette_autosave_log.json")

# ─── レガシー設定ファイルの1回移行 ────────────────────────────────────
# Python実行時の旧保存先（RRoulette/roulette_settings.json）が存在し、
# 新保存先（dist/roulette_settings.json）がまだない場合のみ1回だけ移行する。
# 新保存先が既に存在する場合はレガシーファイルを無視する。
if not getattr(sys, "frozen", False):
    _legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roulette_settings.json")
    if os.path.exists(_legacy) and not os.path.exists(CONFIG_FILE):
        try:
            import shutil as _shutil
            _shutil.copy2(_legacy, CONFIG_FILE)
        except Exception:
            pass
    del _legacy


def _is_on_any_monitor(x, y, w=1, h=1):
    """ウィンドウ中心がいずれかのモニター上にあるか確認"""
    try:
        MONITOR_DEFAULTTONULL = 0
        pt = _wintypes.POINT(x + w // 2, y + h // 2)
        return ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONULL) != 0
    except Exception:
        return True


def _parse_geometry(geo_str):
    """'WxH+X+Y' を (w, h, x, y) にパース。失敗時は None。"""
    m = _re.match(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', geo_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return None
