import { useCallback, useRef, useState } from 'react'
import { api } from '../api'

/**
 * Referans kaydı analiz kartı — şema: docs/SOZLESME.md §4.
 *   <AnalysisCard analysis={a} compact={bool} loading={bool} onAnalyze={fn} title="…" />
 * compact: yalnızca puan halkası + derece + ilk 2 sorun. analysis null → "Analiz yok" (+ onAnalyze varsa düğme).
 * Ayrıca: QualityBadge (★ 84), ScoreRing, useFileAnalysis (dosya seçilince otomatik analiz) ve Türkçe biçimlendiriciler.
 */

/* ---------- biçimlendirme ---------- */

const numberFormats = {}

/** Türkçe sayı: 5.1 → "5,1" (null/geçersiz → "–") */
export function fmtNum(value, digits = 1) {
  const n = Number(value)
  if (value == null || !Number.isFinite(n)) return '–'
  const f = numberFormats[digits] || (numberFormats[digits] = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: digits }))
  return f.format(n)
}

/** Oran → Türkçe yüzde: 0.82 → "%82" */
export const fmtPct = (ratio, digits = 0) => `%${fmtNum(Number(ratio) * 100, digits)}`

/** Saniye → "12,3 sn" ya da "2 dk 5 sn" */
export function fmtSn(seconds) {
  const n = Number(seconds)
  if (seconds == null || !Number.isFinite(n)) return ''
  if (n < 59.95) return `${fmtNum(n, 1)} sn`
  const total = Math.round(n)
  const m = Math.floor(total / 60)
  const s = total % 60
  return s ? `${m} dk ${s} sn` : `${m} dk`
}

export const trLower = (s) => String(s ?? '').toLocaleLowerCase('tr-TR')

/** İlk harfi Türkçe kurala göre büyütür: "iyi" → "İyi" */
export const capTr = (s) => (s ? String(s).charAt(0).toLocaleUpperCase('tr-TR') + String(s).slice(1) : '')

/* ---------- puan ve sorunlar ---------- */

const TIERS = [
  { min: 85, grade: 'mükemmel', color: '#22c55e', note: 'Klonlama için çok uygun.' },
  { min: 70, grade: 'iyi', color: '#84cc16', note: 'Kullanılabilir; küçük iyileştirmeler sonucu güzelleştirir.' },
  { min: 50, grade: 'orta', color: '#f97316', note: 'Sonuç etkilenebilir; önerilere göz atın.' },
  { min: -Infinity, grade: 'zayıf', color: '#ef4444', note: 'Yeniden kaydetmeniz önerilir.' },
]

/** Puana göre derece/renk: ≥85 yeşil, ≥70 açık yeşil, ≥50 turuncu, <50 kırmızı. */
export function scoreTier(score) {
  const s = Number(score)
  return TIERS.find((t) => s >= t.min) || TIERS[TIERS.length - 1]
}

/** Analiz "zayıf" mı? (sunucunun grade'i öncelikli, yoksa puan < 50) */
export function isPoor(a) {
  if (!a) return false
  if (a.grade) return trLower(a.grade) === 'zayıf'
  const s = Number(a.quality_score)
  return Number.isFinite(s) && s < 50
}

// Renkler temaya duyarlı tasarım değişkenleri (yedek değerli): açık temada da doğru tonlar.
const SEVERITY = {
  error: { icon: '⛔', rank: 3, label: 'Hata', color: 'var(--err, #ef4444)' },
  warn: { icon: '⚠', rank: 2, label: 'Uyarı', color: 'var(--warn, #f59e0b)' },
  info: { icon: 'ℹ', rank: 1, label: 'Bilgi', color: 'var(--info, #38bdf8)' },
}
const rank = (sev) => SEVERITY[sev]?.rank || 0

/** Sorunları önem sırasına dizer (error → warn → info; eşitlerde sunucu sırası korunur). */
export function sortedIssues(issues) {
  return (Array.isArray(issues) ? issues : []).filter(Boolean).sort((a, b) => rank(b.severity) - rank(a.severity))
}

