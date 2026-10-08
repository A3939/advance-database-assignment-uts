import "server-only";
import { studioStore } from "@/server/studio/store";
import { guard, jsonBody, headers, errorResponse } from "@/server/studio/http";
import { analysisRuntime } from "@/server/agent/runtime";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Params = { params: Promise<{ id: string }> };
export async function GET(request: Request, { params }: Params) {
  try {
    guard(request);
    const { id } = await params,
      query = new URL(request.url).searchParams;
    const store = studioStore();
    if (query.has("catalog")) {
      const s = store.get(id),
        r = await analysisRuntime({
          page: "/studio",
          filters: s.context.filters,
        });
      return Response.json(
        {
          catalog: await r.workspace.execute(
            "workspace_catalog",
            {},
            request.signal,
            "catalog",
          ),
          datasets: await r.service.getDatasetMetadata(),
        },
        { headers },
      );
    }
    return Response.json(
      query.has("version")
        ? store.version(id, query.get("version")!)
        : query.has("history")
          ? store.versions(id)
          : store.get(id),
      { headers },
    );
  } catch (e) {
    return errorResponse(e);
  }
}
export async function PATCH(request: Request, { params }: Params) {
  try {
    return Response.json(
      studioStore().action((await params).id, await jsonBody(request)),
      { headers },
    );
  } catch (e) {
    return errorResponse(e);
  }
}
export async function DELETE(request: Request, { params }: Params) {
  try {
    const body = await jsonBody(request);
    return Response.json(studioStore().deleteStudy((await params).id, body), { headers });
  } catch (e) {
    return errorResponse(e);
  }
}
