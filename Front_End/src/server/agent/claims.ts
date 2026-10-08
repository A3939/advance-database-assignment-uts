import type { FunctionTool } from "openai/resources/responses/responses";
import type { Evidence } from "../../services/contracts";

const record = (v: unknown): Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {};
const numericalTools = new Set(["core_metrics", "time_series", "compare_periods", "monthly_contributions", "severity_distribution", "regional_analysis", "workspace_query"]);
export const claimTool: FunctionTool = {
  type: "function", name: "check_claims", strict: true,
  description: "Check up to 12 key numerical claims against exact values in this turn's data evidence. Use RFC 6901 pointers into the tool result, its exact requested query range, source and metric. This checks value/scope binding, not causal or free-text conclusions. Python execution alone cannot certify a claim.",
  parameters: {type:"object",additionalProperties:false,required:["claims"],properties:{claims:{type:"array",minItems:1,maxItems:12,items:{type:"object",additionalProperties:false,required:["evidenceId","pointer","source","metric","from","to","value"],properties:{evidenceId:{type:"string"},pointer:{type:"string"},source:{type:"string"},metric:{type:"string"},from:{type:"string"},to:{type:"string"},value:{type:"number"}}}}}},
};

export function checkClaims(value: unknown, evidence: Map<string, Evidence>) {
  const claims=record(value).claims;
  if (!Array.isArray(claims) || !claims.length || claims.length>12) throw Error("Choose 1–12 claims.");
  return {status:"checked", limitation:"Exact tool value and query-scope checks; narrative, interpretation and causality are not automatically verified.",claims:claims.map(raw => {
    const c=record(raw), e=evidence.get(String(c.evidenceId));
    const reject=(reason:string)=>({...c,status:"unsupported",reason});
    if (!e || !e.query || !numericalTools.has(e.query.tool)) return reject("No numerical data evidence with this ID.");
    const root=record(e.result), range=record(root.requestedRange);
    if (c.from!==range.from || c.to!==range.to || typeof c.from!=="string") return reject("Claim range differs from the actual query range.");
    if (typeof c.pointer!=="string" || c.pointer.length>500 || !c.pointer.startsWith("/") || /~(?![01])/.test(c.pointer)) return reject("Invalid exact-value pointer.");
    const parts=c.pointer.slice(1).split("/").map(p=>p.replaceAll("~1","/").replaceAll("~0","~"));
    let node:unknown=root, source=root.source, metric:unknown=root.metric;
    for (const part of parts) {
      const obj=record(node);
      if (obj.source!==undefined) source=obj.source;
      if (obj.metric!==undefined) metric=obj.metric;
      if ((obj.availability!==undefined && obj.availability!=="available") || (record(obj.meta).availability!==undefined && record(obj.meta).availability!=="available")) return reject("Value belongs to unavailable evidence.");
      if (["crashes","fatalCrashes","livesLost","casualties"].includes(part)) metric=part;
      if (Array.isArray(node)) {
        if (!/^(0|[1-9][0-9]*)$/.test(part)) return reject("Invalid array pointer.");
        node=node[Number(part)];
      } else {
        if (!Object.hasOwn(obj,part)) return reject("Pointer is absent from the evidence.");
        node=obj[part];
      }
    }
    if (source!==c.source || source==="All") return reject("Claim must name the actual independent source.");
    if (!metric || metric!==c.metric) return reject("Metric identity is not established at this pointer.");
    if (typeof node!=="number" || !Number.isFinite(node) || node!==c.value) return reject("Claim value differs from the exact tool value; null is not zero.");
    return {...c,status:"supported_exact_value",batchId:root.batchId,releaseId:root.releaseId,baselineRange:root.baselineRange,
      limitation:"Query range identifies selection; point periods, partial coverage and source definitions remain in the linked evidence."};
  })};
}

export function evidenceAssurance(tool:string,result:unknown): NonNullable<Evidence["query"]>["assurance"] {
  const r=record(result);
  return {parameters:"validated",execution:tool==="python_analysis" ? String(r.status || "unknown") : "returned",
    claims:tool==="check_claims" ? "scoped_values_checked" : "not_automatically_verified"};
}

export function answerCheck(text:string,evidence:Map<string,Evidence>) {
  const unknownEvidence=[...new Set(text.match(/\bE[1-9]\d*\b/g)||[])].filter(id=>!evidence.has(id));
  const numericWithoutData=/\d/.test(text.replace(/\bE[1-9]\d*\b/g,"")) && ![...evidence.values()].some(e=>numericalTools.has(e.query?.tool||""));
  return {status:unknownEvidence.length||numericWithoutData ? "needs_review":"not_exhaustively_verified",unknownEvidence,numericWithoutData,
    limitation:"Parameter validation and successful execution do not establish narrative correctness. Scoped numerical claims can be checked with check_claims."};
}
