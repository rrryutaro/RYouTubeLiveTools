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
)


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

    # ════════════════════════════════════════════════════════════════
    #  項目リスト — 表示モード切り替え
    # ════════════════════════════════════════════════════════════════
    def _build_listbox(self):
        for w in self._lb_frm.winfo_children():
            w.destroy()
        sb = tk.Scrollbar(self._lb_frm)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb = tk.Listbox(
            self._lb_frm, yscrollcommand=sb.set,
            bg="#0f3460", fg=WHITE, selectbackground=ACCENT,
            activestyle="none", font=("Meiryo", 10),
            relief=tk.FLAT, bd=0,
        )
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lb.yview)
        for item in self.items:
            self.lb.insert(tk.END, item)
        self.lb.bind("<Double-Button-1>", self._on_lb_double_click)

    def _on_lb_double_click(self, event):
        """リスト空白部分のダブルクリックで編集モードに入る。"""
        if self._edit_mode:
            return
        size = self.lb.size()
        if size == 0:
            self._enter_edit_mode()
            return
        bbox = self.lb.bbox(size - 1)
        if bbox and event.y > bbox[1] + bbox[3]:
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
        self._edit_text.insert(tk.END, _serialize_items(self.items))
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
        self.items = preview
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
        self.items = items

        pat_name = self._pattern_var.get().strip() or "デフォルト"
        self._item_patterns[pat_name] = list(self.items)
        self._current_pattern = pat_name

        self._pattern_cb.config(values=list(self._item_patterns.keys()))
        self._pattern_var.set(pat_name)

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
            self.items = list(self._item_patterns[val])
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
            self.items = list(self._item_patterns[text])
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
        self.items = []
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
        self._item_patterns = {"デフォルト": ["項目A", "項目B", "項目C", "項目D", "項目E", "項目F"]}
        self._current_pattern = "デフォルト"
        self.items = list(self._item_patterns[self._current_pattern])
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
        self._item_patterns[self._current_pattern] = list(self.items)
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

        # 形式チェック: dict[str, list[str]]
        if (not isinstance(data, dict)
                or not all(isinstance(k, str) and isinstance(v, list) for k, v in data.items())):
            _msgbox.showerror(
                "インポートエラー",
                "ファイルの形式が正しくありません。\n"
                "エクスポートで作成したJSONファイルを使用してください。",
                parent=self.root,
            )
            return

        self._item_patterns = {k: [str(i) for i in v] for k, v in data.items()}
        if not self._item_patterns:
            _msgbox.showwarning("インポート", "グループが1件もありませんでした。", parent=self.root)
            return

        self._current_pattern = next(iter(self._item_patterns))
        self.items = list(self._item_patterns[self._current_pattern])
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
        state = tk.DISABLED if locked else tk.NORMAL
        self._pattern_cb.config(state="disabled" if locked else "normal")
        self._edit_btn.config(state=state)
        self._save_btn.config(state=tk.DISABLED)
        for btn in getattr(self, "_item_list_title_btns", []):
            btn.config(state=state)
        if hasattr(self, "lb") and self.lb.winfo_exists():
            self.lb.config(state=state)
        if hasattr(self, "_edit_text") and self._edit_text.winfo_exists():
            self._edit_text.config(state=state)

    def _group_delete_silent(self):
        """確認ダイアログなしでグループを削除（1つしかない場合は元に戻す）"""
        if len(self._item_patterns) <= 1:
            self._pattern_var.set(self._current_pattern)
            return
        del self._item_patterns[self._current_pattern]
        self._current_pattern = next(iter(self._item_patterns))
        self.items = list(self._item_patterns[self._current_pattern])
        self._refresh_pattern_cb()
        self._build_listbox()
        self._save_config()
        self._redraw()
