# 本地 Imports 流水线验收记录

验收日期：2026-10-01（Australia/Sydney）。这是当前工作区的本地开发实测，
不是服务器部署或旧课程流水线的验收替代。实现未提交、未推送。

## 交付与使用

网站入口是 `http://127.0.0.1:3100/imports`。当前后台已启动。页面可以真实上传
一个州的文件组合，查看持久任务进度、补充缺失文件、复核映射、取消/重试、
查看 QA 和下载证据，再读取独立的 LOCAL TEST 发布结果。页面关闭后已提交任务继续运行。

重启电脑后，先启动 Docker 和已有的 3100 网站，再从 `ARSIA/pipeline` 运行：

```sh
.venv/bin/python -m arsia_pipeline.dev up
.venv/bin/python -m arsia_pipeline.dev status
```

`dev stop` 只停止专属实验后台并保留数据；`dev restart` 用于代码更新。
新机器安装需要 Python 3.12+，见 [README](README.md)。现有开发启动器使用本机已安装的
PostgreSQL 镜像 ID；可选 Compose 是独立 Linux 演练骨架，尚未构建或部署。

系统使用 Next.js 流式上传桥接、Python FastAPI、一个重型 worker、SQLite 磁盘关系索引和
独立 PostgreSQL。数据库保存 jobs/attempts/events，真实 COPY 写入 Canonical，核对后事务发布。
发布版本包含 source→batch 映射，更新一个来源保留其他来源；相同指纹返回 `no_change`。
它没有运行旧 Raw/Vault/DW 或 E SQL FP1；保留旧源规则及作者归属，并提供独立验证证据。

## 七份真实原始文件的完整验证

原文件共 406,215,298 bytes，2,118,028 条原始记录。原始记录包含事故、车辆、人员、节点，
不是 2,118,028 起事故。完整文件的键和关系先验证，随后按既有规则选择 2020–2024 年。

| 来源 | 文件组合 | 原始记录 | 事故 | 致命事故 | 死亡人数 | 伤亡人数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| NSW | 2 XLSX | 263,151 | 92,082 | 1,388 | 1,507 | 78,154 |
| VIC | 4 CSV | 1,439,470 | 72,170 | 1,182 | 1,265 | 91,798 |
| QLD | 1 CSV | 415,407 | 66,624 | 1,304 | 1,424 | 88,609 |

首次通过私有 API 完成解析、关系检查、真实 PostgreSQL COPY、发布，三个任务均 `succeeded`。
提交到终态的轮询观测时间分别约 27.2 / 27.2 / 15.1 秒，不含上传时间。

随后全部文件通过实际 Next.js `127.0.0.1:3100/api/imports` 上传，包含 213,483,181 bytes
的 QLD 文件，再次解析并检查数据库，三州均正确返回 `no_change`。
**836 项数值、类别、范围、限制及结果检查全部通过**，其他来源的 batch 保持不变。
年度和月度四项指标、严重程度、NSW 单位类型均对照未改写的现有 snapshot。
最终数据库只读核验也通过：

| 来源 | Canonical units 实际行数 | 可参与单位统计 | 报告 |
| --- | ---: | ---: | --- |
| NSW | 170,747 | 170,747 | 来源定义的 traffic units，包含行人 |
| VIC | 132,372 | 0 | `null / unavailable`，保持受限政策 |
| QLD | 0 | 0 | `null / unavailable`，不凭汇总属性生成单位 |

单位主键重复、孤儿关系、错误 source_id 均为 0。VIC Person/Node 保留原始文件及关系证据，
没有伪造分析事实或修补未知关系。三州地图点均保持 unavailable，QA07 为明确的 limited。

## 差异判断

所有统计数值与现有结果一致，没有放宽数值容差。新严重程度表还列出原合同已经定义、
本次没有记录的 0 类别：NSW 的 `UNCATEGORISED_INJURY` / `__MISSING__`，
VIC 的 `__MISSING__`，QLD 的 `PROPERTY_DAMAGE_ONLY` / `__MISSING__`。

旧查询只返回实际出现的 GROUP BY 分组，新输出保留完整来源字典。这是可接受的表示差异，
对识别“定义存在但未观察到”更清楚；不是新增事故，也没有把未知值推断为其他类别。
首次验收脚本按字典形状比较，因此保留的首次报告显示 severity 项不相等。
最终脚本按类别并集逐项比较精确整数，并另行确认全部类别来自冻结源合同；原 oracle 未改动。

Generic 的缺失统计采取保守规则：任何参与记录的计数未知时，对应汇总为 null，
不把不完整合计当完整总数。这是新来源的明确规则，不追溯改动三州原口径。

## 自动化、恢复和 AI 实测

- Python：81 项通过，包含 24 项 Generic、23 项 native、34 项真实 PostgreSQL 后端测试。
  后端测试创建独立临时数据库，核验 marker 后只清理该测试库；没有 truncate 实验运行库。
- Node：全项目 110 项单元测试通过；AI 结构校验修改后再跑 4 项 advisor 测试通过。
  TypeScript 和改动范围 ESLint 通过。
- 浏览器：最终 4 项通过。覆盖真实上传→缺文件→补齐→发布→刷新/证据、失败保留旧批次、
  取消/重试，以及 mock AI 草案必须复核。已检查桌面与 390px 深浅色布局。
