import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import Player, { fmtDur } from './Player'

const PRESETS = [
  { name: 'Doğal', exaggeration: 0.55, cfg_weight: 0.45, temperature: 0.8, speed: 1.0 },
  { name: 'Sakin / anlatım', exaggeration: 0.4, cfg_weight: 0.5, temperature: 0.7, speed: 0.93 },
  { name: 'Heyecanlı / YouTube', exaggeration: 0.85, cfg_weight: 0.35, temperature: 0.9, speed: 1.02 },
  { name: 'Reklam / enerjik', exaggeration: 0.9, cfg_weight: 0.3, temperature: 0.9, speed: 1.05 },
  { name: 'Dramatik', exaggeration: 1.0, cfg_weight: 0.3, temperature: 1.0, speed: 0.95 },
]

const EXAMPLE = `[heyecanlı] Selam millet! Bugün size çok güzel bir şey göstereceğim. Hem de Türkçe!
[sakin] Peki nasıl çalışıyor? On saniyelik bir kayıt yüklüyorsunuz... ve bitti.
[üzgün] Eskiden bunun için aylarca uğraşırdık, maalesef.
[heyecanlı] Ama artık öyle değil. Hazırsanız başlıyoruz!`

export default function Generate({ voices, languages, maxChars, health, onGenerated, notify }) {
  const [text, setText] = useState(EXAMPLE)
  const [voiceId, setVoiceId] = useState('')
  const [language, setLanguage] = useState('tr')
  const [exaggeration, setExaggeration] = useState(0.55)
  const [cfg, setCfg] = useState(0.45)
  const [temperature, setTemperature] = useState(0.8)
  const [speed, setSpeed] = useState(1.0)
  const [seed, setSeed] = useState('')
  const [format, setFormat] = useState('mp3')
  const [colloquial, setColloquial] = useState(true)
  const [punctEmotion, setPunctEmotion] = useState(true)
  const [autoEmotion, setAutoEmotion] = useState(false)
  const [emotionFx, setEmotionFx] = useState('off')
  const [baseEmotion, setBaseEmotion] = useState('')
  const [showTags, setShowTags] = useState(true)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState(null)
  const textRef = useRef(null)

  const tags = health?.tags
  const emotions = tags?.emotions || []
  const nonverbal = tags?.nonverbal || []
  const pauses = tags?.pauses || []

  useEffect(() => {
    if (!voiceId && voices.length) setVoiceId(voices[0].id)
    if (voiceId && !voices.find((v) => v.id === voiceId)) setVoiceId(voices[0]?.id || '')
  }, [voices])

  useEffect(() => {
    const v = voices.find((x) => x.id === voiceId)
    if (v?.language) setLanguage(v.language)
  }, [voiceId])

  useEffect(() => {
    if (!busy) return
    const t0 = Date.now()
    const id = setInterval(() => setElapsed((Date.now() - t0) / 1000), 200)
    return () => clearInterval(id)
  }, [busy])

  function applyPreset(p) {
    setExaggeration(p.exaggeration); setCfg(p.cfg_weight); setTemperature(p.temperature); setSpeed(p.speed ?? 1)
  }

  function insertTag(tag) {
    const el = textRef.current
    const token = `[${tag}] `
    if (!el) { setText((x) => x + ' ' + token); return }
    const start = el.selectionStart ?? text.length
    const end = el.selectionEnd ?? text.length
    const before = text.slice(0, start)
    const after = text.slice(end)
    const sep = before && !before.endsWith(' ') && !before.endsWith('\n') ? ' ' : ''
    const next = before + sep + token + after
    setText(next)
    requestAnimationFrame(() => { el.focus(); const pos = (before + sep + token).length; el.setSelectionRange(pos, pos) })
  }

  async function generate(e) {
    e?.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true); setResult(null); setJob(null)
    try {
      const gen = await api.tts({
        text, voice_id: voiceId || null, language,
        exaggeration, cfg_weight: cfg, temperature,
        seed: seed === '' ? null : Number(seed), speed, format,
        colloquial, punctuation_emotion: punctEmotion, auto_emotion: autoEmotion,
        emotion_fx: emotionFx, emotion_refs: emotionFx === 'full', emotion: baseEmotion || null,
      }, setJob)
      setResult(gen)
      onGenerated?.(gen)
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(false); setJob(null)
    }
  }

  function onKey(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') generate(e)
  }

  const selectedVoice = voices.find((v) => v.id === voiceId)
  const sampleCount = selectedVoice?.samples?.length || 0

  return (
    <div className="grid two">
      <section className="card">
        <h2>Metinden ses üret</h2>
        <form onSubmit={generate} className="stack">
          <label>Metin <span className="muted">(Ctrl+Enter ile üret)</span>
            <textarea ref={textRef} rows={9} value={text} onKeyDown={onKey}
              onChange={(e) => setText(e.target.value.slice(0, maxChars))} placeholder="Seslendirilecek metni yazın…" />
            <div className="row between">
              <button type="button" className="btn ghost small" onClick={() => setShowTags((v) => !v)}>
                {showTags ? 'Etiketleri gizle' : 'Duygu etiketleri'}
              </button>
              <span className="muted small">{text.length} / {maxChars}</span>
            </div>
          </label>

          {showTags && (
            <div className="tagbox">
              <div className="muted small">İmlecin olduğu yere eklenir; bir sonraki etikete kadar geçerli. Noktalama da duyguyu etkiler: <b>!</b> vurgulu, <b>?</b> yükselen ton, <b>...</b> düşünceli.</div>
              <div className="taggroup"><span className="muted small">Duygu</span>
                <div className="presets">{emotions.map((t) => <button type="button" key={t.name} className="chip clickable" onClick={() => insertTag(t.name)}>[{t.label}]</button>)}</div>
              </div>
              <div className="taggroup"><span className="muted small">Sözsüz</span>
                <div className="presets">{['gülme', 'kahkaha', 'kıkırdama', 'iç çekme', 'hmm', 'of', 'şaşırır', 'ağlar', 'öksürür', 'boğaz temizler', 'esner'].filter((t) => !nonverbal.length || nonverbal.includes(t)).map((t) => <button type="button" key={t} className="chip clickable" onClick={() => insertTag(t)}>[{t}]</button>)}</div>
              </div>
              <div className="taggroup"><span className="muted small">Duraklama</span>
                <div className="presets">{['nefes', 'duraklama', 'uzun duraklama'].filter((p) => pauses.includes(p) || !pauses.length).map((t) => <button type="button" key={t} className="chip clickable" onClick={() => insertTag(t)}>[{t}]</button>)}</div>
              </div>
            </div>
          )}

          <div className="row">
            <label className="grow">Ses
              <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                <option value="">Varsayılan model sesi</option>
                {voices.map((v) => <option key={v.id} value={v.id}>{v.name}{v.samples?.length ? ` (${v.samples.length} duygu kaydı)` : ''}</option>)}
              </select>
            </label>
            <label className="grow">Dil
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                {Object.entries(languages).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label className="grow">Genel duygu
              <select value={baseEmotion} onChange={(e) => setBaseEmotion(e.target.value)}>
                <option value="">Etiketlere göre</option>
                {emotions.filter((t) => t.name !== 'normal').map((t) => <option key={t.name} value={t.name}>{t.label}</option>)}
              </select>
            </label>
          </div>
          {selectedVoice && sampleCount === 0 && (
            <div className="muted small">Bu ses için duygu kaydı yok; duygular yalnızca üretim ayarlarıyla verilir. Belirgin duygu için "Sesler" sekmesinden o duyguda kayıt ekleyin.</div>
          )}

          <div className="row wrap">
            <label className="check"><input type="checkbox" checked={colloquial} onChange={(e) => setColloquial(e.target.checked)} /> Konuşma dili</label>
            <label className="check"><input type="checkbox" checked={punctEmotion} onChange={(e) => setPunctEmotion(e.target.checked)} /> Noktalamaya göre duygu</label>
            <label className="check"><input type="checkbox" checked={autoEmotion} onChange={(e) => setAutoEmotion(e.target.checked)} /> İçerikten otomatik duygu</label>
            <label className="inline">Ses işleme
              <select value={emotionFx} onChange={(e) => setEmotionFx(e.target.value)}>
                <option value="off">Kapalı — en doğal (önerilen)</option>
                <option value="light">Hafif — şiddet farkları</option>
                <option value="full">Tam — perde/tempo/fısıltı (deneysel)</option>
              </select>
            </label>
          </div>

          <div className="presets">
            {PRESETS.map((p) => <button type="button" key={p.name} className="chip clickable" onClick={() => applyPreset(p)}>{p.name}</button>)}
            <button type="button" className="chip clickable" onClick={() => setShowAdvanced((v) => !v)}>{showAdvanced ? 'Ayarları gizle ▴' : 'İnce ayar ▾'}</button>
          </div>

          {showAdvanced && (
            <div className="stack">
              <label>Duygu / vurgu (exaggeration): <b>{exaggeration.toFixed(2)}</b>
                <input type="range" min="0" max="1.5" step="0.05" value={exaggeration} onChange={(e) => setExaggeration(+e.target.value)} />
              </label>
              <label>Sese sadakat / tempo (cfg): <b>{cfg.toFixed(2)}</b>
                <input type="range" min="0" max="1" step="0.05" value={cfg} onChange={(e) => setCfg(+e.target.value)} />
                <span className="muted small">Düşük değer daha yavaş ve serbest; referans ses farklı dildeyse 0'a yaklaştırın.</span>
              </label>
              <label>Çeşitlilik (temperature): <b>{temperature.toFixed(2)}</b>
                <input type="range" min="0.1" max="1.5" step="0.05" value={temperature} onChange={(e) => setTemperature(+e.target.value)} />
              </label>
              <label>Hız: <b>{speed.toFixed(2)}×</b>
                <input type="range" min="0.7" max="1.3" step="0.05" value={speed} onChange={(e) => setSpeed(+e.target.value)} />
              </label>
              <div className="row">
                <label className="grow">Tohum (seed)
                  <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="Aynı sonucu tekrar almak için" />
                </label>
                <label>Format
                  <select value={format} onChange={(e) => setFormat(e.target.value)}>
                    <option value="mp3">MP3</option>
                    <option value="wav">WAV</option>
                  </select>
                </label>
              </div>
            </div>
          )}

          <button className="btn primary big" disabled={busy || !text.trim()}>
            {busy ? `Üretiliyor… ${elapsed.toFixed(0)} sn` : '▶ Seslendir'}
          </button>
          {busy && (
            <div className="progress">
              <div className="bar" style={{ width: `${Math.round((job?.progress || 0) * 100)}%` }} />
              <div className="muted small">
                {job?.status === 'queued' && 'Sırada bekliyor…'}
                {job?.status === 'running' && (job.total ? `Parça ${Math.min(job.step + 1, job.total)} / ${job.total}` : 'Model yükleniyor…')}
                {!job && 'Gönderiliyor…'}
                {job?.message ? ` — ${job.message}` : ''}
              </div>
            </div>
          )}
        </form>
      </section>

      <section className="card">
        <h2>Sonuç</h2>
        {!result && <p className="muted">Üretilen ses burada görünecek.</p>}
        {result && (
          <div className="stack">
            <Player src={result.url} downloadName={`sesklon-${result.id}.${result.filename.split('.').pop()}`} autoPlay />
            <div className="muted small">
              {result.voice_name} • {languages[result.language] || result.language} • {fmtDur(result.duration)} • {result.elapsed.toFixed(1)} sn'de üretildi
            </div>
            <div className="row">
              <button type="button" className="btn secondary small" onClick={() => { setSeed(''); generate() }} disabled={busy}>↻ Yeniden üret (farklı)</button>
              <button type="button" className="btn ghost small" onClick={() => { setSeed(String(Math.floor(Math.random() * 1e6))); setShowAdvanced(true) }}>Tohum sabitle</button>
            </div>
            {result.params?.chunks?.length > 0 && (
              <details className="chunks">
                <summary className="muted small">Cümle cümle ne yapıldı ({result.params.chunks.length} parça)</summary>
                <ul className="list">
                  {result.params.chunks.map((c, i) => (
                    <li key={i} className="item small">
                      <div className="row between">
                        <span><span className={`tag ${c.emotion ? 'emo' : ''}`}>{c.emotion || 'nötr'}</span> <span className="muted">ref: {c.ref} • vurgu {c.exaggeration} • hız {c.speed}× • {fmtDur(c.duration)}</span></span>
                      </div>
                      <div>{c.text}</div>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
