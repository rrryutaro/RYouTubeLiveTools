"""
RCommentHub — TTS 投稿者名変換

YouTube の表示名（raw）から読み上げ専用名（tts）を生成する。
表示名は変更しない。読み上げ用ヒューリスティックとして扱う。
"""

import re

# ── 変換ルール設定（定数 — 将来の調整用） ────────────────────────────────────
_SUFFIX_MIN_LEN = 2     # 省略対象サフィックスの最小長
_SUFFIX_MAX_LEN = 6     # 省略対象サフィックスの最大長
_VOWELS         = frozenset("aeiouAEIOU")

_DIGIT_RE       = re.compile(r"\d")

_JAPANESE_RE    = re.compile(
    r"[\u3040-\u30ff"    # ひらがな・カタカナ
    r"\u4e00-\u9fff"     # CJK 統合漢字
    r"\u3400-\u4dbf"     # CJK 拡張 A
    r"\uff00-\uffef]"    # 全角英数・記号
)
_ASCII_ALNUM_RE = re.compile(r"^[A-Za-z0-9]+$")


def make_tts_name(raw_name: str) -> str:
    """
    投稿者表示名から読み上げ用名前を生成する。

    処理順:
      1. 前後空白除去
      2. 先頭 @ を削除
      3. 改行・連続空白を単一空白に正規化
      4-6. 日本語前半 + 短い ASCII サフィックス の場合、サフィックスを除外
      7. 結果が空になった場合は raw_name を返す
    """
    if not raw_name:
        return raw_name

    s = raw_name.strip()

    # 先頭の @ を除去
    if s.startswith("@"):
        s = s[1:]

    # 改行・連続空白を正規化
    s = re.sub(r"[\r\n\t ]+", " ", s).strip()

    # 最後の `-` でサフィックスを判定
    if "-" in s:
        idx    = s.rfind("-")
        prefix = s[:idx]
        suffix = s[idx + 1:]
        if _should_strip_suffix(prefix, suffix):
            s = prefix.strip()

    return s if s else raw_name


def _should_strip_suffix(prefix: str, suffix: str) -> bool:
    """
    suffix を省略すべきか判定。
    以下の条件をすべて満たすとき True を返す:
      - prefix に日本語文字を含む
      - suffix が ASCII 英数字のみ
      - suffix 長が _SUFFIX_MIN_LEN ～ _SUFFIX_MAX_LEN
      - suffix が英単語らしくない（母音なし、または長さ 3 以下）
    """
    if not prefix or not suffix:
        return False

    # prefix に日本語を含む
    if not _JAPANESE_RE.search(prefix):
        return False

    # suffix が ASCII 英数字のみ
    if not _ASCII_ALNUM_RE.match(suffix):
        return False

    # suffix 長チェック
    slen = len(suffix)
    if slen < _SUFFIX_MIN_LEN or slen > _SUFFIX_MAX_LEN:
        return False

    # 英単語らしくないか: 数字混じり、母音なし、または長さ 3 以下
    has_digit = bool(_DIGIT_RE.search(suffix))
    has_vowel = any(c in _VOWELS for c in suffix)
    if has_digit or slen <= 3 or not has_vowel:
        return True

    return False
