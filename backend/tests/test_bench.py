"""Kıyaslama betiği (``app.bench``): şema, ayar farkının ölçülmesi, karşılaştırma, referans ölçümü, boru hattı
modu, komut satırı ve cümle dosyası. Hepsi sahte arka uçla (torch / chatterbox gerekmez).

pyin pahalı olduğu için cümleler kısa tutulur ve iki ayarın sonuçları modül düzeyinde bir kez hesaplanır.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app import bench, config
from app.backends.fake import FakeBackend, speechlike
from app.bench import analyze_files, compare, load_sentences, run_bench, summarize

CUMLELER = [
    {"id": "t1", "category": "nötr", "text": "Bugün hava çok güzel, dışarı çıkalım mı?"},
    {"id": "t2", "category": "mutlu", "text": "Sonunda kabul mektubu geldi, okula gidiyorum!"},
    {"id": "t3", "category": "soru", "text": "Sen gerçekten bunu tek başına mı hallettin?"},
]

CUMLE_ANAHTARLARI = {"id", "category", "text", "input_text", "duration_s", "gen_s", "rtf", "f0", "syllables_per_sec",
                     "chars_per_sec", "pauses", "dynamic_range_db", "qc", "speech_ratio"}
F0_ANAHTARLARI = {"median_hz", "min_hz", "max_hz", "range_semitones", "std_semitones", "voiced_ratio"}
OZET_ANAHTARLARI = {"n", "rtf_mean", "rtf_median", "range_semitones_median", "range_semitones_mean",
                    "std_semitones_median", "syllables_per_sec_mean", "dynamic_range_db_median", "qc_score_mean",
                    "qc_fail_count", "pauses_per_sentence", "verdict", "recommendations"}


@pytest.fixture(scope="module")
def iki_ayar():
    """Aynı tohumla exaggeration 0.2 ve 1.0 sonuçları (bir kez hesaplanır)."""
    a = run_bench("fake", CUMLELER, settings={"exaggeration": 0.2, "seed": 1})
    b = run_bench("fake", CUMLELER, settings={"exaggeration": 1.0, "seed": 1})
    return a, b


@pytest.fixture()
def sentetik_wav(tmp_path) -> Path:
    yol = tmp_path / "referans.wav"
    sf.write(str(yol), speechlike(70, 24000, seed=3, range_st=15.0), 24000)
    return yol


# ---------- şema ----------

def test_sahte_arka_ucla_sema_tam(iki_ayar):
    r, _ = iki_ayar
    assert set(r) == {"version", "created", "backend", "settings", "sentences", "summary"}
    assert r["version"] == 1 and "T" in r["created"]
    assert r["backend"]["name"] == "fake" and r["backend"]["sr"] == 24000 and r["backend"]["model_id"] == "sahte-sinyal"
    st = r["settings"]
    for k in ("backend", "ref", "exaggeration", "cfg_weight", "temperature", "seed", "pipeline", "repeat",
              "emotion_tags", "language", "device"):
        assert k in st, k
    assert st["backend"] == "fake" and st["exaggeration"] == 0.2 and st["seed"] == 1 and st["pipeline"] is False
    assert len(r["sentences"]) == 3
    for s in r["sentences"]:
        assert CUMLE_ANAHTARLARI <= set(s), set(s) ^ CUMLE_ANAHTARLARI
        assert set(s["f0"]) == F0_ANAHTARLARI
        assert set(s["pauses"]) == {"count", "median_ms"}
        assert set(s["qc"]) == {"score", "decision", "reasons"} and len(s["qc"]["reasons"]) <= 2
        assert s["duration_s"] > 0.5 and s["gen_s"] >= 0 and s["rtf"] is not None
        assert s["f0"]["range_semitones"] > 0 and s["dynamic_range_db"] > 0
    sm = r["summary"]
    assert OZET_ANAHTARLARI <= set(sm)
    assert sm["n"] == 3 and isinstance(sm["verdict"], str) and sm["recommendations"]
    json.dumps(r, ensure_ascii=False)          # JSON'a doğrudan yazılabilir


def test_exaggeration_araligi_acar_ve_compare_kazanani_dogru(iki_ayar):
    a, b = iki_ayar
    ra, rb = a["summary"]["range_semitones_median"], b["summary"]["range_semitones_median"]
    assert rb - ra >= 4.0, (ra, rb)
    c = compare(a, b)
    assert c["winner"] == "b"
    assert set(c) >= {"summary", "sentences", "winner"}
    satir = next(x for x in c["summary"] if x["metric"] == "range_semitones_median")
    assert set(satir) >= {"metric", "a", "b", "delta", "better"}
    assert satir["better"] == "b" and satir["delta"] == pytest.approx(rb - ra, abs=0.01)
    assert [s["id"] for s in c["sentences"]] == ["t1", "t2", "t3"]
    assert all(set(s) >= {"id", "text", "range_a", "range_b", "delta"} and s["delta"] > 0 for s in c["sentences"])
    assert compare(b, a)["winner"] == "a"
    tablo = bench.format_compare(c)
    assert "Kazanan: B" in tablo and "Tonlama aralığı medyanı" in tablo


def test_compare_ayni_sonuc_berabere(iki_ayar):
    a, _ = iki_ayar
    c = compare(a, a)
    assert c["winner"] == "berabere"
    assert all(x["better"] == "-" for x in c["summary"])
    assert all(s["delta"] == 0 for s in c["sentences"])


def test_summarize_karar_ve_oneriler():
    def cumle(rng, std=3.0, rtf=0.5, karar="accept"):
        return {"f0": {"range_semitones": rng, "std_semitones": std}, "rtf": rtf, "syllables_per_sec": 5.0,
                "dynamic_range_db": 20.0, "qc": {"score": 90, "decision": karar}, "pauses": {"count": 1}}

    iyi = summarize([cumle(18.0), cumle(19.0)])
    assert iyi["verdict"] == "ifadeli — Gemini TTS düzeyi" and iyi["qc_fail_count"] == 0
    orta = summarize([cumle(15.0), cumle(16.0)])
    assert orta["verdict"].startswith("orta") and any("--reference-only" in r for r in orta["recommendations"])
    duz = summarize([cumle(10.0, std=2.0, rtf=4.6, karar="retry_seed"), cumle(12.0, std=2.0, rtf=4.6)])
    assert duz["verdict"] == "düz (robotik) — ince ayar gerekli"
    metin = " ".join(duz["recommendations"])
    assert "finetune/README.md" in metin and "chatterbox-mlx" in metin and "qc=false" in metin
    assert "cfg_weight 0.4+" in metin and "temperature 0.6" in metin and "tekdüze" in metin
    assert duz["qc_fail_count"] == 1 and duz["rtf_mean"] == 4.6
    hatali = summarize([{"id": "x", "error": "RuntimeError: bozuk"}])
    assert hatali["n"] == 0 and hatali["errors"] == 1 and hatali["recommendations"]


# ---------- referans kayıtları ----------

def test_analyze_files_sentetik_wav(sentetik_wav):
    rows = analyze_files([sentetik_wav])
    assert len(rows) == 1
    r = rows[0]
    assert r["file"] == str(sentetik_wav) and r["duration_s"] > 3.0
    assert set(r["f0"]) == F0_ANAHTARLARI and r["f0"]["range_semitones"] > 0
    assert "syllables_per_sec" in r and set(r["pauses"]) == {"count", "median_ms"}
    assert r["comment"] and "referansın aralığının altında" in r["comment"]
    with pytest.raises(FileNotFoundError):
        analyze_files([sentetik_wav.parent / "yok.wav"])


def test_referans_yorumu_esikleri():
    assert bench.reference_comment(17.0).startswith("ifadeli — klon için iyi")
    assert bench.reference_comment(14.0).startswith("orta")
    assert bench.reference_comment(9.0).startswith("düz — daha coşkulu bir kayıt deneyin")


# ---------- boru hattı ----------

def test_pipeline_engine_zincirinden_gecer(monkeypatch, sentetik_wav):
    monkeypatch.setattr(config, "DEVICE", None)
    from app.engine import Engine

    cagrilar = []
    asil = Engine.synthesize

    def casus(self, *args, **kw):
        cagrilar.append((args, kw))
        return asil(self, *args, **kw)

    monkeypatch.setattr(Engine, "synthesize", casus)
    r = run_bench("fake", CUMLELER[:2], pipeline=True, ref=sentetik_wav, settings={"seed": 4})
    assert len(cagrilar) == 2
    args, kw = cagrilar[0]
    assert args[0] == CUMLELER[0]["text"] and args[1] == "tr"
    assert args[2].voice_id == "bench" and args[2].base == sentetik_wav
    assert kw["qc"] is True and kw["subtitles"] is False
    assert r["settings"]["pipeline"] is True and r["settings"]["ref"] == str(sentetik_wav)
    assert r["summary"]["n"] == 2 and r["summary"]["range_semitones_median"] > 0
    for s in r["sentences"]:
        assert s["pipeline"]["chunks"] >= 1 and s["qc"]["score"] is not None and s["gen_s"] > 0


# ---------- duygu etiketleri ----------

def test_emotion_tags_yalnizca_duygu_kategorileri():
    model = FakeBackend()
    cumleler = [{"id": "a", "category": "mutlu", "text": "Harika bir haber aldım!"},
                {"id": "b", "category": "nötr", "text": "Kapıyı kapatmayı unutma."}]
    r = run_bench("fake", cumleler, emotion_tags=True, model=model)
    metinler = [c["text"] for c in model.calls]
    assert metinler[0] == "[mutlu] Harika bir haber aldım!"
    assert metinler[1] == "Kapıyı kapatmayı unutma."
    assert r["sentences"][0]["input_text"].startswith("[mutlu] ") and r["sentences"][0]["text"] == cumleler[0]["text"]
    assert r["settings"]["emotion_tags"] is True
    # etiketsiz koşuda önek yok
    model2 = FakeBackend()
    run_bench("fake", cumleler[:1], model=model2)
    assert model2.calls[0]["text"] == "Harika bir haber aldım!"


def test_etiket_eslemesi():
    for k in ("üzgün", "mutlu", "heyecanlı", "kızgın", "fısıltı", "sakin"):
        assert bench.emotion_label(k) == k
        assert bench.tagged_text({"category": k, "text": "Merhaba."}, True) == f"[{k}] Merhaba."
    for k in ("nötr", "soru", "ünlem", "uzun", "sayı", "günlük"):
        assert bench.emotion_label(k) is None
        assert bench.tagged_text({"category": k, "text": "Merhaba."}, True) == "Merhaba."
    assert bench.emotion_label("MUTLU") == "mutlu" and bench.emotion_label("KIZGIN") == "kızgın"   # Türkçe küçük harf


# ---------- komut satırı ----------

def test_main_limit_out_json(tmp_path, capsys):
    out = tmp_path / "sonuc.json"
    assert bench.main(["--backend", "fake", "--limit", "2", "--seed", "1", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1 and len(data["sentences"]) == 2 and data["summary"]["n"] == 2
    assert data["settings"]["backend"] == "fake" and data["settings"]["seed"] == 1
    yazi = capsys.readouterr().out
    assert "Aralık(st)" in yazi and "Hece/sn" in yazi and "Karar:" in yazi and "Öneriler:" in yazi
    assert "ı" in out.read_text(encoding="utf-8")          # ensure_ascii=False: Türkçe harfler kaçışsız


def test_main_quiet_susar(tmp_path, capsys):
    out = tmp_path / "q.json"
    assert bench.main(["--backend", "fake", "--limit", "1", "--quiet", "--out", str(out)]) == 0
    yakalanan = capsys.readouterr()
    assert yakalanan.out == "" and yakalanan.err == "" and out.exists()


def test_main_reference_only(sentetik_wav, capsys):
    assert bench.main(["--reference-only", str(sentetik_wav)]) == 0
    yazi = capsys.readouterr().out
    assert "referans.wav" in yazi and "Aralık(st)" in yazi and "yarım ton" in yazi


def test_main_compare(iki_ayar, tmp_path, capsys):
    a, b = iki_ayar
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    pb.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "fark.json"
    assert bench.main(["--compare", str(pa), str(pb), "--out", str(out)]) == 0
    assert "Kazanan: B" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["winner"] == "b"


def test_bilinmeyen_arka_uc_turkce_hata(capsys):
    assert bench.main(["--backend", "yok-boyle-bir-model", "--limit", "1"]) == 1
    err = capsys.readouterr().err
    assert "Bilinmeyen arka uç" in err and "yok-boyle-bir-model" in err


def test_eksik_dosyalar_turkce_hata(tmp_path, capsys):
    assert bench.main(["--backend", "fake", "--ref", str(tmp_path / "yok.wav")]) == 1
    assert "Referans dosyası bulunamadı" in capsys.readouterr().err
    assert bench.main(["--reference-only", str(tmp_path / "yok.wav")]) == 1
    assert "bulunamadı" in capsys.readouterr().err
    bozuk = tmp_path / "bozuk.json"
    bozuk.write_text("{", encoding="utf-8")
    assert bench.main(["--compare", str(bozuk), str(bozuk)]) == 1
    assert "geçerli bir JSON değil" in capsys.readouterr().err


# ---------- cümle dosyası ----------

def test_cumle_dosyasi_kapsami():
    cumleler = load_sentences()
    assert len(cumleler) >= 30
    kategoriler: dict[str, list[str]] = {}
    for c in cumleler:
        kategoriler.setdefault(c["category"], []).append(c["text"])
        assert not c["text"].startswith("["), c          # cümleler duygu etiketi taşımaz
    for k in bench.ALL_CATEGORIES:
        assert len(kategoriler.get(k, [])) >= 2, k
    assert set(kategoriler) <= set(bench.ALL_CATEGORIES)
    assert all(len(t) >= 120 for t in kategoriler["uzun"])
    sayilar = " ".join(kategoriler["sayı"])
    for parca in ("14:30'da", "%12", "Dr.", "3,5 kg", "2024"):
        assert parca in sayilar, parca
    assert [c["id"] for c in cumleler[:2]] == ["n01", "n02"]
    assert len({c["id"] for c in cumleler}) == len(cumleler)
    assert len({c["text"] for c in cumleler}) == len(cumleler)      # tekrar yok


def test_load_sentences_yorum_ve_bos_satirlari_atlar(tmp_path):
    dosya = tmp_path / "set.txt"
    dosya.write_text("# yorum satırı\n\n  \nNÖTR|Birinci cümle.\n# başka yorum\nmutlu| İkinci cümle! \n",
                     encoding="utf-8")
    assert load_sentences(dosya) == [{"id": "n01", "category": "nötr", "text": "Birinci cümle."},
                                     {"id": "n02", "category": "mutlu", "text": "İkinci cümle!"}]
    bozuk = tmp_path / "bozuk.txt"
    bozuk.write_text("ayraçsız satır\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_sentences(bozuk)
    assert "satır 1" in str(exc.value)
    with pytest.raises(FileNotFoundError):
        load_sentences(tmp_path / "yok.txt")


# ---------- yardımcılar ----------

def test_dinamik_aralik_ve_tekrar_medyani():
    sr = 24000
    sabit = np.full(sr, 0.1, dtype=np.float32)
    assert bench.dynamic_range_db(sabit, sr) == pytest.approx(0.0, abs=0.01)
    degisken = np.concatenate([np.full(sr // 2, 0.3), np.full(sr // 2, 0.03)]).astype(np.float32)
    assert bench.dynamic_range_db(degisken, sr) == pytest.approx(20.0, abs=0.5)
    model = FakeBackend()
    r = run_bench("fake", CUMLELER[:1], model=model, repeat=2, settings={"seed": 5})
    s = r["sentences"][0]
    assert len(model.calls) == 2 and s["runs"] == 2 and len(s["range_semitones_runs"]) == 2
    assert s["f0"]["range_semitones"] == pytest.approx(float(np.median(s["range_semitones_runs"])), abs=0.01)
    assert r["settings"]["repeat"] == 2
