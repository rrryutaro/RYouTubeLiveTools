import ctypes
import ctypes.wintypes as _wintypes
import re as _re
import sys
import os

# ─── パス設定 ────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "roulette_settings.json")

# ─── エクスポート保存先 ───────────────────────────────────────────────
# EXE実行時: BASE_DIR = dist/ なのでそのまま使う
# Python実行時: BASE_DIR = RRoulette/ なので dist/ サブフォルダを使う
if getattr(sys, "frozen", False):
    EXPORT_DIR = BASE_DIR
else:
    EXPORT_DIR = os.path.join(BASE_DIR, "dist")

os.makedirs(EXPORT_DIR, exist_ok=True)

# ─── 自動保存ログファイル ──────────────────────────────────────────────
AUTO_LOG_FILE = os.path.join(EXPORT_DIR, "roulette_autosave_log.json")


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
