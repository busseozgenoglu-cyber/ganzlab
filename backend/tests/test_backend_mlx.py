"""Chatterbox MLX arka ucu — sahte ``mlx`` / ``mlx.core`` / ``mlx_audio`` modülleriyle.

Bu kutuda mlx / mlx_audio KURULU DEĞİL. Sahte modüllere ``importlib.machinery.ModuleSpec`` ile ``__spec__`` verilir ki
``importlib.util.find_spec`` (``BaseBackend.available``) onları kurulu saysın. Sahte modelin ``generate`` imzası
mlx-audio 0.5.8'deki gerçek imzanın (``ref_audio``, ``lang_code``, ``verbose``, ``**kwargs``) kopyasıdır; ayrıca
farklı ad varyantları (``audio_prompt_path``/``language``, ``speaker_wav``/``language_id``) denenir.
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

from app import backends, config
from app.backends import BackendUnavailable
from app.backends.chatterbox_mlx import ChatterboxMlxBackend
from app.backends.fake import speechlike
from app.engine import Engine, VoiceRefs

MLX_KURULU = importlib.util.find_spec("mlx") is not None


def _modul(name: str, **attrs) -> types.ModuleType:
    """``sys.modules``'a konacak sahte modül; ``__spec__`` olmadan find_spec ValueError verir (→ kurulu değil)."""
    m = types.ModuleType(name)
    m.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


class SahteMxDizi:
    """mx.array benzeri: ``tolist()`` ve (isteğe bağlı) ``__array__`` destekler, ``shape`` taşır."""

    def __init__(self, veri, array_protokolu: bool = True) -> None:
        self._veri = np.asarray(veri, dtype=np.float32)
        self.shape = self._veri.shape
        self.ndim = self._veri.ndim
        self.tolist_cagrildi = 0
        if array_protokolu:
            self.__array__ = self._array          # örnek özniteliği: np.asarray bunu kullanır

    def _array(self, dtype=None, copy=None):
        return self._veri if dtype is None else self._veri.astype(dtype)

    def tolist(self):
        self.tolist_cagrildi += 1
        return self._veri.tolist()


class SahteSonuc:
    """mlx-audio ``GenerationResult``'ın kullanılan alanları."""

    def __init__(self, audio, sample_rate: int = 24000) -> None:
        self.audio = audio
        self.sample_rate = sample_rate
        self.samples = int(np.prod(getattr(audio, "shape", (0,))))


class SahteMlxModel:
    """Gerçek imzanın kopyası (mlx_audio/tts/models/chatterbox/chatterbox.py, 0.5.8); üreteç, metin başına 2 parça."""

    sample_rate = 24000

    def __init__(self, yol: str, kayit: dict) -> None:
        self.yol = yol
        self.sr = 24000
        self.calls: list[dict] = []
        self.kayit = kayit

    def generate(self, text, audio_prompt=None, audio_prompt_sr=None, conds=None, exaggeration=0.1, cfg_weight=0.5,
                 temperature=0.8, repetition_penalty=1.2, min_p=0.05, top_p=1.0, max_new_tokens=1000,
                 ref_audio=None, voice=None, speed=1.0, lang_code="en", max_tokens=None, verbose=True,
                 stream=False, streaming_interval=2.0, **kwargs):
        self.calls.append({"text": text, "ref_audio": ref_audio, "lang_code": lang_code, "exaggeration": exaggeration,
                           "cfg_weight": cfg_weight, "temperature": temperature, "verbose": verbose,
                           "audio_prompt": audio_prompt, "kwargs": dict(kwargs)})
        wav = speechlike(len(text), self.sample_rate, seed=len(self.calls))
        yari = len(wav) // 2
        dizi_protokolu = self.kayit.get("array_protokolu", True)
        for parca in (wav[:yari], wav[yari:]):
            yield SahteSonuc(SahteMxDizi(parca, array_protokolu=dizi_protokolu), self.sample_rate)


