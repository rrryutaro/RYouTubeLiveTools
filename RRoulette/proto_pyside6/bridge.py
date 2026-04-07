"""
PySide6 プロトタイプ — 既存ロジック橋渡し層

既存 RRoulette のロジック資産（constants, design_settings, geometry,
layout_search, config_utils）と PySide6 UI 層を接続する。

責務:
  - sys.path を通して既存モジュールを import 可能にする
  - layout_search の tkinter.font 依存を QtFontAdapter でモンキーパッチ
  - 設定読み込み（raw config dict / AppSettings / DesignSettings）
  - セグメント構築（確率・分割・配置の既存ロジック呼び出し）
  - UI 側へ渡すデータの整形

設定の流れ:
  config file → load_config() → raw dict
                                  ├→ load_app_settings() → AppSettings  (型付き設定)
                                  ├→ load_design()       → DesignSettings (デザイン)
                                  ├→ load_items()         → list[str]     (項目テキスト)
                                  └→ build_segments_from_config() → segments (セグメント)
"""

import sys
import os
import json

# ── 既存モジュールへのパスを通す ─────────────────────────────────
_RROULETTE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..")
)
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

# ── 既存モジュールの import ───────────────────────────────────────
# tkinter 非依存モジュール: そのまま import
from constants import (
    SEGMENT_COLORS, BG, PANEL, ACCENT, DARK2, WHITE, GOLD,
    SIZE_PROFILES, MIN_W, MIN_H, MIN_R,
    SIDEBAR_W, CFG_PANEL_W, SIDEBAR_MIN_W,
    MAIN_PANEL_PAD, POINTER_OVERHANG, WHEEL_OUTER_MARGIN,
    MAIN_MIN_W, MAIN_MIN_H,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES,
    ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES,
    DONUT_DRAW_RADIUS, DONUT_HIT_RADIUS,
    Segment, VERSION,
)
from design_settings import (
    DesignSettings, DesignPresetManager,
    GlobalColors, WheelDesign, SegmentDesign, PointerDesign,
    LogDesign, FontSettings, WheelFontSettings, ResultDesign,
    DESIGN_PRESETS, DESIGN_PRESET_NAMES,
    SEGMENT_COLOR_PRESETS, SEGMENT_PRESET_NAMES,
)
from geometry import (
    SafeSector, get_sector_safe_area,
    get_radial_width_at_tangential_offset,
    polar_to_canvas, normalize_angle_deg,
)
from config_utils import CONFIG_FILE, BASE_DIR

# ── layout_search の tkinter.font 依存をモンキーパッチ ─────────────
# layout_search は import 時に `import tkinter.font as tkfont` を実行するため、
# import 前にモックモジュールを挿入して回避し、_make_font を差し替える。
from font_adapter import make_qt_font, QtFontAdapter

# tkinter.font のモックを sys.modules に挿入
import types
_mock_tkfont = types.ModuleType("tkinter.font")
_mock_tkfont.Font = QtFontAdapter  # 形式的な代替（直接は使われない）
if "tkinter" not in sys.modules:
    _mock_tk = types.ModuleType("tkinter")
    sys.modules["tkinter"] = _mock_tk
if "tkinter.font" not in sys.modules:
    sys.modules["tkinter.font"] = _mock_tkfont

# これで layout_search を import 可能に
import layout_search
from layout_search import (
    build_all_sector_layouts,
    LayoutResult, LinePlacement,
)

# _make_font を QtFontAdapter 版に差し替え
layout_search._make_font = make_qt_font


# ── 設定読み込み ──────────────────────────────────────────────────

from app_settings import AppSettings


def load_app_settings(config: dict | None = None) -> AppSettings:
    """config dict から型付き AppSettings を構築する。

    MainWindow は raw config dict ではなくこの関数経由で設定を取得する。
    将来設定の追加時は AppSettings.from_config() のみ修正すればよい。
    """
    if config is None:
        config = load_config()
    return AppSettings.from_config(config)


def load_config() -> dict:
    """既存の設定ファイルを読み込む。ファイルがなければ空辞書を返す。"""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_design(config: dict | None = None) -> DesignSettings:
    """設定辞書からデザイン設定を復元する。"""
    if config is None:
        config = load_config()
    return DesignSettings.from_dict(config.get("design", {}))


def _extract_item_text(entry) -> str | None:
    """項目エントリからテキストを抽出する。
    既存の設定形式では項目は dict（{'text': ..., 'enabled': ..., ...}）で保存されている。
    enabled=False の項目は None を返す（ホイールに表示しない）。
    """
    if isinstance(entry, str):
        return entry if entry.strip() else None
    if isinstance(entry, dict):
        if not entry.get("enabled", True):
            return None
        return entry.get("text", "")
    return None


