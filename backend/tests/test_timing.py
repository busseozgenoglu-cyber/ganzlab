"""timing — zaman çizelgesi, hece ağırlıklı sözcük zamanları ve SRT / VTT / JSON / LRC altyazı testleri.

Zamanlar örnek ızgarasında toplandığı için beklenen değerler saniyede 3 ondalık, altyazıda tam milisaniyedir.
"""
import json
import random
import re

import numpy as np
import pytest

from app import timing
from app.timing import (
    MIN_BLOCK_MS,
    MIN_GAP_MS,
    build_timeline,
    merge_timelines,
    render,
    shift,
    to_json,
    to_lrc,
    to_srt,
    to_vtt,
    token_weight,
    tokenize,
    total_duration,
)

SR = 24000
ZAMAN_SRT = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})$")
ZAMAN_VTT = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> (\d{2}):(\d{2}):(\d{2})\.(\d{3})$")

UZUN = ("Yapay zekâ destekli ses klonlama teknolojisi, kısa bir referans kaydından yola çıkarak konuşmacının "
        "tınısını, vurgusunu ve konuşma hızını taklit edebiliyor; bu da sesli kitap ve video üretimini hızlandırıyor.")


# ---------- yardımcılar ----------

def parca(text, duration, speaker=None, emotion=None) -> dict:
    return {"text": text, "duration": duration, "emotion": emotion, "speaker": speaker}


def _ms(saat, dakika, saniye, milisaniye) -> int:
    return ((int(saat) * 60 + int(dakika)) * 60 + int(saniye)) * 1000 + int(milisaniye)


def bloklar(metin: str, desen=ZAMAN_SRT) -> list[tuple[int, int, int, list[str]]]:
    """SRT/VTT gövdesini [(no, başlangıç_ms, bitiş_ms, [satırlar])] listesine çevirir (biçimi de denetler)."""
    out = []
    for blok in metin.strip("\n").split("\n\n"):
        satirlar = blok.split("\n")
        m = desen.match(satirlar[1])
        assert m, f"zaman satırı bozuk: {satirlar[1]!r}"
        g = m.groups()
        out.append((int(satirlar[0]), _ms(*g[:4]), _ms(*g[4:]), satirlar[2:]))
    return out


def sure(sozcuk: dict) -> float:
    return sozcuk["end"] - sozcuk["start"]


@pytest.fixture
def uc_parca():
    """Süreler 2.0 / 3.5 / 1.2 sn, duraklamalar 400 / 300 / 0 ms, başta 100 ms."""
    return build_timeline(
        [parca("Merhaba, bugün size yeni projemizi anlatacağım.", 2.0, emotion="samimi"),
         parca("Bu proje Türkçe ses klonlama üzerine kurulu ve oldukça heyecan verici.", 3.5, speaker="Ayşe"),
         parca("Hazır mısınız?", 1.2)],
        [400, 300, 0], SR, lead_in_ms=100)


# ---------- zaman çizelgesi ----------

def test_uc_parcali_cizelge_zamanlari(uc_parca):
    assert [c["start"] for c in uc_parca] == [0.1, 2.5, 6.3]
    assert [c["end"] for c in uc_parca] == [2.1, 6.0, 7.5]
    assert [c["index"] for c in uc_parca] == [0, 1, 2]
    assert set(uc_parca[0]) == {"index", "start", "end", "text", "emotion", "speaker", "words"}
    assert uc_parca[0]["text"] == "Merhaba, bugün size yeni projemizi anlatacağım."
    assert uc_parca[0]["emotion"] == "samimi" and uc_parca[1]["emotion"] is None
    assert uc_parca[1]["speaker"] == "Ayşe" and uc_parca[0]["speaker"] is None   # konuşmacı yoksa None


def test_extra_before_parcadan_once_eklenir():
    tl = build_timeline([parca("Bir.", 2.0), parca("İki.", 3.5), parca("Üç.", 1.2)], [400, 300, 0], SR,
                        lead_in_ms=100, extra_before_ms=[50, 250, 0])
    assert [c["start"] for c in tl] == [0.15, 2.8, 6.6]
    assert [c["end"] for c in tl] == [2.15, 6.3, 7.8]


