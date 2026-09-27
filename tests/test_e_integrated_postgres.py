"""Re-run E's unchanged database regressions with B's actual build manifest."""
import os

import pytest

if 'AC_TEST_RUN' not in os.environ:
    pytest.skip('Use tools/verify_full_build_postgres.py', allow_module_level=True)

from arsia_ingest.build import s0_request
from test_cd_integration_postgres import ROOT, prepared, private_database
from test_raw_load_postgres import connection
from test_e_postgres import (
    deployment,
    test_real_producers_fp1_publish_and_caller_rollback,
    test_fp1_pg16_utf8_canonical_json_and_b_normalization,
    test_fp1_only_grants_loader_usage_and_execute,
    test_gate_rejects_fault_and_keeps_running_batch,
    test_context_mismatch_rejected,
    test_rollback_preserves_previous_release,
)


@pytest.fixture
def frozen(prepared):
    return s0_request(connect=None, project_root=ROOT, prepared_run=prepared[0],
                      evidence_root=prepared[1] / 'build')['manifest']