/** Yanıt {analysis: {...}} biçiminde sarılı gelirse içini çıkarır. */
export function pickAnalysis(res) {
  if (res && typeof res === 'object' && !('quality_score' in res) && res.analysis && typeof res.analysis === 'object') {
    return res.analysis
  }
  return res || null
}

/* ---------- otomatik analiz kancası ---------- */

/**
 * Dosya seçilince/kayıt bitince api.analyze(file) çağırır; eski isteklerin geç gelen yanıtlarını yok sayar.
 * Dönüş: { analysis, analyzing, error, run(file), reset() }
 */
export function useFileAnalysis({ enabled = true, notify } = {}) {
  const [state, setState] = useState({ analysis: null, analyzing: false, error: '' })
  const seq = useRef(0)
  const notifyRef = useRef(notify)
  notifyRef.current = notify

  const run = useCallback(async (file) => {
    const id = ++seq.current
    if (!file || !enabled) {
      setState({ analysis: null, analyzing: false, error: '' })
      return null
    }
    setState({ analysis: null, analyzing: true, error: '' })
    try {
      const a = pickAnalysis(await api.analyze(file))
      if (id === seq.current) setState({ analysis: a, analyzing: false, error: '' })
      return a
    } catch (err) {
      if (id === seq.current) {
        setState({ analysis: null, analyzing: false, error: err.message })
        notifyRef.current?.('Kayıt incelenemedi: ' + err.message, 'warn')
      }
      return null
    }
  }, [enabled])

  const reset = useCallback(() => {
    seq.current++
    setState({ analysis: null, analyzing: false, error: '' })
  }, [])

  return { ...state, run, reset }
}

/* ---------- alt bileşenler ---------- */

/** Puan halkası (SVG). Voices "Kaydı iyileştir" önce/sonra karşılaştırmasında da kullanılır. */
export function ScoreRing({ score, color, size = 64, stroke = 6 }) {
  const pct = Math.max(0, Math.min(100, Number(score) || 0))
  const c = size / 2
  const r = (size - stroke) / 2
  const len = 2 * Math.PI * r
  return (
    <svg className="score-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={`Kalite puanı ${Math.round(pct)}/100`}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth={stroke} />
      <circle className="score-ring-value" cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={stroke}
        strokeLinecap={pct > 0 ? 'round' : 'butt'} strokeDasharray={len} strokeDashoffset={len * (1 - pct / 100)}
        transform={`rotate(-90 ${c} ${c})`} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fill="currentColor"
        fontSize={Math.round(size * 0.3)} fontWeight="700">{Math.round(pct)}</text>
    </svg>
  )
}

/** Renkli kalite rozeti: ★ 84 (puan yoksa hiçbir şey çizmez). */
export function QualityBadge({ score, small = false, title }) {
  const s = Number(score)
  if (score == null || !Number.isFinite(s)) return null
  const t = scoreTier(s)
  return (
    <span className={`chip qbadge${small ? ' small' : ''}`}
      style={{ borderColor: t.color, background: `${t.color}22`, color: 'var(--text)' }}
      title={title || `Kalite puanı ${Math.round(s)}/100 — ${t.grade}`}>
      <span style={{ color: t.color }} aria-hidden="true">★</span> {Math.round(s)}
    </span>
  )
}

/** Her ölçümün tonunu ilgili sorun kodundan alır; böylece rozetler sunucunun değerlendirmesiyle tutarlı kalır. */
const METRIC_ISSUES = {
  duration: ['too_short', 'too_long'],
  snr: ['noisy', 'music_or_multi'],
  speech: ['low_speech_ratio'],
  f0: ['monotone'],
  rate: ['too_fast', 'too_slow'],
  bandwidth: ['low_bandwidth'],
  reverb: ['reverb'],
  clipping: ['clipping'],
}

