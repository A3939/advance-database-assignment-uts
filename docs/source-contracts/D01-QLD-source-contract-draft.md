# D01 · QLD 来源合同与核对记录（draft）

**版本**：qld-d01-draft-0.1  
**核对日期**：2026-09-18  
**主责**：D；**语义复核**：C（待完成）；**报表复核**：D（待完成）  
**状态**：`draft`。本文是团队内部来源调研和本地文件核对记录，不等于 official 发布批准或数据库运行证据。

## 1. 来源与本地快照

| 项目 | 已核内容 / 处理 |
|---|---|
| 发布者与许可 | Queensland Department of Transport and Main Roads；Creative Commons Attribution 4.0。[数据集页](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads) |
| 官方资源 | [Road crash locations 资源页及字段字典](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads/resource/e88943c0-5968-4972-a15f-38e120d72ec0)；资源 ID `e88943c0-5968-4972-a15f-38e120d72ec0`。交接包 05 登记的原下载地址为 `https://www.data.qld.gov.au/dataset/f3e0ca94-2d7b-44ee-abef-d6b06e9b0729/resource/e88943c0-5968-4972-a15f-38e120d72ec0/download/_1_crash_locations.csv`。官网资源元数据 Hash 为 `19a17cdddde8f70e7121e677fcd0cba9`，与本地文件 MD5 一致；尚未重新下载当前文件逐字节验证。 |
| 本地原件 | `raw.zip` 中 `raw/qld_crash_locations.csv`；UTF-8 CSV，52 列，415,407 个逻辑数据记录；文件字节 SHA256 `975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704`；MD5 `19a17cdddde8f70e7121e677fcd0cba9`。 |
| 发布标签 / 身份范围 | **待团队确认**。官网当前显示数据集版本 `rqC45037- June 2025`、最后更新 2026-04-24；本地哈希与官网资源元数据匹配。具体 `release_label`、`release_scope` 及原件归档时间仍须登记确认；确认前不跨发布合并事故 ID。 |
| 原生粒度和键 | 字段字典定义一行一宗事故，`Crash_Ref_Number` 为匿名事故标识，且可能随发布变化。本地全文件无空键、无重复键。键作为文本保留，不转整数。 |
| 原生覆盖 | 本地观察到 2001-01 至 2025-06 的年份、月份；2025 年仅观察到 1–6 月。2020–2024 分别为 12,147、13,476、13,021、13,622、14,358 行，合计 66,624。观察到记录不等于官方保证每个月完整覆盖。 |
| 目标分析范围 | 团队默认事故发生年 2020–2024。按 `Crash_Year` 筛选；`Crash_Month` 只给月份精度，不补造事故日。范围外原件仍留 raw。 |

**身份描述差异需核实**：官网字段字典称事故 ID 的前四位“目前”表示事故年，但本地文件前五行 ID 为 `1`、`2`、`3`、`4`、`5`。本地文件 MD5 与官网资源元数据哈希一致；两项证据之间的差异原因尚未确定。使用 `Crash_Year` 判断发生年，保留 `Crash_Ref_Number` 原文作为键，不从 ID 推导年份。

## 2. 字段语义与候选映射

| 目标 | 原字段及已找到的依据 | D01 处置 |
|---|---|---|
| 事故身份 | `Crash_Ref_Number`；[官方字段字典](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads/resource/e88943c0-5968-4972-a15f-38e120d72ec0)称其为匿名、可能跨发布变化的唯一事故标识。 | 来源 + 发布范围 + 原键共同构成身份；本地唯一性已核。 |
| 发生时间 | `Crash_Year` 与 `Crash_Month` 的官方定义分别为事故发生年、月。 | 年转整数；英文月份按合同映射为 1–12；`occurrence_date=NULL`、`date_precision=month`，不使用报告时间补日。 |
| 事故严重度 | `Crash_Severity` 官方五类：Fatal、Hospitalisation、Medical treatment、Minor injury、Property damage only，取事故参与单元的最高严重度。 | 保留来源原类别和定义版本；Fatal→死亡事故的候选映射须与 C 审核。不可将 NSW/VIC 同名类别直接合并。 |
| 死亡人数 | `Count_Casualty_Fatality`；官方定义包含因事故伤害在 30 天内死亡的道路使用者。 | 候选 `fatality_count`；应与其他州口径比较后再批准跨州合计。 |
| 伤亡人数 | `Count_Casualty_Total`；官方定义为事故中死亡或受伤的道路使用者。四分项为 Fatality、Hospitalised、MedicallyTreated、MinorInjury。 | 候选 `casualty_count`；本地全部 415,407 行四分项之和等于 Total。最终资格和跨州可比性须 C 审核。未知值保留 NULL，不补零。 |
| 单元分类计数 | 七个 `Count_Unit_*` 字段，官方定义为事故中各类参与者/车辆数量。 | 仅保留事故行内原始聚合属性，不生成车辆或人员明细。 |
| 坐标 | `Crash_Latitude` / `Crash_Longitude`；[官方数据集页](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads)和字段字典明确标为 **GDA2020**。 | 原始 CRS 已知；待确认的是满足团队 Canonical 地图层 EPSG:4326 要求的方法。C 需确定并测试转换方案，或记录暂不使用 QLD 地图点的处置。确认前保留原坐标，不直接改贴 EPSG:4326 标签；质量原因代码由实现时按合同确定。 |

