# ARSIA 整体优化：实现与验收记录

执行日期：2026-10-03–04。**维护状态更新：经用户授权，160 个审查文件及两个浏览器发现的界面修复已集成；默认 Turbopack 构建、173 项 Node 测试和 lint 通过。主机重启后的服务恢复、业务保护复核、真实 TAS 与合成受限场景的隔离浏览器验收已完成。原始 ACT 官方准入仍被最终规则阻断，真实官方跨版本发布未执行。最新事实与回退入口见 [本地维护交接](MAINTENANCE-INTEGRATION-20261004.md)。**

下文保留隔离开发阶段的逐项证据和时点记录，其中“未集成”“3100 未替换”“主库未连接”等描述只代表维护授权前，不应作为当前状态。不得将历史 ACT 旧规则结果作为原文件通过最终规则的证明。

## 保护边界与源码

独立工作源码：`Workspace/ARSIA-Integration-20261003/source`。尚未集成至运行中的 `Workspace/ARSIA`。基线与测试证据位于相邻 `evidence`。

已记录 458 个源码文件的内容身份、Git HEAD 与工作区修改，以及主 runtime 和 ACT 原文件哈希。原业务数据库只读连接失败（OperationalError）；没有尝试修复或写入，不能用文件哈希宣称主库内容已核验。3100 与原 API 进程仍属于原工作区，未重启。所有本轮 PostgreSQL 测试使用 TestSession 专属数据根、容器、冷启动 runtime；结束只停止本轮容器并 keep-full 保留证据。

模型设置保持当前 expanded-v1：gpt-6.1-sol/high，120 model calls、200 tools、40 corrections、7200s wall、2400s compute；没有提高预算。本轮仅 autonomous-act-03 实际调用数据模型 22 次；此前两次在模型调用前因验收环境失败，保留证据。Web 当前 Terra/Sol 路由保持不变。

## 隔离开发阶段质量状态（维护增量见顶部交接链接）

| 层级 | 当前证据 | 结果与边界 |
|---|---|---|
| Python普通入口 | pure-all-05.log；末次查询增量见下行 | 1482 passed / 46 skipped / 1依赖弃用提示；不含专用DB，末次只读身份变更另作定点验收 |
| Node普通入口 | web-all-08.log | 173 passed；临时SQLite/网络替身，不调用真实模型 |
| 隔离DB | publication-db-07、08，codex-boundary-db-02；research-publication-db-02、query-authority-db-02/03 | 15统一发布、80autonomous backend、37backend、17Codex边界；末次15统一发布及9身份/查询+1地理+1单位查询通过，不重复累加 |
| 兼容DB | optional-columns-db-02、limited-preprocess-retained-db-03、retained-db-03 | 包装/字段版本、受限地图、去重逐行分配、辅助原值保留通过 |
| 真容器 | analysis-container-final-01；analysis-lifecycle-01 | 6项分析容器通过；父进程死亡独立35s墙钟/清理失败恢复另验 |
| 类型/静态/生产构建 | typecheck-21、lint-03、build-05 | 通过；构建使用Webpack。默认Turbopack受快照依赖符号链接限制，未通过 |
| Python包 | wheel-final-03 / wheel-import-03 | 新venv、源码外、隔离解释器导入/时区哈希/许可文件通过 |
| 官方输入 | real-source-index-04.json | ACT/SA/TAS主链及真实TAS派生表示通过；不含浏览器 |
| 自主调查 | autonomous-act-03 | raw-only新任务，22次真实模型、独立oracle通过；开发者已知ACT，非盲测 |
| 固定native | real-native-qld-02 | 415407原行，2020–24入域66624；完整键/日期/类别/计数独立核对，改名no_change，0模型 |
| SQL恢复 | cold-sql-restore-02 | 抽样1份历史TAS备份，632 payload、引用完整性通过，容器停止卷保留 |
| 浏览器/运行中集成 | not_run | 原3100和API仍加载原工作区；未改默认release或正常Studio |

代码以隔离目录为准。以上集合不能相加作为“全项目通过数”。普通依赖构建失败、旧fixture错误、验收脚本错误均保留在相邻evidence，不通过删除失败记录制造完成状态。

## 当前来源能力矩阵

研究目录仍保留2026-10-01–02的13个来源、63个资源与35份成功/失败证据索引；它不是运行registry授权。当前级别以这里和具体TestSession为准，所有新文件仍需fresh QA。`real_source_verified`只覆盖所列文件/时间范围，不代表整州全部产品或新版本。

