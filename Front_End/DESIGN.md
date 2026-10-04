> 2026-09-29 地区层更新：单州地图现使用真实 LGA 名称匹配聚合，不再是边界空态。LGA 筛选联动指标与图表；匹配覆盖率不是坐标 QA 通过率。实现与限制见 [REGIONS.md](REGIONS.md)。

> 2026-09-29 AI 第一阶段更新：Ask AI 现在是真实只读分析 Agent。保留右侧面板，显示 OpenAI / project snapshot，支持增量文本、查询进度、证据、停止、重试和 New chat；更换页面或筛选重置会话。详细能力和限制见 [AI.md](AI.md)。

# ARSIA Web 设计规范

本文件整理用户 2026-09-29 的开发要求与后续真实数据接入要求。范围是本地 Web 分析界面及固定项目快照的只读展示；不是整个 ARSIA 平台的验收结论。

## 最新数据接入要求（覆盖早期演示设计）

本节优先于历史截图和旧演示要求。当前生产入口使用真实官方来源项目快照，`datasetVersion: official-v1`、`batchId: bcc5da57-25f2-41ec-9925-bef421b02671`，覆盖 2020–2024，`recordedAt: 2026-09-28T12:43:08.025519+00:00`。页面称为 Project snapshot，并明确不是 live data。此前验收数据库已清理、不再运行；前端无需连接数据库。

- 保留当前顶栏、四卡、左侧无边框地图及右侧双图布局，用真实聚合替换合成统计。来源切换保留同一批次；默认 All 分州展示，不计算全国总数。
- 四指标为 Crashes、Fatal crashes、Lives lost、Casualties。NSW 使用 Crash 级统计；VIC 仅报告 Accident 级指标，不能使用受限 Person/Vehicle 明细；QLD 为 casualty-crash 覆盖且没有 Unit 明细。指标定义和限制必须随分析、证据和导出保留。
- 月度趋势、热图与月份均值使用真实导出，不再按年度权重构造。仅完整 2020–2024 区间有严重程度分布；其他有覆盖区间显示 unsupported 及原因，不将“不支持”写成“没有事故”。未知指标保持 null，缺失不补零。
- 国家地图只将来源级事故计数映射到 ABS 参考州边界；州视图按真实源文件名称匹配的 LGA 计数着色，保留悬停、区域选择及未匹配说明。禁止虚构事故点或热点，不用配色暗示跨州风险可比。
- JSON 导出保留真实数据标记、筛选、版本/批次、定义和证据，不附虚构事故记录。records API 明确不支持；不恢复首页记录表。
- Data 页与证据说明固定批次发布 succeeded、QA01–QA06 pass、QA07 location limited，保留 `independentMemberSignoff: false` 和 `finalPlatformAccepted: false`；不能显示“全部 QA 通过”或“已完成全项目验收”。
- Ask AI 使用真实服务端 OpenAI Responses API 和受控只读工具；不执行任意查询或导入。Imports 继续明确为文件元数据预览，不宣称已清洗或入库。

实际只读 API、状态语义及 SHA256 校验见 [API.md](API.md)，固定快照、三州四指标总量和更新流程见 [README.md](README.md)。以下界面要求应在这些数据边界内实现。

## 当前界面要求（按 2026-09-29 后续反馈更新）

本节覆盖下方首版截图及此前修订中不一致的要求。首版截图只保留为设计来源；实现和验收以本节为准。