def test_eksik_negatif_degerler_ve_gecersiz_sr():
    tl = build_timeline([parca("Bir.", 1.0), parca("İki.", 1.0), parca("Üç.", 1.0)], [250], 0)   # eksik → 0
    assert [c["start"] for c in tl] == [0.0, 1.25, 2.25]
    tl = build_timeline([parca("Bir.", -1.0), parca("İki.", None)], [-100], SR, lead_in_ms=-50)
    assert [(c["start"], c["end"]) for c in tl] == [(0.0, 0.0), (0.0, 0.0)]


def test_cizelge_join_natural_ile_ornegi_ornegine_ortusur():
    from app.prosody import join_natural

    uzunluklar, duraklamalar = [12345, 30001, 777], [333, 0, 0]
    ses = join_natural([np.full(n, 0.1, dtype=np.float32) for n in uzunluklar], duraklamalar, SR)
    tl = build_timeline([parca("bir iki", n / SR) for n in uzunluklar], duraklamalar, SR)
    assert tl[-1]["end"] == round(len(ses) / SR, 3)
    assert tl[1]["start"] == round((12345 + round(SR * 0.333)) / SR, 3)


def test_sozcuk_zamanlari_monoton_ve_parca_sinirinda(uc_parca):
    for c in uc_parca:
        w = c["words"]
        assert w[0]["start"] == c["start"] and w[-1]["end"] == c["end"]
        assert all(x["start"] < x["end"] for x in w)
        assert all(a["end"] == b["start"] for a, b in zip(w, w[1:]))     # sözcükler arası boşluk yok
    assert [x["word"] for x in uc_parca[2]["words"]] == ["Hazır", "mısınız?"]
    assert set(uc_parca[0]["words"][0]) == {"word", "start", "end"}


def test_hece_agirligi_ve_noktalama_payi():
    w = build_timeline([parca("merhaba ve", 2.0)], [], SR)[0]["words"]
    assert [(x["word"], x["start"], x["end"]) for x in w] == [("merhaba", 0.0, 1.5), ("ve", 1.5, 2.0)]
    assert sure(w[0]) / sure(w[1]) == pytest.approx(3.0)                 # 3 hece : 1 hece
    w = build_timeline([parca("merhaba, ve", 2.0)], [], SR)[0]["words"]
    assert sure(w[0]) / sure(w[1]) == pytest.approx(3.5, abs=0.02)       # virgül payı sözcüğün sonunda
    w = build_timeline([parca("Merhaba, ve.", 2.0)], [], SR)[0]["words"]
    assert [(x["start"], x["end"]) for x in w] == [(0.0, 1.4), (1.4, 2.0)]   # 3.5 : 1.5


def test_sozcuk_agirliklari():
    assert token_weight("merhaba") == 3
    assert token_weight("ve") == 1
    assert token_weight("önemli,") == 3.5
    assert token_weight("bitti.") == 2.5
    assert token_weight('"Tamam."') == 2.5        # kapanış tırnağı atlanır
    assert token_weight("hmm") == 1               # ünlüsüz sözcük 1 hece sayılır
    assert token_weight("hâlâ") == 2              # şapkalı ünlüler de hece
    assert token_weight("2024'te") == 7           # iki bin yirmi dört + te


def test_noktalama_sozcuge_yapisik_kalir():
    assert tokenize("Bu çok önemli, dikkat edin!") == ["Bu", "çok", "önemli,", "dikkat", "edin!"]
    assert tokenize("Peki — ne olacak ?") == ["Peki —", "ne", "olacak ?"]
    assert tokenize("— Evet, tamam.") == ["— Evet,", "tamam."]
    assert tokenize("[gülerek] Çok komik!") == ["Çok", "komik!"]


def test_bos_metin_sozcuksuz():
    tl = build_timeline([parca("", 1.0), parca("   ", 0.5), parca("[nefes]", 0.3)], [100, 100], SR)
    assert [c["words"] for c in tl] == [[], [], []]
    assert to_srt(tl) == ""


def test_toplam_sure(uc_parca):
    assert total_duration(uc_parca) == 7.5


# ---------- SRT ----------

