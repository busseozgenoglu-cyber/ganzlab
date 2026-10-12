"""Duygu sistemi (ElevenLabs v3 etiket mantığıyla).

Üç katman birlikte çalışır:
1. Referans katmanı — duyguyu asıl belirleyen şey referans klibin tonudur. Her sesin duygu başına
   kendi örneği olabilir (kullanıcı kaydeder). Yoksa nötr örnekten perde/tempo/dinamik ile türetilir.
2. Üretim katmanı — duyguya göre exaggeration / cfg / temperature.
3. Çıktı katmanı — duyguya göre tempo, kazanç, mikro perde kaydırma, fısıltı için nefesli ton, kızgın için sıkıştırma.

Ayrıca sözsüz etiketler ([gülme], [iç çekme], [hmm]…) ve cümle içeriğinden otomatik duygu çıkarımı.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger("sesklon.emotion")


@dataclass
class EmotionProfile:
    name: str
    label: str
    # üretim
    exaggeration: float | None = None
    cfg_weight: float | None = None
    temperature: float | None = None
    # referans türetme (nötr klipten): yarım ton ve tempo çarpanı
    ref_pitch: float = 0.0
    ref_tempo: float = 1.0
    ref_gain_db: float = 0.0
    ref_breathy: bool = False
    # çıktı işleme
    speed: float = 1.0
    out_pitch: float = 0.0
    out_gain_db: float = 0.0
    highpass_hz: int = 0
    compress: bool = False
    breathy: bool = False
    whisper_mix: float = 0.0     # 1 = tam fısıltı dönüşümü, 0.3 = hafif nefesli
    pause_mul: float = 1.0       # cümle arası duraklama çarpanı
    aliases: list[str] = field(default_factory=list)


PROFILES: dict[str, EmotionProfile] = {p.name: p for p in [
    EmotionProfile("normal", "Normal", aliases=["nötr", "neutral", "doğal", "natural"]),
    EmotionProfile("heyecanlı", "Heyecanlı", exaggeration=0.7, cfg_weight=0.35, temperature=0.9,
                   ref_pitch=+1.2, ref_tempo=1.07, ref_gain_db=+2, speed=1.04, out_pitch=+0.5, out_gain_db=+1.5,
                   pause_mul=0.8, aliases=["heyecanli", "excited", "coşkulu", "enerjik", "energetic", "enthusiastic"]),
    EmotionProfile("mutlu", "Mutlu", exaggeration=0.7, cfg_weight=0.4, temperature=0.85,
                   ref_pitch=+0.8, ref_tempo=1.03, speed=1.02, out_pitch=+0.2, out_gain_db=+0.5,
                   pause_mul=0.9, aliases=["happy", "neşeli", "cheerful", "sevinçli"]),
    EmotionProfile("sakin", "Sakin", exaggeration=0.35, cfg_weight=0.55, temperature=0.7,
                   ref_pitch=-0.4, ref_tempo=0.95, speed=0.95, out_gain_db=-0.5,
                   pause_mul=1.25, aliases=["calm", "huzurlu", "rahat", "relaxed", "soft"]),
    EmotionProfile("ciddi", "Ciddi", exaggeration=0.4, cfg_weight=0.55, temperature=0.7,
                   ref_pitch=-0.6, ref_tempo=0.97, speed=0.97, out_pitch=-0.2,
                   pause_mul=1.15, aliases=["serious", "resmi", "formal", "kararlı", "determined"]),
    EmotionProfile("üzgün", "Üzgün", exaggeration=0.3, cfg_weight=0.5, temperature=0.7,
                   ref_pitch=-1.3, ref_tempo=0.9, ref_gain_db=-2, speed=0.9, out_pitch=-0.5, out_gain_db=-2.5,
                   pause_mul=1.5, aliases=["uzgun", "sad", "hüzünlü", "kederli", "melancholic", "mutsuz"]),
    EmotionProfile("kızgın", "Kızgın", exaggeration=0.85, cfg_weight=0.3, temperature=0.9,
                   ref_pitch=+0.5, ref_tempo=1.06, ref_gain_db=+3, speed=1.03, out_gain_db=+2.5, compress=True,
                   pause_mul=0.8, aliases=["kizgin", "angry", "öfkeli", "sinirli", "furious", "annoyed"]),
    EmotionProfile("şaşkın", "Şaşkın", exaggeration=0.75, cfg_weight=0.35, temperature=0.9,
                   ref_pitch=+1.5, ref_tempo=1.0, speed=1.0, out_pitch=+0.6,
                   pause_mul=1.1, aliases=["saskin", "surprised", "hayret", "shocked", "amazed"]),
    EmotionProfile("korkmuş", "Korkmuş", exaggeration=0.65, cfg_weight=0.4, temperature=0.9,
                   ref_pitch=+1.0, ref_tempo=1.08, ref_breathy=True, speed=1.05, out_pitch=+0.4, whisper_mix=0.25,
                   pause_mul=0.9, aliases=["korkmus", "scared", "endişeli", "nervous", "tedirgin", "anxious"]),
    EmotionProfile("fısıltı", "Fısıltı", exaggeration=0.25, cfg_weight=0.6, temperature=0.65,
                   ref_pitch=-0.3, ref_tempo=0.95, ref_gain_db=-6, ref_breathy=True, speed=0.93, out_gain_db=-8,
                   whisper_mix=1.0, pause_mul=1.3, aliases=["fisilti", "whisper", "whispers", "sessiz", "gizli"]),
    EmotionProfile("vurgulu", "Vurgulu", exaggeration=0.8, cfg_weight=0.45, temperature=0.8,
                   ref_tempo=0.97, speed=0.97, out_gain_db=+1.5, compress=True,
                   pause_mul=1.1, aliases=["emphasis", "emphatic", "önemli", "dikkat", "kesin"]),
    EmotionProfile("samimi", "Samimi", exaggeration=0.55, cfg_weight=0.45, temperature=0.8,
                   ref_pitch=-0.2, ref_tempo=0.98, speed=0.98,
                   pause_mul=1.05, aliases=["warm", "sıcak", "friendly", "dostça", "içten"]),
    EmotionProfile("sıkılmış", "Sıkılmış", exaggeration=0.25, cfg_weight=0.55, temperature=0.7,
                   ref_pitch=-0.8, ref_tempo=0.92, speed=0.92, out_pitch=-0.3, out_gain_db=-1.5,
                   pause_mul=1.3, aliases=["sikilmis", "bored", "bıkkın", "isteksiz", "tired", "yorgun"]),
    EmotionProfile("alaycı", "Alaycı", exaggeration=0.75, cfg_weight=0.4, temperature=0.85,
                   ref_pitch=+0.4, ref_tempo=0.96, speed=0.96, out_pitch=+0.2,
                   pause_mul=1.15, aliases=["alayci", "sarcastic", "ironik", "ironic", "dalga"]),
    EmotionProfile("hızlı", "Hızlı", ref_tempo=1.1, speed=1.12, pause_mul=0.7, aliases=["hizli", "fast", "acele"]),
    EmotionProfile("yavaş", "Yavaş", ref_tempo=0.92, speed=0.9, pause_mul=1.4, aliases=["yavas", "slow", "ağır"]),
]}

ALIAS_TO_NAME: dict[str, str] = {}
for _p in PROFILES.values():
    ALIAS_TO_NAME[_p.name] = _p.name
    for _a in _p.aliases:
        ALIAS_TO_NAME[_a] = _p.name

# Sözsüz etiketler → seslendirilecek metin (model doğal gülme/iç çekme üretemez; en yakın ünlem kullanılır)
NONVERBAL: dict[str, str] = {
    "gülme": "Hahaha!", "güler": "Hahaha!", "gülüyor": "Hahaha!", "kahkaha": "Hahahaha!", "laughs": "Hahaha!",
    "laugh": "Hahaha!", "kıkırdar": "Hihihi!", "kıkırdama": "Hihihi!", "chuckles": "Heh heh.", "giggles": "Hihihi!",
    "iç çeker": "Ahh...", "iç çekme": "Ahh...", "sighs": "Ahh...", "sigh": "Ahh...", "of": "Off...",
    "hmm": "Hmm...", "düşünür": "Hmm...", "şaşırır": "Vay canına!", "wow": "Vay!", "vay": "Vay!",
    "ağlar": "Hıh hıh...", "cries": "Hıh hıh...", "öksürür": "Öhö öhö.", "coughs": "Öhö öhö.",
    "boğaz temizler": "Ehem.", "clears throat": "Ehem.", "esner": "Aaah...", "yawns": "Aaah...",
    "nefes alır": "", "takes a breath": "", "pause": "", "duraklama": "", "nefes": "", "breath": "", "...": "",
}
PAUSE_TAGS = {"nefes": 500, "breath": 500, "nefes alır": 500, "takes a breath": 500, "pause": 800, "duraklama": 800,
              "...": 800, "uzun duraklama": 1500, "long pause": 1500}

# Otomatik duygu çıkarımı için anahtar sözcükler (küçük harf, köklere göre)
AUTO_LEXICON: list[tuple[str, tuple[str, ...]]] = [
    ("heyecanlı", ("harika", "müthiş", "inanılmaz", "muhteşem", "süper", "efsane", "hadi", "başlıyoruz", "kaçırma",
                   "mükemmel", "bomba", "wow", "vay", "heyecan", "yaşasın", "kazandı", "sürpriz", "yeni geldi")),
    ("mutlu", ("mutlu", "sevin", "teşekkür", "güzel", "tebrik", "seviyorum", "keyif", "neşe", "gülümse", "harikasın")),
    ("üzgün", ("maalesef", "üzgün", "ne yazık", "üzül", "kaybet", "özledim", "hüzün", "ağla", "veda", "keşke",
               "yalnız", "kırgın", "pişman", "başımız sağ olsun")),
    ("kızgın", ("sinir", "öfke", "yeter artık", "rezalet", "saçma", "dayanamıyorum", "bıktım", "kabul edilemez",
                "ciddi misin", "asla", "nasıl olur", "utanmaz")),
    ("şaşkın", ("şaşır", "inanamıyorum", "gerçekten mi", "ciddi mi", "nasıl ya", "olamaz", "ne?", "yok artık",
                "cidden mi")),
    ("korkmuş", ("korku", "endişe", "tehlike", "dikkat et", "korkuyorum", "ürper", "tedirgin", "panik")),
    ("ciddi", ("önemli", "unutma", "dikkat", "uyarı", "mutlaka", "kesinlikle", "lütfen", "şart", "zorunlu", "kural")),
    ("sakin", ("rahatla", "sakin", "huzur", "derin nefes", "yavaşça", "dinlen", "sessiz", "usulca")),
]


def resolve(name: str) -> EmotionProfile | None:
    key = name.strip().lower().replace("i̇", "i")
    return PROFILES.get(ALIAS_TO_NAME.get(key, "")) if key else None


def infer_emotion(sentence: str) -> str | None:
    """Cümle içeriğinden ve noktalamadan basit duygu tahmini. Emin değilse None."""
    s = sentence.lower()
    scores: dict[str, int] = {}
    for emo, words in AUTO_LEXICON:
        hits = sum(1 for w in words if w in s)
        if hits:
            scores[emo] = scores.get(emo, 0) + hits * 2
    if s.rstrip().endswith("!"):
        for emo in ("heyecanlı", "kızgın", "şaşkın", "mutlu"):
            if emo in scores:
                scores[emo] += 1
        if not scores:
            scores["heyecanlı"] = 1
    if not scores:
        return None
    return max(scores, key=scores.get)


# ---------- ses işleme (ffmpeg) ----------

def _has_rubberband() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=10).stdout
        return " rubberband " in out
    except Exception:  # noqa: BLE001
        return False


_RB: bool | None = None


def _rb() -> bool:
    global _RB
    if _RB is None:
        _RB = shutil.which("ffmpeg") is not None and _has_rubberband()
    return _RB


def _ffmpeg_filter(wav: np.ndarray, sr: int, afilter: str) -> np.ndarray:
    if not shutil.which("ffmpeg") or not afilter:
        return wav
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        sf.write(str(src), np.asarray(wav, dtype=np.float32), sr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter:a", afilter, "-ar", str(sr), str(dst)], check=True)
        out, _ = sf.read(str(dst), dtype="float32", always_2d=False)
    return np.asarray(out, dtype=np.float32).squeeze()


def pitch_tempo_filter(sr: int, semitones: float = 0.0, tempo: float = 1.0) -> str:
    """Perde (yarım ton) ve tempoyu bağımsız değiştiren ffmpeg filtre dizesi."""
    parts = []
    if _rb() and (abs(semitones) > 0.01 or abs(tempo - 1) > 0.005):
        parts.append(f"rubberband=pitch={2 ** (semitones / 12):.5f}:tempo={tempo:.4f}:pitchq=quality")
    else:
        if abs(semitones) > 0.01:
            ratio = 2 ** (semitones / 12)
            parts.append(f"asetrate={int(sr * ratio)},aresample={sr},atempo={1 / ratio:.5f}")
        if abs(tempo - 1) > 0.005:
            parts.append(f"atempo={tempo:.4f}")
    return ",".join(parts)


def breathy_filter(level_db: float = -24.0) -> str:
    """Nefesli/fısıltı tınısı: alçakları kes, 2–6 kHz'i hafif yükselt."""
    return f"highpass=f=160,equalizer=f=3500:t=q:w=1.2:g=4,treble=g=3:f=5000"


