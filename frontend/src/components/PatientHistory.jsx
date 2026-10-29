import { useEffect, useState } from 'react'
import { requestJson } from '../services/api'
import { historyFields } from '../utils/history'
import { minuteLabel } from '../utils/clinical'
const KINDS = ['all','visit','assessment','recommendation','follow_up','handover','escalation','context','follow_up_status','doctor_review_status','model_review','vital_limits','shift_handover','doctor_review_request']
export default function PatientHistory({ patientId, minute }) {
  const [filters,setFilters]=useState({search:'',kind:'all',author_id:'',minute_from:'0',saved_after:'',saved_before:''})
  const [authors,setAuthors]=useState([]),[offset,setOffset]=useState(0),[revision,setRevision]=useState(0),[data,setData]=useState(null),[error,setError]=useState(null)
  useEffect(()=>{ const change=()=>setRevision(v=>v+1);window.addEventListener('silent-window-workspace-refresh',change);return()=>window.removeEventListener('silent-window-workspace-refresh',change) },[])
  useEffect(()=>{
    const controller=new AbortController();setError(null);setData(null)
    const params=new URLSearchParams({as_of_minutes:String(minute),offset:String(offset),limit:'25'})
    for(const [key,value] of Object.entries(filters)) if(value!=='') params.set(key,key.startsWith('saved_')?String(new Date(value).getTime()/1000):value)
    requestJson(`/patients/${encodeURIComponent(patientId)}/history?${params}`,{signal:controller.signal}).then(value=>{if(!controller.signal.aborted){setData(value);setAuthors(value.authors)}}).catch(failure=>{if(!controller.signal.aborted)setError(failure.message)})
    return()=>controller.abort()
  },[patientId,minute,filters,offset,revision])
  return <section id="patient-history-search" className="panel"><h2>Search staff history</h2><p>Search all saved staff records through recorded {minuteLabel(minute)}, including older entries outside the short timeline.</p>
    <form className="shift-toolbar" onSubmit={event=>{event.preventDefault();setOffset(0);setFilters(Object.fromEntries(new FormData(event.currentTarget)))}}>
      <label>Search notes or staff name<input name="search" maxLength={100} defaultValue={filters.search}/></label><label>Entry type<select name="kind" defaultValue={filters.kind}>{KINDS.map(kind=><option key={kind} value={kind}>{kind.replaceAll('_',' ')}</option>)}</select></label>
      <label>Staff author<select name="author_id" defaultValue={filters.author_id}><option value="">All authors</option>{authors.map(author=><option key={author.id} value={author.id}>{author.display_name}</option>)}</select></label>
      <label>From recorded minute<input type="number" name="minute_from" min="0" max={minute} defaultValue={filters.minute_from}/></label><label>Saved after (local time)<input type="datetime-local" name="saved_after" defaultValue={filters.saved_after}/></label><label>Saved before (local time)<input type="datetime-local" name="saved_before" defaultValue={filters.saved_before}/></label><button className="action-button">Search history</button>
    </form>{error&&<p role="alert">{error}</p>}{!data&&!error&&<p role="status">Loading staff history...</p>}
    {data&&<><p>{data.total} matching records</p>{data.items.map(item=><article className="clinical-block" key={`${item.source}:${item.id}`}><strong>{item.kind.replaceAll('_',' ')} | {item.author} | recorded {minuteLabel(item.minute)}</strong><p className="panel-footnote">Saved {new Date(item.created_at*1000).toLocaleString()}</p>{historyFields(item).map(field=><p key={field.label}><strong>{field.label}: </strong>{field.value}</p>)}</article>)}<button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous history</button><button disabled={offset+25>=data.total} onClick={()=>setOffset(offset+25)}>Next history</button></>}
  </section>
}
