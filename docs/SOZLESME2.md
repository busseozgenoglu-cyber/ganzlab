# SesKlon v4 — "Diyalog, duygu yoğunluğu, gerçek tepkiler" sözleşmesi (2. dalga)

v3 üzerine 10 paralel geliştirici. Herkes yalnızca kendi dosyalarına yazar; imzalar **birebir** uygulanır.
Ortak yardımcılar: `backend/app/tr.py` (tr_lower, count_syllables, …), `audio.py` (fade, trim_silence, rms_normalize,
db_to_amp, resample, TARGET_SR=24000), `prosody.py`, `analysis.py`. Hiçbir modül `str.lower()` kullanmaz.
Entegrasyon (engine.py / main.py / db.py) dalga bittikten sonra tek elden yapılır — bu dosyalara DOKUNULMAZ.

---

## 1. `dialog.py` — çok konuşmacılı metin (Diyalog modu)

```python
@dataclass
class Turn:
    index: int
    speaker: str | None        # "Ayşe" / None = anlatıcı
    text: str                  # satırın metni (etiketler dahil; [ses:…] ve "Ad:" öneki ÇIKARILMIŞ)
    line_no: int

parse_dialog(text: str) -> list[Turn]
# Desteklenen biçimler (karışık olabilir):
#   "Ayşe: Selam, naber?"            → satır başı, 1–3 sözcüklük ad (harf, nokta, tire, kesme), ardından ":" veya " - "
#   "[ses:Mehmet] İyiyim ya."        → aynı satırda bölüm; [konuşmacı:…] eş anlamlı; "[ses: Mehmet]" boşluklu da
#   "AYŞE —" / "Ayşe (gülerek):"     → parantezli yönerge → Turn.text başına "[gülerek]" olarak eklenir (duygu etiketi
#                                       çözülür; çözülemezse atılır)
#   Konuşmacısız satır → önceki konuşmacı devam eder; en başta ise anlatıcı (None).
#   "Not:" "Saat 12:30:" gibi yanlış pozitifler: ad sözlük/ünlem değil (ad büyük harfle başlar, ≤ 3 sözcük, sonrasında
#   boşluk + metin; "12:30" sayı olduğu için ad değil; "Not", "Örnek", "Dikkat", "Uyarı", "Soru", "Cevap", "Özet",
#   "Başlık", "Konu" gibi 20 yaygın başlık sözcüğü istisna listesinde).
is_dialog(text: str) -> bool            # ≥ 2 farklı konuşmacı (anlatıcı sayılmaz)
speakers_of(turns: list[Turn]) -> list[str]   # ilk görülme sırasıyla, tekil
plan_turn_pauses(turns: list[Turn], durations_s: list[float], seed: int | None = None) -> list[int]
# Sıralar arası ms: aynı konuşmacı devam → 450; konuşmacı değişimi → 260 (soru→cevap 200, "!"→ 230, "..." sonrası 520,
# uzun önceki sıra (>6 sn) +80); ±15 % jitter (seed ile belirlenimci); son sıra 0; 120–1500 arasına sıkıştır.
merge_turn_report(turns, starts_s: list[float], ends_s: list[float], voice_names: dict[str, str]) -> list[dict]
# [{index, speaker, voice_name, text, start, end}]
```

## 2. `nonverbal.py` — gerçek tepki kayıtları (gülme, iç çekme…)

