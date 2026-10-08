# 自主接入验证记录（进行中）

记录日期：2026-10-01，Australia/Sydney。本文记录当前工作区的第二阶段自主接入开发，
不能替代 [ACCEPTANCE.md](ACCEPTANCE.md) 中第一阶段的真实发布验收，也不能用第一阶段
的结果宣称第二阶段已经完成。没有生产部署或 GitHub 发布。

## 验证层次

| 层次 | 当前已有证据 | 本文尚未证明的内容 |
| --- | --- | --- |
| 官方来源调查 | SA、ACT、TAS 官方元数据、公开下载 URL、检索日期、内容 SHA256 和下载收据 | 官方数据没有质量问题；来源口径能够跨州直接比较 |
| 完整原始输入 | SA 完整三表 ZIP；ACT 全量 CSV；TAS 完整 ArcGIS 查询结果及所有分页收据 | 这些输入已被真实模型自主处理或发布 |
| 确定性工具验证 | 输入格式、流式读取、安全 ZIP、文档提取、公开网络安全、统计与关系工具的针对性测试 | 所有网络协议、所有损坏文件均已穷尽验证 |
| 独立人工验收基准 | 本地直接重算原始文件的行数、键、关系、声明数量、年份和严重程度 | 基准数值属于官方语义证据，或可反馈模型要求它填出这些结果 |
| 自主 Agent 与发布 | ACT 独立 v3 为 2,570 项通过；SA 后续实际发布，v3 为 1,168 通过/1 项差异，详见追加记录 | SA 尚未严格验收全过；SA/ACT 地图未准入；TAS 未实跑 |

最终端到端任务 ID、模型/tool 轨迹、adapter 代码版本、镜像 ID、全量 QA、数据库核对、
失败保持旧发布、恢复和资源结果，由执行该轮验收的主任务追加。没有这些记录的项目保持待验。

### 当前真实任务状态（只读核查）

2026-10-01 **04:17:24 UTC / 14:17:24 Australia/Sydney**，以只读、repeatable-read 数据库事务
核对任务、attempt、durable steps、版本和当前 release，记录在
[source-state-review-2026-10-01.json](../artifacts/autonomous-imports/source-state-review-2026-10-01.json)。
下表是这一时点的状态；后续 retry 不覆盖已完成或已取消 attempt 的历史事实。

| 场景 | 已实际发生 | 仍未证明 |
| --- | --- | --- |
| ACT | 真实文件、真实模型、sample/full QA、注册和发布；独立 v3 为 2,570/2,570 通过 | 地图未准入；不能声称首次运行无需操作恢复即成功 |
| SA | 官方三表上传并调查；第 1 次 attempt 由主任务取消，当前 `cancelled` | adapter/sample/full QA/注册/发布尚未发生；计划 retry 不是通过证据 |
| TAS | 全量公开输入及 392 页抓取证据、独立异常分析已完成 | 尚无该实际上传哈希对应的任务；真实模型、阻断诊断和发布隔离均未执行 |
| 控制 NameError 恢复 | 专用工具和离线测试已完成 | 尚未实际运行真实模型故障注入；没有恢复验收成功报告 |

ACT 成功不代表三个新来源全部完成；SA 的操作取消也不是数据已经通过或未通过 full QA。
**后续更新：SA 已从同一任务恢复并发布，严格验收仍有一项差异；以下取消表格保留为历史
时点记录，最新结论见 South Australia 小节的追加验收。**

## 输入与工具实现

- [intakereaders.py](arsia_pipeline/intakereaders.py)：共享的无网络、只读格式读取器；
  CSV 显式编码/分隔符，XLSX，旧 BIFF XLS，JSON/JSONL，GeoJSON 和 ArcGIS JSON。
  文件魔数和实际表头决定结构，无后缀文件也能读取。Excel 日历值转 ISO；XLSX 公式/
  错误单元格拒绝；XLS 读取原文件保存的单元格结果，不执行 Excel。
- [intake_tools.py](arsia_pipeline/intake_tools.py)：完整文件 SHA256 验证、安全 ZIP 展开、
  使用 SQLite 磁盘索引的全表统计和复合键关系检查、PDF/文本/字典/官方元数据提取。
  模型得到表头、类型、范围、受限类别统计与文档正文，不得到完整人员记录或任意主机路径。
  日期格式候选来自整列解析结果，仍须源语义和独立 QA；不把候选当批准。
