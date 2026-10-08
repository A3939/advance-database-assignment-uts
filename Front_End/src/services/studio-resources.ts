import type { Availability, Provenance } from "./contracts";
import type { ResearchContext } from "./studio-contracts";

/** Registered presentation/query pairs, not caller-provided code or result data. */
export const RESOURCE_DEFINITIONS = [
  { id: "overview-kpis", label: "Overview key metrics", kind: "kpi", pages: ["overview"] },
  { id: "trend", label: "Recorded counts over time", kind: "line", pages: ["overview", "trends"] },
  { id: "period-comparison", label: "Compare two periods", kind: "bar", pages: ["trends"] },
  { id: "severity", label: "Native severity distribution", kind: "bar", pages: ["overview", "severity"] },
  { id: "fatal-outcomes", label: "Fatal crashes and lives lost", kind: "bar", pages: ["severity"] },
  { id: "severity-change", label: "Severity category comparison", kind: "table", pages: ["severity"] },
  { id: "speed-zones", label: "Fatal crash share by speed zone", kind: "bar", pages: ["severity"] },
  { id: "spatial-map", label: "Recorded crashes map", kind: "map", pages: ["overview", "spatial"] },
  { id: "area-table", label: "Mapped area detail", kind: "table", pages: ["spatial"] },
  { id: "spatial-concentration", label: "Mapped crash concentration", kind: "line", pages: ["spatial"] },
  { id: "calendar-pattern", label: "Calendar-month averages", kind: "bar", pages: ["trends"] },
  { id: "monthly-matrix", label: "Monthly observations", kind: "table", pages: ["trends"] },
  { id: "yearly-comparison", label: "Annual counts and matching-month change", kind: "table", pages: ["trends"] },
] as const;
export type ResourceId = typeof RESOURCE_DEFINITIONS[number]["id"];
export interface ResourceQuery {
  granularity?: "monthly" | "yearly";
  severityMode?: "count" | "share";
  comparison?: { first: string; second: string };
  sort?: "count" | "fatalShare" | "name";
}
export interface ResourceRequest {
  requestId: string;
  definitionId: ResourceId;
  context: ResearchContext;
  query?: ResourceQuery;
  title?: string;
  target?: { studyId: string; revision: number };
  /** Explicit Studio document intent. Absent keeps legacy resource-library saves unchanged. */
  document?: { afterId?: string | null };
}
export interface ResearchAsset {
  id: string;
  definitionId: ResourceId;
  definitionVersion: 1;
  requestId: string;
  requestHash: string;
  targetStudyId?: string;
  resultHash: string;
  bindingHash: string;
  context: ResearchContext;
  query: ResourceQuery;
  availability: Availability;
  display: { kind: typeof RESOURCE_DEFINITIONS[number]["kind"]; x: string; y: string; series: string | null };
  actualCoverage: Provenance["coverage"][];
  unit: string;
  limitations: string[];
  createdAt: string;
}
export interface ResourceCatalogEntry {
  id: ResourceId;
  label: string;
  kind: ResearchAsset["display"]["kind"];
  pages: readonly string[];
  availability: Availability;
  reason?: string;
  limitations: string[];
  query: ResourceQuery;
}
