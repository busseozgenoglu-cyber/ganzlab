"""Türkçe doğallık değerlendirme seti: tests/data/tr_corpus.jsonl satır satır.

Her satır ``{"text", "expect", "reject", "note"}`` biçimindedir ve metin, seslendirmeden önceki tam zincirden geçer:

    apply_inline_readings → expand_chat_speak → apply_lexicon → textnorm.normalize(tr) → colloquial_tr(light)

Eşleşme kuralları:

* ``expect`` öğelerinin hepsi çıktıda geçmeli, ``reject`` öğelerinin hiçbiri geçmemeli.
* Düz öğeler Türkçe küçük harfe (``tr_lower``) indirilmiş ve boşlukları tekleştirilmiş çıktıda alt dizge olarak aranır.
* ``re:`` ile başlayan öğe ham çıktıda düzenli ifade olarak aranır (ör. ``"re:\\bTL\\b"``).
* Her satıra ayrıca ``ORTAK_YASAKLAR`` uygulanır: modele rakam, birleşik nokta (U+0307), etiket/okunuş parantezi
  ya da emoji gitmemeli.

Başarısız satır ``note`` alanıyla raporlanır. Mevcut modüllerdeki (textnorm / colloquial) bilinen hatalar burada
DÜZELTİLMEZ; ``BILINEN_HATALAR`` ile ``xfail(strict=False)`` işaretlenir — hata giderilince XPASS olarak görünür.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import lexicon
from app.colloquial import colloquial_tr
from app.textnorm import normalize
from app.tr import tr_lower

DERLEM = Path(__file__).resolve().parent / "data" / "tr_corpus.jsonl"
EN_AZ_SATIR = 120

#: Zincirdeki kullanıcı sözlüğü adımı için sabit örnek genel sözlük (gerçek data/lexicon.json'a dokunulmaz).
ORNEK_SOZLUK = {
    "SesKlon": "Ses Klon",
    "Michael": "Maykıl",
    "Jackson": "Ceksın",
    "Hugging Face": "Haging Feys",
}

#: Her satırda geçerli yasaklar: (desen, açıklama).
ORTAK_YASAKLAR = [
    ("re:\\d", "rakam kalmış"),
    ("re:\\u0307", "birleşik nokta (U+0307) kalmış — str.lower() hatası"),
    ("re:[{}|\\[\\]]", "etiket / satır içi okunuş sözdizimi kalmış"),
    ("re:[\\U0001F000-\\U0001FAFF\\u2600-\\u27BF\\uFE0F]", "emoji kalmış"),
]

#: Mevcut modüllerde bulunan gerçek hatalar (bu görevde düzeltilmez): metin → neden.
BILINEN_HATALAR: dict[str, str] = {}   # v4: önceki bilinen hatalar (buçuk/çeyrek yumuşaması, napıcaz, 5G, '2. Dünya') düzeltildi


def zincir(metin: str) -> str:
    """Seslendirme öncesi Türkçe metin zinciri (entegrasyondaki sırayla)."""
    t = lexicon.apply_inline_readings(metin)
    t = lexicon.expand_chat_speak(t)
    t = lexicon.apply_lexicon(t, "tr")
    t = normalize(t, "tr")
    return colloquial_tr(t, "light")


def _katla(s: str) -> str:
    return " ".join(tr_lower(s).split())


def _var_mi(cikti: str, desen: str) -> bool:
    if desen.startswith("re:"):
        return re.search(desen[3:], cikti) is not None
    return _katla(desen) in _katla(cikti)


def _satirlar() -> list[tuple[int, dict]]:
    out = []
    with DERLEM.open(encoding="utf-8") as f:
        for no, satir in enumerate(f, 1):
            if satir.strip():
                out.append((no, json.loads(satir)))
    return out


_ASCII = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _kimlik(no: int, kayit: dict) -> str:
    """Test kimliği: satır no + not kategorisi, ASCII ("L016-yuzde") — pytest çıktısında okunur kalsın."""
    kategori = str(kayit.get("note", "")).split(":", 1)[0].strip() or "satir"
    kategori = re.sub(r"[^a-z0-9]+", "-", tr_lower(kategori).translate(_ASCII)).strip("-")
    return f"L{no:03d}-{kategori}"


def _parametreler() -> list:
    params = []
    for no, kayit in _satirlar():
        neden = BILINEN_HATALAR.get(kayit["text"])
        marks = [pytest.mark.xfail(strict=False, reason=neden)] if neden else []
        params.append(pytest.param(no, kayit, id=_kimlik(no, kayit), marks=marks))
    return params


@pytest.fixture(autouse=True)
def ornek_sozluk(tmp_path, monkeypatch):
    """Zincirin sözlük adımı her satırda aynı, yalıtılmış örnek sözlükle çalışır."""
    yol = tmp_path / "lexicon.json"
    yol.write_text(json.dumps(ORNEK_SOZLUK, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(lexicon, "LEXICON_PATH", yol)
    return yol


# ------------------------------------------------------------------------------------------------ biçim

def test_derlem_bicimi():
    satirlar = _satirlar()
    assert len(satirlar) >= EN_AZ_SATIR, f"derlemde en az {EN_AZ_SATIR} satır olmalı: {len(satirlar)}"
    gorulen: set[str] = set()
    for no, kayit in satirlar:
        assert set(kayit) == {"text", "expect", "reject", "note"}, f"satır {no}: alanlar {sorted(kayit)}"
        assert isinstance(kayit["text"], str) and kayit["text"].strip(), f"satır {no}: boş metin"
        assert isinstance(kayit["note"], str) and kayit["note"].strip(), f"satır {no}: not yok"
        assert isinstance(kayit["expect"], list) and kayit["expect"], f"satır {no}: expect boş"
        assert isinstance(kayit["reject"], list), f"satır {no}: reject liste değil"
        assert all(isinstance(x, str) and x for x in kayit["expect"] + kayit["reject"]), f"satır {no}: boş desen"
        for desen in kayit["expect"] + kayit["reject"]:
            if desen.startswith("re:"):
                re.compile(desen[3:])
        assert kayit["text"] not in gorulen, f"satır {no}: yinelenen metin {kayit['text']!r}"
        gorulen.add(kayit["text"])


def test_bilinen_hatalar_derlemde_var():
    metinler = {k["text"] for _, k in _satirlar()}
    assert set(BILINEN_HATALAR) <= metinler, set(BILINEN_HATALAR) - metinler


def test_degerlendirme_duzenegi():
    """Düzeneğin kendisi: ortak yasaklar gerçekten yakalıyor; düz desenler Türkçe küçük harfle eşleşiyor."""
    rakam, nokta, sozdizimi, emoji = (d for d, _ in ORTAK_YASAKLAR)
    assert _var_mi("saat 5", rakam)
    assert _var_mi("i" + chr(0x307) + "stanbul", nokta)
    assert _var_mi("{Klod}", sozdizimi) and _var_mi("[gülerek]", sozdizimi) and _var_mi("a|b", sozdizimi)
    assert _var_mi("harika " + chr(0x1F60A), emoji) and _var_mi("kalp " + chr(0x2764) + chr(0xFE0F), emoji)
    temiz = "İstanbul'da hava ılık, saat on dört otuz. Kâr ettik!"
    assert not any(_var_mi(temiz, d) for d, _ in ORTAK_YASAKLAR)
    assert _var_mi("İSTANBUL'DA", "istanbul'da")
    assert _var_mi("ILIK", "ılık") and not _var_mi("ILIK", "ilik")
    assert _var_mi("bir  iki\nüç", "bir iki üç")
    assert _var_mi("Sitemiz sesklon nokta com nokta.", "re:nokta\\W*$")       # cümle noktası okunmuş
    assert not _var_mi("Sitemiz sesklon nokta com.", "re:nokta\\W*$")


# --------------------------------------------------------------------------------------- satır satır

@pytest.mark.parametrize("no, kayit", _parametreler())
def test_derlem_satiri(no, kayit):
    cikti = zincir(kayit["text"])
    eksik = [d for d in kayit["expect"] if not _var_mi(cikti, d)]
    yasak = [d for d in kayit["reject"] if _var_mi(cikti, d)]
    yasak += [f"{d} ({neden})" for d, neden in ORTAK_YASAKLAR if _var_mi(cikti, d)]
    assert not eksik and not yasak, (
        f"\n satır  : {no} — {kayit['note']}"
        f"\n girdi  : {kayit['text']!r}"
        f"\n çıktı  : {cikti!r}"
        f"\n eksik  : {eksik}"
        f"\n yasak  : {yasak}"
    )
