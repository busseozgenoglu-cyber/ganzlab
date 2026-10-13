import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { useRecorder } from '../useRecorder'
import Player from './Player'
import AnalysisCard, {
  QualityBadge, ScoreRing, capTr, fmtNum, fmtSn, isPoor, pickAnalysis, scoreTier, sortedIssues, trLower, useFileAnalysis,
} from './AnalysisCard'

/* ---------- okuma metinleri ---------- */

/**
 * Temel (nötr) kayıt için okuma metinleri: ~12 sn, kişinin doğal tonu.
 * Fonetik denge: ç ş ğ ö ü ı ve r/l yoğun; c, j, v, f, p, z, h gibi ünsüzler de metinlere dağıtıldı.
 */
const BASE_SCRIPTS = [
  {
    id: 'sohbet', label: 'Sohbet', hint: 'Günlük, rahat bir konuşma gibi',
    text: 'Geçen pazar eski bir arkadaşımla çay içtik. Çocukluğumuzu, okul yıllarını, bahçedeki koca ceviz ağacını konuştuk. Gülüşmeler, şakalar derken saatler nasıl geçti, hiç anlamadım; doğrusu onu çok özlemişim.',
  },
  {
    id: 'anlatim', label: 'Anlatım', hint: 'Hikâye anlatır gibi, akıcı',
    text: 'Küçük bir sahil kasabasında yaşlı bir balıkçı yaşarmış. Her sabah güneş doğmadan kayığını denize iter, rüzgârı dinlermiş. Bir gün ağına öyle parlak bir taş takılmış ki, bütün köy şaşkınlıkla ona bakakalmış.',
  },
  {
    id: 'haber', label: 'Haber', hint: 'Net, tane tane ve akıcı',
    text: 'İstanbul’da sabah başlayan yağmur, öğleden sonra yerini güneşli bir havaya bıraktı. Meteoroloji uzmanları, hafta sonu boyunca hava sıcaklığının mevsim normallerinin üzerinde seyredeceğini açıkladı.',
  },
]

/** Duygu kayıtları için okuma metinleri (~8–12 sn). Anahtar = duygu adı; bulunamazsa takma adlar denenir. */
const SAMPLE_SCRIPTS = {
  'heyecanlı': 'Vay be, bu gerçekten inanılmaz! Bugün size bomba gibi bir şey göstereceğim, hazır olun! İlk gördüğümde yerimde duramadım, siz de bayılacaksınız!',
  'mutlu': 'Bugün çok güzel bir gün, her şey yolunda gidiyor ve ben bundan gerçekten keyif alıyorum. Güneşli bir sabah, sıcacık bir kahve ve sevdiğim insanlar; daha ne isteyebilirim ki?',
  'sakin': 'Şimdi derin bir nefes al. Acele etmeye gerek yok, her şey sırasıyla olacak. Omuzlarını gevşet, gözlerini yavaşça kapat ve sadece sesimi dinle.',
  'ciddi': 'Bu konu gerçekten önemli. Lütfen söyleyeceklerimi dikkatle dinleyin. Vereceğimiz karar önümüzdeki yılları doğrudan etkileyecek; hata yapma lüksümüz yok.',
  'üzgün': 'Keşke her şey farklı olsaydı. Bunu söylemek bana çok zor geliyor, maalesef. Birlikte geçirdiğimiz o güzel günler hâlâ aklımdan çıkmıyor.',
  'kızgın': 'Yeter artık! Bu kadarı da fazla, kabul edilemez, bıktım bunlardan! Kaç kere söyledim, kimse beni dinlemiyor! Bu iş böyle yürümez!',
  'şaşkın': 'Ne? Gerçekten mi? İnanamıyorum, bunu hiç beklemiyordum! Daha dün konuşmuştuk, nasıl olur? Şaka yapıyorsun, değil mi?',
  'korkmuş': 'Dur, bir ses duydun mu? Buradan hemen çıkmamız lazım, lütfen acele et. Kapı kendi kendine açıldı… Işıkları kim kapattı?',
  'fısıltı': 'Şşş, sessiz ol. Kimse duymasın, sana gizli bir şey söyleyeceğim. Yarın sabah erkenden buluşalım, ama sakın kimseye söyleme.',
  'vurgulu': 'Bunu asla unutmayın: en önemli şey, her gün biraz daha ilerlemektir. Küçük adımlar büyük sonuçlar doğurur. Vazgeçmek yok!',
  'samimi': 'Canım, bugün nasılsın? Seninle konuşmak gerçekten çok iyi geliyor. Hadi gel, bir çay koyayım da biraz dertleşelim; anlatacak o kadar çok şeyim var ki!',
  'sıkılmış': 'Of, yine mi aynı şey. Tamam, yapalım da bitsin artık. Saatlerdir aynı toplantıdayız ve kimse yeni bir şey söylemiyor zaten.',
  'alaycı': 'Tabii, kesinlikle. Harika bir fikir, hiç aklıma gelmezdi. Hele o son dakika planların yok mu, onlara bayılıyorum.',
  'nazik': 'Rica etsem, bir dakikanızı alabilir miyim? Size yardımcı olmaktan memnuniyet duyarım; acele etmeyin, ben buradayım. İlginiz için çok teşekkür ederim.',
  'gururlu': 'Başardık! Aylarca gece gündüz çalıştık ve sonunda hayalimizi gerçeğe dönüştürdük. Seninle gurur duyuyorum; hepimizle gurur duyuyorum.',
  'umutlu': 'Biliyorum, bugün zor bir gün. Ama yarın güneş yine doğacak ve her şey yoluna girecek. İnan bana, en güzel günlerimiz daha önümüzde.',
  'nostaljik': 'Ah, o eski yaz akşamları… Mahallede top oynar, annemin bizi çağırmasını beklerdik. Şimdi o sokaklardan geçerken hâlâ ıhlamur kokusu gelir burnuma.',
  'gergin': 'Sonuçlar birazdan açıklanacak. Ellerim titriyor, kalbim küt küt atıyor. Ya olmazsa? Hayır, hayır, öyle düşünmemeliyim.',
  'romantik': 'Seni ilk gördüğüm an, sanki zaman durdu. O gülüşün, o bakışların… Bu gece yıldızların altında sadece ikimiz olalım, olur mu?',
  'çocuksu': 'Anne bak, bak! Kocaman bir kelebek! Rengârenk kanatları var! Onu yakalayabilir miyim? Söz veriyorum, sonra hemen bırakacağım!',
  'otoriter': 'Herkes yerine geçsin. Toplantı tam saat dokuzda başlıyor ve kimse geç kalmayacak. Görevler belli; şimdi işinizin başına!',
}

/** Hazır metni olmayan duygular için: kullanıcı bunu o duygunun tonunda okur. */
const GENERIC_SCRIPT = 'Bugün sana kısa bir şey anlatmak istiyorum. Dün akşam eve dönerken eski bir dostuma rastladım; oturduk, uzun uzun konuştuk ve zamanın nasıl geçtiğini hiç anlamadık.'

