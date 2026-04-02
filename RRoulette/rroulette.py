"""
RRoulette — ルーレットアプリ
  - セグメントの追加・削除
  - ルーレットを回してランダムに選択
  - 効果音（スピン中のティック音・決定音）をプログラムで生成（ライセンスフリー）
  - 音のオン/ミュート切り替え
  - タイトルバー非表示（カスタムバーなし）
  - 右クリックコンテキストメニューで設定・サイズ変更
  - クライアント領域ドラッグで移動
  - ウィンドウリサイズグリップ
  - サイズプロファイル（S/M/L）
  - 設定パネル表示/非表示
"""

import tkinter as tk
import tkinter.ttk as ttk
import json

from sound_manager import SoundManager
from config_utils import BASE_DIR, CONFIG_FILE, _is_on_any_monitor, _parse_geometry
from constants import (
    BG, PANEL, ACCENT, DARK2, WHITE,
    SIZE_PROFILES, MIN_W, MIN_H,
    SIDEBAR_W, CFG_PANEL_W, MAIN_PANEL_PAD,
    POINTER_PRESET_NAMES, _POINTER_PRESET_ANGLES, _ADD_SENTINEL,
)
from wheel_renderer import WheelRendererMixin
from spin_engine import SpinEngineMixin
from cfg_panel import CfgPanelMixin, _SETTINGS_DEFAULTS
from item_list import ItemListMixin
from window_manager import WindowManagerMixin
from history_manager import HistoryManagerMixin
from tooltip_utils import _SimpleTooltip


# ════════════════════════════════════════════════════════════════════
#  ItemEntry ヘルパー関数
# ════════════════════════════════════════════════════════════════════

def _make_entry(text):
    """テキストからデフォルト設定の ItemEntry dict を作成する。"""
    return {"text": text, "enabled": True, "prob_mode": None, "prob_value": None, "split_count": 1}


def _ensure_entries(raw_items):
    """旧 list[str] 形式を list[dict] (ItemEntry) 形式に変換する。"""
    if not raw_items:
        return []
    if isinstance(raw_items[0], str):
        return [_make_entry(t) for t in raw_items]
    return [dict(e) for e in raw_items]


def _calc_probs(entries):
    """有効な entries リストの各エントリーの確率 (%) を計算して返す。"""
    n = len(entries)
    if n == 0:
        return []

    fixed_idx    = [i for i, e in enumerate(entries) if e.get("prob_mode") == "fixed"]
    nonfixed_idx = [i for i, e in enumerate(entries) if e.get("prob_mode") != "fixed"]

    sum_fixed = sum(entries[i].get("prob_value") or 0.0 for i in fixed_idx)
    sum_fixed = min(sum_fixed, 99.999)
    remaining = 100.0 - sum_fixed

    weights = []
    for i in nonfixed_idx:
        e = entries[i]
        if e.get("prob_mode") == "weight" and e.get("prob_value") is not None:
            weights.append(max(0.0001, float(e["prob_value"])))
        else:
            weights.append(1.0)
    total_w = sum(weights) or 1.0

    probs = [0.0] * n
    for i in fixed_idx:
        probs[i] = float(entries[i].get("prob_value") or 0.0)
    for j, i in enumerate(nonfixed_idx):
        probs[i] = remaining * weights[j] / total_w
    return probs


def _apply_split(entries_with_probs):
    """
    entries_with_probs: list of (entry_dict, orig_idx_in_item_entries, prob_pct)
    Returns: list of (text, orig_item_idx, arc_degrees)
    """
    raw = []
    for entry, orig_idx, prob in entries_with_probs:
        k = max(1, min(10, int(entry.get("split_count") or 1)))
        sub_arc = prob * 360.0 / 100.0 / k
        for _ in range(k):
            raw.append((entry["text"], orig_idx, sub_arc))
    return raw


