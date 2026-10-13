// SesKlon API istemcisi. Tüm uç noktalar burada; hata mesajları Türkçedir.
// Sözleşme: docs/SOZLESME.md bölüm 7–8, docs/SOZLESME2.md bölüm 9–10 (diyalog, altyazı, telaffuz, tepki, iyileştirme).

const KEY_STORAGE = 'sesklon_api_key'

export function getApiKey() {
  try { return localStorage.getItem(KEY_STORAGE) || '' } catch { return '' }
}
export function setApiKey(k) {
  try { k ? localStorage.setItem(KEY_STORAGE, k) : localStorage.removeItem(KEY_STORAGE) } catch {}
}

/** İsteğe eklenecek kimlik başlıkları (Player gibi doğrudan fetch yapanlar için). */
export function authHeaders(extra) {
  const h = { ...(extra || {}) }
  const key = getApiKey()
  if (key) h['X-API-Key'] = key
  return h
}

// ---------- hata sınıfları ----------

export class ApiError extends Error {
  constructor(message, { status = 0, data = null, path = '', network = false } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
    this.path = path
    this.network = network
  }
}

/** waitJob, iş "cancelled" durumuna geçince bunu fırlatır. */
export class CancelledError extends Error {
  constructor(message = 'İptal edildi', job = null) {
    super(message)
    this.name = 'CancelledError'
    this.cancelled = true
    this.job = job
  }
}

export const isCancelled = (err) => err instanceof CancelledError || err?.name === 'CancelledError'

const STATUS_TR = {
  400: 'Geçersiz istek.',
  401: 'API anahtarı gerekli veya geçersiz.',
  403: 'Bu işlem için yetkiniz yok.',
  404: 'İstenen kayıt veya uç nokta bulunamadı.',
  405: 'Bu işlem sunucuda desteklenmiyor.',
  408: 'İstek zaman aşımına uğradı.',
  409: 'Çakışma: kayıt başka bir işlemle değişmiş olabilir.',
  413: 'Dosya çok büyük.',
  415: 'Desteklenmeyen dosya türü.',
  422: 'Gönderilen veriler geçersiz.',
  429: 'Çok fazla istek gönderildi; biraz bekleyip tekrar deneyin.',
  500: 'Sunucuda bir hata oluştu.',
  502: 'Sunucuya ulaşılamıyor (ağ geçidi hatası).',
  503: 'Sunucu şu anda meşgul veya hazır değil.',
  504: 'Sunucu zamanında yanıt vermedi.',
}

// Sunucunun İngilizce varsayılan mesajları için karşılıklar.
const EN_TR = {
  'not found': 'Bulunamadı.',
  'method not allowed': 'Bu işlem sunucuda desteklenmiyor.',
  'internal server error': 'Sunucuda bir hata oluştu.',
  unauthorized: 'API anahtarı gerekli veya geçersiz.',
  forbidden: 'Bu işlem için yetkiniz yok.',
  'bad request': 'Geçersiz istek.',
  'request entity too large': 'Dosya çok büyük.',
  'payload too large': 'Dosya çok büyük.',
  'there was an error parsing the body': 'İstek gövdesi okunamadı.',
}

const FIELD_TR = {
  text: 'Metin', voice_id: 'Ses', language: 'Dil', exaggeration: 'Vurgu', cfg_weight: 'Sadakat (cfg)',
  temperature: 'Çeşitlilik', speed: 'Hız', seed: 'Tohum', format: 'Format', file: 'Dosya', name: 'Ad',
  emotion: 'Duygu', style: 'Stil', pause_scale: 'Duraklama çarpanı', variants: 'Varyant sayısı',
  colloquial: 'Konuşma dili', notes: 'Notlar', default_style: 'Varsayılan stil', consent: 'İzin onayı',
  limit: 'Sayfa boyutu', offset: 'Başlangıç', favorite: 'Favori', emotion_fx: 'Ses işleme', kind: 'Tür',
  breaths: 'Nefes', room_tone: 'Oda tonu', master: 'Mastering', q: 'Arama',
  // v4
  speakers: 'Konuşmacılar', narrator_voice_id: 'Anlatıcı sesi', consistency: 'Tutarlılık', qc: 'Kalite kontrol',
  fillers: 'Dolgu sözcükleri', chat_speak: 'Sohbet kısaltmaları', subtitles: 'Altyazı', word: 'Sözcük',
  reading: 'Okunuş', tag: 'Tepki', force: 'Zorla', punctuation_emotion: 'Noktalamaya göre duygu',
  auto_emotion: 'Otomatik duygu',
}

