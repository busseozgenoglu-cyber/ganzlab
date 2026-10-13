#!/usr/bin/env python3
"""Kayıt senaryosu üretici — ince ayar verisi için okuma senaryoları, manifest ve özet (SOZLESME3 §4).

Cümle bankasını (``finetune/cumleler/<duygu>.txt``) okur, isteğe bağlı olarak kullanıcının kendi metnini
(kitap, senaryo) cümlelere bölüp ``normal`` duyguya ekler, satırları oturumlara böler ve kayıt masasında
kullanılacak dosyaları yazar:

* ``senaryo/oturum_01.md`` … — okuma senaryosu: kayıt hatırlatması, her duygu için başlık + yönerge + örnek,
  numaralı satırlar ``1. [mutlu_0007] Cümle…`` ve yoğunluk notu
* ``senaryo/manifest.csv`` — ``id|duygu|yogunluk|metin`` (başlık satırlı, UTF-8; ``hazirla.py`` bunu okur)
* ``senaryo/OZET.md`` — toplam cümle, duygu dağılımı, tahmini süre, oturumlar, "3 saat için ne gerekir" hesabı
* ``senaryo/kayit_listesi.txt`` — yalnızca kayıt adları, sırayla (kayıt programına yapıştırmak için)

Kullanım::

    python finetune/senaryo.py --cikti senaryo/ [--banka finetune/cumleler] [--oturum N] [--metin kitap.txt]
                               [--duygular mutlu,üzgün] [--tekrar 2] [--kisi "Ad"]
    python finetune/senaryo.py --kontrol          # bankayı denetler; HATA varsa çıkış kodu 1

Banka biçimi: satır başına bir cümle; ``#`` ile başlayan satırlar yorumdur; ``# yönerge: …`` oyuncuya tek
cümlelik oynama talimatı, ``# örnek: …`` nasıl söyleneceğine dair örnektir. Duygu adı dosya adıdır
(``üzgün.txt`` → ``üzgün``; Türkçe karakter serbest). Küçük harfe çevirme her yerde ``app.tr.tr_lower`` iledir.

Betik yalnızca ``app.tr``'ye muhtaçtır (backend klasörünü ``sys.path``'e kendisi ekler); duygu adı denetimi için
``app.emotion`` varsa kullanılır, yoksa o denetim atlanır.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.tr import tr_lower  # noqa: E402  (yol yukarıda eklenir)

# ---------- sabitler ----------

SN_CUMLE = 3.5                 # bir cümlenin ortalama ses süresi (sn)
SN_ARA = 1.5                   # cümleler arası bekleme (sn); kırpılır, eğitim verisine girmez
OTURUM_SATIR = 120             # bir oturumda en çok satır (≈ 25 dk okuma)
MIN_SOZCUK = 4                 # --metin bölmede: virgülden bölünen parçalar bundan kısaysa komşusuna eklenir
MIN_CUMLE_SOZCUK = 2           # --metin bölmede: tam cümle bundan kısaysa ("Evet.") öncekine eklenir
MAX_SOZCUK = 25                # --metin bölmede: bundan uzun cümleler virgülden bölünür
BANKA_MIN_CUMLE = 30           # her banka dosyasında en az cümle
BANKA_MIN_SOZCUK = 3           # bankada bir cümlede en az sözcük (HATA)
BANKA_MAX_SOZCUK = 20          # bankada bir cümlede en çok sözcük (UYARI)
HEDEF_SAAT = 3.0               # önerilen toplam ses (saat)
ZORUNLU_DK = 30.0              # zorunlu en az toplam ses (dk)
YOGUNLUK_SIRASI = ("hafif", "normal", "güçlü")
SOZCUK_PER_CUMLE = 12          # ek metin tahmini için ortalama sözcük/cümle
SOZCUK_PER_SAYFA = 300         # ek metin tahmini için ortalama sözcük/kitap sayfası
VARSAYILAN_YONERGE = "Doğal, nötr okuma; anlatır gibi, duygu katmadan, sohbet temposunda."

# Nokta ile biten ama cümleyi bitirmeyen kısaltmalar (küçük harf, noktasız)
KISALTMALAR = frozenset("""
dr prof doç yrd av vb vs vd bkz örn ör sn no tel cad sok mah apt bay bayan mr mrs ms hz md gen alb yzb tğm
üstğm bnb yrb uzm op ar gör yy çev haz ed der mad fak ünv bşk ltd şti sf bl böl krş bk age agy mim müh ecz vet
dz hv ord asb astsb bşb bşç çvş onb
""".split())

_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")
_SON_RE = re.compile(r"([.!?…]+)([\"'»”’)\]]*)(?=\s|$)")       # cümle sonu adayı: noktalama (+kapanış) + boşluk/son
_KAPANIS_RE = re.compile(r"[.!?…][\"'»”’)\]]*$")                 # metin noktalamayla bitiyor mu
_YORUM_RE = re.compile(r"^#\s*([^:]{1,24}):\s*(.*)$")           # "# yönerge: …" / "# örnek: …"
_SOZCUK_RE = re.compile(r"\w")
_ETIKET_RE = re.compile(r"\[[^\]]{1,60}\]")


def _fold(s: str) -> str:
    """Türkçe küçük harf + ASCII indirgeme ("Üzgün" → "uzgun"); yedek eşleşme için."""
    return tr_lower(s).translate(_FOLD)


def _sozcuk_sayisi(s: str) -> int:
    """Harf ya da rakam içeren boşlukla ayrılmış parçaların sayısı ("—" gibi tek başına işaretler sayılmaz)."""
    return sum(1 for t in s.split() if _SOZCUK_RE.search(t))


def _normalize_cumle(s: str) -> str:
    """Tekrar denetimi için anahtar: Türkçe küçük harf, tek boşluk, baş/son noktalama ve tırnak atılmış."""
    s = re.sub(r"\s+", " ", tr_lower(s)).strip()
    return s.strip(" .!?…,;:\"'«»“”‘’()-–—")


def _tr_sayi(x: float, basamak: int = 1) -> str:
    """Türkçe ondalık ayırıcı: 3.5 → "3,5"."""
    return f"{x:.{basamak}f}".replace(".", ",")


def _dk(sn: float) -> str:
    return _tr_sayi(sn / 60.0)


def _temiz_metin(s: str) -> str:
    """Manifest alanına girecek metin: tek satır, ayırıcı ``|`` içermez."""
    return re.sub(r"\s+", " ", s.replace("|", "/")).strip()


# ---------- banka ----------

def _dosya_oku(path: Path) -> dict:
    """Tek banka dosyasını okur → {"yonerge", "ornek", "cumleler"}. UTF-8 değilse ValueError (Türkçe mesaj)."""
    try:
        ham = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path.name}: dosya UTF-8 değil ({e.reason}, bayt {e.start})") from None
    yonerge, ornek, cumleler = "", "", []
    for satir in ham.splitlines():
        satir = satir.strip()
        if not satir:
            continue
        if satir.startswith("#"):
            m = _YORUM_RE.match(satir)
            if m:
                anahtar = tr_lower(m.group(1)).strip()
                if anahtar in ("yönerge", "yonerge"):
                    yonerge = m.group(2).strip()
                elif anahtar in ("örnek", "ornek"):
                    ornek = m.group(2).strip()
            continue
        cumleler.append(re.sub(r"\s+", " ", satir))
    return {"yonerge": yonerge, "ornek": ornek, "cumleler": cumleler}


def load_bank(dir: str | Path) -> dict[str, dict]:
    """Cümle bankasını okur: {duygu: {"yonerge": str, "ornek": str, "cumleler": [str]}}.

    Duygu adı = dosya adı (uzantısız, Türkçe küçük harf). Sıra: ``normal`` önce (oturuma ısınma), kalanlar dosya
    adı sırasıyla; klasör yoksa {}.
    Okunamayan (UTF-8 olmayan) dosya ValueError fırlatır; ``check_bank`` bunu sorun olarak raporlar.
    """
    klasor = Path(dir)
    if not klasor.is_dir():
        return {}
    banka: dict[str, dict] = {}
    for path in sorted(klasor.glob("*.txt")):
        if path.name.startswith("."):
            continue
        banka[tr_lower(path.stem).strip()] = _dosya_oku(path)
    if "normal" in banka:
        banka = {"normal": banka.pop("normal"), **banka}
    return banka


def _profil_adlari() -> set[str] | None:
    """app.emotion yüklenebiliyorsa bilinen duygu adları; yoksa None (denetim atlanır)."""
    try:
        from app.emotion import PROFILES
    except Exception:  # noqa: BLE001 — numpy/soundfile yoksa duygu adı denetimi yapılmaz
        return None
    return set(PROFILES)


def check_bank(dir: str | Path) -> list[str]:
    """Bankayı denetler; her sorun "HATA: …" ya da "UYARI: …" ile başlayan tek satırdır. Sorun yoksa [].

    HATA: dosya yok/boş, UTF-8 değil, < 30 cümle, yönerge yok, tekrar (tr_lower ile), < 3 sözcük, satır sonunda
    noktalama yok, ``|`` ya da ``[etiket]`` içeriyor. UYARI: > 20 sözcük, örnek yok, duygu adı profillerde yok.
    """
    klasor = Path(dir)
    sorunlar: list[str] = []
    if not klasor.is_dir():
        return [f"HATA: banka klasörü yok: {klasor}"]
    dosyalar = sorted(p for p in klasor.glob("*.txt") if not p.name.startswith("."))
    if not dosyalar:
        return [f"HATA: banka klasöründe .txt dosyası yok: {klasor}"]
    profiller = _profil_adlari()
    for path in dosyalar:
        ad = path.name
        try:
            d = _dosya_oku(path)
        except ValueError as e:
            sorunlar.append(f"HATA: {e}")
            continue
        cumleler = d["cumleler"]
        if len(cumleler) < BANKA_MIN_CUMLE:
            sorunlar.append(f"HATA: {ad}: {len(cumleler)} cümle (en az {BANKA_MIN_CUMLE} gerekli)")
        if not d["yonerge"]:
            sorunlar.append(f"HATA: {ad}: '# yönerge:' satırı yok")
        if not d["ornek"]:
            sorunlar.append(f"UYARI: {ad}: '# örnek:' satırı yok")
        duygu = tr_lower(path.stem).strip()
        if profiller is not None and duygu not in profiller:
            sorunlar.append(f"UYARI: {ad}: '{duygu}' app.emotion profillerinde yok (etiket motor tarafından tanınmaz)")
        gorulen: dict[str, int] = {}
        for i, c in enumerate(cumleler, 1):
            anahtar = _normalize_cumle(c)
            if anahtar in gorulen:
                sorunlar.append(f"HATA: {ad}: {i}. cümle {gorulen[anahtar]}. cümlenin tekrarı: \"{c}\"")
            else:
                gorulen[anahtar] = i
            n = _sozcuk_sayisi(c)
            if n < BANKA_MIN_SOZCUK:
                sorunlar.append(f"HATA: {ad}: {i}. cümle {n} sözcük (en az {BANKA_MIN_SOZCUK}): \"{c}\"")
            elif n > BANKA_MAX_SOZCUK:
                sorunlar.append(f"UYARI: {ad}: {i}. cümle {n} sözcük (en çok {BANKA_MAX_SOZCUK} önerilir): \"{c}\"")
            if not _KAPANIS_RE.search(c):
                sorunlar.append(f"HATA: {ad}: {i}. cümle noktalamayla bitmiyor: \"{c}\"")
            if "|" in c:
                sorunlar.append(f"HATA: {ad}: {i}. cümle '|' içeriyor (manifest ayırıcısı): \"{c}\"")
            if _ETIKET_RE.search(c):
                sorunlar.append(f"HATA: {ad}: {i}. cümle köşeli parantez etiketi içeriyor: \"{c}\"")
    return sorunlar


# ---------- cümle bölme ----------

def _kisaltma_mi(onceki: str) -> bool:
    """Noktadan önceki son sözcük bir kısaltma mı (Dr., vb., T.C., tek harf, 1–2 basamaklı sıra sayısı)?"""
    m = re.search(r"(\S+)$", onceki)
    if not m:
        return False
    tok = tr_lower(m.group(1)).lstrip("\"'«“‘([—–-")
    if not tok:
        return False
    if "." in tok:                                   # T.C / A.Ş
        return True
    if tok in KISALTMALAR:
        return True
    if len(tok) == 1 and tok.isalpha():              # A. Kemal
        return True
    if tok.isdigit() and len(tok) <= 2:              # 3. kat, 19. yüzyıl
        return True
    return False


def _ham_cumleler(para: str) -> list[str]:
    """Bir paragrafı noktalamadan cümlelere ayırır; kısaltmalardan ve küçük harfle süren yerlerden bölmez."""
    out: list[str] = []
    bas = 0
    for m in _SON_RE.finditer(para):
        son = m.end()
        kalan = para[son:].lstrip()
        if not kalan:
            break
        if kalan[0].islower():                       # "vb. gibi", "Gel!" dedi, "belki..." sonra
            continue
        if m.group(1) == "." and _kisaltma_mi(para[:m.start()]):
            continue
        parca = para[bas:son].strip()
        if parca:
            out.append(parca)
        bas = son
    kalan = para[bas:].strip()
    if kalan:
        out.append(kalan)
    return out


def _noktala(s: str) -> str:
    """Parçanın sonunu cümle gibi bitirir: sondaki virgül/noktalı virgül atılır, noktalama yoksa nokta eklenir."""
    s = re.sub(r"[,;:]+$", "", s.strip()).strip()
    if s and not _KAPANIS_RE.search(s):
        s += "."
    return s


def _sozcuklerden_bol(parca: str, max_words: int) -> list[str]:
    """Virgülsüz uzun parçayı sözcük sınırlarından dengeli böler (her parça ≤ max_words)."""
    tokens = parca.split()
    adet = max(1, math.ceil(len(tokens) / max_words))
    boy = math.ceil(len(tokens) / adet)
    return [" ".join(tokens[i:i + boy]) for i in range(0, len(tokens), boy)]


def _uzunu_bol(cumle: str, max_words: int, min_words: int) -> list[str]:
    """Uzun cümleyi virgül/noktalı virgülden parçalara böler; küçük artıkları öncekine ekler."""
    if _sozcuk_sayisi(cumle) <= max_words:
        return [cumle]
    atomlar: list[str] = []
    for p in re.split(r"(?<=[,;:])\s+", cumle):
        if not p.strip():
            continue
        if _sozcuk_sayisi(p) > max_words:
            atomlar.extend(_sozcuklerden_bol(p, max_words))
        else:
            atomlar.append(p.strip())
    gruplar: list[list[str]] = []
    cur: list[str] = []
    cur_n = 0
    for a in atomlar:
        n = _sozcuk_sayisi(a)
        if cur and cur_n + n > max_words:
            gruplar.append(cur)
            cur, cur_n = [], 0
        cur.append(a)
        cur_n += n
    if cur:
        gruplar.append(cur)
    parcalar = [" ".join(g) for g in gruplar]
    birlesik: list[str] = []
    for p in parcalar:
        if birlesik and _sozcuk_sayisi(p) < min_words:
            birlesik[-1] = f"{birlesik[-1]} {p}"
        else:
            birlesik.append(p)
    if len(birlesik) >= 2 and _sozcuk_sayisi(birlesik[0]) < min_words:
        birlesik[1] = f"{birlesik[0]} {birlesik[1]}"
        del birlesik[0]
    return [_noktala(p) for p in birlesik]


def split_sentences(text: str, *, min_words: int = MIN_SOZCUK, max_words: int = MAX_SOZCUK,
                    min_sentence_words: int = MIN_CUMLE_SOZCUK) -> list[str]:
    """Serbest metni kayıt satırlarına böler.

    * Cümle sonu: ``. ! ? …`` (+ kapanış tırnağı/parantezi) ve ardından boşluk. Kısaltmalardan ("Dr.", "vb.",
      "T.C.", "A." gibi tek harf, "3." gibi 1–2 basamaklı sıra sayısı) ve küçük harfle süren yerlerden
      ("Gel!" dedi, "belki... sonra") bölünmez.
    * ``max_words``'ten uzun cümleler virgül/noktalı virgülden parçalanır; virgül yoksa sözcük sınırından.
      Ara parçaların sonundaki virgül atılır ve nokta konur.
    * Virgülden bölünen parçalardan ``min_words``'ten (4) kısa olanlar komşusuna eklenir; tam cümlelerden
      ``min_sentence_words``'ten (2) kısa olanlar ("Evet.", "Hayır!") bir öncekine (ilk cümleyse sonrakine)
      eklenir. Böylece "Dr. Ayşe geldi. Sonra gitti." iki satır kalır; tek sözcüklük tepki ayrı kayıt olmaz.
    * Paragraflar boş satırla ayrılır; noktalaması olmayan ≤ 5 sözcüklük paragraf (başlık) atlanır; satır başındaki
      diyalog çizgisi atılır.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    birimler: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        if not _SON_RE.search(para) and _sozcuk_sayisi(para) <= 5:
            continue                                  # başlık / bölüm adı
        for ham in _ham_cumleler(para):
            ham = re.sub(r"^[\-–—]+\s*", "", ham).strip()
            if not ham or not _SOZCUK_RE.search(ham):
                continue
            birimler.extend(_uzunu_bol(ham, max_words, min_words))
    sonuc: list[str] = []
    for b in birimler:
        if sonuc and _sozcuk_sayisi(b) < min_sentence_words:
            sonuc[-1] = f"{sonuc[-1]} {b}"
        else:
            sonuc.append(b)
    if len(sonuc) >= 2 and _sozcuk_sayisi(sonuc[0]) < min_sentence_words:
        sonuc[1] = f"{sonuc[0]} {sonuc[1]}"
        del sonuc[0]
    return [_noktala(s) for s in sonuc]