def _standard_order(raw_segs):
    """
    raw_segs: list of (text, item_idx, arc)
    分割された項目を均等分散配置し、残りを順番に埋めた並び順を返す。

    単一 split — Bresenham 法:
      F 個のフィラーを K 個のギャップへ floor((k+1)*F/K) - floor(k*F/K) で均等割りし、
      split 片を最大限均等に散らす。1-step lookahead より大域的に最適。

    複数 split — 位相ずらし greedy:
      複数 split 項目がある場合、各項目に total_arc 上での位相オフセットを与え
      目標中心角が重ならないよう分散させる。
      タイブレーク時は filler を優先して split 片の局所集中を防ぐ。
    """
    T = len(raw_segs)
    if T == 0:
        return []

    seen   = []
    by_idx = {}
    for text, idx, arc in raw_segs:
        if idx not in by_idx:
            by_idx[idx] = []
            seen.append(idx)
        by_idx[idx].append((text, idx, arc))

    split_idxs    = [i for i in seen if len(by_idx[i]) > 1]
    nonsplit_idxs = [i for i in seen if len(by_idx[i]) == 1]

    if not split_idxs:
        return list(raw_segs)

    fillers = [by_idx[i][0] for i in nonsplit_idxs]

    # ── 単一 split: Bresenham 法で最適配置 ──────────────────────────
    if len(split_idxs) == 1:
        subs = by_idx[split_idxs[0]]
        K, F = len(subs), len(fillers)
        result = []
        fi = 0
        for k in range(K):
            n_fill = (k + 1) * F // K - k * F // K
            result.extend(fillers[fi:fi + n_fill])
            fi += n_fill
            result.append(subs[k])
        return result

    # ── 複数 split: 位相ずらし greedy（タイブレーク filler 優先）──────
    total_arc         = sum(a for _, _, a in raw_segs)
    total_split_count = sum(len(by_idx[i]) for i in split_idxs)

    split_queue = []  # (target_center_angle, sub_seg)
    for i_idx, sidx in enumerate(split_idxs):
        subs  = by_idx[sidx]
        K     = len(subs)
        phase = i_idx * total_arc / total_split_count
        for j, sub in enumerate(subs):
            target = (phase + j * total_arc / K) % total_arc
            split_queue.append((target, sub))
    split_queue.sort(key=lambda x: x[0])

    result = []
    cum    = 0.0
    fi     = 0
    si     = 0

    while si < len(split_queue) or fi < len(fillers):
        if si >= len(split_queue):
            result.extend(fillers[fi:])
            break

        target, split_seg = split_queue[si]
        center_now        = cum + split_seg[2] / 2.0

        if fi >= len(fillers):
            result.append(split_seg)
            cum += split_seg[2]
            si  += 1
        elif center_now >= target:
            result.append(split_seg)
            cum += split_seg[2]
            si  += 1
        else:
            center_after = cum + fillers[fi][2] + split_seg[2] / 2.0
            if abs(center_now - target) < abs(center_after - target):
                result.append(split_seg)
                cum += split_seg[2]
                si  += 1
            else:
                result.append(fillers[fi])
                cum += fillers[fi][2]
                fi  += 1

    return result


