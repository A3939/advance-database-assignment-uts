import { resolveCatalog, validateCatalogFilters, publicationRead } from "../data-catalog";
import { LOCAL_VERSION } from "../../services/catalog-contracts";
import { createPublishedProvider } from "../published-data";
import OpenAI from "openai";
import { createOfficialProvider, loadOfficialSnapshot } from "../official-data";
import { createRegionalProvider, loadRegionSnapshot } from "../region-data";
import { AnalysisWorkspace } from "../analysis/workspace";
import type { AgentContext } from "../../services/contracts";
import { routeModel, type ModelRoute } from "./model-routing";

export async function analysisRuntime(context: AgentContext, read: typeof publicationRead = publicationRead) {
  const [snapshot, regional] = await Promise.all([
    loadOfficialSnapshot(),
    loadRegionSnapshot(),
  ]);
  let service = createRegionalProvider(
    createOfficialProvider(snapshot),
    regional,
  );
  const catalog = await resolveCatalog(context.filters.releaseId, context.filters.datasetVersion !== LOCAL_VERSION, read);
  validateCatalogFilters(context.filters, catalog);
  if (catalog.mode === "local") service = createPublishedProvider(catalog, service, read);
  const scopedSnapshot = catalog.mode === "local" ? { ...snapshot, provenance: { ...snapshot.provenance, version: catalog.datasetVersion, batchId: catalog.batchId, releaseId: catalog.releaseId, coverage: catalog.coverage, sourceBatches: Object.fromEntries(catalog.sources.map(s => [s.source, s.batchId])), qa: [], evidenceHashes: {}, publicationStatus: "Local immutable release; source QA accompanies each publication", scope: "Source-specific local integrated data" } } : snapshot;
  return {
    snapshot: scopedSnapshot,
    catalog,
    service,
    workspace: new AnalysisWorkspace(context, service, regional, catalog),
  };
}
export function configuredModel(selection: ModelRoute = routeModel({ surface: "imports" })) {
  if (process.env.NODE_TEST_CONTEXT) throw Error("Real models require the explicit acceptance harness; ordinary tests are offline.");
  if (!process.env.OPENAI_API_KEY?.trim())
    throw Error("ASSISTANT_NOT_CONFIGURED");
  const model = selection.model;
  const client = new OpenAI({
    apiKey: process.env.OPENAI_API_KEY,
    baseURL: "https://api.openai.com/v1",
    timeout: 120000,
    // The host admits and records each request before transmission. SDK retries
    // would hide an additional attempt (and potentially unknown usage) behind
    // that single admission, so retries must remain explicit host operations.
    maxRetries: 0,
    logLevel: "off",
  });
  return { model, client, selection, reasoningEffort: selection.reasoningEffort };
}
