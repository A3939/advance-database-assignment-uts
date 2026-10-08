/** Local editing state only. Host revisions remain the authority for every write. */
export type StudioEditAction = Record<string, unknown>;
export type StudioFieldBinding = {key:string;token:number};
export type PendingStudioEdit = { token: number; studyId: string; key: string; action: StudioEditAction; fields:StudioFieldBinding[]; error?: string };
const editable = new Set(['rename', 'draft', 'context', 'report_meta', 'report_title', 'report_details', 'block_edit', 'finding']);
export class StudioEditBuffer {
  private sequence = 0;
  private records = new Map<string, PendingStudioEdit>();
  stage(studyId: string, action: StudioEditAction, drafts?:StudioFieldDrafts): PendingStudioEdit {
    const token = ++this.sequence;
    // Only an explicit edit to the same fields supersedes an earlier local edit.
    // Structural actions (including a new finding) are independent intentions.
    const names = Object.keys(action).filter(k => !['type','id','revision'].includes(k)).sort();
    const replaceable = editable.has(String(action.type)) && (action.type !== 'finding' || !!action.id);
    const key = JSON.stringify([studyId, action.type, action.id ?? '', replaceable ? names : token]);
    const record = { token, studyId, key, action: structuredClone(action),fields:drafts?.bind(studyId,action)||[] };
    this.records.set(key, record);
    return record;
  }
  owns(record: PendingStudioEdit) { return this.records.get(record.key)?.token === record.token; }
  acknowledge(record: PendingStudioEdit) { if (this.owns(record)) this.records.delete(record.key); }
  fail(record: PendingStudioEdit, message: string) { if(this.owns(record)) this.records.set(record.key, {...record,error:message}); }
  entries(studyId: string) { return [...this.records.values()].filter(v => v.studyId === studyId).map(v => structuredClone(v)); }
  clear(studyId: string) { for(const [key,value] of this.records) if(value.studyId===studyId)this.records.delete(key); }
  discardField(studyId:string,fieldKey:string) { for(const [key,value] of this.records)if(value.studyId===studyId&&value.fields.some(f=>f.key===fieldKey))this.records.delete(key); }
}

/** Each user edit has its own identity: an old A receipt cannot acknowledge a newer A after B. */
export class StudioFieldDrafts {
  private sequence=0;
  private values = new Map<string, { value: string; token:number; save: () => Promise<void> }>();
  set(key: string, value: string, save: () => Promise<void>) { const token=++this.sequence;this.values.set(key,{value,token,save});return token; }
  get(key: string) { return this.values.get(key)?.value; }
  token(key:string) {return this.values.get(key)?.token;}
  acknowledge(key: string, token: number) { if(this.token(key)===token)this.values.delete(key); }
  discard(key:string) {this.values.delete(key);}
  get size() { return this.values.size; }
  snapshot() { return [...this.values.entries()].map(([key,value])=>({key,value:value.value,token:value.token})); }
  clear() { this.values.clear(); }
  async flush() { await Promise.all([...this.values.values()].map(v=>v.save())); }
  bind(studyId:string,action:StudioEditAction):StudioFieldBinding[] {
    const expected:Array<[string,string]>=[];
    if(action.type==='rename'&&typeof action.title==='string')expected.push([`${studyId}:title`,action.title]);
    if(action.type==='report_title'&&typeof action.title==='string')expected.push([`${studyId}:reportTitle`,action.title]);
    if(action.type==='block_edit')for(const field of ['text','caption'])if(typeof action[field]==='string')expected.push([`${studyId}:block:${action.id}:${field}`,action[field] as string]);
    if(action.type==='finding'&&action.id)for(const field of ['title','explanation'])if(typeof action[field]==='string')expected.push([`${studyId}:finding:${action.id}:${field}`,action[field] as string]);
    if(action.type==='context')expected.push([`${studyId}:context`,JSON.stringify(action.context)]);
    if(action.type==='report_meta')expected.push([`${studyId}:reportMeta`,JSON.stringify(action.metadata)]);
    if(action.type==='report_details')expected.push([`${studyId}:reportDetails`,JSON.stringify(action.metadata)]);
    return expected.flatMap(([key,text])=>{const value=this.values.get(key);return value?.value===text?[{key,token:value.token}]:[];});
  }
}
export function acknowledgeStudioFields(fields: StudioFieldDrafts, edit: PendingStudioEdit) {
  for(const binding of edit.fields)fields.acknowledge(binding.key,binding.token);
}

/** A settled failed request is history. Current local intentions decide whether leaving/export is safe. */
export async function requireStudioWritesSaved(tail:Promise<unknown>,unresolved:()=>boolean) {
  await tail.catch(()=>{});
  if(unresolved())throw Error('Resolve unsaved edits first.');
}
