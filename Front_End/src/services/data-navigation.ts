/** Page selection is separate from the validated analysis/release context. */
export type DataTab = "library" | "imports";
export function dataTab(value: string | string[] | null | undefined): DataTab {
  return value === "imports" ? "imports" : "library";
}
export function workspaceParameters(path: string, search: string): URLSearchParams {
  const params = new URLSearchParams(search);
  if (path === "/studio") { params.delete("study"); params.delete("studioView"); }
  if (path === "/data") params.delete("tab");
  return params;
}
export function preservePageSelection(path: string, href: string, search: string): string {
  const current = new URLSearchParams(search);
  const key = path === "/studio" ? "study" : path === "/data" ? "tab" : null;
  if (!key || !current.has(key)) return href;
  const value = key === "tab" ? dataTab(current.get(key)) : current.get(key)!;
  const mode = current.get("studioView");
  const suffix = path === "/studio" && ["explore", "document", "findings"].includes(mode || "") ? `&studioView=${mode}` : "";
  return `${href}&${key}=${encodeURIComponent(value)}${suffix}`;
}
export function importsDataHref(values: Record<string, string | string[] | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || key === "tab") continue;
    for (const item of Array.isArray(value) ? value : [value]) params.append(key, item);
  }
  params.set("tab", "imports");
  return `/data?${params}`;
}