# ---------- manifest ----------

def yogunluklar(tekrar: int) -> tuple[str, ...]:
    """Tekrar sayısına göre yoğunluk dizisi: 1 → normal; 2 → hafif, güçlü; 3 → hafif, normal, güçlü; fazlası döner."""
    tekrar = max(1, int(tekrar))
    if tekrar == 1:
        return ("normal",)
    if tekrar == 2:
        return ("hafif", "güçlü")
    return tuple(YOGUNLUK_SIRASI[i % 3] for i in range(tekrar))


def secili_duygular(bank: dict, duygular=None) -> tuple[list[str], list[str]]:
    """İstenen duyguları bankadaki adlara eşler → (bulunanlar, bulunamayanlar). None → tüm banka."""
    if duygular is None:
        return list(bank), []
    if isinstance(duygular, str):
        duygular = duygular.split(",")
    istenen = [tr_lower(d).strip() for d in duygular if d and d.strip()]
    katlanmis = {_fold(k): k for k in bank}
    bulunan: list[str] = []
    yok: list[str] = []
    for d in istenen:
        k = d if d in bank else katlanmis.get(_fold(d))
        if k is None:
            yok.append(d)
        elif k not in bulunan:
            bulunan.append(k)
    return bulunan, yok


def _id(duygu: str, n: int) -> str:
    """Kayıt adı: "mutlu_0007" (duygu adındaki boşluk/işaretler alt çizgiye çevrilir)."""
    ad = re.sub(r"\W+", "_", duygu).strip("_") or "duygu"
    return ad + "_" + format(n, "04d")


