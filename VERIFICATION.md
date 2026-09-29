# 2026-09-29 LGA 名称匹配扩展验证

当前预览：http://127.0.0.1:3102 ，构建目录 `.next-regions`。原 3100/3101 服务保持运行。

- 类型检查、ESLint、production build 通过；71 项单元测试通过（新增 9 项地区验证）。
- 既有 26 项浏览器回归：25 项首轮通过；剩余 1 项修正旧“边界不可用”空态断言及 GeoJSON worker 就绪等待后复测通过。未将 canvas 已挂载误认为边界已可交互。
- 原文件 hash/行数/独立事故键校验；3 州 × 60 个月 × 4 指标 = 720 项数值对账；各州全期严重程度逐项相等。未匹配部分不丢弃。
- 原生多边形点击：Lachlan LGA → 84 起事故；Sydney LGA → 2,932；筛选 2024 → 641。四指标、趋势、严重程度同步，地区证据含 SYDNEY/SURRY HILLS 等原生标签。
- 地图 hover、地区下拉、清除地区、来源切换、证据链接可用；Analytics 保留并可清除地区筛选。深浅主题、390px 手机无横向溢出；既有 1280/1440/1920/2560 布局回归通过。
- 人工浏览器故障模拟：禁止 WebGL 时，本地 SVG 可用；键盘 Enter 选择 Sydney 多边形得到 2,932，aria-pressed 同步。
- 一次真实 OpenAI 问答：Sydney LGA / 2024 返回 641 起，Town 前三 SYDNEY 125、SURRY HILLS 57、ALEXANDRIA 48；与实际工具结果一致，说明 LGA 并非整个悉尼。E1 证据可打开；切到 Newcastle 后旧会话清空、上下文更新。没有新增批量付费测试。
- 正常浏览器交互未发现 JS/console error；仍可观察到 Next.js 非阻断的 CSS preload 提示。

截图：`output/playwright/regions-nsw-dark.png`、`regions-sydney-light.png`、`regions-mobile.png`、`regions-vic-dark.png`、`regions-agent.png`。单元测试日志：`output/playwright/regions-unit.log`。

方法、覆盖及尚未开放的坐标功能见 [REGIONS.md](REGIONS.md)。这是独立前端派生层验证；原 QA07 仍 limited，不是整个 ARSIA 平台验收。

---

# 第一阶段 OpenAI 只读 Agent 验证 · 2026-09-29

当前新增真实 OpenAI Responses API 路径。下面的历史“模拟 AI”记录不再描述当前 Ask AI；Imports 仍保持模拟。

- `npm run typecheck`、`npm run lint`、`ARSIA_NEXT_DIST_DIR=.next-agent npm run build` 通过；隔离构建避免修改 3100 服务使用的 `.next`。
- `npm test`：62/62 通过（含 18 项新增 Agent 工具、算术、校验、上下文、循环上限、取消与错误安全测试）。日志 `artifacts/agent-unit-tests.txt`。
- `ARSIA_TEST_URL=http://127.0.0.1:3101 ARSIA_BROWSER_CHANNEL=chrome npm run test:e2e`：26/26 通过，26.5 秒。现有 AI 传输回归使用明确的测试拦截，不产生付费模型请求。日志 `artifacts/agent-browser-regression.txt`。
- 另以 Playwright CLI 操作真实浏览器：API 失败提示及 Retry、失败内容不进历史、连续追问携带新鲜上下文、切换来源/日期/页面清空历史、截断流错误、停止生成、键盘输入、390px 浅色和桌面深色无横向溢出。
- 真实 API 联调共 5 个用户问题/追问（内部受控工具循环会包含多次 Responses 请求），模型 `gpt-6-luna`。NSW 四指标与已验证快照一致；2024 对 2023：事故 18,711 → 18,939，差值 228 / 1.22%；死亡 340 → 327，差值 -13 / -3.82%。中文追问正确保持范围，并明确无法证明下降原因。
- 多工具边界问题验证：VIC 2024 severity 返回 unsupported，VIC 2025 trend 返回 no_results，metadata 说明事故坐标不可用。实际查询范围、回答和证据保存于 `artifacts/agent-live-boundary-verification.json`。
- 联调发现并修复：Next.js localhost/127.0.0.1 地址规范化导致的同源误拒绝；模型用全五年严重程度代替用户请求单年的行为（收紧 exact-date 工具规则后真实重试通过）；小于 0.01% 的非零严重程度比例不再在工具结果中舍入为零。
- API 边界：跨源 403、无效来源/批次 400、GET 405、过大请求体 400；这些验证在调用模型前完成。超时、provider 错误脱敏、循环上限和中途取消由确定性测试验证，未故意消耗账户额度触发真实限流。
- 证据弹窗显示服务器生成的来源、实际范围与摘要，完整工具 JSON 可展开。最后一次界面证据检查使用已录下的真实回复回放，不增加付费调用。
- 密钥存在性只输出布尔值；没有输出或复制密钥、没有修改 `.env.local`。检查服务端引用、客户端构建文件和验证日志，未发现密钥格式串或客户端 OpenAI SDK / API endpoint。SDK logger 关闭，错误仅返回固定安全消息。

