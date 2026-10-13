"""Motorun gerçek ses zinciri: sahte Chatterbox modeli ile tüm doğallık katmanları (normalizasyon → bölümleme →
üretim → prozodi/nefes/oda tonu → mastering) uçtan uca çalışır. Model yerine konuşma benzeri sentetik ses üretilir."""
import json

import numpy as np
import pytest
import soundfile as sf

from app import audio
from app.engine import Engine, VoiceRefs

SR = 24000


def _speechlike(n_chars: int, seed: int = 0) -> np.ndarray:
    """Konuşma benzeri sinyal: 150 Hz temel + harmonikler, 5 Hz hece zarfı, ~0,07 sn/karakter."""
    rng = np.random.default_rng(seed)
    dur = max(0.4, n_chars * 0.07)
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    f0 = 150 + 20 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    sig = sum((0.5 / k) * np.sin(k * phase) for k in range(1, 6))
    env = 0.55 + 0.45 * np.sin(2 * np.pi * 5 * t) ** 2
    sig = sig * env * 0.25 + rng.standard_normal(len(t)) * 0.002
    return sig.astype(np.float32)


class FakeModel:
    sr = SR

    def __init__(self):
        self.calls = []

    def generate(self, text, language_id="tr", exaggeration=0.5, cfg_weight=0.5, temperature=0.8, audio_prompt_path=None):
        self.calls.append({"text": text, "ex": exaggeration, "cfg": cfg_weight, "ref": audio_prompt_path})
        return _speechlike(len(text), seed=len(self.calls))


class ChainEngine(Engine):
    """Gerçek Engine; yalnızca model yüklemesi sahte."""

    def __init__(self):
        self.device, self.model_name = "cpu", "fake-chain"
        self._tts, self._vc = FakeModel(), None
        import threading

        self._lock, self._load_lock = threading.Lock(), threading.Lock()
        self.loading, self.load_error = False, None
        self._ref_cache = {}

    def tts(self):
        return self._tts

    def _seed(self, seed):
        pass


@pytest.fixture()
def ref_path(tmp_path):
    """Gerçekçi referans: konuşma + duraklamalar + nefes + oda gürültüsü."""
    rng = np.random.default_rng(1)
    parts = []
    for i in range(4):
        parts.append(_speechlike(40, seed=i))
        parts.append(np.zeros(int(SR * 0.45), dtype=np.float32))
    wav = np.concatenate(parts)
    wav += (rng.standard_normal(len(wav)) * 0.0008).astype(np.float32)   # ~ -62 dBFS oda tonu
    p = tmp_path / "ref.wav"
    sf.write(str(p), wav, SR)
    return p


def test_chain_produces_natural_output(ref_path):
    from app.analysis import analyze_reference

    analysis = analyze_reference(ref_path)
    assert "pauses" in analysis and "quality_score" in analysis
    refs = VoiceRefs("v1", ref_path, {}, analysis)
    eng = ChainEngine()
    text = ("[heyecanlı] Selam millet! Bugün 12.10.2026 tarihinde, saat 14:30'da başlıyoruz.\n\n"
            "[sakin] Peki nasıl çalışıyor? Çok basit, geleceğim ve göstereceğim. [nefes] Ama önce bir şey söyleyeyim... "
            "Fiyatı sadece 1.250 TL.")
    partials = []
    wav, sr, report = eng.synthesize(text, "tr", refs, seed=7, colloquial="light", pause_scale=1.1,
                                     partial=lambda i, w, s, t: partials.append((i, len(w) / s, t)))
    assert sr == SR and wav.ndim == 1 and len(wav) > SR
    # normalizasyon + konuşma dili çalıştı
    norm = report["normalized_text"]
    assert "on iki ekim iki bin yirmi altı" in norm and "on dört otuzda" in norm and "bin iki yüz elli lira" in norm
    assert "gelicem" in norm and "bişey" in norm
    assert any(c["from"] == "geleceğim" and c["to"] == "gelicem" for c in report["colloquial_changes"])
    # parçalar ve duygular
    chunks = report["chunks"]
    assert len(chunks) >= 3 and chunks[0]["emotion"] == "heyecanlı" and any(c["emotion"] == "sakin" for c in chunks)
    assert len(partials) == len(chunks) and partials[0][0] == 0
    # prozodi: planlanan duraklamalar, nefes, oda tonu; son parça 0
    pro = report["prosody"]
    assert "fallback" not in pro, pro
    assert len(pro["pauses_ms"]) == len(chunks) and pro["pauses_ms"][-1] == 0
    assert all(60 <= p <= 2500 for p in pro["pauses_ms"][:-1])
    assert pro["room_tone"] is True
    assert abs(pro["pause_scale"] - 1.1 * analysis["pauses"]["scale"]) < 0.01
    # toplam süre ≈ parçalar + duraklamalar (nefes payıyla)
    expected = sum(c["duration"] for c in chunks) + sum(pro["pauses_ms"]) / 1000
    assert expected * 0.95 <= len(wav) / sr <= expected * 1.25
    # duraklamalarda sıfır değil oda tonu var: en sessiz 100 ms penceresi tam sıfır değil
    frame = int(sr * 0.1)
    n = len(wav) // frame
    rms = np.sqrt(np.mean(wav[: n * frame].reshape(n, frame) ** 2, axis=1))
    assert rms.min() > 0 and 20 * np.log10(rms.min() + 1e-12) > -90
    # mastering: tepe sınırı ve ses yüksekliği
    assert np.max(np.abs(wav)) <= audio.db_to_amp(-1.5) + 1e-3
    loud = report.get("loudness") or {}
    if loud.get("lufs") is not None:
        assert -19.5 <= loud["lufs"] <= -12.5, loud
    # JSON'a yazılabilir rapor
    json.dumps(report)


