# ARSIA Front_End · 展示版与数据接入说明

本目录是迁入本项目的独立 Next.js 展示版，包含刚完成的界面修改。导航为 **Overview / Analytics / Studio / Data**：Studio 外观与其他导航一致，点击无动作；Data 仅展示紧凑的数据目录和上传模式，不执行上传、导入或发布。Imports 和 Reports 已移除。详情弹窗仅保留标题、说明和信息表。

**现在即可运行，不需要先导入数据或连接业务数据库。** 本目录自带 NSW、VIC、QLD 的固定项目统计快照。若要展示项目的其他批次，需由项目后端提供下述统计数据，再完成显式适配；当前实现不是自动读取最新数据库或任意 CSV 的通用导入器。

## 1. 启动

在 `Workspace_Github` 仓库根目录执行：

```bash
cd Front_End
npm ci
npm run dev -- --port 3101
```

本机迁移时已经保留依赖并启动服务，直接访问 <http://127.0.0.1:3101> 即可；首次克隆或依赖不完整时才需要 `npm ci`。验收环境为 Node.js 22.22.2、npm 10.9.7，依赖版本由 `package-lock.json` 固定。

这里使用 **3101**。仓库已有的 `frontend -> ../ARSIA` 链接仍指向主开发版，未修改；主版的 3100 服务也未重启。请区分 `Front_End/` 和 `frontend`，不要为运行本展示版停止主开发服务。

图表和地图不需要 `.env`、数据库密码、Docker 或 AI Key。Ask AI 是保留的可选独立功能，需要服务端配置及另行验收，详见 [AI.md](AI.md)；本次没有连接或调用 AI，也未验证其沙箱功能。

## 2. 页面如何取得数据

```text
Overview / Analytics / Map
  → src/services/http-provider.ts（同源 GET）
  → src/app/api/data/[report]/route.ts
  → src/server/official-data.ts + src/server/region-data.ts
  → 本目录 data/ 下的固定 JSON 快照 + public/geo/ 下的边界
```

- [contracts.ts](src/services/contracts.ts) 是浏览器接口类型。
- [official-data.ts](src/server/official-data.ts) 把项目 D05/D06 报表映射为界面指标。
- [region-data.ts](src/server/region-data.ts) 提供 LGA 地区聚合及地图联动。
- [config.ts](src/services/config.ts) 固定批次、版本和默认日期。
- [catalog-contracts.ts](src/services/catalog-contracts.ts) 和 [region-catalog.json](src/services/region-catalog.json) 提供来源及地区目录。

Next.js 在服务端读取文件并校验哈希，**没有连接父项目 PostgreSQL，没有在启动时执行 SQL 迁移或导入**。成功加载的快照在进程内缓存；浏览器请求 `no-store` 不表示服务会自动发现新批次。

当前快照：

| 项目 | 值 |
| --- | --- |
| `datasetVersion` | `official-v1` |
| `batchId` | `bcc5da57-25f2-41ec-9925-bef421b02671` |
| 来源 | `NSW` / `VIC` / `QLD`，分别对应 `official_nsw` / `official_vic` / `official_qld` |
| 覆盖 | `2020-01-01` 至 `2024-12-31`，每州 60 个月 |
| 模式 | 固定项目快照；不是实时政府数据或主开发版最新 release |

## 3. 已实现的数据 HTTP 接口

以下接口均为 **GET**，相对于本服务地址：

