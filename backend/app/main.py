"""SesKlon HTTP API (FastAPI).

Uç noktalar: sağlık/istatistik, sesler (+ analiz, duygu örnekleri, dışa/içe aktarma), metin → ses (iş kuyruğu,
canlı önizleme, iptal, varyantlar), ses → ses, geçmiş (arama, filtre, favori). Tüm mesajlar Türkçe.
"""
from __future__ import annotations

import io
import json
import logging
import secrets
import shutil
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional, Union

from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import audio, config, db
from .colloquial import LEVELS as COLLOQUIAL_LEVELS, normalize_level
from .emotion import PROFILES, resolve, tag_catalog
from .engine import VoiceRefs, get_engine
from .jobs import Job, JobCancelled, get_queue
from .styles import STYLES, apply_style, resolve_style, style_catalog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sesklon")

VERSION = "3.0.0"
MAX_UPLOAD_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024
PARTIAL_DIR = config.OUTPUT_DIR / "partial"
PARTIAL_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    cleanup_outputs()
    get_queue()
    if config.PRELOAD:
        get_engine().preload_background()
    yield


app = FastAPI(title="SesKlon", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
                   expose_headers=["X-Total-Count", "Content-Disposition"])
db.init_db()


@app.exception_handler(ValueError)
async def _value_error(_req: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc) or "Geçersiz değer"})


# ---------- yardımcılar ----------
_TR_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜâîûÂÎÛ", "cgiosuCGIOSUaiuAIU")


def _fold_tr(s: str) -> str:
    """Türkçe harfleri ASCII'ye katlar (dosya adı / HTTP başlığı için)."""
    return s.translate(_TR_FOLD)


def require_key(x_api_key: Optional[str] = Header(default=None)):
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Geçersiz API anahtarı")


auth = [Depends(require_key)]


def _voice_out(v: dict) -> dict:
    samples = db.list_voice_samples(v["id"])
    return {
        **v,
        "url": f"/files/voices/{v['filename']}",
        "samples": [{**s, "url": f"/files/voices/{s['filename']}"} for s in samples],
    }


def _gen_out(g: dict) -> dict:
    return {**g, "url": f"/files/outputs/{g['filename']}"}


