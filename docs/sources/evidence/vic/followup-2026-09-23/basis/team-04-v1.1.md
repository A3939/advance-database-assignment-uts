# 团队协作、接口与验收

**协作合同 v1.1 · 2026-09-14 · 待成员实现。** 本文固定共同输入、输出与判定依据；实际函数及代码由成员编写。官方来源和课程未决项见§8，不预写批准或运行通过。

全员先读§1；按负责接口读§2；共同核对§3–5；交接使用§6–7。类型及约束见[02](02-数据库字段字典.md)，来源规则见[05](05-来源与映射说明.md)。

## 1. 主责与协作方式

| 成员 | 主责及来源调研 | 直接使用方 / 复核人 | 第一份交接成果 |
|---|---|---|---|
| A | 环境、全部17表迁移/权限、Vault五表。调研NSW两资源。 | 环境交B，Vault交C；B/C复核，E查约束。 | 空库证据；按共用投影合同加载一事故一单元。 |
| B | 原生读取/归档、来源/资源登记、raw、manifest；唯一运行入口、连接、锁、提交/回滚、失败留证。调研VIC Accident/Vehicle。 | 原始输入交C；A/E复核生命周期。 | 七资源传输合同和小样本；对接已登记的模块调用。 |
| C | SQL投影、Person/Node检查、Canonical两表、来源语义。调研VIC Person/Node。 | 投影交A，Canonical交D；A/D复核。 | 类型化行合同；与D逐行核对共用样例。 |
| D | 三维一事实、分析SQL、一个本地界面。调研QLD。 | 报表交全组；C核口径，E核结果。 | 按固定返回结构展示手算样例，再接SQL。 |
| E | QA协议/汇总、发布门槛及当前指针、集成验收、课程证据索引。 | 门槛交B，摘要交D；B/C复核。 | 必查对象集合和缺检查反例；统一证据格式。 |

A维护迁移文件，表所属模块作者提出修改并复核。B写meta来源/资源、running登记及失败状态；E的发布模块写succeeded和current_release。QA生产者按§3写结果，E不代写全部检查。**所有构建模块共用B提供的连接，只有B提交或回滚。** 每人负责本人代码、解释、测试和修复；A完成环境后协助C的历史/关联。来源负责人填05，C统一口径，D复核指标，E登记状态。

| 共用事项 | 工作规则 |
|---|---|
| 环境 | 一个PostgreSQL 16业务库，UTF-8、会话时区UTC，Docker Compose隔离，Python 3.12。A/B在P0锁定实际镜像摘要、补丁版和Python依赖，记录复现命令；不要求PostGIS、独立API或认证界面。 |
| 结构维护 | 02/03是设计基线；实施后A维护的编号迁移和字段注释是实际结构权威。一次变更同步迁移、字典、图及受影响接口；不改已应用迁移，不由辅助JSON反向覆盖。 |
| 文件责任 | A：environment、sql/migrations、sql/vault；B：ingest、runner；C：sql/project、sql/canonical；D：sql/dw、sql/analysis、ui；E：sql/qa、sql/publish、验收索引。以上为待团队建立的代码位置，包内未提供实现。config按来源分文件，B维护公共格式。 |
| 变更与集成 | 每次一个短分支/PR；直接使用方复核后合并。字段、NULL、身份、粒度、错误结果或指标含义变化，先共同确认并更新合同/样例/调用方。主分支保持可运行小链路，不等全部模块写完才联调。 |
| 权限 | migration建改结构；loader加载/发布；reader只通过受控查询读取成功批次，不能写表或读running/failed候选。历史成功批次可读；A实现、E做拒绝反例。 |
| 沟通 | 每次工作结束记录“已交付证据 / 下一接口 / 阻塞项及需要谁”；阻塞当天告知使用方。每周至少一次全组运行小链路。贡献和会议记录随工作维护。 |

允许手工构造接口输入以并行开发，但端到端验收必须从原生CSV/XLSX样例走完整入口；模块测试不能替代它。

## 2. 六项交接合同

L0–L5是逻辑编号，不是已安装函数。首次联调前，提供方登记实际调用名、参数类型、返回字段及代码位置，使用方复核；未实现调用不得宣称可用。

