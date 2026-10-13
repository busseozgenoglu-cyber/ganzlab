# SesKlon v5 — 3. dalga sözleşmesi: model arka uçları, kıyaslama ve ince ayar hattı

Bu belge 3. dalganın (10 paralel ajan) **dosya sahipliğini ve arayüzlerini** sabitler. Önceki dalgalar:
`docs/SOZLESME.md` (v3) ve `docs/SOZLESME2.md` (v4). Oradaki genel kurallar aynen geçerlidir:

* Her şey Türkçe: kod yorumları, docstring'ler, log/hata mesajları, test adları ve belgeler. Küçük harfe
  çevirme asla `str.lower()` ile değil `app.tr.tr_lower` ile yapılır (İ/ı sorunu).
* Testler `backend/tests/` altında pytest ile, **torch / chatterbox / mlx / f5_tts / TTS kurulu olmadan** geçer.
  Gerçek çerçeve gerektiren kod yolları testte `sys.modules`'a sahte modül koyularak (monkeypatch) denenir.
* Sahiplik dışındaki dosyalara dokunulmaz; ortak bir dosyada değişiklik gerekiyorsa not bırakılır, entegrasyon
  bunu yapar.
* Her ajan yalnızca kendi testlerini çalıştırır (`cd backend && python -m pytest -q -p no:warnings tests/test_X.py`),
  bitince tüm paketi entegrasyon çalıştırır.

## 1. Neden bu dalga?

Gerçek model (Chatterbox Multilingual V3, M2 Pro / mps) Türkçede **robotik ve duygusuz** çıktı verdi: tonlama
aralığı 13,5 yarım ton (Gemini TTS 17,6); `exaggeration`/`cfg_weight` ayarları aralığı değiştirmedi; hız gerçek
zamanın 4,6 katı. Ön/son işleme katmanları (v3–v4) bunu çözmez; düzlük modelin Türkçe prozodi önceliğinden gelir.
Karar: Chatterbox kalır (MIT, duygu kontrolü, VC), ama

1. **ölçüm standartlaşır** (`app.bench`): her değişiklik aynı Türkçe cümle setiyle, aynı pyin ölçümüyle sayıya döner;
2. **model takılabilir olur** (`app.backends`): PyTorch / MLX (Apple Silicon hız) / F5-TTS-Türkçe / XTTS A/B;
   ince ayarlı T3 ağırlıkları ortam değişkeniyle takılır;
3. **ince ayar hattı** (`finetune/`): kayıt senaryoları → veri hazırlama → LoRA eğitimi → kabul ölçütü.

## 2. Arka uç arayüzü (`backend/app/backends/`) — HAZIR, değiştirilmez

`backends/__init__.py` (kayıt defteri, `BaseBackend`, `BackendUnavailable`) ve `backends/fake.py` entegrasyon
tarafından yazıldı. Motor (`engine.Engine.tts()`) modeli `backends.create(name, device)` ile kurar ve modelle
yalnızca şu yüzden konuşur:

```python
model.sr                       # int
model.generate(text, language_id="tr", exaggeration=0.5, cfg_weight=0.5, temperature=0.8,
               audio_prompt_path=None, emotion=None)   # → np.ndarray float32 mono (ya da torch tensörü)
model.conds                    # (isteğe bağlı) Chatterbox klon koşulları; motor varsayılanı geri yükler
model.seed(int)                # (isteğe bağlı) çerçevenin kendi tohumu
```

Kurallar:

* `generate` **açık parametrelerle** tanımlanır, `**kwargs` YOK. Motor `inspect.signature` ile bakıp yalnızca
  tanımlı parametreleri geçirir; F5 `exaggeration` bilmiyorsa o parametreyi hiç tanımlamaz.
* `emotion` (parça duygusu, örn. `"mutlu"`, `None`) motor tarafından her çağrıda gönderilir; yalnızca bunu
  tanımlayan arka uçlar alır. Chatterbox arka ucu `config.T3_EMOTION_TAGS` açıkken metnin başına `[mutlu] ` ekler
  (ince ayar verisiyle aynı biçim, bkz. §5).
