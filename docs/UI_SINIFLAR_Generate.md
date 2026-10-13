# Generate.jsx — CSS sınıf istekleri

Bu sınıfları `frontend/src/components/Generate.jsx` kullanıyor ama `styles.css` içinde henüz yoklar.
CSS sahibi ajan ekleyecek; önerilen kurallar aşağıda (mevcut değişkenlerle: `--accent`, `--accent-2`, `--line`,
`--bg-2`, `--muted`, `--text`, `--ok`). Sınıflar eklenmeden de ekran kullanılabilir durumda (geri dönüş notları
her maddede). Generate.jsx satır içi stil olarak yalnızca ilerleme çubuğunun genişliğini kullanır (`.progress .bar`).

| Sınıf | Nerede | Amaç |
|---|---|---|
| `.stack.tight` | stil satırı + açıklama, metin bloğu, üret çubuğu | `.stack` ama sık aralık |
| `.style-chips` | en üstteki stil ön ayarları (`role="toolbar"`) | **yatay kaydırılabilir** chip satırı |
| `.chip.customized` | seçili stil chip'i, kullanıcı bir değeri değiştirince | "özelleştirilmiş" görünümü |
| `.panel`, `.panel-body` | "Doğallık" ve "İnce ayar" (`<details>`) | katlanabilir bölüm kutusu |
| `.checklist` | Doğallık içindeki onay kutuları | dikey, sık liste |
| `.warn-text` | zayıf kayıt uyarısı, karakter sınırına yaklaşınca sayaç | uyarı (amber) rengi |
| `.voice-info` | ses seçiminin altındaki kalite satırları | sık satırlar |
| `.num-sm` | "Sayılı duraklama" sayı girişi | dar sayı kutusu |
| `.partial-list` | sağ sütundaki "Hazır olan parçalar" listesi | yükseklik sınırı + kaydırma |
| `.item.playing` | sıralı dinlemede çalan parça | vurgulu kenar |
| `.variant-tabs` | A/B/C/D varyant sekmeleri (`role="tablist"`, chip'ler) | sekme görünümü |

## Önerilen kurallar

```css
/* Sık yığın */
.stack.tight { gap: 6px; }

/* Stil ön ayarları: tek satır, yatay kaydırma (geri dönüş: .presets gibi alt satıra sarar) */
.style-chips { flex-wrap: nowrap; overflow-x: auto; overscroll-behavior-x: contain; scroll-snap-type: x proximity;
  padding: 2px 2px 6px; scrollbar-width: thin; -webkit-overflow-scrolling: touch; }
.style-chips .chip { flex: 0 0 auto; white-space: nowrap; scroll-snap-align: start; }

/* Seçili ama özelleştirilmiş stil (her zaman .active ile birlikte gelir) */
.chip.active.customized { background: transparent; color: var(--accent); border: 1px dashed var(--accent); }

/* Klavye odağı (chip/sekme/özet) — genel erişilebilirlik */
.chip:focus-visible, .btn:focus-visible, .panel > summary:focus-visible {
  outline: 2px solid var(--accent-2); outline-offset: 2px; }

/* Katlanabilir bölümler (<details class="panel">); geri dönüş: tarayıcının varsayılan üçgeni */
.panel { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; background: var(--bg-2); }
.panel > summary { cursor: pointer; list-style: none; display: flex; align-items: baseline; gap: 6px; user-select: none; }
.panel > summary::-webkit-details-marker { display: none; }
.panel > summary::before { content: '▸'; color: var(--muted); display: inline-block; transition: transform .15s; }
.panel[open] > summary::before { transform: rotate(90deg); }
.panel-body { margin-top: 12px; }

/* Onay kutusu listesi */
.checklist { display: flex; flex-direction: column; gap: 8px; }

/* Uyarı rengi */
.warn-text { color: #f59e0b; }

/* Ses kalite satırları */
.voice-info { display: flex; flex-direction: column; gap: 2px; margin-top: -4px; }

/* Sayılı duraklama girişi (label.inline içinde) */
.num-sm { width: 76px; padding: 6px 8px; }

/* Canlı önizleme listesi */
.partial-list { max-height: 360px; overflow-y: auto; padding-right: 4px; }
.item.playing { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }

/* Varyant sekmeleri (A/B/C/D) */
.variant-tabs .chip { min-width: 44px; justify-content: center; text-align: center; font-weight: 700; }
```

## Not (Player sahibine)

Generate, Player'ı şu prop'larla çağırır: `src`, `downloadName`, `autoPlay`, `title` (varyant sekmesinde
"Varyant B", parça listesinde "Parça 3") ve `compact` (canlı önizlemedeki küçük oynatıcılar). Sıralı dinleme
başlarken `stopAllPlayers()` çağrılır; herhangi bir Player çalınca (`playerBus` "play") sıralı dinleme durur.
İkisi de yoksa Generate sessizce kendi yedeğine düşer.
