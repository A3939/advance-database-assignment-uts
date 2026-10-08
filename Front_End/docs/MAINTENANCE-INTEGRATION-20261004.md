# ARSIA 本地维护集成与验收

日期：2026-10-04，Australia/Sydney。状态：**本地维护集成、服务恢复、业务保护复核和隔离浏览器验收完成。** 原始 ACT 官方准入被最终规则阻断、真实 SA 跨版本发布未执行；这些数据能力仍未完成，不包含在维护通过结论中。

证据根：`../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/`，下文简称 M。全部历史失败与原始文件保留。无 commit、push、部署、定时任务或正常数据库/Studio 迁移。

## 实际集成清单

- 已应用 `review-candidate-02.patch`，SHA-256 `ae89763d5510d84bbef6b0806a7c5919864340eb0f891ca0b64cc8b513a519df`。逐文件前后哈希及动作见 [integration-applied.json](../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/integration-applied.json)，共 160 个文件。
- 覆盖统一发布和来源权限、完整文件绑定、representation replay、registry/recipe 检索、fresh QA、粒度/覆盖/未知值语义、网站 catalog/release、模型用量、Studio 隔离及显式迁移、执行器资源边界。F01–F40/K01–K10 和逐项证据仍见 [实现记录](INTEGRATED-OPTIMIZATION-20261003.md)。
- 正常 runtime 的连接端口由失效的 63986 改为当时同一归属容器实际映射 52738；主机重启后重新验证归属及数据库 marker，更新为 49692。实例和数据库未替换。增加专属 knowledge cache、启用新任务 autonomous adaptation、固定已验执行器镜像。原 expanded-v1 模型路由与预算未改。
- 旧 manual API 同样修正连接端口并重启 API，未启动其 worker；历史 needs_input/cancelled 导入不动。
- 浏览器增量修复：`src/app/globals.css` 为全部证据弹窗限制视口高度并允许滚动，解决长说明使关闭按钮超出屏幕；`src/components/workspace.tsx` 渲染已由 API 提供的证据明细行，明确显示请求能力、实际限制和逐资源许可。两项均先在隔离预览实际点击复验，再按文件前态哈希应用到原工作区；原内容分别另存 M/backups。
- 最终默认 Turbopack 生产构建在 `artifacts/maintenance-build-20261004-03` 成功；Next 自动更新 `tsconfig.json` 和 `next-env.d.ts` 的类型引用。前两次构建保留，原配置在源码备份中。
- 本文、实现记录顶部状态、两个浏览器修复与构建配置属于维护增量。完整最终前后哈希见 M/final-integration-manifest.json，原审查清单不覆盖。

## 安全集成与备份

集成前只读确认正常库只有 3 个 succeeded job、无未结束 attempt/排队任务，current release 为 `ff8b9868-515f-48c4-95c0-33ffbae73430`，已有 migration 1–3。manual 库有 1 cancelled 和 1 needs_input，后者 `5a216839-193a-4309-8fe0-25be1bf9daeb` 的 attempt=1、更新时间仍为 10 月 1 日，无活跃 attempt。正常 Studio schema=0、46 studies、无 running run/lease。源码 458 个基线文件、160 个候选文件与审查哈希一致后才停止准确识别的服务并应用补丁。

备份包含源码前态、0600 私有配置归档、两个 PostgreSQL dump 和 SQLite 一致性备份。SQL dump 以 pg_restore 完整解码至 `/dev/null`，没有执行还原 SQL；Studio integrity_check=ok。备份路径/哈希见 [backup-manifest.json](../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/backup-manifest.json) 和 [manual-backup-manifest.json](../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/manual-backup-manifest.json)。不得公开私有配置归档内容。

正常库 16 个业务表、534,010 行的最终逻辑内容摘要与维护前完全相同；仅排除正常 worker 心跳表。正常 Studio 在全部浏览器操作后仍为 schema0、46 studies、6 表逻辑摘要完全相同。manual 的两项历史任务状态、attempt 和更新时间与重启前相同。见 [final-audit.json](../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/final-audit.json)。manual 未做全库逐行前后摘要比较，不能将任务核对扩大为该库所有内容证明。

