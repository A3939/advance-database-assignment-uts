# Studio 研究工作空间

Studio 位于 `/studio`，使用项目已有的 ARSIA 主题、真实快照服务、只读 Agent、ECharts 和隔离 Python 工具。原 `/reports` 是未实现的空态，现跳转至 Studio。Overview / Analytics 保留原布局，仅增加必要入口。

## 结构

- `src/components/studio.tsx` / `studio.module.css`：研究列表、Explore / Findings / Report、上下文、证据、版本历史与响应式侧栏。
- `src/services/studio-contracts.ts`：研究、运行、发现、报告块、附件、版本契约。
- `src/services/studio-client.ts`：JSON 与 NDJSON 客户端。
- `src/server/studio/store.ts`：SQLite、事务、引用校验、乐观保存、运行去重、版本与文件完整性。
- `src/server/studio/collector.ts`：只接收服务器产生的工具事件，保存结果、证据、图表及附件。
- `src/server/studio/create.ts`：新研究、Analytics 重新查询、Ask AI 服务端完成回执的导入。
- `src/server/studio/export.ts`：Markdown、聚合 CSV、JSON 来源清单与真实附件的 ZIP。
- `src/server/agent/runtime.ts`：与 Ask AI 共用服务端模型配置和聚合数据运行环境。

## 存储与生命周期

本地目录为 `artifacts/studio/`，已由仓库 `/artifacts/` 忽略规则排除。`research.sqlite` 及运行中的 `research.sqlite-wal`、`research.sqlite-shm` 属于 Studio，不属于正式业务数据库。Node 22.22 的内置 `node:sqlite` 避免另设数据库服务，目前 Node 会发出实验性模块提示。

SQLite 保存研究 JSON、运行、问题/回复、草稿、结果、工具证据、发现及编辑历史、报告块和版本。研究附件以 BLOB 保存，保存时验证类型、文件名、字节数、内容格式和 SHA-256；下载再次校验完整性。它们是研究自有副本，不受原分析文件 24 小时过期策略影响。备份时需使用 SQLite 一致性备份，或在服务退出后一起备份该目录，不要只在写入过程中复制主文件。

正式快照仍从 `data/official` 和 `data/regions` 只读读取；没有业务数据库写入、导入或发布权限。localStorage 仅保存最后打开的研究 ID，不保存研究内容。

新分析冻结当时的上下文；之后修改来源、区域、日期、指标或备注，不改变之前的结果。变更上下文前自动创建版本。恢复只保存一个 Before restore 版本，并以选中版本更新当前研究；不会额外占用第二个版本槽。旧版本不会被覆盖。绑定的批次不可用时重新运行会明确失败，不换用新批次。

运行请求以客户端生成的请求 ID 去重。重试复用未完成运行，保留此前尝试记录，最多三次。完成结果不可作为重试目标，另行 Run again 会创建新结果。运行通过限时 lease 检测中断：客户端关闭/取消传播 AbortSignal；崩溃或重启后首次读取会根据执行进程及到期时间标记 Interrupted，而不是永久 Running。

保存字段使用版本号和事务，失败显示 Unsaved，并保留可重试的本地编辑。并发运行事件不会把整份客户端研究内容写回服务器。

## 接口

所有路由禁用缓存，检查同源浏览器请求；写入使用有界 JSON。研究 ID 和跨研究引用在服务端校验。客户端不得提交查询结果来充当证据。

