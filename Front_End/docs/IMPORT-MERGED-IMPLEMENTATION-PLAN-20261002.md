# 通用接入修复与官方知识库：合并实施计划

日期：2026-10-02，Australia/Sydney。

当前批次：policy20/r9 接入 CKAN 目录内按精确资源 URL 选取 schema，字段／计数／类别共用资源范围；补入父坐标实际对象和轴向的结构化定义检查。冻结 VIC 官方 Node 经度／纬度定义已验证，不能据此忽略原始重复键。790 项离线、46 项真实 Docker、139 项隔离 DB/工具桥回归通过。完整语义准入与实际来源整链仍未完成，继续保留系统准入门禁。本批模型 0 次；报告为 `artifacts/generalization-implementation-20261002/lookup-subject-1/report.md`。以下段落与初始台账保留各历史阶段。

上一批 policy19/r9 的父字段计数粒度／防广播和物理地理检查记录保留在 `lookup-counts-1/report.md`，766／46／139 项不与本批重复累计。

上一批 policy18/r9 的父字段／CRS／类别及有限 CSVW 关联证据诊断记录保留在 `lookup-evidence-1/report.md`；其 740／44／139 项通过不与本批重复累计。

最新补充：交接报告和来源证据重新核实；F10 前置关系检查修复了部分空复合键误判和重复父键统计，627 项离线回归通过。六组现有 VIC 全量关系与独立 oracle 一致；Node 不是唯一 lookup，后续须按基数和粒度建模。详见 `artifacts/generalization-implementation-20261002/relation-preflight-1/report.md`。本批未重跑模型／浏览器／数据库验收。

此前实施进展更新：最新状态见 `artifacts/generalization-implementation-20261002/PROGRESS.md`。policy 15 / r6 的 union、ACT／SA 独立验收，Codex 短结果／定点读取／问题级进展已接入。已有 620 项离线、139 项 DB／bridge 回归。ACT 真实 API 冷启动通过；本批进一步通过 3100 `/imports/test` 的真实浏览器上传、关页继续、重开结果、证据下载及移动端，后台一次 attempt 174.88 秒、23 次模型／52 次工具，76,657 条独立逐行 oracle 与查询通过。测试配置原样恢复，自有容器停止。测试绑定 3 项离线回归和 TypeScript 通过。lookup／聚合、partial casualty、更多 provider／holdout 与最终审计仍待完成。下文初始台账为交接基线，当前状态以恢复检查点为准。

依据：`IMPORT-GENERALIZATION-IMPLEMENTATION-20261001.md` 定义正确性与隔离要求；`OFFICIAL-ROAD-DATA-KNOWLEDGE-20261002.md` 定义已经交付的研究目录、工具及保守复用能力；`artifacts/official-knowledge-20261001/VERIFICATION.json` 是历史验收索引。用户补充的执行顺序优先：先核实，再完成影响正确性的 P0 和回归，然后推进 adapter；不以全部 P1/P2 完成为前提。

本文交付现状核验、依赖关系和实施验收计划，不代表下面尚未实施的 P0 已经完成。核验过程仅增加本计划和审计产物，没有修改业务代码、启用配置、访问业务数据库、重启服务或恢复历史任务。

## 1. 本轮实际核验

- 已阅读两份文档、验收 JSON，并核对当前 reader、QA、grounding、地理审查、来源身份、知识库、recipe、Agent/bridge、更新兼容和进度实现。
- 原回归日志与 SA acceptance.json 的 SHA-256 均与验收索引一致。原报告的 **190 passed** 属于上一轮，不计入本轮测试数字。
- 目录实际为 13 个来源、63 个资源、35 个证据索引。30 个 fetched 条目的内容哈希和大小全部匹配；另外 5 个失败条目没有被当作成功证据。
- 本轮复跑 `test_source_knowledge.py`、`test_evidence_grounding.py`、`test_geography_review.py`、`test_source_identity.py`、`test_intake_tools.py`：**81 passed in 0.47s**。这是现有测试基线，不证明旧文档新矩阵已通过。
- 本轮重新执行 JSON envelope 顺序诊断：`type` 在 `features` 后，FeatureCollection 被误识别为 ArcGIS；ArcGIS `spatialReference` 在 `features` 后，其 CRS 丢失。两种旧缺陷仍可复现。
- ACT 原 CRS 诊断已有独立文件检查与失败复现；交接后的相关底层规则仍相同。本轮没有新建 ACT 导入，也没有再次执行 full QA 或发布。
- 保存了当前 Python 源码/测试及两份文档哈希与 Git 状态；不覆盖现有未提交工作。

