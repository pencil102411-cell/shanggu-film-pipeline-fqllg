# 安装与 MCP

## 需要的软件

| 软件 | 版本 | 说明 |
|---|---|---|
| Blender | 4.2 及以上（在 5.2.1 上测试） | 不需要装插件；便携版也行 |
| Python | 3.9 及以上 | 运行 `previs.py` |
| Pillow | 任意较新版本 | Python 画图库：`python -m pip install pillow` |
| FFmpeg + ffprobe | 任意较新版本 | 合成视频、核对视频规格 |

## 安装技能

本技能随「上古影视工作流-FQLLG」插件一起安装，不要再复制到 `~/.claude/skills` 或 `~/.codex/skills`（会出现两份同名技能）。

第一次使用时运行一次：

```
python -B "<技能目录>/scripts/previs.py" setup
```

它会自动寻找 Blender 和 FFmpeg，把路径记到 `~/.blender-greybox-previs/config.json`，并实测一次后台渲染。

找不到软件时，手动指定路径：

```
python -B "<技能目录>/scripts/previs.py" setup --blender "C:\path\to\blender.exe" --ffmpeg "C:\path\to\ffmpeg.exe" --ffprobe "C:\path\to\ffprobe.exe"
```

也可以用环境变量 `BLENDER_EXE`、`FFMPEG_EXE`、`FFPROBE_EXE`，或者用 `PREVIS_CONFIG` 指向别的配置文件。

## Blender MCP（可选）

MCP 能让 Agent 直接操作**开着的 Blender 窗口**：截取视口图、读取物体位置。本技能的主流程用命令行就能走完，MCP 只是辅助。

> ⚠️ MCP 会让 Agent 在 Blender 里直接执行代码。只在本机使用，不要开放给局域网。

推荐社区版 [mcp-for-blender](https://github.com/ahujasid/mcp-for-blender)（原名 blender-mcp，MIT 许可）。

### 1. 安装 MCP 服务（Windows 示例）

用一个独立的 Python 虚拟环境装，可以避开杀毒软件锁文件的问题：

```
uv venv C:\Users\<你>\tools\blender-mcp-venv --python <Python 3.10+ 路径>
uv pip install --python C:\Users\<你>\tools\blender-mcp-venv\Scripts\python.exe mcp-for-blender
```

没有 uv 时，用 `python -m venv` 加 `pip install mcp-for-blender` 也一样。

### 2. 装 Blender 插件并启用

```
C:\Users\<你>\tools\blender-mcp-venv\Scripts\mcp-for-blender.exe install-addon --addons-dir "%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons"
<blender.exe> --background --python-expr "import bpy; bpy.ops.preferences.addon_enable(module='blender_mcp'); bpy.ops.wm.save_userpref()"
```

插件默认随 Blender 启动自动开服务（端口 9876），默认不上传使用数据。

### 3. 登记到 Agent

**Claude Code：**

```
claude mcp add --scope user blender -- "C:\Users\<你>\tools\blender-mcp-venv\Scripts\mcp-for-blender.exe"
```

**Codex**（加到 `~/.codex/config.toml`）：

```toml
[mcp_servers.blender]
command = 'C:\Users\<你>\tools\blender-mcp-venv\Scripts\mcp-for-blender.exe'
args = []
startup_timeout_sec = 30
```

登记后要**新开一个对话**，MCP 工具才会出现。

### 4. 在流程里怎么用

1. `previs.py open <项目目录>` 在 Blender 窗口里打开最新版本。
2. 用 MCP 截取视口图，或者读物体位置（场景信息工具、执行代码工具）。
3. 用户在窗口里拖动了家具、墙之类的静态物体：读出新位置，**写回 scene.json**，再重新生成。
4. 人物和相机的动画是逐帧烘焙的，在窗口里拖它们只会改到当前那一帧，不要用这种方式修改走位和运镜。
