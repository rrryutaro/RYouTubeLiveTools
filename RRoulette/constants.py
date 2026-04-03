"""
RRoulette — 共有定数
"""

VERSION = "0.4.2"

# Windows ウィンドウスタイル定数
GWL_EXSTYLE      = -20
WS_EX_APPWINDOW  = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

# ─── カラー ──────────────────────────────────────────────────────────
SEGMENT_COLORS = [
    "#E74C3C", "#3498DB", "#2ECC71", "#F39C12", "#9B59B6",
    "#1ABC9C", "#E67E22", "#27AE60", "#E91E63", "#00BCD4",
    "#8BC34A", "#FF5722", "#2980B9", "#8E44AD", "#F4D03F",
]
BG     = "#1a1a2e"
PANEL  = "#16213e"
ACCENT = "#e94560"
DARK2  = "#44446a"
WHITE  = "#ffffff"
GOLD   = "#f8d347"
TRANSPARENT_KEY = "#000100"   # 透過クロマキー（他のカラーと絶対に重複させないこと）

# ─── サイズ ──────────────────────────────────────────────────────────
# サイズプロファイル: (ラベル, メインパネル幅, 高さ)
# main_w ≒ h に揃えてキャンバスを正方形に近づけ、余白を最小化する
SIZE_PROFILES = [
    ("S", 530, 530),
    ("M", 620, 620),
    ("L", 740, 740),
]
MIN_W, MIN_H = 300, 300
MIN_R = 100          # ルーレット半径の最小値（px）
SIDEBAR_W = 224      # サイドバー幅 + パディング分
CFG_PANEL_W = 290    # 設定パネル幅

# ─── レイアウト余白 ──────────────────────────────────────────────────
MAIN_PANEL_PAD    = 4   # main_frame の padx / pady
POINTER_OVERHANG  = 28   # ポインターのホイール外周からの飛び出し量
WHEEL_OUTER_MARGIN = POINTER_OVERHANG + 4  # ホイール外周〜キャンバス端の余白（POINTER_OVERHANG + 安全余白 4px）

# ─── 各エリア独立最小サイズ ──────────────────────────────────────────
# メインパネル（ホイールキャンバス）の最小幅/高さ
# = 2 * (MIN_R + WHEEL_OUTER_MARGIN) + MAIN_PANEL_PAD * 2 = 272 px
MAIN_MIN_W = 2 * (MIN_R + WHEEL_OUTER_MARGIN) + MAIN_PANEL_PAD * 2
MAIN_MIN_H = MAIN_MIN_W
# 項目リストサイドバーの最小幅: タイトル行（ラベル＋4ボタン）が収まるサイズ
SIDEBAR_MIN_W = 300

# ─── ポインター ───────────────────────────────────────────────────────
POINTER_PRESET_NAMES   = ["上", "右", "下", "左", "任意"]
_POINTER_PRESET_ANGLES = [0.0, 90.0, 180.0, 270.0]   # 上/右/下/左（時計回り・上基準）

# ─── 項目リスト 制限値 ────────────────────────────────────────────────
ITEM_MAX_COUNT      = 36   # 最大項目数
ITEM_MAX_LINE_CHARS = 20   # 1行の最大文字数
ITEM_MAX_LINES      = 4    # 多行項目の最大行数

# ─── その他 ──────────────────────────────────────────────────────────
_ADD_SENTINEL = "＋ 新規グループを追加..."   # コンボボックス末尾の追加用エントリ

# ─── 確率・分割 ──────────────────────────────────────────────────────
SPLIT_MAX = 10
WEIGHT_BELOW_ONE = (0.75, 0.5, 0.25)

# ─── ドーナツ穴 ──────────────────────────────────────────────────────
DONUT_DRAW_RADIUS = 13   # 描画上のドーナツ穴半径（px）
DONUT_HIT_RADIUS  = 26   # クリック無効化半径（px）= DONUT_DRAW_RADIUS × 2


class Segment:
    """ルーレットの1セグメントを表すデータクラス。"""
    __slots__ = ("item_text", "item_index", "arc", "start_angle")

    def __init__(self, item_text, item_index, arc, start_angle=0.0):
        self.item_text   = item_text
        self.item_index  = item_index
        self.arc         = arc
        self.start_angle = start_angle
