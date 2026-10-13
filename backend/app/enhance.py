"""Referans kaydı iyileştirme — kaydı KORUYARAK temizler.

Klon kalitesinin en büyük belirleyicisi referans kayıttır; kullanıcıların çoğu gürültülü bir odada, telefonla kaydeder.
Bu modül kaydı tınısına dokunmadan temizler: DC kayması, tıklar, 50/60 Hz şebeke uğultusu, durağan arka plan
gürültüsü, 70 Hz altı gümbürtü ve seviye. Aşırı temizlik klonu "robotlaştırdığı" için her adım temkinlidir:
konuşma karelerinde eşiği aşan binlere dokunulmaz, gürültü en fazla ``max_reduction_db`` (yapaylık sınırı, 12 dB)
kadar azaltılır, tık sanılan olaylar kaydın %1'inden fazlasını kaplıyorsa hiç yama yapılmaz.
Sözleşme: ``docs/SOZLESME2.md`` bölüm 4.

    should_enhance(analysis) -> (bool, nedenler)
    detect_hum(wav, sr) -> 50.0 | 60.0 | None
    enhance_reference(wav, sr, analysis=None, *, denoise=True, dehum=True, declick=True, highpass_hz=70,
                      target_dbfs=-20.0, max_reduction_db=12.0) -> (wav_out, rapor)
    quality_delta(before, after) -> int
    enhance_file(src, dst, backup=None) -> rapor (+ "before", "after", "delta")

İşlem sırası: dc → declick → dehum → denoise → highpass → seviye. Yöntemler (özet):

* dc: ortalama çıkarılır.
* declick: türev x' üzerinde gürbüz σ = 1.4826 × MAD; |x'| > 8σ olan noktalar ve ±1 ms komşulukları doğrusal ara
  değerle yamanır. σ, küresel değer ile noktanın ±10–20 ms çevresindeki yerel değerin büyüğüdür: sürekli yüksek
  frekanslı sesler (s, ş) "tık" sayılmaz, sessizlikteki tık yine yakalanır. Gerçek konuşmada 8σ'yı aşan olayların
  çoğu tık değil gırtlak darbesi ya da patlamalı ünsüz salınımıdır; bu yüzden aday ancak (a) ±20 ms çevresindeki en
  büyük türevin en az 3 katıysa (darbeler perde periyodunda tekrarlanır, tık yalıtıktır) ve (b) öncesi ile sonrası
  arasındaki enerji farkı ≤ 10 dB ise (patlama bir başlangıçtır, tık arka plana geri döner) yamanır. Yamanacak
  toplam süre kaydın %1'ini aşarsa olaylar tık değil gürültü/konuşma yapısıdır: hiç yama yapılmaz.
* dehum: ``detect_hum`` (Welch PSD, 40–70 Hz'de komşu bantlara göre ≥ 12 dB tepe) → temel ve 2. harmonik için
  ``iirnotch`` (Q=30), ``filtfilt``. 3. harmonik (150/180 Hz) konuşmanın temel frekans bölgesine düştüğü için
  ATLANIR. Notch'un yerleşme süresi (~0.2 sn) kayıt kenarlarında uğultu bırakmasın diye sinyal, uğultu periyodunun
  tam katı uzunlukta bloklarla (uğultu fazını sürdürerek) dolgulanır; dolgu süzme sonrası atılır.
* denoise: STFT (1024/256, Hann) spektral kapı. Gürültü profili = kare enerjisine göre en sessiz %10 karenin bin
  bazında medyan gücü (dijital sessizlik hariç). Eşiğin (profil + 6 dB) altındaki binler zayıflatılır; kazanç maskesi
  zamanda 3 kare, frekansta 5 bin ile yumuşatılır (aynı pencerede önce medyan: yalıtık eşik aşımları — müzikal
  gürültü — atılır; sonra ortalama: yumuşak geçiş), en düşük kazanç 10^(-max_reduction_db/20). Konuşma karelerinde
  (enerji > profil + 12 dB; iki yana 2 karelik pay) eşik üstü binlere dokunulmaz — harmonikler olduğu gibi kalır.
  Profil ancak kayıtta tabana yakın (+3 dB), en az 0.1 sn kesintisiz bir duraklama varsa güvenilir sayılır;
  duraklamasız konuşmada en sessiz kareler hece çukurlarıdır ve gürültü azaltma hiç uygulanmaz.
  ``analysis.noise_floor_dbfs`` verilmişse ve kendi profilimiz bundan 6 dB'den fazla yüksekse (en sessiz karelere
  konuşma karışmış demektir) profil o düzeye çekilir: kapı yalnızca daha temkinli olabilir. Gürültü karelerindeki
  ölçülen azalma 0.5 dB'yi bulmazsa (zaten temiz kayıt) sonuç atılır, sinyal değişmez.
* highpass: 2. derece Butterworth, ``sosfiltfilt`` (sıfır faz). Çift geçiş eğimi ikiye katladığından tasarım
  frekansı, toplam yanıtın −3 dB noktası ``highpass_hz``'e denk gelecek biçimde ayarlanır (aksi hâlde 70 Hz
  ayarı fiilen 87 Hz'de keser ve 80–100 Hz perdeli erkek seslerinin temelini 2–4 dB kısar). Analizde perde varsa
  kesim ``f0.min_hz × 0.8``'i (en az 40 Hz) aşmaz.
* seviye: ``audio.rms_normalize`` ile RMS ``target_dbfs``, tepe −1 dBFS; kazanç en fazla +40 dB.

Çıktı girdiyle aynı uzunlukta, mono, float32 ve NaN içermez. 0.3 sn'den kısa ya da tamamen sessiz girdi olduğu gibi
döner (``applied`` boş). Rapordaki sayılar yuvarlanmış, yerleşik Python tipleridir (``json.dumps`` doğrudan çalışır).
"""
from __future__ import annotations

