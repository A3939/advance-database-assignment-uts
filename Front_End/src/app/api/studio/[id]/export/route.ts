import "server-only";
import { studioStore } from "@/server/studio/store";
import { exportStudyBundle, exportRevision } from "@/server/studio/export";
import { StudioError } from "@/server/studio/store";
import { guard, headers, errorResponse } from "@/server/studio/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    guard(request);
    const query = new URL(request.url).searchParams, format = query.get("format") || "zip";
    if (!["pdf", "zip"].includes(format)) throw new StudioError("Choose PDF or ZIP export.");
    const store = studioStore(), s = store.get((await params).id);
    const bundle = await exportStudyBundle(store, s, exportRevision(query));
    return new Response(new Uint8Array(format === "pdf" ? bundle.pdf : bundle.zip), {
      headers: {
        ...headers,
        "Content-Type": format === "pdf" ? "application/pdf" : "application/zip",
        "Content-Disposition": `attachment; filename="ARSIA-study-r${bundle.revision}.${format}"`,
        "X-ARSIA-Report-Revision": String(bundle.revision),
        "X-ARSIA-Report-Hash": bundle.reportHash,
        "X-ARSIA-File-SHA256": format === "pdf" ? bundle.pdfHash : bundle.zipHash,
      },
    });
  } catch (e) {
    return errorResponse(e);
  }
}