| 来源资源 | 格式 / grain / 范围 | 当前级别与转换/更新边界 |
|---|---|---|
| NSW TfNSW crash / traffic unit / 手册 | XLSX、PDF；crash/unit；目录2020–24及历史 | implemented：既有固定native；早期冻结输入回放证据保留。本轮未做当前发布版本完整主链；新版本research_only |
| VIC Accident / Vehicle / Person / Node / lite及字典 | CSV/API；crash/unit/person/location/事件；2012起多表 | implemented：固定native；当前portal新UUID、多表关系、lite重叠与新版本research_only，不能混算 |
| QLD crash locations / casualties / 主题表 | CSV/API；crash与聚合observation | real_source_verified：固定SHA、原415407行中的2020–24共66624行及改名复用。当前GDA2020资源与去标识键跨版稳定性仍需新证据 |
| SA DIT 2020–24归档 | ZIP内CSV；63239 crash / 134981 unit / 23892 casualty | real_source_verified：完整三粒度关系、Lambert坐标、计数、复用。实际2020旧版已取得，但REPORT_ID跨版无交集；跨版发布not_run |
| ACT Socrata 6jn4-m8rx | CSV；76657 crash，2015–2026观测 | real_source_verified：2026-10-03当前官方导出，RDF/W3C字段依据；0模型复用及raw-only自主路径通过。死亡/伤亡人数未知；用户旧CSV不能冒充当前无损表示 |
| TAS Crash FeatureServer / 统计报告 | 有界GeoJSON/API；2024-01共632 crash；另有聚合报告 | real_source_verified：精确query范围、时间/坐标/全键、无损表示派生与复用。不是完整全州总体；统计报告仅research_only |
| WA DataWA / CrashMap | 官方委托ArcGIS目录、元数据、5条query；空间服务 | research_only：原服务停止与另一个图层需区分；不把几何WKID推广至所有WA文件；当前完整主链未验 |
| NT 道路安全统计/申请入口 | 报告/聚合；公开明细未取得 | research_only / access_limited：记录访问限制；未绕过申请，CSV/API主链not_run |
| 全国 BITRE ARDD旧/新入口及相关统计 | XLSX/CSV/报告；伤亡明细和聚合、各sheet粒度不同 | research_only：字典/方法/修订入口已登记；未下载全部历史工作簿，未把每行当事故，未做全国整包发布 |

完整入口、资源ID、许可状态、覆盖、字段和可回读证据见 `pipeline/arsia_pipeline/knowledge/catalog.json`；历史研究说明见 `OFFICIAL-ROAD-DATA-KNOWLEDGE-20261002.md`。后者已标明历史时点，不能将其中旧CRS阻塞与未执行声明当作本轮当前结论。

## F01–F40 处置表

