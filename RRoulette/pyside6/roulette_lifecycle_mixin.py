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

from bridge import (
    build_segments_from_config, build_segments_from_entries,
    load_all_item_entries, ItemEntry,
    get_current_pattern_name, get_pattern_id,
)
from roulette_panel import RoulettePanel
from roulette_context import RouletteContext
from per_roulette_settings import PerRouletteSettings
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
        if self._settings.spin_preset_name:
            panel.spin_ctrl.set_spin_preset(self._settings.spin_preset_name)
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
        """roulette_id から表示ラベル文字列を返す（i427）。"""
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
            # 表示名: roulette_id がシンプルなら番号で表示
            if rid == "default":
                label = "ルーレット 1"
            elif rid.startswith("roulette_"):
                try:
                    n = int(rid[len("roulette_"):])
                    label = f"ルーレット {n}"
                except ValueError:
                    label = rid
            else:
                label = rid
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

    def _on_manage_apply_to_all_changed(self, value: bool) -> None:
        """ManagePanel の一括適用チェックボックスから: _apply_to_all フラグを更新する（i347）。"""
        self._apply_to_all = value

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
                    log_show = entry.get("log_overlay_show", self._settings.log_overlay_show)
                    log_on_top = entry.get("log_on_top", self._settings.log_on_top)
                    ctx.panel.wheel.set_log_visible(log_show)
                    ctx.panel.wheel.set_log_on_top(log_on_top)
                    self._restore_per_panel_from_entry(ctx.panel, entry, ctx=ctx)  # i368: ctx も渡す
                continue

            if self._manager.get(rid) is not None:
                continue
            panel = self._add_roulette(rid, activate=False)
            if panel is None:
                continue
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
        if entry.get("spin_preset_name") is not None:
            sc.set_spin_preset(entry["spin_preset_name"])
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
        # i368: ctx.settings を config エントリと整合させる（キー欠落は既存値を維持）
        if ctx is not None:
            ctx.settings = PerRouletteSettings.from_config_entry(
                entry, fallback=ctx.settings
            )
