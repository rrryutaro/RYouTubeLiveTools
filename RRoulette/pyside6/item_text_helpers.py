"""
RRoulette PySide6 — 項目テキスト変換ヘルパー

settings_panel.py から分離した純関数群。
テキストエリアと項目リストの相互変換と上限強制を担う。

由来: v0.4.4 item_list モジュールのロジックを移植し、settings_panel.py に
     取り込まれていたもの。UI に依存しないため独立ファイルに分離した。
"""

from app_constants import ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES
from item_entry import ItemEntry


def match_entries_to_texts(old_entries: list, texts: list[str]) -> list:
    """テキスト編集結果（行リスト）と旧項目リストを対応付けて新しい ItemEntry リストを返す。

    対応付けの規則:
      1. テキスト完全一致（上から順に 1 対 1 で消費）
         → 旧エントリのオブジェクトをそのまま維持（属性・item_id を保持）
      2. 一致しなかった行同士を出現順にペアリングして属性を継承（リネーム扱い）
         → enabled / prob_mode / prob_value / split_count / special_role / item_id
      3. どちらにも該当しない行は初期値（分割なし・確率なし）で新規作成

    従来は「同じ行位置」だけで対応付けていたため、行の削除・挿入・並べ替えで
    分割・確率などの属性が別の項目へ移る不具合があった（例: 中間行を削除すると
    削除した項目の分割数が次の項目へ引き継がれる）。

    Args:
        old_entries: 編集前の ItemEntry リスト
        texts: テキスト編集で得られた項目テキストのリスト

    Returns:
        新しい ItemEntry リスト（texts と同じ順序・件数）
    """
    n_old = len(old_entries)
    consumed = [False] * n_old
    matched: list = [None] * len(texts)

    # パス1: テキスト完全一致（上から順に未消費の旧エントリを消費）
    for j, text in enumerate(texts):
        for i in range(n_old):
            if not consumed[i] and old_entries[i].text == text:
                consumed[i] = True
                matched[j] = old_entries[i]
                break

    # パス2: 残った行同士を出現順にペアリングして属性継承（リネーム扱い）
    leftovers = [old_entries[i] for i in range(n_old) if not consumed[i]]
    li = 0
    result: list = []
    for j, text in enumerate(texts):
        if matched[j] is not None:
            result.append(matched[j])
            continue
        if li < len(leftovers):
            base = leftovers[li]
            li += 1
            result.append(ItemEntry(
                text=text,
                enabled=base.enabled,
                prob_mode=base.prob_mode,
                prob_value=base.prob_value,
                split_count=base.split_count,
                item_id=base.item_id,
                special_role=base.special_role,
            ))
        else:
            result.append(ItemEntry(text=text))
    return result


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


def validate_item_limits(
    items: list[str],
    max_count: int | None = None,
    max_chars: int | None = None,
) -> str:
    """項目数 / 行数 / 文字数の上限を検証し、違反があればエラーメッセージを返す。

    i078: 保存前チェック用。切り捨ては行わない。
    問題なければ空文字列を返す。
    max_count / max_chars を省略した場合は定数のデフォルト値を使う。

    Returns:
        エラーメッセージ文字列。問題なければ "" を返す。
    """
    n_count = max_count if max_count is not None else ITEM_MAX_COUNT
    n_chars = max_chars if max_chars is not None else ITEM_MAX_LINE_CHARS
    errors: list[str] = []
    if len(items) > n_count:
        errors.append(
            f"項目数が上限（{n_count}件）を超えています（現在 {len(items)} 件）。"
            f"\n超過分を削除してから保存してください。"
        )
    for i, item in enumerate(items):
        lines = item.split("\n")
        if len(lines) > ITEM_MAX_LINES:
            label = item[:10] + "…" if len(item) > 10 else item
            errors.append(
                f"項目 {i + 1}「{label}」の行数が上限（{ITEM_MAX_LINES}行）を超えています。"
            )
        for ln in lines:
            if len(ln) > n_chars:
                label = item[:10] + "…" if len(item) > 10 else item
                errors.append(
                    f"項目 {i + 1}「{label}」に {n_chars} 文字を超える行があります"
                    f"（{len(ln)} 文字）。"
                )
                break  # 1 項目につき 1 件のエラーで十分
    if not errors:
        return ""
    return "\n".join(errors)


def enforce_item_limits(
    items: list[str],
    max_count: int | None = None,
    max_chars: int | None = None,
) -> tuple[list[str], bool, str]:
    """項目数 / 行数 / 文字数の上限を強制する。

    max_count / max_chars を省略した場合は定数のデフォルト値を使う。

    Returns: (trimmed_items, was_changed, warn_message)
    （v0.4.4 `item_list._enforce_limits` を移植）
    """
    n_count = max_count if max_count is not None else ITEM_MAX_COUNT
    n_chars = max_chars if max_chars is not None else ITEM_MAX_LINE_CHARS
    warnings: list[str] = []
    changed = False
    if len(items) > n_count:
        items = items[:n_count]
        warnings.append(f"項目数を上限（{n_count}）に制限")
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
            if len(ln) > n_chars:
                new_lines.append(ln[:n_chars])
                warnings.append(f"1行{n_chars}文字に制限")
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
