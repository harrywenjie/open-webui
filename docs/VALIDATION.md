# Open WebUI fork 验证导航

## 复验发布候选

| 要证明的行为 | 取证入口与判据 |
|---|---|
| 能从冻结上游恢复定制 | 从固定 fork 提交校验清单和补丁，在干净索引重放并比对路径、文件模式和 blob。受保护的主题与 Function 按审定发布字节另验。[重放与受保护来源校验](development/upstream-sync.md#固定产品与备份) |
| 安装后保留完整外观 | 对同一候选逐阶段核对源码、wheel、安装目录、实际 HTTP 图标及 manifest 指向。安装演练在真实浏览器切换四种主题和 System 明暗，检查聊天页、HUD 及重启后首屏。[图标与主题验收](development/open-webui-upgrade-2026-11.md#图标与主题验收) · [安装演练](../downstream/tests/rehearse_install.py) |
| 登录、来源权限和记忆在重启后仍有效 | 登录按该窗口决定的范围演练。连续记忆从聊天和 HUD 入口覆盖归档、显式整理、Profile、分支与撤权、FAST 取消与发布，再重启 WebUI 和专用 Core 读回。记录回环与真实模型各自的结果。[登录工具的版本边界](ENGINEERING_DESIGN.md#登录迁移) · [组合演练](../downstream/tests/qualify_continuity.py) |

## 候选证据

两份 2026-11-21 的 Windows 记录对应不同的 wheel。同名包按 fork 提交和各自 JSON 中的 SHA-256 区分。

| 候选 | 可据此确认的范围 |
|---|---|
| Adapter 4.21，fork `31b109a08`，导出 `0da9380` | 合成账号的密码与回环 OIDC、空业务表、图标、主题、聊天和重启。HUD 组件另有模拟 API 回归。该导出的 Dissipative 全池运行有一项条件跳过。[候选 JSON](evidence/open-webui-0.13.4-candidate.json) · [构建与外观记录](../downstream/upgrade-20261121.md#构建与外观) · [导出提交与门禁计数](../downstream/upgrade-20261121.md#schema-34-客户端) |
| Adapter 4.22，fork `106e98dd4`，导出 `acb4be0` | schema 34 空库、合成账号和对话。真实 Qwen 覆盖整理、FAST 发布、重启与来源编辑后失效。派发前取消及重启后仍为 `CANCELLED` 由回环用例覆盖。Chromium 的整理控件用例模拟 503。历史来源格式只检查状态，空库未执行旧数据格式转换。[最终候选 JSON](evidence/open-webui-0.13.4-schema34.json) · [客户端逐项实测](../downstream/upgrade-20261121.md#schema-34-客户端) |

## 现场证据

2026-11-21 的 Mac 切换报告给出已安装 wheel 与 Core 身份，记录实际登录、图标和主题、真实聊天、Profile、召回、双进程重启和 WorldHatch 独立性。判断 FAST 取消或发布时，使用上表注明的 Windows 组合证据。[实装身份](https://github.com/harrywenjie/PrivateOperations/blob/340e5c62f61a51d2399ad9390052abb8b183b644/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md#installed-identity) · [服务与浏览器验收](https://github.com/harrywenjie/PrivateOperations/blob/340e5c62f61a51d2399ad9390052abb8b183b644/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md#service-and-browser-acceptance)

2026-11-22 的主机报告记录同一套服务在重启至桌面登录前后的观测。该日的恢复决定和手动更新器校验结果由主机记录维护，排障从[开发入口的实装与恢复边界](DEVELOPMENT.md#当前状态)进入。
