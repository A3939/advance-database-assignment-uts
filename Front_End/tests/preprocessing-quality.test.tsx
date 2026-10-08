import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ImportPreprocessingQuality } from '../src/components/import-preprocessing-quality';
import type { PreprocessingQuality } from '../src/services/preprocessing-contracts';

test('Q01 old releases never imply zero or complete quality', () => {
  const html = renderToStaticMarkup(<ImportPreprocessingQuality />);
  assert.match(html, /not provided/);
  assert.doesNotMatch(html, /0 duplicates|verified|complete result/);
});
test('Q01 partial records, unknown counts and unsatisfied original goal survive rendering', () => {
  const report: PreprocessingQuality = {status:'partial',raw_rows:9,usable_crashes:4,dispositions:{retained:4,duplicate_of:1,quarantined:3,excluded_by_scope:1},unknown_date_count:2,unlocated_crash_count:4,metrics:{fatalities:{known_count:2,unknown_count:1,invalid_count:1,known_subtotal:0}},agent_new_judgment:false,rules:['PP05','PP12']};
  const html = renderToStaticMarkup(<ImportPreprocessingQuality report={report} official={false} goalSatisfied={false} />);
  for (const text of ['Partial research result','9 original rows','4 usable crash records','2 crash records have unknown dates','unverified','not satisfied','not a complete total','PP05, PP12']) assert.ok(html.includes(text));
});
