"""Referans kaydı iyileştirme (app.enhance) testleri.

Gerçek kayıt yerine tohumlu (deterministik) sentetik "konuşma" kullanılır: 24 kHz, 150 Hz temel + harmonikler
(1/k genlik), 5 Hz hece zarfı, cümleler arasında 400 ms, baş/sonda 1 sn sessizlik ve -35 dBFS beyaz gürültü
(SNR ≈ 18 dB: tipik "gürültülü odada telefonla" kaydı). Harmonik fazları sabit ama rastgeledir: gerçek seste ses yolu
fazları dağıtır; sıfır fazlı testere dişinin her periyottaki keskin sıçraması (türevde tık gibi görünür) ayrıca
"konuşmaya dokunmama" testinde kullanılır.
"""
import json
import math
import time

import numpy as np
import pytest
import soundfile as sf
from scipy import signal

from app.analysis import analyze_array
from app.enhance import (ADIM_ETIKETLERI, NEDEN_ETIKETLERI, detect_hum, enhance_file, enhance_reference,
                         quality_delta, should_enhance)

SR = 24000
RAPOR_ANAHTARLARI = {"applied", "noise_reduction_db", "hum_hz", "clicks_removed", "gain_db", "before_rms_db",
                     "after_rms_db"}
SIRA = ["dc", "declick", "dehum", "denoise", "highpass", "level"]


# ---------- sentetik sinyaller ve ölçüm yardımcıları ----------

def konusma(n_cumle=4, cumle_s=2.2, bosluk_s=0.4, bas_son_s=1.0, f0=150.0, tepe=0.5, gurultu_db=-35.0, tohum=0):
    """(gürültülü sinyal, temiz konuşma, konuşma maskesi, cümle sınırları [(başlangıç, bitiş) örnek])."""
    rng = np.random.default_rng(tohum)
    k_max = int(0.45 * SR / f0)
    faz = rng.uniform(0.0, 2 * np.pi, k_max)
    t = np.arange(int(cumle_s * SR)) / SR
    ton = sum(np.sin(2 * np.pi * k * f0 * t + faz[k - 1]) / k for k in range(1, k_max + 1))
    zarf = 0.25 + 0.75 * np.sin(np.pi * 5.0 * t) ** 2  # saniyede 5 hece
    n_y = int(0.02 * SR)
    rampa = np.linspace(0.0, 1.0, n_y)
    zarf[:n_y] *= rampa
    zarf[-n_y:] *= rampa[::-1]
    cumle = ton * zarf
    kenar = np.zeros(int(bas_son_s * SR))
    parcalar, sinirlar, konum = [kenar], [], kenar.size
    for i in range(n_cumle):
        parcalar.append(cumle)
        sinirlar.append((konum, konum + cumle.size))
        konum += cumle.size
        if i < n_cumle - 1:
            parcalar.append(np.zeros(int(bosluk_s * SR)))
            konum += int(bosluk_s * SR)
    parcalar.append(kenar)
    temiz = np.concatenate(parcalar)
    temiz *= tepe / np.max(np.abs(temiz))
    maske = np.zeros(temiz.size, dtype=bool)
    for a, b in sinirlar:
        maske[a:b] = True
    return temiz + 10 ** (gurultu_db / 20) * rng.standard_normal(temiz.size), temiz, maske, sinirlar


def girtlak_darbeli(f0=150.0, n_cumle=4, cumle_s=2.2, tepe=0.5, gurultu_db=-45.0, tohum=0):
    """Sıfır fazlı 1/k harmonikler (testere dişi) + tonlama: her periyotta gırtlak darbesi gibi keskin sıçrama."""
    rng = np.random.default_rng(tohum)
    parcalar = [np.zeros(SR)]
    for i in range(n_cumle):
        t = np.arange(int(cumle_s * SR)) / SR
        faz = 2 * np.pi * np.cumsum(f0 * 2 ** (3.0 * np.sin(2 * np.pi * 0.35 * t + i) / 12)) / SR
        k_max = int(0.45 * SR / (f0 * 2 ** (3.0 / 12)))
        x = sum(np.sin(k * faz) / k for k in range(1, k_max + 1))
        parcalar += [x * (0.25 + 0.75 * np.sin(np.pi * 5.0 * t) ** 2), np.zeros(int(0.4 * SR))]
    y = np.concatenate(parcalar)
    y *= tepe / np.max(np.abs(y))
    return y + 10 ** (gurultu_db / 20) * rng.standard_normal(y.size)


