# 限定自主适配优化：开发交付，尚未测试

日期：2026-10-02。依据侧聊的人类授权交接，仅开发后暂停，等待用户提供测试数据。**本轮未执行 pytest、导入、浏览器验收、smoke、模型验证、lint、typecheck、build 或项目模块。** 下述为源码实现与源码审阅记录，不是验收结果。此前限定一轮验收和 810 项历史离线结果不能证明本轮改动通过。

## 范围与集成

沿用 Codex harness、Python worker、隔离 executor、独立 QA、registry、事务发布及现有知识缓存，没有新建 harness、规划 Agent、知识库、UI 或数据库 schema。

可信 runtime 新开关为 `autonomous_adaptation_v1`，只有 JSON 布尔值 true 才启用；默认缺省关闭。它不是 upload options、合同字段或模型工具参数。新 session 从服务端配置读取并保存在 checkpoint；历史 session 未保存此开关则保持关闭。当前运行配置未修改，服务未重启。后续只能在用户授权的新隔离实验中启用，不能直接启用现有服务。

代码已接入既有 `agent_process → ReuseCache.prepare → AgentSession.execute_tool`。Codex TaskBridge 与 legacy loop 共用新的工具路由；worker 继续接收既有 NeedsInput/ValidationFailure 及 details，不引入状态机或迁移。

## 实际代码改动

1. `capability_preflight.py`：新增明确 opt-in 判断、有限失败分类及既有操作支持清单。阻塞包含操作、字段／行定位（已有诊断能提供时）、责任方、下一步、恢复条件。按结构化代码和异常类型判断，不把来源正文当指令或按正文猜错误类别。区分 input/source quality、证据缺失／冲突、adapter 修订、系统不支持、环境依赖、模型传输、预算停止；不是对所有历史异常的穷尽分类。
2. `agent.py`：开关按 session 固定；现有工具执行包装器接入分类和系统阻塞立即停止。拒绝的合同提议保留在 runtime_state；不授予执行／发布权限。preflight、执行前和独立 QA 使用同一操作限制。终态错误保留为既有 API 可读的 details。
3. `issue_progress.py`：opt-in 任务的问题范围绑定原上传 bundle 的 hash 与 policy，提议 URL、source_id、业务键编辑不自动换掉同一问题的身份；新网页、引文与代码编辑仍不算条件解除。保留原检查通过才解除问题的逻辑及预算，不增大调用额度。普通旧 session 沿用原范围。
4. `codex_bridge.py`：将结构化阻塞保存在既有 durable tool result，继续通过 needs_input/paused 与原 terminal 控制停止。保留真实模型传输的专属分类。
5. `trusted_qa.py`：可选操作门禁与 preflight 共用；opt-in admission 收据记录 operation_policy；原始重复键增加可分类的 source 标记。原行重放、守恒、完整关联、lookup 防广播、CRS／计数语义等保持既有规则，不执行模型自带 verifier。
6. `adapter_reuse.py`：保留原 sha256+size 路径，在 opt-in 新 full QA + registry 后记录同来源版本候选资料；未命中原路径时尝试新候选。复用的是 SDK 声明式转换逻辑，历史任意 Python 不进入宿主。所有命中继续 sample/full、QA、注册、发布；没有修改事务 no_change 逻辑。
7. `pipeline/AUTONOMOUS_CONTRACT.md`：更正会被 Agent 读取的旧 policy20 blanket lookup blocker 描述，说明实际 policy21 的受限语义门禁及本轮尚未测试的 opt-in 行为。
8. `pipeline/tests/test_adaptation_opt_in.py`：编写默认关闭、失败分类、问题身份、操作清单、CSV schema／列序和全输入日期范围的测试源码；**未执行**。

## 新版本候选的保守边界

候选只来自当前数据库实例中已 full-admitted 且在新开关下登记的 recipe。旧缓存不靠 schema 自动提升为新候选。注册代码、合同、证据 bytes、依赖、镜像均重新核对。

第一版只允许现有按字段名读取的单资源 CSV，以及各资源均满足条件的 unique lookup 组合。完整字段集、编码、delimiter、table selector 必须兼容；允许行数、内容、文件名、upload ID 变化。CSV 列序可在 shape 比较中等价，但最终上传 bytes 仍须与精确官方资源的当前导出一致，不能把用户自行编辑过的文件凭列名认作官方数据。

