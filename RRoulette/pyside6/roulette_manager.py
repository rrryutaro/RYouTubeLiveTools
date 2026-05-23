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
        self._names: dict[str, str] = {}

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

    def get_name(self, roulette_id: str) -> str | None:
        """カスタム表示名を返す。未設定なら None。"""
        return self._names.get(roulette_id)

    def set_name(self, roulette_id: str, name: str) -> None:
        """カスタム表示名を設定する。"""
        self._names[roulette_id] = name

    def unset_name(self, roulette_id: str) -> None:
        """カスタム表示名を削除する（ルーレット削除時）。"""
        self._names.pop(roulette_id, None)

    def move(self, roulette_id: str, direction: int) -> bool:
        """ルーレットの表示順を direction だけ移動する。

        Args:
            roulette_id: 移動対象の ID
            direction: -1 = 前へ（上）, +1 = 次へ（下）

        Returns:
            移動できた場合 True、境界やIDが無効な場合 False。
        """
        keys = list(self._roulettes.keys())
        if roulette_id not in keys:
            return False
        idx = keys.index(roulette_id)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(keys):
            return False
        keys[idx], keys[new_idx] = keys[new_idx], keys[idx]
        self._roulettes = {k: self._roulettes[k] for k in keys}
        return True

    def reorder(self, id_list: list[str]) -> None:
        """指定された ID 順にルーレットを並べ替える。

        id_list に含まれない既存 ID は末尾に残す。
        """
        known = set(self._roulettes.keys())
        ordered = [rid for rid in id_list if rid in known]
        remaining = [rid for rid in self._roulettes if rid not in set(ordered)]
        new_keys = ordered + remaining
        self._roulettes = {k: self._roulettes[k] for k in new_keys}

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
