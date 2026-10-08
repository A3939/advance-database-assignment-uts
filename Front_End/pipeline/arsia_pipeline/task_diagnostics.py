"""Untrusted Python diagnostics under the existing Docker execution boundary.

Reports never enter the registry, canonical loader, or source evidence registry.
The AST check is a preflight convenience; Docker is the access-control boundary.
"""
import ast
import json
from pathlib import Path
import time

from .errors import BudgetExhausted

IMPORTS = {'csv', 'json', 'collections', 'datetime', 'math', 'statistics', 'decimal',
           're', 'hashlib', 'itertools', 'pathlib', 'sqlite3', 'arsia_pipeline.intakereaders'}
PURPOSES = {'schema_comparison', 'key_relationships', 'value_comparison', 'coordinate_comparison'}


def preflight(code):
    if not isinstance(code, str) or not 1 <= len(code.encode()) <= 64000:
        raise ValueError('Diagnostic code must be 1–64 KiB')
    tree = ast.parse(code)
    if not any(isinstance(n, ast.FunctionDef) and n.name == 'adapt' for n in tree.body):
        raise ValueError('Define adapt(ctx); inputs are ctx.input_paths and output is ctx.output_dir/report.json')
    for node in ast.walk(tree):
        imports = [x.name for x in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
        if any(name not in IMPORTS for name in imports) or isinstance(node, ast.ImportFrom) and node.level:
            raise ValueError('Diagnostic import outside the reviewed offline data modules')
        if isinstance(node, ast.Name) and node.id in {'eval', 'exec', 'compile', '__import__', 'globals', 'locals', 'getattr', 'setattr', 'delattr'}:
            raise ValueError('Dynamic code or introspection is not a diagnostic operation')
        if isinstance(node, ast.Attribute) and (node.attr.startswith('__') or node.attr in {'system', 'popen', 'connect', 'load_extension'}):
            raise ValueError('Process, network, extension or introspection operation is prohibited')
    return tree


def run(session, args):
    from .repair_context import require_blocker
    from .task_authority import require_files
    from .isolated_executor import run_python
    from .config import read_config
    blocker = require_blocker(session, args['blocker_id'])
    if args.get('purpose') not in PURPOSES:
        raise ValueError('Choose a supported diagnostic purpose')
    files = require_files(session, args['file_ids'])
    preflight(args['code'])
    session.check_budget()
    remaining = session.budget['compute_seconds'] - session.usage['compute_seconds']
    seconds = min(120, int(remaining))
    if seconds < 1:
        raise BudgetExhausted('No cumulative compute budget remains for diagnosis.')
    cfg = read_config()
    started = time.monotonic()
    try:
        result = run_python(args['code'], files, session.work_dir, mode='diagnostic',
            source_contract={}, check_cancelled=session.cancel,
            storage_root=Path(session.job['work_dir']).parent,
            limits={**cfg.get('executor_limits', {}), 'seconds': seconds, 'cpus': 1,
                    'memory_mb': 512, 'pids': 16, 'output_bytes': 16*1024**2},
            ownership={'instance_id': cfg['instance_id'], 'data_root': cfg['data_root'],
                       'job_id': str(session.job['id']), 'attempt_id': str(session.job['attempt_id'])})
    finally:
        # Includes failed/cancelled attempts; changing scripts never resets this.
        session.usage['compute_seconds'] += time.monotonic() - started
        session.persist()
    result['binding'] = {'blocker_id': blocker['blocker_id'], 'purpose': args['purpose'],
                         'inputs': [{'id': f['id'], 'sha256': f['sha256']} for f in files],
                         'job_id': str(session.job['id']), 'attempt_id': str(session.job['attempt_id'])}
    result['authority'] = 'untrusted_diagnostic_only'
    result['admission'] = False
    report = Path(result['output_dir']) / 'report.json'
    if result['status'] == 'succeeded' and report.is_file() and not report.is_symlink():
        if report.stat().st_size > 64000:
            result['report_error'] = 'Report exceeds 64 KiB; retain local evidence and summarize it.'
        else:
            try:
                result['report'] = json.loads(report.read_text())
            except (ValueError, UnicodeError):
                result['report_error'] = 'Report must be valid UTF-8 JSON.'
    session.runtime_state.setdefault('diagnostic_runs', []).append({k: result[k] for k in
        ('run_id', 'binding', 'status', 'code_sha256', 'authority')})
    return result
