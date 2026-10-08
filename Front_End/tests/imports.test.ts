import test from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import { once } from "node:events";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { bridgeImport, guardImportRequest, importTarget } from "../src/server/imports/bridge";
import { IMPORT_FILE_LIMIT, validateImportFiles } from "../src/services/imports-contracts";

const id = "bb930c21-b1ef-4e37-98f6-19bce02e7011";
test("storage bridge exposes read-only exact paths without config or restore controls", () => {
  assert.equal(importTarget(request('/storage'), ['storage']).path, '/storage');
  assert.equal(importTarget(request(`/jobs/${id}/storage`), ['jobs', id, 'storage']).path, `/jobs/${id}/storage`);
  assert.throws(() => importTarget(request('/storage?config=/private/runtime.json'), ['storage']));
  assert.throws(() => importTarget(request('/storage', { method: 'DELETE' }), ['storage']));
  assert.throws(() => importTarget(request('/storage/restore', { method: 'POST' }), ['storage','restore']));
});
function request(path: string, init: RequestInit & { duplex?: "half" } = {}) {
  return new Request(`http://127.0.0.1:3100/api/imports${path}`, {
    ...init, headers: { Host: "127.0.0.1:3100", Origin: "http://127.0.0.1:3100", ...init.headers },
  });
}
async function fixture(fn: (req: IncomingMessage, res: ServerResponse) => void, run: (socket: string) => Promise<void>) {
  const dir = await mkdtemp("/tmp/arsia-bridge-test-");
  const socket = join(dir, "api.sock");
  const server = createServer(fn);
  server.listen(socket); await once(server, "listening");
  try { await run(socket); }
  finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); await rm(dir, { recursive: true, force: true }); }
}

