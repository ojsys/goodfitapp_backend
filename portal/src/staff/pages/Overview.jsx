import { Link } from 'react-router-dom'
import { ago, fmt } from '../api.js'
import { Loading, useLoad, useSession } from '../App.jsx'
import Icon from '../../icons.jsx'

const QUEUE = { reports: ['/reports', 'flag'], featured: ['/featured', 'star'], businesses: ['/businesses', 'store'], support: ['/support', 'chat'] }

export function Spark({ data, label }) {
  const max = Math.max(1, ...data.map((d) => d.n))
  const total = data.reduce((a, d) => a + d.n, 0)
  return (
    <div>
      <div className="spark" role="img" aria-label={`${label}: ${total} in the last 30 days`}>
        {data.map((d) => (
          <i key={d.day} title={`${d.day}: ${d.n}`} style={{ height: `${Math.max(2, (d.n / max) * 100)}%` }} className={d.n ? '' : 'z'} />
        ))}
      </div>
      <div className="spark-axis"><span>30 days ago</span><span>Today</span></div>
    </div>
  )
}

export default function Overview() {
  const s = useSession()
  const [d, err, retry] = useLoad('overview/')
  const h = new Date().getHours()
  const hello = `${h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'}, ${s.user.first_name}`
  if (!d) return <Loading err={err} retry={retry} />
  const mixMax = Math.max(1, ...d.mix.map((m) => m.n))
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">{hello}</div>
          <h1>Overview</h1>
        </div>
      </div>

      <div className="queues">
        {d.queues.map((q) => {
          const [to, icon] = QUEUE[q.key]
          const body = (
            <>
              <span className={`qi${q.n ? ' on' : ''}`}><Icon name={icon} /></span>
              <span className="qt">
                <b>{fmt(q.n)}</b>
                <span>{q.label}</span>
                {q.urgent > 0 && <span className="urgent">{q.urgent} {q.key === 'support' ? 'about safety' : 'unsafe'}</span>}
              </span>
            </>
          )
          return q.allowed
            ? <Link key={q.key} to={to} className="queue">{body}</Link>
            : <div key={q.key} className="queue off" title="You don’t have access to this queue">{body}</div>
        })}
      </div>

      <div className="stats wrap">
        {d.stats.map((st) => (
          <div className="stat" key={st.k}>
            <div className="k">{st.k}</div>
            <div className="v">{fmt(st.v)}</div>
            <div className="n">{st.n}</div>
          </div>
        ))}
      </div>

      <div className="cols">
        <div className="wide">
          <div className="card">
            <h2>New members</h2>
            <p className="sub">Sign-ups per day, last 30 days</p>
            <Spark data={d.signups} label="New members" />
          </div>
          <div className="card">
            <h2>Activities recorded</h2>
            <p className="sub">Per day, last 30 days</p>
            <Spark data={d.activities} label="Activities" />
          </div>
        </div>
        <div className="narrow">
          <div className="card">
            <h2>What people are doing</h2>
            <p className="sub">Activities by type, last 30 days</p>
            <div style={{ marginTop: 12 }}>
              {d.mix.length === 0 && <p className="sub">No activities yet.</p>}
              {d.mix.map((m) => (
                <div className="hbar slim" key={m.type}>
                  <span>{(m.type || 'other').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())}</span>
                  <span className="tr"><i style={{ width: `${(m.n / mixMax) * 100}%` }} /></span>
                  <b>{fmt(m.n)}</b>
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="row-between"><h2>Recent changes</h2><Link to="/log" className="small-link">All</Link></div>
            {d.recent.length === 0 && <p className="sub" style={{ marginTop: 8 }}>Nothing yet. Changes made here or in the Django admin show up here.</p>}
            {d.recent.map((e) => (
              <div className="logrow" key={e.id}>
                <span className="avatar sm">{e.by.slice(0, 1).toUpperCase()}</span>
                <div style={{ minWidth: 0 }}>
                  <div><b>{e.by}</b> {e.action} {e.model_name.toLowerCase()} <LogTarget e={e} /></div>
                  {e.message && <div className="when">{e.message}</div>}
                  <div className="when">{ago(e.when)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

export function LogTarget({ e }) {
  if (e.action !== 'deleted' && e.model && e.object_id) {
    return <Link to={`/data/${e.model}/${e.object_id}`}>{e.object}</Link>
  }
  return <b>{e.object}</b>
}
