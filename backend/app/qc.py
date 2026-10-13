"""Üretilen parçanın kalite kontrolü (QC) — otoregresif TTS halüsinasyonlarını yakalayan "kulak".

Chatterbox gibi otoregresif modeller bazen cümleyi uzatır, sözcük ya da cümle tekrar eder, ortada takılır (uzun
sessiz boşluk), sonuna uzun sessizlik ekler, vızıltı üretir ya da cümleyi yarım keser. Bu modül bir parçanın
ses + metin çiftini ölçer, 0–100 arası puanlar ve ne yapılacağına karar verir: kabul et, farklı tohumla yeniden
üret, daha kararlı ayarlarla yeniden üret ya da kırp. Sözleşme: ``docs/SOZLESME2.md`` bölüm 5.

    check_chunk(wav, sr, text, *, expected_cps=None) -> dict
    estimate_cps(samples) -> float | None
    trim_tail(wav, sr, max_tail_ms=250) -> np.ndarray
    trim_head(wav, sr, max_head_ms=150) -> np.ndarray
    pick_best(reports) -> int
    summarize(reports) -> dict
    apply_trim(wav, sr, report=None) -> np.ndarray      # "trim" kararını uygular (ek yardımcı)

Ölçüm yöntemleri (özet):

* Çerçeveleme: 20 ms'lik kareler, kare RMS (dBFS). -45 dBFS altı "sessiz" kare. Konuşma bölgesi = ilk ve son
  sesli kare arası (``audio.trim_silence`` ile aynı hesap, pay yok). Baş/son sessizlik bu bölgenin dışıdır.
* Hız: ``cps`` = ``len(text.strip())`` / konuşma süresi, ``sps`` = ``tr.count_syllables_text`` / konuşma süresi.
  ``expected_cps`` yoksa cps 6–28 (``engine.MIN/MAX_CHARS_PER_SEC``) ve sps 2,5–8,5 birlikte bakılır: ikisi de
  aynı yönde dışarıdaysa kesin (too_long / too_short), yalnız biri dışarıdaysa uyarı (rate, -15). ``expected_cps``
  varsa (geçmişten, bkz. ``estimate_cps``; 4–40 dışı/geçersiz değer yok sayılır) eşikler onun ±%45'i olur ve tek
  başına kesindir. Kısa metinlerde
  (< 27 karakter) uzunluk sınırına en çok 0,6 sn pay eklenir ("Hmm..." gibi ünlemler doğal olarak uzar).
* Sessizlik oranı: konuşma bölgesindeki sessiz karelerin oranı (> 0,45 → silence). Noktalamanın açıkladığı doğal
  duraklamalar (aşağıda) karar için ayrıca düşülür (``unexplained_silence``): "Evet. Hayır. Belki." gibi kısa,
  boşluklu parçalar haksız yere yeniden üretilmesin.
* Boşluklar (dropout): konuşma bölgesinin ilk ve son 150 ms'i dışında, ≥ 250 ms süren sessiz kare dizileri.
  Metindeki iç noktalama doğal duraklama hakkı verir: her virgül/noktalı virgül/iki nokta/tire ≤ 600 ms'lik, her
  cümle içi nokta/ünlem/soru/üç nokta ≤ 1000 ms'lik bir boşluğu "doğal" sayar. Açıklanamayan boşluk başına -15
  (en çok -30); 2 ve üzeri açıklanamayan boşluk → dropout (retry_stable), tek boşluk yalnızca uyarıdır (pause).
  ``metrics["dropouts"]`` ham sayıdır (noktalama düşülmeden).
* Tekrar (repeat), iki yöntem — biri yeterli:
  1. Zarf: 10 ms atlamalı RMS zarfının normalize (yansız) otokorelasyonu; 0,6–3,0 sn gecikmede tepe > 0,8 VE
     zarfın o gecikmeyle kaydırılmış kopyasıyla Pearson korelasyonu > 0,85.
  2. MFCC (librosa, 13 katsayı; c0 atılır, katsayı başına ortalama/varyans normalize, 3 karelik yumuşatma):
     0,6–3,0 sn ötelemede köşegen boyunca kosinüs benzerliği; ±20 ms hizalama toleransıyla, en az
     max(0,5 sn, 0,8 × öteleme) uzunluğunda bir pencerede ortalama > 0,9 (kısmi tekrarları da yakalar).
  MFCC'de iki ucu da sessiz kare çiftleri ortalamaya girmez (sessizlik sessizliğe benzer, tekrar kanıtı değildir),
  pencerenin en az yarısı iki ucu da sesli çift olmalıdır. Yanlış pozitif korumaları: gecikme ≥ 0,6 sn; tekrar
  eden bölümde en az 2 zarf tepesi (dB zarfında ≥ 1 dB, hece) olmalı; aynı bölüm kısa gecikmelerde (0,12–0,6 sn)
  de aynı ölçüde benzer çıkıyorsa bu tekrar değil, hece zarfının periyodikliği ya da durağan sestir (ör. sinüs
  zarflı test sinyalleri); spektrumu durağan (MFCC değişimi çok düşük) seste MFCC yöntemi kullanılmaz. Metnin
  kendisi ≥ 3 heceli bir sözcük dizisini tekrarlıyorsa ("güzel bir gün, güzel bir gün") ve sesteki gecikme bu
  tekrarın ölçülen hece hızındaki karşılığına ±%35 yakınsa tekrar beklenendir, cezalandırılmaz.
  Kalibrasyon (LibriSpeech, 2–12 sn'lik 162 pencere): yanlış pozitif 0; araya eklenmiş 0,7–2,5 sn'lik birebir ya
  da ±%4 gerdirilmiş kopyaların çoğu (çoğunluğu sessizlik olan kopyalar dışında) yakalanır.
* Kırpılma: |x| ≥ 0,985 olan örnek oranı (> 0,001 → clipping, trim: seviye düşürülür).
* Vızıltı (buzz): Welch PSD (Hann, 4096 örnek); 4–8 kHz'de tek bir dar tepe: çevresinin (±50–400 Hz) 90.
  yüzdeliğinden ≥ 15 dB yüksek (yüzdelik taban, konuşmanın harmonik tarağını tek tondan ayırır), -6 dB genişliği
  ≤ 60 Hz, toplam gücün en az -50 dB'i (duyulur) ve sürekli: ≥ 1 sn parçada üç bölümün en az ikisinde de görünür;
  daha kısa parçada (oynak PSD) ≥ 20 dB istenir. Ya da 50/100 Hz şebeke uğultusu: ≥ 1,4 sn parçada ince
  çözünürlüklü PSD'de (≈ 1,5 Hz) -6 dB genişliği ≤ 4,5 Hz, ±8–30 Hz komşularının medyanından ≥ 12 dB yüksek ve
  toplam gücün en az -35 dB'i olan çizgi (perdesi 100 Hz civarındaki erkek sesi birkaç Hz oynar, uğultu sayılmaz).
  Kalibrasyon: gerçek konuşmanın 606 penceresinde ve 1080 gürültü/sentetik örnekte yanlış pozitif 0.
* Kuyruk: son sesli kareden sonraki sessizlik (ms; > 600 → tail, trim).

Puanlama: 100'den düşülür — too_long -40, too_short -35, silence -25, dropout -15/adet (en çok -30), repeat -40,
clipping -10, buzz -20, tail -5, rate (uyarı) -15. Karar: repeat / too_short / silence / too_long → "retry_seed"
(too_long'da konuşma hızı alt sınırın yarısından da düşükse ve tekrar yoksa "trim": fazlalık sessiz bir noktadan
kesilir); dropout / buzz → "retry_stable"; yalnızca tail / clipping → "trim"; aksi halde puan ≥ 60 ise "accept".
``ok`` yalnızca puan eşiğidir (≥ 60); ne yapılacağını ``decision`` söyler. Her gerekçe ``{"code", "message",
"severity", "penalty", "action"}`` taşır: "error" kararı belirler (``action``: retry_seed / retry_stable / trim),
"warn" (rate, pause) yalnızca puanı düşürür.

Tüm sayılar yerleşik Python tipleriyle döner (``json.dumps`` doğrudan çalışır). Boş ya da çok kısa girdi çökmez:
puan 0, karar "retry_seed".
"""
from __future__ import annotations

