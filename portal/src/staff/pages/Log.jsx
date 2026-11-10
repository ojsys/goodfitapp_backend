import { useState } from 'react'
import { ago, when } from '../api.js'
import { Loading, useLoad } from '../App.jsx'
import { LogTarget } from './Overview.jsx'

export default function Log() {
  const [page, setPage] = useState(1)
  const [d, err, retry] = useLoad(`log/?page=${page}`)
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">Audit trail</div>
          <h1>Change history</h1>
          <p className="sub">Every change made by staff, here or in the Django admin.</p>
        </div>
      </div>
      {!d ? <Loading err={err} retry={retry} /> : (
        <div className="card flush scroll-x">
          <table className="data">
            <thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">What</th><th scope="col">Details</th></tr></thead>
            <tbody>
              {d.items.map((e) => (
                <tr key={e.id}>
                  <td className="when" title={when(e.when)}>{ago(e.when)}</td>
                  <td>{e.by}</td>
                  <td><span className={`pill sm ${e.action === 'deleted' ? 'rejected' : e.action === 'added' ? 'active' : 'draft'}`}>{e.action}</span>{' '}
                    {e.model_name} <LogTarget e={e} /></td>
                  <td className="note">{e.message}</td>
                </tr>
              ))}
              {d.items.length === 0 && <tr><td colSpan={4} className="empty">No changes yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {d && d.pages > 1 && (
        <div className="pager">
          <button type="button" className="btn ghost sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {d.page} of {d.pages}</span>
          <button type="button" className="btn ghost sm" disabled={page >= d.pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </>
  )
}
