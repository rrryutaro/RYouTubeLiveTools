"""
RRoulette — スピンエンジン: 4段階モデル (push / cruise / decel / landing)

RRoulettePWA の spinEngine.ts を Python に移植。
各段階で「終了秒・終了速度・カーブ種別」を独立指定し、
解析積分で任意時刻の累積回転数を計算する。

速度プロファイル:
  v0=0 → v1 (push終端) → v2 (cruise終端) → v3 (decel終端) → 0

プリセットプロファイル (3種):
  'z' = バランス型 (既定)
  'y' = 緩急強調
  'x' = AIお勧め
"""

from __future__ import annotations

import math
import random
import dataclasses
from dataclasses import dataclass
from typing import Optional

# ── カーブ種別 ─────────────────────────────────────────────────────────────
# SpinCurve: 'linear' | 'easeOut' | 'easeIn' | 'easeInOut'
# SpinPresetProfile: 'x' | 'y' | 'z'

CURVE_POWER = 2  # ease 系の指数

# ── 公開定数 ───────────────────────────────────────────────────────────────
PEAK_SPEED_MIN_RPS: float = 0.0
PEAK_SPEED_MAX_RPS: float = 25.0
PEAK_SPEED_DEFAULT_RPS: float = 4.0
MIN_PHASE_LEN_MS: float = 30.0
SPIN_DURATION_RANDOM_MAX_RATIO: float = 0.5
SPIN_PHASE_RANDOMIZE_MAX: float = 1.0

PRESET_DURATIONS_MS: list[int] = [1000, 3000, 5000, 7000, 9000, 12000]
PRESET_PROFILES_LIST: list[str] = ['x', 'y', 'z']

# 後方互換: 旧 spin_preset_name 系は廃止。空リストで参照エラーを回避する。
SPIN_PRESET_NAMES: list[str] = []
DEFAULT_PRESET_NAME: str = ''


# ── PhaseTimes ────────────────────────────────────────────────────────────
@dataclass
class PhaseTimes:
    """4段階モデルの絶対時間・速度・カーブを保持する内部構造。

    時間はすべて ms、速度は RPS (回転/秒)。
      push_end_ms   : ① 加速の終了時刻
      cruise_end_ms : ② 巡航の終了時刻
      decel_end_ms  : ③ 減速の終了時刻
      total_ms      : ④ 着地の終了時刻 (= スピン総時間)
      v1 : 加速終端速度 (= 巡航開始速度)
      v2 : 巡航終端速度 (= 減速開始速度)
      v3 : 減速終端速度 (= 着地開始速度)
    """
    push_end_ms:   float
    cruise_end_ms: float
    decel_end_ms:  float
    total_ms:      float
    v1: float
    v2: float
    v3: float
    push_curve:    str
    cruise_curve:  str
    decel_curve:   str
    landing_curve: str


# ── プリセットエントリ (内部型) ────────────────────────────────────────────
@dataclass
class _PresetEntry:
    duration_ms:  float
    push:         float  # ratio
    cruise:       float  # ratio
    decel:        float  # ratio
    landing:      float  # ratio
    peak_rps:     float
    v_low_rps:    float
    push_curve:   str
    cruise_curve: str
    decel_curve:  str
    landing_curve:str


# ── プロファイル定義 ────────────────────────────────────────────────────────
_L, _EO, _EI = 'linear', 'easeOut', 'easeIn'


def _e(dur, push, cruise, decel, landing, peak, vlow, pc, cc, dc, lc) -> _PresetEntry:
    return _PresetEntry(dur, push, cruise, decel, landing, peak, vlow, pc, cc, dc, lc)


