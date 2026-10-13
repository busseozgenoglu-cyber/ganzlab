"""dialog.py testleri: biçimler, yönergeler, yanlış pozitifler, konuşmacı eşleştirme, duraklama planı, rapor."""
import pytest

from app import dialog
from app.dialog import (
    HEADER_WORDS, Turn, format_dialog, is_dialog, merge_turn_report, parse_dialog, plan_turn_pauses,
    resolve_directive, speakers_of, strip_speaker_tags,
)
from app.tr import tr_capitalize, tr_upper


def _ozet(text):
    """(konuşmacı, metin) listesi."""
    return [(t.speaker, t.text) for t in parse_dialog(text)]


# ---------- üç biçim ----------

def test_iki_nokta_bicimi_ve_satir_numaralari():
    turns = parse_dialog("Ayşe: Selam, naber?\n\nMehmet: İyiyim, sen?")
    assert [(t.index, t.speaker, t.text, t.line_no) for t in turns] == [
        (0, "Ayşe", "Selam, naber?", 1),
        (1, "Mehmet", "İyiyim, sen?", 3),            # boş satır atlanır ama satır numarası korunur
    ]
    assert isinstance(turns[0], Turn)
    assert [t.line_no for t in parse_dialog("Ayşe: a\r\n\r\nMehmet: b")] == [1, 3]
    assert _ozet("﻿Ayşe : Selam") == [("Ayşe", "Selam")]       # BOM ve iki noktadan önce boşluk


def test_tire_bicimleri():
    assert _ozet("AYŞE — Merhaba.\nMehmet – Selam.\nAyşe - Nasılsın?") == [
        ("AYŞE", "Merhaba."), ("Mehmet", "Selam."), ("AYŞE", "Nasılsın?"),
    ]
    assert _ozet("Ayşe-Nur - Selam.") == [("Ayşe-Nur", "Selam.")]    # tireli ad, boşluklu tire ayraç
    assert _ozet("Ayşe -Selam") == [(None, "Ayşe -Selam")]           # tireden sonra boşluk yok → ad değil


def test_ses_etiketi_bicimi():
    turns = parse_dialog("[ses:Ali] Selam. [ses:Veli] Merhaba.")
    assert [(t.index, t.speaker, t.text, t.line_no) for t in turns] == [
        (0, "Ali", "Selam.", 1), (1, "Veli", "Merhaba.", 1),
    ]
    assert _ozet("[konuşmacı: Mehmet Ali] Tamam.") == [("Mehmet Ali", "Tamam.")]
    assert _ozet("[SES: Zeynep] Evet. [KONUŞMACI:Can] Hayır.") == [("Zeynep", "Evet."), ("Can", "Hayır.")]
    # yalnızca etiketten oluşan satır konuşmacıyı değiştirir; sonraki satırlar onunla sürer
    assert _ozet("[ses:Elif]\nSelam.\nNasılsın?") == [("Elif", "Selam."), ("Elif", "Nasılsın?")]
    # etiketten önceki metin o anki konuşmacıya (burada anlatıcı) aittir
    assert _ozet("Önce bu. [ses:Can] Sonra bu.") == [(None, "Önce bu."), ("Can", "Sonra bu.")]
    assert _ozet("Ayşe: Selam. [ses:Mehmet] Merhaba.") == [("Ayşe", "Selam."), ("Mehmet", "Merhaba.")]


def test_karisik_bicim():
    text = (
        "Bir gün...\n"
        "Ayşe: Selam!\n"
        "MEHMET — Merhaba.\n"
        "[ses:Zeynep] Ben de buradayım. [ses:Ayşe] Harika.\n"
        "Mehmet (fısıldayarak): Sessiz ol."
    )
    turns = parse_dialog(text)
    assert [(t.speaker, t.text) for t in turns] == [
        (None, "Bir gün..."), ("Ayşe", "Selam!"), ("MEHMET", "Merhaba."), ("Zeynep", "Ben de buradayım."),
        ("Ayşe", "Harika."), ("MEHMET", "[fısıldayarak] Sessiz ol."),
    ]
    assert [t.index for t in turns] == list(range(6))
    assert [t.line_no for t in turns] == [1, 2, 3, 4, 4, 5]
    assert speakers_of(turns) == ["Ayşe", "MEHMET", "Zeynep"]