```python
NONVERBAL_KEYS: tuple[str, ...]  # kaydedilebilir anahtarlar: "gülme","kahkaha","kıkırdama","iç çekme","hmm","of",
                                 # "nefes verir","öksürür","boğaz temizler","esner","ağlar","şaşırır","hıh","mmm","cık"
NONVERBAL_SCRIPTS: dict[str, str]  # anahtar → Türkçe kayıt yönergesi ("Doğal, içten bir kahkaha at — 1–3 sn")
sample_key(tag: str) -> str | None   # etiket/eş ad → anahtar ("laughs"→"gülme", "güler"→"gülme", "kıkırdar"→"kıkırdama")
prepare_nonverbal(src: Path, dst: Path, sr: int = 24000) -> float
# ffmpeg/librosa ile mono sr'ye çevir, -40 dB eşikle kırp, en fazla 3.0 sn (en yüksek enerjili pencere), 15 ms fade,
# RMS -22 dBFS; dst'ye yaz; süre (sn) döner. 0.15 sn'den kısaysa ValueError("Kayıt çok kısa").
render_nonverbal(path: Path, sr: int, target_rms_db: float = -22.0, seed: int | None = None) -> np.ndarray
# yükle, sr eşle, hedef RMS (±1.5 dB seed'li jitter), tempo ±3 % ve perde ±0.3 yarım ton mikro varyasyon (ffmpeg varsa
# rubberband/asetrate+atempo, yoksa yalnızca seviye) → aynı gülme iki kez birebir aynı duyulmaz; 10 ms fade.
db_key(key: str) -> str   # "nv:gülme"  (voice_samples.emotion sütununda bu önekle saklanır)
is_db_key(s: str) -> bool ; key_of_db(s: str) -> str
```

## 3. `emotion.py` — duygu yoğunluğu, karışım, satır içi kontroller (mevcut dosya genişler)

`Segment` yeni alanlar: `nonverbal: str | None = None` (keep_nonverbal=True iken "gülme" gibi anahtar; text ""),
`intensity: float = 1.0` (0.5–1.6), `blend: list[str] = []` (ikincil duygular), `rate: float | None = None`
(`[hız:0.9]`, 0.7–1.3), `pitch: float | None = None` (`[perde:+1]`, yarım ton, −4…+4), `speaker: str | None = None`
(`[ses:Ad]` — yalnızca parse edilir), `arc_to: str | None = None` (`[sakinleşerek]`, `[heyecanlanarak]` → bölüm
boyunca hedef duyguya kayış; engine cümle cümle ara değer alır).

```python
parse_tagged_text(text: str, keep_nonverbal: bool = False) -> list[Segment]   # eski çağrı aynı sonucu verir
# Yoğunluk sözdizimi: "[heyecanlı:1]" 0.7, ":2" 1.0, ":3" 1.4; "[biraz X]"/"[hafif X]" 0.65; "[çok X]" 1.35; "[aşırı X]" 1.6
# Karışım: "[üzgün+umutlu]" → emotion "üzgün", blend ["umutlu"]
# Arc: "[heyecanlı→sakin]" ya da "[sakinleşerek]" (sakin), "[heyecanlanarak]" (heyecanlı), "[yumuşayarak]" (samimi),
#      "[sertleşerek]" (kızgın), "[hüzünlenerek]" (üzgün)
effective_profile(name: str | None, intensity: float = 1.0, blend: list[str] | None = None) -> EmotionProfile | None
# ex = 0.5 + (ex-0.5)*intensity (0.25–0.95), cfg = 0.5 + (cfg-0.5)*intensity (0.3–0.7), temp aynı, speed = 1+(speed-1)*intensity,
# pause_mul = 1+(pause_mul-1)*intensity, out_gain*intensity; blend: birincil %70 + ikincil %30 (sayısal alanlar), name
# birincilden, label "Üzgün + Umutlu".
interpolate_profile(a: EmotionProfile | None, b: EmotionProfile | None, t: float) -> EmotionProfile  # arc için
plan_emphasis(text: str, words: list[str]) -> list[tuple[str, bool]]
# metni vurgulu sözcük sınırlarından parçalar: [("Bu", False), ("çok", True), ("önemli.", False)] — noktalama korunur,
# sözcük tr_lower ile eşleşir, boş/eşleşmeyen → [(text, False)].
```
`test_text.py` ve mevcut `test_emotion.py` aynen geçmeli.

## 4. `enhance.py` — referans kaydı iyileştirme