| ID | 复核与当前状态 | 根因 / 修改或下一动作 | 验证与限制 |
|---|---|---|---|
| F01 | 已修复并通过直接回归 | trusted_host 的直接/envelope/Session/Bridge 统一归类；未知宿主异常为 system_fault | pure-all-05；codex-boundary-db-02 |
| F02 | 仍成立；隔离数据库验证 | publication_policy.py、worker.py；manual_reviewed 不获得 official_admitted 身份 | publication-db-02：9 passed |
| F03 | 实现及隔离 DB 验证完成；真实跨版未验 | native_membership.py 保留原键/前导零，旧固定输入不能回退已准入版本 | publication-db-07 的15项含A→B→A（明确QA替身）；real-native-qld-02 实际固定输入/独立oracle/改名no_change；未称真实官方A/B成功 |
| F04 | 危险默认入口已绕开；独立浏览器已补验 | 4个历史写测试默认排除；DB双marker与冷绑定；pytest真实模型禁用 | pure-all-05 / publication-db-07、08；维护 browser-lab-02、browser-limited-01 仅写独立Studio；唯一3100顺序切换 |
| F05 | 已修复、执行环境已验 | Node22.22.x及生命周期检查；node:sqlite需求与文档一致 | Node22.22.2；typecheck20/lint02/build03 |
| F06 | 最终wheel干净安装通过 | 时区规则及许可显式打包；新venv在源码外 -I 导入 | wheel-final-03 / wheel-import-03；未修改原venv |
| F07 | 仍成立；Studio 已修改 | 统一 UTF-8 字节、替换净增量、事务内容量检查 | studio-existing-01.log；studio-boundaries-01：6 passed |
| F08 | 仍成立；Studio 已修改 | 64 上限只阻止新增，不阻止合法原位 retry | studio-boundaries-01：6 passed |
| F09 | 仍成立；Studio 已修改 | transfer 建研究与持久化身份在同一 SQLite 事务 | 父进程退出studio-boundaries-01：6 passed |
| F10 | 仍成立；隔离数据库验证 | registry filters-before-limit + stable keyset pages | registry-db-01 |
| F11 | 已实现及实际复用通过 | recipe模板/运行审计分开，索引候选不受无关对象数量影响 | 90无关模板/86运行；ACT/TAS/SA同名或改名 fresh QA，0模型 |
| F12 | 仍成立；纯测试验证 | CancellationCheck 本地检查逐次、外部轮询 250ms、发布前强制 | 100000 次行回调仅一次 SQL 轮询；取消与失锁反例 |
| F13 | 已实现及新旧覆盖回归通过 | 完整区间与观测跨度分离；逐键移除权限仍检查 | publication-db-07/08；optional-columns-db-02；真实三源 complete=false |
| F14 | 已实现直接回归 | Python/Web 同用 date-range.json 1800–2200 | web-default-01：153 passed；pure-02：17 passed |
| F15 | 已实现直接回归 | catalog 错误明确 503/404；空本地发布标记 empty | web-default-01；维护浏览器验证实际release与能力，故障分支仍以直接回归为据 |
| F16 | 已实现、真实请求账本已对账 | 失败/取消保留unknown；待完成请求有持久租约 | 173 Node tests；autonomous-act-03 22次账本与步骤完全一致 |
| F17 | 仍成立；测试启动已改 | 每个 DB 测试模块冷启动独立 runtime，禁止重绑定正常配置 | registry-db-01 / publication-db-02 |
| F18 | 说明已更新并完成维护集成 | README/IMPORTS/STUDIO/pipeline README、本文及维护交接说明当前入口与限制 | 历史任务的临时次数/冻结限制不变成永久规则 |
| F19 | 已更新当前能力断言 | ACT 历史 RDF 阻塞单列；当前实现不冒充真实输入准入 | catalog-02：60 passed |
| F20 | 已实现真实容器验证 | 独立 35s 容器 wall time；精确归属收据；失败清理可重试 | analysis-lifecycle-01：父进程 SIGKILL 后 35043ms 退出；Docker 不可达后恢复通过 |
| F21 | 进程边界及直接回归通过 | 复杂解析子进程 CPU/wall/输出/取消边界；Linux AS、Darwin RSS100ms | pure-all-05；Darwin瞬时内存超调不宣称硬内存上限 |
| F22 | 三来源独立逐行oracle及自主ACT通过 | 标准库原始值/键/日期/计数核对；SA独立Lambert反算；不复用canonical.project生成expected | real-source-index-04；QLD固定native额外415407原行/66624入域记录核对 |
| F23 | 已实施并直接验证 | claims.ts 将参数、执行、数值引用支持分开；check_claims 绑定 source/metric/date/pointer；最终自由文字不自动认证 | claims-02：32 passed；不是因果或任意自然语言结论验证器 |
| F24 | 已实现直接回归 | 所有入口共享 loopback 3100 Host/Origin 策略 | web-default-01 |
| F25 | 容量与显式维护入口已验 | UTF-8 净增量、Before restore 单快照；studio-admin.ts 容量/完整备份 | studio-admin-01：7 passed；没有自动清理或完整跨工作区迁移 UI |
| F26 | v1 与显式备份后迁移已验 | 历史库只读，CLI 指定绝对路径，拒绝覆盖备份 | studio-admin-01；只迁移测试 fixture，正常 Studio 不动 |
| F27 | 已实现有限依赖兼容及复用验收 | 仅合同证明未使用的工作簿/lookup模块可缩小失效范围；核心依赖始终严格 | test_dependency_scope；历史表示/受控字段版本DB链通过 |
| F28 | 已实现离线严格校验 | catalog_schema.py：资源、grain、字段、许可范围、证据引用及标准采用链 | catalog-02：60 passed；研究记录并不获得准入权限 |
| F29 | 运行合同、QA、catalog 和 Web 已串联 | licence_assessment.py 只接受授权图中的精确资源 URI 声明；未知/冲突/限制状态不会由文字获得许可 | 3 项 licence 测试及三来源真实发布均保留 unknown；不宣称再分发许可 |
| F30 | 共享模型账本、按需容器视图与真实网关已验；浏览器未跑 | model-budget.ts 多进程协调；resource-usage.ts 只读精确归属；缺失 Docker 状态为 unknown | autonomous-act-03：22 次调用的数据库步骤与网关账本 input/output/cache 全相等；容器总并发预算未配置，执行器各自资源限制保留 |
| F31 | 发布时摘要与读取减负已验 | publication_summary.py 在已完成数据库对账后记录不可变行数/月度能力；catalog 不扫描新批次明细 | DB 50 次拒绝明细扫描测试；三来源各 20 次真实 catalog 延迟见证据；冷/热缓存压力矩阵未跑 |
| F32 | 当前质量总表已建立 | 纯Python、Node、专用DB、容器、官方主链与浏览器状态分列 | 见本文当前质量状态；失败证据全部保留 |
| F33 | 当前规则入口已建立 | 本报告关联Goal、知识目录及运行文档，标明实现与未验收边界 | 本轮授权优先于旧任务临时次数限制；永久保护边界不变 |
| F34 | 已完成一份真实历史冷备份的 SQL 恢复 | verify_cold_database.py；新网络隔离卷/容器，仅 PostgreSQL 启动，事务默认只读 | cold-sql-restore-02：1393 成员还原、632 payload 全相等、release/batch/registry 引用一致、0 孤儿；17 张表；没有迁移或恢复历史 worker |
| F35 | 代码审查清单与保护复核已生成 | 独立快照逐文件新增/修改清单；458个原文件哈希未变 | review-candidate-02.json/.patch；基于完整未提交工作区，不是Git HEAD可重建声明 |
| F36 | 按实际边界整理完成 | 抽出生产Codex gateway复用于私有验收；JSON/CSV表示证明、资源视图局部分离 | 未做无关格式化或巨型策略DSL |
| F37 | 三州三类主链及额外自主路径通过 | 当前官方 ACT CSV / SA ZIP三粒度 / TAS GeoJSON；raw-only ACT自主研究完整链 | real-source-index-04；维护补验真实TAS及合成受限浏览器，ACT/SA为API/服务链。用户原ACT最终绑定被阻断，不能用当前官方输入替代该结论 |
| F38 | 直接回归及适用浏览器通过 | All 地图保留未被替换的 baseline 州；新来源单独能力 | web-default-01；维护TAS 632条/149格与保留baseline州、缺CRS地图unsupported均实际浏览器验证 |
| F39 | deferred，本轮不要求 | Linux/多用户/公网部署 | 未验收；仅本地单用户范围 |
| F40 | 版本/字段变化与从空缓存自主流程已验 | 完整源绑定、最小字段差异、证据刷新、fresh QA；自主 ACT 保持原模型预算 | optional-columns-db-02 全链 0 模型；autonomous-act-03 自行调查成功。开发者已知 ACT，不宣称未知盲测 |

