import type { AgentContext, AgentEvent, Evidence, Filters } from "./contracts";
import type { AnalysisArtifact, AnalysisView } from "./analysis-contracts";
import type { ResearchAsset } from "./studio-resources";

export type ResearchMode = "explore" | "analyze" | "draft" | "revise";
export interface EvidenceReference {
  runId: string;
  attempt: number;
  evidenceId: string;
  resultHash: string;
}
export interface FindingChecks {
  evidenceLinked: boolean;
  numericChecked: boolean;
  reviewNeeded: boolean;
  unsupportedClaim: boolean;
  userReviewed: boolean;
  checkedAt: string;
  contentHash: string;
  notes: string[];
}
export interface NumericClaim {
  evidenceId: string; pointer: string; source: string; metric: string;
  from: string; to: string; value: number; unit: string;
}
export interface ReportMetadata {
  contractVersion: 1;
  template: "brief" | "full";
  language: "en" | "zh" | "bilingual";
  title: string;
  author: string;
  date: string;
}
export interface ResearchReportDraft {
  id: string;
  mode: "draft" | "revise";
  baseReportHash: string;
  targetBlockId?: string;
  blocks: ReportBlock[];
  createdAt: string;
  status: "proposed" | "applied";
  appliedRevision?: number;
}

export interface ResearchContext {
  filters: Filters;
  metric: "crashes" | "fatalCrashes" | "livesLost" | "casualties";
  notes: string;
  references: string;
}
export type RunStatus =
  | "running"
  | "complete"
  | "failed"
  | "stopped"
  | "interrupted";
export interface ResearchStep {
  label: string;
  stage: "data" | "analysis" | "presentation";
  optional: boolean;
  status:
    | "pending"
    | "active"
    | "complete"
    | "skipped"
    | "not_needed"
    | "incomplete";
}
export interface ResearchRun {
  id: string;
  question: string;
  context: ResearchContext;
  status: RunStatus;
  answer: string;
  progress: string;
  error?: string;
  createdAt: string;
  updatedAt: string;
  attempt: number;
  previousAttempts: {
    status: RunStatus;
    answer: string;
    evidence: Evidence[];
    error?: string;
    views?: AnalysisView[];
    artifactIds?: string[];
  }[];
  plan: ResearchStep[];
  skipPresentation: boolean;
  evidence: Evidence[];
  views: AnalysisView[];
  artifactIds: string[];
  changes: string[];
  origin: "assistant" | "analytics" | "ask-ai";
  toolErrors?: { name: string; parameters: unknown; message: string }[];
  mode?: ResearchMode;
  selectedRunIds?: string[];
  targetBlockId?: string;
  resource?: ResearchAsset;
  reportDraft?: ResearchReportDraft;
  completionWarnings?: string[];
}
export type FindingKind = "Observation" | "Hypothesis" | "Open question";
export interface ResearchFinding {
  id: string;
  kind: FindingKind;
  title: string;
  explanation: string;
  runId?: string;
  evidenceIds: string[];
  context: ResearchContext;
  limitations: string;
  origin: "assistant" | "user";
  archived: boolean;
  createdAt: string;
  updatedAt: string;
  evidenceRefs?: EvidenceReference[];
  claims?: NumericClaim[];
  checks?: FindingChecks;
  edits: {
    at: string;
    title: string;
    explanation: string;
    kind: FindingKind;
    evidenceRefs?: EvidenceReference[];
    claims?: NumericClaim[];
    checks?: FindingChecks;
  }[];
}
export interface ReportBlock {
  id: string;
  kind:
    | "title"
    | "text"
    | "finding"
    | "chart"
    | "table"
    | "evidence"
    | "artifact"
    | "section"
    | "resource";
  text: string;
  refId?: string;
  runId?: string;
  caption?: string;
  resultHash?: string;
  citations?: EvidenceReference[];
  /** Host-bound origin of an answer copied into editable, unverified prose. */
  answerSource?: { runId: string; attempt: number; answerHash: string };
  pageBreakBefore?: boolean;
  size?: "full" | "half";
}
export interface StudyArtifact extends Omit<AnalysisArtifact, "expiresAt"> {
  runId: string;
  attempt?: number;
  createdAt: string;
  provenance: unknown;
}
export interface Study {
  schemaVersion?: 1;
  id: string;
  title: string;
  context: ResearchContext;
  draft: string;
  archived: boolean;
  revision: number;
  createdAt: string;
  updatedAt: string;
  runs: ResearchRun[];
  findings: ResearchFinding[];
  report: ReportBlock[];
  reportMeta?: ReportMetadata;
  artifacts: StudyArtifact[];
}
export type StudySummary = Pick<
  Study,
  "id" | "title" | "archived" | "updatedAt"
>;
export interface StudyVersion {
  id: string;
  label: string;
  createdAt: string;
  context: ResearchContext;
  runs: number;
  findings: number;
}
export interface CompletedTransfer {
  id: string;
  context: AgentContext;
  question: string;
  events: AgentEvent[];
  createdAt: string;
}
export type StudioEvent = AgentEvent | { type: "study"; study: Study };
