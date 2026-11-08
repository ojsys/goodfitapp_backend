import { useState } from 'react'
import { api } from '../api.js'
import { Loading, toast, useAccount, useLoad } from '../App.jsx'

const COLORS = ['#7D6224', '#5F7A78', '#8A5A44', '#5E7233', '#A65F2E', '#4E5E2B']

function SuggestionCard({ a, s, onChange }) {
  const [busy, setBusy] = useState(false)
  const [state, setState] = useState(s.status)
  const [err, setErr] = useState('')
  const first = s.member.first_name || s.member.name.split(' ')[0]
  const act = async (action) => {
    setBusy(true)
    setErr('')
    try {
      if (action === 'message') {
        const r = await api(`a/${a.id}/suggestions/${s.id}/message/`, { method: 'POST' })
        toast(r.message)
      } else {
        const r = await api(`a/${a.id}/suggestions/${s.id}/${action}/`, { method: 'POST' })
        setState(r.status)
        onChange()
      }
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <article className="card" aria-label={`${s.title}, suggested by ${s.member.name}`}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span className="avatar" style={{ background: COLORS[s.member.id % COLORS.length] }} aria-hidden="true">{s.member.initials}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14.5, color: 'var(--ink-2)' }}>Suggested by <b style={{ color: 'var(--ink)' }}>{s.member.name}</b></div>
          <div style={{ fontSize: 13.5, color: 'var(--muted)' }}>{s.member.line}</div>
        </div>
        {state === 'new' && <span className="pill new">New</span>}
      </div>
      <h2 style={{ fontSize: 22, marginTop: 12 }}>{s.title}</h2>
      <div style={{ fontSize: 15, marginTop: 4 }}>{s.line}</div>
      <div style={{ fontSize: 15, color: 'var(--muted)', marginTop: 2 }}>{s.line2}</div>
      {s.note && <div className="quote">“{s.note}”</div>}
      {err && <p className="err" role="alert" style={{ marginBottom: 10 }}>{err}</p>}
      {state === 'new' ? (
        <div className="sug-actions">
          <button type="button" className="btn" disabled={busy} onClick={() => act('approve')}>Approve as club ride</button>
          <button type="button" className="btn ghost" style={{ flex: 'none' }} disabled={busy} onClick={() => act('decline')}>Decline</button>
          <button type="button" className="link" disabled={busy} onClick={() => act('message')}>Message {first}</button>
        </div>
      ) : (
        <div className="okmsg" role="status" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
          <span>{state === 'approved'
            ? `Approved. It’s on the club calendar as a Club ride, and ${first} is ride leader.`
            : `Declined. ${first} got a kind note and can still host it as a community ride.`}</span>
          <button type="button" className="link" style={{ height: 32 }} disabled={busy} onClick={() => act('undo')}>Undo</button>
        </div>
      )}
    </article>
  )
}

export default function Suggestions() {
  const a = useAccount()
  const [d, err, retry, setD] = useLoad(`a/${a.id}/suggestions/`, [a.id])
  const [flagMsg, setFlagMsg] = useState({})
  if (!d) return <Loading err={err} retry={retry} />
  const open = d.suggestions.length
  const flag = async (f, action) => {
    try {
      const r = await api(`a/${a.id}/flags/${f.id}/${action}/`, { method: 'POST' })
      setFlagMsg({ ...flagMsg, [f.id]: r.message })
    } catch (e) {
      toast(e.message)
    }
  }
  return (
    <>
      <div>
        <div className="kicker">{d.club}{d.is_house ? ' · Parent company' : ''}</div>
        <h1>Suggested rides</h1>
        <p className="kicker" style={{ marginTop: 6 }}>{open ? `${open} waiting for review` : 'Nothing waiting for review'}</p>
      </div>
      <div className="cols">
        <div className="wide">
          {open === 0 && <div className="card empty">When members suggest rides to {d.club}, they show up here.</div>}
          {d.suggestions.map((s) => <SuggestionCard key={s.id} a={a} s={s} onChange={() => setD({ ...d })} />)}
        </div>
        <div className="narrow">
          <div className="card">
            <h2 style={{ fontSize: 20 }}>How suggestions work</h2>
            <div className="steps-list">
              <div><i>1</i>A member suggests a ride from the app.</div>
              <div><i>2</i>Anyone on your team who can approve suggestions reviews it here.</div>
              <div><i>3</i>Approved rides become Club rides with the member as ride leader. Event data stays with the club.</div>
            </div>
          </div>
          <div className="card">
            <h2 style={{ fontSize: 20 }}>Using the club’s name</h2>
            <p className="sub" style={{ fontSize: 14.5, lineHeight: 1.45 }}>
              Community rides that mention {d.club.split(' ')[0]} but aren’t run by the club.
            </p>
            {d.flags.length === 0 && <p className="sub" style={{ marginTop: 12 }}>None right now.</p>}
            {d.flags.map((f) => (
              <div className="flag" key={f.id}>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{f.title}</div>
                <div style={{ fontSize: 13.5, color: 'var(--muted)', marginTop: 2 }}>{f.line}</div>
                {flagMsg[f.id] ? <div className="okmsg" role="status" style={{ marginTop: 10 }}>{flagMsg[f.id]}</div> : (
                  <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
                    <button type="button" className="btn sm" style={{ flex: 1 }} onClick={() => flag(f, 'rename')}>Ask to rename</button>
                    <button type="button" className="btn ghost sm" onClick={() => flag(f, 'allow')}>It’s fine</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
