# 上古影视工作流-FQLLG

横屏真人古装、仙侠、武侠短剧的 Seedance 2.5 视频制作插件，可以装进 Claude Code 和 Codex。

## 包含什么

| skill | 做什么 | 什么时候用 |
|---|---|---|
| `film-pipeline` | 总调度：判断下一步交给哪个 skill，记进度表和交接文件（素材表、接线单） | 按场推进时：说「开这一场」「这场做到哪了」「下一步做什么」 |
| `horizontal-cinematic-prompt-agent-v2` | 把分镜写成可直接生成的 Seedance 提示词，检查、返修；场次记忆；内置《风起玲珑骨》24 集剧本、场次索引和人物表演圣经 | 主线 |
| `blender-greybox-previs` | 按平面图在本机 Blender 搭真实尺寸的灰模，摆人偶、编走位和运镜，导出给 Seedance 当参考的预演视频 | 可选：走位复杂、要锁定站位和运镜时 |
| `xuanshang-canvas` | 操作本机的玄上无限画布：上传认证素材、建视频节点、提交生成、样片转成片（画布工具随插件一起装） | 上画布时 |
| `video-local-edit` | 在已有视频上局部修改，其余部分锁定不变 | 只在你点名时：说「视频编辑」「局部修改」「二次编辑」。光给视频、说哪里不对，走返修提示词重新生成 |
| `video-rephotography` | 保留已有视频的表演、对白和节奏，换机位重拍 | 只在你点名「换机位重拍」「补拍角度」时 |
| `video-depth-rerender` | 把已有视频转成深度视频（只留远近层次的黑白灰视频），当参考视频重新生成，换人物、换场景 | 只在你点名「深度视频」「转深度」「深度重渲染」时。只说换人物、换场景，走返修提示词重新生成 |

```
分镜 ─┬─ 不做灰模（默认）──────────┐
      └─ 做灰模 → 灰模预演 ────────┴→ 写生成提示词 → 上画布生成
                                                    ├→ 满意 → 转成片
                                                    ├→ 不满意（默认，给视频让 AI 看也算）→ 返修提示词 → 重新生成
                                                    ├→ 点名「视频编辑」「换机位重拍」→ 局部修改 / 换机位重拍 → 上画布
                                                    └→ 点名「深度视频」「转深度」→ 转深度视频 → 写生成提示词（换人物、换场景）→ 上画布
```

分镜本身不在本插件里做。说「开这一场」时，总调度会在当前文件夹建这场的项目文件夹和进度表，之后每一步做完都停下等你确认；提交生成、转成片只在你明确说时才做。示例见 [docs/示例项目/](docs/示例项目/README.md)。

## 安装

最省事的办法：把下面这句话原样发给 Claude Code 或 Codex，它会照这份 README 帮你装好。

> 请帮我安装「上古影视工作流-FQLLG」插件：按 https://github.com/pencil102411-cell/shanggu-film-pipeline-fqllg 这个仓库 README 里「安装」一节操作。装之前先按「装之前：撤掉旧版本」检查，有旧版本的先列出来问我。装完运行自检，再按「检查深度视频工具」查一下这台电脑有没有转换工具，没有的先告诉我要装什么、多大、装到哪，问我要不要装。最后把结果告诉我。

下面的命令都在普通 PowerShell 窗口里运行（不用管理员）。

### 先准备

- **画布**：装好并打开玄上无限画布（或玄上内部版），登录自己的账号；电脑上要有 uv（画布工具运行要用的小工具）。没有 uv 时运行 `winget install --id=astral-sh.uv -e`。
- **灰模**（用到时才要）：Blender 4.2 及以上、Python 3.9 及以上、Pillow、FFmpeg。第一次用时运行灰模的 `setup`，见 [安装与MCP.md](plugins/shanggu-film-pipeline-fqllg/skills/blender-greybox-previs/references/安装与MCP.md)。
- **深度视频**（用到时才要）：转换工具「离线深度视频」，只支持 Windows。它有 800 多 MB，不放在插件里；装完插件后按下面「检查深度视频工具」查一次，电脑上已经有就直接用，没有再装。

### 装之前：撤掉旧版本

以前单独装过旧版的，要先撤掉，否则同一句话会叫出两个同名 skill，画布工具也会启动两份。没装过的跳过这一节。建议都先挪到一个备份文件夹，不要直接删。

