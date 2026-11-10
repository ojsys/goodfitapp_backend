import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ago, api, when } from '../api.js'
import { Loading, Tabs, toast, useLoad, useSession } from '../App.jsx'

const SEV = { 0: 'rejected', 1: 'pending', 2: 'draft' }

export default function Reports() {
  const s = useSession()
  const [tab, setTab] = useState('open')
  const [d, err, retry] = useLoad(`reports/?status=${tab}`)
  useEffect(() => { if (d && tab === 'open') s.setCounts((c) => ({ ...c, reports: d.open })) }, [d]) // eslint-disable-line
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">Trust &amp; safety</div>
          <h1>Reports</h1>
          <p className="sub">Unsafe first, then under 21, then the rest; oldest first. A decision about a member settles every open report about them, and reporters see the outcome in the app.</p>
        </div>
      </div>
      <Tabs label="Report status" value={tab} onChange={setTab}
        items={[['open', 'Open', d && tab === 'open' ? d.open : undefined], ['resolved', 'Resolved']]} />
      {!d ? <Loading err={err} retry={retry} /> : d.items.length === 0
        ? <div className="card empty">{tab === 'open' ? 'Nothing waiting. Nice.' : 'No resolved reports yet.'}</div>
        : d.items.map((r) => <ReportCard key={r.id} r={r} decisions={d.decisions} done={retry} />)}
    </>
  )
}

function ReportCard({ r, decisions, done }) {
  const [decision, setDecision] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const decide = async () => {
    setBusy(true)
    try {
      const res = await api(`reports/${r.id}/decide/`, { method: 'POST', body: { decision, note } })
      toast(`Done. ${res.resolved} report${res.resolved === 1 ? '' : 's'} resolved.`)
      done()
    } catch (e) {
      toast(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <article className="card qcard" aria-labelledby={`r${r.id}`}>
      <div className="qhead">
        <span className={`pill ${SEV[r.priority]}`}>{r.severity}</span>
        <h2 id={`r${r.id}`}>{r.reason}</h2>
        <span className="sub nomargin">· {r.kind}{r.context ? ` · ${r.context}` : ''}</span>
        <span className="grow" />
        <span className="when" title={when(r.created_at)}>{ago(r.created_at)}</span>
      </div>
      <div className="kv">
        <div><span>About</span>{r.about
          ? <><Link to={`/data/users.user/${r.about.id}`}>{r.about.name}</Link>{r.about_active === false && <span className="pill rejected sm">Suspended</span>}
            {r.times > 1 && <span className="pill pending sm">{r.times} open reports</span>}</>
          : <b>Deleted account</b>}</div>
        <div><span>Reported by</span>{r.reporter ? <Link to={`/data/users.user/${r.reporter.id}`}>{r.reporter.name}</Link> : '—'}</div>
        <div><span>Report</span><Link to={`/data/safety.report/${r.id}`}>#{r.id}</Link></div>
      </div>
      {r.snapshot && <div className="quote pre">{r.snapshot}</div>}
      {r.details && <p className="details"><b>Reporter’s note: </b>{r.details}</p>}
      {r.status === 'open' ? (
        <div className="decide">
          <div className="chips" role="radiogroup" aria-label="Outcome">
            {decisions.map(([k, label]) => (
              <button key={k} type="button" role="radio" className={`chip${['suspend', 'ban', 'age_check'].includes(k) ? ' strong' : ''}`}
                aria-checked={decision === k} aria-pressed={decision === k} onClick={() => setDecision(k)}>{label}</button>
            ))}
          </div>
          {decision && (
            <div className="row-gap">
              <input className="input" placeholder="Note the reporter sees (optional; a standard one is used otherwise)"
                aria-label="Note for the reporter" value={note} onChange={(e) => setNote(e.target.value)} />
              <button type="button" className="btn" disabled={busy} onClick={decide}>{busy ? 'Saving…' : 'Decide'}</button>
            </div>
          )}
        </div>
      ) : (
        <div className="okmsg">{r.outcome}{r.outcome_note ? `: ${r.outcome_note}` : ''} · {r.reviewed_by ? r.reviewed_by.name : '—'} · {when(r.resolved_at)}</div>
      )}
    </article>
  )
}
