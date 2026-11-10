import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ago, api } from '../api.js'
import { Loading, toast, useLoad, useSession } from '../App.jsx'

export default function Team() {
  const s = useSession()
  const [d, err, retry] = useLoad('team/')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('staff')
  const [busy, setBusy] = useState(false)
  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await api('team/', { method: 'POST', body: { email, role } })
      toast(`${email} is now ${role === 'admin' ? 'an admin' : 'staff'}.`)
      setEmail('')
      retry()
    } catch (e2) {
      toast(e2.message)
    } finally {
      setBusy(false)
    }
  }
  const change = async (u, next) => {
    try {
      await api(`team/${u.id}/`, { method: 'PATCH', body: { role: next } })
      toast(next ? `${u.name} is now ${next === 'admin' ? 'an admin' : 'staff'}.` : `${u.name} was removed from the team.`)
      retry()
    } catch (e) {
      toast(e.message)
    }
  }
  return (
    <>
      <div className="head">
        <div>
          <div className="kicker">Access</div>
          <h1>Staff team</h1>
          <p className="sub"><b>Admins</b> can do everything: edit or delete any record, and manage the team. <b>Staff</b> can see everything except private conversations, work the review queues, and suspend or reinstate members.</p>
        </div>
      </div>
      {!d ? <Loading err={err} retry={retry} /> : (
        <>
          {d.can_manage && (
            <form className="card row-gap" onSubmit={add}>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="t-email">Add someone (they need an A Good Fit account)</label>
                <input id="t-email" className="input" type="email" placeholder="name@agoodfit.app" value={email}
                  onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="t-role">Role</label>
                <select id="t-role" className="input" value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="staff">Staff</option><option value="admin">Admin</option>
                </select>
              </div>
              <button type="submit" className="btn" style={{ alignSelf: 'flex-end' }} disabled={busy || !email}>Add to team</button>
            </form>
          )}
          <div className="card flush scroll-x">
            <table className="data">
              <thead><tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Last sign-in</th>{d.can_manage && <th scope="col"><span className="sr">Actions</span></th>}</tr></thead>
              <tbody>
                {d.items.map((u) => (
                  <tr key={u.id}>
                    <td className="t"><Link to={`/data/users.user/${u.id}`}>{u.name}</Link>{u.id === s.user.id && <span className="sub nomargin"> (you)</span>}</td>
                    <td>{u.email}</td>
                    <td><span className={`role ${u.role}`}>{u.role === 'admin' ? 'Admin' : 'Staff'}</span>{!u.active && <span className="pill rejected sm">Inactive</span>}</td>
                    <td className="when">{u.last_login ? ago(u.last_login) : 'Never'}</td>
                    {d.can_manage && (
                      <td className="right">
                        {u.id !== s.user.id && (
                          <>
                            <button type="button" className="link" onClick={() => change(u, u.role === 'admin' ? 'staff' : 'admin')}>
                              Make {u.role === 'admin' ? 'staff' : 'admin'}</button>
                            <button type="button" className="link muted" onClick={() => change(u, null)}>Remove</button>
                          </>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}
