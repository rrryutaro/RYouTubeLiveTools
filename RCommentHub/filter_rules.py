"""
RCommentHub — フィルタルール管理
第1段階: 複数ルールを持てる構造 + 基本的な一致評価
"""

import re
import uuid
from dataclasses import dataclass, field


MATCH_TYPES = ["部分一致", "完全一致", "前方一致", "後方一致", "正規表現"]

_NORMAL_KINDS    = ["textMessageEvent"]
_SC_KINDS        = ["superChatEvent", "superStickerEvent"]


@dataclass
class FilterRule:
    """1件のフィルタルール定義"""
    rule_id:            str  = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name:               str  = ""
    enabled:            bool = True
    match_type:         str  = "部分一致"    # MATCH_TYPES のいずれか
    target_text:        str  = ""
    target_field:       str  = "本文"        # "本文" | "投稿者名"
    # 種別条件（全 True = 全種別対象）
    kind_normal:        bool = True
    kind_superchat:     bool = True
    kind_other:         bool = True
    # 投稿者属性条件（全 False = 属性指定なし）
    role_owner:         bool = False
    role_mod:           bool = False
    role_member:        bool = False
    role_verified:      bool = False
    # ユーザー管理連動
    exclude_blacklist:  bool = False   # ブラック対象を除外
    filter_target_only: bool = False   # フィルタ対象ユーザーのみ

    def to_dict(self) -> dict:
        return {
            "rule_id":            self.rule_id,
            "name":               self.name,
            "enabled":            self.enabled,
            "match_type":         self.match_type,
            "target_text":        self.target_text,
            "target_field":       self.target_field,
            "kind_normal":        self.kind_normal,
            "kind_superchat":     self.kind_superchat,
            "kind_other":         self.kind_other,
            "role_owner":         self.role_owner,
            "role_mod":           self.role_mod,
            "role_member":        self.role_member,
            "role_verified":      self.role_verified,
            "exclude_blacklist":  self.exclude_blacklist,
            "filter_target_only": self.filter_target_only,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FilterRule":
        rule = cls()
        for k, v in d.items():
            if hasattr(rule, k):
                setattr(rule, k, v)
        return rule


def _match_text(pattern: str, text: str, match_type: str) -> bool:
    """テキスト一致判定"""
    if not pattern:
        return True
    try:
        if match_type == "部分一致":
            return pattern in text
        if match_type == "完全一致":
            return pattern == text
        if match_type == "前方一致":
            return text.startswith(pattern)
        if match_type == "後方一致":
            return text.endswith(pattern)
        if match_type == "正規表現":
            return bool(re.search(pattern, text))
    except re.error:
        return False
    return False


class FilterRuleManager:
    """フィルタルールの一覧管理と評価"""

    def __init__(self):
        self._rules: list[FilterRule] = []

    @property
    def rules(self) -> list:
        return list(self._rules)

    def add_rule(self, rule: "FilterRule | None" = None) -> FilterRule:
        if rule is None:
            rule = FilterRule(name=f"ルール {len(self._rules) + 1}")
        self._rules.append(rule)
        return rule

    def remove_rule(self, rule_id: str):
        self._rules = [r for r in self._rules if r.rule_id != rule_id]

    def get_rule(self, rule_id: str) -> "FilterRule | None":
        for r in self._rules:
            if r.rule_id == rule_id:
                return r
        return None

    def move_up(self, rule_id: str):
        idx = next((i for i, r in enumerate(self._rules) if r.rule_id == rule_id), -1)
        if idx > 0:
            self._rules[idx - 1], self._rules[idx] = self._rules[idx], self._rules[idx - 1]

    def move_down(self, rule_id: str):
        idx = next((i for i, r in enumerate(self._rules) if r.rule_id == rule_id), -1)
        if 0 <= idx < len(self._rules) - 1:
            self._rules[idx], self._rules[idx + 1] = self._rules[idx + 1], self._rules[idx]

    def evaluate(self, item, user_manager=None) -> list:
        """コメントに一致したルールの rule_id リストを返す（一致なしは空リスト）"""
        matched = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            if self._rule_matches(rule, item, user_manager):
                matched.append(rule.rule_id)
        return matched

    def _rule_matches(self, rule: FilterRule, item, user_manager) -> bool:
        # ブラックリスト除外
        if rule.exclude_blacklist and user_manager:
            if user_manager.is_blacklisted(item.channel_id):
                return False

        # フィルタ対象ユーザーのみ
        if rule.filter_target_only and user_manager:
            rec = user_manager.get(item.channel_id)
            if rec and not rec.is_filter_target:
                return False

        # 種別条件
        kind = item.kind
        kind_ok = (
            (rule.kind_normal    and kind in _NORMAL_KINDS) or
            (rule.kind_superchat and kind in _SC_KINDS) or
            (rule.kind_other     and kind not in _NORMAL_KINDS and kind not in _SC_KINDS)
        )
        if not kind_ok:
            return False

        # 投稿者属性条件（いずれかが True なら、それを満たす必要あり）
        role_any = rule.role_owner or rule.role_mod or rule.role_member or rule.role_verified
        if role_any:
            role_ok = (
                (rule.role_owner    and getattr(item, "is_owner",     False)) or
                (rule.role_mod      and getattr(item, "is_moderator", False)) or
                (rule.role_member   and getattr(item, "is_member",    False)) or
                (rule.role_verified and getattr(item, "is_verified",  False))
            )
            if not role_ok:
                return False

        # テキスト一致
        if rule.target_text:
            text = (item.author_name if rule.target_field == "投稿者名"
                    else item.body or "")
            if not _match_text(rule.target_text, text, rule.match_type):
                return False

        return True

    def to_list(self) -> list:
        return [r.to_dict() for r in self._rules]

    def from_list(self, data: list):
        self._rules = [FilterRule.from_dict(d) for d in data]
