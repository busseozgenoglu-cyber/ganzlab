#!/usr/bin/env python3
"""İnce ayar değerlendirmesi — temel Chatterbox ile ince ayarlı T3'ü aynı cümle seti ve referansla ölçer, kabul/ret verir.

Sözleşme: ``docs/SOZLESME3.md`` §6. Ölçüm ``app.bench`` ile yapılır (aynı pyin "kulağı", aynı Türkçe cümle seti);
karşılaştırma ``bench.compare`` ile, karar :func:`karar_ver` ile.

Kullanım (proje kökünden)::

    # iki modeli de koştur (önce temel, sonra ince ayarlı; aynı referans)
    python finetune/degerlendir.py --ref ses.wav --ince t3_finetuned_merged.safetensors --cikti rapor.json
    python finetune/degerlendir.py --ref ses.wav --ince t3.safetensors --etiketli --pipeline   # duygu etiketli veri

    # hazır sonuçları karşılaştır (model yüklemez)
    python finetune/degerlendir.py --temel temel.json --ince-sonuc ince.json

    # temel sonuç hazırsa yalnızca ince ayarlıyı koştur
    python finetune/degerlendir.py --temel temel.json --ref ses.wav --ince t3.safetensors

Kabul ölçütü (hepsi birden):

* ince ayarlı modelin tonlama aralığı medyanı ≥ 17 yarım ton (Gemini TTS ≈ 17,6; temel Chatterbox ≈ 13,5),
* kalite kontrolden geçemeyen cümle sayısı artmamış (``qc_fail_count`` ince ≤ temel),
* konuşma hızı doğal: 3,5 ≤ hece/sn ortalaması ≤ 6,5,
* aralık temelden gerçekten büyük (ince > temel).

Çıkış kodu: 0 = KABUL, 2 = RET, 1 = hata (dosya yok, model yüklenemedi …).

İnce ayarlı model nasıl yüklenir: ``T3_FINETUNED`` ortam değişkeni ayarlanır, ``app.config`` yeniden yüklenir ve
``backends.create("chatterbox")`` çağrılır — arka uç ağırlıkları ``model.t3``'e yükler (``load_finetuned_t3``).
Temel koşuda ``T3_FINETUNED`` boşaltılır; kabukta ayarlı kalmış bir değer temel ölçümü bozmasın.
"""
from __future__ import annotations

import argparse
import gc
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SURUM = 1
HEDEF_ARALIK = 17.0          # yarım ton — Gemini TTS düzeyi
HECE_MIN = 3.5               # hece/sn — altı ağır, sürünen konuşma
HECE_MAX = 6.5               # hece/sn — üstü yutulan heceler
GEMINI_ARALIK = 17.6


# ---------- yardımcılar ----------

def _sayi(v: Any, nd: int = 1) -> str:
    """Türkçe ondalık: 17.84 → '17,8'; ölçüm yoksa '—'."""
    if v is None:
        return "—"
    try:
        return f"{float(v):.{nd}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


def _ozet(sonuc: dict) -> dict:
    """Tam bench sonucu (``{"summary": …}``) ya da doğrudan özet sözlüğü kabul eder."""
    if not isinstance(sonuc, dict):
        raise ValueError("Kıyaslama sonucu bir sözlük olmalı.")
    ozet = sonuc.get("summary", sonuc)
    if not isinstance(ozet, dict):
        raise ValueError("Kıyaslama sonucunda 'summary' alanı bir sözlük değil.")
    return ozet


def _hata_sayisi(sonuc: dict) -> int:
    """Üretilemeyen cümle sayısı: cümle listesindeki ``error`` alanları, yoksa özetteki ``errors``."""
    cumleler = sonuc.get("sentences") if isinstance(sonuc, dict) else None
    if isinstance(cumleler, list):
        return sum(1 for s in cumleler if isinstance(s, dict) and "error" in s)
    try:
        return int(_ozet(sonuc).get("errors") or 0)
    except (TypeError, ValueError):
        return 0


def _float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# ---------- karar ----------

