"""Parçalar arası tını/seviye tutarlılığı — cümle cümle üretilen uzun metin "yapışık" duyulsun.

Model uzun metni parça parça üretir ve her parçada tınıyı biraz farklı tutturur: biri daha boğuk, biri daha tiz,
biri daha gür; seviye ve perde de sıçrar. Dinleyici bunu "yapışık değil, yapay" diye duyar. Bu modül parçaları
referans sesin uzun dönem spektrumuna (LTAS) yumuşak bir EQ ile yaklaştırır, ardışık parçalar arasındaki ani seviye
sıçramalarını sınırlar ve isteğe bağlı olarak perde kaymasını düzeltir. Kural: NAZİK ol — EQ ±3 dB'yi aşmaz, duygu
farkları (seviye, perde) silinmez, yalnızca törpülenir. Sözleşme: ``docs/SOZLESME2.md`` bölüm 7.

    ltas(wav, sr, n_fft=2048) -> np.ndarray
    match_timbre(piece, sr, target_ltas, *, max_db=3.0, strength=0.7, lo_hz=150, hi_hz=8000) -> np.ndarray
    align_loudness(pieces, *, max_jump_db=4.0, step_db=2.0) -> list[np.ndarray]
    measure_f0_median(wav, sr) -> float | None
    correct_pitch_drift(piece, sr, target_hz, *, max_semitones=2.0, threshold=1.0) -> tuple[np.ndarray, float]
    consistency_report(before, after, sr) -> dict      # {"timbre_db", "loudness_steps", "max_gain_db"}
    voice_ltas_cache_key(path) -> str

Yöntem (özet):

* LTAS: Hann pencere, hop = n_fft/4; kenarlara n_fft/2 sıfır eklenir (ilk/son örnek de bir pencerenin ortasına
  düşer). Kare RMS'i en gür karenin 30 dB altından büyük olan kareler "konuşma" sayılır, bunların güç spektrumu
  ortalanır. 1/3-oktav yumuşatma: her bin için [f·2^(-1/6), f·2^(+1/6)] penceresinin ortalaması. Ortalama GÜÇ
  alanında alınır (bant enerjisi), sonra dB'ye çevrilir: dB alanında ortalama, harmonik aralarındaki çukurları ve
  gürültü tabanını harmoniklerle eşit sayıyor; denemelerde aynı sesin başka cümlelerinde ve perdesi farklı
  parçalarda sahte EQ'yu 2–3 kat büyüttü. Taban: en yüksek binin 120 dB altı. En gür kare -60 dBFS'nin altındaysa
  girdi sessizdir → sıfırlar.
* Tını eşleme: fark = hedef − parça LTAS'ı, yalnızca ŞEKİL farkı: ikisinden de lo–hi (150–8000 Hz) ortalaması
  çıkarılır. Ortalama log-frekansta alınır (her oktav eşit ağırlık; 1/3-oktav çerçevesiyle tutarlı): doğrusal bin
  ortalaması ağırlığın ~%89'unu 1–8 kHz'e verir ve "boğuk" parçada konuşma enerjisinin bulunduğu alçakları da
  ~3 dB kısıp parçayı ~2.9 dB sessizleştiriyordu (log ağırlıkla ~1.3 dB). Ortalama, medyan çevresinde ±12 dB'ye
  kırpılmış farktan alınır (olağan farklarda etkisiz; dar bantlı referansın ölü tizleri sürüklemez). Fark ayrıca bant
  içinde, en az 400 Hz genişliğinde (ve 1/3 oktavdan dar olmayan) bir pencereyle yumuşatılır: 1.7 kHz'in altında
  1/3 oktav harmonik aralığından dardır; yalnızca perdesi farklı (ör. duygulu) bir parça 150–400 Hz'de ±3 dB'lik
  tarak biçimli sahte EQ alıyordu, yumuşatmayla ≤ ~1 dB'lik geniş bir rafa iner. Kazanç = clip(fark × strength,
  ±max_db); lo altında ve hi üstünde 1/3 oktavlık yükseltilmiş-kosinüs rampayla 0'a iner. Aynı STFT (n_fft =
  2·(len(hedef)−1), hop n_fft/4, Hann) × 10^(kazanç/20) → pencere-karesi ağırlıklı örtüşmeli toplama (ISTFT);
  uzunluk birebir korunur. Çıkışın tepesi orijinali aşarsa tüm parça orijinal tepeye ölçeklenir (seviye değişir,
  tını değil; ±max_db sınırı EQ'nun şekli içindir). Hedef aynı sr ile hesaplanmış olmalıdır.
* Seviye: parça seviyesi = konuşma karelerinin (1024 örneklik kareler, -30 dB göreli kapı) ortalama gücü, dBFS.
  Soldan sağa tek geçiş: bir önceki (düzeltilmiş) parçaya göre |fark| > max_jump_db ise parça farkın tersine
  step_db kadar yaklaştırılır — tam eşitleme yok, duygu farkı kalır; adım farkın kendisini aşmaz, yükseltme tepeyi
  0 dBFS'nin üstüne taşımaz. Sessiz ya da çok kısa (< 0.2 sn; imzada sr olmadığı için 24 kHz varsayılır) parça
  atlanır ve zinciri bozmaz (sonraki parça son geçerli parçayla karşılaştırılır).
* Perde: librosa.pyin (60–450 Hz), 16 kHz'e indirilmiş, ilk konuşmadan itibaren en fazla 30 sn; enerji kapısından
  (en gür karenin 35 dB altı) geçen sesli karelerin medyanı; 3'ten az sesli kare → None. Düzeltme ffmpeg ile:
  rubberband varsa ``rubberband=pitch=…:formant=preserved`` (formantlar korunur → ses kimliği kaymaz), yoksa
  ``asetrate+aresample+atempo``. Uzunluk ±%2 içinde değilse düzeltme reddedilir, içindeyse birebir eşitlenir
  (zaman çizelgesi bozulmasın). Sonuç yeniden ölçülür; F0 hedefe yaklaşmadıysa orijinal döner (pyin oktav hatasına
  karşı güvenlik).

Hiçbir fonksiyon girdisini yerinde değiştirmez; çıktılar float32'dir. Motor nonverbal (gülme vb.) parçaları bu
işlemlerden geçirmemelidir: konuşma LTAS'ına göre EQ'lanmaları anlamsızdır.
"""
from __future__ import annotations