def test_srt_numaralama_ve_zaman_bicimi(uc_parca):
    srt = to_srt(uc_parca)
    b = bloklar(srt)
    assert [x[0] for x in b] == [1, 2, 3]
    assert srt.startswith("1\n00:00:00,100 --> 00:00:02,100\n")
    assert b[0][3] == ["Merhaba, bugün size yeni", "projemizi anlatacağım."]
    assert [(x[1], x[2]) for x in b[1:]] == [(2500, 6000), (6300, 7500)]
    assert srt.endswith("Hazır mısınız?\n\n")      # dosya sonunda boş satır
    assert "\r" not in srt                          # CRLF değil LF


def test_srt_saat_ve_dakika_tasmasi():
    tl = shift(build_timeline([parca("Uzun bir kaydın sonu.", 1.25)], [], SR), 3725.5)
    assert to_srt(tl).splitlines()[1] == "01:02:05,500 --> 01:02:06,750"


def test_srt_turkce_karakterler_aynen():
    metin = "Işık, ğüşöç ve İstanbul'da ÇĞÖŞÜ."
    assert metin in to_srt(build_timeline([parca(metin, 3.0)], [], SR))


def test_uzun_cumle_bloklara_ve_satirlara_bolunur():
    b = bloklar(to_srt(build_timeline([parca(UZUN, 14.0)], [], SR)))
    assert len(b) == 3
    assert all(len(satir) <= 42 for x in b for satir in x[3])
    assert all(len(x[3]) <= 2 for x in b)
    assert " ".join(s for x in b for s in x[3]) == UZUN      # sözcük kaybı ya da tekrarı yok
    assert b[0][1] == 0 and b[-1][2] == 14000                 # blok süreleri sözcük zamanlarından
    assert b[0][3] == ["Yapay zekâ destekli ses klonlama", "teknolojisi, kısa bir referans"]


def test_satir_dengesi_piramit_degil():
    b = bloklar(to_srt(build_timeline([parca("Yarın sabah erkenden yola çıkıp arkadaşlarımızla buluşacağız.", 3.0)],
                                      [], SR)))
    assert b[0][3] == ["Yarın sabah erkenden yola çıkıp", "arkadaşlarımızla buluşacağız."]   # 31 / 29
    b = bloklar(to_srt(build_timeline([parca("Bu akşam sinemaya gitmeyi düşünüyoruz, sen de gelir misin?", 3.0)],
                                      [], SR)))
    ust, alt = b[0][3]
    assert len(ust) >= len(alt)                      # üst satır alttan kısa değil
    assert (ust, alt) == ("Bu akşam sinemaya gitmeyi düşünüyoruz,", "sen de gelir misin?")
    b = bloklar(to_srt(build_timeline([parca("Kısa bir cümle.", 1.0)], [], SR)))
    assert b[0][3] == ["Kısa bir cümle."]            # sığan metin tek satır


def test_bloklar_arasi_en_az_80_ms():
    tl = build_timeline([parca("Birinci cümle burada bitiyor.", 2.0), parca("İkinci cümle hemen başlıyor.", 2.0)],
                        [0], SR)
    b = bloklar(to_srt(tl))
    assert (b[0][2], b[1][1]) == (2000 - MIN_GAP_MS, 2000)    # önceki bloğun sonu kırpıldı
    b = bloklar(to_srt(build_timeline([parca(UZUN, 14.0)], [], SR)))
    assert all(y[1] - x[2] >= MIN_GAP_MS for x, y in zip(b, b[1:]))


def test_kisa_parca_sonrakiyle_ayni_bloga_girer():
    tl = build_timeline([parca("Evet.", 0.4), parca("Bugün hava çok güzel.", 2.0), parca("Yürüyüşe çıkalım mı?", 1.8)],
                        [200, 500], SR)
    b = bloklar(to_srt(tl))
    assert [x[3] for x in b] == [["Evet. Bugün hava çok güzel."], ["Yürüyüşe çıkalım mı?"]]
    assert [(x[1], x[2]) for x in b] == [(0, 2600), (3100, 4900)]
    assert all(x[2] - x[1] >= MIN_BLOCK_MS for x in b)


