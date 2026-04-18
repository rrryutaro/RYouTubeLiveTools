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