function validationMessage(items) {
  const parts = items.slice(0, 3).map((it) => {
    const loc = Array.isArray(it?.loc) ? it.loc.filter((x) => !['body', 'query', 'path', 'form', 'header'].includes(x)) : []
    const last = loc.length ? loc[loc.length - 1] : ''
    const field = last === '' ? '' : (FIELD_TR[last] || loc.join('.'))
    const t = String(it?.type || '')
    const ctx = it?.ctx || {}
    let why
    if (t === 'missing' || t.endsWith('.missing')) why = 'zorunlu alan eksik'
    else if (t.startsWith('string_too_long')) why = `çok uzun${ctx.max_length ? ` (en fazla ${ctx.max_length} karakter)` : ''}`
    else if (t.startsWith('string_too_short')) why = 'boş veya çok kısa'
    else if (/greater_than|less_than/.test(t)) {
      const lo = ctx.ge ?? ctx.gt
      const hi = ctx.le ?? ctx.lt
      why = lo != null && hi != null ? `${lo} ile ${hi} arasında olmalı` : lo != null ? `en az ${lo} olmalı` : hi != null ? `en fazla ${hi} olmalı` : 'izin verilen aralığın dışında'
    } else if (t.includes('pattern') || t.includes('enum') || t.includes('literal')) why = 'geçersiz değer'
    else if (/int_|float_|number|decimal/.test(t)) why = 'sayı olmalı'
    else if (t.startsWith('bool')) why = 'evet/hayır olmalı'
    else why = it?.msg || 'geçersiz'
    return field ? `${field}: ${why}` : why
  })
  return `Geçersiz istek — ${parts.join('; ')}${items.length > 3 ? ' …' : ''}`
}

function messageFrom(status, data, statusText) {
  let detail = null
  if (data && typeof data === 'object') detail = data.detail ?? data.message ?? data.error ?? null
  else if (typeof data === 'string' && data.length < 300 && !data.trim().startsWith('<')) detail = data
  if (typeof detail === 'string' && detail.trim()) return EN_TR[detail.trim().toLowerCase()] || detail.trim()
  if (Array.isArray(detail) && detail.length) return validationMessage(detail)
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
  return STATUS_TR[status] || `Beklenmeyen sunucu yanıtı (${status}${statusText ? ' ' + statusText : ''}).`
}

function emitUnauthorized(err) {
  try { api.onUnauthorized?.(err) } catch (e) { console.error(e) }
  try { window.dispatchEvent(new CustomEvent('sesklon:unauthorized', { detail: { message: err.message, path: err.path } })) } catch {}
}

const NETWORK_MSG = 'Sunucuya bağlanılamadı. Sunucunun çalıştığından ve ağ bağlantınızdan emin olun.'

async function readBody(res) {
  if (res.status === 204 || res.status === 205) return null
  const text = await res.text()
  if (!text) return null
  try { return JSON.parse(text) } catch { return text }
}

/** Ham istek: hata durumlarını Türkçe ApiError'a çevirir, başarılıysa Response döndürür. */
async function send(path, { method = 'GET', body, json, headers, timeout, signal } = {}) {
  const h = authHeaders(headers)
  let payload = body
  if (json !== undefined) {
    h['Content-Type'] = 'application/json'
    payload = JSON.stringify(json)
  }
  let ctrl = null
  let timer = 0
  if (timeout) {
    ctrl = new AbortController()
    timer = setTimeout(() => ctrl.abort(), timeout)
    if (signal) {
      if (signal.aborted) ctrl.abort()
      else signal.addEventListener('abort', () => ctrl.abort(), { once: true })
    }
  }
  let res
  try {
    res = await fetch(path, { method, headers: h, body: payload, signal: ctrl ? ctrl.signal : signal })
  } catch (e) {
    if (e?.name === 'AbortError') {
      if (signal?.aborted) throw e // çağıran iptal etti: olduğu gibi ilet
      throw new ApiError('Sunucu zamanında yanıt vermedi.', { status: 0, path, network: true })
    }
    throw new ApiError(NETWORK_MSG, { status: 0, path, network: true })
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) {
    const data = await readBody(res).catch(() => null)
    // Geliştirme vekil sunucusu (Vite) arka uç kapalıyken gövdesiz 5xx döndürür → bağlantı hatası say.
    const proxyDown = res.status >= 500 && (data == null || data === '')
    const err = new ApiError(proxyDown ? NETWORK_MSG : messageFrom(res.status, data, res.statusText), {
      status: res.status, data, path, network: proxyDown,
    })
    if (res.status === 401) emitUnauthorized(err)
    throw err
  }
  return res
}

