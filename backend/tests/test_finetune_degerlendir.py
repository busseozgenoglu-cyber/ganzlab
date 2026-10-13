"""İnce ayar hattının son halkası: ``finetune/degerlendir.py`` (kabul ölçütü), ``finetune/egit.sh`` (sözdizimi) ve
``finetune/README.md``. Model yüklenmez: sonuçlar gerçek ``app.bench.summarize`` ile el yapımı cümle ölçümlerinden
üretilir; kuru çalışma sahte arka uçla yapılır (torch / chatterbox gerekmez).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
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


def sonuc(aralik: float, hece: float, qc_fail: int, n: int = 6, ad: str = "chatterbox", hata: int = 0,
          **ayar) -> dict:
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
    for k in range(hata):                    # run_bench'in hatalı cümle satırı: ölçüm yok, "error" alanı var
        satirlar.append({"id": f"h{k + 1:02d}", "category": "nötr", "text": "Üretilemeyen cümle.",
                         "input_text": "Üretilemeyen cümle.", "error": "RuntimeError: sahte hata"})
    ayarlar = {"backend": ad, "exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "pipeline": False,
               "ref": None, "seed": 1, "repeat": 1, "emotion_tags": False}
    ayarlar.update(ayar)
    return {"version": bench.VERSION, "created": "2026-10-13T12:00:00+03:00",
            "backend": {"name": ad, "sr": 24000}, "settings": ayarlar, "sentences": satirlar, "summary": bench.summarize(satirlar)}


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
    assert not _kalan(nedenler) and len(nedenler) == 6
    assert any("Üretim hatası artmadı (temel 0, ince 0" in n for n in nedenler)
    assert any("ölçülen cümle sayısı azalmadı (6 → 6)" in n for n in nedenler)
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


def test_ret_basarili_cumle_sayisi_azaldi():
    kabul, nedenler = degerlendir.karar_ver(TEMEL, sonuc(17.8, 4.8, 1, n=5))
    assert kabul is False
    kalan = _kalan(nedenler)
    assert len(kalan) == 1 and "Başarıyla ölçülen cümle sayısı azaldı (temel 6 → ince 5)" in kalan[0]


def test_ret_hatali_cumleler_ozetten_dusse_de_sayilir():
    """50 cümleden 38'i hata verip 12'si iyi çıkan ince model KABUL almamalı (özet yalnız 12 cümleye dayanır)."""
    temel = sonuc(13.5, 4.6, 0, n=50)
    ince = sonuc(17.8, 4.8, 0, n=12, hata=38)
    assert ince["summary"]["n"] == 12 and ince["summary"]["qc_fail_count"] == 0
    kabul, nedenler = degerlendir.karar_ver(temel, ince)
    assert kabul is False
    metin = " ".join(_kalan(nedenler))
    assert "üretim hatası arttı (temel 0 → ince 38 cümle)" in metin
    assert "Başarıyla ölçülen cümle sayısı azaldı (temel 50 → ince 12)" in metin
    # yalnız özet verilse de "errors" alanından sayılır
    kabul2, nedenler2 = degerlendir.karar_ver(temel["summary"], ince["summary"])
    assert kabul2 is False and any("38 cümle" in n for n in _kalan(nedenler2))


def test_hata_sayisi_esitse_gecer():
    kabul, nedenler = degerlendir.karar_ver(sonuc(13.5, 4.6, 1, hata=2), sonuc(17.8, 4.8, 1, hata=2))
    assert kabul is True and any("Üretim hatası artmadı (temel 2, ince 2" in n for n in nedenler)


# ---------- kıyasın adilliği ----------

def test_metin_etiketi_iki_kosuda_ayni():
    assert degerlendir.metin_etiketi(pipeline=False, etiketli=True) is False   # ham: önek arka uçta
    assert degerlendir.metin_etiketi(pipeline=True, etiketli=True) is True     # boru hattı: iki koşu da etiketli
    assert degerlendir.metin_etiketi(pipeline=True, etiketli=False) is False


def test_ayar_farklari_turkce_uyari():
    a = degerlendir.kiyas_ayarlari({"pipeline": False, "ref": "/x/ses.wav", "seed": 1, "exaggeration": 0.5,
                                    "cfg_weight": 0.5, "temperature": 0.8}, 24)
    b = degerlendir.kiyas_ayarlari({"pipeline": True, "ref": "/baska/yer/ses.wav", "seed": 2, "exaggeration": 0.5,
                                    "cfg_weight": 0.3, "temperature": 0.8, "sentences_file": "baska.txt"}, 10)
    uyarilar = degerlendir.ayar_farklari(a, b)
    metin = " ".join(uyarilar)
    assert all("kıyas adil olmayabilir" in u for u in uyarilar)
    assert "boru hattı farklı (temel: hayır, ince ayar: evet)" in metin
    assert "tohum farklı (temel: 1, ince ayar: 2)" in metin and "cfg_weight farklı" in metin
    assert "cümle sayısı farklı (temel: 24, ince ayar: 10)" in metin and "cümle dosyası farklı" in metin
    assert "referans" not in metin                       # aynı dosya adı → aynı referans
    assert degerlendir.ayar_farklari(a, dict(a)) == []


def test_main_farkli_ayarli_sonuclar_uyarir(tmp_path, capsys):
    a = _yaz(tmp_path / "temel.json", TEMEL)
    b = _yaz(tmp_path / "ince.json", sonuc(17.8, 4.8, 1, pipeline=True, seed=7))
    rapor = tmp_path / "rapor.json"
    assert degerlendir.main(["--temel", a, "--ince-sonuc", b, "--cikti", str(rapor)]) == 0
    cikti = capsys.readouterr().out
    assert "kıyas adil olmayabilir" in cikti and "boru hattı farklı" in cikti and "tohum farklı" in cikti
    veri = json.loads(rapor.read_text(encoding="utf-8"))
    assert len(veri["uyarilar"]) == 2


def test_main_hazir_temel_ile_yeni_kosu_ayarlarini_karsilastirir(tmp_path, capsys):
    temel = sonuc(13.5, 4.6, 0, n=2, pipeline=True, ref="/a/ref.wav", seed=1)
    a = _yaz(tmp_path / "temel.json", temel)
    cumleler = tmp_path / "cumleler.txt"
    cumleler.write_text("nötr|Bugün hava güzel.\nmutlu|Sınavı geçtim!\n", encoding="utf-8")
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), speechlike(60, 24000, seed=2, range_st=15.0), 24000)
    agirlik = tmp_path / "t3.safetensors"
    agirlik.write_bytes(b"0")
    kod = degerlendir.main(["--temel", a, "--arka-uc", "fake", "--ref", str(ref), "--ince", str(agirlik),
                            "--cumleler", str(cumleler), "--quiet", "--cihaz", "cpu"])
    assert kod in (0, 2)
    yazi = capsys.readouterr()
    assert "UYARI: boru hattı farklı (temel: evet, yeni koşu: hayır) — kıyas adil olmayabilir." in yazi.err
    assert "cümle dosyası farklı" in yazi.err and "tohum" not in yazi.err and "referans" not in yazi.err


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
    gorulen, metinler = [], []
    asil = degerlendir.model_kos

    def izle(etiket, **kw):
        gorulen.append((etiket, os.environ.get("T3_FINETUNED"), kw["etiketli"]))
        metinler.append(kw["metin_etiketli"])
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
    # iki koşu aynı metni alır (ham modda etiketsiz); duygu öneki yalnız ince koşunun arka ucunda (T3_EMOTION_TAGS)
    assert metinler == [False, False]
    assert veri["ince"]["settings"]["emotion_tags"] is False and veri["temel"]["settings"]["emotion_tags"] is False
    assert veri["ince"]["settings"]["t3_emotion_tags"] is True and veri["temel"]["settings"]["t3_emotion_tags"] is False
    assert veri["uyarilar"] == []
    assert [s["input_text"] for s in veri["temel"]["sentences"]] == [s["input_text"] for s in veri["ince"]["sentences"]]
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


# ---------- egit.sh: sahte eğitim deposuna karşı yama ve akış ----------
#
# Sahte depo, gokhaneraslan/chatterbox-finetuning'in yamalanan satırlarını aynen taşır (içe aktarımlar,
# check_pretrained_models, bf16, persistent_workers, text_to_tokens, mtl_tts dosya adı) ama torch istemez:
# train.py ön işlemede her metadata satırı için bir .pt yazar ve hangi taban sınıfını gördüğünü yazdırır.

SAHTE_CONFIG = '''from dataclasses import dataclass, field
from typing import List

@dataclass
class TrainConfig:
    model_dir: str = "./pretrained_models"
    csv_path: str = "./MyTTSDataset/metadata.csv"
    wav_dir: str = "./MyTTSDataset/wavs"
    preprocessed_dir = "./MyTTSDataset/preprocess"
    output_dir: str = "./chatterbox_output"
    is_inference = False
    ljspeech = True # Set True if the dataset format is ljspeech
    json_format = False # Set True if the dataset format is json
    preprocess = True # If you've already done preprocessing once, set it to false.
    is_turbo: bool = False # Set True if you're training Turbo
    is_lora: bool = True   # True: Efficient LoRA training
    lora_r: int = 128
    lora_alpha: int = 256
    lora_modules_to_save: List[str] = field(default_factory=lambda: ["text_emb", "text_head"])
    new_vocab_size: int = 52260 if is_turbo else 2454
    batch_size: int = 32         # Adjust based on VRAM (2, 4, 8)
    grad_accum: int = 1        # Effective Batch Size = Batch * Accum
    learning_rate: float = 1e-4 if is_lora else 1e-5  # T3 is sensitive, keep low
    num_epochs: int = 10 if is_lora else 30
    dataloader_num_workers: int = 8
'''

SAHTE_TRAIN = '''import os
import sys
from src.chatterbox_.tts import ChatterboxTTS
from src.utils import check_pretrained_models
from src.config import TrainConfig


def egitim_argumanlari(cfg):
    import torch
    return dict(
        bf16=True,
        dataloader_persistent_workers=True,
    )


def main():
    cfg = TrainConfig()
    if not check_pretrained_models(mode="chatterbox"):
        sys.exit(1)
    print("taban:", ChatterboxTTS.AD, "isci:", cfg.dataloader_num_workers, "batch:", cfg.batch_size)
    if cfg.preprocess:
        os.makedirs(cfg.preprocessed_dir, exist_ok=True)
        n = 0
        for satir in open(cfg.csv_path, encoding="utf-8"):
            if satir.strip():
                open(os.path.join(cfg.preprocessed_dir, satir.split("|")[0] + ".pt"), "w").write("x")
                n += 1
        print(f"Preprocessing completed! Success: {n}/{n}")
    print("pt:", " ".join(sorted(f for f in os.listdir(cfg.preprocessed_dir) if f.endswith(".pt"))))
    if os.environ.get("SAHTE_OOM"):
        print("torch.OutOfMemoryError: CUDA out of memory.")
        sys.exit(1)
    os.makedirs(os.path.join(cfg.output_dir, "new_lang_adapter"), exist_ok=True)


if __name__ == "__main__":
    main()
'''

SAHTE_MERGE = '''import os
from src.chatterbox_.tts import ChatterboxTTS
from src.config import TrainConfig

cfg = TrainConfig()
open(os.path.join(cfg.output_dir, "t3_finetuned_merged.safetensors"), "wb").write(b"x" * 100)
print("MERGE COMPLETE", ChatterboxTTS.AD)
'''

SAHTE_DOSYALAR = {
    "src/__init__.py": "",
    "src/config.py": SAHTE_CONFIG,
    "src/utils.py": 'def check_pretrained_models(model_dir="pretrained_models", mode="chatterbox"):\n'
                    '    return False   # İngilizce dosyalar yok: yamasız train.py burada durur\n',
    "src/preprocess_ljspeech.py": "from src.chatterbox_.tts import ChatterboxTTS, punc_norm\n\n\n"
                                  "def belirtecle(tts_engine, clean_text):\n"
                                  "    return tts_engine.tokenizer.text_to_tokens(clean_text).squeeze(0).cpu()\n",
    "src/chatterbox_/__init__.py": "",
    "src/chatterbox_/tts.py": 'class ChatterboxTTS:\n    AD = "EN"\n\n\ndef punc_norm(t):\n    return t\n',
    "src/chatterbox_/mtl_tts.py": 'class ChatterboxMultilingualTTS:\n    AD = "MTL"\n\n\ndef punc_norm(t):\n'
                                  '    return t\n\n\ndef from_local(ckpt_dir):\n    import torch\n'
                                  '    torch.load(ckpt_dir / "ve.pt", weights_only=True)\n'
                                  '    return ckpt_dir / "t3_mtl23ls_v2.safetensors"\n',
    "train.py": SAHTE_TRAIN,
    "merge_lora.py": SAHTE_MERGE,
    "requirements.txt": "peft==0.17.1\n",
}


@pytest.fixture()
def sahte_depo(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("bash yok")
    depo = tmp_path / "chatterbox-finetuning"
    for ad, icerik in SAHTE_DOSYALAR.items():
        yol = depo / ad
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(icerik, encoding="utf-8")
    if shutil.which("git"):
        git = ["git", "-C", str(depo), "-c", "user.email=test@sesklon", "-c", "user.name=test"]
        subprocess.run(["git", "init", "-q", str(depo)], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "ilk"], check=True)
    (depo / ".venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, depo / ".venv" / "bin" / "python")
    veri = tmp_path / "MyTTSDataset"
    (veri / "wavs").mkdir(parents=True)
    _metadata(veri, ["mutlu_0001|[mutlu] Merhaba!|[mutlu] Merhaba!", "normal_0001|Selam.|Selam."])
    return depo, veri


def _metadata(veri: Path, satirlar: list[str]) -> None:
    (veri / "metadata.csv").write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    for s in satirlar:
        (veri / "wavs" / f"{s.split('|')[0]}.wav").write_bytes(b"RIFF")


def egit(depo: Path, veri: Path, **ortam) -> subprocess.CompletedProcess:
    env = dict(os.environ, DEPO_DIZIN=str(depo), VERI=str(veri), CIHAZ="cpu", PYTHON=sys.executable)
    env.pop("ISCI", None)
    env.update({k: str(v) for k, v in ortam.items()})
    return subprocess.run(["bash", str(FINETUNE / "egit.sh")], capture_output=True, text=True, env=env, timeout=120)


def test_egit_yamala_sahte_depo_mtl(sahte_depo):
    depo, veri = sahte_depo
    r = egit(depo, veri, ADIM="yamala", ISCI=0, EPOCH=3, OGRENME_HIZI="5e-5")
    assert r.returncode == 0, r.stderr
    cfg = (depo / "src" / "config.py").read_text(encoding="utf-8")
    for parca in ("is_turbo: bool = False", "is_lora: bool = True", "new_vocab_size: int = 2454", "lora_r: int = 64",
                  "lora_alpha: int = 128", "batch_size: int = 4", "grad_accum: int = 4", "num_epochs: int = 3",
                  "learning_rate: float = 5e-05", "dataloader_num_workers: int = 0", "json_format = False",
                  f"csv_path: str = {str(veri / 'metadata.csv')!r}", f"preprocessed_dir = {str(veri / 'preprocess')!r}"):
        assert parca in cfg, parca
    train = (depo / "train.py").read_text(encoding="utf-8")
    assert "from src.chatterbox_.mtl_tts import ChatterboxMultilingualTTS as ChatterboxTTS" in train
    assert "if not True:" in train and "def check_pretrained_models" not in train
    assert "bf16=bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())," in train
    assert "dataloader_persistent_workers=bool(cfg.dataloader_num_workers > 0)," in train
    on = (depo / "src" / "preprocess_ljspeech.py").read_text(encoding="utf-8")
    assert "from src.chatterbox_.mtl_tts import ChatterboxMultilingualTTS as ChatterboxTTS, punc_norm" in on
    assert 'text_to_tokens(clean_text, language_id="tr")' in on
    mtl = (depo / "src" / "chatterbox_" / "mtl_tts.py").read_text(encoding="utf-8")
    assert "t3_mtl23ls_v3.safetensors" in mtl and 'weights_only=True, map_location="cpu")' in mtl
    assert "def check_pretrained_models" in (depo / "src" / "utils.py").read_text(encoding="utf-8")   # dokunulmadı
    if shutil.which("git"):                     # git ile geri alınıp yeniden yamalanır: iki çalıştırma aynı sonucu verir
        once = {p: (depo / p).read_text(encoding="utf-8") for p in ("train.py", "src/config.py", "src/chatterbox_/mtl_tts.py")}
        assert egit(depo, veri, ADIM="yamala", ISCI=0, EPOCH=3, OGRENME_HIZI="5e-5").returncode == 0
        assert once == {p: (depo / p).read_text(encoding="utf-8") for p in once}


def test_egit_yamala_mtl0_ozgun_yol_uyarir(sahte_depo):
    depo, veri = sahte_depo
    r = egit(depo, veri, ADIM="yamala", MTL_TABAN=0, TAM_INCE_AYAR=1)
    assert r.returncode == 0, r.stderr
    train = (depo / "train.py").read_text(encoding="utf-8")
    assert "from src.chatterbox_.tts import ChatterboxTTS" in train and "mtl_tts" not in train
    cfg = (depo / "src" / "config.py").read_text(encoding="utf-8")
    assert "is_lora: bool = False" in cfg
    assert "MTL_TABAN=0" in r.stderr and "güvenilmez" in r.stderr


def test_egit_akisi_on_isleme_temizligi_isaret_ve_taban_kaydi(sahte_depo):
    depo, veri = sahte_depo
    pre = veri / "preprocess"
    pre.mkdir()
    (pre / "reddedilen_0009.pt").write_text("eski")         # önceki hazırlıktan kalan: eğitime sızmamalı
    r = egit(depo, veri, ADIM="egit")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "taban: MTL" in r.stdout and "Eski ön işleme dosyaları siliniyor: 1 .pt" in r.stdout
    assert "pt: mutlu_0001.pt normal_0001.pt" in r.stdout
    assert not (pre / "reddedilen_0009.pt").exists()
    isaret = (pre / ".sesklon_taban").read_text(encoding="utf-8")
    assert isaret.startswith("mtl-v3-tr ") and len(isaret.split()[1]) == 64          # taban + metadata sha256
    kayit = (depo / "chatterbox_output" / "sesklon_taban.txt").read_text(encoding="utf-8")
    assert "MTL_TABAN=1" in kayit and "MTL_T3_SURUM=v3" in kayit and "TAM_INCE_AYAR=0" in kayit

    r2 = egit(depo, veri, ADIM="egit")                        # veri ve taban aynı → ön işleme atlanır
    assert r2.returncode == 0 and "Ön işleme atlanıyor" in r2.stdout and "Preprocessing completed" not in r2.stdout

    _metadata(veri, ["mutlu_0001|[mutlu] Merhaba!|[mutlu] Merhaba!"])   # veri değişti → yeniden ön işle
    r3 = egit(depo, veri, ADIM="egit")
    assert r3.returncode == 0 and "Ön işleme açık" in r3.stdout and "pt: mutlu_0001.pt\n" in r3.stdout

    r4 = egit(depo, veri, ADIM="egit", MTL_T3_SURUM="v2")     # taban değişti → yeniden ön işle
    assert r4.returncode == 0 and "Ön işleme açık" in r4.stdout

    # birleştirme eğitimdeki tabanla (v2) yapılmalı
    r5 = egit(depo, veri, ADIM="birlestir")
    assert r5.returncode == 1 and "farklı bir tabanla" in r5.stderr and "MTL_T3_SURUM=v2" in r5.stderr
    r6 = egit(depo, veri, ADIM="birlestir", MTL_T3_SURUM="v2")
    assert r6.returncode == 0, r6.stderr
    assert "MERGE COMPLETE MTL" in r6.stdout and "Eğitim tabanı doğrulandı" in r6.stdout
    assert "T3_MODEL=v2 uvicorn app.main:app" in r6.stdout and "T3_EMOTION_TAGS=1" in r6.stdout
    assert "t3_finetuned_merged.safetensors" in r6.stdout


def test_egit_oom_onerisi(sahte_depo):
    depo, veri = sahte_depo
    r = egit(depo, veri, ADIM="egit", SAHTE_OOM=1, BATCH=4, GRAD_ACCUM=4)
    assert r.returncode == 1
    assert "ADIM=egit BATCH=2 GRAD_ACCUM=8" in r.stderr and "train.py başarısız" in r.stderr
    assert not (depo / "chatterbox_output" / "sesklon_taban.txt").exists()


def test_egit_bos_metin_turkce_hata(sahte_depo):
    depo, veri = sahte_depo
    _metadata(veri, ["normal_0001|Selam.|Selam.", "normal_0002||", "normal_0003| | "])
    r = egit(depo, veri, ADIM="egit")
    assert r.returncode == 1
    assert "metni boş satırlar var: 2 satır (ilk: normal_0002, normal_0003)" in r.stderr and "ASR" in r.stderr


def test_egit_sayisal_kayit_adi_turkce_hata(sahte_depo):
    depo, veri = sahte_depo
    _metadata(veri, ["0001|Selam.|Selam.", "0002|Merhaba.|Merhaba."])
    r = egit(depo, veri, ADIM="egit")
    assert r.returncode == 1 and "Tüm kayıt adları yalnız rakam" in r.stderr and "ön ek" in r.stderr