- 删除首页可见标题、副标题、v1.0 按钮；日期胶囊保持原尺寸样式，移到左侧独立筛选栏。
- 删除地图质量底栏、AI 分析摘要条、Crash records 整块和站点底栏；删除严重程度副标题。Ask AI 与图表证据入口保留。
- 顶栏通知按钮替换为明暗主题按钮。默认 dark；用户选择 light 后在本地持久化，刷新及页面切换保持选择。主题按钮提供明确名称、当前状态及切换反馈。
- light 使用完整语义颜色 tokens，覆盖页面、卡片、文字、控件、边框、地图及覆盖层、ECharts、tooltip、弹窗、popover 和 AI 抽屉；切换后已创建的地图/图表同步更新，不保留 dark 专用背景或文字。
- Source 默认 All。All 使用本地 ABS 2021 州/领地边界，以同一珊瑚红浓度尺度表示当前日期各来源的实际 recorded crash count，不再使用绿色 availability 图例。无数据地区使用中性底色，不生成数值或伪装成零；hover/标签说明缺失状态。颜色不表示跨州风险、严重程度率或可比性，也不构造全国总数。
- 点击有数据的州或标签，同步切换 Source，并在原 MapLibre 实例中用 700ms 相机过渡进入本地 LGA 地图；reduced-motion 下立即切换。
- All 的四卡分州列值，趋势按州分线，严重程度保留各州原分类，不构造全国总数。选中州后恢复单州四卡和图表。
- 严重程度使用 item tooltip，关闭 axis pointer；仅柱体颜色和轻阴影作 180ms hover 过渡，不改变数据长度。
- 地图 canvas 不再常驻 ABS 署名；来源、CC BY 4.0 许可、年份、边界层级和链接移至 Map layer evidence，并保留 `public/geo/provenance.json` 的可追溯记录。
- 宽度 >1100px 且高度 ≥720px 时，Overview 按桌面视口分配可用空间，窗口放大时内容随之扩展；地图面板与右侧 severity 面板底边对齐，最下方保留 16–24px 防裁切空间。日期工具栏上下使用相等、紧凑的边距。更矮视口、平板和手机保持自然页面滚动，不以隐藏溢出裁掉内容。
- 固定快照性质通过指标定义、Data 页、导出与来源证据说明；AI 和 Imports 各自保留模拟标记。首页不恢复已删除的 Demo 文案或持续底部 Demo 行。

## 首版视觉来源（历史记录，不是当前待实现清单）

原始来源为用户截图 `codex-clipboard-ead33558-0952-4a4e-965e-e4cf02818631.png`。沿用真实 React 组件、ECharts 图表和 MapLibre 地图，不把截图作为背景；保留四张指标卡、左地图与右侧趋势/严重程度的主要布局。

- 顶部左侧 ARSIA；居中胶囊 Overview / Explore / Data / Imports / Reports；原截图右侧为设置、通知、头像。**通知已被后续主题切换要求覆盖。**
- 原 Overview 包含 Road safety overview、日期范围、来源、版本、Export、Ask AI。**可见标题、副标题及版本已删除；日期、来源、Export、Ask AI 保留。**
- 四卡：Crashes、Fatal crashes、Lives lost、Casualties。
- 左大地图 Spatial exploration；右上 Crashes over time；右下 Crash severity 水平条形图。
- 原底部紧凑分析摘要、可展开 Crash records、地图质量底栏与站点底栏，**均已被后续删除要求覆盖**。
- 其他导航只提供基础页面、明确能力边界。Imports 不真实入库。UI 英文，开发文档中文。

## Tokens 与布局

统一在 `src/app/globals.css` 定义字体、颜色、圆角、间距、图表颜色和动效变量。下表为默认 dark 基准；light 必须提供完整的语义对应值，而不是只更换页面背景。主题偏好仅作本地界面设置，不改变数据、来源或分析状态。

| Token            | 值 / 用途                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------ |
| --font-sans      | 本地 Inter；system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC, sans-serif 回退 |
| --background     | #101614                                                                                          |
| --surface        | #18201D                                                                                          |
| --text-primary   | #F3F5F4                                                                                          |
| --text-secondary | #A8B2AD                                                                                          |
| --lime           | #B7F34D，主操作、选中态和趋势                                                                    |
| --coral          | #F47771，严重程度与地图强调，始终附文字                                                          |
| --radius         | 14px；胶囊 99px                                                                                  |
| --space-1…5      | 8 / 16 / 24 / 32 / 40px                                                                          |
| --duration       | 200ms，通常 150–250ms                                                                            |

桌面以视口剩余空间驱动地图和图表尺寸，不保留阻止宽屏扩展的页面宽度上限或固定图表行高。页面边距 24–32、卡片间距 16、主要卡片内边距 20–24；底部保留 16–24px。正文 14–16px，指标数值 36–40px，紧凑图表说明一般 12px；首页可见大标题已移除。数值使用 tabular-nums 和 en-AU 千位格式。细边框与轻阴影，不使用大面积磨砂/强发光。平板重排、手机单列，过矮桌面和小屏自然滚动，不使整页横向溢出。

## 必须可用的交互

- 来源和整月日期筛选联动 KPI、趋势、地图与导出上下文；范围外显示无结果，不填零。严重程度仅完整五年区间可用，子区间显示不支持原因。
- Yearly / Monthly，ECharts tooltip；图表 evidence 同时提供键盘可访问数值。
- MapLibre 缩放、重置、全屏、州 hover/click 与可聚焦州标签；单州仅参考边界，无事故热点。无 WebGL 时使用同一本地 GeoJSON 的 SVG 降级层。
- 首版 Records 搜索、排序、分页的首页交互要求已撤销。官方快照只暴露聚合，不支持事故级记录；不恢复首页记录表。旧示例记录仅保留在单元测试 mock 中。
- Export 当前选择，JSON 包含 demo: false、筛选、指标定义、覆盖、版本/批次和来源证据，不附虚构记录。
- Ask AI 右侧抽屉，可关闭、键盘操作；建议问题、输入、模拟回答、上下文与证据。
- 所有设置/主题/头像/证据入口有明确反馈。未连接功能使用空态或能力说明。
- 输入、焦点、键盘、Escape、对话框 focus trap；尊重 reduced-motion。