| 接口 | 返回值 | 页面用途及当前限制 |
| --- | --- | --- |
| `/api/data/overview` | `Response<Overview>` | 事故数、致命事故数、死亡人数、伤亡人数及口径；All 按州列值 |
| `/api/data/timeseries` | `Response<TimePoint[]>` | 月/年趋势、Analytics 热图、同比、月份均值和表格；加 `granularity=monthly` 或 `yearly`，默认 yearly |
| `/api/data/severity` | `Response<Severity[]>` | 严重程度分类与事故数；州级只有完整五年数据，LGA 扩展支持整月筛选 |
| `/api/data/severity-change` | `Response<SeverityChange>` | 严重程度哑铃图：用已校验逐月分类汇总对比所选首末年份的相同月份；All 分州展示，州总数包含未匹配地区，不拆分五年报表 |
| `/api/data/map` | `Response<MapData>` | 全国州界和单州 LGA 计数、匹配覆盖、选区；不是事故点坐标接口 |
| `/api/data/metadata` | `Dataset[]` | 来源标题、版本、批次、覆盖、定义和限制；不使用 `Response<T>` 包装 |
| `/api/data/evidence` | `{ demo: false, ...provenance }` | 固定批次的 QA、文件哈希、来源和发布证据 |
| `/api/data/region-evidence` | 地区扩展证据对象 | LGA 名称匹配、边界版本、匹配/未匹配对账 |
| `/api/data/records` | `Response<Records>` | 路由保留，但明细能力为 `unsupported`；`rows: []` 不表示事故为零 |

公共查询参数：

| 参数 | 规则 |
| --- | --- |
| `source` | `All`、`NSW`、`VIC`、`QLD`；默认 All |
| `from` / `to` | 含首尾日的 ISO 日期；月初至月末，起点不能晚于终点；默认上述五年 |
| `datasetVersion` / `batchId` | 默认上述固定值；不能省略批次语义或悄悄替换成最新版本 |
| `regionId` | 可选，所选单州的 ABS 2024 LGA 代码，如 VIC Melbourne `24600`；All 不支持地区参数 |

页面 URL 还保存 `metric`、`interval`、`overviewInterval`，这些是界面状态，不是上述报表的 API 参数。虽然共享类型保留 `releaseId` 字段，本展示版没有本地 release 发现或切换能力。

可直接执行的只读示例：

```bash
curl --get 'http://127.0.0.1:3101/api/data/overview' \
  --data-urlencode 'source=NSW' \
  --data-urlencode 'from=2020-01-01' \
  --data-urlencode 'to=2024-12-31' \
  --data-urlencode 'datasetVersion=official-v1' \
  --data-urlencode 'batchId=bcc5da57-25f2-41ec-9925-bef421b02671'

curl --get 'http://127.0.0.1:3101/api/data/timeseries' \
  --data-urlencode 'source=VIC' \
  --data-urlencode 'regionId=24600' \
  --data-urlencode 'granularity=monthly'
```

一般返回 `{ data, meta }`；`meta` 包含 `source`、`datasetVersion`、`batchId`、`availability`、`coverage`、`unit`、`definition`、`evidence`，以及可选 `reason`。指标本身也有独立的 `availability`：

- `available`：有可靠观测；实际零可以是 `0`。
- `unknown`：该指标未知，保留 `null`。
- `unsupported`：来源或当前实现不支持，不能按零处理。
- `no_results`：所选期间没有覆盖或观测。

无效参数返回 400，未知报表返回 404，文件缺失/哈希不匹配返回 503；有效但不支持的数据请求通常返回 200，并由 `availability/reason` 说明。All 不计算跨州合计，合计值为 `null`，各州实际值在 `bySource` 中。

另外保留 `POST /api/agent`（JSON 请求、NDJSON 事件）及 `GET /api/analysis/artifacts/[id]`（分析附件），它们不接收原始事故数据作为导入。**没有上传、创建导入任务、发布数据或 Studio API。** Data 页的两种模式只切换展示内容。

## 4. 需要项目提供哪些数据

前端需要的是**同一成功批次的统计结果、地区聚合和元数据**。浏览器不需要业务库连接，也不应直接获取整套 Raw/Vault/Canonical 表。