主机重启后离线复核 528 个基线/集成文件，除上述两项构建类型配置外无差异；`.env.local` 和用户 ACT 原文件未变；正常 Studio 6 个表逐行多重集摘要完全不变，schema 仍为 0、46 studies。见 [resume-offline-audit-01.json](../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/resume-offline-audit-01.json)。

## 验收结果与当前服务状态

| 项目 | 实际结果 | 限制 |
|---|---|---|
| 集成后构建 | 默认 Turbopack 构建与 TypeScript 检查成功，M/build-final-03.log | 含两个最终 UI 修复；不依赖此前快照的 Webpack 构建结论 |
| 集成后 Node/lint | 173 tests 通过；最终 lint 通过 | 普通测试与浏览器结果分别记录，数量不相加 |
| 正常 API/worker、manual API | 重启后 /health=200，正常 worker idle/alive；manual worker 未启动 | PID 5565/5566/5567 是本次观察，不是永久身份 |
| 正常前端 | 原 release、3100 生产服务；Chrome 打开 Overview、Imports、正常 Studio；Imports worker online | 无正常业务写入；CSS preload warnings 保留，未出现 console error |
| TAS 完整浏览器链 | 新 M/browser-lab-02：632 行真实输入、sample/full QA、独立 oracle、registry、发布、网站服务、同名/改名 fresh QA/no_change；Chrome Overview、149 坐标网格、Analytics、Data/证据、Imports；保存至独立 Studio、编辑 finding/report、刷新、ZIP 导出核对均通过；0 模型 | 原 M/browser-lab-01 被主机重启打断并保留，没有恢复旧 job；官方 TAS 仅该月份有界样本 |
| 缺 CRS 受限能力 | 新 M/browser-limited-01：真实执行器/QA/SQL，Chrome 显示 1 条事故、地图 unavailable、人数未知；Data 显示 Requested/unverified/原始诊断及许可 unknown；独立 Studio 保留 target_satisfied=false 和固定 release | 明确是 synthetic fixture，不是官方 ACT 文件或真实未知源；0 模型 |
| 原始 ACT | 最终规则下实际上传、inspect/contract preflight，执行前来源绑定拒绝；0 模型、0 发布 | 见下一节；不称 full QA/发布成功 |
| 正常 Studio | 重启后逻辑内容与维护前完全相同 | 不自动升级 schema0；写入验收只用独立新 Studio |

主机重启曾使 Docker 引擎和服务退出。用户明确授权启动 Docker 后，先验证原数据库归属、实际端口及任务状态，再恢复服务。没有重跑集成、恢复历史导入或迁移正常存储。最终仅原业务 PostgreSQL 容器运行；本次所有测试容器均已停止，卷与证据保留。TAS/受限浏览器两次新协调器正常结束并 retained；被重启打断的 browser-lab-01 保留 exit255 和缺失 finalizer 事实，不伪造正常结束。

浏览器截图/快照/导出在 `../output/playwright/maintenance-20261004/`（相对本文目录）；结构化结果见 M/browser-lab-02/browser-acceptance.json 和 M/browser-limited-01/browser-acceptance.json。Ask AI 仅验面板打开；其真实服务工具/metadata 由保存至 Studio 的实际服务调用与前轮专用验收验证。本维护未运行浏览器中的真实模型生成、任意自然语言结论核验或全面视觉回归。

## 用户原始 ACT 文件的最终规则验收

输入就是 `/Users/zhengpeixian/Downloads/ACT_Road_Crash_Data_20261001.csv`，16,637,960 bytes；SHA-256 `950eb319cc566d375f7fbe993760cbc8245f4f1d51b93b5a0baa720eb4cebb41`。上传收据与原文件哈希一致。新下载官方文件仅作比较证据，未替代上传输入。

`canonical-v2-auto-admission-25` 下，来源绑定得到 `OFFICIAL_UPLOAD_UNBOUND`，在执行 sample adapter 之前阻断；没有 batch、release、source_version、adapter_version 或 canonical_crash。独立读取原 CSV 得到 76,657 行/唯一键，105 Fatal crash、6,576 Injury、69,976 Property damage only，日期观测跨度 2015-01-01 至 2026-09-07。死亡/伤亡人数未提供，保持未知，不能由 fatal crash 数填人数。

