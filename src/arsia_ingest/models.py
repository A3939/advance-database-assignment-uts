"""Data classes and errors used during input preparation."""
from dataclasses import dataclass, field
from pathlib import Path


class IntakeError(Exception):
    """An error that stops preparation and carries details for the run log."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details = details

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": str(self), **self.details}


@dataclass(frozen=True)
class ResourceSpec:
    source_id: str
    resource_id: str
    resource_role: str
    entity_kind: str
    path: Path
    format: str
    header: tuple[str, ...]
    encoding: str | None = None
    sheet: str | None = None
    header_row: int = 1
    expected_sha256: str | None = None

    @property
    def parser_version(self) -> str:
        return {"csv": "csv-native-v1", "xlsx": "xlsx-native-v1"}[self.format]

    @property
    def locator_version(self) -> str:
        return {"csv": "csv-logical-v1", "xlsx": "xlsx-physical-v1"}[self.format]


@dataclass
class ParseStats:
    header: list[str] = field(default_factory=list)
    raw_count: int = 0
    blank_records_skipped: int = 0
    trailing_rows_skipped: int = 0
    records_seen: int = 0


@dataclass(frozen=True)
class NativeRow:
    row_locator: str
    payload: dict[str, str | None]


@dataclass(frozen=True)
class IntakeConfig:
    dataset_kind: str
    resources: tuple[ResourceSpec, ...]
    config_path: Path