def _save_upload(file: UploadFile, prefix: str = "up") -> Path:
    tmp = config.UPLOAD_TMP_DIR / f"{db.new_id()}_{prefix}_{Path(file.filename or 'ses').name[-60:]}"
    size = 0
    with tmp.open("wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, f"Dosya çok büyük (en fazla {config.MAX_UPLOAD_MB} MB)")
            f.write(chunk)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Boş dosya")
    return tmp


def _analyze_safe(path: Path) -> dict | None:
    """Kayıt analizi; başarısız olursa None (analiz üretimi engellemez)."""
    try:
        from .analysis import analyze_reference

        return analyze_reference(path)
    except Exception as e:  # noqa: BLE001
        log.warning("Kayıt analizi yapılamadı: %s", e)
        return None


def _prepare_reference_upload(file: UploadFile) -> tuple[str, float, dict | None]:
    tmp = _save_upload(file, "ref")
    filename = f"{db.new_id()}.wav"
    dst = config.VOICES_DIR / filename
    try:
        dur = audio.prepare_reference(tmp, dst, config.MAX_REF_SECONDS)
    except Exception as e:  # noqa: BLE001
        log.exception("Ses dönüştürülemedi")
        dst.unlink(missing_ok=True)
        raise HTTPException(400, f"Ses dosyası okunamadı: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)
    if dur < 2.0:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, "Referans ses en az 2 saniye konuşma içermeli (ideali 8–15 sn).")
    return filename, dur, _analyze_safe(dst)


def _voice_refs(voice_id: str | None) -> tuple[VoiceRefs | None, dict | None]:
    if not voice_id:
        return None, None
    voice = db.get_voice(voice_id)
    if not voice:
        raise HTTPException(404, "Ses bulunamadı")
    by_emotion = {s["emotion"]: config.VOICES_DIR / s["filename"] for s in db.list_voice_samples(voice_id)}
    analysis = voice.get("analysis") if isinstance(voice.get("analysis"), dict) else None
    pause_scale = voice.get("pause_scale")       # elle girilmişse analizdeki ölçülen değeri ezer
    return VoiceRefs(voice_id, config.VOICES_DIR / voice["filename"], by_emotion, analysis,
                     float(pause_scale) if pause_scale else None), voice


def cleanup_outputs() -> int:
    """MAX_OUTPUTS üzerindeki en eski çıktıları siler (favoriler hariç; 0 = sınırsız); eski geçici dosyaları temizler."""
    removed = 0
    if config.MAX_OUTPUTS > 0:
        gens = db.list_generations(limit=100000)
        for g in gens[config.MAX_OUTPUTS:]:
            if g.get("favorite"):                 # beğenilenler silinmez
                continue
            (config.OUTPUT_DIR / g["filename"]).unlink(missing_ok=True)
            db.delete_generation(g["id"])
            removed += 1
    now = time.time()
    for p in config.UPLOAD_TMP_DIR.glob("*"):
        if p.is_file() and now - p.stat().st_mtime > 3600:
            p.unlink(missing_ok=True)
    for p in PARTIAL_DIR.glob("*"):
        if p.is_file() and now - p.stat().st_mtime > 1800:
            p.unlink(missing_ok=True)
    return removed


# ---------- şemalar ----------
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=config.MAX_TEXT_CHARS)
    voice_id: Optional[str] = None
    language: str = "tr"
    style: Optional[str] = None                      # stil ön ayarı (styles.STYLES); verilen alanlar üstüne yazar
    exaggeration: Optional[float] = Field(None, ge=0.0, le=1.5)
    cfg_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    temperature: Optional[float] = Field(None, ge=0.05, le=2.0)
    seed: Optional[int] = Field(None, ge=0, le=2**32 - 1)
    speed: Optional[float] = Field(None, ge=0.7, le=1.3)
    colloquial: Optional[Union[bool, str]] = None   # off | light | full (bool: True=light)
    punctuation_emotion: Optional[bool] = None
    auto_emotion: Optional[bool] = None
    emotion_refs: bool = False                       # (yalnızca emotion_fx=full) kayıt yoksa nötr kayıttan türet
    emotion_fx: str = Field("off", pattern="^(off|light|full)$")
    emotion: Optional[str] = None                    # tüm metin için varsayılan duygu
    breaths: Optional[bool] = None                   # cümleler arası doğal nefes
    room_tone: Optional[bool] = None                 # sessizlik yerine kayıttan oda tonu
    master: Optional[bool] = None                    # -16 LUFS mastering
    pause_scale: Optional[float] = Field(None, ge=0.5, le=2.0)
    variants: int = Field(1, ge=1, le=4)             # farklı tohumlarla N varyant
    format: str = Field("wav", pattern="^(wav|mp3)$")
    wait: bool = False

    @field_validator("colloquial")
    @classmethod
    def _colloquial_ok(cls, v):
        if v is None or isinstance(v, bool):
            return v
        lv = str(v).strip().lower()
        if lv not in COLLOQUIAL_LEVELS:
            raise ValueError(f"colloquial değeri off, light ya da full olmalı (gelen: {v!r})")
        return lv

    @field_validator("style")
    @classmethod
    def _style_ok(cls, v):
        if v in (None, ""):
            return None
        if resolve_style(v) is None:
            raise ValueError(f"Bilinmeyen stil: {v!r}. Seçenekler: {', '.join(STYLES)}")
        return resolve_style(v).name


class VoiceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    notes: Optional[str] = Field(None, max_length=2000)
    default_style: Optional[str] = Field(None, max_length=40)
    pause_scale: Optional[float] = Field(None, ge=0.5, le=2.0)
    language: Optional[str] = None


