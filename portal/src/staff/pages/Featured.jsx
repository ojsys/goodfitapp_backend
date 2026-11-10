import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ago, when } from '../api.js'
import { Loading, NoteAction, Tabs, toast, useLoad, useSession } from '../App.jsx'
import Icon from '../../icons.jsx'

export default function Featured() {
  const s = useSession()
  const [tab, setTab] = useState('in_review')
  const [d, err, retry] = useLoad(`featured/?status=${tab}`)
  const c = (d && d.counts) || {}
  useEffect(() => { if (d) s.setCounts((x) => ({ ...x, featured: c.in_review || 0 })) }, [d]) // eslint-disable-line
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">Business</div>
          <h1>Featured events</h1>
          <p className="sub">Check that each one fits the Community Guidelines and the Featured Events Policy, the details are accurate and the business is real. Approving charges the card on file, then schedules it.</p>
        </div>
      </div>
      <Tabs label="Featured status" value={tab} onChange={setTab} items={[
        ['in_review', 'To review', c.in_review || 0], ['approved', 'Approved', c.approved || 0],
        ['rejected', 'Sent back', c.rejected || 0], ['draft', 'Drafts', c.draft || 0]]} />
      {!d ? <Loading err={err} retry={retry} /> : d.items.length === 0
        ? <div className="card empty">{tab === 'in_review' ? 'Nothing to review.' : 'None here.'}</div>
        : d.items.map((p) => <Placement key={p.id} p={p} done={retry} />)}
    </>
  )
}

function Placement({ p, done }) {
  const [busy, setBusy] = useState(false)
  const act = async (action, note) => {
    setBusy(true)
    try {
      await api(`featured/${p.id}/${action}/`, { method: 'POST', body: { note } })
      toast(action === 'approve' ? `Approved ${p.event.title}.` : `Sent back to ${p.account.name}.`)
      done()
    } catch (e) {
      toast(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <article className="card qcard">
      <div className="cols tight">
        <div className="wide">
          <div className="qhead">
            <span className={`pill ${p.status}`}>{p.status_label}</span>
            <h2>{p.event.title}</h2>
            <span className="grow" />
            {p.submitted_at && <span className="when">Submitted {ago(p.submitted_at)}</span>}
          </div>
          <div className="kv">
            <div><span>Business</span><Link to={`/data/business.businessaccount/${p.account.id}`}>{p.account.name}</Link>
              {p.account.verified ? <span className="pill active sm">Verified</span> : <span className="pill pending sm">Not verified yet</span>}</div>
            <div><span>When</span>{when(p.event.start_time)}</div>
            <div><span>Where</span>{p.event.location}{p.event.address ? `, ${p.event.address}` : ''}</div>
            <div><span>Package</span>{p.package} · {p.price} · {p.payment}</div>
            <div><span>Shown to</span>{[...(p.neighborhoods || []), ...(p.interests || [])].join(', ') || 'Everyone nearby'}</div>
            {p.starts_at && <div><span>Runs</span>{when(p.starts_at, { time: false })} to {when(p.ends_at, { time: false })}</div>}
          </div>
          {p.event.description && <div className="quote pre">{p.event.description}</div>}
          {p.review_note && <div className="warn">Review note: {p.review_note}</div>}
        </div>
        <div className="narrow">
          <div className="preview">
            <div className="cover"><span className="ft"><Icon name="star" size={12} stroke={2} />Featured</span></div>
            <div className="bd">
              <div className="tt">{p.event.title}</div>
              <div className="hb">Hosted by {p.account.name}</div>
              <div className="wh">{when(p.event.start_time)}</div>
            </div>
          </div>
          <Link className="small-link" to={`/data/events.event/${p.event.id}`} style={{ marginTop: 8, display: 'inline-block' }}>Open the event record</Link>
        </div>
      </div>
      {p.status === 'in_review' && (
        <div className="row-gap actions">
          <button type="button" className="btn" disabled={busy} onClick={() => act('approve')}><Icon name="check" />Approve</button>
          <NoteAction label="Send back" placeholder="What needs to change? The business sees this." onSubmit={(n) => act('reject', n)} />
        </div>
      )}
    </article>
  )
}
