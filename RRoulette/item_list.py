"""
RRoulette — 項目リスト Mixin
  - _build_listbox: 表示用リストボックスの構築
  - _enter_edit_mode / _save_edit: テキスト編集モード
  - _refresh_pattern_cb / _on_pattern_select: グループ選択
  - _on_cb_return / _on_cb_escape: コンボボックスキーイベント
  - _group_add / _group_delete_silent: グループ追加・削除
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
    _PM_MAP = {"デフォルト": None, "固定%": "fixed", "重み": "weight"}
    _PM_INV = {None: "デフォルト", "fixed": "固定%", "weight": "重み"}

    # ════════════════════════════════════════════════════════════════
    #  項目リスト — 表示モード切り替え
    # ════════════════════════════════════════════════════════════════
    def _build_listbox(self):
        for w in self._lb_frm.winfo_children():
            w.destroy()
        self._check_vars    = []
        self._check_buttons = []
        self._pm_vars       = []   # prob_mode StringVar per item
        self._pm_cbs        = []   # prob_mode Combobox per item
        self._pv_vars       = []   # fixed-prob Entry StringVar per item
        self._pv_entries    = []   # fixed-prob Entry widget per item
        self._pw_vars       = []   # weight Combobox StringVar per item
        self._pw_cbs        = []   # weight Combobox widget per item
        self._sp_vars       = []   # split_count StringVar per item
        self._split_cbs     = []   # split_count Combobox widget per item

        sb = tk.Scrollbar(self._lb_frm)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        cv = tk.Canvas(self._lb_frm, bg="#0f3460",
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

        _LBL_KW = dict(bg="#0f3460", fg="#8899cc", font=("Meiryo", 8))
        _CB_KW  = dict(font=("Meiryo", 8), state="readonly")
        _ENT_KW = dict(
            font=("Meiryo", 8), bg="#1a3a6a", fg=WHITE,
            insertbackground=WHITE, relief=tk.FLAT,
            highlightthickness=1, highlightbackground="#334466",
            highlightcolor=ACCENT,
        )

        for i, entry in enumerate(self._item_entries):
            # ── Outer frame for entire item block ────────────────
            outer = tk.Frame(inner, bg="#0f3460")
            outer.pack(fill=tk.X)

            # ── Row 1: Checkbox + item text ──────────────────────
            row1 = tk.Frame(outer, bg="#0f3460")
            row1.pack(fill=tk.X)

            var = tk.BooleanVar(value=entry.get("enabled", True))
            self._check_vars.append(var)
            cb = tk.Checkbutton(
                row1, variable=var,
                bg="#0f3460", activebackground="#0f3460",
                selectcolor="#1a3a6a", highlightthickness=0,
                relief=tk.FLAT,
                command=lambda idx=i: self._on_item_enabled_change(idx),
            )
            cb.pack(side=tk.LEFT)
            self._check_buttons.append(cb)

            display = entry["text"].replace("\n", "↵")
            if len(display) > 18:
                display = display[:17] + "…"
            lbl = tk.Label(row1, text=display, bg="#0f3460", fg=WHITE,
                           font=("Meiryo", 10), anchor="w")
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # ── Row 2: 確率設定 + 分割設定 ───────────────────────
            row2 = tk.Frame(outer, bg="#0f3460")
            row2.pack(fill=tk.X, padx=(22, 2), pady=(0, 3))

            # 確率モード Combobox
            pm_display = self._PM_INV.get(entry.get("prob_mode"), "デフォルト")
            pm_var = tk.StringVar(value=pm_display)
            self._pm_vars.append(pm_var)
            tk.Label(row2, text="確率:", **_LBL_KW).pack(side=tk.LEFT)
            pm_cb = ttk.Combobox(
                row2, textvariable=pm_var,
                values=list(self._PM_MAP.keys()),
                width=6, **_CB_KW,
            )
            pm_cb.pack(side=tk.LEFT, padx=(0, 4))
            self._pm_cbs.append(pm_cb)

            # 確率値ホルダー（固定% Entry または 重み Combobox を切り替え）
            val_holder = tk.Frame(row2, bg="#0f3460")
            val_holder.pack(side=tk.LEFT, padx=(0, 6))

            # 固定確率 Entry
            pv_init = (
                str(entry["prob_value"])
                if entry.get("prob_mode") == "fixed" and entry.get("prob_value") is not None
                else ""
            )
            pv_var = tk.StringVar(value=pv_init)
            self._pv_vars.append(pv_var)
            pv_ent = tk.Entry(val_holder, textvariable=pv_var, width=5, **_ENT_KW)
            self._pv_entries.append(pv_ent)

            # 重み係数 Combobox
            pw_init = (
                str(entry["prob_value"])
                if entry.get("prob_mode") == "weight" and entry.get("prob_value") is not None
                else "1"
            )
            pw_var = tk.StringVar(value=pw_init)
            self._pw_vars.append(pw_var)
            pw_cb_w = ttk.Combobox(val_holder, textvariable=pw_var, width=4, **_CB_KW)
            self._pw_cbs.append(pw_cb_w)

            # モードに応じて値ウィジェットを表示
            _mode = entry.get("prob_mode")
            if _mode == "fixed":
                pv_ent.pack()
            elif _mode == "weight":
                pw_cb_w["values"] = self._weight_choices()
                pw_cb_w.pack()

            # 分割数 Combobox
            tk.Label(row2, text="分割:", **_LBL_KW).pack(side=tk.LEFT)
            sp_val = str(entry.get("split_count", 1))
            sp_var = tk.StringVar(value=sp_val)
            self._sp_vars.append(sp_var)
            sp_cb_w = ttk.Combobox(
                row2, textvariable=sp_var,
                values=[str(j) for j in range(1, SPLIT_MAX + 1)],
                width=2, **_CB_KW,
            )
            sp_cb_w.pack(side=tk.LEFT)
            self._split_cbs.append(sp_cb_w)

            # イベントバインド
            pm_cb.bind("<<ComboboxSelected>>",
                       lambda e, idx=i: self._on_prob_mode_change(idx))
            pv_ent.bind("<Return>",   lambda e, idx=i: self._on_prob_value_change(idx))
            pv_ent.bind("<FocusOut>", lambda e, idx=i: self._on_prob_value_change(idx))
            pw_cb_w.bind("<<ComboboxSelected>>",
                         lambda e, idx=i: self._on_weight_change(idx))
            sp_cb_w.bind("<<ComboboxSelected>>",
                         lambda e, idx=i: self._on_split_change(idx))

            # スクロール・ダブルクリックバインド
            _scroll_targets = (outer, row1, row2, cb, lbl,
                               pm_cb, val_holder, pv_ent, pw_cb_w, sp_cb_w)
            for w in _scroll_targets:
                w.bind("<MouseWheel>", _on_wheel)
                w.bind("<Double-Button-1>", self._on_lb_double_click)

        cv.bind("<Double-Button-1>", self._on_lb_double_click)

    def _on_item_enabled_change(self, idx: int):
        """チェックボックスのトグル時に enabled を更新してセグメントを再構築する。"""
        if idx < len(self._item_entries) and idx < len(self._check_vars):
            self._item_entries[idx]["enabled"] = self._check_vars[idx].get()
            self._rebuild_segments()
            self._refresh_weight_choices()
            self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  確率設定 / 分割設定 ハンドラ
    # ════════════════════════════════════════════════════════════════
    def _weight_choices(self) -> list:
        """重み係数の選択肢リストを返す（ON item 数に応じて上限を変える）。"""
        n_on = max(1, sum(1 for e in self._item_entries if e.get("enabled", True)))
        below = sorted(str(w) for w in WEIGHT_BELOW_ONE)   # "0.25", "0.5", "0.75"
        above = []
        v = 1.5
        while v <= n_on + 1e-9:
            above.append(str(round(v, 1)))
            v += 0.5
        return below + ["1"] + above

    def _refresh_weight_choices(self):
        """全重み Combobox の選択肢を現在の ON item 数に合わせて更新する。"""
        choices = self._weight_choices()
        for pw_cb_w in getattr(self, "_pw_cbs", []):
            try:
                if pw_cb_w.winfo_exists():
                    pw_cb_w["values"] = choices
            except tk.TclError:
                pass

    def _on_prob_mode_change(self, i: int):
        """確率モード Combobox 変更ハンドラ。"""
        if i >= len(self._item_entries) or i >= len(self._pm_vars):
            return
        entry   = self._item_entries[i]
        mode    = self._PM_MAP.get(self._pm_vars[i].get())
        pv_ent  = self._pv_entries[i]
        pw_cb_w = self._pw_cbs[i]

        # 両方の値ウィジェットをいったん非表示
        pv_ent.pack_forget()
        pw_cb_w.pack_forget()

        if mode == "fixed":
            if entry.get("prob_mode") != "fixed":
                # 他モードから切り替え時は値をリセット
                entry["prob_value"] = None
                self._pv_vars[i].set("")
            pv_ent.pack()
        elif mode == "weight":
            if entry.get("prob_mode") != "weight":
                entry["prob_value"] = 1.0
                self._pw_vars[i].set("1")
            pw_cb_w["values"] = self._weight_choices()
            pw_cb_w.pack()
        else:
            # デフォルト（等確率）
            entry["prob_value"] = None

        entry["prob_mode"] = mode
        self._hide_edit_warning()
        self._rebuild_segments()
        self._redraw()

    def _on_prob_value_change(self, i: int):
        """固定確率 Entry の FocusOut / Return ハンドラ。"""
        if i >= len(self._item_entries) or i >= len(self._pv_vars):
            return
        entry = self._item_entries[i]
        if entry.get("prob_mode") != "fixed":
            return

        raw = self._pv_vars[i].get().strip()
        if not raw:
            entry["prob_value"] = None
            self._hide_edit_warning()
            self._rebuild_segments()
            self._redraw()
            return

        try:
            val = float(raw)
        except ValueError:
            self._show_edit_warning("数値を入力してください（例: 30）")
            self._pv_vars[i].set(
                str(entry["prob_value"]) if entry.get("prob_value") is not None else ""
            )
            return

        if not (0.0 < val < 100.0):
            self._show_edit_warning("0より大きく100未満の値を入力してください")
            self._pv_vars[i].set(
                str(entry["prob_value"]) if entry.get("prob_value") is not None else ""
            )
            return

        # Σ固定確率 の合計チェック（自分以外 かつ enabled のみ。_calc_probs と同条件）
        sum_others = sum(
            (e.get("prob_value") or 0.0)
            for j, e in enumerate(self._item_entries)
            if e.get("prob_mode") == "fixed" and j != i and e.get("enabled", True)
        )
        if sum_others + val >= 100.0:
            self._show_edit_warning(
                f"固定確率の合計が100以上になります（他の固定: {sum_others:.1f}%）"
            )
            self._pv_vars[i].set(
                str(entry["prob_value"]) if entry.get("prob_value") is not None else ""
            )
            return

        self._hide_edit_warning()
        entry["prob_value"] = val
        self._rebuild_segments()
        self._redraw()

    def _on_weight_change(self, i: int):
        """重み係数 Combobox 変更ハンドラ。"""
        if i >= len(self._item_entries) or i >= len(self._pw_vars):
            return
        entry = self._item_entries[i]
        if entry.get("prob_mode") != "weight":
            return
        try:
            val = float(self._pw_vars[i].get())
        except ValueError:
            val = 1.0
            self._pw_vars[i].set("1")
        entry["prob_value"] = val
        self._rebuild_segments()
        self._redraw()

    def _on_split_change(self, i: int):
        """分割数 Combobox 変更ハンドラ。"""
        if i >= len(self._item_entries) or i >= len(self._sp_vars):
            return
        try:
            val = int(self._sp_vars[i].get())
        except ValueError:
            val = 1
        self._item_entries[i]["split_count"] = max(1, min(SPLIT_MAX, val))
        self._rebuild_segments()
        self._redraw()

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

    def _show_edit_warning(self, msg: str):
        """制限超過の警告を表示する。"""
        if hasattr(self, "_edit_warn_lbl"):
            self._edit_warn_lbl.config(text=f"⚠ {msg}")

    def _hide_edit_warning(self):
        """制限超過の警告を消す。"""
        if hasattr(self, "_edit_warn_lbl"):
            self._edit_warn_lbl.config(text="")

    def _preview_items(self):
        """編集中テキストを一時的にパースしてルーレットを再描画する。"""
        self._preview_redraw_id = None
        raw = self._edit_text.get("1.0", tk.END)
        preview = _parse_items(raw)
        if not preview:
            return
        preview, changed, warn = _enforce_limits(preview)
        if changed:
            # テキストウィジェットを制限適用後の内容に更新
            new_text = _serialize_items(preview)
            self._edit_text.delete("1.0", tk.END)
            self._edit_text.insert("1.0", new_text)
            self._show_edit_warning(warn)
        else:
            self._hide_edit_warning()
        # 既存の enabled 状態を維持しながらテキストを更新
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
        items, _, _ = _enforce_limits(items)  # 保存時も制限を保証

        # 既存の enabled 状態を維持しながら新しい ItemEntry リストを構築
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
            # 新しい名前 → 現在グループをリネーム
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

        # 形式チェック: dict[str, list]
        if (not isinstance(data, dict)
                or not all(isinstance(k, str) and isinstance(v, list) for k, v in data.items())):
            _msgbox.showerror(
                "インポートエラー",
                "ファイルの形式が正しくありません。\n"
                "エクスポートで作成したJSONファイルを使用してください。",
                parent=self.root,
            )
            return

        # 旧 list[str] 形式と新 list[dict] 形式の両方に対応
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
        for cb in getattr(self, "_check_buttons", []):
            if cb.winfo_exists():
                cb.config(state=state)
        if hasattr(self, "_edit_text") and self._edit_text.winfo_exists():
            self._edit_text.config(state=state)
        # 確率設定 / 分割設定 コントロール
        for cb in getattr(self, "_pm_cbs", []):
            if cb.winfo_exists():
                cb.config(state=cb_state)
        for ent in getattr(self, "_pv_entries", []):
            if ent.winfo_exists():
                ent.config(state=state)
        for cb in getattr(self, "_pw_cbs", []):
            if cb.winfo_exists():
                cb.config(state=cb_state)
        for cb in getattr(self, "_split_cbs", []):
            if cb.winfo_exists():
                cb.config(state=cb_state)

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
