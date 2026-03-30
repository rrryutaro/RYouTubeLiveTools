"""
RRoulette — テキスト省略・行分割ユーティリティ
  mode 1/3 用: 省略表示（ellipsis）
  mode 2 用:   可用幅に収まるだけ先頭から貪欲に詰める（greedy fill）
"""

_PRIORITY_BREAK_CHARS = (' ', '　', '/', '・', '-', '。', '、', ':', '：')


# ════════════════════════════════════════════════════════════════
#  mode 1: 省略（ellipsis）
# ════════════════════════════════════════════════════════════════

def layout_text_ellipsis(text: str, font_obj, available_width: float) -> str:
    """available_width に収まるようにテキストを省略して返す。

    - 既存の \\n がある場合は各行を個別に省略する。
    - 収まる場合はそのまま返す。
    - 収まらない場合は末尾を削って '…' を付ける。
    - '…' すら入らない場合はできる限り入れる（空文字になることも許容）。
    """
    if '\n' in text:
        lines = [_ellipsis_single(ln, font_obj, available_width) for ln in text.split('\n')]
        return '\n'.join(lines)
    return _ellipsis_single(text, font_obj, available_width)


def _ellipsis_single(text: str, font_obj, available_width: float) -> str:
    if font_obj.measure(text) <= available_width:
        return text
    ellipsis = '…'
    ellipsis_w = font_obj.measure(ellipsis)
    if ellipsis_w > available_width:
        # '…' すら入らない — 文字を1つずつ試す
        result = ''
        for ch in text:
            if font_obj.measure(result + ch) > available_width:
                break
            result += ch
        return result
    # 末尾から削って '…' を付ける
    truncated = text
    while truncated and font_obj.measure(truncated + ellipsis) > available_width:
        truncated = truncated[:-1]
    return truncated + ellipsis


# ════════════════════════════════════════════════════════════════
#  mode 2: 貪欲詰め（greedy fill）
# ════════════════════════════════════════════════════════════════

def greedy_fill_lines(text: str, font_obj, get_width_for_line_idx) -> list:
    """テキストを各行の利用可能幅に収まるように先頭から貪欲に詰めた行リストを返す。

    Args:
        text: 表示対象テキスト（\\n を含む場合はそれを尊重する）
        font_obj: tkinter.font.Font オブジェクト
        get_width_for_line_idx: 行インデックス(0起算)を受けて利用可能幅(px)を返す関数

    Returns:
        行文字列のリスト。全文字が詰め込めた場合は fitted=True、
        利用可能行が尽きても文字が余った場合は fitted=False。
        → (lines: list[str], fitted: bool)
    """
    # 既存改行を尊重: \\n で分割された各段落を個別に処理
    if '\n' in text:
        paragraphs = text.split('\n')
        return _fill_paragraphs(paragraphs, font_obj, get_width_for_line_idx)

    return _fill_single(text, font_obj, get_width_for_line_idx)


def _fill_single(text: str, font_obj, get_width_for_line_idx):
    """改行なしテキストを貪欲に行へ詰める。"""
    lines = []
    remaining = text
    line_idx = 0

    while remaining:
        avail_w = get_width_for_line_idx(line_idx)
        if avail_w <= 0:
            # 利用可能幅がない行はスキップ
            line_idx += 1
            if line_idx > 50:  # 無限ループ防止
                return lines, False
            continue

        fitted, remaining = fit_text_to_width(remaining, font_obj, avail_w)
        lines.append(fitted)
        line_idx += 1

        if line_idx > 50:  # 安全上限
            return lines, not bool(remaining)

    return lines, True


def _fill_paragraphs(paragraphs: list, font_obj, get_width_for_line_idx):
    """改行で分割された段落リストをそれぞれ1行として詰める。
    段落が利用可能幅を超える場合は折り返す。
    """
    lines = []
    line_idx = 0
    fitted_all = True

    for para in paragraphs:
        if not para:
            lines.append('')
            line_idx += 1
            continue

        remaining = para
        while remaining:
            avail_w = get_width_for_line_idx(line_idx)
            if avail_w <= 0:
                line_idx += 1
                if line_idx > 50:
                    return lines, False
                continue
            fitted, remaining = fit_text_to_width(remaining, font_obj, avail_w)
            lines.append(fitted)
            line_idx += 1
            if remaining:
                fitted_all = False
            if line_idx > 50:
                return lines, False

    return lines, fitted_all


def fit_text_to_width(text: str, font_obj, avail_w: float):
    """text の先頭から avail_w に収まる最大文字列を返す。

    Returns:
        (fitted_text, remaining_text)
        fitted_text が空文字の場合は先頭1文字を強制的に収める（無限ループ防止）。
    """
    if font_obj.measure(text) <= avail_w:
        return text, ''

    # 優先区切り文字での分割を試みる
    best_pos = _find_greedy_break(text, font_obj, avail_w)

    if best_pos <= 0:
        # 区切り文字が見つからない — バイナリサーチで最大文字数を探す
        best_pos = _binary_search_fit(text, font_obj, avail_w)

    if best_pos <= 0:
        # 最低1文字は収める
        best_pos = 1

    fitted = text[:best_pos].rstrip()
    remaining = text[best_pos:].lstrip()
    return fitted, remaining


def _find_greedy_break(text: str, font_obj, avail_w: float) -> int:
    """優先区切り文字で収まる最大位置を探す（文字の直後）。"""
    best_pos = 0
    for i, ch in enumerate(text):
        pos = i + 1
        if font_obj.measure(text[:pos]) > avail_w:
            break
        if ch in _PRIORITY_BREAK_CHARS:
            best_pos = pos
    return best_pos


def _binary_search_fit(text: str, font_obj, avail_w: float) -> int:
    """収まる最大文字数を二分探索で求める。"""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font_obj.measure(text[:mid]) <= avail_w:
            lo = mid
        else:
            hi = mid - 1
    return lo
