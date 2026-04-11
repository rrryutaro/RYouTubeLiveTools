"""
PySide6 プロトタイプ — メインウィンドウ

責務:
  - frameless ウィンドウ管理（タイトルバーなし、エッジリサイズ、背景ドラッグ移動）
  - 独立パネル群の土台（RoulettePanel + SettingsPanel）
  - 既存設定の読み込みと各コンポーネントへの配布
  - キーボードショートカット
  - コンテキストメニュー
  - コンポーネント間のオーケストレーション

パネル構成:
  RoulettePanel  — ルーレット描画・操作を一体化した独立パネル
  SettingsPanel  — 項目設定・表示設定を編集するパネル
  各パネルは独立に移動・リサイズ可能。
  片方のパネル操作がもう片方の geometry を変更しない。

将来のマルチルーレット化:
  RoulettePanel を複数インスタンス化し、
  SettingsPanel は「アクティブな RoulettePanel」を編集する形にする。
  メインウィンドウは透過最大化してパネルをディスプレイ内に自由配置する。
"""

import re

from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRect, QObject, QEvent
from PySide6.QtGui import QScreen, QMouseEvent, QCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QMenu, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
    QSlider, QScrollBar, QAbstractItemView,
)

import os

from bridge import (
    SIZE_PROFILES, MIN_W, MIN_H, VERSION,
    DesignSettings, DESIGN_PRESET_NAMES, DESIGN_PRESETS,
    DesignPresetManager,
    load_config, load_design,
    load_all_item_entries, load_app_settings,
    build_segments_from_config, build_segments_from_entries,
    save_config, save_item_entries,
    get_pattern_names, get_current_pattern_name,
    set_current_pattern, add_pattern, delete_pattern,
)
from config_utils import BASE_DIR, INSTANCE_NUM
from app_settings import AppSettings
from win_history import WinHistory
from replay_manager_pyside6 import ReplayManager
from roulette_panel import RoulettePanel
from roulette_context import RouletteContext
from roulette_manager import RouletteManager
from roulette_actions import (
    RouletteAction, ActionOrigin, LastSpinResult,
    AddRoulette, RemoveRoulette, SetActiveRoulette,
    SpinRoulette, UpdateItemEntries, UpdateSettings,
    BranchOnWinner,
)
from roulette_action_recorder import ActionRecorder
from roulette_macro_session import MacroPlaybackSession
from settings_panel import SettingsPanel, ItemPanel, ManagePanel, _PanelGrip
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME
from sound_manager import SoundManager
from dark_theme import get_app_stylesheet, resolve_theme_mode


class _PanelInputFilter(QObject):
    """i278/i279/i280: メインウィンドウ内パネル用の統一マウスフィルタ。

    QApplication 全体に install され、対象パネル (settings / item / manage)
    およびその子ウィジェットへ届く左マウス操作を以下のルールで扱う。

    i280 改訂のポイント:
    - **非アクティブパネル上の UI クリックを 1 回で通す**: press を吸収せず、
      focus を立てた上で素通しする。これによりインアクティブパネル上の
      ボタン/チェック/コンボ等が初回クリックでそのまま動作する。
    - **リサイズ判定をドラッグより優先**: panel の右端 / 下端 / 右下角の
      RESIZE_EDGE 内で press された場合、ドラッグ昇格判定に入る前に
      リサイズトラッキングを開始する。
    - **カーソルプレビュー**: press されていない状態で対象パネルの
      右端 / 下端 / 角にホバーしたら resize cursor を表示する。
    - **ルーレットパネルはフィルタ非対象**: ルーレットパネルは自前の
      mousePressEvent に内蔵のドラッグ/クリック判定があるため、フィルタは
      触らない (focus_only 登録もしない)。

    各イベントの扱い:

    1. **MouseMove (no button)**: press 中でない時は、対象パネル背景上に
       いる場合のみ resize cursor のプレビューを行う。

    2. **MouseButtonPress**:
       a. 対象パネルでなければ素通し。
       b. _PanelGrip 上ならフィルタは触らない (grip 自身が処理)。
       c. 入力系 (QLineEdit/QSpinBox 等) なら focus だけ立てて素通し。
       d. 右端 / 下端 / 角にいたら、focus を立ててリサイズトラッキング開始
          (press は吸収して return True)。
       e. それ以外は focus を立てて、ドラッグ追跡を開始しつつ press を
          素通し (return False)。

    3. **MouseMove (button held)**:
       - リサイズ中: 開始時の geometry + delta から resize() を適用。
       - ドラッグ追跡中: 移動量が DRAG_THRESHOLD を超えたら、
         元 target へ画面外 release を sendEvent して press 状態をキャンセル
         し、popup を hide してパネル移動へ昇格する。

    4. **MouseButtonRelease**:
       - リサイズ中: トラッキング終了。
       - ドラッグ済: 吸収してクリックを発火させない。
       - ドラッグ未昇格: 素通し → 元のウィジェットの通常クリック動作。

    5. **テキスト入力系**: QLineEdit / QPlainTextEdit / QSpinBox 等は
       「press + 移動」を本来動作で使うため、ドラッグ追跡対象外。
       focus は更新するが、press はそのまま素通しする。

    6. **_PanelGrip**: パネル右下の corner グリップ。自前のドラッグ resize
       を持つため、フィルタは press / move / release のいずれも触らない。
    """

    DRAG_THRESHOLD = 6  # manhattan px
    RESIZE_EDGE = 6     # px from right/bottom for resize hit zone

    # ドラッグ追跡から除外する widget 型
    EXEMPT_TYPES = (
        QLineEdit, QPlainTextEdit, QTextEdit,
        QSpinBox, QDoubleSpinBox,
        QSlider, QScrollBar,
        QAbstractItemView,
    )

    def __init__(self, main_window):
        super().__init__(main_window)
        self._mw = main_window
        self._drag_panels: list[QWidget] = []
        self._focus_only_panels: list[QWidget] = []
        # press 追跡状態
        self._press_panel: QWidget | None = None
        self._press_global = QPoint()
        self._press_panel_pos = QPoint()
        self._press_target: QWidget | None = None
        self._dragging = False
        self._cancelling = False  # 同期 sendEvent の再入防止
        # i280: リサイズトラッキング状態
        self._resize_panel: QWidget | None = None
        self._resize_edge = ""  # 'right' / 'bottom' / 'corner' / ''
        self._resize_start_global = QPoint()
        self._resize_start_geom = None  # QRect
        # i282: 現在 push 中の override cursor の種類
        self._active_override_edge = ""

    def set_panels(self, drag_panels, focus_only_panels=()):
        """監視対象パネルを設定する。

        Args:
            drag_panels: drag-from-anywhere + focus-first-click 対象。
            focus_only_panels: focus-first-click のみ対象 (i280 では空でよい)。
        """
        self._drag_panels = list(drag_panels)
        self._focus_only_panels = list(focus_only_panels)
        # i280/i281: 対象パネル+全子ウィジェットで mouseTracking を有効化。
        # これによりボタン/コンボ/スクロール等の上にホバーしている時も
        # MouseMove (no button) が発火し、フィルタが resize cursor を
        # プレビューできる (非アクティブパネルでも有効)。
        for p in self._drag_panels:
            self._enable_tracking_recursive(p)

    @staticmethod
    def _enable_tracking_recursive(widget):
        """widget とその全子孫 QWidget で setMouseTracking(True) を呼ぶ。"""
        try:
            widget.setMouseTracking(True)
        except Exception:
            pass
        try:
            for child in widget.findChildren(QWidget):
                try:
                    child.setMouseTracking(True)
                except Exception:
                    pass
        except Exception:
            pass

    def _find_panel(self, obj) -> tuple[QWidget | None, bool]:
        """obj が監視対象パネルか祖先かを判定。

        Returns:
            (panel, has_drag) — panel が見つからなければ (None, False)。
            has_drag は drag-from-anywhere を許可するかどうか。
        """
        if not isinstance(obj, QWidget):
            return None, False
        w = obj
        depth = 0
        while w is not None and depth < 64:
            if w in self._drag_panels:
                return w, True
            if w in self._focus_only_panels:
                return w, False
            w = w.parentWidget()
            depth += 1
        return None, False

    def _is_exempt(self, obj) -> bool:
        """obj が drag 追跡から除外されるべき型か判定する。

        obj 自身またはその直近の祖先 (3 段) のいずれかが除外型なら True。
        QComboBox の中の QLineEdit などもケアする。
        """
        if isinstance(obj, self.EXEMPT_TYPES):
            return True
        p = obj
        for _ in range(3):
            if p is None:
                break
            if isinstance(p, self.EXEMPT_TYPES):
                return True
            p = p.parentWidget()
        return False

    def _is_grip(self, obj) -> bool:
        """obj 自身またはその祖先に _PanelGrip があるか判定する。

        i280: パネル右下の grip 上での press はフィルタを介さず grip 自身の
        mousePressEvent に処理させたい (corner サイズ変更用)。
        """
        p = obj
        for _ in range(3):
            if p is None:
                break
            if isinstance(p, _PanelGrip):
                return True
            p = p.parentWidget()
        return False

    def _hit_resize_edge(self, panel, global_pos) -> str:
        """global_pos が panel の右端 / 下端 / 角の resize 領域にいるか判定。

        Returns:
            'right' / 'bottom' / 'corner' / '' (none)
        """
        try:
            local = panel.mapFromGlobal(global_pos)
        except Exception:
            return ""
        x = local.x()
        y = local.y()
        w = panel.width()
        h = panel.height()
        if x < 0 or y < 0 or x >= w or y >= h:
            return ""
        in_right = x >= w - self.RESIZE_EDGE
        in_bottom = y >= h - self.RESIZE_EDGE
        if in_right and in_bottom:
            return "corner"
        if in_right:
            return "right"
        if in_bottom:
            return "bottom"
        return ""

    def _update_override_cursor(self, edge: str):
        """edge に応じて QApplication の override cursor を push/pop する。

        i282: panel.setCursor() は子ウィジェット (QScrollBar, QPushButton 等)
        が自前で setCursor 済みの場合に上書きできず、非アクティブパネルの
        外枠ホバー時にカーソルがアロー表示のままになる不具合の原因だった。
        QApplication.setOverrideCursor は全ウィジェットのカーソルを強制的に
        上書きするため、子ウィジェットの上でも resize cursor が確実に出る。

        edge:
            'right' / 'bottom' / 'corner' / '' (空 = 解除)
        """
        current = getattr(self, "_active_override_edge", "")
        if edge == current:
            return  # 変化なし
        # 直前の override を解除
        if current:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self._active_override_edge = ""
        # 新しい override を push
        if edge:
            shape_map = {
                "right": Qt.CursorShape.SizeHorCursor,
                "bottom": Qt.CursorShape.SizeVerCursor,
                "corner": Qt.CursorShape.SizeFDiagCursor,
            }
            try:
                QApplication.setOverrideCursor(QCursor(shape_map[edge]))
                self._active_override_edge = edge
            except Exception:
                pass

    def _apply_resize(self, global_pos):
        """進行中の resize に対し、現在マウス位置から panel をリサイズする。"""
        panel = self._resize_panel
        edge = self._resize_edge
        geom = self._resize_start_geom
        if panel is None or geom is None:
            return
        delta = global_pos - self._resize_start_global
        new_w = geom.width()
        new_h = geom.height()
        min_w = panel.minimumWidth() or 200
        min_h = panel.minimumHeight() or 200
        if edge in ("right", "corner"):
            new_w = max(min_w, geom.width() + delta.x())
        if edge in ("bottom", "corner"):
            new_h = max(min_h, geom.height() + delta.y())
        # 親領域内にクランプ
        parent = panel.parentWidget()
        if parent is not None:
            max_w = max(min_w, parent.width() - geom.x())
            max_h = max(min_h, parent.height() - geom.y())
            new_w = min(new_w, max_w)
            new_h = min(new_h, max_h)
        panel.resize(new_w, new_h)

    def _close_active_popup(self):
        """直前 press でコントロールが開いた popup (combobox 等) を閉じる。

        i279: アクティブパネル上のコンボボックスからドラッグ開始した時、
        ドラッグ移行直後にもポップアップが浮いたまま残る不具合を防ぐ。
        QApplication.activePopupWidget() で取得できれば hide する。
        加えて、target 自体が QComboBox 系なら hidePopup() も呼ぶ。
        """
        try:
            popup = QApplication.activePopupWidget()
            if popup is not None:
                popup.hide()
        except Exception:
            pass
        try:
            target = self._press_target
            if target is not None:
                # target 自身またはその祖先で hidePopup を持つものを閉じる
                w = target
                for _ in range(4):
                    if w is None:
                        break
                    if hasattr(w, "hidePopup"):
                        try:
                            w.hidePopup()
                        except Exception:
                            pass
                        break
                    w = w.parentWidget()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if self._cancelling:
            return False

        et = event.type()
        # マウス系 3 種以外は早期 return
        if et not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        ):
            return False

        # ============================================================
        # MouseMove (no button) — i280/i282: resize cursor のホバープレビュー
        # ============================================================
        if (et == QEvent.Type.MouseMove
                and self._press_panel is None
                and self._resize_panel is None):
            try:
                if event.buttons() != Qt.MouseButton.NoButton:
                    return False
            except Exception:
                return False
            panel, has_drag = self._find_panel(obj)
            if panel is None or not has_drag:
                # 対象パネル外: 直前の override があれば解除
                self._update_override_cursor("")
                return False
            # i282: grip 上は grip 自身の cursor (SizeFDiagCursor) に任せる
            if self._is_grip(obj):
                self._update_override_cursor("")
                return False
            try:
                global_pos = event.globalPosition().toPoint()
            except Exception:
                return False
            # i282: exempt (QScrollBar / QLineEdit / QSpinBox 等) の上でも
            # resize edge にいるなら override cursor を出す。これがないと
            # スクロールバーが右端に貼り付いている設定パネルで非アクティブ時
            # の resize cursor が表示されない。
            edge = self._hit_resize_edge(panel, global_pos)
            self._update_override_cursor(edge)
            return False

        # press 状態が無いときは Press 以外は全部スルー
        if (self._press_panel is None
                and self._resize_panel is None
                and et != QEvent.Type.MouseButtonPress):
            return False

        # ============================================================
        # MouseButtonPress
        # ============================================================
        if et == QEvent.Type.MouseButtonPress:
            try:
                if event.button() != Qt.MouseButton.LeftButton:
                    return False
            except Exception:
                return False

            panel, has_drag = self._find_panel(obj)
            if panel is None:
                return False

            # i280: _PanelGrip 上は完全にフィルタを抜ける (grip 自身が処理)
            if self._is_grip(obj):
                return False

            is_focused = self._mw._is_panel_focused(panel)

            # focus-only パネルは focus だけ更新して素通し
            if not has_drag:
                if not is_focused:
                    self._mw._set_panel_focused(panel)
                return False

            # i280: リサイズ判定 (ドラッグより優先)
            try:
                global_pos = event.globalPosition().toPoint()
            except Exception:
                global_pos = None
            if global_pos is not None:
                edge = self._hit_resize_edge(panel, global_pos)
                if edge:
                    if not is_focused:
                        self._mw._set_panel_focused(panel)
                    self._resize_panel = panel
                    self._resize_edge = edge
                    self._resize_start_global = global_pos
                    self._resize_start_geom = panel.geometry()
                    return True  # press を吸収

            # 入力系: focus を立てて素通し (press は本来動作)
            if self._is_exempt(obj):
                if not is_focused:
                    self._mw._set_panel_focused(panel)
                return False

            # i280: drag tracking — focus + press 素通し
            # 非アクティブでも press は吸収しない。これにより、ボタンや
            # コンボ等の UI コントロールが「単純クリック」で初回から
            # 通常動作する。ドラッグへ昇格した際は別途 press キャンセルを送る。
            if not is_focused:
                self._mw._set_panel_focused(panel)
            self._press_panel = panel
            self._press_global = event.globalPosition().toPoint()
            self._press_panel_pos = panel.pos()
            self._press_target = obj
            self._dragging = False
            return False  # press を素通し

        # ============================================================
        # MouseMove (button held) — resize / drag
        # ============================================================
        if et == QEvent.Type.MouseMove:
            # i280: リサイズ進行中
            if self._resize_panel is not None:
                try:
                    global_pos = event.globalPosition().toPoint()
                except Exception:
                    return True
                self._apply_resize(global_pos)
                return True

            if self._press_panel is None:
                return False
            try:
                cur_global = event.globalPosition().toPoint()
            except Exception:
                return False
            delta = cur_global - self._press_global
            if not self._dragging:
                if (abs(delta.x()) + abs(delta.y())) > self.DRAG_THRESHOLD:
                    self._dragging = True
                    # 元 press をキャンセルし、popup を閉じる
                    target = self._press_target
                    if target is not None:
                        self._cancelling = True
                        try:
                            cancel_ev = QMouseEvent(
                                QEvent.Type.MouseButtonRelease,
                                QPointF(-1000.0, -1000.0),
                                event.globalPosition(),
                                Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier,
                            )
                            QApplication.sendEvent(target, cancel_ev)
                        except Exception:
                            pass
                        finally:
                            self._cancelling = False
                    self._close_active_popup()
            if self._dragging:
                panel = self._press_panel
                new_x = self._press_panel_pos.x() + delta.x()
                new_y = self._press_panel_pos.y() + delta.y()
                parent = panel.parentWidget()
                if parent is not None:
                    pw = panel.width()
                    ph = panel.height()
                    new_x = max(0, min(new_x, max(0, parent.width() - pw)))
                    new_y = max(0, min(new_y, max(0, parent.height() - ph)))
                panel.move(new_x, new_y)
                return True
            return False

        # ============================================================
        # MouseButtonRelease
        # ============================================================
        if et == QEvent.Type.MouseButtonRelease:
            try:
                if event.button() != Qt.MouseButton.LeftButton:
                    return False
            except Exception:
                return False

            # i280: リサイズ終了
            if self._resize_panel is not None:
                self._resize_panel = None
                self._resize_edge = ""
                self._resize_start_geom = None
                return True

            if self._press_panel is None:
                return False
            was_dragging = self._dragging
            self._press_panel = None
            self._press_global = QPoint()
            self._press_panel_pos = QPoint()
            self._press_target = None
            self._dragging = False
            if was_dragging:
                # ドラッグ後の release はクリックを発火させない
                return True
            return False  # 素通し → 通常クリックとして発火

        return False


