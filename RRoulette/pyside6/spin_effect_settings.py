"""
spin_effect_settings.py — 特殊演出設定データ構造

RRoulettePWA v0.9.1 の SpinEffectSettings / EffectConfig を Python に移植。

公開 API:
  EffectKey     — 演出種別の文字列リテラル集合（str alias）
  EFFECT_KEYS   — 全 EffectKey の順序付きリスト
  EFFECT_TRIGGERS — EffectKey → 対応 role のマッピング
  EffectConfig  — 1 演出の設定 (dataclass)
  SpinEffectSettings — 全演出の設定集合 (dataclass)
  default_effect_config(key) — デフォルト EffectConfig
  default_spin_effect_settings() — 全演出デフォルト設定
  spin_effect_settings_from_dict(d) — config dict → SpinEffectSettings
  spin_effect_settings_to_dict(s)   — SpinEffectSettings → config dict
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

# ── 型定義 ──────────────────────────────────────────────────────────

SpecialRole = Literal["target", "avoid"]

EffectKey = Literal[
    "soundConfirm", "soundExpect", "soundNgConfirm",
    "miniCharTarget", "miniCharExpect", "miniCharNg",
    "cutInTarget", "cutInExpect", "cutInNg",
    "flashConfirm", "wheelGlow", "textChance",
]

EFFECT_KEYS: list[str] = [
    "soundConfirm", "soundExpect", "soundNgConfirm",
    "miniCharTarget", "miniCharExpect", "miniCharNg",
    "cutInTarget", "cutInExpect", "cutInNg",
    "flashConfirm", "wheelGlow", "textChance",
]

# どの role のときに各 effect が発火するか
EFFECT_TRIGGERS: dict[str, list[str]] = {
    "soundConfirm":   ["target"],
    "soundExpect":    ["target", "expect_candidate"],
    "soundNgConfirm": ["avoid"],
    "miniCharTarget": ["target"],
    "miniCharExpect": ["target", "expect_candidate"],
    "miniCharNg":     ["avoid"],
    "cutInTarget":    ["target"],
    "cutInExpect":    ["target", "expect_candidate"],
    "cutInNg":        ["avoid"],
    "flashConfirm":   ["target"],
    "wheelGlow":      ["target", "avoid", "expect_candidate"],
    "textChance":     ["target", "expect_candidate"],
}

# UI 表示名
EFFECT_DISPLAY_NAMES: dict[str, str] = {
    "soundConfirm":   "確定音",
    "soundExpect":    "期待度音",
    "soundNgConfirm": "NG確定音",
    "miniCharTarget": "ミニキャラ（ドラゴン）",
    "miniCharExpect": "ミニキャラ（ウサギ）",
    "miniCharNg":     "ミニキャラ（ゴースト）",
    "cutInTarget":    "カットイン（ドラゴン）",
    "cutInExpect":    "カットイン（ウサギ）",
    "cutInNg":        "カットイン（ゴースト）",
    "flashConfirm":   "画面フラッシュ",
    "wheelGlow":      "ホイール発光",
    "textChance":     "CHANCE!テキスト",
}


# ── EffectConfig ────────────────────────────────────────────────────

@dataclass
class EffectConfig:
    """1 演出の設定。

    Attributes:
        enabled: 演出の ON/OFF
        probability_range: 発火確率の範囲 (min, max) ∈ [0, 1]
        probability_random: True = 0〜100% 完全ランダム (probability_range 無視)
        timing_range: スピン開始からの発火タイミング比率の範囲 (min, max) ∈ [0, 1]
        timing_random: True = 0〜100% 完全ランダム (timing_range 無視)
        selected_variant: 0=ランダム (1〜5 から毎回抽選), 1〜5=固定
    """
    enabled: bool = True
    probability_range: tuple[float, float] = (0.01, 0.10)
    probability_random: bool = False
    timing_range: tuple[float, float] = (0.40, 0.60)
    timing_random: bool = False
    selected_variant: int = 0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "probability_range": list(self.probability_range),
            "probability_random": self.probability_random,
            "timing_range": list(self.timing_range),
            "timing_random": self.timing_random,
            "selected_variant": self.selected_variant,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EffectConfig":
        pr = d.get("probability_range", [0.01, 0.10])
        tr = d.get("timing_range", [0.40, 0.60])
        return cls(
            enabled=bool(d.get("enabled", True)),
            probability_range=(float(pr[0]), float(pr[1])),
            probability_random=bool(d.get("probability_random", False)),
            timing_range=(float(tr[0]), float(tr[1])),
            timing_random=bool(d.get("timing_random", False)),
            selected_variant=int(d.get("selected_variant", 0)),
        )


# ── デフォルト値定義 ────────────────────────────────────────────────

def _tr(center: float) -> tuple[float, float]:
    """タイミング中心値 ±0.10 の範囲を返す。"""
    return (max(0.0, center - 0.10), min(1.0, center + 0.10))


_PROB_SOUND = (0.01, 0.20)
_PROB_MINI  = (0.01, 0.15)
_PROB_CUTIN = (0.01, 0.05)
_PROB_OTHER = (0.01, 0.10)

_DEFAULT_CONFIGS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "soundConfirm":   (_PROB_SOUND, _tr(0.70)),
    "soundExpect":    (_PROB_SOUND, _tr(0.55)),
    "soundNgConfirm": (_PROB_SOUND, _tr(0.55)),
    "miniCharTarget": (_PROB_MINI,  _tr(0.40)),
    "miniCharExpect": (_PROB_MINI,  _tr(0.35)),
    "miniCharNg":     (_PROB_MINI,  _tr(0.40)),
    "cutInTarget":    (_PROB_CUTIN, _tr(0.45)),
    "cutInExpect":    (_PROB_CUTIN, _tr(0.35)),
    "cutInNg":        (_PROB_CUTIN, _tr(0.45)),
    "flashConfirm":   (_PROB_OTHER, _tr(0.85)),
    "wheelGlow":      (_PROB_OTHER, _tr(0.50)),
    "textChance":     (_PROB_OTHER, _tr(0.45)),
}


def default_effect_config(key: str) -> EffectConfig:
    """指定キーのデフォルト EffectConfig を返す。"""
    prob, timing = _DEFAULT_CONFIGS.get(key, (_PROB_OTHER, _tr(0.50)))
    return EffectConfig(
        enabled=True,
        probability_range=prob,
        probability_random=False,
        timing_range=timing,
        timing_random=False,
        selected_variant=0,
    )


# ── SpinEffectSettings ───────────────────────────────────────────────

@dataclass
class SpinEffectSettings:
    """全演出の設定集合。

    Attributes:
        enabled: マスター ON/OFF
        effects: EffectKey → EffectConfig のマッピング
    """
    enabled: bool = False
    all_random: bool = False   # True = ON の全演出のバリアントを毎回ランダム扱い
    effects: dict[str, EffectConfig] = field(default_factory=dict)

    def __post_init__(self):
        # 不足しているキーをデフォルトで補完する
        for key in EFFECT_KEYS:
            if key not in self.effects:
                self.effects[key] = default_effect_config(key)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "all_random": self.all_random,
            "effects": {k: v.to_dict() for k, v in self.effects.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpinEffectSettings":
        effects = {}
        raw_effects = d.get("effects", {})
        for key in EFFECT_KEYS:
            if key in raw_effects:
                effects[key] = EffectConfig.from_dict(raw_effects[key])
            else:
                effects[key] = default_effect_config(key)
        return cls(
            enabled=bool(d.get("enabled", False)),
            all_random=bool(d.get("all_random", False)),
            effects=effects,
        )


def default_spin_effect_settings() -> SpinEffectSettings:
    """全演出デフォルト設定（マスター OFF）を返す。"""
    return SpinEffectSettings(
        enabled=False,
        effects={key: default_effect_config(key) for key in EFFECT_KEYS},
    )
