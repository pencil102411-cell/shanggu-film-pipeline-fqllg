"""玄上画布插件的 MCP 服务。

这一层只负责把核心库包装成工具；规则都在 core 里执行。
"""

import logging
import re
import sys
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from .. import __version__
from ..core.errors import CanvasError
from ..core.service import CanvasService

WORKFLOW = """\
这是「玄上无限画布」插件，用来操作用户电脑上正在运行的画布。所有请求都经过用户本机的画布，用的是画布里登录的账号和积分。

必须遵守下面的规则（大部分由插件代码强制执行，违反时工具会拒绝并说明原因）：
"""


def _load_rules() -> str:
    try:
        text = resources.files("xuanshang_canvas").joinpath("RULES.md").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        # 开发时直接从源码目录运行：规则源文件在仓库根目录 rules/RULES.md
        source = Path(__file__).resolve().parents[3] / "rules" / "RULES.md"
        text = source.read_text(encoding="utf-8") if source.exists() else ""
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)


service = CanvasService()
mcp = MCPServer(
    name="xuanshang-canvas",
    title="玄上画布插件",
    version=__version__,
    instructions=WORKFLOW + _load_rules(),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)

ProjectArg = Annotated[str, Field(description="项目名称或项目 ID（用 list_projects 查）")]
def _fail(exc: Exception) -> ToolError:
    if isinstance(exc, CanvasError):
        return ToolError(exc.message)
    return ToolError(f"插件内部出错（{type(exc).__name__}）：{exc}。请把这段信息告诉插件维护者。")


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 统一转成给用户看的错误
        raise _fail(exc) from exc


# ---------------------------------------------------------------------- 只读工具


@mcp.tool(annotations=READ_ONLY)
def canvas_status(
    port: Annotated[int | None, Field(description="同时开着多个画布时，用它选定要用的那个（端口号见上次返回的「可选画布」）")] = None,
) -> dict[str, Any]:
    """查看画布是否在运行、是哪个程序（无限画布/内部版）、端口、版本是否兼容、项目数量。开始操作前先调一次。"""
    return _safe(lambda: service.status(port))


@mcp.tool(annotations=READ_ONLY)
def list_projects() -> dict[str, Any]:
    """列出画布里的项目（名称、ID、节点数）。"""
    return _safe(lambda: {"项目": service.list_projects()})


@mcp.tool(annotations=READ_ONLY)
def get_graph_summary(project: ProjectArg) -> dict[str, Any]:
    """项目节点摘要：每个视频节点的名字、参数、按顺序列出的接入素材（图片1、视频1……）、最近任务状态、
    是否已有生成好的视频（可以当参考）；以及认证图片节点、认证视频节点的名字和 ID。"""
    return _safe(lambda: service.graph_summary(project))


@mcp.tool(annotations=READ_ONLY)
def list_certified_groups(project: ProjectArg) -> dict[str, Any]:
    """项目的认证分组，以及组内每个素材（图片、视频）的认证状态（向玄上实时查）、是否已经放到画布上。"""
    return _safe(lambda: service.certified_groups(project))


@mcp.tool(annotations=READ_ONLY)
def get_task(
    project: ProjectArg,
    task_id: Annotated[str | None, Field(description="任务 ID")] = None,
    node: Annotated[str | None, Field(description="节点名或节点 ID；给了就查这个节点最近一次任务")] = None,
) -> dict[str, Any]:
    """查某个任务，或某个节点最近一次任务的状态、进度和输出文件。只在用户问进度时调用，不要反复轮询。"""
    return _safe(lambda: service.get_task(project, task_id, node))


# ---------------------------------------------------------------------- 写入工具


@mcp.tool(annotations=WRITE)
def create_project(
    name: Annotated[str, Field(description="新项目的名称，比如「第08集-场10」。不能和已有项目重名")],
    description: Annotated[str | None, Field(description="项目说明，可不填")] = None,
) -> dict[str, Any]:
    """在画布里新建一个空项目。已经有同名项目时会拒绝（避免以后选错项目），请换个名字或直接用原来的项目。"""
    return _safe(lambda: service.create_project(name, description))


