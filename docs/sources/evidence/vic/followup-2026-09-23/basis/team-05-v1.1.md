# 来源、原生输入与核心映射

**协作合同 v1.1 · 2026-09-14。** 默认事故发生年2020–2024，范围配置化。本文给出可共同实现的结构规则及映射候选；官方发布兼容性、分类/人数定义和CRS仍须来源证据确认，不因表头一致或合成通过而批准official发布。接口、QA、样例和责任见[04](04-团队分工与验收.md)。

## 1. 七资源及成员交接

| 资源 / 调研主责 | 原生粒度与完整键 | 列数 | 本地文件 / 读取 |
|---|---|---:|---|
| T1 NSW Crash / A | 一事故；Crash ID | 50 | nsw_crash_2020_2024.xlsx，Sheet1，第1行表头 |
| T2 NSW Traffic Unit / A | 事故内一单元；Crash ID + Traffic unit ID | 10 | nsw_traffic_unit_2020_2024.xlsx，Export，第1行表头 |
| T3 VIC Accident / B | 一事故；ACCIDENT_NO | 23 | vic_accident.csv |
| T4 VIC Vehicle / B | 事故内一车辆；ACCIDENT_NO + VEHICLE_ID | 37 | vic_vehicle.csv |
| T5 VIC Person / C | 一人员记录；候选键ACCIDENT_NO + PERSON_ID | 14 | vic_person.csv |
| T6 VIC Node / C | 一位置观察；ACCIDENT_NO + NODE_ID仅为匹配键，不先假定唯一 | 11 | vic_node.csv |
| T7 QLD Road crash locations / D | 一事故；Crash_Ref_Number | 52 | qld_crash_locations.csv |

附件ZIP保持路径 `Resources/source/raw/`（七原件）和 `Resources/source/metadata/`（三来源元数据）。成员只读原件，生成结果另存。T1/T2是一组，T3–T6是一组，T7独立；时间接近、哈希齐全或能JOIN均不能单独证明兼容发布。当前本地组合尚待确认，不伪称统一官方发布。

全197列保留在raw.payload及归档原件。Person仅raw及必要检查；Node观察完整留存，可信位置才进入事故；QLD Count_Unit_*只留原值，不展开车辆/人员或增加分类事实。NSW交通单元与VIC车辆各保留统计范围，不能默认同义。

## 2. B/C共同遵守的原生规则

| 项目 | 固定规则 |
|---|---|
| CSV | UTF-8，允许开头BOM且只去BOM；使用CSV逻辑记录解析，不能按物理换行切含引号字段。表头与§7有序列表完全一致。原字段值保持文本，空字段保留空串，不在Python改业务缺失码。 |
| XLSX | 按指定sheet及第1行表头；文本单元格原样，空单元格为NULL，数值以固定无指数十进制文本提取，原格式仍在归档原件追溯。日期单元格按parser固定ISO表示，公式/意外类型先归档再阻断确认，不能猜缓存值。合成ID单元格必须写文本以保留0001。 |
| 行定位 | CSV数据逻辑记录从1编号，locator为文本csv:1、csv:2等；XLSX为JSON数组文本[sheet,物理行号]，首数据行2。locator_version固定并进manifest；不使用排序后编号。 |
| 空行与表头 | CSV中完全空白逻辑记录、XLSX尾部全空行排除且计入解析日志；有分隔列的空值记录仍算数据并接受后续坏键检查。中间空行不使XLSX后续原行号改变。新增/缺失/重命名/换序列先归档，再block并更新合同，不静默忽略。 |
| 原生身份 | raw按资源+文件SHA256+parser+row_locator去重；同定位不同payload为错误。文件字节哈希不等于构建指纹。元数据raw_count指纳入的原生数据行，按同一parser重放应完全一致。 |
| 业务身份 | SQL把完整原生键组件作为文本按声明顺序编码为PostgreSQL 16 JSON数组文本。crash为[事故ID]，unit为[事故ID,单元ID]；外层再加source_id、release_scope，快照层加batch_id。无分隔符拼接，不将ID转整数，不自动改变大小写、去前导零或修剪有效ID。空/全空白键block。 |
| 类型与缺失 | SQL按字段合同把空串/明确缺失token转NULL并给原因；没有证据的NA/Unknown/0不能统一当缺失。非缺失非法整数、非法日期、负人数block；坐标非法交位置处置，不因此删除事故。 |

