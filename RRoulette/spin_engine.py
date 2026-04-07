"""
RRoulette — スピンエンジン Mixin
  - _start_spin: スピン開始（結果先行決定・velocity 逆算）
  - _frame: アニメーション更新ループ
  - _finish / _flash: 停止処理・結果オーバーレイ
  - _calc_final_angle / _compress_to: 停止角度計算・強制減速
  - _handle_action / _on_cv_release / _on_space_press: 操作ハンドラ
"""

import math
import random
import tkinter.font as _tkfont

from constants import DONUT_HIT_RADIUS


# ────────────────────────────────────────────────────────────────────
#  結果オーバーレイ描画ユーティリティ
# ────────────────────────────────────────────────────────────────────

def _draw_rounded_rect(cv, x0: int, y0: int, x1: int, y1: int,
                       r: int = 10, tags: str = "", **kwargs):
    """角丸矩形を create_polygon (smooth=True) で描画する。
    r=0 の場合は通常の create_rectangle にフォールバックする。"""
    if r <= 0:
        cv.create_rectangle(x0, y0, x1, y1, tags=tags, **kwargs)
        return
    # smooth=True B-spline の重複制御点による角丸近似
    pts = [
        x0 + r, y0,   x0 + r, y0,
        x1 - r, y0,   x1 - r, y0,
        x1,     y0,   x1,     y0 + r,
        x1,     y0 + r,
        x1,     y1 - r,   x1,     y1 - r,
        x1,     y1,   x1 - r, y1,   x1 - r, y1,
        x0 + r, y1,   x0 + r, y1,
        x0,     y1,   x0,     y1 - r,   x0, y1 - r,
        x0,     y0 + r,   x0, y0 + r,
        x0,     y0,   x0 + r, y0,
    ]
    cv.create_polygon(pts, smooth=True, tags=tags, **kwargs)


def _fit_text_ellipsis(root, text: str, max_w: int,
                       font_family: str, fsize: int) -> str:
    """省略モード: 目標フォントサイズでテキスト幅が max_w を超える場合、
    末尾を '…' で省略する。フォントサイズは変更しない。"""
    if not text:
        return text
    f = _tkfont.Font(root=root, family=font_family, size=fsize, weight="bold")
    if f.measure(text) <= max_w:
        return text
    t = text
    while t and f.measure(t + "…") > max_w:
        t = t[:-1]
    return (t + "…") if t else "…"


_RESULT_MIN_FONT_SIZE = 10  # 収めるモード最小フォントサイズ


def _fit_text_shrink(root, text: str, max_w: int,
                     target_size: int, font_family: str) -> tuple:
    """収めるモード: フォントサイズを target_size から縮小して max_w に収める。
    Returns (actual_size: int, display_text: str)"""
    if not text:
        return target_size, text
    for size in range(target_size, _RESULT_MIN_FONT_SIZE - 1, -1):
        f = _tkfont.Font(root=root, family=font_family, size=size, weight="bold")
        if f.measure(text) <= max_w:
            return size, text
    # 最小サイズでも収まらない場合のみ省略
    f = _tkfont.Font(root=root, family=font_family, size=_RESULT_MIN_FONT_SIZE, weight="bold")
    t = text
    while t and f.measure(t + "…") > max_w:
        t = t[:-1]
    return _RESULT_MIN_FONT_SIZE, (t + "…") if t != text else text