# ---------- parantezli yönergeler ----------

def test_parantezli_yonerge_duygu_olarak_cozulur():
    assert _ozet("Ayşe (gülerek): Selam.") == [("Ayşe", "[güler] Selam.")]
    assert _ozet("Mehmet (Fısıldayarak.): Gel.") == [("Mehmet", "[fısıldayarak] Gel.")]
    assert _ozet("Can (heyecanla) — Başlıyoruz!") == [("Can", "[heyecanlı] Başlıyoruz!")]
    assert _ozet("Ayşe: (iç çekerek) Of ya.") == [("Ayşe", "[iç çeker] Of ya.")]       # metin başında da
    assert _ozet("Ayşe (alaycı ve sinirli): Tabii.") == [("Ayşe", "[alaycı] [sinirli] Tabii.")]
    assert _ozet("Ayşe [gülme]: Hahaha.") == [("Ayşe", "[gülme] Hahaha.")]                # köşeli: olduğu gibi
    assert _ozet("[ses:Ali] (biraz üzgün) Gidiyorum.") == [("Ali", "[biraz üzgün] Gidiyorum.")]


def test_parantezli_yonerge_cozulemezse_atilir():
    assert _ozet("Mehmet (kapıyı açar): Kim o?") == [("Mehmet", "Kim o?")]
    assert _ozet("Ayşe (gülerek, kapıyı açar): Ben.") == [("Ayşe", "[güler] Ben.")]
    assert _ozet("Ayşe: (ayağa kalkar) Gidiyorum.") == [("Ayşe", "Gidiyorum.")]
    # 60 karakteri aşan ve ardından metin gelen parantez yönerge sayılmaz, metin olarak kalır
    uzun = "Ayşe: (bu parantez altmış karakterden uzun olduğu için yönerge sayılmaz, metin kalır) Evet."
    assert parse_dialog(uzun)[0].text == uzun[len("Ayşe: "):]


def test_yalnizca_parantezden_olusan_satir_sahne_yonergesidir():
    text = (
        "Ayşe: Kim o?\n"
        "(Kapı çalar.)\n"
        "(güler)\n"
        "(Uzun bir sessizlik olur, kimse konuşmaz, rüzgâr perdeleri savurur, uzakta bir köpek havlar.)\n"
        "Mehmet: Benim."
    )
    turns = parse_dialog(text)
    assert [(t.speaker, t.text, t.line_no) for t in turns] == [
        ("Ayşe", "Kim o?", 1), ("Ayşe", "[güler]", 3), ("Mehmet", "Benim.", 5),
    ]


def test_resolve_directive():
    # sözsüz tepki tabloları emotion.py'de genişleyebilir: zarf-fiilin kendisi de eklenirse o anahtar döner
    assert resolve_directive("gülerek") in {"güler", "gülme", "gülerek"}
    assert resolve_directive("iç çekerek") in {"iç çeker", "iç çekme", "iç çekerek"}
    assert resolve_directive("kahkaha atarak") in {"kahkaha atar", "kahkaha", "kahkaha atarak"}
    assert resolve_directive("Fısıldayarak") == "fısıltı"
    assert resolve_directive("alaycı bir sesle") == "alaycı"
    assert resolve_directive("heyecanla") == "heyecanlı"
    assert resolve_directive("sessizce") == "fısıltı"
    assert resolve_directive("HEYECANLI") == "heyecanlı"
    assert resolve_directive("biraz üzgün") == "üzgün"
    assert resolve_directive("sakinleşerek") == "sakin"
    assert resolve_directive("2 sn") == "2 sn"
    assert resolve_directive("kapıyı açar") is None
    assert resolve_directive("ayağa kalkar") is None
    assert resolve_directive("") is None and resolve_directive(None) is None


# ---------- konuşmacısız satırlar, anlatıcı ----------

