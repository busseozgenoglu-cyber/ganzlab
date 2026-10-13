"""Üretilen parça kalite kontrolü (app.qc) testleri.

Gerçek TTS çıktısı yerine tohumlu (deterministik) sentetik "konuşma" kullanılır: 24 kHz, 150 Hz temel + harmonikler
(1/k, hafif tonlama) × ortalama 5 Hz hece zarfı; süre = karakter × 0,07 sn (≈ 14,3 karakter/sn). Hece süreleri
±%40 rastgeledir ve her hece rastgele bir Türkçe ünlünün formantlarıyla renklenir: gerçek konuşma gibi tam periyodik
değildir, MFCC'si değişir. Tam periyodik (sinüs zarflı, durağan spektrumlu) sinyal ayrıca yanlış pozitif koruması
için kullanılır.
"""
import json
import math
import time
from functools import lru_cache

import numpy as np
import pytest
from scipy import signal

from app import qc
from app.qc import apply_trim, check_chunk, estimate_cps, pick_best, summarize, trim_head, trim_tail

SR = 24000
SN_PER_KAR = 0.07
METIN = "Yarın sabah erkenden yola çıkacağız."  # 36 karakter, 13 hece → 2,52 sn; iç noktalama yok
BEKLENEN_CPS = 1 / SN_PER_KAR
UNLULER = {"a": (700, 1200), "e": (500, 1900), "ı": (350, 1400), "i": (300, 2200),
           "o": (500, 900), "ö": (450, 1600), "u": (320, 800), "ü": (300, 1700)}
SOZLESME_METRIKLERI = {"duration", "cps", "silence_ratio", "dropouts", "repeats", "clipping", "buzz", "tail_silence"}
KARARLAR = {"accept", "retry_seed", "retry_stable", "trim"}


@lru_cache(maxsize=None)
def _konusma(sure_s: float, tohum: int, formant: bool, sr: int) -> np.ndarray:
    rng = np.random.default_rng(tohum)
    n = int(round(sure_s * sr))
    t = np.arange(n) / sr
    f0, tonlama = 150.0, 2.0
    f_an = f0 * 2 ** (tonlama * np.sin(2 * np.pi * 0.3 * t + rng.uniform(0, 2 * np.pi)) / 12)
    faz = 2 * np.pi * np.cumsum(f_an) / sr
    k_max = int(0.45 * sr / (f0 * 2 ** (tonlama / 12)))
    kaynak = sum(np.sin(k * faz) / k for k in range(1, k_max + 1))
    # hece sınırları: ortalama 1/5 sn, ±%40 rastgele
    sinir = [0]
    while sinir[-1] < n:
        sinir.append(sinir[-1] + int(rng.uniform(0.6, 1.4) / 5.0 * sr))
    sinir[-1] = n
    zarf = np.empty(n)
    agirlik = np.zeros((len(UNLULER), n))
    for a, b in zip(sinir[:-1], sinir[1:]):
        u = np.linspace(0, 1, b - a, endpoint=False)
        zarf[a:b] = 0.2 + 0.8 * rng.uniform(0.55, 1.0) * np.sin(np.pi * u) ** 2
        agirlik[rng.integers(len(UNLULER)), a:b] = 1.0
    if formant:
        cekirdek = np.ones(int(0.03 * sr)) / int(0.03 * sr)
        x = np.zeros(n)
        for i, (f1, f2) in enumerate(UNLULER.values()):
            if not agirlik[i].any():
                continue
            b1, a1 = signal.iirpeak(f1, f1 / 90.0, fs=sr)
            b2, a2 = signal.iirpeak(f2, f2 / 120.0, fs=sr)
            renkli = 0.3 * kaynak + 1.5 * signal.lfilter(b1, a1, kaynak) + signal.lfilter(b2, a2, kaynak)
            x += np.convolve(agirlik[i], cekirdek, mode="same") * renkli
    else:
        x = kaynak
    x = x * zarf
    r = int(0.02 * sr)
    x[:r] *= np.linspace(0, 1, r)
    x[-r:] *= np.linspace(1, 0, r)
    y = (x / np.max(np.abs(x)) * 0.5).astype(np.float32)
    y.setflags(write=False)
    return y