import math
import os
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import ndimage, signal

from .analysis import analyze_array
from .audio import db_to_amp, rms_normalize

# ---------- sabitler ----------

MIN_DURATION_S = 0.3  # bundan kısa girdiye dokunulmaz
SILENCE_RMS = 1e-7  # ≈ −140 dBFS: altı "sessiz" sayılır
DB_FLOOR = -120.0  # log(0) yerine kullanılan alt sınır
DIGITAL_SILENCE_DB = -100.0  # bunun altı dijital sessizlik: gürültü profiline katılmaz

# should_enhance
SNR_NOISY_DB = 30.0

# dc
DC_REPORT_RATIO = 0.02  # |ortalama| > %2 × AC RMS ise raporda "dc"

# declick
CLICK_SIGMA = 8.0
CLICK_PATCH_MS = 1.0
CLICK_LOCAL_MS = 10.0  # yerel σ blok uzunluğu; komşu bloklarla birlikte ±10–20 ms
CLICK_MAX_RATIO = 0.01  # yamalanacak toplam süre en fazla kaydın %1'i
CLICK_SCAN_RATIO = 0.10  # adaylar kaydın %10'undan fazlasını kaplıyorsa tek tek incelemeye bile gerek yok: gürültü
CLICK_MIN_JUMP = 1e-4  # −80 dBFS'den küçük sıçrama duyulmaz: tık sayılmaz
CLICK_CONTEXT_MS = 20.0  # çevre penceresi: en düşük konuşma perdesinin (~60 Hz) bir periyodu
CLICK_ISOLATION = 3.0  # tık, çevresindeki en büyük türevin en az bu katı olmalı (gırtlak darbeleri periyodiktir)
CLICK_CONTEXT_DB = 10.0  # önceki/sonraki enerji farkı bundan büyükse olay bir başlangıçtır (patlamalı ünsüz)

# dehum
HUM_NPERSEG = 8192  # 24 kHz'de ≈ 2.9 Hz çözünürlük
HUM_BAND_HZ = (40.0, 70.0)
HUM_NEIGHBOR_HZ = (8.0, 25.0)  # tepeye uzaklık: komşu bant (ana lob dışı)
HUM_MIN_PROMINENCE_DB = 12.0
HUM_Q = 30.0
HUM_HARMONICS = 2  # temel + 2. harmonik; 3. harmonik konuşma temel frekansıyla çakışır, atlanır
HUM_PAD_S = 0.75  # notch yerleşme süresinin (~0.2 sn) birkaç katı
HUM_BLOCK_S = 0.04  # dolgu bloğu (uğultu periyodunun tam katı); kısa blok = frekans kaymasında küçük faz hatası

