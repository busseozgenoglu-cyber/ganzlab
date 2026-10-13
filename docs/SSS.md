# Sık sorulan sorular

1. [GPU şart mı?](#1-gpu-şart-mı)
2. [CPU'da ne kadar sürer?](#2-cpuda-ne-kadar-sürer)
3. [Hangi dilleri destekliyor?](#3-hangi-dilleri-destekliyor)
4. [Kendi sesim olmadan kullanabilir miyim?](#4-kendi-sesim-olmadan-kullanabilir-miyim)
5. [ElevenLabs'tan farkı ne?](#5-elevenlabstan-farkı-ne)
6. [Filigran nedir?](#6-filigran-nedir)
7. [Verilerim nerede duruyor?](#7-verilerim-nerede-duruyor)
8. [Mac'te nasıl çalıştırırım?](#8-macte-nasıl-çalıştırırım)
9. [Ne kadar VRAM gerekir?](#9-ne-kadar-vram-gerekir)
10. [Bir seferde kaç karakter seslendirebilirim?](#10-bir-seferde-kaç-karakter-seslendirebilirim)
11. [Ticari olarak kullanabilir miyim?](#11-ticari-olarak-kullanabilir-miyim)
12. [Telefonla aldığım kayıt olur mu?](#12-telefonla-aldığım-kayıt-olur-mu)
13. [Duygu neden zayıf çıkıyor?](#13-duygu-neden-zayıf-çıkıyor)
14. [Gülme neden yapay duyuluyor?](#14-gülme-neden-yapay-duyuluyor)
15. [Daha yavaş ya da daha hızlı konuşturmak için ne yapmalıyım?](#15-daha-yavaş-ya-da-daha-hızlı-konuşturmak-için-ne-yapmalıyım)

---

### 1. GPU şart mı?

Hayır. SesKlon üç cihazda çalışır:

| Cihaz | 10 sn ses için yaklaşık süre |
|---|---|
| NVIDIA GPU (6 GB+ VRAM) | 2–5 sn |
| Apple Silicon (M1–M4, `mps`) | GPU'ya yakın, modele ve çipe göre değişir |
| Yalnızca CPU | 1–3 dk |

Cihaz kendiliğinden seçilir (`DEVICE` boşken); üst çubukta hangi cihazın kullanıldığı görünür. Kısa metinler için CPU
yeterlidir; düzenli ve uzun üretim için GPU önerilir.

### 2. CPU'da ne kadar sürer?

Modern 8 çekirdekli bir işlemcide 10 sn ses için 1–3 dk; süre metin uzunluğuyla doğru orantılı artar (1 dk ses ≈ 6–18
dk). İlk üretim modelin yüklenmesini de içerir; `PRELOAD=1` (varsayılan) bunu açılışa taşır. Hızlandırmak için:
varyant sayısını 1'de tutun, önce kısa bir parçayla ayarları deneyin, uzun metni üretirken bilgisayarda başka ağır iş
çalıştırmayın. Üretim arka planda sürer; canlı önizleme sayesinde hazır olan parçaları beklerken dinleyebilirsiniz.

### 3. Hangi dilleri destekliyor?

Chatterbox Multilingual'ın 23 dili: Türkçe, İngilizce, Almanca, Fransızca, İspanyolca, İtalyanca, Portekizce,
Felemenkçe, Lehçe, Rusça, Arapça, İbranice, Hintçe, Japonca, Korece, Çince, Yunanca, Danca, Fince, İsveççe, Norveççe,
Malayca ve Svahili.

Türkçe'ye özel katmanlar (ayrıntılı normalizasyon, konuşma dili, Türkçe bağlaçlara göre duraklama) yalnızca Türkçe
metinde çalışır. Diğer dillerde temel sayı okuma, nefes, oda tonu ve mastering uygulanır. Türkçe bir ses başka dilde
de konuşturulabilir; aksan bir miktar taşınır.

### 4. Kendi sesim olmadan kullanabilir miyim?

Evet. Ses seçmeden üretirseniz (`voice_id` boş) modelin yerleşik varsayılan sesi kullanılır. Başka birinin sesini
kullanacaksanız o kişiden açık izin almanız gerekir (bir seslendirme sanatçısı, gönüllü bir arkadaş…). SesKlon'da
metinden yeni ses "tasarlama" özelliği yoktur; her ses gerçek bir kayıttan gelir.

### 5. ElevenLabs'tan farkı ne?

| | SesKlon | ElevenLabs gibi bulut hizmetleri |
|---|---|---|
| Nerede çalışır | Kendi bilgisayarınızda ya da sunucunuzda | Hizmet sağlayıcının sunucularında |
| Ücret | Ücretsiz (donanım ve elektrik sizin) | Abonelik / karakter başına ücret |
| Veriler | Metin ve kayıtlar makinenizden çıkmaz | Metin ve kayıtlar sağlayıcıya gönderilir |
| Türkçe metin işleme | Türkçe'ye özel normalizasyon, konuşma dili, Türkçe bağlaçlara göre duraklama | Genel, çok dilli işleme |
| Ses kaynağı | Yalnızca kendi kayıtlarınız | Geniş hazır ses kütüphanesi, ses tasarımı ve ek hizmetler |
| Hız | GPU'nuza bağlı | Sağlayıcının altyapısına bağlı |
| Etiketler | `[heyecanlı]`, `[fısıltı]`, `[gülme]`…; İngilizce adlar (`[excited]`, `[whispers]`, `[laughs]`) da çalışır | Kendi etiket seti |

Sonuç büyük ölçüde referans kaydınıza bağlıdır. Hangisinin işinize daha uygun olduğunu görmek için aynı metni, aynı
sesle iki sistemde deneyip dinleyin.

### 6. Filigran nedir?

Chatterbox, ürettiği her sese Resemble AI'ın **PerTh** adlı, kulakla duyulmayan bir filigranını gömer. Amaç, sesin
yapay olarak üretildiğinin sonradan doğrulanabilmesidir; Resemble AI'a göre MP3 sıkıştırmaya ve yaygın düzenlemelere
dayanıklıdır. Filigran üretim sırasında model tarafından eklenir; SesKlon filigran eklemez ve kaldırmaz. Kaldırmaya
çalışmayın. Bir dosyada filigran olup olmadığını Resemble AI'ın açık kaynak aracıyla denetleyebilirsiniz (`perth`
paketi Chatterbox ile birlikte kurulur; SesKlon'un sanal ortamında hazırdır):

```python
import librosa
import perth

wav, sr = librosa.load("uretim.wav", sr=None)
print(perth.PerthImplicitWatermarker().get_watermark(wav, sample_rate=sr))   # 1.0 = filigranlı, 0.0 = filigransız
```

### 7. Verilerim nerede duruyor?

| | Docker | Docker'sız |
|---|---|---|
| Sesler ve duygu kayıtları | `sesklon-data` birimi → `/data/voices/` | `backend/data/voices/` |
| Üretimler | `/data/outputs/` | `backend/data/outputs/` |
| Veritabanı (sesler, geçmiş, analizler) | `/data/sesklon.db` | `backend/data/sesklon.db` |
| Okunuş sözlüğü | `/data/pronunciations.json` | `backend/data/pronunciations.json` |
| Model önbelleği (~2 GB) | `/data/hf-cache/` | `~/.cache/huggingface/` |

Docker'sız çalıştırmada veri klasörü `DATA_DIR` ile değiştirilebilir. Yedek almak için bu klasörü (Docker'da birimi)
kopyalayın; tek bir sesi taşımak içinse ses kartındaki **Yedekle (zip)** yeterlidir.

İnternete yalnızca kurulumda (pip, npm, Docker imajları) ve modelin ilk indirilmesinde (Hugging Face) çıkılır. Metinler,
kayıtlar ve üretimler hiçbir yere gönderilmez. Arayüz yazı tipini Google Fonts'tan ister; bağlantı yoksa sistem yazı
tipi kullanılır. Model indirildikten sonra SesKlon internetsiz çalışır; tamamen çevrimdışı kullanım için
`HF_HUB_OFFLINE=1` tanımlayın.

`/files/...` altındaki ses dosyaları API anahtarı istemez (adları tahmin edilemeyen rastgele kimliklerdir). Sunucuyu
internete açacaksanız `API_KEY` tanımlayın ve önüne HTTPS'li bir ters vekil koyun.

### 8. Mac'te nasıl çalıştırırım?

Apple Silicon (M1–M4) Mac'te Docker yerine `./run.sh` kullanın; macOS'taki Docker GPU'ya erişemez, yalnızca CPU ile
çalışır.

```bash
brew install python@3.11 node ffmpeg git
./run.sh
```

Cihaz kendiliğinden `mps` seçilir. Python'un arm64 olduğundan emin olun
(`python3 -c "import platform; print(platform.machine())"` → `arm64`); Rosetta altındaki x86 Python GPU'yu
kullanamaz. Bir işlem MPS'te hata verirse `PYTORCH_ENABLE_MPS_FALLBACK=1 ./run.sh` ya da `DEVICE=cpu` deneyin. Intel
Mac'ler yalnızca CPU ile çalışır.

### 9. Ne kadar VRAM gerekir?

6 GB ve üstü önerilir; 8 GB rahattır. Daha az VRAM'li kartlarda kısa metinler çalışabilir ama "CUDA out of memory"
hatası alabilirsiniz. Böyle olursa GPU kullanan diğer uygulamaları kapatın, varyant sayısını 1 yapın ve
`CHUNK_CHARS=120` gibi daha küçük parça boyu deneyin; olmazsa `DEVICE=cpu`. Üretimler tek bir kuyrukta sırayla
yapıldığı için aynı anda birden fazla istek VRAM kullanımını katlamaz.

### 10. Bir seferde kaç karakter seslendirebilirim?

Tek istekte varsayılan en fazla **5000 karakter** (`MAX_TEXT_CHARS`), bu da Türkçe'de yaklaşık 5–6 dakikalık sese denk
gelir. Metin cümle sınırlarından ~170 karakterlik parçalara (`CHUNK_CHARS`) bölünerek üretilir; iş kuyruğu sayesinde
uzun metinlerde zaman aşımı olmaz ve hazır parçalar üretim sürerken dinlenebilir. Daha uzun metinler (sesli kitap
bölümleri gibi) için metni bölümlere ayırın ya da `MAX_TEXT_CHARS` değerini artırın; süre ve bellek metinle birlikte
artar.

### 11. Ticari olarak kullanabilir miyim?

Lisans açısından evet: SesKlon MIT, Chatterbox modeli MIT lisanslıdır. Ancak lisans, **sesin** kullanım hakkını vermez:

- Ses size ait olmalı ya da sahibinden (tercihen yazılı) izin almış olmalısınız; ses kişisel veridir (KVKK).
- Yayın platformlarının yapay içerik bildirme kurallarına uyun.
- Üretimlerdeki PerTh filigranı yerinde kalır.

Bu bir hukuki görüş değildir; ticari projelerde bir hukukçuya danışın.

### 12. Telefonla aldığım kayıt olur mu?

Olur; iyi bir telefon kaydı çoğu dizüstü mikrofonundan iyidir. Ses kaydedici uygulamasını en yüksek kalitede
(iPhone'da "Kayıpsız") kullanın, telefonu 20–30 cm uzağa koyun, gürültü azaltma filtrelerini kapatın ve dosyayı
WhatsApp sesli mesajı olarak değil, **dosya olarak** aktarın. WhatsApp ve telefon görüşmesi kayıtları dar bantlıdır;
analiz bunu `low_bandwidth` olarak işaretler ve klon boğuk çıkar. Ayrıntılar:
[Kayıt rehberi → Telefonla kayıt](KAYIT_REHBERI.md#3-telefonla-kayıt).

### 13. Duygu neden zayıf çıkıyor?

Bu modelde duyguyu en çok referans kaydın tonu belirler; nötr bir kayıttan güçlü bir öfke ya da coşku çıkmaz.
Etkiliden aza doğru:

1. **Duygu kaydı ekleyin:** Sesler → ses kartı → Duygu kayıtları. En büyük fark buradan gelir.
2. **Vurguyu artırın:** "Duygu / vurgu" (`exaggeration`) 0,6–0,9; "Sese sadakat" (`cfg_weight`) 0,3–0,4.
3. **Noktalamayı kullanın:** `!`, `?` ve `...` duyguyu güçlendirir ("Noktalamaya göre duygu" açıkken).
4. **Uygun stili seçin:** reklam, spor-spikeri, duygusal gibi stiller ayarları birlikte değiştirir.
5. **Duyguyu metne yazın:** "Bu harika!" gibi duyguyu taşıyan sözcükler etiketten daha çok iş görür. Kısa cümleler
   kurun; tek cümlede çok sayıda farklı duygu etiketi kullanmayın.
6. **Ses işleme seviyesi:** "Hafif" duygular arasında şiddet farkı ekler; "Tam" (deneysel) perde, tempo ve fısıltı
   dönüşümü uygular ama sesi kimliğinden uzaklaştırabilir.

Not: Çok kısa parçalarda vurgu, bozulmayı önlemek için sınırlanabilir; tek sözcüklük cümleler yerine birkaç sözcüklük
cümleler kurun.

### 14. Gülme neden yapay duyuluyor?

Model gülme, iç çekme, ağlama gibi sözsüz sesleri gerçekten üretemez. SesKlon `[gülme]` gibi etiketleri en yakın
konuşulabilir ünleme çevirir ("Hahaha!", iç çekme için "Ahh...") ve cümlenin içine yerleştirir; model bunu konuşur
gibi seslendirir. Daha doğal sonuç için:

- Sözsüz etiketleri az kullanın; `[kıkırdama]` ("Hihihi!") çoğu zaman `[kahkaha]`dan doğal durur.
- Gülmeyi tonla verin: `[mutlu]` ya da `[samimi]` ile gülümseyen bir ses çoğu durumda yeterlidir.
- Gerçek bir gülme gerekiyorsa kendi gülmenizi kaydedip montajda ekleyin.

### 15. Daha yavaş ya da daha hızlı konuşturmak için ne yapmalıyım?

| Ne | Nasıl |
|---|---|
| Tüm metni yavaşlat/hızlandır | **Hız** (`speed`, 0,7–1,3). Perde korunarak tempo değişir; 0,9–1,1 arası en doğal sonucu verir. |
| Metnin bir bölümü | `[yavaş]` … `[hızlı]` … `[normal]` etiketleri |
| Cümle aralarını aç/kıs | **Duraklama** (`pause_scale`, 0,5–2,0); tek bir yer için `[duraklama]` ya da `[1.5 sn]` |
| Daha ağır, tane tane konuşma | "Sese sadakat" (`cfg_weight`) 0,3–0,4 |
| Bir kullanım için hazır tempo | Stil: `masal`, `belgesel`, `sesli-kitap` daha yavaş; `reklam`, `spor-spikeri` daha hızlı |

En kalıcı çözüm referans kaydıdır: klon, kaydınızdaki konuşma hızını ve duraklama ritmini taklit eder. İstediğiniz
tempoda yeni bir kayıt almak çoğu zaman ayarlarla oynamaktan iyi sonuç verir.
