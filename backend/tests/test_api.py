import time
from pathlib import Path

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

    @property
    def loaded(self):
        return True

    def preload(self):
        pass

    def preload_background(self):
        pass

    def synthesize(self, text, lang, refs, ex, cfg, temp, seed, speed, colloquial, pe, auto, er, progress=None, emotion_fx="off"):
        chunks = split_text(text, 170, None, auto)
        for i, c in enumerate(chunks):
            if progress:
                progress(i, len(chunks), c.text)
        sr = 24000
        t = np.linspace(0, 1, sr)
        rep = {"normalized_text": " ".join(c.text for c in chunks),
               "chunks": [{"text": c.text, "emotion": c.emotion, "ref": self.reference_for(refs, c.emotion, derive=(emotion_fx == "full"))[1]} for c in chunks]}
        return (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32"), sr, rep

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


def test_full_flow(client, ref_file):
    assert client.get("/api/health").json()["ok"]
    r = client.post("/api/voices", data={"name": "Test", "language": "tr", "consent": "true"},
                    files={"file": ("ref.wav", ref_file.read_bytes(), "audio/wav")})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
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

    r = client.post("/api/tts", json={"text": "[heyecanlı] Selam!", "voice_id": vid, "wait": True, "emotion_fx": "full"})
    assert r.json()["params"]["chunks"][0]["ref"] == "türetilmiş"

    r = client.post("/api/tts", json={"text": "Merhaba", "voice_id": vid, "wait": True, "format": "mp3"})
    assert r.status_code == 200 and r.json()["url"].endswith(".mp3")
    assert client.get(r.json()["url"]).status_code == 200

    r = client.post("/api/vc", data={"voice_id": vid, "wait": "true"}, files={"file": ("s.wav", ref_file.read_bytes(), "audio/wav")})
    assert r.status_code == 200 and r.json()["kind"] == "vc"
    assert len(client.get("/api/generations").json()) == 4
    assert client.delete(f"/api/voices/{vid}").json()["ok"]
    assert client.get("/api/nope").status_code == 404


def test_validation(client):
    assert client.post("/api/tts", json={"text": "", "voice_id": None}).status_code == 422
    assert client.post("/api/tts", json={"text": "x", "language": "xx"}).status_code == 400
    assert client.post("/api/tts", json={"text": "x", "emotion": "yok"}).status_code == 400
    assert client.post("/api/voices", data={"name": "a", "consent": "false"},
                       files={"file": ("a.wav", b"notaudio", "audio/wav")}).status_code == 400