| 界面需求 | 项目需要提供的结果 | 当前可利用的项目模块 |
| --- | --- | --- |
| 四张指标卡、年/月趋势 | 按来源、年月的四项计数及已知值计数、覆盖状态 | [D05 query_trend](../src/arsia_d05/trend.py)，分别使用 `grain="month"` / `"year"`；四卡从选中月份汇总 |
| 严重程度图 | 来源内的分类代码、显示名、定义版本/文本和事故数 | [D06 query_severity](../src/arsia_d06/severity.py)；保持来源自己的分类 |
| 全国地图 | 各州事故数 + 州界 GeoJSON | 州数来自 D05；参考边界已随前端保存 |
| 州内 LGA 地图、地区联动 | 按来源 × 月 × LGA 的四指标及严重程度计数，地区代码/名称、未匹配数量 | 当前由本目录 LGA 扩展生成；项目现有 D07 事故点查询不能直接替代此结构 |
| 来源、批次和可信状态 | 批次 ID、dataset kind、发布状态、版本、覆盖、定义、限制、QA 与文件哈希 | 项目 manifest、发布/QA 证据及来源注册信息 |

项目已有 [D05–D08 查询说明](../docs/analysis-integration.md)。这些 Python 查询接收调用方的只读连接与固定成功批次，不是 HTTP 服务；仍需导出程序或服务端适配层包装结果。当前前端并没有自动调用这些 Python 模块。

D07 的真实事故点目前受来源政策限制；展示版使用参考边界及 LGA 名称匹配计数，不能把地区中心点当成事故位置。D08 车辆/交通单位明细不参与目前页面计算，不过现有固定快照导入脚本仍要求 `:map` 与 `:units` 的报表条目，用状态/原因明确表达不支持的能力。

### 4.1 州级报表格式

[reader-results.json](data/official/reader-results.json) 顶层按来源和报表命名，例如：

```text
官方来源：official_nsw、official_vic、official_qld
每个来源：:trend、:monthly、:severity、:map、:units
示例键：official_nsw:monthly
```

每个报表对象包含 `dataset_kind`、`batch_id`、`source_id`、`report`、`status`、`reason`、`rows`、`source_label`、`quality_limits`、`coverage_basis`、`comparison_scope`。项目 snake_case 字段在服务端适配成前端 camelCase：

| 项目字段 | 前端字段 | 含义 |
| --- | --- | --- |
| `crash_count` | `crashes` | 事故次数 |
| `fatal_crash_count` | `fatalCrashes` | 致命事故次数 |
| `fatality_count` | `livesLost` | 死亡人数 |
| `casualty_count` | `casualties` | 伤亡人数，按来源定义 |

月度行还需 `batch_id`、`source_id`、`period_year`、`period_month`、`coverage_status`、`fatal_crash_known_count`、`fatality_known_count`、`casualty_known_count`、`excluded_unknown_month_count`。原 D05 导出还保存 `dataset_kind`、`grain`、`requested_month_count`、`covered_month_count`、`month_known_count`、`coverage_basis`，应保留。

严重程度行需 `severity_code`、`severity_label`、`definition_version`、`definition_text`、`crash_count`，以及相同批次/来源和 `filter_year_from`、`filter_year_to`、`filter_months`。不能把一个全期分布按月份比例拆成子区间。

### 4.2 地区数据格式

[aggregates.json](data/regions/aggregates.json) 是另一份必需的本地快照。顶层为 `extensionVersion`、`batchId`、`datasetVersion`、`coverage`、`sources`。每个来源保存 `regions`、`severityLabels`、`rows`、`localities`、`unmatched`、`crosswalk`、`audit`。

每个地区月度 `rows` 元素的顺序固定：

```text
["YYYY-MM", "LGA_CODE", crashes, fatalCrashes, livesLost, casualties, [severityCounts...]]
```

严重程度数组与该来源的 `severityLabels` 一一对应。未匹配地区使用 `__unmatched__`，仍计入州总量。边界 GeoJSON 的 `region_id`、`region_name` 与地区目录一致；当前 ABS LGA 文件另保留 `lga_code_2024`、`lga_name_2024` 供生成器使用。地图颜色按事故数量分级；严重程度在独立图表显示。

