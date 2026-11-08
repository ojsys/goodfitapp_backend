import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api.js'
import { Loading, toast, useAccount, useLoad } from '../App.jsx'
import Icon from '../icons.jsx'

const EMPTY = { title: '', date: '', time: '09:00', location: '', description: '', package: 'boost',
  neighborhoods: [], interests: [] }

function whenLine(date, time, location) {
  if (!date) return 'Pick a date'
  const d = new Date(`${date}T${time || '09:00'}`)
  const day = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  const t = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  const place = (location || '').split(',')[0]
  return [day, t, place].filter(Boolean).join(' · ')
}

export default function Feature() {
  const a = useAccount()
  const { pid } = useParams()
  const nav = useNavigate()
  const [opts, optsErr, retry] = useLoad(`a/${a.id}/options/`, [a.id])
  const [f, setF] = useState(EMPTY)
  const [id, setId] = useState(pid ? Number(pid) : null)
  const [status, setStatus] = useState('draft')
  const [note, setNote] = useState('')
  const [loaded, setLoaded] = useState(!pid)
  const [reach, setReach] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [done, setDone] = useState(false)
  const timer = useRef()

  useEffect(() => {
    if (!pid) return
    api(`a/${a.id}/featured/${pid}/`).then((d) => {
      setF({ title: d.title, date: d.date, time: d.time, location: d.location, description: d.description,
        package: d.package, neighborhoods: d.neighborhoods, interests: d.interests })
      setStatus(d.status)
      setNote(d.review_note)
      setLoaded(true)
    }).catch((e) => setErr({ message: e.message }))
  }, [a.id, pid])

  // Live reach estimate.
  useEffect(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      api(`a/${a.id}/reach/`, { method: 'POST', body: { neighborhoods: f.neighborhoods, interests: f.interests } })
        .then(setReach).catch(() => {})
    }, 250)
    return () => clearTimeout(timer.current)
  }, [a.id, f.neighborhoods, f.interests])

  const pkg = useMemo(() => opts?.packages.find((p) => p.id === f.package), [opts, f.package])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const toggle = (k, v) => setF({ ...f, [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v] })
  const ready = f.title.trim().length > 2 && f.date && f.time && f.location.trim()

  const save = async (submit) => {
    setBusy(true)
    setErr(null)
    try {
      const body = { ...f, submit, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }
      const d = id ? await api(`a/${a.id}/featured/${id}/`, { method: 'PATCH', body })
        : await api(`a/${a.id}/featured/`, { method: 'POST', body })
      setId(d.id)
      setStatus(d.status)
      if (!pid) nav(`/a/${a.id}/feature/${d.id}`, { replace: true })
      if (submit) setDone(true)
      else toast('Draft saved')
    } catch (e) {
      if (e.data?.draft) {
        setId(e.data.draft)
        nav(`/a/${a.id}/feature/${e.data.draft}`, { replace: true })
      }
      setErr({ code: e.code, message: e.message })
    } finally {
      setBusy(false)
    }
  }

  const stripe = async (kind) => {
    try {
      const r = await api(`a/${a.id}/billing/${kind}/`, { method: 'POST', body: { return_url: window.location.href } })
      window.location.assign(r.url)
    } catch (e) {
      setErr({ message: e.message })
    }
  }

  if (!opts || !loaded) return <Loading err={optsErr || (err && !loaded ? err : null)} retry={retry} />

  if (done) {
    return (
      <>
        <Link to={`/a/${a.id}/overview`} className="back"><Icon name="back" size={16} />Overview</Link>
        <div className="card" style={{ maxWidth: 620 }}>
          <div className="note-box" style={{ marginBottom: 14 }}><Icon name="check" />Submitted, in review</div>
          <h2 style={{ fontSize: 22 }}>{f.title}</h2>
          <p style={{ marginTop: 8, color: 'var(--ink-2)', lineHeight: 1.5 }}>
            We’ll email you when it’s approved, usually within 1 business day.
            {opts.is_house ? ' Featured events are free on the house account.' : ' You’re only charged once it’s approved.'}
          </p>
          <Link to={`/a/${a.id}/overview`} className="btn" style={{ marginTop: 18 }}>Back to Overview</Link>
        </div>
      </>
    )
  }

  const locked = status === 'approved'
  return (
    <>
      <div>
        <Link to={`/a/${a.id}/overview`} className="back"><Icon name="back" size={16} />Overview</Link>
        <h1>Feature an event</h1>
      </div>
      {status === 'rejected' && note && (
        <div className="warn" role="status">We couldn’t approve this yet: {note} Edit it and send it again.</div>
      )}
      {status === 'in_review' && <div className="okmsg">In review. Editing it moves it back to a draft until you send it again.</div>}
      {locked && <div className="okmsg">Approved. Contact us to change an approved event.</div>}
      <div className="cols">
        <div className="wide">
          <section className="card" aria-labelledby="s1">
            <div className="step"><i>1</i><h2 id="s1">Event details</h2></div>
            <div className="field">
              <label htmlFor="ev-name">Event name</label>
              <input id="ev-name" className="input" value={f.title} onChange={set('title')} placeholder="Pilates on the Pier" disabled={locked} />
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              <div className="field">
                <label htmlFor="ev-date">Date</label>
                <input id="ev-date" className="input" type="date" value={f.date} onChange={set('date')} disabled={locked} />
              </div>
              <div className="field">
                <label htmlFor="ev-time">Start time</label>
                <input id="ev-time" className="input" type="time" value={f.time} onChange={set('time')} disabled={locked} />
              </div>
              <div className="field" style={{ flex: 1.6 }}>
                <label htmlFor="ev-loc">Location</label>
                <input id="ev-loc" className="input" value={f.location} onChange={set('location')} placeholder="Pier 6, Brooklyn Bridge Park" disabled={locked} />
              </div>
            </div>
            <div className="field" style={{ marginTop: 14 }}>
              <label htmlFor="ev-desc">What to expect</label>
              <textarea id="ev-desc" className="input" value={f.description} onChange={set('description')}
                placeholder="A 50-minute mat Pilates class on the pier. All levels, mats provided." disabled={locked} />
            </div>
          </section>

          <section className="card" aria-labelledby="s2">
            <div className="step"><i>2</i><h2 id="s2">Who should see it</h2></div>
            <div className="lbl" style={{ color: 'var(--muted)', marginBottom: 10 }}>Neighborhoods</div>
            <div className="chips">
              {opts.neighborhoods.map((n) => (
                <button key={n} type="button" className="chip" aria-pressed={f.neighborhoods.includes(n)}
                  onClick={() => toggle('neighborhoods', n)} disabled={locked}>{n}</button>
              ))}
            </div>
            <div className="lbl" style={{ color: 'var(--muted)', margin: '18px 0 10px' }}>Interests</div>
            <div className="chips">
              {opts.interests.map(([k, label]) => (
                <button key={k} type="button" className="chip" aria-pressed={f.interests.includes(k)}
                  onClick={() => toggle('interests', k)} disabled={locked}>{label}</button>
              ))}
            </div>
            <div className="note-box" style={{ marginTop: 18 }} aria-live="polite">
              <Icon name="eye" />{reach ? reach.label : 'Estimating reach…'}
            </div>
            <p className="sub" style={{ marginTop: 8 }}>Targeting uses only neighborhood and the interests members chose. Leave a list empty to reach everyone nearby.</p>
          </section>

          <section className="card" aria-labelledby="s3">
            <div className="step"><i>3</i><h2 id="s3">Choose a package</h2></div>
            <div className="pkgs" role="radiogroup" aria-labelledby="s3">
              {opts.packages.map((p) => (
                <button key={p.id} type="button" role="radio" className="pkg" aria-checked={f.package === p.id}
                  onClick={() => setF({ ...f, package: p.id })} disabled={locked}>
                  <span className="nm">{p.name}</span>
                  <span className="pr">{p.price_label}</span>
                  <span className="ln">{p.line}</span>
                  <span className="dt">{p.detail}</span>
                </button>
              ))}
            </div>
            <p className="sub" style={{ marginTop: 12 }}>
              {opts.is_house ? 'Featured events are free on the house account. ' : ''}
              {f.package === 'partner' && opts.partner && !opts.is_house
                ? `${opts.partner_used} of ${opts.partner_limit} Partner events used this month. ` : ''}
              Prices are placeholders while pricing is finalized.
            </p>
          </section>
        </div>

        <aside className="narrow">
          <div className="card">
            <div className="label13" style={{ marginBottom: 12 }}>How members will see it</div>
            <div className="preview" aria-label="Preview of the featured card in the app">
              <div className="cover"><span className="ft"><Icon name="star" size={13} stroke={2} />Featured</span></div>
              <div className="bd">
                <div className="tt">{f.title || 'Your event name'}</div>
                <div className="hb">Hosted by {opts.business}{opts.verified ? ' · Verified business' : ''}</div>
                <div className="wh">{whenLine(f.date, f.time, f.location)}</div>
              </div>
            </div>
            <div style={{ borderTop: '1px solid var(--line-soft)', margin: '18px 0 10px' }} />
            <div className="sumrow"><span>Package</span><b>{pkg?.name}</b></div>
            <div className="sumrow"><span>Runs</span><b>{pkg ? `${pkg.days} days` : ''}</b></div>
            <div className="sumrow total"><span>Total</span><span>
              {opts.is_house ? 'Free' : f.package === 'partner' ? (opts.partner ? 'Included' : '$299/mo') : pkg?.price_label}
            </span></div>
            {err && (
              <div className="warn" role="alert" style={{ marginTop: 12 }}>
                {err.message}
                {err.code === 'card_required' && (
                  <div><button type="button" className="btn sm" style={{ marginTop: 10 }} onClick={() => stripe('card')}>Add a card</button></div>
                )}
                {err.code === 'partner_required' && (
                  opts.stripe
                    ? <div><button type="button" className="btn sm" style={{ marginTop: 10 }} onClick={() => stripe('partner')}>Start the Partner plan</button></div>
                    : <div style={{ marginTop: 6 }}>Write to partners@agoodfit.app and we’ll set it up.</div>
                )}
              </div>
            )}
            {!locked && (
              <>
                <button type="button" className="btn block" style={{ marginTop: 16 }} disabled={!ready || busy}
                  onClick={() => save(true)}>{busy ? 'Sending…' : 'Submit for review'}</button>
                <button type="button" className="link" style={{ width: '100%', marginTop: 4 }} disabled={!ready || busy}
                  onClick={() => save(false)}>Save draft</button>
              </>
            )}
            <p className="sub" style={{ marginTop: 6, lineHeight: 1.45 }}>
              {opts.is_house ? 'We review within 1 business day.' : 'You’re only charged once it’s approved. We review within 1 business day.'}
            </p>
          </div>
        </aside>
      </div>
    </>
  )
}
