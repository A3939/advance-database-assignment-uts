"""Use this repository after integration, or the neighbouring B checkout."""
import os
from pathlib import Path
import sys

PACKAGE = Path(__file__).resolve().parents[1]
DEFAULT_REPO = PACKAGE if (PACKAGE / "src/arsia_ingest").is_dir() else PACKAGE.parent / "Workspace/Workspace_Github"
REPO = Path(os.environ.get("ARSIA_REPOSITORY", DEFAULT_REPO))
if os.environ.get("AC_REQUIRE_INSTALLED") != "1":
    sys.path[:0] = [str(PACKAGE / "src"), str(REPO / "src")]
else:
    import arsia_c
    import arsia_ingest

    for module in (arsia_c, arsia_ingest):
        assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
