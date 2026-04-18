"""
PySide6 プロトタイプ — マクロ再生セッション

読込済み action 列を保持し、1件ずつ取り出すマクロ再生セッション。

責務分離:
  - recorder: 記録する
  - io: JSON へ保存/読込する
  - macro session（本モジュール）: 読込済み action 列を step 管理する
  - MainWindow: 開発確認用にそれらをつなぐ
"""

from __future__ import annotations

from typing import Sequence

from roulette_actions import RouletteAction


class MacroPlaybackSession:
    """読込済み action 列のマクロ再生セッション。

    load() で action 列をセットし、pop_next() で1件ずつ取り出す。
    index 管理は pop_next() の呼び出し時点で進める（取り出し即進行）。
    """

    def __init__(self):
        self._actions: list[RouletteAction] = []
        self._index: int = 0

    def load(self, actions: Sequence[RouletteAction]) -> None:
        """action 列をセットし、index を先頭に戻す。"""
        self._actions = list(actions)
        self._index = 0

    def clear(self) -> None:
        """action 列と index をクリアする。"""
        self._actions.clear()
        self._index = 0

    @property
    def total_count(self) -> int:
        """読込済みの全 action 数を返す。"""
        return len(self._actions)

    @property
    def current_index(self) -> int:
        """現在の index（次に取り出す位置）を返す。"""
        return self._index

    def has_next(self) -> bool:
        """次の action があるかを返す。"""
        return self._index < len(self._actions)

    def remaining_count(self) -> int:
        """残りの action 数を返す。"""
        return max(0, len(self._actions) - self._index)

    def peek_next(self) -> RouletteAction | None:
        """次の action を返す（index は進めない）。"""
        if self._index < len(self._actions):
            return self._actions[self._index]
        return None

    def pop_next(self) -> RouletteAction | None:
        """次の action を返し、index を1つ進める。

        action が無い場合は None を返す。
        """
        if self._index < len(self._actions):
            action = self._actions[self._index]
            self._index += 1
            return action
        return None

    def rewind_one(self) -> None:
        """index を1つ戻す（失敗時のリトライ用）。

        先頭より前には戻らない。
        """
        if self._index > 0:
            self._index -= 1

    def insert_actions(self, actions: Sequence[RouletteAction]) -> None:
        """現在の index 位置に action 列を挿入する。

        分岐マクロ再生で、BranchOnWinner の then/else action 列を
        現在位置に差し込むために使う。
        """
        if actions:
            insert_list = list(actions)
            self._actions[self._index:self._index] = insert_list
