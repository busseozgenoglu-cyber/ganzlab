"""Kıyaslama betiği — her model/ayar değişikliğini aynı Türkçe cümle setiyle, aynı ölçümle sayıya döker.

Neden: gerçek model Türkçede düz (robotik) çıktı veriyor; "daha iyi oldu mu?" sorusunun cevabı kulak değil sayı
olmalı. Bu modül cümle setini (``app/bench_tr.txt``) seçilen arka uçla üretir ve her cümleyi referans
analiziyle aynı "kulakla" (``app.analysis.analyze_array`` — pyin, p5–p95) ölçer. Sözleşme: ``docs/SOZLESME3.md`` §3.

Komut satırı (backend klasöründen)::

    python -m app.bench --backend fake --out sonuc.json
    python -m app.bench --backend chatterbox --ref ses.wav --exaggeration 0.8 --cfg-weight 0.3 --out b.json
    python -m app.bench --backend chatterbox --ref ses.wav --pipeline --out c.json   # tüm motor zinciri
    python -m app.bench --reference-only sakin.wav coskulu.wav                       # yalnızca referans ölçümü
    python -m app.bench --compare a.json b.json                                      # iki sonucun farkı

Modül API'si::

    load_sentences(path) -> [{"id", "category", "text"}]
    run_bench(backend_name, sentences, *, ref=None, settings=None, pipeline=False, repeat=1, device="cpu",
              emotion_tags=False, progress=None, model=None, language="tr", style=None) -> dict
    summarize(sentences) -> dict
    compare(a, b) -> {"summary": [...], "sentences": [...], "winner": "a" | "b" | "berabere"}
    analyze_files(paths) -> list[dict]
    format_table(result) / format_compare(cmp) / format_reference(rows) -> str
    main(argv=None) -> int

Ölçüm notları:

* Ham mod: ``model.generate`` doğrudan çağrılır (imzaya göre süzülmüş parametrelerle), çıktı baş/son sessizlikten
  kırpılır (``audio.trim_silence``, −45 dB, 40 ms pay — motorla aynı), sonra ölçülür. ``gen_s`` yalnızca
  ``generate`` süresidir; ``rtf = gen_s / duration_s`` (1'in altı gerçek zamandan hızlı).
* Boru hattı modu (``--pipeline``): ``Engine.synthesize`` (normalizasyon, prozodi, QC'li yeniden üretim, birleştirme,
  mastering) çağrılır; ``gen_s`` tüm zincirin süresidir. QC değeri motorun kendi parça QC raporlarından en kötüsüdür
  (yeniden üretim sonrası); motor rapor vermezse çıktı ``qc.check_chunk`` ile ölçülür.
* ``dynamic_range_db``: 25 ms kare / 10 ms atlama RMS dB; konuşma kareleri = en yüksek karenin 30 dB altına kadar
  olanlar; p95 − p5.
* ``--repeat N``: her cümle N kez üretilir; sayısal ölçümlerin medyanı alınır, QC için puanı medyan olan deneme
  kullanılır.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from .tr import tr_lower

log = logging.getLogger("sesklon.bench")

VERSION = 1
DEFAULT_SENTENCES = Path(__file__).resolve().parent / "bench_tr.txt"

# Duygu etiketi alan kategoriler (--emotion-tags ile metnin başına "[kategori] " eklenir); diğerleri etiketsiz
EMOTION_CATEGORIES = ("üzgün", "mutlu", "heyecanlı", "kızgın", "fısıltı", "sakin")
NEUTRAL_CATEGORIES = ("nötr", "soru", "ünlem", "uzun", "sayı", "günlük")
ALL_CATEGORIES = NEUTRAL_CATEGORIES[:3] + EMOTION_CATEGORIES + NEUTRAL_CATEGORIES[3:]

DEFAULT_SETTINGS = {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "seed": None}

# Karar eşikleri (tonlama aralığı medyanı, yarım ton). Gemini TTS ≈ 17,6; Chatterbox'ın ilk ölçümü 13,5.
RANGE_GOOD = 17.0
RANGE_OK = 14.0
STD_FLAT = 2.5
RTF_SLOW = 2.0

VERDICT_GOOD = "ifadeli — Gemini TTS düzeyi"
VERDICT_OK = "orta — referans/ayar iyileştirmesi deneyin"
VERDICT_FLAT = "düz (robotik) — ince ayar gerekli"

# Referans kaydı yorumu eşikleri (--reference-only)
REF_GOOD = 16.0
REF_OK = 12.0
REF_NOTE = "Klon genelde referansın aralığının altında kalır; referansta ≥ 16 yarım ton hedefleyin."

DECISION_TR = {"accept": "kabul", "trim": "kırp", "retry_seed": "yeniden", "retry_stable": "kararlı-yeniden"}
QC_PASS = ("accept", "trim")

# compare: oy veren ölçütler (anahtar, yön: +1 büyük iyi / −1 küçük iyi, oy için en az fark)
_VOTES = (("range_semitones_median", +1, 0.5), ("std_semitones_median", +1, 0.2),
          ("qc_fail_count", -1, 0.5), ("rtf_mean", -1, 0.05))
# compare tablosundaki tüm satırlar (anahtar, Türkçe ad, yön: +1 / −1 / 0 = yön yok, tolerans)
_COMPARE_ROWS = (
    ("range_semitones_median", "Tonlama aralığı medyanı (st)", +1, 0.5),
    ("range_semitones_mean", "Tonlama aralığı ort. (st)", +1, 0.5),
    ("std_semitones_median", "Perde sapması medyanı (st)", +1, 0.2),
    ("syllables_per_sec_mean", "Hece/sn ort.", 0, 0.0),
    ("dynamic_range_db_median", "Dinamik aralık medyanı (dB)", +1, 1.0),
    ("pauses_per_sentence", "Duraklama/cümle", 0, 0.0),
    ("qc_score_mean", "QC puanı ort.", +1, 2.0),
    ("qc_fail_count", "QC başarısız", -1, 0.5),
    ("rtf_mean", "RTF ort.", -1, 0.05),
    ("rtf_median", "RTF medyan", -1, 0.05),
)


class BenchError(RuntimeError):
    """Kullanıcıya Türkçe mesajla gösterilen kıyaslama hatası."""


# ---------- küçük yardımcılar ----------

def _round(v: Any, nd: int = 2) -> float | None:
    """JSON'a güvenli yuvarlama (None / NaN / sonsuz → None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, nd) + 0.0


