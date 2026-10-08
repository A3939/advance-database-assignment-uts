> 2026-09-29 AI 第一阶段更新：新增 `POST /api/agent`：服务端 Responses API + 受控只读工具，NDJSON 流式事件；错误不回退 mock。请求/事件、配置与边界见 [AI.md](AI.md)。旧模拟 Agent 说明已由此覆盖，Imports 模拟保持不变。

# 前端只读接口

权威契约为 [src/services/contracts.ts](src/services/contracts.ts)。组件从 `src/services/index.ts` 消费 `ArsiaService`，默认使用 `http-provider.ts`，通过 Next.js Node 路由读取固定官方项目快照。旧 `mock-provider.ts` 仅保留为单元测试 fixture；本节描述已经实现的接口，不是未来 `/api/v1` 提案。

## 固定上下文与请求参数

应用内部使用 `Filters = { source, dateRange: { from, to }, datasetVersion, batchId, regionId? }`，HTTP 映射为以下查询参数：

| 参数 | 规则与默认值 |
| --- | --- |
| `regionId` | 可选 ABS 2024 LGA 代码；必须属于所选单州，All + regionId / 未知代码返回 400。切换来源清除地区 |
| `source` | `All` / `NSW` / `VIC` / `QLD`；默认 `All` |
| `from` | 含首日的有效 ISO 日期，必须为月初；默认 `2020-01-01` |
| `to` | 含末日的有效 ISO 日期，必须为月末；默认 `2024-12-31` |
| `datasetVersion` | 默认 `official-v1` |
| `batchId` | 默认 `bcc5da57-25f2-41ec-9925-bef421b02671` |

参数名称是 `datasetVersion` / `batchId`，不使用 `version` / `batch` 别名。`from` 不能晚于 `to`；起止年份差不能超过 20。来源切换保留同一官方批次，不拼接 demo 批次名。只支持当前固定批次，传入其他版本或批次会得到不支持的数据状态，不会自动回退或切换到最新数据。

示例：

```text
GET /api/data/overview?source=NSW&from=2020-01-01&to=2024-12-31&datasetVersion=official-v1&batchId=bcc5da57-25f2-41ec-9925-bef421b02671
GET /api/data/timeseries?source=QLD&from=2023-07-01&to=2024-06-30&granularity=monthly
```

## 已实现的 GET 路由

| 端点 | 返回与边界 |
| --- | --- |
| `/api/data/overview` | `Response<Overview>`；四指标、定义、状态，单州 fatalShare；All 分州列值、不计算全国总值 |
| `/api/data/timeseries` | `Response<TimePoint[]>`；`granularity=yearly`（默认）或 `monthly`，四指标均允许 `null` |
| `/api/data/severity` | `Response<Severity[]>`；仅完整 `2020-01-01` 至 `2024-12-31` 可用，保留来源原分类与定义 |
| `/api/data/map` | `Response<MapData>`；All 来源级计数和州参考边界；单州真实名称匹配 LGA 汇总，`regionMode: lga`、matching coverage 和当前地区代码 |
| `/api/data/records` | `Response<Records>`；始终明确 `unsupported`，不暴露事故级记录 |
| `/api/data/metadata` | `Dataset[]`，直接返回三州固定快照元数据，不使用 `Response<T>` 包装 |
| `/api/data/region-evidence` | 前端派生层方法、原始文件哈希、边界哈希、地区 crosswalk、歧义与对账统计 |
| `/api/data/evidence` | `{ demo: false, ...provenance }`，直接返回固定批次证据 |

所有路由均校验公共筛选参数。metadata/evidence 返回已接入快照本身的元数据，不随筛选缩小内容，也不切换到请求中的其他版本。records 可校验 `page`（1–100000，默认 1）和 `pageSize`（1–50，默认 20）；由于没有记录数据，尚不实现实际搜索、排序或分页结果。provider 保留的 search/sort/direction 参数不代表服务端已提供这些能力。