## K01–K10 兼容性验收台账

这些是验收要求，不是十个已经确认或修复的缺陷。未运行不得视为通过。

| ID | 正例 / 配对反例 | 当前状态 |
|---|---|---|
| K01 | 改名/CSV 列序/BOM/换行/UTF-16/CP1252/分隔符、JSON 属性序；改键、精度、丢行/重复属性阻断 | real-tas-derived-01：真实632条派生 GeoJSON 属性反序/CRLF/BOM 完整主链及 oracle、同名/改名 no_change、0 模型；CSV 合成完整重放正反例通过 |
| K02 | 机械表头与备注/可选字段；核心键/计数/单位改义阻断 | optional-columns-db-02：连续增加 Extra、移除 Note、重排列序/BOM；完整官方传输 fixture 绑定→QA→DB，保留全原值；缺 DATE 无执行/无发布。34 项相关直接回归通过；不把合成传输当真实官方版本 |
| K03 | 历史收据/受控转换；伪造和无版本绑定拒绝 | representation-reuse-db-04：可信历史收据无需 HTTP 即完成新 QA/发布；完整上传绑定 policy 25，伪造/改义反例通过 |
| K04 | 适用 PDF/HTML/标准链；改义/越作用范围/任意外链拒绝 | 复核现有证据链已支持：test_count_definitions 真实固定 PDF 与版本/字段/范围/权限反例；metadata_extractors/evidence_scope 不将 HTML href 自动当授权；SA真实主链和 TAS官方 Esri链通过。任意自然语言自动解释与任意迁移仍未支持 |
| K05 | 缺 CRS 的原始坐标保留，非空间指标可发布；编造地图输出仍被完整 QA 拒绝 | limited-publication-db-02 真实 QA→registry→DB→API→Web/Ask AI/Studio 工具通过；维护 browser-limited-01 另补实际浏览器与独立Studio、请求能力和未达目标显示。明确合成源 |
| K06 | 未验证辅助表原样保留/扫描并标限制；与已验证同粒度或关系冲突拒绝 | retained-db-03：policy 25 真实 executor→QA→PG→Web/Ask AI/Studio 工具通过；合成辅助表 2 条完整保留且不造出 unit facts |
| K07 | 显式完整键及全原值相同的去重；逐行 retained/exact_duplicate 去向、1/0 分配；冲突、丢行、伪造去向拒绝 | limited-preprocess-retained-db-03/01：policy 25 真实 executor/QA/DB 与独立 literal oracle 通过；冲突去重负例保留 |
| K08 | 有界 ArcGIS 观测可在 snapshot/partition/incremental 下提出；实际移除仍需权限，min/max 不补零 | bounded-observations-01：55 passed；TAS 632 条官方观测查询通过；三真实来源 complete=false |
| K09 | 超旧阈值索引/分页；资源预算仍有界 | registry 85 条/跨州分页已验；cache 86 审计/90 无关模板直接回归已验 |
| K10 | 合法研究候选独立；不能覆盖官方或污染 recipe | research-publication-db-02：15项发布回归通过；实际generic parser→SQL→API→Web/Ask AI/Studio工具完整链。来源选择、查询和证据明确标official identity unverified；0模型、不写官方registry、同名官方覆盖反例保留。浏览器未跑 |

