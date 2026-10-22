"""素材文件相关：读图片尺寸、生成传输用的 ASCII 文件名、上传后核对（规则 4、5）。

图片尺寸靠读文件头解析，不额外加依赖包。
"""

from __future__ import annotations

import os
import re
import secrets
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import httpx2 as httpx

IMAGE_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}
VIDEO_EXTENSIONS = {".mp4": "video/mp4", ".mov": "video/quicktime"}

# 画布对玄上认证图片的处理：长边超过 6000px 会被自动缩到 5800px 并转成 JPEG。
MAX_IMAGE_SIDE = 6000
RESIZED_LONG_SIDE = 5800


def parse_image_size(data: bytes) -> tuple[str, int, int] | None:
    """从文件开头的字节读出（格式, 宽, 高）。读不出来返回 None。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "gif", width, height
    if data[:2] == b"BM" and len(data) >= 26:
        width, height = struct.unpack("<ii", data[18:26])
        return "bmp", abs(width), abs(height)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8 ":
            width, height = struct.unpack("<HH", data[26:30])
            return "webp", width & 0x3FFF, height & 0x3FFF
        if chunk == b"VP8L":
            b0, b1, b2, b3 = data[21:25]
            width = 1 + (b0 | ((b1 & 0x3F) << 8))
            height = 1 + ((b1 >> 6) | (b2 << 2) | ((b3 & 0x0F) << 10))
            return "webp", width, height
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return "webp", width, height
        return None
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            if marker == 0xFF:
                index += 1
                continue
            length = struct.unpack(">H", data[index + 2 : index + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return "jpeg", width, height
            index += 2 + length
        return None
    return None


def local_image_info(path: Path) -> tuple[str, int, int] | None:
    return parse_image_size(path.read_bytes())


def transfer_name(kind: str, original: Path) -> str:
    """规则 5：实际传输用纯 ASCII 文件名，避免中文被画布接口弄成乱码。不超过 32 个字符。

    保留原文件名里的英文、数字部分，方便在玄上素材库里认出来，例如
    「16-21-段2-镜135.mp4」→「16-21-2-135_a1b2c3.mp4」。
    """
    extension = original.suffix.lower()
    readable = re.sub(r"[^A-Za-z0-9]+", "-", original.stem).strip("-")[:14].strip("-")
    token = secrets.token_hex(3)
    if readable:
        return f"{readable}_{token}{extension}"
    prefix = "img" if kind == "image" else "vid"
    return f"{prefix}_{time.strftime('%Y%m%d%H%M%S')}_{token}{extension}"


@dataclass
class RemoteCheck:
    status: str  # ok / warn / fail / unknown
    message: str
    local_size: int
    remote_size: int | None = None
    local_dims: tuple[int, int] | None = None
    remote_dims: tuple[int, int] | None = None

    def to_dict(self) -> dict:
        result = {
            "结果": {"ok": "一致", "warn": "基本一致（有细微差异）", "fail": "不一致", "unknown": "没能核对"}[self.status],
            "说明": self.message,
            "本地大小": self.local_size,
            "远端大小": self.remote_size,
        }
        if self.local_dims or self.remote_dims:
            result["本地尺寸"] = f"{self.local_dims[0]}×{self.local_dims[1]}" if self.local_dims else None
            result["远端尺寸"] = f"{self.remote_dims[0]}×{self.remote_dims[1]}" if self.remote_dims else None
        return result


def _remote_size(http: httpx.Client, url: str) -> int | None:
    try:
        response = http.head(url, follow_redirects=True)
        if response.status_code < 400 and response.headers.get("content-length"):
            return int(response.headers["content-length"])
    except (httpx.HTTPError, ValueError):
        pass
    try:
        response = http.get(url, headers={"Range": "bytes=0-0"}, follow_redirects=True)
        content_range = response.headers.get("content-range", "")
        if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit():
            return int(content_range.rsplit("/", 1)[1])
        if response.status_code == 200 and response.headers.get("content-length"):
            return int(response.headers["content-length"])
    except (httpx.HTTPError, ValueError):
        pass
    return None


def _remote_head_bytes(http: httpx.Client, url: str, limit: int = 1 << 20) -> bytes:
    buffer = bytearray()
    try:
        with http.stream("GET", url, headers={"Range": f"bytes=0-{limit - 1}"}, follow_redirects=True) as response:
            if response.status_code >= 400:
                return b""
            for chunk in response.iter_bytes():
                buffer.extend(chunk)
                if len(buffer) >= limit:
                    break
    except httpx.HTTPError:
        return bytes(buffer)
    return bytes(buffer)


def verify_upload(
    url: str,
    local_path: Path,
    *,
    kind: str,
    tolerance: float,
    expect_resized: bool = False,
    timeout: float = 30.0,
) -> RemoteCheck:
    """规则 4：上传后核对远端文件和本地一致。图片核对大小和像素尺寸，视频核对大小。"""
    local_size = os.path.getsize(local_path)
    local_dims = None
    if kind == "image":
        info = local_image_info(local_path)
        local_dims = (info[1], info[2]) if info else None
    try:
        with httpx.Client(timeout=timeout) as http:
            remote_size = _remote_size(http, url)
            remote_dims = None
            if kind == "image":
                info = parse_image_size(_remote_head_bytes(http, url))
                remote_dims = (info[1], info[2]) if info else None
    except httpx.HTTPError as exc:
        return RemoteCheck("unknown", f"没能读取远端文件：{exc}", local_size)

    check = RemoteCheck("ok", "", local_size, remote_size, local_dims, remote_dims)
    if expect_resized:
        if remote_dims and max(remote_dims) <= RESIZED_LONG_SIDE:
            check.status, check.message = "warn", f"原图长边超过 {MAX_IMAGE_SIDE}px，画布自动缩小了：长边缩到 {max(remote_dims)}px"
        elif remote_dims:
            check.status, check.message = "fail", f"预期被压缩到长边 {RESIZED_LONG_SIDE}px，远端却是 {remote_dims[0]}×{remote_dims[1]}"
        else:
            check.status, check.message = "unknown", f"原图长边超过 {MAX_IMAGE_SIDE}px，画布会自动缩小，但没能读到远端尺寸"
        return check
    # 尺寸不一致：图一定被改过，直接报错。
    if kind == "image" and local_dims and remote_dims and remote_dims != local_dims:
        check.status = "fail"
        check.message = f"尺寸不一致：本地 {local_dims[0]}×{local_dims[1]}，远端 {remote_dims[0]}×{remote_dims[1]}，图被改过"
        return check
    if remote_size is None:
        check.status = "unknown"
        check.message = "远端没有返回文件大小，没能核对大小" + ("；尺寸一致" if remote_dims else "")
        return check
    diff = abs(remote_size - local_size) / max(local_size, 1)
    if diff > tolerance:
        check.status = "fail"
        check.message = f"大小差了 {diff:.1%}（本地 {local_size} 字节，远端 {remote_size} 字节），超过 {tolerance:.0%}，说明被重新压缩过"
        return check
    if remote_size != local_size:
        check.status = "warn"
        check.message = (
            f"大小差了 {diff:.1%}（本地 {local_size} 字节，远端 {remote_size} 字节），在允许范围内；"
            "通常是存储去掉了文件里的附加信息，画质没变"
        )
    else:
        check.message = ("大小和尺寸都" if kind == "image" and remote_dims else "大小") + "和本地一致，按原质量上传"
    if kind == "image" and remote_dims is None:
        check.message += "（远端尺寸没读到，只核对了大小）"
    return check
