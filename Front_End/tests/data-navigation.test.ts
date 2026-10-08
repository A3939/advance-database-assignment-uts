import test from "node:test";
import assert from "node:assert/strict";
import { dataTab, importsDataHref, workspaceParameters, preservePageSelection } from "../src/services/data-navigation";
import { parseAnalysisState } from "../src/services/analysis-state";

test("legacy import links move to Data while preserving exact pinned query values", () => {
  const query = { source: "custom source", releaseId: "release-1", from: "2020-01-01", tab: "library", repeated: ["one", "two"] };
  const target = new URL(importsDataHref(query), "http://localhost");
  assert.equal(target.pathname, "/data");
  assert.equal(target.searchParams.get("tab"), "imports");
  assert.equal(target.searchParams.get("source"), "custom source");
  assert.equal(target.searchParams.get("releaseId"), "release-1");
  assert.deepEqual(target.searchParams.getAll("repeated"), ["one", "two"]);
});
test("Data tab is removed only from Data analysis validation, never loosening unrelated parameters", () => {
  assert.equal(parseAnalysisState(workspaceParameters("/data", "?tab=imports").toString()).error, undefined);
  assert.match(parseAnalysisState(workspaceParameters("/", "?tab=imports").toString()).error!, /Unknown analysis parameter/);
  assert.match(parseAnalysisState(workspaceParameters("/data", "?tab=imports&bogus=1").toString()).error!, /Unknown analysis parameter/);
});
test("release restoration preserves independent Data tab and Studio selection", () => {
  assert.equal(preservePageSelection("/data", "/data?releaseId=R", "?tab=imports"), "/data?releaseId=R&tab=imports");
  assert.equal(preservePageSelection("/studio", "/studio?releaseId=R", "?study=S"), "/studio?releaseId=R&study=S");
  assert.equal(preservePageSelection("/", "/?releaseId=R", "?tab=imports&study=S"), "/?releaseId=R");
  assert.equal(workspaceParameters("/studio", "?study=S&releaseId=R").toString(), "releaseId=R");
});
test("unknown or repeated Data tab values use the library, without changing import authority", () => {
  assert.equal(dataTab("imports"), "imports");
  for (const value of ["library", "unknown", undefined, null, ["imports", "library"]]) assert.equal(dataTab(value), "library");
});

import { studyHref } from "../src/services/studio-client";
import { DEFAULT_FILTERS } from "../src/services/config";
test("Studio links pin the saved study filters and retain local release identity", () => {
  for (const filters of [DEFAULT_FILTERS, { ...DEFAULT_FILTERS, source: "dataset-27", datasetVersion: "local-integrated-v1", batchId: "batch-27", releaseId: "batch-27" }]) {
    const study = { id: "study-27", context: { filters, metric: "crashes" as const, notes: "", references: "" } };
    const url = new URL(studyHref(study), "http://localhost");
    assert.equal(url.pathname, "/studio");
    for (const key of ["source", "datasetVersion", "batchId"] as const) assert.equal(url.searchParams.get(key), filters[key]);
    assert.equal(url.searchParams.get("releaseId"), filters.releaseId ?? null);
    assert.equal(url.searchParams.get("study"), study.id);
  }
});

test("Studio workspace mode survives restoration without entering analysis validation", () => {
  for (const mode of ["explore", "document", "findings"]) {
    const query=`?study=S&studioView=${mode}`;
    assert.equal(parseAnalysisState(workspaceParameters("/studio",query).toString()).error,undefined);
    assert.equal(preservePageSelection("/studio","/studio?releaseId=R",query),`/studio?releaseId=R&study=S&studioView=${mode}`);
  }
  assert.match(parseAnalysisState(workspaceParameters("/analytics","?studioView=explore").toString()).error!,/Unknown analysis parameter/);
  assert.match(parseAnalysisState(workspaceParameters("/studio","?studioView=explore&bogus=1").toString()).error!,/Unknown analysis parameter/);
});