class SpinEngineMixin:

    _ACTION_WINDOW_MS = 400  # 連打をまとめる時間窓（ms）

    # ════════════════════════════════════════════════════════════════
    #  スピン制御
    # ════════════════════════════════════════════════════════════════
    def _start_spin(self, _replay_source: str = "unknown"):
        if self.spinning or getattr(self, '_replaying', False):
            return
        if len(getattr(self, 'current_segments', [])) < 2:
            return
        # auto_shuffle が有効なら spinning=True にする前に配置をランダム化する
        # （spinning=True 後に呼ぶと _redraw() 内でキャッシュ再構築がスキップされ
        #   文字が表示されなくなるため、必ず spinning=False の状態で実行する）
        if getattr(self, '_auto_shuffle', False):
            self._apply_random_arrangement()

        self.spinning      = True
        self._flashing     = False  # フラッシュを強制終了
        self.set_item_spin_lock(True)
        self.set_cfg_spin_lock(True)
        self._decelerating = False
        self._action_count = 0
        if self._action_timer:
            self.root.after_cancel(self._action_timer)
            self._action_timer = None
        self.cv.delete("result_overlay")
        self._result_showing = False
        self._result_overlay_rect = None
        if getattr(self, '_result_auto_timer', None):
            self.root.after_cancel(self._result_auto_timer)
            self._result_auto_timer = None
        self._result_close_fn = None

        target_frames = max(1, self._spin_duration * 1000 / 16)

        # ── 結果を先に確率比例でランダム決定し、そこへ着地する velocity を逆算 ──
        segs = self.current_segments
        r_val = random.uniform(0, 360)
        cumulative = 0.0
        target_seg = len(segs) - 1
        for i, seg in enumerate(segs):
            cumulative += seg.arc
            if r_val < cumulative:
                target_seg = i
                break
        seg_start  = cumulative - segs[target_seg].arc
        seg_arc    = segs[target_seg].arc
        target_offset = seg_start + seg_arc * random.uniform(0.15, 0.85)
        target_angle  = (self._pointer_angle + target_offset) % 360
        self._final_angle = target_angle

        # target_angle に着地するための総回転量を決める
        v_ref = 25.0
        d_ref = (0.06 / v_ref) ** (1.0 / target_frames)
        ref_total = (v_ref - 0.06) / (1.0 - d_ref)
        base_rots  = max(3, int(ref_total / 360))
        _spin_sign  = -1 if getattr(self, '_spin_direction', 0) == 1 else 1
        if _spin_sign == 1:
            needed_residual = (target_angle - self.angle) % 360
        else:
            needed_residual = (self.angle - target_angle) % 360
        adjusted_total  = base_rots * 360 + needed_residual

        # adjusted_total を実現する velocity を二分探索
        def total_for_v(v):
            d = (0.06 / v) ** (1.0 / target_frames)
            return (v - 0.06) / (1.0 - d)

        lo, hi = 1.0, 300.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if total_for_v(mid) < adjusted_total:
                lo = mid
            else:
                hi = mid
        self.velocity = (lo + hi) / 2
        self.decel    = (0.06 / self.velocity) ** (1.0 / target_frames)

        self.prev_seg = self._seg_at_pointer()
        if hasattr(self, '_replay_record_start'):
            self._replay_record_start(_replay_source)
        self._frame()

    def _frame(self):
        if not self.spinning:
            return
        _spin_sign = -1 if getattr(self, '_spin_direction', 0) == 1 else 1
        self.angle     = (self.angle + _spin_sign * self.velocity) % 360
        self.velocity *= self.decel

        seg = self._seg_at_pointer()
        if seg != self.prev_seg:
            self.prev_seg = seg
            if self.velocity > 0.6:
                self.snd.play_tick()
                if hasattr(self, '_replay_record_sound'):
                    self._replay_record_sound("tick")

        if hasattr(self, '_replay_record_frame'):
            self._replay_record_frame(self.angle)
        self._redraw()

        if self.velocity < 0.06:
            self._finish()
        else:
            self.root.after(16, self._frame)

    def _finish(self):
        self.spinning      = False
        self._decelerating = False
        self._action_count = 0
        if self._action_timer:
            self.root.after_cancel(self._action_timer)
            self._action_timer = None
        seg = self._seg_at_pointer()
        if seg >= 0:
            winner = self.current_segments[seg].item_text
            winner_idx = self.current_segments[seg].item_index
            seg_color = self._design.segment.color_for(winner_idx)
            if hasattr(self, '_replay_record_sound'):
                self._replay_record_sound("win")   # finish前に記録（finish後は_replay_rec=None）
            if hasattr(self, '_replay_record_finish'):
                self._replay_record_finish(winner, winner_idx, self.angle, seg_color)
            self._record_result(winner)
            self.snd.play_win()
            self._flash(4, winner, seg_color)
        else:
            self.set_item_spin_lock(False)
            self.set_cfg_spin_lock(False)

    def _flash(self, times: int, winner: str, seg_color: str):
        # _flashing を一時解除して _redraw() を呼ぶことで
        # ホイール・ログの正しい描画順（log_on_top 設定準拠）を維持する。
        # その後 _flashing を再セットしてリザルトを最前面に追加する。
        self._flashing = False
        self._redraw()          # log_on_top に従い [ログ→ホイール] or [ホイール→ログ] を描画
        self._flashing = True   # 以降の _redraw() 割り込みをブロック

        self._draw_result_overlay(winner, times, seg_color)  # 常に最前面

        if times > 0:
            self.root.after(220, lambda: self._flash(times - 1, winner, seg_color))
        else:
            self._flashing = False  # フラッシュ完了
            self.set_item_spin_lock(False)
            self.set_cfg_spin_lock(False)
            # 結果表示の閉じ方を設定に従って制御
            mode = getattr(self, '_result_close_mode', 2)
            hold = getattr(self, '_result_hold_sec', 5.0)
            self._result_showing = True
            self._result_close_fn = lambda: self.cv.delete("result_overlay")
            if mode in (1, 2):  # 自動 or 両方
                ms = max(500, int(hold * 1000))
                self._result_auto_timer = self.root.after(ms, self._close_result_overlay)

    def _draw_result_overlay(self, winner: str, times: int, seg_color: str):
        """結果フラッシュ枠とテキストを canvas item として描画する。
        描画順（呼び出し順）で Z-order を制御するため use_window は使わない。

        - ホイール半径 R に連動してボックスサイズ・目標フォントサイズを計算する。
        - times > 0（フラッシュ中）: セグメント色で演出（既存挙動維持）。
        - times == 0（フラッシュ完了・定常表示）: デザイン設定の色を使用。
        - 文字フィット: design.result.text_fit_mode に従い省略 / 収めるを適用。
        """
        R = getattr(self, 'R', 140)
        rd = self._design.result

        # ── ボックスサイズ（ホイールサイズ連動）────────────────────────
        pw = max(160, int(R * 1.1))
        ph = max(55,  int(R * 0.35))

        # ── 目標フォントサイズ（ホイールサイズ連動・デザインエディタは使わない）─
        target_fsize = max(14, int(R * 0.13))

        # ── 座標 ────────────────────────────────────────────────────────
        x0 = self.CX - pw // 2
        y0 = self.CY - ph // 2
        x1 = self.CX + pw // 2
        y1 = self.CY + ph // 2
        # ヒットテスト用に矩形を保持（フラッシュ中もクリックブロックに使う）
        self._result_overlay_rect = (x0, y0, x1, y1)

        # ── 色・スタイル: フラッシュ中と定常表示で切り替え ──────────────
        is_flash = times > 0
        if is_flash:
            bg_col      = seg_color
            outline_col = "#ff0000"
            outline_w   = 3
            corner_r    = 0
            text_col    = self._design.wheel.text_color if times % 2 else self._design.gold
        else:
            # 定常表示: 配色モードに従って背景色を決定
            steady_mode = getattr(rd, 'steady_color_mode', 0)
            bg_col      = seg_color if steady_mode == 1 else rd.bg_color
            outline_col = rd.outline_color
            outline_w   = rd.outline_width
            corner_r    = min(rd.corner_radius, min(pw, ph) // 4)
            text_col    = rd.text_color

        # ── 背景ボックス描画 ────────────────────────────────────────────
        _draw_rounded_rect(
            self.cv, x0, y0, x1, y1,
            r=corner_r,
            fill=bg_col, outline=outline_col, width=outline_w,
            tags="result_overlay",
        )

        # ── フォントファミリー ───────────────────────────────────────────
        font_family = getattr(self._design.fonts, 'result_family', 'Meiryo')

        # ── テキスト幅上限 ──────────────────────────────────────────────
        padding = rd.padding if not is_flash else 12
        text_max_w = max(20, pw - 2 * padding)

        # ── 文字フィット ────────────────────────────────────────────────
        fit_mode = getattr(rd, 'text_fit_mode', 0)
        if fit_mode == 1:
            # 収めるモード: 入りきるまでフォントサイズを縮小
            fsize, display_text = _fit_text_shrink(
                self.root, winner, text_max_w, target_fsize, font_family
            )
        else:
            # 省略モード（デフォルト）: 目標サイズで収まらなければ末尾を省略
            fsize = target_fsize
            display_text = _fit_text_ellipsis(
                self.root, winner, text_max_w, font_family, fsize
            )

        # ── テキスト描画（1行固定・中央揃え）─────────────────────────────
        # 疑似アウトライン（4方向オフセットで黒縁）
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            self.cv.create_text(
                self.CX + dx, self.CY + dy,
                text=display_text, fill="#000000",
                font=(font_family, fsize, "bold"),
                tags="result_overlay",
            )
        # 本体テキスト
        self.cv.create_text(
            self.CX, self.CY,
            text=display_text, fill=text_col,
            font=(font_family, fsize, "bold"),
            tags="result_overlay",
        )

    def _close_result_overlay(self):
        """結果オーバーレイを閉じる（タイマーキャンセル + canvas 削除 / クロージャ実行）。"""
        self._result_showing = False
        self._result_overlay_rect = None
        if getattr(self, '_result_auto_timer', None):
            self.root.after_cancel(self._result_auto_timer)
            self._result_auto_timer = None
        fn = getattr(self, '_result_close_fn', None)
        self._result_close_fn = None
        if fn:
            fn()
        else:
            self.cv.delete("result_overlay")

    # ════════════════════════════════════════════════════════════════
    #  クリック / スペースキー操作
    # ════════════════════════════════════════════════════════════════
    def _calc_final_angle(self) -> float:
        """現在の velocity / decel から自然停止する最終角度をシミュレートして返す"""
        a, v, d = self.angle, self.velocity, self.decel
        sign = -1 if getattr(self, '_spin_direction', 0) == 1 else 1
        while v >= 0.06:
            a = (a + sign * v) % 360
            v *= d
        return a

    def _on_cv_release(self, event):
        """キャンバス上で ButtonRelease-1 が発生したとき、ドラッグでなければ操作を処理する"""
        if self._dragging_pointer:
            self._dragging_pointer = False
            return
        dx = abs(event.x_root - self._click_start_x)
        dy = abs(event.y_root - self._click_start_y)
        if dx > 5 or dy > 5:
            return
        # 結果オーバーレイ領域内クリック判定
        # フラッシュ中（_flashing=True）も含めて領域内クリックはスピンへ流さない
        _rect = getattr(self, '_result_overlay_rect', None)
        if _rect and (getattr(self, '_flashing', False) or getattr(self, '_result_showing', False)):
            rx0, ry0, rx1, ry1 = _rect
            if rx0 <= event.x <= rx1 and ry0 <= event.y <= ry1:
                # 領域内: 表示済み（フラッシュ完了後）なら閉じる、フラッシュ中はブロックのみ
                if getattr(self, '_result_showing', False):
                    mode = getattr(self, '_result_close_mode', 2)
                    if mode in (0, 2):  # クリック or 両方
                        self._close_result_overlay()
                return  # スピン開始には渡さない
        if getattr(self, '_replaying', False):
            return
        # ドーナツ判定: セグメント描画領域（外周R以内 かつ 中心ハブDONUT_HIT_RADIUS超）のみ受け付ける
        dist = math.hypot(event.x - self.CX, event.y - self.CY)
        if dist > self.R or dist <= DONUT_HIT_RADIUS:
            return
        self._handle_action("mouse")

    def _is_global_key_blocked(self) -> bool:
        """グローバルショートカットを無効にすべき状況なら True を返す。
        Entry / Text / Spinbox / Combobox などの入力系ウィジェットにフォーカスが
        ある場合は、文字入力を妨げないようにグローバル操作を抑制する。"""
        try:
            w = self.root.focus_get()
            if w is None:
                return False
            return w.winfo_class() in ("Entry", "Text", "Spinbox", "TCombobox")
        except Exception:
            return False

    def _on_space_press(self, event):
        """スペースキー押下: スピン開始 / 連打で停止操作
        入力系ウィジェットにフォーカスがある場合は何もしない（文字入力を優先）。"""
        if self._is_global_key_blocked():
            return
        self._handle_action("space")

    def _handle_action(self, source: str = "unknown"):
        """操作の共通ハンドラ。
        - 非スピン中: スピン開始
        - スピン中 ダブル操作: 停止フェーズ開始
        - スピン中 トリプル操作: 即時停止
        source: "mouse" / "space" / "unknown"
        """
        if getattr(self, '_replaying', False):
            return
        if not self.spinning:
            self._start_spin(source)
            return

        self._action_count += 1
        if self._action_timer:
            self.root.after_cancel(self._action_timer)
        self._action_timer = self.root.after(
            self._ACTION_WINDOW_MS, self._reset_action_count
        )

        if self._action_count == 2:
            self._compress_to(self._double_duration)
            if hasattr(self, '_replay_record_event'):
                self._replay_record_event("double_stop", source)
        elif self._action_count >= 3:
            self._action_count = 0
            if self._action_timer:
                self.root.after_cancel(self._action_timer)
                self._action_timer = None
            self._compress_to(self._triple_duration)
            if hasattr(self, '_replay_record_event'):
                self._replay_record_event("triple_stop", source)

    def _reset_action_count(self):
        """連打タイマー満了 → カウントをリセット"""
        self._action_count = 0
        self._action_timer = None

    def _compress_to(self, target_seconds: int):
        """残りアニメーションを target_seconds 秒に圧縮する。
        0 = 即時停止。残り時間が既に target 以下の場合は介入しない。
        """
        if not self.spinning:
            return

        if self.decel < 1.0 and self.velocity > 0.06:
            remaining_frames = math.log(0.06 / self.velocity) / math.log(self.decel)
        else:
            remaining_frames = 0

        target_frames = target_seconds * 1000 / 16

        if remaining_frames <= target_frames:
            return

        if target_seconds == 0:
            self.angle = self._final_angle
            self._redraw()
            self._finish()
            return

        self._decelerating = True

        total_remaining = 0.0
        vv, dd = self.velocity, self.decel
        while vv >= 0.06:
            total_remaining += vv
            vv *= dd

        if total_remaining < 0.5:
            self.angle = self._final_angle
            self._redraw()
            self._finish()
            return

        fast_frames = max(1, int(target_frames))
        new_d = (0.06 / max(self.velocity, 0.07)) ** (1.0 / fast_frames)
        self.velocity = total_remaining * (1.0 - new_d)
        self.decel = new_d