def konusma(sure_s: float, tohum: int = 0, formant: bool = True, sr: int = SR) -> np.ndarray:
    """Konuşma benzeri sinyal (önbellekli; değiştirmeden önce kopyalanır)."""
    return _konusma(round(float(sure_s), 4), tohum, formant, sr).copy()


def metin_sesi(metin: str = METIN, tohum: int = 0, **kw) -> np.ndarray:
    return konusma(len(metin) * SN_PER_KAR, tohum, **kw)


def periyodik(sure_s: float, sr: int = SR) -> np.ndarray:
    """Tam periyodik test sinyali: sabit 150 Hz harmonikler × sin² 5 Hz zarf (durağan spektrum)."""
    t = np.arange(int(sure_s * sr)) / sr
    x = sum(np.sin(2 * np.pi * k * 150.0 * t) / k for k in range(1, 72))
    x = x * (0.25 + 0.75 * np.sin(np.pi * 5.0 * t) ** 2)
    return (x / np.max(np.abs(x)) * 0.5).astype(np.float32)


def sessizlik(sn: float) -> np.ndarray:
    return np.zeros(int(sn * SR), dtype=np.float32)


def kodlar(r: dict) -> list[str]:
    return [x["code"] for x in r["reasons"]]


def yerlesik_tipler(o) -> bool:
    if isinstance(o, dict):
        return all(isinstance(k, str) and yerlesik_tipler(v) for k, v in o.items())
    if isinstance(o, list):
        return all(yerlesik_tipler(v) for v in o)
    return o is None or type(o) in (int, float, str, bool)


# ---------- normal parça ----------

def test_normal_konusma_kabul_edilir():
    r = check_chunk(metin_sesi(), SR, METIN)
    m = r["metrics"]
    assert r["decision"] == "accept"
    assert r["ok"] is True
    assert r["score"] >= 85
    assert not [x for x in r["reasons"] if x["severity"] == "error"]
    assert m["duration"] == pytest.approx(2.52, abs=0.01)
    assert m["cps"] == pytest.approx(BEKLENEN_CPS, rel=0.03)
    assert 3.5 <= m["sps"] <= 7.0  # Türkçe tipik hece hızı
    assert m["repeats"] == 0 and m["dropouts"] == 0 and m["buzz"] is False
    assert m["silence_ratio"] < 0.1 and m["tail_silence"] < 100 and m["clipping"] == 0.0


@pytest.mark.parametrize("tohum", [1, 2, 3])
def test_farkli_tohumlarda_da_kabul(tohum):
    r = check_chunk(metin_sesi(tohum=tohum), SR, METIN)
    assert r["decision"] == "accept" and r["score"] >= 85


def test_rapor_yapisi_ve_json():
    r = check_chunk(metin_sesi(), SR, METIN, expected_cps=BEKLENEN_CPS)
    assert set(r) == {"score", "ok", "decision", "reasons", "metrics"}
    assert SOZLESME_METRIKLERI <= set(r["metrics"])
    assert isinstance(r["score"], int) and 0 <= r["score"] <= 100
    assert r["decision"] in KARARLAR
    assert yerlesik_tipler(r)
    json.dumps(r, ensure_ascii=False)


# ---------- uzama + tekrar ----------

def test_iki_kat_uzayan_parca_hem_uzun_hem_tekrar():
    x = metin_sesi()
    r = check_chunk(np.concatenate([x, x]), SR, METIN, expected_cps=BEKLENEN_CPS)
    assert {"too_long", "repeat"} <= set(kodlar(r))
    assert r["decision"] == "retry_seed"
    assert r["score"] <= 20  # 100 - 40 - 40
    m = r["metrics"]
    assert m["repeats"] >= 1
    assert m["repeat_lag"] == pytest.approx(2.52, abs=0.05)
    assert "%" in next(x["message"] for x in r["reasons"] if x["code"] == "too_long")


def test_tekrar_beklenen_hiz_olmadan_da_yakalanir():
    x = metin_sesi(tohum=4)
    r = check_chunk(np.concatenate([x, x]), SR, METIN)
    assert "repeat" in kodlar(r)
    assert r["decision"] == "retry_seed"
    assert "mfcc" in r["metrics"]["repeat_method"]


