import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { authHeaders } from '../api'

/* ---------- biçimlendirme (Generate / History / Voices bunları kullanır) ---------- */

export function fmtDur(s) {
  if (s == null || s === '' || !Number.isFinite(+s)) return ''
  const v = +s
  if (v < 60) return `${v.toFixed(1)} sn`
  const t = Math.round(v)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const sec = String(t % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

export function fmtDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return String(iso)
    return d.toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' })
  } catch { return String(iso) }
}

/** Oynatıcı saati: 0:07, 1:05, 1:02:03 */
export function fmtClock(s) {
  if (s == null || !Number.isFinite(+s) || +s < 0) return '0:00'
  const t = Math.floor(+s)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const sec = String(t % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

/* ---------- aynı anda tek oynatıcı ---------- */

/** Modül düzeyi olay yolu: "play" (detail = oynatıcı kimliği), "stop", "theme". */
export const playerBus = new EventTarget()

/** Çalan tüm oynatıcıları durdurur. */
export function stopAllPlayers() {
  playerBus.dispatchEvent(new CustomEvent('stop'))
}

let themeWatching = false
function watchTheme() {
  if (themeWatching || typeof window === 'undefined') return
  themeWatching = true
  const fire = () => playerBus.dispatchEvent(new CustomEvent('theme'))
  try { new MutationObserver(fire).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] }) } catch {}
  try { window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', fire) } catch {}
}

/* ---------- dalga formu verisi ---------- */

const PEAK_COUNT = 400
const MAX_DECODE_BYTES = 80 * 1024 * 1024
const MAX_PARALLEL = 3
const peakCache = new Map() // src → Promise<{ peaks, duration }>
const waiting = []
let active = 0
let decodeCtx = null

function getDecodeCtx() {
  if (decodeCtx) return decodeCtx
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext
  // Düşük örnekleme hızı belleği korur; tepe görselleştirmesi için yeterli.
  for (const sr of [8000, 22050, 44100]) {
    try { if (OAC) { decodeCtx = new OAC(1, 1, sr); return decodeCtx } } catch {}
  }
  const AC = window.AudioContext || window.webkitAudioContext
  if (AC) decodeCtx = new AC()
  return decodeCtx
}

function decodeAudio(buf) {
  const ctx = getDecodeCtx()
  if (!ctx) return Promise.reject(new Error('Web Audio desteklenmiyor'))
  return new Promise((resolve, reject) => {
    const p = ctx.decodeAudioData(buf, resolve, reject)
    if (p && typeof p.then === 'function') p.then(resolve, reject)
  })
}

function computePeaks(ab, n = PEAK_COUNT) {
  const chans = []
  for (let c = 0; c < ab.numberOfChannels; c++) chans.push(ab.getChannelData(c))
  const len = ab.length
  const out = new Float32Array(n)
  const step = len / n
  let max = 0
  for (let i = 0; i < n; i++) {
    const start = Math.floor(i * step)
    const end = Math.min(len, Math.max(start + 1, Math.floor((i + 1) * step)))
    let peak = 0
    for (const d of chans) {
      for (let j = start; j < end; j++) {
        const v = d[j] < 0 ? -d[j] : d[j]
        if (v > peak) peak = v
      }
    }
    out[i] = peak
    if (peak > max) max = peak
  }
  const norm = max > 1e-4 ? 1 / max : 0
  for (let i = 0; i < n; i++) out[i] = Math.pow(out[i] * norm, 0.8)
  return out
}

function schedule(task) {
  return new Promise((resolve, reject) => {
    const run = () => {
      active += 1
      Promise.resolve().then(task).then(resolve, reject).finally(() => {
        active -= 1
        const next = waiting.shift()
        if (next) next()
      })
    }
    if (active < MAX_PARALLEL) run()
    else waiting.push(run)
  })
}

function isSameOrigin(src) {
  try {
    const u = new URL(src, window.location.href)
    return u.origin === window.location.origin && /^https?:$/.test(u.protocol)
  } catch { return false }
}

