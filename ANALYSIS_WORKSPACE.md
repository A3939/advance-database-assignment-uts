# ARSIA Assistant 分析工作空间

本次升级复用真实项目数据快照及 `lga-name-v1` 扩展，没有改数据流水线、数据库、QA 状态或正式发布结果。

## 当前开放能力

- 原有七个只读工具继续提供指标、覆盖、口径、月/年趋势、等长时间比较、严重程度、LGA 与批次证据。
- `workspace_catalog`：查看已授权的三个分析表、字段字典、来源限制和已经验证的关联。
- `workspace_query`：按来源、整月区间、LGA 筛选；支持 eq / contains / gte / lte 前置过滤，维度分组、指标求和、排序及结果上限。所有分组强制保留 source，不能意外产生全国合计。null 保持未知，缺行不补零。
- `present_analysis`：直接从真实查询结果生成 ECharts 折线/柱形图或表格，附 CSV 与 provenance JSON。模型不能提交任意 JavaScript 图表配置或伪造数值。
- `python_analysis`：读取当前轮查询结果，用 pandas、NumPy、Matplotlib 计算、绘图，生成 CSV/JSON/Markdown/TXT/PNG/PDF；自动附 Python 源代码和来源清单。异常结果返回 Agent，允许在限额内修改并再次运行。

| 表 | 粒度 / 可用字段 | 边界 |
| --- | --- | --- |
| monthly_metrics | 来源×月份；四项指标，派生 year/month | 复用官方服务；页面选中 LGA 时继承该区域范围 |
| lga_monthly | 来源×月份×LGA；四项指标与地区名称 | 稀疏月度计数，保留 __unmatched__；LGA 不等于城市都会区 |
| locality_monthly | 来源×月份×LGA×Town/Suburb 标签；crashes | NSW Town、QLD Loc_Suburb；VIC 尚未接入，无坐标含义 |

地区名称通过 `(source, regionId)` 与唯一地区目录做 many-to-one 关联，不直接连接两个事实表。VIC Accident/Node 的既有 `(ACCIDENT_NO, NODE_ID)` 关联在区域快照生成时验证，合并相同重复 Node，排除冲突地区，按月核对总数。其他任意关联未开放。

数据为 2020–2024 的 `official-v1` / `bcc5da57-25f2-41ec-9925-bef421b02671` 项目快照，不是实时数据库。请求范围、实际观察月份、查询参数、版本与批次进入证据和文件来源清单。

## 本地 Python 隔离

```sh
# Docker Desktop 运行时才可执行 Python；无容器时明确失败，不用宿主机 Python 代替。
npm run sandbox:build
npm run test:sandbox
ARSIA_NEXT_DIST_DIR=.next-analysis npm run build
ARSIA_NEXT_DIST_DIR=.next-analysis npm run start -- --port 3103
```

镜像构建上下文仅含 `sandbox/Dockerfile` 和受控 `runner.py`；基础镜像固定 digest，主要分析包固定版本。每次执行把镜像 tag 解析为不可变 image ID，并将 ID 写入来源清单。生产镜像供应链和漏洞维护仍需单独负责。

服务端只创建一个随机输入副本目录，内容是 `input.json` 和 `analysis.py`。容器只读挂载这一个目录；不挂载仓库、数据库、宿主用户目录、API 环境文件或 Docker socket。容器环境由镜像定义，不继承服务端密钥。

执行限制：

- network=none、非 root UID 65534、只读根文件系统、cap-drop=ALL、no-new-privileges、Docker 默认 seccomp。
- 1 CPU、512 MB 内存（不额外交换）、32 个进程、64 个文件描述符、单文件 4 MB。
- 只有 `/analysis` 是分析写入目录：32 MB 有界 tmpfs；缓存与临时文件也写在这里。容器自身必要的 `/dev` 等内核接口仍存在，但无宿主文件/网络权限。
- 每次 30 秒墙钟 / 20 秒 CPU，每问题最多 3 次 Python；超时/取消后强制移除本次随机命名容器，然后删除输入副本。不停止其他容器。
- 最多 8 个生成文件、合计 8 MB；只收集允许扩展名的普通文件，拒绝符号链接、管道、套接字、目录和超限文件。只有成功执行才发布下载结果。文本报告/输出的证据编号还需通过服务端实际编号校验；不合法引用退回 Agent 修正，Markdown 字面量换行问题也会明确返回。
- 失败关闭：Docker 未运行、镜像未安装、结果异常或资源超限均明确返回失败；不会退回宿主 Python。

容器属于操作系统隔离，不是形式化证明。Docker daemon/虚拟机是受信任基础设施；公网多租户服务还需独立工作节点、身份鉴权与配额。当前不提供任意宿主命令、网络访问或依赖在线安装。

## 文件、会话和额度

- 模型循环：最多 12 轮 / 16 个工具，单轮输出最多 5,000 tokens，总回复最多 16,000 字符，总请求 240 秒；单次 API 45 秒、最多 1 次 SDK 重试。
- 查询最多保留 10,000 行在本轮内存，模型只收到前 12 行及范围/截断说明。图表/表格最多显示 100 行；All 的来源必须分系列展示。
- Python 只拿到显式指定的当前轮 queryId 结果，不拿整份原始数据。跟进问题重新查询，避免过期 queryId 或筛选混用。
- 生成文件保存 `frontend/artifacts/analysis/`（gitignored），随机 192-bit capability ID 下载；SHA256 验证，24 小时失效，后续写入时清理过期文件；总存储限额 128 MB。
- 下载接口仅附件响应，nosniff + CSP sandbox，不把 Python 生成 HTML/SVG/JavaScript 作为网页执行。路径遍历与任意文件名不支持。
- 界面统称 ARSIA Assistant。模型提供商信息不出现在普通用户 UI/错误消息中；不会声称模型由项目团队训练。
- 关闭/换筛选取消请求；失败、停止的残缺内容不进入下一轮历史。文件仍可在有效期内下载，刷新页面不恢复对话。

## 真实性和剩余限制

Agent 的解释依据实际工具结果，Python 计算提供可复核代码、输入查询来源和输出。代码能生成分析并不等于统计结论已独立审核；复杂统计仍应检查方法和假设。

不能把未接入字段说成数据不存在；不能把尚未验证的坐标/城市对应关系说成可用。事故地点、个人/车辆明细、曝光分母、其他州、任意 SQL/任意表关联和因果推断未开放。州级严重程度全期快照仍不能按比例拆成年份。此工作不构成 ARSIA 全平台验收。
