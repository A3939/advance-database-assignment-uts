import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {ImportAgentProgress} from '../src/components/import-agent-progress';
import {qualityForEvidence, sourceForEvidence} from '../src/components/import-evidence';
import {importAction, importOutcomeLabel, type LocalImportAgentStatus, type LocalImportJob, type ImportOutcome} from '../src/services/imports-contracts';
const outcome: ImportOutcome = {version:'import-outcome-v1',task_mode:'candidate_validation_only',phase:'candidate_verified',terminal_for_task_mode:true,execution:{status:'completed',raw_exit_code:130},validation:{status:'passed',receipt_status:'verified_current',scope:'research_candidate',qa_run_count:1,check_count:3,checks_passed:3},goal_coverage:{status:'satisfied_with_source_limits',requested_goals_satisfied:true,original_goal_satisfied:false},publication:{status:'not_published'},official_identity:{status:'unverified'},active_blockers:[],historical_blockers:[],actions:{add_files:false,submit:false,retry:false,cancel:false,view_evidence:true},action_reasons:{},counts:{scope:'current_attempt',full_runs:1,sample_runs:0,qa_checks:1,unknown_conversion_steps:0,unknown_qa_steps:0},source_limits:[{count:2}],limitations:[],unverified_capabilities:['displayed_map']};

test('current host outcome drives label actions and dynamic QA count',()=>{
 const job={status:'needs_input',outcome} as LocalImportJob;
 assert.match(importOutcomeLabel(job),/Verified/);
 for(const action of ['submit','add_files','cancel','retry'] as const)assert.equal(importAction(job,action),false);
 const html=renderToStaticMarkup(<ImportAgentProgress agent={{status:'needs_input',phase:outcome.phase,outcome,model_calls:0,tool_calls:9,correction_count:0,latest_steps:[],checks:{full_runs:1,sample_runs:0,qa_checks:1}}}/>);
 for(const text of ['Research candidate verified','No further input','3 checks recorded','Independent QA runs','displayed map: not verified','No unresolved blockers'])assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/Waiting for specific information|7 checks|176226/);
 assert.doesNotMatch(html,/aria-current="step">Publish/);
});
test('engineering fixture retains engineering stop',()=>{
 const html=renderToStaticMarkup(<ImportAgentProgress agent={{status:'needs_input',phase:'engineering_required',model_calls:0,tool_calls:0,correction_count:0,latest_steps:[]}}/>);
 assert.match(html,/Waiting for a system update/);assert.doesNotMatch(html,/Research candidate verified|add the missing file/);
});
test('QA empty/null fallbacks and invalid current receipt never borrows its QA',()=>{
 const qa=[{code:'QA01',status:'pass',message:'recorded'}];
 for(const value of [null,[],undefined])assert.deepEqual(qualityForEvidence({job:{qa:value,result:{qa}}}),qa);
 assert.deepEqual(qualityForEvidence({job:{qa:[]},candidate:{receipt_status:'verified_current',qa}}),qa);
 assert.deepEqual(qualityForEvidence({job:{qa:[]},candidate:{receipt_status:'evidence_invalid',qa}}),[]);
});

test('published source is not shadowed by empty research source',()=>{
 const source={title:'Published fixture',publisher:'Publisher'};
 assert.deepEqual(sourceForEvidence({job:{result:{source}},candidate:{source:{source_name:null,publisher:null}}}),source);
 assert.deepEqual(sourceForEvidence({job:{result:{source}},candidate:{source:{source_name:'Research fixture'}}}),{source_name:'Research fixture'});
});

test('historical unconfirmed observations are not labelled resolved and active counts stay explicit',()=>{
 const current={id:'scope-a',code:'SCOPE_ACTION_MISSING',category:'resource_applicability',owner:'agent',message:'Bound action is missing',status:'active'};
 const value={...outcome,phase:'needs_input',active_blockers:[current],historical_blockers:[{id:'older',status:'unconfirmed',message:'Earlier observation needs review'}]};
 const html=renderToStaticMarkup(<ImportAgentProgress agent={{status:'needs_input',phase:'needs_input',outcome:value,model_calls:0,tool_calls:0,correction_count:0,latest_steps:[],blocker_summary:{active_count:1,engineering_count:0,scope_issue_count:0,blockers:[current],unmet_goals:[],goal_satisfied:false,count_scope:'host issues'},repair:{original_goal:'Preserve requested goals',requested_context:'Explicit display fixture',target_satisfied:false,current_blocker:current.message,diagnostic_attempts:[],limitations:[]}}}/>);
 assert.match(html,/1 active blockers/);assert.match(html,/Current blocker:/);assert.match(html,/Bound action is missing/);
 assert.match(html,/Historical issues · resolution and applicability/);assert.match(html,/unconfirmed/);
 assert.doesNotMatch(html,/Resolved historical issues|No unresolved blockers/);
});