const SKIP_EMOTIONS = new Set(['normal', 'hızlı', 'yavaş']) // nötr ve tempo etiketleri duygu kaydı almaz
const REF_MAX_SECONDS = 30
const REF_GOOD_SECONDS = 15
const SAMPLE_GOOD_SECONDS = 10
const LEVEL_COLORS = { ok: '#22c55e', hot: '#eab308', clip: '#ef4444' }
const COUNTDOWN_KEY = 'sesklon_countdown'

/* ---------- gerçek tepkiler (gülme, iç çekme…) ---------- */

const NV_MAX_SECONDS = 5 // sunucu en yüksek enerjili 3 sn'yi alır; 5 sn kayıt payı bırakır

/**
 * Sunucu health.tags.nonverbal_recordable göndermezse (features.nonverbal açıkken) kullanılan liste.
 * Anahtarlar sözleşmedeki NONVERBAL_KEYS ile aynıdır (docs/SOZLESME2.md §2).
 */
const NV_FALLBACK_SCRIPTS = {
  'gülme': 'Komik bir şey duymuş gibi doğal, içten bir gülüş (1–3 sn).',
  'kahkaha': 'Kendini bırak: gür, gerçek bir kahkaha at (2–3 sn).',
  'kıkırdama': 'Ağzın kapalı, kısa ve hafif bir kıkırdama (1–2 sn).',
  'iç çekme': 'Derin bir nefes al ve yorgun bir "hıııh" ile bırak (1–2 sn).',
  'hmm': 'Düşünüyormuş gibi uzatarak "hımmm" de (1–2 sn).',
  'of': 'Bıkkın, sıkılmış bir "offf" çek (1 sn).',
  'nefes verir': 'Rahatlamış gibi nefesini yavaşça dışarı ver (1 sn).',
  'öksürür': 'Kısa, doğal bir öksürük (1 sn).',
  'boğaz temizler': 'Konuşmaya başlamadan önceki gibi boğazını temizle: "ıhım" (1 sn).',
  'esner': 'Uykulu, uzun bir esneme (2–3 sn).',
  'ağlar': 'Hafif hıçkırıklı, kısa bir ağlama (2–3 sn).',
  'şaşırır': 'Şaşırmış gibi kısa bir nefes çek ya da "haa!" de (1 sn).',
  'hıh': 'Burnundan kısa, küçümseyen bir "hıh" (1 sn).',
  'mmm': 'Lezzetli bir şey tatmış gibi "mmm" de (1–2 sn).',
  'cık': 'Dilini damağına vurarak "cık" de — "hayır" anlamında (1 sn).',
}
const NV_GENERIC_SCRIPT = 'Bu tepkiyi doğal hâliyle, kısa ve net olarak kaydedin (1–3 sn); önünde ve arkasında uzun sessizlik bırakmayın.'

/** Ses örneğinin türü: "nonverbal" (gerçek tepki) ya da "emotion" (duygu kaydı). Eski sunucu "nv:" önekli döndürebilir. */
function sampleKind(s) {
  if (s?.kind === 'nonverbal' || s?.kind === 'emotion') return s.kind
  return typeof s?.emotion === 'string' && s.emotion.startsWith('nv:') ? 'nonverbal' : 'emotion'
}
const sampleKey = (s) => String(s?.emotion ?? '').replace(/^nv:/, '')

function countSamples(samples) {
  let emotion = 0
  let nonverbal = 0
  for (const s of samples || []) {
    if (sampleKind(s) === 'nonverbal') nonverbal++
    else emotion++
  }
  return { emotion, nonverbal }
}

function buildNvItems(raw, feature) {
  const list = (Array.isArray(raw) ? raw : [])
    .filter((x) => x && typeof x.key === 'string' && x.key.trim())
    .map((x) => ({
      key: x.key.trim(),
      label: typeof x.label === 'string' && x.label.trim() ? x.label.trim() : capTr(x.key.trim()),
      script: typeof x.script === 'string' && x.script.trim() ? x.script.trim() : NV_FALLBACK_SCRIPTS[x.key.trim()] || '',
    }))
  if (list.length) return list
  if (feature !== true) return []
  return Object.entries(NV_FALLBACK_SCRIPTS).map(([key, script]) => ({ key, label: capTr(key), script }))
}

/* ---------- kayıt iyileştirme ---------- */

const ENHANCE_MIN_GAIN = 3 // sunucu bu kadar puan kazanç yoksa uygulamaz (force ile uygulanır)
const ENHANCE_REASONS = { noisy: 'arka plan gürültüsü', hum: 'elektrik uğultusu', too_quiet: 'kısık kayıt', dc_offset: 'DC kayması' }

/** "Kaydı iyileştir" belirgin gösterilsin mi? Zayıf/orta kayıt ya da gürültü, uğultu, kısıklık, DC kayması varsa evet. */
function enhanceAdvice(a) {
  if (!a) return { recommend: false, reasons: [] }
  const codes = new Set(sortedIssues(a.issues).map((i) => i.code))
  const reasons = Object.keys(ENHANCE_REASONS).filter((c) => codes.has(c)).map((c) => ENHANCE_REASONS[c])
  const score = Number(a.quality_score)
  const grade = trLower(a.grade || (a.quality_score != null && Number.isFinite(score) ? scoreTier(score).grade : ''))
  const weak = grade === 'zayıf' || grade === 'orta'
  if (weak && !reasons.length) reasons.push(`kayıt kalitesi ${grade}`)
  return { recommend: weak || reasons.length > 0, reasons }
}

/** Sunucu raporundaki adım kodlarını Türkçe etikete çevirir (report.applied + ölçümler). */
function enhanceSteps(report) {
  const r = report && typeof report === 'object' ? report : {}
  const list = Array.isArray(r.applied) ? r.applied : []
  return list.map((code) => {
    switch (String(code)) {
      case 'denoise': {
        const db = Math.abs(Number(r.noise_reduction_db))
        return Number.isFinite(db) && db >= 0.5 ? `Gürültü azaltma (−${fmtNum(db, 0)} dB)` : 'Gürültü azaltma'
      }
      case 'dehum':
        return Number(r.hum_hz) > 0 ? `Elektrik uğultusu (${fmtNum(r.hum_hz, 0)} Hz)` : 'Elektrik uğultusu'
      case 'declick':
        return Number(r.clicks_removed) > 0 ? `Tık temizliği (${fmtNum(r.clicks_removed, 0)})` : 'Tık temizliği'
      case 'highpass':
        return 'Alçak frekans kesimi'
      case 'level':
      case 'gain': {
        const g = Number(r.gain_db)
        return Number.isFinite(g) && Math.abs(g) >= 0.5 ? `Seviye (${g > 0 ? '+' : '−'}${fmtNum(Math.abs(g), 0)} dB)` : 'Seviye'
      }
      case 'dc':
      case 'dc_offset':
        return 'DC kayması düzeltme'
      default:
        return String(code)
    }
  })
}

const scoreOf = (a) => {
  const n = Number(a?.quality_score)
  return a?.quality_score != null && Number.isFinite(n) ? n : null
}

/** Tarayıcı ve Player dalga formu önbelleği eski kaydı göstermesin diye adrese sürüm ekler. */
const withRev = (url, rev) => (url && rev ? `${url}${url.includes('?') ? '&' : '?'}v=${rev}` : url)

