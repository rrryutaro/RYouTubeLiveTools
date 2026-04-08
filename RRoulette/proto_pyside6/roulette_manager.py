"""
PySide6 プロトタイプ — ルーレットマネージャー

マルチルーレット化のための管理層スケルトン。
複数の RouletteContext を保持し、アクティブなルーレットを追跡する。

現時点では最小定義のみ。MainWindow への本格統合は次段で行う。
"""

from PySide6.QtCore import QObject, Signal

from roulette_context import RouletteContext


class RouletteManager(QObject):
    """ルーレットインスタンスの管理層。

    Signals:
        active_changed(str): アクティブなルーレット ID が変わった
    """

    active_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roulettes: dict[str, RouletteContext] = {}
        self._active_id: str = ""

    # ================================================================
    #  プロパティ
    # ================================================================

    @property
    def active(self) -> RouletteContext | None:
        """現在アクティブな RouletteContext を返す。"""
        return self._roulettes.get(self._active_id)

    @property
    def active_id(self) -> str:
        """現在アクティブなルーレット ID を返す。"""
        return self._active_id

    # ================================================================
    #  操作
    # ================================================================

    def get(self, roulette_id: str) -> RouletteContext | None:
        """指定 ID の RouletteContext を返す。"""
        return self._roulettes.get(roulette_id)

    def register(self, context: RouletteContext) -> None:
        """RouletteContext を登録する。

        同じ ID が既に登録されている場合は上書きする。
        登録後、アクティブが未設定なら自動的にアクティブにする。
        """
        self._roulettes[context.roulette_id] = context
        if not self._active_id:
            self._active_id = context.roulette_id

    def unregister(self, roulette_id: str) -> RouletteContext | None:
        """指定 ID の RouletteContext を登録解除して返す。

        未登録 ID の場合は None を返す。
        アクティブ対象を削除した場合、残る先頭の ID を自動で active にする。
        全て削除された場合は active_id を空にする。
        """
        ctx = self._roulettes.pop(roulette_id, None)
        if ctx is None:
            return None
        if self._active_id == roulette_id:
            if self._roulettes:
                new_id = next(iter(self._roulettes))
                self._active_id = new_id
                self.active_changed.emit(new_id)
            else:
                self._active_id = ""
        return ctx

    @property
    def count(self) -> int:
        """登録されているルーレット数を返す。"""
        return len(self._roulettes)

    def ids(self) -> list[str]:
        """登録順の ID リストを返す。"""
        return list(self._roulettes.keys())

    def next_id(self, current_id: str) -> str | None:
        """current_id の次の ID を返す（循環）。1個以下なら None。"""
        keys = self.ids()
        if len(keys) <= 1:
            return None
        try:
            idx = keys.index(current_id)
        except ValueError:
            return None
        return keys[(idx + 1) % len(keys)]

    def prev_id(self, current_id: str) -> str | None:
        """current_id の前の ID を返す（循環）。1個以下なら None。"""
        keys = self.ids()
        if len(keys) <= 1:
            return None
        try:
            idx = keys.index(current_id)
        except ValueError:
            return None
        return keys[(idx - 1) % len(keys)]

    def set_active(self, roulette_id: str) -> None:
        """アクティブなルーレットを切り替える。

        存在する ID のときだけ更新し、変更時のみ active_changed を発火する。
        """
        if roulette_id not in self._roulettes:
            return
        if roulette_id == self._active_id:
            return
        self._active_id = roulette_id
        self.active_changed.emit(roulette_id)