/** JSON (veya metin) döndüren istek. */
export async function request(path, opts) {
  const res = await send(path, opts)
  return readBody(res)
}

// ---------- iş kuyruğu ----------

const wakers = new Map() // iş kimliği → bekleyen sorguyu hemen uyandıran fonksiyon

function sleep(ms, id) {
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(t)
      if (id && wakers.get(id) === done) wakers.delete(id)
      resolve()
    }
    const t = setTimeout(done, ms)
    if (id) wakers.set(id, done)
  })
}

/**
 * 202 ile dönen işi bitene kadar sorgular; her sorguda onProgress(job) çağrılır
 * (job.partial, job.eta_s, job.position alanları sunucudan geldiği gibi iletilir).
 * Sorgu aralığı: çalışırken 500 ms, sıradayken 1 sn. İptal edilen iş → CancelledError.
 */
export async function waitJob(job, onProgress) {
  if (!job || typeof job !== 'object' || !('status' in job)) return job // senkron sonuç (ör. wait:true)
  let j = job
  let failures = 0
  for (;;) {
    try { onProgress?.(j) } catch (e) { console.error(e) }
    const st = j.status
    if (st === 'done') return j.result
    if (st === 'cancelled' || (j.cancelled && st !== 'queued' && st !== 'running')) throw new CancelledError('İptal edildi', j)
    if (st === 'error' || st === 'failed') throw new ApiError(j.error || 'Üretim başarısız oldu.', { status: 500, data: j })
    if (st !== 'queued' && st !== 'running') {
      if (j.result !== undefined) return j.result
      throw new ApiError(`Bilinmeyen iş durumu: ${st}`, { data: j })
    }
    await sleep(st === 'running' ? 500 : 1000, j.id)
    try {
      j = await request(`/api/jobs/${encodeURIComponent(j.id)}`)
      failures = 0
    } catch (err) {
      if (err.status === 404) throw new ApiError('İş bulunamadı; sunucu yeniden başlatılmış olabilir.', { status: 404, path: err.path })
      if (err.status === 401 || err.status === 403) throw err
      failures += 1
      if (failures > 8) throw err
      await sleep(Math.min(5000, 400 * 2 ** failures)) // geçici kopukluk: bekleyip yeniden dene
    }
  }
}

// ---------- yardımcılar ----------

const enc = (v) => encodeURIComponent(String(v))

function formData(fields) {
  const fd = new FormData()
  for (const [k, v] of Object.entries(fields)) {
    if (v === undefined || v === null) continue
    fd.append(k, typeof v === 'boolean' ? (v ? 'true' : 'false') : v)
  }
  return fd
}