路由使用 Node runtime、动态响应与 `Cache-Control: no-store`，并设置 `X-Content-Type-Options: nosniff`。另有 `POST /api/agent` 只读分析路由；没有数据写入或上传路由，没有数据库连接。

## 返回状态和数值语义

一般数据接口返回 `Response<T> = { data, meta }`。meta 包含 `demo: false`、来源、版本、批次、单位、定义、evidence、availability、reason 和 coverage。coverage 描述快照的 `2020-01-01` 至 `2024-12-31` 月度覆盖；请求跨出该区间但仍有观测时，只聚合覆盖内观测，`complete: false`，不填补缺失月份。

| availability | 含义 | 数值处理 |
| --- | --- | --- |
| `available` | 该项有观测且适用 | 已知的真实零可为 `0` |
| `unknown` | 有观测，但对应指标包含未知值或 known-count 不完整 | 指标为 `null`，附原因，不把未知当零 |
| `unsupported` | 当前快照或来源不支持请求的能力 | 以 `null` / 空集合及原因表示；不能解释为未发生事故 |
| `no_results` | 请求月份在该快照中没有观测 | 空集合 / `null`，说明无覆盖 |

指标级状态与集合级 meta 可以不同。例如 All 的 meta 可为 available，但每个合并 `Metric.value` 都为 `null / unsupported`；实际州值通过 `bySource` 提供。单个未知 measure 不应使其他已知指标也变成零。TimePoint 的四个计数均可为 null，消费端必须保留这一语义。

HTTP 400 用于无效来源、日期、月边界、granularity 或分页参数，返回 `{ error }`；未知 report 为 404。文件缺失、SHA256 不匹配或快照加载失败为 503，返回不包含本机路径的错误，不用 mock 掩盖故障。合法请求中的数据不支持/无覆盖通常仍为 HTTP 200，由 availability/reason 表达。

## 指标、地图与记录限制

- 四指标对应 `crash_count`、`fatal_crash_count`、`fatality_count`、`casualty_count`。NSW 取 Crash 级统计，VIC 只取 Accident 级统计，QLD 为 casualty-crash 覆盖。受限 VIC Person/Vehicle 与 QLD 不存在的 Unit 明细不能成为前端报告来源。
- All 的 TimePoint 和 Severity 用 `source` 分组，不合并州分类。不同州的计数不是暴露量校正后的风险，也不构造全国总值。单州 `fatalShare` 是已知致命状态事故中的致命事故比例，不是人口/交通暴露率。
- Severity 只在完整五年区间可用。其他有覆盖区间返回 `unsupported` 和明确理由，不把全量严重程度按月份比例拆分；无覆盖请求继续使用 `no_results`。
- Country MapData 使用本地 `australia-states.geojson`，`legendLabel: "Recorded crashes by source"`，states 的 count 由来源月度事故数聚合，缺失时省略。标签坐标仅用于地图标注，不是事故位置。
- State MapData 的 `regions` 是实际 LGA 代码/名称/事故数/致命事故数，**不含事故坐标**。`coverage` 返回所选月份的州级 matched/unmatched/total/percentage；选中 LGA 后地图保留整州范围，突出选区。仅选区附最多 8 个原生 Town/Suburb 标签和对应事故数。地区四指标、趋势与严重程度来自 hash-verified 新派生聚合；未匹配部分仍在州总量中。
- Records 的 `rows: []`、`total: 0` 表示当前 API 暴露零条明细，并非事故数为零。`aggregateCount` 保留单州汇总（All 为 null），`sampleOnly: false`；导出不附虚构记录。

## 快照完整性与证据

`src/server/official-data.ts` 只读取固定 `data/official/reader-results.json` 和 `provenance.json`，不接受请求传入文件路径。服务端核对两个文件的固定 SHA256、版本/批次、succeeded 发布状态和 provenance 中的 reader hash。成功加载结果在进程内缓存；客户端 no-store 不表示每次请求都会从磁盘重新导入。