## 3. 本地只读检查结果

从 `raw.zip` 内原始 CSV 按 UTF-8、CSV 逻辑记录读取，未修改源文件。

| 检查 | 结果 |
|---|---:|
| 数据行 / 列 | 415,407 / 52 |
| 空 `Crash_Ref_Number` / 同文件重复键 | 0 / 0 |
| 2020–2024 数据行 | 66,624 |
| 2020–2024 严重度 | Fatal 1,304；Hospitalisation 31,922；Medical treatment 22,730；Minor injury 10,668；Property damage only 0 |
| 全文件四分项与 Total 不相等 | 0 |
| 全文件伤亡五字段空串或无法转整数 | 0 |
| 全文件空纬度 / 空经度 | 598 / 598（同一批记录）；2020–2024 为 0 / 0 |
| 全文件非空坐标非法或超出经纬度基本范围 | 0 |

这些结果只证明本地文件可解析及观察到的值；不证明官方文件版本一致、业务定义可比、坐标已转换、数据库 QA 已通过或可发布。

## 4. 官方范围与版本风险

[官方数据集概述](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads)写明：来源为 RoadCrash 数据库，近 12 个月记录可能仍属初步结果；Property damage only 事故自 2010-12-31 后不再由昆士兰警方报告/记录。因此 2020–2024 本地文件没有 Property damage only 与官方说明一致，但三州“全部事故”不能默认可比。官网目前描述的报告截止、数据更新日与本地快照的关系仍需核对。

## 5. 未决项与交接给 C 的决定

1. **本地发布识别**：本地 MD5 与官网资源元数据 Hash 一致，是文件对应关系的强证据；仍须登记原下载时间、归档证据和经团队确认的 `release_label`、`release_scope`。确认前不跨发布合并事故键；同名资源页面会更新，不能仅凭 URL 批准。
2. **坐标处置**：官方已明确原始坐标为 GDA2020；待确认的是满足团队 EPSG:4326 地图层要求的方法。请 C 确定并测试转换方案，或记录暂不使用 QLD 地图点的处置。确认前保留原坐标，不直接改贴 EPSG:4326 标签；质量原因代码由实现时按合同确定。[ICSM 技术手册](https://www.icsm.gov.au/sites/default/files/GDA2020%20Technical%20Manual%20V1.8_published_0.pdf)可供选择转换方法时参考。
3. **指标可比性**：请 C 核对 QLD 的 30 天死亡定义、四类伤亡范围与 NSW/VIC 的定义；按来源先报，不预设跨州人数可合计。
4. **覆盖声明**：确定本地 2020–2024 每个年月是否可声明完整覆盖，以及历史修订/删项的预期处置。观察到有记录不足以证明零事故月份也被完整覆盖。
5. **缺失规则**：本地文件五个伤亡计数字段未观察到空串或非整数值；这不证明官方不存在其他缺失 token。新文件出现未登记 token 时阻断并补充有依据的规则，不自行转为 0 或 NULL；新严重度类别同样阻断并更新定义。

**交接**：此时 **QLD 官方来源合同状态**仍为 `draft`，第 5 节未决项交 C 与相关负责人复核；取得版本化确认记录后，才将合同状态改为 `confirmed`。synthetic 开发使用独立虚构合同，不以 D01 任务完成代替 official 发布批准。