候选选择分两步：先比较实际结构，仅用于缩小候选；再通过既有受控 fetch 工具重新取得既有精确资料／资源 URL。元数据最终 URL 必须不变，raw hash 始终留存审计。仅受支持的 CKAN package_show JSON 可在明确的非语义差异规则下比较新旧资料，并重新绑定值未变的结构化引用；其他变化仍回退调查。上传 hash+size 仍必须一一对应官方资源下载，禁止下载内容替代上传内容。多个语义不同的候选不按“最新”武断选择；只合并 source/resource/操作、证据、解析、依赖均等价而旧 observed coverage 不同的候选。

重新扫描所有 crash 日期测量新范围，不用旧 source.coverage 过滤。新范围还必须在 preflight 已验证、实际被 coverage_update 引用且适用于对应资源的显式时间证据内；缺少明确时间范围时返回 `VERSION_TEMPORAL_AUTHORITY_MISSING`，不猜。旧 partition 更新边界不能因新 min/max 自动扩大；snapshot／删除权限仍由原完整性与事务门禁决定。

一轮候选扫描最多 64 个现有缓存对象；只对一个无歧义候选进行资料绑定，最多 16 份已有文档及 24 个资源，并使用原 fetch 大小/时间限制和任务预算。这些是有界候选预检，不是新重试机制。下载失败、schema/parser drift、证据变更、来源字节不符等返回具体 differences 给既有 Agent。实际操作／环境不支持则保留候选并停止。

## 能力支持矩阵（源码状态，均非本轮实测）

| 能力 | 实现方式 | 本轮边界 |
|---|---|---|
| 字段／日期／类别逐行映射 | 原 canonical + SDK，宿主逐行重放 | 不证明任意 Python 语义 |
| 同构 union | 原 table_plan 与原完整键／守恒 QA | 支持执行；新版本自动匹配暂不支持分片独立官方绑定 |
| unique lookup | 原完整父索引、关系证据、宿主重放及计数分配 | 不放宽重复键，不制造一对多输出 |
| 同字节改名重传 | 原 ReuseCache 路径 | 仍需当前依赖、证据和 fresh QA |
| 同来源新版本候选 | 新保守 CSV + 唯一官方 bytes 绑定 | 是候选，不继承 QA 结论 |
| CSV 列序变化 | 字段集合与有效 parser shape 比较 | 必须无歧义且有上述来源绑定 |
| XLSX/JSON 等新版本匹配 | 返回具体 parser unsupported，交回原 Agent | 原 reader 能力未删除；本轮不增加版本兼容解释 |
| 未知 CRS | 原 scoped evidence/transform 门禁 | 不靠坐标范围猜 CRS |
| 聚合、宽转长、任意一对多 | opt-in 明确 unsupported | 本轮不实现 |
| partial casualty、复杂 CRS、新 provider | 保留原具体能力边界 | 本轮不扩展 |

## 未完成、限制和后续验收

以下全部等待用户数据，当前不得写为通过：

- 默认关闭及历史暂停 session 行为；新开关不能由上传或模型启用。
- 首次用户数据调查、source identity／schema／日期／QA，以及新 recipe 登记。
- 同字节改名重传必须仍返回 no_change；新字节新版本不能仅凭文件名/行数判 no_change。
- 同官方来源新内容、行数和覆盖日期变化：候选命中后重跑全部 QA，并核对发布、更新保护与查询。
- 同字段集列重排：兼容结构与官方 bytes 绑定分别核验；人工改写来源无法证明时应退出自动复用。
- 新增、缺失或改义字段、encoding/parser drift、元数据变更：具体 differences，原 Agent 接手；不得自动放行。
- 两个资源共享 schema、重复文件或模糊绑定：不得任选其一。
- union 跨分片重复主键、lookup 完整父键重复／未匹配／计数广播：真实负例需正确拒绝。
- 缺少明确覆盖权威、未知坐标、聚合输入：分别展示 missing evidence 或 unsupported，不进入无限资料调查。
- 模型传输、环境缺依赖和预算终止：保留候选与诊断，不误要求用户提供数据字典。
- 系统 blocker 必须停止 Codex/legacy 后续模型请求；修改 URL/文字不能续重试额度。
- 新旧镜像、trusted hash、registry、主数据保护、网页/API 状态均需后续隔离核查。