原文件与当前官方导出存在 Location 原字符串及坐标精度差异；现有无损表示重放要求全值等价，不能只凭相同行数、表头、事件键或容差取得官方身份。需要能精确绑定原字节/全值的可信历史收据、官方历史发布证明，或有证据授权且可完整重放的变换。取得之前只可保留独立待核验候选，不得污染已验证官方来源或可信 recipe。

实际结果见 [original-acceptance.json](../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/act-original-final-02/original-acceptance.json)。测试脚本捕获预检拒绝并验证零发布；测试 job 留在其独立 profiling 状态，storage-finalize 记录 `STORAGE_RECOVERABLE`，因此**测试生命周期收尾不是成功状态**。最终已确认专属容器停止、exit0、卷和证据保留；没有恢复/重试/取消该历史测试 job，也没有改写其生命周期账本。

## 真实官方跨版本更新：执行政策与未完成项

已合法取得 SA 官方 2020 历史 ZIP 和 2020–2024 新包，实际比较证据在 `../sa-official-version-pair-01`（相对 M）。相同 2020 年各 11,534 个事故，但 REPORT_ID 后缀由 20210527 变为 20250919，完整键无交集；新版另有 Crash Date Time。**真实官方 A→B 发布 not_run**；受控 fixture 版本转换及 A→B→旧 A 防回退测试不能替代这一结果。

后续按以下顺序执行：

1. 分别保留官方资源身份、完整收据、字典和版本适用范围；把键、字段、计数、CRS、日期、关系、覆盖与修订声明的变化写成结构化 diff。已确认依赖继续复用，仅将变化和相关证据定位交给模型。
2. 在没有稳定键或发布机构支持的键迁移证明时，保存独立候选/版本，不自动将新键当作新增记录并删除全部旧键，也不截后缀拼出同一键。
3. 若取得迁移依据，声明原键→新键的完整映射，独立检查唯一性、基数、关联和计数守恒；覆盖/删除权限仍需适用资源与范围的证据。不能以观测跨度或“完整包”标题替代证明。
4. 新候选始终执行当前 sample/full QA、独立 oracle 和事务发布校验。先在新 TestSession 验证升级、重传 no_change、旧输入不回滚、失败/取消不发布，再判断正式更新条件。不得自动处理现有历史导入。

目前缺少真实 SA 跨版键迁移/替代政策的充分官方证据及对应端到端发布验收；当前资料不支持宣称全州所有历史版本自动更新。WA/NT/全国等 research_only/access_limited 能力仍按实现记录逐项列出，不升级为全部可导入。

## 运行、回退与剩余边界

详细步骤见 [ROLLBACK.md](../../ARSIA-Integration-20261003/evidence/maintenance-20261004-01/ROLLBACK.md)：先重新确认队列/Studio/源码，再停止已验证归属的服务；逐文件核对当前哈希后恢复原内容，新文件移至专属 quarantine 而非删除；存在并发修改即停止。重启后 PID 和端口必须重新发现，不沿用旧记录。数据库/Studio 备份不授权自动还原或迁移。

正常前端当前为 `npm run start`，工作目录 ARSIA，`ARSIA_NEXT_DIST_DIR=artifacts/maintenance-build-20261004-03`，`ARSIA_ANALYSIS_IMAGE=sha256:3a6763eaea6979b09a76856759168e5d9ce52871ea12cb062dd212d3cabe5e17`；npm PID 8771、Next PID 8827，启动收据 M/frontend-normal-final.json。当前已运行，不要重复执行启动命令。后端直接运行 `pipeline/.venv/bin/python -m arsia_pipeline.dev serve` 及正常库的 `-m arsia_pipeline.worker`，分别显式设置 `ARSIA_IMPORT_CONFIG` 为绝对 runtime 路径、`PYTHONPATH` 为绝对 pipeline 路径。禁止用带 initialize/migrate 的 dev up/init 代替；manual 只运行 API。

正常 Studio schema0 保持只读兼容；写功能需要用户另行选择显式备份迁移，本维护不执行。剩余数据能力是上文 ACT 历史身份绑定、真实官方键迁移/跨版发布，以及来源矩阵列明的 research_only/access_limited。任意 ETL、Linux/多人/公网部署、未知原始来源的普遍成功率均未验，不从当前通过数推断。