def _num_tr(v: Any, nd: int = 1) -> str:
    """Türkçe ondalık gösterim: 13.54 → '13,5'; None → '—'."""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(f):
        return "—"
    f = round(f, nd) + 0.0          # "−0,00" görünmesin
    if f == 0:
        f = 0.0
    return f"{f:.{nd}f}".replace(".", ",").replace("-", "−")


def _median(vals: Iterable[Any]) -> float | None:
    xs = [float(v) for v in vals if v is not None and math.isfinite(float(v))]
    return float(statistics.median(xs)) if xs else None


def _mean(vals: Iterable[Any]) -> float | None:
    xs = [float(v) for v in vals if v is not None and math.isfinite(float(v))]
    return float(sum(xs) / len(xs)) if xs else None


def _short(text: str, width: int = 40) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= width else t[: width - 1] + "…"


def _cell(s: str, width: int, right: bool = False) -> str:
    s = str(s)
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.rjust(width) if right else s.ljust(width)


def _row(vals, cols) -> str:
    """Tablo satırı (sondaki boşluklar atılır)."""
    return "  ".join(_cell(v, w, r) for v, (_, w, r) in zip(vals, cols)).rstrip()


def _filter_kwargs(fn: Callable, kwargs: dict) -> dict:
    """Motorla aynı süzgeç: yalnızca ``generate`` imzasında tanımlı parametreler geçer."""
    from .engine import _filter_kwargs as engine_filter

    return engine_filter(fn, kwargs)


def emotion_label(category: str) -> str | None:
    """Kategori → duygu etiketi (``"mutlu"``) ya da etiketsiz kategoriler için ``None``."""
    c = tr_lower((category or "").strip())
    return c if c in EMOTION_CATEGORIES else None


def tagged_text(sentence: dict, emotion_tags: bool) -> str:
    """Modele gidecek metin: ``--emotion-tags`` açıksa duygu kategorilerinde ``"[mutlu] "`` öneki."""
    text = sentence["text"]
    label = emotion_label(sentence.get("category", ""))
    if emotion_tags and label:
        return f"[{label}] {text}"
    return text


# ---------- cümle dosyası ----------

def load_sentences(path: str | Path | None = None) -> list[dict]:
    """``kategori|cümle`` satırlarını okur; ``#`` ile başlayan yorumları ve boş satırları atlar.

    Dönüş: ``[{"id": "n01", "category": "nötr", "text": "…"}, …]`` (kimlikler dosyadaki sırayla numaralanır).
    """
    p = Path(path) if path else DEFAULT_SENTENCES
    if not p.exists():
        raise FileNotFoundError(f"Cümle dosyası bulunamadı: {p}")
    out: list[dict] = []
    for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cat, sep, text = line.partition("|")
        cat, text = tr_lower(cat.strip()), text.strip()
        if not sep or not cat or not text:
            raise ValueError(f"{p.name}, satır {lineno}: 'kategori|cümle' biçiminde değil: {line[:60]}")
        out.append({"id": "", "category": cat, "text": text})
    width = max(2, len(str(len(out))))
    for i, s in enumerate(out, start=1):
        s["id"] = f"n{i:0{width}d}"
    return out


# ---------- ölçüm ----------

def dynamic_range_db(wav: np.ndarray, sr: int) -> float:
    """Konuşma karelerinin RMS dB'sinde p95 − p5 (25 ms kare, 10 ms atlama; en yüksek karenin 30 dB altına kadar)."""
    x = np.asarray(wav, dtype=np.float64).reshape(-1)
    win = max(8, int(round(sr * 0.025)))
    hop = max(1, int(round(sr * 0.010)))
    if x.size < win:
        return 0.0
    n = 1 + (x.size - win) // hop
    starts = np.arange(n) * hop
    cs = np.concatenate(([0.0], np.cumsum(x * x)))
    power = np.maximum((cs[starts + win] - cs[starts]) / win, 0.0)
    db = 10.0 * np.log10(power + 1e-12)
    speech = db[db >= float(db.max()) - 30.0]
    if speech.size < 2:
        return 0.0
    p5, p95 = np.percentile(speech, [5, 95])
    return float(p95 - p5)


