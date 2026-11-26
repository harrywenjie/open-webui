# Open WebUI fork 产品大纲

## 维护范围与上游同步

2026-11-21，维护者确定由本 fork 维护 WebUI 客户端定制及其升级计划。跟进上游时应保留普通聊天、Dissipative 记忆接入和实例外观。定制源码及资源可从冻结的上游版本重放，保留已发布历史。常规升级采用固定 release，当次指定同步官方主线时固定提交。Core 与规范插件归 Dissipative，主机配置、主题发布源和上线窗口归 PrivateOperations。[文档归属决定](maintenance/upgrade-document-ownership-20261121.md) · [主分支与定制备份决定](maintenance/fork-main-20261121.md#历史归属) · [上游同步约定](../AGENTS.md#上游同步与交付)

## 实例外观

Data Rift 图标和 Harry's Ops Deck 是每次升级、构建和重新安装都要交付的实例外观。站点 favicon、Apple touch、PWA 图标及应用 logo 应匹配发布清单。新库从审定来源恢复已启用的 Theme Designer Pro 及其发布内容。用户可以在聊天页和 HUD 使用 Dark、OLED Dark、Light、Her，选择 System 时跟随系统明暗，重启后仍能看到所选外观。

2026-11-21 确定的放行条件分别要求图标字节匹配、主题在实际浏览器生效。上游改动若破坏其中一项，修复并复验后才能发布。主动改版由维护者另行决定。[当日项目规则](https://github.com/harrywenjie/open-webui/blob/3ae22bd845767de1ed201498fe2810ffa3daa511/AGENTS.md#所有升级和更新均须保留自定义图标与主题) · [外观验收依据](development/open-webui-upgrade-2026-11.md#图标与主题验收)

## 聊天与连续记忆

普通聊天沿用 WebUI 自己的模型连接。Core 独立配置记忆推理。用户在 HUD 分别查看当前聊天、当前分支的 Archive 归档覆盖和 Curator 整理覆盖。FAST 回答、取消和发布共用一次服务端签发的尝试身份，推理和发布前均复核聊天所有权。[2026-09-27 已有客户端约定](https://github.com/harrywenjie/open-webui/blob/5a3026ed431bd2f01e3b47909a77dd871bf76c7b/downstream/README.md)

2026-11-21 的升级将连续记忆接到 WebUI 专用 Core。完成的对话轮自动归档，用户显式发起整理、查询进度并选择 Profile。选择 `NONE` 仍可召回一般记忆。编辑、切换分支、撤权和删除后，召回应遵守有效来源和账号权限。重启后应能读回有效的聊天、选择和回执。WorldHatch 继续使用独立实例。[记忆接入决定与验收方向](development/open-webui-upgrade-2026-11.md#新版记忆接入)

## 登录与数据范围

2026-11-21 的 Mac 4.22 窗口仅迁登录和准入信息。原账号应能按原方式登录，禁用和待批限制仍生效。目标 WebUI 与专用 Core 从空库建立，实例主题和插件从审定材料恢复。旧聊天、上传、个人设置、会话、旧记忆和 WorldHatch 数据均在迁移范围之外。该窗口选择向前修复，结束后备份和恢复安排随主机决定更新。[登录白名单](development/open-webui-upgrade-2026-11.md#登录信息最小迁移) · [当次窗口决定](development/open-webui-upgrade-2026-11.md#候选资格与-mac-窗口) · [后续恢复边界](DEVELOPMENT.md#当前状态)

后续升级的数据范围、恢复方式及生产窗口授权由维护者在当次任务确定。[同步手册的现场条件](development/upstream-sync.md#构建与组合验收)
