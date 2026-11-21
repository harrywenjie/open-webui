# Open WebUI 全面升级开发计划

本页保留 2026-11-21 的计划与当时的资格边界。Mac 4.22 窗口已完成。[当次实装](https://github.com/harrywenjie/PrivateOperations/blob/340e5c62f61a51d2399ad9390052abb8b183b644/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md) · [后续同步手册](upstream-sync.md)

2026-11-21，维护者决定同步官方主线，接入新版 Dissipative 连续记忆。此次切换从空的 WebUI 与专用 Core 库启用，只迁用户登录信息，放弃回退。自定义图标与主题是每次升级都要交付的实例功能。当前进度归[开发入口](../DEVELOPMENT.md)，长期要求归[仓库规则](../../AGENTS.md#所有升级和更新均须保留自定义图标与主题)。

## 起点和目标版本

| 对象 | 规划时的依据 | 开工时的处理 |
| --- | --- | --- |
| 官方 `open-webui/open-webui:main` | 11 月 21 日核到 `0666e59d26a4d056e0bacee41742486badd71cf8`，包版本 `0.13.4`。相对旧上游 `8bd8b4fac5e059578ac0c74b3c18d11139f88b7d` 前进 2,211 个提交 | 重新读取官方 `main`。若前移，记录新 SHA、包版本和差异，冻结该 SHA 贯穿构建与验收。[上游提交](https://github.com/open-webui/open-webui/commit/0666e59d26a4d056e0bacee41742486badd71cf8) · [上游比较](https://github.com/open-webui/open-webui/compare/8bd8b4fac5e059578ac0c74b3c18d11139f88b7d...0666e59d26a4d056e0bacee41742486badd71cf8) |
| 本 fork | 产品基线 `5a3026ed431bd2f01e3b47909a77dd871bf76c7b`，Open WebUI `0.11.4` / Adapter `4.20`。该产品提交相对旧上游有 12 个提交、38 个变更路径 | 从维护分支 `codex/dissipative-online` 的实际已发布 HEAD 开工，保留后续仓库规则与文档；产品差异与纯文档差异分别盘点。[下游清单](../../downstream/adapter.json) |
| Core | 规划时 Dissipative 的产品源码为 `a2da5229d8548bafa9a91b49b700bab8a2a89101`。WebUI 专用实例为 r27 / schema 27。目标源码默认普通协议与 schema 29，连续记忆整套能力须显式启用，可到 schema 34 | 固定实际集成源码、描述符、启动参数与 wheel 哈希。WebUI 与 WorldHatch 拥有独立的 Core 进程、实例身份和数据库，开发使用独立测试实例。[安装基线](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/releases/current.json) · [Core 服务入口](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/scripts/run-service.py) |

## 上游同步

1. 在 fork 的隔离工作树核对 `origin`、`upstream`、工作区和共同祖先，合并冻结的官方提交，保留双方历史。记录 Python、Node、锁文件、数据库初始化及认证变化，使用目标提交的工具链构建。
2. 按下游清单复核八处上游补丁和 13 项 overlay，逐项说明保留、上游已等效提供或需要移植的行为。八处包括后端 `env.py`、`main.py`、`routers/chats.py`、`utils/middleware.py`，以及前端 `Chat.svelte`、`MessageInput.svelte`、`IntegrationsMenu.svelte`、`ValvesModal.svelte`。自动合并也需核对消息持久化、回调顺序、异步任务和权限。保留品牌资产和许可。[补丁职责](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/adapters/open-webui/patches/README.md)
3. 从正常入口验证登录、建聊、流式结束、Continue、重新生成、编辑、分支、删除、跨用户隔离、Filter / Events / Tool、HUD、FAST 及模型挂载。核对中断、重试和重启的状态与去重。按下一节在同一候选验证完整外观。
4. 提交 fork 后，在 Dissipative 仓库用 `python scripts/sync-open-webui-fork.py --source "<已提交的 fork 工作树绝对路径>" --write` 再生导出，再用 `--check` 核对。若原工具只收 release tag，补充可验证的固定提交身份支持。更新 Adapter 版本、清单、上游文件哈希、patch、overlay 和构建身份，保存候选 wheel 及 SHA-256。[导出工具](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/scripts/sync-open-webui-fork.py)

**首个检查点**要求候选含旧下游与冻结上游两个祖先，下游每项差异有去向，正常入口的回归有结果，导出可追溯到已提交 fork。候选产物与实际安装记录分别登记。

## 图标与主题验收

| 检查对象 | 基线与操作 | 验收证据 |
| --- | --- | --- |
| Data Rift 图标 | `data-rift-v1` 清单含八个资产，另有根 `favicon.png`。在 fork 根运行 `python downstream/verify_branding.py`，对实际候选 wheel 加 `--wheel`；安装包目录可用 `--installed`，部署或演练站点用 `--url`。检查 HTML/manifest 指向的实际图标入口，覆盖浏览器标签、Apple touch 与 PWA | 源码、构建物和实际 HTTP 端按各自阶段逐项匹配清单；干净浏览器加载自定义图标。仅发布源码时，后续未运行的阶段列为待验。[图标清单](../../downstream/branding/manifest.json) · [校验程序](../../downstream/verify_branding.py) |
| Harry's Ops Deck 的发布材料 | 从获准的 PrivateOperations 主机目录取 `open-webui-theme` 的版本化定义、CSS、生成物与 `open-webui-functions` 中经审核的 Theme Designer Pro。用 `build_theme.py --check` 核对生成物。将 `theme_designer_pro` 作为 active、non-global、无模型挂载的 Event Function 配置，按审定策略重建 `DATA_DIR/theme/` 的 CSS、state、sections 和 library 四个发布文件 | 对照主题源核对 Function 身份、配置与四文件的 hash。若现场有已接受但尚未归入版本控制的主题发布，先在其归属仓库核实差异。候选空库从审定材料重建实例主题；旧聊天库、个人偏好和浏览器状态均不作为主题来源 |
| 主题在界面上生效 | 验证 `/static/custom.css`、`/static/loader.js` 的组合标记，及 `/api/v1/theme-designer/theme.css`、`/api/v1/theme-designer/state.json` 的实际响应。用新浏览器会话访问聊天和 HUD，切换 Dark、OLED Dark、Light、Her 与 System，核对前景/背景、焦点和弹层；按既有策略，登录页主题开关关闭 | 记录候选版本、轻量截图或可比较的渲染证据，核对刷新、干净安装和服务重启后的外观。上游若调整样式选择器、路由或 DOM，修复加载/样式并重新验证。默认外观或仅有 HTTP 200 均不能通过视觉验收 |

## 新版记忆接入

| 工作 | WebUI 交付行为与通过条件 |
| --- | --- |
| 协商、内部模型 | WebUI 后端持专用实例密钥，走认证的 `/v1/continuity/*`。区分 transport v1、基础快照/输入 `dissipative.continuity.v2` 与 `curator-v16-continuity` 提示词。按依赖启用 transport、round curation、Profile selection、publication、source-format transition，实测 schema 34 与各项能力，单列可选模式。旧 managed catalog 的 `--model-admin-store` 与新启动模式互斥；用独立 Qwen Continuity 绑定、实例 key、调度协议 4 在空库跑通，核对必要管理操作并记录兼容路径。覆盖缺配置、权限、错误、超时、预算、重启；错误向界面可见。[运行契约](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/architecture/memory-continuity-runtime.md) · [模型管理](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/development/model-administration.md) |
| 来源与生命周期 | 以受信后端已持久化消息和活动分支全量同步，提交有序 observe，按 Core 返回的来源 ID prepare / recall。覆盖 Continue、流式中断重试、同角色多消息、重新生成、编辑、分支、共享撤权、删除、丢 ACK 和重启。核对实例、owner、chat、来源、角色、父子顺序与可读资格，重复完成不重复归档，旧分支及撤权内容不可召回。[有序来源](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/architecture/observation-events.md) · [删除](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/architecture/continuity-deletion.md) |
| 整理与 Profile | 完成对话轮即归档，显式整理单独准入、查询与重试。提供 `NONE/SELECTED` 选择、版本核对和并发保护；`NONE` 保留一般记忆与召回，选择 Profile 后传递 guidance。用实际 WebUI 验证空库、切换、重启回读与权限隔离。[整理合同](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/architecture/round-curation.md) · [Profile 选择](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/contracts/profile-selection-v1.json) |
| 字段发布与格式切换 | 结构化字段能追溯发布证据、原作业和有效来源。区分沿用结果与本次发布，校验撤权和旧 revision。严格来源格式转换仅对已排空且身份满足合同的 scope 开放。验证正常返回、拒绝及不可见状态。[字段发布](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/contracts/profile-publication-v1.json) · [任务身份](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/architecture/publication-job-identity.md) · [格式切换](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/architecture/source-format-transition.md) |

WebUI 自有聊天模型连接与 Core 内部模型各自配置。保留插件 ID、挂载、冻结提示与协议，变化采用版本化迁移。WebUI 源码和客户端验收在本 fork；规范插件、Core、导出和对应资格归 Dissipative。WorldHatch 的既有运行与合成测试各有独立资格范围。[Core 维护矩阵](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/MAINTENANCE.md#change-matrix)

## 登录信息最小迁移

- **迁入。** 从实际启用的登录方式、源版和目标版 schema 建立字段白名单。保留稳定账号 ID、登录标识、密码验证哈希、启用/禁用、待批准及管理员等准入角色。对已启用的外部登录保留必要 issuer/provider 和 subject；如有 MFA/目录绑定，核实最小所需材料。其余必填字段取安全默认值。检查唯一性、外键、哈希验证器、角色冲突与孤立绑定。[身份验证模型](../../backend/open_webui/models/auths.py) · [账户模型](../../backend/open_webui/models/users.py)
- **从空库重建。** 不迁旧聊天、共享链接、上传、知识/向量库、个人设置、头像、OAuth token、API key 或会话。旧 Core 镜像、Archive、Profile、召回记录、作业和派生索引退出。盘点专属卷、对象存储和后台任务，防止回灌。新库由目标版初始化；按版本化材料建立实例级图标、主题、插件、模型挂载和受保护的服务配置。
- **验收。** 先以合成管理员、普通、禁用/待批账号及实际启用的外部登录类别演练可重复导入、中断续做及重复标识拒绝。在受保护进程内核对数量、角色、哈希及绑定完整性，仅记录汇总。原账号能以原方式重新登录，禁用账号仍被拒，角色与隔离正确，原聊天、上传和旧记忆计数为零。新建聊天与记忆可在重启后读回。限制登录专用导出的权限与留存；验证不采集用户明文密码。

## 候选资格与 Mac 窗口

1. **组合资格。** 从实际 wheel、规范插件、全新 WebUI/Core 库和专用配置安装。在 fork 运行定向后端/前端测试及浏览器回归；在 Dissipative 运行受影响门禁和 `python scripts/test.py --all`。从实际 WebUI 登录、聊天、归档、整理、切换 Profile、召回、撤权/删除，随后重启，复核图标与主题。按已有授权预算，在合成 scope 使用 `DISSIPATIVE_CREDENTIAL_FILE` 完成真实 provider 资格。将源码、合成、浏览器、模型与安装证据分别记录。[测试规范](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/docs/development/testing.md)
2. **切换演练。** 用合成旧库围住写入口与后台写者，只导登录，核验后建空库，重新配置主题与必需服务。演练中断、重复运行、重登和向前修复。开发审阅标准 `window.sh` 与旧 reset 工具：前者默认整库备份并在失败时回退，后者保留的数据范围超过登录白名单。本次窗口使用认证专用导出和向前修复。[窗口手册](https://github.com/harrywenjie/dissipative/blob/main/docs/operations/updater-and-versioning.md) · [旧 reset](https://github.com/harrywenjie/dissipative/blob/a2da5229d8548bafa9a91b49b700bab8a2a89101/deployment/dissipative_reset.py)
3. **生产与故障。** 组合与演练通过后，按实际生产窗口授权，从 PrivateOperations 主机清单和完整主机文档核对路径、实例、端口与产物。冻结全部写入，验证受保护的最小登录导出后才处理专属旧数据。授权范围限 WebUI 专用服务及其 Core，排除共享备份和 WorldHatch。切换后如有故障，保持维护页面，修复新候选或从登录专用导出重建。复核登录、聊天、新记忆、主题、图标、重启与后台健康，再开放访问；从新状态恢复例行备份。按来源仓库登记实际安装身份和已知限制。

上游同步、记忆接线与登录迁移分别形成检查点。组合资格依赖三者及外观验收，生产窗口依赖组合资格和完整演练。
