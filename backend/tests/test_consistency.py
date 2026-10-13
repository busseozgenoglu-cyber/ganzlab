"""Parçalar arası tını/seviye/perde tutarlılığı (app.consistency) testleri.

Gerçek TTS çıktısı yerine tohumlu (belirlenimci) sentetik "konuşma" kullanılır: 24 kHz, f0 (varsayılan 150 Hz)
temel + 1/k genlikli harmonikler, süre boyunca tam iki dönemlik hafif tonlama (medyan f0'da kalır), 4.5 Hz hece
zarfı ve -60 dBFS beyaz gürültü. "Boğuk parça" = aynı sinyalin 3 kHz'lik birinci derece alçak geçirenden geçmiş
kopyası (6 dB/oktav eğim — modelin bir parçada tınıyı karartması gibi).
"""
import json
import math
import os
import time

import numpy as np
import pytest
from scipy import signal

from app import consistency as tut
from app.audio import has_ffmpeg

SR = 24000
ffmpeg_gerekli = pytest.mark.skipif(not has_ffmpeg(), reason="ffmpeg kurulu değil")


# ---------- yardımcılar ----------

def konusma(f0=150.0, sure_s=3.0, tonlama_yt=1.5, hece_hz=4.5, gurultu_db=-60.0, tepe=0.5, tohum=0, sr=SR):
    """Konuşma benzeri sinyal: harmonik dizisi (1/k) × hece zarfı (0.25–1), 30 ms giriş/çıkış rampası, düşük gürültü."""
    rng = np.random.default_rng(tohum)
    n = int(sure_s * sr)
    t = np.arange(n) / sr
    f_an = f0 * 2.0 ** (tonlama_yt * np.sin(2 * np.pi * 2.0 * t / sure_s + tohum) / 12.0)  # tam 2 dönem
    faz = 2 * np.pi * np.cumsum(f_an) / sr
    k_max = int(0.45 * sr / (f0 * 2.0 ** (abs(tonlama_yt) / 12.0)))
    x = sum(np.sin(k * faz) / k for k in range(1, k_max + 1))
    zarf = 0.25 + 0.75 * np.sin(np.pi * hece_hz * t) ** 2
    m = int(0.03 * sr)
    rampa = np.linspace(0.0, 1.0, m)
    zarf[:m] *= rampa
    zarf[-m:] *= rampa[::-1]
    y = x * zarf
    y = y / np.max(np.abs(y)) * tepe + 10.0 ** (gurultu_db / 20.0) * rng.standard_normal(n)
    return y.astype(np.float32)


def boguk(x, fc=3000.0, sr=SR):
    """3 kHz birinci derece alçak geçiren (6 dB/oktav): "boğuk" parça."""
    b, a = signal.butter(1, fc, fs=sr)
    return signal.lfilter(b, a, x).astype(np.float32)


def raf(x, fc, kazanc_db, yukari=True, sr=SR):
    """Sıfır fazlı raf EQ: fc üstünü (yukari) ya da altını kazanc_db kadar değiştirir ("tiz"/"gür" parça)."""
    X = np.fft.rfft(np.asarray(x, dtype=np.float64))
    f = np.maximum(np.fft.rfftfreq(len(x), 1.0 / sr), 1.0)
    s = 1.0 / (1.0 + (fc / f) ** 4) if yukari else 1.0 / (1.0 + (f / fc) ** 4)
    return np.fft.irfft(X * 10.0 ** (kazanc_db * s / 20.0), n=len(x)).astype(np.float32)


