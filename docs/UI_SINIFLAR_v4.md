# v4 arayüzü — CSS sınıfları (Generate · Voices · Lexicon)

Kapsam: `frontend/src/components/Generate.jsx`, `Voices.jsx`, `Lexicon.jsx` (yeni "Telaffuz" sekmesi) ve
`AnalysisCard.jsx` (`ScoreRing` artık dışa açık). Bu dosyalarda **yeni satır içi stil yok**; her şey mevcut
sınıflarla çalışır. Aşağıdaki "yeni" sınıfların çoğu yalnızca kancadır; CSS eklenmese de ekran düzgün görünür.

## 1. styles.css'te zaten olan v4 sınıfları (işaretleme bunlara uyduruldu)

| Sınıf | Nerede |
|---|---|
| `.row.subtitle-bar` | Sonuçta "Altyazı: ⤓ SRT · ⤓ VTT · ⤓ JSON · Önizle" satırı |
| `pre.subtitle-preview` | Altyazı önizlemesi (SRT/VTT/JSON chip'leriyle biçim değişir) |
| `table.lex-table`, `tr.lex-row` | Telaffuz tablosu (son hücre sağa yaslı düğmeler) |
| `.lex-test` (+ `.quote`, `mark`) | "Dene" sonucu: modelin okuyacağı metin, değişen okunuşlar `<mark>` |

Not: `table.lex-table th` kuralı (yapışkan, soluk, 12 px) tüm `th`'lere uyduğu için satır başlığı `th` yerine
`td.lex-word` kullanıldı. Yalnızca `thead th` hedeflenirse sözcük hücresi yeniden `th scope="row"` yapılabilir.

## 2. Yeniden kullanılan mevcut sınıflar

- **Generate — etiket kutusu:** `.tagbox`, `.taggroup` (başlık `<b>` + `.muted` açıklama), `.presets`,
  `.chip.clickable` (gerçek kaydı olan sözsüz etiket: `.chip.on` + "✓"), `.num-sm`, `label.inline`, `.actions`.
- **Generate — Doğallık:** `.checklist` + `label.check` (devre dışı dolgu seçeneği mevcut `:disabled` kuralıyla).
- **Generate — sonuç:** `.stack.tight` rapor satırları (`.small` + `<b>`), `.warn-text` (⚠ düşük puan), `details.chunks`,
  `.item.small`, `.tag.emo`, `.alert.error`, `.spinner`.
- **Voices — iyileştirme:** `.alert.ok` / `.alert.info` kutu, `.row.analysis-head` + `svg.score-ring` (önce/sonra
  halkaları), `.badge.ok|warn` (+12 puan), `.chip.small` (uygulanan adımlar), `.btn.primary.small` (önerildiğinde belirgin
  düğme) / `.btn.ghost.small` (ikincil).
- **Voices — gerçek tepkiler:** `.samplebox`, `.sample-editor`, `.quote` (yönerge), `.chip.clickable.on|active`,
  `.tag.vc` (tepki adı), `.player.compact`, `.list` / `.item.small`.
- **Lexicon:** `.grid.two`, `.card`, `.toolbar` + `.search`, `.row` form, `.badge` / `.badge.accent` (genel / bu ses),
  `.empty`, `.alert.warn|error`, `.count`, `ul.tips > li.tip`, `.sr-only` (tablo başlığı ve "İşlemler").

## 3. Yeni sınıflar

| Sınıf | Nerede | Gerekli mi |
|---|---|---|
| `.table-wrap` | `table.lex-table` sarmalayıcısı | **Önerilir** — dar ekranda yatay kaydırma |
| `.qc-reasons` | "Cümle cümle" listesinde kalite kontrol nedenleri (`ul`) | Önerilir — tarayıcı girintisi büyük |
| `.item.qc-low` | Düşük puanlı (<60) parça | İsteğe bağlı vurgu |
| `tr.lex-row.inherited` | Ses kapsamında genel sözlükten gelen satır | İsteğe bağlı (soluk) |
| `.enhance-bar` | Ses kartında "✨ Kaydı iyileştir" + öneri nedeni (`.row`) | İsteğe bağlı hiza |
| `.enhance-result`, `.enhance-compare` | İyileştirme sonucu kutusu / halka satırı | Kanca |
| `.tag-control` | Etiket kutusunda sayı girişi + "+ [hız:0.9]" (`.actions`) | Kanca |
| `.gen-report` | Kalite kontrol · Tutarlılık · Kullanılan tepkiler satırları | Kanca |
| `.nv-samples` | "Gerçek tepkiler" bölümü (`.samplebox`) | Kanca |
| `.lexicon`, `.lex-toolbar`, `.lex-new`, `.lex-word`, `.lex-reading`, `.lex-actions` | Telaffuz sekmesi parçaları | Kanca |

## 4. Önerilen kurallar

```css
/* Telaffuz tablosu: dar ekranda yatay kaydırma */
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }
.lex-word .badge { margin-left: 4px; padding: 1px 7px; font-size: 11px; }
tr.lex-row.inherited td { color: var(--text-2); }
tr.lex-row.inherited .lex-word b { font-weight: 600; }

/* Kalite kontrol nedenleri ve düşük puanlı parça */
.qc-reasons { margin: 2px 0 0; padding-left: 18px; display: flex; flex-direction: column; gap: 2px; }
.item.qc-low { border-color: var(--warn); background: var(--warn-bg); }

/* İyileştirme çubuğu: düğme ile açıklama ortada hizalı */
.enhance-bar { align-items: center; }
.enhance-compare { gap: 10px; }

/* Etiket kutusundaki sayı girişleri biraz daha dar */
.tag-control .num-sm { width: 70px; }
```

## 5. Davranış notları (CSS sahibine)

- Vurgu / Okunuş / Yoğunluk chip'leri `onMouseDown` ile odağı metin kutusunda tutar; `:focus-visible` yalnızca klavyeyle gelir.
- Ses kartındaki oynatıcı, iyileştirme ya da geri alma sonrası `?v=…` ekli adresle yeniden yüklenir (Player önbelleği).