截图和手工交互脚本在 `output/playwright/`；独立 CLI 浏览器已与用户其他浏览器隔离。原有 3100 进程保留，新的生产预览使用 3101。

限制：固定项目数据快照，不是实时数据库；模型回复并非形式化正确性证明，需以工具证据核对；严重程度无单年数据、无事故位置与原始个人/车辆明细；无导入执行、写入、SQL、发布、会话持久化、登录鉴权或跨实例限流。未验证 Safari/Firefox/实体手机，也未宣称全平台验收完成。

---

# 真实项目数据快照接入验证（2026-09-29，当前）

当前默认数据来源已由 mock 改为只读官方项目快照；下方旧章节保留为历史验证，不代表当前仍使用虚构统计。预览：`http://127.0.0.1:3100/`。

## 数据与证据

- 来源：工作区 `artifacts/role-e-completion-20260928/official-v1/postgres/ac-evidence/e09-official/reader-results.json`，复制到 `frontend/data/official/reader-results.json`；175,283 bytes，SHA256 `fed5e2ea8736ce5db17fbdf1227cc4e6cafed2ec8fa3937956c218542e134e8d`。
- 成功批次 `bcc5da57-25f2-41ec-9925-bef421b02671`；runtime commit `1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5`；记录时间 `2026-09-28T12:43:08.025519+00:00`，分析覆盖 2020–2024。
- 原始 reader、manifest、raw-qa、source-metrics、dashboard、full-build、recovery-cost 哈希与 PR49/50 审阅证据索引一致；当前七个原始文件哈希与 manifest 一致（只读核验）。原 full-build 的 unknown_commit 是刻意注入的回包丢失；recovery-cost 明确恢复判定 succeeded、observed batch succeeded、当前批次匹配。
- 三州各 60 个月和 5 年的四项指标加总与来源总量一致，严重程度全期分类和事故总数一致。真实事故数 NSW 92,082 / VIC 72,170 / QLD 66,624；前端不计算全国总量。
- QA01–QA06 为 pass；QA07_LOCATION 为 limited。`independentMemberSignoff=false`、`finalPlatformAccepted=false`。原验收数据库和容器已清理，本轮读取导出快照，没有恢复、启动或修改数据库。
- `data/official/provenance.json` 仅含批次、规则范围、文件哈希、资源计数和 QA 摘要，排除了绝对本地路径及原始 Person/Vehicle 记录。运行时对 reader 和 provenance 两份文件固定 SHA256 校验，失败返回 503，不回退 mock。

## 实际执行

