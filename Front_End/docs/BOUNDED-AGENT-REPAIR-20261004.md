# 有边界的 Agent 卡点处理：实现、验收与交接

2026-10-04，Australia/Sydney。本轮开发目录是相邻 `ARSIA-Agent-Repair-20261004/source`，证据根（下称 E）为 `../../ARSIA-Agent-Repair-20261004/evidence/`。本任务是本地开发和维护，没有 commit、push、PR、部署或定时任务。

隔离验收结论：SA 两版的真实 Agent 发布、单版本查询及零模型重传链已通过；原始 ACT 完成真实调查与隔离诊断，但官方身份尚未验证，不能称为官方导入成功。正常工作区的实际集成状态以 E/integration-01/applied.json、服务启动和 protection-final.json 收据为准，最终交接见 E/HANDOFF.md。本文各项结论以对应执行证据为限。

## 实际实现

- `AgentSession` 增加 opt-in `bounded_repair_v1`，将原始请求、输入哈希、job/attempt、当前卡点、合同/代码身份、错误出处、已尝试诊断及累计额度保存在 checkpoint。历史 session 未保存该标记时仍为 false；没有迁移、恢复或重写历史任务。
- `repair_context.py` 使用已有错误分类形成调查、工程审查或停止路由。诊断上下文可通过现有定点读取工具取得，大文件留在本任务证据中。工程提案最多 64 KiB、始终 untrusted、禁止自动加载；即使初始错误被归为 adapter 问题，也可请求审查疑似宿主缺陷。
- `task_authority.py` 用真实表结构和最多 64 行样本验证字段绑定、日期和值；辅助表必须关联已审查的主表及实际字段。来源未知、非政府域名、未知文件名不等于无关。没有完成范围审查时最多 4 次模型调用、3 次发现动作，只允许少量元数据；不会执行上传程序。
- `task_diagnostics.py` 允许针对当前 blocker、当前 job/attempt 和已绑定输入执行生成的 Python。诊断可以先于导入合同准入运行，支持全表键、关系、值及坐标比较。输出永远不是官方证明、QA 或发布授权。
- 新会话的 `publish_candidate` 在 Agent 工具调用中执行真实事务。发布拒绝返回同一 session；只有真实提交成功才完成。确定性 generic 的缺证据拒绝和发布层 NeedsInput 可进入一次有界 Agent，携带原始失败；不会在已有 Agent 后再启动另一个 Agent 绕过停止。
- `independent_versions.py` 在 sample/full 执行前，使用宿主注册文档及严格来源预检提出独立版本身份；绑定 dataset family 与完整输入哈希。提案不产生准入，最终仍须 fresh sample/full QA、注册和发布时的官方 family 复核。改变合同使旧 QA 失效。每版独立 source_id，查询必须选择一个版本；不推断逐事故对应、版本先后或范围删除权限。
- QA 临时 SQLite 不再重复保存两份完整行：全部字段（包括 raw extensions、坐标和关系）的稳定序列化 SHA-256 仍逐行比对，SQL 只保留后续计数/关系检查所需字段；失败时从不可变原始输入重新取得定位诊断。原件与完整候选输出不删除，不增加 512 MiB 额度。
- 下载比较 ZIP 的子表保留宿主给出的 evidence 来源标记；同一 ZIP 的物理缓存按当前父资源重新绑定，不能让真实上传表借相同内容哈希获得免检。`QA02_RAW` 对用户输入事实表的完整分配要求未放宽。
- Codex CLI 的 shell、插件、浏览器和 app 能力关闭；只准许受监管的 Code Mode dispatch。VM dispatch 与 MCP 工具分别计入累计工具预算；dispatch 包装不再重复计作一次“语义无进展”。执行成功不能从 dispatch 授权推断。
- 单版本 autonomous 车辆查询用 EXISTS 判断是否关联本次选中事故，避免小样本估计下的嵌套循环；继续按角色和完整原键关联，每个车辆只计一次，不通过增加查询超时绕过问题。
- UI 展示原始请求、当前卡点、工程审查提示、尝试的诊断和未达成能力。失败、取消及 needs_input 均不显示成功发布。独立版本/受限结果保留 `target_satisfied=false`。

