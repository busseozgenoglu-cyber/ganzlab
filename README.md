# SesKlon

Kendi bilgisayarınızda çalışan, Türkçe'ye özel ses klonlama ve metin seslendirme (TTS) uygulaması. 10–15 saniyelik
bir kayıttan sesinizi klonlar; metni duygu etiketleri, stil ön ayarları ve doğal konuşma ritmiyle seslendirir; çok
konuşmacılı diyalogları her karakterin kendi sesiyle, gülmeyi de sizin gerçek gülmenizle üretir.

- **Yerel:** Metinleriniz, kayıtlarınız ve üretimleriniz bilgisayarınızda kalır, hiçbir sunucuya gönderilmez. İnternet
  yalnızca kurulumda ve modelin ilk indirilmesinde (~2 GB, Hugging Face) gerekir. (Arayüz yalnızca yazı tipini
  Google Fonts'tan ister; bağlantı yoksa sistem yazı tipi kullanılır.)
- **Ücretsiz ve açık kaynak:** SesKlon MIT lisanslıdır. Model: [Chatterbox Multilingual V3](https://github.com/resemble-ai/chatterbox)
  (Resemble AI, MIT, Türkçe dahil 23 dil).
- **Türkçe'ye özel:** Türkçe metin normalizasyonu, konuşma dili katmanı, telaffuz sözlüğü, sohbet kısaltmaları,
  Türkçe bağlaçlara göre duraklama, Türkçe kayıt analizi ve arayüz.

> **Sürüm 4.0 — "Diyalog":** çok konuşmacılı diyalog, kendi kaydınızla gerçek tepkiler (gülme, iç çekme…), duygu
> yoğunluğu, karışım ve geçişi, satır içi hız/perde kontrolleri, kalite kontrol, tutarlılık, altyazı, telaffuz sözlüğü
> ve kayıt iyileştirme. v3 istekleri değişmeden çalışır (yeni alanların hepsi isteğe bağlı). Ayrıntılar ve yükseltme
> notları: [CHANGELOG](CHANGELOG.md#400--2026-10-13).

ElevenLabs gibi bulut hizmetlerine yerel bir alternatif olarak tasarlandı: benzer etiket mantığı (`[heyecanlı]`,
`[fısıltı]`, `[gülme]`…), diyalog, ses kütüphanesi, geçmiş ve HTTP API'si var. Fark, her şeyin sizin donanımınızda
çalışması: hız GPU'nuza, kalite büyük ölçüde referans kaydınıza bağlıdır.

> PyPI'daki `chatterbox-tts` paketi V2 ağırlıklarını kullanır; SesKlon V3 için GitHub kaynağından kurar.

**İçindekiler:** [Neler var](#neler-var) · [Neden doğal?](#neden-doğal) · [Donanım](#donanım) ·
[Hızlı başlangıç](#hızlı-başlangıç) · [İlk diyalog](#kurulumdan-sonra-ilk-diyalog) · [Ses ekleme](#ses-ekleme-ilk-adımlar) ·
[Stiller ve etiketler](#stiller-ve-etiketler) · [Ortam değişkenleri](#ortam-değişkenleri) · [API](#api) ·
[Sorun giderme](#sorun-giderme) · [Sorumluluk](#sorumluluk-ve-izin) · [Lisans](#lisans)

## Neler var

Sekmeler: **Seslendir · Diyalog · Sesler · Telaffuz · Dönüştür · Geçmiş**

- Sıfır-shot ses klonlama (10–15 sn kayıt), tarayıcıdan mikrofonla kayıt, ses → ses dönüştürme
- **Diyalog modu:** "Ayşe: …" satırları her konuşmacının kendi sesiyle, anlatıcıyla ve doğal sıra alma
  duraklamalarıyla; sıra sıra dinleme
- **Gerçek tepkiler:** 15 tepki (gülme, kahkaha, kıkırdama, iç çekme, hmm, öksürük…) için kendi kaydınız;
  `[gülme]` yazınca modelin "Hahaha"sı yerine sizin gülmeniz çalınır
- Duygu etiketleri (Türkçe ve İngilizce adlarla) ve **duygu yoğunluğu** (`[heyecanlı:3]`, `[çok kızgın]`),
  **karışım** (`[üzgün+umutlu]`), **geçiş** (`[heyecanlı→sakin]`); ses başına duygu kayıtları; 12 stil ön ayarı
- **Satır içi kontroller:** `[hız:0.9]`, `[perde:+1]`, diyalogda `[ses:Ad]`; vurgu (`*sözcük*`), sözsüz etiketler,
  sabit ve sayılı duraklamalar (`[1.5 sn]`)
- **Telaffuz sözlüğü** (genel ve ses başına, "Dene" önizlemesiyle) ve satır içi okunuş `{Claude|Klod}`;
  **sohbet kısaltmaları** (slm, tmm, nbr…) ve isteğe bağlı **konuşma dolguları** (yani, hani, işte)
- **Kalite kontrol** (tekrar, takılma, yarıda kesilme, vızıltı → yeniden üretim) ve **tutarlılık** (parçalar arası
  tını ve seviye eşitleme)
- **Altyazı:** SRT, VTT, JSON (API'de ayrıca LRC); sözcük zamanlı zaman çizelgesi
- Kayıt analizi (0–100 kalite puanı, Türkçe sorun açıklamaları ve öneriler) ve **kaydı iyileştirme** (gürültü,
  uğultu, tık; geri alınabilir)
- Varyant üretimi (A/B/C/D), canlı önizleme (parçalar hazır oldukça dinleme), iş iptali
- Geçmişte arama, tür süzgeci ve favoriler; dalga formlu oynatıcı; MP3/WAV
- Ses yedekleme (duygu ve tepki kayıtlarıyla zip), koyu/açık/sistem teması
- İsteğe bağlı API anahtarı, Swagger belgesi, Docker (GPU/CPU), Windows/Linux/macOS betikleri

```
sesklon/
├─ backend/app/   main.py (API) · engine.py (üretim) · textnorm.py (normalizasyon) · colloquial.py (konuşma dili)
│                 lexicon.py (telaffuz sözlüğü, okunuş, kısaltmalar, dolgular) · emotion.py · styles.py
│                 dialog.py (diyalog) · nonverbal.py (gerçek tepkiler) · qc.py (kalite kontrol)
│                 consistency.py (tutarlılık) · timing.py (altyazı) · enhance.py (kayıt iyileştirme)
│                 prosody.py (duraklama/nefes/mastering) · analysis.py (kayıt analizi) · audio.py
│                 jobs.py (iş kuyruğu) · db.py (SQLite) · tr.py (Türkçe yardımcılar)
├─ backend/tests/ pytest paketi (sahte motorla uçtan uca; GPU/model gerekmez)
├─ frontend/      React + Vite arayüz
├─ docs/          KAYIT_REHBERI · ETIKETLER · API · SSS · SOZLESME, SOZLESME2 (geliştirici sözleşmeleri)
└─ Dockerfile · docker-compose.yml (GPU) · docker-compose.cpu.yml · run.sh (Linux/macOS) · run.ps1 (Windows)
```

## Neden doğal?

Sesi "insan gibi" duyuran şey yalnızca model değil; modelin önündeki ve arkasındaki katmanlardır (v4 ile gelenler
işaretli):

| Katman | Ne yapar |
|---|---|
| Türkçe normalizasyon | Para (kuruşuyla), saat, tarih, telefon, IBAN, Roma rakamı, matematik, birim ve 150+ marka adını bir Türk'ün okuyacağı biçime çevirir; kısaltmaları harf harf okur ("ABD" → "a be de"). |
| Telaffuz sözlüğü (v4) | Marka ve adların okunuşunu bir kez yazarsınız ("Shopify" → "Şopifay"), her metinde uygulanır; genel ya da yalnız bir ses için. Tek seferlik okunuş: `{Claude\|Klod}`. |
| Sohbet kısaltmaları (v4) | "slm, tmm, yrn grs" gibi mesajlaşma dilini "selam, tamam, yarın görüşürüz" diye okur; "TSK" gibi kurum kısaltmalarına dokunmaz. |
| Konuşma dili | Yazı dilini isteğe göre konuşma diline çevirir: hafif seviyede "geleceğim → gelicem", tam seviyede ayrıca "geliyorum → geliyom", "böyle → böle". |
| Konuşma dolguları (v4) | İsteğe bağlı, seyrek "yani", "hani", "işte": hazırlıksız konuşma havası. Haber, sesli kitap gibi stillerde eklenmez. |
| Bağlama göre duraklama | Cümle aralarını noktalamaya, bağlaçlara ("ama", "çünkü"…), soru-cevap ritmine ve cümle uzunluğuna göre ayarlar; iki duraklama birebir aynı olmaz. |
| Nefes | Uzun konuşmalarda ve paragraf başlarında nefes ekler; mümkünse kaydınızdan çıkarılan gerçek nefesinizi kullanır. |
| Oda tonu | Duraklamaları dijital sessizlik yerine kaydınızdaki ortam sesiyle doldurur, böylece konuşma aralarında "boşluğa düşme" hissi olmaz. |
| Gerçek tepkiler (v4) | `[gülme]`, `[iç çekme]`, `[hmm]` gibi etiketlerde modelin yapay ünlemi yerine sizin kaydınız çalınır; konuşmanın seviyesine oturtulur ve her seferinde hafif farklıdır. |
| Duygu katmanları | Her duygu için varsa kendi kaydınızı referans alır; duyguya ve noktalamaya (`!` `?` `...`) göre vurgu, tempo ve duraklamayı ayarlar. |
| Yoğunluk, karışım, geçiş (v4) | Duygunun şiddetini (`[heyecanlı:3]`, `[biraz üzgün]`), iki duygunun harmanını (`[üzgün+umutlu]`) ve bölüm boyunca bir duygudan ötekine kayışı (`[heyecanlı→sakin]`, `[sakinleşerek]`) yazarsınız. |
| Satır içi kontroller (v4) | `[hız:0.9]` ve `[perde:+1]` cümlenin yalnızca bir bölümünün temposunu ve perdesini değiştirir; `*vurgu*` sözcüğü gerçekten öne çıkarır. |
| Diyalog (v4) | Her konuşmacı kendi sesi, duygu ve tepki kayıtlarıyla konuşur; konuşmacı değişiminde, sorudan sonra ve "..." sonrası farklı sıra alma duraklamaları. |
| Kalite kontrol (v4) | Tekrar eden, takılan, yarıda kesilen ya da vızıltılı parçayı yakalar; farklı tohumla ya da daha kararlı ayarlarla yeniden üretir, fazla sessizliği kırpar. |
| Tutarlılık (v4) | Parça parça üretilen uzun metinde tınıyı referans sese yaklaştırır (±3 dB) ve seviye sıçramalarını yumuşatır; duygu farkını silmez. |
| Mastering | Çıktıyı yayın seviyesine (−16 LUFS, en fazla −1,5 dBTP) getirir, hafif EQ ve sibilans (s/ş) yumuşatma uygular. |
| Referans analizi | Kaydınızı 0–100 puanlar, sorunları Türkçe açıklar ve ölçtüğü kişisel duraklama ritminizi üretime otomatik uygular. |
| Kayıt iyileştirme (v4) | Gürültü, elektrik uğultusu, tık ve DC kaymasını ölçülü temizler; puan en az 3 artmazsa uygulamaz, geri alınabilir. |
| Altyazı (v4) | Sesle örtüşen zaman çizelgesi; SRT, VTT, JSON ve LRC; diyalogda konuşmacı değişimleri ayrı satırda. |
| Stil ön ayarları | Sohbet, haber, masal, reklam gibi 12 kullanım için tutarlı ayar setleri sunar. |
| Varyantlar | Aynı metni farklı tohumlarla 2–4 kez üretir; en iyisini seçip tohumunu sabitleyerek aynı sonucu yeniden alabilirsiniz. |

## Donanım

| Cihaz | Durum |
|---|---|
| NVIDIA GPU (≥ 6 GB VRAM) | Önerilen — 10 sn ses ≈ 2–5 sn |
| Apple Silicon | Çalışır (`DEVICE=mps`) |
| Yalnızca CPU | Çalışır ama yavaş (10 sn ses ≈ 1–3 dk) |

Disk: en az 10 GB boş alan (PyTorch, GPU kurulumunda CUDA kütüphaneleri ve ~2 GB model). Bellek: en az 8 GB RAM
(CPU'da 16 GB önerilir). Kalite kontrol bozuk bir parçayı yeniden ürettiğinde o parçanın süresi 2–3 katına çıkabilir.

## Hızlı başlangıç

Üç yol var; hepsinde arayüz **http://localhost:8000** adresinde açılır. İlk açılışta model (~2 GB) indirilir ve arka
planda yüklenir; üst çubukta "model hazır" görününce üretime başlayabilirsiniz.

### 1. Docker + NVIDIA GPU (önerilen)

- **Linux:** Docker Engine ve [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- **Windows:** Docker Desktop (WSL 2 altyapısı) ve güncel NVIDIA sürücüsü; ek kurulum gerekmez.

```bash
git clone <depo-adresi> sesklon && cd sesklon
docker compose up -d --build
docker compose logs -f            # kurulum ve model indirme ilerlemesi
```

GPU'nun konteynerde görüldüğünü doğrulamak için:
`docker compose exec sesklon python -c "import torch; print(torch.cuda.is_available())"` → `True`.

### 2. Docker, yalnız CPU

NVIDIA GPU yoksa (macOS'taki Docker da GPU kullanamaz):

```bash
docker compose -f docker-compose.cpu.yml up -d --build
```

Bu imaj PyTorch'un CPU sürümüyle kurulur; CUDA kütüphaneleri inmediği için GPU imajından birkaç GB küçüktür. Veri
birimi (`sesklon-data`) GPU kurulumuyla ortaktır; aralarında geçişte sesler ve geçmiş korunur.

| İş | Komut (CPU kurulumunda `-f docker-compose.cpu.yml` ekleyin) |
|---|---|
| Durdur | `docker compose down` (veriler korunur) |
| Güncelle | `git pull && docker compose up -d --build` |
| Günlükler | `docker compose logs -f` |
| Her şeyi sil | `docker compose down -v` (sesler ve geçmiş dahil; geri alınamaz) |

### 3. Docker'sız (Windows, Linux, macOS)

Gereksinimler: Python 3.11 (3.10–3.13 çalışır), Node.js 18+ (güncel LTS önerilir), ffmpeg, git.

```bash
./run.sh                                              # Linux / macOS
```

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1    # Windows (PowerShell)
```

Eksik araçlar için:

| | Windows (winget) | macOS (Homebrew) | Ubuntu / Debian |
|---|---|---|---|
| Python | `winget install Python.Python.3.11` | `brew install python@3.11` | `sudo apt install python3 python3-venv` |
| Node.js | `winget install OpenJS.NodeJS.LTS` | `brew install node` | [nodejs.org](https://nodejs.org) ya da `nvm install --lts` |
| ffmpeg | `winget install Gyan.FFmpeg` | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| git | `winget install Git.Git` | `xcode-select --install` | `sudo apt install git` |

Betik şunları yapar: araçları denetler (eksikse Türkçe hata ve kurulum komutu verir), `.venv` sanal ortamını oluşturur,
Python paketlerini yalnızca ilk seferde ya da `requirements.txt` değişince kurar (PyTorch dahil birkaç GB, 5–15 dk),
arayüzü kaynakları değiştiyse yeniden derler, `.env` dosyasını okur ve sunucuyu başlatır. Sonraki açılışlar hızlıdır
ve internet gerektirmez.

- **Windows + NVIDIA:** `nvidia-smi` bulunursa PyTorch CUDA 12.4 sürümüyle kurulur (PyPI'daki Windows PyTorch'u yalnız
  CPU'dur). İstemiyorsanız: `$env:TORCH_INDEX='https://download.pytorch.org/whl/cpu'; .\run.ps1`
- **GPU'suz Linux:** `TORCH_INDEX=https://download.pytorch.org/whl/cpu ./run.sh` CUDA kütüphanelerini indirmez.
- Model önbelleği Docker'sız çalıştırmada `~/.cache/huggingface` altındadır (Windows: `%USERPROFILE%\.cache\huggingface`).

### Kurulumdan sonra: ilk diyalog

Kurulum bitince **Diyalog** sekmesini açın ve senaryoyu satır satır yazın (ya da hazır örneklerden birini yükleyin):

```
Akşam olmuş, kafede iki eski arkadaş karşılaşır.
Ayşe: [heyecanlı] Mehmet? Sen misin? Yıllar oldu!
Mehmet: [gülme] Ayşe! Hiç değişmemişsin.
Ayşe (fısıldayarak): Sana bir sır vereyim mi?
Mehmet: [çok şaşkın] Ne sırrı?
```

Her konuşmacıya **Sesler** sekmesine eklediğiniz seslerden birini seçin ("Otomatik eşle" de olur). İlk satır gibi adsız
satırları **Anlatıcı** okur; sesi seçilmeyen konuşmacı modelin varsayılan sesiyle konuşur. **▶ Diyaloğu seslendir**
(Ctrl+Enter): sonuçta sıra sıra dinleme, kalite kontrol özeti ve altyazı indirme gelir. Seslerin gerçek tepki kaydı
varsa `[gülme]` yerine kendi gülmeleri çalınır. Biçimler: [Etiketler → Diyalog](docs/ETIKETLER.md#12-diyalog-biçimleri) ·
API: [Diyalog](docs/API.md#diyalog).

### Ayarlar

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

`.env` dosyasını Docker Compose ve iki betik de okur; değişkenler [aşağıda](#ortam-değişkenleri).

### Geliştirme

```bash
./run.sh --dev            # Windows: .\run.ps1 -Dev
```

API `uvicorn --reload` ile :8000'de, arayüz Vite ile :5173'te çalışır; **http://localhost:5173** adresini açın, kod
değişiklikleri anında yansır. Testler model ve GPU gerektirmez (sahte motorla çalışır):

```bash
source .venv/bin/activate                 # Windows: .venv\Scripts\Activate.ps1
pip install -r backend/requirements-dev.txt
cd backend && pytest
```

Yalnızca testler için hafif kurulum (Chatterbox ve PyTorch olmadan; CI böyle çalışır):
`pip install -r <(grep -v chatterbox backend/requirements.txt) -r backend/requirements-dev.txt`.
GitHub Actions, `main` dalına her push'ta ve her PR'da pytest'i ve `vite build`'i çalıştırır (`.github/workflows/test.yml`).

## Ses ekleme: ilk adımlar

1. **Sesler** sekmesi → "Yeni ses ekle": ses adı ve dili.
2. Okuma metinlerinden birini seçip **Mikrofondan kaydet** ile 10–15 sn okuyun ya da hazır bir kayıt yükleyin (mp3,
   wav, m4a, ogg, webm, mp4…). İyi kayıt için: sessiz ve eşyalı oda, mikrofona 20–30 cm, videoda konuşacağınız enerji.
   Ayrıntılar: [Kayıt rehberi](docs/KAYIT_REHBERI.md).
3. Kayıt seçildiği anda **analiz** edilir: kalite puanı (0–100), derece (mükemmel / iyi / orta / zayıf), sorunlar ve
   öneriler. Puan 70'in altındaysa önerilere göre yeniden kaydetmeniz iyi olur; zayıf kayıt da kaydedilebilir ama
   gürültü, yankı ya da boğukluk klona geçer.
4. İzin kutusunu işaretleyip **Sesi kaydet**. Kayıt kırpılır, sessizlikleri temizlenir, seviyesi dengelenir ve analizi
   sesle birlikte saklanır; üretimde kaydınızdaki oda tonu, nefes ve duraklama ritmi kullanılır. Yeniden kayıt
   alamıyorsanız ses kartındaki **✨ Kaydı iyileştir** gürültüyü ve uğultuyu temizler (geri alınabilir).
5. (Önerilir) Ses kartında **Duygu kayıtları**: en çok kullanacağınız 3–4 duygu için 8–12 sn'lik kayıt ekleyin. Duygu
   etkisini en çok artıran adım budur.
6. (Önerilir) Ses kartında **Gerçek tepkiler**: gülme, kıkırdama, iç çekme, hmm gibi tepkileri 1–3 sn kaydedin; metinde
   `[gülme]` yazınca modelin "Hahaha"sı yerine bu kayıt çalınır.
7. **Seslendir** sekmesi: sesi ve bir stili seçin (ya da örnek metin yükleyin), metni yazın, **▶ Seslendir**
   (Ctrl+Enter). Parçalar hazır oldukça dinleyebilir, gerekirse iptal edebilirsiniz. 2–4 varyant isteyip en iyisini
   seçin; **Tohumu sabitle** ile aynı sonucu yeniden alabilirsiniz. Sonuçta kalite kontrol, tutarlılık ve kullanılan
   tepkiler özetlenir; altyazıyı SRT/VTT/JSON olarak indirebilirsiniz.
8. Yanlış okunan marka ya da adlar için **Telaffuz** sekmesine sözcük ve okunuşunu ekleyin; **Dene** modelin okuyacağı
   metni gösterir.
9. Ses kartındaki **Yedekle (zip)** sesi tüm duygu ve tepki kayıtları ve analizleriyle indirir; başka bir kurulumda
   **İçe aktar (zip)** ile geri yüklenir.

## Stiller ve etiketler

Stil, bir kullanım için ayar setidir (duygu, vurgu, tempo, duraklama, konuşma dili seviyesi…). İstekte ayrıca
verdiğiniz alanlar stilin değerlerini ezer.

| Stil | Ne için |
|---|---|
| `sohbet` | Varsayılan: doğal, samimi, konuşur gibi |
| `anlatıcı` | Hikâye ve sesli anlatım için ölçülü, akıcı anlatıcı |
| `haber` | Haber spikeri gibi net, tarafsız ve tempolu |
| `reklam` | Enerjik tanıtım ve kampanya seslendirmesi |
| `masal` | Çocuklara masal okur gibi sıcak, yavaş ve canlı |
| `podcast` | Rahat, sohbet havasında uzun konuşma |
| `belgesel` | Ciddi, derin ve ağırbaşlı anlatım |
| `eğitim` | Ders anlatır gibi açık, sabırlı ve anlaşılır |
| `sesli-kitap` | Uzun metinleri yormadan, dengeli ve tutarlı okuma |
| `duygusal` | Dramatik; duyguyu cümle içeriğinden kendisi seçer |
| `müşteri-hizmeti` | Nazik ve yardımsever; çağrı merkezi ve karşılama mesajları |
| `spor-spikeri` | Maç anlatır gibi heyecanlı ve hızlı |

Etiketler metnin içine köşeli parantezle yazılır. `[üzgün] …` bir sonraki duygu etiketine kadar,
`[heyecanlı: …]` yalnızca parantez içine uygulanır; `*sözcük*` tek bir sözcüğü vurgular.

| Tür | Örnekler |
|---|---|
| Duygu | `[heyecanlı]` `[mutlu]` `[sakin]` `[ciddi]` `[üzgün]` `[kızgın]` `[şaşkın]` `[korkmuş]` `[fısıltı]` `[vurgulu]` `[samimi]` `[sıkılmış]` `[alaycı]` `[nazik]` `[gururlu]` `[umutlu]` `[nostaljik]` `[gergin]` `[romantik]` `[çocuksu]` `[otoriter]` |
| Yoğunluk | `[heyecanlı:1]` … `[heyecanlı:3]` · `[biraz üzgün]` `[çok kızgın]` `[aşırı heyecanlı]` · `[kızgın %120]` |
| Karışım · geçiş | `[üzgün+umutlu]` · `[heyecanlı→sakin]` `[sakinleşerek]` `[yumuşayarak]` `[sertleşerek]` |
| Kontrol | `[hız:0.9]` `[perde:+1]` · diyalogda `[ses:Ayşe]`; `[hız]` sıfırlar |
| Tempo / sıfırlama | `[hızlı]` `[yavaş]` `[normal]` |
| Vurgu · okunuş | `*sözcük*` `[vurgu] sözcük` `[vurgu: kısa öbek]` · `{Claude\|Klod}` |
| Sözsüz | `[gülme]` `[kahkaha]` `[kıkırdama]` `[iç çekme]` `[hmm]` `[of]` `[öksürür]` `[boğaz temizler]` `[esner]` `[ağlar]` `[şaşırır]` … (15'i kaydedilebilir) · `[tüh]` `[aman]` `[şey]` … |
| Duraklama | `[kısa duraklama]` 0,35 sn · `[nefes]` 0,5 sn · `[duraklama]` 0,8 sn · `[uzun duraklama]` 1,5 sn · `[sessizlik]` 2 sn · sayılı: `[1.5 sn]`, `[500 ms]` (en fazla 10 sn) |

```
[heyecanlı:3] Selam millet! Bugün size çok güzel bir şey göstereceğim. [gülme]
[sakin] Peki nasıl çalışıyor? On saniyelik bir kayıt yüklüyorsunuz... [nefes] ve bitti.
[fısıltı] Size bir sır vereyim: artık *hiç* gerekmiyor. [1.5 sn] [şaşkın: Gerçekten mi?] Evet, gerçekten.
[samimi+mutlu] Yani {SesKlon|ses klon} ile kendi sesiniz, kendi bilgisayarınızda. Hem de Türkçe!
```

Tüm etiketler, eş anlamlılar, yoğunluk ve geçiş kuralları, diyalog biçimleri, stil parametreleri ve örnek metinler:
[docs/ETIKETLER.md](docs/ETIKETLER.md). Model gülme, iç çekme gibi sesleri gerçekten üretemez: sesin **gerçek tepki
kaydı** varsa o çalınır, yoksa etiket en yakın ünlemle ("Hahaha!") okunur.

Marka ve yabancı sözcüklerin okunuşu **Telaffuz** sekmesinden (genel ya da ses başına; `DATA_DIR/lexicon.json`) eklenir;
tek seferlik okunuş için metne `{Yazılış|okunuş}` yazın. Eski `DATA_DIR/pronunciations.json` (`{"Yazılış": "okunuş"}`;
Docker'da `/data/pronunciations.json`) da çalışmaya devam eder.

## Ortam değişkenleri

`.env` dosyasında ya da ortamda tanımlanır (bkz. [.env.example](.env.example)).

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `API_KEY` | boş | Doluysa `/api/*` için `X-API-Key` başlığı gerekir. İnternete açacaksan doldur. |
| `DEVICE` | otomatik | `cuda` / `mps` / `cpu` |
| `PRELOAD` | `1` | Modeli açılışta arka planda yükle |
| `T3_MODEL` | `v3` | Chatterbox Multilingual sürümü |
| `DATA_DIR` | `backend/data` (Docker: `/data`) | Sesler, çıktılar, SQLite, telaffuz sözlükleri (Docker'da model önbelleği de burada) |
| `MAX_TEXT_CHARS` | `5000` | Tek istekte en fazla karakter (diyalogda tüm senaryo) |
| `MAX_UPLOAD_MB` | `60` | Yükleme sınırı |
| `MAX_OUTPUTS` | `500` | Geçmişte tutulacak çıktı sayısı (0 = sınırsız) |
| `CHUNK_CHARS` | `170` | Parça boyu |
| `MAX_REF_SECONDS` | `15` | Referansın kullanılan süresi |
| `FRONTEND_DIST` | `frontend/dist` | Derlenmiş arayüz klasörü (betikler ve Docker kendisi ayarlar) |
| `HF_HOME` | `~/.cache/huggingface` (Docker: `/data/hf-cache`) | Model önbelleği (Hugging Face standardı) |

Kurulum seçenekleri (uygulama değil, kurulum içindir): `TORCH_INDEX` ve `TORCH_VERSION` — Docker'da build argümanı
(`docker-compose.cpu.yml` kullanır), Docker'sız çalıştırmada `run.sh` / `run.ps1` ortam değişkeni.

## API

Swagger: `http://localhost:8000/api/docs` · Ayrıntılı başvuru ve örnekler (curl, Python, JavaScript): [docs/API.md](docs/API.md)

| Metot | Yol | Açıklama |
|---|---|---|
| GET | `/api/health` | Cihaz, model durumu, diller, etiket ve stil kataloğu, özellikler |
| POST | `/api/warmup` | Modeli yükle |
| GET / POST | `/api/voices` | Sesler / yeni ses (`name`, `language`, `consent=true`, `file`); yanıtta `analysis` |
| GET / PATCH / DELETE | `/api/voices/{id}` | Ses ayrıntısı / ad, not, varsayılan stil / sil |
| POST · DELETE | `/api/voices/{id}/samples[/{emotion}]` | Duygu kaydı ekle / sil |
| POST · DELETE | `/api/voices/{id}/nonverbal[/{tag}]` | Gerçek tepki kaydı ekle (`tag`, `file`) / sil |
| POST | `/api/voices/{id}/enhance` · `/api/voices/{id}/enhance/undo` | Kaydı iyileştir (`force`) · geri al |
| GET | `/api/voices/{id}/analysis` | Sesin kayıt analizi |
| GET · POST | `/api/voices/{id}/export` · `/api/voices/import` | Sesi zip olarak yedekle / geri yükle |
| POST | `/api/analyze` | Kaydı saklamadan analiz et |
| POST | `/api/tts` | Metin → ses; `speakers` ile diyalog. Varsayılan **202 + iş**; `"wait": true` ile sonucu bekler |
| GET · POST | `/api/jobs/{id}` · `/api/jobs/{id}/cancel` | İş durumu, ilerleme, hazır parçalar · iptal |
| POST | `/api/vc` | Ses → ses (`voice_id`, `file`, `wait`) |
| GET · PUT · DELETE | `/api/lexicon` | Telaffuz sözlüğü: listele (`voice_id`) · ekle `{word, reading, voice_id?}` · sil (`word`, `voice_id`) |
| POST | `/api/lexicon/test` | Metnin modele nasıl gideceğini göster |
| GET · DELETE | `/api/generations[/{id}]` | Geçmiş (`limit`, `offset`, `kind`, `voice_id`, `q`, `favorite`) · sil |
| GET | `/api/generations/{id}/subtitles` | Altyazı: `format=srt\|vtt\|json\|lrc` |
| POST | `/api/generations/{id}/favorite` | Favoriye ekle / çıkar |

`POST /api/tts`'e v4'te gelen alanlar: `speakers`, `narrator_voice_id`, `speaker_emotions` (diyalog), `consistency`,
`qc`, `chat_speak`, `subtitles` (varsayılan açık), `fillers` (varsayılan kapalı). Sonuç `params` içinde `qc_reports`,
`qc_summary`, `consistency_report`, `timeline`, `turns`, `speakers`, `nonverbal_used`, `lexicon_changes`.

```bash
curl -X POST http://localhost:8000/api/tts -H "Content-Type: application/json" -d '{
  "text": "[heyecanlı:3] Merhaba İzmir! [fısıltı] Bu bir sır. [gülme]",
  "voice_id": "<ses_id>", "style": "sohbet", "format": "mp3", "wait": true }'

# Diyalog: her konuşmacı kendi sesiyle; adsız ilk satırı anlatıcı okur
curl -X POST http://localhost:8000/api/tts -H "Content-Type: application/json" -d '{
  "text": "Kafede iki arkadaş karşılaşır.\nAyşe: [heyecanlı] Selam!\nMehmet: [gülme] Sen misin?",
  "speakers": {"Ayşe": "<ses_id_1>", "Mehmet": "<ses_id_2>"}, "narrator_voice_id": "<ses_id_3>",
  "format": "mp3", "wait": true }'
```

## Sorun giderme

**GPU kullanılmıyor (üst çubukta "CPU" yazıyor)**
- Docker: host'ta `nvidia-smi` çalışmalı ve `docker run --rm --gpus all ubuntu nvidia-smi` GPU'yu göstermeli; göstermiyorsa
  NVIDIA Container Toolkit kurulu değildir. `docker-compose.cpu.yml` değil `docker-compose.yml` ile başlattığınızdan emin olun.
- Docker'sız Windows: eski bir `.venv` içinde CPU'luk PyTorch kalmış olabilir; `.venv` klasörünü silip `run.ps1`'i yeniden
  çalıştırın. Doğrulama: `.venv\Scripts\python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`
  → `2.6.0+cu124 True`.
- Linux: `.venv/bin/python -c "import torch; print(torch.cuda.is_available())"` `False` veriyorsa NVIDIA sürücüsünü
  güncelleyin (PyTorch CUDA 12 sürümüyle gelir).
- "CUDA out of memory": GPU kullanan diğer uygulamaları kapatın, varyant sayısını 1 yapın, `CHUNK_CHARS=120` deneyin;
  olmazsa `DEVICE=cpu`.

**Apple Silicon (mps)**
- macOS'taki Docker GPU'ya erişemez; Apple GPU için `./run.sh` kullanın (cihaz kendiliğinden `mps` seçilir).
- `.venv/bin/python -c "import torch; print(torch.backends.mps.is_available())"` `False` ise: macOS 12.3+ gerekir ve Python
  arm64 olmalıdır (`python3 -c "import platform; print(platform.machine())"` → `arm64`; Rosetta altındaki x86 Python MPS
  kullanamaz).
- Bir işlem MPS'te desteklenmiyorsa: `PYTORCH_ENABLE_MPS_FALLBACK=1 ./run.sh` (o işlemler CPU'da yapılır) ya da `DEVICE=cpu`.

**ffmpeg bulunamadı**
- `run.sh` / `run.ps1` ffmpeg olmadan başlamaz; Docker imajında hazırdır. ffmpeg olmadan tarayıcı kayıtları (webm) ve
  m4a okunamaz, MP3 üretilemez, hız ayarı, `[hız:…]` / `[perde:…]` kontrolleri ve mastering çalışmaz
  (`/api/health` → `"ffmpeg": false`).
- Kurulum: Windows `winget install Gyan.FFmpeg` · macOS `brew install ffmpeg` · Ubuntu/Debian `sudo apt install ffmpeg`.
  Kurduktan sonra yeni bir terminal açın (PATH güncellensin).

**Model inmedi / yüklenmiyor**
- İlk açılışta ~2 GB indirilir; arayüz "model yükleniyor" gösterir. İlerleme için günlüklere bakın
  (`docker compose logs -f` ya da betiğin çalıştığı terminal). Hata metni `/api/health` → `model_error` alanındadır.
- İnternet/vekil sunucu (`HTTPS_PROXY`) ayarlarını ve en az 5 GB boş disk alanını kontrol edin; güvenlik duvarı
  `huggingface.co` adresini engellememeli.
- Yarım kalmış indirme: önbellekteki `models--ResembleAI--*` klasörünü silip yeniden başlatın. Docker'da:
  `docker compose exec sesklon sh -c 'rm -rf /data/hf-cache/hub/models--ResembleAI--*'`
- İnternetsiz makine: modeli bağlantılı bir makinede indirip önbellek klasörünü kopyalayın, `HF_HUB_OFFLINE=1` ile başlatın.

**CPU'da çok yavaş**
- Beklenen hız 10 sn ses için 1–3 dk; ilk üretim modelin yüklenmesini de içerir (`PRELOAD=1` bunu açılışa taşır).
- Kısa metinlerle deneyin, varyant sayısını 1'de tutun, ağır uygulamaları kapatın; denemelerde kalite kontrolü
  kapatmak süreyi kısaltır. Mümkünse GPU'lu bir makine kullanın; CPU'da PyTorch'un CPU sürümü
  (`docker-compose.cpu.yml` ya da `TORCH_INDEX`) diski küçültür ama hızı değiştirmez.

**Diyalog ve altyazı**
- Satır yanlış konuşmacıya gitti: ad satır başında, büyük harfle ve ":"dan sonra boşlukla yazılmalı; "Not:", "Soru:"
  gibi başlık sözcükleri ad sayılmaz. Kurallar: [Diyalog biçimleri](docs/ETIKETLER.md#12-diyalog-biçimleri).
- Bir konuşmacı varsayılan sesle konuşuyor: Diyalog sekmesinde ona ses seçilmemiş (API'de `speakers` içinde yok).
- Altyazı indirilemiyor ("zaman çizelgesi yok"): üretim "Altyazı üret" kapalıyken yapılmış; yeniden üretin.

**Diğer**
- `401 Geçersiz API anahtarı`: arayüzde ⚙ düğmesinden anahtarı girin; API istemcilerinde `X-API-Key` başlığını gönderin.
- 8000 portu dolu: diğer uygulamayı kapatın ya da Docker'da `ports` satırını `"8080:8000"` yapın.
- Mikrofon çalışmıyor: tarayıcılar mikrofona yalnızca `https` ya da `localhost` üzerinden izin verir; başka bir cihazdan
  `http://<ip>:8000` ile açtıysanız kaydı o cihazda alıp dosya olarak yükleyin.

Daha fazlası: [Sık sorulan sorular](docs/SSS.md).

## Sorumluluk ve izin

- Yalnızca kendi sesinizi ya da sahibinden açık izin aldığınız sesleri klonlayın; arayüz ses eklerken bu onayı ister.
  Başkasının sesini izinsiz klonlamak ve kullanmak hukuki sorumluluk doğurur; ses kişisel veridir (KVKK). Bu, duygu ve
  gerçek tepki kayıtları için de geçerlidir.
- Her üretim, Resemble AI'ın algılanamaz PerTh filigranını taşır; bu, sesin yapay üretildiğinin sonradan
  doğrulanabilmesini sağlar. Kaldırmaya çalışmayın.
- Dolandırıcılık, kişi taklidi ve yanıltıcı içerik için kullanmayın; yayın platformlarının yapay içerik etiketleme
  kurallarına uyun.
- Sunucuyu internete açacaksanız `API_KEY` tanımlayın ve önüne HTTPS'li bir ters vekil koyun.

## Lisans

SesKlon [MIT](LICENSE) lisanslıdır (© 2026 SesKlon katkıda bulunanlar). Model ve motor
[Chatterbox](https://github.com/resemble-ai/chatterbox) (Resemble AI) MIT lisanslıdır; diğer bağımlılıklar kendi
lisanslarına tabidir.

**Belgeler:** [Kayıt rehberi](docs/KAYIT_REHBERI.md) · [Etiketler ve stiller](docs/ETIKETLER.md) · [API](docs/API.md) ·
[SSS](docs/SSS.md) · [Değişiklik günlüğü](CHANGELOG.md) · Modül sözleşmeleri: [v3](docs/SOZLESME.md), [v4](docs/SOZLESME2.md)