- **Claude Code**：
  - 插件 `horizontal-cinematic-prompt-agent-v2@hengping-film-tools`、`xuanshang-canvas@xuanshang-tools`，以及插件市场 `hengping-film-tools`、`xuanshang-tools`（用 `claude plugin uninstall …`、`claude plugin marketplace remove …`）。
  - `~/.claude/skills/` 下的 `blender-greybox-previs`、`video-local-edit`、`video-rephotography`。
- **Codex**：
  - Windows 定时任务「Codex - 横屏影视提示词 Agent 2.0 自动更新」，以及 `%LOCALAPPDATA%\Codex\horizontal-cinematic-prompt-agent-v2\`。**这个不撤，旧插件会被自动装回来。**
  - 插件 `horizontal-cinematic-prompt-agent-v2@hengping-film-tools` 和插件市场 `hengping-film-tools`。
  - `~/.codex/skills/` 下的 `blender-greybox-previs`、`video-rephotography`、`video-local-edit`、`horizontal-cinematic-prompt-agent-v2`。
  - `~/.agents/plugins/marketplace.json` 里的 `horizontal-cinematic-prompt-agent-v2` 条目，和 `~/plugins/horizontal-cinematic-prompt-agent-v2`。
  - `~/.agents/skills/xuanshang-canvas`。
  - `~/.codex/config.toml` 里旧的 `[mcp_servers.xuanshang-canvas]`（换成下面新的登记），和它指向的 `%LOCALAPPDATA%\CodexTools\xuanshang-canvas\`。

Codex 的定时任务、旧插件、旧市场可以用这几行撤（第一行找到 Codex 的命令行程序；第二行删掉旧定时任务，没有就什么也不做；后两行卸掉旧插件、删掉旧市场，没有会提示找不到，不影响）：

```powershell
$codex = (Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Filter codex.exe -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
Unregister-ScheduledTask -TaskName 'Codex - 横屏影视提示词 Agent 2.0 自动更新' -Confirm:$false -ErrorAction SilentlyContinue
& $codex plugin remove horizontal-cinematic-prompt-agent-v2@hengping-film-tools
& $codex plugin marketplace remove hengping-film-tools
```

分镜 skill（`horizontal-storyboard-design`）不在本插件里，不用撤。

### Claude Code

第一条登记插件市场，第二条安装插件：

```
claude plugin marketplace add pencil102411-cell/shanggu-film-pipeline-fqllg
claude plugin install shanggu-film-pipeline-fqllg@shanggu-film
```

画布工具随插件一起装。**建议装完先自检一次**，把约 50MB 的依赖提前装好，免得第一次开会话时画布工具启动超时（画布开着时显示「已连接」）：

```powershell
$root = (Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw | ConvertFrom-Json).plugins.'shanggu-film-pipeline-fqllg@shanggu-film'[0].installPath
$env:UV_PROJECT_ENVIRONMENT = "$env:USERPROFILE\.claude\plugins\data\shanggu-film-pipeline-fqllg-shanggu-film\venv"
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\canvas-mcp\scripts\start-mcp.ps1" --check
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

然后新开一个会话。之后直接说需求就会用到对应的 skill；也可以用全名调用，例如 `/shanggu-film-pipeline-fqllg:blender-greybox-previs`。

### Codex

Codex 的命令行程序藏在 `%LOCALAPPDATA%\OpenAI\Codex\bin\<一串字母>\codex.exe`，第一行先找到它：

```powershell
$codex = (Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Filter codex.exe -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
& $codex plugin marketplace add pencil102411-cell/shanggu-film-pipeline-fqllg
& $codex plugin add shanggu-film-pipeline-fqllg@shanggu-film
```

画布工具在 Codex 里要另外登记：第一次启动要装依赖、上传大视频要等认证，都比 Codex 默认的等待时间长，而 Codex 官方文档没写插件里怎么把等待时间调长，所以改在配置文件里登记。

1. 放一个启动小脚本。它每次去插件缓存里找最新版的画布工具，插件更新后不用改配置。放在 `.codex` 文件夹里，不放 AppData：从 Claude 桌面版运行命令时，往 AppData 里新建的文件会被系统存进 Claude 自己的私有文件夹，Codex 看不到。

   ```powershell
   $dst = "$env:USERPROFILE\.codex\shanggu-film-pipeline-fqllg"; New-Item -ItemType Directory -Force $dst | Out-Null
   Copy-Item "$env:USERPROFILE\.codex\.tmp\marketplaces\shanggu-film\tools\codex-canvas-launcher.ps1" "$dst\start-canvas.ps1" -Force
   ```

2. 在 `%USERPROFILE%\.codex\config.toml` 末尾加上下面这段。已经有 `[mcp_servers.xuanshang-canvas]` 的，换掉旧的那段。`args` 里的路径用这一行打印出来，原样替换：`"$env:USERPROFILE\.codex\shanggu-film-pipeline-fqllg\start-canvas.ps1" -replace '\\','/'`

   ```toml
   [mcp_servers.xuanshang-canvas]
   command = "powershell"
   args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:/Users/你的用户名/.codex/shanggu-film-pipeline-fqllg/start-canvas.ps1"]
   startup_timeout_sec = 120
   tool_timeout_sec = 300
   ```

3. 自检，顺便把依赖提前装好（画布开着时显示「已连接」）。如果同一个窗口刚跑过 Claude Code 的自检，先运行 `Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue`。让 Claude 桌面版代装的，这一步最好自己从开始菜单打开 PowerShell 再跑一次：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\shanggu-film-pipeline-fqllg\start-canvas.ps1" --check
   ```

4. 重启 Codex。在 Codex 里用 `$film-pipeline`、`$horizontal-cinematic-prompt-agent-v2` 这样的写法点名调用 skill。

### 检查深度视频工具

不做深度重渲染的可以跳过。这一步只是在电脑上找一找转换工具「离线深度视频」，不下载、不安装：以前装过（桌面或开始菜单有它的快捷方式、或装在常见位置）就会找到，并记住位置，以后直接用。

Claude Code（`$root` 的取法见上面「Claude Code」一节的自检）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\skills\video-depth-rerender\scripts\depth-tool.ps1" check
```

Codex：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\.tmp\marketplaces\shanggu-film\plugins\shanggu-film-pipeline-fqllg\skills\video-depth-rerender\scripts\depth-tool.ps1" check
```

显示「未安装」时，把命令末尾的 `check` 换成 `install` 再运行一次：这一次只打印要装什么、多大（下载约 370 MB，装好约 870 MB）、装到哪（默认 `%USERPROFILE%\.shanggu-film-pipeline-fqllg\offline-video-depth`），仍然不下载。确认要装，在末尾再加 ` -Yes` 运行，它会从本仓库的发布页下载、核对文件没被改过、解压。想装到别的位置，加 ` -InstallDir "D:\某个文件夹"`。

没提前装也没关系：第一次说「转深度」时，`video-depth-rerender` 会先做同样的检查，没有就先问你。

## 更新

Claude Code：

```
claude plugin marketplace update shanggu-film
claude plugin update shanggu-film-pipeline-fqllg@shanggu-film
```

Codex（`$codex` 的找法同上）：

```powershell
& $codex plugin marketplace upgrade shanggu-film
& $codex plugin add shanggu-film-pipeline-fqllg@shanggu-film
```

更新后新开会话才生效。CHANGELOG 里写了「启动小脚本有改动」时，再做一次「安装 → Codex」第 1 步。从 1.0.1 或更早升级到 1.0.2 时，启动小脚本换了位置，要把「安装 → Codex」第 1～4 步重做一遍。

Codex 也可以用仓库里的脚本更新，它会先比对版本，有新版才装：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\.tmp\marketplaces\shanggu-film\tools\update-plugin.ps1"
```

想让 Codex 自动更新，把上面的 `update-plugin.ps1` 换成 `register-auto-update.ps1` 运行一次，会注册一个 Windows 定时任务（每次登录和每天中午 12 点各检查一次）；不想要了，同一条命令末尾加 ` -Remove` 再运行一次即可撤销。

## 仓库结构

```
.claude-plugin/marketplace.json      Claude Code 插件市场
.agents/plugins/marketplace.json     Codex 插件市场
plugins/shanggu-film-pipeline-fqllg/
├─ .claude-plugin/plugin.json        Claude Code 插件清单
├─ .codex-plugin/plugin.json         Codex 插件清单
├─ .mcp.json                         Claude Code 启动画布工具的配置
├─ skills/                           7 个 skill（总调度 + 6 个工作 skill）
├─ shared/                           几个 skill 共用的 Seedance 平台说明、素材引用写法、信息来源标注
└─ canvas-mcp/                       画布工具的程序
docs/                                示例项目、演示视频、旧仓库的更新记录（不随插件安装）
tools/
├─ check.py                          一致性检查
├─ codex-canvas-launcher.ps1         Codex 用的画布工具启动小脚本
├─ update-plugin.ps1                 Codex 检查并更新插件
└─ register-auto-update.ps1          注册 / 撤销 Codex 自动更新的定时任务
```

## 给维护者

- 改完任何东西，在仓库根目录运行 `python -B tools/check.py`，全部通过再发布。
- 发新版要改 3 处版本号，必须一致：`.claude-plugin/marketplace.json` 里的插件条目、插件的 `.claude-plugin/plugin.json`、`.codex-plugin/plugin.json`。
- 画布工具的版本号单独管：画布代码或依赖有变化时才改，见 [canvas-mcp/README.md](plugins/shanggu-film-pipeline-fqllg/canvas-mcp/README.md)「给维护者」。
- 画布规则只改 `canvas-mcp/rules/RULES.md`，再运行 `canvas-mcp/scripts/build_adapters.py` 生成画布 skill。规则里涉及引用写法、画布限制的改动，同步改 `shared/素材引用写法.md` 和 `shared/Seedance平台.md`。
- 平台限额、任务类型、引用写法这类几个 skill 都要用的知识，只写在 `shared/` 里，各 skill 指过去，不要再各抄一份。
- 深度视频转换工具的安装包不放进仓库（GitHub 不收超过 100 MB 的单个文件），放在发布页（Releases）`depth-tool-<版本>` 这个标签下。换新版时：重新打包上传，再改 `skills/video-depth-rerender/scripts/depth-tool-package.json` 里的版本、下载地址、大小和 SHA256（文件的校验码，用来确认下载的文件没被改过）。安装包没上传或这几项对不上，别人安装时会下载失败或校验不通过。
- 剧本资料（`references/风起玲珑骨/剧本/`）不要手改；换行规则由 `.gitattributes` 固定，改坏了剧本校验会报错。
- 仓库别放在太深的文件夹里。Windows 默认只认 260 个字符以内的完整路径，最长的剧本 PDF 路径已接近 200 字；超出后剧本校验会报"PDF 找不到"，其实是路径太长。

## 许可与剧本资料

代码和规则文字使用 MIT 许可，见 [LICENSE](LICENSE)。

`plugins/shanggu-film-pipeline-fqllg/skills/horizontal-cinematic-prompt-agent-v2/references/风起玲珑骨/` 下的剧本资料（定稿 PDF、逐集正文、场次索引、人物表演圣经）**不在 MIT 许可范围内**，版权归原权利人。

`plugins/shanggu-film-pipeline-fqllg/skills/video-rephotography/references/scenario-original-prompt.txt` 是第三方公开发布的提示词原文副本，同样不在 MIT 许可范围内，版权归原作者（来源见该 skill 的 README）。

发布页上的深度视频转换工具安装包同样不在 MIT 许可范围内。它带有第三方组件：FFmpeg（GPL v3 许可）、Depth Anything V2 Small 模型（Apache-2.0 许可）、PyTorch 等，许可说明和源码地址在安装包的 `licenses/` 文件夹里。

## 来源

本仓库由下面 5 个仓库合并而来，括号里是合并时的版本：

- [horizontal-cinematic-prompt-agent-plugin](https://github.com/pencil102411-cell/horizontal-cinematic-prompt-agent-plugin)（`b96e76a`）
- [xuanshang-canvas](https://github.com/pencil102411-cell/xuanshang-canvas)（`2e82965`）
- [blender-greybox-previs](https://github.com/pencil102411-cell/blender-greybox-previs)（`8ee5329`）
- [video-local-edit](https://github.com/pencil102411-cell/video-local-edit)（`64feb23`）
- [video-rephotography](https://github.com/pencil102411-cell/video-rephotography)（`b3104da`）

提示词插件以前的更新记录见 [docs/history/](docs/history/horizontal-cinematic-prompt-agent-v2-CHANGELOG.md)。
