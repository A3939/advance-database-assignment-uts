# 官方道路事故知识库与 Adapter 复用交接（历史研究记录）

> **时点说明：** 本文保存2026-10-01–02的研究与当时验收，不是当前实现状态。下文“当前”“本轮”“未做”均指该历史阶段；ACT RDF grounding、完整文件绑定、表示兼容、真实主链与模型实验已在后续隔离开发中推进。最新F/K处置、来源能力矩阵和限制以[整体优化交接](INTEGRATED-OPTIMIZATION-20261003.md)为准；旧失败证据仍保留，不能将它们改写为成功。

调研：2026-10-01 至 2026-10-02，Australia/Sydney。范围为当前可公开发现、合法取得的官方资料，不声称穷尽历史版本。此交付是代码、冻结研究证据和本地隔离验收；没有启用运行中服务的配置，没有提交、推送或线上部署。

## 交付入口

- `pipeline/arsia_pipeline/knowledge/catalog.json`：13 个来源条目、63 个资源条目，覆盖八州/领地及全国；35 个证据索引条目包含成功、失败与复用的历史收据。
- `pipeline/arsia_pipeline/knowledge/evidence/`：按 SHA-256 存储官方元数据、字典、有限 API 样本及 ACT 既有 RDF 样本；重复内容只保留一份。失败响应不伪装成已获取数据。
- `source_knowledge.py`：目录查询、定点证据读取、保守 schema 候选识别、字段碰撞检测、provider 元数据投影和有界 JSON Pointer 差异；可对照新任务已登记的官方元数据收据。
- `adapter_reuse.py`：按数据库实例隔离的准入 recipe 缓存；命中后编译 SDK 声明式投影，重新执行 sample/full、可信 QA、registry 和 publication gate。
- `knowledge_cli.py`：不联网、不调用模型、不连接业务 DB 的目录、证据、差异、识别及 native 回放入口。
- `pipeline/tests/test_source_knowledge.py`：新功能的正反例。
- `pipeline/tools/verify_knowledge_isolated.py`：真实 SA 全量、Docker executor、独立 PostgreSQL、重复导入和失败准入验证。
- `pipeline/tools/verify_act_knowledge.py`：独立 CSV/RDF 检查；不产生 ACT 准入。
- `artifacts/official-knowledge-20261001/`：基线、网络收据、原始测试日志、失败实验、隔离数据库与本轮报告。目录沿用任务开始日期。

## 项目调查与实施位置

先读取了根 AGENTS、README、pipeline README、通用兼容性任务书、ACT 诊断、processing/native、registry/source_identity、trusted_qa、AgentSession、Codex runtime/bridge、隔离 executor 和 publication 路径。原有未提交文件较多，因此保存了文件哈希和 Git 状态基线；仅对 `agent.py`、`codex_bridge.py`、`pyproject.toml` 作小范围集成，其余实现为新增文件。

未修改 trusted_qa、canonical、readers、geography_review、source_identity、publication、原有 profiles 或数据库 schema；这些门禁仍按原规则工作。运行中两组 API/worker 和 3100 前端没有重启，也没有恢复、重试、取消原有导入。

数据接入代码的职责：

```text
上传 → 既有 native pinned/revision 边界
     → 新 AgentSession（配置 knowledge_root 时启用复用预检）
     → inspect_bundle / 原始字节哈希
     ├─ 已注册 recipe + 同一完整资源集合 + 相同依赖/证据/镜像
     │    → 确定性编译 → sample 执行和 QA → full 执行和 QA
     │    → 原 registry → 原事务发布（或 no_change）
     └─ 不命中、变化或歧义
          → compact schema 差异 + 知识目录引用
          → 原 Codex 自主调查 → 原独立 QA
          → 注册成功后沉淀 recipe
```

研究目录与 adapter 准入是两个不同层次。目录里的 `adapter_status` 是研究状态说明，不是可执行授权。只有真实 registry 的 full admission、当前文件哈希、依赖和新 QA 能授权实际处理。模型没有“批准知识条目”的工具。

## 官方来源清单与关键结论

每个资源的官方 ID、URL、格式、版本时间、grain、parser 未知项、字段字典及定位见 JSON。以下是需要人理解的边界，不能据此把不同来源相加。