证据：`artifacts/generalization-handoff-audit-20261002/` 下的 `audit.json`、`regression.txt`、`regression-command.json`、`baseline-files.json`、`git-status.txt`。

## 2. 已交付部分：直接复用，不重建

| 现有能力 | 合并后的使用方式 | 边界 |
|---|---|---|
| knowledge/catalog.json 和 evidence 内容对象 | 唯一研究目录和冻结证据入口；按需补充资源与新收据 | research_only 不转化为准入授权 |
| source_knowledge 的查询、定位、provider 投影与差异 | 沿用 read_source_knowledge/read_source_evidence/compare_source_metadata | 当前 schema 候选与元数据 diff 不等于语义兼容证明 |
| adapter_reuse.ReuseCache | 继续作为按实例隔离、依赖固定的 recipe 候选存储 | 必须新 sample/full QA；不能沿用旧 admission |
| EvidenceStore | 沿用按内容哈希保存对象的机制 | 权限、dataset scope 和时效不能仅由相同 hash 继承 |
| AgentSession / Codex TaskBridge 集成 | 在现有工具及 source-knowledge.json 上扩展预检、事实引用和 blocker | 不引入第二个规划 Agent，不重建一套 harness |
| SA 隔离验证和 ACT 独立 oracle 工具 | 作为新版本验收基础，补充缺失断言和新输出目录 | 历史通过不能替代修改后的回归；ACT 数据检查不是 admission |
| 原三州 native / registry / publication | 保持 frozen 边界，复用事务、取消、原子发布和版本机制 | 新官方资料不自动改写历史 source policy |

旧文档中建议的模块名不是新增文件清单。typed claims、metadata extractor、preflight 可增加独立职责，但应消费同一知识目录、原始收据和 registry；不要另建第二个来源目录、adapter 缓存或 evidence 存储。

## 3. 旧文档 F01–F18 状态台账

这里的 F 编号专指旧文档 §2.2 的缺口编号，避免与 §8 格式测试编号混淆。

| ID | 当前状态与依据 | 未完成原因／剩余工作 | 安排 |
|---|---|---|---|
| F01 | 仍需修复：trusted_qa._proof 仍以 .gov.au + final_host_official 筛选 | 知识目录只保存标准引用，没有改变 host 授权；需分角色、作用域和委托链 | P0 |
| F02 | 仍需修复：coordinate_evidence 无 RDF property 语义；ACT 尚阻断 | standards_links 是研究记录，不能替代可信提取与字段绑定 | P0 |
| F03 | 仍需修复：本轮重现 JSON 成员顺序导致误判／CRS 丢失 | reader 未在知识库任务中修改；补完整 envelope 检查与排列测试 | P0 |
| F04 | 仍需修复：reader 的 geojson_default_crs 尚未贯通地理准入 | 需 RFC 7946 geometry 的有范围解释、冲突处理及整链回归 | P0 |
| F05 | 仍需修复：_proof 验证 bytes 后仅向 grounding 传 text | 原始 JSON/XML/HTML 结构须进入可信抽取；保留定位和收据哈希 | P0 |
| F06 | 仍需修复：ground_contract 仍通过普通链接双向扩展连接 | 新目录的研究引用不解决授权；增加 typed directed edges、字段和资源范围 | P0 |
| F07 | 部分已有、仍需修复：CKAN UUID/name 有受验证 alias；URL 身份仍限制 gov.au 且与 grounding 分离 | 保留已有 alias 测试，统一 identity；区分 dataset 与带查询条件的 representation | P0 |
| F08 | 仍需修复：CSV 编码／首行表头／方言限制仍在 | 本轮知识查询允许继续调查，不代表 reader 已能解析；按实际 adapter 输入依赖实现 ParserPlan 子集 | 依赖型 P1 |
| F09 | 仍需修复：JSON header 仍只取前 100 条，Excel 首行／公式限制未变 | 若映射 late field 会影响完整性，优先补测；复杂 workbook 能力按资源需要推进 | 依赖型 P1；正确性问题升 P0 |
| F10 | 仍需修复：资源唯一分配及投影能力边界仍在 | recipe 是既有合同复用，不是 union/lookup/宽转长；为目标资源逐项扩展受控算子 | 依赖型 P1 |
| F11 | 仍需修复：casualty 完整性仍使用有限文本模式，partial 需澄清 | 目录已经辨明部分 grain，但没有实现可信 scope 运算 | casualty adapter 前置 |
| F12 | 部分事实已补、语义门禁仍待完善 | 官方字典/粒度知识更完整；类别、计数求和、snapshot 删除权仍需每种算子对应 claim | 涉及的正确性门禁先于 adapter |
| F13 | 仍需修复：Transformer 使用 always_xy，未见冻结 operation/grid/accuracy 计划 | 库存 CRS 说明不能证明运行时转换精度；非平凡转换需对应计划 | 涉及转换的 adapter 前置 |
| F14 | 部分已有错误码、仍需修复：传输/预算已各有 code，但缺统一 blocker 与问题进展 | 新知识 diff 尚未代替网页 hash／引用片段的进展统计 | P0 最小 blocker；其余 P1 |
| F15 | 部分完成：新增 compact 知识查询、定点读取、source-knowledge.json | 通用 TaskBridge 仍最多回传约 48KB；其余工具尚无统一短事实与差量接口；真实 token 收益待验证 | 复用现有接口，按需 P1 |
| F16 | 部分完成：recipe 已固定更多依赖、证据与 image | trusted QA 仍是固定清单；新增证据规则须纳入；update 当前主要校验身份／关联，不覆盖全部语义变化 | 新规则版本依赖为 P0，其余按 adapter |
| F17 | 仍需修复：qa_checks 仍按运行中或含特定结果字段计数 | 失败的 needs_evidence 可不计入；拆尝试／通过／失败及 blocker | 验收可观测性依赖，不阻塞全部 P0 内核 |
| F18 | 部分完成、待验证：ACT 原 CSV/RDF、SA counts、native 回放已有独立证据 | SDK 与 trusted replay 仍共享 canonical.project；本轮未执行新版本完整语义 oracle、行政边界或位置精度验收 | 每个 adapter 验收必需；超出声明范围的空间验收单列 |

