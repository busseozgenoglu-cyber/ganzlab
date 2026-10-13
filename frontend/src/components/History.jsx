import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import Player, { fmtDate, fmtDur } from './Player'

const REUSE_KEY = 'sesklon_reuse' // Generate bu anahtarı okur: { text, params }
const PAGE = 50
const CLIP = 220
const LETTERS = 'ABCDEFGHIJ'
const FILTERS = [
  { id: 'all', label: 'Tümü' },
  { id: 'tts', label: 'Metin → Ses' },
  { id: 'vc', label: 'Ses → Ses' },
  { id: 'fav', label: 'Favoriler' },
]
const FX_LABEL = { light: 'hafif', full: 'tam' }
const TR_FOLD = { ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u', â: 'a', î: 'i', û: 'u' }

// Türkçe büyük/küçük harf ve aksan duyarsız karşılaştırma için katlama.
const fold = (s) => String(s ?? '')
  .toLocaleLowerCase('tr-TR')
  .replace(/[çğıöşüâîû]/g, (c) => TR_FOLD[c])
  .normalize('NFD')
  .replace(/[̀-ͯ]/g, '')

const isFav = (g) => g?.favorite === true || g?.favorite === 1 || g?.favorite === '1' || g?.favorite === 'true'
const seedOf = (g) => g?.seed ?? g?.params?.seed ?? null
const groupIdOf = (g) => g?.group_id || g?.params?.group_id || null
const extOf = (g) => {
  const f = g?.filename || g?.url || ''
  const m = /\.([a-z0-9]+)(?:\?.*)?$/i.exec(f)
  return m ? m[1].toLowerCase() : 'wav'
}

function useDebounced(value, ms) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Sunucu filtreleri yok sayarsa (eski sürüm) diye istemcide de süzer; hiçbir zaman sunucunun döndürdüğünden daha dar değildir. */
function matches(g, { q, filter, voiceId }) {
  if ((filter === 'tts' || filter === 'vc') && g.kind !== filter) return false
  if (filter === 'fav' && !isFav(g)) return false
  if (voiceId && g.voice_id !== voiceId) return false
  if (q) {
    const hay = fold([g.text, g.voice_name, g.params?.normalized_text, g.params?.style, g.params?.emotion].filter(Boolean).join('\n'))
    return fold(q).split(/\s+/).filter(Boolean).every((w) => hay.includes(w))
  }
  return true
}

/** Yeni ilk sayfayı, daha önce yüklenmiş eski sayfalarla birleştirir ("daha fazla yükle" kaybolmasın). */
function mergeFirstPage(first, prev, deleted) {
  const ids = new Set(first.map((g) => g.id))
  const oldest = first.length ? String(first[first.length - 1].created_at || '') : ''
  if (!oldest) return first
  const extra = prev.filter((g) => !ids.has(g.id) && !deleted.has(g.id) && String(g.created_at || '') < oldest)
  return extra.length ? [...first, ...extra] : first
}

function variantOrder(a, b) {
  const ia = a.params?.variant_index ?? a.params?.variant
  const ib = b.params?.variant_index ?? b.params?.variant
  if (Number.isFinite(ia) && Number.isFinite(ib) && ia !== ib) return ia - ib
  return String(a.created_at || '').localeCompare(String(b.created_at || '')) || String(a.id).localeCompare(String(b.id))
}

export default function History({ items, languages = {}, reload, notify, voices, onReuse, styles }) {
  const [q, setQ] = useState('')
  const dq = useDebounced(q.trim(), 300)
  const [filter, setFilter] = useState('all')
  const [voiceId, setVoiceId] = useState('')
  const isFiltered = !!(dq || filter !== 'all' || voiceId)
  // items verilmemişse (bağımsız kullanım) ya da filtre varsa liste sunucudan çekilir.
  const serverMode = isFiltered || items == null

  const [list, setList] = useState(() => items || [])
  const [total, setTotal] = useState(() => (Number.isFinite(items?.total) ? items.total : null))
  const [hasMore, setHasMore] = useState(() => (Number.isFinite(items?.total) ? items.total > (items?.length || 0) : (items?.length || 0) >= PAGE))
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState(() => new Set())
  const [expanded, setExpanded] = useState(() => new Set())
  const [activeIdx, setActiveIdx] = useState({})

  const deletedRef = useRef(new Set())
  const seqRef = useRef(0)
  const listKeyRef = useRef('')
  const seenVoicesRef = useRef(new Map())
  const searchRef = useRef(null)

  const query = useMemo(() => ({
    q: dq || undefined,
    kind: filter === 'tts' || filter === 'vc' ? filter : undefined,
    favorite: filter === 'fav' ? true : undefined,
    voice_id: voiceId || undefined,
  }), [dq, filter, voiceId])
  const qKey = JSON.stringify(query)
  const crit = useMemo(() => ({ q: dq, filter, voiceId }), [dq, filter, voiceId])

  // Filtre yokken ilk sayfa App'ten gelir (items); her yenilemede eski sayfalar korunur.
  useEffect(() => {
    if (serverMode) return
    seqRef.current += 1
    const first = (items || []).filter((g) => !deletedRef.current.has(g.id))
    const same = listKeyRef.current === qKey
    listKeyRef.current = qKey
    setList((prev) => (same ? mergeFirstPage(first, prev, deletedRef.current) : first))
    if (!same) setSelected(new Set())
    const t = Number.isFinite(items?.total) ? items.total : null
    setTotal(t)
    setHasMore(t != null ? t > first.length : (items?.length || 0) >= PAGE)
    setLoading(false)
  }, [items, serverMode, qKey])

  // Filtre varken sunucudan çek; App yeniden yüklediğinde (items değişince) tazele.
  useEffect(() => {
    if (!serverMode) return
    const my = ++seqRef.current
    const same = listKeyRef.current === qKey
    if (!same) { setLoading(true); setList([]); setSelected(new Set()) }
    api.generations({ limit: PAGE, offset: 0, ...query })
      .then((raw) => {
        if (my !== seqRef.current) return
        const first = raw.filter((g) => !deletedRef.current.has(g.id) && matches(g, crit))
        listKeyRef.current = qKey
        setList((prev) => (same ? mergeFirstPage(first, prev, deletedRef.current) : first))
        const t = Number.isFinite(raw.total) ? raw.total : null
        setTotal(t)
        setHasMore(raw.length >= PAGE && (t == null || first.length < t))
      })
      .catch((err) => { if (my === seqRef.current) notify?.(err.message, 'error') })
      .finally(() => { if (my === seqRef.current) setLoading(false) })
  }, [serverMode, qKey, items]) // eslint-disable-line react-hooks/exhaustive-deps

  // "/" ile aramaya odaklan
  useEffect(() => {
    function onKey(e) {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
      const t = e.target
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
      e.preventDefault()
      searchRef.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  async function loadMore() {
    if (loadingMore) return
    setLoadingMore(true)
    const my = seqRef.current
    try {
      const raw = await api.generations({ limit: PAGE, offset: list.length, ...query })
      if (my !== seqRef.current) return
      const have = new Set(list.map((g) => g.id))
      const add = raw.filter((g) => !have.has(g.id) && !deletedRef.current.has(g.id) && matches(g, crit))
      setList((prev) => {
        const ids = new Set(prev.map((g) => g.id))
        return [...prev, ...add.filter((g) => !ids.has(g.id))]
      })
      const t = Number.isFinite(raw.total) ? raw.total : total
      if (Number.isFinite(raw.total)) setTotal(raw.total)
      setHasMore(add.length > 0 && raw.length >= PAGE && (t == null || list.length + add.length < t))
    } catch (err) {
      notify?.(err.message, 'error')
    } finally {
      setLoadingMore(false)
    }
  }

  const refresh = () => { Promise.resolve(reload?.()).catch(() => {}) }

  function patchItem(id, patch) {
    setList((prev) => prev.map((g) => (g.id === id ? { ...g, ...patch } : g)))
  }

  async function toggleFav(g) {
    const next = !isFav(g)
    patchItem(g.id, { favorite: next })
    try {
      await api.favorite(g.id, next)
      refresh()
    } catch (err) {
      patchItem(g.id, { favorite: !next })
      notify?.(err.message, 'error')
    }
  }

  function forget(ids) {
    for (const id of ids) deletedRef.current.add(id)
    setList((prev) => prev.filter((g) => !deletedRef.current.has(g.id)))
    setSelected((prev) => {
      const n = new Set(prev)
      for (const id of ids) n.delete(id)
      return n
    })
    setTotal((t) => (t == null ? t : Math.max(0, t - ids.length)))
  }

  async function removeOne(g) {
    if (!confirm('Bu kayıt kalıcı olarak silinsin mi?')) return
    try {
      await api.deleteGeneration(g.id)
      forget([g.id])
      refresh()
    } catch (err) {
      notify?.(err.message, 'error')
    }
  }

  async function removeSelected() {
    const ids = [...selected]
    if (!ids.length) return
    if (!confirm(`${ids.length} kayıt kalıcı olarak silinsin mi?`)) return
    setBusy(true)
    const queue = [...ids]
    const done = []
    let failed = 0
    const worker = async () => {
      while (queue.length) {
        const id = queue.shift()
        try { await api.deleteGeneration(id); done.push(id) } catch { failed += 1 }
      }
    }
    await Promise.all(Array.from({ length: Math.min(4, ids.length) }, worker))
    forget(done)
    setBusy(false)
    if (failed) notify?.(`${done.length} kayıt silindi, ${failed} kayıt silinemedi.`, 'error')
    else notify?.(`${done.length} kayıt silindi.`)
    refresh()
  }

  function reuse(g) {
    const { chunks, normalized_text, variants, ...rest } = g.params || {} // eslint-disable-line no-unused-vars
    const params = {
      ...rest,
      voice_id: g.voice_id ?? rest.voice_id ?? null,
      language: g.language || rest.language || 'tr',
      seed: seedOf(g),
      format: rest.format || extOf(g),
    }
    const payload = { text: g.text || '', params }
    try { localStorage.setItem(REUSE_KEY, JSON.stringify(payload)) } catch {}
    try { window.dispatchEvent(new CustomEvent('sesklon:reuse', { detail: payload })) } catch {}
    notify?.('Metin ve ayarlar Seslendir sekmesine kopyalandı.')
    onReuse?.(payload)
  }

  // Varyant grupları: aynı group_id'li üretimler tek kartta.
  const groups = useMemo(() => {
    const out = []
    const byGroup = new Map()
    for (const g of list) {
      const gid = groupIdOf(g)
      if (gid) {
        let grp = byGroup.get(gid)
        if (!grp) {
          grp = { key: `grup:${gid}`, items: [] }
          byGroup.set(gid, grp)
          out.push(grp)
        }
        grp.items.push(g)
      } else out.push({ key: g.id, items: [g] })
    }
    for (const grp of out) if (grp.items.length > 1) grp.items.sort(variantOrder)
    return out
  }, [list])

  const voiceOptions = useMemo(() => {
    const m = seenVoicesRef.current
    for (const v of voices || []) if (v?.id) m.set(v.id, v.name || v.id)
    for (const g of list) if (g.voice_id && !m.has(g.voice_id)) m.set(g.voice_id, g.voice_name || g.voice_id)
    return [...m].sort((a, b) => String(a[1]).localeCompare(String(b[1]), 'tr'))
  }, [voices, list])

  const styleLabel = useMemo(() => {
    const m = {}
    for (const s of styles || []) if (s?.name) m[s.name] = s.label || s.name
    return m
  }, [styles])

  const allIds = useMemo(() => list.map((g) => g.id), [list])
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id))

  function toggleGroupSelect(grp) {
    const ids = grp.items.map((g) => g.id)
    setSelected((prev) => {
      const n = new Set(prev)
      const on = ids.every((id) => n.has(id))
      for (const id of ids) (on ? n.delete(id) : n.add(id))
      return n
    })
  }

  function toggleExpand(key) {
    setExpanded((prev) => {
      const n = new Set(prev)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
  }

  function clearFilters() {
    setQ('')
    setFilter('all')
    setVoiceId('')
  }

  const count = total ?? list.length
  const countLabel = total == null && hasMore ? `${list.length}+` : String(count)

  return (
    <section className="card history">
      <h2>Geçmiş <span className="count">{countLabel}</span></h2>

      <div className="toolbar">
        <input
          ref={searchRef}
          className="search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Metinde veya ses adında ara…  ( / )"
          aria-label="Geçmişte ara"
        />
        <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)} aria-label="Sese göre süz">
          <option value="">Tüm sesler</option>
          {voiceOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </div>

      <div className="row between">
        <div className="filter-chips" role="group" aria-label="Türe göre süz">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" aria-pressed={filter === f.id}
              className={`chip clickable${filter === f.id ? ' active' : ''}`} onClick={() => setFilter(f.id)}>
              {f.id === 'fav' ? '★ ' : ''}{f.label}
            </button>
          ))}
        </div>
        {list.length > 0 && (
          <label className="check small">
            <input type="checkbox" checked={allSelected}
              onChange={() => setSelected(allSelected ? new Set() : new Set(allIds))} />
            Tümünü seç
          </label>
        )}
      </div>

      {selected.size > 0 && (
        <div className="bulkbar" role="region" aria-label="Toplu işlemler">
          <strong>{selected.size} kayıt seçildi</strong>
          <div className="row">
            <button type="button" className="btn danger small" onClick={removeSelected} disabled={busy}>
              {busy ? 'Siliniyor…' : 'Seçilenleri sil'}
            </button>
            <button type="button" className="btn ghost small" onClick={() => setSelected(new Set())} disabled={busy}>Seçimi kaldır</button>
          </div>
        </div>
      )}

      {loading && list.length === 0 ? (
        <div className="stack" aria-busy="true" aria-label="Yükleniyor">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton card" />)}
        </div>
      ) : groups.length === 0 ? (
        isFiltered ? (
          <div className="empty">
            <strong>Bu filtrelerle eşleşen kayıt yok.</strong>
            <span className="small">Arama sözcüğünü değiştirin ya da filtreleri temizleyin.</span>
            <button type="button" className="btn ghost small" onClick={clearFilters}>Filtreleri temizle</button>
          </div>
        ) : (
          <div className="empty">
            <strong>Henüz üretim yok.</strong>
            <span className="small">"Seslendir" sekmesinde ürettiğiniz sesler burada listelenir.</span>
          </div>
        )
      ) : (
        <ul className="list">
          {groups.map((grp) => {
            const n = grp.items.length
            const idx = Math.min(activeIdx[grp.key] || 0, n - 1)
            const g = grp.items[idx]
            const ids = grp.items.map((x) => x.id)
            const isSel = ids.every((id) => selected.has(id))
            const open = expanded.has(grp.key)
            const fav = isFav(g)
            const seed = seedOf(g)
            const style = g.params?.style
            const emotion = g.params?.emotion
            const fx = g.params?.emotion_fx
            const meta = [
              fmtDate(g.created_at),
              languages[g.language] || g.language || '',
              fmtDur(g.duration),
              g.params?.chunks?.length ? `${g.params.chunks.length} parça` : '',
              Number.isFinite(g.elapsed) ? `${g.elapsed.toFixed(1)} sn'de üretildi` : '',
            ].filter(Boolean).join(' • ')
            return (
              <li key={grp.key} className={`item history-item${isSel ? ' selected' : ''}`}>
                <div className="item-head">
                  <div className="history-title">
                    <input type="checkbox" className="item-select" checked={isSel} onChange={() => toggleGroupSelect(grp)}
                      aria-label={n > 1 ? `${n} varyantı seç` : 'Kaydı seç'} />
                    <div>
                      <span className={`tag ${g.kind}`}>{g.kind === 'vc' ? 'Ses → Ses' : 'Metin → Ses'}</span>
                      <strong> {g.voice_name || 'Varsayılan ses'}</strong>
                      {n > 1 && <span className="count">{n} varyant</span>}
                      <div className="muted small">{meta}</div>
                    </div>
                  </div>
                  <div className="actions">
                    <button type="button" className={`star${fav ? ' on' : ''}`} onClick={() => toggleFav(g)} aria-pressed={fav}
                      aria-label={fav ? 'Favorilerden çıkar' : 'Favorilere ekle'} title={fav ? 'Favorilerden çıkar' : 'Favorilere ekle'}>
                      {fav ? '★' : '☆'}
                    </button>
                    {g.kind !== 'vc' && g.text && (
                      <button type="button" className="btn ghost small" onClick={() => reuse(g)} title="Metni ve ayarları Seslendir sekmesine kopyala">
                        Ayarları Seslendir sekmesine kopyala
                      </button>
                    )}
                    <button type="button" className="btn ghost small danger-text" onClick={() => removeOne(g)} disabled={busy}>
                      {n > 1 ? 'Varyantı sil' : 'Sil'}
                    </button>
                  </div>
                </div>

                {(style || emotion || seed != null || (fx && fx !== 'off')) && (
                  <div className="badges">
                    {style && <span className="badge accent" title="Stil ön ayarı">Stil: {styleLabel[style] || style}</span>}
                    {emotion && <span className="badge info" title="Genel duygu">Duygu: {emotion}</span>}
                    {seed != null && <span className="badge" title="Tohum: aynı ayarlarla aynı sonucu verir">Tohum: {seed}</span>}
                    {fx && fx !== 'off' && <span className="badge warn" title="Ses işleme seviyesi">Ses işleme: {FX_LABEL[fx] || fx}</span>}
                  </div>
                )}

                {n > 1 && (
                  <div className="variant-tabs" role="tablist" aria-label="Varyantlar">
                    {grp.items.map((v, i) => (
                      <button key={v.id} type="button" role="tab" aria-selected={i === idx} className={i === idx ? 'active' : ''}
                        onClick={() => setActiveIdx((m) => ({ ...m, [grp.key]: i }))}
                        title={`Varyant ${LETTERS[i] || i + 1}${seedOf(v) != null ? ` • tohum ${seedOf(v)}` : ''}`}>
                        {LETTERS[i] || i + 1}{isFav(v) ? ' ★' : ''}
                      </button>
                    ))}
                  </div>
                )}

                {g.text && (
                  <div className="history-text">
                    <p className="quote small">{open || g.text.length <= CLIP ? g.text : `${g.text.slice(0, CLIP).trimEnd()}…`}</p>
                    {g.text.length > CLIP && (
                      <button type="button" className="linklike small" onClick={() => toggleExpand(grp.key)} aria-expanded={open}>
                        {open ? 'Daralt' : 'Tamamını göster'}
                      </button>
                    )}
                  </div>
                )}

                <Player
                  key={g.id}
                  src={g.url}
                  downloadName={`sesklon-${g.id}.${extOf(g)}`}
                  title={n > 1 ? `Varyant ${LETTERS[idx] || idx + 1}` : undefined}
                />
              </li>
            )
          })}
        </ul>
      )}

      {hasMore && groups.length > 0 && (
        <div className="load-more">
          <button type="button" className="btn ghost" onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? 'Yükleniyor…' : 'Daha fazla yükle'}
          </button>
        </div>
      )}
    </section>
  )
}
