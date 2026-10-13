# Referans kaydı rehberi

SesKlon bir sesi tek bir kısa kayıttan klonlar. Model kaydı "düzeltmez", taklit eder: ses rengi, tempo, enerji,
duraklama alışkanlığı, hatta odanın yankısı ve uğultusu klona geçer. SesKlon ayrıca kaydınızdaki **oda tonunu**
(konuşma aralarındaki ortam sesi) duraklamaları doldurmak için, **nefeslerinizi** de cümle aralarında kullanır. Bu yüzden
sonucu en çok etkileyen şey, 10–15 saniyelik bu kayıttır.

## Kısa kontrol listesi

- [ ] Küçük, eşyalı, sessiz bir oda (perde, halı, dolap); boş oda, banyo ve mutfak değil
- [ ] Klima, vantilatör, buzdolabı kapalı; telefon uçak modunda ya da "Rahatsız Etmeyin"de
- [ ] Mikrofon ağızdan 20–30 cm (bir karış), tam önde değil hafifçe yanda; elde değil, sabit bir yerde
- [ ] 10–15 sn akıcı konuşma; başta ve sonda yaklaşık yarım saniye sessizlik
- [ ] Videoda ya da yayında nasıl konuşacaksanız o enerjiyle, "okur gibi" değil "anlatır gibi"
- [ ] WAV ya da kayıpsız kayıt; WhatsApp sesli mesajı ya da telefon görüşmesi kaydı değil
- [ ] Analiz puanı en az 70 ("iyi"); 85 ve üstü ideal

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
- **Filtre kullanmayın:** "Kaydı iyileştir", "gürültü azaltma", "ses izolasyonu" gibi seçenekler sese metalik, su altı
  gibi izler bırakır ve bu izler klona geçer.
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
- **Temel (nötr) kayıtta** fısıldamayın, bağırmayın, ses taklidi yapmayın. Duygular için ayrı duygu kayıtları
  ekleyin (bölüm 7).
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
  rengi de değişir.
- **Süre:** 8–12 sn. Duyguyu bütün sesinizle verin ama karikatürleştirmeyin; doğal bir oyunculuk en iyi sonucu verir.
- **Hepsi şart değil:** Önce en çok kullanacağınız 3–4 duyguyu kaydedin.
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

## 8. Analiz puanı nasıl yorumlanır

Kayıt seçildiği anda kaydedilmeden incelenir (`POST /api/analyze`); ses kaydedilince analiz sesle birlikte saklanır ve
ses kartındaki **Analiz** düğmesiyle yeniden görülebilir (`GET /api/voices/{id}/analysis`). Duygu kayıtları da analiz edilir.

**Puan ve derece.** Puan 100'den başlar; her sorun ağırlığı kadar puan düşürür.

| Puan | Derece | Ne yapmalı |
|---|---|---|
| 85–100 | mükemmel | Olduğu gibi kullanın. |
| 70–84 | iyi | Kullanılabilir; uyarıları düzeltmek benzerliği artırır. |
| 50–69 | orta | Çalışır ama gürültü, yankı ya da boğukluk klona geçebilir; önerilere göre yeniden kaydedin. |
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
| `noisy` | Sinyal/gürültü 30 dB'nin altında (20 dB altı uyarı) | Klima, fan, buzdolabını kapatın; pencere ve kapıyı kapatın; mikrofona 20–30 cm yaklaşın. |
| `clipping` | Örneklerin %0,01'inden fazlası tavanda ya da düz tepeler var (%0,1 üstü hata) | Kazancı düşürün ya da biraz uzaklaşın; tepeler −6 dBFS civarında kalsın ve yeniden kaydedin. |
| `too_loud` | Tepe −0,5 dBFS'in üstünde (bilgi) | Kazancı biraz düşürün. |
| `too_quiet` | Ortalama seviye −32 dBFS'in altında | Mikrofona yaklaşın ya da kazancı artırın; ortalama −24…−16 dBFS olsun. |
| `low_bandwidth` | Frekans genişliği 6,5 kHz'in altında (4 kHz altı hata) | Telefon görüşmesi, WhatsApp ya da Bluetooth kulaklık kaydı kullanmayın; ses kaydediciyle WAV/kayıpsız kaydedin. |
| `reverb` | Yankı orta (bilgi) ya da yüksek (uyarı) | Eşyalı küçük bir odaya geçin; boş oda, banyo ve mutfaktan kaçının; mikrofona biraz yaklaşın. |
| `monotone` | Perde aralığı 4 yarım tondan dar (bilgi) | Anlatır gibi okuyun; vurgulu sözcüklerde ses doğal olarak yükselip alçalsın. |
| `too_fast` | Saniyede ~5,8 heceden hızlı (bilgi) | Biraz yavaşlayın, cümle aralarında nefes alın; klon bu ritmi taklit eder. |
| `too_slow` | Saniyede ~3,8 heceden yavaş (bilgi) | Sohbet temponuzda, cümle bütünlüğüyle okuyun. |
| `dc_offset` | Sinyalde sabit kayma (tepenin %2'sinden fazla; bilgi) | Başka bir mikrofon girişi, kablo ya da kayıt uygulaması deneyin. |

**Analiz üretimi nasıl etkiler:** `pauses.scale` sesin duraklama çarpanı olarak saklanır ve istekteki `pause_scale` ile
çarpılır. Kaydın en sessiz bölümü oda tonu, bulunan nefes de cümle arası nefes olarak kullanılır; kayıtta sessiz bölüm
ya da nefes yoksa bunların sentetik karşılıkları devreye girer.

## 9. Sık hatalar

- WhatsApp sesli mesajı ya da telefon görüşmesi kaydı yüklemek: dar bant, boğuk klon.
- Telefonun "kaydı iyileştir" / gürültü azaltma filtresini açık bırakmak: metalik, yapay iz.
- Arka planda müzik, televizyon ya da ikinci bir konuşmacı: model karışık bir ses üretir. Videodan kesit alırken
  müziksiz bir bölüm seçin.
- "Okuma sesi" ile monoton okumak: klon da monoton olur.
- Mikrofona çok yakından ya da bağırarak kaydetmek: kırpılma sonradan düzeltilemez.
- Kaydın başında ve sonunda klavye, fare ya da masa sesleri.
- Duygu kayıtlarını farklı odalarda ya da farklı mikrofonla almak: duygular arasında ses rengi değişir.
- Kaydı bir ses programında sıkıştırıp (compressor) ya da "normalize" edip yüklemek: SesKlon seviyeyi zaten dengeler;
  ek işlem gürültüyü yükseltir.
- Uzun "eee"ler, öksürük ve yarım kalmış cümlelerle dolu bir kayıt.
- Başkasının sesini izinsiz kullanmak: hukuki sorumluluk doğurur (bkz. [README → Sorumluluk](../README.md#sorumluluk-ve-izin)).