def karar_ver(temel: dict, ince: dict) -> tuple[bool, list[str]]:
    """Temel ve ince ayarlı kıyaslama sonuçlarından (ya da özetlerinden) kabul kararı ve Türkçe nedenler.

    Her koşul için bir neden döner: geçen koşullar ``"✓ "``, kalanlar ``"✗ "`` ile başlar; ölçülemeyen değer
    koşulu geçemez. Koşullar: üretim hatası artmamış, başarıyla ölçülen cümle sayısı azalmamış, aralık medyanı
    ≥ 17, QC başarısız artmamış, hece/sn 3,5–6,5, aralık temelden geniş.
    """
    t, i = _ozet(temel), _ozet(ince)
    nedenler: list[str] = []
    kabul = True

    def kosul(gecti: bool, evet: str, hayir: str) -> None:
        nonlocal kabul
        kabul = kabul and gecti
        nedenler.append(("✓ " + evet) if gecti else ("✗ " + hayir))

    if i.get("n") == 0:
        kosul(False, "", "İnce ayarlı model hiçbir cümleyi üretemedi (ölçülen cümle sayısı 0); sonuç JSON'undaki "
                         "'error' alanlarına bakın.")

    # Hatalı cümleler özetten (n, qc_fail_count) düşülür: 50 cümleden 38'i hata verip 12'si iyi çıkan bir model
    # yalnız o 12 cümleyle "ifadeli" görünmesin diye hata ve başarı sayıları ayrıca denetlenir.
    hata_t, hata_i = _hata_sayisi(temel), _hata_sayisi(ince)
    kosul(hata_i <= hata_t,
          f"Üretim hatası artmadı (temel {hata_t}, ince {hata_i} cümle).",
          f"İnce ayarlı modelde üretim hatası arttı (temel {hata_t} → ince {hata_i} cümle): bu cümleler ölçüme "
          f"girmedi, özet yanıltıcı olabilir — sonuç JSON'undaki 'error' alanlarına bakın.")
    n_t, n_i = t.get("n"), i.get("n")
    if n_t is not None and n_i is not None:
        kosul(int(n_i) >= int(n_t),
              f"Başarıyla ölçülen cümle sayısı azalmadı ({n_t} → {n_i}).",
              f"Başarıyla ölçülen cümle sayısı azaldı (temel {n_t} → ince {n_i}): ince model bazı cümleleri "
              f"üretemedi ya da farklı bir cümle setiyle ölçüldü; kıyas aynı cümlelerle yapılmalı.")

    ar_i, ar_t = _float(i.get("range_semitones_median")), _float(t.get("range_semitones_median"))
    if ar_i is None:
        kosul(False, "", "İnce ayarlı modelin tonlama aralığı ölçülemedi.")
    else:
        kosul(ar_i >= HEDEF_ARALIK,
              f"Tonlama aralığı medyanı {_sayi(ar_i)} yarım ton ≥ {_sayi(HEDEF_ARALIK, 0)} hedefi "
              f"(Gemini TTS ≈ {_sayi(GEMINI_ARALIK)}).",
              f"Tonlama aralığı medyanı {_sayi(ar_i)} yarım ton, hedef ≥ {_sayi(HEDEF_ARALIK, 0)} "
              f"(Gemini TTS ≈ {_sayi(GEMINI_ARALIK)}): model hâlâ düz — daha ifadeli veri ya da daha çok epoch gerekli.")

    qc_i, qc_t = i.get("qc_fail_count"), t.get("qc_fail_count")
    if qc_i is None or qc_t is None:
        kosul(False, "", "Kalite kontrol başarısız sayısı ölçülemedi (qc_fail_count yok).")
    else:
        kosul(int(qc_i) <= int(qc_t),
              f"Kalite kontrolden geçemeyen cümle sayısı artmadı ({qc_t} → {qc_i}).",
              f"Kalite kontrolden geçemeyen cümle sayısı arttı ({qc_t} → {qc_i}): ince ayar kararlılığı bozmuş "
              f"(yutulan/tekrarlanan sözcük, kesilme) — öğrenme hızını ya da epoch'u düşürün.")

    hece = _float(i.get("syllables_per_sec_mean"))
    if hece is None:
        kosul(False, "", "Konuşma hızı (hece/sn) ölçülemedi.")
    else:
        if hece < HECE_MIN:
            hayir = (f"Konuşma hızı {_sayi(hece, 2)} hece/sn, doğal aralığın altında ({_sayi(HECE_MIN)}–"
                     f"{_sayi(HECE_MAX)}): konuşma ağır ve sürünüyor.")
        else:
            hayir = (f"Konuşma hızı {_sayi(hece, 2)} hece/sn, doğal aralığın üstünde ({_sayi(HECE_MIN)}–"
                     f"{_sayi(HECE_MAX)}): heceler yutuluyor ya da konuşma aceleye geliyor.")
        kosul(HECE_MIN <= hece <= HECE_MAX,
              f"Konuşma hızı {_sayi(hece, 2)} hece/sn, doğal aralıkta ({_sayi(HECE_MIN)}–{_sayi(HECE_MAX)}).",
              hayir)

    if ar_i is None or ar_t is None:
        kosul(False, "", "Temel ile karşılaştırılamadı: tonlama aralığı iki sonuçtan birinde yok.")
    else:
        fark = ar_i - ar_t
        kosul(ar_i > ar_t,
              f"Tonlama aralığı temelden {_sayi(fark)} yarım ton geniş ({_sayi(ar_t)} → {_sayi(ar_i)}).",
              f"Tonlama aralığı temelden geniş değil ({_sayi(ar_t)} → {_sayi(ar_i)}, fark {_sayi(fark)}): "
              f"ince ayar ifadeyi artırmamış.")
    return kabul, nedenler


