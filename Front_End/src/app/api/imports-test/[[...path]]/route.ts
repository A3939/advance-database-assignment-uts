import "server-only";
import { bridgeImport, guardImportRequest } from "@/server/imports/bridge";
import { manualTestSocket } from "@/server/imports/test-environment";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 600;
type Context = { params: Promise<{ path?: string[] }> };
async function handle(request: Request, context: Context) {
  try {
    guardImportRequest(request);
    return bridgeImport(request, (await context.params).path || [], await manualTestSocket());
  } catch {
    // Never fall back to the website's original database.
    return Response.json({ error: "Isolated upload environment is unavailable. Original website data is unchanged." }, { status: 503 });
  }
}
export { handle as GET, handle as POST, handle as PUT };