- [public_sources.py](arsia_pipeline/public_sources.py)：只允许无凭证 HTTPS；所有 DNS 结果
  必须是公共地址，连接固定数值 IP 并验证原域名 TLS；每次重定向重新校验；拒绝私网、
  元数据服务、认证 URL、非标准端口、超量/截断响应。没有关闭 TLS 验证、代理凭证或访问绕过。
  官网返回 401/403 时保留失败原因，使用公开官方 API/导出是独立的正常访问途径。
- `fetch_arcgis_layer` 从官方 layer metadata 获取真实对象 ID 字段，读取完整 ID 清单，
  按明确 ID 分页，逐页核对缺失/重复/transfer limit，再重取 ID 清单和总数。
  最多四个请求同时进行；保留每页原始字节、URL、时间、哈希，生成可流式读取的派生 JSON。
  前后 ID/总数一致不等于数据库事务快照；抓取期间同 ID 的字段编辑仍是明确限制。
- `read_document` 返回原始文件与提取文本的两个哈希、真实 fetch receipt、官方 URL、
  获取时间和提取方式。支持 offset/search 查看长文档；移除 Socrata 缓存样例；
  不把 JSON 记录集合或改名的 CSV 当文档发送。模型不能凭一个 URL 自报准入成功。
  新增 `citation_spans` 给出精确 document ID、原文子串与字符范围，结构化 JSON 的
  `field_definitions` 只读取官方 raw name/alias/type/description；不创造别名或自动认可语义。
  search 默认上下文上限 4,000 字符，使用 `next_offset` 可继续读取。

新增运行依赖固定于 [requirements-intake.txt](requirements-intake.txt)。表读取器既被工具
调用，也被隔离 SDK 和主机独立 QA 使用；生成的 adapter 不能覆盖这个可信模块。

针对性测试：`test_intake_tools.py` 17 项、`test_public_sources.py` 10 项、
`test_evidence_grounding.py` 8 项，共 35 项通过；只读验收器另有 9 项、真实恢复工具另有
11 项离线测试通过。后两组最近合跑 20/20；这些测试计数与实际来源验收逐项检查数分开。
包括真实 BIFF8 夹具、UTF-16/显式 CP1252、CSV 多行和损坏宽度、XLSX 内部空行与公式、
BOM GeoJSON、ArcGIS CRS、JSON 重复键、ZIP 路径穿越/符号链接/字节改变、复合关系孤儿、
个人行不出现在 profile、改名 CSV 文档限制、SSRF、混合公共/私有 DNS、私网重定向、
响应截断、访问拒绝、ArcGIS 缺页和抓取期间 ID 变化。

发现工具另有实际公网验证：提供 `6jn4-m8rx.csv` 文件名，同时故意传入 SA 查询和 SA
起始 URL，工具仍从全国官方 catalogue 的通用数据集 ID 检索找到 ACT，沿其公开资源链接
获取 ACT 官方元数据。实现没有硬编码 ID→州映射。传入 URL 是线索，不再关闭跨目录发现；
所有结果仍要求表头和业务语义匹配。证据在 `source-downloads/discovery-review/`。

[evidence_grounding.py](arsia_pipeline/evidence_grounding.py) 提供供可信 QA 接入的纯函数，
在收据、原文哈希和精确引文已验证后，检查 dataset URL/官方资源链接/同一 dataset ID 的
连接关系，以及 key/date/severity/count/FK/geo 关键字段是否出现在该来源的官方字典。
共享 `.gov.au` 域名不构成同一数据集；跨目录检索结果不会把所有返回的数据集串成一个来源。
Socrata/ArcGIS 别名只认官方结构化关联；PDF 文本只规范大小写、空格、下划线。
显式地理映射没有 CRS 依据会阻断，须明确移除地图能力后重新执行，不能静默修改候选。
这是字段及来源绑定检查，仍不等于证明科学可比性或自动消除官方文档间的矛盾。

## 真实来源输入与独立发现