```python
should_enhance(analysis: dict | None) -> tuple[bool, list[str]]   # (öneri, nedenler: ["noisy","hum","dc_offset","too_quiet"])
enhance_reference(wav: np.ndarray, sr: int, analysis: dict | None = None, *, denoise: bool = True, dehum: bool = True,
                  declick: bool = True, highpass_hz: int = 70, target_dbfs: float = -20.0, max_reduction_db: float = 12.0
                  ) -> tuple[np.ndarray, dict]
# rapor: {"applied": [...], "noise_reduction_db": float, "hum_hz": 50|60|None, "clicks_removed": int, "gain_db": float}
# denoise: STFT (1024/256) spektral kapı; gürültü profili = en sessiz %10 kare (ya da analysis.noise_floor); kapı eşiği
#   profil + 6 dB; yumuşatma (zaman 3 kare, frekans 5 bin); azaltma en çok max_reduction_db (yapaylık sınırı); konuşma
#   karelerinde harmonikleri koru (eşik üstü binler dokunulmaz).
# dehum: 40–70 Hz arası en belirgin tepe (komşulara göre ≥ 12 dB) → 50/60 Hz + 2 harmonik için dar notch (Q=30).
# declick: türevde |x'| > 8σ olan noktalar → 1 ms komşulukta medyan/doğrusal yama.
# dc: ortalama çıkar; highpass butter 2. derece; target_dbfs RMS; tepe -1 dB.
# Çıktı uzunluğu girdiyle aynı; float32; NaN yok. Çok kısa (<0.3 sn) girdi: olduğu gibi + applied=[].
quality_delta(before: dict, after: dict) -> int   # analysis.quality_score farkı (iyileştirme kabul ölçütü: ≥ +3)
```

## 5. `qc.py` — üretilen parçanın kalite kontrolü

```python
check_chunk(wav: np.ndarray, sr: int, text: str, *, expected_cps: float | None = None) -> dict
# {"score": 0–100, "ok": bool (≥ 60), "decision": "accept"|"retry_seed"|"retry_stable"|"trim",
#  "reasons": [{"code","message"}], "metrics": {duration, cps, silence_ratio, dropouts, repeats, clipping, buzz, tail_silence}}
# Kodlar: too_long (cps < 6 → halüsinasyon, retry_seed/trim), too_short (cps > 28, retry_seed), silence (sessizlik
#   oranı > 0.45, retry_seed), dropout (konuşma ortasında ≥ 250 ms sessiz boşluk sayısı ≥ 2, retry_stable), repeat
#   (zarf otokorelasyonunda 0.6–3 sn gecikmede tepe > 0.8 → tekrar/takılma, retry_seed), clipping (> 0.001, trim/level),
#   buzz (4–8 kHz'de dar bant sürekli tepe ya da 50/100 Hz hum, retry_stable), tail (sondaki sessizlik > 600 ms → trim).
# expected_cps verilmişse too_long/too_short eşikleri ona göre (±45 %).
estimate_cps(samples: list[tuple[int, float]]) -> float | None   # (karakter, saniye) geçmişinden medyan, ≥ 3 örnekle
trim_tail(wav: np.ndarray, sr: int, max_tail_ms: int = 250) -> np.ndarray
pick_best(reports: list[dict]) -> int    # en yüksek score; eşitlikte ilk
```

## 6. `timing.py` — zaman çizelgesi ve altyazı

```python
build_timeline(chunks: list[dict], pauses_ms: list[int], sr: int, *, lead_in_ms: int = 0,
               extra_before_ms: list[int] | None = None) -> list[dict]
# chunks[i] = {"text", "duration" (sn), "emotion", "speaker"?}; i. parçadan sonra pauses_ms[i]; extra_before_ms[i]
# (nefes gibi) parçadan ÖNCE eklenir. Dönüş: [{"index","start","end","text","emotion","speaker","words":[{"word","start","end"}]}]
# Sözcük zamanları: parça süresi sözcüklerin hece sayısına (tr.count_syllables; 0 heceli sözcük 1 sayılır) orantılı
# dağıtılır; noktalama sözcüğe yapışık kalır; sözcükler arası 0 boşluk.
to_srt(timeline: list[dict], *, max_chars: int = 42, max_lines: int = 2, max_duration_s: float = 7.0) -> str
# Uzun cümleler sözcük sınırından satırlara/bloklara bölünür (blok süresi sözcük zamanlarından); SRT zaman biçimi
# "00:00:01,250"; Türkçe karakterler olduğu gibi; sonda boş satır.
to_vtt(timeline: list[dict], **kw) -> str      # "WEBVTT" başlığı, nokta ondalık
to_json(timeline: list[dict]) -> str
```

