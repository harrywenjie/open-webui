# Open WebUI fork 工程导航

## 上游同步与导出

升级在隔离工作树合并冻结的上游提交。已修改的上游文件、新增的集成和品牌资源由 Adapter 清单列出。发生冲突或路径改名时，按原行为逐项移植，用可重放补丁核对产品差异。Dissipative 从已提交的 fork 再生导出，并用同一来源构建 wheel。[冻结输入](development/upstream-sync.md#冻结本轮输入) · [移植与重放](development/upstream-sync.md#合并与重新打补丁) · [Adapter 清单](../downstream/adapter.json) · [导出与构建](development/upstream-sync.md#构建与组合验收)

## 图标与主题

Data Rift 的八个发布资产和复用同名 PNG 的根 favicon 由品牌清单定位。排查替换或遗漏时，从清单追到源码、wheel、安装目录和浏览器实际请求的位置。[定制目录](../downstream/README.md) · [品牌清单](../downstream/branding/manifest.json) · [图标校验程序](../downstream/verify_branding.py)

Harry's Ops Deck 和 Theme Designer Pro 取自 PrivateOperations 的固定提交。在私有工作区导出审定字节，以 active、non-global、无模型挂载的 `theme_designer_pro` 恢复 CSS、state、sections 和 library。排查主题未加载时，核对静态加载入口、主题接口响应及聊天页实际渲染。[受保护来源清单](../downstream/repatch/protected-sources.json) · [发布字节导出方法](development/upstream-sync.md#固定产品与备份) · [加载与渲染合同](development/open-webui-upgrade-2026-11.md#图标与主题验收)

## 聊天与连续记忆

| 修改对象 | 应保留的接口与行为 |
|---|---|
| 来源、归档和 Profile | WebUI 负责聊天模型、用户权限与已落库的活动分支，Core 独立配置记忆推理。后端按聊天串行保存来源版本，按 Core 返回的消息 ID 同步。完成轮归档，显式请求整理，同一请求可查回执，选择 Profile 时检查预期版本。[接入合同](development/open-webui-upgrade-2026-11.md#新版记忆接入) · [schema 34 客户端](../downstream/upgrade-20261121.md#schema-34-客户端) |
| HUD 和 FAST | HUD 分列当前聊天、当前分支的 Archive 和 Curator 处理覆盖。旧 Core 缺少覆盖字段时沿用原显示。FAST 回答、取消、发布共用服务端签发的尝试身份，推理和发布前复核所有权。[原行为合同](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md) · [客户端组合验收](../downstream/upgrade-20261121.md#schema-34-客户端) |

## 登录迁移

两个候选均从 WebUI 数据库版本 `d4c1a8e37b62` 读取准入白名单。4.21 隔离演练的目标版本为 `9f6c2a8d1b43`，4.22 的迁移程序要求目标为 `d59b632a4c18`。核对账号、角色、外部主体、组权限及空业务表时，使用对应提交的工具和证据。[白名单决定](development/open-webui-upgrade-2026-11.md#登录信息最小迁移) · [4.21 隔离演练](https://github.com/harrywenjie/open-webui/blob/677ad272dbcab7f0b0cb50cda8b814f559f53b4f/downstream/upgrade-20261121.md#仅迁登录的隔离演练) · [4.22 迁移程序](https://github.com/harrywenjie/open-webui/blob/106e98dd4f8b4adb9dc68fe4f367e19d5a311663/downstream/migrate_login.py) · [实装后的恢复条件](DEVELOPMENT.md#当前状态)