* Sınıf öznitelikleri: `name`, `label`, `license` (Türkçe, örn. `"MIT — ticari kullanım serbest"`),
  `commercial: bool`, `supports_emotion_controls: bool`, `needs_torch: bool`, `required_modules: tuple[str, ...]`
  (find_spec ile denetlenir), `install_hint: str` (pip komutu), `model_id` (yükleme sonrası gerçek kimlik), `sr`.
* `available()` modül yüklemez (ucuz). `__init__(device=...)` ağırlıkları yükler; yüklenemezse Türkçe mesajlı
  `BackendUnavailable` ya da `RuntimeError` fırlatır.
* Çıktıyı `BaseBackend.to_numpy` ile mono float32'ye çevirir; örnekleme hızı `self.sr`'ye yazılır (gerçek değer).
* Ortam değişkenleri `app/config.py`'de hazır: `TTS_BACKEND`, `T3_FINETUNED`, `CHATTERBOX_LOCAL_DIR`,
  `T3_EMOTION_TAGS`, `MLX_MODEL`, `F5_TR_CKPT`, `F5_TR_VOCAB`, `XTTS_MODEL`.
* Sahte arka uç (`fake`): `exaggeration` tonlama aralığını açar (0 → ~3, 0.5 → ~9, 1.0 → ~15–19 yarım ton),
  `audio_prompt_path` temel perdeyi belirler. Testlerde ve kıyaslama kuru çalışmasında kullanılır.

| Ajan | Dosya | İçerik |
|---|---|---|
| A1 | `backends/chatterbox.py`, `tests/test_backends.py` | PyTorch Chatterbox: `from_pretrained(device, t3_model)` ya da `CHATTERBOX_LOCAL_DIR` → `from_local`; `T3_FINETUNED` → safetensors/pt'yi `model.t3`'e `strict=False` yükle (eksik/fazla anahtar sayısını logla, `t3.`/`module.` öneklerini soy); `conds` özelliği iç modele delege; `emotion` etiketi; `seed`. Testler: kayıt defteri (adlar, takma adlar, describe, bilinmeyen ad), sahte arka uç (aralık ↑ exaggeration, referans → perde), motorun sahte arka uçla uçtan uca üretimi (`Engine(backend="fake").synthesize`), chatterbox adaptörü sahte `chatterbox.mtl_tts` + sahte `torch`/`safetensors` modülleriyle. |
| A2 | `backends/chatterbox_mlx.py`, `tests/test_backend_mlx.py` | mlx-audio: `from mlx_audio.tts.utils import load_model`; `load_model(config.MLX_MODEL)`; `model.generate(text, ref_audio=…, lang_code/language=…, exaggeration=…, cfg_weight=…, temperature=…)` üreteç → `result.audio` (mx.array) parçalarını birleştir. Gerçek imzayı WebFetch ile mlx-audio deposundan doğrula (chatterbox model dosyası + README) ve parametre adlarını `inspect.signature` ile uyarlayarak geçir (bilinmeyen adı gönderme). `needs_torch=False`, `seed` → `mx.random.seed`. |
| A3 | `backends/f5_turkish.py`, `tests/test_backend_f5.py` | F5-TTS Türkçe (marduk-ra/F5-TTS-Turkish, CC-BY-NC — `commercial=False`): `from f5_tts.api import F5TTS`; `F5TTS(model="F5TTS_v1_Base", ckpt_file=config.F5_TR_CKPT, vocab_file=config.F5_TR_VOCAB, device=…)`; `infer(ref_file, ref_text, gen_text, seed=…)` → `(wav, sr, spect)`. `ref_text` boşsa F5 ASR çalıştırır (yavaş) — `ref_text` parametresi `generate`'te açık (motor göndermez, bench gönderebilir). `audio_prompt_path` zorunlu (yoksa Türkçe hata). Gerçek API'yi WebFetch ile doğrula. |
| A4 | `backends/xtts.py`, `tests/test_backend_xtts.py` | Coqui XTTS-v2 (CPML, ticari değil): `from TTS.api import TTS`; `TTS(config.XTTS_MODEL).to(device)`; `tts(text, speaker_wav=…, language="tr")` → float listesi, sr 24000 (`synthesizer.output_sample_rate`). Python ≥ 3.12 için `coqui-tts` çatalını kurulum ipucunda belirt. `audio_prompt_path` zorunlu. |

