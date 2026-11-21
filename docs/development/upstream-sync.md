# 从官方 main 同步并恢复 fork 定制

在 PowerShell 7 的 fork 根目录执行。每次选择新上游时，保留原 fork 历史、冻结的上游提交和实装版本三种身份。产品差异列在 [Adapter 清单](../../downstream/adapter.json)，备份和验收脚本从 [downstream](../../downstream/README.md) 进入。

## 冻结本轮输入

确认 `origin` 是自己的 fork、`upstream` 是 `https://github.com/open-webui/open-webui.git`，本地 `main` 干净且与 `origin/main` 一致。先验证上一版备份。示例目录名按本轮更换。

```powershell
git status --short --branch
git switch main
git remote -v
# 首次克隆只有 origin 时，执行下行一次。
# git remote add upstream https://github.com/open-webui/open-webui.git
git fetch --no-tags origin refs/heads/main
git merge --ff-only FETCH_HEAD
$fork = (git rev-parse --show-toplevel).Trim()
$prior = (git rev-parse HEAD).Trim()
$config = Get-Content -Raw downstream/adapter.json | ConvertFrom-Json
$oldUpstream = $config.upstream.commit
python downstream/repatch/snapshot.py check
git fetch --no-tags --refmap= upstream refs/heads/main
$next = (git rev-parse FETCH_HEAD).Trim()
git log -1 --format='%H %cs %s' $next
git diff --stat $oldUpstream $next
$job = Join-Path $fork ('temp/sync-' + $next.Substring(0,12))
New-Item -ItemType Directory -Path $job -ErrorAction Stop
$candidate = Join-Path $job 'candidate'
git worktree add --detach $candidate $prior
git -C $candidate merge --no-ff --no-commit $next
```

每一步核对返回码。上游历史分叉、已是同一提交或合并有冲突时，先核对共同祖先及变更范围。保留 `$next` 的完整 SHA 和包版本贯穿本轮。常规 release 升级按项目规则固定 tag 对应的提交。

## 合并与重新打补丁

常规路线在候选工作树完成上面的历史合并。`git -C $candidate diff --name-only --diff-filter=U` 列出冲突。按清单对比“上一上游 → 当前 fork”和“上一上游 → 新上游”。对每项记录继续使用、移植到新位置或上游已提供等效行为。特别核对上游异步回调、消息落库和授权检查的顺序。4.22 的客户端涵盖 9 个修改文件、15 个新增文件和 9 个品牌路径。[逐项移植记录](../../downstream/upgrade-20261121.md)

需要从干净上游重建、查明遗漏或解决改名时，在另一份分离工作树重放备份。补丁含完整 Git blob 身份和二进制资源。已合并的候选继续用于正式交付，以保留父提交。

```powershell
$repair = Join-Path $job 'repatch'
$patch = Join-Path $fork 'downstream/repatch/webui.patch'
git worktree add --detach $repair $next
git -C $repair apply --3way --index $patch
git -C $repair ls-files -u
git -C $repair diff --cached --stat
```

三方应用发生冲突时，逐个比对三个版本，结合新组件、路由、静态资源布局重新移植，在候选中落实验证过的解法。图标可从[逐文件原件](../../downstream/branding/assets)恢复到新版本实际使用的位置。数据库资格、旧聊天过滤、Profile、FAST 尝试与取消、Tool 权限、聊天 HUD 和静态图标各有自己的验收边界。保持上游许可和第三方署名。

## 固定产品与备份

更新候选的 `downstream/adapter.json` 中的上游版本、ref、完整 SHA、Adapter 版本及路径分类。新引入的运行时修改须列入相应路径。先提交解决后的产品源码和清单，再从该提交刷新备份。工具直接读取 Git blob，校验根 favicon、8 个图标和清单，也会指出遗漏的产品路径。每次重放使用新的临时索引名。

```powershell
Set-Location $candidate
git status --short
# 逐项暂存已解决的产品源码和清单，检查暂存差异，然后提交候选合并。
git diff --cached --check
git commit -m "feat: port fork customizations to the pinned upstream"
$source = (git rev-parse HEAD).Trim()
python downstream/repatch/snapshot.py refresh --ref $source
python downstream/repatch/snapshot.py check --ref $source --replay-index temp/repatch-check/replay.index
python downstream/verify_branding.py
git diff --check
```