def test_birlesme_sure_sinirini_asmaz():
    tl = build_timeline([parca("Evet.", 0.4), parca("Bu cümle tam altı buçuk saniye sürüyor.", 6.7)], [100], SR)
    b = bloklar(to_srt(tl))
    assert len(b) == 2                               # 7.2 sn'lik tek blok yerine
    assert all(MIN_BLOCK_MS <= x[2] - x[1] <= 7000 for x in b)
    assert b[0][3][0].startswith("Evet.")
    assert " ".join(s for x in b for s in x[3]) == "Evet. Bu cümle tam altı buçuk saniye sürüyor."


def test_birlestirilemeyen_kisa_blok_uzatilir():
    tl = build_timeline([parca("Evet.", 0.4), parca("Tamam, başlayalım.", 1.5), parca("Peki.", 0.3)], [1000, 400], SR)
    b = bloklar(to_srt(tl))                          # uzun duraklama: birleştirmek yerine 700 ms'ye uzatılır
    assert [(x[1], x[2]) for x in b] == [(0, 700), (1400, 2900), (3300, 4000)]


def test_yedi_saniyeyi_asan_blok_bolunur():
    tl = build_timeline([parca("Bu cümle yavaş okunuyor ve uzun sürüyor.", 10.0)], [], SR)
    b = bloklar(to_srt(tl))
    assert [x[3] for x in b] == [["Bu cümle yavaş okunuyor"], ["ve uzun sürüyor."]]
    assert all(x[2] - x[1] <= 7000 for x in b)
    assert b[0][1] == 0 and b[1][2] == 10000
    b = bloklar(to_srt(tl, max_duration_s=3.0))
    assert len(b) >= 4 and all(x[2] - x[1] <= 3000 for x in b)


def test_diyalogda_kisa_sozler_tireli_tek_blok():
    tl = build_timeline([parca("Naber?", 0.5, "Ayşe"), parca("İyiyim.", 0.6, "Mehmet"),
                         parca("Harika, hadi gidelim.", 1.5, "Ayşe")], [200, 300], SR)
    b = bloklar(to_srt(tl))
    assert b[0][3] == ["- Naber?", "- İyiyim."]
    assert (b[0][1], b[0][2]) == (0, 1300)
    assert b[1][3] == ["Harika, hadi gidelim."]


def test_sozcuk_zamani_olmayan_cizelge_de_calisir():
    tl = [{"index": 0, "start": 1.0, "end": 3.0, "text": "Sözcük zamanı olmayan çizelge de çalışır.",
           "emotion": None, "speaker": None}]
    b = bloklar(to_srt(tl))
    assert [(x[1], x[2], x[3]) for x in b] == [(1000, 3000, ["Sözcük zamanı olmayan çizelge de çalışır."])]


def test_buyuk_cizelgede_degismezler():
    rnd = random.Random(11)
    sozler = ("ve bir bu çok daha güzel ses klonlama yapay zekâ teknolojisi konuşmacının tınısını, sesli kitap "
              "üretimini hızlandırıyor. bugün yarın İstanbul'da arkadaşlarımızla evet! peki,").split()
    chunks = [parca(" ".join(rnd.choice(sozler) for _ in range(n)), n * 0.45, rnd.choice([None, "Ayşe", "Mehmet"]))
              for n in (rnd.randint(1, 25) for _ in range(120))]
    tl = build_timeline(chunks, [rnd.choice([0, 200, 450, 900]) for _ in chunks], SR)
    b = bloklar(to_srt(tl))
    assert [x[0] for x in b] == list(range(1, len(b) + 1))
    assert all(len(s) <= 42 for x in b for s in x[3]) and all(1 <= len(x[3]) <= 2 for x in b)
    assert all(MIN_BLOCK_MS <= x[2] - x[1] <= 7000 for x in b)
    assert all(y[1] - x[2] >= MIN_GAP_MS for x, y in zip(b, b[1:]))
    tireli = lambda x: len(x[3]) > 1 and all(s.startswith("- ") for s in x[3])      # noqa: E731
    yazilan = " ".join(s[2:] if tireli(x) else s for x in b for s in x[3])
    assert yazilan == " ".join(c["text"] for c in tl)


# ---------- VTT / JSON / LRC ----------

