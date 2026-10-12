import { api } from '../api'
import Player, { fmtDate, fmtDur } from './Player'

export default function History({ items, languages, reload, notify }) {
  async function remove(g) {
    if (!confirm('Bu kayıt silinsin mi?')) return
    try { await api.deleteGeneration(g.id); await reload() } catch (err) { notify(err.message, 'error') }
  }

  return (
    <section className="card">
      <h2>Geçmiş <span className="count">{items.length}</span></h2>
      {items.length === 0 && <p className="muted">Henüz üretim yok.</p>}
      <ul className="list">
        {items.map((g) => (
          <li key={g.id} className="item">
            <div className="item-head">
              <div>
                <span className={`tag ${g.kind}`}>{g.kind === 'tts' ? 'Metin → Ses' : 'Ses → Ses'}</span>
                <strong> {g.voice_name}</strong>
                <div className="muted small">
                  {fmtDate(g.created_at)} • {languages[g.language] || g.language || ''} • {fmtDur(g.duration)}
                  {g.params?.chunks?.length ? ` • ${g.params.chunks.length} parça` : ''}{g.params?.emotion ? ` • ${g.params.emotion}` : ''}
                </div>
              </div>
              <button className="btn ghost small danger-text" onClick={() => remove(g)}>Sil</button>
            </div>
            {g.text && <p className="quote small">{g.text.length > 220 ? g.text.slice(0, 220) + '…' : g.text}</p>}
            <Player src={g.url} downloadName={`sesklon-${g.id}.${g.filename.split('.').pop()}`} />
          </li>
        ))}
      </ul>
    </section>
  )
}
