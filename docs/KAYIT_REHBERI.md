# Kayıt rehberi: referans, duygu ve gerçek tepkiler

SesKlon bir sesi tek bir kısa kayıttan klonlar. Model kaydı "düzeltmez", taklit eder: ses rengi, tempo, enerji,
duraklama alışkanlığı, hatta odanın yankısı ve uğultusu klona geçer. SesKlon ayrıca kaydınızdaki **oda tonunu**
(konuşma aralarındaki ortam sesi) duraklamaları doldurmak için, **nefeslerinizi** de cümle aralarında kullanır. Bu yüzden
sonucu en çok etkileyen şey, 10–15 saniyelik bu kayıttır.

Bu rehber üç tür kaydı anlatır: **temel (referans) kayıt** (bölüm 1–6), **duygu kayıtları** (bölüm 7) ve `[gülme]`
gibi etiketlerde modelin yerine çalınan **gerçek tepki kayıtları** (bölüm 8).

## Kısa kontrol listesi

- [ ] Küçük, eşyalı, sessiz bir oda (perde, halı, dolap); boş oda, banyo ve mutfak değil
- [ ] Klima, vantilatör, buzdolabı kapalı; telefon uçak modunda ya da "Rahatsız Etmeyin"de
- [ ] Mikrofon ağızdan 20–30 cm (bir karış), tam önde değil hafifçe yanda; elde değil, sabit bir yerde
- [ ] 10–15 sn akıcı konuşma; başta ve sonda yaklaşık yarım saniye sessizlik
- [ ] Videoda ya da yayında nasıl konuşacaksanız o enerjiyle, "okur gibi" değil "anlatır gibi"
- [ ] WAV ya da kayıpsız kayıt; WhatsApp sesli mesajı ya da telefon görüşmesi kaydı değil
- [ ] Analiz puanı en az 70 ("iyi"); 85 ve üstü ideal
- [ ] Duygu ve tepki kayıtları temel kayıtla aynı oda, aynı mikrofon, aynı mesafe

## 1. Ortam

- **Küçük ve eşyalı oda seçin.** Perde, halı, koltuk, yatak ve içi dolu dolap yankıyı emer. Elbise dolabının önü ya da
  kanepenin köşesi çoğu zaman evdeki en iyi "kabindir".
- **Kaçının:** boş odalar, banyo, mutfak, merdiven boşluğu, araba içi (motor uğultusu), dış mekân (rüzgâr, trafik).
- **Sürekli sesleri kapatın:** klima, vantilatör, buzdolabı, akvaryum pompası, bilgisayar fanı. Dizüstü bilgisayarı
  mikrofondan uzaklaştırın.
- **Yankı testi:** Ellerinizi bir kez çırpın. Çınlama kulakta asılı kalıyorsa başka bir köşe deneyin.
- **Neden önemli:** Model gürültüyü ve yankıyı sesin parçası sanar. Ayrıca kaydın sessiz bölümü oda tonu olarak her
  duraklamada duyulur; uğultulu bir oda tonu bütün üretime yayılır.

## 2. Mikrofon ve mesafe

- **Mesafe 20–30 cm (bir karış).** Daha yakın: "p, b" patlamaları, nefes sesi ve kırpılma. Daha uzak: oda yankısı ve gürültü.
- Mikrofonu ağzın tam karşısına değil, biraz yana ya da aşağıya koyun; pop filtresi varsa kullanın.
- Mesafeyi kayıt boyunca sabit tutun; başınızı çevirmeyin. Mikrofonu elde tutmayın, masaya koyun (tutma ve sürtünme sesi olur).
- **Seviye:** En yüksek yerlerde yaklaşık −6 dBFS (gösterge kırmızıya değmesin), ortalama −24 ile −16 dBFS arası.
  Kırpılma (tavana vurma) sonradan düzeltilemez; emin değilseniz biraz daha kısık kaydedin.
- **Mikrofon sırası (iyiden kötüye):** USB/stüdyo mikrofonu → yaka mikrofonu → telefonun kendi mikrofonu → kulaklık
  mikrofonu → dizüstü bilgisayarın dahili mikrofonu. Bluetooth kulaklık mikrofonları dar bantlıdır; kullanmayın.

## 3. Telefonla kayıt

Telefonla da iyi kayıt alınır; dikkat edilecekler:

- **Uygulama:** iPhone'da *Sesli Notlar* (Ayarlar → (Uygulamalar →) Sesli Notlar → Ses Kalitesi: **Kayıpsız**). Android'de
  yerleşik *Ses Kaydedici*; ayarlarda en yüksek kalite ya da WAV seçeneği varsa onu seçin.
- **Filtre kullanmayın:** Telefonun "Kaydı iyileştir", "gürültü azaltma", "ses izolasyonu" gibi seçenekleri sese metalik,
  su altı gibi izler bırakır ve bu izler klona geçer. Gerekirse SesKlon'un ölçülü iyileştirmesini kullanın (bölüm 10).
- **Tutuş:** Telefonun alt kenarındaki mikrofon size dönük, ağzınızdan 20–30 cm uzakta olsun. Telefonu bir kitabın
  üstüne koymak elde tutmaktan iyidir.
- **Uçak modu:** Bildirim sesleri ve şebeke paraziti kaydı bozar.
- **Aktarma:** Dosyayı AirDrop, kablo, e-posta eki ya da bulut klasörüyle **dosya olarak** aktarın. WhatsApp/Telegram
  sesli mesajı ve telefon görüşmesi kaydı tizleri keser; analiz `low_bandwidth` verir, klon boğuk çıkar.
- **Tarayıcıdan kayıt:** SesKlon'u telefonun tarayıcısında açıp "Mikrofondan kaydet" ile de kaydedebilirsiniz. Ancak
  tarayıcılar mikrofona yalnızca `https` ya da `localhost` adreslerinde izin verir; `http://<bilgisayarın-ip>:8000`
  üzerinden açtıysanız kaydı telefonun kaydedicisiyle alıp dosya olarak yükleyin.

## 4. Süre

- **10–15 sn akıcı konuşma idealdir.** SesKlon referansın en fazla 15 sn'sini kullanır (`MAX_REF_SECONDS`); daha uzun
  kayıtlarda konuşmanın en yoğun bölümü otomatik seçilir.
- 7 sn'nin altı analizde `too_short` uyarısı, 4 sn'nin altı hata verir. Sessizlikler kırpıldıktan sonra 2 sn'den az
  konuşma kalırsa kayıt kabul edilmez.
- 25 sn'den uzun kayıt sorun değildir (`too_long` yalnızca bilgi notudur); yine de en temiz 10–20 sn'yi kendiniz
  seçmek daha iyi sonuç verebilir.
- Başta ve sonda **yaklaşık yarım saniye sessiz kalın:** oda tonu bu bölümden alınır. Bir saniyeden uzun sessizlik
  bırakmayın; uzun boşluklar `low_speech_ratio` uyarısı verir.

## 5. Ton ve enerji

- **Klon, kaydınızın tonunu taklit eder.** Monoton okursanız monoton, canlı anlatırsanız canlı üretir. Videoda nasıl
  konuşacaksanız (sakin bir anlatım mı, enerjik bir tanıtım mı) öyle kaydedin.
- **Okumayın, anlatın.** Metni iki üç kez okuyup sonra birine anlatır gibi söyleyin. Gülümseyerek konuşmak sese
  duyulur ve çoğu içerikte iyi sonuç verir.
- **Temel (nötr) kayıtta** fısıldamayın, bağırmayın, ses taklidi yapmayın, gülmeyin. Duygular için duygu kayıtları
  (bölüm 7), gülme ve iç çekme gibi sesler için tepki kayıtları (bölüm 8) ekleyin.
- **Ritminiz kopyalanır:** SesKlon kayıttaki ortalama duraklama sürenizi ölçer (`pauses.scale`) ve üretimdeki cümle
  arası duraklamaları buna göre ayarlar. Cümle aralarında doğal nefes alın; nefesleri bastırmaya ya da sonradan
  silmeye çalışmayın.
- **Tempo:** Saniyede yaklaşık 3,8–5,8 hece "normal" sayılır. Sohbet temponuzda okuyun; çok hızlı okuma
  (`too_fast`) ya da tek tek sözcük okuma (`too_slow`) klona da geçer.

## 6. Fonetik denge: örnek okuma metinleri

Türkçeye özgü sesler (ç, ş, ğ, ö, ü, ı) kayıtta geçerse model bunları sizin ağzınızdan duyar; soru ve ünlem cümleleri
tonlama aralığınızı gösterir. Aşağıdaki üç metnin her biri bu harflerin hepsini içerir ve normal tempoda 12–15 sn
sürer. "Sesler" sekmesindeki okuma metinlerine ek olarak kullanabilirsiniz; içeriğinize en yakın olanı seçin.

