# SesKlon HTTP API

Web arayüzü de bu API'yi kullanır; arayüzde yapılabilen her şey API ile de yapılabilir. Örneklerdeki adres
`http://localhost:8000`'dir.

- **Etkileşimli belge (Swagger):** `http://localhost:8000/api/docs` — istekleri tarayıcıdan deneyebilirsiniz.
- **OpenAPI şeması:** `http://localhost:8000/api/openapi.json`

**İçindekiler:** [Temel bilgiler](#temel-bilgiler) · [Uç noktalar](#uç-noktalar) · [Sistem](#sistem) · [Sesler](#sesler) ·
[Metin → ses](#metin--ses) · [İşler ve akış](#kuyruk-işler-ve-akış) · [Ses → ses](#ses--ses) · [Geçmiş](#geçmiş) ·
[Dosyalar](#dosyalar) · [Analiz şeması](#analiz-şeması) · [Hata kodları](#hata-kodları) · [Sınırlar](#sınırlar-ve-davranış)

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
| GET | `/api/health` | Cihaz, model durumu, diller, etiket ve stil kataloğu, özellikler |
| POST | `/api/warmup` | Modeli yükle |
| GET | `/api/stats` | Sayılar: ses, duygu kaydı, üretim, favori, toplam süre |
| GET | `/api/voices` | Sesler |
| POST | `/api/voices` | Yeni ses (multipart) — yanıtta `analysis` |
| GET | `/api/voices/{id}` | Ses ayrıntısı |
| PATCH | `/api/voices/{id}` | Ad, not, varsayılan stil, duraklama çarpanı |
| DELETE | `/api/voices/{id}` | Sesi ve kayıtlarını sil |
| POST | `/api/voices/{id}/samples` | Duygu kaydı ekle / değiştir (multipart) |
| DELETE | `/api/voices/{id}/samples/{emotion}` | Duygu kaydını sil |
| GET | `/api/voices/{id}/analysis` | Sesin kayıt analizi |
| GET | `/api/voices/{id}/export` | Sesi zip olarak yedekle |
| POST | `/api/voices/import` | Zip yedeğinden ses oluştur (multipart) |
| POST | `/api/analyze` | Kaydı saklamadan analiz et (multipart) |
| POST | `/api/tts` | Metin → ses |
| GET | `/api/jobs` | Son işler |
| GET | `/api/jobs/{id}` | İş durumu, ilerleme, hazır parçalar, sonuç |
| POST | `/api/jobs/{id}/cancel` | İşi iptal et |
| POST | `/api/vc` | Ses → ses (multipart) |
| GET | `/api/generations` | Geçmiş: arama, süzgeç, sayfalama |
| POST | `/api/generations/{id}/favorite` | Favoriye ekle / çıkar |
| DELETE | `/api/generations/{id}` | Geçmiş kaydını ve dosyasını sil |

## Sistem

### `GET /api/health`

Arayüzün açılışta ve düzenli aralıklarla sorguladığı durum bilgisi. Docker sağlık denetimi de bunu kullanır.

```json
{
  "ok": true,
  "device": "cuda",
  "model": "chatterbox-multilingual-v3",
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
    "pauses": ["duraklama", "nefes"],
    "pause_detail": [{"tag": "nefes", "ms": 500}],
    "timed_pause_examples": ["[500 ms]", "[1 sn]", "[1.5 sn]", "[2 saniye]"],
    "emphasis_examples": ["*çok* önemli", "[vurgu] yarın", "[vurgu: hemen şimdi]"],
    "scoped_example": "[heyecanlı: Yalnızca bu cümle heyecanlı.]"
  },
  "emotion_tags": ["normal", "heyecanlı", "mutlu"],
  "styles": [{"name": "sohbet", "label": "Sohbet", "description": "Varsayılan: doğal, samimi, konuşur gibi.",
              "emotion": null, "exaggeration": 0.55, "cfg_weight": 0.45, "temperature": 0.8, "speed": 1.0,
              "pause_scale": 1.0, "colloquial": "light", "breaths": true, "punctuation_emotion": true,
              "auto_emotion": false, "aliases": ["conversational", "chat"]}],
  "colloquial_levels": ["off", "light", "full"],
  "features": {"breaths": true, "room_tone": true, "master": true, "analysis": true}
}
```

(Listeler kısaltıldı.) `model_error` doluysa model yüklenememiştir; metin hatanın nedenini verir.

### `POST /api/warmup`

Model yüklü değilse arka planda yüklemeyi başlatır: `{"ok": true, "model_loaded": false, "model_loading": true}`.
`PRELOAD=1` (varsayılan) iken buna gerek yoktur.

### `GET /api/stats`

```json
{"voices": 3, "samples": 7, "generations": 128, "favorites": 9, "by_kind": {"tts": 120, "vc": 8},
 "total_duration_s": 1843.2, "total_elapsed_s": 512.7, "rtf": 0.278}
```

`rtf`: üretime harcanan süre / üretilen ses süresi (1'in altı gerçek zamandan hızlı demektir); üretim yoksa `null`.

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
  "analysis": {"quality_score": 88, "grade": "mükemmel", "…": "…"},
  "samples": [
    {"id": "0c9d8e7f6a5b", "voice_id": "a1b2c3d4e5f6", "emotion": "üzgün", "filename": "1a2b3c4d5e6f.wav",
     "url": "/files/voices/1a2b3c4d5e6f.wav", "duration": 9.8, "created_at": "2026-10-13T09:20:01+00:00",
     "analysis": {"quality_score": 81, "grade": "iyi", "…": "…"}}
  ]
}
```

- `duration`: kırpılıp hazırlanmış referansın süresi (en fazla `MAX_REF_SECONDS`).
- `pause_scale`: sesin kişisel duraklama çarpanı; analizdeki `pauses.scale` değerinden gelir, elle değiştirilebilir.
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

Ses nesnesini döndürür · Sesi, temel kaydını ve tüm duygu kayıtlarını siler (`{"ok": true}`). Geçmişteki üretimler
silinmez.

### `PATCH /api/voices/{id}`

JSON gövdesinde yalnızca değiştirmek istediğiniz alanları gönderin; yanıt güncel ses nesnesidir.

| Alan | Tip | Açıklama |
|---|---|---|
| `name` | str (1–80) | Ses adı |
| `notes` | str \| null | Serbest not; boş metin notu siler |
| `default_style` | str \| null | Varsayılan stil (stil adı); `null` kaldırır |
| `pause_scale` | float 0,5–2,0 | Sesin duraklama çarpanı |

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

Sesin kayıtlı analizini döndürür · Yüklenen dosyayı **saklamadan** analiz eder (`multipart/form-data`, alan: `file`).
Arayüz, bir kayıt seçildiği anda kaliteyi göstermek için ikincisini kullanır. Yanıt: [Analiz şeması](#analiz-şeması).

```bash
curl -X POST http://localhost:8000/api/analyze -F file=@deneme.m4a
```

### `GET /api/voices/{id}/export` · `POST /api/voices/import`

Sesi tüm duygu kayıtları ve analizleriyle tek bir zip dosyası olarak indirir (`application/zip`; dosya adı
`Content-Disposition` başlığındadır). Zip; ses dosyalarını ve sesin bilgilerini (ad, dil, not, varsayılan stil,
duraklama çarpanı, analizler) taşıyan bir bilgi dosyasını (`"format": "sesklon-voice"`) içerir. İçe aktarma aynı zipi
`multipart/form-data` (`file`) ile alır ve yeni bir kimlikle ses oluşturup ses nesnesini döndürür.

```bash
curl -o buse.zip http://localhost:8000/api/voices/a1b2c3d4e5f6/export
curl -X POST http://localhost:8000/api/voices/import -F file=@buse.zip
```

## Metin → ses

### `POST /api/tts`

| Alan | Tip | Varsayılan | Açıklama |
|---|---|---|---|
| `text` | str | — (zorunlu) | Seslendirilecek metin, 1–`MAX_TEXT_CHARS` karakter; etiketler: [ETIKETLER.md](ETIKETLER.md) |
| `voice_id` | str \| null | `null` | Ses kimliği; `null` modelin yerleşik sesini kullanır |
| `language` | str | `"tr"` | Dil kodu (`health.languages`) |
| `style` | str \| null | `null` | Stil ön ayarı: ad, etiket ya da eş anlamlı (`"haber"`, `"Sesli Kitap"`, `"audiobook"`) |
| `emotion` | str \| null | stilden | Etiketsiz bölümler için varsayılan duygu; metindeki etiketler önceliklidir |
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
| `variants` | int 1–4 | 1 | Farklı tohumlarla üretilecek sonuç sayısı |
| `seed` | int \| null | `null` | Tohum; aynı tohum ve ayarlar aynı donanımda aynı sonucu verir |
| `format` | `"wav"` \| `"mp3"` | `"wav"` | Çıktı biçimi (MP3 için ffmpeg gerekir) |
| `wait` | bool | `false` | `true`: iş bitene kadar bekler ve sonucu döndürür |

**Stil önceliği:** "stilden" yazan alanlarda; alanı gönderirseniz sizin değeriniz, göndermezseniz stilin değeri,
stil de yoksa tablodaki varsayılan kullanılır.

**Yanıt:** Varsayılan olarak `202 Accepted` ve bir [iş nesnesi](#get-apijobsid). `"wait": true` ile `200` ve doğrudan
üretim nesnesi döner (üretim başarısız olursa `500`).

```bash
curl -X POST http://localhost:8000/api/tts -H "Content-Type: application/json" -d '{
  "text": "[heyecanlı] Merhaba İzmir! [fısıltı] Bu bir sır.",
  "voice_id": "a1b2c3d4e5f6", "style": "sohbet", "format": "mp3", "wait": true }'
```

### Üretim nesnesi

```json
{
  "id": "7c1e2d3f4a5b",
  "kind": "tts",
  "text": "[heyecanlı] Merhaba İzmir! [fısıltı] Bu bir sır.",
  "voice_id": "a1b2c3d4e5f6",
  "voice_name": "Buse — doğal",
  "language": "tr",
  "filename": "5e4d3c2b1a09.mp3",
  "url": "/files/outputs/5e4d3c2b1a09.mp3",
  "duration": 3.42,
  "elapsed": 4.1,
  "created_at": "2026-10-13T09:31:07.000000+00:00",
  "seed": 1739201,
  "group_id": null,
  "favorite": false,
  "params": {
    "style": "sohbet", "exaggeration": 0.55, "cfg_weight": 0.45, "speed": 1.0, "colloquial": "light",
    "normalized_text": "Merhaba İzmir! Bu bir sır.",
    "chunks": [
      {"text": "Merhaba İzmir!", "emotion": "heyecanlı", "ref": "kayıt", "exaggeration": 0.9, "cfg_weight": 0.3,
       "speed": 1.0, "pause_ms": 520, "duration": 1.61},
      {"text": "Bu bir sır.", "emotion": "fısıltı", "ref": "nötr", "exaggeration": 0.3, "cfg_weight": 0.6,
       "speed": 1.0, "pause_ms": 0, "duration": 1.29}
    ]
  }
}
```

- `params`: istekte kullanılan ayarlar (stil uygulanmış hâliyle) ve tanılama bilgileri. `normalized_text` modele
  giden metindir (normalizasyon ve konuşma dili sonrası).
- `params.chunks`: her parça için uygulanan duygu, ayarlar, ardından gelen duraklama (`pause_ms`) ve süre. `ref`
  parçanın referansını söyler: `kayıt` (o duygunun kaydı), `nötr` (temel kayıt), `türetilmiş` (`emotion_fx: "full"`
  ile nötrden türetilmiş), `model` (ses seçilmemiş).
- `seed`: kullanılan tohum; aynı sonucu yeniden almak için istekte gönderin.
- **Varyantlar:** `variants > 1` ise sonuç ilk varyanttır ve `variants` alanı tüm varyantları (ilki dahil) sırayla
  içerir. Hepsi aynı `group_id` ile geçmişe yazılır.

```json
{"id": "7c1e…", "url": "/files/outputs/….mp3", "group_id": "g9f8e7d6c5b4", "seed": 1739201,
 "variants": [{"id": "7c1e…", "seed": 1739201, "…": "…"}, {"id": "8d2f…", "seed": 52144, "…": "…"}]}
```

## Kuyruk: işler ve akış

### `GET /api/jobs/{id}`

```json
{
  "id": "3f2a9c1d7e4b", "kind": "tts", "status": "running", "progress": 0.4, "step": 2, "total": 5,
  "message": "Peki nasıl çalışıyor?", "error": null,
  "created_at": 1791874267.12, "started_at": 1791874267.3, "finished_at": null, "elapsed": 6.2,
  "partial": [
    {"index": 0, "url": "/files/outputs/partial/3f2a9c1d7e4b_0.wav", "text": "Selam millet!", "duration": 1.2},
    {"index": 1, "url": "/files/outputs/partial/3f2a9c1d7e4b_1.wav", "text": "Bugün size…", "duration": 3.4}
  ],
  "cancelled": false, "eta_s": 9.3, "position": 0
}
```

| Alan | Açıklama |
|---|---|
| `status` | `queued` → `running` → `done` \| `error` \| `cancelled` |
| `progress`, `step`, `total` | 0–1 arası ilerleme; işlenen ve toplam parça sayısı |
| `message` | O anki adım (işlenen parçanın başı, "birleştiriliyor"…) |
| `partial` | Hazır olan parçalar (canlı önizleme): `index`, `url`, `text`, `duration`. Son ses, mastering ve birleştirmeden sonra `result` içindedir |
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
```

API anahtarı varsa her `curl` komutuna `-H "X-API-Key: $API_KEY"` ekleyin.

**Python (requests)**

```python
import time

import requests

BASE = "http://localhost:8000"
HEADERS = {"X-API-Key": "anahtariniz"}   # API_KEY boşsa gerekmez


def seslendir(text: str, voice_id: str, **ayarlar) -> list[str]:
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
    return [BASE + g["url"] for g in (result.get("variants") or [result])]


urls = seslendir("[heyecanlı] Yaz indirimi başladı! [1 sn] Kampanya 3 gün sürecek.", "a1b2c3d4e5f6",
                 style="reklam", variants=2)
for harf, url in zip("ABCD", urls):
    with open(f"varyant_{harf}.mp3", "wb") as f:
        f.write(requests.get(url, timeout=60).content)

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

const url = await seslendir('[samimi] Selam! Nasılsın?', 'a1b2c3d4e5f6', { style: 'sohbet' })
new Audio(url).play()
```

## Ses → ses

### `POST /api/vc`

Bir konuşma kaydını seçilen sese dönüştürür (tonlama ve sözler kaynaktan, ses rengi hedef sesten gelir).
`multipart/form-data`: `voice_id` (hedef ses), `file` (kaynak kayıt), `wait` (isteğe bağlı, `true`/`false`). Yanıt
`/api/tts` ile aynı biçimdedir; üretimin `kind` alanı `vc`'dir.

```bash
curl -X POST http://localhost:8000/api/vc -F voice_id=a1b2c3d4e5f6 -F file=@kaynak.wav -F wait=true
```

## Geçmiş

### `GET /api/generations`

Üretim nesnelerinden oluşan bir dizi, en yeni önce.

| Parametre | Açıklama |
|---|---|
| `limit` | Sayfa boyutu (varsayılan 100, en fazla 500) |
| `offset` | Atlanacak kayıt sayısı (sayfalama) |
| `kind` | `tts` ya da `vc` |
| `voice_id` | Yalnızca bu sesin üretimleri |
| `q` | Metinde ya da ses adında arama (Türkçe büyük/küçük harf duyarsız) |
| `favorite` | `true`: yalnızca favoriler |

Gelen dizi `limit`'ten kısaysa son sayfadasınız.

```bash
curl "http://localhost:8000/api/generations?q=kampanya&kind=tts&limit=20&offset=0"
```

### `POST /api/generations/{id}/favorite` · `DELETE /api/generations/{id}`

`{"favorite": true}` ya da `{"favorite": false}` gövdesiyle favori durumunu değiştirir ve güncel üretim nesnesini
döndürür · Kaydı ve ses dosyasını siler (`{"ok": true}`).

Geçmişte en fazla `MAX_OUTPUTS` (varsayılan 500) üretim tutulur; aşılınca en eskileri dosyalarıyla birlikte silinir.

## Dosyalar

| Yol | İçerik |
|---|---|
| `/files/voices/{dosya}` | Referans kayıtları ve duygu kayıtları |
| `/files/outputs/{dosya}` | Üretimler (WAV ya da MP3) |
| `/files/outputs/partial/{dosya}` | Canlı önizleme parçaları (geçici) |

Dosya yolları yanıtlardaki `url` alanlarından alınır; API anahtarı istemez.

## Analiz şeması

`POST /api/voices`, `POST /api/analyze`, `GET /api/voices/{id}/analysis` ve duygu kayıtları bu nesneyi döndürür.
Sayılar yuvarlanmıştır.

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
[Kayıt rehberi → Analiz puanı](KAYIT_REHBERI.md#8-analiz-puanı-nasıl-yorumlanır).

## Hata kodları

Hata yanıtlarının gövdesi `{"detail": "Türkçe açıklama"}` biçimindedir; 422'de `detail` bir listedir.

| Kod | Ne zaman |
|---|---|
| 400 | Geçersiz değer: desteklenmeyen dil, bilinmeyen duygu ya da stil, izin onayı yok (`consent`), geçersiz duygu kaydı adı, okunamayan ya da boş dosya, kırpma sonrası 2 sn'den kısa konuşma |
| 401 | `API_KEY` tanımlı ve `X-API-Key` başlığı eksik ya da yanlış |
| 404 | Ses, iş ya da geçmiş kaydı bulunamadı (sunucu yeniden başladıysa eski işler de); bilinmeyen `/api` yolu |
| 413 | Dosya `MAX_UPLOAD_MB` sınırından büyük |
| 422 | Şema doğrulaması: boş ya da `MAX_TEXT_CHARS`'tan uzun metin, aralık dışı sayı, geçersiz `format` / `emotion_fx` / `colloquial` |
| 500 | `"wait": true` ile üretim ya da dönüştürme başarısız (`"Üretim başarısız: …"`) |

`"wait": false` (varsayılan) ile üretim hataları HTTP hatası olarak değil, işin `status: "error"` ve `error` alanı
olarak görünür.

```json
{"detail": [{"type": "less_than_equal", "loc": ["body", "speed"], "msg": "Input should be less than or equal to 1.3",
             "input": 1.6, "ctx": {"le": 1.3}}]}
```

## Sınırlar ve davranış

| Konu | Davranış |
|---|---|
| Metin uzunluğu | İstek başına `MAX_TEXT_CHARS` (5000); metin ~`CHUNK_CHARS` (170) karakterlik parçalara bölünür |
| Yükleme | Dosya başına `MAX_UPLOAD_MB` (60 MB) |
| Referans | En fazla `MAX_REF_SECONDS` (15 sn) kullanılır |
| Kuyruk | Tek işçi, işler sırayla; iş kayıtları bellekte (son 200) |
| Geçmiş | En fazla `MAX_OUTPUTS` (500) üretim; fazlası en eskiden silinir |
| Tekrarlanabilirlik | Aynı `seed` ve ayarlarla aynı donanımda aynı sonuç; donanım değişirse küçük farklar olabilir |
| Filigran | Her üretim Resemble AI'ın algılanamaz PerTh filigranını taşır |
