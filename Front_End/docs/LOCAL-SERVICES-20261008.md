# ARSIA 本地完整运行入口

主项目为 `Workspace/ARSIA`，统一网页入口为 http://127.0.0.1:3100 。这是当前单用户本地安装，未进行公网部署，也没有修改数据的官方身份和发布门槛。

## 日常命令

先打开 Docker Desktop，然后在 ARSIA 目录执行：

```sh
npm run services:start
npm run services:status
```

`services:start` 复用当前 3100 网页、原 PostgreSQL 数据库与已有 API/worker；缺少进程时启动对应进程。数据库因 Docker 重启重新分配端口时，核验容器/卷/数据库身份后修正私有连接。网页没有生产构建时先执行 `npm run build`，Python 分析镜像缺失时执行 `npm run sandbox:build`。不会自动下载或替换 Codex 模型配置。

启动器不初始化数据库、不执行迁移、不恢复历史导入。冷启动 worker 前，若存在排队或未结束任务，停止并报告，避免无意重放。已经运行的 worker 会直接复用，不打断它当前的工作。任何未归属本项目的 3100 进程均不接管。

需要停止时：

```sh
npm run services:stop
```

停止前检查在途导入与 Studio 活动，只停止本项目网页、私有 API 和 worker；保留数据库容器运行、数据卷和全部记录，不关闭共享 Docker Desktop。该命令不取消任务。若提示活动任务，请先等待或人工处理，不使用全局 kill/pkill。

## 已接通服务

- Next.js 生产构建网页：3100；Overview / Analytics / Studio / Data。
- 原 PostgreSQL 容器：仅 loopback 动态端口，凭据不进入浏览器。
- 私有 Unix-socket API 与串行 worker：经同一 3100 HTTP 桥访问。
- 已有 Codex runtime、工具桥和宿主模型网关；没有修改模型或预算规则。
- Python 分析沙箱：`arsia-analysis:2`，无网络、只读根文件系统、独立资源限制。
- 原导入执行器镜像：保留 runtime 中的固定身份，不覆盖现有导入配置。
- Studio SQLite、资源和导出；PDF 使用现有 Chromium 配置。

## 本次确认及限制

2026-10-08 已恢复原 release `ff8b9868-515f-48c4-95c0-33ffbae73430`，原 3 个已完成任务没有重试。实际浏览器验证无参数 Studio、Overview、Analytics、Data 和导入页；数据源为当前已发布目录，不自动换成其他快照。

一次真实 Ask AI 比较 NSW 2023 与 2024 年事故数，经过模型和数据工具返回 18,711、18,939、增加 228，模型为 gpt-6.1-sol。发生 5 次供应方请求，均有用量回执。没有创建新的导入或 Studio 研究，没有进行发布。

`services:status` 的 `ai_configured` 只代表有配置，`ai_live_check` 明确注明该命令不调用模型；不把配置检查称作实时模型成功。镜像与运行时准备检查也不等于一次新自主导入。此次未重新验证所有数据源、任意新文件或整套 Agent 自主导入能力。

详细备份、测试、浏览器、用量及只读保护核验在 `artifacts/local-services-20261008-210139/`。私有 runtime 备份不应提交或公开。未提交、推送或部署；不安装开机任务或定时任务。