### L0 环境：A → 全组

交付空库安装入口、依赖锁定、迁移顺序/摘要、角色连接方式及冷启动记录；密钥不进代码或证据。安装后17表/129字段/30外键；额外来源视图另列。B能加载合成输入，D能读成功结果，E验证reader写入及候选读取失败。只能清理本人测试库，不直接清空团队共享库。

### L1 固定原始输入：B → C/A/E

每行传输固定为 `source_id、resource_id、file_sha256、parser_version、row_locator、payload`；SQL接收后返回 `raw_record_id`。同去重键须复用ID且payload完全相同，否则block。一次包含启用来源要求的全部资源，数量不写死三州七文件。原生空串/NULL及定位见05。

| manifest字段 | 类型与必填内容 |
|---|---|
| 根对象 | contract_version:string=`team-v1.1`；dataset_kind:official/synthetic；analysis、sources、files、rules、required_checks、provenance。未知根字段拒绝，扩展先改合同。 |
| analysis | year_from:int、year_to:int；包含两端、前者≤后者，默认2020–2024。 |
| sources[] | source_id、jurisdiction_code、source_name、publisher、release_label、release_scope为文本；resource_ids为文本数组。每来源每批只选一组兼容发布；发布标签不由接入时间伪代。 |
| files[] | source_id、resource_id、resource_role、entity_kind、file_sha256、parser_version、locator_version、format为文本；encoding、sheet为文本或NULL（XLSX编码NULL、CSV工作表NULL）；header_row为整数1，header为有序文本数组；raw_count为非负整数。本版每资源选一个完整快照文件。 |
| rules | 每资源contract全文/版本、各引用mapping全文/版本、severity定义、qa_contract全文/版本、code_files和schema_files的“相对路径+SHA256”清单。声明数量、覆盖范围及快照变化依据属于contract。 |
| required_checks | §3七个完整rule_id，按编号排列；不能删除必需组。具体对象集合由§3及本批来源/文件/年份独立推导，不能由输入漏项降低门槛。 |
| provenance | prepared_at、prepared_by、每资源/哈希的archive_relpath、原下载链接、原文件名及证据定位。时间UTC ISO 8601；保留按哈希找原件的能力。 |

source_id/resource_id只用ASCII字母、数字和下划线，首字符为字母；parser_version等协议版本限字母、数字、点、下划线和短横线。official/synthetic使用不同ID、目录、batch及current_release，不能只靠文件夹名隔离。

**指纹协议FP1**：输入为manifest去掉整个provenance后的对象。sources按source_id、resource_ids按ID、files按resource_id排序；合同/映射清单按ID、代码/结构清单按相对路径、severity按source_id和severity_code排序；表头、键组件、转换顺序等有语义的数组保持原序。拒绝重复JSON键、重复清单ID及非有限数；配置小数用十进制字符串，年份/计数用整数。

E定义并测试、B调用唯一SQL侧指纹操作：整理后的对象转为PostgreSQL 16 jsonb文本，对其UTF-8字节计算SHA256，输出64位小写十六进制。Python不独立拼另一种JSON文本计算数据库指纹；文件字节哈希仍由B计算。序列化版本属于FP1环境条件，升级时重新确认。

指纹包含合同/映射全文及版本、来源展示定义、QA协议、构建/发布/指标查询代码与结构摘要、模式和年份；不含batch UUID、开始时间、随机raw UUID、本机路径或自身摘要。代码按实际文件字节哈希，清单不含日志/证据/纯文档。仅匹配**当前同模式成功批次**才no_change；换目录不重建，改变规则要重建，命中历史批次不回切。

归档、raw和running登记先独立提交。登记前的坏文件/表头错误写带run_id的文件记录，batch_id可NULL；尚无batch不能伪造QA数据库结果。

### L2 类型化投影：C → A；辅助检查：C → E

构建事务内产生会话临时行集 `I_crash`、`I_unit`（逻辑称呼，不是提供的代码），结束后不作为恢复点。

