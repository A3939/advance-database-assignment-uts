# 2026-10-08 本地项目合并

当前使用 Workspace/ARSIA 与 http://127.0.0.1:3100。此次接入 3133 中已经验收的界面、Studio 文档/探索/资源/Findings 与相关 AI 服务端实现。Data 保留资料库与 Imports 入口；顶栏是 Overview / Analytics / Studio / Data。

Studio 支持 Explore / Document / Findings 切换、固定对话输入、资源保存到文档、可编辑文档块、搜索研究，以及每条记录的重命名、归档/恢复和确认删除。图表按可用宽度显示，长图可在内部滚动。

数据合并保留 ARSIA 的 46 条历史研究及当前 3133 的 10 条研究，共 56 条；旧存储 schema 0 先在副本经已有维护工具升级为 schema 1，逐项核对旧内容仅增加 schema 标记，再合入新记录。历史版本、附件和请求关联一起保留。不存在直接用 10 条新研究覆盖旧数据库的操作。

本次范围为 Web / Studio 合并；现有 Python 导入 pipeline、业务数据库、release 和原始文件保留原状。未执行导入、恢复历史任务或付费模型验收。模型代码的合并不代表重新完成真实 Agent 验收。

构建和运行仍使用 npm run build / npm run start，绑定 3100。PDF 渲染使用本机已安装的受控 Chromium，执行路径通过 ARSIA_REPORT_CHROMIUM_EXECUTABLE 配置；现有模型 key 保留。

准确补丁、逐文件清单、测试记录、SQLite 备份、服务切换与回退记录位于同级 ARSIA-Studio-Project-Merge-20261008/evidence。该目录保留合并前未提交文件内容和旧数据库；回退前必须再备份用户此后新增的研究内容。