def build_manifest(bank: dict, *, tekrar: int = 1, duygular=None, ek_metin=None) -> list[dict]:
    """Kayıt satırlarını üretir: [{"id": "mutlu_0007", "duygu", "yogunluk", "metin", "yonerge", "ornek"}, …].

    * id: duygu başına 4 haneli sıra; ``tekrar=2`` ile aynı cümle hafif/güçlü iki AYRI satır ve iki ayrı id olur.
    * ``normal`` duygu yoğunluk taşımaz: tekrar ne olursa olsun tek satır (yoğunluk "normal").
    * ``duygular``: ad listesi ya da "mutlu,üzgün" dizesi; bankada olmayanlar atlanır (bkz. ``secili_duygular``).
    * ``ek_metin``: serbest metin (``split_sentences`` ile bölünür) ya da hazır cümle listesi; ``normal`` duyguya,
      bankadaki normal cümlelerin ardına eklenir (bankada normal yoksa varsayılan yönergeyle açılır).
    """
    secili, _ = secili_duygular(bank, duygular)
    ek: list[str] = []
    if ek_metin:
        ek = split_sentences(ek_metin) if isinstance(ek_metin, str) else [str(s).strip() for s in ek_metin if str(s).strip()]
    sayac: dict[str, int] = {}
    satirlar: list[dict] = []

    def ekle(duygu: str, metin: str, yog: str, yonerge: str, ornek: str) -> None:
        sayac[duygu] = sayac.get(duygu, 0) + 1
        satirlar.append({"id": _id(duygu, sayac[duygu]), "duygu": duygu, "yogunluk": yog,
                         "metin": _temiz_metin(metin), "yonerge": yonerge, "ornek": ornek})

    for duygu in secili:
        d = bank[duygu]
        yog_dizi = ("normal",) if duygu == "normal" else yogunluklar(tekrar)
        for cumle in d["cumleler"]:
            for yog in yog_dizi:
                ekle(duygu, cumle, yog, d.get("yonerge", ""), d.get("ornek", ""))
    if ek:
        normal = bank.get("normal", {})
        yonerge = normal.get("yonerge") or VARSAYILAN_YONERGE
        for cumle in ek:
            ekle("normal", cumle, "normal", yonerge, normal.get("ornek", ""))
    return satirlar


