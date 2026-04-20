"""
segment_builder.py — セグメント構築の純ロジック層

bridge.py から切り出したセグメント構築責務。
tkinter / UI 非依存。dict / list / dataclass / 数値処理のみで完結する。

公開 API:
  build_segments_from_entries(entries, config) → (list[Segment], list[str])
  build_segments_from_config(config)           → (list[Segment], list[str])
"""

import sys
import os

# RRoulette ルートを sys.path に追加（constants の参照用）
_RROULETTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _RROULETTE_DIR not in sys.path:
    sys.path.insert(0, _RROULETTE_DIR)

from constants import Segment
from item_entry import ItemEntry
from item_data_io import _get_current_pattern_items
from config_io import load_config


def build_segments_from_entries(
    entries: list[ItemEntry], config: dict | None = None
) -> tuple[list[Segment], list[str]]:
    """ItemEntry リストからセグメントを構築する。

    編集 UI から渡された entries を直接使用する。
    enabled=True の項目のみ対象。config は arrangement_direction の参照用。
    """
    if config is None:
        config = {}
    raw_entries = [e.to_dict() for e in entries if e.enabled]
    if not raw_entries:
        return [], []

    probs = _calc_probs(raw_entries)
    entries_with_probs = [
        (raw_entries[j], j, probs[j]) for j in range(len(raw_entries))
    ]
    raw_segs = _apply_split(entries_with_probs)
    ordered = _standard_order(raw_segs)

    if ordered:
        first_item_idx = min(idx for _, idx, _ in ordered)
        pivot = next(
            (i for i, (_, idx, _) in enumerate(ordered) if idx == first_item_idx),
            0,
        )
        if pivot > 0:
            ordered = ordered[pivot:] + ordered[:pivot]

    arrangement_direction = config.get("arrangement_direction", 0)
    if arrangement_direction == 0:
        ordered = list(reversed(ordered))

    segments = []
    angle = 0.0
    for text, idx, arc in ordered:
        seg = Segment(item_text=text, item_index=idx, arc=arc, start_angle=angle)
        segments.append(seg)
        angle += arc

    items = [seg.item_text for seg in segments]
    return segments, items


def build_segments_from_config(config: dict | None = None) -> tuple[list[Segment], list[str]]:
    """config dict からセグメントを構築する。

    既存の _rebuild_segments と同一のロジック。
    処理フロー:
      1. enabled フィルタ
      2. _calc_probs で確率計算（fixed/weight/default 対応）
      3. _apply_split で split_count 展開
      4. _standard_order で均等分散配置
      5. arrangement_direction で反転
      6. start_angle 累積
    """
    if config is None:
        config = load_config()
    raw_entries = _get_current_pattern_items(config)

    enabled = []
    for i, entry in enumerate(raw_entries):
        if isinstance(entry, dict):
            if entry.get("enabled", True):
                enabled.append((entry, i))
        elif isinstance(entry, str) and entry.strip():
            enabled.append(({"text": entry, "prob_mode": None, "prob_value": None, "split_count": 1}, i))

    if not enabled:
        return [], []

    enabled_entries = [e for e, _ in enabled]
    orig_indices = [i for _, i in enabled]

    probs = _calc_probs(enabled_entries)
    entries_with_probs = [
        (enabled_entries[j], orig_indices[j], probs[j])
        for j in range(len(enabled_entries))
    ]
    raw_segs = _apply_split(entries_with_probs)
    ordered = _standard_order(raw_segs)

    if ordered:
        first_item_idx = min(idx for _, idx, _ in ordered)
        pivot = next(
            (i for i, (_, idx, _) in enumerate(ordered) if idx == first_item_idx),
            0,
        )
        if pivot > 0:
            ordered = ordered[pivot:] + ordered[:pivot]

    arrangement_direction = config.get("arrangement_direction", 0)
    if arrangement_direction == 0:
        ordered = list(reversed(ordered))

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
    # i339: split セグメントを fillers より先に配置し、
    # 「分割後の先頭が必ず split 項目になる」並び順を保証する。
    if len(split_idxs) == 1:
        subs = by_idx[split_idxs[0]]
        K, F = len(subs), len(fillers)
        result = []
        fi = 0
        for k in range(K):
            result.append(subs[k])
            n_fill = (k + 1) * F // K - k * F // K
            result.extend(fillers[fi:fi + n_fill])
            fi += n_fill
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
