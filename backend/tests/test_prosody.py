"""prosody — duraklama planı, nefes, oda tonu, doğal birleştirme, mastering ve ses yüksekliği ölçümü testleri.

Sentetik "konuşma" olarak 1 kHz sinüs + hece benzeri zarf kullanılır. ffmpeg gerektiren testler ffmpeg yoksa
atlanır (skip); saf Python yedekleri ffmpeg'siz ortamı taklit ederek ayrıca sınanır.
"""
import shutil
import time

import numpy as np
import pytest
from numpy.lib.stride_tricks import sliding_window_view

from app import prosody
from app.audio import db_to_amp, fade
from app.prosody import (
    join_natural,
    make_room_tone,
    master,
    measure_loudness,
    plan_breaths,
    plan_pauses,
    synth_breath,
)

SR = 24000
FFMPEG_VAR = shutil.which("ffmpeg") is not None
ffmpeg_gerekir = pytest.mark.skipif(not FFMPEG_VAR, reason="ffmpeg kurulu değil")

NOTR = "Bugün hava oldukça güzel görünüyor."          # 35 karakter: ne kısa ne uzun
NOTR_SONRAKI = "Yarın yine buradayız."


# ---------- yardımcılar ----------

def konusma(saniye: float, genlik: float = 0.5, sr: int = SR, f: float = 1000.0) -> np.ndarray:
    """1 kHz sinüs + 3 Hz hece zarfı: sentetik "konuşma"."""
    t = np.arange(int(round(saniye * sr))) / sr
    zarf = 0.55 + 0.45 * np.sin(2 * np.pi * 3.0 * t)
    return (genlik * zarf * np.sin(2 * np.pi * f * t)).astype(np.float32)


def sinus(saniye: float, genlik: float = 1.0, sr: int = SR, f: float = 1000.0) -> np.ndarray:
    t = np.arange(int(round(saniye * sr))) / sr
    return (genlik * np.sin(2 * np.pi * f * t)).astype(np.float32)


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-20))


def parca(text, punct="", pause=400, paragraph_end=False, next_text=None, emotion=None) -> dict:
    return {"text": text, "punct": punct, "emotion": emotion, "pause_after_ms": pause,
            "paragraph_end": paragraph_end, "next_text": next_text}


def ilk_duraklama(sonraki, punct="", text=NOTR, pause=400, seed=7, paragraph_end=False, pause_scale=1.0) -> int:
    """İki parçalık listede birinci parçanın duraklaması (aynı tohum → aynı titreşim, oranlar karşılaştırılabilir)."""
    ch = [parca(text, punct, pause, paragraph_end, next_text=sonraki), parca(sonraki or "Son.")]
    return plan_pauses(ch, pause_scale=pause_scale, seed=seed)[0]


# ======================= plan_pauses =======================

def test_duraklama_bos_liste_ve_tipler():
    assert plan_pauses([]) == []
    ch = [parca(NOTR, next_text=NOTR_SONRAKI), parca(NOTR_SONRAKI, next_text=None)]
    out = plan_pauses(ch, seed=1)
    assert len(out) == 2
    assert all(isinstance(v, int) for v in out), "duraklamalar int olmalı"


@pytest.mark.parametrize("sonraki", [
    "Ama yine de gitmedik.", "Çünkü çok yorgunduk.", "Ve sonunda geldik.", "Ya da hiç gitmeyelim.",
    "Daha sonra konuşuruz.", "O zaman başlayalım.", "İşte böyle oldu.", "Lâkin kimse gelmedi.",
    "— Peki, ne yapacağız?", "Bu yüzden erken çıktık.", "Hem de nasıl!", "«Yani anlayacağın, bitti.»",
])
def test_baglacla_baslayan_cumle_duraklamayi_kisaltir(sonraki):
    temel = ilk_duraklama(NOTR_SONRAKI)
    assert ilk_duraklama(sonraki) == pytest.approx(temel * 0.65, abs=1.5), f"{sonraki!r} bağlaç sayılmadı"


@pytest.mark.parametrize("sonraki", [
    "Amaç belliydi.", "Veriler geldi.", "Kitap masadaydı.", "Deniz çok güzeldi.", "Davul çaldı.",
    "Sonbahar geldi.", "Yabancı biri kapıdaydı.", "Bir gün döneceğim.", "Odalar boştu.", "3 kişi geldi, ama geç.",
])
def test_baglac_tam_sozcuk_olarak_aranir(sonraki):
    assert ilk_duraklama(sonraki) == ilk_duraklama(NOTR_SONRAKI), f"{sonraki!r} yanlışlıkla bağlaç sayıldı"


