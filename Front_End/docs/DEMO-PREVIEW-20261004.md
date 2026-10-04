# Front_End 展示副本 · 2026-10-04

该展示副本现已迁至 `Workspace_Github/Front_End`（原路径为 `Ass2-temp/ARSIA`），基于 `peixian/arsia-platform` 的 `362e8eb`。运行地址为 http://127.0.0.1:3101 。主项目只读参考：16 个参考文件复核哈希未变，3100 原服务 PID 82112 未重启。没有连接、复制或迁移主项目数据库，没有运行导入、worker 或 Studio。

## 已完成

- 导航调整为 Overview / Analytics / Studio / Data；Studio 为与其他导航相同外观及 hover 的普通按钮，点击无动作，没有页面或后端。
- 删除 Imports、Reports 页面及原有导入模拟器、轮询、相关服务契约；Agent 请求白名单也移除这两个旧页面。副本原本没有真实上传后端。
- Data 改为紧凑三行数据目录、文件上传/来源链接两种展示模式与资料提示。目录为随副本提供的 NSW/VIC/QLD snapshot 展示内容；上传、输入、继续按钮禁用；切换展示模式不请求 API。
- Overview、Analytics、图表、样式及相应展示辅助函数从主项目文件快照对齐。保留副本的固定 official-v1 数据服务，不引入主项目本地 release 发现、数据库、导入或 Studio 逻辑。移除 Analytics 保存到 Studio 操作。
- 地图沿用副本原有七级色阶、按数量分级规则、Lower/Higher 图例；新增主版右下角地区搜索与缩放/重置/全屏按钮，移除地图内左上角 LGA 下拉框。
- 注意：这套原始地图色阶表示事故数量，不是严重程度。右侧 Crash severity 图表仍单独展示严重程度，来源口径仍独立。

## 验收

- `npm run lint`、`npm run typecheck` 通过。
- `ARSIA_NEXT_DIST_DIR=.next-demo-build npm run build` 通过，独立输出，开发服务仍在 3101。
- `npx tsx --test tests/analytics.test.ts tests/map-viewport.test.ts tests/fixtures.test.ts tests/agent.test.ts`：51 项通过。年度数据断言补充主版新增的月份覆盖字段；删除只验证已移除导入模拟器的过时测试。
- 真实 Chromium：验证导航及 Studio 占位、Data 两种模式、深浅主题、390px 小屏无页面横溢；Analytics 切换 VIC / Yearly / Lives lost 并刷新保留；VIC 地图搜索 Melbourne、LGA 联动、缩放/重置。控制台无错误或警告。
- `/`、`/analytics`、`/data` 返回 200；`/imports`、`/reports`、`/studio`、`/api/data/imports`、`/api/studio` 返回 404。
- 没有验收真实上传、发布、Studio、AI 请求或沙箱执行；前两项和 Studio 按要求不提供功能。Overview/Analytics 仍使用副本原有静态官方来源快照，不能当作主项目最新发布的数据。

构建、lint、单元结果、参考哈希与验收 JSON：`artifacts/demo-refresh-20261004/`。
浏览器截图与快照：`output/playwright/demo-refresh/`。

## 启动与局部回退

在本副本目录执行 `npm run dev -- --port 3101`。已有 3101 服务时直接访问，不要重复启动或停止 3100。

修改前的源文件、测试及配置备份位于 `artifacts/demo-refresh-20261004/before/`；改动清单位于同目录的 `changed-files.json`。回退时先核对没有后续修改，仅恢复清单中的原文件；新增文件可移到单独的回退保留目录。不要整体 reset、清理未知文件或覆盖主项目。`next-env.d.ts` 为 Next 自动生成文件，在本副本重启开发服务后重建即可。

未提交、推送或部署。

## 展示细节调整

按追加要求删除地图下方 “Source definitions differ. Counts are not comparable risk rates.”；Studio 保留普通导航外观与 hover，点击不跳转；共用详情弹窗只展示 DATA & EVIDENCE、标题、说明和信息表，不再展示表格下方的原始结果、证据链接、来源说明或底部提示。原数据和证据没有从数据服务中删除。调整前备份：`artifacts/demo-detail-refinement-20261004/before/`。

迁移后接口与项目数据接入说明以根目录 [README](../README.md) 为准；原副本 Git 信息在迁移记录指定的位置保留，Front_End 是父仓库的普通目录。