共同键一致性样例：原生事故文本0001的数组只有一个文本成员；单元0001/01有两个文本成员。A/B/C不得分别采用无空格JSON、带空格JSON或普通字符串拼接作为不同文本主键；**业务键编码也统一由SQL生成**。B只传原生组件。

## 3. 事故与真实单元的核心映射

“字段已在本地表头观察到”只确认结构来源。涉及定义的候选必须由调研主责+C记录依据和版本，D复核可分析性。以下统一写入04的类型化投影，之后通过Satellite进入Canonical。

| 目标 / 处理 | NSW T1 | VIC T3 | QLD T7 |
|---|---|---|---|
| crash_key | Crash ID | ACCIDENT_NO | Crash_Ref_Number |
| occurrence_year | Year of crash转整数；不用Reporting year | 从ACCIDENT_DATE提取年 | Crash_Year转整数 |
| occurrence_month | Month of crash按英文月份表转换；已明确缺失时NULL | 从真实日期提取月 | Crash_Month按英文月份表转换；明确缺失时NULL |
| occurrence_date / date_precision | 日期NULL；有月为month，仅年为year | ACCIDENT_DATE按YYYY-MM-DD解析为真实日期，精度day | 日期NULL；有月为month，仅年为year |
| severity_raw | Degree of crash - detailed原值 | SEVERITY原值文本 | Crash_Severity原值 |
| severity_code | 来源内原类别文本；明确缺失映射__MISSING__ | 来源内原代码文本；明确缺失映射__MISSING__ | 来源内原类别文本；明确缺失映射__MISSING__ |
| is_fatal_crash（候选） | Fatal→true；其他已登记类别→false | 1→true，2/3/4→false | Fatal→true；其他已登记类别→false |
| fatality_count（候选口径） | No. killed | NO_PERSONS_KILLED | Count_Casualty_Fatality |
| casualty_count（候选口径） | No. killed + No. seriously injured + No. moderately injured + No. minor-other injured | NO_PERSONS_KILLED + NO_PERSONS_INJ_2 + NO_PERSONS_INJ_3 | Count_Casualty_Total；另核对Fatality/Hospitalised/MedicallyTreated/MinorInjury四分项 |
| 原声明单元数（检查用） | No. of traffic units involved | NO_OF_VEHICLES | 无真实单元明细，不由Count_Unit_*造单元 |
| 位置候选 | Latitude / Longitude | 本事故ACCIDENT_NO+NODE_ID匹配T6，取其LATITUDE/LONGITUDE候选 | Crash_Latitude / Crash_Longitude |

英文月份表固定：January=1、February=2、March=3、April=4、May=5、June=6、July=7、August=8、September=9、October=10、November=11、December=12。SQL可按合同修剪月份字段外围空白；其他非空未知月份block，不能误当年份精度。真实日期非法或缺失且无法得到有依据的发生年时block，不从报告年补齐。

NSW候选非死亡类别为Non-casualty (towaway)、Moderate Injury、Serious Injury、Minor/Other Injury；QLD为Hospitalisation、Medical treatment、Minor injury、Property damage only。这些是已有候选，不是本轮已批准定义。新非空类别不能默认false或__MISSING__，必须block并补版本化定义；真正缺失按已确认合同可保留未知。

| 目标 / 处理 | NSW T2 | VIC T4 |
|---|---|---|
| crash_key / unit_key | [Crash ID] / [Crash ID,Traffic unit ID] | [ACCIDENT_NO] / [ACCIDENT_NO,VEHICLE_ID] |
| unit_type_raw / unit_type_code | TU type group原文及来源内映射代码 | VEHICLE_TYPE原代码；VEHICLE_TYPE_DESC保留source_extra，不能替代代码 |
| statistical_scope | 来源合同定义的交通单元范围及版本 | 来源合同定义的车辆范围及版本 |
| count_eligible / quality_notes | 类型、父关系、统计范围已确认才true，否则false并留原因；未定义非空类别按QA05处置 | 同左；不与NSW直接合并成跨州统一车辆数 |

