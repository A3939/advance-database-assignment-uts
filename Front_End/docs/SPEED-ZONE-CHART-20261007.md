# All Severity：限速分组致命事故占比

2026-10-07。仅替换 All 严重程度页右侧预留图；左侧 Count/Share、单州右侧 Fatal crashes & lives lost 保持原实现。

## 统计口径

每根柱为同州、所选月份、同限速组的**致命事故事件数 / 记录事故事件数 × 100%**。不是死亡人数、行驶速度或考虑交通暴露量的风险率。三州分别计算，不合并为全国值。

QLD 原件提供整个区间，因此实际统一为 ≤50、60、70、80–90、100–110 km/h。NSW/VIC 精确限速仅归入这些完整区间，不拆分 QLD 已发布区间。

| 来源 | 原生字段 | 2020–2024 事故数（含排除限速） | 排除限速记录 |
| --- | --- | ---: | ---: |
| NSW | `Speed limit` | 92,082 | Unknown：26 |
| VIC | `SPEED_ZONE` | 72,170 | 075：3；777：187；888：529；999：5,386 |
| QLD | `Crash_Speed_Limit` | 66,624 | 0 |

VIC 075 不强行归到 70 或 80；特殊编码不猜测其含义。排除原值及对应事故、致命事故数可在 Definitions 查阅。QLD 为 casualty crash 覆盖，各州纳入范围及严重程度定义不同，不应据此排名州的道路安全水平。

## 数据绑定与运行

- 当前固定批次 `bcc5da57-25f2-41ec-9925-bef421b02671`、版本 `official-v1`。
- 构建脚本 `scripts/build-speed-zone-snapshot.py` 只读已绑定 NSW crash XLSX、VIC Accident CSV、QLD crash CSV；校验原件哈希、原始行数、选中事故主键唯一性和原生严重程度。
- 每州 60 个月的事故数、致命事故数、已知 fatal 状态数，与原项目 reader 报表逐月独立对账，共 540 项数值比较。
- 输出 `data/speed-zones/aggregates.json` 与 `provenance.json`，服务端固定校验两者哈希。页面运行不读原件、不访问业务数据库或模型。
- 支持覆盖期内完整月份；错误批次、版本、超出覆盖和 LGA 范围不会借用全量值。无观察或 fatal 状态不完整时显示 N/A，实际已知零值才显示 0%。
- 新接口是本展示版派生扩展，不修改原有官方报表、数据库权限或 release。

可选重建：在本目录执行 `python3 scripts/build-speed-zone-snapshot.py`；默认原件位于同级 `../raw_datasource`，也可用 `ARSIA_RAW_DATA_DIR` 指定。仅在明确更新输入后重新审阅证据及服务端哈希，不自动接纳不同文件。

## 验证

- `npx tsx --test tests/speed-zone.test.ts tests/severity-comparison.test.ts`：19 项通过（新增 9，既有相邻回归 10）。
- `python3 scripts/test-speed-zone-snapshot.py`：2 项通过，验证区间、特殊/未知值归组。
- 修改文件的 ESLint、TypeScript 检查及 `npm run build` 通过。构建输出为 `.next`；运行预览使用独立 `.next-local-preview-20261007`，生成类型引用已恢复为预览入口。
- 实际浏览器：桌面悬浮、Definitions、左图 Count/Share 切换、三个月筛选、刷新、NSW 原右图、390px 窄屏无横向溢出。
- API 响应和检查日志：`output/speed-zone-20261007/`；截图：`output/playwright/speed-zone-*.png`。

没有调用真实 Agent、导入 pipeline 或执行数据库写入；这不是其他数据批次、所有州或 LGA 限速统计的验收。