如果项目暂时没有这种 LGA 聚合，可以保留本目录自带的同批次扩展。**不能把新州级批次和旧地区聚合混在同一页面。** 当前所有数据路由都会先加载两份快照，缺少地区快照也会导致服务失败，并不会自动降级为仅州级图表。

### 4.3 需要原始文件吗

**只运行当前展示版不需要。** 只有重新生成当前 LGA 扩展时，才需要父项目 `raw_datasource/` 中以下四个、与 provenance 哈希一致的文件：

| 文件 | 作用 |
| --- | --- |
| `nsw_crash_2020_2024.xlsx` | NSW 事故年月、LGA、严重程度、死亡/伤亡指标；Town 用于可选地区标签 |
| `vic_accident.csv` | VIC Accident 级日期、严重程度及事故级人数指标 |
| `vic_node.csv` | 通过 `ACCIDENT_NO + NODE_ID` 取得 LGA 名称；不是采用事故点坐标 |
| `qld_crash_locations.csv` | QLD 事故年月、LGA、严重程度、人数指标；Suburb 用于可选标签 |

父项目 [native-inputs.json](../config/native-inputs.json) 共登记七个资源，另外包括 NSW Traffic Unit、VIC Vehicle、VIC Person。它们属于项目原始数据/其他模块范围；这份展示版的四指标和 LGA 扩展**不要求导入全部七个原始文件**。VIC 当前快照只采用允许使用的 Accident 级指标，不能借接前端绕过 Person/Vehicle 的既有使用限制。

## 5. 重新接入与更新快照

### 5.1 展示版需要保留的文件

```text
data/official/reader-results.json    州级统计
data/official/provenance.json        固定批次、定义边界和证据
data/regions/aggregates.json         LGA 月度统计
data/regions/provenance.json         地区匹配与对账证据
public/geo/*.geojson                 州界、三州 LGA 参考边界
public/geo/provenance.json           边界来源/版本/哈希
src/services/region-catalog.json     浏览器可用的 LGA 目录
```

这些文件已随迁移完整保留。正常运行不下载边界、不解析 Raw 文件、不重新导入数据库。

### 5.2 重建同一已审查批次

[scripts/import-official-snapshot.mjs](scripts/import-official-snapshot.mjs) 只接受当前固定批次及 reader 哈希，不是任意新批次导入器。它需要项目正式运行的证据目录、`receipt.json` 与证据索引，索引中的 `runs.official.evidence_files` 至少覆盖：

- `reader-results.json`
- `manifest.json`
- `raw-qa.json`
- `source-metrics.json`
- `recovery-cost.json`

脚本逐文件验证 SHA256、发布 succeeded、receipt passed、报告/行身份、每州 60 个唯一月份、四指标月年汇总与严重程度总量。验证后写本目录 `data/official/`；不连接业务数据库。

如果明确要重建同批次文件，在 **Front_End** 下显式传入证据路径：

```bash
node scripts/import-official-snapshot.mjs \
  /absolute/path/to/official-run \
  /absolute/path/to/current-evidence.json
```

上面是路径占位符，需要替换为实际证据目录。脚本原有的默认导出路径来自旧工作区布局，迁移后请显式传参。只复制 `reader-results.json` 而缺少配套证据，不能通过此导入流程。

同批次的 LGA 扩展可按需重建：

```bash
ARSIA_RAW_DATA_DIR=../raw_datasource python3 scripts/build-region-snapshot.py
```

生成器默认路径也已调整为父项目 `raw_datasource/`，仍允许上述环境变量覆盖。它先校验四个原始文件、州级统计及边界哈希，再对账后写 `data/regions/` 和 `src/services/region-catalog.json`。本次迁移**没有执行**这两个重建命令，现有快照内容未变。

### 5.3 接入一个新的项目批次