/* ---------- yardımcılar (Convert.jsx de kullanır) ---------- */

const TR_ASCII = { ç: 'c', Ç: 'C', ğ: 'g', Ğ: 'G', ı: 'i', İ: 'I', ö: 'o', Ö: 'O', ş: 's', Ş: 'S', ü: 'u', Ü: 'U' }

/** İndirme adı için Türkçe karakter güvenli ASCII ad: "Buse — doğal" → "Buse-dogal". */
export function safeFileName(name, fallback = 'ses') {
  const s = String(name ?? '')
    .replace(/[çÇğĞıİöÖşŞüÜ]/g, (ch) => TR_ASCII[ch])
    .normalize('NFKD').replace(/[̀-ͯ]/g, '') // â, î, û ve diğer aksanlar
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .slice(0, 80)
    .replace(/^[-.]+|[-.]+$/g, '')
  return s || fallback
}

/** Seçilen dosya için önizleme adresi (bileşen kapanınca/dosya değişince serbest bırakılır). */
export function useObjectUrl(file) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    if (!file) {
      setUrl(null)
      return undefined
    }
    const u = URL.createObjectURL(file)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [file])
  return url
}

function readCountdownPref() {
  try { return localStorage.getItem(COUNTDOWN_KEY) !== '0' } catch { return true }
}

function writeCountdownPref(on) {
  try { localStorage.setItem(COUNTDOWN_KEY, on ? '1' : '0') } catch { /* tercih saklanamazsa önemli değil */ }
}

function scriptFor(emotion) {
  if (!emotion) return null
  for (const key of [emotion.name, ...(emotion.aliases || [])]) {
    const s = SAMPLE_SCRIPTS[trLower(key)]
    if (s) return s
  }
  return null
}

function gradeText(a) {
  const score = Number(a?.quality_score)
  if (a?.quality_score == null || !Number.isFinite(score)) return ''
  return `${Math.round(score)}/100 (${a.grade || scoreTier(score).grade})`
}

function defaultVoiceName(name, file, fromMic) {
  const n = name.trim()
  if (n) return n
  if (fromMic) return `Mikrofon kaydı ${new Date().toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' })}`
  return (file?.name || 'Yeni ses').replace(/\.[^.]+$/, '').slice(0, 80)
}

function poorConfirmText(a) {
  const fixes = sortedIssues(a?.issues).filter((i) => i.severity !== 'info').map((i) => i.message).filter(Boolean)
  const list = (fixes.length ? fixes : (a?.tips || [])).slice(0, 6)
  const score = gradeText(a)
  return [
    `Kayıt kalitesi zayıf${score ? ` — ${score}` : ''}. Bu kayıttan klonlanan ses gürültülü ya da yapay duyulabilir.`,
    ...(list.length ? ['', 'Düzeltilmesi önerilenler:', ...list.map((m) => `• ${m}`)] : []),
    '',
    'Yine de kaydedilsin mi?',
  ].join('\n')
}

/* ---------- mikrofon kaydı ---------- */

function LevelMeter({ level, peak, hint }) {
  const state = peak > 0.9 ? 'clip' : peak > 0.7 || level > 0.85 ? 'hot' : 'ok'
  const pct = Math.round(Math.min(1, Math.max(0, level)) * 100)
  let message = ''
  if (hint) {
    if (state === 'clip') message = '⚠ Çok yüksek — kırpılma riski! Mikrofondan biraz uzaklaşın.'
    else if (state === 'hot') message = 'Seviye yüksek; biraz uzaklaşmak iyi olabilir.'
    else if (peak < 0.08) message = 'Ses çok kısık — mikrofona yaklaşın ya da biraz daha yüksek sesle konuşun.'
    else message = 'Seviye iyi.'
  }
  return (
    <div className="meter-wrap">
      <svg className="meter" width="100%" height="10" role="meter" aria-label="Mikrofon seviyesi"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <rect width="100%" height="10" rx="5" fill="currentColor" fillOpacity="0.14" />
        {pct > 0 && <rect width={`${pct}%`} height="10" rx="5" fill={LEVEL_COLORS[state]} />}
      </svg>
      {message && <div className={`small ${state === 'clip' ? 'danger-text' : state === 'hot' ? 'warn-text' : 'muted'}`}>{message}</div>}
    </div>
  )
}

function RecTimer({ seconds, maxSeconds, goodSeconds }) {
  const enough = goodSeconds > 0 && seconds >= goodSeconds
  const left = maxSeconds > 0 ? maxSeconds - seconds : null
  return (
    <div className="rec-timer small">
      <span className="rec-dot danger-text" aria-hidden="true">●</span> Kaydediliyor: <b>{seconds} sn</b>
      {maxSeconds > 0 && <span className="muted"> / {maxSeconds} sn</span>}
      {goodSeconds > 0 && (enough
        ? <> <span className="chip on">yeterli ✓</span><span className="muted"> dilediğiniz an durdurabilirsiniz</span></>
        : <span className="muted"> · en az {goodSeconds} sn önerilir</span>)}
      {left != null && left <= 5 && <span className="muted"> · {left} sn sonra otomatik durur</span>}
    </div>
  )
}

/**
 * Mikrofon kaydı: 3-2-1 geri sayım seçeneği, canlı seviye çubuğu, süre sayacı, goodSeconds'ta "yeterli ✓",
 * maxSeconds'ta otomatik durdurma. Kayıt bitince onFile(file, { seconds, auto }).
 */
export function Recorder({ onFile, label = '● Mikrofondan kaydet', maxSeconds = 0, goodSeconds = 0, disabled = false }) {
  const [withCountdown, setWithCountdown] = useState(readCountdownPref)
  const [notice, setNotice] = useState('')
  const rec = useRecorder({
    onFile: (file, info) => {
      setNotice(info?.auto ? `${maxSeconds} sn sınırına ulaşıldı; kayıt otomatik durduruldu.` : '')
      onFile?.(file, info)
    },
  })
  const counting = rec.countdown > 0
  const active = rec.recording || counting

  function toggle() {
    if (active) {
      rec.stop() // dosya onFile ile gelir
      return
    }
    setNotice('')
    rec.start({ countdown: withCountdown ? 3 : 0, maxSeconds })
  }

  function toggleCountdown(e) {
    setWithCountdown(e.target.checked)
    writeCountdownPref(e.target.checked)
  }

  if (!rec.supported) {
    return <div className="muted small">Bu tarayıcıda mikrofon kaydı kullanılamıyor (https ya da localhost gerekir); dosya yükleyebilirsiniz.</div>
  }

  return (
    <div className="recorder stack">
      <div className="row">
        <button type="button" className={`btn ${active ? 'danger' : 'secondary'}`} onClick={toggle} disabled={disabled && !active}>
          {counting ? '✕ Vazgeç' : rec.recording ? `■ Durdur (${rec.seconds} sn)` : label}
        </button>
        {rec.recording && (
          <button type="button" className="btn ghost small" onClick={rec.cancel} title="Bu kaydı atıp baştan başlayın">Kaydı at</button>
        )}
        {!active && (
          <label className="check small">
            <input type="checkbox" checked={withCountdown} onChange={toggleCountdown} /> 3-2-1 geri sayım
          </label>
        )}
      </div>
      {active && (
        <div className="rec-live stack">
          {counting && <div className="countdown" aria-live="assertive">Hazırlanın… <b>{rec.countdown}</b></div>}
          <LevelMeter level={rec.level} peak={rec.peak} hint={rec.recording && rec.seconds >= 1} />
          {rec.recording && <RecTimer seconds={rec.seconds} maxSeconds={maxSeconds} goodSeconds={goodSeconds} />}
        </div>
      )}
      {!active && notice && <div className="muted small">{notice}</div>}
      {rec.error && <div className="alert error">{rec.error}</div>}
    </div>
  )
}

