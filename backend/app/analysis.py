"""Referans kaydı analizi — yüklenen kaydı "dinleyen kulak".

Ses klonlamada sonucun kalitesini en çok referans kayıt belirler. Bu modül kaydı ölçer, 0–100 arası puanlar,
Türkçe ve somut öneriler üretir; ayrıca sentez motoruna kişinin doğal ritmini (duraklama ölçeği), oda tonunu ve
gerçek nefesini verir. Sözleşme: ``docs/SOZLESME.md`` bölüm 4.

    analyze_reference(path) -> dict
    analyze_array(wav, sr) -> dict
    extract_noise_floor(wav, sr, seconds=0.8) -> np.ndarray | None
    extract_breath(wav, sr) -> np.ndarray | None

Ölçüm yöntemleri (özet):

* Seviye: tepe/RMS (dBFS), DC kayması = |ortalama| / tepe, kırpılma = |x| ≥ 0.985 olan örnek oranı; ayrıca
  ardışık ≥ 3 örneklik düz tepeler (tavana ya da kaydın tepe seviyesine yapışmış, değişmeyen örnekler) sayılır.
* Çerçeveleme: 25 ms pencere, 10 ms atlama; kare RMS (dB). Gürültü tabanı = en düşük %10 karenin medyanı
  (dijital sıfırlar hariç). Konuşma eşiği = max(taban + 12 dB, -45 dBFS); çok kısık kayıtlarda -45 dBFS, kaydın tepe
  seviyesinin 35 dB altına kaydırılır. Nefes olduğu anlaşılan kareler konuşmadan ayıklanır; 100 ms'ye kadar boşluklar
  doldurulur, 50 ms'den kısa parçalar atılır.
* SNR = konuşma karelerinin ortalama gücü (dB) − gürültü tabanı.
* Bant genişliği: konuşma karelerinin ortalama güç spektrumundan gürültü spektrumu çıkarılır (konuşmanın gürültüden
  istatistiksel olarak ayrışmadığı frekanslar sıfırlanır), konuşmanın doğal -6 dB/oktav eğimi f² ağırlığıyla
  dengelenir; toplam enerjinin %99'unun altında kaldığı frekans (rolloff). Eğim düzeltmesi olmadan tam bantlı gerçek
  kayıtlar bile ~2 kHz çıkıp yanlışlıkla "telefon kaydı" sayılıyordu; bu hâliyle ölçü kanal bant genişliğini verir
  (telefon < 4 kHz). Gürültü tabanı geniş bantlıyken ölçülen düşük değer kanal kısıtı değil gürültü maskelemesidir:
  o durumda ayrıca "dar bant" cezası verilmez (gürültü uyarısı yeterli).
* Yankı: konuşma bitişlerinde enerjinin düşüş hızı. Seviyenin tabana inmeden önceki son ≤ 15 dB'lik inişinin süresi
  ölçülür (son hecenin doğal kısılması değil, kaynak sustuktan sonraki oda sönümü burada görünür) ve "200 ms'de kaç dB
  düşer" hızına çevrilir; böylece gürültü tabanının yüksekliğinden bağımsız kalır. İniş bölgesi spektral olarak gürültü
  kadar düzse (spektral düzlük ≈ taban düzlüğü) o bitiş yankı kanıtı sayılmaz. Bitişlerin 75. yüzdeliği:
  > 25 dB düşük, 15–25 orta, < 15 yüksek.
* F0: ``librosa.pyin`` (60–450 Hz), 16 kHz'e indirilmiş, ilk konuşmadan itibaren en fazla 30 sn; yalnızca konuşma
  karelerindeki sesli kareler. ``range_semitones`` = p5–p95 aralığı (yarım ton), ``std_semitones`` = perdenin medyana
  göre yarım ton cinsinden standart sapması (tonlama canlılığı; kıyaslama betiği ``app.bench`` bunu kullanır). pyin nefesli/gürültülü seste sesli kare bulamazsa yin perdesi, o perdedeki
  periyodiklikle doğrulanarak kullanılır. Etiket: medyan < 165 erkek, > 185 kadın, arası belirsiz.
* Konuşma hızı: 300–2500 Hz (ünlü bölgesi) RMS zarfı 8 Hz alçak geçirenle yumuşatılır; konuşma içindeki tepeler
  (hece çekirdekleri, ≥ 80 ms arayla, belirginlik = eşik payının %15'i ≈ 1.8 dB) / konuşma süresi.
* Duraklama: konuşma segmentleri arasındaki 150–2500 ms sessizlikler; ``scale = clip(medyan / 400 ms, 0.7, 1.5)``.
* Nefes: konuşma dışı (eşiği aşsa bile ünlüye yapışık olmayan), tabanın ≥ 8 dB üstünde, 120–600 ms, spektral
  merkezi 1–5 kHz, sıfır geçişi yüksek, periyodikliği (normalize otokorelasyon tepesi) düşük bölgeler. Sözcük sonu
  sürtünmelileri (ş, h) ünlüye yapışık oldukları için nefes sayılmaz.

Tüm sayılar yuvarlanır (çoğu 1–2 ondalık; küçük oranlar olan clipping_ratio 5, dc_offset 4 ondalık) ve yerleşik
Python tipleriyle döner (``json.dumps`` doğrudan çalışır). Çok uzun kayıtlarda ölçümler ilk 180 sn'den yapılır.
"""
from __future__ import annotations

import math
import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from .audio import TARGET_SR, db_to_amp, fade, to_wav

# ---------- sabitler ----------

FRAME_MS = 25.0
HOP_MS = 10.0
DB_FLOOR = -120.0  # log(0) yerine kullanılan alt sınır
DIGITAL_SILENCE_DB = -100.0  # bunun altı "dijital sessizlik": oda tonu sayılmaz
CLIP_LEVEL = 0.985
SPEECH_MIN_DBFS = -45.0
SPEECH_MARGIN_DB = 12.0
MAX_ANALYSIS_S = 180.0  # çerçeve analizi en fazla bu kadar (uzun dosyalarda bellek/süre sınırı)
READ_MAX_S = 600.0  # analyze_reference en fazla bu kadarını okur
F0_MAX_S = 30.0
F0_SR = 16000
F0_FMIN, F0_FMAX = 60.0, 450.0
PAUSE_MIN_MS, PAUSE_MAX_MS = 150.0, 2500.0
PAUSE_REF_MS = 400.0
BREATH_MIN_MS, BREATH_MAX_MS = 120.0, 600.0
BREATH_TARGET_DBFS = -34.0
NOISE_FLOOR_MIN_S = 0.3

GRADES = ((85, "mükemmel"), (70, "iyi"), (50, "orta"), (0, "zayıf"))
_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
EXCELLENT_TIP = "Harika kayıt — bu ses klonlama için ideal."


# ---------- küçük yardımcılar ----------

def _num(v: float, nd: int = 1) -> float:
    """JSON'a güvenli, yuvarlanmış Python float'ı (NaN/inf → 0.0, -0.0 → 0.0)."""
    v = float(v)
    if not math.isfinite(v):
        return 0.0
    return round(v, nd) + 0.0


