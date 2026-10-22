"""读画布图数据的小工具：节点名字、素材类型、绝对坐标、找空位。"""

from __future__ import annotations

import secrets
import time
from typing import Any

NODE_W, NODE_H = 300, 200
KINDS = ("image", "video", "audio")
TASK_OUTPUT_TOOL_TYPES = {"video-enhance", "video-subtitle-erase-rh", "generation-observation"}


def new_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(2)}"


def label_of(node: dict[str, Any]) -> str:
    ui = node.get("ui") or {}
    data = node.get("data") or {}
    return str(ui.get("label") or data.get("name") or data.get("originalName") or node.get("id"))


def is_hidden(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    current: dict[str, Any] | None = node
    seen: set[str] = set()
    while current is not None and current.get("id") not in seen:
        seen.add(current.get("id"))
        if (current.get("ui") or {}).get("hidden"):
            return True
        parent = current.get("parentId")
        current = by_id.get(parent) if parent else None
    return False


def produces_task_output(node_type: str) -> bool:
    return "generation" in node_type or node_type in TASK_OUTPUT_TOOL_TYPES


def output_kind(node: dict[str, Any], definitions: dict[str, dict[str, Any]]) -> str | None:
    """这个节点接到视频节点上时算图片、视频还是音频。"""
    node_type = str(node.get("type"))
    data = node.get("data") or {}
    if node_type == "certified-asset":
        kind = str(data.get("assetType") or "Image").lower()
        return kind if kind in KINDS else None
    if node_type in ("image-asset", "video-asset", "audio-asset"):
        return node_type.split("-")[0]
    dynamic = str(data.get("outputMediaType") or "").lower()
    if dynamic in KINDS:
        return dynamic
    definition = definitions.get(node_type) or {}
    outputs = [str(o.get("type")) for o in definition.get("outputs") or [] if o.get("type") != "reference"]
    for kind in ("video", "image", "audio"):
        if kind in outputs:
            return kind
    if produces_task_output(node_type):
        return "video" if "video" in node_type else "image"
    return None


def absolute_position(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> tuple[float, float]:
    x = float((node.get("ui") or {}).get("x") or 0)
    y = float((node.get("ui") or {}).get("y") or 0)
    parent_id = node.get("parentId")
    seen: set[str] = set()
    while parent_id and parent_id in by_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id[parent_id]
        x += float((parent.get("ui") or {}).get("x") or 0)
        y += float((parent.get("ui") or {}).get("y") or 0)
        parent_id = parent.get("parentId")
    return x, y


def occupied_rects(nodes: list[dict[str, Any]]) -> list[tuple[float, float, float, float]]:
    by_id = {node["id"]: node for node in nodes}
    rects = []
    for node in nodes:
        x, y = absolute_position(node, by_id)
        ui = node.get("ui") or {}
        rects.append((x, y, float(ui.get("width") or NODE_W), float(ui.get("height") or NODE_H)))
    return rects


def _overlaps(rect: tuple[float, float, float, float], rects: list[tuple[float, float, float, float]], gap: float = 40) -> bool:
    x, y, w, h = rect
    for ox, oy, ow, oh in rects:
        if x < ox + ow + gap and x + w + gap > ox and y < oy + oh + gap and y + h + gap > oy:
            return True
    return False


def find_free_spot(
    rects: list[tuple[float, float, float, float]],
    *,
    width: float,
    height: float,
    near: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """找一块不和现有节点重叠的空地。near 给了就尽量靠近它（在它右边），否则放在所有节点的右边。"""
    if near is None:
        if not rects:
            return 0.0, 0.0
        right = max(x + w for x, _, w, _ in rects)
        top = min(y for _, y, _, _ in rects)
        start_x, start_y = right + 200, top
    else:
        start_x, start_y = near
    for column in range(0, 30):
        x = start_x + column * (width + 80)
        for row in range(0, 40):
            y = start_y + row * 60
            if not _overlaps((x, y, width, height), rects):
                return round(x), round(y)
    right = max((x + w for x, _, w, _ in rects), default=0)
    return round(right + 200), round(start_y)


def latest_tasks_by_node(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for task in tasks:
        node_id = task.get("nodeId")
        if not node_id:
            continue
        if node_id not in latest or (task.get("createdAt") or 0) > (latest[node_id].get("createdAt") or 0):
            latest[node_id] = task
    return latest


def has_output(node: dict[str, Any], latest_task: dict[str, Any] | None, tasks: list[dict[str, Any]]) -> bool:
    data = node.get("data") or {}
    if data.get("primaryOutputAssetId") or data.get("outputAssetIds"):
        return True
    for task in tasks:
        if task.get("nodeId") == node.get("id") and task.get("status") == "succeeded":
            result = task.get("result") or {}
            if result.get("outputAssetIds") or result.get("primaryOutputAssetId"):
                return True
    return False
