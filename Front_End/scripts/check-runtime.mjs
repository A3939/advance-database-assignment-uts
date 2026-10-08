import { createRequire } from "node:module";

const [major, minor] = process.versions.node.split(".").map(Number);
if (major !== 22 || minor < 22) {
  throw new Error(`ARSIA requires Node 22.22.x or later in the 22.x series; found ${process.versions.node}. Studio requires node:sqlite. This check does not upgrade Node.`);
}
const { DatabaseSync } = createRequire(import.meta.url)("node:sqlite");
const db = new DatabaseSync(":memory:");
try {
  if (db.prepare("SELECT 1 AS supported").get().supported !== 1) throw new Error("SQLite runtime probe failed");
} finally { db.close(); }