@pytest.fixture()
def sahte_mlx(monkeypatch):
    """Sahte mlx / mlx.core / mlx_audio(.tts.utils) modüllerini kurar; çağrılar ``kayit``'ta toplanır."""
    kayit: dict = {"seed": [], "load_model": [], "modeller": [], "array_protokolu": True}

    def load_model(model_path, lazy=False, strict=True, **kwargs):
        kayit["load_model"].append(str(model_path))
        model = SahteMlxModel(str(model_path), kayit)
        kayit["modeller"].append(model)
        return model

    mlx = _modul("mlx")
    mlx_core = _modul("mlx.core", random=types.SimpleNamespace(seed=lambda s: kayit["seed"].append(int(s))))
    mlx.core = mlx_core
    mlx_audio = _modul("mlx_audio")
    mlx_audio_tts = _modul("mlx_audio.tts")
    mlx_audio_utils = _modul("mlx_audio.tts.utils", load_model=load_model)
    mlx_audio.tts = mlx_audio_tts
    mlx_audio_tts.utils = mlx_audio_utils
    for name, mod in (("mlx", mlx), ("mlx.core", mlx_core), ("mlx_audio", mlx_audio), ("mlx_audio.tts", mlx_audio_tts),
                      ("mlx_audio.tts.utils", mlx_audio_utils)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(config, "MLX_MODEL", "mlx-community/chatterbox-multilingual-v3")
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", False)
    monkeypatch.setattr(config, "T3_EMOTION_SET", "", raising=False)
    monkeypatch.setattr(config, "T3_FINETUNED", None)
    monkeypatch.setattr(config, "DEVICE", None)
    return kayit


INCE_AYARLI_MLX = "/modeller/sesklon-t3-ince-ayar-mlx"


# ---------- kurulum / kayıt defteri ----------

def test_mlx_sinif_oznitelikleri():
    c = ChatterboxMlxBackend
    assert c.name == "chatterbox-mlx" and c.label == "Chatterbox Multilingual (MLX, Apple Silicon)"
    assert c.license == "MIT — ticari kullanım serbest" and c.commercial is True
    assert c.supports_emotion_controls is True and c.needs_torch is False
    assert c.required_modules == ("mlx", "mlx_audio") and c.install_hint == "pip install mlx-audio"
    params = inspect.signature(c.generate).parameters
    assert list(params) == ["self", "text", "language_id", "exaggeration", "cfg_weight", "temperature",
                            "audio_prompt_path", "emotion"]
    assert not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())     # **kwargs YOK


@pytest.mark.skipif(MLX_KURULU, reason="mlx kurulu; bu test mlx'siz kutu içindir")
def test_mlx_kurulu_degilken_describe_nedeni():
    ok, neden = ChatterboxMlxBackend.available()
    assert ok is False and "mlx" in neden and "kurulu değil" in neden
    satir = next(r for r in backends.describe() if r["name"] == "chatterbox-mlx")
    assert satir["available"] is False and "mlx" in satir["reason"]
    assert ChatterboxMlxBackend.install_hint in satir["reason"]
    assert satir["label"] == ChatterboxMlxBackend.label and satir["commercial"] is True
    with pytest.raises(BackendUnavailable) as exc:
        backends.create("mlx")
    assert "'chatterbox-mlx' arka ucu kullanılamıyor" in str(exc.value) and "pip install mlx-audio" in str(exc.value)


def test_mlx_sahte_modullerle_kurulu(sahte_mlx):
    assert ChatterboxMlxBackend.available() == (True, "kurulu")
    satir = next(r for r in backends.describe() if r["name"] == "chatterbox-mlx")
    assert satir["available"] is True and satir["reason"] == "kurulu"


def test_mlx_create_yukler(sahte_mlx):
    m = backends.create("chatterbox-mlx", device="cpu")
    assert isinstance(m, ChatterboxMlxBackend)
    assert sahte_mlx["load_model"] == ["mlx-community/chatterbox-multilingual-v3"]
    assert m.model_id == "mlx-community/chatterbox-multilingual-v3" and m.device == "mlx" and m.sr == 24000
    assert backends.create("mlx").name == "chatterbox-mlx"                      # takma ad
    info = m.info()
    assert info["name"] == "chatterbox-mlx" and info["mlx_model"] == "mlx-community/chatterbox-multilingual-v3"
    assert info["emotion_tags"] is False and info["sr"] == 24000 and info["device"] == "mlx"
    assert info["license"].startswith("MIT") and info["commercial"] is True


