#!/usr/bin/env python3
"""ビルド前実行スクリプト: 効果音WAVファイルを事前生成してsounds/フォルダに保存する。

PyInstallerビルド前に実行することで、起動時のnumpy計算コストをWAVロードに置き換える。
生成ファイル: tick_*.wav (x5), win_*.wav (x5), effect_*_*.wav (x15) = 計25ファイル
"""
import os
import sys
import wave

# sound_manager.py と同じディレクトリから実行することを想定
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

try:
    import numpy as np
    import pygame
except ImportError as e:
    print(f"ERROR: 必要なライブラリが見つかりません: {e}")
    print("pip install numpy pygame を実行してください。")
    sys.exit(1)

from sound_manager import SoundManager


def save_wav(path: str, sound: "pygame.Sound") -> None:
    samples = pygame.sndarray.samples(sound).copy()
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(samples.tobytes())
    print(f"  {os.path.basename(path)}")


def main() -> None:
    print("=" * 50)
    print(" RRoulette - Build Sounds (WAV pre-generation)")
    print("=" * 50)

    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

    sounds_dir = os.path.join(_HERE, "sounds")
    os.makedirs(sounds_dir, exist_ok=True)

    count = 0

    print("\n[Tick sounds]")
    tick_files = [
        ("tick_snap",  SoundManager._build_tick_snap),
        ("tick_click", SoundManager._build_tick_click),
        ("tick_drum",  SoundManager._build_tick_drum),
        ("tick_coin",  SoundManager._build_tick_coin),
        ("tick_soft",  SoundManager._build_tick_soft),
    ]
    for name, fn in tick_files:
        save_wav(os.path.join(sounds_dir, f"{name}.wav"), fn())
        count += 1

    print("\n[Win sounds]")
    win_files = [
        ("win_bell",    SoundManager._build_bell),
        ("win_fanfare", SoundManager._build_fanfare),
        ("win_casino",  SoundManager._build_casino),
        ("win_chime",   SoundManager._build_chime),
        ("win_victory", SoundManager._build_victory),
    ]
    for name, fn in win_files:
        save_wav(os.path.join(sounds_dir, f"{name}.wav"), fn())
        count += 1

    print("\n[Effect sounds]")
    for i in range(1, 6):
        save_wav(os.path.join(sounds_dir, f"effect_confirm_{i}.wav"), SoundManager._build_effect_confirm(i))
        save_wav(os.path.join(sounds_dir, f"effect_expect_{i}.wav"),  SoundManager._build_effect_expect(i))
        save_wav(os.path.join(sounds_dir, f"effect_ng_{i}.wav"),      SoundManager._build_effect_ng(i))
        count += 3

    pygame.mixer.quit()

    print(f"\n[Done] {count} WAV files -> {sounds_dir}")


if __name__ == "__main__":
    main()
