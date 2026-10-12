# SesKlon — kendi sunucunda çalışan, duygu kontrollü Türkçe ses klonlama

ElevenLabs tarzı bir metin‑okuma ve ses klonlama uygulaması; tamamen yerel çalışır, veri dışarı çıkmaz.
Model: [Chatterbox Multilingual V3](https://github.com/resemble-ai/chatterbox) (Resemble AI, **MIT**, Türkçe dahil 23 dil).
> PyPI'daki `chatterbox-tts` paketi V2 ağırlıklarını kullanır; bu proje V3 için GitHub kaynağından kurar.

**Neler var**
- 8–15 sn kayıttan sıfır‑shot ses klonlama; mikrofondan kayıt; ses → ses dönüştürme
- **Duygu sistemi**: `[heyecanlı] [üzgün] [kızgın] [fısıltı] …` etiketleri, `[gülme] [iç çekme] [nefes]` sözsüz etiketler,
  noktalamaya göre duygu, içerikten otomatik duygu, ses başına **duygu kayıtları**
- **Konuşma dili**: "geleceğim → gelicem", "bir şey → bişey" (kapatılabilir)
- Türkçe normalizasyon: sayı, tarih, saat, para, birim, kısaltma, marka okunuşu (`pronunciations.json` ile genişletilebilir)
- İş kuyruğu + ilerleme çubuğu (uzun metinlerde zaman aşımı yok), geçmiş, MP3/WAV, API anahtarı, Swagger

```
sesklon/
├─ backend/app/   main.py (API) · engine.py (üretim) · emotion.py (duygu) · colloquial.py · textnorm.py · audio.py · jobs.py · db.py
├─ backend/tests/ pytest paketi (sahte motorla uçtan uca)
├─ frontend/      React + Vite arayüz
├─ Dockerfile · docker-compose.yml · run.sh (Linux/macOS) · run.ps1 (Windows)
```

## Kurulum

| Cihaz | Durum |
|---|---|
| NVIDIA GPU (≥ 6 GB VRAM) | Önerilen — 10 sn ses ≈ 2–5 sn |
| Apple Silicon | Çalışır (`DEVICE=mps`) |
| Yalnızca CPU | Çalışır ama yavaş (10 sn ses ≈ 1–3 dk) |

**Docker (önerilen)** — host'ta NVIDIA için `nvidia-container-toolkit` kurulu olmalı:
```bash
docker compose up -d --build        # → http://localhost:8000
```
GPU yoksa `docker-compose.yml` içindeki `deploy:` bloğunu silin ve `DEVICE=cpu` satırını açın.

**Docker'sız**: Linux/macOS `./run.sh` · Windows `.\run.ps1` (Python 3.11, Node 20, ffmpeg, git gerekir).
İlk açılışta model (~2 GB) Hugging Face'ten indirilir, `data/hf-cache` altında saklanır ve arka planda yüklenir.

**Geliştirme**: `cd backend && uvicorn app.main:app --reload` · `cd frontend && npm run dev` · testler: `cd backend && pytest`

## Duygu sistemi nasıl çalışır

Bu modelde duyguyu belirleyen en güçlü şey **referans klibin tonu**. SesKlon üç katmanı birlikte kullanır:

1. **Referans** — her `[etiket]` için: o duygu için senin kaydın varsa o, yoksa nötr kaydın.
   "Sesler" sekmesinde her sese duygu başına kayıt eklenebilir; okuma metinleri hazır. **En iyi sonuç buradan gelir.**
2. **Üretim** — duyguya göre vurgu (exaggeration), sadakat (cfg) ve sıcaklık; `!` `?` `...` noktalaması üstüne eklenir; duraklamalar duyguya göre uzar/kısalır.
3. **Ses işleme** (`emotion_fx`) — varsayılan **kapalı** (en doğal). `light`: duyguya göre şiddet farkı. `full` (deneysel): nötr kayıttan
   perde/tempo kaydırılmış referans türetme, mikro perde, sıkıştırma ve fısıltı için LPC sessiz‑konuşma dönüşümü. Bu işlemler
   duyguyu belirginleştirir ama sesi kimliğinden uzaklaştırıp yapaylık ekleyebilir; dinleyip karar ver.

Etiketler (Türkçe/İngilizce eş anlamlılar da çalışır): `[normal] [heyecanlı] [mutlu] [sakin] [ciddi] [üzgün] [kızgın] [şaşkın] [korkmuş] [fısıltı] [vurgulu] [samimi] [sıkılmış] [alaycı] [hızlı] [yavaş]`
Sözsüz: `[gülme] [kahkaha] [kıkırdama] [iç çekme] [hmm] [of] [şaşırır] [ağlar] [öksürür] [boğaz temizler] [esner]`
Duraklama: `[nefes]` 0,5 sn · `[duraklama]` 0,8 sn · `[uzun duraklama]` 1,5 sn

```
[heyecanlı] Selam millet! Bugün size çok güzel bir şey göstereceğim. [gülme] Hem de Türkçe!
[sakin] Peki nasıl çalışıyor? On saniyelik bir kayıt yüklüyorsunuz... [nefes] ve bitti.
[fısıltı] Size bir sır vereyim: artık hiç gerekmiyor. [kızgın] Ve kimse bunu söylemiyor!
```

Sınır: model gülme/iç çekme gibi sesleri doğal üretemez; bunlar en yakın ünlemle ("Hahaha!") seslendirilir.

## Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `API_KEY` | boş | Doluysa `/api/*` için `X-API-Key` başlığı gerekir. İnternete açacaksan doldur. |
| `DEVICE` | otomatik | `cuda` / `mps` / `cpu` |
| `PRELOAD` | `1` | Modeli açılışta arka planda yükle |
| `T3_MODEL` | `v3` | Chatterbox Multilingual sürümü |
| `DATA_DIR` | `backend/data` | Sesler, çıktılar, SQLite, model önbelleği |
| `MAX_TEXT_CHARS` | `5000` | Tek istekte en fazla karakter |
| `MAX_UPLOAD_MB` | `60` | Yükleme sınırı |
| `MAX_OUTPUTS` | `500` | Geçmişte tutulacak çıktı sayısı (0 = sınırsız) |
| `CHUNK_CHARS` | `170` | Parça boyu |
| `MAX_REF_SECONDS` | `15` | Referansın kullanılan süresi |

## API

Swagger: `http://localhost:8000/api/docs`

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/health` | Cihaz, model durumu, dil ve etiket kataloğu |
| POST | `/api/warmup` | Modeli yükle |
| GET/POST | `/api/voices` | Sesler / yeni ses (`name`, `language`, `consent=true`, `file`) |
| PATCH/DELETE | `/api/voices/{id}` | Ad değiştir / sil |
| POST | `/api/voices/{id}/samples` | Duygu kaydı ekle (`emotion`, `file`) |
| DELETE | `/api/voices/{id}/samples/{emotion}` | Duygu kaydını sil |
| POST | `/api/tts` | Metin → ses. Varsayılan **202 + iş**; `"wait": true` ile sonucu bekler |
| GET | `/api/jobs/{id}` | İş durumu / ilerleme / sonuç |
| POST | `/api/vc` | Ses → ses (`voice_id`, `file`, `wait`) |
| GET / DELETE | `/api/generations[/{id}]` | Geçmiş |

```bash
curl -X POST http://localhost:8000/api/tts -H "Content-Type: application/json" -d '{
  "text": "[heyecanlı] Merhaba İzmir! [fısıltı] Bu bir sır.",
  "voice_id": "<ses_id>", "language": "tr", "format": "mp3", "wait": true }'
