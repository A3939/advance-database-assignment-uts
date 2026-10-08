import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { routeModel } from '../src/server/agent/model-routing';
import { createModelAudit } from '../src/server/agent/model-audit';

test('simple bilingual questions use Terra; reasoning and ambiguity use Sol', () => {
  for (const message of ['你好', '什么是致命事故？', '死亡人数是什么意思？', '请显示事故总数', 'Please show crash counts', 'How many crashes are in the selected period?', '显示事故总数', '有多少死亡人数？']) {
    const route=routeModel({surface:'ask',message,source:'NSW'});
    assert.equal(route.model,'gpt-5.6-terra',message);
    assert.equal(route.reasoningEffort,'high');
  }
  for (const message of ['为什么死亡人数增加？', 'Compare crashes in 2023 and 2024', 'What is the average crash count?', '显示事故数量的分布', '计算事故数的同比变化', 'Explain the coordinate system', '这个结果合理吗？', '显示事故数以及伤亡人数'])
    assert.equal(routeModel({surface:'ask',message,source:'NSW'}).model,'gpt-6.1-sol',message);
  assert.equal(routeModel({surface:'ask',message:'多少事故？',historyCount:1}).model,'gpt-6.1-sol');
  assert.equal(routeModel({surface:'ask',message:'Show crash counts',source:'ALL'}).model,'gpt-6.1-sol');
});
test('research and onboarding use Sol regardless of short user text', () => {
  for (const surface of ['studio','imports'] as const)
    assert.equal(routeModel({surface,message:'hi'}).model,'gpt-6.1-sol');
});
test('routing receipt records exact model and usage without question content', async () => {
  const dir=await mkdtemp(join(tmpdir(),'arsia-routing-test-'));
  const route=routeModel({surface:'ask',message:'How many crashes?',source:'NSW'});
  const audit=await createModelAudit(route,'ask',dir);
  await audit.response({id:'response-test',model:route.model,status:'completed'});
  await audit.finish('completed');
  const text=await readFile(join(dir,(await readdir(dir)).find(name=>name.endsWith(".jsonl"))!),'utf8');
  const rows=text.trim().split('\n').map(s=>JSON.parse(s));
  assert.equal(rows[0].route.model,'gpt-5.6-terra');
  assert.equal(rows[1].usage,null);
  assert.equal(rows[2].status,'completed');
  assert.equal(text.includes('How many crashes?'),false);
});

test('a started request with no final receipt remains unknown after failure', async () => {
  const dir=await mkdtemp(join(tmpdir(),'arsia-routing-unknown-'));
  const audit=await createModelAudit(routeModel({surface:'ask',message:'Counts'}),'ask',dir);
  await audit.request('request-no-response'); await audit.finish('failed');
  const rows=(await readFile(join(dir,(await readdir(dir)).find(name=>name.endsWith(".jsonl"))!),'utf8')).trim().split('\n').map(s=>JSON.parse(s));
  assert.equal(rows[1].usage,null);assert.equal(rows[1].usageStatus,'unknown');
  assert.equal(rows.at(-1).unknownRequests,1);assert.equal(rows.at(-1).usageComplete,false);
});
