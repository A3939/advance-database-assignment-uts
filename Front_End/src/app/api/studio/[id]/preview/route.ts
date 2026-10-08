import "server-only";
import { studioStore } from "@/server/studio/store";
import { exportRevision, savedExportSnapshot } from "@/server/studio/export";
import { renderStudyReport, REPORT_CSP } from "@/server/studio/report-renderer";
import { guard, headers, errorResponse } from "@/server/studio/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    guard(request);
    const store = studioStore(), study = store.get((await params).id);
    const report = renderStudyReport(savedExportSnapshot(store, study, exportRevision(new URL(request.url).searchParams)));
    return new Response(report.html, { headers: { ...headers, "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": REPORT_CSP,
      "X-ARSIA-Report-Revision": String(report.revision), "X-ARSIA-Report-Hash": report.reportHash } });
  } catch (error) { return errorResponse(error); }
}