# denoise
NFFT = 1024
HOP = 256
NOISE_PERCENT = 0.10
GATE_DB = 6.0
SPEECH_MARGIN_DB = 12.0
SMOOTH_FRAMES = 3
SMOOTH_BINS = 5
SPEECH_GUARD_FRAMES = 2  # konuşma karelerinin iki yanında korunan kare sayısı (hece başı/sonu yumuşak kalsın)
NOISE_MIN_DBFS = -90.0  # gürültü tabanı bunun altındaysa temizlenecek bir şey yok
DENOISE_MIN_DB = 0.5  # gürültü karelerindeki azalma bundan küçükse sonuç atılır (temiz kayıt: değişiklik yok)
PAUSE_NEAR_DB = 3.0  # tabana bu kadar yakın kareler "duraklama" sayılır
PAUSE_MIN_S = 0.1  # profil ancak en az bu uzunlukta kesintisiz bir duraklamadan geliyorsa güvenilir
FLOOR_TOLERANCE_DB = 6.0
FLOOR_BAND_HZ = (50.0, 12000.0)  # analysis gürültü tabanıyla karşılaştırma bandı (50 Hz HP, en fazla 24 kHz)

# highpass
HP_FILTFILT_FACTOR = (1.0 / (math.sqrt(2.0) - 1.0)) ** 0.25  # ≈ 1.2465: çift geçişte −3 dB noktası highpass_hz olsun
HP_F0_RATIO = 0.8  # analiz varsa kesim, konuşmacının en düşük perdesinin (f0.min_hz) %80'ini aşmaz
HP_MIN_HZ = 40.0  # perdeye göre indirilen kesim bundan aşağı inmez

# seviye
PEAK_DBFS = -1.0
MAX_GAIN_DB = 40.0

# Arayüz/entegrasyon için Türkçe etiketler
ADIM_ETIKETLERI = {
    "dc": "DC kayması giderildi",
    "declick": "Tıklar temizlendi",
    "dehum": "Şebeke uğultusu (50/60 Hz) giderildi",
    "denoise": "Arka plan gürültüsü azaltıldı",
    "highpass": "Alçak frekans gümbürtüsü süzüldü",
    "level": "Ses seviyesi dengelendi",
}
NEDEN_ETIKETLERI = {
    "noisy": "Arka plan gürültüsü",
    "hum": "Şebeke uğultusu (50/60 Hz)",
    "dc_offset": "DC kayması",
    "too_quiet": "Kayıt çok kısık",
}


# ---------- küçük yardımcılar ----------

def _mono(wav) -> np.ndarray:
    """Giriş dizisini mono float64'e çevirir (tamsayı PCM ölçeklenir, NaN/inf sıfırlanır)."""
    x = np.asarray(wav)
    if np.issubdtype(x.dtype, np.unsignedinteger):  # ör. 8 bit WAV: 128 merkezli
        half = (float(np.iinfo(x.dtype).max) + 1.0) / 2.0
        x = (x.astype(np.float64) - half) / half
    elif np.issubdtype(x.dtype, np.integer):
        info = np.iinfo(x.dtype)
        x = x.astype(np.float64) / float(max(abs(info.min), info.max))
    x = np.squeeze(np.asarray(x, dtype=np.float64))
    if x.ndim == 2:
        # soundfile düzeni (örnek, kanal); kanal-önce (kanal, örnek) de kabul edilir
        x = x.mean(axis=1) if (x.shape[1] <= 16 and x.shape[0] >= x.shape[1]) else x.mean(axis=0)
    elif x.ndim != 1:
        x = x.reshape(-1)
    if not np.all(np.isfinite(x)):
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    return x


