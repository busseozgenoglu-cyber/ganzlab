"""Sahte arka uç — model yüklemeden konuşma BENZERİ sinyal üretir (testler, kıyaslama betiğinin kuru çalışması,
arayüz geliştirme). Gerçek konuşma değildir; ama ölçüm zincirinin (F0 aralığı, hece/sn, QC) anlamlı sayılar
görmesi için şu özellikleri taklit eder:

* ``exaggeration`` tonlama aralığını açar: 0 → ~3 yarım ton, 0.5 → ~9, 1.0 → ~15 (p5–p95). Böylece kıyaslama
  betiğinin ayar farklarını raporlayabildiği testle doğrulanır.
* ``temperature`` perde titremesini (jitter) artırır.
* ``audio_prompt_path`` verilirse temel perde dosya adından türetilir (aynı referans → aynı "ses").
* Süre ≈ 0,07 sn/karakter; heceler düzensiz uzunlukta (QC "tekrar" dedektörü düzenli zarfı haklı olarak yakalar).
"""
from __future__ import annotations

import hashlib

import numpy as np

from . import BaseBackend


def speechlike(n_chars: int, sr: int = 24000, *, seed: int = 0, f0_base: float = 150.0, range_st: float = 9.0,
               jitter: float = 0.5) -> np.ndarray:
    """Konuşma benzeri sentetik sinyal (harmonik kaynak × düzensiz hece zarfı + hafif gürültü)."""
    rng = np.random.default_rng(seed)
    dur = max(0.4, n_chars * 0.07)
    n = int(sr * dur)
    t = np.arange(n) / sr
    # perde: yavaş bir tonlama dalgası (aralık yarım ton cinsinden) + rastgele yürüyüş (titreme)
    half = range_st / 2.0
    contour_st = half * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 2 * np.pi)) \
        + 0.3 * half * np.sin(2 * np.pi * 2.3 * t)
    walk = rng.standard_normal(n).cumsum()
    walk -= np.linspace(walk[0], walk[-1], n)        # yürüyüş sürüklenmesin
    walk *= jitter / (float(np.std(walk)) + 1e-9)    # titreme: ``jitter`` yarım ton standart sapma
    f0 = f0_base * 2 ** ((contour_st + walk) / 12.0)
    phase = 2 * np.pi * np.cumsum(f0) / sr
    sig = sum((0.5 / k) * np.sin(k * phase) for k in range(1, 6))
    env = np.zeros(n)
    pos = 0
    while pos < n:
        syl = int(sr * rng.uniform(0.12, 0.28))
        gap = int(sr * rng.uniform(0.0, 0.05))
        amp = rng.uniform(0.5, 1.0)
        seg = np.hanning(max(8, syl)) ** 0.7 * amp
        end = min(n, pos + len(seg))
        env[pos:end] = seg[: end - pos]
        pos += syl + gap
    env = 0.15 + 0.85 * env
    sig = sig * env * 0.25 + rng.standard_normal(n) * 0.002
    return sig.astype(np.float32)


class FakeBackend(BaseBackend):
    name = "fake"
    label = "Sahte (test) arka ucu"
    license = "—"
    model_id = "sahte-sinyal"
    sr = 24000
    commercial = True
    supports_emotion_controls = True
    needs_torch = False
    required_modules = ()
    install_hint = ""

    def __init__(self, device: str = "cpu", sr: int = 24000) -> None:
        super().__init__(device)
        self.sr = int(sr)
        self.calls: list[dict] = []
        self._seed = 0

    def seed(self, seed: int) -> None:
        self._seed = int(seed)

    def generate(self, text: str, language_id: str = "tr", exaggeration: float = 0.5, cfg_weight: float = 0.5,
                 temperature: float = 0.8, audio_prompt_path: str | None = None) -> np.ndarray:
        self.calls.append({"text": text, "language_id": language_id, "exaggeration": exaggeration,
                           "cfg_weight": cfg_weight, "temperature": temperature, "ref": audio_prompt_path})
        f0_base = 150.0
        if audio_prompt_path:
            h = int(hashlib.sha1(str(audio_prompt_path).encode("utf-8")).hexdigest()[:6], 16)
            f0_base = 110.0 + (h % 120)                       # 110–230 Hz: referansa göre sabit "ses"
        ex = float(np.clip(exaggeration, 0.0, 1.5))
        range_st = 3.0 + 12.0 * ex                            # 0 → 3, 0.5 → 9, 1.0 → 15 yarım ton
        jitter = 0.2 + 0.5 * float(np.clip(temperature, 0.0, 1.5))     # yarım ton cinsinden perde titremesi
        seed = (self._seed * 7919 + len(self.calls) * 104729 + len(text)) % (2 ** 32)
        return speechlike(len(text), self.sr, seed=seed, f0_base=f0_base, range_st=range_st, jitter=jitter)
