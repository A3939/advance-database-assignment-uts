import { localRequest } from "../local-request";
/** Loopback-only, bounded streaming transport. No database credentials cross this boundary. */
import { request as httpRequest } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { IMPORT_FILE_LIMIT } from "../../services/imports-contracts";

const JSON_LIMIT = 256 * 1024;
const RESPONSE_LIMIT = 8 * 1024 * 1024;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const uuid = "[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
export class ImportBridgeError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export function guardImportRequest(request: Request) {
  if (!localRequest(request))
    throw new ImportBridgeError(403, "Open Imports from this instance's configured local ARSIA website to make this request.");
}
export function importTarget(request: Request, segments: string[]) {
  const method = request.method;
  const path = `/${segments.join("/")}`;
  const query = new URL(request.url).searchParams;
  const read = method === "GET" && (/^\/(health|jobs|catalog|reports|query|storage)$/.test(path) || new RegExp(`^/jobs/${uuid}(/(evidence|storage))?$`).test(path));
  const post = method === "POST" && (path === "/jobs" || new RegExp(`^/jobs/${uuid}/(submit|cancel|retry)$`).test(path));
  const upload = method === "PUT" && new RegExp(`^/jobs/${uuid}/files$`).test(path);
  if (!read && !post && !upload) throw new ImportBridgeError(404, "Unknown local import operation.");
  const permitted = upload ? ["filename"] : path === "/reports" ? ["source_id", "release_id"] : path === "/catalog" ? ["release_id"] : path === "/query" ? ["release_id", "source_id", "from", "to", "include_units"] : [];
  if ([...query.keys()].some(key => !permitted.includes(key) || query.getAll(key).length !== 1))
    throw new ImportBridgeError(400, "Invalid local import query.");
  if (query.has("include_units") && !["true", "false"].includes(query.get("include_units")!))
    throw new ImportBridgeError(400, "Invalid publication query option.");
  if (upload) {
    const name = query.get("filename") || "";
    if (!/^[^/\\\x00-\x1f]{1,180}$/.test(name) || name === "." || name === "..")
      throw new ImportBridgeError(400, "Use a filename without directory separators.");
    if (request.headers.get("content-type") !== "application/octet-stream")
      throw new ImportBridgeError(415, "Upload file contents as binary data.");
  } else if (post && !request.headers.get("content-type")?.startsWith("application/json")) {
    throw new ImportBridgeError(415, "Use a JSON request.");
  }
  const limit = upload ? IMPORT_FILE_LIMIT : JSON_LIMIT;
  const length = request.headers.get("content-length");
  if (length && (!/^\d+$/.test(length) || Number(length) > limit))
    throw new ImportBridgeError(413, upload ? "A file can contain at most 512 MiB." : "The import request is too large.");
  if (path === "/reports" && [...query.values()].some(value => value.length > 150))
    throw new ImportBridgeError(400, "Invalid publication selection.");
  return { path: `${path}${query.size ? `?${query}` : ""}`, limit, upload };
}
async function configuredSocket() {
  const path = join(process.cwd(), "artifacts/imports-local/runtime.json");
  const info = await stat(path);
  if (!info.isFile() || info.size > 16384 || (info.mode & 0o077) !== 0) throw Error("Invalid private runtime configuration");
  const config = JSON.parse(await readFile(path, "utf8"));
  if (typeof config.socket_path !== "string" || !/^\/tmp\/arsia-imports-[a-f0-9]+\/api\.sock$/.test(config.socket_path) || config.socket_path.length > 100)
    throw Error("Invalid local socket");
  return config.socket_path as string;
}
const safeFailure = (status: number) => ({
  400: "The import request was rejected. Check the selected files and mapping profile.",
  404: "This local import or publication was not found.",
  409: "The job changed or is not ready for this operation. Refresh its status before retrying.",
  413: "The upload exceeds its file, bundle or storage limit.",
  422: "The mapping profile or request fields need correction.",
  429: "The local import service is busy. Wait before retrying.",
  507: "There is not enough local storage to accept this upload.",
}[status] || "The local import service could not complete this request. Check its status and retry.");

export async function bridgeImport(request: Request, segments: string[], socketOverride?: string): Promise<Response> {
  try {
    guardImportRequest(request);
    const target = importTarget(request, segments);
    const socketPath = socketOverride || await configuredSocket();
    return await new Promise<Response>((resolve, reject) => {
      let settled = false;
      const finish = (error?: Error, response?: Response) => {
        if (settled) return;
        settled = true;
        request.signal.removeEventListener("abort", abort);
        if (error) reject(error); else resolve(response!);
      };
      const upstream = httpRequest({ socketPath, path: target.path, method: request.method, agent: false,
        headers: { "Content-Type": target.upload ? "application/octet-stream" : "application/json", Accept: "application/json" },
      }, response => {
        const chunks: Buffer[] = []; let size = 0;
        response.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > RESPONSE_LIMIT) { response.destroy(); upstream.destroy(); finish(new ImportBridgeError(502, "The local import response exceeded its safe limit.")); }
          else chunks.push(chunk);
        });
        response.on("error", () => finish(new ImportBridgeError(502, "The local import response was interrupted.")));
        response.on("end", () => {
          const status = response.statusCode || 502;
          if (status < 200 || status >= 300) { finish(undefined, Response.json({ error: safeFailure(status) }, { status: status >= 400 && status <= 599 ? status : 502, headers })); return; }
          try {
            const data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
            finish(undefined, Response.json(data, { status, headers }));
          } catch { finish(new ImportBridgeError(502, "The local import service returned an invalid response.")); }
        });
      });
      const abort = () => { upstream.destroy(); finish(new ImportBridgeError(499, "The upload connection was closed. Incomplete uploads are discarded.")); };
      request.signal.addEventListener("abort", abort, { once: true });
      upstream.setTimeout(target.upload ? 10 * 60 * 1000 : 30000, () => { upstream.destroy(); finish(new ImportBridgeError(504, "The local import service timed out.")); });
      upstream.on("error", error => finish(error instanceof ImportBridgeError ? error : new ImportBridgeError(503, "The local import service is unavailable. Start its local worker and API, then retry.")));
      if (request.signal.aborted) { abort(); return; }
      if (!request.body) { upstream.end(); return; }
      let bytes = 0;
      const limiter = new Transform({ transform(chunk, _encoding, callback) {
        bytes += chunk.length;
        if (bytes > target.limit) {
          const error = new ImportBridgeError(413, "The import request exceeds its byte limit.");
          finish(error); callback(error);
        }
        else callback(null, chunk);
      } });
      const incoming = Readable.fromWeb(request.body as import("node:stream/web").ReadableStream);
      void pipeline(incoming, limiter, upstream).catch(error => finish(error instanceof ImportBridgeError ? error : new ImportBridgeError(503, "The upload did not complete. Check job status before retrying.")));
    });
  } catch (error) {
    return Response.json({ error: error instanceof ImportBridgeError ? error.message : "The local import service is not configured or is unavailable." }, { status: error instanceof ImportBridgeError ? error.status : 503, headers });
  }
}
