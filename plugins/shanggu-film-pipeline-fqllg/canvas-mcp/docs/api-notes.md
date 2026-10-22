# 画布内部接口记录（第 0 步）

记录时间：2026-10-15。依据：玄上内部版构建 20260923203739 的后台代码（`resources\app\apps\server\dist`）和实测。玄上无限画布（构建 20260923203516）是同一套代码的另一个品牌，待实测。

画布没有官方插件接口，下面都是画布界面自己用的本地接口，升级后可能变化。插件启动时会做兼容性检查（`CanvasService._check_compat`）。

## 1. 找到画布

- 后台进程：`node.exe ...\resources\app\apps\server\dist\index.js`（Tauri 启动器把程序解压到 `%TEMP%\ai-canvas-*-standalone-*`）。
- 程序名：同目录 `resources\app\brand.json` 的 `appName`（如「玄上内部版」）。构建号在启动器 exe 文件名里（14 位数字）。
- 端口：启动器模式默认从 56888 开始找空闲端口（最多往后 200 个），开发模式 48051。只监听 127.0.0.1。
- 验证：`GET /api/projects` 返回 `{"success": true, ...}`。
- 数据目录：`%APPDATA%\XuanshangCanvas\server-settings.json` 的 `data_dir`（本机是 `Documents\xuanshang`）。

## 2. 通用约定

- 返回格式：`{"success": true, "data": ...}`；失败时 `{"success": false, "error": "...", "code": "...", "errors": [{message, code}]}`。
- 插件只用 `GET` 和下面列出的 `POST`，不用 `PUT /graph` 和任何删除接口（规则 1）。

## 3. 用到的接口

| 用途 | 接口 | 说明 |
|---|---|---|
| 项目列表 | `GET /api/projects` | 每项含 `id`、`name`、`overview`（节点数等）、`certifiedAssetGroups`、`cacheDir`（项目文件夹，任务输出路径相对它） |
| 读图 | `GET /api/projects/:id/graph` | `{projectId, nodes, edges, viewport, settings}`。节点 `{id, type, parentId?, ui:{x,y,width,height,nodeType,label,hidden?}, data}`；连线 `{id, source, target}`。分组里的节点坐标相对分组 |
| 节点类型 | `GET /api/nodes` | 每种节点的 `inputs`/`outputs`/`dataSchema`。视频生成节点 `video-generation` 输入：图片 ≤30、视频 ≤10、音频 ≤10 |
| 增量加节点 | `POST /api/projects/:id/graph/items` | `{mutationId, nodes, edges}`，单次最多 100 节点、200 连线。`mutationId` 相同且内容相同会当作重放。服务端按连线顺序补 `inputAssetOrder`。成功后广播 `graph:items-added`，开着的界面会实时合并 |
| 任务列表 | `GET /api/projects/:id/tasks?limit=500` | 最新在前，最多 500 |
| 单个任务 | `GET /api/projects/:id/tasks/:taskId` | `{id, nodeId, status, progress, params, result:{outputAssetIds, outputPaths, providerUrl, metadata:{draft, seed, xuanshangDraftTaskId}}, createdAt, completedAt}` |
| 提交生成 | `POST /api/projects/:id/tasks` | `{nodeId}`。服务端从图里现编译参数和素材；同一节点有排队/运行中的任务返回 409 |
| 样片转成片 | `POST /api/projects/:id/tasks/create-final-video` | `{originalTaskId}`。要求：样片任务成功、Seedance 2.5、7 天内。画布会在样片节点右边新建 `generation-observation` 节点「成片生成」。成片固定 1080p、MP4，沿用样片提示词 |
| 认证分组 | `POST /api/certified-assets/groups/list` | `{projectId, providerId:"xuanshang"}`。分组跟随项目保存在 project.json |
| 新建分组 | `POST /api/certified-assets/groups` | `{projectId, name, providerId}`（插件第一版没开放，测试时用） |
| 查分组里的素材 | `POST /api/certified-assets/list-cloud` | `{providerId, filter:{groupIds:[...]}, pageNumber, pageSize}`，向玄上实时查，一次几秒。`/list` 只读本地缓存，经常是空的 |
| 查单个素材 | `POST /api/certified-assets/get` | `{id, projectName:"default", providerId}`，状态 `Processing` / `Active` / `Failed` |
| 上传并认证 | `POST /api/certified-assets/upload` | multipart，**表单字段必须在文件前面**：`providerId`、`groupId`、`assetType`（Image/Video/Audio）、`projectName`，然后 `file`。返回 `{id, url, localPath, hosting}` |

## 4. 关键行为（规则就是根据这些定的）

- **图片超过 6000px**：上传时画布用 sharp 把长边缩到 5800px，转 JPEG（质量 100）。视频不处理。
- **素材名**：玄上那边的素材名就是上传文件名，超过 32 个字符会被截断（保留扩展名）。插件传输用 ASCII 文件名，节点上显示原始中文名。
- **存储去向**：先传玄上自己的存储（`/v1/files`，`hosting = "xszy"`）；失败时自动改传公共图床链（tfLink → uguu → Litterbox → storage.to），`hosting` 是图床名。
- **认证**：上传后状态是 `Processing`，实测 10 秒内变 `Active`（测试图片和 4 秒测试视频）。
- **提交时素材怎么传**：认证素材用 `asset://素材ID` 直接引用；本地素材和画布生成的结果在提交时再上传（同样先玄上存储、失败走公共图床）。
- **素材编号**：按视频节点 `inputAssetOrder` 排序后，图片、视频、音频分别从 1 编号。
- **提示词里的引用**：画布认 `[（(](图片|视频|音频)N[）)]` 两种括号。
  - **画布界面每次保存图（哪怕只拖动一个节点）都会把所有提示词里的引用改写成半角 `(图片N)`**，所以半角是画布的标准写法。
  - 提交执行时只把 `〔图片N〕`、`【图片N】` 改成 `(图片N)`，其余原样发给 Seedance。
  - 2026-10-15 定：插件跟画布保持一致，统一写半角 `(图片N)`（计划 v3 规则 2 原来要求全角，已改）。
- **编辑会话**：同一项目同一时间只有一个编辑会话，新打开的会顶掉旧的。插件不占编辑会话。
- **界面开着时增量写入是否安全**：实测安全。插件加节点后，界面实时显示；在界面上拖动别的节点触发保存，插件加的节点仍在。
- **Seedance 参考视频限制**：画布代码里写明「不在本地拦截参考视频和音频的格式、大小及时长，由上游校验」，所以具体数值查不到，只能等上传/生成时的报错。画布上传接口允许的类型：mp4、mov。
- **Seedance 2.5 参数**：时长 -1（自动）或 4–30 秒，视频编辑模式只能 -1；分辨率 draft（样片，实际 480p）/480p/720p/1080p；非多模态模式比例只能 adaptive；种子 -1–2147483647；输出 mp4/mov。
