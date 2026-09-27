#!/usr/bin/env python3
"""Run AT15 and S0 regressions from an installed wheel in private PG16."""
import argparse
import json
from pathlib import Path

from verify_ac_postgres import ROOT, main, record
from verify_d04_lineage_postgres import check_schema

if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output', type=Path, required=True)
    args, _ = parser.parse_known_args()
    check_schema()
    result = main(
        inventory_path='config/build-inventory.json',
        tests=('test_build_integration.py', 'test_project_dispatcher.py', 'test_s8.py', 'test_s8_projection.py',
               'test_s8_projection_postgres.py', 'test_s8_qa_expectations.py',
               'test_s8_build_postgres.py', 'test_full_build_postgres.py',
               'test_e_gate_contract.py', 'test_e_publication.py', 'test_e_integrated_postgres.py',
               'test_runner.py', 'test_recovery.py', 'test_manifest.py', 'test_cd_inventory.py'),
        scope='AT15: real S0/S8 builds, independent Raw QA, FP1, publication, D05-D08 and rollback',
    )
    inputs_path = args.output.resolve() / 'inputs.json'
    inputs = json.loads(inputs_path.read_text(encoding='utf-8'))
    inputs['test_dependencies'].append(record(ROOT / 'tools/create_s0_inputs.py'))
    inputs_path.write_text(json.dumps(inputs, indent=2) + '\n', encoding='utf-8')
    path = args.output.resolve() / 'summary.json'
    summary = json.loads(path.read_text(encoding='utf-8'))
    summary.update(at15_verified=result == 0, full_s0_regression_verified=result == 0,
                   publication_performed=True if result == 0 else None,
                   publication_scope='Private synthetic database; no official release',
                   final_platform_accepted=False,
                   boundary='Independent E sign-off, D09 and official replay remain separate')
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(result)
