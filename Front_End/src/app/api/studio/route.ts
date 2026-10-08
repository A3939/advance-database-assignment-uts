import "server-only";
import { studioStore } from "@/server/studio/store";
import { guard, jsonBody, headers, errorResponse } from "@/server/studio/http";
import { createStudy } from "@/server/studio/create";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  try {
    guard(request);
    return Response.json(studioStore().list(), { headers });
  } catch (e) {
    return errorResponse(e);
  }
}
export async function POST(request: Request) {
  try {
    return Response.json(
      await createStudy(studioStore(), await jsonBody(request)),
      { headers, status: 201 },
    );
  } catch (e) {
    return errorResponse(e);
  }
}
