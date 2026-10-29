// Native EventSource reconnects automatically. Each generation ignores late frames.
export class WorkspaceEvents {
  constructor({url,createSource=(url,options)=>new EventSource(url,options),onConnected=()=>{},onRefresh=()=>{},onSessionEnded=()=>{}}){Object.assign(this,{url,createSource,onConnected,onRefresh,onSessionEnded});this.generation=0;this.source=null;this.revision=null}
  open(visible=true){
    this.close();if(!visible)return
    const generation=this.generation,source=this.createSource(this.url,{withCredentials:true});this.source=source
    const current=()=>this.source===source&&generation===this.generation
    source.addEventListener('workspace',event=>{
      if(!current())return
      let value;try{value=JSON.parse(event.data)}catch{return}
      if(!/^[a-f0-9]{64}$/.test(value?.revision||''))return
      this.onConnected(true)
      if(value.revision!==this.revision){this.revision=value.revision;this.onRefresh()}
    })
    source.addEventListener('session-ended',()=>{if(!current())return;this.close();this.onSessionEnded()})
    source.onerror=()=>{if(current())this.onConnected(false)}
  }
  close(){++this.generation;this.source?.close();this.source=null;this.onConnected(false)}
}