- `npm run typecheck`、`npm run lint`、`npm run build` 通过；构建包含动态只读路由 `/api/data/[report]`。
- `npm test` **44/44 通过**：原 mock/投影回归继续保留；新增真实快照对账、All 不合并、跨年连续月份、未知与零分离、局部 severity 拒绝、地图/记录不造假、元数据净化和双文件哈希篡改拒绝。Analytics 新增 nullable 指标传播与 unknown 同比测试。
- 最终生产构建 `ARSIA_BROWSER_CHANNEL=chrome npm run test:e2e` **26/26 通过，0 跳过，25.1 秒**。覆盖真实数值、同批次/demo:false、年/月、同比、热图键盘/按月分析、分类占比、聚合表排序/分页、导出、证据、真实统计的模拟助手回复、导航和 Imports 模拟。
- HTTP 错误路径：无效州、无效日期、非整月、错误 granularity → 400；未知报表 → 404；POST → 405；错误 batch → unsupported/null。模拟 VIC 网络失败时，Overview 清除旧 NSW 值并禁用导出，随后 QLD 恢复为 66,624。
- 地图验证：All 仅按来源事故总数着色；进入州只保留 ABS 参考边界，无虚构事故点、LGA 计数或热点。悬停、选择、缩放/重置、SVG 降级、主题切换及同一个 canvas 保留均通过。
- 布局覆盖桌面 1280×720 / 1440×900 / 1920×1080 / 2560×1440，以及 768px、390px；无整页横向溢出。Overview 的地图/图表底部对齐检查通过。
- 已查看 Overview、Analytics、Data 深浅主题的 1440px / 390px 截图；Data 文本、数值和按钮对比度断言 ≥4.5。截图等待主题颜色稳定及绘制帧，避免将切换瞬间误判为产品问题。
- 最后修正单州严重程度图遗留的“前两个柱子高亮”假设：按原生 fatal/serious/hospitalisation 类别文字高亮，不依赖真实导出的类别排序；没有修改类别数值或映射为统一州际等级。修正后重新生产构建并完整通过 26 项浏览器回归。
- `agent-browser` 独立会话实查首页和 Analytics，真实内容加载、关键交互存在，无框架错误覆盖层或控制台错误；检查会话已关闭。测试使用独立 Chrome 临时 profile，不操作用户浏览器窗口。Safari、Firefox 和真实移动设备未验收。

## 当前限制

- 严重程度只导出了完整 2020–2024；子区间返回 unsupported 并显示原因，不按比例分摊。州内事故位置仍受源策略限制；地图几何不是官方 crash-location 报表。Crash records API 明确 unsupported，不附带虚构样例。
- AI 回复仍为模板/模拟、未接模型，但可读取当前真实汇总；Imports 仍仅元数据预览，没有真实解析、上传、入库或发布。
- 仅修改 `frontend/`；保留已有未提交和未跟踪文件。未改 Python/SQL 流水线、数据库、Git 分支，未提交、推送、部署。只替换本任务拥有的本地预览进程。

证据截图：`artifacts/official-{overview,analytics,data}-{dark,light}-{1440,390}.png`。日志：`artifacts/official-snapshot-unit-tests.txt`、`artifacts/official-snapshot-browser-tests.txt`。这些是本地前端接入验证，不构成 ARSIA 全平台验收。

---

# Overview 无边框地图验证（2026-09-29）

- 左侧移除卡片边框/圆角/阴影/底色和 Spatial exploration / Illustrative layer；画布利用标题空位并向左扩展，MapLibre 背景与页面主题底色一致。边界文件和数据 fixture 未修改。
- before/after 对比覆盖 1280×720、1440×900、1920×1080、2560×1440、768×1024、390×844，每个 All/NSW，共 12 组。topbar、metric-grid、四个 metric-card、chart-stack、trend-panel、severity-panel 的 x/y/width/height 全部完全相同。原始证据在 ignored `artifacts/free-map-before.json` 与 `free-map-after.json`。
- 日夜主题地图底色与 body 相同；无页面横向溢出，浮动图例和五个控制按钮均在地图内。国家视图保留本土与 Tasmania；沿用原有主视图范围，不宣称覆盖所有外部领土。
- 最终补查修复：增加 country 底部安全区，1440 light 的 Tasmania 标签不再与 Zoom in 相交；1280/768/390 的 Sydney/Wollongong 两个标签均可独立点击，地理圆点保持坐标。
- 最终 Chrome 全屏补查通过：1440 light 下 Expand → Reset → 退出恢复正常，Tasmania 与 Zoom in 的交叠面积在普通/全屏/退出后三种状态均为 0；州标签均在地图内。截图保存在 `artifacts/free-map-production-light-1440-country.png`、`free-map-production-light-1440-expanded.png`、`free-map-production-dark-390-nsw.png`。
- `npm run typecheck`、`npm run lint`、`npm run build` 通过；`npm test` 30/30 通过（新增 5 项投影/fit 测试）；最终生产 `npm run test:e2e` 20/20 通过。
- 浏览器回归覆盖来源/日期筛选、区域悬停、点击州进入、缩放、重置、主题持久化、备用 SVG、键盘/reduced-motion、Analytics 和其他页面。采用独立 Chrome profile，不影响用户浏览器；未验证 Safari 或真实移动设备。

