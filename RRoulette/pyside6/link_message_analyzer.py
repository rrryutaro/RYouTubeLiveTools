"""
link_message_analyzer.py — 連携メッセージ簡易分析 (i109)

RCommentHub から受信したメッセージを spin / ticket_add / unknown に分類し、
チケット名・効果候補を可能な範囲で抽出する。

設計方針:
  - 外部AIやLLMは一切使わない。ローカルのキーワードルールのみ。
  - テスト可能な純粋関数として実装する。
  - 既存のチケット効果種別に対応するものだけ抽出する。
  - 対応する効果種別: none / pointer_move / set_item_enabled /
                      set_weight / set_fixed_prob / add_prob
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 既存チケット効果タイプ (ticket_panel.py の定数と一致させること)
EFFECT_NONE             = "none"
EFFECT_POINTER_MOVE     = "pointer_move"
EFFECT_SET_ITEM_ENABLED = "set_item_enabled"
EFFECT_SET_WEIGHT       = "set_weight"
EFFECT_SET_FIXED_PROB   = "set_fixed_prob"
EFFECT_ADD_PROB         = "add_prob"

# ── キーワード定義 ─────────────────────────────────────────────────────────

# spin 判定キーワード
_SPIN_KEYWORDS = [
    "回して", "回す", "まわして", "まわす",
    "スピン", "spin",
    "抽選", "ルーレット開始", "開始", "スタート", "start",
]

# ticket_add 判定キーワード（強: 単独でticket_add確定）
_TICKET_STRONG_KEYWORDS = ["チケット", "ticket"]

# ticket_add 判定キーワード（弱: spin語が無い場合のみticket_add）
_TICKET_WEAK_KEYWORDS = ["券", "追加", "登録", "作って", "作成"]

# 効果別キーワード
_POINTER_KEYWORDS   = ["ポインター", "pointer", "移動", "ずらす", "角度"]
_HIDE_KEYWORDS      = ["非表示", "消す", "除外", "隠す"]
_WEIGHT_KEYWORDS    = ["倍率", "重み係数", "重み"]
_ADD_PROB_KEYWORDS  = ["追加確率", "上げる", "アップ"]
_FIXED_PROB_KEYWORDS = ["固定確率", "確率を", "にする"]


# ── 解析結果 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedLinkAction:
    """連携メッセージの解析結果。"""
    action_type: str          # "spin" | "ticket_add" | "unknown"
    confidence: float         # 0.0 ~ 1.0
    reason: str               # 判定理由（UI表示用）
    raw_text: str             # 元テキスト
    ticket_name: str | None = None
    ticket_description: str | None = None  # 元メッセージを含む説明文
    effect_type: str = EFFECT_NONE
    effect_params: dict = field(default_factory=dict)
    needs_review: bool = True


# ── 公開API ───────────────────────────────────────────────────────────────

def analyze_link_message(text: str) -> ParsedLinkAction:
    """連携メッセージを解析して ParsedLinkAction を返す。

    Args:
        text: 受信した連携メッセージのテキスト
    Returns:
        ParsedLinkAction (action_type は "spin" / "ticket_add" / "unknown")
    """
    t = text.strip()

    if not t or len(t) < 2:
        return ParsedLinkAction(
            action_type="unknown",
            confidence=0.0,
            reason="テキストが空または短すぎます",
            raw_text=text,
        )

    has_ticket_strong = any(kw in t for kw in _TICKET_STRONG_KEYWORDS)
    has_ticket_strong_lower = any(kw in t.lower() for kw in [k.lower() for k in _TICKET_STRONG_KEYWORDS])
    has_ticket = has_ticket_strong or has_ticket_strong_lower
    has_ticket_weak = any(kw in t for kw in _TICKET_WEAK_KEYWORDS)
    has_spin = any(kw in t.lower() for kw in [k.lower() for k in _SPIN_KEYWORDS])

    # チケット追加を優先（強キーワードがあればspinと同時でも優先）
    if has_ticket:
        return _parse_ticket_add(t, text)

    # 弱キーワード: spinキーワードが無い場合のみticket_add
    if has_ticket_weak and not has_spin:
        return _parse_ticket_add(t, text)

    if has_spin:
        return ParsedLinkAction(
            action_type="spin",
            confidence=0.8,
            reason="スピン系キーワードを検出",
            raw_text=text,
            needs_review=False,
        )

    return ParsedLinkAction(
        action_type="unknown",
        confidence=0.0,
        reason="判定キーワードが見つかりません",
        raw_text=text,
    )


def action_type_label(action_type: str) -> str:
    """action_type の日本語ラベルを返す（UI表示用）。"""
    return {"spin": "spin", "ticket_add": "追加", "unknown": "不明"}.get(action_type, "不明")


# ── 内部処理 ──────────────────────────────────────────────────────────────

def _parse_ticket_add(t: str, raw: str) -> ParsedLinkAction:
    """ticket_add と判定されたメッセージを詳細解析する。"""
    ticket_name = _extract_ticket_name(t)
    effect_type, effect_params, effect_reason = _extract_effect(t)
    needs_review = (effect_type is None or effect_type == EFFECT_NONE)

    desc = f"連携メッセージから作成: {raw}"

    return ParsedLinkAction(
        action_type="ticket_add",
        confidence=0.75 if not needs_review else 0.5,
        reason=f"チケット追加系キーワードを検出。{effect_reason}",
        raw_text=raw,
        ticket_name=ticket_name,
        ticket_description=desc,
        effect_type=effect_type or EFFECT_NONE,
        effect_params=effect_params,
        needs_review=needs_review,
    )


def _extract_ticket_name(t: str) -> str:
    """テキストからチケット名を抽出する。

    優先順:
      1. 鉤括弧・引用符内の文字列
      2. ○○チケット の形
      3. ○○券 の形
      4. フォールバック: "連携チケット"
    """
    # 1. 鉤括弧・引用符
    m = re.search(r'[「『"](.*?)[」』"]', t)
    if m:
        name = m.group(1).strip()
        if name:
            return name

    # 2. ○○チケット
    m = re.search(r'(\S{1,15}チケット)', t)
    if m:
        return m.group(1)

    # 3. ticket (英字)
    m = re.search(r'([\w\s]{1,20}ticket)', t, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # 4. ○○券
    m = re.search(r'(\S{1,15}券)', t)
    if m:
        return m.group(1)

    return "連携チケット"


def _extract_effect(t: str) -> tuple[str | None, dict, str]:
    """効果種別と効果パラメータを抽出する。

    Returns:
        (effect_type, effect_params, reason_text)
        effect_type は None の場合「特定不能」
    """
    # ポインター移動
    # param key: max_move_deg (ticket_panel.py の _read_effect_from_ui に合わせる)
    if any(kw in t for kw in _POINTER_KEYWORDS):
        deg = _extract_float(t, r'(\d+(?:\.\d+)?)\s*[度°]')
        if deg is not None:
            deg = max(0.5, min(180.0, deg))
            return EFFECT_POINTER_MOVE, {"max_move_deg": deg}, f"ポインター移動 {deg}° を抽出"
        return EFFECT_POINTER_MOVE, {"max_move_deg": 15.0}, "ポインター移動（移動量デフォルト15°）"

    # 項目非表示
    # param: なし (使用時選択型)
    if any(kw in t for kw in _HIDE_KEYWORDS):
        return EFFECT_SET_ITEM_ENABLED, {}, "項目非表示効果を検出"

    # 重み係数 (倍率・重み系)
    # param key: weight_value (ticket_panel.py の _read_effect_from_ui に合わせる)
    if any(kw in t for kw in _WEIGHT_KEYWORDS):
        val = _extract_float(t, r'[x×＊\*]\s*(\d+(?:\.\d+)?)')
        if val is None:
            val = _extract_float(t, r'(\d+(?:\.\d+)?)\s*倍')
        if val is not None and 0.25 <= val <= 99.0:
            return EFFECT_SET_WEIGHT, {"weight_value": round(val, 2)}, f"重み係数 ×{val} を抽出"
        return EFFECT_SET_WEIGHT, {"weight_value": 2.0}, "重み係数効果（値デフォルト×2.0）"

    # 追加確率 (add_prob) — fixed_prob より前にチェック
    # param key: prob_value (ticket_panel.py の _read_effect_from_ui に合わせる)
    if any(kw in t for kw in _ADD_PROB_KEYWORDS):
        prob = _extract_float(t, r'[+＋]\s*(\d+(?:\.\d+)?)\s*[%％]')
        if prob is None:
            prob = _extract_float(t, r'(\d+(?:\.\d+)?)\s*[%％]\s*(?:上げ|アップ)')
        if prob is not None and 0.1 <= prob <= 99.9:
            return EFFECT_ADD_PROB, {"prob_value": round(prob, 1)}, f"追加確率 +{prob}% を抽出"

    # 固定確率 (set_fixed_prob)
    # param key: prob_value
    has_fixed = any(kw in t for kw in _FIXED_PROB_KEYWORDS) or "%" in t or "％" in t
    if has_fixed:
        prob = _extract_float(t, r'(\d+(?:\.\d+)?)\s*[%％]')
        if prob is not None and 0.1 <= prob <= 99.9:
            return EFFECT_SET_FIXED_PROB, {"prob_value": round(prob, 1)}, f"固定確率 {prob}% を抽出"

    return None, {}, "効果種別を特定できませんでした（要確認）"


def _extract_float(text: str, pattern: str) -> float | None:
    """正規表現で最初の数値 (float) を抽出する。"""
    m = re.search(pattern, text)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, IndexError):
            pass
    return None
