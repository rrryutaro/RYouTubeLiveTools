"""
PySide6 プロトタイプ — アクション記録バッファ

apply_action() 境界で成功したアクションをメモリ内に蓄積する最小 recorder。

保持形式: action object（RouletteAction）のまま保持する。
理由:
  - メモリ内で完結する段階では、dict 変換のオーバーヘッドが不要
  - snapshot 時に codec で dict 化すれば JSON 保存へつなげられる
  - 実行用に戻す変換も不要（そのまま apply_action() へ渡せる）

将来の保存/再生への接続:
  - 保存時: snapshot() → codec.action_to_dict() で dict リスト化 → JSON 出力
  - 再生時: JSON 読込 → codec.action_from_dict() → apply_action() へ順次投入
"""

from __future__ import annotations

from roulette_actions import RouletteAction


class ActionRecorder:
    """メモリ内アクション記録バッファ。

    recording ON の間に record() されたアクションを蓄積する。
    OFF の間は record() を無視する。
    """

    def __init__(self):
        self._recording: bool = False
        self._buffer: list[RouletteAction] = []

    @property
    def is_recording(self) -> bool:
        """現在 recording 中かどうかを返す。"""
        return self._recording

    @property
    def count(self) -> int:
        """記録済みアクション数を返す。"""
        return len(self._buffer)

    def start(self) -> None:
        """recording を開始する。既に ON なら何もしない。"""
        self._recording = True

    def stop(self) -> None:
        """recording を停止する。バッファはクリアしない。"""
        self._recording = False

    def clear(self) -> None:
        """バッファをクリアする。recording 状態は変えない。"""
        self._buffer.clear()

    def record(self, action: RouletteAction) -> None:
        """アクションをバッファに追加する。

        recording OFF の場合は何もしない。
        """
        if self._recording:
            self._buffer.append(action)

    def snapshot(self) -> list[RouletteAction]:
        """記録済みアクションのコピーを返す。

        内部バッファの参照を直接渡さず、浅いコピーを返す。
        """
        return list(self._buffer)
