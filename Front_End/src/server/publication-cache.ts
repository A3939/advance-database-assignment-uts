/** Bounded cache for immutable, release-pinned aggregate reads only. */
export function createPublicationCache(now = Date.now) {
  const pending = new Map<string, Promise<unknown>>();
  const completed = new Map<string, { expires: number; value: unknown }>();
  const waiters: (() => void)[] = [];
  let active = 0;
  async function limited(load: () => Promise<unknown>) {
    if (active >= 2) {
      if (waiters.length >= 128) throw Error("Publication reads busy");
      await new Promise<void>(resolve => waiters.push(resolve));
    } else active++;
    try { return await load(); }
    finally { const next = waiters.shift(); if (next) next(); else active--; }
  }
  return async function read<T>(path: string, query: Record<string, string>, load: () => Promise<T>): Promise<T> {
    const pinned = ["query", "catalog", "reports"].includes(path) && /^[a-f0-9-]{36}$/.test(query.release_id || "");
    // Latest catalog must remain fresh; never substitute a cached release.
    if (!pinned) return load();
    const key = JSON.stringify([path, Object.entries(query).sort(([a], [b]) => a.localeCompare(b))]);
    const cached = completed.get(key);
    if (cached && cached.expires > now()) {
      completed.delete(key); completed.set(key, cached);
      return structuredClone(cached.value) as T;
    }
    completed.delete(key);
    let promise = pending.get(key);
    if (!promise) {
      promise = limited(load).then(value => {
        if (Buffer.byteLength(JSON.stringify(value)) <= 256 * 1024) {
          if (completed.size >= 64) completed.delete(completed.keys().next().value!);
          completed.set(key, { expires: now() + 30000, value: structuredClone(value) });
        }
        return value;
      }).finally(() => pending.delete(key));
      pending.set(key, promise);
    }
    return structuredClone(await promise) as T;
  };
}