## 7. `consistency.py` — parçalar arası tını/seviye tutarlılığı

```python
ltas(wav: np.ndarray, sr: int, n_fft: int = 2048) -> np.ndarray      # dB, 1/3-oktav yumuşatılmış, uzunluk n_fft//2+1
match_timbre(piece: np.ndarray, sr: int, target_ltas: np.ndarray, *, max_db: float = 3.0, strength: float = 0.7,
             lo_hz: int = 150, hi_hz: int = 8000) -> np.ndarray
# parçanın LTAS'ını hedefe yaklaştıran yumuşak EQ (fark × strength, ±max_db'ye sıkıştır, lo/hi dışında 0); STFT
# çarpımsal düzeltme + ISTFT; uzunluk korunur; sessiz parçada dokunma.
align_loudness(pieces: list[np.ndarray], *, max_jump_db: float = 4.0, step_db: float = 2.0) -> list[np.ndarray]
# ardışık parçalar arasında RMS sıçraması > max_jump_db ise ikinci parçayı step_db kadar yaklaştır (duygu farkını
# tamamen silmez); tek geçiş, soldan sağa.
measure_f0_median(wav: np.ndarray, sr: int) -> float | None
correct_pitch_drift(piece: np.ndarray, sr: int, target_hz: float, *, max_semitones: float = 2.0, threshold: float = 1.0
                    ) -> tuple[np.ndarray, float]   # (ses, uygulanan yarım ton); |sapma| ≤ threshold → dokunma; ffmpeg yoksa dokunma
```

## 8. `lexicon.py` — telaffuz sözlüğü, satır içi okunuş, günlük Türkçe

```python
LEXICON_PATH = config.DATA_DIR / "lexicon.json"            # {"word": "reading", ...}
voice_lexicon_path(voice_id) -> Path                         # config.VOICES_DIR / f"{voice_id}.lexicon.json"
list_entries(voice_id: str | None = None) -> list[dict]      # [{"word","reading","scope":"global"|"voice"}] birleşik
set_entry(word: str, reading: str, voice_id: str | None = None) -> dict
delete_entry(word: str, voice_id: str | None = None) -> bool
apply_lexicon(text: str, lang: str = "tr", voice_id: str | None = None) -> str
# textnorm'dan ÖNCE; sözcük sınırı, tr_lower eşleşme, en uzun anahtar önce, baş harf büyüklüğü korunur; ses sözlüğü
# genel sözlüğü ezer; textnorm.DEFAULT_PRONUNCIATIONS'a dokunmaz (o ayrıca çalışır).
apply_inline_readings(text: str) -> str     # "{Claude|Klod}" → "Klod"; "{Klod}" → "Klod"; iç içe yok; etiketlere dokunmaz
CHAT_ABBREV: dict[str, str]                 # tmm→tamam, nbr→naber, slm→selam, mrb→merhaba, tşk/tşkr/tsk→teşekkürler,
                                            # kib→kendine iyi bak, bb→bay bay, msj→mesaj, tlf→telefon, grs→görüşürüz,
                                            # iyi gcl→iyi geceler, nsl→nasıl, nslsn→nasılsın, bgn→bugün, yrn→yarın,
                                            # şmd→şimdi, hyr→hayır, evt→evet, ok→okey, cnm→canım, knk→kanka, abi/abe→abi,
                                            # inş→inşallah, mşl→maşallah, aeo→allaha emanet ol, sa (tek başına, cümle
                                            # başı)→selamün aleyküm, as (tek başına, cümle başı)→aleyküm selam
expand_chat_speak(text: str) -> str         # kelime sınırı, tr_lower; "sa"/"as" yalnızca tek sözcüklük cümle ya da satır başı
add_fillers(text: str, rate: float = 0.08, seed: int | None = None, style: str = "sohbet") -> str
# konuşma dolguları: cümle başı "Yani, " / "Hani, " / "İşte, " / "Şey, " / "Ya, "; virgülden sonra "yani"; cümle sonu
# " ya" (yalnızca ünlem/düz cümle, soruya değil); en fazla her 4 cümlede 1; aynı dolgu art arda yok; [etiket] içine
# ve tırnak içine dokunma; haber/belgesel/sesli-kitap/eğitim stillerinde hiç ekleme (style parametresine göre);
# seed belirlenimci; rate 0 → değişmez; idempotent değil ama ikinci uygulama dolgu olan cümleye tekrar eklemez.
```
Ek: `backend/tests/data/tr_corpus.jsonl` — 100+ satır `{"text": …, "expect": [...], "reject": [...], "note": …}`
(normalize + colloquial light + lexicon zinciri) ve `tests/test_corpus.py` (satır satır parametreli).

