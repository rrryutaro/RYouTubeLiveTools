"""
Google Sheets Viewer
- フレームレスウィンドウ（タイトルバー・枠なし）
- ツールバーをドラッグして移動
- ウィンドウ端をドラッグしてリサイズ
- システムの Chrome を専用プロファイルで起動・埋め込み
"""

import sys
import os
import json
import time
import subprocess
import ctypes
import ctypes.wintypes
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDialog, QDialogButtonBox, QLineEdit,
    QMessageBox, QStatusBar, QSizeGrip
)
from PyQt6.QtCore import (
    QSize, QPoint, Qt, QTimer, QThread, pyqtSignal, QRect, QPointF
)
from PyQt6.QtGui import QKeySequence, QShortcut, QCursor

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────
APP_DIR     = Path(os.environ.get("APPDATA", Path.home())) / "SheetsViewer"
CONFIG_FILE = APP_DIR / "config.json"
PROFILE_DIR = APP_DIR / "chrome_profile"
TOOLBAR_H   = 44
RESIZE_MARGIN = 6   # ウィンドウ端のリサイズ判定幅(px)

def load_config() -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg: dict):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────────────────────
# Chrome パス探索
# ─────────────────────────────────────────────────────────────
def find_chrome() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES", ""))
            / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None

# ─────────────────────────────────────────────────────────────
# Win32 API
# ─────────────────────────────────────────────────────────────
user32 = ctypes.windll.user32

GWL_STYLE      = -16
WS_CAPTION     = 0x00C00000
WS_THICKFRAME  = 0x00040000
WS_BORDER      = 0x00800000
WS_DLGFRAME    = 0x00400000
WS_SYSMENU     = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE       = 0x0002
SWP_NOSIZE       = 0x0001
SWP_NOZORDER     = 0x0004
SWP_NOACTIVATE   = 0x0010

EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)

def find_hwnd_by_pid(pid: int) -> int | None:
    found = []
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        tid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(tid))
        if tid.value == pid:
            found.append(hwnd)
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None

def strip_chrome_decoration(hwnd: int):
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER |
               WS_DLGFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                        SWP_NOACTIVATE | SWP_FRAMECHANGED)

# ─────────────────────────────────────────────────────────────
# ウィンドウリサイズ方向
# ─────────────────────────────────────────────────────────────
class ResizeDir:
    NONE  = 0
    LEFT  = 1
    RIGHT = 2
    TOP   = 4
    BOT   = 8
    TL    = LEFT  | TOP
    TR    = RIGHT | TOP
    BL    = LEFT  | BOT
    BR    = RIGHT | BOT

def get_resize_dir(pos: QPoint, rect: QRect, margin: int) -> int:
    d = ResizeDir.NONE
    if pos.x() <= margin:              d |= ResizeDir.LEFT
    if pos.x() >= rect.width() - margin: d |= ResizeDir.RIGHT
    if pos.y() <= margin:              d |= ResizeDir.TOP
    if pos.y() >= rect.height() - margin: d |= ResizeDir.BOT
    return d

RESIZE_CURSORS = {
    ResizeDir.LEFT:  Qt.CursorShape.SizeHorCursor,
    ResizeDir.RIGHT: Qt.CursorShape.SizeHorCursor,
    ResizeDir.TOP:   Qt.CursorShape.SizeVerCursor,
    ResizeDir.BOT:   Qt.CursorShape.SizeVerCursor,
    ResizeDir.TL:    Qt.CursorShape.SizeFDiagCursor,
    ResizeDir.BR:    Qt.CursorShape.SizeFDiagCursor,
    ResizeDir.TR:    Qt.CursorShape.SizeBDiagCursor,
    ResizeDir.BL:    Qt.CursorShape.SizeBDiagCursor,
}

