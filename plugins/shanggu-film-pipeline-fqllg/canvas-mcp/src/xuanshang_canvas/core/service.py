"""核心操作。MCP 服务和以后的命令行工具都调用这里，所以不管接的是哪个 AI 工具，行为都一样。"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from . import graph as g
from .client import CanvasClient, probe_canvas
from .config import Settings, data_dir, load_settings
from .discovery import CanvasInstance, find_instances, instance_for_port
from .errors import CanvasApiError, CanvasConnectionError, CanvasError, RuleViolation
from .media import IMAGE_EXTENSIONS, MAX_IMAGE_SIDE, VIDEO_EXTENSIONS, local_image_info, transfer_name, verify_upload
from .rules import KIND_LABEL, build_video_params, canvas_view, check_prompt, compare_fields, dedupe_name, describe_params, find_format_problems

PROVIDER = "xuanshang"
REMOTE_PROJECT = "default"  # 玄上之音那边的 ProjectName，画布固定用 default
VERIFIED_BUILDS = {"20260923203739": "玄上内部版"}
TASK_STATUS = {"queued": "排队中", "running": "生成中", "succeeded": "已完成", "failed": "失败", "cancelled": "已取消"}
CERT_STATUS = {"Active": "已认证（Active）", "Processing": "认证中", "Failed": "认证失败"}
VIDEO_NODE_DEFAULTS = {
    "provider": PROVIDER,
    "bitrateMode": "high",
    "generateAudio": True,
    "priority": 0,
    "returnLastFrame": False,
    "watermark": False,
    "executionExpiresAfter": 172800,
}
PARAM_KEYS = ["model", "seedanceMode", "resolution", "ratio", "duration", "seed", "outputFormat", "webSearch"]


def _fmt_time(ms: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return None


def _short(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + f"……（共 {len(text)} 字）"


class NameStore:
    """规则 5：传输用 ASCII 文件名，画布上显示原始中文名。这里记住素材 ID 对应的显示名。"""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, asset_id: str) -> str | None:
        entry = self._load().get(asset_id)
        return entry.get("display_name") if isinstance(entry, dict) else None

    def save(self, asset_id: str, display_name: str, source: str, transfer: str) -> None:
        with self._lock:
            data = self._load()
            data[asset_id] = {
                "display_name": display_name,
                "source_file": source,
                "transfer_name": transfer,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)


class CanvasService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.names = NameStore(data_dir() / "asset-names.json")
        self._selected_port: int | None = self.settings.canvas_port
        self._instance: CanvasInstance | None = None
        self._client: CanvasClient | None = None
        self._definitions: dict[str, dict[str, Any]] | None = None
        self._compat: dict[str, Any] | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ 连接

    def _reset(self) -> None:
        if self._client:
            self._client.close()
        self._client = None
        self._instance = None
        self._definitions = None
        self._compat = None

    def connect(self, *, require_compatible: bool = True) -> CanvasClient:
        with self._lock:
            if self._client and probe_canvas(self._client.port, timeout=1.5):
                if require_compatible:
                    self._raise_if_incompatible()
                return self._client
            self._reset()
            if self._selected_port:
                instance = instance_for_port(self._selected_port)
                if instance is None:
                    raise CanvasConnectionError(
                        f"端口 {self._selected_port} 上没有找到画布。画布可能关掉了，或者重启后换了端口。"
                        "请确认画布开着；如果是在配置或环境变量 CANVAS_PORT 里写死了端口，请改掉或删掉它。"
                    )
            else:
                found = find_instances()
                if not found:
                    raise CanvasConnectionError("请先打开玄上无限画布：这台电脑上没找到正在运行的画布。打开并登录后再试。")
                if len(found) > 1:
                    listing = "；".join(f"{index}）{item.describe()}" for index, item in enumerate(found, 1))
                    raise CanvasError(
                        f"同时开着 {len(found)} 个画布：{listing}。请问使用者要用哪一个，"
                        "然后调用 canvas_status 并带上 port 参数选定（选一次，这次会话里一直有效）。",
                        code="MULTIPLE_CANVASES",
                        detail=[item.to_dict() for item in found],
                    )
                instance = found[0]
            self._instance = instance
            self._client = CanvasClient(
                instance.port, timeout=self.settings.http_timeout_seconds, upload_timeout=self.settings.upload_timeout_seconds
            )
            self._compat = self._check_compat(self._client)
            if require_compatible:
                self._raise_if_incompatible()
            return self._client

    def select_port(self, port: int) -> None:
        with self._lock:
            if not probe_canvas(port):
                raise CanvasConnectionError(f"端口 {port} 上没有找到画布，请确认端口号。可以先不带 port 调用 canvas_status 看看有哪些画布。")
            self._selected_port = port
            self._reset()

    def _raise_if_incompatible(self) -> None:
        if self._compat and not self._compat["ok"]:
            raise CanvasError(
                "画布版本和插件不兼容，为避免出错已停止操作：" + "；".join(self._compat["problems"]) +
                "。请把这段信息发给插件维护者，或换用 README 里写明已验证的画布版本。",
                code="INCOMPATIBLE_CANVAS",
            )

    def _check_compat(self, client: CanvasClient) -> dict[str, Any]:
        """第一次连上时检查关键接口能不能用。只读，不会改任何东西。"""
        problems: list[str] = []
        try:
            definitions = client.get("/api/nodes")
            by_id = {item["id"]: item for item in definitions if isinstance(item, dict) and "id" in item}
            self._definitions = by_id
            video = by_id.get("video-generation")
            if not video:
                problems.append("画布里没有 Seedance 视频生成节点（video-generation）")
            else:
                inputs = {i.get("type") for i in video.get("inputs") or []}
                if not {"image", "video"} <= inputs:
                    problems.append("视频生成节点不再接受图片/视频输入")
            if "certified-asset" not in by_id:
                problems.append("画布里没有认证素材节点（certified-asset）")
        except CanvasError as exc:
            problems.append(f"读不到节点类型列表：{exc.message}")
        probes = [
            ("POST", "/api/projects/__plugin_compat_probe__/graph/items", {}, 400, "MUTATION_ID_REQUIRED", "增量加节点接口"),
            ("GET", "/api/projects/__plugin_compat_probe__/tasks/__none__", None, 404, "TASK_NOT_FOUND", "查任务接口"),
        ]
        for method, path, body, status, code, label in probes:
            try:
                got_status, got = client.raw_post(path, body) if method == "POST" else client.raw_get(path)
                if got_status != status or not (isinstance(got, dict) and got.get("code") == code):
                    problems.append(f"{label}的返回和预期不一样（HTTP {got_status}：{str(got)[:120]}）")
            except CanvasError as exc:
                problems.append(f"{label}检查失败：{exc.message}")
        try:
            status, got = client.raw_post("/api/certified-assets/groups/list", {})
            if not (isinstance(got, dict) and "projectId" in str(got.get("error", ""))):
                problems.append(f"认证素材接口的返回和预期不一样（HTTP {status}）")
        except CanvasError as exc:
            problems.append(f"认证素材接口检查失败：{exc.message}")
        return {"ok": not problems, "problems": problems}

    def definitions(self) -> dict[str, dict[str, Any]]:
        if self._definitions is None:
            client = self.connect(require_compatible=False)
            self._definitions = {item["id"]: item for item in client.get("/api/nodes")}
        return self._definitions

    # ------------------------------------------------------------------ 读取

    def status(self, port: int | None = None) -> dict[str, Any]:
        if port:
            self.select_port(port)
        try:
            client = self.connect(require_compatible=False)
        except CanvasError as exc:
            result: dict[str, Any] = {"已连接": False, "说明": exc.message}
            if exc.code == "MULTIPLE_CANVASES":
                result["可选画布"] = exc.detail
            return result
        instance = self._instance
        projects = client.get("/api/projects")
        build = instance.build if instance else None
        result = {
            "已连接": True,
            "画布": instance.to_dict() if instance else {"port": client.port},
            "版本兼容": "兼容" if self._compat and self._compat["ok"] else "不兼容",
            "兼容性问题": (self._compat or {}).get("problems") or [],
            "已验证版本": "是" if build in VERIFIED_BUILDS else ("未知（没读到构建号）" if not build else "否，这个构建号还没实测过，用的时候留意报错"),
            "项目数量": len(projects),
            "认证等待上限秒数": self.settings.certify_wait_seconds,
            "配置来源": self.settings.source,
        }
        if self.settings.warnings:
            result["配置提醒"] = self.settings.warnings
        return result

    def list_projects(self) -> list[dict[str, Any]]:
        client = self.connect()
        items = []
        for project in client.get("/api/projects"):
            overview = project.get("overview") or {}
            items.append(
                {
                    "名称": project.get("name"),
                    "ID": project.get("id"),
                    "节点数": overview.get("totalNodes"),
                    "生成节点数": overview.get("generationNodes"),
                    "认证分组数": len(project.get("certifiedAssetGroups") or []),
                    "最近更新": _fmt_time(project.get("updatedAt")),
                }
            )
        return items

    def resolve_project(self, project: str) -> dict[str, Any]:
        client = self.connect()
        items = client.get("/api/projects")
        key = str(project or "").strip()
        if not key:
            raise CanvasError("请指定项目（项目名称或 ID）。可以先用 list_projects 查看。")
        for item in items:
            if item.get("id") == key:
                return item
        matches = [item for item in items if str(item.get("name", "")).strip() == key]
        if not matches:
            matches = [item for item in items if str(item.get("name", "")).strip().lower() == key.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            listing = "；".join(f"{m.get('name')}（ID {m.get('id')}）" for m in matches)
            raise CanvasError(f"有 {len(matches)} 个项目都叫「{key}」：{listing}。请用项目 ID 指定。")
        names = "、".join(str(item.get("name")) for item in items[:30])
        raise CanvasError(f"没找到项目「{key}」。现有项目：{names}")

    def _graph(self, project_id: str) -> dict[str, Any]:
        return self.connect().get(f"/api/projects/{project_id}/graph")

    def _tasks(self, project_id: str) -> list[dict[str, Any]]:
        return self.connect().get(f"/api/projects/{project_id}/tasks", params={"limit": 500})

    def _resolve_node(self, graph: dict[str, Any], ref: str, purpose: str) -> dict[str, Any]:
        key = str(ref or "").strip()
        nodes = graph.get("nodes") or []
        for node in nodes:
            if node.get("id") == key:
                return node
        matches = [node for node in nodes if g.label_of(node) == key]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            listing = "；".join(f"{node['id']}（{node['type']}）" for node in matches[:10])
            raise CanvasError(f"{purpose}「{key}」有 {len(matches)} 个同名节点：{listing}。请用节点 ID 指定。")
        raise CanvasError(f"{purpose}「{key}」在这个项目里没找到。可以先用 get_graph_summary 查看节点名和 ID。")

    def _ordered_inputs(self, node: dict[str, Any], graph: dict[str, Any], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按画布自己的规则算出视频节点接入的素材顺序和编号（图片1、视频1……）。"""
        nodes = graph.get("nodes") or []
        by_id = {item["id"]: item for item in nodes}
        definitions = self.definitions()
        order = (node.get("data") or {}).get("inputAssetOrder") or []
        incoming = [edge for edge in graph.get("edges") or [] if edge.get("target") == node["id"]]

        def sort_key(edge: dict[str, Any]) -> int:
            return order.index(edge["source"]) if edge["source"] in order else len(order) + 1

        incoming.sort(key=sort_key)
        counters = {kind: 0 for kind in g.KINDS}
        latest = g.latest_tasks_by_node(tasks)
        inputs = []
        seen: set[str] = set()
        for edge in incoming:
            source = by_id.get(edge["source"])
            if source is None or source["id"] in seen or source.get("type") == "text-input":
                continue
            seen.add(source["id"])
            if g.is_hidden(source, by_id):
                continue
            kind = g.output_kind(source, definitions)
            if kind is None:
                continue
            counters[kind] += 1
            data = source.get("data") or {}
            entry = {
                "编号": f"{KIND_LABEL[kind]}{counters[kind]}",
                "节点ID": source["id"],
                "节点名": g.label_of(source),
                "类型": kind,
                "来源": "认证素材" if source.get("type") == "certified-asset" else (
                    "画布生成" if g.produces_task_output(source.get("type", "")) else "本地素材"
                ),
            }
            if source.get("type") == "certified-asset":
                entry["认证状态"] = CERT_STATUS.get(str(data.get("status")), data.get("status"))
            elif g.produces_task_output(source.get("type", "")):
                entry["有输出"] = g.has_output(source, latest.get(source["id"]), tasks)
            inputs.append(entry)
        return inputs

    def graph_summary(self, project: str) -> dict[str, Any]:
        proj = self.resolve_project(project)
        graph = self._graph(proj["id"])
        tasks = self._tasks(proj["id"])
        latest = g.latest_tasks_by_node(tasks)
        nodes = graph.get("nodes") or []
        by_id = {node["id"]: node for node in nodes}
        video_nodes, images, videos, others = [], [], [], {}
        for node in nodes:
            node_type = node.get("type")
            data = node.get("data") or {}
            hidden = g.is_hidden(node, by_id)
            if node_type == "video-generation":
                task = latest.get(node["id"])
                video_nodes.append(
                    {
                        "节点ID": node["id"],
                        "节点名": g.label_of(node),
                        "参数": describe_params(data),
                        "接入素材": [f"{i['编号']} = {i['节点名']}" for i in self._ordered_inputs(node, graph, tasks)],
                        "提示词开头": _short(data.get("prompt", ""), 80),
                        "最近任务": {
                            "任务ID": task.get("id"),
                            "状态": TASK_STATUS.get(task.get("status"), task.get("status")),
                            "时间": _fmt_time(task.get("createdAt")),
                        }
                        if task
                        else None,
                        "有生成好的视频（可当参考）": g.has_output(node, task, tasks),
                        **({"已停用": True} if hidden else {}),
                    }
                )
            elif node_type == "certified-asset":
                entry = {
                    "节点ID": node["id"],
                    "节点名": g.label_of(node),
                    "认证状态": CERT_STATUS.get(str(data.get("status")), data.get("status")),
                    "素材ID": data.get("assetId"),
                    **({"已停用": True} if hidden else {}),
                }
                (videos if str(data.get("assetType")).lower() == "video" else images).append(entry)
            elif node_type == "generation-observation":
                task = latest.get(node["id"])
                others.setdefault("成片节点", []).append(
                    {
                        "节点ID": node["id"],
                        "节点名": g.label_of(node),
                        "状态": TASK_STATUS.get((task or {}).get("status"), (task or {}).get("status")),
                        "有生成好的视频（可当参考）": g.has_output(node, task, tasks),
                    }
                )
            else:
                others.setdefault("其他节点数量", {}).setdefault(node_type, 0)
                others["其他节点数量"][node_type] += 1
        return {
            "项目": {"名称": proj.get("name"), "ID": proj["id"]},
            "视频生成节点": video_nodes,
            "认证图片节点": images,
            "认证视频节点": videos,
            **others,
        }

    def _groups(self, project_id: str) -> list[dict[str, Any]]:
        data = self.connect().post("/api/certified-assets/groups/list", {"projectId": project_id, "providerId": PROVIDER})
        return (data or {}).get("items") or []

    def _resolve_group(self, project: dict[str, Any], group: str) -> dict[str, Any]:
        groups = self._groups(project["id"])
        key = str(group or "").strip()
        if not key:
            raise CanvasError("请指定认证分组（分组名或 ID）。可以先用 list_certified_groups 查看。")
        for item in groups:
            if item.get("id") == key:
                return item
        matches = [item for item in groups if str(item.get("name", "")).strip() == key]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            listing = "；".join(f"{m.get('id')}" for m in matches)
            raise CanvasError(f"这个项目里有 {len(matches)} 个分组都叫「{key}」（ID：{listing}），请用分组 ID 指定。")
        names = "、".join(f"{item.get('name')}" for item in groups) or "（这个项目还没有认证分组）"
        raise CanvasError(
            f"项目「{project.get('name')}」里没有叫「{key}」的认证分组。现有分组：{names}。"
            "要新建的话，先问用户确认分组名，再用 create_certified_group 建。"
        )

    # ------------------------------------------------------------------ 新建项目和认证分组

    def create_project(self, name: str, description: str | None = None) -> dict[str, Any]:
        """新建画布项目。同名项目已存在时拒绝：项目名重复后很容易选错。"""
        client = self.connect()
        key = str(name or "").strip()
        if not key:
            raise CanvasError("项目名称不能为空。")
        if len(key) > 100:
            raise RuleViolation(f"项目名称太长了（{len(key)} 个字），请控制在 100 个字以内。")
        same = [item for item in client.get("/api/projects") if str(item.get("name", "")).strip() == key]
        if same:
            raise RuleViolation(
                f"已经有叫「{key}」的项目了（ID {same[0].get('id')}）。项目名重复后很容易选错，请换个名字；"
                "要用原来那个项目就直接用它。"
            )
        created = client.post("/api/projects", {"name": key, "description": (description or "").strip()})
        project_id = created.get("id")
        saved = client.get(f"/api/projects/{project_id}")
        problems = []
        if str(saved.get("name", "")).strip() != key:
            problems.append(f"读回的项目名是「{saved.get('name')}」，和请求的不一样")
        return {
            "项目名": saved.get("name"),
            "项目ID": project_id,
            "项目文件夹": saved.get("cacheDir"),
            "保存核对": "一致" if not problems else problems,
            "下一步": "要上传认证素材的话，先用 create_certified_group 在这个项目里建认证分组。",
        }

    def create_certified_group(self, project: str, name: str, description: str | None = None) -> dict[str, Any]:
        """在项目里新建认证分组（同时在玄上那边建分组）。同名分组已存在时拒绝：重名后很容易传错分组。"""
        proj = self.resolve_project(project)
        key = str(name or "").strip()
        if not key:
            raise CanvasError("分组名称不能为空。")
        if len(key) > 64:
            raise RuleViolation(f"分组名称太长了（{len(key)} 个字），请控制在 64 个字以内。")
        existing = self._groups(proj["id"])
        same = [item for item in existing if str(item.get("name", "")).strip() == key]
        if same:
            raise RuleViolation(
                f"项目「{proj.get('name')}」里已经有叫「{key}」的认证分组了（ID {same[0].get('id')}），可以直接用。"
                "名字重复后很容易传错分组，所以不再新建。"
            )
        try:
            created = self.connect().post(
                "/api/certified-assets/groups",
                {
                    "projectId": proj["id"],
                    "name": key,
                    "description": (description or "").strip(),
                    "providerId": PROVIDER,
                    "projectName": REMOTE_PROJECT,
                },
            )
        except CanvasApiError as exc:
            raise CanvasApiError(f"建分组失败，画布原始报错：{exc.message}", status=exc.status, code=exc.code, raw=exc.raw) from exc
        group_id = created.get("id")
        saved = next((item for item in self._groups(proj["id"]) if item.get("id") == group_id), None)
        problems = []
        if saved is None:
            problems.append("读回时这个项目的分组列表里没有新分组")
        elif str(saved.get("name", "")).strip() != key:
            problems.append(f"读回的分组名是「{saved.get('name')}」，和请求的不一样")
        return {
            "分组名": key,
            "分组ID": group_id,
            "项目": {"名称": proj.get("name"), "ID": proj["id"]},
            "保存核对": "一致" if not problems else problems,
            "注意": "玄上那边没有删除分组的接口，分组建了就删不掉，以后起名前先想好。",
            "下一步": "可以用 upload_certified_image / upload_certified_video 往这个分组上传素材。",
        }

    def _remote_asset(self, asset_id: str) -> dict[str, Any]:
        return self.connect().post(
            "/api/certified-assets/get", {"id": asset_id, "projectName": REMOTE_PROJECT, "providerId": PROVIDER}
        )

    def certified_groups(self, project: str) -> dict[str, Any]:
        proj = self.resolve_project(project)
        groups = self._groups(proj["id"])
        graph = self._graph(proj["id"])
        on_canvas: dict[str, list[str]] = {}
        for node in graph.get("nodes") or []:
            if node.get("type") == "certified-asset":
                on_canvas.setdefault((node.get("data") or {}).get("assetId"), []).append(node["id"])
        client = self.connect()

        def fetch(group: dict[str, Any]) -> list[dict[str, Any]]:
            # 画布的本地缓存经常是空的，直接向玄上那边按分组查（只读）。
            items: list[dict[str, Any]] = []
            page = 1
            while True:
                listing = client.post(
                    "/api/certified-assets/list-cloud",
                    {
                        "providerId": PROVIDER,
                        "filter": {"groupIds": [group["id"]]},
                        "pageNumber": page,
                        "pageSize": 100,
                        "projectName": group.get("projectName") or REMOTE_PROJECT,
                    },
                )
                batch = (listing or {}).get("items") or []
                items.extend(batch)
                if len(batch) < 100 or len(items) >= int((listing or {}).get("totalCount") or 0) or page >= 20:
                    return items
                page += 1

        # 每个分组单独查一次，一次要几秒，并行查省时间。
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(fetch, groups))

        result_groups = []
        for group, items in zip(groups, fetched):
            assets = []
            for asset in items:
                status = asset.get("status")
                nodes_on_canvas = on_canvas.get(asset.get("id")) or []
                assets.append(
                    {
                        "素材ID": asset.get("id"),
                        "名称": self.names.get(asset.get("id")) or asset.get("name"),
                        "类型": {"Image": "图片", "Video": "视频", "Audio": "音频"}.get(asset.get("assetType"), asset.get("assetType")),
                        "认证状态": CERT_STATUS.get(status, status),
                        "画布上的节点": nodes_on_canvas[:3] + ([f"……共 {len(nodes_on_canvas)} 个"] if len(nodes_on_canvas) > 3 else []),
                    }
                )
            result_groups.append({"分组名": group.get("name"), "分组ID": group.get("id"), "素材": assets})
        return {"项目": {"名称": proj.get("name"), "ID": proj["id"]}, "认证分组": result_groups, "说明": "状态是向玄上实时查的"}

    def get_task(self, project: str, task_id: str | None = None, node: str | None = None) -> dict[str, Any]:
        proj = self.resolve_project(project)
        client = self.connect()
        if task_id:
            task = client.get(f"/api/projects/{proj['id']}/tasks/{task_id}")
        elif node:
            graph = self._graph(proj["id"])
            target = self._resolve_node(graph, node, "节点")
            tasks = [t for t in self._tasks(proj["id"]) if t.get("nodeId") == target["id"]]
            if not tasks:
                return {"节点": g.label_of(target), "说明": "这个节点还没有提交过任务"}
            task = max(tasks, key=lambda t: t.get("createdAt") or 0)
        else:
            raise CanvasError("请给任务 ID（task_id）或节点（node）。")
        return self._describe_task(proj, task)

    def _describe_task(self, project: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        result = task.get("result") or {}
        params = task.get("params") or {}
        cache_dir = project.get("cacheDir")
        outputs = []
        for rel in result.get("outputPaths") or []:
            path = Path(cache_dir) / rel if cache_dir else Path(rel)
            outputs.append(str(path) if path.exists() else rel)
        info = {
            "任务ID": task.get("id"),
            "节点ID": task.get("nodeId"),
            "状态": TASK_STATUS.get(task.get("status"), task.get("status")),
            "进度": f"{task.get('progress', 0)}%",
            "提交时间": _fmt_time(task.get("createdAt")),
            "完成时间": _fmt_time(task.get("completedAt")),
            "模型": task.get("modelId"),
            "是样片": params.get("resolution") == "draft" or bool((result.get("metadata") or {}).get("draft")),
            "输出文件": outputs,
        }
        error = task.get("error") or result.get("error")
        if error:
            info["错误"] = error
        if (result.get("metadata") or {}).get("seed") is not None:
            info["实际种子"] = result["metadata"]["seed"]
        return info

    # ------------------------------------------------------------------ 上传认证素材

    def upload(
        self,
        project: str,
        file_path: str,
        group: str,
        display_name: str | None,
        kind: str,
    ) -> dict[str, Any]:
        proj = self.resolve_project(project)
        path = Path(str(file_path or "").strip().strip('"')).expanduser()
        if not path.is_absolute():
            raise CanvasError(f"请给文件的完整路径（比如 C:\\素材\\人物.png），现在是「{file_path}」。")
        if not path.is_file():
            raise CanvasError(f"文件不存在：{path}")
        ext = path.suffix.lower()
        allowed = IMAGE_EXTENSIONS if kind == "image" else VIDEO_EXTENSIONS
        if ext not in allowed:
            raise RuleViolation(f"{'图片' if kind == 'image' else '参考视频'}只支持 {'、'.join(allowed)} 格式，这个文件是「{ext or '没有扩展名'}」。")
        group_obj = self._resolve_group(proj, group)
        display = (display_name or path.name).strip() or path.name
        needs_resize = False
        if kind == "image":
            info = local_image_info(path)
            if info is None:
                raise RuleViolation(f"读不出这张图片的尺寸，可能文件损坏或不是真正的 {ext} 图片：{path}")
            # 规则 4：超过 6000px 照样上传，画布会自动缩到长边 5800px（JPEG），结果里写清楚缩到了多大。
            needs_resize = max(info[1], info[2]) > MAX_IMAGE_SIDE
        return self._upload(proj, path, group_obj, display, kind, needs_resize)

    def _upload(self, proj: dict[str, Any], path: Path, group: dict[str, Any], display: str, kind: str, resized: bool) -> dict[str, Any]:
        client = self.connect()
        ext = path.suffix.lower()
        mime = (IMAGE_EXTENSIONS if kind == "image" else VIDEO_EXTENSIONS)[ext]
        name = transfer_name(kind, path)
        try:
            uploaded = client.upload(
                "/api/certified-assets/upload",
                fields={
                    "providerId": PROVIDER,
                    "groupId": group["id"],
                    "assetType": "Image" if kind == "image" else "Video",
                    "projectName": REMOTE_PROJECT,
                },
                file_path=path,
                transfer_name=name,
                mime=mime,
            )
        except CanvasApiError as exc:
            raise CanvasApiError(f"上传失败，画布原始报错：{exc.message}", status=exc.status, code=exc.code, raw=exc.raw) from exc
        asset_id = uploaded.get("id")
        url = uploaded.get("url")
        hosting = uploaded.get("hosting") or "未知"
        self.names.save(asset_id, display, str(path), name)
        result: dict[str, Any] = {
            "素材ID": asset_id,
            "显示名": display,
            "传输文件名": name,
            "分组": f"{group.get('name')}（{group.get('id')}）",
            "存储去向": "玄上自己的存储" if hosting == "xszy" else f"公共图床（{hosting}）",
        }
        warnings: list[str] = []
        if hosting != "xszy":
            warnings.append(
                f"玄上存储上传失败，画布自动改传到了公共图床（{hosting}）：这个文件现在在公网上，拿到链接的人都能打开。是否继续使用，由使用者决定。"
            )
        check = verify_upload(url, path, kind=kind, tolerance=self.settings.size_tolerance, expect_resized=resized) if url else None
        if check:
            result["上传核对"] = check.to_dict()
            if check.status == "fail":
                raise RuleViolation(
                    f"文件已经传上去了（素材 ID {asset_id}），但核对不通过：{check.message}。"
                    "已停止，没有等认证，也不建议使用这个素材。"
                )
            if resized and check.local_dims and check.remote_dims:
                result["自动缩小"] = (
                    f"原图 {check.local_dims[0]}×{check.local_dims[1]}，长边超过 {MAX_IMAGE_SIDE}px，"
                    f"画布上传时自动缩到了 {check.remote_dims[0]}×{check.remote_dims[1]}（JPEG）"
                )
            elif check.status in ("warn", "unknown"):
                warnings.append(f"上传核对：{check.message}")
        else:
            warnings.append("画布没有返回文件地址，没能核对远端文件")

        asset, waited = self._wait_certified(asset_id)
        status = asset.get("status")
        result["认证状态"] = CERT_STATUS.get(status, status)
        result["等待秒数"] = round(waited)
        if status == "Failed":
            result["认证失败原因"] = asset.get("error") or "画布没有给出原因"
        elif status != "Active":
            warnings.append(
                f"等了 {waited:.0f} 秒还在认证中，先返回。稍后用 list_certified_groups 查状态，变成「已认证」后再用 add_certified_asset_node 放到画布上。"
            )
        if warnings:
            result["注意"] = warnings
        result["下一步"] = "认证完成后，用 add_certified_asset_node 把它放到画布上。" if status == "Active" else None
        return {k: v for k, v in result.items() if v is not None}

    def _wait_certified(self, asset_id: str) -> tuple[dict[str, Any], float]:
        """规则 7：等认证状态变成 Active 再返回，但有等待上限。"""
        start = time.monotonic()
        asset: dict[str, Any] = {}
        while True:
            try:
                asset = self._remote_asset(asset_id)
            except CanvasError:
                asset = asset or {"status": "Processing"}
            if asset.get("status") in ("Active", "Failed"):
                break
            if time.monotonic() - start + self.settings.certify_poll_seconds > self.settings.certify_wait_seconds:
                break
            time.sleep(self.settings.certify_poll_seconds)
        return asset, time.monotonic() - start

    # ------------------------------------------------------------------ 放认证素材节点

    def add_certified_nodes(
        self,
        project: str,
        asset_ids: list[str],
        display_names: list[str] | None = None,
        allow_duplicate: bool = False,
    ) -> dict[str, Any]:
        proj = self.resolve_project(project)
        if not asset_ids:
            raise CanvasError("请给至少一个素材 ID。")
        if display_names and len(display_names) != len(asset_ids):
            raise CanvasError("display_names 的数量要和 asset_ids 一样多（一一对应），不需要改名可以不传。")
        if len(set(asset_ids)) != len(asset_ids):
            raise CanvasError("asset_ids 里有重复的素材 ID。")
        graph = self._graph(proj["id"])
        existing: dict[str, list[dict[str, Any]]] = {}
        for node in graph.get("nodes") or []:
            if node.get("type") == "certified-asset":
                existing.setdefault((node.get("data") or {}).get("assetId"), []).append(node)

        problems, skipped, planned = [], [], []
        for index, asset_id in enumerate(asset_ids):
            try:
                asset = self._remote_asset(asset_id)
            except CanvasError as exc:
                problems.append(f"{asset_id}：查不到这个素材（{exc.message}）")
                continue
            status = asset.get("status")
            if status != "Active":
                problems.append(f"{asset_id}：{CERT_STATUS.get(status, status)}，认证完成后才能放到画布上")
                continue
            if asset.get("assetType") not in ("Image", "Video"):
                problems.append(f"{asset_id}：类型是 {asset.get('assetType')}，第一版只支持图片和视频")
                continue
            if existing.get(asset_id) and not allow_duplicate:
                skipped.append({"素材ID": asset_id, "已有节点": [f"{g.label_of(n)}（{n['id']}）" for n in existing[asset_id]]})
                continue
            display = (display_names[index] if display_names else None) or self.names.get(asset_id) or asset.get("name") or asset_id
            planned.append((asset, display))
        if problems:
            raise RuleViolation("没有放任何节点，因为：\n- " + "\n- ".join(problems))
        if not planned:
            return {"新建节点": [], "跳过（画布上已有）": skipped, "说明": "这些素材画布上都已经有节点了，可以直接用。确实要再放一个，带上 allow_duplicate=true。"}

        rects = g.occupied_rects(graph.get("nodes") or [])
        x, y = g.find_free_spot(rects, width=g.NODE_W, height=len(planned) * 220 - 20)
        new_nodes = []
        for offset, (asset, display) in enumerate(planned):
            new_nodes.append(
                {
                    "id": g.new_id("certified-asset"),
                    "type": "certified-asset",
                    "ui": {"x": x, "y": y + offset * 220, "width": g.NODE_W, "height": g.NODE_H, "nodeType": "certified-asset", "label": display},
                    "data": {
                        "providerId": PROVIDER,
                        "assetId": asset["id"],
                        "groupId": asset.get("groupId"),
                        "name": display,
                        "assetType": asset.get("assetType"),
                        "url": asset.get("url"),
                        "projectName": asset.get("projectName") or REMOTE_PROJECT,
                        "status": "Active",
                    },
                }
            )
        self._add_items(proj["id"], new_nodes, [])
        mismatches = self._verify_nodes(proj["id"], new_nodes, [])
        return {
            "新建节点": [
                {"节点ID": n["id"], "节点名": n["ui"]["label"], "类型": "视频" if n["data"]["assetType"] == "Video" else "图片", "素材ID": n["data"]["assetId"]}
                for n in new_nodes
            ],
            **({"跳过（画布上已有）": skipped} if skipped else {}),
            "保存核对": "一致" if not mismatches else mismatches,
        }

    def _add_items(self, project_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """规则 1：只用增量接口加节点和连线，不整张图保存，也不删任何东西。"""
        self.connect().post(
            f"/api/projects/{project_id}/graph/items",
            {"mutationId": f"xs-plugin-{uuid.uuid4()}", "nodes": nodes, "edges": edges},
        )

    def _verify_nodes(self, project_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
        """规则 10：建完马上读回，核对内容和请求一致。"""
        graph = self._graph(project_id)
        by_id = {node["id"]: node for node in graph.get("nodes") or []}
        edge_ids = {(edge.get("source"), edge.get("target")) for edge in graph.get("edges") or []}
        problems = []
        for node in nodes:
            saved = by_id.get(node["id"])
            if saved is None:
                problems.append(f"节点 {node['id']} 读回时不见了")
                continue
            if g.label_of(saved) != node["ui"]["label"]:
                problems.append(f"节点 {node['id']} 的名字变了：{g.label_of(saved)}")
            for key, value in node["data"].items():
                if (saved.get("data") or {}).get(key) != value:
                    problems.append(f"节点 {g.label_of(node)} 的 {key} 和请求不一致")
        for edge in edges:
            if (edge["source"], edge["target"]) not in edge_ids:
                problems.append(f"连线 {edge['source']} → {edge['target']} 读回时不见了")
        return problems

    # ------------------------------------------------------------------ 建视频节点

    def create_video_node(
        self,
        project: str,
        name: str,
        prompt: str,
        image_nodes: list[str] | None = None,
        video_nodes: list[str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        proj = self.resolve_project(project)
        graph = self._graph(proj["id"])
        tasks = self._tasks(proj["id"])
        nodes = graph.get("nodes") or []
        by_id = {node["id"]: node for node in nodes}
        definitions = self.definitions()
        image_nodes = list(image_nodes or [])
        video_nodes = list(video_nodes or [])

        problems: list[str] = []
        sources: list[tuple[str, dict[str, Any]]] = []
        for kind, refs in (("image", image_nodes), ("video", video_nodes)):
            for ref in refs:
                try:
                    node = self._resolve_node(graph, ref, "图片节点" if kind == "image" else "视频节点")
                except CanvasError as exc:
                    problems.append(exc.message)
                    continue
                issue = self._source_problem(node, kind, by_id, definitions, tasks)
                if issue:
                    problems.append(issue)
                sources.append((kind, node))
        ids = [node["id"] for _, node in sources]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            problems.append("同一个节点接了不止一次：" + "、".join(g.label_of(by_id[i]) for i in duplicated))
        counts = {"image": len(image_nodes), "video": len(video_nodes), "audio": 0}
        check = check_prompt(prompt, counts)
        if check.format_problems:
            problems.append(
                f"提示词里有 {len(check.format_problems)} 处素材编号画布认不出来（全文每一处引用都要写成 (图片N)、(视频N)，"
                "不能只在开头声明区加括号、正文省略）：\n  · " + "\n  · ".join(check.format_problems[:30])
                + ("\n  · ……" if len(check.format_problems) > 30 else "")
            )
        problems.extend(check.problems)
        if problems:
            raise RuleViolation("没有创建视频节点，因为：\n- " + "\n- ".join(problems))

        final_params = build_video_params(self.settings.video_defaults, params or {}, counts)
        existing_names = [g.label_of(node) for node in nodes if node.get("type") == "video-generation"]
        final_name = dedupe_name(name or "玄上-Seedance", existing_names)

        rects = g.occupied_rects(nodes)
        if sources:
            positions = [g.absolute_position(node, by_id) for _, node in sources]
            right = max(px + float((node.get("ui") or {}).get("width") or g.NODE_W) for (px, _), (_, node) in zip(positions, sources))
            near = (right + 120, min(py for _, py in positions))
            x, y = g.find_free_spot(rects, width=g.NODE_W, height=g.NODE_H, near=near)
        else:
            x, y = g.find_free_spot(rects, width=g.NODE_W, height=g.NODE_H)

        node_id = g.new_id("video-generation")
        order = [node["id"] for _, node in sources]
        data = {**VIDEO_NODE_DEFAULTS, **final_params, "prompt": check.prompt, "inputAssetOrder": order}
        video_node = {
            "id": node_id,
            "type": "video-generation",
            "ui": {"x": x, "y": y, "width": g.NODE_W, "height": g.NODE_H, "nodeType": "video-generation", "label": final_name},
            "data": data,
        }
        edges = [
            {"id": f"e-{src}-{node_id}-{int(time.time() * 1000)}-{index:04d}", "source": src, "target": node_id}
            for index, src in enumerate(order)
        ]
        self._add_items(proj["id"], [video_node], edges)

        mismatches = self._verify_nodes(proj["id"], [video_node], edges)
        saved_graph = self._graph(proj["id"])
        saved = next((n for n in saved_graph.get("nodes") or [] if n["id"] == node_id), None)
        mapping = self._ordered_inputs(saved, saved_graph, tasks) if saved else []
        expected = [f"{KIND_LABEL[k]}{sum(1 for kk, _ in sources[: i + 1] if kk == k)}" for i, (k, _) in enumerate(sources)]
        if [m["编号"] for m in mapping] != expected or [m["节点ID"] for m in mapping] != order:
            mismatches.append("画布算出来的素材编号和请求的顺序对不上：" + "、".join(f"{m['编号']}={m['节点名']}" for m in mapping))
        result: dict[str, Any] = {
            "节点ID": node_id,
            "节点名": final_name,
            "参数": describe_params(final_params),
            "素材编号": [f"{m['编号']} = {m['节点名']}" for m in mapping],
            # 两项核对分开报：保存一致 ≠ 每一处引用都能被画布认出来。
            "保存核对": "一致（画布里保存的提示词、素材顺序、参数都和请求一样）" if not mismatches else mismatches,
            "引用格式检查": f"通过：全文 {check.reference_count} 处素材引用都是画布能识别的 (图片N)/(视频N) 写法，没有漏括号、省略或范围写法",
        }
        if final_name != (name or "玄上-Seedance").strip():
            result["改名说明"] = f"已有同名节点，自动改名为「{final_name}」，旧节点保留不动"
        if check.converted:
            result["引用格式已转换"] = check.converted
        if check.warnings:
            result["注意"] = check.warnings
        result["下一步"] = "用户明确要生成时，用 submit_generation 提交（会花积分）。"
        return result

    def _source_problem(
        self,
        node: dict[str, Any],
        kind: str,
        by_id: dict[str, dict[str, Any]],
        definitions: dict[str, dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> str | None:
        label = f"「{g.label_of(node)}」"
        actual = g.output_kind(node, definitions)
        node_type = node.get("type", "")
        data = node.get("data") or {}
        if g.is_hidden(node, by_id):
            return f"{label}已停用（隐藏），画布不会用它"
        if actual != kind:
            return f"{label}是{KIND_LABEL.get(actual or '', '不能当素材的节点')}，不能放进{KIND_LABEL[kind]}列表"
        if node_type == "certified-asset":
            if data.get("status") != "Active":
                return f"{label}还没认证完成（{CERT_STATUS.get(data.get('status'), data.get('status'))}）"
            return None
        if kind == "video" and node_type == "video-asset":
            return f"{label}是没认证的本地视频。参考视频要先用 upload_certified_video 上传认证，再用认证后的节点"
        if node_type.endswith("-asset"):
            return None if data.get("status") in (None, "ready") else f"{label}的素材还没准备好"
        if g.produces_task_output(node_type):
            latest = g.latest_tasks_by_node(tasks).get(node["id"])
            return None if g.has_output(node, latest, tasks) else f"{label}还没有生成好的结果，不能当参考"
        return f"{label}（{node_type}）不能当素材接入"

    # ------------------------------------------------------------------ 提交生成 / 转成片（花积分）
    # 不再弹确认：用户自己检查过提示词和画布才会下达生成指令。规则里要求 AI 只在用户明确要求时调用。

    def submit_generation(self, project: str, node: str, allow_unrecognized_refs: bool = False) -> dict[str, Any]:
        proj = self.resolve_project(project)
        graph = self._graph(proj["id"])
        tasks = self._tasks(proj["id"])
        target = self._resolve_node(graph, node, "视频节点")
        if target.get("type") != "video-generation":
            raise RuleViolation(f"「{g.label_of(target)}」不是 Seedance 视频生成节点，第一版只支持提交这种节点。")
        running = [t for t in tasks if t.get("nodeId") == target["id"] and t.get("status") in ("queued", "running")]
        if running:
            task = running[0]
            raise RuleViolation(
                f"没有提交：「{g.label_of(target)}」已经有任务在跑（任务 {task.get('id')}，{TASK_STATUS.get(task.get('status'))}）。"
                "一个节点同一时间只能跑一个任务，等它结束再提交，或者新建一个节点。"
            )
        data = target.get("data") or {}
        inputs = self._ordered_inputs(target, graph, tasks)
        counts = {kind: sum(1 for i in inputs if i["类型"] == kind) for kind in g.KINDS}
        check = check_prompt(data.get("prompt", ""), counts)
        # 按画布的识别规则查原提示词（@图片N 画布不认，也算问题），有画布认不出的写法就先不提交，免得白花积分。
        unrecognized = find_format_problems(canvas_view(data.get("prompt", "")))
        if unrecognized and not allow_unrecognized_refs:
            raise RuleViolation(
                f"没有提交：「{g.label_of(target)}」的提示词里有 {len(unrecognized)} 处素材编号画布认不出来，提交后这些地方不会关联到素材：\n  · "
                + "\n  · ".join(unrecognized[:30]) + ("\n  · ……" if len(unrecognized) > 30 else "")
                + "\n建议用 create_video_node 按原素材和参数新建一个修正版节点再提交。"
                "如果用户确认这些地方本来就不是引用素材（比如只是普通文字），可以带上 allow_unrecognized_refs=true 照原样提交。"
            )
        warnings = list(check.problems) + list(check.warnings)
        if unrecognized:
            warnings.append(f"用户确认按原样提交；提示词里有 {len(unrecognized)} 处素材编号画布认不出来")
        task = self.connect().post(f"/api/projects/{proj['id']}/tasks", {"nodeId": target["id"]})
        result: dict[str, Any] = {
            "任务ID": task.get("id"),
            "节点": g.label_of(target),
            "节点ID": target["id"],
            "状态": TASK_STATUS.get(task.get("status"), task.get("status")),
            "参数": describe_params(data),
            "素材": [f"{i['编号']} = {i['节点名']}" for i in inputs],
            "说明": "已提交。插件不会自动盯进度；用户问进度时用 get_task 查。",
        }
        if warnings:
            result["注意"] = warnings
        return result

    def create_final_video(self, project: str, task_id: str | None = None, node: str | None = None) -> dict[str, Any]:
        proj = self.resolve_project(project)
        tasks = self._tasks(proj["id"])
        graph = self._graph(proj["id"])
        by_id = {n["id"]: n for n in graph.get("nodes") or []}
        if task_id:
            source = next((t for t in tasks if t.get("id") == task_id), None)
            if source is None:
                source = self.connect().get(f"/api/projects/{proj['id']}/tasks/{task_id}")
        elif node:
            target = self._resolve_node(graph, node, "视频节点")
            candidates = [
                t for t in tasks
                if t.get("nodeId") == target["id"] and t.get("status") == "succeeded" and (t.get("params") or {}).get("resolution") == "draft"
            ]
            if not candidates:
                raise RuleViolation(f"「{g.label_of(target)}」还没有已完成的样片任务，不能转成片。")
            source = max(candidates, key=lambda t: t.get("createdAt") or 0)
        else:
            raise CanvasError("请给样片任务 ID（task_id）或视频节点（node）。")
        params = source.get("params") or {}
        is_draft = params.get("resolution") == "draft" or bool(((source.get("result") or {}).get("metadata") or {}).get("draft"))
        problems = []
        if source.get("status") != "succeeded":
            problems.append(f"样片任务还没成功完成（{TASK_STATUS.get(source.get('status'), source.get('status'))}）")
        if not is_draft:
            problems.append("这个任务不是样片（draft），不需要转成片")
        if source.get("modelId") != "Doubao-Seedance-2.5":
            problems.append("只有 Seedance 2.5 的样片能转成片")
        if source.get("providerId") != PROVIDER:
            problems.append("只支持玄上之音的任务")
        age_days = (time.time() * 1000 - float(source.get("createdAt") or 0)) / 86400000
        if age_days >= 7:
            problems.append("样片已经超过 7 天有效期")
        if problems:
            raise RuleViolation("不能转成片：" + "；".join(problems))
        node_label = g.label_of(by_id[source["nodeId"]]) if source.get("nodeId") in by_id else source.get("nodeId")
        task = self.connect().post(f"/api/projects/{proj['id']}/tasks/create-final-video", {"originalTaskId": source["id"]})
        return {
            "任务ID": task.get("id"),
            "成片节点ID": task.get("nodeId"),
            "成片节点名": "成片生成",
            "来自样片节点": node_label,
            "样片任务": source.get("id"),
            "状态": TASK_STATUS.get(task.get("status"), task.get("status")),
            "说明": "已提交（1080p、MP4，沿用样片的提示词和素材）。画布在样片节点旁边新建了一个「成片生成」节点；插件不会自动盯进度，用户问进度时用 get_task 查。",
        }
