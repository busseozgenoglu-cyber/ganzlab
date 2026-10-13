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
    """Konuşma benzeri sinyal: 150 Hz temel + harmonikler, DÜZENSİZ hece zarfı (süre/genlik rastgele), ~0,07 sn/karakter.
    Düzenli (tam periyodik) zarf, kalite kontrolünün "tekrar" dedektörünü haklı olarak tetikler; gerçek konuşma gibi
    her hece farklı uzunlukta ve şiddette üretilir."""
    rng = np.random.default_rng(seed)
    dur = max(0.4, n_chars * 0.07)
    n = int(SR * dur)
    t = np.arange(n) / SR
    f0 = 150 + 20 * np.sin(2 * np.pi * 0.7 * t) + rng.standard_normal(n).cumsum() * 0.02
    phase = 2 * np.pi * np.cumsum(f0) / SR
    sig = sum((0.5 / k) * np.sin(k * phase) for k in range(1, 6))
    env = np.zeros(n)
    pos = 0
    while pos < n:
        syl = int(SR * rng.uniform(0.12, 0.28))
        gap = int(SR * rng.uniform(0.0, 0.05))
        amp = rng.uniform(0.5, 1.0)
        seg = np.hanning(max(8, syl)) ** 0.7 * amp
        end = min(n, pos + len(seg))
        env[pos:end] = seg[: end - pos]
        pos += syl + gap
    env = 0.15 + 0.85 * env
    sig = sig * env * 0.25 + rng.standard_normal(n) * 0.002
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
        self._ref_cache, self._ltas_cache, self._cps_history, self._default_conds = {}, {}, {}, None

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


def test_chain_v4_features(ref_path, tmp_path):
    """Yoğunluk, kayış, vurgu, gerçek tepki kaydı, sözlük, QC ve zaman çizelgesi birlikte."""
    from app.nonverbal import prepare_nonverbal
    from app import lexicon

    # gerçek gülme kaydı
    sr = SR
    rng = np.random.default_rng(3)
    parts = []
    for _ in range(3):
        n = int(sr * 0.22)
        t = np.linspace(0, 0.22, n, endpoint=False)
        parts.append(((0.25 * np.sin(2 * np.pi * 180 * t) + rng.standard_normal(n) * 0.08) * np.hanning(n)).astype(np.float32))
        parts.append(np.zeros(int(sr * 0.06), dtype=np.float32))
    raw = tmp_path / "raw.wav"
    sf.write(str(raw), np.concatenate(parts), sr)
    laugh = tmp_path / "gulme.wav"
    prepare_nonverbal(raw, laugh, sr)
    lexicon.set_entry("Fumor", "Fumór", "v1")

    eng = ChainEngine()
    refs = VoiceRefs("v1", ref_path, {}, None, None, {"gülme": laugh}, "Buse")
    text = ("[çok heyecanlı] Fumor mağazası açıldı! [gülme] Bu *gerçekten* güzel.\n\n"
            "[sakinleşerek] Şimdi biraz sakin olalım. Her şey yolunda. [hız:0.9] Yavaşça anlatıyorum.")
    wav, sr, rep = eng.synthesize(text, "tr", refs, seed=11, master=False)
    chunks = rep["chunks"]
    # gerçek tepki kullanıldı, metne "Hahaha" gömülmedi
    assert rep["nonverbal_used"] == ["gülme"]
    assert not any("Hahaha" in c["text"] for c in chunks)
    nv_chunks = [c for c in chunks if c.get("nonverbal") == "gülme"]
    assert len(nv_chunks) == 1 and nv_chunks[0]["ref"] == "tepki kaydı" and 0.3 <= nv_chunks[0]["duration"] <= 3.0
    # yoğunluk ve vurgu parçaları
    first = chunks[0]
    assert first["intensity"] and first["intensity"] > 1.0 and first["emotion"] == "heyecanlı"
    assert any(c.get("emphasized") for c in chunks) and any("gerçekten" == c["text"].strip(".,!") for c in chunks if c.get("emphasized"))
    # kayış: arc_to sakin işaretli parçalar
    assert any(c.get("arc_to") == "sakin" for c in chunks)
    # hız kontrolü: [hız:0.9] sonrası parça hızı < 1
    slow = [c for c in chunks if "Yavaşça" in c["text"]]
    assert slow and slow[0]["speed"] < 1.0
    # sözlük uygulandı
    assert "Fumór" in rep["normalized_text"] and any(c["from"] == "Fumor" for c in rep["lexicon_changes"])
    # QC raporları ve zaman çizelgesi
    assert rep.get("qc_summary") and all("qc_score" in c for c in chunks if not c.get("nonverbal"))
    tl = rep["timeline"]
    assert len(tl) == len(chunks) and tl[-1]["end"] <= len(wav) / sr + 0.05
    assert all(tl[i]["end"] <= tl[i + 1]["start"] + 1e-6 for i in range(len(tl) - 1))
    # tutarlılık raporu
    assert rep["prosody"].get("consistency") is not None
    # vurgu/tepki mikro duraklamaları makul
    assert all(0 <= p <= 2500 for p in rep["prosody"]["pauses_ms"][:-1])