**Metin 1 — Sohbet**

> Geçen hafta sonu kuzenimle Kadıköy'de buluştuk. Önce çarşıda biraz dolaştık, sonra sahilde oturup simit yedik,
> çay içtik. Hava öyle güzeldi ki, doğrusu eve dönmek hiç içimden gelmedi! Sen en son ne zaman böyle keyifli bir gün
> geçirdin?

**Metin 2 — Anlatım**

> Dağ köyündeki eski değirmenin yanında, ağaçların gölgesinde küçük bir çeşme vardı. Çocuklar her akşam oraya koşup
> soğuk suyla yüzlerini yıkarlardı. Yaşlı değirmenci onlara gülümseyip "Acele etmeyin, su kaçmıyor ya!" derdi.

**Metin 3 — Bilgilendirme**

> Peki, iyi bir uyku için neler yapabiliriz? Uzmanlar, yatmadan önce telefonu bırakmayı, odayı serin ve karanlık
> tutmayı öneriyor. Öğleden sonra çay ve kahveyi azaltmak da işe yarıyor. Küçük alışkanlıklar, büyük farklar yaratır.

## 7. Duygu kayıtları

Metinde `[üzgün]` gibi bir etiket kullandığınızda SesKlon, o duygu için kaydınız varsa onu referans alır. Duyguyu
asıl taşıyan referansın tonu olduğundan, duygu etkisini en çok artıran adım budur. Kayıt yoksa nötr kaydınız
kullanılır ve duygu yalnızca üretim ayarlarıyla (vurgu, tempo, duraklama) verilir.