因此，不把知识库交付写成旧文档全部修复完成。已经完成的子项是目录／定位／差异／严格同内容复用及其回归；影响 ACT、外部委托和 JSON 正确性的关键 P0 仍未闭环。

## 4. 合并后的实施阶段及门槛

### 阶段 0：交接核验与保护基线（本轮已完成离线部分）

完成上述代码核查、报告哈希、证据对象和 81 项基线测试，记录 F01–F18 状态。启动任何有写入的集成测试前，再读取主实例的 release/表哈希和历史 ACT 状态作为保护基线；只向本轮新 marker 的测试实例写入。

不重复调研已经冻结的 13 个来源；可以提前补查会影响后续资源选择的官方许可、覆盖和精确字段定义，但调研不能提升 adapter 状态。

### 阶段 1：P0 基础正确性修复

顺序：

1. 固化 JSON 顺序失败测试与原始证据传递测试，再修复 reader；包括 GeoJSON type、legacy crs、ArcGIS spatialReference 在 features 前后的排列与冲突。保持流式读取和有界内存，不加载整份 features。
2. 建立单一来源／资源身份与 raw metadata 提取；沿用现有 provider 知识，分清 publisher、具体 delegated resource、normative vocabulary 和普通 discovery。保留 Socrata 查询范围、CKAN 子对象范围、ArcGIS 精确层。
3. 以 host 派生 typed claims 和有向边替换授权上的普通连通性。实现安全 RDF/XML property 使用、精确 namespace、字段绑定；标准词汇只能解释已证明被采用的属性。接入 GeoJSON、ArcGIS 的几何作用域与明确轴序。
4. 加入 inspect_capabilities/preflight_contract 和最小 blocker schema。在模型调查与执行器启动前指出 unsupported_capability、evidence_conflict、evidence_missing 等，并明确负责方和恢复条件。研究目录描述不能当作自动支持声明。
5. 更新 QA policy、trusted dependencies 和需要的 executor image。旧 recipe 应因依赖变化拒绝直接复用；历史 ACT attempt/hash 不迁移、不重标成功。

门槛：旧文档 §8 的 E01–E10、F01（JSON 顺序）、G01–G02、A01 正反例及现有安全／身份／QA 回归通过。错误 locator、篡改 hash、第三方回链、页脚链接、邻近 dataset、只有 namespace 未实际使用、反转轴序、XXE 等均须拒绝。这里只完成机制与 fixtures，不声称 adapter 已准入。

### 阶段 2：ACT 最小整链验收，复查 SA 复用

