/** Shared policy for the local single-user HTTP surface; no implicit Origin trust. */
const hosts = new Set(['127.0.0.1:3100','localhost:3100','[::1]:3100']);
/** Explicit server-owned origin for isolated instances; never derived from a request. */
export function localHttpOrigin(): string | null {
  const configured = process.env.ARSIA_LOCAL_HTTP_ORIGIN;
  if (configured === undefined) return 'http://127.0.0.1:3100';
  const match = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):([1-9][0-9]{3,4})$/.exec(configured);
  if (!match || Number(match[2]) < 1024 || Number(match[2]) > 65535) return null;
  return configured;
}
export function localRequest(request: Request): boolean {
  const configured = localHttpOrigin();
  if (!configured) return false;
  const allowed = process.env.ARSIA_LOCAL_HTTP_ORIGIN === undefined ? hosts : new Set([new URL(configured).host]);
  const host = request.headers.get('host') || '';
  const target = new URL(request.url);
  // NextRequest normalizes a loopback URL to localhost; the HTTP Host and
  // browser Origin remain exact and must still match this owned instance.
  const canonicalTarget = `localhost:${new URL(configured).port}`;
  const targetAllowed = allowed.has(target.host) || target.host === canonicalTarget;
  if (!allowed.has(host) || !targetAllowed || target.protocol !== 'http:' || request.headers.get('sec-fetch-site') === 'cross-site') return false;
  const expected = `http://${host}`;
  const origin = request.headers.get('origin');
  if (origin) return origin === expected;
  if (request.method !== 'GET' || request.headers.get('sec-fetch-site') !== 'same-origin') return false;
  try { return new URL(request.headers.get('referer') || '').origin === expected; }
  catch { return false; }
}