共用字段来源：batch_id来自运行上下文；source_id/release_scope来自冻结source；raw_record_id为选中主原始行；severity_definition_version来自冻结分类定义；quality_notes按§4。fact_crash与维度交接规则见04，界面不再做映射。

三项指标资格分别计算：已确认定义且该行值可判断/计量才true；未知值保持NULL、资格false并留原因。必要加项任一个未知，合计NULL，不用0代替。死亡事故数与死亡人数分列，参与人数不等于伤亡人数。定义本身未知会阻断official发布，不能仅将所有资格设false来规避合同确认。

## 4. Person、Node与质量原因

Person检查：ACCIDENT_NO必须有同源同版事故；候选人员键ACCIDENT_NO+PERSON_ID须核验唯一性。VEHICLE_ID空白按来源合同区分“合法不关联”与异常，非空则按完整事故+车辆键匹配；找不到为block，不造车辆。T3 NO_PERSONS与T5人数仅在包含范围一致且已确认时对账，不将历史例外数量当自动容忍阈值。

Node检查：按ACCIDENT_NO+NODE_ID匹配事故的NODE_ID；保留每条原生观察。匹配键不是唯一键。把候选坐标以未舍入的精确十进制数比较，先校验完整性、数值、范围及CRS，不能用保留7位后的相同数掩盖原观察差异。

只有该事故匹配观察均为有效完整坐标，且唯一精确坐标对、CRS及关系有依据时可用。重复观察等价时，按文件哈希、parser_version、原始行数值位置排序选代表行，仅用于location_record_id；全部其他观察仍raw可查。多对坐标、部分无效观察、缺失或无法确认时不任取首行/平均值，map_eligible=false并记依据。缺位置候选不是补造Node的理由；非空Node引用真正无父事故属于关系错误，QA04 block。

有地图资格时latitude/longitude均为有限有效值，location_crs非空且EPSG:4326，location_record_id匹配正确事故/节点；需要变换的坐标必须实际变换并验证，不能改标签。无可信位置时Canonical经纬度、CRS及位置定位均NULL；原始候选和冲突定位仍留raw及quality_notes。地图缺失只限制空间用途，不删除其他指标合格事故。

quality_notes为对象，固定可选成员 `fields[]、location、references[]`。fields每项含field、reason_code、raw_token（可NULL）、contract_version；location含reason_code、candidate_raw_record_ids[]、resolution、evidence_ref。原因词汇固定：missing、unmapped、definition_unconfirmed、invalid_coordinate、crs_unconfirmed、location_conflict、no_location。非空非法核心值仍block，不能靠写notes放行。指标资格false或位置资格false须存在对应原因；人员/节点检查的原因同时进入QA证据。

## 5. 来源合同的最小确认记录

| 部分 | 每资源必填 |
|---|---|
| 输入 | resource_id、source_id、角色/实体、下载链接/发布者/许可、实际哈希、format/encoding/sheet/header、parser/locator版本；原生全字段固定，链接不能只留门户首页。 |
| 身份/范围 | 完整键组件及顺序、父键、release_label/release_scope、兼容文件组合依据、实际覆盖年月、筛选与范围外记录规则。 |
| 语义/映射 | 本文首期目标字段的原字段、操作、参数、NULL/token、分类定义/版本、资格条件、指标包含范围、单位及CRS依据。无单位/人数等新功能字段要求。 |
| 变化 | 完整快照相对上一批的记录删除、数量减少或覆盖缩减说明及预期影响；未说明则QA01 block，不自动继承旧事实。 |
| 确认 | status=draft/confirmed；每项证据的URL或文件+页/章节、核对日期、调研主责、C复核、未决问题和处置；官方业务定义draft禁止发布。 |

