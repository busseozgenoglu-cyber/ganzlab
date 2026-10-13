import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import Player, { fmtDur } from './Player'
// Player'ın isteğe bağlı "aynı anda tek oynatıcı" yolu (playerBus / stopAllPlayers); yoksa sessizce atlanır.
import * as PlayerModule from './Player'

// ─────────────────────────────────────────────────────────── sabitler ──

const STORAGE_KEY = 'sesklon_generate_v3'
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
  format: 'mp3', variants: 1,
}
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

// ─────────────────────────────────────────────────────────── yardımcılar ──

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
const trLower = (s) => String(s).toLocaleLowerCase('tr')
const fmtNum = (n) => String(Math.round(n * 10) / 10)
const seedOf = (g) => g?.seed ?? g?.params?.seed ?? null
const isCancelledError = (err) =>
  (typeof api.isCancelled === 'function' && api.isCancelled(err)) || err?.name === 'CancelledError' || err?.cancelled === true

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
  const n = v.samples?.length || 0
  if (n) bits.push(`${n} duygu kaydı`)
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
  return {
    styles: Array.isArray(h?.styles) ? h.styles.filter((s) => s && typeof s.name === 'string') : [],
    levels: Array.isArray(h?.colloquial_levels) && h.colloquial_levels.length ? h.colloquial_levels : DEFAULT_LEVELS,
    features: (h && h.features) || {},
    emotions: Array.isArray(tags.emotions) ? tags.emotions.filter((e) => e && e.name) : [],
    nonverbal,
    pauses,
    pauseMs,
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

function TagGroup({ title, children }) {
  const id = useId()
  return (
    <div className="taggroup" role="group" aria-labelledby={id}>
      <span id={id} className="muted small">{title}</span>
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

const TagBox = memo(function TagBox({ id, emotions, nonverbal, pauses, onInsert }) {
  const [secs, setSecs] = useState('1.5')
  const secsId = useId()
  const n = Number.parseFloat(String(secs).replace(',', '.'))
  const value = Number.isFinite(n) && n > 0 ? clamp(Math.round(n * 10) / 10, 0.1, 10) : null
  const addNumeric = () => { if (value != null) onInsert(`[${value} sn]`) }

  return (
    <div className="tagbox" id={id}>
      <div className="muted small">
        İmlecin olduğu yere eklenir; duygu, bir sonraki duygu etiketine kadar sürer. Noktalama da tonu etkiler:
        {' '}<b>!</b> vurgulu, <b>?</b> yükselen ton, <b>...</b> düşünceli.
      </div>
      {emotions.length > 0 && (
        <TagGroup title="Duygu">
          {emotions.map((e) => {
            const label = e.label || e.name
            const tip = [e.description, e.aliases?.length ? `Diğer adları: ${e.aliases.slice(0, 5).join(', ')}` : '']
              .filter(Boolean).join(' • ')
            return (
              <button key={e.name} type="button" className="chip clickable" title={tip || undefined}
                aria-label={`Duygu etiketi ekle: ${label}`} onClick={() => onInsert(`[${e.name}]`)}>[{label}]</button>
            )
          })}
        </TagGroup>
      )}
      {nonverbal.length > 0 && (
        <TagGroup title="Sözsüz">
          {nonverbal.map((t) => (
            <button key={t.tag} type="button" className="chip clickable" title={t.reads ? `Okunuşu: “${t.reads}”` : undefined}
              aria-label={`Sözsüz etiket ekle: ${t.tag}`} onClick={() => onInsert(`[${t.tag}]`)}>[{t.tag}]</button>
          ))}
        </TagGroup>
      )}
      <TagGroup title="Duraklama">
        {pauses.map((p) => (
          <button key={p.tag} type="button" className="chip clickable"
            title={Number.isFinite(p.ms) ? `${p.ms} ms duraklama` : undefined}
            aria-label={`Duraklama etiketi ekle: ${p.tag}`} onClick={() => onInsert(`[${p.tag}]`)}>
            [{p.tag}]{Number.isFinite(p.ms) && <span className="muted"> {fmtNum(p.ms / 1000)} sn</span>}
          </button>
        ))}
      </TagGroup>
      <div className="row">
        <label className="inline small" htmlFor={secsId}>
          Sayılı duraklama
          <input id={secsId} className="num-sm" type="number" min="0.1" max="10" step="0.1" value={secs}
            onChange={(e) => setSecs(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); addNumeric() }
            }} />
          sn
        </label>
        <button type="button" className="btn ghost small" disabled={value == null} onClick={addNumeric}
          aria-label={value != null ? `${value} saniyelik duraklama ekle` : 'Geçerli bir süre gir'}>
          + [{value ?? '?'} sn] ekle
        </button>
      </div>
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
  const samples = voice.samples?.length || 0
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
    </div>
  )
})

const NaturalnessPanel = memo(function NaturalnessPanel({ settings, levels, features, language, voicePauseScale, open, onToggle, onChange }) {
  const levelOptions = useMemo(() => {
    const list = levels.includes(settings.colloquial) ? levels : [...levels, settings.colloquial]
    return list.map((l) => [l, COLLOQUIAL_LABELS[l] || l])
  }, [levels, settings.colloquial])
  const missing = (k) => features[k] === false
  const note = (k) => (missing(k) ? 'bu sunucuda yok' : '')
  const pauseHint = Number.isFinite(voicePauseScale)
    ? `Bu sesin doğal ritmi ×${voicePauseScale.toFixed(2)} (otomatik uygulanır).`
    : 'Cümleler arasındaki duraklamaları uzatır ya da kısaltır.'

  return (
    <details className="panel" open={open} onToggle={onToggle}>
      <summary><b>Doğallık</b> <span className="muted small">— insan gibi duyulsun diye</span></summary>
      <div className="stack panel-body">
        <SelectField name="colloquial" label="Konuşma dili" value={settings.colloquial} options={levelOptions} onChange={onChange}
          hint={language === 'tr' ? 'Yazı dilini konuşur gibi okutur: "geleceğim" → "gelicem".' : 'Yalnızca Türkçe metinlerde etkili.'} />
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
  if (c.ref) bits.push(`ref: ${c.ref}`)
  if (c.exaggeration != null) bits.push(`vurgu ${c.exaggeration}`)
  if (c.speed != null) bits.push(`hız ${c.speed}×`)
  if (c.pause_ms) bits.push(`ardından ${c.pause_ms} ms`)
  if (c.breath || c.breath_before) bits.push('nefes')
  if (c.duration != null) bits.push(fmtDur(c.duration))
  return bits.join(' • ')
}

function ChunkDetails({ chunks }) {
  if (!Array.isArray(chunks) || !chunks.length) return null
  return (
    <details className="chunks">
      <summary className="muted small">Cümle cümle ne yapıldı ({chunks.length} parça)</summary>
      <ul className="list">
        {chunks.map((c, i) => (
          <li key={i} className="item small">
            <div className="row between">
              <span><span className={`tag ${c.emotion ? 'emo' : ''}`}>{c.emotion || 'nötr'}</span> <span className="muted">{chunkMeta(c)}</span></span>
            </div>
            <div>{c.text}</div>
          </li>
        ))}
      </ul>
    </details>
  )
}

const VariantResult = memo(function VariantResult({ result, languages, autoPlay, favs, onFavorite, onRegenerate, onPinSeed }) {
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
      <ColloquialChanges changes={gen.params?.colloquial_changes} />
      <ChunkDetails chunks={gen.params?.chunks} />
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
    latestSaveRef.current = { v: 3, settings, voiceId, text, ui }
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
            <TagBox id={tagsId} emotions={catalog.emotions} nonverbal={catalog.nonverbal} pauses={catalog.pauses} onInsert={insertToken} />
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
            voicePauseScale={voicePauseScale} open={ui.natural} onToggle={onToggleNatural} onChange={setField} />
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
            onFavorite={markFavorite} onRegenerate={regenerate} onPinSeed={pinSeed} />
        ) : (
          <p className="muted">Üretilen ses burada görünecek.</p>
        )}
      </section>
    </div>
  )
}
