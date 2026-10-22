# 上古影视工作流-FQLLG

横屏真人古装、仙侠、武侠短剧的 Seedance 2.5 视频制作插件，可以装进 Claude Code 和 Codex。

## 包含什么

| skill | 做什么 | 什么时候用 |
|---|---|---|
| `film-pipeline` | 总调度：判断下一步交给哪个 skill，记进度表和交接文件（素材表、接线单） | 按场推进时：说「开这一场」「这场做到哪了」「下一步做什么」 |
| `horizontal-cinematic-prompt-agent-v2` | 把分镜写成可直接生成的 Seedance 提示词，检查、返修；场次记忆；内置《风起玲珑骨》24 集剧本、场次索引和人物表演圣经 | 主线 |
| `blender-greybox-previs` | 按平面图在本机 Blender 搭真实尺寸的灰模，摆人偶、编走位和运镜，导出给 Seedance 当参考的预演视频 | 可选：走位复杂、要锁定站位和运镜时 |
| `xuanshang-canvas` | 操作本机的玄上无限画布：上传认证素材、建视频节点、提交生成、样片转成片（画布工具随插件一起装） | 上画布时 |
| `video-local-edit` | 在已有视频上局部修改，其余部分锁定不变 | 只在你明确要在已有视频上改时 |
| `video-rephotography` | 保留已有视频的表演、对白和节奏，换机位重拍 | 只在你明确要换机位重拍时 |

```
分镜 ─┬─ 不做灰模（默认）──────────┐
      └─ 做灰模 → 灰模预演 ────────┴→ 写生成提示词 → 上画布生成
                                                    ├→ 满意 → 转成片
                                                    ├→ 不满意（默认）→ 返修提示词 → 重新生成
                                                    └→ 明确要改已有视频 → 局部修改 / 换机位重拍 → 上画布
```

分镜本身不在本插件里做。说「开这一场」时，总调度会在当前文件夹建这场的项目文件夹和进度表，之后每一步做完都停下等你确认；提交生成、转成片只在你明确说时才做。示例见 [docs/示例项目/](docs/示例项目/README.md)。

## 安装

最省事的办法：把下面这句话原样发给 Claude Code 或 Codex，它会照这份 README 帮你装好。

> 请帮我安装「上古影视工作流-FQLLG」插件：按 https://github.com/pencil102411-cell/shanggu-film-pipeline-fqllg 这个仓库 README 里「安装」一节操作。装之前先按「装之前：撤掉旧版本」检查，有旧版本的先列出来问我。装完运行自检，把结果告诉我。

### 装之前：撤掉旧版本

以前单独装过这几样的，要先撤掉，否则同一句话会叫出两个同名 skill，画布工具也会启动两份：

- Claude Code：插件 `horizontal-cinematic-prompt-agent-v2@hengping-film-tools`、`xuanshang-canvas@xuanshang-tools`；`~/.claude/skills/` 下的 `blender-greybox-previs`、`video-local-edit`、`video-rephotography`。
- Codex：插件 `horizontal-cinematic-prompt-agent-v2@hengping-film-tools`；`~/.codex/skills/` 下的 `blender-greybox-previs`、`video-rephotography`、`horizontal-cinematic-prompt-agent-v2`；`~/.agents/skills/xuanshang-canvas`；`~/.codex/config.toml` 里旧的 `[mcp_servers.xuanshang-canvas]`（换成下面新的登记）。

建议先挪到一个备份文件夹，不要直接删。分镜 skill（`horizontal-storyboard-design`）不在本插件里，不用撤。

### Claude Code

在普通 PowerShell 窗口里运行（第一条登记插件市场，第二条安装插件）：

```
claude plugin marketplace add pencil102411-cell/shanggu-film-pipeline-fqllg
claude plugin install shanggu-film-pipeline-fqllg@shanggu-film
```

装好后新开一个会话。之后直接说需求就会用到对应的 skill；也可以用全名调用，例如 `/shanggu-film-pipeline-fqllg:blender-greybox-previs`。画布工具随插件一起装，第一次启动会下载约 50MB 依赖；想提前装好，按 [canvas-mcp/README.md](plugins/shanggu-film-pipeline-fqllg/canvas-mcp/README.md)「二、自检」运行一次。

### Codex

在普通 PowerShell 窗口里运行。Codex 的命令行程序藏在 `%LOCALAPPDATA%\OpenAI\Codex\bin\<一串字母>\codex.exe`，第一行先找到它：

```powershell
$codex = (Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Filter codex.exe -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
& $codex plugin marketplace add pencil102411-cell/shanggu-film-pipeline-fqllg
& $codex plugin add shanggu-film-pipeline-fqllg@shanggu-film
```

