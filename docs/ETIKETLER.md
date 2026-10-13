# Etiketler, noktalama ve stiller

Metnin nasıl seslendirileceğini üç şey belirler: metnin içine yazdığınız **etiketler**, **noktalama** ve seçtiğiniz
**stil**. Bu sayfa hepsinin tam başvurusudur (v4). Kısa özet: [README → Stiller ve etiketler](../README.md#stiller-ve-etiketler).

**İçindekiler:** [1. Yazım kuralları](#1-yazım-kuralları) · [2. Duygular](#2-duygular-24) ·
[3. Yoğunluk](#3-duygu-yoğunluğu) · [4. Karışım](#4-duygu-karışımı) · [5. Geçiş (kayış)](#5-duygu-geçişi-kayış) ·
[6. Hız, perde, konuşmacı](#6-satır-içi-kontroller-hız-perde-konuşmacı) · [7. Vurgu](#7-vurgu) ·
[8. Okunuş](#8-okunuş-yazılışokunuş) · [9. Sözsüz tepkiler](#9-sözsüz-tepkiler) · [10. Duraklamalar](#10-duraklamalar) ·
[11. Noktalama](#11-noktalamanın-etkisi) · [12. Diyalog biçimleri](#12-diyalog-biçimleri) ·
[13. Stiller](#13-stil-ön-ayarları) · [14. Örnekler](#14-örnek-metinler) · [15. Pratik öneriler](#15-pratik-öneriler)

## 1. Yazım kuralları

| Tür | Yazım | Etki |
|---|---|---|
| Duygu (sürekli) | `[üzgün] Metin…` | Bir sonraki duygu etiketine kadar geçerli |
| Duygu (kapsamlı) | `[heyecanlı: Yalnızca bu cümle.]` | Yalnızca parantezin içine; sonra önceki duyguya dönülür |
| Yoğunluk | `[heyecanlı:3]` `[çok kızgın]` `[üzgün %80]` | Duygunun şiddeti ([bölüm 3](#3-duygu-yoğunluğu)) |
| Karışım | `[üzgün+umutlu]` | İki-üç duygunun harmanı ([bölüm 4](#4-duygu-karışımı)) |
| Geçiş (kayış) | `[heyecanlı→sakin]` `[sakinleşerek]` | Bölüm boyunca bir duygudan ötekine ([bölüm 5](#5-duygu-geçişi-kayış)) |
| Kontrol | `[hız:0.9]` `[perde:+1]` `[ses:Ayşe]` | Tempo, perde, konuşmacı; duygudan bağımsız ([bölüm 6](#6-satır-içi-kontroller-hız-perde-konuşmacı)) |
| Sıfırlama | `[normal]` · `[hız]` `[perde]` | Duyguyu · kontrolü kaldırır |
| Vurgu | `*sözcük*` `[vurgu] sözcük` `[vurgu: öbek]` | Tek sözcük ya da kısa öbek vurgulanır |
| Okunuş | `{yazılış\|okunuş}` | Sözcük yazdığınız gibi okunur ([bölüm 8](#8-okunuş-yazılışokunuş)) |
| Sözsüz tepki | `[gülme]` `[iç çekme]` `[hmm]` | Sesin gerçek tepki kaydı ya da en yakın ünlem |
| Duraklama | `[nefes]` `[duraklama]` `[1.5 sn]` | O noktada ara |

Kurallar:

- Büyük/küçük harf ve Türkçe karakter fark etmez: `[HEYECANLI]`, `[heyecanli]`, `[Heyecanlı]` aynıdır.
- Etiketlerin Türkçe ve İngilizce eş adları vardır; ElevenLabs tarzı `[excited]`, `[whispers]`, `[laughs]`, `[sighs]` de
  çalışır.
- Tanınmayan etiket sessizce yok sayılır; köşeli parantez içindeki hiçbir şey seslendirilmez (`[not: burayı düzelt]`).
- Kapsamlı etiketin adı en fazla 30 karakter olabilir (`[çok heyecanlı: …]`); içerik herhangi bir uzunlukta olabilir.
- Satır başındaki "Heyecanlı: …" biçimi duygu etiketi değildir (diyalogda konuşmacı adı sayılır); köşeli parantez kullanın.
- Duygu, kontrol, duraklama ve sözsüz etiketleri metni o noktada **ayrı parçalara böler**; her parça ayrı üretilir.
  Etiketleri mümkünse cümle başlarına ya da cümle aralarına koyun.
- Üretim sonucunun ayrıntılarında (`params.chunks`) her parçanın duygusu, yoğunluğu, referansı ve duraklaması görünür;
  bir etiketin çalışıp çalışmadığını buradan anlayabilirsiniz.

## 2. Duygular (24)

**Vurgu** (`exaggeration`), **Sadakat** (`cfg_weight`) ve **Sıcaklık** (`temperature`), o etiketli bölüm üretilirken
kullanılan değerlerdir; "—" olanlarda istekteki ya da stildeki değer geçerlidir. **Duraklama ×** cümle arası
duraklamaların çarpanıdır. Noktalama (bölüm 11) ve yoğunluk (bölüm 3) bunların üstüne eklenir; motor sonucu güvenli
aralıkta tutar (vurgu 0,3–0,95, sadakat 0,3–0,7).

| Etiket | Ne zaman | Eş anlamlılar | Vurgu | Sadakat | Sıcaklık | Duraklama × |
|---|---|---|---|---|---|---|
| `[normal]` | Doğal, nötr okuma; ek duygu ayarı yapılmaz. | `nötr`, `neutral`, `doğal`, `natural`, `düz`, `plain` | — | — | — | 1 |
| `[heyecanlı]` | Enerjik ve coşkulu; tanıtım, müjde ve sürprizler için. | `heyecanli`, `excited`, `coşkulu`, `enerjik`, `energetic`, `enthusiastic`, `heyecan`, `coşku`, `thrilled`, `hyped`, `canlı`, `lively` | 0,7 | 0,35 | 0,9 | 0,8 |
| `[mutlu]` | Neşeli, gülümseyen bir ton; teşekkür ve iyi haberler için. | `happy`, `neşeli`, `cheerful`, `sevinçli`, `joyful`, `glad`, `keyifli`, `sevinç`, `neşe`, `pleased` | 0,7 | 0,4 | 0,85 | 0,9 |
| `[sakin]` | Yavaş, yumuşak ve huzurlu; meditasyon ve rahatlatıcı anlatım için. | `calm`, `huzurlu`, `rahat`, `relaxed`, `soft`, `dingin`, `peaceful`, `serene`, `yumuşak`, `sükûnet`, `sakince` | 0,35 | 0,55 | 0,7 | 1,25 |
| `[ciddi]` | Ağırbaşlı ve kararlı; uyarılar ve önemli duyurular için. | `serious`, `resmi`, `formal`, `kararlı`, `determined`, `ağırbaşlı`, `solemn`, `grave`, `ciddiyetle` | 0,4 | 0,55 | 0,7 | 1,15 |
| `[üzgün]` | Hüzünlü, alçak ve yavaş; kötü haber ve veda anları için. | `uzgun`, `sad`, `hüzünlü`, `kederli`, `melancholic`, `mutsuz`, `hüzün`, `keder`, `upset`, `kırgın`, `melankolik`, `sorrowful` | 0,3 | 0,5 | 0,7 | 1,5 |
| `[kızgın]` | Sert ve yüksek enerjili; öfke ve tepki cümleleri için. | `kizgin`, `angry`, `öfkeli`, `sinirli`, `furious`, `annoyed`, `öfke`, `sinir`, `mad`, `hiddetli`, `rage`, `irritated` | 0,85 | 0,3 | 0,9 | 0,8 |
| `[şaşkın]` | Yüksek perdeli hayret; beklenmedik haberler ve sorular için. | `saskin`, `surprised`, `hayret`, `shocked`, `amazed`, `şaşırmış`, `şok`, `astonished`, `hayretle`, `şaşkınlık` | 0,75 | 0,35 | 0,9 | 1,1 |
| `[korkmuş]` | Hızlı, nefesli ve tedirgin; gerilim ve tehlike anları için. | `korkmus`, `scared`, `endişeli`, `nervous`, `tedirgin`, `anxious`, `korku`, `afraid`, `fearful`, `ürkek`, `panik`, `frightened`, `korkarak` | 0,65 | 0,4 | 0,9 | 0,9 |
| `[fısıltı]` | Kısık, nefesli fısıltı; sır ve gizem anları için. | `fisilti`, `whisper`, `whispers`, `sessiz`, `gizli`, `fısıldar`, `fısıldayarak`, `whispering`, `fısılda`, `kısık` | 0,25 | 0,6 | 0,65 | 1,3 |
| `[vurgulu]` | Sözcükleri bastırarak, net ve güçlü okuma; önemli noktalar için. | `emphasis`, `emphatic`, `önemli`, `dikkat`, `kesin`, `vurgulayarak`, `altını çizerek` | 0,8 | 0,45 | 0,8 | 1,1 |
| `[samimi]` | Sıcak, dostça ve içten; sohbet ve kişisel mesajlar için. | `warm`, `sıcak`, `friendly`, `dostça`, `içten`, `sincere`, `içtenlikle`, `sevecen`, `cana yakın` | 0,55 | 0,45 | 0,8 | 1,05 |
| `[sıkılmış]` | İsteksiz, yorgun ve yavaş; bıkkınlık anları için. | `sikilmis`, `bored`, `bıkkın`, `isteksiz`, `tired`, `yorgun`, `sıkkın`, `bezgin`, `bitkin`, `uninterested`, `weary` | 0,25 | 0,55 | 0,7 | 1,3 |
| `[alaycı]` | İğneleyici, ironik bir ton; dalga geçme ve espri için. | `alayci`, `sarcastic`, `ironik`, `ironic`, `dalga`, `iğneleyici`, `mocking`, `sarkastik`, `alaylı`, `dalgacı` | 0,75 | 0,4 | 0,85 | 1,15 |
| `[nazik]` | Kibar ve yardımsever; müşteri hizmetleri ve karşılama mesajları için. | `kibar`, `polite`, `hizmet`, `courteous`, `nazikçe`, `kibarca`, `müşteri hizmeti`, `customer service` | 0,45 | 0,5 | 0,75 | 1,1 |
| `[gururlu]` | Göğsü kabarmış, güçlü ve onurlu; başarı ve kutlama anları için. | `proud`, `proudly`, `gurur`, `gururla`, `onurlu`, `iftihar` | 0,6 | 0,45 | — | 1 |
| `[umutlu]` | Aydınlık ve iyimser; gelecek, dilek ve cesaret sözleri için. | `hopeful`, `iyimser`, `optimistic`, `umut`, `umut dolu`, `umutla` | 0,55 | — | — | 1 |
| `[nostaljik]` | Yavaş, hatıralara dalmış ve hafif buruk; geçmişi anlatırken. | `nostalgic`, `nostalji`, `özlem`, `özlemli`, `hasret`, `hatıra`, `eski günler` | 0,4 | — | — | 1,3 |
| `[gergin]` | Hızlı ve diken üstünde; geri sayım ve gerilim sahneleri için. | `tense`, `stresli`, `stressed`, `stres`, `gerilim`, `huzursuz`, `uneasy`, `diken üstünde` | 0,6 | 0,4 | 0,85 | 0,85 |
| `[romantik]` | Yumuşak, yavaş ve hafif nefesli; sevgi sözleri için. | `romantic`, `aşık`, `âşık`, `aşk`, `sevgi dolu`, `loving`, `tender`, `şefkatli` | 0,5 | 0,5 | 0,8 | 1,25 |
| `[çocuksu]` | İnce ve oyunbaz; çocuk karakterleri ve masallar için. | `childlike`, `childish`, `çocuk`, `çocukça`, `child`, `kid`, `sevimli`, `cute` | 0,7 | — | — | 1 |
| `[otoriter]` | Güçlü, kontrollü ve buyurgan; talimat ve liderlik konuşmaları için. | `authoritative`, `authority`, `otorite`, `buyurgan`, `commanding`, `emredici`, `komuta` | 0,55 | 0,55 | 0,7 | 1 |
| `[hızlı]` | Tempoyu artırır, duraklamaları kısaltır. | `hizli`, `fast`, `acele`, `quick`, `rapid`, `çabuk`, `seri` | — | — | — | 0,7 |
| `[yavaş]` | Tempoyu düşürür, duraklamaları uzatır. | `yavas`, `slow`, `ağır`, `slowly`, `ağır ağır`, `yavaşça` | — | — | — | 1,4 |

- `[hızlı]` tempoyu ×1,1, `[yavaş]` ×0,9 yapar (duygu etiketlerinin temposu 0,9–1,1 arasında tutulur; daha büyük
  değişiklik için `[hız:0.8]`). Diğer duyguların küçük tempo, perde ve şiddet farkları yalnızca "Ses işleme seviyesi"
  (`emotion_fx`) **hafif** ya da **tam** iken uygulanır; varsayılan **kapalı** en doğal sonucu verir.
- `[vurgulu]` bir duygudur ve bölümün tamamını etkiler; tek bir sözcük için `*sözcük*` ya da `[vurgu]` kullanın.
- Duyguyu en çok, o duygu için aldığınız **duygu kaydı** taşır ([Kayıt rehberi → Duygu kayıtları](KAYIT_REHBERI.md#7-duygu-kayıtları)).
- "İçerikten otomatik duygu" (`auto_emotion`) açıksa etiketsiz cümlelerin duygusu sözcüklerden ("harika", "maalesef",
  "yeter artık"…), olumsuzluktan ("hiç güzel değil"), noktalamadan ve büyük harf oranından tahmin edilir.

```
[samimi] Hoş geldiniz! [ciddi] Başlamadan önce kısa bir uyarı. [normal] Hadi başlayalım.
```

## 3. Duygu yoğunluğu

Bir duygunun şiddetini etiketin içinde ayarlarsınız. Yoğunluk (k) 0,5–1,6 arasındadır; 1 = tablodaki değerler.

| Yazım | k | Not |
|---|---|---|
| `[heyecanlı:1]` · `[heyecanlı:2]` · `[heyecanlı:3]` | 0,7 · 1 · 1,4 | Hafif · normal · güçlü |
| `[biraz üzgün]` `[hafif üzgün]` `[az üzgün]` | 0,65 | Ayrıca `birazcık`, `azıcık`, `hafifçe`, `slightly`, `a bit` |
| `[çok kızgın]` `[epey kızgın]` `[oldukça kızgın]` | 1,35 | Ayrıca `very` |
| `[aşırı heyecanlı]` `[çok çok heyecanlı]` `[son derece heyecanlı]` | 1,6 | Ayrıca `extremely` |
| `[heyecanlı %150]` · `[%120 heyecanlı]` · `[üzgün:%80]` | 1,5 · 1,2 · 0,8 | Yüzde 50–160'a sıkıştırılır (`[kızgın %200]` → 1,6) |

- Sözcük ve sayı birlikte yazılırsa çarpılır ve sınıra sıkıştırılır: `[çok heyecanlı:3]` → 1,35 × 1,4 → 1,6.
- ASCII yazım da tanınır: `[cok kizgin]`, `[asiri heyecanli]`. Kapsamlı yazılabilir: `[çok heyecanlı: Kazandık!]`.
- **Ne değişir:** yoğunluk, duygunun nötrden uzaklığını ölçekler. Vurgu = 0,5 + (vurgu − 0,5) × k (0,25–0,95),
  sadakat = 0,5 + (sadakat − 0,5) × k (0,3–0,7), duraklama çarpanı = 1 + (çarpan − 1) × k; ses işleme açıkken tempo ve
  seviye de. Sıcaklık ve referans kaydı değişmez. Örnek: heyecanlı (vurgu 0,7) `:3` ile 0,78, `:1` ile 0,64 olur.
  Enerjik duygularda vurgu artar; üzgün, sakin gibi düşük enerjili duygularda azalır (daha durgun) ve duraklamalar uzar.

```
[heyecanlı:1] Paketiniz yola çıktı. [heyecanlı:3] Ve yarın kapınızda!
[biraz üzgün] Toplantı ertelendi. [çok üzgün] Proje de iptal edildi.
```

## 4. Duygu karışımı

`[birincil+ikincil]` iki ya da üç duyguyu harmanlar: birincil %70, ikinciller kalan %30'u eşit paylaşır (en çok iki
ikincil; fazlası atılır). Vurgu, sadakat, sıcaklık, tempo, duraklama, seviye ve fısıltı oranı ağırlıklı ortalanır;
referans kaydı **birincilin** kaydıdır. Yoğunlukla birlikte yazılabilir: `[çok üzgün+umutlu]`.

```
[üzgün+umutlu] Zor bir yıldı, biliyorum. Ama önümüzdeki bahar her şey değişecek.
[mutlu+nostaljik] Çocukken bu sokakta saatlerce top oynardık.
```

## 5. Duygu geçişi (kayış)

Bölüm boyunca bir duygudan ötekine yavaşça geçer.

| Yazım | Geçiş |
|---|---|
| `[heyecanlı→sakin]` (ayrıca `->`, `=>`, `>`) | Heyecanlıdan sakine |
| `[→sakin]` | O anki duygudan sakine |
| `[sakinleşerek]` · `[heyecanlanarak]` · `[yumuşayarak]` · `[sertleşerek]` | → sakin · heyecanlı · samimi · kızgın |
| `[hüzünlenerek]` · `[neşelenerek]` · `[ciddileşerek]` | → üzgün · mutlu · ciddi |
| `[heyecanlı→sakin: …]` | Yalnızca parantezin içinde; sonra önceki duyguya dönülür |

- Geçiş, etiketten sonraki metne (bir sonraki etikete kadar) uygulanır; bölüm bitince ses hedef duyguda kalır.
- Geçiş **parça parça** ilerler (≈170 karakterlik cümle grupları). Tek parçalık kısa bölüm doğrudan hedef duyguyla
  okunur; kademeli geçiş için en az iki-üç parçalık (≈300+ karakter) bölüm yazın.
- Bölümün ilk yarısında başlangıç duygusunun, ikinci yarısında hedef duygunun kaydı referans alınır; vurgu, sadakat ve
  duraklama hedefe doğru kayar.

```
[heyecanlı→sakin] Kazandık! İnanamıyorum, gerçekten kazandık ve herkes sahaya koştu, bağırıyor, sarılıyordu.
Sonra kalabalık yavaş yavaş dağıldı, ışıklar söndü. Stadyumda yalnızca rüzgârın sesi kaldı.
```

## 6. Satır içi kontroller: hız, perde, konuşmacı

| Yazım | Değer | Eş ad | Sıfırlama |
|---|---|---|---|
| `[hız:0.9]` | 0,7–1,3; `0,9`, `1.1x`, `%90` de olur | `tempo` | `[hız]`, `[hız:normal]` |
| `[perde:+1]` | −4…+4 yarım ton; `-2`, `−1,5` | `pitch` | `[perde]`, `[perde:normal]` |
| `[ses:Ayşe]` | Konuşmacı adı (en çok 40 karakter) | `konuşmacı` | — (yeni `[ses:Ad]` yazılır) |

- Hız ve perde duygudan bağımsızdır ve bir sonraki aynı tür kontrole kadar sürer; `normal` yerine `varsayılan`,
  `default`, `sıfırla` da yazılabilir. Aralık dışı değer yok sayılır (`[hız:1.5]` etkisizdir).
- `[hız:…]` istekteki **Hız** (`speed`) ve `[hızlı]`/`[yavaş]` ile çarpılır; perde korunur. `[hız:…]` ve
  `[perde:…]` ffmpeg gerektirir (yoksa etkisizdir). ±1–2 yarım tonluk perde doğal kalır; büyük kaymalar sesin
  karakterini değiştirebilir.
- `[ses:Ad]` yalnızca **Diyalog** modunda sesi değiştirir ([bölüm 12](#12-diyalog-biçimleri)); tek sesli
  seslendirmede yok sayılır.

```
[hız:0.85] Şimdi dikkatle dinleyin: şifreniz üç, yedi, dokuz. [hız] Tekrar ediyorum.
[perde:-1] Gecenin bir yarısı kapı çaldı. [perde] Kimse yoktu.
```

## 7. Vurgu

| Yazım | Vurgulanan |
|---|---|
| `Bu *çok* önemli.` | Yıldızlar arasındaki sözcük |
| `**hemen şimdi**` ya da `*hemen şimdi*` | Kısa öbek (en çok 60 karakter) |
| `[vurgu] yarın geliyorum.` | Etiketten sonraki ilk sözcük ("yarın") |
| `[vurgu: hemen şimdi] gel.` | Parantezdeki öbek |

Vurgulu sözcük ayrı bir parça olarak biraz daha güçlü (vurgu +0,15, en çok 0,95) ve biraz daha yavaş (×0,95)
üretilir; önüne 110 ms, ardına 40 ms mikro duraklama gelir. Sözcüğün o bölümdeki her geçişi vurgulanır; yıldızlar ve
etiket okunmaz. `2*3*4` gibi yazımlar vurgu sayılmaz. Az kullanın: her vurgu metni böler.

## 8. Okunuş: {yazılış|okunuş}

Bir sözcüğün bu metinde nasıl okunacağını süslü parantezle yazarsınız:

```
{Claude|Klod} bugün yeni sürümü duyurdu. Toplantı {Zoom|Zum} üzerinden yapılacak.
```

- `{Claude|Klod}` → "Klod"; `{Klod}` → "Klod" (`|` yoksa içerik aynen); okunuş boşsa yazılış kullanılır.
- İç içe yazılmaz; köşeli parantez etiketlerinin içine dokunulmaz. Dilden bağımsız çalışır.
- Okunuş sonraki katmanlardan da geçer (sayılar okunur, konuşma dili uygulanır). Metnin modele nasıl gideceğini
  **Telaffuz → Dene** gösterir. Zincir: okunuş → sohbet kısaltmaları → telaffuz sözlüğü → normalizasyon → konuşma
  dili → (açıksa) konuşma dolguları.
- Aynı sözcük her metinde aynı okunsun istiyorsanız **Telaffuz** sekmesindeki sözlüğe ekleyin (genel ya da yalnız bir
  ses için; API: `/api/lexicon`). Sözlük yalnızca Türkçe metinde uygulanır; sözcük sınırına bakar, büyük/küçük harf
  duyarsızdır, kesmeli eki korur ("Claude'un" → "Klod'un").

## 9. Sözsüz tepkiler

Sesin **gerçek tepki kaydı** varsa (Sesler → ses kartı → **Gerçek tepkiler**) etiket yerine o kayıt çalınır: önceki
konuşma parçasının yaklaşık 4 dB altına oturtulur, her kullanımda hafif farklıdır (seviye ±1,5 dB; ffmpeg varsa tempo
±%3, perde ±0,3 yarım ton) ve ardından 140 ms'lik kısa bir boşlukla konuşma sürer. Kayıt yoksa etiket aşağıdaki ünleme
çevrilir ve önceki cümlenin sonuna eklenerek okunur. Kayıt rehberi: [Gerçek tepki kayıtları](KAYIT_REHBERI.md#8-gerçek-tepki-kayıtları).

**Kaydedilebilir 15 tepki** (eş adlar aynı kayda gider)

| Anahtar | Arayüzde | Metinde eş adlar | Kayıt yoksa okunuş |
|---|---|---|---|
| `[gülme]` | Gülme | `[güler]` `[gülüyor]` `[gülüş]` `[laughs]` `[laugh]` `[laughing]` `[haha]` `[hahaha]` | Hahaha! |
| `[kahkaha]` | Kahkaha | `[kahkaha atar]` `[kahkahalar]` `[laughs hard]` | Hahahaha! |
| `[kıkırdama]` | Kıkırdama | `[kıkırdar]` `[giggles]` `[giggle]` `[hihi]` `[chuckles]` `[chuckle]` `[kıs kıs güler]` | Hihihi! |
| `[iç çekme]` | İç çekme | `[iç çeker]` `[sighs]` `[sigh]` | Ahh... |
| `[hmm]` | Hmm | `[hm]` `[düşünür]` `[thinks]` | Hmm... |
| `[of]` | Of | `[off]` `[pff]` `[pf]` `[pöf]` `[puflar]` | Off... |
| `[nefes verir]` | Nefes verme | `[nefes verme]` `[exhales]` | Hoff... |
| `[öksürür]` | Öksürük | `[öksürük]` `[coughs]` `[cough]` | Öhö öhö. |
| `[boğaz temizler]` | Boğaz temizleme | `[boğazını temizler]` `[clears throat]` `[ehem]` | Ehem. |
| `[esner]` | Esneme | `[esneme]` `[yawns]` | Aaah... |
| `[ağlar]` | Ağlama | `[ağlıyor]` `[ağlama]` `[cries]` `[sobs]` | Hıh hıh... |
| `[şaşırır]` | Şaşırma | `[vay canına]` `[vay]` `[wow]` `[gasps]` `[gasp]` `[hah]` `[nefesi kesilir]` | Vay canına! |
| `[hıh]` | Hı hı (onay) | `[hı hı]` `[hıhı]` `[ıhı]` `[onay]` `[uh huh]` | Hıh. |
| `[mmm]` | Mmm | `[mm]` `[lezzet]` `[yum]` | Mmm... |
| `[cık]` | Cık cık | `[cık cık]` | Cık cık. |

**Yalnızca okunan tepkiler** (kaydedilemez)

| Okunuş | Etiketler |
|---|---|
| Iıı... | `[ıı]` `[ee]` `[dolgu]` `[um]` `[uh]` |
| Şey... | `[şey]` |
| Hmm hmm hmm. | `[mırıldanır]` `[hums]` `[hum]` |
| Evet, evet. | `[evet evet]` |
| Tüh! · Aman! · Ay! · Oh... · Yok ya! | `[tüh]` · `[aman]` · `[ay]` · `[oh]` · `[yok ya]` |
| Hişt! · Pişt! | `[hişt]` · `[pişt]` |
| Fiiüüt! | `[ıslık]` `[ıslık çalar]` `[whistles]` |
| Ohh... | `[inler]` `[inleme]` `[groans]` `[groan]` |
| Hık! | `[hıçkırır]` |
| Sniff. | `[burnunu çeker]` `[sniffs]` `[sniff]` |

- Tekrarlı yazımlar da tanınır: `[hahahaha]` → gülme, `[hihihi]` → kıkırdama, `[hmmm]` → hmm, `[offf]` → of.
- Sözsüz etiket metni o noktada böler. Kayıt yoksa etiketi cümle **sonuna** yazın (`Bunu duyunca çok güldüm. [gülme]`):
  ünlem önceki cümleyle birlikte üretilir. Satırın başındaki etiket tek başına üretilir ve daha yapay duyulabilir.
- Hangi tepkinin gerçek kayıttan çalındığı sonuçta "Kullanılan tepkiler" satırında (`params.nonverbal_used`) görünür.
- Kayıt yoksa etiketin **kendi** okunuşu seslendirilir: `[hı hı]` → "Hı hı.", `[vay]` → "Vay!", `[gülme]` → "Hahaha!".

## 10. Duraklamalar

**Sabit duraklamalar**

| Süre | Etiketler |
|---|---|
| 0,35 sn | `[kısa duraklama]` `[kısa ara]` `[short pause]` |
| 0,5 sn | `[nefes]` `[nefes alır]` `[breath]` `[takes a breath]` |
| 0,7 sn | `[derin nefes]` `[deep breath]` |
| 0,8 sn | `[duraklama]` `[pause]` `[...]` |
| 1,5 sn | `[uzun duraklama]` `[long pause]` |
| 2 sn | `[sessizlik]` `[silence]` |

**Sayılı duraklama:** Süreyi kendiniz yazın; en fazla 10 sn.

| Yazım | Süre |
|---|---|
| `[1.5 sn]` · `[1,5 sn]` · `[1.5 saniye]` | 1,5 sn |
| `[500 ms]` · `[500 milisaniye]` | 0,5 sn |
| `[2 saniye]` · `[2 s]` · `[2 sec]` | 2 sn |
| `[duraklama: 1 sn]` · `[pause 2s]` · `[bekle 3 sn]` | 1 sn · 2 sn · 3 sn |

Birimler: `ms`, `msn`, `milisaniye`, `sn`, `s`, `saniye`, `sec`, `second(s)`. Etiket duraklamaları ölçeklenmeden,
birebir eklenir; art arda yazılanlar toplanır (bir noktada en çok 10 sn). `[nefes]` yalnızca ara açar; nefes sesleri
"Nefes" ayarı (`breaths`) açıkken uygun aralara kendiliğinden yerleştirilir.

```
Ve kazanan… [2 sn] Ayşe! [kısa duraklama] Tebrikler.
```

## 11. Noktalamanın etkisi

| İşaret | Ton (noktalamaya göre duygu açıkken) | Ardından temel duraklama |
|---|---|---|
| `.` | — | ~0,38 sn |
| `!` | Vurgu artar, sadakat biraz düşer: daha enerjik | ~0,42 sn |
| `?` | Soru tonu, vurgu biraz artar | ~0,45 sn |
| `...` ya da `…` | Düşünceli, vurgu azalır | ~0,55 sn |
| Satır sonu / boş satır | Paragraf sonu | ~0,65 sn |
| `,` `;` `:` | Cümle içi duraklamayı model kendisi verir; çok uzun cümle bu işaretlerden bölünürse kısa ara | 0,18–0,3 sn |
| `—` (uzun tire), `( )` | Kısa duraklamaya çevrilir | — |

- Temel süreler sonra **bağlama göre** ayarlanır: sonraki cümle bağlaçla başlıyorsa ("ama", "çünkü", "yani"…) %35
  kısalır; sorudan sonra kısa bir cevap geliyorsa %20 kısalır; çok uzun cümleden sonra %15 uzar; kısa cümleden sonra
  çabuk devam edilir; iki duraklama birebir aynı olmasın diye ±%12 oynatılır. Sonuç 0,06–2,5 sn arasında tutulur.
- Ardından duygunun çarpanı (bölüm 2–3), istekteki ya da stildeki **Duraklama** (`pause_scale`) ve sesin kayıttan
  ölçülen kişisel ritmi (`pauses.scale`) uygulanır.
- `!!!` → `!`, `??` → `?`, `?!` → `?` olarak sadeleştirilir; tekrar etkiyi artırmaz. Emojiler okunmaz.
- **Haber** stilinde "noktalamaya göre duygu" kapalıdır: `!` ve `?` tonu daha az etkiler.
- Tamamı büyük harfle yazılmış cümleler ("ARTIK YETER!") harf harf okunmaz; otomatik duygu açıksa kızgın ya da
  heyecanlı tona iter. Kısa büyük harfli sözcükler kısaltma sayılıp harf harf okunabilir ("ABD" → "a be de").

## 12. Diyalog biçimleri

**Diyalog** sekmesinde (API'de `speakers` gönderilince) her satır konuşmacısının sesiyle üretilir. **Seslendir**
sekmesinde "Ayşe:" önekleri düz metin olarak okunur.

| Biçim | Örnek | Not |
|---|---|---|
| `Ad: metin` | `Ayşe: Selam, naber?` | Satır başında; ayraçtan sonra boşluk ve metin gelmeli (`Ayşe:Selam` ad sayılmaz) |
| `Ad — metin` · `Ad - metin` | `MEHMET — İyiyim, sen?` | Uzun tire (— –) ya da iki yanı boşluklu kısa tire |
| `[ses:Ad] metin` | `[ses:Mehmet] Hadi! [ses:Ayşe] Sonra.` | Satır ortasında da yeni sıra başlatır; `[konuşmacı:Ad]`, `[speaker:Ad]`, `[voice:Ad]`, `[ses: Ad]` |
| `Ad (yönerge): metin` | `Ayşe (fısıldayarak): Gel buraya.` | Yönerge sıranın başına etiket olur: `[fısıldayarak] Gel buraya.`; ad yanında en çok 3; çözülemeyen ("kapıyı açar") atılır |
| `Ad [etiket]: metin` | `Ayşe [heyecanlı]: Kazandık!` | Etiket olduğu gibi sıraya geçer |
| `(yönerge)` | `(sessizlik)` · `Ayşe: (güler) Selam!` | Tek başına satır ya da sıra başı; etiketse uygulanır, değilse okunmaz |
| Adsız satır | `Akşam olmuş, kafe kalabalık.` | Metnin başındaysa **anlatıcı**; sonra önceki konuşmacının devamı |

**Konuşmacı adı:** 1–3 sözcük, en çok 40 karakter, büyük harfle başlar ("Dr. Ayşe Yılmaz"); küçük harfli hitaplar
olur ("Ali bey", "Fatma teyze", "Hasan usta", "Ayşe abla"). Rakam içeren ad olmaz. Büyük/küçük harf aynı kişidir
(`AYŞE` = `Ayşe`; ilk yazım korunur); daha önce geçen ad küçük harfle de yazılabilir (`ayşe:`).

**Anlatıcı:** Metnin başındaki adsız satırları anlatıcı okur; sesi `narrator_voice_id` (arayüzde "Anlatıcı" satırı),
verilmezse `voice_id`, o da yoksa modelin varsayılan sesidir. Bir konuşmacı konuştuktan sonra adsız satır o
konuşmacının devamıdır; anlatıcıya dönmek için satırı `Anlatıcı:` ile başlatın. Diyalog sekmesi `Anlatıcı:` ve
`Anlatan:` satırlarını anlatıcı sesine bağlar; API'de bunlar sıradan konuşmacı adıdır (`speakers` içinde onlara da
ses verin).

**Başlık istisnaları** (ad sayılmaz, satır önceki konuşmacının metni olarak okunur): `Not`, `Örnek`, `Dikkat`,
`Uyarı`, `Soru`, `Cevap`, `Özet`, `Başlık`, `Konu`, `Tarih`, `Saat`, `Adres`, `Telefon`, `Fiyat`, `Önemli`, `Sonuç`,
`Kaynak`, `Açıklama`, `İpucu`, `Adım` (çoğulları da: `Notlar:`); ayrıca söylem sözcükleri (`Yani:`, `Mesela:`…),
belge/senaryo başlıkları (`Bölüm:`, `Sahne:`, `Madde:`…), iletişim alanları (`Tel:`, `E-posta:`…), ünlemler
(`Hey:`, `Aman:`…), `Saat 12:30:` ve `1. Bölüm:` gibi rakamlı satırlar ve adresler (`https://…`). Röportaj için
`Soru:`/`Cevap:` yerine `Muhabir:`/`Konuk:` yazın.

**Sıra alma:** Her dolu satır en az bir ayrı sıradır. Sıralar arası temel duraklama: aynı konuşmacı devam ederse
450 ms; konuşmacı değişince 260 ms (sorudan sonra 200, ünlemden sonra 230, "..." sonrası 520; önceki sıra 6 sn'den
uzunsa +80); ±%15 oynatılır, 120–1500 ms arasında tutulur; ardından bağlam ve **Duraklama** ayarı uygulanır. Her
konuşmacının kendi gerçek tepki kayıtları ve telaffuz sözlüğü kullanılır.

```
Akşam olmuş, kafede iki eski arkadaş karşılaşır.
Ayşe: [heyecanlı] Mehmet? Sen misin? Yıllar oldu!
Mehmet: [gülme] Ayşe! Hiç değişmemişsin.
Ayşe (fısıldayarak): Sana bir sır vereyim mi?
[ses:Mehmet] [çok şaşkın] Ne sırrı? [ses:Ayşe] Sonra anlatırım.
```

**Yönergeler ve notlar**

- Parantezli yönergeler etikete çevrilir: `(gülerek)` → `[güler]`, `(bağırarak)` → `[kızgın]`, `(heyecanla)` →
  `[heyecanlı]`, `(alaycı bir sesle)` → `[alaycı]`, `(fısıldayarak)` → fısıltı. Doğrudan etiket adı olan yönergeler
  olduğu gibi kalır (`(biraz üzgün)` yoğunluğu korur, `(2 sn)` duraklamadır). Çözülemeyen sahne notu (`(kapıyı açar)`)
  atılır.
- İstekteki `emotion` ve stilin varsayılan duygusu diyalogda uygulanmaz; konuşmacı başına varsayılan duygu için
  arayüzdeki "varsayılan duygu" seçimini ya da API'de `speaker_emotions` kullanın. Sıra bir **duygu** etiketiyle
  başlıyorsa eklenmez; `[gülme]` ya da `[2 sn]` ile başlayan sıraya yine eklenir.
- `Anlatıcı:`, `Anlatan:`, `Dış ses:` önekleri konuşmacı değil anlatıcıdır (anlatıcı sesiyle okunur, `is_dialog`
  sayımına girmez).
- Yalnızca duraklama içeren sıra (`Mehmet: [2 sn]`) sessiz bir bekleyiş olarak önceki sıranın sonuna eklenir.
- Sesi seçilmemiş konuşmacı modelin varsayılan sesiyle okunur.

## 13. Stil ön ayarları

Stil, bir kullanım için ayar setidir. İstekte `style` verildiğinde, istekte **verilmeyen** alanlar stilden gelir;
verdiğiniz alanlar stilin değerini ezer (arayüzde bir ayarı değiştirince stil "özelleştirilmiş" görünür). Stil adı
etiketinden ya da eş anlamlısından da bulunur (`"Sesli Kitap"`, `"sesli_kitap"`, `"audiobook"`, `"egitim"`). Tüm
stillerde nefes açıktır. Sesler sekmesinde bir sese varsayılan stil atanabilir; arayüz o sesi seçince stili de seçer.

| Stil | Ne için | Duygu | Vurgu | Sadakat | Sıcaklık | Hız | Duraklama | Konuşma dili | Noktalama duygusu | Otomatik duygu | Eş anlamlılar (örnek) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `sohbet` | Varsayılan: doğal, samimi, konuşur gibi. | — | 0,55 | 0,45 | 0,8 | 1 | 1 | light | açık | kapalı | `conversational`, `chat`, `casual`, `youtube` |
| `anlatıcı` | Hikâye ve sesli anlatım için ölçülü, akıcı bir anlatıcı sesi. | — | 0,45 | 0,5 | 0,75 | 0,97 | 1,2 | off | açık | kapalı | `narrator`, `narration`, `storyteller`, `anlatım` |
| `haber` | Haber spikeri gibi net, tarafsız ve tempolu okuma. | — | 0,4 | 0,55 | 0,7 | 1 | 0,9 | off | kapalı | kapalı | `news`, `newscaster`, `anchor`, `spiker` |
| `reklam` | Enerjik tanıtım ve kampanya seslendirmesi. | `heyecanlı` | 0,8 | 0,35 | 0,9 | 1,04 | 0,8 | light | açık | kapalı | `ad`, `ads`, `advert`, `advertisement` |
| `masal` | Çocuklara masal okur gibi sıcak, yavaş ve canlı. | `samimi` | 0,65 | 0,4 | 0,85 | 0,93 | 1,35 | off | açık | kapalı | `fairy tale`, `fairytale`, `bedtime story`, `çocuk masalı` |
| `podcast` | Rahat, sohbet havasında uzun konuşma. | — | 0,5 | 0,45 | 0,8 | 0,98 | 1,1 | full | açık | kapalı | `podkast`, `radyo`, `radio`, `talk show` |
| `belgesel` | Ciddi, derin ve ağırbaşlı belgesel anlatımı. | `ciddi` | 0,4 | 0,55 | 0,7 | 0,95 | 1,3 | off | açık | kapalı | `documentary`, `docu`, `doku`, `belgesel anlatımı` |
| `eğitim` | Ders anlatır gibi açık, sabırlı ve anlaşılır. | — | 0,45 | 0,5 | 0,75 | 0,96 | 1,15 | light | açık | kapalı | `education`, `educational`, `ders`, `lesson` |
| `sesli-kitap` | Uzun metinleri yormadan, dengeli ve tutarlı okur. | — | 0,4 | 0,5 | 0,7 | 0,95 | 1,25 | off | açık | kapalı | `audiobook`, `audio book`, `kitap`, `book` |
| `duygusal` | Dramatik ve duygu yüklü; duyguyu cümle içeriğinden kendisi seçer. | — | 0,75 | 0,35 | 0,9 | 0,95 | 1,3 | light | açık | açık | `emotional`, `dramatic`, `dramatik`, `drama` |
| `müşteri-hizmeti` | Nazik ve yardımsever; çağrı merkezi ve karşılama mesajları için. | `nazik` | 0,45 | 0,5 | 0,8 | 0,98 | 1,05 | off | açık | kapalı | `support`, `customer support`, `customer service`, `müşteri hizmetleri` |
| `spor-spikeri` | Maç anlatır gibi heyecanlı ve hızlı. | `heyecanlı` | 0,85 | 0,3 | 0,95 | 1,08 | 0,7 | light | açık | kapalı | `sports`, `sport`, `sports commentator`, `commentator` |

Stilin **duygusu**, metinde etiket olmayan bölümlere uygulanır (diyalogda uygulanmaz); metindeki etiketler her
zaman önceliklidir. **Konuşma dili** seviyeleri: `off` metne dokunmaz; `light` "geleceğim → gelicem", "bir şey →
bişey", "ne yapacaksın → napıcaksın" gibi güvenli kısaltmaları yapar; `full` bunlara ek olarak "geliyorum →
geliyom", "böyle → böle", "değil → diil" der. Özel adlara, kısaltmalara ve yabancı sözcüklere dokunulmaz.
**Konuşma dolguları** (`fillers`) haber, belgesel, sesli kitap, eğitim, müşteri hizmeti ve anlatıcı stillerinde
eklenmez.

## 14. Örnek metinler

Aşağıdaki "Okunuş" satırları, normalizasyon ve konuşma dili katmanının modele verdiği metinden kesitlerdir.

**Sohbet** — stil `sohbet`

```
[samimi] Selam millet, hoş geldiniz! Bugün size bu hafta denediğim üç uygulamayı anlatacağım.
[hmm] Açıkçası ilk başta pek emin değildim... [gülme] ama sonuç beni bayağı şaşırttı.
Hadi bakalım, ilkiyle başlayalım!
```

Okunuş: "… denediğim üç uygulamayı **anlatıcam**." (konuşma dili `light`)

**Reklam** — stil `reklam`

```
Yaz indirimi başladı! Tüm ürünlerde %50'ye varan fırsatlar sizi bekliyor.
[vurgu] Üstelik kargo bedava! [kısa duraklama] Kampanya yalnızca 3 gün sürecek.
Kulaklıklar 499 TL yerine *sadece* 299 TL! [mutlu] Hemen şimdi sipariş verin!
```

Okunuş: "… **yüzde elliye** varan fırsatlar …", "… yalnızca **üç** gün **sürücek**.", "Kulaklıklar **dört yüz doksan
dokuz lira** yerine sadece **iki yüz doksan dokuz lira**!" Etiketsiz bölümler stilin duygusuyla (`heyecanlı`) okunur.

**Masal** — stil `masal`

```
[sakin] Bir varmış, bir yokmuş. Ormanın kıyısında, yaşlı bir çınarın altında minik bir kirpi yaşarmış. [1.5 sn]
[fısıltı] Bir gece, yapraklar arasından tuhaf bir hışırtı gelmiş. [korkmuş] Kirpi hemen top gibi büzülmüş: "Kim var orada?"
[çocuksu] "Korkma, benim! Yolunu kaybeden küçük tavşan!" [uzun duraklama]
[mutlu] O geceden sonra ikisi hiç ayrılmamışlar. [nostaljik: Hâlâ o çınarın altında oturup yıldızları sayarlarmış.]
```

**Haber** — stil `haber`

```
[ciddi] İyi akşamlar, ana haber bültenine hoş geldiniz.
İstanbul'da sabah saatlerinde başlayan sağanak yağış, 14:30 itibarıyla etkisini yitirdi.
[duraklama] TBMM Genel Kurulu'nda bugün yeni vergi düzenlemesi görüşüldü; düzenleme 01.01.2027'de yürürlüğe girecek.
[duraklama] Merkez Bankası politika faizini %45'te sabit tuttu.
```

Okunuş: "… **on dört otuz** itibarıyla …", "**te be me me** Genel Kurulu'nda …", "… **bir ocak iki bin yirmi yedide**
yürürlüğe girecek.", "… faizini **yüzde kırk beşte** sabit tuttu." Haber stilinde konuşma dili kapalıdır.

**Duygu yoğunluğu, geçiş ve gerçek tepki** — stil `duygusal`

```
[biraz üzgün] Sonuçlar açıklandığında kimse konuşmadı. [üzgün+umutlu] Yine de içimden bir ses bitmediğini söylüyordu.
[hız:0.9] Sonra telefon çaldı. [hız] [aşırı şaşkın] Kazanmışız! Bunu duyunca kahkahayı bastım. [kahkaha]
[sakinleşerek] Saatlerce sevindik, ağladık, birbirimize sarıldık.
Gece ilerledikçe ev sessizleşti; çay demlendi, herkes kendi köşesine çekildi.
Ve ilk kez, uzun zamandır ilk kez, gerçekten rahat bir uyku uyuduk.
```

Sesin `[kahkaha]` kaydı varsa kendi kahkahanız çalınır, yoksa "Hahahaha!" okunur. Satır sonu paragraf sonu sayılır;
cümleyi iki satıra bölmeyin.

## 15. Pratik öneriler

- **Gerçek gülme için kayıt alın.** Model gülmeyi gerçekten üretemez; kaydı olmayan `[gülme]` "Hahaha!" diye okunur.
  En çok kullandığınız 3–4 tepkiyi (gülme, kıkırdama, iç çekme, hmm) kaydetmek en büyük farkı yaratır.
- **Cümle başına bir duygu.** Tek cümlenin duygusunu değiştirmek için kapsamlı etiket kullanın: `[şaşkın: Gerçekten mi?]`.
  Çok sık duygu değişimi metni küçük parçalara böler; geçişlerde ton kırılabilir.
- **Önce yoğunluk, sonra yeni duygu.** "Biraz daha üzgün" için yeni etiket yerine `[üzgün:3]` ya da `[çok üzgün]` deneyin.
- **Duyguyu metne de yazın.** "Bu harika!" gibi duygu taşıyan sözcükler ve noktalama, etiketten çok iş görür.
- **Sayıları, tarihleri ve kısaltmaları olduğu gibi yazın;** normalizasyon okur ("12,50 TL", "14:30", "KDV").
  Yanlış okunan bir marka ya da ad için **Telaffuz** sekmesine ekleyin ya da `{Yazılış|okunuş}` kullanın.
- **Bağırmayı büyük harfle değil,** `[kızgın]`, `[çok kızgın]` ya da `!` ile verin; tek sözcük için `*sözcük*`.
- **Uzun boşluk için** çok sayıda nokta yerine `[duraklama]` ya da `[2 sn]` yazın.
- **Etiket çalışmadı mı?** Yazımı kontrol edin (tanınmayan etiket sessizce atlanır) ve üretim ayrıntılarındaki
  "Cümle cümle" listesine bakın.
