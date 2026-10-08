import { sameOrigin } from "../agent/request";
import { StudioError } from "./store";
export const headers = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
export function guard(request: Request) {
  if (!sameOrigin(request))
    throw new StudioError("Cross-origin access is not allowed.", 403);
}
export async function jsonBody(request: Request) {
  guard(request);
  if (!request.headers.get("content-type")?.startsWith("application/json"))
    throw new StudioError("Use JSON.", 415);
  if (!request.body) throw new StudioError("Missing body.");
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let text = "",
    size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 128000) {
        await reader.cancel();
        throw new StudioError("Request is too large.", 413);
      }
      text += decoder.decode(value, { stream: true });
    }
    const value = JSON.parse(text + decoder.decode()) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new StudioError("Use a JSON object.");
    return value;
  } catch (e) {
    if (e instanceof StudioError) throw e;
    throw new StudioError("Invalid JSON request.");
  } finally {
    reader.releaseLock();
  }
}
export function errorResponse(error: unknown) {
  return Response.json(
    {
      error:
        error instanceof StudioError
          ? error.message
          : "The research could not be saved or loaded. Your last saved version is intact; please retry.",
    },
    { status: error instanceof StudioError ? error.status : 500, headers },
  );
}
