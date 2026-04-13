"""
RRoulette — レイアウト計算（3モード × 横/縦 対応）

座標系:
  ローカル X軸 = 放射方向（セクター中央角方向）
  ローカル Y軸 = 接線方向（中央角から90°CCW）

テキスト方向別のスタック軸:
  direction=0 (横表示1・内→外): 行は接線方向に積む。各行幅 = font.measure → 放射方向
  direction=1 (横表示2・常に水平): 常に水平（angle=0）で横書き。
               行は垂直方向に積む。各行幅 ≈ 接線方向弦長（近似）
               行数制約 ≈ 放射方向安全幅（近似）
  direction=2 (縦表示1・外→内): 行は放射方向に積む。各行幅 = font.measure → 接線方向
               angle = mid_deg-90 → テキストの「上」= 外向き → char[0] が外側
  direction=3 (縦表示2・内→外): 同上（角度のみ異なる）
               angle = mid_deg+90 → テキストの「上」= 内向き → char[0] が内側
  direction=4 (縦表示3・常に垂直): 直立（angle=0）のため扇形座標系と非整合

LinePlacement.stack_offset の意味:
  direction=0: 接線方向オフセット（center_r 位置で接線方向に変位）
  direction=2/3: 放射方向オフセット（center_r からの半径方向変位）
  direction=4: 垂直方向オフセット（canvas Y 軸方向、正=下）
LinePlacement.extra_offset: 縦2/3 の複数列レイアウトで使う接線方向オフセット。

モード対応（_text_size_mode）:
  0: ellipsis  — 固定フォントサイズ・省略
  1: fit       — 可変サイズ・最大化（縦表示では複数列を試みて最大化）
  2: scale     — 可変サイズ・固定サイズ以下に縮小のみ（1列固定）
"""
import math
import tkinter.font as tkfont
from dataclasses import dataclass, field
from typing import List

from geometry import (
    SafeSector, get_sector_safe_area,
    get_radial_width_at_tangential_offset,
)
from line_break import layout_text_ellipsis, fit_text_to_width

# テキストと境界の間に確保する余白（px）
_TEXT_PAD = 6
# 縦表示複数列間の隙間（px）
_COL_GAP = 2
# fit モード: 最大フォントに対してこの比率以上の候補を「十分大きい」とみなす
# 大きさがほぼ同等なら少ない行数を優先、行数を増やして明確に大きくなる場合は改行を許可
_FIT_SIZE_THRESHOLD = 0.85
# fit モード: 1行候補がこのサイズ以上なら改行せず1行を優先する（明示 \n なしの場合のみ適用）
_FIT_MIN_SINGLE_LINE = 10


# ════════════════════════════════════════════════════════════════
#  データ構造
# ════════════════════════════════════════════════════════════════

@dataclass
class LinePlacement:
    """1行（または1文字）の描画情報。"""
    text: str
    stack_offset: float        # 主スタック方向オフセット（横=接線, 縦=放射）
    extra_offset: float = 0.0  # 縦表示複数列の接線方向オフセット
    radial_center: float = -1.0  # 横表示専用: 行ごとの放射方向中心（<0 なら LayoutResult.center_r を使用）


@dataclass
class LayoutResult:
    """1セクターの描画レイアウト結果。"""
    sector_index: int
    mode: int            # 0=ellipsis, 1=fit, 2=scale
    direction: int       # 0=横, 2=縦(外→内), 3=縦(内→外)
    font_family: str
    font_size: int
    line_height: int
    center_r: float      # 放射方向中心（全行共通）
    lines: List[LinePlacement]
    fits: bool
    was_truncated: bool = False


# ════════════════════════════════════════════════════════════════
#  外部エントリーポイント
# ════════════════════════════════════════════════════════════════