/* ---------- yeni ses formu ---------- */

function ScriptPicker({ value, onChange }) {
  const current = BASE_SCRIPTS.find((s) => s.id === value) || BASE_SCRIPTS[0]
  return (
    <div className="script stack">
      <div className="row between">
        <span className="muted small">Okuma metni — kendi doğal tonunuzla, acele etmeden (~12 sn)</span>
        <div className="presets" role="radiogroup" aria-label="Okuma metni">
          {BASE_SCRIPTS.map((s) => (
            <button type="button" key={s.id} role="radio" aria-checked={s.id === current.id} title={s.hint}
              className={`chip clickable ${s.id === current.id ? 'active' : ''}`} onClick={() => onChange(s.id)}>
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <blockquote className="quote">{current.text}</blockquote>
    </div>
  )
}

function NewVoiceForm({ languages, analysisEnabled, refresh, notify, onCreated }) {
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('tr')
  const [file, setFile] = useState(null)
  const [fromMic, setFromMic] = useState(false)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [scriptId, setScriptId] = useState(BASE_SCRIPTS[0].id)
  const fileRef = useRef(null)
  const preview = useObjectUrl(file)
  const check = useFileAnalysis({ enabled: analysisEnabled, notify })
  const poor = isPoor(check.analysis)

  function pick(f, mic = false) {
    setFile(f)
    setFromMic(Boolean(mic && f))
    if (mic && fileRef.current) fileRef.current.value = ''
    check.run(f)
  }

  function clearFile() {
    setFile(null)
    setFromMic(false)
    check.reset()
    if (fileRef.current) fileRef.current.value = ''
  }

  async function submit(e) {
    e.preventDefault()
    if (busy) return
    if (!file) return notify('Önce bir ses dosyası seçin ya da mikrofondan kaydedin.', 'error')
    if (!consent) return notify('Bu sesi kullanma izniniz olduğunu onaylayın.', 'error')
    if (check.analyzing) return notify('Kayıt hâlâ inceleniyor; birkaç saniye bekleyin.', 'error')
    if (poor && !window.confirm(poorConfirmText(check.analysis))) return
    setBusy(true)
    try {
      const created = await api.createVoice({ name: defaultVoiceName(name, file, fromMic), language, file, consent })
      onCreated?.(created)
      setName('')
      setConsent(false)
      clearFile()
      const quality = gradeText(pickAnalysis(created?.analysis))
      if (await refresh()) notify(quality ? `Ses eklendi — kalite ${quality}.` : 'Ses eklendi.')
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>Yeni ses ekle</h2>
      <p className="muted">
        10–15 saniyelik, sessiz bir ortamda, doğal tonda bir konuşma. Kayıt seçildiği anda kalitesi incelenir;
        kaydedilirken kırpılır, sessizlikleri temizlenir ve seviyesi dengelenir.
      </p>
      <form onSubmit={submit} className="stack">
        <div className="row">
          <label className="grow">Ses adı
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="örn. Buse — doğal" maxLength={80} />
          </label>
          <label>Örneğin dili
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {Object.entries(languages).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>

        <ScriptPicker value={scriptId} onChange={setScriptId} />
        <Recorder onFile={(f) => pick(f, true)} maxSeconds={REF_MAX_SECONDS} goodSeconds={REF_GOOD_SECONDS} disabled={busy} />
        <label>…ya da dosya yükleyin (mp3, wav, m4a, ogg, webm, mp4…)
          <input ref={fileRef} type="file" accept="audio/*,video/*" onChange={(e) => pick(e.target.files?.[0] || null)} />
        </label>

        {file && (
          <div className="stack">
            <div className="row between">
              <span className="chip">Seçili: {file.name}{file.size ? ` (${Math.round(file.size / 1024)} KB)` : ''}</span>
              <button type="button" className="btn ghost small" onClick={clearFile} disabled={busy}>✕ Kaldır</button>
            </div>
            {preview && <Player src={preview} downloadName={file.name} compact title="Seçili kayıt" />}
            {analysisEnabled && (
              <AnalysisCard analysis={check.analysis} loading={check.analyzing} onAnalyze={() => check.run(file)} title="Kayıt kalitesi" />
            )}
            {poor && (
              <div className="alert warn">⚠ Bu kayıt zayıf görünüyor. Yukarıdaki önerilere göre yeniden kaydetmeniz önerilir; yine de kaydedebilirsiniz.</div>
            )}
          </div>
        )}

        <label className="check">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          Bu ses bana ait ya da sahibinden kullanım izni aldım.
        </label>
        <button className="btn primary" disabled={busy || check.analyzing}>
          {busy ? 'Yükleniyor…' : check.analyzing ? 'Kayıt inceleniyor…' : poor ? 'Yine de kaydet' : 'Sesi kaydet'}
        </button>
      </form>
    </section>
  )
}

/* ---------- kütüphane ---------- */

function LibraryHeader({ count, refresh, notify }) {
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)

  async function onImport(e) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    setBusy(true)
    try {
      const v = await api.importVoice(f)
      if (await refresh()) notify(v?.name ? `"${v.name}" içe aktarıldı.` : 'Ses içe aktarıldı.')
    } catch (err) {
      notify('İçe aktarılamadı: ' + err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="row between library-head">
      <h2>Ses kütüphanesi <span className="count">{count}</span></h2>
      <button type="button" className="btn ghost small" onClick={() => inputRef.current?.click()} disabled={busy}
        title="Daha önce alınmış bir ses yedeğini (zip) geri yükleyin">
        {busy ? 'İçe aktarılıyor…' : '⤒ İçe aktar (zip)'}
      </button>
      <input ref={inputRef} type="file" accept=".zip,application/zip,application/x-zip-compressed" hidden onChange={onImport} />
    </div>
  )
}

function EmptyGuide() {
  return (
    <div className="empty-guide stack">
      <p><strong>Henüz ses yok.</strong> <span className="muted">Üç adımda ilk sesinizi hazırlayın:</span></p>
      <ol className="steps">
        <li><b>Kaydet</b> — Soldaki okuma metnini mikrofondan 10–15 sn okuyun ya da hazır bir kayıt yükleyin.</li>
        <li><b>Analiz</b> — Kayıt anında incelenir; puan düşükse önerilere göre yeniden kaydedin.</li>
        <li><b>Üret</b> — "Seslendir" sekmesinde metninizi yazın, sesinizi seçin ve dinleyin.</li>
      </ol>
      <p className="muted small">Yedeğiniz varsa "İçe aktar (zip)" ile geri yükleyebilirsiniz.</p>
    </div>
  )
}

function CoverageBar({ done, total }) {
  const pct = total ? Math.round((done / total) * 100) : 0
  return (
    <div className="progress coverage" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}
      title={`${total} duygudan ${done} tanesinin kaydı var`}>
      <div className="bar" style={{ width: `${pct}%` }} />
      <div className="small">{done}/{total} duygu kaydı{total > 0 && done >= total ? ' — tamamlandı ✓' : ''}</div>
    </div>
  )
}

function VoiceSettings({ v, styles, refresh, notify }) {
  const [style, setStyle] = useState(v.default_style || '')
  const [note, setNote] = useState(v.notes || '')
  const editing = useRef(false)

  useEffect(() => { setStyle(v.default_style || '') }, [v.default_style])
  useEffect(() => { if (!editing.current) setNote(v.notes || '') }, [v.notes])

  const options = useMemo(() => {
    const list = styles.filter((s) => s?.name)
    return style && !list.some((s) => s.name === style) ? [...list, { name: style, label: style }] : list
  }, [styles, style])

  async function save(patch, message, revert) {
    try {
      await api.updateVoice(v.id, patch)
      if (await refresh()) notify(message)
    } catch (err) {
      revert?.()
      notify(err.message, 'error')
    }
  }

  function changeStyle(e) {
    const prev = style
    const next = e.target.value
    setStyle(next)
    const label = options.find((s) => s.name === next)?.label || next
    save({ default_style: next || null }, next ? `Varsayılan stil: ${label}.` : 'Varsayılan stil kaldırıldı.', () => setStyle(prev))
  }

  function blurNote() {
    editing.current = false
    const next = note.trim()
    if (next === (v.notes || '').trim()) return
    save({ notes: next }, 'Not kaydedildi.')
  }

  return (
    <div className="row voice-settings">
      {options.length > 0 && (
        <label className="inline small">Varsayılan stil
          <select value={style} onChange={changeStyle}>
            <option value="">Yok</option>
            {options.map((s) => <option key={s.name} value={s.name} title={s.description || ''}>{s.label || s.name}</option>)}
          </select>
        </label>
      )}
      <label className="grow small">Not
        <textarea rows={2} value={note} maxLength={500} placeholder="ör. stüdyo mikrofonu; reklam metinleri için"
          onFocus={() => { editing.current = true }} onChange={(e) => setNote(e.target.value)} onBlur={blurNote} />
      </label>
    </div>
  )
}

function EmotionSamples({ v, emotions, refresh, notify }) {
  // Yalnızca duygu kayıtları; gerçek tepkiler (kind: "nonverbal") ayrı bölümde ve kapsamaya sayılmaz.
  const samples = useMemo(() => (v.samples || []).filter((s) => sampleKind(s) === 'emotion'), [v.samples])
  const byEmotion = useMemo(() => new Map(samples.map((s) => [s.emotion, s])), [samples])
  const [sel, setSel] = useState(() => (emotions.find((e) => !byEmotion.has(e.name)) || emotions[0])?.name || '')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)

  // Duygu listesi sonradan gelirse ya da değişirse geçerli bir seçim yap (önce eksik olan).
  // Yalnızca liste değişince çalışır; kayıt eklenince seçimi add() yönetir.
  useEffect(() => {
    if (emotions.some((e) => e.name === sel)) return
    const first = emotions.find((e) => !byEmotion.has(e.name)) || emotions[0]
    setSel(first ? first.name : '')
  }, [emotions])

  const emo = emotions.find((e) => e.name === sel)
  const current = emo ? byEmotion.get(emo.name) : null
  const script = scriptFor(emo)
  const recorded = emotions.filter((e) => byEmotion.has(e.name)).length

  function clearInput() {
    if (fileRef.current) fileRef.current.value = ''
  }

  async function add() {
    if (!file || !emo) return notify('Önce kayıt yapın ya da dosya seçin.', 'error')
    setBusy(true)
    try {
      const updated = await api.addSample(v.id, emo.name, file)
      const saved = updated?.samples?.find((s) => s.emotion === emo.name)
      const a = pickAnalysis(saved?.analysis)
      setFile(null)
      clearInput()
      const quality = gradeText(a)
      const message = quality
        ? `"${emo.label}" kaydı eklendi — kalite ${quality}${isPoor(a) ? '; yeniden kaydetmeyi düşünün.' : '.'}`
        : `"${emo.label}" kaydı eklendi.`
      if (await refresh()) notify(message, isPoor(a) ? 'warn' : 'ok')
      if (!isPoor(a) && Array.isArray(updated?.samples)) {
        // Kayıt seansını hızlandır: sıradaki eksik duyguya geç.
        const have = new Set(updated.samples.map((s) => s.emotion))
        const next = emotions.find((e) => !have.has(e.name))
        if (next) setSel(next.name)
      }
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function removeSample(s) {
    if (!window.confirm(`"${s.emotion}" duygu kaydı silinsin mi?`)) return
    try {
      await api.deleteSample(v.id, s.emotion)
      if (await refresh()) notify(`"${s.emotion}" kaydı silindi.`)
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  return (
    <div className="samplebox stack">
      <div className="muted small">
        Her duygu için o tonda 8–15 sn kayıt ekleyin; metinde <b>[etiket]</b> kullanıldığında o kayıt referans alınır.
        Kaydı olmayan duygular yalnızca üretim ayarlarıyla verilir (daha zayıf).
      </div>

      {emotions.length > 0 ? (
        <>
          <CoverageBar done={recorded} total={emotions.length} />
          <div className="presets">
            {emotions.map((e) => {
              const s = byEmotion.get(e.name)
              const q = s?.analysis?.quality_score
              const title = s ? `Kayıtlı${q != null ? ` — kalite ${Math.round(q)}/100` : ''}. Yenilemek için seçin.` : 'Kayıt yok — seçip kaydedin.'
              return (
                <button type="button" key={e.name} title={title} onClick={() => setSel(e.name)}
                  className={`chip clickable ${s ? 'on' : ''} ${sel === e.name ? 'active' : ''}`}>
                  {s ? '✓ ' : '+ '}{e.label}
                </button>
              )
            })}
          </div>
        </>
      ) : (
        <div className="muted small">Duygu listesi yükleniyor…</div>
      )}

      {emo && (
        <div className="sample-editor stack">
          <div className="small">
            <b>{current ? `Kaydı yenile: ${emo.label}` : `+ Kaydet: ${emo.label}`}</b>
            <span className="muted"> — bu tonda, doğal konuşur gibi okuyun</span>
          </div>
          <blockquote className="quote">{script || GENERIC_SCRIPT}</blockquote>
          {!script && <div className="muted small">Bu duygu için hazır metin yok; yukarıdaki genel metni "{emo.label}" tonunda okuyun.</div>}
          <Recorder onFile={(f) => { setFile(f); clearInput(); notify('Kayıt alındı.') }} label="● Kaydet"
            maxSeconds={REF_MAX_SECONDS} goodSeconds={SAMPLE_GOOD_SECONDS} disabled={busy} />
          <div className="row">
            <label className="grow">…ya da dosya
              <input ref={fileRef} type="file" accept="audio/*,video/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <button type="button" className="btn primary" disabled={busy || !file} onClick={add}>
              {busy ? 'Yükleniyor…' : current ? `"${emo.label}" kaydını değiştir` : `"${emo.label}" olarak ekle`}
            </button>
          </div>
          {file && <div className="chip">Seçili: {file.name}</div>}
        </div>
      )}

      {samples.length > 0 && (
        <ul className="list" aria-label="Duygu kayıtları">
          {samples.map((s) => (
            <li key={s.id} className="item small">
              <div className="item-head">
                <span>
                  <span className="tag emo">{s.emotion}</span> <span className="muted">{fmtSn(s.duration)}</span>{' '}
                  <QualityBadge score={s.analysis?.quality_score} small />
                </span>
                <button type="button" className="btn ghost small danger-text" onClick={() => removeSample(s)}>Sil</button>
              </div>
              <Player src={s.url} downloadName={`${safeFileName(v.name)}-${safeFileName(s.emotion, 'duygu')}.wav`}
                compact title={`${v.name} — ${s.emotion}`} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Gerçek tepki kayıtları: metinde [gülme] yazıldığında modelin "Hahaha" okuması yerine bu kayıt çalınır.
 * items: [{ key, label, script }] (health.tags.nonverbal_recordable).
 */
function NonverbalSamples({ v, items, refresh, notify }) {
  const recorded = useMemo(() => {
    const m = new Map()
    for (const s of v.samples || []) if (sampleKind(s) === 'nonverbal') m.set(sampleKey(s), s)
    return m
  }, [v.samples])
  const [sel, setSel] = useState(() => (items.find((i) => !recorded.has(i.key)) || items[0])?.key || '')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)
  const preview = useObjectUrl(file)

  // Liste sonradan gelirse ya da değişirse geçerli bir seçim yap (önce kaydı olmayan).
  useEffect(() => {
    if (items.some((i) => i.key === sel)) return
    const first = items.find((i) => !recorded.has(i.key)) || items[0]
    setSel(first ? first.key : '')
  }, [items]) // eslint-disable-line react-hooks/exhaustive-deps

  const item = items.find((i) => i.key === sel) || null
  const current = item ? recorded.get(item.key) : null
  const labelOf = (key) => items.find((i) => i.key === key)?.label || capTr(key)
  // Kayıtlı tepkiler: önce sunucu listesindeki sırayla, listede olmayanlar sonda
  const list = useMemo(() => {
    const order = new Map(items.map((i, k) => [i.key, k]))
    return [...recorded.entries()].sort((a, b) => (order.get(a[0]) ?? 999) - (order.get(b[0]) ?? 999) || a[0].localeCompare(b[0], 'tr'))
  }, [recorded, items])

  function clearInput() {
    if (fileRef.current) fileRef.current.value = ''
  }

  async function add() {
    if (!file || !item) return notify('Önce kayıt yapın ya da dosya seçin.', 'error')
    setBusy(true)
    try {
      const updated = await api.addNonverbal(v.id, item.key, file)
      setFile(null)
      clearInput()
      if (await refresh()) notify(`"${item.label}" eklendi — metinde [${item.key}] yazınca bu kayıt çalınır.`)
      // Kayıt seansını hızlandır: sıradaki eksik tepkiye geç.
      const have = new Set(recorded.keys()).add(item.key)
      for (const s of Array.isArray(updated?.samples) ? updated.samples : []) if (sampleKind(s) === 'nonverbal') have.add(sampleKey(s))
      const next = items.find((i) => !have.has(i.key))
      if (next) setSel(next.key)
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function remove(key) {
    const label = labelOf(key)
    if (!window.confirm(`"${label}" tepki kaydı silinsin mi?`)) return
    try {
      await api.deleteNonverbal(v.id, key)
      if (await refresh()) notify(`"${label}" tepki kaydı silindi.`)
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  return (
    <div className="samplebox stack nv-samples">
      <div className="muted small">
        Metinde <b>[gülme]</b> yazdığında modelin "Hahaha" demesi yerine <b>SENİN</b> gülmen kullanılır.
        Her tepki için 1–3 sn yeterli (en fazla {NV_MAX_SECONDS} sn kaydedilir); sessizlik kırpılır, seviye dengelenir.
      </div>

      <div className="presets" role="group" aria-label="Kaydedilebilir tepkiler">
        {items.map((i) => {
          const s = recorded.get(i.key)
          const on = sel === i.key
          const title = s ? `Kayıtlı${s.duration ? ` (${fmtSn(s.duration)})` : ''}. Yenilemek için seçin.` : 'Kayıt yok — seçip kaydedin.'
          return (
            <button type="button" key={i.key} title={title} aria-pressed={on} onClick={() => setSel(i.key)}
              className={`chip clickable ${s ? 'on' : ''} ${on ? 'active' : ''}`}>
              {s ? '✓ ' : '+ '}{i.label}
            </button>
          )
        })}
      </div>

      {item && (
        <div className="sample-editor stack">
          <div className="small">
            <b>{current ? `Kaydı yenile: ${item.label}` : `+ Kaydet: ${item.label}`}</b>
            <span className="muted"> — metinde <code>[{item.key}]</code> yazınca çalınır</span>
          </div>
          <blockquote className="quote">{item.script || NV_GENERIC_SCRIPT}</blockquote>
          <Recorder onFile={(f) => { setFile(f); clearInput(); notify('Kayıt alındı — dinleyip ekleyebilirsin.') }} label="● Kaydet"
            maxSeconds={NV_MAX_SECONDS} disabled={busy} />
          <div className="row">
            <label className="grow">…ya da dosya
              <input ref={fileRef} type="file" accept="audio/*,video/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <button type="button" className="btn primary" disabled={busy || !file} onClick={add}
              aria-label={current ? `"${item.label}" tepki kaydını değiştir` : `"${item.label}" tepkisi olarak ekle`}>
              {busy ? 'Yükleniyor…' : current ? 'Değiştir' : 'Ekle'}
            </button>
          </div>
          {file && preview && (
            <Player src={preview} compact title={`Seçili kayıt — ${item.label}`} downloadName={file.name || 'tepki.webm'} />
          )}
        </div>
      )}

      {list.length > 0 ? (
        <ul className="list" aria-label="Tepki kayıtları">
          {list.map(([key, s]) => (
            <li key={s.id || key} className="item small">
              <div className="item-head">
                <span>
                  <span className="tag vc">{labelOf(key)}</span> <span className="muted">{fmtSn(s.duration)}</span>{' '}
                  <code>[{key}]</code>
                </span>
                <button type="button" className="btn ghost small danger-text" onClick={() => remove(key)}
                  aria-label={`"${labelOf(key)}" tepki kaydını sil`}>Sil</button>
              </div>
              <Player src={s.url} compact title={`${v.name} — ${labelOf(key)}`}
                downloadName={`${safeFileName(v.name)}-${safeFileName(key, 'tepki')}.wav`} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="muted small">Henüz tepki kaydı yok; kayıt yoksa etiket ünleme çevrilip okunur ("Hahaha!").</div>
      )}
    </div>
  )
}

/** Referans kaydını iyileştirme / geri alma. İşlem sürerken ikinci istek gönderilmez. */
function useEnhance(v, refresh, notify, onAudioChange) {
  const [busy, setBusy] = useState('') // '' | 'run' | 'force' | 'undo'
  const [result, setResult] = useState(null)
  const busyRef = useRef(false)

  async function guard(kind, fn) {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(kind)
    try {
      await fn()
    } finally {
      busyRef.current = false
      setBusy('')
    }
  }

  const run = (force = false) => guard(force ? 'force' : 'run', async () => {
    if (typeof api.enhanceVoice !== 'function') return notify('Kayıt iyileştirme bu sürümde yok.', 'error')
    try {
      const res = await api.enhanceVoice(v.id, force)
      const data = res && typeof res === 'object' ? res : { applied: false }
      setResult(data)
      if (!data.applied) {
        notify('Belirgin bir kazanım olmadı; kayıt değiştirilmedi.', 'warn')
        return
      }
      onAudioChange()
      const b = scoreOf(pickAnalysis(data.before))
      const a = scoreOf(pickAnalysis(data.after))
      const scores = b != null && a != null ? ` — puan ${Math.round(b)} → ${Math.round(a)}` : ''
      if (await refresh()) notify(`Kayıt iyileştirildi${scores}.`)
    } catch (err) {
      notify('İyileştirilemedi: ' + err.message, 'error')
    }
  })

  const undo = () => guard('undo', async () => {
    if (typeof api.undoEnhance !== 'function') return notify('Geri alma bu sürümde yok.', 'error')
    try {
      await api.undoEnhance(v.id)
      setResult(null)
      onAudioChange()
      if (await refresh()) notify('Özgün kayda geri dönüldü.')
    } catch (err) {
      notify('Geri alınamadı: ' + err.message, 'error')
    }
  })

  return { busy, result, run, undo, dismiss: () => setResult(null) }
}

function EnhanceResult({ result, busy, onForce, onUndo, onClose }) {
  const bs = scoreOf(pickAnalysis(result?.before))
  const as = scoreOf(pickAnalysis(result?.after))
  const delta = bs != null && as != null ? Math.round(as) - Math.round(bs) : null
  const deltaText = delta == null ? '' : `${delta > 0 ? '+' : delta < 0 ? '−' : '±'}${Math.abs(delta)} puan`
  const steps = enhanceSteps(result?.report)
  const applied = Boolean(result?.applied)
  return (
    <div className={`alert ${applied ? 'ok' : 'info'} stack tight enhance-result`} role="status">
      <div className="row between">
        <b>{applied ? '✓ Kayıt iyileştirildi' : 'Kayıt iyileştirme denendi'}</b>
        <button type="button" className="btn ghost small" onClick={onClose} disabled={Boolean(busy)} aria-label="İyileştirme sonucunu kapat">✕</button>
      </div>
      {(bs != null || as != null) && (
        <div className="row analysis-head enhance-compare">
          {bs != null && <ScoreRing score={bs} color={scoreTier(bs).color} size={44} stroke={5} />}
          <span className="muted" aria-hidden="true">→</span>
          {as != null && <ScoreRing score={as} color={scoreTier(as).color} size={44} stroke={5} />}
          <span className="small">
            <b>Önce {bs != null ? Math.round(bs) : '–'} → sonra {as != null ? Math.round(as) : '–'}</b>
            {delta != null && <> <span className={`badge ${delta >= ENHANCE_MIN_GAIN ? 'ok' : delta < 0 ? 'warn' : ''}`}>{deltaText}</span></>}
          </span>
        </div>
      )}
      {steps.length > 0 ? (
        <div className="stack tight">
          <span className="muted small">{applied ? 'Uygulananlar' : 'Denenenler'}</span>
          <div className="presets">
            {steps.map((s, k) => <span key={`${s}-${k}`} className="chip small">{s}</span>)}
          </div>
        </div>
      ) : (
        <div className="muted small">Düzeltilecek belirgin bir sorun bulunmadı.</div>
      )}
      {applied ? (
        <div className="row between">
          <span className="small">İyileştirilmiş kayıt kullanılıyor; özgün kayıt yedekte duruyor.</span>
          <button type="button" className="btn ghost small" onClick={onUndo} disabled={Boolean(busy)}>
            {busy === 'undo' ? 'Geri alınıyor…' : '↺ Geri al'}
          </button>
        </div>
      ) : (
        <div className="row between">
          <span className="small">
            Yeterli kazanım yok{delta != null ? ` (${deltaText}; en az +${ENHANCE_MIN_GAIN} gerekir)` : ''} — kayıt değiştirilmedi.
          </span>
          <button type="button" className="btn secondary small" onClick={onForce} disabled={Boolean(busy)}>
            {busy === 'force' ? 'Uygulanıyor…' : 'Yine de uygula'}
          </button>
        </div>
      )}
    </div>
  )
}

function VoiceCard({ v, languages, emotions, styles, nvItems, nvEnabled, enhanceEnabled, fresh, refresh, notify }) {
  const [showAnalysis, setShowAnalysis] = useState(Boolean(fresh))
  const [showSamples, setShowSamples] = useState(false)
  const [showNv, setShowNv] = useState(false)
  const [fetched, setFetched] = useState(null)
  const [loadingAnalysis, setLoadingAnalysis] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [audioRev, setAudioRev] = useState(0) // iyileştirme/geri alma sonrası oynatıcı yeni dosyayı yüklesin
  const ref = useRef(null)
  const analysis = pickAnalysis(v.analysis) || fetched || fresh?.analysis || null
  const counts = countSamples(v.samples)
  const freshId = fresh?.id
  const enh = useEnhance(v, refresh, notify, () => { setFetched(null); setAudioRev(Date.now()) })
  const advice = enhanceAdvice(analysis)
  const enhancing = enh.busy === 'run' || enh.busy === 'force'
  // Sunucu iyileştirilmiş sesi işaretliyorsa (isteğe bağlı alan) sonuç kartı kapalıyken de geri alınabilsin.
  const enhancedFlag = v.enhanced === true || v.enhance?.applied === true

  // Yeni eklenen ses: analiz açık gelir ve görünür alana kaydırılır.
  useEffect(() => {
    if (freshId) ref.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }, [freshId])

  async function loadAnalysis() {
    setLoadingAnalysis(true)
    try {
      const a = pickAnalysis(await api.voiceAnalysis(v.id))
      setFetched(a)
      if (!a) notify('Bu ses için analiz bulunamadı.', 'warn')
    } catch (err) {
      notify('Analiz alınamadı: ' + err.message, 'error')
    } finally {
      setLoadingAnalysis(false)
    }
  }

  function toggleAnalysis() {
    const open = !showAnalysis
    setShowAnalysis(open)
    if (open && !analysis && !loadingAnalysis) loadAnalysis()
  }

  async function rename() {
    const n = window.prompt('Yeni ad:', v.name)?.trim()
    if (!n || n === v.name) return
    try {
      await api.updateVoice(v.id, { name: n })
      if (await refresh()) notify('Ad güncellendi.')
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  async function backup() {
    setExporting(true)
    try {
      await api.exportVoice(v.id, `sesklon-${safeFileName(v.name)}.zip`)
      notify(`"${v.name}" yedeği indirildi.`)
    } catch (err) {
      notify('Yedeklenemedi: ' + err.message, 'error')
    } finally {
      setExporting(false)
    }
  }

  async function remove() {
    if (!window.confirm(`"${v.name}" ve tüm duygu/tepki kayıtları silinsin mi?`)) return
    try {
      await api.deleteVoice(v.id)
      if (await refresh()) notify(`"${v.name}" silindi.`)
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  const meta = [languages[v.language] || v.language, fmtSn(v.duration), `${counts.emotion} duygu kaydı`]
  if (counts.nonverbal) meta.push(`${counts.nonverbal} gerçek tepki`)

  return (
    <li ref={ref} className="item voice">
      <div className="item-head">
        <div>
          <strong>{v.name}</strong> <QualityBadge score={analysis?.quality_score} />
          <div className="muted small">{meta.filter(Boolean).join(' • ')}</div>
        </div>
        <div className="actions">
          <button type="button" className="btn ghost small" onClick={toggleAnalysis} aria-expanded={showAnalysis}>
            Analiz {showAnalysis ? '▴' : '▾'}
          </button>
          <button type="button" className="btn ghost small" onClick={() => setShowSamples((s) => !s)} aria-expanded={showSamples}>
            Duygu kayıtları {showSamples ? '▴' : '▾'}
          </button>
          {nvEnabled && (
            <button type="button" className="btn ghost small" onClick={() => setShowNv((s) => !s)} aria-expanded={showNv}
              title="Gülme, iç çekme gibi tepkileri kendi sesinle kaydet">
              Gerçek tepkiler {showNv ? '▴' : '▾'}
            </button>
          )}
        </div>
      </div>
      <Player src={withRev(v.url, audioRev)} downloadName={`${safeFileName(v.name)}.wav`} title={v.name} />
      {enhanceEnabled && advice.recommend && !enh.result && (
        <div className="row enhance-bar">
          <button type="button" className="btn primary small" onClick={() => enh.run(false)} disabled={Boolean(enh.busy)}
            aria-busy={enhancing}>
            {enhancing ? <><span className="spinner" aria-hidden="true" /> İyileştiriliyor…</> : '✨ Kaydı iyileştir'}
          </button>
          <span className="muted small">
            Önerilir: {advice.reasons.join(', ')}. Gürültü, uğultu ve seviye otomatik düzeltilir; özgün kayıt saklanır.
          </span>
        </div>
      )}
      {enh.result && (
        <EnhanceResult result={enh.result} busy={enh.busy} onForce={() => enh.run(true)} onUndo={enh.undo} onClose={enh.dismiss} />
      )}
      {showAnalysis && (
        <AnalysisCard analysis={analysis} loading={loadingAnalysis} onAnalyze={loadAnalysis} title="Referans kaydı" />
      )}
      <VoiceSettings v={v} styles={styles} refresh={refresh} notify={notify} />
      {showSamples && <EmotionSamples v={v} emotions={emotions} refresh={refresh} notify={notify} />}
      {nvEnabled && showNv && <NonverbalSamples v={v} items={nvItems} refresh={refresh} notify={notify} />}
      <div className="row voice-tools">
        <button type="button" className="btn ghost small" onClick={rename}>Adı değiştir</button>
        {enhanceEnabled && !advice.recommend && (
          <button type="button" className="btn ghost small" onClick={() => enh.run(false)} disabled={Boolean(enh.busy)}
            aria-busy={enhancing} title="Gürültü, elektrik uğultusu, tık sesleri ve seviyeyi otomatik düzeltir; özgün kayıt yedeklenir.">
            {enhancing ? 'İyileştiriliyor…' : 'Kaydı iyileştir'}
          </button>
        )}
        {enhanceEnabled && enhancedFlag && !enh.result && (
          <button type="button" className="btn ghost small" onClick={enh.undo} disabled={Boolean(enh.busy)}
            title="İyileştirmeden önceki özgün kayda dön">
            {enh.busy === 'undo' ? 'Geri alınıyor…' : '↺ İyileştirmeyi geri al'}
          </button>
        )}
        <button type="button" className="btn ghost small" onClick={backup} disabled={exporting}
          title="Sesi, duygu ve tepki kayıtlarını tek bir zip dosyası olarak indirin">
          {exporting ? 'Hazırlanıyor…' : '⤓ Yedekle (zip)'}
        </button>
        <button type="button" className="btn ghost small danger-text" onClick={remove}>Sil</button>
      </div>
    </li>
  )
}

/* ---------- sekme ---------- */

export default function Voices({ voices, languages, health, styles: stylesProp, reload, notify }) {
  const [fresh, setFresh] = useState(null) // son eklenen ses: { id, analysis }
  const tagEmotions = health?.tags?.emotions
  const emotions = useMemo(() => (tagEmotions || []).filter((e) => e?.name && !SKIP_EMOTIONS.has(e.name)), [tagEmotions])
  const styles = Array.isArray(stylesProp) ? stylesProp : Array.isArray(health?.styles) ? health.styles : []
  const features = health?.features || {}
  const analysisEnabled = features.analysis !== false
  // health 15 sn'de bir yeniden gelir; liste içerik olarak değişmedikçe aynı dizi kalsın.
  const nvKey = JSON.stringify(health?.tags?.nonverbal_recordable ?? null)
  const nvFeature = features.nonverbal
  const nvItems = useMemo(() => buildNvItems(JSON.parse(nvKey), nvFeature), [nvKey, nvFeature])
  const nvEnabled = nvFeature !== false && nvItems.length > 0 && typeof api.addNonverbal === 'function'
  const enhanceEnabled = features.enhance !== false && typeof api.enhanceVoice === 'function'

  /** Listeyi yeniler; başarısızsa bildirir ve false döner (başarı bildirimi yalnızca true'da gösterilir). */
  const refresh = useCallback(async () => {
    try {
      await reload()
      return true
    } catch (err) {
      notify('İşlem tamamlandı ancak ses listesi yenilenemedi: ' + err.message, 'error')
      return false
    }
  }, [reload, notify])

  const onCreated = useCallback((v) => {
    if (v?.id) setFresh({ id: v.id, analysis: pickAnalysis(v.analysis) })
  }, [])

  return (
    <div className="grid two">
      <NewVoiceForm languages={languages} analysisEnabled={analysisEnabled} refresh={refresh} notify={notify} onCreated={onCreated} />

      <section className="card">
        <LibraryHeader count={voices.length} refresh={refresh} notify={notify} />
        {voices.length === 0 ? <EmptyGuide /> : (
          <ul className="list">
            {voices.map((v) => (
              <VoiceCard key={v.id} v={v} languages={languages} emotions={emotions} styles={styles}
                nvItems={nvItems} nvEnabled={nvEnabled} enhanceEnabled={enhanceEnabled}
                fresh={fresh?.id === v.id ? fresh : null} refresh={refresh} notify={notify} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
