import { chromium } from "playwright-core";
import { StudioError } from "./store";
import { REPORT_RENDERER_VERSION, type RenderedReport } from "./report-renderer";

const CACHE_LIMIT = 48 * 1024 * 1024;
const cache = new Map<string, Buffer>();
let cachedBytes = 0, active = false;

/** No browser page navigation or user executable template is permitted. Only the
 * self-contained host renderer's HTML is printed. Every request is blocked. */
export async function renderReportPdf(report: RenderedReport): Promise<Buffer> {
  const key = `${REPORT_RENDERER_VERSION}:${report.reportHash}`;
  const previous = cache.get(key); if (previous) return Buffer.from(previous);
  if (active) throw new StudioError("Another report is being rendered. Try the saved report again shortly.", 429);
  active = true;
  let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    // The renderer has no reason to inherit provider credentials, private DSNs,
    // model routing or the user's complete application environment.
    const environment = Object.fromEntries(["PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT"]
      .flatMap(name => process.env[name] ? [[name, process.env[name]!]] : []));
    browser = await chromium.launch({ headless: true, timeout: 15000, chromiumSandbox: true, env: environment,
      ...(process.env.ARSIA_REPORT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.ARSIA_REPORT_CHROMIUM_EXECUTABLE } : {}) });
    const ownedBrowser = browser;
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => { void ownedBrowser.close(); reject(new StudioError("Report rendering exceeded its 30 second limit. The saved study is unchanged.", 503)); }, 30000);
    });
    const rendered = (async () => {
      const context = await ownedBrowser.newContext({ javaScriptEnabled: false, serviceWorkers: "block", offline: true });
      await context.route("**/*", route => route.abort("blockedbyclient"));
      const page = await context.newPage();
      page.setDefaultTimeout(10000);
      await page.setContent(report.html, { waitUntil: "load", timeout: 10000 });
      await page.emulateMedia({ media: "print" });
      const bytes = await page.pdf({ format: "A4", printBackground: true, preferCSSPageSize: true, tagged: true,
        displayHeaderFooter: true, headerTemplate: "<span></span>",
        footerTemplate: `<div style="font-family:Arial,sans-serif;font-size:8px;color:#60707b;width:100%;padding:0 17mm;display:flex;justify-content:space-between"><span>ARSIA · Research draft · Revision ${report.revision}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
        margin: { top: "18mm", right: "17mm", bottom: "20mm", left: "17mm" } });
      if (!bytes.subarray(0,5).equals(Buffer.from("%PDF-")) || bytes.length > 20000000) throw new StudioError("The PDF renderer returned an invalid or oversized document.", 503);
      return bytes;
    })();
    const bytes = await Promise.race([rendered, deadline]);
    while (cache.size && cachedBytes + bytes.length > CACHE_LIMIT) { const oldest = cache.keys().next().value!; cachedBytes -= cache.get(oldest)!.length; cache.delete(oldest); }
    cache.set(key, bytes); cachedBytes += bytes.length;
    return Buffer.from(bytes);
  } catch (error) {
    if (error instanceof StudioError) throw error;
    throw new StudioError("PDF rendering is unavailable. Install the configured Playwright Chromium runtime and retry this saved revision; no research or model has been rerun.", 503);
  } finally { if (timer) clearTimeout(timer); await browser?.close().catch(() => {}); active = false; }
}
