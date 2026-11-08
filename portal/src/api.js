// Same-site calls to the Django API with the session cookie. Writes send
// the CSRF token the server hands back from /session/ and /login/.
let csrf = ''
export const setCsrf = (t) => { if (t) csrf = t }

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api/business/${path}`, {
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
export const change = (c) => (c === null || c === undefined ? '' : `${c >= 0 ? '+' : ''}${c}%`)
