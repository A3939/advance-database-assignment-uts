"use client";
import { SelectField } from "./ui/select-field";
import { useState } from "react";
import type { ResearchRun, Study, FindingKind } from "@/services/studio-contracts";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "./ui/dialog";
import { Button } from "./ui/button";
import styles from "./studio-research.module.css";
export function FindingComposer({study, initialRun, close, save}: {study:Study; initialRun:ResearchRun|null; close:()=>void; save:(a:Record<string,unknown>)=>Promise<void>}) {
  const [title,setTitle]=useState(""),[explanation,setExplanation]=useState(""),[kind,setKind]=useState<FindingKind>("Observation");
  const [runId,setRunId]=useState(initialRun?.id || ""),[evidenceId,setEvidenceId]=useState(initialRun?.evidence[0]?.id || ""),[rowIndex,setRowIndex]=useState("");
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const run=study.runs.find(r=>r.id===runId), resource=run?.resource, rows=run?.views[0]?.rows || [];
  async function submit() {
    setBusy(true);setError("");
    try {
      const row=rows[Number(rowIndex)];
      const claim=resource && rowIndex !== "" && row && evidenceId === "E1" ? {evidenceId,pointer:`/rows/${rowIndex}/${resource.display.y.replaceAll("~","~0").replaceAll("/","~1")}`,source:String(row.source ?? resource.context.filters.source),metric:String(row.metric ?? resource.context.metric),from:String(row.from ?? resource.context.filters.dateRange.from),to:String(row.to ?? resource.context.filters.dateRange.to),value:row[resource.display.y],unit:String(row.unit ?? resource.unit)} : undefined;
      await save({type:"finding",kind,title,explanation,...(runId ? {runId,evidenceIds:evidenceId ? [evidenceId] : []} : {}),...(claim ? {claims:[claim]} : {})});
    } catch(e) {setError((e as Error).message);} finally{setBusy(false);}
  }
  return <Dialog open onOpenChange={v=>{if(!v&&!busy)close();}}><DialogContent className={styles.dialog}>
    <DialogTitle>Record one finding</DialogTitle><DialogDescription>Write one claim. Linking evidence and checking a value do not establish an explanation or cause.</DialogDescription>
    <label className={styles.field}>Type<SelectField aria-label="Finding type" value={kind} onValueChange={value=>setKind(value as FindingKind)} options={["Observation","Hypothesis","Open question"].map(value=>({value,label:value}))}/></label>
    <label className={styles.field}>Claim title<input value={title} maxLength={500} onChange={e=>setTitle(e.target.value)}/></label>
    <label className={styles.field}>Explanation<textarea rows={3} value={explanation} maxLength={6000} onChange={e=>setExplanation(e.target.value)}/></label>
    <label className={styles.field}>Evidence resource<SelectField aria-label="Evidence resource" value={runId} onValueChange={value=>{setRunId(value);setEvidenceId(study.runs.find(r=>r.id===value)?.evidence[0]?.id||"");setRowIndex("");}} options={[{value:"",label:"No evidence — manual finding"},...study.runs.filter(r=>r.status==="complete").map(r=>({value:r.id,label:r.question}))]}/></label>
    {run && <label className={styles.field}>Evidence record<SelectField aria-label="Evidence record" value={evidenceId} onValueChange={value=>{setEvidenceId(value);setRowIndex("");}} placeholder="No evidence records" options={run.evidence.map(e=>({value:e.id,label:`${e.id} · ${e.title}`}))}/></label>}
    {resource && evidenceId==="E1" && <label className={styles.field}>Value to check (optional)<SelectField aria-label="Value to check (optional)" value={rowIndex} onValueChange={setRowIndex} options={[{value:"",label:"No numerical claim"},...rows.flatMap((r,i)=>typeof r.metric==="string"&&typeof r.unit==="string"&&typeof r[resource.display.y]==="number"&&Number.isFinite(r[resource.display.y])?[{value:String(i),label:`${r.source} · ${String(r[resource.display.x])} · ${r[resource.display.y]} ${String(r.unit ?? resource.unit)}`}]:[])]}/></label>}
    <p className={styles.note}>The server checks any selected value, unit and scope. The wording remains unreviewed; evidence never certifies a causal explanation.</p>
    {error&&<p className={styles.error} role="alert">{error}</p>}<Button disabled={busy||!title.trim()} onClick={()=>void submit()}>{busy?"Saving…":"Save finding"}</Button>
  </DialogContent></Dialog>;
}