Evidence 包括 recordedAt `2026-09-28T12:43:08.025519+00:00`、runtime commit、input fingerprint、输入文件与证据 hash、三州总量和 QA。当前 QA01–QA06 pass，QA07 location limited；`independentMemberSignoff: false`、`finalPlatformAccepted: false`。这证明的是所记录批次的项目证据，不是实时政府认证或全平台验收。

重新接入脚本、默认 artifacts 路径和以后变更批次/hash 的审查要求见 [README.md](README.md#重新接入与更新快照)。接口不会自动发现最新产物。

## 真实只读助手与导入预览

`sendAgentMessage(context, message, signal, history)` 通过 `POST /api/agent` 获取 NDJSON 流，返回 `AsyncIterable<AgentEvent>`。message 为增量文本；progress、tool_result、evidence、done、error 描述状态。工具和模型输出均为 `simulated: false`，失败不回退模板。AbortSignal 传递到 SDK；历史按当前筛选上下文隔离。

工具包括元数据、四指标、趋势、可比时间段、严重程度与批次证据，复用现有服务端聚合适配器。算术由代码完成。接口、服务端模型配置及限制见 [AI.md](AI.md)。

`createImportJob(files)` / `getImportJobStatus(jobId)` 仍为浏览器元数据模拟，不读取文件内容、不上传、不入库。Imports 与真实 AI 查询是独立能力。

## Analytics 派生分析

`src/services/analytics.ts` 的 `getAnalytics(filters, service = arsia)` 通过服务并行读取 overview、monthly series、severity、前一年同月 series 和 metadata，再生成 `Response<AnalyticsData>`。它不直接读 fixture；真实月度观测共同用于趋势、热图、表格和导出。

- All 明确进入 NSW 单州分析，同一官方批次保持不变。不同来源、批次、版本或互不相符的聚合总量不能混用。
- 四指标保留 null；`yoyPct` 为百分数（如 -6.1），`fatalShare` / `severity.share` 为 0–1 比例。同比使用相同月份，缺失或零基期为 null。
- 年度 `complete` 表示所选月份完整，`fullYear` 表示选择了 12 个月；部分年份须显示月份范围。月份均值仅取可用观测，已知零参与均值。
- severity 的 availability/reason 独立保留；不将子区间不支持伪装为零分布。表格是月/年聚合，不是事故明细。
- JSON 导出携带真实数据标记、filters、view、analysis、定义与来源元数据；不包含合成季节性说明或虚构事故记录。

## LGA 名称匹配扩展

`src/server/region-data.ts` 包装原 `createOfficialProvider()`，原快照文件与原始边界均不改写。regionId 存在时，overview/timeseries/severity/records.aggregateCount 使用该区域；map 仍展示整个州以便切换地区。regionId 缺省时保留原州指标与州级 severity 全期限制。区域 severity 逐月从原始事件计数，无比例拆分。地区零表示覆盖内没有匹配事件；范围外返回 no_results/null。完整方法及局限见 [REGIONS.md](REGIONS.md)。

## 分析工作空间扩展

`POST /api/agent` 额外产生 `artifact {artifact}`、`visualization {view}` 事件。契约见 `src/services/analysis-contracts.ts`；图表仅含数据与受控 kind/x/y/series，不接受模型提供的 JavaScript。当前上下文始终由服务端校验。

`GET /api/analysis/artifacts/[id]` 下载经 SHA256 校验的分析附件；ID 是服务端随机 capability，不接受路径。24 小时失效返回 404，跨源浏览器请求返回 403。CSV/Python/报告等均按附件传输，不内嵌执行。当前为本地无账户模式，生产用户隔离尚未开放。

工具和安全边界详见 `ANALYSIS_WORKSPACE.md`。
