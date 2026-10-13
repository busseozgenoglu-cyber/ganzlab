import { Component, Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { api, getApiKey, setApiKey } from './api'
import Voices from './components/Voices'
import Generate from './components/Generate'
import Convert from './components/Convert'
import History from './components/History'

const TABS = [
  { id: 'generate', label: 'Seslendir', hash: 'seslendir', key: '1' },
  { id: 'voices', label: 'Sesler', hash: 'sesler', key: '2' },
  { id: 'convert', label: 'Dönüştür', hash: 'donustur', key: '3' },
  { id: 'history', label: 'Geçmiş', hash: 'gecmis', key: '4' },
]
const GEN_PAGE = 50 // History'nin sayfa boyutuyla aynı
const THEME_KEY = 'sesklon_theme'
const GUIDE_KEY = 'sesklon_guide_hidden'
const READY_KEY = 'sesklon_model_ready_once'
const THEME_COLORS = { dark: '#0d0f14', light: '#f6f7fb' }

const SHORTCUTS = [
  { keys: ['1'], desc: 'Seslendir sekmesi' },
  { keys: ['2'], desc: 'Sesler sekmesi' },
  { keys: ['3'], desc: 'Dönüştür sekmesi' },
  { keys: ['4'], desc: 'Geçmiş sekmesi' },
  { keys: ['?'], desc: 'Bu kısayol listesini aç / kapat' },
  { keys: ['Esc'], desc: 'Açık pencereyi kapat' },
  { keys: ['Ctrl', 'Enter'], sep: '+', desc: 'Metni seslendir (metin kutusundayken)' },
  { keys: ['Boşluk'], desc: 'Oynat / duraklat (oynatıcı odaklıyken)' },
  { keys: ['←', '→'], sep: '/', desc: '5 sn geri / ileri (oynatıcı odaklıyken)' },
  { keys: ['/'], desc: 'Geçmişte ara (Geçmiş sekmesinde)' },
]

const store = {
  get(k) { try { return localStorage.getItem(k) } catch { return null } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v) } catch {} },
}

const slug = (s) => String(s || '').toLocaleLowerCase('tr-TR').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i')