本轮没有执行任何以上验证。源码审阅不能证明实际运行正确、性能、token 节省或所有州均可成功。

## 版本与恢复

沿用 policy21 名称，但 trusted implementation 依赖哈希已因源码修改变化；不能以相同 policy 字符串声称与旧验收版本相同。旧 recipe 的依赖失效是既有保护机制。未构建镜像、修改默认镜像或启动服务；未来由用户授权隔离验收，核对加载代码和 executor 兼容后再运行。

恢复入口：`artifacts/generalization-implementation-20261002/adaptation-development-pause-1/`。保留之前的 limited-acceptance-pause-1 全部证据，当前源码快照、逐文件 hash、相对旧暂停快照的补丁、开发报告及尚未测试状态单独保存。目标再次按要求暂停，等待用户提供测试数据；不自动进入下一阶段。


## 后续静态审阅限定修复（同日；仍未测试）

以 `adaptation-static-fix-pause-1` 为最新检查点，本节替代上文中“全部新旧资料原始 hash 必须相同”的笼统要求。本轮只修复两项静态发现，没有执行任何验证。

### 执行器错误与停止

已确认旧包装器会把 ImageUnavailable 转成 ValueError，并在补充分类前判断停止；full 模式还可能先被 image 一致性检查覆盖。现在保留 host executor envelope，完成最终分类后再判断停止；failed/unavailable 不经过成功执行的 image 一致性检查。宿主缺镜像、Docker 创建/状态不可用、宿主 TransformError 能区分为系统/环境阻塞，并保存 run_id、原类型、操作、责任方、下一步和恢复条件。

sandbox 的 bounded_report 丢弃模型提供的 origin/code，并标注 adapter；因此生成代码的 ImportError、ModuleNotFoundError、FileNotFoundError 等仍是任务内代码修订问题，不因异常名称自动升级为系统依赖问题。真实宿主异常使用独立的可信来源标记。取消继续以 ImportCancelled 传播；Codex bridge 和受控 reuse 路径保存 cancelled，系统停止保存 needs_input，不能被辅助包装器改回 investigating。

以上新增决策仍使用默认关闭的 trusted opt-in；没有修改当前服务配置或启用行为。运行效果待验证。

### 有限结构化资料兼容

复用已有 source_knowledge.metadata_projection、semantic_diff 和严格 JSON 抽取器。仅支持精确官方 CKAN `/3/action/package_show`，校对 URL dataset 标识与响应 id/name。允许：

- JSON 格式化、空白和对象 key 顺序变化；数组顺序不归一化。
- package 级 metadata_modified 在合法 ISO 时间戳之间变化。
- package 级 tracking_summary.total/recent 两个已有非负整数计数的变化。

先比较既有语义投影，再核对原始结构差异；后者不能省略，因为原研究投影还会忽略 revision_id 等不适合直接复用忽略的字段。未知字段、资源变更/重排、字段含义、主键、粒度、单位、CRS、coverage、revision_id 及任何未列出的变化均保守回退。差异超过有界报告范围也不得视作无变化。

不支持 HTML/PDF 排版等价，也不泛化到 Socrata/ArcGIS。保留新旧 raw SHA、规则版本、差异路径和新旧 document ID。已有 JSON Pointer 引用必须先在旧原文验真，再在新原文定位到完全相同的值，才换成新 document ID/hash；自由文本引用或值变化不能自动改写。新的 preflight/full QA 仍重新验证完整资料权威和适用范围。固定 hash 的 reviewed claim 规则不会被此兼容比较绕过。

上传数据绑定没有放宽成 schema/domain/AI 证明。当前唯一实现的自动绑定仍是精确官方 endpoint 导出 bytes 与上传 hash+size 一一匹配；历史版本或不同表示若缺少现有可靠绑定证据，保存 VERSION_OFFICIAL_BYTES_UNBOUND 和原因并回退。本轮不创建通用溯源框架；替代版本绑定仍是未完成限制。

新测试源码 `pipeline/tests/test_adaptation_static_fixes.py` 覆盖真实 Agent 执行包装（含 full 缺镜像）、Codex bridge terminal、生成代码导入错误、伪造来源标记、取消与持久化、CKAN 兼容/不兼容、引用换绑以及上传 bytes 无法绑定。**测试执行数为 0**，不能将测试源码当作通过证据。
