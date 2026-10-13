# Değişiklik günlüğü

Bu dosyadaki önemli değişiklikler sürüm sürüm listelenir. Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/)
düzenine, sürüm numaraları [Anlamsal Sürümleme](https://semver.org/lang/tr/)'ye uyar.

## 3.0.0 — 2026-10-13

"Doğallık" sürümü: Türkçe metin işleme derinleşti; duraklama, nefes, oda tonu ve mastering ile konuşma ritmi
insanlaştı; referans kaydı artık analiz edilip üretime girdi olarak kullanılıyor. v2 istemcileri değişmeden çalışır
(yeni alanların hepsi isteğe bağlıdır); varsayılan çıktının sesi ise değişti (bkz. [Yükseltme notları](#v2den-v3e-yükseltme)).

### Eklendi

**Türkçe metin normalizasyonu**
- Para kuruş/sentiyle: "12,50 TL" → "on iki lira elli kuruş", "$1,250.75" → "bin iki yüz elli dolar yetmiş beş sent";
  ₺ $ € £, TL/TRY/USD/EUR/GBP, "2,5 milyar $", "500 bin TL'ye".
- Saat ("14:30", "09.30", "saat 5'te", "09:00-18:00"), tarih ("12.10.2026", "2026-10-12", "12/2024") ve dönemler ("1990'larda").
- Kısaltmalar harf harf ("ABD" → "a be de", "KDV" → "ka de ve"), sözcük gibi okunanlar ("NATO", "TÜBİTAK"), yaygın
  İngilizce kısaltmalar ("SMS" → "es em es", "PDF", "USB"), harf-rakam birleşimleri ("4K", "5G", "MP3", "A101").
- Roma rakamları ve sıra sayıları ("II. Dünya Savaşı", "XIV. Louis", "21. yüzyıl", "3'üncüsü").
- Telefon numaraları gruplu okunur ("0532 123 45 67", "+90 …", "444 0 444"); IBAN, kart numarası, URL ve e-posta.
- Matematik ve aralıklar: "5x3", "5-3=2", "±5", "1/2" → "yarım", "3/4" → "dörtte üç", "3+1 daire", "3-4 kişi", "%20-30".
- Birimler: km², kWh, mAh, fps, °C, km/sa ve daha fazlası; "10K takipçi" → "on bin takipçi".
- 150+ marka ve yabancı sözcük okunuşu ("YouTube" → "Yutub", "iPhone" → "Ayfon"); `DATA_DIR/pronunciations.json` ile
  genişletilebilir.
- Kesme işaretiyle yazılmış ekler okunuşa ünlü uyumu ve ünsüz benzeşmesiyle bağlanır ("2024'te" → "iki bin yirmi
  dörtte", "150 TL'ye" → "yüz elli liraya", "ABD'de" → "a be dede").
- Emoji, emotikon ve görünmez karakter temizliği; uzun tire ve parantezler duraklamaya dönüşür.
- Türkçe büyük/küçük harf dönüşümü (İ/ı) tüm modüllerde ortak yardımcıyla (`tr.py`) yapılır.

**Konuşma dili seviyeleri** (`colloquial`)
- `off` (dokunma), `light` (varsayılan: "gelicem", "bişey", "bi dakka", "naber", "di mi", "yapıyım"), `full` (ek olarak
  "geliyom", "böle/şöle", "diil"). Özel adlara, kısaltmalara ve yabancı sözcüklere dokunulmaz.

**Doğal prozodi** (`prosody.py`)
- Bağlama göre duraklama: bağlaçla ("ama", "çünkü", "yani"…) başlayan cümleden önce %35 kısa, soru → kısa cevap %20
  kısa, çok uzun cümleden sonra %15 uzun; ±%12 titreşim; 60–2500 ms; `pause_scale` (0,5–2,0).
- Nefes (`breaths`): uzun konuşmada aralıklarla ve paragraf başlarında; kayıttan çıkarılan gerçek nefes ya da sentetik nefes.
- Oda tonu (`room_tone`): duraklamalar dijital sessizlik yerine kayıttaki ortam sesiyle doldurulur.
- Mastering (`master`): yüksek geçiren süzgeç, hafif de-esser, sıcaklık EQ'su, EBU R128 ölçümüyle −16 LUFS ve en fazla
  −1,5 dBTP; ffmpeg yoksa RMS tabanlı yedek.
- Parçalar çapraz geçişle (crossfade) birleştirilir.

**Referans kaydı analizi** (`analysis.py`)
- 0–100 kalite puanı ve derece (mükemmel / iyi / orta / zayıf); sorun kodları (`too_short`, `noisy`, `clipping`,
  `low_bandwidth`, `reverb`, `monotone`…) Türkçe açıklama ve önerilerle.
- Ölçümler: SNR, gürültü tabanı, tepe/RMS, kırpılma, bant genişliği, yankı, perde (F0), konuşma hızı, duraklamalar, nefesler.
- Kişinin duraklama ritmi (`pauses.scale`) sese kaydedilir ve üretimde otomatik uygulanır.
- Kayıttan oda tonu ve gerçek nefes çıkarılır.
- `POST /api/analyze` (kaydetmeden analiz), `GET /api/voices/{id}/analysis`; duygu kayıtları da analiz edilir.

**Stiller ve duygular**
- 12 stil ön ayarı (`style`): sohbet, anlatıcı, haber, reklam, masal, podcast, belgesel, eğitim, sesli-kitap,
  duygusal, müşteri-hizmeti, spor-spikeri. İstekte açıkça verilen alanlar stilin değerlerini ezer. Her sese varsayılan
  stil atanabilir.
- 8 yeni duygu: nazik, gururlu, umutlu, nostaljik, gergin, romantik, çocuksu, otoriter (Türkçe/İngilizce eş anlamlılarıyla);
  mevcut duyguların eş anlamlıları genişletildi.
- Kapsamlı duygu etiketi: `[heyecanlı: yalnızca bu cümle]` yalnızca parantez içine uygulanır.
- Vurgu: `*sözcük*`, `[vurgu] sözcük`, `[vurgu: kısa öbek]`.
- Sayılı duraklama etiketi: `[1.5 sn]`, `[2 saniye]`, `[500 ms]`, `[duraklama: 1 sn]` (en fazla 10 sn); yeni sabit
  duraklamalar: `[kısa duraklama]` (0,35 sn), `[derin nefes]` (0,7 sn), `[sessizlik]` (2 sn).
- Sözsüz etiketler genişletildi: `[tüh]`, `[aman]`, `[cık cık]`, `[pöf]`, `[şey]`, `[hı hı]`, `[ıslık]`, `[hıçkırır]`,
  `[burnunu çeker]` ve İngilizce karşılıkları; `[hahaha]`, `[hihihi]` gibi tekrarlı yazımlar.
- Otomatik duygu tahmini olumsuzluğu ("hiç güzel değil"), noktalamayı ve büyük harf oranını da hesaba katar.

**Üretim ve arayüz**
- Varyantlar (`variants`, 1–4): aynı metin farklı tohumlarla A/B/C/D olarak üretilir; geçmişte `group_id` ile
  gruplanır; beğenilen sonucun tohumu sabitlenebilir.
- Canlı önizleme: hazır olan parçalar üretim sürerken dinlenebilir (`job.partial`).
- İş iptali (`POST /api/jobs/{id}/cancel`), kalan süre tahmini (`eta_s`) ve sıradaki konum (`position`).
- Geçmişte metin/ses adı araması, tür süzgeci, favoriler ve sayfalama.
- Dalga formlu oynatıcı.
- Ses yedekleme: ses tüm duygu kayıtları ve analizleriyle zip olarak dışa aktarılır ve başka bir kuruluma içe aktarılır.
- Seslere not ve varsayılan stil.
- Kayıt sırasında seviye göstergesi ve hazır okuma metinleri; koyu / açık / sistem teması.

**Kurulum, geliştirme, belgeler**
- `docker-compose.cpu.yml`: CUDA'sız, birkaç GB küçük CPU imajı (`TORCH_INDEX` build argümanı).
- Docker Compose `.env` dosyasını okur; tüm ayarlar varsayılanlarıyla tanımlı.
- `run.sh` / `run.ps1`: Python, Node.js, ffmpeg ve git denetimi ve Türkçe hata mesajları; `--dev` modu (uvicorn
  `--reload` + Vite birlikte); paketler yalnızca ilk kurulumda ya da `requirements.txt` değişince kurulur; arayüz
  kaynakları değişince yeniden derlenir; `.env` okunur; Windows'ta NVIDIA GPU varsa PyTorch CUDA sürümüyle kurulur.
- GitHub Actions: pytest (Chatterbox/PyTorch olmadan, sahte motorla) ve `vite build`; `backend/requirements-dev.txt`,
  `backend/pytest.ini`.
- Belgeler: [Kayıt rehberi](docs/KAYIT_REHBERI.md), [Etiketler ve stiller](docs/ETIKETLER.md), [API](docs/API.md),
  [SSS](docs/SSS.md); [MIT lisansı](LICENSE).

### Değişti

- `colloquial` artık seviye alır (`"off"`, `"light"`, `"full"`); `true` = `"light"`, `false` = `"off"` olarak
  çalışmaya devam eder.
- Varsayılan çıktı nefes, oda tonu ve mastering içerir; ses seviyesi v2'ye göre belirgin biçimde yüksektir (−16 LUFS).
- Cümle arası duraklamalar sabit tablo yerine bağlama, duyguya ve kişinin ölçülen ritmine göre belirlenir.
- `GET /api/generations` arama ve süzgeç (`q`, `kind`, `voice_id`, `favorite`) ile sayfalama (`limit`, `offset`) destekler.
- İş sözlüğüne `partial`, `eta_s`, `cancelled`, `position` alanları ve `cancelled` durumu eklendi.
- `GET /api/health` stil kataloğunu, konuşma dili seviyelerini ve özellik bayraklarını (`features`) da döndürür.
- Veritabanı açılışta kendiliğinden göç eder: eski veritabanına yeni sütunlar eklenir; sesler ve geçmiş korunur.
- Docker imajına yalnızca `backend/app` kopyalanır; yerel `backend/data` (sesler, çıktılar) artık imaja girmez.
- Docker Compose ayarları `.env` dosyasından okunur; `docker-compose.yml` içindeki `deploy:` bloğunu silmek yerine CPU
  için ayrı dosya kullanılır.
- Yeni ağır Python bağımlılığı eklenmedi; ses ölçümü ve mastering için mevcut ffmpeg, NumPy ve SciPy kullanılır.

### v2'den v3'e yükseltme

- **Docker:** `git pull && docker compose up -d --build`. Veri birimi korunur, veritabanı kendiliğinden güncellenir.
  GPU'suz kurulumlar artık `docker compose -f docker-compose.cpu.yml up -d --build` kullanmalıdır.
- **Docker'sız:** `git pull` ardından `./run.sh` ya da `.\run.ps1`; betik paketleri ve arayüzü kendisi günceller.
- **Windows + NVIDIA:** v2 betiği PyPI'dan yalnız CPU'luk PyTorch kuruyordu (GPU boşta kalıyordu). v3 betiği ilk
  çalıştırmada PyTorch'u CUDA 12.4 sürümüyle yeniden kurar (~2,5 GB indirme).
- **API istemcileri:** İstekler değişmeden çalışır. v2'ye yakın bir çıktı için `"breaths": false, "room_tone": false,
  "master": false` gönderin. Varsayılan `wait: false` davranışı (202 + iş) aynıdır.
- **Mevcut sesler:** Kayıt analizi, kişisel duraklama ritmi, oda tonu ve nefes özelliklerinden tam yararlanmak için
  önemli seslerinizi yeniden yüklemeniz ya da analizlerini yenilemeniz önerilir.

## 2.0.0

İlk yayımlanan sürüm.

- Chatterbox Multilingual V3 ile 8–15 sn kayıttan sıfır-shot ses klonlama; mikrofondan kayıt; ses → ses dönüştürme.
- Duygu etiketleri (`[heyecanlı]`, `[üzgün]`, `[fısıltı]`…), sözsüz etiketler (`[gülme]`, `[iç çekme]`…), duraklama
  etiketleri; noktalamaya göre ve içerikten otomatik duygu; ses başına duygu kayıtları; `emotion_fx` (off/light/full).
- Konuşma dili dönüşümü (aç/kapa) ve temel Türkçe normalizasyon (sayı, tarih, saat, para, birim, kısaltma, marka okunuşu).
- İş kuyruğu ve ilerleme çubuğu, geçmiş, MP3/WAV, API anahtarı, Swagger, Docker, `run.sh` / `run.ps1`.
