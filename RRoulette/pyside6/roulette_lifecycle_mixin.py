"""
roulette_lifecycle_mixin.py — ルーレットライフサイクル Mixin

i437: main_window.py から分離。
責務:
  - RoulettePanel の生成 (_create_roulette)
  - 登録・削除 (_add_roulette, _remove_roulette, _add_new_roulette)
  - ID 採番 (_next_roulette_id)
  - 位置計算 (_compute_new_roulette_position)
  - マルチルーレット表示管理 (_update_instance_labels, _update_roulette_manage_panel)
  - ManagePanel コールバック群 (_on_manage_roulette_*)
  - Z オーダー管理 (_bring_panel_to_front)
  - 追加ルーレット復元 (_restore_extra_roulettes, _restore_per_panel_from_entry)

使用側: class MainWindow(RouletteLifecycleMixin, PanelGeometryMixin, QMainWindow)
"""

import os
import uuid as _uuid_mod

from PySide6.QtWidgets import QWidget, QMessageBox

from segment_builder import build_segments_from_config, build_segments_from_entries
from item_data_io import load_all_item_entries
from item_entry import ItemEntry
from pattern_store import get_current_pattern_name, get_pattern_id
from roulette_panel import RoulettePanel
from roulette_context import RouletteContext
from per_roulette_settings import PerRouletteSettings, PER_ROULETTE_KEYS
from spin_effect_settings import SpinEffectSettings
from roulette_actions import UpdateSettings
from panel_widgets import ConfirmOverlay
from replay_manager_pyside6 import ReplayManager
from roulette_actions import SetActiveRoulette


