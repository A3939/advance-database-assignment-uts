"""Source-specific read boundary for the pinned official build."""
from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_d08 import UnitRequest, query_units

from .models import IntakeError


def query_official(connection, *, batch_id, source_id, report,
                   year_from=None, year_to=None, months=None, grain="year"):
    """Read one successful batch and report unavailable outputs explicitly."""
    if source_id not in ("official_nsw", "official_vic", "official_qld"):
        raise IntakeError("OFFICIAL_READER", "Select one supported official source")
    if report not in ("trend", "severity", "map", "units"):
        raise IntakeError("OFFICIAL_READER", "Unknown official report")
    filters = dict(source_ids=(source_id,), year_from=year_from,
                   year_to=year_to, months=months)
    request = TrendRequest("official", batch_id, grain=grain, **filters)
    # D05 checks publication, namespace, source and coverage even for disabled reports.
    trend = query_trend(connection, request)
    labels = {"official_nsw": "NSW pinned Crash / Traffic Unit snapshot",
              "official_vic": "VIC restricted Accident snapshot",
              "official_qld": "QLD pinned crash snapshot"}
    limits = ["Official maps are unavailable.",
              "Source definitions differ; do not pool interstate totals."]
    if source_id == "official_vic":
        limits.append("Accident metrics only; Person and Vehicle rows are retained for checks, not reporting.")
    elif source_id == "official_qld":
        limits.append("No unit-detail records are available in this resource.")
    result = {"dataset_kind": "official", "batch_id": request.parameters()[1],
              "source_id": source_id, "report": report, "status": "available",
              "reason": None, "rows": None,
              "source_label": labels[source_id], "quality_limits": limits,
              "coverage_basis": sorted({row["coverage_basis"] for row in trend
                                         if row.get("coverage_basis")}),
              "comparison_scope": "This source only; interstate totals are not supported."}
    if report == "map":
        result.update(status="unavailable", reason="Official maps are disabled by the pinned source policy.")
    elif report == "units" and source_id != "official_nsw":
        reason = ("The VIC restricted profile excludes vehicle and person statistics."
                  if source_id == "official_vic" else "This QLD resource has no unit-detail records.")
        result.update(status="unavailable", reason=reason)
    elif report == "trend":
        result["rows"] = trend
    elif report == "severity":
        result["rows"] = query_severity(connection, SeverityRequest("official", batch_id, **filters))
    else:
        result["rows"] = query_units(connection, UnitRequest("official", batch_id, **filters))
    return result