def _rms(x: np.ndarray) -> float:
    return math.sqrt(float(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0


def _rms_db(x: np.ndarray) -> float:
    r = _rms(x)
    return round(20.0 * math.log10(r), 1) if r > 10 ** (DB_FLOOR / 20) else DB_FLOOR


def _longest_run(mask: np.ndarray) -> int:
    """Mantıksal dizideki en uzun kesintisiz True koşusunun uzunluğu."""
    m = np.asarray(mask, dtype=np.int8)
    if not m.any():
        return 0
    d = np.diff(np.concatenate(([0], m, [0])))
    return int(np.max(np.flatnonzero(d == -1) - np.flatnonzero(d == 1)))


def _number(v) -> float | None:
    """Sonlu sayıysa float, değilse None (analiz sözlüğündeki alanlar için)."""
    if isinstance(v, bool) or not isinstance(v, (int, float, np.integer, np.floating)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


# ---------- karar ----------

def should_enhance(analysis: dict | None) -> tuple[bool, list[str]]:
    """Analiz sözlüğüne (``analysis.analyze_array`` çıktısı) bakarak iyileştirme önerir.

    Nedenler (bu sırayla): ``noisy`` (snr_db < 30 ya da "noisy" sorunu), ``hum`` (sözlükte ``hum_hz`` varsa —
    analiz uğultu ölçmez; ``detect_hum`` sonucu sözlüğe eklenerek iletilebilir), ``dc_offset``, ``too_quiet``
    (aynı adlı sorun kodları). Yalnızca sözlüğe bakar; sinyal işlemez.
    """
    if not isinstance(analysis, dict) or not analysis:
        return False, []
    codes = {i.get("code") for i in (analysis.get("issues") or []) if isinstance(i, dict)}
    reasons: list[str] = []
    snr = _number(analysis.get("snr_db"))
    floor = _number(analysis.get("noise_floor_dbfs"))
    # dijital sessizlikte (taban ≤ −100 dBFS) düşük SNR gürültüden değil, konuşma yokluğundandır
    quiet_floor = floor is not None and floor <= DIGITAL_SILENCE_DB
    if "noisy" in codes or (snr is not None and snr < SNR_NOISY_DB and not quiet_floor):
        reasons.append("noisy")
    if _number(analysis.get("hum_hz")):
        reasons.append("hum")
    for code in ("dc_offset", "too_quiet"):
        if code in codes:
            reasons.append(code)
    return bool(reasons), reasons


def quality_delta(before: dict, after: dict) -> int:
    """``after.quality_score − before.quality_score`` (iyileştirme kabul ölçütü: ≥ +3)."""
    def score(a) -> float:
        v = _number(a.get("quality_score")) if isinstance(a, dict) else None
        return v if v is not None else 0.0

    return int(round(score(after) - score(before)))


# ---------- uğultu ----------

def detect_hum(wav: np.ndarray, sr: int) -> float | None:
    """50/60 Hz şebeke uğultusunu bulur: 40–70 Hz'deki en güçlü tepe, 8–25 Hz uzaktaki komşu bantların medyanından
    ≥ 12 dB yüksekse yakın olan şebeke frekansı (50.0 ya da 60.0), değilse ``None``.

    Welch PSD (Hann, nperseg 8192; daha yüksek örnekleme hızlarında aynı ≈ 2.9 Hz çözünürlük için büyütülür).
    Konuşmanın perdesi sürekli değiştiği için ortalama spektrumda dar ve sabit bir çizgi yalnızca uğultuda oluşur.
    """
    sr = int(sr)
    x = _mono(wav)
    if sr < 400:
        return None
    nper = max(HUM_NPERSEG, 1 << int(math.ceil(math.log2(sr / 3.0))))
    if x.size < nper:
        return None  # 50 ile 60 Hz'i ayıracak frekans çözünürlüğü yok
    x = x - x.mean()
    if not np.any(x):
        return None
    f, p = signal.welch(x, fs=sr, window="hann", nperseg=nper)
    band = np.flatnonzero((f >= HUM_BAND_HZ[0]) & (f <= HUM_BAND_HZ[1]))
    if band.size == 0:
        return None
    k = int(band[np.argmax(p[band])])
    if p[k] <= 0.0 or k == 0 or k >= p.size - 1 or p[k] < p[k - 1] or p[k] < p[k + 1]:
        return None  # bant kenarındaki eğim (gümbürtü, konuşma) tepe değildir
    dist = np.abs(f - f[k])
    neigh = p[(dist >= HUM_NEIGHBOR_HZ[0]) & (dist <= HUM_NEIGHBOR_HZ[1])]
    ref = float(np.median(neigh)) if neigh.size else 0.0
    if ref > 0.0 and 10.0 * math.log10(float(p[k]) / ref) < HUM_MIN_PROMINENCE_DB:
        return None
    return 50.0 if abs(f[k] - 50.0) <= abs(f[k] - 60.0) else 60.0


def _dehum(x: np.ndarray, sr: int, hum_hz: float) -> np.ndarray:
    """Temel + 2. harmonik için dar notch (Q=30), filtfilt. Kenarlar uğultu fazını sürdüren dolguyla korunur."""
    n = x.size
    freqs = [hum_hz * k for k in range(1, HUM_HARMONICS + 1) if hum_hz * k < 0.45 * sr]
    if not freqs:
        return x
    period = max(1, int(round(sr / hum_hz)))
    if n >= period:
        block = period * max(2, int(round(HUM_BLOCK_S * sr / period)))
        block = min(block, (n // period) * period)
    else:
        block = n
    pad = int(HUM_PAD_S * sr)
    reps = int(math.ceil(pad / block))
    # x[0:block] uğultu periyodunun tam katı: önüne konunca uğultu x[0]'a fazı bozulmadan bağlanır (sonda da aynı)
    xp = np.concatenate([np.tile(x[:block], reps)[-pad:], x, np.tile(x[n - block:], reps)[:pad]])
    for f0 in freqs:
        b, a = signal.iirnotch(f0, HUM_Q, fs=sr)
        xp = signal.filtfilt(b, a, xp)
    return xp[pad: pad + n]


# ---------- tık ----------

def _declick(x: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """(yamalı sinyal, tık sayısı). Ayrıntı modül belgesinde; %1 sınırı aşılırsa sinyal değişmeden döner."""
    n = x.size
    d = np.diff(x)
    if d.size < 3:
        return x, 0
    ad = np.abs(d - np.median(d))
    sigma = 1.4826 * float(np.median(ad))
    # yerel gürbüz σ: 10 ms'lik blokların MAD'i, komşu bloklarla birlikte en büyüğü
    blk = max(8, int(round(CLICK_LOCAL_MS * 1e-3 * sr)))
    nb = ad.size // blk
    if nb >= 1:
        sig_b = 1.4826 * np.median(ad[: nb * blk].reshape(nb, blk), axis=1)
        sig_b = ndimage.maximum_filter1d(sig_b, size=3, mode="nearest")
        local = np.empty(ad.size)
        local[: nb * blk] = np.repeat(sig_b, blk)
        local[nb * blk:] = sig_b[-1]
    else:
        local = np.zeros(ad.size)
    thr = np.maximum(CLICK_SIGMA * np.maximum(local, sigma), CLICK_MIN_JUMP)
    hits = np.flatnonzero(np.abs(d) > thr)
    if hits.size == 0:
        return x, 0
    # d[i] = x[i+1] − x[i]: yama [i − w, i + 1 + w] (dahil); çakışan/bitişik yamalar tek tık sayılır
    w = max(1, int(round(CLICK_PATCH_MS * 1e-3 * sr)))
    starts = np.maximum(hits - w, 0)
    ends = np.minimum(hits + 1 + w, n - 1)
    brk = np.flatnonzero(starts[1:] > ends[:-1] + 1) + 1
    s_reg = starts[np.concatenate(([0], brk))]
    e_reg = ends[np.concatenate((brk - 1, [hits.size - 1]))]
    if int(np.sum(e_reg - s_reg + 1)) > CLICK_SCAN_RATIO * n:
        return x, 0
    # onay: gerçek tık yalıtıktır (±20 ms içinde benzeri yok: gırtlak darbesi değil) ve durağan bir bağlamda durur
    # (öncesi ve sonrası benzer enerjide: patlamalı ünsüz salınımı gibi bir başlangıç değil)
    absd = np.abs(d)
    cw = max(1, int(round(CLICK_CONTEXT_MS * 1e-3 * sr)))
    regions: list[tuple[int, int]] = []
    for s, e in zip(s_reg.tolist(), e_reg.tolist()):
        peak = float(absd[s:e].max())  # tamamen bölge içindeki örnek çiftleri
        around = max(float(absd[max(0, s - 1 - cw): max(0, s - 1)].max(initial=0.0)),
                     float(absd[e + 1: e + 1 + cw].max(initial=0.0)))
        if peak < CLICK_ISOLATION * around:
            continue
        sides = [float(np.mean(np.square(v))) for v in (x[max(0, s - cw): s], x[e + 1: e + 1 + cw]) if v.size]
        if len(sides) == 2 and 10.0 * math.log10((max(sides) + 1e-20) / (min(sides) + 1e-20)) > CLICK_CONTEXT_DB:
            continue
        regions.append((s, e))
    if not regions or sum(e - s + 1 for s, e in regions) > CLICK_MAX_RATIO * n:
        return x, 0  # bu kadar "tık" gürültü ya da konuşmanın kendi yapısıdır: dokunma
    y = x.copy()
    for s, e in regions:
        left = y[s - 1] if s > 0 else (y[e + 1] if e < n - 1 else 0.0)
        right = y[e + 1] if e < n - 1 else left
        y[s: e + 1] = np.linspace(left, right, e - s + 3)[1:-1]
    return y, len(regions)


# ---------- gürültü ----------

def _denoise(x: np.ndarray, sr: int, max_reduction_db: float,
             floor_hint_db: float | None = None) -> tuple[np.ndarray, float] | None:
    """Spektral kapı. (temizlenmiş sinyal, gürültü karelerinde ölçülen azalma dB) ya da yapılacak iş yoksa None."""
    n = x.size
    if n < NFFT:
        return None
    kw = dict(fs=sr, window="hann", nperseg=NFFT, noverlap=NFFT - HOP, nfft=NFFT)
    freqs, _, Z = signal.stft(x, boundary="zeros", padded=True, **kw)
    P = Z.real * Z.real + Z.imag * Z.imag
    n_frames = P.shape[1]
    win = signal.get_window("hann", NFFT)
    c = float(win.sum()) ** 2 / (NFFT * float(np.dot(win, win)))
    wts = np.full(P.shape[0], 2.0)  # tek taraflı spektrum: DC ve Nyquist bir, diğerleri iki kez sayılır
    wts[0] = wts[-1] = 1.0
    ms = c * (wts @ P)  # kare başına ortalama güç (durağan sinyalde örnek varyansına eşit, dBFS ölçeğinde)

    # gürültü profili: kenar dolgusu içermeyen, dijital sessizlik olmayan karelerin en sessiz %10'u
    centers = np.arange(n_frames) * HOP  # kare t'nin merkezi = t·HOP. örneği (boundary="zeros")
    live = ms > 10 ** (DIGITAL_SILENCE_DB / 10)
    pool = np.flatnonzero(live & (centers >= NFFT // 2) & (centers + NFFT // 2 <= n))
    if pool.size < 3:
        pool = np.flatnonzero(live)
    if pool.size == 0:
        return None
    k = max(1, int(math.ceil(NOISE_PERCENT * pool.size)))
    quiet = pool[np.argsort(ms[pool], kind="stable")[:k]]  # sessizden gürültüye sıralı
    # taban: en sessiz %10'un alt %20'si (duraklamalar karelerin %10'undan azsa kümeye hece çukurları karışır)
    floor_ms = float(ms[quiet[k // 5]])
    if 10.0 * math.log10(floor_ms) < NOISE_MIN_DBFS:
        return None
    near_ms = floor_ms * 10 ** (PAUSE_NEAR_DB / 10)
    # duraklamasız (sürekli) konuşmada en sessiz kareler hece çukurlarıdır; o "profil" konuşmayı keser: dokunma
    if _longest_run(live & (ms <= near_ms)) < math.ceil(PAUSE_MIN_S * sr / HOP):
        return None
    quiet = quiet[ms[quiet] <= near_ms]  # normal kayıtta kümenin tamamı; karışık kümede yalnızca gürültü kareleri
    profile = np.median(P[:, quiet], axis=1)
    if floor_hint_db is not None:
        band = (freqs >= FLOOR_BAND_HZ[0]) & (freqs <= min(FLOOR_BAND_HZ[1], 0.5 * sr))
        own = float(np.median(2.0 * c * P[band][:, quiet].sum(axis=0)))
        if own > 0.0:
            excess = 10.0 * math.log10(own) - (floor_hint_db + FLOOR_TOLERANCE_DB)
            if excess > 0.0:
                profile = profile * 10 ** (-excess / 10)

    g_min = 10 ** (-float(max_reduction_db) / 20)
    above = P >= profile[:, None] * 10 ** (GATE_DB / 10)
    gain = np.where(above, 1.0, g_min)
    # yumuşatma (frekansta 5 bin × zamanda 3 kare): önce medyan — yalıtık eşik aşımları (müzikal gürültü
    # kaynağı) atılır, kümelenmiş konuşma enerjisi kalır —, sonra ortalama ile yumuşak geçiş
    size = (SMOOTH_BINS, SMOOTH_FRAMES)
    gain = ndimage.uniform_filter(ndimage.median_filter(gain, size=size, mode="nearest"), size=size, mode="nearest")
    speech = ms > c * float(wts @ profile) * 10 ** (SPEECH_MARGIN_DB / 10)
    if SPEECH_GUARD_FRAMES > 0 and speech.any():
        speech = np.convolve(speech.astype(np.int32), np.ones(2 * SPEECH_GUARD_FRAMES + 1, np.int32), "same") > 0
    gain[above & speech[None, :]] = 1.0  # konuşmada eşik üstü binlere (harmoniklere) dokunulmaz
    np.clip(gain, g_min, 1.0, out=gain)
    _, y = signal.istft(Z * gain, input_onesided=True, boundary=True, **kw)
    y = y[:n] if y.size >= n else np.concatenate([y, np.zeros(n - y.size)])

    # azalmayı gürültü karelerinin (profil kareleri) merkez bölgelerinde ölç
    idx = (quiet[:, None] * HOP + np.arange(-(HOP // 2), HOP - HOP // 2)[None, :]).ravel()
    idx = idx[(idx >= 0) & (idx < n)]
    r_in, r_out = _rms(x[idx]), _rms(y[idx])
    reduction = 20.0 * math.log10(r_in / r_out) if r_in > 0.0 and r_out > 0.0 else 0.0
    return y, reduction


# ---------- yüksek geçiren ----------

def _highpass_cutoff(highpass_hz, analysis: dict | None) -> float:
    """Etkin kesim frekansı (Hz; 0 = kapalı). Analizde perde varsa derin seslerin temel frekansı kesilmesin diye
    ``f0.min_hz × 0.8``'e (en az 40 Hz) indirilir; hiçbir zaman ``highpass_hz``'in üstüne çıkmaz."""
    hp = _number(highpass_hz) or 0.0
    if hp <= 0.0:
        return 0.0
    f0 = analysis.get("f0") if isinstance(analysis, dict) else None
    f0_min = _number(f0.get("min_hz")) if isinstance(f0, dict) else None
    if f0_min and f0_min > 0.0:
        hp = min(hp, max(HP_MIN_HZ, HP_F0_RATIO * f0_min))
    return hp


# ---------- ana işlev ----------

def enhance_reference(wav: np.ndarray, sr: int, analysis: dict | None = None, *, denoise: bool = True,
                      dehum: bool = True, declick: bool = True, highpass_hz: int = 70, target_dbfs: float = -20.0,
                      max_reduction_db: float = 12.0) -> tuple[np.ndarray, dict]:
    """Referans kaydını korumacı biçimde temizler; (float32 mono sinyal, rapor) döndürür.

    Rapor: ``{"applied": [...], "noise_reduction_db", "hum_hz", "clicks_removed", "gain_db", "before_rms_db",
    "after_rms_db"}``. ``applied`` sinyali gerçekten değiştiren adımları sırasıyla listeler ("dc", "declick",
    "dehum", "denoise", "highpass", "level"; Türkçe karşılıkları ``ADIM_ETIKETLERI``). ``highpass_hz`` ≤ 0 ya da
    ``None`` yüksek geçireni kapatır. ``analysis`` (aynı kaydın ``analyze_array`` çıktısı) verilirse
    ``noise_floor_dbfs`` kapı eşiğini tutarlı kılmak, ``f0.min_hz`` derin seslerde yüksek geçiren kesimini
    temel frekansın altında tutmak için kullanılır.
    """
    sr = int(sr)
    if sr <= 0:
        raise ValueError("Örnekleme hızı pozitif olmalı.")
    x = _mono(wav)
    before_db = _rms_db(x)
    report: dict = {"applied": [], "noise_reduction_db": 0.0, "hum_hz": None, "clicks_removed": 0, "gain_db": 0.0,
                    "before_rms_db": before_db, "after_rms_db": before_db}
    if x.size < MIN_DURATION_S * sr or _rms(x) <= SILENCE_RMS:
        return x.astype(np.float32), report  # çok kısa ya da sessiz: olduğu gibi
    applied: list[str] = report["applied"]

    # 1) DC
    mean = float(x.mean())
    x = x - mean
    if abs(mean) > DC_REPORT_RATIO * _rms(x):
        applied.append("dc")

    if _rms(x) > SILENCE_RMS:  # yalnızca DC'den ibaret sinyalde başka işlem yok
        # 2) tıklar
        if declick:
            x, clicks = _declick(x, sr)
            if clicks:
                applied.append("declick")
                report["clicks_removed"] = clicks
        # 3) uğultu
        if dehum:
            hum = detect_hum(x, sr)
            if hum is not None:
                x = _dehum(x, sr, hum)
                applied.append("dehum")
                report["hum_hz"] = hum
        # 4) gürültü
        if denoise and max_reduction_db > 0:
            hint = _number(analysis.get("noise_floor_dbfs")) if isinstance(analysis, dict) else None
            if hint is not None and hint <= DIGITAL_SILENCE_DB:
                hint = None
            res = _denoise(x, sr, max_reduction_db, hint)
            if res is not None and res[1] >= DENOISE_MIN_DB:
                x, reduction = res
                applied.append("denoise")
                report["noise_reduction_db"] = round(reduction, 1) + 0.0
        # 5) yüksek geçiren
        hp = _highpass_cutoff(highpass_hz, analysis)
        if 0.0 < hp < 0.45 * sr:
            sos = signal.butter(2, hp / HP_FILTFILT_FACTOR, btype="highpass", fs=sr, output="sos")
            x = signal.sosfiltfilt(sos, x)
            applied.append("highpass")
        # 6) seviye: RMS hedefi, tepe −1 dBFS, kazanç en fazla +40 dB
        r_in = _rms(x)
        if r_in > SILENCE_RMS:
            y = rms_normalize(x, float(target_dbfs), PEAK_DBFS).astype(np.float64)
            gain = _rms(y) / r_in
            cap = db_to_amp(MAX_GAIN_DB)
            if gain > cap:
                y, gain = x * cap, cap
            x = y
            gain_db = 20.0 * math.log10(gain) if gain > 0.0 else 0.0
            if abs(gain_db) >= 0.05:
                applied.append("level")
                report["gain_db"] = round(gain_db, 2) + 0.0

    out = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    report["after_rms_db"] = _rms_db(out)
    return out, report


def enhance_file(src: Path, dst: Path, backup: Path | None = None) -> dict:
    """Dosyayı okur, iyileştirir, ``dst``'ye yazar; rapora önce/sonra analizini ve puan farkını ekler.

    ``backup`` verilirse işe başlamadan önce ``src`` oraya kopyalanır (varsa üzerine yazılır). ``dst`` ``src`` ile
    aynı olabilir; yazma geçici dosya + ``os.replace`` ile yapılır (yarım dosya kalmaz). Kaynakla aynı biçime
    yazılıyorsa örnek biçimi (PCM_16, FLOAT…) korunur. Dönüş: ``enhance_reference`` raporu + ``"before"``,
    ``"after"`` (``analyze_array``) ve ``"delta"`` (``quality_delta``).
    """
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {src}")
    if backup is not None:
        backup = Path(backup)
        if backup.resolve() != src.resolve():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, backup)
    try:
        info = sf.info(str(src))
        data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    except Exception as e:  # noqa: BLE001 - kullanıcıya anlaşılır hata
        raise ValueError(f"Ses dosyası okunamadı: {src.name}") from e
    wav = data.mean(axis=1)

    before = analyze_array(wav, sr)
    out, report = enhance_reference(wav, sr, before)
    after = analyze_array(out, sr)

    dst.parent.mkdir(parents=True, exist_ok=True)
    subtype = info.subtype if dst.suffix.lower() == src.suffix.lower() else None
    tmp = dst.with_name(f".{dst.stem}.iyilestirme{dst.suffix}")
    try:
        sf.write(str(tmp), out, sr, subtype=subtype)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)

    report.update(before=before, after=after, delta=quality_delta(before, after))
    return report
