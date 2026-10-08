import {test,expect} from '@playwright/test';
import {SNAPSHOT_CATALOG,LOCAL_VERSION} from '../../src/services/catalog-contracts';
import {createPublishedProvider} from '../../src/server/published-data';
import {createOfficialProvider,loadOfficialSnapshot} from '../../src/server/official-data';
import type {publicationRead} from '../../src/server/data-catalog';
const release='aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa';
const source='act_ui_fixture';
const catalog={...SNAPSHOT_CATALOG,mode:'local' as const,releaseId:release,batchId:release,datasetVersion:LOCAL_VERSION,coverage:{from:'2025-01-15',to:'2025-12-20'},sources:[{source,sourceId:source,title:'ACT UI transport fixture',jurisdiction:'ACT',publisher:'Synthetic UI test',batchId:'bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb',origin:'publication' as const,coverage:{from:'2025-01-15',to:'2025-12-20'},capabilities:{monthly:true,severity:true,geography:false,units:false},definitions:{crashes:'Synthetic crash observations.',fatalCrashes:'Fatal crashes.',livesLost:'Not provided.'},limitations:['Synthetic fixture; not evidence of ACT adaptation.']}]};
test('dynamic partial-month source crosses Overview, Analytics and Ask AI with one release; unknowns are not zero',async({page})=>{
 const seen:string[]=[];
 const read=(async(_path:string,q:Record<string,string>)=>{
   const known=q.from.startsWith('2025'); const counts={crash_count:known?2:null,fatal_crash_count:known?1:null,fatalities:null,casualties:null};
   return {release_id:release,batch_id:catalog.sources[0].batchId,source_id:source,coverage:{...catalog.coverage,complete:false},availability:known?'available':'no_results',metric_availability:{casualties:'unsupported'},summary:counts,monthly:known?Array.from({length:12},(_,i)=>({year:2025,month:i+1,crash_count:i===0?2:0,fatal_crash_count:i===0?1:0,fatalities:null,casualties:null})):[],yearly:known?[{year:2025,...counts}]:[],severity:known?[{code:'F',label:'Fatal',count:1},{code:'N',label:'Non-fatal',count:1}]:[]};
 }) as typeof publicationRead;
 const provider=createPublishedProvider(catalog,createOfficialProvider(await loadOfficialSnapshot()),read);
 await page.route('**/api/data/**',async route=>{
  const u=new URL(route.request().url()),p=u.searchParams,report=u.pathname.split('/').at(-1);
  if(report==='catalog')return route.fulfill({json:catalog});
  seen.push(p.get('releaseId') || 'missing');
  expect(p.get('from')).toMatch(/^20(?:24|25)-01-01$/);
  expect(p.get('to')).toMatch(/^20(?:24|25)-12-31$/);
  const f={source:p.get('source')!,dateRange:{from:p.get('from')!,to:p.get('to')!},datasetVersion:LOCAL_VERSION,batchId:release,releaseId:release};
  const data=report==='overview'?await provider.getOverview(f):report==='timeseries'?await provider.getTimeSeries(f,p.get('granularity')==='yearly'?'yearly':'monthly'):report==='severity'?await provider.getSeverityDistribution(f):report==='metadata'?await provider.getDatasetMetadata():await provider.getMapData(f);
  return route.fulfill({json:data});
 });
 let agentContext:unknown;
 await page.route('**/api/agent',async route=>{agentContext=route.request().postDataJSON().context;return route.fulfill({contentType:'application/x-ndjson',body:[{type:'visualization',view:{id:'fixture-null-values',title:'Synthetic unavailable deaths',kind:'line',rows:[{period:'2025',livesLost:null}],x:'period',y:'livesLost',series:null,evidenceId:'fixture-evidence',source,period:'2025',truncated:false}},{type:'message',text:'Transport fixture: 2 crashes; deaths unknown.',simulated:true},{type:'done',model:'fixture'}].map(event=>JSON.stringify(event)).join('\n')+'\n'});});
 await page.goto('/');
 await page.getByRole('combobox',{name:'Data source'}).click();
 await page.getByRole('option',{name:source,exact:true}).click();
 await expect(page.locator('.metric-value').first()).toHaveText('2');
 await expect(page.locator('.metric-value').nth(2)).toHaveText('—');
 await expect(page.getByText('Unavailable for this source · see definition',{exact:true})).toBeVisible();
 await expect(page).toHaveURL(new RegExp(`releaseId=${release}`));
 await expect(page).toHaveURL(/from=2025-01-01&to=2025-12-31/);
 await page.getByRole('link',{name:'Analytics',exact:true}).click();
 await expect(page.getByRole('button',{name:source,exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(page.locator('.analytics-chart canvas').first()).toBeVisible();
 await page.getByRole('region',{name:'Time and change'}).getByRole('button',{name:'Casualties',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'This source does not provide casualties.'})).toBeVisible();
 await page.getByRole('region',{name:'Time and change'}).getByRole('button',{name:'Lives lost',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Lives lost unavailable for this selection. Unknown observations are not zero.'})).toBeVisible();
 await page.getByRole('button',{name:/Ask AI/}).first().click();
 await page.getByRole('textbox',{name:'Message ARSIA assistant'}).fill('How many crashes in this selection?');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByText('Transport fixture: 2 crashes; deaths unknown.')).toBeVisible();
 await expect(page.getByRole('status').filter({hasText:'No known values for livesLost. Unknown observations are not zero.'})).toBeVisible();
 await expect(page.locator('.agent-viz').getByRole('cell',{name:'Unknown',exact:true})).toBeVisible();
 expect((agentContext as {filters:{releaseId:string;source:string}}).filters).toMatchObject({releaseId:release,source});
 expect(seen.length).toBeGreaterThan(4);expect(new Set(seen)).toEqual(new Set([release]));
 await page.goto('/data'+new URL(page.url()).search);
 const sourceCard=page.locator('.dataset-card').filter({has:page.getByRole('heading',{name:catalog.sources[0].title,exact:true})});
 await expect(sourceCard).toContainText('Local publication');
 await expect(sourceCard).toContainText('Source batch');
 await expect(sourceCard).toContainText(catalog.sources[0].batchId);
 await expect(sourceCard).toContainText('Release');
 await expect(sourceCard).toContainText(release);
 await expect(sourceCard).toContainText('geography unavailable');
});

test('annual-only publications show known deaths without inventing crash counts or months',async({page})=>{
 const annualCatalog={...catalog,coverage:{from:'2025-01-01',to:'2025-12-31'},sources:catalog.sources.map(s=>({...s,coverage:{from:'2025-01-01',to:'2025-12-31'},capabilities:{...s.capabilities,monthly:false,severity:false}}))};
 const read=(async(_path:string,q:Record<string,string>)=>{
  const known=q.from.startsWith('2025');const summary={crash_count:null,fatal_crash_count:null,fatalities:known?7:null,casualties:null};
  return {release_id:release,batch_id:annualCatalog.sources[0].batchId,source_id:source,coverage:{...annualCatalog.coverage,complete:known},availability:known?'available':'no_results',summary,monthly:[],yearly:known?[{year:2025,...summary}]:[],severity:[]};
 }) as typeof publicationRead;
 const provider=createPublishedProvider(annualCatalog,createOfficialProvider(await loadOfficialSnapshot()),read);
 await page.route('**/api/data/**',async route=>{
  const url=new URL(route.request().url()),p=url.searchParams,report=url.pathname.split('/').at(-1);
  if(report==='catalog')return route.fulfill({json:annualCatalog});
  const f={source:p.get('source')!,dateRange:{from:p.get('from')!,to:p.get('to')!},datasetVersion:LOCAL_VERSION,batchId:release,releaseId:release};
  const data=report==='overview'?await provider.getOverview(f):report==='timeseries'?await provider.getTimeSeries(f,p.get('granularity')==='yearly'?'yearly':'monthly'):report==='severity'?await provider.getSeverityDistribution(f):report==='metadata'?await provider.getDatasetMetadata():await provider.getMapData(f);
  return route.fulfill({json:data});
 });
 await page.goto('/analytics');
 await expect(page.getByRole('heading',{name:'Trend over time',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'No data for this selection',exact:true})).toHaveCount(0);
 await expect(page.getByTestId('analytics-total')).toHaveText('—');
 await expect(page.getByRole('button',{name:'Monthly',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'Yearly',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(page.getByRole('status').filter({hasText:'Crashes unavailable for this selection.'})).toBeVisible();
 await page.getByRole('region',{name:'Time and change'}).getByRole('button',{name:'Lives lost',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Lives lost unavailable for this selection.'})).toHaveCount(0);
 await page.getByRole('button',{name:'View values',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText('2025');
 await expect(page.getByRole('dialog').getByText('7',{exact:true})).toBeVisible();
});

test('fresh sessions discover publications while restored release URLs remain fixed',async({page})=>{
 const nextRelease='cccccccc-1111-4111-8111-cccccccccccc',futureRelease='dddddddd-1111-4111-8111-dddddddddddd';
 let latest=release;
 await page.route('**/api/data/catalog*',route=>{
  const requested=new URL(route.request().url()).searchParams.get('releaseId') || latest;
  if(requested==='unavailable') return route.fulfill({json:SNAPSHOT_CATALOG});
  return route.fulfill({json:{...catalog,releaseId:requested,batchId:requested}});
 });
 await page.route('**/api/imports/**',route=>{
  const path=new URL(route.request().url()).pathname;
  return route.fulfill({json:path.endsWith('/health')?{status:'ok',worker:{alive:true}}:path.endsWith('/catalog')?{release_id:null,sources:[]}:{jobs:[]}});
 });
 await page.goto('/imports');
 await expect(page).toHaveURL(new RegExp(`releaseId=${release}`));
 latest='unavailable';
 const fallbackResponse=page.waitForResponse(r=>r.url().includes('/api/data/catalog')&&!new URL(r.url()).searchParams.has('releaseId'));
 await page.evaluate(()=>window.dispatchEvent(new Event('arsia:publication')));
 await fallbackResponse;
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await expect(page).toHaveURL(new RegExp(`releaseId=${release}`));
 latest=nextRelease;
 await page.evaluate(()=>window.dispatchEvent(new Event('arsia:publication')));
 await expect(page).toHaveURL(new RegExp(`releaseId=${nextRelease}`));
 await page.reload();
 await expect(page.getByRole('heading',{name:'From source files to evidence.'})).toBeVisible();
 latest=futureRelease;
 await page.evaluate(()=>window.dispatchEvent(new Event('arsia:publication')));
 await expect(page).toHaveURL(new RegExp(`releaseId=${nextRelease}`));
 await page.getByRole('button',{name:'Local release',exact:true}).click();
 await expect(page).toHaveURL(new RegExp(`releaseId=${futureRelease}`));
});