function tabFromHash() {
  let h = ''
  try { h = decodeURIComponent(window.location.hash.replace(/^#\/?/, '')) } catch { h = window.location.hash.slice(1) }
  const s = slug(h)
  const t = TABS.find((x) => x.hash === s || x.id === s)
  return t ? t.id : null
}

function readTheme() {
  const t = store.get(THEME_KEY)
  return t === 'dark' || t === 'light' || t === 'system' ? t : 'system'
}

function systemPrefersLight() {
  try { return window.matchMedia('(prefers-color-scheme: light)').matches } catch { return false }
}

function applyTheme(theme) {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
  const light = theme === 'light' || (theme === 'system' && systemPrefersLight())
  root.style.colorScheme = light ? 'light' : 'dark'
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute('content', light ? THEME_COLORS.light : THEME_COLORS.dark))
}

function modelState(h) {
  if (!h) return 'unknown'
  if (h.model_loaded) return 'ready'
  if (h.model_loading) return 'loading'
  if (h.model_error) return 'error'
  return 'idle'
}

function deviceInfo(h) {
  const d = String(h?.device || '').toLowerCase()
  const name = h?.gpu_name || h?.device_name || (typeof h?.gpu === 'string' ? h.gpu : '')
  const vram = h?.vram_gb ?? h?.gpu_memory_gb
  if (d.startsWith('cuda')) return { label: 'GPU', cls: 'ok', title: `NVIDIA GPU (CUDA)${name ? ` — ${name}` : ''}${vram ? ` • ${vram} GB` : ''}` }
  if (d.startsWith('mps')) return { label: 'Apple GPU', cls: 'ok', title: 'Apple Silicon (MPS) üzerinde çalışıyor' }
  if (d === 'cpu') return { label: 'CPU', cls: 'warn', title: 'GPU bulunamadı; üretim yavaş olabilir (10 sn ses ≈ 1–3 dk).' }
  return { label: d ? d.toUpperCase() : '—', cls: '', title: 'Hesaplama cihazı' }
}

const num = (...vals) => vals.find((v) => typeof v === 'number' && Number.isFinite(v))

/** api.stats() yanıtını (alan adları esnek) görünüm değerlerine çevirir; yoksa yerel verilerden tahmin eder. */
function statsView(s, voices, gens) {
  const voicesN = num(s?.voices, s?.voices?.count, s?.voice_count, s?.voices_count, s?.total_voices)
  const gensN = num(s?.generations, s?.generations?.count, s?.generation_count, s?.generations_count, s?.total_generations)
  let minutes = num(s?.total_minutes, s?.minutes, s?.generations?.minutes)
  if (minutes == null) {
    const sec = num(s?.total_duration_s, s?.total_seconds, s?.total_duration, s?.duration_total, s?.audio_seconds, s?.total_audio_seconds, s?.generations?.duration)
    if (sec != null) minutes = sec / 60
  }
  const approx = gensN == null
  const localGens = Number.isFinite(gens?.total) ? gens.total : gens?.length || 0
  return {
    voices: voicesN ?? voices.length,
    gens: gensN ?? localGens,
    gensPlus: gensN == null && !Number.isFinite(gens?.total) && (gens?.length || 0) >= GEN_PAGE,
    minutes: minutes ?? (gens || []).reduce((a, g) => a + (Number(g.duration) || 0), 0) / 60,
    approx,
  }
}

const fmtMin = (m) => (m >= 100 ? Math.round(m).toLocaleString('tr-TR') : m.toLocaleString('tr-TR', { maximumFractionDigits: 1 }))

/* ---------- küçük bileşenler ---------- */

const svg = { viewBox: '0 0 24 24', width: 15, height: 15, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, focusable: 'false' }
const IconMoon = () => <svg {...svg}><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" /></svg>
const IconSun = () => <svg {...svg}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M4.5 12h-2M21.5 12h-2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" /></svg>
const IconAuto = () => <svg {...svg}><rect x="3" y="4.5" width="18" height="12" rx="2" /><path d="M8.5 20h7M12 16.5V20" /></svg>
const IconKey = () => <svg {...svg}><circle cx="8" cy="15" r="4" /><path d="m10.8 12.2 8.7-8.7M16.5 6.5l2.5 2.5M14 9l2 2" /></svg>

const THEMES = [
  { id: 'dark', label: 'Koyu', Icon: IconMoon },
  { id: 'light', label: 'Açık', Icon: IconSun },
  { id: 'system', label: 'Sistem', Icon: IconAuto },
]

function ThemeToggle({ value, onChange }) {
  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Tema">
      {THEMES.map(({ id, label, Icon }) => (
        <button key={id} type="button" role="radio" aria-checked={value === id} className={value === id ? 'active' : ''}
          title={`Tema: ${label}`} aria-label={`${label} tema`} onClick={() => onChange(id)}>
          <Icon />
        </button>
      ))}
    </div>
  )
}

function ModelStatus({ health, warming, onWarm }) {
  if (!health) return <span className="badge"><span className="dot" /> bağlanıyor…</span>
  const dev = deviceInfo(health)
  const st = modelState(health)
  const pct = Number.isFinite(health.model_progress) ? Math.round(health.model_progress * 100) : null
  const queue = num(health.queue_pending, health.queue) || 0
  const running = num(health.queue_running, health.jobs_running) || 0
  return (
    <div className="status" aria-live="polite">
      <span className={`badge ${dev.cls}`} title={dev.title}>{dev.label}</span>
      {st === 'ready' && <span className="badge ok" title={health.model || 'Model'}><span className="dot on" /> Model hazır</span>}
      {st === 'loading' && (
        <span className="badge info model-loading" title={health.model_message || 'İlk açılışta model indirilir ve belleğe yüklenir.'}>
          <span className="spinner" aria-hidden="true" /> Model yükleniyor{pct != null ? ` %${pct}` : '…'}
        </span>
      )}
      {st === 'error' && <span className="badge err" title={String(health.model_error)}>Model hatası</span>}
      {st === 'idle' && <span className="badge warn"><span className="dot idle" /> Model bekliyor</span>}
      {(queue > 0 || running > 0) && (
        <span className="badge" title="Sıradaki üretim işleri">Kuyruk: {queue}{running ? ` (+${running} çalışıyor)` : ''}</span>
      )}
      {(st === 'idle' || st === 'error') && (
        <button type="button" className="btn ghost small" onClick={onWarm} disabled={warming}>
          {warming ? 'Başlatılıyor…' : st === 'error' ? 'Yeniden dene' : 'Modeli yükle'}
        </button>
      )}
    </div>
  )
}

function ModelGuide({ health, onWarm, warming, onHide }) {
  const st = modelState(health)
  const pct = Number.isFinite(health.model_progress) ? Math.max(0, Math.min(100, health.model_progress * 100)) : null
  const [since] = useState(() => Date.now())
  const [, tick] = useState(0)
  useEffect(() => {
    if (st !== 'loading') return
    const id = setInterval(() => tick((x) => x + 1), 1000)
    return () => clearInterval(id)
  }, [st])
  const secs = Math.round((Date.now() - since) / 1000)
  const cpu = String(health.device || '').toLowerCase() === 'cpu'
  return (
    <section className="card guide" aria-live="polite">
      <div className="row between">
        <h2>{st === 'loading' ? 'Model yükleniyor' : st === 'error' ? 'Model yüklenemedi' : 'Model henüz yüklenmedi'}</h2>
        <button type="button" className="btn ghost small" onClick={onHide}>Gizle</button>
      </div>
      <p className="muted">
        İlk açılışta ses modeli (<b>~2 GB</b>) Hugging Face'ten indirilir ve belleğe yüklenir. Bağlantınıza göre birkaç
        dakika sürebilir; sonraki açılışlarda önbellekten çok daha hızlı yüklenir. Bu sırada ses ekleyebilirsiniz.
      </p>
      {st === 'loading' && (
        <div className={`progress${pct == null ? ' indeterminate' : ''}`} role="progressbar" aria-label="Model yükleme"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct == null ? undefined : Math.round(pct)}>
          <div className="bar" style={pct == null ? undefined : { width: `${pct}%` }} />
          <span className="small">
            {health.model_message || (pct == null ? 'İndiriliyor / yükleniyor…' : `%${Math.round(pct)}`)}
            {secs > 2 ? ` — ${secs} sn` : ''}
          </span>
        </div>
      )}
      {st === 'error' && <div className="issue error">{String(health.model_error)}</div>}
      <ol className="steps">
        <li><b>Ses ekleyin</b> — "Sesler" sekmesinden 8–15 saniyelik, sessiz ortamda alınmış bir kayıt yükleyin.</li>
        <li><b>Metni yazın</b> — <code>[heyecanlı]</code>, <code>[fısıltı]</code> gibi etiketlerle duygu verin.</li>
        <li><b>Seslendirin</b> — model hazır olunca "Seslendir" düğmesiyle üretin; sonuçlar "Geçmiş"te saklanır.</li>
      </ol>
      {cpu && <div className="tip">GPU bulunamadı: model CPU'da çalışacak. Üretim yavaş olur (10 sn ses ≈ 1–3 dk).</div>}
      {(st === 'idle' || st === 'error') && (
        <div className="row">
          <button type="button" className="btn primary" onClick={onWarm} disabled={warming}>
            {warming ? 'Başlatılıyor…' : 'Modeli şimdi yükle'}
          </button>
        </div>
      )}
    </section>
  )
}

function ShortcutsModal({ onClose }) {
  const closeRef = useRef(null)
  useEffect(() => {
    const prev = document.activeElement
    closeRef.current?.focus()
    return () => { try { prev?.focus?.() } catch {} }
  }, [])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal card" role="dialog" aria-modal="true" aria-labelledby="kisayol-baslik">
        <div className="row between">
          <h2 id="kisayol-baslik">Klavye kısayolları</h2>
          <button ref={closeRef} type="button" className="btn ghost small" onClick={onClose}>Kapat</button>
        </div>
        <dl className="shortcut-list">
          {SHORTCUTS.map((s) => (
            <Fragment key={s.desc}>
              <dt>
                {s.keys.map((k, i) => (
                  <Fragment key={k}>
                    {i > 0 && <span className="muted"> {s.sep || '+'} </span>}
                    <kbd className="kbd">{k}</kbd>
                  </Fragment>
                ))}
              </dt>
              <dd>{s.desc}</dd>
            </Fragment>
          ))}
        </dl>
      </div>
    </div>
  )
}

