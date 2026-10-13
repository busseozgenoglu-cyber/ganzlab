"""İnce ayar hattının son halkası: ``finetune/degerlendir.py`` (kabul ölçütü), ``finetune/egit.sh`` (sözdizimi) ve
``finetune/README.md``. Model yüklenmez: sonuçlar gerçek ``app.bench.summarize`` ile el yapımı cümle ölçümlerinden
üretilir; kuru çalışma sahte arka uçla yapılır (torch / chatterbox gerekmez).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import soundfile as sf

from app import bench
from app.backends.fake import speechlike

KOK = Path(__file__).resolve().parents[2]
FINETUNE = KOK / "finetune"


def _yukle():
    spec = importlib.util.spec_from_file_location("degerlendir", FINETUNE / "degerlendir.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


degerlendir = _yukle()


def sonuc(aralik: float, hece: float, qc_fail: int, n: int = 6, ad: str = "chatterbox") -> dict:
    """``run_bench`` şemasında sonuç: cümle satırları ``bench.measure`` alanlarıyla, özet gerçek ``summarize``'dan."""
    satirlar = []
    for k in range(n):
        satirlar.append({
            "id": f"n{k + 1:02d}", "category": "nötr", "text": f"Deneme cümlesi {k + 1}.",
            "input_text": f"Deneme cümlesi {k + 1}.", "duration_s": 2.0, "gen_s": 4.0, "rtf": 2.0,
            "f0": {"median_hz": 180.0, "min_hz": 120.0, "max_hz": 260.0, "range_semitones": aralik,
                   "std_semitones": 3.0, "voiced_ratio": 0.7},
            "syllables_per_sec": hece, "chars_per_sec": 12.0, "pauses": {"count": 1, "median_ms": 250},
            "dynamic_range_db": 18.0,
            "qc": {"score": 40 if k < qc_fail else 90, "decision": "retry_seed" if k < qc_fail else "accept",
                   "reasons": []},
            "speech_ratio": 0.8,
        })
    return {"version": bench.VERSION, "created": "2026-10-13T12:00:00+03:00",
            "backend": {"name": ad, "sr": 24000}, "settings": {"backend": ad, "exaggeration": 0.5, "cfg_weight": 0.5,
                                                              "temperature": 0.8, "pipeline": False, "ref": None},
            "sentences": satirlar, "summary": bench.summarize(satirlar)}


TEMEL = sonuc(13.5, 4.6, 1)


def _kalan(nedenler: list[str]) -> list[str]:
    return [n for n in nedenler if n.startswith("✗")]


# ---------- karar_ver ----------

def test_ozet_gercek_summarize_ile_beklenen_degerler():
    s = sonuc(17.8, 4.8, 1)["summary"]
    assert s["range_semitones_median"] == 17.8 and s["syllables_per_sec_mean"] == 4.8 and s["qc_fail_count"] == 1


def test_kabul_tum_kosullar_gecer():
    kabul, nedenler = degerlendir.karar_ver(TEMEL, sonuc(17.8, 4.8, 1))
    assert kabul is True
    assert not _kalan(nedenler) and len(nedenler) == 4
    assert all(n.startswith("✓") for n in nedenler)
    assert any("17,8" in n and "Tonlama aralığı medyanı" in n for n in nedenler)
    assert any("artmadı (1 → 1)" in n for n in nedenler)
    assert any("doğal aralıkta" in n for n in nedenler)
    assert any("temelden 4,3 yarım ton geniş" in n for n in nedenler)


def test_ozet_sozlugu_de_kabul_edilir():
    kabul, _ = degerlendir.karar_ver(TEMEL["summary"], sonuc(17.8, 4.8, 1)["summary"])
    assert kabul is True


def test_ret_aralik_hedefin_altinda():
    kabul, nedenler = degerlendir.karar_ver(TEMEL, sonuc(15.0, 4.8, 1))
    assert kabul is False
    kalan = _kalan(nedenler)
    assert len(kalan) == 1
    assert "Tonlama aralığı medyanı 15,0 yarım ton" in kalan[0] and "hedef ≥ 17" in kalan[0] and "düz" in kalan[0]


def test_ret_qc_basarisiz_artti():
    kabul, nedenler = degerlendir.karar_ver(TEMEL, sonuc(17.8, 4.8, 3))
    assert kabul is False
    kalan = _kalan(nedenler)
    assert len(kalan) == 1 and "Kalite kontrolden geçemeyen cümle sayısı arttı (1 → 3)" in kalan[0]


def test_ret_hece_hizi_cok_yuksek():
    kabul, nedenler = degerlendir.karar_ver(TEMEL, sonuc(17.8, 7.2, 1))
    assert kabul is False
    kalan = _kalan(nedenler)
    assert len(kalan) == 1 and "7,20 hece/sn" in kalan[0] and "üstünde" in kalan[0] and "yutuluyor" in kalan[0]


