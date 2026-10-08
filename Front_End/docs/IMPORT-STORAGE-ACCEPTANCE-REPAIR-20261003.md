# ARSIA 存储验收工具修复与补验收执行书

日期：2026-10-03（Australia/Sydney）  
项目：`/Users/zhengpeixian/ZPX/UTS/Advanced Database/Assignment 2/Workspace/ARSIA`  
状态：待执行。本文只交付修复说明，没有启动开发、测试或恢复旧环境。

## 1. 任务范围与最终目标

本轮只做 **验收工具修复、轻量预检、上一轮三个存储模块的真实隔离验收**。不要扩展数据导入业务，不重写存储架构，不调整 AI adapter 或质量门禁。

直接执行要求：

> 阅读本文和上轮报告，先修复公开/内部上传收据混用、硬中断证据延迟落盘、上传阶段锁断言错误，巩固子进程解释器与工作目录。先运行不创建数据库的工具预检；通过后冻结源码，运行一次限时隔离验收，完成真实恢复回收、跨轮保留、上传提交前后硬中断和正常导入回归。发现生产实现缺陷时保存证据并停止该依赖链，不在本轮扩展生产修复。完成或达到限制后停止自有资源并暂停。

这份文档优先于上一份任务书中“所有阶段合计只允许一次修正”的调度约束；新的阶段、修正与时间限制见第 10 节。原有数据保护、QA、零数据模型调用和禁止部署要求继续有效。

本轮成功的条件是上一份 H01–H16 的必要子项获得当前代码的实测证据；不是只修掉 `KeyError`，也不是重跑 162 个单元测试即可完成。不能完成的项目必须准确标记。

## 2. 必须先阅读与核对的文件

- `docs/IMPORT-STORAGE-HARDENING-IMPLEMENTATION-20261002.md`：H01–H16 定义与资源边界。
- `artifacts/storage-hardening-20261002T123718Z/REPORT.md`
- 同目录 `checkpoint.json`、`VERIFICATION.json`、`SOURCE-final.json`。
- 同目录 `integration.txt`、`integration-repair-1.txt`、`REPAIR-1.json`。
- `pipeline/tools/verify_storage_hardening.py`
- `pipeline/tools/storage_hardening_child.py`
- `pipeline/tools/verify_storage_isolated.py`
- `pipeline/arsia_pipeline/api.py`、`store.py`、`input_store.py`、`upload_gc.py`。
- `storage_restore.py`、`storage_catalog.py`、`test_session.py`：只读理解真实行为。

编写本文时，上轮 `SOURCE-final.json.source_hashes` 中 221 个文件与当前字节一致。执行者必须重新核对；若主线程已有新改动，先识别实际差异，不覆盖或回退。

## 3. 已定位问题：原因、修改位置和禁止的修法

| 编号 | 定位 | 根因及要求 |
|---|---|---|
| R1 | `verify_storage_hardening.py` 中 `response.json()['files'][0]` 随后传入 `input_store.resolve` | 公共响应经过 `store.clean_job()` 删除 `path`；内部 resolver 必须收到可信数据库收据。修测试取证，不修公开 API |
| R2 | `child()` 启动解释器与相对路径 | `.resolve()` 跟随虚拟环境解释器符号链接曾导致依赖丢失；现已改为 `.absolute()`，仍依赖 cwd。统一使用经过预检的解释器和明确项目根 |
| R3 | 上传循环中三个 phase 共用“GC 必须无法获得上传锁”断言 | `upload_sql_committed` hook 位于事务退出之后，此时事务锁已释放；锁预期必须按阶段区分 |
| R4 | `hard.append(...)`、循环结束后才写 `upload-hard-kills.json` | 后续断言失败会丢掉已经执行的 PID/exitcode 证明。每个关键动作完成后立即原子落盘 |
| R5 | `step()` 先标 pass、外部随后才做语义断言；部分结果含 TestSession 对象 | 步骤执行完不等于验收通过。把必要断言放入步骤函数，保存明确的 JSON 结果，不能依赖 default=str 序列化运行对象 |

R1/R2 是上轮真实阻塞。R3 是本次静态检查发现、尚未执行到的确定性测试预期错误。R4/R5 是验收记录与结论可靠性缺口。不要把它们描述成已观察到的生产数据损坏。