# ---------- oturum planı ----------

def _gruplar(manifest: list[dict]) -> list[tuple[str, list[dict]]]:
    """Satırları duyguya göre (ilk görülme sırasıyla) toplar."""
    sira: dict[str, list[dict]] = {}
    for r in manifest:
        sira.setdefault(r["duygu"], []).append(r)
    return list(sira.items())


def _dengeli_parcala(rows: list[dict], en_cok: int) -> list[list[dict]]:
    """Listeyi her biri ≤ en_cok olan, boyları dengeli parçalara böler."""
    if len(rows) <= en_cok:
        return [rows]
    adet = math.ceil(len(rows) / en_cok)
    boy = math.ceil(len(rows) / adet)
    return [rows[i:i + boy] for i in range(0, len(rows), boy)]


def plan_sessions(manifest: list[dict], oturum: int | None = None, max_per_session: int = OTURUM_SATIR) -> list[list[dict]]:
    """Satırları oturumlara böler → [[satır, …], …]. Duygular bir oturumda bir arada kalır (oyuncu duygu değiştirmesin).

    * ``oturum=None``: her oturum en çok ``max_per_session`` satır; bir duygu sınırı aşarsa dengeli ikiye (üçe…)
      bölünür ve oturumlar sırayla doldurulur.
    * ``oturum=N``: tam N oturuma, satır sayısı olabildiğince eşit olacak biçimde; kesme noktaları duygu
      sınırlarına çekilir, uygun sınır yoksa (sapma hedefin %20'sinden fazla) duygu içinden kesilir.
      ``max_per_session`` bu kipte uygulanmaz (çağıran uyarır).
    """
    toplam = len(manifest)
    if toplam == 0:
        return []
    gruplar = _gruplar(manifest)
    if oturum is None:
        en_cok = max(1, int(max_per_session))
        bloklar: list[list[dict]] = []
        for _, rows in gruplar:
            bloklar.extend(_dengeli_parcala(rows, en_cok))
        oturumlar: list[list[dict]] = []
        cur: list[dict] = []
        for b in bloklar:
            if cur and len(cur) + len(b) > en_cok:
                oturumlar.append(cur)
                cur = []
            cur.extend(b)
        if cur:
            oturumlar.append(cur)
        return oturumlar
    n = max(1, min(int(oturum), toplam))
    duz = [r for _, rows in gruplar for r in rows]       # duygular bitişik
    if n == 1:
        return [duz]
    sinirlar: list[int] = []
    biriken = 0
    for _, rows in gruplar[:-1]:
        biriken += len(rows)
        sinirlar.append(biriken)
    hedef = toplam / n
    tolerans = max(2.0, 0.2 * hedef)
    kesimler: list[int] = []
    onceki = 0
    for i in range(1, n):
        ideal = i * toplam / n
        ust = toplam - (n - i)                           # kalan her oturuma en az bir satır kalsın
        adaylar = [s for s in sinirlar if onceki < s <= ust]
        en_yakin = min(adaylar, key=lambda s: abs(s - ideal)) if adaylar else None
        if en_yakin is not None and abs(en_yakin - ideal) <= tolerans:
            kesim = en_yakin
        else:
            kesim = min(max(int(round(ideal)), onceki + 1), ust)
        kesimler.append(kesim)
        onceki = kesim
    oturumlar = []
    bas = 0
    for k in kesimler + [toplam]:
        oturumlar.append(duz[bas:k])
        bas = k
    return [o for o in oturumlar if o]


