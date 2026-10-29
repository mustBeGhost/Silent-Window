import { useState } from 'react'
import { API_BASE_URL } from '../services/api'
export default function PatientPdf({patientId,minute,modelProfile}) {
  const [busy,setBusy]=useState(false),[error,setError]=useState(null)
  async function download(){
    setBusy(true);setError(null)
    try{
      const response=await fetch(`${API_BASE_URL}/patients/${encodeURIComponent(patientId)}/summary.pdf?as_of_minutes=${minute}&model_profile=${modelProfile}`,{credentials:'include'})
      if(!response.ok){if(response.status===401)window.dispatchEvent(new Event('silent-window-session-ended'));throw new Error('The summary could not be downloaded. Check your access and retry.')}
      if(!response.headers.get('Content-Type')?.includes('application/pdf'))throw new Error('The server returned an unexpected document.')
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`${patientId}-research-summary.pdf`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
    }catch(failure){setError(failure.message)}finally{setBusy(false)}
  }
  return <div className="patient-export"><button className="secondary-button" disabled={busy} onClick={download}>{busy?'Preparing PDF...':'Download research PDF'}</button><span>Includes only this recorded view. Staff sections include up to 30 items each.</span>{error&&<p role="alert">{error}</p>}</div>
}
