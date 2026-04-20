"""
RRoulette — PySide6 版エントリーポイント

使い方:
  cd RRoulette
  python rroulette_pyside6.py

操作:
  - 左ドラッグ: ウィンドウ移動
  - 右クリック: メニュー（パネル開閉・サイズ・デザイン・テキストモード・終了）
  - F1: 右パネル表示/非表示
  - Esc: 終了

既存設定ファイル (dist/roulette_settings.json) があれば、
項目リスト・デザイン・テキストモード・ポインター位置を自動読み込みする。
"""

import sys
import os
import ctypes

# pyside6/ ディレクトリを sys.path に追加（main_window 等のフラットな import を有効化）
_pyside6_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyside6")
if _pyside6_dir not in sys.path:
    sys.path.insert(0, _pyside6_dir)

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

# i489: 複数起動禁止 — Win32 名前付きミューテックスで検出する。
#
# run_proto.py (Python 開発用) と同一ミューテックス名を使用することで、
# Python 実行中に EXE を起動した場合も（またはその逆も）多重起動を防ぐ。
# Win32 名前付きミューテックスはプロセス終了時に OS が自動解放するため
# クラッシュ後の stale 問題は発生しない。
_INSTANCE_MUTEX_NAME = "Local\\RRoulette_SingleInstance_v1"
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
