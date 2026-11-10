// Same-site calls to /api/staff/ with the Django session (the same login as
// /admin/). Writes send the CSRF token the server hands back.
let csrf = ''
export const setCsrf = (t) => { if (t) csrf = t }

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api/staff/${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' ? { 'X-CSRFToken': csrf } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  let data = null
  try { data = res.status === 204 ? {} : await res.json() } catch { data = null }
  if (data && data.csrf) setCsrf(data.csrf)
  if (!res.ok) {
    const err = new Error((data && (data.message || data.detail)) || 'Something went wrong. Try again.')
    err.code = (data && data.code) || res.status
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

export const fmt = (n) => (n === null || n === undefined ? '–' : typeof n === 'number' ? n.toLocaleString('en-US') : n)

export function when(iso, { time = true } = {}) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', time
    ? { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }
    : { month: 'short', day: 'numeric', year: 'numeric' })
}

export function ago(iso) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`
  return when(iso, { time: false })
}

export const qs = (o) => {
  const p = new URLSearchParams()
  Object.entries(o).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) p.set(k, v) })
  const s = p.toString()
  return s ? `?${s}` : ''
}
