"""
RRoulette — デザイン設定基盤 (v0.4.2)

将来の完全自由編集に耐えるデザイン設定コンテナ。

構造:
  DesignSettings (トップレベル)
    ├─ preset_name: str
    ├─ global_colors: GlobalColors   # 全体共通カラートークン
    ├─ wheel: WheelDesign            # ホイール描画用設定
    ├─ segment: SegmentDesign        # セグメント配色（プリセット＋個別上書き）
    ├─ pointer: PointerDesign        # ポインター描画用設定
    ├─ log: LogDesign                # ログオーバーレイ描画用設定
    ├─ item_list: ItemListDesign     # 項目リスト UI 用設定
    ├─ cfg_panel: CfgPanelDesign     # 設定パネル UI 用設定
    └─ fonts: FontSettings           # フォント設定（用途別）

保存:
  config JSON の "design" キー配下に to_dict() で保存。
  将来のデザイン専用インポート/エクスポートや独立デザインエディタへの接続を想定。

将来の拡張ポイント:
  - SegmentDesign.overrides で項目/セグメント単位の個別色上書き
  - デザインプリセットを別ファイルとして export/import
  - ルーレット全体プリセット（DesignSettings はその一部として組み込める）
"""

import dataclasses
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List


# ════════════════════════════════════════════════════════════════════
#  ユーティリティ
# ════════════════════════════════════════════════════════════════════

def _safe_from_dict(cls, d: dict):
    """dataclass cls を dict d から安全に構築する。
    未知のキーは無視し、欠損キーはデフォルト値を使用する。"""
    if not d:
        return cls()
    valid_keys = {f.name for f in dataclasses.fields(cls)}
    kwargs = {k: v for k, v in d.items() if k in valid_keys}
    try:
        return cls(**kwargs)
    except Exception:
        return cls()


# ════════════════════════════════════════════════════════════════════
#  共通カラートークン
# ════════════════════════════════════════════════════════════════════

@dataclass
class GlobalColors:
    """全ウィジェットで共有される基本カラートークン"""
    bg: str = "#1a1a2e"          # 背景色
    panel: str = "#16213e"       # パネル色
    accent: str = "#e94560"      # アクセント色
    text: str = "#ffffff"        # 文字色
    text_sub: str = "#aaaacc"    # 補助文字色
    gold: str = "#f8d347"        # ゴールド（強調・選択・ポインター）
    separator: str = "#44446a"   # セパレーター・暗色 UI 要素


# ════════════════════════════════════════════════════════════════════
#  フォント設定
# ════════════════════════════════════════════════════════════════════

@dataclass
class WheelFontSettings:
    """ルーレット文字表示用フォント設定"""
    family: str = "Meiryo"
    # 「省略」モードの基準サイズ（表示できない場合は省略記号で切り捨て）
    omit_base_size: int = 12
    # 「収める」モードの基準サイズ（探索上限として使用。大きく置く挙動を維持する）
    fit_base_size: int = 72
    # 「縮小」モードの初期サイズ（収まらない場合のみ縮小する）
    shrink_base_size: int = 12
    min_size: int = 6
    max_size: int = 72


@dataclass
class FontSettings:
    """用途別フォント設定"""
    wheel: WheelFontSettings = field(default_factory=WheelFontSettings)
    ui_family: str = "Meiryo"       # 項目リスト・設定 UI 用フォントファミリー
    log_family: str = "Meiryo"      # ログオーバーレイ用フォントファミリー
    result_family: str = "Meiryo"   # 結果表示用フォントファミリー


# ════════════════════════════════════════════════════════════════════
#  セグメント配色プリセット
# ════════════════════════════════════════════════════════════════════

