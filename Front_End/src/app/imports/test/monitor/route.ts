import { readFile } from "node:fs/promises";
import { join } from "node:path";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  if (!["127.0.0.1:3100", "localhost:3100", "[::1]:3100"].includes(request.headers.get("host") || "")) return new Response("Local monitoring only", {status:403});
  try {
    const html = await readFile(join(process.cwd(), "artifacts/manual-import-test/live-monitor/live.html"), "utf8");
    return new Response(html, {headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'"}});
  } catch {return new Response("Monitor starting; refresh shortly",{status:503});}
}
