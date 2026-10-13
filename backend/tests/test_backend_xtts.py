"""Coqui XTTS-v2 adaptörü — sahte ``torch`` / ``TTS`` / ``TTS.api`` modülleriyle.

Bu kutuda torch ve coqui-tts KURULU DEĞİL: sahte modüller ``sys.modules``'a konur ve ``__spec__`` verilir ki
``importlib.util.find_spec`` (``BaseBackend.available``) onları kurulu saysın.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import inspect
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app import backends, config
from app.backends import BackendUnavailable
from app.backends.fake import speechlike
from app.backends.xtts import XTTS_LANGUAGES, XttsBackend, xtts_language
from app.engine import Engine, VoiceRefs

MODEL_ADI = "tts_models/multilingual/multi-dataset/xtts_v2"


def _modul(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _referans_wav(yol: Path) -> Path:
    sf.write(str(yol), speechlike(60, 24000, seed=11), 24000)
    return yol


@pytest.fixture()
def sahte(monkeypatch, tmp_path):
    """Sahte torch + TTS.api kurar; ``kayit`` sözlüğü çağrıları toplar."""
    kayit: dict = {"seed": [], "init": [], "to": [], "tts": [], "to_hata": set()}

    torch = _modul("torch", manual_seed=lambda s: kayit["seed"].append(int(s)), load=lambda *a, **k: {},
                   device=lambda d: f"device({d})",
                   cuda=types.SimpleNamespace(is_available=lambda: False, manual_seed_all=lambda s: None),
                   backends=types.SimpleNamespace(mps=None))

    class TTS:
        def __init__(self, model_name="", *, model_path=None, config_path=None, progress_bar=True, gpu=False):
            kayit["init"].append({"model_name": model_name, "model_path": model_path, "config_path": config_path})
            self.model_name = model_name
            self.synthesizer = types.SimpleNamespace(output_sample_rate=24000)
            self.device = "cpu"

        def to(self, device):
            kayit["to"].append(device)
            if device in kayit["to_hata"]:
                raise RuntimeError(f"'{device}' üzerinde desteklenmeyen işlem")
            self.device = device
            return self

        def tts(self, text, speaker_wav=None, language=None, split_sentences=True, speed=1.0):
            kayit["tts"].append({"text": text, "speaker_wav": speaker_wav, "language": language,
                                 "split_sentences": split_sentences, "speed": speed})
            return [float(x) for x in speechlike(len(text), 24000, seed=len(kayit["tts"]))]

    tts_paket = _modul("TTS")
    tts_api = _modul("TTS.api", TTS=TTS)
    tts_paket.api = tts_api
    for ad, mod in (("torch", torch), ("TTS", tts_paket), ("TTS.api", tts_api)):
        monkeypatch.setitem(sys.modules, ad, mod)
    monkeypatch.setattr(config, "XTTS_MODEL", MODEL_ADI)
    monkeypatch.setattr(config, "DEVICE", "cpu")
    monkeypatch.setenv("COQUI_TOS_AGREED", "1")
    kayit["sinif"] = TTS
    kayit["ref"] = _referans_wav(tmp_path / "ref.wav")
    kayit["tmp"] = tmp_path
    return kayit


# ---------- kurulum denetimi ----------

def test_sahte_modullerle_kurulu_gorunur(sahte):
    assert XttsBackend.available() == (True, "kurulu")
    satir = next(r for r in backends.describe() if r["name"] == "xtts")
    assert satir["available"] is True and satir["commercial"] is False and satir["emotion_controls"] is False
    assert satir["label"] == "Coqui XTTS-v2 (A/B için)" and satir["license"].startswith("CPML")


def test_tts_kurulu_degilken_describe_nedeni_tts_icerir(sahte, monkeypatch):
    monkeypatch.setitem(sys.modules, "TTS", None)          # find_spec → ValueError → kurulu değil
    ok, neden = XttsBackend.available()
    assert ok is False and "'TTS' paketi kurulu değil" in neden and "coqui-tts" in neden
    satir = next(r for r in backends.describe() if r["name"] == "xtts")
    assert satir["available"] is False and "TTS" in satir["reason"] and "pip install" in satir["reason"]
    with pytest.raises(BackendUnavailable) as exc:
        backends.create("xtts")
    assert "'xtts' arka ucu kullanılamıyor" in str(exc.value)


@pytest.mark.skipif(importlib.util.find_spec("TTS") is not None, reason="coqui-tts kurulu")
def test_bu_kutuda_xtts_kurulu_degil():
    satir = next(r for r in backends.describe() if r["name"] == "xtts")
    assert satir["available"] is False and "TTS" in satir["reason"]


def test_sinif_oznitelikleri():
    assert XttsBackend.name == "xtts" and XttsBackend.commercial is False
    assert XttsBackend.supports_emotion_controls is False and XttsBackend.needs_torch is True
    assert XttsBackend.required_modules == ("torch", "TTS")
    assert "coqui-tts" in XttsBackend.install_hint and "pip install TTS" in XttsBackend.install_hint
    assert XttsBackend.license == "CPML — yalnızca ticari olmayan kullanım"


# ---------- yükleme ----------

def test_create_xtts_yukler(sahte):
    m = backends.create("xtts-v2", device="cpu")
    assert isinstance(m, XttsBackend)
    assert sahte["init"] == [{"model_name": MODEL_ADI, "model_path": None, "config_path": None}]
    assert sahte["to"] == ["cpu"] and m.device == "cpu"
    assert m.sr == 24000 and m.model_id == MODEL_ADI
    info = m.info()
    assert info["name"] == "xtts" and info["xtts_model"] == MODEL_ADI and info["commercial"] is False
    assert info["sr"] == 24000 and info["emotion_controls"] is False


def test_ornekleme_hizi_synthesizerdan_okunur(sahte):
    sinif = sahte["sinif"]
    eski_init = sinif.__init__

    def yeni_init(self, *a, **k):
        eski_init(self, *a, **k)
        self.synthesizer = types.SimpleNamespace(output_sample_rate=22050)

    sinif.__init__ = yeni_init
    assert XttsBackend(device="cpu").sr == 22050
    sinif.__init__ = lambda self, *a, **k: None          # synthesizer yok → 24000 varsayılanı
    assert XttsBackend(device="cpu").sr == 24000


def test_mps_hatasinda_cpuya_duser(sahte):
    sahte["to_hata"].add("mps")
    m = XttsBackend(device="mps")
    assert sahte["to"] == ["mps", "cpu"] and m.device == "cpu" and m.model.device == "cpu"


def test_yerel_klasorden_yukleme(sahte, monkeypatch):
    klasor = sahte["tmp"] / "xtts_v2"
    klasor.mkdir()
    monkeypatch.setattr(config, "XTTS_MODEL", str(klasor))
    m = XttsBackend(device="cpu")
    assert sahte["init"] == [{"model_name": "", "model_path": str(klasor),
                              "config_path": str(klasor / "config.json")}]
    assert m.model_id == str(klasor)


def test_lisans_onayi_etkilesimsiz_ortamda_turkce_hata(sahte):
    def sorar(self, *a, **k):
        raise EOFError("stdin yok")

    sahte["sinif"].__init__ = sorar
    with pytest.raises(BackendUnavailable) as exc:
        XttsBackend(device="cpu")
    assert "COQUI_TOS_AGREED=1" in str(exc.value) and "lisans" in str(exc.value)


# ---------- üretim ----------

def test_generate_referanssiz_turkce_hata(sahte):
    m = XttsBackend(device="cpu")
    with pytest.raises(ValueError) as exc:
        m.generate("Merhaba dünya.")
    assert "referans" in str(exc.value) and "zorunlu" in str(exc.value)
    with pytest.raises(FileNotFoundError) as exc2:
        m.generate("Merhaba dünya.", audio_prompt_path=str(sahte["tmp"] / "yok.wav"))
    assert "bulunamadı" in str(exc2.value)
    assert sahte["tts"] == []


def test_generate_referansla_dogru_argumanlar(sahte):
    m = XttsBackend(device="cpu")
    out = m.generate("Bugün hava çok güzel.", language_id="TR", audio_prompt_path=sahte["ref"], speed=1.1)
    assert isinstance(out, np.ndarray) and out.dtype == np.float32 and out.ndim == 1 and len(out) > 0
    assert sahte["tts"] == [{"text": "Bugün hava çok güzel.", "speaker_wav": str(sahte["ref"]), "language": "tr",
                             "split_sentences": False, "speed": 1.1}]


def test_uzun_metinde_cumle_bolme_acilir(sahte):
    m = XttsBackend(device="cpu")
    m.generate("Uzun bir cümle. " * 20, audio_prompt_path=str(sahte["ref"]))     # 320 kar. > 226 (tr sınırı)
    assert sahte["tts"][-1]["split_sentences"] is True


def test_desteklenmeyen_dil_turkce_hata(sahte):
    m = XttsBackend(device="cpu")
    with pytest.raises(ValueError) as exc:
        m.generate("Habari yako?", language_id="sw", audio_prompt_path=str(sahte["ref"]))
    assert "desteklemiyor" in str(exc.value) and "sw" in str(exc.value) and "tr" in str(exc.value)
    assert sahte["tts"] == []
    assert "tr" in XTTS_LANGUAGES and xtts_language("zh") == "zh-cn" and xtts_language("TR") == "tr"


def test_dar_imzada_speed_gonderilmez(sahte):
    m = XttsBackend(device="cpu")
    cagrilar = []

    def eski_tts(text, speaker_wav=None, language=None, split_sentences=True):
        cagrilar.append({"text": text, "speaker_wav": speaker_wav, "language": language})
        return [0.0] * 2400

    m.model.tts = eski_tts
    m.generate("Selam.", audio_prompt_path=str(sahte["ref"]), speed=1.2)
    assert cagrilar == [{"text": "Selam.", "speaker_wav": str(sahte["ref"]), "language": "tr"}]


def test_generate_imzasi_sozlesmeye_uygun():
    params = inspect.signature(XttsBackend.generate).parameters
    for yok in ("exaggeration", "cfg_weight", "temperature", "emotion"):
        assert yok not in params
    assert {"text", "language_id", "audio_prompt_path", "speed"} <= set(params)
    assert not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def test_seed_torch_tohumu(sahte, monkeypatch):
    m = XttsBackend(device="cpu")
    m.seed(42)
    assert sahte["seed"] == [42]
    monkeypatch.setitem(sys.modules, "torch", None)
    m.seed(7)                                            # torch yok → sessizce geçer
    assert sahte["seed"] == [42]


# ---------- motor uçtan uca ----------

def test_motor_xtts_ile_uctan_uca(sahte):
    eng = Engine(backend="xtts")
    assert eng.backend_name == "xtts" and eng.device == "cpu"
    refs = VoiceRefs("v", base=sahte["ref"], by_emotion={})
    wav, sr, rep = eng.synthesize("Merhaba! Bugün hava çok güzel.", "tr", refs, seed=3, master=False,
                                  breaths=False, room_tone=False, qc=False)
    assert sr == 24000 and wav.ndim == 1 and wav.dtype == np.float32 and len(wav) > sr * 0.3
    assert isinstance(eng.tts(), XttsBackend) and eng.model_name == MODEL_ADI
    assert sahte["tts"] and all(c["speaker_wav"] == str(sahte["ref"]) and c["language"] == "tr"
                                for c in sahte["tts"])
    assert all(c["speed"] == 1.0 for c in sahte["tts"])          # motor hızı kendisi uygular
    assert rep["chunks"][0]["ref"] == "nötr"
    assert 3 in sahte["seed"]                                     # motor tohumu sahte torch'a ulaştı


def test_motor_referanssiz_xtts_turkce_hata(sahte):
    eng = Engine(backend="xtts")
    with pytest.raises(ValueError) as exc:
        eng.synthesize("Merhaba.", "tr", None, master=False, breaths=False, room_tone=False, qc=False)
    assert "referans" in str(exc.value)
