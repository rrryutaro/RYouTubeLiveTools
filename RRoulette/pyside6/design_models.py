"""
design_models.py — PySide6 側から直接参照できるデザイン設定層

RRoulette ルート (../design_settings.py) のデザイン設定クラス・プリセットデータを
PySide6 側に提供する。
tkinter / PySide6 ウィジェットに依存しない純データのみ。

PySide6 モジュールはデザイン設定をこのモジュールから直接参照すること。

公開 API:
  クラス:
    DesignSettings, DesignPresetManager
    GlobalColors, WheelDesign, SegmentDesign, PointerDesign
    LogDesign, FontSettings, WheelFontSettings, ResultDesign
  定数:
    DESIGN_PRESETS, DESIGN_PRESET_NAMES
    SEGMENT_COLOR_PRESETS, SEGMENT_PRESET_NAMES
  関数:
    load_design(config) → DesignSettings
"""

import sys
import os

# ── RRoulette ルートを sys.path に追加 ───────────────────────────────
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

# ── design_settings.py から re-export ───────────────────────────────
from design_settings import (
    DesignSettings, DesignPresetManager,
    GlobalColors, WheelDesign, SegmentDesign, PointerDesign,
    LogDesign, FontSettings, WheelFontSettings, ResultDesign,
    DESIGN_PRESETS, DESIGN_PRESET_NAMES,
    SEGMENT_COLOR_PRESETS, SEGMENT_PRESET_NAMES,
)


def load_design(config: dict | None = None) -> DesignSettings:
    """設定辞書からデザイン設定を復元する。

    bridge.py から移動。config が None の場合は load_config() を呼ぶ。
    """
    if config is None:
        from config_io import load_config
        config = load_config()
    return DesignSettings.from_dict(config.get("design", {}))