## 当前证据索引

- `../evidence/registry-db-01/00-test_registry_pagination/pytest.txt`：独立 PostgreSQL，85 adapters 跨州过滤与分页。
- `../evidence/publication-db-01/`：保留失败；负例破坏共享 CAS 测试输入导致后续 fixture 上传拒绝。修复 fixture 隔离，不放宽生产校验。
- `../evidence/publication-db-02/00-test_unified_publication/pytest.txt`：9 passed。合成 loader 政策测试与实际 generic parser QA；不代表三州官方端到端。
- `../evidence/wheel-build-02.log`、`wheel-import-01.json`：离开源码在新 venv 安装导入，timezone 内容哈希通过。历史wheel早于后续代码；当前源码已由wheel-final-03重建、wheel-import-03源码外干净安装验证。
- `../evidence/studio-existing-01.log`：8 passed；临时 SQLite 与静态项目快照，无真实模型。

## 维护授权前的未完成项（历史时点）

Goal 保持 active，等待最终交接与安全集成条件确认。隔离候选已完成本报告列出的实现/直接验证；现有产品尚未改变。真实浏览器 not_run，原因是唯一3100仍由原工作区提供服务，本轮不替换其他窗口服务或临时增加预览端口。实际官方A/B键迁移/跨版本发布 not_run：SA真实版本对虽已取得，键后缀发生全量变化，缺少授权的稳定键迁移证明；不截后缀造成功。

固定 native A→已准入B→旧A 已用明确的宿主QA替身验证发布政策，并补充真实固定QLD完整解析与重传。它不等于真实新版QLD自主准入。本轮未实现任意ETL、任意证据语言解释、任意JSON数组重排等价、Linux/多人/公网部署；未把这些能力标通过。

缺少支持证据的地图、人数、辅助关系及许可维持受限/unknown，原始值与用户未达目标保留。主数据库只读访问未成功；没有进行主库内容比对，文件哈希保护不替代SQL证明。

## 最近验证补充（不是合并后的全项目通过数）

- `publication-db-04/`：独立 PostgreSQL，37 个 backend + 11 个统一发布测试通过；本轮容器已停止并保留。
- `studio-boundaries-01.log`：6 项临界容量、retry、transfer 父进程退出、版本恢复和显式备份迁移。
- `web-default-01.log`：当时源码的 153 项默认 Node 测试通过；typecheck-04 无错误。
- `analysis-lifecycle-01.log` 与 `analysis-lifecycle-01/parent-death-verification.json`：仅本轮专属镜像/容器，父进程死亡、独立墙钟、清理失败恢复。
- `parser-01` 至 `parser-05` 保留初始失败与修正；macOS 不支持 RLIMIT_AS，RSS 是 100 ms 采样，允许瞬时超调；不宣称宿主进程拥有 Linux 容器式文件系统隔离。

## 历史验收阶段（当前身份验收以04及最终索引为准）

以下是开发中的较早阶段记录，保留用于解释修复；特别是real-act-03不能证明用户旧CSV满足最终源绑定。当前官方输入以real-act-04 / real-sa-04 / real-tas-04及real-source-index-04为准。以下来源均已参与此前研究，是当时合同在新实例中的确定性复验；不是未知盲测。私有 oracle 不进入 Agent 输入。三条链均执行真实 API 上传、当前 sample/full QA、registry、事务发布、数据库查询、通过专用只读 Unix socket 的网站数据服务。没有改绑 3100，没有真实浏览器或模型调用。结果绑定各自 session.json 的 trusted implementation，不等同于后续所有修改的最终冻结验收。

| 来源 / 表示 | 独立核对范围 | 本轮结果与证据 |
|---|---|---|
| SA / 官方 2020–2024 ZIP | 63,239 crash、134,981 unit、23,892 casualty；所有键、原值、日期、类别、计数、父子关系、原行定位；根据官方 Lambert 参数独立反算坐标 | `real-sa-02`；437 fatal crashes / 469 fatalities；改名复用 no_change，0 模型；约 123.61 s |
| ACT / 用户原始 CSV | 76,657 行；逐键日期、严重程度、原值、八位小数坐标误差界；fatal crashes 与人数分开 | `real-act-03`；105 fatal crashes，fatalities/casualties 仍 null；同名及改名均 fresh QA/no_change，0 模型；约 92.76 s |
| TAS / 官方 2024-01 GeoJSON | 632 feature；全键、日期 UTC+10、原值、原生类别、精确原始数字及坐标；未声称完整总体覆盖 | `real-tas-03`；同名及改名均 fresh QA/no_change，0 模型；约 9.86 s |

精确文件哈希、batch/release/adapter ID、oracle 与运行身份索引：`../evidence/real-source-index-01.json`。每个目录包含 `initial.json`、`independent-oracle.json`、`web-service.json`、`acceptance.json` 和 `storage-finalize.json`。仅停止本轮容器并完整保留。

