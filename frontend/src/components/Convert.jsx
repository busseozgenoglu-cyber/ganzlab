import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import Player from './Player'
import AnalysisCard, { capTr, fmtNum, fmtSn, useFileAnalysis } from './AnalysisCard'
import { Recorder, safeFileName, useObjectUrl } from './Voices'

const SOURCE_MAX_SECONDS = 120 // mikrofondan kaynak kaydı en fazla 2 dk (uzun dönüşümler yavaş)

/** busy iken geçen süre (sn). */
function useElapsed(active) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!active) return undefined
    const t0 = Date.now()
    setSeconds(0)
    const id = setInterval(() => setSeconds((Date.now() - t0) / 1000), 500)
    return () => clearInterval(id)
  }, [active])
  return seconds
}

function SourceInput({ file, fileRef, onPick, onClear, check, analysisEnabled }) {
  const preview = useObjectUrl(file)
  return (
    <div className="stack">
      <label>Kaynak konuşma (dosya)
        <input ref={fileRef} type="file" accept="audio/*,video/*" onChange={(e) => onPick(e.target.files?.[0] || null)} />
      </label>
      <Recorder onFile={(f) => onPick(f, true)} label="● Mikrofondan kaydet" maxSeconds={SOURCE_MAX_SECONDS} />
      {file && (
        <div className="stack">
          <div className="row between">
            <span className="chip">Kaynak: {file.name}</span>
            <button type="button" className="btn ghost small" onClick={onClear}>✕ Kaldır</button>
          </div>
          {preview && <Player src={preview} downloadName={file.name} compact title="Kaynak kayıt" />}
          {analysisEnabled && (
            <AnalysisCard compact analysis={check.analysis} loading={check.analyzing}
              onAnalyze={() => check.run(file)} title="Kaynak kaydın kalitesi" />
          )}
        </div>
      )}
    </div>
  )
}

function JobProgress({ job, elapsed, cancelling, onCancel }) {
  const pct = Math.round(Math.min(1, Math.max(0, Number(job?.progress) || 0)) * 100)
  let status = 'Gönderiliyor…'
  if (job?.status === 'queued') status = job.position > 0 ? `Sırada bekliyor (önünde ${job.position} iş var)…` : 'Sırada bekliyor…'
  else if (job?.status === 'running') status = job.message ? capTr(job.message) : 'Dönüştürülüyor…'
  const eta = Number(job?.eta_s)
  return (
    <div className="stack">
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <div className="bar" style={{ width: `${pct}%` }} />
        <div className="muted small">
          {status}{pct > 0 ? ` — %${pct}` : ''}{eta > 0 ? ` • kalan ~${fmtSn(eta)}` : ''} • {Math.round(elapsed)} sn
        </div>
      </div>
      <div className="row">
        <button type="button" className="btn ghost small danger-text" onClick={onCancel} disabled={cancelling || !job?.id}>
          {cancelling ? 'İptal ediliyor…' : '✕ İptal et'}
        </button>
      </div>
    </div>
  )
}