```
`/api/tts` alanları: `text`, `voice_id`, `language`, `emotion` (tüm metin için), `exaggeration` (0.5), `cfg_weight` (0.45),
`temperature` (0.8), `speed` 0.7–1.3, `colloquial` (true), `punctuation_emotion` (true), `auto_emotion` (false),
`emotion_fx` (`off` | `light` | `full`, varsayılan off), `emotion_refs` (yalnızca full), `seed`, `format`, `wait`. Yanıttaki `params.chunks` her cümle için kullanılan duygu/referans/ayarı listeler.

## İyi sonuç için

- En büyük fark referanstır: 10–15 sn, sessiz oda, 20–30 cm mesafe, videoda konuşacağın enerjiyle.
- Duygu kayıtları ekle: türetilmiş referans iş görür, gerçek kayıt çok daha iyidir.
- Metni konuşur gibi yaz: kısa cümleler, `!` `?` `...`, "yani", "bakın" gibi doğal bağlaçlar.
- Ses çok hızlıysa `cfg_weight` 0.3–0.4 veya Hız 0.9.

## Sorumluluk
Arayüz ses eklerken izin onayı ister; her üretim Resemble AI'ın algılanamaz PerTh filigranını taşır.
Başkasının sesini izinsiz klonlamak yasal sorumluluk doğurur.
