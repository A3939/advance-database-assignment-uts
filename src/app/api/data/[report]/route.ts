import { createRegionalProvider, loadRegionSnapshot, regionEvidence } from "@/server/region-data";
import {
  createOfficialProvider,
  loadOfficialSnapshot,
  parseOfficialFilters,
} from "@/server/official-data";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
export async function GET(
  request: Request,
  { params }: { params: Promise<{ report: string }> },
) {
  const { report } = await params;
  if (
    ![
      "overview",
      "timeseries",
      "severity",
      "map",
      "records",
      "metadata",
      "evidence",
      "region-evidence",
    ].includes(report)
  )
    return Response.json(
      { error: "Unknown data report." },
      { status: 404, headers },
    );
  const query = new URL(request.url).searchParams;
  let filters;
  try {
    filters = parseOfficialFilters(query);
    if (
      report === "timeseries" &&
      query.has("granularity") &&
      !["monthly", "yearly"].includes(query.get("granularity")!)
    )
      throw Error("Granularity must be monthly or yearly.");
    if (report === "records")
      for (const key of ["page", "pageSize"])
        if (
          query.has(key) &&
          (!/^\d+$/.test(query.get(key)!) ||
            Number(query.get(key)) < 1 ||
            Number(query.get(key)) > (key === "pageSize" ? 50 : 100000))
        )
          throw Error(
            "Invalid pagination. Page size must be between 1 and 50.",
          );
  } catch (error) {
    return Response.json(
      {
        error: error instanceof Error ? error.message : "Invalid data filters.",
      },
      { status: 400, headers },
    );
  }
  try {
    const snapshot = await loadOfficialSnapshot(),
      service = createRegionalProvider(createOfficialProvider(snapshot), await loadRegionSnapshot());
    let payload: unknown;
    switch (report) {
      case "region-evidence":
        payload = await regionEvidence();
        break;
      case "evidence":
        payload = { demo: false, ...snapshot.provenance };
        break;
      case "metadata":
        payload = await service.getDatasetMetadata();
        break;
      case "overview":
        payload = await service.getOverview(filters);
        break;
      case "timeseries":
        payload = await service.getTimeSeries(
          filters,
          query.get("granularity") === "monthly" ? "monthly" : "yearly",
        );
        break;
      case "severity":
        payload = await service.getSeverityDistribution(filters);
        break;
      case "map":
        payload = await service.getMapData(filters);
        break;
      case "records":
        payload = await service.getCrashRecords(
          filters,
          {
            page: Number(query.get("page") || 1),
            pageSize: Number(query.get("pageSize") || 20),
          },
          { field: "date", direction: "desc" },
        );
        break;
    }
    return Response.json(payload, { headers });
  } catch {
    // Never leak local paths or fall back to fictional data after an I/O failure.
    return Response.json(
      {
        error:
          "The verified project snapshot is unavailable. Check the local data files and retry.",
      },
      { status: 503, headers },
    );
  }
}