import functools
import hashlib
import logging
import math
import subprocess
import tempfile
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import fft as sfft  # float32'de numpy.fft'ten ~2.4 kat hızlı
from scipy import signal

from .audio import TARGET_SR, db_to_amp, fade, has_ffmpeg

log = logging.getLogger("sesklon.consistency")

# ---------- sabitler ----------

DEFAULT_N_FFT = 2048
SPEECH_GATE_DB = 30.0  # konuşma karesi: en gür karenin en çok bu kadar altı
SILENCE_DBFS = -60.0  # en gür kare bunun altındaysa parça "sessiz"
MIN_PIECE_S = 0.2  # bundan kısa parçalara dokunulmaz
LTAS_FLOOR_DB = 120.0  # LTAS tabanı: en yüksek binin bu kadar altı (log(0) yerine). Gerçek içeriğe değmemeli:
# taban en yüksek bine bağlı olduğundan EQ onu değiştirince tabana oturan binler de "değişmiş" görünür (80 dB'lik
# tabanla aşırı boğuk bir parçada EQ'nun hiç dokunmadığı ölü tizler −2.5 dB değişmiş ölçüldü); 120 dB, float32 FFT
# gürültüsüne yakındır.
MIN_EQ_BW_HZ = 400.0  # EQ farkının en dar yumuşatma penceresi (harmonik yapısını bastırır)
MEAN_CLIP_DB = 12.0  # şekil hizalaması: bant ortalaması, medyan ±bu kadara kırpılmış farktan (ölü bantlar sürüklemesin)
EDGE_RAMP_OCT = 1.0 / 3.0  # lo altında / hi üstünde kazancın 0'a indiği genişlik (oktav)
BAND_LO_HZ, BAND_HI_HZ = 150.0, 8000.0  # rapordaki şekil karşılaştırma bandı
STFT_BLOCK = 512  # bellek sınırı: tek seferde dönüştürülen kare sayısı
LEVEL_FRAME, LEVEL_HOP = 1024, 512  # align_loudness kareleri (örnek; imzada sr yok)
REPORT_STEP_DB = 1.5  # raporda "seviyelendi" sayılan en küçük düzey değişimi (varsayılan adımın ¾'ü)
F0_SR = 16000
F0_FMIN, F0_FMAX = 60.0, 450.0
F0_MAX_S = 30.0
F0_HOP_S = 0.02
F0_GATE_DB = 35.0
F0_MIN_VOICED = 3
LENGTH_TOL = 0.02  # perde düzeltmesinde kabul edilen uzunluk sapması
FFMPEG_TIMEOUT_S = 120
_LTAS_CACHE_VERSION = 1  # LTAS hesabı değişirse artır: eski önbellek anahtarları geçersiz olur


