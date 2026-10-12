import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audio, config, db
from .emotion import PROFILES, resolve, tag_catalog
from .engine import VoiceRefs, get_engine
from .jobs import Job, get_queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sesklon")

MAX_UPLOAD_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    cleanup_outputs()
    get_queue()
    if config.PRELOAD:
        get_engine().preload_background()
    yield


app = FastAPI(title="SesKlon", version="2.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False)
db.init_db()


# ---------- yardımcılar ----------
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


def _prepare_reference_upload(file: UploadFile) -> tuple[str, float]:
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
    return filename, dur


def _voice_refs(voice_id: str | None) -> tuple[VoiceRefs | None, dict | None]:
    if not voice_id:
        return None, None
    voice = db.get_voice(voice_id)
    if not voice:
        raise HTTPException(404, "Ses bulunamadı")
    by_emotion = {s["emotion"]: config.VOICES_DIR / s["filename"] for s in db.list_voice_samples(voice_id)}
    return VoiceRefs(voice_id, config.VOICES_DIR / voice["filename"], by_emotion), voice


def cleanup_outputs() -> int:
    """MAX_OUTPUTS üzerindeki en eski çıktıları siler (0 = sınırsız)."""
    if config.MAX_OUTPUTS <= 0:
        return 0
    gens = db.list_generations(limit=100000)
    removed = 0
    for g in gens[config.MAX_OUTPUTS:]:
        (config.OUTPUT_DIR / g["filename"]).unlink(missing_ok=True)
        db.delete_generation(g["id"])
        removed += 1
    for p in config.UPLOAD_TMP_DIR.glob("*"):
        if p.is_file() and time.time() - p.stat().st_mtime > 3600:
            p.unlink(missing_ok=True)
    return removed


# ---------- şemalar ----------
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=config.MAX_TEXT_CHARS)
    voice_id: Optional[str] = None
    language: str = "tr"
    exaggeration: float = Field(0.5, ge=0.0, le=1.5)
    cfg_weight: float = Field(0.45, ge=0.0, le=1.0)
    temperature: float = Field(0.8, ge=0.05, le=2.0)
    seed: Optional[int] = None
    speed: float = Field(1.0, ge=0.7, le=1.3)
    colloquial: bool = True              # konuşma dili (geleceğim → gelicem)
    punctuation_emotion: bool = True     # ! ? ... noktalamasına göre duygu
    auto_emotion: bool = False           # etiket yoksa cümle içeriğinden duygu tahmini
    emotion_refs: bool = False           # (yalnızca emotion_fx=full) duygu için kayıt yoksa nötr kayıttan türet
    emotion_fx: str = Field("off", pattern="^(off|light|full)$")  # çıktı işleme seviyesi: off = en doğal
    emotion: Optional[str] = None        # tüm metin için varsayılan duygu (etiket yazmadan)
    format: str = Field("wav", pattern="^(wav|mp3)$")
    wait: bool = False                   # true: iş bitene kadar bekle ve sonucu döndür


class RenameBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


# ---------- sistem ----------
@app.get("/api/health")
def health():
    eng = get_engine()
    return {
        "ok": True,
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
        "ffmpeg": audio.has_ffmpeg(),
    }


@app.post("/api/warmup", dependencies=auth)
def warmup():
    eng = get_engine()
    if not eng.loaded and not eng.loading:
        eng.preload_background()
    return {"ok": True, "model_loaded": eng.loaded, "model_loading": eng.loading}


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
    filename, dur = _prepare_reference_upload(file)
    return _voice_out(db.add_voice(name, filename, dur, language))


@app.get("/api/voices/{vid}", dependencies=auth)
def get_voice(vid: str):
    v = db.get_voice(vid)
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
    return _voice_out(v)


@app.patch("/api/voices/{vid}", dependencies=auth)
def rename_voice(vid: str, body: RenameBody):
    v = db.rename_voice(vid, body.name.strip())
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
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