## 数据真实性与历史演示范围

真实统计来自经过审查的固定项目导出，三州四指标口径各自保留。完整区间 NSW 为 92,082 / 1,388 / 1,507 / 78,154；VIC 为 72,170 / 1,182 / 1,265 / 91,798；QLD 为 66,624 / 1,304 / 1,424 / 88,609，依次为事故、致命事故、死亡人数、伤亡人数。它们不是全国可池化总量，也不是当前政府实时数据。

区分 available（包括已知零）、unknown（有观测但指标未知）、unsupported（能力或统计口径不支持）和 no_results（所选月份无覆盖）。无数值必须配状态说明。严重程度子区间不能按比例分摊，单州地图不能从 hash 或示意权重生成区域数值。

边界为 ABS ASGS 2021 州/领地与 ASGS 2024 LGA_GEN，CC BY 4.0；Map layer evidence 提供署名、来源和链接，`public/geo/provenance.json` 保留详细记录。经过制图泛化的边界用于参考，不是法定边界。参考边界可显示不意味着官方事故定位可用；不采用早期截图的 92% / 98% 等作为真实 QA。

历史演示曾采用 NSW 18,420 / 172 / 188 / 8,640 的基准、合成月份、每月 3 条虚构记录和三组示意热点。这些要求已被真实快照接入覆盖；仅旧 mock/fixture 单元测试可保留，不进入生产 provider、地图或导出。

## 工程与接口

Next.js / React / TypeScript，Tailwind v4、shadcn/ui Radix primitives、Motion、ECharts、MapLibre、Lucide。字体、地理边界本地提供，不要求外部服务或私有 key。

组件通过 `src/services/index.ts` 的 ArsiaService 与 `http-provider.ts` 获取真实统计；契约在 `src/services/contracts.ts`。GET `/api/data/{overview,timeseries,severity,map,records,metadata,evidence}` 由 `src/server/official-data.ts` 读取固定本地聚合文件，校验 reader/provenance SHA256、批次和版本。生产链路不导入 mock provider；旧 fixture 仅供单元测试，Imports 使用独立 `import-preview.ts`。

统一 source/dateRange/datasetVersion/batchId；真实数据响应包含 demo: false、来源、定义、单位、覆盖、状态和 evidence。Agent async iterable 读取真实只读 API，再生成明确标记的模板回答；无模型/SSE 服务。导入状态契约包含 queued/running/needs_input/succeeded/failed，当前元数据预览停在 needs_input，不伪装解析/入库成功。

地图和图表动态加载；筛选调用 setData/setOption 而非重新创建画布；容器变化同步 resize，主题变化同步颜色。记录服务保留分页契约。动效优先 opacity/transform。复杂后台、真实 Agent、Redis/Celery/LangGraph 等不在本轮范围。

## 完成检查

类型检查、lint、官方快照与保留的 fixture 单元测试、production build；实际浏览器检查首页、筛选、图表、地图、AI、导出、Imports、导航及响应式。补充验证 dark 默认、light 本地持久化、两主题地图/图表/弹窗、All count 浓度与缺失状态、Map layer evidence 署名，以及 1100/1101px 宽和 679/720px 高断点、宽屏扩展、地图/severity 同底边、16–24px 底部余量。数据验证还应覆盖固定批次/hash、整月范围、三州四指标、严重程度子区间不支持、未知值不补零、州地图无虚构点与明细不支持；不再要求首页 records。以上是验收要求；实际执行范围与结果见 `VERIFICATION.md`，不据本文件宣称通过。不改原流水线、数据库、分支或其他进程；保留已有未提交工作，不部署、不提交推送。

## 统一顶栏与浅色主操作（当前）

以用户最新图 3 为准，五个页面共用 Data/Imports/Reports 原有顶栏尺寸：桌面高度 88px，标识圆形 44px，顶部与下边线之间居中、两侧各约 22px。移除 Overview 的独立压缩顶栏和标识/导航放大规则；此前 2/3 高度方案已被本要求覆盖。保留分析区全宽布局和各页现有横向容器。地图底边、Crash severity 的高度和位置保持；顶栏占用空间的变化由地图与趋势区域承担。手机继续使用统一的双行导航。

