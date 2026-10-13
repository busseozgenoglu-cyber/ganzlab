# Voices / Convert / AnalysisCard — CSS sınıfları

Kapsam: `frontend/src/components/Voices.jsx`, `Convert.jsx`, `AnalysisCard.jsx` (paylaşılan) ve `useRecorder.js`.
Aşağıdaki sınıfların neredeyse tamamı `styles.css` içinde **zaten tanımlı** (CSS sahibi işaretlemeye göre ekledi);
"Durum" sütunu bunu gösterir. Yalnızca en alttaki küçük, isteğe bağlı eklemeler kaldı.

## Satır içi stil (yalnızca veriye bağlı değerler)

| Nerede | Ne | Değer |
|---|---|---|
| `svg.score-ring` ikinci `<circle>` | `stroke` özniteliği | puan rengi: ≥85 `#22c55e`, ≥70 `#84cc16`, ≥50 `#f97316`, <50 `#ef4444` |
| `.chip.qbadge` | `border-color`, `background` (`#RRGGBB22`), yıldızın `color`'ı; metin `var(--text)` | puan rengi |
| `.chip.metric` (sorunlu ölçüm) | `color` + `border-color` | `var(--err)` / `var(--warn)` (sunucunun `issues` koduna göre) |
| `.issue > .ico` | `color` | `var(--err)` / `var(--warn)` / `var(--info)` |
| `svg.meter` dolgu `<rect>` | `fill`, `width` | yeşil `#22c55e` · sarı `#eab308` (tepe > 0.7) · kırmızı `#ef4444` (tepe > 0.9, kırpılma riski) |
| `.progress .bar`, `.progress.coverage .bar` | `width` | iş ilerlemesi / duygu kapsaması yüzdesi |

## Sınıflar

| Sınıf | Nerede | Amaç | Durum |
|---|---|---|---|
| `.analysis` (+ `.stack`) | AnalysisCard kapsayıcısı | kart | ✓ |
| `.analysis.compact` | Convert kaynak analizi, kısa kart | sık aralık | ✓ |
| `.analysis.loading` | "Kayıt inceleniyor…" (+ `.spinner`) | yükleniyor satırı | ✓ |
| `.analysis.empty` (+ `.row`) | "Analiz yok" + "Analiz et" | `.empty` süsünü ezer | ✓ |
| `.analysis-head` (+ `.row`), `.analysis-grade` | halka + derece + puan | ortalı satır | ✓ |
| `svg.score-ring`, `.score-ring-value` | puan halkası (SVG) | geçiş animasyonu | ✓ |
| `.chip.metric` | ölçüm rozetleri (`title` = açıklama) | `cursor: help` | ✓ |
| `.chip.metric.warn`, `.chip.metric.bad` | sorunlu ölçüm (⚠ / ⛔ önekli) | ton kancası | isteğe bağlı |
| `ul.issues > li.issue.error\|warn\|info > span.ico` | sorun listesi (⛔ ⚠ ℹ) | `:has(> .ico)` kendi simgesi | ✓ |
| `div.tips > div.muted + ul > li` | "Öneriler" | liste | ✓ |
| `.chip.qbadge` (+ `.small`) | ★ 84 — ses kartı başlığı, örnek satırları | kalın, tabular rakam | ✓ |
| `.recorder` (+ `.stack`) | mikrofon kaydı bloğu | sık aralık | ✓ |
| `.rec-live` (+ `.stack`) | geri sayım/kayıt sırasında canlı panel | kutu | ✓ |
| `.countdown` | "Hazırlanın… **3**" | genel hap biçimi | ✓ |
| `.meter-wrap`, `svg.meter` | canlı seviye çubuğu + ipucu | blok SVG | ✓ |
| `.rec-timer`, `.rec-dot` (+ `.danger-text`) | "● Kaydediliyor: 12 sn / 30 sn · yeterli ✓" | yanıp sönen nokta | ✓ |
| `.warn-text`, `.danger-text` | seviye ipucu (yüksek / kırpılma) | renk | ✓ |
| `.script` (+ `.stack`) | okuma metni seçici (Sohbet/Anlatım/Haber) | kanca; stil gerekmez | — |
| `.alert.warn` | "Bu kayıt zayıf görünüyor…" | uyarı kutusu | ✓ |
| `.library-head` (+ `.row.between`) | kütüphane başlığı + "İçe aktar (zip)" | başlık hizası | ✓ |
| `.empty-guide`, `ol.steps` | "Henüz ses yok" + 3 adım | rehber kutusu | ✓ |
| `.progress.coverage` | "5/21 duygu kaydı" | kapsama çubuğu | ✓ |
| `.voice-settings` (+ `.row`), `label.inline` | varsayılan stil + not | ayırıcı çizgi | ✓ |
| `.sample-editor` (+ `.stack`) | seçili duygu için metin + kayıt | iç kutu | ✓ |
| `.voice-tools` (+ `.row`) | Adı değiştir · Yedekle (zip) · Sil | sık düğmeler | ✓ |
| `.item.voice` | ses kartı `<li>` | kanca; stil gerekmez | — |

Convert.jsx yalnızca mevcut sınıfları kullanır (`.progress` + `.bar`, `.chip.on`, `.presets`, `.chip.clickable`)
ve kayıt/analiz için yukarıdaki `Recorder` ile `AnalysisCard`'ı paylaşır.

## İsteğe bağlı küçük eklemeler

```css
/* Geri sayım rakamı belirgin olsun */
.countdown b { font-size: 15px; color: var(--accent-2-text); }

/* Sorunlu ölçüm rozetlerine hafif zemin (renk/kenar zaten satır içi) */
.chip.metric.warn { background: var(--warn-bg); }
.chip.metric.bad { background: var(--err-bg); }

/* Devre dışı chip düğmeleri (Convert kısayolu dönüşüm sürerken) */
.chip.clickable:disabled { opacity: .55; cursor: not-allowed; }
```