def test_chain_dialog(ref_path):
    eng = ChainEngine()
    a = VoiceRefs("a", ref_path, {}, None, None, {}, "Ayşe Sesi")
    b = VoiceRefs("b", ref_path, {}, None, None, {}, "Mehmet Sesi")
    text = "İkisi kafede oturuyordu.\nAyşe: Selam, naber?\nMehmet: İyiyim ya, sen?\nAyşe: Ben de iyiyim."
    wav, sr, rep = eng.synthesize_dialog(text, {"Ayşe": a, "Mehmet": b}, a, "tr", seed=5, master=False,
                                         default_emotions={"Mehmet": "sıkılmış"})
    assert rep["dialog"] and len(rep["turns"]) == 4
    assert [t["speaker"] for t in rep["turns"]] == [None, "Ayşe", "Mehmet", "Ayşe"]
    assert rep["turns"][2]["voice_name"] == "Mehmet Sesi"
    assert rep["turns"][0]["end"] <= rep["turns"][1]["start"] and rep["turns"][2]["end"] <= rep["turns"][3]["start"]
    # Mehmet'in parçası varsayılan duyguyu aldı
    mehmet = [c for c in rep["chunks"] if c["speaker"] == "Mehmet"]
    assert mehmet and mehmet[0]["emotion"] == "sıkılmış"
    # soru→cevap sıra alma duraklaması kısa (< 450): "naber?" → Mehmet
    pauses = rep["prosody"]["pauses_ms"]
    q_idx = next(i for i, c in enumerate(rep["chunks"]) if "naber" in c["text"])
    assert 120 <= pauses[q_idx] <= 450
    assert len(wav) > sr and rep["timeline"]


def test_chain_review_regressions(ref_path, tmp_path):
    """v4 incelemesinin bulguları: kaydı olmayan tepki satır içinde kalır, sıra duraklaması ezilmez,
    cps geçmişi ham süreden, dolgular bölüm başına seed, vurgu kısa parça sınırı, [1 sn] başta yok sayılır."""
    eng = ChainEngine()
    refs = VoiceRefs("v1", ref_path, {}, None, None, {}, "Buse")        # tepki kaydı YOK
    # kaydı olmayan [gülme] → tek başına parça olmaz, bir sonraki cümleye okunuş olarak gömülür
    _, sr, rep = eng.synthesize("[gülme] Çok komik bir şey oldu. Bunu duyunca [gülme] çok şaşırdım.", "tr", refs,
                                seed=2, master=False, breaths=False)
    texts = [c["text"] for c in rep["chunks"]]
    assert not any(c.get("nonverbal") for c in rep["chunks"])
    assert texts[0].startswith("Hahaha!")                                        # ilk gülme ilk cümlenin başında
    assert len(texts) == 1 and "Bunu duyunca Hahaha! çok şaşırdım" in texts[0]   # cümle ortasından bölünmedi (v3 gibi satır içi)
    assert rep["nonverbal_used"] == []
    # [1 sn] en başta → yok sayılır (duraklama kaymaz)
    _, _, rep2 = eng.synthesize("[1 sn] Merhaba. İkinci cümle.", "tr", refs, seed=2, master=False, breaths=False)
    assert rep2["prosody"]["pauses_ms"][0] < 1000
    # cps geçmişi ham süreden (hız 0.7 olsa da)
    eng._cps_history.clear()
    eng.synthesize("Bu cümle yirmi karakterden uzun bir deneme cümlesidir.", "tr", refs, seed=2, speed=0.7, master=False, breaths=False)
    chars, secs = eng._cps_history["v1"][-1]
    assert 8 <= chars / secs <= 20            # sahte model ~14 kar/sn; 0.7 hız uygulanmış olsaydı ~10'un altına düşerdi
    # vurgu: kısa parça kararlılık sınırı (ex ≤ 0.8)
    _, _, rep3 = eng.synthesize("[çok heyecanlı] Bu *harika*!", "tr", refs, seed=2, master=False, breaths=False)
    emph = [c for c in rep3["chunks"] if c.get("emphasized")]
    assert emph and emph[0]["exaggeration"] <= 0.8
    # dolgular bölüm başına farklı seed: 6 sıra içinde ya hep ya hiç olmasın (en az bir farklılık)
    text = "\n\n".join(f"Bugün {i} numaralı cümleyi söylüyorum." for i in range(1, 9))
    _, _, rep4 = eng.synthesize(text, "tr", refs, seed=2, master=False, breaths=False, fillers=True, style="sohbet")
    import re as _re

    texts4 = [c["text"] for c in rep4["chunks"]]
    filled = [t_ for t_ in texts4 if _re.search(r"^(?:Yani|Hani|İşte|Şey|Ya|Bak|Valla),|\b(?:yani|işte|ya)[.!]$", t_)]
    assert 0 < len(filled) < len(texts4)          # ne hepsinde ne hiçbirinde: doğal seyreklik


