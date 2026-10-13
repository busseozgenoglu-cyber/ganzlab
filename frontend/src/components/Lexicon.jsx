import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { api } from '../api'

/**
 * Telaffuz sekmesi: genel ya da ses başına telaffuz sözlüğü (sözcük → okunuş), deneme alanı ve ipuçları.
 * Sözleşme: docs/SOZLESME2.md §8–10 — api.lexicon(voiceId?), setLexicon, deleteLexicon, testLexicon.
 *   <Lexicon voices={[…]} health={…} notify={(mesaj, tür) => …} />
 * Sunucuda sözlük yoksa (features.lexicon === false ya da 404) uyarı gösterilir, formlar kapanır.
 */

const trLower = (s) => String(s ?? '').toLocaleLowerCase('tr-TR')
const squash = (s) => String(s ?? '').replace(/\s+/g, ' ').trim()
const WORD_MAX = 80
const READING_MAX = 160
const TEST_MAX = 2000
const BAD_CHARS_RE = /[{}|[\]\n]/ // satır içi okunuş ve etiket sözdizimiyle karışmasın

// testLexicon değişiklik kaynakları → Türkçe etiket (sunucu farklı ad gönderirse olduğu gibi gösterilir)
const SOURCE_LABELS = {
  lexicon: 'sözlük', global: 'genel sözlük', voice: 'ses sözlüğü', inline: 'satır içi okunuş', reading: 'satır içi okunuş',
  chat: 'sohbet kısaltması', chat_speak: 'sohbet kısaltması', abbrev: 'kısaltma', abbreviation: 'kısaltma',
  textnorm: 'yazım düzeltme', normalize: 'yazım düzeltme', number: 'sayı', colloquial: 'konuşma dili',
  pronunciation: 'yerleşik okunuş', builtin: 'yerleşik okunuş', default: 'yerleşik okunuş',
}

/** Sunucu yanıtı → [{ word, reading, scope }]. Dizi, {entries}, {items} ya da {sözcük: okunuş} kabul edilir. */
function normalizeEntries(res, voiceScope) {
  let list = []
  if (Array.isArray(res)) list = res
  else if (Array.isArray(res?.entries)) list = res.entries
  else if (Array.isArray(res?.items)) list = res.items
  else if (res && typeof res === 'object') {
    const pairs = Object.entries(res)
    if (pairs.every(([, v]) => typeof v === 'string')) list = pairs.map(([word, reading]) => ({ word, reading }))
  }
  return list
    .filter((e) => e && typeof e.word === 'string' && e.word.trim())
    .map((e) => ({
      word: e.word.trim(),
      reading: squash(e.reading),
      // ses kapsamında scope yazılmamışsa sese özel sayılır; genel kapsamda hepsi geneldir
      scope: voiceScope ? (e.scope === 'global' ? 'global' : 'voice') : 'global',
    }))
}

/** Aynı sözcüğün genel ve sese özel girdisi varsa sese özel olan gösterilir, genel okunuş not düşülür. */
function buildRows(entries, voiceScope) {
  const map = new Map()
  for (const e of entries) {
    const key = trLower(e.word)
    const cur = map.get(key)
    if (!cur) map.set(key, { ...e, key, overrides: '' })
    else if (voiceScope && e.scope === 'voice' && cur.scope !== 'voice') map.set(key, { ...e, key, overrides: cur.reading })
    else if (voiceScope && e.scope !== 'voice' && cur.scope === 'voice') cur.overrides = e.reading
  }
  return [...map.values()].sort((a, b) => a.word.localeCompare(b.word, 'tr', { sensitivity: 'base' }))
}

