"""Doğal konuşma ritmi: duraklama planı, nefes, oda tonu, doğal birleştirme ve mastering.

ElevenLabs çıktılarını "insan" gibi duyuran şey cümleler arasındaki ritimdir: her yerde aynı uzunlukta dijital
sessizlik yerine bağlama göre değişen duraklamalar, arada bir nefes, "ölü hava" yerine sürekli bir oda tonu ve
tutarlı ses seviyesi. Bu modül bunları motordan bağımsız, saf numpy/scipy fonksiyonları olarak sağlar; ffmpeg
yalnızca `master` ve `measure_loudness` içinde (varsa) kullanılır, yoksa saf Python yedeklerine düşülür.

Sözleşme: docs/SOZLESME.md bölüm 3. Motor tarafında tipik kullanım:

    pauses = plan_pauses(chunk_dicts, pause_scale, seed)
    plan = plan_breaths(chunk_dicts, [len(p) / sr for p in pieces], seed=seed)
    wav = join_natural(pieces, pauses, sr, room_tone=floor, breath=breath, breath_plan=plan)
    wav = master(wav, sr)
"""
from __future__ import annotations

import functools
import logging
import math
import re
import subprocess
import tempfile
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import fft as sfft
from scipy import signal

from .audio import db_to_amp, fade, has_ffmpeg, rms_normalize
from .tr import count_syllables_text, tr_lower

log = logging.getLogger("sesklon.prosody")

__all__ = [
    "CONJUNCTIONS",
    "plan_pauses",
    "plan_breaths",
    "synth_breath",
    "make_room_tone",
    "join_natural",
    "master",
    "measure_loudness",
]

# ---------- duraklama kuralları ----------

#: Sonraki cümle bunlardan biriyle başlıyorsa düşünce sürüyordur → duraklama kısalır. Çok sözcüklüler de var;
#: eşleşme tam sözcük bazındadır ("ama" ≠ "amaç", "ve" ≠ "veri", "de" ≠ "deniz").
CONJUNCTIONS: tuple[str, ...] = (
    "ama", "fakat", "ancak", "lakin", "çünkü", "zira", "yani", "ki", "ve", "veya", "ya da", "de", "da",
    "hatta", "üstelik", "ayrıca", "oysa", "halbuki", "sonra", "daha sonra", "o zaman", "zaten", "mesela",
    "örneğin", "yoksa", "neyse", "tabii", "tabi", "tamam", "peki", "işte", "şimdi", "bir de", "hem de",
    "nitekim", "dolayısıyla", "bu yüzden", "bu nedenle", "böylece", "ama yine de",
)
_CONJ_TOKENS: tuple[tuple[str, ...], ...] = tuple(
    sorted({tuple(c.split()) for c in CONJUNCTIONS}, key=len, reverse=True)
)

CONJ_FACTOR = 0.65            # bağlaçla başlayan sonraki cümle → %35 kısa
QA_FACTOR = 0.80              # soru → kısa cevap → %20 kısa (soru-cevap ritmi)
QA_MAX_CHARS = 40
LONG_CHARS, LONG_FACTOR = 140, 1.15     # çok uzun cümleden sonra soluklanma
SHORT_CHARS, SHORT_FACTOR = 15, 0.85    # "Evet." gibi kısa cümleden sonra çabuk devam
JITTER = 0.12                 # ±%12 titreşim: hiçbir iki duraklama birebir aynı olmasın
PARAGRAPH_MIN_MS = 600
PAUSE_MIN_MS, PAUSE_MAX_MS = 60, 2500
PAUSE_SCALE_MIN, PAUSE_SCALE_MAX = 0.5, 2.0
# pause_after_ms verilmemişse (engine.PAUSE_MS ile aynı temel değerler)
_DEFAULT_PAUSE_MS = {"": 380, "!": 420, "?": 450, "...": 550}
_PARAGRAPH_PAUSE_MS = 650

# ---------- nefes kuralları ----------

BREATH_MIN_PIECE_S = 2.5      # nefes, ancak bu kadar uzun bir cümleden önce alınır (aralık kuralı)
BREATH_PAD_MS = 120           # nefesin iki yanında toplam bu kadar boşluk kalır
ELLIPSIS_BREATH_P = 0.75      # "..." sonrası nefes olasılığı
EXCITED_GAP_FACTOR = 0.8      # "!"/heyecan sonrası nefes daha sık
_MAX_BREATH_S = 1.0
_WHISPER = frozenset({"fısıltı", "fisilti", "whisper"})
_EXCITED = frozenset({"heyecanlı", "heyecanli", "kızgın", "kizgin", "korkmuş", "korkmus"})

# ---------- oda tonu / seviye ----------

ROOM_TONE_DB = -58.0
ROOM_TONE_MAX_BOOST_DB = 6.0  # çok temiz bir kaydın tabanını en fazla bu kadar yükselt
_LOOP_XFADE_MS = 20
_EDGE_FADE_MS = 10
_PINK_MAX_S = 8.0             # daha uzun pembe gürültü bu uzunlukta üretilip döngülenir (bellek sınırı)
SILENCE_DB = -120.0           # sessizlik için dBFS tabanı (JSON'a yazılabilir sonlu değer)
_ABS_GATE_LUFS = -70.0
_LIMITER_MARGIN_DB = 0.2