# ---------- model koşusu ----------

def _ortam_ayarla(ince: str | None, etiketli: bool) -> None:
    """``T3_FINETUNED`` / ``T3_EMOTION_TAGS`` ortamını ayarlayıp ``app.config``'i yeniden yükler."""
    os.environ["T3_FINETUNED"] = ince or ""
    os.environ["T3_EMOTION_TAGS"] = "1" if etiketli else "0"
    import app.config as config

    importlib.reload(config)     # chatterbox arka ucu config'i modül olarak tutar: yeni değerleri görür


def _bellek_birak() -> None:
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is None:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        mps = getattr(torch, "mps", None)
        if mps is not None and hasattr(mps, "empty_cache") and torch.backends.mps.is_available():
            mps.empty_cache()
    except Exception:  # noqa: BLE001 - önbellek boşaltılamazsa değerlendirme yine sürer
        pass


def model_kos(etiket: str, *, arka_uc: str, ince: str | None, sentences: list[dict], ref: str | None,
              ayarlar: dict, pipeline: bool, repeat: int, cihaz: str, etiketli: bool, metin_etiketli: bool,
              sessiz: bool, cumle_dosyasi: str | None = None) -> dict:
    """Bir modeli (temel ya da ince ayarlı) kurar ve cümle setini ``bench.run_bench`` ile ölçer.

    ``etiketli``: arka uç düzeyinde ``T3_EMOTION_TAGS`` (yalnız ince koşuda açılır; chatterbox arka ucu parça
    duygusunu ``[mutlu] `` öneki olarak ekler). ``metin_etiketli``: cümle metnine ``[duygu]`` etiketi yazılsın mı —
    iki koşuda **aynı** olmalı (boru hattında motor etiketi duygu profili olarak da uygular; bkz. :func:`metin_etiketi`).
    """
    from app import backends, bench

    _ortam_ayarla(ince, etiketli)
    if not sessiz:
        print(f"\n▶ {etiket}: {arka_uc}" + (f" + {Path(ince).name}" if ince else "") + f" • {len(sentences)} cümle • "
              f"cihaz {cihaz}" + (" • boru hattı" if pipeline else "") + (" • T3 duygu öneki" if etiketli else ""),
              file=sys.stderr, flush=True)

    def ilerleme(i: int, n: int, metin: str) -> None:
        print(f"  [{etiket} {i + 1}/{n}] {metin[:60]}", file=sys.stderr, flush=True)

    model = backends.create(arka_uc, device=cihaz)
    try:
        sonuc = bench.run_bench(arka_uc, sentences, ref=ref, settings=ayarlar, pipeline=pipeline, repeat=repeat,
                                device=cihaz, emotion_tags=metin_etiketli, progress=None if sessiz else ilerleme,
                                model=model)
    finally:
        del model
        _bellek_birak()
    sonuc["settings"].update({"finetuned": ince, "rol": etiket, "t3_emotion_tags": bool(etiketli),
                              "sentences_file": str(cumle_dosyasi) if cumle_dosyasi else None,
                              "n_sentences": len(sentences)})
    return sonuc


