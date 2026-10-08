import "server-only";
import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { codexGateway } from "@/server/imports/codex-gateway";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 900;
export async function POST(request:Request) {
  return codexGateway(request, {runtimeConfig:async()=>{
    const path=join(process.cwd(),"artifacts/imports-local/runtime.json");
    const file=await stat(path);
    if(!file.isFile() || file.size>16384 || file.mode & 0o077) throw Error("Private runtime required");
    return JSON.parse(await readFile(path,"utf8"));
  }});
}
