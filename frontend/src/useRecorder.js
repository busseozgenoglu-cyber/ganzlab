import { useCallback, useEffect, useRef, useState } from 'react'

/** Tarayıcı mikrofonundan kayıt alır; sonuç bir File (webm/ogg) olarak döner. */
export function useRecorder() {
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const recRef = useRef(null)
  const chunksRef = useRef([])
  const timerRef = useRef(null)
  const resolveRef = useRef(null)

  const stop = useCallback(() => {
    return new Promise((resolve) => {
      const rec = recRef.current
      if (!rec || rec.state === 'inactive') return resolve(null)
      resolveRef.current = resolve
      rec.stop()
    })
  }, [])

  const start = useCallback(async () => {
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
        .find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || ''
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      chunksRef.current = []
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        clearInterval(timerRef.current)
        setRecording(false)
        const type = rec.mimeType || 'audio/webm'
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm'
        const file = new File(chunksRef.current, `kayit.${ext}`, { type })
        resolveRef.current?.(file)
        resolveRef.current = null
      }
      recRef.current = rec
      rec.start(250)
      setSeconds(0)
      setRecording(true)
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000)
    } catch (e) {
      setError('Mikrofona erişilemedi: ' + (e?.message || e))
    }
  }, [])

  useEffect(() => () => clearInterval(timerRef.current), [])

  return { recording, seconds, error, start, stop }
}