允许修改的主体：两个 hardening 工具、必要的工具专用 helper，以及对应测试。`verify_storage_isolated.py` 只有确实需要传递已验证参数或改善工具返回值时才作最小修改。

本轮不修改 `api.py`、`store.py`、`input_store.py`、`upload_gc.py`、`storage_restore.py`、`storage_catalog.py` 等生产实现来迎合测试。若真实测试暴露其错误，记录具体代码和复现路径，保留现场，作为下一轮生产修复。

## 4. R1：正确取得内部上传收据

### 4.1 精确修改方式

在验收工具内新增 `load_internal_receipt(session, job_id, public_receipt)`，或放入可独立测试的工具 helper。优先使用显式 `store.connect(session.cfg)` 查询，避免 `store.get_job(..., internal=True)` 隐含读取当前全局配置：脚本会切换多个测试 session。

推荐实现骨架如下，执行者可以调整错误类型和风格，但不得减少身份验证：

```python
def load_internal_receipt(session, job_id, public_receipt):
    from uuid import UUID
    from arsia_pipeline import store

    wanted_job = UUID(str(job_id))
    if 'path' in public_receipt:
        raise AssertionError('Public upload receipt exposed host path')

    # connect(cfg) retains existing database-name and local_instance checks.
    with store.connect(session.cfg) as conn, conn.transaction():
        conn.execute('SET TRANSACTION READ ONLY')
        row = conn.execute(
            'SELECT id, files FROM jobs WHERE id=%s', (wanted_job,)
        ).fetchone()
    if row is None or str(row['id']) != str(wanted_job):
        raise AssertionError('Uploaded job missing from this test instance')

    matches = [f for f in row['files'] if f.get('id') == public_receipt['id']]
    if len(matches) != 1:
        raise AssertionError('Expected exactly one persisted upload receipt')
    receipt = matches[0]
    for key in ('id', 'name', 'format', 'size', 'sha256'):
        if receipt.get(key) != public_receipt.get(key):
            raise AssertionError(f'Upload receipt mismatch: {key}')
    if not receipt.get('path'):
        raise AssertionError('Internal receipt has no stored path')
    if receipt.get('storage_version'):
        if (receipt.get('instance_id') != session.cfg['instance_id']
                or str(receipt.get('job_id')) != str(wanted_job)):
            raise AssertionError('CAS receipt belongs to another instance/job')
    return receipt
```

之后用 `input_store.resolve(session.cfg, receipt)` 完成既有路径、宿主收据、大小、SHA 校验；不得自行拼接 `blobs/sha256/...` 来替代这一步。

### 4.2 调用点

把现有成功上传那一行拆开：

1. `response.raise_for_status()`。
2. 保存 `public_receipt`，断言所有公开 `files` 元素均无 `path`。
3. 按本次上传的 file ID 取得唯一内部收据，不依赖列表最后一个元素。
4. 确认 `resolve(...).read_bytes()` 与本次合成输入相同。
5. 再执行测试需要的 cancel；取消后仍须按原引用保护要求保留该已提交输入。

SQL 提交窗口中的 `row['files']` 已来自显式配置的内部查询，可用其对应 file ID 收据；仍验证 job/instance，不能混入另一 session 的同名文件。

私有收据留在受信任进程内。不把完整 `path`、DSN 或凭据加回公共 HTTP 响应；公开接口“不包含宿主路径”的断言作为回归保留。不要修改 `store.clean_job()`，也不要让 resolver 从缺字段的收据猜测路径。

## 5. R2：解释器、工作目录和子进程轻量探测

### 5.1 固定路径基准