预览：`http://127.0.0.1:3100/`。本次仅修改前端及其文档/测试，未改流水线、数据库、分支；未提交、推送或部署。只替换本任务拥有的本地服务。

---

# Analytics 深入分析页验证（2026-09-29）

本轮新增 `/analytics`，导航位于 Overview 右侧，原 `/explore` 重定向。验证对象仅为本地演示前端，不是 ARSIA 数据平台或官方数据验收。

- `npm run typecheck`、`npm run lint`、`npm run build` 均通过。
- `npm test`：25/25 通过，包含 12 项新增 Analytics 计算测试；覆盖三州总量一致、半年度同月比较、跨年部分月份、缺失与零、零基期、空结果/unsupported、错误版本和批次、跨来源混合及无效日期。
- 生产预览完整浏览器回归：20/20 通过（原有 14 项 + Analytics 6 项）。最终严重程度长标签布局调整后重新构建，并再次运行 Analytics 6/6 通过。
- 实际检查四指标趋势、年/月、同比、月份热图键盘/点击/按月下钻、月份均值、严重程度数量/占比、聚合表排序/分页、JSON 导出、证据弹窗、AI 来源上下文、空结果恢复和主题持久化。
- Analytics 布局检查覆盖 1280px、1440×1000、768×1024、390×844，以及最终 2560×1440；没有页面级横向溢出。手机热图允许局部横滑且年份列保持可见。
- 最终生产检查确认切换来源和主题时三个 ECharts canvas 均保留；控制台/pageerror、ECharts 生命周期警告均未出现。旧 `/explore` 地址正确重定向。
- 独立 Chrome 临时实例运行，不操作用户已有浏览器窗口；Safari 和真实移动设备未测试。

最终生产预览：`http://127.0.0.1:3100/analytics`。截图位于被忽略的 `artifacts/analytics-production-dark.png`、`analytics-production-light.png`、`analytics-production-mobile.png`。

仍然使用演示 provider。月份是固定权重分配，页面就地标记合成数据，不代表真实季节性；对比不代表因果或道路风险。真实 HTTP 数据服务、正式指标维度扩展和 Agent 执行逻辑仍未接入。未修改 Python/SQL 流水线、数据库、Git 分支；未部署、提交或推送。仅替换本任务拥有的预览服务。

---

# 五页顶栏留白统一

2026-09-29：按最新图 3 复用 Data/Imports/Reports 的公共顶栏。仅 CSS、现有测试定位及前端说明调整。

- 桌面五页顶栏均 88px，标识圆形均 44px、top=21.5px；移除 Overview/Explore 压缩及标识/导航放大特例。仍保留各页横向容器及分析区全宽。
- 独立浏览器几何检查 6 个 viewport × 5 个路由，共 30 组：1280×720、1536×864、2560×1440、1920×720、768×1024、390×844。五页 header/brand/logo/nav/actions 的顶部和高度一致，无整页横向溢出。手机仍为双行导航。
- 对照上一轮实测值核对 12 组 All/QLD 桌面布局，地图 bottom 与 severity 高度保持，差异 <0.12px。
- 类型检查、lint、production build 通过；最终 3100 production 服务已有浏览器用例 14/14 通过。初次复查暴露旧地图测试固定鼠标坐标失效，改为按当前画布尺寸定位 NSW 内部，并在加载前启用 reduced-motion；复查通过，不改变地图产品逻辑。
- 已查看最终深/浅色页面，生产截图 `artifacts/shared-header-production-light.png` 地图边界完整；几何记录在 `artifacts/shared-header-verification.json`。未实机验证 Safari。
- 原本地地址 http://127.0.0.1:3100 已更新并运行；临时 3101 已停止。只重启本线程拥有的服务，没有数据库/流水线修改、提交、推送或部署，保留所有原有未提交文件。

# 顶栏压缩与 Ask AI 配色修订

2026-09-29：仅修改前端展示与设计说明。