class FavoriteBody(BaseModel):
    favorite: bool = True


DEFAULTS = {"exaggeration": 0.5, "cfg_weight": 0.45, "temperature": 0.8, "speed": 1.0, "pause_scale": 1.0,
            "colloquial": "light", "breaths": True, "punctuation_emotion": True, "auto_emotion": False, "emotion": None}


def _effective_settings(req: TTSRequest) -> dict:
    """Stil ön ayarı + kullanıcının verdiği alanlar → uygulanacak ayarlar.

    Verilmeyen alan stilden gelir; `emotion` için AÇIKÇA gönderilen null ("Etiketlere göre") stilin duygusunu kapatır.
    """
    overrides = {k: getattr(req, k) for k in ("exaggeration", "cfg_weight", "temperature", "speed", "pause_scale",
                                               "colloquial", "breaths", "punctuation_emotion", "auto_emotion", "emotion")
                 if getattr(req, k) is not None}
    emotion_off = "emotion" in req.model_fields_set and req.emotion in (None, "")
    if req.style:
        settings = apply_style(req.style, overrides)
    else:
        settings = {**DEFAULTS, **overrides}
    if emotion_off:
        settings["emotion"] = None
    settings["colloquial"] = normalize_level(settings.get("colloquial"))
    settings["room_tone"] = True if req.room_tone is None else bool(req.room_tone)
    settings["master"] = True if req.master is None else bool(req.master)
    return settings


# ---------- sistem ----------
@app.get("/api/health")
def health():
    eng = get_engine()
    return {
        "ok": True,
        "version": VERSION,
        "device": eng.device,
        "model": eng.model_name,
        "model_loaded": eng.loaded,
        "model_loading": eng.loading,
        "model_error": eng.load_error,
        "queue_pending": get_queue().pending(),
        "languages": config.SUPPORTED_LANGUAGES,
        "auth_required": bool(config.API_KEY),
        "max_text_chars": config.MAX_TEXT_CHARS,
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "tags": tag_catalog(),
        "emotion_tags": list(PROFILES.keys()),
        "styles": style_catalog(),
        "colloquial_levels": list(COLLOQUIAL_LEVELS),
        "features": {"breaths": True, "room_tone": True, "master": audio.has_ffmpeg(), "analysis": True,
                     "variants": True, "partial_preview": True, "cancel": True},
        "ffmpeg": audio.has_ffmpeg(),
    }


@app.get("/api/stats", dependencies=auth)
def stats():
    return db.stats()


@app.post("/api/warmup", dependencies=auth)
def warmup():
    eng = get_engine()
    if not eng.loaded and not eng.loading:
        eng.preload_background()
    return {"ok": True, "model_loaded": eng.loaded, "model_loading": eng.loading}