| 行集 | 固定结构 | 必须保证 |
|---|---|---|
| I_crash | canonical.crash全部24字段，同名、同类型及NULL规则；一批/来源/发布范围/事故一行。 | 显式提供每个字段，不以默认值掩盖漏映射；身份、主raw、日期精度、资格/原因完整。 |
| I_unit | canonical.unit全部11字段，同名、同类型及NULL规则；一完整真实单元一行。 | 单元键含父事故键；同批/同源/同发布关联；不造QLD单元。 |
| Person/Node观察 | 只保留raw；运行时可投影完整事故/人员/车辆/节点键、位置候选及raw定位。 | 空引用与非空孤儿分开；Node重复和冲突见05，不增加持久分析表。 |

先建立原生事故父键全集，再筛发生年。范围外子记录留raw并记排除数量；找不到父事故的记录不能伪装“范围外”。事故/单元业务键重复一律block，不静默取第一行；raw同定位幂等复用不属于业务重复。

### L3 分层加载：A/C/D → E

A把投影身份写Hub、观察写Satellite、父子写Link。Satellite `attributes` 固定为对应Canonical行除batch_id、source_id、release_scope、其自身业务键、raw_record_id外的字段；unit的attributes仍包含crash_key。空字段显式JSON null，数值/布尔用对应类型，日期YYYY-MM-DD、UUID文本。可另有 `source_extra` 保存原声明数量、原节点键及来源差异，不覆盖固定字段；新增属性先改合同版本。

C必须从选定Satellite读取这些字段写Canonical，主raw定位一致，不绕过Vault另算一份。location_record_id必须属于本批选中文件并匹配正确事故/节点；FK之外的血缘由SQL检查。各模块不自行提交。

D逐行复制Canonical同名事实字段，以可信年月生成month_id。dim_source取冻结manifest，dim_severity取完整来源分类定义（含未出现类别及缺失类别），同来源代码不能对应两套定义。dim_month生成配置年份全部月份、跨批复用；未知月份不补1月或“未知月”。

成功Satellite/Canonical/事实和manifest不可原地改写；共享月份可追加。Canonical事故与事实逐行一一对应；单元停留Canonical。A的权限与各模块共同保证只增历史，测试不得只核对总行数。

### L4 QA与提交：E → B

B用同一会话持有全生命周期session advisory lock，双整数标识固定 `(32113,2)`，两模式也互斥。忙时立即busy，不登记batch。短事务登记之后才开始构建事务；E核对§3结果，写succeeded和current_release，返回B后由B一次提交。不能使用登记事务结束即释放的锁。[PostgreSQL锁说明](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS)

| 运行器result | 返回内容 / 退出码 | 数据含义 |
|---|---|---|
| succeeded | run_id、dataset_kind、batch_id、input_fingerprint、previous_batch_id、qa_summary、evidence_ref；0 | 各层、成功状态及指针已同事务提交。 |
| no_change | 同上，batch_id为既有当前成功批次；0 | 无新batch/事实，不改switched_at。 |
| busy | run_id、dataset_kind、reason，batch_id=NULL；2 | 未获锁，无构建副作用。 |
| failed | run_id、dataset_kind、batch_id或NULL、stage、error_code、message、evidence_ref；1 | 确认未提交后回滚，另开短事务记failed。 |
| unknown_commit | run_id、dataset_kind、batch_id、evidence_ref；3 | COMMIT应答丢失且未查明，不能直接重跑/改记失败/宣称成功。 |

数据库status仍仅running/succeeded/failed；上表其余值是运行器结果。失败依据含stage、error_code、message、rule_id/object_key（如有）、原始定位、实际/预期和UTC时间。模块先把诊断传给B，B在回滚后独立留证；DB不可用先写错误文件，恢复后核对再补记，不能依赖已回滚的QA行。

新会话获锁后先处理遗留running：确认其未成功提交才结束失败登记，并新建批次整批重试，不恢复中间阶段。旧批次已succeeded时，即使当前指针后来更新，也不能误改failed或回切。查询状态才能解除unknown_commit。

### L5 固定版本查询：D → 界面/E

