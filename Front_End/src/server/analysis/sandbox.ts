import { execFile } from "node:child_process";
import { mkdtemp, chmod, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { promisify } from "node:util";
const exec = promisify(execFile);
export const SANDBOX_IMAGE = "arsia-analysis:1";
export const SANDBOX_TIMEOUT = 30000;
export type SandboxResult = {
  status: "succeeded" | "failed" | "unavailable";
  stdout: string;
  error: string | null;
  files: { name: string; data: string }[];
  image?: string;
};
// Environment is deliberately constructed, never inherited from the API server.
const environment = () => ({
  NODE_ENV: "production" as const,
  PATH: "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
  HOME: process.env.HOME || "",
});
async function docker(
  args: string[],
  options: { signal?: AbortSignal; timeout?: number; maxBuffer?: number } = {},
) {
  return exec("docker", args, {
    env: environment(),
    encoding: "utf8",
    killSignal: "SIGKILL",
    timeout: 10000,
    maxBuffer: 1024 * 1024,
    ...options,
  });
}
export function sandboxArguments(
  name: string,
  inputDirectory: string,
  image: string,
) {
  return [
    "run",
    "--name",
    name,
    "--pull=never",
    "--network=none",
    "--read-only",
    "--user=65534:65534",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--memory=512m",
    "--memory-swap=512m",
    "--cpus=1",
    "--pids-limit=32",
    "--ulimit",
    "nofile=64:64",
    "--ulimit",
    "fsize=4194304:4194304",
    "--shm-size=4m",
    "--log-driver=none",
    "--mount",
    `type=bind,source=${inputDirectory},target=/data,readonly`,
    "--tmpfs",
    "/analysis:rw,noexec,nosuid,nodev,size=33554432,uid=65534,gid=65534,mode=700",
    image,
  ];
}
export async function runPython(
  code: string,
  inputs: unknown,
  signal: AbortSignal,
  timeout = SANDBOX_TIMEOUT,
): Promise<SandboxResult> {
  signal.throwIfAborted();
  if (!code.trim() || code.length > 24000)
    throw Error("Python code must be 1–24,000 characters.");
  let image: string;
  try {
    image = (
      await docker(["image", "inspect", SANDBOX_IMAGE, "--format", "{{.Id}}"], {
        signal,
      })
    ).stdout.trim();
    if (!/^sha256:[a-f0-9]{64}$/.test(image)) throw Error("Image not found");
  } catch {
    signal.throwIfAborted();
    return {
      status: "unavailable",
      stdout: "",
      error:
        "The isolated Python runtime is unavailable. Start Docker Desktop and build the sandbox image; host Python is never used.",
      files: [],
    };
  }
  const directory = await mkdtemp(join(tmpdir(), "arsia-analysis-"));
  const name = `arsia-analysis-${randomUUID()}`;
  try {
    await chmod(directory, 0o755);
    await writeFile(join(directory, "input.json"), JSON.stringify(inputs), {
      mode: 0o444,
    });
    await writeFile(join(directory, "analysis.py"), code, { mode: 0o444 });
    const result = await docker(sandboxArguments(name, directory, image), {
      signal,
      timeout,
      maxBuffer: 13 * 1024 * 1024,
    });
    // The container is untrusted: validate the returned envelope and every exported file.
    const r = JSON.parse(result.stdout);
    if (
      !["succeeded", "failed"].includes(r.status) ||
      typeof r.stdout !== "string" ||
      r.stdout.length > 12000 ||
      !Array.isArray(r.files) ||
      r.files.length > 8
    )
      throw Error("Invalid sandbox output");
    let total = 0;
    for (const f of r.files) {
      if (
        typeof f.name !== "string" ||
        !/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,75}\.(csv|json|md|txt|png|pdf)$/.test(
          f.name,
        ) ||
        typeof f.data !== "string" ||
        !/^[A-Za-z0-9+/]*={0,2}$/.test(f.data)
      )
        throw Error("Invalid sandbox file");
      const n = Buffer.byteLength(f.data, "base64");
      total += n;
      if (n > 4 * 1024 * 1024 || total > 8 * 1024 * 1024)
        throw Error("Sandbox output limit");
    }
    return {
      status: r.status,
      stdout: r.stdout,
      error: typeof r.error === "string" ? r.error.slice(0, 5000) : null,
      files: r.files,
      image,
    };
  } catch {
    signal.throwIfAborted();
    return {
      status: "failed",
      stdout: "",
      error:
        "Python exceeded a resource/output limit, timed out, or returned an invalid result. Simplify the code and retry.",
      files: [],
      image,
    };
  } finally {
    // Only our cryptographically unique container is removed, including on cancellation.
    await docker(["rm", "-f", name]).catch(() => {});
    await rm(directory, { recursive: true, force: true });
  }
}
