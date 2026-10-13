"""Uçtan uca API testleri — sahte motorla (Chatterbox yüklenmez)."""
import io
import json
import time
import zipfile

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import main
from app.engine import Engine, split_text


class FakeEngine(Engine):
    def __init__(self):
        self.device, self.model_name, self._tts = "cpu", "fake", None
        self.loading, self.load_error = False, None
        self._ref_cache, self._ltas_cache, self._cps_history, self._default_conds = {}, {}, {}, None

    @property
    def loaded(self):
        return True

    def preload(self):
        pass

    def preload_background(self):
        pass

    def synthesize(self, text, lang, refs, ex, cfg, temp, seed, speed, colloquial, pe, auto, er, progress=None,
                   emotion_fx="off", *, breaths=True, room_tone=True, master=True, pause_scale=1.0,
                   consistency=True, qc=True, fillers=False, chat_speak=True, subtitles=True, style=None,
                   partial=None, check_cancelled=None):
        chunks = split_text(text, 170, None, auto)
        sr = 24000
        t = np.linspace(0, 1, sr)
        tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
        for i, c in enumerate(chunks):
            if check_cancelled:
                check_cancelled()
            if progress:
                progress(i, len(chunks), c.text)
            if partial:
                partial(i, tone[: sr // 4], sr, c.text)
            time.sleep(0.01)
        rep = {"normalized_text": " ".join(c.text for c in chunks),
               "chunks": [{"text": c.text, "emotion": c.emotion,
                           "ref": self.reference_for(refs, c.emotion, derive=(emotion_fx == "full"))[1]} for c in chunks],
               "colloquial_level": colloquial, "colloquial_changes": [], "prosody": {"breaths": 0},
               "settings_seen": {"breaths": breaths, "room_tone": room_tone, "master": master, "pause_scale": pause_scale,
                                 "ex": ex, "speed": speed, "colloquial": colloquial, "seed": seed}}
        if subtitles:
            rep["timeline"] = [{"index": i, "start": i * 1.0, "end": i * 1.0 + 0.9, "text": c.text, "emotion": c.emotion,
                                "speaker": None, "words": []} for i, c in enumerate(chunks)]
        return tone, sr, rep

    def synthesize_dialog(self, text, speakers, narrator=None, lang="tr", *, default_emotions=None, progress=None,
                          partial=None, check_cancelled=None, **opts):
        from app.dialog import parse_dialog
        turns = [t for t in parse_dialog(text) if t.text.strip()]
        sr = 24000
        t = np.linspace(0, 1, sr)
        tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
        names = {}
        chunks = []
        for i, tn in enumerate(turns):
            if check_cancelled:
                check_cancelled()
            if progress:
                progress(i, len(turns), tn.text)
            r = narrator if tn.speaker is None else speakers.get(tn.speaker, narrator)
            names[tn.speaker or "Anlatıcı"] = r.name if r and r.name else "Varsayılan ses"
            chunks.append({"text": tn.text, "emotion": None, "ref": "kayıt" if r else "model", "speaker": tn.speaker,
                           "duration": 1.0, "pause_ms": 260})
        rep = {"normalized_text": " ".join(c["text"] for c in chunks), "chunks": chunks, "colloquial_changes": [],
               "prosody": {"breaths": 0}, "nonverbal_used": [], "dialog": True,
               "turns": [{"index": tn.index, "speaker": tn.speaker, "voice_name": names[tn.speaker or "Anlatıcı"],
                          "text": tn.text, "start": i * 1.3, "end": i * 1.3 + 1.0} for i, tn in enumerate(turns)],
               "speakers": [{"speaker": k, "voice_name": v} for k, v in names.items()],
               "timeline": [{"index": i, "start": i * 1.3, "end": i * 1.3 + 1.0, "text": tn.text, "emotion": None,
                             "speaker": tn.speaker, "words": []} for i, tn in enumerate(turns)]}
        return np.concatenate([tone] * max(1, len(turns))), sr, rep

    def convert_voice(self, s, t):
        return np.zeros(24000, dtype="float32"), 24000


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "get_engine", lambda: FakeEngine())
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def ref_file(tmp_path):
    sr = 24000
    t = np.linspace(0, 8, sr * 8)
    sf.write(str(tmp_path / "ref.wav"), (0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32"), sr)
    return tmp_path / "ref.wav"


def _wait(client, job):
    while job["status"] in ("queued", "running"):
        time.sleep(0.05)
        job = client.get(f"/api/jobs/{job['id']}").json()
    return job


def _add_voice(client, ref_file, name="Test"):
    r = client.post("/api/voices", data={"name": name, "language": "tr", "consent": "true"},
                    files={"file": ("ref.wav", ref_file.read_bytes(), "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_catalog(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["version"].startswith("4.")
    assert "sohbet" in [s["name"] for s in h["styles"]]
    assert h["colloquial_levels"] == ["off", "light", "full"]
    assert h["features"]["breaths"] and h["features"]["analysis"]
    assert "nonverbal_detail" in h["tags"] and "pause_detail" in h["tags"]


def test_full_flow(client, ref_file):
    v = _add_voice(client, ref_file)
    vid = v["id"]
    assert v["analysis"] is None or isinstance(v["analysis"], dict)
    r = client.post(f"/api/voices/{vid}/samples", data={"emotion": "üzgün"},
                    files={"file": ("sad.wav", ref_file.read_bytes(), "audio/wav")})
    assert [s["emotion"] for s in r.json()["samples"]] == ["üzgün"]
    assert client.post(f"/api/voices/{vid}/samples", data={"emotion": "yok"},
                       files={"file": ("x.wav", ref_file.read_bytes(), "audio/wav")}).status_code == 400

    r = client.post("/api/tts", json={"text": "[heyecanlı] Selam! [üzgün] Bitti. [normal] Son.", "voice_id": vid})
    assert r.status_code == 202
    job = _wait(client, r.json())
    assert job["status"] == "done", job
    refs = [c["ref"] for c in job["result"]["params"]["chunks"]]
    assert refs == ["nötr", "kayıt", "nötr"]          # off modunda türetme yok; üzgün için gerçek kayıt var
    assert job["partial"] and job["partial"][0]["url"].startswith("/files/outputs/partial/")
    assert client.get(job["partial"][0]["url"]).status_code == 200

    r = client.post("/api/tts", json={"text": "[heyecanlı] Selam!", "voice_id": vid, "wait": True, "emotion_fx": "full"})
    assert r.json()["params"]["chunks"][0]["ref"] == "türetilmiş"

    r = client.post("/api/tts", json={"text": "Merhaba", "voice_id": vid, "wait": True, "format": "mp3"})
    assert r.status_code == 200 and r.json()["url"].endswith(".mp3")
    assert client.get(r.json()["url"]).status_code == 200

    r = client.post("/api/vc", data={"voice_id": vid, "wait": "true"}, files={"file": ("s.wav", ref_file.read_bytes(), "audio/wav")})
    assert r.status_code == 200 and r.json()["kind"] == "vc"
    r = client.get("/api/generations")
    assert len(r.json()) == 4 and r.headers["x-total-count"] == "4"
    assert client.delete(f"/api/voices/{vid}").json()["ok"]
    assert client.get("/api/nope").status_code == 404


def test_style_and_naturalness_settings(client, ref_file):
    vid = _add_voice(client, ref_file)["id"]
    # stil ön ayarı: reklam → heyecanlı duygu + yüksek vurgu; kullanıcı hızı üstüne yazıyor
    r = client.post("/api/tts", json={"text": "Büyük indirim başladı.", "voice_id": vid, "wait": True,
                                      "style": "reklam", "speed": 0.9, "colloquial": "full", "breaths": False})
    assert r.status_code == 200, r.text
    p = r.json()["params"]
    assert p["style"] == "reklam" and p["emotion"] == "heyecanlı"
    assert p["speed"] == 0.9 and p["colloquial"] == "full" and p["breaths"] is False
    assert p["exaggeration"] >= 0.75
    # bool colloquial geriye uyumlu
    r = client.post("/api/tts", json={"text": "Merhaba.", "voice_id": vid, "wait": True, "colloquial": False})
    assert r.json()["params"]["colloquial"] == "off"
    r = client.post("/api/tts", json={"text": "Merhaba.", "voice_id": vid, "wait": True, "colloquial": True})
    assert r.json()["params"]["colloquial"] == "light"
    assert client.post("/api/tts", json={"text": "x", "style": "yok-böyle-stil"}).status_code == 422
    assert client.post("/api/tts", json={"text": "x", "colloquial": "çok"}).status_code == 422


def test_variants_and_favorites(client, ref_file):
    vid = _add_voice(client, ref_file)["id"]
    r = client.post("/api/tts", json={"text": "Varyant denemesi.", "voice_id": vid, "wait": True, "variants": 3, "seed": 42})
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["variants"]) == 3 and out["group_id"]
    seeds = [v["seed"] for v in out["variants"]]
    assert len(set(seeds)) == 3 and seeds[0] == 42
    assert all(v["group_id"] == out["group_id"] for v in out["variants"])
    gid = out["variants"][1]["id"]
    assert client.post(f"/api/generations/{gid}/favorite", json={"favorite": True}).json()["favorite"] is True
    favs = client.get("/api/generations?favorite=true").json()
    assert [g["id"] for g in favs] == [gid]
    assert client.get("/api/generations?q=varyant").headers["x-total-count"] == "3"
    assert all(g["kind"] == "vc" for g in client.get("/api/generations?kind=vc").json())
    assert client.get("/api/generations?kind=zzz").status_code == 400
    assert len(client.get("/api/generations?q=varyant&limit=2&offset=2").json()) == 1
    s = client.get("/api/stats").json()
    assert s["generations"] >= 3 and s["favorites"] >= 1


def test_cancel_job(client, ref_file):
    vid = _add_voice(client, ref_file)["id"]
    long_text = " ".join("Bu uzun bir cümle." for _ in range(60))
    r = client.post("/api/tts", json={"text": long_text, "voice_id": vid})
    job = r.json()
    assert job["status"] in ("queued", "running")
    rc = client.post(f"/api/jobs/{job['id']}/cancel").json()
    assert rc["ok"]
    job = _wait(client, job)
    assert job["status"] == "cancelled" and job["cancelled"]
    assert client.get("/api/jobs").json()[0]["id"] == job["id"]
    assert client.post("/api/jobs/yok/cancel").status_code == 404


def test_voice_update_analysis_export_import(client, ref_file):
    v = _add_voice(client, ref_file, "Buse")
    vid = v["id"]
    r = client.patch(f"/api/voices/{vid}", json={"name": "Buse 2", "notes": "stüdyo", "default_style": "podcast", "pause_scale": 1.2})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Buse 2" and r.json()["default_style"] == "podcast" and r.json()["pause_scale"] == 1.2
    assert client.patch(f"/api/voices/{vid}", json={"default_style": "yok"}).status_code == 400
    a = client.get(f"/api/voices/{vid}/analysis")
    assert a.status_code == 200 and "quality_score" in a.json()
    a2 = client.post("/api/analyze", files={"file": ("x.wav", ref_file.read_bytes(), "audio/wav")})
    assert a2.status_code == 200 and "grade" in a2.json()
    client.post(f"/api/voices/{vid}/samples", data={"emotion": "kızgın"},
                files={"file": ("k.wav", ref_file.read_bytes(), "audio/wav")})

    r = client.get(f"/api/voices/{vid}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        meta = json.loads(z.read("sesklon-voice.json"))
    assert "sesklon-voice.json" in names and len([n for n in names if n.startswith("audio/")]) == 2
    assert meta["voice"]["name"] == "Buse 2"

    r = client.post("/api/voices/import", files={"file": ("yedek.zip", r.content, "application/zip")})
    assert r.status_code == 200, r.text
    imp = r.json()
    assert imp["id"] != vid and imp["name"] == "Buse 2" and [s["emotion"] for s in imp["samples"]] == ["kızgın"]
    assert imp["default_style"] == "podcast"
    assert client.post("/api/voices/import", files={"file": ("x.zip", b"bozuk", "application/zip")}).status_code == 400


def test_validation(client):
    assert client.post("/api/tts", json={"text": "", "voice_id": None}).status_code == 422
    assert client.post("/api/tts", json={"text": "x", "language": "xx"}).status_code == 400
    assert client.post("/api/tts", json={"text": "x", "emotion": "yok"}).status_code == 400
    assert client.post("/api/tts", json={"text": "x", "variants": 9}).status_code == 422
    assert client.post("/api/voices", data={"name": "a", "consent": "false"},
                       files={"file": ("a.wav", b"notaudio", "audio/wav")}).status_code == 400


# ---------- inceleme bulguları için regresyon testleri ----------

def test_spa_path_traversal_blocked(client, monkeypatch, tmp_path):
    """SPA rotası dist dışına çıkamaz: '..%2F' ile .env gibi dosyalar okunamaz."""
    from app import config as cfg
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>SesKlon</html>", encoding="utf-8")
    (tmp_path / "gizli.txt").write_text("API_KEY=sır", encoding="utf-8")
    monkeypatch.setattr(cfg, "FRONTEND_DIST", dist)
    # SPA rotası modül yüklenirken bağlanır; aynı mantığı doğrudan sınarız
    root = dist.resolve()
    for p in ("..%2Fgizli.txt", "../gizli.txt", "/etc/passwd", "assets/../../gizli.txt"):
        from urllib.parse import unquote
        target = (root / unquote(p)).resolve()
        assert not (target.is_file() and target.is_relative_to(root)), p
    # canlı sunucuda da index döner (dist yoksa JSON kökü): ikisi de gizli dosyayı vermez
    r = client.get("/..%2F..%2F.env.example")
    assert r.status_code in (200, 404) and "API_KEY" not in r.text


def test_export_turkish_name_and_emotion_off(client, ref_file):
    v = _add_voice(client, ref_file, "Ayşe Doğan — İş")
    r = client.get(f"/api/voices/{v['id']}/export")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "filename=" in cd and "filename*=UTF-8''" in cd and "Ayse-Dogan" in cd
    # Reklam stili "heyecanlı" verir; "Etiketlere göre" (emotion: null) seçilince kapanmalı
    r = client.post("/api/tts", json={"text": "Deneme.", "voice_id": v["id"], "wait": True, "style": "reklam", "emotion": None})
    assert r.json()["params"]["emotion"] is None
    r = client.post("/api/tts", json={"text": "Deneme.", "voice_id": v["id"], "wait": True, "style": "reklam"})
    assert r.json()["params"]["emotion"] == "heyecanlı"
    # varsayılan stil null ile kaldırılabilir
    assert client.patch(f"/api/voices/{v['id']}", json={"default_style": "podcast"}).json()["default_style"] == "podcast"
    assert client.patch(f"/api/voices/{v['id']}", json={"default_style": None}).json()["default_style"] is None
    assert client.patch(f"/api/voices/{v['id']}", json={"name": "  "}).status_code == 400


def test_seed_always_recorded_and_bounded(client, ref_file):
    vid = _add_voice(client, ref_file)["id"]
    r = client.post("/api/tts", json={"text": "Tohum.", "voice_id": vid, "wait": True})
    assert isinstance(r.json()["seed"], int) and r.json()["params"]["seed"] == r.json()["seed"]
    assert client.post("/api/tts", json={"text": "x", "seed": 2**40}).status_code == 422
    assert client.post("/api/tts", json={"text": "x", "seed": -1}).status_code == 422


def test_cancel_cleans_partial_variants(client, ref_file):
    vid = _add_voice(client, ref_file)["id"]
    before = int(client.get("/api/generations").headers["x-total-count"])
    long_text = "\n\n".join("Uzun bir cümle daha." for _ in range(12))
    job = client.post("/api/tts", json={"text": long_text, "voice_id": vid, "variants": 4}).json()
    # ilk varyant bitene kadar bekle, sonra iptal et
    for _ in range(200):
        time.sleep(0.05)
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] != "queued" and j.get("step", 0) >= j.get("total", 99) // 4 + 1:
            break
    client.post(f"/api/jobs/{job['id']}/cancel")
    j = _wait(client, job)
    assert j["status"] == "cancelled"
    assert int(client.get("/api/generations").headers["x-total-count"]) == before   # yarım grup silindi


def test_import_rejects_oversized_member(client, ref_file, monkeypatch):
    from app import main as m
    vid = _add_voice(client, ref_file)["id"]
    r = client.get(f"/api/voices/{vid}/export")
    monkeypatch.setattr(m, "MAX_UPLOAD_BYTES", 1024)       # 1 KB sınır → paket üyesi aşar
    r2 = client.post("/api/voices/import", files={"file": ("y.zip", r.content, "application/zip")})
    assert r2.status_code == 413
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("sesklon-voice.json", json.dumps({"format": "sesklon-voice", "voice": {"name": "x", "filename": "a.wav"}}))
        z.writestr("audio/a.wav", b"bu ses degil")
    monkeypatch.setattr(m, "MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
    r3 = client.post("/api/voices/import", files={"file": ("z.zip", bad.getvalue(), "application/zip")})
    assert r3.status_code == 400
    assert all(v["name"] != "x" for v in client.get("/api/voices").json())   # yarım kayıt kalmadı


# ---------- v4: diyalog, gerçek tepkiler, iyileştirme, sözlük, altyazı ----------

def _laugh_file(tmp_path):
    """Sentetik gülme: 3 kısa darbe, bant geçiren gürültü + 180 Hz ton."""
    sr = 24000
    rng = np.random.default_rng(3)
    parts = []
    for _ in range(3):
        n = int(sr * 0.22)
        t = np.linspace(0, 0.22, n, endpoint=False)
        env = np.hanning(n)
        parts.append(((0.25 * np.sin(2 * np.pi * 180 * t) + rng.standard_normal(n) * 0.08) * env).astype("float32"))
        parts.append(np.zeros(int(sr * 0.06), dtype="float32"))
    p = tmp_path / "gulme.wav"
    sf.write(str(p), np.concatenate(parts), sr)
    return p


def test_dialog_generation(client, ref_file):
    a = _add_voice(client, ref_file, "Ayşe Sesi")
    m = _add_voice(client, ref_file, "Mehmet Sesi")
    text = "İkisi kafede oturuyordu.\nAyşe: Selam, naber?\nMehmet: [yorgun] İyiyim ya, sen?\nAyşe: Ben de iyiyim."
    r = client.post("/api/tts", json={"text": text, "speakers": {"Ayşe": a["id"], "Mehmet": m["id"]},
                                      "narrator_voice_id": a["id"], "speaker_emotions": {"Mehmet": "sıkılmış"}, "wait": True})
    assert r.status_code == 200, r.text
    p = r.json()["params"]
    assert p["dialog"] is True and len(p["turns"]) == 4
    assert [t["speaker"] for t in p["turns"]] == [None, "Ayşe", "Mehmet", "Ayşe"]
    assert p["turns"][1]["voice_name"] == "Ayşe Sesi" and p["turns"][2]["voice_name"] == "Mehmet Sesi"
    assert p["turns"][0]["voice_name"] == "Ayşe Sesi"      # anlatıcı = narrator_voice_id
    assert "Ayşe Sesi" in r.json()["voice_name"] and "Mehmet Sesi" in r.json()["voice_name"]
    gid = r.json()["id"]
    srt = client.get(f"/api/generations/{gid}/subtitles?format=srt")
    assert srt.status_code == 200 and "-->" in srt.text and "Selam" in srt.text
    assert client.get(f"/api/generations/{gid}/subtitles?format=vtt").text.startswith("WEBVTT")
    assert client.get(f"/api/generations/{gid}/subtitles?format=xyz").status_code == 400
    # konuşmacı yok → 400
    assert client.post("/api/tts", json={"text": "Düz bir metin.", "speakers": {}}).status_code == 400


def test_nonverbal_recordings(client, ref_file, tmp_path):
    v = _add_voice(client, ref_file, "Buse")
    vid = v["id"]
    laugh = _laugh_file(tmp_path)
    r = client.post(f"/api/voices/{vid}/nonverbal", data={"tag": "laughs"},
                    files={"file": ("gulme.wav", laugh.read_bytes(), "audio/wav")})
    assert r.status_code == 200, r.text
    samples = r.json()["samples"]
    assert [s for s in samples if s["kind"] == "nonverbal"][0]["emotion"] == "gülme"
    assert client.get(f"/api/voices/{vid}").json()["samples"][0]["kind"] == "nonverbal"
    # kataloğa göre geçersiz etiket
    assert client.post(f"/api/voices/{vid}/nonverbal", data={"tag": "yok"},
                       files={"file": ("x.wav", laugh.read_bytes(), "audio/wav")}).status_code == 400
    # çok kısa kayıt
    short = tmp_path / "kisa.wav"
    sf.write(str(short), np.zeros(1200, dtype="float32"), 24000)
    assert client.post(f"/api/voices/{vid}/nonverbal", data={"tag": "gülme"},
                       files={"file": ("k.wav", short.read_bytes(), "audio/wav")}).status_code == 400
    # dışa aktarma tepkiyi de taşır, içe aktarma geri getirir
    z = client.get(f"/api/voices/{vid}/export")
    imp = client.post("/api/voices/import", files={"file": ("y.zip", z.content, "application/zip")}).json()
    assert any(s["kind"] == "nonverbal" and s["emotion"] == "gülme" for s in imp["samples"])
    assert client.delete(f"/api/voices/{vid}/nonverbal/gülme").status_code == 200
    assert client.get(f"/api/voices/{vid}").json()["samples"] == []
    h = client.get("/api/health").json()
    assert any(x["key"] == "gülme" for x in h["tags"]["nonverbal_recordable"]) and h["features"]["nonverbal"]


def test_enhance_and_undo(client, tmp_path):
    # gürültülü referans
    sr = 24000
    rng = np.random.default_rng(5)
    t = np.linspace(0, 8, sr * 8)
    wav = (0.2 * np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t) ** 2)).astype("float32")
    wav += (rng.standard_normal(len(wav)) * 0.02).astype("float32")
    p = tmp_path / "noisy.wav"
    sf.write(str(p), wav, sr)
    v = _add_voice(client, p, "Gürültülü")
    vid = v["id"]
    r = client.post(f"/api/voices/{vid}/enhance", data={"force": "true"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["applied"] is True and "before" in out and "after" in out and out["voice"]["enhanced"] is True
    assert (out["after"]["snr_db"] or 0) >= (out["before"]["snr_db"] or 0)
    r2 = client.post(f"/api/voices/{vid}/enhance/undo")
    assert r2.status_code == 200 and r2.json()["voice"]["enhanced"] is False
    assert client.post(f"/api/voices/{vid}/enhance/undo").status_code == 400


def test_lexicon_endpoints(client, ref_file):
    vid = _add_voice(client, ref_file)["id"]
    assert client.get("/api/lexicon").json() == []
    r = client.put("/api/lexicon", json={"word": "Fumor", "reading": "Fumor"})
    assert r.status_code == 200
    client.put("/api/lexicon", json={"word": "Shopify", "reading": "Şopifay"})
    client.put("/api/lexicon", json={"word": "Shopify", "reading": "Şopifayy", "voice_id": vid})
    entries = client.get(f"/api/lexicon?voice_id={vid}").json()
    assert any(e["word"] == "Shopify" and e["scope"] == "voice" for e in entries)
    t = client.post("/api/lexicon/test", json={"text": "tmm, Shopify mağazası {Claude|Klod} ile 12:30'da açılacak", "voice_id": vid}).json()
    assert "Şopifayy" in t["normalized"] and "tamam" in t["normalized"] and "Klod" in t["normalized"]
    assert "on iki otuzda" in t["normalized"] and "açılıcak" in t["normalized"]
    assert client.delete(f"/api/lexicon?word=Shopify&voice_id={vid}").json()["ok"]
    assert client.delete("/api/lexicon?word=yokboyle").status_code == 404
    assert client.get("/api/lexicon?voice_id=yok").status_code == 404
    # sözlük üretime de uygulanır
    r = client.post("/api/tts", json={"text": "Shopify harika.", "voice_id": vid, "wait": True})
    assert r.status_code == 200


def test_v4_settings_roundtrip(client, ref_file):
    vid = _add_voice(client, ref_file)["id"]
    r = client.post("/api/tts", json={"text": "Deneme.", "voice_id": vid, "wait": True,
                                      "consistency": False, "qc": False, "fillers": True, "chat_speak": False, "subtitles": False})
    p = r.json()["params"]
    assert p["consistency"] is False and p["qc"] is False and p["fillers"] is True and p["chat_speak"] is False
    assert p["timeline"] is None or p["timeline"] == []
    assert client.get(f"/api/generations/{r.json()['id']}/subtitles").status_code == 404
