# Open WebUI fork 仓库规则

开发从 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 进入。涉及用户可见行为、外观或升级数据范围时，先读[产品大纲](docs/Project_Outline.md)的对应章节。本 fork 维护 WebUI 源码、下游适配、升级计划和客户端验收。Dissipative 维护 Core、规范插件、从已提交 fork 再生的导出及其资格。PrivateOperations 维护主机配置、受保护的主题发布源和现场记录。

## 所有升级和更新均须保留自定义图标与主题

- **自定义图标。** 合并上游、更新依赖、调整前后端、更换构建或重新安装，都须交付完整的 Data Rift 图标，包括站点 favicon、Apple touch 图标、PWA 图标和应用 logo。以[图标清单](downstream/branding/manifest.json)为准，更新前核对源资源；发布候选验证 wheel，安装后验证实际提供的资源。[图标校验工具](downstream/verify_branding.py)
- **自定义主题。** 保留实例级 Harry's Ops Deck，以及已有的 Dark、OLED Dark、Light、Her 四种模式和 System 选择行为。维护 Theme Designer Pro（`theme_designer_pro`）的交付接口、启用状态、发布内容和经审定的配置。新库安装也从版本化主题源恢复实例外观。每个发布候选在实际浏览器核对加载、模式切换、聊天界面与 HUD，以及重启后再次加载。图标哈希与主题渲染分别验收。
- **放行条件。** 上游若改变静态资源位置、CSS/JS 加载方式、主题标记或组件结构，应移植下游适配并补齐对应证据。图标或主题丢失、回落到上游默认外观，或候选验证缺失时，先修复并复验再发布。主题、图标的主动改版需有单独的产品决定。

## 上游同步与交付

长期分支为 `main`。常规升级固定上游 release，指定同步官方主线时冻结不可变提交，在分离工作树验证后合入。保留已发布历史，从已提交的 fork 再生下游导出，分别记录候选和实装证据。[同步与补丁手册](docs/development/upstream-sync.md)

## 文档维护

遵循维护者全局 `AGENTS.md` 的文档分层与维护约定。普通更新沿[入口任务卡](docs/DEVELOPMENT.md#下一任务卡)直达大纲、工程合同或验证依据。整体整理、焦点转移、导航增长和模块收尾使用 `doc-governance`。