class MainWindow(QMainWindow):
    """PySide6 プロトタイプのメインウィンドウ。

    独立パネル群（RoulettePanel, SettingsPanel）を載せる土台。
    パネル同士は互いの geometry に干渉しない。
    """

    # エッジリサイズ定数
    _EDGE_SIZE = 6
    _EDGE_NONE = 0
    _EDGE_RIGHT = 1
    _EDGE_BOTTOM = 2
    _EDGE_CORNER = 3  # right + bottom

    def __init__(self):
        super().__init__()

        # --- frameless ウィンドウ（フラグは _apply_window_flags で設定） ---
        self.setMouseTracking(True)
        # 初期化中のフラグ（debounce save 等を init 中に発火させない）
        self._init_complete = False

        # --- 既存設定の読み込み ---
        self._config = load_config()
        self._settings = load_app_settings(self._config)
        self._design = load_design(self._config)

        # --- デザインプリセットマネージャー ---
        self._preset_mgr = DesignPresetManager.from_dict(
            self._config.get("design_presets", {})
        )
        self._design_editor = None  # DesignEditorDialog (遅延生成)
        self._graph_dialog = None   # GraphDialog (遅延生成)
        self._replay_dialog = None  # ReplayDialog (遅延生成)

        # --- ルーレットマネージャー・パネル一覧 ---
        self._manager = RouletteManager(parent=self)
        self._manager.active_changed.connect(self._on_active_changed)
        self._panels: list[QWidget] = []

        self.setWindowTitle(self._base_window_title())
        # メインウィンドウ最小サイズ:
        # ルーレットパネル最小描画領域 (約 272x272) ＋ ポインター描画余白を
        # 確保するため 320x320 に設定する。これより小さくすると描画破綻が
        # 発生する。v0.4.4 とほぼ同等で、過剰に大きくはしていない。
        self.setMinimumSize(320, 320)

        # frameless + always_on_top
        self._apply_window_flags()

        # 透過モード基盤を常時有効化する。
        # WA_TranslucentBackground は **show 前に必ず立てておく** のが
        # Windows 上で安定動作する条件で、show 後に setAttribute だけで
        # 切り替えるのは native window 再生成を伴うため不安定になる。
        # 実際の見た目の透過/不透明は centralWidget の背景塗りで切り替える。
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_NoSystemBackground, True
        )
        self.setStyleSheet(
            "QMainWindow { background: transparent; }"
        )

        # サイズプロファイル（保存値が無い場合のデフォルト）
        prof_idx = min(self._settings.profile_idx, len(SIZE_PROFILES) - 1)
        _, default_w, default_h = SIZE_PROFILES[prof_idx]
        self._wheel_base_w = default_w
        self._wheel_base_h = default_h

        # ウィンドウサイズ・位置の復元
        self._restore_window_geometry(default_w, default_h)

        # --- 中央ウィジェット（レイアウトなし — パネルを手動配置） ---
        # 注意: centralWidget には WA_TranslucentBackground を立てない。
        # 立てると stylesheet の background-color が描画されなくなり、
        # 「不透明モード」のときに solid bg が出なくなる。
        # QMainWindow 側だけ WA_TranslucentBackground=True にしてあるので、
        # centralWidget の bg を transparent にすればウィンドウ全体が透ける。
        central = QWidget()
        central.setAutoFillBackground(False)
        central.setMouseTracking(True)
        self.setCentralWidget(central)
        self._apply_central_background(self._settings.window_transparent)

        # --- ダークテーマ適用 ---
        self._apply_app_theme(self._design)

        # ============================================================
        #  アクション記録バッファ
        # ============================================================

        self._recorder = ActionRecorder()
        self._macro_session = MacroPlaybackSession()

        # ============================================================
        #  マクロ自動進行状態（spin 完了待ち → 自動再開）
        # ============================================================

        self._macro_auto_advancing: bool = False
        self._macro_waiting_spin: bool = False
        self._macro_waiting_roulette_id: str | None = None
        self._macro_viewer = None  # MacroActionViewer 参照（表示中のみ）

        # 直前当選結果（manual / macro 共通）
        self._last_spin_result: LastSpinResult | None = None

        # ============================================================
        #  サウンド
        # ============================================================

        self._sound = SoundManager()
        self._log_autosave_path = os.path.join(BASE_DIR, "roulette_autosave_log.json")
        self._win_history = WinHistory(
            os.path.join(BASE_DIR, "roulette_win_history.json")
        )
        self._win_history.load()
        self._replay_mgr = ReplayManager(
            os.path.join(BASE_DIR, "roulette_replay.json"),
            max_count=self._settings.replay_max_count,
            parent=self,
        )
        self._replay_mgr.load()
        self._replay_mgr.playback_finished.connect(self._on_replay_finished)
        self._sound.set_tick_volume(self._settings.tick_volume / 100.0)
        self._sound.set_win_volume(self._settings.win_volume / 100.0)
        self._sound.set_tick_pattern(self._settings.tick_pattern)
        self._sound.set_win_pattern(self._settings.win_pattern)
        if self._settings.tick_custom_file:
            self._sound.load_tick_custom(self._settings.tick_custom_file)
        if self._settings.win_custom_file:
            self._sound.load_win_custom(self._settings.win_custom_file)

        # ============================================================
        #  ルーレットパネル（独立パネル）
        # ============================================================

        self._roulette_panel = self._create_roulette("default", central)

        # ログ履歴復元
        self._roulette_panel.wheel.load_log(self._log_autosave_path)

        # ============================================================
        #  項目設定パネル（メインウィンドウ内の内部パネル / i277）
        # ============================================================

        # i277: SettingsPanel は centralWidget の child widget。
        # OBS が取り込めるようにするには別ウィンドウではなく
        # メインウィンドウの内部要素である必要がある。
        self._settings_panel = SettingsPanel(
            self._active_context.item_entries, self._settings, self._design,
            pattern_names=get_pattern_names(self._config),
            current_pattern=get_current_pattern_name(self._config),
            parent=central,
        )
        self._settings_panel._floating = False
        self._settings_panel_visible = False
        self._settings_panel.hide()

        self._settings_panel.spin_requested.connect(self._start_spin)
        self._settings_panel.preset_changed.connect(self._on_preset_changed)
        self._settings_panel.setting_changed.connect(self._on_setting_changed)
        self._settings_panel.item_entries_changed.connect(
            self._on_item_entries_changed
        )
        self._settings_panel.pattern_switched.connect(self._on_pattern_switched)
        self._settings_panel.pattern_added.connect(self._on_pattern_added)
        self._settings_panel.pattern_deleted.connect(self._on_pattern_deleted)
        self._settings_panel.preview_tick_requested.connect(self._on_preview_tick)
        self._settings_panel.preview_win_requested.connect(self._on_preview_win)
        self._settings_panel.custom_tick_file_changed.connect(self._on_custom_tick_file)
        self._settings_panel.custom_win_file_changed.connect(self._on_custom_win_file)
        self._settings_panel.log_clear_requested.connect(self._on_log_clear)
        self._settings_panel.shuffle_once_requested.connect(self._on_shuffle_once)
        # i284: 並びリセット / 項目一括リセット
        self._settings_panel.arrangement_reset_requested.connect(
            self._on_arrangement_reset
        )
        self._settings_panel.items_reset_requested.connect(
            self._on_items_reset
        )
        self._settings_panel.pattern_export_requested.connect(self._on_pattern_export)
        self._settings_panel.pattern_import_requested.connect(self._on_pattern_import)
        self._settings_panel.log_export_requested.connect(self._on_log_export)
        self._settings_panel.design_editor_requested.connect(
            self._open_design_editor
        )
        self._settings_panel.graph_requested.connect(self._open_graph)
        self._settings_panel.replay_play_requested.connect(
            lambda: self._start_replay(0)
        )
        self._settings_panel.replay_stop_requested.connect(self._cancel_replay)
        self._settings_panel.replay_manager_requested.connect(
            self._open_replay_manager
        )

        # i277: SettingsPanel は内部パネルへ戻したため、ここでは事前 restore
        # を行わない (`_restore_all_panel_geometries` で 3 パネルまとめて
        # 復元する)。

        # --- grip / ctrl_box の初期状態適用 ---
        if not self._settings.grip_visible:
            self._apply_grip_visible(False)
        if not self._settings.ctrl_box_visible:
            self._apply_ctrl_box_visible(False)

        # --- パネル位置の保存を間引くためのデバウンスタイマー ---
        # geometry_changed が連続発火しても、最後の値だけを 500ms 後に書き出す
        self._panel_save_timer = QTimer(self)
        self._panel_save_timer.setSingleShot(True)
        self._panel_save_timer.setInterval(500)
        self._panel_save_timer.timeout.connect(self._persist_panel_positions)

        # --- パネル一覧（Z オーダー管理対象）に SettingsPanel を追加 ---
        self._panels.append(self._settings_panel)
        self._settings_panel.geometry_changed.connect(
            lambda: self._bring_panel_to_front(self._settings_panel)
        )
        self._settings_panel.geometry_changed.connect(
            self._panel_save_timer.start
        )

        # --- 項目パネル（メインウィンドウ内の内部パネル / i277）---
        # SettingsPanel から項目セクションとパターン (グループ) セクションを
        # 取り外し、ItemPanel に載せ替える。**centralWidget の child widget**。
        items_widget = self._settings_panel.pop_items_section()
        pattern_widget = self._settings_panel.pop_pattern_section()
        self._item_panel = ItemPanel(
            self._design,
            items_widget=items_widget,
            pattern_widget=pattern_widget,
            settings_panel=self._settings_panel,
            parent=central,
        )
        self._item_panel.hide()  # restore で表示判定する
        self._panels.append(self._item_panel)
        self._item_panel.geometry_changed.connect(
            lambda: self._bring_panel_to_front(self._item_panel)
        )
        self._item_panel.geometry_changed.connect(
            self._panel_save_timer.start
        )

        # --- 全体管理パネル (F1) — 内部パネル ---
        self._manage_panel = ManagePanel(
            self._design,
            items_visible=self._settings.items_panel_visible,
            settings_visible=self._settings.settings_panel_visible,
            parent=central,
        )
        self._manage_panel.items_panel_toggled.connect(
            self._on_manage_items_toggled
        )
        self._manage_panel.settings_panel_toggled.connect(
            self._on_manage_settings_toggled
        )
        self._manage_panel.reset_positions_requested.connect(
            self._reset_panel_positions
        )
        self._manage_panel.geometry_changed.connect(
            self._panel_save_timer.start
        )
        # i279: 親 (centralWidget) が show されると child は既定で
        # visible になるため、ここで明示的に hide しておく。表示は
        # `_restore_all_panel_geometries` で manage_panel_visible に
        # 従って判断する。これを忘れると、保存値が False でも起動時に
        # 管理パネルだけが表示される不具合になる。
        self._manage_panel.hide()
        self._manage_panel_visible = False

        # i278/i280: 統一マウスフィルタ (focus + drag + resize) を
        # QApplication 全体にインストール。
        # i280: ルーレットパネルは自前の mousePressEvent に内蔵の
        # ドラッグ/クリック判定があるため、フィルタの drag/focus 対象には
        # 含めない (focus_only_panels も空)。
        self._focused_panel = self._active_panel
        self._panel_input_filter = _PanelInputFilter(self)
        self._panel_input_filter.set_panels(
            drag_panels=[
                self._settings_panel,
                self._item_panel,
                self._manage_panel,
            ],
            focus_only_panels=[],
        )
        QApplication.instance().installEventFilter(self._panel_input_filter)

        # i279: 復元は showEvent (初回) で行う。
        # __init__ 時点では centralWidget の layout が未活性で、stale な
        # 既定サイズ (640x480) を返すため、ユーザー保存値が小さく
        # クランプされる事故が起きていた。
        # ここでは復元せず、各パネルは hide() のままにしておく。
        self._panels_restored = False

        # --- 初期勝利数表示 ---
        self._update_win_counts()
        self._settings_panel.set_replay_count(self._replay_mgr.count())

        # --- ドラッグ・リサイズ状態 ---
        self._dragging_window = False
        self._window_drag_start = QPoint()
        self._window_drag_start_pos = QPoint()
        self._resizing_edge = self._EDGE_NONE
        self._resize_start = QPoint()
        self._resize_start_rect = QRect()

        # --- コンテキストメニュー ---
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # --- OS テーマ変更の定期監視 (system モード用) ---
        self._last_os_theme = resolve_theme_mode("system")
        self._os_theme_timer = QTimer(self)
        self._os_theme_timer.setInterval(3000)  # 3秒ごと
        self._os_theme_timer.timeout.connect(self._check_os_theme_change)
        if self._settings.theme_mode in ("system", "auto"):
            self._os_theme_timer.start()

        # 初期化完了フラグを立て、以後の geometry_changed で
        # _persist_panel_positions が走るようにする。
        self._init_complete = True

    # ================================================================
    #  アクティブルーレット参照（manager 経由）
    # ================================================================

    @property
    def _active_context(self) -> RouletteContext:
        """アクティブな RouletteContext を返す。"""
        return self._manager.active

    @property
    def _active_panel(self) -> RoulettePanel:
        """アクティブな RoulettePanel を返す。"""
        return self._manager.active.panel

    @property
    def _active_entries(self) -> list:
        """アクティブなルーレットの item_entries を返す。"""
        return self._manager.active.item_entries

    @property
    def _active_segments(self) -> list:
        """アクティブなルーレットの segments を返す。"""
        return self._manager.active.segments

    def _sync_settings_to_active(self):
        """SettingsPanel の表示をアクティブコンテキストに同期する。"""
        self._settings_panel.set_active_entries(self._active_entries)

    # ================================================================
    #  アクションディスパッチャ（マクロ向け共通入口）
    # ================================================================

    def apply_action(self, action: RouletteAction, *,
                     origin: ActionOrigin = ActionOrigin.USER) -> bool:
        """アクションを実行する。

        マクロ記録・再生の共通入口。
        USER 起点の成功アクションのみ recorder へ記録する。
        MACRO 起点の成功アクションは記録しない。

        Args:
            action: 実行するアクション。
            origin: 実行起点。デフォルトは USER。

        Returns:
            操作が成功したら True、失敗（制約違反等）なら False。
        """
        ok = self._dispatch_action(action)
        if ok and origin == ActionOrigin.USER:
            self._recorder.record(action)
            if self._recorder.is_recording:
                self._update_title_active_id()
        return ok

    def _dispatch_action(self, action: RouletteAction) -> bool:
        """アクションを各ハンドラへ振り分ける。"""
        if isinstance(action, AddRoulette):
            return self._add_new_roulette(activate=action.activate) is not None
        elif isinstance(action, RemoveRoulette):
            return self._remove_roulette(action.roulette_id)
        elif isinstance(action, SetActiveRoulette):
            old_id = self._manager.active_id
            self._set_active_roulette(action.roulette_id)
            return self._manager.active_id != old_id
        elif isinstance(action, SpinRoulette):
            return self._spin_by_action(action.roulette_id)
        elif isinstance(action, UpdateItemEntries):
            return self._update_items_by_action(
                action.roulette_id, list(action.entries),
            )
        elif isinstance(action, UpdateSettings):
            return self._update_setting_by_action(action.key, action.value)
        return False

    def _spin_by_action(self, roulette_id: str) -> bool:
        """アクション経由の spin 開始。

        Args:
            roulette_id: 対象 ID。空文字なら active を対象にする。

        Returns:
            spin を開始できたら True。
        """
        if roulette_id:
            ctx = self._manager.get(roulette_id)
        else:
            ctx = self._manager.active
        if ctx is None:
            return False
        panel = ctx.panel
        if panel.spin_ctrl.is_spinning:
            return False
        if self._replay_mgr.is_playing:
            return False
        # auto_shuffle: スピン前に項目順をランダム化してセグメント再構築
        if self._settings.auto_shuffle:
            import random
            entries = list(ctx.item_entries)
            random.shuffle(entries)
            ctx.item_entries = entries
            ctx.segments, _ = build_segments_from_entries(
                entries, self._config
            )
            panel.set_segments(ctx.segments)
        self._settings_panel.set_spinning(True)
        panel.start_spin()
        return True

    def _set_active_roulette(self, roulette_id: str):
        """アクティブなルーレットを切り替え、SettingsPanel を追従させる。

        将来の複数ルーレット切替の統一入口。
        manager の set_active → SettingsPanel 同期をまとめる。
        """
        old_id = self._manager.active_id
        self._manager.set_active(roulette_id)
        # set_active は同一 ID では何もしないので、
        # 実際に変わった場合のみ同期する
        if self._manager.active_id != old_id:
            self._sync_settings_to_active()

    def _on_active_changed(self, roulette_id: str):
        """manager の active_changed シグナルに応答する。

        manager.set_active() が外部から呼ばれた場合にも
        SettingsPanel が追従するようにする。
        """
        self._sync_settings_to_active()
        # 開発確認用: ウィンドウタイトルに active ID を反映
        self._update_title_active_id()

    def _base_window_title(self) -> str:
        """インスタンス番号を考慮した基本ウィンドウタイトルを返す。

        旧 v0.4.4 の `window_manager.py` と同じ規則:
          1個目          → "RRoulette"
          2個目以降      → "RRoulette #N"
        """
        if INSTANCE_NUM == 1:
            return "RRoulette"
        return f"RRoulette #{INSTANCE_NUM}"

    def _update_title_active_id(self):
        """ウィンドウタイトルに recording / playback 状態のみを反映する。

        v0.4.4 と同じく、通常時は `RRoulette` (または `RRoulette #N`) のみを
        表示する。開発確認用の active ID は冗長なので含めない。
        REC / PLAY は実操作で意味のある情報なので、状態がある場合だけ
        末尾に付加する。
        """
        base = self._base_window_title()
        parts = []
        if self._recorder.is_recording:
            parts.append(f"REC:{self._recorder.count}")
        if self._macro_session.total_count > 0:
            play_label = f"PLAY:{self._macro_session.current_index}/{self._macro_session.total_count}"
            if self._macro_waiting_spin:
                play_label += " WAIT"
            elif self._macro_auto_advancing:
                play_label += " AUTO"
            parts.append(play_label)
        if parts:
            self.setWindowTitle(f"{base} [{', '.join(parts)}]")
        else:
            self.setWindowTitle(base)

    def _toggle_recording(self):
        """開発確認用: recording ON/OFF を切り替える。"""
        if self._recorder.is_recording:
            self._recorder.stop()
        else:
            self._recorder.clear()
            self._recorder.start()
        self._update_title_active_id()

    def _dump_recording(self):
        """開発確認用: 記録済みアクションを標準出力にダンプする。"""
        from roulette_action_codec import action_to_dict
        actions = self._recorder.snapshot()
        print(f"--- recording snapshot ({len(actions)} actions) ---")
        for i, a in enumerate(actions):
            print(f"  [{i}] {action_to_dict(a)}")
        print("--- end ---")

    # 開発確認用の固定保存パス
    _DEV_MACRO_PATH = "dev_macro.json"

    def _dev_save_recording(self):
        """開発確認用: snapshot を固定パスへ JSON 保存する。"""
        from roulette_action_io import save_actions_json, ActionIOError
        actions = self._recorder.snapshot()
        if not actions:
            print("[dev] no actions to save")
            return
        try:
            save_actions_json(self._DEV_MACRO_PATH, actions)
            print(f"[dev] saved {len(actions)} actions to {self._DEV_MACRO_PATH}")
        except ActionIOError as e:
            print(f"[dev] save error: {e}")

    def _dev_load_to_session(self):
        """開発確認用: 固定パスから JSON 読込して macro session へセットする。"""
        from roulette_action_io import load_actions_json, ActionIOError
        try:
            actions = load_actions_json(self._DEV_MACRO_PATH)
            self._macro_session.load(actions)
            print(f"[dev] loaded {len(actions)} actions to session from {self._DEV_MACRO_PATH}")
            self._update_title_active_id()
        except ActionIOError as e:
            print(f"[dev] load error: {e}")

    def _dev_step_action(self) -> tuple[bool, str]:
        """開発確認用: session から次の1件を取り出して apply_action する。

        Returns:
            (成功フラグ, エラー詳細)。成功時は (True, "")。
        """
        from roulette_action_codec import action_summary as _summary

        if not self._macro_session.has_next():
            print("[dev] no more actions to step")
            return (False, "session が空です")
        action = self._macro_session.pop_next()

        # BranchOnWinner は apply_action に渡さず直接処理
        if isinstance(action, BranchOnWinner):
            ok = self._handle_branch_on_winner(action)
            if not ok:
                print("[dev] step branch FAILED — stopped")
            self._update_title_active_id()
            if ok:
                return (True, "")
            return (False, f"branch 評価失敗: {_summary(action)}")

        from roulette_action_codec import action_to_dict
        print(f"[dev] step [{self._macro_session.current_index}/{self._macro_session.total_count}] {action_to_dict(action)}")
        ok = self.apply_action(action, origin=ActionOrigin.MACRO)
        if not ok:
            self._macro_session.rewind_one()
            print(f"[dev] step FAILED — index rewound to {self._macro_session.current_index}")
        self._update_title_active_id()
        if ok:
            return (True, "")
        return (False, f"実行失敗: {_summary(action)}")

    def _dev_clear_session(self):
        """開発確認用: macro session をクリアする。"""
        if self._macro_auto_advancing:
            print("[dev] auto advance stopped — session cleared")
            self._stop_auto_advance()
        self._macro_session.clear()
        self._last_spin_result = None
        print("[dev] session cleared (last_spin_result cleared)")
        self._update_title_active_id()

    def _dev_show_action_viewer(self):
        """開発確認用: 現在の session / recorder の action 列を閲覧ダイアログで表示する。"""
        from macro_action_viewer import MacroActionViewer

        # session に action がある場合はそちらを表示、なければ recorder snapshot
        if self._macro_session.total_count > 0:
            actions = []
            for i in range(self._macro_session.total_count):
                if i < len(self._macro_session._actions):
                    actions.append(self._macro_session._actions[i])
            source = "session"
        else:
            actions = self._recorder.snapshot()
            source = "recorder"

        print(f"[dev] viewer: showing {len(actions)} actions from {source}")

        def apply_to_session(new_actions):
            self._macro_session.load(new_actions)
            print(f"[dev] viewer: applied {len(new_actions)} actions to session")
            self._update_title_active_id()

        viewer = MacroActionViewer(
            actions,
            active_roulette_id=self._manager.active_id,
            on_session_apply=apply_to_session,
            on_step=self._dev_step_action,
            on_run=self._dev_run_until_pause,
            session=self._macro_session,
            get_auto_advancing=lambda: self._macro_auto_advancing,
            parent=self,
        )
        viewer.setWindowTitle(f"マクロエディタ — {source}: {len(actions)} actions")
        self._macro_viewer = viewer
        viewer.exec()
        self._macro_viewer = None
        self._update_title_active_id()

    def _show_recording_preview(self):
        """記録中のアクション一覧をプレビュー表示する。"""
        from macro_action_viewer import MacroActionViewer

        actions = self._recorder.snapshot()
        if not actions:
            return

        viewer = MacroActionViewer(
            actions,
            active_roulette_id=self._manager.active_id,
            parent=self,
        )
        rec_status = "記録中" if self._recorder.is_recording else "記録済み"
        viewer.setWindowTitle(f"マクロエディタ — {rec_status}: {len(actions)} actions")
        viewer.exec()

    def _is_any_spinning(self) -> bool:
        """いずれかの roulette が spinning 中かを返す。"""
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx and ctx.panel.spin_ctrl.is_spinning:
                return True
        return False

    def _dev_run_until_pause(self) -> tuple[bool, str]:
        """開発確認用: session を安全に進められる範囲まで連続実行する。

        SpinRoulette 成功時は待機状態に入り、spin 完了後に自動再開する。

        停止条件:
          1. session が空になった
          2. apply_action() が False を返した
          3. SpinRoulette を成功実行した直後 → 待機状態に入って return
          4. いずれかの roulette が spinning 中

        Returns:
            (成功フラグ, エラー詳細)。成功時は (True, "")。
        """
        if not self._macro_session.has_next():
            print("[dev] run: no actions in session")
            self._stop_auto_advance()
            return (True, "")
        if self._is_any_spinning():
            print("[dev] run: blocked — spinning in progress")
            return (True, "")

        # auto advance 開始
        self._macro_auto_advancing = True

        from roulette_action_codec import action_to_dict, action_summary as _summary
        executed = 0
        error_detail = ""

        while self._macro_session.has_next():
            # auto advance が外部から停止された場合
            if not self._macro_auto_advancing:
                print(f"[dev] run: stopped by external ({executed} executed)")
                break

            action = self._macro_session.pop_next()

            # BranchOnWinner: apply_action に渡さず、ここで直接処理
            if isinstance(action, BranchOnWinner):
                branch_ok = self._handle_branch_on_winner(action)
                if not branch_ok:
                    self._stop_auto_advance()
                    error_detail = f"branch 評価失敗: {_summary(action)}"
                    break
                executed += 1
                print(f"[dev] run: [{self._macro_session.current_index}/{self._macro_session.total_count}] "
                      f"branch_on_winner('{action.winner_text}')")
                continue

            ok = self.apply_action(action, origin=ActionOrigin.MACRO)

            if not ok:
                self._macro_session.rewind_one()
                print(f"[dev] run: FAILED at [{self._macro_session.current_index}/{self._macro_session.total_count}] "
                      f"{action_to_dict(action)} — stopped")
                self._stop_auto_advance()
                error_detail = f"実行失敗: {_summary(action)}"
                break

            executed += 1
            print(f"[dev] run: [{self._macro_session.current_index}/{self._macro_session.total_count}] "
                  f"{action_to_dict(action)}")

            # SpinRoulette 成功後は待機状態に入る
            if isinstance(action, SpinRoulette):
                rid = action.roulette_id or self._manager.active_id
                # auto advance 中は overlay を macro_hold_sec 後に自動クローズさせる
                ctx = self._manager.get(rid)
                if ctx:
                    ctx.panel.result_overlay.set_force_auto_close(
                        True, self._settings.macro_hold_sec
                    )
                self._macro_waiting_spin = True
                self._macro_waiting_roulette_id = rid
                print(f"[dev] run: waiting for spin completion on '{rid}' ({executed} executed)")
                self._update_title_active_id()
                self._notify_macro_viewer()
                return (True, "")  # ResultOverlay.closed で _try_resume_macro_after_overlay が呼ばれる

            # spinning が始まっていたら安全側で停止
            if self._is_any_spinning():
                print(f"[dev] run: paused — spinning detected ({executed} executed)")
                self._stop_auto_advance()
                break
        else:
            print(f"[dev] run: completed all ({executed} executed)")
            self._stop_auto_advance()

        self._update_title_active_id()
        return (not bool(error_detail), error_detail)

    def _handle_branch_on_winner(self, branch: BranchOnWinner) -> bool:
        """BranchOnWinner を評価し、適切な action 列を session に挿入する。

        安全側停止条件:
          - _last_spin_result が None
          - source_roulette_id が未設定（空文字）
          - _last_spin_result.roulette_id が source_roulette_id と不一致

        Returns:
            処理成功なら True。安全側停止すべき場合は False。
        """
        result = self._last_spin_result
        if result is None:
            print("[dev] branch: STOPPED — no last spin result")
            return False

        if not branch.source_roulette_id:
            print("[dev] branch: STOPPED — source_roulette_id is empty")
            return False

        if result.roulette_id != branch.source_roulette_id:
            print(f"[dev] branch: STOPPED — roulette mismatch: "
                  f"result='{result.roulette_id}' vs source='{branch.source_roulette_id}'")
            return False

        # 第1条件を評価
        cond1 = self._eval_single_condition(
            result.winner_text, branch.match_mode, branch.winner_text,
            branch.regex_ignore_case, branch.numeric_operator, branch.numeric_value)
        if cond1 is None:
            return False  # 安全側停止（invalid regex 等）

        # compound_logic に応じて第2条件を評価
        logic = branch.compound_logic
        if logic in ("and", "or"):
            cond2 = self._eval_single_condition(
                result.winner_text, branch.cond2_match_mode, branch.cond2_winner_text,
                branch.cond2_regex_ignore_case, branch.cond2_numeric_operator,
                branch.cond2_numeric_value)
            if cond2 is None:
                return False
            if logic == "and":
                matched = cond1 and cond2
            else:
                matched = cond1 or cond2
        else:
            matched = cond1

        if matched:
            chosen = branch.then_actions
            label = "then"
        else:
            chosen = branch.else_actions
            label = "else"

        print(f"[dev] branch: source='{branch.source_roulette_id}' "
              f"winner='{result.winner_text}' vs condition='{branch.winner_text}' "
              f"mode={mode} → {label} ({len(chosen)} actions)")

        if chosen:
            self._macro_session.insert_actions(chosen)
        return True

    @staticmethod
    def _eval_single_condition(winner_text: str, mode: str, cond_text: str,
                               regex_ic: bool, num_op: str, num_val: str) -> bool | None:
        """単一条件を評価する。True/False または None（安全側停止）を返す。"""
        mode = mode or "exact"
        if mode == "numeric":
            try:
                wn = float(winner_text)
                cn = float(num_val)
            except (ValueError, TypeError):
                return False
            ops = {"==": wn == cn, "!=": wn != cn, ">": wn > cn,
                   ">=": wn >= cn, "<": wn < cn, "<=": wn <= cn}
            return ops.get(num_op, False)
        elif mode == "regex":
            try:
                flags = re.IGNORECASE if regex_ic else 0
                return bool(re.search(cond_text, winner_text, flags))
            except re.error:
                return None
        elif mode == "contains":
            return cond_text in winner_text
        else:
            return winner_text == cond_text

    def _stop_auto_advance(self):
        """auto advance 状態を全てクリアする。"""
        self._macro_auto_advancing = False
        self._macro_waiting_spin = False
        self._macro_waiting_roulette_id = None
        self._notify_macro_viewer()

    def _notify_macro_viewer(self):
        """macro viewer が表示中であれば実行状態表示を更新する。"""
        if self._macro_viewer is not None:
            self._macro_viewer._update_execution_status()

    def _on_result_overlay_closed(self, roulette_id: str):
        """ResultOverlay が閉じられた時のハンドラ。

        auto advance 待機中であれば再開を試みる。
        """
        self._try_resume_macro_after_overlay(roulette_id)

    def _try_resume_macro_after_overlay(self, closed_roulette_id: str):
        """ResultOverlay 閉じ通知を受けて、安全条件を満たせば auto advance を再開する。

        再開条件（全て満たす場合のみ再開）:
          1. auto advance 実行中であること
          2. spin 完了待ち中であること
          3. 閉じた roulette が待機対象と一致すること
          4. 他の roulette が spinning 中でないこと
        """
        if not self._macro_auto_advancing:
            return
        if not self._macro_waiting_spin:
            return
        if closed_roulette_id != self._macro_waiting_roulette_id:
            print(f"[dev] resume: ignored — overlay closed '{closed_roulette_id}' "
                  f"!= waiting '{self._macro_waiting_roulette_id}'")
            return
        if self._is_any_spinning():
            print("[dev] resume: blocked — roulette still spinning")
            return

        # 待機状態を解除して再開
        self._macro_waiting_spin = False
        self._macro_waiting_roulette_id = None
        print(f"[dev] resume: overlay closed on '{closed_roulette_id}', resuming macro")
        self._dev_run_until_pause()

    # ================================================================
    #  ルーレット生成
    # ================================================================

    def _create_roulette(self, roulette_id: str, parent: QWidget) -> RoulettePanel:
        """ルーレットパネルを生成し、manager に登録して返す。

        処理:
          1. 項目データ・セグメントの読み込み
          2. RoulettePanel の生成と初期設定適用
          3. RouletteContext の作成と manager 登録
          4. signal/slot 接続
          5. パネル一覧への登録
          6. 位置・サイズの復元
        """
        # データ読み込み
        segments, _ = build_segments_from_config(self._config)
        item_entries = load_all_item_entries(self._config)

        # パネル生成・初期設定
        panel = RoulettePanel(
            self._design, self._sound,
            roulette_id=roulette_id, parent=parent,
        )
        panel.apply_settings(self._settings, self._design)
        panel.set_segments(segments)

        panel.spin_ctrl.set_sound_tick_enabled(self._settings.sound_tick_enabled)
        panel.spin_ctrl.set_sound_result_enabled(self._settings.sound_result_enabled)
        if self._settings.spin_preset_name:
            panel.spin_ctrl.set_spin_preset(self._settings.spin_preset_name)
        panel.result_overlay.set_close_mode(self._settings.result_close_mode)
        panel.result_overlay.set_hold_sec(self._settings.result_hold_sec)
        # i274: ログオーバーレイは「ログ前面表示 (log_on_top)」のみで制御。
        # 旧 log_visible は内部的に常時 True にしておく（描画条件は log_on_top）。
        panel.wheel.set_log_visible(True)
        panel.wheel.set_log_timestamp(self._settings.log_timestamp)
        panel.wheel.set_log_box_border(self._settings.log_box_border)
        panel.wheel.set_log_on_top(self._settings.log_on_top)
        panel.spin_ctrl.set_spin_duration(self._settings.spin_duration)
        panel.spin_ctrl.set_replay_manager(self._replay_mgr)
        panel.spin_ctrl.set_spin_mode(self._settings.spin_mode)
        panel.spin_ctrl.set_double_duration(self._settings.double_duration)
        panel.spin_ctrl.set_triple_duration(self._settings.triple_duration)
        panel.set_transparent(self._settings.roulette_transparent)

        # manager 登録
        self._manager.register(RouletteContext(
            roulette_id=roulette_id,
            panel=panel,
            item_entries=item_entries,
            segments=segments,
        ))

        # signal 接続
        panel.spin_requested.connect(self._start_spin)
        panel.spin_finished.connect(
            lambda w, s, rid=roulette_id: self._on_spin_finished(w, s, rid)
        )
        panel.pointer_angle_changed.connect(self._on_pointer_angle_changed)
        panel.pointer_angle_committed.connect(self._on_pointer_angle_committed)
        panel.activate_requested.connect(
            lambda rid: self.apply_action(SetActiveRoulette(rid))
        )
        panel.result_overlay.closed.connect(
            lambda rid=roulette_id: self._on_result_overlay_closed(rid)
        )

        # パネル一覧・Z オーダー管理
        self._panels.append(panel)
        panel.geometry_changed.connect(
            lambda p=panel: self._bring_panel_to_front(p)
        )

        # 位置・サイズ復元
        self._restore_roulette_panel(panel)

        return panel

    # 新規パネルの初期位置オフセット（複数生成時に重ならないよう少しずらす）
    _NEW_PANEL_OFFSET = 30

    def _add_roulette(self, roulette_id: str, *,
                      activate: bool = False) -> RoulettePanel | None:
        """新しいルーレットを内部生成する。

        将来 UI（追加ボタン等）から呼ばれることを想定した入口。
        既に同じ roulette_id が登録されている場合は None を返す。

        Args:
            roulette_id: 新しいルーレットの一意 ID
            activate: True なら生成後にアクティブにする

        Returns:
            生成した RoulettePanel。重複 ID の場合は None。
        """
        if self._manager.get(roulette_id) is not None:
            return None

        parent = self.centralWidget()
        panel = self._create_roulette(roulette_id, parent)

        # 既存パネルと重ならないよう少しずらす
        count = len([p for p in self._panels if isinstance(p, RoulettePanel)])
        if count > 1:
            offset = (count - 1) * self._NEW_PANEL_OFFSET
            panel.move(panel.x() + offset, panel.y() + offset)

        panel.show()

        if activate:
            self._set_active_roulette(roulette_id)

        self._update_instance_labels()
        return panel

    def _remove_roulette(self, roulette_id: str) -> bool:
        """指定 ID のルーレットを削除する。

        将来 UI（削除ボタン等）から呼ばれることを想定した入口。

        削除制約:
          - 最後の1個は削除不可（ルーレットが0個になるのを防ぐ）
          - 未登録 ID は False を返す

        active 削除時の退避:
          - manager.unregister が残る先頭の ID を自動で active にする
          - active_changed signal → _on_active_changed で SettingsPanel が追従

        Returns:
            削除成功なら True、制約違反や未登録なら False。
        """
        if self._manager.count <= 1:
            return False

        ctx = self._manager.unregister(roulette_id)
        if ctx is None:
            return False

        panel = ctx.panel
        if panel in self._panels:
            self._panels.remove(panel)
        panel.hide()
        panel.deleteLater()

        # 削除された roulette の当選結果が残っていたら無効化
        if (self._last_spin_result is not None
                and self._last_spin_result.roulette_id == roulette_id):
            self._last_spin_result = None

        self._update_instance_labels()
        return True

    # ---- ID 採番 ----

    _ID_PREFIX = "roulette_"

    def _next_roulette_id(self) -> str:
        """既存 ID と重複しない一意の roulette_id を返す。

        採番規則: roulette_2, roulette_3, ... の連番。
        欠番があればそこを飛ばして次の空き番号を使う。
        """
        n = 2
        while self._manager.get(f"{self._ID_PREFIX}{n}") is not None:
            n += 1
        return f"{self._ID_PREFIX}{n}"

    def _add_new_roulette(self, *, activate: bool = True) -> RoulettePanel | None:
        """新しいルーレットを自動採番で追加する。

        将来 UI（追加ボタン等）から呼ばれることを想定した入口。
        呼び出し側が ID を意識する必要がない。

        Args:
            activate: True なら生成後にアクティブにする（デフォルト True）

        Returns:
            生成した RoulettePanel。
        """
        roulette_id = self._next_roulette_id()
        return self._add_roulette(roulette_id, activate=activate)

    # ================================================================
    #  保存ヘルパー
    # ================================================================

    def _apply_app_theme(self, design: DesignSettings):
        """QApplication 全体にテーマを適用する。"""
        app = QApplication.instance()
        if app:
            app.setStyleSheet(
                get_app_stylesheet(self._settings.theme_mode, design)
            )

    def _check_os_theme_change(self):
        """OS テーマの変化を検知し、system モード時にテーマを再適用する。"""
        if self._settings.theme_mode not in ("system", "auto"):
            return
        current = resolve_theme_mode("system")
        if current != self._last_os_theme:
            self._last_os_theme = current
            self._apply_app_theme(self._design)
            self._settings_panel.set_panel_theme_mode(self._settings.theme_mode)

    def _save_config(self):
        """アプリ設定・デザイン設定を config に書き戻して保存する。

        i281: offscreen QPA では (smoke test 等) ディスク書き込みを抑止する。
        本物の Windows / Linux / Mac セッションでは通常通り保存する。
        """
        try:
            if QApplication.platformName() == "offscreen":
                return
        except Exception:
            pass
        self._config.update(self._settings.to_config_patch())
        if self._design:
            self._config["design"] = self._design.to_dict()
        self._config["design_presets"] = self._preset_mgr.to_dict()
        save_config(self._config)

    def _save_item_entries(self):
        """項目データを config に書き戻して保存する。"""
        save_item_entries(self._config, self._active_context.item_entries)

    # ================================================================
    #  ウィンドウフラグ・パネル Z オーダー管理
    # ================================================================

    def _apply_window_flags(self):
        """always_on_top の設定に基づいてウィンドウフラグを適用する。"""
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if self._settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _apply_central_background(self, transparent: bool):
        """centralWidget の塗りつぶしのみを切り替える。

        QMainWindow 自身は常時 WA_TranslucentBackground 状態。実際の
        透過/不透明は centralWidget の stylesheet の background-color で
        切り替える。これなら native window 再生成が不要なので、
        実行時トグルが安定して反映される。
        """
        central = self.centralWidget()
        if not central:
            return
        if transparent:
            central.setStyleSheet("background-color: transparent;")
        else:
            central.setStyleSheet(
                f"background-color: {self._design.bg};"
            )

    def _apply_window_transparent(self, enabled: bool):
        """メインウィンドウ自体の透過モードを適用する。

        QMainWindow / centralWidget は init 時から常に
        WA_TranslucentBackground 構成にしてあるので、実行時切替では
        centralWidget の背景塗り (transparent / design.bg) だけを
        差し替える。`hide → setWindowFlags → show` のような重い処理は
        不要で、即時反映される。
        """
        self._settings.window_transparent = enabled
        self._apply_central_background(enabled)
        # 念のため再描画
        if self.isVisible():
            self.update()
            central = self.centralWidget()
            if central:
                central.update()

    def _apply_roulette_transparent(self, enabled: bool):
        """ルーレットパネル側の透過モードを適用する。

        メインウィンドウ自体は触らない。各 RoulettePanel 自身の背景塗り
        (`set_transparent`) と内部 WheelWidget の塗りを切り替える。
        """
        self._settings.roulette_transparent = enabled
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx and ctx.panel:
                ctx.panel.set_transparent(enabled)

    def _toggle_always_on_top(self):
        """常に最前面の ON/OFF を切り替える。"""
        self._settings.always_on_top = not self._settings.always_on_top
        was_visible = self.isVisible()
        self._apply_window_flags()
        if was_visible:
            self.show()  # setWindowFlags 後に再表示が必要
        # クイック設定バーのチェックボックスを同期
        self._settings_panel.update_setting(
            "always_on_top", self._settings.always_on_top
        )
        self._save_config()

    def _toggle_grip_visible(self):
        """リサイズグリップの表示/非表示を切り替える。"""
        new_val = not self._settings.grip_visible
        self._settings.grip_visible = new_val
        self._apply_grip_visible(new_val)
        self._settings_panel.update_setting("grip_visible", new_val)
        self._save_config()

    def _toggle_ctrl_box_visible(self):
        """コントロールボックスの表示/非表示を切り替える。"""
        new_val = not self._settings.ctrl_box_visible
        self._settings.ctrl_box_visible = new_val
        self._apply_ctrl_box_visible(new_val)
        self._settings_panel.update_setting("ctrl_box_visible", new_val)
        self._save_config()

    def _toggle_show_instance(self):
        """インスタンス番号表示の ON/OFF を切り替える。"""
        new_val = not self._settings.float_win_show_instance
        self._settings.float_win_show_instance = new_val
        self._update_instance_labels()
        self._settings_panel.update_setting("float_win_show_instance", new_val)
        self._save_config()

    def _toggle_settings_panel_float(self):
        """設定パネルのフローティング独立化を切り替える。"""
        new_val = not self._settings.settings_panel_float
        self._settings.settings_panel_float = new_val
        self._apply_settings_panel_float(new_val)
        self._settings_panel.update_setting("settings_panel_float", new_val)
        self._save_config()

    def _apply_settings_panel_float(self, floating: bool):
        """設定パネルの埋め込み/フローティングを切り替える。"""
        sp = self._settings_panel
        was_visible = self._settings_panel_visible

        # 現在の位置・サイズを保存
        if was_visible:
            cur_w, cur_h = sp.width(), sp.height()
            if floating:
                # 埋め込み→フローティング: 親内座標→スクリーン座標に変換
                global_pos = sp.mapToGlobal(QPoint(0, 0))
                cur_x, cur_y = global_pos.x(), global_pos.y()
            else:
                # フローティング→埋め込み: スクリーン座標→親内座標に変換
                parent = self.centralWidget()
                if parent:
                    local_pos = parent.mapFromGlobal(sp.pos())
                    cur_x, cur_y = local_pos.x(), local_pos.y()
                else:
                    cur_x, cur_y = sp.x(), sp.y()
        else:
            cur_w = getattr(self, '_last_sp_w', sp._panel_min_w)
            cur_h = getattr(self, '_last_sp_h', 400)
            cur_x = getattr(self, '_last_sp_x', 0)
            cur_y = getattr(self, '_last_sp_y', 0)

        # 一旦隠す
        sp.hide()

        if floating:
            # フローティング化: 親から切り離し
            sp.setParent(None)
            sp.setWindowFlags(
                Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            )
            sp._floating = True
            # スクリーン座標で配置
            sp.setGeometry(cur_x, cur_y, cur_w, cur_h)
        else:
            # 埋め込み化: 親に戻す
            central = self.centralWidget()
            sp.setParent(central)
            sp.setWindowFlags(Qt.WindowType.Widget)
            sp._floating = False
            # 親内座標で配置（クランプ）
            pw = central.width() if central else self.width()
            ph = central.height() if central else self.height()
            cur_x = max(0, min(cur_x, pw - cur_w))
            cur_y = max(0, min(cur_y, ph - cur_h))
            sp.setGeometry(cur_x, cur_y, cur_w, cur_h)

        # 表示復元
        if was_visible:
            sp.show()
            sp.raise_()

        # 保存座標を更新
        self._last_sp_w = cur_w
        self._last_sp_h = cur_h
        self._last_sp_x = cur_x
        self._last_sp_y = cur_y

    def _apply_grip_visible(self, visible: bool):
        """全パネルのリサイズグリップの表示状態を反映する。"""
        self._active_panel._grip.setVisible(visible)
        self._settings_panel._resize_grip.setVisible(visible)

    def _apply_ctrl_box_visible(self, visible: bool):
        """コントロールボックス相当UIの表示状態を反映する。

        PySide6 側では v0.4.4 のコントロールボックス（最小化/閉じるボタン群）に
        直接対応するUIがない。ここでは SettingsPanel のスピンセクション
        （スピンボタン + プリセット選択行）を「操作ボックス」相当とみなし、
        その表示/非表示を制御する。
        """
        self._settings_panel.set_spin_section_visible(visible)

    def _update_instance_labels(self):
        """全 RoulettePanel のインスタンス番号ラベルを更新する。

        表示条件:
          - float_win_show_instance が ON
          - かつルーレットが2個以上
        単窓時や設定 OFF 時は番号を非表示にする。
        """
        ids = self._manager.ids()
        show = self._settings.float_win_show_instance and len(ids) > 1
        for i, rid in enumerate(ids):
            ctx = self._manager.get(rid)
            if ctx and ctx.panel:
                ctx.panel.set_instance_label(i + 1 if show else None)

    def _bring_panel_to_front(self, panel):
        """指定パネルを Z オーダーの最前面へ移動する。

        pinned_front パネルは通常パネルより常に上に表示される。
        同カテゴリ内では最後に触ったものが最前面。
        """
        # 通常パネルを先に、pinned パネルを後に raise する
        # （後に raise したものが上に来る）
        normal = [p for p in self._panels if p.isVisible() and not p.pinned_front and p is not panel]
        pinned = [p for p in self._panels if p.isVisible() and p.pinned_front and p is not panel]

        if panel.pinned_front:
            for p in normal:
                p.raise_()
            for p in pinned:
                p.raise_()
            panel.raise_()
        else:
            for p in normal:
                p.raise_()
            panel.raise_()
            for p in pinned:
                p.raise_()

    # ================================================================
    #  ウィンドウ / パネル配置の復元・保存
    # ================================================================

    def _restore_window_geometry(self, default_w: int, default_h: int):
        """保存済みウィンドウ位置・サイズを復元する。"""
        s = self._settings
        w = s.window_width if s.window_width is not None else default_w
        h = s.window_height if s.window_height is not None else default_h
        w = max(MIN_W, w)
        h = max(MIN_H, h)

        avail = self._get_available_geometry()
        if avail is not None:
            w = min(w, avail.width())
            h = min(h, avail.height())

        self.resize(w, h)

        # i281: 復元時の追跡フラグ初期化
        # - _window_pos_was_fallback: 保存位置がどの画面にも乗っていなくて
        #   _clamp_position がセンタリングへ落ちた印
        # - _window_pos_user_moved: ユーザー操作 (run 中の move) で位置が
        #   変わった印
        # 両方が立っていない状態 (= load 時 fallback、ユーザー未操作) では、
        # 終了時に元の保存値を上書きせず温存する。これにより一時的に画面
        # 構成が変わっても、後で同じ画面が復活したときに元の位置へ戻る。
        self._window_pos_was_fallback = False
        self._window_pos_user_moved = False

        if s.window_x is not None and s.window_y is not None:
            x, y = s.window_x, s.window_y
            cx, cy = self._clamp_position(x, y, w, h)
            if (cx, cy) != (x, y):
                self._window_pos_was_fallback = True
            self.move(cx, cy)

    def _restore_roulette_panel(self, panel: RoulettePanel | None = None):
        """ルーレットパネルの位置・サイズを復元する。"""
        if panel is None:
            panel = self._roulette_panel
        s = self._settings
        parent = self.centralWidget()
        pw = parent.width() if parent else self.width()
        ph = parent.height() if parent else self.height()
        m = 2

        rp_x = s.roulette_panel_x if s.roulette_panel_x is not None else m
        rp_y = s.roulette_panel_y if s.roulette_panel_y is not None else m
        rp_w = s.roulette_panel_width if s.roulette_panel_width is not None else pw - 2 * m
        rp_h = s.roulette_panel_height if s.roulette_panel_height is not None else ph - 2 * m

        rp_w = max(RoulettePanel._MIN_W, min(rp_w, pw))
        rp_h = max(RoulettePanel._MIN_H, min(rp_h, ph))
        rp_x = max(0, min(rp_x, pw - rp_w))
        rp_y = max(0, min(rp_y, ph - rp_h))

        panel.setGeometry(rp_x, rp_y, rp_w, rp_h)

    # ================================================================
    #  i277: パネル管理 (centralWidget 内の内部パネル) + 前面化フォーカス
    # ================================================================

    def _is_panel_focused(self, panel: QWidget) -> bool:
        """指定パネルが現在 focused (最前面) かどうか。"""
        return getattr(self, "_focused_panel", None) is panel

    def _set_panel_focused(self, panel: QWidget):
        """指定パネルを focused (最前面) にする。"""
        self._focused_panel = panel
        panel.raise_()


    def _default_panel_positions(self) -> dict:
        """各パネルのデフォルト初期位置を計算する (client = centralWidget 座標)。

        i277: top-level 方式から内部パネル方式へ戻したため、座標は
        centralWidget 内の (x, y, w, h)。
        """
        central = self.centralWidget()
        # i279: centralWidget は init 直後 (show 前) は既定 640x480 を返すので、
        # `self.width()/height()` (resize 済み) を併用して大きい方を採用する。
        if central:
            cw = max(central.width(), self.width(), 1)
            ch = max(central.height(), self.height(), 1)
        else:
            cw = max(self.width(), 1)
            ch = max(self.height(), 1)
        if cw < 100:
            cw = max(self.width(), 320)
        if ch < 100:
            ch = max(self.height(), 320)

        # ManagePanel: 左上 (小さい)
        mp_w, mp_h = 240, 180
        mp_x = 12
        mp_y = 12

        # ItemPanel: 左寄り、ManagePanel の下
        ip_w = min(360, max(260, cw - 24))
        ip_h = min(460, max(220, ch - mp_h - 36))
        ip_x = 12
        ip_y = mp_h + 24

        # SettingsPanel: 右寄り
        sp_w = min(320, max(260, cw - 24))
        sp_h = min(480, max(220, ch - 24))
        sp_x = max(0, cw - sp_w - 12)
        sp_y = 12

        return {
            "items": (ip_x, ip_y, ip_w, ip_h),
            "settings": (sp_x, sp_y, sp_w, sp_h),
            "manage": (mp_x, mp_y, mp_w, mp_h),
        }

    def _clamp_to_client(self, x: int, y: int, w: int, h: int) -> tuple[int, int]:
        """指定 geometry を centralWidget 内にクランプする (client 座標)。

        パネルが完全にクライアント領域外へ消えるのを防ぐ。

        i279: centralWidget は QMainWindow のレイアウト活性化が走るまで
        既定値 (640x480 など) を返すため、`self.width()/height()` (`resize()`
        済みの値) を併用して大きい方を採用する。これにより init 直後
        (show 前) でも、ユーザーが指定したウィンドウサイズに対して正しく
        クランプできる。
        """
        central = self.centralWidget()
        if central:
            cw = max(central.width(), self.width(), 1)
            ch = max(central.height(), self.height(), 1)
        else:
            cw = max(self.width(), 1)
            ch = max(self.height(), 1)
        if cw < 100:
            cw = max(self.width(), 320)
        if ch < 100:
            ch = max(self.height(), 320)
        # パネルがクライアント領域内に完全に収まるようにクランプ
        x = max(0, min(x, max(0, cw - w)))
        y = max(0, min(y, max(0, ch - h)))
        return x, y

    def _apply_panel_geometry(self, panel: QWidget,
                              x: int, y: int, w: int, h: int,
                              min_w: int = 200, min_h: int = 200):
        """パネルに geometry を適用 (client 座標、クライアント領域内クランプ込み)。"""
        w = max(min_w, w)
        h = max(min_h, h)
        x, y = self._clamp_to_client(x, y, w, h)
        panel.setGeometry(x, y, w, h)

    def _restore_all_panel_geometries(self):
        """全パネルの位置・表示状態を AppSettings から復元する。"""
        s = self._settings
        defaults = self._default_panel_positions()

        # ItemPanel
        ip_x = s.items_panel_x if s.items_panel_x is not None else defaults["items"][0]
        ip_y = s.items_panel_y if s.items_panel_y is not None else defaults["items"][1]
        ip_w = s.items_panel_width if s.items_panel_width is not None else defaults["items"][2]
        ip_h = s.items_panel_height if s.items_panel_height is not None else defaults["items"][3]
        self._apply_panel_geometry(self._item_panel, ip_x, ip_y, ip_w, ip_h, 260, 220)
        if s.items_panel_visible:
            self._item_panel.show()
            self._item_panel.raise_()

        # SettingsPanel
        sp_x = s.settings_panel_x if s.settings_panel_x is not None else defaults["settings"][0]
        sp_y = s.settings_panel_y if s.settings_panel_y is not None else defaults["settings"][1]
        sp_w = s.settings_panel_width if s.settings_panel_width is not None else defaults["settings"][2]
        sp_h = s.settings_panel_height if s.settings_panel_height is not None else defaults["settings"][3]
        sp_min = self._settings_panel._panel_min_w
        self._apply_panel_geometry(self._settings_panel, sp_x, sp_y, sp_w, sp_h, sp_min, 200)
        if s.settings_panel_visible:
            self._settings_panel.show()
            self._settings_panel.raise_()
            self._settings_panel_visible = True

        # ManagePanel
        mp_x = s.manage_panel_x if s.manage_panel_x is not None else defaults["manage"][0]
        mp_y = s.manage_panel_y if s.manage_panel_y is not None else defaults["manage"][1]
        mp_w = s.manage_panel_width if s.manage_panel_width is not None else defaults["manage"][2]
        mp_h = s.manage_panel_height if s.manage_panel_height is not None else defaults["manage"][3]
        self._apply_panel_geometry(self._manage_panel, mp_x, mp_y, mp_w, mp_h, 220, 220)
        if s.manage_panel_visible:
            self._manage_panel.show()
            self._manage_panel.raise_()
            self._manage_panel_visible = True

        # ManagePanel のチェックボックスを実状態と同期
        self._sync_manage_panel_checks()

    def _refresh_panel_tracking(self):
        """各パネルの全子孫に mouseTracking を再適用する。

        i281: 項目行などが動的に追加されると、新しい QWidget は
        mouseTracking が False のため、その上では filter のホバー型
        cursor preview が効かない。エントリ更新などのタイミングで
        この helper を呼んで全体に行き渡らせる。
        """
        f = getattr(self, "_panel_input_filter", None)
        if f is None:
            return
        for p in (
            getattr(self, "_settings_panel", None),
            getattr(self, "_item_panel", None),
            getattr(self, "_manage_panel", None),
        ):
            if p is None:
                continue
            try:
                f._enable_tracking_recursive(p)
            except Exception:
                pass

    def _sync_manage_panel_checks(self):
        """ManagePanel の表示チェックを実際のパネル表示状態と一致させる。

        i279: 起動直後・F2/F3・ManagePanel 自身のクリック・コードによる
        表示切替のいずれの経路でも、UI チェックと実状態を必ず合わせる。
        """
        if not hasattr(self, "_manage_panel"):
            return
        try:
            self._manage_panel.set_items_visible(
                self._item_panel.isVisible()
                if hasattr(self, "_item_panel") else False
            )
            self._manage_panel.set_settings_visible(
                self._settings_panel.isVisible()
                if hasattr(self, "_settings_panel") else False
            )
        except Exception:
            pass

    def _on_manage_items_toggled(self, visible: bool):
        """ManagePanel から: 項目パネルの表示状態を切り替える。"""
        if visible:
            self._item_panel.show()
            self._item_panel.raise_()
        else:
            self._item_panel.hide()
        self._settings.items_panel_visible = visible
        self._sync_manage_panel_checks()
        self._save_config()

    def _on_manage_settings_toggled(self, visible: bool):
        """ManagePanel から: 設定パネルの表示状態を切り替える。"""
        if visible:
            self._settings_panel.show()
            self._settings_panel.raise_()
            self._settings_panel_visible = True
        else:
            self._settings_panel.hide()
            self._settings_panel_visible = False
        self._settings.settings_panel_visible = visible
        self._sync_manage_panel_checks()
        self._save_config()

    def _toggle_manage_panel(self):
        """F1: 全体管理パネルの表示 / 非表示。"""
        if self._manage_panel.isVisible():
            self._manage_panel.hide()
            self._manage_panel_visible = False
            self._settings.manage_panel_visible = False
        else:
            self._manage_panel.show()
            self._manage_panel.raise_()
            self._manage_panel_visible = True
            self._settings.manage_panel_visible = True
        self._save_config()

    def _toggle_item_panel(self):
        """F2: 項目パネルの表示 / 非表示。"""
        new_visible = not self._item_panel.isVisible()
        if new_visible:
            self._item_panel.show()
            self._item_panel.raise_()
        else:
            self._item_panel.hide()
        self._settings.items_panel_visible = new_visible
        self._sync_manage_panel_checks()
        self._save_config()

    def _toggle_settings_panel_v2(self):
        """F3: 設定パネルの表示 / 非表示。"""
        new_visible = not self._settings_panel.isVisible()
        if new_visible:
            self._settings_panel.show()
            self._settings_panel.raise_()
            self._settings_panel_visible = True
        else:
            self._settings_panel.hide()
            self._settings_panel_visible = False
        self._settings.settings_panel_visible = new_visible
        self._sync_manage_panel_checks()
        self._save_config()

    def _reset_panel_positions(self):
        """全パネルの位置を初期値に戻す (見失い時の復旧手段)。"""
        defaults = self._default_panel_positions()
        # ItemPanel
        ip_x, ip_y, ip_w, ip_h = defaults["items"]
        self._apply_panel_geometry(self._item_panel, ip_x, ip_y, ip_w, ip_h, 260, 220)
        # SettingsPanel
        sp_x, sp_y, sp_w, sp_h = defaults["settings"]
        sp_min = self._settings_panel._panel_min_w
        self._apply_panel_geometry(self._settings_panel, sp_x, sp_y, sp_w, sp_h, sp_min, 200)
        # ManagePanel
        mp_x, mp_y, mp_w, mp_h = defaults["manage"]
        self._apply_panel_geometry(self._manage_panel, mp_x, mp_y, mp_w, mp_h, 220, 220)
        # 全部を表示してユーザーが見つけられるようにする
        self._item_panel.show()
        self._item_panel.raise_()
        self._settings_panel.show()
        self._settings_panel.raise_()
        self._settings_panel_visible = True
        self._manage_panel.show()
        self._manage_panel.raise_()
        self._manage_panel_visible = True
        # チェックボックスと AppSettings を同期
        self._sync_manage_panel_checks()
        self._settings.items_panel_visible = True
        self._settings.settings_panel_visible = True
        self._settings.manage_panel_visible = True
        # 即座に保存
        self._panel_save_timer.stop()
        self._persist_panel_positions()

    # 旧名 (互換のため残す)
    def _restore_item_panel_geometry(self):
        """新 ItemPanel の保存位置を復元する。

        重要: 初回 show() より前は centralWidget の geometry がまだ最終
        サイズではない（Qt の遅延レイアウトで stale な値を返す）。そのため
        クランプには **QMainWindow 自身の width/height** を基準にする。
        QMainWindow は `_restore_window_geometry` で既にユーザー設定値に
        合わせてあるので、frameless 構成の central widget は最終的にこの
        サイズへ広がる前提で安全。
        """
        s = self._settings
        pw = max(self.width(), 1)
        ph = max(self.height(), 1)
        ip = self._item_panel
        min_w = ip.minimumWidth() or 260
        min_h = ip.minimumHeight() or 220

        ip_w = s.items_panel_width if s.items_panel_width is not None else 360
        ip_h = s.items_panel_height if s.items_panel_height is not None else 420
        ip_x = s.items_panel_x if s.items_panel_x is not None else 20
        ip_y = s.items_panel_y if s.items_panel_y is not None else 60

        ip_w = max(min_w, min(ip_w, max(min_w, pw)))
        ip_h = max(min_h, min(ip_h, max(min_h, ph)))
        ip_x = max(0, min(ip_x, max(0, pw - ip_w)))
        ip_y = max(0, min(ip_y, max(0, ph - ip_h)))
        ip.setGeometry(ip_x, ip_y, ip_w, ip_h)

    def _persist_panel_positions(self):
        """全パネルの現在位置を AppSettings に書き戻して保存する。

        debounce タイマー (`_panel_save_timer`) または明示呼び出しから利用。
        i275 以降、各パネルは top-level Tool window のため、`pos()` は
        screen 座標を返す。

        初期化中 (`_init_complete=False`) は何もしない。これは復元中の
        setGeometry が geometry_changed を発火させて未調整の位置を
        書き戻してしまうのを防ぐためのガード。
        i281: offscreen QPA (smoke test 等) ではディスク書き込みを抑止する。
        """
        if not getattr(self, "_init_complete", False):
            return
        try:
            if QApplication.platformName() == "offscreen":
                return
        except Exception:
            pass
        s = self._settings
        # ItemPanel — 表示中のときだけ最新位置を保存する。
        # 非表示中はパネル自身の geometry が無効なので保存しない。
        if hasattr(self, "_item_panel") and self._item_panel.isVisible():
            ip = self._item_panel
            s.items_panel_x = ip.x()
            s.items_panel_y = ip.y()
            s.items_panel_width = ip.width()
            s.items_panel_height = ip.height()
        # SettingsPanel — 表示中のときだけ
        if hasattr(self, "_settings_panel") and self._settings_panel.isVisible():
            sp = self._settings_panel
            s.settings_panel_x = sp.x()
            s.settings_panel_y = sp.y()
            s.settings_panel_width = sp.width()
            s.settings_panel_height = sp.height()
            self._last_sp_x = sp.x()
            self._last_sp_y = sp.y()
            self._last_sp_w = sp.width()
            self._last_sp_h = sp.height()
        # ManagePanel — 表示中のときだけ
        if hasattr(self, "_manage_panel") and self._manage_panel.isVisible():
            mp = self._manage_panel
            s.manage_panel_x = mp.x()
            s.manage_panel_y = mp.y()
            s.manage_panel_width = mp.width()
            s.manage_panel_height = mp.height()
        self._save_config()

    def _restore_settings_panel_visibility(self):
        """項目設定パネルの表示状態と位置を復元する。"""
        s = self._settings

        if s.settings_panel_width is not None:
            self._last_sp_w = max(self._settings_panel._panel_min_w, s.settings_panel_width)
        if s.settings_panel_height is not None:
            self._last_sp_h = s.settings_panel_height
        if s.settings_panel_x is not None:
            self._last_sp_x = s.settings_panel_x
        if s.settings_panel_y is not None:
            self._last_sp_y = s.settings_panel_y

        if s.settings_panel_visible:
            self._show_settings_panel_at_saved_or_default()

    def _show_settings_panel_at_saved_or_default(self):
        """項目設定パネルを保存位置またはデフォルト位置で表示する。"""
        sp = self._settings_panel
        panel_min = sp._panel_min_w

        if sp._floating:
            # フローティング時: スクリーン座標で配置
            avail = self._get_available_geometry()
            sw = avail.width() if avail else 1920
            sh = avail.height() if avail else 1080
            sx = avail.x() if avail else 0
            sy = avail.y() if avail else 0

            sp_w = getattr(self, '_last_sp_w', panel_min)
            sp_h = getattr(self, '_last_sp_h', 600)
            sp_x = getattr(self, '_last_sp_x', sx + sw - sp_w - 10)
            sp_y = getattr(self, '_last_sp_y', sy + 10)

            sp_w = max(panel_min, min(sp_w, sw))
            sp_h = max(100, min(sp_h, sh))

            sp.setGeometry(sp_x, sp_y, sp_w, sp_h)
        else:
            # 埋め込み時: 親内座標で配置
            # 注意: 初回 show 前は centralWidget の geometry が stale な
            # ため、クランプには QMainWindow 自身のサイズを使う。
            pw = max(self.width(), 1)
            ph = max(self.height(), 1)
            m = 2

            sp_w = getattr(self, '_last_sp_w', panel_min)
            sp_h = getattr(self, '_last_sp_h', ph - 2 * m)
            sp_x = getattr(self, '_last_sp_x', pw - sp_w - m)
            sp_y = getattr(self, '_last_sp_y', m)

            sp_w = max(panel_min, min(sp_w, pw))
            sp_h = max(100, min(sp_h, ph))
            sp_x = max(0, min(sp_x, pw - sp_w))
            sp_y = max(0, min(sp_y, ph - sp_h))

            sp.setGeometry(sp_x, sp_y, sp_w, sp_h)

        sp.show()
        sp.raise_()
        self._settings_panel_visible = True

    def _clamp_position(self, x: int, y: int, w: int, h: int) -> tuple[int, int]:
        """ウィンドウ位置を画面内に補正する。

        i281: いずれかの画面に対して十分な可視矩形 (>=100x30 px) があるなら、
        保存値をそのまま尊重する。すべての画面と一切重ならない場合のみ
        プライマリ画面の中央へリセットする。

        以前の実装は `x + 100 > sg.x()` という辺ベース判定で、ユーザーが
        境界の僅か手前 (例: secondary 開始 3840 に対し x=3739) に置いていた
        場合に near-miss でセンタリングへ落ちる不具合があった。
        矩形交差ベースに変更したことで、保存位置がほぼ画面上に乗っている
        限りそのまま復元される。
        """
        min_visible_w = 100
        min_visible_h = 30

        screens = QApplication.screens()
        for screen in screens:
            sg = screen.availableGeometry()
            visible_left = max(x, sg.x())
            visible_right = min(x + w, sg.x() + sg.width())
            visible_top = max(y, sg.y())
            visible_bottom = min(y + h, sg.y() + sg.height())
            vw = max(0, visible_right - visible_left)
            vh = max(0, visible_bottom - visible_top)
            if vw >= min_visible_w and vh >= min_visible_h:
                return x, y

        # どの画面とも交差なし: プライマリ中央へフォールバック
        avail = self._get_available_geometry()
        if avail is not None:
            x = avail.x() + (avail.width() - w) // 2
            y = avail.y() + (avail.height() - h) // 2
        return x, y

    def _get_available_geometry(self):
        screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _save_window_state(self):
        """現在のウィンドウ・パネル状態を保存する。

        i275: 最小化中は window geometry を保存しない (Windows 上で
        -32000 のような sentinel 値が pos() から返ってくることがあり、
        次回起動でレイアウトが破綻する)。

        i281: 加えて以下を守る:
        - offscreen QPA (smoke test 等) ではディスクへの保存自体を抑止する
        - load 時に画面外で fallback されたまま、ユーザーが手動で動かして
          いない場合は window_x / window_y を上書きしない (元の保存値を温存)
        """
        # i281: offscreen platform は smoke test 用なので保存しない
        try:
            if QApplication.platformName() == "offscreen":
                return
        except Exception:
            pass

        s = self._settings
        # 最小化中は window 位置は保存しない (古い値を維持)
        if not self.isMinimized():
            pos = self.pos()
            # 念のため -32000 系の sentinel もガード
            if pos.x() > -10000 and pos.y() > -10000:
                # i281: load 時 fallback されていて、かつユーザーが
                # 動かしていない場合は元の保存値を上書きしない
                preserve_pos = (
                    getattr(self, "_window_pos_was_fallback", False)
                    and not getattr(self, "_window_pos_user_moved", False)
                )
                if not preserve_pos:
                    s.window_x = pos.x()
                    s.window_y = pos.y()
                s.window_width = self.width()
                s.window_height = self.height()

        # ルーレットパネル
        rp = self._active_panel
        s.roulette_panel_x = rp.x()
        s.roulette_panel_y = rp.y()
        s.roulette_panel_width = rp.width()
        s.roulette_panel_height = rp.height()

        # SettingsPanel: 表示中のとき位置を更新、非表示なら最後の値を維持。
        # visible フラグは現在状態を尊重する。
        if self._settings_panel.isVisible():
            sp = self._settings_panel
            s.settings_panel_width = sp.width()
            s.settings_panel_height = sp.height()
            s.settings_panel_x = sp.x()
            s.settings_panel_y = sp.y()
        s.settings_panel_visible = self._settings_panel.isVisible()

        # ItemPanel
        if self._item_panel.isVisible():
            ip = self._item_panel
            s.items_panel_x = ip.x()
            s.items_panel_y = ip.y()
            s.items_panel_width = ip.width()
            s.items_panel_height = ip.height()
        s.items_panel_visible = self._item_panel.isVisible()

        # ManagePanel
        if self._manage_panel.isVisible():
            mp = self._manage_panel
            s.manage_panel_x = mp.x()
            s.manage_panel_y = mp.y()
            s.manage_panel_width = mp.width()
            s.manage_panel_height = mp.height()
        s.manage_panel_visible = self._manage_panel.isVisible()

        self._save_config()

    def closeEvent(self, event):
        self._save_window_state()
        super().closeEvent(event)

    # ================================================================
    #  初期表示・リサイズ
    # ================================================================

    def showEvent(self, event):
        super().showEvent(event)
        # i279: 初回 show のときに各パネルの位置・サイズ・表示状態を復元する。
        # super().showEvent() の後では centralWidget が QMainWindow と同じ
        # サイズに layout 済みなので、保存値を正しいクライアント領域内へ
        # クランプできる。
        if not getattr(self, "_panels_restored", False):
            self._panels_restored = True
            # singleShot(0) でイベントループの次サイクルへ後回しすることで、
            # 初回 paint 後の最終 layout を待つ。これにより centralWidget
            # の width/height が確実に最終値になる。
            QTimer.singleShot(0, self._do_initial_panel_restore)

    def _do_initial_panel_restore(self):
        """初回 show 後のパネル位置・表示状態の遅延復元。

        i279: __init__ 時に行っていた `_restore_all_panel_geometries()` を
        ここへ移した。central が確実に最終サイズになっている時点で
        実行することで、保存位置が小さくクランプされる事故を回避する。
        """
        try:
            self._restore_all_panel_geometries()
        finally:
            # 復元後の checkbox 同期と保存対象再開
            self._sync_manage_panel_checks()
            # i281: 復元時点で内部 layout が確定した子ウィジェットにも
            # mouseTracking を行き渡らせる。これがないと、項目行などの
            # 動的に追加された QWidget 上で resize cursor のホバーが
            # プレビューされない。
            try:
                f = getattr(self, "_panel_input_filter", None)
                if f is not None:
                    for p in (
                        self._settings_panel,
                        self._item_panel,
                        self._manage_panel,
                    ):
                        f._enable_tracking_recursive(p)
            except Exception:
                pass

    def moveEvent(self, event):
        """ウィンドウ移動時に位置を保存対象にする (最小化中はスキップ)。"""
        super().moveEvent(event)
        if not getattr(self, "_init_complete", False):
            return
        if self.isMinimized():
            return
        pos = self.pos()
        if pos.x() <= -10000 or pos.y() <= -10000:
            return
        s = self._settings
        s.window_x = pos.x()
        s.window_y = pos.y()
        # i281: ユーザー操作 (またはウィンドウマネージャ) で移動した印
        self._window_pos_user_moved = True
        # ディスク書き込みは debounce
        self._panel_save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            size = max(event.size().width(), event.size().height())
            self.blockSignals(True)
            self.resize(size, size)
            self.blockSignals(False)
        # 通常リサイズ時もサイズを保存対象にする
        if not getattr(self, "_init_complete", False):
            return
        if self.isMinimized():
            return
        s = self._settings
        s.window_width = self.width()
        s.window_height = self.height()
        self._panel_save_timer.start()

    # ================================================================
    #  Spin
    # ================================================================

    def _start_spin(self):
        # 手動 spin → auto advance を安全側で停止
        if self._macro_auto_advancing:
            print("[dev] auto advance stopped — manual spin requested")
            self._stop_auto_advance()
        self.apply_action(SpinRoulette())

    def _on_spin_finished(self, winner: str, seg_idx: int,
                          roulette_id: str = ""):
        self._settings_panel.set_spinning(False)
        # 直前当選結果を更新（manual / macro 共通の唯一の更新地点）
        self._last_spin_result = LastSpinResult(
            roulette_id=roulette_id,
            winner_text=winner,
            seg_index=seg_idx,
        )
        print(f"[dev] last_spin_result: roulette='{roulette_id}', "
              f"winner='{winner}', seg={seg_idx}")
        # ログオーバーレイに追加 + 自動保存
        if winner:
            ctx = self._manager.get(roulette_id) if roulette_id else self._manager.active
            if ctx:
                ctx.panel.wheel.add_log_entry(winner)
                ctx.panel.wheel.save_log(self._log_autosave_path)
            # 勝利数集計用履歴に記録
            pattern = get_current_pattern_name(self._config)
            self._win_history.record(winner, pattern)
            self._win_history.save()
            self._update_win_counts()
            self._settings_panel.set_replay_count(self._replay_mgr.count())
            self._refresh_replay_dialog()
        # auto advance の再開は ResultOverlay.closed で行う（spin_finished 直後ではなく
        # 結果表示の hold 完了後に再開するため）

    def _on_pointer_angle_changed(self, angle: float):
        self._settings.pointer_angle = angle
        self._settings_panel.update_setting("pointer_angle", angle)

    def _on_pointer_angle_committed(self):
        self._save_config()

    def _on_preset_changed(self, name: str):
        from spin_preset import SPIN_PRESETS
        self._active_panel.spin_ctrl.set_spin_preset(name)
        self._settings.spin_preset_name = name
        # プリセット切替時、そのプリセットの duration で spin_duration を連動更新
        if name in SPIN_PRESETS:
            dur = SPIN_PRESETS[name].duration
            self._settings.spin_duration = dur
            self._active_panel.spin_ctrl.set_spin_duration(dur)
            self._settings_panel.update_setting("spin_duration", dur)
        self._save_config()

    def _on_preview_tick(self):
        """tick音テスト再生。"""
        self._sound.preview_tick(self._settings.tick_pattern)

    def _on_preview_win(self):
        """result音テスト再生。"""
        self._sound.preview_win(self._settings.win_pattern)

    def _on_pattern_export(self):
        """現在のパターンをJSONファイルにエクスポートする。"""
        import json
        from PySide6.QtWidgets import QFileDialog
        ctx = self._active_context
        pattern_name = get_current_pattern_name(self._config)
        entries = [e.to_dict() for e in ctx.item_entries]
        if not entries:
            return
        default_name = f"{pattern_name}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "パターンをエクスポート", default_name,
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return
        data = {
            "pattern_name": pattern_name,
            "entries": entries,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _on_pattern_import(self):
        """JSONファイルからパターンをインポートする。"""
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(
            self, "パターンをインポート", "",
            "JSON ファイル (*.json);;全てのファイル (*)"
        )
        if not path:
            return
        # ファイル読み込み
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.warning(self, "インポートエラー",
                                f"ファイルを読み込めませんでした。\n{e}")
            return
        # バリデーション: トップレベル構造
        if not isinstance(data, dict):
            QMessageBox.warning(self, "インポートエラー",
                                "不正な形式です。JSON オブジェクトが必要です。")
            return
        pattern_name = data.get("pattern_name")
        entries_raw = data.get("entries")
        if not isinstance(pattern_name, str) or not pattern_name.strip():
            QMessageBox.warning(self, "インポートエラー",
                                "pattern_name が見つからないか不正です。")
            return
        if not isinstance(entries_raw, list):
            QMessageBox.warning(self, "インポートエラー",
                                "entries が見つからないか不正です。")
            return
        # バリデーション: 各エントリ
        for i, entry in enumerate(entries_raw):
            if not isinstance(entry, dict):
                QMessageBox.warning(self, "インポートエラー",
                                    f"entries[{i}] が不正な形式です。")
                return
            if "text" not in entry:
                QMessageBox.warning(self, "インポートエラー",
                                    f"entries[{i}] に text キーがありません。")
                return
        # 同名パターン衝突時: 連番付き別名で追加
        pattern_name = pattern_name.strip()
        existing = get_pattern_names(self._config)
        final_name = pattern_name
        if final_name in existing:
            suffix = 1
            while f"{pattern_name}_{suffix}" in existing:
                suffix += 1
            final_name = f"{pattern_name}_{suffix}"
        # 現在のパターンを保存してからインポート
        self._save_item_entries()
        # パターン追加 + エントリ書き込み
        add_pattern(self._config, final_name)
        # ItemEntry に変換して保存
        from item_entry import ItemEntry
        imported_entries = []
        for raw in entries_raw:
            item = ItemEntry.from_config_entry(raw, keep_disabled=True)
            if item is not None:
                imported_entries.append(item)
        save_item_entries(self._config, imported_entries, pattern_name=final_name)
        # インポートしたパターンに切替
        set_current_pattern(self._config, final_name)
        ctx = self._active_context
        ctx.item_entries = imported_entries
        ctx.segments, _ = build_segments_from_entries(imported_entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(imported_entries)
        self._settings_panel.set_pattern_list(
            get_pattern_names(self._config), final_name
        )

    def _on_shuffle_once(self):
        """単発ランダム再配置。item_entries をシャッフルしてセグメント再構築。

        i284: シャッフル直前のエントリ並びをスナップショットとして
        ctx に保持し、`_on_arrangement_reset` から復元できるようにする。
        既にスナップショットがある場合は上書きしない（複数回シャッフルしても
        最初の標準並びを記憶しておくため）。
        """
        import random
        ctx = self._active_context
        # i284: 並びリセット用スナップショット
        if getattr(ctx, "_pre_shuffle_entries", None) is None:
            ctx._pre_shuffle_entries = list(ctx.item_entries)
        entries = list(ctx.item_entries)
        random.shuffle(entries)
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._save_item_entries()

    def _on_arrangement_reset(self):
        """i284: 並びリセット。

        v0.4.4 の「標準配置に戻す」相当。直前のシャッフル前 snapshot へ
        並び順を戻す。snapshot が無い（一度もシャッフルしていない）場合は何もしない。
        """
        ctx = self._active_context
        snap = getattr(ctx, "_pre_shuffle_entries", None)
        if snap is None:
            return
        ctx.item_entries = list(snap)
        ctx._pre_shuffle_entries = None
        ctx.segments, _ = build_segments_from_entries(
            ctx.item_entries, self._config
        )
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(ctx.item_entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._save_item_entries()

    def _on_items_reset(self):
        """i284: 項目一括リセット（v0.4.4 「一括リセット」相当）。

        全項目の prob_mode / prob_value / split_count をデフォルトに戻す。
        項目名・enabled は維持する。`confirm_reset` ON 時は確認ダイアログ。
        """
        if self._settings.confirm_reset:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "項目一括リセット",
                "全項目の確率・分割設定をデフォルトに戻します。\n"
                "（項目名・有効/無効はそのまま）\nよろしいですか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        ctx = self._active_context
        from item_entry import ItemEntry as _IE
        new_entries = [
            _IE(text=e.text, enabled=e.enabled,
                prob_mode=None, prob_value=None, split_count=1)
            for e in ctx.item_entries
        ]
        ctx.item_entries = new_entries
        ctx.segments, _ = build_segments_from_entries(
            new_entries, self._config
        )
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(new_entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._save_item_entries()

    def _update_win_counts(self):
        """勝利数集計を SettingsPanel / ItemPanel とグラフに反映する。"""
        pattern = get_current_pattern_name(self._config)
        counts = self._win_history.count_by_item(pattern)
        self._settings_panel.update_win_counts(counts)
        self._item_panel.update_win_counts(counts)
        self._refresh_graph()

    def _on_log_clear(self):
        """ログ履歴クリア。confirm_reset=ON なら確認ダイアログを表示。"""
        if self._settings.confirm_reset:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "確認", "ログ履歴をクリアしますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._active_panel.wheel.clear_log()
        self._active_panel.wheel.save_log(self._log_autosave_path)
        self._win_history.clear()
        self._win_history.save()
        self._update_win_counts()
        self._settings_panel.set_replay_count(self._replay_mgr.count())

    def _on_log_export(self):
        """ログ履歴をテキストファイルにエクスポートする。"""
        from PySide6.QtWidgets import QFileDialog
        entries = self._active_panel.wheel.get_log_entries()
        if not entries:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "ログをエクスポート", "roulette_log.txt",
            "テキストファイル (*.txt);;全てのファイル (*)"
        )
        if not path:
            return
        # 古い順に出力（entries は新しい順なので逆順）
        lines = []
        for ts, text in reversed(entries):
            lines.append(f"[{ts}] {text}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _on_custom_tick_file(self, path: str):
        """カスタムtick音ファイル変更。"""
        self._settings.tick_custom_file = path
        self._sound.load_tick_custom(path)
        self._save_config()

    def _on_custom_win_file(self, path: str):
        """カスタムresult音ファイル変更。"""
        self._settings.win_custom_file = path
        self._sound.load_win_custom(path)
        self._save_config()

    # ================================================================
    #  設定変更ハンドラ（SettingsPanel → MainWindow → コンポーネント）
    # ================================================================

    def _on_setting_changed(self, key: str, value):
        """SettingsPanel からの設定変更を受けてアクション経由で反映する。"""
        self.apply_action(UpdateSettings(key=key, value=value))

    def _update_setting_by_action(self, key: str, value) -> bool:
        """アクション経由の設定変更。

        既存の設定反映分岐ロジックをそのまま保持する。

        Args:
            key: 設定キー名
            value: 設定値

        Returns:
            設定キーが有効なら True。
        """
        if not key:
            return False

        if hasattr(self._settings, key):
            setattr(self._settings, key, value)

        rp = self._active_panel
        if key == "text_size_mode":
            rp.wheel.set_text_mode(value, self._settings.text_direction)
        elif key == "text_direction":
            rp.wheel.set_text_mode(self._settings.text_size_mode, value)
        elif key == "donut_hole":
            rp.wheel.set_donut_hole(value)
        elif key == "pointer_angle":
            rp.wheel.set_pointer_angle(value)
            return True
        elif key == "spin_direction":
            rp.wheel._spin_direction = value
        elif key == "profile_idx":
            idx = min(value, len(SIZE_PROFILES) - 1)
            _, w, h = SIZE_PROFILES[idx]
            self._wheel_base_w = w
            self._wheel_base_h = h
            self.resize(w, h)
        elif key == "result_close_mode":
            rp.result_overlay.set_close_mode(value)
        elif key == "result_hold_sec":
            rp.result_overlay.set_hold_sec(value)
        elif key == "sound_tick_enabled":
            rp.spin_ctrl.set_sound_tick_enabled(value)
        elif key == "sound_result_enabled":
            rp.spin_ctrl.set_sound_result_enabled(value)
        elif key == "tick_volume":
            self._sound.set_tick_volume(value / 100.0)
        elif key == "win_volume":
            self._sound.set_win_volume(value / 100.0)
        elif key == "tick_pattern":
            self._sound.set_tick_pattern(value)
        elif key == "win_pattern":
            self._sound.set_win_pattern(value)
        elif key == "log_overlay_show":
            # i274: 廃止された設定。互換のため受け流す。
            pass
        elif key == "log_timestamp":
            rp.wheel.set_log_timestamp(value)
        elif key == "log_box_border":
            rp.wheel.set_log_box_border(value)
        elif key == "log_on_top":
            rp.wheel.set_log_on_top(value)
        elif key == "spin_duration":
            rp.spin_ctrl.set_spin_duration(value)
        elif key == "spin_mode":
            rp.spin_ctrl.set_spin_mode(value)
        elif key == "double_duration":
            rp.spin_ctrl.set_double_duration(value)
        elif key == "triple_duration":
            rp.spin_ctrl.set_triple_duration(value)
        elif key == "replay_max_count":
            self._replay_mgr.set_max_count(value)
            self._settings_panel.set_replay_count(self._replay_mgr.count())
        elif key == "replay_show_indicator":
            pass  # 値は AppSettings に保存済み。再生開始時に参照
        elif key == "window_transparent":
            self._apply_window_transparent(value)
        elif key == "roulette_transparent":
            self._apply_roulette_transparent(value)
        elif key == "always_on_top":
            if value != self._settings.always_on_top:
                self._toggle_always_on_top()
        elif key == "arrangement_direction":
            # 配置方向変更: config 更新 → セグメント再構築
            self._config["arrangement_direction"] = value
            ctx = self._active_context
            ctx.segments, _ = build_segments_from_entries(
                ctx.item_entries, self._config
            )
            rp.set_segments(ctx.segments)
        elif key == "grip_visible":
            self._apply_grip_visible(value)
        elif key == "ctrl_box_visible":
            self._apply_ctrl_box_visible(value)
        elif key == "float_win_show_instance":
            self._update_instance_labels()
        elif key == "settings_panel_float":
            self._apply_settings_panel_float(value)
        elif key == "show_item_prob":
            # i283: 項目行の確率行表示 ON/OFF。AppSettings に保存し、
            # SettingsPanel / ItemPanel 側にも反映を依頼する。
            self._settings.show_item_prob = bool(value)
            self._settings_panel.update_setting("show_item_prob", value)
            self._item_panel.update_setting("show_item_prob", value)
        elif key == "show_item_win_count":
            # i283: 項目行の当選回数表示 ON/OFF。
            self._settings.show_item_win_count = bool(value)
            self._settings_panel.update_setting("show_item_win_count", value)
            self._item_panel.update_setting("show_item_win_count", value)
        elif key == "item_panel_display_mode":
            # i289: 項目パネル表示モード切替。
            self._settings.item_panel_display_mode = int(value)
            self._item_panel.update_setting("item_panel_display_mode", value)
        elif key == "theme_mode":
            self._apply_app_theme(self._design)
            self._settings_panel.set_panel_theme_mode(value)
            # system モード時のみ OS テーマ監視を有効化
            if value in ("system", "auto"):
                self._last_os_theme = resolve_theme_mode("system")
                if not self._os_theme_timer.isActive():
                    self._os_theme_timer.start()
            else:
                self._os_theme_timer.stop()

        self._save_config()
        return True

    # ================================================================
    #  項目データ変更ハンドラ
    # ================================================================

    def _on_item_entries_changed(self, entries: list):
        self.apply_action(UpdateItemEntries(entries=tuple(entries)))

    def _update_items_by_action(self, roulette_id: str,
                                entries: list) -> bool:
        """アクション経由の項目データ全件置換。

        Args:
            roulette_id: 対象 ID。空文字なら active を対象にする。
            entries: 置換後の項目データ（list）。

        Returns:
            置換できたら True。
        """
        if roulette_id:
            ctx = self._manager.get(roulette_id)
        else:
            ctx = self._manager.active
        if ctx is None:
            return False
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(
            entries, self._config
        )
        ctx.panel.set_segments(ctx.segments)
        self._save_item_entries()
        # i289 t07: _refresh_panel_tracking はここでは呼ばない。
        # 新規行ウィジェットを追加する set_active_entries 呼び出し元で行う。
        return True

    # ================================================================
    #  パターン管理ハンドラ
    # ================================================================

    def _on_pattern_switched(self, name: str):
        """パターン切替: 項目を切り替えてホイールを更新する。"""
        # 現在のパターンの項目を保存してから切替
        self._save_item_entries()
        set_current_pattern(self._config, name)
        # 新パターンの項目を読み込み
        entries = load_all_item_entries(self._config)
        ctx = self._active_context
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._update_win_counts()

    def _on_pattern_added(self, name: str):
        """パターン追加: 空パターンを作成し、切り替える。"""
        # 現在のパターンの項目を保存
        self._save_item_entries()
        add_pattern(self._config, name)
        set_current_pattern(self._config, name)
        # 空の項目リストで更新
        entries = []
        ctx = self._active_context
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()

    def _on_pattern_deleted(self, name: str):
        """パターン削除: 削除後に残りの先頭パターンに切り替える。"""
        # 現在のパターンを保存してから削除
        self._save_item_entries()
        delete_pattern(self._config, name)
        # 新しい current の項目を読み込み
        new_current = get_current_pattern_name(self._config)
        entries = load_all_item_entries(self._config)
        ctx = self._active_context
        ctx.item_entries = entries
        ctx.segments, _ = build_segments_from_entries(entries, self._config)
        ctx.panel.set_segments(ctx.segments)
        self._settings_panel.set_active_entries(entries)
        # i289 t07: 行ウィジェット再構築後に mouseTracking を再適用する。
        self._refresh_panel_tracking()
        self._settings_panel.set_pattern_list(
            get_pattern_names(self._config), new_current
        )

    # ================================================================
    #  パネル開閉（F1 でトグル）
    # ================================================================

    def _toggle_settings_panel(self):
        if self._settings_panel_visible:
            sp = self._settings_panel
            self._last_sp_w = sp.width()
            self._last_sp_h = sp.height()
            self._last_sp_x = sp.x()
            self._last_sp_y = sp.y()
            self._settings_panel.hide()
            self._settings_panel_visible = False
        else:
            self._show_settings_panel_at_saved_or_default()

    # ================================================================
    #  コンテキストメニュー
    # ================================================================

    def _show_context_menu(self, pos):
        d = self._design
        s = self._settings
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {d.panel};
                color: {d.text};
                font-family: Meiryo;
                font-size: 10pt;
                border: 1px solid {d.separator};
            }}
            QMenu::item:selected {{
                background-color: {d.separator};
            }}
        """)

        spin_action = menu.addAction("  スピン開始 (Space)")
        spin_action.triggered.connect(self._start_spin)
        if self._active_panel.spin_ctrl.is_spinning:
            spin_action.setEnabled(False)

        menu.addSeparator()

        panel_mark = "\u25cf" if self._settings_panel_visible else "  "
        action = menu.addAction(f"{panel_mark} 設定パネルを表示 (F1)")
        action.triggered.connect(self._toggle_settings_panel)

        menu.addSeparator()

        for idx, (label, w, h) in enumerate(SIZE_PROFILES):
            marker = "\u25cf" if idx == s.profile_idx else "  "
            action = menu.addAction(f"{marker} サイズ {label}  ({w} x {h})")
            action.triggered.connect(
                lambda checked, i=idx, ww=w, hh=h: self._set_profile(i, ww, hh)
            )

        menu.addSeparator()

        current_preset = self._design.preset_name
        for name in DESIGN_PRESET_NAMES:
            marker = "\u25cf" if name == current_preset else "  "
            action = menu.addAction(f"{marker} デザイン: {name}")
            action.triggered.connect(
                lambda checked, n=name: self._apply_design_preset(n)
            )

        editor_action = menu.addAction("  デザインエディタ...")
        editor_action.triggered.connect(self._open_design_editor)

        graph_action = menu.addAction("  勝利履歴グラフ...")
        graph_action.triggered.connect(self._open_graph)

        menu.addSeparator()

        mode_names = ["省略", "収める", "縮小"]
        for m, name in enumerate(mode_names):
            marker = "\u25cf" if m == s.text_size_mode else "  "
            action = menu.addAction(f"{marker} テキスト: {name}")
            action.triggered.connect(
                lambda checked, mm=m: self._set_text_size_mode(mm)
            )

        menu.addSeparator()

        donut_mark = "\u25cf" if s.donut_hole else "  "
        action = menu.addAction(f"{donut_mark} ドーナツ穴")
        action.triggered.connect(self._toggle_donut)

        menu.addSeparator()

        # 常に最前面
        aot_mark = "\u25cf" if s.always_on_top else "  "
        action = menu.addAction(f"{aot_mark} 常に最前面")
        action.triggered.connect(self._toggle_always_on_top)

        # リサイズグリップ表示
        grip_mark = "\u25cf" if s.grip_visible else "  "
        action = menu.addAction(f"{grip_mark} リサイズグリップ表示")
        action.triggered.connect(self._toggle_grip_visible)

        # コントロールボックス表示
        cb_mark = "\u25cf" if s.ctrl_box_visible else "  "
        action = menu.addAction(f"{cb_mark} コントロールボックス表示")
        action.triggered.connect(self._toggle_ctrl_box_visible)

        # インスタンス番号表示
        inst_mark = "\u25cf" if s.float_win_show_instance else "  "
        action = menu.addAction(f"{inst_mark} インスタンス番号表示")
        action.triggered.connect(self._toggle_show_instance)

        # 設定パネル独立化
        float_mark = "\u25cf" if s.settings_panel_float else "  "
        action = menu.addAction(f"{float_mark} 設定パネル独立化")
        action.triggered.connect(self._toggle_settings_panel_float)

        menu.addSeparator()

        # マクロ
        macro_menu = menu.addMenu("  マクロ")
        macro_menu.setStyleSheet(menu.styleSheet())

        has_session = self._macro_session.total_count > 0
        session_info = (f" [{self._macro_session.current_index}/"
                        f"{self._macro_session.total_count}]") if has_session else ""

        action = macro_menu.addAction(f"  エディタを開く{session_info}")
        action.triggered.connect(self._dev_show_action_viewer)

        macro_menu.addSeparator()

        action = macro_menu.addAction("  ステップ実行")
        action.triggered.connect(self._dev_step_action)
        action.setEnabled(self._macro_session.has_next())

        action = macro_menu.addAction("  連続実行")
        action.triggered.connect(self._dev_run_until_pause)
        action.setEnabled(self._macro_session.has_next())

        action = macro_menu.addAction("  セッションクリア")
        action.triggered.connect(self._dev_clear_session)
        action.setEnabled(has_session)

        macro_menu.addSeparator()

        # 記録
        is_recording = self._recorder.is_recording
        rec_count = self._recorder.count
        if is_recording:
            rec_label = f"\u25cf 記録停止 ({rec_count} 件記録中)"
            action = macro_menu.addAction(rec_label)
            action.triggered.connect(self._toggle_recording)

            action = macro_menu.addAction(f"  記録プレビュー ({rec_count} 件)")
            action.triggered.connect(self._show_recording_preview)
            action.setEnabled(rec_count > 0)
        else:
            action = macro_menu.addAction("  記録開始")
            action.triggered.connect(self._toggle_recording)
            if rec_count > 0:
                action = macro_menu.addAction(f"  記録プレビュー ({rec_count} 件)")
                action.triggered.connect(self._show_recording_preview)

        macro_menu.addSeparator()

        macro_menu.addAction("  保存...").triggered.connect(self._dev_save_recording)
        macro_menu.addAction("  読込...").triggered.connect(self._dev_load_to_session)

        menu.addSeparator()

        menu.addAction("  終了").triggered.connect(self.close)

        menu.exec(self.mapToGlobal(pos))

    # ================================================================
    #  設定変更アクション（コンテキストメニュー経由）
    # ================================================================

    def _set_profile(self, idx: int, w: int, h: int):
        self._settings.profile_idx = idx
        self._wheel_base_w = w
        self._wheel_base_h = h
        self.resize(w, h)
        self._settings_panel.update_setting("profile_idx", idx)
        self._save_config()

    def _apply_design_preset(self, name: str):
        preset = DESIGN_PRESETS.get(name)
        if preset is None:
            return
        self._design = DesignSettings.from_dict(preset.to_dict())
        self._design.preset_name = name
        self._settings.design_preset_name = name

        self._apply_app_theme(self._design)
        self._active_panel.update_design(self._design)
        self._apply_central_background(self._settings.window_transparent)
        self._settings_panel.update_design(self._design)
        if hasattr(self, "_item_panel") and self._item_panel:
            self._item_panel.update_design(self._design)
        self._save_config()

    def _open_design_editor(self):
        """デザインエディタダイアログを開く（非モーダル）。"""
        from design_editor_dialog import DesignEditorDialog
        if self._design_editor is not None:
            self._design_editor.raise_()
            self._design_editor.activateWindow()
            return
        self._design_editor = DesignEditorDialog(
            self._design, self._preset_mgr, parent=self
        )
        self._design_editor.design_changed.connect(
            self._on_design_editor_changed
        )
        self._design_editor.finished.connect(self._on_design_editor_closed)
        self._design_editor.set_item_count(len(self._active_entries))
        self._design_editor.show()

    def _on_design_editor_changed(self, design: DesignSettings):
        """デザインエディタからの変更を即時反映する。"""
        self._design = DesignSettings.from_dict(design.to_dict())
        self._settings.design_preset_name = design.preset_name
        self._apply_app_theme(self._design)
        self._active_panel.update_design(self._design)
        self._apply_central_background(self._settings.window_transparent)
        self._settings_panel.update_design(self._design)
        if hasattr(self, "_item_panel") and self._item_panel:
            self._item_panel.update_design(self._design)
        self._save_config()

    def _on_design_editor_closed(self):
        """デザインエディタが閉じられた。"""
        self._design_editor = None

    def _open_graph(self):
        """勝利履歴グラフダイアログを開く（非モーダル）。"""
        from graph_dialog import GraphDialog
        if self._graph_dialog is not None:
            self._graph_dialog.raise_()
            self._graph_dialog.activateWindow()
            self._refresh_graph()
            return
        self._graph_dialog = GraphDialog(self._design, parent=self)
        self._graph_dialog.finished.connect(self._on_graph_closed)
        self._refresh_graph()
        self._graph_dialog.show()

    def _on_graph_closed(self):
        """グラフダイアログが閉じられた。"""
        self._graph_dialog = None

    def _refresh_graph(self):
        """グラフダイアログが開いていればデータを更新する。"""
        if self._graph_dialog is None:
            return
        pattern = get_current_pattern_name(self._config)
        counts = self._win_history.count_by_item(pattern)
        total = self._win_history.total_count(pattern)
        # 現在の有効項目リスト順で項目データを構成
        items = []
        for entry in self._active_context.item_entries:
            if entry.enabled:
                name = entry.text
                items.append((name, len(items), counts.get(name, 0)))
        # カウントが0より大きい項目のみ（有効項目に含まれない過去の結果も追加）
        shown_names = {name for name, _, _ in items}
        for name, count in counts.items():
            if name not in shown_names:
                items.append((name, len(items), count))
        self._graph_dialog.update_graph(items, total, pattern)

    # ================================================================
    #  Replay 再生
    # ================================================================

    def _start_replay(self, idx: int = 0):
        """指定インデックスの replay を再生する。

        Args:
            idx: replay records のインデックス（0=最新）
        """
        if self._replay_mgr.is_playing or self._replay_mgr.is_recording:
            return
        if self._active_panel.spin_ctrl.is_spinning:
            return
        if self._replay_mgr.count() == 0:
            return

        # 再生前の状態を退避
        panel = self._active_panel
        self._replay_saved_segments = list(panel.wheel._segments)
        self._replay_saved_angle = panel.wheel._angle
        self._replay_saved_pointer = panel.wheel._pointer_angle
        self._replay_saved_direction = panel.wheel._spin_direction

        # UI ロック
        self._settings_panel.set_spinning(True)
        self._settings_panel.set_replay_playing(True)

        # リプレイ中表示
        if self._settings.replay_show_indicator:
            panel.wheel.set_replay_indicator(True)

        # 再生開始
        ok = self._replay_mgr.start_playback(
            idx, panel.wheel, self._sound
        )
        if not ok:
            self._settings_panel.set_spinning(False)
            self._settings_panel.set_replay_playing(False)
            panel.wheel.set_replay_indicator(False)
            return

    def _on_replay_finished(self, winner: str, winner_idx: int):
        """replay 再生完了時の処理。"""
        panel = self._active_panel

        # 結果表示（win_history / log には記録しない）
        if winner:
            panel.result_overlay.show_result(winner)

        # 結果表示クローズ後に状態復元
        def _restore_after_overlay():
            self._replay_restore_state()

        # ResultOverlay の closed シグナルに一度だけ接続
        def _on_overlay_closed():
            try:
                panel.result_overlay.closed.disconnect(_on_overlay_closed)
            except RuntimeError:
                pass
            _restore_after_overlay()

        if winner:
            panel.result_overlay.closed.connect(_on_overlay_closed)
        else:
            self._replay_restore_state()

    def _replay_restore_state(self):
        """replay 再生後に通常状態へ復元する。"""
        panel = self._active_panel

        # インジケーター消去
        panel.wheel.set_replay_indicator(False)

        # セグメント・角度・ポインターを復元
        if hasattr(self, '_replay_saved_segments'):
            panel.wheel.set_segments(self._replay_saved_segments)
            panel.wheel.set_angle(self._replay_saved_angle)
            panel.wheel.set_pointer_angle(self._replay_saved_pointer)
            panel.wheel._spin_direction = self._replay_saved_direction

        # UI ロック解除
        self._settings_panel.set_spinning(False)
        self._settings_panel.set_replay_playing(False)
        if self._replay_dialog is not None:
            self._replay_dialog.set_playing(False)

    def _cancel_replay(self):
        """進行中の replay を中断する。"""
        if self._replay_mgr.is_playing:
            self._replay_mgr.stop_playback()
            self._replay_restore_state()

    # ================================================================
    #  Replay 管理ダイアログ
    # ================================================================

    def _open_replay_manager(self):
        """リプレイ管理ダイアログを開く（非モーダル）。"""
        from replay_dialog import ReplayDialog
        if self._replay_dialog is not None:
            self._replay_dialog.raise_()
            self._replay_dialog.activateWindow()
            self._replay_dialog.refresh_list(self._replay_mgr.records)
            return
        self._replay_dialog = ReplayDialog(self._design, parent=self)
        self._replay_dialog.play_requested.connect(self._on_replay_dialog_play)
        self._replay_dialog.delete_requested.connect(
            self._on_replay_dialog_delete
        )
        self._replay_dialog.rename_requested.connect(
            self._on_replay_dialog_rename
        )
        self._replay_dialog.keep_requested.connect(
            self._on_replay_dialog_keep
        )
        self._replay_dialog.export_requested.connect(
            self._on_replay_dialog_export
        )
        self._replay_dialog.export_multi_requested.connect(
            self._on_replay_dialog_export_multi
        )
        self._replay_dialog.import_requested.connect(
            self._on_replay_dialog_import
        )
        self._replay_dialog.finished.connect(self._on_replay_dialog_closed)
        self._replay_dialog.refresh_list(self._replay_mgr.records)
        self._replay_dialog.show()

    def _on_replay_dialog_play(self, idx: int):
        """管理ダイアログからの再生リクエスト。"""
        self._start_replay(idx)
        if self._replay_dialog is not None:
            self._replay_dialog.set_playing(self._replay_mgr.is_playing)

    def _on_replay_dialog_delete(self, idx: int):
        """管理ダイアログからの削除リクエスト。"""
        self._replay_mgr.delete(idx)
        self._settings_panel.set_replay_count(self._replay_mgr.count())
        if self._replay_dialog is not None:
            self._replay_dialog.refresh_list(self._replay_mgr.records)

    def _on_replay_dialog_rename(self, idx: int, new_name: str):
        """管理ダイアログからの名称変更リクエスト。"""
        self._replay_mgr.rename(idx, new_name)
        if self._replay_dialog is not None:
            self._replay_dialog.refresh_list(self._replay_mgr.records)

    def _on_replay_dialog_keep(self, idx: int, keep: bool):
        """管理ダイアログからの保持フラグ変更リクエスト。"""
        self._replay_mgr.set_keep(idx, keep)
        if self._replay_dialog is not None:
            self._replay_dialog.refresh_list(self._replay_mgr.records)

    def _on_replay_dialog_export(self, idx: int, path: str):
        """管理ダイアログからの書き出しリクエスト。"""
        from PySide6.QtWidgets import QMessageBox
        ok = self._replay_mgr.export_record(idx, path)
        if self._replay_dialog is not None:
            if ok:
                QMessageBox.information(
                    self._replay_dialog, "書き出し完了",
                    "リプレイを書き出しました。",
                )
            else:
                QMessageBox.warning(
                    self._replay_dialog, "書き出し失敗",
                    "リプレイの書き出しに失敗しました。",
                )

    def _on_replay_dialog_export_multi(self, indices: list, path: str):
        """管理ダイアログからの複数書き出しリクエスト。"""
        from PySide6.QtWidgets import QMessageBox
        ok = self._replay_mgr.export_records(indices, path)
        if self._replay_dialog is not None:
            if ok:
                QMessageBox.information(
                    self._replay_dialog, "書き出し完了",
                    f"{len(indices)}件のリプレイを書き出しました。",
                )
            else:
                QMessageBox.warning(
                    self._replay_dialog, "書き出し失敗",
                    "リプレイの書き出しに失敗しました。",
                )

    def _on_replay_dialog_import(self, paths: list):
        """管理ダイアログからの読み込みリクエスト（複数ファイル対応）。"""
        from PySide6.QtWidgets import QMessageBox
        total_imported = 0
        failed_files = []
        for path in paths:
            count = self._replay_mgr.import_record(path)
            if count > 0:
                total_imported += count
            else:
                import os
                failed_files.append(os.path.basename(path))

        if self._replay_dialog is not None:
            if total_imported > 0:
                self._settings_panel.set_replay_count(self._replay_mgr.count())
                self._replay_dialog.refresh_list(self._replay_mgr.records)
            if total_imported > 0 and not failed_files:
                if total_imported > 1 or len(paths) > 1:
                    QMessageBox.information(
                        self._replay_dialog, "読み込み完了",
                        f"{total_imported}件のリプレイを読み込みました。",
                    )
            elif total_imported > 0 and failed_files:
                QMessageBox.information(
                    self._replay_dialog, "読み込み完了",
                    f"{total_imported}件を読み込みました。\n"
                    f"失敗: {', '.join(failed_files)}",
                )
            else:
                QMessageBox.warning(
                    self._replay_dialog, "読み込み失敗",
                    "リプレイの読み込みに失敗しました。\n"
                    "ファイル形式を確認してください。",
                )

    def _on_replay_dialog_closed(self):
        """リプレイ管理ダイアログが閉じられた。"""
        self._replay_dialog = None

    def _refresh_replay_dialog(self):
        """リプレイ管理ダイアログが開いていれば一覧を更新する。"""
        if self._replay_dialog is not None:
            self._replay_dialog.refresh_list(self._replay_mgr.records)

    def _set_text_size_mode(self, mode: int):
        self._settings.text_size_mode = mode
        self._active_panel.wheel.set_text_mode(mode, self._settings.text_direction)
        self._settings_panel.update_setting("text_size_mode", mode)
        self._save_config()

    def _toggle_donut(self):
        self._settings.donut_hole = not self._settings.donut_hole
        self._active_panel.wheel.set_donut_hole(self._settings.donut_hole)
        self._settings_panel.update_setting("donut_hole", self._settings.donut_hole)
        self._save_config()

    # ================================================================
    #  frameless ウィンドウ — エッジリサイズ
    # ================================================================

    def _edge_at(self, pos) -> int:
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        edge = self._EDGE_NONE
        if x >= w - self._EDGE_SIZE:
            edge |= self._EDGE_RIGHT
        if y >= h - self._EDGE_SIZE:
            edge |= self._EDGE_BOTTOM
        return edge

    def _update_edge_cursor(self, pos):
        edge = self._edge_at(pos)
        if edge == self._EDGE_CORNER:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge == self._EDGE_RIGHT:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == self._EDGE_BOTTOM:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    # ================================================================
    #  入力操作
    #
    #  パネル内のクリックは各パネルが自身で処理する。
    #  MainWindow に届くのは:
    #    - エッジ領域（リサイズ）
    #    - 背景領域（ウィンドウドラッグ移動）
    #    - キーボードイベント
    # ================================================================

    def keyPressEvent(self, event):
        mods = event.modifiers()
        ctrl_shift = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
        )

        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_F1:
            self._toggle_manage_panel()
        elif event.key() == Qt.Key.Key_F2:
            self._toggle_item_panel()
        elif event.key() == Qt.Key.Key_F3:
            self._toggle_settings_panel_v2()
        elif event.key() == Qt.Key.Key_Space:
            self._start_spin()
        # --- 開発用ショートカット（アクション経由） ---
        elif event.key() == Qt.Key.Key_N and (mods & ctrl_shift) == ctrl_shift:
            self.apply_action(AddRoulette())
        elif event.key() == Qt.Key.Key_W and (mods & ctrl_shift) == ctrl_shift:
            self.apply_action(RemoveRoulette(self._manager.active_id))
        elif event.key() == Qt.Key.Key_Period and (mods & ctrl_shift) == ctrl_shift:
            nxt = self._manager.next_id(self._manager.active_id)
            if nxt:
                self.apply_action(SetActiveRoulette(nxt))
        elif event.key() == Qt.Key.Key_Comma and (mods & ctrl_shift) == ctrl_shift:
            prv = self._manager.prev_id(self._manager.active_id)
            if prv:
                self.apply_action(SetActiveRoulette(prv))
        # --- 開発用ショートカット（記録） ---
        elif event.key() == Qt.Key.Key_R and (mods & ctrl_shift) == ctrl_shift:
            self._toggle_recording()
        elif event.key() == Qt.Key.Key_L and (mods & ctrl_shift) == ctrl_shift:
            self._dump_recording()
        # --- 開発用ショートカット（保存/読込/再生） ---
        elif event.key() == Qt.Key.Key_S and (mods & ctrl_shift) == ctrl_shift:
            self._dev_save_recording()
        elif event.key() == Qt.Key.Key_O and (mods & ctrl_shift) == ctrl_shift:
            self._dev_load_to_session()
        elif event.key() == Qt.Key.Key_P and (mods & ctrl_shift) == ctrl_shift:
            self._dev_step_action()
        elif event.key() == Qt.Key.Key_K and (mods & ctrl_shift) == ctrl_shift:
            self._dev_clear_session()
        elif event.key() == Qt.Key.Key_G and (mods & ctrl_shift) == ctrl_shift:
            self._dev_run_until_pause()
        elif event.key() == Qt.Key.Key_V and (mods & ctrl_shift) == ctrl_shift:
            self._dev_show_action_viewer()
        else:
            super().keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()

            # エッジリサイズ
            edge = self._edge_at(pos)
            if edge:
                self._resizing_edge = edge
                self._resize_start = event.globalPosition().toPoint()
                self._resize_start_rect = self.geometry()
                event.accept()
                return

            # 背景ドラッグ → ウィンドウ移動
            self._dragging_window = True
            self._window_drag_start = event.globalPosition().toPoint()
            self._window_drag_start_pos = self.pos()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing_edge:
            delta = event.globalPosition().toPoint() - self._resize_start
            rect = self._resize_start_rect
            new_w = rect.width()
            new_h = rect.height()
            if self._resizing_edge & self._EDGE_RIGHT:
                new_w = max(self.minimumWidth(), rect.width() + delta.x())
            if self._resizing_edge & self._EDGE_BOTTOM:
                new_h = max(self.minimumHeight(), rect.height() + delta.y())
            self.resize(new_w, new_h)
            event.accept()
            return

        if self._dragging_window:
            delta = event.globalPosition().toPoint() - self._window_drag_start
            self.move(self._window_drag_start_pos + delta)
            event.accept()
            return

        # ボタン非押下時: エッジカーソル更新
        if not event.buttons():
            self._update_edge_cursor(event.pos())
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resizing_edge:
                self._resizing_edge = self._EDGE_NONE
                event.accept()
                return
            if self._dragging_window:
                self._dragging_window = False
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """パネル外でのマウスホイール回転を無効化する。"""
        event.accept()
