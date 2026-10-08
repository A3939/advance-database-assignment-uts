"""Cold-process entry for explicit, newly owned source acceptance runs.

The coordinator creates and finalizes only this invocation's TestSession. The
worker imports business modules after its immutable runtime environment is set.
No old laboratory, normal runtime, job or model credentials are adopted.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def copy_public_reference(file, directory):
    """Copy an actual archived host receipt into a new owned instance.

    No evidence URL, retrieval time or byte content is rewritten. This is an
    explicit developer acceptance harness, not an Agent-supplied receipt tool.
    """
    import copy
    import hashlib
    import shutil
    from arsia_pipeline.source_binding import reference_receipt
    directory=Path(directory);(directory/'sha256').mkdir(parents=True,exist_ok=True)
    original=Path(file['receipt_path'])
    # Validate the archived capture in its original content-addressed directory
    # before copying; the normal runtime is neither opened nor modified.
    reference_receipt(file,original.parent)
    result=copy.deepcopy(file)
    target=directory/'sha256'/file['sha256']
    if not target.exists():shutil.copyfile(file['path'],target)
    receipt_hash=hashlib.sha256(original.read_bytes()).hexdigest()
    receipt=directory/(receipt_hash+'.json')
    if not receipt.exists():shutil.copyfile(original,receipt)
    result.update(path=str(target),receipt_path=str(receipt))
    reference_receipt(result,directory)
    return result


def child_config(output):
    from arsia_pipeline.config import CONFIG, read_config
    cfg = read_config()
    if (not cfg.get('test_session_id') or not cfg.get('storage_policy', {}).get('enabled')
            or cfg['instance_id'] != os.environ.get('ARSIA_ACCEPTANCE_INSTANCE')
            or Path(cfg['storage_home']).resolve() != output.resolve()
            or CONFIG != Path(cfg['data_root']) / 'runtime.json'):
        raise RuntimeError('Acceptance worker requires its newly owned, immutable runtime')
    return cfg


def launch(args, *, suite, configure=None):
    if args.storage_policy != 'keep-full':
        raise ValueError('Source acceptance retains all evidence; use keep-full')
    if os.environ.get('ARSIA_IMPORT_CONFIG'):
        raise RuntimeError('Start acceptance outside a bound runtime; never inherit another laboratory')
    from arsia_pipeline.test_session import TestSession
    from arsia_pipeline.storage_lifecycle import atomic_json
    session = TestSession.create(args.output.resolve(), suite=suite,
        postgres_image='efedf3595f1d', executor_image=args.executor_image,
        keep_full=True)
    output = args.output.resolve()
    env = dict(os.environ, ARSIA_IMPORT_CONFIG=str(Path(session.cfg['data_root']) / 'runtime.json'),
        ARSIA_ACCEPTANCE_INSTANCE=session.cfg['instance_id'])
    started = time.monotonic(); code = 1
    try:
        if configure:
            configure(session.cfg)
            atomic_json(Path(session.cfg['data_root'])/'runtime.json',session.cfg)
        # Streaming stdout preserves stage visibility without buffering full logs.
        result = subprocess.run([sys.executable, str(Path(sys.argv[0]).resolve()),
            *sys.argv[1:], '--owned-child'], env=env, timeout=7200)
        code = result.returncode
        atomic_json(output/'process-result.json', {'returncode': code,
            'wall_seconds': time.monotonic()-started, 'cold_runtime_binding': True,
            'instance_id': session.cfg['instance_id'], 'test_session_id':session.cfg['test_session_id']})
    finally:
        atomic_json(output/'storage-finalize.json', session.finish(success=code==0))
    return code
