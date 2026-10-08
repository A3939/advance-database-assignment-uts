# Overview 地图严重程度分类：历史代码与恢复参考

记录日期：2026-10-04（Australia/Sydney）。本文件保存本次只读检查结果和后续开发定位依据。

本次唯一新增内容是这份文档：没有恢复旧版本，没有修改业务代码、数据库、release 或 Studio，没有重启服务，没有提交或推送。本文件中的提取命令和恢复建议尚未执行，不是恢复完成声明。

## 1. 可以找到什么

**旧代码仍在本地 Git 历史中，可以按完整 commit ID 准确提取。** 下面区分“代码版本”与网页 URL 里的“数据版本”：切换 `official-v1` 可以查看旧数据快照，但不会把当前 React 页面切换成旧 HTML 原型。

| 历史代码版本 | 当地时间 | 相关内容与精确位置 |
|---|---|---|
| `c08682760bc294fd36d82d84c1e5d87410a8b5d5` — Initial ARSIA dashboard prototype | 2026-09-29 00:58:52 +10:00 | `index.html:79` 的 Map 页面含 Fatal crashes、Serious injuries、Other crashes 勾选框；`app.js:61` 起是 `layerCounts` 与勾选事件。此版本 Overview 地图本身使用数量渐变。 |
| `4427acbf40a0fa77f9e52be9c764fefafba7ae2c` — Restore six-page ARSIA dashboard design | 2026-09-29 02:13:35 +10:00 | **最接近用户提到的 Overview 地图四类图例。** `app.js:3` 是 `dot()`；`app.js:7` 是完整 `mapSvg()`；`app.js:12` 的 `overview()` 调用它；`app.js:15` 的 Map 页面也复用它。`styles.css:1` 含 `.maplegend`、`.dot.*` 和地图样式。 |
| `362e8ebde2c6084fa7095afc553098e7eb6b91b6` — Replace static prototype with ARSIA analysis platform | 2026-09-29 21:34:27 +10:00 | 改为 React 平台；`src/components/spatial-map.tsx` 中使用 `concentrationToken()` 和数量渐变图例，旧四类严重程度图例没有沿用。 |

这些历史文件较多代码压缩在单行中；精确函数名比行号更适合后续查找。不能把旧原型整套文件直接覆盖当前 Next.js 应用。

## 2. 旧图例的实际含义和限制

`4427acb` 的地图图例为：Fatal（红）、Serious injury（橙）、Other injury（青绿）、Property damage only（蓝）。

该版本 `README.md` 明确说明是静态 HTML/CSS/JavaScript 原型，使用 mock data，没有连接数据库或 API。`mapSvg()` 内的 SVG 边界、点坐标、聚类数量和颜色都是硬编码；`.specks circle:nth-child(...)` 也按元素位置配色。**图例存在不等于当时已经实现了按真实事故严重程度筛选或着色。**

更早的 `c086827` 有分类复选框，但其事件处理只是把硬编码 `layerCounts` 相加、更新 Visible incidents 和提示文字；该处理器没有按类别过滤真实地图记录。

因此可以恢复视觉设计，但真实数据功能还需要当前数据接口、空间聚合和分类语义的支持。不能把旧演示数字或颜色当作真实结果迁入当前页面。

## 3. 本次页面与接口检查结果

检查对象：正常项目目录 `ARSIA` 提供的 `127.0.0.1:3100`，不是另一个临时预览端口。检查包括真实浏览器页面、只读 `/api/data/catalog`、`/api/data/map`、`/api/data/severity`，以及本地源码和 Git 历史。

| 数据选择（2020-01-01 至 2024-12-31） | 地图结果 | 严重程度分布 |
|---|---|---|
| `local-integrated-v1`，release `ff8b9868-515f-48c4-95c0-33ffbae73430` | NSW、VIC、QLD 均为 `geography: false`，接口 `availability: unsupported`，无区域/网格数据，页面显示 Geography unavailable | NSW 5 类；VIC 4 类；QLD 4 类，均 available |
| `official-v1`，batch `bcc5da57-25f2-41ec-9925-bef421b02671` | NSW 129、VIC 80、QLD 78 个 LGA 区域，接口均 available | NSW 5 类；VIC 4 类；QLD 4 类，均 available |