具体逐文件前后哈希见 E/integration-01/candidate-manifest-03.json；最终是否应用以 applied.json 为准。构建自动生成的 `next-env.d.ts` 和 `tsconfig.json` 不从隔离目录直接覆盖正常项目。

## 终止出口与去向

| 入口或出口 | 本轮去向 | 已验证边界 |
|---|---|---|
| 已验证 recipe | 优先确定性复用，每次 fresh QA | registry 与 full QA 仍独立；不是结构命中就准入 |
| 未知来源、普通缺证据、adapter 执行失败 | 同一 Agent 有界调查/修订 | 实际输入绑定；合同或代码变化使旧 QA 失效 |
| explicit generic 的 NeedsInput | 新标记会话可带原失败进入 Agent | 历史开关关闭时保持旧行为；预算停止不触发新会话 |
| autonomous 最终事务发布拒绝 | 返回当前工具/当前 session | 实际 SQL fixture 验证失败回滚、修复后成功、累计次数未归零 |
| deterministic 发布的 NeedsInput | 尚无 Agent 时可进入一次调查 | 已有 autonomous 候选不再另开会话 |
| 固定 native 策略、deterministic ValidationFailure、未分类宿主异常 | 保存明确工程审查去向并停止 | 没有给数据 Agent 改写固定政策的权限；这些出口不是全自动修复完成 |
| reader/新变换/宿主能力缺口 | 隔离诊断及不可信工程提案；由维护流程验证补丁 | 没有自动部署工程补丁的第二套 Agent 平台 |
| 取消、累计预算、身份/路径/所有权完整性失败 | 停止，保留证据与账本 | 不重试、不重新开 Agent、不增加额度 |
| 外部登录/授权、无法取得的历史来源证明 | 具体 needs_input 与剩余能力 | 不绕过访问控制，不把比较相似当证明 |

工程案例不止提示词：ACT/SA 实际诊断先发现执行路径被错误放在未登记的 `diagnostics` 子目录。Agent 写出复现与修复提案后，维护代码改用既有、已登记的 attempt/agent/run 路径；正向真实容器执行和错误兄弟目录拒绝均通过。SA 后续又暴露参考 ZIP 的资源标记传递缺陷，以及 Codex 运行缓存链接与下一任务存储检查冲突；均保存原失败并单独修复，没有恢复旧 job。

## 权限和资源边界

数据 Agent 只能提议合同/adapter、读取本任务受控证据、执行专属输出的沙箱。不能修改宿主验证器、可信收据、业务库或已发布数据。`report.json` 成功、模型自签权限、相同行数、完整键交集或数值相近均不产生官方准入。

Python 诊断使用实际 Docker：只读输入、专属输出、无网络、无宿主根/凭据/Docker socket/其他任务挂载，1 CPU、512 MiB、16 PID、最多 120 秒且不超过剩余计算额度、16 MiB 输出。AST 是提前反馈，容器才是主要访问边界。失败和取消仍扣除实际诊断时间。

保留用户实际 Sol/high 与 expanded-v1：120 model、200 tool、40 correction、7200 秒墙钟、2400 秒计算预算，未增加或降配。新限制进一步收紧：未审查范围时单次下载最多 2 MiB/15 秒、累计元数据 6 MiB；同 session 全部下载累计 256 MiB，失败/重复下载也计数，去重不退款；同 job 所有 attempt 的工作证据上限 512 MiB/32768 文件条目。已有 TestSession 的空间总额及磁盘保留量继续生效。

Codex 子进程组另有每秒 CPU、RSS、进程数、文件量和墙钟 watchdog。CPU 保留已观察到的退出子进程用量，累计计入同 session；1.5 GiB RSS、32 进程和 512 MiB runtime 文件上限。**这是采样监督，不是内核硬配额**：极短子进程可能漏采、限额可能有短时超出。诊断 Docker 的内核限制与此应区分。宿主解析/网络等待主要受 reader 限制与总墙钟约束，不能声称所有宿主 CPU 都按进程精确计费。

