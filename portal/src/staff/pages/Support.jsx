import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ago, when } from '../api.js'
import { Loading, Tabs, toast, useLoad, useSession } from '../App.jsx'

export default function Support() {
  const s = useSession()
  const [tab, setTab] = useState('open')
  const [d, err, retry] = useLoad(`support/?handled=${tab === 'handled'}`)
  useEffect(() => { if (d) s.setCounts((x) => ({ ...x, support: d.open })) }, [d]) // eslint-disable-line
  const mark = async (m, handled) => {
    try {
      await api(`support/${m.id}/`, { method: 'POST', body: { handled } })
      toast(handled ? 'Marked handled.' : 'Moved back to open.')
      retry()
    } catch (e) {
      toast(e.message)
    }
  }
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">Members</div>
          <h1>Support</h1>
          <p className="sub">Messages sent from Help in the app. Reply by email, then mark them handled.</p>
        </div>
      </div>
      <Tabs label="Support status" value={tab} onChange={setTab} items={[['open', 'Open', d ? d.open : undefined], ['handled', 'Handled']]} />
      {!d ? <Loading err={err} retry={retry} /> : d.items.length === 0
        ? <div className="card empty">{tab === 'open' ? 'No open messages.' : 'Nothing handled yet.'}</div>
        : d.items.map((m) => (
          <article key={m.id} className="card qcard">
            <div className="qhead">
              <span className={`pill ${m.safety ? 'rejected' : 'draft'}`}>{m.topic}</span>
              <h2>{m.user ? <Link to={`/data/users.user/${m.user.id}`}>{m.user.name}</Link> : 'Deleted account'}</h2>
              <span className="grow" />
              <span className="when" title={when(m.created_at)}>{ago(m.created_at)}</span>
            </div>
            <div className="quote pre">{m.text}</div>
            <div className="row-gap actions">
              {m.user && <a className="btn ghost sm" href={`mailto:${m.user.email}?subject=${encodeURIComponent('Your message to A Good Fit')}`}>Reply by email</a>}
              <button type="button" className="btn sm" onClick={() => mark(m, !m.handled)}>{m.handled ? 'Reopen' : 'Mark handled'}</button>
            </div>
          </article>
        ))}
    </>
  )
}