def test_vtt_baslik_nokta_ve_ayni_bloklar(uc_parca):
    vtt = to_vtt(uc_parca)
    assert vtt.startswith("WEBVTT\n\n1\n00:00:00.100 --> 00:00:02.100\n")
    b = bloklar(vtt[len("WEBVTT\n\n"):], ZAMAN_VTT)
    assert [x[1:] for x in b] == [x[1:] for x in bloklar(to_srt(uc_parca))]
    assert all(len(s) <= 20 for x in bloklar(to_vtt(uc_parca, max_chars=20)[8:], ZAMAN_VTT) for s in x[3])


def test_vtt_ozel_karakterleri_kacislar():
    tl = build_timeline([parca("Ali & Veli <3", 1.5)], [], SR)
    assert "Ali &amp; Veli &lt;3" in to_vtt(tl)
    assert "Ali & Veli <3" in to_srt(tl)


def test_json_turkce_karakterler_kacissiz(uc_parca):
    js = to_json(uc_parca)
    assert "Türkçe" in js and "mısınız" in js and "\\u" not in js
    assert js.startswith("[\n  {")                   # 2 boşluk girinti
    assert json.loads(js) == uc_parca


def test_lrc_satir_zamanli(uc_parca):
    lrc = to_lrc(uc_parca)
    assert lrc.splitlines() == [
        "[00:00.10]Merhaba, bugün size yeni projemizi anlatacağım.",
        "[00:02.50]Bu proje Türkçe ses klonlama üzerine kurulu ve oldukça heyecan verici.",
        "[00:06.30]Hazır mısınız?",
        "[00:07.50]",                                # ekranı temizleyen son damga
    ]
    assert lrc.endswith("\n")
    assert to_lrc(shift(uc_parca, 125.0)).startswith("[02:05.10]")


def test_bos_cizelge():
    assert build_timeline([], [], SR) == []
    assert to_srt([]) == ""
    assert to_vtt([]) == "WEBVTT\n\n"
    assert to_lrc([]) == ""
    assert to_json([]) == "[]"
    assert total_duration([]) == 0.0
    assert merge_timelines([], []) == []


def test_render_bicim_secimi(uc_parca):
    assert render(uc_parca, "srt") == to_srt(uc_parca)
    assert render(uc_parca, "VTT") == to_vtt(uc_parca)
    assert render(uc_parca, "json") == to_json(uc_parca)
    assert render(uc_parca, ".lrc") == to_lrc(uc_parca)
    assert set(timing.SUBTITLE_FORMATS) == {"srt", "vtt", "json", "lrc"}
    with pytest.raises(ValueError):
        render(uc_parca, "ass")


# ---------- kaydırma ve birleştirme ----------

def test_shift_kaydirir_girdiyi_degistirmez(uc_parca):
    kaymis = shift(uc_parca, 1.5)
    assert [c["start"] for c in kaymis] == [1.6, 4.0, 7.8]
    assert kaymis[0]["words"][0]["start"] == 1.6 and kaymis[2]["words"][-1]["end"] == 9.0
    assert uc_parca[0]["start"] == 0.1 and uc_parca[0]["words"][0]["start"] == 0.1
    geri = shift(uc_parca, -1.0)
    assert (geri[0]["start"], geri[0]["end"], geri[1]["start"]) == (0.0, 1.1, 1.5)   # 0'ın altı 0


def test_merge_timelines_diyalog_sira_sira():
    a = build_timeline([parca("Selam, naber?", 1.2, "Ayşe"), parca("Uzun zaman oldu.", 1.0, "Ayşe")], [300], SR)
    b = build_timeline([parca("İyiyim, sen nasılsın?", 1.6, "Mehmet")], [], SR, lead_in_ms=50)
    m = merge_timelines([a, b], [0.4])
    assert [c["index"] for c in m] == [0, 1, 2]
    assert [c["speaker"] for c in m] == ["Ayşe", "Ayşe", "Mehmet"]
    assert (m[2]["start"], m[2]["end"]) == (2.95, 4.55)      # a: 2.5 sn + 0.4 boşluk + b'nin 50 ms girişi
    assert m[2]["words"][0]["start"] == 2.95 and m[2]["words"][-1]["end"] == 4.55
    assert total_duration(m) == 4.55
    assert b[0]["start"] == 0.05 and b[0]["index"] == 0      # girdiler değişmedi
    assert merge_timelines([a, b], [])[2]["start"] == 2.55   # eksik boşluk → 0
