# Fork 定制目录

| 需要的内容 | 位置及用法 |
|---|---|
| 已修改的上游文件、新增的前后端集成、数据库迁移和发布图标 | [Adapter 路径清单](adapter.json)列出实际源码。[可重放 Git 补丁](repatch/webui.patch)备份完整产品差异，可用标准 `git apply --3way --index` 从上游重建。[备份与重放校验](repatch/snapshot.py) |
| Data Rift 图标 | [设计原件](branding/data-rift-icon.svg)、[预览](branding/data-rift-icon-preview.png)、[8 个发布原件](branding/assets)、[字节清单](branding/manifest.json)与[源码、wheel、安装、HTTP 校验](verify_branding.py)。根 favicon 复用同名 PNG。 |
| Harry's Ops Deck、Theme Designer Pro、Qwen 控件 | [来源与发布哈希](repatch/protected-sources.json)固定 PrivateOperations 中的版本。[私有来源校验](repatch/verify_protected.py)只输出数量和版本。 |
| 登录迁移和客户端资格 | [登录迁移工具](migrate_login.py)、[登录与主题演练](tests/rehearse_install.py)、[连续记忆组合演练](tests/qualify_continuity.py)、[HUD 回归](tests/hud-lifecycle.cjs)。 |

从[开发入口](../docs/DEVELOPMENT.md)查实装基线。更新上游或恢复补丁时阅读[同步手册](../docs/development/upstream-sync.md)。
