# Open WebUI fork 开发入口

## 当前状态

2026-11-21，维护者决定把此 fork 同步到官方 `open-webui/open-webui:main`，接入新版 Dissipative 连续记忆。此次切换仅保留用户登录所需信息，允许重新登录，旧聊天和派生记忆从空库开始，故障时向前修复。所有升级均须保留自定义图标与实例主题。[仓库规则](../AGENTS.md#所有升级和更新均须保留自定义图标与主题) · [本次计划](development/open-webui-upgrade-2026-11.md)

Open WebUI 0.13.4 / Adapter 4.22 已于 2026-11-21 在 Mac 开放，产品提交为 `106e98dd4`，上游冻结点为 `0666e59d2`，专用 schema 34 Core 来自 `acb4be0`。现场只迁入登录信息，图标、实例主题、真实 Qwen 对话、记忆召回和服务重启回读已通过。[现场验收与恢复](https://github.com/harrywenjie/PrivateOperations/blob/main/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md) · [候选实测](https://github.com/harrywenjie/open-webui/blob/e9bd4de79455b2b509a8ffc7f2eab70fad32d004/docs/evidence/open-webui-0.13.4-schema34.json)

## 下一任务卡

本次 Mac 窗口已完成，没有待执行的切换步骤。需要处理本次安装的故障时，从[向前修复与备份](https://github.com/harrywenjie/PrivateOperations/blob/main/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md#forward-repair-and-backups)进入。新的产品改动按[升级计划](development/open-webui-upgrade-2026-11.md)重新验收。

连续记忆采用 WebUI 自有实例和独立推理配置。WorldHatch 继续使用原有独立实例。

## 下游已有行为

普通聊天使用 WebUI 自己的模型连接，Core 负责独立推理配置。fork 提供认证的来源同步、管理、HUD 和发布。HUD 按当前聊天及分支分别展示 Archive 与 Curator 的处理覆盖，旧 Core 缺少新字段时沿用原显示。Adapter 4.20 的 FAST 回答、取消及发布共享服务端签发的尝试身份，推理和发布前再次核对聊天所有权。这些行为均纳入升级回归。[下游基线原文](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md)

仅处理文档归属、历史入口或下一次主题切换时，按全局 AGENTS.md 的文档分层规则及 `doc-governance` 阅读[本次维护记录](maintenance/upgrade-document-ownership-20261121.md)。