# ---------- ortak yardımcılar ----------

def _as_mono(wav) -> np.ndarray:
    """float32, tek boyutlu görünüm (gerekirse kopya). İki boyutluda kısa eksen kanal sayılıp ortalanır;
    NaN/sonsuz değerler 0 olur. Girdi hiçbir zaman yerinde değiştirilmez."""
    x = np.asarray(wav, dtype=np.float32)
    if x.ndim != 1:
        x = np.squeeze(x)
        if x.ndim == 0:
            x = x.reshape(1)
        elif x.ndim == 2:
            x = x.mean(axis=0 if x.shape[0] <= x.shape[1] else 1, dtype=np.float32)
        elif x.ndim > 2:
            raise ValueError("Ses dizisi tek ya da iki boyutlu olmalı")
    if x.size and not np.isfinite(x).all():
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    return x


@functools.lru_cache(maxsize=8)
def _hann(n: int) -> np.ndarray:
    """Periyodik Hann penceresi (hop = n/4 ile sabit örtüşme toplamı verir); salt okunur."""
    w = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)).astype(np.float32)
    w.setflags(write=False)
    return w


def _layout(n: int, n_fft: int, hop: int) -> tuple[int, int, int]:
    """(kare sayısı, dolgulu uzunluk, ön dolgu): kenarlara n_fft/2 sıfır; her örnek pencerelerle tam örtülür."""
    pad = n_fft // 2
    extra = max(0, n + 2 * pad - n_fft)
    frames = 1 + -(-extra // hop)
    return frames, (frames - 1) * hop + n_fft, pad


def _padded(x: np.ndarray, n_fft: int, hop: int) -> tuple[np.ndarray, int, int]:
    frames, total, pad = _layout(x.size, n_fft, hop)
    xp = np.zeros(total, dtype=np.float32)
    xp[pad:pad + x.size] = x
    return xp, frames, pad


def _frame_ms(xp: np.ndarray, frame: int, hop: int, frames: int) -> np.ndarray:
    """Her karenin ortalama karesi (penceresiz), kümülatif toplamla O(n)."""
    cs = np.concatenate(([0.0], np.cumsum(np.square(xp, dtype=np.float64))))
    starts = np.arange(frames, dtype=np.int64) * hop
    return np.maximum(cs[starts + frame] - cs[starts], 0.0) / frame


def _speech_power(xp: np.ndarray, n_fft: int, hop: int, frames: int) -> np.ndarray | None:
    """Konuşma karelerinin ortalama güç spektrumu (doğrusal ölçek); sessiz girdide None."""
    ms = _frame_ms(xp, n_fft, hop, frames)
    peak = float(ms.max()) if ms.size else 0.0
    if peak <= 0.0 or 10.0 * math.log10(peak) < SILENCE_DBFS:
        return None
    idx = np.flatnonzero(ms > peak * 10.0 ** (-SPEECH_GATE_DB / 10.0))
    view = np.lib.stride_tricks.sliding_window_view(xp, n_fft)[::hop]
    w = _hann(n_fft)
    acc = np.zeros(n_fft // 2 + 1)
    for s in range(0, idx.size, STFT_BLOCK):
        spec = sfft.rfft(view[idx[s:s + STFT_BLOCK]] * w, axis=1)
        acc += np.sum(spec.real ** 2 + spec.imag ** 2, axis=0, dtype=np.float64)
    # 4/(Σw)²: tam ölçekli sinüsün tepe bini ≈ 0 dB (göreli ölçek; anlamlı olan şekil ve farklar)
    return acc * (4.0 / float(np.sum(w, dtype=np.float64)) ** 2) / idx.size


@functools.lru_cache(maxsize=8)
def _third_octave_bounds(n_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Her bin için 1/3-oktav penceresinin (merkez ±1/6 oktav) ilk/son bin indisi; f ∝ k olduğundan sr'den bağımsız."""
    k = np.arange(n_bins, dtype=np.int64)
    lo = np.minimum(np.ceil(k * 2.0 ** (-1.0 / 6.0) - 1e-9).astype(np.int64), k)
    hi = np.clip(np.maximum(np.floor(k * 2.0 ** (1.0 / 6.0) + 1e-9).astype(np.int64), k), 0, n_bins - 1)
    lo.setflags(write=False)
    hi.setflags(write=False)
    return lo, hi


def _smooth_third_octave(power: np.ndarray) -> np.ndarray:
    lo, hi = _third_octave_bounds(power.size)
    cs = np.concatenate(([0.0], np.cumsum(power, dtype=np.float64)))
    return (cs[hi + 1] - cs[lo]) / (hi - lo + 1)


def _to_db(power: np.ndarray) -> np.ndarray:
    floor = max(float(np.max(power)) * 10.0 ** (-LTAS_FLOOR_DB / 10.0), 1e-30)
    return 10.0 * np.log10(np.maximum(power, floor))


def _ltas_of(x: np.ndarray, n_fft: int) -> np.ndarray | None:
    hop = max(1, n_fft // 4)
    xp, frames, _ = _padded(x, n_fft, hop)
    power = _speech_power(xp, n_fft, hop, frames)
    return None if power is None else _to_db(_smooth_third_octave(power))


def _log_weights(f: np.ndarray, band: np.ndarray) -> np.ndarray:
    """Bant içi log-frekans ağırlıkları (her oktav eşit; toplam 1)."""
    w = 1.0 / f[band]
    return w / w.sum()


# ---------- LTAS ----------

def ltas(wav: np.ndarray, sr: int, n_fft: int = DEFAULT_N_FFT) -> np.ndarray:
    """Uzun dönem ortalama spektrum, dB; 1/3-oktav yumuşatılmış; uzunluk n_fft//2+1; sessiz girdi → sıfırlar.

    Konuşma kareleri (RMS > en gür kare − 30 dB) ortalanır; yumuşatma güç alanında yapılır (bkz. modül notu).
    ``sr`` frekans eksenini belirler (bin k = k·sr/n_fft Hz); hesap biçimi sr'den bağımsızdır."""
    n_fft = int(n_fft)
    if n_fft < 16:
        raise ValueError("n_fft en az 16 olmalı")
    if sr <= 0:
        raise ValueError("sr pozitif olmalı")
    x = _as_mono(wav)
    out = _ltas_of(x, n_fft) if x.size else None
    return np.zeros(n_fft // 2 + 1) if out is None else out


# ---------- tını eşleme ----------

def _edge_ramp(f: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """[lo, hi] içinde 1; dışında 1/3 oktavda yükseltilmiş-kosinüsle 0'a iner; DC'de 0."""
    r = np.zeros_like(f)
    r[(f >= lo) & (f <= hi)] = 1.0
    below = (f > 0.0) & (f < lo)
    a = np.clip(1.0 + np.log2(f[below] / lo) / EDGE_RAMP_OCT, 0.0, 1.0)
    r[below] = 0.5 - 0.5 * np.cos(np.pi * a)
    above = f > hi
    b = np.clip(1.0 - np.log2(f[above] / hi) / EDGE_RAMP_OCT, 0.0, 1.0)
    r[above] = 0.5 - 0.5 * np.cos(np.pi * b)
    return r


def _band_smooth(d: np.ndarray, band: np.ndarray, bin_hz: float) -> np.ndarray:
    """Farkı yalnızca bant içi binlerle ortalar; pencere 1/3 oktavdan ve MIN_EQ_BW_HZ'den dar değil.
    Bant dışındaki binler (rampa bölgesi) en yakın bant içi değerleri kullanır."""
    k = np.arange(d.size, dtype=np.float64)
    half = np.maximum(k * (2.0 ** (1.0 / 6.0) - 2.0 ** (-1.0 / 6.0)) / 2.0, 0.5 * MIN_EQ_BW_HZ / bin_hz)
    idx = np.flatnonzero(band)
    b0, b1 = int(idx[0]), int(idx[-1])
    lo = np.clip(np.ceil(k - half - 1e-9), b0, b1).astype(np.int64)
    hi = np.clip(np.floor(k + half + 1e-9), b0, b1).astype(np.int64)
    cs = np.concatenate(([0.0], np.cumsum(np.where(band, d, 0.0))))
    return (cs[hi + 1] - cs[lo]) / (hi - lo + 1)


def _timbre_gain_db(piece_db: np.ndarray, target_db: np.ndarray, sr: int, *, max_db: float, strength: float,
                    lo_hz: float, hi_hz: float) -> np.ndarray:
    """Bin başına EQ kazancı (dB): şekil farkı × strength, ±max_db, bant dışında rampayla 0."""
    n_bins = target_db.size
    n_fft = 2 * (n_bins - 1)
    f = np.arange(n_bins) * (sr / n_fft)
    lo = max(float(lo_hz), float(f[1]))
    hi = min(float(hi_hz), sr / 2.0)
    band = (f >= lo) & (f <= hi)
    if hi <= lo or np.count_nonzero(band) < 2 or max_db <= 0 or strength <= 0:
        return np.zeros(n_bins)
    w = _log_weights(f, band)
    d = target_db - piece_db
    # Yalnızca şekil: iki LTAS'ın bant ortalaması hizalanır (= farkın bant ortalaması çıkarılır). Ortalama, farkın
    # (log-ağırlıklı) medyanı çevresinde ±12 dB'ye kırpılmış değerlerden alınır: olağan farklarda birebir bant
    # ortalamasıdır ve seviyeden bağımsızdır; dar bantlı bir referansın ölü tizleri (−60…−100 dB) ise ortalamayı
    # sürükleyip bütün konuşma bandına +3 dB'lik raf verdirmez.
    db = d[band]
    order = np.argsort(db)
    center = float(db[order][min(int(np.searchsorted(np.cumsum(w[order]), 0.5)), db.size - 1)])
    d = d - (center + float(np.dot(w, np.clip(db - center, -MEAN_CLIP_DB, MEAN_CLIP_DB))))
    d = _band_smooth(d, band, float(f[1]))
    return np.clip(d * strength, -max_db, max_db) * _edge_ramp(f, lo, hi)


def _ola_window_sum(n_fft: int, hop: int, frames: int, chunks: int) -> np.ndarray:
    w2 = np.square(_hann(n_fft), dtype=np.float64)
    if chunks * hop != n_fft:
        w2 = np.pad(w2, (0, chunks * hop - n_fft))
    ws = np.zeros((frames + chunks) * hop)
    for r in range(chunks):
        ws[r * hop:r * hop + frames * hop] += np.tile(w2[r * hop:(r + 1) * hop], frames)
    return ws


def _filter_stft(xp: np.ndarray, n: int, n_fft: int, hop: int, frames: int, pad: int, gain: np.ndarray) -> np.ndarray:
    """STFT × gain → ISTFT (pencere-karesi ağırlıklı örtüşmeli toplama); blok blok, uzunluk n."""
    w = _hann(n_fft)
    view = np.lib.stride_tricks.sliding_window_view(xp, n_fft)[::hop]
    chunks = -(-n_fft // hop)
    out = np.zeros((frames + chunks) * hop)
    for s in range(0, frames, STFT_BLOCK):
        blk = view[s:s + STFT_BLOCK]
        y = sfft.irfft(sfft.rfft(blk * w, axis=1) * gain, n=n_fft, axis=1) * w
        if chunks * hop != n_fft:
            y = np.pad(y, ((0, 0), (0, chunks * hop - n_fft)))
        # kare j'nin r. hop-dilimi (s+j+r)·hop'a düşer: ardışık karelerin aynı dilimleri bitişiktir
        for r in range(chunks):
            a = (s + r) * hop
            out[a:a + blk.shape[0] * hop] += y[:, r * hop:(r + 1) * hop].reshape(-1)
    ws = _ola_window_sum(n_fft, hop, frames, chunks)
    return (out[pad:pad + n] / np.maximum(ws[pad:pad + n], 1e-8)).astype(np.float32)


def match_timbre(piece: np.ndarray, sr: int, target_ltas: np.ndarray, *, max_db: float = 3.0, strength: float = 0.7,
                 lo_hz: int = 150, hi_hz: int = 8000) -> np.ndarray:
    """Parçanın LTAS şeklini hedefe yaklaştıran yumuşak EQ (en çok ±max_db); uzunluk korunur, float32.

    Parça 0.2 sn'den kısa ya da sessizse, hedef geçersizse (sessiz referans → sıfırlar) ya da gereken düzeltme
    ihmal edilebilirse parça olduğu gibi döner. ``target_ltas`` aynı sr ile ``ltas()`` sonucudur; n_fft onun
    uzunluğundan çıkarılır."""
    x = _as_mono(piece)
    target = np.asarray(target_ltas, dtype=np.float64).reshape(-1)
    if sr <= 0 or x.size < MIN_PIECE_S * sr or target.size < 9:
        return x
    if not np.isfinite(target).all() or not np.any(target):
        return x
    n_fft = 2 * (target.size - 1)
    hop = max(1, n_fft // 4)
    xp, frames, pad = _padded(x, n_fft, hop)
    power = _speech_power(xp, n_fft, hop, frames)
    if power is None:
        return x
    g = _timbre_gain_db(_to_db(_smooth_third_octave(power)), target, int(sr), max_db=float(max_db),
                        strength=float(strength), lo_hz=float(lo_hz), hi_hz=float(hi_hz))
    if float(np.max(np.abs(g))) < 1e-3:
        return x
    y = _filter_stft(xp, x.size, n_fft, hop, frames, pad, (10.0 ** (g / 20.0)).astype(np.float32))
    peak_in = float(np.max(np.abs(x)))
    peak_out = float(np.max(np.abs(y)))
    if peak_out > peak_in > 0.0:  # EQ tepeyi yükselttiyse tüm parçayı orijinal tepeye çek
        y *= np.float32(peak_in / peak_out)
    return y


# ---------- seviye ----------

def _level_db(x: np.ndarray) -> float | None:
    """Konuşma karelerinin (göreli -30 dB kapı) ortalama gücü, dBFS; sessiz ya da çok kısa parçada None."""
    if x.size < MIN_PIECE_S * TARGET_SR:
        return None
    frame = min(LEVEL_FRAME, x.size)
    frames = 1 + (x.size - frame) // LEVEL_HOP
    ms = _frame_ms(x, frame, LEVEL_HOP, frames)
    peak = float(ms.max())
    if peak <= 0.0 or 10.0 * math.log10(peak) < SILENCE_DBFS:
        return None
    sel = ms > peak * 10.0 ** (-SPEECH_GATE_DB / 10.0)
    return 10.0 * math.log10(float(ms[sel].mean()))


def align_loudness(pieces: list[np.ndarray], *, max_jump_db: float = 4.0, step_db: float = 2.0) -> list[np.ndarray]:
    """Ardışık parçalar arasındaki > max_jump_db seviye sıçramasını step_db kadar törpüler (tam eşitlemez).

    Soldan sağa tek geçiş; karşılaştırma bir önceki parçanın DÜZELTİLMİŞ seviyesiyle yapılır. Sessiz/çok kısa
    parçalar atlanır. Yeni liste ve yeni diziler döner (float32, mono); orijinaller değişmez."""
    out: list[np.ndarray] = []
    prev: float | None = None
    for p in pieces:
        x = np.array(_as_mono(p), dtype=np.float32, copy=True)
        level = _level_db(x)
        if level is None:
            out.append(x)
            continue
        if prev is not None and step_db > 0:
            diff = level - prev
            if abs(diff) > max_jump_db:
                shift = -math.copysign(min(float(step_db), abs(diff)), diff)
                if shift > 0:  # kırpılma koruması: yükseltme tepeyi 0 dBFS'nin üstüne taşımasın
                    peak = float(np.max(np.abs(x)))
                    shift = max(0.0, min(shift, -20.0 * math.log10(peak))) if peak > 0 else 0.0
                if shift:
                    x *= np.float32(db_to_amp(shift))
                    level += shift
        out.append(x)
        prev = level
    return out


# ---------- perde ----------

def _first_speech_sample(x: np.ndarray, sr: int) -> int:
    frame = max(1, int(0.02 * sr))
    n = x.size // frame
    if n == 0:
        return 0
    ms = _frame_ms(x, frame, frame, n)
    peak = float(ms.max())
    if peak <= 0.0:
        return 0
    loud = np.flatnonzero(ms > peak * 10.0 ** (-SPEECH_GATE_DB / 10.0))
    return max(0, int(loud[0]) * frame - frame) if loud.size else 0


def measure_f0_median(wav: np.ndarray, sr: int) -> float | None:
    """Medyan F0 (Hz): librosa.pyin 60–450 Hz, 16 kHz'e indirilmiş; sesli kare yoksa (ya da < 3) None."""
    x = _as_mono(wav)
    if sr <= 0 or x.size == 0 or not np.any(x):
        return None
    try:
        import librosa
    except Exception:  # pragma: no cover - librosa yoksa F0 ölçülmez
        return None
    sr = int(sr)
    start = _first_speech_sample(x, sr)
    seg = x[start:start + int(F0_MAX_S * sr)].astype(np.float64)
    sr_p = min(sr, F0_SR)
    if sr_p != sr:
        g = math.gcd(sr, sr_p)
        seg = signal.resample_poly(seg, sr_p // g, sr // g)
    fl = 1 << int(math.ceil(math.log2(sr_p * 2.2 / F0_FMIN)))
    hop = max(1, int(round(F0_HOP_S * sr_p)))
    if seg.size < fl:
        seg = np.pad(seg, (0, fl - seg.size))
    y = np.ascontiguousarray(seg, dtype=np.float32)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f0, vflag, _ = librosa.pyin(y, fmin=F0_FMIN, fmax=F0_FMAX, sr=sr_p, frame_length=fl, hop_length=hop)
            rms = librosa.feature.rms(y=y, frame_length=fl, hop_length=hop, center=True)[0]
    except Exception as e:  # noqa: BLE001 — beklenmeyen librosa hatası üretimi düşürmesin
        log.warning("F0 ölçülemedi: %s", e)
        return None
    m = min(f0.size, rms.size)
    f0, vflag = np.asarray(f0[:m], dtype=np.float64), np.asarray(vflag[:m], dtype=bool)
    rdb = 20.0 * np.log10(np.maximum(rms[:m].astype(np.float64), 1e-10))
    gate = rdb > max(float(rdb.max()) - F0_GATE_DB, SILENCE_DBFS)
    voiced = vflag & np.isfinite(f0) & gate
    if int(voiced.sum()) < F0_MIN_VOICED:
        return None
    return float(np.median(f0[voiced]))


_RUBBERBAND: bool | None = None


def _has_rubberband() -> bool:
    """ffmpeg'de rubberband filtresi var mı (bir kez sorulur, önbelleğe alınır)."""
    global _RUBBERBAND
    if _RUBBERBAND is None:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True,
                                 timeout=10).stdout
            _RUBBERBAND = " rubberband " in out
        except Exception:  # noqa: BLE001
            _RUBBERBAND = False
    return _RUBBERBAND


def _pitch_filter(sr: int, semitones: float) -> str:
    ratio = 2.0 ** (semitones / 12.0)
    if _has_rubberband():
        return f"rubberband=pitch={ratio:.6f}:formant=preserved:pitchq=quality"
    new_sr = int(round(sr * ratio))
    return f"asetrate={new_sr},aresample={sr},atempo={sr / new_sr:.6f}"


def _run_ffmpeg(x: np.ndarray, sr: int, afilter: str) -> np.ndarray | None:
    """ffmpeg ses filtresi (float WAV gidiş-dönüş); hata/zaman aşımında uyarı yazar ve None döner."""
    try:
        with tempfile.TemporaryDirectory(prefix="sesklon-tutarlilik-") as td:
            src, dst = Path(td) / "girdi.wav", Path(td) / "cikti.wav"
            sf.write(str(src), x, sr, subtype="FLOAT")
            subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", afilter,
                 "-ac", "1", "-ar", str(sr), "-c:a", "pcm_f32le", str(dst)],
                check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_S,
            )
            y, _ = sf.read(str(dst), dtype="float32", always_2d=False)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()[:300] or f"çıkış kodu {e.returncode}"
        log.warning("Perde düzeltme filtresi başarısız (%s): %s", afilter, detail)
        return None
    except Exception as e:  # noqa: BLE001 — zaman aşımı, dosya/soundfile hataları
        log.warning("Perde düzeltme uygulanamadı (%s): %s", afilter, e)
        return None
    y = np.asarray(y, dtype=np.float32)
    return y.mean(axis=1, dtype=np.float32) if y.ndim > 1 else y


def correct_pitch_drift(piece: np.ndarray, sr: int, target_hz: float, *, max_semitones: float = 2.0,
                        threshold: float = 1.0) -> tuple[np.ndarray, float]:
    """Parçanın medyan F0'ı hedeften threshold yarım tondan fazla saptıysa en çok ±max_semitones düzeltir.

    Dönüş: (ses, uygulanan yarım ton). Dokunulmayan durumlar (hepsi (parça, 0.0)): |sapma| ≤ threshold, ffmpeg
    yok, F0 ölçülemedi, hedef geçersiz, parça < 0.2 sn, ffmpeg hatası, uzunluk ±%2 dışında ya da yeniden ölçülen
    F0 hedefe yaklaşmadı."""
    x = _as_mono(piece)
    try:
        target = float(target_hz)
    except (TypeError, ValueError):
        return x, 0.0
    if not math.isfinite(target) or target <= 0 or sr <= 0 or max_semitones <= 0 or x.size < MIN_PIECE_S * sr:
        return x, 0.0
    if not has_ffmpeg():
        return x, 0.0
    sr = int(sr)
    f0 = measure_f0_median(x, sr)
    if f0 is None:
        return x, 0.0
    deviation = 12.0 * math.log2(target / f0)
    if abs(deviation) <= threshold:
        return x, 0.0
    semitones = float(np.clip(deviation, -max_semitones, max_semitones))
    y = _run_ffmpeg(x, sr, _pitch_filter(sr, semitones))
    if y is None:
        return x, 0.0
    if abs(y.size - x.size) > LENGTH_TOL * x.size:
        log.warning("Perde düzeltmesi uzunluğu bozdu (%d → %d örnek); parça olduğu gibi bırakıldı", x.size, y.size)
        return x, 0.0
    y = y[:x.size] if y.size >= x.size else np.pad(y, (0, x.size - y.size))
    y = fade(y, sr, 5)  # uzunluk eşitleme ya da filtre kenarı tık bırakmasın
    f1 = measure_f0_median(y, sr)
    if f1 is None or abs(12.0 * math.log2(target / f1)) >= abs(deviation):
        log.warning("Perde düzeltmesi F0'ı hedefe yaklaştırmadı (%.1f → %s Hz, hedef %.1f); geri alındı",
                    f0, f"{f1:.1f}" if f1 else "?", target)
        return x, 0.0
    return y.astype(np.float32, copy=False), semitones


# ---------- rapor ve önbellek ----------

def consistency_report(before: list[np.ndarray], after: list[np.ndarray], sr: int) -> dict:
    """İşlem öncesi/sonrası parçalardan özet: {"timbre_db", "loudness_steps", "max_gain_db"}.

    * timbre_db: ardışık (geçerli) parçalar arasındaki ortalama mutlak LTAS şekil farkının azalması (dB; 150–8000
      Hz, log-frekans ağırlıklı ortalama; pozitif = parçalar birbirine yaklaştı).
    * loudness_steps: genel düzeyi ≥ 1.5 dB değişen parça sayısı (seviyelenen parçalar; EQ'nun ve tepe korumasının
      küçük seviye etkisi sayılmaz).
    * max_gain_db: herhangi bir parçada 150–8000 Hz içinde herhangi bir frekansta ölçülen en büyük değişim (dB;
      EQ + seviye adımı birlikte).
    Sessiz ya da 0.2 sn'den kısa parçalar hesaba katılmaz."""
    if len(before) != len(after):
        raise ValueError("before ve after aynı sayıda parça içermeli")
    sr = int(sr)
    if sr <= 0:
        raise ValueError("sr pozitif olmalı")
    n_bins = DEFAULT_N_FFT // 2 + 1
    f = np.arange(n_bins) * (sr / DEFAULT_N_FFT)
    band = (f >= BAND_LO_HZ) & (f <= min(BAND_HI_HZ, sr / 2.0))
    w = _log_weights(f, band)

    def profile(wav) -> np.ndarray | None:
        x = _as_mono(wav)
        return _ltas_of(x, DEFAULT_N_FFT) if x.size >= MIN_PIECE_S * sr else None

    shapes_before: list[np.ndarray] = []
    shapes_after: list[np.ndarray] = []
    steps = 0
    max_gain = 0.0
    for b, a in zip(before, after):
        lb, la = profile(b), profile(a)
        if lb is None or la is None:
            continue
        delta = (la - lb)[band]
        if abs(float(np.dot(w, delta))) >= REPORT_STEP_DB:
            steps += 1
        max_gain = max(max_gain, float(np.max(np.abs(delta))))
        shapes_before.append(lb[band] - float(np.dot(w, lb[band])))
        shapes_after.append(la[band] - float(np.dot(w, la[band])))

    def spread(shapes: list[np.ndarray]) -> float:
        if len(shapes) < 2:
            return 0.0
        return float(np.mean([np.dot(w, np.abs(s1 - s0)) for s0, s1 in zip(shapes, shapes[1:])]))

    timbre = round(spread(shapes_before) - spread(shapes_after), 2) + 0.0  # + 0.0: JSON'da "-0.0" görünmesin
    return {"timbre_db": float(timbre), "loudness_steps": int(steps), "max_gain_db": round(max_gain, 2)}


def voice_ltas_cache_key(path) -> str:
    """Referans dosyası için LTAS önbellek anahtarı: mutlak yol + mtime (ns) + boyut + algoritma sürümü (sha1).

    Dosya değişince (yeniden kayıt, iyileştirme, geri alma) anahtar değişir. Dosya yoksa da hata vermez; o yol için
    var olan her dosyadan farklı bir anahtar döner. Hedef LTAS'ı farklı sr/n_fft ile tutan çağıran anahtara bunları
    ekler."""
    p = Path(path).expanduser()
    try:
        p = p.resolve(strict=False)
    except (OSError, RuntimeError):  # sembolik bağ döngüsü vb.
        p = p.absolute()
    try:
        st = p.stat()
        stamp = f"{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        stamp = "yok"
    raw = f"ltas-v{_LTAS_CACHE_VERSION}|n_fft={DEFAULT_N_FFT}|{p}|{stamp}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
