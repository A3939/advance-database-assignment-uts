import type { AnalysisArtifact, AnalysisView } from "./analysis-contracts";
/** ARSIA Web contract v1. No database credentials or pipeline imports belong here. */
export type Source = "NSW" | "VIC" | "QLD";
export type SourceSelection = Source | "All";
export type Availability =
  "available" | "unknown" | "unsupported" | "no_results";
export type Granularity = "yearly" | "monthly";
export interface Filters {
  releaseId?: string;
  source: SourceSelection;
  /** ABS 2024 LGA code; never an accident coordinate. */
  regionId?: string;
  dateRange: { from: string; to: string }; // inclusive ISO calendar dates
  datasetVersion: string;
  batchId: string;
}
export interface Evidence {
  id: string;
  title: string;
  description: string;
  href?: string;
  /** Server-produced tool result, never a model-authored URL. */
  result?: unknown;
  rows?: { label: string; value: string }[];
}
export interface Provenance {
  demo: boolean;
  source: SourceSelection;
  datasetVersion: string;
  batchId: string;
  availability: Availability;
  reason?: string;
  coverage: {
    from: string;
    to: string;
    granularity: "month";
    complete: boolean;
  };
  definition: string;
  unit: string;
  evidence: Evidence[];
}
export interface Response<T> {
  data: T;
  meta: Provenance;
}
export interface Metric {
  reason?: string;
  bySource?: {
    source: Source;
    value: number | null;
    availability: Availability;
  }[];
  value: number | null;
  availability: Availability;
  label: string;
  unit: string;
  definition: string;
}
export interface Overview {
  crashes: Metric;
  fatalCrashes: Metric;
  livesLost: Metric;
  casualties: Metric;
  fatalShare: number | null;
}
export interface TimePoint {
  selectedMonths?: number[];
  observedMonths?: number;
  fullYear?: boolean;
  source?: Source;
  period: string;
  crashes: number | null;
  fatalCrashes: number | null;
  livesLost: number | null;
  casualties: number | null;
}
export interface Severity {
  source?: Source;
  label: string;
  count: number;
  definition: string;
}
export interface MapRegion {
  id: string;
  name: string;
  count: number;
  coordinates?: [number, number];
  fatalCrashes?: number | null;
  localities?: { name: string; count: number }[];
  localityTotal?: number;
}
export interface StateCoverage {
  code: string;
  label: string;
  name: string;
  source?: Source;
  available: boolean;
  /** Selected source count; absent means unknown, never zero-filled. */
  count?: number;
  coordinates: [number, number];
}
export interface MapData {
  level: "country" | "state";
  states?: StateCoverage[];
  boundaryUrl: string;
  regions: MapRegion[];
  bounds: [[number, number], [number, number]];
  illustrationOnly: boolean;
  unavailableReason?: string;
  legendLabel?: string;
  regionMode?: "lga";
  selectedRegionId?: string;
  coverage?: { matched: number; unmatched: number; total: number; percentage: number | null };
}
export interface CrashRecord {
  id: string;
  date: string;
  region: string;
  severity: string;
  source: Source;
  demo: boolean;
}
export interface Pagination {
  page: number;
  pageSize: number;
  search?: string;
}
export interface Sort {
  field: "date" | "id" | "region" | "severity";
  direction: "asc" | "desc";
}
export interface Records {
  rows: CrashRecord[];
  total: number;
  page: number;
  pageSize: number;
  aggregateCount: number | null;
  sampleOnly: boolean;
}
export interface Dataset {
  demo?: boolean;
  description?: string;
  evidence?: Evidence[];
  metricDefinitions?: { label: string; value: string }[];
  source: Source;
  title: string;
  version: string;
  batchId: string;
  coverage: string;
  limitations: string[];
}
export interface AgentContext {
  filters: Filters;
  selectedRegion?: string;
  page: string;
}
export interface AgentTurn {
  role: "user" | "assistant";
  text: string;
  context: AgentContext;
}
export type AgentEvent =
  | { type: "artifact"; artifact: AnalysisArtifact }
  | { type: "visualization"; view: AnalysisView }
  | { type: "message"; text: string; simulated: boolean }
  | { type: "progress"; text: string }
  | { type: "tool_result"; name: string; data: unknown; simulated: boolean }
  | { type: "evidence"; evidence: Evidence }
  | { type: "done"; model: string }
  | { type: "error"; code: string; message: string };
export interface ArsiaService {
  getOverview(filters: Filters, signal?: AbortSignal): Promise<Response<Overview>>;
  getTimeSeries(
    filters: Filters,
    granularity: Granularity,
    signal?: AbortSignal,
  ): Promise<Response<TimePoint[]>>;
  getSeverityDistribution(filters: Filters, signal?: AbortSignal): Promise<Response<Severity[]>>;
  getMapData(filters: Filters, signal?: AbortSignal): Promise<Response<MapData>>;
  getCrashRecords(
    filters: Filters,
    pagination: Pagination,
    sort: Sort,
  ): Promise<Response<Records>>;
  getDatasetMetadata(signal?: AbortSignal, filters?: Filters): Promise<Dataset[]>;
  sendAgentMessage(
    context: AgentContext,
    message: string,
    signal?: AbortSignal,
    history?: AgentTurn[],
  ): AsyncIterable<AgentEvent>;
}