def test_mlx_ozel_model_ortam_degiskeni(sahte_mlx, monkeypatch):
    monkeypatch.setattr(config, "MLX_MODEL", "/yerel/chatterbox-mlx")
    m = ChatterboxMlxBackend()
    assert sahte_mlx["load_model"] == ["/yerel/chatterbox-mlx"] and m.model_id == "/yerel/chatterbox-mlx"
    assert m.info()["mlx_model"] == "/yerel/chatterbox-mlx"


def test_mlx_sr_modelden_ya_da_varsayilan(sahte_mlx, monkeypatch):
    class Model22k:
        sample_rate = 22050

        def generate(self, text, ref_audio=None, lang_code="en"):
            yield SahteSonuc(SahteMxDizi(np.zeros(2205)), 22050)

    class SrsizModel:
        def generate(self, text, ref_audio=None, lang_code="en"):
            return SahteSonuc(SahteMxDizi(np.zeros(2400)), 24000)

    utils = sys.modules["mlx_audio.tts.utils"]
    monkeypatch.setattr(utils, "load_model", lambda yol, **kw: Model22k())
    assert ChatterboxMlxBackend().sr == 22050
    monkeypatch.setattr(utils, "load_model", lambda yol, **kw: SrsizModel())
    m = ChatterboxMlxBackend()
    assert m.sr == 24000
    assert m.generate("Selam.").shape == (2400,)                 # tek sonuç (üreteç değil) de çalışır


def test_mlx_yukleme_hatasi_turkce(sahte_mlx, monkeypatch):
    def bozuk(yol, **kw):
        raise OSError("repo bulunamadı")

    monkeypatch.setattr(sys.modules["mlx_audio.tts.utils"], "load_model", bozuk)
    with pytest.raises(RuntimeError) as exc:
        ChatterboxMlxBackend()
    assert "MLX modeli yüklenemedi" in str(exc.value) and "repo bulunamadı" in str(exc.value)
    # mlx_audio içe aktarılamıyorsa: BackendUnavailable + kurulum ipucu
    monkeypatch.setitem(sys.modules, "mlx_audio.tts.utils", None)
    with pytest.raises(BackendUnavailable) as exc2:
        ChatterboxMlxBackend()
    assert "pip install mlx-audio" in str(exc2.value)


# ---------- üretim ----------

def test_mlx_generate_parcalari_birlestirir(sahte_mlx):
    m = ChatterboxMlxBackend()
    out = m.generate("Merhaba dünya, bugün hava çok güzel.")
    beklenen = speechlike(len("Merhaba dünya, bugün hava çok güzel."), 24000, seed=1)
    assert isinstance(out, np.ndarray) and out.dtype == np.float32 and out.ndim == 1
    assert out.flags["C_CONTIGUOUS"] and np.allclose(out, beklenen)          # iki parça sırasıyla birleşti


def test_mlx_generate_tolist_yolu(sahte_mlx):
    """``__array__`` desteklemeyen dizi: ``tolist()`` yoluna düşer (BaseBackend.to_numpy)."""
    sahte_mlx["array_protokolu"] = False
    m = ChatterboxMlxBackend()
    out = m.generate("Kısa bir cümle.")
    assert out.dtype == np.float32 and np.allclose(out, speechlike(len("Kısa bir cümle."), 24000, seed=1))
    sahte_mlx["array_protokolu"] = True
    out2 = m.generate("Kısa bir cümle.")
    assert out2.dtype == np.float32 and out2.ndim == 1 and len(out2) > 0


def test_mlx_np_asarray_hizli_yol_tolist_cagirmaz(sahte_mlx):
    m = ChatterboxMlxBackend()
    dizi = SahteMxDizi(np.ones((1, 480)))
    out = m._numpy(dizi)
    assert out.shape == (480,) and out.dtype == np.float32 and dizi.tolist_cagrildi == 0
    yavas = SahteMxDizi(np.ones(480), array_protokolu=False)
    assert m._numpy(yavas).shape == (480,) and yavas.tolist_cagrildi == 1