- 真正的 NSW 处理中取消成功，发布版本不变。另一 NSW 任务执行时强制终止专属 worker，
  PID、命令、cwd 和 active_job 均匹配后才注入故障。重启后保留 `interrupted` attempt，
  新 attempt 自动完成并返回 `no_change`，全部旧来源保留。
- 真实模型调用仅收到合成 WA 的表头及显式公共测试定义，没有发送原始记录。
  初次开发测试发现生成的 severity JSON 结构不符合合同，已加强明确字段形状、结构校验和
  最多一次格式修复。最终草案通过确定性 profile 结构验证；未确认草案被拒绝执行。
  对照合成夹具核验并明确确认后，真实入库得到 2 起事故、1 起致命事故、1 人死亡、
  4 人伤亡，所有其他来源保持不变。它不代表真实 WA 官方资料已完成适配。

测试仍有一个 Starlette/AnyIO 测试依赖弃用 warning，不影响通过结果。

## 隔离与资源证据

前后 SHA256/大小核对的 **17 个受保护文件全部不变**，包括七份原始文件、网站快照和
原有读取代码。`/api/data/metadata` 仍返回旧批次
`bcc5da57-25f2-41ec-9925-bef421b02671`。
Overview/Analytics/Studio 没有切换到导入测试数据；新结果只在 Imports 的 LOCAL TEST 中读取。
没有更新 GitHub、原课程数据库或服务器，也没有启动第二个网站预览端口。

网站桥接仅允许本机 3100 同源请求，后台 API 使用私有 Unix socket；独立数据库随机绑定
loopback 端口。单文件 512 MiB、每任务 1 GiB/12 文件、待处理输入 4 GiB 配额、处理并发 1。
原始上传、处理产物、失败证据和数据库均保留，完成任务不会自动清理。实验文件目录本轮约
1.95 GiB（包含多轮副本，不含数据库卷）；长期保留/清理策略仍需生产化设计。

macOS 27 / ARM64 / Python 3.12.6 上，第二轮 `no_change` 验证每约 2–4 秒采样一次：

| 来源 | 提交到终态 | worker RSS 观测最大值 | PostgreSQL 容器内存观测最大值 |
| --- | ---: | ---: | ---: |
| NSW | 24.2 s | 92.0 MiB | 221.4 MiB |
| VIC | 24.2 s | 83.5 MiB | 223.7 MiB |
| QLD | 15.1 s | 80.2 MiB | 221.9 MiB |

这是第二轮重新解析/验证并复用已发布 batch 的采样值，**不含新 batch COPY 的资源峰值**，
也不是 ru_maxrss、整机总内存或 Linux VPS 测量。证据另存 API RSS、容器 CPU 和主机内存页/
磁盘计数；主机计数包含其他进程。新实现与旧 21.8 分钟 / 3.46 GiB 的执行层不同，
不能把这两个实验当相同工作的严格性能对比，也不能据此保证 8 GB VPS 的容量。

## 支持边界

已知固定三州组合自动执行。其他州/领地可用 reviewed `generic-v1` 描述 CSV/XLSX 的
事故、单位和辅助表，并自动执行后续步骤；WA/TAS 的不同结构通过合成测试。
首次来源含义必须有证据并复核，已识别 native 文件内容改变需要新的源合同，
尤其不能用 Generic 绕过 VIC 四文件和精确例外政策。

当前不自动抽取 PDF/字典正文、不执行模型生成 Python、不推断坐标、不接受仅有汇总统计的
表充当逐事故记录。网站旧分析数据切换、生产认证/权限分离、备份恢复演练、Linux 容量验证、
自动保留策略和服务器部署均未实施。它们不会被本地成功记录误标为生产就绪。

## 证据与复现

私有且已忽略的 `ARSIA/artifacts/imports-development/` 中保留：

- `full-volume-2026-10-01.json`：首次真实发布及最初表示层差异。
- `full-volume-website-final.json`：836 项最终比较、三州 no_change、分别采样的资源信息。
- `database-final.json`：当前发布实际表行数、主外键、来源及单位口径检查。
- `recovery-live-final.json`：真实取消和进程丢失恢复证据。
- `ai-schema-live-validated.json` / `ai-fixture-end-to-end.json`：最终 AI 草案及确定性入库。
- `protected-files-before.json` / `protected-files-final.json`：原数据和读取代码未变。
- `python-tests-final.log` / `node-tests.log` / `browser-tests-final.log`：测试结果。

从 ARSIA 根目录重跑（只写独立本地实验环境）：

```sh
PYTHONPATH=pipeline pipeline/.venv/bin/python -m pytest pipeline/tests -q
npm test
npx tsc --noEmit --incremental false
ARSIA_BROWSER_CHANNEL=chrome npx playwright test tests/browser/imports.spec.ts
PYTHONPATH=pipeline pipeline/.venv/bin/python pipeline/tools/verify_full_volume.py --via-website --measure --output artifacts/imports-development/full-volume-new-run.json
pipeline/.venv/bin/python pipeline/tools/verify_database.py --require-official
```

`verify_recovery.py` 是单独 opt-in 的故障注入脚本，会终止匹配的实验 worker；
不要在别人正在使用实验库时运行。所有证据/原始数据/私有 runtime 和凭证均被 `.gitignore`
排除，不能把 `runtime.json` 或完整产物目录添加到 Git。
