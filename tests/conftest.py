"""Use this repository after integration, or the neighbouring B checkout."""
import os
from pathlib import Path
import sys

PACKAGE = Path(__file__).resolve().parents[1]
DEFAULT_REPO = PACKAGE if (PACKAGE / "src/arsia_ingest").is_dir() else PACKAGE.parent / "Workspace/Workspace_Github"
REPO = Path(os.environ.get("ARSIA_REPOSITORY", DEFAULT_REPO))
sys.path[:0] = [str(PACKAGE / "src"), str(REPO / "src")]
