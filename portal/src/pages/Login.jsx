import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useSession } from '../App.jsx'

export default function Login() {
  const s = useSession()
  const nav = useNavigate()
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
      s.set({ user: r.user, accounts: r.accounts })
      nav(r.accounts.length ? `/a/${r.accounts[0].id}/overview` : '/signup')
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="split">
      <div className="hero">
        <div className="brand">A Good Fit<small>for Business</small></div>
        <h1>Welcome back.</h1>
        <p>See how your featured events are doing, review suggested rides and run your club team.</p>
        <div className="grow" />
        <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.7)' }}>
          You see counts, never members’ personal info.
        </div>
      </div>
      <div className="formside">
        <form className="form" onSubmit={submit}>
          <div>
            <h2>Log in</h2>
            <p className="sub" style={{ fontSize: 15 }}>Use your business login, or your A Good Fit email and password if you’re on a club team.</p>
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
            {busy ? 'Logging in…' : 'Log in'}
          </button>
          <p style={{ fontSize: 14, color: 'var(--muted)' }}>New here? <Link to="/signup">Create a business account</Link></p>
        </form>
      </div>
    </div>
  )
}
