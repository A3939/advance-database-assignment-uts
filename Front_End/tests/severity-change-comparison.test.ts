import test from "node:test";
import assert from "node:assert/strict";
import type { Source } from "../src/services/contracts";
import type { SeverityChangeRow } from "../src/services/severity-change";
import { groupSeverityCategories } from "../src/services/severity-comparison";

const row = (source: Source, label: string, startShare: number | null, endShare: number | null): SeverityChangeRow & { source: Source } => ({
  source, label, startCount: 10, endCount: 20, startShare, endShare,
  change: startShare === null || endShare === null ? null : endShare - startShare,
});

test("grouped changes retain native identity and unrounded period metrics without pooling states", () => {
  const rows = [row("VIC", "Other injury", 60.345, 66.606), row("QLD", "Hospitalisation", 46.916, 49.108), row("NSW", "Serious Injury", 20.917, 23.544)];
  const before = structuredClone(rows);
  const result = groupSeverityCategories(rows, ["NSW", "VIC", "QLD"]);
  assert.deepEqual(result.sources, ["NSW", "VIC", "QLD"]);
  assert.equal(result.groups[0].label, "Serious injury /\nhospitalisation");
  assert.equal(result.groups[0].rows[0], rows[2]);
  assert.equal(result.groups[0].rows[2], rows[1]);
  assert.equal(result.groups[1].rows[1], rows[0]);
  assert.equal(result.groups[1].rows[1]?.change, 66.606 - 60.345);
  assert.deepEqual(rows, before);
});

test("missing categories, unavailable periods and observed zero remain distinct", () => {
  const zero = row("VIC", "Non-injury", 0, 0);
  const unknown = row("NSW", "Non-casualty (towaway)", null, 30.8);
  const result = groupSeverityCategories([unknown, zero], ["NSW", "VIC", "QLD"]);
  assert.equal(result.groups[0].rows[0]?.startShare, null);
  assert.equal(result.groups[0].rows[0]?.change, null);
  assert.equal(result.groups[0].rows[1]?.startShare, 0);
  assert.equal(result.groups[0].rows[1]?.change, 0);
  assert.equal(result.groups[0].rows[2], null);
});

test("ambiguous and new categories are kept separately rather than overwritten", () => {
  const rows = [row("NSW", "Minor injury", 5, 6), row("NSW", "Other injury", 10, 12), row("VIC", "Other injury", 20, 22), row("QLD", "Unknown severity", 1, 2)];
  const result = groupSeverityCategories(rows, ["NSW", "VIC", "QLD"]);
  assert.deepEqual(result.groups.map(group => group.label), ["Minor injury", "Other injury", "Unknown severity"]);
  assert.deepEqual(new Set(result.groups.flatMap(group => group.rows.filter(Boolean))), new Set(rows));
});

test("single-source native ordering and an unavailable source are retained", () => {
  const rows = [row("QLD", "Medical treatment", 36.7, 30.7), row("QLD", "Fatal", 2.1, 1.9)];
  const result = groupSeverityCategories(rows, ["QLD"]);
  assert.equal(result.multiple, false);
  assert.deepEqual(result.groups.map(group => group.label), rows.map(row => row.label));
  assert.deepEqual(groupSeverityCategories([], ["NSW", "VIC", "QLD"]), { sources: ["NSW", "VIC", "QLD"], multiple: true, groups: [] });
});
