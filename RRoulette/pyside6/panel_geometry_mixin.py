"""
panel_geometry_mixin.py — パネル管理・ジオメトリ復元・保存 Mixin

i436: main_window.py から分離。
責務:
  - 内部パネル (ItemPanel / SettingsPanel / ManagePanel) の表示管理・位置復元・保存
  - ウィンドウ geometry の復元・保存
  - show / move / resize / close イベントハンドラ

使用側: class MainWindow(PanelGeometryMixin, QMainWindow)
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from bridge import MIN_W, MIN_H
from roulette_panel import RoulettePanel
from panel_input_filter import PANEL_BAR_HEIGHT


class PanelGeometryMixin:
    """MainWindow に mix-in するパネル管理・ジオメトリ群。

    self.* で MainWindow の属性・メソッドを参照するため、
    MainWindow のサブクラスとしてのみ使用可能。
    """

    # ================================================================
    #  ウィンドウ / パネル配置の復元・保存
    # ================================================================

    def _restore_window_geometry(self, default_w: int, default_h: int):
        """保存済みウィンドウ位置・サイズを復元する。"""
        s = self._settings
        if s.window_width is not None and s.window_height is not None:
            w, h = s.window_width, s.window_height
        else:
            # 初回起動または保存なし: 横長レイアウト用の初期サイズ
            w, h = self._INITIAL_W, self._INITIAL_H
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
        else:
            # 初回起動または保存位置なし: メインディスプレイの利用可能領域の中央に表示
            avail = self._get_available_geometry()
            if avail is not None:
                cx = avail.x() + (avail.width() - w) // 2
                cy = avail.y() + (avail.height() - h) // 2
                self.move(cx, cy)

    def _restore_roulette_panel(self, panel: RoulettePanel | None = None):
        """ルーレットパネルの位置・サイズを復元する。"""
        if panel is None:
            panel = self._roulette_panel
        s = self._settings
        parent = self.centralWidget()
        # i318: centralWidget は __init__ 中（show 前）は Qt の既定サイズ（640×480 等）
        # を返すため、_default_panel_positions と同様に resize() 済みの
        # self.width()/height() を併用して大きい方を採用する。
        # これにより初期サイズ計算・クランプが正しくなり、保存サイズが
        # stale な centralWidget サイズで潰される不具合も修正される。
        if parent:
            pw = max(parent.width(), self.width(), 1)
            ph = max(parent.height(), self.height(), 1)
        else:
            pw = max(self.width(), 1)
            ph = max(self.height(), 1)
        if pw < 100:
            pw = max(self.width(), self._INITIAL_W)
        if ph < 100:
            ph = max(self.height(), self._INITIAL_H)
        m = 2
        bar_h = PANEL_BAR_HEIGHT  # ドラッグバーの高さ (パネルはこの下から配置)

        rp_x = s.roulette_panel_x if s.roulette_panel_x is not None else m
        rp_y = s.roulette_panel_y if s.roulette_panel_y is not None else bar_h + m
        # 初回起動 / 保存なし: ドラッグバー下の領域を正方形基準で確保する
        rp_default_size = min(pw, ph - bar_h) - 2 * m
        rp_w = s.roulette_panel_width if s.roulette_panel_width is not None else rp_default_size
        rp_h = s.roulette_panel_height if s.roulette_panel_height is not None else rp_default_size

        rp_w = max(RoulettePanel._MIN_W, min(rp_w, pw))
        rp_h = max(RoulettePanel._MIN_H, min(rp_h, ph - bar_h))
        rp_x = max(0, min(rp_x, pw - rp_w))
        rp_y = max(bar_h, min(rp_y, ph - rp_h))

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

        bar_h = PANEL_BAR_HEIGHT  # ドラッグバーの高さ (パネルはこの下から配置)
        panel_top = bar_h + 4  # パネル配置の上端 y 座標

        # ManagePanel: 左上（i348: 高さを増やしスクロール込みで十分な初期サイズに）
        mp_w, mp_h = 260, 320
        mp_x = 12
        mp_y = panel_top

        # ItemPanel: ルーレット正方形領域の右隣に配置（v0.4.4 再現: 左ルーレット・右項目）
        # ルーレットのデフォルト幅 = min(cw, ch - bar_h) - 4（ドラッグバー下領域の正方形）
        rp_default_size = min(cw, ch - bar_h) - 4
        rp_right = rp_default_size + 4  # ルーレット右端 x 座標 (= rp_x + rp_w = 2 + size)
        ip_x = rp_right + 8
        ip_w = max(260, cw - ip_x - 12)
        # i315: 上限を撤廃し、詳細モードで全要素がスクロールなく収まる高さを確保する
        ip_h = max(220, (ch - bar_h) - 24)
        ip_y = panel_top

        # SettingsPanel: 右寄り
        sp_w = min(320, max(260, cw - 24))
        sp_h = min(480, max(220, (ch - bar_h) - 24))
        sp_x = max(0, cw - sp_w - 12)
        sp_y = panel_top

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
        # i339: 移動バーの下端（bar_h）より上にはパネルが入らないようにする
        bar_h = PANEL_BAR_HEIGHT
        x = max(0, min(x, max(0, cw - w)))
        y = max(bar_h, min(y, max(bar_h, ch - h)))
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
        self._apply_panel_geometry(self._manage_panel, mp_x, mp_y, mp_w, mp_h, 240, 220)
        if s.manage_panel_visible:
            self._manage_panel.show()
            self._manage_panel.raise_()
            self._manage_panel_visible = True

        # i336: 追加ルーレットの位置復元
        for rid, (rx, ry, rw, rh) in getattr(self, "_roulette_saved_geometries", {}).items():
            ctx = self._manager.get(rid)
            if ctx is None:
                continue
            self._apply_panel_geometry(
                ctx.panel, rx, ry, rw, rh,
                RoulettePanel._MIN_W, RoulettePanel._MIN_H,
            )

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
        self._apply_panel_geometry(self._manage_panel, mp_x, mp_y, mp_w, mp_h, 240, 220)
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
        # ルーレットパネル — i318: geometry_changed トリガーで debounce 保存
        rp = getattr(self, "_active_panel", None)
        if rp is not None:
            s.roulette_panel_x = rp.x()
            s.roulette_panel_y = rp.y()
            s.roulette_panel_width = rp.width()
            s.roulette_panel_height = rp.height()
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

        # i336/i338: マルチルーレット構成を config["roulettes"] に保存
        roulettes_cfg = []
        for rid in self._manager.ids():
            ctx = self._manager.get(rid)
            if ctx is None:
                continue
            p = ctx.panel
            if ctx.item_patterns is not None:
                # i338: non-default ルーレット — 現在の項目を per-roulette パターンにフラッシュ
                pat = ctx.current_pattern or "デフォルト"
                ctx.item_patterns[pat] = [e.to_dict() for e in ctx.item_entries]
                entry = {
                    "id": rid,
                    "x": p.x(), "y": p.y(), "w": p.width(), "h": p.height(),
                    "current_pattern": ctx.current_pattern or "デフォルト",
                    "item_patterns": ctx.item_patterns,
                    "pattern_ids": ctx.pattern_id_map,  # i407: pattern_id_map を保存
                }
            else:
                # default ルーレット: items はグローバル config に保存済み
                entry = {
                    "id": rid,
                    "x": p.x(), "y": p.y(), "w": p.width(), "h": p.height(),
                }
            # i424: 表示/非表示状態を保存（再起動後に非表示を維持するため）
            entry["visible"] = rid in self._roulette_visible_ids
            # i343: per-roulette ログ設定を保存
            entry["log_overlay_show"] = p.wheel._log_visible
            entry["log_on_top"] = p.wheel._log_on_top
            # i364: per-roulette 実設定を保存（スピン・サウンド・表示・結果表示）
            entry["spin_preset_name"]   = p.spin_ctrl.preset_name
            entry["spin_duration"]      = p.spin_ctrl._spin_duration
            entry["spin_mode"]          = p.spin_ctrl._spin_mode
            entry["double_duration"]    = p.spin_ctrl._double_duration
            entry["triple_duration"]    = p.spin_ctrl._triple_duration
            entry["sound_tick_enabled"]   = p.spin_ctrl._sound_tick_enabled
            entry["sound_result_enabled"] = p.spin_ctrl._sound_result_enabled
            entry["spin_direction"]  = p.wheel._spin_direction
            entry["donut_hole"]      = p.wheel._donut_hole
            entry["pointer_angle"]   = p.wheel._pointer_angle
            entry["text_size_mode"]  = p.wheel._text_size_mode
            entry["text_direction"]  = p.wheel._text_direction
            entry["log_timestamp"]   = p.wheel._log_timestamp
            entry["log_box_border"]  = p.wheel._log_box_border
            entry["result_close_mode"] = p.result_overlay._close_mode
            entry["result_hold_sec"]   = p.result_overlay._hold_sec
            roulettes_cfg.append(entry)
        self._config["roulettes"] = roulettes_cfg

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
            # i333: 初期ルーレット一覧と active 状態を反映
            self._update_roulette_manage_panel()
            active_id = self._manager.active_id
            if active_id:
                ctx = self._manager.get(active_id)
                if ctx and ctx.panel:
                    ctx.panel.set_active(True)
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
            # i345: 復元後に SettingsPanel 表示を active ルーレットの実状態に合わせる
            try:
                self._sync_settings_to_active()
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
        # 移動バーをウィンドウ幅に追従させ、常に最前面に置く
        # roulette_only_mode 中はドラッグバーを非表示のまま再配置のみスキップ
        if (hasattr(self, "_mw_drag_bar")
                and not getattr(self._settings, "roulette_only_mode", False)):
            self._mw_drag_bar.setGeometry(
                0, 0, self.width(), PANEL_BAR_HEIGHT
            )
            self._mw_drag_bar.raise_()
        # 通常リサイズ時もサイズを保存対象にする
        if not getattr(self, "_init_complete", False):
            return
        if self.isMinimized():
            return
        s = self._settings
        s.window_width = self.width()
        s.window_height = self.height()
        self._panel_save_timer.start()
