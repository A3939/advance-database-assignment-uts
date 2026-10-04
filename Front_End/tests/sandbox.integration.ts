// Explicit opt-in: runs isolated containers, never host Python and never paid APIs.
import test from "node:test";
import assert from "node:assert/strict";
import { runPython } from "../src/server/analysis/sandbox";
const signal = new AbortController().signal;
test("isolated Python can compute using data copies and generate real downloadable outputs", async () => {
  const r = await runPython(
    `import json, pandas as pd\nimport matplotlib.pyplot as plt\nd=json.load(open('/data/input.json'))\nf=pd.DataFrame(d['rows'])\nprint(f['crashes'].sum())\nf.to_csv('/analysis/counts.csv',index=False)\nf.plot(x='year',y='crashes');plt.savefig('/analysis/chart.png')`,
    {
      rows: [
        { year: 2023, crashes: 18711 },
        { year: 2024, crashes: 18939 },
      ],
    },
    signal,
  );
  assert.equal(r.status, "succeeded", r.error || "");
  assert.match(r.stdout, /37650/);
  assert.deepEqual(
    r.files.map((f) => f.name),
    ["chart.png", "counts.csv"],
  );
});
test("network, host secrets, root FS and input writes denied; symlink artifacts not exported", async () => {
  const r = await runPython(
    `import os,socket,json\nchecks={}\nfor key,path in [('host','/Users/zhengpeixian/.ssh'),('key','/data/.env.local')]:\n checks[key]=os.path.exists(path)\nchecks['env_key']=bool(os.getenv('OPENAI_API_KEY'))\nfor key,path in [('input_write','/data/input.json'),('root_write','/etc/arsia-test')]:\n try:\n  open(path,'w').write('x');checks[key]=True\n except OSError:checks[key]=False\ntry:\n socket.create_connection(('1.1.1.1',443),timeout=1);checks['network']=True\nexcept OSError:checks['network']=False\nos.symlink('/data/input.json','/analysis/leak.json')\nprint(json.dumps(checks))`,
    { rows: [] },
    signal,
  );
  assert.equal(r.status, "succeeded", r.error || "");
  assert.deepEqual(JSON.parse(r.stdout), {
    host: false,
    key: false,
    env_key: false,
    input_write: false,
    root_write: false,
    network: false,
  });
  assert.equal(r.files.length, 0);
});
test("Python exception is returned for repair, then a corrected run succeeds", async () => {
  const bad = await runPython("raise ValueError('fix the column')", {}, signal);
  assert.equal(bad.status, "failed");
  assert.match(bad.error!, /fix the column/);
  const good = await runPython("print(2 + 2)", {}, signal);
  assert.equal(good.status, "succeeded");
  assert.equal(good.stdout.trim(), "4");
});
test("infinite loop timeout and user cancellation terminate only the dedicated sandbox", async () => {
  const r = await runPython("while True: pass", {}, signal, 1000);
  assert.equal(r.status, "failed");
  const abort = new AbortController();
  const pending = runPython("import time; time.sleep(60)", {}, abort.signal);
  setTimeout(() => abort.abort(), 1200);
  await assert.rejects(pending);
});
test("memory/file limits are enforced and malformed report format is repairable", async () => {
  const memory = await runPython("x=bytearray(700000000)", {}, signal);
  assert.equal(memory.status, "failed");
  const file = await runPython(
    "open('/analysis/too-big.txt','w').write('x'*5000000)",
    {},
    signal,
  );
  assert.equal(file.status, "failed");
  const report = await runPython(
    "open('/analysis/report.md','w').write('Title'+chr(92)+'nText')",
    {},
    signal,
  );
  assert.equal(report.status, "failed");
  assert.match(report.error!, /line breaks/);
});
test("the workspace rejects invented report citations, permits repair, and caps Python runs", async () => {
  const { AnalysisWorkspace } =
    await import("../src/server/analysis/workspace");
  const { loadOfficialSnapshot, createOfficialProvider } =
    await import("../src/server/official-data");
  const { loadRegionSnapshot, createRegionalProvider } =
    await import("../src/server/region-data");
  const { DEFAULT_FILTERS } = await import("../src/services/config");
  const regional = await loadRegionSnapshot();
  const w = new AnalysisWorkspace(
    { page: "/", filters: DEFAULT_FILTERS },
    createRegionalProvider(
      createOfficialProvider(await loadOfficialSnapshot()),
      regional,
    ),
    regional,
  );
  await w.execute(
    "workspace_query",
    {
      dataset: "monthly_metrics",
      source: "NSW",
      dateRange: null,
      regionId: null,
      groupBy: ["year"],
      metrics: ["crashes"],
      where: [],
      orderBy: null,
      limit: 5,
    },
    signal,
    "E1",
  );
  const bad = await w.execute(
    "python_analysis",
    {
      queryIds: ["Q1"],
      title: "Report",
      code: "open('/analysis/report.md','w').write('Based on [E99]')",
    },
    signal,
    "E2",
  );
  assert.equal(bad.status, "failed");
  assert.deepEqual(bad.artifacts, []);
  assert.match(String(bad.error), /unavailable evidence/);
  const good = await w.execute(
    "python_analysis",
    {
      queryIds: ["Q1"],
      title: "Report",
      code: "import json\np=json.load(open('/data/input.json'))\nopen('/analysis/report.md','w').write('Source: '+p['queries']['Q1']['evidenceId'])",
    },
    signal,
    "E3",
  );
  assert.equal(good.status, "succeeded");
  assert.equal((good.artifacts as unknown[]).length, 3);
  await w.execute(
    "python_analysis",
    { queryIds: ["Q1"], title: "Calculation", code: "print(1)" },
    signal,
    "E4",
  );
  await assert.rejects(
    w.execute(
      "python_analysis",
      { queryIds: ["Q1"], title: "Fourth run", code: "print(1)" },
      signal,
      "E5",
    ),
    /limit/,
  );
});
