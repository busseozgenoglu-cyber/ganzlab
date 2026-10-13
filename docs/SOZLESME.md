# SesKlon v3 — Modül ve API Sözleşmesi (geliştirme sırasında ortak referans)

Bu dosya, paralel çalışan geliştiricilerin aynı arayüzleri hedeflemesi için yazıldı. Her modül burada tanımlı
imzaları **birebir** uygular; başka modülün dosyasına dokunulmaz.

Ortak yardımcı: `backend/app/tr.py` — `tr_lower`, `tr_upper`, `last_vowel`, `harmony_vowel_2/4`, `count_syllables`,
`locative_suffix`, `dative_suffix`, `ablative_suffix`, `genitive_suffix`, `plural_suffix`, `is_turkish_word_like`.
**Hiçbir modül `str.lower()` kullanmaz; `tr_lower` kullanır** (İ/ı sorunu).

---

## 1. `textnorm.py` — Türkçe normalizasyon

```python
normalize(text: str, lang: str = "tr") -> str          # mevcut imza korunur
normalize_tr(text: str) -> str
tr_int_to_words(n: int) -> str
tr_ordinal(n: int) -> str
spell_acronym(word: str) -> str                         # "ABD" → "a be de", "KDV" → "ka de ve"
read_money_tr(amount: str, currency: str) -> str        # "12,50", "lira" → "on iki lira elli kuruş"
read_time_tr(h: int, m: int) -> str                     # (14, 5) → "on dört sıfır beş", (14, 30) → "on dört otuz"
```

Mevcut testler (`tests/test_text.py`) **aynen geçmeli**.

## 2. `colloquial.py` — konuşma dili

```python
colloquial_tr(text: str, level: str | bool = "light") -> str
# level: "off" (dokunma) | "light" (gelecek zaman kısaltma, bişey, bi tane…) | "full" (+ -yor r düşmesi, böle/şöle, diil, bi + isim)
# bool True → "light", False → "off"
LEVELS = ("off", "light", "full")
```

Mevcut testler aynen geçmeli (bunlar "light" seviyesine denk).

## 3. `prosody.py` — duraklama, nefes, oda tonu, mastering (yeni)

```python
plan_pauses(chunks: list[dict], pause_scale: float = 1.0, seed: int | None = None) -> list[int]
# chunks[i] = {"text": str, "punct": "!"|"?"|"..."|"", "emotion": str|None, "pause_after_ms": int,
#              "paragraph_end": bool, "next_text": str|None}
# Dönüş: her parça için ms. Kurallar: bağlaçla başlayan sonraki cümle (ama, fakat, çünkü, yani, ki, ve, ya da,
# ancak, sonra, o zaman, zaten, hatta, üstelik, oysa, çünkü…) → %35 kısa; soru→cevap → %20 kısa; çok uzun cümle
# sonrası +%15; seed'li ±12 % titreşim (jitter). Son parça için 0. Sonuç 60–2500 ms arasına sıkıştırılır.

plan_breaths(chunks: list[dict], durations_s: list[float], min_gap_s: float = 6.0, seed: int | None = None) -> list[bool]
# breaths[i] = i. parçadan ÖNCE nefes konulsun mu. İlk parça False. Son nefesten bu yana konuşma ≥ min_gap_s ve
# parça yeterince uzunsa (≥ 2.5 sn) True. Paragraf başına her zaman True (ilk hariç).

synth_breath(sr: int, duration_ms: int = 320, level_db: float = -34.0, seed: int | None = None) -> np.ndarray
# Gürültü tabanlı, bant geçiren (300–4000 Hz) ve yumuşak zarflı sentetik nefes.

make_room_tone(n_samples: int, sr: int, floor_sample: np.ndarray | None = None, level_db: float = -58.0,
               seed: int | None = None) -> np.ndarray
# floor_sample varsa onu rastgele kaydırarak/döngüleyerek, yoksa pembe gürültü ile verilen seviyede "oda tonu".

join_natural(pieces: list[np.ndarray], pauses_ms: list[int], sr: int, *, room_tone: np.ndarray | None = None,
             breath: np.ndarray | None = None, breath_plan: list[bool] | None = None, crossfade_ms: int = 15) -> np.ndarray
# Parçaları duraklamalarla birleştirir; duraklamalar sıfır yerine oda tonuyla doldurulur; nefes planı True olan
# parçanın önündeki duraklamanın ortasına nefes yerleştirilir (duraklama en az nefes kadar uzatılır); kenarlar çapraz
# geçişle yumuşatılır. room_tone None ise sessizlik.

master(wav: np.ndarray, sr: int, *, target_lufs: float = -16.0, true_peak_db: float = -1.5,
       highpass_hz: int = 60, deess: bool = True, warmth: bool = True) -> np.ndarray
# ffmpeg varsa: highpass + hafif de-ess (6–9 kHz dinamik EQ yoksa statik -2 dB) + loudnorm (EBU R128) +
# tek tepe sınırlayıcı. Yoksa RMS tabanlı yedek. Çıktı float32, tepe ≤ true_peak.

measure_loudness(wav: np.ndarray, sr: int) -> dict   # {"lufs": float|None, "peak_dbfs": float, "rms_dbfs": float}
```

