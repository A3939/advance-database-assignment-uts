import { lstat, readFile } from "node:fs/promises";
import { join } from "node:path";

/** A dedicated route selects this fixed private file; clients cannot choose a DB. */
export function isolatedTestSocket(test: Record<string, unknown>, main: Record<string, unknown>) {
  if (test.mode !== "local-test" || test.purpose !== "manual-upload-isolated" ||
      typeof test.database !== "string" || !/^arsia_imports_test_manual_[a-f0-9]{12}$/.test(test.database) ||
      typeof test.instance_id !== "string" || !/^[a-f0-9]{32}$/.test(test.instance_id) ||
      typeof test.socket_path !== "string" || !/^\/tmp\/arsia-imports-manual-[a-f0-9]{12}\/api\.sock$/.test(test.socket_path) ||
      test.database === main.database || test.instance_id === main.instance_id || test.socket_path === main.socket_path)
    throw Error("An independent manual-test runtime is required");
  return test.socket_path;
}

export async function manualTestSocket() {
  async function read(name: string) {
    const path = join(process.cwd(), "artifacts/imports-local", name);
    const info = await lstat(path);
    if (!info.isFile() || info.size > 16384 || (info.mode & 0o077)) throw Error("Private runtime required");
    return JSON.parse(await readFile(path, "utf8"));
  }
  return isolatedTestSocket(await read("manual-test.json"), await read("runtime.json"));
}