依赖阶段 1。使用原 ACT CSV 与冻结资料创建新隔离任务；P0 完成前不让新 adapter 绕过旧门禁。

- 验证 CSV 全文件 Location 与 x/y 对应；官方有限样本覆盖不同年份和非空类别，明确抽样范围。保留 14 条 suburb 缺失、28,786 条方向缺失及示意坐标限制。
- 使用真实 sample/full executor、可信 QA、注册、事务发布、固定 release 查询。独立 oracle 不调用 canonical.project：76,657 个事故、105 Fatal，源严重程度与分年逐键核对；没有源人数定义则 fatalities/casualties 保持 unknown/null。
- 文件改名、列重排、ZIP 包装分开验证。当前同字节 recipe 复用已实现；列重排与包装等价能力未完成时须明确失败原因，不能误称零模型支持。
- 在新 policy 下重新验证 SA 的 sample/full、计数、重复导入 no_change 和错误候选拒绝；沿用现有验收工具，不另造第二条 publication 路径。
- 检查取消、失败、worker loss 不改变旧 release；核对主 NSW/VIC/QLD 保护基线和历史 ACT 状态。

门槛：报告分别列执行、QA、注册、发布与 query 结果；ACT 和 SA 每个承诺的能力都有独立预期。若新增共享投影逻辑，必须补独立 oracle，不能只增加共享实现的 replay 测试。

### 阶段 3：按实际依赖建设更多 adapter

不等待旧文档所有 P1/P2。按精确资源准备情况分批：

| 批次 | 目标 | 必需前置／正确阻断条件 |
|---|---|---|
| 保持现有三州 | native 回归与已发布边界保护 | 不自动用新版目录改历史 policy；更新需来源版本与覆盖证明 |
| TAS 或 WA 精确层 | 选择证据完整的一个不同 provider 资源做验证样本 | 先解决精确层许可、覆盖、geometry CRS、日期定义；WA 不同服务层不能互借授权。既有资料已参与设计，不能称盲 holdout |
| 真正 holdout | 在规则冻结后选未参与设计的 provider 表现形式／资源样本 | 记录选择与规则版本；允许正确阻断，不硬凑成功率 |
| VIC 多表 | 事件／lookup 关联及多个资源 | TablePlan、唯一 lookup、关系基数、完整包与跨表覆盖是前置 |
| QLD 相关 casualty / ARDD | 聚合统计和 casualty-only 粒度 | 粒度、稳定主键、计数与更新语义、受控聚合计划是前置；不伪造成事故微观表 |
| NT | 确认合法数据取得渠道 | 当前没有已验真的公开微观文件；资料不足则保持 research_only，不生成空壳已验收 adapter |

每批只实现所需 ParserPlan/算子/转换计划，并补正反例。例如需要非 UTF-8 才推进编码候选，需要 union 才推进同构分片；但发现数据丢失、错误计数或授权扩大时，无论旧标签 P1/P2，都先按正确性 P0 修复。

### 阶段 4：复用效率、网站与最终报告

在现有 knowledge tools 和 recipe 上补统一短事实、问题级进展、缓存失效及 QA 尝试计数。先做确定性测量；真实模型实验单独显式启用、新建隔离 job、记录失败和未知 usage。不能把过去失败成本与新成功成本直接换算为公平节省率。

网站验收复用 3100 的隔离路由，不切主 release；修改 Next 代码前读取已安装版本文档。报告展示的是实际测试完成的 adapter 范围，不宣称所有州都可自动导入。

最终报告逐项更新本台账：完成状态、代码和测试证据、未完成原因、剩余依赖。分别报告本轮与历史结果、离线与真实模型、累计步骤时间与总 wall、input/cached input/output/未知 usage；cached 是 input 子集。

## 5. 明确暂缓与尚未执行

- 全部 P1/P2 格式、通用 workbook/任意 lookup/任意语义算子不作为 ACT 修复前置；按上表依赖逐批扩展。
- 不建设向量库、图数据库、第二套 harness 或第二个规划 Agent；不重建已交付研究与缓存功能。
- 跨机器 registry 可移植、跨实例共享准入、远程定时更新、穷尽历史资料不是本次已确定交付范围。
- 本轮交接核验尚未实施 P0 源码修复，也未重新执行 SA 容器、ACT 准入、真实模型、网站全链测试或 token benchmark；这些是后续阶段任务，不能计为通过。
- 保留原数据、日志、历史失败及验收产物，不提交／推送／部署、不恢复定时任务或旧 needs_input 导入。
