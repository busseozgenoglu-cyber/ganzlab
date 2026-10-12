import { useRef, useState } from 'react'
import { api } from '../api'
import { useRecorder } from '../useRecorder'
import Player, { fmtDur } from './Player'

const SAMPLE_SCRIPTS = {
  'heyecanlı': 'Vay be, bu gerçekten inanılmaz! Bugün size bomba gibi bir şey göstereceğim, hazır olun!',
  'mutlu': 'Bugün çok güzel bir gün, her şey yolunda gidiyor ve ben bundan gerçekten keyif alıyorum.',
  'sakin': 'Şimdi derin bir nefes al. Acele etmeye gerek yok, her şey sırasıyla olacak.',
  'ciddi': 'Bu konu gerçekten önemli. Lütfen söyleyeceklerimi dikkatle dinleyin.',
  'üzgün': 'Keşke her şey farklı olsaydı. Bunu söylemek bana çok zor geliyor, maalesef.',
  'kızgın': 'Yeter artık! Bu kadarı da fazla, kabul edilemez, bıktım bunlardan!',
  'şaşkın': 'Ne? Gerçekten mi? İnanamıyorum, bunu hiç beklemiyordum!',
  'korkmuş': 'Dur, bir ses duydun mu? Buradan hemen çıkmamız lazım, lütfen acele et.',
  'fısıltı': 'Şşş, sessiz ol. Kimse duymasın, sana gizli bir şey söyleyeceğim.',
  'vurgulu': 'Bunu asla unutmayın: en önemli şey, her gün biraz daha ilerlemektir.',
  'samimi': 'Canım, bugün nasılsın? Seninle konuşmak gerçekten çok iyi geliyor.',
  'sıkılmış': 'Of, yine mi aynı şey. Tamam, yapalım da bitsin artık.',
  'alaycı': 'Tabii, kesinlikle. Harika bir fikir, hiç aklıma gelmezdi.',
}

function Recorder({ onFile, label = '● Mikrofondan kaydet' }) {
  const rec = useRecorder()
  async function toggle() {
    if (rec.recording) { const f = await rec.stop(); if (f) onFile(f) } else await rec.start()
  }
  return (
    <>
      <button type="button" className={`btn ${rec.recording ? 'danger' : 'secondary'}`} onClick={toggle}>
        {rec.recording ? `■ Durdur (${rec.seconds} sn)` : label}
      </button>
      {rec.error && <div className="alert error">{rec.error}</div>}
    </>
  )
}

