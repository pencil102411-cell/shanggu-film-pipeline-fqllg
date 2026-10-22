# 玄上画布插件（xuanshang-canvas）

让 Claude Code、Codex 等 AI 工具，用**同一套规则**操作你电脑上正在运行的「玄上无限画布」（也支持玄上内部版）：新建项目和认证分组、查项目、上传认证图片和参考视频、把素材放到画布上、建 Seedance 视频节点、提交生成、样片转成片、查进度。

- **不用每次启动**：在 AI 工具里装一次，以后打开 AI 工具就会在后台自动启动插件，插件再自己去找开着的画布。
- **不碰你的密钥**：插件不读取、不保存任何 API Key。所有请求都经过你本机的画布，用的是画布里登录的账号和积分。
- **只在你下指令时花积分**：提交生成、转成片只在你明确说要生成时才执行，不会自己主动提交。

---

## 一、安装

画布工具已经并入「上古影视工作流-FQLLG」插件，装插件就一起带上了，不用单独装。安装方法见仓库根目录的 [README](../../../README.md)。

准备：

- Windows 电脑，装好并能正常打开「玄上无限画布」，在画布里登录自己的账号。
- 电脑上要有 uv（画布工具运行要用的小工具）。没有时，在 PowerShell 里运行 `winget install --id=astral-sh.uv -e` 安装；winget 不可用时改用 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`。装完不用重启，启动脚本会自己去常见位置找 uv。

## 二、自检

Claude Code 装好插件后，在普通 PowerShell 窗口里运行。它会把依赖提前装到插件的数据目录（第一次要下载约 50MB，一两分钟），画布开着时显示「已连接」：

```powershell
$root = (Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw | ConvertFrom-Json).plugins.'shanggu-film-pipeline-fqllg@shanggu-film'[0].installPath
$env:UV_PROJECT_ENVIRONMENT = "$env:USERPROFILE\.claude\plugins\data\shanggu-film-pipeline-fqllg-shanggu-film\venv"
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\canvas-mcp\scripts\start-mcp.ps1" --check
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

画布没开会提示先打开画布，这也说明画布工具本身装好了。Codex 的登记和自检见仓库根目录 [README](../../../README.md)「安装 → Codex」：Codex 里登记的是 `%LOCALAPPDATA%\shanggu-film-pipeline-fqllg\start-canvas.ps1` 这个启动小脚本，它再去插件缓存里找最新版的画布工具；依赖装在同一个文件夹的 `canvas-venv-<版本号>` 里。

---

## 三、日常怎么用

直接用中文跟 AI 说要做什么，例如：

- 「新建一个项目，叫『第09集-场12』」
- 「在第09集-场12 这个项目里建三个认证分组：人物、场景、参考视频」
- 「看看 16-20 测试这个项目里有哪些视频节点」
- 「把 D:\素材\司徒陌-面部.png 传到 16-20 测试项目的人物分组，认证完放到画布上」
- 「把 D:\预演\镜127.mp4 作为参考视频上传认证，放到画布上」
- 「新建一个视频节点，叫『镜127』，接司徒陌两张图和刚才的参考视频，提示词是……」
- 「提交镜127」（直接提交，会花积分）
- 「镜127 的样片好了没有？」「把这个样片转成片」

AI 会按插件的规则来做，做完会告诉你结果、核对情况和需要注意的地方。

---

## 四、插件会替你守住的规则（摘要）

完整规则见 [rules/RULES.md](rules/RULES.md)，这里说最常碰到的几条：

| 规则 | 说明 |
|---|---|
| 只加不改不删 | 只新增节点和连线；要改就新建一个，重名自动加 -v2、-v3，旧的保留 |
| 引用写法跟画布一致 | 统一写成半角 `(图片1)`、`(视频1)`，和画布界面保存后的样子一样；`@图片1`、全角 `（图片1）` 会自动转过来 |
| 每一处引用都带括号 | 正文里写「背景采用图片11」画布认不出，必须写 (图片11)；「图片7、8」「图片1—8」这类省略写法也要展开。插件会逐处检查，指出第几行哪一处 |
| 引用和素材对得上 | 编号不能超过接入的素材数，接入的每个素材都要被引用，否则拒绝创建 |
| 原质量上传 | 按原文件上传并核对大小和尺寸；长边超过 6000px 的图照样上传，画布会自动缩到长边 5800px，结果里会写清楚缩到了多大 |
| 参考视频要认证 | 本地参考视频先上传认证；画布上已经生成好的视频可以直接当参考 |
| 只在你下指令时花积分 | 提交生成、转成片只在你明确要求时执行；同一节点已有任务在跑时拒绝，避免重复扣积分 |
| 提交后不盯进度 | 你问进度时才去查 |