SEGMENT_COLOR_PRESETS: Dict[str, List[str]] = {
    # ── デフォルト: 彩度高め・色相バランス重視（既存維持）──────────────
    "デフォルト": [
        "#E74C3C", "#3498DB", "#2ECC71", "#F39C12", "#9B59B6",
        "#1ABC9C", "#E67E22", "#27AE60", "#E91E63", "#00BCD4",
        "#8BC34A", "#FF5722", "#2980B9", "#8E44AD", "#F4D03F",
    ],
    # ── パステル: 落ち着いたミッドトーン（白文字視認性を確保した深みのある色）──
    # 旧パステル（#FFB3BA等）は暗背景で白文字コントラスト比 < 3:1 のため全面改訂
    # 方針: HSL S=50-65%, L=30-42% 程度。白文字コントラスト比 ≥ 4.5:1 を目標
    "パステル": [
        "#b84040",  # くすんだクリムゾン
        "#b06820",  # くすんだ琥珀
        "#4e7a18",  # くすんだオリーブ
        "#246b30",  # くすんだ深緑
        "#1a4f8a",  # くすんだスチールブルー
        "#5c2480",  # くすんだ紫
        "#b83060",  # くすんだラズベリー
        "#186868",  # くすんだティール
        "#9a4418",  # くすんだテラコッタ
        "#2e6845",  # くすんだセージ
        "#3a2278",  # くすんだ藍
        "#145e70",  # くすんだシアンブルー
        "#1e5848",  # くすんだシーフォーム
        "#8c5808",  # くすんだ琥珀褐色
        "#6e3a18",  # くすんだシエナ
    ],
    # ── モノクロ: 交互配置グレー（隣接セグメントを明確に区別）──────────
    # 旧モノクロは #F5F5F5 等の超明色で白文字不可・隣接色差も不十分だったため改訂
    # 方針: 暗グレー(~#303030) と中グレー(~#606060) を交互配置
    #       最大輝度 #686868 → 白文字コントラスト比 ≈ 5.0:1
    "モノクロ": [
        "#2e2e2e", "#666666", "#383838", "#585858", "#282828",
        "#606060", "#323232", "#545454", "#3e3e3e", "#686868",
        "#2a2a2a", "#525252", "#3c3c3c", "#626262", "#2c2c2c",
    ],
    # ── ビビッド: 高彩度・最大色相差（配信・エネルギッシュな演出向け）──
    # 方針: 白文字コントラスト比 ≥ 4.5:1 を確保しつつ鮮やかさを最大化
    #       黄系は #996600 程度まで暗くして視認性を担保
    "ビビッド": [
        "#dd1111",  # 鮮烈な赤
        "#e06800",  # 鮮烈なオレンジ
        "#996600",  # 鮮烈な琥珀（黄は暗くして白文字対応）
        "#118811",  # 鮮烈な緑
        "#1155dd",  # 鮮烈な青
        "#9911cc",  # 鮮烈な紫
        "#dd1188",  # 鮮烈なマゼンタ
        "#009090",  # 鮮烈なティール
        "#ee4400",  # 鮮烈な赤橙
        "#008844",  # 鮮烈なエメラルド
        "#cc0066",  # 鮮烈なラズベリー
        "#0044cc",  # 鮮烈なロイヤルブルー
        "#a06800",  # 鮮烈なアンバーゴールド
        "#006633",  # 鮮烈な深緑
        "#7700bb",  # 鮮烈なバイオレット
    ],
}

SEGMENT_PRESET_NAMES: List[str] = list(SEGMENT_COLOR_PRESETS.keys())


@dataclass
class SegmentDesign:
    """セグメント配色設定（プリセット＋将来の個別上書き対応）"""
    preset_name: str = "デフォルト"
    # 将来の個別上書き: {item_index: color_str}
    # 優先順: overrides > preset > デフォルト
    overrides: Dict[int, str] = field(default_factory=dict)
    # ユーザー作成プリセット用カスタム配色（非空の場合 preset_name より優先）
    custom_colors: List[str] = field(default_factory=list)

    def resolve_colors(self) -> List[str]:
        """現在の配色リストを返す。custom_colors が設定されていればそれを優先する"""
        if self.custom_colors:
            return self.custom_colors
        return SEGMENT_COLOR_PRESETS.get(
            self.preset_name, SEGMENT_COLOR_PRESETS["デフォルト"]
        )

    def color_for(self, item_index: int) -> str:
        """item_index に対応する色を返す。個別上書きがあればそれを優先する"""
        if item_index in self.overrides:
            return self.overrides[item_index]
        colors = self.resolve_colors()
        return colors[item_index % len(colors)]


# ════════════════════════════════════════════════════════════════════
#  用途別デザイン設定
# ════════════════════════════════════════════════════════════════════

@dataclass
class WheelDesign:
    """ホイール描画用設定"""
    text_color: str = "#ffffff"
    outline_color: str = "#ffffff"          # ホイール外周線
    outline_width: int = 4
    segment_outline_color: str = "#ffffff"  # セグメント間の線
    segment_outline_width: int = 2
    hole_outline_color: str = "#ffffff"     # ドーナツ穴の枠
    hole_outline_width: int = 3


