import { createHash, randomBytes } from "node:crypto";
import {
  mkdir,
  readFile,
  writeFile,
  readdir,
  rm,
  stat,
} from "node:fs/promises";
import { join } from "node:path";
import type { AnalysisArtifact } from "../../services/analysis-contracts";

const root = () => join(process.cwd(), "artifacts/analysis");
export const ARTIFACT_TTL = 24 * 60 * 60 * 1000;
const allowed = new Set(["csv", "json", "md", "txt", "png", "pdf", "py"]);
const idPattern = /^[a-f0-9]{48}$/;
let pendingWrite: Promise<void> = Promise.resolve();
export async function saveArtifact(
  name: string,
  content: Buffer | string,
  provenance: unknown,
): Promise<AnalysisArtifact> {
  const previous = pendingWrite;
  let release!: () => void;
  pendingWrite = new Promise<void>((resolve) => {
    release = resolve;
  });
  await previous;
  try {
    return await persistArtifact(name, content, provenance);
  } finally {
    release();
  }
}
async function persistArtifact(
  name: string,
  content: Buffer | string,
  provenance: unknown,
): Promise<AnalysisArtifact> {
  const kind = name.split(".").at(-1)!;
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$/.test(name) || !allowed.has(kind))
    throw Error("Invalid analysis filename.");
  const bytes = Buffer.isBuffer(content) ? content : Buffer.from(content);
  if (bytes.length > 4 * 1024 * 1024) throw Error("Artifact exceeds 4 MB.");
  const dir = root();
  await mkdir(dir, { recursive: true, mode: 0o700 });
  // Lazy expiry and a host-storage cap. Only this private analysis directory is touched.
  const entries = await readdir(dir);
  let usage = 0;
  for (const file of entries) {
    if (!/^[a-f0-9]{48}\.(bin|json)$/.test(file)) continue;
    const path = join(dir, file),
      info = await stat(path);
    if (Date.now() - info.mtimeMs > ARTIFACT_TTL)
      await rm(path, { force: true });
    else usage += info.size;
  }
  if (
    usage +
      bytes.length +
      Buffer.byteLength(JSON.stringify(provenance)) +
      2048 >
    128 * 1024 * 1024
  )
    throw Error("Analysis storage limit reached. Files expire after 24 hours.");
  const id = randomBytes(24).toString("hex");
  const artifact: AnalysisArtifact = {
    id,
    name,
    href: `/api/analysis/artifacts/${id}`,
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    kind: kind as AnalysisArtifact["kind"],
    expiresAt: new Date(Date.now() + ARTIFACT_TTL).toISOString(),
  };
  await writeFile(join(dir, `${id}.bin`), bytes, { flag: "wx", mode: 0o600 });
  await writeFile(
    join(dir, `${id}.json`),
    JSON.stringify({ artifact, provenance }),
    { flag: "wx", mode: 0o600 },
  );
  return artifact;
}
export async function readArtifact(id: string) {
  if (!idPattern.test(id)) return null;
  try {
    const metadata = JSON.parse(
      await readFile(join(root(), `${id}.json`), "utf8"),
    );
    if (new Date(metadata.artifact.expiresAt).getTime() < Date.now())
      return null;
    const bytes = await readFile(join(root(), `${id}.bin`));
    if (
      createHash("sha256").update(bytes).digest("hex") !==
      metadata.artifact.sha256
    )
      return null;
    return { ...metadata, bytes } as {
      artifact: AnalysisArtifact;
      provenance: unknown;
      bytes: Buffer;
    };
  } catch {
    return null;
  }
}
