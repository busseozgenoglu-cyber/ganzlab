import { Fragment, memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import Player, { fmtDur } from './Player'
// Player'ın isteğe bağlı "aynı anda tek oynatıcı" yolu (playerBus / stopAllPlayers); yoksa sessizce atlanır.
import * as PlayerModule from './Player'

// ─────────────────────────────────────────────────────────── sabitler ──

const STORAGE_KEY = 'sesklon_generate_v4'
const LEGACY_STORAGE_KEYS = ['sesklon_generate_v3'] // ilk açılışta okunur, v4 anahtarına taşınır ve silinir
const CHARS_PER_SEC = 14 // Türkçe için kaba konuşma hızı (karakter / sn)
const LETTERS = ['A', 'B', 'C', 'D']

const DEFAULT_TEXT = `[heyecanlı] Selam millet! Bugün size çok güzel bir şey göstereceğim. Hem de Türkçe!
[sakin] Peki nasıl çalışıyor? On saniyelik bir kayıt yüklüyorsunuz... ve bitti.
[üzgün] Eskiden bunun için aylarca uğraşırdık, maalesef.
[heyecanlı] Ama artık öyle değil. Hazırsanız başlıyoruz!`

const EXAMPLES = [
  {
    id: 'sohbet', label: 'Sohbet', style: 'sohbet',
    text: `[samimi] Selam! Nasılsın, ne var ne yok? [gülme] Valla ben de tam seni arayacaktım.
Bu akşam bir şeyler yapalım mı? [hmm] Şu yeni açılan kafeye gidebiliriz... Ne dersin?`,
  },
  {
    id: 'reklam', label: 'Reklam', style: 'reklam',
    text: `[heyecanlı] Yaz indirimi başladı! Tüm ürünlerde yarı yarıya fırsatlar sizi bekliyor.
[vurgulu] Üstelik kargo bedava! [duraklama] Kampanya yalnızca 3 gün sürecek. [mutlu] Hemen şimdi sipariş verin!`,
  },
  {
    id: 'masal', label: 'Masal', style: 'masal',
    text: `[sakin] Bir varmış, bir yokmuş... Evvel zaman içinde, uzak bir köyde meraklı bir tilki yaşarmış. [1.5 sn]
[fısıltı] Bir gece ormandan tuhaf bir ses gelmiş. [şaşkın] Tilki kulaklarını dikmiş: "Kim var orada?"`,
  },
  {
    id: 'haber', label: 'Haber', style: 'haber',
    text: `[ciddi] İyi akşamlar, ana haber bültenine hoş geldiniz. İstanbul'da sabah saatlerinde başlayan sağanak yağış, trafiği olumsuz etkiledi.
[duraklama] Meteoroloji, hafta sonundan itibaren havanın ısınacağını bildirdi.`,
  },
  {
    id: 'duygusal', label: 'Duygusal', style: 'duygusal',
    text: `[üzgün] Seni ne çok özledim, bilemezsin... [iç çekme] Bazen eski fotoğraflarımıza bakıyorum; zaman ne çabuk geçmiş.
[samimi] Ama biliyorum, bir gün yine o bahçede oturup çay içeceğiz. [mutlu] Söz veriyorum.`,
  },
]

// Stil + doğallık + ince ayar (seed hariç; seed kalıcı tutulmaz)
const DEFAULTS = {
  style: null,
  exaggeration: 0.5, cfg_weight: 0.45, temperature: 0.8, speed: 1.0,
  pause_scale: 1.0, colloquial: 'light', breaths: true, room_tone: true, master: true,
  punctuation_emotion: true, auto_emotion: false, emotion: '', emotion_fx: 'off',
  // v4: metin ve kalite katmanları (docs/SOZLESME2.md §9)
  chat_speak: true, fillers: false, consistency: true, qc: true, subtitles: true,
  format: 'mp3', variants: 1,
}
// Konuşma dolguları bu stillerde sunucuda hiç eklenmez (lexicon.add_fillers) — seçenek devre dışı gösterilir.
const FILLER_OFF_STYLES = new Set(['haber', 'belgesel', 'sesli-kitap', 'eğitim'])
const LIMITS = {
  exaggeration: [0, 1.5], cfg_weight: [0, 1], temperature: [0.05, 2], speed: [0.7, 1.3],
  pause_scale: [0.5, 2], variants: [1, 4],
}
// Stilin belirlediği alanlar — biri stilden farklıysa stil "özelleştirilmiş" sayılır
const STYLE_FIELDS = ['exaggeration', 'cfg_weight', 'temperature', 'speed', 'pause_scale', 'colloquial',
  'breaths', 'punctuation_emotion', 'auto_emotion', 'emotion']

const DEFAULT_LEVELS = ['off', 'light', 'full']
const COLLOQUIAL_LABELS = {
  off: 'Kapalı — yazıldığı gibi',
  light: 'Hafif — gelicem, bişey',
  full: 'Tam — geliyo, diil, böle',
}
const FX_OPTIONS = [
  ['off', 'Kapalı — en doğal (önerilen)'],
  ['light', 'Hafif — şiddet farkları'],
  ['full', 'Tam — perde/tempo/fısıltı (deneysel)'],
]
const FX_VALUES = FX_OPTIONS.map(([v]) => v)
const FORMAT_OPTIONS = [['mp3', 'MP3'], ['wav', 'WAV']]
const VARIANT_OPTIONS = [['1', '1 — tek sonuç'], ['2', '2 varyant'], ['3', '3 varyant'], ['4', '4 varyant']]

// Etiket kutusu: sunucu ayrıntı vermezse kullanılacak / tercih edilen Türkçe adlar
const PREF_NONVERBAL = ['gülme', 'kahkaha', 'kıkırdama', 'iç çekme', 'hmm', 'of', 'şaşırır', 'ağlar', 'öksürür',
  'boğaz temizler', 'esner', 'tüh', 'aman', 'ay', 'oh', 'hıh', 'hah', 'hişt', 'pöf', 'mmm', 'vay', 'evet evet', 'yok ya',
  'cık', 'ıslık', 'nefes verir', 'burnunu çeker', 'hıçkırır', 'dolgu', 'şey', 'lezzet']
const PREF_PAUSES = ['nefes', 'kısa duraklama', 'duraklama', 'uzun duraklama', 'derin nefes', 'sessizlik']
const FALLBACK_PAUSE_MS = { nefes: 500, duraklama: 800, 'uzun duraklama': 1500 }
// Arayüz Türkçe kalsın: İngilizce eş adları etiket kutusunda gösterme (sunucu yine anlar).
// Liste + kural: Türkçe harf içermeyen ve bilinen İngilizce sözcüklerle yazılan etiketler gizlenir.
const EN_TAGS = new Set(['laughs', 'laugh', 'chuckles', 'chuckle', 'giggles', 'giggle', 'sighs', 'sigh', 'wow', 'cries',
  'cry', 'coughs', 'cough', 'clears throat', 'yawns', 'yawn', 'breath', 'takes a breath', 'pause', 'long pause', '...',
  'gasp', 'gasps', 'groan', 'groans', 'hum', 'hums', 'whistles', 'whistle', 'exhales', 'exhale', 'sniff', 'sniffs',
  'haha', 'hihi', 'short pause', 'deep breath', 'silence', 'breathes', 'inhales', 'inhale', 'ugh', 'oops', 'phew',
  'yay', 'ahem', 'hmph', 'ouch', 'tsk', 'sobs', 'sob', 'snorts', 'snort', 'moans', 'moan', 'mumbles', 'mumble',
  'laughs hard', 'uh huh', 'uh', 'um', 'yum', 'ee', 'thinks', 'laughing'])
const isEnglishTag = (tag) => EN_TAGS.has(tag) || (!/[çğıöşüâîû]/i.test(tag) && /\b(?:th|wh|sh|ck|ee|oo|ea|ou|gh|ph|ing|es|ly)\b|[wqx]|ing$|es$|s$/.test(tag) && !/^(?:hmm+|mmm+|of+|oh+|ay|hah|hıh|cık|pst|şşş)$/.test(tag))

const TAG_RE = /\[([^\]\n]{1,40})\]/g
const NUM_TAG_RE = /^(\d+(?:[.,]\d+)?)\s*(ms|sn|saniye|s)$/

// Duygu yoğunluğu (sözleşme §3): [biraz X]/[hafif X] ≈×0,65 · [çok X] ≈×1,35 · [aşırı X] ≈×1,6 · ya da [X:1|2|3], [X %150].
// Sunucudaki yoğunluk sözcükleri (emotion.INTENSITY_WORDS) — en uzun önce; etiket yeniden yazılırken atılır.
const INTENSITY_QUALIFIERS = ['son derece', 'çok çok', 'birazcık', 'extremely', 'hafifçe', 'oldukça', 'slightly', 'azıcık', 'a bit',
  'biraz', 'hafif', 'aşırı', 'epey', 'very', 'çok', 'az']
