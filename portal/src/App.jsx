import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api } from './api.js'
import Icon from './icons.jsx'
import Signup from './pages/Signup.jsx'
import Login from './pages/Login.jsx'
import Overview from './pages/Overview.jsx'
import Feature from './pages/Feature.jsx'
import Results, { ResultsIndex } from './pages/Results.jsx'
import Suggestions from './pages/Suggestions.jsx'
import Team from './pages/Team.jsx'
import Billing from './pages/Billing.jsx'
import Settings from './pages/Settings.jsx'

const Session = createContext(null)
export const useSession = () => useContext(Session)

/** The account in the URL, with the person's role and permissions on it. */
export function useAccount() {
  const { acct } = useParams()
  const s = useSession()
  return s.accounts.find((a) => String(a.id) === acct) || null
}

let toastTimer
export function toast(msg) {
  window.dispatchEvent(new CustomEvent('agf-toast', { detail: msg }))
}

export default function App() {
  const [s, setS] = useState(null)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      setS(await api('session/'))
    } catch (e) {
      setS({ user: null, accounts: [], error: e.message })
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
  const ctx = { ...s, reload: load, set: (patch) => setS((old) => ({ ...old, ...patch })) }
  const home = s.user ? (s.accounts.length ? `/a/${s.accounts[0].id}/overview` : '/signup') : '/login'
  return (
    <Session.Provider value={ctx}>
      <Routes>
        <Route path="/signup" element={<Signup />} />
        <Route path="/login" element={s.user ? <Navigate to={home} replace /> : <Login />} />
        <Route path="/a/:acct/*" element={s.user ? <Shell /> : <Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to={home} replace />} />
      </Routes>
      {msg && <div className="toast" role="status">{msg}</div>}
    </Session.Provider>
  )
}

const NAV = [
  ['overview', 'grid', 'Overview', 'see_event_data'],
  ['feature', 'star', 'Feature an event', 'feature_events'],
  ['results', 'chart', 'Results', 'see_event_data'],
  ['suggestions', 'inbox', 'Suggested rides', 'approve_suggestions', true],
  ['team', 'people', 'Team', null],
  ['billing', 'card', 'Billing', 'manage_billing'],
  ['settings', 'gear', 'Settings', null],
]

function Shell() {
  const s = useSession()
  const a = useAccount()
  const nav = useNavigate()
  if (!a) return <Navigate to="/" replace />
  const show = NAV.filter(([, , , perm, club]) => (!perm || a.perms[perm]) && (!club || a.club))
  const signOut = async () => {
    await api('logout/', { method: 'POST' })
    await s.reload()
    nav('/login')
  }
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">A Good Fit<small>for Business</small></div>
        <nav className="nav" aria-label="Business">
          {show.map(([path, icon, label]) => (
            <NavLink key={path} to={`/a/${a.id}/${path}`} className={({ isActive }) => (isActive ? 'on' : '')}>
              <Icon name={icon} />{label}
            </NavLink>
          ))}
        </nav>
        <div className="grow" />
        <div>
          <div className="acct-h">Accounts</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {s.accounts.map((x) => (
              <button key={x.id} type="button" className={`acct${x.id === a.id ? ' on' : ''}`}
                aria-current={x.id === a.id ? 'true' : 'false'}
                onClick={() => nav(`/a/${x.id}/${x.perms.see_event_data ? 'overview' : 'team'}`)}>
                <span className={`tile${x.is_house ? ' house' : ''}`}>{x.initials}</span>
                <span style={{ minWidth: 0 }}>
                  <b>{x.name}</b>
                  <span className={`l${x.verified && !x.is_house ? ' ok' : ''}`}>
                    {x.verified && !x.is_house ? '✓ ' : ''}{x.line}
                  </span>
                </span>
              </button>
            ))}
            <NavLink to="/signup" className="link muted" style={{ fontSize: 13, height: 32, paddingLeft: 10 }}>
              + Add a business
            </NavLink>
          </div>
        </div>
        <button type="button" className="signout" onClick={signOut}>Sign out</button>
      </aside>
      <main className="main" id="main">
        <Routes>
          <Route path="overview" element={<Overview />} />
          <Route path="feature" element={<Feature />} />
          <Route path="feature/:pid" element={<Feature />} />
          <Route path="results" element={<ResultsIndex />} />
          <Route path="results/:pid" element={<Results />} />
          <Route path="suggestions" element={<Suggestions />} />
          <Route path="team" element={<Team />} />
          <Route path="billing" element={<Billing />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to={a.perms.see_event_data ? 'overview' : 'team'} replace />} />
        </Routes>
      </main>
    </div>
  )
}

/** Fetch on mount and when deps change: [data, error, reload, setData]. */
export function useLoad(path, deps = []) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const run = useCallback(async () => {
    setErr(null)
    try {
      setData(await api(path))
    } catch (e) {
      setErr(e)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])
  useEffect(() => { run() }, [run])
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

export function greeting(name) {
  const h = new Date().getHours()
  const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
  return `${part}, ${name}`
}
