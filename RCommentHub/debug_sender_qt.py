"""
RCommentHub — Qt版 デバッグコメント送信ウィンドウ

接続なしでも疑似コメントを本番と同じ controller 経路（add_comment）へ流して
CommentWindowQt / OverlayWindowQt の表示確認ができるデバッグツール。

v0.3.2 の debug_sender.py の役割を PySide6 QDialog で再実装。
X で閉じると非表示（アプリは終了しない）。
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QComboBox, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from debug_sender import _build_debug_raw
from constants import INPUT_SOURCE_DEBUG, INPUT_SOURCE_TWITCH

# ─── スタイル ─────────────────────────────────────────────────────────────────
_STYLE = """
QDialog {
    background: #1A1A2E;
    color: #CCCCCC;
}
QLabel {
    color: #CCCCCC;
    background: transparent;
}
QTextEdit {
    background: #252540;
    color: #FFFFFF;
    border: 1px solid #333355;
    border-radius: 2px;
    padding: 4px 6px;
    selection-background-color: #3A3A7A;
}
QTextEdit:focus {
    border: 1px solid #5555AA;
}
QComboBox {
    background: #252540;
    color: #CCCCCC;
    border: 1px solid #333355;
    border-radius: 2px;
    padding: 3px 6px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #1E1E38;
    color: #CCCCCC;
    border: 1px solid #333355;
    selection-background-color: #3A3A7A;
}
QPushButton {
    background: #252535;
    color: #CCCCCC;
    border: none;
    padding: 4px 12px;
    border-radius: 2px;
}
QPushButton:hover    { background: #3A3A5A; }
QPushButton:pressed  { background: #1A1A3A; }
QPushButton:disabled { background: #1A1A2E; color: #555566; }
QFrame { color: #333355; }
"""

_BTN_SEND = "background:#2A4A2A; color:#AAFFAA; padding:5px 20px; border-radius:2px; font-weight:bold;"


class DebugSenderWindowQt(QDialog):
    """
    Qt版 デバッグコメント送信ウィンドウ。

    controller.add_comment(raw) を通じて本番と同じ経路でコメントを流す。
    X で閉じると非表示（アプリは終了しない）。
    """

    def __init__(self, parent=None, *, controller, settings_mgr):
        super().__init__(parent)
        self._ctrl = controller
        self._sm   = settings_mgr
        self._source_map: dict = {}

        # 位置保存デバウンス
        self._pos_save_timer = QTimer(self)
        self._pos_save_timer.setSingleShot(True)
        self._pos_save_timer.setInterval(400)
        self._pos_save_timer.timeout.connect(
            lambda: self._sm.update({"debug_sender_pos": [self.x(), self.y()]})
        )

        self._build_ui()
        self._restore_pos()

    # ─── UI 構築 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("RCommentHub - デバッグ送信")
        self.setFixedWidth(440)
        self.setSizeGripEnabled(False)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        # ── 説明ラベル ──
        desc = QLabel("デバッグコメント送信（接続なしでも動作）")
        desc.setStyleSheet("color: #FF8C00; font-weight: bold;")
        root.addWidget(desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # ── 送信者プリセット選択 ──
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_lbl = QLabel("送信者:")
        preset_lbl.setStyleSheet("color: #AAAACC;")
        preset_lbl.setFixedWidth(56)
        preset_row.addWidget(preset_lbl)
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(160)
        self._preset_combo.currentIndexChanged.connect(self._update_detail)
        preset_row.addWidget(self._preset_combo)
        root.addLayout(preset_row)

        # ── プリセット操作ボタン ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        for label, slot in [("新規", self._new_preset), ("削除", self._delete_preset)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── プリセット詳細表示 ──
        self._detail_lbl = QLabel("← プリセットを選択")
        self._detail_lbl.setStyleSheet(
            "color: #8888AA; background:#252540; border:1px solid #333355;"
            "padding: 4px 8px; border-radius: 2px;"
        )
        self._detail_lbl.setMinimumHeight(42)
        self._detail_lbl.setWordWrap(True)
        root.addWidget(self._detail_lbl)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep2)

        # ── コメント本文 ──
        body_lbl = QLabel("コメント本文  (Ctrl+Enter で送信):")
        body_lbl.setStyleSheet("color: #AAAACC;")
        root.addWidget(body_lbl)

        self._body_edit = QTextEdit()
        self._body_edit.setMaximumHeight(72)
        self._body_edit.setPlaceholderText("コメントを入力してください…")
        # ダーク背景上でも入力文字が確実に見えるよう、ウィジェット単体に直接設定する
        # （ダイアログ全体のスタイルシートに依存すると Qt の palette 継承で色が打ち消されることがある）
        self._body_edit.setStyleSheet(
            "QTextEdit {"
            "  background: #252540; color: #FFFFFF;"
            "  border: 1px solid #333355; border-radius: 2px;"
            "  padding: 4px 6px; selection-background-color: #3A3A7A;"
            "}"
            "QTextEdit:focus { border: 1px solid #5555AA; }"
        )
        root.addWidget(self._body_edit)

        # ── 接続先セレクタ ──
        src_row = QHBoxLayout()
        src_lbl = QLabel("送信先:")
        src_lbl.setStyleSheet("color: #AAAACC;")
        src_lbl.setFixedWidth(56)
        src_row.addWidget(src_lbl)
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(160)
        src_row.addWidget(self._source_combo)
        src_row.addStretch()
        root.addLayout(src_row)

        # ── 送信ボタン ──
        send_row = QHBoxLayout()
        self._btn_send = QPushButton("▶ 送信")
        self._btn_send.setStyleSheet(_BTN_SEND)
        self._btn_send.clicked.connect(self._send)
        send_row.addWidget(self._btn_send)
        send_row.addStretch()
        root.addLayout(send_row)

        # Ctrl+Enter ショートカット
        sc = QShortcut(QKeySequence("Ctrl+Return"), self)
        sc.activated.connect(self._send)

        self._reload_presets()
        self._refresh_source_list()

    # ─── 公開 API ──────────────────────────────────────────────────────────────

    def open(self):
        """デバッグ送信画面を前面表示する。"""
        self._reload_presets()
        self._refresh_source_list()
        self.show()
        self.raise_()
        self.activateWindow()

    # ─── プリセット ────────────────────────────────────────────────────────────

    def _reload_presets(self):
        presets = self._ctrl.get_debug_presets()
        cur = self._preset_combo.currentText()
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for p in presets:
            self._preset_combo.addItem(p["name"])
        if cur:
            idx = self._preset_combo.findText(cur)
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)
        self._preset_combo.blockSignals(False)
        self._update_detail()

    def _current_preset(self) -> dict | None:
        name    = self._preset_combo.currentText()
        presets = self._ctrl.get_debug_presets()
        return next((p for p in presets if p["name"] == name), None)

    def _update_detail(self):
        preset = self._current_preset()
        if not preset:
            self._detail_lbl.setText("← プリセットを選択")
            return
        flags = []
        if preset.get("is_owner"):     flags.append("配信者")
        if preset.get("is_moderator"): flags.append("Mod")
        if preset.get("is_member"):    flags.append("Mbr")
        if preset.get("is_verified"):  flags.append("Ver")
        flag_str = f"[{', '.join(flags)}]" if flags else "[一般]"
        self._detail_lbl.setText(
            f"表示名: {preset['name']}  {flag_str}\n"
            f"ch_id:  {preset.get('channel_id', '')}"
        )

    def _new_preset(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        name, ok = QInputDialog.getText(self, "新規プリセット", "表示名:")
        if not ok or not name.strip():
            return
        name = name.strip()
        presets = self._ctrl.get_debug_presets()
        if any(p["name"] == name for p in presets):
            QMessageBox.warning(self, "保存エラー", f"「{name}」はすでに存在します。")
            return
        presets.append({
            "name":         name,
            "channel_id":   f"debug_{name}",
            "is_owner":     False,
            "is_moderator": False,
            "is_member":    False,
            "is_verified":  False,
        })
        self._ctrl.set_debug_presets(presets)
        self._reload_presets()
        idx = self._preset_combo.findText(name)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _delete_preset(self):
        from PySide6.QtWidgets import QMessageBox
        preset = self._current_preset()
        if not preset:
            return
        reply = QMessageBox.question(
            self, "削除確認", f"「{preset['name']}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        presets = [p for p in self._ctrl.get_debug_presets() if p["name"] != preset["name"]]
        self._ctrl.set_debug_presets(presets)
        self._reload_presets()

    # ─── 接続先 ────────────────────────────────────────────────────────────────

    def _refresh_source_list(self):
        """アクティブな接続先をコンボへ投入する（フォールバック: デバッグ接続）。"""
        self._source_map = {}
        sources = []
        try:
            for pid, info in self._ctrl._stream_infos.items():
                label = f"{info.get('source_name', pid)} ({pid})"
                sources.append(label)
                self._source_map[label] = (
                    pid,
                    info.get("source_name", pid),
                    info.get("platform", "youtube"),
                    info.get("source_name", pid),
                )
        except Exception:
            pass
        if not sources:
            label = "デバッグ (conn1)"
            sources = [label]
            self._source_map[label] = ("conn1", "DEBUG", "youtube", "DEBUG")

        cur = self._source_combo.currentText()
        self._source_combo.blockSignals(True)
        self._source_combo.clear()
        for s in sources:
            self._source_combo.addItem(s)
        if cur in self._source_map:
            self._source_combo.setCurrentText(cur)
        self._source_combo.blockSignals(False)

    # ─── 送信 ──────────────────────────────────────────────────────────────────

    def _send(self):
        from PySide6.QtWidgets import QMessageBox

        if not self._ctrl.debug_mode:
            QMessageBox.warning(
                self, "デバッグモード OFF",
                "デバッグモードが OFF です。\n"
                "詳細画面の「🐛 DEBUG OFF」ボタンで ON にしてから送信してください。"
            )
            return

        preset = self._current_preset()
        if not preset:
            QMessageBox.warning(self, "送信エラー", "送信者プリセットを選択してください。")
            return

        body = self._body_edit.toPlainText().strip()
        if not body:
            QMessageBox.warning(self, "送信エラー", "コメント本文を入力してください。")
            return

        self._refresh_source_list()
        src_label = self._source_combo.currentText()
        entry = self._source_map.get(src_label, ("conn1", "DEBUG", "youtube", "DEBUG"))
        source_id, source_name, platform, tts_name = entry
        source_type = INPUT_SOURCE_TWITCH if platform == "twitch" else INPUT_SOURCE_DEBUG

        raw = _build_debug_raw(
            preset, body,
            source_id=source_id,
            source_name=source_name,
            source_type=source_type,
            tts_source_name=tts_name,
        )
        self._ctrl.add_comment(raw)

        # 送信後に本文クリア
        self._body_edit.clear()
        self._body_edit.setFocus()

    # ─── 位置保存・復元 ────────────────────────────────────────────────────────

    def _restore_pos(self):
        pos = self._sm.get("debug_sender_pos", None)
        if pos and len(pos) >= 2:
            self.move(int(pos[0]), int(pos[1]))

    def moveEvent(self, event):
        super().moveEvent(event)
        self._pos_save_timer.start()

    def closeEvent(self, event):
        """X ボタンで閉じると非表示（アプリは終了しない）。"""
        event.ignore()
        self.hide()