| 范围 | 取得的来源与粒度 | 版本、字段和限制 |
|---|---|---|
| NSW | Transport for NSW CKAN：事故 XLSX、Traffic Unit XLSX、27 页手册；历史滚动版本 | Crash ID 与 Crash ID + Traffic unit ID；交通参与单位包括行人。当前目录为 2020–2024；旧版 overlap 被新版修订替代。部分目录标为 XLS，URL 实为 XLSX；2019–2023 TU 名称与描述年份冲突。未确认公开人员明细；经纬度 datum 不由数值范围推断。 |
| VIC | Transport Victoria 新 CKAN：Accident、Vehicle、Person、Node、Accident Location、事件/环境表、lite 事故平表、DCA 文档；5 行 API 样本 | 2012 起，月更新、约七个月滞后；不同资源更新时间/结束期不同。新 portal UUID 与旧目录不同，旧 API 404。CSV 和字典展示字段名并不总相同。lite 与多表事故覆盖重叠，不能一起算；项目 frozen VIC 限制不因新 portal 公开而消失。 |
| QLD | TMR CKAN：事故点 CSV、Road casualties、驾驶人/约束装置/车型/因素主题表；事故与 casualty 各 5 行 API 样本 | 当前坐标字段字典明确 GDA2020；曾用 GDA94。Crash_Ref_Number 被去标识，官方明确可能不跨发布稳定。Road casualties 每行是维度组合及 Casualty_Count，不是一个人。PDO 只到 2010；当前下载口径结束于 2025-06-30，其他 reportable cutoff 不同。 |
| SA | DIT CKAN：滚动和年度 ZIP、7 页字典；复用已有官方 2020–2024 ZIP，检查三张 CSV | REPORT_ID；unit 加 Unit No；casualty 加 UND_UNIT_NUMBER、CASUALTY_NUMBER。字典 p2 绑定 ACCLOC_X/Y 到 EPSG:8059，GDA2020、米。PDO 门槛在多个年份变化。日期/计数/关系继续由原 QA 验证。 |
| WA | DataWA 官方目录委托 ArcGIS Hub；另取得 Main Roads CrashMap layer metadata 和 5 条 query | DataWA 明确 2024 暂时撤下，覆盖 2019–2023。原 OpenData MapServer/2 返回 service not started，不能把 HTTP 200 当成功。另一个 CrashMap/0 的 geometry WKID 为 4283、severity renderer 有 1–5 标签；它不是对所有 WA 文件的 CRS 授权。该精确层许可和完整覆盖仍需核验。 |
| TAS | 两条官方 CKAN 记录及 PUBLIC/CDM_CRASH FeatureServer/0、item 元数据和 5 条 query；另有年度报告入口 | 事故层标题自 2009-01-01；geometry 102100/latestWkid 3857。日期服务声明固定 Etc/GMT-10、不随 DST。两个目录 licence 信息不同，保留各自范围。报告页本机请求 403，Web 读取可见 2009–2025 年 PDF/DOC(X) 入口及申请联系；未解析所有报告表。 |
| ACT | Socrata 6jn4-m8rx 元数据、用户 CSV、既有官方 100 行 RDF、W3C Geo vocabulary | 一行事故，CRASH_ID；CSV LONGITUDE/LATITUDE 对应 API x/y。描述 2015–2025、custom coverage 2012–current、实测 CSV 到 2026，分别记录。只能代表 AFP 表单报告；位置是示意点。原 QA 尚不接受 RDF 词汇证据链，继续标记 CRS_UNGROUNDED。 |
| NT | 官方 road-safety/statistics 入口；NT open-data 对 crash、road safety 两次检索 | 两次目录检索均零结果，不是“NT 没有数据”的证明。直接统计页请求 403/超时；官方搜索结果可见 road toll、年度伤亡报告和联系机构。本轮没有验证公开微观事故/人员 CSV/API，也没有绕过限制或代发申请。 |
| 全国 ARDD | 旧 data.gov.au、现 infrastructure CKAN、National Road Safety Data Hub；2025-12 字典 v1.3 与停更通知 | 旧目录停留 2023-10；新 CKAN 当次列 2026-06，Data Hub 列 2026-08。自 2025-05 不再发布独立 fatal-crash CSV。主表每行一个死亡者，Crash ID 不是死亡者主键；-9 是未知。月度更新，重型车辆标志另有季度周期。 |
| 全国相关 | 官方 catalogue 中的 National Crash Dashboard、Road Trauma Australia、hospitalised injury、severe injury/trauma registry | 作为独立相关统计产品保留。医院 episode、人员、事故与死亡不能混用；未验证 dashboard 的全部底层数据或受限微观资料。 |

主要入口：

