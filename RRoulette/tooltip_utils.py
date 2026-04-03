"""
RRoulette — 共有ツールチップヘルパー

_SimpleTooltip: ホバー時に簡易ツールチップを表示する。
  root を渡すとルートウィンドウ内の place() で描画（OBS キャプチャ対応）。
  root=None の場合は Toplevel にフォールバック。
"""

import tkinter as tk


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