def build_all_sector_layouts(
    items: list,
    wheel_cx: float,
    wheel_cy: float,
    R: float,
    text_size_mode: int = 1,
    text_direction: int = 0,
    font_family: str = "Meiryo",
    fixed_font_size: int = 10,
    min_size: int = 6,
    max_size: int = 72,
    donut_r: float = 0.0,
    segments=None,
) -> list:
    """全セクターのレイアウトを計算して返す（angle=0 基準）。

    segments: Segment オブジェクトのリスト（.arc を使用）。
              渡した場合は各セグメントの実際の arc に基づいて安全領域を計算する。
              None の場合は等分割前提（360/n）にフォールバックする。
    """
    n = len(items)
    if n == 0:
        return []

    default_arc = 360.0 / n
    radial_margin_inner = max(12.0, R * 0.12)
    radial_margin_outer = max(8.0,  R * 0.05)

    results = []
    for i, text in enumerate(items):
        if segments is not None and i < len(segments):
            seg_arc = segments[i].arc
            start_angle = 90.0 + segments[i].start_angle
        else:
            seg_arc = default_arc
            start_angle = 90.0 + i * default_arc
        # seg_arc * 0.4 を上限とし safe_extent >= 20% of seg_arc を保証する
        # （下限 2.0° はやめて比例値を使う。極小 arc で safe_extent が消えるのを防ぐ）
        angle_margin_deg = min(max(0.5, seg_arc * 0.08), seg_arc * 0.4)
        safe = get_sector_safe_area(
            start_angle_deg=start_angle,
            extent_deg=seg_arc,
            inner_radius=max(donut_r, 0.0),
            outer_radius=R,
            radial_margin_inner=radial_margin_inner,
            radial_margin_outer=radial_margin_outer,
            angle_margin_deg=angle_margin_deg,
            index=i,
        )

        if text_direction == 4:
            if text_size_mode == 0:
                result = _layout_ellipsis_v1(text, i, font_family, fixed_font_size, safe)
            elif text_size_mode == 1:
                result = _layout_fit_v1(text, i, font_family, min_size, max_size, safe)
            else:
                result = _layout_scale_v1(text, i, font_family, fixed_font_size, min_size, max_size, safe)
        elif text_direction == 1:
            if text_size_mode == 0:
                result = _layout_ellipsis_h0(text, i, font_family, fixed_font_size, safe)
            elif text_size_mode == 1:
                result = _layout_fit_h0(text, i, font_family, min_size, max_size, safe)
            else:
                result = _layout_scale_h0(text, i, font_family, fixed_font_size, min_size, max_size, safe)
        elif text_direction in (2, 3):
            if text_size_mode == 0:
                result = _layout_ellipsis_v(text, i, text_direction, font_family, fixed_font_size, safe)
            elif text_size_mode == 1:
                result = _layout_fit_v(text, i, text_direction, font_family, min_size, max_size, safe)
            else:
                result = _layout_scale_v(text, i, text_direction, font_family, fixed_font_size, min_size, max_size, safe)
        else:
            if text_size_mode == 0:
                result = _layout_ellipsis(text, i, font_family, fixed_font_size, safe)
            elif text_size_mode == 1:
                result = _layout_fit(text, i, font_family, min_size, max_size, safe)
            else:
                result = _layout_scale(text, i, font_family, fixed_font_size, min_size, max_size, safe)

        results.append(result)

    return results


# ════════════════════════════════════════════════════════════════
#  共通ヘルパー
# ════════════════════════════════════════════════════════════════

def _make_font(family: str, size: int) -> tkfont.Font:
    return tkfont.Font(family=family, size=size, weight="bold")


def _build_placements(lines: list, line_height: int) -> list:
    """行リストをスタック方向中央寄せで LinePlacement リストに変換する。
    k=0 が最小オフセット（横=上端 / 縦=内側）。
    """
    n = len(lines)
    total = line_height * n
    start = -(total / 2) + line_height / 2
    return [
        LinePlacement(text=ln, stack_offset=start + k * line_height)
        for k, ln in enumerate(lines)
    ]


def _outer_r_placements(lines: list, line_height: int, safe: SafeSector, font) -> list:
    """横表示（direction=0）用: 外周端基準で各行の放射方向中心を決める LinePlacement リストを生成する。

    各行の外周側端 = safe_outer_radius - TEXT_PAD に揃える。
    行の描画中心（放射方向）= outer_edge - line_width / 2。
    接線方向オフセットは _build_placements と同じ中央寄せ。
    """
    outer_edge = safe.safe_outer_radius - _TEXT_PAD
    n = len(lines)
    total = line_height * n
    start = -(total / 2) + line_height / 2
    result = []
    for k, ln in enumerate(lines):
        w = font.measure(ln) if ln else 0
        rc = outer_edge - w / 2.0
        # 内周側へはみ出さないようクランプ
        rc = max(safe.safe_inner_radius + _TEXT_PAD, min(outer_edge, rc))
        result.append(LinePlacement(
            text=ln,
            stack_offset=start + k * line_height,
            radial_center=rc,
        ))
    return result


def _get_chars_v(text: str, direction: int) -> list:
    """縦表示用: テキストを文字リストに変換。

    \\n を除去し、direction=2（テキスト上=外向き・外→内読み）のとき char[0] が外側になるよう逆順にする。
    direction=2: create_text の先頭行 = 外側 → chars を逆順にして
                 _build_placements の k=0（内側）に末尾文字が来るようにする。
    direction=3: create_text の先頭行 = 内側 → そのまま。
    """
    chars = [c for c in text if c != '\n']
    if direction == 2:
        chars = chars[::-1]
    return chars


# ════════════════════════════════════════════════════════════════
#  横表示（direction=0）外周端基準 幅計算ヘルパー
# ════════════════════════════════════════════════════════════════

def _single_outer_w(t: float, outer_edge: float, safe: SafeSector) -> float:
    """接線方向位置 t での外周端基準放射方向利用可能幅（1点評価）。"""
    abs_t = abs(t)
    if abs_t < safe.safe_inner_radius:
        x_inner_donut = math.sqrt(safe.safe_inner_radius ** 2 - abs_t ** 2) + _TEXT_PAD
    else:
        x_inner_donut = _TEXT_PAD
    # half_extent_rad=0 は safe_extent=0（角度幅なし）→ 利用可能幅を 0 にする
    x_angular = (abs_t / math.tan(safe.half_extent_rad) + _TEXT_PAD
                 if safe.half_extent_rad > 0 else float('inf'))
    return max(0.0, outer_edge - max(x_inner_donut, x_angular))


def _radial_w_band(t_offset: float, line_height: float, safe: SafeSector) -> float:
    """行帯域（t_offset ± line_height/2）全体での最小利用可能幅を返す。

    中心線だけでなく行の上下端でも成立することを確認することで、
    実描画時に角度境界をはみ出す問題を防ぐ。
    """
    outer_edge = safe.safe_outer_radius - _TEXT_PAD
    half_h = line_height / 2.0
    return min(
        _single_outer_w(t_offset - half_h, outer_edge, safe),
        _single_outer_w(t_offset,           outer_edge, safe),
        _single_outer_w(t_offset + half_h, outer_edge, safe),
    )


