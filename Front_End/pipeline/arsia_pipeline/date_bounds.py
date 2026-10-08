"""Supported representation bounds, not evidence of any source's coverage."""
import json
from pathlib import Path
_BOUNDS = json.loads((Path(__file__).parent/'knowledge/date-range.json').read_text())
MIN_YEAR, MAX_YEAR = _BOUNDS['min_year'], _BOUNDS['max_year']