def _db(power: float | np.ndarray) -> float | np.ndarray:
    """Güç → dB (alt sınır DB_FLOOR)."""
    return 10.0 * np.log10(np.maximum(power, 10 ** (DB_FLOOR / 10)))


def _mono(wav) -> np.ndarray:
    """Her türlü giriş dizisini mono float64'e çevirir (tamsayı PCM ölçeklenir, NaN/inf temizlenir)."""
    x = np.asarray(wav)
    if np.issubdtype(x.dtype, np.unsignedinteger):  # ör. 8 bit WAV: 128 merkezli
        half = (float(np.iinfo(x.dtype).max) + 1.0) / 2.0
        x = (x.astype(np.float64) - half) / half
    elif np.issubdtype(x.dtype, np.integer):
        info = np.iinfo(x.dtype)
        x = x.astype(np.float64) / float(max(abs(info.min), info.max))
    x = np.asarray(x, dtype=np.float64)
    x = np.squeeze(x)
    if x.ndim == 2:
        # soundfile düzeni (örnek, kanal); kanal-önce (kanal, örnek) dizileri de kabul edilir
        if x.shape[1] <= 16 and x.shape[0] >= x.shape[1]:
            x = x.mean(axis=1)
        else:
            x = x.mean(axis=0)
    elif x.ndim > 2:
        x = x.reshape(-1)
    elif x.ndim == 0:
        x = x.reshape(1)
    if not np.all(np.isfinite(x)):
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    return x


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Mantıksal dizideki True koşularını [(başlangıç, bitiş)) listesi olarak döndürür."""
    m = np.asarray(mask, dtype=bool)
    if m.size == 0:
        return []
    d = np.diff(np.concatenate(([0], m.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def _fill_gaps(mask: np.ndarray, max_gap: int) -> np.ndarray:
    """İki True koşusu arasındaki ≤ max_gap uzunluktaki boşlukları doldurur."""
    out = np.array(mask, dtype=bool)
    runs = _runs(out)
    for (_, b0), (a1, _) in zip(runs, runs[1:]):
        if a1 - b0 <= max_gap:
            out[b0:a1] = True
    return out


def _drop_short(mask: np.ndarray, min_len: int) -> np.ndarray:
    out = np.array(mask, dtype=bool)
    for a, b in _runs(out):
        if b - a < min_len:
            out[a:b] = False
    return out


def _dilate(mask: np.ndarray, k: int) -> np.ndarray:
    """Her True'yu iki yana k kare genişletir (uzunluk korunur)."""
    m = np.asarray(mask, dtype=bool)
    if k <= 0 or not m.any():
        return m.copy()
    c = np.concatenate(([0], np.cumsum(m, dtype=np.int64)))
    i = np.arange(m.size)
    return (c[np.minimum(i + k + 1, m.size)] - c[np.maximum(i - k, 0)]) > 0


