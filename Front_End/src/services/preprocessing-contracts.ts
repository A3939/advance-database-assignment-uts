/** Absent reports are unavailable, never implicitly complete or zero. */
export interface PreprocessingQuality {
  report_version?: string;
  status: string;
  reason?: string;
  raw_rows?: number;
  usable_crashes?: number;
  dispositions?: { retained: number; duplicate_of: number; quarantined: number; excluded_by_scope: number };
  unknown_date_count?: number;
  unlocated_crash_count?: number;
  metrics?: Record<string, { known_count: number; unknown_count: number; invalid_count: number; known_subtotal: number }>;
  rules?: string[];
  agent_new_judgment?: boolean;
  plan?: { profile_sha256?: string; authority?: string; version?: string };
}
export interface SelectionQuality {
  unknown_date_membership_count: number;
  retained_unknown_date_count: number;
  all_time: boolean;
  quality_report_status: string;
  metrics?: PreprocessingQuality['metrics'];
}
