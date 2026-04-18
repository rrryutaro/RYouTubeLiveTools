"""
RRoulette PySide6 — 項目テキスト変換ヘルパー

settings_panel.py から分離した純関数群。
テキストエリアと項目リストの相互変換と上限強制を担う。

由来: v0.4.4 item_list モジュールのロジックを移植し、settings_panel.py に
     取り込まれていたもの。UI に依存しないため独立ファイルに分離した。
"""

from bridge import ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES


def serialize_items_text(items: list[str]) -> str:
    """項目リストをテキストエリア用の文字列に変換する。

    改行を含む項目はクォートブロックで囲む。通常項目はそのまま出力。
    （v0.4.4 `item_list._serialize_items` を移植）
    """
    parts = []
    for item in items:
        if "\n" in item:
            content_lines = item.split("\n")
            esc = []
            for ln in content_lines:
                if ln.endswith('"') and not ln.endswith('""'):
                    ln += '"'
                esc.append(ln)
            esc[0] = '"' + esc[0]
            last = esc[-1]
            if last.endswith('"'):
                esc.append('"')
            else:
                esc[-1] += '"'
            parts.append("\n".join(esc))
        else:
            parts.append(item)
    return "\n".join(parts)


def parse_items_text(raw: str) -> list[str]:
    """テキストをパースして項目リストを返す。

    書式:
      - 通常行: 各行が 1 項目
      - クォートブロック: 行頭 `"` で開始 → 行末 `"` で 1 項目に確定
      - `""` エスケープ: ブロック内で行末 `"` を含めたいとき
    （v0.4.4 `item_list._parse_items` を移植）
    """
    items: list[str] = []
    buf: list[str] | None = None

    def _flush_pending():
        if buf:
            items.append('"' + buf[0])
            for ln in buf[1:]:
                if ln.strip():
                    items.append(ln.strip())

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if buf is not None:
            if s == '"':
                item = '\n'.join(buf).strip('\n').replace('""', '"')
                if item:
                    items.append(item)
                buf = None
            elif s[0] == '"':
                _flush_pending()
                rest = s[1:]
                if rest and rest[-1] == '"' and not rest.endswith('""'):
                    item = rest[:-1].replace('""', '"')
                    if item:
                        items.append(item)
                    buf = None
                else:
                    buf = [rest] if rest else []
            elif s[-1] == '"' and not s.endswith('""'):
                buf.append(s[:-1])
                item = '\n'.join(buf).strip('\n').replace('""', '"')
                if item:
                    items.append(item)
                buf = None
            else:
                buf.append(s)
        else:
            if s[0] == '"':
                rest = s[1:]
                if rest and rest[-1] == '"' and not rest.endswith('""'):
                    item = rest[:-1].replace('""', '"')
                    if item:
                        items.append(item)
                elif rest:
                    buf = [rest]
                else:
                    items.append('"')
            else:
                items.append(s)
    _flush_pending()
    return items


def enforce_item_limits(items: list[str]) -> tuple[list[str], bool, str]:
    """項目数 / 行数 / 文字数の上限を強制する。

    Returns: (trimmed_items, was_changed, warn_message)
    （v0.4.4 `item_list._enforce_limits` を移植）
    """
    warnings: list[str] = []
    changed = False
    if len(items) > ITEM_MAX_COUNT:
        items = items[:ITEM_MAX_COUNT]
        warnings.append(f"項目数を上限（{ITEM_MAX_COUNT}）に制限")
        changed = True
    trimmed: list[str] = []
    for item in items:
        lines = item.split("\n")
        if len(lines) > ITEM_MAX_LINES:
            lines = lines[:ITEM_MAX_LINES]
            warnings.append(f"1項目{ITEM_MAX_LINES}行に制限")
            changed = True
        new_lines: list[str] = []
        for ln in lines:
            if len(ln) > ITEM_MAX_LINE_CHARS:
                new_lines.append(ln[:ITEM_MAX_LINE_CHARS])
                warnings.append(f"1行{ITEM_MAX_LINE_CHARS}文字に制限")
                changed = True
            else:
                new_lines.append(ln)
        trimmed.append("\n".join(new_lines))
    seen: set[str] = set()
    unique: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return trimmed, changed, " / ".join(unique)