def test_soru_cevap_ritmi():
    soru = "Bu akşam bize gelecek misin?"
    duz = ilk_duraklama("Evet, gelirim.", punct="", text=soru)
    assert ilk_duraklama("Evet, gelirim.", punct="?", text=soru) == pytest.approx(duz * 0.8, abs=1.5)
    uzun_cevap = "Evet, gelirim ama biraz geç kalabilirim, işten çıkmam zor olacak."
    assert ilk_duraklama(uzun_cevap, punct="?", text=soru) == ilk_duraklama(uzun_cevap, punct="", text=soru), \
        "uzun cevapta soru-cevap kısaltması olmamalı"


def test_uzun_ve_kisa_cumle_carpanlari():
    temel = ilk_duraklama(NOTR_SONRAKI)
    uzun = ("Bu cümle bilerek çok uzun yazıldı, çünkü dinleyicinin nefeslenmesi ve anlamı sindirmesi için "
            "uzun bir cümleden sonra biraz daha uzun bir duraklama gerekir, aksi halde akış boğucu olur.")
    assert len(uzun) > 140
    assert ilk_duraklama(NOTR_SONRAKI, text=uzun) == pytest.approx(temel * 1.15, abs=1.5)
    assert ilk_duraklama(NOTR_SONRAKI, text="Evet.") == pytest.approx(temel * 0.85, abs=1.5)
    # "..." için ek çarpan yok
    assert ilk_duraklama(NOTR_SONRAKI, punct="...", text=NOTR) == temel


def test_son_parca_sifir_ve_next_text_cikarimi():
    ch = [parca("Birinci cümle burada.", next_text="İkinci cümle burada."),
          parca("İkinci cümle burada.", next_text=None)]
    out = plan_pauses(ch, seed=3)
    assert out[1] == 0 and out[0] > 0
    # next_text anahtarı hiç yoksa listedeki sonraki parçanın metni kullanılır (bağlaç kuralı dahil)
    a = [{"text": NOTR, "punct": "", "pause_after_ms": 400}, {"text": "Ama ikinci.", "pause_after_ms": 400}]
    b = [{"text": NOTR, "punct": "", "pause_after_ms": 400}, {"text": "Yarın ikinci.", "pause_after_ms": 400}]
    pa, pb = plan_pauses(a, seed=3), plan_pauses(b, seed=3)
    assert pa[1] == 0 and pb[1] == 0
    assert pa[0] == pytest.approx(pb[0] * 0.65, abs=1.5)


def test_eksik_temel_degerde_varsayilan():
    out = plan_pauses([{"text": "Merhaba.", "next_text": "Nasılsın?"}], seed=0)
    assert 60 <= out[0] <= 2500 and out[0] > 0


def test_sikistirma_sinirlari():
    assert ilk_duraklama(NOTR_SONRAKI, pause=10_000) == 2500
    assert ilk_duraklama(NOTR_SONRAKI, pause=5) == 60
    ch = [parca(NOTR, pause=400, next_text=NOTR_SONRAKI), parca(NOTR_SONRAKI)]
    assert plan_pauses(ch, pause_scale=9.0, seed=5) == plan_pauses(ch, pause_scale=2.0, seed=5)
    assert plan_pauses(ch, pause_scale=0.01, seed=5) == plan_pauses(ch, pause_scale=0.5, seed=5)
    assert plan_pauses(ch, pause_scale=2.0, seed=5)[0] == pytest.approx(plan_pauses(ch, seed=5)[0] * 2, abs=2)


def test_paragraf_sonu_en_az_600():
    for s in range(25):
        assert ilk_duraklama("Ama yeni paragraf başlıyor.", pause=300, paragraph_end=True, seed=s,
                             pause_scale=0.5) >= 600