# ---------- çıktı dosyaları ----------

HATIRLATMA = (
    "**Sessiz oda:** klima, vantilatör ve buzdolabı kapalı; kapı-pencere kapalı; telefon uçak modunda.",
    "**Mikrofon ağızdan 15–20 cm**, hafifçe yanda (pop filtresi varsa takın); mesafeyi oturum boyunca değiştirmeyin.",
    "**Su:** yanınızda oda sıcaklığında su bulundurun; ses yorulmadan, yaklaşık her 40 cümlede kısa mola verin.",
    "**Her cümleden sonra 1 saniye sessiz bekleyin;** cümleleri birbirine bağlamayın (kesme için gerekir).",
    "**Hata olursa** durun, kısa bir sessizlikten sonra cümleyi baştan okuyun; yarım kalanı silmeyin, temiz olanı seçin.",
)
YOGUNLUK_NOTU = ("**Yoğunluk:** *hafif* = duyguyu belli belirsiz, günlük konuşma dozunda verin; "
                 "*güçlü* = duyguyu tam gücüyle verin, ama karikatürleştirmeden (bağırmadan, ağlamaklı taklit yapmadan).")


def _duygu_sayim(rows: list[dict]) -> list[tuple[str, int]]:
    return [(d, len(r)) for d, r in _gruplar(rows)]