def test_chain_options_off(ref_path):
    eng = ChainEngine()
    refs = VoiceRefs("v1", ref_path, {})
    wav, sr, report = eng.synthesize("Birinci paragraf, geleceğim.\n\nİkinci paragraf.\n\nÜçüncü paragraf.", "tr", refs,
                                     seed=1, colloquial="off", breaths=False, room_tone=False, master=False)
    pro = report["prosody"]
    assert pro["breaths"] == 0 and pro["room_tone"] is False
    assert report["colloquial_level"] == "off" and report["colloquial_changes"] == []
    assert "geleceğim" in report["normalized_text"]          # konuşma dili kapalı: dokunulmadı
    assert len(report["chunks"]) == 3
    # oda tonu kapalı: duraklamalar tam sıfır (paragraf duraklaması ≥ 600 ms)
    pauses = pro["pauses_ms"]
    assert pauses[0] >= 600
    d0 = int(report["chunks"][0]["duration"] * sr)
    gap = wav[d0 + int(sr * 0.05): d0 + int(sr * pauses[0] / 1000) - int(sr * 0.05)]
    assert gap.size > 0 and np.max(np.abs(gap)) == 0.0


def test_chain_cancel(ref_path):
    from app.jobs import JobCancelled

    eng = ChainEngine()
    refs = VoiceRefs("v1", ref_path, {})
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        if calls["n"] >= 2:
            raise JobCancelled("iptal")

    with pytest.raises(JobCancelled):
        eng.synthesize("Bir.\n\nİki.\n\nÜç.\n\nDört.", "tr", refs, check_cancelled=check)
    assert len(eng._tts.calls) == 1      # ikinci parçaya geçmeden durdu


def test_chain_without_reference():
    eng = ChainEngine()
    wav, sr, report = eng.synthesize("Referanssız üretim. Model sesi.", "tr", None, seed=3)
    assert len(wav) > 0 and report["chunks"][0]["ref"] == "model"
    assert report["prosody"]["room_tone"] is False     # kayıt yok → oda tonu yok; sentetik nefes olabilir


def test_tag_pauses_applied_verbatim(ref_path):
    """[2 sn] gibi etiket duraklamaları planlayıcı ölçeği/kırpmasından etkilenmez, birebir eklenir."""
    eng = ChainEngine()
    refs = VoiceRefs("v1", ref_path, {})
    _, sr, rep = eng.synthesize("Birinci cümle bitiyor. [5 sn] Ama ikinci cümle başlıyor.", "tr", refs, seed=1,
                                breaths=False, room_tone=False, master=False)
    pauses = rep["prosody"]["pauses_ms"]
    assert len(pauses) == 2 and pauses[0] >= 5000 and pauses[0] <= 5000 + 2500
    _, _, rep2 = eng.synthesize("Birinci cümle bitiyor. Ama ikinci cümle başlıyor.", "tr", refs, seed=1,
                                breaths=False, room_tone=False, master=False)
    assert rep2["prosody"]["pauses_ms"][0] < 1000          # etiketsiz: yalnızca bağlaç-kısaltmalı normal duraklama


def test_manual_pause_scale_overrides_analysis(ref_path):
    from app.analysis import analyze_reference

    analysis = analyze_reference(ref_path)
    eng = ChainEngine()
    auto = eng.synthesize("Bir.\n\nİki.", "tr", VoiceRefs("v", ref_path, {}, analysis), seed=1, master=False)[2]
    manual = eng.synthesize("Bir.\n\nİki.", "tr", VoiceRefs("v", ref_path, {}, analysis, pause_scale=1.8), seed=1, master=False)[2]
    assert abs(auto["prosody"]["pause_scale"] - analysis["pauses"]["scale"]) < 0.01
    assert abs(manual["prosody"]["pause_scale"] - 1.8) < 0.01
