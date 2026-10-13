# Sık sorulan sorular

**Doğallık ve ses kalitesi**

1. [Gülme neden yapay duyuluyor?](#1-gülme-neden-yapay-duyuluyor)
2. [Duygu yoğunluğu nasıl ayarlanır?](#2-duygu-yoğunluğu-nasıl-ayarlanır)
3. [Duygu neden zayıf çıkıyor?](#3-duygu-neden-zayıf-çıkıyor)
4. [Ses parçadan parçaya değişiyor, neden?](#4-ses-parçadan-parçaya-değişiyor-neden)
5. [Model cümleyi tekrar etti ya da takıldı. Kalite kontrol ne yapar?](#5-model-cümleyi-tekrar-etti-ya-da-takıldı-kalite-kontrol-ne-yapar)
6. [Kaydım gürültülü, ne yapabilirim?](#6-kaydım-gürültülü-ne-yapabilirim)
7. [Marka adını ya da bir sözcüğü yanlış okuyor](#7-marka-adını-ya-da-bir-sözcüğü-yanlış-okuyor)
8. [Konuşma dolguları ne zaman açılmalı?](#8-konuşma-dolguları-ne-zaman-açılmalı)
9. [Daha yavaş ya da daha hızlı konuşturmak için ne yapmalıyım?](#9-daha-yavaş-ya-da-daha-hızlı-konuşturmak-için-ne-yapmalıyım)

**Diyalog ve altyazı**

10. [Diyalogda anlatıcı kim?](#10-diyalogda-anlatıcı-kim)
11. [Altyazı sözcük zamanları ne kadar doğru?](#11-altyazı-sözcük-zamanları-ne-kadar-doğru)

**Donanım ve kurulum**

12. [GPU şart mı? GPU'da ve CPU'da ne kadar sürer?](#12-gpu-şart-mı-gpuda-ve-cpuda-ne-kadar-sürer)
13. [Ne kadar VRAM gerekir?](#13-ne-kadar-vram-gerekir)
14. [Mac'te nasıl çalıştırırım?](#14-macte-nasıl-çalıştırırım)
15. [Hangi dilleri destekliyor?](#15-hangi-dilleri-destekliyor)

**Kullanım, veriler ve haklar**

16. [Kendi sesim olmadan kullanabilir miyim?](#16-kendi-sesim-olmadan-kullanabilir-miyim)
17. [ElevenLabs'tan farkı ne?](#17-elevenlabstan-farkı-ne)
18. [Filigran nedir?](#18-filigran-nedir)
19. [Verilerim nerede duruyor?](#19-verilerim-nerede-duruyor)
20. [Bir seferde kaç karakter seslendirebilirim?](#20-bir-seferde-kaç-karakter-seslendirebilirim)
21. [Ticari olarak kullanabilir miyim?](#21-ticari-olarak-kullanabilir-miyim)
22. [Telefonla aldığım kayıt olur mu?](#22-telefonla-aldığım-kayıt-olur-mu)

---

### 1. Gülme neden yapay duyuluyor?

Model gülme, iç çekme, öksürme gibi sesleri gerçekten üretemez; kaydı olmayan `[gülme]` en yakın ünleme ("Hahaha!")
çevrilip konuşur gibi okunur. Çözüm: **gerçek tepki kaydı**. Sesler → ses kartı → **Gerçek tepkiler** bölümünden
gülmenizi (1–3 sn) bir kez kaydedin; o sesle yazılan her `[gülme]`, `[laughs]`, `[güler]` etiketinde sizin gülmeniz
çalınır, konuşmanın seviyesine oturtulur ve her seferinde hafif farklı duyulur. 15 tepki kaydedilebilir (gülme,
kahkaha, kıkırdama, iç çekme, hmm, of, nefes verme, öksürük, boğaz temizleme, esneme, ağlama, şaşırma, hı hı, mmm,
cık cık). Yönergeler: [Kayıt rehberi → Gerçek tepki kayıtları](KAYIT_REHBERI.md#8-gerçek-tepki-kayıtları).

Kayıt yoksa: tepkiyi az kullanın, cümle sonuna yazın (önceki cümleyle birlikte üretilir) ve gülümseyen bir ton için
çoğu zaman `[mutlu]` ya da `[samimi]` yeterlidir.

### 2. Duygu yoğunluğu nasıl ayarlanır?

Etiketin içinde: `[heyecanlı:1]` hafif (0,7), `[heyecanlı:2]` normal, `[heyecanlı:3]` güçlü (1,4); sözcükle
`[biraz üzgün]` (0,65), `[çok kızgın]` (1,35), `[aşırı heyecanlı]` (1,6); yüzdeyle `[şaşkın %120]` (50–160). Yoğunluk
duygunun vurgu, sadakat ve duraklama ayarlarını nötrden uzaklaştırır: heyecanlı daha coşkulu, üzgün daha durgun ve
yavaş olur. İki duyguyu harmanlamak için `[üzgün+umutlu]`, bölüm boyunca değiştirmek için `[heyecanlı→sakin]` ya da
`[sakinleşerek]`. Arayüzde etiket kutusunun **Yoğunluk** ve **Geçiş** satırları bunları yazar. Ayrıntı:
[Etiketler → Yoğunluk](ETIKETLER.md#3-duygu-yoğunluğu).

Yoğunluk referans kaydını değiştirmez; çok güçlü bir duygu için o duygunun kaydını eklemek her zaman daha etkilidir
(soru 3).

### 3. Duygu neden zayıf çıkıyor?

Bu modelde duyguyu en çok referans kaydın tonu belirler; nötr bir kayıttan güçlü bir öfke ya da coşku çıkmaz.
Etkiliden aza doğru:

1. **Duygu kaydı ekleyin:** Sesler → ses kartı → Duygu kayıtları. En büyük fark buradan gelir.
2. **Yoğunluğu artırın:** `[kızgın:3]`, `[çok heyecanlı]`.
3. **Vurguyu artırın:** "Duygu / vurgu" (`exaggeration`) 0,6–0,9; "Sese sadakat" (`cfg_weight`) 0,3–0,4.
4. **Noktalamayı kullanın:** `!`, `?` ve `...` duyguyu güçlendirir ("Noktalamaya göre duygu" açıkken).
5. **Uygun stili seçin:** reklam, spor-spikeri, duygusal gibi stiller ayarları birlikte değiştirir.
6. **Duyguyu metne yazın:** "Bu harika!" gibi duyguyu taşıyan sözcükler etiketten daha çok iş görür. Kısa cümleler
   kurun; tek cümlede çok sayıda farklı duygu etiketi kullanmayın.
7. **Ses işleme seviyesi:** "Hafif" duygular arasında şiddet farkı ekler; "Tam" (deneysel) perde, tempo ve fısıltı
   dönüşümü uygular ama sesi kimliğinden uzaklaştırabilir.

Not: 25 karakterden kısa parçalarda vurgu, bozulmayı önlemek için sınırlanır; tek sözcüklük cümleler yerine birkaç
sözcüklük cümleler kurun.

### 4. Ses parçadan parçaya değişiyor, neden?

Model uzun metni ~170 karakterlik parçalar hâlinde üretir ve her parçada tınıyı biraz farklı tutturabilir: biri daha
boğuk, biri daha gür. **Tutarlılık** katmanı (varsayılan açık; API `consistency`) her parçayı referans sesinizin uzun
dönem spektrumuna yumuşak bir EQ ile yaklaştırır (150–8000 Hz, en çok ±3 dB) ve ardışık parçalar arasındaki 4 dB'yi aşan
seviye sıçramalarını 2 dB yumuşatır; duygu farkları silinmez. Sonuçtaki "Tutarlılık" satırı ne kadar düzeltildiğini
gösterir. Hâlâ fark varsa:

- Duygu kayıtlarını temel kayıtla aynı oda ve mikrofonla alın (farklı odadaki kayıt, o duyguya geçince tınıyı değiştirir).
- "Sıcaklık"ı (`temperature`) 0,6–0,7'ye indirin, "Sese sadakat"i (`cfg_weight`) 0,5–0,6'ya çıkarın.
- Beğendiğiniz bir sonucun tohumunu sabitleyin; aynı ayarlarla aynı sesi yeniden alırsınız.
- Kaydın kalitesini artırın: gürültülü ya da yankılı referans parçalar arasında daha çok oynar.

### 5. Model cümleyi tekrar etti ya da takıldı. Kalite kontrol ne yapar?

Otoregresif modeller bazen bir cümleyi tekrar eder, ortada takılır, sona uzun sessizlik ekler, cümleyi yarıda keser
ya da vızıltı üretir. **Kalite kontrol** (varsayılan açık; API `qc`) her parçayı üretildiği anda ölçer ve 0–100 puanlar:
tekrar ya da aşırı uzunlukta **farklı tohumla**, takılma ya da vızıltıda **daha kararlı ayarlarla** (sıcaklık ≤ 0,6,
sadakat ≥ 0,4) yeniden üretir; sondaki fazla sessizliği ve cümle bittikten sonra eklenen anlamsız sesi **kırpar**,
tavana vuran sesin seviyesini düşürür. Parça başına en çok üç deneme yapılır, en iyisi seçilir. Sonuçtaki "Kalite kontrol" satırı ortalama puanı ve yeniden üretilen parça sayısını,
"Cümle cümle" listesi düşük puanlı (<60) parçanın nedenini gösterir.

Hâlâ sorunluysa: o cümleyi kısaltın ya da noktalamayla bölün, tek sözcüklük cümleleri birleştirin, "Sıcaklık"ı
düşürün, farklı bir tohum deneyin. Vızıltı ya da 50 Hz uğultusu sürekli çıkıyorsa referans kaydınızdaki uğultu sese
geçiyordur: **Kaydı iyileştir** (soru 6). Kalite kontrol bozuk parçaları yeniden ürettiği için süre bazen uzar; hızlı
deneme için kapatabilirsiniz.

### 6. Kaydım gürültülü, ne yapabilirim?

En iyi çözüm sessiz bir odada yeniden kaydetmektir ([Kayıt rehberi](KAYIT_REHBERI.md)). Olmuyorsa ses kartındaki
**✨ Kaydı iyileştir**: DC kaymasını, tıkları, elektrik uğultusunu (50/60 Hz) ve arka plan gürültüsünü (en çok 12 dB)
temizler, 70 Hz altını keser, seviyeyi dengeler. Analiz puanı en az 3 artarsa uygulanır; artmazsa **Yine de uygula**
diyebilirsiniz. Özgün kayıt yedekte durur, **↺ Geri al** ile dönülür. Yankıyı, kırpılmayı, telefon/WhatsApp kaydının
dar bandını ve arka plandaki müziği düzeltmez. Yalnızca temel kayda uygulanır.

### 7. Marka adını ya da bir sözcüğü yanlış okuyor

- **Kalıcı:** **Telaffuz** sekmesinde sözcüğü ve okunuşunu ekleyin ("Shopify" → "Şopifay"). Genel sözlük her seste,
  ses sözlüğü yalnızca seçtiğiniz seste geçerlidir; **Dene** modelin okuyacağı metni gösterir. Büyük/küçük harf fark
  etmez, ekler korunur ("Shopify'da" → "Şopifay'da"), çok sözcüklü adlar da olur ("Red Bull" → "Red Bul").
- **Tek seferlik:** metinde `{Shopify|Şopifay}` yazın.
- Okunuşu Türkçe yazılışla verin ("Klod", "Ayfon", "Yutub"); kısaltmanın harf harf okunmasını istemiyorsanız açık
  hâlini yazın. 150'den fazla marka zaten tanımlıdır; eski `pronunciations.json` dosyası da çalışmaya devam eder.

Sözlük yalnızca Türkçe metinde uygulanır.

### 8. Konuşma dolguları ne zaman açılmalı?

**Konuşma dolguları** (varsayılan kapalı; API `fillers`) metne ara sıra "Yani,", "Hani,", "İşte,", "Şey,", "Ya,",
"Bak,", "Valla," ile başlayan cümle, virgülden sonra "yani"/"işte" ve düz cümle sonunda "ya"/"yani"/"işte" ekler:
cümlelerin yaklaşık %8'ine, her dört cümlede en çok birine. Sorulara, tırnak içine ve etiketlere dokunmaz.

- **Açın:** sohbet, vlog, podcast, karakter diyaloğu, "hazırlıksız konuşuyormuş gibi" duyulması gereken metinler.
- **Kapalı tutun:** reklam, duyuru, talimat ve sözcüğü sözcüğüne okunması gereken her şey. Haber, belgesel, sesli
  kitap, eğitim, müşteri hizmeti ve anlatıcı stillerinde zaten eklenmez.
- Dolgular altyazıya da girer; tohum sabitse aynı yerlere eklenir.

Ayrı bir katman olan **sohbet kısaltmaları** (varsayılan açık; API `chat_speak`) "slm, nbr, tmm, tşk, yrn, grs" gibi
yazışma kısaltmalarını açar ("selam, naber, tamam, teşekkürler, yarın, görüşürüz"). "sa"/"as" yalnızca tek başına,
"ok" yalnızca tek sözcükse açılır; "TSK" gibi büyük harfli kurum kısaltmalarına dokunulmaz.

### 9. Daha yavaş ya da daha hızlı konuşturmak için ne yapmalıyım?

| Ne | Nasıl |
|---|---|
| Tüm metni yavaşlat/hızlandır | **Hız** (`speed`, 0,7–1,3). Perde korunarak tempo değişir; 0,9–1,1 arası en doğal sonucu verir. |
| Metnin bir bölümü | `[hız:0.85]` … `[hız]` (0,7–1,3); ya da `[yavaş]` / `[hızlı]` (×0,9 / ×1,1) … `[normal]` |
| Cümle aralarını aç/kıs | **Duraklama** (`pause_scale`, 0,5–2,0); tek bir yer için `[duraklama]` ya da `[1.5 sn]` |
| Daha ağır, tane tane konuşma | "Sese sadakat" (`cfg_weight`) 0,3–0,4 |
| Bir kullanım için hazır tempo | Stil: `masal`, `belgesel`, `sesli-kitap` daha yavaş; `reklam`, `spor-spikeri` daha hızlı |

Tempo değişiklikleri ffmpeg gerektirir. En kalıcı çözüm referans kaydıdır: klon, kaydınızdaki konuşma hızını ve
duraklama ritmini taklit eder.

### 10. Diyalogda anlatıcı kim?

Metnin başındaki, adı olmayan satırlar anlatıcıdır. Anlatıcının sesi Diyalog sekmesindeki **Anlatıcı** satırında
seçilir (API: `narrator_voice_id`; verilmezse `voice_id`, o da yoksa modelin varsayılan sesi). Bir konuşmacı
konuştuktan sonra adsız satır **o konuşmacının devamıdır**; araya anlatım koymak için satırı `Anlatıcı:` ile başlatın.
Diyalog sekmesi `Anlatıcı:` ve `Anlatan:` satırlarını anlatıcı sesine bağlar; API'de bunlar sıradan konuşmacı adıdır
(`speakers` içinde ses verin). Sesi seçilmemiş her konuşmacı modelin varsayılan sesiyle okunur. Biçimler ve sınırlar:
[Etiketler → Diyalog biçimleri](ETIKETLER.md#12-diyalog-biçimleri).

Aşağıdaki örnekte ilk ve son satırı anlatıcı okur:

```
Kafede iki eski arkadaş karşılaşır.
Ayşe: Selam!
Mehmet: [gülme] Sen misin?
Anlatıcı: Saatlerce konuştular.
```

### 11. Altyazı sözcük zamanları ne kadar doğru?

Parça (cümle grubu) başlangıç ve bitişleri gerçek ses uzunluklarından ve uygulanan duraklamalardan hesaplanır;
dosyayla örtüşür. **Sözcük** zamanları ise ses hizalaması değil, parça süresinin sözcüklerin hece sayısına göre
paylaştırılmasıdır: karaoke tarzı vurgu ve SRT/VTT blokları için yeterli, dudak senkronu ya da kare hassasiyetinde
kurgu için değil. Bilinmesi gerekenler:

- Altyazı metni modelin **okuduğu** metindir: sayılar yazıyla ("on iki lira elli kuruş"), konuşma dili uygulanmış
  ("gelicem"), dolgular dahil. Yazılı metni görmek istiyorsanız konuşma dilini kapatın.
- Etiketler ve gerçek tepki kayıtları altyazıya girmez; tepkinin süresi blokların arasında boşluk olarak kalır.
- Bloklar satırda en çok 42 karakter, 2 satır ve 7 sn'dir; diyalogda aynı bloğa düşen konuşmacılar "- " ile ayrılır.
- Arayüz SRT, VTT ve JSON indirir; API ayrıca LRC verir. Altyazı seçeneği kapalı üretilen kaydın altyazısı yoktur.

### 12. GPU şart mı? GPU'da ve CPU'da ne kadar sürer?

Hayır, ama hız büyük ölçüde cihaza bağlıdır:

| Cihaz | 10 sn ses için yaklaşık süre |
|---|---|
| NVIDIA GPU (6 GB+ VRAM) | 2–5 sn |
| Apple Silicon (M1–M4, `mps`) | GPU'ya yakın, modele ve çipe göre değişir |
| Yalnızca CPU (modern 8 çekirdek) | 1–3 dk; 1 dk ses ≈ 6–18 dk |

- İlk üretim modelin yüklenmesini de içerir; `PRELOAD=1` (varsayılan) bunu açılışa taşır.
- **Kalite kontrol** bozuk bulduğu parçayı en çok iki kez daha üretir; o parçanın süresi 2–3 katına çıkabilir.
  Tutarlılık, altyazı ve tepki kayıtları model üretimine göre küçük bir ek süre getirir. Diyalogda her satır ayrı
  parça olduğundan kısa satırlı senaryolar, aynı uzunluktaki düz metinden biraz daha uzun sürebilir.
- CPU'da hızlandırmak için: varyant sayısını 1'de tutun, ayarları önce kısa bir parçayla deneyin, gerekirse kalite
  kontrolü kapatın. Üretim arka planda sürer; hazır parçaları beklerken dinleyebilirsiniz.

Cihaz kendiliğinden seçilir (`DEVICE` boşken); üst çubukta hangi cihazın kullanıldığı görünür.

### 13. Ne kadar VRAM gerekir?

6 GB ve üstü önerilir; 8 GB rahattır. Daha az VRAM'li kartlarda kısa metinler çalışabilir ama "CUDA out of memory"
hatası alabilirsiniz. Böyle olursa GPU kullanan diğer uygulamaları kapatın, varyant sayısını 1 yapın ve
`CHUNK_CHARS=120` gibi daha küçük parça boyu deneyin; olmazsa `DEVICE=cpu`. Üretimler tek bir kuyrukta sırayla
yapıldığı için aynı anda birden fazla istek VRAM kullanımını katlamaz.

### 14. Mac'te nasıl çalıştırırım?

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

### 14b. Mac'te üretim çok yavaş (gerçek zamanın 4–5 katı). Ne yapabilirim?

PyTorch'un `mps` yolu Chatterbox'ta yavaştır. `pip install mlx-audio` kurup `TTS_BACKEND=chatterbox-mlx ./run.sh` ile
MLX arka ucunu deneyin; hızı `cd backend && python -m app.bench --backend chatterbox-mlx --ref ses.wav` ile ölçün.
Kalite kontrol bozuk parçaları yeniden ürettiği için bazı parçalar 2–3 kez üretilir; hız öncelikliyse istekte
`"qc": false` verin. Not: MLX arka ucu `T3_FINETUNED` ince ayarını uygulamaz (ağırlıklar MLX'e dönüştürülmelidir).

### 14c. Ses düz ve robotik; ayarlar fark etmiyor. Neden?

Türkçedeki düzlük büyük ölçüde modelin kendi tonlama alışkanlığından gelir; `exaggeration`/`cfg_weight` aralığı ancak
biraz açar. Önce ölçün: `python -m app.bench --reference-only ses.wav` referansınızın aralığını, `python -m app.bench
--backend chatterbox --ref ses.wav` klonun aralığını verir. Klon referansın altında kalır; daha coşkulu bir referans
(≥ 16 yarım ton) ilk ve ucuz çözümdür. Yetmezse ince ayar: [finetune/README.md](../finetune/README.md).

### 15. Hangi dilleri destekliyor?

Chatterbox Multilingual'ın 23 dili: Türkçe, İngilizce, Almanca, Fransızca, İspanyolca, İtalyanca, Portekizce,
Felemenkçe, Lehçe, Rusça, Arapça, İbranice, Hintçe, Japonca, Korece, Çince, Yunanca, Danca, Fince, İsveççe, Norveççe,
Malayca ve Svahili.

Türkçe'ye özel katmanlar (ayrıntılı normalizasyon, konuşma dili, telaffuz sözlüğü, sohbet kısaltmaları, konuşma
dolguları, Türkçe bağlaçlara göre duraklama) yalnızca Türkçe metinde çalışır. Etiketler, gerçek tepkiler, `{okunuş}`,
tutarlılık ve altyazı her dilde çalışır. Diyalogda ad algılama büyük harfle başlayan adlara bakar (büyük harfi olmayan
yazılarda `[ses:Ad]` kullanın); kalite kontrolün konuşma hızı ölçütleri Türkçeye göre ayarlıdır. Türkçe bir ses başka
dilde de konuşturulabilir; aksan bir miktar taşınır.

### 16. Kendi sesim olmadan kullanabilir miyim?

Evet. Ses seçmeden üretirseniz (`voice_id` boş) modelin yerleşik varsayılan sesi kullanılır; bu ses, öncesinde hangi
klonla üretim yapılmış olursa olsun hep aynı kalır. Diyalogda sesi seçilmemiş konuşmacılar da bu sesle okunur.
Başka birinin sesini kullanacaksanız o kişiden açık izin almanız gerekir (bir seslendirme sanatçısı, gönüllü bir
arkadaş…). SesKlon'da metinden yeni ses "tasarlama" özelliği yoktur; her ses gerçek bir kayıttan gelir.

### 17. ElevenLabs'tan farkı ne?

| | SesKlon | ElevenLabs gibi bulut hizmetleri |
|---|---|---|
| Nerede çalışır | Kendi bilgisayarınızda ya da sunucunuzda | Hizmet sağlayıcının sunucularında |
| Ücret | Ücretsiz (donanım ve elektrik sizin) | Abonelik / karakter başına ücret |
| Veriler | Metin ve kayıtlar makinenizden çıkmaz | Metin ve kayıtlar sağlayıcıya gönderilir |
| Türkçe metin işleme | Türkçe'ye özel normalizasyon, konuşma dili, telaffuz sözlüğü, sohbet kısaltmaları, Türkçe bağlaçlara göre duraklama | Genel, çok dilli işleme |
| Sözsüz sesler | Kendi gerçek gülme, iç çekme… kayıtlarınız; yoksa ünlem | Modelin ürettiği sesler |
| Ses kaynağı | Yalnızca kendi kayıtlarınız | Geniş hazır ses kütüphanesi, ses tasarımı ve ek hizmetler |
| Hız | GPU'nuza bağlı | Sağlayıcının altyapısına bağlı |
| Etiketler | `[heyecanlı:3]`, `[üzgün+umutlu]`, `[heyecanlı→sakin]`, `[fısıltı]`, `[gülme]`…; İngilizce adlar (`[excited]`, `[whispers]`, `[laughs]`) da çalışır | Kendi etiket seti |

Sonuç büyük ölçüde referans kaydınıza bağlıdır. Hangisinin işinize daha uygun olduğunu görmek için aynı metni, aynı
sesle iki sistemde deneyip dinleyin.

### 18. Filigran nedir?

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

### 19. Verilerim nerede duruyor?

| | Docker | Docker'sız |
|---|---|---|
| Sesler, duygu ve tepki kayıtları | `sesklon-data` birimi → `/data/voices/` | `backend/data/voices/` |
| Ses sözlükleri, iyileştirme yedekleri | `/data/voices/<ses_id>.lexicon.json`, `*.orig.wav` | `backend/data/voices/` |
| Genel telaffuz sözlüğü | `/data/lexicon.json` | `backend/data/lexicon.json` |
| Eski okunuş sözlüğü | `/data/pronunciations.json` | `backend/data/pronunciations.json` |
| Üretimler | `/data/outputs/` | `backend/data/outputs/` |
| Veritabanı (sesler, geçmiş, analizler, zaman çizelgeleri) | `/data/sesklon.db` | `backend/data/sesklon.db` |
| Model önbelleği (~2 GB) | `/data/hf-cache/` | `~/.cache/huggingface/` |

Docker'sız çalıştırmada veri klasörü `DATA_DIR` ile değiştirilebilir. Yedek almak için bu klasörü (Docker'da birimi)
kopyalayın; tek bir sesi taşımak içinse ses kartındaki **Yedekle (zip)** yeterlidir (duygu ve tepki kayıtları dahil,
ses sözlüğü hariç).

İnternete yalnızca kurulumda (pip, npm, Docker imajları) ve modelin ilk indirilmesinde (Hugging Face) çıkılır. Metinler,
kayıtlar ve üretimler hiçbir yere gönderilmez. Arayüz yazı tipini Google Fonts'tan ister; bağlantı yoksa sistem yazı
tipi kullanılır. Model indirildikten sonra SesKlon internetsiz çalışır; tamamen çevrimdışı kullanım için
`HF_HUB_OFFLINE=1` tanımlayın.

`/files/...` altındaki ses dosyaları API anahtarı istemez (adları tahmin edilemeyen rastgele kimliklerdir). Sunucuyu
internete açacaksanız `API_KEY` tanımlayın ve önüne HTTPS'li bir ters vekil koyun.

### 20. Bir seferde kaç karakter seslendirebilirim?

Tek istekte varsayılan en fazla **5000 karakter** (`MAX_TEXT_CHARS`; diyalogda tüm senaryo), bu da Türkçe'de yaklaşık
5–6 dakikalık sese denk gelir. Metin cümle sınırlarından ~170 karakterlik parçalara (`CHUNK_CHARS`) bölünerek üretilir;
iş kuyruğu sayesinde uzun metinlerde zaman aşımı olmaz ve hazır parçalar üretim sürerken dinlenebilir. Daha uzun
metinler (sesli kitap bölümleri gibi) için metni bölümlere ayırın ya da `MAX_TEXT_CHARS` değerini artırın; süre ve
bellek metinle birlikte artar.

### 21. Ticari olarak kullanabilir miyim?

Lisans açısından evet: SesKlon MIT, Chatterbox modeli MIT lisanslıdır. Ancak lisans, **sesin** kullanım hakkını vermez:

- Ses size ait olmalı ya da sahibinden (tercihen yazılı) izin almış olmalısınız; ses kişisel veridir (KVKK). Bu, gerçek
  tepki kayıtları için de geçerlidir.
- Yayın platformlarının yapay içerik bildirme kurallarına uyun.
- Üretimlerdeki PerTh filigranı yerinde kalır.

Bu bir hukuki görüş değildir; ticari projelerde bir hukukçuya danışın.

### 22. Telefonla aldığım kayıt olur mu?

Olur; iyi bir telefon kaydı çoğu dizüstü mikrofonundan iyidir. Ses kaydedici uygulamasını en yüksek kalitede
(iPhone'da "Kayıpsız") kullanın, telefonu 20–30 cm uzağa koyun, gürültü azaltma filtrelerini kapatın ve dosyayı
WhatsApp sesli mesajı olarak değil, **dosya olarak** aktarın. WhatsApp ve telefon görüşmesi kayıtları dar bantlıdır;
analiz bunu `low_bandwidth` olarak işaretler ve klon boğuk çıkar (Kaydı iyileştir bunu düzeltemez). Ayrıntılar:
[Kayıt rehberi → Telefonla kayıt](KAYIT_REHBERI.md#3-telefonla-kayıt).
