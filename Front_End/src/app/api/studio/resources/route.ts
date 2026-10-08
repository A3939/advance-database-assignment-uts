import "server-only";
import { studioStore } from "@/server/studio/store";
import { guard, jsonBody, headers, errorResponse } from "@/server/studio/http";
import { resourceCatalog, saveResource } from "@/server/studio/resources";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  try {
    guard(request);
    const value = new URL(request.url).searchParams.get("context");
    if (!value || value.length > 16000) return Response.json({ error: "Provide the selected research context." }, { status: 400, headers });
    return Response.json(await resourceCatalog(JSON.parse(value)), { headers });
  } catch (error) { return errorResponse(error); }
}
export async function POST(request: Request) {
  try { return Response.json(await saveResource(studioStore(), await jsonBody(request)), { status: 201, headers }); }
  catch (error) { return errorResponse(error); }
}
