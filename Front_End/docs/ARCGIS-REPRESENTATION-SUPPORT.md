# Bounded ArcGIS representation evidence v1

Protocol references consulted 2026-10-02 (live documentation; no vendor release pinned):
- https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/ (query operation10.0+, GeoJSON RFC7946 behavior10.8+, date-field UTC response and per-field timezone discussion)
- https://developers.arcgis.com/rest/services-reference/enterprise/layer-feature-service/ (layer id/fields/objectIdField/dateFieldsTimeReference/timeZoneIANA, service version metadata)
- https://www.rfc-editor.org/rfc/rfc7946#section-4 (geometry longitude/latitude, CRS84)

Implementation rule `arcgis-bounded-representation-v1`, integrated in existing graph and trusted QA. Source identity is distinct from parameter-preserving representation. Explicit service layers[] membership authorizes a layer; same exact layer endpoint and verified definition relate its query representation. Both directions of definition/representation evidence require official byte receipts; shared hostname/prefix alone never authorizes a layer. Metadata schema may explain output fields; extent CRS cannot override output geometry. Source semantics/category/count checks remain separate.

Supported filters: `1=1`, or one literal field with `>= DATE 'YYYY-MM-DD' AND < DATE 'YYYY-MM-DD'`. Distinct field projection, simple field ordering, JSON/pjson or RFC7946 GeoJSON (outSR absent/4326), boolean geometry, numeric WKID, first page with maximum20000 requested rows. Repeated/unknown parameters, ambiguous encoding, unsupported SQL/statistics, nonzero offset, unknown/time-aware/editor-tracking date overrides stop explicitly. Multi-page whole exports continue to use the existing export verifier and are not granted by this rule.

Required host proof: original upload hash equals a registered official query-response hash; layer id agrees with endpoint; response has unique declared OIDs, expected fields, point geometry/CRS, finite count below limit or explicit untruncated flag. Count responses with the same layer and row filter must agree if available. Their receipt timestamps are saved; neither count nor end-of-page marker proves a transactional whole-source snapshot. Different receipt bytes are never refetched to force a match by this verifier.

ArcGIS Date values are epoch milliseconds returned in UTC. Query date bounds apply in the official field timezone; explicit IANA or UTC metadata is required. Observed date bounds are recorded separately from requested bounds. Contract coverage/update cannot exceed the query interval. Only incremental publication is supported for bounded responses; no deletion authority. Existing independent row replay and transactional membership protection remain mandatory.

A field's presence is not its business meaning. Missing injury/death counts stay unknown. Unknown classification is retained. This rule does not support polygon/line geometry or authorize new adapter execution operations. Historical local files whose hash has no matching official receipt remain unbound.

Checks expose explicit pass/fail/not_checked. Partial passes resolve only matching gate/resource/claim/field under the same policy and source scope. New supporting evidence can earn finite progress only through an executed host check; changed URLs or downloaded document hashes alone do not.

## 2026-10-02：OID 与属性/几何边界

共用 `arcgis_query.object_id_field`（有界准入和现有完整导出均使用）：官方 `fields` 必须有唯一 `esriFieldTypeOID`，原始名称及大小写保持不变。存在 `objectIdField` / `objectIdFieldName` 时必须与该字段严格一致。FeatureServer layer 要求顶层 `objectIdField`；MapServer layer 可使用唯一类型声明作为缺失顶层声明的依据。空声明、矛盾类型/大小写、重复字段、多个/无 OID、哈希 OID 明确拒绝。响应自身的 OID 声明也与层声明核对。没有按字段名、州或域名猜测。

依据官方 [FeatureServer layer](https://developers.arcgis.com/rest/services-reference/enterprise/layer-feature-service/) 和 [MapServer layer/table](https://developers.arcgis.com/rest/services-reference/enterprise/layer-table/) 的不同元数据形式（2026-10-02核查）。MapServer 示例仅在 fields 中给出 OID 类型。该选择是有界支持规则，并非宣称接受一切历史服务格式。

`esriFieldTypeGeometry` 是几何成员，由已有 geometry/CRS 验证处理；`outFields=*` 的普通属性完整性不要求它再次出现在 properties/attributes。按协议类型判断，不依赖 `geom` / `Shape` 等名字。普通字段缺失仍拒绝。官方 [query geometry/attributes](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/) 分开返回；没有放宽几何/CRS 或上传响应哈希绑定。

WA气象站已参与修复，定位为跨来源协议回归；不再是冻结后盲测，不代表道路事故全业务接入。