/** Bir sekmedeki beklenmeyen hata tüm uygulamayı düşürmesin. */
class TabBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) { return { error } }
  componentDidCatch(error, info) { console.error('Sekme hatası:', error, info?.componentStack) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <section className="card">
        <div className="empty">
          <strong>Bu bölüm görüntülenemedi.</strong>
          <span className="small">{String(this.state.error?.message || this.state.error)}</span>
          <button type="button" className="btn primary small" onClick={() => this.setState({ error: null })}>Yeniden dene</button>
        </div>
      </section>
    )
  }
}

let toastSeq = 0

/* ---------- uygulama ---------- */

export default function App() {
  const [tab, setTab] = useState(() => tabFromHash() || 'generate')
  const [health, setHealth] = useState(null)
  const [conn, setConn] = useState('connecting') // connecting | ok | down
  const [connError, setConnError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [retryIn, setRetryIn] = useState(0)
  const [offline, setOffline] = useState(false)
  const [voices, setVoices] = useState([])
  const [gens, setGens] = useState([])
  const [stats, setStats] = useState(null)
  const [toasts, setToasts] = useState([])
  const [apiKey, setKey] = useState(getApiKey())
  const [showKey, setShowKey] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [warming, setWarming] = useState(false)
  const [theme, setTheme] = useState(readTheme)
  const [guideHidden, setGuideHidden] = useState(() => store.get(GUIDE_KEY) === '1')
  const [readyOnce, setReadyOnce] = useState(() => store.get(READY_KEY) === '1')

  const toastTimers = useRef(new Map())
  const statsTimer = useRef(0)
  const offlineRef = useRef(false)
  const lastAuthToast = useRef(0)
  const prevModel = useRef(null)

  /* ----- bildirimler (üst üste yığılır) ----- */
  const dismiss = useCallback((id) => {
    setToasts((ts) => ts.filter((t) => t.id !== id))
    clearTimeout(toastTimers.current.get(id))
    toastTimers.current.delete(id)
  }, [])

  const notify = useCallback((message, type = 'ok', opts = {}) => {
    const id = ++toastSeq
    const text = typeof message === 'string' ? message : message?.message || String(message)
    setToasts((ts) => [...ts.filter((t) => !(t.message === text && t.type === type)), { id, message: text, type }].slice(-5))
    const ms = opts.duration ?? (type === 'error' ? 6500 : type === 'warn' ? 5000 : 3200)
    toastTimers.current.set(id, setTimeout(() => dismiss(id), ms))
    return id
  }, [dismiss])

  useEffect(() => () => { for (const t of toastTimers.current.values()) clearTimeout(t) }, [])

  /* ----- tema ----- */
  useEffect(() => {
    applyTheme(theme)
    store.set(THEME_KEY, theme)
    if (theme !== 'system') return
    let mq
    try { mq = window.matchMedia('(prefers-color-scheme: light)') } catch { return }
    const on = () => applyTheme('system')
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [theme])

  /* ----- 401 → API anahtarı istemi ----- */
  useEffect(() => {
    api.onUnauthorized = () => {
      setShowKey(true)
      const now = Date.now()
      if (now - lastAuthToast.current > 4000) {
        lastAuthToast.current = now
        notify('API anahtarı gerekli veya geçersiz. Lütfen anahtarı girin.', 'error')
      }
    }
    return () => { api.onUnauthorized = null }
  }, [notify])

  /* ----- veri ----- */
  const refreshStats = useCallback(() => {
    clearTimeout(statsTimer.current)
    statsTimer.current = setTimeout(async () => {
      try { setStats(await api.stats()) } catch { setStats(null) }
    }, 250)
  }, [])
  useEffect(() => () => clearTimeout(statsTimer.current), [])

  const loadVoices = useCallback(async () => {
    const v = await api.voices()
    setVoices(Array.isArray(v) ? v : v?.items || [])
    refreshStats()
  }, [refreshStats])

  const loadGens = useCallback(async () => {
    setGens(await api.generations({ limit: GEN_PAGE }))
    refreshStats()
  }, [refreshStats])

  const loadAll = useCallback(async () => {
    let h
    try {
      h = await api.health()
    } catch (err) {
      setConn('down')
      setConnError(err.message)
      setAttempt((a) => a + 1)
      return
    }
    setHealth(h)
    setConn('ok')
    setConnError('')
    setAttempt(0)
    offlineRef.current = false
    setOffline(false)
    if (h.auth_required && !getApiKey()) { setShowKey(true); return }
    const res = await Promise.allSettled([loadVoices(), loadGens()])
    const bad = res.find((r) => r.status === 'rejected')
    if (bad && bad.reason?.status !== 401) notify(`Veriler yüklenemedi: ${bad.reason?.message || bad.reason}`, 'error')
  }, [loadVoices, loadGens, notify])

  useEffect(() => { loadAll() }, [loadAll])

  // Bağlantı yoksa geri sayımla otomatik yeniden dene (5, 10, 15 … en fazla 30 sn).
  useEffect(() => {
    if (conn !== 'down') return
    let left = Math.min(30, 5 * Math.max(1, attempt))
    setRetryIn(left)
    const id = setInterval(() => {
      left -= 1
      setRetryIn(left)
      if (left <= 0) { clearInterval(id); loadAll() }
    }, 1000)
    return () => clearInterval(id)
  }, [conn, attempt, loadAll])

  const retryNow = () => { setConn('connecting'); loadAll() }

  // Sağlık sorgusu: model yüklenirken sık, hazırken seyrek; sekme gizliyken atla.
  const mstate = modelState(health)
  useEffect(() => {
    if (conn !== 'ok') return
    const ms = offline ? 3000 : mstate === 'loading' ? 2500 : mstate === 'ready' ? 15000 : 6000
    let stopped = false
    const id = setInterval(async () => {
      if (document.hidden) return
      try {
        const h = await api.health()
        if (stopped) return
        setHealth(h)
        if (offlineRef.current) {
          offlineRef.current = false
          setOffline(false)
          notify('Sunucu bağlantısı yeniden kuruldu.')
          loadVoices().catch(() => {})
          loadGens().catch(() => {})
        }
      } catch (err) {
        if (stopped) return
        if (err.network || err.status === 0 || err.status === 404 || err.status >= 500) {
          offlineRef.current = true
          setOffline(true)
        }
      }
    }, ms)
    return () => { stopped = true; clearInterval(id) }
  }, [conn, mstate, offline, notify, loadVoices, loadGens])

  // Model durum geçişleri
  useEffect(() => {
    const prev = prevModel.current
    prevModel.current = mstate
    if (mstate === 'ready') {
      if (!readyOnce) { store.set(READY_KEY, '1'); setReadyOnce(true) }
      if (prev === 'loading' || prev === 'idle') notify('Model hazır — seslendirmeye başlayabilirsiniz.')
    } else if (mstate === 'error' && prev && prev !== 'error' && prev !== 'unknown') {
      notify(`Model yüklenemedi: ${health?.model_error || 'bilinmeyen hata'}`, 'error')
    }
  }, [mstate]) // eslint-disable-line react-hooks/exhaustive-deps

  async function warm() {
    setWarming(true)
    try {
      await api.warmup()
      setHealth(await api.health())
      notify('Model yükleniyor… Hazır olduğunda haber vereceğim.', 'info')
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setWarming(false)
    }
  }

  /* ----- sekme ↔ adres (#seslendir) ----- */
  const selectTab = useCallback((id) => setTab(id), [])

  useEffect(() => {
    const t = TABS.find((x) => x.id === tab) || TABS[0]
    const want = `#${t.hash}`
    if (window.location.hash === want) return
    if (!window.location.hash || !tabFromHash()) {
      try { window.history.replaceState(null, '', want) } catch { window.location.hash = want }
    } else window.location.hash = want
  }, [tab])

  useEffect(() => {
    const onHash = () => { const t = tabFromHash(); if (t) setTab(t) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  /* ----- klavye kısayolları ----- */
  useEffect(() => {
    function onKey(e) {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === 'Escape') {
        if (showHelp) { setShowHelp(false); e.preventDefault() } else if (showKey) setShowKey(false)
        return
      }
      const t = e.target
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
      if (e.key === '?') { e.preventDefault(); setShowHelp((s) => !s); return }
      if (showHelp) return
      const target = TABS.find((x) => x.key === e.key)
      if (target) { e.preventDefault(); selectTab(target.id) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showHelp, showKey, selectTab])

  /* ----- API anahtarı ----- */
  function saveKey(e) {
    e.preventDefault()
    setApiKey(apiKey.trim())
    setShowKey(false)
    notify(apiKey.trim() ? 'API anahtarı kaydedildi.' : 'API anahtarı temizlendi.')
    loadAll()
  }
  function clearKey() {
    setApiKey('')
    setKey('')
    notify('API anahtarı silindi.')
  }

  const onGenerated = useCallback(() => { loadGens().catch(() => {}) }, [loadGens])
  const onReuse = useCallback(() => {
    selectTab('generate')
    try { window.scrollTo({ top: 0, behavior: 'smooth' }) } catch {}
  }, [selectTab])

  const hideGuide = () => { store.set(GUIDE_KEY, '1'); setGuideHidden(true) }

  const languages = health?.languages || { tr: 'Türkçe' }
  const styles = health?.styles || []
  const sv = statsView(stats, voices, gens)
  const showGuide = conn === 'ok' && health && mstate !== 'ready' && !readyOnce && !guideHidden

  const toastStack = (
    <div className="toast-stack" role="region" aria-label="Bildirimler" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.type}`} role={t.type === 'error' ? 'alert' : 'status'}>
          <span className="toast-msg">{t.message}</span>
          <button type="button" className="toast-close" onClick={() => dismiss(t.id)} aria-label="Bildirimi kapat">×</button>
        </div>
      ))}
    </div>
  )

  const brand = (
    <div className="brand">
      <span className="logo" aria-hidden="true">◉</span>
      <div>
        <h1>SesKlon</h1>
        <div className="muted small">Türkçe ses klonlama ve doğal seslendirme • Chatterbox Multilingual</div>
      </div>
    </div>
  )

  /* ----- sunucuya ulaşılamıyor: tam sayfa ----- */
  if (conn === 'down') {
    return (
      <div className="app">
        <header className="topbar">
          {brand}
          <div className="topbar-right"><ThemeToggle value={theme} onChange={setTheme} /></div>
        </header>
        <div className="fullpage">
          <div className="empty big" role="alert">
            <h2>Sunucuya bağlanılamadı</h2>
            <p className="muted">
              SesKlon arka ucu yanıt vermiyor. Sunucunun çalıştığından emin olun
              (<code>./run.sh</code>, <code>.\run.ps1</code> ya da <code>docker compose up -d</code>) ve adresin doğru olduğunu kontrol edin.
            </p>
            {connError && <p className="small muted">Ayrıntı: {connError}</p>}
            <div className="row center">
              <button type="button" className="btn primary" onClick={retryNow}>Yeniden dene</button>
              {retryIn > 0 && <span className="countdown" aria-live="off">{retryIn} sn içinde yeniden denenecek</span>}
            </div>
          </div>
        </div>
        {toastStack}
      </div>
    )
  }

  return (
    <div className="app">
      {mstate === 'loading' && <div className="loadbar" aria-hidden="true" />}

      <header className="topbar">
        <div className="brand-wrap">
          {brand}
          <div className="stats" aria-label="İstatistikler">
            <span className="stat" title="Kayıtlı ses sayısı"><b>{sv.voices}</b> ses</span>
            <span className="stat" title="Toplam üretim"><b>{sv.gens}{sv.gensPlus ? '+' : ''}</b> üretim</span>
            <span className="stat" title={sv.approx ? 'Yüklenen kayıtlardan hesaplandı' : 'Üretilen toplam ses süresi'}>
              <b>{sv.approx && sv.gensPlus ? '≥ ' : ''}{fmtMin(sv.minutes)}</b> dk
            </span>
          </div>
        </div>
        <div className="topbar-right">
          <ModelStatus health={health} warming={warming} onWarm={warm} />
          <div className="controls">
            <ThemeToggle value={theme} onChange={setTheme} />
            <button type="button" className="btn ghost small icon" onClick={() => setShowHelp(true)} title="Klavye kısayolları (?)" aria-label="Klavye kısayolları">?</button>
            <button type="button" className={`btn ghost small icon${showKey ? ' active' : ''}`} onClick={() => setShowKey((s) => !s)}
              title="API anahtarı" aria-label="API anahtarı" aria-expanded={showKey}>
              <IconKey />
            </button>
          </div>
        </div>
      </header>

      {offline && (
        <div className="banner warn" role="status">
          <span className="spinner" aria-hidden="true" /> Sunucu bağlantısı koptu — yeniden bağlanmaya çalışılıyor…
        </div>
      )}

      {showKey && (
        <form className="card keybox" onSubmit={saveKey}>
          <label>API anahtarı {health?.auth_required ? '(sunucu istiyor)' : '(sunucuda kapalı, boş bırakabilirsiniz)'}
            <input type="password" value={apiKey} onChange={(e) => setKey(e.target.value)} placeholder="X-API-Key" autoComplete="off" autoFocus />
          </label>
          <div className="row">
            <button className="btn primary small">Kaydet</button>
            {getApiKey() && <button type="button" className="btn ghost small danger-text" onClick={clearKey}>Anahtarı sil</button>}
            <button type="button" className="btn ghost small" onClick={() => setShowKey(false)}>Kapat</button>
          </div>
        </form>
      )}

      {showGuide && <ModelGuide health={health} warming={warming} onWarm={warm} onHide={hideGuide} />}

      <nav className="tabs" role="tablist" aria-label="Bölümler">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} aria-controls="icerik"
            className={`tab ${tab === t.id ? 'active' : ''}`} onClick={() => selectTab(t.id)} title={`${t.label} (kısayol: ${t.key})`}>
            {t.label}
            {t.id === 'voices' && voices.length > 0 && <span className="count">{voices.length}</span>}
            <kbd className="kbd tab-key" aria-hidden="true">{t.key}</kbd>
          </button>
        ))}
      </nav>

      <main id="icerik" role="tabpanel">
        {conn === 'connecting' && !health ? (
          <div className="grid two" aria-busy="true" aria-label="Yükleniyor">
            <div className="skeleton card tall" />
            <div className="skeleton card tall" />
          </div>
        ) : (
          <>
            {/* Seslendir sekmesi hiç kapanmaz (yalnızca gizlenir): süren üretim, ilerleme, iptal ve canlı önizleme
                başka sekmeye geçince kaybolmaz. Diğer sekmeler hafiftir, açılıp kapanabilir. */}
            <div hidden={tab !== 'generate'}>
              <TabBoundary key="generate">
                <Generate voices={voices} languages={languages} maxChars={health?.max_text_chars || 5000} health={health} onGenerated={onGenerated} notify={notify} active={tab === 'generate'} />
              </TabBoundary>
            </div>
            {tab !== 'generate' && (
              <TabBoundary key={tab}>
                {tab === 'voices' && <Voices voices={voices} languages={languages} health={health} styles={styles} reload={loadVoices} notify={notify} />}
                {tab === 'convert' && <Convert voices={voices} health={health} onGenerated={onGenerated} notify={notify} />}
                {tab === 'history' && (
                  <History items={gens} languages={languages} reload={loadGens} notify={notify} voices={voices} styles={styles} onReuse={onReuse} />
                )}
              </TabBoundary>
            )}
          </>
        )}
      </main>

      <footer className="footer muted small">
        <span>SesKlon{health?.version ? ` v${health.version}` : ''}</span>
        <span aria-hidden="true">•</span>
        <span>Her üretim, Resemble AI'ın algılanamaz PerTh filigranını içerir. Sesleri yalnızca izinle klonlayın.</span>
        <span aria-hidden="true">•</span>
        <button type="button" className="linklike" onClick={() => setShowHelp(true)}>Kısayollar <kbd className="kbd">?</kbd></button>
      </footer>

      {showHelp && <ShortcutsModal onClose={() => setShowHelp(false)} />}
      {toastStack}
    </div>
  )
}
