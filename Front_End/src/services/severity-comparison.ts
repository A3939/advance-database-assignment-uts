import type { Severity, Source } from "./contracts";

export type SeverityValue = Severity & { share?: number | null };
export interface SeverityGroup {
  label: string;
  rows: (SeverityValue | null)[];
}
// Display slots only: original labels and definitions remain on each observation.
// These pairings do not establish an interstate severity classification.
const displayGroups = [
  { label: "Fatal", labels: ["fatal"] },
  { label: "Serious injury /\nhospitalisation", labels: ["serious injury", "hospitalisation"] },
  { label: "Moderate injury /\nmedical treatment", labels: ["moderate injury", "medical treatment"] },
  { label: "Other / minor\ninjury", labels: ["minor/other injury", "other injury", "minor injury"] },
  { label: "Non-injury /\ntowaway", labels: ["non-injury", "non-casualty (towaway)"] },
];
const key = (label: string) => label.trim().toLowerCase();
const validCount = (value: number) => Number.isFinite(value) && value >= 0;

/** Shared display grouping only; keeps each native observation and its metrics intact. */
export function groupSeverityCategories<T extends Pick<Severity, "label" | "source">>(rows: T[], requestedSources: Source[] = []) {
  const sources = [...new Set([...requestedSources, ...rows.flatMap(row => row.source ? [row.source] : [])])];
  const multiple = sources.length > 1;
  const sourceKeys = sources.length ? sources : [undefined];
  const slot = (row: T) => multiple
    ? displayGroups.find(group => group.labels.includes(key(row.label)))?.label ?? row.label
    : row.label;
  // If a source supplies two native categories for one display slot, retain
  // separate native categories rather than merging, overwriting or dropping them.
  const ambiguous = new Set(rows.filter(row => rows.some(other =>
    other !== row && other.source === row.source && slot(other) === slot(row))).map(slot));
  const resolvedSlot = (row: T) => ambiguous.has(slot(row)) ? row.label : slot(row);
  const labels = [...new Set(rows.map(resolvedSlot))];
  if (multiple) labels.sort((a, b) => {
    const order = (label: string) => {
      const index = displayGroups.findIndex(group => group.label === label);
      return index < 0 ? displayGroups.length : index;
    };
    return order(a) - order(b);
  });
  const groups = labels.map(label => ({
    label,
    rows: sourceKeys.map(source => rows.find(row => row.source === source && resolvedSlot(row) === label) ?? null),
  }));
  return { sources, multiple, groups };
}

export function severityComparison(rows: SeverityValue[], requestedSources: Source[] = []) {
  const { sources, multiple, groups } = groupSeverityCategories(rows, requestedSources);
  const sourceKeys = sources.length ? sources : [undefined];
  const totals = sourceKeys.map(source => rows.filter(row => row.source === source && validCount(row.count)).reduce((sum, row) => sum + row.count, 0));
  return { sources, multiple, groups, series: sourceKeys.map((source, index) => ({
    source,
    counts: groups.map(group => group.rows[index] && validCount(group.rows[index]!.count) ? group.rows[index]!.count : null),
    shares: groups.map(group => {
      const row = group.rows[index];
      if (!row || !validCount(row.count)) return null;
      if ("share" in row) return row.share != null && Number.isFinite(row.share) && row.share >= 0 && row.share <= 1 ? row.share * 100 : null;
      return totals[index] > 0 ? row.count / totals[index] * 100 : null;
    }),
  })) };
}

/** Source-native composition. Supplied shares are retained, never renormalised. */
export function severityComposition(rows: SeverityValue[], requestedSources: Source[] = []) {
  const sources = [...new Set([...requestedSources, ...rows.flatMap(row => row.source ? [row.source] : [])])];
  return (sources.length ? sources : [undefined]).map(source => {
    const nativeRows = rows.filter(row => row.source === source);
    const total = nativeRows.filter(row => validCount(row.count)).reduce((sum, row) => sum + row.count, 0);
    const segments = nativeRows.map(row => {
      const tone = displayGroups.findIndex(group => group.labels.includes(key(row.label)));
      const share = !validCount(row.count) ? null : "share" in row
        ? row.share != null && Number.isFinite(row.share) && row.share >= 0 && row.share <= 1 ? row.share * 100 : null
        : total > 0 ? row.count / total * 100 : null;
      return {...row, share, tone: tone < 0 ? 5 : tone};
    }).sort((a, b) => a.tone - b.tone);
    const knownShare = segments.reduce((sum, row) => sum + (row.share ?? 0), 0);
    const available = segments.some(row => row.share !== null) && knownShare <= 100 + 1e-8;
    return {source, segments, available, knownShare,
      unclassifiedShare: available ? Math.max(0, 100 - knownShare) : null};
  });
}

export function formatSeverityShare(value: number | null) {
  return value == null ? "Unavailable" : value > 0 && value < .1 ? "<0.1%" : `${value.toLocaleString("en-AU", {maximumFractionDigits:1})}%`;
}