Codex 的三种 argv 缓存链接仅在准确 job UUID/home/tmp/arg0 路径、指向所配置 Codex binary 时允许按链接自身大小计量；不跟随目标。任意其他符号链接仍拒绝；资源读取、archive、路径绑定的严格拒绝没有改变。

## 真实输入与自主验收

### SA 官方历史/当前版本

原历史 ZIP SHA-256：`8a5f4269d900b9b518db0d7274d935a53b3befeb148ee49cfc0e71d74947f989`；当前 ZIP：`b1c22ba4444542c07f876a26aab0bc5ee1bfc4689001dabf6309c634550737de`。复用既有合法下载原件及收据，没有给 Agent 手写最终合同、映射或 adapter。旧研究收据不冒充可信网络准入；Agent 使用受控工具重新取得证据。

E/sa-pair-agent-03 的 Agent Python 实际比较全部 6 张表，维护侧在 E/independent-real-comparison-02.json 独立复算。历史/当前 2020 年事故均 11534 行，但原完整键交集为 0。截去发布后缀只得到 11514 个共有假设键，20 个旧事故仍不匹配，且存在严重程度/人数/坐标变化；车辆和伤亡假设键分别仍有 489、808 个旧键不匹配。两版原父子关系没有孤儿。这些结果否定“去后缀即可合并”，不建立官方键迁移关系。

E/sa-pair-agent-05/old 已真实 succeeded：Agent 自主形成候选、执行 sample/full、选择独立版本后重新验证、登记和事务发布。独立查询/原 ZIP oracle 检查事故、车辆、伤亡人数及零孤儿。28 次模型调用，309.06 秒。下一 current job 在模型前因严格存储扫描遇到 CLI argv 缓存链接而失败，旧 release 保持不变；跨版和重传当轮未执行。E/sa-pair-agent-06 的 old 再次成功，current 在完整 QA 阶段达到 512 MiB，准确停止并保留旧发布，没有重传。随后压缩 QA 工作表示并前置版本提案，避免重复全量输出。E/sa-pair-agent-07 又由真实 Agent 定位版本提案漏装宿主注册文档的问题并提交工程提案；未恢复旧任务。修复后 E/sa-namespace-replay-03 用真实保存候选完成无模型预检/提案复现（不是自主发布），E/version-hydration-01.log 的 72 个针对性测试通过。E/sa-pair-agent-08 的两版均由真实 Agent 发布成功，但新版单版本车辆查询遭遇 15 秒超时，原 harness 因 oracle 查询失败而结束，未执行重传。E/sa-query-audit-01 只读 EXPLAIN 定位新批次统计尚未更新时的嵌套循环；同义 EXISTS 半连接在约 0.49 秒返回全部 134981 个车辆，15 秒限额未变。E/query-db-11 的 88 个发布/查询回归通过。已关闭测试会话拒绝了后续写入（没有新建 job、没有重试旧导入），最终完整链在新 E/sa-pair-agent-09 执行。

E/sa-pair-agent-09 最终完整链通过，process returncode=0，474.76 秒总墙钟：旧版 31 次模型调用、255.61 秒；新版 15 次、156.08 秒；旧/新重传分别 16.39/38.57 秒，均 fresh QA、`no_change`、0 模型调用，catalog 不变。原件 oracle 与实际单版本查询分别确认旧版 11534 事故/24539 车辆/4877 伤亡记录、新版 63239/134981/23892，原父子关系无孤儿；按单版本选择避免跨版相加。该轮是全新实例，没有恢复任何失败 job。

真实逐事故映射仍未完成；独立版本只证明各版可独立查询，不证明同一事故身份、自动最新版本、跨版总数或删除授权。真实失败保留旧 release 的证据来自 05/06；最终事务故障注入为明确 SQL fixture，不伪装成生产故障。

### 用户原始 ACT

