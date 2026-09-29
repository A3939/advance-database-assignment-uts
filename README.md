> 独立仓库：当前项目根目录为 `Workspace/ARSIA`，远端为 `https://github.com/yyyZYH/ARSIA.git`。直接在此目录运行 npm 命令；当前预览为 http://127.0.0.1:3103。迁移方式及外部快照重建输入见 [MIGRATION.md](MIGRATION.md)。

> 2026-09-29 地区扩展：已接入真实 LGA 名称匹配汇总，支持地图着色、悬停计数、区域筛选和 Town/Suburb 详情。详见 [REGIONS.md](REGIONS.md)。此前预览使用 3102，独立仓库当前预览使用 3103。

> 2026-09-29 AI 第一阶段更新：当前 Ask AI 已连接真实 OpenAI Responses API；不再使用模板回复。模型、运行方式、只读工具、隐私与限额见 [AI.md](AI.md)。数据仍是项目快照。

# ARSIA Web 本地分析平台

当前界面通过 Next.js 只读 API 展示 ARSIA 已发布的官方来源项目快照，覆盖 NSW、VIC、QLD 的 2020–2024 年数据。统计来自真实项目导出，不是合成演示数据；它也不是实时数据库或持续更新的政府数据源。Ask AI 已连接真实 OpenAI Responses API，只读查询经过验证的聚合统计；Imports 仍为文件元数据预览。

本目录不连接或修改原 Python / PostgreSQL 流水线。此前用于验收的数据库已清理、不再运行；本地 Web 启动使用随项目保存的聚合文件，无需恢复该数据库。

## 本地运行

需要 Node.js 20.9+ 和 npm。进入本目录：

```bash
npm ci
npm run dev -- --port 3100
```

打开 http://127.0.0.1:3100。端口占用时选择 3101 等空闲端口，不结束已有进程。生产预览：

```bash
npm run build
npm run start -- --port 3100
```

地图及数据浏览无需数据库凭证或地图 key；真实 Ask AI 需要已有服务端 `OPENAI_API_KEY` 配置。字体、ABS GeoJSON、MapLibre worker 和已接入的数据快照均由本地服务提供。`postinstall`、`predev`、`prebuild` 自动复制锁定版本的 worker/shared 文件及许可证到被忽略的 `public/vendor/`；ES module worker 需要相邻 shared 文件。

只读 API 需要 Next.js Node 服务，不能仅把页面作为静态 HTML 托管。本轮没有部署或发布网站。

## 页面与能力

- **Overview**：整月日期/来源筛选、四项指标、分州参考地图、年/月趋势、严重程度、带来源元数据的 JSON 导出、只读 AI Agent 和证据抽屉。保留左侧无边框地图与右侧双图布局；不恢复首页记录表或持续底部 Demo 行。
- **Analytics**：独立 `/analytics` 页面。单州四指标趋势、相同月份同比、年×月热图、月份均值、严重程度数量/占比和聚合数据表，共用真实月度统计。All 进入深入分析时明确选中 NSW；旧 `/explore` 重定向至此。
- **Data**：三州数据集、指标定义、来源限制、固定版本/批次和 QA 证据；读取失败时提供明确错误与重试入口。
- **Imports**：选择/拖入文件后只查看名称、大小和类型。浏览器内模拟 queued → running → needs_input，不读取或上传内容、不解析、不入库、不持久化。
- **Reports**：尚未接入报告编辑和保存，提供返回分析入口。

默认 dark，light 偏好本地持久化；主题切换同步更新地图、图表与覆盖层。Overview 在宽度 >1100px 且高度 ≥720px 时填充桌面视口，地图与 severity 面板同底边，底部留 16–24px；更矮窗口、手机和平板自然滚动。五页共享桌面 88px 顶栏。Analytics 自然纵向滚动，热图与宽表仅局部横向滚动。当前视觉要求见 [DESIGN.md](DESIGN.md)。

## 当前数据快照

| 项目 | 固定值 |
| --- | --- |
| datasetVersion | `official-v1` |
| batchId | `bcc5da57-25f2-41ec-9925-bef421b02671` |
| 覆盖 | `2020-01-01` 至 `2024-12-31`，可按整月筛选 |
| recordedAt | `2026-09-28T12:43:08.025519+00:00` |
| 运行模式 | 固定项目快照；不是 live DB / live government feed |

完整区间的四项计数来自 [provenance.json](data/official/provenance.json)，单位分别为事故、事故、人、人。下表按来源分别列出，不计算全国合计：

| 来源 | Crashes | Fatal crashes | Lives lost | Casualties |
| --- | ---: | ---: | ---: | ---: |
| NSW | 92,082 | 1,388 | 1,507 | 78,154 |
| VIC | 72,170 | 1,182 | 1,265 | 91,798 |
| QLD | 66,624 | 1,304 | 1,424 | 88,609 |

这些数值具有不同统计口径。NSW 使用固定 Crash 文件的事故级指标；VIC 仅报告 Accident 级指标，不使用受限 Person/Vehicle 明细；QLD 为 casualty-crash 事件覆盖，不代表道路上的全部事故，也没有 Unit 明细。Fatal crashes 是致命事故次数，Lives lost 是死亡人数，两者不能互换。指标定义通过 API、Data 页和导出保留。