test('trusted host attention drives current title and appropriate suggestions without changing authority', async()=>{
 const {importSuggestedAction}=await import('../src/services/imports-contracts');
 for(const kind of ['resource_observation_failed','budget_exhausted','budget_unconfirmed','authorization_boundary']){
  const attention={kind,title:'Stopped for host review',description:'Review retained host evidence before requesting any new run.',review_required:true};
  const value={...outcome,phase:'needs_input',attention,actions:{add_files:true,submit:true,retry:true,cancel:true,view_evidence:true}};
  const job={status:'needs_input',outcome:value} as LocalImportJob;
  assert.equal(importOutcomeLabel(job),attention.title);
  for(const action of ['add_files','submit','retry'] as const){assert.equal(importAction(job,action),true);assert.equal(importSuggestedAction(job,action),false);}
  assert.equal(importSuggestedAction(job,'cancel'),true);assert.equal(importSuggestedAction(job,'view_evidence'),true);
  const html=renderToStaticMarkup(<ImportAgentProgress agent={{status:'needs_input',phase:'needs_input',outcome:value,model_calls:0,tool_calls:0,correction_count:0,latest_steps:[]}}/>);
  assert.match(html,/Stopped for host review/);assert.doesNotMatch(html,/Waiting for specific information|add the missing file|try again automatically/);
 }
 const information={...outcome,phase:'needs_input',attention:{kind:'evidence_missing',title:'Waiting for specific information',description:'A definition is required',review_required:false},actions:{...outcome.actions,submit:true,add_files:true}};
 assert.equal(importSuggestedAction({status:'needs_input',outcome:information} as LocalImportJob,'submit'),true);
 for(const action of ['add_files','submit','retry','cancel'] as const)assert.equal(importSuggestedAction({status:'needs_input',outcome} as LocalImportJob,action),false);
});

const originalGoalRepair = {
 original_goal:'Ingest and independently validate Australian road-safety data',
 requested_context:'Validate an unpublished research candidate. Registration and publication are not authorized.',
 target_satisfied:false,diagnostic_attempts:[],limitations:[],
};
function renderGoalProgress(value: ImportOutcome | undefined, repair = originalGoalRepair) {
 const agent: LocalImportAgentStatus={status:'needs_input',phase:value?.phase ?? 'needs_input',outcome:value,model_calls:13,tool_calls:59,correction_count:0,latest_steps:[],repair};
 const before=structuredClone(agent);
 const html=renderToStaticMarkup(<ImportAgentProgress agent={agent}/>);
 assert.deepEqual(agent,before,'Presentation must preserve the original goal and host facts');
 return html;
}

test('completed candidate goals remain distinct from the unverified broader original goal',()=>{
 const html=renderGoalProgress(outcome);
 assert.match(html,/Requested candidate goals: satisfied with source limits/);
 assert.match(html,/The requested goals for this candidate validation are satisfied/);
 assert.match(html,/The broader original goal remains unverified/);
 assert.match(html,/Official identity and publication require separate verification and authorization/);
 assert.match(html,/Original goal:/);
 assert.match(html,/Ingest and independently validate Australian road-safety data/);
 assert.match(html,/Registration and publication are not authorized/);
 assert.doesNotMatch(html,/A published limited result does not establish the remaining capabilities/);
 assert.doesNotMatch(html,/The original goal is not fully verified/);
});

for(const [name,value] of [
 ['partial candidate',{...outcome,phase:'candidate_partial',goal_coverage:{...outcome.goal_coverage,requested_goals_satisfied:false}}],
 ['unconfirmed goals',{...outcome,goal_coverage:{...outcome.goal_coverage,requested_goals_satisfied:null}}],
 ['unmet goals',{...outcome,goal_coverage:{...outcome.goal_coverage,requested_goals_satisfied:false}}],
 ['nonterminal task',{...outcome,terminal_for_task_mode:false}],
 ['unconfirmed receipt',{...outcome,validation:{...outcome.validation,receipt_status:'historical_unconfirmed'}}],
 ['host failure after QA',{...outcome,phase:'failed'}],
 ['invalid current receipt',{...outcome,phase:'evidence_invalid'}],
 ['publication task',{...outcome,task_mode:'import',phase:'publication_waiting'}],
 ['legacy response',undefined],
] as const) test(`${name} does not borrow candidate completion wording`,()=>{
 const html=renderGoalProgress(value);
 assert.match(html,/The original goal is not fully verified/);
 assert.doesNotMatch(html,/The requested goals for this candidate validation are satisfied/);
 assert.match(html,/Ingest and independently validate Australian road-safety data/);
});

test('an already satisfied original goal does not acquire an unverified warning',()=>{
 const html=renderGoalProgress(outcome,{...originalGoalRepair,target_satisfied:true});
 assert.doesNotMatch(html,/The broader original goal remains unverified|The original goal is not fully verified/);
});