# ─────────────────────────────────────────────────────────────
# ドラッグ移動可能なツールバー
# ─────────────────────────────────────────────────────────────
class DraggableToolbar(QWidget):
    """ドラッグで親ウィンドウを移動するツールバー"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """ダブルクリックで最大化/元に戻す"""
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()
        super().mouseDoubleClickEvent(event)

# ─────────────────────────────────────────────────────────────
# Chrome 起動スレッド
# ─────────────────────────────────────────────────────────────
class ChromeLauncher(QThread):
    ready  = pyqtSignal(int, int)
    failed = pyqtSignal(str)

    def __init__(self, chrome_path: str, url: str, parent=None):
        super().__init__(parent)
        self.chrome_path = chrome_path
        self.url         = url

    def run(self):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        args = [
            self.chrome_path,
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "--lang=ja",
            "--app=" + self.url,
        ]
        try:
            proc = subprocess.Popen(args)
        except Exception as e:
            self.failed.emit(f"Chrome起動失敗: {e}")
            return

        pid = proc.pid
        for _ in range(100):
            time.sleep(0.15)
            hwnd = find_hwnd_by_pid(pid)
            if hwnd:
                time.sleep(0.5)
                self.ready.emit(pid, hwnd)
                return
        self.failed.emit("Chromeウィンドウが見つかりませんでした。")

# ─────────────────────────────────────────────────────────────
# URL 入力ダイアログ
# ─────────────────────────────────────────────────────────────
class UrlDialog(QDialog):
    def __init__(self, current_url: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("URLを変更")
        self.setMinimumWidth(540)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.result_url = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Google スプレッドシートの URL を入力してください："))

        self.edit = QLineEdit(current_url)
        self.edit.setPlaceholderText("https://docs.google.com/spreadsheets/d/...")
        self.edit.selectAll()
        layout.addWidget(self.edit)

        hint = QLabel('<span style="color:gray;font-size:11px;">'
                      '例: https://docs.google.com/spreadsheets/d/xxxxxx/edit</span>')
        hint.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(hint)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("開く")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        self.edit.returnPressed.connect(self._on_ok)

    def _on_ok(self):
        url = self.edit.text().strip()
        if not url:
            QMessageBox.warning(self, "入力エラー", "URL を入力してください。")
            return
        if not url.startswith("http"):
            url = "https://" + url
        self.result_url = url
        self.accept()

    def get_url(self) -> str:
        return self.result_url

# ─────────────────────────────────────────────────────────────
# メインウィンドウ
# ─────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # ── フレームレスウィンドウ設定 ──
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        # 半透明対応（角丸などを使う場合に必要）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.cfg          = load_config()
        self._chrome_pid  = None
        self._chrome_hwnd = None
        self._launcher    = None

        # リサイズ用状態
        self._resizing     = False
        self._resize_dir   = ResizeDir.NONE
        self._resize_start_pos   = QPoint()
        self._resize_start_geom  = QRect()

        chrome = find_chrome()
        if chrome is None:
            QMessageBox.critical(
                None, "Chrome が見つかりません",
                "Google Chrome がインストールされていません。\n"
                "https://www.google.com/chrome/ からインストールしてください。"
            )
            sys.exit(1)
        self._chrome_path = chrome

        self._setup_ui()
        self._restore_geometry()

        # リサイズ追従タイマー
        self._resize_timer = QTimer(self)
        self._resize_timer.setInterval(200)
        self._resize_timer.timeout.connect(self._sync_chrome_size)

        last_url = self.cfg.get("last_url", "")
        if last_url:
            QTimer.singleShot(200, lambda: self._launch_chrome(last_url))
        else:
            QTimer.singleShot(200, self._open_url_dialog)

    # ── UI ───────────────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle("Sheets Viewer")
        self.setMinimumSize(640, 400)

        # マウストラッキングをウィンドウ全体で有効化（リサイズカーソル用）
        self.setMouseTracking(True)

        central = QWidget()
        central.setMouseTracking(True)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── ツールバー（ドラッグ移動） ──
        self.toolbar = DraggableToolbar()
        self.toolbar.setFixedHeight(TOOLBAR_H)
        self.toolbar.setMouseTracking(True)
        self.toolbar.setStyleSheet("""
            DraggableToolbar { background: #1a73e8; }
            QPushButton {
                color: white; background: transparent;
                border: none; border-radius: 4px;
                padding: 4px 10px; font-size: 13px;
            }
            QPushButton:hover    { background: rgba(255,255,255,0.18); }
            QPushButton:pressed  { background: rgba(255,255,255,0.30); }
            QPushButton:disabled { color: rgba(255,255,255,0.35); }
            QLabel { color: white; font-weight: bold; font-size: 13px; }
        """)
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(10, 0, 6, 0)
        tb.setSpacing(4)

        tb.addWidget(QLabel("📊 Sheets Viewer"))
        tb.addSpacing(10)

        self.btn_back    = QPushButton("◀")
        self.btn_forward = QPushButton("▶")
        self.btn_reload  = QPushButton("↻")
        self.btn_back.setToolTip("戻る")
        self.btn_forward.setToolTip("進む")
        self.btn_reload.setToolTip("再読み込み (F5)")
        for b in (self.btn_back, self.btn_forward, self.btn_reload):
            b.setEnabled(False)
            b.setFixedWidth(32)
        self.btn_back.clicked.connect(self._go_back)
        self.btn_forward.clicked.connect(self._go_forward)
        self.btn_reload.clicked.connect(self._go_reload)
        tb.addWidget(self.btn_back)
        tb.addWidget(self.btn_forward)
        tb.addWidget(self.btn_reload)

        tb.addStretch()

        self.lbl_tb = QLabel("起動中...")
        self.lbl_tb.setStyleSheet("color: rgba(255,255,255,0.8); font-size:12px;")
        tb.addWidget(self.lbl_tb)
        tb.addSpacing(6)

        self.btn_url = QPushButton("🔗 URLを変更")
        self.btn_url.setToolTip("Ctrl+L")
        self.btn_url.clicked.connect(self._open_url_dialog)
        tb.addWidget(self.btn_url)
        tb.addSpacing(4)

        # 最小化／最大化／閉じるボタン
        for text, tip, slot in (
            ("─", "最小化", self.showMinimized),
            ("□", "最大化 / 元に戻す", self._toggle_maximize),
            ("✕", "閉じる", self.close),
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setFixedWidth(36)
            btn.clicked.connect(slot)
            if text == "✕":
                btn.setStyleSheet(
                    "QPushButton { color:white; background:transparent; border:none; "
                    "border-radius:4px; font-size:14px; padding:4px; }"
                    "QPushButton:hover { background: #e53935; }"
                )
            tb.addWidget(btn)

        root.addWidget(self.toolbar)

        # ── Chrome 埋め込みエリア ──
        self.embed_area = QWidget()
        self.embed_area.setMouseTracking(True)
        self.embed_area.setStyleSheet("background: #e8eaed;")
        root.addWidget(self.embed_area, 1)

        # 右下にサイズグリップ（視覚ヒント）
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet(
            "QSizeGrip { background: transparent; width:12px; height:12px; }"
        )

        # ステータスバー
        self.status_bar = QStatusBar()
        self.status_bar.setFixedHeight(20)
        self.status_bar.setStyleSheet(
            "QStatusBar { background:#f1f3f4; font-size:11px; color:#555; }"
        )
        self.setStatusBar(self.status_bar)

        # ショートカット
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self._open_url_dialog)
        QShortcut(QKeySequence("F5"),     self).activated.connect(self._go_reload)
        QShortcut(QKeySequence("F11"),    self).activated.connect(self._toggle_fullscreen)

    # ── ウィンドウ操作 ────────────────────────────────────────
    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ── マウスイベント（リサイズ） ────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            d = get_resize_dir(event.pos(), self.rect(), RESIZE_MARGIN)
            if d != ResizeDir.NONE:
                self._resizing            = True
                self._resize_dir          = d
                self._resize_start_pos    = event.globalPosition().toPoint()
                self._resize_start_geom   = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing and event.buttons() & Qt.MouseButton.LeftButton:
            self._do_resize(event.globalPosition().toPoint())
            event.accept()
            return

        # カーソル変更
        d = get_resize_dir(event.pos(), self.rect(), RESIZE_MARGIN)
        if d in RESIZE_CURSORS:
            self.setCursor(RESIZE_CURSORS[d])
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing   = False
            self._resize_dir = ResizeDir.NONE
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _do_resize(self, global_pos: QPoint):
        d     = self._resize_dir
        diff  = global_pos - self._resize_start_pos
        geo   = QRect(self._resize_start_geom)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()

        new_left   = geo.left()
        new_top    = geo.top()
        new_right  = geo.right()
        new_bottom = geo.bottom()

        if d & ResizeDir.RIGHT:  new_right  = geo.right()  + diff.x()
        if d & ResizeDir.BOT:    new_bottom = geo.bottom() + diff.y()
        if d & ResizeDir.LEFT:
            new_left = geo.left() + diff.x()
            if new_right - new_left < min_w:
                new_left = new_right - min_w
        if d & ResizeDir.TOP:
            new_top = geo.top() + diff.y()
            if new_bottom - new_top < min_h:
                new_top = new_bottom - min_h

        self.setGeometry(new_left, new_top,
                         max(min_w, new_right - new_left),
                         max(min_h, new_bottom - new_top))

    # ── Chrome 起動 ───────────────────────────────────────────
    def _launch_chrome(self, url: str):
        self._kill_chrome()
        self.lbl_tb.setText("Chrome 起動中...")
        self.status_bar.showMessage("Chrome を起動しています...")
        for b in (self.btn_back, self.btn_forward, self.btn_reload):
            b.setEnabled(False)

        self.cfg["last_url"] = url
        save_config(self.cfg)

        self._launcher = ChromeLauncher(self._chrome_path, url, self)
        self._launcher.ready.connect(self._on_chrome_ready)
        self._launcher.failed.connect(self._on_chrome_failed)
        self._launcher.start()

    def _on_chrome_ready(self, pid: int, hwnd: int):
        self._chrome_pid  = pid
        self._chrome_hwnd = hwnd

        container = int(self.embed_area.winId())
        strip_chrome_decoration(hwnd)
        user32.SetParent(hwnd, container)
        self._sync_chrome_size()

        for b in (self.btn_back, self.btn_forward, self.btn_reload):
            b.setEnabled(True)
        self.lbl_tb.setText("")
        self.status_bar.showMessage("準備完了", 3000)
        self._resize_timer.start()

    def _on_chrome_failed(self, msg: str):
        self.lbl_tb.setText("エラー")
        self.status_bar.showMessage(msg, 8000)
        QMessageBox.warning(self, "Chrome 起動エラー", msg)

    def _sync_chrome_size(self):
        if self._chrome_hwnd:
            r = self.embed_area.rect()
            user32.MoveWindow(self._chrome_hwnd, 0, 0, r.width(), r.height(), True)

    def _kill_chrome(self):
        if hasattr(self, "_resize_timer"):
            self._resize_timer.stop()
        if self._chrome_pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(self._chrome_pid)],
                    capture_output=True
                )
            except Exception:
                pass
        self._chrome_pid  = None
        self._chrome_hwnd = None

    # ── キー送信 ──────────────────────────────────────────────
    KEYUP = 0x0002

    def _focus_chrome(self):
        if self._chrome_hwnd:
            user32.SetForegroundWindow(self._chrome_hwnd)

    def _go_back(self):
        self._focus_chrome()
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x25, 0, 0, 0)
        user32.keybd_event(0x25, 0, self.KEYUP, 0)
        user32.keybd_event(0x12, 0, self.KEYUP, 0)

    def _go_forward(self):
        self._focus_chrome()
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x27, 0, 0, 0)
        user32.keybd_event(0x27, 0, self.KEYUP, 0)
        user32.keybd_event(0x12, 0, self.KEYUP, 0)

    def _go_reload(self):
        self._focus_chrome()
        user32.keybd_event(0x74, 0, 0, 0)
        user32.keybd_event(0x74, 0, self.KEYUP, 0)

    # ── URL ダイアログ ────────────────────────────────────────
    def _open_url_dialog(self):
        dlg = UrlDialog(self.cfg.get("last_url", ""), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            url = dlg.get_url()
            if url:
                self._launch_chrome(url)

    # ── ウィンドウ状態 ────────────────────────────────────────
    def _restore_geometry(self):
        geo = self.cfg.get("geometry")
        if geo:
            try:
                self.resize(QSize(geo["width"], geo["height"]))
                self.move(QPoint(geo["x"], geo["y"]))
                return
            except Exception:
                pass
        self.resize(1280, 800)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - 1280) // 2,
            (screen.height() - 800)  // 2
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_chrome_size()
        # SizeGrip を右下に配置
        sg = self.size_grip
        sg.move(self.width() - sg.width(), self.height() - sg.height())

    def closeEvent(self, event):
        self._resize_timer.stop()
        pos, size = self.pos(), self.size()
        self.cfg["geometry"] = {
            "x": pos.x(), "y": pos.y(),
            "width": size.width(), "height": size.height()
        }
        save_config(self.cfg)
        self._kill_chrome()
        event.accept()

# ─────────────────────────────────────────────────────────────
# エントリポイント
# ─────────────────────────────────────────────────────────────
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    os.environ.setdefault("LANG", "ja_JP.UTF-8")

    app = QApplication(sys.argv)
    app.setApplicationName("SheetsViewer")
    app.setApplicationDisplayName("Sheets Viewer")

    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
