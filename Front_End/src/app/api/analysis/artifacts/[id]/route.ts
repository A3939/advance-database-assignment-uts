import 'server-only';
import { readArtifact } from '@/server/analysis/artifacts';
import { sameOrigin } from '@/server/agent/request';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request: Request, { params }: { params: Promise<{id: string}> }) {
  if (!sameOrigin(request)) return new Response('Forbidden', {status:403});
  const item = await readArtifact((await params).id);
  if (!item) return Response.json({error:'This analysis file is unavailable or has expired. Run the analysis again.'}, {status:404});
  return new Response(new Uint8Array(item.bytes), {headers: {
    'Content-Type': 'application/octet-stream',
    'Content-Disposition': `attachment; filename="${item.artifact.name}"`,
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; sandbox",
  }});
}