def derive_reference(src: Path, dst: Path, profile: EmotionProfile, sr: int) -> Path:
    """Nötr referanstan duyguya özgü referans üretir (perde/tempo/kazanç/nefes)."""
    wav, file_sr = sf.read(str(src), dtype="float32", always_2d=False)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    filters = []
    pt = pitch_tempo_filter(file_sr, profile.ref_pitch, profile.ref_tempo)
    if pt:
        filters.append(pt)
    if profile.ref_breathy:
        filters.append(breathy_filter())
    if abs(profile.ref_gain_db) > 0.1:
        filters.append(f"volume={profile.ref_gain_db:+.1f}dB")
    out = _ffmpeg_filter(wav, file_sr, ",".join(filters)) if filters else wav
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out = out * (0.98 / peak)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), out, file_sr)
    return dst


def whisperize(wav: np.ndarray, sr: int, mix: float = 1.0, order: int = 24, frame_ms: int = 25, hop_ms: int = 10) -> np.ndarray:
    """Konuşmayı fısıltıya çevirir: her karede LPC ile ses yolu zarfı çıkarılır, periyodik uyarım yerine
    gürültü ile yeniden sentezlenir (ses telleri titreşmiyormuş gibi). mix=1 tam fısıltı, 0.5 yarı nefesli."""
    import librosa
    from scipy.signal import lfilter

    x = np.asarray(wav, dtype=np.float64)
    if x.size < sr // 10:
        return wav
    frame = int(sr * frame_ms / 1000)
    hop = int(sr * hop_ms / 1000)
    pre = np.append(x[0], x[1:] - 0.97 * x[:-1])          # pre-emphasis
    win = np.hanning(frame)
    out = np.zeros(len(x) + frame)
    norm = np.zeros(len(x) + frame)
    rng = np.random.default_rng(7)
    for start in range(0, len(x) - frame, hop):
        seg = pre[start:start + frame] * win
        energy = np.sqrt(np.mean(seg ** 2)) + 1e-9
        if energy < 1e-4:
            continue
        try:
            a = librosa.lpc(seg, order=order)
        except Exception:  # noqa: BLE001
            continue
        noise = rng.standard_normal(frame)
        synth = lfilter([1.0], a, noise)
        if not np.all(np.isfinite(synth)):
            continue
        synth *= energy / (np.sqrt(np.mean(synth ** 2)) + 1e-9)
        out[start:start + frame] += synth * win
        norm[start:start + frame] += win ** 2
    norm[norm < 1e-6] = 1.0
    y = out[: len(x)] / norm[: len(x)]
    y = lfilter([1.0], [1.0, -0.97], y)                    # de-emphasis
    # Fısıltıda alçak frekans yoktur; tipik fısıltı spektrumu için yüksek geçiren + hafif tiz
    y = _ffmpeg_filter(y.astype(np.float32), sr, "highpass=f=250,treble=g=2:f=4000,lowpass=f=9000")
    y = y[: len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))
    # Orijinalin RMS zarfını koru (hece vurgusu kaybolmasın)
    env_x = _envelope(x, sr)
    env_y = _envelope(y, sr) + 1e-6
    y = y * np.clip(env_x / env_y, 0, 10)
    hp_orig = _ffmpeg_filter(np.asarray(wav, dtype=np.float32), sr, "highpass=f=1200")
    hp_orig = hp_orig[: len(x)] if len(hp_orig) >= len(x) else np.pad(hp_orig, (0, len(x) - len(hp_orig)))
    res = mix * y + (1 - mix) * np.asarray(wav, dtype=np.float64) + 0.15 * hp_orig  # biraz tıslama ayrıntısı
    peak = np.max(np.abs(res)) + 1e-9
    target = np.max(np.abs(x)) + 1e-9
    return (res * (target / peak)).astype(np.float32)