# z = バランス型 ★ 既定
_PROFILE_Z: list[_PresetEntry] = [
    _e(1000,  0.05, 0.15, 0.25, 0.55, 15,  0.5, _EO, _L, _L,  _EO),
    _e(3000,  0.10, 0.12, 0.25, 0.53,  8,  0.5, _EO, _L, _L,  _EO),
    _e(5000,  0.15, 0.12, 0.23, 0.50,  6,  0.5, _EO, _L, _L,  _EO),
    _e(7000,  0.22, 0.11, 0.22, 0.45,  5,  0.5, _EI, _L, _L,  _EO),
    _e(9000,  0.22, 0.11, 0.22, 0.45,  4,  0.5, _EI, _L, _L,  _EO),
    _e(12000, 0.22, 0.08, 0.22, 0.48,  4,  0.5, _EI, _L, _L,  _EO),
]

# y = 緩急強調: 投擲感 + 長い余韻
_PROFILE_Y: list[_PresetEntry] = [
    _e(1000,  0.03, 0.10, 0.20, 0.67, 20,  0.3, _EO, _L, _L,  _EO),
    _e(3000,  0.05, 0.08, 0.20, 0.67, 16,  0.3, _EO, _L, _L,  _EO),
    _e(5000,  0.07, 0.07, 0.20, 0.66, 12,  0.3, _EO, _L, _L,  _EO),
    _e(7000,  0.10, 0.05, 0.20, 0.65, 10,  0.3, _EO, _L, _L,  _EO),
    _e(9000,  0.12, 0.05, 0.18, 0.65,  8,  0.3, _EO, _L, _L,  _EO),
    _e(12000, 0.12, 0.03, 0.18, 0.67,  7,  0.3, _EO, _L, _L,  _EO),
]

# x = AIお勧め: 滑らかなクレッシェンド + 映画的減速
_PROFILE_X: list[_PresetEntry] = [
    _e(1000,  0.08, 0.10, 0.25, 0.57, 12,  0.5, _EO, _L, _EO, _EO),
    _e(3000,  0.18, 0.08, 0.22, 0.52,  8,  0.5, _EI, _L, _EO, _EO),
    _e(5000,  0.22, 0.08, 0.22, 0.48,  6,  0.5, _EI, _L, _EO, _EO),
    _e(7000,  0.25, 0.07, 0.22, 0.46,  5,  0.5, _EI, _L, _EO, _EO),
    _e(9000,  0.28, 0.07, 0.22, 0.43,  4.5,0.5, _EI, _L, _EO, _EO),
    _e(12000, 0.28, 0.05, 0.22, 0.45,  4,  0.5, _EI, _L, _EO, _EO),
]

_PROFILES: dict[str, list[_PresetEntry]] = {
    'x': _PROFILE_X,
    'y': _PROFILE_Y,
    'z': _PROFILE_Z,
}


# ── ヘルパー ───────────────────────────────────────────────────────────────
def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pick_random(lst: list):
    return lst[int(random.random() * len(lst))]


def _get_preset_entry(profile: str, duration_ms: float) -> _PresetEntry:
    """プロファイル + 秒数 → 補間済み PresetEntry。"""
    lst = _PROFILES.get(profile) or _PROFILE_Z
    if duration_ms <= lst[0].duration_ms:
        return dataclasses.replace(lst[0])
    if duration_ms >= lst[-1].duration_ms:
        return dataclasses.replace(lst[-1])
    for a, b in zip(lst, lst[1:]):
        if a.duration_ms <= duration_ms <= b.duration_ms:
            t = (duration_ms - a.duration_ms) / (b.duration_ms - a.duration_ms)
            c = a if t < 0.5 else b
            return _PresetEntry(
                duration_ms=duration_ms,
                push=a.push    + (b.push    - a.push)    * t,
                cruise=a.cruise + (b.cruise - a.cruise)  * t,
                decel=a.decel  + (b.decel   - a.decel)   * t,
                landing=a.landing + (b.landing - a.landing) * t,
                peak_rps=a.peak_rps   + (b.peak_rps   - a.peak_rps)   * t,
                v_low_rps=a.v_low_rps + (b.v_low_rps  - a.v_low_rps) * t,
                push_curve=c.push_curve,
                cruise_curve=c.cruise_curve,
                decel_curve=c.decel_curve,
                landing_curve=c.landing_curve,
            )
    return dataclasses.replace(lst[-1])