def test_kismi_tekrar_sonda_takilma():
    # cümle + son 0,9 sn'nin iki kez daha tekrarı ("…yola çıkacağız çıkacağız çıkacağız")
    x = metin_sesi(tohum=5)
    son = x[-int(0.9 * SR):]
    r = check_chunk(np.concatenate([x, son, son]), SR, METIN)
    assert "repeat" in kodlar(r)
    assert r["metrics"]["repeat_lag"] == pytest.approx(0.9, abs=0.05)
    assert r["metrics"]["repeats"] >= 2


def test_spektrumu_durgan_sinyalde_zarf_yontemi_yakalar():
    x = metin_sesi(tohum=6, formant=False)
    r = check_chunk(np.concatenate([x, x]), SR, METIN)
    assert "repeat" in kodlar(r)
    assert r["metrics"]["repeat_method"] == "zarf"


def test_tam_periyodik_test_sinyali_tekrar_sayilmaz():
    p = periyodik(len(METIN) * SN_PER_KAR)
    for y in (p, np.concatenate([p, p])):
        r = check_chunk(y, SR, METIN)
        assert r["metrics"]["repeats"] == 0
        assert "repeat" not in kodlar(r)


def test_metindeki_tekrar_cezalandirilmaz():
    metin = "Güzel bir gün, güzel bir gün."
    ifade = konusma(1.3, 11)
    y = np.concatenate([ifade, ifade])
    r = check_chunk(y, SR, metin)
    assert r["metrics"]["repeats"] >= 1 and r["metrics"]["repeat_expected"] is True
    assert "repeat" not in kodlar(r) and r["decision"] == "accept"
    # aynı ses, tekrarsız metinle: halüsinasyon sayılır
    assert check_chunk(y, SR, "Bugün hava gerçekten çok güzel.")["decision"] == "retry_seed"


# ---------- kısa / sessiz / boşluklu ----------