## 4. `analysis.py` — referans kaydı analizi (yeni)

```python
analyze_reference(path: str | Path) -> dict   # aşağıdaki şema
analyze_array(wav: np.ndarray, sr: int) -> dict
extract_noise_floor(wav: np.ndarray, sr: int, seconds: float = 0.8) -> np.ndarray | None   # en sessiz bölge (oda tonu)
extract_breath(wav: np.ndarray, sr: int) -> np.ndarray | None                              # kayıttan gerçek nefes
```

Analiz şeması (JSON'a yazılabilir, tüm sayılar yuvarlanmış):
```json
{
  "duration": 12.3, "speech_ratio": 0.82, "snr_db": 31.5, "noise_floor_dbfs": -58.0,
  "peak_dbfs": -1.2, "rms_dbfs": -20.1, "clipping_ratio": 0.0, "dc_offset": 0.001, "bandwidth_hz": 7800,
  "reverb": "düşük",
  "f0": {"median_hz": 180.0, "min_hz": 110.0, "max_hz": 290.0, "range_semitones": 16.8, "voiced_ratio": 0.6,
         "label": "kadın|erkek|belirsiz"},
  "speaking_rate": {"syllables_per_sec": 5.1, "label": "yavaş|normal|hızlı"},
  "pauses": {"count": 4, "mean_ms": 420, "median_ms": 380, "per_minute": 19.5, "scale": 1.05},
  "breaths": {"count": 2, "positions_s": [3.1, 7.8]},
  "quality_score": 84, "grade": "mükemmel|iyi|orta|zayıf",
  "issues": [{"code": "noisy", "severity": "warn", "message": "Türkçe açıklama ve öneri"}],
  "tips": ["Türkçe kısa öneri", "..."]
}
```
`pauses.scale`: kişinin ölçülen ortalama duraklaması / 400 ms, 0.7–1.5 arasına sıkıştırılmış (motor PAUSE çarpanı).
`issues.code` değerleri: `too_short`, `too_long`, `noisy`, `clipping`, `too_quiet`, `too_loud`, `low_bandwidth`,
`reverb`, `dc_offset`, `low_speech_ratio`, `monotone`, `too_fast`, `too_slow`, `music_or_multi` (isteğe bağlı).

## 5. `emotion.py` + `styles.py`

`emotion.py` mevcut arayüzler korunur; `resolve`, `infer_emotion` `tr_lower` kullanır. Sözsüz etiket ve sözlük genişletilir.

`styles.py` (yeni):
```python
@dataclass
class Style:
    name: str; label: str; description: str
    emotion: str | None = None; exaggeration: float = 0.5; cfg_weight: float = 0.45; temperature: float = 0.8
    speed: float = 1.0; pause_scale: float = 1.0; colloquial: str = "light"; breaths: bool = True
    punctuation_emotion: bool = True; auto_emotion: bool = False
STYLES: dict[str, Style]        # anahtar = name
resolve_style(name: str) -> Style | None   # tr_lower + alias
style_catalog() -> list[dict]
```
Stiller: `sohbet`, `anlatıcı`, `haber`, `reklam`, `masal`, `podcast`, `belgesel`, `eğitim`, `sesli-kitap`, `duygusal`.

## 6. `db.py` + `jobs.py`

db: `voices.analysis TEXT`, `voice_samples.analysis TEXT`, `generations.seed INTEGER`, `generations.group_id TEXT`
(varyant grubu). Göç: `PRAGMA table_info` ile eksik sütun eklenir (`ALTER TABLE`).
```python
set_voice_analysis(vid, analysis: dict) -> None ; get_voice(vid)["analysis"] dict|None (JSON çözülmüş)
set_sample_analysis(sid, analysis: dict)
add_generation(..., seed=None, group_id=None)
list_generations(limit=100, offset=0, kind=None, voice_id=None, q=None) -> list[dict]
count_generations() -> int
```
jobs:
```python
Job.partial: list[dict]      # [{"index": 0, "url": "/files/outputs/partial/...", "text": "...", "duration": 1.2}]
Job.add_partial(d: dict)
Job.cancel() ; Job.cancelled: bool ; Job.check_cancelled()  # raise JobCancelled
Job.to_dict() → + "partial", "eta_s" (kalan tahmini sn; ilerlemeden), "cancelled"
JobQueue.cancel(job_id) -> bool ; status "cancelled"
```

## 7. HTTP API (main.py — entegrasyon aşamasında uygulanır; arayüz buna göre yazılır)

`POST /api/tts` gövde — mevcut alanlara ek:
| alan | tip | varsayılan | açıklama |
|---|---|---|---|
| `colloquial` | bool \| "off"\|"light"\|"full" | "light" | konuşma dili seviyesi |
| `breaths` | bool | true | cümleler arası doğal nefes |
| `room_tone` | bool | true | sessizlik yerine referanstan oda tonu |
| `master` | bool | true | -16 LUFS, -1.5 dBTP, hafif EQ |
| `pause_scale` | float 0.5–2.0 | 1.0 | duraklama çarpanı (ses analizindeki `pauses.scale` ile çarpılır) |
| `style` | str \| null | null | stil ön ayarı (`styles`) — alan verilmezse stilin değeri, verilirse kullanıcının değeri |
| `variants` | int 1–4 | 1 | farklı tohumlarla N varyant |

İş (`/api/jobs/{id}`) sözlüğüne ek: `partial: [...]`, `eta_s`, `cancelled`. `POST /api/jobs/{id}/cancel`.

Sonuç: üretim sözlüğü; `variants>1` ise `result.variants = [gen, gen, ...]` (ilki = result'ın kendisi; hepsi geçmişte
`group_id` ile).

`GET /api/health` ek: `styles: [{name,label,description}]`, `colloquial_levels`, `features: {breaths, room_tone, master, analysis}`.

Sesler: `POST /api/voices` yanıtında `analysis`; `GET /api/voices/{id}/analysis`; `POST /api/analyze` (multipart `file`)
→ kaydetmeden analiz. Örnekler (`samples[]`) de `analysis` taşır.

`GET /api/generations?limit=&offset=&kind=&voice_id=&q=`.

## 8. Arayüz (`frontend/src/api.js`)

```js
api.cancelJob(id)                       // POST /api/jobs/{id}/cancel
api.analyze(file)                       // POST /api/analyze
api.voiceAnalysis(id)                   // GET /api/voices/{id}/analysis
api.generations({limit, offset, kind, voice_id, q})
api.tts(payload, onProgress)            // onProgress(job) — job.partial listesi parça parça dolar
```
