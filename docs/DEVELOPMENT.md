# Open WebUI fork 开发入口

## 当前状态

2026-11-21，维护者决定把此 fork 同步到官方 `open-webui/open-webui:main`，接入新版 Dissipative 连续记忆。此次切换仅保留用户登录所需信息，允许重新登录，旧聊天和派生记忆从空库开始，故障时向前修复。所有升级均须保留自定义图标与实例主题。[仓库规则](../AGENTS.md#所有升级和更新均须保留自定义图标与主题) · [本次计划](development/open-webui-upgrade-2026-11.md)

本分支最近发布的产品源码为 `5a3026ed4`（Open WebUI 0.11.4 / Adapter 4.20）。隔离候选从本分支 `3ae22bd84` 开工，在 `31b109a08` 合并了冻结的官方主线 `0666e59d26a4d056e0bacee41742486badd71cf8`。0.13.4 / Adapter 4.21 的 wheel、图标、浏览器主题、重启与仅登录的合成演练已验证。候选的执行进度由该分支的开发入口维护。[候选开发入口](https://github.com/harrywenjie/open-webui/blob/codex/dissipative-upgrade-20261121/docs/DEVELOPMENT.md) · [验证记录](https://github.com/harrywenjie/open-webui/blob/codex/dissipative-upgrade-20261121/downstream/upgrade-20261121.md)

## 下一任务卡

| 工作包 | 必读输入 | 交付与通过条件 |
| --- | --- | --- |
| 连续记忆与下游组合验收 | [候选任务卡](https://github.com/harrywenjie/open-webui/blob/codex/dissipative-upgrade-20261121/docs/DEVELOPMENT.md#下一任务卡)、[新版记忆接入](development/open-webui-upgrade-2026-11.md#新版记忆接入) | 在隔离候选接入专用 Core，通过真实客户端、重启和实际模型组合验证 |
| Mac 切换 | [演练及窗口](development/open-webui-upgrade-2026-11.md#候选资格与-mac-窗口) | 完整演练通过并获得独立窗口授权后，核对现场并按向前修复方案切换 |

连续记忆采用 WebUI 自有实例和独立推理配置。WorldHatch 继续使用原有独立实例。

## 下游已有行为

普通聊天使用 WebUI 自己的模型连接，Core 负责独立推理配置。fork 提供认证的来源同步、管理、HUD 和发布。HUD 按当前聊天及分支分别展示 Archive 与 Curator 的处理覆盖，旧 Core 缺少新字段时沿用原显示。Adapter 4.20 的 FAST 回答、取消及发布共享服务端签发的尝试身份，推理和发布前再次核对聊天所有权。这些行为均纳入升级回归。[下游基线原文](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md)

仅处理文档归属、历史入口或下一次主题切换时，按全局 AGENTS.md 的文档分层规则及 `doc-governance` 阅读[本次维护记录](maintenance/upgrade-document-ownership-20261121.md)。
