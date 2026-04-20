"""
config_io.py — 設定ファイルの純 I/O 層

bridge.py から切り出した設定読み書き責務。
tkinter / UI 非依存。

このモジュールは bridge.py より先に import されても動作するよう
sys.path 設定を自己完結させている。
"""

import sys
import os
import json

# RRoulette ルートディレクトリを sys.path に追加（config_utils の参照用）
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

from config_utils import CONFIG_FILE


def load_config() -> dict:
    """設定ファイルを読み込む。ファイルがなければ空辞書を返す。"""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: dict) -> None:
    """設定辞書をファイルに保存する。"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
