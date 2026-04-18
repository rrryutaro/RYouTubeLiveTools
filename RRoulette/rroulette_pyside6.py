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

# pyside6/ ディレクトリを sys.path に追加（main_window 等のフラットな import を有効化）
_pyside6_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyside6")
if _pyside6_dir not in sys.path:
    sys.path.insert(0, _pyside6_dir)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# bridge を import する前に QApplication を作成する必要がある
# （QFontMetrics は QApplication が存在しないと動作しない）
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)
app = QApplication(sys.argv)
app.setFont(QFont("Meiryo", 9))

from main_window import MainWindow

window = MainWindow()
window.show()

sys.exit(app.exec())
