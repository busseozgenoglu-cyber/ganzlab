import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import Player, { fmtDur } from './Player'
// Player'ın isteğe bağlı "aynı anda tek oynatıcı" yolu (playerBus / stopAllPlayers); yoksa sessizce atlanır.
import * as PlayerModule from './Player'

/*
 * Diyalog sekmesi — çok konuşmacılı senaryo seslendirme (docs/SOZLESME2.md §1, §9, §10).
 * Senaryo satır satır çözümlenir ("Ayşe: Selam!", "[ses:Mehmet] İyiyim."), her konuşmacıya bir ses ve varsayılan
 * duygu atanır; api.tts'e `speakers` + `narrator_voice_id` ile gönderilir, sunucu metni diyalog olarak işler.
 * Buradaki çözümleme yalnızca önizleme ve eşleme içindir; asıl ayrıştırma sunucudaki dialog.parse_dialog'dadır.
 */

// ─────────────────────────────────────────────────────────── sabitler ──

const STORAGE_KEY = 'sesklon_dialog_v4'
const MAP_LIMIT = 300 // hatırlanan konuşmacı eşlemesi üst sınırı (en eskiler düşer)
const PALETTE = 8 // .spk-0 … .spk-7 (styles.css)
const NARRATOR = '__anlatici__' // eşleme haritasında anlatıcının anahtarı
const UNSET = '__secilmedi__' // select: henüz ses seçilmedi
const CHARS_PER_SEC = 14 // Türkçe için kaba konuşma hızı (karakter / sn)
const TURN_GAP_S = 0.35 // sıralar arası ortalama boşluk (tahmin için)

const EXAMPLES = [
  {
    id: 'sohbet', label: 'Sohbet / komedi', style: 'sohbet',
    text: `Ayşe: [heyecanlı] Mehmet! Bil bakalım bugün kimi gördüm?
Mehmet: Hmm... Tarkan mı? [gülme]
Ayşe: [alaycı] Çok komik. Bizim eski matematik hocasını!
Mehmet: [şaşkın] Yok artık! Hâlâ o kocaman gözlükleri takıyor mu?
Ayşe: Takıyor tabii. Beni görür görmez "Türev neydi?" diye sordu. [kahkaha]
Mehmet: [hız:1.1] Kaçtın değil mi? Söyle, kaçtın!
Ayşe: [gülme] Koşarak kaçtım!`,
  },
  {
    id: 'musteri', label: 'Müşteri hizmeti', style: 'müşteri-hizmeti',
    text: `Temsilci: [nazik] SesKlon müşteri hizmetlerine hoş geldiniz, ben Elif. Size nasıl yardımcı olabilirim?
Müşteri: Merhaba. Dün verdiğim sipariş hâlâ kargoya verilmemiş görünüyor.
Temsilci: Hemen kontrol ediyorum. [kısa duraklama] Sipariş numaranızı alabilir miyim?
Müşteri: Tabii, 4 8 1 5 2.
Temsilci: [samimi] Teşekkürler. Siparişiniz bugün öğleden sonra kargoya verilecek, takip numarası kısa mesajla gelecek.
Müşteri: [mutlu] Harika, çok teşekkür ederim!
Temsilci: Rica ederim, iyi günler dileriz.`,
  },
  {
    id: 'drama', label: 'Drama', style: 'duygusal',
    text: `[sakin] Gece yarısı. Eski bir istasyonda son tren kalkmak üzere.
Zeynep: [üzgün] [hız:0.9] Gerçekten gidiyor musun?
Can: [iç çekme] Başka çarem yok, Zeynep. Orada beni bekleyen bir hayat var.
Zeynep: Peki ya burada bıraktıkların? [duraklama] Ya ben?
Can: [fısıltı] Seni hiç bırakmadım ki...
Zeynep: [kızgın] Bırakmadın mı? Üç yıl boyunca tek bir mektup bile yazmadın!
Can: [sakinleşerek] Haklısın. Ama bu sefer söz veriyorum, döneceğim.`,
  },
]

const PLACEHOLDER = `Her satıra bir konuşmacı yaz, örneğin:
Ayşe: Selam! Nasılsın?
Mehmet: [gülme] İyiyim, sen?
[ses:Ayşe] Ben de iyiyim. [üzgün] Ama yorgunum...

Konuşmacısız satırları anlatıcı okur.`

const DEFAULTS = {
  style: '', language: 'tr', colloquial: 'light', format: 'mp3',
  breaths: true, room_tone: true, master: true,
  consistency: true, qc: true, subtitles: true, fillers: false, chat_speak: true,
}
const BOOL_FIELDS = ['breaths', 'room_tone', 'master', 'consistency', 'qc', 'subtitles', 'fillers', 'chat_speak']
const DEFAULT_LEVELS = ['off', 'light', 'full']
const COLLOQUIAL_LABELS = {
  off: 'Kapalı — yazıldığı gibi',
  light: 'Hafif — gelicem, bişey',
  full: 'Tam — geliyo, diil, böle',
}
const COLLOQUIAL_SHORT = { off: 'konuşma dili kapalı', light: 'hafif konuşma dili', full: 'tam konuşma dili' }
const FORMAT_OPTIONS = [['mp3', 'MP3'], ['wav', 'WAV']]
const FALLBACK_EMOTIONS = ['heyecanlı', 'mutlu', 'sakin', 'ciddi', 'üzgün', 'kızgın', 'şaşkın', 'korkmuş', 'fısıltı',
  'vurgulu', 'samimi', 'sıkılmış', 'alaycı', 'nazik', 'gururlu', 'umutlu', 'nostaljik', 'gergin', 'romantik', 'çocuksu',
  'otoriter', 'hızlı', 'yavaş']
const DECISION_LABELS = {
  accept: 'kabul edildi',
  retry_seed: 'farklı tohumla yeniden üretildi',
  retry_stable: 'daha kararlı ayarla yeniden üretildi',
  trim: 'kırpıldı',
}

// ── Konuşmacı algılama: sunucudaki backend/app/dialog.py ile aynı kurallar (arayüz sunucunun yapacağını göstersin) ──
// Sözleşmedeki 20 başlık sözcüğü — asla konuşmacı adı değil (çoğulları da: "Notlar", "Adımlar")
const HEADER_WORDS = new Set(['not', 'örnek', 'dikkat', 'uyarı', 'soru', 'cevap', 'özet', 'başlık', 'konu', 'tarih',
  'saat', 'adres', 'telefon', 'fiyat', 'önemli', 'sonuç', 'kaynak', 'açıklama', 'ipucu', 'adım'])
// Ad olamayan sözcükler: söylem belirteçleri, belge/senaryo başlıkları, iletişim alanları, ünlemler
const NON_NAME_WORDS = new Set(`yani mesela örneğin özetle kısacası ayrıca ancak fakat ama lakin çünkü bence evet hayır
  tamam peki şimdi sonra önce hatta üstelik oysa aslında elbette tabii neyse işte bakın dinleyin şöyle bu şu ve veya ya ki
  sorun mesele durum amaç hedef öneri tavsiye bilgi duyuru haber dakika flaş güncelleme hatırlatma bölüm kısım ünite ders
  sayfa madde giriş ek tablo şekil liste malzemeler yapılışı hazırlanışı ipuçları talimat görev ödev gün hafta yıl sene
  oda kat sınıf aşama sahne perde mekan mekân zaman yer dekor müzik efekt ses tel gsm faks fax e-posta eposta mail e-mail
  email web site url www http https ftp link bağlantı ah oh of eyvah hey vay ey aman hadi haydi bravo`.split(/\s+/))
// Addan sonra küçük harfle yazılabilen hitaplar: "Ali bey:", "Fatma teyze:", "Hasan usta:"
const HONORIFICS = new Set(`bey beyefendi hanım hanımefendi abla abi ağabey amca teyze dayı hala yenge enişte efendi paşa
  ağa hoca hocam usta bacı kardeş dede nine nene`.split(/\s+/))
const SPEAKER_TAG_KEYS = new Set(['ses', 'konusmaci', 'speaker', 'voice']) // [ses:…] anahtarları (ASCII'ye indirgenmiş)
const NAME_MAX_CHARS = 40
// Sahne yönergeleri (sunucudaki resolve_directive'in arayüz yaklaşığı; yalnızca "bu yönerge sıra üretir mi" için)
const EMOTION_DIRECTIVES = new Set(['sakinleşerek', 'heyecanlanarak', 'yumuşayarak', 'sertleşerek', 'hüzünlenerek',
  'bağırarak', 'bağırır', 'haykırarak', 'sinirlenerek', 'öfkelenerek', 'gülümseyerek', 'gülümser', 'sevinerek',
  'titreyerek', 'ürkerek', 'ağlamaklı'])
const OTHER_DIRECTIVES = new Set(['hıçkırarak', 'duraksayarak', 'düşünerek', 'tereddütle'])
const INTENSIFIERS = ['çok ', 'biraz ', 'hafif ', 'hafifçe ', 'aşırı ', 'son derece ', 'oldukça ', 'gayet ']
const MANNER_SUFFIXES = [' bir ses tonuyla', ' ses tonuyla', ' bir sesle', ' sesle', ' bir tonla', ' bir şekilde',
  ' şekilde', ' bir edayla', ' bir ifadeyle', ' ifadeyle', ' bir tavırla', ' tavırla']
const FALLBACK_TAGS = ['gülme', 'güler', 'kahkaha', 'kıkırdama', 'kıkırdar', 'iç çekme', 'iç çeker', 'hmm', 'of',
  'öksürür', 'esner', 'ağlar', 'ağlama', 'şaşırır', 'nefes', 'duraklama', 'kısa duraklama', 'uzun duraklama', 'sessizlik']
// "Anlatıcı: …" satırları (sunucu için sıradan bir konuşmacı) arayüzde anlatıcı sesine bağlanır.
const NARRATOR_WORDS = new Set(['anlatıcı', 'anlatan', 'dış ses'])

