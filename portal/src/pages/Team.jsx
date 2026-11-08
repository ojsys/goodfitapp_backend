import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Loading, toast, useAccount, useLoad } from '../App.jsx'
import Icon from '../icons.jsx'

const COLORS = ['#5E7233', '#6B7F3C', '#A65F2E', '#5F7A78', '#8A5A44', '#7D6224']
const ROLES = [['admin', 'Admin'], ['organizer', 'Organizer'], ['ride_leader', 'Ride leader']]
const LABEL = { owner: 'Owner', admin: 'Admin', organizer: 'Organizer', ride_leader: 'Ride leader' }

function Invite({ a, onDone }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [pick, setPick] = useState(null)
  const [role, setRole] = useState('ride_leader')
  const [err, setErr] = useState('')
  useEffect(() => {
    if (pick || q.trim().length < 2) { setHits([]); return undefined }
    const t = setTimeout(() => {
      api(`a/${a.id}/team/?q=${encodeURIComponent(q)}`).then((r) => setHits(r.people)).catch(() => {})
    }, 200)
    return () => clearTimeout(t)
  }, [a.id, q, pick])
  const send = async () => {
    setErr('')
    try {
      const r = await api(`a/${a.id}/team/invite/`, { method: 'POST', body: { user: pick.id, role } })
      onDone(r, `Invite sent to ${r.invited}. They’ll get it in the app.`)
    } catch (e) {
      setErr(e.message)
    }
  }
  return (
    <div style={{ padding: '0 22px 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div className="field" style={{ flex: 2, position: 'relative' }}>
          <label htmlFor="inv-q">Member name</label>
          <input id="inv-q" className="input" value={pick ? pick.name : q} autoComplete="off"
            onChange={(e) => { setPick(null); setQ(e.target.value) }} placeholder="Search A Good Fit members" />
          {hits.length > 0 && (
            <div role="listbox" className="card" style={{ position: 'absolute', top: 76, left: 0, right: 0, padding: 6, zIndex: 5 }}>
              {hits.map((h) => (
                <button key={h.id} type="button" role="option" aria-selected="false" className="acct"
                  onClick={() => { setPick(h); setHits([]) }}>
                  <span className="avatar" style={{ width: 32, height: 32, fontSize: 12, background: COLORS[h.id % COLORS.length] }}>{h.initials}</span>
                  <span><b>{h.name}</b><span className="l">{h.line}</span></span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="field">
          <label htmlFor="inv-role">Role</label>
          <select id="inv-role" className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.slice().reverse().map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <button type="button" className="btn" style={{ flex: 'none' }} disabled={!pick} onClick={send}>Send invite</button>
      </div>
      {err && <p className="err" role="alert">{err}</p>}
    </div>
  )
}

export default function Team() {
  const a = useAccount()
  const [d, err, retry, setD] = useLoad(`a/${a.id}/team/`, [a.id])
  const [adding, setAdding] = useState(false)
  const [msg, setMsg] = useState('')
  if (!d) return <Loading err={err} retry={retry} />
  const call = async (path, method, body) => {
    try {
      setD(await api(`a/${a.id}/team/${path}`, { method, body }))
    } catch (e) {
      toast(e.message)
    }
  }
  const manage = d.can_manage
  return (
    <>
      <div><div className="kicker">{d.club ? `${d.club}${a.is_house ? ' · Parent company' : ''}` : a.name}</div><h1>Team</h1></div>
      <div className="cols">
        <div className="wide">
          <div className="card flush">
            <div className="pad" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div><h2 style={{ fontSize: 20 }}>People</h2>
                <p className="sub">{d.club ? 'Members who can act for the club' : 'People who can sign in for this business'}</p></div>
              {manage && d.club && (
                <button type="button" className="btn outline sm" aria-expanded={adding} onClick={() => setAdding(!adding)}>
                  <Icon name="plus" size={16} stroke={2.4} />Add someone
                </button>
              )}
            </div>
            {adding && <Invite a={a} onDone={(r, m) => { setD(r); setAdding(false); setMsg(m) }} />}
            {msg && <div className="okmsg" role="status" style={{ margin: '0 22px 14px' }}>{msg}</div>}
            <table>
              <thead><tr><th>Name</th><th>Role</th><th><span className="sr">Actions</span></th></tr></thead>
              <tbody>
                {d.people.map((p) => (
                  <tr key={`${p.id}-${p.pending}`}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                        <span className="avatar" style={{ background: COLORS[p.id % COLORS.length] }} aria-hidden="true">{p.initials}</span>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: 16 }}>{p.name}
                            {p.pending && <span className="pill pending plain" style={{ marginLeft: 8, height: 24, fontSize: 12.5 }}>Invite pending</span>}
                          </div>
                          <div style={{ fontSize: 13.5, color: 'var(--muted)' }}>{p.line}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      {p.role === 'owner' || !manage || !d.club || p.id === d.me ? (
                        <span className="pill active plain">{LABEL[p.role]}</span>
                      ) : (
                        <select className="input" style={{ width: 160, height: 42 }} aria-label={`Role for ${p.name}`}
                          value={p.role} onChange={(e) => call(`${p.id}/`, 'PATCH', { role: e.target.value })}>
                          {ROLES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {manage && d.club && p.role !== 'owner' && p.id !== d.me && (
                        <button type="button" className="link muted" onClick={() => call(`${p.id}/`, 'DELETE')}
                          aria-label={`Remove ${p.name}`}>Remove</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.grid && (
            <div className="card flush">
              <div className="pad"><h2 style={{ fontSize: 20 }}>What each role can do</h2>
                <p className="sub">Owners can do everything. Changes apply right away.</p></div>
              <table className="grid">
                <thead><tr><th>Permission</th><th>Owner</th>{ROLES.map(([k, v]) => <th key={k}>{v}</th>)}</tr></thead>
                <tbody>
                  {d.rows.map(([perm, label]) => (
                    <tr key={perm}>
                      <td className="t">{label}</td>
                      {perm === 'run_rides' ? (
                        <td colSpan={4} style={{ color: 'var(--muted)', fontSize: 14 }}>All roles: attendance, ride chat, day-of updates</td>
                      ) : (
                        <>
                          <td><Icon name="lock" size={18} color="#6E6A5C" /><span className="sr">Owners always</span></td>
                          {ROLES.map(([role, rl]) => {
                            const on = d.grid[role].includes(perm)
                            const fixed = !manage || perm === 'manage_billing'
                            return (
                              <td key={role}>
                                <button type="button" className="cb" role="checkbox" aria-checked={on}
                                  aria-label={`${rl}: ${label}`} disabled={fixed}
                                  style={fixed ? { opacity: 0.6 } : undefined}
                                  onClick={() => call('grid/', 'PATCH', { role, perm, on: !on })}>
                                  {on && <Icon name="check" size={16} stroke={3} color="#fff" />}
                                </button>
                              </td>
                            )
                          })}
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!d.club && (
            <div className="card">
              <h2 style={{ fontSize: 18 }}>Run a club on A Good Fit</h2>
              <p className="sub" style={{ fontSize: 14.5, lineHeight: 1.5 }}>Partners can start a club and build a team of admins, organizers and ride leaders here. Write to partners@agoodfit.app to set one up.</p>
            </div>
          )}
        </div>
        <div className="narrow">
          <div className="card">
            <h2 style={{ fontSize: 20, marginBottom: 6 }}>Activity</h2>
            {d.log.length === 0 && <p className="sub">Team actions show up here.</p>}
            {d.log.map((l, i) => (
              <div className="logrow" key={i}>
                <span className="avatar" style={{ background: COLORS[l.who.length % COLORS.length] }} aria-hidden="true">{l.initials}</span>
                <div><b>{l.who}</b> {l.what}<div className="when">{l.when}</div></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