def test_konusmacisiz_satir_onceki_konusmaciyla_surer():
    turns = parse_dialog("Ayşe: Selam.\nNasılsın?\nBugün hava güzel.\nMehmet: İyiyim.\nSen?")
    assert [(t.speaker, t.text) for t in turns] == [
        ("Ayşe", "Selam."), ("Ayşe", "Nasılsın?"), ("Ayşe", "Bugün hava güzel."),
        ("Mehmet", "İyiyim."), ("Mehmet", "Sen?"),
    ]                                                   # aynı konuşmacının ardışık satırları AYRI Turn


def test_bastaki_konusmacisiz_satirlar_anlaticidir():
    turns = parse_dialog("Bir varmış bir yokmuş.\n\nKüçük bir köy varmış.\nAyşe: Selam.")
    assert [t.speaker for t in turns] == [None, None, "Ayşe"]
    assert speakers_of(turns) == ["Ayşe"]
    assert parse_dialog("") == [] and parse_dialog("  \n\n ") == []


# ---------- yanlış pozitifler ----------

def test_baslik_sozcukleri_sayisi():
    assert len(HEADER_WORDS) == 20
    assert {"not", "örnek", "saat", "ipucu", "adım", "açıklama"} <= HEADER_WORDS


@pytest.mark.parametrize("word", sorted(HEADER_WORDS))
def test_baslik_sozcugu_konusmaci_degildir(word):
    for line in (f"{tr_capitalize(word)}: Bu satır düz metindir.", f"{tr_upper(word)}: Bu satır düz metindir."):
        assert _ozet(line) == [(None, line)]


def test_baslik_sozcukleri_diyalog_saydirmaz():
    assert not is_dialog("Not: a\nÖrnek: b\nSoru: c\nCevap: d")
    assert _ozet("Notlar: x\nİpucu - y") == [(None, "Notlar: x"), (None, "İpucu - y")]
    # gerçek konuşmacıdan sonra gelen başlık satırı o konuşmacının metnidir
    assert _ozet("Ayşe: Selam.\nNot: yarın gel.") == [("Ayşe", "Selam."), ("Ayşe", "Not: yarın gel.")]


def test_sayi_iceren_ad_degildir():
    for line in ("Saat 14:30: Toplantı başlıyor.", "12:30'da buluşalım.", "Toplantı 14:30: herkes gelsin",
                 "Konuşmacı 1: Merhaba."):
        assert _ozet(line) == [(None, line)]
    assert _ozet("Ayşe: Saat 14:30'da gel.") == [("Ayşe", "Saat 14:30'da gel.")]


def test_url_konusmaci_degildir():
    for line in ("https://ornek.com/sayfa adresine bakın.", "http://ornek.com - bağlantı",
                 "Kaynak: https://ornek.com"):
        assert _ozet(line) == [(None, line)]


def test_ad_bicimi_kurallari():
    assert _ozet("Bu Çok Uzun Bir Ad Olamaz: metin") == [(None, "Bu Çok Uzun Bir Ad Olamaz: metin")]
    uzun_ad = "Muhteşemsüleymanoğulları Kardeşlerinevinden Ahmet"           # 3 sözcük ama > 40 karakter
    assert len(uzun_ad) > 40 and parse_dialog(f"{uzun_ad}: Selam.")[0].speaker is None
    assert parse_dialog("ayşe: selam")[0].speaker is None                    # küçük harfle başlıyor
    assert _ozet("Ali:Selam") == [(None, "Ali:Selam")]                       # ayraçtan sonra boşluk yok
    assert _ozet("Ayşe:") == [(None, "Ayşe:")]                               # ad var, metin yok
    assert _ozet("Sorun şu: param yok.") == [(None, "Sorun şu: param yok.")]  # küçük harfli 2. sözcük
    assert _ozet("Ali bey: Buyurun.\nFatma teyze - Gel kızım.") == [
        ("Ali bey", "Buyurun."), ("Fatma teyze", "Gel kızım."),               # küçük harfli hitaplar
    ]
    assert _ozet("Dr. Ahmet Yılmaz: Geçmiş olsun.") == [("Dr. Ahmet Yılmaz", "Geçmiş olsun.")]
    assert _ozet("Ali’nin Annesi: Gel.") == [("Ali’nin Annesi", "Gel.")]