/** Ses dosyasını indirip çözer ve 400 tepe değeri döndürür (önbellekli, en fazla 3 eşzamanlı). */
export function loadPeaks(src) {
  const hit = peakCache.get(src)
  if (hit) {
    peakCache.delete(src)
    peakCache.set(src, hit)
    return hit
  }
  const p = schedule(async () => {
    const res = await fetch(src, isSameOrigin(src) ? { headers: authHeaders() } : undefined)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const len = Number(res.headers.get('content-length') || 0)
    if (len > MAX_DECODE_BYTES) throw new Error('Dosya dalga formu için çok büyük')
    const buf = await res.arrayBuffer()
    if (buf.byteLength > MAX_DECODE_BYTES) throw new Error('Dosya dalga formu için çok büyük')
    const ab = await decodeAudio(buf)
    return { peaks: computePeaks(ab), duration: ab.duration }
  })
  peakCache.set(src, p)
  p.catch(() => { if (peakCache.get(src) === p) peakCache.delete(src) })
  while (peakCache.size > 150) peakCache.delete(peakCache.keys().next().value)
  return p
}

function resample(peaks, n) {
  if (n >= peaks.length) return peaks
  const out = new Float32Array(n)
  const ratio = peaks.length / n
  for (let i = 0; i < n; i++) {
    const s = Math.floor(i * ratio)
    const e = Math.max(s + 1, Math.floor((i + 1) * ratio))
    let m = 0
    for (let j = s; j < e; j++) if (peaks[j] > m) m = peaks[j]
    out[i] = m
  }
  return out
}

/* ---------- yardımcılar ---------- */

const RATES = [0.75, 1, 1.25, 1.5]
const rateLabel = (r) => `${String(r).replace('.', ',')}×`
let preferredRate = 1 // kullanıcı bir oynatıcıda hızı değiştirince yenileri de öyle başlar

function absoluteUrl(src) {
  try { return new URL(src, window.location.href).href } catch { return src }
}

function legacyCopy(text) {
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    ta.style.pointerEvents = 'none'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  } catch { return false }
}

function fileNameFrom(src) {
  try {
    const last = new URL(src, window.location.href).pathname.split('/').pop()
    return decodeURIComponent(last || '') || 'ses'
  } catch { return 'ses' }
}

const svgProps = { viewBox: '0 0 24 24', width: 16, height: 16, 'aria-hidden': true, focusable: 'false' }
const IconPlay = () => <svg {...svgProps}><path fill="currentColor" d="M8 5.6v12.8a1 1 0 0 0 1.53.85l10.04-6.4a1 1 0 0 0 0-1.7L9.53 4.75A1 1 0 0 0 8 5.6z" /></svg>
const IconPause = () => <svg {...svgProps}><path fill="currentColor" d="M6.5 5h4v14h-4zM13.5 5h4v14h-4z" /></svg>
const strokeProps = { ...svgProps, width: 15, height: 15, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }
const IconDownload = () => <svg {...strokeProps}><path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19.5h14" /></svg>
const IconLink = () => <svg {...strokeProps}><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 1 0-5.66-5.66l-1 1" /><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 1 0 5.66 5.66l1-1" /></svg>
const IconCheck = () => <svg {...strokeProps}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>

/* ---------- bileşen ---------- */

/**
 * <Player src downloadName autoPlay compact title />
 * Dalga formu (tıkla/sürükle ile konum), hız, indirme, bağlantı kopyalama, klavye (odaklıyken:
 * boşluk oynat/duraklat, ←/→ 5 sn). compact: küçük düğme + 28 px dalga + süre.
 * Çözümleme başarısız olursa tarayıcının sade <audio> oynatıcısına düşer.
 */
export default function Player(props) {
  if (!props.src) return null
  return <PlayerView key={props.src} {...props} />
}

