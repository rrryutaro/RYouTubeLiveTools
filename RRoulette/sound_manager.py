# ─── サウンド用ライブラリ（オプション）────────────────────────────────
try:
    import numpy as np
    import pygame
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

TICK_PATTERN_NAMES = ["スナップ", "クリック", "ドラム", "コイン", "ソフト", "消音", "カスタム"]
WIN_PATTERN_NAMES  = ["ベル", "ファンファーレ", "カジノ", "チャイム", "ビクトリー", "消音", "カスタム"]

# 特殊演出音 — confirm (target確定), expect (期待度), ng (avoid確定)。各 5 バリエーション
EFFECT_SOUND_KEYS = ("confirm", "expect", "ng")


# ════════════════════════════════════════════════════════════════════
#  SoundManager — プログラムで音を生成（外部ファイル不要）
# ════════════════════════════════════════════════════════════════════
class SoundManager:
    """numpy + pygame で効果音をゼロから生成。外部音声ファイル不使用のためライセンスフリー。"""

    def __init__(self):
        self.muted         = False
        self._tick_volume  = 0.5  # 既定 50%
        self._win_volume   = 0.5  # 既定 50%
        self._effect_volume = 0.5  # 既定 50%
        self._tick_pattern = 0
        self._win_pattern  = 0
        self._tick_snds    = []   # None 要素 = 消音
        self._win_snds     = []
        self._tick_custom_snd  = None
        self._win_custom_snd   = None
        self._tick_custom_path = ""
        self._win_custom_path  = ""

        # 特殊演出音: confirm × 5, expect × 5, ng × 5
        self._effect_snds: dict[str, list] = {"confirm": [], "expect": [], "ng": []}

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
            # 演出音: PWA と同じ wav ファイルを優先ロード、無ければ生成音にフォールバック
            self._effect_snds = self._load_effect_sounds()
        except Exception:
            pass

    def _load_effect_sounds(self) -> dict:
        """sounds/ から PWA と同じ effect_*.wav を読み込む。失敗時は生成音を返す。"""
        import os, sys
        # 実行時パス: PyInstaller bundle / 通常実行 両対応
        base_dirs = []
        if hasattr(sys, "_MEIPASS"):
            base_dirs.append(os.path.join(sys._MEIPASS, "sounds"))
        # constants.py と同じディレクトリの sounds/
        try:
            base_dirs.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds"))
        except Exception:
            pass

        def _try_load(filename: str):
            for base in base_dirs:
                path = os.path.join(base, filename)
                if os.path.isfile(path):
                    try:
                        return pygame.mixer.Sound(path)
                    except Exception:
                        continue
            return None

        result = {}
        for snd_key, prefix in (("confirm", "effect_confirm"),
                                ("expect", "effect_expect"),
                                ("ng", "effect_ng")):
            wav_snds = []
            all_loaded = True
            for i in range(1, 6):
                snd = _try_load(f"{prefix}_{i}.wav")
                if snd is None:
                    all_loaded = False
                    break
                wav_snds.append(snd)
            if all_loaded:
                result[snd_key] = wav_snds
            else:
                # フォールバック: 生成音
                if snd_key == "confirm":
                    result[snd_key] = [self._build_effect_confirm(i) for i in range(1, 6)]
                elif snd_key == "expect":
                    result[snd_key] = [self._build_effect_expect(i) for i in range(1, 6)]
                else:
                    result[snd_key] = [self._build_effect_ng(i) for i in range(1, 6)]
        return result

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

    # ── 特殊演出音 ────────────────────────────────────────────────

    @staticmethod
    def _build_effect_confirm(variant: int) -> "pygame.Sound":
        """target 確定音 — ファンファーレ系 (variant 1〜5)。"""
        sr = 44100
        # 各 variant でアルペジオのパターンを変える
        patterns = {
            1: [(523.25, 0.10), (659.25, 0.10), (783.99, 0.10), (1046.50, 0.35)],  # ド ミ ソ ド
            2: [(587.33, 0.09), (739.99, 0.09), (880.00, 0.09), (1174.66, 0.30)],  # レ ファ# ラ レ
            3: [(659.25, 0.08), (830.61, 0.08), (987.77, 0.08), (1318.51, 0.28)],  # ミ ソ# シ ミ
            4: [(523.25, 0.07), (659.25, 0.07), (784.00, 0.07), (1046.50, 0.07), (1318.51, 0.28)],
            5: [(440.00, 0.10), (587.33, 0.10), (880.00, 0.10), (1174.66, 0.35)],  # ラ レ ラ レ
        }
        notes = patterns.get(variant, patterns[1])
        parts = []
        for freq, dur in notes:
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False)
            wave = (
                np.sin(2 * np.pi * freq * t) * 1.0
                + np.sin(2 * np.pi * freq * 2 * t) * 0.3
            ) * np.exp(-t * 3.5)
            parts.append(wave)
        return SoundManager._make_stereo(np.concatenate(parts) * 24000)

    @staticmethod
    def _build_effect_expect(variant: int) -> "pygame.Sound":
        """期待度音 — パチンコ風キュイン系 (variant 1〜5)。"""
        sr = 44100
        dur = 0.45
        n = int(sr * dur)
        t = np.linspace(0, dur, n, endpoint=False)
        # variant ごとに開始/終了周波数と倍率を変える
        starts = [300, 350, 250, 400, 280]
        ends   = [900, 1100, 800, 1300, 950]
        f0 = starts[(variant - 1) % 5]
        f1 = ends[(variant - 1) % 5]
        # 対数スイープ
        freq = f0 * np.exp(np.log(f1 / f0) * t / dur)
        phase = 2 * np.pi * np.cumsum(freq) / sr
        wave = np.sin(phase) * np.exp(-t * 1.5) * 20000
        return SoundManager._make_stereo(wave)

    @staticmethod
    def _build_effect_ng(variant: int) -> "pygame.Sound":
        """NG確定音 — 下降/不協和音系 (variant 1〜5)。"""
        sr = 44100
        # 下降アルペジオ + 少し不協和
        patterns = {
            1: [(523.25, 0.12), (415.30, 0.12), (329.63, 0.12), (261.63, 0.30)],  # ド ラb ミ ド
            2: [(466.16, 0.11), (369.99, 0.11), (293.66, 0.11), (233.08, 0.28)],
            3: [(440.00, 0.10), (415.30, 0.10), (392.00, 0.10), (349.23, 0.30)],  # クロマ下降
            4: [(523.25, 0.09), (466.16, 0.09), (415.30, 0.09), (311.13, 0.09), (261.63, 0.28)],
            5: [(392.00, 0.12), (369.99, 0.12), (329.63, 0.12), (261.63, 0.28)],  # ソ ファ# ミ ド
        }
        notes = patterns.get(variant, patterns[1])
        parts = []
        for i, (freq, dur) in enumerate(notes):
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False)
            # 下降する音は少し暗め（奇数倍音強め）
            wave = (
                np.sin(2 * np.pi * freq * t) * 1.0
                + np.sin(2 * np.pi * freq * 3 * t) * 0.2
                + np.sin(2 * np.pi * freq * 5 * t) * 0.1
            ) * np.exp(-t * 4.0)
            parts.append(wave)
        return SoundManager._make_stereo(np.concatenate(parts) * 20000)

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

    # v0.6.1: 演出 SE の素材音量が他 SE より大きいため、ユーザー設定値に
    # 0.5 を掛けて baseline 50% として扱う（設定 100% で実音量 0.5）。
    _EFFECT_GAIN_SCALE = 0.5

    def play_effect(self, key: str, variant: int = 0) -> None:
        """特殊演出音を再生する。

        Args:
            key: "confirm" / "expect" / "ng"
            variant: 1〜5 (0 or out-of-range でランダム抽選)
        """
        if self.muted:
            return
        snds = self._effect_snds.get(key, [])
        if not snds:
            return
        if 1 <= variant <= len(snds):
            idx = variant - 1
        else:
            import random
            idx = random.randint(0, len(snds) - 1)
        snd = snds[idx]
        if snd:
            snd.set_volume(self._effect_volume * self._EFFECT_GAIN_SCALE)
            snd.play()

    def preview_effect(self, key: str, variant: int = 0) -> None:
        """特殊演出音の試聴（ミュート無視）。"""
        snds = self._effect_snds.get(key, [])
        if not snds:
            return
        if 1 <= variant <= len(snds):
            idx = variant - 1
        else:
            import random
            idx = random.randint(0, len(snds) - 1)
        snd = snds[idx]
        if snd:
            snd.set_volume(self._effect_volume * self._EFFECT_GAIN_SCALE)
            snd.play()

    def set_effect_volume(self, vol: float):
        """演出音量 (0.0〜1.0) を設定する。"""
        self._effect_volume = max(0.0, min(1.0, vol))

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
