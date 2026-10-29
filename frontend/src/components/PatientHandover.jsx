import { useEffect,useState } from 'react'
import { useAuth } from '../context/Auth'
import { requestJson } from '../services/api'
import HandoverCards from './HandoverCards'
export default function PatientHandover({patientId,minute}) {
  const {user}=useAuth();const [data,setData]=useState(null),[people,setPeople]=useState([]),[team,setTeam]=useState([]),[sender,setSender]=useState(''),[offset,setOffset]=useState(0),[revision,setRevision]=useState(0),[error,setError]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(null)
  useEffect(()=>{const refresh=()=>setRevision(v=>v+1);window.addEventListener('silent-window-workspace-refresh',refresh);return()=>window.removeEventListener('silent-window-workspace-refresh',refresh)},[])
  useEffect(()=>{
    const controller=new AbortController();setError(null)
    Promise.all([requestJson(`/handovers?status=all&patient_id=${encodeURIComponent(patientId)}&as_of_minutes=${minute}&offset=${offset}`,{signal:controller.signal}),requestJson('/staff/availability',{signal:controller.signal}),requestJson(`/patients/${encodeURIComponent(patientId)}/workflow?as_of_minutes=${minute}`,{signal:controller.signal})]).then(([value,staff,workflow])=>{if(!controller.signal.aborted){setData(value);setPeople(staff);setTeam(workflow.assignments)}}).catch(failure=>{if(!controller.signal.aborted){setError(failure.message);setData(null)}})
    return()=>controller.abort()
  },[patientId,minute,offset,revision,user.id])
  const sources=team.filter(person=>person.active&&(user.role==='coordinator'||person.id===user.id))
  const from=sources.find(person=>String(person.id)===sender)||sources[0]
  async function save(path,body){setBusy(true);setError(null);setMessage(null);try{await requestJson(path,{method:'POST',body});setMessage('Handover saved. Current assignments change only when the receiving person accepts.');setRevision(v=>v+1);window.dispatchEvent(new Event('silent-window-workflow-changed'));window.dispatchEvent(new Event('silent-window-workspace-refresh'))}catch(failure){setError(failure.message)}finally{setBusy(false)}}
  return <section id="patient-shift-handover" className="panel"><h2>Shift handover</h2><p>Offer a transfer to another person in the same role. The receiving person can see the offer in My Shift and must accept before assignments change.</p>{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    {['doctor','nurse','coordinator'].includes(user.role)&&from&&<details className="clinical-disclosure"><summary>Offer shift handover</summary><form className="account-form clinical-form" onSubmit={event=>{event.preventDefault();const values=new FormData(event.currentTarget);save(`/patients/${encodeURIComponent(patientId)}/handovers`,{from_id:from.id,to_id:Number(values.get('to_id')),minute:Number(values.get('minute')),as_of_minutes:minute,summary:values.get('summary')})}}>
      <label>Sending staff<select value={String(from.id)} onChange={event=>setSender(event.target.value)}>{sources.map(person=><option key={person.id} value={person.id}>{person.display_name} ({person.role})</option>)}</select></label><label>Receiving staff<select name="to_id" required defaultValue="" key={from.id}><option value="" disabled>Select receiving staff</option>{people.filter(person=>person.role===from.role&&person.id!==from.id&&!team.some(member=>member.id===person.id)).map(person=><option key={person.id} value={person.id}>{person.display_name} | {person.availability.status.replaceAll('_',' ')}</option>)}</select></label>
      <label>Recorded handover minute<input type="number" name="minute" min="0" max={minute} defaultValue={minute} required/></label><label>Handover summary<textarea name="summary" required minLength={2} maxLength={2000}/></label><p>Pending follow-ups at the entered minute are captured with this offer. Availability is current, not replayed.</p><button className="action-button" disabled={busy}>Offer handover</button>
    </form></details>}
    {!data&&!error&&<p role="status">Loading handovers...</p>}{data&&<><HandoverCards items={data.items} user={user} minute={minute} busy={busy} onAction={(item,body)=>save(`/handovers/${item.id}/status`,body)}/>{data.total===0&&<p>No visible handovers.</p>}<p>{data.total} handovers</p><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous handovers</button><button disabled={offset+25>=data.total} onClick={()=>setOffset(offset+25)}>Next handovers</button></>}
  </section>
}
