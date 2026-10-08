import "server-only";
import { studioStore, StudioError } from "@/server/studio/store";
import { jsonBody, headers, errorResponse } from "@/server/studio/http";
import { saveResource } from "@/server/studio/resources";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    const body = await jsonBody(request) as Record<string, unknown>;
    if ("target" in body) throw new StudioError("The study target is bound by this route.");
    const { revision, ...input } = body;
    return Response.json(await saveResource(studioStore(), { ...input, target: { studyId: id, revision } }), { headers });
  } catch (error) { return errorResponse(error); }
}