def load_items(config: dict | None = None) -> list[str]:
    """設定辞書から現在の有効な項目テキストリストを取得する。"""
    if config is None:
        config = load_config()
    patterns = config.get("item_patterns", {})
    current = config.get("current_pattern", "デフォルト")
    raw_items = patterns.get(current, [])
    if not raw_items:
        for v in patterns.values():
            if v:
                raw_items = v
                break
    # dict → str 変換 + enabled フィルタ
    items = []
    for entry in raw_items:
        text = _extract_item_text(entry)
        if text is not None and text.strip():
            items.append(text)
    return items


def load_item_entries(config: dict | None = None) -> list[dict]:
    """設定辞書から現在の有効な項目エントリをリストで返す。

    各エントリは dict 形式で、少なくとも以下のキーを含む:
      - text: 項目テキスト
      - enabled: 有効かどうか（True のみ返す）
      - split_count: 分割数
      - prob_mode: 確率モード (None / "fixed" / "weight")
      - prob_value: 確率値

    項目データ（テキスト・確率・分割等）と設定データ（AppSettings）を
    分離して扱うための入口。将来の項目編集 UI はこのデータを基にする。
    """
    if config is None:
        config = load_config()
    patterns = config.get("item_patterns", {})
    current = config.get("current_pattern", "デフォルト")
    raw_items = patterns.get(current, [])
    if not raw_items:
        for v in patterns.values():
            if v:
                raw_items = v
                break
    entries = []
    for entry in raw_items:
        if isinstance(entry, str):
            if entry.strip():
                entries.append({
                    "text": entry,
                    "enabled": True,
                    "split_count": 1,
                    "prob_mode": None,
                    "prob_value": None,
                })
        elif isinstance(entry, dict):
            if entry.get("enabled", True):
                entries.append({
                    "text": entry.get("text", ""),
                    "enabled": True,
                    "split_count": entry.get("split_count", 1),
                    "prob_mode": entry.get("prob_mode"),
                    "prob_value": entry.get("prob_value"),
                })
    return entries


def load_weights_from_config(config: dict | None = None) -> list[float]:
    """設定辞書から項目の重み（split_count ベース）を取得する。"""
    if config is None:
        config = load_config()
    patterns = config.get("item_patterns", {})
    current = config.get("current_pattern", "デフォルト")
    raw_items = patterns.get(current, [])
    if not raw_items:
        for v in patterns.values():
            if v:
                raw_items = v
                break
    weights = []
    for entry in raw_items:
        text = _extract_item_text(entry)
        if text is not None and text.strip():
            if isinstance(entry, dict):
                weights.append(float(entry.get("split_count", 1) or 1))
            else:
                weights.append(1.0)
    return weights


def build_segments_from_config(config: dict | None = None) -> tuple[list[Segment], list[str]]:
    """既存の rroulette.py _rebuild_segments と同一のロジックでセグメントを構築する。

    Returns:
        (segments, items_text_list)
        segments: Segment リスト（start_angle 付き）
        items_text_list: 描画用テキストリスト（segments と同順）

    既存の _rebuild_segments の処理フロー:
      1. enabled フィルタ
      2. _calc_probs で確率計算（fixed/weight/default 対応）
      3. _apply_split で split_count 展開
      4. _standard_order で均等分散配置
      5. arrangement_direction で反転
      6. start_angle 累積
    """
    if config is None:
        config = load_config()
    patterns = config.get("item_patterns", {})
    current = config.get("current_pattern", "デフォルト")
    raw_entries = patterns.get(current, [])
    if not raw_entries:
        for v in patterns.values():
            if v:
                raw_entries = v
                break

    # 1. enabled フィルタ（orig_index を保持）
    enabled = []
    for i, entry in enumerate(raw_entries):
        if isinstance(entry, dict):
            if entry.get("enabled", True):
                enabled.append((entry, i))
        elif isinstance(entry, str) and entry.strip():
            enabled.append({"text": entry, "prob_mode": None, "prob_value": None, "split_count": 1}, i)

    if not enabled:
        return [], []

    enabled_entries = [e for e, _ in enabled]
    orig_indices = [i for _, i in enabled]

    # 2. _calc_probs
    probs = _calc_probs(enabled_entries)

    # 3. _apply_split
    entries_with_probs = [
        (enabled_entries[j], orig_indices[j], probs[j])
        for j in range(len(enabled_entries))
    ]
    raw_segs = _apply_split(entries_with_probs)

    # 4. _standard_order
    ordered = _standard_order(raw_segs)

    # 5. pivot（先頭項目を最初に配置）
    if ordered:
        first_item_idx = min(idx for _, idx, _ in ordered)
        pivot = next(
            (i for i, (_, idx, _) in enumerate(ordered) if idx == first_item_idx),
            0,
        )
        if pivot > 0:
            ordered = ordered[pivot:] + ordered[:pivot]

    # 6. arrangement_direction
    arrangement_direction = config.get("arrangement_direction", 0)
    if arrangement_direction == 0:
        ordered = list(reversed(ordered))

    # 7. start_angle 累積
    segments = []
    angle = 0.0
    for text, idx, arc in ordered:
        seg = Segment(item_text=text, item_index=idx, arc=arc, start_angle=angle)
        segments.append(seg)
        angle += arc

    items = [seg.item_text for seg in segments]
    return segments, items