@dataclass
class PointerDesign:
    """ポインター描画用設定"""
    fill_color: str = "#f8d347"
    outline_color: str = "#ffffff"
    outline_width: int = 2


@dataclass
class LogDesign:
    """ログオーバーレイ描画用設定"""
    text_color: str = "#aaaacc"
    shadow_color: str = "#000000"
    box_outline_color: str = "#4455bb"
    box_bg_color: str = "#111133"
    font_size: int = 9


@dataclass
class ItemListDesign:
    """項目リスト UI 用設定（None = GlobalColors を参照）"""
    bg: Optional[str] = None
    accent: Optional[str] = None


@dataclass
class CfgPanelDesign:
    """設定パネル UI 用設定（None = GlobalColors を参照）"""
    bg: Optional[str] = None
    accent: Optional[str] = None


# ════════════════════════════════════════════════════════════════════
#  DesignSettings — トップレベルコンテナ
# ════════════════════════════════════════════════════════════════════

@dataclass
class DesignSettings:
    """
    RRoulette デザイン設定の全体コンテナ。

    config JSON の "design" キー配下に保存される。
    将来のデザイン専用インポート/エクスポートや
    独立デザインエディタへの接続を想定した構造。

    DesignSettings.to_dict() / DesignSettings.from_dict() で
    JSON シリアライズ/デシリアライズが可能。
    """
    preset_name: str = "デフォルト"
    global_colors: GlobalColors = field(default_factory=GlobalColors)
    wheel: WheelDesign = field(default_factory=WheelDesign)
    segment: SegmentDesign = field(default_factory=SegmentDesign)
    pointer: PointerDesign = field(default_factory=PointerDesign)
    log: LogDesign = field(default_factory=LogDesign)
    item_list: ItemListDesign = field(default_factory=ItemListDesign)
    cfg_panel: CfgPanelDesign = field(default_factory=CfgPanelDesign)
    fonts: FontSettings = field(default_factory=FontSettings)

    # ── GlobalColors へのショートカット ──────────────────────────────
    # 既存の定数名と対応させ、描画コードの移行コストを最小化する

    @property
    def bg(self) -> str:
        return self.global_colors.bg

    @property
    def panel(self) -> str:
        return self.global_colors.panel

    @property
    def accent(self) -> str:
        return self.global_colors.accent

    @property
    def text(self) -> str:
        return self.global_colors.text

    @property
    def text_sub(self) -> str:
        return self.global_colors.text_sub

    @property
    def gold(self) -> str:
        return self.global_colors.gold

    @property
    def separator(self) -> str:
        return self.global_colors.separator

    def to_dict(self) -> dict:
        """JSON シリアライズ用 dict に変換する"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignSettings":
        """dict から DesignSettings を復元する。不正な値は無視してデフォルトを使用"""
        if not d:
            return cls()
        try:
            # overrides のキーを int に変換（JSON では string key になる）
            seg_raw = d.get("segment", {}) or {}
            overrides_raw = seg_raw.get("overrides", {}) or {}
            overrides = {int(k): v for k, v in overrides_raw.items()}

            fonts_raw = d.get("fonts", {}) or {}
            wheel_font_raw = fonts_raw.get("wheel", {}) or {}

            return cls(
                preset_name=d.get("preset_name", "デフォルト"),
                global_colors=_safe_from_dict(GlobalColors, d.get("global_colors", {})),
                wheel=_safe_from_dict(WheelDesign, d.get("wheel", {})),
                segment=SegmentDesign(
                    preset_name=seg_raw.get("preset_name", "デフォルト"),
                    overrides=overrides,
                    custom_colors=seg_raw.get("custom_colors", []) or [],
                ),
                pointer=_safe_from_dict(PointerDesign, d.get("pointer", {})),
                log=_safe_from_dict(LogDesign, d.get("log", {})),
                item_list=_safe_from_dict(ItemListDesign, d.get("item_list", {})),
                cfg_panel=_safe_from_dict(CfgPanelDesign, d.get("cfg_panel", {})),
                fonts=FontSettings(
                    wheel=_safe_from_dict(WheelFontSettings, wheel_font_raw),
                    ui_family=fonts_raw.get("ui_family", "Meiryo"),
                    log_family=fonts_raw.get("log_family", "Meiryo"),
                    result_family=fonts_raw.get("result_family", "Meiryo"),
                ),
            )
        except Exception:
            return cls()

    def apply_preset(self, preset_name: str) -> None:
        """指定プリセットの配色・描画設定を適用する。
        segment.preset_name は独立して管理するため変更しない。"""
        preset = DESIGN_PRESETS.get(preset_name)
        if preset is None:
            return
        self.preset_name = preset.preset_name
        self.global_colors = GlobalColors(**asdict(preset.global_colors))
        self.wheel = WheelDesign(**asdict(preset.wheel))
        self.pointer = PointerDesign(**asdict(preset.pointer))
        self.log = LogDesign(**asdict(preset.log))
        # segment, fonts, item_list, cfg_panel は維持


# ════════════════════════════════════════════════════════════════════
#  組み込みデザインプリセット
# ════════════════════════════════════════════════════════════════════

def _make_warm() -> DesignSettings:
    """ウォーム: 深い茶褐色背景＋琥珀アクセント。落ち着いた暖色系配信向け。
    旧版は accent が #ff6b35 と強烈すぎ、separator が背景に埋もれていたため改訂。
    改訂方針:
      - bg を純黒に近い暗茶褐色にして視認性を確保
      - accent を落ち着いた琥珀オレンジに調整
      - text_sub は明るい琥珀色（読みやすさ重視）
      - gold は温かみのある黄金（ポインターとして機能する明度）
      - separator はパネルより明確に明るく識別可能に
    """
    return DesignSettings(
        preset_name="ウォーム",
        global_colors=GlobalColors(
            bg="#1a0f04",       # 非常に深い茶褐色
            panel="#241608",    # 濃い琥珀茶
            accent="#e08030",   # 落ち着いた琥珀オレンジ
            text="#ffffff",
            text_sub="#d4a870", # 明るい琥珀（bg 対比コントラスト比 ≈ 6:1）
            gold="#f0c030",     # 暖かいゴールド（ポインター色）
            separator="#3d2008",# bg より明確に明るい茶
        ),
        wheel=WheelDesign(
            text_color="#ffffff",
            outline_color="#d4a870",
            outline_width=4,
            segment_outline_color="#d4a870",
            segment_outline_width=2,
            hole_outline_color="#d4a870",
            hole_outline_width=3,
        ),
        pointer=PointerDesign(
            fill_color="#f0c030",
            outline_color="#ffffff",
            outline_width=2,
        ),
        log=LogDesign(
            text_color="#d4a870",
            shadow_color="#000000",
            box_outline_color="#7a4818",
            box_bg_color="#120a02",
        ),
    )


def _make_cool() -> DesignSettings:
    """クール: 深い紺背景＋スカイブルーアクセント。落ち着いた寒色系配信向け。
    旧版は gold="#00ffcc"（ティール）がセグメント色と被りやすく、
    separator="#003366" が panel に埋もれていたため改訂。
    改訂方針:
      - 背景を純黒に近い深い紺にして輝度を抑制
      - accent を過飽和な cyan から落ち着いたスカイブルーへ
      - gold = 暖かい琥珀ゴールド（寒色背景との補色コントラストでポインターが目立つ）
      - separator はパネルより明確に識別できる青系に
    """
    return DesignSettings(
        preset_name="クール",
        global_colors=GlobalColors(
            bg="#0c1825",       # 非常に深い紺
            panel="#12243a",    # 濃いスレートブルー
            accent="#4da8d8",   # 落ち着いたスカイブルー
            text="#ffffff",
            text_sub="#88b4d8", # 薄いスカイブルー（bg 対比コントラスト比 ≈ 5:1）
            gold="#f5c030",     # 暖かい琥珀ゴールド（寒色背景に映える補色関係）
            separator="#1c3850",# panel より明確に明るい青系
        ),
        wheel=WheelDesign(
            text_color="#ffffff",
            outline_color="#88b4d8",
            outline_width=4,
            segment_outline_color="#88b4d8",
            segment_outline_width=2,
            hole_outline_color="#88b4d8",
            hole_outline_width=3,
        ),
        pointer=PointerDesign(
            fill_color="#f5c030",   # 寒色背景に対して補色的に目立つ暖色ゴールド
            outline_color="#ffffff",
            outline_width=2,
        ),
        log=LogDesign(
            text_color="#88b4d8",
            shadow_color="#000000",
            box_outline_color="#1a5080",
            box_bg_color="#081420",
        ),
    )


def _make_high_contrast() -> DesignSettings:
    """ハイコントラスト: ほぼ黒背景＋最大視認性。OBS 配信・録画での見やすさ最優先。
    設計方針:
      - bg をほぼ黒にして全要素との最大コントラストを確保
      - text_sub も十分明るく（#cccccc）
      - ポインターは明るいイエロー＋黒縁で任意セグメント上でも埋もれない
      - accent はビビッドなピンク系でアクセント要素を即識別
    """
    return DesignSettings(
        preset_name="ハイコントラスト",
        global_colors=GlobalColors(
            bg="#0a0a0a",       # ほぼ黒
            panel="#141414",    # 非常に濃い灰
            accent="#ff4466",   # 鮮明なビビッドピンク
            text="#ffffff",
            text_sub="#cccccc", # 明るいグレー（十分な視認性）
            gold="#ffdd00",     # 明るいイエロー（ポインター最大視認性）
            separator="#2a2a2a",
        ),
        wheel=WheelDesign(
            text_color="#ffffff",
            outline_color="#ffffff",
            outline_width=4,
            segment_outline_color="#ffffff",
            segment_outline_width=2,
            hole_outline_color="#ffffff",
            hole_outline_width=3,
        ),
        pointer=PointerDesign(
            fill_color="#ffdd00",   # 明るいイエロー
            outline_color="#000000",# 黒縁でどのセグメント上でも確実に視認
            outline_width=2,
        ),
        log=LogDesign(
            text_color="#cccccc",
            shadow_color="#000000",
            box_outline_color="#555555",
            box_bg_color="#0f0f0f",
        ),
    )


DESIGN_PRESETS: Dict[str, DesignSettings] = {
    "デフォルト":       DesignSettings(preset_name="デフォルト"),
    "ウォーム":         _make_warm(),
    "クール":           _make_cool(),
    "ハイコントラスト": _make_high_contrast(),
}

DESIGN_PRESET_NAMES: List[str] = list(DESIGN_PRESETS.keys())


# ════════════════════════════════════════════════════════════════════
#  DesignPresetManager — プリセット管理
# ════════════════════════════════════════════════════════════════════

class DesignPresetManager:
    """デザインプリセットとセグメント配色プリセットの管理クラス。

    組み込みプリセット（DESIGN_PRESETS / SEGMENT_COLOR_PRESETS）はコード側に保持し、
    ユーザーが作成・編集したプリセットは別管理で永続化する。

    ルール:
      - 組み込みプリセット: 編集可、リセット可（コード基準値へ）、名前変更・削除は不可
      - ユーザー作成プリセット: 名前変更可、削除可
    """

    def __init__(self) -> None:
        # key = プリセット名, value = DesignSettings.to_dict()
        # 組み込み名のエントリ = ユーザー上書き分
        # 非組み込み名のエントリ = ユーザー作成プリセット
        self._user_design: Dict[str, dict] = {}
        # key = プリセット名, value = List[str]
        self._user_segment: Dict[str, List[str]] = {}

    # ── 全プリセット名 ──────────────────────────────────────────────

    def all_design_names(self) -> List[str]:
        """全デザインプリセット名（組み込み先頭、ユーザー作成を末尾に追加）"""
        names: List[str] = list(DESIGN_PRESETS.keys())
        for n in self._user_design:
            if n not in DESIGN_PRESETS:
                names.append(n)
        return names

    def all_segment_names(self) -> List[str]:
        """全セグメント配色プリセット名"""
        names: List[str] = list(SEGMENT_COLOR_PRESETS.keys())
        for n in self._user_segment:
            if n not in SEGMENT_COLOR_PRESETS:
                names.append(n)
        return names

    # ── 種別判定 ─────────────────────────────────────────────────────

    def is_builtin_design(self, name: str) -> bool:
        return name in DESIGN_PRESETS

    def is_builtin_segment(self, name: str) -> bool:
        return name in SEGMENT_COLOR_PRESETS

    # ── 取得 ──────────────────────────────────────────────────────────

    def get_design(self, name: str) -> "DesignSettings":
        """指定名のデザイン設定を返す（ユーザー上書きがあればそれを優先）"""
        if name in self._user_design:
            ds = DesignSettings.from_dict(self._user_design[name])
            ds.preset_name = name
            return ds
        if name in DESIGN_PRESETS:
            return DesignSettings.from_dict(DESIGN_PRESETS[name].to_dict())
        return DesignSettings(preset_name=name)

    def get_segment_colors(self, name: str) -> List[str]:
        """指定名のセグメント配色リストを返す"""
        if name in self._user_segment:
            return list(self._user_segment[name])
        if name in SEGMENT_COLOR_PRESETS:
            return list(SEGMENT_COLOR_PRESETS[name])
        return list(SEGMENT_COLOR_PRESETS["デフォルト"])

    # ── 保存 ──────────────────────────────────────────────────────────

    def save_design(self, name: str, design: "DesignSettings") -> None:
        """指定名でデザイン設定を保存する"""
        d = design.to_dict()
        d["preset_name"] = name
        self._user_design[name] = d

    def save_segment(self, name: str, colors: List[str]) -> None:
        """指定名でセグメント配色を保存する"""
        self._user_segment[name] = list(colors)

    # ── リセット ──────────────────────────────────────────────────────

    def reset_design(self, name: str) -> "DesignSettings":
        """ユーザー上書きを削除してコード基準値を返す"""
        self._user_design.pop(name, None)
        if name in DESIGN_PRESETS:
            return DesignSettings.from_dict(DESIGN_PRESETS[name].to_dict())
        return DesignSettings(preset_name=name)

    def reset_segment(self, name: str) -> List[str]:
        """ユーザー上書きを削除してコード基準値を返す"""
        self._user_segment.pop(name, None)
        if name in SEGMENT_COLOR_PRESETS:
            return list(SEGMENT_COLOR_PRESETS[name])
        return list(SEGMENT_COLOR_PRESETS["デフォルト"])

    # ── 新規作成 / 複製 ───────────────────────────────────────────────

    def create_design(self, name: str, base_name: str = "デフォルト") -> "DesignSettings":
        """デフォルト（または指定）を基準に新規プリセットを作成する"""
        ds = self.get_design(base_name)
        ds.preset_name = name
        self.save_design(name, ds)
        return ds

    def duplicate_design(self, src_name: str, new_name: str) -> "DesignSettings":
        """既存プリセットを複製する"""
        ds = self.get_design(src_name)
        ds.preset_name = new_name
        self.save_design(new_name, ds)
        return ds

    def create_segment(self, name: str, base_name: str = "デフォルト") -> List[str]:
        """デフォルト（または指定）を基準に新規セグメント配色を作成する"""
        colors = self.get_segment_colors(base_name)
        self._user_segment[name] = list(colors)
        return colors

    def duplicate_segment(self, src_name: str, new_name: str) -> List[str]:
        """既存セグメント配色を複製する"""
        colors = self.get_segment_colors(src_name)
        self._user_segment[new_name] = list(colors)
        return colors

    # ── 名前変更 / 削除（ユーザー作成のみ） ──────────────────────────

    def rename_design(self, old: str, new: str) -> None:
        if old in self._user_design and old not in DESIGN_PRESETS:
            self._user_design[new] = self._user_design.pop(old)
            self._user_design[new]["preset_name"] = new

    def delete_design(self, name: str) -> None:
        if name in self._user_design and name not in DESIGN_PRESETS:
            del self._user_design[name]

    def rename_segment(self, old: str, new: str) -> None:
        if old in self._user_segment and old not in SEGMENT_COLOR_PRESETS:
            self._user_segment[new] = self._user_segment.pop(old)

    def delete_segment(self, name: str) -> None:
        if name in self._user_segment and name not in SEGMENT_COLOR_PRESETS:
            del self._user_segment[name]

    # ── セグメント配色を DesignSettings に適用 ────────────────────────

    def apply_segment_to_design(self, name: str, design: "DesignSettings") -> None:
        """セグメント配色プリセットを design.segment に反映する。
        ユーザーが編集した色がある場合（組み込み・ユーザー作成問わず）は
        custom_colors に色リストを設定する。
        未編集の組み込みプリセットは custom_colors をクリアして名前引きに委ねる。"""
        design.segment.preset_name = name
        if name in self._user_segment:
            # ユーザーが保存した色（編集済み組み込み or ユーザー作成プリセット）
            design.segment.custom_colors = list(self._user_segment[name])
        else:
            # 未編集の組み込みプリセット → preset_name での名前引きを使用
            design.segment.custom_colors = []

    # ── シリアライズ ──────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "user_design": dict(self._user_design),
            "user_segment": {k: list(v) for k, v in self._user_segment.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DesignPresetManager":
        mgr = cls()
        if not d:
            return mgr
        ud = d.get("user_design", {})
        us = d.get("user_segment", {})
        if isinstance(ud, dict):
            mgr._user_design = {str(k): v for k, v in ud.items() if isinstance(v, dict)}
        if isinstance(us, dict):
            mgr._user_segment = {str(k): list(v) for k, v in us.items() if isinstance(v, list)}
        return mgr