All 将各州值、趋势和原始严重程度分类分开展示，合并值为 `null / unsupported`。未知指标保持 `null / unknown`，无覆盖为 `no_results`，真实零才显示为 0。月度观测是项目导出，不再使用演示年度权重分配；部分覆盖会提示，缺失月份不补零。

原正式州级严重程度仅导出了完整 2020–2024 区间。选中 LGA 后，新增派生层按原始事故月份直接统计地区严重程度，支持整月筛选，不是比例拆分。选择其他有覆盖区间时显示 `unsupported` 及原因；无覆盖区间显示 `no_results`，不按比例生成月度分类。快照 API 不提供事故级记录，records 返回明确的不支持状态；导出不附虚构记录。

国家地图使用来源级事故数对 ABS 参考州边界着色，图例为 “Recorded crashes by source”。这不是事故位置、行政区热点或可比风险率。进入单州后按源文件 LGA 名称与 ABS 2024 边界匹配的真实事故计数着色，可选择地区联动四指标、趋势和严重程度；未匹配记录保留在州总量中。点击 Area details 可查看 NSW Town / QLD Suburb 聚合。原正式流水线的事故点地图仍不可用；这一新增前端派生层不修改 QA07 或坐标资格。

边界来自 ABS ASGS 2021 州/领地与 ASGS 2024 LGA_GEN，CC BY 4.0。Map layer evidence 提供署名、年份、层级和链接；[public/geo/provenance.json](public/geo/provenance.json) 保存来源、泛化与 SHA256。`scripts/fetch-boundaries.py` 可手动更新，正常启动不重新下载。无 WebGL 时使用本地 SVG 参考边界降级并提示限制。

## 读取链路与证据

```text
页面 / Analytics 派生分析
  → src/services/index.ts → http-provider.ts
  → GET /api/data/{overview,timeseries,severity,map,records,metadata,evidence}
  → src/server/official-data.ts
  → data/official/reader-results.json + provenance.json
```

[contracts.ts](src/services/contracts.ts) 定义服务契约，[config.ts](src/services/config.ts) 固定默认日期、版本和批次，[API.md](API.md) 说明实际 HTTP 参数与状态。服务端只读取固定文件路径，校验 reader 与 provenance 的 SHA256、版本/批次和成功发布状态；文件不完整或校验失败返回 503，不回退到 mock。成功载入的快照在服务器进程内缓存，不追踪外部最新产物。

生产入口不导入 `mock-provider.ts`；旧 mock 和合成 fixture 保留供单元测试使用。`import-preview.ts` 单独提供 Imports 的元数据演示，不把 mock 报表引入生产链路。真实 AI 通过 `/api/agent` 使用受控只读工具，保留当前筛选上下文与实际工具证据；不执行任意 SQL、文件操作或真实导入。具体配置、限额与测试边界见 [AI.md](AI.md)。

固定证据记录为：发布状态 succeeded，QA01–QA06 pass，QA07 location limited；`independentMemberSignoff: false`、`finalPlatformAccepted: false`。Data 页和 evidence API 必须保留这一边界，不能将局部检查通过表述为 QA 全通过或全项目验收完成。

## 重新接入与更新快照

随项目保存的两个快照文件足够支持正常运行，不需要本机保留原验收 artifacts。需要从已审查证据重新生成时，在本仓库根目录执行：

```bash
node scripts/import-official-snapshot.mjs
# 或显式指定原导出目录与证据索引：
node scripts/import-official-snapshot.mjs /path/to/official-run /path/to/current-evidence.json
```

默认导出目录为同级工作区的 `artifacts/role-e-completion-20260928/official-v1`，默认证据索引为同级工作区的 `artifacts/pr49-pr50-review-20260928/current-evidence.json`，均由脚本位置定位，不依赖调用时的工作目录；重导入需要这些原始文件仍可访问。输出写入 `data/official/`，不连接数据库、不重跑流水线。

脚本核验索引中 reader-results、manifest、raw-qa、source-metrics、recovery-cost 五个文件的 SHA256，核对固定 reader hash、批次发布/receipt 状态、报表及行来源身份、每州 60 个唯一月份，以及四指标月/年汇总和严重程度总量对账。

以后切换批次必须先审查新证据、来源政策、覆盖范围和对账结果，再显式更新 config 中的批次/版本、导入脚本的固定批次/hash、服务端 reader/provenance hash，并重新验证。不能自动选择最新 artifacts、跳过 hash 检查或把旧批次标识贴到新数据上；已载入快照的进程也不会自动热更新数据文件。

## 验证

以下是可执行检查命令，不代表本次文档编辑已经运行它们：

```bash
npm run typecheck
npm run lint
npm run test
npm run build
# 启动本地服务后，在独立测试浏览器中检查：
ARSIA_BROWSER_CHANNEL=chrome npm run test:e2e
```

最后一条使用已安装 Chrome 的独立临时 profile，不操作用户现有窗口。可用 `ARSIA_TEST_URL` 指定另一端口；这些是可选测试环境变量，应用运行不需要 `.env`。测试截图在被忽略的 `artifacts/`，失败 trace 在 `test-results/`。实际执行范围与结果仅见 [VERIFICATION.md](VERIFICATION.md)；本目录专项验证不代表 ARSIA 全项目验收。
