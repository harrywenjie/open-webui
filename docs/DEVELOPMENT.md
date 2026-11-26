# Open WebUI fork 开发入口

## 当前状态

`main` 保存 fork 历史、定制源码和可重放补丁。当前没有已授权的开发或发布任务。产品取舍查[产品大纲](Project_Outline.md)，接口与脚本查[工程导航](ENGINEERING_DESIGN.md)，发布结论查[验证导航](VALIDATION.md)。

**最近确认的实装。** 2026-11-21，Mac 安装 Open WebUI 0.13.4 / Adapter 4.22，产品提交 `106e98dd4`，冻结上游 `0666e59d2`，WebUI 专用 schema 34 Core 为 `acb4be0`。WorldHatch 使用独立实例。11 月 22 日的主机重启复核了桌面登录前的启动。[实装身份](https://github.com/harrywenjie/PrivateOperations/blob/340e5c62f61a51d2399ad9390052abb8b183b644/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md#installed-identity) · [后续启动验证](https://github.com/harrywenjie/PrivateOperations/blob/b7351ca2dae375c04884b228c955ebac21312526/servers/192.168.1.60/reports/2026-11-22-webui-stack-prelogin.md#正常重启和首次桌面登录)

**恢复边界与待核项。** 11 月 22 日，维护者取消 WebUI 和专用 Core 的业务数据备份。11 月 21 日依赖登录导出重建账号的路径已退出。主机手动更新器的综合校验还缺一个策略要求的固定模型项，下次评审模型设置或升级时复核。[备份决定](https://github.com/harrywenjie/PrivateOperations/blob/b7351ca2dae375c04884b228c955ebac21312526/servers/192.168.1.60/reports/2026-11-22-webui-stack-prelogin.md#备份清理) · [更新器校验结果](https://github.com/harrywenjie/PrivateOperations/blob/b7351ca2dae375c04884b228c955ebac21312526/servers/192.168.1.60/reports/2026-11-22-webui-stack-prelogin.md#维护工具)

## 下一任务卡

| 何时阅读 | 直接依据与通过条件 |
|---|---|
| 收到上游同步或重新打补丁的任务 | 对照[升级范围](Project_Outline.md#维护范围与上游同步)，按[同步手册](development/upstream-sync.md#冻结本轮输入)固定输入并逐项移植。补丁可重放，导出可追溯到 fork 提交，同一候选通过 [wheel、浏览器、记忆及重启验收](development/upstream-sync.md#构建与组合验收)。 |
| 升级影响图标、主题或加载方式 | 对照[实例外观](Project_Outline.md#实例外观)和[定制目录](../downstream/README.md)核对原件。图标按阶段匹配清单，主题在候选聊天页、HUD 和重启首屏分别通过[外观验收](development/open-webui-upgrade-2026-11.md#图标与主题验收)。 |
| 复查 4.22 的登录迁移或数据恢复 | 从[当次登录白名单](development/open-webui-upgrade-2026-11.md#登录信息最小迁移)查准入范围，按[实装与后续恢复边界](#当前状态)核对所问日期的可用路径。未来窗口须重新确定数据范围并获得授权。 |
| 整理文档或变更当前焦点 | 按维护者全局 `AGENTS.md` 和[项目维护约定](../AGENTS.md#文档维护)，复核受影响的大纲章节、合同和证据。上次[章节映射与阅读走查](maintenance/fork-docs-migration-20261126.md)按需查阅。 |

## 下游已有行为

调查模型归属、HUD 计数、分支权限或 FAST 取消与发布时，从[聊天与连续记忆合同](ENGINEERING_DESIGN.md#聊天与连续记忆)进入。需要判断哪些行为经过真实模型、回环模型或现场验证时，查[候选证据](VALIDATION.md#候选证据)和[现场证据](VALIDATION.md#现场证据)。
