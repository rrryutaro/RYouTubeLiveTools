"""
PySide6 プロトタイプ — リプレイ管理ダイアログ

保存済み replay の一覧表示・選択・再生・削除を行う独立ウィンドウ。

責務:
  - replay 一覧の表示（名前・結果・日時）
  - 選択 replay の再生リクエスト
  - 選択 replay の削除
  - 0 件時の空状態表示
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QMenu, QInputDialog,
    QFileDialog,
)

from dark_theme import build_dialog_stylesheet
from design_settings import DesignSettings


class ReplayDialog(QDialog):
    """リプレイ管理ダイアログ。

    非モーダルの Tool ウィンドウとして動作する。
    """

    play_requested = Signal(int)          # 再生リクエスト (replay index)
    delete_requested = Signal(int)        # 削除リクエスト (replay index)
    rename_requested = Signal(int, str)   # 名称変更リクエスト (replay index, new_name)
    keep_requested = Signal(int, bool)    # 保持フラグ変更リクエスト (replay index, keep)
    export_requested = Signal(int, str)   # 書き出しリクエスト (replay index, file_path)
    export_multi_requested = Signal(list, str)  # 複数書き出しリクエスト (indices, file_path)
    import_requested = Signal(list)        # 読み込みリクエスト (file_paths)

    def __init__(self, design: DesignSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("リプレイ管理")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(380, 300)
        self.resize(420, 400)

        self._design = design
        self._replay_count = 0
        self._playing = False
        self._records: list[dict] = []

        self._build_ui()

    def _build_ui(self):
        d = self._design
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.setStyleSheet(build_dialog_stylesheet(d))

        # ヘッダー
        header = QLabel("保存済みリプレイ")
        header.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {d.gold};")
        layout.addWidget(header)

        # 一覧
        self._list = QListWidget()
        self._list.setFont(QFont("Meiryo", 9))
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setStyleSheet(
            f"QListWidget {{"
            f"  background-color: {d.bg}; color: {d.text};"
            f"  border: 1px solid {d.separator};"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background-color: {d.separator};"
            f"}}"
        )
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.currentRowChanged.connect(lambda _: self._update_buttons())
        self._list.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._list, stretch=1)

        # 空状態ラベル
        self._empty_lbl = QLabel("リプレイ記録がありません")
        self._empty_lbl.setFont(QFont("Meiryo", 9))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(f"color: {d.text_sub};")
        self._empty_lbl.hide()
        layout.addWidget(self._empty_lbl)

        # ボタン行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        btn_style = (
            f"QPushButton {{"
            f"  background-color: {d.separator}; color: {d.text};"
            f"  border: none; border-radius: 3px; padding: 6px 12px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {d.accent}; }}"
            f"QPushButton:disabled {{ color: {d.text_sub}; }}"
        )

        self._play_btn = QPushButton("再生")
        self._play_btn.setFont(QFont("Meiryo", 9))
        self._play_btn.setStyleSheet(btn_style)
        self._play_btn.clicked.connect(self._on_play)
        btn_row.addWidget(self._play_btn)

        self._delete_btn = QPushButton("削除")
        self._delete_btn.setFont(QFont("Meiryo", 9))
        self._delete_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {d.separator}; color: {d.text};"
            f"  border: none; border-radius: 3px; padding: 6px 12px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #c0392b; color: white; }}"
            f"QPushButton:disabled {{ color: {d.text_sub}; }}"
        )
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        self._rename_btn = QPushButton("名称変更")
        self._rename_btn.setFont(QFont("Meiryo", 9))
        self._rename_btn.setStyleSheet(btn_style)
        self._rename_btn.clicked.connect(self._on_rename)
        btn_row.addWidget(self._rename_btn)

        self._keep_btn = QPushButton("保持")
        self._keep_btn.setFont(QFont("Meiryo", 9))
        self._keep_btn.setStyleSheet(btn_style)
        self._keep_btn.clicked.connect(self._on_keep_toggle)
        btn_row.addWidget(self._keep_btn)

        btn_row.addStretch(1)

        self._count_lbl = QLabel("0件")
        self._count_lbl.setFont(QFont("Meiryo", 8))
        self._count_lbl.setStyleSheet(f"color: {d.text_sub};")
        btn_row.addWidget(self._count_lbl)

        layout.addLayout(btn_row)

        # ボタン行2（書き出し / 読み込み）
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(4)

        self._export_btn = QPushButton("書き出し...")
        self._export_btn.setFont(QFont("Meiryo", 9))
        self._export_btn.setStyleSheet(btn_style)
        self._export_btn.clicked.connect(self._on_export)
        btn_row2.addWidget(self._export_btn)

        self._import_btn = QPushButton("読み込み...")
        self._import_btn.setFont(QFont("Meiryo", 9))
        self._import_btn.setStyleSheet(btn_style)
        self._import_btn.clicked.connect(self._on_import)
        btn_row2.addWidget(self._import_btn)

        btn_row2.addStretch(1)
        layout.addLayout(btn_row2)

    def refresh_list(self, records: list[dict]):
        """replay 一覧を更新する。

        Args:
            records: ReplayManager.records のコピー
        """
        self._records = records
        self._list.clear()
        self._replay_count = len(records)
        self._count_lbl.setText(f"{self._replay_count}件")

        if not records:
            self._list.hide()
            self._empty_lbl.show()
            self._play_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            return

        self._empty_lbl.hide()
        self._list.show()

        for i, rec in enumerate(records):
            name = rec.get("name", f"replay {i}")
            result = rec.get("result", {})
            winner = result.get("winner", "") if result else ""
            created = rec.get("created_at", "")[:19]  # ISO 8601 切り詰め

            display = name
            if not display:
                display = f"{created} - {winner}" if winner else created

            keep = rec.get("keep", False)
            if keep:
                display = f"\u2605 {display}"

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)

        self._list.setCurrentRow(0)
        self._update_buttons()

    def set_playing(self, playing: bool):
        """再生中状態を設定する。"""
        self._playing = playing
        self._update_buttons()

    def _update_buttons(self):
        """ボタンの有効/無効を更新する。"""
        selected = self._list.selectedItems()
        has_selection = len(selected) >= 1
        single_selection = len(selected) == 1
        self._play_btn.setEnabled(single_selection and not self._playing)
        self._delete_btn.setEnabled(single_selection and not self._playing)
        self._rename_btn.setEnabled(single_selection and not self._playing)
        self._keep_btn.setEnabled(single_selection)
        self._export_btn.setEnabled(has_selection and not self._playing)
        self._import_btn.setEnabled(not self._playing)

        # 書き出しボタンのラベルを選択数に応じて更新
        if len(selected) > 1:
            self._export_btn.setText(f"書き出し({len(selected)}件)...")
        else:
            self._export_btn.setText("書き出し...")

        # keep ボタンのラベルを現在の keep 状態に応じて切り替え
        if has_selection:
            idx = self._list.currentItem().data(Qt.ItemDataRole.UserRole)
            if 0 <= idx < len(self._records) and self._records[idx].get("keep"):
                self._keep_btn.setText("保持解除")
            else:
                self._keep_btn.setText("保持")
        else:
            self._keep_btn.setText("保持")

    def _on_play(self):
        """再生ボタン押下。"""
        item = self._list.currentItem()
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        self.play_requested.emit(idx)

    def _on_delete(self):
        """削除ボタン押下。"""
        item = self._list.currentItem()
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()

        reply = QMessageBox.question(
            self, "リプレイ削除",
            f"リプレイ「{name}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(idx)

    def _on_keep_toggle(self):
        """保持ボタン押下。現在の keep 状態を反転する。"""
        item = self._list.currentItem()
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(self._records):
            current_keep = self._records[idx].get("keep", False)
            self.keep_requested.emit(idx, not current_keep)

    def _on_rename(self):
        """名称変更ボタン押下。"""
        item = self._list.currentItem()
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        current_name = self._get_record_name(idx)
        self._request_rename(idx, current_name)

    def _get_record_name(self, idx: int) -> str:
        """実データの name を取得する（表示用接頭辞なし）。"""
        if 0 <= idx < len(self._records):
            return self._records[idx].get("name", "")
        return ""

    def _request_rename(self, idx: int, current_name: str):
        """名称変更ダイアログを表示し、確定時にシグナルを発火する。"""
        new_name, ok = QInputDialog.getText(
            self, "リプレイ名称変更",
            "新しい名前:",
            text=current_name,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        self.rename_requested.emit(idx, new_name)

    def _on_export(self):
        """書き出しボタン押下（単体/複数を自動切替）。"""
        selected = self._list.selectedItems()
        if not selected:
            return

        indices = [item.data(Qt.ItemDataRole.UserRole) for item in selected]

        if len(indices) == 1:
            # 単体 export（既存フロー）
            idx = indices[0]
            rec_name = self._get_record_name(idx)
            safe_name = "".join(
                c if c not in r'\/:*?"<>|' else "_" for c in rec_name
            ) if rec_name else "replay"

            path, _ = QFileDialog.getSaveFileName(
                self, "リプレイ書き出し",
                safe_name + ".json",
                "JSON Files (*.json)",
            )
            if not path:
                return
            self.export_requested.emit(idx, path)
        else:
            # 複数 export
            path, _ = QFileDialog.getSaveFileName(
                self, f"リプレイ書き出し（{len(indices)}件）",
                f"replays_{len(indices)}.json",
                "JSON Files (*.json)",
            )
            if not path:
                return
            self.export_multi_requested.emit(indices, path)

    def _on_import(self):
        """読み込みボタン押下（複数ファイル選択対応）。"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "リプレイ読み込み",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not paths:
            return
        self.import_requested.emit(paths)

    def _on_context_menu(self, pos):
        """一覧の右クリックコンテキストメニュー。"""
        item = self._list.itemAt(pos)
        if item is None:
            return

        # 右クリックした行を選択状態にする
        self._list.setCurrentItem(item)

        idx = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()

        # keep 状態を取得
        is_keep = False
        if 0 <= idx < len(self._records):
            is_keep = self._records[idx].get("keep", False)

        menu = QMenu(self)
        play_action = menu.addAction("再生")
        rename_action = menu.addAction("名称変更")
        keep_action = menu.addAction("保持解除" if is_keep else "保持")
        menu.addSeparator()
        delete_action = menu.addAction("削除")

        # 再生中は再生・名称変更・削除を無効化（保持は操作可能）
        if self._playing:
            play_action.setEnabled(False)
            rename_action.setEnabled(False)
            delete_action.setEnabled(False)

        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is None:
            return

        if chosen is play_action:
            self.play_requested.emit(idx)
        elif chosen is rename_action:
            self._request_rename(idx, self._get_record_name(idx))
        elif chosen is keep_action:
            self.keep_requested.emit(idx, not is_keep)
        elif chosen is delete_action:
            reply = QMessageBox.question(
                self, "リプレイ削除",
                f"リプレイ「{name}」を削除しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.delete_requested.emit(idx)
