#!/usr/bin/env python3
"""İnce ayar verisi hazırlama — kayıtlardan LJSpeech biçiminde eğitim kümesi (SOZLESME3 §5).

Kayıt masasında ``senaryo.py``'nin ürettiği manifestle okunan kayıtları (ya da ``kayitlar/*.wav`` + aynı adlı
``.txt`` transkriptleri) ``gokhaneraslan/chatterbox-finetuning`` deposunun beklediği biçime çevirir:

* ``MyTTSDataset/wavs/<id>.wav`` — mono, ``--sr`` (varsayılan 24 kHz), PCM16; baş-son sessizlik kırpılmış
* ``MyTTSDataset/metadata.csv`` — ``filename|raw_text|normalized_text`` (başlıksız, UTF-8, ``filename`` uzantısız)
* ``MyTTSDataset/metadata_val.csv`` — ``--dogrulama`` oranında, duygu başına dengeli doğrulama ayrımı
* ``MyTTSDataset/rapor.json`` — toplam süre, duygu başına dakika ve ifade ölçümü, reddedilenler, yeterlilik

Kullanım::

    python finetune/hazirla.py --kayitlar kayitlar/ --manifest senaryo/manifest.csv --cikti MyTTSDataset \\
        [--sr 24000] [--etiket] [--dogrulama 0.05] [--min-snr 20] [--max-sn 12] [--boleme --transkriptsiz]

Adımlar (hepsi ``app`` modülleriyle):

1. Oku: soundfile; okuyamazsa ffmpeg ile geçici WAV (``app.audio.to_wav``). Mono'ya indir, ``--sr``'ye yeniden
   örnekle (``app.audio.resample``), DC kaymasını gider.
2. Kırp: ``app.audio.trim_silence`` (−45 dB, 40 ms pay) → çıktı sinyali. Ölçüm için aynı kırpma 400 ms payla
   yapılır: gürültü tabanı (SNR) kaydın başındaki/sonundaki oda tonundan ölçülebilsin diye. Sıkı kırpılmış kısa
   bir cümlede taban konuşmanın içinden ölçülür ve temiz kayıt yanlışlıkla "gürültülü" çıkar.
3. Denetle (``app.analysis.analyze_array``, ölçekleme ÖNCESİ sinyalde — kırpılma görünür kalsın):
   SNR < ``--min-snr`` → "gürültülü"; kırpılma oranı > 0,001 → "kırpılmış"; süre < 1 sn → "çok kısa";
   süre > ``--max-sn`` → "uzun"; konuşma oranı < 0,3 → "konuşma az". Reddedilen kayıt çıktıya kopyalanmaz.
4. Tepe > 0,99 ise sinyal 0,95 tepeye ölçeklenir; PCM16 yazılır.
5. Metin: raw_text = manifest metni (boşluklar sadeleşir, ``|`` boşluğa döner); normalized_text =
   ``app.textnorm.normalize(raw_text)``. ``--etiket`` ile duygu ``normal`` değilse iki sütunun başına
   ``[duygu] `` eklenir — normalize SONRASI (normalize köşeli parantezli etiketi siler).
6. ``--boleme --transkriptsiz`` birlikte verilirse 10 sn'den uzun kayıtlar sessizliklerden 3–10 sn parçalara
   bölünür (``<id>_01``, ``<id>_02`` …). Metni olmayan klipler ``metadata.csv``'ye YAZILMAZ (eğitim deposu
   pandas ile okur; boş alan NaN → "nan" metniyle eğitilirdi): ``metadata_transkriptsiz.csv``'ye ``ad||``
   satırları olarak gider; kullanıcı Whisper ile doldurup ``metadata.csv``'ye ekler. Aksi hâlde bölme yapılmaz: metni olan uzun kaydın hangi sözcüğünün hangi parçaya düştüğü
   bilinemez, o kayıt "uzun" diye reddedilir.

Manifest biçimi (``senaryo.py`` çıktısı): başlık ``id|duygu|yogunluk|metin``, ayırıcı ``|``, tırnaklama yok;
``id`` kayıt dosyasının uzantısız adıdır (``üzgün_0012``). macOS Türkçe karakterli dosya adlarını NFD yazar;
``find_recording`` NFC ve NFD adları (ve büyük/küçük harf farkını, ``app.tr.tr_lower`` ile) eşler.
Yalnızca sayıdan oluşan adlar (``0001.wav``; pandas bunları tamsayı okur ve ``1.wav`` arar) çıktıda
``kayit_0001`` olur; eşleme ``rapor.json → id_eslemesi``'nde.

Çıkış kodu: 0 başarı, 1 hata (klasör/manifest yok ya da bozuk), 2 hiçbir kayıt kabul edilmedi.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.analysis import analyze_array  # noqa: E402  (yol yukarıda eklenir)
from app.audio import cut_at_silence, resample, to_wav, trim_silence  # noqa: E402
from app.textnorm import normalize  # noqa: E402
from app.tr import tr_lower  # noqa: E402

# ---------- sabitler ----------

SES_UZANTILARI = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aiff", ".aif")
MANIFEST_BASLIK = ("id", "duygu", "yogunluk", "metin")
YOGUNLUKLAR = ("normal", "hafif", "güçlü")
ID_RE = re.compile(r"^[a-zçğıöşü]+_\d{4}$")
GUVENSIZ_ID_RE = re.compile(r"[/\\|\x00-\x1f]|^\.|^$")

KIRPMA_DB = -45.0            # trim_silence eşiği (dBFS)
KIRPMA_PAY_MS = 40           # çıktıda baş/sonda bırakılan pay
OLCUM_PAY_MS = 400           # ölçüm penceresinde bırakılan oda tonu (SNR tabanı için)
KIRPILMA_ESIK = 0.001        # |x| ≥ 0,985 örnek oranı bunu aşarsa "kırpılmış"
EN_KISA_SN = 1.0
KONUSMA_ORANI_ESIK = 0.3
TEPE_SINIR = 0.99            # tepe bunu aşarsa …
TEPE_HEDEF = 0.95            # … bu seviyeye ölçeklenir
BOLME_EN_KISA_SN = 3.0
BOLME_EN_UZUN_SN = 10.0
DUZ_ARALIK_ST = 12.0         # duygu başına medyan perde aralığı bunun altındaysa "düz okunmuş" uyarısı
ZORUNLU_DK = 30.0
ONERILEN_SAAT = 3.0
TRANSKRIPTSIZ_DOSYA = "metadata_transkriptsiz.csv"
TRANSKRIPTSIZ_TALIMAT = (
    "{n} klibin ({dk} dk) metni yok; bunlar metadata.csv'ye YAZILMADI (boş metin eğitimde 'nan' olarak okunur). "
    "metadata_transkriptsiz.csv dosyasındaki 'ad||' satırlarını Whisper ile doldurun (ad|ham metin|normalize metin), "
    "sonra metadata.csv'ye ekleyin.")
TOHUM = 1234                 # doğrulama ayrımı için sabit tohum (tekrar üretilebilir)

NEDENLER = ("gürültülü", "kırpılmış", "çok kısa", "uzun", "konuşma az")


# ---------- küçük yardımcılar ----------

def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _anahtar(s: str) -> str:
    """Dosya adı eşleme anahtarı: NFC + Türkçe küçük harf (NFD'de "İ" = "I" + nokta; önce NFC şart)."""
    return tr_lower(_nfc(s))


def _tr_sayi(x: float, basamak: int = 1) -> str:
    """Türkçe ondalık ayırıcı: 3.5 → "3,5"."""
    return f"{x:.{basamak}f}".replace(".", ",")


def _temiz_metin(s: str) -> str:
    """Metadata alanı: tek satır, ``|`` yok, tek boşluk."""
    return re.sub(r"\s+", " ", (s or "").replace("|", " ")).strip()


def _duygu_adi(s: str) -> str:
    return _anahtar((s or "").strip()) or "normal"


# pandas'ın sayı/boş/mantıksal sanacağı adlar: eğitim deposu metadata'yı pandas ile okur; "0001" tamsayı 1 olur
# ve ön işleme "1.wav" arayıp kaydı sessizce atlar, "nan"/"null" ise boş (NaN) okunur.
_PANDAS_SAYI_RE = re.compile(r"^[0-9.eE+\-]+$")
_PANDAS_OZEL = frozenset("""
nan -nan na n/a null none true false inf -inf +inf infinity -infinity #n/a #n/a n/a #na -1.#ind -1.#qnan
1.#ind 1.#qnan <na>
""".split())
ID_ONEK = "kayit_"


def pandas_tuzagi_mi(kid: str) -> bool:
    """Ad, pandas ``read_csv`` tarafından metin olarak değil sayı/NaN/mantıksal olarak okunur mu?"""
    k = kid.strip()
    if _PANDAS_SAYI_RE.match(k) and any(c.isdigit() for c in k):
        return True
    return _anahtar(k) in _PANDAS_OZEL


def _duygu_from_ad(ad: str) -> str:
    """``mutlu_0007`` → ``mutlu``; kalıba uymayan adlar ``normal``."""
    a = _anahtar(ad)
    return a.rsplit("_", 1)[0] if ID_RE.match(a) else "normal"


# ---------- manifest ve dosya bulma ----------

def read_manifest(path: str | Path) -> list[dict]:
    """``id|duygu|yogunluk|metin`` manifestini okur → [{"id", "duygu", "yogunluk", "metin"}, …].

    Başlık zorunludur (BOM'a tolerans var). Boş ve ``#`` ile başlayan satırlar atlanır. Metin ``|`` içerse bile
    bölünmez (``split("|", 3)``); tırnaklar olduğu gibi kalır. Bozuk satır, güvensiz ya da yinelenen id →
    ``ValueError`` (Türkçe mesaj, satır numarasıyla).
    """
    path = Path(path)
    try:
        satirlar = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as e:
        raise ValueError(f"{path.name}: dosya UTF-8 değil ({e.reason}, bayt {e.start})") from None
    if not satirlar:
        raise ValueError(f"{path.name}: manifest boş")
    baslik = tuple(_anahtar(p.strip()) for p in satirlar[0].split("|"))
    if baslik != MANIFEST_BASLIK:
        raise ValueError(f"{path.name}: başlık satırı 'id|duygu|yogunluk|metin' olmalı, bulunan: '{satirlar[0]}'")
    kayitlar: list[dict] = []
    gorulen: set[str] = set()
    for no, satir in enumerate(satirlar[1:], 2):
        if not satir.strip() or satir.lstrip().startswith("#"):
            continue
        parcalar = satir.split("|", 3)
        if len(parcalar) != 4:
            raise ValueError(f"{path.name} {no}. satır: 4 alan bekleniyordu (id|duygu|yogunluk|metin): '{satir}'")
        kid = _nfc(parcalar[0].strip())
        if GUVENSIZ_ID_RE.search(kid) or ".." in kid:
            raise ValueError(f"{path.name} {no}. satır: geçersiz kayıt adı '{kid}'")
        if kid in gorulen:
            raise ValueError(f"{path.name} {no}. satır: yinelenen kayıt adı '{kid}'")
        gorulen.add(kid)
        yog = _anahtar(parcalar[2].strip()) or "normal"   # normal|hafif|güçlü; eğitim çıktısını etkilemez
        kayitlar.append({"id": kid, "duygu": _duygu_adi(parcalar[1]), "yogunluk": yog,
                         "metin": _temiz_metin(parcalar[3])})
    return kayitlar


_dizin_onbellek: dict[str, tuple[int, dict[str, Path]]] = {}


def _dizin_indeksi(dizin: Path) -> dict[str, Path]:
    """Klasördeki ses dosyaları: {anahtar(ad) + uzantı: yol}; klasör değişmedikçe önbellekten."""
    try:
        damga = dizin.stat().st_mtime_ns
    except OSError:
        return {}
    kayit = _dizin_onbellek.get(str(dizin))
    if kayit and kayit[0] == damga:
        return kayit[1]
    indeks: dict[str, Path] = {}
    for p in sorted(dizin.iterdir()):
        uz = tr_lower(p.suffix)
        if uz in SES_UZANTILARI and p.is_file():
            indeks.setdefault(_anahtar(p.stem) + uz, p)
    _dizin_onbellek[str(dizin)] = (damga, indeks)
    return indeks


def find_recording(dir: str | Path, id: str) -> Path | None:  # noqa: A002 - sözleşmedeki ad
    """``<dir>/<id>.(wav|flac|mp3|m4a|ogg|aiff)`` → yol ya da None.

    Önce doğrudan yol denenir; olmazsa klasör listesi NFC + Türkçe küçük harf anahtarıyla eşlenir (macOS NFD
    dosya adları, ``Mutlu_0007.WAV`` gibi büyük harfler). Birden çok biçim varsa uzantı sırası önceliklidir.
    """
    dizin = Path(dir)
    for ad in {_nfc(id), unicodedata.normalize("NFD", id)}:
        for uz in SES_UZANTILARI:
            p = dizin / f"{ad}{uz}"
            if p.is_file():
                return p
    indeks = _dizin_indeksi(dizin)
    a = _anahtar(id)
    for uz in SES_UZANTILARI:
        p = indeks.get(a + uz)
        if p is not None:
            return p
    return None


def _txt_kayitlari(dizin: Path) -> tuple[list[dict], list[str]]:
    """Manifestsiz mod: klasördeki ses dosyaları + aynı adlı ``.txt`` → (kayıtlar, uyarılar).

    ``.txt`` yoksa metin ``None`` olur (``--transkriptsiz`` değilse kayıt "transkript yok" diye reddedilir).
    """
    uyarilar: list[str] = []
    txtler = {_anahtar(p.stem): p for p in sorted(dizin.iterdir())
              if p.is_file() and tr_lower(p.suffix) == ".txt"}
    kayitlar: list[dict] = []
    gorulen: dict[str, Path] = {}
    dosyalar = sorted((p for p in dizin.iterdir() if p.is_file() and tr_lower(p.suffix) in SES_UZANTILARI),
                      key=lambda p: (_anahtar(p.stem), SES_UZANTILARI.index(tr_lower(p.suffix))))
    for p in dosyalar:
        kid = _nfc(p.stem)
        a = _anahtar(kid)
        if a in gorulen:
            uyarilar.append(f"{p.name} atlandı: aynı adlı {gorulen[a].name} zaten kullanılıyor.")
            continue
        gorulen[a] = p
        txt = txtler.get(a)
        metin = None
        if txt is not None:
            try:
                metin = _temiz_metin(txt.read_text(encoding="utf-8-sig"))
            except UnicodeDecodeError:
                uyarilar.append(f"{txt.name} UTF-8 değil; transkript okunamadı.")
        kayitlar.append({"id": kid, "duygu": _duygu_from_ad(kid), "yogunluk": "normal", "metin": metin,
                         "yol": p})
    return kayitlar, uyarilar


# ---------- ses ----------

def load_audio(path: str | Path, sr: int = 24000) -> np.ndarray:
    """Ses dosyasını okur → mono float32, ``sr`` örnekleme hızında (ölçekleme yapılmaz; kırpılma görünür kalır).

    soundfile okuyamazsa (m4a vb.) ffmpeg ile geçici WAV'a çevrilir (``app.audio.to_wav``). Okunamazsa
    ``ValueError``.
    """
    path = Path(path)
    try:
        data, dosya_sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001 - biçim desteklenmiyor → ffmpeg
        try:
            with tempfile.TemporaryDirectory() as td:
                gecici = Path(td) / "gecici.wav"
                to_wav(path, gecici, sr)
                data, dosya_sr = sf.read(str(gecici), dtype="float32", always_2d=True)
        except Exception as e:  # noqa: BLE001 - kullanıcıya anlaşılır hata
            raise ValueError(f"ses dosyası okunamadı: {path.name}") from e
    wav = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    return resample(wav, int(dosya_sr), int(sr)).astype(np.float32)


def check_clip(wav: np.ndarray, sr: int, analysis: dict, max_s: float, min_snr: float) -> str | None:
    """Klip eğitim verisine uygun mu? → None (uygun) ya da red nedeni (``NEDENLER``'den biri).

    Süre ``wav``'dan (kırpılmış çıktı sinyali), diğerleri ``analysis``'ten (``analyze_array`` sonucu) okunur.
    Sıra: süre, kırpılma, gürültü, konuşma oranı (gürültülü kayıtta konuşma oranı da düşer; asıl neden gürültü).
    """
    sure = len(wav) / float(sr) if sr else 0.0
    if sure < EN_KISA_SN:
        return "çok kısa"
    if sure > max_s:
        return "uzun"
    if float(analysis.get("clipping_ratio", 0.0)) > KIRPILMA_ESIK:
        return "kırpılmış"
    if float(analysis.get("snr_db", 0.0)) < min_snr:
        return "gürültülü"
    if float(analysis.get("speech_ratio", 0.0)) < KONUSMA_ORANI_ESIK:
        return "konuşma az"
    return None


def _ayrinti(neden: str, sure: float, a: dict, max_s: float, min_snr: float) -> str:
    """Red nedeninin sayısal açıklaması (rapora)."""
    if neden == "çok kısa":
        return f"{_tr_sayi(sure, 2)} sn < {_tr_sayi(EN_KISA_SN)} sn"
    if neden == "uzun":
        return f"{_tr_sayi(sure)} sn > {_tr_sayi(max_s)} sn"
    if neden == "kırpılmış":
        return f"kırpılan örnek oranı %{_tr_sayi(100 * float(a.get('clipping_ratio', 0)), 2)} (sınır %0,1)"
    if neden == "gürültülü":
        return f"SNR {_tr_sayi(float(a.get('snr_db', 0)))} dB < {_tr_sayi(min_snr)} dB"
    if neden == "konuşma az":
        return f"konuşma oranı {_tr_sayi(float(a.get('speech_ratio', 0)), 2)} < {_tr_sayi(KONUSMA_ORANI_ESIK)}"
    return ""


def _bol(wav: np.ndarray, sr: int) -> list[tuple[int, int]]:
    """Uzun sinyali sessizliklerden 3–10 sn parçalara böler → [(başlangıç, bitiş), …] örnek indeksleri.

    Her adımda kalan > 10 sn ise [3 sn, min(10, kalan − 3) sn] aralığındaki en sessiz kareden kesilir
    (``app.audio.cut_at_silence``); böylece son parça da 3 sn'den kısa kalmaz.
    """
    n = len(wav)
    sinirlar: list[tuple[int, int]] = []
    bas = 0
    while n - bas > BOLME_EN_UZUN_SN * sr:
        kalan = (n - bas) / sr
        ust = min(BOLME_EN_UZUN_SN, kalan - BOLME_EN_KISA_SN)
        arama_ms = int((ust - BOLME_EN_KISA_SN) * 1000)
        parca = cut_at_silence(wav[bas:], sr, ust, search_ms=arama_ms)
        kes = bas + max(int(BOLME_EN_KISA_SN * sr), len(parca))
        sinirlar.append((bas, kes))
        bas = kes
    sinirlar.append((bas, n))
    return sinirlar


def _olcekle(wav: np.ndarray) -> np.ndarray:
    tepe = float(np.max(np.abs(wav))) if wav.size else 0.0
    if tepe > TEPE_SINIR:
        wav = wav * (TEPE_HEDEF / tepe)
    return np.clip(wav, -1.0, 1.0).astype(np.float32)


# ---------- doğrulama ayrımı ----------

def _dogrulama_sec(kabul: list[dict], oran: float, tohum: int = TOHUM) -> set[str]:
    """Doğrulamaya ayrılacak id'ler: toplamın ``oran``'ı (en az 1, en çok N−1), duygu başına orantılı (en büyük
    kalan yöntemi), her duygu içinde sabit tohumla karıştırılarak seçilir."""
    n = len(kabul)
    if oran <= 0 or n < 2:
        return set()
    hedef = min(n - 1, max(1, round(oran * n)))
    gruplar: dict[str, list[str]] = {}
    for k in kabul:
        gruplar.setdefault(k["duygu"], []).append(k["id"])
    adlar = sorted(gruplar)
    tam = {d: hedef * len(gruplar[d]) / n for d in adlar}
    kota = {d: int(tam[d]) for d in adlar}
    kalan = hedef - sum(kota.values())
    for d in sorted(adlar, key=lambda d: (-(tam[d] - kota[d]), -len(gruplar[d]), d))[:kalan]:
        kota[d] += 1
    secilen: set[str] = set()
    for d in adlar:
        idler = sorted(gruplar[d])
        random.Random(f"{tohum}-{d}").shuffle(idler)
        secilen.update(idler[: kota[d]])
    return secilen


# ---------- ana iş ----------

def _yeterlilik(toplam_dk: float) -> str:
    if toplam_dk < ZORUNLU_DK:
        return "yetersiz (<30 dk)"
    if toplam_dk < ONERILEN_SAAT * 60:
        return "asgari (30 dk–3 sa)"
    return "iyi (≥3 sa)"


def _medyan(degerler: list[float]) -> float | None:
    return round(float(statistics.median(degerler)), 1) if degerler else None


def prepare(kayitlar: str | Path, manifest: str | Path | None, cikti: str | Path, *, sr: int = 24000,
            etiket: bool = False, dogrulama: float = 0.0, min_snr: float = 20.0, max_s: float = 12.0,
            boleme: bool = False, transkriptsiz: bool = False, ilerleme=None) -> dict:
    """Kayıtları LJSpeech kümesine çevirir, ``<cikti>/rapor.json``'u yazar ve raporu döndürür.

    ``manifest`` None ise manifestsiz mod (ses + aynı adlı ``.txt``). ``ilerleme(i, toplam, id)`` verilirse her
    kayıttan önce çağrılır. Kayıt klasörü/manifest yoksa ``FileNotFoundError``, manifest bozuksa ``ValueError``.
    """
    kdizin = Path(kayitlar)
    if not kdizin.is_dir():
        raise FileNotFoundError(f"kayıt klasörü bulunamadı: {kdizin}")
    if not 0.0 <= float(dogrulama) < 1.0:
        raise ValueError("--dogrulama 0 ile 1 arasında olmalı (örn. 0.05)")
    sr = int(sr)
    uyarilar: list[str] = []
    eksik: list[str] = []
    if manifest is not None:
        mpath = Path(manifest)
        if not mpath.is_file():
            raise FileNotFoundError(f"manifest bulunamadı: {mpath}")
        girdiler = read_manifest(mpath)
        for g in girdiler:
            g["yol"] = find_recording(kdizin, g["id"])
    else:
        girdiler, ek = _txt_kayitlari(kdizin)
        uyarilar.extend(ek)
    bol = boleme and transkriptsiz
    if boleme and not transkriptsiz:
        uyarilar.append("--boleme yalnızca --transkriptsiz ile çalışır (bölünen parçanın metni bilinemez); "
                        "bölme yapılmadı, uzun kayıtlar reddedildi.")

    cdizin = Path(cikti)
    wdizin = cdizin / "wavs"
    wdizin.mkdir(parents=True, exist_ok=True)

    kabul: list[dict] = []
    red: list[dict] = []
    id_eslemesi: dict[str, str] = {}               # pandas tuzağına düşen ad → çıktı adı ("0001" → "kayit_0001")
    tum_idler = {g["id"] for g in girdiler}

    def cikti_id(kid: str) -> str:
        """Çıktı adı: pandas'ın sayı sanacağı adların başına ``kayit_`` eklenir (çakışırsa ``_2`` …)."""
        if not pandas_tuzagi_mi(kid):
            return kid
        aday, n = ID_ONEK + kid, 2
        while aday in tum_idler or aday in id_eslemesi.values():
            aday, n = f"{ID_ONEK}{kid}_{n}", n + 1
        id_eslemesi[kid] = aday
        return aday

    def reddet(kid: str, neden: str, ayrinti: str = "") -> None:
        red.append({"id": kid, "neden": neden, "ayrinti": ayrinti})

    def denetle_ve_yaz(kid: str, girdi: dict, cikis: np.ndarray, olcum: np.ndarray, metin: str | None,
                       bolum: bool, red_adi: str | None = None) -> None:
        """``kid`` çıktı adı; ``red_adi`` reddedilirse rapora yazılacak ad (kullanıcının verdiği ad)."""
        a = analyze_array(olcum, sr)
        neden = check_clip(cikis, sr, a, max_s, min_snr)
        if neden:
            reddet(red_adi or kid, neden, _ayrinti(neden, len(cikis) / sr, a, max_s, min_snr))
            return
        if metin:
            raw = _temiz_metin(metin)
            norm = _temiz_metin(normalize(raw))
            if etiket and girdi["duygu"] != "normal":
                raw, norm = f"[{girdi['duygu']}] {raw}", f"[{girdi['duygu']}] {norm}"
        else:
            raw = norm = ""
        sf.write(str(wdizin / f"{kid}.wav"), _olcekle(cikis), sr, subtype="PCM_16")
        f0 = a.get("f0") or {}
        kabul.append({"id": kid, "duygu": girdi["duygu"], "yogunluk": girdi.get("yogunluk", "normal"),
                      "kaynak": girdi["id"], "sn": round(len(cikis) / sr, 2), "raw": raw, "norm": norm,
                      "snr_db": a.get("snr_db"), "range_semitones": f0.get("range_semitones", 0.0),
                      "std_semitones": f0.get("std_semitones", 0.0), "bolundu": bolum})

    for i, g in enumerate(girdiler):
        kid = g["id"]                                # red/eksik listelerinde kullanıcının verdiği ad
        if ilerleme:
            ilerleme(i, len(girdiler), kid)
        if g.get("yol") is None:
            eksik.append(kid)
            continue
        if g.get("metin") is None and not transkriptsiz:
            reddet(kid, "transkript yok", f"{Path(g['yol']).stem}.txt bulunamadı")
            continue
        if manifest is not None and not g.get("metin") and not transkriptsiz:
            reddet(kid, "metin boş", "manifestte metin yok")
            continue
        try:
            wav = load_audio(g["yol"], sr)
        except ValueError as e:
            reddet(kid, "okunamadı", str(e))
            continue
        if wav.size:
            wav = wav - float(np.mean(wav))          # DC kayması
        cikis = trim_silence(wav, sr, threshold_db=KIRPMA_DB, pad_ms=KIRPMA_PAY_MS)
        cid = cikti_id(kid)
        if bol and len(cikis) > BOLME_EN_UZUN_SN * sr:
            pay = int(OLCUM_PAY_MS * sr / 1000)
            for k, (b, e) in enumerate(_bol(cikis, sr), 1):
                parca = trim_silence(cikis[b:e], sr, threshold_db=KIRPMA_DB, pad_ms=KIRPMA_PAY_MS)
                olcum = cikis[max(0, b - pay): min(len(cikis), e + pay)]
                denetle_ve_yaz(f"{cid}_{k:02d}", g, parca, olcum, None, True)
            continue
        olcum = trim_silence(wav, sr, threshold_db=KIRPMA_DB, pad_ms=OLCUM_PAY_MS)
        denetle_ve_yaz(cid, g, cikis, olcum, g.get("metin"), False, red_adi=kid)

    # doğrulama ayrımı ve metadata. Metinsiz klipler (transkriptsiz bölme / .txt'siz kayıt) metadata.csv'ye
    # YAZILMAZ: eğitim deposu pandas ile okur, boş alan NaN → "nan" metniyle eğitilir. Ayrı dosyaya gider.
    metinli = [k for k in kabul if k["raw"]]
    metinsiz = [k for k in kabul if not k["raw"]]
    val = _dogrulama_sec(metinli, float(dogrulama))
    if dogrulama > 0 and not val:
        uyarilar.append("Doğrulama kümesi ayrılamadı: en az 2 kabul edilmiş, metinli kayıt gerekir.")
    egitim = [k for k in metinli if k["id"] not in val]
    dogru = [k for k in metinli if k["id"] in val]
    for k in kabul:
        k["bolum"] = "transkriptsiz" if not k["raw"] else ("dogrulama" if k["id"] in val else "egitim")

    def yaz(path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(f"{r['id']}|{r['raw']}|{r['norm']}\n")

    yaz(cdizin / "metadata.csv", egitim)
    for ad, satirlar in (("metadata_val.csv", dogru), (TRANSKRIPTSIZ_DOSYA, metinsiz)):
        if satirlar:
            yaz(cdizin / ad, satirlar)
        else:
            (cdizin / ad).unlink(missing_ok=True)    # önceki çalıştırmadan kalan, artık geçersiz dosya

    # rapor
    toplam_sn = round(sum(k["sn"] for k in kabul), 2)
    toplam_dk = toplam_sn / 60.0
    duygu: dict[str, dict] = {}
    for d in sorted({k["duygu"] for k in kabul}):
        ks = [k for k in kabul if k["duygu"] == d]
        aralik = _medyan([float(k["range_semitones"]) for k in ks if k["range_semitones"]])
        std = _medyan([float(k["std_semitones"]) for k in ks if k["std_semitones"]])
        uyari = None
        if aralik is not None and aralik < DUZ_ARALIK_ST:
            uyari = (f"{d} duygusu düz okunmuş, daha ifadeli tekrar kaydedin (medyan perde aralığı "
                     f"{_tr_sayi(aralik)} yarım ton; hedef ≥ {_tr_sayi(DUZ_ARALIK_ST, 0)})")
            uyarilar.append(uyari)
        duygu[d] = {"adet": len(ks), "dakika": round(sum(k["sn"] for k in ks) / 60.0, 2),
                    "range_semitones_medyan": aralik, "std_semitones_medyan": std, "uyari": uyari}
    yeterlilik = _yeterlilik(toplam_dk)
    if toplam_dk < ZORUNLU_DK:
        uyarilar.append(f"Toplam {_tr_sayi(toplam_dk)} dk kabul edilen ses var; eğitim için en az "
                        f"{_tr_sayi(ZORUNLU_DK, 0)} dk zorunlu, {_tr_sayi(ONERILEN_SAAT, 0)} saat ve üstü önerilir.")
    elif toplam_dk < ONERILEN_SAAT * 60:
        uyarilar.append(f"Toplam {_tr_sayi(toplam_dk)} dk: asgari eşik aşıldı; ifadeli ve kararlı sonuç için "
                        f"{_tr_sayi(ONERILEN_SAAT, 0)} saat ve üstü önerilir.")
    if eksik:
        uyarilar.append(f"{len(eksik)} kaydın ses dosyası bulunamadı (eksik listesine bakın).")
    if girdiler and len(red) > 0.2 * len(girdiler):
        uyarilar.append(f"Kayıtların %{round(100 * len(red) / len(girdiler))}'i reddedildi; kayıt ortamını ve "
                        "mikrofon seviyesini gözden geçirin (bkz. docs/KAYIT_REHBERI.md).")
    if metinsiz:
        uyarilar.append(TRANSKRIPTSIZ_TALIMAT.format(n=len(metinsiz), dk=_tr_sayi(sum(k["sn"] for k in metinsiz) / 60)))
    if id_eslemesi:
        ornek = ", ".join(f"{a} → {b}" for a, b in list(id_eslemesi.items())[:5])
        uyarilar.append(f"{len(id_eslemesi)} kayıt adı yalnızca sayıdan oluşuyor (eğitim deposu pandas ile okuyunca "
                        f"sayıya çevirir ve dosyayı bulamaz); çıktıda başlarına '{ID_ONEK}' eklendi: {ornek}"
                        + (" …" if len(id_eslemesi) > 5 else "") + " (tam liste: rapor.json → id_eslemesi).")
    yerli = {k["id"] for k in kabul}
    artik = sorted(p.name for p in wdizin.glob("*.wav") if _nfc(p.stem) not in yerli)
    if artik:
        uyarilar.append(f"wavs/ klasöründe bu çalıştırmaya ait olmayan {len(artik)} dosya var (önceki çalıştırma?); "
                        "metadata'da yer almazlar, isterseniz silin.")

    rapor = {
        "olusturma": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ayarlar": {"sr": sr, "etiket": bool(etiket), "dogrulama": float(dogrulama), "min_snr": float(min_snr),
                    "max_sn": float(max_s), "boleme": bool(boleme), "transkriptsiz": bool(transkriptsiz),
                    "manifest": str(manifest) if manifest is not None else None},
        "toplam_sn": toplam_sn,
        "toplam_dk": round(toplam_dk, 2),
        "toplam_saat": round(toplam_sn / 3600.0, 3),
        "duygu": duygu,
        "kabul": len(kabul),
        "egitim_adet": len(egitim),
        "dogrulama_adet": len(dogru),
        "transkriptsiz_adet": len(metinsiz),
        "transkriptsiz_dk": round(sum(k["sn"] for k in metinsiz) / 60.0, 2),
        "id_eslemesi": id_eslemesi,
        "red": red,
        "eksik": eksik,
        "yeterlilik": yeterlilik,
        "uyarilar": uyarilar,
        "kabul_edilenler": [{"id": k["id"], "duygu": k["duygu"], "yogunluk": k["yogunluk"], "sn": k["sn"],
                             "snr_db": k["snr_db"], "range_semitones": k["range_semitones"],
                             "bolum": k["bolum"]} for k in kabul],
    }
    (cdizin / "rapor.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rapor


# ---------- konsol ----------

def ozet_metni(rapor: dict, cikti: str | Path) -> str:
    """Raporun Türkçe konsol özeti."""
    s: list[str] = []
    s.append(f"Veri hazırlandı → {cikti}")
    s.append(f"  Kabul: {rapor['kabul']} klip (eğitim {rapor['egitim_adet']}, doğrulama {rapor['dogrulama_adet']}, "
             f"metinsiz {rapor['transkriptsiz_adet']} → {TRANSKRIPTSIZ_DOSYA}), "
             f"red: {len(rapor['red'])}, eksik: {len(rapor['eksik'])}")
    s.append(f"  Toplam ses: {_tr_sayi(rapor['toplam_dk'])} dk ({_tr_sayi(rapor['toplam_saat'], 2)} sa) — "
             f"yeterlilik: {rapor['yeterlilik']}")
    if rapor["duygu"]:
        s.append(f"  {'duygu':<12} {'adet':>5} {'dk':>7} {'aralık':>7} {'std':>6}")
        for d, v in rapor["duygu"].items():
            ar = "—" if v["range_semitones_medyan"] is None else _tr_sayi(v["range_semitones_medyan"])
            st = "—" if v["std_semitones_medyan"] is None else _tr_sayi(v["std_semitones_medyan"])
            isaret = "  ← düz" if v["uyari"] else ""
            s.append(f"  {d:<12} {v['adet']:>5} {_tr_sayi(v['dakika'], 2):>7} {ar:>7} {st:>6}{isaret}")
    if rapor["red"]:
        sayim: dict[str, int] = {}
        for r in rapor["red"]:
            sayim[r["neden"]] = sayim.get(r["neden"], 0) + 1
        s.append("  Red nedenleri: " + ", ".join(f"{n} {c}" for n, c in sorted(sayim.items(), key=lambda x: -x[1])))
        for r in rapor["red"][:15]:
            s.append(f"    - {r['id']}: {r['neden']}" + (f" ({r['ayrinti']})" if r.get("ayrinti") else ""))
        if len(rapor["red"]) > 15:
            s.append(f"    … ve {len(rapor['red']) - 15} kayıt daha (rapor.json)")
    if rapor["eksik"]:
        ilk = ", ".join(rapor["eksik"][:10])
        s.append(f"  Eksik kayıtlar: {ilk}" + (" …" if len(rapor["eksik"]) > 10 else ""))
    for u in rapor["uyarilar"]:
        s.append(f"  Uyarı: {u}")
    return "\n".join(s)


def _arg_ayristirici() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hazirla.py",
        description="Kayıtları Chatterbox ince ayarı için LJSpeech kümesine çevirir (SesKlon, SOZLESME3 §5).")
    p.add_argument("--kayitlar", required=True, help="kayıt klasörü (manifest id'leri ya da ses + .txt)")
    p.add_argument("--manifest", default=None, help="senaryo/manifest.csv (yoksa ses + aynı adlı .txt modu)")
    p.add_argument("--cikti", default="MyTTSDataset", help="çıktı klasörü (varsayılan MyTTSDataset)")
    p.add_argument("--sr", type=int, default=24000, help="çıktı örnekleme hızı (varsayılan 24000)")
    p.add_argument("--etiket", action="store_true", help="metinlerin başına [duygu] etiketi ekle (normal hariç)")
    p.add_argument("--dogrulama", type=float, default=0.0, help="doğrulama oranı (örn. 0.05)")
    p.add_argument("--min-snr", type=float, default=20.0, help="en düşük SNR (dB, varsayılan 20)")
    p.add_argument("--max-sn", type=float, default=12.0, help="en uzun klip (sn, varsayılan 12)")
    p.add_argument("--boleme", action="store_true", help="uzun kayıtları sessizliklerden 3–10 sn parçalara böl")
    p.add_argument("--transkriptsiz", action="store_true",
                   help="transkript olmadan çalış (bölünen parçaların ve .txt'si olmayanların metni boş kalır)")
    return p


def main(argv: list[str] | None = None) -> int:
    """Komut satırı girişi → çıkış kodu (0 başarı, 1 hata, 2 hiç kabul yok)."""
    args = _arg_ayristirici().parse_args(argv)

    def ilerleme(i: int, toplam: int, kid: str) -> None:
        if toplam >= 50 and i % 25 == 0:
            print(f"  … {i}/{toplam} ({kid})", flush=True)

    try:
        rapor = prepare(args.kayitlar, args.manifest, args.cikti, sr=args.sr, etiket=args.etiket,
                        dogrulama=args.dogrulama, min_snr=args.min_snr, max_s=args.max_sn,
                        boleme=args.boleme, transkriptsiz=args.transkriptsiz, ilerleme=ilerleme)
    except (FileNotFoundError, ValueError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 1
    print(ozet_metni(rapor, args.cikti))
    if rapor["kabul"] == 0:
        print("Hata: hiçbir kayıt kabul edilmedi; red nedenlerine bakın.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