- `npm run typecheck`、`npm run lint`、`npm run build` 均通过；最终 3100 production 预览上已有浏览器用例 14/14 通过。未改动数据逻辑，本轮不重复数据测试。
- 独立 Chrome 浏览器记录修改前后真实 DOM 几何数据，检查 1280×720、1440×900、1536×864、1920×1080、2560×1440、1920×720，各覆盖 All / QLD，共 12 组。顶栏高度为原来的 2/3；标识、导航、右侧按钮上下居中且不越界；边线到日期栏距离不变；地图底边不变；地图与 trend 增高恰等于节省的顶栏高度；severity 顶部和高度保持不变（最大亚像素差 <0.12px）。
- 1536×864 示例：顶栏 84.671875 → 56.4375px，省出 28.234375px；地图底边保持 846.734375px；QLD severity 高度保持 261.9375px。
- 实际查看浅色界面截图，Ask AI 使用灰绿色底、深绿色字；深色仍为青柠色。无框架错误覆盖层或控制台错误。
- 截图及测量位于被忽略的 `artifacts/compact-header-light.png`、`compact-header-production.png`、`header-before.json`、`header-comparison.json`。几何对比在 3101 开发预览完成，最终交互测试在 3100 生产预览完成；未实测 Safari。
- 本地地址保持 http://127.0.0.1:3100。仅重启本线程管理的预览服务；3101 临时服务已停止。没有部署、提交、推送或更改数据库/流水线；原有未提交文件保留。

# 日夜主题与桌面自适应验证

2026-09-29，范围仅为 `frontend/`；不代表 ARSIA 数据流水线或全平台验收。

- 最终代码 `npm run typecheck`、`npm run lint`、`npm run build` 通过。
- `npm test`：13/13 通过。All 地图新增 count 与分州指标一致、2024 日期筛选一致、无覆盖 count 保持 undefined 的断言。
- 最终 production server（http://127.0.0.1:3100）上的 `ARSIA_BROWSER_CHANNEL=chrome npm run test:e2e`：14/14 通过。
- 浏览器覆盖：默认 dark → light → 刷新仍为 light → dark；localStorage 不可用时仍可切换；切换主题与来源保留同一个地图 canvas；Settings 显示当前主题；手机/平板主题入口可见。
- 桌面几何检查：1280×720、1440×900、1920×1080、2560×1440，各检查 All 与 QLD。地图/趋势顶部对齐，地图/severity 底部对齐，日期栏上下间隔相等，无横向或纵向溢出，底部留白 15–40px 范围内（设计值 16–24px）。
- 另实测 1536×864 QLD：地图和 severity 底边均为 846.734375px，距窗口底部约 17.27px，无横向溢出。
- 实际查看深/浅色桌面、All 12 项分类、QLD、浅色 AI 抽屉和地图证据弹窗截图。修复短图面刻度重叠、自动省略分类标签、浅色错误文字/发送按钮对比度，以及地图和图表 resize 后大小不一致问题。
- All 和州级地图共享珊瑚红浓度尺度；未覆盖州保持未知/中性底色，不伪造零值，也不宣称跨州可比较风险率。ABS 署名已移入地图证据，provenance 来源文件仍可访问。
- 保留并通过筛选/日期、Yearly/Monthly、tooltip、导出、模拟 AI、地图钻取、同实例 canvas、WebGL SVG 降级、导航、Imports 元数据演示及键盘/reduced-motion 检查。768px、390px 自然滚动，无整页横向溢出。
- 使用独立测试浏览器，控制台未发现错误；没有操作用户其他浏览器窗口。

当前 production 预览运行于 http://127.0.0.1:3100，临时 3101 开发服务已停止。验证截图保存在被忽略的 `artifacts/`（如 `final-dark-qld-1536.png`、`final-light-qld-1536.png`、`desktop-light-1280-720-final.png`）。

限制：桌面宽度 >1100px 且高度 ≥720px 时填充视口；更矮窗口以自然滚动保证可读性。真实 Safari、Firefox、手机设备及屏幕阅读器未验收。AI、导入和分析数据仍为演示，没有连接模型、数据库或真实后端。原分支、流水线和数据库未更改；保留已有未提交/未跟踪文件，没有部署、提交或推送。

# 上一轮界面修订验证（历史）

2026-09-29：精简 Overview，新增默认 All 与澳大利亚覆盖地图。

