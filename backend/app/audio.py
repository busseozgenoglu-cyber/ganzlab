"""Ses dosyası yardımcıları: dönüştürme, kırpma, süre ölçme, kaydetme."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

TARGET_SR = 24000


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def to_wav(src: Path, dst: Path, sr: int = TARGET_SR, max_seconds: float | None = None) -> None:
    """Herhangi bir ses/video formatını mono 24 kHz WAV'a çevirir (ffmpeg varsa onu kullanır)."""
    if has_ffmpeg():
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr)]
        if max_seconds:
            cmd += ["-t", str(max_seconds)]
        cmd += ["-c:a", "pcm_s16le", str(dst)]
        subprocess.run(cmd, check=True)
        return

    # ffmpeg yoksa torchaudio/librosa ile dene
    import librosa

    y, _ = librosa.load(str(src), sr=sr, mono=True, duration=max_seconds)
    sf.write(str(dst), y, sr)


def duration_of(path: Path) -> float:
    info = sf.info(str(path))
    return float(info.frames) / float(info.samplerate)


def save_wav(path: Path, wav: np.ndarray, sr: int) -> float:
    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.squeeze()
    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    if peak > 1.0:
        wav = wav / peak
    sf.write(str(path), wav, sr)
    return len(wav) / sr


def wav_to_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "128k") -> bool:
    if not has_ffmpeg():
        return False
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)],
        check=True,
    )
    return True


# ---------- doğallık için sinyal işleme ----------

def db_to_amp(db: float) -> float:
    return 10 ** (db / 20)


