# Open WebUI fork 开发入口

## 当前状态

`main` 维护 fork 的完整历史、定制源码和可重放备份。2026-11-21 实装为 Open WebUI 0.13.4 / Adapter 4.22，产品提交 `106e98dd4`，冻结上游 `0666e59d2`，WebUI 专用 schema 34 Core 为 `acb4be0`。WorldHatch 使用独立实例。本次 Mac 窗口已完成。[现场与向前修复](https://github.com/harrywenjie/PrivateOperations/blob/340e5c62f61a51d2399ad9390052abb8b183b644/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md) · [候选资格](evidence/open-webui-0.13.4-schema34.json)

## 下一任务卡

| 何时阅读 | 输入与通过条件 |
|---|---|
| 下一次收到上游同步或重新打补丁的任务 | 按[同步手册](development/upstream-sync.md)冻结上游、逐项移植并重放校验，再验收 wheel、浏览器、记忆及重启。 |
| 修复图标、主题或下游脚本 | 从[定制目录](../downstream/README.md)定位原件、补丁、私有来源和对应检查。 |
| 调查 4.22 的数据或恢复边界 | 查[当次登录决定](development/open-webui-upgrade-2026-11.md#登录信息最小迁移)及上方现场记录。 |

## 下游已有行为

WebUI 维护自己的对话模型和来源权限，Core 独立配置推理。HUD 按聊天和分支显示 Archive 与 Curator 的处理覆盖，兼容旧 Core 缺少覆盖字段的响应。FAST 回答、取消、发布共用服务端签发的尝试身份，推理和发布前复核聊天所有权。[客户端合同与资格](../downstream/upgrade-20261121.md#schema-34-客户端) · [早期 HUD 与 FAST 行为](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md)

复查分支来源或本次整理时读[维护记录](maintenance/fork-main-20261121.md)。导航维护遵循[项目规则](../AGENTS.md)。