参数：dataset_kind、一次解析得到的成功batch_id、source_ids、year_from/year_to、可选month_from/month_to（1–12，包含两端）。来源及年份须在manifest范围内，否则参数错误。无月筛选时年度包含月份未知事故；有月筛选时只保留已知月份且符合范围者。本版不提供跨来源通用严重度筛选。

| 结果 | 固定返回字段及粒度 |
|---|---|
| 共用上下文 | contract_version、dataset_kind、batch_id、各来源release_label/definition_version、实际筛选条件、quality_limits；所有结果同一batch。 |
| 趋势 | 每source_id+year或source_id+year+month：crash_count、fatal_crash_count、fatality_count、casualty_count、fatal_crash_known_count、fatality_known_count、casualty_known_count、month_known_count。known_count为对应资格true的事故数。 |
| 严重度 | 每source_id+definition_version+severity_code：severity_label、crash_count；仅返回有事故组，缺失用__MISSING__，不跨来源合并代码。 |
| 地图 | 点：source_id、release_scope、crash_key、latitude、longitude；同坐标不同事故保留身份。摘要按来源及所选合计返回crash_count、map_count、unmapped_count、map_coverage、map_coverage_pct。 |
| 基础单元 | 每source_id+statistical_scope+unit_type_code返回unit_count，只计count_eligible=true；不与事故直接JOIN后求事故指标。 |

事故数按事实行计；死亡事故数仅计资格true且is_fatal_crash=true；人数只合计各自资格true的值。known_count=0时指标NULL，有合格记录而合计为零才返回0。跨来源人数默认分来源，只有定义确认可比才总计；§4合成数据明确采用共同虚构定义。

有依据覆盖的时段无事故，crash_count=0；未声明覆盖时段为NULL并标not_covered，不能补零。月度不造未知月，摘要显示month_known_count及排除数。map_coverage=map_count/crash_count，分母0为NULL；SQL同时返回百分比map_coverage_pct，四舍五入两位，界面不重算。

首次无成功版本返回no_publication和空结果；刷新才重新取指针，一页所有SQL绑定原batch。SQL拒绝未成功或模式不符的batch。

## 3. QA具体对象与发布门槛

文件对象键 `file:<resource_id>:<file_sha256>:<parser_version>`；资源 `resource:<resource_id>`；来源 `source:<source_id>`；来源年 `source_year:<source_id>:<YYYY>`。每组另有object_key=batch汇总。来源年按全部启用来源×配置全部年份生成，零事故年份不能省略。

| rule_id / 生产者 | 必需具体对象 | pass要求及处置 |
|---|---|---|
| QA01_INPUT / B，各来源负责人供依据 | 每个files成员 | 文件齐全、哈希/表头/格式/parser/兼容发布一致；未知操作、draft官方合同、未说明的快照减少或覆盖缩减block。 |
| QA02_RAW / B | 每个文件 | 原生行数=raw_count；字段/值/定位/去重一致；缺行、多行、漏字段、同定位异payload block。 |
| QA03_PROJECTED / C，A复核 | 每个crash/unit资源 | 键唯一有效、日期/类型/计数正确、范围投影数正确、同源同版关联；错误核心值/孤儿/JOIN放大block。坐标不可用交QA07，不丢事故。 |
| QA04_AUXILIARY / C | 每个unit/person_raw/node_raw资源 | 单元与人员父键、Person非空车辆引用、已确认同口径声明数量对账；孤儿/无依据差异block。Node重复本身不block，记录组数及冲突；按05合规隔离地图交QA07。 |
| QA05_SEMANTICS / C，来源负责人复核 | 每个来源 | 定义、覆盖、缺失码、分类、指标资格及原因有版本依据；新非缺失分类/未知业务定义block；已明确缺失规则的个别NULL可通过。 |
| QA06_RECONCILIATION / D，C/E复核 | 每个来源年 | Canonical与事实事故键集合、同名字段、资格逐行一致；人数/死亡事故/各known_count汇总差0；主raw/位置血缘与定义版本正确。仅等总数不足。 |
| QA07_LOCATION / C，D复核摘要 | 每个来源年 | 资格true有非空有效坐标、非空正确CRS、正确位置定位及一致性依据。全可定位或零事故pass；合规隔离缺失/冲突limited；无依据仍放行、丢事故或伪造CRS block。 |