# ════════════════════════════════════════════════════════════════
#  mode 0: 省略（ellipsis）— 横表示
# ════════════════════════════════════════════════════════════════

def _layout_ellipsis(
    text: str,
    sector_index: int,
    font_family: str,
    font_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """固定サイズ・省略表示のレイアウト（横表示）。"""
    font       = _make_font(font_family, font_size)
    line_h     = max(1, font.metrics("linespace"))
    center_r   = safe.outer_bias_r
    outer_edge = safe.safe_outer_radius - _TEXT_PAD
    radial_w   = _radial_w_band(0.0, line_h, safe)

    raw_lines = text.split('\n') if '\n' in text else [text]
    display_lines = [layout_text_ellipsis(ln, font, radial_w) for ln in raw_lines]
    truncated = any(d != r for d, r in zip(display_lines, raw_lines))

    max_rows = max(1, int(safe.tangential_chord_at(outer_edge) / line_h))
    display_lines = display_lines[:max_rows]

    return LayoutResult(
        sector_index=sector_index,
        mode=0,
        direction=0,
        font_family=font_family,
        font_size=font_size,
        line_height=line_h,
        center_r=center_r,
        lines=_outer_r_placements(display_lines, line_h, safe, font),
        fits=True,
        was_truncated=truncated,
    )


# ════════════════════════════════════════════════════════════════
#  mode 1: 収める（fit multiline）— 横表示
# ════════════════════════════════════════════════════════════════

def _layout_fit(
    text: str,
    sector_index: int,
    font_family: str,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """可変サイズ・可変行・行ごとの放射方向幅でレイアウトを計算する（横表示）。

    評価基準:
      全行数候補を収集し、最大フォントサイズの _FIT_SIZE_THRESHOLD 倍以上の候補に絞り、
      その中で最小行数を採用する。
      → 「行数を増やして明確に大きくなる場合は改行を許可」
        「大きさがほぼ同等なら少ない行数を優先」
    ユーザーが明示した \\n は段落区切りとして尊重し、最低行数の下限とする。
    """
    min_n = len(text.split('\n')) if '\n' in text else 1

    font_tmp   = _make_font(font_family, min_size)
    line_h_tmp = max(1, font_tmp.metrics("linespace"))
    chord_tmp  = safe.tangential_chord_at(safe.outer_bias_r)
    max_possible = max(min_n, max(1, int(chord_tmp / line_h_tmp)))

    # 全候補を収集: (n_lines, font_size, rows)
    candidates = []
    for n in range(min_n, max_possible + 1):
        sz = _max_font_for_n_lines(text, n, font_family, min_size, max_size, safe)
        if sz >= min_size:
            font   = _make_font(font_family, sz)
            line_h = max(1, font.metrics("linespace"))
            rows   = _try_fit_capped(text, font, line_h, safe, n)
            if rows is not None:
                candidates.append((n, sz, rows))

    if not candidates:
        font     = _make_font(font_family, min_size)
        line_h   = max(1, font.metrics("linespace"))
        radial_w = safe.safe_radial_height
        fallback = layout_text_ellipsis(text, font, radial_w)
        return LayoutResult(
            sector_index=sector_index,
            mode=1,
            direction=0,
            font_family=font_family,
            font_size=min_size,
            line_height=line_h,
            center_r=safe.outer_bias_r,
            lines=_outer_r_placements([fallback], line_h, safe, font),
            fits=False,
            was_truncated=True,
        )

    # 評価: 明示改行なしで1行が _FIT_MIN_SINGLE_LINE 以上なら改行しない
    # それ以下（1行が小さすぎる）場合は threshold フィルタで多行を許可する
    top_size = max(sz for _, sz, _ in candidates)
    threshold = top_size * _FIT_SIZE_THRESHOLD

    if min_n == 1:
        single_line_cands = [(n, sz, rows) for n, sz, rows in candidates if n == 1]
        if single_line_cands and single_line_cands[0][1] >= _FIT_MIN_SINGLE_LINE:
            filtered = single_line_cands
        else:
            filtered = [(n, sz, rows) for n, sz, rows in candidates if sz >= threshold]
            if not filtered:
                filtered = candidates
    else:
        filtered = [(n, sz, rows) for n, sz, rows in candidates if sz >= threshold]
        if not filtered:
            filtered = candidates

    # 最小行数 → 同じ行数なら最大フォント
    filtered.sort(key=lambda x: (x[0], -x[1]))
    best_n, best_sz, best_rows = filtered[0]

    # i340: 全角1文字の tangential overflow 後確認
    # _try_fit_capped は outer_edge での chord をチェックするが、
    # 実際のテキスト中心 rc = outer_edge - measure/2 は内側にあり、
    # その位置での tangential chord が小さい場合に視覚的クリップが生じる。
    # 対象を「改行なし・1文字・large font」に限定して保守的に縮小する。
    stripped = text.replace('\n', '').strip()
    if best_sz > min_size and len(stripped) == 1:
        outer_edge_tmp = safe.safe_outer_radius - _TEXT_PAD
        font_tmp   = _make_font(font_family, best_sz)
        line_h_tmp = max(1, font_tmp.metrics("linespace"))
        w_tmp      = font_tmp.measure(stripped)
        rc_tmp     = max(safe.safe_inner_radius + _TEXT_PAD,
                         min(outer_edge_tmp, outer_edge_tmp - w_tmp / 2.0))
        while best_sz > min_size and line_h_tmp > safe.tangential_chord_at(rc_tmp):
            best_sz   -= 1
            font_tmp   = _make_font(font_family, best_sz)
            line_h_tmp = max(1, font_tmp.metrics("linespace"))
            w_tmp      = font_tmp.measure(stripped)
            rc_tmp     = max(safe.safe_inner_radius + _TEXT_PAD,
                             min(outer_edge_tmp, outer_edge_tmp - w_tmp / 2.0))
        # 縮小後のフォントで rows を再計算
        if best_sz != filtered[0][1]:
            font_tmp   = _make_font(font_family, best_sz)
            line_h_tmp = max(1, font_tmp.metrics("linespace"))
            rows_tmp   = _try_fit_capped(text, font_tmp, line_h_tmp, safe, best_n)
            if rows_tmp is not None:
                best_rows = rows_tmp
                font      = font_tmp
                line_h    = line_h_tmp

    font   = _make_font(font_family, best_sz)
    line_h = max(1, font.metrics("linespace"))

    return LayoutResult(
        sector_index=sector_index,
        mode=1,
        direction=0,
        font_family=font_family,
        font_size=best_sz,
        line_height=line_h,
        center_r=safe.outer_bias_r,
        lines=_outer_r_placements(best_rows, line_h, safe, font),
        fits=True,
        was_truncated=False,
    )


def _try_fit(text: str, font, line_height: int, safe: SafeSector):
    center_r  = safe.outer_bias_r
    chord     = safe.tangential_chord_at(center_r)
    max_rows  = max(1, int(chord / line_height))

    total_t = line_height * max_rows
    start_t = -(total_t / 2) + line_height / 2
    slots   = []
    for k in range(max_rows):
        t_offset = start_t + k * line_height
        radial_w = get_radial_width_at_tangential_offset(
            t_offset, center_r, safe, padding=_TEXT_PAD
        )
        slots.append((t_offset, radial_w))

    if '\n' in text:
        return _fill_paragraphs(text.split('\n'), font, slots)
    else:
        return _fill_greedy(text, font, slots)


def _try_fit_capped(text: str, font, line_height: int, safe: SafeSector, max_lines: int):
    """_try_fit と同じだが、使用行数を max_lines に制限する。"""
    outer_edge = safe.safe_outer_radius - _TEXT_PAD
    chord      = safe.tangential_chord_at(outer_edge)
    max_rows   = min(max_lines, max(1, int(chord / line_height)))

    total_t = line_height * max_rows
    start_t = -(total_t / 2) + line_height / 2
    slots   = []
    for k in range(max_rows):
        t_offset = start_t + k * line_height
        radial_w = _radial_w_band(t_offset, line_height, safe)
        slots.append((t_offset, radial_w))

    if '\n' in text:
        return _fill_paragraphs(text.split('\n'), font, slots)
    else:
        return _fill_greedy(text, font, slots)


def _max_font_for_n_lines(
    text: str,
    max_lines: int,
    font_family: str,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> int:
    """text が max_lines 行以内に収まる最大フォントサイズを二分探索で求める。

    min_size でも収まらない場合は min_size - 1 を返す（不成立を示す）。
    """
    def fits(sz: int) -> bool:
        font   = _make_font(font_family, sz)
        line_h = max(1, font.metrics("linespace"))
        return _try_fit_capped(text, font, line_h, safe, max_lines) is not None

    if not fits(min_size):
        return min_size - 1

    lo, hi, best = min_size, max_size, min_size
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits(mid):
            best = mid
            lo   = mid + 1
        else:
            hi   = mid - 1
    return best


def _fill_greedy(text: str, font, slots: list):
    rows      = []
    remaining = text

    for t_offset, radial_w in slots:
        if not remaining:
            break
        if radial_w <= 0:
            continue
        fitted, remaining = fit_text_to_width(remaining, font, radial_w)
        rows.append(fitted)

    return rows if (not remaining and rows) else None


def _fill_paragraphs(paragraphs: list, font, slots: list):
    rows     = []
    slot_idx = 0

    for para in paragraphs:
        if slot_idx >= len(slots):
            return None
        if not para:
            rows.append('')
            slot_idx += 1
            continue

        remaining = para
        while remaining:
            if slot_idx >= len(slots):
                return None
            t_offset, radial_w = slots[slot_idx]
            if radial_w <= 0:
                slot_idx += 1
                continue
            fitted, remaining = fit_text_to_width(remaining, font, radial_w)
            rows.append(fitted)
            slot_idx += 1

    return rows if rows else None


# ════════════════════════════════════════════════════════════════
#  mode 2: 縮小（scale）— 横表示
# ════════════════════════════════════════════════════════════════

def _layout_scale(
    text: str,
    sector_index: int,
    font_family: str,
    fixed_font_size: int,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """全文表示・fixed_font_size を上限としたレイアウト（横表示）。"""
    center_r   = safe.outer_bias_r
    outer_edge = safe.safe_outer_radius - _TEXT_PAD
    chord      = safe.tangential_chord_at(outer_edge)

    lines   = text.split('\n') if '\n' in text else [text]
    n_lines = len(lines)

    def fits_at_size(sz: int) -> bool:
        font   = _make_font(font_family, sz)
        line_h = max(1, font.metrics("linespace"))
        if n_lines * line_h > chord:
            return False
        total_t = line_h * n_lines
        start_t = -(total_t / 2) + line_h / 2
        for k, ln in enumerate(lines):
            if ln:
                t_offset = start_t + k * line_h
                if font.measure(ln) > _radial_w_band(t_offset, line_h, safe):
                    return False
        return True

    lo, hi, best = min_size, min(fixed_font_size, max_size), min_size
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits_at_size(mid):
            best = mid
            lo   = mid + 1
        else:
            hi   = mid - 1

    font   = _make_font(font_family, best)
    line_h = max(1, font.metrics("linespace"))

    return LayoutResult(
        sector_index=sector_index,
        mode=2,
        direction=0,
        font_family=font_family,
        font_size=best,
        line_height=line_h,
        center_r=center_r,
        lines=_outer_r_placements(lines, line_h, safe, font),
        fits=True,
        was_truncated=False,
    )


# ════════════════════════════════════════════════════════════════
#  縦表示2/3 — 複数列レイアウトヘルパー
# ════════════════════════════════════════════════════════════════

def _max_size_for_n_cols(
    chars: list,
    n_cols: int,
    font_family: str,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> int:
    """n_cols 列レイアウトで収まる最大フォントサイズを二分探索で求める。

    制約:
      放射方向: ceil(n/n_cols) × line_h ≤ safe_radial_height
      接線方向: font.measure(ch) ≤ col_width  (内側行での弦長を基準)
    """
    n      = len(chars)
    n_rows = math.ceil(n / n_cols)

    def fits(sz: int) -> bool:
        font   = _make_font(font_family, sz)
        line_h = max(1, font.metrics("linespace"))
        # 放射方向: 外周端基準 — 最外文字が safe_outer_radius - TEXT_PAD になるよう center_r を逆算
        half_span = (n_rows - 1) / 2.0 * line_h
        # center = safe_outer - TEXT_PAD - half_span
        # 最内文字 = center - half_span = safe_outer - TEXT_PAD - (n_rows-1)*line_h
        inner_edge = safe.safe_outer_radius - _TEXT_PAD - (n_rows - 1) * line_h
        if inner_edge < safe.safe_inner_radius:
            return False
        # 接線方向: 最内行での弦長を使う（最も狭い）
        r_inner    = inner_edge  # 最内文字の半径
        tang_total = max(0.0, safe.tangential_chord_at(max(1.0, r_inner)) - _TEXT_PAD * 2)
        col_w = max(0.0, (tang_total - _COL_GAP * (n_cols - 1)) / n_cols)
        if col_w <= 0:
            return False
        for ch in chars:
            if ch and font.measure(ch) > col_w:
                return False
        return True

    lo, hi, best = min_size, max_size, min_size
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits(mid):
            best = mid
            lo   = mid + 1
        else:
            hi   = mid - 1

    return best


def _make_placements_v_cols(
    chars: list,
    n_cols: int,
    line_h: int,
    safe: SafeSector,
    center_r: float = -1.0,
) -> list:
    """n_cols 列レイアウトの LinePlacement リストを生成する。

    文字は列優先（col0: chars[0..n_rows-1], col1: chars[n_rows..], ...）で並べる。
    center_r が与えられた場合（外周端基準）、最内行の半径を使って接線弦長を計算する。
    """
    n      = len(chars)
    n_rows = math.ceil(n / n_cols)

    # 列の接線方向オフセット（最内行の半径での弦長を使用 — 最も狭い制約）
    if center_r >= 0:
        r_inner = center_r - (n_rows - 1) / 2.0 * line_h
    else:
        r_inner = safe.outer_bias_r
    tang_total = max(0.0, safe.tangential_chord_at(max(1.0, r_inner)) - _TEXT_PAD * 2)
    col_w      = max(0.0, (tang_total - _COL_GAP * (n_cols - 1)) / n_cols)
    col_step   = col_w + _COL_GAP
    col_t = [(c - (n_cols - 1) / 2) * col_step for c in range(n_cols)]

    # 行の放射方向オフセット（center_r からの対称）
    row_start = -(n_rows - 1) / 2 * line_h

    placements = []
    for idx, ch in enumerate(chars):
        col   = idx // n_rows
        row   = idx % n_rows
        r_off = row_start + row * line_h
        t_off = col_t[col] if col < n_cols else col_t[-1]
        placements.append(LinePlacement(text=ch, stack_offset=r_off, extra_offset=t_off))

    return placements


# ════════════════════════════════════════════════════════════════
#  mode 0: 省略（ellipsis）— 縦表示2/3
# ════════════════════════════════════════════════════════════════

def _layout_ellipsis_v(
    text: str,
    sector_index: int,
    direction: int,
    font_family: str,
    font_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """固定サイズ・省略表示のレイアウト（縦表示2/3）。"""
    font   = _make_font(font_family, font_size)
    line_h = max(1, font.metrics("linespace"))

    # 外周端基準: 最外文字が safe_outer_radius - TEXT_PAD に来る
    # (n-1)*line_h <= safe_radial_height - TEXT_PAD を満たす最大文字数
    max_rows   = max(1, int(max(0.0, safe.safe_radial_height - _TEXT_PAD) / line_h) + 1)
    orig_chars = [c for c in text if c != '\n']
    truncated  = len(orig_chars) > max_rows
    if truncated:
        chars = orig_chars[:max_rows - 1] + ['⋮']
    else:
        chars = orig_chars

    # direction=2 のみ逆順（char[0] が外側になるよう）
    if direction == 2:
        chars = chars[::-1]

    # center_r: 最外文字が safe_outer_radius - TEXT_PAD になる半径
    n        = len(chars)
    half_span = (n - 1) / 2.0 * line_h
    center_r  = safe.safe_outer_radius - _TEXT_PAD - half_span
    # 内周側クランプ（文字が safe_inner より内側に落ちないよう）
    center_r  = max(safe.safe_inner_radius + half_span, center_r)

    return LayoutResult(
        sector_index=sector_index,
        mode=0,
        direction=direction,
        font_family=font_family,
        font_size=font_size,
        line_height=line_h,
        center_r=center_r,
        lines=_build_placements(chars, line_h),
        fits=True,
        was_truncated=truncated,
    )


# ════════════════════════════════════════════════════════════════
#  mode 1: 収める（fit）— 縦表示2/3
#  複数列を試みて最大フォントサイズを実現する。
# ════════════════════════════════════════════════════════════════

def _layout_fit_v(
    text: str,
    sector_index: int,
    direction: int,
    font_family: str,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """可変サイズ・全文字表示・複数列対応のレイアウト（縦表示2/3）。

    n_cols = 1, 2, 3, 4 を試し、最大フォントサイズを実現する列数を採用する。
    """
    chars = _get_chars_v(text, direction)
    if not chars:
        chars = [' ']

    n = len(chars)
    max_cols = min(n, 4)

    best_sz   = -1
    best_cols = 1

    for n_cols in range(1, max_cols + 1):
        sz = _max_size_for_n_cols(chars, n_cols, font_family, min_size, max_size, safe)
        if sz > best_sz:
            best_sz   = sz
            best_cols = n_cols

    if best_sz < min_size:
        best_sz = min_size

    font   = _make_font(font_family, best_sz)
    line_h = max(1, font.metrics("linespace"))

    # 外周端基準 center_r
    n_rows    = math.ceil(len(chars) / best_cols)
    half_span = (n_rows - 1) / 2.0 * line_h
    center_r  = safe.safe_outer_radius - _TEXT_PAD - half_span
    center_r  = max(safe.safe_inner_radius + half_span, center_r)

    return LayoutResult(
        sector_index=sector_index,
        mode=1,
        direction=direction,
        font_family=font_family,
        font_size=best_sz,
        line_height=line_h,
        center_r=center_r,
        lines=_make_placements_v_cols(chars, best_cols, line_h, safe, center_r),
        fits=True,
        was_truncated=False,
    )


# ════════════════════════════════════════════════════════════════
#  mode 2: 縮小（scale）— 縦表示2/3（1列固定・固定サイズ以下に縮小）
# ════════════════════════════════════════════════════════════════

def _layout_scale_v(
    text: str,
    sector_index: int,
    direction: int,
    font_family: str,
    fixed_font_size: int,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """全文字表示・fixed_font_size 以下に縮小・1列固定のレイアウト（縦表示2/3）。"""
    chars = _get_chars_v(text, direction)
    if not chars:
        chars = [' ']

    sz = _max_size_for_n_cols(
        chars, 1, font_family, min_size, min(fixed_font_size, max_size), safe
    )

    font   = _make_font(font_family, sz)
    line_h = max(1, font.metrics("linespace"))

    # 外周端基準 center_r（1列固定）
    n_rows    = len(chars)
    half_span = (n_rows - 1) / 2.0 * line_h
    center_r  = safe.safe_outer_radius - _TEXT_PAD - half_span
    center_r  = max(safe.safe_inner_radius + half_span, center_r)

    return LayoutResult(
        sector_index=sector_index,
        mode=2,
        direction=direction,
        font_family=font_family,
        font_size=sz,
        line_height=line_h,
        center_r=center_r,
        lines=_build_placements(chars, line_h),
        fits=True,
        was_truncated=False,
    )


# ════════════════════════════════════════════════════════════════
#  縦表示1（直立縦積み）— 全モード共通ヘルパー
#
#  direction=1 は angle=0（直立）で文字を縦積みするため、扇形ローカル座標系と
#  非整合。近似として接線方向弦長を縦の高さ制約、放射方向安全幅を横幅制約に使う。
#  LayoutResult.lines は要素1つ（"\n".join(chars)）で構成し、
#  描画側は create_text(tx, ty, angle=0) の単一呼び出しで行う。
# ════════════════════════════════════════════════════════════════

def _layout_ellipsis_v1(
    text: str,
    sector_index: int,
    font_family: str,
    font_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """固定サイズ・省略表示のレイアウト（縦表示1・直立縦積み）。"""
    font   = _make_font(font_family, font_size)
    line_h = max(1, font.metrics("linespace"))
    tang_h = max(0.0, safe.tangential_chord_at(safe.outer_bias_r) - _TEXT_PAD * 2)

    chars = [c for c in text if c != '\n']
    max_v = max(1, int(tang_h / line_h))
    truncated = len(chars) > max_v
    if truncated:
        chars = chars[:max_v - 1] + ['⋮']

    return LayoutResult(
        sector_index=sector_index,
        mode=0,
        direction=4,
        font_family=font_family,
        font_size=font_size,
        line_height=line_h,
        center_r=safe.outer_bias_r,
        lines=[LinePlacement(text='\n'.join(chars), stack_offset=0.0)],
        fits=True,
        was_truncated=truncated,
    )


def _layout_fit_v1(
    text: str,
    sector_index: int,
    font_family: str,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """可変サイズ・全文字表示のレイアウト（縦表示1・直立縦積み）。"""
    chars = [c for c in text if c != '\n'] or [' ']
    n = len(chars)

    def fits(sz: int) -> bool:
        font   = _make_font(font_family, sz)
        line_h = max(1, font.metrics("linespace"))
        tang_h   = max(0.0, safe.tangential_chord_at(safe.outer_bias_r) - _TEXT_PAD * 2)
        radial_w = max(0.0, safe.safe_radial_height - _TEXT_PAD * 2)
        if n * line_h > tang_h:
            return False
        return all(not ch or font.measure(ch) <= radial_w for ch in chars)

    lo, hi, best = min_size, max_size, min_size
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits(mid):
            best = mid
            lo   = mid + 1
        else:
            hi   = mid - 1

    font   = _make_font(font_family, best)
    line_h = max(1, font.metrics("linespace"))
    return LayoutResult(
        sector_index=sector_index,
        mode=1,
        direction=4,
        font_family=font_family,
        font_size=best,
        line_height=line_h,
        center_r=safe.outer_bias_r,
        lines=[LinePlacement(text='\n'.join(chars), stack_offset=0.0)],
        fits=True,
        was_truncated=False,
    )


def _layout_scale_v1(
    text: str,
    sector_index: int,
    font_family: str,
    fixed_font_size: int,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """全文字表示・fixed_font_size 以下に縮小のレイアウト（縦表示1・直立縦積み）。"""
    chars = [c for c in text if c != '\n'] or [' ']
    n = len(chars)

    def fits(sz: int) -> bool:
        font   = _make_font(font_family, sz)
        line_h = max(1, font.metrics("linespace"))
        tang_h   = max(0.0, safe.tangential_chord_at(safe.outer_bias_r) - _TEXT_PAD * 2)
        radial_w = max(0.0, safe.safe_radial_height - _TEXT_PAD * 2)
        if n * line_h > tang_h:
            return False
        return all(not ch or font.measure(ch) <= radial_w for ch in chars)

    lo, hi, best = min_size, min(fixed_font_size, max_size), min_size
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits(mid):
            best = mid
            lo   = mid + 1
        else:
            hi   = mid - 1

    font   = _make_font(font_family, best)
    line_h = max(1, font.metrics("linespace"))
    return LayoutResult(
        sector_index=sector_index,
        mode=2,
        direction=4,
        font_family=font_family,
        font_size=best,
        line_height=line_h,
        center_r=safe.outer_bias_r,
        lines=[LinePlacement(text='\n'.join(chars), stack_offset=0.0)],
        fits=True,
        was_truncated=False,
    )


# ════════════════════════════════════════════════════════════════
#  横表示・常に水平（direction=1）— 全モード共通ヘルパー
#
#  direction=4 は angle=0（水平固定）で横書きテキストを描画する。
#  接線方向弦長を行幅制約、放射方向安全幅を行数（縦高さ）制約として近似する。
#  セクターが12時・6時付近では近似精度が高く、3時・9時付近では誤差が出る。
#  stack_offset は canvas Y 軸方向オフセット（正=下）。
# ════════════════════════════════════════════════════════════════

def _layout_ellipsis_h0(
    text: str,
    sector_index: int,
    font_family: str,
    font_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """固定サイズ・省略表示のレイアウト（横表示・常に水平）。"""
    font     = _make_font(font_family, font_size)
    line_h   = max(1, font.metrics("linespace"))
    center_r = safe.outer_bias_r
    tang_w   = max(0.0, safe.tangential_chord_at(center_r) - _TEXT_PAD * 2)
    radial_h = max(0.0, safe.safe_radial_height - _TEXT_PAD * 2)

    raw_lines = text.split('\n') if '\n' in text else [text]
    display_lines = [layout_text_ellipsis(ln, font, tang_w) for ln in raw_lines]
    truncated = any(d != r for d, r in zip(display_lines, raw_lines))

    max_rows = max(1, int(radial_h / line_h))
    if len(display_lines) > max_rows:
        display_lines = display_lines[:max_rows]
        truncated = True

    return LayoutResult(
        sector_index=sector_index,
        mode=0,
        direction=1,
        font_family=font_family,
        font_size=font_size,
        line_height=line_h,
        center_r=center_r,
        lines=_build_placements(display_lines, line_h),
        fits=True,
        was_truncated=truncated,
    )


def _layout_fit_h0(
    text: str,
    sector_index: int,
    font_family: str,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """可変サイズ・全文字表示のレイアウト（横表示・常に水平）。

    優先順位:
      1. 行数が少ないこと（最小行数優先）
      2. 同じ行数ならフォントサイズが大きいこと
    """
    min_n    = len(text.split('\n')) if '\n' in text else 1
    radial_h = max(0.0, safe.safe_radial_height - _TEXT_PAD * 2)

    def try_n(n: int, sz: int):
        """sz サイズで n 行以内に収まるか試す。成功時に行リストを返す。"""
        font     = _make_font(font_family, sz)
        line_h   = max(1, font.metrics("linespace"))
        tang_w   = max(0.0, safe.tangential_chord_at(safe.outer_bias_r) - _TEXT_PAD * 2)
        max_rows = min(n, max(1, int(radial_h / line_h)))
        return _fill_greedy_h0(text, font, tang_w, max_rows)

    def max_font_h0_n(n: int) -> int:
        """n 行以内で収まる最大フォントサイズを二分探索で求める。"""
        if try_n(n, min_size) is None:
            return min_size - 1
        lo, hi, best = min_size, max_size, min_size
        while lo <= hi:
            mid = (lo + hi) // 2
            if try_n(n, mid) is not None:
                best = mid
                lo   = mid + 1
            else:
                hi   = mid - 1
        return best

    # min_size での最大行数を上限として探索
    font_tmp   = _make_font(font_family, min_size)
    line_h_tmp = max(1, font_tmp.metrics("linespace"))
    max_possible = max(min_n, max(1, int(radial_h / line_h_tmp)))

    # 全候補を収集して比較
    candidates = []
    for n in range(min_n, max_possible + 1):
        sz = max_font_h0_n(n)
        if sz >= min_size:
            rows = try_n(n, sz)
            if rows is not None:
                candidates.append((n, sz, rows))

    if not candidates:
        font   = _make_font(font_family, min_size)
        line_h = max(1, font.metrics("linespace"))
        tang_w = max(0.0, safe.tangential_chord_at(safe.outer_bias_r) - _TEXT_PAD * 2)
        fallback = layout_text_ellipsis(text, font, tang_w)
        return LayoutResult(
            sector_index=sector_index,
            mode=1,
            direction=1,
            font_family=font_family,
            font_size=min_size,
            line_height=line_h,
            center_r=safe.outer_bias_r,
            lines=_build_placements([fallback], line_h),
            fits=False,
            was_truncated=True,
        )

    top_size = max(sz for _, sz, _ in candidates)
    threshold = top_size * _FIT_SIZE_THRESHOLD

    if min_n == 1:
        single_line_cands = [(n, sz, rows) for n, sz, rows in candidates if n == 1]
        if single_line_cands and single_line_cands[0][1] >= _FIT_MIN_SINGLE_LINE:
            filtered = single_line_cands
        else:
            filtered = [(n, sz, rows) for n, sz, rows in candidates if sz >= threshold]
            if not filtered:
                filtered = candidates
    else:
        filtered = [(n, sz, rows) for n, sz, rows in candidates if sz >= threshold]
        if not filtered:
            filtered = candidates

    filtered.sort(key=lambda x: (x[0], -x[1]))
    best_n, best_size, best_rows = filtered[0]

    font   = _make_font(font_family, best_size)
    line_h = max(1, font.metrics("linespace"))

    return LayoutResult(
        sector_index=sector_index,
        mode=1,
        direction=1,
        font_family=font_family,
        font_size=best_size,
        line_height=line_h,
        center_r=safe.outer_bias_r,
        lines=_build_placements(best_rows, line_h),
        fits=True,
        was_truncated=False,
    )


def _fill_greedy_h0(text: str, font, tang_w: float, max_rows: int):
    """横表示・常に水平用グリーディ折り返し。tang_w幅・max_rows行に収まれば行リストを返す。"""
    if tang_w <= 0 or max_rows <= 0:
        return None

    rows = []

    if '\n' in text:
        for para in text.split('\n'):
            if not para:
                if len(rows) >= max_rows:
                    return None
                rows.append('')
                continue
            remaining = para
            while remaining:
                if len(rows) >= max_rows:
                    return None
                fitted, remaining = fit_text_to_width(remaining, font, tang_w)
                rows.append(fitted)
    else:
        remaining = text
        while remaining:
            if len(rows) >= max_rows:
                return None
            fitted, remaining = fit_text_to_width(remaining, font, tang_w)
            rows.append(fitted)

    return rows if rows else None


def _layout_scale_h0(
    text: str,
    sector_index: int,
    font_family: str,
    fixed_font_size: int,
    min_size: int,
    max_size: int,
    safe: SafeSector,
) -> LayoutResult:
    """全文表示・fixed_font_size を上限としたレイアウト（横表示・常に水平）。"""
    center_r = safe.outer_bias_r

    lines   = text.split('\n') if '\n' in text else [text]
    n_lines = len(lines)

    def fits_at_size(sz: int) -> bool:
        font     = _make_font(font_family, sz)
        line_h   = max(1, font.metrics("linespace"))
        tang_w   = max(0.0, safe.tangential_chord_at(center_r) - _TEXT_PAD * 2)
        radial_h = max(0.0, safe.safe_radial_height - _TEXT_PAD * 2)
        if n_lines * line_h > radial_h:
            return False
        for ln in lines:
            if ln and font.measure(ln) > tang_w:
                return False
        return True

    lo, hi, best = min_size, min(fixed_font_size, max_size), min_size
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits_at_size(mid):
            best = mid
            lo   = mid + 1
        else:
            hi   = mid - 1

    font   = _make_font(font_family, best)
    line_h = max(1, font.metrics("linespace"))

    return LayoutResult(
        sector_index=sector_index,
        mode=2,
        direction=1,
        font_family=font_family,
        font_size=best,
        line_height=line_h,
        center_r=center_r,
        lines=_build_placements(lines, line_h),
        fits=True,
        was_truncated=False,
    )