- `GET /api/studio`：研究摘要列表，包括归档标记。
- `POST /api/studio`：创建研究；`kind: analytics` 用合法范围重新查询真实趋势；`transferId` 只读取 Ask AI 在成功完成后保存的服务端回执。
- `GET /api/studio/:id`：研究；`?history=1` 版本摘要；`?version=:versionId` 历史研究；`?catalog=1` 已接入数据字典、字段、覆盖与来源定义。
- `PATCH /api/studio/:id`：带 `revision` 的结构化操作，包括 rename/archive/draft/context/snapshot/restore、finding、报告块操作和跳过可选展示步骤。没有任意路径、SQL 或整体结果覆盖入口。
- `POST /api/studio/:id/runs`：带 `requestId`、问题和可选 `retryId` 的流式分析；上下文和已完成历史从服务器读取。NDJSON 除原 Agent 事件外包含权威 `study` 更新。
- `DELETE /api/studio/:id/runs`：取消本研究的本机活跃执行。
- `GET /api/studio/:id/artifacts/:artifactId`：研究自有附件，强制下载，不执行 HTML/JavaScript。
- `GET /api/studio/:id/export`：ZIP，包含 report.md、manifest.json、data/*.csv 和 attachments/*。没有虚假的 PDF 导出入口。

证据保留工具名称、经校验参数、请求上下文、实际结果、来源版本/批次、覆盖/限制和计算说明。多次运行的 E1 属于不同运行，引用由 runId + evidenceId 定位，不能跨研究复用。

## 分析与真实性

保持 `model-routing.ts` 当前路由：简单单来源查询采用 `gpt-5.6-terra/high`，推理、Studio 研究及 Imports 采用 `gpt-6.1-sol/high`；本轮没有调整路由或模型预算。不得将 `.env.local` 内容写入研究、日志、下载或客户端。界面统一使用 ARSIA Assistant。

工具覆盖核心指标、趋势、同口径期间比较、逐月变化贡献、原生严重程度、元数据、地域聚合、受控分组/排名、ECharts 与 Python。新增 monthly_contributions 使用实际月度聚合计算差值和对净变化的贡献；负贡献、超过 100% 或净变化为零都保留相应含义，空值不填零。

复杂研究可以产生 3–5 项任务计划，状态由实际工具事件更新；可跳过可选展示。计划不包含内部思维链，也不成为数值证据。历史回复仅用于理解追问，当前结论必须重新查询。研究备注和引用说明被当成用户材料，不能覆盖来源限制。

所有来源按 catalog 的 source ID 独立查询，不生成混合全国合计。历史州级快照严重程度只支持完整五年范围；新发布来源按已验证能力支持日期筛选。LGA 的月度衍生分布按实际数据查询。LGA 不等于城市范围或事故点；计数不等于风险率；无法验证的因果关系不能转成 Verified 标签。手动发现可保存但显示 No data evidence。证据关联也不代表结论已经人工验证。

## 运行和边界

继续复用 `http://127.0.0.1:3100`，无需新端口。前端 `npm run dev`；Python 需要已安装 Docker 正常运行及既有 `arsia-analysis:2` 镜像。沙箱不连接网络，只读授权聚合副本，512 MB 内存、1 CPU、父进程 30 秒预算及容器独立 35 秒墙钟监督，每轮最多三次。容器有精确归属收据，父进程死亡或清理失败后仅允许按收据恢复清理，不能按名称前缀全局删除。禁用时返回明确不可用，不回退到宿主机 Python。

Agent 保持 12 轮、16 工具调用、240 秒、16,000 字回复上限。Studio 最多同时两项分析，每分钟 12 次启动；无无限自动付费重试。研究上限：128 项、每项 64 次运行、200 个发现、100 个报告块、50 个版本；单研究 JSON 8 MB，附件 100 个 / 64 MB，每个 4 MB，本地研究数据总预算 256 MB。容量以 UTF-8 字节统一计量；替换仅计净增量，达到 64 次运行后仍允许未完成运行的原位重试。达到限制会拒绝新增写入，不删除旧结果，导出仍可使用。

这是本地单用户工作空间，不是生产级账户隔离或团队协作系统。没有任意文件上传解析、外部资料抓取、SQL、正式数据修改、生产发布或新的任务队列。未完成和失败的分析不能作为图表/发现的有效结果导入；报告导出保留分析状态。

## 验证入口

- `npm run typecheck`
- `npm run lint`
- `npm test`
- `npm run test:sandbox`（Docker 集成测试）
- 历史 `studio.spec.ts` 会写普通 Studio，已从默认浏览器集合排除；新的隔离浏览器绑定尚未验收，不使用旧命令作为安全入口。
- `ARSIA_NEXT_DIST_DIR=artifacts/studio-build npm run build -- --webpack`

验证构建使用独立 `artifacts/studio-build`，不清理运行目录、不重启当前服务。Next 构建会自动补充 `tsconfig.json` / `next-env.d.ts` 的类型路径；本次构建前保存了原文件，完成后恢复原内容，保留用户原有修改。Studio 单元测试使用临时 SQLite，不写正式数据。浏览器验证研究以 Validation 命名并归档。`NSW 2024 changes` 为实际少量 API 联调产生的可继续研究示例，结果来自当前快照。

## 历史验证（2026-10-01；不代表本轮通过）

- TypeScript、ESLint、`git diff --check` 和隔离 production build 通过；3100 仍由原开发进程提供服务。
- 98 项单元测试通过，覆盖原有数据/Agent 服务与 Studio 持久化、独立范围、版本恢复、失败保存、重试去重、引用校验、可信导入及月度贡献计算。
- 6 项 Docker 沙箱集成测试通过，覆盖执行、文件、资源限制、取消、宿主文件/网络访问拒绝和修复重试。
- 38 项浏览器回归通过，涵盖 Overview、Analytics、既有数据真实性及 4 项 Studio 流程测试。Studio 验证宽度包括 1440、1280、820、390、320px，检查深浅主题、键盘/侧栏、草稿、Unsaved 重试、报告编辑、导出和上下文隔离。
- 少量真实调用完成 NSW 2024/2023 比较和逐月追问，生成交互图表及 CSV、PNG、Python；实际保存 Observation、报告块，刷新恢复，修改范围，查看并恢复历史，导出 ZIP 并通过 CRC 检查。2024 年 18,939 次、2023 年 18,711 次、净增加 228 次；逐月差值相加与净变化一致。
- 实测首页 Ask AI → Open in Studio、Analytics → Save analysis to Studio。测试研究已归档；保留 `NSW 2024 changes` 示例。
- 检查客户端开发/生产产物、研究存储、验证日志和示例导出，未发现服务端密钥内容；环境配置未覆盖。

这些验证针对当前本地实现与项目数据快照，不代表整个 ARSIA 平台或生产多用户环境完成验收。

## 显式容量、备份与升级

应用的 SQLite schema/document 当前为 v1。已有 v0 数据库按只读兼容方式打开；不因读取而写 lease、创建表或迁移。超出当前支持版本时拒绝写入。正常用户库本轮没有迁移。需要实际升级时，先结束该库的写入，再使用明确绝对路径；`migrate` 必须先创建新的完整一致性备份，目标已存在则拒绝覆盖。

```sh
node --import tsx scripts/studio-admin.ts capacity /absolute/research.sqlite
node --import tsx scripts/studio-admin.ts backup /absolute/research.sqlite /absolute/new-backup.sqlite
node --import tsx scripts/studio-admin.ts migrate /absolute/research.sqlite /absolute/before-migration.sqlite
```

容量命令只读并显示使用字节、总预算、研究/版本/transfer 数量和迁移状态。备份不依赖 UI 有剩余容量；不提供自动删除旧研究或覆盖恢复的命令。完整备份恢复应在服务退出后复制到新的工作区并检查应用版本及内容，不能覆盖仍在使用的库。达到研究数或版本数上限后的逐项整理仍需用户选择，尚无自动跨工作区迁移。

当前直接验收与边界见 [整体优化记录](docs/INTEGRATED-OPTIMIZATION-20261003.md)。
