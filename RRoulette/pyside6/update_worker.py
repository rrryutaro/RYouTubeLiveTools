"""
update_worker.py — 更新チェックを非同期化する QThread ワーカー（P1）

仕様: 自動アップデート機能 設計仕様 §9

GitHub Releases API へのアクセスはネットワーク遅延を伴うため、UI スレッドを
ブロックしないよう QThread 上で `updater.check_for_update()` を実行し、結果を
Qt シグナルで UI スレッドへ通知する。

- 成功（更新あり）: check_finished(ReleaseInfo)
- 成功（最新 / source / 開発ビルド）: check_finished(None)
- 失敗（ネットワーク不通・タイムアウト・レート超過・JSON異常）: check_failed(str)

外部依存は増やさない（stdlib + PySide6 のみ）。ダウンロード・適用は後続 P2/P3。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

import updater


class UpdateCheckWorker(QThread):
    """更新チェックをバックグラウンドで実行する QThread。

    使い方（呼び出し側 = UI スレッド）:
        self._update_worker = UpdateCheckWorker(timeout=10, manual=True, parent=self)
        self._update_worker.check_finished.connect(self._on_update_check_finished)
        self._update_worker.check_failed.connect(self._on_update_check_failed)
        self._update_worker.start()

    `manual` は「手動チェックか起動時チェックか」を UI へ伝えるための付帯情報。
    ワーカー自体の挙動は変えず、結果ハンドラ側でダイアログ表示可否の判断に使う。
    """

    # ReleaseInfo | None（None = 最新 / 更新対象外）
    check_finished = Signal(object)
    # エラー詳細文字列
    check_failed = Signal(str)

    def __init__(self, timeout: int = 10, manual: bool = False, parent=None):
        super().__init__(parent)
        self._timeout = timeout
        self.manual = manual

    def run(self):  # QThread のワーカー本体（別スレッドで実行される）
        try:
            release = updater.check_for_update(timeout=self._timeout)
        except Exception as e:  # ネットワーク系例外はここで捕捉して UI へ通知
            self.check_failed.emit(f"{type(e).__name__}: {e}")
            return
        self.check_finished.emit(release)


class UpdateDownloadWorker(QThread):
    """更新素材のダウンロード＋ステージングをバックグラウンドで実行する QThread。

    UI スレッドから cancel() でキャンセル可能。進捗・結果は Qt シグナルで通知する。
    """

    # (downloaded:int, total:int|None)
    progress = Signal(int, object)
    # 成功: staged dict（{"new_exe":..., "new_manifest":...}）
    finished_ok = Signal(object)
    # 失敗: エラー詳細
    failed = Signal(str)
    # キャンセル完了
    cancelled = Signal()

    def __init__(self, plan, release, install_dir, parent=None):
        super().__init__(parent)
        self._plan = plan
        self._release = release
        self._install_dir = install_dir
        self._cancel_event = threading.Event()

    def cancel(self):
        """ダウンロードのキャンセルを要求する（UI スレッドから呼ぶ）。"""
        self._cancel_event.set()

    def run(self):
        try:
            staged = updater.stage_update(
                self._plan, self._release, self._install_dir,
                progress_cb=lambda dl, total: self.progress.emit(dl, total),
                cancel=self._cancel_event,
            )
        except updater.CancelledError:
            self._cleanup_partial()
            self.cancelled.emit()
            return
        except Exception as e:
            self._cleanup_partial()
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.finished_ok.emit(staged)

    def _cleanup_partial(self):
        """中断・失敗時のステージング残骸を掃除する。"""
        import os
        for name in (updater._NEW_EXE_NAME, updater._NEW_MANIFEST_NAME):
            updater._safe_remove(os.path.join(self._install_dir, name))
