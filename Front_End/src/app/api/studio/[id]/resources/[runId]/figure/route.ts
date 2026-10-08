import "server-only";
import { studioStore, StudioError } from "@/server/studio/store";
import { exportRevision, savedExportSnapshot } from "@/server/studio/export";
import { studyResourceSvg } from "@/server/studio/report-renderer";
import { guard, headers, errorResponse } from "@/server/studio/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request, { params }: { params: Promise<{ id: string; runId: string }> }) {
  try {
    guard(request);
    const store = studioStore(), { id, runId } = await params, query = new URL(request.url).searchParams;
    const versionId = query.get("versionId"), revision = exportRevision(query);
    const saved = versionId ? store.version(id, versionId) : savedExportSnapshot(store, store.get(id), revision);
    if (saved.id !== id || saved.revision !== revision) throw new StudioError("The saved resource revision does not match this study version.", 409);
    return new Response(studyResourceSvg(saved, runId), { headers: { ...headers, "Content-Type": "image/svg+xml; charset=utf-8",
      "Content-Security-Policy": "default-src 'none'; style-src 'none'; sandbox", "X-ARSIA-Report-Revision": String(saved.revision) } });
  } catch (error) { return errorResponse(error); }
}
