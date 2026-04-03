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

from constants import DONUT_HIT_RADIUS


class SpinEngineMixin:

    _ACTION_WINDOW_MS = 400  # 連打をまとめる時間窓（ms）

    # ════════════════════════════════════════════════════════════════
    #  スピン制御
    # ════════════════════════════════════════════════════════════════
    def _start_spin(self):
        if self.spinning or len(getattr(self, 'current_segments', [])) < 2:
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
            self._record_result(winner)
            self.snd.play_win()
            seg_color = self._design.segment.color_for(self.current_segments[seg].item_index)
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

    def _draw_result_overlay(self, winner: str, times: int, seg_color: str):
        """結果フラッシュ枠とテキストを canvas item として描画する。
        描画順（呼び出し順）で Z-order を制御するため use_window は使わない。
        """
        pw, ph = 280, 90
        text_color = self._design.wheel.text_color if times % 2 else self._design.gold
        x0 = self.CX - pw // 2
        y0 = self.CY - ph // 2
        x1 = self.CX + pw // 2
        y1 = self.CY + ph // 2
        self.cv.create_rectangle(
            x0, y0, x1, y1,
            fill=seg_color, outline="#ff0000", width=3,
            tags="result_overlay",
        )
        # 疑似アウトライン（4方向オフセットで黒縁）
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            self.cv.create_text(
                self.CX + dx, self.CY + dy,
                text=winner, fill="#000000",
                font=("Meiryo", 16, "bold"), tags="result_overlay",
                width=pw - 20,
            )
        # 本体テキスト
        self.cv.create_text(
            self.CX, self.CY,
            text=winner, fill=text_color,
            font=("Meiryo", 16, "bold"), tags="result_overlay",
            width=pw - 20,
        )

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
        # ドーナツ判定: セグメント描画領域（外周R以内 かつ 中心ハブDONUT_HIT_RADIUS超）のみ受け付ける
        dist = math.hypot(event.x - self.CX, event.y - self.CY)
        if dist > self.R or dist <= DONUT_HIT_RADIUS:
            return
        self._handle_action()

    def _on_space_press(self, event):
        """スペースキー押下: スピン開始 / 連打で停止操作"""
        self._handle_action()

    def _handle_action(self):
        """操作の共通ハンドラ。
        - 非スピン中: スピン開始
        - スピン中 ダブル操作: 停止フェーズ開始
        - スピン中 トリプル操作: 即時停止
        """
        if not self.spinning:
            self._start_spin()
            return

        self._action_count += 1
        if self._action_timer:
            self.root.after_cancel(self._action_timer)
        self._action_timer = self.root.after(
            self._ACTION_WINDOW_MS, self._reset_action_count
        )

        if self._action_count == 2:
            self._compress_to(self._double_duration)
        elif self._action_count >= 3:
            self._action_count = 0
            if self._action_timer:
                self.root.after_cancel(self._action_timer)
                self._action_timer = None
            self._compress_to(self._triple_duration)

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
