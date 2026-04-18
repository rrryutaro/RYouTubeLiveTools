"""
RRoulette PySide6 — 全体管理パネル

settings_panel.py から分離した ManagePanel クラス。
SettingsPanel / ItemPanel に依存せず、独立して動作する。

責務:
  - 各パネル（項目パネル / 設定パネル）の表示/非表示制御
  - ルーレット一覧の表示と操作（追加 / アクティブ切替 / 表示切替 / 削除）
  - 設定一括適用フラグの管理
  - パネル位置初期化リクエストの発行
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QScrollArea, QWidget,
)

from bridge import DesignSettings
from panel_widgets import _PanelDragBar, install_panel_context_menu


class ManagePanel(QFrame):
    """全体管理パネル (F1)。

    各パネルを見失わずに管理するための最小ハブ。トップレベル Tool window として
    生成し、メインウィンドウ最小化時にも独立して位置が保たれる。

    機能:
      - 項目パネル表示 / 非表示 (チェックボックス)
      - 設定パネル表示 / 非表示 (チェックボックス)
      - パネル位置初期化ボタン
      - F1/F2/F3 ショートカット案内
    """

    items_panel_toggled = Signal(bool)
    settings_panel_toggled = Signal(bool)
    reset_positions_requested = Signal()
    geometry_changed = Signal()
    roulette_add_requested = Signal()
    roulette_activate_requested = Signal(str)
    roulette_visibility_toggled = Signal(str, bool)
    roulette_delete_requested = Signal(str)
    apply_to_all_changed = Signal(bool)  # i347: 一括適用フラグ
    roulette_pkg_export_requested = Signal()  # i419: ルーレット package エクスポート
    roulette_pkg_import_requested = Signal()  # i419: ルーレット package インポート

    def __init__(self, design: DesignSettings, *,
                 items_visible: bool = True,
                 settings_visible: bool = False,
                 on_drag_bar_changed=None,
                 parent=None):
        super().__init__(parent)
        self._design = design
        self.pinned_front = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 上部ドラッグバー (パネル移動の起点)
        self._drag_bar = _PanelDragBar(self, design, parent=self)
        outer.addWidget(self._drag_bar)
        # 右クリック → 移動バー表示/非表示
        install_panel_context_menu(self, self._drag_bar,
                                   on_drag_bar_changed=on_drag_bar_changed)

        # コンテンツ
        body = QFrame()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(8)

        title = QLabel("パネル管理")
        title.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {design.text};")
        body_layout.addWidget(title)

        self._items_cb = QCheckBox("項目パネルを表示 (F2)")
        self._items_cb.setFont(QFont("Meiryo", 9))
        self._items_cb.setStyleSheet(f"color: {design.text};")
        self._items_cb.setChecked(items_visible)
        self._items_cb.toggled.connect(self.items_panel_toggled.emit)
        body_layout.addWidget(self._items_cb)

        self._settings_cb = QCheckBox("設定パネルを表示 (F3)")
        self._settings_cb.setFont(QFont("Meiryo", 9))
        self._settings_cb.setStyleSheet(f"color: {design.text};")
        self._settings_cb.setChecked(settings_visible)
        self._settings_cb.toggled.connect(self.settings_panel_toggled.emit)
        body_layout.addWidget(self._settings_cb)

        body_layout.addSpacing(4)

        self._reset_btn = QPushButton("パネル位置を初期化")
        self._reset_btn.setFont(QFont("Meiryo", 9))
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 4px; padding: 6px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._reset_btn.clicked.connect(self.reset_positions_requested.emit)
        body_layout.addWidget(self._reset_btn)

        # i276: ショートカット説明はユーザー要請により削除。
        # 将来ヘルプを追加する余地を残してあるが、本セッションでは追加しない。

        body_layout.addSpacing(8)

        # i420: 「ルーレット管理」ラベル行に export / import アイコンを並べる
        _roulette_title_row = QHBoxLayout()
        _roulette_title_row.setContentsMargins(0, 0, 0, 0)
        _roulette_title_row.setSpacing(2)

        self._roulette_title_label = QLabel("ルーレット管理")
        self._roulette_title_label.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._roulette_title_label.setStyleSheet(f"color: {design.text};")
        _roulette_title_row.addWidget(self._roulette_title_label, stretch=1)

        _pkg_icon_style = (
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text};"
            f"  border: none; padding: 1px 4px;"
            f"  font-size: 10pt; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ color: {design.accent}; }}"
        )
        self._pkg_export_btn = QPushButton("↑")
        self._pkg_export_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._pkg_export_btn.setStyleSheet(_pkg_icon_style)
        self._pkg_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pkg_export_btn.setToolTip(
            "active ルーレットを書き出す\n（他者共有・移行用）"
        )
        self._pkg_export_btn.clicked.connect(self.roulette_pkg_export_requested.emit)
        _roulette_title_row.addWidget(self._pkg_export_btn)

        self._pkg_import_btn = QPushButton("↓")
        self._pkg_import_btn.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        self._pkg_import_btn.setStyleSheet(_pkg_icon_style)
        self._pkg_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pkg_import_btn.setToolTip(
            "ルーレットを読み込む\n（ファイルから新規追加）"
        )
        self._pkg_import_btn.clicked.connect(self.roulette_pkg_import_requested.emit)
        _roulette_title_row.addWidget(self._pkg_import_btn)

        body_layout.addLayout(_roulette_title_row)

        # ルーレット一覧（動的に更新）
        self._roulette_list_layout = QVBoxLayout()
        self._roulette_list_layout.setSpacing(4)
        self._roulette_list_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addLayout(self._roulette_list_layout)
        self._roulette_rows: dict[str, QWidget] = {}

        # 追加ボタン
        self._add_roulette_btn = QPushButton("+ ルーレットを追加")
        self._add_roulette_btn.setFont(QFont("Meiryo", 9))
        self._add_roulette_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_roulette_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {design.separator}; color: {design.text};"
            f"  border: none; border-radius: 4px; padding: 5px 10px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {design.accent}; }}"
        )
        self._add_roulette_btn.clicked.connect(self.roulette_add_requested.emit)
        body_layout.addWidget(self._add_roulette_btn)

        body_layout.addSpacing(8)

        # i347: 設定一括適用チェックボックス
        apply_title = QLabel("設定適用先")
        apply_title.setFont(QFont("Meiryo", 10, QFont.Weight.Bold))
        apply_title.setStyleSheet(f"color: {design.text};")
        body_layout.addWidget(apply_title)

        self._apply_all_cb = QCheckBox("全ルーレットに適用")
        self._apply_all_cb.setFont(QFont("Meiryo", 9))
        self._apply_all_cb.setStyleSheet(f"color: {design.text};")
        self._apply_all_cb.setChecked(False)
        self._apply_all_cb.setToolTip(
            "ON: 設定パネルの変更を全ルーレットに一括適用\nOFF: 選択中ルーレットのみに適用"
        )
        self._apply_all_cb.toggled.connect(self.apply_to_all_changed.emit)
        body_layout.addWidget(self._apply_all_cb)

        body.setStyleSheet(f"background-color: {design.panel};")

        # i348: コンテンツをスクロール領域で包む（高さ不足でも潰れない）
        self._scroll = QScrollArea()
        self._scroll.setWidget(body)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(f"background-color: {design.panel};")
        outer.addWidget(self._scroll, stretch=1)

        self.setStyleSheet(f"background-color: {design.panel};")
        self.setMinimumSize(240, 220)

    # ----------------------------------------------------------------
    #  公開 API
    # ----------------------------------------------------------------

    def set_items_visible(self, visible: bool):
        """項目パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._items_cb.blockSignals(True)
        self._items_cb.setChecked(visible)
        self._items_cb.blockSignals(False)

    def set_settings_visible(self, visible: bool):
        """設定パネルチェック状態を外部から同期する (シグナルなし)。"""
        self._settings_cb.blockSignals(True)
        self._settings_cb.setChecked(visible)
        self._settings_cb.blockSignals(False)

    def set_roulette_list(self, entries: list) -> None:
        """ルーレット一覧を更新する。

        Args:
            entries: list of dicts with keys:
                - 'id': str
                - 'label': str (表示名)
                - 'active': bool
                - 'visible': bool
        """
        # 既存行をクリア
        for row in self._roulette_rows.values():
            self._roulette_list_layout.removeWidget(row)
            row.deleteLater()
        self._roulette_rows.clear()

        total = len(entries)
        for entry in entries:
            rid = entry["id"]
            row = self._make_roulette_row(entry, total_count=total)
            self._roulette_list_layout.addWidget(row)
            self._roulette_rows[rid] = row

    def _make_roulette_row(self, entry: dict, *, total_count: int = 2) -> QWidget:
        """ルーレット1件の行ウィジェットを作成する。"""
        rid = entry["id"]
        is_active = entry["active"]
        is_visible = entry.get("visible", True)
        label_text = entry.get("label", rid)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        # i423: アクティブ時は "▶ " プレフィックスで編集対象を明示
        btn_label = f"▶ {label_text}" if is_active else label_text
        name_btn = QPushButton(btn_label)
        name_btn.setFont(QFont("Meiryo", 9))
        name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_active:
            name_btn.setStyleSheet(
                f"QPushButton {{ background-color: {self._design.accent}; color: {self._design.text};"
                f" border: none; border-radius: 4px; padding: 4px 8px; text-align: left; }}"
                f"QPushButton:hover {{ opacity: 0.8; }}"
            )
            # i423: アクティブ行には現在の役割をツールチップで明示
            name_btn.setToolTip("現在の編集対象\nクリックで再選択")
        else:
            name_btn.setStyleSheet(
                f"QPushButton {{ background-color: {self._design.separator}; color: {self._design.text};"
                f" border: none; border-radius: 4px; padding: 4px 8px; text-align: left; }}"
                f"QPushButton:hover {{ background-color: {self._design.accent}; }}"
            )
            # i423: 非アクティブ行には切替操作をツールチップで案内
            name_btn.setToolTip("クリックで編集対象を切り替え")
        name_btn.clicked.connect(lambda checked=False, r=rid: self.roulette_activate_requested.emit(r))
        row_layout.addWidget(name_btn, stretch=1)

        # 表示/非表示トグル
        vis_btn = QPushButton("👁" if is_visible else "🚫")
        vis_btn.setFont(QFont("Meiryo", 9))
        vis_btn.setFixedSize(28, 28)
        vis_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        vis_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self._design.separator}; color: {self._design.text};"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: {self._design.accent}; }}"
        )
        # i423: 現在状態に合わせたツールチップで操作結果を案内
        vis_btn.setToolTip("表示中 → クリックで非表示" if is_visible else "非表示 → クリックで表示")
        current_visible = is_visible
        vis_btn.clicked.connect(
            lambda checked=False, r=rid, b=vis_btn, cv=current_visible:
            self._on_vis_btn_clicked(r, b, cv)
        )
        row_layout.addWidget(vis_btn)

        # i338: 削除ボタン（最後の1個は無効）
        del_btn = QPushButton("✕")
        del_btn.setFont(QFont("Meiryo", 9))
        del_btn.setFixedSize(28, 28)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QPushButton {{ background-color: {self._design.separator}; color: {self._design.text};"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: #E53935; color: #FFFFFF; }}"
            f"QPushButton:disabled {{ opacity: 0.3; }}"
        )
        del_btn.setToolTip("このルーレットを削除")
        del_btn.setEnabled(total_count > 1)
        del_btn.clicked.connect(lambda checked=False, r=rid: self.roulette_delete_requested.emit(r))
        row_layout.addWidget(del_btn)

        return row

    def _on_vis_btn_clicked(self, roulette_id: str, btn: QPushButton, current_visible: bool):
        """表示/非表示ボタンのクリック処理。"""
        new_visible = not current_visible
        btn.setText("👁" if new_visible else "🚫")
        # i423: ツールチップも切替後の状態に更新する
        btn.setToolTip("表示中 → クリックで非表示" if new_visible else "非表示 → クリックで表示")
        # ボタンのクロージャの cv を更新するため、clicked を再接続する
        try:
            btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        btn.clicked.connect(
            lambda checked=False, r=roulette_id, b=btn, cv=new_visible:
            self._on_vis_btn_clicked(r, b, cv)
        )
        self.roulette_visibility_toggled.emit(roulette_id, new_visible)

    def update_active_roulette(self, active_id: str) -> None:
        """アクティブなルーレット ID だけを更新（一覧全再構築を避ける）。

        実際には set_roulette_list を呼んで全再構築する。
        """
        # 現在の実装では set_roulette_list で全更新する方が簡単なため、
        # 呼び出し元から set_roulette_list を使ってもらう。
        pass

    def set_apply_to_all(self, value: bool) -> None:
        """一括適用チェック状態を外部から同期する（シグナルなし）。"""
        self._apply_all_cb.blockSignals(True)
        self._apply_all_cb.setChecked(value)
        self._apply_all_cb.blockSignals(False)

    def update_design(self, design: DesignSettings):
        self._design = design
        self.setStyleSheet(f"background-color: {design.panel};")
        self._drag_bar.update_design(design)
        self._scroll.setStyleSheet(f"background-color: {design.panel};")
        self._apply_all_cb.setStyleSheet(f"color: {design.text};")
        self._roulette_title_label.setStyleSheet(f"color: {design.text};")
        _pkg_icon_style = (
            f"QPushButton {{"
            f"  background-color: transparent; color: {design.text};"
            f"  border: none; padding: 1px 4px;"
            f"  font-size: 10pt; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ color: {design.accent}; }}"
        )
        self._pkg_export_btn.setStyleSheet(_pkg_icon_style)
        self._pkg_import_btn.setStyleSheet(_pkg_icon_style)

    # ----------------------------------------------------------------
    #  イベント
    # ----------------------------------------------------------------

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.geometry_changed.emit()

    def mousePressEvent(self, event):
        # クリックは吸収。ドラッグはドラッグバーからのみ。
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()
