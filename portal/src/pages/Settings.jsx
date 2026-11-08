import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Loading, toast, useAccount, useLoad, useSession } from '../App.jsx'

export default function Settings() {
  const a = useAccount()
  const s = useSession()
  const [d, err, retry] = useLoad(`a/${a.id}/settings/`, [a.id])
  const [f, setF] = useState(null)
  useEffect(() => { if (d) setF(d) }, [d])
  if (!f) return <Loading err={err} retry={retry} />
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const save = async (e) => {
    e.preventDefault()
    try {
      setF(await api(`a/${a.id}/settings/`, { method: 'PATCH', body: f }))
      await s.reload()
      toast('Saved')
    } catch (e2) {
      toast(e2.message)
    }
  }
  const ro = !f.can_edit
  return (
    <>
      <div><div className="kicker">{a.name}</div><h1>Settings</h1></div>
      {f.status === 'pending' && <div className="warn">We’re verifying your business. That usually takes 1 business day.</div>}
      {f.status === 'rejected' && <div className="warn">We couldn’t verify your business{f.review_note ? `: ${f.review_note}` : '.'} Write to partners@agoodfit.app.</div>}
      <form className="card" style={{ maxWidth: 680, display: 'flex', flexDirection: 'column', gap: 14 }} onSubmit={save}>
        <div className="field"><label htmlFor="st-name">Business name</label>
          <input id="st-name" className="input" value={f.name} onChange={set('name')} disabled={ro} /></div>
        <div className="field"><label htmlFor="st-cat">Category</label>
          <select id="st-cat" className="input" value={f.category} onChange={set('category')} disabled={ro}>
            {(s.categories || []).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></div>
        <div className="field"><label htmlFor="st-addr">Address</label>
          <input id="st-addr" className="input" value={f.address} onChange={set('address')} disabled={ro} /></div>
        <div className="row">
          <div className="field"><label htmlFor="st-web">Website or Instagram</label>
            <input id="st-web" className="input" value={f.website} onChange={set('website')} disabled={ro} /></div>
          <div className="field"><label htmlFor="st-email">Work email</label>
            <input id="st-email" className="input" type="email" value={f.work_email} onChange={set('work_email')} disabled={ro} /></div>
        </div>
        {!ro && <div><button type="submit" className="btn">Save</button></div>}
        <p className="sub">Signed in as {s.user.email}.</p>
      </form>
    </>
  )
}
