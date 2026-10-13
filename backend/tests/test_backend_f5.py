"""F5-TTS Türkçe adaptörü — sahte ``torch`` / ``f5_tts`` / ``f5_tts.api`` modülleriyle.

Bu kutuda torch / f5_tts KURULU DEĞİL: sahte modüller ``sys.modules``'a konur ve ``__spec__`` verilir ki
``importlib.util.find_spec`` (``BaseBackend.available``) onları kurulu saysın. Sahte ``F5TTS`` sınıfı gerçek
imzayı (``src/f5_tts/api.py``) taklit eder ve aldığı argümanları kaydeder.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import inspect
import logging
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app import backends, config
from app.backends import BackendUnavailable
from app.backends.f5_turkish import F5TurkishBackend
from app.backends.fake import speechlike
from app.engine import Engine, VoiceRefs

F5_KURULU = importlib.util.find_spec("f5_tts") is not None


def _modul(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


@pytest.fixture()
def sahte_f5(monkeypatch, tmp_path):
    """Sahte torch + f5_tts.api.F5TTS; config yolları tmp_path'teki sahte dosyalara."""
    kayit: dict = {"init": [], "infer": [], "transcribe": [], "seed": [], "sr": 24000, "transkript": "referans metni"}

    class F5TTS:
        def __init__(self, model="F5TTS_v1_Base", ckpt_file="", vocab_file="", ode_method="euler", use_ema=True,
                     vocoder_local_path=None, device=None, hf_cache_dir=None):
            kayit["init"].append({"model": model, "ckpt_file": ckpt_file, "vocab_file": vocab_file, "device": device,
                                  "ode_method": ode_method, "use_ema": use_ema})
            self.target_sample_rate = 24000

        def transcribe(self, ref_audio, language=None):
            kayit["transcribe"].append({"ref_audio": ref_audio, "language": language})
            return kayit["transkript"]

        def infer(self, ref_file, ref_text, gen_text, show_info=print, progress=None, target_rms=0.1,
                  cross_fade_duration=0.15, sway_sampling_coef=-1, cfg_strength=2, nfe_step=32, speed=1.0,
                  fix_duration=None, remove_silence=False, file_wave=None, file_spec=None, seed=None):
            kayit["infer"].append({"ref_file": ref_file, "ref_text": ref_text, "gen_text": gen_text, "seed": seed,
                                   "nfe_step": nfe_step, "speed": speed, "show_info": show_info,
                                   "remove_silence": remove_silence})
            wav = speechlike(len(gen_text), kayit["sr"], seed=len(kayit["infer"]))
            return wav, kayit["sr"], None

    torch = _modul("torch", manual_seed=lambda s: kayit["seed"].append(int(s)),
                   load=lambda *a, **k: {}, device=lambda d: f"device({d})",
                   cuda=types.SimpleNamespace(is_available=lambda: False, manual_seed_all=lambda s: None),
                   backends=types.SimpleNamespace(mps=None))
    f5_tts = _modul("f5_tts")
    api = _modul("f5_tts.api", F5TTS=F5TTS)
    f5_tts.api = api
    for name, mod in (("torch", torch), ("f5_tts", f5_tts), ("f5_tts.api", api)):
        monkeypatch.setitem(sys.modules, name, mod)

    ckpt = tmp_path / "f5_tts_turkish_1000000.safetensors"
    ckpt.write_bytes(b"sahte")
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("a\nb\n", encoding="utf-8")
    monkeypatch.setattr(config, "F5_TR_CKPT", str(ckpt))
    monkeypatch.setattr(config, "F5_TR_VOCAB", str(vocab))
    monkeypatch.setattr(config, "DEVICE", "cpu")
    monkeypatch.delenv("F5_TR_MODEL", raising=False)
    monkeypatch.delenv("F5_TR_NFE", raising=False)
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), speechlike(60, 24000, seed=9), 24000)
    kayit.update(ckpt=ckpt, vocab=vocab, ref=ref, tmp=tmp_path)
    return kayit