@mcp.tool(annotations=WRITE)
def create_certified_group(
    project: ProjectArg,
    name: Annotated[str, Field(description="新认证分组的名称，比如「人物」「场景」「参考视频」。不能和这个项目里已有的分组重名")],
    description: Annotated[str | None, Field(description="分组说明，可不填")] = None,
) -> dict[str, Any]:
    """在项目里新建一个认证分组（玄上那边也会同时建好），之后上传认证素材时选它。
    注意：玄上没有删除分组的接口，建了就删不掉，名字要先和用户确认。同名分组已存在时会拒绝。"""
    return _safe(lambda: service.create_certified_group(project, name, description))


@mcp.tool(annotations=WRITE)
def upload_certified_image(
    project: ProjectArg,
    file_path: Annotated[str, Field(description="本地图片的完整路径，如 C:\\素材\\司徒陌-面部.png")],
    group: Annotated[str, Field(description="认证分组名或分组 ID（用 list_certified_groups 查）")],
    display_name: Annotated[str | None, Field(description="放到画布上时显示的名字，不填就用原文件名")] = None,
) -> dict[str, Any]:
    """本地图片按原质量上传并认证（JPG/PNG/WEBP/BMP/GIF）。返回素材 ID、存储去向、上传核对结果、认证状态。
    长边超过 6000px 的图照样上传，画布会自动缩到长边 5800px（JPEG），结果的「自动缩小」里会写原图和缩小后的尺寸，要转告用户。
    上传后要再用 add_certified_asset_node 放到画布上。"""
    return _safe(lambda: service.upload(project, file_path, group, display_name, "image"))


@mcp.tool(annotations=WRITE)
def upload_certified_video(
    project: ProjectArg,
    file_path: Annotated[str, Field(description="本地参考视频的完整路径（MP4 或 MOV），如 D:\\预演\\16-20-镜127.mp4")],
    group: Annotated[str, Field(description="认证分组名或分组 ID（用 list_certified_groups 查）")],
    display_name: Annotated[str | None, Field(description="放到画布上时显示的名字，不填就用原文件名")] = None,
) -> dict[str, Any]:
    """本地参考视频按原文件上传并认证（不转码、不剪辑）。返回素材 ID、存储去向、大小核对结果、认证状态。
    本地参考视频必须先认证才能接到视频节点上；画布上已生成的视频不用这一步。认证完再用 add_certified_asset_node 放到画布上。"""
    return _safe(lambda: service.upload(project, file_path, group, display_name, "video"))


@mcp.tool(annotations=WRITE)
def add_certified_asset_node(
    project: ProjectArg,
    asset_ids: Annotated[list[str], Field(description="要放到画布上的认证素材 ID 列表（图片、视频都行）")],
    display_names: Annotated[
        list[str] | None, Field(description="和 asset_ids 一一对应的显示名；不填就用上传时记下的原始中文名")
    ] = None,
    allow_duplicate: Annotated[bool, Field(description="画布上已经有这个素材的节点时，是否还要再放一个")] = False,
) -> dict[str, Any]:
    """把已认证的素材（图片或视频）放到画布上，自动找空位，排成一列。只接受「已认证」的素材。"""
    return _safe(lambda: service.add_certified_nodes(project, asset_ids, display_names, allow_duplicate))