结果按02写入。actual对象固定 `evaluated_count:int、violation_count:int、metrics:object`；expected固定 `evaluated_count:int、violation_count:int、metrics:object`，其中expected.violation_count=0。实际检查量须达到冻结预期，不能少检查几行后通过。metrics键如下；不适用项为NULL并在evidence说明，不伪造0。

| 规则 | actual.metrics固定键 / expected.metrics判定 |
|---|---|
| QA01 | hash_match、header_match、bundle_confirmed、contract_confirmed：均为boolean，预期均true。 |
| QA02 | raw_count、distinct_locator_count、payload_mismatch_count：预期分别为冻结raw_count、同值、0。 |
| QA03 | input_count、excluded_count、projected_count、duplicate_key_count、orphan_count、invalid_value_count：input=raw_count；projected=input-excluded；后三项0；excluded按有父事故的范围规则独立核对。 |
| QA04 | orphan_count、nonblank_unmatched_count、declared_count_delta、duplicate_group_count、coordinate_conflict_group_count：适用的前三项0；Node后两项是观察数量，expected为NULL表示不要求为0，但必须在证据列明并交QA07处理。不是通用跳过检查开关。 |
| QA05 | undefined_category_count、unconfirmed_definition_count、eligibility_error_count：预期均0；合同已声明的缺失不算新分类。 |
| QA06 | missing_fact_count、extra_fact_count、field_mismatch_count、lineage_error_count、definition_error_count、crash_delta、fatal_crash_delta、fatality_delta、casualty_delta、fatal_crash_known_delta、fatality_known_delta、casualty_known_delta：预期均0；NULL按双方是否同为空检查，不直接相减后忽略。 |
| QA07 | crash_count、map_count、unmapped_count、invalid_eligible_count：crash_count=该来源年事实数；map_count+unmapped_count=crash_count；invalid_eligible_count=0。前两项的预期由独立位置观察判定，不照抄被验结果。 |

batch汇总metrics统一为object_count、pass_count、limited_count、block_count、missing_count；object_count须等于应有具体对象数，block/missing均0。汇总evaluated_count为具体对象数，影响量只汇总具体结果，不把汇总自身重复相加。qa_summary返回七项rule_id、result、affected_count，供B/D使用。

evidence固定 `reason_codes[]、resolution、references[]、producer_version`；references含资源、哈希、row_locator及可得的raw_record_id。大量异常可指向带SHA256和总行数的明细文件，不能仅给无计数截图。证据文件路径由B按运行上下文提供，C/D/E不自建彼此不兼容的定位方式。

pass的affected_count=0；block记违反规则的不同对象/行数。QA07 limited的affected_count为无地图资格的不同事故数，violation_count=0表示没有错误放行地图点；逐事故须有原因。只有QA07允许limited。零事故覆盖NULL且pass，不伪造100%。

E独立推导应有对象集合，先查完整性，再汇总：任一block→block；否则有合法QA07 limited→limited；否则pass。缺失/未执行不得补pass，汇总不替代具体结果，额外检查的block也阻断。无适用对象的组仍写batch汇总，说明集合为空。每个成功批次结果只写一次，不覆盖“改绿”；失败重试新batch。七个汇总及全部应有对象同时符合才能发布。

## 4. 共用手算样例S0（设计预期，尚未执行）

这是虚构语义的synthetic样例，不确认官方代码/CRS。source_id为syn_nsw、syn_vic、syn_qld；资源S1–S7依次对应05中T1–T7角色；release_scope=s0。每个来源均使用事故原生ID 0001/0002，验证不跨源合并。N/V/Q只是阅读别名。每来源定义F/I/N/__MISSING__四类：F死亡、I/N非死亡、缺失未知，definition_version=syn-1；三来源样例指标定义可比。2020–2024全部年月有覆盖。