const INTENSITY_LEVELS = [
  { word: 'biraz', label: 'biraz', title: 'Hafif şiddet (≈ ×0,65): [biraz heyecanlı]' },
  { word: '', label: 'normal', title: 'Varsayılan şiddet — öneki kaldırır: [heyecanlı]' },
  { word: 'çok', label: 'çok', title: 'Güçlü şiddet (≈ ×1,35): [çok heyecanlı]' },
]
// health.tags.arcs / tags.controls gelmezse
const FALLBACK_ARCS = [
  { tag: 'sakinleşerek', to: 'sakin' }, { tag: 'heyecanlanarak', to: 'heyecanlı' }, { tag: 'yumuşayarak', to: 'samimi' },
  { tag: 'sertleşerek', to: 'kızgın' }, { tag: 'hüzünlenerek', to: 'üzgün' },
]
const FALLBACK_CONTROLS = [{ tag: 'hız:0.9', label: 'Hız' }, { tag: 'perde:+1', label: 'Perde' }]
// Sayısal satır içi kontroller (emotion._CONTROL_LABELS). "[ses:Ad]" konuşmacı kontrolüdür → Diyalog sekmesinde.
const CONTROL_KINDS = { 'hız': 'rate', 'tempo': 'rate', 'perde': 'pitch', 'pitch': 'pitch' }
const CONTROL_SPECS = {
  rate: { min: 0.7, max: 1.3, step: 0.05, def: '0.9', signed: false, hint: 'Konuşma hızı: 0.7 (yavaş) – 1.3 (hızlı)' },
  pitch: { min: -4, max: 4, step: 0.5, def: '+1', signed: true, hint: 'Ses perdesi, yarım ton: −4 (kalın) … +4 (ince)' },
}
const ANY_TAG_RE = /\[([^\[\]\n]{1,200})\]/g
const NUM_SUFFIX_RE = /^\s*[+-]?\d+(?:[.,]\d+)?\s*$/
const PCT_TAIL_RE = /\s*%\s*\d+(?:[.,]\d+)?\s*$/
const PCT_HEAD_RE = /^\s*%\s*\d+(?:[.,]\d+)?\s+/
const ASCII_FOLD = { ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u', â: 'a', î: 'i', û: 'u' }
const READING_BLOCK_RE = /^\{([^{}|\n]+)(?:\|([^{}\n]*))?\}$/
const WORD_CH_RE = /[\p{L}\p{N}_]/u
const EDGE_CH_RE = /[\s.,;:!?…"“”'‘’()«»–—-]/u
const EMPHASIS_MAX = 60 // sunucudaki *…* deseninin üst sınırı

const QC_OK = 60 // qc.check_chunk: score ≥ 60 → kabul
const SUB_FORMATS = [['srt', 'SRT'], ['vtt', 'VTT'], ['json', 'JSON']]

// ─────────────────────────────────────────────────────────── yardımcılar ──

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
const trLower = (s) => String(s).toLocaleLowerCase('tr')
const fmtNum = (n) => String(Math.round(n * 10) / 10)
const seedOf = (g) => g?.seed ?? g?.params?.seed ?? null
const isCancelledError = (err) =>
  (typeof api.isCancelled === 'function' && api.isCancelled(err)) || err?.name === 'CancelledError' || err?.cancelled === true
const capFirst = (s) => (s ? s.charAt(0).toLocaleUpperCase('tr') + s.slice(1) : '')
const round2 = (n) => Math.round(n * 100) / 100

/** Sohbet kısaltmaları ayrı bayrakla bildirilmezse sözlük modülüyle birlikte gelir. */
const chatSpeakAvailable = (f) => (f.chat_speak !== undefined ? f.chat_speak !== false : f.lexicon !== false)

/** Ses örneğinin türü: "nonverbal" (gerçek tepki) ya da "emotion" (duygu kaydı). */
function sampleKind(s) {
  if (s?.kind === 'nonverbal' || s?.kind === 'emotion') return s.kind
  return typeof s?.emotion === 'string' && s.emotion.startsWith('nv:') ? 'nonverbal' : 'emotion'
}
const sampleKey = (s) => String(s?.emotion ?? '').replace(/^nv:/, '')

function countSamples(samples) {
  let emotion = 0
  let nonverbal = 0
  for (const s of samples || []) {
    if (sampleKind(s) === 'nonverbal') nonverbal++
    else emotion++
  }
  return { emotion, nonverbal }
}

/** Sunucudaki fold_ascii gibi: küçük harf + Türkçe harfler ASCII'ye ("Heyecanlı" → "heyecanli"). Uzunluk değişmez. */
const foldAscii = (s) => trLower(s).replace(/[çğıöşüâîû]/g, (ch) => ASCII_FOLD[ch])

/** Duygu adı ve eş adları (küçük harf ve ASCII karşılığı) → duygu adı. "normal" yoğunluk almaz. */
function buildEmotionIndex(emotions) {
  const m = new Map()
  for (const e of emotions) {
    if (!e?.name || e.name === 'normal') continue
    for (const k of [e.name, ...(Array.isArray(e.aliases) ? e.aliases : [])]) {
      const raw = String(k).trim()
      for (const key of [trLower(raw), foldAscii(raw)]) if (key && !m.has(key)) m.set(key, e.name)
    }
  }
  return m
}

const isEmotionName = (s, index) => index.has(trLower(s)) || index.has(foldAscii(s))

/** Baştaki yoğunluk sözcüğünü atar: "çok çok üzgün" → "üzgün". */
function stripQualifier(head) {
  const folded = foldAscii(head)
  for (const q of INTENSITY_QUALIFIERS) {
    const prefix = `${foldAscii(q)} `
    if (folded.startsWith(prefix)) return head.slice(prefix.length).trim()
  }
  return head
}

/**
 * Köşeli parantez içini duygu etiketi olarak çözer: "biraz heyecanlı", "heyecanlı:3", "heyecanlı %150",
 * "heyecanlı: kapsamlı metin", "çok üzgün+umutlu". Duygu değilse (duraklama, kontrol, geçiş, sözsüz…) null.
 * Dönüş: { core: yoğunluksuz duygu ifadesi, tail: kapsamlı etiketin ": metin" kısmı }
 */
function parseEmotionInner(inner, index) {
  let head = inner
  let tail = ''
  const colon = inner.indexOf(':')
  if (colon >= 0) {
    head = inner.slice(0, colon)
    // [heyecanlı:3] sayısal yoğunluk → atılır (yerine önek gelecek); [heyecanlı: metin] kapsamlı → korunur
    if (!NUM_SUFFIX_RE.test(inner.slice(colon + 1))) tail = inner.slice(colon)
  }
  head = stripQualifier(head.replace(PCT_TAIL_RE, '').replace(PCT_HEAD_RE, '').trim())
  if (!head || /→|->/.test(head)) return null // [heyecanlı→sakin] geçiş etiketi
  const first = head.split('+')[0].trim()
  return isEmotionName(first, index) ? { core: head, tail } : null
}

/** İmleçten önceki (ya da imlecin içinde olduğu) son duygu etiketi: { core, tail, start, end, raw } | null */
function findEmotionTagBefore(text, caret, index) {
  let found = null
  for (const m of text.matchAll(ANY_TAG_RE)) {
    if (m.index >= caret) break
    const p = parseEmotionInner(m[1], index)
    if (p) found = { ...p, start: m.index, end: m.index + m[0].length, raw: m[0] }
  }
  return found
}

const emotionTagWith = (p, word) => `[${word ? `${word} ` : ''}${p.core}${p.tail}]`

const isWordCh = (ch) => Boolean(ch) && WORD_CH_RE.test(ch)

/**
 * Seçimi sözcük sınırlarına oturtur: kenardaki boşluk/noktalama atılır, yarım kalan sözcük tamamlanır.
 * Seçim yoksa imlecin üzerindeki sözcük. Uygun aralık yoksa null.
 */
function wordRange(text, start, end) {
  let s = start
  let e = end
  if (s === e) {
    while (s > 0 && isWordCh(text[s - 1])) s--
    while (e < text.length && isWordCh(text[e])) e++
    return s < e ? [s, e] : null
  }
  while (s < e && EDGE_CH_RE.test(text[s])) s++
  while (e > s && EDGE_CH_RE.test(text[e - 1])) e--
  if (s >= e) return null
  while (s > 0 && isWordCh(text[s - 1]) && isWordCh(text[s])) s--
  while (e < text.length && isWordCh(text[e - 1]) && isWordCh(text[e])) e++
  return [s, e]
}

/** [s, e) aralığını saran tek satırlık open…close bloğunun sınırları ([a, b) — parantezler dahil) ya da null. */
function enclosingBlock(text, s, e, open, close) {
  if (s <= 0) return null
  const a = text.lastIndexOf(open, s - 1)
  if (a < 0 || text.lastIndexOf(close, s - 1) > a) return null
  const b = text.indexOf(close, e)
  if (b < 0) return null
  const nextOpen = text.indexOf(open, e)
  if (nextOpen >= 0 && nextOpen < b) return null
  if (text.slice(a, b).includes('\n')) return null
  return [a, b + 1]
}

function fmtControl(spec, n) {
  const r = round2(n)
  return spec.signed && r > 0 ? `+${r}` : String(r)
}

/** "+1.2 dB" / "−1.2 dB" (eksi işareti U+2212) */
function signedDb(n) {
  const r = Math.round(Number(n) * 10) / 10
  if (!Number.isFinite(r) || r === 0) return '0 dB'
  return `${r > 0 ? '+' : '−'}${Math.abs(r)} dB`
}

// Kalite kontrol (params.qc) yardımcıları
const qcScore = (q) => {
  const n = Number(q?.score)
  return q?.score != null && Number.isFinite(n) ? n : null
}
const qcLow = (q) => {
  const s = qcScore(q)
  return (s != null && s < QC_OK) || q?.ok === false
}
const qcRetried = (q) =>
  q?.retried === true || Number(q?.retries) > 0 || Number(q?.attempts) > 1 || /^retry/.test(String(q?.decision || ''))
function qcByIndex(qc) {
  const m = new Map()
  ;(Array.isArray(qc) ? qc : []).forEach((q, i) => {
    if (q && typeof q === 'object') m.set(Number.isInteger(q.index) ? q.index : i, q)
  })
  return m
}

function fmtSecs(s) {
  const t = Math.max(0, Math.round(s))
  if (t < 60) return `${Math.max(1, t)} sn`
  const m = Math.floor(t / 60)
  const r = t % 60
  return r ? `${m} dk ${r} sn` : `${m} dk`
}

function extOf(nameOrUrl, fallback = 'wav') {
  const m = /\.([a-z0-9]{2,4})(?:$|\?)/i.exec(nameOrUrl || '')
  return m ? m[1].toLowerCase() : fallback
}

function parseSeed(s) {
  if (s === '' || s == null) return null
  const n = Number.parseInt(String(s), 10)
  return Number.isFinite(n) ? n : null
}

function normColloquial(v) {
  if (v === true) return 'light'
  if (v === false || v == null || v === '') return 'off'
  return String(v)
}

/** Stil sözlüğünden arayüz ayarlarına (eksik alanlar varsayılanla). */
function styleValues(st) {
  const num = (v, d) => (typeof v === 'number' && Number.isFinite(v) ? v : d)
  const bool = (v, d) => (typeof v === 'boolean' ? v : d)
  const emotion = typeof st.emotion === 'string' && st.emotion !== 'normal' ? st.emotion : ''
  return {
    exaggeration: num(st.exaggeration, DEFAULTS.exaggeration),
    cfg_weight: num(st.cfg_weight, DEFAULTS.cfg_weight),
    temperature: num(st.temperature, DEFAULTS.temperature),
    speed: num(st.speed, DEFAULTS.speed),
    pause_scale: num(st.pause_scale, DEFAULTS.pause_scale),
    colloquial: normColloquial(st.colloquial ?? DEFAULTS.colloquial),
    breaths: bool(st.breaths, DEFAULTS.breaths),
    punctuation_emotion: bool(st.punctuation_emotion, DEFAULTS.punctuation_emotion),
    auto_emotion: bool(st.auto_emotion, DEFAULTS.auto_emotion),
    emotion,
  }
}

function isCustomized(settings, st) {
  if (!st) return false
  const v = styleValues(st)
  return STYLE_FIELDS.some((k) => {
    const a = settings[k]
    const b = v[k]
    return typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) > 1e-6 : a !== b
  })
}

function sanitizeSettings(raw) {
  const s = { ...DEFAULTS }
  if (!raw || typeof raw !== 'object') return s
  for (const [k, d] of Object.entries(DEFAULTS)) {
    const v = raw[k]
    if (v === undefined) continue
    if (k === 'style') s.style = typeof v === 'string' && v ? v : null
    else if (k === 'colloquial') s.colloquial = normColloquial(v)
    else if (typeof d === 'number') { const n = Number(v); if (Number.isFinite(n)) s[k] = n }
    else if (typeof d === 'boolean') { if (typeof v === 'boolean') s[k] = v }
    else if (typeof d === 'string' && typeof v === 'string') s[k] = v
  }
  for (const [k, [lo, hi]] of Object.entries(LIMITS)) s[k] = clamp(s[k], lo, hi)
  s.variants = Math.round(s.variants)
  if (!FORMAT_OPTIONS.some(([v]) => v === s.format)) s.format = DEFAULTS.format
  if (!FX_VALUES.includes(s.emotion_fx)) s.emotion_fx = DEFAULTS.emotion_fx
  if (s.emotion === 'normal') s.emotion = ''
  return s
}

function sanitizeUi(raw) {
  const u = { tags: true, natural: true, advanced: false }
  if (raw && typeof raw === 'object') for (const k of Object.keys(u)) if (typeof raw[k] === 'boolean') u[k] = raw[k]
  return u
}

/** Kayıtlı durumu okur; yalnızca eski (v3) kayıt varsa onu v4 anahtarına taşır. Yeni alanlar varsayılanla dolar. */
function loadSaved() {
  for (const key of [STORAGE_KEY, ...LEGACY_STORAGE_KEYS]) {
    let data = null
    try {
      const raw = localStorage.getItem(key)
      data = raw ? JSON.parse(raw) : null
    } catch {
      data = null // bozuk kayıt ya da depolama kapalı: sıradakine bak
    }
    if (!data || typeof data !== 'object') continue
    if (key !== STORAGE_KEY) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...data, v: 4 }))
        localStorage.removeItem(key)
      } catch { /* taşınamazsa bir sonraki kayıtta yazılır */ }
    }
    return data
  }
  return null
}

