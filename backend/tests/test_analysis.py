"""Referans kaydı analizi (app.analysis) testleri.

Gerçek kayıt yerine tohumlu (deterministik) sentetik "konuşma" kullanılır: 24 kHz, 150 Hz temel + harmonikler
(hafif tonlamalı), 5 Hz hece zarfı, cümleler arasında 400 ms sessizlik ve -55 dBFS beyaz gürültü.
"""
import json
import math
import time

import numpy as np
import pytest
import soundfile as sf
from scipy import signal

from app.analysis import EXCELLENT_TIP, analyze_array, analyze_reference, extract_breath, extract_noise_floor

SR = 24000
GECERLI_KODLAR = {"too_short", "too_long", "noisy", "clipping", "too_quiet", "too_loud", "low_bandwidth", "reverb",
                  "dc_offset", "low_speech_ratio", "monotone", "too_fast", "too_slow", "music_or_multi"}
SEMA_ANAHTARLARI = {"duration", "speech_ratio", "snr_db", "noise_floor_dbfs", "peak_dbfs", "rms_dbfs", "clipping_ratio",
                    "dc_offset", "bandwidth_hz", "reverb", "f0", "speaking_rate", "pauses", "breaths", "quality_score",
                    "grade", "issues", "tips"}


def konusma(f0=150.0, n_cumle=4, cumle_s=2.2, duraklama_s=0.4, bas_son_s=1.0, gurultu_db=-55.0, tepe=0.5,
            hece_hz=5.0, tonlama_yt=3.0, duraklamalar=None, sr=SR, tohum=0):
    """Konuşma benzeri sinyal: harmonik dizisi (1/k) × hece zarfı, cümle aralarında sessizlik, düşük beyaz gürültü."""
    rng = np.random.default_rng(tohum)
    parcalar = [np.zeros(int(bas_son_s * sr))]
    for i in range(n_cumle):
        t = np.arange(int(cumle_s * sr)) / sr
        f_an = f0 * 2 ** (tonlama_yt * np.sin(2 * np.pi * 0.35 * t + i) / 12)  # hafif tonlama
        faz = 2 * np.pi * np.cumsum(f_an) / sr
        k_max = int(0.45 * sr / (f0 * 2 ** (abs(tonlama_yt) / 12)))
        x = sum(np.sin(k * faz) / k for k in range(1, k_max + 1))
        zarf = 0.25 + 0.75 * np.sin(np.pi * hece_hz * t) ** 2  # hece_hz tepe/sn
        n_y = int(0.02 * sr)
        rampa = np.linspace(0.0, 1.0, n_y)
        zarf[:n_y] *= rampa
        zarf[-n_y:] *= rampa[::-1]
        parcalar.append(x * zarf)
        if i < n_cumle - 1:
            parcalar.append(np.zeros(int((duraklamalar[i] if duraklamalar else duraklama_s) * sr)))
    parcalar.append(np.zeros(int(bas_son_s * sr)))
    y = np.concatenate(parcalar)
    y = y / np.max(np.abs(y)) * tepe
    y = y + 10 ** (gurultu_db / 20) * rng.standard_normal(y.size)
    return y.astype(np.float32)


