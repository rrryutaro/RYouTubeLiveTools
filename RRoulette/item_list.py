"""
RRoulette — 項目リスト Mixin (v0.3.0 UI再設計)
  3ブロック構成:
    上部: クイック操作帯 (_build_quick_bar)
    中央: 項目カード一覧 (_build_card_list)
    下部: 詳細設定カード (_build_detail_card)

  - _build_listbox      : 3ブロック構成の組み立て
  - _enter_edit_mode    : テキスト編集モード
  - _save_edit          : テキスト編集保存
  - _refresh_pattern_cb / _on_pattern_select : グループ選択
  - _on_cb_return / _on_cb_escape            : コンボボックスキーイベント
  - _group_add / _group_delete_silent        : グループ追加・削除
"""

import json
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as _filedialog
import tkinter.messagebox as _msgbox

from config_utils import EXPORT_DIR
from constants import (
    PANEL, ACCENT, DARK2, WHITE, _ADD_SENTINEL,
    ITEM_MAX_COUNT, ITEM_MAX_LINE_CHARS, ITEM_MAX_LINES,
    SPLIT_MAX, WEIGHT_BELOW_ONE,
)


class _SimpleTooltip:
    """ホバー時に簡易ツールチップを表示するヘルパー。

    root を渡すとルートウィンドウ内の place() で描画（OBSキャプチャ対応）。
    root=None の場合は Toplevel にフォールバック。
    """
    _shared: dict = {}  # root → Label（ルートごとに1つ共有ラベル）

    def __init__(self, widget, text: str, root=None):
        self._widget = widget
        self._text = text
        self._root = root
        self._after_id = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')

    def _schedule(self, _=None):
        self._after_id = self._widget.after(350, self._show)

    def _show(self, _=None):
        self._after_id = None
        if self._root is not None:
            lbl = _SimpleTooltip._shared.get(self._root)
            if lbl is None or not lbl.winfo_exists():
                lbl = tk.Label(
                    self._root, bg='#ffffcc', fg='#222222',
                    font=('Meiryo', 8), relief='solid', bd=1, padx=4, pady=2,
                )
                _SimpleTooltip._shared[self._root] = lbl
            rx = self._widget.winfo_rootx() - self._root.winfo_rootx()
            ry = (self._widget.winfo_rooty() - self._root.winfo_rooty()
                  + self._widget.winfo_height() + 2)
            lbl.config(text=self._text)
            lbl.place(x=rx, y=ry)
            lbl.lift()
        else:
            x = self._widget.winfo_rootx() + 4
            y = self._widget.winfo_rooty() + self._widget.winfo_height() + 2
            tip = tk.Toplevel(self._widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f'+{x}+{y}')
            tk.Label(
                tip, text=self._text,
                bg='#ffffcc', fg='#222222',
                font=('Meiryo', 8), relief='solid', bd=1, padx=4, pady=2,
            ).pack()
            self._tip_window = tip

    def _hide(self, _=None):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        if self._root is not None:
            lbl = _SimpleTooltip._shared.get(self._root)
            if lbl and lbl.winfo_exists():
                lbl.place_forget()
        elif hasattr(self, '_tip_window') and self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None


def _make_entry(text):
    """テキストからデフォルト設定の ItemEntry dict を作成する。"""
    return {"text": text, "enabled": True, "prob_mode": None, "prob_value": None, "split_count": 1}


def _enforce_limits(items: list):
    """
    項目リストに制限を適用して強制的にカットする。
    Returns: (trimmed_items, was_changed, warn_message)
    """
    warnings = []
    trimmed = []
    changed = False

    if len(items) > ITEM_MAX_COUNT:
        items = items[:ITEM_MAX_COUNT]
        warnings.append(f"項目数を上限（{ITEM_MAX_COUNT}）に制限")
        changed = True

    for item in items:
        lines = item.split("\n")
        if len(lines) > ITEM_MAX_LINES:
            lines = lines[:ITEM_MAX_LINES]
            warnings.append(f"1項目{ITEM_MAX_LINES}行に制限")
            changed = True
        new_lines = []
        for ln in lines:
            if len(ln) > ITEM_MAX_LINE_CHARS:
                new_lines.append(ln[:ITEM_MAX_LINE_CHARS])
                warnings.append(f"1行{ITEM_MAX_LINE_CHARS}文字に制限")
                changed = True
            else:
                new_lines.append(ln)
        trimmed.append("\n".join(new_lines))

    # 重複メッセージを除去して結合
    seen, unique = set(), []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return trimmed, changed, " / ".join(unique)


def _serialize_items(items: list) -> str:
    """
    項目リストをテキストエリア用の文字列に変換する。
    改行を含む項目はクォートブロックで囲む。通常項目はそのまま出力。
    ブロック内でコンテンツ行が " で終わる場合は誤クローズ防止のため "" にエスケープ。
    閉じ " の付加で末尾が "" になる場合は独立行に閉じ " を置く。
    """
    parts = []
    for item in items:
        if "\n" in item:
            content_lines = item.split("\n")
            esc = []
            for ln in content_lines:
                # 行末 " は誤クローズになるため "" にエスケープ
                if ln.endswith('"') and not ln.endswith('""'):
                    ln += '"'
                esc.append(ln)
            esc[0] = '"' + esc[0]   # 先頭行に開きクォート
            last = esc[-1]
            if last.endswith('"'):
                # 末尾が " で終わっていると閉じ " の付加が判別不能 → 独立行に置く
                esc.append('"')
            else:
                esc[-1] += '"'      # 末尾行に閉じクォート
            parts.append("\n".join(esc))
        else:
            parts.append(item)      # 通常項目はそのまま
    return "\n".join(parts)


def _parse_items(raw: str) -> list:
    """
    テキストをパースして項目リストを返す。

    書式:
      - 通常行: 各行が1項目（そのまま）
      - クォートブロック: 行頭 " で開始 → 後続のいずれかの行末 " で1項目に確定
      - 行頭 " が複数現れた場合: 直前のブロックを破棄して新しいブロックを開始
        （破棄されたブロックの各行は別項目としてそのまま出力）
      - 閉じクォートがない場合: 各行が別項目（行頭の " もそのまま）
      - "" エスケープ: ブロック内で行末の " を含めたいとき（誤クローズ防止）
    """
    items = []
    buf = None  # None=ブロック外、list=ブロック内の蓄積行

    def _flush_pending():
        """未閉じブロックをリテラル行として出力する。"""
        if buf:
            items.append('"' + buf[0])  # 先頭行は " を戻す
            for ln in buf[1:]:
                if ln.strip():
                    items.append(ln.strip())

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue

        if buf is not None:
            # ── ブロック内 ──────────────────────────────────────────
            if s == '"':
                # 単独 " → ブロック閉じ（空の閉じ行）
                item = '\n'.join(buf).strip('\n').replace('""', '"')
                if item:
                    items.append(item)
                buf = None
            elif s[0] == '"':
                # 新しい行頭 " → 旧ブロックを破棄して新規ブロック開始
                _flush_pending()
                rest = s[1:]
                if rest and rest[-1] == '"' and not rest.endswith('""'):
                    # 同一行クローズ: "内容"
                    item = rest[:-1].replace('""', '"')
                    if item:
                        items.append(item)
                    buf = None
                else:
                    buf = [rest] if rest else []
            elif s[-1] == '"' and not s.endswith('""'):
                # 行末 " → ブロック閉じ
                buf.append(s[:-1])
                item = '\n'.join(buf).strip('\n').replace('""', '"')
                if item:
                    items.append(item)
                buf = None
            else:
                buf.append(s)
        else:
            # ── ブロック外 ──────────────────────────────────────────
            if s[0] == '"':
                rest = s[1:]
                if rest and rest[-1] == '"' and not rest.endswith('""'):
                    # 同一行ブロック: "内容"
                    item = rest[:-1].replace('""', '"')
                    if item:
                        items.append(item)
                elif rest:
                    # マルチライン開始
                    buf = [rest]
                else:
                    # 単独 " → リテラル項目
                    items.append('"')
            else:
                items.append(s)

    # 末尾に未閉じブロック → リテラル行として出力
    _flush_pending()
    return items