## 9. HTTP API (entegrasyonda uygulanır — arayüz buna göre yazılır)

`POST /api/tts` ek alanlar: `speakers: {"Ayşe": "<voice_id>", ...} | null` (verilirse ve metin diyalogsa diyalog modu;
anlatıcı için `narrator_voice_id`), `consistency: bool=true`, `qc: bool=true`, `fillers: bool=false`,
`chat_speak: bool=true`, `subtitles: bool=true` (zaman çizelgesi üretilir).
Sonuç `params` ek: `turns: [{index, speaker, voice_name, text, start, end}]` (diyalogda), `qc: [{index, score, decision,
reasons}]`, `timeline: [...]`, `consistency: {"timbre_db": float, "loudness_steps": int}`, `nonverbal_used: ["gülme", …]`.
- `GET /api/generations/{id}/subtitles?format=srt|vtt|json` → dosya (Content-Disposition)
- `GET /api/lexicon?voice_id=` → entries; `PUT /api/lexicon {word, reading, voice_id?}`; `DELETE /api/lexicon?word=&voice_id=`;
  `POST /api/lexicon/test {text, voice_id?, language?}` → `{normalized: str, changes: [...]}`
- `POST /api/voices/{id}/nonverbal` form `tag`, `file` → ses (samples listesinde `kind: "nonverbal"`, `emotion: "gülme"`);
  `DELETE /api/voices/{id}/nonverbal/{tag}`
- `POST /api/voices/{id}/enhance` → `{before: analysis, after: analysis, report, applied: bool}` (puan ≥ +3 ise uygular,
  `.orig.wav` yedeği tutar; `force=true` form ile her durumda); `POST /api/voices/{id}/enhance/undo`
- `GET /api/voices/{id}` → `samples[]` her örnek `kind: "emotion"|"nonverbal"` ve `emotion` (nv: öneksiz)
- `GET /api/health` → `features` ek: `dialog, subtitles, lexicon, nonverbal, enhance, consistency, qc, fillers, emphasis,
  intensity`; `tags.nonverbal_recordable: [{key, label, script}]`; `tags.intensity: [{suffix,label}]`

## 10. Arayüz sözleşmesi (`api.js`'e eklenecekler — adlar birebir)

```js
api.tts(payload /* + speakers, narrator_voice_id, consistency, qc, fillers, chat_speak, subtitles */, onProgress)
api.subtitles(genId, format)              // GET …/subtitles?format=  → blob indir (Promise<void>)
api.subtitleText(genId, format)           // → metin (önizleme için)
api.lexicon(voiceId?)                     // GET
api.setLexicon(word, reading, voiceId?)   // PUT
api.deleteLexicon(word, voiceId?)         // DELETE
api.testLexicon(text, voiceId?, language?)// POST /api/lexicon/test
api.addNonverbal(voiceId, tag, file)      // POST
api.deleteNonverbal(voiceId, tag)         // DELETE
api.enhanceVoice(voiceId, force=false)    // POST
api.undoEnhance(voiceId)                  // POST
```
Sekmeler: `Seslendir · Diyalog · Sesler · Telaffuz · Dönüştür · Geçmiş` (App.jsx; bileşenler `./components/Dialog`,
`./components/Lexicon`). Diyalog bileşeni `api.tts` ile `speakers` gönderir.
