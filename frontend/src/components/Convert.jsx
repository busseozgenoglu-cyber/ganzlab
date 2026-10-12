import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useRecorder } from '../useRecorder'
import Player, { fmtDur } from './Player'

export default function Convert({ voices, onGenerated, notify }) {
  const [voiceId, setVoiceId] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [job, setJob] = useState(null)
  const fileRef = useRef(null)
  const rec = useRecorder()

  useEffect(() => { if (!voiceId && voices.length) setVoiceId(voices[0].id) }, [voices])

  async function toggleRecord() {
    if (rec.recording) {
      const f = await rec.stop()
      if (f) setFile(f)
    } else await rec.start()
  }

  async function submit(e) {
    e.preventDefault()
    if (!file || !voiceId) return notify('Kaynak ses ve hedef ses seçin.', 'error')
    setBusy(true); setResult(null)
    try {
      const gen = await api.vc({ voice_id: voiceId, file }, setJob)
      setResult(gen); onGenerated?.(gen)
    } catch (err) { notify(err.message, 'error') } finally { setBusy(false); setJob(null) }
  }

  return (
    <div className="grid two">
      <section className="card">
        <h2>Ses → ses dönüştür</h2>
        <p className="muted">Kendi konuşmanızı kaydedin; söylediğiniz her şey tonlamasıyla birlikte seçtiğiniz sesle yeniden söylenir.</p>
        <form onSubmit={submit} className="stack">
          <label>Hedef ses
            <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
              {voices.length === 0 && <option value="">Önce bir ses ekleyin</option>}
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
          <div className="row">
            <label className="grow">Kaynak konuşma
              <input ref={fileRef} type="file" accept="audio/*,video/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <button type="button" className={`btn ${rec.recording ? 'danger' : 'secondary'}`} onClick={toggleRecord}>
              {rec.recording ? `■ Durdur (${rec.seconds} sn)` : '● Kaydet'}
            </button>
          </div>
          {rec.error && <div className="alert error">{rec.error}</div>}
          {file && <div className="chip">Seçili: {file.name}</div>}
          <button className="btn primary big" disabled={busy || !file || !voiceId}>{busy ? (job?.status === 'queued' ? 'Sırada…' : 'Dönüştürülüyor…') : '⇄ Dönüştür'}</button>
        </form>
      </section>
      <section className="card">
        <h2>Sonuç</h2>
        {!result && <p className="muted">Dönüştürülen ses burada görünecek.</p>}
        {result && (
          <div className="stack">
            <Player src={result.url} downloadName={`sesklon-vc-${result.id}.wav`} autoPlay />
            <div className="muted small">{result.voice_name} • {fmtDur(result.duration)} • {result.elapsed.toFixed(1)} sn</div>
          </div>
        )}
      </section>
    </div>
  )
}