def rms_db(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    return 10.0 * math.log10(float(np.mean(x * x)) + 1e-30)


def seviyeye(x, hedef_db):
    """Düz RMS'i hedef_db'ye getirir."""
    return (np.asarray(x, dtype=np.float64) * 10.0 ** ((hedef_db - rms_db(x)) / 20.0)).astype(np.float32)


def frekanslar(n_bin, sr=SR):
    return np.arange(n_bin) * sr / (2 * (n_bin - 1))


def sekil_farki(a_db, b_db, sr=SR):
    """İki LTAS arasındaki ortalama mutlak ŞEKİL farkı (dB): 150–8000 Hz, her biri kendi bant ortalamasından
    arındırılmış, log-frekans ağırlıklı (her oktav eşit) — modülün şekil tanımıyla aynı."""
    f = frekanslar(a_db.size, sr)
    bant = (f >= 150) & (f <= 8000)
    w = 1.0 / f[bant]
    w /= w.sum()
    a = a_db[bant] - np.dot(w, a_db[bant])
    b = b_db[bant] - np.dot(w, b_db[bant])
    return float(np.dot(w, np.abs(a - b)))


def ton_db(x, frekans, sr=SR):
    """Uzun Hann pencereli FFT'de frekansın çevresindeki en yüksek genlik (dB)."""
    X = np.abs(np.fft.rfft(np.asarray(x, dtype=np.float64) * np.hanning(len(x))))
    k = int(round(frekans * len(x) / sr))
    return 20.0 * math.log10(float(X[k - 2:k + 3].max()))


@pytest.fixture(scope="module")
def referans():
    return konusma(sure_s=6.0, tohum=1)


@pytest.fixture(scope="module")
def hedef(referans):
    return tut.ltas(referans, SR)


# ---------- ltas ----------

def test_ltas_uzunluk_tip_ve_sonlu(referans):
    l2048 = tut.ltas(referans, SR)
    l1024 = tut.ltas(referans, SR, n_fft=1024)
    assert l2048.shape == (1025,)
    assert l1024.shape == (513,)
    assert np.isfinite(l2048).all() and np.isfinite(l1024).all()
    assert l2048.max() > -60.0  # gerçek içerik ölçülmüş, taban değil


def test_ltas_sessiz_girdi_sifirlar():
    assert np.array_equal(tut.ltas(np.zeros(SR, dtype=np.float32), SR), np.zeros(1025))
    cok_kisik = (1e-5 * np.random.default_rng(0).standard_normal(SR)).astype(np.float32)  # ≈ -100 dBFS
    assert not np.any(tut.ltas(cok_kisik, SR))
    assert tut.ltas(np.zeros(0, dtype=np.float32), SR, n_fft=512).shape == (257,)


def test_ltas_seviyeden_bagimsiz_sekil(referans):
    fark = tut.ltas(0.25 * referans, SR) - tut.ltas(referans, SR)
    assert np.mean(fark) == pytest.approx(20 * math.log10(0.25), abs=0.01)  # her bin -12.04 dB kayar
    assert np.std(fark) < 0.01


def test_ltas_yalnizca_konusma_kareleri(referans):
    """Başa/sona eklenen uzun sessizlik (−30 dB kapısının altında) LTAS'ı değiştirmez."""
    sessiz = np.zeros(2 * SR, dtype=np.float32)
    uzun = np.concatenate([sessiz, referans, sessiz])
    f = frekanslar(1025)
    bant = (f >= 150) & (f <= 8000)
    assert np.max(np.abs(tut.ltas(uzun, SR) - tut.ltas(referans, SR))[bant]) < 0.2


def test_ltas_alcak_geciren_yanitini_izler(referans):
    b, a = signal.butter(1, 3000.0, fs=SR)
    fark = tut.ltas(boguk(referans), SR) - tut.ltas(referans, SR)
    for hz in (500.0, 2000.0, 6000.0):
        k = int(round(hz / (SR / 2048)))
        _, h = signal.freqz(b, a, worN=[hz], fs=SR)
        assert fark[k] == pytest.approx(20 * math.log10(abs(h[0])), abs=0.5)


def test_ltas_ucte_bir_oktav_yumusatma():
    t = np.arange(2 * SR) / SR
    l = tut.ltas((0.3 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32), SR)
    f = frekanslar(l.size)
    assert 1000 * 2 ** (-1 / 6) - 12 <= f[np.argmax(l)] <= 1000 * 2 ** (1 / 6) + 12  # tepe 1 kHz'in 1/3 oktavında
    assert l.max() - l[int(round(2000 / (SR / 2048)))] > 40.0  # bir oktav ötesine yayılmaz


def test_ltas_cok_kanalli_girdi_ortalanir(referans):
    stereo = np.stack([referans, referans], axis=1)  # soundfile biçimi (örnek, kanal)
    assert np.allclose(tut.ltas(stereo, SR), tut.ltas(referans, SR), atol=1e-6)


# ---------- match_timbre ----------

def test_match_timbre_bogukluk_farki_en_az_yuzde_40_azalir(referans, hedef):
    parca = boguk(referans)
    once = sekil_farki(hedef, tut.ltas(parca, SR))
    sonra = sekil_farki(hedef, tut.ltas(tut.match_timbre(parca, SR, hedef), SR))
    assert once > 1.5  # gerçekten boğuk: düzeltilecek bir fark var
    assert sonra <= 0.6 * once


def test_match_timbre_hicbir_bin_3_db_den_fazla_degismez(referans, hedef):
    parca = boguk(referans)
    degisim = tut.ltas(tut.match_timbre(parca, SR, hedef), SR) - tut.ltas(parca, SR)
    assert np.max(np.abs(degisim)) <= 3.0 + 0.05  # pay: STFT yeniden analizinin sayısal hatası
    assert np.max(degisim) > 2.5  # tizler gerçekten yükseltildi (EQ çalışıyor, sınıra dayanıyor)
    sinirli = tut.ltas(tut.match_timbre(parca, SR, hedef, max_db=1.0), SR) - tut.ltas(parca, SR)
    assert np.max(np.abs(sinirli)) <= 1.0 + 0.05


def test_match_timbre_uzunluk_tip_ve_tepe(referans, hedef):
    for parca in (boguk(referans[: SR * 2 + 123]), raf(konusma(tohum=7), 2000.0, 5.0)):
        cikti = tut.match_timbre(parca, SR, hedef)
        assert cikti.shape == parca.shape
        assert cikti.dtype == np.float32
        assert np.isfinite(cikti).all()
        assert np.max(np.abs(cikti)) <= np.max(np.abs(parca)) * (1 + 1e-6)


def test_match_timbre_tiz_parca_da_yaklasir(hedef):
    parca = raf(konusma(tohum=7), 2000.0, 5.0)  # 2 kHz üstü +5 dB: "tiz" parça
    once = sekil_farki(hedef, tut.ltas(parca, SR))
    sonra = sekil_farki(hedef, tut.ltas(tut.match_timbre(parca, SR, hedef), SR))
    assert sonra <= 0.6 * once


def test_match_timbre_sessiz_ve_kisa_parcaya_dokunmaz(hedef):
    sessiz = np.zeros(SR, dtype=np.float32)
    assert np.array_equal(tut.match_timbre(sessiz, SR, hedef), sessiz)
    kisa = boguk(konusma(sure_s=0.15, tohum=3))  # < 0.2 sn
    assert np.array_equal(tut.match_timbre(kisa, SR, hedef), kisa)


def test_match_timbre_gecersiz_hedefte_dokunmaz(referans):
    parca = boguk(referans[:SR])
    assert np.array_equal(tut.match_timbre(parca, SR, np.zeros(1025)), parca)  # sessiz referansın LTAS'ı
    bozuk = np.full(1025, -40.0)
    bozuk[100] = np.nan
    assert np.array_equal(tut.match_timbre(parca, SR, bozuk), parca)


def test_match_timbre_hedefin_kendisine_dokunmaz(referans, hedef):
    cikti = tut.match_timbre(referans, SR, hedef)
    assert np.max(np.abs(cikti - referans)) < 1e-5


def test_match_timbre_seviyeden_bagimsiz(referans, hedef):
    parca = boguk(referans[: 3 * SR])
    tam = tut.match_timbre(parca, SR, hedef)
    kisik = tut.match_timbre(0.25 * parca, SR, hedef)
    assert np.allclose(kisik, 0.25 * tam, atol=1e-5)


def test_match_timbre_bant_disina_dokunmaz(referans, hedef):
    """lo·2^(-1/3) altı (60 Hz uğultu) ve hi·2^(1/3) üstü (11 kHz) değişmez."""
    t = np.arange(referans.size) / SR
    parca = (boguk(referans) + 10 ** (-30 / 20) * np.sin(2 * np.pi * 60 * t)
             + 10 ** (-40 / 20) * np.sin(2 * np.pi * 11000 * t)).astype(np.float32)
    cikti = tut.match_timbre(parca, SR, hedef)
    assert abs(ton_db(cikti, 60) - ton_db(parca, 60)) < 0.1
    assert abs(ton_db(cikti, 11000) - ton_db(parca, 11000)) < 0.1


def test_match_timbre_farkli_n_fft_hedefi(referans):
    hedef_1024 = tut.ltas(referans, SR, n_fft=1024)
    parca = boguk(referans[: 2 * SR])
    cikti = tut.match_timbre(parca, SR, hedef_1024)
    assert cikti.shape == parca.shape
    assert sekil_farki(hedef_1024, tut.ltas(cikti, SR, 1024)) < sekil_farki(hedef_1024, tut.ltas(parca, SR, 1024))


def test_match_timbre_tepe_korumasi(referans, hedef, monkeypatch):
    """EQ tepeyi yükseltirse tüm parça orijinal tepeye ölçeklenir."""
    gercek = tut._filter_stft
    monkeypatch.setattr(tut, "_filter_stft", lambda *a: gercek(*a) * np.float32(2.0))
    parca = boguk(referans[: 2 * SR])
    cikti = tut.match_timbre(parca, SR, hedef)
    assert np.max(np.abs(cikti)) == pytest.approx(float(np.max(np.abs(parca))), rel=1e-5)


def test_kazanc_egrisi_sinirli_ve_bant_disinda_sifir():
    rng = np.random.default_rng(5)
    n_bin = 1025
    f = frekanslar(n_bin)
    hedef_db = -40 + np.cumsum(rng.normal(0, 1.5, n_bin))  # ±onlarca dB'lik rastgele yürüyüş
    parca_db = -40 + np.cumsum(rng.normal(0, 1.5, n_bin))
    g = tut._timbre_gain_db(parca_db, hedef_db, SR, max_db=3.0, strength=0.7, lo_hz=150, hi_hz=8000)
    assert np.max(np.abs(g)) <= 3.0 + 1e-12
    assert not np.any(g[f < 150 * 2 ** (-1 / 3) - 1e-9])  # lo'nun 1/3 oktav altı: 0
    assert not np.any(g[f > 8000 * 2 ** (1 / 3) + 1e-9])  # hi'nin 1/3 oktav üstü: 0
    g1 = tut._timbre_gain_db(parca_db, hedef_db, SR, max_db=1.0, strength=0.7, lo_hz=150, hi_hz=8000)
    assert np.max(np.abs(g1)) <= 1.0 + 1e-12
    assert not np.any(tut._timbre_gain_db(parca_db, hedef_db, SR, max_db=3.0, strength=0.0, lo_hz=150, hi_hz=8000))


def test_kazanc_dar_bantli_referansta_konusma_bandini_itmez():
    """Referansın 4 kHz üstü ölü (telefon kaydı gibi) olsa da konuşma bandı +3 dB'lik rafa itilmez."""
    f = frekanslar(1025)
    parca_db = -40.0 - 6.0 * np.log2(np.maximum(f, 100.0) / 100.0)
    hedef_db = np.where(f > 4000, -150.0, parca_db)
    g = tut._timbre_gain_db(parca_db, hedef_db, SR, max_db=3.0, strength=0.7, lo_hz=150, hi_hz=8000)
    assert np.max(np.abs(g[(f >= 150) & (f <= 3000)])) < 2.0
    assert np.all(g[(f >= 4800) & (f <= 8000)] < -2.9)  # ölü bant yine en çok -3 dB kısılır


def test_kazanc_yalnizca_sekle_bakar():
    """Hedefin tamamı +10 dB kaysa da (yalnızca seviye farkı) kazanç sıfırdır."""
    rng = np.random.default_rng(6)
    parca_db = -50 + np.cumsum(rng.normal(0, 0.5, 1025))
    g = tut._timbre_gain_db(parca_db, parca_db + 10.0, SR, max_db=3.0, strength=0.7, lo_hz=150, hi_hz=8000)
    assert np.max(np.abs(g)) < 1e-9


# ---------- align_loudness ----------

def test_align_loudness_ornek_senaryo():
    parcalar = [seviyeye(konusma(sure_s=2.0, tohum=10 + i), db) for i, db in enumerate((-20.0, -26.0, -18.0))]
    cikti = tut.align_loudness(parcalar)
    assert rms_db(cikti[0]) == pytest.approx(-20.0, abs=0.05)  # ilk parça referans: dokunulmaz
    assert rms_db(cikti[1]) == pytest.approx(-24.0, abs=0.05)  # -26 → 2 dB yaklaştı (tam eşitlenmedi)
    assert rms_db(cikti[2]) == pytest.approx(-20.0, abs=0.05)  # -24'e göre 6 dB sıçrama → -20


def test_align_loudness_yeni_liste_orijinaller_degismez():
    parcalar = [seviyeye(konusma(sure_s=1.0, tohum=20), -20.0), seviyeye(konusma(sure_s=1.0, tohum=21), -30.0)]
    kopyalar = [p.copy() for p in parcalar]
    cikti = tut.align_loudness(parcalar)
    assert cikti is not parcalar and len(cikti) == 2
    assert all(np.array_equal(p, k) for p, k in zip(parcalar, kopyalar))
    assert all(c is not p for c, p in zip(cikti, parcalar))
    assert all(c.dtype == np.float32 for c in cikti)
    assert rms_db(cikti[1]) == pytest.approx(-28.0, abs=0.05)


def test_align_loudness_esik_icinde_dokunmaz():
    parcalar = [seviyeye(konusma(sure_s=1.0, tohum=30 + i), db) for i, db in enumerate((-20.0, -23.0, -19.5, -23.4))]
    cikti = tut.align_loudness(parcalar)
    assert all(np.array_equal(c, p) for c, p in zip(cikti, parcalar))


def test_align_loudness_sessiz_ve_kisa_parca_atlanir():
    taban = konusma(sure_s=1.5, tohum=40)
    sessiz = np.zeros(SR, dtype=np.float32)
    kisa = seviyeye(konusma(sure_s=0.1, tohum=41), -5.0)  # < 0.2 sn, çok gür
    parcalar = [seviyeye(taban, -20.0), sessiz, kisa, seviyeye(taban, -27.0)]
    cikti = tut.align_loudness(parcalar)
    assert np.array_equal(cikti[1], sessiz)
    assert np.array_equal(cikti[2], kisa)
    assert rms_db(cikti[3]) == pytest.approx(-25.0, abs=0.05)  # zincir -20'li parçadan sürer


def test_align_loudness_adim_farki_asmaz():
    taban = konusma(sure_s=1.5, tohum=50)
    cikti = tut.align_loudness([seviyeye(taban, -20.0), seviyeye(taban, -25.0)], max_jump_db=4.0, step_db=6.0)
    assert rms_db(cikti[1]) == pytest.approx(-20.0, abs=0.05)  # 6 dB'lik adım 5 dB'lik farkı aşmaz


def test_align_loudness_kirpilma_korumasi():
    gur = seviyeye(konusma(sure_s=1.0, tohum=60), -12.0)
    sivri = seviyeye(konusma(sure_s=1.0, tohum=61), -18.0)
    sivri[SR // 2] = 0.95  # tek örneklik tepe
    cikti = tut.align_loudness([gur, sivri])
    assert np.max(np.abs(cikti[1])) <= 1.0 + 1e-6
    assert 0.0 < rms_db(cikti[1]) - rms_db(sivri) < 2.0  # yükseltildi ama tepe izin verdiği kadar


def test_align_loudness_bos_liste():
    assert tut.align_loudness([]) == []


# ---------- perde ----------

def test_measure_f0_median_150():
    assert tut.measure_f0_median(konusma(tohum=2), SR) == pytest.approx(150.0, abs=10.0)


def test_measure_f0_median_kadin_sesi():
    assert tut.measure_f0_median(konusma(f0=220.0, tohum=4), SR) == pytest.approx(220.0, abs=10.0)


def test_measure_f0_median_sessiz_none():
    assert tut.measure_f0_median(np.zeros(SR, dtype=np.float32), SR) is None
    assert tut.measure_f0_median(np.zeros(0, dtype=np.float32), SR) is None


@ffmpeg_gerekli
def test_correct_pitch_drift_yukari_ust_sinirla():
    parca = konusma(tonlama_yt=0.0, tohum=2)  # düz 150 Hz
    once = tut.measure_f0_median(parca, SR)
    cikti, uygulanan = tut.correct_pitch_drift(parca, SR, 170.0)  # sapma ≈ +2.17 yt → +2 ile sınırlanır
    sonra = tut.measure_f0_median(cikti, SR)
    assert uygulanan == pytest.approx(2.0)
    assert sonra > once + 10.0  # F0 yükseldi (150 · 2^(2/12) ≈ 168)
    assert abs(sonra - 170.0) < abs(once - 170.0)
    assert abs(cikti.size - parca.size) <= 0.02 * parca.size
    assert cikti.dtype == np.float32


@ffmpeg_gerekli
def test_correct_pitch_drift_asagi():
    parca = konusma(tonlama_yt=0.0, tohum=3)
    cikti, uygulanan = tut.correct_pitch_drift(parca, SR, 130.0)  # sapma ≈ -2.48 yt → -2
    assert uygulanan == pytest.approx(-2.0)
    assert tut.measure_f0_median(cikti, SR) < 140.0


@ffmpeg_gerekli
def test_correct_pitch_drift_sinir_icinde_tam_sapma_kadar():
    parca = konusma(tohum=2)
    f0 = tut.measure_f0_median(parca, SR)
    cikti, uygulanan = tut.correct_pitch_drift(parca, SR, f0 * 2 ** (1.5 / 12))
    assert uygulanan == pytest.approx(1.5, abs=1e-6)
    assert tut.measure_f0_median(cikti, SR) == pytest.approx(f0 * 2 ** (1.5 / 12), rel=0.03)


@ffmpeg_gerekli
def test_correct_pitch_drift_esik_icinde_dokunmaz():
    parca = konusma(tohum=2)
    cikti, uygulanan = tut.correct_pitch_drift(parca, SR, 155.0)  # ≈ 0.5 yt < 1.0
    assert uygulanan == 0.0
    assert np.array_equal(cikti, parca)


@ffmpeg_gerekli
def test_correct_pitch_drift_rubberband_yokken_yedek_yol(monkeypatch):
    monkeypatch.setattr(tut, "_has_rubberband", lambda: False)
    assert tut._pitch_filter(SR, 2.0).startswith("asetrate=")
    parca = konusma(tonlama_yt=0.0, tohum=2)
    cikti, uygulanan = tut.correct_pitch_drift(parca, SR, 170.0)
    assert uygulanan == pytest.approx(2.0)
    assert cikti.size == parca.size
    assert tut.measure_f0_median(cikti, SR) > 160.0


@pytest.mark.skipif(not (has_ffmpeg() and tut._has_rubberband()), reason="ffmpeg rubberband filtresi yok")
def test_rubberband_formant_koruyarak_kullanilir():
    filtre = tut._pitch_filter(SR, 2.0)
    assert filtre.startswith("rubberband=pitch=1.12246")
    assert "formant=preserved" in filtre


def test_correct_pitch_drift_ffmpeg_yokken_dokunmaz(monkeypatch):
    monkeypatch.setattr(tut, "has_ffmpeg", lambda: False)
    parca = konusma(tonlama_yt=0.0, tohum=2)
    cikti, uygulanan = tut.correct_pitch_drift(parca, SR, 170.0)
    assert uygulanan == 0.0
    assert np.array_equal(cikti, parca)


def test_correct_pitch_drift_olculemeyen_ya_da_gecersiz(monkeypatch):
    sessiz = np.zeros(SR, dtype=np.float32)
    assert tut.correct_pitch_drift(sessiz, SR, 170.0)[1] == 0.0
    parca = konusma(sure_s=1.0, tohum=2)
    for gecersiz in (0.0, -5.0, float("nan"), None):
        assert tut.correct_pitch_drift(parca, SR, gecersiz)[1] == 0.0


# ---------- rapor ve önbellek anahtarı ----------

def test_consistency_report_alanlar_ve_json():
    parcalar = [seviyeye(konusma(sure_s=1.5, tohum=70 + i), db) for i, db in enumerate((-20.0, -27.0))]
    rapor = tut.consistency_report(parcalar, tut.align_loudness(parcalar), SR)
    assert set(rapor) == {"timbre_db", "loudness_steps", "max_gain_db"}
    assert type(rapor["timbre_db"]) is float and type(rapor["max_gain_db"]) is float
    assert type(rapor["loudness_steps"]) is int
    assert json.loads(json.dumps(rapor)) == rapor


def test_consistency_report_degisiklik_yoksa_sifir():
    parcalar = [konusma(sure_s=1.0, tohum=80 + i) for i in range(3)]
    assert tut.consistency_report(parcalar, parcalar, SR) == {"timbre_db": 0.0, "loudness_steps": 0,
                                                              "max_gain_db": 0.0}


def test_consistency_report_seviye_adimlari():
    parcalar = [seviyeye(konusma(sure_s=2.0, tohum=10 + i), db) for i, db in enumerate((-20.0, -26.0, -18.0))]
    rapor = tut.consistency_report(parcalar, tut.align_loudness(parcalar), SR)
    assert rapor["loudness_steps"] == 2
    assert rapor["max_gain_db"] == pytest.approx(2.0, abs=0.05)
    assert abs(rapor["timbre_db"]) < 0.02  # düz kazanç tınıyı değiştirmez


def test_consistency_report_tini_farki_azalir(referans, hedef):
    once = [referans[: 2 * SR].copy(), boguk(konusma(sure_s=2.0, tohum=90)),
            raf(konusma(sure_s=2.0, tohum=91), 2000.0, 5.0)]
    sonra = [tut.match_timbre(p, SR, hedef) for p in once]
    rapor = tut.consistency_report(once, sonra, SR)
    assert rapor["timbre_db"] > 0.3
    assert rapor["max_gain_db"] <= 3.05
    assert rapor["loudness_steps"] == 0  # EQ'nun küçük seviye etkisi "seviyeleme" sayılmaz


def test_consistency_report_parca_sayisi_uyusmazligi():
    with pytest.raises(ValueError):
        tut.consistency_report([konusma(sure_s=0.5)], [], SR)


def test_voice_ltas_cache_key(tmp_path):
    yol = tmp_path / "ses.wav"
    yol.write_bytes(b"RIFF....ilk")
    k1 = tut.voice_ltas_cache_key(yol)
    assert k1 == tut.voice_ltas_cache_key(str(yol))  # Path ya da str
    assert isinstance(k1, str) and len(k1) == 40 and all(c in "0123456789abcdef" for c in k1)
    yol.write_bytes(b"RIFF....ikinci kayit")
    st = yol.stat()
    os.utime(yol, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    k2 = tut.voice_ltas_cache_key(yol)
    assert k2 != k1  # dosya değişince anahtar değişir
    diger = tmp_path / "diger.wav"
    diger.write_bytes(b"RIFF....ikinci kayit")
    os.utime(diger, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert tut.voice_ltas_cache_key(diger) != k2  # aynı içerik ve zaman, farklı yol
    yok = tut.voice_ltas_cache_key(tmp_path / "yok.wav")  # hata vermez
    assert isinstance(yok, str) and yok not in (k1, k2)


# ---------- performans ----------

def test_performans_60_sn_ses_bir_bucuk_saniyenin_altinda(hedef):
    tabanlar = [konusma(f0=f0, sure_s=5.0, tohum=100 + i) for i, f0 in enumerate((140.0, 155.0, 170.0))]
    parcalar = []
    for i in range(12):  # 12 × 5 sn = 60 sn; boğuk/tiz/ham, farklı seviyeler
        p = tabanlar[i % 3]
        p = boguk(p) if i % 4 == 0 else raf(p, 2000.0, 4.0) if i % 4 == 1 else p
        parcalar.append(seviyeye(np.roll(p, 977 * i), -18.0 - 3.0 * (i % 4)))
    tut.align_loudness([tut.match_timbre(parcalar[0][:SR], SR, hedef)])  # ısınma (ilk çağrı yükleri ölçülmesin)
    # İşlemci süresi ölçülür: paralel çalışan test süreçleri bu VM'de süreci aç bırakıp duvar saatini 5–7 kat
    # şişirebiliyor (ölçüldü: işlemci 0.3 sn iken duvar 1.5 sn); algoritmanın maliyeti işlemci süresidir.
    c0, t0 = time.process_time(), time.perf_counter()
    sonuc = tut.align_loudness([tut.match_timbre(p, SR, hedef) for p in parcalar])
    islemci, duvar = time.process_time() - c0, time.perf_counter() - t0
    assert len(sonuc) == 12 and all(s.size == p.size for s, p in zip(sonuc, parcalar))
    assert islemci < 1.5, f"match_timbre + align_loudness 60 sn ses için {islemci:.2f} sn (duvar {duvar:.2f} sn)"