def trim_silence(wav: np.ndarray, sr: int, threshold_db: float = -42.0, pad_ms: int = 60, frame_ms: int = 20) -> np.ndarray:
    """Baştaki ve sondaki sessizliği kırpar; küçük bir pay bırakır."""
    wav = np.asarray(wav, dtype=np.float32).squeeze()
    if wav.size == 0:
        return wav
    frame = max(1, int(sr * frame_ms / 1000))
    n = len(wav) // frame
    if n == 0:
        return wav
    frames = wav[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    thr = db_to_amp(threshold_db)
    loud = np.where(rms > thr)[0]
    if loud.size == 0:
        return wav
    pad = int(sr * pad_ms / 1000)
    start = max(0, loud[0] * frame - pad)
    end = min(len(wav), (loud[-1] + 1) * frame + pad)
    return wav[start:end]


def rms_normalize(wav: np.ndarray, target_dbfs: float = -20.0, peak_dbfs: float = -1.0) -> np.ndarray:
    """Ortalama seviyeyi hedefe çeker, tepe değeri sınırlar."""
    wav = np.asarray(wav, dtype=np.float32).squeeze()
    if wav.size == 0:
        return wav
    rms = float(np.sqrt(np.mean(wav ** 2) + 1e-12))
    if rms > 0:
        wav = wav * (db_to_amp(target_dbfs) / rms)
    peak = float(np.max(np.abs(wav)))
    limit = db_to_amp(peak_dbfs)
    if peak > limit:
        wav = wav * (limit / peak)
    return wav.astype(np.float32)


def fade(wav: np.ndarray, sr: int, ms: int = 12) -> np.ndarray:
    n = min(len(wav) // 2, int(sr * ms / 1000))
    if n <= 0:
        return wav
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    wav = wav.copy()
    wav[:n] *= ramp
    wav[-n:] *= ramp[::-1]
    return wav


def join_with_pauses(pieces: list[np.ndarray], pauses_ms: list[int], sr: int, fade_ms: int = 12) -> np.ndarray:
    """Parçaları, aralarına doğal duraklamalar koyarak ve kenarları yumuşatarak birleştirir."""
    out: list[np.ndarray] = []
    for i, piece in enumerate(pieces):
        out.append(fade(piece, sr, fade_ms))
        if i < len(pieces) - 1:
            out.append(np.zeros(int(sr * pauses_ms[i] / 1000), dtype=np.float32))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def best_window(wav: np.ndarray, sr: int, seconds: float, frame_ms: int = 20, threshold_db: float = -40.0) -> np.ndarray:
    """Konuşma oranı en yüksek `seconds` uzunluğundaki pencereyi döndürür; sınırları sessizliğe denk getirir."""
    frame = max(1, int(sr * frame_ms / 1000))
    n = len(wav) // frame
    frames = wav[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    voiced = (rms > db_to_amp(threshold_db)).astype(np.float32)
    win = int(seconds * sr / frame)
    if win >= n:
        return wav
    cum = np.concatenate([[0.0], np.cumsum(voiced)])
    scores = cum[win:] - cum[:-win]
    start_f = int(np.argmax(scores))
    # Pencere başını/sonunu en yakın sessiz kareye kaydır (kelime ortasında kesmemek için)
    for k in range(start_f, max(0, start_f - 25), -1):
        if voiced[k] == 0:
            start_f = k
            break
    end_f = min(n, start_f + win)
    for k in range(end_f, max(start_f + win // 2, end_f - 25), -1):
        if voiced[k - 1] == 0:
            end_f = k
            break
    return wav[start_f * frame: end_f * frame]


def prepare_reference(src: Path, dst: Path, max_seconds: float, sr: int = TARGET_SR) -> float:
    """Referans örneği: mono/24k'ya çevir, sessizlikleri kırp, seviyeyi dengele, en fazla max_seconds tut."""
    tmp = dst.with_suffix(".raw.wav")
    to_wav(src, tmp, sr, None)
    try:
        wav, file_sr = sf.read(str(tmp), dtype="float32", always_2d=False)
    finally:
        tmp.unlink(missing_ok=True)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    wav = trim_silence(wav, file_sr, threshold_db=-45.0, pad_ms=100)
    # Uzun kayıtlarda en "dolu" (en çok konuşma, en az boşluk içeren) pencereyi seç
    max_len = int(max_seconds * file_sr)
    if len(wav) > max_len:
        wav = best_window(wav, file_sr, max_seconds)
    wav = rms_normalize(wav, target_dbfs=-20.0)
    wav = fade(wav, file_sr, 20)
    sf.write(str(dst), wav, file_sr)
    return len(wav) / file_sr


def change_speed(wav: np.ndarray, sr: int, speed: float) -> np.ndarray:
    """Perdeyi bozmadan tempo değiştirir (ffmpeg atempo, WSOLA). 0.5–2.0 arası."""
    speed = float(speed)
    if abs(speed - 1.0) < 0.01 or not has_ffmpeg():
        return wav
    speed = min(2.0, max(0.5, speed))
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.wav"
        dst = Path(td) / "out.wav"
        sf.write(str(src), np.asarray(wav, dtype=np.float32), sr)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter:a", f"atempo={speed:.3f}", "-ar", str(sr), str(dst)],
            check=True,
        )
        out, _ = sf.read(str(dst), dtype="float32", always_2d=False)
    return np.asarray(out, dtype=np.float32).squeeze()


def normalize_relative(wav: np.ndarray, pieces: list[np.ndarray], target_dbfs: float = -18.0, peak_dbfs: float = -1.0) -> np.ndarray:
    """En gür parçayı hedefe çeker; parçalar arası (duyguya bağlı) şiddet farklarını korur."""
    wav = np.asarray(wav, dtype=np.float32).squeeze()
    if wav.size == 0:
        return wav
    rms_list = [float(np.sqrt(np.mean(p ** 2) + 1e-12)) for p in pieces if p.size]
    ref = max(rms_list) if rms_list else float(np.sqrt(np.mean(wav ** 2) + 1e-12))
    if ref > 0:
        wav = wav * (db_to_amp(target_dbfs) / ref)
    peak = float(np.max(np.abs(wav)))
    limit = db_to_amp(peak_dbfs)
    if peak > limit:
        wav = wav * (limit / peak)
    return wav.astype(np.float32)


def cut_at_silence(wav: np.ndarray, sr: int, max_seconds: float, search_ms: int = 600, frame_ms: int = 20) -> np.ndarray:
    """max_seconds civarındaki en sessiz kareden keser (kelime ortasında kesmemek için), sonuna kısa fade koyar."""
    wav = np.asarray(wav, dtype=np.float32)
    limit = int(max_seconds * sr)
    if len(wav) <= limit:
        return wav
    frame = max(1, int(sr * frame_ms / 1000))
    lo = max(0, limit - int(sr * search_ms / 1000))
    seg = wav[lo:limit]
    n = len(seg) // frame
    if n > 0:
        rms = np.sqrt(np.mean(seg[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
        cut = lo + int(np.argmin(rms)) * frame
    else:
        cut = limit
    out = wav[:cut].copy()
    return fade(out, sr, 25)