| 别名 | 来源/原生ID | 时间 / 精度 | 类别 | 死亡事故 | 死亡人数 | 伤亡人数 | 地图资格 / 坐标 | 单元数 |
|---|---|---|---|---|---:|---:|---|---:|
| N1 | syn_nsw/0001 | 2020-01 / month | F | true | 2 | 3 | true / -33.8600000,151.2000000 | 2 |
| N2 | syn_nsw/0002 | 2020 / year | __MISSING__ | NULL | NULL | NULL | false / NULL,NULL，缺位置 | 1 |
| V1 | syn_vic/0001 | 2020-01-15 / day | F | true | 1 | 2 | true / -37.8000000,144.9000000 | 1 |
| V2 | syn_vic/0002 | 2021-02-15 / day | I | false | 0 | 1 | false / NULL,NULL，Node冲突 | 2 |
| Q1 | syn_qld/0001 | 2020-01 / month | I | false | 0 | 1 | true / -27.4700000,153.0200000 | 无明细 |
| Q2 | syn_qld/0002 | 2021-02 / month | N | false | 0 | 0 | true / -27.5000000,153.0500000 | 无明细 |

N2三项指标资格false，其余事故三项均true。地图资格true时CRS=EPSG:4326且位置raw定位非空；不可用时经纬度、location_crs、location_record_id均NULL并记录原因。UUID由成员生成，不作为手算固定值或指纹输入。

| 资源 | 小样本组成 |
|---|---|
| S1/S3/S7 | 分别N1/N2、V1/V2、Q1/Q2，各2行；按05原生表头制作CSV/XLSX。 |
| S2 | N1单元01/02、N2单元01，共3行；类型CAR，statistical_scope=synthetic_traffic_unit，count_eligible=true。 |
| S4 | V1车辆01、V2车辆01/02，共3行；类型CAR，statistical_scope=synthetic_vehicle，count_eligible=true。 |
| S5 | V1人员P1/P2均引用车辆01，V2人员P1车辆引用空白，共3行；样例合同明确允许空车辆引用，全部有事故父键。 |
| S6 | V1/NODE01两条不同原始观察，均-37.8,144.9；V2/NODE02两条观察分别-37.9,145.0和-38.0,145.1。共4行，事故NODE_ID匹配；V1可信、V2冲突。 |

保留全部197列，未使用列为空原生值并在样例合同声明；事故声明单元数与上表相同，VIC人员声明数V1=2/V2=1。NSW伤亡分项N1=2+1+0+0，N2全未知；VIC V1=1+1+0、V2=0+1+0；QLD Q1=0+1+0+0、Q2全0，Total为1/0。QLD分类单元数可设非负值但不产生单元明细。样例使用独立虚构分类映射，不能把官方draft合同改名当作批准。

**空库首个成功批次预期**：raw=19；meta.source/resource/batch/current_release=3/7/1/1；hub_crash/sat_crash=6/6；hub_unit/sat_unit/link_crash_unit=6/6/6；canonical.crash/unit=6/6；dim_source/month/severity/fact_crash=3/60/12/6。V1两个同坐标观察均留raw，仅按05选择有依据的代表位置。历史场景按batch核对，不能把累计快照当事故数。

| 范围 | 事故 | 月份已知 | 三项各known_count | 死亡事故 | 死亡人数 | 伤亡人数 | 地图点 |
|---|---:|---:|---:|---:|---:|---:|---:|
| syn_nsw | 2 | 1 | 1 | 1 | 2 | 3 | 1 |
| syn_vic | 2 | 2 | 2 | 1 | 1 | 3 | 1 |
| syn_qld | 2 | 2 | 2 | 0 | 0 | 1 | 2 |
| 2020合计（合成共同口径） | 4 | 3 | 3 | 2 | 3 | 6 | 3 |
| 2021合计（合成共同口径） | 2 | 2 | 2 | 0 | 0 | 1 | 1 |
| 全部 | 6 | 5 | 5 | 2 | 3 | 7 | 4 |

月度非零合计为2020-01的3宗、2021-02的2宗，年度另含N2。严重度六个非零来源组各1宗：NSW F/缺失，VIC F/I，QLD I/N。地图4/6，百分比66.67%；查询模块仅输入N2的独立子样例时（不增加页面事故筛选）三指标NULL、known_count=0、地图覆盖0%；筛2024时事故0、指标NULL、覆盖NULL。