# ---------- küçük yardımcılar ----------

def _to_float(v, default: float | None = None) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _rng(seed: int | None) -> np.random.Generator:
    if seed is None:
        return np.random.default_rng()
    # negatif tohumlar da kabul edilsin (default_rng yalnızca negatif olmayanı alır)
    return np.random.default_rng(int(seed) & 0xFFFFFFFFFFFFFFFF)


def _mono(x) -> np.ndarray:
    """Herhangi bir diziyi tek boyutlu, sonlu float32 diziye çevirir (çok kanallıysa ortalama alır)."""
    if x is None:
        return np.zeros(0, dtype=np.float32)
    a = np.asarray(x, dtype=np.float32)
    if a.ndim > 1:
        a = np.squeeze(a)
        if a.ndim > 1:
            # (örnek, kanal) ya da (kanal, örnek): kısa eksen kanal eksenidir
            a = a.mean(axis=1 if a.shape[0] >= a.shape[1] else 0)
    a = a.reshape(-1)
    if a.size and not np.all(np.isfinite(a)):
        a = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    return np.ascontiguousarray(a, dtype=np.float32)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0


def _db(v: float) -> float:
    return max(SILENCE_DB, 20.0 * math.log10(v)) if v > 0 else SILENCE_DB


def _ffmpeg_ok() -> bool:
    """ffmpeg kullanılabilir mi (testlerde yedek yolu denemek için değiştirilebilir)."""
    return has_ffmpeg()


# ---------- 1) duraklama planı ----------

_LEADING_NONWORD = re.compile(r"^[\W_]+")
_WORD = re.compile(r"\w+")
_CIRCUMFLEX = str.maketrans("âîû", "aiu")


def _starts_with_conjunction(text: str | None) -> bool:
    """Metin (baştaki tırnak/tire atlanarak) Türkçe bir bağlaç/edat öbeğiyle mi başlıyor?"""
    if not text:
        return False
    s = _LEADING_NONWORD.sub("", tr_lower(str(text)).translate(_CIRCUMFLEX))
    toks = tuple(_WORD.findall(s[:64]))[:3]
    return any(toks[: len(c)] == c for c in _CONJ_TOKENS)


def _punct_of_text(s: str) -> str:
    s = s.rstrip().rstrip("'\"»”’)").rstrip()
    if s.endswith(("...", "…")):
        return "..."
    if s.endswith("!"):
        return "!"
    if s.endswith("?"):
        return "?"
    return ""


def _punct(ch: dict) -> str:
    """Parçanın cümle sonu noktalaması: "!" | "?" | "..." | "" (verilmemişse metinden çıkarılır)."""
    p = ch.get("punct")
    if p is None:
        return _punct_of_text(str(ch.get("text") or ""))
    p = str(p).strip()
    if p in ("!", "?", "...", ""):
        return p
    return _punct_of_text(p)


def _next_text(chunks: list[dict], i: int) -> str | None:
    """Sonraki cümlenin metni. "next_text" anahtarı varsa o geçerlidir (None/boş = son parça);
    anahtar hiç yoksa listedeki bir sonraki parçanın metni kullanılır."""
    ch = chunks[i]
    if "next_text" in ch:
        nt = ch.get("next_text")
    else:
        nt = chunks[i + 1].get("text") if i + 1 < len(chunks) else None
    if nt is None:
        return None
    nt = str(nt).strip()
    return nt or None


def plan_pauses(chunks: list[dict], pause_scale: float = 1.0, seed: int | None = None) -> list[int]:
    """Her parçadan SONRAKİ duraklamayı (ms) bağlama göre planlar.

    chunks[i] = {"text", "punct" ("!"|"?"|"..."|""), "emotion", "pause_after_ms" (temel değer; motor duygu
    çarpanını zaten uygulamış olabilir, burada duyguya tekrar bakılmaz), "paragraph_end": bool,
    "next_text": str|None}.

    Kurallar (çarpımsal): sonraki cümle bağlaçla başlıyorsa ×0.65; soru ve sonraki cümle ≤ 40 karakterse ×0.8;
    bu cümle > 140 karakterse ×1.15, < 15 karakterse ×0.85; "..." için ek çarpan yok; pause_scale (0.5–2.0'a
    sıkıştırılır); ±%12 titreşim (seed verilirse belirlenimci). Paragraf sonu en az 600 ms. Sonuç 60–2500 ms;
    sonraki metin yoksa (son parça) 0.
    """
    n = len(chunks)
    if n == 0:
        return []
    scale = min(PAUSE_SCALE_MAX, max(PAUSE_SCALE_MIN, _to_float(pause_scale, 1.0)))
    # Her parça için sırayla bir çekiliş: aynı tohum + aynı parça sayısı → aynı titreşim dizisi
    jitter = _rng(seed).uniform(-JITTER, JITTER, size=n)
    out: list[int] = []
    for i, ch in enumerate(chunks):
        nxt = _next_text(chunks, i)
        if nxt is None:
            out.append(0)
            continue
        text = str(ch.get("text") or "").strip()
        punct = _punct(ch)
        para = bool(ch.get("paragraph_end"))
        base = _to_float(ch.get("pause_after_ms"))
        if base is None:
            base = float(_PARAGRAPH_PAUSE_MS if para else _DEFAULT_PAUSE_MS.get(punct, _DEFAULT_PAUSE_MS[""]))
        mul = 1.0
        if _starts_with_conjunction(nxt):
            mul *= CONJ_FACTOR
        if punct == "?" and len(nxt) <= QA_MAX_CHARS:
            mul *= QA_FACTOR
        if len(text) > LONG_CHARS:
            mul *= LONG_FACTOR
        elif 0 < len(text) < SHORT_CHARS:
            mul *= SHORT_FACTOR
        ms = max(0.0, base) * mul * scale * (1.0 + float(jitter[i]))
        if para:
            ms = max(ms, float(PARAGRAPH_MIN_MS))
        ms = min(float(PAUSE_MAX_MS), max(float(PAUSE_MIN_MS), ms))
        out.append(int(round(ms)))
    return out