import math
import warnings
from collections import Counter

import numpy as np
from scipy import signal

from .audio import cut_at_silence, db_to_amp
from .tr import count_syllables, count_syllables_text, tr_lower, words

# ---------- sabitler ----------

FRAME_MS = 20.0                 # sessizlik / boşluk / kuyruk karesi
SILENCE_DB = -45.0              # bu seviyenin (kare RMS, dBFS) altı sessiz
MIN_SPEECH_S = 0.06             # bundan kısa konuşma bölgesi "boş" sayılır
CLIP_LEVEL = 0.985
CLIP_RATIO_MAX = 0.001
SILENCE_RATIO_MAX = 0.45
GAP_MIN_MS = 250.0
EDGE_MS = 150.0                 # konuşmanın ilk/son bu kadarındaki boşluklar sayılmaz
DROPOUT_MIN_COUNT = 2
NATURAL_COMMA_GAP_MS = 600.0    # virgül / noktalı virgül / iki nokta / tire duraklaması üst sınırı
NATURAL_SENTENCE_GAP_MS = 1000.0  # cümle içi nokta / ünlem / soru / üç nokta duraklaması üst sınırı
TAIL_MAX_MS = 600.0

# engine.MIN_CHARS_PER_SEC / MAX_CHARS_PER_SEC ile aynı (motor içe aktarılmaz: döngüsel bağımlılık olmasın)
CPS_MIN, CPS_MAX = 6.0, 28.0
SPS_MIN, SPS_MAX = 2.5, 8.5     # Türkçe tipik 3,5–7 hece/sn
EXPECTED_TOL = 0.45             # expected_cps verilince ±%45
EXPECTED_CPS_RANGE = (4.0, 40.0)
TYPICAL_SPS = 5.0               # mesajlardaki "beklenen süre" için
TYPICAL_CPS = 14.0
VERY_SLOW_FACTOR = 0.5          # cps < alt sınır × bu → aşırı uzun (tekrar yoksa kırpılır)
SHORT_TEXT_SLACK_S = 0.6        # kısa metinlerde uzunluk sınırına eklenen en büyük pay

HOP_S = 0.010                   # zarf / MFCC atlaması
REPEAT_MIN_LAG_S, REPEAT_MAX_LAG_S = 0.6, 3.0
REPEAT_OVERLAP = 1.8            # gecikme ≤ konuşma süresi / 1,8 (tekrar eden bölüm en az bir kez tam görünmeli)
ENV_ACF_MIN = 0.8
ENV_CORR_MIN = 0.85
MFCC_SIM_MIN = 0.9
MFCC_N = 13
MFCC_LAG_TOL = 2                # ±2 kare (±20 ms) hizalama toleransı
MFCC_WIN_MIN_S = 0.5
MFCC_WIN_FRAC = 0.8
MFCC_STATIC_STD = 2.0           # c1–c12 ortalama std bunun altındaysa spektrum durağan sayılır
PERIODIC_MIN_LAG_S = 0.12       # periyodiklik koruması: bu ile REPEAT_MIN_LAG_S arası gecikmeler
PERIODIC_MARGIN = 0.05          # kısa gecikme benzerliği (eşik - bu) kadar yüksekse tekrar sayılmaz
PEAK_MIN_COUNT = 2
PEAK_PROM_DB = 1.0
MFCC_MIN_ACTIVE = 0.5           # pencerede en az bu oranda iki ucu da sesli kare çifti olmalı
TEXT_REPEAT_MIN_SYL = 3
TEXT_REPEAT_LAG_TOL = 0.35      # sesteki gecikme, metindeki tekrarın beklenen gecikmesine ±%35 yakınsa beklenen tekrar

WELCH_NPERSEG = 4096
BUZZ_BAND_HZ = (4000.0, 8000.0)
BUZZ_PROM_DB = 15.0
BUZZ_PROM_SHORT_DB = 20.0       # < 1 sn parçada (az Welch ortalaması, oynak PSD) istenen belirginlik
BUZZ_PERSIST_MIN_S = 1.0        # bundan uzun parçada ton üç bölümün en az ikisinde de görünmeli ("sürekli")
BUZZ_MAX_WIDTH_HZ = 60.0
BUZZ_MIN_REL_DB = -50.0         # tonun gücü toplam gücün bu kadar altından azsa duyulmaz, sayılmaz
HUM_FREQS = (50.0, 100.0)
HUM_PROM_DB = 12.0
HUM_NPERSEG = 16384             # 24 kHz'de ≈ 1,5 Hz çözünürlük
HUM_MAX_WIDTH_HZ = 4.5          # şebeke çizgisi -6 dB'de bundan dar; konuşmanın F0'ı daha geniş
HUM_MIN_S = 1.4                 # daha kısa parçada uğultu F0'dan ayrılamaz, bakılmaz
HUM_MIN_REL_DB = -35.0          # kulak 50 Hz'e az duyarlı: toplam gücün 35 dB altındaki uğultu sayılmaz

PENALTY = {"too_long": 40, "too_short": 35, "silence": 25, "dropout": 15, "repeat": 40, "clipping": 10,
           "buzz": 20, "tail": 5, "rate": 15, "pause": 15}
DROPOUT_MAX_PENALTY = 30
OK_SCORE = 60

ACCEPT, RETRY_SEED, RETRY_STABLE, TRIM = "accept", "retry_seed", "retry_stable", "trim"
RETRY_DECISIONS = (RETRY_SEED, RETRY_STABLE)

_SENTENCE_MARKS = "…!?."


# ---------- küçük yardımcılar ----------

def _tr(v: float, nd: int = 1) -> str:
    """Türkçe ondalık gösterim (virgüllü): 3.25 → '3,3' (nd=1)."""
    return f"{v:.{nd}f}".replace(".", ",").replace("-", "−")