function ResultPanel({ result, voices, busy, lastSource, onConvertWith }) {
  const ext = (result.filename || '').split('.').pop() || 'wav'
  const others = voices.filter((v) => v.id !== result.voice_id)
  return (
    <div className="stack">
      <Player src={result.url} downloadName={`sesklon-donusum-${safeFileName(result.voice_name)}-${result.id}.${ext}`} autoPlay />
      <div className="muted small">
        {result.voice_name} • {fmtSn(result.duration)}
        {result.elapsed != null ? ` • ${fmtNum(result.elapsed, 1)} sn'de dönüştürüldü` : ''}
      </div>
      <div className="small">
        <span className="chip on">✓ Geçmişe eklendi</span>
        <span className="muted"> "Geçmiş" sekmesinden yeniden dinleyebilir ya da indirebilirsiniz.</span>
      </div>
      {lastSource && others.length > 0 && (
        <div className="stack">
          <div className="muted small">Aynı kaynağı ({lastSource.name}) başka bir sesle dönüştür:</div>
          <div className="presets">
            {others.map((v) => (
              <button type="button" key={v.id} className="chip clickable" disabled={busy} onClick={() => onConvertWith(v.id)}>
                ⇄ {v.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Convert({ voices, onGenerated, notify, health }) {
  const [voiceId, setVoiceId] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState(null)
  const [cancelling, setCancelling] = useState(false)
  const [result, setResult] = useState(null)
  const [lastSource, setLastSource] = useState(null) // son dönüştürülen kaynak (kısayol için tutulur)
  const busyRef = useRef(false)
  const cancelRef = useRef(false)
  const fileRef = useRef(null)
  const analysisEnabled = health?.features?.analysis !== false
  const check = useFileAnalysis({ enabled: analysisEnabled, notify })
  const elapsed = useElapsed(busy)

  // Hedef ses listede yoksa (silindiyse) ilk sese geç.
  useEffect(() => {
    if (!voiceId || !voices.some((v) => v.id === voiceId)) setVoiceId(voices[0]?.id || '')
  }, [voices, voiceId])

  function pick(f, fromMic = false) {
    setFile(f)
    if (fromMic && fileRef.current) fileRef.current.value = ''
    check.run(f) // ses→ses için de kaynak kalitesi sonucu doğrudan etkiler
  }

  function clearSource() {
    setFile(null)
    check.reset()
    if (fileRef.current) fileRef.current.value = ''
  }

  async function convert(targetId = voiceId, source = file) {
    if (busyRef.current) return
    if (!source || !targetId) {
      notify('Kaynak ses ve hedef ses seçin.', 'error')
      return
    }
    busyRef.current = true
    cancelRef.current = false
    setBusy(true)
    setCancelling(false)
    setJob(null)
    setResult(null)
    try {
      const gen = await api.vc({ voice_id: targetId, file: source }, setJob)
      if (!gen) {
        notify('Dönüştürme iptal edildi.')
        return
      }
      setResult(gen)
      setLastSource(source)
      onGenerated?.(gen)
      if (cancelRef.current) notify('İptal yetişmedi: dönüştürme tamamlandı ve geçmişe eklendi.', 'warn')
    } catch (err) {
      // waitJob iptalde CancelledError fırlatır; iptal başka yerden (ör. iş listesi) gelmiş de olabilir.
      if (cancelRef.current || api.isCancelled?.(err)) notify('Dönüştürme iptal edildi.')
      else notify(err.message, 'error')
    } finally {
      busyRef.current = false
      setBusy(false)
      setJob(null)
      setCancelling(false)
    }
  }

  async function cancel() {
    if (!job?.id || cancelling) return
    cancelRef.current = true
    setCancelling(true)
    try {
      await api.cancelJob(job.id)
    } catch (err) {
      cancelRef.current = false
      setCancelling(false)
      notify('İptal edilemedi: ' + err.message, 'error')
    }
  }

  function convertWith(id) {
    setVoiceId(id)
    convert(id, lastSource)
  }

  return (
    <div className="grid two">
      <section className="card">
        <h2>Ses → ses dönüştür</h2>
        <p className="muted">Kendi konuşmanızı kaydedin ya da yükleyin; söylediğiniz her şey tonlamasıyla birlikte seçtiğiniz sesle yeniden söylenir.</p>
        <form onSubmit={(e) => { e.preventDefault(); convert() }} className="stack">
          <label>Hedef ses
            <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
              {voices.length === 0 && <option value="">Önce bir ses ekleyin</option>}
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
          <SourceInput file={file} fileRef={fileRef} onPick={pick} onClear={clearSource} check={check} analysisEnabled={analysisEnabled} />
          <button className="btn primary big" disabled={busy || !file || !voiceId}>
            {busy ? (job?.status === 'queued' ? 'Sırada…' : 'Dönüştürülüyor…') : '⇄ Dönüştür'}
          </button>
          {busy && <JobProgress job={job} elapsed={elapsed} cancelling={cancelling} onCancel={cancel} />}
        </form>
      </section>

      <section className="card">
        <h2>Sonuç</h2>
        {!result && <p className="muted">{busy ? 'Dönüştürme sürüyor; bitince burada çalınacak.' : 'Dönüştürülen ses burada görünecek.'}</p>}
        {result && <ResultPanel result={result} voices={voices} busy={busy} lastSource={lastSource} onConvertWith={convertWith} />}
      </section>
    </div>
  )
}
