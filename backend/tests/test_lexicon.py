"""lexicon.py testleri: telaffuz sözlüğü (CRUD, kalıcılık, eşzamanlılık, eşleşme kuralları), satır içi okunuş,
sohbet kısaltmaları ve konuşma dolguları.

Her test kendi geçici genel sözlüğü ve ses klasörüyle çalışır (gerçek data/lexicon.json'a dokunulmaz).
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from itertools import pairwise

import pytest

from app import config, lexicon
from app.lexicon import (
    CHAT_ABBREV,
    FILLER_MIN_GAP,
    FILLERS_COMMA,
    FILLERS_END,
    FILLERS_START,
    NO_FILLER_STYLES,
    add_fillers,
    apply_inline_readings,
    apply_lexicon,
    delete_entry,
    expand_chat_speak,
    lexicon_report,
    list_entries,
    set_entry,
    voice_lexicon_path,
)
from app.textnorm import normalize
from app.tr import tr_lower

SES = "ses01"
SES2 = "ses02"


@pytest.fixture(autouse=True)
def yalitilmis(tmp_path, monkeypatch):
    genel = tmp_path / "lexicon.json"
    sesler = tmp_path / "voices"
    sesler.mkdir()
    monkeypatch.setattr(lexicon, "LEXICON_PATH", genel)
    monkeypatch.setattr(config, "VOICES_DIR", sesler)
    return genel


def _dosya(yol):
    return json.loads(yol.read_text(encoding="utf-8"))


def _disaridan_yaz(yol, veri):
    """Başka bir sürecin/düzenleyicinin yazması gibi: geçici dosya + yeniden adlandırma."""
    gecici = yol.with_name(yol.name + ".dis")
    gecici.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    os.replace(gecici, yol)


# =============================================================================================================
# 1. CRUD ve kalıcılık
# =============================================================================================================

def test_bos_sozluk(yalitilmis):
    assert list_entries() == []
    assert list_entries(SES) == []
    assert apply_lexicon("Claude geldi.") == "Claude geldi."
    assert lexicon_report("Claude geldi.") == []
    assert not yalitilmis.exists()


def test_ekle_dosyaya_yazar_ve_listeler(yalitilmis):
    girdi = set_entry("Claude", "Klod")
    assert girdi == {"word": "Claude", "reading": "Klod", "scope": "global"}
    assert yalitilmis.exists()
    assert _dosya(yalitilmis) == {"Claude": "Klod"}
    assert list_entries() == [{"word": "Claude", "reading": "Klod", "scope": "global"}]


def test_ayni_sozcuk_buyuk_kucuk_harf_turevi_tek_girdi(yalitilmis):
    set_entry("Claude", "Klod")
    set_entry("CLAUDE", "Kılod")
    girdiler = list_entries()
    assert len(girdiler) == 1
    assert girdiler[0] == {"word": "CLAUDE", "reading": "Kılod", "scope": "global"}
    assert _dosya(yalitilmis) == {"CLAUDE": "Kılod"}


def test_sil(yalitilmis):
    set_entry("Claude", "Klod")
    set_entry("Red Bull", "Red Bul")
    assert delete_entry("claude") is True               # büyük/küçük harf duyarsız
    assert delete_entry("Claude") is False              # artık yok
    assert [g["word"] for g in list_entries()] == ["Red Bull"]
    assert delete_entry("red   bull") is True           # boşluk farkı önemsiz
    assert list_entries() == []
    assert not yalitilmis.exists()                      # boşalan sözlüğün dosyası silinir
    assert delete_entry("") is False


def test_kalicilik_ve_dis_degisiklik(yalitilmis):
    set_entry("Claude", "Klod")
    assert apply_lexicon("Claude") == "Klod"
    _disaridan_yaz(yalitilmis, {"Claude": "Kılod", "Michael": "Maykıl"})
    assert apply_lexicon("Claude ve Michael") == "Kılod ve Maykıl"    # önbellek dosya değişince yenilenir
    assert {g["word"] for g in list_entries()} == {"Claude", "Michael"}
    yalitilmis.unlink()
    assert list_entries() == []
    assert apply_lexicon("Claude") == "Claude"


def test_bozuk_dosya_bos_sayilir_ve_yedeklenir(yalitilmis):
    yalitilmis.write_text("{bozuk json", encoding="utf-8")
    assert list_entries() == []
    assert apply_lexicon("Claude") == "Claude"
    set_entry("Claude", "Klod")
    yedek = yalitilmis.with_name("lexicon.json.bozuk")
    assert yedek.read_text(encoding="utf-8") == "{bozuk json"
    assert _dosya(yalitilmis) == {"Claude": "Klod"}


def test_dosyadaki_gecersiz_girdiler_atlanir(yalitilmis):
    _disaridan_yaz(yalitilmis, {"Claude": "Klod", "": "boş", "Sayı": 5, "Etiket[": "x"})
    assert list_entries() == [{"word": "Claude", "reading": "Klod", "scope": "global"}]


@pytest.mark.parametrize("sozcuk, okunus", [
    ("", "Klod"), ("   ", "Klod"), ("Claude", ""), ("Cla[ude", "Klod"), ("Claude", "{Klod}"), ("Claude", "Kl|od"),
    ("x" * (lexicon.MAX_WORD_CHARS + 1), "Klod"), ("Claude", "y" * (lexicon.MAX_READING_CHARS + 1)),
    ("...", "nokta"), (None, "Klod"),
])
def test_gecersiz_girdi_reddedilir(sozcuk, okunus):
    with pytest.raises(ValueError):
        set_entry(sozcuk, okunus)


@pytest.mark.parametrize("kimlik", ["../kacis", "a/b", "", " ", "x" * 70, "ses 1"])
def test_gecersiz_ses_kimligi(kimlik):
    with pytest.raises(ValueError):
        voice_lexicon_path(kimlik)
    if kimlik.strip():                                   # boş kimlik genel sözlük demektir
        with pytest.raises(ValueError):
            set_entry("Claude", "Klod", voice_id=kimlik)


def test_ses_sozlugu_yolu():
    assert voice_lexicon_path(SES) == config.VOICES_DIR / f"{SES}.lexicon.json"


def test_turk_alfabesi_sirasi():
    for sozcuk in ["zeytin", "çay", "ılık", "cam", "iğne", "Ankara", "Şule", "su", "Windows", "kâr", "kar", ".NET"]:
        set_entry(sozcuk, sozcuk + " okunuşu")
    assert [g["word"] for g in list_entries()] == [
        ".NET", "Ankara", "cam", "çay", "ılık", "iğne", "kar", "kâr", "su", "Şule", "Windows", "zeytin",
    ]


def test_atomik_yazma_hatada_eski_dosya_saglam(yalitilmis, monkeypatch):
    set_entry("Claude", "Klod")

    def patla(*a, **k):
        raise OSError("disk dolu")

    monkeypatch.setattr(lexicon.os, "replace", patla)
    with pytest.raises(OSError):
        set_entry("Michael", "Maykıl")
    monkeypatch.undo()
    assert _dosya(yalitilmis) == {"Claude": "Klod"}
    assert [p.name for p in yalitilmis.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_eszamanli_okuma_ve_yazma(yalitilmis):
    hatalar: list[BaseException] = []
    bitti = threading.Event()

    def yazar(bas: int):
        try:
            for i in range(bas, bas + 25):
                set_entry(f"sözcük{i}", f"okunuş {i}")
        except BaseException as e:  # noqa: BLE001
            hatalar.append(e)

    def okur():
        try:
            while not bitti.wait(0.001):             # kısa bekleme: yazarları GIL için aç bırakma
                list_entries()
                apply_lexicon("sözcük1 ve sözcük2 ve sözcük99")
        except BaseException as e:  # noqa: BLE001
            hatalar.append(e)

    okurlar = [threading.Thread(target=okur) for _ in range(3)]
    yazarlar = [threading.Thread(target=yazar, args=(i * 25,)) for i in range(4)]
    for t in okurlar + yazarlar:
        t.start()
    for t in yazarlar:
        t.join()
    bitti.set()
    for t in okurlar:
        t.join()
    assert hatalar == []
    assert len(list_entries()) == 100                    # kayıp güncelleme yok
    assert len(_dosya(yalitilmis)) == 100                # dosya geçerli JSON
    assert apply_lexicon("sözcük7") == "okunuş 7"


# =============================================================================================================
# 2. Ses sözlüğü
# =============================================================================================================

def test_ses_sozlugu_geneli_ezer():
    set_entry("Claude", "Klod")
    set_entry("Michael", "Maykıl")
    assert set_entry("claude", "Kılod", voice_id=SES)["scope"] == "voice"
    assert voice_lexicon_path(SES).exists()
    assert apply_lexicon("Claude ve Michael", voice_id=SES) == "Kılod ve Maykıl"
    assert apply_lexicon("Claude ve Michael") == "Klod ve Maykıl"
    assert list_entries(SES) == [
        {"word": "claude", "reading": "Kılod", "scope": "voice"},
        {"word": "Michael", "reading": "Maykıl", "scope": "global"},
    ]
    assert delete_entry("Claude", voice_id=SES) is True
    assert not voice_lexicon_path(SES).exists()
    assert apply_lexicon("Claude", voice_id=SES) == "Klod"   # genel sözlük yeniden geçerli


def test_baska_sesin_sozlugu_karismaz():
    set_entry("Ece", "Ece'cik", voice_id=SES)
    assert apply_lexicon("Ece geldi", voice_id=SES) == "Ece'cik geldi"
    assert apply_lexicon("Ece geldi", voice_id=SES2) == "Ece geldi"
    assert apply_lexicon("Ece geldi") == "Ece geldi"
    assert list_entries(SES2) == []


def test_gecersiz_ses_kimligiyle_uygulama_genel_sozlukle_surer():
    set_entry("Claude", "Klod")
    assert apply_lexicon("Claude", voice_id="../x") == "Klod"


# =============================================================================================================
# 3. Eşleşme kuralları
# =============================================================================================================

def test_bas_harf_buyuklugu_korunur():
    set_entry("Claude", "Klod")
    assert apply_lexicon("claude dedi") == "klod dedi"
    assert apply_lexicon("Claude dedi") == "Klod dedi"
    assert apply_lexicon("CLAUDE DEDİ") == "Klod DEDİ"


def test_turkce_i_harfleri():
    set_entry("ılık", "ılıcık")
    assert apply_lexicon("ılık su") == "ılıcık su"
    assert apply_lexicon("ILIK SU") == "Ilıcık SU"      # büyük I Türkçede ı'dır
    assert apply_lexicon("ilik suyu") == "ilik suyu"    # küçük i ile ı ayrı harflerdir
    set_entry("Ikea", "Ayki")
    assert apply_lexicon("IKEA mağazası") == "Ayki mağazası"   # büyük ASCII I yabancı sözcükte i olabilir
    assert apply_lexicon("ikea'dan aldım") == "ayki'dan aldım"


def test_sapkali_harf_ayri_sayilir():
    set_entry("kâr", "kâaar")
    assert apply_lexicon("kâr ettik") == "kâaar ettik"
    assert apply_lexicon("kar yağdı") == "kar yağdı"


def test_sozcuk_siniri():
    set_entry("Claude", "Klod")
    assert apply_lexicon("Claudette geldi") == "Claudette geldi"
    assert apply_lexicon("Claudes") == "Claudes"
    assert apply_lexicon("Claude2") == "Claude2"
    assert apply_lexicon("@Claude, *Claude*") == "@Klod, *Klod*"
    set_entry("in", "iiin")
    assert apply_lexicon("Ahmet'in kitabı") == "Ahmet'in kitabı"   # kesme ekinin içi sözcük değildir


def test_cok_sozcuklu_ve_en_uzun_anahtar_once():
    set_entry("Red", "Rıd")
    set_entry("Red Bull", "Red Bul")
    assert apply_lexicon("Red Bull içtim") == "Red Bul içtim"
    assert apply_lexicon("Red   Bull içtim") == "Red Bul içtim"
    assert apply_lexicon("red bull içtim") == "red Bul içtim"
    assert apply_lexicon("Red Hot Chili") == "Rıd Hot Chili"
    assert apply_lexicon("Red Bulls") == "Rıd Bulls"


def test_kesmeli_ek_korunur():
    set_entry("Claude", "Klod")
    set_entry("Red Bull", "Red Bul")
    assert apply_lexicon("Claude'un cevabı") == "Klod'un cevabı"
    assert apply_lexicon("Claude’a sordum") == "Klod’a sordum"
    assert apply_lexicon("Red Bull'u içtim") == "Red Bul'u içtim"


def test_etiket_url_eposta_ve_okunusa_dokunulmaz():
    set_entry("Claude", "Klod")
    assert apply_lexicon("[ses:Claude] Claude geldi") == "[ses:Claude] Klod geldi"
    assert apply_lexicon("[vurgu: Claude] dedi") == "[vurgu: Klod] dedi"
    assert apply_lexicon("[Claude]") == "[Claude]"
    assert apply_lexicon("claude.ai ve https://claude.com/x") == "claude.ai ve https://claude.com/x"
    assert apply_lexicon("claude@firma.com yaz") == "claude@firma.com yaz"
    assert apply_lexicon("{Claude|Klot}") == "{Claude|Klot}"


def test_textnorm_varsayilan_okunusundan_once_ve_baskin():
    set_entry("Netflix", "Netfiliks")
    sonuc = normalize(apply_lexicon("Netflix'te izledim."), "tr")
    assert "Netfiliks" in sonuc and "Netfliks" not in sonuc


def test_turkce_disi_dilde_uygulanmaz():
    set_entry("Claude", "Klod")
    assert apply_lexicon("Claude", "en") == "Claude"
    assert apply_lexicon("Claude", "tr-TR") == "Klod"
    assert lexicon_report("Claude", None, "en") == []


def test_lexicon_report():
    set_entry("Claude", "Klod")
    set_entry("Red Bull", "Red Bul")
    assert lexicon_report("Claude'un Red Bull'u", None) == [
        {"from": "Claude'un", "to": "Klod'un"},
        {"from": "Red Bull'u", "to": "Red Bul'u"},
    ]
    rapor = lexicon_report("claude ve Claude", None)
    assert rapor == [{"from": "claude", "to": "klod"}, {"from": "Claude", "to": "Klod"}]
    assert all(set(r) == {"from", "to"} for r in rapor)
    assert lexicon_report("hiçbir eşleşme yok", None) == []
    set_entry("Claude", "Kılod", voice_id=SES)
    assert lexicon_report("Claude", SES) == [{"from": "Claude", "to": "Kılod"}]


# =============================================================================================================
# 4. Satır içi okunuş
# =============================================================================================================

@pytest.mark.parametrize("girdi, beklenen", [
    ("{Claude|Klod} geldi.", "Klod geldi."),
    ("{Klod} geldi.", "Klod geldi."),
    ("{ Claude | Klod }", "Klod"),
    ("{Claude|}", "Claude"),
    ("{}", ""),
    ("{GIF|cif} mi {GIF|gif} mi?", "cif mi gif mi?"),
    ("[gülerek] {Hello|Helo} dedi.", "[gülerek] Helo dedi."),
    ("[ses:{Ali|Veli}] merhaba", "[ses:{Ali|Veli}] merhaba"),
    ("Kapanmamış {parantez", "Kapanmamış {parantez"),
    ("Parantezsiz metin", "Parantezsiz metin"),
])
def test_satir_ici_okunus(girdi, beklenen):
    assert apply_inline_readings(girdi) == beklenen


# =============================================================================================================
# 5. Sohbet kısaltmaları
# =============================================================================================================

SOZLESME_KISALTMALARI = {
    "tmm": "tamam", "nbr": "naber", "slm": "selam", "mrb": "merhaba", "tşk": "teşekkürler",
    "tşkr": "teşekkürler", "tsk": "teşekkürler", "kib": "kendine iyi bak", "bb": "bay bay", "msj": "mesaj",
    "tlf": "telefon", "grs": "görüşürüz", "iyi gcl": "iyi geceler", "nsl": "nasıl", "nslsn": "nasılsın",
    "bgn": "bugün", "yrn": "yarın", "şmd": "şimdi", "hyr": "hayır", "evt": "evet", "ok": "okey", "cnm": "canım",
    "knk": "kanka", "abi": "abi", "abe": "abi", "inş": "inşallah", "mşl": "maşallah", "aeo": "allaha emanet ol",
    "sa": "selamün aleyküm", "as": "aleyküm selam",
}


def test_sozlesmedeki_kisaltmalar_ve_ekler():
    for k, v in SOZLESME_KISALTMALARI.items():
        assert CHAT_ABBREV.get(k) == v, k
    assert len(set(CHAT_ABBREV) - set(SOZLESME_KISALTMALARI)) >= 20


@pytest.mark.parametrize("girdi, beklenen", [
    ("tmm", "tamam"),
    ("slm nbr", "selam naber"),
    ("kib knk", "kendine iyi bak kanka"),
    ("bb", "bay bay"),
    ("iyi gcl", "iyi geceler"),
    ("tmm yrn grs", "tamam yarın görüşürüz"),
    ("aeo", "allaha emanet ol"),
    ("abe napıyon", "abi napıyon"),
    ("msj atarım, tşk ederim", "mesaj atarım, teşekkür ederim"),   # en uzun kalıp önce
    ("msj'ı aldın mı", "mesajı aldın mı"),                          # kesmeli ek bitişir
    ("tlf'u aç", "telefonu aç"),
])
def test_sohbet_kisaltmalari(girdi, beklenen):
    assert expand_chat_speak(girdi) == beklenen


@pytest.mark.parametrize("girdi, beklenen", [
    ("Tmm", "Tamam"),
    ("Tmm.", "Tamam."),
    ("TMM ABİ", "TAMAM ABİ"),
    ("KİB", "KENDİNE İYİ BAK"),
    ("Kib canım", "Kendine iyi bak canım"),
])
def test_sohbet_buyuk_harf_korunur(girdi, beklenen):
    assert expand_chat_speak(girdi) == beklenen


@pytest.mark.parametrize("girdi, beklenen", [
    ("sa", "selamün aleyküm"),
    ("Sa.", "Selamün aleyküm."),
    ("sa nasılsın", "selamün aleyküm nasılsın"),                    # satır başı + boşluk
    ("sa, nasılsın?", "selamün aleyküm, nasılsın?"),                # satır başı + noktalama
    ("Merhaba. Sa!", "Merhaba. Selamün aleyküm!"),                  # tek sözcüklük cümle
    ("Ali: sa\nVeli: as kardeşim", "Ali: selamün aleyküm\nVeli: aleyküm selam kardeşim"),
    ("as", "aleyküm selam"),
    ("as, iyiyim", "aleyküm selam, iyiyim"),
    ("Ali sa dedi.", "Ali sa dedi."),                               # cümle ortası
    ("Selam dedim, o da as dedi.", "Selam dedim, o da as dedi."),
    ("Kasa açık, masa hazır.", "Kasa açık, masa hazır."),           # sözcük içi
    ("As oyuncu sakatlandı.", "As oyuncu sakatlandı."),             # as = as oyuncu
    ("As bayrakları!", "As bayrakları!"),                            # as = asmak
    ("sa'ya git", "sa'ya git"),
])
def test_sohbet_sa_as_baglami(girdi, beklenen):
    assert expand_chat_speak(girdi) == beklenen


@pytest.mark.parametrize("girdi, beklenen", [
    ("ok", "okey"),
    ("Ok.", "Okey."),
    ("Tamam, ok.", "Tamam, okey."),
    ("ok, gelirim", "okey, gelirim"),
    ("OK!", "OKEY!"),
    ("ok ve yay aldım.", "ok ve yay aldım."),
    ("Oku hedefe attı.", "Oku hedefe attı."),
    ("Tamam ok gidelim", "Tamam ok gidelim"),
])
def test_sohbet_ok_yalniz_tek_basina(girdi, beklenen):
    assert expand_chat_speak(girdi) == beklenen


@pytest.mark.parametrize("girdi", [
    "TSK açıklama yaptı.",            # kurum kısaltması
    "Shinzo Abe Tokyo'da.",           # cümle ortasında büyük harfli özel ad
    "Adres site.com/tmm sayfası.",    # URL
    "[ses:knk] Merhaba.",             # konuşmacı etiketi
    "{tmm|tamam}",                    # satır içi okunuş
])
def test_sohbet_dokunulmayan_yerler(girdi):
    assert expand_chat_speak(girdi) == girdi


def test_sohbet_kapsamli_etiket_metni_islenir_ve_idempotent():
    assert expand_chat_speak("[vurgu: tmm] knk") == "[vurgu: tamam] kanka"
    metin = "sa knk, nbr? Tmm, yrn grs. ok"
    bir = expand_chat_speak(metin)
    assert bir == "selamün aleyküm kanka, naber? Tamam, yarın görüşürüz. okey"
    assert expand_chat_speak(bir) == bir


# =============================================================================================================
# 6. Konuşma dolguları
# =============================================================================================================

TABAN = "Bugün eve döndüm, biraz dinlendim."


def _varyantlar(cumle: str, ilk_kucuk: str) -> set[str]:
    """Tek dolgulu tüm geçerli biçimler (cümlede tek virgül ve '.' sonu varsayılır)."""
    on, _, arka = cumle.partition(",")
    out = {f + ilk_kucuk for f in FILLERS_START}
    out |= {f"{on},{f}{arka}" for f in FILLERS_COMMA}
    out |= {cumle[:-1] + f + "." for f in FILLERS_END}
    return out


TABAN_VARYANT = _varyantlar(TABAN, "bugün eve döndüm, biraz dinlendim.")


def _cumleler(metin: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", metin.strip())


def _dolgulu_siralar(metin: str) -> list[int]:
    return [i for i, c in enumerate(_cumleler(metin)) if c != TABAN]


def _dolgu_sozcugu(cumle: str) -> str:
    for f in FILLERS_START:
        if cumle.startswith(f):
            return tr_lower(f.strip(" ,"))
    for f in FILLERS_COMMA:
        if "," + f + " " in cumle:
            return f.strip()
    for f in FILLERS_END:
        if cumle.endswith(f + "."):
            return f.strip()
    raise AssertionError(f"dolgu bulunamadı: {cumle!r}")


@pytest.mark.parametrize("stil", sorted(NO_FILLER_STYLES) + ["Sesli Kitap", "audiobook", "news", "egitim"])
def test_dolgu_stil_engeli(stil):
    metin = " ".join([TABAN] * 12)
    assert add_fillers(metin, rate=1.0, seed=1, style=stil) == metin


def test_dolgu_sohbet_stilinde_ve_varsayilanda_eklenir():
    metin = " ".join([TABAN] * 12)
    assert add_fillers(metin, rate=1.0, seed=1) != metin
    assert add_fillers(metin, rate=1.0, seed=1, style="podcast") != metin


@pytest.mark.parametrize("oran", [0, 0.0, -1, float("nan")])
def test_dolgu_oran_sifir_degistirmez(oran):
    metin = " ".join([TABAN] * 12)
    assert add_fillers(metin, rate=oran, seed=3) == metin


def test_dolgu_bos_ve_seedsiz():
    assert add_fillers("", seed=1) == ""
    assert isinstance(add_fillers(" ".join([TABAN] * 8), rate=0.5), str)


def test_dolgu_seed_belirlenimci():
    metin = " ".join([TABAN] * 40)
    assert add_fillers(metin, rate=0.2, seed=7) == add_fillers(metin, rate=0.2, seed=7)
    farkli = {add_fillers(metin, rate=0.2, seed=s) for s in range(6)}
    assert len(farkli) >= 3


@pytest.mark.parametrize("seed", range(6))
def test_dolgu_orani_ve_dort_cumlede_bir(seed):
    metin = " ".join([TABAN] * 100)
    siralar = _dolgulu_siralar(add_fillers(metin, rate=0.08, seed=seed))
    assert len(siralar) == 8                                       # 0.08 × 100
    assert min(b - a for a, b in pairwise(siralar)) >= FILLER_MIN_GAP
    yogun = _dolgulu_siralar(add_fillers(metin, rate=1.0, seed=seed))
    assert 10 <= len(yogun) <= math.ceil(100 / FILLER_MIN_GAP)
    assert min(b - a for a, b in pairwise(yogun)) >= FILLER_MIN_GAP


@pytest.mark.parametrize("seed", range(8))
def test_dolgu_yalniz_izinli_bicimler_ve_art_arda_ayni_yok(seed):
    cikti = add_fillers(" ".join([TABAN] * 60), rate=1.0, seed=seed)
    cumleler = _cumleler(cikti)
    assert len(cumleler) == 60
    dolgulu = [c for c in cumleler if c != TABAN]
    assert dolgulu and all(c in TABAN_VARYANT for c in dolgulu), dolgulu
    sozcukler = [_dolgu_sozcugu(c) for c in dolgulu]
    assert all(a != b for a, b in pairwise(sozcukler)), sozcukler


def test_dolgu_soru_cumlesinin_sonuna_eklenmez():
    metin = " ".join(["Yarın bize geliyor musun?"] * 40)
    for seed in range(10):
        for c in _cumleler(add_fillers(metin, rate=1.0, seed=seed)):
            assert c.endswith("geliyor musun?"), c
            assert not re.search(r"\b(ya|yani|işte)\?$", c)


def test_dolgu_uc_nokta_ve_tirnakla_biten_cumlenin_sonuna_eklenmez():
    metin = " ".join(['Annem bana dedi ki "yarın gel."', "Bilmiyorum, belki gelirim..."] * 10)
    for seed in range(10):
        cikti = add_fillers(metin, rate=1.0, seed=seed)
        assert cikti.count('"yarın gel."') == 10
        assert not re.search(r"(ya|yani|işte)\.\.\.", cikti)
        assert not re.search(r'"\s*(ya|yani|işte)\b', cikti)


def test_dolgu_dogal_olmayan_yerlere_girmez():
    metin = " ".join(["Güzel bir gün, di mi?", "Geldim, ama geç kaldım.", "Selam, nasılsın?",
                      'Bir gün yine gideriz, söz. Annem "Bir daha gel" dedi.'] * 6)
    for seed in range(25):
        cikti = add_fillers(metin, rate=1.0, seed=seed)
        assert not re.search(r", (yani|işte) (di mi|ama)\b", cikti), cikti     # soru eki / bağlaçtan önce olmaz
        assert not re.search(r"Selam, (yani|işte)\b", cikti), cikti            # selamlaşmadan sonra olmaz
        # tırnak içindeki "Bir daha" özel ad kanıtı sayılmaz: başa dolgu gelirse "bir gün" küçülür
        assert not re.search(r"(Yani|Hani|İşte|Şey|Ya|Bak|Valla), Bir gün", cikti), cikti


def test_dolgu_etiket_ve_tirnak_icine_dokunmaz():
    metin = ('[gülerek] Bugün çok güldük, sonra eve döndük. Annem "Yarın gel, olur mu? Bekliyorum." dedi. '
             '[fısıldayarak] Sonra sessizce çıktık, kimse duymadı. «Tamam, tamam» dedim ona. '
             '[vurgu: Çok önemli, unutma.] Bunu herkes bilsin.')
    korunanlar = ["[gülerek]", '"Yarın gel, olur mu? Bekliyorum."', "[fısıldayarak]", "«Tamam, tamam»",
                  "[vurgu: Çok önemli, unutma.]"]
    degisti = False
    for seed in range(30):
        cikti = add_fillers(metin, rate=1.0, seed=seed)
        degisti |= cikti != metin
        for parca in korunanlar:
            assert parca in cikti, (seed, cikti)
        assert not re.search(r"\[(Yani|Hani|İşte|Şey|Ya|Bak|Valla), ", cikti)
    assert degisti


def test_dolgu_ikinci_uygulama_dolgulu_cumleye_eklemez():
    metin = " ".join([TABAN] * 24)
    bir = add_fillers(metin, rate=1.0, seed=1)
    for seed in range(2, 8):
        iki = add_fillers(bir, rate=1.0, seed=seed)
        for once, sonra in zip(_cumleler(bir), _cumleler(iki)):
            if once != TABAN:
                assert sonra == once                      # dolgulu cümle olduğu gibi kalır
            else:
                assert sonra == TABAN or sonra in TABAN_VARYANT
    hazir = "Yani, bugün geldim. Hani, dün gelmiştin. İşte, böyle oldu. Bak, geç kaldın. Valla, bilmiyorum."
    assert add_fillers(hazir, rate=1.0, seed=3) == hazir


def test_dolgu_konusmaci_adi_ve_ozel_ad_korunur():
    metin = ("Ayşe: Bugün çok yorgunum, eve gidiyorum.\nMehmet: İstanbul'a döndüm, çok yoruldum.\n"
             "Ayşe: Ben de yoruldum, yarın görüşürüz.\nMehmet: Tamam, iyi geceler.")
    for seed in range(20):
        satirlar = add_fillers(metin, rate=1.0, seed=seed).split("\n")
        assert [s.split(":")[0] for s in satirlar] == ["Ayşe", "Mehmet", "Ayşe", "Mehmet"]
        assert "İstanbul'a" in satirlar[1]                 # kesmeli özel ad küçültülmez
        if satirlar[0].startswith(tuple("Ayşe: " + f for f in FILLERS_START)):
            assert "bugün çok yorgunum" in satirlar[0]    # sıradan sözcüğün baş harfi küçülür
