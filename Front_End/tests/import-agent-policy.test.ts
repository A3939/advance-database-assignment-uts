import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { selectImportModelPolicy } from '../src/server/imports/agent-policy';
import { validateGatewayBody } from '../src/server/imports/agent-model';

const catalog = readFileSync(new URL('../pipeline/arsia_pipeline/profiles/agent-policies.json', import.meta.url), 'utf8');
test('import policy preserves explicit model and isolates it from the analysis model', () => {
  const expected = JSON.parse(catalog).profiles['expanded-v1'];
  const selected = selectImportModelPolicy(catalog, 'expanded-v1');
  assert.equal(selected.model, expected.model);
  assert.equal(selected.reasoning_effort, 'high');
  assert.equal(selected.request_timeout_seconds, 600);
  assert.equal(selectImportModelPolicy(catalog).model, 'gpt-6-luna');
  assert.throws(() => selectImportModelPolicy(catalog, '__proto__'));
  assert.throws(() => selectImportModelPolicy(catalog, 'expanded-v1', '0'.repeat(64)));
});
test('model payload cannot inject policy values and catalog drift fails closed', () => {
  const tool = { type: 'function', name: 'read_task_state', parameters: { type: 'object' } };
  const body = validateGatewayBody({ input: [{role:'user',content:'inspect evidence'}], tools:[tool], model:'unauthorized', policy_profile:'expanded-v1' });
  assert.equal('model' in body, false);
  assert.equal(body.policy_profile, 'expanded-v1');
  assert.throws(() => validateGatewayBody({...body, policy_catalog_sha256:'bad'}));
});

test('new import experiment agrees with the application reasoning route', async () => {
  const { routeModel } = await import('../src/server/agent/model-routing');
  const selected=selectImportModelPolicy(catalog,'expanded-v1');
  assert.equal(selected.model,routeModel({surface:'imports'}).model);
  assert.equal(selected.reasoning_effort,routeModel({surface:'imports'}).reasoningEffort);
});
