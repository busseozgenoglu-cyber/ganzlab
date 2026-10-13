"""Arka uç kayıt defteri, sahte arka uç, motorun sahte arka uçla uçtan uca üretimi ve Chatterbox adaptörü.

Bu kutuda torch / chatterbox KURULU DEĞİL: Chatterbox adaptörü ``sys.modules``'a konan sahte ``torch``,
``safetensors`` ve ``chatterbox.mtl_tts`` modülleriyle denenir. Sahte modüllere ``__spec__`` verilir ki
``importlib.util.find_spec`` (``BaseBackend.available``) onları kurulu saysın.
"""
from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import inspect
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from app import backends, config
from app.analysis import analyze_array
from app.backends import BackendUnavailable
from app.backends.chatterbox import ChatterboxBackend, load_finetuned_t3, strip_key_prefixes
from app.backends.fake import FakeBackend, speechlike
from app.engine import Engine, VoiceRefs

METIN = "Bugün hava çok güzel, dışarı çıkalım mı?"
TORCH_KURULU = importlib.util.find_spec("torch") is not None


# ---------- kayıt defteri ----------

def test_kayit_defteri_bes_ad():
    assert backends.names() == ["chatterbox", "chatterbox-mlx", "f5-tr", "xtts", "fake"]
    assert backends.DEFAULT_BACKEND == "chatterbox"


@pytest.mark.parametrize("takma, gercek", [
    ("mlx", "chatterbox-mlx"), ("f5", "f5-tr"), ("sahte", "fake"), ("", "chatterbox"), (None, "chatterbox"),
    ("torch", "chatterbox"), ("XTTS-v2", "xtts"), ("f5_tr", "f5-tr"), (" fake ", "fake"),
])
def test_takma_adlar(takma, gercek):
    assert backends.normalize_name(takma) == gercek


def test_bilinmeyen_ad_turkce_hata():
    with pytest.raises(KeyError) as exc:
        backends.normalize_name("bilinmeyen-model")
    assert "Bilinmeyen arka uç" in str(exc.value) and "bilinmeyen-model" in str(exc.value)
    with pytest.raises(KeyError):
        backends.create("yok-boyle-bir-sey")


def test_describe_her_kayit_icin_anahtarlar():
    rows = backends.describe()
    assert [r["name"] for r in rows] == backends.names()
    beklenen = {"name", "label", "license", "commercial", "emotion_controls", "available", "reason"}
    for r in rows:
        assert set(r) == beklenen, r
        assert isinstance(r["available"], bool) and isinstance(r["reason"], str)
    fake = next(r for r in rows if r["name"] == "fake")
    assert fake["available"] is True and fake["reason"] == "kurulu"
    cb = next(r for r in rows if r["name"] == "chatterbox")
    assert cb["label"] == "Chatterbox Multilingual (PyTorch)" and cb["license"].startswith("MIT")
    assert cb["commercial"] is True and cb["emotion_controls"] is True


@pytest.mark.skipif(TORCH_KURULU, reason="torch kurulu; bu test torch'suz kutu içindir")
def test_describe_chatterbox_bu_kutuda_kurulu_degil():
    cb = next(r for r in backends.describe() if r["name"] == "chatterbox")
    assert cb["available"] is False
    assert "torch" in cb["reason"] and "kurulu değil" in cb["reason"]
    assert ChatterboxBackend.install_hint in cb["reason"] and "pip install" in cb["reason"]


def test_create_fake_ve_create_chatterbox():
    m = backends.create("fake")
    assert isinstance(m, FakeBackend) and m.sr == 24000 and m.device == "cpu"
    assert backends.create("sahte", device="cpu").name == "fake"
    if not TORCH_KURULU:
        with pytest.raises(BackendUnavailable) as exc:
            backends.create("chatterbox")
        msg = str(exc.value)
        assert "'chatterbox' arka ucu kullanılamıyor" in msg and "torch" in msg and "pip install" in msg


def test_create_ortam_degiskeninden(monkeypatch):
    monkeypatch.setenv("TTS_BACKEND", "sahte")
    assert isinstance(backends.create(None), FakeBackend)


# ---------- sahte arka uç ----------

def _sahte_uret(seed: int, **kw) -> np.ndarray:
    """Taze örnek + aynı tohum → aynı çağrı sırası (sahte arka uç tohumu çağrı sayısıyla karıştırır)."""
    m = FakeBackend()
    m.seed(seed)
    return m.generate(METIN, **kw)


