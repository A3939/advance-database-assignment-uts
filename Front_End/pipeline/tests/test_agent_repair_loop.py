"""Deterministic loop regressions. No data model and no official-source claim."""
import copy,json,hashlib
import pytest
from arsia_pipeline import agent,capability_preflight as cp,arcgis_query as aq
from arsia_pipeline.errors import NeedsInput,BudgetExhausted,ImportCancelled,UnsupportedCapability
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.metadata_extractors import MetadataError
from test_arcgis_representation import bundle


def bound_check(c,f,d):
 try:return aq.bind_uploads(c,f,d,build_graph(c['source']['dataset_url'],d,{'query'}),lambda:None)
 except MetadataError as exc:
  raise NeedsInput(str(exc),[],{'grounding':{'issues':[{'code':exc.code,'message':str(exc),**exc.details}]}}) from exc


def test_bounded_partition_binding_does_not_grant_deletion_and_rechecks_range(tmp_path):
 c,f,d,_=bundle(tmp_path,layer=41,year=2018,field='WHEN');c['update']['mode']='partition'
 # Binding a complete uploaded bounded query is independent of whether the
 # subsequent transaction can remove history. Only the latter needs removal
 # authority, which this query cannot grant.
 proof=bound_check(c,f,d)[0]['proofs'][0]
 assert proof['deletion_authority'] is False and c['update']['mode']=='partition'
 c['update']['to']='2018-02-02'
 with pytest.raises(NeedsInput) as e:bound_check(c,f,d)
 assert cp.classified_blockers(e.value)[0]['code']=='ARCGIS_UPDATE_RANGE_CONFLICT'
 c['update']['to']='2018-01-31'
 assert bound_check(c,f,d)[0]['proofs'][0]['deletion_authority'] is False


def test_repair_advice_cannot_be_requested_by_unbound_upload(tmp_path):
 c,f,d,_=bundle(tmp_path);c['update']['mode']='partition';f[0]['sha256']='0'*64
 c['blockers']=[{'kind':'adapter_revision','admission':True}]
 c['deletion_authority']=True
 with pytest.raises(NeedsInput) as e:bound_check(c,f,d)
 rows=cp.classified_blockers(e.value)
 assert rows[0]['code']=='ARCGIS_UPLOAD_HASH_CONFLICT'
 assert 'candidate_repair' not in rows[0]['details']


def test_unknown_host_fault_and_configuration_are_terminal():
 for exc in (RuntimeError('internal bug'),FileNotFoundError('trusted missing'),UnsupportedCapability('OP','No verifier')):
  assert cp.requires_system_change({'blockers':cp.classified_blockers(exc)})
 from arsia_pipeline.config import RuntimeConfigurationError
 assert cp.requires_system_change({'blockers':cp.classified_blockers(RuntimeConfigurationError('Wrong root'))})


def test_budget_inside_preflight_is_not_a_returned_candidate_error(tmp_path,monkeypatch):
 from arsia_pipeline import trusted_qa
 def fail(*a,**kw):raise BudgetExhausted('limit')
 monkeypatch.setattr(trusted_qa,'validate_contract',fail)
 with pytest.raises(BudgetExhausted):cp.preflight_contract({},[],tmp_path,operation_policy=True)


def test_timezone_bundle_integrity_failure_requires_system_repair():
 exc=NeedsInput('Rule bytes damaged',[],{'grounding':{'issues':[{'code':'TIMEZONE_RULE_INTEGRITY','message':'Pinned rule bytes damaged'}]}})
 assert cp.requires_system_change({'blockers':cp.classified_blockers(exc)})


def test_suffix_alone_does_not_decide_responsibility():
 exc=NeedsInput('Need scoped material',[],{'grounding':{'issues':[{'code':'SCOPED_MATERIAL_UNSUPPORTED','message':'Investigate evidence'}]}})
 assert cp.classified_blockers(exc)[0]['kind']=='evidence_missing'
 assert cp.classified_blockers(UnsupportedCapability('SCOPED_MATERIAL_UNSUPPORTED','No reviewed operator'))[0]['kind']=='unsupported_capability'