def test_tohum_belirlenimci_ve_titresim_araligi():
    ch = [parca(NOTR, pause=500, next_text=NOTR_SONRAKI) for _ in range(8)] + [parca("Son cümle burada.")]
    a = plan_pauses(ch, seed=42)
    assert a == plan_pauses(ch, seed=42), "aynı tohum aynı planı vermeli"
    assert plan_pauses(ch, seed=43) != a
    assert len(set(a[:-1])) > 1, "titreşim her duraklamayı farklı kılmalı"
    for s in [None] + list(range(30)):
        for v in plan_pauses(ch, seed=s)[:-1]:
            assert 500 * 0.88 - 1 <= v <= 500 * 1.12 + 1, f"±%12 dışında: {v}"
    # tohum yoksa titreşim rastgele: farklı çağrılar farklı değerler üretir
    degerler = {v for _ in range(4) for v in plan_pauses(ch)[:-1]}
    assert len(degerler) > 5


# ======================= plan_breaths =======================

def nefes_parca(text="Bu, nefes testi için yazılmış orta uzunlukta bir cümle.", punct="", paragraph_end=False,
                emotion=None) -> dict:
    return parca(text, punct, 400, paragraph_end, None, emotion)


def test_nefes_ilk_parca_ve_aralik_kurali():
    ch = [nefes_parca() for _ in range(6)]
    plan = plan_breaths(ch, [3.0] * 6, min_gap_s=6.0, seed=1)
    assert plan[0] is False
    assert plan == [False, False, True, False, True, False]
    assert plan_breaths([], []) == []


def test_kisa_parcadan_once_nefes_yok():
    ch = [nefes_parca() for _ in range(4)]
    # i=2: 8 sn konuşuldu ama parça 1.5 sn (< 2.5) → hayır; i=3: 9.5 sn ve parça 4 sn → evet
    assert plan_breaths(ch, [4.0, 4.0, 1.5, 4.0], min_gap_s=6.0, seed=1) == [False, False, False, True]


def test_paragraf_basinda_nefes():
    ch = [nefes_parca("Birinci paragraf.", paragraph_end=True), nefes_parca("Kısa."), nefes_parca()]
    plan = plan_breaths(ch, [1.0, 0.8, 1.0], seed=0)
    assert plan == [False, True, False]


def test_fisiltida_nefes_yok():
    ch = [nefes_parca(paragraph_end=True), nefes_parca(emotion="fısıltı"), nefes_parca(emotion="Fısıltı")]
    assert plan_breaths(ch, [8.0, 8.0, 8.0], seed=0) == [False, False, False]


def test_unlem_sonrasi_nefes_daha_sik():
    sure = [2.5, 2.5, 2.5]
    duz = [nefes_parca() for _ in range(3)]
    unlem = [nefes_parca("Harika bir haber bu!", punct="!") for _ in range(3)]
    assert plan_breaths(duz, sure, min_gap_s=6.0, seed=0)[2] is False      # 5.0 < 6.0
    assert plan_breaths(unlem, sure, min_gap_s=6.0, seed=0)[2] is True     # 5.0 ≥ 6.0 × 0.8


def test_uc_nokta_sonrasi_nefes_olasiligi_yuksek():
    ch = [nefes_parca("Bilmiyorum, belki de...", punct="..."), nefes_parca()]
    sayi = sum(plan_breaths(ch, [2.0, 2.0], min_gap_s=6.0, seed=s)[1] for s in range(200))
    assert 120 < sayi < 190, f"'...' sonrası nefes oranı beklenen ~%75 değil: {sayi}/200"
    duz = [nefes_parca("Bilmiyorum, belki de."), nefes_parca()]
    assert not any(plan_breaths(duz, [2.0, 2.0], min_gap_s=6.0, seed=s)[1] for s in range(50))


def test_nefes_plani_belirlenimci_ve_uzun_sure_nefessiz_kalmaz():
    ch = [nefes_parca("Ve sonra...", punct="...") if i % 2 else nefes_parca() for i in range(12)]
    sure = [2.0 + 0.3 * i for i in range(12)]
    assert plan_breaths(ch, sure) == plan_breaths(ch, sure), "tohumsuz plan da belirlenimci olmalı"
    assert plan_breaths(ch, sure, seed=9) == plan_breaths(ch, sure, seed=9)
    # 1.2 sn'lik parçalar: aralık kuralı hiç tetiklenmez ama 12 sn nefessiz konuşulmaz
    kisa = [nefes_parca() for _ in range(20)]
    assert any(plan_breaths(kisa, [1.2] * 20, min_gap_s=6.0, seed=0))


def test_eksik_sureler_metinden_tahmin_edilir():
    uzun = "Bu oldukça uzun bir cümle, içinde pek çok hece ve sözcük barındırıyor, dinleyiciyi yorabilir."
    plan = plan_breaths([nefes_parca(uzun) for _ in range(5)], [], min_gap_s=6.0)
    assert len(plan) == 5 and plan[0] is False and any(plan)


