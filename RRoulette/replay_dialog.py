"""
RRoulette — リプレイ管理ウィンドウ

独立した Toplevel で保存済みリプレイの一覧表示・再生・名称変更・
保持切替・削除・import/export を行う。
位置・サイズは config に保存し、再オープン時に復元する。

一覧は tk.Canvas + Frame 行で描画し、OS テーマに依存しないデザインとする。
"""

import tkinter as tk
import tkinter.messagebox as _msgbox
import tkinter.filedialog as _filedialog
import tkinter.simpledialog as _simpledialog

from config_utils import EXPORT_DIR, _is_on_any_monitor, _parse_geometry


_MIN_W, _MIN_H = 520, 300
_ROW_H = 26          # 行の高さ
_COL_KEEP_W = 36     # 保持列幅
_COL_CREATED_W = 140  # 作成日時列幅
_COL_WINNER_W = 90   # 結果列幅


class ReplayDialog(tk.Toplevel):
    """リプレイ管理画面（独立ウィンドウ）。"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._selected: int = -1   # 選択インデックス
        self._row_frames: list = []

        # ── 独立ウィンドウ設定 ─────────────────────────────────────
        self.title(app._float_win_title("リプレイ管理"))
        self.configure(bg=app._design.panel)
        self.resizable(True, True)
        self.attributes("-topmost", app._topmost)
        self.minsize(_MIN_W, _MIN_H)

        self._restore_geometry()
        self._build_ui()
        self._refresh_list()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ════════════════════════════════════════════════════════════════
    #  ジオメトリ保存・復元
    # ════════════════════════════════════════════════════════════════
    def _restore_geometry(self):
        geo = getattr(self.app, "_replay_dialog_geo", None)
        if geo:
            try:
                parsed = _parse_geometry(geo)
                if (parsed
                        and parsed[0] >= _MIN_W and parsed[1] >= _MIN_H
                        and _is_on_any_monitor(parsed[2], parsed[3], parsed[0], parsed[1])):
                    self.geometry(geo)
                    return
            except Exception:
                pass
        self.geometry(f"{_MIN_W + 60}x{_MIN_H + 80}")

    def _save_geometry(self):
        try:
            self.app._replay_dialog_geo = self.geometry()
        except Exception:
            pass

    def _on_close(self):
        self._save_geometry()
        self.app._replay_dialog_win = None
        self.destroy()

    # ════════════════════════════════════════════════════════════════
    #  UI 構築
    # ════════════════════════════════════════════════════════════════
    def _build_ui(self):
        d = self.app._design
        bg = d.panel
        fg = d.text
        gold = d.gold
        sep = d.separator

        _FONT = ("Meiryo", 9)
        _FONT_H = ("Meiryo", 9, "bold")
        _BTN = dict(bg=sep, fg=fg, font=_FONT,
                    activebackground=d.accent, activeforeground=fg,
                    relief=tk.FLAT, bd=1, padx=6, pady=2)

        # ── ヘッダー行 ───────────────────────────────────────────
        hdr = tk.Frame(self, bg=sep, height=24)
        hdr.pack(fill=tk.X, padx=8, pady=(8, 0))
        hdr.pack_propagate(False)

        tk.Label(hdr, text="保持", bg=sep, fg=gold, font=_FONT_H,
                 width=4, anchor="center").pack(side=tk.LEFT, padx=(2, 0))
        tk.Label(hdr, text="名前", bg=sep, fg=gold, font=_FONT_H,
                 anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        tk.Label(hdr, text="作成日時", bg=sep, fg=gold, font=_FONT_H,
                 width=18, anchor="w").pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(hdr, text="結果", bg=sep, fg=gold, font=_FONT_H,
                 width=10, anchor="w").pack(side=tk.LEFT, padx=(4, 4))

        # ── スクロール可能な一覧エリア ────────────────────────────
        list_outer = tk.Frame(self, bg=bg)
        list_outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self._canvas = tk.Canvas(list_outer, bg=bg, highlightthickness=0, bd=0)
        self._sb = tk.Scrollbar(list_outer, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._list_frame = tk.Frame(self._canvas, bg=bg)
        self._canvas_win = self._canvas.create_window((0, 0), window=self._list_frame, anchor="nw")

        self._list_frame.bind("<Configure>", self._on_list_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # マウスホイールスクロール
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._list_frame.bind("<MouseWheel>", self._on_mousewheel)

        # ── ボタン行 ──────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=bg)
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        tk.Button(btn_frame, text="▶ 再生", command=self._on_play, **_BTN).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(btn_frame, text="名前変更", command=self._on_rename, **_BTN).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(btn_frame, text="保持", command=self._on_toggle_keep, **_BTN).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(btn_frame, text="削除", command=self._on_delete, **_BTN).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(btn_frame, text="↑ エクスポート", command=self._on_export, **_BTN).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(btn_frame, text="↓ インポート", command=self._on_import, **_BTN).pack(side=tk.LEFT, padx=(0, 3))

    def _on_list_configure(self, event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event=None):
        self._canvas.itemconfig(self._canvas_win, width=event.width)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    # ════════════════════════════════════════════════════════════════
    #  一覧更新
    # ════════════════════════════════════════════════════════════════
    def _refresh_list(self, select_idx: int | None = None):
        """一覧を再構築する。"""
        # 旧行を破棄
        for w in self._row_frames:
            w.destroy()
        self._row_frames.clear()

        d = self.app._design
        bg = d.panel
        fg = d.text
        gold = d.gold
        sep = d.separator
        accent = d.accent
        _FONT = ("Meiryo", 9)

        if select_idx is not None:
            self._selected = select_idx

        for i, rec in enumerate(self.app._replay_records):
            is_sel = (i == self._selected)
            row_bg = accent if is_sel else (sep if i % 2 == 1 else bg)
            row_fg = fg

            row = tk.Frame(self._list_frame, bg=row_bg, height=_ROW_H)
            row.pack(fill=tk.X, pady=(0, 1))
            row.pack_propagate(False)

            # 保持
            keep_text = "★" if rec.get("keep") else ""
            lbl_keep = tk.Label(row, text=keep_text, bg=row_bg, fg=gold,
                                font=_FONT, width=4, anchor="center")
            lbl_keep.pack(side=tk.LEFT, padx=(2, 0))

            # 名前
            name = rec.get("name", f"リプレイ {i+1}")
            lbl_name = tk.Label(row, text=name, bg=row_bg, fg=row_fg,
                                font=_FONT, anchor="w")
            lbl_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

            # 作成日時
            created = rec.get("created_at", "")
            if created:
                try:
                    created = created[:19].replace("T", " ")
                except Exception:
                    pass
            lbl_created = tk.Label(row, text=created, bg=row_bg, fg=row_fg,
                                   font=_FONT, width=18, anchor="w")
            lbl_created.pack(side=tk.LEFT, padx=(4, 0))

            # 結果
            winner = ""
            result = rec.get("result")
            if result:
                winner = result.get("winner", "")
            lbl_winner = tk.Label(row, text=winner, bg=row_bg, fg=row_fg,
                                   font=_FONT, width=10, anchor="w")
            lbl_winner.pack(side=tk.LEFT, padx=(4, 4))

            # クリックで選択
            idx = i
            for widget in (row, lbl_keep, lbl_name, lbl_created, lbl_winner):
                widget.bind("<Button-1>", lambda e, ii=idx: self._select_row(ii))
                widget.bind("<Double-Button-1>", lambda e, ii=idx: self._dbl_click_row(ii))
                widget.bind("<MouseWheel>", self._on_mousewheel)

            self._row_frames.append(row)

        # スクロール領域更新
        self._list_frame.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

        # 選択行が見えるようにスクロール
        if 0 <= self._selected < len(self._row_frames):
            self._canvas.update_idletasks()
            row_w = self._row_frames[self._selected]
            y_top = row_w.winfo_y()
            y_bot = y_top + row_w.winfo_height()
            canvas_h = self._canvas.winfo_height()
            total_h = self._list_frame.winfo_reqheight()
            if total_h > canvas_h:
                frac = max(0.0, (y_top - 4) / total_h)
                self._canvas.yview_moveto(frac)

    def _select_row(self, idx: int):
        if self._selected == idx:
            return
        self._selected = idx
        self._refresh_list()

    def _dbl_click_row(self, idx: int):
        self._selected = idx
        self.app._replay_play(idx)

    def _selected_idx(self) -> int | None:
        if self._selected < 0 or self._selected >= len(self.app._replay_records):
            _msgbox.showinfo("リプレイ管理", "リプレイを選択してください。", parent=self)
            return None
        return self._selected

    # ════════════════════════════════════════════════════════════════
    #  操作ハンドラ
    # ════════════════════════════════════════════════════════════════
    def _on_play(self):
        idx = self._selected_idx()
        if idx is None:
            return
        self.app._replay_play(idx)

    def _on_rename(self):
        idx = self._selected_idx()
        if idx is None:
            return
        current = self.app._replay_records[idx].get("name", "")
        new_name = _simpledialog.askstring(
            "名前変更", "新しい名前を入力してください:",
            initialvalue=current, parent=self,
        )
        if new_name is not None and new_name.strip():
            self.app._replay_rename(idx, new_name.strip())
            self._refresh_list()

    def _on_toggle_keep(self):
        idx = self._selected_idx()
        if idx is None:
            return
        rec = self.app._replay_records[idx]
        rec["keep"] = not rec.get("keep", False)
        self.app._replay_save()
        self._refresh_list()

    def _on_delete(self):
        idx = self._selected_idx()
        if idx is None:
            return
        name = self.app._replay_records[idx].get("name", f"リプレイ {idx+1}")
        keep = self.app._replay_records[idx].get("keep", False)
        msg = f"「{name}」を削除しますか？"
        if keep:
            msg += "\n（保持指定されています）"
        if not _msgbox.askyesno("削除確認", msg, parent=self):
            return
        self.app._replay_delete(idx)
        new_sel = min(self._selected, len(self.app._replay_records) - 1)
        self._selected = new_sel
        self._refresh_list()

    def _on_export(self):
        idx = self._selected_idx()
        if idx is None:
            return
        name = self.app._replay_records[idx].get("name", "replay")
        safe_name = "".join(c for c in name if c not in r'\/:*?"<>|')[:50] or "replay"
        path = _filedialog.asksaveasfilename(
            parent=self,
            title="リプレイをエクスポート",
            initialdir=EXPORT_DIR,
            initialfile=f"{safe_name}.json",
            defaultextension=".json",
            filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        if self.app._replay_export(idx, path):
            _msgbox.showinfo("エクスポート完了", f"保存しました:\n{path}", parent=self)
        else:
            _msgbox.showerror("エクスポートエラー", "書き出しに失敗しました。", parent=self)

    def _on_import(self):
        path = _filedialog.askopenfilename(
            parent=self,
            title="リプレイをインポート",
            initialdir=EXPORT_DIR,
            defaultextension=".json",
            filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        err = self.app._replay_import(path)
        if err:
            _msgbox.showerror("インポートエラー", err, parent=self)
        else:
            _msgbox.showinfo("インポート完了", "リプレイを読み込みました。", parent=self)
            self._selected = 0
            self._refresh_list()