# ── 公開 API: PhaseTimes 生成 ──────────────────────────────────────────────
def get_preset_phase_times(duration_ms: float, profile: str = 'z') -> PhaseTimes:
    """プリセット既定の PhaseTimes を返す (UI リセット参照用を兼ねる)。"""
    e = _get_preset_entry(profile, duration_ms)
    return PhaseTimes(
        push_end_ms=duration_ms * e.push,
        cruise_end_ms=duration_ms * (e.push + e.cruise),
        decel_end_ms=duration_ms * (e.push + e.cruise + e.decel),
        total_ms=duration_ms,
        v1=e.peak_rps,
        v2=e.peak_rps,  # 巡航は定速 (= v1) を既定とする
        v3=e.v_low_rps,
        push_curve=e.push_curve,
        cruise_curve=e.cruise_curve,
        decel_curve=e.decel_curve,
        landing_curve=e.landing_curve,
    )


def get_effective_phase_times(
    duration_ms: float,
    overrides: Optional[dict],
    profile: str = 'z',
) -> PhaseTimes:
    """プリセット既定値に overrides を適用し、安全クランプした PhaseTimes を返す。

    overrides キー (すべて省略可能):
      push_end_ms, cruise_end_ms, decel_end_ms  — 時間境界 (ms)
      push_end_rps, cruise_end_rps, decel_end_rps — 速度 (RPS)
      push_curve, cruise_curve, decel_curve, landing_curve — カーブ種別
    """
    preset = get_preset_phase_times(duration_ms, profile)
    ov = overrides or {}

    v1 = _clamp(ov.get('push_end_rps',   preset.v1), PEAK_SPEED_MIN_RPS, PEAK_SPEED_MAX_RPS)
    v2 = _clamp(ov.get('cruise_end_rps', v1),         PEAK_SPEED_MIN_RPS, PEAK_SPEED_MAX_RPS)
    v3 = _clamp(ov.get('decel_end_rps',  preset.v3),  PEAK_SPEED_MIN_RPS, PEAK_SPEED_MAX_RPS)

    push_end   = ov.get('push_end_ms',   preset.push_end_ms)
    cruise_end = ov.get('cruise_end_ms', preset.cruise_end_ms)
    decel_end  = ov.get('decel_end_ms',  preset.decel_end_ms)

    safe_push   = _clamp(push_end,   MIN_PHASE_LEN_MS, duration_ms - 3 * MIN_PHASE_LEN_MS)
    safe_cruise = _clamp(cruise_end, safe_push   + MIN_PHASE_LEN_MS, duration_ms - 2 * MIN_PHASE_LEN_MS)
    safe_decel  = _clamp(decel_end,  safe_cruise + MIN_PHASE_LEN_MS, duration_ms - MIN_PHASE_LEN_MS)

    return PhaseTimes(
        push_end_ms=safe_push,
        cruise_end_ms=safe_cruise,
        decel_end_ms=safe_decel,
        total_ms=duration_ms,
        v1=v1, v2=v2, v3=v3,
        push_curve=ov.get('push_curve',    preset.push_curve),
        cruise_curve=ov.get('cruise_curve', preset.cruise_curve),
        decel_curve=ov.get('decel_curve',   preset.decel_curve),
        landing_curve=ov.get('landing_curve', preset.landing_curve),
    )


