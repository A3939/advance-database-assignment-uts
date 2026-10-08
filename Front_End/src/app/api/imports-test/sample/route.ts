import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { guardImportRequest } from "@/server/imports/bridge";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const filename = "2020-2024_data_sa_crash_as_at_20250919.zip";
export async function GET(request: Request) {
  try {
    guardImportRequest(request);
    const data = await readFile(join(process.cwd(), "artifacts/manual-import-test/input", filename));
    if (createHash("sha256").update(data).digest("hex") !== "b1c22ba4444542c07f876a26aab0bc5ee1bfc4689001dabf6309c634550737de") throw Error("Fixture changed");
    return new Response(data, { headers: { "Content-Type": "application/zip", "Content-Disposition": `attachment; filename="${filename}"`, "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Test data unavailable" }, { status: 503 });
  }
}