def metin_etiketi(pipeline: bool, etiketli: bool) -> bool:
    """İki koşuda da aynı olan metin etiketi kararı.

    * Ham mod: metin etiketsiz; ``bench`` her cümlenin duygusunu ``emotion`` parametresiyle gönderir, ince koşuda
      arka uç (``T3_EMOTION_TAGS=1``) öneki kendisi ekler, temel arka uç eklemez. Böylece iki model aynı metni alır.
    * Boru hattı + ``--etiketli``: metin iki koşuda da ``[duygu] …`` olur; motor etiketi iki koşuda da aynı duygu
      profili olarak uygular ve parçanın duygusunu arka uca iletir (ince koşuda yine önek olur).
    """
    return bool(pipeline and etiketli)


# ---------- kıyasın adilliği ----------

_KIYAS_ADLARI = (("pipeline", "boru hattı"), ("ref", "referans dosyası"), ("seed", "tohum"),
                 ("sentences_file", "cümle dosyası"), ("n", "cümle sayısı"), ("exaggeration", "exaggeration"),
                 ("cfg_weight", "cfg_weight"), ("temperature", "temperature"), ("repeat", "tekrar"),
                 ("emotion_tags", "metindeki duygu etiketi"))


def kiyas_ayarlari(settings: dict | None, n: int | None) -> dict:
    """Bir sonucun kıyası etkileyen ayarları, karşılaştırılabilir biçimde (dosya yolları yalnız adıyla)."""
    from app import bench

    st = settings or {}
    dosya = st.get("sentences_file") or str(bench.DEFAULT_SENTENCES)
    return {"pipeline": bool(st.get("pipeline")), "ref": Path(str(st["ref"])).name if st.get("ref") else None,
            "seed": st.get("seed"), "sentences_file": Path(str(dosya)).name, "n": n,
            "exaggeration": st.get("exaggeration"), "cfg_weight": st.get("cfg_weight"),
            "temperature": st.get("temperature"), "repeat": st.get("repeat") or 1,
            "emotion_tags": bool(st.get("emotion_tags"))}


def _sonuc_kiyas_ayarlari(sonuc: dict) -> dict:
    cumleler = sonuc.get("sentences")
    n = len(cumleler) if isinstance(cumleler, list) else (sonuc.get("settings") or {}).get("n_sentences")
    return kiyas_ayarlari(sonuc.get("settings"), n)


def ayar_farklari(a: dict, b: dict, *, ad_a: str = "temel", ad_b: str = "ince ayar") -> list[str]:
    """İki kıyas ayarı sözlüğünün farkları → Türkçe uyarılar ("kıyas adil olmayabilir")."""
    uyarilar = []
    for anahtar, ad in _KIYAS_ADLARI:
        va, vb = a.get(anahtar), b.get(anahtar)
        if va is None and vb is None:
            continue
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
            ayni = abs(float(va) - float(vb)) < 1e-9
        else:
            ayni = va == vb
        if not ayni:
            uyarilar.append(f"{ad} farklı ({ad_a}: {_deger(va)}, {ad_b}: {_deger(vb)}) — kıyas adil olmayabilir.")
    return uyarilar


def _deger(v: Any) -> str:
    if v is None:
        return "yok"
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    if isinstance(v, float):
        return _sayi(v, 2)
    return str(v)


# ---------- konsol ----------

def _karsilastirma_metni(temel: dict, ince: dict) -> tuple[dict, str]:
    from app import bench

    cmp = bench.compare(temel, ince)
    cmp.setdefault("labels", {})
    cmp["labels"] = {"a": "temel — " + str(cmp["labels"].get("a", "")),
                     "b": "ince ayar — " + str(cmp["labels"].get("b", ""))}
    bicimle = getattr(bench, "format_compare", None)
    if callable(bicimle):
        return cmp, bicimle(cmp)
    satirlar = [f"{'Ölçüt':30}  {'Temel':>8}  {'İnce':>8}  {'Fark':>8}"]
    for r in cmp.get("summary") or []:
        satirlar.append(f"{r.get('label', r.get('metric', ''))[:30]:30}  {_sayi(r.get('a'), 2):>8}  "
                        f"{_sayi(r.get('b'), 2):>8}  {_sayi(r.get('delta'), 2):>8}")
    return cmp, "\n".join(satirlar)