/** testLexicon değişiklik öğesi → { text: "Shopify → Şopifay", to: "Şopifay", source: "genel sözlük" } */
function changeView(c) {
  if (typeof c === 'string') return { text: c, to: '', source: '' }
  if (!c || typeof c !== 'object') return null
  const from = c.from ?? c.word ?? c.original ?? c.src ?? c.before
  const to = c.to ?? c.reading ?? c.replacement ?? c.dst ?? c.after
  const src = String(c.source ?? c.kind ?? c.type ?? c.scope ?? '')
  return {
    text: from != null && to != null ? `${from} → ${to}` : JSON.stringify(c),
    to: to != null ? String(to) : '',
    source: SOURCE_LABELS[trLower(src)] || src,
  }
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Modelin okuyacağı metinde değişen okunuşları <mark> ile işaretler (en uzun önce). */
function highlight(text, words) {
  const list = [...new Set(words.map((w) => w.trim()).filter(Boolean))].sort((a, b) => b.length - a.length).slice(0, 50)
  if (!text || !list.length) return text
  const parts = text.split(new RegExp(`(${list.map(escapeRe).join('|')})`, 'g'))
  return parts.map((p, i) => (i % 2 === 1 ? <mark key={i}>{p}</mark> : p))
}

function validate(word, reading) {
  if (!word) return 'Sözcüğü yaz.'
  if (!reading) return 'Okunuşu yaz: sözcüğün Türkçe okunduğu gibi yazılışı (ör. Şopifay).'
  if (BAD_CHARS_RE.test(word) || BAD_CHARS_RE.test(reading)) return 'Sözcük ve okunuşta { } | [ ] karakterleri kullanılamaz.'
  if (trLower(word) === trLower(reading)) return 'Okunuş sözcükle aynı; farklı bir okunuş yaz.'
  return ''
}

/* ---------- tablo satırı ---------- */

function LexRow({ row, voiceScope, editing, busy, locked, onEdit, onChange, onSave, onCancel, onDelete }) {
  const inherited = voiceScope && row.scope === 'global'
  const onKeyDown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); onSave() } else if (e.key === 'Escape') { e.preventDefault(); onCancel() }
  }
  return (
    <tr className={`lex-row${inherited ? ' inherited' : ''}`}>
      <td className="lex-word">
        <b>{row.word}</b>
        {voiceScope && (
          <> <span className={`badge${row.scope === 'voice' ? ' accent' : ''}`}>{row.scope === 'voice' ? 'bu ses' : 'genel'}</span></>
        )}
      </td>
      <td className="lex-reading">
        {editing ? (
          <input value={editing.value} onChange={(e) => onChange(e.target.value)} onKeyDown={onKeyDown} autoFocus
            maxLength={READING_MAX} autoComplete="off" spellCheck={false} disabled={busy}
            aria-label={`"${row.word}" okunuşu${editing.toVoice ? ' (yalnızca bu ses için)' : ''}`} />
        ) : (
          <>
            <span>{row.reading}</span>
            {row.overrides && <span className="muted small"> (genel: {row.overrides})</span>}
          </>
        )}
      </td>
      {/* son hücre: tr.lex-row td:last-child sağa yaslı, satır kırılmaz; düğmeler satır içi (inline-flex) */}
      <td className="lex-actions">
        {editing ? (
          <>
            <button type="button" className="btn primary small" onClick={onSave} disabled={busy}>{busy ? 'Kaydediliyor…' : 'Kaydet'}</button>
            {' '}
            <button type="button" className="btn ghost small" onClick={onCancel} disabled={busy}>Vazgeç</button>
          </>
        ) : (
          <>
            <button type="button" className="btn ghost small" onClick={onEdit} disabled={locked}
              title={inherited ? 'Genel okunuşu bozmadan yalnızca bu ses için farklı okunuş tanımla' : undefined}
              aria-label={`"${row.word}" okunuşunu ${inherited ? 'bu ses için değiştir' : 'düzenle'}`}>
              {inherited ? 'Bu ses için değiştir' : 'Düzenle'}
            </button>
            {!inherited && (
              <>
                {' '}
                <button type="button" className="btn ghost small danger-text" onClick={onDelete} disabled={locked}
                  aria-label={`"${row.word}" girdisini sil`}>
                  {busy ? 'Siliniyor…' : 'Sil'}
                </button>
              </>
            )}
          </>
        )}
      </td>
    </tr>
  )
}

/* ---------- sekme ---------- */

