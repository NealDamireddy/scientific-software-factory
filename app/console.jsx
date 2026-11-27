"use client";
import {useEffect,useRef,useState} from "react";
import { evolvePath } from "./paths";
import {X,Play,Download,Check,ShieldCheck,Terminal,ArrowRight,AlertCircle,LoaderCircle} from "lucide-react";
export function Dialog({title,close,children,large=false}) {
  const ref=useRef();
  useEffect(()=>{const dialog=ref.current;dialog.showModal();return ()=>dialog.close()},[]);
  return <dialog ref={ref} className={large?"wide":""} onCancel={close} onClick={e=>{if(e.target===ref.current)close()}}>
    <div className="modalHead"><h2>{title}</h2><button className="iconBtn" aria-label="Close dialog" onClick={close}><X size={19}/></button></div>{children}</dialog>
}
export function RunConsole({run,close}) {
  const [cap,setCap]=useState(run.context.project.operation);
  const [unit,setUnit]=useState(Object.values(run.context.project.units)[0]);
  const [objective,setObjective]=useState(run.context.project.description);
  const [state,setState]=useState("ready"),[result,setResult]=useState(null);
  const worker=useRef(null),timer=useRef(null);
  useEffect(()=>()=>{worker.current?.terminate();clearTimeout(timer.current)},[]);
  const project=run.context.project,registry=run.context.instrument.capabilities,expected=Object.values(project.units)[0];
  const reset=()=>{setResult(null);setState("ready")};
  const busy=state==="running", custom=objective.trim()!==project.description;
  const getOrder=()=>({...run.order,id:"LOCAL-"+project.id,origin:"local",upstream_id:undefined,objective:objective.trim(),
    operations:["read-export",cap],input:{...run.order.input,units:{...project.units,[Object.keys(project.units)[0]]:unit}},
    acceptance:custom?[...run.order.acceptance,"review-custom-objective"]:run.order.acceptance});
  const download=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(getOrder(),null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="work-order.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
  const go=()=>{
    if(!objective.trim()){setResult({error:"Enter a scientific objective."});setState("blocked");return}
    if(!registry[cap]||registry[cap].status!=="supported"){setState("blocked");setResult({error:(registry[cap]?.status==="unsupported"?"Unsupported capability. ":"Unverified capability. ")+(registry[cap]?.reason||"Missing registry evidence.")});return}
    if(unit!==expected){setState("blocked");setResult({error:"Unit mismatch. The registered reference and acquisition metadata require "+expected+". This order declares "+unit+"."});return}
    if(custom){setState("handoff");return}
    setState("running");
    worker.current=new Worker(evolvePath("/replay.mjs"),{type:"module"});
    const finish=value=>{clearTimeout(timer.current);worker.current?.terminate();worker.current=null;setResult(value);setState(value.error||!value.passed?"failed":"done")};
    worker.current.onmessage=e=>finish(e.data);
    worker.current.onerror=e=>finish({error:e.message||"Python worker could not start."});
    timer.current=setTimeout(()=>finish({error:"Browser replay exceeded its 60-second limit."}),60000);
    worker.current.postMessage({folder:run.folder,manifest:run.report.artifacts,reference:run.report.tests[0]});
  };
  return <Dialog title="Work order console" close={close}><div className="modalBody">
    <div className="metaLine"><span className="tag"><Terminal size={13}/> Factory runtime</span><span>{project.name}</span></div>
    <label>Scientific objective<textarea value={objective} disabled={busy} onChange={e=>{setObjective(e.target.value);reset()}}/></label>
    <div className="formGrid"><label>Requested capability<select value={cap} disabled={busy} onChange={e=>{setCap(e.target.value);reset()}}>
      {[project.operation,"pulse-acquisition","vendor-binary"].map(key=><option key={key}>{key}</option>)}</select></label>
      <label>Declared input unit<select value={unit} disabled={busy} onChange={e=>{setUnit(e.target.value);reset()}}>{[expected,expected==="K"?"°C":"T"].map(v=><option key={v}>{v}</option>)}</select></label></div>
    <p className="subtle">Replay executes the archived Python on the registered input in your browser. Download a changed order to generate new source with local Codex.</p>
    {state==="running"&&<div className="notice"><LoaderCircle className="spin" size={16}/> Loading Python and checking artifact hashes…</div>}
    {(state==="failed"||state==="blocked")&&<div role="status" className="notice bad"><AlertCircle size={18}/><div><b>{state==="blocked"?"Preflight blocked":"Replay failed"}</b><p>{result?.error||"Output exceeded reference tolerance."}</p></div></div>}
    {state==="done"&&<div role="status" className="notice good"><ShieldCheck size={20}/><div><b>Browser replay passed</b><p>Python {result.python} executed the archived source. All primary reference values matched.</p><code>{project.id==="curie"?"C = "+result.output.coefficient_au_K.toFixed(3)+" a.u. K":"ΔBpp = "+result.output.linewidth_mT.toFixed(3)+" mT"}</code></div></div>}
    {state==="handoff"&&<div role="status" className="notice"><Terminal size={18}/><div><b>Ready for local generation</b><p>Download this order and run it from the repository. Custom objectives require independent review.</p><code>python -m factory run work-order.json --mode generate</code></div></div>}
    <div className="modalActions"><button className="btn" disabled={busy||!objective.trim()} onClick={download}><Download size={15}/>Order JSON</button><button className="btn primary" disabled={busy} onClick={go}><Play size={14}/>{custom?"Check work order":"Run preflight & replay"}</button></div></div></Dialog>
}
export function Artifact({run,file,close}){
  const [body,setBody]=useState("Loading…");
  useEffect(()=>{const controller=new AbortController();fetch(run.folder+"/"+file,{signal:controller.signal}).then(res=>{if(!res.ok)throw Error("Artifact unavailable");return res.text()}).then(setBody).catch(e=>{if(e.name!=="AbortError")setBody(e.message)});return ()=>controller.abort()},[run,file]);
  return <Dialog title={file} close={close} large><div className="fileMeta"><span>{run.report.id}</span><a href={run.folder+"/"+file} download><Download size={14}/>Download file</a></div><pre className="source">{body}</pre></Dialog>
}
