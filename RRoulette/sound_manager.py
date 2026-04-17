# ─── サウンド用ライブラリ（オプション）────────────────────────────────
try:
    import numpy as np
    import pygame
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

TICK_PATTERN_NAMES = ["スナップ", "クリック", "ドラム", "コイン", "ソフト", "消音", "カスタム"]
WIN_PATTERN_NAMES  = ["ベル", "ファンファーレ", "カジノ", "チャイム", "ビクトリー", "消音", "カスタム"]


# ════════════════════════════════════════════════════════════════════
#  SoundManager — プログラムで音を生成（外部ファイル不要）
# ════════════════════════════════════════════════════════════════════
class SoundManager:
    """numpy + pygame で効果音をゼロから生成。外部音声ファイル不使用のためライセンスフリー。"""

    def __init__(self):
        self.muted         = False
        self._tick_volume  = 1.0
        self._win_volume   = 1.0
        self._tick_pattern = 0
        self._win_pattern  = 0
        self._tick_snds    = []   # None 要素 = 消音
        self._win_snds     = []
        self._tick_custom_snd  = None
        self._win_custom_snd   = None
        self._tick_custom_path = ""
        self._win_custom_path  = ""

        if not SOUND_AVAILABLE:
            return
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._tick_snds = [
                self._build_tick_snap(),
                self._build_tick_click(),
                self._build_tick_drum(),
                self._build_tick_coin(),
                self._build_tick_soft(),
                None,               # 消音
            ]
            self._win_snds = [
                self._build_bell(),
                self._build_fanfare(),
                self._build_casino(),
                self._build_chime(),
                self._build_victory(),
                None,               # 消音
            ]
        except Exception:
            pass

    # ── ユーティリティ ───────────────────────────────────────────────
    @staticmethod
    def _make_stereo(mono: "np.ndarray") -> "pygame.Sound":
        s = np.clip(mono, -32767, 32767).astype(np.int16)
        return pygame.sndarray.make_sound(np.ascontiguousarray(np.column_stack([s, s])))

    # ── スピン中ティック音 ─────────────────────────────────────────
    @staticmethod
    def _build_tick_click() -> "pygame.Sound":
        """クリック: 標準的なクリック音"""
        sr, dur = 44100, 0.035
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        wave = np.sin(2 * np.pi * 650 * t) * np.exp(-t * 120) * 18000
        return SoundManager._make_stereo(wave)

    @staticmethod
    def _build_tick_snap() -> "pygame.Sound":
        """スナップ: piliapp風 — フラッパーが仕切りを弾く短い乾いた音"""
        sr, dur = 44100, 0.022
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        rng = np.random.default_rng(0)
        noise = rng.uniform(-1.0, 1.0, len(t))
        snap  = (np.sin(2 * np.pi * 900 * t) * 0.7
                 + np.sin(2 * np.pi * 1800 * t) * 0.2
                 + noise * 0.15)
        wave  = snap * np.exp(-t * 280) * 22000
        return SoundManager._make_stereo(wave)

    @staticmethod
    def _build_tick_drum() -> "pygame.Sound":
        """ドラム: 低音パーカッション"""
        sr, dur = 44100, 0.055
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        # 周波数が時間と共に急降下するドラム風
        freq = 180 * np.exp(-t * 40)
        wave = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 60) * 22000
        return SoundManager._make_stereo(wave)

    @staticmethod
    def _build_tick_coin() -> "pygame.Sound":
        """コイン: 金属的な高音"""
        sr, dur = 44100, 0.04
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        wave = (
            np.sin(2 * np.pi * 1400 * t) * 1.0
            + np.sin(2 * np.pi * 2100 * t) * 0.4
        ) * np.exp(-t * 100) * 16000
        return SoundManager._make_stereo(wave)

    @staticmethod
    def _build_tick_soft() -> "pygame.Sound":
        """ソフト: 柔らかくこもった音"""
        sr, dur = 44100, 0.04
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        wave = np.sin(2 * np.pi * 320 * t) * np.exp(-t * 150) * 10000
        return SoundManager._make_stereo(wave)

    # ── 決定音 ────────────────────────────────────────────────────
    @staticmethod
    def _build_fanfare() -> "pygame.Sound":
        """ファンファーレ: 上昇アルペジオ"""
        sr = 44100
        notes = [
            (523.25, 0.13, 6.0),
            (659.25, 0.13, 6.0),
            (783.99, 0.13, 6.0),
            (1046.50, 0.13, 6.0),
            (1046.50, 0.30, 2.5),
        ]
        parts = []
        for freq, dur, decay in notes:
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False)
            parts.append(np.sin(2 * np.pi * freq * t) * np.exp(-t * decay))
        return SoundManager._make_stereo(np.concatenate(parts) * 26000)

    @staticmethod
    def _build_bell() -> "pygame.Sound":
        """ベル: 倍音付き単音クリアベル"""
        sr, dur = 44100, 1.2
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        freq = 880.0
        wave = (
            np.sin(2 * np.pi * freq * t) * 1.0
            + np.sin(2 * np.pi * freq * 2.756 * t) * 0.5
            + np.sin(2 * np.pi * freq * 5.404 * t) * 0.25
        ) * np.exp(-t * 2.8) * 11000
        return SoundManager._make_stereo(wave)

    @staticmethod
    def _build_casino() -> "pygame.Sound":
        """カジノ: 高速上昇ブリップ → 和音"""
        sr = 44100
        parts = []
        for freq in [300, 400, 500, 600, 750, 900]:
            dur = 0.045
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False)
            parts.append(np.sin(2 * np.pi * freq * t) * np.exp(-t * 30) * 22000)
        dur_chord = 0.5
        n = int(sr * dur_chord)
        t = np.linspace(0, dur_chord, n, endpoint=False)
        chord = (
            np.sin(2 * np.pi * 1046.50 * t)
            + np.sin(2 * np.pi * 1318.51 * t)
            + np.sin(2 * np.pi * 1567.98 * t)
        ) * np.exp(-t * 3.0) * 12000
        parts.append(chord)
        return SoundManager._make_stereo(np.concatenate(parts))

    @staticmethod
    def _build_chime() -> "pygame.Sound":
        """チャイム: 4音ドアチャイム風"""
        sr = 44100
        melody = [659.25, 783.99, 739.99, 523.25]
        parts = []
        for freq in melody:
            n = int(sr * 0.28)
            t = np.linspace(0, 0.28, n, endpoint=False)
            parts.append(np.sin(2 * np.pi * freq * t) * np.exp(-t * 4.0) * 24000)
        return SoundManager._make_stereo(np.concatenate(parts))

    @staticmethod
    def _build_victory() -> "pygame.Sound":
        """ビクトリー: 短いジングル"""
        sr = 44100
        notes = [
            (523.25, 0.10, 8.0),
            (659.25, 0.10, 8.0),
            (783.99, 0.10, 8.0),
            (523.25, 0.10, 8.0),
            (659.25, 0.10, 8.0),
            (783.99, 0.10, 8.0),
            (1046.50, 0.45, 2.0),
        ]
        parts = []
        for freq, dur, decay in notes:
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False)
            parts.append(np.sin(2 * np.pi * freq * t) * np.exp(-t * decay))
        return SoundManager._make_stereo(np.concatenate(parts) * 24000)

    # ── 再生 ──────────────────────────────────────────────────────
    def play_tick(self, pattern: int | None = None):
        """スピン中ティック音を再生する。

        i370: pattern を指定した場合はそのインデックスで鳴らす（per-roulette パターン対応）。
        None の場合は self._tick_pattern を使う（後方互換）。
        """
        if self.muted:
            return
        p = pattern if pattern is not None else self._tick_pattern
        p = max(0, min(p, len(TICK_PATTERN_NAMES) - 1))
        if p == len(TICK_PATTERN_NAMES) - 1:
            if self._tick_custom_snd:
                self._tick_custom_snd.play()
            return
        snd = self._tick_snds[p] if self._tick_snds else None
        if snd:
            snd.play()

    def play_win(self, pattern: int | None = None):
        """決定音を再生する。

        i370: pattern を指定した場合はそのインデックスで鳴らす（per-roulette パターン対応）。
        None の場合は self._win_pattern を使う（後方互換）。
        """
        if self.muted:
            return
        p = pattern if pattern is not None else self._win_pattern
        p = max(0, min(p, len(WIN_PATTERN_NAMES) - 1))
        if p == len(WIN_PATTERN_NAMES) - 1:
            if self._win_custom_snd:
                self._win_custom_snd.play()
            return
        if not self._win_snds:
            return
        snd = self._win_snds[p]
        if snd:
            snd.play()

    def preview_tick(self, idx: int):
        """試聴用（ミュート無視）"""
        if idx == len(TICK_PATTERN_NAMES) - 1:
            if self._tick_custom_snd:
                self._tick_custom_snd.set_volume(self._tick_volume)
                self._tick_custom_snd.play()
            return
        if self._tick_snds:
            snd = self._tick_snds[max(0, min(idx, len(self._tick_snds) - 1))]
            if snd:
                snd.set_volume(self._tick_volume)
                snd.play()

    def preview_win(self, idx: int):
        """試聴用（ミュート無視）"""
        if idx == len(WIN_PATTERN_NAMES) - 1:
            if self._win_custom_snd:
                self._win_custom_snd.set_volume(self._win_volume)
                self._win_custom_snd.play()
            return
        if self._win_snds:
            snd = self._win_snds[max(0, min(idx, len(self._win_snds) - 1))]
            if snd:
                snd.set_volume(self._win_volume)
                snd.play()

    def set_tick_pattern(self, idx: int):
        self._tick_pattern = max(0, min(idx, len(TICK_PATTERN_NAMES) - 1))

    def set_win_pattern(self, idx: int):
        self._win_pattern = max(0, min(idx, len(WIN_PATTERN_NAMES) - 1))

    def set_tick_volume(self, vol: float):
        self._tick_volume = vol
        for snd in self._tick_snds:
            if snd:
                snd.set_volume(vol)
        if self._tick_custom_snd:
            self._tick_custom_snd.set_volume(vol)

    def set_win_volume(self, vol: float):
        self._win_volume = vol
        for snd in self._win_snds:
            if snd:
                snd.set_volume(vol)
        if self._win_custom_snd:
            self._win_custom_snd.set_volume(vol)

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def load_tick_custom(self, path: str):
        """カスタムスピン音ファイルを読み込む。"""
        self._tick_custom_path = path
        self._tick_custom_snd = None
        if not path or not SOUND_AVAILABLE:
            return
        try:
            snd = pygame.mixer.Sound(path)
            snd.set_volume(self._tick_volume)
            self._tick_custom_snd = snd
        except Exception:
            pass

    def load_win_custom(self, path: str):
        """カスタム決定音ファイルを読み込む。"""
        self._win_custom_path = path
        self._win_custom_snd = None
        if not path or not SOUND_AVAILABLE:
            return
        try:
            snd = pygame.mixer.Sound(path)
            snd.set_volume(self._win_volume)
            self._win_custom_snd = snd
        except Exception:
            pass