# ---------- analiz ----------
@app.post("/api/analyze", dependencies=auth)
def analyze_upload(file: UploadFile = File(...)):
    """Kaydı kaydetmeden analiz eder (kalite puanı, öneriler, doğal ritim)."""
    tmp = _save_upload(file, "an")
    wav_tmp = config.UPLOAD_TMP_DIR / f"{db.new_id()}_an.wav"
    try:
        try:
            audio.to_wav(tmp, wav_tmp, audio.TARGET_SR, 180)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Ses dosyası okunamadı: {e}") from e
        from .analysis import analyze_reference

        try:
            return analyze_reference(wav_tmp)
        except Exception as e:  # noqa: BLE001
            log.exception("Analiz başarısız")
            raise HTTPException(500, f"Analiz yapılamadı: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)
        wav_tmp.unlink(missing_ok=True)


# ---------- sesler ----------
@app.get("/api/voices", dependencies=auth)
def voices():
    return [_voice_out(v) for v in db.list_voices()]


@app.post("/api/voices", dependencies=auth)
def create_voice(
    name: str = Form(...),
    language: str = Form("tr"),
    consent: bool = Form(False),
    file: UploadFile = File(...),
):
    if not consent:
        raise HTTPException(400, "Bu sesi kullanma izniniz olduğunu onaylamalısınız.")
    if language not in config.SUPPORTED_LANGUAGES:
        raise HTTPException(400, "Desteklenmeyen dil")
    name = name.strip()[:80] or "Adsız ses"
    filename, dur, analysis = _prepare_reference_upload(file)
    return _voice_out(db.add_voice(name, filename, dur, language, analysis=analysis))


@app.get("/api/voices/{vid}", dependencies=auth)
def get_voice(vid: str):
    v = db.get_voice(vid)
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
    return _voice_out(v)


@app.get("/api/voices/{vid}/analysis", dependencies=auth)
def voice_analysis(vid: str, refresh: bool = False):
    v = db.get_voice(vid)
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
    if v.get("analysis") and not refresh:
        return v["analysis"]
    analysis = _analyze_safe(config.VOICES_DIR / v["filename"])
    if analysis is None:
        raise HTTPException(500, "Analiz yapılamadı")
    old_scale = v.get("pause_scale")
    old_measured = (v.get("analysis") or {}).get("pauses", {}).get("scale") if isinstance(v.get("analysis"), dict) else None
    db.set_voice_analysis(vid, analysis)
    # Kullanıcı ritmi elle değiştirmişse (kayıtlı değer ölçülenden farklı) yeniden analiz onu ezmesin
    if old_scale and old_measured and abs(float(old_scale) - float(old_measured)) > 1e-6:
        db.update_voice(vid, pause_scale=float(old_scale))
    return analysis


@app.patch("/api/voices/{vid}", dependencies=auth)
def update_voice(vid: str, body: VoiceUpdate):
    if not db.get_voice(vid):
        raise HTTPException(404, "Ses bulunamadı")
    # Açıkça gönderilen null = alanı temizle (ör. varsayılan stili kaldır); gönderilmeyen alanlara dokunulmaz
    fields = body.model_dump(exclude_unset=True)
    if fields.get("name") is None and "name" in fields:
        raise HTTPException(400, "Ad boş olamaz")
    if "language" in fields and (fields["language"] is None or fields["language"] not in config.SUPPORTED_LANGUAGES):
        raise HTTPException(400, "Desteklenmeyen dil")
    if "default_style" in fields:
        st = resolve_style(fields["default_style"]) if fields["default_style"] else None
        if fields["default_style"] and st is None:
            raise HTTPException(400, f"Bilinmeyen stil: {fields['default_style']}")
        fields["default_style"] = st.name if st else None
    if "name" in fields:
        fields["name"] = fields["name"].strip() or None
        if fields["name"] is None:
            raise HTTPException(400, "Ad boş olamaz")
    v = db.update_voice(vid, **fields)
    return _voice_out(v)


@app.delete("/api/voices/{vid}", dependencies=auth)
def delete_voice(vid: str):
    v = db.get_voice(vid)
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
    for s in db.delete_all_voice_samples(vid):
        (config.VOICES_DIR / s["filename"]).unlink(missing_ok=True)
    base = config.VOICES_DIR / v["filename"]
    for d in (config.VOICES_DIR / "derived").glob(f"{base.stem}_*"):
        d.unlink(missing_ok=True)
    base.unlink(missing_ok=True)
    db.delete_voice(vid)
    return {"ok": True}


@app.get("/api/voices/{vid}/export", dependencies=auth)
def export_voice(vid: str):
    """Ses + duygu kayıtları + analizleri tek zip dosyası olarak indirir."""
    bundle = db.export_voice_bundle(vid)
    if not bundle:
        raise HTTPException(404, "Ses bulunamadı")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("sesklon-voice.json", json.dumps(bundle, ensure_ascii=False, indent=2))
        for fn in bundle["files"]:
            p = config.VOICES_DIR / fn
            if p.exists():
                z.write(p, f"audio/{fn}")
    name = bundle["voice"]["name"]
    ascii_name = ("".join(ch if (ch.isascii() and ch.isalnum()) or ch in "-_" else "-" for ch in _fold_tr(name))
                  .strip("-")[:40] or "ses")
    utf8_name = quote(f"sesklon-{name[:40]}-{vid}.zip")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition":
                             f'attachment; filename="sesklon-{ascii_name}-{vid}.zip"; filename*=UTF-8\'\'{utf8_name}'})