def test_mlx_gercek_imza_parametre_eslemesi(sahte_mlx):
    m = ChatterboxMlxBackend()
    m.generate("Merhaba.", language_id="tr", exaggeration=0.7, cfg_weight=0.3, temperature=0.9,
               audio_prompt_path=Path("ref.wav"), emotion="mutlu")
    c = sahte_mlx["modeller"][-1].calls[-1]
    assert c["ref_audio"] == "ref.wav" and c["lang_code"] == "tr"           # language_id → lang_code
    assert c["exaggeration"] == 0.7 and c["cfg_weight"] == 0.3 and c["temperature"] == 0.9
    assert c["verbose"] is False and c["audio_prompt"] is None
    assert c["kwargs"] == {}                  # **kwargs'a bilinmeyen ad (language_id, emotion…) sızmadı
    m.generate("Referanssız.")
    c2 = sahte_mlx["modeller"][-1].calls[-1]
    assert c2["ref_audio"] is None and c2["lang_code"] == "tr"


@pytest.mark.parametrize("imza, beklenen", [
    ("audio_prompt_path_language", {"text": "Selam.", "audio_prompt_path": "r.wav", "language": "tr",
                                    "exaggeration": 0.8}),
    ("speaker_wav_language_id", {"text": "Selam.", "speaker_wav": "r.wav", "language_id": "tr", "cfg_weight": 0.2,
                                 "temperature": 0.6}),
    ("yalnizca_kwargs", {"text": "Selam.", "ref_audio": "r.wav", "lang_code": "tr", "exaggeration": 0.8,
                         "cfg_weight": 0.2, "temperature": 0.6}),
    ("referanssiz", {"text": "Selam.", "lang_code": "tr"}),
])
def test_mlx_parametre_suzme_varyantlari(sahte_mlx, imza, beklenen):
    cagrilar: list[dict] = []

    def audio_prompt_path_language(text, audio_prompt_path=None, language="en", exaggeration=0.5):
        cagrilar.append({"text": text, "audio_prompt_path": audio_prompt_path, "language": language,
                         "exaggeration": exaggeration})
        yield SahteSonuc(SahteMxDizi(np.zeros(240)))

    def speaker_wav_language_id(text, speaker_wav=None, language_id="en", cfg_weight=0.5, temperature=0.8):
        cagrilar.append({"text": text, "speaker_wav": speaker_wav, "language_id": language_id,
                         "cfg_weight": cfg_weight, "temperature": temperature})
        yield SahteSonuc(SahteMxDizi(np.zeros(240)))

    def yalnizca_kwargs(text, **kwargs):
        cagrilar.append({"text": text, **kwargs})
        yield SahteSonuc(SahteMxDizi(np.zeros(240)))

    def referanssiz(text, lang_code="en"):
        cagrilar.append({"text": text, "lang_code": lang_code})
        yield SahteSonuc(SahteMxDizi(np.zeros(240)))

    m = ChatterboxMlxBackend()
    m._model.generate = locals()[imza]
    out = m.generate("Selam.", language_id="tr", exaggeration=0.8, cfg_weight=0.2, temperature=0.6,
                     audio_prompt_path="r.wav", emotion="mutlu")
    assert cagrilar == [beklenen] and out.shape == (240,)


def test_mlx_ornekleme_hizi_uyusmazligi_yeniden_ornekler(sahte_mlx):
    m = ChatterboxMlxBackend()

    def gen16k(text, lang_code="en"):
        yield SahteSonuc(SahteMxDizi(np.zeros(1600)), 16000)

    m._model.generate = gen16k
    assert m.generate("Selam.").shape == (2400,)          # 0,1 sn 16 kHz → 24 kHz


def test_mlx_bos_cikti_turkce_hata(sahte_mlx):
    m = ChatterboxMlxBackend()
    m._model.generate = lambda text, lang_code="en": iter(())
    with pytest.raises(RuntimeError) as exc:
        m.generate("Selam.")
    assert "ses üretmedi" in str(exc.value)