def _envelope(x: np.ndarray, sr: int, ms: int = 20) -> np.ndarray:
    n = max(1, int(sr * ms / 1000))
    kernel = np.ones(n) / n
    return np.sqrt(np.convolve(np.asarray(x, dtype=np.float64) ** 2, kernel, mode="same") + 1e-12)


FX_LEVELS = ("off", "light", "full")


def post_process(wav: np.ndarray, sr: int, profile: EmotionProfile | None, fx: str = "off") -> np.ndarray:
    """Üretilen parçaya duyguya göre çıktı işleme uygular (hız hariç; o ayrı uygulanır).

    fx="off"  : işleme yok (en doğal; fısıltı yalnızca kısılır ve alçaklar kesilir)
    fx="light": kazanç + fısıltı/kızgın için hafif tını
    fx="full" : perde kaydırma, sıkıştırma, nefesli tını, LPC fısıltı dönüşümü (deneysel)
    """
    if profile is None:
        return wav
    if fx == "off":
        if profile.name == "fısıltı":
            try:
                return _ffmpeg_filter(wav, sr, "highpass=f=150,volume=-7dB")
            except Exception:  # noqa: BLE001
                return wav
        return wav
    if fx == "light":
        filters = []
        if abs(profile.out_gain_db) > 0.1:
            filters.append(f"volume={profile.out_gain_db:+.1f}dB")
        if profile.name == "fısıltı":
            filters.append("highpass=f=180,treble=g=2:f=4000")
        if not filters:
            return wav
        try:
            return _ffmpeg_filter(wav, sr, ",".join(filters))
        except Exception:  # noqa: BLE001
            return wav
    if profile.whisper_mix > 0:
        try:
            wav = whisperize(wav, sr, mix=profile.whisper_mix)
        except Exception as e:  # noqa: BLE001
            log.warning("Fısıltı dönüşümü atlandı: %s", e)
    filters = []
    if abs(profile.out_pitch) > 0.01:
        filters.append(pitch_tempo_filter(sr, profile.out_pitch, 1.0))
    if profile.highpass_hz:
        filters.append(f"highpass=f={profile.highpass_hz}")
    if profile.breathy:
        filters.append(breathy_filter())
    if profile.compress:
        filters.append("acompressor=threshold=-18dB:ratio=3:attack=10:release=120:makeup=2")
    if abs(profile.out_gain_db) > 0.1:
        filters.append(f"volume={profile.out_gain_db:+.1f}dB")
    filters = [f for f in filters if f]
    if not filters:
        return wav
    try:
        return _ffmpeg_filter(wav, sr, ",".join(filters))
    except Exception as e:  # noqa: BLE001
        log.warning("Duygu çıktı işleme atlandı: %s", e)
        return wav