@app.post("/api/voices/import", dependencies=auth)
def import_voice(file: UploadFile = File(...)):
    """`/export` ile alınan zip'i geri yükler (yeni kimliklerle)."""
    tmp = _save_upload(file, "imp")
    written: list[Path] = []
    created_vid: str | None = None
    try:
        with zipfile.ZipFile(tmp) as z:
            # Zip bombası koruması: her üye ve toplam, yükleme sınırını aşamaz
            total = 0
            for info in z.infolist():
                if info.file_size > MAX_UPLOAD_BYTES or (total := total + info.file_size) > MAX_UPLOAD_BYTES * 2:
                    raise HTTPException(413, f"Paket çok büyük (üye başına en fazla {config.MAX_UPLOAD_MB} MB)")
            try:
                meta = json.loads(z.read("sesklon-voice.json").decode("utf-8"))
            except KeyError:
                raise HTTPException(400, "Geçersiz paket: sesklon-voice.json yok") from None
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, "Geçersiz paket: sesklon-voice.json okunamadı") from None
            if not isinstance(meta, dict) or meta.get("format") != "sesklon-voice" or not isinstance(meta.get("voice"), dict):
                raise HTTPException(400, "Geçersiz paket biçimi")
            voice = meta["voice"]
            language = voice.get("language") or "tr"
            if language not in config.SUPPORTED_LANGUAGES:
                language = "tr"

            def _extract(fn: Any) -> tuple[str, float]:
                """Zip'ten sesi alır, referans olarak yeniden işler (24 kHz mono, kırpma, seviye)."""
                if not isinstance(fn, str) or not fn:
                    raise HTTPException(400, "Pakette ses dosyası adı eksik")
                raw = config.UPLOAD_TMP_DIR / f"{db.new_id()}_imp.wav"
                try:
                    with z.open(f"audio/{Path(fn).name}") as src, raw.open("wb") as out:
                        shutil.copyfileobj(src, out, 1024 * 1024)
                    new_name = f"{db.new_id()}.wav"
                    dst = config.VOICES_DIR / new_name
                    try:
                        dur = audio.prepare_reference(raw, dst, config.MAX_REF_SECONDS)
                    except Exception as e:  # noqa: BLE001
                        dst.unlink(missing_ok=True)
                        raise HTTPException(400, f"Paketteki ses okunamadı ({fn}): {e}") from e
                    written.append(dst)
                    if dur < 2.0:
                        raise HTTPException(400, f"Paketteki ses çok kısa ({fn})")
                    return new_name, dur
                except KeyError:
                    raise HTTPException(400, f"Pakette ses dosyası eksik: {fn}") from None
                finally:
                    raw.unlink(missing_ok=True)

            fn, dur = _extract(voice.get("filename"))
            analysis = voice.get("analysis") if isinstance(voice.get("analysis"), dict) else _analyze_safe(config.VOICES_DIR / fn)
            v = db.add_voice(str(voice.get("name") or "İçe aktarılan ses")[:80], fn, dur, language, analysis=analysis)
            created_vid = v["id"]
            extra = {k: voice.get(k) for k in ("notes", "default_style", "pause_scale") if voice.get(k) is not None}
            if extra.get("default_style") and resolve_style(extra["default_style"]) is None:
                extra.pop("default_style")
            if extra:
                try:
                    db.update_voice(v["id"], **extra)
                except ValueError:
                    pass
            for s in meta.get("samples") or []:
                if not isinstance(s, dict):
                    continue
                prof = resolve(str(s.get("emotion") or ""))
                if not prof or prof.name == "normal":
                    continue
                sfn, sdur = _extract(s.get("filename"))
                db.set_voice_sample(v["id"], prof.name, sfn, sdur,
                                    analysis=s.get("analysis") if isinstance(s.get("analysis"), dict) else None)
            return _voice_out(db.get_voice(v["id"]))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Dosya bir zip paketi değil") from None
    except HTTPException:
        # Yarım kalan içe aktarmayı geri al: yazılan dosyalar ve ses kaydı silinir
        if created_vid:
            db.delete_all_voice_samples(created_vid)
            db.delete_voice(created_vid)
        for p in written:
            p.unlink(missing_ok=True)
        raise
    finally:
        tmp.unlink(missing_ok=True)


