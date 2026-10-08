import 'server-only';
import { localRequest } from '@/server/local-request';
import { modelBudgetView } from '@/server/agent/model-budget';
import { resourceUsage } from '@/server/analysis/resource-usage';
export const runtime='nodejs';
export const dynamic='force-dynamic';
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
export async function GET(request:Request) {
  if (!localRequest(request)) return Response.json({error:'Local same-origin access required'},{status:403,headers});
  try { return Response.json({...modelBudgetView(),resources:await resourceUsage()},{headers}); }
  catch {return Response.json({error:'The local usage ledger is unavailable. Unknown usage has not been replaced with zero.'},{status:503,headers});}
}
