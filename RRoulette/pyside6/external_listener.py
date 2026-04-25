"""
external_listener.py — RCommentHub 連携用ローカル HTTP 受信サーバ

Phase 1: POST /api/link-message を受け取り、message_received シグナルで
メインスレッドへ渡す。UIスレッドをブロックしない。

設計方針:
  - http.server.HTTPServer をデーモンスレッドで起動
  - ハンドラ内で queue.Queue へ enqueue
  - QTimer(100ms) がキューをポーリングして message_received を emit
  - ホストは 127.0.0.1 に限定（外部ネットワークから接続不可）
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PySide6.QtCore import QObject, QTimer, Signal

_log = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 100  # キューポーリング間隔 (ms)


class ExternalListener(QObject):
    """ローカル HTTP サーバを管理し、受信メッセージをシグナルで通知する。

    Signals:
        message_received(dict): 連携メッセージを受信したとき（メインスレッドで emit）
        status_changed(str):    サーバ状態の変化（"started:{port}" / "stopped" / "error:{msg}"）
    """

    message_received = Signal(dict)
    status_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_queue)

    # ================================================================
    #  公開API
    # ================================================================

    def start(self, port: int) -> bool:
        """サーバを起動する。成功時 True、失敗時 False を返す。"""
        if self._server is not None:
            return True

        q = self._queue

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                if self.path != "/api/link-message":
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    data = json.loads(body.decode("utf-8"))
                    q.put(data)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                except Exception as e:
                    _log.warning("ExternalListener: request parse error: %s", e)
                    self.send_response(400)
                    self.end_headers()

            def log_message(self, fmt, *args):  # noqa: N802
                pass  # http.server のデフォルトログを抑制

        try:
            self._server = HTTPServer(("127.0.0.1", port), _Handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="ExternalListenerThread",
            )
            self._thread.start()
            self._poll_timer.start()
            _log.info("ExternalListener: started on 127.0.0.1:%d", port)
            self.status_changed.emit(f"started:{port}")
            return True
        except Exception as e:
            _log.error("ExternalListener: start failed on port %d: %s", port, e)
            self._server = None
            self._thread = None
            self.status_changed.emit(f"error:{e}")
            return False

    def stop(self) -> None:
        """サーバを停止する。"""
        self._poll_timer.stop()
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
        self._thread = None
        _log.info("ExternalListener: stopped")
        self.status_changed.emit("stopped")

    @property
    def is_running(self) -> bool:
        return self._server is not None

    # ================================================================
    #  内部
    # ================================================================

    def _poll_queue(self) -> None:
        """QTimer コールバック — キューからメッセージを取り出して emit する。"""
        while True:
            try:
                data = self._queue.get_nowait()
                self.message_received.emit(data)
            except queue.Empty:
                break