@mcp.tool(annotations=WRITE)
def create_video_node(
    project: ProjectArg,
    name: Annotated[str, Field(description="节点名字；和已有视频节点重名时自动加 -v2、-v3")],
    prompt: Annotated[str, Field(description="提示词。用 (图片N)、(视频N) 引用素材（半角括号，和画布一致）；@图片N、全角（图片N）会自动转成半角")],
    image_nodes: Annotated[
        list[str] | None, Field(description="按顺序排列的图片节点（节点名或 ID），第一个就是 (图片1)")
    ] = None,
    video_nodes: Annotated[
        list[str] | None,
        Field(description="按顺序排列的视频节点（节点名或 ID），第一个就是 (视频1)。可以是认证过的参考视频，也可以是画布上已生成的视频"),
    ] = None,
    duration: Annotated[int | None, Field(description="时长（秒）。Seedance 2.5 可选 4–30，-1 表示自动；不填用默认 5")] = None,
    ratio: Annotated[str | None, Field(description="画面比例：adaptive、21:9、16:9、4:3、1:1、3:4、9:16；不填用默认 21:9")] = None,
    resolution: Annotated[str | None, Field(description="draft（样片）、480p、720p、1080p；不填用默认 draft")] = None,
    seed: Annotated[int | None, Field(description="随机种子，-1 表示随机；不填用默认 1")] = None,
    model: Annotated[str | None, Field(description="不填用默认 Doubao-Seedance-2.5")] = None,
    seedance_mode: Annotated[
        str | None, Field(description="multimodal（多模态参考，默认）、first-frame、first-last-frame、video-edit、video-extend")
    ] = None,
    output_format: Annotated[str | None, Field(description="mp4（默认）或 mov")] = None,
    web_search: Annotated[bool | None, Field(description="是否开联网搜索，默认关")] = None,
) -> dict[str, Any]:
    """新建 Seedance 视频生成节点并连好素材。会检查：引用格式（自动统一成画布的 (图片N) 写法）、引用编号和接入素材是否对得上、
    素材是否已认证/已生成、参数是否合规，以及全文每一处素材编号是否都写成画布能识别的 (图片N)/(视频N)（漏括号、省略、范围写法都会拒绝并指出位置）。
    建完分别报告「保存核对」和「引用格式检查」。不会提交生成。"""
    overrides = {
        "duration": duration,
        "ratio": ratio,
        "resolution": resolution,
        "seed": seed,
        "model": model,
        "seedanceMode": seedance_mode,
        "outputFormat": output_format,
        "webSearch": web_search,
    }
    return _safe(lambda: service.create_video_node(project, name, prompt, image_nodes, video_nodes, overrides))


@mcp.tool(annotations=WRITE)
def submit_generation(
    project: ProjectArg,
    node: Annotated[str, Field(description="要提交的视频节点（节点名或 ID）")],
    allow_unrecognized_refs: Annotated[
        bool,
        Field(description="提示词里有画布认不出的素材编号时会拒绝提交。只有用户确认那些地方本来就不是引用素材时才填 true；平时不填"),
    ] = False,
) -> dict[str, Any]:
    """提交生成任务（会花积分），调用后直接提交，不再弹确认。只在用户明确要求生成这个节点时调用，不要自己主动提交。
    同一节点已有任务在跑时会拒绝；提示词里有画布认不出的素材编号（漏括号等）时也会拒绝，并给出位置。提交后只返回任务 ID，不会自动盯进度。"""
    return _safe(lambda: service.submit_generation(project, node, allow_unrecognized_refs))


@mcp.tool(annotations=WRITE)
def create_final_video(
    project: ProjectArg,
    task_id: Annotated[str | None, Field(description="样片任务 ID")] = None,
    node: Annotated[str | None, Field(description="视频节点名或 ID；给了就用这个节点最近一次成功的样片")] = None,
) -> dict[str, Any]:
    """把 Seedance 2.5 样片转成 1080p 成片（会花积分），调用后直接提交，不再弹确认。只在用户明确要求转成片时调用。
    画布会在样片节点旁边新建「成片生成」节点。"""
    return _safe(lambda: service.create_final_video(project, task_id, node))


def main() -> None:
    # 每个 HTTP 请求都打一行日志太吵，只留警告和错误。
    for name in ("httpx2", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if sys.platform == "win32":
        # 让报错信息里的中文在 Windows 控制台不乱码（stdout 是 MCP 协议通道，只改 stderr）。
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if "--check" in sys.argv[1:]:
        # 装完自检：不启动 MCP 服务，只连一次画布、打印结果。顺便把依赖提前装好。
        import json

        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        result = service.status()
        print(f"玄上画布插件 {__version__} 已就绪。")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("已连接") else 1)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
