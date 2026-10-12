const KEY_STORAGE = 'sesklon_api_key'

export function getApiKey() {
  try { return localStorage.getItem(KEY_STORAGE) || '' } catch { return '' }
}
export function setApiKey(k) {
  try { k ? localStorage.setItem(KEY_STORAGE, k) : localStorage.removeItem(KEY_STORAGE) } catch {}
}

async function request(path, { method = 'GET', body, json } = {}) {
  const headers = {}
  const key = getApiKey()
  if (key) headers['X-API-Key'] = key
  if (json) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, { method, headers, body: json ? JSON.stringify(body ?? json) : body })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data)
    } catch {}
    throw new Error(msg)
  }
  return res.json()
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 202 ile dönen işi, bitene kadar sorgular; onProgress(job) ile ilerleme verir. */
async function waitJob(job, onProgress) {
  let j = job
  while (j.status === 'queued' || j.status === 'running') {
    onProgress?.(j)
    await sleep(j.status === 'queued' ? 1000 : 600)
    j = await request(`/api/jobs/${j.id}`)
  }
  onProgress?.(j)
  if (j.status === 'error') throw new Error(j.error || 'Üretim başarısız')
  return j.result
}

export const api = {
  health: () => request('/api/health'),
  warmup: () => request('/api/warmup', { method: 'POST' }),
  voices: () => request('/api/voices'),
  createVoice: ({ name, language, file, consent }) => {
    const fd = new FormData()
    fd.append('name', name); fd.append('language', language)
    fd.append('consent', consent ? 'true' : 'false'); fd.append('file', file)
    return request('/api/voices', { method: 'POST', body: fd })
  },
  renameVoice: (id, name) => request(`/api/voices/${id}`, { method: 'PATCH', json: { name } }),
  deleteVoice: (id) => request(`/api/voices/${id}`, { method: 'DELETE' }),
  addSample: (id, emotion, file) => {
    const fd = new FormData(); fd.append('emotion', emotion); fd.append('file', file)
    return request(`/api/voices/${id}/samples`, { method: 'POST', body: fd })
  },
  deleteSample: (id, emotion) => request(`/api/voices/${id}/samples/${encodeURIComponent(emotion)}`, { method: 'DELETE' }),
  tts: async (payload, onProgress) => {
    const job = await request('/api/tts', { method: 'POST', json: payload })
    return waitJob(job, onProgress)
  },
  vc: async ({ voice_id, file }, onProgress) => {
    const fd = new FormData(); fd.append('voice_id', voice_id); fd.append('file', file)
    const job = await request('/api/vc', { method: 'POST', body: fd })
    return waitJob(job, onProgress)
  },
  generations: () => request('/api/generations'),
  deleteGeneration: (id) => request(`/api/generations/${id}`, { method: 'DELETE' }),
}
