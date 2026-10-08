# 本地自主接入最终验证报告框架

状态：2026-10-01 的证据汇总框架，当前真实 SA 新版本与 worker-loss 验收仍在执行。
本文的“待本轮证据”不可解释为通过。没有远端部署、GitHub 发布或旧数据重置。

## 最终结论填写规则

最终报告先写“哪些实际来源完成上传→调查→代码→sample/full QA→数据库→网站”，再写
尚未完成或被明确阻断的来源及原因。每项结论绑定 job、attempt、source、batch、release、
adapter、image 和 QA policy/implementation hash；不要把旧版本的数值验收、新版本的代码
测试和一次模型运行拼成一轮全通过。

测试总数、独立来源核对项数、实际模型调用数分别记录。模拟模型、专属测试数据库、真实
Docker 隔离测试和实际上传链路分别标注。保存失败、取消、未注入和后续修正的全部历史。

## 当前已有结论与本轮待补项

| 范围 | 已有证据 | 最终报告仍需核实 |
| --- | --- | --- |
| 原 NSW/VIC/QLD | 原 frozen native 处理保持；主任务原三州 836 项回归精确通过，重复输入 no_change | 引用该回归实际产物与保护数据哈希；不要等同于 native 新年度实测 |
| ACT | 真实模型最终发布，独立 v3 2,570 项通过；76,657 crashes、105 fatal crashes，死亡/伤亡人数缺支持而为 null | 保留早期 needs_input、重试与累计预算历史；地图未准入不等于已证明无坐标字段 |
| SA 首个发布版本 | job `8056ec76-da6c-4bfd-afc4-3b7681e426ec`；source `sa_road_crash_data`；batch `bcbee8e4-f39a-4b38-87f1-1562d2469ed1`；release `317b799e-8637-4ecb-90bd-4590dc556324`；v3 1,168 通过、1 项差异 | 该版本缺 declared_casualties；已发现的官方 CRS 未映射，地理未验收。历史版本保留，不回写成新结果 |
| SA 新版本 | policy `canonical-v2-auto-admission-3` 的能力/对账适用性门已落盘并独立复审 | 待本轮新 job 的自主修正、full QA、独立逐键事实、坐标/缺失值、发布与网站验证；不得用只读内存 counterfactual 当作实跑 |
| TAS | 完整官方输入、分页收据及独立异常调查已准备 | 真实模型任务、异常阻断、保留旧 release 尚待执行；没有任务就保持未验 |
| 正常取消 | 实际 SA 调查中取消约 0.6 秒、release 不变，保留 `sa-active-cancellation.json` | 不将本地取消解释为远端模型服务已停止计算 |
| Scoped orphan | 离线所有权测试和独立 marked test DB 的真实容器回收通过 | 与真实 worker SIGKILL 整链恢复分开报告 |
| 实际 SIGKILL 恢复 | 三次早期 watcher 已安全结束，均 injected=false/passed=false | `--hold-owned-container` 新方案待本轮实际 injection、strict reap、同 session 恢复、新 sample/full QA、发布的完整证据 |
| 部署 | 本地 Next 3100 + host API/worker + 专属 PG + 隔离 adapter；Linux 模板和说明已准备 | Linux 8 GiB/75 GiB 资源、权限、备份恢复、认证/HTTPS和生产角色分离均未实测/部署 |

## SA 版本修正验收填写区

不要覆盖第一版的失败事实。将本轮结果作为新一行版本记录追加：

| 字段 | 本轮结果 |
| --- | --- |
| job / Agent session / attempts | 待本轮证据 |
| 原始 ZIP SHA256、三张表 SHA256 | 待本轮证据；核对来源下载收据，不复制 oracle 到模型 |
| 原 source identity 与新 source/batch/release | 待本轮证据；应更新同一 logical source，保留其他 source |
| 模型 policy / SDK / image / trusted implementation | 待本轮真实 step 与 admission 记录 |
| 自主代码及合同修正 | 待本轮 tool steps；地理映射和 declared_casualties 必须由 Agent 提出并重新 QA |
| sample/full 执行与独立 QA | 待本轮实际 run IDs、admission 和结果 |
| 独立 crash/unit/casualty 逐键事实 | 待本轮独立验收；不放宽第一版失败项 |
| 地理变换与源缺失坐标 | 待本轮独立检查；区分 available、unknown、unsupported，不填造坐标 |
| 重复上传 no_change | 待同一新 QA/image/合同有效版本再次上传；政策变化产生新版本不算重复测试通过 |
| Overview/Analytics/Map/Ask AI/Studio | 待固定同一新 release 的页面与模型结果；记录能力状态和查询范围 |

## 生命周期验收填写区

最终收据必须同时说明是否执行 watcher、是否看到正确容器、是否 hold、是否真正 SIGKILL、
是否严格回收 orphan、是否完成重新 QA 与发布。安全地不注入不是恢复失败，也不是恢复通过。

- 注入前：数据库 marker、唯一 active job、worker PID/command/cwd/start、host receipt/hash、
  immutable Docker ID、labels/mounts、session/attempt、累积 model/tool/correction/wall 预算。
- 故障动作：可选 hold 的时间与 exact ID、SIGKILL 时间；没有信号时 exact unpause 的结果。
- 恢复：不同且属于本项目的新 worker PID；对应 orphan-recovery 审计；旧 attempt interrupted；
  同 job/session 的新 attempt；完整历史与预算未重置，pending call/output 配对。
- 新执行：恢复 attempt 的实际 sample、sample QA、full、full QA；不复用旧 attempt 的批准。
- 原子发布：最终状态、batch/release、原 source 更新规则、其他 sources 不变；失败时旧发布保留。
- 结论：每个断言的实际结果及收据路径。checkpoint 恢复成功而后续 needs_input，仍不能称端到端恢复通过。

## 部署与资源边界

明确本轮没有运行课程 Raw/Vault/DW 旧生产链，也没有将 legacy Compose 等同于自主 Agent
部署。当前部署准备见 [deployment/README.md](deployment/README.md)。备份范围须覆盖 PostgreSQL
和原始文件、文档收据、adapter、运行产物；DB-only 备份不能保证可复现。独立 orphan watchdog、
远端身份认证、权限分离、异机恢复演练和资源容量仍按实际完成状态填写。

最终资源表分别记录 wall time、模型/工具调用、CPU、峰值 RSS、容器 cgroup 峰值、PG/Next
整体占用、原始/临时/保留 artifact 与 DB/WAL 字节。注明采样方法、操作系统、单位及覆盖阶段。
macOS ru_maxrss 是历史进程高水位，不能直接当 Linux KiB，不能简单相加声称并发总内存。

## 证据入口

- [AUTONOMOUS_VALIDATION.md](AUTONOMOUS_VALIDATION.md)：独立来源事实、真实版本记录与未完成项。
- [AGENT_LIFECYCLE_ACCEPTANCE.md](AGENT_LIFECYCLE_ACCEPTANCE.md)：严格生命周期前置条件、watcher 和收据断言。
- [AUTONOMOUS_BACKEND.md](AUTONOMOUS_BACKEND.md)：持久 Agent、版本、原子发布与 QA 门说明。
- `artifacts/autonomous-imports/`：来源收据、独立 oracle、实际来源验收和浏览器报告。
- `artifacts/imports-local/audits/`：私有 mode-0600 生命周期与隔离审计；不得附 runtime 凭证。

最终对外答案使用简短完成清单、实际局限和报告链接；不要把本框架的待验项省略成默认通过。
