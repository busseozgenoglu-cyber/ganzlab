# İnce ayar: Chatterbox'a ifadeli Türkçe öğretmek

Bu klasör, SesKlon'un sentez modelini (Chatterbox Multilingual, T3 bileşeni) **tek bir konuşmacının ifadeli Türkçe
kayıtlarıyla** LoRA yöntemiyle ince ayarlamak için gereken her şeyi içerir: kayıt senaryosu, veri hazırlama, eğitim,
ölçüm ve kabul kararı. Sözleşme: [docs/SOZLESME3.md](../docs/SOZLESME3.md) §4–§6.

| Dosya | Ne yapar |
|---|---|
| `senaryo.py` | Duygu cümle bankasından (`cumleler/`) okuma senaryoları ve `manifest.csv` üretir |
| `hazirla.py` | Kayıtları denetler, keser, normalize eder; LJSpeech biçiminde `MyTTSDataset/` yazar |
| `egit.sh` | Eğitim deposunu kurar, ayarları yamalar, eğitir, LoRA'yı birleştirir |
| `degerlendir.py` | Temel ve ince ayarlı modeli aynı cümlelerle ölçer: **KABUL** / **RET** |

## Neden ince ayar?

Gerçek modelle yapılan ölçümler (M2 Pro, mps):

- **Tonlama aralığı 13,5 yarım ton**; aynı cümlelerde Gemini TTS **17,6**. Dinleyici bunu "robotik, duygusuz" diye
  duyuyor.
- `exaggeration` ve `cfg_weight` ayarları aralığı **değiştirmedi**; ön/son işleme katmanları (prozodi, duygu
  yoğunluğu) da düzlüğü gidermiyor. Düzlük, modelin Türkçe prozodi önceliğinden geliyor: 23 dilli eğitimde Türkçe
  verisi az ve büyük ölçüde okuma (haber, sesli kitap) tarzında.
- Hız gerçek zamanın **4,6 katı** (RTF ≈ 4,6). İnce ayar hızı değiştirmez; hız için Apple Silicon'da
  `TTS_BACKEND=chatterbox-mlx` arka ucu vardır.

Ayarla çözülmeyen bir öncelik ancak veriyle değişir: model, aynı mimariyle, ifadeli konuşan bir Türkçe sesten
öğrenmeli.

## Hedef

| Ölçüt (`python -m app.bench` özeti) | Temel | Hedef |
|---|---|---|
| Tonlama aralığı medyanı (`range_semitones_median`) | 13,5 st | **≥ 17 st** ve temelden geniş |
| Kalite kontrolden geçemeyen cümle (`qc_fail_count`) | ölçülen | **artmamış** (yutulan/tekrarlanan sözcük yok) |
| Hece/sn ortalaması (`syllables_per_sec_mean`) | ölçülen | **3,5–6,5** (doğal konuşma hızı) |
| Üretilemeyen cümle (`errors`) / başarıyla ölçülen cümle (`n`) | ölçülen | hata **artmamış**, `n` **azalmamış** |

`degerlendir.py` bu koşulların hepsini birlikte denetler (üretim hatası artmamış, ölçülen cümle sayısı azalmamış,
aralık ≥ 17, QC artmamış, hece/sn aralıkta, aralık > temel); biri bile kalırsa sonuç RET'tir ve nedeni Türkçe yazılır.
Hata ve cümle sayısı ayrıca denetlenir, çünkü kıyaslama özeti hata veren cümleleri dışarıda bırakır: 50 cümleden 38'i
hata verip 12'si iyi çıkan bir model, yalnız o 12 cümleyle "ifadeli" görünmemeli.

## Önce ucuz deney: ifadeli referans

İnce ayar günler süren bir iştir (kayıt + eğitim). Önce, klonun **referans kaydının** ne kadar ifadeli olduğunu ölçün;
model referansın tonlamasını büyük ölçüde taklit eder ve klon genelde referansın aralığının biraz altında kalır.

```bash
cd backend
python -m app.bench --reference-only sakin.wav coskulu.wav          # model yüklemez: her kaydın aralığı ve yorumu
python -m app.bench --backend chatterbox --ref coskulu.wav --out ref_coskulu.json
python -m app.bench --compare temel.json ref_coskulu.json            # temel ↔ ifadeli referans
```