class RouletteLifecycleMixin:
    """RoulettePanel の生存管理責務を MainWindow から分離した Mixin。

    self.* で MainWindow の属性・メソッドを参照するため、
    MainWindow のサブクラスとしてのみ使用可能。
    """

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
        panel.spin_ctrl.set_tick_pattern(self._settings.tick_pattern)
        panel.spin_ctrl.set_win_pattern(self._settings.win_pattern)
        panel.result_overlay.set_close_mode(self._settings.result_close_mode)
        panel.result_overlay.set_hold_sec(self._settings.result_hold_sec)
        # i342: ログ表示 (log_overlay_show) と前面表示 (log_on_top) を分離。
        panel.wheel.set_log_visible(self._settings.log_overlay_show)
        panel.wheel.set_log_timestamp(self._settings.log_timestamp)
        panel.wheel.set_log_box_border(self._settings.log_box_border)
        panel.wheel.set_log_on_top(self._settings.log_on_top)
        panel.wheel.set_log_all_patterns(self._settings.log_history_all_patterns)  # i395: 初期デフォルト（apply_to_panel で上書き）
        panel.spin_ctrl.set_spin_duration(self._settings.spin_duration)
        # i351: ルーレットごとに独立した ReplayManager を生成して紐づける
        _new_rp_path = self._roulette_replay_path(roulette_id)
        _new_rp_mgr = ReplayManager(
            _new_rp_path,
            max_count=self._settings.replay_max_count,
            parent=self,
        )
        _new_rp_mgr.load()
        # i352: roulette_id を lambda でキャプチャして _on_replay_finished へ渡す
        _new_rp_mgr.playback_finished.connect(
            lambda w, wi, rid=roulette_id: self._on_replay_finished(w, wi, rid)
        )
        self._replay_mgrs[roulette_id] = _new_rp_mgr
        panel.spin_ctrl.set_replay_manager(_new_rp_mgr)
        panel.spin_ctrl.set_spin_mode(self._settings.spin_mode)
        panel.spin_ctrl.set_double_duration(self._settings.double_duration)
        panel.spin_ctrl.set_triple_duration(self._settings.triple_duration)
        # v0.6.1: リプレイに特殊演出を記録するか
        panel.spin_ctrl.set_replay_record_effects(
            getattr(self._settings, "replay_record_effects", True)
        )
        panel.set_transparent(self._settings.roulette_transparent)

        # manager 登録
        # i368: PerRouletteSettings を AppSettings から初期化して ctx に持たせる。
        # この時点では AppSettings が source-of-truth のままだが、
        # ctx.settings は保存/復元の入口として使い始める（第2段階で反映経路を移す）。
        self._manager.register(RouletteContext(
            roulette_id=roulette_id,
            panel=panel,
            item_entries=item_entries,
            segments=segments,
            settings=PerRouletteSettings.from_app_settings(self._settings),
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
        panel.graph_requested.connect(self._on_panel_graph_requested)
        panel.in_panel_graph_opened.connect(self._on_in_panel_graph_opened)  # i389
        panel.result_overlay.closed.connect(
            lambda rid=roulette_id: self._on_result_overlay_closed(rid)
        )
        # i070: pointer_move drag release 時の確定 winner を pending に反映
        panel.pointer_move_committed.connect(self._on_pointer_move_committed)
        panel.window_drag_delta.connect(self._on_roulette_window_drag)
        panel.window_resize_needed.connect(self._on_roulette_window_resize)

        # パネル一覧・Z オーダー管理
        self._panels.append(panel)
        panel.geometry_changed.connect(
            lambda p=panel: self._bring_panel_to_front(p)
        )
        # i318: ルーレットパネルの geometry 変化も debounce 保存対象にする
        if hasattr(self, "_panel_save_timer"):
            panel.geometry_changed.connect(self._panel_save_timer.start)
        # i334: multi roulette-only mode 中のウィンドウ境界再計算
        panel.geometry_changed.connect(self._recalc_multi_roulette_only_bounds)

        # 位置・サイズ復元
        self._restore_roulette_panel(panel)

        return panel

    # i425: 新規パネル候補位置のステップ幅（ピクセル）
    _NEW_PANEL_STEP = 40

    def _compute_new_roulette_position(self) -> tuple[int, int]:
        """新規ルーレットの初期位置候補を計算する（i425）。

        表示中の既存ルーレットと重なりにくい位置を返す。
        最終的な境界クランプは _apply_panel_geometry で行われる。

        アルゴリズム:
          - アクティブパネルを基準に (STEP, STEP) ずつ対角方向へずらした候補を順に試す
          - 表示中の既存パネルと重なりが THRESHOLD 未満になった最初の候補を採用する
          - MAX_TRIES 回試して全て重なる場合は最後の候補を返す（clamp に委ねる）
        """
        STEP = self._NEW_PANEL_STEP
        THRESHOLD = STEP  # top-left 間距離がこれ未満なら「重なっている」とみなす
        MAX_TRIES = 8

        # 表示中ルーレットの top-left 座標を収集
        visible_tops: list[tuple[int, int]] = []
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx is not None and ctx.panel.isVisible():
                visible_tops.append((ctx.panel.x(), ctx.panel.y()))

        # 基準: アクティブパネルの位置
        base_x = self._active_panel.x()
        base_y = self._active_panel.y()

        for i in range(1, MAX_TRIES + 1):
            cx = base_x + i * STEP
            cy = base_y + i * STEP
            too_close = any(
                abs(cx - vx) < THRESHOLD and abs(cy - vy) < THRESHOLD
                for vx, vy in visible_tops
            )
            if not too_close:
                return cx, cy

        # 全候補が重なる場合は最後の候補（clamp で補正される）
        return base_x + MAX_TRIES * STEP, base_y + MAX_TRIES * STEP

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

        # i338: default 以外のルーレットは空の項目 + 1パターンで初期化
        if roulette_id != "default":
            ctx = self._manager.get(roulette_id)
            if ctx is not None:
                _default_pid = str(_uuid_mod.uuid4())
                ctx.item_patterns = {"デフォルト": []}
                ctx.current_pattern = "デフォルト"
                ctx.pattern_id_map = {"デフォルト": _default_pid}
                ctx.current_pattern_id = _default_pid
                ctx.item_entries = []
                ctx.segments = []
                ctx.panel.set_segments([])

        # i425: visible 既存パネルと重なりにくい初期位置を計算して適用する
        count = len([p for p in self._panels if isinstance(p, RoulettePanel)])
        if count > 1:
            new_x, new_y = self._compute_new_roulette_position()
            self._apply_panel_geometry(
                panel, new_x, new_y, panel.width(), panel.height(),
                RoulettePanel._MIN_W, RoulettePanel._MIN_H,
            )

        panel.show()
        self._roulette_visible_ids.add(roulette_id)
        # i120: 新規パネルのグリップ表示状態を現在設定に合わせる
        self._sync_roulette_grips_visible()

        if activate:
            self._set_active_roulette(roulette_id)

        self._update_instance_labels()
        self._update_roulette_manage_panel()
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

        self._roulette_visible_ids.discard(roulette_id)
        # i351: 削除された roulette の ReplayManager を破棄する
        self._replay_mgrs.pop(roulette_id, None)
        # i421: 削除した roulette の win_history を消去する。
        # 同じ roulette_id が再採番された場合に削除前履歴が dedup base に混入しないようにする。
        self._win_history.clear(roulette_id=roulette_id)
        self._win_history.save()
        self._manager.unset_name(roulette_id)  # i048: カスタム名のメモリクリーンアップ
        self._update_instance_labels()
        self._update_roulette_manage_panel()
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
    #  ラベル・表示管理
    # ================================================================

    def _roulette_label(self, roulette_id: str) -> str:
        """roulette_id から表示ラベル文字列を返す（i427）。

        i047: カスタム名が設定されていればそれを優先する。
        """
        custom = self._manager.get_name(roulette_id)
        if custom:
            return custom
        if roulette_id == "default":
            return "ルーレット 1"
        if roulette_id.startswith("roulette_"):
            try:
                n = int(roulette_id[len("roulette_"):])
                return f"ルーレット {n}"
            except ValueError:
                pass
        return roulette_id

    def _update_instance_labels(self):
        """全 RoulettePanel のインスタンス番号ラベルを更新する。

        表示条件:
          - float_win_show_instance が ON
          - かつルーレットが2個以上
        単窓時や設定 OFF 時は番号を非表示にする。
        i427: multi 時はタイトルプレートにルーレット名を設定する。
        """
        ids = self._manager.ids()
        show = self._settings.float_win_show_instance and len(ids) > 1
        is_multi = len(ids) > 1
        for i, rid in enumerate(ids):
            ctx = self._manager.get(rid)
            if ctx and ctx.panel:
                ctx.panel.set_instance_label(i + 1 if show else None)
                # i427: multi 時はタイトルプレートにラベルを設定、single なら非表示
                ctx.panel.set_title(self._roulette_label(rid) if is_multi else None)

    # ================================================================
    #  i333: マルチルーレット管理
    # ================================================================

    def _update_roulette_manage_panel(self):
        """ManagePanel のルーレット一覧を現在の状態に合わせて更新する。"""
        if not hasattr(self, "_manage_panel") or not hasattr(self, "_roulette_visible_ids"):
            return
        active_id = self._manager.active_id
        entries = []
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx is None:
                continue
            label = self._roulette_label(rid)
            entries.append({
                "id": rid,
                "label": label,
                "active": rid == active_id,
                "visible": rid in self._roulette_visible_ids,
            })
        self._manage_panel.set_roulette_list(entries)

    def _on_manage_roulette_add(self):
        """ManagePanel の追加ボタンからのコールバック。"""
        self._add_new_roulette(activate=True)

    def _on_manage_roulette_activate(self, roulette_id: str):
        """ManagePanel からのアクティブ切替コールバック。"""
        self.apply_action(SetActiveRoulette(roulette_id))

    def _on_manage_roulette_visibility(self, roulette_id: str, visible: bool):
        """ManagePanel からの表示/非表示切替コールバック。"""
        ctx = self._manager.get(roulette_id)
        if ctx is None:
            return
        if visible:
            self._roulette_visible_ids.add(roulette_id)
            ctx.panel.show()
            # i424: 画面外に出ていた場合にクライアント領域内へクランプする
            p = ctx.panel
            self._apply_panel_geometry(
                p, p.x(), p.y(), p.width(), p.height(),
                RoulettePanel._MIN_W, RoulettePanel._MIN_H,
            )
        else:
            self._roulette_visible_ids.discard(roulette_id)
            ctx.panel.hide()

    def _on_manage_roulette_delete(self, roulette_id: str):
        """ManagePanel からの削除コールバック（i338）。"""
        if self._manager.count <= 1:
            return
        ctx = self._manager.get(roulette_id)
        if ctx is None:
            return
        # 表示名を取得
        label = self._roulette_label(roulette_id)
        reply = QMessageBox.question(
            self, "ルーレット削除",
            f"「{label}」を削除しますか？\nこの操作は取り消せません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._remove_roulette(roulette_id)

    def _on_manage_roulette_rename(self, roulette_id: str, new_name: str) -> None:
        """ManagePanel からの名前変更コールバック（i047）。"""
        new_name = new_name.strip()
        if not new_name:
            return
        self._manager.set_name(roulette_id, new_name)
        # タイトルプレートを即時更新
        ctx = self._manager.get(roulette_id)
        is_multi = self._manager.count > 1
        if ctx and ctx.panel and is_multi:
            ctx.panel.set_title(new_name)
        # 管理パネル一覧を更新
        self._update_roulette_manage_panel()
        # 設定を保存
        self._save_config()

    def _on_manage_apply_to_all_changed(self, value: bool) -> None:
        """ManagePanel の一括適用チェックボックスから: _apply_to_all フラグを更新する（i347）。"""
        self._apply_to_all = value

    # =====================================================================
    #  v0.6.1: 主要セクション初期化 / 全体初期化
    # =====================================================================

    # 各主要セクションが初期化対象とする per-roulette キー一覧
    _SECTION_RESET_KEYS = {
        "spin": [
            "spin_duration", "spin_preset_profile", "spin_preset_random",
            "spin_duration_random", "spin_duration_random_ratio",
            "spin_phase_randomize", "spin_phase_overrides",
            "spin_mode", "double_duration", "triple_duration",
            "profile_idx",
        ],
        "display": [
            "text_size_mode", "text_direction", "donut_hole",
            "pointer_angle", "spin_direction",
        ],
        "result": [
            "result_close_mode", "result_hold_sec",
        ],
        "sound": [
            "sound_tick_enabled", "sound_result_enabled",
            "tick_pattern", "win_pattern",
            "tick_custom_file", "win_custom_file",
        ],
        "log": [
            "log_overlay_show", "log_on_top", "log_timestamp",
            "log_box_border", "log_all_patterns",
        ],
        # v0.6.1: リプレイ初期化ボタンは廃止（履歴クリアは管理画面で行う）
        "effects": [
            "spin_effects",
        ],
    }

    _SECTION_LABELS = {
        "spin": "スピン", "display": "表示", "result": "結果表示",
        "sound": "サウンド", "log": "ログ",
        "effects": "特殊演出（テスト版）",
    }

    def _show_reset_confirm_overlay(self, title: str, body: str, on_ok) -> None:
        """ConfirmOverlay で OBS 可視の確認ダイアログを表示する。

        confirm_reset = False ならスキップして即時 on_ok を実行する。
        """
        if not getattr(self._settings, "confirm_reset", True):
            on_ok()
            return
        parent = self.centralWidget() if hasattr(self, "centralWidget") else self
        if parent is None:
            parent = self
        overlay = ConfirmOverlay(
            title=title,
            body=body,
            buttons=[
                ("初期化する", "ok",     "danger"),
                ("キャンセル", "cancel", "cancel"),
            ],
            design=self._design,
            parent=parent,
        )

        def _on_chosen(v: str):
            if v == "ok":
                try:
                    on_ok()
                except Exception:
                    pass
            overlay.deleteLater()

        overlay.chosen.connect(_on_chosen)
        overlay.show()

    def _on_section_reset_requested(self, section_name: str) -> None:
        """設定パネルの主要セクションヘッダー右の初期化ボタンから。"""
        if section_name == "all":
            # v0.6.1: 設定パネル先頭の「全体初期化」ボタンから（実質 _on_global_reset_requested）
            self._on_global_reset_requested()
            return
        label = self._SECTION_LABELS.get(section_name, section_name)
        scope = "全ルーレット" if getattr(self, "_apply_to_all", False) else "アクティブなルーレット"
        body = f"「{label}」を新規ルーレット作成時の状態に戻します。\n対象: {scope}"
        self._show_reset_confirm_overlay(
            title=f"{label} を初期化",
            body=body,
            on_ok=lambda: self._perform_section_reset(section_name),
        )

    def _perform_section_reset(self, section_name: str) -> None:
        """指定セクションのキー一覧を PerRouletteSettings デフォルトで上書きする。"""
        keys = self._SECTION_RESET_KEYS.get(section_name, [])
        if not keys:
            return
        defaults = PerRouletteSettings()

        # 対象 ctx を決定
        if getattr(self, "_apply_to_all", False):
            target_ids = list(self._manager.ids())
        else:
            target_ids = [self._manager.active_id]

        active_id = self._manager.active_id
        for rid in target_ids:
            ctx = self._manager.get(rid)
            if ctx is None:
                continue
            for k in keys:
                if not hasattr(defaults, k):
                    continue
                default_val = getattr(defaults, k)
                if rid == active_id:
                    # active は dispatch 経由で UI も runtime もまとめて更新
                    self.apply_action(UpdateSettings(key=k, value=default_val))
                else:
                    # 非 active は ctx.settings に書き込みのみ
                    setattr(ctx.settings, k, default_val)
        self._save_config()

    def _on_global_reset_requested(self) -> None:
        """v0.6.1: 管理パネルからの全体初期化要求ハンドラ。"""
        scope = "全ルーレット" if getattr(self, "_apply_to_all", False) else "アクティブなルーレット"
        body = (
            "全設定（スピン・表示・結果表示・サウンド・ログ・特殊演出）を\n"
            f"新規ルーレット作成時の状態に戻します。\n対象: {scope}"
        )
        self._show_reset_confirm_overlay(
            title="全体初期化",
            body=body,
            on_ok=self._perform_global_reset,
        )

    # ── v0.6.1: 管理パネル各グループの初期化 ──

    def _on_ro_only_reset_requested(self) -> None:
        """管理パネル「ルーレット以外非表示時」グループの初期化。"""
        body = "「ルーレット以外非表示時」の表示設定を既定値に戻します。"
        self._show_reset_confirm_overlay(
            title="ルーレット以外非表示時 を初期化",
            body=body,
            on_ok=self._perform_ro_only_reset,
        )

    def _perform_ro_only_reset(self) -> None:
        """v0.6.1: AppSettings 既定値で各キーを上書きし、ManagePanel CB
        と各パネル runtime に即時反映する。
        """
        from app_settings import AppSettings
        d = AppSettings()
        # 内部 short_key → AppSettings 属性
        key_map = {
            "selection_handle":  "roulette_only_show_selection_handle",
            "title_plate":       "roulette_only_show_title_plate",
            "graph_btn":         "roulette_only_show_graph_btn",
            "grip":              "roulette_only_show_grip",
            "log":               "roulette_only_show_log",
            "manage_panel":      "roulette_only_show_manage_panel",
            "items_panel":       "roulette_only_show_items_panel",
            "settings_panel":    "roulette_only_show_settings_panel",
            "execution_panel":   "roulette_only_show_execution_panel",
            "ticket_panel":      "roulette_only_show_ticket_panel",
            "link_panel":        "roulette_only_show_link_panel",
        }
        for short_key, attr in key_map.items():
            if not hasattr(d, attr):
                continue
            default_val = getattr(d, attr)
            # AppSettings 書き込み + roulette_only_mode 中の runtime 反映
            self._on_roulette_only_hide_changed(short_key, default_val)
            # ManagePanel チェックボックス UI を同期
            if hasattr(self._manage_panel, "update_roulette_only_hide"):
                self._manage_panel.update_roulette_only_hide(short_key, default_val)

    def _on_app_settings_reset_requested(self) -> None:
        """管理パネル「アプリ設定」グループの初期化。"""
        body = (
            "アプリ全体に影響する設定（透過/テーマ/動作/音量/リプレイ/\n"
            "自動全面非表示）を既定値に戻します。"
        )
        self._show_reset_confirm_overlay(
            title="アプリ設定 を初期化",
            body=body,
            on_ok=self._perform_app_settings_reset,
        )

    def _perform_app_settings_reset(self) -> None:
        from app_settings import AppSettings
        d = AppSettings()
        keys = [
            # 透過 / 最前面
            "window_transparent", "roulette_transparent",
            "panels_transparent", "always_on_top",
            # テーマ / 動作
            "theme_mode", "confirm_item_delete",
            "float_win_show_instance", "confirm_reset",
            # 音量
            "tick_volume", "win_volume", "effect_volume",
            # リプレイ
            "replay_max_count", "replay_show_indicator",
            "replay_record_effects",
            # 自動全面非表示
            "auto_hide_enabled", "auto_hide_seconds",
            "auto_hide_fade_enabled", "auto_hide_fade_seconds",
            "auto_hide_only_in_roulette_only_mode",
            "auto_hide_after_spin_after_restore",
        ]
        for k in keys:
            if hasattr(d, k):
                self.apply_action(UpdateSettings(key=k, value=getattr(d, k)))
        self._save_config()

    # サブグループ単位の初期化対象キー
    _APP_SUBGROUP_KEYS = {
        "window_display": [
            "window_transparent", "roulette_transparent",
            "panels_transparent", "always_on_top",
        ],
        "theme_action": [
            "theme_mode", "confirm_item_delete",
            "float_win_show_instance", "confirm_reset",
        ],
        "volume": ["tick_volume", "win_volume", "effect_volume"],
        "replay": [
            "replay_max_count", "replay_show_indicator",
            "replay_record_effects",
        ],
        "auto_hide": [
            "auto_hide_enabled", "auto_hide_seconds",
            "auto_hide_fade_enabled", "auto_hide_fade_seconds",
            "auto_hide_only_in_roulette_only_mode",
            "auto_hide_after_spin_after_restore",
        ],
        "link": [
            "link_integration_enabled", "link_integration_port",
            "link_integration_max_hold", "link_panel_show_time",
        ],
    }

    _APP_SUBGROUP_LABELS = {
        "window_display": "ウィンドウ表示",
        "theme_action":   "テーマ・動作",
        "volume":         "音量",
        "replay":         "リプレイ",
        "auto_hide":      "自動全面非表示",
        "link":           "外部連携",
    }

    def _on_app_subgroup_reset_requested(self, sub_key: str) -> None:
        """管理パネル「アプリ設定」内のサブグループ単位の初期化要求。"""
        label = self._APP_SUBGROUP_LABELS.get(sub_key, sub_key)
        body = f"「{label}」の設定を既定値に戻します。"
        self._show_reset_confirm_overlay(
            title=f"{label} を初期化",
            body=body,
            on_ok=lambda: self._perform_app_subgroup_reset(sub_key),
        )

    def _perform_app_subgroup_reset(self, sub_key: str) -> None:
        from app_settings import AppSettings
        d = AppSettings()
        keys = self._APP_SUBGROUP_KEYS.get(sub_key, [])
        if sub_key in ("auto_hide", "link"):
            # auto_hide / link 系は dispatch ルートを経由しないため、
            # ManagePanel ウィジェットを直接更新してシグナル発火経由で適用
            for k in keys:
                if hasattr(d, k):
                    self._set_app_widget(k, getattr(d, k))
        else:
            for k in keys:
                if hasattr(d, k):
                    self.apply_action(UpdateSettings(key=k, value=getattr(d, k)))
        self._save_config()

    def _set_app_widget(self, key: str, value) -> None:
        """auto_hide / link 系 ManagePanel ウィジェットを value に設定し
        既存の toggled / valueChanged シグナルを発火させる。"""
        mp = self._manage_panel
        widget_map = {
            "auto_hide_enabled":         ("_auto_hide_cb", "setChecked", bool),
            "auto_hide_seconds":         ("_auto_hide_spin", "setValue", int),
            "auto_hide_fade_enabled":    ("_auto_hide_fade_cb", "setChecked", bool),
            "auto_hide_fade_seconds":    ("_auto_hide_fade_spin", "setValue", float),
            "auto_hide_only_in_roulette_only_mode":
                ("_auto_hide_roulette_only_cb", "setChecked", bool),
            "auto_hide_after_spin_after_restore":
                ("_auto_hide_after_spin_restore_cb", "setChecked", bool),
            "link_integration_enabled":
                ("_link_int_enabled_cb", "setChecked", bool),
            "link_integration_port":
                ("_link_int_port_spin", "setValue", int),
            "link_integration_max_hold":
                ("_link_int_max_hold_spin", "setValue", int),
            "link_panel_show_time":
                ("_link_int_show_time_cb", "setChecked", bool),
        }
        if key not in widget_map:
            return
        attr, method, cast = widget_map[key]
        w = getattr(mp, attr, None)
        if w is None:
            return
        getattr(w, method)(cast(value))

    def _perform_global_reset(self) -> None:
        """全 per-roulette 設定を PerRouletteSettings デフォルトに戻す。

        AppSettings 側の app-wide 設定（テーマ・透過・最前面・音量等）は
        対象外（管理パネル側で個別管理）。
        """
        defaults = PerRouletteSettings()
        if getattr(self, "_apply_to_all", False):
            target_ids = list(self._manager.ids())
        else:
            target_ids = [self._manager.active_id]
        active_id = self._manager.active_id
        for rid in target_ids:
            ctx = self._manager.get(rid)
            if ctx is None:
                continue
            for k in PER_ROULETTE_KEYS:
                if not hasattr(defaults, k):
                    continue
                default_val = getattr(defaults, k)
                if rid == active_id:
                    self.apply_action(UpdateSettings(key=k, value=default_val))
                else:
                    setattr(ctx.settings, k, default_val)
        self._save_config()

    def _on_roulette_only_hide_changed(self, key: str, value: bool) -> None:
        """管理パネルのルーレット以外非表示時個別設定変更ハンドラ（i463/i464/i466）。"""
        _key_map = {
            "selection_handle":  "roulette_only_show_selection_handle",
            "title_plate":       "roulette_only_show_title_plate",
            "graph_btn":         "roulette_only_show_graph_btn",
            "grip":              "roulette_only_show_grip",
            "log":               "roulette_only_show_log",
            "manage_panel":      "roulette_only_show_manage_panel",
            "items_panel":       "roulette_only_show_items_panel",
            "settings_panel":    "roulette_only_show_settings_panel",
            "execution_panel":   "roulette_only_show_execution_panel",
            "ticket_panel":      "roulette_only_show_ticket_panel",
            "link_panel":        "roulette_only_show_link_panel",
        }
        attr = _key_map.get(key)
        if not attr:
            return
        setattr(self._settings, attr, value)
        self._save_config()
        # i466: roulette_only_mode 中にチェックボックスが変更された場合は即時反映する
        if not self._settings.roulette_only_mode:
            return
        if key == "log":
            # i469: _roulette_only_log_show を更新して _refresh_log_overlay に委ねる。
            for rid in self._manager.ids():
                ctx = self._manager.get(rid)
                if ctx is None or not ctx.panel.isVisible():
                    continue
                panel = ctx.panel
                panel._roulette_only_log_show = value
                panel._refresh_log_overlay()
        elif key == "execution_panel":
            # roulette_only 中に設定変更: 連続抽選パネルの表示/非表示を即時反映
            _dlg = getattr(self, '_seq_dialog', None)
            if _dlg is not None:
                if value:
                    _dlg.show()
                else:
                    _dlg.hide()
        elif key == "ticket_panel":
            # roulette_only 中に設定変更: チケットパネルの表示/非表示を即時反映
            _tp = getattr(self, '_ticket_panel', None)
            if _tp is not None:
                if value:
                    _tp.show()
                else:
                    _tp.hide()
        elif key == "link_panel":
            # roulette_only 中に設定変更: 連携パネルの表示/非表示を即時反映
            _lp = getattr(self, '_link_panel', None)
            if _lp is not None:
                if value:
                    _lp.show()
                else:
                    _lp.hide()

    def _bring_panel_to_front(self, panel):
        """指定パネルを Z オーダーの最前面へ移動する。

        pinned_front パネルは通常パネルより常に上に表示される。
        同カテゴリ内では最後に触ったものが最前面。
        """
        # 通常パネルを先に、pinned パネルを後に raise する
        # （後に raise したものが上に来る）
        # i100: getattr で pinned_front 未定義パネルへの AttributeError を防ぐ
        normal = [p for p in self._panels if p.isVisible() and not getattr(p, "pinned_front", False) and p is not panel]
        pinned = [p for p in self._panels if p.isVisible() and getattr(p, "pinned_front", False) and p is not panel]

        if getattr(panel, "pinned_front", False):
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

    def _restore_extra_roulettes(self, parent: QWidget) -> None:
        """i336: config["roulettes"] から全ルーレットの geometry と追加ルーレットを復元する。

        i337 修正: AppSettings.roulette_panel_x/y はアクティブパネルの位置を保存するため、
        アクティブが "default" 以外だった場合に "default" の復元位置がずれる。
        config["roulettes"] の "default" エントリも _roulette_saved_geometries に記録し、
        _restore_all_panel_geometries で AppSettings の 誤位置を上書きする。
        """
        roulettes_cfg = self._config.get("roulettes", [])
        for entry in roulettes_cfg:
            rid = entry.get("id", "")
            if not rid:
                continue

            # geometry を記録（"default" 含む全エントリ対象）
            x = entry.get("x")
            y = entry.get("y")
            w = entry.get("w")
            h = entry.get("h")
            if None not in (x, y, w, h):
                self._roulette_saved_geometries[rid] = (x, y, w, h)

            if rid == "default":
                # "default" パネル生成は不要だが per-roulette 設定は復元する (i344/i364)
                ctx = self._manager.get("default")
                if ctx is not None:
                    # i047: カスタム名を復元
                    custom_name = entry.get("roulette_name")
                    if custom_name:
                        self._manager.set_name("default", custom_name)
                    log_show = entry.get("log_overlay_show", self._settings.log_overlay_show)
                    log_on_top = entry.get("log_on_top", self._settings.log_on_top)
                    ctx.panel.wheel.set_log_visible(log_show)
                    ctx.panel.wheel.set_log_on_top(log_on_top)
                    self._restore_per_panel_from_entry(ctx.panel, entry, ctx=ctx)  # i368: ctx も渡す
                    # i050/i052: チケットデータを復元
                    ctx.ticket_holdings  = list(entry.get("ticket_holdings", []))
                    ctx.ticket_history   = list(entry.get("ticket_history", []))
                    ctx.ticket_templates = list(entry.get("ticket_templates", []))
                continue

            if self._manager.get(rid) is not None:
                continue
            panel = self._add_roulette(rid, activate=False)
            if panel is None:
                continue
            # i047: カスタム名を復元
            custom_name = entry.get("roulette_name")
            if custom_name:
                self._manager.set_name(rid, custom_name)
            # i338: per-roulette item_patterns + current_pattern を復元
            item_patterns_raw = entry.get("item_patterns")
            current_pat = entry.get("current_pattern", "デフォルト")
            ctx = self._manager.get(rid)
            if ctx is not None and item_patterns_raw is not None:
                ctx.item_patterns = dict(item_patterns_raw)
                ctx.current_pattern = current_pat
                # i407: pattern_id_map を復元する（なければその場で生成）
                _pid_map_raw = entry.get("pattern_ids", {})
                ctx.pattern_id_map = dict(_pid_map_raw)
                for _pname in ctx.item_patterns:
                    if _pname not in ctx.pattern_id_map:
                        ctx.pattern_id_map[_pname] = str(_uuid_mod.uuid4())
                ctx.current_pattern_id = ctx.pattern_id_map.get(current_pat, "")
                if not ctx.current_pattern_id:
                    ctx.current_pattern_id = str(_uuid_mod.uuid4())
                    ctx.pattern_id_map[current_pat] = ctx.current_pattern_id
                # 現在パターンの項目を ItemEntry リストに変換
                raw_items = ctx.item_patterns.get(current_pat, [])
                entries_list = [
                    ItemEntry.from_config_entry(r, keep_disabled=True)
                    for r in raw_items
                ]
                entries_list = [e for e in entries_list if e is not None]
                ctx.item_entries = entries_list
                ctx.segments, _ = build_segments_from_entries(entries_list, self._config)
                ctx.panel.set_segments(ctx.segments)
            elif ctx is not None:
                # 旧形式 or データなし: 空の1パターンで初期化（_add_roulette 時点で済み）
                pass

            # i343: per-roulette ログ設定を復元
            if ctx is not None:
                log_show = entry.get("log_overlay_show", self._settings.log_overlay_show)
                log_on_top = entry.get("log_on_top", self._settings.log_on_top)
                ctx.panel.wheel.set_log_visible(log_show)
                ctx.panel.wheel.set_log_on_top(log_on_top)
                # i407: ログフィルタ用パターン（UUID）を設定
                _rp_pat = ctx.current_pattern or get_current_pattern_name(self._config)
                _rp_pid = ctx.current_pattern_id or get_pattern_id(self._config, _rp_pat)
                ctx.panel.wheel.set_current_pattern(_rp_pat, _rp_pid)
                # i364: per-roulette 実設定の復元（i368: ctx も渡して ctx.settings を同期）
                # i395: log_all_patterns は apply_to_panel() 経由で設定される
                self._restore_per_panel_from_entry(ctx.panel, entry, ctx=ctx)
            # i345: per-roulette ログ自動保存ファイルを復元
            if ctx is not None:
                log_path = self._roulette_log_path(rid)
                if os.path.exists(log_path):
                    ctx.panel.wheel.load_log(log_path)

            # i050/i052: チケットデータを復元
            if ctx is not None:
                ctx.ticket_holdings  = list(entry.get("ticket_holdings", []))
                ctx.ticket_history   = list(entry.get("ticket_history", []))
                ctx.ticket_templates = list(entry.get("ticket_templates", []))

            # i424: 前回非表示だったパネルを非表示に戻す
            if not entry.get("visible", True) and ctx is not None:
                ctx.panel.hide()
                self._roulette_visible_ids.discard(rid)

    def _restore_per_panel_from_entry(self, panel, entry: dict,
                                       ctx=None) -> None:
        """per-roulette 実設定を config エントリから復元する。i364

        _create_roulette() で self._settings から初期化された後、
        config["roulettes"][*] に保存された per-roulette 値で上書きする。
        キーが存在しない（旧形式 config）場合は何もしない（self._settings 値を維持）。
        log_overlay_show / log_on_top は呼び出し元で処理済みのため対象外。

        i368: ctx が渡された場合は ctx.settings も同時に更新する。
        これにより config 読込時に ctx.settings が実態と乖離しない。
        """
        sc = panel.spin_ctrl
        w  = panel.wheel
        ro = panel.result_overlay
        if entry.get("spin_duration") is not None:
            sc.set_spin_duration(entry["spin_duration"])
        if entry.get("spin_mode") is not None:
            sc.set_spin_mode(entry["spin_mode"])
        if entry.get("double_duration") is not None:
            sc.set_double_duration(entry["double_duration"])
        if entry.get("triple_duration") is not None:
            sc.set_triple_duration(entry["triple_duration"])
        if "sound_tick_enabled" in entry:
            sc.set_sound_tick_enabled(entry["sound_tick_enabled"])
        if "sound_result_enabled" in entry:
            sc.set_sound_result_enabled(entry["sound_result_enabled"])
        if "tick_pattern" in entry:
            sc.set_tick_pattern(entry["tick_pattern"])
        if "win_pattern" in entry:
            sc.set_win_pattern(entry["win_pattern"])
        if "spin_direction" in entry:
            w._spin_direction = entry["spin_direction"]
        if "donut_hole" in entry:
            w.set_donut_hole(entry["donut_hole"])
        if "pointer_angle" in entry:
            w.set_pointer_angle(entry["pointer_angle"])
        if "text_size_mode" in entry or "text_direction" in entry:
            w.set_text_mode(
                entry.get("text_size_mode", w._text_size_mode),
                entry.get("text_direction",  w._text_direction),
            )
        if "log_timestamp" in entry:
            w.set_log_timestamp(entry["log_timestamp"])
        if "log_box_border" in entry:
            w.set_log_box_border(entry["log_box_border"])
        if "log_all_patterns" in entry:
            # i398: per-roulette 設定をホイールウィジェットへ反映（i395 で ctx.settings への
            # 書き込みは from_config_entry で済んでいたが、wheel への set が欠落していた）
            w.set_log_all_patterns(entry["log_all_patterns"])
        if "result_close_mode" in entry:
            ro.set_close_mode(entry["result_close_mode"])
        if "result_hold_sec" in entry:
            ro.set_hold_sec(entry["result_hold_sec"])
        if "spin_effects" in entry:
            panel.set_effect_settings(SpinEffectSettings.from_dict(entry["spin_effects"]))
        # i368: ctx.settings を config エントリと整合させる（キー欠落は既存値を維持）
        if ctx is not None:
            ctx.settings = PerRouletteSettings.from_config_entry(
                entry, fallback=ctx.settings
            )