# ---------- büyük/küçük harf, etiketler ----------

def test_buyuk_kucuk_harf_ayni_konusmaci_ilk_yazim_korunur():
    turns = parse_dialog("Ayşe: Bir.\nAYŞE: İki.\nayşe: Üç.\n[ses:AYŞE] Dört.\nİlker: Beş.\nİLKER — Altı.")
    assert [t.speaker for t in turns] == ["Ayşe"] * 4 + ["İlker"] * 2
    assert [t.text for t in turns] == ["Bir.", "İki.", "Üç.", "Dört.", "Beş.", "Altı."]
    assert speakers_of(turns) == ["Ayşe", "İlker"]
    assert speakers_of(parse_dialog("[ses:mehmet] a\nMehmet: b")) == ["mehmet"]


def test_koseli_parantez_etiketleri_oldugu_gibi_kalir():
    assert _ozet("Ayşe: [heyecanlı] Kazandık! [gülme] [1.5 sn] Hadi.") == [
        ("Ayşe", "[heyecanlı] Kazandık! [gülme] [1.5 sn] Hadi."),
    ]
    assert _ozet("Mehmet: [heyecanlı: Bu kısım coşkulu.] Sonra normal.") == [
        ("Mehmet", "[heyecanlı: Bu kısım coşkulu.] Sonra normal."),          # kapsamlı duygu etiketi ses değil
    ]
    assert _ozet("Can: [heyecanlı]Selam") == [("Can", "[heyecanlı]Selam")]


# ---------- is_dialog / speakers_of ----------

def test_is_dialog():
    assert is_dialog("Ayşe: Selam.\nMehmet: Merhaba.")
    assert is_dialog("[ses:A] Selam. [ses:B] Merhaba.")
    assert not is_dialog("Ayşe: Selam.\nAYŞE: Yine ben.\nayşe: Bir daha.")   # tek konuşmacı
    assert not is_dialog("Bir varmış.\nAyşe: Selam.")                        # anlatıcı sayılmaz
    assert not is_dialog("Düz bir metin.") and not is_dialog("")


def test_speakers_of_sira_ve_tekillik():
    turns = [Turn(0, None, "a", 1), Turn(1, "Zeynep", "b", 2), Turn(2, "Ali", "c", 3), Turn(3, "ZEYNEP", "d", 4)]
    assert speakers_of(turns) == ["Zeynep", "Ali"]
    assert speakers_of([]) == []


# ---------- duraklama planı ----------

_DIYALOG = (
    "Ayşe: Selam.\nNasılsın?\nMehmet: İyiyim!\nAyşe: Emin misin?\nMehmet: Bilmem...\nAyşe: Peki…\n"
    "Mehmet: \"Tamam.\"\nAyşe: Gel."
)


def test_plan_turn_pauses_kurallar(monkeypatch):
    monkeypatch.setattr(dialog, "JITTER", 0.0)
    turns = parse_dialog(_DIYALOG)
    assert plan_turn_pauses(turns, [1.0] * len(turns)) == [450, 200, 230, 200, 520, 520, 260, 0]
    # uzun önceki sıra (> 6 sn) konuşmacı değişiminde +80; aynı konuşmacıda ek yok
    uzun = [7.0] * len(turns)
    assert plan_turn_pauses(turns, uzun) == [450, 280, 310, 280, 600, 600, 340, 0]
    # sondaki etiket ve tırnak atlanır; anlatıcıdan konuşmacıya geçiş de değişimdir
    assert plan_turn_pauses(parse_dialog("Ayşe: Gel mi? [gülme]\nMehmet: Gelirim."), [1, 1]) == [200, 0]
    assert plan_turn_pauses(parse_dialog('Ayşe: "Geliyor musun?"\nMehmet: Evet.'), [1, 1]) == [200, 0]
    assert plan_turn_pauses(parse_dialog("Bir gün.\nAyşe: Selam."), [1, 1]) == [260, 0]
    assert plan_turn_pauses([], []) == []
    assert plan_turn_pauses(turns[:1], [3.0]) == [0]


