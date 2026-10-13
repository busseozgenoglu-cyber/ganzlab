# Etiketler, noktalama ve stiller

Metnin nasıl seslendirileceğini üç şey belirler: metnin içine yazdığınız **etiketler**, **noktalama** ve seçtiğiniz
**stil**. Bu sayfa hepsinin tam listesidir. Etiketlerin kısa özeti için: [README → Stiller ve etiketler](../README.md#stiller-ve-etiketler).

## 1. Etiket yazımı

| Tür | Yazım | Etki |
|---|---|---|
| Duygu (sürekli) | `[üzgün] Metin…` | Bir sonraki duygu etiketine kadar geçerlidir |
| Duygu (kapsamlı) | `[heyecanlı: Yalnızca bu cümle.]` | Yalnızca köşeli parantezin içine uygulanır; sonra önceki duyguya dönülür |
| Sıfırlama | `[normal]` | Duyguyu kaldırır |
| Sözsüz | `[gülme]`, `[iç çekme]` | En yakın ünleme çevrilip cümlenin içinde seslendirilir ("Hahaha!") |
| Duraklama | `[duraklama]`, `[1.5 sn]` | O noktada ara verir |
| Vurgu | `*sözcük*`, `[vurgu] sözcük`, `[vurgu: kısa öbek]` | İşaretlenen sözcük ya da öbek vurgulanır; yıldızlar ve etiket okunmaz |

Kurallar:

- Büyük/küçük harf ve Türkçe karakter fark etmez: `[HEYECANLI]`, `[heyecanli]`, `[Heyecanlı]` aynıdır.
- Her etiketin Türkçe ve İngilizce eş anlamlıları vardır; ElevenLabs tarzı `[excited]`, `[whispers]`, `[laughs]`,
  `[sighs]` de çalışır.
- Tanınmayan etiket sessizce yok sayılır. Köşeli parantez içindeki tanınmayan ifadeler (ör. `[not: burayı düzelt]`)
  seslendirilmez.
- Kapsamlı etiketin adı en fazla 30 karakter olabilir; içerik herhangi bir uzunlukta olabilir.
- Satır başında "Heyecanlı: …" biçimi etiket sayılmaz (diyalog metinleriyle karışmasın diye); köşeli parantez kullanın.
- Duygu ve duraklama etiketleri metni o noktada ayrı parçalara böler; her parça ayrı üretilir. Bu yüzden etiketleri
  mümkünse cümle başlarına ya da cümle aralarına koyun.
- Üretim sonucunun ayrıntılarında (`params.chunks`) her parça için uygulanan duygu, referans ve duraklama görünür;
  bir etiketin çalışıp çalışmadığını buradan anlayabilirsiniz.

## 2. Duygu etiketleri

**Vurgu** (`exaggeration`), **Sadakat** (`cfg_weight`) ve **Sıcaklık** (`temperature`) sütunları, o etiketli bölüm
üretilirken kullanılan değerlerdir; "—" olanlarda istekteki ya da stildeki değer geçerlidir. **Duraklama ×** cümle
arası duraklamaların çarpanıdır. Noktalamanın etkisi (bölüm 5) bunların üstüne eklenir ve motor değerleri güvenli bir
aralıkta tutar.

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

- `[hızlı]` tempoyu ×1,12, `[yavaş]` ×0,9 yapar. Diğer duyguların küçük tempo, perde ve şiddet farkları yalnızca
  "Ses işleme seviyesi" (`emotion_fx`) **hafif** ya da **tam** iken uygulanır; varsayılan **kapalı** en doğal sonucu verir.
- `[vurgulu]` bir duygudur ve bölümün tamamını etkiler; tek bir sözcüğü vurgulamak için `*sözcük*` ya da `[vurgu]` kullanın.
- Duyguyu en çok, o duygu için aldığınız **duygu kaydı** taşır ([Kayıt rehberi → Duygu kayıtları](KAYIT_REHBERI.md#7-duygu-kayıtları)).
- "İçerikten otomatik duygu" (`auto_emotion`) açıksa etiketsiz cümlelerin duygusu sözcüklerden ("harika", "maalesef",
  "yeter artık"…), olumsuzluktan ("hiç güzel değil"), noktalamadan ve büyük harf oranından tahmin edilir.

## 3. Sözsüz etiketler

Model gülme, iç çekme, ağlama gibi sesleri gerçekten üretemez. Bu etiketler aşağıdaki ünlemlere çevrilir ve cümlenin
akışı içinde seslendirilir (tek başına üretilen ünlemler modelde bozulmaya yol açıyor). `[hahahaha]`, `[hihihi]`
gibi tekrarlı yazımlar da tanınır.

| Okunuş | Etiketler |
|---|---|
| Hahaha! | `[gülme]` `[güler]` `[gülüyor]` `[gülüş]` `[laughs]` `[laugh]` `[laughing]` `[hahaha]` |
| Haha! | `[haha]` |
| Hahahaha! | `[kahkaha]` `[kahkaha atar]` `[kahkahalar]` `[laughs hard]` |
| Hihihi! | `[kıkırdama]` `[kıkırdar]` `[giggles]` `[giggle]` |
| Hihi! | `[hihi]` |
| Heh heh. | `[chuckles]` `[chuckle]` `[kıs kıs güler]` |
| Ahh... | `[iç çekme]` `[iç çeker]` `[sighs]` `[sigh]` |
| Hoff... | `[nefes verir]` `[nefes verme]` `[exhales]` |
| Off... | `[of]` `[off]` |
| Pöf... | `[pff]` `[pf]` `[pöf]` `[puflar]` |
| Hmm... | `[hmm]` `[hm]` `[düşünür]` `[thinks]` |
| Iıı... | `[ıı]` `[ee]` `[dolgu]` `[um]` `[uh]` |
| Şey... | `[şey]` |
| Hı hı. | `[hı hı]` `[hıhı]` `[ıhı]` `[onay]` `[uh huh]` |
| Mmm... | `[mmm]` `[mm]` `[lezzet]` `[yum]` |
| Hmm hmm hmm. | `[hums]` `[hum]` `[mırıldanır]` |
| Evet, evet. | `[evet evet]` |
| Cık cık. | `[cık]` `[cık cık]` |
| Vay canına! | `[şaşırır]` `[vay canına]` |
| Vay! | `[wow]` `[vay]` |
| Hah! | `[gasps]` `[gasp]` `[hah]` `[nefesi kesilir]` |
| Tüh! | `[tüh]` |
| Aman! | `[aman]` |
| Ay! | `[ay]` |
| Oh... | `[oh]` |
| Hıh. | `[hıh]` |
| Yok ya! | `[yok ya]` |
| Hişt! | `[hişt]` |
| Pişt! | `[pişt]` |
| Fiiüüt! | `[ıslık]` `[ıslık çalar]` `[whistles]` |
| Ohh... | `[groans]` `[groan]` `[inler]` `[inleme]` |
| Hıh hıh... | `[ağlar]` `[ağlıyor]` `[ağlama]` `[cries]` `[sobs]` |
| Hık! | `[hıçkırır]` |
| Sniff. | `[sniffs]` `[sniff]` `[burnunu çeker]` |
| Öhö öhö. | `[öksürür]` `[öksürük]` `[coughs]` `[cough]` |
| Ehem. | `[boğaz temizler]` `[boğazını temizler]` `[clears throat]` `[ehem]` |
| Aaah... | `[esner]` `[esneme]` `[yawns]` |

## 4. Duraklama etiketleri

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

Birimler: `ms`, `msn`, `milisaniye`, `sn`, `s`, `saniye`, `sec`, `second(s)`. Art arda yazılan duraklamalar toplanır.
`[nefes]` yalnızca ara açar; nefes sesleri "Nefes" ayarı (`breaths`) açıkken uygun aralara kendiliğinden yerleştirilir.

## 5. Noktalamanın etkisi

| İşaret | Ton (noktalamaya göre duygu açıkken) | Ardından temel duraklama |
|---|---|---|
| `.` | — | ~0,38 sn |
| `!` | Vurgu artar, sadakat biraz düşer: daha enerjik | ~0,42 sn |
| `?` | Soru tonu, vurgu biraz artar | ~0,45 sn |
| `...` ya da `…` | Düşünceli, vurgu azalır | ~0,55 sn |
| Satır sonu / boş satır | Paragraf sonu | ~0,65 sn |
| `,` `;` `:` | Cümle içi duraklamayı model kendisi verir; çok uzun cümle bu işaretlerden bölünürse kısa ara | 0,18–0,3 sn |
| `—` (uzun tire), `( )` | Kısa duraklamaya çevrilir | — |

- Temel süreler sonra **bağlama göre** ayarlanır: sonraki cümle bağlaçla başlıyorsa ("ama", "çünkü", "yani", "hatta"…)
  %35 kısalır; sorudan sonra kısa bir cevap geliyorsa %20 kısalır; çok uzun cümleden sonra %15 uzar; kısa cümleden
  sonra çabuk devam edilir; hiçbir iki duraklama birebir aynı olmasın diye ±%12 oynatılır. Sonuç 0,06–2,5 sn arasında
  tutulur.
- Ardından duygunun çarpanı (bölüm 2), istekteki ya da stildeki **Duraklama** (`pause_scale`) ve sesin kayıttan
  ölçülen kişisel ritmi (`pauses.scale`) uygulanır.
- `!!!` → `!`, `??` → `?`, `?!` → `?` olarak sadeleştirilir; tekrar etkiyi artırmaz. Emojiler okunmaz.
- **Haber** stilinde "noktalamaya göre duygu" kapalıdır: `!` ve `?` tonu daha az etkiler, okuma tarafsız kalır.
- Tamamı büyük harfle yazılmış cümleler ("ARTIK YETER!") harf harf okunmaz; otomatik duygu açıksa kızgın ya da
  heyecanlı tona iter. Kısa büyük harfli sözcükler ise kısaltma sayılıp harf harf okunabilir ("ABD" → "a be de").

## 6. Stil ön ayarları

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

Stilin **duygusu**, metinde etiket olmayan bölümlere uygulanır; metindeki etiketler her zaman önceliklidir.
**Konuşma dili** seviyeleri: `off` metne dokunmaz; `light` "geleceğim → gelicem", "bir şey → bişey", "ne yapacaksın →
napıcaksın" gibi güvenli kısaltmaları yapar; `full` bunlara ek olarak "geliyorum → geliyom", "böyle → böle",
"değil → diil" der. Özel adlara, kısaltmalara ve yabancı sözcüklere dokunulmaz.

## 7. Örnek metinler

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
yürürlüğe girecek.", "… faizini **yüzde kırk beşte** sabit tuttu." Haber stilinde konuşma dili kapalıdır; "girecek"
olduğu gibi okunur.

## 8. İpuçları

- **Model gülmeyi gerçekten üretemez;** `[gülme]` "Hahaha!" olarak seslendirilir. Az kullanın: `[kıkırdama]` çoğu zaman
  `[kahkaha]`dan doğal durur, gülümseyen bir ton için `[mutlu]` ya da `[samimi]` genellikle yeterlidir. Gerçek bir
  gülme gerekiyorsa kendi gülmenizi kaydedip montajda ekleyin.
- **Cümle başına bir duygu.** Tek bir cümlenin duygusunu değiştirmek için kapsamlı etiket kullanın:
  `[şaşkın: Gerçekten mi?]`. Çok sık duygu değişimi metni küçük parçalara böler ve geçişlerde ton kırılabilir.
- **Duyguyu metne de yazın.** "Bu harika!" gibi duygu taşıyan sözcükler ve noktalama, etiketten daha çok iş görür.
- **Sayıları, tarihleri ve kısaltmaları olduğu gibi yazın;** normalizasyon okur ("12,50 TL", "14:30", "KDV"). Yanlış
  okunan bir marka ya da ad için `DATA_DIR/pronunciations.json` dosyasına `{"Yazılış": "okunuş"}` ekleyin
  (Docker'da `/data/pronunciations.json`); dosya değişince yeniden başlatma gerekmez.
- **Bağırmayı büyük harfle değil,** `[kızgın]`, `[vurgulu]` ya da `!` ile verin; tek sözcük vurgusu için `*sözcük*`.
- **Uzun boşluk için** çok sayıda nokta yerine `[duraklama]` ya da `[2 sn]` yazın.
- **Etiket çalışmadı mı?** Yazımı kontrol edin (tanınmayan etiket sessizce atlanır) ve üretim ayrıntılarındaki parça
  listesine bakın.