class ItemListMixin:

    # 確率モード表示名 ↔ 内部値マッピング
    # UI上は「重み」を使わず「倍率」を使用する
    _PM_MAP = {"デフォルト": None, "固定%": "fixed", "倍率": "weight"}
    _PM_INV = {None: "デフォルト", "fixed": "固定%", "weight": "倍率"}

    # ════════════════════════════════════════════════════════════════
    #  項目リスト — 3ブロック構成の組み立て
    # ════════════════════════════════════════════════════════════════
    def _build_listbox(self):
        """_lb_frm を 3ブロック構成で構築する。"""
        for w in self._lb_frm.winfo_children():
            w.destroy()

        # 初回のみデフォルト値を設定（リビルド時は現在の状態を維持）
        if not hasattr(self, '_show_prob'):
            self._show_prob = False
        if not hasattr(self, '_show_wins'):
            self._show_wins = False
        if not hasattr(self, '_selected_item_idx'):
            self._selected_item_idx = None

        # 選択インデックスの範囲チェック
        if (self._selected_item_idx is not None
                and self._selected_item_idx >= len(self._item_entries)):
            self._selected_item_idx = None

        # 上部: クイック操作帯
        self._lb_quick_frm = tk.Frame(self._lb_frm, bg=PANEL)
        self._lb_quick_frm.pack(fill=tk.X, padx=4, pady=(2, 0))
        self._build_quick_bar()

        # 下部: 詳細設定カード（先にpackして残りを中央が埋める）
        self._lb_detail_frm = tk.Frame(self._lb_frm, bg="#0d1f38")
        if not getattr(self, '_detail_collapsed', True):
            self._lb_detail_frm.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(2, 2))
            self._build_detail_card()

        # 中央: 項目カード一覧
        self._lb_cards_frm = tk.Frame(self._lb_frm, bg="#0f3460")
        self._lb_cards_frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 0))
        self._build_card_list()

    # ════════════════════════════════════════════════════════════════
    #  上部: クイック操作帯
    # ════════════════════════════════════════════════════════════════
    def _build_quick_bar(self):
        """上部クイック操作帯を構築する。
        左: 実行ボタン群（⇄ ↺ ⟲） ─ 右: トグルボタン群（↻ % ★ ☰ ▾）
        各ボタンにホバーツールチップ（OBSキャプチャ対応）。
        """
        qb = self._lb_quick_frm

        _BTN_BASE = dict(
            font=("Meiryo", 10),
            relief=tk.FLAT, cursor="hand2", padx=6, pady=3, bd=0,
        )
        _EXEC_KW = dict(**_BTN_BASE, bg=DARK2, fg=WHITE)

        def _tog_kw(on=False):
            return dict(**_BTN_BASE,
                        bg=ACCENT if on else DARK2,
                        fg=WHITE if on else "#778899")

        row = tk.Frame(qb, bg=PANEL)
        row.pack(fill=tk.X, pady=(2, 2))

        # ── 実行ボタン（左側） ─────────────────────────────────────
        self._qs_rand_btn = tk.Button(
            row, text="⇄", command=self._apply_random_arrangement, **_EXEC_KW)
        self._qs_rand_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_rand_btn, "今すぐランダム配置", self.root)

        self._qs_restore_btn = tk.Button(
            row, text="↺", command=self._reset_to_standard_arrangement, **_EXEC_KW)
        self._qs_restore_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_restore_btn, "標準配置に戻す", self.root)

        self._qs_reset_btn = tk.Button(
            row, text="⟲", command=self._reset_all_items_probs, **_EXEC_KW)
        self._qs_reset_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_reset_btn, "一括リセット", self.root)

        # 区切り
        tk.Frame(row, bg="#334455", width=1).pack(side=tk.LEFT, fill=tk.Y, padx=(4, 4))

        # ── トグルボタン（左寄せ続き） ───────────────────────────────
        auto = getattr(self, '_auto_shuffle', False)
        self._qs_auto_btn = tk.Button(
            row, text="↻", command=self._toggle_auto_shuffle, **_tog_kw(auto))
        self._qs_auto_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_auto_btn, "スピン毎ランダム配置", self.root)

        show_prob = getattr(self, '_show_prob', False)
        self._qs_prob_btn = tk.Button(
            row, text="%", command=self._toggle_show_prob, **_tog_kw(show_prob))
        self._qs_prob_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_prob_btn, "確率表示（項目行1列目）", self.root)

        show_wins = getattr(self, '_show_wins', False)
        self._qs_wins_btn = tk.Button(
            row, text="★", command=self._toggle_show_wins, **_tog_kw(show_wins))
        self._qs_wins_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_wins_btn, "当選回数表示（項目行1列目）", self.root)

        card_rows2 = getattr(self, '_card_rows', 1) == 2
        self._qs_card_rows_btn = tk.Button(
            row, text="☰", command=self._toggle_card_rows, **_tog_kw(card_rows2))
        self._qs_card_rows_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_card_rows_btn, "項目 1行 / 2行 切り替え", self.root)

        collapsed = getattr(self, '_detail_collapsed', False)
        self._qs_detail_btn = tk.Button(
            row, text="▾", command=self._toggle_detail_card, **_tog_kw(not collapsed))
        self._qs_detail_btn.pack(side=tk.LEFT, padx=(0, 2))
        _SimpleTooltip(self._qs_detail_btn, "詳細設定カード 表示/非表示", self.root)

        # スピン中ロック対象を収集
        self._qs_lockable_btns = [
            self._qs_rand_btn, self._qs_restore_btn, self._qs_reset_btn,
            self._qs_auto_btn, self._qs_prob_btn, self._qs_wins_btn,
            self._qs_card_rows_btn,
        ]

    def _toggle_card_rows(self):
        """項目カードの1行/2行表示を切り替える。"""
        self._card_rows = 2 if getattr(self, '_card_rows', 1) == 1 else 1
        on = self._card_rows == 2
        if hasattr(self, '_qs_card_rows_btn') and self._qs_card_rows_btn.winfo_exists():
            self._qs_card_rows_btn.config(
                bg=ACCENT if on else DARK2,
                fg=WHITE if on else "#778899",
            )
        self._build_card_list()

    def _toggle_detail_card(self):
        """詳細設定カードの表示/非表示を切り替える。"""
        if getattr(self, '_detail_collapsed', False):
            if getattr(self, '_selected_item_idx', None) is None:
                return  # 未選択時は展開しない
            self._show_detail_card()
        else:
            self._hide_detail_card()
        collapsed = getattr(self, '_detail_collapsed', False)
        if hasattr(self, '_qs_detail_btn') and self._qs_detail_btn.winfo_exists():
            self._qs_detail_btn.config(
                bg=ACCENT if not collapsed else DARK2,
                fg=WHITE if not collapsed else "#778899",
            )

    def _toggle_auto_shuffle(self):
        self._auto_shuffle = not getattr(self, '_auto_shuffle', False)
        on = self._auto_shuffle
        if hasattr(self, '_qs_auto_btn') and self._qs_auto_btn.winfo_exists():
            self._qs_auto_btn.config(
                bg=ACCENT if on else DARK2,
                fg=WHITE if on else "#778899",
            )
        # cfg_panel の変数があれば同期
        if hasattr(self, '_cfg_auto_shuffle_var'):
            self._cfg_auto_shuffle_var.set(self._auto_shuffle)
        if hasattr(self, '_auto_shuffle_hint_lbl'):
            hint = "ON（開始クリック直後に再配置）" if on else ""
            self._auto_shuffle_hint_lbl.config(text=hint)
        self._save_config()

    def _toggle_show_prob(self):
        self._show_prob = not getattr(self, '_show_prob', False)
        on = self._show_prob
        if hasattr(self, '_qs_prob_btn') and self._qs_prob_btn.winfo_exists():
            self._qs_prob_btn.config(
                bg=ACCENT if on else DARK2,
                fg=WHITE if on else "#778899",
            )
        # カードの確率ラベルだけ更新（全再構築不要）
        self._refresh_prob_labels()

    def _toggle_show_wins(self):
        self._show_wins = not getattr(self, '_show_wins', False)
        on = self._show_wins
        if hasattr(self, '_qs_wins_btn') and self._qs_wins_btn.winfo_exists():
            self._qs_wins_btn.config(
                bg=ACCENT if on else DARK2,
                fg=WHITE if on else "#778899",
            )
        # カードの当選ラベルだけ更新（全再構築不要）
        self._refresh_wins_labels()

    def _reset_all_items_probs(self):
        """一括リセット: 全項目の確率・分割設定をデフォルトに戻す。"""
        if getattr(self, '_confirm_reset', True):
            if not _msgbox.askyesno(
                "一括リセット",
                "全項目の確率・分割設定をデフォルトに戻します。\n"
                "（項目名・有効/無効は変わりません）\nよろしいですか？",
                parent=self.root,
            ):
                return
        for entry in self._item_entries:
            entry["prob_mode"] = None
            entry["prob_value"] = None
            entry["split_count"] = 1
        self._rebuild_segments()
        self._refresh_all_cards()
        if getattr(self, '_show_prob', False):
            self._refresh_prob_labels()
        self._build_detail_card()
        self._save_config()
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  中央: 項目カード一覧
    # ════════════════════════════════════════════════════════════════
    def _calc_all_probs(self) -> list:
        """全項目の現在確率 (%) を計算して返す。無効項目は None。"""
        enabled = [(e, i) for i, e in enumerate(self._item_entries) if e.get("enabled", True)]
        if not enabled:
            return [None] * len(self._item_entries)

        enabled_entries = [e for e, _ in enabled]
        orig_indices    = [i for _, i in enabled]
        n = len(enabled_entries)

        fixed_idx    = [j for j, e in enumerate(enabled_entries) if e.get("prob_mode") == "fixed"]
        nonfixed_idx = [j for j, e in enumerate(enabled_entries) if e.get("prob_mode") != "fixed"]

        sum_fixed = sum(enabled_entries[j].get("prob_value") or 0.0 for j in fixed_idx)
        sum_fixed = min(sum_fixed, 99.999)
        remaining = 100.0 - sum_fixed

        weights = []
        for j in nonfixed_idx:
            e = enabled_entries[j]
            if e.get("prob_mode") == "weight" and e.get("prob_value") is not None:
                weights.append(max(0.0001, float(e["prob_value"])))
            else:
                weights.append(1.0)
        total_w = sum(weights) or 1.0

        probs_enabled = [0.0] * n
        for j in fixed_idx:
            probs_enabled[j] = float(enabled_entries[j].get("prob_value") or 0.0)
        for k, j in enumerate(nonfixed_idx):
            probs_enabled[j] = remaining * weights[k] / total_w

        probs_all = [None] * len(self._item_entries)
        for j, orig_i in enumerate(orig_indices):
            probs_all[orig_i] = probs_enabled[j]
        return probs_all

    def _get_win_counts(self) -> dict:
        """当選回数をキャッシュ付きで返す。履歴が増えたときのみ再集計する。"""
        hist_len = len(getattr(self, '_history', []))
        if (not hasattr(self, '_win_counts_cache')
                or self._win_counts_cache_len != hist_len):
            counts = {}
            for record in getattr(self, '_history', []):
                result = record.get("result", "")
                counts[result] = counts.get(result, 0) + 1
            self._win_counts_cache = counts
            self._win_counts_cache_len = hist_len
        return self._win_counts_cache

    # ────────────────────────────────────────────────────────────────
    #  カード部分更新ヘルパー
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def _card_bg(enabled: bool, selected: bool) -> str:
        if selected:
            return "#1e3a5f"
        return "#0f3460" if enabled else "#0a1e35"

    @staticmethod
    def _chip_text(entry: dict) -> str:
        mode  = entry.get("prob_mode")
        val   = entry.get("prob_value")
        split = entry.get("split_count", 1)
        if mode == "fixed":
            txt = f"固定 {val:.0f}%" if val is not None else "固定%"
        elif mode == "weight":
            txt = f"倍率 ×{val}" if val is not None else "倍率"
        else:
            txt = "標準"
        if split and split > 1:
            txt += f"  分割{split}"
        return txt

    def _update_info_row_visibility(self, refs: dict):
        """2行モードで info_row が pack されていることを保証する。
        1行モード（info_row=None）では何もしない。
        chip_lbl が常に可視のため info_row は常に表示する。
        """
        if refs.get('info_row') is None:
            return  # 1行モード: prob/wins は row1 内で管理
        if not refs.get('_info_row_packed', False):
            refs['info_row'].pack(fill=tk.X, padx=(26, 4), pady=(0, 2))
            refs['_info_row_packed'] = True

    def _refresh_single_card(self, idx: int):
        """単一カードの色・チップテキストを enabled / selected 状態に合わせて更新する。"""
        if not hasattr(self, '_card_refs') or idx >= len(self._card_refs):
            return
        refs  = self._card_refs[idx]
        entry = self._item_entries[idx]
        enabled  = entry.get("enabled", True)
        selected = (getattr(self, '_selected_item_idx', None) == idx)
        bg = self._card_bg(enabled, selected)

        refs['card'].config(bg=bg)
        refs['row1'].config(bg=bg)
        refs['toggle_btn'].config(
            text="●" if enabled else "○",
            bg=ACCENT if enabled else DARK2,
            fg=WHITE if enabled else "#556677",
        )
        refs['name_lbl'].config(bg=bg, fg=WHITE if enabled else "#4a5e70")
        refs['chip_lbl'].config(
            bg=bg,
            fg="#7788aa" if enabled else "#3a4a55",
            text=self._chip_text(entry),
        )
        if refs.get('info_row') is not None:
            refs['info_row'].config(bg=bg)
        refs['prob_lbl'].config(bg=bg)
        refs['wins_lbl'].config(bg=bg)

    def _refresh_all_cards(self):
        """全カードの色・チップテキストを更新する（スクロール構造は維持）。"""
        if not hasattr(self, '_card_refs'):
            return
        for i in range(len(self._card_refs)):
            self._refresh_single_card(i)

    def _refresh_prob_labels(self):
        """確率ラベルのテキストと表示状態を更新する（カード再構築なし）。"""
        if not hasattr(self, '_card_refs'):
            return
        show  = getattr(self, '_show_prob', False)
        probs = self._calc_all_probs() if show else None
        for i, refs in enumerate(self._card_refs):
            if refs.get('info_row') is None:
                # 1行モード: row1の右側パッキングを全体で再調整
                self._repack_row1_right(refs, i)
            else:
                # 2行モード: 固定順で再パック
                self._repack_info_row(refs, i)

    def _refresh_wins_labels(self):
        """当選ラベルのテキストと表示状態を更新する（カード再構築なし）。"""
        if not hasattr(self, '_card_refs'):
            return
        show = getattr(self, '_show_wins', False)
        wins = self._get_win_counts() if show else None
        for i, refs in enumerate(self._card_refs):
            if refs.get('info_row') is None:
                # 1行モード: row1の右側パッキングを全体で再調整
                self._repack_row1_right(refs, i)
            else:
                # 2行モード: 固定順で再パック
                self._repack_info_row(refs, i)

    def _repack_row1_right(self, refs: dict, idx: int):
        """1行モードで row1 右側ラベル（prob/wins/chip）を正しい順序で再パックする。
        pack順: chip(RIGHT, 右端) → wins(RIGHT) → prob(RIGHT)
        視覚順: [prob%] [wins★] [chip]
        """
        show_prob = getattr(self, '_show_prob', False)
        show_wins = getattr(self, '_show_wins', False)
        probs = self._calc_all_probs() if show_prob else None
        wins  = self._get_win_counts()  if show_wins else None

        # 一度全てを外してから再配置
        refs['chip_lbl'].pack_forget()
        refs['wins_lbl'].pack_forget()
        refs['prob_lbl'].pack_forget()

        refs['chip_lbl'].pack(side=tk.RIGHT, padx=(2, 0))
        if show_wins and wins is not None:
            count = wins.get(self._item_entries[idx]["text"], 0)
            refs['wins_lbl'].config(text=f"当選 {count}回")
            refs['wins_lbl'].pack(side=tk.RIGHT, padx=(0, 2))
        if show_prob and probs and idx < len(probs) and probs[idx] is not None:
            refs['prob_lbl'].config(text=f"{probs[idx]:.1f}%")
            refs['prob_lbl'].pack(side=tk.RIGHT, padx=(0, 2))

    def _repack_info_row(self, refs: dict, idx: int):
        """2行モードで info_row 内ラベル（chip/prob/wins）を固定順で再パックする。
        pack順（視覚左→右）: chip → prob → wins
        """
        show_prob = getattr(self, '_show_prob', False)
        show_wins = getattr(self, '_show_wins', False)
        probs = self._calc_all_probs() if show_prob else None
        wins  = self._get_win_counts()  if show_wins else None

        # 一度全て外してから固定順で再配置
        refs['chip_lbl'].pack_forget()
        refs['prob_lbl'].pack_forget()
        refs['wins_lbl'].pack_forget()

        refs['chip_lbl'].pack(side=tk.LEFT)
        if show_prob and probs and idx < len(probs) and probs[idx] is not None:
            refs['prob_lbl'].config(text=f"{probs[idx]:.1f}%")
            refs['prob_lbl'].pack(side=tk.LEFT, padx=(4, 0))
        if show_wins and wins is not None:
            count = wins.get(self._item_entries[idx]["text"], 0)
            refs['wins_lbl'].config(text=f"当選 {count}回")
            refs['wins_lbl'].pack(side=tk.LEFT, padx=(4, 0))
        # info_row は常に表示（chip_lbl が常に可視）
        self._update_info_row_visibility(refs)

    def _build_card_list(self):
        """中央の項目カード一覧を全再構築する（グループ切替・編集保存後などに使用）。"""
        if not hasattr(self, '_lb_cards_frm') or not self._lb_cards_frm.winfo_exists():
            return

        for w in self._lb_cards_frm.winfo_children():
            w.destroy()

        sb = tk.Scrollbar(self._lb_cards_frm)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        cv = tk.Canvas(self._lb_cards_frm, bg="#0f3460",
                       yscrollcommand=sb.set, highlightthickness=0)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=cv.yview)
        self._lb_canvas = cv

        inner  = tk.Frame(cv, bg="#0f3460")
        win_id = cv.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner(e):
            cv.configure(scrollregion=cv.bbox("all"))

        def _on_cv(e):
            cv.itemconfig(win_id, width=e.width)

        inner.bind("<Configure>", _on_inner)
        cv.bind("<Configure>", _on_cv)

        def _on_wheel(e):
            cv.yview_scroll(int(-1 * (e.delta / 120)), "units")

        cv.bind("<MouseWheel>", _on_wheel)

        # 初回構築時のみ確率・当選回数を計算
        show_prob = getattr(self, '_show_prob', False)
        show_wins = getattr(self, '_show_wins', False)
        probs = self._calc_all_probs() if show_prob else None
        wins  = self._get_win_counts()  if show_wins else None

        self._card_toggle_btns = []
        self._card_refs = []  # 部分更新用ウィジェット参照リスト

        two_row = getattr(self, '_card_rows', 1) == 2

        for i, entry in enumerate(self._item_entries):
            enabled  = entry.get("enabled", True)
            selected = (getattr(self, '_selected_item_idx', None) == i)

            card_bg = self._card_bg(enabled, selected)

            card = tk.Frame(inner, bg=card_bg, pady=2)
            card.pack(fill=tk.X, padx=3, pady=(2, 0))

            # 行1: トグル + 項目名 + [確率/当選] + 要約チップ
            row1 = tk.Frame(card, bg=card_bg)
            row1.pack(fill=tk.X, padx=4)

            tog_btn = tk.Button(
                row1,
                text="●" if enabled else "○",
                command=lambda idx=i: self._on_item_toggle(idx),
                bg=ACCENT if enabled else DARK2,
                fg=WHITE if enabled else "#556677",
                font=("Meiryo", 10), relief=tk.FLAT, cursor="hand2",
                padx=3, pady=1, bd=0,
            )
            tog_btn.pack(side=tk.LEFT, padx=(0, 4))
            self._card_toggle_btns.append(tog_btn)

            display = entry["text"].replace("\n", "↵")
            if len(display) > 16:
                display = display[:15] + "…"
            name_lbl = tk.Label(
                row1, text=display,
                bg=card_bg, fg=WHITE if enabled else "#4a5e70",
                font=("Meiryo", 10), anchor="w",
            )
            name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            if two_row:
                # 2行モード: chip・確率・当選を info_row (行2) に固定順で表示
                # 視覚上: [設定] [prob%] [wins★]
                info_row = tk.Frame(card, bg=card_bg)
                chip_lbl = tk.Label(
                    info_row, text=self._chip_text(entry),
                    bg=card_bg, fg="#7788aa" if enabled else "#3a4a55",
                    font=("Meiryo", 8),
                )
                prob_lbl = tk.Label(info_row, text="", bg=card_bg, fg="#6699cc", font=("Meiryo", 8))
                wins_lbl = tk.Label(info_row, text="", bg=card_bg, fg="#9977bb", font=("Meiryo", 8))

                chip_lbl.pack(side=tk.LEFT)
                if show_prob and probs and probs[i] is not None:
                    prob_lbl.config(text=f"{probs[i]:.1f}%")
                    prob_lbl.pack(side=tk.LEFT, padx=(4, 0))
                if show_wins and wins is not None:
                    wins_lbl.config(text=f"当選 {wins.get(entry['text'], 0)}回")
                    wins_lbl.pack(side=tk.LEFT, padx=(4, 0))
                # info_row は chip_lbl が常に表示されるため常にpack
                info_row.pack(fill=tk.X, padx=(26, 4), pady=(0, 2))
                info_row_packed = True
            else:
                # 1行モード: chip・確率・当選を行1の右側に配置
                # pack order: chip(RIGHT) → wins(RIGHT) → prob(RIGHT)
                # 視覚上: [tog][name...expand][prob%][wins★][chip]
                chip_lbl = tk.Label(
                    row1, text=self._chip_text(entry),
                    bg=card_bg, fg="#7788aa" if enabled else "#3a4a55",
                    font=("Meiryo", 8),
                )
                chip_lbl.pack(side=tk.RIGHT, padx=(2, 0))
                prob_lbl = tk.Label(row1, text="", bg=card_bg, fg="#6699cc", font=("Meiryo", 8))
                wins_lbl = tk.Label(row1, text="", bg=card_bg, fg="#9977bb", font=("Meiryo", 8))
                info_row = None
                info_row_packed = False

                # 右側パッキング順（chipより左に積む）
                if show_wins and wins is not None:
                    wins_lbl.config(text=f"当選 {wins.get(entry['text'], 0)}回")
                    wins_lbl.pack(side=tk.RIGHT, padx=(0, 2))
                if show_prob and probs and probs[i] is not None:
                    prob_lbl.config(text=f"{probs[i]:.1f}%")
                    prob_lbl.pack(side=tk.RIGHT, padx=(0, 2))

            # ウィジェット参照を保存
            refs = {
                'card':    card,
                'row1':    row1,
                'toggle_btn': tog_btn,
                'name_lbl':   name_lbl,
                'chip_lbl':   chip_lbl,
                'info_row':   info_row,
                'prob_lbl':   prob_lbl,
                'wins_lbl':   wins_lbl,
                '_info_row_packed': info_row_packed,
            }
            self._card_refs.append(refs)

            # イベントバインド
            def _bind_card(w):
                w.bind("<MouseWheel>", _on_wheel)
                w.bind("<Button-1>", lambda e, idx=i: self._select_item(idx))
                w.bind("<Double-Button-1>", self._on_lb_double_click)

            for w in [card, row1, name_lbl, chip_lbl, info_row, prob_lbl, wins_lbl]:
                if w is not None:
                    _bind_card(w)

        cv.bind("<Double-Button-1>", self._on_lb_double_click)

    def _on_item_toggle(self, idx: int):
        """ON/OFF トグルクリック時に enabled を更新する（部分更新）。
        ① カード視覚反映を即座に実行（~3ms）
        ② 重いホイール再計算（~420ms）は50msデバウンスで後回しにする
        """
        if idx >= len(self._item_entries):
            return
        self._item_entries[idx]["enabled"] = not self._item_entries[idx].get("enabled", True)
        # ① 即時フィードバック（_item_entries から直接計算できるもの）
        self._refresh_single_card(idx)
        if getattr(self, '_show_prob', False):
            self._refresh_prob_labels()
        sel = getattr(self, '_selected_item_idx', None)
        if sel == idx:
            self._build_detail_card()
        elif sel is not None and sel < len(self._item_entries):
            if self._item_entries[sel].get("prob_mode") == "weight":
                self._refresh_weight_choices()
        # ② ホイール再計算・再描画をデバウンスで遅延実行
        self._schedule_wheel_update()

    def _schedule_wheel_update(self):
        """ホイール再計算を50msデバウンスで後回しにする。連続操作は統合する。"""
        if getattr(self, '_wheel_update_id', None) is not None:
            self.root.after_cancel(self._wheel_update_id)
        self._wheel_update_id = self.root.after(50, self._do_wheel_update)

    def _do_wheel_update(self):
        """デバウンス後にホイール再計算・再描画を実行する。"""
        self._wheel_update_id = None
        self._rebuild_segments()
        self._redraw()

    def _select_item(self, idx: int):
        """カードをクリックして詳細設定カードに表示する（部分更新）。"""
        old_idx = getattr(self, '_selected_item_idx', None)
        self._selected_item_idx = idx
        # 前の選択カードと新しい選択カードの色だけ更新
        if old_idx is not None and old_idx != idx:
            self._refresh_single_card(old_idx)
        self._refresh_single_card(idx)
        # 折りたたまれていたら選択操作で自動再表示
        if getattr(self, '_detail_collapsed', False):
            self._show_detail_card()
        else:
            self._build_detail_card()

    def _hide_detail_card(self):
        """詳細設定カードを折りたたむ（即時非表示）。"""
        self._detail_collapsed = True
        if hasattr(self, '_lb_detail_frm') and self._lb_detail_frm.winfo_exists():
            self._lb_detail_frm.pack_forget()

    def _show_detail_card(self):
        """折りたたまれた詳細設定カードを再表示する。"""
        self._detail_collapsed = False
        if hasattr(self, '_lb_detail_frm') and self._lb_detail_frm.winfo_exists():
            self._lb_detail_frm.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(2, 2))
        self._build_detail_card()

    # ════════════════════════════════════════════════════════════════
    #  下部: 詳細設定カード
    # ════════════════════════════════════════════════════════════════
    def _build_detail_card(self):
        """下部の詳細設定カードを構築する。"""
        if not hasattr(self, '_lb_detail_frm') or not self._lb_detail_frm.winfo_exists():
            return

        for w in self._lb_detail_frm.winfo_children():
            w.destroy()
        self._detail_lockable_widgets = []

        idx = getattr(self, '_selected_item_idx', None)
        if idx is None or idx >= len(self._item_entries):
            return

        entry   = self._item_entries[idx]
        card_bg = "#0d1f38"

        # 項目名ヘッダー（折りたたみボタン付き）
        header_row = tk.Frame(self._lb_detail_frm, bg=card_bg)
        header_row.pack(fill=tk.X, padx=4, pady=(4, 2))
        display = entry["text"].replace("\n", "↵")
        if len(display) > 20:
            display = display[:19] + "…"
        tk.Label(
            header_row, text=display,
            bg=card_bg, fg=WHITE,
            font=("Meiryo", 10, "bold"), anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        tk.Button(
            header_row, text="✕",
            command=self._hide_detail_card,
            bg=card_bg, fg="#556677",
            font=("Meiryo", 8),
            relief=tk.FLAT, cursor="hand2", bd=0, padx=4, pady=1,
        ).pack(side=tk.RIGHT)

        _LBL_KW = dict(bg=card_bg, fg="#8899cc", font=("Meiryo", 8))
        _CB_KW  = dict(font=("Meiryo", 8), state="readonly")
        _ENT_KW = dict(
            font=("Meiryo", 8), bg="#1a3a6a", fg=WHITE,
            insertbackground=WHITE, relief=tk.FLAT,
            highlightthickness=1, highlightbackground="#334466",
            highlightcolor=ACCENT,
        )

        # 抽選方式 Combobox
        mode_row = tk.Frame(self._lb_detail_frm, bg=card_bg)
        mode_row.pack(fill=tk.X, padx=8, pady=(0, 2))
        tk.Label(mode_row, text="抽選方式:", **_LBL_KW).pack(side=tk.LEFT)

        pm_display = self._PM_INV.get(entry.get("prob_mode"), "デフォルト")
        self._detail_pm_var = tk.StringVar(value=pm_display)
        pm_cb = ttk.Combobox(
            mode_row, textvariable=self._detail_pm_var,
            values=list(self._PM_MAP.keys()),
            width=8, **_CB_KW,
        )
        pm_cb.pack(side=tk.LEFT, padx=(4, 0))
        pm_cb.bind("<<ComboboxSelected>>", lambda e: self._on_detail_prob_mode_change())
        self._detail_lockable_widgets.append(pm_cb)

        # 値入力フレーム（モードに応じて切り替え）
        self._detail_val_frm = tk.Frame(self._lb_detail_frm, bg=card_bg)
        self._detail_val_frm.pack(fill=tk.X, padx=8, pady=(0, 2))
        self._build_detail_value_row(entry)

        # 分割数 Combobox
        split_row = tk.Frame(self._lb_detail_frm, bg=card_bg)
        split_row.pack(fill=tk.X, padx=8, pady=(0, 2))
        tk.Label(split_row, text="分割数:", **_LBL_KW).pack(side=tk.LEFT)
        sp_var = str(entry.get("split_count", 1))
        self._detail_sp_var = tk.StringVar(value=sp_var)
        sp_cb = ttk.Combobox(
            split_row, textvariable=self._detail_sp_var,
            values=[str(j) for j in range(1, SPLIT_MAX + 1)],
            width=3, **_CB_KW,
        )
        sp_cb.pack(side=tk.LEFT, padx=(4, 0))
        sp_cb.bind("<<ComboboxSelected>>", lambda e: self._on_detail_split_change())
        self._detail_lockable_widgets.append(sp_cb)

        # 補助説明
        mode = entry.get("prob_mode")
        if mode == "weight":
            help_txt = "1が標準です。0.5で半分、2で2倍です。"
        elif mode == "fixed":
            help_txt = "0より大きく100未満の数値で固定（例: 30）"
        else:
            help_txt = "有効な項目で均等に確率を分配します"
        self._detail_help_lbl = tk.Label(
            self._lb_detail_frm, text=help_txt,
            bg=card_bg, fg="#556677",
            font=("Meiryo", 7), anchor="w", wraplength=180,
        )
        self._detail_help_lbl.pack(fill=tk.X, padx=8, pady=(0, 2))

        # 個別リセットボタン
        btn_row = tk.Frame(self._lb_detail_frm, bg=card_bg)
        btn_row.pack(fill=tk.X, padx=8, pady=(2, 5))
        rst_btn = tk.Button(
            btn_row, text="個別リセット",
            command=self._reset_selected_item,
            bg=DARK2, fg=WHITE, font=("Meiryo", 8),
            relief=tk.FLAT, cursor="hand2", padx=6, pady=2,
        )
        rst_btn.pack(side=tk.RIGHT)
        self._detail_lockable_widgets.append(rst_btn)

    def _build_detail_value_row(self, entry):
        """詳細設定カードの値入力ウィジェットを構築/更新する。"""
        for w in self._detail_val_frm.winfo_children():
            w.destroy()

        card_bg = "#0d1f38"
        _LBL_KW = dict(bg=card_bg, fg="#8899cc", font=("Meiryo", 8))
        _ENT_KW = dict(
            font=("Meiryo", 8), bg="#1a3a6a", fg=WHITE,
            insertbackground=WHITE, relief=tk.FLAT,
            highlightthickness=1, highlightbackground="#334466",
            highlightcolor=ACCENT,
        )
        _CB_KW = dict(font=("Meiryo", 8), state="readonly")

        mode = entry.get("prob_mode")
        val  = entry.get("prob_value")

        if mode == "fixed":
            tk.Label(self._detail_val_frm, text="固定確率%:", **_LBL_KW).pack(side=tk.LEFT)
            pv_init = str(val) if val is not None else ""
            self._detail_pv_var = tk.StringVar(value=pv_init)
            pv_ent = tk.Entry(
                self._detail_val_frm, textvariable=self._detail_pv_var,
                width=6, **_ENT_KW,
            )
            pv_ent.pack(side=tk.LEFT, padx=(4, 0))
            pv_ent.bind("<Return>",   lambda e: self._on_detail_prob_value_change())
            pv_ent.bind("<FocusOut>", lambda e: self._on_detail_prob_value_change())
            self._detail_lockable_widgets.append(pv_ent)

        elif mode == "weight":
            tk.Label(self._detail_val_frm, text="当たりやすさ倍率:", **_LBL_KW).pack(side=tk.LEFT)
            pw_init = str(val) if val is not None else "1"
            self._detail_pw_var = tk.StringVar(value=pw_init)
            pw_cb = ttk.Combobox(
                self._detail_val_frm, textvariable=self._detail_pw_var,
                values=self._weight_choices(), width=4, **_CB_KW,
            )
            pw_cb.pack(side=tk.LEFT, padx=(4, 0))
            pw_cb.bind("<<ComboboxSelected>>", lambda e: self._on_detail_weight_change())
            self._detail_lockable_widgets.append(pw_cb)

    def _on_detail_prob_mode_change(self):
        """詳細カードの抽選方式変更ハンドラ。"""
        idx = getattr(self, '_selected_item_idx', None)
        if idx is None or idx >= len(self._item_entries):
            return
        entry = self._item_entries[idx]
        new_mode = self._PM_MAP.get(self._detail_pm_var.get())

        if new_mode == "fixed" and entry.get("prob_mode") != "fixed":
            entry["prob_value"] = None
        elif new_mode == "weight" and entry.get("prob_mode") != "weight":
            entry["prob_value"] = 1.0
        elif new_mode is None:
            entry["prob_value"] = None

        entry["prob_mode"] = new_mode
        self._build_detail_value_row(entry)
        self._update_detail_help_text(entry)
        self._rebuild_segments()
        self._refresh_single_card(idx)
        if getattr(self, '_show_prob', False):
            self._refresh_prob_labels()
        self._redraw()

    def _update_detail_help_text(self, entry):
        """詳細カードの補助説明ラベルを更新する。"""
        if not hasattr(self, '_detail_help_lbl'):
            return
        mode = entry.get("prob_mode")
        if mode == "weight":
            help_txt = "1が標準です。0.5で半分、2で2倍です。"
        elif mode == "fixed":
            help_txt = "0より大きく100未満の数値で固定（例: 30）"
        else:
            help_txt = "有効な項目で均等に確率を分配します"
        self._detail_help_lbl.config(text=help_txt)

    def _on_detail_prob_value_change(self):
        """詳細カードの固定確率 Entry 変更ハンドラ。"""
        idx = getattr(self, '_selected_item_idx', None)
        if idx is None or idx >= len(self._item_entries):
            return
        entry = self._item_entries[idx]
        if entry.get("prob_mode") != "fixed":
            return

        raw = self._detail_pv_var.get().strip()
        if not raw:
            entry["prob_value"] = None
            self._hide_edit_warning()
            self._rebuild_segments()
            self._refresh_single_card(idx)
            if getattr(self, '_show_prob', False):
                self._refresh_prob_labels()
            self._redraw()
            return

        try:
            val = float(raw)
        except ValueError:
            self._show_edit_warning("数値を入力してください（例: 30）")
            self._detail_pv_var.set(
                str(entry["prob_value"]) if entry.get("prob_value") is not None else ""
            )
            return

        if not (0.0 < val < 100.0):
            self._show_edit_warning("0より大きく100未満の値を入力してください")
            self._detail_pv_var.set(
                str(entry["prob_value"]) if entry.get("prob_value") is not None else ""
            )
            return

        sum_others = sum(
            (e.get("prob_value") or 0.0)
            for j, e in enumerate(self._item_entries)
            if e.get("prob_mode") == "fixed" and j != idx and e.get("enabled", True)
        )
        if sum_others + val >= 100.0:
            self._show_edit_warning(
                f"固定確率の合計が100以上になります（他の固定: {sum_others:.1f}%）"
            )
            self._detail_pv_var.set(
                str(entry["prob_value"]) if entry.get("prob_value") is not None else ""
            )
            return

        self._hide_edit_warning()
        entry["prob_value"] = val
        self._rebuild_segments()
        self._refresh_single_card(idx)
        if getattr(self, '_show_prob', False):
            self._refresh_prob_labels()
        self._redraw()

    def _on_detail_weight_change(self):
        """詳細カードの倍率 Combobox 変更ハンドラ。"""
        idx = getattr(self, '_selected_item_idx', None)
        if idx is None or idx >= len(self._item_entries):
            return
        entry = self._item_entries[idx]
        try:
            val = float(self._detail_pw_var.get())
        except ValueError:
            val = 1.0
            self._detail_pw_var.set("1")
        entry["prob_value"] = val
        self._rebuild_segments()
        self._refresh_single_card(idx)
        if getattr(self, '_show_prob', False):
            self._refresh_prob_labels()
        self._redraw()

    def _on_detail_split_change(self):
        """詳細カードの分割数 Combobox 変更ハンドラ。"""
        idx = getattr(self, '_selected_item_idx', None)
        if idx is None or idx >= len(self._item_entries):
            return
        entry = self._item_entries[idx]
        try:
            val = int(self._detail_sp_var.get())
        except ValueError:
            val = 1
        entry["split_count"] = max(1, min(SPLIT_MAX, val))
        self._rebuild_segments()
        self._refresh_single_card(idx)
        self._redraw()

    def _reset_selected_item(self):
        """個別リセット: 選択中項目の確率・分割設定をデフォルトに戻す。"""
        idx = getattr(self, '_selected_item_idx', None)
        if idx is None or idx >= len(self._item_entries):
            return
        entry = self._item_entries[idx]
        entry["prob_mode"]  = None
        entry["prob_value"] = None
        entry["split_count"] = 1
        self._rebuild_segments()
        self._refresh_single_card(idx)
        if getattr(self, '_show_prob', False):
            self._refresh_prob_labels()
        self._build_detail_card()
        self._save_config()
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  確率設定共通ヘルパー
    # ════════════════════════════════════════════════════════════════
    def _weight_choices(self) -> list:
        """倍率係数の選択肢リストを返す（ON 項目数に応じて上限を変える）。"""
        n_on = max(1, sum(1 for e in self._item_entries if e.get("enabled", True)))
        below = sorted(str(w) for w in WEIGHT_BELOW_ONE)   # "0.25", "0.5", "0.75"
        above = []
        v = 1.5
        while v <= n_on + 1e-9:
            above.append(str(round(v, 1)))
            v += 0.5
        return below + ["1"] + above

    def _refresh_weight_choices(self):
        """詳細カードの倍率 Combobox の選択肢を現在の ON 項目数に合わせて更新する。"""
        if not hasattr(self, '_detail_val_frm'):
            return
        choices = self._weight_choices()
        for w in self._detail_val_frm.winfo_children():
            if isinstance(w, ttk.Combobox):
                try:
                    if w.winfo_exists():
                        w["values"] = choices
                except tk.TclError:
                    pass

    def _show_edit_warning(self, msg: str):
        """制限超過の警告を表示する。"""
        if hasattr(self, "_edit_warn_lbl"):
            self._edit_warn_lbl.config(text=f"⚠ {msg}")
            self._edit_warn_lbl.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 2))

    def _hide_edit_warning(self):
        """制限超過の警告を消す。"""
        if hasattr(self, "_edit_warn_lbl"):
            self._edit_warn_lbl.pack_forget()

    # ════════════════════════════════════════════════════════════════
    #  テキスト編集モード
    # ════════════════════════════════════════════════════════════════
    def _on_lb_double_click(self, event):
        """ダブルクリックで編集モードに入る。"""
        if self._edit_mode:
            return
        self._enter_edit_mode()

    def _on_edit_focus_out(self, _event=None):
        """テキストボックスからフォーカスが外れたら自動保存する。"""
        if self._edit_mode:
            self._save_edit()

    def _enter_edit_mode(self):
        for w in self._lb_frm.winfo_children():
            w.destroy()
        sb = tk.Scrollbar(self._lb_frm)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._edit_text = tk.Text(
            self._lb_frm, yscrollcommand=sb.set,
            bg="#0f3460", fg=WHITE, insertbackground=WHITE,
            font=("Meiryo", 10), relief=tk.FLAT, bd=0,
            wrap=tk.NONE, undo=True,
        )
        self._edit_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self._edit_text.yview)
        self._edit_text.insert(tk.END, _serialize_items([e["text"] for e in self._item_entries]))
        self._edit_text.edit_reset()   # 初期挿入をundo履歴から除外
        self._edit_text.bind("<FocusOut>", self._on_edit_focus_out)
        self._edit_text.bind("<KeyRelease>", self._on_edit_key)
        self._edit_btn.config(state=tk.DISABLED)
        self._save_btn.config(state=tk.NORMAL)
        self._edit_mode = True
        self._preview_redraw_id = None

    def _on_edit_key(self, _event=None):
        """編集中のキー入力に合わせてルーレットをプレビュー更新する（デバウンス150ms）。"""
        if self._preview_redraw_id is not None:
            self.root.after_cancel(self._preview_redraw_id)
        self._preview_redraw_id = self.root.after(150, self._preview_items)

    def _preview_items(self):
        """編集中テキストを一時的にパースしてルーレットを再描画する。"""
        self._preview_redraw_id = None
        raw = self._edit_text.get("1.0", tk.END)
        preview = _parse_items(raw)
        if not preview:
            return
        preview, changed, warn = _enforce_limits(preview)
        if changed:
            new_text = _serialize_items(preview)
            self._edit_text.delete("1.0", tk.END)
            self._edit_text.insert("1.0", new_text)
            self._show_edit_warning(warn)
        else:
            self._hide_edit_warning()
        old_entries = self._item_entries
        new_entries = []
        for j, text in enumerate(preview):
            if j < len(old_entries) and old_entries[j]["text"] == text:
                new_entries.append(old_entries[j])
            else:
                entry = _make_entry(text)
                if j < len(old_entries):
                    entry["enabled"] = old_entries[j].get("enabled", True)
                new_entries.append(entry)
        self._item_entries = new_entries
        self._rebuild_segments()
        self._redraw()

    def _save_edit(self):
        if not self._edit_mode:
            return
        if self._preview_redraw_id is not None:
            self.root.after_cancel(self._preview_redraw_id)
            self._preview_redraw_id = None
        raw = self._edit_text.get("1.0", tk.END)
        items = _parse_items(raw)
        items, _, _ = _enforce_limits(items)

        old_entries = self._item_entries
        new_entries = []
        for j, text in enumerate(items):
            if j < len(old_entries) and old_entries[j]["text"] == text:
                new_entries.append(old_entries[j])
            else:
                entry = _make_entry(text)
                if j < len(old_entries):
                    entry["enabled"] = old_entries[j].get("enabled", True)
                new_entries.append(entry)
        self._item_entries = new_entries

        pat_name = self._pattern_var.get().strip() or "デフォルト"
        self._item_patterns[pat_name] = list(self._item_entries)
        self._current_pattern = pat_name

        self._pattern_cb.config(values=list(self._item_patterns.keys()))
        self._pattern_var.set(pat_name)

        self._rebuild_segments()
        self._build_listbox()
        self._edit_btn.config(state=tk.NORMAL)
        self._save_btn.config(state=tk.DISABLED)
        self._edit_mode = False
        self._hide_edit_warning()
        self._save_config()
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  グループ管理（ダイアログ不使用・コンボボックス内で完結）
    # ════════════════════════════════════════════════════════════════
    def _refresh_pattern_cb(self):
        self._pattern_cb.config(
            values=list(self._item_patterns.keys()) + [_ADD_SENTINEL]
        )
        self._pattern_var.set(self._current_pattern)

    def _on_pattern_select(self, _event=None):
        val = self._pattern_var.get()
        if val == _ADD_SENTINEL:
            self._group_add()
            return
        if val in self._item_patterns:
            self._current_pattern = val
            self._item_entries = list(self._item_patterns[val])
            self._rebuild_segments()
            self._build_listbox()
            self._redraw()

    def _on_cb_return(self, _event=None):
        """Enter キー: 空白→削除 / 既存名→切替 / 新名→リネーム"""
        text = self._pattern_var.get().strip()
        old  = self._current_pattern
        if text == "" or text == _ADD_SENTINEL:
            self._group_delete_silent()
        elif text == old:
            pass
        elif text in self._item_patterns:
            self._current_pattern = text
            self._item_entries = list(self._item_patterns[text])
            self._rebuild_segments()
            self._build_listbox()
            self._redraw()
        else:
            self._item_patterns = {
                (text if k == old else k): v
                for k, v in self._item_patterns.items()
            }
            self._current_pattern = text
            self._refresh_pattern_cb()
            self._save_config()
        self.root.focus_set()
        return "break"

    def _on_cb_escape(self, _event=None):
        """Escape キー: 編集キャンセルして元の名前に戻す"""
        self._pattern_var.set(self._current_pattern)
        self.root.focus_set()
        return "break"

    def _group_add(self):
        """センチネル選択時: 連番で新規グループを作成しコンボボックスにフォーカス"""
        base, i, name = "新規グループ", 2, "新規グループ"
        while name in self._item_patterns:
            name = f"{base} {i}"; i += 1
        self._item_patterns[name] = []
        self._current_pattern = name
        self._item_entries = []
        self._rebuild_segments()
        self._refresh_pattern_cb()
        self._build_listbox()
        self._save_config()
        self._redraw()
        self._pattern_cb.focus_set()
        self._pattern_cb.select_range(0, tk.END)

    # ════════════════════════════════════════════════════════════════
    #  項目リスト リセット
    # ════════════════════════════════════════════════════════════════
    def _reset_item_patterns(self):
        """全グループ・項目をデフォルト状態に戻す。"""
        if not _msgbox.askyesno(
            "項目リストをリセット",
            "全グループ・項目をデフォルトに戻します。\nよろしいですか？",
            parent=self.root,
        ):
            return
        _default_texts = ["項目A", "項目B", "項目C", "項目D", "項目E", "項目F"]
        self._item_patterns = {"デフォルト": [_make_entry(t) for t in _default_texts]}
        self._current_pattern = "デフォルト"
        self._item_entries = list(self._item_patterns[self._current_pattern])
        self._rebuild_segments()
        self._refresh_pattern_cb()
        self._build_listbox()
        self._save_config()
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  項目リスト インポート / エクスポート
    # ════════════════════════════════════════════════════════════════
    def _export_item_patterns(self):
        """現在の全グループ・項目をJSONファイルに書き出す。"""
        path = _filedialog.asksaveasfilename(
            parent=self.root,
            title="項目リストをエクスポート",
            initialdir=EXPORT_DIR,
            initialfile="roulette_items.json",
            defaultextension=".json",
            filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        self._item_patterns[self._current_pattern] = list(self._item_entries)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._item_patterns, f, ensure_ascii=False, indent=2)
            _msgbox.showinfo("エクスポート完了", f"保存しました:\n{path}", parent=self.root)
        except Exception as ex:
            _msgbox.showerror("エクスポートエラー", str(ex), parent=self.root)

    def _import_item_patterns(self):
        """JSONファイルから全グループ・項目を読み込み、既存リストを上書きする。"""
        path = _filedialog.askopenfilename(
            parent=self.root,
            title="項目リストをインポート",
            initialdir=EXPORT_DIR,
            defaultextension=".json",
            filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as ex:
            _msgbox.showerror("インポートエラー", f"ファイルを読み込めませんでした:\n{ex}", parent=self.root)
            return

        if (not isinstance(data, dict)
                or not all(isinstance(k, str) and isinstance(v, list) for k, v in data.items())):
            _msgbox.showerror(
                "インポートエラー",
                "ファイルの形式が正しくありません。\n"
                "エクスポートで作成したJSONファイルを使用してください。",
                parent=self.root,
            )
            return

        converted = {}
        for k, v in data.items():
            if not v:
                converted[k] = []
            elif isinstance(v[0], str):
                converted[k] = [_make_entry(s) for s in v]
            elif isinstance(v[0], dict) and "text" in v[0]:
                converted[k] = [dict(e) for e in v]
            else:
                converted[k] = []
        self._item_patterns = converted

        if not self._item_patterns:
            _msgbox.showwarning("インポート", "グループが1件もありませんでした。", parent=self.root)
            return

        self._current_pattern = next(iter(self._item_patterns))
        self._item_entries = list(self._item_patterns[self._current_pattern])
        self._rebuild_segments()
        self._refresh_pattern_cb()
        self._build_listbox()
        self._save_config()
        self._redraw()
        _msgbox.showinfo(
            "インポート完了",
            f"{len(self._item_patterns)} グループを読み込みました。",
            parent=self.root,
        )

    # ════════════════════════════════════════════════════════════════
    #  スピン中 UI ロック
    # ════════════════════════════════════════════════════════════════
    def set_item_spin_lock(self, locked: bool):
        """スピン中は項目リストパネルのすべての操作ウィジェットを無効化する。"""
        state    = tk.DISABLED if locked else tk.NORMAL
        cb_state = "disabled" if locked else "readonly"

        self._pattern_cb.config(state="disabled" if locked else "normal")
        self._edit_btn.config(state=state)
        self._save_btn.config(state=tk.DISABLED)

        for btn in getattr(self, "_item_list_title_btns", []):
            btn.config(state=state)

        # クイック操作帯ボタン
        for btn in getattr(self, "_qs_lockable_btns", []):
            try:
                if btn.winfo_exists():
                    btn.config(state=state)
            except tk.TclError:
                pass

        # カードトグルボタン
        for btn in getattr(self, "_card_toggle_btns", []):
            try:
                if btn.winfo_exists():
                    btn.config(state=state)
            except tk.TclError:
                pass

        # 詳細設定カードウィジェット
        for w in getattr(self, "_detail_lockable_widgets", []):
            try:
                if not w.winfo_exists():
                    continue
                if isinstance(w, ttk.Combobox):
                    w.config(state=cb_state)
                else:
                    w.config(state=state)
            except tk.TclError:
                pass

        # テキスト編集中の場合
        if hasattr(self, "_edit_text") and self._edit_text.winfo_exists():
            self._edit_text.config(state=state)

    def _group_delete_silent(self):
        """確認ダイアログなしでグループを削除（1つしかない場合は元に戻す）"""
        if len(self._item_patterns) <= 1:
            self._pattern_var.set(self._current_pattern)
            return
        del self._item_patterns[self._current_pattern]
        self._current_pattern = next(iter(self._item_patterns))
        self._item_entries = list(self._item_patterns[self._current_pattern])
        self._rebuild_segments()
        self._refresh_pattern_cb()
        self._build_listbox()
        self._save_config()
        self._redraw()
