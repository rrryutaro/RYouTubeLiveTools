"""
RRoulette PySide6 — 開発用起動スクリプト

使い方:
  cd RRoulette/pyside6
  python run.py

操作:
  - 左ドラッグ: ウィンドウ移動
  - 右クリック: メニュー（パネル開閉・サイズ・デザイン・テキストモード・終了）
  - F1: 右パネル表示/非表示
  - Esc: 全面非表示（タスクバー/Alt+Tab で再表示）

既存設定ファイル (dist/roulette_settings.json) があれば、
項目リスト・デザイン・テキストモード・ポインター位置を自動読み込みする。
"""

import sys
import os
import ctypes

# RRoulette ルートを sys.path に追加（pyside6 モジュールから ../constants.py 等を参照するため）
# 各モジュールにも同等のガードがあるが、エントリーポイントで明示することで
# 起動経路に依存しない初期化順序を保証する。
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# main_window → wheel_widget → layout_search_adapter → font_adapter (QFontMetrics) の
# import チェーンより先に QApplication を作成する必要がある
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)
app = QApplication(sys.argv)
app.setFont(QFont("Meiryo", 9))

# i467: 複数起動禁止 — Win32 名前付きミューテックスで検出する。
#
# 旧実装 (i462) はウィンドウタイトルの startswith("RRoulette") で検出していたが、
# 同名ウィンドウを持つ他プロセス（IDE・ランチャー等）に誤ヒットして
# 「起動していないのに起動中扱い」になる問題があった。
#
# Win32 名前付きミューテックスはプロセス終了時（クラッシュ含む）に
# OS が自動解放するため stale 問題は発生しない。
# モジュール変数 _instance_mutex に保持することで、プロセス生存中は
# ミューテックスが解放されず、確実に二重起動を防ぐ。
#
# i489: ミューテックス名を main.py (EXE エントリー) と統一。
# Python 実行と EXE 実行で同じ名前を使うことで、どちらが起動中でも
# もう一方の多重起動を防ぐ。
_INSTANCE_MUTEX_NAME = "Local\\RRoulette_SingleInstance_v1"
_ERROR_ALREADY_EXISTS = 183


def _acquire_instance_mutex():
    """単一起動ミューテックスを取得（更新直後 --rr-updated は数秒リトライ）。"""
    import time
    updated = "--rr-updated" in sys.argv
    attempts = 24 if updated else 1
    handle = None
    for _i in range(attempts):
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, _INSTANCE_MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() != _ERROR_ALREADY_EXISTS:
            return handle, True
        ctypes.windll.kernel32.CloseHandle(handle)
        handle = None
        if _i < attempts - 1:
            time.sleep(0.5)
    return handle, False


_instance_mutex, _acquired = _acquire_instance_mutex()
if not _acquired:
    # 既に起動中 — ウィンドウを列挙して前面化する
    _found_hwnd = [0]
    _EnumCB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_long)

    def _find_roulette_window(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == "RRoulette" and ctypes.windll.user32.IsWindowVisible(hwnd):
            _found_hwnd[0] = hwnd
            return False  # 見つかったら列挙停止
        return True

    _enum_fn = _EnumCB(_find_roulette_window)
    ctypes.windll.user32.EnumWindows(_enum_fn, 0)

    QMessageBox.information(
        None, "RRoulette",
        "RRoulette はすでに起動しています。\n既存のウィンドウを前面に表示します。",
    )
    if _found_hwnd[0]:
        SW_RESTORE = 9
        ctypes.windll.user32.ShowWindow(_found_hwnd[0], SW_RESTORE)
        ctypes.windll.user32.SetForegroundWindow(_found_hwnd[0])
    sys.exit(0)

from main_window import MainWindow

window = MainWindow()
window.show()

sys.exit(app.exec())