def karar_metni(kabul: bool, nedenler: list[str]) -> str:
    satirlar = ["", "═" * 60, f"SONUÇ: {'KABUL' if kabul else 'RET'}", "═" * 60]
    satirlar += [f"  {n}" for n in nedenler]
    if kabul:
        satirlar += ["", "İnce ayarlı modeli kullanmak için SesKlon'u T3_FINETUNED=<dosya> ile başlatın "
                         "(duygu etiketli veriyle eğitildiyse T3_EMOTION_TAGS=1 de)."]
    else:
        satirlar += ["", "Öneri: veri raporundaki duygu başına tonlama aralıklarına bakın (MyTTSDataset/rapor.json); "
                         "düz kayıtlarla eğitilen model de düz konuşur. Ayrıntı: finetune/README.md → Sık sorunlar."]
    return "\n".join(satirlar)


# ---------- komut satırı ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python finetune/degerlendir.py",
        description="Temel ve ince ayarlı Chatterbox'ı aynı Türkçe cümle setiyle ölçer; kabul ölçütü: tonlama aralığı "
                    "medyanı ≥ 17 yarım ton, QC bozulmamış, hece/sn 3,5–6,5, aralık temelden geniş.")
    ap.add_argument("--ref", default=None, help="konuşmacının referans kaydı (WAV) — model koşusu için gerekli")
    ap.add_argument("--ince", default=None, metavar="DOSYA", help="ince ayarlı T3 ağırlıkları (.safetensors / .pt)")
    ap.add_argument("--cumleler", default=None, metavar="DOSYA",
                    help="cümle dosyası, 'kategori|cümle' (varsayılan: backend/data/bench_tr.txt)")
    ap.add_argument("--cikti", default=None, metavar="JSON", help="raporu (iki sonuç + karşılaştırma + karar) yaz")
    ap.add_argument("--pipeline", action="store_true", help="tüm motor zinciriyle (Engine.synthesize) ölç")
    ap.add_argument("--etiketli", action="store_true",
                    help="ince ayar verisi '[duygu] ' etiketliyse: ince koşuda T3_EMOTION_TAGS=1 (iki koşu aynı "
                         "metni alır; --pipeline ile metin iki koşuda da etiketli)")
    ap.add_argument("--temel", default=None, metavar="JSON", help="hazır temel sonuç (app.bench --out çıktısı)")
    ap.add_argument("--ince-sonuc", default=None, metavar="JSON", help="hazır ince ayar sonucu (app.bench --out)")
    ap.add_argument("--arka-uc", default="chatterbox", help="arka uç (varsayılan: chatterbox; 'fake' kuru çalışma)")
    ap.add_argument("--cihaz", default=None, help="cuda | mps | cpu (varsayılan: otomatik)")
    ap.add_argument("--limit", type=int, default=None, help="yalnızca ilk N cümle")
    ap.add_argument("--repeat", type=int, default=1, help="her cümleyi N kez üret, medyanı al")
    ap.add_argument("--exaggeration", type=float, default=0.5)
    ap.add_argument("--cfg-weight", type=float, default=0.5)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=1, help="tohum (iki modelde aynı; varsayılan 1)")
    ap.add_argument("--quiet", action="store_true", help="ilerleme ve tabloları yazma (karar satırı yine yazılır)")
    return ap


