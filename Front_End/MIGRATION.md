# 独立仓库迁移

原目录：`Workspace/Workspace_Github/frontend`。新目录：`Workspace/ARSIA`，前端文件直接位于此 Git 仓库根目录。

已完整移动源代码、文档、锁文件、数据快照、地图、测试、沙箱、环境文件、现有依赖、构建输出和本地分析产物。移动保留文件内容及环境配置，没有执行快照重建，也没有复制原数据库仓库的 Git 历史。

本地 Git 分支为 `main`，仓库为 `https://github.com/yyyZYH/ARSIA`。迁移时没有提交或推送；后续按用户要求准备同步时，使用本机已有 SSH 认证，将 `origin` 改为 `git@github.com:yyyZYH/ARSIA.git`，并读取了远端 `main`。当前前端接续远端已有静态原型的历史，使用 Next.js 入口取代旧版根目录静态入口及其部署配置，不强制推送或改写已有提交。远端 README 提及自动部署，实际推送需与用户“不部署”的约束协调。

## 运行兼容

旧位置保留相对符号链接 `Workspace_Github/frontend -> ../ARSIA`，用于兼容旧窗口路径；旧链接不属于新仓库，不应提交到原数据库仓库。2026-09-30 将 `ARSIA-dashboard-trust` 的最新提交 `3398f1f` 快进整合到此目录的 `peixian/arsia-platform`，保留全部历史。唯一开发目录为 `Workspace/ARSIA`，唯一固定本地预览为 3100；历史验证中的其他端口不再使用。

```sh
cd "/Users/zhengpeixian/ZPX/UTS/Advanced Database/Assignment 2/Workspace/ARSIA"
npm run dev
```

已有快照、地理边界可直接运行。AI 使用原目录保留的 `.env.local`；Python 分析仍需 Docker Desktop 及已建立的 `arsia-analysis:1` 镜像。`.env*`、node_modules、各构建目录、测试输出及分析文件继续被 Git 忽略。开发服务支持热更新；不为每次改动新开服务或递增端口。

旧 `ARSIA-dashboard-trust` 工作树已收起。2026-09-30 按用户只保留最新版的要求，删除 `artifacts/worktree-archive/` 旧工作树归档及 `.next-agent`、`.next-regions`、`.next-analysis` 三份旧构建目录；最新源码、数据、环境配置、依赖及当前 `.next` 保留。当前唯一预览运行于 3100。`peixian/arsia-dashboard-trust` 分支及提交历史仍保留在 Git 中。

## 可选的数据快照重建

正常运行无需原始数据目录或验收产物。只有手动重建快照时才读取外部项目文件：

- `scripts/import-official-snapshot.mjs` 从脚本位置定位工作区 `../artifacts/`；仍可通过两个命令行参数指定正式导出目录与证据索引。输出固定为本仓库 `data/official/`。
- `scripts/build-region-snapshot.py` 默认只读 `../Workspace_Github/raw_datasource/`；迁移到其他机器时可使用 `ARSIA_RAW_DATA_DIR=/path/to/raw_datasource` 指定原始文件位置。

上述脚本未在本次迁移中执行。正式流水线、数据库和原始数据未移动或修改。
