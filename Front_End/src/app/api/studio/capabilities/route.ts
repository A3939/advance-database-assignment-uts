import "server-only";
import { guard, headers, errorResponse } from "@/server/studio/http";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
/** Configuration inspection only: no SDK, connection probe, credentials or model call. */
export async function GET(request: Request) {
  try {
    guard(request);
    const available = !!process.env.OPENAI_API_KEY?.trim();
    return Response.json({ assistant: { available, reason: available ? null : "Assistant is unavailable in this environment. Add resources, organize findings and export reports without AI." }, backgroundResearch: false }, { headers });
  } catch (e) { return errorResponse(e); }
}