def test_ret_hece_hizi_cok_dusuk():
    kabul, nedenler = degerlendir.karar_ver(TEMEL, sonuc(17.8, 3.0, 1))
    assert kabul is False
    assert "altında" in _kalan(nedenler)[0] and "ağır" in _kalan(nedenler)[0]


def test_ret_temelden_dusuk():
    kabul, nedenler = degerlendir.karar_ver(sonuc(18.5, 4.6, 1), sonuc(17.8, 4.8, 1))
    assert kabul is False
    kalan = _kalan(nedenler)
    assert len(kalan) == 1 and "temelden geniş değil (18,5 → 17,8" in kalan[0] and "artırmamış" in kalan[0]


def test_ret_olculemeyen_deger_ve_bos_sonuc():
    bos = {"summary": {"n": 0, "range_semitones_median": None, "syllables_per_sec_mean": None,
                       "qc_fail_count": 0}}
    kabul, nedenler = degerlendir.karar_ver(TEMEL, bos)
    assert kabul is False
    metin = " ".join(_kalan(nedenler))
    assert "hiçbir cümleyi üretemedi" in metin and "ölçülemedi" in metin


def test_farkli_cumle_sayisi_bilgi_notu_karari_degistirmez():
    kabul, nedenler = degerlendir.karar_ver(TEMEL, sonuc(17.8, 4.8, 1, n=5))
    assert kabul is True and any(n.startswith("ℹ") and "cümle sayıları farklı" in n for n in nedenler)


# ---------- main: hazır JSON karşılaştırma ----------

def _yaz(yol: Path, veri: dict) -> str:
    yol.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    return str(yol)


def test_main_hazir_sonuclar_kabul_0(tmp_path, capsys):
    a = _yaz(tmp_path / "temel.json", TEMEL)
    b = _yaz(tmp_path / "ince.json", sonuc(17.8, 4.8, 1))
    rapor = tmp_path / "rapor.json"
    assert degerlendir.main(["--temel", a, "--ince-sonuc", b, "--cikti", str(rapor)]) == 0
    cikti = capsys.readouterr().out
    assert "SONUÇ: KABUL" in cikti and "Tonlama aralığı medyanı" in cikti and "Kazanan: B" in cikti
    veri = json.loads(rapor.read_text(encoding="utf-8"))
    assert veri["karar"]["sonuc"] == "KABUL" and veri["karar"]["kabul"] is True
    assert veri["karsilastirma"]["winner"] == "b"
    assert veri["temel"]["summary"]["range_semitones_median"] == 13.5
    assert veri["ince"]["summary"]["range_semitones_median"] == 17.8


def test_main_hazir_sonuclar_ret_2(tmp_path, capsys):
    a = _yaz(tmp_path / "temel.json", TEMEL)
    b = _yaz(tmp_path / "ince.json", sonuc(15.0, 4.8, 1))
    assert degerlendir.main(["--temel", a, "--ince-sonuc", b]) == 2
    cikti = capsys.readouterr().out
    assert "SONUÇ: RET" in cikti and "✗ Tonlama aralığı medyanı 15,0" in cikti and "rapor.json" in cikti


def test_main_hatalar_turkce_1(tmp_path, capsys):
    a = _yaz(tmp_path / "temel.json", TEMEL)
    assert degerlendir.main(["--temel", a, "--ince-sonuc", str(tmp_path / "yok.json")]) == 1
    assert "Sonuç dosyası bulunamadı" in capsys.readouterr().err
    assert degerlendir.main(["--temel", a]) == 1
    assert "--ince" in capsys.readouterr().err
    agirlik = tmp_path / "t3.safetensors"
    agirlik.write_bytes(b"0")
    assert degerlendir.main(["--ince", str(agirlik)]) == 1
    assert "--ref" in capsys.readouterr().err
    assert degerlendir.main(["--ref", str(tmp_path / "yok.wav"), "--ince", str(tmp_path / "yok.safetensors")]) == 1
    assert "İnce ayar ağırlık dosyası bulunamadı" in capsys.readouterr().err
    bozuk = tmp_path / "bozuk.json"
    bozuk.write_text("{}", encoding="utf-8")
    assert degerlendir.main(["--temel", str(bozuk), "--ince-sonuc", str(bozuk)]) == 1
    assert "'summary' alanı yok" in capsys.readouterr().err


# ---------- kuru çalışma: sahte arka uçla iki model koşusu ----------

