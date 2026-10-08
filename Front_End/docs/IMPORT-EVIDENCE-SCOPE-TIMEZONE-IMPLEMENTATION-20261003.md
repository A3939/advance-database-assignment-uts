# ARSIA：证据范围隔离与通用时区支持

日期：2026-10-03（Australia/Sydney）  
状态：待执行的开发任务书。本文件的编写仅包含源码、现有证据与官方资料的只读核查，没有开发、导入或测试运行。  
项目：`/Users/zhengpeixian/ZPX/UTS/Advanced Database/Assignment 2/Workspace/ARSIA`

## 1. 本轮目标、优先级和授权边界

本轮交付两个通用修复，随后进行一次有条件的 WA 自主接入复验：

1. **E：证据范围与错误隔离。** 无关研究资料不能破坏候选准入；相关的官方冲突不能因为 Agent 没引用而被忽略。
2. **T：通用时区解析。** 用有版本依据的 Windows/IANA 映射及时间语义验证，支持明确可证明的 ArcGIS Date 情形；不能按州名或固定偏移放行。
3. **V：独立验证。** 先离线复现、合成反例和保存候选的完整预检，再冻结代码，在新隔离空间由 Agent 重新处理原 WA 文件。

允许修改证据选择/图、相关预检、时区解析、必要的共享日期执行代码、可信实现清单、规则资源打包及直接相关测试。复用现有 evidence graph、独立 QA、runtime 和 Codex harness，不另建一套系统。

不扩展 G2、全州 adapter 库、新格式解析器、前端、数据库 schema 重构、存储清理或模型路由。上一轮启动隔离与 helper 修复保留；只做受影响检查，不重跑完整存储矩阵。

本文件对本轮范围及修正权限优先于旧任务书。不能借此取消独立 QA、XML 防护、原始字节绑定、范围/删除授权、隔离或发布门禁。

## 2. 开始前必读和已确认事实

读取：

- `artifacts/isolated-startup-20261003T055135Z/REPORT.md`
- 同目录 `ROOT-CAUSE.md`、`VERIFICATION.json`、`SOURCE-final.json`、`checkpoint.json`
- `WA/minimal-uncited-xml-repro.json`、`WA/minimal-timezone-repro.json`、`WA/contract-submitted.json`
- `docs/ARCGIS-REPRESENTATION-SUPPORT.md`
- `docs/IMPORT-RELIABILITY-AND-GENERALIZATION-20261003.md` 中仍适用的隔离、泛化及证据要求。

核对当前源码与检查点，保留其他线程修改，不覆盖旧候选和日志。

已经确认：

- `agent.py` 的预检、执行及验证相关路径会附加全部注册 documents。
- `trusted_qa._proof_checks()` 核验下载收据/内容字节后交给图构建。
- `evidence_graph.build_graph()` 在权限和相关范围确定前，对全部文档调用 `extract(raw)`。
- 未引用的 CLDR 研究 XML 含 DOCTYPE，触发 `METADATA_UNSAFE_XML`。这只说明它不满足现有安全解析策略，不能据此称该官方标准文件恶意。
- `metadata_extractors._xml()` 使用 `forbid_dtd/entities/external`；这些安全限制必须保留。
- `arcgis_query.timezone_for()` 目前只接受显式 IANA 或 UTC；WA 元数据为 `{"timeZone":"W. Australia Standard Time","respectsDaylightSaving":false}`。
- 保存候选的日期映射是 `epoch_ms`、`Australia/Perth`、day 精度；这是失败案例的事实，不是向新运行 Agent 提供的答案。
- `verify_response()` 按返回 epoch 值验证本地日期范围，`bind_uploads()` 对比合同时区，`canonical.py` 执行日期转换。这些路径必须语义一致。
- WA 上轮没有执行成功的样本、独立 QA、注册或发布。精确 CrashMap 许可仍未核实。不能把这两项技术修复视作所有前置条件已经满足。

