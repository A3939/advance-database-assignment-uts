import type { ResponseUsage } from 'openai/resources/responses/responses';
/** Decode only terminal transport receipts. Source/model text is never logged. */
export class ModelSseAudit {
  private decoder = new TextDecoder();
  private pending = '';
  terminal = false;
  status: "completed" | "failed" = "failed";
  constructor(private record: (value: {id:string;model:string;status:string;usage?:ResponseUsage}) => Promise<void>) {}
  async push(bytes: Uint8Array) {
    this.pending += this.decoder.decode(bytes, {stream:true});
    if (this.pending.length > 4*1024*1024) throw Error('Model event byte limit');
    const lines = this.pending.split('\n'); this.pending = lines.pop() || '';
    for (const line of lines) {
      if (this.terminal || !line.startsWith('data:')) continue;
      let event;
      try { event=JSON.parse(line.slice(5)); } catch { continue; }
      if (!['response.completed','response.failed','response.incomplete'].includes(event?.type)) continue;
      const r=event.response;
      if (!r || typeof r.id!=='string' || typeof r.model!=='string') continue;
      await this.record({id:r.id,model:r.model,status:typeof r.status==='string' ? r.status : 'unknown',usage:r.usage});
      this.status=event.type === "response.completed" && r.status === "completed" ? "completed" : "failed";
      this.terminal=true;
    }
  }
}