def test_plan_turn_pauses_jitter_seed_belirlenimci(monkeypatch):
    turns = parse_dialog(_DIYALOG)
    durs = [2.0] * len(turns)
    a = plan_turn_pauses(turns, durs, seed=42)
    assert a == plan_turn_pauses(turns, durs, seed=42)
    assert a != plan_turn_pauses(turns, durs, seed=43)
    with monkeypatch.context() as m:
        m.setattr(dialog, "JITTER", 0.0)
        base = plan_turn_pauses(turns, durs)
    for plan in (a, plan_turn_pauses(turns, durs, seed=None)):
        assert plan[-1] == 0
        for got, b in zip(plan[:-1], base[:-1]):
            assert round(b * 0.85) <= got <= round(b * 1.15)
        assert all(120 <= p <= 1500 for p in plan[:-1])


def test_plan_turn_pauses_sikistirma_ve_eksik_sure(monkeypatch):
    monkeypatch.setattr(dialog, "JITTER", 0.0)
    monkeypatch.setitem(dialog.TURN_PAUSE_MS, "same", 5000)
    monkeypatch.setitem(dialog.TURN_PAUSE_MS, "change", 10)
    turns = parse_dialog("Ayşe: Bir.\nİki.\nMehmet: Üç.")
    assert plan_turn_pauses(turns, [1, 1, 1]) == [1500, 120, 0]
    # eksik / geçersiz süre çökertmez, 0 sn sayılır
    assert plan_turn_pauses(turns, []) == [1500, 120, 0]
    assert plan_turn_pauses(turns, [None, float("nan")]) == [1500, 120, 0]


# ---------- rapor, temizleme, geri yazım ----------

def test_merge_turn_report():
    turns = parse_dialog("Giriş.\nAyşe: Selam.\nMEHMET: Merhaba.\nKerem: Hey.")
    rep = merge_turn_report(turns, [0, 1.23456, 2.5, 3.0], [1.0, 2.0],
                            {"ayşe": "Elif (sıcak)", "Mehmet": "Can", "anlatıcı": "Anlatıcı sesi"})
    assert set(rep[0]) == {"index", "speaker", "voice_name", "text", "start", "end"}
    assert [r["voice_name"] for r in rep] == ["Anlatıcı sesi", "Elif (sıcak)", "Can", None]
    assert [r["index"] for r in rep] == [0, 1, 2, 3] and rep[2]["speaker"] == "MEHMET"
    assert rep[1]["text"] == "Selam." and rep[1]["start"] == 1.235 and rep[1]["end"] == 2.0
    assert rep[2]["end"] is None and rep[3]["end"] is None
    assert merge_turn_report([], [], [], {}) == []


def test_strip_speaker_tags():
    assert strip_speaker_tags("[ses:Ayşe] Merhaba, ben Ayşe.") == "Merhaba, ben Ayşe."
    assert strip_speaker_tags("[ses:Ayşe]\nSelam.\n\nNasılsın [konuşmacı: Ayşe] ?") == "Selam.\n\nNasılsın?"
    assert strip_speaker_tags("[heyecanlı: harika] [ses:Ali] olmuş") == "[heyecanlı: harika] olmuş"
    diyalog = "[ses:A] Selam. [ses:B] Merhaba."
    assert strip_speaker_tags(diyalog) == diyalog                       # diyalogsa dokunulmaz
    duz = "Ayşe: Selam.\n  girintili satır"
    assert strip_speaker_tags(duz) == duz and strip_speaker_tags("") == ""


def test_format_dialog_geri_yazim():
    src = "Giriş metni.\nAyşe (gülerek): Selam.\n[ses:mehmet] Merhaba. [ses:Not] Hı.\nDevam.\nAli bey - Buyurun."
    turns = parse_dialog(src)
    out = format_dialog(turns)
    assert out.splitlines() == [
        "Giriş metni.", "Ayşe: [güler] Selam.", "[ses:mehmet] Merhaba.", "[ses:Not] Hı.", "[ses:Not] Devam.",
        "Ali bey: Buyurun.",
    ]
    assert [(t.speaker, t.text) for t in parse_dialog(out)] == [(t.speaker, t.text) for t in turns]
    assert format_dialog([]) == ""