---

## 五、配置项（可选）

不配置也能用。要改默认参数，新建 `C:\Users\你的用户名\AppData\Roaming\xuanshang-canvas\config.json`，只写要改的项：

```json
{
  "video_defaults": {
    "model": "Doubao-Seedance-2.5",
    "seedanceMode": "multimodal",
    "resolution": "draft",
    "ratio": "21:9",
    "seed": 1,
    "outputFormat": "mp4",
    "webSearch": false,
    "duration": 5
  },
  "certify_wait_seconds": 50,
  "size_tolerance": 0.05
}
```

| 配置项 | 意思 | 默认 |
|---|---|---|
| `video_defaults` | 新建视频节点时没指定的参数用这些 | 见上 |
| `canvas_port` | 写死画布端口（一般不用，插件会自己找） | 不写 |
| `certify_wait_seconds` | 上传后最多等认证多少秒 | 50 |
| `size_tolerance` | 上传后大小差多少以内只提示不报错 | 0.05（5%） |

也可以用环境变量：`CANVAS_PORT`、`XUANSHANG_CERTIFY_WAIT_SECONDS`；配置文件位置可用 `XUANSHANG_CANVAS_CONFIG` 指定。

> 等待时间要比 AI 工具自己的等待上限短。Codex 的等待上限在登记画布工具时设置（`tool_timeout_sec`，README 里给的是 300 秒）；如果你把它调得更长，这里也可以跟着调长。

---

## 六、常见问题

**提示「请先打开玄上无限画布」**：画布没开，或者刚开还没启动完。打开画布、等界面出来后再试。

**提示「同时开着 2 个画布」**：比如无限画布和内部版都开着。告诉 AI 用哪个，它会带上端口号选定；只开一个就不会问。

**上传后说「认证中」**：玄上那边认证慢，插件最多等 50 秒就先返回。过一会儿让 AI 用 `list_certified_groups` 查，变成「已认证」后再放到画布上。

**结果里写着「公共图床」**：玄上存储上传失败时，画布会自动改传到公共图床，文件会在公网上。是否继续用这个素材由你决定。

**参考视频上传或生成时报错**：Seedance 对参考视频有格式、时长、大小、分辨率限制（单段最短按 4 秒算、多段合计不超过 30 秒等，见插件的 `shared/Seedance平台.md`）。插件会把画布的原始报错原样给你，照着报错改视频即可。

**提示「画布版本和插件不兼容」**：画布升级后内部接口变了。把报错发给插件维护者。

**Claude Code / Codex 说插件启动失败（比如 Connection closed）**：跟 AI 说「按画布工具 README（插件里的 canvas-mcp/README.md）的自检步骤，重新检查 uv 并运行自检」。自检会把依赖装好并显示具体报错。第一次启动要下载依赖，网络慢时可能超时，自检通过后再新开会话试一次。

---

## 七、已验证的画布版本

| 程序 | 构建号 | 状态 |
|---|---|---|
| 玄上内部版 | 20260923203739 | 已实测：读取、建项目、上传认证、放节点、建视频节点 |
| 玄上无限画布 | 20260923203516 | 和内部版同一套接口，待实测 |

`canvas_status` 会显示当前画布的构建号和是否实测过。

---

## 八、给维护者

画布工具在插件里的位置（`plugins/shanggu-film-pipeline-fqllg/` 下）：

