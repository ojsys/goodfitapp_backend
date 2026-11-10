import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { api } from './api.js'
import Icon from '../icons.jsx'
import Login from './pages/Login.jsx'
import Overview from './pages/Overview.jsx'
import Reports from './pages/Reports.jsx'
import Featured from './pages/Featured.jsx'
import Businesses from './pages/Businesses.jsx'
import Support from './pages/Support.jsx'
import { DataIndex, DataList, DataRecord } from './pages/Data.jsx'
import Log from './pages/Log.jsx'
import Team from './pages/Team.jsx'

const Session = createContext(null)
export const useSession = () => useContext(Session)

let toastTimer
export function toast(msg) {
  window.dispatchEvent(new CustomEvent('agf-toast', { detail: msg }))
}

export default function App() {
  const [s, setS] = useState(null)
  const [msg, setMsg] = useState('')
  const [counts, setCounts] = useState({})

  const load = useCallback(async () => {
    try {
      setS(await api('session/'))
    } catch (e) {
      setS({ user: null, error: e.message })
    }
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const h = (e) => {
      setMsg(e.detail)
      clearTimeout(toastTimer)
      toastTimer = setTimeout(() => setMsg(''), 3500)
    }
    window.addEventListener('agf-toast', h)
    return () => window.removeEventListener('agf-toast', h)
  }, [])

  if (!s) return <div className="empty" style={{ paddingTop: 120 }}>Loading…</div>
  const ctx = { ...s, reload: load, set: (patch) => setS((old) => ({ ...old, ...patch })), counts, setCounts }
  return (
    <Session.Provider value={ctx}>
      <Routes>
        <Route path="/login" element={s.user ? <Navigate to="/" replace /> : <Login />} />
        <Route path="/*" element={s.user ? <Shell /> : <Navigate to="/login" replace />} />
      </Routes>
      {msg && <div className="toast" role="status">{msg}</div>}
    </Session.Provider>
  )
}

const NAV = [
  ['/', 'grid', 'Overview', null, true],
  ['/reports', 'flag', 'Reports', 'reports'],
  ['/featured', 'star', 'Featured events', 'featured'],
  ['/businesses', 'store', 'Businesses', 'businesses'],
  ['/support', 'chat', 'Support', 'support'],
  ['/data/users.user', 'user', 'Members'],
  ['/data', 'db', 'All data', null, true],
  ['/log', 'clock', 'Change history'],
  ['/team', 'people', 'Staff team'],
]

function Shell() {
  const s = useSession()
  const nav = useNavigate()
  useEffect(() => {
    api('overview/').then((d) => s.setCounts(Object.fromEntries(d.queues.map((q) => [q.key, q.n])))).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const signOut = async () => {
    await api('logout/', { method: 'POST' })
    await s.reload()
    nav('/login')
  }
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="side">
        <div className="brand">A Good Fit<small>Staff</small></div>
        <nav className="nav" aria-label="Staff">
          {NAV.map(([path, icon, label, q, end]) => (
            <NavLink key={path} to={path} end={end} className={({ isActive }) => (isActive ? 'on' : '')}>
              <Icon name={icon} />{label}
              {q && s.counts[q] > 0 && <span className="count" aria-label={`${s.counts[q]} waiting`}>{s.counts[q]}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="grow" />
        <a className="side-link" href="/admin/"><Icon name="out" size={16} />Django admin</a>
        <div className="who">
          <span className="avatar sm">{(s.user.name || '?').slice(0, 1).toUpperCase()}</span>
          <span style={{ minWidth: 0 }}>
            <b>{s.user.name}</b>
            <span className={`role ${s.user.role}`}>{s.user.role === 'admin' ? 'Admin' : 'Staff'}</span>
          </span>
        </div>
        <button type="button" className="signout" onClick={signOut}>Sign out</button>
      </aside>
      <main className="main" id="main" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/featured" element={<Featured />} />
          <Route path="/businesses" element={<Businesses />} />
          <Route path="/support" element={<Support />} />
          <Route path="/data" element={<DataIndex />} />
          <Route path="/data/:model" element={<DataList />} />
          <Route path="/data/:model/new" element={<DataRecord create />} />
          <Route path="/data/:model/:pk" element={<DataRecord />} />
          <Route path="/log" element={<Log />} />
          <Route path="/team" element={<Team />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

/** Fetch on mount and when the path changes: [data, error, reload, setData]. */
export function useLoad(path) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const run = useCallback(async () => {
    setErr(null)
    try {
      setData(await api(path))
    } catch (e) {
      setErr(e)
    }
  }, [path])
  useEffect(() => { setData(null); run() }, [run])
  return [data, err, run, setData]
}

export function Loading({ err, retry }) {
  if (err) {
    return (
      <div className="card empty">
        <p>{err.message}</p>
        {retry && <button type="button" className="btn ghost sm" style={{ marginTop: 12 }} onClick={retry}>Try again</button>}
      </div>
    )
  }
  return <div className="empty">Loading…</div>
}

export function Tabs({ value, onChange, items, label }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map(([k, name, n]) => (
        <button key={k} type="button" role="tab" aria-selected={value === k} className={value === k ? 'on' : ''}
          onClick={() => onChange(k)}>
          {name}{n !== undefined && n !== null && <span className="n">{n}</span>}
        </button>
      ))}
    </div>
  )
}

/** A note box that has to be filled before a "send back"-type action. */
export function NoteAction({ label, placeholder, onSubmit, danger }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  if (!open) {
    return <button type="button" className={`btn ghost sm${danger ? ' danger-t' : ''}`} onClick={() => setOpen(true)}>{label}</button>
  }
  return (
    <div className="note-action">
      <textarea className="input" rows={2} aria-label={placeholder} placeholder={placeholder} value={note}
        onChange={(e) => setNote(e.target.value)} autoFocus />
      <div className="row-gap">
        <button type="button" className="btn sm" disabled={!note.trim() || busy}
          onClick={async () => { setBusy(true); try { await onSubmit(note.trim()) } finally { setBusy(false) } }}>
          {busy ? 'Sending…' : label}
        </button>
        <button type="button" className="link muted" onClick={() => { setOpen(false); setNote('') }}>Cancel</button>
      </div>
    </div>
  )
}