def test_chain_dialog_turn_pauses_not_overridden(ref_path, tmp_path):
    """Diyalogda sıra sonu duraklaması, sonraki sıranın tepkiyle başlaması ya da vurguyla bitmesi durumunda ezilmez."""
    from app.nonverbal import prepare_nonverbal

    sr = SR
    rng = np.random.default_rng(3)
    parts = []
    for _ in range(3):
        n = int(sr * 0.22)
        t = np.linspace(0, 0.22, n, endpoint=False)
        parts.append(((0.25 * np.sin(2 * np.pi * 180 * t) + rng.standard_normal(n) * 0.08) * np.hanning(n)).astype(np.float32))
        parts.append(np.zeros(int(sr * 0.06), dtype=np.float32))
    raw = tmp_path / "raw.wav"
    sf.write(str(raw), np.concatenate(parts), sr)
    laugh = tmp_path / "gulme.wav"
    prepare_nonverbal(raw, laugh, sr)
    eng = ChainEngine()
    a = VoiceRefs("a", ref_path, {}, None, None, {}, "Ayşe Sesi")
    b = VoiceRefs("b", ref_path, {}, None, None, {"gülme": laugh}, "Mehmet Sesi")
    text = "Ayşe: Naber, *nasılsın*?\nMehmet: [gülme] İyiyim.\nMehmet: Sen nasılsın?\nAyşe: Ben de iyiyim."
    wav, sr, rep = eng.synthesize_dialog(text, {"Ayşe": a, "Mehmet": b}, a, "tr", seed=5, master=False, breaths=False)
    pauses = rep["prosody"]["pauses_ms"]
    chunks = rep["chunks"]
    # Ayşe'nin sorusu (vurguyla biten sıra sonu) → Mehmet'in gülmesi: sıra alma duraklaması (120–450), 450 değil sabit
    q_end = max(i for i, c in enumerate(chunks) if c["speaker"] == "Ayşe" and "nasılsın" in c["text"] and i < 3)
    assert 120 <= pauses[q_end] <= 450
    # gülme parçası var ve sonrası 140 ms civarı mikro duraklama
    g = next(i for i, c in enumerate(chunks) if c.get("nonverbal") == "gülme")
    assert pauses[g] <= 200
    # sırada yalnızca duraklama etiketi: "Ayşe: [2 sn]" → kayıp olmaz
    text2 = "Ayşe: Bir.\nMehmet: [2 sn]\nAyşe: İki."
    _, _, rep5 = eng.synthesize_dialog(text2, {"Ayşe": a, "Mehmet": b}, a, "tr", seed=5, master=False, breaths=False)
    assert rep5["prosody"]["pauses_ms"][0] >= 2000
