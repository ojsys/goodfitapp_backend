import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Loading, toast, useAccount, useLoad } from '../App.jsx'

export default function Billing() {
  const a = useAccount()
  const [d, err, retry] = useLoad(`a/${a.id}/billing/`, [a.id])
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    if (q.get('card') === 'saved') toast('Card saved. You’re only charged once an event is approved.')
    if (q.get('partner') === 'started') toast('Welcome to the Partner plan.')
  }, [])
  if (!d) return <Loading err={err} retry={retry} />
  const go = async (kind) => {
    setBusy(true)
    try {
      const r = await api(`a/${a.id}/billing/${kind}/`, { method: 'POST', body: { return_url: window.location.href.split('?')[0] } })
      window.location.assign(r.url)
    } catch (e) {
      toast(e.message)
      setBusy(false)
    }
  }
  return (
    <>
      <div><div className="kicker">{a.name}</div><h1>Billing</h1></div>
      {d.is_house ? (
        <div className="card"><h2>House account</h2><p className="sub" style={{ fontSize: 15 }}>GoodCo runs A Good Fit: no billing, and featured events are free.</p></div>
      ) : (
        <div className="cols">
          <div className="wide">
            <div className="card">
              <h2 style={{ fontSize: 20 }}>Partner plan</h2>
              <p className="sub" style={{ fontSize: 15, lineHeight: 1.5 }}>
                {d.plan.partner ? `${d.plan.status}${d.plan.renews ? ` · Renews ${d.plan.renews}` : ''}`
                  : `${d.plan.price}: up to 4 featured events a month on Events, Home and the Community hub, start and run a club, plus a monthly report.`}
              </p>
              {d.stripe ? (
                <button type="button" className="btn sm" style={{ marginTop: 14 }} disabled={busy}
                  onClick={() => go(d.plan.partner ? 'manage' : 'partner')}>
                  {d.plan.partner ? 'Manage plan and invoices' : 'Start the Partner plan'}
                </button>
              ) : <p className="sub" style={{ marginTop: 10 }}>Write to partners@agoodfit.app to start the Partner plan.</p>}
            </div>
            <div className="card flush">
              <div className="pad"><h2 style={{ fontSize: 20 }}>Charges</h2><p className="sub">Featured events are charged once approved.</p></div>
              {d.charges.length === 0 ? <div className="empty">No charges yet.</div> : (
                <table>
                  <thead><tr><th>Event</th><th>Package</th><th>Approved</th><th>Amount</th><th>Payment</th></tr></thead>
                  <tbody>{d.charges.map((c, i) => (
                    <tr key={i}><td className="t">{c.title}</td><td>{c.package}</td><td>{c.when}</td><td className="num">{c.amount}</td><td className="note">{c.payment}</td></tr>
                  ))}</tbody>
                </table>
              )}
            </div>
          </div>
          <div className="narrow">
            <div className="card">
              <h2 style={{ fontSize: 20 }}>Card on file</h2>
              {!d.stripe ? <p className="sub" style={{ fontSize: 14.5, lineHeight: 1.5 }}>Online billing isn’t switched on yet. Featured events are approved without a charge for now.</p>
                : d.card ? <p style={{ marginTop: 8, fontSize: 15 }}>{d.card.brand} ending {d.card.last4} · expires {d.card.expires}</p>
                  : <p className="sub" style={{ fontSize: 14.5 }}>No card yet. You’re only charged once an event is approved.</p>}
              {d.stripe && (
                <button type="button" className="btn ghost sm" style={{ marginTop: 14 }} disabled={busy} onClick={() => go('card')}>
                  {d.card ? 'Replace card' : 'Add a card'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