始终只读 `/Users/zhengpeixian/Downloads/ACT_Road_Crash_Data_20261001.csv`，16637960 bytes，SHA-256 `950eb319cc566d375f7fbe993760cbc8245f4f1d51b93b5a0baa720eb4cebb41`。76657 行、唯一 CRASH_ID 76657；105 Fatal、6576 Injury、69976 Property damage only，日期观测范围 2015-01-01 至 2026-09-07。Fatal crash 不是死亡人数，缺失人数仍未知。

E/act-original-agent-01 至 04 都是新隔离任务。01 暴露 provider 原生 exec 事件缺 namespace 的兼容问题；02 的真实 Agent 诊断触发路径归属错误并给出工程提案；03/04 已实际运行完整比较脚本，保留未绑定官方身份并结束 needs_input。03 的无进展计数还包含重复 VM 包装，随后修正；04 在修正后的真实语义无进展边界停止，**不是官方导入成功**。

完整比较和维护侧独立复算：与所绑定的当次官方参考文件全部 CRASH_ID 匹配，Location 字符串 76657 行不同，数值经纬字段分别 4169/4585 行不同，最大绝对差 5E-12。原始 Location 与其自身数值坐标有 4629 行表示不一致；其 Location 可与参考高精度值对应。11 位 half-up 的候选数值重放解释了该比较中的数值差异，但没有证明历史原字节生成过程、官方授权或完整序列化重放。不同抓取的官方 CSV 也可能有排序差异。

E/act-original-agent-05 已完成 14 次真实模型调用、268.79 秒 worker 墙钟：实际执行两次完整诊断，随后提交包含实现建议及正反例的工程能力缺口，准确结束 needs_input。未进入官方执行/QA/发布。最终代码再用 E/act-final-rule-replay-02 在全新实例重放保存候选及原可信参考收据，确认原件字节不变、OFFICIAL_UPLOAD_UNBOUND 保留，独立版本工具也不能绕过；该复验为 0 模型、不是新的自主成功。

合法隔离研究已落实为绑定原始输入的诊断运行及保留候选/报告；现有产品没有将“身份未验证研究候选”当作官方 source 发布的入口，本轮没有偷换身份。最小后续动作是取得可信历史绑定证据，或开发并独立验证适用的完整表示变换证明；若另做研究发布，必须有独立命名空间和明确未验证身份的查询/UI 政策。不能仅给现有官方 QA 增加容差来放行。

## 测试与证据索引

测试数量按种类分开，不把重跑、假模型 fixture 或预期拒绝加成“成功官方数据源数量”。共 3 份不同原始输入（SA 两版、ACT 用户原件），覆盖 2 个辖区；20 个真实 harness job 中含失败及零模型重传，累计 393 次真实模型调用，其中 1 次用量未知。已知 input 19847325、output 183197、total 20030522 tokens；input 内含 cached 16370095，不重复相加。各 job 墙钟及失败阶段见 E/real-model-usage-final.json，不把并行时长相加称为实际总墙钟。当前可核对：