# ---------- 2) nefes planı ----------

def _emotion(ch: dict) -> str:
    e = ch.get("emotion")
    return tr_lower(str(e)).strip() if e else ""


def _estimate_duration(text: str | None) -> float:
    """Süre bilinmiyorsa kaba tahmin: Türkçe ortalama ~5.5 hece/sn."""
    return count_syllables_text(str(text or "")) / 5.5


def _durations(chunks: list[dict], durations_s) -> list[float]:
    durs = list(durations_s) if durations_s is not None else []
    out = []
    for i, ch in enumerate(chunks):
        d = _to_float(durs[i]) if i < len(durs) else None
        out.append(d if d is not None and d >= 0 else _estimate_duration(ch.get("text")))
    return out


def _content_seed(chunks: list[dict], durs: list[float]) -> int:
    """Tohum verilmediğinde plan yine belirlenimci olsun: içerikten türetilmiş tohum."""
    h = zlib.crc32("\x1f".join(str(c.get("text") or "") for c in chunks).encode("utf-8"))
    return zlib.crc32(np.round(np.asarray(durs, dtype=np.float64), 3).tobytes(), h)


def plan_breaths(chunks: list[dict], durations_s: list[float], min_gap_s: float = 6.0,
                 seed: int | None = None) -> list[bool]:
    """breaths[i] = i. parçadan ÖNCE nefes alınsın mı. Belirlenimci (tohum yoksa içerikten türetilir).

    - İlk parça: False. Fısıltı parçalarının önüne nefes konmaz (sentetik nefes fısıltıyla uyumsuz).
    - Paragraf başı (önceki parça paragraph_end): True.
    - Son nefesten beri konuşma ≥ min_gap_s ve bu parça ≥ 2.5 sn: True. Önceki parça "!" ile bitiyorsa ya da
      duygu heyecanlıysa aralık ×0.8 (heyecanlı konuşmada nefes daha sık).
    - "..." sonrası (son nefesten beri ≥ 1.5 sn konuşulduysa) yüksek olasılıkla (%75) True.
    - Emniyet: 2 × aralık boyunca hiç nefes alınmadıysa ≥ 1 sn'lik parçadan önce de True.
    durations_s eksik/geçersizse süre metinden tahmin edilir.
    """
    n = len(chunks)
    if n == 0:
        return []
    durs = _durations(chunks, durations_s)
    gap0 = max(0.0, _to_float(min_gap_s, 6.0))
    draws = _rng(seed if seed is not None else _content_seed(chunks, durs)).random(n)
    plan = [False] * n
    since = 0.0
    for i in range(1, n):
        since += durs[i - 1]
        prev, cur = chunks[i - 1], chunks[i]
        if _emotion(cur) in _WHISPER:
            continue
        prev_punct = _punct(prev)
        gap = gap0
        if prev_punct == "!" or _emotion(prev) in _EXCITED or _emotion(cur) in _EXCITED:
            gap *= EXCITED_GAP_FACTOR
        if bool(prev.get("paragraph_end")):
            want = True
        elif since >= gap and durs[i] >= BREATH_MIN_PIECE_S:
            want = True
        elif since >= 2.0 * gap and durs[i] >= 1.0:
            want = True
        elif prev_punct == "..." and since >= 1.5 and draws[i] < ELLIPSIS_BREATH_P:
            want = True
        else:
            want = False
        if want:
            plan[i] = True
            since = 0.0
    return plan


# ---------- 3) sentetik nefes ----------

def _breath_envelope(n: int, rise_frac: float = 0.35) -> np.ndarray:
    """Asimetrik zarf: hızlı yükseliş (~%35) + yavaş düşüş, ikisi de yükseltilmiş kosinüs; uçlar 0."""
    rise = min(n - 1, max(1, int(round(n * rise_frac))))
    fall = n - rise
    env = np.empty(n, dtype=np.float64)
    env[:rise] = 0.5 - 0.5 * np.cos(np.pi * np.arange(rise) / max(1, rise))
    env[rise:] = 0.5 + 0.5 * np.cos(np.pi * np.arange(fall) / max(1, fall - 1))
    return env