def _yaz_json(yol: str | Path, veri: Any) -> None:
    p = Path(yol)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from app import bench

        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit en az 1 olmalı.")
        if args.repeat < 1:
            raise ValueError("--repeat en az 1 olmalı.")
        temel = bench._read_result(args.temel) if args.temel else None
        ince = bench._read_result(args.ince_sonuc) if args.ince_sonuc else None
        uyarilar: list[str] = []
        if temel is not None and ince is not None:
            uyarilar = ayar_farklari(_sonuc_kiyas_ayarlari(temel), _sonuc_kiyas_ayarlari(ince))

        if temel is None or ince is None:          # en az bir model koşusu gerekiyor
            if ince is None and not args.ince:
                raise ValueError("İnce ayarlı model için --ince <ağırlık dosyası> ya da --ince-sonuc <JSON> verin.")
            if args.ince and ince is None and not Path(args.ince).expanduser().is_file():
                raise FileNotFoundError(f"İnce ayar ağırlık dosyası bulunamadı: {args.ince}")
            if not args.ref:
                raise ValueError("Model koşusu için --ref <konuşmacı.wav> gerekli (ince ayar verisindeki konuşmacının "
                                 "kaydı; iki model aynı referansla ölçülür).")
            if not Path(args.ref).is_file():
                raise FileNotFoundError(f"Referans dosyası bulunamadı: {args.ref}")
            sentences = bench.load_sentences(args.cumleler)
            if args.limit:
                sentences = sentences[: args.limit]
            ayarlar = {"exaggeration": args.exaggeration, "cfg_weight": args.cfg_weight,
                       "temperature": args.temperature, "seed": args.seed}
            cihaz = args.cihaz or bench._auto_device()
            metin_etiketli = metin_etiketi(args.pipeline, args.etiketli)
            ortak = dict(arka_uc=args.arka_uc, sentences=sentences, ref=args.ref, ayarlar=ayarlar,
                         pipeline=args.pipeline, repeat=args.repeat, cihaz=cihaz, sessiz=args.quiet,
                         metin_etiketli=metin_etiketli, cumle_dosyasi=args.cumleler)
            # Hazır bir sonuçla yeni koşu kıyaslanacaksa ayarları önceden karşılaştır (uzun koşudan önce uyar)
            plan = kiyas_ayarlari({"pipeline": args.pipeline, "ref": args.ref, "seed": args.seed,
                                   "sentences_file": args.cumleler, "exaggeration": args.exaggeration,
                                   "cfg_weight": args.cfg_weight, "temperature": args.temperature,
                                   "repeat": args.repeat, "emotion_tags": metin_etiketli}, len(sentences))
            if temel is not None:
                uyarilar = ayar_farklari(_sonuc_kiyas_ayarlari(temel), plan, ad_b="yeni koşu")
            elif ince is not None:
                uyarilar = ayar_farklari(plan, _sonuc_kiyas_ayarlari(ince), ad_a="yeni koşu")
            for u in uyarilar:
                print(f"UYARI: {u}", file=sys.stderr, flush=True)
            onceki = {k: os.environ.get(k) for k in ("T3_FINETUNED", "T3_EMOTION_TAGS")}
            try:
                if temel is None:
                    temel = model_kos("temel", ince=None, etiketli=False, **ortak)
                if ince is None:
                    ince_yol = str(Path(args.ince).expanduser().resolve())
                    ince = model_kos("ince ayar", ince=ince_yol, etiketli=args.etiketli, **ortak)
            finally:                                # ortamı eski hâline getir
                for k, v in onceki.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                import app.config as config

                importlib.reload(config)

        cmp, tablo = _karsilastirma_metni(temel, ince)
        kabul, nedenler = karar_ver(temel, ince)
        if not args.quiet:
            print(tablo)
        print(karar_metni(kabul, nedenler))
        if uyarilar:
            print("\nKıyas uyarıları (ayarlar farklı — kıyas adil olmayabilir):")
            for u in uyarilar:
                print(f"  ⚠ {u}")
        if args.cikti:
            _yaz_json(args.cikti, {
                "version": SURUM,
                "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "olcut": {"aralik_medyani_en_az": HEDEF_ARALIK, "hece_sn": [HECE_MIN, HECE_MAX],
                          "qc_fail_artmamali": True, "aralik_temelden_genis": True},
                "karar": {"kabul": kabul, "sonuc": "KABUL" if kabul else "RET", "nedenler": nedenler},
                "uyarilar": uyarilar,
                "karsilastirma": cmp,
                "temel": temel,
                "ince": ince,
            })
            if not args.quiet:
                print(f"\nRapor yazıldı: {args.cikti}")
        return 0 if kabul else 2
    except Exception as e:  # noqa: BLE001 - her hata Türkçe mesaj + çıkış kodu 1
        print(f"Hata: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