```
.mcp.json                    # Claude Code 启动画布工具的配置
skills/xuanshang-canvas/     # 画布 skill（自动生成，Claude Code 和 Codex 共用）
canvas-mcp/
├── src/xuanshang_canvas/
│   ├── core/                # 核心库：连接画布 + 统一规则，所有写入都经过这里
│   └── mcp_server/          # MCP 服务（所有 AI 工具共用）
├── rules/RULES.md           # 规则源文件（唯一来源）
├── docs/api-notes.md        # 画布内部接口记录
├── tests/                   # 规则检查的测试
├── scripts/                 # start-mcp.ps1 启动画布工具；build_adapters.py 生成画布 skill
├── pyproject.toml           # 直接依赖，固定版本
└── uv.lock                  # 全部间接依赖的固定版本
```

- 改规则只改 `rules/RULES.md`，然后在 `canvas-mcp` 目录运行 `python scripts/build_adapters.py`，重新生成插件里的 `skills/xuanshang-canvas/SKILL.md`；`--check` 只检查是否一致。MCP 服务的使用说明直接读 `RULES.md`。
- 所有 AI 工具都通过 `scripts/start-mcp.ps1` 启动插件。它自己去 uv 的常见安装位置找 uv，再运行 `uv run --frozen --quiet --no-editable --project <插件目录> python -m xuanshang_canvas.mcp_server.server`。不直接写 `uv`，是因为 Windows 上刚装好 uv 时，已经开着的程序（包括 Claude 应用）看不到新的 PATH，会报 Connection closed。
- 为什么画布代码放在插件文件夹里：启动脚本要从插件自己的文件夹运行，插件目录里必须有 Python 源码。
- 依赖目录按版本分开：Claude Code 给的基础位置是 `${CLAUDE_PLUGIN_DATA}/venv`，启动脚本实际用 `venv-<版本号>`。没给基础位置时（比如在 Codex 里），默认用 `%LOCALAPPDATA%\shanggu-film-pipeline-fqllg\canvas-venv-<版本号>`，不放进插件文件夹，因为插件每次更新都会换文件夹。升级时旧版本的会话可能还开着、占用着旧目录里的文件（Windows 会报「另一个程序正在使用此文件」），分开后互不影响。旧版本目录由启动脚本自动删除，但只删「没有任何正在运行的程序来自这个目录」的（用进程列表判断；改名试探不可靠，Windows 上正在用的目录也可能改名成功）。比较路径前先统一格式，因为 Claude Code 传进来的是正斜杠路径。服务用 `python -m` 启动，而不是 venv 里的 exe，同样是为了不锁住需要更新的文件。
- 为什么用 `uv run --frozen --project` 而不是 `uvx --from`：在开着 Windows Defender 的电脑上实测，uvx 在临时目录里装依赖时会被 Defender 锁住 pywin32 的文件而失败（`os error 32`）；装到固定目录（`uv run`、`uv tool install`）没有这个问题。`--frozen` 按 `uv.lock` 装，所有间接依赖的版本也是固定的。
- `start-mcp.ps1` 要保存成带 BOM 的 UTF-8，否则 Windows PowerShell 5.1 读中文会乱码。
- 用 `--no-editable` 把插件代码复制进依赖目录：默认的「可编辑安装」靠一个 .pth 文件记源码路径，中文版 Windows 上的 Python 3.12 及更早版本用 GBK 读这个文件，路径里有中文就读成乱码、找不到代码。`pyproject.toml` 里的 `[tool.uv] cache-keys` 让源码一改就重新打包。
- 依赖升级：改 `pyproject.toml` 后运行 `uv lock`，测完再发布。
- 本地调试：在 `canvas-mcp` 目录运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-mcp.ps1 --check`；或在 Claude Code 里 `claude --plugin-dir <插件文件夹>` 临时加载整个插件。
- 版本号：画布代码或依赖有变化时，改 `pyproject.toml` 和 `src/xuanshang_canvas/__init__.py` 里的版本号并运行 `uv lock`（依赖目录按这个版本号分开，忘了改会和正在运行的旧会话抢同一个目录）。插件本身的版本号按仓库根目录 README 的发版说明改。
- 画布接口细节见 `docs/api-notes.md`。画布升级后先跑 `canvas_status` 看兼容性检查。