const GROUP = '\\([^()\\[\\]\\n]{1,60}\\)|\\[[^()\\[\\]\\n]{1,60}\\]'
const NAME_PART = '(\\p{L}[^:()\\[\\]\\n]{0,59}?)' // ad adayı; asıl denetim validName'de
const SEP = '(?:\\s*:|\\s*[—–]|\\s+--?)'
// "Ayşe: Selam" · "Ayşe (gülerek): Selam" · "AYŞE — Selam" · "Ayşe - Selam" (en çok 3 yönerge; ayraçtan sonra boşluk + metin)
const PREFIX_RE = new RegExp(`^(\\s*)${NAME_PART}((?:\\s*(?:${GROUP})){0,3})${SEP}\\s+(?=\\S)`, 'u')
const GROUP_RE = /\(([^()[\]\n]{1,60})\)|(\[[^()[\]\n]{1,60}\])/gu
// "AYŞE:" tek başına (söz alt satırda) — sunucu bunu konuşmacı saymaz; kullanıcıyı uyarırız.
const NAME_ONLY_RE = new RegExp(`^\\s*${NAME_PART}(?:\\s*(?:${GROUP})){0,3}${SEP}\\s*$`, 'u')
// "Ayşe:Selam" — iki noktadan sonra boşluk yok (saat "12:30" ve adresler "https://" hariç)
const NO_SPACE_RE = new RegExp(`^\\s*${NAME_PART}(?:\\s*(?:${GROUP})){0,3}\\s*:(?=[^\\s\\d/])`, 'u')
const NAME_TOKEN_RE = /^[\p{L}\p{M}][\p{L}\p{M}.'’-]*$/u
// "[anahtar: değer]" — anahtarı SPEAKER_TAG_KEYS'te olanlar konuşmacı etiketidir: [ses:Mehmet], [konuşmacı: Ayşe]
const KV_TAG_RE = /\[\s*([^[\]:\n]{1,20}?)\s*:\s*([^[\]\n]{0,60}?)\s*\]/gu
const LEAD_BRACKET_RE = /^\[([^[\]\n]{0,600})\]\s*/u
const LEAD_PAREN_RE = /^\(([^()\n]{1,300})\)\s*/u
const TIMED_RE = /^\d+(?:[.,]\d+)?\s*(?:ms|milisaniye|sn|saniye|s|sec|secs|second|seconds)$/u
const TAG_RE = /\[[^\]\n]{1,60}\]/g
const ASCII_FOLD = { ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u', â: 'a', î: 'i', û: 'u' }

// ─────────────────────────────────────────────────────────── yardımcılar ──

const trLower = (s) => String(s ?? '').toLocaleLowerCase('tr')
const trUpper = (s) => String(s ?? '').toLocaleUpperCase('tr')
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
function finite(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string' && v.trim() !== '') { const n = Number(v); return Number.isFinite(n) ? n : null }
  return null
}
const isCancelledError = (err) =>
  (typeof api.isCancelled === 'function' && api.isCancelled(err)) || err?.name === 'CancelledError' || err?.cancelled === true

/** Konuşmacı karşılaştırma anahtarı: Türkçe küçük harf, tek boşluk ("AYŞE" = "Ayşe"). */
const speakerKey = (name) => trLower(String(name ?? '').replace(/[’`´]/g, "'")).replace(/\s+/g, ' ').trim()

/** Senaryo biçimindeki BÜYÜK HARF adı okunur yazar: "MEHMET ALİ" → "Mehmet Ali". */
function displayName(raw) {
  const s = String(raw ?? '').replace(/\s+/g, ' ').trim()
  if (s.length < 2 || s !== trUpper(s) || s === trLower(s)) return s
  return trLower(s).replace(/(^|[\s.'’-])(\p{L})/gu, (_, sep, ch) => sep + trUpper(ch))
}

function hashIndex(key) {
  let h = 7
  for (const ch of String(key)) h = (Math.imul(h, 31) + ch.codePointAt(0)) >>> 0
  return h % PALETTE
}

function fmtSecs(s) {
  const t = Math.max(0, Math.round(s))
  if (t < 60) return `${Math.max(1, t)} sn`
  const m = Math.floor(t / 60)
  const r = t % 60
  return r ? `${m} dk ${r} sn` : `${m} dk`
}

/** Sıra zamanı: "00:07.3" (dakika:saniye.onda bir). */
function fmtStamp(s) {
  const t = Math.round(Math.max(0, Number(s) || 0) * 10) / 10
  const m = Math.floor(t / 60)
  const sec = t - m * 60
  return `${String(m).padStart(2, '0')}:${sec.toFixed(1).padStart(4, '0')}`
}

function extOf(nameOrUrl, fallback = 'wav') {
  const m = /\.([a-z0-9]{2,4})(?:$|\?)/i.exec(nameOrUrl || '')
  return m ? m[1].toLowerCase() : fallback
}

function normColloquial(v) {
  if (v === true) return 'light'
  if (v === false || v == null || v === '') return 'off'
  return String(v)
}

// ─────────────────────────────────────────────────────────── senaryo çözümleme ──

const foldAscii = (s) => String(s).replace(/[çğıöşüâîû]/g, (c) => ASCII_FOLD[c])
const wordKey = (t) => trLower(t).replace(/^[.'’-]+|[.'’-]+$/gu, '')

function blockedWord(w) {
  return HEADER_WORDS.has(w) || NON_NAME_WORDS.has(w) || (w.length > 3 && /(?:lar|ler)$/u.test(w) && HEADER_WORDS.has(w.slice(0, -3)))
}

/** Satır başı ad adayı gerçekten konuşmacı adı mı? Daha önce görülen ad (known) küçük harfle yazılsa da kabul edilir. */
function validName(raw, known) {
  const name = String(raw ?? '').trim()
  if (!name || name.length > NAME_MAX_CHARS) return false
  const toks = name.split(/\s+/u)
  if (toks.length > 3 || !toks.every((t) => NAME_TOKEN_RE.test(t))) return false
  if (!known || !known.has(speakerKey(name))) {
    if (!/^\p{Lu}/u.test(toks[0])) return false
    if (!toks.slice(1).every((t) => /^\p{Lu}/u.test(t) || HONORIFICS.has(wordKey(t)))) return false
  }
  return !toks.some((t) => blockedWord(wordKey(t)))
}

const NARRATOR_REF = { key: NARRATOR, raw: null }

function speakerRef(raw) {
  const name = String(raw ?? '').replace(/\s+/g, ' ').trim()
  if (!name) return null
  const key = speakerKey(name)
  return { key: NARRATOR_WORDS.has(key) ? NARRATOR : key, raw: name }
}

/** Etiket kümeleri: duygular (ad, etiket, eş ad) ve sözsüz tepki / duraklama etiketleri; ASCII'ye indirgenmiş hâlleriyle. */
function buildSets(catalog) {
  const emo = new Set(['normal', ...FALLBACK_EMOTIONS])
  for (const e of catalog.emotions) for (const w of [e.name, e.label, ...(Array.isArray(e.aliases) ? e.aliases : [])]) if (w) emo.add(trLower(w).trim())
  const tags = new Set(catalog.tags.length ? catalog.tags : FALLBACK_TAGS)
  for (const s of [emo, tags]) for (const w of [...s]) s.add(foldAscii(w))
  return { emo, tags }
}

/** Köşeli parantez etiketi bir duygu mu? "[mutlu]", "[mutlu:2]", "[çok mutlu]", "[üzgün+umutlu]", "[heyecanlı→sakin]" */
function isEmotionTag(inner, emoSet) {
  let t = trLower(inner).trim()
  t = t.replace(/^(?:biraz|hafif|hafifçe|çok|aşırı|oldukça|gayet|son derece)\s+/u, '')
  t = t.split(/\s*(?:\+|→|->)\s*/u)[0]
  t = t.replace(/\s*:\s*[0-9.,]+$/u, '').trim()
  return EMOTION_DIRECTIVES.has(t) || emoSet.has(t) || emoSet.has(foldAscii(t))
}

// Sunucudaki _verb_forms / _candidates: "gülerek" → güler, gülme…; "heyecanla" → heyecanlı; "sessizce" → sessiz
function verbForms(stem) {
  const out = /[aeıioöuü]$/u.test(stem) ? [`${stem}r`] : [...'aeıiuü'].map((v) => `${stem}${v}r`)
  return [...out, `${stem}me`, `${stem}ma`, stem]
}

function candidates(k) {
  const bases = [k, ...INTENSIFIERS.filter((p) => k.startsWith(p)).map((p) => k.slice(p.length))]
  for (const b of [...bases]) for (const s of MANNER_SUFFIXES) if (b.endsWith(s) && b.length > s.length) bases.push(b.slice(0, -s.length))
  const out = [...bases]
  for (const b of bases) {
    const a = ['yarak', 'yerek', 'arak', 'erek'].find((s) => b.endsWith(s) && b.length > s.length + 1)
    if (a) out.push(...verbForms(b.slice(0, -a.length)))
    const l = ['yla', 'yle', 'la', 'le'].find((s) => b.endsWith(s) && b.length > s.length + 2)
    if (l) { const st = b.slice(0, -l.length); out.push(st, `${st}lı`, `${st}li`, `${st}lu`, `${st}lü`) }
    const c = ['ca', 'ce', 'ça', 'çe'].find((s) => b.endsWith(s) && b.length > s.length + 2)
    if (c) out.push(b.slice(0, -c.length))
  }
  return out
}

const normDirective = (s) => trLower(s).replace(/\s+/gu, ' ').replace(/^[\s.,;:!?…"'“”‘’«»—–-]+|[\s.,;:!?…"'“”‘’«»—–-]+$/gu, '')

/** "(gülerek)", "(alaycı bir sesle)" sıra üreten bir etikete çözülür mü? "(kapıyı açar)" çözülmez → sunucu atar. */
function directiveResolves(inner, sets) {
  const direct = (c) => {
    if (!c) return false
    if (EMOTION_DIRECTIVES.has(c) || OTHER_DIRECTIVES.has(c)) return true
    const f = foldAscii(c)
    return sets.tags.has(c) || sets.tags.has(f) || sets.emo.has(c) || sets.emo.has(f) || TIMED_RE.test(f)
  }
  const one = (k) => Boolean(k) && k.length <= 60 && candidates(k).some(direct)
  const whole = normDirective(inner)
  if (one(whole)) return true
  return whole.split(/\s*[,;/]\s*|\s+ve\s+/u).map(normDirective).some(one)
}

/** Sıra metninin başı (sunucudaki _turn_text): baştaki [etiket]ler ve (yönerge)ler. */
function analyzeChunk(chunk, sets) {
  const s = chunk.trim()
  let pos = 0
  let tags = false
  let resolved = false
  let emo = false
  for (;;) {
    const rest = s.slice(pos)
    let m = LEAD_BRACKET_RE.exec(rest)
    if (m) {
      tags = true
      if (!emo && isEmotionTag(m[1], sets.emo)) emo = true
      pos += m[0].length
      continue
    }
    m = LEAD_PAREN_RE.exec(rest)
    if (m && (m[1].length <= 60 || pos + m[0].length >= s.length)) {
      if (directiveResolves(m[1], sets)) resolved = true
      pos += m[0].length
      continue
    }
    break
  }
  return { exists: tags || resolved || Boolean(s.slice(pos).trim()), emo, lead: chunk.length - chunk.trimStart().length }
}

/**
 * Senaryoyu sıralara ayırır (sunucudaki dialog.parse_dialog'un arayüz karşılığı; önizleme ve eşleme için).
 * turns: [{key (konuşmacı anahtarı | NARRATOR), raw (yazıldığı hâli | null), line, at (sıra metninin başladığı konum),
 *          nameAt (ad yanında yönerge varsa adın bittiği konum), groups (ad yanındaki yönerge sayısı), text,
 *          emo (sıra kendi duygu etiketiyle başlıyor)}]
 * speakers: [{key, name, raws, count, line}] (ilk görülme sırasıyla; anlatıcı hariç)
 */
function parseScript(text, sets = { emo: new Set(), tags: new Set(FALLBACK_TAGS) }) {
  const src = String(text ?? '').replace(/^﻿/u, '')
  const shift = String(text ?? '').length - src.length
  const turns = []
  const hints = []
  const known = new Set() // görülen ad anahtarları: sonra küçük harfle yazılsalar da tanınır
  let cur = NARRATOR_REF // en baştaki konuşmacısız satırlar anlatıcının

  const processLine = (line, lineStart, lineNo) => {
    if (!line.trim()) return
    let pos = 0
    let lead = null
    const m = PREFIX_RE.exec(line)
    if (m && validName(m[2], known)) {
      const raw = m[2].trim()
      cur = speakerRef(raw)
      known.add(speakerKey(raw))
      const groups = [...(m[3] || '').matchAll(GROUP_RE)]
      lead = {
        nameAt: lineStart + m[1].length + m[2].replace(/\s+$/u, '').length,
        count: groups.length,
        exists: groups.some((g) => g[2] || directiveResolves(g[1], sets)),
        emo: groups.some((g) => g[2] && isEmotionTag(g[2].slice(1, -1), sets.emo)),
      }
      pos = m[0].length
    } else if (hints.length < 3) {
      const n = NAME_ONLY_RE.exec(line)
      const g = n ? null : NO_SPACE_RE.exec(line)
      if (n && validName(n[1], known)) {
        hints.push({ line: lineNo, msg: `“${line.trim()}” tek başına konuşmacı sayılmaz — sözü aynı satıra yazın (örn. “${displayName(n[1].trim())}: Merhaba!”).` })
      } else if (g && validName(g[1], known)) {
        hints.push({ line: lineNo, msg: `“${displayName(g[1].trim())}:” sonrasında boşluk yok — konuşmacı sayılması için iki noktadan sonra boşluk bırakın.` })
      }
    }
    const body = line.slice(pos)
    let last = 0
    const push = (chunk, from) => {
      const info = analyzeChunk(chunk, sets)
      if (!info.exists && !lead?.exists) return
      turns.push({
        key: cur.key, raw: cur.raw, line: lineNo, at: lineStart + pos + from + info.lead,
        nameAt: lead && lead.count ? lead.nameAt : null, groups: lead ? lead.count : 0,
        text: chunk.trim(), emo: info.emo || Boolean(lead?.emo),
      })
    }
    for (const tm of body.matchAll(KV_TAG_RE)) {
      if (!SPEAKER_TAG_KEYS.has(foldAscii(trLower(tm[1].trim())))) continue
      push(body.slice(last, tm.index), last)
      lead = null
      const val = tm[2].trim()
      if (val) { cur = speakerRef(val); known.add(speakerKey(val)) } // boş "[ses:]" yok sayılır
      last = tm.index + tm[0].length
    }
    push(body.slice(last), last)
  }

  // Satırlar: \r\n | \r | \n (konumlar korunur)
  let i = 0
  let lineNo = 0
  for (;;) {
    let j = i
    while (j < src.length && src[j] !== '\n' && src[j] !== '\r') j++
    processLine(src.slice(i, j), i + shift, ++lineNo)
    if (j >= src.length) break
    i = j + (src[j] === '\r' && src[j + 1] === '\n' ? 2 : 1)
  }

  const groups = new Map()
  const narrator = { count: 0, raws: new Set() }
  for (const t of turns) {
    if (t.key === NARRATOR) {
      narrator.count += 1
      if (t.raw) narrator.raws.add(t.raw)
      continue
    }
    let g = groups.get(t.key)
    if (!g) { g = { key: t.key, raws: new Set(), count: 0, line: t.line }; groups.set(t.key, g) }
    g.count += 1
    g.raws.add(t.raw)
  }
  const speakers = [...groups.values()].map((g) => {
    const raws = [...g.raws]
    const nice = raws.find((r) => r !== trUpper(r)) || raws[0]
    return { key: g.key, name: displayName(nice), raws, count: g.count, line: g.line }
  })
  // "ALI" (→ alı) ile "Ali" Türkçe küçük harfte ayrı ad olur; büyük olasılıkla aynı kişi
  const folded = new Map()
  for (const s of speakers) {
    const f = s.key.replace(/ı/g, 'i')
    const other = folded.get(f)
    if (!other) { folded.set(f, s); continue }
    if (hints.length < 4) {
      hints.push({ line: s.line, msg: `“${other.raws[0]}” ile “${s.raws[0]}” ayrı konuşmacı sayılır (Türkçede “I” küçülünce “ı” olur). Aynı kişiyse adı her satırda aynı yazın.` })
    }
  }
  return {
    turns, speakers, hints,
    narrator: { count: narrator.count, raws: [...narrator.raws] },
    // Sunucu "Anlatıcı:" yazılan satırı da konuşmacı sayar (is_dialog: ≥ 2 farklı konuşmacı).
    dialogCount: speakers.length + (narrator.raws.size ? 1 : 0),
  }
}

/**
 * Konuşmacının varsayılan duygusunu her sıranın başına "[duygu]" olarak ekler (sunucuya giden metin). Sıra kendi
 * duygu etiketiyle başlıyorsa dokunulmaz. Ad yanında yönerge varsa ("Ayşe (fısıldayarak): …") etiket yönergeden ÖNCE
 * eklenir; böylece duygu bildiren yönerge sonradan gelip varsayılanı ezer.
 */
function withEmotions(text, turns, emotionOf) {
  const ins = []
  for (const t of turns) {
    const e = emotionOf(t.key)
    if (!e || t.emo) continue
    if (t.nameAt != null && t.groups > 0 && t.groups < 3) ins.push([t.nameAt, ` [${e}]`])
    else ins.push([t.at, `[${e}] `])
  }
  if (!ins.length) return text
  ins.sort((a, b) => a[0] - b[0])
  let out = ''
  let last = 0
  for (const [at, s] of ins) {
    out += text.slice(last, at) + s
    last = at
  }
  return out + text.slice(last)
}

/** Konuşmacılara renk: kayıtlı renk (çakışmıyorsa), yoksa adın karmasından başlayıp ilk boş renk. */
function assignColors(speakers, map) {
  const out = {}
  const used = new Set()
  for (const s of speakers) {
    const c = map[s.key]?.color
    if (Number.isInteger(c) && c >= 0 && c < PALETTE && !used.has(c)) { out[s.key] = c; used.add(c) }
  }
  for (const s of speakers) {
    if (out[s.key] != null) continue
    let c = hashIndex(s.key)
    for (let k = 0; k < PALETTE && used.has(c); k++) c = (c + 1) % PALETTE
    out[s.key] = c
    used.add(c)
  }
  return out
}

/** Sonuçtaki konuşmacı adından renk sınıfı (üretim anındaki renk eşlemesiyle). */
function spkClass(name, colors) {
  if (name == null || String(name).trim() === '') return 'spk-narrator'
  const key = speakerKey(name)
  if (NARRATOR_WORDS.has(key)) return 'spk-narrator'
  const c = colors?.[key]
  return `spk-${Number.isInteger(c) ? c : hashIndex(key)}`
}

function voiceChoice(entry, voiceById) {
  const v = entry?.voice
  if (v === '') return { value: '', id: null, voice: null, mapped: true, missing: false }
  if (typeof v === 'string' && voiceById.has(v)) return { value: v, id: v, voice: voiceById.get(v), mapped: true, missing: false }
  // Ses listesi henüz gelmediyse "bulunamadı" demeyelim
  return { value: UNSET, id: null, voice: null, mapped: false, missing: typeof v === 'string' && voiceById.size > 0 }
}

function nameMatches(voiceName, key) {
  const vn = speakerKey(voiceName)
  return vn === key || vn.startsWith(`${key} `) || vn.split(/[\s—–-]+/u)[0] === key
}

function upsert(map, key, patch) {
  const { [key]: old, ...rest } = map
  return { ...rest, [key]: { ...(old || {}), ...patch } }
}

function estimateSeconds(turns) {
  let chars = 0
  for (const t of turns) chars += t.text.replace(TAG_RE, ' ').replace(/\s+/g, ' ').trim().length
  return chars ? chars / CHARS_PER_SEC + Math.max(0, turns.length - 1) * TURN_GAP_S : 0
}

function progressText(job, elapsed) {
  if (!job) return 'Gönderiliyor…'
  if (job.status === 'queued') {
    return Number.isFinite(job.position) && job.position > 0 ? `Sırada bekliyor — ${job.position}. sıradasın` : 'Sırada bekliyor…'
  }
  const bits = []
  if (job.total) bits.push(job.step < job.total ? `Parça ${Math.min(job.step + 1, job.total)}/${job.total}` : (job.message || 'Son işlemler'))
  else bits.push(job.message || 'Model yükleniyor…')
  let eta = Number.isFinite(job.eta_s) ? job.eta_s : null
  const p = job.progress || 0
  if (eta == null && p > 0.05 && elapsed > 2) eta = (elapsed * (1 - p)) / p
  if (eta != null && eta >= 1) bits.push(`kalan ≈ ${fmtSecs(eta)}`)
  return bits.join(' • ')
}

function qcSummary(qc) {
  if (!Array.isArray(qc) || !qc.length) return null
  const items = qc.filter((q) => q && typeof q === 'object')
  const scores = items.map((q) => finite(q.score)).filter((v) => v != null)
  return {
    total: items.length,
    avg: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null,
    retried: items.filter((q) => Number(q.retries) > 0 || Number(q.attempts) > 1).length,
    trimmed: items.filter((q) => q.decision === 'trim').length,
    problems: items.filter((q) => q.decision && q.decision !== 'accept'),
  }
}

function normalizeTurns(raw) {
  if (!Array.isArray(raw)) return []
  const list = raw.filter((t) => t && typeof t === 'object').map((t, i) => ({
    index: Number.isInteger(t.index) ? t.index : i,
    speaker: typeof t.speaker === 'string' && t.speaker.trim() ? t.speaker.trim() : null,
    voice: typeof t.voice_name === 'string' ? t.voice_name : '',
    text: String(t.text ?? ''),
    start: finite(t.start),
    end: finite(t.end),
  }))
  if (list.every((t) => t.start != null)) list.sort((a, b) => a.start - b.start || a.index - b.index)
  return list
}

// ─────────────────────────────────────────────────────────── kalıcılık ──

function sanitizeSettings(raw) {
  const s = { ...DEFAULTS }
  if (!raw || typeof raw !== 'object') return s
  for (const k of BOOL_FIELDS) if (typeof raw[k] === 'boolean') s[k] = raw[k]
  if (typeof raw.style === 'string') s.style = raw.style
  if (typeof raw.language === 'string' && raw.language) s.language = raw.language
  if (raw.colloquial !== undefined) s.colloquial = normColloquial(raw.colloquial)
  if (FORMAT_OPTIONS.some(([v]) => v === raw.format)) s.format = raw.format
  return s
}

function sanitizeMap(raw) {
  const out = {}
  if (!raw || typeof raw !== 'object') return out
  for (const [k, e] of Object.entries(raw)) {
    if (!k || !e || typeof e !== 'object') continue
    const v = {}
    if (typeof e.voice === 'string') v.voice = e.voice
    if (typeof e.emotion === 'string' && e.emotion) v.emotion = e.emotion
    if (Number.isInteger(e.color) && e.color >= 0 && e.color < PALETTE) v.color = e.color
    if (Object.keys(v).length) out[k] = v
  }
  return out
}

function loadSaved() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const data = raw ? JSON.parse(raw) : null
    return data && typeof data === 'object' ? data : null
  } catch {
    return null
  }
}

function saveState(data) {
  try {
    const keys = Object.keys(data.map || {})
    const map = keys.length > MAP_LIMIT ? Object.fromEntries(keys.slice(-MAP_LIMIT).map((k) => [k, data.map[k]])) : data.map
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...data, map }))
  } catch { /* depolama kapalı olabilir */ }
}

// ─────────────────────────────────────────────────────────── hook'lar ──

/** Kimliği hiç değişmeyen ama her zaman son hâli çağıran geri çağırım (memo'lu çocuklar için). */
function useLatest(fn) {
  const ref = useRef(fn)
  useLayoutEffect(() => { ref.current = fn })
  return useCallback((...args) => ref.current(...args), [])
}

function useCatalog(health) {
  const key = useMemo(() => JSON.stringify({
    styles: health?.styles ?? null,
    colloquial_levels: health?.colloquial_levels ?? null,
    features: health?.features ?? null,
    emotions: health?.tags?.emotions ?? null,
    nonverbal: health?.tags?.nonverbal ?? null,
    nonverbalDetail: health?.tags?.nonverbal_detail ?? null,
    pauses: health?.tags?.pauses ?? null,
    pauseDetail: health?.tags?.pause_detail ?? null,
  }), [health])
  return useMemo(() => {
    const h = JSON.parse(key)
    const arr = (v) => (Array.isArray(v) ? v : [])
    const tags = [...arr(h.nonverbal), ...arr(h.pauses), ...arr(h.nonverbalDetail).map((x) => x?.tag), ...arr(h.pauseDetail).map((x) => x?.tag)]
      .filter((t) => typeof t === 'string' && t.trim()).map((t) => trLower(t).trim())
    return {
      styles: arr(h.styles).filter((s) => s && typeof s.name === 'string'),
      levels: arr(h.colloquial_levels).length ? h.colloquial_levels : DEFAULT_LEVELS,
      features: h.features && typeof h.features === 'object' ? h.features : {},
      emotions: arr(h.emotions).filter((e) => e && e.name),
      tags: [...new Set(tags)],
    }
  }, [key])
}

function useElapsed(active, since) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return undefined
    setNow(Date.now())
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [active, since])
  return active && since ? Math.max(0, (now - since) / 1000) : 0
}

/** Hazır parçaları sırayla çalan basit HTMLAudio zinciri; yeni parça gelirse kuyruğa eklenir. */
function useChainPlayer(parts, onActiveChange) {
  const partsRef = useRef(parts)
  const audioRef = useRef(null)
  const posRef = useRef(0)
  const activeRef = useRef(false)
  const playRef = useRef(null)
  const [state, setState] = useState({ active: false, index: 0, waiting: false })

  useEffect(() => { partsRef.current = parts }, [parts])

  const playAt = useCallback((i) => {
    if (!activeRef.current) return
    posRef.current = i
    const list = partsRef.current
    if (i >= list.length) { setState({ active: true, index: i, waiting: true }); return }
    let a = audioRef.current
    if (!a) {
      a = new Audio()
      const next = () => playRef.current?.(posRef.current + 1)
      a.addEventListener('ended', next)
      a.addEventListener('error', next) // bozuk parçayı atla
      audioRef.current = a
    }
    a.src = list[i].url
    const p = a.play()
    if (p && typeof p.catch === 'function') p.catch(() => {})
    setState({ active: true, index: i, waiting: false })
  }, [])
  playRef.current = playAt

  useEffect(() => {
    if (state.waiting && activeRef.current && posRef.current < parts.length) playAt(posRef.current)
  }, [parts, state.waiting, playAt])

  const halt = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    a.pause()
    a.removeAttribute('src')
    try { a.load() } catch { /* yok say */ }
  }, [])

  const stop = useCallback(() => {
    if (!activeRef.current) return
    activeRef.current = false
    halt()
    setState({ active: false, index: 0, waiting: false })
    onActiveChange?.(false)
  }, [halt, onActiveChange])

  const start = useCallback(() => {
    activeRef.current = true
    onActiveChange?.(true)
    playAt(0)
  }, [onActiveChange, playAt])

  useEffect(() => () => { activeRef.current = false; halt(); audioRef.current = null }, [halt])

  return { ...state, start, stop }
}

// ─────────────────────────────────────────────────────────── küçük alanlar ──

const SelectField = memo(function SelectField({ name, label, value, options, hint, onChange }) {
  const id = useId()
  return (
    <label htmlFor={id} className="grow">
      <span>{label}</span>
      <select id={id} value={value} aria-describedby={hint ? `${id}h` : undefined} onChange={(e) => onChange(name, e.target.value)}>
        {options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
      {hint && <span id={`${id}h`} className="muted small">{hint}</span>}
    </label>
  )
})

const Check = memo(function Check({ name, title, desc, checked, missing, onChange }) {
  const id = useId()
  return (
    <label className="check" htmlFor={id}>
      <input id={id} type="checkbox" checked={Boolean(checked)} disabled={missing} onChange={(e) => onChange(name, e.target.checked)} />
      <span><b>{title}</b> <span className="muted small">— {desc}{missing ? ' (bu sunucuda yok)' : ''}</span></span>
    </label>
  )
})

/** Metindeki [etiket]leri soluk gösterir. */
function TaggedText({ text }) {
  const parts = String(text).split(/(\[[^\]\n]{1,40}\])/g)
  return parts.map((p, i) => (i % 2 ? <span key={i} className="turn-tag">{p}</span> : p))
}

function QualityBadge({ choice }) {
  if (!choice.mapped) return <span className="badge warn" title="Ses seçilmedi; varsayılan model sesi kullanılır">seçilmedi</span>
  if (!choice.voice) return <span className="badge" title="Modelin yerleşik sesi">model</span>
  const a = choice.voice.analysis
  const q = Number.isFinite(a?.quality_score) ? Math.round(a.quality_score) : null
  if (q == null) return <span className="badge" title="Kayıt kalitesi ölçülmemiş">★ —</span>
  const cls = q >= 70 ? 'ok' : q >= 50 ? 'warn' : 'err'
  return <span className={`badge ${cls}`} title={`Kayıt kalitesi: ${a?.grade || '—'} (${q}/100)`}>★ {q}</span>
}

// ─────────────────────────────────────────────────────────── eşleme paneli ──

const SpeakerRow = memo(function SpeakerRow({ id, label, cls, countLabel, choice, idle, emotion, voices, emotionOptions, onVoice, onEmotion }) {
  const warn = !idle && !choice.mapped
  return (
    <li className={`speaker-row${warn ? ' unmapped' : ''}${idle ? ' idle' : ''}`}>
      <div className="speaker-name">
        <span className={`speaker-badge ${cls}`}>{label}</span>
        <span className="muted small">{countLabel}</span>
        {choice.missing && !idle && <span className="small warn-text">Kayıtlı ses bulunamadı</span>}
      </div>
      <select aria-label={`${label}: ses`} value={choice.value} onChange={(e) => onVoice(id, e.target.value)}>
        {!choice.mapped && <option value={UNSET}>— Ses seçin —</option>}
        <option value="">Varsayılan model sesi</option>
        {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
      </select>
      <select aria-label={`${label}: varsayılan duygu`} value={emotion} onChange={(e) => onEmotion(id, e.target.value)}>
        <option value="">Etiketlere göre</option>
        {emotionOptions.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
      {idle ? <span className="badge" title="Bu senaryoda bu satırlardan yok">—</span> : <QualityBadge choice={choice} />}
    </li>
  )
})

function SpeakerMap({ parsed, colors, choiceOf, emotionOf, voices, emotionOptions, onVoice, onEmotion, onAuto }) {
  const titleId = useId()
  const { speakers, narrator } = parsed
  const narratorChoice = choiceOf(NARRATOR)
  return (
    <div className="speaker-map" role="group" aria-labelledby={titleId}>
      <div className="row between">
        <b id={titleId}>Konuşmacılar <span className="count">{speakers.length}</span></b>
        {speakers.length > 0 && (
          <button type="button" className="btn ghost small" onClick={onAuto} disabled={!voices.length}
            title={voices.length ? 'Sesi seçilmemiş konuşmacılara ad benzerliğine göre, yoksa sırayla farklı sesler atar' : 'Önce "Sesler" sekmesinden ses ekleyin'}>
            Otomatik eşle
          </button>
        )}
      </div>
      {speakers.length === 0 ? (
        <p className="muted small speaker-empty">Konuşmacı algılanmadı. En az iki konuşmacı yazın (örn. 'Ayşe: Merhaba').</p>
      ) : (
        <div className="speaker-map-head small muted" aria-hidden="true">
          <span>Konuşmacı</span><span>Ses</span><span>Varsayılan duygu</span><span>Kalite</span>
        </div>
      )}
      <ul className="speaker-rows">
        {speakers.map((s) => (
          <SpeakerRow key={s.key} id={s.key} label={s.name} cls={`spk-${colors[s.key] ?? hashIndex(s.key)}`}
            countLabel={`${s.count} sıra`} choice={choiceOf(s.key)} emotion={emotionOf(s.key)} voices={voices}
            emotionOptions={emotionOptions} onVoice={onVoice} onEmotion={onEmotion} />
        ))}
        <SpeakerRow id={NARRATOR} label="Anlatıcı" cls="spk-narrator"
          countLabel={narrator.count ? `${narrator.count} sıra` : 'satırı yok'}
          choice={narratorChoice} idle={!narrator.count}
          emotion={emotionOf(NARRATOR)} voices={voices} emotionOptions={emotionOptions} onVoice={onVoice} onEmotion={onEmotion} />
      </ul>
      <p className="muted small">
        Anlatıcı, ilk konuşmacıdan önceki konuşmacısız satırları ve "Anlatıcı:" satırlarını okur. Varsayılan duygu, satırda
        kendi duygu etiketi yoksa başına eklenir. Eşlemeler konuşmacı adına göre hatırlanır.
      </p>
    </div>
  )
}

// ─────────────────────────────────────────────────────────── üretim çubuğu ──

const GenerateBar = memo(function GenerateBar({ busy, job, startedAt, disabled, onCancel }) {
  const elapsed = useElapsed(busy, startedAt)
  const pct = Math.round(clamp(job?.progress || 0, 0, 1) * 100)
  const status = busy ? progressText(job, elapsed) : ''
  const submitRef = useRef(null)
  const cancelRef = useRef(null)
  const wasBusyRef = useRef(false)

  // Klavye odağı kaybolmasın: düğme devre dışı kalınca İptal'e, İptal kaybolunca Seslendir'e geç
  useEffect(() => {
    const ae = document.activeElement
    const lost = !ae || ae === document.body
    if (busy && (lost || ae === submitRef.current)) cancelRef.current?.focus()
    else if (!busy && wasBusyRef.current && lost) submitRef.current?.focus()
    wasBusyRef.current = busy
  }, [busy])

  return (
    <div className="stack tight">
      <div className="row">
        <button ref={submitRef} type="submit" className="btn primary big grow" disabled={disabled || busy} aria-keyshortcuts="Control+Enter">
          {busy ? `Üretiliyor… ${Math.floor(elapsed)} sn` : '▶ Diyaloğu seslendir'}
        </button>
        {busy && <button ref={cancelRef} type="button" className="btn danger big" onClick={onCancel} aria-label="Üretimi iptal et">✕ İptal</button>}
      </div>
      {busy && (
        <div className="progress" role="progressbar" aria-label="Üretim ilerlemesi" aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={pct} aria-valuetext={status}>
          <div className="bar" style={{ width: `${pct}%` }} />
          <div className="muted small">{status}</div>
        </div>
      )}
    </div>
  )
})

// ─────────────────────────────────────────────────────────── canlı parçalar ──

const PartialItem = memo(function PartialItem({ url, text, duration, speaker, cls, n, playing }) {
  return (
    <li className={`item small${playing ? ' playing' : ''}`} aria-current={playing ? 'true' : undefined}>
      <div className="row between">
        <span className="muted">
          {speaker && <span className={`speaker-badge small ${cls}`}>{speaker}</span>} Parça {n}{Number.isFinite(duration) ? ` • ${fmtDur(duration)}` : ''}
        </span>
        {playing && <span className="tag emo">çalıyor</span>}
      </div>
      <Player src={url} compact title={`Parça ${n}`} downloadName={`sesklon-diyalog-parca-${n}.${extOf(url)}`} />
      {text && <div><TaggedText text={text} /></div>}
    </li>
  )
})

const PartialPreview = memo(function PartialPreview({ parts, total, colors, onActiveChange }) {
  const listRef = useRef(null)
  const chain = useChainPlayer(parts, onActiveChange)
  const { stop } = chain

  // Herhangi bir oynatıcı çalmaya başlarsa sıralı dinlemeyi durdur (iki ses üst üste binmesin)
  useEffect(() => {
    const el = listRef.current
    const bus = PlayerModule.playerBus
    const hasBus = Boolean(bus && typeof bus.addEventListener === 'function')
    el?.addEventListener('play', stop, true)
    if (hasBus) bus.addEventListener('play', stop)
    return () => {
      el?.removeEventListener('play', stop, true)
      if (hasBus) bus.removeEventListener('play', stop)
    }
  }, [stop])

  const start = () => {
    if (typeof PlayerModule.stopAllPlayers === 'function') PlayerModule.stopAllPlayers()
    listRef.current?.querySelectorAll('audio').forEach((a) => a.pause())
    chain.start()
  }

  let status = null
  if (chain.active) status = chain.waiting ? `Parça ${chain.index + 1} hazırlanıyor…` : `Çalınıyor: parça ${chain.index + 1} / ${parts.length}`

  return (
    <div className="stack">
      <div className="row between">
        <b className="small">Hazır olan parçalar: {parts.length}{total ? ` / ${total}` : ''}</b>
        {chain.active ? (
          <button type="button" className="btn secondary small" onClick={chain.stop} aria-label="Sıralı dinlemeyi durdur">■ Durdur</button>
        ) : (
          <button type="button" className="btn primary small" onClick={start}>▶ Baştan dinlemeye başla</button>
        )}
      </div>
      {status && <div className="muted small" aria-live="polite">{status}</div>}
      <ul className="list partial-list" ref={listRef} aria-label="Hazır olan parçalar">
        {parts.map((p, i) => (
          <PartialItem key={p.url} url={p.url} text={p.text} duration={p.duration} n={i + 1}
            speaker={typeof p.speaker === 'string' && p.speaker ? displayName(p.speaker) : null} cls={spkClass(p.speaker, colors)}
            playing={chain.active && !chain.waiting && chain.index === i} />
        ))}
      </ul>
    </div>
  )
})

// ─────────────────────────────────────────────────────────── sonuç ──

function QualitySummary({ qc }) {
  const s = qcSummary(qc)
  if (!s) return null
  const avg = s.avg != null ? Math.round(s.avg) : null
  const cls = avg == null ? '' : avg >= 80 ? 'ok' : avg >= 60 ? 'warn' : 'err'
  return (
    <div className="stack tight qc-summary">
      <div className="badges">
        {avg != null && <span className={`badge ${cls}`} title="Denetlenen parçaların ortalama kalite puanı">Kalite kontrol: ort. {avg}/100</span>}
        <span className="badge" title="Kalite kontrolünden geçen parça sayısı">{s.total} parça denetlendi</span>
        {s.retried > 0 && <span className="badge warn" title="Takılma, tekrar, sessizlik gibi sorunlar nedeniyle">{s.retried} parça yeniden üretildi</span>}
        {s.trimmed > 0 && <span className="badge info" title="Sondaki fazla sessizlik ya da kırpılma düzeltildi">{s.trimmed} parça kırpıldı</span>}
      </div>
      {s.problems.length > 0 && (
        <details className="chunks">
          <summary className="muted small">Kalite kontrol ayrıntıları ({s.problems.length})</summary>
          <ul className="list">
            {s.problems.map((q, i) => {
              const reasons = (Array.isArray(q.reasons) ? q.reasons : []).map((r) => (typeof r === 'string' ? r : r?.message || r?.code)).filter(Boolean)
              const n = Number.isInteger(q.index) ? q.index + 1 : i + 1
              return (
                <li key={`${q.index ?? i}-${i}`} className="item small">
                  <div className="row between">
                    <b>Parça {n}</b>
                    <span className="muted">{DECISION_LABELS[q.decision] || q.decision}{finite(q.score) != null ? ` • puan ${Math.round(finite(q.score))}` : ''}</span>
                  </div>
                  {reasons.length > 0 && <div className="muted">{reasons.join(' • ')}</div>}
                </li>
              )
            })}
          </ul>
        </details>
      )}
    </div>
  )
}

function SubtitleBar({ genId, notify }) {
  const [busyFmt, setBusyFmt] = useState('')
  const [preview, setPreview] = useState({ loading: false, text: '', error: '' })
  const loadedRef = useRef(false)
  const aliveRef = useRef(true)
  useEffect(() => {
    aliveRef.current = true // StrictMode'daki ikinci kurulumda da doğru kalsın
    return () => { aliveRef.current = false }
  }, [])

  async function download(fmt) {
    if (busyFmt) return
    setBusyFmt(fmt)
    try {
      await api.subtitles(genId, fmt)
    } catch (err) {
      notify?.(err?.message || 'Altyazı indirilemedi', 'error')
    } finally {
      if (aliveRef.current) setBusyFmt('')
    }
  }

  function onToggle(e) {
    if (!e.currentTarget.open || loadedRef.current) return
    loadedRef.current = true
    setPreview({ loading: true, text: '', error: '' })
    api.subtitleText(genId, 'srt')
      .then((text) => { if (aliveRef.current) setPreview({ loading: false, text: String(text || ''), error: '' }) })
      .catch((err) => {
        loadedRef.current = false
        if (aliveRef.current) setPreview({ loading: false, text: '', error: err?.message || 'Altyazı alınamadı' })
      })
  }

  return (
    <div className="stack tight">
      <div className="row subtitle-bar">
        <span className="small muted">Altyazı indir:</span>
        {['srt', 'vtt'].map((f) => (
          <button key={f} type="button" className="btn ghost small" onClick={() => download(f)} disabled={Boolean(busyFmt)}
            aria-label={`Altyazıyı ${f.toUpperCase()} olarak indir`}>
            {busyFmt === f ? 'İndiriliyor…' : f.toUpperCase()}
          </button>
        ))}
      </div>
      <details className="chunks" onToggle={onToggle}>
        <summary className="muted small">Altyazıyı önizle (SRT)</summary>
        {preview.loading && <p className="muted small">Yükleniyor…</p>}
        {preview.error && <p className="small warn-text">{preview.error}</p>}
        {preview.text && <pre className="subtitle-preview">{preview.text}</pre>}
      </details>
    </div>
  )
}

/**
 * Sıralar listesi: tıklanan sıraya atlar. Player'ın konum API'si yok; bu yüzden önce playerBus'a iptal edilebilir
 * {type:'seek', src, time} olayı yayınlanır (bir Player dinleyip preventDefault() ile üstlenirse o kullanılır), yoksa
 * gizli bir <audio> ile o saniyeden çalınır. Ana oynatıcı çalarken de etkin sıra işaretlenir.
 */
function TurnList({ gen, turns, colors, wrapRef, notify }) {
  const busId = useId()
  const audioRef = useRef(null)
  const listRef = useRef(null)
  const pendingRef = useRef(null) // gidilecek saniye; sunucu Range desteklemezse veri geldikçe yeniden denenir
  const [pos, setPos] = useState({ source: null, time: 0, playing: false, duration: 0 })

  const applyPending = useCallback(() => {
    const a = audioRef.current
    const want = pendingRef.current
    if (!a || want == null) return
    if (Math.abs((a.currentTime || 0) - want) < 0.35) { pendingRef.current = null; return }
    try { a.currentTime = want } catch { /* henüz konumlanamıyor; sonraki olayda yeniden */ }
  }, [])

  // Ana oynatıcıyı (Player) izle: medya olayları kabarmaz ama yakalama evresinde atadan dinlenebilir.
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return undefined
    const on = (e) => {
      const a = e.target
      if (!a || typeof a.currentTime !== 'number') return
      if (e.type === 'play') {
        pendingRef.current = null
        setPos((p) => ({ ...p, source: 'player', time: a.currentTime, playing: true }))
        return
      }
      setPos((p) => {
        if (p.source === 'mini' && p.playing) return p // gizli oynatıcı çalarken ana oynatıcıdaki konum değişimi işaret değiştirmez
        if (p.source !== 'player' && e.type !== 'seeked') return p
        return { ...p, source: 'player', time: a.currentTime, playing: !a.paused && !a.ended }
      })
    }
    const types = ['play', 'pause', 'timeupdate', 'seeked', 'ended']
    types.forEach((t) => el.addEventListener(t, on, true))
    return () => types.forEach((t) => el.removeEventListener(t, on, true))
  }, [wrapRef])

  // Aynı anda tek oynatıcı: başka bir oynatıcı çalarsa ya da "stop" gelirse gizli oynatıcı durur.
  useEffect(() => {
    const bus = PlayerModule.playerBus
    if (!bus || typeof bus.addEventListener !== 'function') return undefined
    const onPlay = (e) => { if (e.detail !== busId) audioRef.current?.pause() }
    const onStop = () => audioRef.current?.pause()
    bus.addEventListener('play', onPlay)
    bus.addEventListener('stop', onStop)
    return () => {
      bus.removeEventListener('play', onPlay)
      bus.removeEventListener('stop', onStop)
    }
  }, [busId])

  useEffect(() => {
    const a = audioRef.current
    return () => { try { a?.pause() } catch { /* yok say */ } }
  }, [])

  const activeIdx = useMemo(() => {
    if (!pos.source || !turns.length) return -1
    const t = pos.time + 0.05
    let idx = -1
    for (let i = 0; i < turns.length; i++) {
      const s = turns[i].start
      if (s == null) continue
      if (s <= t) idx = i
      else break
    }
    return idx
  }, [pos.source, pos.time, turns])

  // Etkin sıra görünür kalsın (yalnızca liste kayar, sayfa değil)
  useEffect(() => {
    const list = listRef.current
    if (activeIdx < 0 || !list || list.scrollHeight <= list.clientHeight + 2) return
    const row = list.querySelector(`[data-turn="${activeIdx}"]`)
    if (!row) return
    const top = row.offsetTop
    const bottom = top + row.offsetHeight
    if (top < list.scrollTop) list.scrollTop = Math.max(0, top - 6)
    else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight + 6
  }, [activeIdx])

  const playTurn = useCallback((i) => {
    const turn = turns[i]
    if (!turn) return
    const time = Math.max(0, turn.start ?? 0)
    const bus = PlayerModule.playerBus
    let handled = false
    try {
      if (bus && typeof bus.dispatchEvent === 'function' && typeof CustomEvent === 'function') {
        handled = !bus.dispatchEvent(new CustomEvent('seek', { cancelable: true, detail: { type: 'seek', src: gen.url, time } }))
      }
    } catch { /* yok say */ }
    if (handled) { setPos((p) => ({ ...p, source: 'player', time })); return }

    if (typeof PlayerModule.stopAllPlayers === 'function') PlayerModule.stopAllPlayers()
    const a = audioRef.current
    if (!a) return
    pendingRef.current = time
    applyPending() // meta veri yoksa tarayıcı başlangıç konumu olarak saklar; yüklenince yeniden denenir
    setPos((p) => ({ ...p, source: 'mini', time, playing: true }))
    const pr = a.play()
    if (pr && typeof pr.catch === 'function') {
      pr.catch((err) => {
        if (err?.name === 'AbortError') return
        setPos((p) => ({ ...p, playing: false }))
        notify?.(err?.name === 'NotAllowedError' ? 'Tarayıcı oynatmaya izin vermedi; tekrar deneyin.' : 'Ses oynatılamadı.', 'error')
      })
    }
  }, [turns, gen.url, notify, applyPending])

  const toggleMini = () => {
    const a = audioRef.current
    if (!a) return
    if (a.paused) {
      const pr = a.play()
      if (pr && typeof pr.catch === 'function') pr.catch(() => {})
    } else a.pause()
  }
  const stopMini = () => {
    pendingRef.current = null
    audioRef.current?.pause()
    setPos((p) => ({ ...p, source: null, playing: false }))
  }

  const onAudioPlay = () => {
    setPos((p) => ({ ...p, source: 'mini', playing: true }))
    try { PlayerModule.playerBus?.dispatchEvent(new CustomEvent('play', { detail: busId })) } catch { /* yok say */ }
  }
  const onAudioPause = () => setPos((p) => (p.source === 'mini' ? { ...p, playing: false } : p))
  const onAudioTime = (e) => {
    const t = e.currentTarget.currentTime
    if (pendingRef.current != null) applyPending()
    setPos((p) => (p.source === 'mini' ? { ...p, time: t } : p))
  }
  const onAudioMeta = (e) => {
    const d = e.currentTarget.duration
    applyPending()
    if (Number.isFinite(d) && d > 0) setPos((p) => (p.duration === d ? p : { ...p, duration: d }))
  }

  if (!turns.length) {
    return (
      <p className="muted small">
        Sunucu sıra bilgisi döndürmedi; metin diyalog olarak işlenmemiş olabilir (sunucu sürümünü ve konuşmacı satırlarını kontrol edin).
      </p>
    )
  }

  const active = activeIdx >= 0 ? turns[activeIdx] : null
  const dur = pos.duration || finite(gen.duration) || 0

  return (
    <div className="stack tight">
      <div className="row between">
        <b className="small">Sıralar <span className="count">{turns.length}</span></b>
        <span className="muted small">Bir sıraya tıkla: o andan dinle</span>
      </div>
      {pos.source === 'mini' && (
        <div className="turn-player" role="group" aria-label="Sıradan dinleme">
          <button type="button" className="btn ghost small" onClick={toggleMini} aria-label={pos.playing ? 'Duraklat' : 'Devam et'}>
            {pos.playing ? '❚❚ Duraklat' : '▶ Devam'}
          </button>
          <span className="small turn-player-status">
            {active ? <><span className={`speaker-badge small ${spkClass(active.speaker, colors)}`}>{active.speaker ? displayName(active.speaker) : 'Anlatıcı'}</span> </> : null}
            <span className="mono">{fmtStamp(pos.time)}{dur ? ` / ${fmtStamp(dur)}` : ''}</span>
          </span>
          <button type="button" className="btn ghost small" onClick={stopMini} aria-label="Sıradan dinlemeyi durdur">■ Durdur</button>
        </div>
      )}
      <audio ref={audioRef} src={gen.url} preload="none" hidden onPlay={onAudioPlay} onPause={onAudioPause} onEnded={onAudioPause}
        onTimeUpdate={onAudioTime} onLoadedMetadata={onAudioMeta} onDurationChange={onAudioMeta}
        onCanPlay={applyPending} onCanPlayThrough={applyPending} onProgress={applyPending} onSeeked={applyPending} />
      <ul className="turn-list" ref={listRef} aria-label="Sıralar">
        {turns.map((t, i) => {
          const cls = spkClass(t.speaker, colors)
          const on = i === activeIdx
          const who = t.speaker ? displayName(t.speaker) : 'Anlatıcı'
          return (
            <li key={`${t.index}-${i}`} data-turn={i}>
              <button type="button" className={`turn ${cls}${on ? ' active' : ''}`} aria-current={on ? 'true' : undefined}
                onClick={() => playTurn(i)} title={`${who} — ${fmtStamp(t.start)} anından dinle`}>
                <span className="turn-head">
                  <span className={`speaker-badge small ${cls}`}>{who}</span>
                  <span className="turn-time mono">{fmtStamp(t.start)}</span>
                  {t.voice && <span className="muted small turn-voice">{t.voice}</span>}
                </span>
                <span className="turn-text"><TaggedText text={t.text} /></span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

const DialogResult = memo(function DialogResult({ result, autoPlay, notify }) {
  const { gen, colors, subtitles } = result
  const params = gen.params && typeof gen.params === 'object' ? gen.params : {}
  const turns = useMemo(() => normalizeTurns(params.turns), [params.turns])
  const wrapRef = useRef(null)

  const speakerCount = new Set(turns.filter((t) => t.speaker).map((t) => speakerKey(t.speaker))).size
  const meta = []
  if (speakerCount) meta.push(`${speakerCount} konuşmacı`)
  if (Number.isFinite(gen.duration)) meta.push(fmtDur(gen.duration))
  const lufs = params.loudness?.lufs
  if (Number.isFinite(lufs)) meta.push(`${lufs.toFixed(1)} LUFS`)
  if (Number.isFinite(gen.elapsed)) meta.push(`${gen.elapsed.toFixed(1)} sn'de üretildi`)

  const cons = (params.consistency_report && typeof params.consistency_report === 'object') ? params.consistency_report
    : (params.consistency && typeof params.consistency === 'object' ? params.consistency : null)
  const timbre = finite(cons?.timbre_db)
  const steps = finite(cons?.loudness_steps)
  const nonverbal = Array.isArray(params.nonverbal_used) ? [...new Set(params.nonverbal_used.filter(Boolean))] : []
  const showSubs = Array.isArray(params.timeline) ? params.timeline.length > 0 : subtitles

  return (
    <div className="stack">
      <div ref={wrapRef}>
        <Player key={gen.id} src={gen.url} title="Diyalog" autoPlay={autoPlay}
          downloadName={`sesklon-diyalog-${gen.id}.${extOf(gen.filename || gen.url)}`} />
      </div>
      <div className="muted small">
        {meta.join(' • ')}{meta.length ? ' • ' : ''}<span className="ok-text">✓ Geçmişe eklendi</span>
      </div>
      {(cons || nonverbal.length > 0) && (
        <div className="badges">
          {cons && (
            <span className="badge info" title="Parçalar arası tını eşleme ve ses seviyesi düzeltmesi">
              Tutarlılık{timbre != null ? `: tını ±${Math.abs(timbre).toFixed(1)} dB` : ''}{steps != null ? ` • ${steps} seviye düzeltmesi` : ''}
            </span>
          )}
          {nonverbal.length > 0 && <span className="badge accent" title="Sesin kendi tepki kayıtlarından eklendi">Gerçek tepki: {nonverbal.join(', ')}</span>}
        </div>
      )}
      <QualitySummary qc={params.qc_reports ?? params.qc} />
      {showSubs && <SubtitleBar genId={gen.id} notify={notify} />}
      <TurnList gen={gen} turns={turns} colors={colors} wrapRef={wrapRef} notify={notify} />
      {params.normalized_text && (
        <details className="chunks">
          <summary className="muted small">Modelin okuduğu metin</summary>
          <p className="quote small">{params.normalized_text}</p>
        </details>
      )}
    </div>
  )
})

// ─────────────────────────────────────────────────────────── ana bileşen ──

export default function Dialog({ voices = [], languages, health, onGenerated, notify }) {
  const [saved] = useState(loadSaved)
  const maxChars = health?.max_text_chars || 5000
  const [text, setText] = useState(() => (typeof saved?.text === 'string' ? saved.text : EXAMPLES[0].text).slice(0, maxChars))
  const [map, setMap] = useState(() => sanitizeMap(saved?.map))
  const [settings, setSettings] = useState(() => sanitizeSettings(saved?.settings))
  const [ui, setUi] = useState(() => ({ natural: saved?.ui?.natural === true }))
  const [busy, setBusy] = useState(false)
  const [startedAt, setStartedAt] = useState(0)
  const [job, setJob] = useState(null)
  const [result, setResult] = useState(null) // { gen, colors, subtitles }
  const [resultAutoPlay, setResultAutoPlay] = useState(true)
  const [runColors, setRunColors] = useState({}) // süren üretimin renk eşlemesi (canlı parçalar için)

  const rootRef = useRef(null)
  const autoStyleRef = useRef(Boolean(saved?.settings)) // kayıtlı ayar yoksa ilk açılışta "sohbet" stili
  const textRef = useRef(null)
  const busyRef = useRef(false)
  const runRef = useRef(0) // her üretim bir "çalışma"; vazgeçilen çalışmanın sonucu yok sayılır
  const jobRef = useRef(null)
  const chainActiveRef = useRef(false)
  const cancelledIdsRef = useRef(new Set())
  const latestSaveRef = useRef(null)

  const textId = useId()
  const countId = useId()
  const exampleId = useId()
  const leftId = useId()
  const rightId = useId()

  const catalog = useCatalog(health)
  const langs = languages && typeof languages === 'object' && Object.keys(languages).length ? languages : { tr: 'Türkçe' }
  const voiceById = useMemo(() => new Map(voices.map((v) => [v.id, v])), [voices])
  const tagSets = useMemo(() => buildSets(catalog), [catalog])
  const parsed = useMemo(() => parseScript(text, tagSets), [text, tagSets])
  const colors = useMemo(() => assignColors(parsed.speakers, map), [parsed.speakers, map])
  const emotionOptions = useMemo(() => {
    const list = catalog.emotions.length
      ? catalog.emotions.filter((e) => e.name !== 'normal').map((e) => [e.name, e.label || e.name])
      : FALLBACK_EMOTIONS.map((e) => [e, e])
    const known = new Set(list.map(([v]) => v))
    for (const e of Object.values(map)) if (e.emotion && !known.has(e.emotion)) { known.add(e.emotion); list.push([e.emotion, e.emotion]) }
    return list
  }, [catalog.emotions, map])
  const activeStyle = useMemo(() => catalog.styles.find((s) => s.name === settings.style) || null, [catalog.styles, settings.style])

  const choiceOf = useCallback((key) => voiceChoice(map[key], voiceById), [map, voiceById])
  const emotionOf = useCallback((key) => map[key]?.emotion || '', [map])
  const finalText = useMemo(() => withEmotions(text, parsed.turns, emotionOf), [text, parsed.turns, emotionOf])

  // Canlı önizleme: yalnızca yeni parça geldiğinde yeni dizi (her yoklamada değil)
  const rawPartial = job?.partial
  const partialKey = Array.isArray(rawPartial) ? rawPartial.map((p) => p?.url).join('|') : ''
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const partial = useMemo(() => (Array.isArray(rawPartial) ? rawPartial.filter((p) => p && p.url) : []), [partialKey])

  const notifyLatest = useLatest((msg, type) => notify?.(msg, type))
  const onGeneratedLatest = useLatest((g) => onGenerated?.(g))

  // ── etkiler
  useEffect(() => { setText((t) => (t.length > maxChars ? t.slice(0, maxChars) : t)) }, [maxChars])

  // Kalıcılık (400 ms gecikmeli; bileşen kapanırken hemen yaz)
  useEffect(() => {
    latestSaveRef.current = { v: 4, text, map, settings, ui }
    const t = setTimeout(() => saveState(latestSaveRef.current), 400)
    return () => clearTimeout(t)
  }, [text, map, settings, ui])
  useEffect(() => () => { if (latestSaveRef.current) saveState(latestSaveRef.current) }, [])

  // ── eşleme
  const setVoice = useCallback((key, value) => {
    if (value === UNSET) return
    setMap((m) => upsert(m, key, key === NARRATOR ? { voice: value } : { voice: value, color: colors[key] }))
  }, [colors])
  const setEmotion = useCallback((key, value) => {
    setMap((m) => {
      const next = upsert(m, key, key === NARRATOR ? {} : { color: colors[key] })
      if (value) next[key].emotion = value
      else delete next[key].emotion
      return next
    })
  }, [colors])

  const autoMap = useLatest(() => {
    if (!voices.length) { notifyLatest('Önce "Sesler" sekmesinden ses ekleyin.', 'warn'); return }
    const targets = parsed.speakers.map((s) => s.key)
    if (parsed.narrator.count) targets.push(NARRATOR)
    const used = new Set()
    for (const k of targets) { const c = choiceOf(k); if (c.mapped && c.id) used.add(c.id) }
    const assign = {}
    let cycle = 0
    for (const k of targets) {
      if (choiceOf(k).mapped) continue
      let v = k === NARRATOR ? null : voices.find((x) => !used.has(x.id) && nameMatches(x.name, k))
      if (!v) v = voices.find((x) => !used.has(x.id))
      if (!v && k !== NARRATOR) v = voices[cycle++ % voices.length] // ses sayısı yetmezse baştan dağıt
      if (!v) continue
      used.add(v.id)
      assign[k] = v.id
    }
    const keys = Object.keys(assign)
    if (!keys.length) { notifyLatest('Tüm konuşmacıların sesi zaten seçili.'); return }
    setMap((m) => keys.reduce((acc, k) => upsert(acc, k, k === NARRATOR ? { voice: assign[k] } : { voice: assign[k], color: colors[k] }), m))
    notifyLatest(`${keys.length} konuşmacıya ses atandı.`)
  })

  // ── ayarlar
  const setField = useCallback((key, value) => setSettings((s) => (s[key] === value ? s : { ...s, [key]: value })), [])
  const onStyle = useLatest((_, name) => {
    const st = catalog.styles.find((s) => s.name === name)
    setSettings((s) => {
      const next = { ...s, style: name }
      if (st) {
        if (st.colloquial !== undefined && st.colloquial !== null) next.colloquial = normColloquial(st.colloquial)
        if (typeof st.breaths === 'boolean') next.breaths = st.breaths
      }
      return next
    })
  })
  const onToggleNatural = useCallback((e) => {
    const open = e.currentTarget.open
    setUi((u) => (u.natural === open ? u : { ...u, natural: open }))
  }, [])

  useEffect(() => {
    if (autoStyleRef.current || !catalog.styles.length) return
    autoStyleRef.current = true
    if (!settings.style && catalog.styles.some((s) => s.name === 'sohbet')) onStyle('style', 'sohbet')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.styles, onStyle])

  // ── metin
  const onTextChange = (e) => setText(e.target.value.slice(0, maxChars))

  function onExample(e) {
    const ex = EXAMPLES.find((x) => x.id === e.target.value)
    if (!ex) return
    const cur = textRef.current ? textRef.current.value : text
    const replaceable = !cur.trim() || EXAMPLES.some((x) => x.text === cur)
    if (!replaceable && !window.confirm('Yazdığın senaryonun yerine örnek senaryo konsun mu?')) return
    setText(ex.text.slice(0, maxChars))
    const st = catalog.styles.find((s) => s.name === ex.style)
    if (st) {
      onStyle('style', st.name)
      notifyLatest(`"${ex.label}" örneği yüklendi; "${st.label || st.name}" stili seçildi.`)
    }
  }

  // ── üretim / iptal
  const requestCancel = useCallback((id) => {
    if (!id || cancelledIdsRef.current.has(id)) return
    cancelledIdsRef.current.add(id)
    if (typeof api.cancelJob !== 'function') {
      notifyLatest('Bu sürüm iptali desteklemiyor; iş arka planda tamamlanacak.', 'error')
      return
    }
    Promise.resolve()
      .then(() => api.cancelJob(id))
      .catch((err) => notifyLatest(`İptal isteği iletilemedi: ${err?.message || err}`, 'error'))
  }, [notifyLatest])

  const tooFew = parsed.dialogCount < 2
  const overLimit = finalText.length > maxChars
  const dialogOff = catalog.features.dialog === false
  const canGenerate = Boolean(text.trim()) && !tooFew && !overLimit && !dialogOff

  const generate = useLatest(async () => {
    if (busyRef.current) return
    if (!canGenerate) {
      if (tooFew) textRef.current?.focus()
      return
    }
    busyRef.current = true
    const run = ++runRef.current
    const s = settings
    const speakers = {}
    for (const sp of parsed.speakers) {
      const id = choiceOf(sp.key).id
      for (const raw of sp.raws) speakers[raw] = id
    }
    const narratorId = choiceOf(NARRATOR).id
    for (const raw of parsed.narrator.raws) speakers[raw] = narratorId
    const payload = {
      text: finalText,
      voice_id: null, // diyalogda sesler `speakers` ve `narrator_voice_id` ile gelir; eşlenmeyen → varsayılan model sesi
      language: s.language || 'tr',
      style: activeStyle ? activeStyle.name : null,
      colloquial: s.colloquial,
      breaths: s.breaths,
      room_tone: s.room_tone,
      master: s.master,
      consistency: s.consistency,
      qc: s.qc,
      subtitles: s.subtitles,
      fillers: s.fillers,
      chat_speak: s.chat_speak,
      speakers,
      narrator_voice_id: narratorId,
      format: s.format,
      variants: 1,
    }
    const snapshot = { colors: { ...colors }, subtitles: s.subtitles }
    jobRef.current = null
    chainActiveRef.current = false
    setRunColors(snapshot.colors)
    setBusy(true); setStartedAt(Date.now()); setJob(null); setResult(null)

    const onProgress = (j) => {
      if (!j) return
      if (run !== runRef.current) { // vazgeçilen çalışma: sunucudaki işi de durdur
        if (j.id && (j.status === 'queued' || j.status === 'running')) requestCancel(j.id)
        return
      }
      jobRef.current = j
      setJob(j)
    }

    try {
      const gen = await api.tts(payload, onProgress)
      if (gen) onGeneratedLatest(gen)
      if (run !== runRef.current) return
      if (!gen) {
        const wasCancelled = jobRef.current?.status === 'cancelled'
        notifyLatest(wasCancelled ? 'Üretim iptal edildi.' : 'Sunucu sonuç döndürmedi.', wasCancelled ? 'ok' : 'error')
        return
      }
      // Kullanıcı başka sekmedeyse (bu bölüm gizli) kendiliğinden çalma; haber ver
      const visible = Boolean(rootRef.current && rootRef.current.offsetParent !== null)
      setResultAutoPlay(visible && !chainActiveRef.current) // sıralı dinleme açıksa sonucu baştan çalıp bölme
      setResult({ gen, ...snapshot })
      if (!visible) notifyLatest('Diyalog hazır — "Diyalog" sekmesinden dinleyebilirsin.')
    } catch (err) {
      if (run !== runRef.current) return
      const cancelled = isCancelledError(err) || jobRef.current?.status === 'cancelled'
      notifyLatest(cancelled ? 'Üretim iptal edildi.' : (err?.message || 'Üretim başarısız'), cancelled ? 'ok' : 'error')
    } finally {
      if (run === runRef.current) { busyRef.current = false; setBusy(false); setJob(null) }
    }
  })

  const cancel = useCallback(() => {
    if (!busyRef.current) return
    const id = jobRef.current?.id
    runRef.current += 1 // bu çalışmadan vazgeç; kimlik henüz yoksa ilk ilerlemede iptal gönderilir
    busyRef.current = false
    chainActiveRef.current = false
    setBusy(false); setJob(null)
    if (id) requestCancel(id)
    notifyLatest('Üretim iptal edildi.')
  }, [requestCancel, notifyLatest])

  const setChainActive = useCallback((v) => { chainActiveRef.current = v }, [])
  const onSubmit = useCallback((e) => { e.preventDefault(); generate() }, [generate])
  const onFormKeyDown = useCallback((e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); generate() }
  }, [generate])

  // ── görünüm değerleri
  const estimate = estimateSeconds(parsed.turns)
  const nearLimit = text.length >= maxChars * 0.9
  const unmapped = parsed.speakers.filter((s) => !choiceOf(s.key).mapped).map((s) => s.name)
  if (parsed.narrator.count && !choiceOf(NARRATOR).mapped) unmapped.push('Anlatıcı')
  const levelOptions = (catalog.levels.includes(settings.colloquial) ? catalog.levels : [...catalog.levels, settings.colloquial])
    .map((l) => [l, COLLOQUIAL_LABELS[l] || l])
  const styleOptions = [['', 'Stilsiz (varsayılan ayarlar)'], ...catalog.styles.map((st) => [st.name, st.label || st.name])]
  if (settings.style && !catalog.styles.some((st) => st.name === settings.style)) styleOptions.push([settings.style, settings.style])
  const langOptions = Object.entries(langs).map(([k, v]) => [k, v])
  if (!langs[settings.language]) langOptions.push([settings.language, settings.language])
  const f = catalog.features
  const naturalSummary = [
    activeStyle ? activeStyle.label || activeStyle.name : 'stilsiz',
    COLLOQUIAL_SHORT[settings.colloquial] || settings.colloquial,
    settings.subtitles ? 'altyazı' : null,
    settings.qc ? 'kalite kontrol' : null,
    settings.format.toUpperCase(),
  ].filter(Boolean).join(' · ')
  const tooFewMsg = `${parsed.dialogCount === 0 ? 'Konuşmacı algılanmadı. ' : `Yalnızca bir konuşmacı var (${parsed.speakers[0]?.name || 'Anlatıcı'}). `}En az iki konuşmacı yazın (örn. 'Ayşe: Merhaba')`

  return (
    <div className="grid two dialog" ref={rootRef}>
      <section className="card" aria-labelledby={leftId}>
        <h2 id={leftId}>Senaryo</h2>
        <form className="stack" onSubmit={onSubmit} onKeyDown={onFormKeyDown} noValidate>
          <div className="stack tight">
            <div className="row between">
              <label htmlFor={textId}><span>Diyalog metni <span className="muted">(Ctrl+Enter ile üret)</span></span></label>
              <label className="inline small" htmlFor={exampleId}>
                Örnek senaryo
                <select id={exampleId} value="" onChange={onExample}>
                  <option value="">Seç…</option>
                  {EXAMPLES.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
                </select>
              </label>
            </div>
            <textarea id={textId} ref={textRef} className="script-area" rows={11} value={text} onChange={onTextChange}
              placeholder={PLACEHOLDER} aria-describedby={countId} spellCheck={false} />
            <div className="row between" id={countId}>
              <span className={`small ${nearLimit ? 'warn-text' : 'muted'}`}>{text.length} / {maxChars} karakter</span>
              <span className="small muted">
                {estimate > 0 ? `≈ ${fmtSecs(estimate)} ses • ${parsed.turns.length} sıra` : 'Metin boş'}
              </span>
            </div>
            {parsed.hints.length > 0 && (
              <ul className="issues">
                {parsed.hints.map((h, i) => <li key={`${h.line}-${i}`} className="issue warn">Satır {h.line}: {h.msg}</li>)}
              </ul>
            )}
          </div>

          <SpeakerMap parsed={parsed} colors={colors} choiceOf={choiceOf} emotionOf={emotionOf} voices={voices}
            emotionOptions={emotionOptions} onVoice={setVoice} onEmotion={setEmotion} onAuto={autoMap} />

          <details className="panel" open={ui.natural} onToggle={onToggleNatural}>
            <summary><b>Doğallık ve çıktı</b> <span className="muted small">— {naturalSummary}</span></summary>
            <div className="panel-body">
              <div className="stack tight">
                <div className="row">
                  <SelectField name="style" label="Stil" value={settings.style} options={styleOptions} onChange={onStyle} />
                  <SelectField name="colloquial" label="Konuşma dili" value={settings.colloquial} options={levelOptions} onChange={setField} />
                </div>
                <span className="muted small">
                  {activeStyle?.description ? `${activeStyle.label || activeStyle.name}: ${activeStyle.description}` : 'Stil; tempo, duraklama ve konuşma dilini birlikte ayarlar.'}
                </span>
              </div>
              <div className="row">
                <SelectField name="language" label="Dil" value={settings.language} options={langOptions} onChange={setField} />
                <SelectField name="format" label="Format" value={settings.format} options={FORMAT_OPTIONS} onChange={setField} />
              </div>
              <div className="checklist cols">
                <Check name="breaths" title="Nefes" desc="Cümleler arasında doğal nefes" checked={settings.breaths} missing={f.breaths === false} onChange={setField} />
                <Check name="room_tone" title="Oda tonu" desc="Sıralar arasında dijital sessizlik yerine oda tonu" checked={settings.room_tone} missing={f.room_tone === false} onChange={setField} />
                <Check name="master" title="Mastering" desc="-16 LUFS yayın seviyesi" checked={settings.master} missing={f.master === false} onChange={setField} />
                <Check name="consistency" title="Tutarlılık" desc="Parçalar arası tını ve ses seviyesi eşleme" checked={settings.consistency} missing={f.consistency === false} onChange={setField} />
                <Check name="qc" title="Kalite kontrol" desc="Takılan, tekrarlayan parçayı yeniden üretir" checked={settings.qc} missing={f.qc === false} onChange={setField} />
                <Check name="subtitles" title="Altyazı üret" desc="SRT / VTT olarak indirilebilir" checked={settings.subtitles} missing={f.subtitles === false} onChange={setField} />
                <Check name="fillers" title="Dolgu sözcükleri" desc="“yani”, “hani”, “şey” — sohbet havası (haber, belgesel, sesli kitap ve eğitim stillerinde eklenmez)" checked={settings.fillers} missing={f.fillers === false} onChange={setField} />
                <Check name="chat_speak" title="Sohbet kısaltmaları" desc="slm → selam, tşk → teşekkürler, nbr → naber" checked={settings.chat_speak} missing={f.lexicon === false} onChange={setField} />
              </div>
            </div>
          </details>

          {finalText !== text && (
            <details className="chunks">
              <summary className="muted small">Sunucuya gidecek metin (varsayılan duygular eklenmiş)</summary>
              <p className="quote small">{finalText}</p>
            </details>
          )}

          {dialogOff && <div className="alert error" role="alert">Bu sunucu sürümü diyalog modunu desteklemiyor; sunucuyu güncelleyin.</div>}
          {tooFew && text.trim() && <div className="alert warn" role="status">{tooFewMsg}</div>}
          {!tooFew && unmapped.length > 0 && (
            <div className="alert info" role="status">
              Sesi seçilmemiş: <b>{unmapped.join(', ')}</b> — varsayılan model sesiyle okunur. İstersen "Otomatik eşle"yi kullan.
            </div>
          )}
          {overLimit && (
            <div className="alert error" role="alert">
              Eklenen duygu etiketleriyle metin {finalText.length} karakter oluyor (sınır {maxChars}). Metni kısaltın ya da bazı varsayılan duyguları kaldırın.
            </div>
          )}

          <GenerateBar busy={busy} job={job} startedAt={startedAt} disabled={!canGenerate} onCancel={cancel} />
        </form>
      </section>

      <section className="card" aria-labelledby={rightId} aria-busy={busy}>
        <h2 id={rightId}>Sonuç</h2>
        {busy ? (
          partial.length > 0 ? (
            <PartialPreview parts={partial} total={job?.total || 0} colors={runColors} onActiveChange={setChainActive} />
          ) : (
            <p className="muted">Üretim sürüyor… İlk parça hazır olunca buradan dinlemeye başlayabilirsin.</p>
          )
        ) : result ? (
          <DialogResult key={result.gen.id} result={result} autoPlay={resultAutoPlay} notify={notifyLatest} />
        ) : (
          <div className="stack tight">
            <p className="muted">Üretilen diyalog burada görünecek. Sıralar listesinden istediğin repliğe atlayabilirsin.</p>
            <ul className="muted small dialog-help">
              <li><code>Ayşe: Selam!</code> — satır başında ad ve iki nokta (ya da <code>Ayşe — Selam!</code>)</li>
              <li><code>[ses:Mehmet] İyiyim.</code> — aynı satırda konuşmacı değiştirir</li>
              <li><code>Ayşe (gülerek): …</code> — yönerge etikete çevrilir; <code>(Kapı çalar.)</code> gibi sahne notları okunmaz</li>
              <li><code>[gülme]</code>, <code>[üzgün]</code>, <code>[hız:0.9]</code> — etiketler her sırada çalışır</li>
            </ul>
          </div>
        )}
      </section>
    </div>
  )
}