def test_mlx_duygu_etiketi_ince_ayarli_modelde(sahte_mlx, monkeypatch):
    monkeypatch.setattr(config, "MLX_MODEL", INCE_AYARLI_MLX)
    m = ChatterboxMlxBackend()
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", True)
    for duygu in ("mutlu", "normal", None, "Üzgün", "kızgın"):
        m.generate("[kızgın] Yeter artık!" if duygu == "kızgın" else "Merhaba dünya.", emotion=duygu)
    texts = [c["text"] for c in m._model.calls]
    assert texts == ["[mutlu] Merhaba dünya.", "Merhaba dünya.", "Merhaba dünya.", "[üzgün] Merhaba dünya.",
                     "[kızgın] Yeter artık!"]
    info = m.info()
    assert info["emotion_tags"] is True and "mutlu" in info["emotion_set"] and "normal" not in info["emotion_set"]
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", False)
    m.generate("Merhaba dünya.", emotion="mutlu")
    assert m._model.calls[-1]["text"] == "Merhaba dünya." and m.info()["emotion_tags"] is False
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", True)
    assert m.tag_text("Selam", "  ") == "Selam"
    assert m.tag_text("Selam", "uydurma-duygu") == "Selam"          # bankada olmayan duygu etiket almaz


@pytest.mark.parametrize("finetuned", [None, "/x/t3_finetuned.safetensors"])
def test_mlx_varsayilan_modelde_etiketler_atlanir_bir_kez_uyarir(sahte_mlx, monkeypatch, caplog, finetuned):
    """Temel MLX modeli etiketi görmedi: T3_EMOTION_TAGS=1 (+ T3_FINETUNED) olsa da önek eklenmez, tek uyarı."""
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", True)
    monkeypatch.setattr(config, "T3_FINETUNED", finetuned)
    with caplog.at_level("WARNING", logger="sesklon.backends.chatterbox_mlx"):
        m = ChatterboxMlxBackend()
        m.generate("Merhaba dünya.", emotion="mutlu")
        m.generate("Yeter artık!", emotion="kızgın")
    assert [c["text"] for c in m._model.calls] == ["Merhaba dünya.", "Yeter artık!"]
    uyarilar = [r for r in caplog.records if "etiketleri atlanıyor" in r.getMessage()]
    assert len(uyarilar) == 1
    if finetuned:
        assert "MLX'e uygulanmadığı" in uyarilar[0].getMessage()
    assert m.info()["emotion_tags"] is False and m.info()["emotion_set"] == []


def test_mlx_varsayilan_model_sonradan_acilan_etiket_uyarisi(sahte_mlx, monkeypatch, caplog):
    m = ChatterboxMlxBackend()                                  # açılışta etiket kapalı → uyarı yok
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", True)
    with caplog.at_level("WARNING", logger="sesklon.backends.chatterbox_mlx"):
        m.generate("Merhaba.", emotion="mutlu")
        m.generate("Merhaba.", emotion="mutlu")
    assert sum("etiketleri atlanıyor" in r.getMessage() for r in caplog.records) == 1
    assert m._model.calls[-1]["text"] == "Merhaba."


def test_mlx_duygu_kumesi_pytorch_ile_ayni():
    """Bilerek tekrarlanan liste PyTorch arka ucununkiyle aynı kalmalı (ayrışırsa bu test yakalar)."""
    from app.backends.chatterbox import DEFAULT_EMOTION_SET
    from app.backends.chatterbox_mlx import VARSAYILAN_DUYGU_KUMESI

    assert tuple(VARSAYILAN_DUYGU_KUMESI) == tuple(DEFAULT_EMOTION_SET)


@pytest.mark.parametrize("model, beklenen", [
    ("mlx-community/chatterbox-multilingual-v3", True), ("MLX-Community/Chatterbox-Multilingual-V3/", True),
    (" mlx-community/chatterbox-multilingual-v3 ", True), (INCE_AYARLI_MLX, False),
    ("mlx-community/chatterbox-fp16", False),
])
def test_mlx_varsayilan_model_tespiti(model, beklenen):
    from app.backends.chatterbox_mlx import varsayilan_model_mi

    assert varsayilan_model_mi(model) is beklenen


