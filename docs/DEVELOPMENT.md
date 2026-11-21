# Open WebUI fork 开发入口

## 当前状态

2026-11-21，维护者决定把此 fork 同步到官方 `open-webui/open-webui:main`，接入新版 Dissipative 连续记忆。此次切换仅保留用户登录所需信息，允许重新登录，旧聊天和派生记忆从空库开始，故障时向前修复。所有升级均须保留自定义图标与实例主题。[仓库规则](../AGENTS.md#所有升级和更新均须保留自定义图标与主题) · [本次计划](development/open-webui-upgrade-2026-11.md)

Open WebUI 0.13.4 / Adapter 4.22 候选的产品提交为 `106e98dd4`，上游冻结点为 `0666e59d2`。从该提交构建的 wheel 已安装到隔离环境，与 WebUI 专用的 schema 34 空 Core 完成真实 Qwen、浏览器及重启联调。Dissipative 候选 `acb4be0` 保存并核对了 26 个导出文件。最近记录的生产基线为 WebUI 0.11.4 / Adapter 4.20。[组合实测](../downstream/upgrade-20261121.md#schema-34-客户端) · [候选证据](evidence/open-webui-0.13.4-schema34.json) · [导出清单](https://github.com/harrywenjie/dissipative/blob/acb4be0a5db015747697974f539dc62a8f9837c6/adapters/open-webui/adapter_manifest.json)

## 下一任务卡

| 工作包 | 必读输入 | 交付与通过条件 |
| --- | --- | --- |
| Mac 切换，等待单独授权 | [登录迁移边界](development/open-webui-upgrade-2026-11.md#登录信息最小迁移) · [窗口与验收](development/open-webui-upgrade-2026-11.md#候选资格与-mac-窗口) | 取得窗口授权后核实现场基线，按白名单迁入登录信息，恢复 Data Rift 与 Harry's Ops Deck，从空库启动 WebUI 专用 Core，现场复验并按向前修复方案处理故障 |

WorldHatch 使用其原有独立实例。仅在重新打包或更换模型、插件及主题时，复跑受影响的[候选验收](../downstream/upgrade-20261121.md#schema-34-客户端)。

## 下游已有行为

普通聊天使用 WebUI 自己的模型连接，Core 负责独立推理配置。fork 提供认证的来源同步、管理、HUD 和发布。HUD 按当前聊天及分支分别展示 Archive 与 Curator 的处理覆盖，旧 Core 缺少新字段时沿用原显示。Adapter 4.20 的 FAST 回答、取消及发布共享服务端签发的尝试身份，推理和发布前再次核对聊天所有权。这些行为均纳入升级回归。[下游基线原文](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md)

仅处理文档归属、历史入口或下一次主题切换时，按全局 AGENTS.md 的文档分层规则及 `doc-governance` 阅读[本次维护记录](maintenance/upgrade-document-ownership-20261121.md)。
