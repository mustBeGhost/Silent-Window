import { minuteLabel } from '../utils/clinical'
export default function HandoverCards({items,user,minute,busy,onAction}) {
  return items.map(item=><article className="clinical-block" key={`${item.id}:${item.event_id}`}>
    <h3>{item.patient_id} | Handover #{item.id} | {item.status}</h3><p>{item.sender} to {item.recipient} ({item.staff_role})</p><p>{item.summary}</p><p className="panel-footnote">Recorded {minuteLabel(item.minute)} | saved {new Date(item.created_at*1000).toLocaleString()}</p>
    <details><summary>Pending tasks captured when offered ({item.tasks.count})</summary><ul>{item.tasks.items.map(task=><li key={task.entry_id}>{task.action} | next review: {task.review_minute==null?'not scheduled':minuteLabel(task.review_minute)}</li>)}</ul>{item.tasks.truncated&&<p>The snapshot was limited. Review the full follow-up list after accepting.</p>}</details>
    {item.status_note&&<p>{item.status_author}: {item.status_note} | recorded {minuteLabel(item.status_minute)} | saved {new Date(item.status_saved_at*1000).toLocaleString()}</p>}
    {item.status==='pending'&&(item.to_id===user.id||item.from_id===user.id||user.role==='coordinator')&&<form className="account-form clinical-form" onSubmit={event=>{event.preventDefault();const values=new FormData(event.currentTarget);onAction(item,{status:values.get('status'),content:values.get('content'),minute:Number(values.get('minute')),as_of_minutes:minute,expected_event_id:item.event_id})}}>
      <label>Action<select name="status">{item.to_id===user.id&&<><option value="accepted">Accept handover and take assignment</option><option value="declined">Decline handover</option></>}{(item.from_id===user.id||user.role==='coordinator')&&<option value="cancelled">Cancel handover</option>}</select></label>
      <label>Recorded action minute<input name="minute" type="number" min={item.minute} max={minute} defaultValue={minute} required/></label><label>Handover action note<textarea name="content" required minLength={2} maxLength={2000}/></label><p>Accepting transfers this staff assignment now. Set yourself On duty first. Other doctors and nurses remain assigned.</p><button className="action-button" disabled={busy}>Save handover action</button>
    </form>}
  </article>)
}