export default function Lexicon({ voices = [], health, notify }) {
  const [scope, setScope] = useState('') // '' = genel sözlük; aksi hâlde ses kimliği
  const [entries, setEntries] = useState([])
  const [status, setStatus] = useState('loading') // loading | ready | missing | error
  const [loadError, setLoadError] = useState('')
  const [query, setQuery] = useState('')
  const [word, setWord] = useState('')
  const [reading, setReading] = useState('')
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState(null) // { key, word, value, original, toVoice }
  const [busyKey, setBusyKey] = useState('')
  const [testText, setTestText] = useState('')
  const [testLang, setTestLang] = useState('tr')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null) // { normalized, changes } | { error }
  const seq = useRef(0)
  const wordRef = useRef(null)

  const titleId = useId()
  const scopeId = useId()
  const wordId = useId()
  const readingId = useId()
  const testId = useId()
  const testTitleId = useId()

  const supported = health?.features?.lexicon !== false && typeof api.lexicon === 'function'
  const voice = voices.find((v) => v.id === scope) || null
  const voiceScope = Boolean(scope)
  const languages = health?.languages && typeof health.languages === 'object' ? health.languages : { tr: 'Türkçe' }

  const load = useCallback(async () => {
    const id = ++seq.current
    if (!supported) {
      setStatus('missing')
      return
    }
    try {
      const res = await api.lexicon(scope || undefined)
      if (id !== seq.current) return
      setEntries(normalizeEntries(res, Boolean(scope)))
      setLoadError('')
      setStatus('ready')
    } catch (err) {
      if (id !== seq.current) return
      if (err?.status === 404 || err?.status === 405 || err?.status === 501) {
        setStatus('missing')
      } else {
        setLoadError(err?.message || 'Sözlük yüklenemedi.')
        setStatus('error')
      }
    }
  }, [scope, supported])

  useEffect(() => { load() }, [load])

  // Seçili ses silinirse genel sözlüğe dön; ses değişince deneme dili o sesin dili olsun
  useEffect(() => {
    if (scope && voices.length && !voices.some((v) => v.id === scope)) changeScope('')
  }, [voices, scope]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (voice?.language && languages[voice.language]) setTestLang(voice.language)
  }, [voice?.language]) // eslint-disable-line react-hooks/exhaustive-deps

  function changeScope(id) {
    setScope(id)
    setEntries([])
    setStatus(supported ? 'loading' : 'missing')
    setEditing(null)
    setFormError('')
    setTestResult(null)
  }

  const rows = useMemo(() => buildRows(entries, voiceScope), [entries, voiceScope])
  const q = trLower(query.trim())
  const shown = q ? rows.filter((r) => trLower(r.word).includes(q) || trLower(r.reading).includes(q)) : rows
  const ready = status === 'ready'
  const voiceOwn = rows.filter((r) => r.scope === 'voice').length

  /* ----- ekleme ----- */
  async function onAdd(e) {
    e.preventDefault()
    if (saving || !ready) return
    const w = squash(word)
    const r = squash(reading)
    const problem = validate(w, r)
    if (problem) {
      setFormError(problem)
      return
    }
    const same = rows.find((x) => x.key === trLower(w) && (!voiceScope || x.scope === 'voice'))
    if (same && !window.confirm(`"${same.word}" zaten var (okunuşu: ${same.reading}). "${r}" ile değiştirilsin mi?`)) return
    setSaving(true)
    setFormError('')
    try {
      await api.setLexicon(w, r, scope || undefined)
      setWord('')
      setReading('')
      notify(`${same ? 'Güncellendi' : 'Eklendi'}: ${w} → ${r}${voice ? ` (yalnızca ${voice.name})` : ''}`)
      await load()
      wordRef.current?.focus()
    } catch (err) {
      setFormError(err?.message || 'Kaydedilemedi.')
    } finally {
      setSaving(false)
    }
  }

  /* ----- satır içi düzenleme ----- */
  function startEdit(row) {
    setEditing({ key: row.key, word: row.word, value: row.reading, original: row.reading, toVoice: voiceScope && row.scope === 'global' })
  }

  async function saveEdit() {
    const ed = editing
    if (!ed || busyKey) return
    const r = squash(ed.value)
    if (!r) {
      notify('Okunuş boş olamaz; girdiyi kaldırmak için "Sil"i kullan.', 'error')
      return
    }
    if (r === ed.original && !ed.toVoice) {
      setEditing(null)
      return
    }
    const problem = validate(ed.word, r)
    if (problem) {
      notify(problem, 'error')
      return
    }
    setBusyKey(ed.key)
    try {
      await api.setLexicon(ed.word, r, scope || undefined)
      setEditing(null)
      notify(ed.toVoice ? `"${ed.word}" artık ${voice?.name || 'bu ses'} için "${r}" okunacak.` : `"${ed.word}" → ${r}`)
      await load()
    } catch (err) {
      notify(err?.message || 'Kaydedilemedi.', 'error')
    } finally {
      setBusyKey('')
    }
  }

  async function remove(row) {
    if (busyKey) return
    const fallback = row.overrides ? ` Genel okunuş ("${row.overrides}") geçerli olacak.` : ''
    if (!window.confirm(`"${row.word}" ${voiceScope ? 'bu sesin sözlüğünden' : 'sözlükten'} silinsin mi?${fallback}`)) return
    setBusyKey(row.key)
    try {
      await api.deleteLexicon(row.word, scope || undefined)
      notify(`"${row.word}" silindi.${fallback}`)
      await load()
    } catch (err) {
      notify(err?.message || 'Silinemedi.', 'error')
    } finally {
      setBusyKey('')
    }
  }

  /* ----- deneme ----- */
  async function onTest(e) {
    e?.preventDefault()
    const t = testText.trim()
    if (!t || testing) return
    if (typeof api.testLexicon !== 'function') {
      setTestResult({ error: 'Deneme bu sürümde yok.' })
      return
    }
    setTesting(true)
    try {
      const res = await api.testLexicon(t, scope || undefined, testLang)
      const changes = (Array.isArray(res?.changes) ? res.changes : []).map(changeView).filter(Boolean)
      setTestResult({ normalized: String(res?.normalized ?? res?.text ?? ''), changes })
    } catch (err) {
      setTestResult({ error: err?.status === 404 ? 'Bu sunucuda deneme uç noktası yok.' : err?.message || 'Denenemedi.' })
    } finally {
      setTesting(false)
    }
  }

  const langEntries = Object.entries(languages)

  return (
    <div className="grid two lexicon">
      <section className="card" aria-labelledby={titleId}>
        <h2 id={titleId}>
          Telaffuz sözlüğü {ready && <span className="count">{rows.length}</span>}
        </h2>
        <p className="muted small">
          Model bir sözcüğü yanlış okuyorsa doğru okunuşunu bir kez buraya yaz; her seslendirmede kendiliğinden uygulanır.
        </p>

        <div className="toolbar lex-toolbar">
          <label className="inline small" htmlFor={scopeId}>
            Kapsam
            <select id={scopeId} value={scope} onChange={(e) => changeScope(e.target.value)} disabled={!supported}>
              <option value="">Genel — tüm sesler</option>
              {voices.length > 0 && (
                <optgroup label="Yalnızca bu ses">
                  {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </optgroup>
              )}
            </select>
          </label>
          <input type="search" className="search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Ara: sözcük ya da okunuş" aria-label="Sözlükte ara" disabled={!ready || rows.length === 0} />
        </div>
        {voice && ready && (
          <div className="muted small">
            "{voice.name}" için tanımlananlar ({voiceOwn}) genel sözlüğü ezer; diğer genel girdiler bu seste de geçerlidir.
          </div>
        )}

        {status === 'missing' ? (
          <div className="alert warn" role="status">
            <b>Bu sunucuda telaffuz sözlüğü yok.</b> Sunucu güncellenince yabancı sözcüklerin okunuşunu buradan
            tanımlayabilirsin. O zamana kadar sözcüğü metne okunduğu gibi yazabilirsin (Shopify yerine "Şopifay").
          </div>
        ) : (
          <>
            <form className="row lex-new" onSubmit={onAdd} noValidate aria-label="Yeni okunuş">
              <label className="grow" htmlFor={wordId}>
                Sözcük
                <input id={wordId} ref={wordRef} value={word} maxLength={WORD_MAX} placeholder="Shopify" autoComplete="off"
                  spellCheck={false} onChange={(e) => { setWord(e.target.value); setFormError('') }} />
              </label>
              <label className="grow" htmlFor={readingId}>
                Okunuş
                <input id={readingId} value={reading} maxLength={READING_MAX} placeholder="Şopifay" autoComplete="off"
                  spellCheck={false} onChange={(e) => { setReading(e.target.value); setFormError('') }} />
              </label>
              <button type="submit" className="btn primary" disabled={saving || !ready}>
                {saving ? 'Kaydediliyor…' : voice ? `+ ${voice.name} için kaydet` : '+ Kaydet'}
              </button>
            </form>
            {formError && <div className="alert error" role="alert">{formError}</div>}

            {status === 'loading' ? (
              <div className="muted small" role="status"><span className="spinner" aria-hidden="true" /> Sözlük yükleniyor…</div>
            ) : status === 'error' ? (
              <div className="alert error row between" role="alert">
                <span>Sözlük yüklenemedi: {loadError}</span>
                <button type="button" className="btn ghost small" onClick={load}>Yeniden dene</button>
              </div>
            ) : rows.length === 0 ? (
              <div className="empty">
                <strong>{voice ? `"${voice.name}" için özel okunuş yok` : 'Sözlük boş'}</strong>
                <span className="small">
                  {voice
                    ? 'Bu ses için farklı okunması gereken bir ad varsa yukarıdan ekle; yoksa genel sözlük uygulanır.'
                    : 'Yabancı marka ve adların Türkçe okunuşunu ekle: Shopify → Şopifay, iPhone → Ayfon.'}
                </span>
              </div>
            ) : shown.length === 0 ? (
              <div className="muted small" role="status">"{query.trim()}" için sonuç yok.</div>
            ) : (
              <div className="table-wrap">
                <table className="lex-table">
                  <caption className="sr-only">Telaffuz sözlüğü: sözcük ve okunuşu</caption>
                  <thead>
                    <tr>
                      <th scope="col">Sözcük</th>
                      <th scope="col">Okunuş</th>
                      <th scope="col"><span className="sr-only">İşlemler</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((row) => {
                      const isEditing = editing?.key === row.key
                      return (
                        <LexRow key={row.key} row={row} voiceScope={voiceScope} editing={isEditing ? editing : null}
                          busy={busyKey === row.key} locked={Boolean(busyKey) || Boolean(editing && !isEditing)}
                          onEdit={() => startEdit(row)} onChange={(value) => setEditing((ed) => (ed ? { ...ed, value } : ed))}
                          onSave={saveEdit} onCancel={() => setEditing(null)} onDelete={() => remove(row)} />
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {ready && q && shown.length > 0 && shown.length < rows.length && (
              <div className="muted small">{rows.length} girdiden {shown.length} tanesi gösteriliyor.</div>
            )}
          </>
        )}
      </section>

      <div className="stack">
        <section className="card" aria-labelledby={testTitleId}>
          <h2 id={testTitleId}>Dene</h2>
          <p className="muted small">
            Bir metin yaz: sözlük, satır içi okunuşlar ve sohbet kısaltmaları uygulanınca modelin okuyacağı hâli görürsün.
            {voice ? ` "${voice.name}" sözlüğü de uygulanır.` : ''}
          </p>
          <form className="stack" onSubmit={onTest}>
            <label htmlFor={testId}>
              Metin
              <textarea id={testId} rows={4} value={testText} maxLength={TEST_MAX}
                placeholder="Shopify mağazamı yarın {Claude|Klod} ile kuruyoruz, tmm mı?"
                onChange={(e) => setTestText(e.target.value)}
                onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); onTest() } }} />
            </label>
            <div className="row">
              {langEntries.length > 1 && (
                <label className="inline small">
                  Dil
                  <select value={testLang} onChange={(e) => setTestLang(e.target.value)}>
                    {langEntries.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
              )}
              <button type="submit" className="btn secondary" disabled={!testText.trim() || testing || status === 'missing'}
                aria-keyshortcuts="Control+Enter">
                {testing ? 'Deneniyor…' : 'Dene'}
              </button>
            </div>
          </form>
          <div aria-live="polite">
            {testResult?.error && <div className="alert error">{testResult.error}</div>}
            {testResult && !testResult.error && (
              <div className="lex-test">
                <span className="muted small">Modelin okuyacağı metin</span>
                <blockquote className="quote">
                  {testResult.normalized ? highlight(testResult.normalized, testResult.changes.map((c) => c.to)) : '(boş)'}
                </blockquote>
                {testResult.changes.length > 0 ? (
                  <>
                    <span className="muted small">Değişiklikler ({testResult.changes.length})</span>
                    <div className="presets">
                      {testResult.changes.map((c, i) => (
                        <span key={i} className="chip small">
                          {c.text}{c.source && <span className="muted"> · {c.source}</span>}
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="muted small">Değişiklik yok — metin olduğu gibi okunur.</div>
                )}
              </div>
            )}
          </div>
        </section>

        <section className="card">
          <h2>İpuçları</h2>
          <ul className="tips">
            <li className="tip">
              Yabancı markaları Türkçe okunuşuyla yaz: <b>Shopify → Şopifay</b>, <b>iPhone → Ayfon</b>, <b>WhatsApp → Vatsap</b>.
            </li>
            <li className="tip">
              Tek seferlik okunuş için metne <code>{'{sözcük|okunuş}'}</code> yaz: <code>{'{Claude|Klod}'}</code>.
              Seslendir sekmesindeki <b>{'{Okunuş}'}</b> düğmesi seçili sözcük için bunu senin yerine yapar.
            </li>
            <li className="tip">
              Ses sözlüğü genel sözlüğü ezer: bir ses bir adı farklı okuyacaksa kapsamdan o sesi seç.
            </li>
            <li className="tip">
              Eşleşme büyük/küçük harfe bakmaz ve tam sözcüğü arar; baş harfin büyüklüğü korunur. Uzun ifadeler önce
              uygulanır ("New York" girdisi "York"tan önce).
            </li>
            <li className="tip">
              "tmm", "slm" gibi sohbet kısaltmaları "Sohbet kısaltmaları" açıkken kendiliğinden açılır; buraya eklemen gerekmez.
            </li>
          </ul>
        </section>
      </div>
    </div>
  )
}