function saveState(data) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)) } catch { /* depolama kapalı olabilir */ }
}

/** Kaba süre tahmini: etiketsiz metin / 14 kar/sn / hız + duraklama etiketleri × duraklama çarpanı. */
function estimateSeconds(text, speed, pauseScale, pauseMs) {
  let pauses = 0
  const plain = text.replace(TAG_RE, (_, inner) => {
    const t = trLower(inner.trim())
    const m = NUM_TAG_RE.exec(t)
    if (m) {
      const n = Number.parseFloat(m[1].replace(',', '.'))
      pauses += m[2] === 'ms' ? n / 1000 : n
    } else if (pauseMs[t]) {
      pauses += pauseMs[t] / 1000
    }
    return ' '
  })
  const chars = plain.replace(/\s+/g, ' ').trim().length
  if (!chars) return 0
  return chars / CHARS_PER_SEC / (speed || 1) + pauses * (pauseScale || 1)
}

function progressText(job, elapsed) {
  if (!job) return 'Gönderiliyor…'
  if (job.status === 'queued') {
    return Number.isFinite(job.position) && job.position > 0
      ? `Sırada bekliyor — ${job.position}. sıradasın`
      : 'Sırada bekliyor…'
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

function voiceOptionLabel(v) {
  const bits = []
  const q = v.analysis?.quality_score
  if (Number.isFinite(q)) bits.push(`★ ${Math.round(q)}`)
  const n = countSamples(v.samples)
  if (n.emotion) bits.push(`${n.emotion} duygu kaydı`)
  if (n.nonverbal) bits.push(`${n.nonverbal} tepki`)
  return bits.length ? `${v.name} (${bits.join(' • ')})` : v.name
}

function genMeta(g, languages) {
  const bits = []
  if (g.voice_name) bits.push(g.voice_name)
  if (g.language) bits.push(languages[g.language] || g.language)
  if (Number.isFinite(g.duration)) bits.push(fmtDur(g.duration))
  const seed = seedOf(g)
  if (seed != null) bits.push(`tohum ${seed}`)
  const lufs = g.params?.loudness?.lufs
  if (Number.isFinite(lufs)) bits.push(`${lufs.toFixed(1)} LUFS`)
  if (Number.isFinite(g.elapsed)) bits.push(`${g.elapsed.toFixed(1)} sn'de üretildi`)
  return bits.join(' • ')
}

/** Aynı okunuşa / süreye sahip eş adları tekilleştirir; tercih edilen Türkçe adları öne alır. */
function pickTags(items, groupOf, preferred) {
  const groups = new Map()
  for (const it of items) {
    const tag = typeof it?.tag === 'string' ? it.tag.trim() : ''
    if (!tag || isEnglishTag(tag)) continue
    const key = groupOf(it)
    const cur = groups.get(key)
    if (!cur || (preferred.includes(tag) && !preferred.includes(cur.tag))) groups.set(key, { ...it, tag })
  }
  const rank = (t) => { const i = preferred.indexOf(t.tag); return i < 0 ? preferred.length : i }
  return [...groups.values()].sort((a, b) => rank(a) - rank(b))
}

function buildCatalog(h) {
  const tags = (h && h.tags) || {}
  let nonverbal
  if (Array.isArray(tags.nonverbal_detail)) {
    nonverbal = pickTags(tags.nonverbal_detail.filter((x) => x && x.reads !== ''), (x) => String(x.reads ?? x.tag), PREF_NONVERBAL)
  } else {
    const list = Array.isArray(tags.nonverbal) ? tags.nonverbal : []
    nonverbal = PREF_NONVERBAL.filter((t) => !list.length || list.includes(t)).map((tag) => ({ tag }))
  }
  const pauseMs = { ...FALLBACK_PAUSE_MS }
  let pauses
  if (Array.isArray(tags.pause_detail)) {
    for (const p of tags.pause_detail) if (p?.tag && Number.isFinite(p.ms)) pauseMs[trLower(p.tag)] = p.ms
    pauses = pickTags(tags.pause_detail, (x) => String(x.ms ?? x.tag), PREF_PAUSES)
  } else {
    const list = Array.isArray(tags.pauses) ? tags.pauses : []
    pauses = PREF_PAUSES.filter((t) => !list.length || list.includes(t)).map((tag) => ({ tag, ms: FALLBACK_PAUSE_MS[tag] }))
  }
  const bare = (t) => String(t).trim().replace(/^\[|\]$/g, '').split(':')[0].trim()
  const arcs = Array.isArray(tags.arcs)
    ? tags.arcs.filter((a) => a && typeof a.tag === 'string' && bare(a.tag))
      .map((a) => ({ tag: bare(a.tag), to: typeof a.to === 'string' ? a.to : '' }))
    : FALLBACK_ARCS
  // Kontroller: {tag: "hız:0.9", label} → { tag: "hız", kind: "rate", def: "0.9" }; sayısal olmayanlar (ses:Ad) atlanır
  const controls = []
  for (const c of Array.isArray(tags.controls) ? tags.controls : FALLBACK_CONTROLS) {
    const raw = c && typeof c.tag === 'string' ? c.tag.trim().replace(/^\[|\]$/g, '') : ''
    const tag = bare(raw)
    const kind = CONTROL_KINDS[trLower(tag)]
    if (!kind || controls.some((x) => x.kind === kind)) continue
    const example = raw.includes(':') ? raw.slice(raw.indexOf(':') + 1).trim() : ''
    const def = NUM_SUFFIX_RE.test(example) ? example : CONTROL_SPECS[kind].def
    controls.push({ tag, kind, def, label: typeof c.label === 'string' && c.label ? c.label : capFirst(tag) })
  }
  // Sayısal yoğunluk ipucu: [{suffix: ":1", label: "hafif"}, …] — yalnızca ":N" biçimindekiler gösterilir
  const intensity = (Array.isArray(tags.intensity) ? tags.intensity : [])
    .filter((i) => i && (typeof i.suffix === 'string' || typeof i.suffix === 'number') && typeof i.label === 'string')
    .map((i) => ({ suffix: /^\d/.test(String(i.suffix)) ? `:${i.suffix}` : String(i.suffix), label: i.label }))
    .filter((i) => i.suffix.startsWith(':'))
  return {
    styles: Array.isArray(h?.styles) ? h.styles.filter((s) => s && typeof s.name === 'string') : [],
    levels: Array.isArray(h?.colloquial_levels) && h.colloquial_levels.length ? h.colloquial_levels : DEFAULT_LEVELS,
    features: (h && h.features) || {},
    emotions: Array.isArray(tags.emotions) ? tags.emotions.filter((e) => e && e.name) : [],
    nonverbal,
    pauses,
    pauseMs,
    arcs,
    controls,
    intensity,
  }
}

// ─────────────────────────────────────────────────────────── hook'lar ──

/** Kimliği hiç değişmeyen ama her zaman son hâli çağıran geri çağırım (memo'lu çocuklar için). */
function useLatest(fn) {
  const ref = useRef(fn)
  useLayoutEffect(() => { ref.current = fn })
  return useCallback((...args) => ref.current(...args), [])
}

/** İçerik aynı kaldıkça aynı nesneyi döndürür (health 15 sn'de bir yeniden geliyor). */
function useStableJson(value) {
  const key = JSON.stringify(value ?? null)
  return useMemo(() => JSON.parse(key), [key])
}

function useCatalog(health) {
  const key = useMemo(() => JSON.stringify({
    styles: health?.styles ?? null,
    colloquial_levels: health?.colloquial_levels ?? null,
    features: health?.features ?? null,
    tags: health?.tags ?? null,
  }), [health])
  return useMemo(() => buildCatalog(JSON.parse(key)), [key])
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
    if (i >= list.length) { // sıradaki parça henüz yok — gelince devam
      setState({ active: true, index: i, waiting: true })
      return
    }
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

const RangeField = memo(function RangeField({ name, label, value, min, max, step = 0.05, unit = '', hint, onChange }) {
  const id = useId()
  const display = `${Number(value).toFixed(2)}${unit}`
  return (
    <label htmlFor={id}>
      <span id={`${id}l`}>{label}: <b>{display}</b></span>
      <input id={id} type="range" min={min} max={max} step={step} value={value}
        aria-labelledby={`${id}l`} aria-describedby={hint ? `${id}h` : undefined} aria-valuetext={display}
        onChange={(e) => onChange(name, Number(e.target.value))} />
      {hint && <span id={`${id}h`} className="muted small">{hint}</span>}
    </label>
  )
})

const SelectField = memo(function SelectField({ name, label, value, options, hint, numeric = false, className, onChange }) {
  const id = useId()
  return (
    <label htmlFor={id} className={className}>
      <span id={`${id}l`}>{label}</span>
      <select id={id} value={value} aria-labelledby={`${id}l`} aria-describedby={hint ? `${id}h` : undefined}
        onChange={(e) => onChange(name, numeric ? Number(e.target.value) : e.target.value)}>
        {options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
      {hint && <span id={`${id}h`} className="muted small">{hint}</span>}
    </label>
  )
})

const Check = memo(function Check({ name, title, desc, note, checked, disabled, onChange }) {
  const id = useId()
  return (
    <label className="check" htmlFor={id}>
      <input id={id} type="checkbox" checked={Boolean(checked)} disabled={disabled}
        onChange={(e) => onChange(name, e.target.checked)} />
      <span><b>{title}</b> <span className="muted small">— {desc}{note ? ` (${note})` : ''}</span></span>
    </label>
  )
})

function TagGroup({ title, desc, children }) {
  const id = useId()
  return (
    <div className="taggroup" role="group" aria-labelledby={`${id}t`} aria-describedby={desc ? `${id}d` : undefined}>
      <span className="small">
        <b id={`${id}t`}>{title}</b>
        {desc && <span id={`${id}d`} className="muted"> — {desc}</span>}
      </span>
      <div className="presets">{children}</div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────── alt bileşenler ──

const StyleChips = memo(function StyleChips({ styles, active, customized, onSelect }) {
  const btnRefs = useRef([])
  const descId = useId()
  if (!styles.length) return null
  const activeIdx = styles.findIndex((s) => s.name === active)
  const tabStop = activeIdx >= 0 ? activeIdx : 0
  const current = activeIdx >= 0 ? styles[activeIdx] : null
  const label = current ? current.label || current.name : ''

  // Ok tuşlarıyla chip'ler arasında gezin; Enter/Boşluk seçer (toolbar deseni)
  function onKeyDown(e) {
    const list = btnRefs.current.slice(0, styles.length)
    const i = list.indexOf(e.target)
    if (i < 0) return
    let n = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') n = (i + 1) % list.length
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') n = (i - 1 + list.length) % list.length
    else if (e.key === 'Home') n = 0
    else if (e.key === 'End') n = list.length - 1
    if (n === null) return
    e.preventDefault()
    list[n]?.focus()
    list[n]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }

  let desc = 'Bir stil seç: tüm ayarlar ona göre dolar, sonra dilediğin gibi değiştirebilirsin.'
  if (current && customized) desc = `"${label}" stilinden başlayıp ayarları değiştirdin — stil yine gönderilir, senin değerlerin geçerli olur.`
  else if (current) desc = current.description ? `${label}: ${current.description}` : `${label} stili seçili.`

  return (
    <div className="stack tight">
      <div className="presets style-chips" role="toolbar" aria-label="Stil ön ayarları" aria-describedby={descId} onKeyDown={onKeyDown}>
        {styles.map((s, i) => {
          const on = i === activeIdx
          return (
            <button key={s.name} ref={(el) => { btnRefs.current[i] = el }} type="button"
              className={`chip clickable${on ? ' active' : ''}${on && customized ? ' customized' : ''}`}
              aria-pressed={on} tabIndex={i === tabStop ? 0 : -1} title={s.description || undefined}
              onClick={() => onSelect(s.name)}>
              {s.label || s.name}{on && customized && <span className="small"> · özelleştirilmiş</span>}
            </button>
          )
        })}
      </div>
      <div className="row between">
        <span id={descId} className="muted small" aria-live="polite">{desc}</span>
        {current && customized && (
          <button type="button" className="btn ghost small" onClick={() => onSelect(current.name)}
            aria-label={`${label} stilinin değerlerine geri dön`}>↺ Stile dön</button>
        )}
      </div>
    </div>
  )
})

/** Etiket kutusundaki sayı girişi + "ekle" düğmesi (sayılı duraklama, hız, perde). Enter da ekler. */
function NumberTag({ label, value, onValue, spec, token, onAdd, addLabel }) {
  const id = useId()
  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); if (token) onAdd(token) }
  }
  return (
    <span className="actions tag-control">
      <label className="inline small" htmlFor={id} title={spec.hint || undefined}>
        {label}
        <input id={id} className="num-sm" type="number" min={spec.min} max={spec.max} step={spec.step} value={value}
          onChange={(e) => onValue(e.target.value)} onKeyDown={onKeyDown} />
        {spec.unit}
      </label>
      <button type="button" className="btn ghost small" disabled={!token} onClick={() => onAdd(token)}
        aria-label={token ? addLabel : 'Geçerli bir değer gir'}>
        + {token || '[?]'}
      </button>
    </span>
  )
}

const keepSelection = (e) => e.preventDefault() // tıklayınca odak/seçim metin kutusunda kalsın

const TagBox = memo(function TagBox({ id, catalog, recordedNv, onInsert, onEmotion, onIntensity, onEmphasis, onReading }) {
  const { emotions, nonverbal, pauses, arcs, controls, intensity, features } = catalog
  const showIntensity = features.intensity !== false
  const showEmphasis = features.emphasis !== false
  const showReading = features.lexicon !== false
  const [secs, setSecs] = useState('1.5')
  const [ctl, setCtl] = useState({}) // kontrol etiketi → girilen değer (metin)
  const n = Number.parseFloat(String(secs).replace(',', '.'))
  const value = Number.isFinite(n) && n > 0 ? clamp(Math.round(n * 10) / 10, 0.1, 10) : null
  const hasRealNv = nonverbal.some((t) => recordedNv.has(t.tag))

  return (
    <div className="tagbox" id={id}>
      <div className="muted small">
        İmlecin olduğu yere eklenir. Noktalama da tonu etkiler:
        {' '}<b>!</b> vurgulu, <b>?</b> yükselen ton, <b>...</b> düşünceli.
      </div>
      {emotions.length > 0 && (
        <TagGroup title="Duygu" desc="bir sonraki duygu etiketine kadar sürer">
          {emotions.map((e) => {
            const label = e.label || e.name
            const tip = [e.description, e.aliases?.length ? `Diğer adları: ${e.aliases.slice(0, 5).join(', ')}` : '']
              .filter(Boolean).join(' • ')
            return (
              <button key={e.name} type="button" className="chip clickable" title={tip || undefined}
                aria-label={`Duygu etiketi ekle: ${label}`} onClick={() => onEmotion(e.name)}>[{label}]</button>
            )
          })}
        </TagGroup>
      )}
      {showIntensity && emotions.length > 0 && (
        <TagGroup title="Yoğunluk" desc="imleçten önceki son duygu etiketinin şiddeti; yoksa seçtiğin duyguyla yeni etiket">
          {INTENSITY_LEVELS.map((l) => (
            <button key={l.label} type="button" className="chip clickable" title={l.title} onMouseDown={keepSelection}
              aria-label={`Duygu yoğunluğu: ${l.label}`} onClick={() => onIntensity(l.word)}>
              {l.label}
            </button>
          ))}
          {intensity.length > 0 && (
            <span className="muted small">Sayıyla da: {intensity.map((i) => `[heyecanlı${i.suffix}] ${i.label}`).join(' · ')}</span>
          )}
        </TagGroup>
      )}
      {showIntensity && arcs.length > 0 && (
        <TagGroup title="Geçiş" desc="bölüm boyunca bir tona yavaşça kayar; [heyecanlı→sakin] de yazılabilir">
          {arcs.map((a) => (
            <button key={a.tag} type="button" className="chip clickable"
              title={a.to ? `Bölüm boyunca "${a.to}" tona kayar` : undefined}
              aria-label={`Geçiş etiketi ekle: ${a.tag}`} onClick={() => onInsert(`[${a.tag}]`)}>[{a.tag}]</button>
          ))}
        </TagGroup>
      )}
      {nonverbal.length > 0 && (
        <TagGroup title="Sözsüz"
          desc={hasRealNv ? '✓ olanlarda bu sesin gerçek kaydı çalınır, diğerleri ünleme çevrilip okunur'
            : 'ünleme çevrilip okunur; Sesler sekmesinden kendi gülmeni, iç çekmeni kaydedebilirsin'}>
          {nonverbal.map((t) => {
            const real = recordedNv.has(t.tag)
            const title = real ? 'Bu sesin gerçek kaydı çalınır' : t.reads ? `Okunuşu: “${t.reads}”` : undefined
            return (
              <button key={t.tag} type="button" className={`chip clickable${real ? ' on' : ''}`} title={title}
                aria-label={`Sözsüz etiket ekle: ${t.tag}${real ? ' (gerçek kayıt var)' : ''}`} onClick={() => onInsert(`[${t.tag}]`)}>
                [{t.tag}]{real && ' ✓'}
              </button>
            )
          })}
        </TagGroup>
      )}
      <TagGroup title="Duraklama" desc="o noktada sessizlik">
        {pauses.map((p) => (
          <button key={p.tag} type="button" className="chip clickable"
            title={Number.isFinite(p.ms) ? `${p.ms} ms duraklama` : undefined}
            aria-label={`Duraklama etiketi ekle: ${p.tag}`} onClick={() => onInsert(`[${p.tag}]`)}>
            [{p.tag}]{Number.isFinite(p.ms) && <span className="muted"> {fmtNum(p.ms / 1000)} sn</span>}
          </button>
        ))}
        <NumberTag label="Sayılı" value={secs} onValue={setSecs} spec={{ min: 0.1, max: 10, step: 0.1, unit: 'sn' }}
          token={value != null ? `[${value} sn]` : null} onAdd={onInsert} addLabel={`${value} saniyelik duraklama ekle`} />
      </TagGroup>
      {showIntensity && controls.length > 0 && (
        <TagGroup title="Kontrol" desc={`bulunduğu yerden itibaren geçerli; [${controls[0].tag}:normal] varsayılana döndürür`}>
          {controls.map((c) => {
            const spec = CONTROL_SPECS[c.kind]
            const raw = ctl[c.kind] ?? c.def
            const num = Number.parseFloat(String(raw).replace(',', '.'))
            const ok = Number.isFinite(num) && num >= spec.min && num <= spec.max
            const token = ok ? `[${c.tag}:${fmtControl(spec, num)}]` : null
            return (
              <Fragment key={c.kind}>
                <NumberTag label={c.label} value={raw} spec={spec} token={token} onAdd={onInsert}
                  onValue={(v) => setCtl((s) => ({ ...s, [c.kind]: v }))} addLabel={`${c.label} etiketi ekle: ${token}`} />
                <button type="button" className="chip clickable small" title={`${c.label} varsayılana döner`}
                  aria-label={`${c.label} sıfırlama etiketi ekle`} onClick={() => onInsert(`[${c.tag}:normal]`)}>
                  [{c.tag}:normal]
                </button>
              </Fragment>
            )
          })}
        </TagGroup>
      )}
      {(showEmphasis || showReading) && (
        <TagGroup title="Seçili metin" desc="önce metinde bir sözcük seç (ya da imleci üzerine getir)">
          {showEmphasis && (
            <button type="button" className="chip clickable" onMouseDown={keepSelection} onClick={onEmphasis}
              title="Seçili sözcüğü ya da kısa öbeği vurgular: *çok* önemli. Vurgulu sözcükte yeniden basınca kaldırır.">
              <b>*Vurgu*</b>
            </button>
          )}
          {showReading && (
            <button type="button" className="chip clickable" onMouseDown={keepSelection} onClick={onReading}
              title="Seçili sözcüğün nasıl okunacağını sorar: {Shopify|Şopifay}. Kalıcı okunuşlar için Telaffuz sekmesi.">
              {'{Okunuş}'}
            </button>
          )}
        </TagGroup>
      )}
    </div>
  )
})

const VoiceInfo = memo(function VoiceInfo({ id, voice }) {
  if (!voice) return null
  const a = voice.analysis
  const score = Number.isFinite(a?.quality_score) ? Math.round(a.quality_score) : null
  const grade = a?.grade || null
  const weak = grade === 'zayıf' || (score != null && score < 50)
  const extras = []
  if (a?.f0?.label && a.f0.label !== 'belirsiz') extras.push(`${a.f0.label} sesi`)
  if (a?.speaking_rate?.label) extras.push(`${a.speaking_rate.label} tempo`)
  const samples = countSamples(voice.samples).emotion
  const nvKeys = [...new Set((voice.samples || []).filter((s) => sampleKind(s) === 'nonverbal').map(sampleKey))]
  return (
    <div id={id} className="voice-info">
      {(score != null || grade) && (
        <div className={`small ${weak ? 'warn-text' : 'muted'}`}>
          Kayıt kalitesi: {grade || '—'}{score != null ? ` (${score}/100)` : ''}
          {weak ? ' — Sesler sekmesinden yeniden kaydetmeni öneririm.' : extras.length ? ` • ${extras.join(' • ')}` : ''}
        </div>
      )}
      {samples === 0 && (
        <div className="muted small">
          Bu sesin duygu kaydı yok; duygular yalnızca ayarlarla verilir. Belirgin duygu için "Sesler" sekmesinden o duyguda kayıt ekle.
        </div>
      )}
      {nvKeys.length > 0 && (
        <div className="muted small" title="Bu etiketlerde modelin ünlemi yerine sesin kendi kaydı çalınır">
          Gerçek tepkiler: {nvKeys.slice(0, 8).map((k) => `[${k}]`).join(' ')}{nvKeys.length > 8 ? ` +${nvKeys.length - 8}` : ''}
        </div>
      )}
    </div>
  )
})

const NaturalnessPanel = memo(function NaturalnessPanel({ settings, levels, features, language, voicePauseScale, fillersBlockedBy,
  open, onToggle, onChange }) {
  const levelOptions = useMemo(() => {
    const list = levels.includes(settings.colloquial) ? levels : [...levels, settings.colloquial]
    return list.map((l) => [l, COLLOQUIAL_LABELS[l] || l])
  }, [levels, settings.colloquial])
  const missing = (k) => features[k] === false
  const shown = (k) => features[k] !== false // v4 seçenekleri: sunucu "yok" derse hiç gösterilmez
  const note = (k) => (missing(k) ? 'bu sunucuda yok' : '')
  const trNote = language !== 'tr' ? 'yalnızca Türkçe metinde' : ''
  const chatOk = chatSpeakAvailable(features)
  const pauseHint = Number.isFinite(voicePauseScale)
    ? `Bu sesin doğal ritmi ×${voicePauseScale.toFixed(2)} (otomatik uygulanır).`
    : 'Cümleler arasındaki duraklamaları uzatır ya da kısaltır.'

  return (
    <details className="panel" open={open} onToggle={onToggle}>
      <summary><b>Doğallık</b> <span className="muted small">— insan gibi duyulsun diye</span></summary>
      <div className="stack panel-body">
        <SelectField name="colloquial" label="Konuşma dili" value={settings.colloquial} options={levelOptions} onChange={onChange}
          hint={language === 'tr' ? 'Yazı dilini konuşur gibi okutur: "geleceğim" → "gelicem".' : 'Yalnızca Türkçe metinlerde etkili.'} />
        {(chatOk || shown('fillers')) && (
          <div className="checklist">
            {chatOk && (
              <Check name="chat_speak" title="Sohbet kısaltmaları" desc="tmm → tamam, slm → selam, nbr → naber"
                checked={settings.chat_speak} note={trNote} onChange={onChange} />
            )}
            {shown('fillers') && (
              <Check name="fillers" title="Konuşma dolguları" desc="yani, hani, işte (sohbet için)"
                checked={settings.fillers && !fillersBlockedBy} disabled={Boolean(fillersBlockedBy)}
                note={fillersBlockedBy ? `"${fillersBlockedBy}" stilinde kullanılmaz` : trNote} onChange={onChange} />
            )}
          </div>
        )}
        <div className="checklist">
          <Check name="breaths" title="Nefes" desc="Cümleler arasında doğal nefes" checked={settings.breaths}
            disabled={missing('breaths')} note={note('breaths')} onChange={onChange} />
          <Check name="room_tone" title="Oda tonu" desc="Sessizlik yerine kayıttan oda tonu — dijital boşluk yok"
            checked={settings.room_tone} disabled={missing('room_tone')} note={note('room_tone')} onChange={onChange} />
          <Check name="master" title="Mastering" desc="-16 LUFS yayın seviyesi, hafif EQ" checked={settings.master}
            disabled={missing('master')} note={note('master')} onChange={onChange} />
          <Check name="punctuation_emotion" title="Noktalamaya göre duygu" desc="! vurgulu, ? yükselen ton, ... düşünceli"
            checked={settings.punctuation_emotion} onChange={onChange} />
          <Check name="auto_emotion" title="İçerikten otomatik duygu" desc="Etiket yoksa cümlenin anlamından duygu tahmini"
            checked={settings.auto_emotion} onChange={onChange} />
        </div>
        <RangeField name="pause_scale" label="Duraklama" unit="×" value={settings.pause_scale} min={0.6} max={1.6}
          hint={pauseHint} onChange={onChange} />
        <SelectField name="emotion_fx" label="Ses işleme seviyesi" value={settings.emotion_fx} options={FX_OPTIONS} onChange={onChange}
          hint="Duyguyu çıktı sesine perde, tempo ve kazançla ekler. En doğal sonuç için kapalı önerilir." />
        {(shown('consistency') || shown('qc') || shown('subtitles')) && (
          <div className="stack tight">
            <span className="muted small">Kalite ve çıktı</span>
            <div className="checklist">
              {shown('consistency') && (
                <Check name="consistency" title="Tutarlılık" desc="parçalar arası tını/seviye eşitleme"
                  checked={settings.consistency} onChange={onChange} />
              )}
              {shown('qc') && (
                <Check name="qc" title="Kalite kontrol" desc="bozuk parçayı farklı tohumla yeniden üret"
                  checked={settings.qc} onChange={onChange} />
              )}
              {shown('subtitles') && (
                <Check name="subtitles" title="Altyazı üret" desc="SRT, VTT ve JSON zaman çizelgesi"
                  checked={settings.subtitles} onChange={onChange} />
              )}
            </div>
          </div>
        )}
      </div>
    </details>
  )
})

const AdvancedPanel = memo(function AdvancedPanel({ settings, seed, onSeed, open, onToggle, onChange }) {
  const seedId = useId()
  const n = settings.variants
  return (
    <details className="panel" open={open} onToggle={onToggle}>
      <summary><b>İnce ayar</b> <span className="muted small">— vurgu, sadakat, hız, tohum, varyant</span></summary>
      <div className="stack panel-body">
        <RangeField name="exaggeration" label="Duygu / vurgu (exaggeration)" value={settings.exaggeration} min={0} max={1.5} onChange={onChange} />
        <RangeField name="cfg_weight" label="Sese sadakat / tempo (cfg)" value={settings.cfg_weight} min={0} max={1} onChange={onChange}
          hint="Düşük değer daha yavaş ve serbest; referans ses farklı dildeyse 0'a yaklaştır." />
        <RangeField name="temperature" label="Çeşitlilik (temperature)" value={settings.temperature} min={0.1} max={1.5} onChange={onChange} />
        <RangeField name="speed" label="Hız" unit="×" value={settings.speed} min={0.7} max={1.3} onChange={onChange} />
        <div className="row">
          <label className="grow" htmlFor={seedId}>
            <span>Tohum (seed)</span>
            <input id={seedId} type="number" inputMode="numeric" step="1" min="0" value={seed}
              placeholder="Boş = her seferinde farklı" onChange={(e) => onSeed(e.target.value)} />
          </label>
          <SelectField name="format" label="Format" value={settings.format} options={FORMAT_OPTIONS} onChange={onChange} />
        </div>
        <SelectField name="variants" label="Varyant sayısı" numeric value={String(n)} options={VARIANT_OPTIONS} onChange={onChange}
          hint={`Aynı metinden farklı tohumla ${n > 1 ? n : 3} varyant üret, beğendiğini seç.`} />
      </div>
    </details>
  )
})

const GenerateBar = memo(function GenerateBar({ busy, job, startedAt, disabled, variants, onCancel }) {
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
          {busy ? `Üretiliyor… ${Math.floor(elapsed)} sn` : variants > 1 ? `▶ Seslendir (${variants} varyant)` : '▶ Seslendir'}
        </button>
        {busy && (
          <button ref={cancelRef} type="button" className="btn danger big" onClick={onCancel} aria-label="Üretimi iptal et">✕ İptal</button>
        )}
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

const PartialItem = memo(function PartialItem({ url, text, duration, n, playing }) {
  return (
    <li className={`item small${playing ? ' playing' : ''}`} aria-current={playing ? 'true' : undefined}>
      <div className="row between">
        <span className="muted">Parça {n}{Number.isFinite(duration) ? ` • ${fmtDur(duration)}` : ''}</span>
        {playing && <span className="tag emo">çalıyor</span>}
      </div>
      <Player src={url} compact title={`Parça ${n}`} downloadName={`sesklon-parca-${n}.${extOf(url)}`} />
      {text && <div>{text}</div>}
    </li>
  )
})

const PartialPreview = memo(function PartialPreview({ parts, total, onActiveChange }) {
  const listRef = useRef(null)
  const chain = useChainPlayer(parts, onActiveChange)
  const { stop } = chain

  // Herhangi bir oynatıcı çalmaya başlarsa sıra oynatıcıyı durdur (iki ses üst üste binmesin)
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
  if (chain.active) {
    status = chain.waiting ? `Parça ${chain.index + 1} hazırlanıyor…` : `Çalınıyor: parça ${chain.index + 1} / ${parts.length}`
  }

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
            playing={chain.active && !chain.waiting && chain.index === i} />
        ))}
      </ul>
    </div>
  )
})

function ColloquialChanges({ changes }) {
  if (!Array.isArray(changes) || !changes.length) return null
  const seen = new Set()
  const list = []
  for (const c of changes) {
    if (!c?.from || !c?.to) continue
    const k = `${c.from}→${c.to}`
    if (!seen.has(k)) { seen.add(k); list.push(k) }
  }
  if (!list.length) return null
  const shown = list.slice(0, 12)
  return (
    <div className="muted small" title={list.join(', ')}>
      Konuşma diline çevrilenler: {shown.join(', ')}{list.length > shown.length ? `, … (+${list.length - shown.length})` : ''}
    </div>
  )
}

function chunkMeta(c) {
  const bits = []
  if (c.speaker) bits.push(c.speaker)
  if (c.nonverbal) bits.push(`gerçek tepki: ${String(c.nonverbal).replace(/^nv:/, '')}`)
  if (c.ref) bits.push(`ref: ${c.ref}`)
  const intensity = Number(c.intensity)
  if (c.intensity != null && Number.isFinite(intensity) && Math.abs(intensity - 1) > 0.01) bits.push(`yoğunluk ×${round2(intensity)}`)
  if (Array.isArray(c.blend) && c.blend.length) bits.push(`+ ${c.blend.join(', ')}`)
  if (c.arc_to) bits.push(`→ ${c.arc_to}`)
  if (c.exaggeration != null) bits.push(`vurgu ${c.exaggeration}`)
  if (c.speed != null) bits.push(`hız ${c.speed}×`)
  const pitch = Number(c.pitch)
  if (c.pitch != null && Number.isFinite(pitch) && pitch !== 0) bits.push(`perde ${pitch > 0 ? '+' : ''}${round2(pitch)}`)
  if (c.pause_ms) bits.push(`ardından ${c.pause_ms} ms`)
  if (c.breath || c.breath_before) bits.push('nefes')
  if (c.duration != null) bits.push(fmtDur(c.duration))
  return bits.join(' • ')
}

function ChunkDetails({ chunks, qc }) {
  if (!Array.isArray(chunks) || !chunks.length) return null
  const byIdx = qcByIndex(qc)
  const qcOf = (c, i) => byIdx.get(Number.isInteger(c?.index) ? c.index : i)
  const low = chunks.filter((c, i) => qcLow(qcOf(c, i))).length
  return (
    <details className="chunks">
      <summary className="muted small">
        Cümle cümle ne yapıldı ({chunks.length} parça{low ? ` — ⚠ ${low} düşük puanlı` : ''})
      </summary>
      <ul className="list">
        {chunks.map((c, i) => {
          const q = qcOf(c, i)
          const score = qcScore(q)
          const bad = qcLow(q)
          const retried = qcRetried(q)
          const trimmed = q?.decision === 'trim'
          const reasons = (Array.isArray(q?.reasons) ? q.reasons : []).filter((r) => r && (r.message || r.code))
          const qcBits = [score != null ? `kalite ${Math.round(score)}` : '', retried ? '↻ yeniden üretildi' : '', trimmed ? 'kırpıldı' : '']
            .filter(Boolean)
          return (
            <li key={i} className={`item small${bad ? ' qc-low' : ''}`}>
              <div className="row between">
                <span><span className={`tag ${c.emotion ? 'emo' : ''}`}>{c.emotion || 'nötr'}</span> <span className="muted">{chunkMeta(c)}</span></span>
                {qcBits.length > 0 && (
                  <span className={`small ${bad ? 'warn-text' : 'muted'}`} title="Kalite kontrol puanı (0–100)">
                    {bad ? '⚠ ' : ''}{qcBits.join(' · ')}
                  </span>
                )}
              </div>
              <div>{c.text || (c.nonverbal ? `[${String(c.nonverbal).replace(/^nv:/, '')}]` : '')}</div>
              {reasons.length > 0 && (bad || retried || trimmed) && (
                <ul className={`small qc-reasons ${bad ? 'warn-text' : 'muted'}`} aria-label="Kalite kontrol nedenleri">
                  {reasons.map((r, k) => <li key={k}>{r.message || r.code}</li>)}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </details>
  )
}

/** Sonuç raporu: kalite kontrol özeti, tutarlılık düzeltmeleri, kullanılan gerçek tepkiler. */
function GenReport({ params }) {
  const p = params && typeof params === 'object' ? params : {}
  const lines = []

  const qcList = Array.isArray(p.qc_reports) ? p.qc_reports : (Array.isArray(p.qc) ? p.qc : [])
  const qc = qcList.filter((q) => q && typeof q === 'object')
  if (qc.length) {
    const scores = qc.map(qcScore).filter((s) => s != null)
    const avg = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null
    const retried = qc.filter(qcRetried).length
    const trimmed = qc.filter((q) => q.decision === 'trim').length
    const low = qc.filter(qcLow).length
    const bits = []
    if (avg != null) bits.push(`ortalama ${avg}/100`)
    bits.push(retried ? `${retried} parça yeniden üretildi` : 'yeniden üretim gerekmedi')
    if (trimmed) bits.push(`${trimmed} parça kırpıldı`)
    lines.push(
      <div key="qc" className="small">
        <b>Kalite kontrol:</b> {bits.join(' · ')}
        {low > 0 && <span className="warn-text"> · ⚠ {low} parça düşük puanlı (aşağıda "Cümle cümle")</span>}
      </div>,
    )
  }

  const c = (p.consistency_report && typeof p.consistency_report === 'object') ? p.consistency_report : (p.consistency && typeof p.consistency === 'object' ? p.consistency : null)
  if (c && typeof c === 'object') {
    const bits = []
    const t = Number(c.timbre_db)
    if (c.timbre_db != null && Number.isFinite(t) && Math.abs(t) >= 0.05) bits.push(`tını ${signedDb(t)}`)
    const steps = Number(c.loudness_steps)
    if (Number.isFinite(steps) && steps > 0) bits.push(`${steps} parça seviyelendi`)
    lines.push(
      <div key="consistency" className="small">
        <b>Tutarlılık:</b> {bits.length ? bits.join(', ') : 'parçalar zaten uyumluydu, düzeltme gerekmedi'}
      </div>,
    )
  }

  const used = [...new Set((Array.isArray(p.nonverbal_used) ? p.nonverbal_used : [])
    .map((u) => String(u && typeof u === 'object' ? (u.key ?? u.tag ?? '') : u ?? '').replace(/^nv:/, '').trim())
    .filter(Boolean))]
  if (used.length) {
    lines.push(
      <div key="nv" className="small" title="Bu etiketlerde modelin ünlemi yerine sesin kendi kaydı çalındı">
        <b>Kullanılan tepkiler:</b> {used.join(', ')}
      </div>,
    )
  }

  return lines.length ? <div className="stack tight gen-report">{lines}</div> : null
}

// api.js 404'ü zaten "bu üretimin altyazısı yok" diye açıklar; sunucu mesajı varsa o gösterilir.
const subtitleError = (err) => err?.message || 'Altyazı alınamadı.'

/** "Altyazı: SRT · VTT · JSON" indirme düğmeleri + önizleme. */
function SubtitleBar({ gen, notify }) {
  const [busy, setBusy] = useState('')
  const [preview, setPreview] = useState(null) // { format, text, loading, error }
  const reqRef = useRef(0)
  const timeline = gen.params?.timeline
  const available = (Array.isArray(timeline) && timeline.length > 0) || gen.params?.subtitles === true
  if (!available || !gen.id) return null

  async function download(fmt) {
    if (typeof api.subtitles !== 'function') { notify('Altyazı indirme bu sürümde yok.', 'error'); return }
    setBusy(fmt)
    try {
      await api.subtitles(gen.id, fmt)
    } catch (err) {
      notify(subtitleError(err), 'error')
    } finally {
      setBusy('')
    }
  }

  async function show(fmt) {
    const id = ++reqRef.current
    if (typeof api.subtitleText !== 'function') {
      setPreview({ format: fmt, text: '', loading: false, error: 'Altyazı önizleme bu sürümde yok.' })
      return
    }
    setPreview({ format: fmt, text: '', loading: true, error: '' })
    try {
      const res = await api.subtitleText(gen.id, fmt)
      let text = typeof res === 'string' ? res : JSON.stringify(res, null, 2)
      if (fmt === 'json' && typeof res === 'string') {
        try { text = JSON.stringify(JSON.parse(res), null, 2) } catch { /* olduğu gibi göster */ }
      }
      if (id === reqRef.current) setPreview({ format: fmt, text, loading: false, error: '' })
    } catch (err) {
      if (id === reqRef.current) setPreview({ format: fmt, text: '', loading: false, error: subtitleError(err) })
    }
  }

  const close = () => { reqRef.current += 1; setPreview(null) }

  return (
    <div className="stack tight">
      <div className="row subtitle-bar">
        <span className="small"><b>Altyazı:</b></span>
        {SUB_FORMATS.map(([f, label]) => (
          <button key={f} type="button" className="btn ghost small" disabled={busy === f} onClick={() => download(f)}
            title={`${label} dosyası olarak indir`} aria-label={`Altyazıyı ${label} olarak indir`}>
            {busy === f ? 'İniyor…' : `⤓ ${label}`}
          </button>
        ))}
        <button type="button" className="btn ghost small" aria-expanded={Boolean(preview)}
          onClick={() => (preview ? close() : show('srt'))}>
          {preview ? 'Önizlemeyi kapat' : 'Önizle'}
        </button>
      </div>
      {preview && (
        <div className="stack tight">
          <div className="presets" role="group" aria-label="Önizleme biçimi">
            {SUB_FORMATS.map(([f, label]) => (
              <button key={f} type="button" className={`chip clickable small${preview.format === f ? ' active' : ''}`}
                aria-pressed={preview.format === f} onClick={() => show(f)}>{label}</button>
            ))}
          </div>
          {preview.loading ? (
            <div className="muted small" role="status"><span className="spinner" aria-hidden="true" /> Altyazı yükleniyor…</div>
          ) : preview.error ? (
            <div className="alert error">{preview.error}</div>
          ) : (
            <pre className="subtitle-preview" tabIndex={0}
              aria-label={`Altyazı önizlemesi (${preview.format.toUpperCase()})`}>{preview.text || '(boş)'}</pre>
          )}
        </div>
      )}
    </div>
  )
}

const VariantResult = memo(function VariantResult({ result, languages, autoPlay, favs, onFavorite, onRegenerate, onPinSeed, notify }) {
  const variants = Array.isArray(result.variants) && result.variants.length > 1 ? result.variants.slice(0, LETTERS.length) : [result]
  const multi = variants.length > 1
  const [idx, setIdx] = useState(0)
  const [picked, setPicked] = useState(false) // kullanıcı sekme değiştirdiyse yeni varyantı hemen çal
  const baseId = useId()
  const tabRefs = useRef([])
  const gen = variants[Math.min(idx, variants.length - 1)]
  const seed = seedOf(gen)
  const fav = Boolean(gen.favorite) || favs.has(gen.id)

  const select = (i) => { setIdx(i); setPicked(true) }
  function onTabKey(e) {
    const n = variants.length
    let next = null
    if (e.key === 'ArrowRight') next = (idx + 1) % n
    else if (e.key === 'ArrowLeft') next = (idx - 1 + n) % n
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = n - 1
    if (next === null) return
    e.preventDefault()
    select(next)
    tabRefs.current[next]?.focus()
  }

  return (
    <div className="stack">
      {multi && (
        <div className="presets variant-tabs" role="tablist" aria-label="Varyantlar" onKeyDown={onTabKey}>
          {variants.map((g, i) => {
            const on = i === idx
            const isFav = Boolean(g.favorite) || favs.has(g.id)
            return (
              <button key={g.id || i} ref={(el) => { tabRefs.current[i] = el }} type="button" role="tab"
                id={`${baseId}t${i}`} aria-selected={on} aria-controls={`${baseId}p`} tabIndex={on ? 0 : -1}
                className={`chip clickable${on ? ' active' : ''}`} onClick={() => select(i)}
                aria-label={`Varyant ${LETTERS[i]}${isFav ? ' (beğenildi)' : ''}`}>
                {LETTERS[i]}{isFav ? ' ★' : ''}
              </button>
            )
          })}
        </div>
      )}
      <div className="stack" id={`${baseId}p`} role={multi ? 'tabpanel' : undefined}
        aria-labelledby={multi ? `${baseId}t${idx}` : undefined}>
        <Player key={gen.id} src={gen.url} title={multi ? `Varyant ${LETTERS[idx]}` : undefined}
          downloadName={`sesklon-${gen.id}.${extOf(gen.filename || gen.url)}`} autoPlay={picked || autoPlay} />
        <div className="muted small">{genMeta(gen, languages)}</div>
        {multi && (
          <div className="row">
            <button type="button" className={`btn small ${fav ? 'secondary' : 'ghost'}`} aria-pressed={fav}
              onClick={() => { if (!fav) onFavorite(gen.id) }}>
              {fav ? '★ Beğenildi' : 'Bunu beğendim ★'}
            </button>
          </div>
        )}
      </div>
      <div className="row">
        <button type="button" className="btn secondary small" onClick={onRegenerate}>↻ Yeniden üret (farklı)</button>
        <button type="button" className="btn ghost small" onClick={() => onPinSeed(gen)}
          title="Bu sonucun tohumunu sabitler; aynı ayarlarla aynı sesi yeniden alırsın.">
          Tohumu sabitle{seed != null ? ` (${seed})` : ''}
        </button>
      </div>
      <GenReport params={gen.params} />
      <SubtitleBar key={gen.id} gen={gen} notify={notify} />
      <ColloquialChanges changes={gen.params?.colloquial_changes} />
      <ChunkDetails chunks={gen.params?.chunks} qc={gen.params?.qc_reports ?? gen.params?.qc} />
      {gen.params?.normalized_text && (
        <details className="chunks">
          <summary className="muted small">Modelin okuduğu metin</summary>
          <p className="quote small">{gen.params.normalized_text}</p>
        </details>
      )}
    </div>
  )
})

// ─────────────────────────────────────────────────────────── ana bileşen ──

export default function Generate({ voices = [], languages, maxChars = 5000, health, onGenerated, notify }) {
  const [saved] = useState(loadSaved)
  const hadSavedRef = useRef(Boolean(saved && saved.settings))
  const [text, setText] = useState(() => (typeof saved?.text === 'string' ? saved.text : DEFAULT_TEXT).slice(0, maxChars))
  const [settings, setSettings] = useState(() => sanitizeSettings(saved?.settings))
  const [voiceId, setVoiceId] = useState(() => (typeof saved?.voiceId === 'string' ? saved.voiceId : null))
  const [language, setLanguage] = useState('tr')
  const [seed, setSeed] = useState('')
  const [ui, setUi] = useState(() => sanitizeUi(saved?.ui))
  const [busy, setBusy] = useState(false)
  const [startedAt, setStartedAt] = useState(0)
  const [job, setJob] = useState(null)
  const [result, setResult] = useState(null)
  const [resultAutoPlay, setResultAutoPlay] = useState(true)
  const [favs, setFavs] = useState(() => new Set())

  const textRef = useRef(null)
  const focusedOnceRef = useRef(false) // metin kutusu hiç odaklanmadıysa etiket sona eklenir
  const lastEmotionRef = useRef('') // etiket kutusunda son tıklanan duygu (yoğunluk düğmeleri yeni etiket eklerken kullanır)
  const touchedRef = useRef(false) // kullanıcı ayarlara dokunduysa otomatik stil seçimi yapılmaz
  const busyRef = useRef(false)
  const runRef = useRef(0) // her üretim bir "çalışma"; iptal edilen çalışmanın sonucu yok sayılır
  const jobRef = useRef(null)
  const chainActiveRef = useRef(false)
  const cancelledIdsRef = useRef(new Set())
  const latestSaveRef = useRef(null)

  const textId = useId()
  const countId = useId()
  const tagsId = useId()
  const exampleId = useId()
  const voiceSelId = useId()
  const voiceInfoId = useId()
  const langId = useId()
  const emotionId = useId()
  const leftId = useId()
  const rightId = useId()

  const catalog = useCatalog(health)
  const langs = useStableJson(languages || { tr: 'Türkçe' })
  const selectedVoice = useMemo(() => voices.find((v) => v.id === voiceId) || null, [voices, voiceId])
  const activeStyle = useMemo(() => catalog.styles.find((s) => s.name === settings.style) || null, [catalog.styles, settings.style])
  const customized = useMemo(() => isCustomized(settings, activeStyle), [settings, activeStyle])
  const rawPauseScale = selectedVoice?.analysis?.pauses?.scale
  const voicePauseScale = Number.isFinite(rawPauseScale) ? rawPauseScale : null
  const estimate = useMemo(
    () => estimateSeconds(text, settings.speed, settings.pause_scale * (voicePauseScale || 1), catalog.pauseMs),
    [text, settings.speed, settings.pause_scale, voicePauseScale, catalog.pauseMs],
  )
  const emotionOptions = useMemo(() => {
    const opts = catalog.emotions.filter((e) => e.name !== 'normal').map((e) => [e.name, e.label || e.name])
    if (settings.emotion && !opts.some(([v]) => v === settings.emotion)) opts.push([settings.emotion, settings.emotion])
    return opts
  }, [catalog.emotions, settings.emotion])
  const emotionIndex = useMemo(() => buildEmotionIndex(catalog.emotions), [catalog.emotions])
  // Seçili sesin gerçek tepki kayıtları (etiket kutusunda ✓ ile gösterilir)
  const nvSamplesKey = (selectedVoice?.samples || []).filter((s) => sampleKind(s) === 'nonverbal').map(sampleKey).sort().join('|')
  const recordedNv = useMemo(() => new Set(nvSamplesKey ? nvSamplesKey.split('|') : []), [nvSamplesKey])
  const fillersBlockedBy = activeStyle && FILLER_OFF_STYLES.has(activeStyle.name) ? activeStyle.label || activeStyle.name : ''

  // Canlı önizleme: yalnızca yeni parça geldiğinde yeni dizi (her yoklamada değil)
  const rawPartial = job?.partial
  const partialKey = Array.isArray(rawPartial) ? rawPartial.map((p) => p?.url).join('|') : ''
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const partial = useMemo(() => (Array.isArray(rawPartial) ? rawPartial.filter((p) => p && p.url) : []), [partialKey])

  const notifyLatest = useLatest((msg, type) => notify?.(msg, type))
  const onGeneratedLatest = useLatest((g) => onGenerated?.(g))

  // ── stil
  const applyStyle = useLatest((name) => {
    const st = catalog.styles.find((s) => s.name === name)
    if (!st) return null
    setSettings((s) => ({ ...s, style: st.name, ...styleValues(st) }))
    return st
  })
  const selectStyle = useCallback((name) => { touchedRef.current = true; applyStyle(name) }, [applyStyle])
  const setField = useCallback((key, value) => {
    touchedRef.current = true
    setSettings((s) => (s[key] === value ? s : { ...s, [key]: value }))
  }, [])

  // ── etkiler
  useEffect(() => { setText((t) => (t.length > maxChars ? t.slice(0, maxChars) : t)) }, [maxChars])

  useEffect(() => {
    if (!voices.length) return
    // '' = kullanıcı açıkça "Varsayılan model sesi"ni seçti; dokunma
    setVoiceId((cur) => (cur === '' || (cur && voices.some((v) => v.id === cur)) ? cur : voices[0].id))
  }, [voices])

  useEffect(() => {
    if (selectedVoice?.language) setLanguage(selectedVoice.language)
  }, [selectedVoice?.id, selectedVoice?.language])

  // İlk açılış (kayıtlı ayar yok, kullanıcı dokunmadı): sesin varsayılan stili, yoksa "sohbet"
  useEffect(() => {
    if (hadSavedRef.current || touchedRef.current || !catalog.styles.length) return
    const has = (n) => Boolean(n) && catalog.styles.some((s) => s.name === n)
    const ds = selectedVoice?.default_style
    const target = has(ds) ? ds : has(settings.style) ? settings.style : has('sohbet') ? 'sohbet' : null
    if (target && target !== settings.style) applyStyle(target)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.styles, selectedVoice?.default_style])

  // Kalıcılık (400 ms gecikmeli; bileşen kapanırken hemen yaz)
  useEffect(() => {
    latestSaveRef.current = { v: 4, settings, voiceId, text, ui }
    const t = setTimeout(() => saveState(latestSaveRef.current), 400)
    return () => clearTimeout(t)
  }, [settings, voiceId, text, ui])
  useEffect(() => () => { if (latestSaveRef.current) saveState(latestSaveRef.current) }, [])

  // ── "Tekrar kullan" (Geçmiş sekmesi): sesklon_reuse anahtarı + sesklon:reuse olayı → metin, ayarlar, ses, tohum
  const applyReuse = useLatest((payload) => {
    if (!payload || typeof payload !== 'object') return
    const p = payload.params && typeof payload.params === 'object' ? payload.params : {}
    touchedRef.current = true
    if (typeof payload.text === 'string') setText(payload.text.slice(0, maxChars))
    setSettings((s) => sanitizeSettings({ ...s, ...p, emotion: p.emotion ?? s.emotion, style: p.style ?? null }))
    if (p.voice_id !== undefined) setVoiceId(p.voice_id || '')
    if (typeof p.language === 'string') setLanguage(p.language)
    setSeed(Number.isFinite(Number(p.seed)) && p.seed !== null && p.seed !== '' ? String(p.seed) : '')
    setUi((u) => ({ ...u, advanced: p.seed != null ? true : u.advanced }))
  })
  useEffect(() => {
    try {
      const raw = localStorage.getItem('sesklon_reuse')
      if (raw) { localStorage.removeItem('sesklon_reuse'); applyReuse(JSON.parse(raw)) }
    } catch { /* yok say */ }
    const onEvent = (e) => { try { localStorage.removeItem('sesklon_reuse') } catch {} applyReuse(e.detail) }
    window.addEventListener('sesklon:reuse', onEvent)
    return () => window.removeEventListener('sesklon:reuse', onEvent)
  }, [applyReuse])

  // ── metin
  const insertToken = useLatest((token) => {
    const el = textRef.current
    const cur = el ? el.value : text
    const useCaret = Boolean(el) && focusedOnceRef.current
    const start = useCaret ? (el.selectionStart ?? cur.length) : cur.length
    const end = useCaret ? (el.selectionEnd ?? cur.length) : cur.length
    const before = cur.slice(0, start)
    const after = cur.slice(end)
    const lead = before && !/\s$/.test(before) ? ' ' : ''
    const trail = /^\s/.test(after) ? '' : ' '
    const ins = lead + token + trail
    const next = (before + ins + after).slice(0, maxChars)
    setText(next)
    const pos = Math.min((before + ins).length, next.length)
    requestAnimationFrame(() => {
      const t = textRef.current
      if (!t) return
      t.focus()
      t.setSelectionRange(pos, pos)
    })
  })
  const onTextChange = (e) => setText(e.target.value.slice(0, maxChars))
  const onTextFocus = () => { focusedOnceRef.current = true }

  /** Metni değiştirir ve seçimi geri yükler; karakter sınırı aşılırsa hiçbir şey yapmaz. */
  const commitEdit = useLatest((next, selStart, selEnd = selStart) => {
    if (next.length > maxChars) {
      notifyLatest(`Bu değişiklikle metin ${maxChars} karakter sınırını aşıyor.`, 'error')
      return false
    }
    setText(next)
    requestAnimationFrame(() => {
      const t = textRef.current
      if (!t) return
      t.focus()
      try { t.setSelectionRange(selStart, selEnd) } catch { /* yok say */ }
    })
    return true
  })

  /** Metin kutusunun güncel seçimi; kutuya hiç odaklanılmadıysa seçim anlamsızdır → null. */
  const readSelection = () => {
    const el = textRef.current
    if (!el || !focusedOnceRef.current) return null
    return { value: el.value, start: el.selectionStart ?? 0, end: el.selectionEnd ?? 0 }
  }

  const insertEmotion = useLatest((name) => {
    lastEmotionRef.current = name
    insertToken(`[${name}]`)
  })

  /** Yoğunluk: imleçten önceki son duygu etiketini [biraz X] / [X] / [çok X] yapar; etiket yoksa yenisini ekler. */
  const applyIntensity = useLatest((word) => {
    const el = textRef.current
    const cur = el ? el.value : text
    const caret = el && focusedOnceRef.current ? (el.selectionEnd ?? cur.length) : cur.length
    const tag = findEmotionTagBefore(cur, caret, emotionIndex)
    if (tag) {
      const next = emotionTagWith(tag, word)
      if (next === tag.raw) { notifyLatest(`${tag.raw} zaten bu yoğunlukta.`, 'info'); return }
      const pos = caret >= tag.end ? caret + next.length - tag.raw.length : tag.start + next.length
      if (commitEdit(cur.slice(0, tag.start) + next + cur.slice(tag.end), pos)) notifyLatest(`${tag.raw} → ${next}`)
      return
    }
    const emo = lastEmotionRef.current || settings.emotion
    if (!emo) {
      notifyLatest('Önce "Duygu" grubundan bir duygu ekle; yoğunluk imleçten önceki son duygu etiketine uygulanır.', 'info')
      return
    }
    insertToken(`[${word ? `${word} ` : ''}${emo}]`)
  })

  /** Vurgu: seçili sözcüğü/öbeği *…* ile sarar; zaten vurguluysa yıldızları kaldırır. */
  const applyEmphasis = useLatest(() => {
    const sel = readSelection()
    const hint = 'Önce metinde vurgulanacak sözcüğü seç (ya da imleci sözcüğün üzerine getir).'
    if (!sel) { notifyLatest(hint, 'info'); return }
    const cur = sel.value
    const r = wordRange(cur, sel.start, sel.end)
    if (!r) { notifyLatest(hint, 'info'); return }
    const [s, e] = r
    if (e - s > 2 && cur[s] === '*' && cur[e - 1] === '*') { // seçim "*çok*" → kaldır
      commitEdit(cur.slice(0, s) + cur.slice(s + 1, e - 1) + cur.slice(e), s, e - 2)
      notifyLatest('Vurgu kaldırıldı.')
      return
    }
    if (cur[s - 1] === '*' && cur[e] === '*') { // imleç/seçim *çok* içinde → kaldır
      commitEdit(cur.slice(0, s - 1) + cur.slice(s, e) + cur.slice(e + 1), s - 1, e - 1)
      notifyLatest('Vurgu kaldırıldı.')
      return
    }
    if (enclosingBlock(cur, s, e, '[', ']') || enclosingBlock(cur, s, e, '{', '}')) {
      notifyLatest('Etiketin ya da okunuş bloğunun içine vurgu eklenemez.', 'warn')
      return
    }
    const inner = cur.slice(s, e)
    if (inner.includes('\n') || inner.includes('*')) {
      notifyLatest('Vurgu tek satırlık bir sözcük ya da kısa öbek olmalı.', 'warn')
      return
    }
    if (inner.length > EMPHASIS_MAX) {
      notifyLatest(`Vurgu en fazla ${EMPHASIS_MAX} karakter olabilir; bir sözcük ya da kısa bir öbek seç.`, 'warn')
      return
    }
    commitEdit(`${cur.slice(0, s)}*${inner}*${cur.slice(e)}`, s + 1, e + 1)
  })

  /** Okunuş: seçili sözcüğü {sözcük|okunuş} yapar (okunuşu sorar); mevcut bloğu düzenler ya da kaldırır. */
  const applyReading = useLatest(() => {
    const sel = readSelection()
    const hint = 'Önce metinde okunuşunu belirleyeceğin sözcüğü seç (ya da imleci üzerine getir).'
    if (!sel) { notifyLatest(hint, 'info'); return }
    const cur = sel.value
    const whole = sel.end - sel.start > 2 && cur[sel.start] === '{' && cur[sel.end - 1] === '}'
    const blk = whole ? [sel.start, sel.end] : enclosingBlock(cur, sel.start, sel.end, '{', '}')
    const parsed = blk ? READING_BLOCK_RE.exec(cur.slice(blk[0], blk[1])) : null
    let range
    let word
    let old = ''
    if (parsed) {
      range = blk
      word = parsed[1].trim()
      old = (parsed[2] ?? '').trim()
    } else {
      range = wordRange(cur, sel.start, sel.end)
      if (!range) { notifyLatest(hint, 'info'); return }
      if (enclosingBlock(cur, range[0], range[1], '[', ']')) {
        notifyLatest('Etiketin içindeki sözcüğe okunuş verilemez.', 'warn')
        return
      }
      word = cur.slice(range[0], range[1])
    }
    if (!word || /[\n{}|[\]*]/.test(word) || word.length > 60) {
      notifyLatest('Okunuş için tek satırlık düz bir sözcük ya da kısa öbek seç.', 'warn')
      return
    }
    const answer = window.prompt(
      `"${word}" nasıl okunsun? Türkçe okunduğu gibi yaz (ör. Shopify → Şopifay).${old ? '\nBoş bırakırsan okunuş kaldırılır.' : ''}`,
      old,
    )
    if (answer == null) return
    const reading = answer.replace(/[{}|[\]\n]/g, ' ').replace(/\s+/g, ' ').trim()
    const [a, b] = range
    if (!reading) {
      if (parsed) {
        commitEdit(cur.slice(0, a) + word + cur.slice(b), a, a + word.length)
        notifyLatest('Okunuş kaldırıldı.')
      }
      return
    }
    if (reading === word) { notifyLatest('Okunuş sözcükle aynı; değişiklik yapılmadı.', 'info'); return }
    const token = `{${word}|${reading}}`
    if (commitEdit(cur.slice(0, a) + token + cur.slice(b), a + token.length)) {
      notifyLatest(`"${word}" → "${reading}" diye okunacak. Her metinde geçerli olsun istersen Telaffuz sekmesinde sözlüğe ekle.`)
    }
  })

  function onExample(e) {
    const ex = EXAMPLES.find((x) => x.id === e.target.value)
    if (!ex) return
    const cur = textRef.current ? textRef.current.value : text
    const replaceable = !cur.trim() || cur === DEFAULT_TEXT || EXAMPLES.some((x) => x.text === cur)
    if (!replaceable && !window.confirm('Yazdığın metnin yerine örnek metin konsun mu?')) return
    setText(ex.text.slice(0, maxChars))
    if (!customized) {
      const st = applyStyle(ex.style)
      if (st) {
        touchedRef.current = true
        notifyLatest(`"${ex.label}" örneği yüklendi; "${st.label || st.name}" stili seçildi.`)
      }
    }
  }

  function onVoiceChange(e) {
    const id = e.target.value
    setVoiceId(id)
    touchedRef.current = true
    const v = voices.find((x) => x.id === id)
    if (v?.default_style) {
      const st = applyStyle(v.default_style)
      if (st) notifyLatest(`${v.name}: varsayılan stil "${st.label || st.name}" uygulandı.`)
    }
  }

  // ── panel aç/kapa
  const toggleTags = useCallback(() => setUi((u) => ({ ...u, tags: !u.tags })), [])
  const onToggleNatural = useCallback((e) => {
    const open = e.currentTarget.open
    setUi((u) => (u.natural === open ? u : { ...u, natural: open }))
  }, [])
  const onToggleAdvanced = useCallback((e) => {
    const open = e.currentTarget.open
    setUi((u) => (u.advanced === open ? u : { ...u, advanced: open }))
  }, [])

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

  const generate = useLatest(async (overrides = {}) => {
    if (busyRef.current) return
    if (!text.trim()) { textRef.current?.focus(); return }
    busyRef.current = true
    const run = ++runRef.current
    const s = settings
    const f = catalog.features
    const on = (k) => f[k] !== false // sunucu "yok" dediği katmanı açık göndermeyiz
    const payload = {
      text,
      voice_id: selectedVoice ? selectedVoice.id : null,
      language,
      style: activeStyle ? activeStyle.name : null, // sunucunun tanımadığı (kaldırılmış) stil gönderilmez
      exaggeration: s.exaggeration,
      cfg_weight: s.cfg_weight,
      temperature: s.temperature,
      speed: s.speed,
      seed: 'seed' in overrides ? overrides.seed : parseSeed(seed),
      format: s.format,
      colloquial: s.colloquial,
      punctuation_emotion: s.punctuation_emotion,
      auto_emotion: s.auto_emotion,
      emotion_fx: s.emotion_fx,
      emotion_refs: s.emotion_fx === 'full',
      emotion: s.emotion || null,
      breaths: s.breaths,
      room_tone: s.room_tone,
      master: s.master,
      pause_scale: s.pause_scale,
      variants: s.variants,
      // v4 katmanları (docs/SOZLESME2.md §9)
      chat_speak: chatSpeakAvailable(f) && s.chat_speak,
      fillers: on('fillers') && s.fillers && !(activeStyle && FILLER_OFF_STYLES.has(activeStyle.name)),
      consistency: on('consistency') && s.consistency,
      qc: on('qc') && s.qc,
      subtitles: on('subtitles') && s.subtitles,
    }
    jobRef.current = null
    chainActiveRef.current = false
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
      setResultAutoPlay(!chainActiveRef.current) // sıralı dinleme açıksa sonucu baştan çalıp bölme
      setResult(gen)
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

  const regenerate = useCallback(() => { setSeed(''); generate({ seed: null }) }, [generate])

  const pinSeed = useCallback((gen) => {
    const s = seedOf(gen)
    const val = Number.isFinite(s) ? s : Math.floor(Math.random() * 1e6)
    setSeed(String(val))
    setSettings((st) => (st.variants === 1 ? st : { ...st, variants: 1 }))
    setUi((u) => (u.advanced ? u : { ...u, advanced: true }))
    notifyLatest(Number.isFinite(s) ? `Tohum ${val} sabitlendi.` : `Bu sonucun tohumu bilinmiyor; yeni tohum ${val} sabitlendi.`)
  }, [notifyLatest])

  const markFavorite = useCallback(async (id) => {
    let fn = null
    if (typeof api.favorite === 'function') fn = () => api.favorite(id, true)
    else if (typeof api.setFavorite === 'function') fn = () => api.setFavorite(id, true)
    if (!fn) { notifyLatest('Favori işaretleme bu sürümde yok.', 'error'); return }
    try {
      await fn()
      setFavs((prev) => new Set(prev).add(id))
      notifyLatest('Favorilere eklendi ★')
      onGeneratedLatest()
    } catch (err) {
      notifyLatest(err?.message || 'Favori kaydedilemedi', 'error')
    }
  }, [notifyLatest, onGeneratedLatest])

  const setChainActive = useCallback((v) => { chainActiveRef.current = v }, [])

  const onSubmit = useCallback((e) => { e.preventDefault(); generate() }, [generate])
  const onFormKeyDown = useCallback((e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); generate() }
  }, [generate])

  const nearLimit = text.length >= maxChars * 0.9
  const variants = settings.variants

  return (
    <div className="grid two">
      <section className="card" aria-labelledby={leftId}>
        <h2 id={leftId}>Metin ve ayarlar</h2>
        <form className="stack" onSubmit={onSubmit} onKeyDown={onFormKeyDown} noValidate>
          <StyleChips styles={catalog.styles} active={settings.style} customized={customized} onSelect={selectStyle} />

          <div className="stack tight">
            <div className="row between">
              <label htmlFor={textId}><span>Metin <span className="muted">(Ctrl+Enter ile üret)</span></span></label>
              <div className="row">
                <label className="inline small" htmlFor={exampleId}>
                  Örnek metin
                  <select id={exampleId} value="" onChange={onExample}>
                    <option value="">Seç…</option>
                    {EXAMPLES.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
                  </select>
                </label>
                <button type="button" className="btn ghost small" aria-expanded={ui.tags} aria-controls={tagsId} onClick={toggleTags}>
                  {ui.tags ? 'Etiketleri gizle' : 'Etiketler'}
                </button>
              </div>
            </div>
            <textarea id={textId} ref={textRef} rows={9} value={text} onChange={onTextChange} onFocus={onTextFocus}
              placeholder="Seslendirilecek metni yaz…" aria-describedby={countId} />
            <div className="row between" id={countId}>
              <span className={`small ${nearLimit ? 'warn-text' : 'muted'}`}>{text.length} / {maxChars} karakter</span>
              <span className="small muted">
                {estimate > 0 ? `≈ ${fmtSecs(estimate)} ses` : 'Metin boş'}{variants > 1 ? ` • ${variants} varyant` : ''}
              </span>
            </div>
          </div>

          {ui.tags && (
            <TagBox id={tagsId} catalog={catalog} recordedNv={recordedNv} onInsert={insertToken} onEmotion={insertEmotion}
              onIntensity={applyIntensity} onEmphasis={applyEmphasis} onReading={applyReading} />
          )}

          <div className="row">
            <label className="grow" htmlFor={voiceSelId}>
              <span>Ses</span>
              <select id={voiceSelId} value={voiceId ?? ''} onChange={onVoiceChange} aria-describedby={voiceInfoId}>
                <option value="">Varsayılan model sesi</option>
                {voices.map((v) => <option key={v.id} value={v.id}>{voiceOptionLabel(v)}</option>)}
              </select>
            </label>
            <label className="grow" htmlFor={langId}>
              <span>Dil</span>
              <select id={langId} value={language} onChange={(e) => setLanguage(e.target.value)}>
                {Object.entries(langs).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label className="grow" htmlFor={emotionId}>
              <span>Genel duygu</span>
              <select id={emotionId} value={settings.emotion} onChange={(e) => setField('emotion', e.target.value)}>
                <option value="">Etiketlere göre</option>
                {emotionOptions.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </label>
          </div>
          <VoiceInfo id={voiceInfoId} voice={selectedVoice} />

          <NaturalnessPanel settings={settings} levels={catalog.levels} features={catalog.features} language={language}
            voicePauseScale={voicePauseScale} fillersBlockedBy={fillersBlockedBy} open={ui.natural} onToggle={onToggleNatural}
            onChange={setField} />
          <AdvancedPanel settings={settings} seed={seed} onSeed={setSeed} open={ui.advanced} onToggle={onToggleAdvanced}
            onChange={setField} />

          <GenerateBar busy={busy} job={job} startedAt={startedAt} disabled={!text.trim()} variants={variants} onCancel={cancel} />
        </form>
      </section>

      <section className="card" aria-labelledby={rightId} aria-busy={busy}>
        <h2 id={rightId}>Sonuç</h2>
        {busy ? (
          partial.length > 0 ? (
            <PartialPreview parts={partial} total={job?.total || 0} onActiveChange={setChainActive} />
          ) : (
            <p className="muted">Üretim sürüyor… İlk parça hazır olunca buradan dinlemeye başlayabilirsin.</p>
          )
        ) : result ? (
          <VariantResult key={result.id} result={result} languages={langs} autoPlay={resultAutoPlay} favs={favs}
            onFavorite={markFavorite} onRegenerate={regenerate} onPinSeed={pinSeed} notify={notifyLatest} />
        ) : (
          <p className="muted">Üretilen ses burada görünecek.</p>
        )}
      </section>
    </div>
  )
}
