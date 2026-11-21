# Open WebUI fork 开发入口

## 当前状态

2026-11-21，维护者决定把此 fork 同步到官方 `open-webui/open-webui:main`，接入新版 Dissipative 连续记忆。此次切换仅保留用户登录所需信息，允许重新登录，旧聊天和派生记忆从空库开始，故障时向前修复。所有升级均须保留自定义图标与实例主题。[仓库规则](../AGENTS.md#所有升级和更新均须保留自定义图标与主题) · [本次计划](development/open-webui-upgrade-2026-11.md)

从已发布 fork `3ae22bd84` 建立的候选在 `31b109a08` 合并了开工时冻结的官方主线 `0666e59d26a4d056e0bacee41742486badd71cf8`。Open WebUI 0.13.4 / Adapter 4.21 的 wheel 已在隔离环境安装。Data Rift 图标、Harry's Ops Deck 的浏览器外观与重启、仅登录迁移均有合成演练证据。Dissipative 的 24 个导出文件来自该合并提交。已发布产品基线为 0.11.4 / Adapter 4.20。[候选与验证记录](../downstream/upgrade-20261121.md) · [下游清单](../downstream/adapter.json)

## 下一任务卡

| 工作包 | 必读输入 | 交付与通过条件 |
| --- | --- | --- |
| 新版连续记忆客户端 | [协议及独立 Core 配置](development/open-webui-upgrade-2026-11.md#新版记忆接入) | 在 WebUI 专用空 Core 上完成能力协商、可信来源事件、每轮归档、显式整理、Profile 选择、召回与撤权；按当前合同验证隔离、重试和重启 |
| 下游正常入口与组合演练 | [上游同步第 3 项](development/open-webui-upgrade-2026-11.md#上游同步)、[演练及窗口](development/open-webui-upgrade-2026-11.md#候选资格与-mac-窗口) | 普通流式聊天、隔离与重启回读已通过回环模型。接入专用 Core 后验证 Continue、再生成、编辑、分支、删除、FAST、插件挂载、重启回读新记忆与已选 Profile，完成获准的模型调用 |
| Mac 切换 | [登录迁移边界](development/open-webui-upgrade-2026-11.md#登录信息最小迁移)、[生产窗口](development/open-webui-upgrade-2026-11.md#候选资格与-mac-窗口) | 组合演练通过后取得窗口授权，复核现场启用的登录方式和专属服务，依本次向前修复决定实施 |

现有记忆客户端仍使用旧协议路由。下一包从专用 schema 34 与独立模型配置开始，旧 managed catalog 启动参数与该模式互斥。现场 Mac 与 WorldHatch 位于此候选运行边界之外。

## 下游已有行为

普通聊天使用 WebUI 自己的模型连接，Core 负责独立推理配置。fork 提供认证的来源同步、管理、HUD 和发布。HUD 按当前聊天及分支分别展示 Archive 与 Curator 的处理覆盖，旧 Core 缺少新字段时沿用原显示。Adapter 4.20 的 FAST 回答、取消及发布共享服务端签发的尝试身份，推理和发布前再次核对聊天所有权。这些行为均纳入升级回归。[下游基线原文](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md)

仅处理文档归属、历史入口或下一次主题切换时，按全局 AGENTS.md 的文档分层规则及 `doc-governance` 阅读[本次维护记录](maintenance/upgrade-document-ownership-20261121.md)。