def test_yariya_inen_parca_cok_kisa():
    x = metin_sesi()
    r = check_chunk(x[: len(x) // 2], SR, METIN)
    assert "too_short" in kodlar(r)
    assert r["decision"] == "retry_seed"
    assert r["metrics"]["cps"] > 28
    assert "kesilmiş" in next(x["message"] for x in r["reasons"] if x["code"] == "too_short")


def test_ortadaki_iki_bosluk_dropout():
    x = metin_sesi()
    a, b = len(x) // 3, 2 * len(x) // 3
    y = np.concatenate([x[:a], sessizlik(0.4), x[a:b], sessizlik(0.4), x[b:]])
    r = check_chunk(y, SR, METIN)
    assert r["metrics"]["dropouts"] == 2
    assert "dropout" in kodlar(r)
    assert r["decision"] == "retry_stable"
    assert r["score"] == 70  # -15 × 2
    assert r["metrics"]["gaps_ms"] == [400, 400]


def test_tek_bosluk_yalnizca_uyari():
    x = metin_sesi()
    y = np.concatenate([x[: len(x) // 2], sessizlik(0.4), x[len(x) // 2:]])
    r = check_chunk(y, SR, METIN)
    assert kodlar(r) == ["pause"] and r["reasons"][0]["severity"] == "warn"
    assert r["decision"] == "accept" and r["score"] == 85


def test_noktalama_dogal_duraklama_hakki_verir():
    metin = "Geldim, gördüm. Sonra da hemen döndüm."
    x = metin_sesi(metin, tohum=7)
    a, b = len(x) // 3, 2 * len(x) // 3
    y = np.concatenate([x[:a], sessizlik(0.4), x[a:b], sessizlik(0.7), x[b:]])
    r = check_chunk(y, SR, metin)
    assert r["metrics"]["dropouts"] == 2 and r["metrics"]["natural_pauses"] == 2
    assert r["decision"] == "accept"
    # aynı boşluklar noktalamasız metinde takılmadır
    assert check_chunk(y, SR, metin.replace(",", "").replace(".", ""))["decision"] == "retry_stable"


def test_kisa_cok_cumleli_parca_sessizlik_sayilmaz():
    y = np.concatenate([konusma(0.45, 20), sessizlik(0.55), konusma(0.45, 21), sessizlik(0.55), konusma(0.45, 22)])
    r = check_chunk(y, SR, "Evet. Hayır. Belki.")
    assert r["metrics"]["silence_ratio"] > qc.SILENCE_RATIO_MAX  # ham oran eşiği aşar…
    assert r["decision"] == "accept"  # …ama duraklamaları noktalama açıklar


def test_cogu_sessiz_parca_silence():
    x = metin_sesi()
    y = np.concatenate([x[: len(x) // 2], sessizlik(3.0), x[len(x) // 2:]])
    r = check_chunk(y, SR, METIN)
    assert "silence" in kodlar(r)
    assert r["metrics"]["silence_ratio"] > 0.45
    assert r["decision"] == "retry_seed"


# ---------- kuyruk / baş ----------

def test_sondaki_sessizlik_kirpilir():
    y = np.concatenate([metin_sesi(), sessizlik(1.0)])
    r = check_chunk(y, SR, METIN)
    assert r["metrics"]["tail_silence"] == pytest.approx(1000, abs=20)
    assert kodlar(r) == ["tail"] and r["decision"] == "trim" and r["score"] == 95
    kirpik = trim_tail(y, SR)
    r2 = check_chunk(kirpik, SR, METIN)
    assert r2["metrics"]["tail_silence"] <= 250
    assert r2["decision"] == "accept"
    assert len(kirpik) < len(y)


def test_trim_head_ve_sinirlar():
    x = metin_sesi()
    y = np.concatenate([sessizlik(1.0), x])
    kirpik = trim_head(y, SR)
    assert check_chunk(kirpik, SR, METIN)["metrics"]["head_silence"] <= 150
    assert len(kirpik) == pytest.approx(len(x) + 0.15 * SR, abs=0.02 * SR)
    assert len(trim_tail(x, SR)) == len(x)  # kırpılacak bir şey yoksa dokunmaz
    assert len(trim_tail(sessizlik(2.0), SR)) == int(0.25 * SR)


def test_apply_trim_kuyruk_ve_kirpilma():
    y = np.concatenate([sessizlik(0.8), np.clip(metin_sesi() * 4, -1, 1), sessizlik(1.0)])
    r = check_chunk(y, SR, METIN)
    assert {"clipping", "tail"} <= set(kodlar(r)) and r["decision"] == "trim"
    z = apply_trim(y, SR, r)
    r2 = check_chunk(z, SR, METIN)
    assert r2["metrics"]["clipping"] == 0.0 and r2["metrics"]["tail_silence"] <= 250
    assert r2["metrics"]["head_silence"] <= 150 and r2["decision"] == "accept"


def test_asiri_uzun_tekrarsiz_parca_kirpilir():
    x = metin_sesi()
    gurultu = (np.random.default_rng(3).standard_normal(int(10 * SR)) * 0.02).astype(np.float32)
    y = np.concatenate([x, gurultu])  # cümleden sonra 10 sn anlamsız ses
    r = check_chunk(y, SR, METIN)
    uzun = next(x for x in r["reasons"] if x["code"] == "too_long")
    assert uzun["action"] == "trim" and r["decision"] == "trim"
    z = apply_trim(y, SR, r)
    assert len(z) / SR <= r["metrics"]["max_duration"] + 0.5
    # cümle + duraklama + anlamsız ses: cümleden sonraki duraklamadan kesilir
    y2 = np.concatenate([x, sessizlik(0.5), gurultu])
    z2 = apply_trim(y2, SR, check_chunk(y2, SR, METIN))
    assert len(z2) / SR == pytest.approx(len(x) / SR, abs=0.15)
    # cümle içindeki (beklenen sürenin %80'inden önceki) duraklamadan asla kesilmez
    y3 = np.concatenate([x[: len(x) // 2], sessizlik(0.4), x[len(x) // 2:], gurultu])
    z3 = apply_trim(y3, SR, check_chunk(y3, SR, METIN))
    assert len(z3) / SR > len(x) / SR + 0.4


# ---------- vızıltı / uğultu / kırpılma ----------

def test_6_khz_sinus_vizilti():
    x = metin_sesi()
    t = np.arange(len(x)) / SR
    r = check_chunk(x + 0.1 * np.sin(2 * np.pi * 6000 * t).astype(np.float32), SR, METIN)  # -20 dBFS
    assert "buzz" in kodlar(r) and r["decision"] == "retry_stable"
    assert r["metrics"]["buzz_hz"] == pytest.approx(6000, abs=15)
    assert r["metrics"]["buzz_db"] >= 15
    # duyulmayacak kadar kısık ton (-80 dBFS) sayılmaz
    sessiz_ton = x + 1e-4 * np.sin(2 * np.pi * 6000 * t).astype(np.float32)
    assert check_chunk(sessiz_ton, SR, METIN)["metrics"]["buzz"] is False


def test_50_hz_sebeke_ugultusu():
    x = metin_sesi()
    t = np.arange(len(x)) / SR
    r = check_chunk(x + 0.03 * np.sin(2 * np.pi * 50 * t).astype(np.float32), SR, METIN)
    assert "buzz" in kodlar(r)
    assert r["metrics"]["buzz_hz"] == 50.0
    assert "uğultu" in next(x["message"] for x in r["reasons"] if x["code"] == "buzz")


def test_kirpilmis_sinyal():
    r = check_chunk(np.clip(metin_sesi() * 4, -1, 1), SR, METIN)
    assert kodlar(r) == ["clipping"]
    assert r["metrics"]["clipping"] > 0.001
    assert r["decision"] == "trim" and r["score"] == 90


# ---------- beklenen hız ----------

def test_beklenen_hiz_esikleri_kaydirir():
    x = metin_sesi()  # 14,3 kar/sn
    assert check_chunk(x, SR, METIN)["decision"] == "accept"
    assert check_chunk(x, SR, METIN, expected_cps=25)["decision"] == "accept"  # alt sınır 13,75
    r_yavas = check_chunk(x, SR, METIN, expected_cps=30)  # alt sınır 16,5 → bu ses "uzun"
    assert "too_long" in kodlar(r_yavas) and r_yavas["decision"] == "retry_seed"
    assert r_yavas["metrics"]["cps_range"] == [16.5, 43.5]
    r_hizli = check_chunk(x, SR, METIN, expected_cps=8)  # üst sınır 11,6 → bu ses "kısa"
    assert "too_short" in kodlar(r_hizli)


def test_yavas_konusmaci_icin_beklenen_hiz():
    x = konusma(len(METIN) * 0.112, 8)  # 8,9 kar/sn: varsayılan sınırların içinde
    assert check_chunk(x, SR, METIN)["decision"] == "accept"
    assert "too_long" in kodlar(check_chunk(x, SR, METIN, expected_cps=20))  # hızlı konuşan bir ses için uzun
    assert check_chunk(x, SR, METIN, expected_cps=9)["decision"] == "accept"  # yavaş konuşan bir ses için normal


def test_tek_olcut_disarida_uyari():
    # 6,5 kar/sn (cps içeride) ama 2,3 hece/sn (sps dışarıda) → yalnızca uyarı, -15
    x = konusma(len(METIN) / 6.5, 9)
    r = check_chunk(x, SR, METIN)
    assert kodlar(r) == ["rate"] and r["reasons"][0]["severity"] == "warn"
    assert r["score"] == 85 and r["decision"] == "accept"


# ---------- estimate_cps / pick_best / summarize ----------

def test_estimate_cps():
    assert estimate_cps([(40, 2.8), (30, 2.1), (50, 3.6)]) == pytest.approx(14.29, abs=0.01)
    assert estimate_cps([(40, 2.8), (30, 2.1)]) is None  # < 3 örnek
    assert estimate_cps([]) is None
    # 4–40 dışı (100 ve 2 kar/sn) ve bozuk örnekler atılır → geriye 2 örnek kalır
    assert estimate_cps([(40, 2.8), (30, 2.1), (10, 0.1), (10, 5.0), (0, 1.0), (5, 0.0)]) is None
    assert estimate_cps([(40, 2.8), (30, 2.1), (36, 2.4), (10, 0.1), ("bozuk", 1)]) == pytest.approx(14.29, abs=0.01)


def test_pick_best():
    assert pick_best([{"score": 50}, {"score": 80}, {"score": 80}]) == 1  # eşitlikte ilk
    assert pick_best([{"score": 30}]) == 0
    raporlar = [check_chunk(y, SR, METIN) for y in (np.concatenate([metin_sesi()] * 2), metin_sesi())]
    assert pick_best(raporlar) == 1
    with pytest.raises(ValueError):
        pick_best([])


def test_summarize():
    raporlar = [check_chunk(metin_sesi(), SR, METIN),
                check_chunk(np.concatenate([metin_sesi()] * 2), SR, METIN, expected_cps=BEKLENEN_CPS),
                check_chunk(np.concatenate([metin_sesi(), sessizlik(1.0)]), SR, METIN)]
    raporlar[2]["index"] = 7
    s = summarize(raporlar)
    assert s["count"] == 3
    assert s["mean_score"] == pytest.approx((100 + 20 + 95) / 3, abs=0.1)
    assert s["retries"] == 1
    assert s["worst"]["index"] == 1 and s["worst"]["score"] == 20
    assert {"too_long", "repeat"} <= set(s["worst"]["codes"]) and s["worst"]["message"]
    assert s["decisions"] == {"accept": 1, "retry_seed": 1, "trim": 1}
    assert yerlesik_tipler(s)
    assert summarize([{"score": 90, "decision": "accept", "reasons": [], "attempts": 3}])["retries"] == 2
    assert summarize([]) == {"count": 0, "mean_score": None, "retries": 0, "worst": None, "decisions": {},
                             "codes": {}}


# ---------- dayanıklılık ----------

@pytest.mark.parametrize("girdi", [np.zeros(0, np.float32), np.full(100, 0.1, np.float32), sessizlik(2.0),
                                   np.full(SR // 50, np.nan, np.float32), None])
def test_bos_ve_cok_kisa_girdi_cokmez(girdi):
    r = check_chunk(girdi, SR, METIN)
    assert r["score"] == 0 and r["ok"] is False
    assert r["decision"] == "retry_seed"
    assert r["reasons"] and SOZLESME_METRIKLERI <= set(r["metrics"])
    json.dumps(r)


def test_bos_metin_ve_gecersiz_beklenen_hiz():
    x = metin_sesi()
    assert check_chunk(x, SR, "")["decision"] == "accept"  # metin yoksa hız denetlenmez
    for bozuk in (0, -3, float("nan"), "abc", 1000):  # geçersiz / 4–40 dışı: yok sayılır, varsayılan eşikler
        r = check_chunk(x, SR, METIN, expected_cps=bozuk)
        assert r["decision"] == "accept" and r["metrics"]["expected_cps"] is None
    with pytest.raises(ValueError):
        check_chunk(x, 0, METIN)


def test_int16_stereo_ve_diger_ornekleme_hizlari():
    x = metin_sesi()
    assert check_chunk((x * 32767).astype(np.int16), SR, METIN)["decision"] == "accept"
    assert check_chunk(np.stack([x, x], axis=1), SR, METIN)["decision"] == "accept"
    for sr in (16000, 44100):
        y = konusma(len(METIN) * SN_PER_KAR, 0, sr=sr)
        assert check_chunk(y, sr, METIN)["decision"] == "accept"
        assert "repeat" in kodlar(check_chunk(np.concatenate([y, y]), sr, METIN))


def test_girdiyi_degistirmez():
    x = np.concatenate([metin_sesi(), sessizlik(1.0)])
    kopya = x.copy()
    r = check_chunk(x, SR, METIN)
    trim_tail(x, SR)
    trim_head(x, SR)
    apply_trim(x, SR, r)
    assert np.array_equal(x, kopya)


def test_performans_20_sn():
    metin = ("Bugün sizlere küçük bir kasabada geçen, sıradan görünen ama aslında çok şaşırtıcı bir hikâye "
             "anlatacağım. Kasabanın en yaşlı fırıncısı her sabah güneş doğmadan kalkar, hamurunu yoğurur ve "
             "komşularına sıcacık ekmek dağıtırdı. Bir gün kapısının önünde, kimsenin daha önce görmediği bir "
             "mektup buldu.")
    x = konusma(20.0, 12)
    check_chunk(x, SR, metin)  # ısınma (librosa tembel içe aktarımları)
    sureler = []
    for _ in range(3):
        t0 = time.perf_counter()
        r = check_chunk(x, SR, metin)
        sureler.append(time.perf_counter() - t0)
    assert min(sureler) < 0.3, f"20 sn'lik parça {min(sureler) * 1000:.0f} ms sürdü"
    assert r["decision"] == "accept"
    assert math.isclose(r["metrics"]["duration"], 20.0, abs_tol=0.01)