def rms_db(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    return 20 * math.log10(math.sqrt(float(np.mean(x * x))) + 1e-12)


def kodlar(r) -> dict:
    return {i["code"]: i["severity"] for i in r["issues"]}


def sentetik_nefes(sure_s=0.3, seviye_db=-30.0, tohum=11):
    """Bant geçiren (500–3000 Hz) gürültü, yumuşak zarflı, RMS = seviye_db."""
    rng = np.random.default_rng(tohum)
    n = int(sure_s * SR)
    sos = signal.butter(4, [500, 3000], btype="band", fs=SR, output="sos")
    b = signal.sosfilt(sos, rng.standard_normal(n)) * signal.windows.tukey(n, 0.4)
    return b / np.sqrt(np.mean(b ** 2)) * 10 ** (seviye_db / 20)


def numpy_tipi_yok(o) -> bool:
    if isinstance(o, dict):
        return all(isinstance(k, str) and numpy_tipi_yok(v) for k, v in o.items())
    if isinstance(o, list):
        return all(numpy_tipi_yok(v) for v in o)
    return type(o) in (int, float, str, bool)


# ---------- ortak (pahalı) analizler ----------

@pytest.fixture(scope="module")
def temel():
    y = konusma()
    return y, analyze_array(y, SR)


@pytest.fixture(scope="module")
def nefesli():
    # ikinci duraklama 900 ms; ortasına 300 ms, -30 dBFS sentetik nefes
    y = konusma(duraklamalar=[0.4, 0.9, 0.4]).astype(np.float64)
    bas = 1.0 + 2.2 + 0.4 + 2.2 + 0.45 - 0.15  # = 6.10 sn
    nefes = sentetik_nefes()
    i = int(bas * SR)
    y[i: i + nefes.size] += nefes
    return y.astype(np.float32), bas


# ---------- temel sentetik konuşma ----------

def test_temel_seviye_olcumleri(temel):
    _, r = temel
    assert r["duration"] == pytest.approx(12.0, abs=0.01)
    assert 0.6 <= r["speech_ratio"] <= 0.9
    assert r["snr_db"] > 25
    assert r["noise_floor_dbfs"] == pytest.approx(-55.0, abs=3.0)
    assert r["peak_dbfs"] == pytest.approx(20 * math.log10(0.5), abs=0.5)
    assert -25.0 < r["rms_dbfs"] < -10.0
    assert r["clipping_ratio"] == 0.0
    assert r["dc_offset"] < 0.01


def test_temel_perde(temel):
    f0 = temel[1]["f0"]
    assert f0["median_hz"] == pytest.approx(150.0, abs=15.0)
    assert f0["label"] == "erkek"
    assert f0["min_hz"] < f0["median_hz"] < f0["max_hz"]
    assert 3.0 <= f0["range_semitones"] <= 10.0  # ±3 yarım ton tonlama
    assert f0["voiced_ratio"] > 0.8


def test_temel_duraklamalar(temel):
    p = temel[1]["pauses"]
    assert p["count"] == 3  # 4 cümle → 3 boşluk
    assert p["median_ms"] == pytest.approx(400, abs=80)
    assert p["mean_ms"] == pytest.approx(400, abs=80)
    assert p["scale"] == pytest.approx(1.0, abs=0.15)
    assert p["per_minute"] > 0


def test_temel_hiz_yanki_bant_ve_puan(temel):
    r = temel[1]
    assert r["speaking_rate"]["syllables_per_sec"] == pytest.approx(5.0, abs=0.8)
    assert r["speaking_rate"]["label"] == "normal"
    assert r["reverb"] == "düşük"
    assert r["bandwidth_hz"] >= 6500
    assert r["breaths"] == {"count": 0, "positions_s": []}
    assert r["grade"] in ("iyi", "mükemmel")
    assert r["quality_score"] >= 70
    assert "error" not in {i["severity"] for i in r["issues"]}
    assert r["tips"] == [EXCELLENT_TIP]


def test_sema_ve_json(temel):
    r = temel[1]
    assert set(r) == SEMA_ANAHTARLARI
    assert set(r["f0"]) == {"median_hz", "min_hz", "max_hz", "range_semitones", "voiced_ratio", "label"}
    assert set(r["speaking_rate"]) == {"syllables_per_sec", "label"}
    assert set(r["pauses"]) == {"count", "mean_ms", "median_ms", "per_minute", "scale"}
    assert set(r["breaths"]) == {"count", "positions_s"}
    assert isinstance(r["quality_score"], int) and 0 <= r["quality_score"] <= 100
    assert isinstance(r["bandwidth_hz"], int)
    assert isinstance(r["pauses"]["count"], int) and isinstance(r["pauses"]["median_ms"], int)
    assert numpy_tipi_yok(r)  # numpy tipleri sızmamalı
    geri = json.loads(json.dumps(r, ensure_ascii=False))
    assert geri == r


# ---------- kusurlu kayıtlar ----------

def test_kirpilma_hata(temel):
    y, r0 = temel
    r = analyze_array(np.clip(y * 4, -1.0, 1.0), SR)
    assert r["clipping_ratio"] > 0.001
    assert kodlar(r).get("clipping") == "error"
    assert r["quality_score"] < r0["quality_score"]
    assert r["issues"][0]["severity"] == "error"  # en ciddi sorun başta


def test_dusuk_seviyede_duz_tepe_kirpilma(temel):
    # tavana (0.985) hiç değmeyen ama 0.6'da kesilmiş (sonra kısılmış kayıt gibi) sinyal: düz tepeler yakalanmalı
    y, _ = temel
    r = analyze_array(np.clip(y * 4, -0.6, 0.6), SR)
    assert r["clipping_ratio"] == 0.0
    assert "clipping" in kodlar(r)


def test_cok_gurultulu(temel):
    y, r0 = temel
    rng = np.random.default_rng(7)
    r = analyze_array(y + (10 ** (-20 / 20) * rng.standard_normal(y.size)).astype(np.float32), SR)
    assert "noisy" in kodlar(r)
    assert r["snr_db"] < 20
    assert r["quality_score"] < 50
    assert r["grade"] in ("orta", "zayıf")


def test_kisa_kayit():
    r = analyze_array(konusma(n_cumle=1, cumle_s=1.6, bas_son_s=0.2), SR)
    assert r["duration"] == pytest.approx(2.0, abs=0.01)
    assert kodlar(r).get("too_short") == "error"


def test_dar_bant_telefon_gibi(temel):
    y, _ = temel
    sos = signal.butter(10, 3000, fs=SR, output="sos")
    r = analyze_array(signal.sosfiltfilt(sos, y).astype(np.float32), SR)
    assert 0 < r["bandwidth_hz"] < 4000
    assert kodlar(r).get("low_bandwidth") == "error"


def test_sessiz_dosya_cokmez():
    r = analyze_array(np.zeros(5 * SR, dtype=np.float32), SR)
    assert r["speech_ratio"] == 0.0
    assert kodlar(r).get("low_speech_ratio") == "error"
    assert r["quality_score"] <= 15 and r["grade"] == "zayıf"
    assert r["f0"]["label"] == "belirsiz"
    assert "noisy" not in kodlar(r)  # sessizlik gürültü değildir
    json.dumps(r, ensure_ascii=False)
    assert extract_noise_floor(np.zeros(5 * SR), SR) is None  # dijital sessizlik oda tonu sayılmaz
    assert extract_breath(np.zeros(5 * SR), SR) is None


def test_bos_girdi_cokmez():
    r = analyze_array(np.zeros(0, dtype=np.float32), SR)
    assert r["duration"] == 0.0
    assert "too_short" in kodlar(r)
    assert r["grade"] == "zayıf"
    assert set(r) == SEMA_ANAHTARLARI


def test_kadin_sesi():
    f0 = analyze_array(konusma(f0=300.0), SR)["f0"]
    assert f0["label"] == "kadın"
    assert f0["median_hz"] == pytest.approx(300.0, abs=30.0)


def test_monoton_okuma():
    r = analyze_array(konusma(tonlama_yt=0.0), SR)
    assert r["f0"]["range_semitones"] < 1.0
    assert kodlar(r).get("monotone") == "info"


def test_hizli_ve_yavas_konusma():
    hizli = analyze_array(konusma(hece_hz=7.0), SR)
    yavas = analyze_array(konusma(hece_hz=3.0), SR)
    assert hizli["speaking_rate"]["label"] == "hızlı" and "too_fast" in kodlar(hizli)
    assert yavas["speaking_rate"]["label"] == "yavaş" and "too_slow" in kodlar(yavas)
    assert hizli["speaking_rate"]["syllables_per_sec"] > 5.8 > 3.8 > yavas["speaking_rate"]["syllables_per_sec"]


def test_duraklama_olcegi_sinirlari():
    uzun = analyze_array(konusma(duraklama_s=0.7), SR)["pauses"]
    kisa = analyze_array(konusma(duraklama_s=0.25), SR)["pauses"]
    assert uzun["median_ms"] == pytest.approx(700, abs=80) and uzun["scale"] == 1.5  # 700/400 → 1.5'e kırpılır
    assert kisa["median_ms"] == pytest.approx(250, abs=80) and kisa["scale"] == 0.7  # 250/400 → 0.7'ye kırpılır


def test_yankili_oda(temel):
    y, _ = temel
    rt60 = 1.0
    rng = np.random.default_rng(1)
    t = np.arange(int(rt60 * 1.2 * SR)) / SR
    h = rng.standard_normal(t.size) * np.exp(-6.91 * t / rt60)
    h[:48] = 0.0
    h /= np.sqrt(np.sum(h ** 2))
    h[0] += 1.0  # doğrudan ses ≈ yankı enerjisi
    yr = signal.fftconvolve(y.astype(np.float64), h)[: y.size]
    r = analyze_array((yr / np.max(np.abs(yr)) * 0.5).astype(np.float32), SR)
    assert r["reverb"] == "yüksek"
    assert kodlar(r).get("reverb") == "warn"


def test_dc_kaymasi(temel):
    y, _ = temel
    r = analyze_array(y + 0.05, SR)
    assert r["dc_offset"] > 0.02
    assert "dc_offset" in kodlar(r)


def test_kisik_kayit(temel):
    y, _ = temel
    r = analyze_array(y * 0.03, SR)
    assert r["rms_dbfs"] < -32
    assert kodlar(r).get("too_quiet") == "warn"
    assert r["f0"]["median_hz"] == pytest.approx(150.0, abs=15.0)  # kısık olsa da ölçümler çalışır
    assert r["pauses"]["count"] == 3


def test_uzun_kayit_bilgi():
    r = analyze_array(konusma(n_cumle=10, cumle_s=2.6), SR)
    assert r["duration"] > 25
    assert kodlar(r).get("too_long") == "info"


# ---------- oda tonu ve nefes ----------

def test_oda_tonu_cikarma(temel):
    y, _ = temel
    oda = extract_noise_floor(y, SR)
    assert oda is not None and oda.dtype == np.float32 and oda.ndim == 1
    assert 0.3 * SR <= oda.size <= 0.8 * SR
    orta = oda[int(0.1 * SR): -int(0.1 * SR)]  # 100 ms yumuşatmalar hariç
    assert rms_db(orta) == pytest.approx(-55.0, abs=3.0)
    assert abs(float(oda[0])) < 1e-4 and abs(float(oda[-1])) < 1e-4  # baş/son fade


def test_oda_tonu_sure_siniri_ve_yoklugu(temel):
    y, _ = temel
    kisa = extract_noise_floor(y, SR, seconds=0.5)
    assert kisa is not None and kisa.size <= int(0.5 * SR)
    # hiç ≥ 0.3 sn sessizlik içermeyen kayıt: oda tonu yok
    assert extract_noise_floor(konusma(n_cumle=1, cumle_s=4.0, bas_son_s=0.05), SR) is None


def test_nefes_tespiti(nefesli):
    y, bas = nefesli
    r = analyze_array(y, SR)
    assert r["breaths"]["count"] == 1
    assert r["breaths"]["positions_s"][0] == pytest.approx(bas, abs=0.1)
    assert r["pauses"]["count"] == 3  # nefes duraklamayı bölmez (konuşma sayılmaz)


def test_nefes_kesme(nefesli):
    y, _ = nefesli
    nefes = extract_breath(y, SR)
    assert nefes is not None and nefes.dtype == np.float32
    assert 0.15 * SR <= nefes.size <= 0.6 * SR
    assert rms_db(nefes) == pytest.approx(-34.0, abs=0.5)
    assert float(np.max(np.abs(nefes))) < 1.0


def test_nefes_yoksa_none(temel):
    y, _ = temel
    assert extract_breath(y, SR) is None


# ---------- girdi biçimleri ve dosyadan analiz ----------

def test_ornekleme_hizlari(temel):
    y, _ = temel
    r16 = analyze_array(signal.resample_poly(y, 2, 3).astype(np.float32), 16000)
    r8 = analyze_array(signal.resample_poly(y, 1, 3).astype(np.float32), 8000)
    r48 = analyze_array(signal.resample_poly(y, 2, 1).astype(np.float32), 48000)
    assert 6500 <= r16["bandwidth_hz"] <= 8000 and "low_bandwidth" not in kodlar(r16)
    assert kodlar(r8).get("low_bandwidth") == "error"  # 8 kHz örnekleme = telefon bandı
    assert r48["f0"]["median_hz"] == pytest.approx(150.0, abs=15.0)
    assert r48["duration"] == pytest.approx(12.0, abs=0.01)


def test_int16_ve_stereo_girdi(temel):
    y, r0 = temel
    r_int = analyze_array((y * 32767).astype(np.int16), SR)
    r_st = analyze_array(np.stack([y, y * 0.5], axis=1), SR)
    assert r_int["pauses"]["count"] == r0["pauses"]["count"]
    assert r_int["f0"]["median_hz"] == pytest.approx(r0["f0"]["median_hz"], abs=3.0)
    assert r_st["duration"] == pytest.approx(r0["duration"], abs=0.01)
    assert r_st["peak_dbfs"] == pytest.approx(20 * math.log10(0.75 * 0.5), abs=0.5)  # (1 + 0.5) / 2 karışım


def test_analyze_reference_dosyadan(temel, tmp_path):
    y, r0 = temel
    yol = tmp_path / "referans.wav"
    sf.write(str(yol), np.stack([y, y], axis=1), SR, subtype="PCM_16")
    r = analyze_reference(yol)
    assert r["duration"] == pytest.approx(r0["duration"], abs=0.01)
    assert r["f0"]["label"] == "erkek"
    assert r["pauses"]["count"] == 3
    with pytest.raises(FileNotFoundError):
        analyze_reference(tmp_path / "yok.wav")


# ---------- sorun/ipucu yapısı ----------

def test_sorun_ve_ipucu_yapisi(temel):
    y, _ = temel
    rng = np.random.default_rng(3)
    kotu = np.clip(y * 4, -1, 1)[: int(3.5 * SR)] + (0.01 * rng.standard_normal(int(3.5 * SR))).astype(np.float32)
    r = analyze_array(kotu, SR)
    sira = {"error": 0, "warn": 1, "info": 2}
    assert len(r["issues"]) >= 2
    for i in r["issues"]:
        assert set(i) == {"code", "severity", "message"}
        assert i["code"] in GECERLI_KODLAR and i["severity"] in sira
        assert isinstance(i["message"], str) and len(i["message"]) > 30
    agirlik = [sira[i["severity"]] for i in r["issues"]]
    assert agirlik == sorted(agirlik)  # en ciddi sorunlar önce
    assert 2 <= len(r["tips"]) <= 4 and all(isinstance(t, str) and t for t in r["tips"])
    assert EXCELLENT_TIP not in r["tips"]
    gurultu = next(i for i in analyze_array(y + (0.1 * rng.standard_normal(y.size)).astype(np.float32), SR)["issues"]
                   if i["code"] == "noisy")
    assert "gürültü" in gurultu["message"] and "dB" in gurultu["message"]  # somut ve Türkçe


# ---------- performans ----------

def test_performans():
    analyze_array(konusma(n_cumle=1, cumle_s=1.0, bas_son_s=0.2), SR)  # ısınma (librosa/numba önbelleği)
    y15 = konusma(n_cumle=5)  # ~14.6 sn
    t0 = time.perf_counter()
    analyze_array(y15, SR)
    assert time.perf_counter() - t0 < 2.0
    y60 = np.concatenate([konusma(n_cumle=5, tohum=s) for s in range(4)])  # ~58 sn
    t0 = time.perf_counter()
    analyze_array(y60, SR)
    assert time.perf_counter() - t0 < 6.0