def synth_breath(sr: int, duration_ms: int = 320, level_db: float = -34.0,
                 seed: int | None = None) -> np.ndarray:
    """Gürültü tabanlı gerçekçi sentetik nefes (float32, tam duration_ms uzunluğunda, tepe < 0.3).

    İki bağımsız beyaz gürültü 300–4000 Hz bant geçirenden (2. derece Butterworth) geçirilir; biri 800 Hz'de
    (ağız boşluğu), diğeri 1.8 kHz'de hafif rezonansla renklendirilir ve yavaş değişen bir ağırlıkla karıştırılır
    (nefesin tınısı boyunca hafif sıklık dalgalanması). Asimetrik zarf uygulanır, RMS level_db'ye getirilir.
    """
    sr = int(sr)
    n = int(round(sr * _to_float(duration_ms, 0.0) / 1000.0)) if sr > 0 else 0
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    rng = _rng(seed)
    pad = min(2048, max(64, n // 4))      # filtrenin oturma payı: baştaki geçici yanıt atılır
    m = n + pad
    hi = min(4000.0, 0.45 * sr)
    lo = min(300.0, 0.5 * hi)
    sos = signal.butter(2, [lo, hi], btype="bandpass", fs=sr, output="sos")
    a = signal.sosfilt(sos, rng.standard_normal(m))
    b = signal.sosfilt(sos, rng.standard_normal(m))
    if 800.0 < 0.4 * sr:                  # alçak bölgede hafif 800 Hz rezonans
        pb, pa = signal.iirpeak(800.0, 2.5, fs=sr)
        a = a + 0.5 * signal.lfilter(pb, pa, a)
    if 1800.0 < 0.4 * sr:                 # ikinci bileşen biraz daha parlak
        pb, pa = signal.iirpeak(1800.0, 2.0, fs=sr)
        b = b + 0.4 * signal.lfilter(pb, pa, b)
    a, b = a[pad:], b[pad:]
    a /= max(_rms(a), 1e-12)
    b /= max(_rms(b), 1e-12)
    t = np.arange(n) / sr
    w = 0.5 + 0.35 * np.sin(2 * np.pi * rng.uniform(2.0, 4.0) * t + rng.uniform(0.0, 2 * np.pi))
    y = (np.sqrt(w) * a + np.sqrt(1.0 - w) * b) * _breath_envelope(n)
    r = _rms(y)
    if r > 0:
        y *= db_to_amp(_to_float(level_db, -34.0)) / r
    peak = float(np.max(np.abs(y)))
    if peak >= 0.3:                       # tepe güvencesi seviyeden önce gelir
        y *= 0.29 / peak
    return y.astype(np.float32)


# ---------- 4) oda tonu ----------

def _loop_to_length(f: np.ndarray, n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Kısa bir örneği rastgele ofsetten başlayarak n örneğe döngüler.

    Döngü gövdesinin başı, örneğin son 20 ms'i ile ilk 20 ms'inin eşit güçlü (sin/cos) çapraz geçişidir; böylece
    gövde art arda eklendiğinde eklem yerinde sıçrama olmaz.
    """
    f = np.asarray(f, dtype=np.float64)
    length = f.size
    xf = min(int(sr * _LOOP_XFADE_MS / 1000), length // 3)
    if xf >= 2:
        t = (np.arange(xf) + 0.5) / xf
        body = f[: length - xf].copy()
        body[:xf] = f[length - xf:] * np.cos(0.5 * np.pi * t) + f[:xf] * np.sin(0.5 * np.pi * t)
    else:
        body = f.copy()
    period = body.size
    off = int(rng.integers(0, period))
    reps = (off + n) // period + 1
    return np.tile(body, reps)[off: off + n]


def _pink_noise(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Birim RMS'li pembe gürültü (1/f güç, FFT ile şekillendirme), 80 Hz altı kesik."""
    seg = n if n <= int(_PINK_MAX_S * sr) else int(_PINK_MAX_S * sr)
    m = sfft.next_fast_len(max(seg, 2), real=True)
    spec = sfft.rfft(rng.standard_normal(m))
    f = sfft.rfftfreq(m, 1.0 / sr)
    shape = np.zeros_like(f)
    band = f >= 80.0
    shape[band] = 1.0 / np.sqrt(f[band])
    ramp = (f >= 80.0) & (f < 100.0)       # 80–100 Hz yumuşak geçiş (keskin kenar çınlamasın)
    shape[ramp] *= 0.5 - 0.5 * np.cos(np.pi * (f[ramp] - 80.0) / 20.0)
    y = sfft.irfft(spec * shape, n=m)[:seg]
    if seg < n:
        y = _loop_to_length(y, n, sr, rng)
    r = _rms(y)
    if r <= 1e-12:                         # aşırı kısa (frekans kutusu yok): beyaz gürültüye düş
        y = rng.standard_normal(n)
        r = _rms(y)
    return y / r


def _room_bed(n: int, sr: int, floor_sample, level_db: float, rng: np.random.Generator) -> np.ndarray:
    """Kenarları yumuşatılmamış oda tonu yatağı (float64)."""
    f = _mono(floor_sample)
    if f.size >= 16:
        f = f.astype(np.float64) - float(np.mean(f))
        r = _rms(f)
        if r > 1e-7:
            # Seviyeyi hedefe getir; ama çok temiz bir tabanı en fazla +6 dB yükselt (tıslamayı büyütme)
            gain_db = min(level_db - _db(r), ROOM_TONE_MAX_BOOST_DB)
            return _loop_to_length(f, n, sr, rng) * db_to_amp(gain_db)
    # örnek yok / kullanışsız (çok kısa ya da dijital sessizlik) → pembe gürültü
    return _pink_noise(n, sr, rng) * db_to_amp(level_db)


def make_room_tone(n_samples: int, sr: int, floor_sample: np.ndarray | None = None, level_db: float = -58.0,
                   seed: int | None = None) -> np.ndarray:
    """n_samples uzunluğunda "oda tonu" (float32): sessizlik yerine konacak sürekli, düşük seviyeli taban.

    floor_sample verilmişse (ör. referans kaydın en sessiz bölgesi) rastgele ofsetten başlayarak döngülenir,
    eklemlerde 20 ms çapraz geçiş yapılır ve RMS level_db'ye getirilir (taban daha sessizse en fazla +6 dB
    yükseltilir). Verilmemişse (ya da kullanışsızsa) 80 Hz altı kesik pembe gürültü üretilir. Baş/son yumuşatılır.
    """
    n = int(n_samples) if n_samples else 0
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    sr = int(sr)
    bed = _room_bed(n, sr, floor_sample, _to_float(level_db, ROOM_TONE_DB), _rng(seed))
    return fade(bed.astype(np.float32), sr, _EDGE_FADE_MS)


# ---------- 5) doğal birleştirme ----------

def _breath_instance(breath, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Yerleştirilecek tek bir nefes. Her yerleşimde ufak fark (aynı nefesin birebir tekrarı duyulmasın)."""
    if breath is None:
        return synth_breath(sr, int(rng.integers(260, 381)), -34.0 + float(rng.uniform(-2.0, 2.0)),
                            seed=int(rng.integers(0, 2**31)))
    b = _mono(breath)[: int(sr * _MAX_BREATH_S)]
    if b.size == 0:
        return b
    b = fade(b, sr, 8) * np.float32(db_to_amp(float(rng.uniform(-1.5, 1.5))))
    return b.astype(np.float32)


def join_natural(pieces: list[np.ndarray], pauses_ms: list[int], sr: int, *, room_tone: np.ndarray | None = None,
                 breath: np.ndarray | None = None, breath_plan: list[bool] | None = None,
                 crossfade_ms: int = 15) -> np.ndarray:
    """Parçaları doğal duraklamalarla birleştirir (float32, tek boyutlu).

    - Her parçanın başı/sonu audio.fade ile crossfade_ms (en az 2 ms) yumuşatılır; parçalar arasına
      pauses_ms[i] kadar boşluk konur (eksik/negatif değer 0 sayılır; plan_pauses çıktısı doğrudan verilebilir).
    - room_tone verilirse boşluklar sıfır yerine oda tonuyla dolar: room_tone bir örnektir, make_room_tone
      kuralıyla (-58 dBFS, en fazla +6 dB yükseltme) tüm çıktı boyunca TEK ve sürekli bir yatağa döngülenir;
      parça kenarlarında parçanın fade'iyle tümleyen rampalarla çapraz geçer, parçanın içine girmez.
      room_tone None → boşluklar tam sıfır.
    - breath_plan[i] True ise i. parçanın önündeki boşluğun ortasına nefes eklenir (oda tonunun üstüne);
      boşluk nefes + 120 ms'den kısaysa o kadar uzatılır. breath None ise her yerleşim için sentetik nefes üretilir.
    Uzunluk = sum(parçalar) + sum(boşluklar). Sonuç belirlenimcidir (girdi boyutlarından türetilen tohum).
    """
    sr = int(sr)
    parts = [_mono(p) for p in (pieces or [])]
    n = len(parts)
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    fade_ms = max(2, int(round(_to_float(crossfade_ms, 15.0))))
    if n == 1:
        return fade(parts[0], sr, fade_ms).astype(np.float32)

    pauses = list(pauses_ms) if pauses_ms is not None else []
    gaps = []
    for i in range(n - 1):
        ms = max(0.0, _to_float(pauses[i], 0.0)) if i < len(pauses) else 0.0
        gaps.append(int(round(sr * ms / 1000.0)))
    lens = [p.size for p in parts]
    rng = np.random.default_rng(zlib.crc32(np.asarray(lens + gaps, dtype=np.int64).tobytes()))

    # Nefesler: önce boşlukları gerekirse uzat (toplam uzunluk buna göre belirlenir)
    breaths: dict[int, np.ndarray] = {}
    plan = list(breath_plan) if breath_plan is not None else []
    pad = int(round(sr * BREATH_PAD_MS / 1000.0))
    for i in range(1, min(n, len(plan))):
        if not plan[i]:
            continue
        b = _breath_instance(breath, sr, rng)
        if b.size == 0:
            continue
        gaps[i - 1] = max(gaps[i - 1], b.size + pad)
        breaths[i - 1] = b

    total = sum(lens) + sum(gaps)
    out = np.zeros(total, dtype=np.float32)
    starts: list[int] = []
    pos = 0
    for i, p in enumerate(parts):
        starts.append(pos)
        out[pos: pos + p.size] = fade(p, sr, fade_ms)
        pos += p.size + (gaps[i] if i < n - 1 else 0)

    if room_tone is not None:
        # Maske: boşlukta 1, parça içinde 0; parça kenarında audio.fade ile aynı uzunlukta tümleyen rampa
        mask = np.ones(total, dtype=np.float32)
        for i, (s, length) in enumerate(zip(starts, lens)):
            mask[s: s + length] = 0.0
            k = min(length // 2, int(sr * fade_ms / 1000))
            if k <= 0:
                continue
            ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)
            if i > 0:                 # parça girişi: parça 0→1, oda tonu 1→0
                mask[s: s + k] = ramp[::-1]
            if i < n - 1:             # parça çıkışı: parça 1→0, oda tonu 0→1
                mask[s + length - k: s + length] = ramp
        bed = _room_bed(total, sr, room_tone, ROOM_TONE_DB, rng)
        out += (bed * mask).astype(np.float32)

    for gi, b in breaths.items():
        g0 = starts[gi] + lens[gi]
        off = g0 + (gaps[gi] - b.size) // 2
        out[off: off + b.size] += b
    return out


# ---------- ffmpeg yardımcıları ----------

def _timeout(n: int, sr: int) -> float:
    return 60.0 + 3.0 * n / max(1, sr)


def _ffmpeg_filter(wav: np.ndarray, sr: int, afilter: str) -> np.ndarray:
    """Diziyi ffmpeg ses filtresinden geçirir (32-bit kayan nokta WAV ile; kırpma/nicemleme yok).

    Hata olursa RuntimeError fırlatır (çağıran yedeğe düşer).
    """
    x = _mono(wav)
    if not afilter:
        return x
    with tempfile.TemporaryDirectory(prefix="sesklon-prosody-") as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        sf.write(str(src), x, sr, subtype="FLOAT")
        cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
               "-af", afilter, "-ar", str(sr), "-ac", "1", "-c:a", "pcm_f32le", str(dst)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=_timeout(x.size, sr))
        if r.returncode != 0 or not dst.exists():
            raise RuntimeError(f"ffmpeg filtresi başarısız ({afilter}): {r.stderr.strip()[-300:]}")
        out, _ = sf.read(str(dst), dtype="float32", always_2d=False)
    return _mono(out)


def _ffmpeg_stderr(wav: np.ndarray, sr: int, afilter: str) -> str:
    """Filtreyi çıktı üretmeden çalıştırır (-f null) ve ölçüm için stderr'i döndürür."""
    x = _mono(wav)
    with tempfile.TemporaryDirectory(prefix="sesklon-prosody-") as td:
        src = Path(td) / "in.wav"
        sf.write(str(src), x, sr, subtype="FLOAT")
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-i", str(src), "-af", afilter, "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=_timeout(x.size, sr))
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg ölçümü başarısız ({afilter}): {r.stderr.strip()[-300:]}")
    return r.stderr


@functools.lru_cache(maxsize=1)
def _ffmpeg_filter_list() -> str:
    try:
        return subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15).stdout
    except Exception:  # noqa: BLE001
        return ""


def _has_filter(name: str) -> bool:
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", _ffmpeg_filter_list(), re.MULTILINE) is not None


_NUM = r"(-?inf|-?\d+(?:\.\d+)?)"


def _ebur128_stats(wav: np.ndarray, sr: int, prechain: list[str], true_peak: bool = False) -> dict | None:
    """ffmpeg ebur128 özetini ayrıştırır → {"I", "thresh", "LRA"[, "TP"]} (ölçülemeyen değer None).

    loudnorm'un ölçüm geçişiyle aynı değerleri verir ama ~4–8 kat hızlıdır (192 kHz'e çıkmaz).
    """
    af = ",".join(prechain + ["ebur128=framelog=quiet" + (":peak=true" if true_peak else "")])
    err = _ffmpeg_stderr(wav, sr, af)
    k = err.rfind("Summary:")
    if k < 0:
        return None
    s = err[k:]
    m_i = re.search(rf"Integrated loudness:\s*I:\s*{_NUM}\s*LUFS\s*Threshold:\s*{_NUM}\s*LUFS", s)
    if not m_i:
        return None
    m_lra = re.search(rf"Loudness range:\s*LRA:\s*{_NUM}\s*LU\b", s)
    out = {"I": _to_float(m_i.group(1)), "thresh": _to_float(m_i.group(2)),
           "LRA": _to_float(m_lra.group(1)) if m_lra else None}
    if true_peak:
        m_tp = re.search(rf"True peak:\s*Peak:\s*{_NUM}\s*dBFS", s)
        out["TP"] = _to_float(m_tp.group(1)) if m_tp else None
    return out


def _lufs_ffmpeg(wav: np.ndarray, sr: int) -> float | None:
    """ffmpeg ebur128 özetinden tümleşik ses yüksekliği."""
    st = _ebur128_stats(wav, sr, [])
    v = st.get("I") if st else None
    # ebur128 ölçülemeyen (sessiz/çok kısa) girdide -70 verir
    return v if v is not None and v > _ABS_GATE_LUFS + 0.05 else None


# ---------- 7) ses yüksekliği ölçümü ----------

@functools.lru_cache(maxsize=16)
def _k_weighting_sos(sr: int) -> np.ndarray:
    """ITU-R BS.1770 K-ağırlıklama (raf +4 dB @ ~1.68 kHz + 38 Hz yüksek geçiren), her örnekleme hızı için.

    Katsayılar libebur128/ffmpeg ile aynı biçimde analog prototipten türetilir; 48 kHz'de standarttaki
    katsayıları birebir verir.
    """
    f0, gain_db, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / sr)
    vh = 10.0 ** (gain_db / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    shelf = [(vh + vb * k / q + k * k) / a0, 2.0 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0,
             1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + k / q + k * k
    highpass = [1.0, -2.0, 1.0, 1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]
    return np.array([shelf, highpass], dtype=np.float64)


def _lufs_numpy(wav: np.ndarray, sr: int) -> float | None:
    """Saf Python BS.1770-4 tümleşik ses yüksekliği (LUFS, tek kanal).

    K-ağırlıklama → 400 ms bloklar (%75 örtüşme) → mutlak (-70 LUFS) ve göreli (-10 LU) kapı →
    -0.691 + 10·log10(ortalama güç). 400 ms'den kısa girdide kapısız ortalama. Sessizse None.
    """
    x = _mono(wav).astype(np.float64)
    sr = int(sr)
    if x.size == 0 or sr <= 0:
        return None
    p = np.square(signal.sosfilt(_k_weighting_sos(sr), x))
    block, hop = int(round(0.4 * sr)), int(round(0.1 * sr))
    if p.size < block or block <= 0 or hop <= 0:
        z = float(np.mean(p))
        if z <= 0:
            return None
        v = -0.691 + 10.0 * math.log10(z)
        return v if v > _ABS_GATE_LUFS else None
    cs = np.concatenate(([0.0], np.cumsum(p)))
    st = np.arange(0, p.size - block + 1, hop)
    z = (cs[st + block] - cs[st]) / block
    z = np.maximum(z, 0.0)                 # birikimli toplamın yuvarlama hatası
    with np.errstate(divide="ignore"):
        lk = -0.691 + 10.0 * np.log10(z)
    gate = lk > _ABS_GATE_LUFS
    if not gate.any():
        return None
    rel = -0.691 + 10.0 * math.log10(float(z[gate].mean())) - 10.0
    gate &= lk > rel
    if not gate.any():
        return None
    return -0.691 + 10.0 * math.log10(float(z[gate].mean()))


def measure_loudness(wav: np.ndarray, sr: int) -> dict:
    """{"lufs": float|None, "peak_dbfs": float, "rms_dbfs": float} — değerler 2 ondalığa yuvarlanır.

    lufs ffmpeg (ebur128) ile ölçülür; ffmpeg yoksa/başarısızsa ya da girdi 400 ms'den kısaysa saf Python
    BS.1770 yedeği kullanılır. Sessiz girdide lufs None, dBFS değerleri -120.
    """
    sr = int(sr)
    x = _mono(wav)
    if x.size == 0:
        return {"lufs": None, "peak_dbfs": SILENCE_DB, "rms_dbfs": SILENCE_DB}
    peak = _db(float(np.max(np.abs(x))))
    rms = _db(_rms(x))
    lufs = None
    if x.size >= int(0.4 * sr) and _ffmpeg_ok():
        try:
            lufs = _lufs_ffmpeg(x, sr)
        except Exception as e:  # noqa: BLE001
            log.debug("ffmpeg ses yüksekliği ölçümü başarısız, saf Python yedeği: %s", e)
    if lufs is None:
        lufs = _lufs_numpy(x, sr)
    return {"lufs": None if lufs is None else round(lufs, 2), "peak_dbfs": round(peak, 2), "rms_dbfs": round(rms, 2)}


# ---------- 6) mastering ----------

def _highpass(x: np.ndarray, sr: int, hz) -> np.ndarray:
    """2. derece Butterworth yüksek geçiren (ffmpeg'in highpass varsayılanıyla aynı eğim)."""
    hz = _to_float(hz, 0.0)
    if hz <= 0 or hz >= 0.45 * sr:
        return x.astype(np.float32)
    sos = signal.butter(2, hz, btype="highpass", fs=sr, output="sos")
    return signal.sosfilt(sos, x.astype(np.float64)).astype(np.float32)


def _fit(y: np.ndarray, n: int, true_peak_db: float) -> np.ndarray:
    """Uzunluğu n'ye kırp/doldur; tepe sınırı aşılıyorsa tüm sinyali ölçekle."""
    y = _mono(y)
    if y.size > n:
        y = y[:n]
    elif y.size < n:
        y = np.concatenate([y, np.zeros(n - y.size, dtype=np.float32)])
    limit = db_to_amp(true_peak_db)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > limit:
        y = y * np.float32(limit / peak)
    return y.astype(np.float32)


def _master_prechain(sr: int, highpass_hz, deess: bool, warmth: bool) -> list[str]:
    nyq = sr / 2.0
    chain: list[str] = []
    hp = _to_float(highpass_hz, 0.0)
    if 0 < hp < 0.45 * sr:
        chain.append(f"highpass=f={hp:g}")
    if deess:
        if _has_filter("deesser"):
            chain.append("deesser=i=0.4:m=0.5:f=0.5")
        elif 7000.0 * 1.2 < nyq:
            chain.append("equalizer=f=7000:t=q:w=1.5:g=-2")      # dinamik de-esser yoksa statik -2 dB
    if warmth:
        chain.append("equalizer=f=180:t=q:w=1:g=1")              # hafif sıcaklık
        if 3000.0 * 1.2 < nyq:
            chain.append("equalizer=f=3000:t=q:w=1.2:g=0.8")     # netlik
    return chain


def _true_peak_limiter(sr: int, tp_db: float) -> list[str]:
    """Tek tepe sınırlayıcı: alimiter, ara-örnek (true peak) tepelerini yakalamak için 4×/2× aşırı örneklenmiş
    hızda çalışır. level=0: otomatik seviye kapalı (yoksa çıkışı 0 dBFS'e çeker); latency=1: gecikme telafisi
    (çıktı girdiyle örnek örnek hizalı kalır). Geri örnekleme taşmasına karşı 0.2 dB pay bırakılır."""
    up = sr * (4 if sr <= 48000 else 2)
    limit = min(1.0, max(0.0625, db_to_amp(tp_db - _LIMITER_MARGIN_DB)))
    return [f"aresample={up}", f"alimiter=limit={limit:.6f}:attack=5:release=60:level=0:latency=1"]


def _master_ffmpeg(x: np.ndarray, sr: int, target: float, tp: float, highpass_hz, deess: bool,
                   warmth: bool) -> np.ndarray:
    """highpass → de-ess → sıcaklık/netlik EQ → EBU R128 kazancı → (gerekirse) gerçek-tepe sınırlayıcı.

    Çift geçiş: önce aynı ön zincir + ebur128 ile tümleşik ses yüksekliği ve gerçek tepe ölçülür, sonra tek bir
    doğrusal kazanç (hedef - ölçülen) uygulanır; kazanç sonrası tepe hedefi aşacaksa sınırlayıcı eklenir.
    loudnorm'un dinamik moduna göre ~3 kat hızlı, hedefe daha yakın ve sesin dinamiğini (duyguya bağlı fısıltı/
    vurgu farklarını) sıkıştırmaz. Ölçüm ya da zincir başarısız olursa tek geçişli loudnorm'a düşülür.
    """
    pre = _master_prechain(sr, highpass_hz, deess, warmth)
    try:
        st = _ebur128_stats(x, sr, pre, true_peak=True)
    except Exception as e:  # noqa: BLE001
        log.info("ebur128 ölçümü başarısız, tek geçişli loudnorm'a düşülüyor: %s", e)
        st = None
    if st and st.get("I") is not None and st["I"] > _ABS_GATE_LUFS + 0.05:
        gain = target - st["I"]
        chain = pre + [f"volume={gain:.3f}dB"]
        if st.get("TP") is None or st["TP"] + gain > tp - 0.1:
            chain += _true_peak_limiter(sr, tp)
        chain.append(f"aresample={sr}")
        try:
            return _ffmpeg_filter(x, sr, ",".join(chain))
        except Exception as e:  # noqa: BLE001  (ör. alimiter 'latency' seçeneği olmayan eski ffmpeg)
            log.info("kazanç + sınırlayıcı zinciri başarısız, loudnorm'a düşülüyor: %s", e)
    # loudnorm içeride 192 kHz'e çıkabilir: aresample + -ar ile asıl örnekleme hızına dönülür.
    return _ffmpeg_filter(x, sr, ",".join(pre + [f"loudnorm=I={target:g}:TP={tp:g}:LRA=11", f"aresample={sr}"]))


def master(wav: np.ndarray, sr: int, *, target_lufs: float = -16.0, true_peak_db: float = -1.5,
           highpass_hz: int = 60, deess: bool = True, warmth: bool = True) -> np.ndarray:
    """Yayın kalitesinde son işlem: tutarlı ses yüksekliği ve güvenli tepe (float32, girdiyle aynı uzunluk).

    ffmpeg varsa zincir: highpass → de-ess (deesser; yoksa 7 kHz'de statik -2 dB) → hafif sıcaklık/netlik EQ →
    EBU R128 normalizasyonu (ebur128 ile ölç, tek doğrusal kazanç) → gerekirse tek gerçek-tepe sınırlayıcı
    (bkz. _master_ffmpeg; başarısızlıkta tek geçişli loudnorm=I:TP:LRA=11). ffmpeg yoksa ya da hata olursa
    yedek: highpass + RMS normalize (target_lufs - 2 dBFS, varsayılanla -18) + tepe sınırı. 0.5 sn'den kısa
    girdide ses yüksekliği ölçümü anlamsız: yalnızca highpass + RMS. Sessiz (ölçülemeyen) girdi yükseltilmez.
    Son güvence: max|y| ≤ db_to_amp(true_peak_db).
    """
    sr = int(sr)
    x = _mono(wav)
    n = x.size
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    target = min(-5.0, max(-70.0, _to_float(target_lufs, -16.0)))   # loudnorm'un kabul ettiği aralıklar
    tp = min(0.0, max(-9.0, _to_float(true_peak_db, -1.5)))
    if n < int(0.5 * sr):
        y = _highpass(x, sr, highpass_hz)
        if _rms(y) > db_to_amp(_ABS_GATE_LUFS):
            y = rms_normalize(y, target - 2.0, tp)
        return _fit(y, n, tp)
    if _lufs_numpy(x, sr) is None:
        # sessizlik / gürültü tabanı: normalize etmek yalnızca tıslamayı büyütür
        return _fit(_highpass(x, sr, highpass_hz), n, tp)
    if _ffmpeg_ok():
        try:
            return _fit(_master_ffmpeg(x, sr, target, tp, highpass_hz, deess, warmth), n, tp)
        except Exception as e:  # noqa: BLE001
            log.warning("ffmpeg mastering başarısız, RMS yedeğine geçiliyor: %s", e)
    y = _highpass(x, sr, highpass_hz)
    return _fit(rms_normalize(y, target - 2.0, tp), n, tp)