工具启动时计算：

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = PROJECT_ROOT / 'pipeline'
CHILD_SCRIPT = PIPELINE_ROOT / 'tools' / 'storage_hardening_child.py'
CHILD_PYTHON = Path(os.path.abspath(sys.executable))  # 不调用 resolve()
```

这里源码文件的 `.resolve()` 可以使用，**虚拟环境解释器的符号链接不能这样处理**。父工具应通过 `pipeline/.venv/bin/python` 启动，并预检其 `sys.prefix` 对应项目现有虚拟环境；不通过自动安装包修复环境。

所有子进程显式 `cwd=PROJECT_ROOT`、`PYTHONPATH=PIPELINE_ROOT`、`PYTHONDONTWRITEBYTECODE=1`。输入、recipe、output 和 config 在入口规范化为绝对路径；子进程不靠调用者 cwd 猜位置。环境继承仅用于正常运行，不把整份环境变量打印到日志。

### 5.2 无数据库 probe 模式

给 child 增加明确的 `probe` action，或同等轻量探测入口：

- 验证 interpreter/prefix、必要包 `fastapi`、`httpx`、`psycopg` 和项目模块能导入。
- 写出简短 JSON：Python 版本、虚拟环境前缀、必要包版本、脚本/项目根身份、probe=pass。
- 不调用 `TestSession(cfg)`、`configure()`、数据库连接、Docker create 或 API 上传。
- 因当前 child 在参数解析后立即构造 TestSession，需要把这段放入非 probe 分支；加 `main()`/`if __name__ == '__main__'`，避免导入测试时启动行为。
- probe 不需要 `--config`；其他 action 仍必须提供并验证私有配置，不能将其变成可选的默认网站配置。

用同一个解释器和启动 helper，从项目根和一个不同 cwd 各启动 probe。两次必须指向同一项目、同一虚拟环境。不能用 mock 成功替代实际启动这两个轻量子进程。

## 6. R3：按事务阶段重写锁与引用断言

代码事实：`api.upload()` 中 `upload_partial`、`upload_pending_commit` 位于 SQL 事务内；`upload_sql_committed` 位于事务上下文退出后、`input_store.committed()` 之前。

| phase | barrier 时 SQL 状态 | 允许的检查 | SIGKILL 后必须验证 |
|---|---|---|---|
| upload_partial | 事务未提交，上传锁仍持有 | GC 应因锁忙拒绝；独立连接尚看不到新 files | files 为空；活动 job 保护；取消本测试 job、过宽限后 partial 回收 |
| upload_pending_commit | blob/宿主 receipt 已发布，SQL 未提交，锁仍持有 | GC 应因锁忙拒绝；新 files 未提交 | files 为空；本次未提交 receipt 可清理；另一成功上传共享 blob 保留 |
| upload_sql_committed | SQL 已提交，上传事务锁已经释放，宿主确认日志尚未写入 | 只读查 SQL 与 ledger，确认已提交收据存在而 operation 尚非 committed；不要求锁忙 | SQL 收据仍在；新进程对账补齐 committed；原字节和共享引用不变 |

### 6.1 提交后窗口的关键次序

**在第三个窗口 kill 之前不要执行会补齐状态的 apply GC**，否则测试会提前修复丢失确认，失去“确认尚未写入便崩溃”的意义。

正确流程：

1. 等到对应 barrier；核对 instance、job、phase 与 child 身份。
2. 独立 SQL 只读查询确认该 job 的 file ID 已持久化；只读 ledger 确认同一 upload operation 仍是 pending_commit（按实际版本合法前态判断）。
3. 将上述前态证明落盘，再对父进程创建且仍存活的那个 child 发 SIGKILL。
4. 等待 `returncode == -signal.SIGKILL`，立即保存进程证明。
5. 重新读取 SQL/ledger，确认还处于“SQL 存在、确认未补”的状态。
6. 由**全新子进程**运行 reconcile。其结果须包含对该 operation 的 committed 判定，且 ledger 已转 committed、文件完整、无删除动作。
7. 对账再运行一次应幂等；不重新上传、不重新导入、不发布新 release。

若随后为了结束测试取消这个上传 job，取消前后的已提交 files 都应受引用保护。不要通过取消来伪造事务回滚，也不要删掉 job 才让 GC 通过。

其余两个窗口继续真实证明锁忙，不用统一删掉全部锁断言。三种窗口各自保存预期和实测状态。

## 7. R4/R5：即时证据与可信步骤状态

### 7.1 child 证据与业务验收结果分开

为每个 child 增加独立持久进程收据，例如 `child-<id>.process.json`。按下列顺序原子更新：

`spawn_intent -> spawned -> barrier_reached -> signal_sent/continue_sent -> exited`

至少记录 child ID、PID（创建后）、action、预期/实际 phase、instance/session、job/operation、开始/结束时间、信号、returncode、log/barrier/result 的相对路径与必要哈希。不得保存 DSN/密码。

- `Popen` 成功后立刻记 PID；到达 barrier 立刻记录。
- child barrier 内容增加 child ID、PID、session、job/operation 等校验字段；父进程不只检查“文件存在”。
- `wait()` 返回后先保存实际 exitcode，再断言是否预期的 SIGKILL。
- parent 只有在自己创建的 `Popen` 仍存活且身份匹配时才发信号；不按名称扫描进程，不复用历史 PID。
- 意外正常退出也要保存证据，不能随后补一次 kill 伪装硬中断。
- 新进程 GC 的结果在后续文件断言之前落盘。

每个上传窗口在完成后立即更新 `upload-hard-kills.json`，不要等循环结束。进程确实被 kill 与业务恢复是否通过是两层结论，前者通过不能直接推导后者通过。

所有证据写入使用现有 `atomic_json` 或等效 flush/fsync/replace 语义。证据落盘失败时不继续执行新的破坏动作；记录可记录的信息并停止。

### 7.2 step 状态机

建议把 step 封装改为：开始写 `running`；执行动作和所有断言；保存结构化证据；然后才写 `pass`。失败则记录 `fail/blocked`、异常类型、证据及耗时并退出该依赖链。

不可在 `published.restore_database()` 返回后立即写 H01/H14 pass，再到 step 外检查容器是否消失、记录是否一致。将这些断言移入该步骤函数。

H13 的 `workload()` 返回 `(TestSession, result)`；将 TestSession 留在内存中的显式变量/返回容器，step 记录只保存 result。不要先把 live object 字符串化写入 `steps.json` 再覆盖。

最终成功判定必须基于必要场景结果，并发生在收尾审计之后。若正文通过但 finally 中发现自有进程无法安全停止，不能留下无条件的总 `status=pass`。

### 7.3 超时统一

所有 child barrier 等待、`wait()` 与场景调用受同一个全局 deadline 约束，使用 `min(局部上限, 剩余时间)`，剩余时间非正时不得新建 child。

`finally` 有单独且有限的安全停止余量；记录额外收尾时间，不把它隐藏到集成耗时之外。先 terminate/wait 自有 child，必要时针对同一 child 强制结束；数据库使用已有归属核验和正常 stop，不能把数据库强杀当作常规超时处理。

## 8. 预检：先发现工具错误，再花时间创建数据库

增加工具专用测试（如 `pipeline/tests/test_storage_hardening_harness.py`），不要新建生产管理框架。以下检查都应在正式集成之前完成：

| ID | 检查 | 通过条件 |
|---|---|---|
| P01 | 解释器/依赖/cwd probe | 两种 cwd 的真实轻量子进程使用同一虚拟环境，无 Docker/DB 创建 |
| P02 | 公共/内部收据契约 | 公共无 path；显式 cfg 内部查询成功；错 file ID、重复 ID、错 job/instance、SHA/format 不同均拒绝 |
| P03 | 阶段预期表 | 提交前执行锁忙检查；提交后不执行 kill 前 apply GC，不要求上传锁仍在 |
| P04 | 证据持久性 | 模拟某个后续断言失败时，先前 spawn/barrier/exitcode/GC 结果仍在；意外退出不标成 SIGKILL 通过 |
| P05 | 步骤结论 | 动作返回但语义断言失败时，steps 中该项为 fail，不能先记 pass；JSON 无 TestSession 对象字符串 |
| P06 | 截止时间 | 过期 deadline 不创建测试空间/child；失败修正不重置原截止时间 |
| P07 | 固定材料与镜像 | 只读验证源 SHA、recipe 所引用的本地 documents、oracle、现有镜像 ID；缺失则 blocked，不下载 |
| P08 | 工具收尾 | 失败路径保存准确资源状态；未知容器/检查错误不当作不存在；只处理本轮明确创建对象 |

P02–P06 可以使用可控连接/transport 和临时文件测试；不能把这些 mock 结果写成 H01/H14 或真实 SQL/SIGKILL 通过。P01 必须实际起轻量 Python 子进程。

本轮执行的目标是修复并验证这些具体错误。不要只把上一轮 failed 行换成 `try/except KeyError: pass`，不要降低断言或将未执行的项目跳过后计入通过数。

## 9. 正式补验收的依赖顺序

新建 `artifacts/storage-acceptance-repair-<UTC timestamp>/`，所有新的 session 从创建起登记到本轮显式测试空间。旧四个测试环境与 checkpoint 保持只读，不恢复旧 job、不自动接管。

建议调整现有大循环的顺序，避免一个上传断言再次挡住全部恢复验收：

### A. 正常导入和独立核对

运行保存的 TAS 固定材料三次：首次成功、同字节原名重传、同字节改名重传。每次保留样本/全量独立 QA、注册、发布、查询与模型调用记录；batch/release 不变。

把脚本尾部原始记录 oracle 提前到此处。它属于开发方只读后验核对，不交给数据 Agent。记录 632 条只作为这份固定 fixture 的预期，不能进入产品过滤/放行逻辑。

### B. 跨轮保留

在三个不同 run 目录建立同一保留 family/suite 的成功 session：A 的已发布库，加两份小型合成测试库。不要把复杂上传崩溃实验当作第三组完成的前置条件。

固定 N=2，先 pin 最老环境，验证第三组完成不会覆盖 pin；再按本轮测试程序明确解除该测试 pin，运行带 barrier 的两个 finalizer，并核对最终只有最近两组数据库展开、最老数据库有校验归档。

必须直接比较实际 input_set/baseline 等兼容字段，不能只用 `len(set(catalog.compatibility)) == 3` 证明输入不同：当前 compatibility 含 instance_id，本身就会造成每组不同。身份不同与业务材料不同分别举证。

### C. 非空数据库恢复和自动回收

使用 B 自动生成的 A 库归档执行 verify_only：核对所有业务表 count/逐行 SHA、632 条 canonical_crash、current release、代表查询和归档 SHA；确认新恢复容器、卷已回收。

随后执行恢复已验证和容器已删除两个真实 SIGKILL 窗口，新进程连续对账两次，应安全收敛；人工恢复、pin、验证前中断按策略保留。清理错误注入后，验证成功证据和导入结果保持不变。

不要通过测试脚本直接 `docker rm` 替代待验收的自动回收方法。失败/保留的恢复环境记录归属和原因，结束时只停止，不为“零残留”删除唯一诊断。

### D. 上传中断、孤儿、保护和预算

使用独立的合成故障 suite/session，不让它的失败状态改变 B 的成功保留分组。依第 6 节执行三个真实 SQL 阶段，再覆盖唯一 orphan、共享 blob、宽限期、checkpoint/needs_input、symlink、未知 staging、数据库不可用等。

H08 的小预算和峰值检查使用本轮新 space；同时记录 SIGKILL 后 reservations/claims 是否残留。不能把“finally 会 release”当成硬中断已收敛的证明；若发现生产预算预留泄漏，保留具体 operation 和状态，标记缺陷，不偷偷清空 catalog 让数字归零。

独立场景可按预先声明的依赖继续，前提是隔离和安全收尾已经确认；涉及资源归属/误删或无法停止自有进程时整批停止。下游依赖失败应写 blocked，不伪造其预置状态继续。

### E. 统一结论

沿用 H01–H16，逐项绑定本轮证据；P01–P08 与原 162 项测试单列，不把测试数量相加冒充真实端到端覆盖。

需要当前存储、上传、QA、publication identity/scoped orphan 的定向回归。上轮三项来源证据业务 fixture 失败仍独立列出，不扩展修复。H13 是固定材料/已验证 adapter 回归，不是未知州自主接入。

## 10. 时间、修正和范围限制

本轮采用如下明确的新限制，替代旧的一次修正覆盖全部阶段的方式：

1. **总墙钟上限 90 分钟**，其中工具修复和轻量预检目标不超过 45 分钟。
2. 预检期间可以修复本文 R1–R5 及其直接工具问题，在时间内迭代；不启动整批真实导入，不修改生产模块。
3. P01–P08 通过后保存 `FROZEN.json`，**启动唯一一批最长 30 分钟的真实验收窗口**。
4. 正式窗口内最多允许两次明确记录的工具局部修正，不能重置 deadline。重跑受影响场景；共享 helper 变化使哪些既有证据失效，要明确列出并重测，不拼接为“当前源码全通过”。
5. 不为工具修正每次从头再跑全部场景。已完成且未受影响的场景记录其工具/生产哈希；最终报告允许逐场景哈希，不能伪称都来自同一次完整运行。
6. 正式集成中发现生产实现缺陷，本轮不修生产代码；保存最小复现、输入、期望/实际状态和资源清单，依第 9 节决定独立场景是否继续。必要核心场景失败则整轮为部分完成。
7. 到总时限或集成截止停止新增操作，安全收尾、保存报告并暂停。预留报告时间，不在最后一分钟新建重环境。

限额约束开发及数据工作，不妨碍必要的有限安全停止。超过截止的收尾时间必须单独报告。不得启动新的周期自动化或无限等待模型/网络。

## 11. 运行材料和命令入口

从上轮记录核实以下本地材料仍存在且 SHA 匹配：

- 输入：`artifacts/tas-isolated-20261002-0458/downloads/TAS_Crashes_2024_01.geojson`
- recipe：`artifacts/closeout-20261002/real-import/recipes/cf7570d4f654b9b802765b6f03aaf19e9f1928519eac5bb42aa5d26bd01803a8/objects/12496d636c1c32a0b8a8769e0a126e3c1f52a700a420f328d9245b5432f69fad`
- oracle：`artifacts/closeout-20261002/tas_oracle.py`
- 解释器：`pipeline/.venv/bin/python`
- 镜像：由上轮配置记录的 PostgreSQL/executor 镜像核对本机 ID；只用本地现有镜像，不 pull/build。

现有正式工具入口仍为：

```text
PYTHONPATH=pipeline pipeline/.venv/bin/python pipeline/tools/verify_storage_hardening.py
  --output <本轮全新绝对目录>
  --deadline <本轮冻结时确定的UTC截止时间>
  --source <已核实的输入绝对路径>
  --recipe <已核实的recipe绝对路径>
