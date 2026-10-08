import type { PreprocessingQuality } from '../services/preprocessing-contracts';

const display = (value: number | undefined) => value === undefined ? 'Not reported' : value.toLocaleString('en-AU');
export function ImportPreprocessingQuality({ report, official, goalSatisfied }: {
  report?: PreprocessingQuality;
  official?: boolean;
  goalSatisfied?: boolean;
}) {
  if (!report || report.status === 'unavailable') return <p>Preprocessing quality report not provided for this release.</p>;
  return <section aria-label="Preprocessing quality">
    <h3>{report.status === 'partial' ? 'Partial research result' : 'Preprocessing quality'}</h3>
    <p>{display(report.raw_rows)} original rows · {display(report.usable_crashes)} usable crash records.</p>
    <p>{display(report.dispositions?.duplicate_of)} duplicates · {display(report.dispositions?.quarantined)} quarantined · {display(report.dispositions?.excluded_by_scope)} explicitly excluded. Original rows remain traceable.</p>
    <p>{display(report.unknown_date_count)} crash records have unknown dates. All-time counts include these records; date filters cannot assign them to an interval. {display(report.unlocated_crash_count)} records have no verified map position.</p>
    {Object.entries(report.metrics || {}).map(([metric, values]) => <p key={metric}>{metric}: {values.known_count} known, {values.unknown_count} unknown, {values.invalid_count} invalid. Known subtotal: {values.known_subtotal}; this is not a complete total when values are missing.</p>)}
    <p>Official identity: {official === true ? 'verified' : 'unverified'}. Original goal: {goalSatisfied === true ? 'satisfied' : goalSatisfied === false ? 'not satisfied' : 'not reported'}.</p>
    <details><summary>Applied rules and evidence</summary><p>{report.rules?.join(', ') || 'Not reported'}</p><p>New Agent judgment: {report.agent_new_judgment === true ? 'yes' : report.agent_new_judgment === false ? 'no' : 'not reported'}.</p><p>Profile reference: {report.plan?.profile_sha256 || 'Not reported'}</p><p>{report.plan?.authority}</p></details>
  </section>;
}