全部新资料只保存到被忽略的 `artifacts/autonomous-imports/source-downloads/`。
[source-cases.json](../artifacts/autonomous-imports/source-downloads/source-cases.json) 给出上传文件
的准确路径、原名称、SHA256、官方文档 URL 和收据位置。原始字节内容寻址保存，原课程
raw、旧 native policy、`data/official` 和网站原快照没有被本子任务写入。

### South Australia

来源：[官方 CKAN 元数据](https://data.sa.gov.au/data/api/3/action/package_show?id=road-crash-data)。
发布者 Department for Infrastructure and Transport；当前完整包是
`2020-2024_data_sa_crash_as_at_20250919.zip`，4,981,599 bytes，SHA256
`b1c22ba4444542c07f876a26aab0bc5ee1bfc4689001dabf6309c634550737de`。

包内三张 CSV 完整读取：63,239 crash、134,981 unit、23,892 casualty。
独立检查 `REPORT_ID`、`REPORT_ID + Unit No`、
`REPORT_ID + UND_UNIT_NUMBER + CASUALTY_NUMBER`，重复完整键和孤儿均为零。
crash 的 Total Units/Total Cas、unit 的 No Of Cas 与全量子表精确一致；
Total Fats + Total SI + Total MI 与 Total Cas 精确一致。
日期列完整解析为 `%d/%m/%Y %H:%M:%S`，2020-01-01 至 2024-12-31。

当前 [官方词典 PDF](https://data.sa.gov.au/data/dataset/21386a53-56a1-4edf-bd0b-61ed15f10acf/resource/02fb14f9-8dcb-4a59-863c-5f7cc3ae1832/download/metadata-for-road-crash-data-20251215.pdf)
是七页、249,787 bytes，SHA256 `cc83678628700ab4867bed6938635c7a34c8eb749ab16523917a1fcd8fbbedac`。
它明确当前 X/Y 是 EPSG:8059（GDA2020 Lambert），不能套用旧坐标假设；Unit 包括车辆、
其他道路使用者、动物和对象，不能标为“车辆数”；fatality 是因事故伤害在 30 天内死亡的人。
Fatal crashes 与 fatalities 独立重算分别为 437 与 469，不可互换。
独立地理基准有 63,230 条可转换坐标、9 条源坐标缺失；后者不能填成坐标零或虚构位置。

词典与输入版本不同的事实保留在来源证据中。准入应检查其字段定义与当前文件一致，
不能只因同一个州或类似文件名而继承旧许可。

真实任务 `8056ec76-da6c-4bfd-afc4-3b7681e426ec`、session
`c329fd64-ae74-442c-9381-1c4fc32aaeed` 的第 1 次 attempt 在 04:07:17 UTC 结束为
`cancelled`。累计 50 次模型调用、49 次 tool 调用、执行器 compute_seconds 为 0。
durable steps 记录 8 次 inspect_bundle、11 次 profile_dataset、24 次成功 read_document；
只有一次失败的 set_source_contract，没有 write_adapter、run_adapter、validate_candidate、
register_adapter 或 publish_candidate 步骤。该任务 batch/release 为 null、实际 batch 数为 0；
当前 release 仍为 ACT 已发布版本。主任务识别到调查记忆丢失造成重复读取并主动取消，随后
补充通用 context memory，准备 retry；该修改是否解决真实 SA 多表调查仍待后续 attempt 验证。

**追加发布验收：** 同一 SA 任务后续发布至 release
`317b799e-8637-4ecb-90bd-4590dc556324`，source `sa_road_crash_data`，batch
`bcbee8e4-f39a-4b38-87f1-1562d2469ed1`。只读 v2/v3 均包含固定 release 的 API query、
job/batch report 和独立 SQL；无模型调用，未修改任何 oracle：

- [v2 报告](../artifacts/autonomous-imports/sa-8056ec76-published-v2.json)：1,157 通过、1 项失败。
- [v3 报告](../artifacts/autonomous-imports/sa-8056ec76-published-v3.json)：1,168 通过、1 项失败。
- 两份报告唯一失败均为 `database.crash.facts.sha256`。63,239 条 crash 全部缺少显式
  `declared_casualties`；合同虽把 `Total Cas` 映射为 `casualties`，但未声明前者，也未设置
  `casualty_table_complete`。原 CSV 独立重算时**只**将该字段换为缺失值，即精确得到实际
  PG fact hash，证明该摘要差异定位明确。该诊断不替换 oracle、不把失败改成通过。
- 原始 `Total Cas` 与 canonical `casualties` 逐条数值差异为 0。63,239 crashes、437 fatal
  crashes、469 fatalities、23,892 casualties、134,981 units，以及 5 年/60 月、严重程度、
  各层完整键、unit/casualty 逐键事实均通过。结果已发布，但不能称严格独立验收全通过。
- 实际和声明日期均为 2020-01-01 至 2024-12-31；63,239 条日期均保留 day precision。
  网页覆盖卡显示缺省值不能归因于源日期缺失，应另查展示或查询路径。
- 地理未映射：全部 63,239 条 unsupported、coordinates null，v3 明确 `not_verified`。
  官方 PDF 已提供 EPSG:8059；模型合同中“未建立 CRS”的说明与已有官方证据不符。这是
  已知遗漏能力，不能反称官方没有坐标依据，也不能用其他指标通过证明地图通过。

独立定位记录：
[sa-8056ec76-fact-difference-diagnostic.json](../artifacts/autonomous-imports/sa-8056ec76-fact-difference-diagnostic.json)。
查询性能问题与数值差异分别记录：以上完整报告已取得 API 数值结果，唯一严格差异如上，
没有将查询超时认定为人数不一致。

### Australian Capital Territory

来源：[官方 Socrata 元数据](https://www.data.act.gov.au/api/views/6jn4-m8rx.json)。
完整 CSV 17,724,947 bytes，SHA256
`2262c4622efd7c1b572ed0599c3f90e06833e027cabc8c1e031366222b586922`。
实际 76,657 行与官方 count API 一致；crash_id 全部非空且唯一。

官方字段说明把 `x` 标为 longitude、`y` 标为 latitude，位置仅指示 intersection/midblock。
不能由列名推断精确定位资格，也不能将事故严重程度转成人数；本文件没有死亡人数、
伤亡人数或单位表，相关指标应保持 unavailable/null。Fatal 类事故 105 条不代表 105 人死亡。

官方元数据内部存在时间范围差异：描述文字称 2015–2025，custom_fields 则称
“2012 until current” 和 “Updated every weeknight”；实际日期覆盖 2015-01-01 至 2026-09-07。
应保留并解释当前覆盖证据，不能静默截掉 2026 数据或用摘要覆盖更宽历史。

### Tasmania

来源：[官方图层元数据](https://data.stategrowth.tas.gov.au/ags/rest/services/PUBLIC/CDM_CRASH/FeatureServer/0?f=pjson)、
[官方旧 catalogue](https://data.gov.au/data/api/3/action/package_show?id=8f7d9792-dde8-4d88-966a-1874c775640f)、
[2025 TheList catalogue](https://data.gov.au/data/api/3/action/package_show?id=a58b3f76-bbef-4ad5-b064-c498a2038828)。
派生完整 JSON 71,150,990 bytes，SHA256
`698c904340a8fbb0fafc5b447f62a5fe26adb07795f6cc67f46eab8e7cb1fc57`。
392 个页面完整核验，176,163 条，抓取前后 ID 清单和 count 一致。

`ID` 是官方 esriFieldTypeOID 且本次全部唯一；`VCRN` 有 84,352 个空值，不能猜为主键。
几何 CRS 是 EPSG:3857；日期官方 `timeZoneIANA` 为 `Etc/GMT-10`，固定 UTC+10，
`respectsDaylightSaving=false`，不能替换成 Australia/Hobart 夏令时。
没有可支持死亡人数、伤亡人数或单位数的字段，不能从 Fatal 严重程度推算人数。

这里存在真实的阻断案例：layer/iteminfo 写“2009 年起”，但全量数据含更早记录；
2025 官方 catalogue 可为 1998-02-01 起的覆盖提供依据，却仍无法解释一条日期
`0002-02-14T11:49:00+10:00`。原始字节保留，不把 0002 猜成 2002，不删除异常后声称全量成功。
若后续采取范围分区或排除，需要可追溯的明确依据和支持该选择的准入规则；证据不足不发布。
另有两条 1998 年 1 月记录早于上述 catalogue 的 1998-02-01 下限；v3 基准保留这三项异常。
严重程度的 8,360 条 `Not known` 保持未知 fatal 标志，不能计入“已确认非致命事故”。
所以已知 Fatal 类为 933 条，但对全量的完整 fatal crash 指标仍为 null。

## 独立基准与待验清单

每州目录的 `independent-oracle.json` 是只用于验收的独立统计，不能作为源文档交给 Agent，
也不能用它代替全量 QA。SA 的 `crash-profile.json` 和各州 `bundle.json` 是实际工具输出。
`data-receipt.json` 记录输入；`public-evidence/` 保存成功/失败请求和内容寻址字节；
字典提取正文与 SHA256 收据保留在 `intake-tools/documents/`。

### 可复现的只读发布验收

[verify_autonomous_sources.py](tools/verify_autonomous_sources.py) 只发 GET 请求，在隔离数据库
开启 `REPEATABLE READ READ ONLY` 事务；不会提交任务、调用模型、修复输入、注册或发布。
默认使用已有私有 Unix socket，`--via-website` 可改由现有 3100 代理读取。

```sh
pipeline/.venv/bin/python pipeline/tools/verify_autonomous_sources.py \
  --state act --job-id <已完成任务 UUID> \
  --output artifacts/autonomous-imports/act-acceptance.json

pipeline/.venv/bin/python pipeline/tools/verify_autonomous_sources.py \
  --state tas --job-id <阻断任务 UUID> \
  --before-release-id <任务开始前的 release UUID> \
  --output artifacts/autonomous-imports/tas-isolation.json
```

ACT/SA 默认要求 `published`，TAS 默认要求 `blocked`；`--expect blocked` 可单独验收其他州
失败任务的隔离。`--before-release-id` 可省略，此时取任务首次 attempt 前的最新不可变 release。
隔离验收应在其他任务发布前运行；若此后已有合法新发布，当前 release 已变的检查会失败，
不能把一次稍后的数据库快照当作当时未变化的证据。退出码 0 为全部检查通过，1 为失败或错误。

每州新增 `independent-oracle-v2.json`，由同目录的
`build_independent_oracles.py` 从原始官方文件独立构建；v1 保留。构建器核对输入完整 SHA256、
用独立 CSV/JSON 和日期处理重算各年、各月、严重程度、各层完整键与关系、逐记录语义摘要，
没有调用生成 adapter、生产投影或可信 QA。仅复用无业务含义的 SHA256 多重集合编码器。
oracle 保存构建脚本 SHA256、输入 SHA256 和异常，不给 Agent 作为工具输入或目标答案。

现默认使用追加的 `independent-oracle-v3.json`；原 v1/v2 内容保持不变。独立构建脚本
`build_independent_oracles_v3.py` 追加 fatal true/false/unknown 按原严重程度的分布、实际日期
上下界与 `independent-geo-records-v3.jsonl`。SA 使用独立指定的 EPSG:8059→4326 转换，
ACT 读取官方 longitude/latitude 字段，TAS 使用独立 Web Mercator 逆算公式。实际数据库
记录按完整键在临时 SQLite 索引中逐条比较；坐标转换仅允许 1e-7 度绝对误差（约厘米量级，
用于不同投影库版本的小数差异），所有人数、分类数和键仍整数精确。未映射的可选 geo 必须
全为 unsupported/null，报告明确 `not_verified`，不阻断已通过的事故指标。

已发布模式分别比较 job result、immutable batch result、固定 release 的 `/query` 与直接 SQL
流式重算，逐月逐指标整数精确相等；`null`、0、浮点数和布尔值不混用。数据库检查原始严重
程度、完整复合键、逐键日期/人数/父子关系的摘要、重复与孤儿、unsupported/available 标志。
这能发现“总数相同但记录被重分配”的错误。查询严重程度 code 可用已声明映射，其原始类别
另外对数据库验收。报告只含聚合和哈希，不输出人员行。

阻断模式证明任务没有 batch/release/result、没有成功注册/发布步骤、候选合同没有新 registry
版本，而且旧 release 及各来源 batch 指针一致。这仅证明失败隔离；不会把模型服务 503 或
证据不足改称数据语义已经验证，也不会把 oracle 的 TAS 异常复制成“实际 QA 已发现”。

本验收器 9 项测试通过。曾对 ACT 任务 `f4ebf169-b6b1-4a60-8a0d-3fb7c2b49485`
执行真实只读隔离检查，13/13 通过；候选未注册、未发布，旧 release
`81aa9593-1e85-42ee-85b3-464b52d76f48` 未变。
报告：`artifacts/autonomous-imports/act-f4ebf169-isolation.json`。
该份历史报告检查的是当时的 `needs_input`；同一任务随后恢复并已实际发布至不可变 release
`6c550eaf-1ff1-46db-b1e2-0d2ef4e16499`，source `act_open_data_6jn4_m8rx`。
追加的 `act-f4ebf169-published-v2.json` 为 2,559/2,559 通过，
`act-f4ebf169-published-v3.json` 为 **2,570/2,570 通过、零失败**。
实际与声明日期均为 2015-01-01 至 2026-09-07；76,657 crashes、105 fatal crashes，
fatalities/casualties 为 null。全部 76,657 行的 geography 为 unsupported、coordinates 为 null，
地图验收状态明确为 `not_verified`。这证明 ACT 当前事故指标的实际发布精确一致；SA 的
后续严格差异见前文，TAS 的实际任务验收仍待执行。

ACT 不是一次无中断的首次成功：四个 attempt 的状态依次为 `needs_input`、`needs_input`、
`needs_input`、`succeeded`；前两次因模型服务不可用，第三次达到累计 model_calls 预算。
最终 session 保留累计 **86 次模型调用（76 次有成功 response 收据、10 次失败）、76 次工具
调用、correction_count=9**，没有重置历史计数。任务 options 中没有人工 profile 或 answers。
主任务曾操作恢复、修复通用上下文/工具流程并暂时提升调用预算；这些操作不等于人工提交
映射，也不能被省略后包装成“上传一次即全程无人干预”。这次总耗时不作为稳定性能基准。

已发布 batch 为 `56b07a3d-96c6-42d4-8faa-a25991edb578`，adapter 代码 SHA256 为
`71032c24771b9eebf86c9559c04c737f0cbca32d165bbe6ec6ec283dcec0216b`，执行器 image 为
`sha256:3899ab367b0c22f8b8c4b11d26e9c30afe519ec0b1e81037d553a5b3921a6c34`，full admission
policy 为 `canonical-v2-auto-admission-2`。完整 adapter/source version IDs、合同 hash、模型
policy/SDK hash 和可信实现 hash 均在上述只读状态记录。核查时四个可信文件
canonical/trusted_qa/intakereaders/evidence_grounding 的当前 hash 仍与 ACT 准入记录一致。

网站端另有已保存的实际 provider / Ask AI / Studio / 导出 ZIP 验证，
[verification.json](../artifacts/analysis-verification/local-act_open_data_6jn4_m8rx/verification.json)
和 [export-verification.json](../artifacts/analysis-verification/local-act_open_data_6jn4_m8rx/export-verification.json)
均为 passed，固定同一 release；12 年度点、141 月度点与独立 oracle 精确一致后才发起这些
模型分析调用。它们证明 ACT 已发布数据的下游读取，不是新的自主导入或地理准入证据。

### 真实模型失败修复验收工具（已实现，尚未运行）

[verify_real_model_recovery.py](tools/verify_real_model_recovery.py) 是独立、明确 opt-in 的
测试驱动器。**目前只有 11 项离线工具测试通过，没有执行本工具的真实模型验收。**
这些离线测试证明注入和断言逻辑，不作为真实模型自行修复的证据。

```sh
pipeline/.venv/bin/python pipeline/tools/verify_real_model_recovery.py \
  --confirm-real-model-recovery \
  --source-job-id <已完整准入并发布的真实新来源任务 UUID> \
  --output artifacts/autonomous-imports/real-recovery-acceptance.json
```

仅在既有本地队列空闲时允许执行。工具只读取得已准入实际来源的原始上传描述，重新核对字节
SHA256，然后创建全新 `arsia_imports_test_recovery_<随机值>` 数据库和唯一 instance marker。
在本进程的 TestClient 中重新上传这些字节，不向正在运行的 API 提交任务，也不提供 mapping、
已验证 adapter、原合同、独立 oracle 或提示答案。模型经现有真实 gateway 自主重新调查来源，
调用真实文档工具、Docker executor、sample/full QA 与 registry。

专用 AgentSession 子类只在首次写入 adapter 时通过 AST 插入一个唯一未定义名称；保存模型
原始代码、故意损坏的版本和注入收据。生成代码从不在主机执行。未修改共享 worker、gateway
或执行器，无进程终止、无新端口。故意注入的错误被明确标为 controlled fault，不能描述成
“模型自然生成了一次错误”。若模型在运行前覆盖了注入版本，工具也不会假定已测试恢复。

验收必须观察到以下有序事实：实际 model response 收据；注入版本 sample 在真实容器内
发生 NameError；模型在收到失败后检查 adapter/运行诊断，或实际下一次模型输入中已有
该失败的完整结构化结果；不同代码版本 sample 成功；
该版本独立 sample QA 后执行 full，并通过独立 full QA；之后才注册和请求发布。仅最终成功
不足以证明恢复。验收先核对这些顺序，再真正发布到本次 TEST 数据库，核对数据库发布证据。

完整 durable steps/checkpoint、实际 model input 哈希及诊断消费路径、代码版本、执行收据
索引和资源使用保存到新 evidence 目录。直接根据已收到的真实 NameError 修复是有效路径，
不会只因缺少一次冗余 inspect_run 调用而失败。
原始上传、测试上传、既有 runtime 文件、现有本地 DB 的 release/各表计数都做前后核对。
测试 registry 的不可变代码文件及私有 attempt 文件保留作为证据；现有数据库不登记这些版本。
完成或失败后，只有本次新建且 instance marker 再次匹配的 TEST 数据库会被删除；无法证明
初始化成功的数据库保留供核查。新证据不会覆盖已有报告。并发合法发布也会使“原 DB 未变”
检查失败，因此执行时必须保持既有队列空闲。

模型 503、文档不可用、语义未解决或预算耗尽会保留 blocked/failed 结果，不能宣称恢复成功。
此工具不包含取消/worker 丢失注入；此前数据库/worker 故障回归与本次真实模型修复证据分开。

### 仍需补齐的硬证据

1. **SA 已发布结果的剩余差异**：补足来源已声明的 crash→casualty 数量对账映射/语义并
   重新完整准入、发布、独立核对；当前 oracle 的显式 `declared_casualties` 不能由验收工具
   默默删去。官方 EPSG:8059 依据已存在，地理能力仍未完成准入和真实转换验收。当前数值
   报表精确通过，不代表这两项缺口已解决。
2. **TAS 的真实阻断隔离**：提交原样全量文件，保留 year 0002 和早期覆盖异常；记录模型/QA
   实际诊断、候选未注册未发布、原 release 未变。独立 oracle 发现异常不等于 Agent 已发现。
   若采用分区，须另有明确合法范围证据与新一次完整验收，不得修原字节或把丢弃行称为成功。
3. **真实模型受控代码恢复**：在空闲时实际执行上述 opt-in 工具，保存失败 sample、实际
   模型诊断消费、新代码 hash、sample/full QA 与 TEST DB 发布。当前 11 项离线 harness 测试
   和 ACT 的服务重试/语义修正都不能替代此实验。
4. **实际来源的版本与更新路径**：同一真实输入重放/no_change、变化输入、source identity、
   分区/增量保留旧历史需真实来源证据。数据库合成测试能覆盖机制，不能宣称所有真实州的
   业务口径都已经验收。
5. **最终版本的整体验证**：本轮结束后固定代码、镜像与模型 policy hash，追加最新的全部
   Python/网站回归、受保护原文件 hash、取消/恢复和资源采样。第一阶段 836 项 native
   比对仍有价值，但不能替代新增 Agent 代码当前版本的完整闭环。
6. **部署与容量**：Linux 实测、并发/资源预算、最小权限、备份恢复、保留清理和生产发布
   仍未实施；本机 Docker 成功或已准备 Compose 文件均不是服务器就绪证据。

[pipeline README](README.md) 已把自主实现与历史 [ACCEPTANCE.md](ACCEPTANCE.md) 分开，
旧报告中的“不解析 PDF/不执行生成 Python”应作为当时边界阅读。最终对外说明应继续使用
上述按来源、按场景的实际状态，不用实现存在或某一次成功推导所有来源与恢复路径已通过。