# ---------- duygu örnekleri (ses başına) ----------
@app.post("/api/voices/{vid}/samples", dependencies=auth)
def add_voice_sample(vid: str, emotion: str = Form(...), file: UploadFile = File(...)):
    v = db.get_voice(vid)
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
    prof = resolve(emotion)
    if prof is None or prof.name == "normal":
        raise HTTPException(400, f"Geçersiz duygu. Seçenekler: {', '.join(k for k in PROFILES if k != 'normal')}")
    filename, dur, analysis = _prepare_reference_upload(file)
    rec = db.set_voice_sample(vid, prof.name, filename, dur, analysis=analysis)
    if rec.get("replaced_filename"):
        (config.VOICES_DIR / rec["replaced_filename"]).unlink(missing_ok=True)
    return _voice_out(v)


@app.delete("/api/voices/{vid}/samples/{emotion}", dependencies=auth)
def delete_voice_sample(vid: str, emotion: str):
    v = db.get_voice(vid)
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
    prof = resolve(emotion)
    rec = db.delete_voice_sample(vid, prof.name if prof else emotion)
    if rec:
        (config.VOICES_DIR / rec["filename"]).unlink(missing_ok=True)
    return _voice_out(v)


# ---------- metin → ses ----------
def _write_partial(job: Job, index: int, wav, sr: int, text: str) -> None:
    """Canlı önizleme: üretilen parçayı hemen diske yazar, işin `partial` listesine ekler."""
    name = f"{job.id}_{index:03d}.wav"
    path = PARTIAL_DIR / name
    dur = audio.save_wav(path, wav, sr)
    job.add_partial({"index": index, "url": f"/files/outputs/partial/{name}", "text": text, "duration": round(dur, 2)})