结构提取已可按本地文件验证；**官方来源合同当前仍draft**。下面工作各有主责，不让所有人等待同一个人：A核NSW定义与两文件组合；B核VIC事故/车辆/人员数量及四文件组合；C核Person空引用、Node关系及CRS；D核QLD伤亡分项/类别及CRS；C汇总口径，D核报表，E登记DEC04/05。可以先用独立synthetic合同开发，不虚构官方确认。

新州使用已支持格式/实体/粒度时，增加来源、文件、合同与映射并复用主流程；新格式补适配器，新操作补SQL，新实体/粒度评审迁移。不承诺任意州零代码接入，不提前添加新州核心表。

## 6. 三个来源模型与查询证据

| 来源 | 需要成员实际展示的模型/查询 |
|---|---|
| NSW | Crash→Traffic Unit完整键关系；原生行数、重复键、孤儿；已确认口径的事故声明单元数对账；发生年与Reporting year差异。 |
| VIC | Accident→Vehicle/Person、Person非空Vehicle引用、Accident→Node观察匹配；重复/孤儿、Node不同坐标对与JOIN放大；人员/节点raw保留证据。 |
| QLD | 一事故一行、分类计数为行内聚合属性；原生键/月份/严重度查询、未知人数和位置覆盖；没有虚构单元实体。 |

可先提出三个来源逻辑schema/原生视图供教师确认，不能把三份文件或三条source记录当完成。具体来源系统证据形式按04 DEC01决定。至少一个整合仓库、三份合成报表、可执行注释SQL、录像、个人贡献及会议证据由团队实际形成。

## 7. 本地快照与完整表头

下面清单用于B/C核对原生传输，所有列仍须保留；没有要求把全部列统一成业务字段。哈希和表头是本次对已有本地文件的只读核对，不证明最新官方发布、完整语义、全量QA或数据库运行已通过。

