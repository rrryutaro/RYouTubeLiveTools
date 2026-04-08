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

from PySide6.QtCore import Qt, QTimer, QPoint, QRect
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QMenu, QApplication,
)

from bridge import (
    SIZE_PROFILES, MIN_W, MIN_H, VERSION,
    DesignSettings, DESIGN_PRESET_NAMES, DESIGN_PRESETS,
    load_config, load_design,
    load_all_item_entries, load_app_settings,
    build_segments_from_config, build_segments_from_entries,
    save_config, save_item_entries,
)
from app_settings import AppSettings
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
from settings_panel import SettingsPanel
from spin_preset import SPIN_PRESET_NAMES, DEFAULT_PRESET_NAME
from sound_manager import SoundManager


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

        # --- 既存設定の読み込み ---
        self._config = load_config()
        self._settings = load_app_settings(self._config)
        self._design = load_design(self._config)

        # --- ルーレットマネージャー・パネル一覧 ---
        self._manager = RouletteManager(parent=self)
        self._manager.active_changed.connect(self._on_active_changed)
        self._panels: list[QWidget] = []

        self.setWindowTitle(f"RRoulette (PySide6 Proto) v{VERSION}")
        self.setMinimumSize(MIN_W, MIN_H)

        # frameless + always_on_top
        self._apply_window_flags()

        # サイズプロファイル（保存値が無い場合のデフォルト）
        prof_idx = min(self._settings.profile_idx, len(SIZE_PROFILES) - 1)
        _, default_w, default_h = SIZE_PROFILES[prof_idx]
        self._wheel_base_w = default_w
        self._wheel_base_h = default_h

        # ウィンドウサイズ・位置の復元
        self._restore_window_geometry(default_w, default_h)

        # --- 中央ウィジェット（レイアウトなし — パネルを手動配置） ---
        central = QWidget()
        central.setStyleSheet(f"background-color: {self._design.bg};")
        central.setMouseTracking(True)
        self.setCentralWidget(central)

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

        # 直前当選結果（manual / macro 共通）
        self._last_spin_result: LastSpinResult | None = None

        # ============================================================
        #  サウンド
        # ============================================================

        self._sound = SoundManager()

        # ============================================================
        #  ルーレットパネル（独立パネル）
        # ============================================================

        self._roulette_panel = self._create_roulette("default", central)

        # ============================================================
        #  項目設定パネル（独立パネル）
        # ============================================================

        self._settings_panel = SettingsPanel(
            self._active_context.item_entries, self._settings, self._design,
            parent=central,
        )
        self._settings_panel_visible = False
        self._settings_panel.hide()

        self._settings_panel.spin_requested.connect(self._start_spin)
        self._settings_panel.preset_changed.connect(self._on_preset_changed)
        self._settings_panel.setting_changed.connect(self._on_setting_changed)
        self._settings_panel.item_entries_changed.connect(
            self._on_item_entries_changed
        )

        self._restore_settings_panel_visibility()

        # --- パネル一覧（Z オーダー管理対象）に SettingsPanel を追加 ---
        self._panels.append(self._settings_panel)
        self._settings_panel.geometry_changed.connect(
            lambda: self._bring_panel_to_front(self._settings_panel)
        )

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

    def _update_title_active_id(self):
        """開発確認用: ウィンドウタイトル末尾に active ID と recording 状態を反映する。"""
        base = f"RRoulette (PySide6 Proto) v{VERSION}"
        parts = []
        active_id = self._manager.active_id
        if active_id:
            parts.append(active_id)
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

    def _dev_step_action(self):
        """開発確認用: session から次の1件を取り出して apply_action する。"""
        if not self._macro_session.has_next():
            print("[dev] no more actions to step")
            return
        action = self._macro_session.pop_next()

        # BranchOnWinner は apply_action に渡さず直接処理
        if isinstance(action, BranchOnWinner):
            ok = self._handle_branch_on_winner(action)
            if not ok:
                print("[dev] step branch FAILED — stopped")
            self._update_title_active_id()
            return

        from roulette_action_codec import action_to_dict
        print(f"[dev] step [{self._macro_session.current_index}/{self._macro_session.total_count}] {action_to_dict(action)}")
        ok = self.apply_action(action, origin=ActionOrigin.MACRO)
        if not ok:
            self._macro_session.rewind_one()
            print(f"[dev] step FAILED — index rewound to {self._macro_session.current_index}")
        self._update_title_active_id()

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
            parent=self,
        )
        viewer.setWindowTitle(f"Macro Action Viewer (dev) — {source}: {len(actions)} actions")
        viewer.exec()
        self._update_title_active_id()

    def _is_any_spinning(self) -> bool:
        """いずれかの roulette が spinning 中かを返す。"""
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx and ctx.panel.spin_ctrl.is_spinning:
                return True
        return False

    def _dev_run_until_pause(self):
        """開発確認用: session を安全に進められる範囲まで連続実行する。

        SpinRoulette 成功時は待機状態に入り、spin 完了後に自動再開する。

        停止条件:
          1. session が空になった
          2. apply_action() が False を返した
          3. SpinRoulette を成功実行した直後 → 待機状態に入って return
          4. いずれかの roulette が spinning 中
        """
        if not self._macro_session.has_next():
            print("[dev] run: no actions in session")
            self._stop_auto_advance()
            return
        if self._is_any_spinning():
            print("[dev] run: blocked — spinning in progress")
            return

        # auto advance 開始
        self._macro_auto_advancing = True

        from roulette_action_codec import action_to_dict
        executed = 0

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
                return  # ResultOverlay.closed で _try_resume_macro_after_overlay が呼ばれる

            # spinning が始まっていたら安全側で停止
            if self._is_any_spinning():
                print(f"[dev] run: paused — spinning detected ({executed} executed)")
                self._stop_auto_advance()
                break
        else:
            print(f"[dev] run: completed all ({executed} executed)")
            self._stop_auto_advance()

        self._update_title_active_id()

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

        # match_mode に応じた条件判定
        mode = branch.match_mode or "exact"
        if mode == "regex":
            try:
                flags = re.IGNORECASE if branch.regex_ignore_case else 0
                matched = bool(re.search(branch.winner_text, result.winner_text, flags))
            except re.error:
                print(f"[dev] branch: STOPPED — invalid regex: {branch.winner_text!r}")
                return False
        elif mode == "contains":
            matched = branch.winner_text in result.winner_text
        else:
            matched = result.winner_text == branch.winner_text

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

    def _stop_auto_advance(self):
        """auto advance 状態を全てクリアする。"""
        self._macro_auto_advancing = False
        self._macro_waiting_spin = False
        self._macro_waiting_roulette_id = None

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

    def _save_config(self):
        """アプリ設定・デザイン設定を config に書き戻して保存する。"""
        self._config.update(self._settings.to_config_patch())
        if self._design:
            self._config["design"] = self._design.to_dict()
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

    def _toggle_always_on_top(self):
        """常に最前面の ON/OFF を切り替える。"""
        self._settings.always_on_top = not self._settings.always_on_top
        was_visible = self.isVisible()
        self._apply_window_flags()
        if was_visible:
            self.show()  # setWindowFlags 後に再表示が必要
        self._save_config()

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

        if s.window_x is not None and s.window_y is not None:
            x, y = s.window_x, s.window_y
            x, y = self._clamp_position(x, y, w, h)
            self.move(x, y)

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

    def _restore_settings_panel_visibility(self):
        """項目設定パネルの表示状態と位置を復元する。"""
        s = self._settings

        if s.item_panel_width is not None:
            self._last_sp_w = max(self._settings_panel._panel_min_w, s.item_panel_width)
        if s.item_panel_height is not None:
            self._last_sp_h = s.item_panel_height
        if s.item_panel_x is not None:
            self._last_sp_x = s.item_panel_x
        if s.item_panel_y is not None:
            self._last_sp_y = s.item_panel_y

        if s.item_panel_visible:
            self._show_settings_panel_at_saved_or_default()

    def _show_settings_panel_at_saved_or_default(self):
        """項目設定パネルを保存位置またはデフォルト位置で表示する。"""
        panel_min = self._settings_panel._panel_min_w
        parent = self.centralWidget()
        pw = parent.width() if parent else self.width()
        ph = parent.height() if parent else self.height()
        m = 2

        sp_w = getattr(self, '_last_sp_w', panel_min)
        sp_h = getattr(self, '_last_sp_h', ph - 2 * m)
        sp_x = getattr(self, '_last_sp_x', pw - sp_w - m)
        sp_y = getattr(self, '_last_sp_y', m)

        sp_w = max(panel_min, min(sp_w, pw))
        sp_h = max(100, min(sp_h, ph))
        sp_x = max(0, min(sp_x, pw - sp_w))
        sp_y = max(0, min(sp_y, ph - sp_h))

        self._settings_panel.setGeometry(sp_x, sp_y, sp_w, sp_h)
        self._settings_panel.show()
        self._settings_panel.raise_()
        self._settings_panel_visible = True

    def _clamp_position(self, x: int, y: int, w: int, h: int) -> tuple[int, int]:
        """ウィンドウ位置を画面内に収まるよう補正する。"""
        min_visible_w = 100
        min_visible_top = 30

        screens = QApplication.screens()
        for screen in screens:
            sg = screen.availableGeometry()
            if (x + min_visible_w > sg.x() and x < sg.x() + sg.width() and
                    y + min_visible_top > sg.y() and y < sg.y() + sg.height()):
                x = max(sg.x() - w + min_visible_w, min(x, sg.x() + sg.width() - min_visible_w))
                y = max(sg.y(), min(y, sg.y() + sg.height() - min_visible_top))
                return x, y

        avail = self._get_available_geometry()
        if avail is not None:
            x = avail.x() + (avail.width() - w) // 2
            y = avail.y() + (avail.height() - h) // 2
        return x, y

    def _get_available_geometry(self):
        screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _save_window_state(self):
        """現在のウィンドウ・パネル状態を保存する。"""
        pos = self.pos()
        s = self._settings
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

        # 項目設定パネル
        if self._settings_panel_visible:
            sp = self._settings_panel
            s.item_panel_width = sp.width()
            s.item_panel_height = sp.height()
            s.item_panel_x = sp.x()
            s.item_panel_y = sp.y()
        else:
            for attr, key in [('_last_sp_w', 'item_panel_width'),
                              ('_last_sp_h', 'item_panel_height'),
                              ('_last_sp_x', 'item_panel_x'),
                              ('_last_sp_y', 'item_panel_y')]:
                val = getattr(self, attr, None)
                if val is not None:
                    setattr(s, key, val)

        s.item_panel_visible = self._settings_panel_visible
        self._save_config()

    def closeEvent(self, event):
        self._save_window_state()
        super().closeEvent(event)

    # ================================================================
    #  初期表示・リサイズ
    # ================================================================

    def showEvent(self, event):
        super().showEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            size = max(event.size().width(), event.size().height())
            self.blockSignals(True)
            self.resize(size, size)
            self.blockSignals(False)

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
        # auto advance の再開は ResultOverlay.closed で行う（spin_finished 直後ではなく
        # 結果表示の hold 完了後に再開するため）

    def _on_pointer_angle_changed(self, angle: float):
        self._settings.pointer_angle = angle
        self._settings_panel.update_setting("pointer_angle", angle)

    def _on_pointer_angle_committed(self):
        self._save_config()

    def _on_preset_changed(self, name: str):
        self._active_panel.spin_ctrl.set_spin_preset(name)
        self._settings.spin_preset_name = name
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
        return True

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

        self._active_panel.update_design(self._design)
        self.centralWidget().setStyleSheet(f"background-color: {self._design.bg};")
        self._settings_panel.update_design(self._design)
        self._save_config()

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
            self._toggle_settings_panel()
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
