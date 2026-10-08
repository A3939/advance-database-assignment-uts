import type { Evidence } from "../../services/contracts";
import { object } from "./tools";
const labels: Record<string, string> = {
  crashes: "Crashes",
  fatalCrashes: "Fatal crashes",
  livesLost: "Lives lost",
  casualties: "Casualties",
};
const number = (value: unknown) =>
  typeof value === "number"
    ? value.toLocaleString("en-AU", { maximumFractionDigits: 2 })
    : "Unavailable";
const percent = (value: unknown) =>
  typeof value === "number"
    ? value !== 0 && Math.abs(value) < 0.01
      ? "<0.01%"
      : `${number(value)}%`
    : "Percentage unavailable";
const dates = (value: unknown) => {
  const r = object(value);
  return `${r.from} → ${r.to}`;
};
/** A readable evidence summary, derived solely from the successful tool payload. */
export function evidenceRows(value: unknown): NonNullable<Evidence["rows"]> {
  const r = object(value),
    rows: NonNullable<Evidence["rows"]> = [
      { label: "Source", value: String(r.source) },
    ];
  if (Array.isArray(r.inputScopes))
    for (const raw of r.inputScopes) {
      const scope = object(raw);
      rows.push({
        label: `Input ${scope.evidenceId} · ${scope.source}`,
        value: `${dates(scope.requestedRange)}${scope.regionId ? ` · LGA ${scope.regionId}` : ""}`,
      });
    }
  if (r.releaseId) rows.push({label:"Release",value:String(r.releaseId)});
  else if (r.batchId) rows.push({label:"Snapshot batch",value:String(r.batchId)});
  if (r.sourceBatches && typeof r.sourceBatches === "object") rows.push({label:"Source batches",value:Object.entries(r.sourceBatches).map(([source,batch])=>`${source}: ${batch}`).join("; ")});
  if (r.queryId) rows.push({ label: "Query", value: String(r.queryId) });
  if (r.dataset) rows.push({ label: "Table", value: String(r.dataset) });
  if (r.returnedRows !== undefined)
    rows.push({
      label: "Rows",
      value: `${r.returnedRows} retained / ${r.resultRows} matched`,
    });
  if (r.status) rows.push({ label: "Execution", value: String(r.status) });
  if (r.stdout)
    rows.push({ label: "Computed output", value: String(r.stdout) });
  if (r.error) rows.push({ label: "Error", value: String(r.error) });
  if (r.regionId)
    rows.push({
      label: "LGA",
      value: `${r.regionName || "ABS code"} · ${r.regionId}`,
    });
  if (r.matchingCoverage) {
    const c = object(r.matchingCoverage);
    rows.push({
      label: "Name matching",
      value: `${number(c.matched)} matched / ${number(c.total)} source crashes; ${number(c.unmatched)} unmatched`,
    });
  }
  if (Array.isArray(r.areas))
    for (const area of r.areas.slice(0, 10)) {
      const a = object(area);
      rows.push({
        label: `${a.name} LGA (${a.id})`,
        value: `${number(a.count)} crashes`,
      });
    }
  if (r.requestedRange)
    rows.push({ label: "Query period", value: dates(r.requestedRange) });
  if (r.observedRange)
    rows.push({
      label: "Snapshot date overlap",
      value: dates(r.observedRange),
    });
  if (r.baselineRange)
    rows.push({ label: "Comparison period", value: dates(r.baselineRange) });
  if (r.reason) rows.push({ label: "Availability", value: String(r.reason) });
  if (r.coverage)
    rows.push({ label: "Snapshot coverage", value: dates(r.coverage) });
  if (Array.isArray(r.results))
    for (const raw of r.results) {
      const item = object(raw),
        source = String(item.source),
        meta = object(item.meta);
      if (meta.availability !== "available") {
        rows.push({
          label: source,
          value: String(meta.reason || meta.availability),
        });
        continue;
      }
      if (Array.isArray(item.metrics))
        for (const raw of item.metrics) {
          const metric = object(raw);
          rows.push({
            label: `${source} · ${labels[String(metric.metric)]}`,
            value:
              metric.availability === "available"
                ? `${number(metric.baseline)} → ${number(metric.current)} · Change ${number(metric.difference)} (${percent(metric.percentChange)})`
                : String(metric.reason || metric.availability),
          });
        }
      else if (Array.isArray(item.points))
        for (const raw of [item.points[0], item.points.at(-1)].filter(
          Boolean,
        )) {
          const point = object(raw);
          rows.push({
            label: `${source} · ${point.period}`,
            value: `${labels[String(item.metric)]}: ${number(point.value)}`,
          });
        }
      else if (Array.isArray(item.data))
        for (const raw of item.data) {
          const severity = object(raw);
          rows.push({
            label: `${source} · ${severity.label}`,
            value: `${number(severity.count)} crashes · ${percent(severity.sharePercent)}`,
          });
        }
      else if (item.data)
        for (const [key, label] of Object.entries(labels)) {
          const metric = object(object(item.data)[key]);
          rows.push({
            label: `${source} · ${label}`,
            value: `${number(metric.value)} ${metric.unit} · ${metric.availability}`,
          });
        }
    }
  if (Array.isArray(r.qa))
    for (const raw of r.qa) {
      const qa = object(raw);
      rows.push({ label: String(qa.check), value: String(qa.status) });
    }
  return rows;
}