| 资源 | 已有本地文件SHA256 | 原登记下载地址 |
|---|---|---|
| T1 | `7345189f017d9c842429674ecf2196cee728de46c0572ce2a85220f9bef49aa9` | [nsw_crash_2020_2024.xlsx](https://opendata.transport.nsw.gov.au/data/dataset/06f9cf3d-0a9d-4098-b0f0-fa9efbdd3921/resource/c6351d27-b1b0-48e9-93a6-a612cba88f99/download/nsw_road_crash_data_2020-2024_crash.xlsx) |
| T2 | `95349666f63952c580edb08973a8ac80be39db98ba289ec8533d61feb6d55f1b` | [nsw_traffic_unit_2020_2024.xlsx](https://opendata.transport.nsw.gov.au/data/dataset/06f9cf3d-0a9d-4098-b0f0-fa9efbdd3921/resource/fbd0a0da-aa1f-4233-a974-d674713ad4a5/download/nsw_road_crash_data_2020-2024_traffic_unit.xlsx) |
| T3 | `a148c00601fab10d44368df80492c594123700a7f9e334ff896fd215295e91d9` | [vic_accident.csv](https://opendata.transport.vic.gov.au/dataset/bb77800e-1857-4edc-bf9e-e188437a1c8e/resource/20772c1a-8b19-424a-a733-eb84f725f611/download/accident.csv) |
| T4 | `05a7a1b9171abaeb5c188df549dee38edde6e76d5a03553988305a8280dccd12` | [vic_vehicle.csv](https://opendata.transport.vic.gov.au/dataset/bb77800e-1857-4edc-bf9e-e188437a1c8e/resource/6d0b21f7-583a-4991-a168-f15a70c13ec4/download/vehicle.csv) |
| T5 | `71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9` | [vic_person.csv](https://opendata.transport.vic.gov.au/dataset/bb77800e-1857-4edc-bf9e-e188437a1c8e/resource/60c8fc0c-2806-40f3-bb33-5c52691120e8/download/person.csv) |
| T6 | `b0bdbec22ac33df66e15cff9b531ba3203320ec5fbe20076a2820b8fec966ed4` | [vic_node.csv](https://opendata.transport.vic.gov.au/dataset/bb77800e-1857-4edc-bf9e-e188437a1c8e/resource/466fd3b5-201b-42b5-b10d-e926324fa215/download/node.csv) |
| T7 | `975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704` | [qld_crash_locations.csv](https://www.data.qld.gov.au/dataset/f3e0ca94-2d7b-44ee-abef-d6b06e9b0729/resource/e88943c0-5968-4972-a15f-38e120d72ec0/download/_1_crash_locations.csv) |

完整表头按原顺序列出；可折叠阅读。

<details><summary>T1 · nsw_crash_2020_2024.xlsx · 50列</summary>

1. `Crash ID`
2. `Degree of crash`
3. `Degree of crash - detailed`
4. `Reporting year`
5. `Year of crash`
6. `Month of crash`
7. `Day of week of crash`
8. `Two-hour intervals`
9. `Street of crash`
10. `Street type`
11. `Distance`
12. `Direction`
13. `Identifying feature`
14. `Identifying feature type`
15. `Town`
16. `Route no.`
17. `School zone location`
18. `School zone active`
19. `Type of location`
20. `Latitude`
21. `Longitude`
22. `LGA`
23. `Urbanisation`
24. `Conurbation 1`
25. `Alignment`
26. `Primary permanent feature`
27. `Primary temporary feature`
28. `Primary hazardous feature`
29. `Street lighting`
30. `Road surface`
31. `Surface condition`
32. `Weather`
33. `Natural lighting`
34. `Signals operation`
35. `Other traffic control`
36. `Speed limit`
37. `Road classification (admin)`
38. `RUM - code`
39. `RUM - description`
40. `DCA - code`
41. `DCA - description`
42. `DCA supplement`
43. `First impact type`
44. `Key TU type`
45. `Other TU type`
46. `No. of traffic units involved`
47. `No. killed`
48. `No. seriously injured`
49. `No. moderately injured`
50. `No. minor-other injured`

</details>

<details><summary>T2 · nsw_traffic_unit_2020_2024.xlsx · 10列</summary>

1. `Crash ID`
2. `Traffic unit ID`
3. `TU controlled flag`
4. `TU role in first impact`
5. `TU type group`
6. `Street of travel`
7. `Direction of travel`
8. `Manoeuvre`
9. `Object hit 1`
10. `Object hit 2`

</details>

<details><summary>T3 · vic_accident.csv · 23列</summary>

1. `ACCIDENT_NO`
2. `ACCIDENT_DATE`
3. `ACCIDENT_TIME`
4. `ACCIDENT_TYPE`
5. `ACCIDENT_TYPE_DESC`
6. `DAY_OF_WEEK`
7. `DAY_WEEK_DESC`
8. `DCA_CODE`
9. `DCA_DESC`
10. `LIGHT_CONDITION`
11. `NODE_ID`
12. `NO_OF_VEHICLES`
13. `NO_PERSONS_KILLED`
14. `NO_PERSONS_INJ_2`
15. `NO_PERSONS_INJ_3`
16. `NO_PERSONS_NOT_INJ`
17. `NO_PERSONS`
18. `POLICE_ATTEND`
19. `ROAD_GEOMETRY`
20. `ROAD_GEOMETRY_DESC`
21. `SEVERITY`
22. `SPEED_ZONE`
23. `RMA`

</details>

<details><summary>T4 · vic_vehicle.csv · 37列</summary>

1. `ACCIDENT_NO`
2. `VEHICLE_ID`
3. `VEHICLE_YEAR_MANUF`
4. `VEHICLE_DCA_CODE`
5. `INITIAL_DIRECTION`
6. `ROAD_SURFACE_TYPE`
7. `ROAD_SURFACE_TYPE_DESC`
8. `REG_STATE`
9. `VEHICLE_BODY_STYLE`
10. `VEHICLE_MAKE`
11. `VEHICLE_MODEL`
12. `VEHICLE_POWER`
13. `VEHICLE_TYPE`
14. `VEHICLE_TYPE_DESC`
15. `VEHICLE_WEIGHT`
16. `CONSTRUCTION_TYPE`
17. `FUEL_TYPE`
18. `NO_OF_WHEELS`
19. `NO_OF_CYLINDERS`
20. `SEATING_CAPACITY`
21. `TARE_WEIGHT`
22. `TOTAL_NO_OCCUPANTS`
23. `CARRY_CAPACITY`
24. `CUBIC_CAPACITY`
25. `FINAL_DIRECTION`
26. `DRIVER_INTENT`
27. `VEHICLE_MOVEMENT`
28. `TRAILER_TYPE`
29. `VEHICLE_COLOUR_1`
30. `VEHICLE_COLOUR_2`
31. `CAUGHT_FIRE`
32. `INITIAL_IMPACT`
33. `LAMPS`
34. `LEVEL_OF_DAMAGE`
35. `TOWED_AWAY_FLAG`
36. `TRAFFIC_CONTROL`
37. `TRAFFIC_CONTROL_DESC`

</details>

<details><summary>T5 · vic_person.csv · 14列</summary>

1. `ACCIDENT_NO`
2. `PERSON_ID`
3. `VEHICLE_ID`
4. `SEX`
5. `AGE_GROUP`
6. `INJ_LEVEL`
7. `INJ_LEVEL_DESC`
8. `SEATING_POSITION`
9. `HELMET_BELT_WORN`
10. `ROAD_USER_TYPE`
11. `ROAD_USER_TYPE_DESC`
12. `LICENCE_STATE`
13. `TAKEN_HOSPITAL`
14. `EJECTED_CODE`

</details>

<details><summary>T6 · vic_node.csv · 11列</summary>

1. `ACCIDENT_NO`
2. `NODE_ID`
3. `NODE_TYPE`
4. `AMG_X`
5. `AMG_Y`
6. `LGA_NAME`
7. `LGA NAME ALL`
8. `DEG_URBAN_NAME`
9. `LATITUDE`
10. `LONGITUDE`
11. `POSTCODE_CRASH`

</details>

<details><summary>T7 · qld_crash_locations.csv · 52列</summary>

1. `Crash_Ref_Number`
2. `Crash_Severity`
3. `Crash_Year`
4. `Crash_Month`
5. `Crash_Day_Of_Week`
6. `Crash_Hour`
7. `Crash_Nature`
8. `Crash_Type`
9. `Crash_Longitude`
10. `Crash_Latitude`
11. `Crash_Street`
12. `Crash_Street_Intersecting`
13. `State_Road_Name`
14. `Loc_Suburb`
15. `Loc_Local_Government_Area`
16. `Loc_Post_Code`
17. `Loc_Police_Division`
18. `Loc_Police_District`
19. `Loc_Police_Region`
20. `Loc_Queensland_Transport_Region`
21. `Loc_Main_Roads_Region`
22. `Loc_ABS_Statistical_Area_2`
23. `Loc_ABS_Statistical_Area_3`
24. `Loc_ABS_Statistical_Area_4`
25. `Loc_ABS_Remoteness`
26. `Loc_State_Electorate`
27. `Loc_Federal_Electorate`
28. `Crash_Controlling_Authority`
29. `Crash_Roadway_Feature`
30. `Crash_Traffic_Control`
31. `Crash_Speed_Limit`
32. `Crash_Road_Surface_Condition`
33. `Crash_Atmospheric_Condition`
34. `Crash_Lighting_Condition`
35. `Crash_Road_Horiz_Align`
36. `Crash_Road_Vert_Align`
37. `Crash_DCA_Code`
38. `Crash_DCA_Description`
39. `Crash_DCA_Group_Description`
40. `DCA_Key_Approach_Dir`
41. `Count_Casualty_Fatality`
42. `Count_Casualty_Hospitalised`
43. `Count_Casualty_MedicallyTreated`
44. `Count_Casualty_MinorInjury`
45. `Count_Casualty_Total`
46. `Count_Unit_Car`
47. `Count_Unit_Motorcycle_Moped`
48. `Count_Unit_Truck`
49. `Count_Unit_Bus`
50. `Count_Unit_Bicycle`
51. `Count_Unit_Pedestrian`
52. `Count_Unit_Other`

</details>

附件另含三份来源元数据和Assignment 1、Assignment 2、课程大纲、选源说明四份PDF。未重新下载官方文件，不把本地哈希核对说成最新发布确认。
