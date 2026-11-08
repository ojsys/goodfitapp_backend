import { Link } from 'react-router-dom'
import { change, fmt } from '../api.js'
import { greeting, Loading, useAccount, useLoad, useSession } from '../App.jsx'
import Icon from '../icons.jsx'

export function Bars({ data, height = 220 }) {
  const max = Math.max(1, ...data.map((d) => d.value))
  const top = Math.max(2, Math.ceil(max / 2) * 2)
  return (
    <div className="bars" style={{ height }} role="img"
      aria-label={data.map((d) => `${d.label}: ${d.value}`).join(', ')}>
      {[top, top / 2, 0].map((v, i) => (
        <div key={i} className="gl" style={{ top: `${(i / 2) * (height - 30)}px` }}><span>{fmt(v)}</span></div>
      ))}
      {data.map((d) => (
        <div className="b" key={d.label}>
          <i style={{ height: `${(d.value / top) * (height - 30)}px` }} />
          <span>{d.label}</span>
        </div>
      ))}
    </div>
  )
}

export function StatusPill({ status, label }) {
  return <span className={`pill ${status}`}>{label}</span>
}

export default function Overview() {
  const a = useAccount()
  const s = useSession()
  const [d, err, retry] = useLoad(`a/${a.id}/overview/`, [a.id])
  const first = (s.user.first_name || a.name.split(' ')[0])
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">{greeting(a.is_house ? first : a.name.split(' ')[0])}</div>
          <h1>Overview</h1>
        </div>
        {a.perms.feature_events && (
          <Link to={`/a/${a.id}/feature`} className="btn"><Icon name="star" />Feature an event</Link>
        )}
      </div>
      {!a.verified && (
        <div className="warn" role="status">
          We’re verifying {a.name}. That usually takes 1 business day. You can set up your first featured event now;
          it’ll go to review once you’re verified.
        </div>
      )}
      {!d ? <Loading err={err} retry={retry} /> : (
        <>
          <div className="label13" style={{ marginBottom: -10 }}>Last 30 days</div>
          <div className="stats">
            {d.stats.map((st) => (
              <div className="stat" key={st.label}>
                <div className="k">{st.label}</div>
                <div className="v">{fmt(st.value)}</div>
                <div className="n">
                  {st.note || (st.change === null ? 'No earlier featured events to compare'
                    : `${change(st.change)}${st.label === 'Views' ? ' vs. prior 30 days' : ''}`)}
                </div>
              </div>
            ))}
          </div>
          <div className="cols">
            <div className="wide">
              <div className="card flush">
                <div className="pad"><h2 style={{ fontSize: 20 }}>Featured events</h2></div>
                {d.events.length === 0 ? (
                  <div className="empty">
                    No featured events yet. {a.perms.feature_events && <Link to={`/a/${a.id}/feature`}>Feature your first event</Link>}
                  </div>
                ) : (
                  <table>
                    <thead><tr><th>Event</th><th>When</th><th>Status</th><th>Views</th><th>RSVPs</th><th><span className="sr">Next step</span></th></tr></thead>
                    <tbody>
                      {d.events.map((e) => (
                        <tr key={e.id}>
                          <td className="t">{e.title}</td>
                          <td className="when">{e.when}</td>
                          <td><StatusPill status={e.status} label={e.status_label} /></td>
                          <td className="num">{e.views === null ? '–' : fmt(e.views)}</td>
                          <td className="num">{e.rsvps === null ? '–' : fmt(e.rsvps)}</td>
                          <td>
                            {e.status === 'live' || e.status === 'scheduled' ? <Link to={`/a/${a.id}/results/${e.id}`}>View results</Link>
                              : e.status === 'in_review' ? <span className="note" style={{ fontSize: 13, color: 'var(--muted)' }}>Usually within 1 business day</span>
                                : e.status === 'draft' ? <Link to={`/a/${a.id}/feature/${e.id}`}>Finish setup</Link>
                                  : e.status === 'rejected' ? <Link to={`/a/${a.id}/feature/${e.id}`}>See why and edit</Link>
                                    : e.status === 'ended' ? <Link to={`/a/${a.id}/results/${e.id}`} style={{ fontWeight: 600, color: 'var(--muted)' }}>{fmt(e.checked_in)} checked in</Link> : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
            <div className="narrow">
              <div className="card">
                <h2 style={{ fontSize: 20 }}>RSVPs by week</h2>
                <p className="sub">From featured events, last 6 weeks</p>
                <div style={{ marginTop: 18 }}><Bars data={d.weeks} /></div>
              </div>
              {d.plan && (
                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h2 style={{ fontSize: 20 }}>{d.plan.name}</h2>
                    <span className={`pill ${d.plan.status === 'Active' ? 'active' : 'rejected'}`}>{d.plan.status}</span>
                  </div>
                  <p style={{ marginTop: 10, fontSize: 15, color: 'var(--ink-2)' }}>{d.plan.line}</p>
                  {d.plan.of && (
                    <div className="meter" style={{ marginTop: 12 }} role="progressbar" aria-valuemin={0}
                      aria-valuemax={d.plan.of} aria-valuenow={d.plan.used}>
                      <i style={{ width: `${(100 * d.plan.used) / d.plan.of}%` }} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          <p className="foot">You see counts, never members’ personal info. Members can choose to share their name when they check in.</p>
        </>
      )}
    </>
  )
}
