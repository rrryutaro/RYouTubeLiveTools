"""
RRoulette PySide6 プロトタイプ — 起動スクリプト

使い方:
  cd RRoulette/pyside6
  python run_proto.py

操作:
  - 左ドラッグ: ウィンドウ移動
  - 右クリック: メニュー（パネル開閉・サイズ・デザイン・テキストモード・終了）
  - F1: 右パネル表示/非表示
  - Esc: 終了

既存設定ファイル (dist/roulette_settings.json) があれば、
項目リスト・デザイン・テキストモード・ポインター位置を自動読み込みする。
"""

import sys
import ctypes
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# bridge を import する前に QApplication を作成する必要がある
# （QFontMetrics は QApplication が存在しないと動作しない）
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
_INSTANCE_MUTEX_NAME = "Local\\RRoulette_RunProto_SingleInstance_v1"
_ERROR_ALREADY_EXISTS = 183
_instance_mutex = ctypes.windll.kernel32.CreateMutexW(None, True, _INSTANCE_MUTEX_NAME)
if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
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
