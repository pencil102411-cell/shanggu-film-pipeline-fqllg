# Blender 灰模预演（blender-greybox-previs）

给 AI Agent（Claude Code、Codex 等）用的技能：按平面图在本机 Blender 搭建**尺寸准确的灰模场景**，摆放**彩色人偶**（头身分开、无四肢，看得出朝向）、编排走位和运镜，导出 **21:9、24 帧/秒**的灰模预演视频，作为 Seedance 2.5 的白模参考，用来锁定人物调度、空间位置、构图和运镜。

## 安装

本技能已并入「上古影视工作流-FQLLG」插件，装插件就带上了，安装方法见仓库根目录的 [README](../../../../README.md)。**插件形式下不要再把本文件夹复制到 `~/.claude/skills` 或 `~/.codex/skills`**，否则会出现两份同名技能。

需要先装好 Blender（4.2 及以上）、Python 3.9 及以上、Pillow（`python -m pip install pillow`）、FFmpeg。第一次使用时运行一次 `previs.py setup`，它会自动寻找 Blender 和 FFmpeg 并实测一次渲染。详细说明和可选的 Blender MCP 见 [references/安装与MCP.md](references/安装与MCP.md)。

## 使用

对 Agent 说："用灰模预演，按这张平面图和分镜做一条预演视频"，然后把平面图和分镜发给它。Agent 会分 3 次请你确认：

1. **尺寸清单**：场景大小、层高、门窗、家具对不对
2. **灰模效果**：俯视叠图和人眼视角图，空间对不对
3. **分镜执行表 + 俯视走位图**：人物怎么走、镜头怎么拍

确认后，它会出低清预览让你改，满意后导出正式版。

## 文件结构

```
SKILL.md                给 Agent 读的流程总纲
references/             参数表写法、运镜规则、交付规范、踩坑记录、安装说明
scripts/previs.py       总命令（普通 Python 运行）
scripts/bl_main.py      在 Blender 里运行的部分
scripts/pv/             场景、人物、相机、检查、渲染模块
scripts/probe_env.py    环境实测
templates/              分镜模板、尺寸清单模板、示例参数表
agents/openai.yaml      Codex 显示用的信息
```

快速体验（在你自己的工作文件夹里运行，测试项目会建在当前文件夹；`<技能目录>` 换成本 README 所在文件夹的完整路径）：

```
python -B "<技能目录>/scripts/previs.py" init 我的测试 --example
python -B "<技能目录>/scripts/previs.py" preview 我的测试
```

## 许可证

[MIT](LICENSE)