```

以上是参数说明，不能原样执行占位符。实际调用应由受信任 launcher 用参数列表构造，或正确引用含空格的路径；deadline 不复用上轮已经过期的值。预检入口新增后在报告中给出真实命令。

## 12. 原环境保护、交付与暂停

本轮数据模型调用应为 0，禁止模型和新来源下载的回退。保留运行审计；开发 Codex 推理用量与数据 Agent 区分。

不得改正常网站绑定、配置、端口、旧数据库；不得启动旧四个测试环境、删除旧诊断/归档或执行全局 Docker 清理。仅使用新受管测试资源。新环境最多两个正常数据库同时运行、一个重型执行/备份/恢复操作；成功 disposable 副本按被测规则回收，失败现场保留原因。

开始与结束核对受保护文件、原容器/卷和生产模块哈希；主库无法只读连接时标 `not_verified`，不修连接，也不以哈希代替数据库全表比对。

交付到本轮唯一目录：

- `HARNESS-REPAIR.md`：R1–R5 修改位置、原因、代码差异、旧问题复现与新预检结果。
- `PREFLIGHT.json`：P01–P08，解释器/依赖/材料校验与工具错误证据。
- `FROZEN.json`、`SOURCE-before.json`、`SOURCE-final.json`、每次局部修正记录。
- `VERIFICATION.json`：H01–H16，每项 pass/fail/blocked/not_run、证据、源码/工具哈希与限制。
- `children/` 或等价目录：每个子进程完整状态、barrier、signal、exitcode、日志和后续对账。
- `REPORT.md`：三个存储目标是否实际完成，逐阶段耗时、模型调用、占用变化和剩余阻塞。
- `checkpoint.json`：paused、精确自有资源、未完成操作、pin、恢复入口与下一步最小动作。

若未通过，错误报告必须指出“验收工具错误 / 生产实现缺陷 / 环境依赖 / 未执行”中的具体类别，不能统称卡住。保存有效证据，停止本轮自有进程，不提交、不推送、不部署，不自动进入下一轮。

**本文没有授权当前侧聊直接修生产代码或运行验收；用户将此文档交给开发 Codex 执行时，按上述范围开展。**