审阅并提交备份的实际差异。将最终选定的干净 fork 提交作为构建输入，登记其 SHA。受保护的 Harry's Ops Deck、Theme Designer Pro 与 Qwen 控件保存在 PrivateOperations。按[保护清单](../../downstream/repatch/protected-sources.json)核对有权限的主题目录与 Function 目录。四份发布文件使用审定字节，Theme Designer Pro 使用审定的 CRLF。新库从版本化来源恢复 Function 的 ID、启用状态、作用域、配置及发布内容。

```powershell
$ops = 'E:/PrivateOperations/servers/192.168.1.60'
$themeDir = Join-Path $ops 'open-webui-theme'
$functionsDir = Join-Path $ops 'open-webui-functions'
$privateStage = Join-Path 'E:/PrivateOperations/temp' ('webui-' + $source.Substring(0,12))
$archive = Join-Path $privateStage 'reviewed.zip'
python downstream/repatch/verify_protected.py --theme-dir $themeDir --functions-dir $functionsDir --private-archive $archive
Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $privateStage 'publication')
```

归档从固定 Git blob 导出四份主题发布文件、生成器、定义和 Function 来源，并保留 Theme Designer Pro 审定的 CRLF。即使 Windows 工作树转换了换行，演练和现场发布仍可从这份归档取相同字节。将解包后的 `theme` 和 `functions/theme_designer_pro_event.py` 分别传给演练程序的 `--theme-source` 和 `--theme-function`。每次导出选用新的私有归档路径。

## 构建与组合验收

在 Dissipative 的本轮工作树执行以下命令。`$candidate` 指向刚固定的干净 fork 工作树。构建目录须是 Dissipative 仓库 `temp` 下尚不存在的目录。构建器先核对导出，再以目标版本的 Node 和 npm 锁文件构建前端，使用 Hatchling 打包同一份前端。留存 wheel 文件名、SHA-256、冻结提交和实际解释器版本。[导出与构建器](https://github.com/harrywenjie/dissipative/tree/main/adapters/open-webui) · [发布手册](https://github.com/harrywenjie/dissipative/blob/main/docs/operations/updater-and-versioning.md)

```powershell
python scripts/sync-open-webui-fork.py --source $candidate --write
python scripts/sync-open-webui-fork.py --source $candidate --check
python adapters/open-webui/build_adapter.py --source $candidate --work temp/upstream-sync/build
python scripts/test.py --all
```

| 验收对象 | 在对应阶段取得的证据 |
|---|---|
| 图标 | 在 fork 根运行 `python downstream/verify_branding.py --wheel <wheel>`。安装后用 `--installed <open_webui目录>`，启动后用 `--url <站点>`。浏览器核实 favicon、Apple、PWA 清单和应用 logo。 |
| 主题与登录 | 用实际安装了候选 wheel 的解释器运行 [rehearse_install.py](../../downstream/tests/rehearse_install.py)，参数见 `--help`。验证 Dark、OLED Dark、Light、Her、System 明暗、聊天 HUD 和重启首屏。登录及数据范围按本次发布决定。 |
| 记忆与权限 | 从 [qualify_continuity.py](../../downstream/tests/qualify_continuity.py) 验证普通对话、分支/编辑/删除、跨用户隔离、Filter/Events/Tool、来源同步、Profile、FAST 取消/发布、重启回读。以独立 WebUI Core 和隔离库演练，真实模型使用获准的合成输入。 |
| 现场 | 单独授权后核对真实登录方式、发布配置与主机身份。验证实装图标和主题、真实对话、重启、备份、开放后的观察及相邻服务独立性。实装完成才更新安装指针。 |

验收通过后从主工作树用 `git merge --ff-only <候选提交>` 合入 `main`，复核 fork 与上游两个祖先，再推送并比对远端 SHA。临时工作树在安全点按全局回收规则收尾。2026-11-21 的“仅迁登录、专用 schema 34 从空库启动、向前修复”属于该次 Mac 窗口。未来的数据迁移与恢复策略须由当次任务确定。[当次决定](open-webui-upgrade-2026-11.md#登录信息最小迁移) · [当次现场验收](https://github.com/harrywenjie/PrivateOperations/blob/340e5c62f61a51d2399ad9390052abb8b183b644/servers/192.168.1.60/reports/2026-11-21-webui-422-cutover.md)