def _as_mono(wav) -> np.ndarray:
    """Her girdiyi tek kanallı float32'ye çevirir; tamsayı PCM ölçeklenir, NaN/sonsuz örnekler sıfırlanır."""
    x = np.asarray(wav if wav is not None else [])
    if x.dtype.kind in "iu":
        info = np.iinfo(x.dtype)
        x = x.astype(np.float64) / float(max(abs(info.min), info.max))
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = np.squeeze(x)
        if x.ndim > 1:  # (örnek, kanal) ya da (kanal, örnek): kısa eksen kanaldır
            x = x.mean(axis=int(np.argmin(x.shape)))
    x = np.nan_to_num(x.reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)
    return x.astype(np.float32)


def _frame_len(sr: int) -> int:
    return max(1, int(round(sr * FRAME_MS / 1000.0)))


def _frame_db(x: np.ndarray, frame: int) -> np.ndarray:
    n = len(x) // frame
    if n <= 0:
        return np.zeros(0)
    f = x[: n * frame].astype(np.float64).reshape(n, frame)
    return 20.0 * np.log10(np.sqrt(np.mean(f * f, axis=1)) + 1e-12)


def _speech_bounds(x: np.ndarray, sr: int) -> tuple[int, int] | None:
    """Konuşma bölgesi (örnek indeksleri, [başlangıç, bitiş)); sesli kare yoksa None."""
    frame = _frame_len(sr)
    loud = np.flatnonzero(_frame_db(x, frame) >= SILENCE_DB)
    if loud.size == 0:
        return None
    return int(loud[0]) * frame, (int(loud[-1]) + 1) * frame


def _ramp(x: np.ndarray, sr: int, ms: float, *, head: bool) -> np.ndarray:
    """Tek uçlu yumuşatma (başta fade-in ya da sonda fade-out); tıkırtı olmasın diye."""
    n = min(len(x) // 2, int(sr * ms / 1000.0))
    if n <= 0:
        return x
    r = np.linspace(0.0, 1.0, n, dtype=np.float32)
    if head:
        x[:n] *= r
    else:
        x[-n:] *= r[::-1]
    return x


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """True dizilerinin (başlangıç, uzunluk) listesi."""
    if mask.size == 0:
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return [(int(s), int(e - s)) for s, e in zip(starts, ends)]


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float(np.dot(a, a)) * float(np.dot(b, b)))
    return float(np.dot(a, b)) / den if den > 0 else 0.0


def _moving_mean(v: np.ndarray, w: int) -> np.ndarray:
    """Uzunluğu len(v) - w + 1 olan kayan pencere ortalaması (w ≥ 1)."""
    c = np.concatenate([[0.0], np.cumsum(v, dtype=np.float64)])
    return (c[w:] - c[:-w]) / w


# ---------- metin ----------

def _pause_slots(text: str) -> tuple[int, int]:
    """Metindeki iç (sonda olmayan) duraklama yerleri: (virgül türü, cümle sonu türü).

    "3,5" / "12:30" / "3.5" gibi boşluksuz işaretler duraklama sayılmaz; "?!" gibi art arda işaretler tek yerdir.
    """
    t = " ".join(text.split()).replace("...", "…")
    alpha = [i for i, c in enumerate(t) if c.isalpha()]
    if not alpha:
        return 0, 0
    last_alpha = alpha[-1]
    comma = sentence = 0
    for i, ch in enumerate(t[:last_alpha]):  # metnin sonundaki noktalama duraklama hakkı vermez
        nxt = t[i + 1: i + 2]
        if ch in _SENTENCE_MARKS:
            if nxt in _SENTENCE_MARKS or (ch == "." and not nxt.isspace()):
                continue
            sentence += 1
        elif ch in "—–" or (ch in ",;:" and nxt.isspace()):
            comma += 1
    return comma, sentence


def _text_repeat_distances(text: str) -> list[int]:
    """Metinde tekrar eden (≥ 3 heceli, ≤ 6 sözcüklük) sözcük dizilerinin ardışık geçişleri arasındaki hece uzaklığı.

    Sesteki tekrarın gecikmesi bu uzaklığın konuşma hızındaki karşılığına denk geliyorsa tekrar metinden gelir
    ("güzel bir gün, güzel bir gün"), halüsinasyon değildir.
    """
    toks = [tr_lower(w) for w in words(text)]
    syl = [count_syllables(w) for w in toks]
    cum = np.concatenate([[0], np.cumsum(syl)]) if syl else np.zeros(1)
    out: set[int] = set()
    for n in range(1, min(6, len(toks)) + 1):
        pos: dict[tuple[str, ...], list[int]] = {}
        for i in range(len(toks) - n + 1):
            pos.setdefault(tuple(toks[i:i + n]), []).append(i)
        for ps in pos.values():
            if len(ps) >= 2 and int(cum[ps[0] + n] - cum[ps[0]]) >= TEXT_REPEAT_MIN_SYL:
                out.update(int(cum[b] - cum[a]) for a, b in zip(ps, ps[1:]))
    return sorted(out)


# ---------- tekrar (repeat) tespiti ----------