# ---------- etiket ayrıştırma ----------

_TAG_RE = re.compile(r"\[\s*([^\[\]]{1,40}?)\s*\]")


@dataclass
class Segment:
    text: str
    emotion: str | None          # profil adı
    pause_before_ms: int = 0     # bölüm başındaki ek duraklama
    pause_after_ms: int = 0


def parse_tagged_text(text: str) -> list[Segment]:
    """Metni [duygu]/[duraklama] sınırlarından bölümlere ayırır; sözsüz etiketler ([gülme] → "Hahaha!")
    akan metne satır içi eklenir ki model onları cümle bağlamında üretsin (tek başına halüsinasyon yapıyor)."""
    segments: list[Segment] = []
    emotion: str | None = None
    pending_pause = 0
    buf: list[str] = []
    pos = 0

    def flush():
        nonlocal pending_pause
        t = " ".join(x.strip() for x in buf if x.strip()).strip()
        buf.clear()
        if t:
            segments.append(Segment(t, emotion, pending_pause, 0))
            pending_pause = 0

    for m in _TAG_RE.finditer(text):
        buf.append(text[pos:m.start()])
        raw = m.group(1).strip().lower()
        if raw in PAUSE_TAGS:
            flush()
            pending_pause += PAUSE_TAGS[raw]
        elif raw in NONVERBAL:
            if NONVERBAL[raw]:
                buf.append(NONVERBAL[raw])
        else:
            prof = resolve(raw)
            if prof is not None:
                flush()
                emotion = None if prof.name == "normal" else prof.name
            # tanınmayan etiket: sessizce yok sayılır (ElevenLabs de bilinmeyenleri yok sayar)
        pos = m.end()
    buf.append(text[pos:])
    flush()
    if segments and pending_pause:
        segments[-1].pause_after_ms += pending_pause
    return segments


def tag_catalog() -> dict:
    return {
        "emotions": [{"name": p.name, "label": p.label, "aliases": p.aliases} for p in PROFILES.values()],
        "nonverbal": sorted({k for k, v in NONVERBAL.items() if v}),
        "pauses": sorted(PAUSE_TAGS.keys()),
    }