# ======================= synth_breath =======================

def test_sentetik_nefes_uzunluk_seviye_tepe():
    b = synth_breath(SR, 320, -34.0, seed=1)
    assert b.dtype == np.float32 and b.ndim == 1
    assert b.size == int(round(SR * 0.320))
    assert rms_db(b) == pytest.approx(-34.0, abs=0.3)
    assert np.max(np.abs(b)) < 0.3
    assert abs(float(b[0])) < 1e-3 and abs(float(b[-1])) < 1e-3, "nefes yumuşak başlayıp bitmeli"
    assert synth_breath(16000, 250, seed=3).size == 4000
    assert synth_breath(SR, 0).size == 0
    # çok yüksek seviye istense bile tepe 0.3'ün altında kalır
    assert np.max(np.abs(synth_breath(SR, 300, -3.0, seed=2))) < 0.3


def test_sentetik_nefes_bant_ve_asimetrik_zarf():
    b = synth_breath(SR, 400, seed=4).astype(np.float64)
    guc = np.abs(np.fft.rfft(b)) ** 2
    f = np.fft.rfftfreq(b.size, 1 / SR)
    assert guc[(f >= 250) & (f <= 4500)].sum() / guc.sum() > 0.85, "enerji 300–4000 Hz bandında olmalı"
    kare = (b[: b.size // 40 * 40].reshape(40, -1) ** 2).mean(axis=1)
    tepe = int(np.argmax(np.convolve(kare, np.ones(5) / 5, mode="same")))
    assert tepe < 20, "hızlı yükseliş: enerji tepesi ilk yarıda olmalı"


def test_sentetik_nefes_tohum():
    assert np.array_equal(synth_breath(SR, seed=5), synth_breath(SR, seed=5))
    assert not np.array_equal(synth_breath(SR, seed=5), synth_breath(SR, seed=6))


# ======================= make_room_tone =======================

def test_oda_tonu_bos_seviye_ve_kenarlar():
    assert make_room_tone(0, SR).size == 0
    rt = make_room_tone(SR * 2, SR, level_db=-58.0, seed=1)
    assert rt.dtype == np.float32 and rt.size == SR * 2
    assert rms_db(rt) == pytest.approx(-58.0, abs=0.5)
    assert rt[0] == 0.0 and rt[-1] == 0.0, "başı/sonu yumuşatılmalı"
    assert np.array_equal(make_room_tone(SR, SR, seed=3), make_room_tone(SR, SR, seed=3))


def test_pembe_gurultu_alcak_frekansta_guclu():
    rt = make_room_tone(SR * 4, SR, level_db=-40.0, seed=2).astype(np.float64)
    guc = np.abs(np.fft.rfft(rt)) ** 2
    f = np.fft.rfftfreq(rt.size, 1 / SR)
    alcak = guc[(f >= 100) & (f < 500)].mean()
    orta = guc[(f >= 1000) & (f < 2000)].mean()
    yuksek = guc[(f >= 4000) & (f < 8000)].mean()
    assert alcak > 5 * yuksek, "pembe gürültü alçak frekansta daha güçlü olmalı"
    assert alcak > orta > yuksek
    assert guc[(f > 5) & (f < 60)].mean() < 0.01 * guc[(f >= 100) & (f < 200)].mean(), "80 Hz altı kesilmeli"


def _tabandan_mi(pencere: np.ndarray, taban: np.ndarray) -> float:
    """Pencere, tabanın bir parçasının ölçekli kopyası mı? (en yüksek normalize ilinti)"""
    w = sliding_window_view(taban.astype(np.float64), pencere.size)
    w = w - w.mean(axis=1, keepdims=True)
    p = pencere.astype(np.float64) - pencere.mean()
    return float(np.max((w @ p) / (np.linalg.norm(w, axis=1) * np.linalg.norm(p) + 1e-20)))


def test_oda_tonu_kisa_ornekten_uzun_dongu():
    taban = (np.random.default_rng(0).standard_normal(int(0.3 * SR)) * db_to_amp(-45)).astype(np.float32)
    rt = make_room_tone(SR * 3, SR, floor_sample=taban, level_db=-50.0, seed=3)
    assert rt.size == SR * 3
    assert rms_db(rt[SR // 10: -SR // 10]) == pytest.approx(-50.0, abs=0.7)
    eslesen = sum(_tabandan_mi(rt[s: s + 200], taban) > 0.999 for s in range(SR // 5, 3 * SR - 400, SR // 2))
    assert eslesen >= 4, "çıktı tabandan döngülenmiş olmalı"


def test_oda_tonu_dongu_eklemi_puruzsuz():
    t = np.arange(int(0.31 * SR)) / SR
    taban = (0.01 * np.cos(2 * np.pi * 50 * t)).astype(np.float32)   # +1'de başlar, ≈−1'de biter (15.5 periyot)
    dogal = float(np.max(np.abs(np.diff(taban))))
    assert np.max(np.abs(np.diff(np.tile(taban, 3)))) > 50 * dogal, "çapraz geçişsiz döngü eklemde sıçramalı"
    rt = make_room_tone(SR * 2, SR, floor_sample=taban, level_db=-40.0, seed=4)
    kazanc = db_to_amp(-40.0) / (0.01 / np.sqrt(2))
    assert np.max(np.abs(np.diff(rt))) < 3 * dogal * kazanc


def test_oda_tonu_en_fazla_6db_yukseltir():
    temiz = (np.random.default_rng(1).standard_normal(SR // 2) * db_to_amp(-75)).astype(np.float32)
    assert rms_db(make_room_tone(SR * 2, SR, floor_sample=temiz, seed=1)[SR // 10: -SR // 10]) == \
        pytest.approx(-69.0, abs=0.7)
    gurultulu = (np.random.default_rng(2).standard_normal(SR // 2) * db_to_amp(-40)).astype(np.float32)
    assert rms_db(make_room_tone(SR * 2, SR, floor_sample=gurultulu, seed=1)[SR // 10: -SR // 10]) == \
        pytest.approx(-58.0, abs=0.7)


# ======================= join_natural =======================

def test_birlestirme_uzunluk_ve_tip():
    p = [konusma(1.0), konusma(0.5), konusma(0.75)]
    out = join_natural(p, [300, 450, 0], SR)
    assert out.dtype == np.float32 and out.ndim == 1
    assert out.size == sum(x.size for x in p) + int(0.3 * SR) + int(0.45 * SR)
    assert join_natural([], [], SR).size == 0


def test_birlestirme_tek_parca_fadeli():
    p = konusma(0.5)
    out = join_natural([p], [], SR, room_tone=make_room_tone(SR, SR, seed=1))
    assert np.allclose(out, fade(p, SR, 15))


def test_oda_tonu_yoksa_bosluk_tam_sifir():
    p = [konusma(0.5), konusma(0.5)]
    out = join_natural(p, [400], SR)
    assert np.all(out[SR // 2: SR // 2 + int(0.4 * SR)] == 0.0)


def test_bosluk_oda_tonuyla_dolar_parca_ici_degismez():
    p = [konusma(0.5), konusma(0.5)]
    out = join_natural(p, [600], SR, room_tone=make_room_tone(SR, SR, level_db=-50.0, seed=2))
    bosluk = out[SR // 2 + 50: SR // 2 + int(0.6 * SR) - 50]
    assert rms_db(bosluk) == pytest.approx(-58.0, abs=1.5), "oda tonu -58 dBFS'e getirilmeli"
    assert np.array_equal(out[SR // 8: SR // 8 + 2000], p[0][SR // 8: SR // 8 + 2000]), \
        "oda tonu parçanın içine girmemeli"


def test_nefes_boslugu_uzatir_ve_ortaya_konur():
    p = [konusma(0.5), konusma(0.5)]
    nefes = synth_breath(SR, 320, seed=1)
    out = join_natural(p, [100], SR, breath=nefes, breath_plan=[False, True])
    bosluk_n = nefes.size + int(round(0.12 * SR))
    assert out.size == SR + bosluk_n, "boşluk nefes + 120 ms'e uzatılmalı"
    e = out[SR // 2: SR // 2 + bosluk_n].astype(np.float64) ** 2
    merkez = float((e * np.arange(e.size)).sum() / e.sum())
    assert abs(merkez - e.size / 2) < 0.1 * e.size, "nefes boşluğun ortasında olmalı"
    assert join_natural(p, [100], SR).size == SR + int(0.1 * SR)
    assert join_natural(p, [1000], SR, breath=nefes, breath_plan=[False, True]).size == 2 * SR, \
        "yeterli boşluk uzatılmamalı"


def test_nefes_verilmezse_sentezlenir():
    out = join_natural([konusma(0.5), konusma(0.5)], [800], SR, breath_plan=[False, True])
    assert np.max(np.abs(out[SR // 2: SR // 2 + int(0.8 * SR)])) > 1e-4


def test_capraz_geciste_sureksizlik_yok():
    # parçalar sinüsün tepesinde başlayıp bitiyor: kenarlar yumuşatılmasa "tık" olurdu
    t = np.arange(int(0.5 * SR)) / SR
    p = (0.6 * np.cos(2 * np.pi * 1000 * t)).astype(np.float32)
    out = join_natural([p, p.copy(), p.copy()], [300, 250], SR, room_tone=make_room_tone(SR, SR, -45.0, seed=3),
                       breath=synth_breath(SR, seed=2), breath_plan=[False, False, True])
    dogal = float(np.max(np.abs(np.diff(p))))
    assert np.max(np.abs(np.diff(out))) <= dogal * 1.05 + 1e-3
    assert abs(float(out[0])) < 1e-6 and abs(float(out[-1])) < 1e-6


def test_birlestirme_performansi():
    p = [konusma(3.0) for _ in range(20)]                  # 60 sn
    plan = [i % 3 == 0 for i in range(20)]
    taban, nefes = make_room_tone(SR, SR, seed=1), synth_breath(SR, seed=1)
    sureler = []
    for _ in range(3):
        t0 = time.perf_counter()
        out = join_natural(p, [400] * 20, SR, room_tone=taban, breath=nefes, breath_plan=plan)
        sureler.append(time.perf_counter() - t0)
    assert out.size > 60 * SR
    assert min(sureler) < 0.2, f"60 sn birleştirme çok yavaş: {min(sureler):.3f} sn"


# ======================= master =======================

@ffmpeg_gerekir
def test_master_tepe_ve_loudness_hedefi():
    x = konusma(4.0, genlik=0.9)
    y = master(x, SR)
    assert y.dtype == np.float32 and y.size == x.size
    assert np.max(np.abs(y)) <= db_to_amp(-1.5) + 1e-3
    assert measure_loudness(y, SR)["lufs"] == pytest.approx(-16.0, abs=1.5)


@ffmpeg_gerekir
def test_master_sessiz_girdiyi_ozel_hedefe_getirir():
    y = master(konusma(3.0, genlik=0.02), SR, target_lufs=-20.0)
    assert measure_loudness(y, SR)["lufs"] == pytest.approx(-20.0, abs=1.5)


@ffmpeg_gerekir
def test_master_tepe_siniri_durtulerle():
    x = konusma(3.0, genlik=0.05)
    x[::4800] = 0.99                                       # yüksek tepe faktörü: sınırlayıcı devreye girer
    y = master(x, SR)
    assert y.size == x.size
    assert np.max(np.abs(y)) <= db_to_amp(-1.5) + 1e-3


@ffmpeg_gerekir
def test_master_sinirlayici_zinciri_bozuksa_loudnorm_yedegi(monkeypatch):
    # eski ffmpeg'i taklit et: sınırlayıcı filtresi tanınmıyor → tek geçişli loudnorm'a düşülmeli
    monkeypatch.setattr(prosody, "_true_peak_limiter", lambda sr, tp: ["alimiter=olmayan_secenek=1"])
    x = konusma(3.0, genlik=0.05)
    x[::4800] = 0.99                                       # kazanç sonrası tepe aşar → sınırlayıcı gerekir
    y = master(x, SR)
    assert y.size == x.size
    assert np.max(np.abs(y)) <= db_to_amp(-1.5) + 1e-3
    assert rms_db(y) > rms_db(x) + 6, "loudnorm yedeği sesi hedefe doğru yükseltmeli"


def test_master_cok_boyutlu_girdi():
    x = konusma(0.3, genlik=0.05)[:, None]                  # (örnek, 1) biçimi
    y = master(x, SR)
    assert y.ndim == 1 and y.size == x.shape[0]


@ffmpeg_gerekir
def test_master_alcak_frekansi_keser():
    t = np.arange(3 * SR) / SR
    x = (0.3 * np.sin(2 * np.pi * 25 * t) + 0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    y = master(x, SR)

    def genlik(s, f):
        return abs(np.dot(s.astype(np.float64), np.exp(-2j * np.pi * f * t)))

    assert genlik(y, 25) / genlik(y, 1000) < (genlik(x, 25) / genlik(x, 1000)) * db_to_amp(-12)


def test_master_kisa_girdi_yalnizca_highpass_ve_rms():
    x = konusma(0.3, genlik=0.05)
    y = master(x, SR)
    assert y.size == x.size and y.dtype == np.float32
    assert rms_db(y) == pytest.approx(-18.0, abs=1.0)
    assert np.max(np.abs(y)) <= db_to_amp(-1.5) + 1e-3


def test_master_bos_ve_sessiz_girdi():
    assert master(np.zeros(0, dtype=np.float32), SR).size == 0
    assert np.max(np.abs(master(np.zeros(2 * SR, dtype=np.float32), SR))) == 0.0
    tislama = (np.random.default_rng(0).standard_normal(2 * SR) * 1e-5).astype(np.float32)   # ~-100 dBFS
    assert np.max(np.abs(master(tislama, SR))) < 1e-3, "sessizlik/tıslama yükseltilmemeli"


def test_master_ffmpegsiz_yedek(monkeypatch):
    monkeypatch.setattr(prosody, "_ffmpeg_ok", lambda: False)
    x = konusma(2.0, genlik=0.05)
    y = master(x, SR)
    assert y.size == x.size and y.dtype == np.float32
    assert rms_db(y) == pytest.approx(-18.0, abs=1.0)
    assert np.max(np.abs(y)) <= db_to_amp(-1.5) + 1e-3


def test_master_ffmpeg_hatasinda_yedek(monkeypatch):
    def bozuk(*_a, **_k):
        raise RuntimeError("bozuk ffmpeg")

    monkeypatch.setattr(prosody, "_ffmpeg_ok", lambda: True)
    monkeypatch.setattr(prosody, "_ffmpeg_filter", bozuk)
    monkeypatch.setattr(prosody, "_ffmpeg_stderr", bozuk)
    y = master(konusma(2.0, genlik=0.05), SR)
    assert rms_db(y) == pytest.approx(-18.0, abs=1.0)


@ffmpeg_gerekir
def test_master_performansi():
    x = konusma(60.0, genlik=0.3)
    sureler = []
    for _ in range(2):
        t0 = time.perf_counter()
        y = master(x, SR)
        sureler.append(time.perf_counter() - t0)
        if sureler[-1] < 3.0:
            break
    assert y.size == x.size
    assert min(sureler) < 3.0, f"60 sn mastering çok yavaş: {min(sureler):.2f} sn"


# ======================= measure_loudness =======================

def test_olcum_tam_olcekli_sinus():
    m = measure_loudness(sinus(3.0, 1.0), SR)                 # RMS −3.01 dBFS → ≈ −3 LUFS
    assert set(m) == {"lufs", "peak_dbfs", "rms_dbfs"}
    assert m["lufs"] == pytest.approx(-3.0, abs=1.0)
    assert m["peak_dbfs"] == pytest.approx(0.0, abs=0.05)
    assert m["rms_dbfs"] == pytest.approx(-3.01, abs=0.05)


def test_olcum_saf_python_yedegi(monkeypatch):
    monkeypatch.setattr(prosody, "_ffmpeg_ok", lambda: False)
    assert measure_loudness(sinus(3.0, 0.1), SR)["lufs"] == pytest.approx(-23.0, abs=0.3)
    # 48 kHz'de standart K-ağırlıklama: tam ölçek 1 kHz sinüs −3.01 LUFS
    assert prosody._lufs_numpy(sinus(3.0, 1.0, sr=48000), 48000) == pytest.approx(-3.01, abs=0.05)
    # 400 ms'den kısa girdide kapısız ölçüm
    assert measure_loudness(sinus(0.2, 0.5), SR)["lufs"] == pytest.approx(-9.0, abs=1.0)


def test_olcum_sessizlik():
    m = measure_loudness(np.zeros(SR, dtype=np.float32), SR)
    assert m["lufs"] is None
    assert m["peak_dbfs"] <= -100 and m["rms_dbfs"] <= -100
    assert measure_loudness(np.zeros(0, dtype=np.float32), SR)["lufs"] is None


@ffmpeg_gerekir
def test_olcum_ffmpeg_ve_saf_python_uyumlu():
    x = konusma(5.0, genlik=0.3)
    assert measure_loudness(x, SR)["lufs"] == pytest.approx(prosody._lufs_numpy(x, SR), abs=0.5)