# ════════════════════════════════════════════════════════════════════
#  RouletteApp
# ════════════════════════════════════════════════════════════════════
class RouletteApp(
    WindowManagerMixin,
    CfgPanelMixin,
    ItemListMixin,
    WheelRendererMixin,
    SpinEngineMixin,
    HistoryManagerMixin,
):

    def __init__(self, root: tk.Tk):
        self.root = root

        root.title("RRoulette")
        root.overrideredirect(True)
        root.configure(bg=BG)

        # ─── ホイール描画パラメータ（Configure イベントで動的更新）─────
        self.CX = 250
        self.CY = 255
        self.R  = 215
        self._resize_redraw_id = None

        # ─── 履歴 ────────────────────────────────────────
        self._history: list[dict] = []
        self._log_item_rects: list = []   # ホバー判定用バウンディングボックス
        self._log_hover_idx   = -1        # 現在ホバー中のログインデックス
        self._auto_load_log()             # 前回のログを復元

        # ─── スピン状態 ───────────────────────────────────
        self.angle      = 0.0
        self.velocity   = 0.0
        self.decel      = 1.0
        self.spinning   = False
        self._flashing  = False
        self.prev_seg   = -1
        self.snd      = SoundManager()

        # クリック/スペースによる操作状態
        self._decelerating   = False
        self._final_angle    = 0.0
        self._action_count   = 0
        self._action_timer   = None
        self._click_start_x  = 0
        self._click_start_y  = 0

        # ドラッグ・リサイズ用
        self._drag_x = 0
        self._drag_y = 0
        self._resize_start_x = 0
        self._resize_start_y = 0
        self._resize_start_w = 0
        self._resize_start_h = 0
        self._resize_frame_pending = False
        self._resize_pending_w = 0
        self._resize_pending_h = 0

        # 浮動ウィンドウ参照（_build_sidebar / _build_cfg_panel で設定される）
        self._sidebar_toplevel    = None
        self._cfg_panel_toplevel  = None

        # 設定パネル表示状態・プロファイル・最前面・スピン設定
        cfg = self._load_config()
        self._settings_visible = cfg.get("settings_visible", True)
        self._profile_idx = cfg.get("profile_idx", 1)
        self._topmost = cfg.get("topmost", False)
        self._spin_duration   = cfg.get("spin_duration",   9)
        self._double_duration = cfg.get("double_duration", 3)
        self._triple_duration = cfg.get("triple_duration", 0)
        self._tick_volume = cfg.get("tick_volume", cfg.get("volume", 100))
        self._win_volume  = cfg.get("win_volume",  cfg.get("volume", 100))
        self._win_pattern = cfg.get("win_pattern", 0)
        self._tick_pattern = cfg.get("tick_pattern", 0)
        self._tick_custom_file = cfg.get("tick_custom_file", "")
        self._win_custom_file  = cfg.get("win_custom_file", "")
        self._text_direction = cfg.get("text_direction", 0)
        self._text_size_mode = cfg.get("text_size_mode", _SETTINGS_DEFAULTS["text_size_mode"])
        self._sidebar_w   = cfg.get("sidebar_w", 216)
        self._cfg_panel_w = cfg.get("cfg_panel_w", CFG_PANEL_W)
        self._cfg_panel_visible   = cfg.get("cfg_panel_visible", False)
        self._item_list_float     = cfg.get("item_list_float", False)
        self._cfg_panel_float     = cfg.get("cfg_panel_float", False)
        self._item_list_float_geo = cfg.get("item_list_float_geo", None)
        self._cfg_panel_float_geo = cfg.get("cfg_panel_float_geo", None)
        self._sash_start_x = 0
        self._sash_start_w = 0

        # ポインター位置設定 (0=上, 1=右, 2=下, 3=左, 4=任意)
        self._pointer_preset = cfg.get("pointer_preset", _SETTINGS_DEFAULTS["pointer_preset"])
        if self._pointer_preset < 4:
            self._pointer_angle = _POINTER_PRESET_ANGLES[self._pointer_preset]
        else:
            self._pointer_angle = cfg.get("pointer_angle", _SETTINGS_DEFAULTS["pointer_angle"])
        self._dragging_pointer            = False
        self._suppress_window_drag        = False
        self._pointer_lock_while_spinning = True
        self._pointer_preset_var = None   # UI構築後に設定

        # 項目パターン管理（ItemEntry 形式・後方互換読み込み）
        _default_texts = ["項目A", "項目B", "項目C", "項目D", "項目E", "項目F"]
        raw_patterns = cfg.get("item_patterns", None)
        if raw_patterns is None:
            self._item_patterns: dict[str, list] = {
                "デフォルト": [_make_entry(t) for t in _default_texts]
            }
        else:
            self._item_patterns = {}
            for pat_name, pat_items in raw_patterns.items():
                self._item_patterns[pat_name] = _ensure_entries(pat_items)
        self._current_pattern: str = cfg.get("current_pattern", "デフォルト")
        if self._current_pattern not in self._item_patterns:
            self._current_pattern = next(iter(self._item_patterns))
        self._item_entries: list[dict] = list(self._item_patterns[self._current_pattern])
        self._auto_shuffle: bool = cfg.get("auto_shuffle", False)
        self._arrangement_direction: int = cfg.get("arrangement_direction", 0)
        self._spin_direction: int = cfg.get("spin_direction", 0)
        self._confirm_reset: bool = cfg.get("confirm_reset", True)
        self._detail_collapsed: bool = True  # 起動時は詳細設定カードを折りたたむ
        # self.items と self.current_segments は _rebuild_segments() で設定
        self.current_segments: list = []
        self.items: list[str] = []
        self._log_timestamp    = cfg.get("log_timestamp", False)
        self._log_overlay_show = cfg.get("log_overlay_show", True)
        self._log_box_border   = cfg.get("log_box_border", False)
        self._log_on_top       = cfg.get("log_on_top", False)
        self._transparent      = cfg.get("transparent", False)
        self._donut_hole       = cfg.get("donut_hole", True)
        self._layout_cache     = []
        self._layout_cache_key = None
        self._grip_visible     = cfg.get("grip_visible", True)
        root.attributes("-topmost", self._topmost)

        self._build_ui()
        self._build_resize_grip()
        self._build_context_menu()
        if self._transparent:
            self._apply_transparency()
        self.snd.set_tick_volume(self._tick_volume / 100)
        self.snd.set_win_volume(self._win_volume / 100)
        self.snd.set_win_pattern(self._win_pattern)
        self.snd.set_tick_pattern(self._tick_pattern)
        if self._tick_custom_file:
            self.snd.load_tick_custom(self._tick_custom_file)
        if self._win_custom_file:
            self.snd.load_win_custom(self._win_custom_file)

        # 初期ジオメトリ（サイズ妥当性・オフスクリーンチェック付き）
        saved_geo = cfg.get("geometry")
        if saved_geo:
            try:
                parsed = _parse_geometry(saved_geo)
                if parsed:
                    w, h, x, y = parsed
                    if w < MIN_W or h < MIN_H:
                        # サイズが最小値未満の壊れた geometry は無視
                        self._apply_profile(self._profile_idx)
                    elif _is_on_any_monitor(x, y, w, h):
                        root.geometry(saved_geo)
                    else:
                        self._apply_profile(self._profile_idx)
                else:
                    self._apply_profile(self._profile_idx)
            except Exception:
                self._apply_profile(self._profile_idx)
        else:
            self._apply_profile(self._profile_idx)

        self._rebuild_segments()
        self._redraw()
        self.root.after(10, self._set_appwindow)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ════════════════════════════════════════════════════════════════
    #  セグメント再構築・配置操作
    # ════════════════════════════════════════════════════════════════
    def _rebuild_segments(self):
        """_item_entries から current_segments を再計算する。self.items も更新する。"""
        from constants import Segment

        enabled = [(e, i) for i, e in enumerate(self._item_entries) if e.get("enabled", True)]
        if not enabled:
            self.current_segments = []
            self.items = []
            return

        enabled_entries = [e for e, _ in enabled]
        orig_indices    = [i for _, i in enabled]

        probs = _calc_probs(enabled_entries)

        entries_with_probs = [
            (enabled_entries[j], orig_indices[j], probs[j])
            for j in range(len(enabled_entries))
        ]

        raw_segs = _apply_split(entries_with_probs)
        ordered  = _standard_order(raw_segs)

        if getattr(self, '_arrangement_direction', 0) == 0:
            ordered = list(reversed(ordered))

        segments = []
        angle = 0.0
        for text, idx, arc in ordered:
            seg = Segment(item_text=text, item_index=idx, arc=arc, start_angle=angle)
            segments.append(seg)
            angle += arc

        self.current_segments = segments
        self.items = [seg.item_text for seg in segments]
        self._layout_cache_key = None  # レイアウトキャッシュを無効化

    def _apply_random_arrangement(self):
        """current_segments をランダムに並び替えて start_angle を更新する。"""
        import random
        if not self.current_segments:
            return
        segs = list(self.current_segments)
        random.shuffle(segs)
        angle = 0.0
        for seg in segs:
            seg.start_angle = angle
            angle += seg.arc
        self.current_segments = segs
        self.items = [seg.item_text for seg in segs]
        self._layout_cache_key = None
        self._redraw()

    def _reset_to_standard_arrangement(self):
        """current_segments を標準配置順にリセットする。"""
        self._rebuild_segments()
        self._redraw()

    # ════════════════════════════════════════════════════════════════
    #  UI 構築
    # ════════════════════════════════════════════════════════════════
    def _build_sidebar(self):
        """項目リストサイドバーを埋め込みまたは浮動ウィンドウとして構築する。"""
        if self._item_list_float:
            self._sidebar_toplevel = self._open_float_win(
                "項目リスト", self._item_list_float_geo
            )
            self._sidebar_toplevel.protocol(
                "WM_DELETE_WINDOW", self._toggle_item_list_float
            )
            parent = self._sidebar_toplevel
            self.sidebar = tk.Frame(parent, bg=PANEL)
            self.sidebar.pack(fill=tk.BOTH, expand=True)
            self._sash = None
            if not self._settings_visible:
                self._sidebar_toplevel.withdraw()
        else:
            self._sidebar_toplevel = None
            self.sidebar = tk.Frame(self.content, bg=PANEL, width=self._sidebar_w)
            self.sidebar.pack_propagate(False)
            self._sash = tk.Frame(self.content, bg=DARK2, width=4)
            self._sash.pack_propagate(False)

        _title_row = tk.Frame(self.sidebar, bg=PANEL)
        _title_row.pack(fill=tk.X, padx=8, pady=(10, 4))
        tk.Label(_title_row, text="項目リスト", bg=PANEL, fg=WHITE,
                 font=("Meiryo", 11, "bold")).pack(side=tk.LEFT, padx=(4, 0))
        _BTN = dict(
            bg=DARK2, fg=WHITE, font=("Meiryo", 10),
            relief=tk.FLAT, cursor="hand2", padx=5, pady=1, bd=0,
        )
        _btn_exp_items = tk.Button(_title_row, text="↑", command=self._export_item_patterns, **_BTN)
        _btn_exp_items.pack(side=tk.RIGHT, padx=(2, 0))
        _SimpleTooltip(_btn_exp_items, "項目リストをエクスポート", self.root)
        _btn_imp_items = tk.Button(_title_row, text="↓", command=self._import_item_patterns, **_BTN)
        _btn_imp_items.pack(side=tk.RIGHT, padx=(2, 0))
        _SimpleTooltip(_btn_imp_items, "項目リストをインポート", self.root)
        _btn_rst_items = tk.Button(_title_row, text="↺", command=self._reset_item_patterns, **_BTN)
        _btn_rst_items.pack(side=tk.RIGHT, padx=(2, 0))
        _SimpleTooltip(_btn_rst_items, "項目リストをリセット", self.root)
        self._item_list_title_btns = [_btn_exp_items, _btn_imp_items, _btn_rst_items]

        pat_frm = tk.Frame(self.sidebar, bg=PANEL)
        pat_frm.pack(fill=tk.X, padx=6, pady=(0, 4))
        self._pattern_var = tk.StringVar(value=self._current_pattern)
        self._pattern_cb = ttk.Combobox(
            pat_frm, textvariable=self._pattern_var,
            values=list(self._item_patterns.keys()) + [_ADD_SENTINEL],
            font=("Meiryo", 9), state="normal",
        )
        self._pattern_cb.pack(fill=tk.X)
        self._pattern_cb.bind("<<ComboboxSelected>>", self._on_pattern_select)
        self._pattern_cb.bind("<Return>",              self._on_cb_return)
        self._pattern_cb.bind("<Escape>",              self._on_cb_escape)

        btn_row = tk.Frame(self.sidebar, bg=PANEL)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=(2, 4))
        self._edit_btn = tk.Button(
            btn_row, text="編集", command=self._enter_edit_mode,
            bg=DARK2, fg=WHITE, font=("Meiryo", 9),
            relief=tk.FLAT, cursor="hand2",
        )
        self._edit_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        self._save_btn = tk.Button(
            btn_row, text="保存", command=self._save_edit,
            bg=ACCENT, fg=WHITE, font=("Meiryo", 9),
            relief=tk.FLAT, cursor="hand2", state=tk.DISABLED,
        )
        self._save_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self._edit_warn_lbl = tk.Label(
            self.sidebar, text="", bg=PANEL, fg="#ff6b6b",
            font=("Meiryo", 8), wraplength=self._sidebar_w - 20,
            justify=tk.LEFT, anchor="w",
        )
        # 警告がある時だけ pack する（_show_edit_warning / _hide_edit_warning で制御）

        self._edit_mode = False
        self._lb_frm = tk.Frame(self.sidebar, bg=PANEL)
        self._lb_frm.pack(fill=tk.BOTH, expand=True, padx=6)
        self._build_listbox()

        # ── サイドバー幅リサイズグリップ（右下角）──────────────────
        # 独立ウィンドウ時は埋め込み用グリップ不要（OS標準リサイズを使用）
        if not self._item_list_float:
            _sg = tk.Canvas(self.sidebar, width=16, height=16,
                            bg=PANEL, highlightthickness=0, cursor="sb_h_double_arrow")
            for _i in range(3):
                _x = 4 + _i * 4
                _sg.create_line(_x, 3, _x, 13, fill="#555577", width=1)
            _sg.bind("<ButtonPress-1>",   self._sash_start)
            _sg.bind("<B1-Motion>",       self._sash_move)
            _sg.bind("<ButtonRelease-1>", self._sash_end)
            _sg.place(relx=1.0, rely=1.0, anchor="se")

        self.sidebar.bind("<Button-3>", self._show_context_menu)

    def _build_ui(self):
        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(fill=tk.BOTH, expand=True)

        # ── 項目リスト・設定パネルを構築して RIGHT 側に配置 ──
        self._build_sidebar()
        self._build_cfg_panel()
        self._apply_right_panel_layout()

        # ── メインエリア ──────────────────────────────────
        self.main_frame = tk.Frame(self.content, bg=BG)
        self.main_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                             padx=MAIN_PANEL_PAD, pady=MAIN_PANEL_PAD)

        self.cv = tk.Canvas(self.main_frame, bg=BG, highlightthickness=0)
        self.cv.pack(fill=tk.BOTH, expand=True)

        self.cv.bind("<Configure>", self._on_canvas_resize)

        for w in (self.cv, self.main_frame, self.content):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        self.cv.bind("<ButtonRelease-1>", self._on_cv_release)
        self.cv.bind("<Motion>", self._on_cv_motion)
        self.root.bind("<KeyPress-space>", self._on_space_press)

        for w in (self.cv, self.main_frame, self.content, self.root):
            w.bind("<Button-3>", self._show_context_menu)

    # ════════════════════════════════════════════════════════════════
    #  設定保存・読み込み
    # ════════════════════════════════════════════════════════════════
    def _save_config(self):
        self._item_patterns[self._current_pattern] = list(self._item_entries)
        config = {
            "profile_idx": self._profile_idx,
            "settings_visible": self._settings_visible,
            "cfg_panel_visible": self._cfg_panel_visible,
            "topmost": self._topmost,
            "spin_duration":   self._spin_duration,
            "double_duration": self._double_duration,
            "triple_duration": self._triple_duration,
            "tick_volume": self._tick_volume,
            "win_volume":  self._win_volume,
            "tick_pattern": self._tick_pattern,
            "win_pattern": self._win_pattern,
            "tick_custom_file": self._tick_custom_file,
            "win_custom_file":  self._win_custom_file,
            "text_direction": self._text_direction,
            "text_size_mode": self._text_size_mode,
            "sidebar_w":   self._sidebar_w,
            "cfg_panel_w": self._cfg_panel_w,
            "geometry": self.root.geometry(),
            "item_patterns": self._item_patterns,
            "current_pattern": self._current_pattern,
            "auto_shuffle": self._auto_shuffle,
            "arrangement_direction": self._arrangement_direction,
            "spin_direction": self._spin_direction,
            "confirm_reset": self._confirm_reset,
            "pointer_preset": self._pointer_preset,
            "pointer_angle":  self._pointer_angle,
            "log_timestamp":     self._log_timestamp,
            "log_overlay_show":  self._log_overlay_show,
            "log_box_border":    self._log_box_border,
            "log_on_top":        self._log_on_top,
            "transparent":       self._transparent,
            "donut_hole":        self._donut_hole,
            "grip_visible":      self._grip_visible,
            "item_list_float":   self._item_list_float,
            "cfg_panel_float":   self._cfg_panel_float,
            "item_list_float_geo": (
                self._sidebar_toplevel.geometry()
                if self._sidebar_toplevel and self._sidebar_toplevel.winfo_exists()
                else self._item_list_float_geo
            ),
            "cfg_panel_float_geo": (
                self._cfg_panel_toplevel.geometry()
                if self._cfg_panel_toplevel and self._cfg_panel_toplevel.winfo_exists()
                else self._cfg_panel_float_geo
            ),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f)
        except Exception:
            pass

    def _load_config(self) -> dict:
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ════════════════════════════════════════════════════════════════
    #  終了
    # ════════════════════════════════════════════════════════════════
    def _on_close(self):
        self._auto_save_log()
        self._save_config()
        self.root.destroy()


# ════════════════════════════════════════════════════════════════════
#  エントリーポイント
# ════════════════════════════════════════════════════════════════════
def main():
    root = tk.Tk()
    RouletteApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
