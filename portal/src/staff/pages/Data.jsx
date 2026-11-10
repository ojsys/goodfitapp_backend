import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ago, api, fmt, qs, when } from '../api.js'
import { Loading, toast, useLoad, useSession } from '../App.jsx'
import Icon from '../../icons.jsx'

// ------------------------------------------------------------------ values

function Val({ f, v, short }) {
  if (v === null || v === undefined || v === '') return <span className="nil">—</span>
  if (typeof v === 'object' && v.hidden) {
    return <span className="hid" title={v.hidden === 'private' ? 'Private conversation: admins only' : 'Never shown'}>
      <Icon name="lock" size={13} />{v.hidden === 'private' ? 'Private' : 'Hidden'}</span>
  }
  switch (f.type) {
    case 'fk':
      return <Link to={`/data/${v.model}/${v.id}`}>{v.label}</Link>
    case 'bool':
      return <span className={`yn ${v ? 'y' : 'n'}`}>{v ? 'Yes' : 'No'}</span>
    case 'datetime':
      return <span title={v}>{short ? ago(v) : when(v)}</span>
    case 'date':
      return when(v, { time: false })
    case 'choice': {
      const c = (f.choices || []).find(([k]) => k === String(v))
      return <span className="pill plain sm">{c ? c[1] : String(v)}</span>
    }
    case 'number':
      return <span className="num">{typeof v === 'number' ? fmt(Math.round(v * 100) / 100) : v}</span>
    case 'json': {
      const s = JSON.stringify(v, null, short ? 0 : 2)
      return short ? <code className="clip">{s.length > 60 ? `${s.slice(0, 59)}…` : s}</code> : <pre className="json">{s}</pre>
    }
    case 'file':
      return <a href={v} target="_blank" rel="noreferrer noopener">Open file <Icon name="out" size={13} /></a>
    default: {
      const s = String(v)
      if (short && s.length > 80) return <span title={s}>{s.slice(0, 79)}…</span>
      return f.type === 'text' && !short ? <span className="pre">{s}</span> : s
    }
  }
}

// ------------------------------------------------------------------ index