function buildMetrics(a) {
  const m = []
  // Konuşma bulunamadıysa perde/hız/duraklama/yankı/bant ölçümleri anlamsızdır (sunucu varsayılan değer döndürür).
  const noSpeech = a.speech_ratio != null && Number(a.speech_ratio) <= 0
  if (a.duration != null) {
    m.push({ key: 'duration', text: `Süre ${fmtSn(a.duration)}`, title: 'Kaydın süresi. Klonlama için ideali 8–15 sn.' })
  }
  if (a.snr_db != null) {
    m.push({ key: 'snr', text: `Sinyal/gürültü ${fmtNum(a.snr_db, 0)} dB`,
      title: 'Konuşmanın arka plan gürültüsünden ne kadar güçlü olduğu. 30 dB üstü çok iyi, 20 dB altı gürültülü sayılır.' })
  }
  if (a.speech_ratio != null) {
    m.push({ key: 'speech', text: `Konuşma ${fmtPct(a.speech_ratio)}`,
      title: 'Kaydın ne kadarının konuşma olduğu. Uzun sessizlikler ve müzik bu oranı düşürür.' })
  }
  if (noSpeech) {
    if (Number(a.clipping_ratio) > 0) m.push(clippingMetric(a))
    return m
  }
  const f0 = a.f0 || {}
  if (f0.median_hz) {
    const who = f0.label && f0.label !== 'belirsiz' ? ` · ${f0.label}` : ''
    const range = f0.min_hz && f0.max_hz ? ` Aralık ${fmtNum(f0.min_hz, 0)}–${fmtNum(f0.max_hz, 0)} Hz` : ''
    const semis = f0.range_semitones != null ? ` (${fmtNum(f0.range_semitones, 1)} yarım ton)` : ''
    m.push({ key: 'f0', text: `Perde ${fmtNum(f0.median_hz, 0)} Hz${who}`,
      title: `Ortanca ses perdesi (temel frekans).${range}${semis}. Dar aralık tekdüze bir anlatım demektir.` })
  }
  const rate = a.speaking_rate || {}
  const sps = Number(rate.syllables_per_sec)
  if (sps > 0 || (rate.syllables_per_sec == null && rate.label)) {
    m.push({ key: 'rate', text: `Hız: ${rate.label || '–'}${sps > 0 ? ` · ${fmtNum(sps, 1)} hece/sn` : ''}`,
      title: 'Konuşma hızı. Türkçede doğal aralık yaklaşık 4–6 hece/sn.' })
  }
  const p = a.pauses
  if (p && (p.count != null || p.mean_ms != null)) {
    const text = p.count === 0
      ? 'Duraklama yok'
      : `Duraklama ${p.mean_ms != null ? `${fmtNum(p.mean_ms, 0)} ms` : '–'}${p.scale != null ? ` · doğal ritim ×${fmtNum(p.scale, 2)}` : ''}`
    m.push({ key: 'pauses', text,
      title: 'Cümleler arası ortalama duraklama. Üretimde duraklamalar bu çarpanla kişinin kendi ritmine uyarlanır.' })
  }
  if (a.bandwidth_hz) {
    m.push({ key: 'bandwidth', text: `Bant ${fmtNum(a.bandwidth_hz / 1000, 1)} kHz`,
      title: 'Kayıttaki en yüksek anlamlı frekans. 7 kHz altı, telefon ya da sıkıştırılmış ses gibi boğuk duyulabilir.' })
  }
  if (a.reverb) {
    m.push({ key: 'reverb', text: `Yankı: ${a.reverb}`,
      title: 'Oda yankısı. Yüksek yankı, klonun uzaktan ve boğuk duyulmasına yol açar.' })
  }
  if (Number(a.clipping_ratio) > 0) m.push(clippingMetric(a))
  return m
}

function clippingMetric(a) {
  return {
    key: 'clipping', text: `Kırpılma ${fmtPct(a.clipping_ratio, 2)}`, tone: 'error',
    title: 'Seviyenin tavana vurduğu örneklerin oranı; cızırtıya yol açar. Mikrofondan biraz uzaklaşın ya da kazancı düşürün.',
  }
}