def test_sahte_exaggeration_tonlama_araligini_acar():
    dusuk = analyze_array(_sahte_uret(1, exaggeration=0.1), 24000)["f0"]["range_semitones"]
    yuksek = analyze_array(_sahte_uret(1, exaggeration=1.0), 24000)["f0"]["range_semitones"]
    assert yuksek - dusuk >= 4.0, (dusuk, yuksek)
    assert dusuk < 10.0 and yuksek >= 12.0


def test_sahte_referans_perdeyi_belirler():
    a1 = analyze_array(_sahte_uret(1, audio_prompt_path="a.wav"), 24000)["f0"]["median_hz"]
    a2 = analyze_array(_sahte_uret(1, audio_prompt_path="a.wav"), 24000)["f0"]["median_hz"]
    b = analyze_array(_sahte_uret(1, audio_prompt_path="b.wav"), 24000)["f0"]["median_hz"]
    assert a1 == a2                       # aynı referans + aynı tohum → aynı ses
    assert abs(a1 - b) > 20.0, (a1, b)    # farklı referans → farklı temel perde
    assert np.array_equal(_sahte_uret(2, audio_prompt_path="a.wav"), _sahte_uret(2, audio_prompt_path="a.wav"))


def test_sahte_tohum_ayni_cikti():
    assert np.array_equal(_sahte_uret(5), _sahte_uret(5))
    assert not np.array_equal(_sahte_uret(5), _sahte_uret(6))
    out = _sahte_uret(5)
    assert out.dtype == np.float32 and out.ndim == 1 and len(out) >= 24000 * 0.4


def test_sahte_cagri_kaydi_ve_bilgi():
    m = FakeBackend()
    m.generate("Merhaba", language_id="tr", exaggeration=0.7, cfg_weight=0.3, temperature=0.9, audio_prompt_path="r.wav")
    assert m.calls == [{"text": "Merhaba", "language_id": "tr", "exaggeration": 0.7, "cfg_weight": 0.3,
                        "temperature": 0.9, "ref": "r.wav"}]
    info = m.info()
    assert info["name"] == "fake" and info["sr"] == 24000 and info["model_id"] == "sahte-sinyal"


# ---------- motor + sahte arka uç uçtan uca ----------

def test_motor_sahte_arka_ucla_uctan_uca(monkeypatch):
    monkeypatch.setattr(config, "DEVICE", None)
    eng = Engine(backend="fake")
    assert eng.backend_name == "fake" and eng.device == "cpu" and not eng.loaded
    wav, sr, rep = eng.synthesize("[mutlu] Merhaba dünya! Bugün hava çok güzel.", "tr", None, seed=3, master=False)
    assert sr == 24000 and wav.ndim == 1 and wav.dtype == np.float32 and len(wav) > sr * 0.5
    assert rep["chunks"] and rep["chunks"][0]["ref"] == "model" and rep["chunks"][0]["emotion"] == "mutlu"
    assert eng.loaded and eng.model_name == "sahte-sinyal" and isinstance(eng.tts(), FakeBackend)
    model = eng.tts()
    assert model.calls and all("emotion" not in c for c in model.calls)        # imzada yok → süzüldü
    assert all(c["language_id"] == "tr" for c in model.calls)
    # referansla da çalışır (ad hoc yol)
    wav2, sr2, rep2 = eng.synthesize("Kısa bir deneme cümlesi.", "tr", VoiceRefs("v", Path("ref.wav"), {}),
                                     seed=1, master=False, breaths=False, room_tone=False, qc=False)
    assert sr2 == 24000 and len(wav2) > 0 and rep2["chunks"][0]["ref"] == "nötr"     # duygusuz parça → temel kayıt
    assert model.calls[-1]["ref"] == "ref.wav"


def test_emotion_parametresi_yalnizca_tanimlayan_arka_uca_gider():
    from app.engine import _filter_kwargs

    assert "emotion" not in inspect.signature(FakeBackend.generate).parameters
    assert "emotion" in inspect.signature(ChatterboxBackend.generate).parameters
    kw = {"language_id": "tr", "exaggeration": 0.5, "emotion": "mutlu"}
    assert _filter_kwargs(FakeBackend().generate, kw) == {"language_id": "tr", "exaggeration": 0.5}
    # sözleşme: generate açık parametrelerle, **kwargs yok
    for cls in (FakeBackend, ChatterboxBackend):
        params = inspect.signature(cls.generate).parameters.values()
        assert not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params), cls