- [全国官方目录](https://www.officeofroadsafety.gov.au/data-hub/data-catalogue)
- [NSW Crash Data](https://opendata.transport.nsw.gov.au/dataset/nsw-crash-data)
- [Victoria road crash data](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data)
- [Queensland crash data](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads)
- [SA Road Crash Data](https://data.sa.gov.au/data/dataset/road-crash-data)
- [WA catalogue](https://catalogue.data.wa.gov.au/dataset/mrwa-crash-information-last-5-years-)
- [TAS public layer](https://data.stategrowth.tas.gov.au/ags/rest/services/PUBLIC/CDM_CRASH/FeatureServer/0)
- [ACT metadata](https://www.data.act.gov.au/api/views/6jn4-m8rx.json)
- [NT statistics](https://roadsafety.nt.gov.au/research-and-statistics)
- [Current national monthly data](https://datahub.roadsafety.gov.au/reporting/monthly-road-deaths)

## 证据、标准与版本

保存的不是一组无来源结论。CKAN 资源用 `/result/resources/N` 定位，API 字段用 `/result/fields/N`，Socrata 用 `/columns`，PDF 用 `page:N`；每份成功响应保留原 URL、最终 URL、取得时间、原始字节 SHA-256、大小及可得的 ETag/Last-Modified。字段、geometry 和 provider 各有作用范围。

ACT 的 `standards_links` 把本数据集 Location、实际出现的 WGS84 namespace `lat/long`、CSV/API 字段绑定、RDF 100 行样本 hash 和 W3C 文档关联起来。W3C 文档仅定义词汇，不能独立证明任意 CSV 采用它。该记录不是对当前 QA 增加外部域名白名单；外部授权/冲突/完整证据链解析仍属于通用兼容性文档后续阶段。

QLD 的 GDA2020 声明不能改写旧文件；WA 的地图层 CRS 不能赋给另一个未取得的层。ARDD 官方 CKAN 指定 Azure Blob URL，是特定资源的委托关系，不表示该域全部内容都可信。新版 ARDD 资源 URL 已保存，但未下载完整 workbook，因此 sheet 布局、编码与行数不冒充已检查。

语义 diff 不排序数组：复合 key 次序、坐标轴次序、优先级仍有意义。CKAN resources 用资源 ID 索引，忽略明确列出的浏览计数/元数据时间等外观项，保留描述、URL、资源修改时间与其他未知新增属性。差异超出 80 项或单值过长时给出 hash 和 `truncated`/`omitted`，不能把裁剪结果当成没有变化。

## 复用的保证与边界

当前自动复用要求完整资源内容哈希相同；支持重新上传 ID、文件名变化，以及 ZIP 外层文件名变化后的成员重新绑定。使用声明式 SDK 程序重新生成输出，不在宿主执行历史 Python。原始代码与合同仍由 registry 复核；新生成的程序也必须获得新的 QA。

新的数据行、列增加/删除、列重排、不同编码、不同 ZIP 成员布局等，最多触发候选或差异调查；**当前没有承诺这些变化都能自动零模型通过**。字段同名不能证明语义相同，也不能证明上传来自官方。多个匹配合同不自动选“最新”，相同 hash 的重复上传或不完整多表包不自动绑定。

缓存按 instance_id 隔离，绑定可信 QA policy、trusted implementation、SDK、身份/update/registry/reuse 代码以及实际 executor image ID。证据 hash、registry 合同或任何依赖改变都会拒绝该旧 recipe 的直接复用。即使数据相同，新增或更换上传的 PDF 字典也会退出直接复用。每次命中仍做 sample/full QA；缓存不缓存“新文件已通过”的结论，也不赋予 snapshot 删除权。

未做：跨机器可移植的 registry 导出/导入、跨 DB 自动共享准入、远程更新监控、批量爬取历史文件、向量库、自动调度、发布 UI 改造、通用 RDF/GeoJSON grounding 修复或任意新格式支持。

## 使用与维护

在 `ARSIA/pipeline` 下，用已有 `.venv/bin/python`：

```sh
.venv/bin/python -m arsia_pipeline.knowledge_cli catalog
.venv/bin/python -m arsia_pipeline.knowledge_cli catalog --dataset-id qld-crash-data
.venv/bin/python -m arsia_pipeline.knowledge_cli evidence sa-dictionary --locator page:2
.venv/bin/python -m arsia_pipeline.knowledge_cli inspect /absolute/path/to/upload.csv
.venv/bin/python -m arsia_pipeline.knowledge_cli diff ckan /absolute/path/old.json /absolute/path/new.json
.venv/bin/python -m pytest -q tests/test_source_knowledge.py -p no:cacheprovider
```

`replay-native --output <不存在的新目录> <完整源文件...>` 只在该目录生成 SQLite/index/输出，不发布。相同 byte 的 native 文件仍要通过既有 frozen profile 的完整检查。

自动 recipe 集成默认关闭。未来仅在独立新测试 runtime 配置添加 `knowledge_root` 指向该实例的私有目录；它不是上传 options，也不是模型参数。没有该配置时，原 Agent 主流程保持不变，但新代码加载后可使用研究查询工具。不要为此重启存在活跃任务的服务；本次没有启用主 runtime。

Codex 的工具桥可调用 `read_source_knowledge`、`read_source_evidence` 和 `compare_source_metadata`。最后一个工具只接收冻结 evidence ID 与新任务已登记的 document ID，不接受模型指定的宿主文件路径。它先复核原始收据及 bytes hash，再返回变化的 JSON Pointer、旧/新片段及相关 evidence ID；数据集 ID 改变时标记 `source_identity_review`。数据未变不表示新上传通过 QA。

有预检结果时，桥会把 compact 信息写入 `evidence/source-knowledge.json`；完整上下文不主动塞入每轮请求。未知源继续使用原调查工具，成功 full QA + register 后由宿主沉淀 recipe。历史暂停任务没有被迁移。当前没有用真实模型试验证明它每次都会遵循差异优先流程；确定性工具和 bridge 路由已验证。

重新构建冻结目录的脚本只读取给定研究收据，不联网：

```sh
PYTHONPATH=pipeline pipeline/.venv/bin/python pipeline/tools/build_source_catalog.py \
  --research artifacts/official-knowledge-20261001 \
  --output /absolute/path/to/new-reviewed-catalog
```

采用新目录前应检查来源/资源 ID、许可与覆盖、schema/字段语义差异、claim 所依赖的证据，并保存旧版本。新增来源不能直接把 `research_only` 改成可执行准入；先经过现有独立 QA 和 registry。

## 验收记录与未完成项

实际日志和结构化结果在 `artifacts/official-knowledge-20261001/`。交接时以 `VERIFICATION.json` 为最终索引，不把历史项目测试数字当成本轮通过数量。最终相关回归测试为 **190 passed**，日志为 `release-regression-tests.txt`；其中知识库专项含参数化反例，覆盖并发对象写入、输入/证据/依赖变化、新字典、同名字段、registry 权威与 QA 阻断。

- ACT：本轮独立重新读取用户原 CSV，核对 76,657 唯一事故、105 Fatal、6,576 Injury、69,976 PDO、日期/时间及全表坐标表示一致性；100 行 RDF 关联重新通过。仍不具备当前 QA 的 CRS proof admission；没有发布 ACT。
- NSW/VIC/QLD：本轮完整 native 回放，分别得到 92,082 / 72,170 / 66,624 个分析范围事故。保留原排除口径与 VIC 限制，没有改 frozen policy。
- SA：独立 PostgreSQL 容器与数据库，sample/full 执行、可信 QA、注册、事务发布，再把同一 ZIP 改名重新上传，走 `agent_process` 的自动零模型路径，获得 `no_change`。对源 CSV 独立计算 crash/unit/casualty/fatal counts；本轮不声称已重新运行过去 1,165 项全字段 oracle。
- 模型：确定性实验中明确封锁模型调用入口；记录为 0 次。未执行新的真实 Codex 推理实验，不提供 token 节省百分比或冷启动成功率。
- 第一次 SA 实验因测试工作目录缺少 `agent/` 被执行器归属检查拒绝，完整保留；后续实验修正测试入口，没有修改门禁。

复跑 SA 验收时，在项目根目录执行，`--output` 必须指向不存在的新目录：

```sh
PYTHONPATH=pipeline pipeline/.venv/bin/python pipeline/tools/verify_knowledge_isolated.py \
  --research artifacts/official-knowledge-20261001 \
  --output /absolute/path/to/new-sa-isolated-test
```

该验收依赖本机已有的 PostgreSQL image、ARSIA executor image、已保存的 SA ZIP 和历史合同模板（脚本中列出路径）；不是可移植的空机器安装脚本。它新建专属容器、数据库和 volume，完成后仅停止其自有容器并保留证据。当前全部五个本轮测试容器均已停止。研究证据对象共约 3.13 MB；多轮全量验收输出保留约 8.8 GB，未删除先前结果。

仍需工作的优先次序：通用 RDF/外部标准证据链 grounding（ACT）；变化后有可信来源绑定的 schema/语义兼容证明；ARDD casualty-only 与聚合计划；VIC 事件/lookup 多表；TAS/WA 精确层的定义/许可/覆盖验证；NT 正式数据取得渠道。以上不冒充已完成。

本地报告、代码与测试可复查；不意味着所有澳大利亚数据集都已有可发布 adapter，也不意味着本轮已完成通用兼容性任务书的全部 A–E 阶段。
