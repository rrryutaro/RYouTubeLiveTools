"""
RRoulette — 幾何計算
  扇形の安全領域計算・座標変換

座標系の定義:
  ローカル座標系（各セクター固有）:
    原点   = ホイール中心
    X軸    = セクター中央角方向（外向き正） = 放射方向
    Y軸    = 中央角から90°CCW = 接線方向

  テキスト描画（create_text angle=mid_deg）時:
    font.measure(text)  = 放射方向（X軸）の幅
    line_height * n行   = 接線方向（Y軸）の高さ
    → 行は接線方向に積まれ、各行の文字は放射方向に並ぶ
"""
import math
from dataclasses import dataclass


@dataclass
class SafeSector:
    index: int
    safe_start_angle_deg: float  # tkinter arc convention (0°=右, CCW正)
    safe_extent_deg: float       # 安全な角度幅
    safe_inner_radius: float
    safe_outer_radius: float

    @property
    def mid_angle_deg(self) -> float:
        return self.safe_start_angle_deg + self.safe_extent_deg / 2

    @property
    def safe_radial_height(self) -> float:
        """放射方向の安全幅（= 各行テキストの最大 font.measure 許容値）。"""
        return max(0.0, self.safe_outer_radius - self.safe_inner_radius)

    @property
    def half_extent_rad(self) -> float:
        return math.radians(self.safe_extent_deg / 2)

    @property
    def center_r(self) -> float:
        """安全領域の放射方向中心。"""
        return (self.safe_inner_radius + self.safe_outer_radius) / 2

    @property
    def outer_bias_r(self) -> float:
        """外周寄せ用の代表半径（安全領域の内側から 70% の位置）。
        center_r より外周側に寄せることで、テキストを外周寄りに配置できる。
        """
        return self.safe_inner_radius + self.safe_radial_height * 0.70

    def tangential_chord_at(self, r: float) -> float:
        """半径 r での接線方向の弦長（行を積める総高さの目安）。"""
        return 2.0 * r * math.sin(self.half_extent_rad)


def normalize_angle_deg(angle: float) -> float:
    return angle % 360.0


def get_sector_safe_area(
    start_angle_deg: float,
    extent_deg: float,
    inner_radius: float,
    outer_radius: float,
    radial_margin_inner: float,
    radial_margin_outer: float,
    angle_margin_deg: float,
    index: int = 0,
) -> SafeSector:
    """扇形から余白を除いた安全描画領域を返す。"""
    safe_extent = max(0.0, extent_deg - 2.0 * angle_margin_deg)
    return SafeSector(
        index=index,
        safe_start_angle_deg=start_angle_deg + angle_margin_deg,
        safe_extent_deg=safe_extent,
        safe_inner_radius=inner_radius + radial_margin_inner,
        safe_outer_radius=outer_radius - radial_margin_outer,
    )


def get_radial_width_at_tangential_offset(
    t_offset: float,
    center_r: float,
    safe: SafeSector,
    padding: float = 0.0,
) -> float:
    """接線方向オフセット t_offset の行について、放射方向に使える幅を返す。

    テキストは center_r を中心として放射方向に対称に広がると仮定する。
    制約:
      1. 外周円弧: x ≤ sqrt(safe_outer_r^2 - t^2)
      2. 内周円弧: x ≥ sqrt(safe_inner_r^2 - t^2)  (|t| < inner_r の場合)
      3. 角度境界: x ≥ |t| / tan(half_extent)
    テキスト中心 center_r の左右それぞれの余裕の小さい方 × 2 が使える幅。
    padding: 各辺から差し引くテキスト余白（px）。
    """
    t = abs(t_offset)

    # 外周円弧
    outer_sq = safe.safe_outer_radius ** 2 - t ** 2
    if outer_sq < 0:
        return 0.0
    x_outer = math.sqrt(outer_sq) - padding

    # 内周円弧（ドーナツ穴）
    if t < safe.safe_inner_radius:
        inner_sq = safe.safe_inner_radius ** 2 - t ** 2
        x_inner = math.sqrt(inner_sq) + padding
    else:
        x_inner = padding

    # 角度境界
    x_angular = (t / math.tan(safe.half_extent_rad) + padding
                 if safe.half_extent_rad > 0 else float('inf'))

    x_min = max(x_inner, x_angular)
    x_max = x_outer

    if x_max <= x_min:
        return 0.0

    # center_r を中心として左右対称に取れる幅
    avail_outer_side = x_max - center_r
    avail_inner_side = center_r - x_min
    return 2.0 * max(0.0, min(avail_outer_side, avail_inner_side))


def polar_to_canvas(
    cx: float, cy: float, r: float, angle_deg: float
) -> tuple:
    """極座標（tkinter arc 角度基準）をキャンバス座標に変換する。"""
    rad = math.radians(angle_deg)
    return cx + r * math.cos(rad), cy - r * math.sin(rad)