浏览器实查 NSW：本地 release 只有边界和不可用说明；旧快照显示 LGA 着色、`Recorded crashes · LGA`、99.995% matched、5 unmatched，以及 1–4,573 crashes 的数量图例。两种数据版本右侧 Crash severity 都正常，NSW 五类数量相同：Fatal 1,388；Minor/Other Injury 15,483；Moderate Injury 26,115；Non-casualty (towaway) 29,507；Serious Injury 19,589。

这里是两个独立问题：

1. **地图严重程度图例改成数量图例**：历史页面实现变化，当前两种数据模式共用的地图组件都没有旧四类分类图例。
2. **本地发布地图能力缺失**：本地目录用同名已发布数据源替换 snapshot 条目，但未保留旧 LGA 数据提供能力，最终进入 Geography unavailable 分支。恢复图例的 CSS 不会修好这一数据路径。

这些是检查时的状态，不代表所有历史 release 或其他部署都已逐一测试。当前主线程继续开发时，源码或运行状态可能变化，应按本文件末尾指纹重新确认。

对比链接（仅适用于这台电脑的现有服务）：

- [当前 NSW 本地 release](http://127.0.0.1:3100/?source=NSW&from=2020-01-01&to=2024-12-31&datasetVersion=local-integrated-v1&batchId=ff8b9868-515f-48c4-95c0-33ffbae73430&releaseId=ff8b9868-515f-48c4-95c0-33ffbae73430&metric=crashes&interval=monthly&overviewInterval=monthly)
- [NSW 原官方快照](http://127.0.0.1:3100/?source=NSW&from=2020-01-01&to=2024-12-31&datasetVersion=official-v1&batchId=bcc5da57-25f2-41ec-9925-bef421b02671&metric=crashes&interval=monthly&overviewInterval=monthly)

## 4. 关键历史代码留存

以下代码直接从指定 Git 对象读取并嵌入，没有运行。即使以后只打开这份文档，也能看到核心旧实现；完整页面依赖应从历史版本提取。

### 4.1 四类图例和完整地图函数

来源：`4427acbf40a0fa77f9e52be9c764fefafba7ae2c:app.js`。保留原文，包括硬编码演示图形和数量。

```javascript
const dot=c=>`<i class="dot ${c}"></i>`;
const mapSvg=()=>`<div class="mapbox"><div class="zoom"><button>＋</button><button>−</button><button>◎</button></div><svg viewBox="0 0 720 500"><g class="states"><path d="M64 105 270 65 295 105 270 350 183 405 76 308Z"/><path d="M279 63 431 64 430 240 293 240 295 105Z"/><path d="M293 247 429 247 507 367 393 408 270 350Z"/><path d="M438 63 579 86 663 180 570 268 488 241 430 240Z"/><path d="M492 248 572 273 605 360 505 384 450 320Z"/><path d="M448 324 505 390 450 425 392 408Z"/><path d="M470 450 517 444 505 493 476 489Z"/></g><g class="labels"><text x="170" y="250">WA</text><text x="355" y="155">NT</text><text x="366" y="330">SA</text><text x="525" y="170">QLD</text><text x="525" y="325">NSW</text><text x="454" y="395">VIC</text><text x="490" y="478">TAS</text></g><g class="specks">${[[110,180],[126,268],[150,330],[185,380],[340,110],[500,130],[540,210],[570,270],[575,315],[535,355],[465,390],[490,465]].map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="4"/>`).join('')}</g><g id="clusters" class="clusters">${[['110','278','427',''],['355','140','186','orange'],['520','195','1,042',''],['585','318','2,381','danger'],['460','390','1,276',''],['495','462','203','orange']].map(x=>`<g transform="translate(${x[0]} ${x[1]})" class="${x[3]}"><circle r="37"/><circle r="26"/><text y="5">${x[2]}</text></g>`).join('')}</g><g id="heat" class="heat hidden"><circle cx="585" cy="318" r="85"/><circle cx="460" cy="390" r="62"/><circle cx="520" cy="195" r="58"/><circle cx="110" cy="278" r="48"/></g></svg><div class="maplegend"><span>${dot('red')}Fatal</span><span>${dot('amber')}Serious injury</span><span>${dot('teal')}Other injury</span><span>${dot('blue')}Property damage only</span></div></div>`;
```

对应 CSS 核心规则，保留原选择器和属性，只为阅读加入换行：

```css
.maplegend {position:absolute;bottom:15px;left:14px;background:#fff;border-radius:5px;padding:10px 12px;display:grid;gap:6px;font-size:12px;box-shadow:0 2px 8px #7896}
.dot {width:12px;height:12px;border-radius:50%;display:inline-block;vertical-align:-1px;margin-right:7px}
.dot.red {background:var(--red)}
.dot.amber {background:var(--amber)}
.dot.teal {background:var(--teal)}
.dot.blue {background:#2c8bdb}
```

该版配色变量为 `--red: #ed3745`、`--amber: #ff9f0a`、`--teal: #0ba394`；`.dot.blue` 直接使用 `#2c8bdb`。小屏原样式另有 `@media(max-width:500px)`，将 `.maplegend` 字号设为 9px。完整定位、底图、响应式样式仍以历史 `styles.css` 为准。

### 4.2 更早的分类勾选事件

来源：`c08682760bc294fd36d82d84c1e5d87410a8b5d5:app.js`。此段仅演示界面计数，不是实际按严重程度过滤数据。

```javascript
const layerCounts = { fatal: 5724, serious: 42306, other: 70452 };
document.querySelectorAll('[data-layer]').forEach(input => input.addEventListener('change', () => {
  const total = [...document.querySelectorAll('[data-layer]:checked')].reduce((sum, item) => sum + layerCounts[item.dataset.layer], 0);
  document.getElementById('visibleIncidents').textContent = total.toLocaleString();
  showToast('Map layers updated');
}));
```

对应控件位于同版本 `index.html` 的 `#view-map` → `fieldset`，属性分别是 `data-layer="fatal"`、`data-layer="serious"`、`data-layer="other"`。

## 5. 后续准确提取完整旧文件

在项目根目录执行以下只读 Git 命令，可查看旧文件，无需切换分支、checkout 或 reset：

```sh
cd '/Users/zhengpeixian/ZPX/UTS/Advanced Database/Assignment 2/Workspace/ARSIA'
git show 4427acbf40a0fa77f9e52be9c764fefafba7ae2c:app.js
git show 4427acbf40a0fa77f9e52be9c764fefafba7ae2c:styles.css
git show 4427acbf40a0fa77f9e52be9c764fefafba7ae2c:index.html
git show c08682760bc294fd36d82d84c1e5d87410a8b5d5:app.js
```

若后续需要完整的静态参考副本，下面命令只会创建一个新的临时目录并将选定历史文件导出其中；不会覆盖工作区，也不启动任何服务。本次没有执行这些导出命令。

```sh
ref_dir=$(mktemp -d /tmp/arsia-map-reference.XXXXXX)
git archive 4427acbf40a0fa77f9e52be9c764fefafba7ae2c   app.js styles.css index.html README.md | tar -x -C "$ref_dir"
printf '%s\n' "$ref_dir"
```

若需长期独立留存完整旧站，可把该新目录作为参考资料另行保存；嵌入本文件的核心代码不依赖历史 Git 对象继续可用。

## 6. 当前代码入口与后续恢复范围

以下是检查时的入口，行号可能随主线程开发移动，应优先查找函数名。

| 当前文件 | 具体入口 | 后续用途 |
|---|---|---|
| `src/components/spatial-map.tsx` | `SpatialMap()`、`BoundaryMap()`、`concentrationToken()`；约 587 行的 `.map-bottom-bar` / `.map-legend` | 当前 MapLibre 与 SVG fallback 地图；数量图例与底部布局。恢复分类样式或新图层控件的主要入口。 |
| `src/components/point-grid-map.tsx` 与 `.module.css` | 发布坐标网格地图 | 当前存在单独网格分支；未来分类图层不能只修改 LGA 分支而遗漏网格分支。 |
| `src/lib/map-scale.ts` | `mapCountBand()`、`mapCountBins()` | 事故数量色阶；不能只改文字就宣称色阶代表严重程度。 |
| `src/components/overview.tsx` | `<SpatialMap>`；约 525 行的 Crash severity 面板 | 页面组合和右侧分类图；后者当前仍正常。 |
| `src/components/charts.tsx` | 严重程度数据的柱状图渲染分支 | 原生严重程度类别及数量的柱状图。 |
| `src/services/contracts.ts` | `MapData`、`MapRegion`、`Severity` | 当前地图聚合与严重程度分布分开；分类地图需要可验证的空间 × 类别数据结构。 |
| `src/server/data-catalog.ts` | `resolveCatalog()`；约 40–50 行 | 按 source ID 将 snapshot 条目替换为 publication 条目及其能力。 |
| `src/server/published-data.ts` | `getMapData()`；约 72–98 行 | snapshot 委托旧数据提供器；publication 读取已验证坐标网格；否则 Geography unavailable。 |
| `src/server/region-data.ts` | `getMapData()`、`getSeverityDistribution()` | 旧快照 LGA 区域与选中 LGA 的严重程度统计。 |
| `src/server/official-data.ts` | `getSeverityDistribution()` | 州级快照的分类统计只支持完整 2020–2024；不能按月份比例分摊。 |
| `pipeline/arsia_pipeline/query.py` | `metadata()` 中的能力投影、地理查询分支 | 发布数据源的 geography 能力和聚合输出；不可只将 false 改为 true 而无实际数据。 |

建议把后续需求写成以下两个独立、可验收的改动，不需要回滚整个站点：

1. **恢复本地 release 的可信地图数据**：核对发布批次与旧 LGA 派生数据的来源、覆盖和内容绑定，接入匹配的区域聚合或生成当前批次的地理聚合。不能把旧快照地图静默贴到不同版本的统计卡片旁，也不能以能力开关代替证据。
2. **增加严重程度地图展示**：借鉴旧图例布局与配色，但分类名称来自当前州的原始定义；将类别选择明确应用于空间聚合和图例。若只是展示旁注，应注明是全州分类，不表示当前地图颜色。不能把事故总量渐变重新命名成严重程度。

后续验收至少确认：地图、图例、分类计数和筛选范围一致；切换日期、来源、release、LGA 后不串用旧数据；未知分类和缺失位置保持明确；各州类别不强行合并；深浅主题及窄屏可读；无地图能力时仍诚实显示不可用。旧原型的硬编码点、聚类数和勾选计数不能用作真实验收依据。

## 7. 文件指纹与留存边界

旧版完整文件的 SHA-256（对 `git show <commit>:<path>` 原始字节计算）：

| `4427acbf40a0fa77f9e52be9c764fefafba7ae2c` 中的文件 | SHA-256 |
|---|---|
| `app.js` | `8d3ac9339f89d83a8b974a4519143baceec6957c271d6a5770b70f47efd7be59` |
| `styles.css` | `ca2f2a3066234794e8a81aff2ab829cd622d028709c6afb123f32d961dbe7b25` |
| `index.html` | `2353d2006e4f80a4e19a79a5e292096470109d9ae1bebe26c7893d726bd52f78` |
| `README.md` | `3fdb46ec5245f496d537d804449ef53ccb717503669e0ce36ba0d155f92ef27b` |

检查时当前工作区相关文件的 SHA-256，用于识别后续并发开发后的版本差异；这不是运行中构建产物的哈希，也不能替代数据库内容核验：

| 当前文件 | SHA-256 |
|---|---|
| `src/components/spatial-map.tsx` | `c6057b92e2530968ddbb394ce533035b60c6466f56fa13d22a6ed07efcea30af` |
| `src/components/overview.tsx` | `bb5a0230bab5383cf340d4f04312cc96b4a48c1c14b16bc218745df226b21738` |
| `src/server/published-data.ts` | `84cac6a9baf21c072a741d91ce5f5dcb4ad2ee347752a90caff963c1294dc072` |
| `src/server/data-catalog.ts` | `0da626c1a066a30f6b68d87ba53bd5c93349eb95a60ca523a1a84a88cfad7001` |
| `src/server/region-data.ts` | `9ebf64433ea2fede979fe38ca7aef9d77939589e4a213399d0b8375a5b1a09fb` |
| `src/services/contracts.ts` | `86c418381f0933a883f159406e16332bbaaa2abf036913d8a98efac8995b081f` |

这份文档保存了恢复线索、核心旧代码、当前原因和实施边界；尚未恢复分类图例、分类地图或本地 release 的 LGA 能力。后续修改仍需复核当时源码和在途任务，避免覆盖主线程或其他窗口的更新。