TAS 的 `real-tas-01` 被旧 TZif 文件相等检查误拒：Windows 地区时区采用夏令时规则，但官方明确声明不采用夏令时并给出固定 IANA 时区。新规则比较适用区间内标准偏移，使用完整 TZif 转换点和 POSIX footer；不是按州放行或只比当前偏移。117 项相关正反例通过。官方依据与下载收据存于 `official-refresh-02`，包括 [Esri timeReference](https://developers.arcgis.com/web-map-specification/objects/timeReference/)、[FeatureServer Date 语义](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/) 和真实 TAS 图层元数据；适用普通 Date 字段，不覆盖编辑追踪/时间感知 override。

失败均保留：TAS 第二次发现 oracle 必须按原始 JSON 十进制核对，而非把 reader 保存的精确字符串当浮点对象；没有修改源数据。ACT 第二次在网站服务阶段失败，原因是验收脚本使用了部分月份上界；第三次采用产品的整月筛选范围，保留 coverage.complete=false。Python 默认 urllib CA 失败记录 `official-refresh-01`；使用系统 CA 验证后 `official-refresh-02` 六份官方元数据/规范成功，没有关闭 TLS 校验。

catalog 真实 Unix-socket 延迟各 20 次，Node 注入读取不使用 publication cache：SA p50/p95 11.84/27.16 ms，ACT 10.24/12.90 ms，TAS 11.04/21.02 ms。它们是当前本机的小样本读性能，不是负载测试或未来容量保证。

## 官方版本对与受限能力

已从当前 SA 官方目录合法取得一份 2020 年历史 ZIP（865,285 bytes），与已有 2020–2024 包构成真实官方版本对，收据与比较在 `sa-official-version-pair-01`。2020 年事故数同为 11,534，但原始 REPORT_ID 后缀分别含 2021 与 2025 发布日期，键集合没有交集；新版多出 Crash Date Time。相同行数/类似表头不能证明跨版键稳定。本轮未截去键后缀，没有根据这种相似性申请删除或覆盖权限。真实官方跨版本发布尚未执行，需要适用历史字典/CRS与合法键迁移或独立版本政策。

`limited-publication-db-02` 使用明确合成的缺 CRS 输入，经真实 Docker sample/full QA、registry、数据库与 Web 服务后，事故数为 1，死亡/伤亡未知，地图 unsupported。原始坐标、附加备注、原始诊断、requested=true 和 target_satisfied=false 保留至 API、证据面板数据、Ask AI metadata 及 Studio workspace。真实浏览器未运行。`limited-parser-01` 11 项正反例包含伪造坐标被完整重放拒绝。

## 当前安全运行入口

- 普通 Node 测试：`npm test`；纯 Python：`PYTHONPATH=pipeline pipeline/.venv/bin/python -m pytest pipeline/tests -q --executor-image <已审查的本地标签>`。在独立源码快照可使用原 venv 的绝对可执行路径，只读复用依赖，不重新安装。
- DB：`verify_isolated_regressions.py --new-managed-session --storage-policy keep-full --output <新绝对路径> --executor-image <标签> --test <测试模块>`。每个模块独立实例、冷进程和持久 marker。
- 真实已知源：`verify_act_isolated.py --dataset act|tas --proof <已核验合同及原收据目录> --output <新路径> --executor-image <标签> --storage-policy keep-full`；SA 用 `verify_knowledge_isolated.py`，显式传只读 `--artifacts` 与 `--research`。这些是确定性复验，不是模型探索脚本。
- 当前本轮 import 镜像为 `arsia-import-adapter:integration-20261003-04`（精确不可变 ID 见每次 session 收据）；真实三源验收使用该镜像。分析镜像为本轮专用 `arsia-analysis:integration-20261003`，不覆盖正常标签。
- Studio 容量、备份和显式 v1 升级见 STUDIO.md 的 `studio-admin.ts`。测试已验证中文/emoji、净增量、原位重试和备份前置；本轮正常用户库从未迁移。

## 最小后续动作

1. 根据可审查差异清单决定安全集成窗口；原工作区有动态加载进程，不能直接覆盖文件。
2. 若执行浏览器验收，应在唯一3100的明确专用绑定与独立Studio/Imports release下进行；没有该条件则保留not_run，不复用危险历史写套件。
3. 需要真实官方跨版本更新时，先取得适用的稳定键/迁移和删除权限证据；当前真实SA版本对不能凭相似行数取得权限。

## 2026-10-04 增量：完整文件绑定、兼容性和共享用量

`pure-all-03.log`：1477 passed / 46 skipped / 1 dependency deprecation warning。此时完整文件绑定、JSON/CSV/ZIP 表示证明、辅助原值保留与重复行去向测试已包含。随后新增模型网关任务身份头，已由pure-all-05完成全量回归。`web-all-04.log`：165 passed，`typecheck-15.log` 与 `lint-01.log` 通过。后续对静态 wiring 测试改成真实 audit/SQLite 联动测试，当前Node结果见web-all-08。

`representation-reuse-db-04` 在真实 Docker、sample/full QA、registry、独立 PG 中完成初始版本→历史收据支持的 UTF-16/CRLF 表示→受控新内容版本。0 次模型，旧批次 Note 值不变、新批次反映新值、观测覆盖 complete=false。前三次失败记录保留，分别揭示 fixture transport 定位、预检未传资源收据及观测跨度误作完整范围的问题。最后一项改为仅保护已证明完整区间，实际逐键移除门禁不变。

源文件认证新增 `source_binding.py`：必须有宿主登记、实例内完整 receipt/CAS 内容，且 URL 与发布机构资源关系相符。历史版本可用；CSV 对全部字段和记录多重集重放，JSON 对所有类型化值/数组顺序/精确数字 token 重放，只忽略属性顺序及无意义空白。元数据、相似样本、表头或模型填写 URL 不够。ZIP 从官方归档完整流式重算成员哈希。研究字典、坐标语义证明与上传身份分别检查。

ACT 原用户文件 76657 条与 2026-10-03 实际官方导出相同键集合，但 Location 全部有前导空格差异，LONGITUDE 4169 / LATITUDE 4585 条有小数精度差异。因此没有将该历史上传宣称为当前导出的无损表示。`act-official-export-01` 保留一次必要完整下载的 HTTPS 收据及独立字段差异；`inputs/act-current-reviewed` 只将真实 HTTP 200 capture 规范为 fetched，并保留原收据哈希/时间/URL，供新的隔离 ACT 主链使用。原用户文件不修改。已有 real-act-03 仅证明旧政策下转换/查询正确，不能代替 policy 25 的上传身份验收。

共享模型账本不记录问题、数据行、凭据。Ask AI 最多 12 请求，Studio 在原三次尝试上累计最多 36 请求，schema assistance 每任务 2 请求，Imports gateway 上限 120（宿主原有更严格策略继续生效）。它们是现有有限任务策略的协调上限，不是用户总 token 预算。请求租约在 240/600 秒权威超时后可以解除占位，但旧调用仍计数、未知用量不变成零。cached input 是 input 子集。没有回填历史 JSONL 或改变当前模型路由。

当前镜像 `arsia-import-adapter:integration-20261003-04` 下，real-act-04 / real-sa-04 / real-tas-04 均通过 policy 25 主链。real-source-index-02.json 记录精确身份。后续native实测、wheel/build、用量、SQL恢复和保护复核均见本报告最新记录；浏览器与原工作区切换未执行。

## 2026-10-04 最新验收与限制

- `autonomous-act-03`：新 TestSession、空 recipe、仅原始 ACT 官方 CSV、未提供合同/adapter/oracle。真实 Codex gpt-6.1-sol/high 自行研究后，经 sample/full QA、registry、事务发布、SQL 与网站服务/独立逐行 oracle 全通过。76657 crash、105 fatal crash；人数未知保持 null。worker 244.804s，总270.384s。模型22次，input1367890、output5008，其中 cached input1277354 属于 input 子集；网关与 AgentSession 账本逐项一致、usage unknown0、pending0。开发者此前知道 ACT，不能称未知来源盲测。
- 独立模型网关复用生产 Codex proxy，专属 Unix socket 0700/0600 与 TestSession marker，不经原 3100。原 runtime、官方输入和原 `.env.local` 哈希均未变；密钥只在进程内加载，不进入收据。之前 `autonomous-act-01` 文件名缺扩展名、`02` 缺固定运行包，均0模型，失败不被重写；新任务只在根因修复后创建。
- 固定运行包为原项目的 codex-cli0.159.3，通过只读目录引用使用；binary SHA256 `4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878`。`check_runtime` 在 task bridge 启动前将缺依赖标为 system/environment_dependency。`codex-boundary-db-02` 17 passed，真实 macOS boundary/descendant 生命周期验证，0模型。
- `real-tas-derived-01`：保持所有数字原 token、数组顺序，反转对象属性顺序并加 BOM/CRLF；原哈希 `c1336426b2414fc590d8b97ce6213c253d7bee3e6b0b1cf625c8331768452f38`，派生哈希 `146a6641cc7636aa42d5ab5ff5527e2f31c9675474f2a7144b0777b12efb9975`。632条完整 oracle 和 Web 服务一致，同/改名重传 fresh QA/no_change，0模型，12.34s。派生输入只验证兼容性，不是新官方版本。
- `cold-sql-restore-02`：抽样恢复历史 TAS 冷备份（归档SHA `e039c1b52b1873b609140f11c4911d6134cb8478da10256b96b8f35d6e8dc7c6`），使用原 PostgreSQL image，网络 none，无主机端口。1393 成员/所有者/模式核验，632 payload 与原证据全相等，SQL 引用完整；约2.25s，专属卷保留、容器停止。此结果仅覆盖该备份，不代表73份备份全部SQL恢复或主库比对。`01` 在创建资源前因原镜像默认 POSTGRES_USER 未显式提供而失败；其旧 finalize 的 volume_retained 是预定名，未实际创建，修订工具改记 null。
- `resource-view-01.log` 5 passed：Docker 故障/归属不符不能变成零，私有配置不泄露，符号链接不能改绑。界面按需显示模型用量及活动/停止/待清理容器；不自动清理，不启动监控；总容器并发预算未配置。

隔离启动命令：`verify_codex_owned.py --confirm-real-model --source <只读原文件> --upload-name <公开文件名.csv> --output <新目录> --reference-runtime <只读原runtime> --model-env <私有环境文件> --executor-image <固定镜像> --storage-policy keep-full`。有实际付费调用；必须是明确授权的新实验。`--probe-only` 只检查私有网关拒绝无权请求，不调用模型。不得用旧 output 或自动恢复旧 job。

SQL冷恢复：`verify_cold_database.py --archive <tar.gz> --receipt <verified.json> --original-inspect <只读原容器清单> --expected-job <原任务结果> --expected-rows <已保留JSONL> --output <新目录>`。仅支持清单内固定归档协议/PG数据目录。验证原归档后创建新卷，不启动应用、不迁移；结束仅停止本次自有容器并保留全部资源。

当前整套直接回归：`pure-all-05.log` 1482 passed、46 skipped（需专用 DB 的集合分开运行）、1 个 Starlette 依赖弃用提示；`web-all-08.log` 173 passed。`analysis-container-final-01.log` 6 passed；`typecheck-21.log`、`lint-03.log`、`build-05.log`（Webpack）通过。默认 Turbopack 构建在隔离快照的外部 node_modules 符号链接处失败并保留 build-01.log；未声称默认构建通过。真实来源总索引更新为 `real-source-index-04.json`。

当前wheel SHA256：`b4513957772828296beb8668cb76862e5138422f59eba0a4d052e6145cc5426f`。第一次 --no-build-isolation 缺 setuptools，未在原venv安装依赖；第二次仅临时构建环境取得构建依赖，最终新venv安装成功。

最新数据库回归：publication-db-07 的统一发布15/基础backend37通过；autonomous backend首轮77通过3失败，原因分别为旧“narrower”文案断言和2个未带持久任务身份的HTTP夹具。更正为实际逐键移除阻断诊断、补齐模拟身份后，publication-db-08 全80通过。生产移除门禁和终态/取消断言保持。

真实QLD fixed-native：real-native-qld-02 输入SHA `975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704`，415407行完整读取，受固定2020–24规则选择66624条，fatalities1424/casualties88609。首次及改名均独立逐键核对；replay no_change，同release/batch，0模型，总21.46s。01在实际发布后因验收脚本将固定准入等级拼为 frozen_native 而失败；实际等级fixed_native，未修改生产准入。


## 最终补充：研究来源身份与交付复核

K10补齐只读身份传播：Python catalog/query从已保存准入结果及registry ID产生publication_status；Web来源选择、metadata/Evidence、单源及All查询、Ask AI/Studio都保留此等级。manual_reviewed标记“Local research: official source identity unverified”，不写official registry，也不能取代已有官方source。受限研究不是官方准入或再分发授权。`research-publication-db-02`在全新数据库实际执行generic parser及API/Node服务链，15项发布测试通过；`web-all-08`共173项通过。没有改动核心QA政策25或官方转换结果。

`query-authority-db-03`9项通过，另验查询身份/未知指标；`query-authority-db-02`的geography与unit volume模块各1项通过。早期query测试把没有完整性证明的空月预期为0，此错误预期已改为null/no_results；配对的complete-calendar测试仍要求有证明时为0。失败记录01/02均保留。`query-authority-01`普通运行因DB保护跳过，不计通过。`research-publication-db-01`在创建容器前因错误测试镜像名失败，随后使用收据中的不可变SHA，未改共享镜像标签。`build-04`因新增测试的可选description未收窄类型失败，补充断言后build-05通过。

最终差异与保护证据见 `../evidence/review-candidate-02.json`、`../evidence/review-candidate-02.patch` 和 `../evidence/final-resource-audit-01.json`。补丁是针对记录过哈希的完整原工作区生成，不能盲目应用到变化后的源码。不得因本文已经准备好交付而自动恢复历史导入、迁移正常Studio或切换3100。

最终资源复核：`final-resource-audit-01.json`确认56个本轮managed TestSession容器均已停止、状态均可读取；Docker当前仅原正常Imports容器运行。原3100及API/worker的既有PID仍在，没有为收尾停止它们。SQL冷恢复及其他执行器的停止证据另见各自收据；不删除其数据卷或历史日志。
