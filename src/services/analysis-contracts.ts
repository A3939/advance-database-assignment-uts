/** Display-only contracts. The client never executes model-authored JavaScript. */
export type AnalysisRow = Record<string, string | number | null>;
export interface AnalysisArtifact {
  id: string;
  name: string;
  href: string;
  bytes: number;
  sha256: string;
  kind: "csv" | "json" | "md" | "txt" | "png" | "pdf" | "py";
  expiresAt: string;
}
export interface AnalysisView {
  id: string;
  title: string;
  kind: "bar" | "line" | "table";
  rows: AnalysisRow[];
  x: string;
  y: string;
  series: string | null;
  evidenceId: string;
  source: string;
  period: string;
  truncated: boolean;
}