# ---------- duygu örnekleri (ses başına) ----------
@app.post("/api/voices/{vid}/samples", dependencies=auth)
def add_voice_sample(vid: str, emotion: str = Form(...), file: UploadFile = File(...)):
    v = db.get_voice(vid)
    if not v:
        raise HTTPException(404, "Ses bulunamadı")
    prof = resolve(emotion)
    if prof is None or prof.name == "normal":
        raise HTTPException(400, f"Geçersiz duygu. Seçenekler: {', '.join(k for k in PROFILES if k != 'normal')}")
    filename, dur = _prepare_reference_upload(file)
    rec = db.set_voice_sample(vid, prof.name, filename, dur)
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
def _run_tts(req: TTSRequest, refs: VoiceRefs | None, voice: dict | None):
    def runner(job: Job):
        eng = get_engine()
        t0 = time.time()
        text = req.text
        if req.emotion and resolve(req.emotion):
            text = f"[{resolve(req.emotion).name}] " + text
        wav, sr, report = eng.synthesize(
            text, req.language, refs, req.exaggeration, req.cfg_weight, req.temperature, req.seed, req.speed,
            req.colloquial, req.punctuation_emotion, req.auto_emotion, req.emotion_refs,
            progress=lambda i, n, msg: job.set_progress(i, n, msg), emotion_fx=req.emotion_fx,
        )
        elapsed = time.time() - t0
        gid = db.new_id()
        wav_path = config.OUTPUT_DIR / f"{gid}.wav"
        dur = audio.save_wav(wav_path, wav, sr)
        filename = wav_path.name
        if req.format == "mp3" and audio.has_ffmpeg():
            mp3_path = config.OUTPUT_DIR / f"{gid}.mp3"
            audio.wav_to_mp3(wav_path, mp3_path)
            wav_path.unlink(missing_ok=True)
            filename = mp3_path.name
        gen = db.add_generation(
            kind="tts", text=req.text, voice_id=voice["id"] if voice else None,
            voice_name=voice["name"] if voice else "Varsayılan ses", language=req.language,
            params={
                "exaggeration": req.exaggeration, "cfg_weight": req.cfg_weight, "temperature": req.temperature,
                "seed": req.seed, "speed": req.speed, "colloquial": req.colloquial,
                "punctuation_emotion": req.punctuation_emotion, "auto_emotion": req.auto_emotion,
                "emotion": req.emotion, "emotion_fx": req.emotion_fx, "normalized_text": report["normalized_text"], "chunks": report["chunks"],
            },
            filename=filename, duration=dur, elapsed=elapsed,
        )
        cleanup_outputs()
        return _gen_out(gen)

    return runner


@app.post("/api/tts", dependencies=auth)
def tts(req: TTSRequest):
    if req.language not in config.SUPPORTED_LANGUAGES:
        raise HTTPException(400, "Desteklenmeyen dil")
    if req.emotion and not resolve(req.emotion):
        raise HTTPException(400, "Bilinmeyen duygu")
    refs, voice = _voice_refs(req.voice_id)
    job = get_queue().submit("tts", _run_tts(req, refs, voice))
    if req.wait:
        while job.status in ("queued", "running"):
            time.sleep(0.25)
        if job.status == "error":
            raise HTTPException(500, f"Üretim başarısız: {job.error}")
        return job.result
    return JSONResponse(status_code=202, content=job.to_dict())


@app.get("/api/jobs/{job_id}", dependencies=auth)
def job_status(job_id: str):
    job = get_queue().get(job_id)
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    return job.to_dict()


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

    job = get_queue().submit("vc", runner)
    if wait:
        while job.status in ("queued", "running"):
            time.sleep(0.25)
        if job.status == "error":
            raise HTTPException(500, f"Dönüştürme başarısız: {job.error}")
        return job.result
    return JSONResponse(status_code=202, content=job.to_dict())


# ---------- geçmiş ----------
@app.get("/api/generations", dependencies=auth)
def generations(limit: int = 100):
    return [_gen_out(g) for g in db.list_generations(min(limit, 500))]


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

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "files/")):
            return JSONResponse(status_code=404, content={"detail": "Bulunamadı"})
        target = config.FRONTEND_DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(config.FRONTEND_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse({"service": "SesKlon API", "docs": "/api/docs"})