必需QA共63行：QA01/02各8（7文件+batch），QA03为6（5实体资源+batch），QA04为5（2单元+Person+Node+batch），QA05为4（3来源+batch），QA06/07各16（3来源×5年+batch）。仅QA07的NSW2020、VIC2021及batch为limited；其余pass，QA07 batch affected_count=2。以上均为预期，不是执行证据。

## 5. 验收输入与通过条件

每个异常场景从S0独立测试库/快照开始，默认当前成功批次B0。未说明时，失败后B0指针及其事故6、单元6、死亡事故/死亡人数/伤亡人数2/3/7不变；候选层回滚，raw和失败登记可增加。实现者保存实际结果，不能预写通过。

| 编号 / 主测→复核 | 操作 | 通过条件 |
|---|---|---|
| AT01 A→B/E | 空库安装、三角色；地图资格true且CRS=NULL，坐标/位置ID均有值。 | 17/129/30；reader写入/候选读取失败；非法地图行拒绝，合法map=false空位置事故可留。 |
| AT02 B→C | S0；分别缺文件、改表头/哈希，同定位重送及改payload。 | raw19；同定位同值复用ID；各异常阻断，无静默漏字段/新事实。 |
| AT03 C/A→E | S0跨源同号；重复键、孤儿、错release_scope或batch。 | 原6宗不跨源合并；错误关系/重复拒绝，不补父记录。 |
| AT04 C→A/D | V2人员空引用改为不存在的99；核对Node组。 | 原空引用通过，99阻断；4观察保留，2个重复匹配组可计量，V2不任取坐标。 |
| AT05 C→D | S0；另改非法日、负人数、未定义分类X。 | 原未知不补0、月份不补日、死亡事故2≠人数3；三个异常block。 |
| AT06 D→C/E | 候选事实删/多事故、改人数、交换键或资格。 | §4逐来源/年和逐行一致；所有差异block，总数相同的错键也发现。 |
| AT07 C/D→E | S0；越界坐标、未知CRS、多位置；再强设地图资格。 | 合规隔离limited且事故仍6；原地图4点/66.67%；错误资格block或约束失败。 |
| AT08 B→E | 相同输入/规则重跑；只换归档目录或JSON对象键顺序。 | no_change，无新batch/事实，batch_id和switched_at不变；FP1一致。 |
| AT09 B/C/D→E | 完整快照修订N1死亡2→3、伤亡3→4及分项，更新发布标签/变化依据。另独立变体删除Q2。 | 修订新批6宗、死亡4/伤亡8/死亡事故2，B0仍3/7；有删项说明的删除变体5宗，无旧事实残留；未说明缩减block。 |
| AT10 B/C→E | 文件不变，改虚构规则使N2可判为非死亡、人数仍未知；另仅改代码摘要。 | 新指纹/批次；fatal_crash_known_count 5→6，两项人数known_count仍5；仅代码变化也重建，旧批不变。 |
| AT11 E→B/C | 逐组删具体对象结果但留汇总；注入block、非QA07 limited。 | 每种情况拒绝发布，不以汇总/缺失代替通过。 |
| AT12 B/E→A | rv后、dw后、指针更新后但提交前抛错；断连接/DB不可用；COMMIT成功但应答丢失。 | 提交前失败回滚并独立留证；不可用先留文件。应答不明unknown_commit，查明成功不误记failed或重复构建；后来被替换的成功旧批仍为成功。 |
| AT13 B→A/E | 会话一持锁，启动二；再结束一。 | 二busy且不登记；一会话结束锁释放。登记短事务提交不能提前释放锁。 |
| AT14 D/B→E | 页面三查询之间切指针；传错模式/未成功batch。 | 同页原batch、刷新才换；错误模式/状态拒绝；合成不改official指针。 |
| AT15 B/C/D→E | 增syn_sa事故资源S8：2020-01，F，死亡1/伤亡1，可信-34.92,138.60，无单元。 | 不改17表或执行器来源数量判断；raw20/事故7/单元6，总死亡事故3/死亡4/伤亡8、地图5/7；原三州不变；S8坏键失败保留B0。 |
| AT16 D→C/E | 三报表；仅N2的模块子样例/筛2024，首次无发布、month=13。 | §4结果及NULL/0正确，批次/模式/定义/限制可见；无发布no_publication，非法月份拒绝。 |
| AT17 全组→E | 未参与安装者从空环境重放；真实规模另测。 | 合成复现无需私人文件或手工修表。官方样本/全量分别记录摘要、行数、耗时、WAL/磁盘、恢复成本；未测写NOT_RUN，不预设虚假性能阈值。若资源/耗时不能支持演示，P3不通过并据实调整。 |

