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
from app.backends.f5_turkish import F5TurkishBackend, ses_suresi
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


# ---------- tohum tek kullanımlık ----------

def test_f5_tohum_tek_kullanimlik(sahte_f5):
    """Tohumlu istekten sonra tohumsuz istekler eski tohumu almaz; F5'e seed hiç gönderilmez (rastgele seçer)."""
    m = F5TurkishBackend()
    m.seed(5)
    m.generate("Birinci.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="Selam.")
    m.generate("İkinci.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="Selam.")
    m.generate("Üçüncü.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="Selam.")
    assert [c["seed"] for c in sahte_f5["infer"]] == [5, None, None] and m._seed is None
    # infer'e "seed" anahtarı hiç gitmez: imzası seed bilmeyen bir infer de çalışır
    alinan = []
    m._model.infer = lambda ref_file, ref_text, gen_text: (alinan.append(gen_text) or np.zeros(2400), 24000, None)
    m.seed(9)
    m.generate("Dört.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="x")
    assert alinan == ["Dört."] and m._seed is None


def test_motor_f5_tohumsuz_istek_onceki_tohumu_almaz(sahte_f5):
    eng = Engine(backend="f5-tr")
    refs = VoiceRefs("v", base=Path(sahte_f5["ref"]), by_emotion={})
    eng.synthesize("Merhaba dünya.", "tr", refs, seed=5, master=False, breaths=False, room_tone=False, qc=False)
    n = len(sahte_f5["infer"])
    assert n and all(c["seed"] is not None for c in sahte_f5["infer"])
    eng.synthesize("Bugün hava güzel.", "tr", refs, seed=None, master=False, breaths=False, room_tone=False,
                   qc=False)
    sonraki = sahte_f5["infer"][n:]
    assert sonraki and all(c["seed"] is None for c in sonraki)


# ---------- uzun referans: F5'in 12 sn kırpmasıyla aynı kırpma ----------

def _uzun_referans(yol: Path, bolumler: list[tuple[str, float]], sr: int = 24000) -> Path:
    """("konuşma"|"sessizlik", sn) bölümlerinden WAV yazar."""
    parcalar = []
    for i, (tur, sn) in enumerate(bolumler):
        if tur == "konuşma":
            p = speechlike(int(sn / 0.07), sr, seed=i)[: int(sn * sr)]
        else:
            p = np.zeros(int(sn * sr), dtype=np.float32)
        parcalar.append(p)
    sf.write(str(yol), np.concatenate(parcalar), sr)
    return yol


def test_f5_uzun_referans_sessizlikten_kirpilir_transkript_kirpilmistan(sahte_f5):
    uzun = _uzun_referans(sahte_f5["tmp"] / "uzun.wav", [("konuşma", 5.0), ("sessizlik", 1.5), ("konuşma", 4.0),
                                                         ("sessizlik", 1.2), ("konuşma", 4.0)])
    assert ses_suresi(str(uzun)) > 15.0
    m = F5TurkishBackend()
    m.clip_dir = sahte_f5["tmp"] / "kirp"
    m.generate("Merhaba.", audio_prompt_path=str(uzun))
    kirpik = sahte_f5["infer"][-1]["ref_file"]
    assert kirpik != str(uzun) and Path(kirpik).parent == m.clip_dir
    sure = ses_suresi(kirpik)
    assert 8.0 <= sure <= 12.0, sure                   # son 4 sn'lik konuşma (sessizlikten) atıldı
    assert sahte_f5["transcribe"] == [{"ref_audio": kirpik, "language": "tr"}]    # transkript kırpılmış sesten
    # önbellek: ikinci üretim yeniden kırpmaz, transkripti de yeniden çıkarmaz
    mtime = Path(kirpik).stat().st_mtime_ns
    m.generate("Tekrar.", audio_prompt_path=str(uzun))
    assert sahte_f5["infer"][-1]["ref_file"] == kirpik and Path(kirpik).stat().st_mtime_ns == mtime
    assert len(sahte_f5["transcribe"]) == 1 and len(list(m.clip_dir.iterdir())) == 1


def test_f5_uzun_referansta_verilen_ref_text_yok_sayilir(sahte_f5, caplog):
    uzun = _uzun_referans(sahte_f5["tmp"] / "uzun2.wav", [("konuşma", 14.0)])
    m = F5TurkishBackend()
    m.clip_dir = sahte_f5["tmp"] / "kirp"
    with caplog.at_level(logging.WARNING, logger="sesklon.backends.f5"):
        m.generate("Merhaba.", audio_prompt_path=str(uzun), ref_text="tam kaydın on dört saniyelik metni")
    c = sahte_f5["infer"][-1]
    assert c["ref_text"] == "referans metni" and c["ref_file"] != str(uzun)
    assert ses_suresi(c["ref_file"]) <= 12.05            # sessizlik yok → ilk 12 sn kesildi (+50 ms)
    assert any("yok sayılıyor" in r.getMessage() for r in caplog.records)


def test_f5_kisa_referans_kirpilmaz(sahte_f5):
    m = F5TurkishBackend()
    m.clip_dir = sahte_f5["tmp"] / "kirp"
    assert ses_suresi(str(sahte_f5["ref"])) < 12.0
    assert m.clip_reference(str(sahte_f5["ref"])) == str(sahte_f5["ref"])
    m.generate("Merhaba.", audio_prompt_path=str(sahte_f5["ref"]), ref_text="Selam.")
    assert sahte_f5["infer"][-1]["ref_file"] == str(sahte_f5["ref"]) and not m.clip_dir.exists()
    assert m.clip_reference(str(sahte_f5["tmp"] / "yok.wav")) == str(sahte_f5["tmp"] / "yok.wav")


def test_f5_pydub_varsa_f5_ile_ayni_cagrilar(sahte_f5, monkeypatch):
    """pydub kuruluysa (f5-tts bağımlılığı) kırpma upstream preprocess_ref_audio_text'in parametreleriyle yapılır."""
    cagri: dict = {"split": [], "lead": [], "export": []}

    class Seg:
        frame_rate = 24000

        def __init__(self, ms):
            self.ms = ms

        def __len__(self):
            return self.ms

        def __add__(self, o):
            return Seg(self.ms + o.ms)

        def __getitem__(self, sl):
            return Seg(len(range(self.ms)[sl]))

        def reverse(self):
            return self

        def export(self, yol, format=None):
            cagri["export"].append((yol, format, self.ms))
            sf.write(yol, np.zeros(int(self.ms * 24)), 24000)

    class AudioSegment:
        @staticmethod
        def from_file(yol):
            return Seg(15700)

        @staticmethod
        def silent(duration=1000, frame_rate=11025):
            return Seg(duration)

    def split_on_silence(aseg, **kw):
        cagri["split"].append(kw)
        return [Seg(5000), Seg(5000), Seg(5700)]

    def detect_leading_silence(seg, silence_threshold=-50.0, chunk_size=10):
        cagri["lead"].append(silence_threshold)
        return 100

    silence = _modul("pydub.silence", split_on_silence=split_on_silence,
                     detect_leading_silence=detect_leading_silence)
    pydub = _modul("pydub", AudioSegment=AudioSegment, silence=silence)
    monkeypatch.setitem(sys.modules, "pydub", pydub)
    monkeypatch.setitem(sys.modules, "pydub.silence", silence)
    uzun = _uzun_referans(sahte_f5["tmp"] / "uzun3.wav", [("konuşma", 15.7)])
    m = F5TurkishBackend()
    m.clip_dir = sahte_f5["tmp"] / "kirp"
    kirpik = m.clip_reference(str(uzun))
    assert cagri["split"] == [{"min_silence_len": 1000, "silence_thresh": -50, "keep_silence": 1000,
                               "seek_step": 10}]           # ilk adım 12 sn'nin altına indirdi
    assert cagri["lead"] == [-42, -42]
    assert cagri["export"] == [(kirpik, "wav", 10000 - 200 + 50)]
