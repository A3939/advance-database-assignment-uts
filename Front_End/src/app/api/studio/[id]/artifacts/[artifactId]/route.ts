import "server-only";
import { studioStore } from "@/server/studio/store";
import { guard, headers, errorResponse } from "@/server/studio/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; artifactId: string }> },
) {
  try {
    guard(request);
    const { id, artifactId } = await params;
    const file = studioStore().file(id, artifactId);
    return new Response(new Uint8Array(file.bytes), {
      headers: {
        ...headers,
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="${file.artifact.name}"`,
        "Content-Security-Policy": "default-src 'none'; sandbox",
      },
    });
  } catch (e) {
    return errorResponse(e);
  }
}
