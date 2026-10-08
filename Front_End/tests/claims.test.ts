import test from "node:test";
import assert from "node:assert/strict";
import { answerCheck, checkClaims, evidenceAssurance } from "../src/server/agent/claims";
import type { Evidence } from "../src/services/contracts";
import { DEFAULT_FILTERS } from "../src/services/config";

const evidence:Evidence={id:"E1",title:"Metrics",description:"Test only",query:{tool:"core_metrics",parameters:{},requestedContext:{page:"/",filters:DEFAULT_FILTERS}},result:{source:"All",batchId:"fixture",requestedRange:{from:"2024-01-01",to:"2024-12-31"},results:[{source:"NSW",meta:{availability:"available"},data:{crashes:{value:7,availability:"available"},casualties:{value:null,availability:"unknown"}}}]}};
const known=new Map([[evidence.id,evidence]]);
const claim={evidenceId:"E1",pointer:"/results/0/data/crashes/value",source:"NSW",metric:"crashes",from:"2024-01-01",to:"2024-12-31",value:7};
const status=(extra:Record<string,unknown>)=>checkClaims({claims:[{...claim,...extra}]},known).claims[0].status;
test("numerical claims bind exact source, metric, selection, value and evidence",()=>{
  assert.equal(status({}),"supported_exact_value");
  for (const c of [{evidenceId:"E90"},{source:"All"},{source:"VIC"},{metric:"livesLost"},{from:"2023-01-01"},{value:71},{value:1.23},{pointer:"/__proto__/value"},{pointer:"/results/00/data/crashes/value"},{pointer:"/results/0/data/casualties/value",metric:"casualties",value:0}]) assert.equal(status(c),"unsupported");
});
test("catalog and Python execution do not certify a numerical claim",()=>{
  for(const tool of ["workspace_catalog","dataset_metadata","python_analysis"]){
    const data=new Map([["E1",{...evidence,query:{...evidence.query!,tool}}]]);
    assert.equal(checkClaims({claims:[claim]},data).claims[0].status,"unsupported");
  }
  assert.deepEqual(evidenceAssurance("python_analysis",{status:"succeeded"}),{parameters:"validated",execution:"succeeded",claims:"not_automatically_verified"});
});
test("final answer review identifies nonexistent references and catalog-only figures",()=>{
  assert.deepEqual(answerCheck("Seven crashes [E99]",known).unknownEvidence,["E99"]);
  const catalog=new Map([["E1",{...evidence,query:{...evidence.query!,tool:"workspace_catalog"}}]]);
  assert.equal(answerCheck("There were 123 crashes [E1]",catalog).numericWithoutData,true);
  assert.equal(answerCheck("There were 7 crashes [E1]",known).status,"not_exhaustively_verified");
});