def _run_tts(req: TTSRequest, refs: VoiceRefs | None, voice: dict | None, settings: dict):
    """İş kuyruğunda çalışacak üretim fonksiyonunu hazırlar (varyantlar, canlı önizleme, iptal temizliği)."""
    emo = settings.get("emotion")
    text = req.text
    if emo and resolve(emo):
        text = f"[{resolve(emo).name}] " + text
    n = max(1, req.variants)

    def _synth_one(job: Job, k: int, seed: int, group_id: str | None) -> dict:
        eng = get_engine()
        t0 = time.time()

        def _progress(i, total, msg):
            prefix = f"varyant {k + 1}/{n} • " if n > 1 else ""
            job.set_progress(k * total + i, n * total, prefix + msg)

        wav, sr, report = eng.synthesize(
            text, req.language, refs,
            settings["exaggeration"], settings["cfg_weight"], settings["temperature"], seed, settings["speed"],
            settings["colloquial"], settings["punctuation_emotion"], settings["auto_emotion"], req.emotion_refs,
            progress=_progress, emotion_fx=req.emotion_fx,
            breaths=settings["breaths"], room_tone=settings["room_tone"], master=settings["master"],
            pause_scale=settings["pause_scale"],
            partial=(lambda i, w, s, t: _write_partial(job, i, w, s, t)) if k == 0 else None,
            check_cancelled=job.check_cancelled,
        )
        job.check_cancelled()                      # kayıttan hemen önce son denetim
        elapsed = time.time() - t0
        gid = db.new_id()
        wav_path = config.OUTPUT_DIR / f"{gid}.wav"
        dur = audio.save_wav(wav_path, wav, sr)
        filename = wav_path.name
        if req.format == "mp3" and audio.has_ffmpeg():
            mp3_path = config.OUTPUT_DIR / f"{gid}.mp3"
            audio.wav_to_mp3(wav_path, mp3_path, bitrate="192k")
            wav_path.unlink(missing_ok=True)
            filename = mp3_path.name
        gen = db.add_generation(
            kind="tts", text=req.text, voice_id=voice["id"] if voice else None,
            voice_name=voice["name"] if voice else "Varsayılan ses", language=req.language,
            params={
                **{k2: settings[k2] for k2 in ("exaggeration", "cfg_weight", "temperature", "speed", "colloquial",
                                                "punctuation_emotion", "auto_emotion", "breaths", "room_tone",
                                                "master", "pause_scale")},
                "style": req.style, "seed": seed, "emotion": emo, "emotion_fx": req.emotion_fx,
                "variant": k + 1 if n > 1 else None, "variants": n if n > 1 else None,
                "normalized_text": report["normalized_text"], "chunks": report["chunks"],
                "colloquial_changes": report.get("colloquial_changes", []),
                "prosody": report.get("prosody"), "loudness": report.get("loudness"),
            },
            filename=filename, duration=dur, elapsed=elapsed, seed=seed, group_id=group_id,
        )
        return _gen_out(gen)

    def runner(job: Job):
        group_id = db.new_id() if n > 1 else None
        # Tohum: verilmemişse rastgele seçilir ve kaydedilir → her sonuç "Tohumu sabitle" ile tekrar üretilebilir
        base_seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        results: list[dict] = []
        try:
            for k in range(n):
                job.check_cancelled()
                results.append(_synth_one(job, k, (base_seed + k * 1009) % (2**32), group_id))
        except JobCancelled:
            # İptal: bu grubun yarım kalan varyantları geçmişte kalmasın
            for g in results:
                (config.OUTPUT_DIR / g["filename"]).unlink(missing_ok=True)
                db.delete_generation(g["id"])
            raise
        cleanup_outputs()
        out = dict(results[0])
        if n > 1:
            out["variants"] = results
            out["group_id"] = group_id
        return out

    return runner


def _wait_job(job: Job, what: str):
    while job.status in ("queued", "running"):
        time.sleep(0.25)
    if job.status == "cancelled":
        raise HTTPException(499, f"{what} iptal edildi")
    if job.status == "error":
        raise HTTPException(500, f"{what} başarısız: {job.error}")
    return job.result


