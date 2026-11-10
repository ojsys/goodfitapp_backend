import { useState } from 'react'
import { api } from '../api.js'
import { useSession } from '../App.jsx'

export default function Login() {
  const s = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      const r = await api('login/', { method: 'POST', body: { email, password } })
      s.set({ user: r.user })
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="split">
      <div className="hero staff-hero">
        <div className="brand">A Good Fit<small>Staff</small></div>
        <h1>Keep it a good place.</h1>
        <p>Reports, featured events, businesses, members and every record in the app, in one place.</p>
        <div className="grow" />
        <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.7)' }}>
          For A Good Fit staff only. Every change you make is recorded.
        </div>
      </div>
      <div className="formside">
        <form className="form" onSubmit={submit}>
          <div>
            <h2>Staff sign in</h2>
            <p className="sub" style={{ fontSize: 15 }}>Use your staff account. It’s the same login as the Django admin.</p>
          </div>
          <div className="field">
            <label htmlFor="li-email">Email</label>
            <input id="li-email" className="input" type="email" autoComplete="email" value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="li-pw">Password</label>
            <input id="li-pw" className="input" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </div>
          {err && <p className="err" role="alert">{err}</p>}
          <button type="submit" className="btn block" disabled={busy || !email || !password}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