def test_mlx_duygu_kumesi_suzgeci(sahte_mlx, monkeypatch):
    monkeypatch.setattr(config, "MLX_MODEL", INCE_AYARLI_MLX)
    monkeypatch.setattr(config, "T3_EMOTION_TAGS", True)
    monkeypatch.setattr(config, "T3_EMOTION_SET", "Mutlu, ÜZGÜN ,normal")
    m = ChatterboxMlxBackend()
    for duygu in ("mutlu", "üzgün", "kızgın", "normal"):
        m.generate("Merhaba.", emotion=duygu)
    assert [c["text"] for c in m._model.calls] == ["[mutlu] Merhaba.", "[üzgün] Merhaba.", "Merhaba.", "Merhaba."]
    assert m.info()["emotion_set"] == ["mutlu", "üzgün"]
    # config'te T3_EMOTION_SET hiç yoksa boş sayılır → bankadaki 19 duygu
    monkeypatch.delattr(config, "T3_EMOTION_SET")
    from app.backends.chatterbox_mlx import VARSAYILAN_DUYGU_KUMESI, duygu_kumesi

    assert duygu_kumesi() == frozenset(VARSAYILAN_DUYGU_KUMESI) and len(VARSAYILAN_DUYGU_KUMESI) == 19
    m.generate("Merhaba.", emotion="kızgın")
    assert m._model.calls[-1]["text"] == "[kızgın] Merhaba."


def test_mlx_seed(sahte_mlx, monkeypatch):
    m = ChatterboxMlxBackend()
    m.seed(42)
    assert sahte_mlx["seed"] == [42]
    monkeypatch.setitem(sys.modules, "mlx.core", None)                       # import → ImportError
    m.seed(7)                                                                 # sessizce geçer
    assert sahte_mlx["seed"] == [42]


def test_mlx_conds_yalnizca_ic_modelde_varsa(sahte_mlx):
    m = ChatterboxMlxBackend()
    assert not hasattr(m, "conds") and getattr(m, "conds", None) is None     # gerçek MLX modelinde genel conds yok
    with pytest.raises(AttributeError):
        m.conds = "x"
    m._model.conds = "varsayılan"                                             # conds sunan bir sürüm
    assert hasattr(m, "conds") and m.conds == "varsayılan"
    m.conds = "klon"
    assert m._model.conds == "klon"


def test_mlx_ince_ayar_uyarisi(sahte_mlx, monkeypatch, caplog):
    monkeypatch.setattr(config, "T3_FINETUNED", "/x/t3.safetensors")
    with caplog.at_level("WARNING", logger="sesklon.backends.chatterbox_mlx"):
        m = ChatterboxMlxBackend()
    assert "T3_FINETUNED" in caplog.text and m.model_id == "mlx-community/chatterbox-multilingual-v3"


# ---------- motor + MLX arka ucu uçtan uca ----------

def test_motor_mlx_arka_ucuyla_uctan_uca(sahte_mlx):
    eng = Engine(backend="chatterbox-mlx")
    assert eng.backend_name == "chatterbox-mlx" and eng.device == "cpu" and not eng.loaded
    wav, sr, rep = eng.synthesize("[mutlu] Merhaba dünya! Bugün hava çok güzel.", "tr", None, seed=3, master=False,
                                  breaths=False, room_tone=False, qc=False)
    assert sr == 24000 and wav.ndim == 1 and wav.dtype == np.float32 and len(wav) > sr * 0.5
    assert rep["chunks"] and rep["chunks"][0]["emotion"] == "mutlu"
    model = eng.tts()
    assert isinstance(model, ChatterboxMlxBackend) and eng.model_name == "mlx-community/chatterbox-multilingual-v3"
    calls = model._model.calls
    assert calls and all(c["lang_code"] == "tr" and c["ref_audio"] is None and c["kwargs"] == {} for c in calls)
    assert all(not c["text"].startswith("[") for c in calls)                 # etiket kapalı
    assert 3 in sahte_mlx["seed"]                                             # motor tohumu mx.random.seed'e ulaştı
    # referansla (ad hoc yol)
    wav2, sr2, _ = eng.synthesize("Kısa bir deneme cümlesi.", "tr", VoiceRefs("v", Path("ref.wav"), {}), seed=1,
                                  master=False, breaths=False, room_tone=False, qc=False)
    assert sr2 == 24000 and len(wav2) > 0 and calls[-1]["ref_audio"] == "ref.wav"