def _oturum_md(rows: list[dict], no: int, toplam_oturum: int, kisi: str | None, devam: str | None) -> str:
    """Bir oturumun okuma senaryosu (Markdown)."""
    n = len(rows)
    kayit_dk = _dk(n * (SN_CUMLE + SN_ARA))
    ses_dk = _dk(n * SN_CUMLE)
    dagilim = ", ".join(f"{d} ({k})" for d, k in _duygu_sayim(rows))
    satirlar = [f"# Kayıt senaryosu — Oturum {no} / {toplam_oturum}", ""]
    if kisi:
        satirlar.append(f"**Kişi:** {kisi}  ")
    satirlar += [
        f"**Satır:** {n} · **Duygular:** {dagilim} · **Tahmini süre:** ~{kayit_dk} dk (ses {ses_dk} dk + aralar)",
        "",
        "## Kayıt hatırlatması",
        "",
    ]
    satirlar += [f"{i}. {h}" for i, h in enumerate(HATIRLATMA, 1)]
    satirlar += [
        "",
        "Her satır **ayrı bir dosya** olarak, köşeli parantezdeki adla kaydedilir (örn. `mutlu_0007.wav`); sıralı "
        "liste `kayit_listesi.txt` dosyasındadır. Satırı okumadan önce bir kez için için okuyun, sonra birine "
        "anlatır gibi söyleyin. Ayrıntılar: `docs/KAYIT_REHBERI.md`.",
        "",
    ]
    sira = 0
    for duygu, drows in _gruplar(rows):
        baslik = f"## Duygu: {duygu}"
        if devam == duygu:
            baslik += " (devam)"
        satirlar += [baslik, ""]
        yonerge = drows[0].get("yonerge") or (VARSAYILAN_YONERGE if duygu == "normal" else "")
        ornek = drows[0].get("ornek") or ""
        if yonerge:
            satirlar.append(f"**Yönerge:** {yonerge}  ")
        if ornek:
            satirlar.append(f"**Örnek:** {ornek}  ")
        if any(r["yogunluk"] != "normal" for r in drows):
            satirlar.append(YOGUNLUK_NOTU)
        satirlar.append("")
        for r in drows:
            sira += 1
            yog = f" ({r['yogunluk']})" if r["yogunluk"] != "normal" else ""
            satirlar.append(f"{sira}. [{r['id']}]{yog} {r['metin']}")
        satirlar.append("")
    return "\n".join(satirlar).rstrip() + "\n"