画布工具在 Codex 里要另外登记（插件里自带的写法没法把等待时间调长，第一次启动装依赖、上传大视频都会超时）：

1. 放一个启动小脚本。它每次去插件缓存里找最新版的画布工具，插件更新后不用改配置：

   ```powershell
   $dst = "$env:LOCALAPPDATA\shanggu-film-pipeline-fqllg"; New-Item -ItemType Directory -Force $dst | Out-Null
   Copy-Item "$env:USERPROFILE\.codex\.tmp\marketplaces\shanggu-film\tools\codex-canvas-launcher.ps1" "$dst\start-canvas.ps1" -Force
   ```

2. 在 `%USERPROFILE%\.codex\config.toml` 末尾加上这段（`你的用户名` 换成实际的，用正斜杠）。已经有 `[mcp_servers.xuanshang-canvas]` 的，换掉旧的那段：

   ```toml
   [mcp_servers.xuanshang-canvas]
   command = "powershell"
   args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:/Users/你的用户名/AppData/Local/shanggu-film-pipeline-fqllg/start-canvas.ps1"]
   startup_timeout_sec = 120
   tool_timeout_sec = 300
   ```

3. 自检，顺便把依赖提前装好（画布开着时显示「已连接」）：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\shanggu-film-pipeline-fqllg\start-canvas.ps1" --check
   ```

4. 重启 Codex。在 Codex 里用 `$film-pipeline`、`$horizontal-cinematic-prompt-agent-v2` 这样的写法点名调用 skill。

### 用到这些功能时，电脑上还要有

- **画布**：玄上无限画布（开着并登录），以及 uv（画布工具运行要用的小工具）。没有 uv 时在 PowerShell 里运行 `winget install --id=astral-sh.uv -e`。
- **灰模**：Blender 4.2 及以上、Python 3.9 及以上、Pillow、FFmpeg。第一次用时运行灰模的 `setup`，见 [安装与MCP.md](plugins/shanggu-film-pipeline-fqllg/skills/blender-greybox-previs/references/安装与MCP.md)。

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

也可以运行 `tools/update-plugin.ps1`，它会先比对版本，有新版才装。想让 Codex 自动更新，运行 `tools/register-auto-update.ps1` 注册一个 Windows 定时任务（每次登录和每天中午 12 点各检查一次）；不想要了加 `-Remove` 再运行一次即可撤销。更新后新开会话才生效。

## 仓库结构

```
.claude-plugin/marketplace.json      Claude Code 插件市场
.agents/plugins/marketplace.json     Codex 插件市场
plugins/shanggu-film-pipeline-fqllg/
├─ .claude-plugin/plugin.json        Claude Code 插件清单
├─ .codex-plugin/plugin.json         Codex 插件清单
├─ .mcp.json                         Claude Code 启动画布工具的配置
├─ skills/                           6 个 skill（总调度 + 5 个工作 skill）
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
- 剧本资料（`references/风起玲珑骨/剧本/`）不要手改；换行规则由 `.gitattributes` 固定，改坏了剧本校验会报错。
- 仓库别放在太深的文件夹里。Windows 默认只认 260 个字符以内的完整路径，最长的剧本 PDF 路径已接近 200 字；超出后剧本校验会报"PDF 找不到"，其实是路径太长。

## 许可与剧本资料

代码和规则文字使用 MIT 许可，见 [LICENSE](LICENSE)。

`plugins/shanggu-film-pipeline-fqllg/skills/horizontal-cinematic-prompt-agent-v2/references/风起玲珑骨/` 下的剧本资料（定稿 PDF、逐集正文、场次索引、人物表演圣经）**不在 MIT 许可范围内**，版权归原权利人。

`plugins/shanggu-film-pipeline-fqllg/skills/video-rephotography/references/scenario-original-prompt.txt` 是第三方公开发布的提示词原文副本，同样不在 MIT 许可范围内，版权归原作者（来源见该 skill 的 README）。

## 来源

本仓库由下面 5 个仓库合并而来，括号里是合并时的版本：

- [horizontal-cinematic-prompt-agent-plugin](https://github.com/pencil102411-cell/horizontal-cinematic-prompt-agent-plugin)（`b96e76a`）
- [xuanshang-canvas](https://github.com/pencil102411-cell/xuanshang-canvas)（`2e82965`）
- [blender-greybox-previs](https://github.com/pencil102411-cell/blender-greybox-previs)（`8ee5329`）
- [video-local-edit](https://github.com/pencil102411-cell/video-local-edit)（`64feb23`）
- [video-rephotography](https://github.com/pencil102411-cell/video-rephotography)（`b3104da`）

提示词插件以前的更新记录见 [docs/history/](docs/history/horizontal-cinematic-prompt-agent-v2-CHANGELOG.md)。
