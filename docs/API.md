# SesKlon HTTP API

Web arayüzü de bu API'yi kullanır; arayüzde yapılabilen her şey API ile de yapılabilir. Örneklerdeki adres
`http://localhost:8000`'dir.

- **Etkileşimli belge (Swagger):** `http://localhost:8000/api/docs` — istekleri tarayıcıdan deneyebilirsiniz.
- **OpenAPI şeması:** `http://localhost:8000/api/openapi.json`

**İçindekiler:** [Temel bilgiler](#temel-bilgiler) · [Uç noktalar](#uç-noktalar) · [Sistem](#sistem) · [Sesler](#sesler) ·
[Gerçek tepki kayıtları](#gerçek-tepki-kayıtları) · [Kayıt iyileştirme](#kayıt-iyileştirme) · [Metin → ses](#metin--ses) ·
[Diyalog](#diyalog) · [Üretim nesnesi](#üretim-nesnesi) · [İşler ve akış](#kuyruk-işler-ve-akış) · [Ses → ses](#ses--ses) ·
[Telaffuz sözlüğü](#telaffuz-sözlüğü) · [Altyazı](#altyazı) · [Geçmiş](#geçmiş) · [Dosyalar](#dosyalar) ·
[Analiz şeması](#analiz-şeması) · [Hata kodları](#hata-kodları) · [Sınırlar](#sınırlar-ve-davranış)

## Temel bilgiler

- İstek ve yanıt gövdeleri JSON'dur (UTF-8). Dosya yüklemeleri `multipart/form-data` ile yapılır.
- Ses dosyaları `/files/...` altından sunulur; yanıtlardaki `url` alanları bu yolları verir (sunucu adresine eklenir).
- CORS açıktır (`*`): başka bir adreste çalışan web uygulamaları da API'yi çağırabilir.
- Üretim (`/api/tts`, `/api/vc`) bir **iş kuyruğunda** yapılır: istek hemen **202** ve bir iş nesnesiyle döner, sonuç
  iş sorgulanarak alınır. Kısa işler için `"wait": true` ile sonucu tek istekte bekleyebilirsiniz.
- Kuyrukta tek işçi vardır (tek GPU); işler sırayla yapılır.

### Kimlik doğrulama

`API_KEY` ortam değişkeni doluysa `/api/health` dışındaki tüm `/api/*` istekleri bu başlığı ister:

```
X-API-Key: <anahtarınız>
```

Başlık yoksa ya da yanlışsa yanıt `401 {"detail": "Geçersiz API anahtarı"}` olur. `/api/health` herkese açıktır
(`auth_required` alanı anahtar gerekip gerekmediğini söyler). `/files/...` altındaki ses dosyaları anahtar istemez;
adları tahmin edilemeyen rastgele kimliklerdir. Sunucuyu internete açacaksanız önüne HTTPS'li ve erişim denetimli bir
ters vekil koyun.

## Uç noktalar

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/health` | Cihaz, model ve arka uç durumu, diller, etiket ve stil kataloğu, özellikler |
| POST | `/api/warmup` | Modeli yükle |
| GET | `/api/stats` | Sayılar: ses, kayıt, üretim, favori, toplam süre |
| GET | `/api/voices` | Sesler |
| POST | `/api/voices` | Yeni ses (multipart) — yanıtta `analysis` |
| GET | `/api/voices/{id}` | Ses ayrıntısı (duygu ve tepki kayıtlarıyla) |
| PATCH | `/api/voices/{id}` | Ad, not, varsayılan stil, duraklama çarpanı, dil |
| DELETE | `/api/voices/{id}` | Sesi, kayıtlarını, ses sözlüğünü ve iyileştirme yedeğini sil |
| POST | `/api/voices/{id}/samples` | Duygu kaydı ekle / değiştir (multipart) |
| DELETE | `/api/voices/{id}/samples/{emotion}` | Duygu kaydını sil |
| POST | `/api/voices/{id}/nonverbal` | Gerçek tepki kaydı ekle / değiştir (multipart: `tag`, `file`) |
| DELETE | `/api/voices/{id}/nonverbal/{tag}` | Tepki kaydını sil |
| POST | `/api/voices/{id}/enhance` | Referans kaydını iyileştir (form: `force`) |
| POST | `/api/voices/{id}/enhance/undo` | İyileştirmeyi geri al |
| GET | `/api/voices/{id}/analysis` | Sesin kayıt analizi |
| GET | `/api/voices/{id}/export` | Sesi zip olarak yedekle |
| POST | `/api/voices/import` | Zip yedeğinden ses oluştur (multipart) |
| POST | `/api/analyze` | Kaydı saklamadan analiz et (multipart) |
| POST | `/api/tts` | Metin → ses; `speakers` ile diyalog |
| GET | `/api/jobs` | Son işler |
| GET | `/api/jobs/{id}` | İş durumu, ilerleme, hazır parçalar, sonuç |
| POST | `/api/jobs/{id}/cancel` | İşi iptal et |
| POST | `/api/vc` | Ses → ses (multipart) |
| GET | `/api/lexicon` | Telaffuz sözlüğü (`voice_id` ile ses sözlüğü dahil) |
| PUT | `/api/lexicon` | Sözcük ekle / güncelle |
| DELETE | `/api/lexicon` | Sözcük sil (`word`, `voice_id`) |
| POST | `/api/lexicon/test` | Metnin modele nasıl gideceğini göster |
| GET | `/api/generations` | Geçmiş: arama, süzgeç, sayfalama |
| GET | `/api/generations/{id}/subtitles` | Altyazı indir (`format=srt\|vtt\|json\|lrc`) |
| POST | `/api/generations/{id}/favorite` | Favoriye ekle / çıkar |
| DELETE | `/api/generations/{id}` | Geçmiş kaydını ve dosyasını sil |

## Sistem

### `GET /api/health`

Arayüzün açılışta ve düzenli aralıklarla sorguladığı durum bilgisi. Docker sağlık denetimi de bunu kullanır.

```json
{
  "ok": true,
  "version": "4.1.0",
  "device": "cuda",
  "model": "chatterbox-multilingual-v3",
  "backend": "chatterbox",
  "backends": [{"name": "chatterbox", "label": "Chatterbox Multilingual (PyTorch)", "license": "MIT — ticari kullanım serbest",
                "commercial": true, "emotion_controls": true, "available": true, "reason": "kurulu"}],
  "finetuned": false,
  "model_loaded": true,
  "model_loading": false,
  "model_error": null,
  "queue_pending": 0,
  "languages": {"tr": "Türkçe", "en": "English", "de": "Deutsch"},
  "auth_required": false,
  "max_text_chars": 5000,
  "max_upload_mb": 60,
  "ffmpeg": true,
  "tags": {
    "emotions": [{"name": "heyecanlı", "label": "Heyecanlı", "aliases": ["excited", "coşkulu"], "description": "…"}],
    "nonverbal": ["gülme", "iç çekme"],
    "nonverbal_detail": [{"tag": "gülme", "reads": "Hahaha!"}],
    "nonverbal_recordable": [{"key": "gülme", "label": "Gülme", "script": "Komik bir şey hatırla ve içten, doğal bir kahkaha at — 1–3 saniye. …",
                              "aliases": ["gülme", "güler", "laughs", "…"]}],
    "pauses": ["duraklama", "nefes"],
    "pause_detail": [{"tag": "nefes", "ms": 500}],
    "timed_pause_examples": ["[500 ms]", "[1 sn]", "[1.5 sn]", "[2 saniye]"],
    "emphasis_examples": ["*çok* önemli", "[vurgu] yarın", "[vurgu: hemen şimdi]"],
    "scoped_example": "[heyecanlı: Yalnızca bu cümle heyecanlı.]",
    "intensity": [{"suffix": ":1", "label": "hafif"}, {"suffix": ":2", "label": "normal"}, {"suffix": ":3", "label": "güçlü"},
                  {"suffix": "biraz ", "label": "biraz"}, {"suffix": "çok ", "label": "çok"}],
    "arcs": [{"tag": "sakinleşerek", "to": "sakin"}, {"tag": "heyecanlanarak", "to": "heyecanlı"}],
    "controls": [{"tag": "hız:0.9", "label": "Hız"}, {"tag": "perde:+1", "label": "Perde"}, {"tag": "ses:Ad", "label": "Konuşmacı"}]
  },
  "emotion_tags": ["normal", "heyecanlı", "mutlu"],
  "styles": [{"name": "sohbet", "label": "Sohbet", "description": "Varsayılan: doğal, samimi, konuşur gibi.",
              "emotion": null, "exaggeration": 0.55, "cfg_weight": 0.45, "temperature": 0.8, "speed": 1.0,
              "pause_scale": 1.0, "colloquial": "light", "breaths": true, "punctuation_emotion": true,
              "auto_emotion": false, "aliases": ["conversational", "chat"]}],
  "colloquial_levels": ["off", "light", "full"],
  "features": {"breaths": true, "room_tone": true, "master": true, "analysis": true, "variants": true,
               "partial_preview": true, "cancel": true, "dialog": true, "subtitles": true, "lexicon": true,
               "nonverbal": true, "enhance": true, "consistency": true, "qc": true, "fillers": true,
               "emphasis": true, "intensity": true}
}
```

(Listeler kısaltıldı.) `model_error` doluysa model yüklenememiştir; metin hatanın nedenini verir.

- `tags.nonverbal_recordable`: kaydedilebilir 15 tepki — `key` (etiket anahtarı), `label` (arayüz adı), `script`
  (kayıt yönergesi), `aliases` (yüklemede kabul edilen eş adlar).
- `tags.intensity`, `tags.arcs`, `tags.controls`: yoğunluk sonekleri/önekleri, geçiş sözcükleri ve satır içi kontroller
  ([Etiketler](ETIKETLER.md)).
- `features`: v4 yetenekleri; istemci bir özelliği göstermeden önce bakabilir. `master` ffmpeg'e bağlıdır.

### `POST /api/warmup`

Model yüklü değilse arka planda yüklemeyi başlatır: `{"ok": true, "model_loaded": false, "model_loading": true}`.
`PRELOAD=1` (varsayılan) iken buna gerek yoktur.

### `GET /api/stats`

```json
{"voices": 3, "samples": 7, "generations": 128, "favorites": 9, "by_kind": {"tts": 120, "vc": 8},
 "total_duration_s": 1843.2, "total_elapsed_s": 512.7, "rtf": 0.278}
```

`rtf`: üretime harcanan süre / üretilen ses süresi (1'in altı gerçek zamandan hızlı demektir); üretim yoksa `null`.
`samples` duygu ve tepki kayıtlarını birlikte sayar.

## Sesler

### Ses nesnesi

```json
{
  "id": "a1b2c3d4e5f6",
  "name": "Buse — doğal",
  "language": "tr",
  "filename": "9f8e7d6c5b4a.wav",
  "url": "/files/voices/9f8e7d6c5b4a.wav",
  "duration": 12.4,
  "created_at": "2026-10-13T09:12:45.123456+00:00",
  "notes": null,
  "default_style": "sohbet",
  "pause_scale": 1.05,
  "enhanced": false,
  "analysis": {"quality_score": 88, "grade": "mükemmel", "…": "…"},
  "samples": [
    {"id": "0c9d8e7f6a5b", "voice_id": "a1b2c3d4e5f6", "kind": "emotion", "emotion": "üzgün",
     "filename": "1a2b3c4d5e6f.wav", "url": "/files/voices/1a2b3c4d5e6f.wav", "duration": 9.8,
     "created_at": "2026-10-13T09:20:01+00:00", "analysis": {"quality_score": 81, "grade": "iyi", "…": "…"}},
    {"id": "5b4a3c2d1e0f", "voice_id": "a1b2c3d4e5f6", "kind": "nonverbal", "emotion": "gülme",
     "filename": "7e6d5c4b3a29.wav", "url": "/files/voices/7e6d5c4b3a29.wav", "duration": 1.84,
     "created_at": "2026-10-13T09:25:40+00:00", "analysis": null}
  ]
}
```

- `duration`: kırpılıp hazırlanmış referansın süresi (en fazla `MAX_REF_SECONDS`).
- `pause_scale`: sesin kişisel duraklama çarpanı; analizdeki `pauses.scale` değerinden gelir, elle değiştirilebilir.
- `enhanced`: referans kaydı iyileştirilmiş ve özgünü yedekte ([Kayıt iyileştirme](#kayıt-iyileştirme)).
- `samples[].kind`: `emotion` (duygu kaydı; `emotion` duygu adı) ya da `nonverbal` (gerçek tepki kaydı; `emotion`
  tepki anahtarı, örn. `gülme`).
- `analysis`: [Analiz şeması](#analiz-şeması).

### `GET /api/voices`

Tüm sesler (en yeni önce), ses nesnelerinden oluşan bir dizi.

### `POST /api/voices`

`multipart/form-data` alanları:

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `name` | evet | Ses adı (en fazla 80 karakter) |
| `language` | hayır (`tr`) | Kaydın dili; `GET /api/health` → `languages` anahtarlarından biri |
| `consent` | evet | `true` olmalı: sesin size ait olduğunu ya da sahibinden izin aldığınızı onaylar |
| `file` | evet | Ses ya da video dosyası (wav, mp3, m4a, ogg, webm, mp4…); en fazla `MAX_UPLOAD_MB` |

Kayıt mono 24 kHz'e çevrilir, baştaki ve sondaki sessizlik kırpılır, uzun kayıtlarda konuşmanın en yoğun bölümü
seçilir ve seviye dengelenir. Yanıt, analizi de içeren ses nesnesidir. Kırpma sonrası 2 sn'den az konuşma kalırsa 400 döner.

```bash
curl -X POST http://localhost:8000/api/voices \
  -F name="Buse — doğal" -F language=tr -F consent=true -F file=@kayit.wav
```

### `GET /api/voices/{id}` · `DELETE /api/voices/{id}`

Ses nesnesini döndürür · Sesi, temel kaydını, iyileştirme yedeğini, tüm duygu ve tepki kayıtlarını ve ses sözlüğünü
siler (`{"ok": true}`). Geçmişteki üretimler silinmez.

### `PATCH /api/voices/{id}`

JSON gövdesinde yalnızca değiştirmek istediğiniz alanları gönderin; yanıt güncel ses nesnesidir.

| Alan | Tip | Açıklama |
|---|---|---|
| `name` | str (1–80) | Ses adı |
| `notes` | str \| null | Serbest not; boş metin notu siler |
| `default_style` | str \| null | Varsayılan stil (stil adı); `null` kaldırır |
| `pause_scale` | float 0,5–2,0 | Sesin duraklama çarpanı |
| `language` | str | Kaydın dili (`health.languages`) |

```bash
curl -X PATCH http://localhost:8000/api/voices/a1b2c3d4e5f6 \
  -H "Content-Type: application/json" -d '{"default_style": "podcast", "notes": "Mikrofon: USB, oturma odası"}'
```

### `POST /api/voices/{id}/samples` · `DELETE /api/voices/{id}/samples/{emotion}`

Duygu kaydı ekler ya da aynı duygu için var olanı değiştirir. `multipart/form-data`: `emotion` (duygu adı ya da eş
anlamlısı; `normal` olamaz) ve `file`. Silmede yol parametresi duygu adıdır. İkisi de güncel ses nesnesini döndürür.
Geçersiz duygu adında 400 ve geçerli seçeneklerin listesi döner.

```bash
curl -X POST http://localhost:8000/api/voices/a1b2c3d4e5f6/samples -F emotion=üzgün -F file=@uzgun.wav
curl -X DELETE "http://localhost:8000/api/voices/a1b2c3d4e5f6/samples/%C3%BCzg%C3%BCn"     # üzgün
```

### `GET /api/voices/{id}/analysis` · `POST /api/analyze`

Sesin kayıtlı analizini döndürür (`?refresh=true` yeniden hesaplar) · Yüklenen dosyayı **saklamadan** analiz eder
(`multipart/form-data`, alan: `file`). Arayüz, bir kayıt seçildiği anda kaliteyi göstermek için ikincisini kullanır.
Yanıt: [Analiz şeması](#analiz-şeması).

```bash
curl -X POST http://localhost:8000/api/analyze -F file=@deneme.m4a
```

### `GET /api/voices/{id}/export` · `POST /api/voices/import`

Sesi tüm duygu ve tepki kayıtları ve analizleriyle tek bir zip dosyası olarak indirir (`application/zip`; dosya adı
`Content-Disposition` başlığındadır). Zip; ses dosyalarını ve sesin bilgilerini (ad, dil, not, varsayılan stil,
duraklama çarpanı, analizler) taşıyan bir bilgi dosyasını (`"format": "sesklon-voice"`) içerir. Ses sözlüğü ve
iyileştirme yedeği pakete girmez. İçe aktarma aynı zipi `multipart/form-data` (`file`) ile alır ve yeni bir kimlikle
ses oluşturup ses nesnesini döndürür.

```bash
curl -o buse.zip http://localhost:8000/api/voices/a1b2c3d4e5f6/export
curl -X POST http://localhost:8000/api/voices/import -F file=@buse.zip
```

## Gerçek tepki kayıtları

Metinde `[gülme]` gibi bir sözsüz etiket geçtiğinde, sesin o tepki için kaydı varsa modelin "Hahaha!" okuması yerine
bu kayıt çalınır. Kayıt yönergeleri: [Kayıt rehberi → Gerçek tepki kayıtları](KAYIT_REHBERI.md#8-gerçek-tepki-kayıtları).

### `POST /api/voices/{id}/nonverbal`

`multipart/form-data`: `tag` ve `file`. Yanıt güncel ses nesnesidir (kayıt `samples` içinde `kind: "nonverbal"`).
Aynı tepki için yeni kayıt eskisinin yerine geçer.

- `tag`: 15 anahtardan biri — `gülme`, `kahkaha`, `kıkırdama`, `iç çekme`, `hmm`, `of`, `nefes verir`, `öksürür`,
  `boğaz temizler`, `esner`, `ağlar`, `şaşırır`, `hıh`, `mmm`, `cık` — ya da eş adı (`laughs`, `kahkaha atar`,
  `iç çeker`, `sighs`, `ehem`, `hı hı`…; tam liste `health.tags.nonverbal_recordable[].aliases`). "derin bir iç
  çekme" gibi niteleyiciler ve "hmmm" gibi uzatmalar da tanınır. Tanınmayan etiket → 400 ve seçenekler.
- İşleme: mono 24 kHz; yüklemenin ilk 60 sn'si incelenir; baş/son sessizlik −40 dBFS eşikle kırpılır; 3 sn'den uzunsa
  en enerjik 3 sn (sınırları sessizliğe denk gelen) seçilir; 15 ms yumuşak giriş/çıkış; seviye −22 dBFS RMS (tepe en
  çok −1 dBFS). 0,15 sn'den kısa ya da duyulur ses içermeyen kayıt → 400 (`"Kayıt çok kısa"`, `"Kayıt çok sessiz…"`).

### `DELETE /api/voices/{id}/nonverbal/{tag}`

Tepki kaydını siler (`tag` anahtar ya da eş ad); yanıt güncel ses nesnesidir.

```bash
curl -X POST http://localhost:8000/api/voices/a1b2c3d4e5f6/nonverbal -F tag=gülme -F file=@gulme.m4a
curl -X DELETE "http://localhost:8000/api/voices/a1b2c3d4e5f6/nonverbal/g%C3%BClme"     # gülme
```

## Kayıt iyileştirme

### `POST /api/voices/{id}/enhance`

Sesin temel referans kaydını temizler: DC kayması, tıklar, şebeke uğultusu (50/60 Hz ve iki harmoniği), arka plan
gürültüsü (spektral kapı, en çok 12 dB azaltma), 70 Hz altı gümbürtü ve seviye (−20 dBFS RMS, tepe −1 dBFS). Sonuç
yeniden analiz edilir; kalite puanı **en az 3** artarsa ya da form alanı `force=true` ise uygulanır. İlk uygulamada
özgün kayıt yedeklenir; sesin analizi yeni kayıtla güncellenir. Duygu ve tepki kayıtlarına dokunulmaz.

```json
{
  "applied": true,
  "delta": 9,
  "before": {"quality_score": 64, "grade": "orta", "…": "…"},
  "after": {"quality_score": 73, "grade": "iyi", "…": "…"},
  "report": {"applied": ["dc", "dehum", "denoise", "highpass", "level"], "noise_reduction_db": 7.4, "hum_hz": 50,
             "clicks_removed": 0, "gain_db": 2.1, "before_rms_db": -24.3, "after_rms_db": -20.0},
  "voice": {"id": "a1b2c3d4e5f6", "enhanced": true, "…": "…"}
}
```

- `applied` (üst düzey): kayıt değiştirildi mi. `delta`: puan farkı (sonra − önce). `report.applied`: sinyali
  değiştiren adımlar (`dc`, `declick`, `dehum`, `denoise`, `highpass`, `level`).
- Uygulanmadıysa kayıt aynı kalır; `before`/`after` ile farkı görüp `force=true` ile yine de uygulayabilirsiniz.
- Yankı, kırpılma ve dar bant (telefon/WhatsApp kaydı) düzeltilmez; bunlar için yeniden kaydedin.

### `POST /api/voices/{id}/enhance/undo`

Yedekteki özgün kaydı geri yükler ve yeniden analiz eder: `{"ok": true, "voice": {…}, "analysis": {…}}`. Yedek
yoksa 400 (`"Geri alınacak iyileştirme yok"`).

```bash
curl -X POST http://localhost:8000/api/voices/a1b2c3d4e5f6/enhance                  # puan ≥ +3 ise uygular
curl -X POST http://localhost:8000/api/voices/a1b2c3d4e5f6/enhance -F force=true     # her durumda uygular
curl -X POST http://localhost:8000/api/voices/a1b2c3d4e5f6/enhance/undo
```

## Metin → ses

### `POST /api/tts`

| Alan | Tip | Varsayılan | Açıklama |
|---|---|---|---|
| `text` | str | — (zorunlu) | Seslendirilecek metin, 1–`MAX_TEXT_CHARS` karakter; etiketler: [ETIKETLER.md](ETIKETLER.md) |
| `voice_id` | str \| null | `null` | Ses kimliği; `null` modelin yerleşik sesini kullanır |
| `language` | str | `"tr"` | Dil kodu (`health.languages`) |
| `style` | str \| null | `null` | Stil ön ayarı: ad, etiket ya da eş anlamlı (`"haber"`, `"Sesli Kitap"`, `"audiobook"`) |
| `emotion` | str \| null | stilden | Etiketsiz bölümler için varsayılan duygu; metindeki etiketler önceliklidir (diyalogda uygulanmaz) |
| `exaggeration` | float 0–1,5 | 0,5 · stilden | Duygu / vurgu yoğunluğu |
| `cfg_weight` | float 0–1 | 0,45 · stilden | Sese sadakat; düşük değer daha serbest ve ağır tempo |
| `temperature` | float 0,05–2 | 0,8 · stilden | Çeşitlilik |
| `speed` | float 0,7–1,3 | 1,0 · stilden | Tempo (perde korunur) |
| `pause_scale` | float 0,5–2,0 | 1,0 · stilden | Duraklama çarpanı; sesin `pause_scale` değeriyle çarpılır |
| `colloquial` | bool \| `"off"` \| `"light"` \| `"full"` | `"light"` · stilden | Konuşma dili; `true` = `"light"`, `false` = `"off"` |
| `breaths` | bool | `true` · stilden | Cümle aralarında nefes |
| `room_tone` | bool | `true` | Duraklamalarda sessizlik yerine kayıttaki oda tonu |
| `master` | bool | `true` | −16 LUFS, en fazla −1,5 dBTP, hafif EQ |
| `punctuation_emotion` | bool | `true` · stilden | `!` `?` `...` noktalamasına göre ton |
| `auto_emotion` | bool | `false` · stilden | Etiketsiz cümlelerde içerikten duygu tahmini |
| `emotion_fx` | `"off"` \| `"light"` \| `"full"` | `"off"` | Duygu için ek ses işleme; `full` deneyseldir |
| `emotion_refs` | bool | `false` | Yalnızca `emotion_fx: "full"`: duygu kaydı yoksa nötr kayıttan türet |
| `consistency` | bool | `true` | Parçalar arası tını (±3 dB EQ) ve seviye sıçraması eşitleme |
| `qc` | bool | `true` | Kalite kontrol: bozuk parçayı en çok iki kez yeniden üretir ([QC](#kalite-kontrol-raporu)) |
| `chat_speak` | bool | `true` | Sohbet kısaltmalarını açar (`tmm` → tamam, `slm` → selam); yalnız Türkçe |
| `fillers` | bool | `false` | Konuşma dolguları (yani, hani, işte); yalnız Türkçe; haber, belgesel, sesli-kitap, eğitim, müşteri-hizmeti ve anlatıcı stillerinde eklenmez |
| `subtitles` | bool | `true` | Zaman çizelgesi üretir; altyazı indirmek için gerekir |
| `speakers` | object \| null | `null` | Verilirse **diyalog modu**: konuşmacı adı → ses kimliği ([Diyalog](#diyalog)) |
| `narrator_voice_id` | str \| null | `null` | Diyalogda anlatıcının sesi; yoksa `voice_id`, o da yoksa model sesi |
| `speaker_emotions` | object \| null | `null` | Diyalogda konuşmacı → varsayılan duygu (`{"Mehmet": "samimi"}`) |
| `variants` | int 1–4 | 1 | Farklı tohumlarla üretilecek sonuç sayısı |
| `seed` | int \| null | `null` | Tohum; aynı tohum ve ayarlar aynı donanımda aynı sonucu verir |
| `format` | `"wav"` \| `"mp3"` | `"wav"` | Çıktı biçimi (MP3 için ffmpeg gerekir) |
| `wait` | bool | `false` | `true`: iş bitene kadar bekler ve sonucu döndürür |

**Stil önceliği:** "stilden" yazan alanlarda; alanı gönderirseniz sizin değeriniz, göndermezseniz stilin değeri,
stil de yoksa tablodaki varsayılan kullanılır. v4 alanları (`consistency`, `qc`, `chat_speak`, `fillers`,
`subtitles`) stilden gelmez.

**Metin zinciri (Türkçe):** `{yazılış|okunuş}` → sohbet kısaltmaları → telaffuz sözlüğü (ses sözlüğü + genel) →
normalizasyon → konuşma dili → konuşma dolguları. Ne değiştiğini `POST /api/lexicon/test` gösterir.

**Yanıt:** Varsayılan olarak `202 Accepted` ve bir [iş nesnesi](#get-apijobsid). `"wait": true` ile `200` ve doğrudan
[üretim nesnesi](#üretim-nesnesi) döner (üretim başarısız olursa `500`).

```bash
curl -X POST http://localhost:8000/api/tts -H "Content-Type: application/json" -d '{
  "text": "[heyecanlı:3] Merhaba İzmir! [fısıltı] Bu bir sır. [gülme]",
  "voice_id": "a1b2c3d4e5f6", "style": "sohbet", "format": "mp3", "wait": true }'
```

## Diyalog

`speakers` verildiğinde metin satır satır sıralara ayrılır ve her sıra konuşmacısının sesiyle üretilir; sıralar
doğal sıra alma duraklamalarıyla birleştirilir. Biçimler ve kurallar: [ETIKETLER → Diyalog biçimleri](ETIKETLER.md#12-diyalog-biçimleri).

- Metinde en az bir adlı konuşmacı olmalı (`Ayşe: …` ya da `[ses:Ayşe] …`); yoksa 400 (`"Diyalog için en az iki
  konuşmacı yazın (örn. 'Ayşe: Merhaba')."`).
- `speakers` eşlemesi ada göredir (büyük/küçük harf duyarsız). Değeri `null` olan ya da haritada bulunmayan konuşmacı
  modelin varsayılan sesiyle okunur. Var olmayan ses kimliği → 404.
- Metnin başındaki adsız satırlar anlatıcıdır (`narrator_voice_id` → `voice_id` → model sesi). `Anlatıcı:` yazılmış
  satır sıradan bir konuşmacıdır; ona ses vermek için `speakers` içine `"Anlatıcı": "<ses_id>"` ekleyin.
- `speaker_emotions` sıra kendi etiketiyle başlamıyorsa başına eklenir. İstekteki `emotion` ve stilin duygusu
  diyalogda uygulanmaz; stilin diğer ayarları (vurgu, tempo, konuşma dili…) uygulanır.
- Her sıra kendi sesinin duygu kayıtlarını, gerçek tepki kayıtlarını ve ses sözlüğünü kullanır; tutarlılık her
  konuşmacının kendi tınısına göre yapılır.
- Geçmişteki `voice_name` sesleri birleştirir ("Buse + Mehmet + Varsayılan ses").

```bash
curl -X POST http://localhost:8000/api/tts -H "Content-Type: application/json" -d '{
  "text": "Akşam olmuş, kafede iki eski arkadaş karşılaşır.\nAyşe: [heyecanlı] Mehmet? Sen misin?\nMehmet: [gülme] Ayşe! Hiç değişmemişsin.\nAyşe (fısıldayarak): Sana bir sır vereyim mi?",
  "speakers": {"Ayşe": "a1b2c3d4e5f6", "Mehmet": "f6e5d4c3b2a1"},
  "narrator_voice_id": "0a1b2c3d4e5f",
  "speaker_emotions": {"Mehmet": "samimi"},
  "style": "sohbet", "format": "mp3", "wait": true }'
```

Yanıttaki diyalog alanları (kısaltıldı):

```json
{
  "voice_name": "Anlatıcı sesi + Buse + Mehmet",
  "params": {
    "dialog": true,
    "speakers": [{"speaker": "Anlatıcı", "voice_name": "Anlatıcı sesi"}, {"speaker": "Ayşe", "voice_name": "Buse"},
                 {"speaker": "Mehmet", "voice_name": "Mehmet"}],
    "turns": [
      {"index": 0, "speaker": null, "voice_name": "Anlatıcı sesi", "text": "Akşam olmuş, kafede iki eski arkadaş karşılaşır.", "start": 0.0, "end": 3.21},
      {"index": 1, "speaker": "Ayşe", "voice_name": "Buse", "text": "[heyecanlı] Mehmet? Sen misin?", "start": 3.86, "end": 5.4},
      {"index": 2, "speaker": "Mehmet", "voice_name": "Mehmet", "text": "[gülme] Ayşe! Hiç değişmemişsin.", "start": 5.62, "end": 8.3},
      {"index": 3, "speaker": "Ayşe", "voice_name": "Buse", "text": "[fısıldayarak] Sana bir sır vereyim mi?", "start": 8.55, "end": 10.7}
    ],
    "nonverbal_used": ["gülme"],
    "timeline": ["…"], "qc_summary": {"…": "…"}
  }
}
```

`turns[].start`/`end` saniyedir (zaman çizelgesinden; `subtitles: false` iken de hesaplanır). `speaker: null`
anlatıcıdır.

## Üretim nesnesi

```json
{
  "id": "7c1e2d3f4a5b",
  "kind": "tts",
  "text": "[heyecanlı:3] Merhaba İzmir! [fısıltı] Bu bir sır. [gülme]",
  "voice_id": "a1b2c3d4e5f6",
  "voice_name": "Buse — doğal",
  "language": "tr",
  "filename": "5e4d3c2b1a09.mp3",
  "url": "/files/outputs/5e4d3c2b1a09.mp3",
  "duration": 4.62,
  "elapsed": 5.3,
  "created_at": "2026-10-13T09:31:07.000000+00:00",
  "seed": 1739201,
  "group_id": null,
  "favorite": false,
  "params": {
    "style": "sohbet", "exaggeration": 0.55, "cfg_weight": 0.45, "speed": 1.0, "colloquial": "light",
    "consistency": true, "qc": true, "fillers": false, "chat_speak": true, "subtitles": true,
    "normalized_text": "Merhaba İzmir! Bu bir sır.",
    "chunks": [
      {"text": "Merhaba İzmir!", "emotion": "heyecanlı", "intensity": 1.4, "blend": null, "arc_to": null,
       "emphasized": null, "ref": "kayıt", "exaggeration": 0.8, "cfg_weight": 0.4, "speed": 1.0, "pause_ms": 260,
       "duration": 1.61, "speaker": null, "qc_score": 100, "retries": 0},
      {"text": "Bu bir sır.", "emotion": "fısıltı", "intensity": null, "blend": null, "arc_to": null,
       "emphasized": null, "ref": "nötr", "exaggeration": 0.3, "cfg_weight": 0.6, "speed": 1.0, "pause_ms": 380,
       "duration": 1.29, "speaker": null, "qc_score": 85, "retries": 1},
      {"text": "[gülme]", "emotion": "fısıltı", "ref": "tepki kaydı", "nonverbal": "gülme", "exaggeration": null,
       "cfg_weight": null, "speed": 1.0, "pause_ms": 0, "duration": 1.84, "speaker": null}
    ],
    "colloquial_changes": [], "lexicon_changes": [],
    "qc_reports": [{"index": 0, "score": 100, "ok": true, "decision": "accept", "reasons": [], "metrics": {"…": "…"},
                    "retries": 0, "attempt": 1}],
    "qc_summary": {"count": 2, "mean_score": 92.5, "retries": 1,
                   "worst": {"index": 1, "score": 85, "decision": "accept", "codes": ["pause"], "message": "…"},
                   "decisions": {"accept": 2}, "codes": {"pause": 1}},
    "consistency_report": {"timbre_db": 0.8, "loudness_steps": 1, "max_gain_db": 2.6},
    "timeline": [{"index": 0, "start": 0.0, "end": 1.61, "text": "Merhaba İzmir!", "emotion": "heyecanlı", "speaker": null,
                  "words": [{"word": "Merhaba", "start": 0.0, "end": 0.878}, {"word": "İzmir!", "start": 0.878, "end": 1.61}]}],
    "nonverbal_used": ["gülme"],
    "dialog": false, "turns": null, "speakers": null
  }
}
```

| `params` alanı | Açıklama |
|---|---|
| `normalized_text` | Modele giden metin (okunuş, sözlük, normalizasyon, konuşma dili ve dolgular sonrası) |
| `chunks` | Parça başına: duygu, `intensity` (1 değilse), `blend`, `arc_to`, `emphasized`, `ref`, ayarlar, ardından gelen duraklama (`pause_ms`), süre, `speaker`, `qc_score`, `retries`. Tepki parçasında `nonverbal` |
| `colloquial_changes` · `lexicon_changes` | Konuşma dilinin ve telaffuz sözlüğünün yaptığı değişiklikler (`from`, `to`, `rule`) |
| `qc_reports` · `qc_summary` | [Kalite kontrol raporu](#kalite-kontrol-raporu) (`qc: false` iken yok) |
| `consistency_report` | `timbre_db`: ardışık parçaların tını farkındaki azalma (dB, pozitif = birbirine yaklaştı); `loudness_steps`: seviyesi ≥ 1,5 dB değiştirilen parça sayısı; `max_gain_db`: bir frekansta en büyük değişim |
| `timeline` | Zaman çizelgesi; [Altyazı](#altyazı) bunu kullanır (`subtitles: false` iken yok) |
| `nonverbal_used` | Gerçek kayıttan çalınan tepkiler (kaydı olmayıp okunanlar sayılmaz) |
| `dialog` · `turns` · `speakers` | Diyalog bilgisi ([Diyalog](#diyalog)) |
| `prosody` · `loudness` | Duraklama planı, nefes, oda tonu ve ses yüksekliği ölçümü |

- `ref` parçanın referansını söyler: `kayıt` (o duygunun kaydı), `nötr` (temel kayıt), `türetilmiş`
  (`emotion_fx: "full"` ile nötrden), `model` (ses seçilmemiş), `tepki kaydı` (gerçek tepki).
- `seed`: kullanılan tohum; aynı sonucu yeniden almak için istekte gönderin.
- **Varyantlar:** `variants > 1` ise sonuç ilk varyanttır ve `variants` alanı tüm varyantları (ilki dahil) sırayla
  içerir. Hepsi aynı `group_id` ile geçmişe yazılır.

```json
{"id": "7c1e…", "url": "/files/outputs/….mp3", "group_id": "g9f8e7d6c5b4", "seed": 1739201,
 "variants": [{"id": "7c1e…", "seed": 1739201, "…": "…"}, {"id": "8d2f…", "seed": 52144, "…": "…"}]}
```

### Kalite kontrol raporu

Her metin parçası üretildikten sonra ölçülür ve 0–100 puanlanır (`ok`: puan ≥ 60). Karar `decision` alanındadır:
`accept` (kabul), `retry_seed` (farklı tohumla yeniden), `retry_stable` (sıcaklık ≤ 0,6 ve sadakat ≥ 0,4 ile
yeniden), `trim` (kırp). Parça başına en çok 3 deneme yapılır, en yüksek puanlı seçilir; `retries` yapılan ek
deneme, `attempt` seçilen denemenin sırasıdır.

| Kod | Ne zaman | Karar |
|---|---|---|
| `too_long` | Parça beklenenden çok uzun (model cümleyi uzatmış ya da ses eklemiş) | `retry_seed`; aşırı yavaşsa ve tekrar yoksa `trim` |
| `too_short` | Parça çok kısa (cümle yarıda kesilmiş) | `retry_seed` |
| `silence` | Konuşmanın %45'inden fazlası sessizlik | `retry_seed` |
| `dropout` | Ortada noktalamayla açıklanamayan ≥ 250 ms'lik en az 2 boşluk | `retry_stable` |
| `repeat` | 0,6–3 sn arayla tekrar eden bölüm (takılma) | `retry_seed` |
| `buzz` | 4–8 kHz'de sürekli vızıltı ya da 50/100 Hz şebeke uğultusu | `retry_stable` |
| `clipping` | Örneklerin %0,1'inden fazlası tavanda | `trim` (seviye düşürülür) |
| `tail` | Sonda 600 ms'den uzun sessizlik | `trim` |
| `rate`, `pause` | Uyarı: hız sınırda · ortada tek uzun boşluk | Yalnızca puan düşer |

Her gerekçe `{"code", "message", "severity", "penalty", "action"}` taşır; `message` Türkçedir. `metrics` süre, hız
(`cps`, `sps`), sessizlik oranı, boşluklar, tekrar gecikmesi, kırpılma, vızıltı ve kuyruk ölçümlerini verir.
`qc_summary`: `count`, `mean_score`, `retries`, `worst` (`index`, `score`, `decision`, `codes`, `message`),
`decisions` ve `codes` sayıları.

## Kuyruk: işler ve akış

### `GET /api/jobs/{id}`

```json
{
  "id": "3f2a9c1d7e4b", "kind": "tts", "status": "running", "progress": 0.4, "step": 2, "total": 5,
  "message": "Peki nasıl çalışıyor?", "error": null,
  "created_at": 1791874267.12, "started_at": 1791874267.3, "finished_at": null, "elapsed": 6.2,
  "partial": [
    {"index": 0, "url": "/files/outputs/partial/3f2a9c1d7e4b_000.wav", "text": "Selam millet!", "duration": 1.2},
    {"index": 1, "url": "/files/outputs/partial/3f2a9c1d7e4b_001.wav", "text": "Bugün size…", "duration": 3.4}
  ],
  "cancelled": false, "eta_s": 9.3, "position": 0
}
```

| Alan | Açıklama |
|---|---|
| `status` | `queued` → `running` → `done` \| `error` \| `cancelled` |
| `progress`, `step`, `total` | 0–1 arası ilerleme; işlenen ve toplam parça sayısı |
| `message` | O anki adım (işlenen parçanın başı; diyalogda "Ayşe: …"; "tını eşitleniyor", "birleştiriliyor"…) |
| `partial` | Hazır olan parçalar (canlı önizleme): `index`, `url`, `text`, `duration`. Tepki parçasının `text`'i `[gülme]` gibidir. Son ses, tutarlılık, mastering ve birleştirmeden sonra `result` içindedir |
| `eta_s` | Kalan tahmini süre (sn); bilinmiyorsa `null` |
| `position` | Sıradaysa önündeki iş sayısı; çalışıyorsa 0; bittiyse `null` |
| `cancelled` | İptal istendi mi |
| `elapsed` | Geçen süre (sn) |
| `error` | `status: "error"` ise hata metni |
| `result` | `status: "done"` ise [üretim nesnesi](#üretim-nesnesi) |

İşler bellekte tutulur (son 200 iş); sunucu yeniden başlarsa iş sorgusu 404 döner. Sonuçlar geçmişte kalır.
`GET /api/jobs` son işleri yeniden eskiye bir dizi olarak döndürür.

### `POST /api/jobs/{id}/cancel`

Sıradaki iş hemen düşer; çalışan iş, o an üretilen parça bitince durur. İki durumda da iş `cancelled` durumuna geçer.
Bitmiş işe etkisi yoktur. Kesin durumu `GET /api/jobs/{id}` ile izleyin.

### Akış

1. `POST /api/tts` → `202` ve iş nesnesi.
2. `GET /api/jobs/{id}` ile 0,5–1 sn arayla sorgulayın; `position` ve `eta_s` kullanıcıya gösterilebilir.
3. Çalışırken `partial` listesine eklenen parçaları sırayla çalarak canlı önizleme yapın.
4. `status: "done"` → `result.url` son dosyadır. `error` → `error` alanı nedeni verir.
5. Vazgeçerseniz `POST /api/jobs/{id}/cancel`.

**curl (bash + jq)**

```bash
BASE=http://localhost:8000
JOB=$(curl -s -X POST "$BASE/api/tts" -H "Content-Type: application/json" \
  -d '{"text": "[sakin] Merhaba! Bu bir deneme.", "voice_id": "a1b2c3d4e5f6", "format": "mp3"}' | jq -r .id)
while :; do
  J=$(curl -s "$BASE/api/jobs/$JOB"); S=$(echo "$J" | jq -r .status)
  echo "$S $(echo "$J" | jq -r .progress)"
  case "$S" in done) break ;; error|cancelled) echo "$J" | jq -r .error; exit 1 ;; esac
  sleep 1
done
curl -s -o cikti.mp3 "$BASE$(echo "$J" | jq -r .result.url)"
curl -s -OJ "$BASE/api/generations/$(echo "$J" | jq -r .result.id)/subtitles?format=srt"   # altyazı
```

API anahtarı varsa her `curl` komutuna `-H "X-API-Key: $API_KEY"` ekleyin.

**Python (requests)**

```python
import time

import requests

BASE = "http://localhost:8000"
HEADERS = {"X-API-Key": "anahtariniz"}   # API_KEY boşsa gerekmez


def seslendir(text: str, voice_id: str, **ayarlar) -> list[dict]:
    r = requests.post(f"{BASE}/api/tts", headers=HEADERS,
                      json={"text": text, "voice_id": voice_id, "format": "mp3", **ayarlar}, timeout=30)
    r.raise_for_status()
    job, seen = r.json(), 0
    while job["status"] in ("queued", "running"):
        time.sleep(1)
        job = requests.get(f"{BASE}/api/jobs/{job['id']}", headers=HEADERS, timeout=30).json()
        for part in job["partial"][seen:]:
            print(f"hazır parça {part['index']}: {BASE}{part['url']}")
        seen = len(job["partial"])
    if job["status"] != "done":
        raise RuntimeError(f"{job['status']}: {job.get('error')}")
    result = job["result"]
    return result.get("variants") or [result]


sonuclar = seslendir("[heyecanlı] Yaz indirimi başladı! [1 sn] Kampanya 3 gün sürecek.", "a1b2c3d4e5f6",
                     style="reklam", variants=2)
for harf, g in zip("ABCD", sonuclar):
    with open(f"varyant_{harf}.mp3", "wb") as f:
        f.write(requests.get(BASE + g["url"], timeout=60).content)
    srt = requests.get(f"{BASE}/api/generations/{g['id']}/subtitles", params={"format": "srt"},
                       headers=HEADERS, timeout=30)
    with open(f"varyant_{harf}.srt", "w", encoding="utf-8") as f:
        f.write(srt.text)

# İptal: requests.post(f"{BASE}/api/jobs/{job_id}/cancel", headers=HEADERS)
```

**JavaScript (fetch)**

```js
const BASE = 'http://localhost:8000'
const HEADERS = {} // API_KEY varsa: { 'X-API-Key': '...' }

async function api(path, { method = 'GET', json } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: json ? { ...HEADERS, 'Content-Type': 'application/json' } : HEADERS,
    body: json ? JSON.stringify(json) : undefined,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `HTTP ${res.status}`)
  return data
}

/** Metni seslendirir; hazır parçaları onPartial ile bildirir, signal iptal edilirse işi iptal eder. */
async function seslendir(text, voiceId, { onPartial, signal, ...ayarlar } = {}) {
  let job = await api('/api/tts', { method: 'POST', json: { text, voice_id: voiceId, format: 'mp3', ...ayarlar } })
  let seen = 0
  while (job.status === 'queued' || job.status === 'running') {
    if (signal?.aborted) await api(`/api/jobs/${job.id}/cancel`, { method: 'POST' })
    await new Promise((r) => setTimeout(r, 700))
    job = await api(`/api/jobs/${job.id}`)
    job.partial.slice(seen).forEach((p) => onPartial?.(BASE + p.url, p))
    seen = job.partial.length
  }
  if (job.status !== 'done') throw new Error(job.error || job.status)
  return BASE + job.result.url
}

const url = await seslendir('Ayşe: Selam! Nasılsın?\nMehmet: [gülme] İyiyim, sen?', null, {
  speakers: { 'Ayşe': 'a1b2c3d4e5f6', 'Mehmet': 'f6e5d4c3b2a1' },
})
new Audio(url).play()
```

## Ses → ses

### `POST /api/vc`

Bir konuşma kaydını seçilen sese dönüştürür (tonlama ve sözler kaynaktan, ses rengi hedef sesten gelir).
`multipart/form-data`: `voice_id` (hedef ses), `file` (kaynak kayıt), `wait` (isteğe bağlı, `true`/`false`). Yanıt
`/api/tts` ile aynı biçimdedir; üretimin `kind` alanı `vc`'dir (zaman çizelgesi ve altyazı yoktur).

```bash
curl -X POST http://localhost:8000/api/vc -F voice_id=a1b2c3d4e5f6 -F file=@kaynak.wav -F wait=true
```

## Telaffuz sözlüğü

Yanlış okunan sözcüklerin kalıcı okunuşu. **Genel sözlük** (`DATA_DIR/lexicon.json`) her seste, **ses sözlüğü**
(`DATA_DIR/voices/<ses_id>.lexicon.json`) yalnızca o seste uygulanır ve aynı sözcükte geneli ezer. Değişiklikler
yeniden başlatmadan hemen geçerlidir. Yalnızca Türkçe metinde uygulanır; sözcük sınırına bakar, büyük/küçük harf
duyarsızdır, en uzun anahtar önce eşleşir, çok sözcüklü anahtar olur ("Red Bull"), kesmeli ek korunur ("Claude'un" →
"Klod'un"), baş harf büyüklüğü korunur; etiketlere, `{…}` okunuşlarına, URL ve e-postalara dokunulmaz. Eski
`DATA_DIR/pronunciations.json` da çalışmaya devam eder; aynı sözcükte bu sözlük kazanır.

### `GET /api/lexicon`

`?voice_id=` verilmezse genel sözlük, verilirse genel + ses sözlüğü birleşik (geçerli okunuş) döner; Türk alfabesine
göre sıralıdır:

```json
[{"word": "Claude", "reading": "Klod", "scope": "global"}, {"word": "Shopify", "reading": "Şopifay", "scope": "voice"}]
```

### `PUT /api/lexicon`

Gövde: `{"word": "…", "reading": "…", "voice_id": null}` — `word` 1–80, `reading` 1–160 karakter; `[ ] { } |`
içeremez. Aynı sözcüğün büyük/küçük harf türevi varsa yerine geçer. Yanıt: `{"word", "reading", "scope"}`.

### `DELETE /api/lexicon`

Sorgu: `word` (büyük/küçük harf duyarsız) ve isteğe bağlı `voice_id`. `{"ok": true}`; sözcük yoksa 404.

### `POST /api/lexicon/test`

Gövde: `{"text": "…", "voice_id": null, "language": "tr", "colloquial": "light"}` (`text` en fazla 2000 karakter).
Metnin modele nasıl gideceğini gösterir (okunuş → sohbet kısaltmaları → sözlük → normalizasyon → konuşma dili;
dolgu eklenmez). Yanıt: `normalized`, `changes` (sözlüğün yaptığı değişiklikler), `colloquial_changes`.

```bash
# Genel sözlüğe ekle · yalnız bir sese ekle · listele · sil
curl -X PUT http://localhost:8000/api/lexicon -H "Content-Type: application/json" \
  -d '{"word": "Shopify", "reading": "Şopifay"}'
curl -X PUT http://localhost:8000/api/lexicon -H "Content-Type: application/json" \
  -d '{"word": "Claude", "reading": "Klod", "voice_id": "a1b2c3d4e5f6"}'
curl "http://localhost:8000/api/lexicon?voice_id=a1b2c3d4e5f6"
curl -X DELETE "http://localhost:8000/api/lexicon?word=Shopify"

# Dene
curl -X POST http://localhost:8000/api/lexicon/test -H "Content-Type: application/json" \
  -d '{"text": "slm, Shopify raporu yrn 14:30 gibi gelir, tmm mı? Ne yapacağız bilmiyorum."}'
```

```json
{"normalized": "selam, Şopifay raporu yarın on dört otuz gibi gelir, tamam mı? Napıcaz bilmiyorum.",
 "changes": [{"from": "Shopify", "to": "Şopifay"}],
 "colloquial_changes": [{"from": "Ne yapacağız", "to": "Napıcaz", "rule": "gelecek-zaman+ne-kaynaşma"}]}
```

## Altyazı

### `GET /api/generations/{id}/subtitles`

Üretimin zaman çizelgesinden altyazı dosyası üretir (`Content-Disposition: attachment; filename="sesklon-<id>.srt"`).

| `format` | İçerik | Content-Type |
|---|---|---|
| `srt` (varsayılan) | SubRip; `00:00:01,250 --> 00:00:03,900` | `application/x-subrip` |
| `vtt` | WebVTT; `WEBVTT` başlığı, noktalı ondalık | `text/vtt` |
| `json` | Zaman çizelgesi: `index`, `start`, `end`, `text`, `emotion`, `speaker`, `words[]` (`word`, `start`, `end`) | `application/json` |
| `lrc` | Satır zamanlı LRC (`[mm:ss.xx]metin`) | `text/plain` |

- Bloklar: satır başına en çok 42 karakter, en çok 2 satır, en çok 7 sn; bloklar arası en az 80 ms; blok en az
  700 ms. Uzun cümle sözcük sınırından bölünür. Diyalogda aynı bloğa düşen farklı konuşmacılar `- ` ile ayrı satırdadır.
- Metin modelin **okuduğu** biçimdir (sayılar yazıyla, konuşma dili uygulanmış); etiketler ve tepkiler altyazıya
  girmez. Parça sınırları sesle örtüşür; sözcük zamanları hece sayısına göre tahmindir (hizalama değildir).
- Üretim `subtitles: false` ile yapıldıysa ya da `kind: "vc"` ise 404; bilinmeyen biçim 400.

```bash
curl -OJ "http://localhost:8000/api/generations/7c1e2d3f4a5b/subtitles?format=srt"
curl -o konusma.vtt "http://localhost:8000/api/generations/7c1e2d3f4a5b/subtitles?format=vtt"
```

```
1
00:00:00,000 --> 00:00:01,100
Selam, naber?

2
00:00:01,300 --> 00:00:02,900
İyiyim ya, sen nasılsın?

3
00:00:03,160 --> 00:00:06,060
Bugün çok güzel bir haber
aldım, anlatayım mı?
```

## Geçmiş

### `GET /api/generations`

Üretim nesnelerinden oluşan bir dizi, en yeni önce. Toplam kayıt sayısı `X-Total-Count` başlığındadır.

| Parametre | Açıklama |
|---|---|
| `limit` | Sayfa boyutu (varsayılan 100, en fazla 500) |
| `offset` | Atlanacak kayıt sayısı (sayfalama) |
| `kind` | `tts` ya da `vc` |
| `voice_id` | Yalnızca bu sesin üretimleri |
| `q` | Metinde ya da ses adında arama (Türkçe büyük/küçük harf duyarsız) |
| `favorite` | `true`: yalnızca favoriler |

```bash
curl "http://localhost:8000/api/generations?q=kampanya&kind=tts&limit=20&offset=0"
```

### `POST /api/generations/{id}/favorite` · `DELETE /api/generations/{id}`

`{"favorite": true}` ya da `{"favorite": false}` gövdesiyle favori durumunu değiştirir ve güncel üretim nesnesini
döndürür · Kaydı ve ses dosyasını siler (`{"ok": true}`).

Geçmişte en fazla `MAX_OUTPUTS` (varsayılan 500) üretim tutulur; aşılınca en eskileri (favoriler hariç) dosyalarıyla
birlikte silinir.

## Dosyalar

| Yol | İçerik |
|---|---|
| `/files/voices/{dosya}` | Referans, duygu ve tepki kayıtları |
| `/files/outputs/{dosya}` | Üretimler (WAV ya da MP3) |
| `/files/outputs/partial/{dosya}` | Canlı önizleme parçaları (geçici) |

Dosya yolları yanıtlardaki `url` alanlarından alınır; API anahtarı istemez.

## Analiz şeması

`POST /api/voices`, `POST /api/analyze`, `GET /api/voices/{id}/analysis`, duygu kayıtları ve kayıt iyileştirmenin
`before`/`after` alanları bu nesneyi döndürür. Sayılar yuvarlanmıştır.

```json
{
  "duration": 12.3, "speech_ratio": 0.82, "snr_db": 31.5, "noise_floor_dbfs": -58.0,
  "peak_dbfs": -1.2, "rms_dbfs": -20.1, "clipping_ratio": 0.0, "dc_offset": 0.001, "bandwidth_hz": 7800,
  "reverb": "düşük",
  "f0": {"median_hz": 180.0, "min_hz": 110.0, "max_hz": 290.0, "range_semitones": 16.8, "voiced_ratio": 0.6,
         "label": "kadın"},
  "speaking_rate": {"syllables_per_sec": 5.1, "label": "normal"},
  "pauses": {"count": 4, "mean_ms": 420, "median_ms": 380, "per_minute": 19.5, "scale": 1.05},
  "breaths": {"count": 2, "positions_s": [3.1, 7.8]},
  "quality_score": 84, "grade": "iyi",
  "issues": [{"code": "noisy", "severity": "info", "message": "Hafif arka plan gürültüsü var (sinyal/gürültü 26 dB). …"}],
  "tips": ["Kayıttan önce klima, fan ve buzdolabı gibi sürekli ses kaynaklarını kapatın; …"]
}
```

| Alan | Açıklama |
|---|---|
| `duration` | Süre (sn) |
| `speech_ratio` | Konuşma içeren bölümün oranı (0–1) |
| `snr_db`, `noise_floor_dbfs` | Sinyal/gürültü oranı; sessiz bölümün (oda tonunun) seviyesi |
| `peak_dbfs`, `rms_dbfs` | Tepe ve ortalama seviye |
| `clipping_ratio`, `dc_offset` | Tavana vuran örneklerin oranı; sinyaldeki sabit kayma |
| `bandwidth_hz` | Kaydın frekans genişliği (telefon hattı ≈ 3400 Hz) |
| `reverb` | `düşük` \| `orta` \| `yüksek` |
| `f0` | Perde istatistikleri; `label`: `kadın` \| `erkek` \| `belirsiz` |
| `speaking_rate` | Saniyedeki hece; `label`: `yavaş` \| `normal` \| `hızlı` |
| `pauses` | Duraklamalar; `scale` = ortanca duraklama / 400 ms, 0,7–1,5 arasına sıkıştırılmış (sesin `pause_scale`'i) |
| `breaths` | Bulunan nefeslerin sayısı ve konumları (sn) |
| `quality_score`, `grade` | 0–100 puan; `mükemmel` (85+) \| `iyi` (70+) \| `orta` (50+) \| `zayıf` |
| `issues` | `code`, `severity` (`error` \| `warn` \| `info`), Türkçe `message` |
| `tips` | En fazla dört kısa Türkçe öneri |

Sorun kodları (`too_short`, `too_long`, `noisy`, `clipping`, `too_quiet`, `too_loud`, `low_bandwidth`, `reverb`,
`dc_offset`, `low_speech_ratio`, `monotone`, `too_fast`, `too_slow`) ve ne yapılması gerektiği:
[Kayıt rehberi → Analiz puanı](KAYIT_REHBERI.md#9-analiz-puanı-nasıl-yorumlanır).

## Hata kodları

Hata yanıtlarının gövdesi `{"detail": "Türkçe açıklama"}` biçimindedir; 422'de `detail` bir listedir.

| Kod | Ne zaman |
|---|---|
| 400 | Geçersiz değer: desteklenmeyen dil, bilinmeyen duygu, stil ya da altyazı biçimi, izin onayı yok (`consent`), geçersiz duygu ya da tepki adı, okunamayan, boş ya da çok kısa dosya, kırpma sonrası 2 sn'den kısa konuşma, konuşmacısız diyalog metni, sözlükte yasak karakter (`[ ] { } \|`), geri alınacak iyileştirme yok |
| 401 | `API_KEY` tanımlı ve `X-API-Key` başlığı eksik ya da yanlış |
| 404 | Ses, iş, geçmiş kaydı ya da sözlük sözcüğü bulunamadı; üretimin zaman çizelgesi yok (altyazı); bilinmeyen `/api` yolu |
| 413 | Dosya `MAX_UPLOAD_MB` sınırından büyük |
| 422 | Şema doğrulaması: boş ya da `MAX_TEXT_CHARS`'tan uzun metin, aralık dışı sayı, geçersiz `format` / `emotion_fx` / `colloquial` |
| 500 | `"wait": true` ile üretim ya da dönüştürme başarısız (`"Üretim başarısız: …"`); kayıt iyileştirme hatası |

`"wait": false` (varsayılan) ile üretim hataları HTTP hatası olarak değil, işin `status: "error"` ve `error` alanı
olarak görünür.

```json
{"detail": [{"type": "less_than_equal", "loc": ["body", "speed"], "msg": "Input should be less than or equal to 1.3",
             "input": 1.6, "ctx": {"le": 1.3}}]}
```

## Sınırlar ve davranış

| Konu | Davranış |
|---|---|
| Metin uzunluğu | İstek başına `MAX_TEXT_CHARS` (5000; diyalogda tüm metin); metin ~`CHUNK_CHARS` (170) karakterlik parçalara bölünür |
| Yükleme | Dosya başına `MAX_UPLOAD_MB` (60 MB) |
| Referans | En fazla `MAX_REF_SECONDS` (15 sn) kullanılır |
| Tepki kaydı | En az 0,15 sn; en fazla 3 sn kullanılır (yüklemenin ilk 60 sn'si incelenir) |
| Telaffuz sözlüğü | Sözcük 1–80, okunuş 1–160 karakter; deneme metni en fazla 2000 karakter |
| Kalite kontrol | Parça başına en çok 3 deneme; bozuk parça üretim süresini uzatır |
| Kuyruk | Tek işçi, işler sırayla; iş kayıtları bellekte (son 200) |
| Geçmiş | En fazla `MAX_OUTPUTS` (500) üretim; fazlası en eskiden silinir |
| Tekrarlanabilirlik | Aynı `seed` ve ayarlarla aynı donanımda aynı sonuç; donanım değişirse küçük farklar olabilir |
| Filigran | Her üretim Resemble AI'ın algılanamaz PerTh filigranını taşır |
