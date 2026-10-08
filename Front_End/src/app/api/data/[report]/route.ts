import { derivedSourceBinding } from "@/server/derived-report-binding";
import { analysisRuntime } from "@/server/agent/runtime";
import { resolveCatalog, parseDataFilters, PublicationUnavailable } from "@/server/data-catalog";
import { getSeverityChange } from "@/server/severity-change";
import { getSpeedZones, loadSpeedZoneSnapshot, speedZoneEvidence } from "@/server/speed-zone";
import { loadRegionSnapshot, regionEvidence } from "@/server/region-data";
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
      "catalog",
      "overview",
      "timeseries",
      "severity",
      "severity-change",
      "speed-zones",
      "speed-zone-evidence",
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
  if (report === "catalog") {
    try { return Response.json(await resolveCatalog(query.get("releaseId") || undefined, query.get("datasetVersion") === "official-v1"), { headers }); }
    catch (error) { return Response.json({error:"The local publication service or requested release is unavailable. No snapshot has been substituted."},{status:error instanceof PublicationUnavailable ? error.status : 404,headers}); }
  }
  let filters;
  try {
    filters = parseDataFilters(query);
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
    const { snapshot, service, catalog } = await analysisRuntime({page:"/",filters});
    let payload: unknown;
    switch (report) {
      case "severity-change":
        payload = await getSeverityChange(filters, service, await loadRegionSnapshot(), catalog);
        break;
      case "speed-zones":
        payload = await getSpeedZones(filters, service, await loadSpeedZoneSnapshot(), catalog);
        break;
      case "speed-zone-evidence": {
        const speed = await loadSpeedZoneSnapshot();
        const evidence = await speedZoneEvidence();
        const sources = filters.source === "All" ? catalog.sources.map(s=>s.source) : [filters.source];
        const bindings = sources.filter(source=>speed.sources[source]).map(source=>derivedSourceBinding(filters,source,speed,catalog,evidence)).filter(Boolean);
        if (!bindings.length) return Response.json({ error: "No speed-zone evidence is bound to this release." }, { status: 404, headers });
        payload = {...evidence, bindings};
        break;
      }
      case "region-evidence":
        payload = await regionEvidence();
        break;
      case "evidence":
        payload = { demo: false, ...snapshot.provenance, catalog };
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
