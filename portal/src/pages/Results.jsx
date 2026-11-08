import { Link, Navigate, useParams } from 'react-router-dom'
import { fmt } from '../api.js'
import { Loading, useAccount, useLoad } from '../App.jsx'
import Icon from '../icons.jsx'
import { StatusPill } from './Overview.jsx'

function Line({ data }) {
  const W = 820, H = 260, L = 44, B = 30, T = 18
  const max = Math.max(1, ...data.map((d) => d.value))
  const top = Math.ceil(max * 1.1 / 10) * 10 || 10
  const x = (i) => L + (data.length === 1 ? (W - L) / 2 : (i * (W - L - 30)) / (data.length - 1) + 14)
  const y = (v) => T + (H - T - B) * (1 - v / top)
  const pts = data.map((d, i) => `${x(i)},${y(d.value)}`).join(' ')
  const last = data[data.length - 1]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
      aria-label={`Views per day: ${data.map((d) => `${d.label} ${d.value}`).join(', ')}`}>
      {[top, top / 2, 0].map((v) => (
        <g key={v}>
          <line x1={L} x2={W} y1={y(v)} y2={y(v)} stroke="#EBE6DB" />
          <text x={L - 8} y={y(v) + 4} fontSize="12" fill="#6E6A5C" textAnchor="end">{fmt(Math.round(v))}</text>
        </g>
      ))}
      <polyline points={pts} fill="none" stroke="#6B7F3C" strokeWidth="2.5" strokeLinejoin="round" />
      {data.map((d, i) => <circle key={d.label} cx={x(i)} cy={y(d.value)} r="5" fill="#6B7F3C" />)}
      {data.map((d, i) => (data.length <= 10 || i % Math.ceil(data.length / 8) === 0) && (
        <text key={`l${d.label}`} x={x(i)} y={H - 8} fontSize="12.5" fill="#6E6A5C" textAnchor="middle">{d.label}</text>
      ))}
      {last && <text x={x(data.length - 1)} y={y(last.value) - 14} fontSize="13" fontWeight="700" fill="#31391B"
        textAnchor="end">{fmt(last.value)} today</text>}
    </svg>
  )
}

function Breakdown({ title, rows, minGroup }) {
  return (
    <div className="card" style={{ flex: 1 }}>
      <h2 style={{ fontSize: 20, marginBottom: 12 }}>{title}</h2>
      {!rows ? (
        <p className="sub">Shown once {minGroup} or more people RSVP, so no one can be singled out.</p>
      ) : rows.map((r) => (
        <div className="hbar" key={r.label}>
          <span>{r.label}</span>
          <span className="tr"><i style={{ width: `${(100 * r.pct) / Math.max(...rows.map((x) => x.pct))}%` }} /></span>
          <b>{r.pct}%</b>
        </div>
      ))}
    </div>
  )
}

export default function Results() {
  const a = useAccount()
  const { pid } = useParams()
  const [d, err, retry] = useLoad(`a/${a.id}/featured/${pid}/results/`, [a.id, pid])
  if (!d) return <Loading err={err} retry={retry} />
  const views = Math.max(1, d.funnel[0].value)
  return (
    <>
      <div>
        <Link to={`/a/${a.id}/overview`} className="back"><Icon name="back" size={16} />Overview</Link>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <h1>{d.title}</h1><StatusPill status={d.status} label={d.status_label} />
        </div>
        <p className="kicker" style={{ marginTop: 8 }}>{d.line}</p>
      </div>
      <div className="stats">
        {d.stats.map((st) => (
          <div className="stat" key={st.label}>
            <div className="k">{st.label}</div>
            <div className="v">{fmt(st.value)}</div>
            <div className="n">{st.note}</div>
          </div>
        ))}
      </div>
      <div className="cols">
        <div className="wide">
          <div className="card">
            <h2 style={{ fontSize: 20 }}>Views per day</h2>
            <p className="sub">Since the feature went live</p>
            <div style={{ marginTop: 14 }}>
              {d.per_day.length ? <Line data={d.per_day} /> : <p className="empty">It isn’t live yet.</p>}
            </div>
          </div>
        </div>
        <div className="narrow" style={{ width: 420 }}>
          <div className="card">
            <h2 style={{ fontSize: 20, marginBottom: 10 }}>From view to RSVP</h2>
            {d.funnel.slice(0, 3).map((f) => (
              <div className="funnel" key={f.label}>
                <span>{f.label}</span>
                <span className="tr"><i style={{ width: `${(100 * f.value) / views}%` }} /></span>
                <b>{fmt(f.value)}</b>
              </div>
            ))}
            <div className="funnel">
              <span style={{ fontWeight: 600 }}>Check-ins</span>
              {d.funnel[3].value > 0
                ? <><span className="tr"><i style={{ width: `${(100 * d.funnel[3].value) / views}%` }} /></span><b>{fmt(d.funnel[3].value)}</b></>
                : <span style={{ gridColumn: 'span 2', fontSize: 14.5, color: 'var(--muted)' }}>{d.checkin_note}</span>}
            </div>
          </div>
          {d.shared_names.length > 0 && (
            <div className="card">
              <h2 style={{ fontSize: 18 }}>Shared their name at check-in</h2>
              <p style={{ marginTop: 8, lineHeight: 1.5 }}>{d.shared_names.join(', ')}</p>
            </div>
          )}
        </div>
      </div>
      <div className="stats">
        <Breakdown title="Where RSVPs live" rows={d.neighborhoods} minGroup={d.min_group} />
        <Breakdown title="What they’re into" rows={d.interests} minGroup={d.min_group} />
      </div>
      <p className="foot">All numbers are counts. Members’ names and profiles are never shared unless they choose to at check-in.</p>
    </>
  )
}

export function ResultsIndex() {
  const a = useAccount()
  const [d, err, retry] = useLoad(`a/${a.id}/overview/`, [a.id])
  if (!d) return <Loading err={err} retry={retry} />
  const shown = d.events.filter((e) => ['live', 'scheduled', 'ended'].includes(e.status))
  if (shown.length === 1) return <Navigate to={`/a/${a.id}/results/${shown[0].id}`} replace />
  return (
    <>
      <div><div className="kicker">{a.name}</div><h1>Results</h1></div>
      <div className="card flush">
        {shown.length === 0 ? <div className="empty">Results show up here once a featured event goes live.</div> : (
          <table>
            <thead><tr><th>Event</th><th>When</th><th>Status</th><th>Views</th><th>RSVPs</th><th /></tr></thead>
            <tbody>{shown.map((e) => (
              <tr key={e.id}>
                <td className="t">{e.title}</td><td>{e.when}</td>
                <td><StatusPill status={e.status} label={e.status_label} /></td>
                <td className="num">{fmt(e.views)}</td><td className="num">{fmt(e.rsvps)}</td>
                <td><Link to={`/a/${a.id}/results/${e.id}`}>View results</Link></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </>
  )
}
