"""
RCommentHub — 定数定義
"""

VERSION = "0.3.0"

# ─── ウィンドウ ──────────────────────────────────────────────────────────────
WINDOW_TITLE   = "RCommentHub — 詳細"
DEFAULT_WIDTH  = 1280
DEFAULT_HEIGHT = 800
MIN_WIDTH      = 800
MIN_HEIGHT     = 500

# ─── 透過キーカラー ──────────────────────────────────────────────────────────
TRANSPARENT_KEY = "#010101"

# ─── 設定ファイル ────────────────────────────────────────────────────────────
CONFIG_FILENAME = "rcommenthub_settings.json"

# ─── コメント種別 ────────────────────────────────────────────────────────────
EVENT_TYPE_LABELS = {
    "textMessageEvent":           "通常",
    "superChatEvent":             "SuperChat",
    "superStickerEvent":          "SuperSticker",
    "memberMilestoneChatEvent":   "メンバー記念",
    "membershipGiftingEvent":     "メンバーギフト",
    "giftMembershipReceivedEvent":"メンバーギフト受取",
    "pollEvent":                  "投票",
    "messageDeletedEvent":        "削除",
    "userBannedEvent":            "BAN",
    "tombstone":                  "Tombstone",
    "chatEndedEvent":             "チャット終了",
    "unknown":                    "その他",
}

# 種別フィルタグループ（チェックボックス用ラベル → 対応する kind 一覧）
FILTER_TYPE_GROUPS = {
    "通常コメント":       ["textMessageEvent"],
    "Super Chat":        ["superChatEvent"],
    "Super Sticker":     ["superStickerEvent"],
    "削除イベント":       ["messageDeletedEvent"],
    "BANイベント":        ["userBannedEvent"],
    "メンバー関連":       ["memberMilestoneChatEvent", "membershipGiftingEvent", "giftMembershipReceivedEvent"],
    "投票関連":           ["pollEvent"],
    "その他イベント":     ["tombstone", "chatEndedEvent", "unknown"],
}

# ─── 処理状態 ────────────────────────────────────────────────────────────────
PROC_STATUS_LABELS = {
    "unprocessed": "未処理",
    "matched":     "フィルタ一致",
    "sent":        "連携送信済み",
    "excluded":    "除外",
    "error":       "エラー",
}

# ─── 接続状態 ────────────────────────────────────────────────────────────────
CONN_STATUS_LABELS = {
    "disconnected":   "未接続",
    "connecting":     "接続中",
    "receiving":      "受信中",
    "reconnecting":   "再接続中",
    "disconnecting":  "切断",
    "error":          "エラー",
    "debug":          "DEBUG受信中",
}

CONN_STATUS_COLORS = {
    "disconnected":  "#888888",
    "connecting":    "#FFA500",
    "receiving":     "#00CC44",
    "reconnecting":  "#FFA500",
    "disconnecting": "#888888",
    "error":         "#FF4444",
    "debug":         "#FF8C00",
}

# ─── 入力ソース ──────────────────────────────────────────────────────────────
INPUT_SOURCE_YOUTUBE = "live_youtube"
INPUT_SOURCE_TWITCH  = "live_twitch"
INPUT_SOURCE_DEBUG   = "debug_manual"

# ─── 接続ソース定義（後方互換用 — 新規コードは connection_profiles を使うこと）──
CONN_IDS = ("conn1", "conn2")

SOURCE_COLORS = {
    "conn1": "#88AAFF",   # 青系
    "conn2": "#FFBB44",   # 橙系
}

SOURCE_DEFAULT_NAMES = {
    "conn1": "接続1",
    "conn2": "接続2",
}

# ─── 接続プロファイル カラーパレット ─────────────────────────────────────────
# インデックス順に接続プロファイルへ割り当てる
SOURCE_COLOR_PALETTE = [
    "#88AAFF",   # 0: 青系
    "#FFBB44",   # 1: 橙系
    "#44DD88",   # 2: 緑系
    "#FF88CC",   # 3: ピンク系
    "#88DDFF",   # 4: シアン系
]


def get_profile_color(profile_id: str, profiles: list) -> str:
    """
    プロファイルIDに対応する表示色を返す。
    プロファイルリスト内のインデックスから色パレットで決定する。
    """
    for i, p in enumerate(profiles):
        if p.get("profile_id") == profile_id:
            return SOURCE_COLOR_PALETTE[i % len(SOURCE_COLOR_PALETTE)]
    return "#AAAAAA"


def get_source_color(source_id: str) -> str:
    """
    source_id に対応する表示色を返す（profiles リスト不要版）。

    旧形式 (conn1/conn2) および新形式 (profile_N) の両方に対応する。
    インデックスが取れない場合はパレットの先頭色を返す。
    """
    # 旧形式
    if source_id in SOURCE_COLORS:
        return SOURCE_COLORS[source_id]
    # 新形式 "profile_N"
    if source_id.startswith("profile_"):
        try:
            idx = int(source_id.split("_", 1)[1])
            return SOURCE_COLOR_PALETTE[idx % len(SOURCE_COLOR_PALETTE)]
        except (IndexError, ValueError):
            pass
    # それ以外は固定ハッシュでパレットを選ぶ
    idx = hash(source_id) % len(SOURCE_COLOR_PALETTE)
    return SOURCE_COLOR_PALETTE[idx]


# ─── プラットフォーム定義 ────────────────────────────────────────────────────
PLATFORM_YOUTUBE = "youtube"
PLATFORM_TWITCH  = "twitch"

PLATFORM_LABELS = {
    PLATFORM_YOUTUBE: "YouTube",
    PLATFORM_TWITCH:  "Twitch",
}