# ---------- kurulum denetimi / kayıt defteri ----------

def test_f5_sahte_modullerle_kurulu(sahte_f5):
    assert F5TurkishBackend.available() == (True, "kurulu")
    row = next(r for r in backends.describe() if r["name"] == "f5-tr")
    assert row["available"] is True and row["commercial"] is False and row["emotion_controls"] is False
    assert row["license"].startswith("CC-BY-NC 4.0") and "ticari olmayan" in row["license"]
    assert row["label"] == "F5-TTS Türkçe (akış eşleme, A/B için)"


@pytest.mark.skipif(F5_KURULU, reason="f5_tts kurulu; bu test f5_tts'siz kutu içindir")
def test_f5_kurulu_degilken_describe_nedeni():
    row = next(r for r in backends.describe() if r["name"] == "f5-tr")
    assert row["available"] is False and ("f5_tts" in row["reason"] or "torch" in row["reason"])
    assert "pip install f5-tts" in row["reason"]
    assert row["commercial"] is False


def test_f5_yalnizca_f5_tts_eksik_nedeni(sahte_f5, monkeypatch):
    monkeypatch.delitem(sys.modules, "f5_tts")
    monkeypatch.delitem(sys.modules, "f5_tts.api")
    if F5_KURULU:
        pytest.skip("f5_tts gerçekten kurulu")
    ok, neden = F5TurkishBackend.available()
    assert ok is False and "'f5_tts' paketi kurulu değil" in neden and "marduk-ra/F5-TTS-Turkish" in neden
    row = next(r for r in backends.describe() if r["name"] == "f5-tr")
    assert row["available"] is False and "f5_tts" in row["reason"] and row["commercial"] is False
    with pytest.raises(BackendUnavailable) as exc:
        backends.create("f5")
    assert "'f5-tr' arka ucu kullanılamıyor" in str(exc.value)


# ---------- yükleme ----------

def test_f5_create_yukler(sahte_f5):
    m = backends.create("f5-tr", device="cpu")
    assert isinstance(m, F5TurkishBackend) and m.sr == 24000 and m.device == "cpu"
    assert sahte_f5["init"] == [{"model": "F5TTS_v1_Base", "ckpt_file": str(sahte_f5["ckpt"]),
                                 "vocab_file": str(sahte_f5["vocab"]), "device": "cpu", "ode_method": "euler",
                                 "use_ema": True}]
    assert m.model_id == "f5-tts-turkish:f5_tts_turkish_1000000.safetensors"
    info = m.info()
    assert info["ckpt"] == str(sahte_f5["ckpt"]) and info["vocab"] == str(sahte_f5["vocab"])
    assert info["ref_text_required"] is True and info["commercial"] is False and info["name"] == "f5-tr"
    assert info["model_id"] == m.model_id and info["emotion_controls"] is False


