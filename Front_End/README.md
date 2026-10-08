# ARSIA 当前正式本地版本

用户于 2026-10-08 确认当前 ARSIA 为正式使用基线。唯一正常运行目录是 **`Workspace/ARSIA`**，唯一网页入口是 **http://127.0.0.1:3100**。`Workspace_Github/Front_End` 为本版本的源码同步副本，不再作为独立展示版或另一套数据环境。

版本归属、同步边界和维护规则见 [当前基线](docs/CURRENT-BASELINE.md)。旧候选、旧端口和历史实验记录仅供追溯；不能自动应用其补丁、恢复旧任务或替换当前数据。

## 日常使用

先复用已经运行的 3100 服务。需要启动时，在 **`Workspace/ARSIA`** 执行：

```sh
npm run services:status
npm run services:start
```

需要 Node.js 22.22.x 或以上的 22.x、Docker Desktop 及本机已有运行配置。启动器核验资源归属，复用现有数据库、API、worker 与网页，不自动迁移数据库或恢复历史任务。详见 [本地服务说明](docs/LOCAL-SERVICES-20261008.md)。

日常开发也在 ARSIA 完成。改动前检查当前文件和进程，保留未提交修改；必要构建放在独立输出，验收后仅重启属于 ARSIA 的网页进程。不要另开第二个正常预览或覆盖运行中的构建。

## 当前应用

- **Overview**：来源、日期、指标、趋势及有证据绑定的行政区地图。
- **Analytics**：Trends、Severity、Spatial；支持 All 和单州视图。已包含最新卡片间距及底部文字清理。
- **Studio**：Explore 问答和资源、Document 全宽编辑、Findings、研究管理与导出；保留实际 AI 和数据工具链。
- **Data**：数据目录与导入入口整合；保留宿主授权、QA、候选和发布门禁。旧 `/imports` 路由不构成第二套版本。

当前普通本地 release 为 `local-integrated-v1` / `ff8b9868-515f-48c4-95c0-33ffbae73430`。原 `official-v1` / `bcc5da57-25f2-41ec-9925-bef421b02671` 是另一个明确标识的数据快照，不可混用或静默替换。应用版本与数据版本是不同概念。

NSW、VIC、QLD 的当前 2020–2024 统计和行政区派生分析已经接通。严重程度、速度区间和地图派生结果只有在当前输入、发布和来源证据绑定通过时才可用。来源统计口径仍不同；这不代表所有州、任意文件、所有历史版本或正式事故点地图都已验收。

## 源码同步与本地资料

`Front_End` 同步应用、服务端接口、Studio、AI、pipeline 源码、测试、文档、锁定依赖及可分发聚合数据/边界。它不获得本机密钥、业务数据库、Studio 数据库、原始数据、上传、历史运行目录、模型运行时二进制或数据卷。

正常研究内容仍保存在 ARSIA 的 `artifacts/studio/research.sqlite`；导入运行配置与输出保留在 ARSIA 原位置。不要把同步副本当作包含这些私有运行资料的第二套安装，也不要在其中另建正常数据库。新机器的完整运行配置需要单独受控安装。

## 检查与证据

使用 `npm run typecheck`、针对受影响文件的 lint，以及 `npm run build` 检查改动。写入测试、模型调用和数据库测试必须使用明确隔离的环境，不能把浏览器 profile 当成数据库隔离。

当前版本的界面验收与同步哈希保存在本轮 `artifacts/` 记录中。历史 [VERIFICATION.md](VERIFICATION.md)、[AI.md](AI.md)、[STUDIO.md](STUDIO.md)、[IMPORTS.md](IMPORTS.md) 及 `docs/` 的日期文档保留原结论与限制；日期更早的入口或操作说明不覆盖本文件和当前基线。

源码同步不等于提交、推送或公网部署，也不使历史未验证能力自动通过。