function PlayerView({ src, downloadName, autoPlay = false, compact = false, title }) {
  const uid = useId()
  const rootRef = useRef(null)
  const audioRef = useRef(null)
  const waveRef = useRef(null)
  const canvasRef = useRef(null)
  const timeRef = useRef(null)
  const geomRef = useRef(null)
  const hoverRef = useRef(null)
  const dragRef = useRef(null)
  const durRef = useRef(0)
  const copyTimer = useRef(0)

  const [visible, setVisible] = useState(!!autoPlay)
  const [peaks, setPeaks] = useState(null)
  const [decodedDur, setDecodedDur] = useState(0)
  const [mediaDur, setMediaDur] = useState(0)
  const [mode, setMode] = useState('wave') // wave | fallback
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(preferredRate)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')

  const dur = Number.isFinite(mediaDur) && mediaDur > 0 ? mediaDur : decodedDur
  durRef.current = dur

  // Görünür olunca yükle (geçmiş listesinde onlarca oynatıcı olabilir).
  useEffect(() => {
    if (visible) return
    const el = rootRef.current
    if (!el || typeof IntersectionObserver === 'undefined') { setVisible(true); return }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setVisible(true); io.disconnect() }
    }, { rootMargin: '300px 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [visible])

  useEffect(() => {
    if (!visible) return
    let alive = true
    loadPeaks(src)
      .then((r) => { if (alive) { setPeaks(r.peaks); setDecodedDur(r.duration || 0) } })
      .catch(() => { if (alive) setMode('fallback') })
    return () => { alive = false }
  }, [visible, src])

  // Hız
  useEffect(() => {
    const a = audioRef.current
    if (!a) return
    a.defaultPlaybackRate = rate
    a.playbackRate = rate
  }, [rate])

  // Başka bir oynatıcı başlayınca dur; "stop" ile hepsi durur.
  useEffect(() => {
    const onPlayOther = (e) => { if (e.detail !== uid) audioRef.current?.pause() }
    const onStop = () => audioRef.current?.pause()
    playerBus.addEventListener('play', onPlayOther)
    playerBus.addEventListener('stop', onStop)
    return () => {
      playerBus.removeEventListener('play', onPlayOther)
      playerBus.removeEventListener('stop', onStop)
    }
  }, [uid])

  useEffect(() => () => clearTimeout(copyTimer.current), [])

  const draw = useCallback(() => {
    const cv = canvasRef.current
    const a = audioRef.current
    const d = durRef.current
    const cur = a ? a.currentTime || 0 : 0
    const started = cur > 0 || (a && !a.paused)
    if (timeRef.current) {
      timeRef.current.textContent = compact ? fmtClock(started ? cur : d) : `${fmtClock(cur)} / ${fmtClock(d)}`
    }
    const sl = waveRef.current
    if (sl) {
      sl.setAttribute('aria-valuenow', String(Math.round(cur)))
      sl.setAttribute('aria-valuemax', String(Math.max(0, Math.round(d))))
      sl.setAttribute('aria-valuetext', `${fmtClock(cur)} / ${fmtClock(d)}`)
    }
    if (!cv) return
    const cssW = cv.clientWidth
    const cssH = cv.clientHeight
    if (!cssW || !cssH) return
    const dpr = Math.min(window.devicePixelRatio || 1, 3)
    const W = Math.round(cssW * dpr)
    const H = Math.round(cssH * dpr)
    if (cv.width !== W) cv.width = W
    if (cv.height !== H) cv.height = H
    const g = cv.getContext('2d')
    if (!g) return
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    g.clearRect(0, 0, cssW, cssH)

    const cs = getComputedStyle(cv)
    const col = (name, fb) => cs.getPropertyValue(name).trim() || fb
    const cBase = col('--wave-base', '#3a4157')
    const grad = g.createLinearGradient(0, 0, cssW, 0)
    grad.addColorStop(0, col('--wave-played', '#8b5cf6'))
    grad.addColorStop(1, col('--wave-played-2', '#22d3ee'))
    const prog = d > 0 ? Math.min(1, Math.max(0, cur / d)) : 0

    if (peaks) {
      const n = Math.max(8, Math.min(peaks.length, Math.floor(cssW / 3)))
      const key = `${n}|${cssW}|${cssH}`
      let geo = geomRef.current
      if (!geo || geo.peaks !== peaks || geo.key !== key) {
        const bars = resample(peaks, n)
        const step = cssW / n
        const bw = Math.max(1, Math.min(step * 0.62, 5))
        const maxH = cssH - 2
        const path = new Path2D()
        const round = typeof path.roundRect === 'function'
        for (let i = 0; i < n; i++) {
          const h = Math.max(2, bars[i] * maxH)
          const x = i * step + (step - bw) / 2
          const y = (cssH - h) / 2
          if (round) path.roundRect(x, y, bw, h, bw / 2)
          else path.rect(x, y, bw, h)
        }
        geo = geomRef.current = { peaks, key, path }
      }
      g.fillStyle = cBase
      g.fill(geo.path)
      if (prog > 0) {
        g.save()
        g.beginPath()
        g.rect(0, 0, cssW * prog, cssH)
        g.clip()
        g.fillStyle = grad
        g.fill(geo.path)
        g.restore()
      }
    } else {
      const y = cssH / 2 - 1
      g.fillStyle = cBase
      g.fillRect(0, y, cssW, 2)
      if (prog > 0) { g.fillStyle = grad; g.fillRect(0, y, cssW * prog, 2) }
    }
    if (hoverRef.current != null) {
      g.fillStyle = col('--wave-hover', 'rgba(255,255,255,.35)')
      g.fillRect(Math.round(hoverRef.current * cssW) - 0.5, 0, 1, cssH)
    }
    if (started) {
      g.fillStyle = col('--wave-head', '#ffffff')
      g.fillRect(Math.min(cssW - 2, Math.max(0, prog * cssW - 1)), 0, 2, cssH)
    }
  }, [peaks, compact])

  useEffect(() => { draw() }, [draw, dur, mode, playing])

  // Çalarken her karede konum çizgisi
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => { draw(); raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, draw])

  // Boyut değişimi ve tema değişimi
  useEffect(() => {
    const el = waveRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => draw())
    ro.observe(el)
    return () => ro.disconnect()
  }, [draw, mode])

  useEffect(() => {
    watchTheme()
    const on = () => draw()
    playerBus.addEventListener('theme', on)
    return () => playerBus.removeEventListener('theme', on)
  }, [draw])

  const toggle = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    if (a.paused || a.ended) {
      setError('')
      const p = a.play()
      if (p && typeof p.catch === 'function') {
        p.catch((err) => {
          if (err?.name === 'NotAllowedError') setError('Tarayıcı oynatmaya izin vermedi; tekrar deneyin.')
          else if (err?.name !== 'AbortError') setError('Ses oynatılamadı.')
        })
      }
    } else a.pause()
  }, [])

  const seekTo = useCallback((t) => {
    const a = audioRef.current
    const d = durRef.current
    if (!a || !(d > 0)) return
    const nt = Math.min(Math.max(0, t), Math.max(0, d - 0.01))
    try { a.currentTime = nt } catch {}
    draw()
  }, [draw])

  const ratioAt = (clientX) => {
    const el = waveRef.current
    if (!el) return 0
    const r = el.getBoundingClientRect()
    return r.width ? Math.min(1, Math.max(0, (clientX - r.left) / r.width)) : 0
  }

  // Fare: basınca konumlan, sürükle. Dokunmatik: dokun-bırak ile konumlan, yatay sürükleme ile tara
  // (dikey kaydırma sayfayı kaydırmaya devam eder).
  function onPointerDown(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    dragRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY, mouse: e.pointerType === 'mouse', scrub: e.pointerType === 'mouse' }
    try { e.currentTarget.setPointerCapture(e.pointerId) } catch {}
    if (e.pointerType === 'mouse') seekTo(ratioAt(e.clientX) * durRef.current)
  }
  function onPointerMove(e) {
    const r = ratioAt(e.clientX)
    if (e.pointerType === 'mouse') hoverRef.current = r
    const dr = dragRef.current
    if (dr && dr.id === e.pointerId) {
      if (!dr.scrub && Math.abs(e.clientX - dr.x) > 6 && Math.abs(e.clientX - dr.x) > Math.abs(e.clientY - dr.y)) dr.scrub = true
      if (dr.scrub) { seekTo(r * durRef.current); return }
    }
    if (audioRef.current?.paused) draw()
  }
  function onPointerUp(e) {
    const dr = dragRef.current
    dragRef.current = null
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch {}
    if (dr && !dr.mouse && !dr.scrub) seekTo(ratioAt(e.clientX) * durRef.current)
  }
  function onPointerCancel() { dragRef.current = null }
  function onPointerLeave() {
    hoverRef.current = null
    if (audioRef.current?.paused) draw()
  }

  function onKeyDown(e) {
    if (mode !== 'wave' || e.altKey || e.ctrlKey || e.metaKey) return
    const tag = e.target?.tagName
    if (tag === 'SELECT' || tag === 'INPUT' || tag === 'TEXTAREA') return
    const k = e.key
    if (k === ' ' || k === 'Spacebar') {
      if (tag === 'BUTTON' || tag === 'A') return // düğmenin kendi etkinleştirmesi
      e.preventDefault()
      toggle()
    } else if (k === 'ArrowLeft' || k === 'ArrowRight') {
      e.preventDefault()
      seekTo((audioRef.current?.currentTime || 0) + (k === 'ArrowLeft' ? -5 : 5))
    } else if (k === 'Home') {
      e.preventDefault()
      seekTo(0)
    } else if (k === 'End') {
      e.preventDefault()
      seekTo(durRef.current)
    }
  }

  async function copyLink() {
    const url = absoluteUrl(src)
    let ok = false
    try {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(url); ok = true }
    } catch {}
    if (!ok) ok = legacyCopy(url)
    if (!ok) { window.prompt('Bağlantıyı kopyalayın:', url); return }
    setCopied(true)
    clearTimeout(copyTimer.current)
    copyTimer.current = setTimeout(() => setCopied(false), 1600)
  }

  const onMeta = (e) => {
    const d = e.currentTarget.duration
    if (Number.isFinite(d) && d > 0) setMediaDur(d)
    e.currentTarget.playbackRate = rate
  }
  const onPlay = () => {
    setPlaying(true)
    playerBus.dispatchEvent(new CustomEvent('play', { detail: uid }))
  }
  const onPause = () => setPlaying(false)
  const onEnded = () => { setPlaying(false); draw() }
  const onSeeked = () => { if (audioRef.current?.paused) draw() }
  const onAudioError = () => {
    if (audioRef.current?.error) setError('Ses dosyası yüklenemedi.')
  }

  const showLink = !/^(blob|data):/i.test(src)
  const name = downloadName || fileNameFrom(src)
  const label = title ? `Oynatıcı: ${title}` : 'Ses oynatıcı'

  const tools = !compact && (
    <div className="player-tools">
      {mode === 'wave' && (
        <select className="rate" value={rate} aria-label="Oynatma hızı" title="Oynatma hızı"
          onChange={(e) => { const r = Number(e.target.value); preferredRate = r; setRate(r) }}>
          {RATES.map((r) => <option key={r} value={r}>{rateLabel(r)}</option>)}
        </select>
      )}
      <a className="btn ghost small" href={src} download={name} title="Ses dosyasını indir"><IconDownload /> İndir</a>
      {showLink && (
        <button type="button" className={`btn ghost small${copied ? ' copied' : ''}`} onClick={copyLink} title="Bağlantıyı panoya kopyala">
          {copied ? <><IconCheck /> Kopyalandı</> : <><IconLink /> Bağlantıyı kopyala</>}
        </button>
      )}
    </div>
  )

  return (
    <div
      ref={rootRef}
      className={`player${compact ? ' compact' : ''}${mode === 'fallback' ? ' fallback' : ''}${playing ? ' playing' : ''}`}
      role="group"
      aria-label={label}
      title={compact && title ? title : undefined}
      onKeyDown={onKeyDown}
    >
      {/* Aynı <audio> öğesi her iki kipte de kullanılır; yedek kipte denetimleri görünür olur. */}
      <audio
        ref={audioRef}
        src={src}
        preload={visible ? 'metadata' : 'none'}
        autoPlay={autoPlay}
        controls={mode === 'fallback'}
        onPlay={onPlay}
        onPause={onPause}
        onEnded={onEnded}
        onLoadedMetadata={onMeta}
        onDurationChange={onMeta}
        onSeeked={onSeeked}
        onError={onAudioError}
      />
      {mode === 'wave' ? (
        <>
          {!compact && title && <div className="player-title">{title}</div>}
          <div className="player-main">
            <button type="button" className="play-btn" onClick={toggle}
              aria-label={playing ? 'Duraklat' : 'Oynat'} title={playing ? 'Duraklat (boşluk)' : 'Oynat (boşluk)'}>
              {playing ? <IconPause /> : <IconPlay />}
            </button>
            <div
              ref={waveRef}
              className={`wave-wrap${visible && !peaks ? ' loading' : ''}`}
              role="slider"
              tabIndex={0}
              aria-label="Oynatma konumu (←/→ 5 sn)"
              aria-valuemin={0}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerCancel}
              onPointerLeave={onPointerLeave}
            >
              <canvas ref={canvasRef} className="wave" aria-hidden="true" />
            </div>
            {compact && <span ref={timeRef} className="time" />}
          </div>
          {!compact && (
            <div className="player-bar">
              <span ref={timeRef} className="time" />
              {tools}
            </div>
          )}
        </>
      ) : tools}
      {error && <div className="player-error" role="alert">{error}</div>}
    </div>
  )
}