@app.post("/api/tts", dependencies=auth)
def tts(req: TTSRequest):
    if req.language not in config.SUPPORTED_LANGUAGES:
        raise HTTPException(400, "Desteklenmeyen dil")
    if req.emotion and not resolve(req.emotion):
        raise HTTPException(400, "Bilinmeyen duygu")
    settings = _effective_settings(req)
    if settings.get("emotion") and not resolve(settings["emotion"]):
        settings["emotion"] = None
    refs, voice = _voice_refs(req.voice_id)
    est_chunks = max(1, len(req.text) // config.CHUNK_CHARS + 1) * req.variants
    job = get_queue().submit("tts", _run_tts(req, refs, voice, settings), total=est_chunks)
    if req.wait:
        return _wait_job(job, "Üretim")
    return JSONResponse(status_code=202, content=job.to_dict())


@app.get("/api/jobs", dependencies=auth)
def jobs_list(limit: int = 50):
    return get_queue().list(min(max(limit, 1), 200))


@app.get("/api/jobs/{job_id}", dependencies=auth)
def job_status(job_id: str):
    job = get_queue().get(job_id)
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
def job_cancel(job_id: str):
    job = get_queue().get(job_id)
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    ok = get_queue().cancel(job_id)
    return {"ok": ok, "status": job.status}


# ---------- ses → ses ----------
@app.post("/api/vc", dependencies=auth)
def voice_conversion(voice_id: str = Form(...), file: UploadFile = File(...), wait: bool = Form(False)):
    voice = db.get_voice(voice_id)
    if not voice:
        raise HTTPException(404, "Hedef ses bulunamadı")
    tmp_in = _save_upload(file, "vc")

    def runner(job: Job):
        src_wav = config.UPLOAD_TMP_DIR / f"{db.new_id()}_src.wav"
        try:
            job.set_progress(0, 2, "kaynak hazırlanıyor")
            audio.to_wav(tmp_in, src_wav, audio.TARGET_SR, None)
            job.check_cancelled()
            job.set_progress(1, 2, "dönüştürülüyor")
            t0 = time.time()
            wav, sr = get_engine().convert_voice(src_wav, config.VOICES_DIR / voice["filename"])
            elapsed = time.time() - t0
        finally:
            tmp_in.unlink(missing_ok=True)
            src_wav.unlink(missing_ok=True)
        gid = db.new_id()
        out = config.OUTPUT_DIR / f"{gid}.wav"
        dur = audio.save_wav(out, wav, sr)
        gen = db.add_generation(kind="vc", text=None, voice_id=voice["id"], voice_name=voice["name"],
                                language=voice["language"], params={}, filename=out.name, duration=dur, elapsed=elapsed)
        return _gen_out(gen)

    job = get_queue().submit("vc", runner, total=2)
    if wait:
        return _wait_job(job, "Dönüştürme")
    return JSONResponse(status_code=202, content=job.to_dict())


# ---------- geçmiş ----------
@app.get("/api/generations", dependencies=auth)
def generations(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), kind: Optional[str] = None,
                voice_id: Optional[str] = None, q: Optional[str] = None, favorite: Optional[bool] = None):
    if kind not in (None, "", "tts", "vc"):
        raise HTTPException(400, "kind yalnızca tts ya da vc olabilir")
    kind = kind or None
    items = [_gen_out(g) for g in db.list_generations(limit=limit, offset=offset, kind=kind, voice_id=voice_id or None,
                                                       q=q or None, favorite=favorite)]
    total = db.count_generations(kind=kind, voice_id=voice_id or None, q=q or None, favorite=favorite)
    return JSONResponse(content=items, headers={"X-Total-Count": str(total)})


@app.post("/api/generations/{gid}/favorite", dependencies=auth)
def favorite_generation(gid: str, body: FavoriteBody):
    g = db.set_generation_favorite(gid, body.favorite)
    if not g:
        raise HTTPException(404, "Kayıt bulunamadı")
    return _gen_out(g)


@app.delete("/api/generations/{gid}", dependencies=auth)
def delete_generation(gid: str):
    g = db.get_generation(gid)
    if not g:
        raise HTTPException(404, "Kayıt bulunamadı")
    (config.OUTPUT_DIR / g["filename"]).unlink(missing_ok=True)
    db.delete_generation(gid)
    return {"ok": True}


# ---------- dosyalar & arayüz ----------
app.mount("/files/voices", StaticFiles(directory=config.VOICES_DIR), name="voices")
app.mount("/files/outputs", StaticFiles(directory=config.OUTPUT_DIR), name="outputs")

if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    _DIST_ROOT = config.FRONTEND_DIST.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "files/")):
            return JSONResponse(status_code=404, content={"detail": "Bulunamadı"})
        # Yol geçişi koruması: dist dışına çıkan ("..", mutlak yol, sembolik bağ) istekler index.html alır
        try:
            target = (_DIST_ROOT / path).resolve()
        except (OSError, ValueError):
            target = _DIST_ROOT
        if path and target.is_file() and target.is_relative_to(_DIST_ROOT):
            return FileResponse(target)
        return FileResponse(_DIST_ROOT / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse({"service": "SesKlon API", "version": VERSION, "docs": "/api/docs"})
