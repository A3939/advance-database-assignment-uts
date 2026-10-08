import { createHash } from "node:crypto";
import type { ResearchRun } from "../../services/studio-contracts";
import { RESOURCE_DEFINITIONS } from "../../services/studio-resources";
import type { Filters, Provenance } from "../../services/contracts";
export const resourceHash = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).filter(([,v])=>v!==undefined).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>[k,canonical(v)]));
  return value;
}
export const canonicalResourceHash = (value: unknown) => resourceHash(canonical(value));
export function actualResourceCoverage(responses: {meta:Provenance}[], range:Filters["dateRange"]):Provenance["coverage"][] {
  return responses.map(({meta})=>({...meta.coverage,from:meta.coverage.from>range.from?meta.coverage.from:range.from,to:meta.coverage.to<range.to?meta.coverage.to:range.to})).filter(coverage=>coverage.from<=coverage.to);
}
/** Pure saved-snapshot validation: never re-queries data, models, files or another study. */
export function verifyResearchAsset(run:ResearchRun):void {
  const asset=run.resource;
  if(!asset||run.status!=="complete")throw new Error("A complete saved resource is required.");
  const evidence=run.evidence.find(e=>e.id==="E1");
  const result=evidence?.result as {definitionId:unknown;context:unknown;query:unknown;rows:unknown;display:unknown;responses:{meta:Provenance}[];availability:unknown;unit:unknown;limitations:unknown}|undefined;
  const view=run.views[0];
  const same=(a:unknown,b:unknown)=>canonicalResourceHash(a)===canonicalResourceHash(b);
  if(!result||asset.definitionVersion!==1||!RESOURCE_DEFINITIONS.some(d=>d.id===asset.definitionId)||resourceHash(result)!==asset.resultHash||
    canonicalResourceHash({context:asset.context,query:asset.query,definitionId:asset.definitionId,definitionVersion:asset.definitionVersion,resultHash:asset.resultHash})!==asset.bindingHash||
    !same(run.context,asset.context)||!same(result.context,asset.context)||!same(result.query,asset.query)||result.definitionId!==asset.definitionId||
    !same(view?.rows,result.rows)||!same(asset.display,result.display)||!same(asset.actualCoverage,actualResourceCoverage(result.responses,asset.context.filters.dateRange))||
    asset.availability!==result.availability||asset.unit!==result.unit||!same(asset.limitations,result.limitations)||
    evidence?.query?.tool!==`studio_resource:${asset.definitionId}`||!same(evidence.query.parameters,asset.query)||!same(evidence.query.requestedContext.filters,asset.context.filters)||
    view.id!==asset.id||view.evidenceId!==evidence.id||view.source!==asset.context.filters.source||view.period!==`${asset.context.filters.dateRange.from} – ${asset.context.filters.dateRange.to}`||
    view.x!==asset.display.x||view.y!==asset.display.y||view.series!==asset.display.series||view.kind!==(["map","kpi"].includes(asset.display.kind)?"table":asset.display.kind))
    throw new Error("Saved resource integrity or scope binding failed.");
}
