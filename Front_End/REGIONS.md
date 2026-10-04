# LGA 名称匹配扩展（lga-name-v1）

此层解决“真实快照进入州后只有边界”的问题。它读取与正式构建相同、哈希固定的原始文件，在前端目录生成独立聚合快照。没有改动 Raw/Vault/Canonical/DW、数据库、正式证据或位置资格。

## 实际覆盖：2020–2024

| 来源 | 原事故数 | 匹配 LGA | 未匹配 | 名称匹配率 |
| --- | ---: | ---: | ---: | ---: |
| NSW | 92,082 | 92,077 | 5 | 99.995% |
| VIC | 72,170 | 69,805 | 2,365 | 96.723% |
| QLD | 66,624 | 66,623 | 1 | 99.998% |

NSW 5 起 Lord Howe Island 记录未匹配到当前本地边界，不强行分给其他地区。QLD 1 起 Unknown 地区保留为未匹配。VIC 包括 2,310 起地区歧义、48 起不能匹配的标签、7 起无匹配 Node；仍完整计入 72,170 的州总数。

## 方法及来源

- 输入 hash 必须符合 `data/official/provenance.json`；核验 NSW Crash、VIC Accident、VIC Node、QLD Crash 四个文件及其完整原始行数。没有读取 Person/Vehicle 作商业指标。
- 地区查找按州限定，规范化大小写、标点、州括号后缀、明确的行政后缀（City/Region/Regional/Shire/Town）。规范化后的边界名称必须唯一。不使用模糊匹配、地址 API、AI 猜测或坐标。
- NSW 的 Unincorporated → Unincorporated NSW；VIC Geelong/Dandenong/Bendigo/Shepparton → 对应 Greater LGA，Moreland → Merri-bek，均为显式版本化 crosswalk；逐项原标签、ABS 代码与计数见 `data/regions/provenance.json`。
- Merri-bek 更名依据：[Council approval](https://www.merri-bek.vic.gov.au/my-council/news-and-publications/news/merri-bek-name-for-council-approved/)。边界和名称依据：[ABS ASGS 2024 LGA_GEN](https://geo.abs.gov.au/arcgis/rest/services/ASGS2024/LGA/MapServer/1)，本地文件 hash 见 `public/geo/provenance.json`。
- VIC 以 **ACCIDENT_NO + NODE_ID** 关联 Node，合并重复记录；LGA_NAME 与 LGA NAME ALL 的所有候选必须在 crosswalk 后指向同一地区。2,301 起多地区列表，加 9 起主/附地区不一致，共 2,310 起歧义。71,264 起存在多行 Node 的事故均只计一次。
- 四指标取每个独立事故的原生值；NSW casualties 为四类死伤之和，VIC 为 Accident 三类死伤之和，QLD 为 Count_Casualty_Total。空指标不替换为零。
- 每州 60 个月 × 4 指标，共 **720 个逐月对账**，匹配与未匹配相加都等于正式 reader-results 的源指标。各州全期原生严重程度分类逐项对账。脚本遇到 hash/唯一键/分类/对账错误会停止。

## 界面与接口

进入州后，LGA 多边形按所选日期真实事故数使用珊瑚红色阶。悬停显示名称、事故和致命事故数；点击区域或使用键盘选择 LGA 后，四卡、趋势和严重程度联动。日期旁显示地区筛选，可一键清除；更换来源清除地区。地图保留全州范围便于继续选择，缩放和重置照常使用。

Area details 显示关联方法、计数、来源 Town/Suburb 前八项及证据。NSW 用 Town；QLD 用 Loc_Suburb；VIC 不构造不存在的城市字段。这些标签为区内汇总，不含精确位置。

新增 `Filters.regionId?`；Next API 和 Agent 共同验证代码属于所选州。All 不能带地区。Analytics 沿用地区筛选，显示可清除标签；Ask AI 携带当前地区，换地区会取消旧请求并清空历史。接口详见 `API.md` / `AI.md`。

地图 API 只输出 LGA 聚合及所选地区最多八个 locality 标签；不把整份 3.6 MB 派生快照发给浏览器。原始事故身份、坐标、人员/车辆行均不暴露。

## 运行与复现

正常启动只读取已有 `data/regions/aggregates.json`，不必保留原始文件。要从相同原文件重新生成：

```sh
python3 scripts/build-region-snapshot.py
```

仅使用 Python 标准库，输出在前端 `data/regions/` 及 `src/services/region-catalog.json`。服务端固定校验 aggregate SHA256。原始文件、边界或批次变化时，必须重新审查映射与对账，再更新固定 hash；不可跳过失败。

本轮预览独立使用 `.next-regions` 和端口 3102：

```sh
ARSIA_NEXT_DIST_DIR=.next-regions npm run build
ARSIA_NEXT_DIST_DIR=.next-regions npm run start -- --port 3102
```

## 明确限制

LGA 不等于 city、都市圈或 suburb，Sydney LGA 不等于 Greater Sydney。地图使用 2024 参考边界承载原始历史名称，未按历史年份重建边界，也没有把历史事故重新做空间分配。名称匹配率不能叫作坐标准确率、事故点覆盖率或 QA07 通过率。

VIC 的地区层是用户授权的前端派生扩展，不代表原 restricted-use profile 新增正式地图报告许可；原快照、原 pipeline 输出和 QA 不变。NSW/VIC 坐标 datum 仍未确认，QLD 坐标转换仍未验证，因此未开放事故点、道路热点、自动反向地理编码或城市精确边界。这不是整个 ARSIA 平台验收。