def _qc_compact(rep: dict | None) -> dict:
    if not rep:
        return {"score": None, "decision": None, "reasons": []}
    reasons = [{"code": r.get("code"), "message": r.get("message", "")}
               for r in (rep.get("reasons") or [])[:2] if isinstance(r, dict)]
    score = rep.get("score")
    return {"score": int(score) if isinstance(score, (int, float)) else None, "decision": rep.get("decision"),
            "reasons": reasons}


def measure(wav: np.ndarray, sr: int, text: str, gen_s: float, *, qc_report: dict | None = None) -> dict:
    """Bir üretimin ölçümleri (ses zaten kırpılmış olmalı). ``qc_report`` yoksa ``qc.check_chunk`` çalışır."""
    from .analysis import analyze_array
    from .qc import check_chunk

    x = np.asarray(wav, dtype=np.float32).reshape(-1)
    duration = x.size / sr if sr > 0 else 0.0
    a = analyze_array(x, sr)
    f0 = a.get("f0") or {}
    if qc_report is None:
        try:
            qc_report = check_chunk(x, sr, text)
        except Exception as e:  # noqa: BLE001 - QC ölçümü kıyaslamayı düşürmesin
            log.warning("QC ölçülemedi: %s", e)
            qc_report = None
    n_chars = len(text.strip())
    return {
        "duration_s": _round(duration, 3),
        "gen_s": _round(gen_s, 3),
        "rtf": _round(gen_s / duration, 3) if duration > 0 else None,
        "f0": {k: f0.get(k, 0.0) for k in ("median_hz", "min_hz", "max_hz", "range_semitones", "std_semitones",
                                           "voiced_ratio")},
        "syllables_per_sec": (a.get("speaking_rate") or {}).get("syllables_per_sec", 0.0),
        "chars_per_sec": _round(n_chars / duration, 2) if duration > 0 else None,
        "pauses": {"count": int((a.get("pauses") or {}).get("count", 0)),
                   "median_ms": int((a.get("pauses") or {}).get("median_ms", 0))},
        "dynamic_range_db": _round(dynamic_range_db(x, sr), 1),
        "qc": _qc_compact(qc_report),
        "speech_ratio": a.get("speech_ratio", 0.0),
    }