export function DataIndex() {
  const [d, err, retry] = useLoad('models/')
  const [q, setQ] = useState('')
  const groups = useMemo(() => {
    if (!d) return []
    const t = q.trim().toLowerCase()
    return d.apps.map((g) => ({ ...g, models: g.models.filter((m) => !t || m.name.toLowerCase().includes(t) || g.label.toLowerCase().includes(t)) }))
      .filter((g) => g.models.length)
  }, [d, q])
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">Everything in the app</div>
          <h1>All data</h1>
          <p className="sub">Every table, with search, filters and edit history. What you can change follows your role.</p>
        </div>
      </div>
      <div className="search">
        <Icon name="search" size={18} />
        <input className="input" placeholder="Find a table (members, events, reports…)" aria-label="Find a table"
          value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {!d ? <Loading err={err} retry={retry} /> : (
        <div className="appgrid">
          {groups.map((g) => (
            <section key={g.app} className="card appcard" aria-labelledby={`g-${g.app}`}>
              <h2 id={`g-${g.app}`}>{g.label}</h2>
              <ul>
                {g.models.map((m) => (
                  <li key={m.key}>
                    <Link to={`/data/${m.key}`}>{m.name}</Link>
                    <span className="num">{fmt(m.count)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {groups.length === 0 && <div className="card empty">No tables match “{q}”.</div>}
        </div>
      )}
    </>
  )
}

// ------------------------------------------------------------------- list

export function DataList() {
  const { model } = useParams()
  const [sp, setSp] = useSearchParams()
  const params = Object.fromEntries(sp.entries())
  const [d, err, retry] = useLoad(`models/${model}/${qs(params)}`)
  const [q, setQ] = useState(params.q || '')
  useEffect(() => { setQ(params.q || '') }, [model]) // eslint-disable-line
  const set = (patch) => {
    const next = { ...params, ...patch }
    if (!('page' in patch)) delete next.page
    Object.keys(next).forEach((k) => { if (next[k] === '' || next[k] === null) delete next[k] })
    setSp(next)
  }
  const sort = (name) => set({ order: params.order === name ? `-${name}` : name })
  const filtered = Object.keys(params).filter((k) => k.startsWith('f_'))

  return (
    <>
      <div className="head">
        <div>
          <Link to="/data" className="back"><Icon name="back" size={16} />All data</Link>
          <h1>{d ? d.model.name : '…'}</h1>
          {d && <p className="sub">{d.model.app_label} · {fmt(d.total)} record{d.total === 1 ? '' : 's'}{filtered.length ? ' matching the filters' : ''}</p>}
        </div>
        {d && d.model.perms.add && <Link to={`/data/${model}/new`} className="btn"><Icon name="plus" />New {d.model.single.toLowerCase()}</Link>}
      </div>
      <div className="toolbar">
        {(!d || d.searchable) && (
          <form className="search" onSubmit={(e) => { e.preventDefault(); set({ q }) }}>
            <Icon name="search" size={18} />
            <input className="input" placeholder="Search" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
        )}
        {d && d.filters.map((f) => (
          <select key={f.name} className="input sel" aria-label={f.label} value={params[`f_${f.name}`] || ''}
            onChange={(e) => set({ [`f_${f.name}`]: e.target.value })}>
            <option value="">{f.label}: all</option>
            {f.choices.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        ))}
        {filtered.filter((k) => !(d && d.filters.some((f) => `f_${f.name}` === k))).map((k) => (
          <button key={k} type="button" className="chip on-chip" onClick={() => set({ [k]: '' })}
            aria-label={`Remove filter ${k.slice(2)}`}>{k.slice(2).replace(/_/g, ' ')} = {params[k]} ✕</button>
        ))}
        {(filtered.length > 0 || params.q) && <button type="button" className="link muted" onClick={() => { setQ(''); setSp({}) }}>Clear</button>}
      </div>
      {!d ? <Loading err={err} retry={retry} /> : (
        <div className="card flush scroll-x">
          <table className="data">
            <thead>
              <tr>
                {d.columns.map((c) => (
                  <th key={c.name} scope="col" aria-sort={params.order === c.name ? 'ascending' : params.order === `-${c.name}` ? 'descending' : 'none'}>
                    {c.hidden ? c.label : (
                      <button type="button" className="th" onClick={() => sort(c.name)}>
                        {c.label}{params.order === c.name ? ' ↑' : params.order === `-${c.name}` ? ' ↓' : ''}
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.pk}>
                  {d.columns.map((c, i) => (
                    <td key={c.name}>
                      {i === 0
                        ? <Link to={`/data/${model}/${r.pk}`} className="rowlink" aria-label={`Open ${r.label}`}>#{r.pk}</Link>
                        : i === 1 && c.type !== 'fk'
                          ? <Link to={`/data/${model}/${r.pk}`} className="plainlink"><Val f={c} v={r.cells[c.name]} short /></Link>
                          : <Val f={c} v={r.cells[c.name]} short />}
                    </td>
                  ))}
                </tr>
              ))}
              {d.rows.length === 0 && <tr><td colSpan={d.columns.length} className="empty">Nothing here.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {d && d.pages > 1 && (
        <div className="pager">
          <button type="button" className="btn ghost sm" disabled={d.page <= 1} onClick={() => set({ page: d.page - 1 })}>Previous</button>
          <span>Page {d.page} of {d.pages}</span>
          <button type="button" className="btn ghost sm" disabled={d.page >= d.pages} onClick={() => set({ page: d.page + 1 })}>Next</button>
        </div>
      )}
    </>
  )
}

// ------------------------------------------------------------------ record

function toLocalInput(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

function FkPicker({ f, value, onChange, id }) {
  const [q, setQ] = useState('')
  const [items, setItems] = useState(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return undefined
    const t = setTimeout(() => {
      api(`models/${f.model}/options/${qs({ q })}`).then((r) => setItems(r.items)).catch(() => setItems([]))
    }, 200)
    return () => clearTimeout(t)
  }, [q, open, f.model])
  return (
    <div className="fk">
      <div className="row-gap">
        <span className="fk-cur">{value ? <><b>{value.label}</b> <span className="sub nomargin">#{value.id}</span></> : <span className="nil">None</span>}</span>
        <button type="button" className="link" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Close' : 'Change'}</button>
        {value && f.null && <button type="button" className="link muted" onClick={() => onChange(null)}>Clear</button>}
      </div>
      {open && (
        <div className="fk-pop">
          <input id={id} className="input" placeholder="Search by name, email or #id" value={q} autoFocus
            onChange={(e) => setQ(e.target.value)} />
          <ul role="listbox" aria-label={`Choose ${f.label}`}>
            {items === null && <li className="sub">Loading…</li>}
            {items && items.length === 0 && <li className="sub">No matches.</li>}
            {items && items.map((o) => (
              <li key={o.id}><button type="button" role="option" aria-selected={value && value.id === o.id}
                onClick={() => { onChange({ id: o.id, label: o.label, model: f.model }); setOpen(false) }}>
                {o.label} <span className="sub nomargin">#{o.id}</span></button></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Input({ f, value, onChange, error }) {
  const id = `f-${f.name}`
  let el
  switch (f.type) {
    case 'bool':
      el = (
        <button id={id} type="button" role="switch" aria-checked={!!value} className={`switch${value ? ' on' : ''}`}
          onClick={() => onChange(!value)}><i /></button>
      )
      break
    case 'choice':
      el = (
        <select id={id} className="input" value={value === null || value === undefined ? '' : String(value)}
          onChange={(e) => onChange(e.target.value)}>
          {(f.blank || f.null) && <option value="">—</option>}
          {f.choices.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      )
      break
    case 'fk':
      el = <FkPicker f={f} id={id} value={value} onChange={onChange} />
      break
    case 'text':
      el = <textarea id={id} className="input" rows={4} value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
      break
    case 'json':
      el = <textarea id={id} className="input mono" rows={5} value={typeof value === 'string' ? value : JSON.stringify(value ?? null, null, 2)}
        onChange={(e) => onChange(e.target.value)} />
      break
    case 'datetime':
      el = <input id={id} className="input" type="datetime-local" value={toLocalInput(value)}
        onChange={(e) => onChange(e.target.value ? new Date(e.target.value).toISOString() : null)} />
      break
    case 'date':
      el = <input id={id} className="input" type="date" value={value ?? ''} onChange={(e) => onChange(e.target.value || null)} />
      break
    case 'number':
      el = <input id={id} className="input" type="number" step="any" value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)} />
      break
    default:
      el = <input id={id} className="input" value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
  }
  return (
    <div className={`field${error ? ' bad' : ''}`}>
      <label htmlFor={id}>{f.label}{!f.blank && f.type !== 'bool' ? ' *' : ''}</label>
      {el}
      {f.help && <span className="help">{f.help}</span>}
      {error && <span className="err" role="alert">{error.join(' ')}</span>}
    </div>
  )
}

export function DataRecord({ create = false }) {
  const { model, pk } = useParams()
  const nav = useNavigate()
  const s = useSession()
  const path = create ? `models/${model}/?schema=1` : `models/${model}/${pk}/`
  const [d, err, retry, setD] = useLoad(path)
  const [edit, setEdit] = useState(create)
  const [draft, setDraft] = useState({})
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [del, setDel] = useState(null)
  useEffect(() => { setEdit(create); setDraft({}); setErrors({}); setDel(null) }, [model, pk, create])

  if (!d) return <Loading err={err} retry={retry} />
  const fields = d.fields
  const editable = fields.filter((f) => f.editable)
  const val = (f) => (f.name in draft ? draft[f.name] : f.value)

  const save = async () => {
    setBusy(true)
    setErrors({})
    const body = {}
    Object.entries(draft).forEach(([k, v]) => {
      body[k] = v && typeof v === 'object' && 'id' in v ? v.id : v
    })
    try {
      const r = create
        ? await api(`models/${model}/`, { method: 'POST', body })
        : await api(`models/${model}/${pk}/`, { method: 'PATCH', body })
      toast(create ? 'Created.' : 'Saved.')
      if (create) nav(`/data/${model}/${r.pk}`, { replace: true })
      else { setD(r); setEdit(false); setDraft({}) }
    } catch (e) {
      if (e.data && e.data.errors) setErrors(e.data.errors)
      toast(e.message)
    } finally {
      setBusy(false)
    }
  }
  const askDelete = async () => {
    try {
      const r = await api(`models/${model}/${pk}/?delete_preview=1`)
      setDel(r.delete_preview ? { items: r.delete_preview } : { blocked: r.delete_blocked || 'Other records depend on this one.' })
    } catch (e) {
      toast(e.message)
    }
  }
  const doDelete = async () => {
    setBusy(true)
    try {
      await api(`models/${model}/${pk}/`, { method: 'DELETE' })
      toast('Deleted.')
      nav(`/data/${model}`, { replace: true })
    } catch (e) {
      toast(e.message)
      setBusy(false)
    }
  }

  return (
    <>
      <div className="head">
        <div>
          <Link to={`/data/${model}`} className="back"><Icon name="back" size={16} />{d.model.name}</Link>
          <h1>{create ? `New ${d.model.single.toLowerCase()}` : d.label}</h1>
          {!create && <p className="sub">{d.model.single} #{d.pk}</p>}
        </div>
        {!create && !edit && (
          <div className="row-gap">
            {d.model.perms.change && editable.length > 0 && <button type="button" className="btn" onClick={() => setEdit(true)}><Icon name="edit" />Edit</button>}
            {d.model.perms.delete && <button type="button" className="btn ghost danger-t" onClick={askDelete}><Icon name="trash" />Delete</button>}
          </div>
        )}
      </div>

      {del && (
        <div className="card danger-card" role="alertdialog" aria-labelledby="del-h">
          <h2 id="del-h">Delete {d.label}?</h2>
          {del.blocked ? <p className="sub">{del.blocked}</p> : (
            <>
              <p className="sub">This can’t be undone. It also deletes:</p>
              <ul className="dellist">{del.items.map((i) => <li key={i.name}><b>{fmt(i.count)}</b> {i.name.toLowerCase()}</li>)}</ul>
            </>
          )}
          <div className="row-gap">
            {!del.blocked && <button type="button" className="btn danger" disabled={busy} onClick={doDelete}>Delete permanently</button>}
            <button type="button" className="btn ghost" onClick={() => setDel(null)}>Cancel</button>
          </div>
        </div>
      )}

      {d.member && <MemberPanel d={d} onChange={setD} me={s.user} />}

      <div className="cols">
        <div className="wide">
          <div className="card">
            {edit ? (
              <>
                <div className="formgrid">
                  {editable.map((f) => (
                    <Input key={f.name} f={f} value={val(f)} error={errors[f.name]}
                      onChange={(v) => setDraft((x) => ({ ...x, [f.name]: v }))} />
                  ))}
                </div>
                {errors.__all__ && <p className="err">{errors.__all__.join(' ')}</p>}
                <div className="row-gap actions">
                  <button type="button" className="btn" disabled={busy || (!create && !Object.keys(draft).length)} onClick={save}>
                    {busy ? 'Saving…' : create ? 'Create' : 'Save changes'}
                  </button>
                  <button type="button" className="btn ghost" onClick={() => (create ? nav(-1) : (setEdit(false), setDraft({}), setErrors({})))}>Cancel</button>
                </div>
              </>
            ) : (
              <dl className="fields">
                {fields.map((f) => (
                  <div key={f.name} className={f.type === 'json' || f.type === 'text' ? 'full' : ''}>
                    <dt>{f.label}</dt>
                    <dd><Val f={f} v={f.value} /></dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </div>
        {!create && (
          <div className="narrow">
            {d.related.length > 0 && (
              <div className="card">
                <h2>Linked records</h2>
                <ul className="rel">
                  {d.related.map((r) => (
                    <li key={`${r.model}-${r.field}`}>
                      <Link to={`/data/${r.model}?f_${r.field}=${d.pk}`}>{r.name}</Link>
                      <span className="sub nomargin">{r.via}</span>
                      <span className="num">{fmt(r.count)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="card">
              <h2>History</h2>
              {d.history.length === 0 && <p className="sub">No changes recorded yet.</p>}
              {d.history.map((e) => (
                <div className="logrow" key={e.id}>
                  <span className="avatar sm">{e.by.slice(0, 1).toUpperCase()}</span>
                  <div>
                    <div><b>{e.by}</b> {e.action}</div>
                    {e.message && <div className="when">{e.message}</div>}
                    <div className="when">{when(e.when)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  )
}

function MemberPanel({ d, onChange, me }) {
  const m = d.member
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const self = String(d.pk) === String(me.id)
  const act = async (action) => {
    setBusy(true)
    try {
      onChange(await api(`members/${d.pk}/${action}/`, { method: 'POST', body: { note } }))
      setNote('')
      toast(action === 'suspend' ? 'Suspended. They’re signed out and can’t sign in.' : 'Reinstated.')
    } catch (e) {
      toast(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card member">
      <div className="stats">
        <div className="mini"><span>Account</span><b className={m.active ? 'ok' : 'bad'}>{m.active ? 'Active' : 'Suspended'}</b></div>
        <div className="mini"><span>Plan</span><b>{m.plan === 'plus' ? 'Plus' : 'Free'}</b></div>
        <div className="mini"><span>Role</span><b>{m.role === 'admin' ? 'Admin' : m.role === 'staff' ? 'Staff' : 'Member'}</b></div>
        <div className="mini"><span>Activities</span><b>{fmt(m.activities)}</b></div>
        <div className="mini"><span>Reports about them</span><b>{fmt(m.reports_about)}{m.open_reports ? ` (${m.open_reports} open)` : ''}</b></div>
      </div>
      {!self && (!m.role || me.role === 'admin') && (
        <div className="row-gap actions">
          <input className="input" placeholder="Note for the record (optional)" aria-label="Moderation note" value={note}
            onChange={(e) => setNote(e.target.value)} />
          {m.active
            ? <button type="button" className="btn danger" disabled={busy} onClick={() => act('suspend')}>Suspend</button>
            : <button type="button" className="btn" disabled={busy} onClick={() => act('reinstate')}>Reinstate</button>}
        </div>
      )}
      {m.actions.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="label13">Moderation history</div>
          {m.actions.map((a, i) => (
            <div className="logrow" key={i}>
              <div><b>{a.kind}</b> by {a.by} · {when(a.when)}{a.note ? <div className="when">{a.note}</div> : null}</div>
            </div>
          ))}
        </div>
      )}
      {m.open_reports > 0 && <Link className="small-link" to="/reports">See open reports</Link>}
    </div>
  )
}