- **Nerede:** Sesler sekmesi → ses kartı → **Duygu kayıtları**. Her duygu için hazır bir okuma metni gösterilir.
- **Aynı koşullar:** Temel kayıtla aynı oda, aynı mikrofon, aynı mesafe. Koşullar değişirse duygular arasında ses
  rengi de değişir (Tutarlılık katmanı bunu ±3 dB'ye kadar törpüler, tamamen silmez).
- **Süre:** 8–12 sn. Duyguyu bütün sesinizle verin ama karikatürleştirmeyin; doğal bir oyunculuk en iyi sonucu verir.
- **Hepsi şart değil:** Önce en çok kullanacağınız 3–4 duyguyu kaydedin.
- **Yoğunluk, karışım ve geçiş** aynı kaydı kullanır: `[çok üzgün]` üzgün kaydını, `[üzgün+umutlu]` birincil
  duygunun (üzgün) kaydını, `[heyecanlı→sakin]` bölüm boyunca başlangıç duygusunun kaydını referans alır; şiddet
  üretim ayarlarıyla verilir ([Etiketler](ETIKETLER.md#3-duygu-yoğunluğu)).
- `[normal]` temel kaydınızdır; `[hızlı]` ve `[yavaş]` tempo etiketleridir, kayıt almazlar.

| Duygu | Nasıl okunur |
|---|---|
| heyecanlı | Sesi bir ton yükseltip tempoyu hafifçe artırın, cümle sonlarını yukarıda bitirin; bağırmadan, gülümseyerek. |
| mutlu | Gülümseyerek okuyun; ton aydınlık, tempo rahat ve akıcı olsun. |
| sakin | Yavaş ve yumuşak, cümle aralarında nefes alarak, birini rahatlatır gibi okuyun. |
| ciddi | Düz ve kararlı bir tonla, cümle sonlarında sesi aşağı indirerek, gereksiz vurgu yapmadan okuyun. |
| üzgün | Enerjiyi düşürüp yavaşlayın, cümle sonlarını alçaltıp söndürün; ağlamaklı taklit yapmayın. |
| kızgın | Ünsüzleri sert ve vurgulu söyleyin ama bağırmayın; kırpılma olmaması için mikrofondan biraz uzaklaşın. |
| şaşkın | Soru cümlelerinde sesi belirgin biçimde yükseltin, "Ne?" gibi tepkileri ani ve kısa verin. |
| korkmuş | Biraz nefesli, hızlı ve alçak sesle konuşun; cümleler arasında kısa, kesik nefesler alın. |
| fısıltı | Ses tellerini titreştirmeden gerçekten fısıldayın; mikrofona biraz yaklaşın ama doğrudan üflemeyin. |
| vurgulu | Önemli sözcüklerin üzerine basın, kısa duraklamalarla altlarını çizin. |
| samimi | Yakın bir arkadaşla konuşur gibi, sıcak ve biraz daha alçak sesle, gülümseyerek okuyun. |
| sıkılmış | Enerjisiz ve isteksiz, düz bir tonla okuyun; "of" gibi iç çekmeleri doğal bırakın. |
| alaycı | Sözcükleri hafifçe uzatıp abartılı bir tatlılıkla söyleyin; vurguyu beklenmedik yerlere koyun. |
| nazik | Yumuşak, saygılı ve yardımsever bir tonla, sesi yükseltmeden ve cümle sonlarını yumuşak bitirerek okuyun. |
| gururlu | Dik durup dolu ve net bir sesle, bir başarıyı anlatır gibi ama bağırmadan okuyun. |
| umutlu | Yumuşak başlayıp cümle sonlarına doğru aydınlanın; ileriye bakan, sıcak bir ton kullanın. |
| nostaljik | Yavaş, hafif buruk ve hayal kurar gibi, anlattığınız anı gözünüzün önüne getirerek okuyun. |
| gergin | Hızlı ve kesik konuşun, sık ve sığ nefes alın; sesin hafifçe titremesine izin verin. |
| romantik | Alçak, yumuşak ve yakın bir sesle, acele etmeden, sözcükleri sevgiyle uzatarak okuyun. |
| çocuksu | Perdeyi biraz yükseltip oyunbaz ve meraklı okuyun; sesi zorlayıp çizgi film karakterine dönüştürmeyin. |
| otoriter | Kısa, net ve kesin konuşun; cümle sonlarında sesi düşürün, soru tonuna kaçmayın. |

## 8. Gerçek tepki kayıtları

Model gülme, iç çekme, öksürme gibi sesleri gerçekten üretemez; kaydı olmayan `[gülme]` "Hahaha!" diye okunur ve yapay
duyulur. Kendi gülmenizi bir kez kaydederseniz o sesle yazdığınız her `[gülme]` etiketinde **sizin gülmeniz** çalınır.
SesKlon'u en çok "insan gibi" yapan adımlardan biridir.

**Nasıl eklenir:** Sesler sekmesi → ses kartı → **Gerçek tepkiler** → tepkiyi seçin → gösterilen yönergeyi okuyun →
**● Kaydet** (mikrofon, en fazla 5 sn) ya da "…ya da dosya" → **Ekle**. Kaydı yenilemek için aynı tepkiyi seçip yeniden
ekleyin; eskisinin yerine geçer. API: `POST /api/voices/{id}/nonverbal` ([API](API.md#gerçek-tepki-kayıtları)).

**Kayda ne olur:** baş ve sondaki sessizlik kırpılır; 3 sn'den uzunsa en enerjik 3 sn alınır; seviye dengelenir
(−22 dBFS). 0,15 sn'den kısa ya da sessiz kayıt kabul edilmez. Üretimde tepki önceki konuşmanın yaklaşık 4 dB altına
oturtulur ve her kullanımda biraz farklı çalınır (seviye ±1,5 dB; ffmpeg varsa tempo ±%3, perde ±0,3 yarım ton): aynı
gülme iki kez birebir aynı duyulmaz.

**Kurallar**

- **Aynı koşullar:** temel kayıtla aynı oda, mikrofon ve mesafe; yoksa tepki konuşmadan "ayrı" duyulur.
- **Yalnızca tepki:** gülerken ya da iç çekerken söz söylemeyin; önünde ve arkasında uzun sessizlik bırakmayın.
- **Kısa ve doğal:** 1–3 sn yeterli. Abartılı, "sahne" gülmesi metinde de abartılı duyulur.
- **Kırpılmasın:** kahkaha ve öksürük gibi gür seslerde mikrofondan bir karış uzaklaşın ya da hafifçe yana dönün.
- **Kendi sesiniz:** dizi ya da videodan kesilmiş başkasının gülmesini eklemeyin; ses rengi sizinkiyle uyuşmaz ve
  izin gerektirir.
- **Öncelik:** önce en sık kullandıklarınız — gülme, kıkırdama, iç çekme, hmm. Kalanlar zamanla.

**Tepkiler ve yönergeler** (kayıt ekranında da aynı yönerge görünür; metindeki eş adlar için:
[Etiketler → Sözsüz tepkiler](ETIKETLER.md#9-sözsüz-tepkiler))

| Tepki | Metinde | Nasıl kaydedilir |
|---|---|---|
| Gülme | `[gülme]` | Komik bir şey hatırla ve içten, doğal bir kahkaha at — 1–3 saniye. Zorlama; kısa bir 'hahaha' bile olur. |
| Kahkaha | `[kahkaha]` | Seni gerçekten güldüren bir anı düşün ve kendini bırak: gür, dolu bir kahkaha — 2–3 saniye. Ses patlamasın diye mikrofondan bir karış uzaklaş. |
| Kıkırdama | `[kıkırdama]` | Gülmemeye çalışırken kaçıveren kısa, kısık bir kıkırdama — 'hihi' ya da 'kıkır kıkır', 1–2 saniye. Ağzın yarı kapalı olabilir. |
| İç çekme | `[iç çekme]` | Yorucu bir günün sonunda koltuğa yeni oturmuşsun gibi derin bir nefes al ve 'ahh' diye yavaşça bırak — 1–2 saniye. Abartma, hafif olsun. |
| Hmm | `[hmm]` | Bir soruyu tartıyormuşsun gibi ağzın kapalı, düşünceli bir 'hmm' — 1 saniye kadar. Sonu nasıl gelirse öyle bırak. |
| Of | `[of]` | Canını sıkan küçük bir şeye tepki verir gibi 'offf' de — bıkkın ama sevimli, 1 saniye kadar. |
| Nefes verme | `[nefes verir]` | Rahatlamışsın gibi ağzından sesli bir nefes ver — 'hoff', yarım ile 1,5 saniye arası. |
| Öksürük | `[öksürür]` | Boğazına bir şey kaçmış gibi bir iki kez doğal öksür — 1 saniye kadar. Mikrofona doğrudan değil, hafif yana dönerek. |
| Boğaz temizleme | `[boğaz temizler]` | Söze girmeden önceki gibi kısa bir 'ehem' ile boğazını temizle — yarım ile 1 saniye arası. |
| Esneme | `[esner]` | Uykun gelmiş gibi doğal bir esneme — 'aaah', 1–2 saniye. Rahat bırak, sonu kendiliğinden sönsün. |
| Ağlama | `[ağlar]` | Duygulandığın bir anı düşün: kısa, burnunu çeken hafif bir ağlama ya da birkaç kesik hıçkırık — 1–3 saniye. Kendini zorlama. |
| Şaşırma | `[şaşırır]` | Hiç beklemediğin bir haber almışsın gibi içten şaşır: kısa bir 'Aa!' ya da 'Vay!' — 1 saniye kadar. |
| Hı hı (onay) | `[hıh]` | Karşındakini dinlerken onaylar gibi ağzın kapalı, kısa bir 'hı hı' — yarım ile 1 saniye arası. |
| Mmm | `[mmm]` | Çok sevdiğin bir tadı alıyormuşsun gibi ağzın kapalı, keyifli bir 'mmm' — 1 saniye kadar. |
| Cık cık | `[cık]` | 'Olmaz' der gibi dilini damağına vurarak iki kez 'cık cık' yap — yarım saniye kadar. |

- `[tüh]`, `[aman]`, `[şey]`, `[ıslık]`, `[hıçkırır]` gibi tepkiler kaydedilemez; her zaman okunur.
- Hangi tepkilerin gerçek kayıttan çalındığı üretim sonucunda "Kullanılan tepkiler" satırında görünür.
- Tepki kayıtları sesin yedek zip'ine dahildir; diyalogda her konuşmacı kendi tepki kayıtlarını kullanır.

## 9. Analiz puanı nasıl yorumlanır

Kayıt seçildiği anda kaydedilmeden incelenir (`POST /api/analyze`); ses kaydedilince analiz sesle birlikte saklanır ve
ses kartındaki **Analiz** düğmesiyle yeniden görülebilir (`GET /api/voices/{id}/analysis`). Duygu kayıtları da analiz edilir.

**Puan ve derece.** Puan 100'den başlar; her sorun ağırlığı kadar puan düşürür.

| Puan | Derece | Ne yapmalı |
|---|---|---|
| 85–100 | mükemmel | Olduğu gibi kullanın. |
| 70–84 | iyi | Kullanılabilir; uyarıları düzeltmek benzerliği artırır. |
| 50–69 | orta | Çalışır ama gürültü, yankı ya da boğukluk klona geçebilir; önerilere göre yeniden kaydedin ya da **Kaydı iyileştir**'i deneyin (bölüm 10). |
| 0–49 | zayıf | Yeniden kaydedin. |

Her sorunun bir önemi vardır: **error** (hata — mutlaka düzeltin), **warn** (uyarı — düzeltmeniz önerilir),
**info** (bilgi — küçük etki). Analiz ayrıca en fazla dört kısa Türkçe öneri (`tips`) verir.

**Ölçümler**

| Alan | Ne ölçer | İyi aralık |
|---|---|---|
| `duration` | Kayıt süresi (sn) | 10–20 |
| `speech_ratio` | Konuşma içeren bölümün oranı | 0,6 ve üstü |
| `snr_db` | Konuşmanın arka plan gürültüsüne oranı (dB) | 30 ve üstü (40+ çok iyi) |
| `noise_floor_dbfs` | Oda tonu (sessiz bölüm) seviyesi | Ne kadar düşükse o kadar iyi (−60 dBFS ve altı) |
| `peak_dbfs` / `rms_dbfs` | Tepe / ortalama seviye | Tepe −6…−3, ortalama −24…−16 dBFS |
| `clipping_ratio` | Tavana vuran örneklerin oranı | 0 |
| `bandwidth_hz` | Kaydın frekans genişliği | 6500 Hz ve üstü |
| `reverb` | Yankı: `düşük` / `orta` / `yüksek` | düşük |
| `f0` | Perde: ortanca, aralık (yarım ton), etiket (`kadın` / `erkek` / `belirsiz`) | Aralık 4 yarım ton ve üstü |
| `speaking_rate` | Saniyedeki hece sayısı ve etiketi (`yavaş` / `normal` / `hızlı`) | 3,8–5,8 (normal) |
| `pauses` | Duraklama sayısı, ortalama/ortanca süre, `scale` (kişisel duraklama çarpanı, 0,7–1,5) | Bilgi amaçlı; `scale` üretimde kullanılır |
| `breaths` | Bulunan nefeslerin sayısı ve konumları | Bilgi amaçlı; bulunan nefes üretimde kullanılır |

**Sorun kodları** (eşikler yaklaşıktır)

| Kod | Ne zaman çıkar | Ne yapmalı |
|---|---|---|
| `too_short` | 7 sn'den kısa (4 sn altı hata) | 10–20 sn akıcı konuşun; soru, ünlem ve düz cümle içeren bir metin okuyun. |
| `too_long` | 25 sn'den uzun (bilgi) | Sorun değil, en dolu bölüm seçilir; isterseniz en temiz 10–20 sn'yi kendiniz kesin. |
| `low_speech_ratio` | Kaydın %60'ından azı konuşma (%40 altı uyarı; hiç konuşma yoksa hata) | Baştaki, sondaki ve aradaki uzun boşlukları kesin; doğru mikrofonun seçildiğini kontrol edin. |
| `noisy` | Sinyal/gürültü 30 dB'nin altında (20 dB altı uyarı) | Klima, fan, buzdolabını kapatın; pencere ve kapıyı kapatın; mikrofona 20–30 cm yaklaşın. Yeniden kaydedemiyorsanız **Kaydı iyileştir**. |
| `clipping` | Örneklerin %0,01'inden fazlası tavanda ya da düz tepeler var (%0,1 üstü hata) | Kazancı düşürün ya da biraz uzaklaşın; tepeler −6 dBFS civarında kalsın ve yeniden kaydedin. |
| `too_loud` | Tepe −0,5 dBFS'in üstünde (bilgi) | Kazancı biraz düşürün. |
| `too_quiet` | Ortalama seviye −32 dBFS'in altında | Mikrofona yaklaşın ya da kazancı artırın; ortalama −24…−16 dBFS olsun. |
| `low_bandwidth` | Frekans genişliği 6,5 kHz'in altında (4 kHz altı hata) | Telefon görüşmesi, WhatsApp ya da Bluetooth kulaklık kaydı kullanmayın; ses kaydediciyle WAV/kayıpsız kaydedin. |
| `reverb` | Yankı orta (bilgi) ya da yüksek (uyarı) | Eşyalı küçük bir odaya geçin; boş oda, banyo ve mutfaktan kaçının; mikrofona biraz yaklaşın. |
| `monotone` | Perde aralığı 4 yarım tondan dar (bilgi) | Anlatır gibi okuyun; vurgulu sözcüklerde ses doğal olarak yükselip alçalsın. |
| `too_fast` | Saniyede ~5,8 heceden hızlı (bilgi) | Biraz yavaşlayın, cümle aralarında nefes alın; klon bu ritmi taklit eder. |
| `too_slow` | Saniyede ~3,8 heceden yavaş (bilgi) | Sohbet temponuzda, cümle bütünlüğüyle okuyun. |
| `dc_offset` | Sinyalde sabit kayma (tepenin %2'sinden fazla; bilgi) | Başka bir mikrofon girişi, kablo ya da kayıt uygulaması deneyin; **Kaydı iyileştir** kaymayı giderir. |

**Analiz üretimi nasıl etkiler:** `pauses.scale` sesin duraklama çarpanı olarak saklanır ve istekteki `pause_scale` ile
çarpılır. Kaydın en sessiz bölümü oda tonu, bulunan nefes de cümle arası nefes olarak kullanılır; kayıtta sessiz bölüm
ya da nefes yoksa bunların sentetik karşılıkları devreye girer.

## 10. Kaydı iyileştirme

Yeniden kayıt alamıyorsanız ses kartındaki **✨ Kaydı iyileştir** temel kaydı ölçülü biçimde temizler. Analiz gürültü,
kısık seviye, DC kayması ya da orta/zayıf puan gösteriyorsa düğme öne çıkar; elektrik uğultusu duyuyorsanız puan iyi
olsa da deneyin (uğultuyu analiz değil iyileştirme ölçer).

- **Yaptıkları:** DC kaymasını giderir, tıkları temizler, şebeke uğultusunu (50/60 Hz ve iki harmoniği) süzer, arka
  plan gürültüsünü azaltır (konuşmanın harmoniklerine dokunmadan, en çok 12 dB — daha fazlası yapay iz bırakır),
  70 Hz altındaki gümbürtüyü keser ve seviyeyi dengeler.
- **Karar:** Temizlenen kayıt yeniden analiz edilir; puan **en az 3** artarsa uygulanır. Artmazsa kayıt değişmez;
  önce/sonra puanını görüp **Yine de uygula** diyebilirsiniz.
- **Geri alma:** Özgün kayıt yedekte durur; **↺ Geri al** (ya da **İyileştirmeyi geri al**) onu geri yükler.
- **Düzeltmedikleri:** yankı, kırpılma, dar bant (telefon görüşmesi, WhatsApp), arka plandaki müzik ya da ikinci
  konuşmacı. Bunlar için yeniden kaydedin.
- Yalnızca temel kayda uygulanır; duygu ve tepki kayıtlarını temiz ortamda alın. Uyguladıktan sonra bir cümle üretip
  dinleyin; ses metalikleştiyse geri alın.

## 11. Sık hatalar

- WhatsApp sesli mesajı ya da telefon görüşmesi kaydı yüklemek: dar bant, boğuk klon.
- Telefonun "kaydı iyileştir" / gürültü azaltma filtresini açık bırakmak: metalik, yapay iz.
- Arka planda müzik, televizyon ya da ikinci bir konuşmacı: model karışık bir ses üretir. Videodan kesit alırken
  müziksiz bir bölüm seçin.
- "Okuma sesi" ile monoton okumak: klon da monoton olur.
- Mikrofona çok yakından ya da bağırarak kaydetmek: kırpılma sonradan düzeltilemez.
- Kaydın başında ve sonunda klavye, fare ya da masa sesleri.
- Duygu ve tepki kayıtlarını farklı odalarda ya da farklı mikrofonla almak: ses rengi değişir, tepki konuşmadan ayrı duyulur.
- Tepki kaydına konuşma karıştırmak ("hahaha, çok komik"): kayıt her `[gülme]`de aynen çalınır.
- Kaydı bir ses programında sıkıştırıp (compressor) ya da "normalize" edip yüklemek: SesKlon seviyeyi zaten dengeler;
  ek işlem gürültüyü yükseltir.
- Uzun "eee"ler, öksürük ve yarım kalmış cümlelerle dolu bir referans kaydı (öksürük için ayrı tepki kaydı ekleyin).
- Başkasının sesini izinsiz kullanmak: hukuki sorumluluk doğurur (bkz. [README → Sorumluluk](../README.md#sorumluluk-ve-izin)).
