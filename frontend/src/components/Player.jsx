export function fmtDur(s) {
  if (s == null) return ''
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return m ? `${m}:${String(sec).padStart(2, '0')}` : `${s.toFixed(1)} sn`
}

export function fmtDate(iso) {
  try { return new Date(iso).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) } catch { return iso }
}

export default function Player({ src, downloadName, autoPlay = false }) {
  if (!src) return null
  return (
    <div className="player">
      <audio controls src={src} autoPlay={autoPlay} preload="metadata" />
      <a className="btn ghost small" href={src} download={downloadName || true} title="İndir">⬇ İndir</a>
    </div>
  )
}
