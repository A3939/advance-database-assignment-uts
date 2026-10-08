import "server-only";
import { bridgeImport } from "@/server/imports/bridge";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 600;
type Context = { params: Promise<{ path?: string[] }> };
async function handle(request: Request, context: Context) {
  return bridgeImport(request, (await context.params).path || []);
}
export { handle as GET, handle as POST, handle as PUT };