def _resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to:
        return x
    g = math.gcd(int(sr_from), int(sr_to))
    return signal.resample_poly(x, int(sr_to) // g, int(sr_from) // g)


def _nccf_max(seg: np.ndarray, sr: int) -> float:
    """60–450 Hz gecikme aralığında normalize çapraz-korelasyonun en büyüğü (0: gürültü, 1: tam periyodik)."""
    seg = np.asarray(seg, dtype=np.float64)
    seg = seg - seg.mean()
    n = len(seg)
    lmin = max(1, int(sr / F0_FMAX))
    lmax = min(int(sr / F0_FMIN), n - n // 3)
    if n < 8 or lmax <= lmin:
        return 0.0
    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    spec = np.fft.rfft(seg, nfft)
    r = np.fft.irfft(spec * np.conj(spec), nfft)[: lmax + 1]
    cs = np.concatenate(([0.0], np.cumsum(seg * seg)))
    lags = np.arange(lmin, lmax + 1)
    e1 = cs[n - lags]
    e2 = cs[n] - cs[lags]
    nccf = r[lags] / np.sqrt(e1 * e2 + 1e-20)
    return float(np.clip(np.max(nccf), 0.0, 1.0))


def _periodicity(seg: np.ndarray, sr: int) -> float:
    """Bölgenin periyodikliği: 50 ms'lik alt pencerelerdeki NCCF tepesinin medyanı."""
    w = int(0.05 * sr)
    h = int(0.025 * sr)
    if len(seg) <= w or h <= 0:
        return _nccf_max(seg, sr)
    vals = [_nccf_max(seg[i: i + w], sr) for i in range(0, len(seg) - w + 1, h)]
    return float(np.median(vals))


# ---------- çekirdek ölçüm ----------

@dataclass
class _Olcum:
    """Çerçeve tabanlı ortak ölçümler (analyze_array ve extract_* fonksiyonları paylaşır)."""

    x: np.ndarray  # analiz sinyali: DC'si alınmış, 50 Hz yüksek geçirgen, en fazla TARGET_SR
    sr: int
    win: int
    hop: int
    n: int
    power: np.ndarray  # kare başına ortalama güç
    level: np.ndarray  # kare başına RMS (dB)
    floor_db: float
    thr_db: float
    ref_db: float  # konuşma karelerinin 90. yüzdelik seviyesi
    raw: np.ndarray  # eşik üstü kareler
    spec: np.ndarray  # kare güç spektrumları (float32)
    freqs: np.ndarray
    centroid: np.ndarray
    flatness: np.ndarray
    zcr_hz: np.ndarray  # sıfır geçiş oranının eşdeğer frekansı (Hz)
    breath_mask: np.ndarray
    breaths: list = field(default_factory=list)
    speech: np.ndarray = None  # nihai konuşma maskesi
    segments: list = field(default_factory=list)
    noise_mask: np.ndarray = None  # oda tonu/gürültü kareleri

    @property
    def hop_ms(self) -> float:
        return 1000.0 * self.hop / self.sr

    @property
    def win_ms(self) -> float:
        return 1000.0 * self.win / self.sr

    def frames_to_ms(self, k: int) -> float:
        """k ardışık karenin kapsadığı yaklaşık süre (pencere taşmasıyla birlikte)."""
        return k * self.hop_ms + (self.win_ms - self.hop_ms)

    def frame_span(self, a: int, b: int) -> tuple[float, float]:
        """[a, b) karelerinin kapsadığı zaman aralığı (sn)."""
        return a * self.hop / self.sr, ((b - 1) * self.hop + self.win) / self.sr


def _olc(wav, sr: int) -> _Olcum:
    """Ortak çerçeve analizi: seviyeler, gürültü tabanı, eşik, spektral özellikler, nefesler, konuşma maskesi."""
    sr = int(sr)
    if sr <= 0:
        raise ValueError("Örnekleme hızı pozitif olmalı.")
    x = _mono(wav)[: int(MAX_ANALYSIS_S * sr)]
    if sr > TARGET_SR:
        x = _resample(x, sr, TARGET_SR)
        sr = TARGET_SR
    x = x - (x.mean() if x.size else 0.0)
    if x.size > 32 and sr >= 1000:
        sos = signal.butter(2, 50.0, btype="highpass", fs=sr, output="sos")
        x = signal.sosfilt(sos, x)

    win = max(8, int(round(sr * FRAME_MS / 1000)))
    hop = max(1, int(round(sr * HOP_MS / 1000)))
    if x.size < win:
        x = np.concatenate([x, np.zeros(win - x.size)])
    n = 1 + (x.size - win) // hop
    starts = np.arange(n) * hop
    cs = np.concatenate(([0.0], np.cumsum(x * x)))
    power = np.maximum((cs[starts + win] - cs[starts]) / win, 0.0)
    level = _db(power)

    # gürültü tabanı: en düşük %10 karenin medyanı (dijital sıfırlar ölçüyü bozmasın)
    valid = level > DIGITAL_SILENCE_DB
    pool = level[valid] if valid.sum() >= max(3, int(0.05 * n)) else level
    k = max(1, int(math.ceil(0.10 * pool.size)))
    floor_db = float(np.median(np.sort(pool)[:k]))
    # konuşma eşiği = max(taban + 12 dB, -45 dBFS). -45 dBFS, tepeleri ~-10 dBFS olan normal seviyeli kayıt içindir;
    # çok kısık kayıtta (tepeler bile düşük) konuşmanın çoğunu kesmesin diye tepe seviyesinin 35 dB altına kaydırılır
    loud_db = float(np.percentile(level, 95))
    thr_db = max(floor_db + SPEECH_MARGIN_DB, min(SPEECH_MIN_DBFS, loud_db - 35.0))
    raw = level >= thr_db
    ref_db = float(np.percentile(level[raw], 90)) if raw.any() else floor_db + 20.0

    # spektral özellikler (Hann pencereli kareler)
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop][:n]
    window = np.hanning(win)
    nb = win // 2 + 1
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    spec = np.empty((n, nb), dtype=np.float32)
    centroid = np.empty(n)
    flatness = np.empty(n)
    for c in range(0, n, 2048):
        ps = np.abs(np.fft.rfft(frames[c: c + 2048] * window, axis=1)) ** 2
        spec[c: c + 2048] = ps
        body = ps[:, 1:]
        tot = body.sum(axis=1) + 1e-20
        centroid[c: c + 2048] = (body @ freqs[1:]) / tot
        flatness[c: c + 2048] = np.exp(np.mean(np.log(body + 1e-20), axis=1)) / (tot / body.shape[1])

    sb = np.signbit(x)
    zc = np.concatenate(([0], np.cumsum(sb[1:] != sb[:-1])))
    zcr = (zc[starts + win - 1] - zc[starts]) / float(win - 1)
    zcr_hz = zcr * sr / 2.0

    o = _Olcum(x=x, sr=sr, win=win, hop=hop, n=n, power=power, level=level, floor_db=floor_db, thr_db=thr_db,
               ref_db=ref_db, raw=raw, spec=spec, freqs=freqs, centroid=centroid, flatness=flatness, zcr_hz=zcr_hz,
               breath_mask=np.zeros(n, dtype=bool))

    o.breaths, o.breath_mask = _detect_breaths(o)
    speech = raw & ~o.breath_mask
    speech = _fill_gaps(speech, int(round(100.0 / o.hop_ms)))
    speech = _drop_short(speech, int(round(50.0 / o.hop_ms)))
    o.speech = speech
    o.segments = _runs(speech)
    o.noise_mask = (~_dilate(speech, int(round(50.0 / o.hop_ms))) & ~o.breath_mask
                    & (level <= floor_db + 6.0) & (level > DIGITAL_SILENCE_DB))
    return o


def _detect_breaths(o: _Olcum) -> tuple[list[dict], np.ndarray]:
    """Nefes bölgelerini bulur: sessiz-ama-taban-üstü, gürültümsü (sözsüz), 1–5 kHz merkezli, 120–600 ms."""
    n = o.n
    mask = np.zeros(n, dtype=bool)
    cand = ((o.level >= o.floor_db + 8.0) & (o.level <= o.ref_db - 6.0) & (o.zcr_hz >= 700.0)
            & (o.centroid >= 700.0) & (o.centroid <= 6000.0))
    cand = _fill_gaps(cand, 2)
    speech_like = o.raw & ~cand
    near = max(1, int(round(30.0 / o.hop_ms)))
    out: list[dict] = []
    for a, b in _runs(cand):
        dur = o.frames_to_ms(b - a)
        if not (BREATH_MIN_MS <= dur <= BREATH_MAX_MS):
            continue
        p = o.power[a:b]
        lvl = float(_db(p.mean()))
        cen = float((o.centroid[a:b] * p).sum() / (p.sum() + 1e-20))
        if not (1000.0 <= cen <= 5000.0):
            continue
        if float(np.mean(o.zcr_hz[a:b])) < 800.0:
            continue
        left = bool(speech_like[max(0, a - near): a].any())
        right = bool(speech_like[b: b + near].any())
        if left:  # ünlüye yapışık sürtünmeli ünsüz (ş, h...) — nefes değil
            continue
        if right and (dur < 150.0 or lvl > o.ref_db - 12.0):
            continue
        s0 = a * o.hop
        s1 = (b - 1) * o.hop + o.win
        per = _periodicity(o.x[s0:s1], o.sr)
        if per >= 0.5:
            continue
        out.append({"start": a, "end": b, "level_db": lvl, "snr_db": lvl - o.floor_db, "periodicity": per,
                    "dur_ms": dur})
        mask[a:b] = True
    return out, mask


# ---------- ölçüm bileşenleri ----------

def _clipping(x: np.ndarray, peak: float) -> tuple[float, int, float]:
    """(|x| ≥ 0.985 oranı, düz tepe sayısı, düz tepe örnek oranı) — bellek dostu, parça parça."""
    n = x.size
    if n == 0:
        return 0.0, 0, 0.0
    chunk = 1 << 20
    hard = 0
    flat_pair = np.zeros(max(0, n - 1), dtype=bool)
    for i in range(0, n, chunk):
        xs = x[i: i + chunk + 1]
        a = np.abs(xs)
        hard += int(np.count_nonzero(a[: chunk] >= CLIP_LEVEL))
        if peak <= 1e-6 or xs.size < 2:
            continue
        d = np.abs(np.diff(xs))
        lo = np.minimum(a[1:], a[:-1])
        # tavanda (≥ 0.985) neredeyse sabit ya da tepe seviyesinde birebir aynı kalan ardışık örnek çiftleri
        flat_pair[i: i + d.size] = (lo >= 0.9 * peak) & (((lo >= CLIP_LEVEL) & (d <= 1e-4)) | (d <= 1e-6))
    runs = [(s, e) for s, e in _runs(flat_pair) if e - s >= 2]  # ≥ 2 çift = ≥ 3 örnek
    flat_samples = sum(e - s + 1 for s, e in runs)
    return hard / n, len(runs), flat_samples / n


def _snr(o: _Olcum) -> float:
    sp = o.raw & ~o.breath_mask
    if sp.sum() >= 10:
        return float(_db(o.power[sp].mean()) - o.floor_db)
    # konuşma yok denecek kadar az: en iyi durum dinamiği
    return float(max(0.0, np.percentile(o.level, 95) - o.floor_db))


def _rolloff99(spectrum: np.ndarray, freqs: np.ndarray) -> int:
    """f² ağırlıklı (konuşmanın -6 dB/oktav eğimi dengelenmiş) güç spektrumunda enerjinin %99'unun altındaki frekans."""
    w = freqs * freqs
    w[freqs < 80.0] = 0.0
    e = np.maximum(spectrum, 0.0) * w
    tot = float(e.sum())
    if tot <= 0.0:
        return 0
    i = int(np.searchsorted(np.cumsum(e), 0.99 * tot))
    return int(round(float(freqs[min(i, freqs.size - 1)]) / 10.0) * 10)


def _bandwidth(o: _Olcum) -> tuple[int, int]:
    """(konuşmanın bant genişliği, gürültü tabanının bant genişliği) — Hz.

    Konuşma spektrumundan gürültü spektrumu çıkarılır; konuşmanın gürültüden istatistiksel olarak ayrışmadığı
    frekanslar sıfırlanır. Gürültü tabanının kendi bant genişliği, düşük ölçümün kanal kısıtından mı (telefon: gürültü
    de dar bantlı) yoksa gürültünün yüksek frekansları örtmesinden mi kaynaklandığını ayırt etmek için döner.
    """
    sp = o.raw & ~o.breath_mask
    if sp.sum() < 5:
        return 0, 0
    S = o.spec[sp].mean(axis=0, dtype=np.float64)
    nm = o.noise_mask
    if nm.sum() < 5:
        valid = np.flatnonzero(o.level > DIGITAL_SILENCE_DB)
        nm = np.zeros(o.n, dtype=bool)
        if valid.size:
            k = max(1, int(0.1 * valid.size))
            nm[valid[np.argsort(o.level[valid])[:k]]] = True
    N = o.spec[nm].mean(axis=0, dtype=np.float64) if nm.any() else np.zeros_like(S)
    k = max(1, int(round(120.0 / (o.sr / o.win))))
    if k > 1:
        ker = np.ones(k) / k
        S = np.convolve(S, ker, mode="same")
        N = np.convolve(N, ker, mode="same")
    # kapı ortalamaların istatistiksel belirsizliğine göre ayarlanır: gürültü az kareyle ölçüldüyse daha temkinli
    gate = float(np.clip(1.0 + 3.0 * math.sqrt(1.0 / (sp.sum() * k) + 1.0 / (max(1, nm.sum()) * k)), 1.2, 2.0))
    clean = np.where(S >= gate * N, S - N, 0.0)
    return _rolloff99(clean, o.freqs), (_rolloff99(N, o.freqs) if nm.any() else 0)


def _reverb(o: _Olcum) -> tuple[str, float | None]:
    """Konuşma bitişlerindeki enerji düşüş hızından yankı sınıfı ve 200 ms'deki düşüş (dB).

    Her bitişte, seviyenin tabana inmeden önceki son ≤ 15 dB'lik inişinin süresi ölçülür (son hecenin doğal
    kısılması değil, kaynak sustuktan sonraki oda sönümü burada görünür) ve "200 ms'de kaç dB" hızına çevrilir.
    Böylece ölçü gürültü tabanının yüksekliğinden bağımsız kalır.
    """
    lv = o.level
    segs = o.segments
    look = int(round(300.0 / o.hop_ms))
    horizon = int(round(800.0 / o.hop_ms))
    min_gap = int(round(150.0 / o.hop_ms))
    long_gap = int(round(400.0 / o.hop_ms))
    floor_flat = float(np.median(o.flatness[o.noise_mask])) if o.noise_mask.any() else 1.0
    drops: list[float] = []
    for k, (a, b) in enumerate(segs):
        nxt = segs[k + 1][0] if k + 1 < len(segs) else o.n
        if nxt - b < min_gap:
            continue
        lo = max(a, b - look)
        p = lo + int(np.argmax(lv[lo:b]))
        peak = float(lv[p])
        # alt sınır: duraklamanın kendi gürültü düzeyi (durağan olmayan gürültüde küresel tabandan yüksek olabilir)
        pause_lv = lv[b:nxt]
        bottom = max(o.floor_db + 6.0, float(np.percentile(pause_lv, 10)) + 3.0)
        D = min(15.0, peak - bottom)
        if D < 8.0:
            continue  # ölçülebilir iniş yok (çok düşük SNR ya da yumuşak bitiş)
        top = bottom + D
        end = min(nxt, p + horizon)
        tail = lv[p:end]
        reached = np.flatnonzero(tail <= bottom)
        if reached.size:
            j_lo = int(reached[0])
            above = np.flatnonzero(tail[:j_lo] >= top)
            j_hi = int(above[-1]) if above.size else 0
            # alt-kare doğrusal ara değerleme ile iniş süresi
            v0, v1 = float(tail[j_hi]), float(tail[min(j_hi + 1, j_lo)])
            f_hi = (v0 - top) / max(v0 - v1, 1e-9) if j_hi + 1 <= j_lo else 0.0
            u0, u1 = float(tail[j_lo - 1]), float(tail[j_lo])
            f_lo = (u0 - bottom) / max(u0 - u1, 1e-9)
            t_ms = max((j_lo - 1 + f_lo - j_hi - min(f_hi, 1.0)) * o.hop_ms, 0.5 * o.hop_ms)
            drop200 = D / t_ms * 200.0
            region = slice(p + j_hi, p + j_lo + 1)
        else:
            if nxt - b < long_gap:
                continue  # kısa duraklamada iniş tamamlanmadı: karar verilemez
            t_ms = max((tail.size - 1) * o.hop_ms, o.hop_ms)
            drop200 = (peak - float(tail.min())) / t_ms * 200.0
            region = slice(p, end)
        # iniş bölgesi gürültü gibi düzse (spektral düzlük ≈ taban) bu bitiş yankı kanıtı değildir
        reg_flat = o.flatness[region]
        if reg_flat.size and float(np.median(reg_flat)) >= 0.8 * floor_flat:
            continue
        drops.append(min(drop200, 60.0))
    if not drops:
        return "düşük", None
    v = float(np.percentile(drops, 75))
    if v > 25.0:
        return "düşük", v
    if v >= 15.0:
        return "orta", v
    return "yüksek", v


def _yin_fallback(librosa, y: np.ndarray, sr: int, fl: int, hop: int, sp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """yin perdesi + o gecikmedeki normalize otokorelasyonla sesli kare kararı (yalnızca konuşma kareleri)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f = librosa.yin(np.ascontiguousarray(y, dtype=np.float32), fmin=F0_FMIN, fmax=F0_FMAX, sr=sr,
                        frame_length=fl, hop_length=hop)
    m = min(f.size, sp.size)
    f, sp = f[:m], sp[:m]
    yp = np.pad(np.asarray(y, dtype=np.float64), (fl // 2, fl // 2))
    voiced = np.zeros(m, dtype=bool)
    for j in np.flatnonzero(sp):
        if not (math.isfinite(f[j]) and f[j] > 0):
            continue
        lag = int(round(sr / f[j]))
        seg = yp[j * hop: j * hop + fl]
        if lag >= seg.size - 8:
            continue
        a, b = seg[:-lag], seg[lag:]
        den = math.sqrt(float(a @ a) * float(b @ b))
        voiced[j] = den > 0.0 and float(a @ b) / den >= 0.5
    return f, voiced


def _f0_stats(o: _Olcum) -> tuple[dict, int]:
    """pyin ile F0 istatistikleri; ikinci değer ölçülen sesli kare sayısı."""
    empty = {"median_hz": 0.0, "min_hz": 0.0, "max_hz": 0.0, "range_semitones": 0.0, "std_semitones": 0.0,
             "voiced_ratio": 0.0, "label": "belirsiz"}
    if not o.speech.any():
        return empty, 0
    try:
        import librosa
    except Exception:  # pragma: no cover - librosa yoksa F0 ölçülmez
        return empty, 0
    first = int(np.flatnonzero(o.speech)[0])
    t0 = max(0.0, first * o.hop / o.sr - 0.1)
    s0 = int(t0 * o.sr)
    y = o.x[s0: s0 + int(F0_MAX_S * o.sr)]
    sr_p = min(o.sr, F0_SR)
    y = _resample(y, o.sr, sr_p)
    fl = 1 << int(math.ceil(math.log2(sr_p * 2.2 / F0_FMIN)))
    hop_p = max(1, int(round(0.02 * sr_p)))
    if y.size < fl:
        return empty, 0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f0, vflag, _ = librosa.pyin(np.ascontiguousarray(y, dtype=np.float32), fmin=F0_FMIN, fmax=F0_FMAX,
                                        sr=sr_p, frame_length=fl, hop_length=hop_p)
    except Exception:  # pragma: no cover - beklenmeyen librosa hatası analizi düşürmesin
        return empty, 0
    t = t0 + np.arange(f0.size) * hop_p / sr_p
    idx = np.clip(np.round((t * o.sr - o.win / 2) / o.hop).astype(int), 0, o.n - 1)
    sp = o.speech[idx]
    voiced = np.asarray(vflag, dtype=bool) & np.isfinite(f0) & sp
    nv = int(voiced.sum())
    if sp.sum() >= 25 and nv < 0.2 * sp.sum():
        # pyin'in sesli/sessiz kararı nefesli ya da gürültülü seslerde çok temkinli kalabiliyor:
        # yin perdesini, o perdedeki periyodiklikle (normalize otokorelasyon ≥ 0.5) doğrulayarak yedek ölçüm yap
        f0_y, voiced_y = _yin_fallback(librosa, y, sr_p, fl, hop_p, sp)
        if int(voiced_y.sum()) > nv:
            f0, voiced, nv = f0_y, voiced_y, int(voiced_y.sum())
    vr = nv / max(1, int(sp.sum()))
    if nv < 5:
        return dict(empty, voiced_ratio=_num(vr, 2)), nv
    v = f0[voiced]
    med = float(np.median(v))
    p5, p95 = (float(q) for q in np.percentile(v, [5, 95]))
    rng = 12.0 * math.log2(p95 / p5) if p5 > 0 else 0.0
    # Tonlama canlılığı: perdenin medyana göre yarım ton cinsinden standart sapması (aralıktan daha kararlı;
    # birkaç uç kare aralığı şişirir, sapma ise konuşmanın bütününe bakar)
    std_st = float(np.std(12.0 * np.log2(np.maximum(v, 1e-6) / med))) if med > 0 else 0.0
    label = "erkek" if med < 165.0 else ("kadın" if med > 185.0 else "belirsiz")
    return {"median_hz": _num(med, 1), "min_hz": _num(p5, 1), "max_hz": _num(p95, 1),
            "range_semitones": _num(rng, 1), "std_semitones": _num(std_st, 2),
            "voiced_ratio": _num(min(vr, 1.0), 2), "label": label}, nv


def _speaking_rate(o: _Olcum) -> float:
    """Hece/sn: ünlü bandı RMS zarfındaki tepeler (hece çekirdekleri) / konuşma süresi."""
    speech_s = o.speech.sum() * o.hop / o.sr
    if speech_s < 0.3 or o.n < 16:
        return 0.0
    band = (o.freqs >= 300.0) & (o.freqs <= min(2500.0, 0.45 * o.sr))
    env = np.sqrt(o.spec[:, band].sum(axis=1, dtype=np.float64) / o.win)
    fs_env = o.sr / o.hop
    sos = signal.butter(2, min(8.0, 0.45 * fs_env), fs=fs_env, output="sos")
    env = signal.sosfiltfilt(sos, env)
    env_db = 20.0 * np.log10(np.maximum(env, 1e-7))
    # belirginlik ≈ konuşma eşik payının (12 dB) %15'i ≈ 1.8 dB: hece arası (ünsüz) çukurlarını yakalar
    prom = 0.15 * SPEECH_MARGIN_DB
    dist = max(1, int(round(80.0 / o.hop_ms)))
    peaks, _ = signal.find_peaks(env_db, prominence=prom, distance=dist)
    peaks = peaks[o.speech[peaks] & (o.level[peaks] >= o.thr_db)]
    return float(peaks.size / speech_s)


def _pauses(o: _Olcum) -> dict:
    durs = []
    for (_, b0), (a1, _) in zip(o.segments, o.segments[1:]):
        ms = o.frames_to_ms(a1 - b0)
        if PAUSE_MIN_MS <= ms <= PAUSE_MAX_MS:
            durs.append(ms)
    speech_min = o.speech.sum() * o.hop / o.sr / 60.0
    if not durs:
        return {"count": 0, "mean_ms": 0, "median_ms": 0, "per_minute": 0.0, "scale": 1.0}
    med = float(np.median(durs))
    return {"count": len(durs), "mean_ms": int(round(float(np.mean(durs)))), "median_ms": int(round(med)),
            "per_minute": _num(len(durs) / speech_min if speech_min > 0 else 0.0, 1),
            "scale": _num(float(np.clip(med / PAUSE_REF_MS, 0.7, 1.5)), 2)}


def _quiet_region(o: _Olcum, seconds: float) -> tuple[int, int] | None:
    """Konuşma içermeyen ardışık ≥ 0.3 sn bölgelerde en düşük ortalama güçlü pencere ([a, b) kare)."""
    min_frames = max(1, int(math.ceil((NOISE_FLOOR_MIN_S * o.sr - o.win) / o.hop)) + 1)
    target = max(1, int((seconds * o.sr - o.win) // o.hop) + 1)
    best: tuple[float, int, int] | None = None
    for a, b in _runs(o.noise_mask):
        if b - a < min_frames:
            continue
        m = min(b - a, target)
        c = np.concatenate(([0.0], np.cumsum(o.power[a:b])))
        means = (c[m:] - c[:-m]) / m
        i = int(np.argmin(means))
        # kısa pencerelere hafif ceza: aynı sessizlikte uzun bölge (döngüde daha doğal) tercih edilir
        score = float(_db(means[i])) + 6.0 * (1.0 - m / target)
        if best is None or score < best[0]:
            best = (score, a + i, a + i + m)
    return (best[1], best[2]) if best else None


# ---------- puanlama, sorunlar, ipuçları ----------

def _tr(v: float, nd: int = 1) -> str:
    """Türkçe ondalık gösterim (virgüllü): 3.25 → '3,3' (nd=1)."""
    s = f"{v:.{nd}f}"
    return s.replace(".", ",").replace("-", "−")


def _grade(score: int) -> str:
    for thr, name in GRADES:
        if score >= thr:
            return name
    return "zayıf"


_TIPS = {
    "noisy": "Kayıttan önce klima, fan ve buzdolabı gibi sürekli ses kaynaklarını kapatın; telefonu uçak moduna alın.",
    "clipping": "Mikrofonla ağzınız arasında bir karış (20–30 cm) mesafe bırakın; bağırmadan, doğal sesinizle konuşun.",
    "too_loud": "Mikrofonla ağzınız arasında bir karış (20–30 cm) mesafe bırakın; bağırmadan, doğal sesinizle konuşun.",
    "reverb": ("Yankıyı azaltmak için perdeli, halılı, eşyalı bir oda seçin; elbise dolabının önü bile iyi bir kabin "
               "olur."),
    "low_bandwidth": ("WhatsApp sesli mesajı ya da telefon görüşmesi kaydı yerine doğrudan ses kaydedici uygulaması "
                      "kullanın."),
    "too_short": "Soru, ünlem ve düz cümle içeren 10–20 saniyelik bir metni akıcı biçimde okuyun.",
    "too_quiet": "Kayıt seviyesini kontrol edin: konuşurken seviye göstergesi ortanın biraz üstünde olmalı.",
    "low_speech_ratio": ("Kaydın başında ve sonunda en fazla bir saniye sessizlik bırakın; aradaki uzun boşlukları "
                         "kesin."),
    "monotone": "Metni ezbere anlatır gibi okuyun; vurgulu kelimelerde sesiniz doğal olarak yükselip alçalsın.",
    "too_fast": "Cümle sonlarında kısa bir nefes alın; acele etmeden, sohbet temponuzda okuyun.",
    "too_slow": "Kelimeleri tek tek değil, cümle bütünlüğüyle ve sohbet temponuzda okuyun.",
    "dc_offset": "Farklı bir mikrofon girişi ya da kablo deneyin; sorun devam ederse kayıt uygulamasını değiştirin.",
}
_GENERAL_TIPS = (
    "Cümleler arasında doğal nefes ve duraklamalar bırakın; sistem konuşma ritminizi buradan öğrenir.",
    "Aynı mikrofon ve ortamla kaydedilmiş birden fazla örnek eklemek benzerliği artırır.",
    "Kayıt sırasında mikrofona dokunmayın; masaya ya da sabit bir yere koyun.",
)
_NO_SPEECH_TIP = ("Kayıt uygulamasında doğru mikrofonun seçili olduğunu ve konuşurken seviye göstergesinin "
                  "hareket ettiğini kontrol edin.")
_ROOM_TONE_TIP = ("Kaydın başında veya sonunda en az yarım saniye sessiz kalın; doğal oda tonunuz bu bölümden "
                  "alınır ve üretilen seste duraklamaları doldurur.")


def _assess(r: dict, ctx: dict) -> tuple[int, str, list[dict], list[str]]:
    """Ölçümlerden (puan, derece, sorunlar, ipuçları) üretir.

    Cezalar görev tanımındaki puanlama tablosunu izler; SNR 30–40 dB'nin küçük cezası (−4) dışında her ceza bir
    sorun kaydıyla birlikte gelir. Konuşma hiç yoksa puan en fazla 15'tir.
    """
    issues: list[tuple[str, str, str, int]] = []

    def add(code: str, severity: str, message: str, penalty: int) -> None:
        issues.append((code, severity, message, penalty))

    has_speech = ctx["has_speech"]
    d = r["duration"]
    if d < 4.0:
        add("too_short", "error", f"Kayıt çok kısa ({_tr(d)} sn). Klonlama için en az 6–8 saniye, ideal olarak "
            "10–20 saniye akıcı konuşma yükleyin.", 30)
    elif d < 7.0:
        add("too_short", "warn", f"Kayıt biraz kısa ({_tr(d)} sn). 10–20 saniyelik bir kayıt sesinizin rengini ve "
            "ritmini çok daha iyi yakalar.", 12)
    elif d > 25.0:
        add("too_long", "info", f"Kayıt uzun ({_tr(d, 0)} sn). Klonlama için en dolu bölüm otomatik seçilir, fazlası "
            "kırpılır; isterseniz en temiz 10–20 saniyeyi kendiniz kesip yükleyin.", 5)

    if not has_speech:
        if r["noise_floor_dbfs"] > -50.0:
            add("noisy", "warn", f"Arka plan gürültüsü çok yüksek (gürültü tabanı {_tr(r['noise_floor_dbfs'], 0)} "
                "dBFS); konuşma gürültüden ayırt edilemiyor. Sessiz bir odada, mikrofona 20–30 cm mesafeden, klima "
                "ve bilgisayar fanından uzakta yeniden kaydedin.", 30)
            add("low_speech_ratio", "error", "Kayıtta gürültüden ayrışan bir konuşma bulunamadı. Daha sessiz bir "
                "ortamda, normal sesinizle 10–20 saniye konuşarak yeniden kaydedin.", 15)
        else:
            add("low_speech_ratio", "error", "Kayıtta konuşma algılanamadı. Mikrofonun açık ve doğru seçili olduğundan "
                "emin olun, ardından 10–20 saniye normal sesinizle konuşarak yeniden kaydedin.", 15)
    else:
        sr_ = r["speech_ratio"]
        if sr_ < 0.4:
            add("low_speech_ratio", "warn", f"Kaydın büyük bölümü sessizlik (yalnızca %{round(sr_ * 100)} konuşma). "
                "Uzun boşlukları kesin ya da baştan sona akıcı konuşarak yeniden kaydedin.", 15)
        elif sr_ < 0.6:
            add("low_speech_ratio", "info", f"Kayıtta uzun sessizlikler var (%{round(sr_ * 100)} konuşma). Baştaki ve "
                "sondaki boşlukları kısaltmanız önerilir.", 6)

        snr = r["snr_db"]
        if snr < 20.0:
            add("noisy", "warn", f"Arka plan gürültüsü yüksek (sinyal/gürültü {_tr(snr, 0)} dB). Sessiz bir odada, "
                "mikrofona 20–30 cm mesafeden, klima ve bilgisayar fanından uzakta kaydedin.", 30)
        elif snr < 30.0:
            add("noisy", "info", f"Hafif arka plan gürültüsü var (sinyal/gürültü {_tr(snr, 0)} dB). Pencereleri ve "
                "kapıyı kapatıp fan/klima gibi sürekli sesleri susturun, mikrofona biraz yaklaşın.", 12)
        elif snr < 40.0:
            issues.append(("", "", "", 4))  # küçük ceza; ayrı uyarı gerektirmez

        bw = r["bandwidth_hz"]
        if 0 < bw < 6500 and snr < 30.0 and ctx["noise_bw"] >= max(6500.0, 1.5 * bw):
            # kanal geniş bantlı (gürültü bile yüksek frekanslara uzanıyor): konuşmanın tizlerini gürültü örtüyor;
            # sorun bant genişliği değil gürültü — ayrı ceza yerine gürültü uyarısı yeterli
            bw = 0
        if 0 < bw < 4000:
            add("low_bandwidth", "error", f"Ses dar bantlı: yaklaşık {_tr(bw / 1000)} kHz üstünde konuşma enerjisi "
                "yok (telefon hattı, arama kaydı ya da düşük kaliteli sıkıştırma gibi). Telefonun ses kaydedici "
                "uygulamasıyla doğrudan, mümkünse WAV ya da yüksek kalite ayarında kaydedin.", 20)
        elif 0 < bw < 6500:
            add("low_bandwidth", "warn", f"Yüksek frekanslar zayıf (bant genişliği ~{_tr(bw / 1000)} kHz); klon boğuk "
                "çıkabilir. Mikrofonun önünü kapatmayın, kaydı en az 44,1 kHz ve sıkıştırmasız (WAV) alın.", 8)

        if r["reverb"] == "yüksek":
            add("reverb", "warn", "Ortamda belirgin yankı var. Halı, perde ve eşyaların olduğu küçük bir odada "
                "kaydedin; boş odalar, banyo ve mutfaktan kaçının, mikrofona biraz yaklaşın.", 18)
        elif r["reverb"] == "orta":
            add("reverb", "info", "Hafif oda yankısı var. Mikrofona biraz yaklaşın ve yumuşak yüzeyli (perde, halı, "
                "koltuk) bir ortam seçin.", 6)

        if ctx["f0_voiced"] >= 20 and r["f0"]["range_semitones"] < 4.0:
            add("monotone", "info", f"Tonlama oldukça düz (perde aralığı {_tr(r['f0']['range_semitones'])} yarım "
                "ton). Duygu kaydı için daha canlı okuyun; bir arkadaşınıza anlatır gibi doğal inişler ve çıkışlar "
                "yapın.", 8)

        # gürültü, güçlü yankı ve ağır kırpılma hece çukurlarını doldurur/bozar: o durumda hıza dayanarak uyarma
        if ctx["speech_s"] >= 2.0 and snr >= 20.0 and r["reverb"] != "yüksek" and ctx["eff_clip"] <= 0.001:
            rate = r["speaking_rate"]["syllables_per_sec"]
            if r["speaking_rate"]["label"] == "hızlı":
                add("too_fast", "info", f"Konuşma hızlı (saniyede ~{_tr(rate)} hece). Biraz yavaşlayıp cümle "
                    "aralarında kısa duraklamalar bırakın; klon bu ritmi taklit eder.", 3)
            elif r["speaking_rate"]["label"] == "yavaş":
                add("too_slow", "info", f"Konuşma yavaş (saniyede ~{_tr(rate)} hece). Doğal temponuzda, akıcı okuyun; "
                    "aşırı yavaş okuma klonda da yapay bir ağırlık yaratır.", 3)

    eff_clip = ctx["eff_clip"]
    runs = ctx["flat_runs"]
    if eff_clip > 0.001:
        extra = f", {runs} düz tepe" if runs else ""
        add("clipping", "error", f"Kayıtta kırpılma (distorsiyon) var: örneklerin %{_tr(eff_clip * 100, 2)} kadarı "
            f"tavana vurmuş{extra}. Mikrofon kazancını düşürün ya da biraz uzaklaşın; en yüksek yerlerde bile seviye "
            "−6 dBFS civarında kalsın ve kaydı yeniden alın.", 25)
    elif eff_clip > 0.0001 or runs >= 5:
        what = f"{runs} düz tepe" if runs else f"örneklerin %{_tr(eff_clip * 100, 3)} kadarı tavanda"
        add("clipping", "warn", f"Birkaç yerde hafif kırpılma var ({what}). Kazancı biraz düşürüp yeniden kaydetmeniz "
            "önerilir; özellikle vurgulu ve yüksek sesli yerlerde ses tavana vuruyor.", 8)

    if r["peak_dbfs"] > -0.5:
        add("too_loud", "info", f"Tepe seviyesi tavana çok yakın ({_tr(r['peak_dbfs'])} dBFS). Kazancı biraz düşürün; "
            "en yüksek yerler −6 ile −3 dBFS arasında kalsın.", 5)
    if DIGITAL_SILENCE_DB < r["rms_dbfs"] < -32.0:
        add("too_quiet", "warn", f"Kayıt çok kısık (ortalama {_tr(r['rms_dbfs'], 0)} dBFS). Mikrofona biraz yaklaşın "
            "(20–30 cm) ya da kayıt kazancını artırın; ortalama seviye −24 ile −16 dBFS arasında olmalı.", 10)
    if r["dc_offset"] > 0.02:
        oran = _tr(r["dc_offset"] * 100)
        add("dc_offset", "info", f"Kayıtta DC kayması var (sinyal ortalaması tepe seviyesinin %{oran} kadarı). "
            "Mikrofon ya da ses kartı kaynaklı olabilir; başka bir giriş veya mikrofon deneyin.", 5)

    score = int(max(0, min(100, 100 - sum(p for *_, p in issues))))
    if not has_speech:
        score = min(score, 15)
    grade = _grade(score)

    real = [i for i in issues if i[0]]
    real.sort(key=lambda i: (_SEVERITY_ORDER[i[1]], -i[3]))
    out_issues = [{"code": c, "severity": s, "message": m} for c, s, m, _ in real]

    if grade == "mükemmel" and not any(i["severity"] in ("error", "warn") for i in out_issues):
        return score, grade, out_issues, [EXCELLENT_TIP]
    tips: list[str] = []
    for c, *_ in real:
        if c == "low_speech_ratio" and not has_speech:
            # konuşma yok: sessizse mikrofon ayarı, gürültülüyse gürültü ipucu (noisy kaydından) öne çıksın
            t = _NO_SPEECH_TIP if r["noise_floor_dbfs"] <= -50.0 else None
        else:
            t = _TIPS.get(c)
        if t and t not in tips:
            tips.append(t)
    if has_speech and not ctx["room_tone"]:
        tips.insert(min(len(tips), 2), _ROOM_TONE_TIP)
    for t in _GENERAL_TIPS:
        if len(tips) >= 2:
            break
        tips.append(t)
    return score, grade, out_issues, tips[:4]


def _empty_result(duration: float) -> dict:
    """Boş/okunamayan giriş için şemaya uygun sonuç."""
    r = {
        "duration": _num(duration, 2), "speech_ratio": 0.0, "snr_db": 0.0, "noise_floor_dbfs": DB_FLOOR,
        "peak_dbfs": DB_FLOOR, "rms_dbfs": DB_FLOOR, "clipping_ratio": 0.0, "dc_offset": 0.0, "bandwidth_hz": 0,
        "reverb": "düşük",
        "f0": {"median_hz": 0.0, "min_hz": 0.0, "max_hz": 0.0, "range_semitones": 0.0, "std_semitones": 0.0,
               "voiced_ratio": 0.0, "label": "belirsiz"},
        "speaking_rate": {"syllables_per_sec": 0.0, "label": "normal"},
        "pauses": {"count": 0, "mean_ms": 0, "median_ms": 0, "per_minute": 0.0, "scale": 1.0},
        "breaths": {"count": 0, "positions_s": []},
    }
    ctx = {"has_speech": False, "eff_clip": 0.0, "flat_runs": 0, "f0_voiced": 0, "speech_s": 0.0, "room_tone": False,
           "noise_bw": 0}
    score, grade, issues, tips = _assess(r, ctx)
    r.update(quality_score=score, grade=grade, issues=issues, tips=tips)
    return r


# ---------- genel arayüz ----------

def analyze_array(wav: np.ndarray, sr: int) -> dict:
    """Bellekteki kaydı analiz eder; şema için modül belgesine ve docs/SOZLESME.md §4'e bakın."""
    return _analyze(wav, sr)


def _analyze(wav, sr: int, true_duration: float | None = None) -> dict:
    """analyze_array'in gövdesi; ``true_duration``: dosyanın yalnızca bir kısmı okunduysa gerçek süresi."""
    sr = int(sr)
    x = _mono(wav)
    if x.size == 0 or sr <= 0:
        return _empty_result(0.0)
    duration = max(x.size / sr, true_duration or 0.0)
    x = x[: int(MAX_ANALYSIS_S * sr)]  # çok uzun kayıtlarda ölçümler ilk MAX_ANALYSIS_S saniyeden yapılır
    peak = float(max(x.max(), -x.min()))
    rms = math.sqrt(float(x @ x) / x.size)
    clip_ratio, flat_runs, flat_ratio = _clipping(x, peak)
    dc = abs(float(np.mean(x))) / peak if peak > 1e-9 else 0.0

    o = _olc(x, sr)
    speech_s = float(o.speech.sum() * o.hop / o.sr)
    speech_ratio = float(o.speech.mean())
    has_speech = speech_s >= 0.5

    f0, nv = _f0_stats(o)
    rate = _speaking_rate(o) if has_speech else 0.0
    rate_label = "yavaş" if rate < 3.8 else ("hızlı" if rate > 5.8 else "normal")
    if not has_speech:
        rate_label = "normal"
    reverb, _ = _reverb(o) if has_speech else ("düşük", None)
    bw_speech, bw_noise = _bandwidth(o) if has_speech else (0, 0)

    r = {
        "duration": _num(duration, 2),
        "speech_ratio": _num(speech_ratio, 2),
        "snr_db": _num(_snr(o), 1),
        "noise_floor_dbfs": _num(o.floor_db, 1),
        "peak_dbfs": _num(_db(peak * peak), 1),
        "rms_dbfs": _num(_db(rms * rms), 1),
        "clipping_ratio": _num(clip_ratio, 5),
        "dc_offset": _num(dc, 4),
        "bandwidth_hz": int(bw_speech),
        "reverb": reverb,
        "f0": f0,
        "speaking_rate": {"syllables_per_sec": _num(rate, 2), "label": rate_label},
        "pauses": _pauses(o),
        "breaths": {"count": len(o.breaths),
                    "positions_s": [_num(b["start"] * o.hop / o.sr, 2) for b in o.breaths]},
    }
    ctx = {"has_speech": has_speech, "eff_clip": max(clip_ratio, flat_ratio), "flat_runs": int(flat_runs),
           "f0_voiced": nv, "speech_s": speech_s, "room_tone": _quiet_region(o, 0.8) is not None,
           "noise_bw": int(bw_noise)}
    score, grade, issues, tips = _assess(r, ctx)
    r.update(quality_score=score, grade=grade, issues=issues, tips=tips)
    return r


def _read_audio(path: Path) -> tuple[np.ndarray, int, float | None]:
    """(mono sinyal, örnekleme hızı, gerçek süre). soundfile ile okur (en fazla READ_MAX_S); okuyamazsa
    ffmpeg/librosa ile geçici WAV'a çevirip dener."""
    try:
        info = sf.info(str(path))
        frames = int(min(info.frames, READ_MAX_S * info.samplerate)) if info.frames > 0 else -1
        data, sr = sf.read(str(path), frames=frames, dtype="float32", always_2d=True)
        real = info.frames / info.samplerate if info.frames > 0 and info.samplerate > 0 else None
        return data.mean(axis=1), int(sr), real
    except Exception:
        pass
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "analiz.wav"
            to_wav(path, tmp, TARGET_SR, READ_MAX_S)
            data, sr = sf.read(str(tmp), dtype="float32", always_2d=True)
        return data.mean(axis=1), int(sr), None
    except Exception as e:  # noqa: BLE001 - kullanıcıya anlaşılır hata
        raise ValueError(f"Ses dosyası okunamadı: {path.name}") from e


def analyze_reference(path: str | Path) -> dict:
    """Dosyayı okur (mono'ya indirir) ve ``analyze_array`` sonucunu döndürür."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {path}")
    wav, sr, real_duration = _read_audio(path)
    return _analyze(wav, sr, real_duration)


def extract_noise_floor(wav: np.ndarray, sr: int, seconds: float = 0.8) -> np.ndarray | None:
    """Kayıttaki en sessiz, konuşmasız (≥ 0.3 sn) bölgeyi oda tonu olarak döndürür (float32, en fazla ``seconds``).

    Baş/son 100 ms yumuşatılır, DC alınır. Uygun bölge yoksa (ya da yalnızca dijital sessizlik varsa) ``None``.
    """
    sr = int(sr)
    x = _mono(wav)
    if x.size == 0 or sr <= 0 or seconds <= 0:
        return None
    o = _olc(x, sr)
    reg = _quiet_region(o, float(seconds))
    if reg is None:
        return None
    t0, t1 = o.frame_span(*reg)
    s0 = int(round(t0 * sr))
    s1 = min(x.size, int(round(t1 * sr)), s0 + int(round(seconds * sr)))
    seg = x[s0:s1]
    if seg.size < 2:
        return None
    seg = (seg - seg.mean()).astype(np.float32)
    return fade(seg, sr, 100)


def extract_breath(wav: np.ndarray, sr: int) -> np.ndarray | None:
    """Kayıttaki en temiz gerçek nefesi (150–500 ms, en yüksek SNR) keser: 20 ms yumuşatma, RMS = -34 dBFS.

    Uygun nefes yoksa ``None`` (motor sentetik nefese döner).
    """
    sr = int(sr)
    x = _mono(wav)
    if x.size == 0 or sr <= 0:
        return None
    o = _olc(x, sr)
    cands = [b for b in o.breaths if 150.0 <= b["dur_ms"] <= 500.0]
    if not cands:
        return None
    best = max(cands, key=lambda b: b["snr_db"])
    t0, t1 = o.frame_span(best["start"], best["end"])
    s0 = max(0, int(round((t0 - 0.02) * sr)))
    s1 = min(x.size, int(round((t1 + 0.02) * sr)))
    seg = x[s0:s1] - float(np.mean(x[s0:s1]))
    if seg.size > 64:
        sos = signal.butter(2, min(80.0, 0.45 * sr), btype="highpass", fs=sr, output="sos")
        seg = signal.sosfiltfilt(sos, seg)
    seg = fade(seg.astype(np.float32), sr, 20).astype(np.float64)
    rms = float(np.sqrt(np.mean(seg * seg)))
    if rms <= 1e-9:
        return None
    seg *= db_to_amp(BREATH_TARGET_DBFS) / rms
    peak = float(np.max(np.abs(seg)))
    if peak > 0.99:  # pratikte olmaz; yine de taşmayı önle
        seg *= 0.99 / peak
    return seg.astype(np.float32)