test("import bridge requires loopback Host and matching browser origin", () => {
  guardImportRequest(request("/health"));
  guardImportRequest(new Request("http://localhost:3100/api/imports/health", { headers: { Host: "localhost:3100", "Sec-Fetch-Site": "same-origin", Referer: "http://localhost:3100/imports" } }));
  for (const headers of [
    { Host: "evil.example:3100", Origin: "http://evil.example:3100" },
    { Host: "127.0.0.1:3100", Origin: "http://evil.example" },
    { Host: "127.0.0.1:3100" },
    { Host: "127.0.0.1:3101", Origin: "http://127.0.0.1:3101" },
    { Host: "127.0.0.1:3100", Origin: "http://127.0.0.1:3100", "Sec-Fetch-Site": "cross-site" },
  ] as Record<string, string>[]) assert.throws(() => guardImportRequest(new Request("http://127.0.0.1:3100/api/imports/health", { headers })), /local|Local/);
  assert.throws(() => guardImportRequest(new Request("http://127.0.0.1:3100/api/imports/jobs", { method: "POST", headers: { Host: "127.0.0.1:3100", "Sec-Fetch-Site": "same-origin", Referer: "http://127.0.0.1:3100/imports" } })), /Open Imports/);
});
test("import transport only admits the declared methods, paths and query keys", () => {
  assert.equal(importTarget(request(`/jobs/${id}/evidence`), ["jobs", id, "evidence"]).path, `/jobs/${id}/evidence`);
  for (const value of ["true", "false"]) assert.equal(importTarget(request(`/query?include_units=${value}`), ["query"]).path, `/query?include_units=${value}`);
  for (const query of ["include_units=0", "include_units=maybe", "include_units=true&include_units=false"]) assert.throws(() => importTarget(request(`/query?${query}`), ["query"]));
  assert.throws(() => importTarget(request("/catalog?include_units=false"), ["catalog"]));
  for (const [path, segments] of [["/health?path=/tmp/x", ["health"]], ["/jobs/../../../health", ["jobs", "..", "..", "health"]], ["/jobs/abc", ["jobs", "abc"]], ["/reports?source_id=A&source_id=B", ["reports"]]] as [string, string[]][]) assert.throws(() => importTarget(request(path), segments));
  assert.throws(() => importTarget(request(`/jobs/${id}`, { method: "DELETE" }), ["jobs", id]));
  assert.throws(() => importTarget(request(`/jobs/${id}/files?filename=..%2Fsecret.csv`, { method: "PUT", headers: { "Content-Type": "application/octet-stream" } }), ["jobs", id, "files"]));
  assert.throws(() => importTarget(request(`/jobs/${id}/files?filename=data.csv`, { method: "PUT", headers: { "Content-Type": "application/octet-stream", "Content-Length": String(IMPORT_FILE_LIMIT + 1) } }), ["jobs", id, "files"]), /512 MiB/);
});
test("binary import contents stream intact to the Unix socket and return a receipt", async () => {
  const bytes = Buffer.alloc(300000); for (let i = 0; i < bytes.length; i++) bytes[i] = i % 256;
  const sha = createHash("sha256").update(bytes).digest("hex");
  await fixture((req, res) => {
    assert.equal(req.method, "PUT"); assert.equal(req.url, `/jobs/${id}/files?filename=large.csv`);
    assert.equal(req.headers["content-type"], "application/octet-stream");
    const digest = createHash("sha256"); let length = 0;
    req.on("data", chunk => { digest.update(chunk); length += chunk.length; });
    req.on("end", () => { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify({ bytes: length, sha256: digest.digest("hex") })); });
  }, async socket => {
    const response = await bridgeImport(request(`/jobs/${id}/files?filename=large.csv`, { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: bytes }), ["jobs", id, "files"], socket);
    assert.equal(response.status, 200); assert.deepEqual(await response.json(), { bytes: bytes.length, sha256: sha });
    assert.equal(response.headers.get("cache-control"), "no-store");
  });
});
test("an undeclared oversized JSON stream is rejected before upstream completion", async () => {
  let completed = false;
  await fixture((req, res) => { req.resume(); req.on("end", () => { completed = true; res.end("{}"); }); }, async socket => {
    const body = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(256 * 1024 + 1)); controller.close(); } });
    const response = await bridgeImport(request("/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body, duplex: "half" }), ["jobs"], socket);
    assert.equal(response.status, 413); assert.equal(completed, false);
  });
});
test("cancelled uploads destroy the Unix-socket request without completing a file", async () => {
  let completed = false, streamCancelled = false;
  const controller = new AbortController();
  await fixture((req, res) => {
    req.on("data", () => controller.abort()); req.on("end", () => { completed = true; res.end("{}"); });
  }, async socket => {
    const body = new ReadableStream({ start(stream) { stream.enqueue(new Uint8Array(4096)); }, cancel() { streamCancelled = true; } });
    const response = await bridgeImport(request(`/jobs/${id}/files?filename=stopped.csv`, { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body, duplex: "half", signal: controller.signal }), ["jobs", id, "files"], socket);
    assert.equal(response.status, 499); assert.equal(completed, false);
    await new Promise(resolve => setTimeout(resolve, 10)); assert.equal(streamCancelled, true);
  });
});
test("upstream failures never reveal private paths or connection strings", async () => {
  await fixture((_req, res) => { res.statusCode = 500; res.end(JSON.stringify({ detail: "/private/secrets.env postgresql://secret:password@host/db" })); }, async socket => {
    const response = await bridgeImport(request("/health"), ["health"], socket);
    assert.equal(response.status, 500); const text = await response.text(); assert.doesNotMatch(text, /private|password|postgresql/);
  });
});
test("bounded responses reject unexpectedly large local API output", async () => {
  await fixture((_req, res) => { res.end(Buffer.alloc(8 * 1024 * 1024 + 1, 32)); }, async socket => {
    const response = await bridgeImport(request("/health"), ["health"], socket);
    assert.equal(response.status, 502);
  });
});
test("file admission allows the real QLD file size and enforces bundle limits", () => {
  validateImportFiles([{ name: "qld_crash_locations.csv", size: 213483181 }]);
  assert.throws(() => validateImportFiles([{ name: "empty.csv", size: 0 }]), /non-empty/);
  assert.throws(() => validateImportFiles([{ name: "large.csv", size: IMPORT_FILE_LIMIT + 1 }]), /512 MiB/);
  assert.throws(() => validateImportFiles(Array.from({ length: 13 }, (_, i) => ({ name: `${i}.csv`, size: 1 }))), /12 files/);
  assert.throws(() => validateImportFiles([{ name: "a.csv", size: 1 }, { name: "a.csv", size: 1 }]), /unique/);
  assert.throws(() => validateImportFiles([{ name: "../secret.csv", size: 1 }]), /directory/);
});
