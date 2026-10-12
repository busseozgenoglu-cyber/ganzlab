"""Chatterbox Multilingual (Resemble AI, MIT) üzerine sesklon üretim motoru.

Doğallık ve duygu için:
- Metin normalizasyonu (sayı, tarih, kısaltma, marka okunuşu) + Türkçe konuşma dili katmanı.
- [etiket] tabanlı duygu bölümleri; cümle noktalamasına ve isteğe bağlı içerik çıkarımına göre duygu.
- Her bölüm için duyguya uygun referans: kullanıcının o duygu için kaydı → nötr kayıttan türetilmiş → nötr.
- Duyguya göre üretim parametreleri, çıktı işleme (perde/kazanç/nefes/sıkıştırma), tempo ve duraklama.
- Parça kenarlarında sessizlik kırpma, yumuşatma, seviye dengeleme; halüsinasyon koruması.
- Model ilk istekte (veya PRELOAD ile arka planda) yüklenir; tek GPU için üretimler kilitle sıraya alınır.
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, config
from .colloquial import colloquial_tr
from .emotion import PROFILES, EmotionProfile, derive_reference, infer_emotion, parse_tagged_text, post_process
from .textnorm import normalize

log = logging.getLogger("sesklon.engine")

_SENT_END = re.compile(r"(?<=[.!?]['\"»”’)])\s+|(?<=[.!?])\s+")
PAUSE_MS = {"paragraph": 650, ".": 380, "!": 420, "?": 450, "...": 550, ";": 300, ":": 280, ",": 180, "": 250}

ProgressFn = Callable[[int, int, str], None]


@dataclass
class Chunk:
    text: str
    pause_after_ms: int
    emotion: str | None = None
    pause_before_ms: int = 0
    punct: str = ""      # cümle sonu noktalaması: "!", "?", "...", ""


def _punct_of(s: str) -> str:
    s = s.rstrip().rstrip("'\"»”’)")
    if s.endswith("..."):
        return "..."
    if s.endswith("!"):
        return "!"
    if s.endswith("?"):
        return "?"
    return ""


def _end_pause(s: str, paragraph_end: bool) -> int:
    if paragraph_end:
        return PAUSE_MS["paragraph"]
    p = _punct_of(s)
    if p:
        return PAUSE_MS[p]
    return PAUSE_MS.get(s.rstrip()[-1:] if s.strip() else "", PAUSE_MS[""])


def split_text(text: str, max_chars: int, normalizer=None, auto_emotion: bool = False) -> list[Chunk]:
    """Etiket bölümlerini ayırır (ham metinde), her bölümü normalize edip cümlelere böler."""
    chunks: list[Chunk] = []
    for seg in parse_tagged_text(text):
        seg_text = normalizer(seg.text) if normalizer else seg.text
        seg_chunks = _split_segment(seg_text, max_chars, seg.emotion, auto_emotion)
        if not seg_chunks:
            continue
        seg_chunks[0].pause_before_ms += seg.pause_before_ms
        seg_chunks[-1].pause_after_ms += seg.pause_after_ms
        chunks.extend(seg_chunks)
    return chunks


def _split_segment(text: str, max_chars: int, emotion: str | None, auto_emotion: bool) -> list[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[Chunk] = []

    def make(cur: str, paragraph_end: bool) -> Chunk:
        emo = emotion
        if emo is None and auto_emotion:
            emo = infer_emotion(cur)
        return Chunk(cur, _end_pause(cur, paragraph_end), emo, 0, _punct_of(cur))

    for pi, para in enumerate(paragraphs):
        para = re.sub(r"\s+", " ", para)
        sentences = [s.strip() for s in _SENT_END.split(para) if s and s.strip()]
        units: list[str] = []
        for s in sentences:
            if len(s) <= max_chars:
                units.append(s)
                continue
            parts = [p.strip() for p in re.split(r"(?<=[,;:])\s+", s) if p.strip()]
            cur = ""
            for p in parts:
                if len(cur) + len(p) + 1 <= max_chars:
                    cur = f"{cur} {p}".strip()
                else:
                    if cur:
                        units.append(cur)
                    cur = p
            if cur:
                units.append(cur)
        cur = ""
        for u in units:
            kind_changes = bool(cur) and _punct_of(cur) != _punct_of(u) and (_punct_of(cur) in ("!", "?") or _punct_of(u) in ("!", "?"))
            if cur and (len(cur) + len(u) + 1 > max_chars or (kind_changes and len(cur) >= 40 and len(u) >= 30)):
                chunks.append(make(cur, False))
                cur = u
            else:
                cur = f"{cur} {u}".strip()
        if cur:
            chunks.append(make(cur, pi < len(paragraphs) - 1))
    return chunks


def pick_device() -> str:
    if config.DEVICE:
        return config.DEVICE
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def _patch_torch_load_for(device: str) -> None:
    """Apple Silicon (mps) ve CPU'da CUDA'ya kaydedilmiş ağırlıkları doğru cihaza eşler."""
    import torch

    if device == "cuda":
        return
    original = torch.load

    def patched(*args, **kwargs):
        kwargs.setdefault("map_location", torch.device(device))
        return original(*args, **kwargs)

    torch.load = patched  # type: ignore[assignment]


def _filter_kwargs(fn, kwargs: dict) -> dict:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


MIN_CHARS_PER_SEC = 6.0
MAX_CHARS_PER_SEC = 28.0

# Noktalamanın duygu üstüne eklediği farklar
PUNCT_DELTA = {
    "!": {"exaggeration": +0.2, "cfg_weight": -0.08, "speed": 1.02},
    "?": {"exaggeration": +0.12, "cfg_weight": -0.05, "speed": 1.0},
    "...": {"exaggeration": -0.1, "cfg_weight": 0.0, "speed": 0.94},
    "": {"exaggeration": 0.0, "cfg_weight": 0.0, "speed": 1.0},
}


@dataclass
class VoiceRefs:
    """Bir sesin referans dosyaları: nötr + duygu başına kayıtlar."""
    voice_id: str
    base: Path | None
    by_emotion: dict[str, Path]


class Engine:
    def __init__(self) -> None:
        self.device = pick_device()
        self._tts = None
        self._vc = None
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self.loading = False
        self.load_error: str | None = None
        self.model_name = f"chatterbox-multilingual-{config.T3_MODEL}"
        _patch_torch_load_for(self.device)
        log.info("SesKlon motoru hazır • cihaz=%s • model=%s", self.device, self.model_name)

    # ---------- durum / yükleme ----------
    @property
    def loaded(self) -> bool:
        return self._tts is not None

    def tts(self):
        if self._tts is None:
            with self._load_lock:
                if self._tts is None:
                    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

                    self.loading = True
                    t0 = time.time()
                    log.info("Chatterbox Multilingual yükleniyor (%s)…", self.device)
                    try:
                        kwargs = _filter_kwargs(
                            ChatterboxMultilingualTTS.from_pretrained,
                            {"device": self.device, "t3_model": config.T3_MODEL},
                        )
                        self._tts = ChatterboxMultilingualTTS.from_pretrained(**kwargs)
                        self.load_error = None
                        log.info("Model yüklendi (%.1f sn)", time.time() - t0)
                    except Exception as e:  # noqa: BLE001
                        self.load_error = str(e)
                        raise
                    finally:
                        self.loading = False
        return self._tts

    def vc(self):
        if self._vc is None:
            with self._load_lock:
                if self._vc is None:
                    from chatterbox.vc import ChatterboxVC

                    log.info("Chatterbox VC yükleniyor (%s)…", self.device)
                    self._vc = ChatterboxVC.from_pretrained(device=self.device)
        return self._vc

    def preload(self) -> None:
        self.tts()

    def preload_background(self) -> None:
        def _run():
            try:
                self.preload()
            except Exception:  # noqa: BLE001
                log.exception("Model arka planda yüklenemedi")

        threading.Thread(target=_run, name="sesklon-preload", daemon=True).start()

    # ---------- referans seçimi ----------
    @staticmethod
    def _derived_path(base: Path, profile: EmotionProfile) -> Path:
        key = hashlib.md5(f"{base.name}|{profile.name}|{profile.ref_pitch}|{profile.ref_tempo}|{profile.ref_gain_db}|{profile.ref_breathy}".encode()).hexdigest()[:10]
        return base.parent / "derived" / f"{base.stem}_{profile.name}_{key}.wav"

    def reference_for(self, refs: VoiceRefs | None, emotion: str | None, derive: bool = True) -> tuple[Path | None, str]:
        """Döndürür: (referans yolu, kaynak: 'kayıt' | 'türetilmiş' | 'nötr' | 'model')."""
        if refs is None or refs.base is None and not refs.by_emotion:
            return None, "model"
        if emotion and emotion in refs.by_emotion and refs.by_emotion[emotion].exists():
            return refs.by_emotion[emotion], "kayıt"
        base = refs.base or next(iter(refs.by_emotion.values()))
        profile = PROFILES.get(emotion or "")
        has_transform = profile and (abs(profile.ref_pitch) > 0.01 or abs(profile.ref_tempo - 1) > 0.005
                                     or abs(profile.ref_gain_db) > 0.1 or profile.ref_breathy)
        if derive and has_transform:
            out = self._derived_path(base, profile)
            if not out.exists():
                try:
                    derive_reference(base, out, profile, audio.TARGET_SR)
                except Exception as e:  # noqa: BLE001
                    log.warning("Duygu referansı türetilemedi (%s): %s", profile.name, e)
                    return base, "nötr"
            return out, "türetilmiş"
        return base, "nötr"

    # ---------- üretim ----------
    def synthesize(
        self,
        text: str,
        language: str = "tr",
        refs: VoiceRefs | Path | str | None = None,
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
        temperature: float = 0.8,
        seed: int | None = None,
        speed: float = 1.0,
        colloquial: bool = True,
        punctuation_emotion: bool = True,
        auto_emotion: bool = False,
        emotion_refs: bool = False,
        progress: ProgressFn | None = None,
        emotion_fx: str = "off",
    ) -> tuple[np.ndarray, int, dict]:
        """Döndürür: (ses, örnekleme hızı, rapor {normalized_text, chunks:[...]})."""
        if isinstance(refs, (str, Path)):
            refs = VoiceRefs("adhoc", Path(refs), {})

        def _norm(seg: str) -> str:
            out = normalize(seg, language)
            if colloquial and language == "tr":
                out = colloquial_tr(out)
            return out

        chunks = split_text(text, config.CHUNK_CHARS, normalizer=_norm, auto_emotion=auto_emotion)
        if not chunks:
            raise ValueError("Metin boş.")
        report: dict = {"normalized_text": " ".join(c.text for c in chunks), "chunks": []}

        with self._lock:
            model = self.tts()
            sr = int(model.sr)

            base_kwargs = _filter_kwargs(model.generate, {
                "language_id": language,
                "exaggeration": float(exaggeration),
                "cfg_weight": float(cfg_weight),
                "temperature": float(temperature),
            })

            pieces: list[np.ndarray] = []
            pauses: list[int] = []
            for i, ch in enumerate(chunks):
                if progress:
                    progress(i, len(chunks), ch.text[:60])
                if seed is not None:
                    self._seed(seed + i)
                profile = PROFILES.get(ch.emotion or "")
                kw, chunk_speed = self._chunk_settings(base_kwargs, profile, ch.punct if punctuation_emotion else "", len(ch.text), emotion_fx)
                ref_path, ref_src = self.reference_for(refs, ch.emotion, derive=emotion_refs and emotion_fx == "full")
                if ref_path is not None:
                    kw["audio_prompt_path"] = str(ref_path)
                kw = _filter_kwargs(model.generate, kw)
                log.info("Parça %d/%d (%d kar.) duygu=%s ref=%s ex=%.2f cfg=%.2f hız=%.2f",
                         i + 1, len(chunks), len(ch.text), ch.emotion or "-", ref_src,
                         kw.get("exaggeration", 0.5), kw.get("cfg_weight", 0.5), chunk_speed * speed)
                piece = self._generate_checked(model, ch.text, kw, sr)
                piece = post_process(piece, sr, profile, emotion_fx)
                piece = audio.change_speed(piece, sr, chunk_speed * speed)
                if ch.pause_before_ms and i > 0:
                    pauses[-1] += ch.pause_before_ms
                pieces.append(piece)
                pause = int(ch.pause_after_ms * (profile.pause_mul if profile else 1.0))
                pauses.append(pause)
                report["chunks"].append({"text": ch.text, "emotion": ch.emotion, "ref": ref_src,
                                         "exaggeration": round(kw.get("exaggeration", 0.5), 2),
                                         "cfg_weight": round(kw.get("cfg_weight", 0.5), 2),
                                         "speed": round(chunk_speed * speed, 2), "pause_ms": pause,
                                         "duration": round(len(piece) / sr, 2)})
            if progress:
                progress(len(chunks), len(chunks), "birleştiriliyor")
            wav = audio.join_with_pauses(pieces, pauses, sr)
            wav = audio.normalize_relative(wav, pieces, target_dbfs=-18.0, peak_dbfs=-1.0)
            return wav, sr, report

    @staticmethod
    def _chunk_settings(base: dict, profile: EmotionProfile | None, punct: str, text_len: int = 100, fx: str = "off") -> tuple[dict, float]:
        kw = dict(base)
        speed = 1.0
        if profile is not None:
            if profile.exaggeration is not None:
                kw["exaggeration"] = profile.exaggeration
            if profile.cfg_weight is not None:
                kw["cfg_weight"] = profile.cfg_weight
            if profile.temperature is not None:
                kw["temperature"] = profile.temperature
            # off modunda tempo yalnızca [hızlı]/[yavaş] etiketleriyle değişir (zaman germe yapaylık ekliyor)
            if fx != "off" or profile.name in ("hızlı", "yavaş"):
                speed = profile.speed
        d = PUNCT_DELTA.get(punct, PUNCT_DELTA[""])
        ex = float(kw.get("exaggeration", 0.5)) + d["exaggeration"]
        cfg = float(kw.get("cfg_weight", 0.5)) + d["cfg_weight"]
        if fx != "off":
            speed *= d["speed"]
        # Kararlılık sınırları: aşırı vurgu/çok düşük cfg kısa parçalarda bozulmaya yol açıyor
        if text_len < 25:
            ex, cfg = min(ex, 0.8), max(cfg, 0.4)
        kw["exaggeration"] = min(0.95, max(0.3, ex))
        kw["cfg_weight"] = min(0.7, max(0.3, cfg))
        speed = min(1.1, max(0.9, speed))
        return kw, speed

    def _generate_checked(self, model, text: str, gen_kwargs: dict, sr: int) -> np.ndarray:
        """Üretir; süre makul değilse (halüsinasyon / erken kesilme) daha düşük sıcaklıkla yeniden dener.
        Yine de uzun kalırsa beklenen azami süreden sonrasını sessiz bir noktada keser."""
        n = len(text)
        max_dur = n / MIN_CHARS_PER_SEC + 1.2          # "Hahaha!" (7) → 2.4 sn, 150 karakter → 26 sn
        min_dur = max(0.25, n / MAX_CHARS_PER_SEC)
        attempts = [gen_kwargs,
                    {**gen_kwargs, "temperature": min(float(gen_kwargs.get("temperature", 0.8)), 0.6),
                     "cfg_weight": max(float(gen_kwargs.get("cfg_weight", 0.5)), 0.4)}]
        best: tuple[float, np.ndarray] | None = None
        for k, kwargs in enumerate(attempts):
            wav = self._to_numpy(model.generate(text, **_filter_kwargs(model.generate, kwargs)))
            wav = audio.trim_silence(wav, sr, threshold_db=-45.0, pad_ms=40)
            dur = len(wav) / sr
            if min_dur <= dur <= max_dur:
                return wav
            log.warning("Parça süresi şüpheli (%.2f sn, beklenen %.1f–%.1f; deneme %d): %r", dur, min_dur, max_dur, k + 1, text[:40])
            score = (dur - max_dur) if dur > max_dur else (min_dur - dur) * 3
            if best is None or score < best[0]:
                best = (score, wav)
        wav = best[1]
        if len(wav) / sr > max_dur:
            wav = audio.cut_at_silence(wav, sr, max_dur)
        return wav

    def convert_voice(self, source_audio_path: str | Path, target_voice_path: str | Path) -> tuple[np.ndarray, int]:
        with self._lock:
            model = self.vc()
            wav = model.generate(str(source_audio_path), target_voice_path=str(target_voice_path))
            sr = int(model.sr)
            return audio.rms_normalize(self._to_numpy(wav), target_dbfs=-18.0), sr

    # ---------- yardımcılar ----------
    @staticmethod
    def _to_numpy(wav) -> np.ndarray:
        if hasattr(wav, "detach"):
            wav = wav.detach().cpu().float().numpy()
        return np.asarray(wav, dtype=np.float32).squeeze()

    def _seed(self, seed: int) -> None:
        import random

        import torch

        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        torch.manual_seed(seed)
        if self.device == "cuda":
            torch.cuda.manual_seed_all(seed)


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine
