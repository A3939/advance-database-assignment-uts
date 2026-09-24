# D02 · Source / Month / Severity 维度阶段性交付

## 当前实现

`src/arsia_d02/dimensions.py` 从同一份冻结 manifest 生成并加载三张维度：

- `dw.dim_source`：逐批次冻结来源名称、辖区、发布标签和发布范围；
- `dw.dim_month`：按 `analysis.year_from` 至 `analysis.year_to` 生成每年完整 12 个月；
- `dw.dim_severity`：逐批次、逐来源保存完整分类定义，包括未出现类别和 `__MISSING__`。

加载采用 A02 提交 `e62e5fb14f2e70f8506461eb74c18479e7ce25d9` 中 `007_warehouse.sql` 的真实列名、主键和外键。重复调用使用 `ON CONFLICT DO NOTHING`，随后读取数据库并与 manifest 期望逐行比较；已有同键但内容不同会阻断。模块不提交、回滚、关闭连接或改变会话设置。

## B10 接口

`runner_callback(connection, context)` 可以注册为当前 D02 的 `dw` 回调。它读取：

- `context.batch_id`；
- `context.manifest.as_dict()`；
- `context.evidence`。

完成后写出 `d02-dimensions.json`。D03 完成后，团队的组合 `dw` 回调应在同一连接和事务内先调用 D02，再调用 D03。

## S0 核对结果

使用 B 的 `tests/fixtures/s0/contract.json` 和 `s0_definitions()` 实际生成：

| 对象 | 预期 |
|---|---:|
| 来源 | 3 |
| 月份 | 60 |
| 严重度定义 | 12 |

三个来源均包含 `F`、`I`、`N` 和 `__MISSING__`。月份范围为 202001–202412，不增加“未知月”；以后 D03 对仅年精度事故使用 `month_id=NULL`。

## 尚待集成

1. 把本目录代码迁入团队分支的 `dw` 组件路径，并登记到 B09 的实际 code inventory。
2. 使用 A02/A03 完整迁移和 `arsia_loader` 权限，在 PostgreSQL 16 上执行真实加载与重复调用。
3. B09 提供最终 `FrozenManifest` 后重复相同测试，保存真实数据库证据。
4. D03 完成后将维度与事故事实加载组合为一个 B10 `dw` 回调。

当前 S0 测试证明固定样例的维度生成和接口行为，不等于真实 PostgreSQL 集成已经验收。