- Referansın kendisi **≥ 16 yarım ton** değilse önce daha coşkulu, "anlatır gibi" bir kayıt alın
  ([docs/KAYIT_REHBERI.md](../docs/KAYIT_REHBERI.md) bölüm 5 ve 7).
- İfadeli referansla klonun aralık medyanı **≥ 16 yarım ton** çıkıyorsa ince ayara gerek olmayabilir: duygu kayıtları
  (Sesler sekmesi) ve iyi bir temel kayıt yetebilir.
- İfadeli referansa rağmen klon 14 yarım tonun altında kalıyorsa, düzlük modeldedir: ince ayar yapın.

## Veri gereksinimi

- **Tek konuşmacı.** Her şey aynı kişiden, aynı oda ve aynı mikrofonla. Kaydedilen kişinin **yazılı izni** şart
  (aşağıda [Lisans ve etik](#lisans-ve-etik)).
- **3–5 saat ifadeli, günlük Türkçe** (temizlendikten sonra). Okuma değil konuşma tonu: soru, ünlem, şaşırma, gülerek
  söyleme. Düz okunmuş 5 saat, ifadeli 2 saatten kötü sonuç verir.
- **30 dakika** (zorunlu en az): yalnızca ses rengi uyumu (klon benzerliği) iyileşir; tonlama aralığı belirgin artmaz.
- Kayıt kalitesi: SNR ≥ 20 dB, kırpılma yok, cümle başına 1–12 sn (ideal 3–10 sn). `hazirla.py` bu eşiklerin altını
  reddeder; ayrıntılı kayıt ortamı için [docs/KAYIT_REHBERI.md](../docs/KAYIT_REHBERI.md).
- **Kayıt adları ön ekli olmalı** (`normal_0001.wav`, `mutlu_0007.wav`), yalnız rakam (`0001.wav`) değil: eğitim deposu
  `metadata.csv`'yi pandas ile okur ve tüm adlar rakamsa `0001`'i sayıya çevirip `1.wav` arar — kayıtlar bulunamaz.
  `senaryo.py` adları zaten ön ekli üretir, `hazirla.py` rakamsal adlara ön ek ekler; `egit.sh` tümü rakam olan
  adlarda Türkçe hatayla durur.

### Transkriptsiz bölme

Uzun bir kaydı (podcast, sesli kitap) metni olmadan parçalara böldüyseniz (`hazirla.py`'nin transkriptsiz bölme
kipi), `metadata.csv`'de metin sütunları boş kalır (`id||`). Bu satırlar **eğitime giremez**: depo boş alanı pandas'ta
`NaN` olarak okur ve modele "nan" metnini öğretir. `egit.sh` böyle satır görürse Türkçe hatayla durur. Önce metinleri
Whisper ile doldurun (Türkçe için `large-v3` ya da `large-v3-turbo`; `language="tr"`), çıktıyı kulakla gözden geçirin
(sayılar, özel adlar, yarım kalan sözcükler) ve `metadata.csv`'nin 2. ve 3. sütununa yazın — 3. sütun (normalize metin)
için `app.textnorm.normalize` kullanın, ardından `hazirla.py`'yi o manifestle yeniden çalıştırın. Yanlış transkript
modelin telaffuzunu bozar; emin olmadığınız parçaları atın.

Önerilen duygu dağılımı (3 saat ≈ 180 dk ≈ 3 000 cümle; cümle başına ortalama 3,5 sn):

| Duygu | Dakika | Not |
|---|---|---|
| `normal` | 45 | Sohbet tonu; `senaryo.py --metin kitap.txt` ile kendi metninizden çoğaltın |
| `samimi` | 15 | Arkadaşa anlatır gibi |
| `mutlu` | 12 | |
| `heyecanlı`, `sakin`, `ciddi`, `üzgün` | 10'ar | |
| `kızgın`, `şaşkın` | 8'er | |
| `korkmuş`, `fısıltı` | 6'şar | Fısıltı sessiz ortam ister |
| `alaycı`, `nazik`, `gergin`, `umutlu`, `otoriter`, `romantik`, `nostaljik`, `gururlu`, `sıkılmış` | 4–5'er (≈ 40) | |

Bankada her duygu için 30 cümle var (bir geçişte ≈ 1,75 dk); `--tekrar 2` her cümleyi *hafif* ve *güçlü* yoğunlukta
iki kez okutur. Yukarıdaki dakikalara ulaşmak için bankayı kendi cümlelerinizle büyütün ya da `--metin` ile uzun bir
metin ekleyin. `senaryo/OZET.md` "3 saat için ne gerekir" hesabını yapar.

## Adım adım

Komutlar proje kökünden çalışır.

```bash
# 1) Okuma senaryosu: oturumlar (≤ 25 dk), manifest ve özet
python finetune/senaryo.py --cikti senaryo/ --tekrar 2 --metin kitap.txt
python finetune/senaryo.py --kontrol                       # cümle bankası denetimi

# 2) Kayıt: senaryo/oturum_01.md … sırayla; her satırı kayıt adıyla (mutlu_0007.wav) kayitlar/ klasörüne
#    Rehber: docs/KAYIT_REHBERI.md (oda, mikrofon mesafesi, seviye; tüm oturumlarda aynı düzen)

# 3) Veri hazırlama: denetim, kırpma, normalizasyon, duygu etiketi, doğrulama payı
python finetune/hazirla.py --kayitlar kayitlar/ --manifest senaryo/manifest.csv \
       --cikti finetune/MyTTSDataset --etiket --dogrulama 0.05
#    → finetune/MyTTSDataset/rapor.json: duygu başına dakika ve tonlama aralığı ("veri ifadeli mi?")

# 4) Eğitim (kurulum + eğitim + LoRA birleştirme); sonunda başlatma komutunu yazdırır
bash finetune/egit.sh
#    adım adım: ADIM=kur …, ADIM=egit …, ADIM=birlestir …

# 5) Değerlendirme: temel ↔ ince ayar, aynı referans ve cümleler → KABUL (çıkış 0) / RET (çıkış 2)
python finetune/degerlendir.py --ref konusmaci.wav \
       --ince finetune/chatterbox-finetuning/chatterbox_output/t3_finetuned_merged.safetensors \
       --etiketli --cikti finetune/rapor.json

# 6) KABUL ise SesKlon'u ince ayarlı T3 ile başlatın
cd backend && T3_FINETUNED=../finetune/chatterbox-finetuning/chatterbox_output/t3_finetuned_merged.safetensors \
    T3_EMOTION_TAGS=1 uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Kalıcı kullanım için proje kökündeki `.env` dosyasına `T3_FINETUNED=<mutlak yol>` (veri `--etiket` ile hazırlandıysa
`T3_EMOTION_TAGS=1` de) yazıp `./run.sh` ile başlatın. `T3_EMOTION_TAGS=1` iken arka uç her parçanın duygusunu
eğitim verisindeki biçimle metnin başına ekler (`[mutlu] Merhaba`); etiketsiz eğitilmiş bir modelde bu ayarı
**açmayın**, etiket sözcük gibi okunur.

`degerlendir.py` ayrıntıları:

- `--temel a.json --ince-sonuc b.json`: hazır `python -m app.bench --out` sonuçlarını karşılaştırır (model yüklemez).
- `--temel a.json --ref … --ince …`: temel sonuç hazırsa yalnızca ince ayarlı modeli koşturur.
- `--pipeline`: tüm motor zinciriyle (normalizasyon, prozodi, QC'li yeniden üretim) ölçer; `--limit N`, `--repeat N`,
  `--cumleler DOSYA`, `--cihaz` de vardır. `--arka-uc fake` model gerektirmeyen kuru çalışmadır (hattı denemek için).
- Temel koşuda `T3_FINETUNED` boşaltılır, ince koşuda dosya yoluna ayarlanır; iş bitince ortam eski hâline döner.
- **İki koşu aynı metni alır.** `--etiketli` yalnız ince koşunun arka ucunda `T3_EMOTION_TAGS=1` açar: ham modda metin
  iki koşuda da etiketsizdir, cümlenin duygusu `emotion` parametresiyle gider ve ince ayarlı arka uç `[mutlu] `
  önekini kendisi ekler. `--pipeline --etiketli` ile metin iki koşuda da `[duygu] …` olur; motor etiketi iki koşuda da
  aynı duygu profili olarak uygular (temel model etiketi görmez, yalnız profil değişir).
- `--temel x.json` (ya da `--ince-sonuc`) ile hazır bir sonuç kullanılınca, onun ayarları (boru hattı, referans dosya
  adı, tohum, cümle dosyası ve sayısı, exaggeration / cfg_weight / temperature, tekrar, metin etiketi) yeni koşuyla
  karşılaştırılır; fark varsa "kıyas adil olmayabilir" uyarısı yazılır ve `rapor.json`'daki `uyarilar`'a eklenir.

### egit.sh ayarları

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `VERI` | `finetune/MyTTSDataset` | `hazirla.py` çıktısı (`metadata.csv` + `wavs/`) |
| `EPOCH` | 10 | Eğitim turu |
| `BATCH` / `GRAD_ACCUM` | 4 / 4 | Etkin batch = 16; bellek yetmezse BATCH yarı, GRAD_ACCUM iki kat |
| `LORA_R` / `LORA_ALPHA` | 64 / 128 | LoRA rankı ve ölçeği |
| `OGRENME_HIZI` | deponunki | LoRA 1e-4, tam ince ayar 1e-5 |
| `CIHAZ` | otomatik | `cuda` / `mps` / `cpu` |
| `TAM_INCE_AYAR` | 0 | 1 = tüm T3 ağırlıkları (çok bellek; > 10 saat veri için) |
| `MTL_TABAN` | 1 | Multilingual T3 tabanından eğit (aşağıdaki bulguya bakın) |
| `MTL_T3_SURUM` | v3 | SesKlon'un `T3_MODEL`'iyle aynı olmalı |
| `ON_ISLEME` | otomatik | Veri (`metadata.csv` sha256) ya da taban değişince belirteçleri yeniden çıkarır; 1 = zorla, 0 = atla |
| `ISCI` | deponunki (8) | Veri yükleyici işçi sayısı; 0 da olur (`persistent_workers` buna göre yamalanır) |
| `DEPO_DIZIN` | `finetune/chatterbox-finetuning` | Eğitim deposunun klonlandığı yer |
| `ADIM` | hepsi | `kur` / `egit` / `birlestir` / `hepsi` / `yamala` (yalnızca yama + etkin ayarlar) |

Ön işleme çalışacaksa `egit.sh` önce `MyTTSDataset/preprocess/` içindeki **eski `.pt` dosyalarını siler**: depo
klasördeki bütün `.pt`'leri eğitime alır; reddedilen klipler, doğrulama klipleri ya da başka tabanla
(`MTL_TABAN` değişimi) çıkarılmış belirteçler sızmasın. Ön işlemenin neyle yapıldığı `preprocess/.sesklon_taban`
dosyasında (taban + `metadata.csv` sha256) tutulur. Eğitim bitince taban `chatterbox_output/sesklon_taban.txt`'ye
yazılır; `ADIM=birlestir` farklı bir `MTL_TABAN` / `MTL_T3_SURUM` / `TAM_INCE_AYAR` ile çağrılırsa Türkçe hatayla
durur ve doğru komutu söyler; sondaki `T3_MODEL` önerisi eğitimdeki sürümdür.

`egit.sh` deponun `src/config.py` dosyasını her çalıştırmada git'ten geri alıp yeniden yamalar; o dosyayı elle
düzenlemeyin, değişkenleri kullanın. Bulunamayan anahtar için uyarı verir ve devam eder. Günlükler:
`finetune/chatterbox-finetuning/gunlukler/`; ilerleme: `tensorboard --logdir finetune/chatterbox-finetuning/chatterbox_output`.

## Donanım, süre, maliyet

| Kurulum | 3 saat veri, LoRA, 10 epoch | Not |
|---|---|---|
| Tek 24 GB GPU (RTX 3090/4090, A10, L4) | **≈ 2–4 saat** + ön işleme ≈ 15–30 dk | Önerilen |
| 16 GB GPU (T4, V100) | ≈ 5–8 saat, `BATCH=2 GRAD_ACCUM=8` | bf16 yok; `egit.sh` bf16'yı kapatır (fp32) |
| Apple Silicon (M1–M4) | **önerilmez** | Aşağıya bakın |
| Yalnızca CPU | günler | Uygulanabilir değil |

- Süreler tahmindir (ölçülmedi); veri süresi ve epoch ile doğru orantılı büyür.
- Bulut GPU: 24 GB'lık bir kart saatlik **yaklaşık 0,4–1,5 $** (sağlayıcıya, bölgeye ve anlık/spot fiyata göre
  değişir); tek bir eğitim çoğu zaman **birkaç dolar ile 10 $** arasıdır. Fiyatları kiralamadan önce denetleyin.
- Disk: ≈ 10 GB (PyTorch, temel model ≈ 3 GB, ön işleme dosyaları, çıktı ≈ 2 GB).
- **Apple Silicon'da eğitim önerilmez:** depo `cuda` ya da `cpu` için yazılmış (`train.py` cihazı
  `cuda if available else cpu` diye seçer), bf16 ve bazı işlemler mps'te desteklenmeyebilir. `egit.sh` mps'te
  `PYTORCH_ENABLE_MPS_FALLBACK=1` ayarlar ama sonuç doğrulanmadı. Eğitimi bulutta yapıp `.safetensors` dosyasını Mac'e
  indirin.
- **Çıkarım Mac'te:** PyTorch arka ucu (`TTS_BACKEND=chatterbox`, `DEVICE=mps`) `T3_FINETUNED`'ı uygular.
  **MLX arka ucu (`chatterbox-mlx`) `T3_FINETUNED`'ı uygulamaz**; ince ayarlı ağırlıkların MLX biçimine dönüştürülmesi
  gerekir (mlx-audio'nun dönüştürme araçlarıyla; bu hatta henüz yok).

## Lisans ve etik

- **Chatterbox: MIT** ([resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox/blob/master/LICENSE)) —
  ince ayarlı ağırlıklar ticari kullanılabilir. Eğitim deposu (gokhaneraslan/chatterbox-finetuning):
  [Apache-2.0](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/LICENSE).
- **TurEV-DB, Turk-SER** gibi Türkçe duygu veri setleri **akademik** kullanım içindir; ticari bir model için kullanmadan
  önce sahiplerinden yazılı izin alın. Lisansı belirsiz veri kullanmayın.
- **Gemini TTS, ElevenLabs vb. çıktılarıyla eğitmek yapılmaz:** bu hizmetlerin kullanım koşulları, çıktılarıyla rakip
  model eğitmeyi yasaklar (ToS ihlali). Ölçümde kıyas noktası olarak kullanmak (17,6 yarım ton) serbesttir; eğitim
  verisi olarak değil.
- **Kaydedilen kişinin yazılı izni:** sesin klonlanacağını, ince ayarlı modelin nerede ve ne süreyle kullanılacağını
  açıkça yazan bir onay alın; izin geri çekilirse model ve veri silinir. Başkasının sesini (ünlü, müşteri, yakın)
  izinsiz kaydetmeyin ve klonlamayın.

## Sık sorunlar

**Bellek yetmedi (`CUDA out of memory`).** `egit.sh` günlükte bunu görürse yarıya indirilmiş komutu yazar:
`ADIM=egit BATCH=2 GRAD_ACCUM=8 ON_ISLEME=0 bash finetune/egit.sh`. Yine yetmezse `LORA_R=32 LORA_ALPHA=64`.
`TAM_INCE_AYAR=1` 24 GB'ta bile sığmayabilir; LoRA kullanın.

**SesKlon açılırken `İnce ayar ağırlıkları T3 ile uyumsuz` / `size mismatch for text_emb.weight`.** Dosya farklı
sözlük boyutuyla eğitilmiş: Turbo kipi (`is_turbo=True`, 52 260 belirteç) ya da 704 belirteçli İngilizce sözlük.
SesKlon Multilingual T3 kullanır: `text_emb` / `text_head` **2454 × 1024** olmalı. `egit.sh` `is_turbo=False` ve
`new_vocab_size=2454` yamalar; deponun ayarını elle değiştirdiyseniz geri alın ve yeniden eğitin.

**`İnce ayar ağırlıkları T3 ile eşleşmiyor: … anahtardan yalnızca … tanesi modelde var`.** `T3_FINETUNED` büyük
olasılıkla LoRA bağdaştırıcısını (`new_lang_adapter/adapter_model.safetensors`) gösteriyor; onun anahtarları
(`lora_A`, `lora_B`) T3'te yoktur. Önce birleştirin: `ADIM=birlestir bash finetune/egit.sh` → `t3_finetuned_merged.safetensors`.

**Apple Silicon (mps).** Eğitim için yukarıdaki nota bakın. Çıkarımda `DEVICE=mps` ile PyTorch arka ucunu kullanın;
mps'te desteklenmeyen bir işlemde `PYTORCH_ENABLE_MPS_FALLBACK=1` ayarlayın (o işlem CPU'da çalışır).

**`bf16` hatası (`Your setup doesn't support bf16/gpu`).** Ampere öncesi GPU (T4, V100). `egit.sh` `bf16`'yı yalnızca
donanım destekliyorsa açacak biçimde yamalar; deponun `train.py`'si değiştiyse ve yama uygulanamadıysa uyarı verir.

**"İnce ayar yaptım ama model hâlâ düz" (RET: aralık < 17).** Model veriden ancak verideki kadar ifadeyi öğrenir.
`finetune/MyTTSDataset/rapor.json` içinde **duygu başına medyan tonlama aralığına** (`range_semitones`) bakın: 12 yarım
tonun altındaki duygular düz okunmuş demektir — o oturumları daha abartılı yeniden kaydedin. Ayrıca:
`degerlendir.py --etiketli` ile ölçtünüz mü (etiketli eğitilen model etiket görmezse nötr konuşur)? `rapor.json`
(değerlendirme) içindeki `karsilastirma.sentences` cümle bazında hangi kategorilerin düz kaldığını gösterir. Epoch'u
artırmak (15–20) yardımcı olabilir ama QC başarısızlıkları artarsa geri dönün.

**Etiket sesli okunuyor ("köşeli parantez mutlu …").** Model etiketsiz veriyle eğitilmiş ama `T3_EMOTION_TAGS=1`
açık — kapatın; ya da veriyi `hazirla.py --etiket` ile yeniden hazırlayıp eğitin.

**`ValueError: persistent_workers option needs num_workers > 0`.** `ISCI=0` verilmiş ve deponun `train.py`'si
değişmiş olduğu için `dataloader_persistent_workers` yamalanamamış; `egit.sh` bu durumda uyarıp `ISCI=1` kullanır.

**Model "nan" diyor ya da boş metinli satır hatası.** Transkriptsiz bölünmüş klipler metinsiz kalmış; yukarıdaki
[Transkriptsiz bölme](#transkriptsiz-bölme) notuna bakın.

**Ön işleme çok az dosya işledi (`Preprocessing completed! Success: 120/3000`).** `metadata.csv`'deki adlar
`wavs/` içindeki dosyalarla eşleşmiyor (rakamsal adlar: yukarıdaki not) ya da dosyalar okunamıyor; günlükteki
`Error (…)` satırlarına bakın.
Veriyi değiştirdikten sonra `ON_ISLEME=1` ile zorlayın.

## Multilingual taban notu (araştırma bulgusu)

**Soru:** [gokhaneraslan/chatterbox-finetuning](https://github.com/gokhaneraslan/chatterbox-finetuning) temel modeli
İngilizce `ChatterboxTTS`'ten mi, `ChatterboxMultilingualTTS`'ten mi yüklüyor? SesKlon Türkçe için
`ChatterboxMultilingualTTS` (T3 `t3_mtl23ls_v2/v3`, `grapheme_mtl_merged_expanded_v1.json`, 2454 belirteç,
`MTLTokenizer`) kullanır.

**Cevap: İngilizce tabandan.** Deponun standart kipi (`is_turbo=False`) Multilingual T3'ü hiç yüklemez; seçecek bir
ayar da yok. Bulgular (2026-10-13, `main` dalı):

1. `setup.py` standart kipte `ResembleAI/chatterbox` deposundan **İngilizce** dosyaları indirir: `ve.safetensors`,
   **`t3_cfg.safetensors`**, `s3gen.safetensors`, `conds.pt`; çok dilli grafem sözlüğünü
   (`grapheme_mtl_merged_expanded_v1.json`) `tokenizer.json` adıyla kaydeder.
   — [setup.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/setup.py) (`CHATTERBOX_FILES`)
2. `train.py` ve `merge_lora.py` `EngineClass = ChatterboxTTS` (deponun içindeki `src/chatterbox_/tts.py`, İngilizce
   sınıf) ile `from_local` yapar, `text_tokens_dict_size = new_vocab_size` (2454) ile yeni bir T3 kurar ve
   `resize_and_load_t3_weights` ile ağırlıkları aktarır: İngilizce sözlüğün 704 satırı kopyalanır, yeni 1750 satır
   **ortalama ile başlatılır**.
   — [train.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/train.py),
   [merge_lora.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/merge_lora.py),
   [src/model.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/src/model.py)
3. `src/chatterbox_/tts.py` `from_local` T3'ü `t3_cfg.safetensors`'tan, belirteçleyiciyi `EnTokenizer(tokenizer.json)`
   ile yükler. `EnTokenizer` yalnızca boşlukları `[SPACE]` yapar: **dil etiketi (`[tr]`) yok, küçük harfe çevirme ve
   NFKD yok.** Ön işleme `tts_engine.tokenizer.text_to_tokens(clean_text)` ile `metadata.csv`'nin 3. sütununu
   (`normalized_text`) belirteçler.
   — [src/chatterbox_/tts.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/src/chatterbox_/tts.py),
   [src/chatterbox_/models/tokenizers/tokenizer.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/src/chatterbox_/models/tokenizers/tokenizer.py),
   [src/preprocess_ljspeech.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/src/preprocess_ljspeech.py)
4. `src/config.py`'de taban seçimi yalnızca `is_turbo` (Turbo / standart) ve `is_lora` ile yapılır; Multilingual
   seçeneği yok. Depo içinde `src/chatterbox_/mtl_tts.py` (`ChatterboxMultilingualTTS`, `T3Config.multilingual()`,
   `t3_mtl23ls_v2.safetensors`, `MTLTokenizer`) **var ama eğitim yolunda kullanılmıyor.**
   — [src/config.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/src/config.py),
   [src/chatterbox_/mtl_tts.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/src/chatterbox_/mtl_tts.py)

**SesKlon'a etkisi.** Özgün yolla birleştirilen dosyada `text_emb` / `text_head` 2454 × 1024'tür; anahtar adları ve
boyutlar Multilingual T3 ile aynı olduğu için SesKlon yükleyicisi (`load_finetuned_t3`) **reddetmez, tüm T3'ü
değiştirir**. Ama: (a) Multilingual T3'ün 23 dilde öğrendiği her şey atılır, yerine İngilizce taban + Türkçe LoRA
gelir; (b) SesKlon çıkarımda `MTLTokenizer` kullanır: metni küçük harfe çevirir, NFKD ile ayrıştırır (ç → c + ◌̧) ve
başına `[tr]` ekler — eğitimde görülmemiş bir belirteç dizisi. Bu **eğitim/çıkarım uyuşmazlığı** sonucu
güvenilmez kılar. Grafem sözlüğünün ilk 704 kimliğinin İngilizce sözlükle aynı karakterlere denk gelip gelmediği
**doğrulanmadı**.

**Ayrıca:** Resemble'ın güncel `mtl_tts.py`'si `v2` ve `v3` T3 dosyalarını tanır (`MULTILINGUAL_T3_MODELS`), ikisi de
`T3Config.multilingual()` (2454 belirteç) ile yüklenir; SesKlon'un varsayılanı `T3_MODEL=v3`.
— [resemble-ai/chatterbox mtl_tts.py](https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/mtl_tts.py)

**`egit.sh`'ın çözümü: `MTL_TABAN=1` (varsayılan, deneysel).** Yamalar:

1. Temel model `setup.py` yerine `huggingface_hub.snapshot_download` ile `ResembleAI/chatterbox`'tan Multilingual
   dosyalarla indirilir: `ve.pt`, `t3_mtl23ls_<MTL_T3_SURUM>.safetensors`, `s3gen.pt`,
   `grapheme_mtl_merged_expanded_v1.json`, `conds.pt`, `Cangjie5_TC.json`.
2. `train.py`, `merge_lora.py`, `src/preprocess_*.py`: `from src.chatterbox_.tts import ChatterboxTTS` →
   `from src.chatterbox_.mtl_tts import ChatterboxMultilingualTTS as ChatterboxTTS` (`punc_norm` de Multilingual
   sürümünden; çıkarımdaki ile aynı noktalama temizliği).
3. Ön işleme: `text_to_tokens(clean_text)` → `text_to_tokens(clean_text, language_id="tr")` — SesKlon'un çıkarımdaki
   belirteçlemesiyle (küçük harf + NFKD + `[tr]`) birebir aynı.
4. `train.py`: İngilizce dosya adlarını arayan `check_pretrained_models(...)` denetimi atlanır; `bf16=True` donanım
   destekliyorsa açılacak biçimde, `dataloader_persistent_workers=True` yalnız işçi varken açılacak biçimde
   değiştirilir (bu iki yama `MTL_TABAN=0`'da da uygulanır).
5. `src/chatterbox_/mtl_tts.py`: T3 dosya adı `MTL_T3_SURUM`'a göre (`t3_mtl23ls_v3.safetensors`), `ve.pt` / `s3gen.pt`
   `map_location="cpu"` ile yüklenir.
6. `new_vocab_size=2454`: Multilingual T3 zaten 2454 belirteçli olduğundan yeniden boyutlandırma bir şey değiştirmez;
   LoRA `text_emb` / `text_head`'i (`lora_modules_to_save`) Multilingual ağırlıklardan başlayarak eğitir.

Durum: yamalar indirilen depo dosyalarına karşı sınandı (doğru yerlere uygulanıyor, sözdizimi bozulmuyor, iki kez
çalıştırmak aynı sonucu veriyor). **GPU'da uçtan uca eğitim ve `v3` dosyasının depodaki T3 koduyla `strict` yüklenmesi
doğrulanmadı**; `v3` yüklenmezse `MTL_T3_SURUM=v2` deneyin (o zaman SesKlon'da da `T3_MODEL=v2`). `MTL_TABAN=0`
deponun özgün yoludur; `egit.sh` uyarıyla çalıştırır.

**Otomatik yama uygulanamazsa (depo değişmişse) elle:**

1. `src/config.py`: `is_turbo = False`, `new_vocab_size = 2454`, `model_dir` Multilingual dosyaların olduğu klasör.
2. Multilingual dosyaları indirin (yukarıdaki 1. madde) ve `model_dir`'e koyun.
3. `train.py` ve `merge_lora.py` içinde `ChatterboxTTS` yerine `ChatterboxMultilingualTTS` (`src/chatterbox_/mtl_tts.py`)
   kullanın; `train.py`'deki `check_pretrained_models` denetimini kaldırın.
4. `src/preprocess_ljspeech.py`: aynı sınıf değişikliği, `punc_norm`'u `mtl_tts`'ten alın ve
   `text_to_tokens(clean_text, language_id="tr")` yazın.
5. `src/chatterbox_/mtl_tts.py`: kullandığınız T3 dosya adını (`t3_mtl23ls_v3.safetensors`) yazın. Önceki ön işleme
   dosyalarını silin (belirteçler değişti) ve eğitimi baştan başlatın.

**Depo belgeleriyle tutarsızlıklar.** README `lora_r=64`, `lora_alpha=128` ve Turbo hedef modüllerini
(`c_attn`, …) gösterir; `src/config.py`'de ise `lora_r=128`, `lora_alpha=256` ve Llama modülleri (`q_proj`, `k_proj`,
`v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`, `spkr_enc`) var; `lora_modules_to_save=["text_emb",
"text_head"]`. `egit.sh` `LORA_R=64`, `LORA_ALPHA=128` yazar. Diğer doğrulanmış değerler: `batch_size=32`,
`grad_accum=1`, `learning_rate = 1e-4 if is_lora else 1e-5`, `num_epochs = 10 if is_lora else 30`,
`new_vocab_size = 52260 if is_turbo else 2454`, `ljspeech=True`, `json_format=False`, `preprocess=True`. Çıktılar:
LoRA → `chatterbox_output/new_lang_adapter/`, birleştirilmiş → `chatterbox_output/t3_finetuned_merged.safetensors`
(Turbo'da `t3_turbo_finetuned_merged.safetensors`), tam ince ayar → `chatterbox_output/t3_finetuned.safetensors`.
Bağımlılıklar: `torch==2.6.0`, `peft==0.17.1`, `chatterbox-tts==0.1.2` (eğitim ise depodaki `src/chatterbox_` kopyasını
kullanır) — [requirements.txt](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/requirements.txt),
[README](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/README.md),
[inference.py](https://github.com/gokhaneraslan/chatterbox-finetuning/blob/main/inference.py).