@pytest.fixture()
def eski_ince_ayar_ortami():
    """Kabukta ayarlı kalmış bir T3_FINETUNED; test bitince ortam ve ``app.config`` eski hâline döner."""
    import importlib

    from app import config

    onceki = os.environ.get("T3_FINETUNED")
    os.environ["T3_FINETUNED"] = "/eski/deger.safetensors"
    yield
    if onceki is None:
        os.environ.pop("T3_FINETUNED", None)
    else:
        os.environ["T3_FINETUNED"] = onceki
    importlib.reload(config)


def test_kuru_calisma_sahte_arka_uc_ortami_ayarlar_ve_geri_alir(tmp_path, monkeypatch, capsys,
                                                                eski_ince_ayar_ortami):
    from app import config

    cumleler = tmp_path / "cumleler.txt"
    cumleler.write_text("nötr|Bugün hava güzel.\nmutlu|Sınavı geçtim!\n", encoding="utf-8")
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), speechlike(60, 24000, seed=2, range_st=15.0), 24000)
    agirlik = tmp_path / "t3_finetuned_merged.safetensors"
    agirlik.write_bytes(b"0")
    gorulen = []
    asil = degerlendir.model_kos

    def izle(etiket, **kw):
        gorulen.append((etiket, os.environ.get("T3_FINETUNED"), kw["etiketli"]))
        sonuc_ = asil(etiket, **kw)
        gorulen.append(("config", config.T3_FINETUNED, config.T3_EMOTION_TAGS))
        return sonuc_

    monkeypatch.setattr(degerlendir, "model_kos", izle)
    rapor = tmp_path / "rapor.json"
    kod = degerlendir.main(["--arka-uc", "fake", "--ref", str(ref), "--ince", str(agirlik), "--cumleler",
                            str(cumleler), "--etiketli", "--quiet", "--cihaz", "cpu", "--cikti", str(rapor)])
    assert kod in (0, 2)
    assert "SONUÇ:" in capsys.readouterr().out
    assert gorulen[0] == ("temel", "/eski/deger.safetensors", False)        # model_kos ortamı kendisi ayarlar
    assert gorulen[1] == ("config", None, False)                            # temel koşuda ince ayar boş
    assert gorulen[2][0] == "ince ayar" and gorulen[2][2] is True
    assert gorulen[3] == ("config", str(agirlik.resolve()), True)           # ince koşuda yol + etiket açık
    assert os.environ["T3_FINETUNED"] == "/eski/deger.safetensors"           # ortam geri alındı
    assert config.T3_FINETUNED == "/eski/deger.safetensors"
    veri = json.loads(rapor.read_text(encoding="utf-8"))
    assert veri["temel"]["summary"]["n"] == 2 and veri["ince"]["summary"]["n"] == 2
    assert veri["ince"]["settings"]["finetuned"] == str(agirlik.resolve())
    assert veri["ince"]["settings"]["emotion_tags"] is True and veri["temel"]["settings"]["emotion_tags"] is False
    assert veri["karar"]["sonuc"] in ("KABUL", "RET")


# ---------- egit.sh ve README ----------

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash yok")
def test_egit_sh_sozdizimi():
    sonuc_ = subprocess.run(["bash", "-n", str(FINETUNE / "egit.sh")], capture_output=True, text=True)
    assert sonuc_.returncode == 0, sonuc_.stderr


def test_egit_sh_ayarlar_ve_guvenlik():
    metin = (FINETUNE / "egit.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in metin
    for ad in ("VERI", "EPOCH", "BATCH", "GRAD_ACCUM", "LORA_R", "LORA_ALPHA", "OGRENME_HIZI", "CIHAZ",
               "TAM_INCE_AYAR", "DEPO_DIZIN", "ADIM", "MTL_TABAN"):
        assert f'{ad}="${{{ad}:-' in metin, ad
    for parca in ("setup.py", "train.py", "merge_lora.py", "PYTORCH_ENABLE_MPS_FALLBACK=1", "out of memory",
                  "T3_FINETUNED=", "T3_EMOTION_TAGS=1", "uvicorn app.main:app", "anahtarı bulunamadı"):
        assert parca in metin, parca


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash yok")
def test_egit_sh_gecersiz_ayar_turkce_hata():
    ortam = dict(os.environ, BATCH="iki", ADIM="yamala")
    sonuc_ = subprocess.run(["bash", str(FINETUNE / "egit.sh")], capture_output=True, text=True, env=ortam)
    assert sonuc_.returncode == 1 and "BATCH pozitif bir tam sayı olmalı" in sonuc_.stderr


def test_readme_bolumleri():
    metin = (FINETUNE / "README.md").read_text(encoding="utf-8")
    for parca in ("Veri", "Lisans", "T3_FINETUNED", "T3_EMOTION_TAGS=1", "egit.sh", "degerlendir.py", "hazirla.py",
                  "senaryo.py", "KAYIT_REHBERI.md", "--reference-only", "Multilingual"):
        assert parca in metin, parca