function metricTone(metric, issues) {
  let best = metric.tone || null
  for (const i of issues) {
    if (METRIC_ISSUES[metric.key]?.includes(i.code) && rank(i.severity) > rank(best)) best = i.severity
  }
  return best
}

function MetricChips({ analysis, issues }) {
  const metrics = buildMetrics(analysis)
  if (!metrics.length) return null
  return (
    <div className="presets">
      {metrics.map((m) => {
        const tone = metricTone(m, issues)
        const flagged = tone === 'error' || tone === 'warn'
        const toneStyle = flagged ? { color: SEVERITY[tone].color, borderColor: SEVERITY[tone].color } : undefined
        return (
          <span key={m.key} className={`chip metric${tone === 'error' ? ' bad' : tone === 'warn' ? ' warn' : ''}`}
            style={toneStyle} title={m.title}>
            {flagged ? `${SEVERITY[tone].icon} ` : ''}{m.text}
          </span>
        )
      })}
    </div>
  )
}

function IssueList({ issues }) {
  return (
    <ul className="issues">
      {issues.map((issue, k) => {
        const sev = SEVERITY[issue.severity] ? issue.severity : 'info'
        return (
          <li key={`${issue.code || 'sorun'}-${k}`} className={`issue ${sev}`}>
            <span className="ico" role="img" aria-label={SEVERITY[sev].label} style={{ color: SEVERITY[sev].color }}>
              {SEVERITY[sev].icon}
            </span>
            <span>{issue.message || issue.code}</span>
          </li>
        )
      })}
    </ul>
  )
}

function TipList({ tips }) {
  return (
    <div className="tips">
      <div className="muted small">Öneriler</div>
      <ul>{tips.map((t, k) => <li key={k}>{t}</li>)}</ul>
    </div>
  )
}

/* ---------- kart ---------- */

export default function AnalysisCard({ analysis, compact = false, loading = false, onAnalyze, title }) {
  if (loading) {
    return (
      <div className="analysis loading muted small" role="status">
        <span className="spinner" aria-hidden="true" /> Kayıt inceleniyor…
      </div>
    )
  }
  if (!analysis) {
    return (
      <div className="analysis empty row">
        <span className="muted small">Analiz yok</span>
        {onAnalyze && <button type="button" className="btn ghost small" onClick={onAnalyze}>Analiz et</button>}
      </div>
    )
  }

  const score = Number(analysis.quality_score)
  const hasScore = analysis.quality_score != null && Number.isFinite(score)
  const tier = hasScore ? scoreTier(score) : null
  const grade = analysis.grade || tier?.grade || ''
  const issues = sortedIssues(analysis.issues)
  const tips = (Array.isArray(analysis.tips) ? analysis.tips : []).filter(Boolean)
  const shown = compact ? issues.slice(0, 2) : issues

  return (
    <div className={`analysis stack${compact ? ' compact' : ''}`} role="group" aria-label={title || 'Kayıt analizi'}>
      <div className="analysis-head row">
        {hasScore && <ScoreRing score={score} color={tier.color} size={compact ? 44 : 64} stroke={compact ? 5 : 6} />}
        <div className="analysis-grade">
          {title && <div className="muted small">{title}</div>}
          <strong>{capTr(grade) || 'Puan yok'}</strong>
          {hasScore && <span className="muted small"> · {Math.round(score)}/100</span>}
          {!compact && tier && <div className="muted small">{tier.note}</div>}
        </div>
      </div>

      {!compact && <MetricChips analysis={analysis} issues={issues} />}

      {shown.length > 0
        ? <IssueList issues={shown} />
        : <div><span className="chip on small">✓ Belirgin bir sorun yok</span></div>}
      {compact && issues.length > shown.length && (
        <div className="muted small">+{issues.length - shown.length} uyarı daha</div>
      )}

      {!compact && tips.length > 0 && <TipList tips={tips} />}
    </div>
  )
}