def _calc_probs(entries: list[dict]) -> list[float]:
    """有効な entries リストの各エントリーの確率 (%) を計算して返す。
    既存の rroulette.py _calc_probs と同一ロジック。
    """
    n = len(entries)
    if n == 0:
        return []

    fixed_idx = [i for i, e in enumerate(entries) if e.get("prob_mode") == "fixed"]
    nonfixed_idx = [i for i, e in enumerate(entries) if e.get("prob_mode") != "fixed"]

    sum_fixed = sum(entries[i].get("prob_value") or 0.0 for i in fixed_idx)
    sum_fixed = min(sum_fixed, 99.999)
    remaining = 100.0 - sum_fixed

    weights = []
    for i in nonfixed_idx:
        e = entries[i]
        if e.get("prob_mode") == "weight" and e.get("prob_value") is not None:
            weights.append(max(0.0001, float(e["prob_value"])))
        else:
            weights.append(1.0)
    total_w = sum(weights) or 1.0

    probs = [0.0] * n
    for i in fixed_idx:
        probs[i] = float(entries[i].get("prob_value") or 0.0)
    for j, i in enumerate(nonfixed_idx):
        probs[i] = remaining * weights[j] / total_w
    return probs


def _apply_split(entries_with_probs: list) -> list:
    """split_count に基づいてセグメントを展開する。
    既存の rroulette.py _apply_split と同一ロジック。
    """
    raw = []
    for entry, orig_idx, prob in entries_with_probs:
        k = max(1, min(10, int(entry.get("split_count") or 1)))
        sub_arc = prob * 360.0 / 100.0 / k
        for _ in range(k):
            raw.append((entry["text"], orig_idx, sub_arc))
    return raw


def _standard_order(raw_segs: list) -> list:
    """分割された項目を均等分散配置し、残りを順番に埋めた並び順を返す。
    既存の rroulette.py _standard_order と同一ロジック。
    """
    T = len(raw_segs)
    if T == 0:
        return []

    seen = []
    by_idx = {}
    for text, idx, arc in raw_segs:
        if idx not in by_idx:
            by_idx[idx] = []
            seen.append(idx)
        by_idx[idx].append((text, idx, arc))

    split_idxs = [i for i in seen if len(by_idx[i]) > 1]
    nonsplit_idxs = [i for i in seen if len(by_idx[i]) == 1]

    if not split_idxs:
        return list(raw_segs)

    fillers = [by_idx[i][0] for i in nonsplit_idxs]

    # 単一 split: Bresenham 法
    if len(split_idxs) == 1:
        subs = by_idx[split_idxs[0]]
        K, F = len(subs), len(fillers)
        result = []
        fi = 0
        for k in range(K):
            n_fill = (k + 1) * F // K - k * F // K
            result.extend(fillers[fi:fi + n_fill])
            fi += n_fill
            result.append(subs[k])
        return result

    # 複数 split: 位相ずらし greedy
    total_arc = sum(a for _, _, a in raw_segs)
    total_split_count = sum(len(by_idx[i]) for i in split_idxs)

    split_queue = []
    for i_idx, sidx in enumerate(split_idxs):
        subs = by_idx[sidx]
        K = len(subs)
        phase = i_idx * total_arc / total_split_count
        for j, sub in enumerate(subs):
            target = (phase + j * total_arc / K) % total_arc
            split_queue.append((target, sub))
    split_queue.sort(key=lambda x: x[0])

    result = []
    cum = 0.0
    fi = 0
    si = 0

    while si < len(split_queue) or fi < len(fillers):
        if si >= len(split_queue):
            result.extend(fillers[fi:])
            break

        target, split_seg = split_queue[si]
        center_now = cum + split_seg[2] / 2.0

        if fi >= len(fillers):
            result.append(split_seg)
            cum += split_seg[2]
            si += 1
        elif center_now >= target:
            result.append(split_seg)
            cum += split_seg[2]
            si += 1
        else:
            center_after = cum + fillers[fi][2] + split_seg[2] / 2.0
            if abs(center_now - target) < abs(center_after - target):
                result.append(split_seg)
                cum += split_seg[2]
                si += 1
            else:
                result.append(fillers[fi])
                cum += fillers[fi][2]
                fi += 1

    return result