## 3. Kıyaslama betiği (`backend/app/bench.py`) — A5

Komut satırı (backend klasöründen):

```
python -m app.bench --backend fake --out sonuc.json                 # cümle seti: data/bench_tr.txt
python -m app.bench --backend chatterbox --ref ses.wav --exaggeration 0.8 --cfg-weight 0.3 --out b.json
python -m app.bench --backend chatterbox --ref ses.wav --pipeline --out c.json   # tüm motor zinciri (prozodi vb.)
python -m app.bench --reference-only sakin.wav coskulu.wav           # model yok: referans kayıtlarının ifade ölçümü
python -m app.bench --compare a.json b.json                          # iki sonucun farkı (tablo)
```

Seçenekler: `--sentences DOSYA`, `--limit N`, `--repeat N` (aynı cümleyi N kez, medyan), `--language tr`,
`--exaggeration/--cfg-weight/--temperature/--seed`, `--emotion-tags` (cümle etiketlerini metinde bırak),
`--pipeline` (Engine.synthesize ile; `--style` geçer), `--device`, `--out`, `--quiet`.

Cümle dosyası `backend/data/bench_tr.txt`: `kategori|cümle` satırları (`#` yorum). En az 24 cümle; kategoriler:
nötr, soru, ünlem, üzgün, mutlu, heyecanlı, kızgın, fısıltı, sakin, uzun (≥ 120 kar.), sayı/kısaltma
(normalizasyon), günlük (napıyosun vb.). Cümleler `[duygu]` etiketi TAŞIMAZ; etiket `--emotion-tags` ile kategoriden
üretilir (nötr/soru/ünlem/uzun/sayı/günlük → etiket yok).

Her cümle için ölçülenler (`app.analysis.analyze_array` — pyin, p5–p95; referansla aynı kulak):
`duration_s`, `gen_s`, `rtf` (= gen_s / duration_s; 1'in altı gerçek zamandan hızlı), `f0` (median_hz, min_hz,
max_hz, range_semitones, std_semitones, voiced_ratio), `syllables_per_sec`, `chars_per_sec`, `pauses`
(count, median_ms), `dynamic_range_db` (konuşma karelerinin RMS dB'sinde p95−p5; 25 ms kare, 10 ms atlama —
bench kendi hesaplar), `qc` (`app.qc.check_chunk` → score, decision, reasons[:2]), `speech_ratio`.

Özet (`summary`): `n`, `rtf_mean`, `rtf_median`, `range_semitones_median`, `range_semitones_mean`,
`std_semitones_median`, `syllables_per_sec_mean`, `dynamic_range_db_median`, `qc_score_mean`, `qc_fail_count`
(decision ≠ accept/trim), `pauses_per_sentence`, `verdict` (Türkçe): aralık medyanı ≥ 17 → "ifadeli — Gemini TTS
düzeyi", 14–17 → "orta — referans/ayar iyileştirmesi deneyin", < 14 → "düz (robotik) — ince ayar gerekli",
`recommendations` listesi (Türkçe cümleler; örn. RTF > 2 ise "MLX arka ucunu ya da qc=false deneyin").

