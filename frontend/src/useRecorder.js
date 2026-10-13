import { useEffect, useRef, useState } from 'react'

/**
 * Tarayıcı mikrofonundan kayıt alır; sonuç bir File (webm/ogg/m4a) olarak döner.
 *
 * Geriye uyumlu API: { recording, seconds, error, start, stop }
 * Ek alanlar:
 *   level      0–1  anlık RMS seviyesi, −60…0 dBFS ölçeğine eşlenmiş (50 ms'de bir güncellenir)
 *   peak       0–1  son tepe genliği (doğrusal, ~1 sn tutulur); > 0.9 → kırpılma riski
 *   countdown       geri sayımda kalan saniye (0 = geri sayım yok)
 *   supported       tarayıcı mikrofondan kaydı destekliyor mu
 *   cancel()        kaydı ya da geri sayımı dosya üretmeden bırakır
 *
 * start({ countdown = 0, maxSeconds = 0 }) — önce mikrofon izni alınır ve seviye göstergesi çalışmaya başlar,
 *   geri sayım bitince kayıt başlar; maxSeconds > 0 ise o sürede kendiliğinden durur. Promise<boolean> döner.
 * stop() → Promise<File|null>
 * useRecorder({ onFile }) — kayıt her bittiğinde (elle ya da otomatik) onFile(file, { seconds, auto }) çağrılır.
 *   onFile kullanan bileşen stop()'un döndürdüğü dosyayı ayrıca işlememeli (aynı dosya iki kez gelir).
 */

const TICK_MS = 50
const FLOOR_DB = -60
const PEAK_HOLD_MS = 1000
const PEAK_DECAY = 0.85
const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
const IDLE = { recording: false, seconds: 0, countdown: 0, level: 0, peak: 0, error: '' }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** RMS genliğini (0–1) gösterge için 0–1 seviyeye çevirir: −60 dBFS → 0, 0 dBFS → 1. */
export function rmsToLevel(rms) {
  if (!(rms > 0)) return 0
  const db = 20 * Math.log10(rms)
  return Math.min(1, Math.max(0, (db - FLOOR_DB) / -FLOOR_DB))
}

function isSupported() {
  return typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof window.MediaRecorder !== 'undefined'
}

function unsupportedMessage() {
  if (typeof window !== 'undefined' && window.isSecureContext === false) {
    return 'Mikrofon yalnızca güvenli bağlantıda (https ya da localhost) kullanılabilir.'
  }
  return 'Bu tarayıcı mikrofondan kaydı desteklemiyor.'
}

function micError(e) {
  switch (e?.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Mikrofon izni verilmedi. Adres çubuğundaki simgeden izin verip tekrar deneyin.'
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'Mikrofon bulunamadı. Bir mikrofon bağlayıp tekrar deneyin.'
    case 'NotReadableError':
    case 'AbortError':
      return 'Mikrofon başka bir uygulama tarafından kullanılıyor olabilir.'
    default:
      return 'Mikrofona erişilemedi: ' + (e?.message || e)
  }
}

/** Dosya adı için ASCII zaman damgası: 20261013-153045 */
function timestamp() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

