# 独立仓库迁移

原目录：`Workspace/Workspace_Github/frontend`。新目录：`Workspace/ARSIA`，前端文件直接位于此 Git 仓库根目录。

已完整移动源代码、文档、锁文件、数据快照、地图、测试、沙箱、环境文件、现有依赖、构建输出和本地分析产物。移动保留文件内容及环境配置，没有执行快照重建，也没有复制原数据库仓库的 Git 历史。

本地 Git 分支为 `main`，仓库为 `https://github.com/yyyZYH/ARSIA`。迁移时没有提交或推送；后续按用户要求准备同步时，使用本机已有 SSH 认证，将 `origin` 改为 `git@github.com:yyyZYH/ARSIA.git`，并读取了远端 `main`。当前前端接续远端已有静态原型的历史，使用 Next.js 入口取代旧版根目录静态入口及其部署配置，不强制推送或改写已有提交。远端 README 提及自动部署，实际推送需与用户“不部署”的约束协调。

## 运行兼容

旧位置保留相对符号链接 `Workspace_Github/frontend -> ../ARSIA`，用于兼容仍在运行的 3100–3103 预览及旧窗口路径；代码只有新目录这一份。未停止任何已有预览进程。今后请在新目录开发，旧链接不属于新仓库，不应提交到原数据库仓库。

```sh
cd "/Users/zhengpeixian/ZPX/UTS/Advanced Database/Assignment 2/Workspace/ARSIA"
npm run dev -- --port 3104
```

已有快照、地理边界可直接运行。AI 使用原有 `.env.local`；Python 分析仍需 Docker Desktop 及已建立的 `arsia-analysis:1` 镜像。`.env*`、node_modules、各构建目录、测试输出及分析文件继续被 Git 忽略。

## 可选的数据快照重建

正常运行无需原始数据目录或验收产物。只有手动重建快照时才读取外部项目文件：

- `scripts/import-official-snapshot.mjs` 从脚本位置定位工作区 `../artifacts/`；仍可通过两个命令行参数指定正式导出目录与证据索引。输出固定为本仓库 `data/official/`。
- `scripts/build-region-snapshot.py` 默认只读 `../Workspace_Github/raw_datasource/`；迁移到其他机器时可使用 `ARSIA_RAW_DATA_DIR=/path/to/raw_datasource` 指定原始文件位置。

上述脚本未在本次迁移中执行。正式流水线、数据库和原始数据未移动或修改。