function filenameFromDisposition(cd) {
  if (!cd) return ''
  const star = /filename\*\s*=\s*([^']*)''([^;]+)/i.exec(cd)
  if (star) {
    try { return decodeURIComponent(star[2].trim().replace(/^"|"$/g, '')) } catch {}
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(cd)
  return plain ? plain[1].trim() : ''
}

function extForType(type) {
  const t = String(type || '').toLowerCase()
  if (t.includes('json')) return '.json'
  if (t.includes('tar')) return '.tar'
  if (t.includes('wav')) return '.wav'
  if (t.includes('mpeg')) return '.mp3'
  return '.zip'
}

function audioExt(type) {
  const t = String(type || '').toLowerCase()
  if (t.includes('ogg')) return '.ogg'
  if (t.includes('wav')) return '.wav'
  if (t.includes('mpeg') || t.includes('mp3')) return '.mp3'
  if (t.includes('mp4') || t.includes('m4a') || t.includes('aac')) return '.m4a'
  return '.webm'
}

/** Dosya alanı ekler; adı olmayan Blob'a (mikrofon kaydı) türüne uygun bir ad verir. */
function appendFile(fd, field, file, base = 'kayit') {
  if (typeof Blob !== 'undefined' && file instanceof Blob && !file.name) fd.append(field, file, `${base}${audioExt(file.type)}`)
  else fd.append(field, file)
}

const SUBTITLE_FORMATS = ['srt', 'vtt', 'json']
const subtitleFormat = (f) => {
  const s = String(f || 'srt').trim().toLowerCase()
  return SUBTITLE_FORMATS.includes(s) ? s : 'srt'
}

/** Sunucu 404'e kendi açıklamasını yazmadıysa (ör. "Not Found") genel mesaj yerine bağlama uygun mesaj verilir. */
function isGenericNotFound(data) {
  const d = data && typeof data === 'object' ? data.detail : data
  if (d == null || d === '') return true
  return typeof d === 'string' && /^not\s*found\.?$/i.test(d.trim())
}

/** GET …/subtitles?format= — 404'ü "bu üretimin altyazısı yok" olarak açıklar. */
async function fetchSubtitles(genId, format) {
  const fmt = subtitleFormat(format)
  try {
    return { res: await send(`/api/generations/${enc(genId)}/subtitles?format=${fmt}`), fmt }
  } catch (err) {
    if (err?.status === 404 && isGenericNotFound(err.data)) {
      throw new ApiError('Bu üretimin altyazısı yok. Altyazı, "Altyazı üret" açıkken üretilen seslerde bulunur.', {
        status: 404, data: err.data, path: err.path,
      })
    }
    throw err
  }
}

/** Blob'u tarayıcıda dosya olarak indirir. */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'indirme'
  a.rel = 'noopener'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30000)
}

// ---------- uç noktalar ----------

export const api = {
  /** 401 alındığında çağrılır (App, API anahtarı kutusunu açmak için atar). */
  onUnauthorized: null,
  request,
  waitJob,
  isCancelled,

  // sistem
  health: () => request('/api/health', { timeout: 10000 }),
  warmup: () => request('/api/warmup', { method: 'POST' }),
  stats: () => request('/api/stats', { timeout: 15000 }),

  // sesler
  voices: () => request('/api/voices'),
  voice: (id) => request(`/api/voices/${enc(id)}`),
  createVoice: ({ name, language, file, consent, ...extra }) => {
    const fd = formData({ ...extra, name: name ?? '', language: language || 'tr', consent: !!consent })
    fd.append('file', file)
    return request('/api/voices', { method: 'POST', body: fd })
  },
  /** PATCH /api/voices/{id} — {name, notes, default_style, pause_scale} (yalnızca verilen alanlar). */
  updateVoice: (id, fields = {}) => {
    const body = {}
    for (const [k, v] of Object.entries(fields || {})) if (v !== undefined) body[k] = v
    return request(`/api/voices/${enc(id)}`, { method: 'PATCH', json: body })
  },
  renameVoice: (id, name) => api.updateVoice(id, { name }),
  deleteVoice: (id) => request(`/api/voices/${enc(id)}`, { method: 'DELETE' }),
  addSample: (id, emotion, file) => {
    const fd = new FormData()
    fd.append('emotion', emotion)
    fd.append('file', file)
    return request(`/api/voices/${enc(id)}/samples`, { method: 'POST', body: fd })
  },
  deleteSample: (id, emotion) => request(`/api/voices/${enc(id)}/samples/${enc(emotion)}`, { method: 'DELETE' }),
  voiceAnalysis: (id) => request(`/api/voices/${enc(id)}/analysis`),
  /** Sesi dışa aktarır ve dosyayı indirir. */
  exportVoice: async (id, filename) => {
    const res = await send(`/api/voices/${enc(id)}/export`)
    const blob = await res.blob()
    const name = filename || filenameFromDisposition(res.headers.get('content-disposition')) || `sesklon-ses-${id}${extForType(blob.type)}`
    downloadBlob(blob, name)
  },
  importVoice: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/api/voices/import', { method: 'POST', body: fd })
  },

  // analiz (kaydetmeden)
  analyze: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/api/analyze', { method: 'POST', body: fd })
  },

  // üretim
  /**
   * POST /api/tts — payload olduğu gibi gönderilir. v4 alanları: speakers ({Ad: voice_id | null}; metin diyalogsa
   * diyalog modu), narrator_voice_id, consistency, qc, fillers, chat_speak, subtitles. Sonuç: üretim nesnesi
   * (params.turns, params.qc, params.timeline, params.consistency, params.nonverbal_used).
   */
  tts: async (payload, onProgress) => {
    const job = await request('/api/tts', { method: 'POST', json: payload })
    return waitJob(job, onProgress)
  },
  vc: async ({ voice_id, file, ...extra }, onProgress) => {
    const fd = formData({ ...extra, voice_id })
    fd.append('file', file)
    const job = await request('/api/vc', { method: 'POST', body: fd })
    return waitJob(job, onProgress)
  },

  // işler
  job: (id) => request(`/api/jobs/${enc(id)}`),
  jobs: () => request('/api/jobs'),
  cancelJob: async (id) => {
    const r = await request(`/api/jobs/${enc(id)}/cancel`, { method: 'POST' })
    wakers.get(id)?.() // bekleyen sorguyu hemen yenile
    return r
  },

  // geçmiş
  /**
   * GET /api/generations — parametresiz çağrı da çalışır. Her zaman dizi döner;
   * sunucu toplamı bildirirse (gövde `total` ya da X-Total-Count) dizinin `.total` alanına yazılır.
   */
  generations: async ({ limit = 100, offset = 0, kind, voice_id, q, favorite } = {}) => {
    const p = new URLSearchParams()
    if (limit != null) p.set('limit', String(limit))
    if (offset) p.set('offset', String(offset))
    if (kind) p.set('kind', kind)
    if (voice_id) p.set('voice_id', voice_id)
    if (q != null && String(q).trim()) p.set('q', String(q).trim())
    if (favorite != null && favorite !== '') p.set('favorite', favorite ? 'true' : 'false')
    const res = await send(`/api/generations?${p}`)
    const data = await readBody(res)
    const items = Array.isArray(data) ? data
      : Array.isArray(data?.items) ? data.items
        : Array.isArray(data?.generations) ? data.generations : []
    const hdr = res.headers.get('x-total-count')
    const total = data && !Array.isArray(data) && data.total != null ? Number(data.total) : hdr != null ? Number(hdr) : NaN
    if (Number.isFinite(total)) items.total = total
    return items
  },
  favorite: (id, on) => request(`/api/generations/${enc(id)}/favorite`, { method: 'POST', json: { favorite: !!on } }),
  deleteGeneration: (id) => request(`/api/generations/${enc(id)}`, { method: 'DELETE' }),

  // altyazı (üretimin zaman çizelgesinden; SOZLESME2 §9)
  /** Altyazıyı dosya olarak indirir (format: "srt" | "vtt" | "json"); ad Content-Disposition'dan. */
  subtitles: async (genId, format = 'srt') => {
    const { res, fmt } = await fetchSubtitles(genId, format)
    const blob = await res.blob()
    const name = filenameFromDisposition(res.headers.get('content-disposition')) || `sesklon-${genId}.${fmt}`
    downloadBlob(blob, name)
  },
  /** Altyazının metni (önizleme için). */
  subtitleText: async (genId, format = 'srt') => {
    const { res } = await fetchSubtitles(genId, format)
    return res.text()
  },

  // telaffuz sözlüğü
  /** GET /api/lexicon[?voice_id=] — girdiler: [{word, reading, scope: "global" | "voice"}] (sunucu yanıtı olduğu gibi). */
  lexicon: (voiceId) => request(`/api/lexicon${voiceId ? `?voice_id=${enc(voiceId)}` : ''}`),
  /** PUT /api/lexicon — voiceId verilirse yalnızca o sese özel girdi. */
  setLexicon: (word, reading, voiceId) => request('/api/lexicon', {
    method: 'PUT', json: { word, reading, ...(voiceId ? { voice_id: voiceId } : {}) },
  }),
  deleteLexicon: (word, voiceId) => {
    const p = new URLSearchParams({ word: String(word ?? '') })
    if (voiceId) p.set('voice_id', voiceId)
    return request(`/api/lexicon?${p}`, { method: 'DELETE' })
  },
  /** POST /api/lexicon/test → {normalized, changes: [...]} */
  testLexicon: (text, voiceId, language) => request('/api/lexicon/test', {
    method: 'POST', json: { text, ...(voiceId ? { voice_id: voiceId } : {}), ...(language ? { language } : {}) },
  }),

  // gerçek tepki kayıtları (gülme, iç çekme…)
  addNonverbal: (voiceId, tag, file) => {
    const fd = new FormData()
    fd.append('tag', tag)
    appendFile(fd, 'file', file, 'tepki')
    return request(`/api/voices/${enc(voiceId)}/nonverbal`, { method: 'POST', body: fd })
  },
  deleteNonverbal: (voiceId, tag) => request(`/api/voices/${enc(voiceId)}/nonverbal/${enc(tag)}`, { method: 'DELETE' }),

  // referans kaydı iyileştirme
  /** POST …/enhance → {before, after, report, applied}; force=true puan artmasa da uygular. */
  enhanceVoice: (voiceId, force = false) => request(`/api/voices/${enc(voiceId)}/enhance`, {
    method: 'POST', body: formData({ force: !!force }),
  }),
  undoEnhance: (voiceId) => request(`/api/voices/${enc(voiceId)}/enhance/undo`, { method: 'POST' }),
}
