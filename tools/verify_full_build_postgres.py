#!/usr/bin/env python3
"""Run real S0 builds from an installed wheel in disposable PostgreSQL 16."""
import argparse
import json
from pathlib import Path

from verify_ac_postgres import main
from verify_d04_lineage_postgres import check_schema

if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output', type=Path, required=True)
    args, _ = parser.parse_known_args()
    check_schema()
    result = main(
        inventory_path='config/build-inventory.json',
        tests=('test_build_integration.py', 'test_full_build_postgres.py',
               'test_e_gate_contract.py', 'test_e_publication.py', 'test_e_integrated_postgres.py',
               'test_runner.py', 'test_recovery.py', 'test_manifest.py', 'test_cd_inventory.py'),
        scope='Real three-source S0 build: installed A/B/C/D/E, FP1, seven QA groups, publication and recovery',
    )
    path = args.output.resolve() / 'summary.json'
    summary = json.loads(path.read_text(encoding='utf-8'))
    summary.update(publication_performed=None if result else True,
                   publication_scope='Private synthetic test database; no official release',
                   full_s0_build_verified=result == 0, final_platform_accepted=False,
                   boundary='D09, official replay, S8 and independent E/platform acceptance remain separate')
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(result)
