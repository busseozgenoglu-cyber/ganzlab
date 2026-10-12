import { useCallback, useEffect, useState } from 'react'
import { api, getApiKey, setApiKey } from './api'
import Voices from './components/Voices'
import Generate from './components/Generate'
import Convert from './components/Convert'
import History from './components/History'

const TABS = [
  { id: 'generate', label: 'Seslendir' },
  { id: 'voices', label: 'Sesler' },
  { id: 'convert', label: 'Dönüştür' },
  { id: 'history', label: 'Geçmiş' },
]

export default function App() {
  const [tab, setTab] = useState('generate')
  const [health, setHealth] = useState(null)
  const [voices, setVoices] = useState([])
  const [gens, setGens] = useState([])
  const [toast, setToast] = useState(null)
  const [apiKey, setKey] = useState(getApiKey())
  const [showKey, setShowKey] = useState(false)
  const [warming, setWarming] = useState(false)

  const notify = useCallback((message, type = 'ok') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), type === 'error' ? 6000 : 3000)
  }, [])

  const loadVoices = useCallback(async () => setVoices(await api.voices()), [])
  const loadGens = useCallback(async () => setGens(await api.generations()), [])

  const loadAll = useCallback(async () => {
    try {
      const h = await api.health()
      setHealth(h)
      if (h.auth_required && !getApiKey()) { setShowKey(true); return }
      await Promise.all([loadVoices(), loadGens()])
    } catch (err) {
      notify('Sunucuya bağlanılamadı: ' + err.message, 'error')
    }
  }, [loadVoices, loadGens, notify])

  useEffect(() => { loadAll() }, [loadAll])

  useEffect(() => {
    const id = setInterval(async () => {
      try { setHealth(await api.health()) } catch {}
    }, health && !health.model_loaded ? 4000 : 15000)
    return () => clearInterval(id)
  }, [health?.model_loaded])

  async function warm() {
    setWarming(true)
    try { await api.warmup(); setHealth(await api.health()); notify('Model yüklendi.') }
    catch (err) { notify(err.message, 'error') } finally { setWarming(false) }
  }

  function saveKey(e) {
    e.preventDefault()
    setApiKey(apiKey.trim()); setShowKey(false); loadAll()
  }

  const languages = health?.languages || { tr: 'Türkçe' }
  const onGenerated = () => loadGens()

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◉</span>
          <div>
            <h1>SesKlon</h1>
            <div className="muted small">Açık kaynak ses klonlama • Chatterbox Multilingual</div>
          </div>
        </div>
        <div className="status">
          {health ? (
            <>
              <span className={`dot ${health.model_loaded ? 'on' : 'idle'}`} />
              <span className="small">{health.device.toUpperCase()} • {health.model_loaded ? 'model hazır' : health.model_loading ? 'model yükleniyor…' : health.model_error ? 'model hatası' : 'model bekliyor'}{health.queue_pending ? ` • sırada ${health.queue_pending}` : ''}</span>
              {!health.model_loaded && !health.model_loading && (
                <button className="btn ghost small" onClick={warm} disabled={warming}>Modeli yükle</button>
              )}
            </>
          ) : <span className="small muted">bağlanıyor…</span>}
          <button className="btn ghost small" onClick={() => setShowKey((s) => !s)} title="API anahtarı">⚙</button>
        </div>
      </header>

      {showKey && (
        <form className="card keybox" onSubmit={saveKey}>
          <label>API anahtarı {health?.auth_required ? '(sunucu istiyor)' : '(sunucuda kapalı, boş bırakabilirsiniz)'}
            <input type="password" value={apiKey} onChange={(e) => setKey(e.target.value)} placeholder="X-API-Key" />
          </label>
          <div className="row">
            <button className="btn primary small">Kaydet</button>
            <button type="button" className="btn ghost small" onClick={() => setShowKey(false)}>Kapat</button>
          </div>
        </form>
      )}

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </nav>

      <main>
        {tab === 'generate' && (
          <Generate voices={voices} languages={languages} maxChars={health?.max_text_chars || 5000} health={health} onGenerated={onGenerated} notify={notify} />
        )}
        {tab === 'voices' && <Voices voices={voices} languages={languages} health={health} reload={loadVoices} notify={notify} />}
        {tab === 'convert' && <Convert voices={voices} onGenerated={onGenerated} notify={notify} />}
        {tab === 'history' && <History items={gens} languages={languages} reload={loadGens} notify={notify} />}
      </main>

      <footer className="muted small">
        Her üretim, Resemble AI'ın algılanamaz PerTh filigranını içerir. Sesleri yalnızca izinle klonlayın.
      </footer>

      {toast && <div className={`toast ${toast.type}`}>{toast.message}</div>}
    </div>
  )
}