还需开发/审查并验收，不能只替换 JSON：

1. 从项目一个已成功发布的批次导出 D05 年/月结果、D06 分类结果和能力状态；保留 manifest、QA、发布/来源证据，统一 dataset kind、批次、覆盖范围。
2. 同步提供该批次的 LGA 月度统计、匹配覆盖、目录与边界证据。若改用项目 API，需在服务端实现同样的接口契约，凭据只放服务端。
3. 显式更新 `src/services/config.ts` 的身份及日期、`catalog-contracts.ts` 的目录、`src/server/official-data.ts` 的固定哈希，以及导入脚本的批次/hash。地区聚合与 `src/server/region-data.ts` 的固定 hash 同步更新。
4. 检查写死的范围：当前 `region-data.ts` 仅枚举 2020–2024，来源类型和边界配置仅覆盖 NSW/VIC/QLD。新年份、新州需要适配，不能宣称只放入新文件就已兼容。
5. 对账四指标、月/年汇总、严重程度、地区 matched + unmatched、空值语义和批次一致性；重启本服务清除快照缓存，再验收界面。不得自动迁移业务库或改变主项目已发布状态。

只需动态接入数据时，可以保持前端 `/api/data/*` 的契约，在 Next 服务端增加项目读取适配层。当前仓库没有现成的“配置一个 backend URL 就自动接入所有接口”的能力。

## 6. 验证与边界

在本目录运行：

```bash
npm run typecheck
npm run lint
npx tsx --test tests/analytics.test.ts tests/map-viewport.test.ts tests/fixtures.test.ts tests/agent.test.ts
ARSIA_NEXT_DIST_DIR=.next-demo-build npm run build
```

现有 `tests/browser/` 保留较早页面的用例，包含旧界面假设，不应把整套 E2E 当成本展示版已经全部验收。最近实际执行的结果以 `artifacts/` 下的记录为准。

本次迁移后实际通过：类型检查、lint、生产构建、51 项相关单元测试，以及三州共 15 个 GET 接口检查。真实浏览器复核 Overview、Data、Analytics 与 Studio 占位，控制台无错误或警告。记录位于 `artifacts/relocation-20261004/`，截图位于 `output/playwright/relocation/`。

- 图表读取当前固定统计；Data 上传和 Studio 按要求没有实际功能。
- 州级严重程度仅完整五年可用；LGA 的月度严重程度由原始事件直接聚合。
- 不暴露真实事故、人员或车辆明细；当前 records 为 unsupported。
- 地图是行政区计数，不是事故点、事故风险率或严重程度等级。
- 底层 API 与 JSON 仍保留来源和 QA 信息，虽然展示弹窗已经按要求隐藏表格下方的证据区。
- 旧证据记录 QA01–QA06 pass、QA07 location limited，`independentMemberSignoff=false`、`finalPlatformAccepted=false`；迁移不是新的全项目验收。
- 运行本展示版不执行数据库导入或部署。

## 7. 迁移与维护记录

2026-10-04 从 `Ass2-temp/ARSIA` 整体迁到本目录，迁移前后核对 105 个版本文件内容一致。旧构建缓存保留在 `artifacts/relocation-20261004/previous-build/`，运行时在新目录重新生成，依赖与历史测试证据保留。

本目录是父仓库的普通子目录，没有嵌套 `.git`。原独立仓库 Git 信息、工作区补丁和迁移前文件哈希保存在：

```text
/Users/zhengpeixian/ZPX/UTS/Advanced Database/Ass2-temp/ARSIA-git-backup-20261004-130721
```

旧 README 保存在 `artifacts/relocation-20261004/README-before-relocation.md`。迁移详情及服务日志见 `artifacts/relocation-20261004/`；界面变更记录见 [展示版说明](docs/DEMO-PREVIEW-20261004.md)。只操作 Front_End 的进程与目录，不要更改已有 `frontend` 链接、主版 ARSIA 或 3100 服务。
