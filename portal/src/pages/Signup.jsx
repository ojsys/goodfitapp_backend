import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useSession } from '../App.jsx'
import Icon from '../icons.jsx'

export default function Signup() {
  const s = useSession()
  const nav = useNavigate()
  const signedIn = !!s.user
  const [f, setF] = useState({ name: '', category: 'yoga', address: '', website: '', email: '', password: '', contact: '' })
  const [agree, setAgree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const ready = f.name.trim().length > 1 && agree && (signedIn || (f.email.includes('@') && f.password.length >= 8))

  const submit = async (e) => {
    e.preventDefault()
    if (!ready || busy) return
    setBusy(true)
    setErr('')
    try {
      const r = await api('signup/', { method: 'POST', body: { ...f, agree } })
      s.set({ user: r.user, accounts: r.accounts })
      nav(`/a/${r.account}/overview`)
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
        <h1>Bring your event to the people who move.</h1>
        <p>Feature your classes, runs and pop-ups to active members near you, and see how many show up.</p>
        <div style={{ marginTop: 16 }} />
        {['Reach members by neighborhood and activity', 'Clear “Featured” labels members trust',
          'Partners can start and run their own club'].map((t) => (
          <div className="pt" key={t}><Icon name="check" color="#F2E2D4" size={18} stroke={2.4} />{t}</div>
        ))}
        <div className="grow" />
        <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.7)' }}>
          Featured events follow our Community Guidelines and are reviewed before going live.
        </div>
      </div>
      <div className="formside">
        <form className="form" onSubmit={submit} noValidate>
          <div>
            <h2>Create your business account</h2>
            <p className="sub" style={{ fontSize: 15 }}>
              Takes about 3 minutes. We verify every business within 1 business day.
            </p>
          </div>
          <div className="field">
            <label htmlFor="bz-name">Business name</label>
            <input id="bz-name" className="input" value={f.name} onChange={set('name')} placeholder="Lumen Yoga Studio" />
          </div>
          <div className="field">
            <label htmlFor="bz-cat">Category</label>
            <select id="bz-cat" className="input" value={f.category} onChange={set('category')}>
              {(s.categories || []).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div className="row">
            <div className="field" style={{ flex: 1.4 }}>
              <label htmlFor="bz-addr">Address</label>
              <input id="bz-addr" className="input" value={f.address} onChange={set('address')} placeholder="88 DeKalb Ave, Brooklyn, NY" />
            </div>
            <div className="field">
              <label htmlFor="bz-web">Website or Instagram</label>
              <input id="bz-web" className="input" value={f.website} onChange={set('website')} placeholder="@lumenyogabk" />
            </div>
          </div>
          {signedIn ? (
            <p className="sub">Adding a business to {s.user.email}.</p>
          ) : (
            <div className="row">
              <div className="field">
                <label htmlFor="bz-email">Work email</label>
                <input id="bz-email" className="input" type="email" autoComplete="email" value={f.email}
                  onChange={set('email')} placeholder="you@lumenyoga.com" />
              </div>
              <div className="field">
                <label htmlFor="bz-pw">Password</label>
                <input id="bz-pw" className="input" type="password" autoComplete="new-password" value={f.password}
                  onChange={set('password')} placeholder="At least 8 characters" />
              </div>
            </div>
          )}
          <button type="button" className="check" role="checkbox" aria-checked={agree ? 'true' : 'false'}
            onClick={() => setAgree(!agree)}>
            <span className="box">{agree && <Icon name="check" size={15} stroke={3} color="#fff" />}</span>
            <span>I agree to the <a href="/community-guidelines/" target="_blank" rel="noreferrer"
              onClick={(e) => e.stopPropagation()}>Community Guidelines</a> and the <a href="/featured-events-policy/" target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>Featured Events Policy</a>.
              Featured events are labeled and reviewed before going live.</span>
          </button>
          {err && <p className="err" role="alert">{err}</p>}
          <button type="submit" className="btn block" disabled={!ready || busy}>
            {busy ? 'Creating your account…' : 'Create business account'}
          </button>
          {!signedIn && (
            <p style={{ fontSize: 14, color: 'var(--muted)' }}>Already have an account? <Link to="/login">Log in</Link></p>
          )}
          {signedIn && s.accounts.length > 0 && (
            <p style={{ fontSize: 14 }}><Link to={`/a/${s.accounts[0].id}/overview`}>← Back to the portal</Link></p>
          )}
        </form>
      </div>
    </div>
  )
}