def _ozet_md(sessions: list[list[dict]], kisi: str | None, max_per_session: int) -> str:
    """OZET.md: toplam, duygu dağılımı, süre tahmini, oturumlar ve 3 saat hesabı."""
    rows = [r for s in sessions for r in s]
    toplam = len(rows)
    benzersiz_hepsi = {(r["duygu"], _normalize_cumle(r["metin"])) for r in rows}
    ses_sn = toplam * SN_CUMLE
    kayit_sn = toplam * (SN_CUMLE + SN_ARA)
    hedef_sn = HEDEF_SAAT * 3600
    hedef_satir = math.ceil(hedef_sn / SN_CUMLE)
    zorunlu_satir = math.ceil(ZORUNLU_DK * 60 / SN_CUMLE)
    eksik = max(0, hedef_satir - toplam)
    out = ["# Kayıt senaryosu — özet", ""]
    if kisi:
        out.append(f"**Kişi:** {kisi}  ")
    out += [
        f"**Toplam satır:** {toplam} ({len(benzersiz_hepsi)} benzersiz cümle) · **Duygu:** {len(_gruplar(rows))} · "
        f"**Oturum:** {len(sessions)}  ",
        f"**Tahmini kayıt süresi:** {_dk(kayit_sn)} dk (cümle başına {_tr_sayi(SN_CUMLE)} sn okuma + "
        f"{_tr_sayi(SN_ARA)} sn ara) · **Elde edilecek ses:** {_dk(ses_sn)} dk (aralar kırpılır)",
        "",
        "## Duygu dağılımı",
        "",
        "| Duygu | Cümle | Satır | Yoğunluk | Ses (dk) | Kayıt (dk) |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for duygu, drows in _gruplar(rows):
        benzersiz = len({_normalize_cumle(r["metin"]) for r in drows})
        yogs = [y for y in YOGUNLUK_SIRASI if any(r["yogunluk"] == y for r in drows)]
        out.append(f"| {duygu} | {benzersiz} | {len(drows)} | {', '.join(yogs)} | {_dk(len(drows) * SN_CUMLE)} | "
                   f"{_dk(len(drows) * (SN_CUMLE + SN_ARA))} |")
    out += ["", "## Oturumlar", "", "| Oturum | Satır | Duygular | Kayıt (dk) |", "|---|---:|---|---:|"]
    genis = max(2, len(str(len(sessions))))
    for i, s in enumerate(sessions, 1):
        dagilim = ", ".join(f"{d} ({k})" for d, k in _duygu_sayim(s))
        out.append(f"| oturum_{i:0{genis}d}.md | {len(s)} | {dagilim} | {_dk(len(s) * (SN_CUMLE + SN_ARA))} |")
    uzun = [i for i, s in enumerate(sessions, 1) if len(s) > max_per_session]
    if uzun:
        out += ["", f"> Uyarı: {', '.join(str(i) for i in uzun)} numaralı oturum(lar) {max_per_session} satırı aşıyor "
                    f"(≈ {_dk(max_per_session * (SN_CUMLE + SN_ARA))} dk); ses yorulur, mola planlayın."]
    yuzde = min(100.0, 100.0 * ses_sn / hedef_sn) if hedef_sn else 0.0
    out += [
        "",
        f"## {_tr_sayi(HEDEF_SAAT, 0)} saat hedefi",
        "",
        f"İnce ayar için toplam ses en az {_tr_sayi(ZORUNLU_DK, 0)} dk zorunlu, {_tr_sayi(HEDEF_SAAT, 0)} saat önerilir "
        "(docs/SOZLESME3.md §5). Süre, aralar kırpıldıktan sonraki ses süresidir "
        f"(cümle başına ~{_tr_sayi(SN_CUMLE)} sn).",
        "",
        f"- Bu senaryo: {toplam} satır ≈ {_dk(ses_sn)} dk ses (hedefe oranı: %{_tr_sayi(yuzde, 0)})"
        + ("" if ses_sn >= ZORUNLU_DK * 60 else f" — **zorunlu {_tr_sayi(ZORUNLU_DK, 0)} dk eşiğinin altında**")
        + ".",
        f"- {_tr_sayi(HEDEF_SAAT, 0)} saat için gereken satır: {hedef_satir} "
        f"({_tr_sayi(ZORUNLU_DK, 0)} dk için {zorunlu_satir}).",
    ]
    if eksik == 0:
        out.append("- Hedef karşılanıyor; ek tekrar ya da metin gerekmez.")
    else:
        out.append(f"- Eksik: {eksik} satır ≈ {_dk(eksik * SN_CUMLE)} dk ses.")
        benzersiz_duygu = {d: len({_normalize_cumle(r["metin"]) for r in drows}) for d, drows in _gruplar(rows)}
        normal_n = benzersiz_duygu.get("normal", 0)
        duygulu = sum(k for d, k in benzersiz_duygu.items() if d != "normal")

        def sayfa(cumle: int) -> int:
            return math.ceil(cumle * SOZCUK_PER_CUMLE / SOZCUK_PER_SAYFA)

        out.append(f"- Yalnızca ek metinle: `--metin` ile yaklaşık {eksik} cümle "
                   f"(≈ {eksik * SOZCUK_PER_CUMLE} sözcük, ≈ {sayfa(eksik)} kitap sayfası) ekleyin.")
        if duygulu:
            yeten = next((t for t in (2, 3) if normal_n + t * duygulu >= hedef_satir), None)
            if yeten is not None:
                out.append(f"- Yalnızca tekrarla: `--tekrar {yeten}` → {normal_n + yeten * duygulu} satır; hedef "
                           "karşılanır (normal duygu tekrarlanmaz).")
            else:
                for t in (2, 3):
                    satir_t = normal_n + t * duygulu
                    kalan = max(0, hedef_satir - satir_t)
                    out.append(f"- `--tekrar {t}` → {satir_t} satır; kalan {kalan} cümle için ek metin "
                               f"(≈ {sayfa(kalan)} sayfa).")
                out.append("- Tekrar tek başına yetmez: 3'ten fazla tekrar aynı cümleyi aynı yoğunlukta yeniden "
                           "okutur, çeşitlilik düşer. Bankaya cümle eklemek ya da kitap metni okumak daha iyidir.")
    return "\n".join(out).rstrip() + "\n"


def write_scripts(sessions: list[list[dict]], out_dir: str | Path, kisi: str | None = None,
                  max_per_session: int = OTURUM_SATIR) -> list[Path]:
    """Oturum senaryolarını, manifest.csv, OZET.md ve kayit_listesi.txt dosyalarını yazar → yazılan yollar."""
    klasor = Path(out_dir)
    klasor.mkdir(parents=True, exist_ok=True)
    yazilan: list[Path] = []
    genis = max(2, len(str(len(sessions))))
    onceki_son: str | None = None
    for i, rows in enumerate(sessions, 1):
        devam = onceki_son if rows and rows[0]["duygu"] == onceki_son else None
        path = klasor / f"oturum_{i:0{genis}d}.md"
        path.write_text(_oturum_md(rows, i, len(sessions), kisi, devam), encoding="utf-8")
        yazilan.append(path)
        onceki_son = rows[-1]["duygu"] if rows else None
    rows = [r for s in sessions for r in s]
    manifest = klasor / "manifest.csv"
    manifest.write_text("id|duygu|yogunluk|metin\n" + "".join(
        f"{r['id']}|{r['duygu']}|{r['yogunluk']}|{_temiz_metin(r['metin'])}\n" for r in rows), encoding="utf-8")
    yazilan.append(manifest)
    ozet = klasor / "OZET.md"
    ozet.write_text(_ozet_md(sessions, kisi, max_per_session), encoding="utf-8")
    yazilan.append(ozet)
    liste = klasor / "kayit_listesi.txt"
    liste.write_text("".join(f"{r['id']}\n" for r in rows), encoding="utf-8")
    yazilan.append(liste)
    return yazilan


# ---------- komut satırı ----------

def _metin_oku(path: Path) -> str:
    """Kullanıcı metnini okur: UTF-8 (BOM'lu olabilir); olmazsa Windows Türkçe (cp1254) denenir."""
    ham = path.read_bytes()
    try:
        return ham.decode("utf-8-sig")
    except UnicodeDecodeError:
        print(f"Uyarı: {path} UTF-8 değil; cp1254 (Windows Türkçe) olarak okunuyor.", file=sys.stderr)
        return ham.decode("cp1254", errors="replace")


def _arg_ayristirici() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="senaryo.py",
        description="Cümle bankasından kayıt senaryoları, manifest.csv ve özet üretir (SesKlon ince ayarı).")
    p.add_argument("--cikti", default="senaryo", help="çıktı klasörü (varsayılan: senaryo/)")
    p.add_argument("--banka", default=str(Path(__file__).resolve().parent / "cumleler"),
                   help="cümle bankası klasörü (varsayılan: finetune/cumleler)")
    p.add_argument("--oturum", type=int, default=None, help="oturum sayısı (verilmezse her oturum ≤ 120 satır)")
    p.add_argument("--metin", default=None, help="kendi metniniz (kitap, senaryo); cümlelere bölünüp 'normal' duyguya eklenir")
    p.add_argument("--duygular", default=None, help="yalnızca bu duygular, virgülle: mutlu,üzgün")
    p.add_argument("--tekrar", type=int, default=1, help="her cümle kaç yoğunlukta okunacak (2 → hafif + güçlü)")
    p.add_argument("--kontrol", action="store_true", help="bankayı denetle ve çık (HATA varsa çıkış kodu 1)")
    p.add_argument("--kisi", default=None, help="kayıt yapan kişinin adı (senaryo başlığına yazılır)")
    return p


