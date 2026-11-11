# video-depth-rerender

**深度视频重渲染**：把一条已有的视频转成深度视频（只留下画面里各处远近层次的黑白灰视频），再把它当参考视频重新生成，镜头和动作跟着原片走，人物和场景换成新的参考图。

## 能做什么

- 检查本机有没有「离线深度视频」工具；没有时说明要装什么、多大、装到哪，用户同意后才下载安装。
- 把视频（整条或其中一段）转成深度视频，核对时长、尺寸、帧率、大小是否符合 Seedance 参考视频的要求。
- 列出要换成的人物和场景参考图，向用户确认对应关系。
- 写一张深度交接卡，交给提示词 skill 写提示词、画布 skill 上传和生成。

本 skill 不写提示词，不提交生成，也不保证新的一条和原片逐帧一致。交接卡里建议的参考声明是仿照灰模参考视频写的，还没有出片验证。

## 什么时候会用到

只认口令：说了「深度视频」「转深度」「深度重渲染」才用。只是给了视频、说哪里不对，或只说要换人物换场景，都不会走这条路。

## 安装

本技能是「上古影视工作流-FQLLG」插件的一部分，装插件就带上了，安装方法见仓库根目录的 [README](../../../../README.md)。

转换工具「离线深度视频」不在插件里（它有 800 多 MB）。第一次用时脚本会先在本机找，找到就直接用；找不到再问你要不要装。只支持 Windows。

自己检查：在普通 PowerShell 窗口运行下面这条，它只查找、不安装：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<技能目录>\scripts\depth-tool.ps1" check
```

## 使用示例

```text
把这条视频转深度，做深度重渲染：人物换成我给的这张人物图，场景换成这张场景图。
```

## 文件说明

| 文件 | 用途 |
| --- | --- |
| [SKILL.md](SKILL.md) | 适用边界和每一步怎么做 |
| [agents/openai.yaml](agents/openai.yaml) | Codex 显示名称及默认调用提示 |
| [references/交接卡模板.md](references/交接卡模板.md) | 深度交接卡的样式 |
| [scripts/depth-tool.ps1](scripts/depth-tool.ps1) | 检查、安装、转换三个动作 |
| [scripts/depth-tool-package.json](scripts/depth-tool-package.json) | 安装包的下载地址、大小和校验指纹 |

## 工具的来源和许可

安装包是「离线深度视频」0.3.1 的免安装版，里面带着：

- 深度模型 Depth Anything V2 Small（Apache-2.0 许可）。
- FFmpeg 8.1（gyan.dev 编译的 essentials 版，GPL v3 许可）。
- PyTorch、OpenCV 等运行库（各自的许可）。

各组件的许可说明和源码地址在安装后的 `licenses` 文件夹里。
