import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ago, when } from '../api.js'
import { Loading, NoteAction, Tabs, toast, useLoad, useSession } from '../App.jsx'
import Icon from '../../icons.jsx'

export default function Businesses() {
  const s = useSession()
  const [tab, setTab] = useState('pending')
  const [d, err, retry] = useLoad(`businesses/?status=${tab}`)
  const c = (d && d.counts) || {}
  useEffect(() => { if (d) s.setCounts((x) => ({ ...x, businesses: c.pending || 0 })) }, [d]) // eslint-disable-line
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">Business</div>
          <h1>Businesses</h1>
          <p className="sub">Verify that each business is real (website, address, a work email on its domain) before its featured events can run.</p>
        </div>
      </div>
      <Tabs label="Verification status" value={tab} onChange={setTab} items={[
        ['pending', 'To verify', c.pending || 0], ['verified', 'Verified', c.verified || 0], ['rejected', 'Not approved', c.rejected || 0]]} />
      {!d ? <Loading err={err} retry={retry} /> : d.items.length === 0
        ? <div className="card empty">{tab === 'pending' ? 'No businesses waiting.' : 'None here.'}</div>
        : d.items.map((a) => <Business key={a.id} a={a} done={retry} />)}
    </>
  )
}

function Business({ a, done }) {
  const [busy, setBusy] = useState(false)
  const act = async (action, note) => {
    setBusy(true)
    try {
      await api(`businesses/${a.id}/${action}/`, { method: 'POST', body: { note } })
      toast(action === 'verify' ? `${a.name} is verified. We emailed them.` : `${a.name} wasn’t approved. We emailed them.`)
      done()
    } catch (e) {
      toast(e.message)
    } finally {
      setBusy(false)
    }
  }
  const site = a.website && (a.website.startsWith('http') ? a.website : `https://${a.website}`)
  return (
    <article className="card qcard">
      <div className="qhead">
        <span className="tile">{a.name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()}</span>
        <h2><Link to={`/data/business.businessaccount/${a.id}`}>{a.name}</Link></h2>
        <span className={`pill ${a.status === 'verified' ? 'active' : a.status}`}>{a.status_label}</span>
        <span className="grow" />
        <span className="when">Signed up {ago(a.created_at)}</span>
      </div>
      <div className="kv">
        <div><span>Category</span>{a.category}</div>
        <div><span>Address</span>{a.address || '—'}</div>
        <div><span>Website</span>{site ? <a href={site} target="_blank" rel="noreferrer noopener">{a.website} <Icon name="out" size={13} /></a> : '—'}</div>
        <div><span>Work email</span>{a.work_email || '—'}</div>
        <div><span>Team</span>{a.team.map((m) => `${m.name} (${m.role})`).join(', ') || '—'}</div>
        {a.verified_at && <div><span>Verified</span>{when(a.verified_at)}</div>}
      </div>
      {a.review_note && <div className="warn">Note: {a.review_note}</div>}
      {a.status === 'pending' && (
        <div className="row-gap actions">
          <button type="button" className="btn" disabled={busy} onClick={() => act('verify')}><Icon name="check" />Verify</button>
          <NoteAction label="Don’t approve" placeholder="Why? The business gets this by email." onSubmit={(n) => act('reject', n)} danger />
        </div>
      )}
    </article>
  )
}