| 类别 | 执行证据 | 结论/边界 |
|---|---|---|
| 完整 Python suite | E/compact-all-02.log、E/version-hydration-01.log | 完整 suite 1547 passed、43 skipped；最后文档绑定修复后的针对性 72 passed。实际重建镜像参与容器测试 |
| PostgreSQL/发布/路由 | E/final-db-10 | 普通 backend、Codex integration、autonomous backend、有界修复分别 37/17/80/8；以各 pytest.txt 为准。真实 SQL 与容器，模型序列为 fixture |
| 旧引擎兼容 | E/legacy-db-05 | Codex integration 17、autonomous backend 80 passed；不启用错误的全局 adaptation fixture 组合 |
| 前端 | E/frontend-tests-01.log、frontend-lint-01.log、typecheck-01.log | 173 Node tests、lint、类型检查通过 |
| 构建 | E/build-02.log、executor-build-02.log | 隔离 Webpack build 通过；执行器可从私有权限源码重建。Turbopack symlink checkout 失败与第一镜像权限失败均保留 |
| 实际执行隔离 | E/bounded-container-02.log、executor-container-03.log | 输入/宿主/凭据/socket/其他 job/网络/根写入拒绝；CPU/墙钟超时、诊断输出无准入 |
| 范围与注入 | test_bounded_repair、test_bounded_evidence、test_codex_resources | 陌生合法字段、关联辅助表、无关包装、输入变更、伪权限、模型 dispatch 边界、累计预算；不宣称百分之百识别伪装 |
| 浏览器 | E/browser-repair-02、03；source/output/playwright/bounded-* | 真实浏览器验证 needs_input/failed/cancelled、原始请求、工程卡点、诊断尝试、刷新保留及受限数据；全部独立 release |
| 独立 Studio | E/browser-studio-proof.json | 创建、改名、刷新后保留目标与 release。缺模型配置提示属预期；没有完成浏览器中的真实 Studio 模型分析 |
| 真实模型用量 | E/real-model-usage-final.json | 每个 job 请求数、已知 input/output/cached、unknown、墙钟分别保留；cached 已含于 input，不重复相加 |

失败证据保留：旧镜像 tag 导致的纯测试失败、fixture 配置差异、首次私有源码镜像 PermissionError、全部真实 Agent 失败及前两轮路径/dispatch 修复。它们不计为通过。测试只使用新实例，没有正常数据库写入验收。

## 保护、集成与回退

初始 E/baseline.json 保存 529 个源文件；E/content-before.json 对正常 PostgreSQL 16 表/534010 行和 Studio 6 表做内容摘要（只排除 worker 心跳），Studio schema0/46 studies。浏览器后 E/content-browser-after.json 完全相同。manual 的两项历史 job 仍为 cancelled/needs_input、attempt=1、原更新时间不变；E/manual-read-only-integration-01.json 的全表摘要也与本轮 manual 基线相同。

正常唯一 3100 前端为独立浏览器窗口短时切换，两次均识别 cwd/PID、核实任务空闲后仅停止本项目前端，随后恢复正常 release `ff8b9868-515f-48c4-95c0-33ffbae73430`；未重启后台 worker/API。E/normal-frontend-restored-03.json 是最近一次恢复收据，PID 只是该时点观察。

并发复核发现另一窗口新增 `docs/OVERVIEW-MAP-SEVERITY-RECOVERY-REFERENCE-20261004.md`，不在补丁范围；记录其哈希并保留，不覆盖、不回退。其他基线文件当时均未变。应用前必须再复核，不能以这些历史时点代替最终检查。

E/integration-01/backups 保存待修改源码、私有配置、正常/manual PostgreSQL dump 和 SQLite 一致性备份。dump 只用 pg_restore 解码到 /dev/null，不执行还原。回退必须先确认空闲/归属/当前文件哈希，只恢复本轮实际修改文件；新文件移入专属 quarantine 保留。不得 reset，不自动还原数据库/Studio，不改变历史任务。具体回退见 E/integration-01/ROLLBACK.md；实际应用和重启以 applied.json、backend-started.json、frontend-started.json 为准。没有这些收据时不能宣称集成完成。

## 未完成与适用范围

- SA 两个代表版本及零模型重传链已通过；逐事故跨版对应没有官方证据，不能推广为全部 SA 历史版本已验收。
- 原 ACT 官方身份未验证，不能用参考下载文件替代原件验收，也不能将诊断成功称为官方发布。
- 数据 Agent 提交工程提案后不会自己获得宿主写权；本轮由被授权的维护开发流程复现、修复、反例测试。任意新 reader/任意 ETL 不是已支持能力。
- deterministic ValidationFailure/固定 native/完整性出口保留停止与明确工程去向，不宣称所有出口都能自主修复。
- 正常 Studio schema0 不迁移；其写功能与真实模型分析没有因独立 Studio 的 fixture 验收而获得验证。
- Codex OS 沙箱仅验证当前 macOS arm64；未知恶意伪装、所有州历史版本、Linux/多人/公网部署不在已验证结论中。
