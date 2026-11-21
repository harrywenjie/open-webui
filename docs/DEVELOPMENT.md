# Open WebUI fork 开发入口

## 当前状态

2026-11-21，维护者决定把此 fork 同步到官方 `open-webui/open-webui:main`，接入新版 Dissipative 连续记忆。此次切换仅保留用户登录所需信息，允许重新登录，旧聊天和派生记忆从空库开始，故障时向前修复。所有升级均须保留自定义图标与实例主题。[仓库规则](../AGENTS.md#所有升级和更新均须保留自定义图标与主题) · [本次计划](development/open-webui-upgrade-2026-11.md)

最近核实的产品源码为 `codex/dissipative-online` 上的 `5a3026ed431bd2f01e3b47909a77dd871bf76c7b`，对应 Open WebUI `0.11.4` / Adapter `4.20`。11 月 21 日记录的官方主线候选为 `0666e59`（`0.13.4`），开发开工时重新冻结。计划及文档迁移已交付；上游合并、候选 wheel、主题与新记忆的组合验证、身份迁移和生产窗口均待执行。[下游清单](../downstream/adapter.json) · [上游固定提交](https://github.com/open-webui/open-webui/commit/0666e59d26a4d056e0bacee41742486badd71cf8)

## 下一任务卡

| 工作包 | 必读输入 | 交付与通过条件 |
| --- | --- | --- |
| 首个检查点：上游同步 | [同步步骤](development/open-webui-upgrade-2026-11.md#上游同步)、[外观验收](development/open-webui-upgrade-2026-11.md#图标与主题验收) | 从已发布下游分支建立隔离候选，冻结官方 SHA，保留两条祖先，审阅自动合并和冲突。逐项说明八处补丁、overlay、图标及主题的去向，以 fork 正常入口与候选构建验证 |
| 客户端接入与身份迁移 | [连续记忆接线](development/open-webui-upgrade-2026-11.md#新版记忆接入)、[登录迁移](development/open-webui-upgrade-2026-11.md#登录信息最小迁移) | 实测独立模型配置和新协议，用合成账号完成可重复的登录迁移，新库只承接登录信息，重新配置实例外观 |
| 候选资格与切换 | [演练及窗口](development/open-webui-upgrade-2026-11.md#候选资格与-mac-窗口) | wheel、浏览器、真实客户端与已授权模型实测均有证据。独立演练成功后进入获准的生产窗口，现场核实后登记实际安装 |

当前首要兼容问题是 Core 的 Continuity 模式与旧 managed catalog 启动参数互斥。开工时还需复核上游认证 schema、消息持久化回调，以及 Theme Designer Pro 的样式和脚本能否在新的页面结构上加载。历史安装或单项离线测试各按其原始范围解释。

## 下游已有行为

普通聊天使用 WebUI 自己的模型连接，Core 负责独立推理配置。fork 提供认证的来源同步、管理、HUD 和发布。HUD 按当前聊天及分支分别展示 Archive 与 Curator 的处理覆盖，旧 Core 缺少新字段时沿用原显示。Adapter 4.20 的 FAST 回答、取消及发布共享服务端签发的尝试身份，推理和发布前再次核对聊天所有权。这些行为均纳入升级回归。[下游基线原文](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md)

仅处理文档归属、历史入口或下一次主题切换时，按全局 AGENTS.md 的文档分层规则及 `doc-governance` 阅读[本次维护记录](maintenance/upgrade-document-ownership-20261121.md)。