def _envelope(x: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """Ortalanmış RMS zarfı: 10 ms atlama, 20 ms pencere; kare sayısı librosa (center=True) ile aynı."""
    hop = max(1, int(round(sr * HOP_S)))
    win = 2 * hop
    pad = win // 2
    xp = np.pad(x.astype(np.float64), (pad, pad))
    c = np.concatenate([[0.0], np.cumsum(xp * xp)])
    t = 1 + len(x) // hop
    starts = np.arange(t) * hop
    ends = np.minimum(starts + win, len(xp))
    e = np.sqrt(np.maximum(c[ends] - c[starts], 0.0) / win)
    return e, hop


def _peak_count(e: np.ndarray) -> int:
    """Zarftaki hece çekirdeği sayısı: dB zarfında en az 80 ms arayla, ≥ 1 dB belirgin tepeler."""
    if e.size < 3 or float(e.max()) <= 0:
        return 0
    edb = 20.0 * np.log10(np.maximum(e, float(e.max()) * 1e-3))
    peaks, _ = signal.find_peaks(edb, prominence=PEAK_PROM_DB, distance=max(1, int(round(0.08 / HOP_S))))
    return int(peaks.size)


def _lag_range(t: int) -> tuple[int, int]:
    lo = int(round(REPEAT_MIN_LAG_S / HOP_S))
    hi = min(int(round(REPEAT_MAX_LAG_S / HOP_S)), int(t / REPEAT_OVERLAP))
    return lo, hi


def _env_periodic(seg: np.ndarray, threshold: float) -> bool:
    """Bölüm kısa gecikmelerde (hece periyodu) de bu kadar benzer mi? (sinüs zarflı test sinyali koruması)"""
    lo = max(1, int(round(PERIODIC_MIN_LAG_S / HOP_S)))
    hi = int(round(REPEAT_MIN_LAG_S / HOP_S))
    for lag in range(lo, min(hi, len(seg) // 2)):
        if _pearson(seg[:-lag], seg[lag:]) >= threshold:
            return True
    return False


def _repeat_envelope(e: np.ndarray) -> dict | None:
    t = len(e)
    lo, hi = _lag_range(t)
    if hi < lo:
        return None
    d = e - e.mean()
    var = float(np.dot(d, d))
    if var <= 1e-18:
        return None
    nfft = 1 << int(math.ceil(math.log2(2 * t)))
    spec = np.fft.rfft(d, nfft)
    r = np.fft.irfft(spec * np.conj(spec), nfft)[:t]
    rho = (r / (t - np.arange(t))) / (var / t)  # yansız normalize otokorelasyon
    seg = rho[lo:hi + 1]
    # yerel tepeler, büyükten küçüğe; en iyi birkaç aday denenir
    is_peak = np.ones(seg.size, dtype=bool)
    is_peak[1:] &= seg[1:] >= seg[:-1]
    is_peak[:-1] &= seg[:-1] >= seg[1:]
    cands = [lo + int(i) for i in np.flatnonzero(is_peak & (seg > ENV_ACF_MIN))]
    cands.sort(key=lambda lag: -rho[lag])
    for lag in cands[:5]:
        a, b = e[: t - lag], e[lag:]
        corr = _pearson(a, b)
        if corr <= ENV_CORR_MIN:
            continue
        if _peak_count(a) < PEAK_MIN_COUNT:
            continue
        if _env_periodic(a, min(float(rho[lag]), corr) - PERIODIC_MARGIN):
            continue
        return {"lag": lag, "score": min(float(rho[lag]), corr), "start": 0, "length": t - lag,
                "repeats": max(1, int(round((t - lag) / lag)))}
    return None


def _mfcc_units(x: np.ndarray, sr: int, hop: int, active: np.ndarray) -> np.ndarray | None:
    """Kare başına birim uzunlukta, normalize MFCC vektörleri (sessiz kareler sıfır); durağan seste None."""
    try:
        import librosa
    except Exception:  # noqa: BLE001 — librosa yoksa yalnızca zarf yöntemi çalışır
        return None
    n_fft = 1 << int(math.ceil(math.log2(max(64, 0.02 * sr))))
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")  # düşük sr'de "boş mel süzgeci" uyarısı günlükleri kirletmesin
            m = librosa.feature.mfcc(y=x.astype(np.float32), sr=sr, n_mfcc=MFCC_N, n_fft=n_fft, hop_length=hop,
                                     n_mels=40, fmin=50.0, fmax=min(8000.0, sr / 2.0))
    except Exception:  # noqa: BLE001 — QC asla üretimi düşürmemeli; MFCC olmadan zarf yöntemi yeter
        return None
    m = m[1:].T.astype(np.float64)  # c0 (enerji) atılır
    t = min(len(m), len(active))
    m, act = m[:t], active[:t]
    if int(act.sum()) < 10:
        return None
    mu = m[act].mean(axis=0)
    sd = m[act].std(axis=0)
    if float(sd.mean()) < MFCC_STATIC_STD:
        return None
    z = (m - mu) / (sd + 1e-6)
    if t >= 3:  # 3 karelik yumuşatma: küçük zamanlama farklarına dayanıklılık
        z = np.vstack([z[:1], (z[:-2] + z[1:-1] + z[2:]) / 3.0, z[-1:]])
    z[~act] = 0.0
    nrm = np.linalg.norm(z, axis=1, keepdims=True)
    return np.divide(z, nrm, out=np.zeros_like(z), where=nrm > 1e-9)


def _diag(u: np.ndarray, lag: int) -> np.ndarray:
    return np.einsum("ij,ij->i", u[:-lag], u[lag:])


def _window_sim(s: np.ndarray, act: np.ndarray, lag: int, n: int, w: int) -> tuple[np.ndarray, np.ndarray]:
    """Köşegen benzerliğinin w karelik pencere ortalaması. İki ucu da sessiz çiftler sayılmaz (sessizlik sessizliğe
    benzer ama bu tekrar kanıtı değildir); yalnız bir ucu sessiz çift uyumsuzluktur (benzerlik 0).
    Dönüş: (pencere ortalamaları, pencerede iki ucu da sesli çift oranı)."""
    a, b = act[:n], act[lag:lag + n]
    both = _moving_mean((a & b).astype(np.float64), w)
    anyp = _moving_mean((a | b).astype(np.float64), w)
    num = _moving_mean(s, w)
    return np.divide(num, anyp, out=np.zeros_like(num), where=anyp > 0), both


def _repeat_mfcc(u: np.ndarray, act: np.ndarray, e: np.ndarray) -> dict | None:
    t = len(u)
    lo, hi = _lag_range(t)
    tol = MFCC_LAG_TOL
    if hi < lo or lo - tol < 1:
        return None
    sims = {lag: _diag(u, lag) for lag in range(lo - tol, hi + tol + 1) if lag < t}
    w_min = int(round(MFCC_WIN_MIN_S / HOP_S))
    best = None
    for lag in range(lo, hi + 1):
        n = t - lag - tol
        w = max(w_min, int(round(MFCC_WIN_FRAC * lag)))
        if n < w or (lag + tol) not in sims:
            continue
        s = np.max(np.stack([sims[lag + k][:n] for k in range(-tol, tol + 1)]), axis=0)
        wm, both = _window_sim(s, act, lag, n, w)
        wm = np.where(both >= MFCC_MIN_ACTIVE, wm, -1.0)
        i = int(np.argmax(wm))
        if best is None or wm[i] > best["score"]:
            best = {"lag": lag, "score": float(wm[i]), "start": i, "length": w, "s": s, "n": n}
    if best is None or best["score"] <= MFCC_SIM_MIN:
        return None
    lag, i, w = best["lag"], best["start"], best["length"]
    # en az 2 hece; kısa gecikmelerde de aynı benzerlik varsa periyodik/durağan sestir, tekrar değil
    if _peak_count(e[i:i + w]) < PEAK_MIN_COUNT:
        return None
    p_lo = max(1, int(round(PERIODIC_MIN_LAG_S / HOP_S)))
    for short in range(p_lo, lo):
        if i + w + short > t:
            break
        ss = _diag(u[i:i + w + short], short)[:w]
        sm, _ = _window_sim(ss, act[i:i + w + short], short, w, w)
        if float(sm[0]) >= best["score"] - PERIODIC_MARGIN:
            return None
    # tekrar sayısı: köşegen boyunca yüksek benzerliğin sürdüğü bölge / gecikme
    k = max(1, int(round(0.2 / HOP_S)))
    sm, _ = _window_sim(best["s"], act, lag, best["n"], k)
    hi_mask = sm >= 0.75
    j = min(i, len(sm) - 1)
    a = b = j
    while a > 0 and hi_mask[a - 1]:
        a -= 1
    while b < len(sm) - 1 and hi_mask[b + 1]:
        b += 1
    run = max(w, b - a + k)
    return {"lag": lag, "score": best["score"], "start": i, "length": w,
            "repeats": max(1, int(round(run / lag)))}


def _detect_repeat(seg: np.ndarray, sr: int) -> dict:
    out = {"repeats": 0, "lag": None, "score": 0.0, "method": None}
    if len(seg) < int(REPEAT_OVERLAP * REPEAT_MIN_LAG_S * sr):
        return out
    e, hop = _envelope(seg, sr)
    found = {}
    env = _repeat_envelope(e)
    if env:
        found["zarf"] = env
    active = e >= max(db_to_amp(SILENCE_DB), float(e.max()) * db_to_amp(-40.0))
    u = _mfcc_units(seg, sr, hop, active)
    if u is not None:
        mf = _repeat_mfcc(u, active[: len(u)], e[: len(u)])
        if mf:
            found["mfcc"] = mf
    if not found:
        return out
    main = found.get("mfcc") or found["zarf"]
    out.update({"repeats": max(f["repeats"] for f in found.values()), "lag": round(main["lag"] * HOP_S, 2),
                "score": round(max(f["score"] for f in found.values()), 3), "method": "+".join(found)})
    return out


# ---------- vızıltı (buzz) tespiti ----------

def _width_hz(pdb: np.ndarray, k: int, df: float, drop_db: float = 6.0) -> float:
    lvl = pdb[k] - drop_db
    a = b = k
    while a > 0 and pdb[a - 1] > lvl:
        a -= 1
    while b < len(pdb) - 1 and pdb[b + 1] > lvl:
        b += 1
    return (b - a + 1) * df


def _psd(x: np.ndarray, sr: int, nperseg: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Welch PSD (Hann, %50 örtüşme): (frekanslar, güç, dB)."""
    nper = min(nperseg, 1 << int(math.floor(math.log2(len(x)))))
    f, p = signal.welch(np.asarray(x, dtype=np.float32), fs=sr, window="hann", nperseg=nper, noverlap=nper // 2,
                        detrend="constant", scaling="density")
    p = p.astype(np.float64)
    return f, p, 10.0 * np.log10(p + 1e-30)


def _hf_prominence(f: np.ndarray, pdb: np.ndarray, k: int) -> float:
    """Tepenin, çevresinin (±50–400 Hz) 90. yüzdeliğine göre yüksekliği (dB). Yüzdelik taban, harmonik tarağın
    tepelerini de içerdiği için tarağı tek tondan ayırır."""
    dist = np.abs(f - f[k])
    nb = (dist >= 50.0) & (dist <= 400.0)
    return float(pdb[k] - np.percentile(pdb[nb], 90)) if nb.any() else 0.0


def _hf_persistent(x: np.ndarray, sr: int, hz: float) -> bool:
    """Ton parçanın üç bölümünün en az ikisinde de (eşik - 6 dB) duruyor mu? ("sürekli" tepe; tek bir ıslık değil)"""
    ok = 0
    for part in np.array_split(x, 3):
        f, _, pdb = _psd(part, sr, WELCH_NPERSEG)
        k = int(np.argmin(np.abs(f - hz)))
        if max(_hf_prominence(f, pdb, j) for j in range(max(0, k - 1), min(len(f), k + 2))) >= BUZZ_PROM_DB - 6:
            ok += 1
    return ok >= 2


def _detect_buzz(x: np.ndarray, sr: int) -> dict:
    out = {"buzz": False, "hz": None, "db": 0.0, "kind": None}
    if len(x) < 1024 or float(np.max(np.abs(x))) <= 0:
        return out
    f, p, pdb = _psd(x, sr, WELCH_NPERSEG)
    df = float(f[1] - f[0])
    total = float(np.sum(p))
    if total <= 0:
        return out
    best: tuple[float, float, str] | None = None  # (belirginlik dB, Hz, tür)
    long_enough = len(x) >= BUZZ_PERSIST_MIN_S * sr

    # 1) 4–8 kHz'de tek, dar, sürekli tepe (ıslık/vızıltı). Kısa parçada (az ortalama → oynak PSD) eşik yüksek.
    lo_hz, hi_hz = BUZZ_BAND_HZ[0], min(BUZZ_BAND_HZ[1], sr / 2.0 - 4 * df)
    if hi_hz - lo_hz > 200:
        need = BUZZ_PROM_DB if long_enough else BUZZ_PROM_SHORT_DB
        idx = np.flatnonzero((f >= lo_hz) & (f <= hi_hz))
        peaks, _ = signal.find_peaks(pdb[idx[0]: idx[-1] + 1], prominence=6.0)
        for pk in peaks:
            k = int(idx[0] + pk)
            prom = _hf_prominence(f, pdb, k)
            if prom < need or _width_hz(pdb, k, df) > BUZZ_MAX_WIDTH_HZ:
                continue
            rel = 10.0 * math.log10(float(np.sum(p[max(0, k - 2): k + 3])) / total + 1e-30)
            if rel < BUZZ_MIN_REL_DB or (best is not None and prom <= best[0]):
                continue
            if long_enough and not _hf_persistent(x, sr, float(f[k])):
                continue
            best = (prom, float(f[k]), "hf")

    # 2) 50/100 Hz şebeke uğultusu: ince çözünürlüklü PSD'de (≈ 1,5 Hz) çok dar çizgi. Perde (F0) 100 Hz civarında
    #    olan bir erkek sesi bile birkaç Hz oynar ve daha geniş görünür; kısa parçada ikisi ayrılamaz → atlanır.
    if best is None and len(x) >= HUM_MIN_S * sr:
        fh, ph, pdbh = _psd(x, sr, HUM_NPERSEG)
        dfh = float(fh[1] - fh[0])
        total_h = float(np.sum(ph))
        for hz in HUM_FREQS:
            near = np.flatnonzero(np.abs(fh - hz) <= max(dfh, 2.0))
            if hz >= sr / 2.0 or near.size == 0:
                continue
            k = int(near[np.argmax(pdbh[near])])
            dist = np.abs(fh - hz)
            nb = (dist >= 8.0) & (dist <= 30.0)
            if not nb.any() or _width_hz(pdbh, k, dfh) > HUM_MAX_WIDTH_HZ:
                continue
            prom = float(pdbh[k] - np.median(pdbh[nb]))
            rel = 10.0 * math.log10(float(np.sum(ph[max(0, k - 3): k + 4])) / total_h + 1e-30)
            if prom >= HUM_PROM_DB and rel >= HUM_MIN_REL_DB and (best is None or prom > best[0]):
                best = (prom, hz, "hum")
    if best is None:
        return out
    return {"buzz": True, "hz": round(best[1], 1), "db": round(best[0], 1), "kind": best[2]}


# ---------- hız (süre) değerlendirmesi ----------

def _slack_s(n_chars: int) -> float:
    """Kısa metinlerde uzunluk sınırına eklenen pay: 5 karakter → 0,6 sn, ≥ 27 karakter → 0."""
    return float(min(SHORT_TEXT_SLACK_S, max(0.0, 0.8 - 0.03 * n_chars)))


def _rate(n_chars: int, n_syl: int, dur: float, expected_cps: float | None) -> dict:
    cps = n_chars / dur if dur > 0 else 0.0
    sps = n_syl / dur if dur > 0 else 0.0
    slack = _slack_s(n_chars)
    r = {"cps": cps, "sps": sps, "long": None, "short": None, "very_slow": False}
    if expected_cps is not None:
        lo, hi = expected_cps * (1 - EXPECTED_TOL), expected_cps * (1 + EXPECTED_TOL)
        max_d, min_d = n_chars / lo + slack, n_chars / hi
        r.update(cps_range=[round(lo, 2), round(hi, 2)], sps_range=None, max_duration=max_d, min_duration=min_d,
                 expected_duration=n_chars / expected_cps)
        if n_chars and dur > max_d:
            r["long"] = "error"
        elif n_chars and dur < min_d:
            r["short"] = "error"
        r["very_slow"] = bool(n_chars and dur > n_chars / (lo * VERY_SLOW_FACTOR) + slack)
        return r
    max_c, min_c = n_chars / CPS_MIN + slack, n_chars / CPS_MAX
    r.update(cps_range=[CPS_MIN, CPS_MAX], sps_range=[SPS_MIN, SPS_MAX], max_duration=max_c, min_duration=min_c,
             expected_duration=(n_syl / TYPICAL_SPS) if n_syl else n_chars / TYPICAL_CPS)
    if not n_chars:
        return r
    long_c, short_c = dur > max_c, dur < min_c
    if n_syl:
        long_s, short_s = dur > n_syl / SPS_MIN + slack, dur < n_syl / SPS_MAX
    else:  # hecesiz metin ("Hmm", "Pşşt"): yalnız karakter hızı
        long_s, short_s = long_c, short_c
    if long_c and long_s:
        r["long"] = "error"
    elif long_c or long_s:
        r["long"] = "warn"
    if short_c and short_s:
        r["short"] = "error"
    elif short_c or short_s:
        r["short"] = "warn"
    r["very_slow"] = bool(dur > n_chars / (CPS_MIN * VERY_SLOW_FACTOR) + slack)
    return r


# ---------- ana fonksiyon ----------

def _metrics_template(duration: float, n_chars: int, n_syl: int, expected_cps: float | None) -> dict:
    """Tüm anahtarlar her zaman bulunur (boş/çok kısa girdide de): tüketici KeyError almasın."""
    return {"duration": round(duration, 3), "speech_duration": 0.0, "chars": n_chars, "syllables": n_syl,
            "cps": 0.0, "sps": 0.0, "expected_cps": expected_cps, "cps_range": None, "sps_range": None,
            "max_duration": None, "expected_duration": None,
            "silence_ratio": 1.0, "unexplained_silence": 1.0, "dropouts": 0, "natural_pauses": 0, "gaps_ms": [],
            "repeats": 0, "repeat_lag": None, "repeat_score": 0.0, "repeat_method": None, "repeat_expected": False,
            "clipping": 0.0, "buzz": False, "buzz_hz": None, "buzz_db": 0.0,
            "tail_silence": 0, "head_silence": 0, "peak_dbfs": -120.0}


def _fatal(metrics: dict, code: str, message: str) -> dict:
    return {"score": 0, "ok": False, "decision": RETRY_SEED,
            "reasons": [{"code": code, "message": message, "severity": "error", "penalty": 100,
                         "action": RETRY_SEED}],
            "metrics": metrics}


def check_chunk(wav: np.ndarray, sr: int, text: str, *, expected_cps: float | None = None) -> dict:
    """Bir parçanın ses + metin çiftini ölçer, 0–100 puanlar ve karar verir (bkz. modül açıklaması).

    Dönüş: ``{"score", "ok", "decision", "reasons": [{"code", "message", "severity", "penalty", "action"}],
    "metrics": {duration, cps, silence_ratio, dropouts, repeats, clipping, buzz, tail_silence, ...}}``.
    ``severity``: "error" kararı değiştirir (retry/trim), "warn" yalnızca puanı düşürür.
    """
    sr = int(sr)
    if sr <= 0:
        raise ValueError(f"Geçersiz örnekleme hızı: {sr}")
    x = _as_mono(wav)
    text = text or ""
    n_chars = len(text.strip())
    n_syl = count_syllables_text(text)
    exp = None
    if expected_cps is not None:  # geçersiz ya da makul aralık (4–40) dışı değer yok sayılır: varsayılan eşikler
        try:
            e = float(expected_cps)
        except (TypeError, ValueError):
            e = float("nan")
        if math.isfinite(e) and EXPECTED_CPS_RANGE[0] <= e <= EXPECTED_CPS_RANGE[1]:
            exp = e
    duration = len(x) / sr
    m = _metrics_template(duration, n_chars, n_syl, round(exp, 2) if exp else None)

    frame = _frame_len(sr)
    if len(x) == 0:
        return _fatal(m, "too_short", "Parça boş: model hiç ses üretmedi.")
    m["peak_dbfs"] = round(20 * math.log10(float(np.max(np.abs(x))) + 1e-12), 1)
    clip_ratio = float(np.mean(np.abs(x) >= CLIP_LEVEL))
    m["clipping"] = round(clip_ratio, 5)
    if len(x) < 2 * frame:
        return _fatal(m, "too_short", f"Parça çok kısa ({int(round(duration * 1000))} ms): model sesi üretmeden "
                                      "durmuş.")
    db = _frame_db(x, frame)
    loud = db >= SILENCE_DB
    if not loud.any():
        m["tail_silence"] = int(round(duration * 1000))
        return _fatal(m, "silence", f"Parçada konuşma yok: tamamı {_tr(SILENCE_DB, 0)} dBFS altında (sessiz).")
    first, last = int(np.argmax(loud)), int(len(loud) - 1 - np.argmax(loud[::-1]))
    s0, s1 = first * frame, (last + 1) * frame
    speech = (s1 - s0) / sr
    m["speech_duration"] = round(speech, 3)
    m["head_silence"] = int(round(s0 / sr * 1000))
    m["tail_silence"] = int(round((len(x) - s1) / sr * 1000))
    if speech < MIN_SPEECH_S:
        return _fatal(m, "too_short", f"Parçada yalnızca {int(round(speech * 1000))} ms ses var: konuşma "
                                      "üretilmemiş.")

    reasons: list[dict] = []

    def add(code: str, severity: str, message: str, penalty: int, action: str | None) -> None:
        reasons.append({"code": code, "message": message, "severity": severity, "penalty": int(penalty),
                        "action": action})

    # --- hız / süre ---
    rate = _rate(n_chars, n_syl, speech, exp)
    m.update(cps=round(rate["cps"], 2), sps=round(rate["sps"], 2), cps_range=rate["cps_range"],
             sps_range=rate["sps_range"], max_duration=round(rate["max_duration"], 2) if n_chars else None,
             expected_duration=round(rate["expected_duration"], 2) if n_chars else None)
    exp_d = rate["expected_duration"]

    # --- sessizlik oranı ve boşluklar ---
    region = loud[first:last + 1]
    m["silence_ratio"] = round(float(1.0 - region.mean()), 3)
    edge = int(math.ceil(EDGE_MS / FRAME_MS))
    gap_frames = int(math.ceil(GAP_MIN_MS / FRAME_MS - 1e-9))
    gaps = [ln * FRAME_MS for st, ln in _runs(~region)
            if ln >= gap_frames and st >= edge and st + ln <= len(region) - edge]
    m["dropouts"] = len(gaps)
    m["gaps_ms"] = [int(g) for g in gaps]
    comma_slots, sentence_slots = _pause_slots(text)
    unexplained: list[float] = []
    natural_ms = 0.0
    for g in sorted(gaps):
        if comma_slots and g <= NATURAL_COMMA_GAP_MS:
            comma_slots -= 1
            natural_ms += g
        elif sentence_slots and g <= NATURAL_SENTENCE_GAP_MS:
            sentence_slots -= 1
            natural_ms += g
        else:
            unexplained.append(g)
    m["natural_pauses"] = len(gaps) - len(unexplained)
    # noktalamanın açıkladığı duraklamalar sessizlik oranı kararına girmez ("Evet. Hayır. Belki." kısa ve boşluklu)
    nat = int(round(natural_ms / FRAME_MS))
    silent = int(region.size - int(region.sum()))
    m["unexplained_silence"] = round((silent - nat) / max(1, region.size - nat), 3)

    # --- tekrar ---
    rep = _detect_repeat(x[s0:s1], sr)
    text_rep = False
    if rep["repeats"] and rate["sps"] > 0:
        text_rep = any(abs(rep["lag"] - d / rate["sps"]) <= TEXT_REPEAT_LAG_TOL * d / rate["sps"]
                       for d in _text_repeat_distances(text))
    m.update(repeats=rep["repeats"], repeat_lag=rep["lag"], repeat_score=rep["score"], repeat_method=rep["method"],
             repeat_expected=bool(text_rep))
    has_repeat = bool(rep["repeats"]) and not text_rep

    # --- vızıltı ---
    bz = _detect_buzz(x, sr)
    m.update(buzz=bz["buzz"], buzz_hz=bz["hz"], buzz_db=bz["db"])

    # --- gerekçeler ---
    if rate["long"] == "error":
        pct = int(round((speech / exp_d - 1) * 100)) if exp_d > 0 else 0
        trimmable = rate["very_slow"] and not has_repeat
        tail_msg = ("sonundaki fazlalık sessiz bir noktadan kesilecek." if trimmable
                    else "model muhtemelen cümleyi uzattı ya da fazladan ses ekledi.")
        add("too_long", "error", f"Parça beklenenden %{pct} uzun ({_tr(speech, 2)} sn; beklenen ≈ {_tr(exp_d, 2)} sn, "
                                 f"en çok {_tr(rate['max_duration'], 2)} sn): {tail_msg}",
            PENALTY["too_long"], TRIM if trimmable else RETRY_SEED)
    if rate["short"] == "error":
        pct = int(round((1 - speech / exp_d) * 100)) if exp_d > 0 else 0
        add("too_short", "error", f"Parça beklenenden %{pct} kısa ({_tr(speech, 2)} sn; beklenen ≈ {_tr(exp_d, 2)} "
                                  f"sn, en az {_tr(rate['min_duration'], 2)} sn): cümle yarıda kesilmiş olabilir.",
            PENALTY["too_short"], RETRY_SEED)
    if rate["long"] == "warn" or rate["short"] == "warn":
        slow = rate["long"] == "warn"
        add("rate", "warn", f"Konuşma hızı sınırda ({'yavaş' if slow else 'hızlı'}): saniyede {_tr(rate['cps'])} "
                            f"karakter (olağan {_tr(CPS_MIN, 0)}–{_tr(CPS_MAX, 0)}), {_tr(rate['sps'])} hece "
                            f"(olağan {_tr(SPS_MIN)}–{_tr(SPS_MAX)}); ölçütlerden yalnız biri dışarıda.",
            PENALTY["rate"], None)
    if m["silence_ratio"] > SILENCE_RATIO_MAX and m["unexplained_silence"] > SILENCE_RATIO_MAX:
        add("silence", "error", f"Konuşmanın %{int(round(m['silence_ratio'] * 100))}'i sessizlik: model takılmış "
                                "ya da uzun boşluklar üretmiş.", PENALTY["silence"], RETRY_SEED)
    if len(unexplained) >= DROPOUT_MIN_COUNT:
        add("dropout", "error", f"Konuşmanın ortasında {len(unexplained)} uzun sessiz boşluk var (en uzunu "
                                f"{int(max(unexplained))} ms): ses kesik kesik, model takılıyor.",
            min(DROPOUT_MAX_PENALTY, PENALTY["dropout"] * len(unexplained)), RETRY_STABLE)
    elif unexplained:
        add("pause", "warn", f"Konuşmanın ortasında {int(unexplained[0])} ms'lik bir boşluk var; tek başına doğal "
                             "bir duraklama olabilir.", PENALTY["dropout"], None)
    if has_repeat:
        how = {"zarf": "ses zarfı", "mfcc": "MFCC", "zarf+mfcc": "ses zarfı ve MFCC"}.get(rep["method"], "")
        add("repeat", "error", f"{_tr(rep['lag'])} sn arayla tekrar eden bölüm bulundu ({how} benzerliği "
                               f"{_tr(rep['score'], 2)}): model sözcük ya da cümle tekrarına düşmüş.",
            PENALTY["repeat"], RETRY_SEED)
    if clip_ratio > CLIP_RATIO_MAX:
        add("clipping", "error", f"Örneklerin %{_tr(clip_ratio * 100, 2)} kadarı tavanda (kırpılma): ses cızırtılı "
                                 "duyulabilir; seviye düşürülecek.", PENALTY["clipping"], TRIM)
    if bz["buzz"]:
        if bz["kind"] == "hum":
            msg = (f"{_tr(bz['hz'], 0)} Hz şebeke uğultusu var (çevresinden {_tr(bz['db'], 0)} dB yüksek): "
                   "referans kaydındaki uğultu sese geçmiş olabilir.")
        else:
            msg = (f"{_tr(bz['hz'] / 1000)} kHz'de sürekli dar bant tepe var (çevresinden {_tr(bz['db'], 0)} dB "
                   "yüksek): vızıltı/ıslık sesi.")
        add("buzz", "error", msg, PENALTY["buzz"], RETRY_STABLE)
    if m["tail_silence"] > TAIL_MAX_MS:
        add("tail", "error", f"Sonda {m['tail_silence']} ms sessizlik var: {int(TAIL_MAX_MS)} ms'yi aşıyor, "
                             "kırpılacak.", PENALTY["tail"], TRIM)

    score = int(max(0, min(100, 100 - sum(r["penalty"] for r in reasons))))
    actions = {r["action"] for r in reasons}
    if RETRY_SEED in actions:
        decision = RETRY_SEED
    elif RETRY_STABLE in actions:
        decision = RETRY_STABLE
    elif TRIM in actions:
        decision = TRIM
    else:
        decision = ACCEPT if score >= OK_SCORE else RETRY_SEED
    order = {"error": 0, "warn": 1}
    reasons.sort(key=lambda r: (order.get(r["severity"], 2), -r["penalty"]))
    return {"score": score, "ok": score >= OK_SCORE, "decision": decision, "reasons": reasons, "metrics": m}


# ---------- yardımcı API ----------

def estimate_cps(samples) -> float | None:
    """(karakter, saniye) geçmişinden konuşma hızı: 4–40 kar/sn dışını atar; ≥ 3 geçerli örnekte medyan, yoksa None."""
    vals: list[float] = []
    for s in samples or []:
        try:
            chars, secs = float(s[0]), float(s[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if not (math.isfinite(chars) and math.isfinite(secs)) or chars <= 0 or secs <= 0:
            continue
        cps = chars / secs
        if EXPECTED_CPS_RANGE[0] <= cps <= EXPECTED_CPS_RANGE[1]:
            vals.append(cps)
    if len(vals) < 3:
        return None
    return round(float(np.median(vals)), 2)


def trim_tail(wav: np.ndarray, sr: int, max_tail_ms: int = 250) -> np.ndarray:
    """Sondaki sessizliği en çok ``max_tail_ms`` bırakacak şekilde kırpar (kesim noktasında kısa fade-out)."""
    x = _as_mono(wav)
    keep = int(sr * max(0, max_tail_ms) / 1000)
    b = _speech_bounds(x, sr)
    end = (b[1] if b else 0) + keep
    if end >= len(x):
        return x.copy()
    return _ramp(x[:end].copy(), sr, 10, head=False)


def trim_head(wav: np.ndarray, sr: int, max_head_ms: int = 150) -> np.ndarray:
    """Baştaki sessizliği en çok ``max_head_ms`` bırakacak şekilde kırpar (kesim noktasında kısa fade-in)."""
    x = _as_mono(wav)
    keep = int(sr * max(0, max_head_ms) / 1000)
    b = _speech_bounds(x, sr)
    start = (b[0] if b else len(x)) - keep
    if start <= 0:
        return x.copy()
    return _ramp(x[start:].copy(), sr, 10, head=True)


def _last_pause_between(x: np.ndarray, sr: int, start_s: float, end_s: float) -> int | None:
    """[start_s, end_s] aralığında başlayan son ≥ 250 ms sessizliğin başlangıç örneği (yoksa None)."""
    frame = _frame_len(sr)
    quiet = _frame_db(x, frame) < SILENCE_DB
    need = int(math.ceil(GAP_MIN_MS / FRAME_MS - 1e-9))
    found = None
    for st, ln in _runs(quiet):
        t = st * frame / sr
        if t > end_s:
            break
        if t >= start_s and ln >= need:
            found = st * frame
    return found


def apply_trim(wav: np.ndarray, sr: int, report: dict | None = None) -> np.ndarray:
    """"trim" kararını uygular: baş ≤ 150 ms / son ≤ 250 ms sessizlik; clipping varsa tepeyi -1 dBFS'e çeker.

    too_long varsa (aşırı uzamış, tekrarsız parça) fazlalık atılır: beklenen sürenin %80'inden sonra, azami süreden
    önce başlayan SON uzun duraklamadan kesilir (tipik halüsinasyon: cümle biter, sessizlik, ardından anlamsız ses;
    son duraklama seçilir ki yavaş okunmuş gerçek bir cümle kesilmesin); böyle bir duraklama yoksa azami süre
    civarındaki en sessiz noktadan (``audio.cut_at_silence``)."""
    report = report or {}
    codes = {r.get("code") for r in report.get("reasons", [])}
    met = report.get("metrics") or {}
    max_d, exp_d = met.get("max_duration"), met.get("expected_duration")
    x = trim_head(wav, sr)
    if "too_long" in codes and max_d:
        b = _speech_bounds(x, sr)
        s0 = b[0] / sr if b else 0.0
        cut = _last_pause_between(x, sr, s0 + 0.8 * float(exp_d), s0 + float(max_d)) if exp_d else None
        if cut is not None:
            x = _ramp(x[:cut + int(0.05 * sr)].copy(), sr, 10, head=False)
        else:
            x = cut_at_silence(x, sr, s0 + float(max_d))
    x = trim_tail(x, sr)
    if "clipping" in codes and x.size:
        peak, limit = float(np.max(np.abs(x))), db_to_amp(-1.0)
        if peak > limit:
            x = x * (limit / peak)
    return np.asarray(x, dtype=np.float32)


def _score_of(r) -> float:
    try:
        s = float(r.get("score", 0)) if isinstance(r, dict) else float("-inf")
    except (TypeError, ValueError):
        return float("-inf")
    return s if math.isfinite(s) else float("-inf")


def pick_best(reports: list[dict]) -> int:
    """En yüksek puanlı raporun indeksi; eşitlikte ilk. Boş listede ValueError."""
    if not reports:
        raise ValueError("Seçilecek rapor yok (boş liste).")
    scores = [_score_of(r) for r in reports]
    return int(max(range(len(scores)), key=lambda i: (scores[i], -i)))


def _retries_of(r: dict) -> int:
    for key, off in (("retries", 0), ("attempts", 1)):
        v = r.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return max(0, int(v) - off)
    return 1 if r.get("decision") in RETRY_DECISIONS else 0


def summarize(reports: list[dict]) -> dict:
    """Geçmişte göstermek için özet: ``{"count", "mean_score", "retries", "worst", "decisions", "codes"}``.

    ``retries``: rapor ``retries`` (ya da ``attempts``) alanı taşıyorsa (motorun eklediği deneme sayısı) o kullanılır,
    yoksa kararı retry_* olan raporlar sayılır. ``worst``: en düşük puanlı parça (eşitlikte ilk) —
    ``{"index", "score", "decision", "codes", "message"}``; ``index`` raporda varsa o, yoksa listedeki sırası.
    """
    items = [(i, r) for i, r in enumerate(reports or []) if isinstance(r, dict)]
    if not items:
        return {"count": 0, "mean_score": None, "retries": 0, "worst": None, "decisions": {}, "codes": {}}
    scores = [max(0.0, _score_of(r)) for _, r in items]
    wi = min(range(len(items)), key=lambda k: (scores[k], k))
    pos, worst = items[wi]
    errs = [x for x in worst.get("reasons", []) if isinstance(x, dict)]
    codes = Counter(x.get("code") for _, r in items for x in r.get("reasons", []) if isinstance(x, dict))
    return {
        "count": len(items),
        "mean_score": round(sum(scores) / len(scores), 1),
        "retries": int(sum(_retries_of(r) for _, r in items)),
        "worst": {"index": worst.get("index", pos), "score": int(round(scores[wi])),
                  "decision": worst.get("decision"), "codes": [x.get("code") for x in errs],
                  "message": errs[0].get("message", "") if errs else ""},
        "decisions": dict(Counter(str(r["decision"]) for _, r in items if r.get("decision"))),
        "codes": {str(k): int(v) for k, v in codes.items() if k},
    }