# ── 公開 API: ランダム化 ───────────────────────────────────────────────────
def apply_random_duration_to_times(times: PhaseTimes, ratio: float) -> PhaseTimes:
    """終了時間ランダム化: ±(ratio × totalMs) の delta を巡航 → 着地で吸収。

    delta < 0: 巡航 → 着地の順に短縮 (急停止演出)
    delta > 0: 着地を延長 (「まだ止まらない?」演出)
    """
    if ratio <= 0:
        return times
    r = min(SPIN_DURATION_RANDOM_MAX_RATIO, max(0.0, ratio))
    delta_ms = (random.random() * 2 - 1) * r * times.total_ms
    if delta_ms == 0:
        return times

    push_len    = times.push_end_ms
    cruise_len  = times.cruise_end_ms - times.push_end_ms
    decel_len   = times.decel_end_ms  - times.cruise_end_ms
    landing_len = times.total_ms      - times.decel_end_ms

    new_cruise_len  = cruise_len
    new_landing_len = landing_len

    if delta_ms < 0:
        cut = -delta_ms
        cruise_avail   = max(0.0, cruise_len  - 50.0)
        cruise_cut     = min(cut, cruise_avail)
        new_cruise_len = cruise_len - cruise_cut
        cut -= cruise_cut
        if cut > 0:
            landing_avail   = max(0.0, landing_len - 200.0)
            new_landing_len = landing_len - min(cut, landing_avail)
    else:
        new_landing_len = landing_len + delta_ms

    new_cruise_end = push_len + new_cruise_len
    new_decel_end  = new_cruise_end + decel_len
    new_total_ms   = new_decel_end  + new_landing_len

    return dataclasses.replace(
        times,
        cruise_end_ms=new_cruise_end,
        decel_end_ms=new_decel_end,
        total_ms=new_total_ms,
    )


def apply_phase_randomize_to_times(times: PhaseTimes, intensity: float) -> PhaseTimes:
    """各フェーズ長・速度を ±intensity で揺らす。totalMs を維持。"""
    if intensity <= 0:
        return times
    i_val = min(SPIN_PHASE_RANDOMIZE_MAX, max(0.0, intensity))

    def rand():
        return 1.0 + (random.random() * 2 - 1) * i_val

    push_len    = times.push_end_ms
    cruise_len  = times.cruise_end_ms - times.push_end_ms
    decel_len   = times.decel_end_ms  - times.cruise_end_ms
    landing_len = times.total_ms      - times.decel_end_ms

    p1 = max(50.0, push_len    * rand())
    p2 = max(50.0, cruise_len  * rand())
    p3 = max(50.0, decel_len   * rand())
    p4 = max(50.0, landing_len * rand())

    total = p1 + p2 + p3 + p4
    scale = times.total_ms / total
    p1 *= scale
    p2 *= scale
    p3 *= scale
    p4 *= scale

    new_v1 = _clamp(times.v1 * rand(), PEAK_SPEED_MIN_RPS, PEAK_SPEED_MAX_RPS)
    new_v2 = _clamp(times.v2 * rand(), PEAK_SPEED_MIN_RPS, PEAK_SPEED_MAX_RPS)
    new_v3 = _clamp(times.v3 * rand(), PEAK_SPEED_MIN_RPS, PEAK_SPEED_MAX_RPS)

    return dataclasses.replace(
        times,
        push_end_ms=p1,
        cruise_end_ms=p1 + p2,
        decel_end_ms=p1 + p2 + p3,
        v1=new_v1, v2=new_v2, v3=new_v3,
    )


# ── 公開 API: 積分計算 ────────────────────────────────────────────────────
def _phase_area_up_to(
    local_t: float,
    phase_len_sec: float,
    v_start: float,
    v_end: float,
    curve: str,
) -> float:
    """1フェーズの [0, local_t] における累積回転数 (解析積分)。

    速度プロファイル v(s) (s ∈ [0,1]):
      linear    : v_start + dv * s
      easeIn    : v_start + dv * s^p
      easeOut   : v_end   - dv * (1-s)^p
      easeInOut : v_start + dv * smoothstep(s)  (smoothstep = 3s²-2s³)
    """
    if local_t <= 0 or phase_len_sec <= 0:
        return 0.0
    t = min(1.0, local_t)
    dv = v_end - v_start
    p = CURVE_POWER

    if curve == 'linear':
        integral = v_start * t + (dv * t * t) / 2.0
    elif curve == 'easeIn':
        integral = v_start * t + (dv * t ** (p + 1)) / (p + 1)
    elif curve == 'easeOut':
        integral = v_end * t - (dv * (1.0 - (1.0 - t) ** (p + 1))) / (p + 1)
    else:  # easeInOut (smoothstep: 3s²-2s³)
        sm = t * t * t - (t * t * t * t) / 2.0
        integral = v_start * t + dv * sm

    return phase_len_sec * integral