/** React'tan bağımsız kayıt denetleyicisi; durum değişikliklerini setState ile bildirir. */
function createController(setState, optsRef) {
  const rt = {
    session: 0, mounted: false, pending: false,
    stream: null, ctx: null, analyser: null, floatBuf: null, byteBuf: null,
    rec: null, chunks: [], timer: null, startedAt: 0, maxSeconds: 0,
    auto: false, discard: false, peakHold: 0, holdUntil: 0, resolvers: [],
  }

  // Yalnızca değişen alan varsa yeni durum üret (50 ms'lik ölçümler gereksiz render yapmasın).
  const patch = (p) => {
    if (!rt.mounted) return
    setState((s) => {
      for (const k in p) if (s[k] !== p[k]) return { ...s, ...p }
      return s
    })
  }

  function releaseMedia() {
    clearInterval(rt.timer)
    rt.timer = null
    rt.stream?.getTracks().forEach((t) => t.stop())
    rt.stream = null
    if (rt.ctx) {
      rt.ctx.close().catch(() => {})
      rt.ctx = null
    }
    rt.analyser = null
    rt.rec = null
    rt.startedAt = 0
    patch({ recording: false, countdown: 0, level: 0, peak: 0 })
  }

  function measure() {
    const an = rt.analyser
    if (!an) return null
    let sum = 0
    let pk = 0
    let n
    if (an.getFloatTimeDomainData) {
      const b = rt.floatBuf
      an.getFloatTimeDomainData(b)
      n = b.length
      for (let i = 0; i < n; i++) {
        const v = b[i]
        sum += v * v
        const a = v < 0 ? -v : v
        if (a > pk) pk = a
      }
    } else {
      const b = rt.byteBuf
      an.getByteTimeDomainData(b)
      n = b.length
      for (let i = 0; i < n; i++) {
        const v = (b[i] - 128) / 128
        sum += v * v
        const a = v < 0 ? -v : v
        if (a > pk) pk = a
      }
    }
    return { rms: Math.sqrt(sum / n), pk }
  }

  function tick() {
    const now = performance.now()
    const p = {}
    const m = measure()
    if (m) {
      if (m.pk >= rt.peakHold) {
        rt.peakHold = m.pk
        rt.holdUntil = now + PEAK_HOLD_MS
      } else if (now > rt.holdUntil) {
        rt.peakHold = Math.max(m.pk, rt.peakHold * PEAK_DECAY)
      }
      p.level = Math.round(rmsToLevel(m.rms) * 100) / 100
      p.peak = Math.round(Math.min(1, rt.peakHold) * 100) / 100
    }
    if (rt.rec && rt.startedAt) {
      const elapsed = (now - rt.startedAt) / 1000
      p.seconds = Math.floor(elapsed)
      if (rt.maxSeconds > 0 && elapsed >= rt.maxSeconds && rt.rec.state === 'recording') {
        rt.auto = true
        rt.rec.stop()
      }
    }
    patch(p)
  }

  function finish(rec) {
    const chunks = rt.chunks
    const seconds = rt.startedAt ? (performance.now() - rt.startedAt) / 1000 : 0
    const { auto, discard } = rt
    rt.chunks = []
    rt.auto = false
    rt.discard = false
    releaseMedia()
    let file = null
    if (!discard && chunks.length) {
      const type = (rec.mimeType || chunks[0].type || 'audio/webm').split(';')[0]
      const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm'
      file = new File(chunks, `kayit-${timestamp()}.${ext}`, { type })
    }
    const resolvers = rt.resolvers
    rt.resolvers = []
    resolvers.forEach((resolve) => resolve(file))
    if (file && rt.mounted) optsRef.current?.onFile?.(file, { seconds: Math.round(seconds * 10) / 10, auto })
  }

  function attachMeter(ctx, stream) {
    if (!ctx) return
    try {
      const an = ctx.createAnalyser()
      an.fftSize = 2048
      ctx.createMediaStreamSource(stream).connect(an) // hoparlöre bağlanmaz → geri besleme yok
      rt.analyser = an
      rt.floatBuf = new Float32Array(an.fftSize)
      rt.byteBuf = new Uint8Array(an.fftSize)
    } catch {
      rt.analyser = null // seviye göstergesi isteğe bağlı; kayıt yine çalışır
    }
  }

  async function start(opts = {}) {
    if (rt.stream || rt.pending) return false
    const o = { ...optsRef.current, ...opts }
    const countdown = Math.max(0, Math.floor(Number(o.countdown) || 0))
    const maxSeconds = Math.max(0, Number(o.maxSeconds) || 0)
    patch({ error: '' })
    if (!isSupported()) {
      patch({ error: unsupportedMessage() })
      return false
    }
    const session = ++rt.session

    // AudioContext tıklama anında oluşturulur: Safari/iOS kullanıcı etkileşimi dışında başlatmaz.
    let ctx = null
    try {
      const AC = window.AudioContext || window.webkitAudioContext
      ctx = AC ? new AC() : null
      ctx?.resume?.().catch(() => {})
    } catch {
      ctx = null
    }

    rt.pending = true
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    } catch (e) {
      rt.pending = false
      ctx?.close().catch(() => {})
      if (session === rt.session) patch({ error: micError(e) })
      return false
    }
    rt.pending = false
    if (session !== rt.session || !rt.mounted) {
      // İzin beklenirken iptal edildi ya da bileşen kapandı.
      stream.getTracks().forEach((t) => t.stop())
      ctx?.close().catch(() => {})
      return false
    }

    rt.stream = stream
    rt.ctx = ctx
    rt.peakHold = 0
    rt.holdUntil = 0
    attachMeter(ctx, stream)
    rt.timer = setInterval(tick, TICK_MS)

    for (let n = countdown; n > 0; n--) {
      patch({ countdown: n })
      await sleep(1000)
      if (session !== rt.session) return false // geri sayım sırasında vazgeçildi
    }
    patch({ countdown: 0 })

    let rec
    try {
      const mime = MIME_TYPES.find((m) => MediaRecorder.isTypeSupported?.(m)) || ''
      rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    } catch (e) {
      releaseMedia()
      patch({ error: 'Kayıt başlatılamadı: ' + (e?.message || e) })
      return false
    }
    rt.chunks = []
    rt.auto = false
    rt.discard = false
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size) rt.chunks.push(e.data)
    }
    rec.onstop = () => finish(rec)
    rec.onerror = (e) => patch({ error: 'Kayıt hatası: ' + (e?.error?.message || 'bilinmeyen hata') })
    rt.rec = rec
    rt.maxSeconds = maxSeconds
    rt.startedAt = performance.now()
    rec.start(250)
    patch({ recording: true, seconds: 0 })
    return true
  }

  function stop() {
    return new Promise((resolve) => {
      if (rt.rec && rt.rec.state !== 'inactive') {
        rt.resolvers.push(resolve)
        rt.rec.stop()
        return
      }
      // Geri sayım ya da izin bekleniyor: dosya yok, yalnızca bırak.
      rt.session++
      if (rt.stream) releaseMedia()
      resolve(null)
    })
  }

  function cancel() {
    if (rt.rec && rt.rec.state !== 'inactive') {
      rt.discard = true
      rt.rec.stop()
      return
    }
    rt.session++
    if (rt.stream) releaseMedia()
  }

  function mount() {
    rt.mounted = true
  }

  function unmount() {
    rt.mounted = false
    rt.session++
    if (rt.rec && rt.rec.state !== 'inactive') {
      rt.discard = true
      try { rt.rec.stop() } catch { /* zaten durmuş */ }
    }
    releaseMedia()
  }

  return { start, stop, cancel, mount, unmount }
}

export function useRecorder(options = {}) {
  const [state, setState] = useState(IDLE)
  const optsRef = useRef(options)
  optsRef.current = options
  const ctlRef = useRef(null)
  if (!ctlRef.current) ctlRef.current = createController(setState, optsRef)
  const ctl = ctlRef.current
  const [supported] = useState(isSupported)

  useEffect(() => {
    ctl.mount()
    return ctl.unmount // sekme değişince mikrofon serbest bırakılır
  }, [ctl])

  return { ...state, supported, start: ctl.start, stop: ctl.stop, cancel: ctl.cancel }
}
