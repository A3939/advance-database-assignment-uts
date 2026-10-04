# ARSIA Assistant：只读查询与隔离分析工作空间

主页及 Analytics 的 Ask AI 通过 Next.js 服务端调用 OpenAI 官方 JS/TS SDK（openai 7.23）和 Responses API。真实模型自行选择受控工具，可连续调用；生产路径不再使用模板答案，也不会在失败时回退为模拟回复。

## 本地运行与配置

密钥沿用 `.env.local` 的 `OPENAI_API_KEY`，只有服务端读取。不需要复制到任何其他文件，不使用 `NEXT_PUBLIC_` 前缀。

默认模型 `gpt-6-luna`，低推理强度，适合聚合数据工具查询和简短解释。可通过服务端 `OPENAI_MODEL` 更换具备 Responses / function calling / streaming 能力的模型。GPT-5/6 系列配置 low reasoning；其他名称不附加 reasoning 参数。更换模型后应重新做少量事实验收；接口不静默切换模型。

不占用现有 3100 预览的运行方式：

```sh
ARSIA_NEXT_DIST_DIR=.next-analysis npm run build
ARSIA_NEXT_DIST_DIR=.next-analysis npm run start -- --port 3103
```

开发时可用同一个环境变量运行 `npm run dev -- --port 3103`。同一个构建目录不能同时用于 dev 和 build。现有 `.env.local` 不需要修改。

官方依据（2026-09-29 核对）：

- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/docs/guides/streaming-responses

## 工具与数据边界

`src/server/agent/tools.ts` 复用 `createRegionalProvider(createOfficialProvider(), regionalSnapshot)`；数据是 `official-v1` 的已校验项目快照，批次 `bcc5da57-25f2-41ec-9925-bef421b02671`。没有实时连接 PostgreSQL。

| 工具 | 能力 |
| --- | --- |
| dataset_metadata | 来源定义、可用范围、限制 |
| core_metrics | 四项指标和确定性致命事故比例 |
| time_series | 月度/年度单指标、确定性相邻期差值和百分比 |
| compare_periods | 等长且不重叠的月份区间；默认基期为去年同月；确定性同比/差值 |
| severity_distribution | 完整 2020–2024 原生分类、确定性占比 |
| regional_analysis | 单州 LGA 列表与代码、匹配覆盖率；指定代码查看地区指标/月趋势/严重程度与 Town/Suburb 前八项 |
| source_evidence | 批次、发布状态、哈希、QA 与验收限制 |

参数为 strict JSON Schema；服务端另外校验白名单、日期、整月、指标和粒度。版本和批次来自验证后的页面上下文，模型不能指定路径、数据库或新版本。

- All 逐州返回，不计算全国总数或跨州风险排名。
- 0、unknown、unsupported、no_results 保留独立语义。
- 比较必须等长、不重叠且两期均完全覆盖。闰年二月基期按真实月末计算；零基数的百分比变化为 null。
- 日期越界不外推。工具同时返回 requestedRange / observedRange；扩大查询区间会在证据中明确显示，不修改页面筛选。
- 州级严重程度只支持完整五年；选中 LGA 时可查询直接计数的区域月度严重程度，均不做比例拆分。
- 真实 LGA 名称匹配计数可查询；LGA 不等于整个城市。事故坐标、个人/车辆明细、曝光分母和因果字段未暴露。Agent 不执行任意 SQL、宿主终端、正式数据写入、导入或发布；可通过隔离工作空间生成分析文件（见 `ANALYSIS_WORKSPACE.md`）。
- QA01–QA06 通过、QA07 location limited；独立成员签署和全平台验收未完成。

## 会话、流式交互与证据

`POST /api/agent` 接受 `{context, message, history}`，输出 NDJSON：`progress`、`tool_result`、`evidence`、`message`（增量）、`done` 或 `error`。服务实现见 `src/server/agent/runner.ts`，客户端见 `src/services/http-provider.ts`，面板见 `src/components/agent-panel.tsx`。

每轮强制先调用新工具。历史只用于理解追问，不作为数值证据。浏览器保留最近最多五组完整对话；服务端再限制历史大小并丢弃来源、地区、日期、页面、版本或批次不一致的历史。更改任一上下文会取消旧请求、清空会话；关闭面板也取消生成。

证据 E1/E2 等由服务器在真实工具成功后生成，附完整结果、来源、实际范围和批次，可在原有证据弹窗查看。模型不控制证据链接，消息以纯文本展示，不执行 HTML 或任意链接。

停止会通过 AbortSignal 传递到 OpenAI SDK。失败和中断显示明确状态及 Retry；失败/中断内容不进入后续历史。New chat 清空本地会话。页面刷新不持久化聊天。

## 限额与隐私

- 每个问题最多 12 次模型调用、16 次工具调用；每次模型输出上限 5,000 tokens，总显示字符上限 16,000。
- 总超时 240 秒，单次 SDK 请求超时 45 秒，SDK 最多 1 次自动重试；流式过程中断不自动重发。
- 单工具结果最多 64,000 字符。问题最多 2,000 字符，历史最多 12 条 / 24,000 字符，请求体最多 128 KB。
- 进程内最多 2 个并发分析、每分钟 12 个请求；拒绝跨源浏览器请求。
- SDK `store:false`；只发送问题、有限会话上下文和被工具选出的聚合数据/定义。不会上传完整快照、原始事故记录或个人明细。
- SDK 日志关闭，服务端不记录请求体、模型原始错误或密钥。错误映射为固定安全提示；密钥不会加入返回值或浏览器包。
- `store:false` 不是对 OpenAI 平台所有数据保留政策的零保留承诺。
- 当前为本机预览，没有登录鉴权、跨实例限流、持久会话或生产监控；公网发布前需要单独完成这些能力。

## 可尝试的问题

1. “用中文概括当前筛选下的四项指标。”
2. “Compare 2024 with 2023.” 然后追问“死亡人数呢？”
3. “显示每年的事故趋势。”
4. “2024 年的严重程度分布是否可用？”
5. “为什么事故下降了？数据能证明原因吗？”
6. “Show data quality and evidence.”

测试结果见 `VERIFICATION.md`。单元测试和常规浏览器回归不调用付费模型；真实联调单独进行，不设自动批量付费测试。

LGA 当前上下文通过 `filters.regionId` 进入核心指标、趋势、同比和严重程度工具；更换来源会清空该地区。`regional_analysis` 在 `regionId:null` 时列出某州的有效地区代码，指定代码后查询该地区，始终明确区域和日期，不修改页面。可试“列出 NSW 事故最多的三个 LGA”，或选 Sydney LGA 后问“当前地区四项指标是多少？2024 与 2023 相比呢？”。

升级后的三个分析表、Python 沙箱安全边界、ECharts 图表、文件下载与限制，见 [ANALYSIS_WORKSPACE.md](./ANALYSIS_WORKSPACE.md)。