def rotations_at(t_ms: float, times: PhaseTimes) -> float:
    """時刻 t_ms における累積回転数 (revolution) を返す。

    spin_controller が角度計算に使用する中核関数。
    """
    if t_ms <= 0:
        return 0.0

    v0, v1, v2, v3, v4 = 0.0, times.v1, times.v2, times.v3, 0.0

    push_len_s    = times.push_end_ms / 1000.0
    cruise_len_s  = (times.cruise_end_ms - times.push_end_ms) / 1000.0
    decel_len_s   = (times.decel_end_ms  - times.cruise_end_ms) / 1000.0
    landing_len_s = (times.total_ms      - times.decel_end_ms) / 1000.0

    # ① push
    if times.push_end_ms > 0 and t_ms <= times.push_end_ms:
        return _phase_area_up_to(
            t_ms / times.push_end_ms, push_len_s, v0, v1, times.push_curve)
    r = _phase_area_up_to(1.0, push_len_s, v0, v1, times.push_curve)

    # ② cruise
    cruise_span = times.cruise_end_ms - times.push_end_ms
    if cruise_span > 0 and t_ms <= times.cruise_end_ms:
        lt = (t_ms - times.push_end_ms) / cruise_span
        return r + _phase_area_up_to(lt, cruise_len_s, v1, v2, times.cruise_curve)
    r += _phase_area_up_to(1.0, cruise_len_s, v1, v2, times.cruise_curve)

    # ③ decel
    decel_span = times.decel_end_ms - times.cruise_end_ms
    if decel_span > 0 and t_ms <= times.decel_end_ms:
        lt = (t_ms - times.cruise_end_ms) / decel_span
        return r + _phase_area_up_to(lt, decel_len_s, v2, v3, times.decel_curve)
    r += _phase_area_up_to(1.0, decel_len_s, v2, v3, times.decel_curve)

    # ④ landing
    landing_span = times.total_ms - times.decel_end_ms
    if landing_span > 0 and t_ms <= times.total_ms:
        lt = (t_ms - times.decel_end_ms) / landing_span
        return r + _phase_area_up_to(lt, landing_len_s, v3, v4, times.landing_curve)
    return r + _phase_area_up_to(1.0, landing_len_s, v3, v4, times.landing_curve)


def build_phase_times(
    duration_ms: float,
    profile: str = 'z',
    overrides: Optional[dict] = None,
    duration_random_ratio: float = 0.0,
    phase_randomize: float = 0.0,
    preset_random: bool = False,
    duration_random: bool = False,
) -> PhaseTimes:
    """スピン開始時に呼ぶ: ランダム化まで含めた最終 PhaseTimes を生成する。

    適用順序:
      1. preset_random → effProfile (X/Y/Z から均等抽選)
      2. duration_random → effDurationMs (プリセット候補から均等抽選)
      3. get_effective_phase_times(effDurationMs, overrides, effProfile)
      4. apply_random_duration_to_times(times, duration_random_ratio)
      5. apply_phase_randomize_to_times(times, phase_randomize)
    """
    eff_profile  = _pick_random(PRESET_PROFILES_LIST) if preset_random else profile
    eff_duration = _pick_random(PRESET_DURATIONS_MS)  if duration_random else duration_ms

    times = get_effective_phase_times(eff_duration, overrides, eff_profile)
    times = apply_random_duration_to_times(times, duration_random_ratio)
    times = apply_phase_randomize_to_times(times, phase_randomize)
    return times