## 3. 官方依据与适用边界

执行者需保存所采用资料的精确版本/访问收据；下面链接是研究入口，不是让运行 Agent 继承未经验证的业务声明。

| 资料 | 对本轮的作用 |
|---|---|
| [ArcGIS MapServer query：Date-time queries](https://developers.arcgis.com/rest/services-reference/enterprise/query-map-service-layer/#date-time-queries) | 普通 Date 字段的查询时区、返回时间及 Unknown 的区别；WA 是 MapServer，不能只引用另一个服务类型 |
| [ArcGIS FeatureServer query：Date-time queries](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/#date-time-queries) | 对应 FeatureServer 分支与字段级例外 |
| [Esri timeReference](https://developers.arcgis.com/web-map-specification/objects/timeReference/) | Windows/IANA 名称及夏令时属性的补充定义；它属于 Web Map 规范，不单独替代 REST 版本语义 |
| [Unicode LDML：Windows Zones](https://unicode-org.github.io/cldr/ldml/tr35-dates.html#Windows_Zones) | CLDR 默认及 territory 映射、别名和版本关系 |
| [Unicode 官方 JSON 映射入口](https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-core/supplemental/windowsZones.json) | 可审查的机器映射来源；部署时必须固定 release/commit，不能运行时追踪 main |
| [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html) | tzdb 加载机制；实施前核实宿主和执行镜像实际数据来源 |

ArcGIS 文档区分查询中的本地时间与通常以 UTC 返回的 Date 值；Unknown 情形另有语义。普通 Date、DateOnly、TimestampOffset、编辑追踪/时间感知字段不能混用同一规则。CLDR 提供名称映射，不证明某个事故数据集采用该时区。数据集适用性仍来自精确官方元数据。[MapServer 依据](https://developers.arcgis.com/rest/services-reference/enterprise/query-map-service-layer/#date-time-queries)

## 4. E：证据范围隔离的实现路径

### 4.1 三层职责

区分：

1. **研究目录**：Agent 找到的资料、收据和诊断；存在于目录不授予权威。
2. **本次证据选择**：宿主根据合同、来源、资源及可证明依赖选出的相关文档。
3. **准入证明**：相关文档经安全解析、授权、声明和原始表示核查后产生的证明。

复用原文档存储，不另建数据库。Agent 可以提议引用，但不能自行将冲突文档标为 research 以逃避检查。CLDR 标准映射也不能据此获得事故字段、许可或来源证明权。

### 4.2 建议算法：收据索引、受限解析、相关闭包、错误判定

在现有模块中实现；可增加一个小型纯函数模块，避免同时维护多套选择规则。

**A. 建立有界收据索引。**

- 从可信宿主收据取得 document ID、原/最终 URL、重定向、内容 SHA、来源及读取边界。
- 保留现有路径、SHA、大小和数量限制。坏收据不能悄悄变为有效证据；隔离/系统错误不能被当作普通无关文档错误吞掉。
- 文档角色不能由上传者或 Agent 的标签单独决定。

**B. 确定候选相关集合。**

- 纳入合同所有声明引用的 ID，不只 source_identity 引用。
- 纳入实际输入资源、精确查询表示、匹配 layer/service 定义及已有可信关系所需文档。
- 纳入已注册、可确定属于同一资源及适用版本的官方定义和冲突候选，即使没有被引用。
- 沿现有明确委托、service→layer、layer↔query 等有类型关系扩展；不是同域名或路径前缀就自动相关。
- CKAN 目录、搜索结果、委托 CDN、RDF 规范依赖继续用原有规则。不为了排除 CLDR 而只允许 `.gov.au` 文档。

**C. 每文档安全解析，相关闭包完成后决定错误影响。**

部分依赖需要读取元数据才能发现，可采用分阶段/惰性解析，或逐文档保存解析结果/错误后再完成相关闭包。只捕获预期的文档解析异常，不宽泛捕获取消、超时、内存/编程或系统异常并继续发布。

- 与当前来源无关、未被引用、也不是受审查规范依赖的研究文档：保留隔离诊断，不影响其他证明，不获得图中的授权。
- 被引用、作为必需依赖、精确资源定义或相关官方冲突检查对象的文档：解析失败必须阻断或明确声明未能完成该门禁。
- 一份文档初步无关、后因可信委托边关联到当前资源时，其已有解析错误必须升级为阻塞。
- 无法确认相关性且缺少必要关联证明时报告具体缺口，不得默认“无关所以跳过”。
- 不能只删除 CLDR 文档、按 URL 黑名单绕开，也不能对 `METADATA_UNSAFE_XML` 全局 catch 后继续。

**D. 复用原有授权及适用性验证。**

选择不等于授权。沿用 `build_graph`、`evidence_scope`、grounding、表示绑定和引用校验；保留同源矛盾、字段/粒度、CRS 和更新范围判定。时效较新、同域或抓取成功不能覆盖冲突。

### 4.3 审计和一致性

保存稳定排序的选择清单：document ID/SHA、角色、选择或排除理由、依赖边、解析状态、阻塞影响和规则版本。无关研究资料的错误可见，但不能与必需官方证据缺失混为一谈。

预检、sample/full QA、注册前复核使用同一选择规则。研究诊断与实际准入证明分开保存；增加无关文档不应改变发布内容身份或制造新 release。它可以改变研究日志，不得赋予新发布权限。

对需要 Agent 修正的缺口返回具体文档和声明；对宿主解析/配置缺陷返回系统诊断，避免要求 Agent 反复找同一证据。

## 5. T：通用时区支持的实现路径

### 5.1 规则资源与业务证据分开

采用固定版本的 Unicode CLDR Windows→IANA 数据，优先从官方 JSON 生成/保存受审查的本地资源。记录 release/commit、原文件 SHA、派生文件 SHA、许可和生成方式；不要只抄写 WA 一项，也不要每次导入现场下载映射。

CLDR XML 的 DOCTYPE 不需要通过放宽业务 XML 解析器解决。标准规则资源是部署依赖，研究下载资料是任务输入，分开处理。

新增解析器及映射文件必须进入 `trusted_qa.TRUSTED_FILES` 或等价可信指纹，并验证实际打包/部署可用。规则变更应使旧准入重新验证，不能静默沿用旧 QA。

固定或可核验使用的 tzdb 版本/实际 TZif 内容身份；宿主协议校验、独立原行校验及 Docker 内 adapter 日期计算必须一致。不要依赖“宿主能找到 ZoneInfo，所以镜像也一定相同”。若需依赖变更，只加入本功能必要的依赖与打包，不无关升级。

### 5.2 单一解析结果，多个消费者

建议 `resolve_time_reference(metadata, field, service_kind, context)` 返回结构化结果，并由现有 `timezone_for()` 等入口兼容调用。至少记录：

- 原始 timeZone/timeZoneIANA 和具体元数据定位；
- 标准化 IANA 名称、映射来源/版本/哈希、territory/default 选择理由；
- respectsDaylightSaving 的原值和采用规则；
- 数据字段类型、返回值解释、字段级覆盖状态；
- 规则适用日期区间或明确限制、tzdb 身份；
- resolver 版本和诊断。

不得让协议检查、合同检查和 canonical 日期转换分别猜测时区。

### 5.3 名称选择与冲突

1. 有合法显式 IANA 时保留该语义；名称或别名按所固定的 tzdb/CLDR 规则验证，不按字符串相似度处理。
2. 只有 Windows 名称时，通过标准映射解析；默认使用 CLDR 的 `001` 默认映射。只有具备可信适用证据并已定义政策时才采用 territory 映射，不从文件名/州简称猜地域。CLDR 定义了默认与地域映射，这不是某州的人工例外。[LDML 依据](https://unicode-org.github.io/cldr/ldml/tr35-dates.html#Windows_Zones)
3. 同时存在两种有效声明时检查一致性；无效或矛盾的显式声明不能被另一项静默覆盖。
4. 不以“当前 UTC 偏移一样”认定两个地区历史时区等价。别名处理使用标准数据；超出已证明历史适用范围则明确限制。
5. 未知 Windows 名称、`Unknown` 标志、坏类型和无法解释的声明继续拒绝；不能默认为 UTC。
6. `dateFieldsTimeReference` 缺失/null 的协议默认语义与明确 Unknown 分开。保持已验证 UTC 分支，并按服务类型及官方依据测试。

### 5.4 夏令时必须处理

WA 的实际 `respectsDaylightSaving=false` 是本轮必须覆盖的通用分支，不能只增加 Windows 名称映射后忽略它。

- `true`：按经过验证的时区历史规则处理，不使用常数偏移。
- `false`：不能无条件把它交给一个会在该数据时期采用夏令时的 IANA 时区。
- 首版可保守限定：仅在能够证明候选区间内既有日期转换与“不采用夏令时”语义一致时支持；否则返回明确 unsupported。证明须覆盖实际行及查询边界所需区间，不能只看今天、一个样本或随意按日抽样。
- 如果确需新增标准时解释模式，必须有协议依据、独立预期和执行/QA一致实现；时间不够则报告支持边界，不用 WA 特判赶进度。
- 缺省、null、非布尔值各自有明确政策。核实准确服务/版本的缺省语义，不将 Python truthiness 当协议规则。
- 跨 DST 切换、重复/不存在本地时间应有测试。UTC 瞬间转本地日期是确定操作；若新代码需要反向解释无偏移本地时间，则必须识别歧义，不能默选 fold。

### 5.5 返回时间、查询范围及映射一致

现有普通 `esriFieldTypeDate` 返回值按 UTC epoch milliseconds 解析，再按已证明时区求业务日期；不能把 epoch 先当本地时间再偏移一次。查询中的本地半开日期区间和 canonical 日期必须一致。[ArcGIS 查询说明](https://developers.arcgis.com/rest/services-reference/enterprise/query-map-service-layer/#date-time-queries)

接入点至少核查：

- `arcgis_query.timezone_for()`、`verify_response()` 和 `bind_uploads()`；
- `canonical.py` 的日期投影及对应 adapter/独立原行验证；
- 证据证明中时区规则身份、QA 缓存/注册失效及发布语义边界。

普通 IANA 字符串合同可保持兼容；如当前合同不能表达某种标准时模式，明确拒绝该模式，不任意扩 schema。编辑追踪/time-aware override、DateOnly、TimestampOffset 等原 unsupported 边界继续保留，除非本轮必需且有单独完整依据，不默默放行。

新增无关研究资料、无语义差异的规范名称表示不能单独制造新发布内容；真实业务日期或适用范围变化则必须反映在输出和发布身份中。现有内容判重无需借机重写。

## 6. 必须执行的无模型测试矩阵

这些是行为条件，不要求一行一个测试函数；不得以测试数量替代覆盖。独立预期不要调用被测 resolver 后再把其输出当答案。

| ID | 验证条件 |
|---|---|
| E01 | 合法候选添加未引用 CLDR/无关损坏 XML，结果不被污染；诊断保留 |
| E02 | 将同一不可安全解析文档作为必需引用，必须拒绝；DTD/entity 外部访问仍禁止 |
| E03 | 未引用但适用的同资源官方冲突仍阻断；research 标签不能隐藏冲突 |
| E04 | 原先无关文档经真实委托边成为必需依赖后，其错误不能被遗漏 |
| E05 | 委托 CDN、RDF 规范关系不因“非政府域”被一刀切删除；规范文档不获得业务权威 |
| E06 | 相邻层、相似 URL、CKAN 搜索邻居不能获得本资源权限；查询参数/字节绑定保留 |
| E07 | 重排研究资料不改判定；增加无关资料不制造 release；各阶段选择规则一致 |
| E08 | 恶意/超限 XML、损坏 JSON、取消/超时及基础完整性错误分型正确，无宽泛异常吞噬 |
| T01 | 多个 Windows 映射：覆盖非 DST、DST、半小时或四十五分钟时区，至少一例澳洲以外 |
| T02 | UTC、合法 IANA、Windows 默认映射、受支持别名；非法和矛盾声明拒绝 |
| T03 | respectsDaylightSaving=false 在适用区间可证明时通过，不可证明/冲突时明确拒绝 |
| T04 | UTC/local 跨日、跨月、半开区间端点、DST前后；不发生双重偏移 |
| T05 | Unknown、字段级 override、DateOnly 等未支持分支保持准确拒绝 |
| T06 | 时区映射/tzdb 资源缺失、损坏或版本改变不能悄悄使用旧准入或不同机器默认 |
| T07 | 宿主与实际隔离执行器对日期有相同结果；独立 oracle 对错误日期能拒绝 |
| X01 | 与 WA 无关的合成来源组合 E/T：改变域、layer、字段名、日期、数量仍使用同规则 |
| X02 | 错时区造成日期偏移的候选不能通过完整 QA/注册/发布；当前 release 保留 |

保留原引用/graph/scope/grounding、ArcGIS、日期、独立 QA 和内容身份的受影响回归。旧三项 category fixture 失败先核对基线、单列；不因此扩大为修复所有旧测试，不忽略新回归。

## 7. 保存候选的离线预检：先消除已知阻塞

在本轮空间复制必要证据并保持哈希/来源收据，或经允许的只读接口读取旧材料；不得改旧合同、receipt 或 SHA。冻结 private oracle，记录当前候选来源为开发案例。

离线步骤必须同时提供真实上传文件与匹配的已保存查询响应、官方 layer 元数据及文档收据，执行实际预检链；不能只重跑 `_proof(... files=None)` 的语义子集就称上传准入通过。

分别记录 E 修复后、T 修复后及组合后的 pass/fail/not_checked。保留未引用 CLDR 研究文档，证明是范围规则生效，不是手工删掉问题文件。

两个已知阻塞均消除且安全反例通过，才允许真实 Agent。若出现新的确定性业务阻塞，本轮做最小定位、记录剩余项并暂停；不要明知预检不可能通过仍调用模型反复调查。

本轮离线预检可以使用历史候选定位，但该候选/adapter/诊断答案不得进入接下来的新 Agent 工作目录或上下文。

## 8. WA 自主复验与准入结论

使用同一份官方 WA January 2023 文件，1,769 条，SHA：

`d28aecf592b55b988e9d1de8da8b2949a78725c24959d73d11c222926968f400`

它已经是参与修复的开发来源；本轮名称应为“通用证据/时区修复后的 WA 自主复验”，不能称新的盲测。未来仍需未参与修复的来源/版本验证迁移能力；本轮不为扩大范围另抓一个州。

1. 新建显式隔离空间和空 admitted recipe/registry，使用 `arsia_pipeline.runtime` 公共入口，先在真实新 worker 进程运行启动预检。
2. 保留研究知识命中记录；不给 Agent 上轮合同、adapter、私有 oracle 或预期日期映射。标准时区支持作为通用工具能力可提供。
3. 冻结生产代码、规则资源、镜像、工具及输入/预期。原始文件不删行、不改字节、不以模型输出调整 oracle。
4. 沿用批准的模型路由/推理强度、已有无进展与系统停止机制。Agent 可以自行调查、编写及修订任务内 Python adapter；无权限修改 QA 或映射规则库。
5. 首次成功必须取得样本和全量独立 QA、注册、发布、查询及原行 oracle。核对成员/键/日期/严重程度/已定义指标/坐标/未知值和更新范围，不能仅比行数。
6. 成功后原名、改名同字节重传，各自 fresh 必需 QA 与注册审计，期待 `no_change` 且 batch/release 不变。增加无关研究资料的发布身份回归可用合成受控案例，不必再开一个模型任务。
7. 精确资源许可状态如实记录，按既有来源政策处理。不继承另一个 DataWA 数据集许可；不为本轮新增绕过或临时许可断言。若该项阻断，分别报告技术预检与最终准入状态。
8. 无发布前不得声称查询/no_change通过。正确拒绝是边界验证，不是成功接入。

## 9. 时间、有限修正与停止

整轮最多 **180 分钟**，不是要求用满。建议：基线/复现15分钟；E实现与测试50分钟；T实现与测试50分钟；组合/离线预检20分钟；模型任务最多20分钟；其余25分钟用于重复导入、保护核查和报告。阶段超时挤占后续，不重置总时钟。

- 开发和无模型预检阶段可修复两个目标及直接工具问题，每根因最多两次修正；不再因一个已定位的取证错误立即交接。
- 生产代码冻结后，只允许有界工具修正，不能更改语义、输入或 oracle 迎合输出；每版失败和哈希均保留。
- 正式 WA 最多一个自主 job，现有早停规则优先，最长20分钟。job 内正常 adapter 修订允许；开发方不得额外不断重开或换来源。
- 新的证据/时区规则之外的业务框架缺陷，记录并暂停，不扩展覆盖所有协议。
- 发现隔离失败、误发布、误删、错误归属或安全验证退化立即停止重任务，保存现场。
- 预留至少10分钟安全收尾；时间不足时不启动模型任务。没有周期监控或自动续跑。

## 10. 资源保护与最终交付

本轮使用新 `artifacts/evidence-timezone-<UTC>/`；不修改正常网站/默认绑定/主库，不动旧 catalog、预留、pin 和原始资料，不部署或推送。外部旧 Docker 清理已由用户解释，不调查、不恢复。

完成后停止本轮自有 worker、模型子进程及容器，保留必要证据；按已有生命周期收尾，不借本轮清理历史资源。

至少保存：

- `REPORT.md`：E/T、离线预检、WA各自结论及限制；
- `VERIFICATION.json`：E01–X02、原失败和未执行项，绑定源码/规则/镜像身份；
- `EVIDENCE-SELECTION.json`：选择、排除、隔离、冲突和错误影响；
- `TIMEZONE-POLICY.md`、`TIMEZONE-PROOFS.json`：映射选择、DST政策、日期范围、CLDR/tzdb身份和未知边界；
- 官方规则资料收据、许可证、生成方法、代码补丁、冻结/最终哈希；
- 离线真实上传绑定结果、独立 oracle、Agent原始trace、QA、发布查询与重复结果；
- `TIMING.json`、`USAGE.json`、精确资源/停止清单、保护核查；
- `checkpoint.json`：paused、剩余阻塞、必要恢复入口。

区分模型调用累计时间与墙钟；缓存输入是输入子集，开发助手用量另计。原主库不可连接时继续 `database_content_comparison=not_verified`，文件哈希不替代内容比对。

最终暂停，不自动下一轮，不提交或部署。没有活动 goal 就保存 paused 检查点，不冒称整个 general pipeline 已完成。

## 11. 执行入口 prompt

> 请在 ARSIA 执行 docs/IMPORT-EVIDENCE-SCOPE-TIMEZONE-IMPLEMENTATION-20261003.md。先核实基线，完成通用证据范围隔离与 Windows/IANA 时区支持及安全反例，再做包含真实上传绑定的离线预检；通过后在新隔离空间进行一次 WA 自主复验和成功后的 no_change 验证。严格保持 XML 防护、相关官方冲突检查、独立 QA 和资料适用性边界，不为 WA 写特判或人工 adapter。整轮180分钟上限，按文档有限修正，保存全部结果并安全暂停。不要重做存储建设、扩展 G2、提交、推送或部署。