测试程序由成员编写，验证不得复用加载中的同一指标计算逻辑。扩州和故障变体也要保存实际输入、独立预期及结果。

## 6. 阶段与并行顺序

| 阶段 | 退出条件 |
|---|---|
| P0 共用约定 | A/B锁环境，全员确认本文、S0及实际调用签名；登记§8。合成合同明确即可启动P1，不能借合成结果关闭官方未决项。 |
| P1 小链路 | B交原生文件→C投影→A Vault→C重读Satellite→D仓库/查询→E QA→B提交；一次成功和一次失败保护实际通过。 |
| P2 七资源 | 各模块并行补齐S0及AT01–07/16；预期数值、QA63行一致，每份交接由下游复现。 |
| P3 运行/扩展 | AT08–15及合成冷启动实际通过；官方合同确认后另跑官方样本/全量，分列状态与规模限制。 |
| P4 课程交付 | 团队自行完成最终报告、注释SQL、三来源模型/查询、仓库、三合成报表、录像、贡献和会议证据；全员能解释上下游。 |

## 7. 一次交接一条记录

| 项目 | 必填内容 |
|---|---|
| 身份 | 任务/接口或AT编号、主责、使用方、复核人、日期。 |
| 版本 | commit/代码摘要、迁移/合同版本、输入哈希、模式、batch_id（无批次说明原因）。 |
| 操作 | 实际命令、前置状态、预期计数/状态、实际计数/状态、PASS/FAIL/NOT_RUN。 |
| 证据 | 他人可打开的日志/结果/截图/录像路径；失败定位及修复PR。 |
| 结论 | 下游复现情况、限制/阻塞及主责；通过才“已交接”，收到文件不等于验收通过。 |

可在PR或现有工作日志填表，不另建协作平台。建议证据路径 `evidence/<AT编号>/<日期或run_id>/`；实际执行者生成，E维护总索引。各人维护个人SQL解释/贡献；跨接口缺陷由提供方和使用方一起定位，E不承担所有修复。

## 8. 需要实际确认的事项

| 编号 | 主责及所需依据 | 截止条件 |
|---|---|---|
| DEC01 来源呈现 | E+A向教师确认三个来源逻辑schema/原生视图是否满足至少三来源数据库/schema要求，记原意见、日期及采用形式。 | 课程设计定稿前。三个文件不替代模型/查询；若需额外物理来源区，另计对象与范围。 |
| DEC02 Lab/技术 | E+A确认Docker对应Lab方式，以及Data Fabric原则是否满足所选技术，是否必须Microsoft Fabric产品。 | 技术路线定稿前；meta/qa不能称为已实施Microsoft Fabric。 |
| DEC03 提交 | E核课程模板/命名、报告与演示、工具使用要求。附件Assignment 2第5页明确禁止用GenAI生成最终报告；本包供内部讨论，团队自行完成最终报告，按教师说明确认工具边界。 | P4提交前，不能直接把本包作为满足该条的最终报告提交。 |
| DEC04 官方语义 | 来源负责人+C确认05中兼容发布、缺失值、分类和人数范围，留来源证据、版本、双方复核。 | official发布前，draft业务合同禁止发布。 |
| DEC05 官方位置 | C+来源负责人确认CRS、变换及可信位置依据，D复核限制。 | 官方合同确认/地图启用前，未知不猜EPSG标签。 |

以上仅列待办，不预写批准。至少三份教师签署会议纪要、个人贡献和全员演示必须真实形成。保持首期边界：不建人员Canonical/事实、QLD分类事实、独立单元仓库、调度或阶段恢复。