def test_f5_yapilandirma_adi_ortamdan(sahte_f5, monkeypatch):
    monkeypatch.setenv("F5_TR_MODEL", "F5TTS_Base")
    monkeypatch.setenv("F5_TR_NFE", "64")
    m = F5TurkishBackend(device="cpu")
    assert sahte_f5["init"][-1]["model"] == "F5TTS_Base" and m.info()["config"] == "F5TTS_Base"
    m.generate("Merhaba.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="Selam.")
    assert sahte_f5["infer"][-1]["nfe_step"] == 64


def test_f5_init_imzasi_suzulur(sahte_f5):
    """Eski bir f5_tts sürümünde ``device`` parametresi yoksa gönderilmez."""
    kayit = []

    class EskiF5:
        def __init__(self, model="F5TTS_Base", ckpt_file="", vocab_file=""):
            kayit.append((model, ckpt_file, vocab_file))

    sys.modules["f5_tts.api"].F5TTS = EskiF5
    m = F5TurkishBackend(device="mps")
    assert kayit == [("F5TTS_v1_Base", str(sahte_f5["ckpt"]), str(sahte_f5["vocab"]))] and m.sr == 24000


def test_f5_config_bos_backend_unavailable(sahte_f5, monkeypatch):
    monkeypatch.setattr(config, "F5_TR_CKPT", None)
    with pytest.raises(BackendUnavailable) as exc:
        backends.create("f5-tr")
    assert "F5_TR_CKPT" in str(exc.value) and "marduk-ra/F5-TTS-Turkish" in str(exc.value)
    monkeypatch.setattr(config, "F5_TR_CKPT", str(sahte_f5["ckpt"]))
    monkeypatch.setattr(config, "F5_TR_VOCAB", None)
    with pytest.raises(BackendUnavailable) as exc2:
        F5TurkishBackend()
    assert "F5_TR_VOCAB" in str(exc2.value) and "vocab.txt" in str(exc2.value)
    assert sahte_f5["init"] == []          # model hiç kurulmadı


def test_f5_dosya_yoksa_turkce_hata(sahte_f5, monkeypatch):
    monkeypatch.setattr(config, "F5_TR_CKPT", str(sahte_f5["tmp"] / "yok.safetensors"))
    with pytest.raises(FileNotFoundError) as exc:
        F5TurkishBackend()
    assert "bulunamadı" in str(exc.value) and "F5_TR_CKPT" in str(exc.value)
    monkeypatch.setattr(config, "F5_TR_CKPT", str(sahte_f5["ckpt"]))
    monkeypatch.setattr(config, "F5_TR_VOCAB", str(sahte_f5["tmp"] / "yok.txt"))
    with pytest.raises(FileNotFoundError) as exc2:
        F5TurkishBackend()
    assert "bulunamadı" in str(exc2.value) and "F5_TR_VOCAB" in str(exc2.value)


# ---------- üretim ----------

def test_f5_referanssiz_turkce_hata(sahte_f5):
    m = F5TurkishBackend()
    with pytest.raises(ValueError) as exc:
        m.generate("Merhaba dünya.")
    assert "F5-TTS referans kaydı olmadan üretemez" in str(exc.value)
    assert sahte_f5["infer"] == []


def test_f5_referansla_infer_argumanlari(sahte_f5):
    m = F5TurkishBackend()
    out = m.generate("Bugün hava çok güzel.", language_id="tr", audio_prompt_path=Path(sahte_f5["ref"]),
                     ref_text="Bu bir referans cümlesi.")
    assert isinstance(out, np.ndarray) and out.dtype == np.float32 and out.ndim == 1 and len(out) > 0
    c = sahte_f5["infer"][-1]
    assert c["gen_text"] == "Bugün hava çok güzel." and c["ref_file"] == str(sahte_f5["ref"])
    assert c["ref_text"] == "Bu bir referans cümlesi." and c["seed"] is None and c["remove_silence"] is False
    assert c["show_info"] is not print          # F5 çıktısı stdout yerine log'a gider
    assert sahte_f5["transcribe"] == []         # transkript verildi → ASR çalışmadı


def test_f5_ref_text_bossa_turkce_asr_ve_onbellek(sahte_f5):
    m = F5TurkishBackend()
    m.generate("Birinci cümle.", audio_prompt_path=str(sahte_f5["ref"]))
    m.generate("İkinci cümle.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="   ")
    assert sahte_f5["transcribe"] == [{"ref_audio": str(sahte_f5["ref"]), "language": "tr"}]   # bir kez
    assert [c["ref_text"] for c in sahte_f5["infer"]] == ["referans metni", "referans metni"]


def test_f5_asr_basarisizsa_bos_metin_f5e_kalir(sahte_f5):
    m = F5TurkishBackend()

    def bozuk(ref_audio, language=None):
        raise RuntimeError("whisper yok")

    m._model.transcribe = bozuk
    m.generate("Deneme.", audio_prompt_path=str(sahte_f5["ref"]))
    assert sahte_f5["infer"][-1]["ref_text"] == ""


def test_f5_seed_iletilir_ve_torch_tohumu(sahte_f5, monkeypatch):
    m = F5TurkishBackend()
    m.seed(42)
    assert sahte_f5["seed"] == [42]
    m.generate("Merhaba.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="Selam.")
    assert sahte_f5["infer"][-1]["seed"] == 42
    monkeypatch.setitem(sys.modules, "torch", None)     # import torch → ImportError; sessizce geçer
    m.seed(7)
    assert m._seed == 7 and sahte_f5["seed"] == [42]


def test_f5_sr_infer_donusunden_guncellenir(sahte_f5):
    m = F5TurkishBackend()
    sahte_f5["sr"] = 22050
    m.generate("Merhaba.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="Selam.")
    assert m.sr == 22050 and m.info()["sr"] == 22050


def test_f5_turkce_olmayan_dil_uyarir_ama_uretir(sahte_f5, caplog):
    m = F5TurkishBackend()
    with caplog.at_level(logging.WARNING, logger="sesklon.backends.f5"):
        out = m.generate("Hello world.", language_id="EN", audio_prompt_path=str(sahte_f5["ref"]), ref_text="x")
    assert len(out) > 0 and any("yalnızca Türkçe" in r.getMessage() for r in caplog.records)


def test_f5_wav_none_turkce_hata(sahte_f5):
    m = F5TurkishBackend()
    m._model.infer = lambda ref_file, ref_text, gen_text, seed=None: (None, 24000, None)
    with pytest.raises(RuntimeError) as exc:
        m.generate("Merhaba.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="x")
    assert "ses üretmedi" in str(exc.value)


def test_f5_generate_imzasi_sozlesmeye_uygun():
    params = inspect.signature(F5TurkishBackend.generate).parameters
    for yok in ("exaggeration", "cfg_weight", "temperature", "emotion"):
        assert yok not in params
    for var in ("text", "language_id", "audio_prompt_path", "ref_text", "speed"):
        assert var in params
    assert not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    assert F5TurkishBackend.commercial is False and F5TurkishBackend.needs_torch is True
    assert F5TurkishBackend.required_modules == ("torch", "f5_tts")


# ---------- motor uçtan uca ----------

def test_motor_f5_ile_uctan_uca(sahte_f5):
    eng = Engine(backend="f5-tr")
    assert eng.backend_name == "f5-tr" and eng.device == "cpu" and not eng.loaded
    refs = VoiceRefs("v", base=Path(sahte_f5["ref"]), by_emotion={})
    wav, sr, rep = eng.synthesize("Merhaba dünya! Bugün hava çok güzel.", "tr", refs, exaggeration=0.9,
                                  cfg_weight=0.3, seed=5, master=False, breaths=False, room_tone=False, qc=False)
    assert sr == 24000 and wav.ndim == 1 and wav.dtype == np.float32 and len(wav) > sr * 0.5
    assert eng.loaded and eng.model_name == "f5-tts-turkish:f5_tts_turkish_1000000.safetensors"
    assert rep["chunks"] and rep["chunks"][0]["ref"] == "nötr"
    calls = sahte_f5["infer"]
    assert calls and all(c["ref_file"] == str(sahte_f5["ref"]) for c in calls)
    assert all(c["seed"] is not None for c in calls) and 5 in sahte_f5["seed"]   # motor tohumu ulaştı
    assert "".join(c["gen_text"] for c in calls).replace(" ", "")
    assert sahte_f5["transcribe"] and all(c["ref_text"] == "referans metni" for c in calls)


def test_motor_f5_referanssiz_turkce_hata(sahte_f5):
    eng = Engine(backend="f5")
    with pytest.raises(ValueError) as exc:
        eng.synthesize("Merhaba dünya.", "tr", None, master=False, breaths=False, room_tone=False, qc=False)
    assert "referans kaydı olmadan" in str(exc.value)