export default function Voices({ voices, languages, health, reload, notify }) {
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('tr')
  const [file, setFile] = useState(null)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [openVoice, setOpenVoice] = useState(null)
  const [sampleEmotion, setSampleEmotion] = useState('heyecanlı')
  const [sampleFile, setSampleFile] = useState(null)
  const fileRef = useRef(null)
  const emotions = (health?.tags?.emotions || []).filter((e) => e.name !== 'normal' && !['hızlı', 'yavaş'].includes(e.name))

  async function submit(e) {
    e.preventDefault()
    if (!file) return notify('Önce bir ses dosyası seçin veya kaydedin.', 'error')
    if (!consent) return notify('Bu sesi kullanma izniniz olduğunu onaylayın.', 'error')
    setBusy(true)
    try {
      await api.createVoice({ name: name || file.name.replace(/\.[^.]+$/, ''), language, file, consent })
      setName(''); setFile(null); setConsent(false)
      if (fileRef.current) fileRef.current.value = ''
      await reload(); notify('Ses eklendi.')
    } catch (err) { notify(err.message, 'error') } finally { setBusy(false) }
  }

  async function addSample(v) {
    if (!sampleFile) return notify('Önce kayıt yapın veya dosya seçin.', 'error')
    setBusy(true)
    try {
      await api.addSample(v.id, sampleEmotion, sampleFile)
      setSampleFile(null); await reload(); notify(`"${sampleEmotion}" kaydı eklendi.`)
    } catch (err) { notify(err.message, 'error') } finally { setBusy(false) }
  }

  async function removeSample(v, emotion) {
    try { await api.deleteSample(v.id, emotion); await reload() } catch (err) { notify(err.message, 'error') }
  }

  async function remove(v) {
    if (!confirm(`"${v.name}" ve tüm duygu kayıtları silinsin mi?`)) return
    try { await api.deleteVoice(v.id); await reload() } catch (err) { notify(err.message, 'error') }
  }

  async function rename(v) {
    const n = prompt('Yeni ad:', v.name)
    if (!n || n === v.name) return
    try { await api.renameVoice(v.id, n); await reload() } catch (err) { notify(err.message, 'error') }
  }

  return (
    <div className="grid two">
      <section className="card">
        <h2>Yeni ses ekle</h2>
        <p className="muted">8–15 saniyelik, sessiz ortamda, doğal tonda bir konuşma örneği. Yüklenen kayıt otomatik kırpılır, sessizlikleri temizlenir ve seviyesi dengelenir (konuşmanın en yoğun 15 sn'si seçilir).</p>
        <form onSubmit={submit} className="stack">
          <label>Ses adı
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="örn. Buse — doğal" maxLength={80} />
          </label>
          <label>Örneğin dili
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {Object.entries(languages).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <div className="row">
            <label className="grow">Ses dosyası (mp3, wav, m4a, ogg, webm, mp4…)
              <input ref={fileRef} type="file" accept="audio/*,video/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <Recorder onFile={(f) => { setFile(f); notify('Kayıt alındı.') }} />
          </div>
          {file && <div className="chip">Seçili: {file.name} {file.size ? `(${(file.size / 1024).toFixed(0)} KB)` : ''}</div>}
          <label className="check">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            Bu ses bana ait veya sahibinden kullanım izni aldım.
          </label>
          <button className="btn primary" disabled={busy}>{busy ? 'Yükleniyor…' : 'Sesi kaydet'}</button>
        </form>
      </section>

      <section className="card">
        <h2>Ses kütüphanesi <span className="count">{voices.length}</span></h2>
        {voices.length === 0 && <p className="muted">Henüz ses yok. Soldan bir örnek ekleyin.</p>}
        <ul className="list">
          {voices.map((v) => (
            <li key={v.id} className="item">
              <div className="item-head">
                <div>
                  <strong>{v.name}</strong>
                  <div className="muted small">{languages[v.language] || v.language} • {fmtDur(v.duration)} • {v.samples?.length || 0} duygu kaydı</div>
                </div>
                <div className="actions">
                  <button className="btn ghost small" onClick={() => setOpenVoice(openVoice === v.id ? null : v.id)}>{openVoice === v.id ? 'Kapat' : 'Duygu kayıtları'}</button>
                  <button className="btn ghost small" onClick={() => rename(v)}>Ad</button>
                  <button className="btn ghost small danger-text" onClick={() => remove(v)}>Sil</button>
                </div>
              </div>
              <Player src={v.url} downloadName={`${v.name}.wav`} />

              {openVoice === v.id && (
                <div className="samplebox stack">
                  <div className="muted small">
                    Her duygu için o tonda 8–15 sn kayıt ekle; <b>[etiket]</b> kullanıldığında o kayıt referans alınır. Kayıt olmayan duygular yalnızca üretim ayarlarıyla verilir (daha zayıf).
                  </div>
                  <div className="presets">
                    {emotions.map((e) => {
                      const has = v.samples?.find((s) => s.emotion === e.name)
                      return (
                        <button type="button" key={e.name} className={`chip clickable ${has ? 'on' : ''} ${sampleEmotion === e.name ? 'active' : ''}`} onClick={() => setSampleEmotion(e.name)}>
                          {has ? '✓ ' : ''}{e.label}
                        </button>
                      )
                    })}
                  </div>
                  <div className="script">
                    <div className="muted small">Okuma metni ({sampleEmotion}) — bu tonda, doğal konuşur gibi:</div>
                    <blockquote className="quote">{SAMPLE_SCRIPTS[sampleEmotion] || 'Bu duyguda, doğal konuşur gibi 8–15 saniye konuşun.'}</blockquote>
                  </div>
                  <div className="row">
                    <label className="grow">Dosya
                      <input type="file" accept="audio/*,video/*" onChange={(e) => setSampleFile(e.target.files?.[0] || null)} />
                    </label>
                    <Recorder onFile={(f) => { setSampleFile(f); notify('Kayıt alındı.') }} label="● Kaydet" />
                    <button type="button" className="btn primary" disabled={busy || !sampleFile} onClick={() => addSample(v)}>"{sampleEmotion}" olarak ekle</button>
                  </div>
                  {sampleFile && <div className="chip">Seçili: {sampleFile.name}</div>}
                  {v.samples?.length > 0 && (
                    <ul className="list">
                      {v.samples.map((s) => (
                        <li key={s.id} className="item small">
                          <div className="item-head">
                            <span><span className="tag emo">{s.emotion}</span> <span className="muted">{fmtDur(s.duration)}</span></span>
                            <button className="btn ghost small danger-text" onClick={() => removeSample(v, s.emotion)}>Sil</button>
                          </div>
                          <Player src={s.url} downloadName={`${v.name}-${s.emotion}.wav`} />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