def main(argv: list[str] | None = None) -> int:
    """Komut satırı girişi → çıkış kodu (0 başarı, 1 sorun)."""
    args = _arg_ayristirici().parse_args(argv)
    banka_yolu = Path(args.banka)
    if args.kontrol:
        sorunlar = check_bank(banka_yolu)
        hatalar = [s for s in sorunlar if s.startswith("HATA")]
        uyarilar = [s for s in sorunlar if not s.startswith("HATA")]
        for s in sorunlar:
            print(s)
        dosya_sayisi = len(list(banka_yolu.glob("*.txt"))) if banka_yolu.is_dir() else 0
        print(f"Banka denetimi: {dosya_sayisi} dosya, {len(hatalar)} hata, {len(uyarilar)} uyarı.")
        return 1 if hatalar else 0
    if args.tekrar < 1:
        print("Hata: --tekrar en az 1 olmalı.", file=sys.stderr)
        return 1
    if args.oturum is not None and args.oturum < 1:
        print("Hata: --oturum en az 1 olmalı.", file=sys.stderr)
        return 1
    try:
        banka = load_bank(banka_yolu)
    except ValueError as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 1
    ek_metin = None
    if args.metin:
        metin_yolu = Path(args.metin)
        if not metin_yolu.is_file():
            print(f"Hata: metin dosyası bulunamadı: {metin_yolu}", file=sys.stderr)
            return 1
        ek_metin = split_sentences(_metin_oku(metin_yolu))
        if not ek_metin:
            print(f"Uyarı: {metin_yolu} içinde cümle bulunamadı.", file=sys.stderr)
    if not banka and not ek_metin:
        print(f"Hata: cümle bankası boş ya da yok: {banka_yolu} (bkz. docs/SOZLESME3.md §4).", file=sys.stderr)
        return 1
    if banka:
        sorunlar = check_bank(banka_yolu)
        hata_sayisi = sum(1 for s in sorunlar if s.startswith("HATA"))
        if hata_sayisi:
            print(f"Uyarı: bankada {hata_sayisi} hata var (ayrıntı için --kontrol); senaryo yine de üretiliyor.",
                  file=sys.stderr)
    secili, bilinmeyen = secili_duygular(banka, args.duygular)
    if bilinmeyen:
        print(f"Uyarı: bankada olmayan duygu(lar) atlandı: {', '.join(bilinmeyen)}. "
              f"Bankadakiler: {', '.join(banka) or '—'}", file=sys.stderr)
    if args.duygular is not None and not secili and not ek_metin:
        print("Hata: --duygular ile seçilen hiçbir duygu bankada yok.", file=sys.stderr)
        return 1
    manifest = build_manifest(banka, tekrar=args.tekrar, duygular=args.duygular, ek_metin=ek_metin)
    if not manifest:
        print("Hata: üretilecek satır yok (banka dosyaları boş olabilir).", file=sys.stderr)
        return 1
    oturumlar = plan_sessions(manifest, oturum=args.oturum)
    dosyalar = write_scripts(oturumlar, args.cikti, kisi=args.kisi)
    toplam = len(manifest)
    print(f"Senaryo yazıldı: {len(oturumlar)} oturum, {toplam} satır, {len(_gruplar(manifest))} duygu → {args.cikti}")
    for path, rows in zip(dosyalar, oturumlar):
        print(f"  {path} ({len(rows)} satır, ~{_dk(len(rows) * (SN_CUMLE + SN_ARA))} dk)")
    print("  " + ", ".join(str(p) for p in dosyalar[len(oturumlar):]))
    print(f"Tahmini kayıt süresi: {_dk(toplam * (SN_CUMLE + SN_ARA))} dk; elde edilecek ses: "
          f"{_dk(toplam * SN_CUMLE)} dk. {_tr_sayi(HEDEF_SAAT, 0)} saat hedefi için bkz. OZET.md.")
    if args.oturum is not None and any(len(o) > OTURUM_SATIR for o in oturumlar):
        print(f"Uyarı: bazı oturumlar {OTURUM_SATIR} satırı aşıyor; mola planlayın ya da --oturum değerini artırın.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
