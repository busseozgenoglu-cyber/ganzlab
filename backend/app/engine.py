"""Chatterbox Multilingual (Resemble AI, MIT) üzerine SesKlon üretim motoru — v4.

İnsan gibi konuşan bir çıktı için katmanlar sırayla:
1. Metin: satır içi okunuş {yazılış|okunuş}, sohbet kısaltmaları, telaffuz sözlüğü, Türkçe normalizasyon,
   konuşma dili (off/light/full), isteğe bağlı konuşma dolguları.
2. Bölümleme: [etiket] duygu bölümleri (yoğunluk, karışım, kayış, hız/perde kontrolleri), sözsüz tepkiler,
   *vurgu*; noktalama ve isteğe bağlı içerik çıkarımına göre cümle duygusu.
3. Referans: her bölüm için duyguya uygun kayıt (kullanıcının o duygu için kaydı → türetilmiş → nötr).
4. Üretim: duyguya göre vurgu/cfg/sıcaklık; kalite kontrol (halüsinasyon, tekrar, takılma) → farklı tohumla
   yeniden üretim; gerçek tepki kayıtları ([gülme] → kullanıcının kendi gülmesi).
5. Tutarlılık: parçalar arası tını (LTAS) ve seviye eşitleme.
6. Prozodi: bağlama göre duraklama planı, kişinin ölçülen doğal ritmi, nefes, oda tonu.
7. Mastering: -16 LUFS, hafif EQ ve de-ess, gerçek tepe sınırı. Zaman çizelgesi (altyazı) üretilir.
Diyalog modu: "Ayşe: …" satırları konuşmacı başına sesle üretilir, sıra alma duraklamalarıyla birleştirilir.

Model ilk istekte (veya PRELOAD ile arka planda) yüklenir; tek GPU için üretimler kilitle sıraya alınır.
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import soundfile as sf

from . import audio, config, prosody
from .colloquial import colloquial_report, colloquial_tr, normalize_level
from .emotion import (PROFILES, EmotionProfile, derive_reference, effective_profile, infer_emotion,
                      interpolate_profile, nonverbal_fallback, parse_tagged_text, plan_emphasis, post_process)
from .textnorm import normalize

log = logging.getLogger("sesklon.engine")

_SENT_END = re.compile(r"(?<=[.!?]['\"»”’)])\s+|(?<=[.!?])\s+")
PAUSE_MS = {"paragraph": 650, ".": 380, "!": 420, "?": 450, "...": 550, ";": 300, ":": 280, ",": 180, "": 250}
MAX_TAG_PAUSE_MS = 10_000
EMPHASIS_PAUSE_BEFORE_MS = 110
EMPHASIS_PAUSE_AFTER_MS = 40
NONVERBAL_PAUSE_BEFORE_MS = 90
NONVERBAL_PAUSE_AFTER_MS = 140

ProgressFn = Callable[[int, int, str], None]
PartialFn = Callable[[int, np.ndarray, int, str], None]   # (indeks, ses, sr, metin)
CheckFn = Callable[[], None]                               # iptal denetimi (JobCancelled fırlatır)


@dataclass
class Chunk:
    text: str
    pause_after_ms: int      # noktalamadan gelen temel duraklama (planlayıcı ölçekler)
    emotion: str | None = None
    pause_before_ms: int = 0
    punct: str = ""          # cümle sonu noktalaması: "!", "?", "...", ""
    paragraph_end: bool = False
    emphasis: list[str] = field(default_factory=list)
    tag_pause_ms: int = 0    # [nefes] / [2 sn] gibi etiketlerden gelen, BİREBİR uygulanacak ek süre (bu parçadan sonra)
    # v4
    intensity: float = 1.0
    blend: list[str] = field(default_factory=list)
    rate: float | None = None          # [hız:0.9]
    pitch: float | None = None         # [perde:+1] yarım ton
    arc_t: float | None = None         # kayış konumu 0..1 (None = kayış yok)
    arc_to: str | None = None
    nonverbal: str | None = None       # "gülme" → gerçek tepki parçası (text boş)
    speaker: str | None = None
    emphasized: bool = False           # bu parça bir *vurgu* parçası
    turn_end: bool = False             # diyalogda sıra sonu: duraklaması sıra alma planından gelir, ezilmez


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


def split_text(text: str, max_chars: int, normalizer=None, auto_emotion: bool = False,
               keep_nonverbal: bool = False, emphasis: bool = True,
               recorded_nonverbal: set[str] | frozenset[str] | None = None) -> list[Chunk]:
    """Etiket bölümlerini ayırır (ham metinde), her bölümü normalize edip cümlelere böler.

    keep_nonverbal=True: [gülme] gibi tepkiler metne gömülmek yerine ayrı (sessiz metinli) parça olur; motor
    kullanıcının gerçek kaydı varsa onu, yoksa okunuş metnini ("Hahaha!") komşu parçaya gömer.
    emphasis=True: *vurgulu* sözcükler ayrı parçaya ayrılır (daha güçlü üretim + mikro duraklama).
    """
    chunks: list[Chunk] = []
    if keep_nonverbal and recorded_nonverbal is not None and not recorded_nonverbal:
        keep_nonverbal = False          # kayıt yoksa tepkiler v3'teki gibi satır içinde kalır (tek başına üretim halüsinasyon yapar)
    pending_fallback = ""               # kaydı olmayan tepkinin okunuşu → sonraki parçanın başına
    for seg in parse_tagged_text(text, keep_nonverbal=keep_nonverbal):
        if getattr(seg, "nonverbal", None) and recorded_nonverbal is not None and seg.nonverbal not in recorded_nonverbal:
            fb = getattr(seg, "nonverbal_reads", "") or nonverbal_fallback(seg.nonverbal) or ""
            if fb:
                pending_fallback = f"{pending_fallback} {fb}".strip()
            if seg.pause_before_ms or seg.pause_after_ms:
                (chunks[-1] if chunks else None) and setattr(chunks[-1], "tag_pause_ms", chunks[-1].tag_pause_ms + seg.pause_before_ms + seg.pause_after_ms)
            continue
        if getattr(seg, "nonverbal", None):
            nv = Chunk("", NONVERBAL_PAUSE_AFTER_MS, seg.emotion, NONVERBAL_PAUSE_BEFORE_MS, "", False,
                       nonverbal=seg.nonverbal, speaker=getattr(seg, "speaker", None),
                       intensity=float(getattr(seg, "intensity", 1.0) or 1.0))
            if seg.pause_before_ms:
                (chunks[-1] if chunks else nv).tag_pause_ms += seg.pause_before_ms
            nv.tag_pause_ms += seg.pause_after_ms
            chunks.append(nv)
            continue
        raw_text = seg.text
        if pending_fallback:
            raw_text = f"{pending_fallback} {raw_text}".strip()
            pending_fallback = ""
        seg_text = normalizer(raw_text) if normalizer else raw_text
        seg_chunks = _split_segment(seg_text, max_chars, seg.emotion, auto_emotion)
        if not seg_chunks:
            continue
        # Etiket duraklamaları ([nefes], [1.5 sn]…) birebir uygulanır; önceki parçanın sonuna eklenir
        # (metnin en başındaki duraklama v3'teki gibi yok sayılır).
        if seg.pause_before_ms and chunks:
            chunks[-1].tag_pause_ms += seg.pause_before_ms
        seg_chunks[-1].tag_pause_ms += seg.pause_after_ms
        n = len(seg_chunks)
        for i, c in enumerate(seg_chunks):
            c.intensity = float(getattr(seg, "intensity", 1.0) or 1.0)
            c.blend = list(getattr(seg, "blend", []) or [])
            c.rate = getattr(seg, "rate", None)
            c.pitch = getattr(seg, "pitch", None)
            c.speaker = getattr(seg, "speaker", None)
            if getattr(seg, "arc_to", None):
                c.arc_to = seg.arc_to
                c.arc_t = (i + 1) / n          # bölüm boyunca hedef duyguya kayış
        emphasis_words = list(getattr(seg, "emphasis_words", []) or []) if emphasis else []
        if emphasis_words and normalizer is not None:
            normed = []
            for w in emphasis_words:
                try:
                    nw = normalizer(w).strip().strip(".,!?;:")
                except Exception:  # noqa: BLE001
                    nw = w
                normed.append(nw or w)
            emphasis_words = normed
        if emphasis_words:
            seg_chunks = _apply_emphasis(seg_chunks, emphasis_words)
        chunks.extend(seg_chunks)
    if pending_fallback:
        if chunks and chunks[-1].text and not chunks[-1].nonverbal:
            chunks[-1].text = f"{chunks[-1].text} {pending_fallback}".strip()
            chunks[-1].punct = _punct_of(chunks[-1].text)
        else:
            chunks.append(Chunk(pending_fallback, PAUSE_MS["!"], None, 0, _punct_of(pending_fallback)))
    return chunks


def _apply_emphasis(chunks: list[Chunk], words: list[str]) -> list[Chunk]:
    """*vurgulu* sözcükleri kendi parçalarına ayırır; vurgulu parça öncesi/sonrası mikro duraklama."""
    out: list[Chunk] = []
    for c in chunks:
        parts = plan_emphasis(c.text, words)
        if len(parts) <= 1 and not (parts and parts[0][1]):
            out.append(c)
            continue
        for k, (txt, emph) in enumerate(parts):
            if not txt.strip():
                continue
            last = k == len(parts) - 1
            t_ = txt.strip()
            if last:
                pause = c.pause_after_ms
            elif t_.endswith((".", "!", "?", "...")):
                pause = _end_pause(t_, False)              # cümle sonu: gerçek cümle duraklaması
            elif t_.endswith((",", ";", ":")):
                pause = PAUSE_MS[t_[-1]]
            else:
                pause = EMPHASIS_PAUSE_AFTER_MS if emph else EMPHASIS_PAUSE_BEFORE_MS
            piece = Chunk(t_, pause, c.emotion, 0, _punct_of(txt), c.paragraph_end if last else False,
                          intensity=c.intensity, blend=list(c.blend), rate=c.rate, pitch=c.pitch, arc_t=c.arc_t,
                          arc_to=c.arc_to, speaker=c.speaker, emphasized=bool(emph))
            if last:
                piece.tag_pause_ms = c.tag_pause_ms
            out.append(piece)
    return out


def _split_segment(text: str, max_chars: int, emotion: str | None, auto_emotion: bool) -> list[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[Chunk] = []

    def make(cur: str, paragraph_end: bool) -> Chunk:
        emo = emotion
        if emo is None and auto_emotion:
            emo = infer_emotion(cur)
        return Chunk(cur, _end_pause(cur, paragraph_end), emo, 0, _punct_of(cur), paragraph_end)

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


# Duygu profillerinin tanımlandığı nötr ayarlar (SynthOptions varsayılanları): profil = nötr + fark
NEUTRAL_SETTINGS = {"exaggeration": 0.5, "cfg_weight": 0.45, "temperature": 0.8}

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
    """Bir sesin referans dosyaları: nötr + duygu başına kayıtlar + gerçek tepkiler + (varsa) analiz."""
    voice_id: str
    base: Path | None
    by_emotion: dict[str, Path]
    analysis: dict | None = None      # analysis.analyze_reference çıktısı (pauses.scale, breaths…)
    pause_scale: float | None = None  # kullanıcının sese elle verdiği ritim çarpanı (analizi ezer)
    nonverbal: dict[str, Path] = field(default_factory=dict)   # "gülme" → kayıt
    name: str = ""


@dataclass
class SynthOptions:
    """Üretim seçenekleri (API isteğinden gelir; stil ön ayarı üzerine yazılmış hali)."""
    language: str = "tr"
    exaggeration: float = 0.5
    cfg_weight: float = 0.45
    temperature: float = 0.8
    seed: int | None = None
    speed: float = 1.0
    colloquial: str = "light"            # off | light | full
    punctuation_emotion: bool = True
    auto_emotion: bool = False
    emotion_refs: bool = False
    emotion_fx: str = "off"
    breaths: bool = True
    room_tone: bool = True
    master: bool = True
    pause_scale: float = 1.0
    consistency: bool = True
    qc: bool = True
    fillers: bool = False
    chat_speak: bool = True
    subtitles: bool = True
    style: str | None = None


class Engine:
    def __init__(self, backend: str | None = None) -> None:
        from . import backends

        self.backend_name = backends.normalize_name(backend if backend is not None else config.TTS_BACKEND)
        self.device = pick_device() if self._backend_needs_torch() else (config.DEVICE or "cpu")
        self._tts = None
        self._vc = None
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self.loading = False
        self.load_error: str | None = None
        self.model_name = self._initial_model_name()
        self._ref_cache: dict[str, tuple[float, np.ndarray | None, np.ndarray | None]] = {}
        self._ltas_cache: dict[str, tuple[float, np.ndarray]] = {}
        self._cps_history: dict[str, list[tuple[int, float]]] = {}   # ses → (karakter, saniye) geçmişi (QC eşiği)
        self._default_conds = None
        if self._backend_needs_torch():
            _patch_torch_load_for(self.device)
        log.info("SesKlon motoru hazır • cihaz=%s • arka uç=%s • model=%s", self.device, self.backend_name,
                 self.model_name)

    def _backend_needs_torch(self) -> bool:
        from . import backends

        try:
            return bool(backends.get_class(self.backend_name).needs_torch)
        except Exception:  # noqa: BLE001 - bozuk arka uç modülü: yükleme sırasında raporlanır
            return True

    def _initial_model_name(self) -> str:
        if self.backend_name == "chatterbox":
            name = f"chatterbox-multilingual-{config.T3_MODEL}"
            return f"{name}+ince-ayar" if config.T3_FINETUNED else name
        return self.backend_name

    # ---------- durum / yükleme ----------
    @property
    def loaded(self) -> bool:
        return self._tts is not None

    def tts(self):
        """Sentez modelini (seçili arka ucu) tembel yükler; ``model.generate`` / ``model.sr`` arayüzü (bkz. app/backends)."""
        if self._tts is None:
            with self._load_lock:
                if self._tts is None:
                    from . import backends

                    self.loading = True
                    t0 = time.time()
                    log.info("Sentez arka ucu yükleniyor: %s (%s)…", self.backend_name, self.device)
                    try:
                        self._tts = backends.create(self.backend_name, device=self.device)
                        self.load_error = None
                        try:
                            self.model_name = self._tts.model_id or self.model_name
                        except Exception:  # noqa: BLE001
                            pass
                        # Varsayılan (klonsuz) ses koşulları: her klon üretimi model.conds'u ezer; referanssız
                        # üretimde bunları geri yükleyerek "varsayılan ses" hep aynı kalır.
                        try:
                            import copy

                            self._default_conds = copy.deepcopy(getattr(self._tts, "conds", None))
                        except Exception:  # noqa: BLE001
                            self._default_conds = None
                        log.info("Model yüklendi (%.1f sn): %s", time.time() - t0, self.model_name)
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

    def _room_and_breath(self, refs: VoiceRefs | None) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Referans kayıttan oda tonu ve gerçek nefes örneğini çıkarır (dosya değişmedikçe önbellekte)."""
        if refs is None or refs.base is None or not refs.base.exists():
            return None, None
        try:
            from .analysis import extract_breath, extract_noise_floor

            key = str(refs.base)
            mtime = refs.base.stat().st_mtime
            cached = self._ref_cache.get(key)
            if cached and cached[0] == mtime:
                return cached[1], cached[2]
            wav, sr = sf.read(str(refs.base), dtype="float32", always_2d=False)
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
            room = extract_noise_floor(wav, sr)
            breath = extract_breath(wav, sr)
            if room is not None and sr != audio.TARGET_SR:
                room = audio.resample(room, sr, audio.TARGET_SR)
            if breath is not None and sr != audio.TARGET_SR:
                breath = audio.resample(breath, sr, audio.TARGET_SR)
            self._ref_cache[key] = (mtime, room, breath)
            if len(self._ref_cache) > 64:
                self._ref_cache.pop(next(iter(self._ref_cache)))
            return room, breath
        except Exception as e:  # noqa: BLE001
            log.warning("Oda tonu / nefes çıkarılamadı: %s", e)
            return None, None

    def _voice_ltas(self, refs: VoiceRefs | None, sr: int) -> np.ndarray | None:
        """Referans sesin uzun dönem spektrumu (tutarlılık hedefi), önbellekli."""
        if refs is None or refs.base is None or not refs.base.exists():
            return None
        try:
            from .consistency import ltas

            key = str(refs.base)
            mtime = refs.base.stat().st_mtime
            cached = self._ltas_cache.get(key)
            if cached and cached[0] == mtime:
                return cached[1]
            wav, fsr = sf.read(str(refs.base), dtype="float32", always_2d=False)
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
            if fsr != sr:
                wav = audio.resample(wav, fsr, sr)
            target = ltas(wav, sr)
            self._ltas_cache[key] = (mtime, target)
            if len(self._ltas_cache) > 64:
                self._ltas_cache.pop(next(iter(self._ltas_cache)))
            return target
        except Exception as e:  # noqa: BLE001
            log.warning("Referans LTAS hesaplanamadı: %s", e)
            return None

    # ---------- metin ön işleme ----------
    @staticmethod
    def _make_normalizer(language: str, level: str, voice_id: str | None, chat_speak: bool, fillers: bool,
                         style: str | None, seed: int | None, changes: list[dict], lex_changes: list[dict]):
        """Bölüm metnini modele hazırlayan zincir: okunuş → kısaltma → sözlük → normalizasyon → konuşma dili → dolgu."""
        try:
            from . import lexicon
        except Exception:  # noqa: BLE001
            lexicon = None

        def _norm(seg: str) -> str:
            out = seg
            if lexicon is not None:
                try:
                    out = lexicon.apply_inline_readings(out)
                    if chat_speak and language == "tr":
                        out = lexicon.expand_chat_speak(out)
                    if language == "tr":
                        lex_changes.extend(lexicon.lexicon_report(out, voice_id, language))
                        out = lexicon.apply_lexicon(out, language, voice_id)
                except Exception as e:  # noqa: BLE001
                    log.debug("Sözlük katmanı atlandı: %s", e)
            out = normalize(out, language)
            if level != "off" and language == "tr":
                try:
                    changes.extend(colloquial_report(out, level))
                except Exception:  # noqa: BLE001
                    pass
                out = colloquial_tr(out, level)
            return out

        return _norm

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
        colloquial: bool | str = True,
        punctuation_emotion: bool = True,
        auto_emotion: bool = False,
        emotion_refs: bool = False,
        progress: ProgressFn | None = None,
        emotion_fx: str = "off",
        *,
        breaths: bool = True,
        room_tone: bool = True,
        master: bool = True,
        pause_scale: float = 1.0,
        consistency: bool = True,
        qc: bool = True,
        fillers: bool = False,
        chat_speak: bool = True,
        subtitles: bool = True,
        style: str | None = None,
        partial: PartialFn | None = None,
        check_cancelled: CheckFn | None = None,
    ) -> tuple[np.ndarray, int, dict]:
        """Döndürür: (ses, örnekleme hızı, rapor {normalized_text, chunks, colloquial_changes, prosody, qc, timeline…})."""
        if isinstance(refs, (str, Path)):
            refs = VoiceRefs("adhoc", Path(refs), {})
        level = normalize_level(colloquial)
        changes: list[dict] = []
        lex_changes: list[dict] = []
        _norm = self._make_normalizer(language, level, refs.voice_id if refs else None, chat_speak, fillers, style,
                                      seed, changes, lex_changes)
        text = self._with_fillers(text, language, fillers, style, seed)
        chunks = split_text(text, config.CHUNK_CHARS, normalizer=_norm, auto_emotion=auto_emotion, keep_nonverbal=True,
                            recorded_nonverbal=self._recorded_nonverbal(refs))
        if not chunks:
            raise ValueError("Metin boş.")
        report: dict = {"normalized_text": " ".join(c.text for c in chunks if c.text), "chunks": [],
                        "colloquial_level": level, "colloquial_changes": _dedupe_changes(changes),
                        "lexicon_changes": _dedupe_changes(lex_changes), "nonverbal_used": []}
        total_scale = self._pause_scale(refs, pause_scale)

        with self._lock:
            model = self.tts()
            sr = int(model.sr)
            base_kwargs = _filter_kwargs(model.generate, {
                "language_id": language, "exaggeration": float(exaggeration),
                "cfg_weight": float(cfg_weight), "temperature": float(temperature),
            })
            pieces, base_pauses, qc_reports = self._render_chunks(
                model, sr, chunks, refs, base_kwargs, seed, speed, punctuation_emotion, emotion_refs, emotion_fx,
                qc, progress, partial, check_cancelled, report)
            if check_cancelled:
                check_cancelled()
            wav, info = self._finish(pieces, base_pauses, chunks, sr, refs, total_scale, breaths, room_tone, master,
                                     consistency, seed, progress, len(chunks), report)
            report["prosody"] = info
            if qc:
                try:
                    from .qc import summarize

                    indexed = [{"index": i, **r} for i, r in enumerate(qc_reports) if r]
                    report["qc"] = indexed
                    report["qc_summary"] = summarize(indexed)
                except Exception:  # noqa: BLE001
                    pass
            if subtitles:
                report["timeline"] = self._timeline(report["chunks"], info, sr)
            return wav, sr, report

    # ---------- diyalog ----------
    def synthesize_dialog(
        self,
        text: str,
        speakers: dict[str, VoiceRefs | None],
        narrator: VoiceRefs | None = None,
        language: str = "tr",
        *,
        default_emotions: dict[str, str] | None = None,
        progress: ProgressFn | None = None,
        partial: PartialFn | None = None,
        check_cancelled: CheckFn | None = None,
        **opts: Any,
    ) -> tuple[np.ndarray, int, dict]:
        """Çok konuşmacılı metin: her sıra kendi sesiyle üretilir, sıra alma duraklamalarıyla birleştirilir."""
        from .dialog import merge_turn_report, parse_dialog, plan_turn_pauses

        turns = [t for t in parse_dialog(text) if t.text.strip()]
        if not turns:
            raise ValueError("Diyalog boş.")
        o = SynthOptions(language=language, **{k: v for k, v in opts.items() if k in SynthOptions.__dataclass_fields__})
        level = normalize_level(o.colloquial)
        seed = o.seed
        default_emotions = default_emotions or {}
        tr_lower = __import__("app.tr", fromlist=["tr_lower"]).tr_lower
        spk_map = {tr_lower(k): v for k, v in speakers.items()}
        emo_map = {tr_lower(k): v for k, v in default_emotions.items()}

        # Her sıranın parçaları (konuşmacı sesine göre normalize edilir)
        all_chunks: list[Chunk] = []
        turn_of_chunk: list[int] = []
        refs_of_turn: list[VoiceRefs | None] = []
        changes: list[dict] = []
        lex_changes: list[dict] = []
        for t in turns:
            refs = narrator if t.speaker is None else spk_map.get(tr_lower(t.speaker), narrator)
            refs_of_turn.append(refs)
            ttext = self._with_fillers(t.text, language, o.fillers, o.style, (seed or 0) + t.index)
            emo = emo_map.get(tr_lower(t.speaker)) if t.speaker else None
            if emo and not _starts_with_emotion_tag(ttext):
                ttext = f"[{emo}] {ttext}"
            _norm = self._make_normalizer(language, level, refs.voice_id if refs else None, o.chat_speak, o.fillers,
                                          o.style, seed, changes, lex_changes)
            tchunks = split_text(ttext, config.CHUNK_CHARS, normalizer=_norm, auto_emotion=o.auto_emotion, keep_nonverbal=True,
                                 recorded_nonverbal=self._recorded_nonverbal(refs))
            for c in tchunks:
                c.speaker = t.speaker
            if tchunks:
                tchunks[-1].turn_end = True
            elif all_chunks:
                # Yalnızca duraklama etiketi içeren sıra ("Ayşe: [2 sn]"): süresi önceki parçaya eklenir
                all_chunks[-1].tag_pause_ms += _pause_only_ms(ttext)
            all_chunks.extend(tchunks)
            turn_of_chunk.extend([t.index] * len(tchunks))
        if not all_chunks:
            raise ValueError("Diyalog boş.")
        report: dict = {"normalized_text": " ".join(c.text for c in all_chunks if c.text), "chunks": [],
                        "colloquial_level": level, "colloquial_changes": _dedupe_changes(changes),
                        "lexicon_changes": _dedupe_changes(lex_changes), "nonverbal_used": [], "dialog": True}

        with self._lock:
            model = self.tts()
            sr = int(model.sr)
            base_kwargs = _filter_kwargs(model.generate, {
                "language_id": language, "exaggeration": float(o.exaggeration),
                "cfg_weight": float(o.cfg_weight), "temperature": float(o.temperature),
            })
            # Parçaları sıra sıra üret (her sıra kendi referansıyla)
            pieces: list[np.ndarray] = []
            base_pauses: list[int] = []
            qc_reports: list[dict | None] = []
            done = 0
            for ti, t in enumerate(turns):
                idx = [k for k, tt in enumerate(turn_of_chunk) if tt == t.index]
                if not idx:
                    continue
                sub = [all_chunks[k] for k in idx]

                def _prog(i, n, msg, _d=done, _tot=len(all_chunks)):
                    if progress:
                        progress(_d + i, _tot, f"{t.speaker or 'anlatıcı'}: {msg}")

                def _part(i, w, s, txt, speaker=None):
                    if partial:
                        _call_partial(partial, i, w, s, txt, speaker)   # _render_chunks zaten index_offset ekler

                p, bp, qr = self._render_chunks(model, sr, sub, refs_of_turn[ti], base_kwargs, seed, o.speed,
                                                o.punctuation_emotion, o.emotion_refs, o.emotion_fx, o.qc,
                                                _prog, _part, check_cancelled, report, index_offset=done)
                pieces.extend(p)
                base_pauses.extend(bp)
                qc_reports.extend(qr)
                done += len(sub)
            if check_cancelled:
                check_cancelled()
            # Sıra sınırlarındaki duraklamalar: konuşma sırası alma planı
            last_chunk_of_turn = {}
            for k, tt in enumerate(turn_of_chunk):
                last_chunk_of_turn[tt] = k
            durations = []
            for t in turns:
                idx = [k for k, tt in enumerate(turn_of_chunk) if tt == t.index]
                durations.append(sum(len(pieces[k]) / sr for k in idx) if idx else 0.0)
            tpauses = plan_turn_pauses(turns, durations, seed=seed)
            for t, tp in zip(turns, tpauses):
                k = last_chunk_of_turn.get(t.index)
                if k is not None:
                    base_pauses[k] = int(tp)
            # Birleştirme: tutarlılık konuşmacı başına, oda tonu/nefes anlatıcı ya da ilk konuşmacı kaydından
            first_refs = next((r for r in refs_of_turn if r is not None), None)
            wav, info = self._finish(pieces, base_pauses, all_chunks, sr, first_refs, self._pause_scale(first_refs, o.pause_scale),
                                     o.breaths, o.room_tone, o.master, False, seed, progress, len(all_chunks), report,
                                     consistency_groups=(turn_of_chunk, refs_of_turn, turns) if o.consistency else None)
            report["prosody"] = info
            if o.qc:
                try:
                    from .qc import summarize

                    indexed = [{"index": i, **r} for i, r in enumerate(qc_reports) if r]
                    report["qc"] = indexed
                    report["qc_summary"] = summarize(indexed)
                except Exception:  # noqa: BLE001
                    pass
            timeline = self._timeline(report["chunks"], info, sr)
            if o.subtitles:
                report["timeline"] = timeline
            # Sıra raporu (başlangıç/bitiş zamanları zaman çizelgesinden)
            starts, ends = [], []
            for t in turns:
                idx = [k for k, tt in enumerate(turn_of_chunk) if tt == t.index]
                if idx and timeline:
                    starts.append(timeline[idx[0]]["start"])
                    ends.append(timeline[idx[-1]]["end"])
                else:
                    starts.append(0.0)
                    ends.append(0.0)
            names = {}
            for t, r in zip(turns, refs_of_turn):
                key = t.speaker or "Anlatıcı"
                names[key] = (r.name if r and r.name else "Varsayılan ses")
            report["turns"] = merge_turn_report(turns, starts, ends, names)
            report["speakers"] = [{"speaker": s, "voice_name": names.get(s, "")} for s in names]
            return wav, sr, report

    # ---------- iç yardımcılar ----------
    @staticmethod
    def _with_fillers(text: str, language: str, fillers: bool, style: str | None, seed: int | None) -> str:
        """Konuşma dolgularını (yani, hani, işte…) tüm metne bir kez, etiketlere dokunmadan uygular."""
        if not fillers or language != "tr":
            return text
        try:
            from . import lexicon

            return lexicon.add_fillers(text, seed=seed, style=style or "sohbet")
        except Exception as e:  # noqa: BLE001
            log.debug("Dolgu katmanı atlandı: %s", e)
            return text

    @staticmethod
    def _pause_scale(refs: VoiceRefs | None, pause_scale: float) -> float:
        natural_scale = 1.0
        if refs is not None:
            try:
                if refs.pause_scale:
                    natural_scale = float(refs.pause_scale)
                elif refs.analysis:
                    natural_scale = float(refs.analysis.get("pauses", {}).get("scale") or 1.0)
            except (TypeError, ValueError, AttributeError):
                natural_scale = 1.0
        return min(2.0, max(0.5, float(pause_scale) * natural_scale))

    @staticmethod
    def _recorded_nonverbal(refs: VoiceRefs | None) -> frozenset[str]:
        """Bu ses için gerçek kaydı olan tepki anahtarları (yalnızca bunlar ayrı parça olur)."""
        if refs is None or not refs.nonverbal:
            return frozenset()
        return frozenset(k for k, p in refs.nonverbal.items() if p is not None and Path(p).exists())

    def _render_chunks(self, model, sr: int, chunks: list[Chunk], refs: VoiceRefs | None, base_kwargs: dict,
                       seed: int | None, speed: float, punctuation_emotion: bool, emotion_refs: bool, emotion_fx: str,
                       use_qc: bool, progress, partial, check_cancelled, report: dict, index_offset: int = 0
                       ) -> tuple[list[np.ndarray], list[int], list[dict | None]]:
        """Parçaları sırayla üretir (tepkiler kayıttan, metinler modelden); QC ile yeniden üretim yapar."""
        pieces: list[np.ndarray] = []
        base_pauses: list[int] = []
        qc_reports: list[dict | None] = []
        n = len(chunks)
        expected_cps = None
        if use_qc and refs is not None:
            try:
                from .qc import estimate_cps

                expected_cps = estimate_cps(self._cps_history.get(refs.voice_id, []))
            except Exception:  # noqa: BLE001
                expected_cps = None
        for i, ch in enumerate(chunks):
            if check_cancelled:
                check_cancelled()
            gi = index_offset + i
            if progress:
                progress(i, n, (ch.text or f"[{ch.nonverbal}]")[:60])
            if seed is not None:
                self._seed(seed + gi)
            # --- gerçek tepki parçası ---
            if ch.nonverbal:
                piece = self._nonverbal_piece(ch, refs, sr, seed, gi, pieces)
                pieces.append(piece)
                base_pauses.append(ch.pause_after_ms)
                qc_reports.append(None)
                report["nonverbal_used"].append(ch.nonverbal)
                report["chunks"].append({"text": f"[{ch.nonverbal}]", "emotion": ch.emotion, "ref": "tepki kaydı",
                                         "nonverbal": ch.nonverbal, "exaggeration": None, "cfg_weight": None,
                                         "speed": 1.0, "pause_ms": ch.pause_after_ms, "duration": round(len(piece) / sr, 3),
                                         "speaker": ch.speaker})
                if partial:
                    try:
                        _call_partial(partial, gi, piece, sr, f"[{ch.nonverbal}]", ch.speaker)
                    except Exception:  # noqa: BLE001
                        pass
                continue
            # --- metin parçası ---
            profile = self._profile_for(ch)
            kw, chunk_speed = self._chunk_settings(base_kwargs, profile, ch.punct if punctuation_emotion else "", len(ch.text), emotion_fx)
            if ch.emphasized:
                cap = 0.8 if len(ch.text) < 25 else 0.95        # kısa parça kararlılık sınırı korunur
                kw["exaggeration"] = min(cap, kw.get("exaggeration", 0.5) + 0.15)
                chunk_speed *= 0.95
            if ch.rate:
                chunk_speed *= float(ch.rate)
            ref_emotion = ch.arc_to if (ch.arc_to and ch.arc_t is not None and ch.arc_t >= 0.5) else ch.emotion
            ref_path, ref_src = self.reference_for(refs, ref_emotion, derive=emotion_refs and emotion_fx == "full")
            if ref_path is not None:
                kw["audio_prompt_path"] = str(ref_path)
            elif self._default_conds is not None and hasattr(model, "conds"):
                model.conds = self._default_conds      # klonsuz üretim: varsayılan sesi geri yükle
            kw["emotion"] = ref_emotion or ch.emotion      # yalnızca bunu tanımlayan arka uçlar alır (ince ayar etiketi)
            kw = _filter_kwargs(model.generate, kw)
            log.info("Parça %d/%d (%d kar.) duygu=%s×%.2f ref=%s ex=%.2f cfg=%.2f hız=%.2f%s",
                     i + 1, n, len(ch.text), ch.emotion or "-", ch.intensity, ref_src,
                     kw.get("exaggeration", 0.5), kw.get("cfg_weight", 0.5), chunk_speed * speed,
                     " VURGU" if ch.emphasized else "")
            piece, qrep = self._generate_checked(model, ch.text, kw, sr, use_qc=use_qc, expected_cps=expected_cps,
                                                 seed=(seed + gi) if seed is not None else None)
            if refs is not None and len(ch.text) >= 20 and piece.size:
                hist = self._cps_history.setdefault(refs.voice_id, [])
                hist.append((len(ch.text), len(piece) / sr))       # ham model süresi (hız/perde öncesi)
                del hist[:-40]
            piece = post_process(piece, sr, profile, emotion_fx)
            if ch.pitch:
                piece = self._pitch_shift(piece, sr, float(ch.pitch))
            piece = audio.change_speed(piece, sr, chunk_speed * speed)
            if piece.size < int(sr * 0.05):      # ffmpeg çok kısa parçayı boşaltabilir; sessiz dolgu
                piece = np.zeros(int(sr * 0.05), dtype=np.float32)
            pieces.append(piece)
            pause = int(ch.pause_after_ms * (profile.pause_mul if profile else 1.0))
            base_pauses.append(pause)
            qc_reports.append(qrep)
            report["chunks"].append({"text": ch.text, "emotion": ch.emotion, "ref": ref_src,
                                     "intensity": round(ch.intensity, 2) if ch.intensity != 1.0 else None,
                                     "blend": ch.blend or None, "arc_to": ch.arc_to, "emphasized": ch.emphasized or None,
                                     "exaggeration": round(kw.get("exaggeration", 0.5), 2),
                                     "cfg_weight": round(kw.get("cfg_weight", 0.5), 2),
                                     "speed": round(chunk_speed * speed, 2), "pause_ms": pause,
                                     "duration": round(len(piece) / sr, 3), "speaker": ch.speaker,
                                     "qc_score": qrep.get("score") if qrep else None,
                                     "retries": qrep.get("retries") if qrep else None})
            if partial:
                try:
                    _call_partial(partial, gi, piece, sr, ch.text, ch.speaker)
                except Exception as e:  # noqa: BLE001
                    log.debug("Canlı önizleme parçası yazılamadı: %s", e)
        return pieces, base_pauses, qc_reports

    @staticmethod
    def _profile_for(ch: Chunk) -> EmotionProfile | None:
        """Parçanın etkin duygu profili: yoğunluk + karışım + kayış."""
        try:
            prof = effective_profile(ch.emotion, ch.intensity, ch.blend or None)
            if ch.arc_to and ch.arc_t is not None:
                target = effective_profile(ch.arc_to, ch.intensity, None)
                prof = interpolate_profile(prof, target, float(ch.arc_t))
            return prof
        except Exception as e:  # noqa: BLE001
            log.debug("Duygu profili hesaplanamadı: %s", e)
            return PROFILES.get(ch.emotion or "")

    def _nonverbal_piece(self, ch: Chunk, refs: VoiceRefs | None, sr: int, seed: int | None, gi: int,
                         prev_pieces: list[np.ndarray]) -> np.ndarray:
        """Kullanıcının gerçek tepki kaydını komşu konuşma seviyesine göre seviyeleyerek döndürür."""
        from .nonverbal import active_rms_db, level_match, render_nonverbal

        path = refs.nonverbal[ch.nonverbal]
        piece = render_nonverbal(path, sr, seed=(seed + gi) if seed is not None else None)
        neighbor = None
        for p in reversed(prev_pieces):
            if p.size > sr // 5:
                try:
                    neighbor = active_rms_db(p, sr)
                except Exception:  # noqa: BLE001
                    neighbor = None
                break
        try:
            piece = level_match(piece, sr, neighbor)
        except Exception:  # noqa: BLE001
            pass
        return np.asarray(piece, dtype=np.float32)

    @staticmethod
    def _pitch_shift(piece: np.ndarray, sr: int, semitones: float) -> np.ndarray:
        from .emotion import _ffmpeg_filter, pitch_tempo_filter

        try:
            f = pitch_tempo_filter(sr, semitones, 1.0)
            return _ffmpeg_filter(piece, sr, f) if f else piece
        except Exception as e:  # noqa: BLE001
            log.debug("Perde kaydırma atlandı: %s", e)
            return piece

    def _finish(self, pieces, base_pauses, chunks, sr, refs, total_scale, breaths, room_tone, master, consistency,
                seed, progress, n, report, consistency_groups=None) -> tuple[np.ndarray, dict]:
        """Tutarlılık → doğal birleştirme → mastering → ses yüksekliği ölçümü."""
        cons_info = None
        if consistency or consistency_groups:
            if progress:
                progress(n, n, "tını eşitleniyor")
            pieces, cons_info = self._apply_consistency(pieces, chunks, sr, refs, consistency_groups)
        if progress:
            progress(n, n, "birleştiriliyor")
        wav, info = self._assemble(chunks, pieces, base_pauses, sr, refs, total_scale, breaths, room_tone, seed)
        if cons_info:
            info["consistency"] = cons_info
        for c, p in zip(report["chunks"], info["pauses_ms"]):
            c["pause_ms"] = p
        if master:
            if progress:
                progress(n, n, "seviye dengeleniyor")
            try:
                wav = prosody.master(wav, sr)
            except Exception as e:  # noqa: BLE001
                log.warning("Mastering atlandı: %s", e)
                wav = audio.normalize_relative(wav, pieces, target_dbfs=-18.0, peak_dbfs=-1.0)
        else:
            wav = audio.normalize_relative(wav, pieces, target_dbfs=-18.0, peak_dbfs=-1.0)
        try:
            report["loudness"] = prosody.measure_loudness(wav, sr)
        except Exception:  # noqa: BLE001
            pass
        return wav, info

    def _apply_consistency(self, pieces, chunks, sr, refs, groups=None):
        """Metin parçalarını referans tınısına yaklaştırır ve ardışık seviye sıçramalarını sınırlar (tepkiler hariç)."""
        try:
            from .consistency import align_loudness, consistency_report, match_timbre
        except Exception:  # noqa: BLE001
            return pieces, None
        before = list(pieces)
        out = list(pieces)
        text_idx = [i for i, c in enumerate(chunks) if not c.nonverbal and pieces[i].size > sr // 5]
        try:
            if groups:
                turn_of_chunk, refs_of_turn, turns = groups
                turn_refs = {t.index: r for t, r in zip(turns, refs_of_turn)}
                targets = {}
                for i in text_idx:
                    r = turn_refs.get(turn_of_chunk[i])
                    key = r.voice_id if r else None
                    if key not in targets:
                        targets[key] = self._voice_ltas(r, sr) if r else None
                    if targets[key] is not None:
                        out[i] = match_timbre(out[i], sr, targets[key])
            else:
                target = self._voice_ltas(refs, sr)
                if target is not None:
                    for i in text_idx:
                        out[i] = match_timbre(out[i], sr, target)
            sub = align_loudness([out[i] for i in text_idx])
            for i, p in zip(text_idx, sub):
                out[i] = p
            rep = consistency_report([before[i] for i in text_idx], [out[i] for i in text_idx], sr) if text_idx else {}
            return out, rep
        except Exception as e:  # noqa: BLE001
            log.warning("Tutarlılık katmanı atlandı: %s", e)
            return pieces, None

    @staticmethod
    def _timeline(chunk_reports: list[dict], info: dict, sr: int) -> list[dict]:
        try:
            from .timing import build_timeline

            tl_chunks = [{"text": c["text"], "duration": float(c["duration"]), "emotion": c.get("emotion"),
                          "speaker": c.get("speaker")} for c in chunk_reports]
            extra = info.get("extra_before_ms")
            return build_timeline(tl_chunks, info.get("pauses_ms", []), sr, extra_before_ms=extra)
        except Exception as e:  # noqa: BLE001
            log.debug("Zaman çizelgesi üretilemedi: %s", e)
            return []

    def _assemble(self, chunks: list[Chunk], pieces: list[np.ndarray], base_pauses: list[int], sr: int,
                  refs: VoiceRefs | None, pause_scale: float, breaths: bool, room_tone: bool,
                  seed: int | None) -> tuple[np.ndarray, dict]:
        """Parçaları doğal duraklama/nefes/oda tonuyla birleştirir; sorun olursa eski düz birleştirmeye düşer."""
        info: dict = {"pause_scale": round(pause_scale, 3), "breaths": 0, "room_tone": False}
        try:
            plan_in = []
            for i, (c, p) in enumerate(zip(chunks, base_pauses)):
                plan_in.append({"text": c.text or f"[{c.nonverbal}]", "punct": c.punct, "emotion": c.emotion,
                                "pause_after_ms": p, "paragraph_end": c.paragraph_end,
                                "next_text": (chunks[i + 1].text or "tepki") if i + 1 < len(chunks) else None})
            pauses = prosody.plan_pauses(plan_in, pause_scale=pause_scale, seed=seed)
            # Vurgu/tepki mikro duraklamaları ve etiket duraklamaları ölçeklenmeden, birebir
            fixed = []
            for i, c in enumerate(chunks):
                is_last = i == len(chunks) - 1
                nxt = chunks[i + 1] if not is_last else None
                if is_last:
                    pass
                elif c.turn_end:
                    pauses[i] = int(c.pause_after_ms)          # diyalog sıra alma planı: ezilmez
                elif nxt is not None and nxt.nonverbal:
                    pauses[i] = int(nxt.pause_before_ms)       # tepki öncesi mikro duraklama (90 ms)
                elif c.nonverbal:
                    pauses[i] = int(c.pause_after_ms)          # tepki sonrası (140 ms)
                elif c.emphasized or (nxt is not None and nxt.emphasized):
                    pauses[i] = int(c.pause_after_ms)          # vurgu mikro duraklaması (_apply_emphasis belirledi)
                fixed.append(min(MAX_TAG_PAUSE_MS, int(c.tag_pause_ms)))
            pauses = [int(p) + t for p, t in zip(pauses, fixed)]
            durations = [len(p) / sr for p in pieces]
            room = breath = None
            if room_tone or breaths:
                room, breath = self._room_and_breath(refs)
            breath_plan = prosody.plan_breaths(plan_in, durations, seed=seed) if breaths else None
            if breath_plan:
                for i, c in enumerate(chunks):
                    if c.nonverbal or c.emphasized or (i > 0 and chunks[i - 1].nonverbal):
                        breath_plan[i] = False
            wav = prosody.join_natural(pieces, pauses, sr, room_tone=room if room_tone else None,
                                       breath=breath, breath_plan=breath_plan)
            # Nefes eklenen yerlerde boşluk uzamış olabilir: gerçek boşluklar prosody'den (zaman çizelgesi için)
            extra = [0] * len(chunks)
            actual = list(getattr(prosody, "LAST_JOIN_GAPS_MS", []) or [])
            if len(actual) == len(pauses):
                for i in range(1, len(chunks)):
                    extra[i] = max(0, int(actual[i - 1]) - int(pauses[i - 1]))
            info.update({"pauses_ms": [int(p) for p in pauses], "extra_before_ms": extra,
                         "breaths": int(sum(breath_plan)) if breath_plan else 0,
                         "breath_source": ("kayıt" if breath is not None else "sentetik") if breath_plan and any(breath_plan) else None,
                         "room_tone": bool(room_tone and room is not None)})
            return wav, info
        except Exception as e:  # noqa: BLE001
            log.warning("Doğal birleştirme başarısız, düz birleştirmeye dönülüyor: %s", e)
            flat = [int(p) + min(MAX_TAG_PAUSE_MS, int(c.tag_pause_ms)) for p, c in zip(base_pauses, chunks)]
            wav = audio.join_with_pauses(pieces, flat, sr)
            info["pauses_ms"] = flat
            info["fallback"] = str(e)
            return wav, info

    @staticmethod
    def _chunk_settings(base: dict, profile: EmotionProfile | None, punct: str, text_len: int = 100, fx: str = "off") -> tuple[dict, float]:
        kw = dict(base)
        speed = 1.0
        if profile is not None:
            # Profil değerleri varsayılan ayarlara (NEUTRAL_SETTINGS) göre tanımlıdır ve kullanıcının ayarının ÜSTÜNE
            # fark olarak eklenir: [heyecanlı] varsayılanda 0,5 → 0,7 iken kullanıcı 0,8 seçtiyse 1,0'a (sınırla 0,95)
            # çıkar. Eskiden mutlak yazılıyordu; her cümlesi etiketli metinde ayar çubukları hiç etki etmiyordu.
            for key in ("exaggeration", "cfg_weight", "temperature"):
                target = getattr(profile, key)
                if target is not None:
                    kw[key] = float(kw.get(key, NEUTRAL_SETTINGS[key])) + (float(target) - NEUTRAL_SETTINGS[key])
            if "temperature" in kw:
                kw["temperature"] = min(1.2, max(0.5, float(kw["temperature"])))
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

    def _generate_checked(self, model, text: str, gen_kwargs: dict, sr: int, *, use_qc: bool = True,
                          expected_cps: float | None = None, seed: int | None = None) -> tuple[np.ndarray, dict | None]:
        """Üretir ve kalite kontrolünden geçirir; bozuksa farklı tohumla / daha kararlı ayarlarla yeniden dener.

        Döndürür: (ses, qc raporu | None). QC kapalıysa eski süre denetimi uygulanır.
        """
        n = len(text)
        max_dur = n / MIN_CHARS_PER_SEC + 1.2
        min_dur = max(0.25, n / MAX_CHARS_PER_SEC)
        stable = {**gen_kwargs, "temperature": min(float(gen_kwargs.get("temperature", 0.8)), 0.6),
                  "cfg_weight": max(float(gen_kwargs.get("cfg_weight", 0.5)), 0.4)}
        if not use_qc:
            best = None
            for k, kwargs in enumerate([gen_kwargs, stable]):
                wav = self._to_numpy(model.generate(text, **_filter_kwargs(model.generate, kwargs)))
                wav = audio.trim_silence(wav, sr, threshold_db=-45.0, pad_ms=40)
                dur = len(wav) / sr
                if min_dur <= dur <= max_dur:
                    return wav, None
                score = (dur - max_dur) if dur > max_dur else (min_dur - dur) * 3
                if best is None or score < best[0]:
                    best = (score, wav)
            wav = best[1]
            if len(wav) / sr > max_dur:
                wav = audio.cut_at_silence(wav, sr, max_dur)
            return wav, None

        from .qc import apply_trim, check_chunk, pick_best

        attempts: list[tuple[np.ndarray, dict]] = []
        plan = [("ilk", gen_kwargs), ("tohum", gen_kwargs), ("kararlı", stable)]
        for k, (label, kwargs) in enumerate(plan):
            if k > 0 and seed is not None:
                self._seed(seed + 9973 * k)
            wav = self._to_numpy(model.generate(text, **_filter_kwargs(model.generate, kwargs)))
            wav = audio.trim_silence(wav, sr, threshold_db=-45.0, pad_ms=40)
            try:
                rep = check_chunk(wav, sr, text, expected_cps=expected_cps)
            except Exception as e:  # noqa: BLE001
                log.debug("QC atlandı: %s", e)
                return wav, None
            attempts.append((wav, rep))
            decision = rep.get("decision", "accept")
            if decision in ("accept", "trim"):
                break
            log.warning("Parça kalite kontrolü (%s): puan %s, karar %s — %s", label, rep.get("score"), decision,
                        "; ".join(r.get("message", "") for r in rep.get("reasons", [])[:2]))
            if decision == "retry_stable" and k < 2:
                plan[k + 1] = ("kararlı", stable)
        idx = pick_best([r for _, r in attempts])
        wav, rep = attempts[idx]
        rep = dict(rep)
        rep["retries"] = len(attempts) - 1
        rep["attempt"] = idx + 1
        if rep.get("decision") in ("trim", "retry_seed") and len(wav) / sr > max_dur:
            try:
                wav = apply_trim(wav, sr, rep)
            except Exception:  # noqa: BLE001
                wav = audio.cut_at_silence(wav, sr, max_dur)
        elif rep.get("decision") == "trim":
            try:
                wav = apply_trim(wav, sr, rep)
            except Exception:  # noqa: BLE001
                pass
        return wav, rep

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

        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        try:
            import torch

            torch.manual_seed(seed)
            if self.device == "cuda":
                torch.cuda.manual_seed_all(seed)
        except ImportError:          # torch'suz arka uçlar (MLX, sahte)
            pass
        model = self._tts
        if model is not None and hasattr(model, "seed"):
            try:
                model.seed(int(seed))        # arka ucun kendi üreteci (mlx.random vb.)
            except Exception:  # noqa: BLE001
                pass


def _pause_only_ms(text: str) -> int:
    """Yalnızca duraklama etiketlerinden oluşan metnin ([2 sn] [nefes]) toplam süresi (ms), en çok 10 sn."""
    from .emotion import PAUSE_TAGS, timed_pause_ms
    from .tr import tr_lower

    total = 0
    for m in re.finditer(r"\[\s*([^\[\]]{1,40}?)\s*\]", text or ""):
        raw = tr_lower(m.group(1).strip())
        ms = timed_pause_ms(raw)
        if ms is None:
            ms = PAUSE_TAGS.get(raw)
        if ms:
            total += int(ms)
    return min(MAX_TAG_PAUSE_MS, total)


def _call_partial(fn, i: int, wav: np.ndarray, sr: int, text: str, speaker: str | None) -> None:
    """Canlı önizleme geri çağrısı: 5 parametre kabul ediyorsa konuşmacıyı da verir (eski 4'lü imza korunur)."""
    try:
        n = len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        n = 4
    if n >= 5:
        fn(i, wav, sr, text, speaker)
    else:
        fn(i, wav, sr, text)


def _starts_with_emotion_tag(text: str) -> bool:
    """Metin bir DUYGU etiketiyle mi başlıyor ([gülme]/[2 sn] gibi tepki ve duraklama etiketleri sayılmaz)."""
    m = re.match(r"\s*\[\s*([^\[\]]{1,40}?)\s*\]", text or "")
    if not m:
        return False
    try:
        segs = parse_tagged_text(m.group(0) + " x", keep_nonverbal=True)
    except Exception:  # noqa: BLE001
        return False
    return bool(segs) and segs[0].emotion is not None


def _dedupe_changes(changes: list[dict], limit: int = 60) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for c in changes:
        key = (str(c.get("from", "")), str(c.get("to", "")))
        if key in seen or key[0] == key[1]:
            continue
        seen.add(key)
        out.append({"from": key[0], "to": key[1], "rule": c.get("rule", "")})
        if len(out) >= limit:
            break
    return out


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine
