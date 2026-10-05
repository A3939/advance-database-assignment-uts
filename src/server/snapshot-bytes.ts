/** Git on Windows may check JSON out with CRLF; published SHA values use LF. */
export function canonicalSnapshotText(value: string): string {
  return value.replace(/\r\n/g, "\n");
}

export function canonicalSnapshotBytes(value: Buffer): Buffer {
  return Buffer.from(canonicalSnapshotText(value.toString("utf8")), "utf8");
}