def rms_db(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    return 20 * math.log10(math.sqrt(float(np.mean(x * x))) + 1e-12)


def bant_db(x, f0, yari=3.0) -> float:
    """Welch PSD'de f0 ± yari Hz bandındaki toplam güç (dB)."""
    f, p = signal.welch(np.asarray(x, dtype=np.float64), fs=SR, nperseg=8192)
    return 10 * math.log10(float(p[(f >= f0 - yari) & (f <= f0 + yari)].sum()) + 1e-30)


def geri_olcekle(y, rapor) -> np.ndarray:
    """Seviye kazancını geri alır: işlem öncesi ölçekle karşılaştırma için."""
    return np.asarray(y, dtype=np.float64) / 10 ** (rapor["gain_db"] / 20)


def sinus(f, rms_dbfs, n, faz=0.0) -> np.ndarray:
    return 10 ** (rms_dbfs / 20) * math.sqrt(2) * np.sin(2 * np.pi * f * np.arange(n) / SR + faz)


def tik_konumlari(n, sinirlar, adet=20, tohum=5):
    """Rastgele tık konumları: birbirinden ≥ 60 ms, cümle başı/sonundan ≥ 50 ms uzakta (yan yana tıklar birbirini
    "yalıtık değil" gösterir; cümle başındaki tık konuşma başlangıcından ayırt edilemez, zaten maskelenir)."""
    rng = np.random.default_rng(tohum)
    ara, pay = int(0.06 * SR), int(0.05 * SR)
    secilen: list[int] = []
    while len(secilen) < adet:
        p = int(rng.integers(int(0.1 * SR), n - int(0.1 * SR)))
        if any(abs(p - q) < ara for q in secilen) or any(abs(p - s) < pay for ab in sinirlar for s in ab):
            continue
        secilen.append(p)
    return np.array(sorted(secilen)), rng.choice([-0.9, 0.9], adet)


# ---------- ortak (pahalı) işlemler ----------

@pytest.fixture(scope="module")
def gurultulu():
    x, temiz, maske, sinirlar = konusma()
    y, rapor = enhance_reference(x, SR)
    return x, temiz, maske, y, rapor


@pytest.fixture(scope="module")
def analizler(gurultulu):
    x, _, _, y, _ = gurultulu
    return analyze_array(x, SR), analyze_array(y, SR)


# ---------- rapor ve çıktı biçimi ----------

def test_rapor_semasi_json_ve_tipler(gurultulu):
    x, _, _, y, rapor = gurultulu
    assert set(rapor) == RAPOR_ANAHTARLARI
    json.dumps(rapor)  # yerleşik tipler: doğrudan JSON'a çevrilebilmeli
    assert isinstance(rapor["applied"], list) and all(isinstance(a, str) for a in rapor["applied"])
    assert set(rapor["applied"]) <= set(ADIM_ETIKETLERI)
    assert rapor["applied"] == sorted(rapor["applied"], key=SIRA.index)  # işlem sırası: dc → … → seviye
    assert type(rapor["clicks_removed"]) is int and rapor["clicks_removed"] == 0
    assert rapor["hum_hz"] is None
    for k in ("noise_reduction_db", "gain_db", "before_rms_db", "after_rms_db"):
        assert type(rapor[k]) is float
    assert rapor["before_rms_db"] == pytest.approx(rms_db(x), abs=0.1)
    assert rapor["after_rms_db"] == pytest.approx(rms_db(y), abs=0.1)
    assert set(NEDEN_ETIKETLERI) == {"noisy", "hum", "dc_offset", "too_quiet"}


def test_uzunluk_float32_ve_nan_yok(gurultulu):
    x, _, _, y, _ = gurultulu
    assert y.shape == x.shape and y.ndim == 1
    assert y.dtype == np.float32
    assert np.all(np.isfinite(y))
    for n in (int(0.3 * SR), 24001, 37333, 5 * SR + 7):  # tek/çift, FFT katı olmayan uzunluklar
        out, _ = enhance_reference(x[:n], SR)
        assert out.shape == (n,) and out.dtype == np.float32 and np.all(np.isfinite(out))


# ---------- gürültü azaltma ----------

def test_gurultu_azaltma_snr_en_az_6_db_artar(analizler):
    once, sonra = analizler
    assert once["snr_db"] < 30  # öncül: kayıt gerçekten gürültülü
    assert sonra["snr_db"] >= once["snr_db"] + 6.0
    assert sonra["noise_floor_dbfs"] <= once["noise_floor_dbfs"] - 6.0


def test_gurultu_azaltma_raporu_ve_yapaylik_siniri(gurultulu):
    x, _, maske, y, rapor = gurultulu
    assert "denoise" in rapor["applied"]
    assert 6.0 <= rapor["noise_reduction_db"] <= 12.5
    # boşluklardaki gerçek azalma: en az 6 dB, en çok yapaylık sınırı (12 dB) kadar
    azalma = rms_db(x[~maske]) - rms_db(geri_olcekle(y, rapor)[~maske])
    assert 6.0 <= azalma <= 12.5


def test_daha_dusuk_yapaylik_siniri_uygulanir():
    x, _, maske, _ = konusma()
    y, rapor = enhance_reference(x, SR, max_reduction_db=6.0)
    assert 3.0 <= rapor["noise_reduction_db"] <= 6.5
    assert rms_db(x[~maske]) - rms_db(geri_olcekle(y, rapor)[~maske]) <= 6.5


def test_konusma_bolgesi_rms_korunur(gurultulu):
    x, temiz, maske, y, rapor = gurultulu
    yc = geri_olcekle(y, rapor)
    assert abs(rms_db(yc[maske]) - rms_db(x[maske])) <= 1.5
    assert abs(rms_db(yc[maske]) - rms_db(temiz[maske])) <= 1.5


def test_harmonikler_korunur(gurultulu):
    x, _, maske, y, rapor = gurultulu
    yc = geri_olcekle(y, rapor)
    for h in (150.0, 300.0, 450.0):
        once, sonra = bant_db(x[maske], h), bant_db(yc[maske], h)
        assert abs(sonra - once) <= 1.0, h  # harmonik seviyesi değişmez
        vadi = bant_db(yc[maske], h + 75.0, yari=20.0)  # iki harmonik arası
        assert sonra - vadi >= 20.0, h  # tepe hâlâ belirgin
        assert sonra - vadi >= once - bant_db(x[maske], h + 75.0, yari=20.0) - 1.0, h  # belirginlik azalmaz


def test_duraklamasiz_konusmaya_gurultu_azaltma_uygulanmaz():
    # en sessiz kareler hece çukurları olur; o "profil" konuşmayı keserdi
    x, temiz, _, _ = konusma(n_cumle=1, cumle_s=3.0, bas_son_s=0.0)
    y, rapor = enhance_reference(x, SR)
    assert "denoise" not in rapor["applied"]
    assert abs(rms_db(geri_olcekle(y, rapor)) - rms_db(x)) <= 0.5


def test_analiz_gurultu_tabani_kapiyi_yalnizca_temkinli_yapar():
    x, _, maske, _ = konusma()
    _, normal = enhance_reference(x, SR)
    y, ipuclu = enhance_reference(x, SR, {"noise_floor_dbfs": -80.0})  # bu kayda göre gerçek dışı düşük taban
    assert ipuclu["noise_reduction_db"] <= normal["noise_reduction_db"] - 3.0
    # kapı neredeyse hiçbir şey yapmadıysa (< 0.5 dB) sonuç atılır: "applied" yalnızca gerçek değişikliği listeler
    assert ipuclu["noise_reduction_db"] >= 0.5 or "denoise" not in ipuclu["applied"]
    assert abs(rms_db(geri_olcekle(y, ipuclu)[maske]) - rms_db(x[maske])) <= 1.0
    _, tutarli = enhance_reference(x, SR, {"noise_floor_dbfs": rms_db(x[~maske])})  # doğru taban: etkisiz
    assert tutarli["noise_reduction_db"] == pytest.approx(normal["noise_reduction_db"], abs=0.3)


# ---------- uğultu ----------

def test_detect_hum():
    x, _, _, _ = konusma()
    n = x.size
    assert detect_hum(x, SR) is None  # 150 Hz konuşma + beyaz gürültü: uğultu yok
    assert detect_hum(x + sinus(50.0, -25.0, n, 0.4), SR) == 50.0
    assert detect_hum(x + sinus(60.0, -25.0, n), SR) == 60.0
    assert detect_hum(x + sinus(50.1, -25.0, n), SR) == 50.0  # şebeke frekansı biraz kaymış
    assert detect_hum(x + sinus(50.0, -70.0, n), SR) is None  # gürültünün altında kalan çizgi tepe sayılmaz
    assert detect_hum(x[: int(0.2 * SR)], SR) is None  # 50/60 Hz'i ayıracak çözünürlük yok
    assert detect_hum(np.zeros(2 * SR), SR) is None


def test_ugultu_giderilir_konusma_temeline_dokunulmaz():
    x, _, _, _ = konusma()
    xh = x + sinus(50.0, -25.0, x.size, 0.4)
    y, rapor = enhance_reference(xh, SR)
    yc = geri_olcekle(y, rapor)
    assert rapor["hum_hz"] == 50.0 and "dehum" in rapor["applied"]
    assert bant_db(xh, 50.0) - bant_db(yc, 50.0) >= 20.0
    assert abs(bant_db(yc, 150.0) - bant_db(xh, 150.0)) < 1.0  # 150 Hz konuşma temeli
    # notch tek başına da yeterli (yüksek geçiren ve gürültü azaltma kapalı)
    y2, r2 = enhance_reference(xh, SR, denoise=False, declick=False, highpass_hz=0)
    yc2 = geri_olcekle(y2, r2)
    assert r2["applied"] == ["dehum", "level"]
    assert bant_db(xh, 50.0) - bant_db(yc2, 50.0) >= 20.0
    assert abs(bant_db(yc2, 150.0) - bant_db(xh, 150.0)) < 1.0


@pytest.mark.parametrize("temel", [50.0, 60.0])
def test_ucuncu_harmonik_atlanir(temel):
    # uğultu 1., 2. ve 3. harmonikle; 3. harmonik (150/180 Hz) konuşmanın temel frekans bölgesinde: notch'lanmaz
    n = 10 * SR
    x = (sinus(temel, -25.0, n) + sinus(2 * temel, -30.0, n, 1.0) + sinus(3 * temel, -30.0, n, 2.0)
         + 10 ** (-50 / 20) * np.random.default_rng(3).standard_normal(n))
    y, rapor = enhance_reference(x, SR, denoise=False, declick=False, highpass_hz=0)
    yc = geri_olcekle(y, rapor)
    assert rapor["hum_hz"] == temel
    assert bant_db(x, temel) - bant_db(yc, temel) >= 20.0
    assert bant_db(x, 2 * temel) - bant_db(yc, 2 * temel) >= 20.0
    assert abs(bant_db(yc, 3 * temel) - bant_db(x, 3 * temel)) < 1.0


# ---------- tıklar ----------

def test_tiklar_temizlenir_ve_tepe_duser():
    x, _, _, sinirlar = konusma()
    konumlar, isaretler = tik_konumlari(x.size, sinirlar)
    xt = x.copy()
    xt[konumlar] += isaretler
    y, rapor = enhance_reference(xt, SR)
    yc = geri_olcekle(y, rapor)
    assert "declick" in rapor["applied"]
    assert 15 <= rapor["clicks_removed"] <= 20
    assert np.max(np.abs(yc)) < 0.75 * np.max(np.abs(xt))
    assert np.max(np.abs(yc)) <= np.max(np.abs(x)) * 1.15  # tıksız kaydın tepesine döner
    assert np.median(np.abs(yc[konumlar] - x[konumlar])) < 0.1  # tık yerlerinde sinyal yeniden kurulur


def test_konusmaya_tik_muamelesi_yapilmaz(gurultulu):
    assert gurultulu[4]["clicks_removed"] == 0
    # sıfır fazlı testere dişinde her periyotta keskin sıçrama var (küresel 8σ binlerce kez aşılır): dokunulmamalı
    x = girtlak_darbeli()
    y, rapor = enhance_reference(x, SR, denoise=False, dehum=False, highpass_hz=0)
    assert rapor["clicks_removed"] == 0 and "declick" not in rapor["applied"]
    assert np.corrcoef(y, x)[0, 1] > 0.99999


def test_seyrek_tiklar_yamalanir_yuzde_1_ustu_gurultu_sayilir():
    n = 12 * SR
    taban = 10 ** (-35 / 20) * np.random.default_rng(9).standard_normal(n)
    seyrek = taban.copy()
    seyrek[np.arange(SR // 8, n - SR // 8, SR // 4)] += 0.5  # 250 ms'de bir: toplam yama ≈ %0.85
    _, rapor = enhance_reference(seyrek, SR, denoise=False)
    assert rapor["clicks_removed"] == len(range(SR // 8, n - SR // 8, SR // 4))
    yogun = taban.copy()
    yogun[np.arange(SR // 8, n - SR // 8, SR // 10)] += 0.5  # 100 ms'de bir: ≈ %2.1 → gürültü, atla
    y, rapor = enhance_reference(yogun, SR, denoise=False)
    assert rapor["clicks_removed"] == 0 and "declick" not in rapor["applied"]


def test_sessizlikteki_tiklar():
    x = np.zeros(2 * SR)
    x[[5000, 20000, 33000]] = [0.5, -0.3, 0.2]
    y, rapor = enhance_reference(x, SR)
    assert rapor["clicks_removed"] == 3
    assert np.all(y == 0.0)


# ---------- DC, seviye, uç durumlar ----------

def test_dc_ofset_giderilir():
    x, _, _, _ = konusma()
    y, rapor = enhance_reference(x + 0.05, SR)
    assert "dc" in rapor["applied"] and rapor["applied"][0] == "dc"
    assert abs(float(np.mean(y))) < 0.002
    _, temiz_rapor = enhance_reference(x, SR)
    assert "dc" not in temiz_rapor["applied"]  # ihmal edilebilir ortalama raporlanmaz


def test_seviye_hedefi_ve_tepe_siniri(gurultulu):
    y, rapor = gurultulu[3], gurultulu[4]
    assert "level" in rapor["applied"]
    assert rms_db(y) == pytest.approx(-20.0, abs=0.3)
    assert np.max(np.abs(y)) <= 10 ** (-1 / 20) + 1e-6
    x, _, _, _ = konusma()
    kisik, r = enhance_reference(x * 10 ** (-25 / 20), SR, target_dbfs=-24.0)
    assert rms_db(kisik) == pytest.approx(-24.0, abs=0.3)
    assert r["gain_db"] > 15.0
    # tıklar bırakılırsa tepe sınırı devreye girer: RMS hedefin altında kalır, tepe tam -1 dBFS
    xt = x.copy()
    xt[SR * 3] += 0.95
    y2, r2 = enhance_reference(xt, SR, declick=False, target_dbfs=-12.0)
    assert 20 * math.log10(float(np.max(np.abs(y2)))) == pytest.approx(-1.0, abs=0.05)
    assert r2["after_rms_db"] < -12.0


def test_tum_adimlar_kapali_yalniz_seviye():
    x, _, _, _ = konusma()
    y, rapor = enhance_reference(x, SR, denoise=False, dehum=False, declick=False, highpass_hz=0)
    assert rapor["applied"] == ["level"]
    assert np.corrcoef(y, x)[0, 1] > 0.99999
    assert rms_db(y) == pytest.approx(-20.0, abs=0.3)


def test_yuksek_geciren_etkin_kesim_ve_derin_ses():
    n = 8 * SR
    x = (sinus(30.0, -30.0, n) + sinus(70.0, -30.0, n, 1.0) + sinus(300.0, -30.0, n, 2.0)
         + 10 ** (-70 / 20) * np.random.default_rng(4).standard_normal(n))
    kapali = dict(denoise=False, dehum=False, declick=False)
    y, r = enhance_reference(x, SR, **kapali)
    yc = geri_olcekle(y, r)
    assert "highpass" in r["applied"]
    assert bant_db(x, 70.0) - bant_db(yc, 70.0) == pytest.approx(3.0, abs=0.5)  # çift geçişte -3 dB = highpass_hz
    assert bant_db(x, 30.0) - bant_db(yc, 30.0) >= 15.0  # gümbürtü
    assert abs(bant_db(x, 300.0) - bant_db(yc, 300.0)) < 0.1
    # derin ses (en düşük perde 70 Hz): kesim 56 Hz'e iner, 70 Hz temel daha az etkilenir
    y2, r2 = enhance_reference(x, SR, {"f0": {"min_hz": 70.0}}, **kapali)
    yc2 = geri_olcekle(y2, r2)
    assert bant_db(x, 70.0) - bant_db(yc2, 70.0) < 1.6
    assert bant_db(x, 30.0) - bant_db(yc2, 30.0) >= 10.0


def test_kisa_girdi_oldugu_gibi_doner():
    x = konusma()[0][int(1.2 * SR): int(1.4 * SR)]  # 0.2 sn
    y, rapor = enhance_reference(x, SR)
    assert rapor["applied"] == [] and rapor["gain_db"] == 0.0
    assert y.dtype == np.float32 and y.shape == x.shape
    assert np.allclose(y, x.astype(np.float32))


def test_sessiz_ve_bos_girdi_cokmez():
    for x in (np.zeros(2 * SR), np.zeros(2 * SR, dtype=np.float32), np.zeros(0)):
        y, rapor = enhance_reference(x, SR)
        assert y.shape == x.shape and y.dtype == np.float32
        assert np.all(y == 0.0) and rapor["applied"] == []
        assert rapor["before_rms_db"] == rapor["after_rms_db"] == -120.0


def test_stereo_tamsayi_ve_nan_girdi():
    x, _, _, _ = konusma(n_cumle=2)
    stereo, _ = enhance_reference(np.stack([x, 0.5 * x], axis=1), SR)
    assert stereo.shape == (x.size,)
    pcm, _ = enhance_reference(np.round(x * 20000).astype(np.int16), SR)
    assert pcm.dtype == np.float32 and rms_db(pcm) == pytest.approx(-20.0, abs=0.3)
    bozuk = x.copy()
    bozuk[::997] = np.nan
    bozuk[5] = np.inf
    y, _ = enhance_reference(bozuk, SR)
    assert np.all(np.isfinite(y)) and y.shape == x.shape
    with pytest.raises(ValueError):
        enhance_reference(x, 0)


def test_performans_15_sn_kayit():
    x, _, _, sinirlar = konusma(n_cumle=5, cumle_s=2.4, bas_son_s=1.3)  # ≈ 15 sn
    konumlar, isaretler = tik_konumlari(x.size, sinirlar)
    x = x + sinus(50.0, -25.0, x.size)
    x[konumlar] += isaretler
    enhance_reference(x[:SR], SR)  # ısınma (ilk çağrı içe aktarma maliyeti taşımasın)
    t0 = time.perf_counter()
    _, rapor = enhance_reference(x, SR)
    sure = time.perf_counter() - t0
    assert x.size / SR >= 15.0
    assert set(rapor["applied"]) >= {"declick", "dehum", "denoise", "highpass", "level"}  # tüm adımlar çalıştı
    assert sure < 1.5, f"{sure:.2f} sn"


# ---------- karar ve puan ----------

def test_should_enhance_senaryolari():
    assert should_enhance(None) == (False, [])
    assert should_enhance({}) == (False, [])
    assert should_enhance({"snr_db": 18.0, "issues": [{"code": "noisy", "severity": "warn"}]}) == (True, ["noisy"])
    assert should_enhance({"snr_db": 25.0, "issues": []}) == (True, ["noisy"])  # yalnızca SNR kuralı
    assert should_enhance({"snr_db": 42.0, "issues": []}) == (False, [])
    assert should_enhance({"snr_db": 45.0, "issues": [{"code": "dc_offset"}, {"code": "too_quiet"},
                                                      {"code": "clipping"}, {"code": "reverb"}]}
                          ) == (True, ["dc_offset", "too_quiet"])  # kırpılma/yankı bu modülle düzelmez
    assert should_enhance({"snr_db": 45.0, "issues": [], "hum_hz": 50.0}) == (True, ["hum"])
    assert should_enhance({"snr_db": 10.0, "hum_hz": 60.0, "issues": [{"code": "too_quiet"}, {"code": "noisy"},
                                                                       {"code": "dc_offset"}]}
                          ) == (True, ["noisy", "hum", "dc_offset", "too_quiet"])
    # dijital sessizlik (konuşma yok): düşük SNR gürültüden değil
    assert should_enhance({"snr_db": 0.0, "noise_floor_dbfs": -120.0,
                           "issues": [{"code": "low_speech_ratio"}]}) == (False, [])


def test_should_enhance_gercek_analizlerle(analizler):
    assert should_enhance(analizler[0]) == (True, ["noisy"])
    temiz, _, _, _ = konusma(gurultu_db=-70.0)
    assert should_enhance(analyze_array(temiz, SR)) == (False, [])
    oneri, nedenler = should_enhance(analyze_array(temiz * 10 ** (-22 / 20), SR))  # ≈ -41 dBFS
    assert oneri and nedenler == ["too_quiet"]
    x, _, _, _ = konusma()
    assert should_enhance(analyze_array(x + 0.05, SR)) == (True, ["noisy", "dc_offset"])


def test_quality_delta(analizler):
    once, sonra = analizler
    assert quality_delta({"quality_score": 62}, {"quality_score": 80}) == 18
    assert quality_delta({"quality_score": 80}, {"quality_score": 62}) == -18
    assert quality_delta({}, {"quality_score": 50}) == 50
    assert type(quality_delta(once, sonra)) is int
    assert quality_delta(once, sonra) == sonra["quality_score"] - once["quality_score"]
    assert quality_delta(once, sonra) >= 3  # API'nin kabul ölçütü: gürültülü kayıtta iyileştirme uygulanır


# ---------- dosya ----------

def test_enhance_file_yedek_ve_hedef(tmp_path):
    x, _, _, _ = konusma(n_cumle=2, cumle_s=1.8)  # 6 sn
    kaynak = tmp_path / "ornek.wav"
    sf.write(str(kaynak), x.astype(np.float32), SR, subtype="PCM_16")
    ozgun = kaynak.read_bytes()
    hedef = tmp_path / "cikti" / "iyi.wav"
    yedek = tmp_path / "yedek" / "ornek.orig.wav"
    rapor = enhance_file(kaynak, hedef, yedek)
    assert yedek.read_bytes() == ozgun and kaynak.read_bytes() == ozgun
    bilgi = sf.info(str(hedef))
    assert bilgi.frames == x.size and bilgi.samplerate == SR and bilgi.channels == 1
    assert bilgi.subtype == "PCM_16"  # kaynağın örnek biçimi korunur
    assert set(rapor) == RAPOR_ANAHTARLARI | {"before", "after", "delta"}
    assert rapor["delta"] == quality_delta(rapor["before"], rapor["after"]) >= 3
    assert rapor["after"]["snr_db"] > rapor["before"]["snr_db"]
    json.dumps(rapor)
    assert not list(hedef.parent.glob(".*"))  # geçici dosya kalmaz
    # yerinde iyileştirme: kaynak değişir, yedek özgün kaydı tutar
    yedek2 = tmp_path / "ornek.orig.wav"
    enhance_file(kaynak, kaynak, yedek2)
    assert yedek2.read_bytes() == ozgun and kaynak.read_bytes() != ozgun
    assert sf.info(str(kaynak)).frames == x.size


def test_enhance_file_hatalari(tmp_path):
    with pytest.raises(FileNotFoundError):
        enhance_file(tmp_path / "yok.wav", tmp_path / "out.wav")
    bozuk = tmp_path / "bozuk.wav"
    bozuk.write_text("ses değil")
    with pytest.raises(ValueError, match="okunamadı"):
        enhance_file(bozuk, tmp_path / "out.wav")
    assert not (tmp_path / "out.wav").exists()