JSON çıktı: `{"version": 1, "created": ISO, "backend": model.info(), "settings": {...}, "sentences": [...],
"summary": {...}}`. Konsola Türkçe tablo (cümle kısaltılmış 40 kar., aralık, std, hece/sn, RTF, QC) ve özet.
`--compare`: iki özetin yan yana tablosu + fark sütunu + cümle bazında aralık farkı; "kazanan" satırı.
`--reference-only`: her dosya için aralık/std/hece/sn/duraklama ve yorum ("bu referans ifadeli / düz; klon
genelde referansın aralığının altında kalır, ≥ 16 yarım ton hedefleyin").

Modül API'si (testler ve `finetune/degerlendir.py` kullanır):

```python
from app.bench import load_sentences, run_bench, compare, analyze_files, summarize
run_bench(backend_name, sentences, *, ref=None, settings=None, pipeline=False, repeat=1, device="cpu",
          emotion_tags=False, progress=None, model=None) -> dict     # model verilirse yeniden yüklenmez
compare(a: dict, b: dict) -> dict      # {"summary": [...satırlar...], "sentences": [...], "winner": "a"|"b"|"berabere"}
analyze_files(paths) -> list[dict]
```

Testler (`tests/test_bench.py`): sahte arka uçla 3 cümle → şema tam; exaggeration 0.2 vs 1.0 → aralık medyanı
anlamlı artar ve `compare` kazananı doğru verir; `--reference-only` sentetik WAV; `--pipeline` sahte arka uçla
`Engine` zincirinden geçer; CLI `main([...])` dönüş kodu 0; cümle dosyası ≥ 24 satır ve tüm kategoriler var.

## 4. Kayıt senaryoları (`finetune/senaryo.py`, `finetune/cumleler/`) — A6, A9, A10

**Cümle bankası** (`finetune/cumleler/<duygu>.txt`, A9+A10): her dosya 30 cümle, satır başına bir cümle; dosyanın
başında `# yönerge:` satırı (oyuncuya tek cümlelik oynama talimatı) ve `# örnek:` (nasıl söylenmeli). Cümleler
**doğal, günlük Türkçe**: 4–20 sözcük, çeşitli uzunluklar, soru/ünlem/üç nokta çeşitliliği, duyguyu içerikle de
taşıyan (kızgın dosyada kızgın içerik), tekrar yok, marka/kişi adı yok, sayı ve kısaltma az (birkaç tane olsun:
"saat 3'te", "2 kg"). Duygular ve sahipleri:

* A9: `normal`, `mutlu`, `heyecanlı`, `üzgün`, `kızgın`, `şaşkın`, `korkmuş`, `sakin`, `ciddi`, `samimi`
* A10: `fısıltı`, `alaycı`, `nazik`, `gergin`, `umutlu`, `otoriter`, `romantik`, `nostaljik`, `gururlu`, `sıkılmış`

**senaryo.py** (A6): bankayı okur; `--oturum N` kadar oturuma böler (her oturum ≤ 25 dk okuma ≈ 120 cümle);
`--metin dosya.txt` ile kullanıcının kendi metnini (kitap, senaryo) cümlelere böler (`app.engine.split_text`
ya da basit noktalama bölme) ve `normal` duyguya ekler; `--duygular mutlu,üzgün` süzer; `--tekrar 2` her cümleyi
iki yoğunlukta (`hafif`, `güçlü`) listeler. Çıktı: `senaryo/<oturum_01>.md` (okuma senaryosu: duygu başlığı,
yönerge, numaralı satırlar, kayıt adı `mutlu_0007`), `senaryo/manifest.csv` (başlık satırı `id|duygu|yogunluk|metin`),
`senaryo/OZET.md` (toplam cümle, tahmini süre: 3,5 sn/cümle × tekrar, duygu dağılımı). `--kontrol`: bankadaki
dosyaları denetler (30 satır, yönerge var, tekrar yok, ≤ 20 sözcük) ve rapor verir. Komut `python finetune/senaryo.py …`
(backend'i `sys.path`'e kendisi ekler: `Path(__file__).resolve().parents[1] / "backend"`).

## 5. Veri hazırlama (`finetune/hazirla.py`) — A7

Girdi: `kayitlar/` klasörü + `manifest.csv` (§4 biçimi) **ya da** `kayitlar/*.wav` + aynı adlı `.txt` transkript.
Adımlar (hepsi `app` modülleriyle): oku (`app.audio` / soundfile; ffmpeg ile her biçim), mono 24 kHz'e çevir
(`--sr 24000`; eğitim deposu zaten 16 kHz'e indirir), DC/kesme kontrolü, baş-son sessizlik kırp
(`app.audio.trim_silence`, −45 dB, 40 ms pay), 10 sn'den uzun kayıtları sessizliklerden böl (3–10 sn parçalar;
bölünen metin eşlemesi yapılamıyorsa kayıt "uzun" diye reddedilir), `app.analysis.analyze_array` ile denetle ve
reddet: SNR < 20 dB, kırpılma > %0,1, süre < 1 sn ya da > 12 sn, konuşma oranı < 0,3; metni
`app.textnorm.normalize` ile normalize et (raw_text = manifestteki, normalized_text = normalize edilmiş);
`--etiket` ile her iki sütunun başına `[duygu] ` ekle (ince ayarda duygu koşullaması; `normal` etiket almaz).
Çıktı: `MyTTSDataset/wavs/<id>.wav`, `MyTTSDataset/metadata.csv` (LJSpeech: `filename|raw_text|normalized_text`,
başlıksız, `filename` uzantısız), `--dogrulama 0.05` ile `metadata_val.csv`, `MyTTSDataset/rapor.json`
(duygu başına dakika, toplam saat, reddedilenler + nedenleri, duygu başına medyan `range_semitones` ve
`std_semitones` — "veri ifadeli mi?" denetimi: duygu başına medyan aralık < 12 yarım tonsa uyarı) ve konsolda
Türkçe özet. Yeterlilik eşiği: toplam ≥ 30 dk zorunlu, ≥ 3 saat önerilir (uyarı metinleri).

## 6. Eğitim ve değerlendirme (`finetune/egit.sh`, `finetune/degerlendir.py`, `finetune/README.md`) — A8

`egit.sh`: `gokhaneraslan/chatterbox-finetuning` deposunu `finetune/chatterbox-finetuning/` altına klonlar (varsa
günceller), sanal ortam/`pip install -r requirements.txt`, `src/config.py`'yi Python ile yamalar
(`is_turbo=False`, `is_lora=True`, `ljspeech=True`, `json_format=False`, veri yolu, `lora_r`, `lora_alpha`, epoch,
batch, `grad_accum` — gerçek anahtar adlarını depodaki `src/config.py`'den WebFetch ile doğrula; yoksa sed yerine
"anahtar bulunamadı" uyarısı), `python setup.py` → `python train.py` → `python merge_lora.py`; sonunda
`T3_FINETUNED=<yol>` ile SesKlon'un nasıl başlatılacağını yazdırır. Ortam değişkenleriyle ayarlanır
(`VERI`, `EPOCH`, `BATCH`, `LORA_R`, `CIHAZ`). `set -euo pipefail`, her adım Türkçe log. OOM ipucu.

`degerlendir.py`: `app.bench.run_bench` ile temel (`chatterbox`) ve ince ayarlı (`T3_FINETUNED` ortam değişkeni ile
ikinci bir Engine/arka uç) modeli aynı cümle seti ve referansla koşturur, `compare` ile karşılaştırır; kabul
ölçütü: aralık medyanı ≥ 17 yarım ton VE `qc_fail_count` artmamış VE hece/sn 3,5–6,5 arasında → "KABUL";
aksi hâlde "RET" + nedenler. `--temel a.json --ince b.json` ile hazır sonuçları da karşılaştırır (model yüklemeden;
test böyle çalışır). Çıkış kodu: kabul 0, ret 2.

`README.md` (Türkçe): neden ince ayar, veri gereksinimi (3–5 saat ifadeli Türkçe; 1 kişi; duygu dağılımı),
kayıt rehberine bağlantı (`docs/KAYIT_REHBERI.md`), adım adım komutlar (senaryo → kayıt → hazirla → egit →
degerlendir → `T3_FINETUNED` ile çalıştır), donanım/süre/maliyet tahmini (LoRA, 3 saat veri: tek 24 GB GPU
≈ 2–4 saat; Apple Silicon'da eğitim önerilmez), lisans notları (Chatterbox MIT; TurEV-DB/Turk-SER akademik;
Gemini/ElevenLabs çıktısıyla eğitmek ToS ihlali — kullanılmaz), sık sorunlar (OOM → LoRA/batch; tokenizer;
mps).

## 7. Entegrasyonun yapacakları (ajanlar dokunmaz)

`engine.py` (motor `emotion` parametresini zaten gönderiyor; `T3_EMOTION_TAGS` config'de hazır), `main.py` sağlık ucu,
`README.md`, `CHANGELOG.md`, `docs/API.md`, `docs/SSS.md`, arayüzde arka uç adının gösterilmesi, sürüm 4.1.0,
CI (`.github/workflows/test.yml`'de finetune testleri zaten `backend/tests` altında olduğu için ek adım yok).