# ─── 配信状態メッセージ ──────────────────────────────────────────────────────
STREAM_STATUS_LABELS = {
    "live":              "ライブ中",
    "chat_disabled":     "チャット無効",
    "ended":             "ライブ終了",
    "no_live_chat_id":   "liveChatId 未取得",
    "unknown":           "不明",
}

# ─── 権限フラグ ──────────────────────────────────────────────────────────────
ROLE_OWNER     = "Owner"
ROLE_MODERATOR = "Mod"
ROLE_MEMBER    = "Mbr"
ROLE_VERIFIED  = "Ver"

# ─── 一覧カラム定義 ─────────────────────────────────────────────────────────
# (id, 表示名, 幅, stretch)
LIST_COLUMNS = [
    ("no",          "No",        50,  False),
    ("recv_time",   "受信時刻",  90,  False),
    ("post_time",   "投稿時刻",  90,  False),
    ("kind",        "種別",      90,  False),
    ("author",      "投稿者名", 130,  True),
    ("body",        "本文",     250,  True),
    ("channel_id",  "Ch ID",    160,  False),
    ("roles",       "権限",      60,  False),
    ("msg_id",      "Msg ID",   160,  False),
    ("status",      "状態",      80,  False),
]

# ─── 行カラー（種別・権限による色分け） ────────────────────────────────────
ROW_COLORS = {
    "owner":       {"bg": "#2A3A6A", "fg": "#FFD700"},
    "moderator":   {"bg": "#1E3A3A", "fg": "#80FFCC"},
    "member":      {"bg": "#1E2A3A", "fg": "#80CCFF"},
    "superchat":   {"bg": "#3A2A10", "fg": "#FFB347"},
    "supersticker":{"bg": "#2A2A10", "fg": "#FFD080"},
    "deleted":     {"bg": "#3A1A1A", "fg": "#FF8080"},
    "banned":      {"bg": "#4A0000", "fg": "#FF6060"},
    "matched":     {"bg": "#1A3A1A", "fg": "#80FF80"},
    "selected":    {"bg": "#3A5A8A", "fg": "#FFFFFF"},
    "default":     {"bg": "#1A1A2E", "fg": "#C8C8D8"},
    "alt":         {"bg": "#1E1E36", "fg": "#C8C8D8"},
}

# ─── カラーテーマ定義 ────────────────────────────────────────────────────────
COLOR_THEMES = {
    "ダーク (デフォルト)": {
        "bg_main":   "#0D0D1A",
        "bg_panel":  "#141428",
        "bg_header": "#0A0A1E",
        "bg_list":   "#1A1A2E",
        "bg_detail": "#141428",
        "bg_log":    "#0A0A14",
        "fg_main":   "#C8C8D8",
        "fg_label":  "#8888AA",
        "fg_header": "#E0E0F0",
        "border":    "#2A2A4A",
        "accent":    "#3A5A8A",
    },
    "ダーク グリーン": {
        "bg_main":   "#0A1A0A",
        "bg_panel":  "#0F200F",
        "bg_header": "#071507",
        "bg_list":   "#142014",
        "bg_detail": "#0F200F",
        "bg_log":    "#070F07",
        "fg_main":   "#C8D8C8",
        "fg_label":  "#88AA88",
        "fg_header": "#E0F0E0",
        "border":    "#2A4A2A",
        "accent":    "#3A7A3A",
    },
    "ダーク パープル": {
        "bg_main":   "#130D1A",
        "bg_panel":  "#1E1428",
        "bg_header": "#0F0A1E",
        "bg_list":   "#261A2E",
        "bg_detail": "#1E1428",
        "bg_log":    "#0A0714",
        "fg_main":   "#D0C8E0",
        "fg_label":  "#9988BB",
        "fg_header": "#EAE0FF",
        "border":    "#3A2A5A",
        "accent":    "#6A3A9A",
    },
    "ダーク アンバー": {
        "bg_main":   "#1A130A",
        "bg_panel":  "#281E0F",
        "bg_header": "#1E1507",
        "bg_list":   "#2E2014",
        "bg_detail": "#281E0F",
        "bg_log":    "#140F07",
        "fg_main":   "#E0D8C0",
        "fg_label":  "#BBAA88",
        "fg_header": "#F0EAD0",
        "border":    "#5A4A2A",
        "accent":    "#9A7A3A",
    },
    "ライト グレー": {
        "bg_main":   "#F0F0F5",
        "bg_panel":  "#E8E8F0",
        "bg_header": "#DCDCE8",
        "bg_list":   "#FFFFFF",
        "bg_detail": "#E8E8F0",
        "bg_log":    "#F8F8FF",
        "fg_main":   "#202030",
        "fg_label":  "#606080",
        "fg_header": "#101020",
        "border":    "#C0C0D0",
        "accent":    "#3A5A9A",
    },
}

# ─── UI 色（起動時に選択テーマで上書きされる） ──────────────────────────────
UI_COLORS = dict(COLOR_THEMES["ダーク (デフォルト)"])


def apply_theme(theme_name: str) -> None:
    """テーマを UI_COLORS に反映する（グローバル in-place 更新）"""
    theme = COLOR_THEMES.get(theme_name, COLOR_THEMES["ダーク (デフォルト)"])
    UI_COLORS.update(theme)

# ─── フォント ────────────────────────────────────────────────────────────────
FONT_FAMILY   = "メイリオ"
FONT_SIZE_S   = 9
FONT_SIZE_M   = 10
FONT_SIZE_L   = 11
FONT_SIZE_LOG = 9
