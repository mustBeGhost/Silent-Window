import { VITAL_LABELS } from './clinical.js'
export function historyFields(item){
  let labels={content:'Note',plan:'Plan',follow_up:'Follow-up',escalation:'Escalation context'}
  if(item.source==='context')labels={content:'Condition summary',plan:'Reason for ICU admission',follow_up:'Admission diagnosis',escalation:'Consulting specialty'}
  else if(item.source==='model')labels={content:'Review note',plan:'Model profile',follow_up:'Assessment checkpoint',escalation:'Review action'}
  else if(item.source==='offer')labels={content:'Handover summary',plan:'Staff role'}
  else if(['follow','review','handover'].includes(item.source))labels={content:'Action note',plan:'Status'}
  else if(item.source==='limits'){
    try{return [{label:'Doctor-entered limits',value:JSON.parse(item.content).map(rule=>`${VITAL_LABELS[rule.parameter]||rule.parameter}: ${rule.lower??'no lower limit'} to ${rule.upper??'no upper limit'}`).join('; ')||'All demonstration limits disabled'}]}
    catch{return [{label:'Doctor-entered limits',value:'Open the vital warnings section to review this saved version.'}]}
  }
  return Object.entries(labels).filter(([key])=>item[key]).map(([key,label])=>({label,value:item[key]}))
}
