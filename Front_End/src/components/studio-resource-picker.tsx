"use client";
import { SelectField } from "./ui/select-field";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "./ui/dialog";
import { Button } from "./ui/button";
import { studioRequest, studyHref } from "@/services/studio-client";
import type { ResearchContext, Study, StudySummary } from "@/services/studio-contracts";
import type { ResourceCatalogEntry, ResourceId, ResourceQuery, ResourceRequest } from "@/services/studio-resources";
import styles from "./studio-research.module.css";

function ResourcePicker({ open, onClose, context, page, query, target, onSaved, contextById, document, initialSelection, lockTarget }: {
  open: boolean; onClose: () => void; context: ResearchContext; page?: string;
  contextById?: Partial<Record<ResourceId,ResearchContext>>;
  document?: {afterId?:string|null};
  initialSelection?:ResourceId;lockTarget?:boolean;
  query?: ResourceQuery; target?: Study; onSaved?: (s: Study) => void;
}) {
  const router = useRouter();
  const [entries, setEntries] = useState<ResourceCatalogEntry[]>([]), [studies, setStudies] = useState<StudySummary[]>([]);
  const [selection, setSelection] = useState<ResourceId | "">(""), [destination, setDestination] = useState(target?.id || "");
  const [loading, setLoading] = useState(true), [saving, setSaving] = useState(false), [error, setError] = useState("");
  const [queryEdit,setQueryEdit] = useState<ResourceQuery>({});
  const request = useRef<{key: string; payload: ResourceRequest} | null>(null);
  const key = JSON.stringify(context);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    Promise.all([studioRequest<ResourceCatalogEntry[]>(`/resources?context=${encodeURIComponent(key)}`, "GET", undefined, abort.signal), studioRequest<StudySummary[]>("", "GET", undefined, abort.signal)])
      .then(([catalog, list]) => { setEntries(catalog); setStudies(list.filter(s => !s.archived)); setSelection(initialSelection&&catalog.some(e=>e.id===initialSelection)?initialSelection:""); setLoading(false); })
      .catch(e => { if (!abort.signal.aborted) { setError(e.message); setLoading(false); } });
    return () => abort.abort();
  }, [open, key, target?.id,initialSelection]);
  const choices = entries.filter(e => !page || e.pages.includes(page));
  const selected = entries.find(e => e.id === selection);
  const selectedContext = (selection && contextById?.[selection]) || context;
  async function save() {
    if (!selected || selected.availability !== "available" || saving) return;
    setSaving(true); setError("");
    try {
      const identity = {definitionId:selected.id, context:selectedContext, query:{...selected.query,...(selected.id === "trend" ? query : {}),...queryEdit}, destination,...(document?{document}:{})};
      const signature = JSON.stringify(identity);
      if (request.current?.key !== signature) {
        const existing = destination ? await studioRequest<Study>(`/${destination}`) : null;
        const bound = target && destination === target.id ? target : existing;
        const {destination: _destination, ...payload} = identity;
        void _destination;
        request.current = {key:signature,payload:{...payload,requestId:crypto.randomUUID(),...(bound ? {target:{studyId:bound.id,revision:bound.revision}} : {})}};
      }
      // Reuse the original request/revision after a lost response; do not turn a retry into another save.
      const study = await studioRequest<Study>("/resources", "POST", request.current.payload);
      onClose();
      if (onSaved) onSaved(study); else router.push(studyHref(study));
    } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
  }
  return <Dialog open={open} onOpenChange={value => { if (!value && !saving) onClose(); }}>
    <DialogContent className={styles.dialog}>
      <DialogTitle>{document?"Add a chart to your document":"Add a platform resource"}</DialogTitle>
      <DialogDescription>Choose a chart or table. Its data scope and sources are saved with it.</DialogDescription>
      <p className={styles.scope}>{selectedContext.filters.source} · {selectedContext.filters.dateRange.from} – {selectedContext.filters.dateRange.to} · {selectedContext.filters.datasetVersion}</p>
      {loading ? <p role="status"><Loader2 size={16} className="spin"/> Checking capabilities…</p> : <>
        <div className={styles.resourceOptions} role="radiogroup" aria-label="Platform resources">
          {choices.map(entry => <label key={entry.id} className={styles.resourceOption}>
            <input type="radio" name="studio-resource" checked={selection === entry.id} disabled={entry.availability === "unsupported"} onChange={() => {setSelection(entry.id);setQueryEdit({});}} />
            <span><strong>{entry.label}</strong><small>{entry.kind} · {entry.availability}{entry.reason ? ` · ${entry.reason}` : ""}</small></span>
          </label>)}
        </div>
        {selected?.id === "period-comparison" && <div><p className={styles.note}>Comparison periods (YYYY–YYYY). These are explicit research periods.</p>{(["first","second"] as const).map(k=><label key={k} className={styles.field}>{k === "first" ? "Baseline" : "Comparison"}<input value={queryEdit.comparison?.[k] ?? selected.query.comparison?.[k] ?? ""} onChange={e=>setQueryEdit({...queryEdit,comparison:{first:queryEdit.comparison?.first ?? selected.query.comparison?.first ?? "",second:queryEdit.comparison?.second ?? selected.query.comparison?.second ?? "",[k]:e.target.value}})}/></label>)}</div>}
        {selected?.id === "severity" && <label className={styles.field}>Severity measure<SelectField aria-label="Severity measure" value={queryEdit.severityMode || "count"} onValueChange={value=>setQueryEdit({severityMode:value as "count"|"share"})} options={[{value:"count",label:"Recorded counts"},{value:"share",label:"Within-source share"}]}/></label>}
        {selected?.id === "area-table" && <label className={styles.field}>Sort areas<SelectField aria-label="Sort areas" value={queryEdit.sort || "count"} onValueChange={value=>setQueryEdit({sort:value as "count"|"fatalShare"|"name"})} options={[{value:"count",label:"Recorded crashes"},{value:"fatalShare",label:"Fatal crash share"},{value:"name",label:"Area name"}]}/></label>}
        {selected && <p className={styles.note}>{selected.limitations.join(" ")}</p>}
        <label className={styles.field}>Save to<SelectField aria-label="Save resource to" disabled={!!target&&(!!document||!!lockTarget)} value={destination} onValueChange={setDestination} options={[{value:"",label:"New study"},...studies.map(s=>({value:s.id,label:s.title}))]}/></label>
        {destination && <p className={styles.note}>This resource keeps the source and period shown above. Existing results retain their own scope.</p>}
        <Button disabled={!selected || selected.availability !== "available" || saving} onClick={() => void save()}>{saving ? "Saving resource…" : document?"Insert chart & start writing":"Get resource"}</Button>
      </>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </DialogContent>
  </Dialog>;
}

export default function StudioResourcePicker(props: Parameters<typeof ResourcePicker>[0]) { return props.open ? <ResourcePicker {...props}/> : null; }