# ---------- Chatterbox adaptörü: sahte torch / safetensors / chatterbox ----------

def _modul(name: str, **attrs) -> types.ModuleType:
    """``sys.modules``'a konacak sahte modül; ``__spec__`` olmadan find_spec ValueError verir (→ kurulu değil)."""
    m = types.ModuleType(name)
    m.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


class _SahteT3:
    """Chatterbox'ın T3 alt modeli: load_state_dict (missing, unexpected) döndürür, eval/to destekler."""

    anahtarlar = frozenset({"tfmr.h.0.w", "tfmr.h.1.w", "speech_emb.weight", "text_emb.weight"})

    def __init__(self) -> None:
        self.loaded: list[tuple[dict, bool]] = []
        self.eval_called = False
        self.to_device = None

    def load_state_dict(self, sd, strict=True):
        self.loaded.append((dict(sd), strict))
        return sorted(self.anahtarlar - set(sd)), sorted(set(sd) - self.anahtarlar)

    def eval(self):
        self.eval_called = True
        return self

    def to(self, device):
        self.to_device = device
        return self


@pytest.fixture()
def sahte(monkeypatch, tmp_path):
    """Sahte torch / safetensors / chatterbox modüllerini kurar; çağrı kayıtlarını ``kayit`` sözlüğünde toplar."""
    kayit: dict = {"seed": [], "cuda_seed": [], "torch_load": [], "load_file": [], "from_pretrained": [],
                   "from_local": [], "sd": {}, "torch_sd": {}}

    class _Cuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def manual_seed_all(s):
            kayit["cuda_seed"].append(int(s))

    def _torch_load(path, map_location=None, **kw):
        kayit["torch_load"].append({"path": str(path), "map_location": map_location})
        return kayit["torch_sd"]

    torch = _modul("torch", manual_seed=lambda s: kayit["seed"].append(int(s)), load=_torch_load,
                   device=lambda d: f"device({d})", cuda=_Cuda, backends=types.SimpleNamespace(mps=None))

    def _load_file(path, device="cpu"):
        kayit["load_file"].append(str(path))
        return kayit["sd"]

    safetensors = _modul("safetensors")
    safetensors_torch = _modul("safetensors.torch", load_file=_load_file)
    safetensors.torch = safetensors_torch

    class ChatterboxMultilingualTTS:
        sr = 24000

        def __init__(self, device, t3_model=None):
            self.device = device
            self.t3_model = t3_model
            self.conds = "varsayılan"
            self.t3 = _SahteT3()
            self.calls: list[dict] = []

        @classmethod
        def from_pretrained(cls, device, t3_model=None):
            kayit["from_pretrained"].append({"device": device, "t3_model": t3_model})
            return cls(device, t3_model)

        @classmethod
        def from_local(cls, ckpt_dir, device):
            kayit["from_local"].append({"ckpt_dir": ckpt_dir, "device": device})
            return cls(device)

        def generate(self, text, language_id, audio_prompt_path=None, exaggeration=0.5, cfg_weight=0.5,
                     temperature=0.8, repetition_penalty=1.2):
            self.calls.append({"text": text, "language_id": language_id, "audio_prompt_path": audio_prompt_path,
                               "exaggeration": exaggeration, "cfg_weight": cfg_weight, "temperature": temperature})
            return speechlike(len(text), self.sr, seed=len(self.calls))[None, :]      # (1, n) — tensör gibi

    chatterbox = _modul("chatterbox")
    mtl_tts = _modul("chatterbox.mtl_tts", ChatterboxMultilingualTTS=ChatterboxMultilingualTTS)
    chatterbox.mtl_tts = mtl_tts
    for name, mod in (("torch", torch), ("safetensors", safetensors), ("safetensors.torch", safetensors_torch),
                      ("chatterbox", chatterbox), ("chatterbox.mtl_tts", mtl_tts)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(config, "T3_MODEL", "v3")
    monkeypatch.setattr(config, "T3_FINETUNED", None)
    monkeypatch.setattr(config, "CHATTERBOX_LOCAL_DIR", None)
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", False)
    monkeypatch.setattr(config, "DEVICE", "cpu")
    kayit["sinif"] = ChatterboxMultilingualTTS
    kayit["tmp"] = tmp_path
    return kayit


def test_find_spec_sahte_modulleri_gorur(sahte, monkeypatch):
    assert importlib.util.find_spec("torch") is not None and importlib.util.find_spec("chatterbox") is not None
    assert ChatterboxBackend.available() == (True, "kurulu")
    cb = next(r for r in backends.describe() if r["name"] == "chatterbox")
    assert cb["available"] is True
    # __spec__'siz sahte modül: find_spec ValueError verir, available bunu "kurulu değil" sayar
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    ok, neden = ChatterboxBackend.available()
    assert ok is False and "torch" in neden and "kurulu değil" in neden


def test_chatterbox_from_pretrained_ile_yuklenir(sahte):
    m = backends.create("chatterbox", device="cpu")
    assert isinstance(m, ChatterboxBackend)
    assert sahte["from_pretrained"] == [{"device": "cpu", "t3_model": "v3"}] and sahte["from_local"] == []
    assert m.sr == 24000 and m.model_id == "chatterbox-multilingual-v3" and m.device == "cpu"
    info = m.info()
    assert info["name"] == "chatterbox" and info["model_id"] == "chatterbox-multilingual-v3"
    assert info["finetuned"] is None and info["t3_model"] == "v3" and info["emotion_tags"] is False
    assert info["license"] == "MIT — ticari kullanım serbest" and info["commercial"] is True
    assert "finetune_keys" not in info


def test_chatterbox_t3_model_imzada_yoksa_gonderilmez(sahte):
    sinif = sahte["sinif"]

    @classmethod
    def eski_from_pretrained(cls, device):
        sahte["from_pretrained"].append({"device": device})
        return cls(device)

    sinif.from_pretrained = eski_from_pretrained
    m = ChatterboxBackend(device="cpu")
    assert sahte["from_pretrained"] == [{"device": "cpu"}] and m._model.t3_model is None


def test_chatterbox_generate_yalnizca_imzadaki_parametreler(sahte):
    m = ChatterboxBackend(device="cpu")
    out = m.generate("Merhaba dünya.", language_id="tr", exaggeration=0.7, cfg_weight=0.3, temperature=0.9,
                     audio_prompt_path=Path("ref.wav"), emotion="mutlu")
    assert isinstance(out, np.ndarray) and out.ndim == 1 and out.dtype == np.float32 and len(out) > 0
    assert m._model.calls == [{"text": "Merhaba dünya.", "language_id": "tr", "audio_prompt_path": "ref.wav",
                               "exaggeration": 0.7, "cfg_weight": 0.3, "temperature": 0.9}]   # etiket kapalı
    # daha dar imza: tanımsız parametreler (exaggeration vb.) hiç gönderilmez
    dar_calls = []

    def dar_generate(text, language_id, audio_prompt_path=None):
        dar_calls.append({"text": text, "language_id": language_id, "audio_prompt_path": audio_prompt_path})
        return np.zeros(2400, dtype=np.float32)

    m._model.generate = dar_generate
    m.generate("Selam.", exaggeration=0.9, cfg_weight=0.1, temperature=1.2)
    assert dar_calls == [{"text": "Selam.", "language_id": "tr", "audio_prompt_path": None}]


def test_chatterbox_duygu_etiketi(sahte, monkeypatch):
    m = ChatterboxBackend(device="cpu")
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", True)
    m.generate("Merhaba dünya.", emotion="mutlu")
    m.generate("Merhaba dünya.", emotion="normal")
    m.generate("Merhaba dünya.", emotion=None)
    m.generate("Merhaba dünya.", emotion="Üzgün")             # Türkçe küçük harf: Ü → ü
    m.generate("[kızgın] Yeter artık!", emotion="kızgın")     # zaten etiketli: ikinci kez eklenmez
    texts = [c["text"] for c in m._model.calls]
    assert texts == ["[mutlu] Merhaba dünya.", "Merhaba dünya.", "Merhaba dünya.", "[üzgün] Merhaba dünya.",
                     "[kızgın] Yeter artık!"]
    assert m.info()["emotion_tags"] is True
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", False)
    m.generate("Merhaba dünya.", emotion="mutlu")
    assert m._model.calls[-1]["text"] == "Merhaba dünya."     # kapalıyken eklenmez
    assert ChatterboxBackend.tag_text("Selam", "  ") == "Selam" and ChatterboxBackend.tag_text("Selam", "x") == "Selam"


def test_chatterbox_conds_ic_modele_delege(sahte):
    m = ChatterboxBackend(device="cpu")
    assert m.conds == "varsayılan" and hasattr(m, "conds")
    varsayilan = copy.deepcopy(getattr(m, "conds", None))     # motorun yaptığı gibi
    m.conds = "klon-kosullari"
    assert m._model.conds == "klon-kosullari" and m.conds == "klon-kosullari"
    m.conds = varsayilan
    assert m._model.conds == "varsayılan"


def test_chatterbox_seed(sahte, monkeypatch):
    m = ChatterboxBackend(device="cpu")
    m.seed(42)
    assert sahte["seed"] == [42] and sahte["cuda_seed"] == []    # cuda yok → manual_seed_all çağrılmaz
    monkeypatch.setitem(sys.modules, "torch", None)                # import torch → ImportError
    m.seed(7)                                                      # sessizce geçer
    assert sahte["seed"] == [42]


def test_chatterbox_ince_ayar_safetensors(sahte, monkeypatch):
    dosya = sahte["tmp"] / "t3_finetuned_merged.safetensors"
    dosya.write_bytes(b"sahte")
    sahte["sd"] = {"module.t3.tfmr.h.0.w": 1, "t3.tfmr.h.1.w": 2, "speech_emb.weight": 3, "module.text_emb.weight": 4,
                   "fazla.bias": 5}
    monkeypatch.setattr(config, "T3_FINETUNED", str(dosya))
    m = backends.create("chatterbox", device="cpu")
    assert sahte["load_file"] == [str(dosya)] and sahte["torch_load"] == []
    t3 = m._model.t3
    assert len(t3.loaded) == 1
    sd, strict = t3.loaded[0]
    assert strict is False
    assert sd == {"tfmr.h.0.w": 1, "tfmr.h.1.w": 2, "speech_emb.weight": 3, "text_emb.weight": 4, "fazla.bias": 5}
    assert t3.eval_called and t3.to_device == "cpu"
    assert m.model_id == "chatterbox-multilingual-v3+ince-ayar:t3_finetuned_merged.safetensors"
    assert "+ince-ayar" in m.model_id
    info = m.info()
    assert info["finetuned"] == str(dosya)
    assert info["finetune_keys"] == {"matched": 4, "missing": 0, "unexpected": 1}
    assert m.finetune_report["renamed"] == 3


def test_chatterbox_ince_ayar_pt_torch_load(sahte, monkeypatch):
    dosya = sahte["tmp"] / "t3_finetuned.pt"
    dosya.write_bytes(b"sahte")
    sahte["torch_sd"] = {"state_dict": {"t3.tfmr.h.0.w": 1, "tfmr.h.1.w": 2}}     # eğitim sarmalayıcısı
    monkeypatch.setattr(config, "T3_FINETUNED", str(dosya))
    m = ChatterboxBackend(device="cpu")
    assert sahte["torch_load"] == [{"path": str(dosya), "map_location": "cpu"}] and sahte["load_file"] == []
    sd, _ = m._model.t3.loaded[0]
    assert sd == {"tfmr.h.0.w": 1, "tfmr.h.1.w": 2}
    assert m.finetune_report["matched"] == 2 and m.finetune_report["missing"] == 2
    assert m.model_id.endswith("+ince-ayar:t3_finetuned.pt")


def test_chatterbox_ince_ayar_eslesmeyen_anahtarlar(sahte, monkeypatch):
    dosya = sahte["tmp"] / "yanlis_model.safetensors"
    dosya.write_bytes(b"sahte")
    sahte["sd"] = {"encoder.layer.0.w": 1, "encoder.layer.1.w": 2, "decoder.w": 3, "tfmr.h.0.w": 4}   # 1/4 eşleşti
    monkeypatch.setattr(config, "T3_FINETUNED", str(dosya))
    with pytest.raises(RuntimeError) as exc:
        ChatterboxBackend(device="cpu")
    assert "İnce ayar ağırlıkları T3 ile eşleşmiyor" in str(exc.value) and "yalnızca 1" in str(exc.value)
    # boş dosya
    sahte["sd"] = {}
    with pytest.raises(RuntimeError) as exc2:
        ChatterboxBackend(device="cpu")
    assert "boş" in str(exc2.value)


def test_chatterbox_ince_ayar_dosya_yok(sahte, monkeypatch):
    monkeypatch.setattr(config, "T3_FINETUNED", str(sahte["tmp"] / "yok.safetensors"))
    with pytest.raises(FileNotFoundError) as exc:
        ChatterboxBackend(device="cpu")
    assert "bulunamadı" in str(exc.value) and "T3_FINETUNED" in str(exc.value)


def test_chatterbox_ince_ayar_boyut_uyusmazligi_turkce(sahte):
    class _BozukT3(_SahteT3):
        def load_state_dict(self, sd, strict=True):
            raise RuntimeError("size mismatch for text_emb.weight")

    model = sahte["sinif"]("cpu")
    model.t3 = _BozukT3()
    dosya = sahte["tmp"] / "x.safetensors"
    dosya.write_bytes(b"sahte")
    sahte["sd"] = {"text_emb.weight": 1}
    with pytest.raises(RuntimeError) as exc:
        load_finetuned_t3(model, str(dosya), "cpu")
    assert "T3 ile uyumsuz" in str(exc.value) and "size mismatch" in str(exc.value)


def test_onek_soyma():
    sd, n = strip_key_prefixes({"module.t3.a": 1, "t3.module.b": 2, "base_model.model.c": 3, "d": 4, "module.": 5})
    assert sd == {"a": 1, "b": 2, "c": 3, "d": 4, "module.": 5} and n == 3


def test_chatterbox_yerel_klasor_from_local(sahte, monkeypatch):
    klasor = sahte["tmp"] / "chatterbox-ckpt"
    klasor.mkdir()
    monkeypatch.setattr(config, "CHATTERBOX_LOCAL_DIR", str(klasor))
    m = ChatterboxBackend(device="cpu")
    assert sahte["from_local"] == [{"ckpt_dir": str(klasor), "device": "cpu"}] and sahte["from_pretrained"] == []
    assert m.model_id == f"chatterbox-multilingual-v3@{klasor}" and m.info()["local_dir"] == str(klasor)
    monkeypatch.setattr(config, "CHATTERBOX_LOCAL_DIR", str(sahte["tmp"] / "yok"))
    with pytest.raises(FileNotFoundError) as exc:
        ChatterboxBackend(device="cpu")
    assert "CHATTERBOX_LOCAL_DIR" in str(exc.value) and "bulunamadı" in str(exc.value)


def test_chatterbox_yerel_klasor_t3_model_imzada_varsa_gecer(sahte, monkeypatch):
    klasor = sahte["tmp"] / "ckpt2"
    klasor.mkdir()
    monkeypatch.setattr(config, "CHATTERBOX_LOCAL_DIR", str(klasor))
    sinif = sahte["sinif"]

    @classmethod
    def yeni_from_local(cls, ckpt_dir, device, t3_model=None):
        sahte["from_local"].append({"ckpt_dir": ckpt_dir, "device": device, "t3_model": t3_model})
        return cls(device, t3_model)

    sinif.from_local = yeni_from_local
    ChatterboxBackend(device="cpu")
    assert sahte["from_local"] == [{"ckpt_dir": str(klasor), "device": "cpu", "t3_model": "v3"}]


def test_motor_chatterbox_adaptoru_ile_duygu_etiketi(sahte, monkeypatch):
    """Motor → Chatterbox adaptörü: emotion parametresi ulaşır, etiket metne eklenir, varsayılan conds geri yüklenir."""
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", True)
    eng = Engine(backend="chatterbox")
    assert eng.device == "cpu" and eng.model_name == "chatterbox-multilingual-v3"
    wav, sr, rep = eng.synthesize("[mutlu] Merhaba dünya! Bugün hava çok güzel.\n\n[normal] İkinci paragraf burada.",
                                  "tr", None, seed=3, master=False, breaths=False, room_tone=False, qc=False)
    assert sr == 24000 and len(wav) > sr * 0.5 and len(rep["chunks"]) == 2
    assert eng.model_name == "chatterbox-multilingual-v3" and isinstance(eng.tts(), ChatterboxBackend)
    calls = eng.tts()._model.calls
    assert calls and calls[0]["text"].startswith("[mutlu] ") and not calls[0]["text"].startswith("[mutlu] [")
    assert all(not c["text"].startswith("[normal]") for c in calls)
    assert any(c["text"].startswith("İkinci paragraf") for c in calls)
    assert all(c["audio_prompt_path"] is None and c["language_id"] == "tr" for c in calls)
    assert eng.tts()._model.conds == "varsayılan"          # klonsuz üretim: varsayılan koşullar geri yüklendi
    assert 3 in sahte["seed"]                              # motor tohumu sahte torch'a ulaştı