- 类型检查、lint、production build 均通过。
- 数据契约/fixture 测试 **13/13** 通过，新增 All 不合并全国值、按州保留指标/时间序列/严重程度、日期无覆盖时清空可用州。
- 最终 production server 上的浏览器测试 **8/8** 通过，含 All 默认值、覆盖/无覆盖反馈、NSW/QLD 地图进入、同一地图 canvas 保留、被删除元素确实不存在、导出和模拟 AI、1280/768/390px、无 WebGL 的国家→州 SVG 降级。
- 实际悬停严重程度柱体并检查截图：item tooltip 正常，悬停长虚线已取消，柱体轻微变亮；数值和柱长不改变。
- 实际检查 All 和 NSW 桌面截图、平板分州指标和完整图表；修复屏幕阅读器标题造成的手机溢出，以及 All 切到州时图表高度残留问题。
- 生产地址仍为 http://127.0.0.1:3100，首页控制台无错误。未改动原流水线/数据库、分支、原有文档；没有提交、推送或部署。
- 原首版记录表交互已按用户要求从页面移除；相关服务契约仍保留。以下为之前的首版历史验证，不表示当前仍显示这些已删除模块。

# 首版验证记录（历史）

日期：2026-09-29。范围仅为新增 `frontend/`，未运行或声明通过全项目 Python / PostgreSQL 验收。

## 已执行

- `npm run typecheck`：通过。
- `npm run lint`：通过。
- `npm run test`：12/12 通过。覆盖 NSW 基准数值、三州月/年/严重程度/热点组总量一致性、缺失与零的区别、部分覆盖、样例分页搜索排序、记录跨筛选稳定性、模拟 Agent 流和取消、导入不伪装发布成功。
- `npm run build`：通过，Next.js production 静态页面生成成功。
- `ARSIA_BROWSER_CHANNEL=chrome npm run test:e2e`：7/7 通过，最终也在 production server 上通过（独立临时 Chrome profile）。检查 1440、1280、768、390px；首页四卡、年/月切换和 tooltip、三州切换、日期/无覆盖空态、地图行政区 hover/click、缩放/重置、样例搜索排序分页、下载 JSON 实际内容、模拟 AI 问答和嵌套证据对话框、Escape、键盘入口、导航、导入文件元数据和 needs_input 状态、报告空态。
- 阻止站外资源后，字体、图表、真实边界和地图仍可用；筛选前后保留同一个 MapLibre canvas。
- 模拟 WebGL 不可用时，129 个 NSW 本地边界 SVG path 可见，缩放禁用，并可通过键盘选择。
- `agent-browser` 实际查看生产预览；首页无空白或框架错误覆盖层，控制台无错误。
- 检查首页及 AI 面板截图，未发现整页横向溢出；表格允许在自己的容器内横向滚动。

## 本轮修复

MapLibre 6 的 worker 在打包后默认地址失效：改为本地提供同版本 worker/shared 文件。补齐站点图标，消除 favicon 404。防止重复点击当前趋势粒度使页面保持 loading。固定同一示例记录在不同日期筛选下的分类。手机使用单列指标卡。修复生产版本中嵌套证据窗口的 Escape 关闭顺序，补齐窄屏图标按钮的无障碍名称。

## 验证边界

- 运行中的地址：`http://127.0.0.1:3100`，仅绑定本机；进程关闭后需按 README 重新启动。
- 当前实测浏览器为桌面 Chrome/Chromium；响应式通过调整 viewport 检查，未在真实 iPhone/iPad、Safari、Firefox 或屏幕阅读器上验收。
- 数据、AI、导入状态均为演示；没有真实 HTTP 后端、模型、入库、认证或报告持久化。未进行生产负载、安全或端到端数据流水线验证。
- 记录是独立样例，导出最多附 50 条；不构成全量 KPI 明细证据。热点和百分比变化不表示真实风险或因果。
- 未切换分支、提交、推送或部署。原有 tracked 文件没有差异；原有三组未跟踪文档仍保留。新增工程集中于 `frontend/`。

截图位于被 Git 忽略的 `artifacts/`；浏览器测试源码为 `tests/browser/overview.spec.ts`，fixture 测试为 `tests/fixtures.test.ts`。