Ask AI 使用独立语义 tokens：dark 保留青柠色；light 使用灰绿色底 `#E1EBD9`、深绿色字 `#34502C` 和柔和边框 `#B9CDB0`，hover 使用 `#D4E3C8`。不更改其他主要操作的颜色。

## Analytics（当前）

- 顶部导航在 Overview 右侧使用 Analytics，替换重复的 Explore；旧 `/explore` 路径重定向到 `/analytics`。Overview 保留原布局。
- Analytics 使用自然纵向滚动和现有 1760px 容器，沿用统一 88px 顶栏、Inter、明暗主题及语义 tokens。标题/操作、来源/日期、紧凑三项摘要后，按「趋势与同比 → 月份分布 → 严重程度与数据」排列。
- 以单州开展深入分析。继承当前日期/版本；从 All 进入时明确选中 NSW，并同步全局和 AI 来源上下文。支持 NSW/VIC/QLD 切换，禁止跨州混合总量或严重程度率。
- 趋势支持四指标及年/月粒度；同比严格使用最新所选年份与上一年相同月份，缺少月份或基期为零时不生成百分比。前期查询可超出当前显示窗口，但不混入当前统计。
- 年×月热图可鼠标/键盘逐月检查四项数值，并将该月应用为全页筛选。月份均值仅使用实际可用的快照月份，不把缺失填零。热图是描述性分布，不能单凭计数推断成因或暴露量校正后的风险。
- 严重程度数量/占比保留来源原分类，仅完整五年可用；子区间显示明确不支持原因。tooltip 不使用长轴指示虚线。数据表直接展示同一套月/年聚合，提供排序、年月切换和分页，不恢复首页已删除的 Crash records。
- Project snapshot 标记简洁且清楚；计算公式、版本及详细说明放入方法弹窗和图表值入口。减少重复说明与装饰性文案。导出包含当前分析、筛选、前期比较和来源元数据，明确 demo: false；AI 模拟标记单独保留。
- 新增组件样式隔离在 `src/components/analytics.module.css`；图表动态加载，实例保留，主题和数据变化更新 option。手机图表重排，宽表格/热图仅在局部横向滚动，整页不横向溢出。

## Overview 自然延展地图（最新）

- 地图保留原双列网格占位，移除卡片边框、圆角、阴影、独立底色及 Spatial exploration / Illustrative layer 标题。顶栏、四张指标卡、右侧趋势和严重程度卡片的几何位置不变；Analytics 不调整。
- `.seamless-map` 局部将 `--map-background` 映射至页面 `--background`，MapLibre background layer 与 CSS/SVG 使用同一底色。画布向左延伸到距视口边缘 8px，利用原标题高度放大真实地图，不改右列宽度或间距。
- `src/lib/map-viewport.ts` 为首次展示、州切换、窗口变化、重置和备用 SVG 共享 fit padding / Mercator 比例。国家视图在可用留白中偏向左下；州视图保留边界可读范围；手机为底部浮动操作留出空间。
- 主视图延续既有澳洲本土＋Tasmania 范围，不缩放到所有外部领土；本地 ABS GeoJSON 与既有布局保持，计数改用真实来源聚合；州视图保持中性边界。SVG fallback 使用 Mercator 和统一缩放，不独立拉伸经纬度，并保留州文字标签。
- 图例、缩放、重置、全屏保持轻量悬浮，Map layer evidence 归入同一浮动按钮组，保留边界来源与许可入口。手机图例和操作分层显示，避免碰撞。
- 国家视图底部额外保留控件安全区，防止 Tasmania 南端被按钮遮挡。原示意州热点及 Sydney/Wollongong 等热点标签不用于官方快照；单州参考边界不生成事故点或区域数值。

## ARSIA Assistant 面板（2026-09-29）

- 使用紧凑的 76px 标题栏，只显示 ARSIA Assistant、新建会话、关闭。移除大标题、供应商标签和独立 CURRENT CONTEXT 区块；当前筛选继续通过请求上下文与证据传递。
- 桌面最大宽度 560px；窄屏全宽，输入框固定底部。四个轻量分析建议，证据默认折叠。
- 回复内展示 ECharts 及可查看数据表、独立下载卡片；失败/停止可以重试。使用既有主题变量、字体、焦点和 reduced-motion 规则。
- 不展示模型供应商品牌，不声称模型由 ARSIA 自行训练。