def _aggregate(runs: list[dict]) -> dict:
    """Tekrarlı ölçümlerin medyanı; QC için puanı medyan olan deneme."""
    if len(runs) == 1:
        return runs[0]
    out: dict = {}
    for key in ("duration_s", "gen_s", "rtf", "syllables_per_sec", "chars_per_sec", "dynamic_range_db",
                "speech_ratio"):
        out[key] = _round(_median(r.get(key) for r in runs), 3)
    out["f0"] = {k: _round(_median(r["f0"].get(k) for r in runs), 2) for k in runs[0]["f0"]}
    out["pauses"] = {"count": int(round(_median(r["pauses"]["count"] for r in runs) or 0)),
                     "median_ms": int(round(_median(r["pauses"]["median_ms"] for r in runs) or 0))}
    by_score = sorted(runs, key=lambda r: (r["qc"]["score"] if r["qc"]["score"] is not None else -1))
    out["qc"] = by_score[len(by_score) // 2]["qc"]
    out["runs"] = len(runs)
    out["range_semitones_runs"] = [r["f0"].get("range_semitones") for r in runs]
    for k in runs[0]:
        if k not in out:
            out[k] = runs[0][k]
    return out


def _seed_for(base: int | None, index: int, rep: int) -> int | None:
    return None if base is None else int(base) + index + 7919 * rep


# ---------- koşu ----------

def _settings(settings: dict | None, **extra: Any) -> dict:
    s = dict(DEFAULT_SETTINGS)
    for k, v in (settings or {}).items():
        if v is not None or k == "seed":
            s[k] = v
    s.update(extra)
    s["exaggeration"] = float(s["exaggeration"])
    s["cfg_weight"] = float(s["cfg_weight"])
    s["temperature"] = float(s["temperature"])
    if s.get("seed") is not None:
        s["seed"] = int(s["seed"])
    return s


def _model_info(model: Any, backend_name: str) -> dict:
    try:
        info = dict(model.info())
    except Exception:  # noqa: BLE001 - info() tanımlamayan model nesneleri
        info = {"name": getattr(model, "name", backend_name), "sr": int(getattr(model, "sr", 0) or 0)}
    return info


def run_bench(backend_name: str, sentences: list[dict], *, ref: str | Path | None = None,
              settings: dict | None = None, pipeline: bool = False, repeat: int = 1, device: str | None = "cpu",
              emotion_tags: bool = False, progress: Callable[[int, int, str], None] | None = None,
              model: Any = None, language: str = "tr", style: str | None = None) -> dict:
    """Cümle setini üretip ölçer; sonuç şeması ``docs/SOZLESME3.md`` §3. ``model`` verilirse yeniden yüklenmez."""
    from . import backends
    from .audio import trim_silence

    name = backends.normalize_name(backend_name)          # bilinmeyen ad → KeyError (Türkçe)
    repeat = max(1, int(repeat or 1))
    if ref is not None and not Path(ref).exists():
        raise FileNotFoundError(f"Referans dosyası bulunamadı: {ref}")
    sentences = list(sentences)
    if not sentences:
        raise BenchError("Kıyaslanacak cümle yok.")

    t_load = time.perf_counter()
    eng = None
    if pipeline:
        from .engine import Engine

        eng = Engine(backend=name)
        if device:
            eng.device = device
        if model is not None:
            eng._tts = model
            eng.model_name = getattr(model, "model_id", "") or eng.model_name
        model = eng.tts()
    elif model is None:
        model = backends.create(name, device=device or "cpu")
    load_s = time.perf_counter() - t_load

    s = _settings(settings)
    seed = s.get("seed")
    info = _model_info(model, name)
    info["load_s"] = _round(load_s, 2)
    if eng is not None:
        info["engine_model"] = eng.model_name

    results: list[dict] = []
    n = len(sentences)
    for i, sent in enumerate(sentences):
        text_in = tagged_text(sent, emotion_tags)
        label = emotion_label(sent.get("category", ""))
        if progress:
            try:
                progress(i, n, sent["text"])
            except Exception:  # noqa: BLE001 - ilerleme bildirimi kıyaslamayı düşürmesin
                pass
        row = {"id": sent.get("id") or f"n{i + 1:02d}", "category": sent.get("category", ""), "text": sent["text"],
               "input_text": text_in}
        runs: list[dict] = []
        try:
            for r in range(repeat):
                sd = _seed_for(seed, i, r)
                if pipeline:
                    runs.append(_run_pipeline(eng, text_in, sent["text"], language, ref, s, sd, style, trim_silence))
                else:
                    runs.append(_run_raw(model, text_in, sent["text"], language, ref, s, sd, label, trim_silence))
        except Exception as e:  # noqa: BLE001 - tek cümlenin hatası tüm kıyaslamayı düşürmesin
            log.warning("Cümle %s üretilemedi: %s", row["id"], e)
            row["error"] = f"{type(e).__name__}: {e}"
            results.append(row)
            continue
        row.update(_aggregate(runs))
        results.append(row)

    settings_out = {"backend": name, "ref": str(ref) if ref else None, "exaggeration": s["exaggeration"],
                    "cfg_weight": s["cfg_weight"], "temperature": s["temperature"], "seed": seed,
                    "pipeline": bool(pipeline), "repeat": repeat, "emotion_tags": bool(emotion_tags),
                    "language": language, "device": getattr(eng, "device", None) or device, "style": style}
    return {"version": VERSION, "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "backend": info, "settings": settings_out, "sentences": results, "summary": summarize(results)}


def _run_raw(model: Any, text_in: str, text: str, language: str, ref, s: dict, seed: int | None,
             label: str | None, trim_silence) -> dict:
    from .backends import BaseBackend

    if seed is not None and hasattr(model, "seed"):
        model.seed(seed)
    kwargs = _filter_kwargs(model.generate, {
        "language_id": language, "exaggeration": s["exaggeration"], "cfg_weight": s["cfg_weight"],
        "temperature": s["temperature"], "audio_prompt_path": str(ref) if ref else None, "emotion": label})
    t0 = time.perf_counter()
    out = model.generate(text_in, **kwargs)
    gen_s = time.perf_counter() - t0
    sr = int(model.sr)
    wav = trim_silence(BaseBackend.to_numpy(out), sr, threshold_db=-45.0, pad_ms=40)
    return measure(wav, sr, text, gen_s)


def _run_pipeline(eng: Any, text_in: str, text: str, language: str, ref, s: dict, seed: int | None,
                  style: str | None, trim_silence) -> dict:
    from .engine import VoiceRefs

    refs = VoiceRefs(voice_id="bench", base=Path(ref), by_emotion={}) if ref else None
    t0 = time.perf_counter()
    wav, sr, rep = eng.synthesize(text_in, language, refs, s["exaggeration"], s["cfg_weight"], s["temperature"],
                                  seed, 1.0, "light", True, False, False, None, "off", qc=True, subtitles=False,
                                  style=style)
    gen_s = time.perf_counter() - t0
    wav = trim_silence(np.asarray(wav, dtype=np.float32), int(sr), threshold_db=-45.0, pad_ms=40)
    qc_reports = [r for r in (rep.get("qc") or []) if isinstance(r, dict)]
    worst = min(qc_reports, key=lambda r: r.get("score", 0)) if qc_reports else None
    m = measure(wav, int(sr), text, gen_s, qc_report=worst)
    m["pipeline"] = {"chunks": len(rep.get("chunks") or []),
                     "qc_retries": int(sum(int(r.get("retries") or 0) for r in qc_reports)),
                     "normalized_text": rep.get("normalized_text", "")}
    return m


# ---------- özet ----------

def verdict_for(range_median: float | None) -> str:
    if range_median is None:
        return "ölçüm yok"
    if range_median >= RANGE_GOOD:
        return VERDICT_GOOD
    if range_median >= RANGE_OK:
        return VERDICT_OK
    return VERDICT_FLAT


def summarize(sentences: list[dict]) -> dict:
    """Cümle ölçümlerinden özet, Türkçe karar ve öneriler (hatalı cümleler sayılmaz, ``errors`` alanında)."""
    ok = [s for s in sentences if "error" not in s and s.get("f0")]
    n = len(ok)
    ranges = [s["f0"].get("range_semitones") for s in ok]
    qc_scores = [s["qc"].get("score") for s in ok if s.get("qc")]
    fails = sum(1 for s in ok if (s.get("qc") or {}).get("decision") not in QC_PASS)
    by_cat: dict[str, list] = {}
    for s in ok:
        by_cat.setdefault(s.get("category", ""), []).append(s["f0"].get("range_semitones"))
    summary = {
        "n": n,
        "errors": len(sentences) - n,
        "rtf_mean": _round(_mean(s.get("rtf") for s in ok), 3),
        "rtf_median": _round(_median(s.get("rtf") for s in ok), 3),
        "range_semitones_median": _round(_median(ranges), 2),
        "range_semitones_mean": _round(_mean(ranges), 2),
        "std_semitones_median": _round(_median(s["f0"].get("std_semitones") for s in ok), 2),
        "syllables_per_sec_mean": _round(_mean(s.get("syllables_per_sec") for s in ok), 2),
        "dynamic_range_db_median": _round(_median(s.get("dynamic_range_db") for s in ok), 1),
        "qc_score_mean": _round(_mean(qc_scores), 1),
        "qc_fail_count": int(fails),
        "pauses_per_sentence": _round(_mean((s.get("pauses") or {}).get("count", 0) for s in ok), 2),
        "range_by_category": {c: _round(_median(v), 2) for c, v in by_cat.items()},
    }
    summary["verdict"] = verdict_for(summary["range_semitones_median"])
    summary["recommendations"] = _recommendations(summary)
    return summary


def _recommendations(s: dict) -> list[str]:
    n = s["n"]
    if not n:
        return ["Hiçbir cümle ölçülemedi: arka ucun kurulu olduğunu ve referans dosyasının okunabildiğini "
                "denetleyin (hatalar JSON'daki 'error' alanında)."]
    recs: list[str] = []
    rng = s["range_semitones_median"] or 0.0
    if rng < RANGE_OK:
        recs.append(f"Tonlama aralığı medyanı {_num_tr(rng)} yarım ton (< {_num_tr(RANGE_OK, 0)}): düzlük modelin "
                    "Türkçe prozodi önceliğinden geliyor, ayarla çözülmez — ifadeli Türkçe veriyle ince ayar yapın "
                    "(adımlar: finetune/README.md).")
    elif rng < RANGE_GOOD:
        recs.append(f"Tonlama aralığı medyanı {_num_tr(rng)} yarım ton (orta): daha ifadeli bir referans deneyin "
                    "(önce --reference-only ile ölçün; referansta ≥ 16 yarım ton hedefleyin).")
    if (s["rtf_mean"] or 0.0) > RTF_SLOW:
        recs.append(f"Üretim yavaş (RTF ort. {_num_tr(s['rtf_mean'], 2)}; gerçek zamanın "
                    f"{_num_tr(s['rtf_mean'], 1)} katı): Apple Silicon'da chatterbox-mlx arka ucunu deneyin ya da "
                    "QC'li yeniden üretimi kapatın (qc=false).")
    if s["qc_fail_count"] > n / 5:
        recs.append(f"{s['qc_fail_count']}/{n} cümle kalite kontrolünden geçmedi: daha kararlı üretim için "
                    "cfg_weight 0.4+ ve temperature 0.6 deneyin.")
    if (s["std_semitones_median"] or 0.0) < STD_FLAT:
        recs.append(f"Perde sapması medyanı {_num_tr(s['std_semitones_median'], 2)} yarım ton (< "
                    f"{_num_tr(STD_FLAT)}): tonlama tekdüze — cümle içi iniş çıkışlar zayıf; exaggeration'ı "
                    "artırmayı ve ifadeli referans kullanmayı deneyin.")
    if not recs:
        recs.append("Ölçümler hedef aralıkta; değişiklikleri bu sonuçla --compare ile karşılaştırarak ilerleyin.")
    return recs


# ---------- karşılaştırma ----------

def _better(key_dir: int, tol: float, a: float | None, b: float | None) -> str:
    if key_dir == 0 or a is None or b is None:
        return "-"
    d = (b - a) * key_dir
    if abs(b - a) <= tol:
        return "-"
    return "b" if d > 0 else "a"


def compare(a: dict, b: dict) -> dict:
    """İki ``run_bench`` sonucunun farkı: özet satırları (b − a), cümle bazında aralık farkı ve kazanan.

    Kazanan oylarla belirlenir: tonlama aralığı medyanı (büyük iyi), perde sapması medyanı (büyük iyi),
    QC başarısız sayısı (küçük iyi), RTF ort. (küçük iyi). Ölçüm gürültüsü oy vermesin diye küçük farklar
    (aralık 0,5 st, sapma 0,2 st, RTF 0,05) yok sayılır. Oylar eşitse "berabere".
    """
    sa, sb = a.get("summary") or {}, b.get("summary") or {}
    rows = []
    for key, label, direction, tol in _COMPARE_ROWS:
        va, vb = sa.get(key), sb.get(key)
        delta = _round(vb - va, 3) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        rows.append({"metric": key, "label": label, "a": va, "b": vb, "delta": delta,
                     "better": _better(direction, tol, va, vb)})
    votes = {"a": 0, "b": 0}
    for key, direction, tol in _VOTES:
        w = _better(direction, tol, sa.get(key), sb.get(key))
        if w in votes:
            votes[w] += 1
    winner = "a" if votes["a"] > votes["b"] else ("b" if votes["b"] > votes["a"] else "berabere")

    by_id_b = {s.get("id"): s for s in b.get("sentences") or [] if "error" not in s}
    sents = []
    for s in a.get("sentences") or []:
        t = by_id_b.get(s.get("id"))
        if t is None or "error" in s:
            continue
        ra, rb = (s.get("f0") or {}).get("range_semitones"), (t.get("f0") or {}).get("range_semitones")
        sents.append({"id": s.get("id"), "text": s.get("text", ""), "range_a": ra, "range_b": rb,
                      "delta": _round(rb - ra, 2) if ra is not None and rb is not None else None})
    return {"summary": rows, "sentences": sents, "winner": winner, "votes": votes,
            "labels": {"a": _label(a), "b": _label(b)}}


def _label(result: dict) -> str:
    st = result.get("settings") or {}
    name = (result.get("backend") or {}).get("name") or st.get("backend") or "?"
    parts = [str(name)]
    if st.get("exaggeration") is not None:
        parts.append(f"ex {_num_tr(st['exaggeration'], 2)}")
    if st.get("cfg_weight") is not None:
        parts.append(f"cfg {_num_tr(st['cfg_weight'], 2)}")
    if st.get("pipeline"):
        parts.append("boru hattı")
    if st.get("ref"):
        parts.append(f"ref {Path(str(st['ref'])).name}")
    return ", ".join(parts)


# ---------- referans kayıtları ----------

def reference_comment(range_st: float | None) -> str:
    r = range_st or 0.0
    if r >= REF_GOOD:
        head = "ifadeli — klon için iyi"
    elif r >= REF_OK:
        head = "orta"
    else:
        head = "düz — daha coşkulu bir kayıt deneyin"
    return f"{head}. {REF_NOTE}"


def analyze_files(paths: Iterable[str | Path]) -> list[dict]:
    """Referans kayıtlarının ifade ölçümü (model yüklemeden): aralık, sapma, hece/sn, duraklama ve yorum."""
    from .analysis import analyze_reference

    out = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            raise FileNotFoundError(f"Ses dosyası bulunamadı: {path}")
        a = analyze_reference(path)
        f0 = a.get("f0") or {}
        out.append({
            "file": str(path),
            "duration_s": a.get("duration"),
            "f0": {k: f0.get(k, 0.0) for k in ("median_hz", "min_hz", "max_hz", "range_semitones", "std_semitones",
                                               "voiced_ratio")},
            "syllables_per_sec": (a.get("speaking_rate") or {}).get("syllables_per_sec", 0.0),
            "pauses": {"count": int((a.get("pauses") or {}).get("count", 0)),
                       "median_ms": int((a.get("pauses") or {}).get("median_ms", 0))},
            "speech_ratio": a.get("speech_ratio"),
            "quality_score": a.get("quality_score"),
            "comment": reference_comment(f0.get("range_semitones")),
        })
    return out


# ---------- konsol çıktısı ----------

def format_table(result: dict) -> str:
    """Cümle tablosu + özet + öneriler (Türkçe)."""
    cols = (("Kimlik", 6, False), ("Kategori", 9, False), ("Cümle", 40, False), ("Aralık(st)", 10, True),
            ("Std", 5, True), ("Hece/sn", 7, True), ("RTF", 6, True), ("QC", 4, True), ("Karar", 15, False))
    head = _row([c for c, _, _ in cols], cols)
    lines = [head, "─" * len(head)]
    for s in result.get("sentences") or []:
        if "error" in s:
            vals = (s.get("id", ""), s.get("category", ""), _short(s.get("text", "")), "—", "—", "—", "—", "—",
                    "HATA")
        else:
            qc = s.get("qc") or {}
            vals = (s.get("id", ""), s.get("category", ""), _short(s.get("text", "")),
                    _num_tr(s["f0"].get("range_semitones")), _num_tr(s["f0"].get("std_semitones")),
                    _num_tr(s.get("syllables_per_sec")), _num_tr(s.get("rtf"), 2),
                    "—" if qc.get("score") is None else str(qc["score"]),
                    DECISION_TR.get(qc.get("decision"), qc.get("decision") or "—"))
        lines.append(_row(vals, cols))
    lines.append("")
    lines.append(format_summary(result))
    errs = [s for s in result.get("sentences") or [] if "error" in s]
    if errs:
        lines.append("")
        lines.append("Hatalar:")
        lines.extend(f"  {s.get('id')}: {s['error']}" for s in errs[:10])
    return "\n".join(lines)


def format_summary(result: dict) -> str:
    sm = result.get("summary") or {}
    st = result.get("settings") or {}
    name = (result.get("backend") or {}).get("name") or st.get("backend") or "?"
    mode = "boru hattı (Engine.synthesize)" if st.get("pipeline") else "ham model"
    rows = [
        ("Tonlama aralığı (medyan / ort.)", f"{_num_tr(sm.get('range_semitones_median'))} / "
                                            f"{_num_tr(sm.get('range_semitones_mean'))} yarım ton"),
        ("Perde sapması (medyan)", f"{_num_tr(sm.get('std_semitones_median'), 2)} yarım ton"),
        ("Hece/sn (ort.)", _num_tr(sm.get("syllables_per_sec_mean"), 2)),
        ("Dinamik aralık (medyan)", f"{_num_tr(sm.get('dynamic_range_db_median'))} dB"),
        ("RTF (ort. / medyan)", f"{_num_tr(sm.get('rtf_mean'), 2)} / {_num_tr(sm.get('rtf_median'), 2)}"),
        ("QC puanı (ort.) / başarısız", f"{_num_tr(sm.get('qc_score_mean'))} / {sm.get('qc_fail_count', 0)}"),
        ("Duraklama / cümle", _num_tr(sm.get("pauses_per_sentence"), 2)),
    ]
    out = [f"Özet — {sm.get('n', 0)} cümle • arka uç: {name} • {mode} • exaggeration "
           f"{_num_tr(st.get('exaggeration'), 2)} • cfg {_num_tr(st.get('cfg_weight'), 2)} • sıcaklık "
           f"{_num_tr(st.get('temperature'), 2)}" + (f" • ref: {Path(str(st['ref'])).name}" if st.get("ref") else "")]
    width = max(len(k) for k, _ in rows)
    out.extend(f"  {k.ljust(width)} : {v}" for k, v in rows)
    cats = sm.get("range_by_category") or {}
    if cats:
        out.append("  Kategori aralıkları (st)".ljust(width + 2) + " : "
                   + ", ".join(f"{c} {_num_tr(v)}" for c, v in cats.items()))
    out.append(f"  Karar: {sm.get('verdict', '—')}")
    recs = sm.get("recommendations") or []
    if recs:
        out.append("Öneriler:")
        out.extend(f"  • {r}" for r in recs)
    return "\n".join(out)


def format_compare(cmp: dict) -> str:
    labels = cmp.get("labels") or {}
    lines = [f"A: {labels.get('a', 'a')}", f"B: {labels.get('b', 'b')}", ""]
    cols = (("Ölçüt", 30, False), ("A", 8, True), ("B", 8, True), ("Fark (B−A)", 10, True), ("İyi", 4, False))
    head = _row([c for c, _, _ in cols], cols)
    lines += [head, "─" * len(head)]
    for row in cmp.get("summary") or []:
        nd = 0 if row["metric"] == "qc_fail_count" else 2
        better = {"a": "A", "b": "B"}.get(row["better"], "-")
        vals = (row.get("label", row["metric"]), _num_tr(row["a"], nd), _num_tr(row["b"], nd),
                _num_tr(row["delta"], nd), better)
        lines.append(_row(vals, cols))
    sents = cmp.get("sentences") or []
    if sents:
        lines += ["", "Cümle bazında tonlama aralığı (st):"]
        c2 = (("Kimlik", 6, False), ("Cümle", 40, False), ("A", 6, True), ("B", 6, True), ("Fark", 6, True))
        h2 = _row([c for c, _, _ in c2], c2)
        lines += [h2, "─" * len(h2)]
        for s in sents:
            vals = (s["id"], _short(s["text"]), _num_tr(s["range_a"]), _num_tr(s["range_b"]), _num_tr(s["delta"]))
            lines.append(_row(vals, c2))
    votes = cmp.get("votes") or {}
    w = cmp.get("winner")
    text = {"a": "A", "b": "B"}.get(w, "berabere")
    lines += ["", f"Kazanan: {text} (oylar — A: {votes.get('a', 0)}, B: {votes.get('b', 0)}; ölçütler: aralık "
                  "medyanı, perde sapması, QC başarısız, RTF)"]
    return "\n".join(lines)


def format_reference(rows: list[dict]) -> str:
    cols = (("Dosya", 28, False), ("Süre", 6, True), ("Aralık(st)", 10, True), ("Std", 5, True),
            ("Hece/sn", 7, True), ("Duraklama", 9, True))
    head = _row([c for c, _, _ in cols], cols)
    lines = [head, "─" * len(head)]
    for r in rows:
        vals = (Path(r["file"]).name, _num_tr(r.get("duration_s")), _num_tr(r["f0"].get("range_semitones")),
                _num_tr(r["f0"].get("std_semitones")), _num_tr(r.get("syllables_per_sec")),
                f"{r['pauses']['count']}×{r['pauses']['median_ms']} ms")
        lines.append(_row(vals, cols))
    lines.append("")
    for r in rows:
        lines.append(f"• {Path(r['file']).name}: {r['comment']}")
    return "\n".join(lines)


# ---------- komut satırı ----------

def _auto_device() -> str:
    from . import config

    if config.DEVICE:
        return config.DEVICE
    try:
        from .engine import pick_device

        return pick_device()
    except Exception:  # noqa: BLE001 - torch yoksa (MLX / sahte arka uç) CPU
        return "cpu"


def _write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_result(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Sonuç dosyası bulunamadı: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BenchError(f"{p.name} geçerli bir JSON değil: {e}") from e
    if not isinstance(data, dict) or "summary" not in data:
        raise BenchError(f"{p.name} bir kıyaslama sonucu değil ('summary' alanı yok).")
    return data


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m app.bench",
        description="SesKlon kıyaslama betiği: Türkçe cümle setini seçilen arka uçla üretir ve tonlama aralığı, "
                    "hız, QC gibi ölçümleri raporlar.")
    ap.add_argument("--backend", default=None,
                    help="arka uç: chatterbox | chatterbox-mlx | f5-tr | xtts | fake (varsayılan: TTS_BACKEND)")
    ap.add_argument("--ref", default=None, help="klon referans kaydı (WAV)")
    ap.add_argument("--sentences", default=None, help=f"cümle dosyası (varsayılan: {DEFAULT_SENTENCES.name})")
    ap.add_argument("--limit", type=int, default=None, help="yalnızca ilk N cümle")
    ap.add_argument("--repeat", type=int, default=1, help="her cümleyi N kez üret, medyanı al")
    ap.add_argument("--language", default="tr", help="dil kodu (varsayılan: tr)")
    ap.add_argument("--exaggeration", type=float, default=DEFAULT_SETTINGS["exaggeration"])
    ap.add_argument("--cfg-weight", type=float, default=DEFAULT_SETTINGS["cfg_weight"])
    ap.add_argument("--temperature", type=float, default=DEFAULT_SETTINGS["temperature"])
    ap.add_argument("--seed", type=int, default=None, help="tohum (cümle başına tohum + sıra)")
    ap.add_argument("--emotion-tags", action="store_true",
                    help="duygu kategorilerinde metnin başına '[duygu] ' etiketi ekle (ince ayarlı model için)")
    ap.add_argument("--pipeline", action="store_true", help="tüm motor zinciriyle (Engine.synthesize) üret")
    ap.add_argument("--style", default=None, help="--pipeline ile stil ön ayarı")
    ap.add_argument("--device", default=None, help="cihaz: cuda | mps | cpu (varsayılan: otomatik)")
    ap.add_argument("--out", default=None, help="sonucu JSON olarak bu dosyaya yaz")
    ap.add_argument("--quiet", action="store_true", help="konsola tablo/ilerleme yazma")
    ap.add_argument("--reference-only", nargs="+", metavar="WAV", default=None,
                    help="model yüklemeden referans kayıtlarının ifade ölçümü")
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"), default=None,
                    help="iki kıyaslama sonucunu karşılaştır")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    say = (lambda *_a, **_k: None) if args.quiet else print
    try:
        if args.compare:
            a, b = (_read_result(p) for p in args.compare)
            cmp = compare(a, b)
            say(format_compare(cmp))
            if args.out:
                _write_json(args.out, {"version": VERSION, "files": list(args.compare), **cmp})
                say(f"\nKarşılaştırma yazıldı: {args.out}")
            return 0

        if args.reference_only:
            rows = analyze_files(args.reference_only)
            say(format_reference(rows))
            if args.out:
                _write_json(args.out, {"version": VERSION, "created": datetime.now(timezone.utc).astimezone()
                                       .isoformat(timespec="seconds"), "files": rows})
                say(f"\nSonuç yazıldı: {args.out}")
            return 0

        from . import backends

        try:
            name = backends.normalize_name(args.backend if args.backend is not None
                                           else os.getenv("TTS_BACKEND", backends.DEFAULT_BACKEND))
        except KeyError as e:          # bilinmeyen arka uç (mesaj Türkçe, kayıt defterinden)
            raise BenchError(e.args[0] if e.args else str(e)) from e
        if args.repeat < 1:
            raise BenchError("--repeat en az 1 olmalı.")
        if args.limit is not None and args.limit < 1:
            raise BenchError("--limit en az 1 olmalı.")
        if args.ref and not Path(args.ref).exists():
            raise FileNotFoundError(f"Referans dosyası bulunamadı: {args.ref}")
        sentences = load_sentences(args.sentences)
        if args.limit:
            sentences = sentences[: args.limit]

        def progress(i: int, n: int, text: str) -> None:
            print(f"[{i + 1}/{n}] {_short(text, 60)}", file=sys.stderr, flush=True)

        device = args.device or _auto_device()
        if not args.quiet:
            print(f"Kıyaslama: {name} • {len(sentences)} cümle • cihaz {device}"
                  + (" • boru hattı" if args.pipeline else ""), file=sys.stderr, flush=True)
        result = run_bench(name, sentences, ref=args.ref, settings={
            "exaggeration": args.exaggeration, "cfg_weight": args.cfg_weight, "temperature": args.temperature,
            "seed": args.seed}, pipeline=args.pipeline, repeat=args.repeat, device=device,
            emotion_tags=args.emotion_tags, progress=None if args.quiet else progress, language=args.language,
            style=args.style)
        if args.sentences:
            result["settings"]["sentences_file"] = str(args.sentences)
        say(format_table(result))
        if args.out:
            _write_json(args.out, result)
            say(f"\nSonuç yazıldı: {args.out}")
        return 0
    except (FileNotFoundError, ValueError, BenchError, RuntimeError, OSError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
