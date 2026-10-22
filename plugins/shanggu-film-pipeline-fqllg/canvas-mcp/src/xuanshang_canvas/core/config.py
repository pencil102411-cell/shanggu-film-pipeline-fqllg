"""配置读取：可选的配置文件 + 环境变量。都不填就用默认值。

配置文件默认位置：%APPDATA%\\xuanshang-canvas\\config.json，也可用环境变量
XUANSHANG_CANVAS_CONFIG 指定。格式见 README「配置项」。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 视频节点默认参数（计划第 6 节「默认参数」）。其余隐藏参数用画布默认值。
DEFAULT_VIDEO_PARAMS: dict[str, Any] = {
    "model": "Doubao-Seedance-2.5",
    "seedanceMode": "multimodal",
    "resolution": "draft",
    "ratio": "21:9",
    "seed": 1,
    "outputFormat": "mp4",
    "webSearch": False,
    "duration": 5,
}

# 0.3.0 起去掉了生成前的确认弹窗，旧配置里的这些项直接忽略。
OBSOLETE_KEYS = {"confirm_mode", "popup_timeout_seconds", "confirm_code_ttl_seconds"}


def default_config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "xuanshang-canvas" / "config.json"


def data_dir() -> Path:
    """插件自己的小文件（素材显示名记录）放这里。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "xuanshang-canvas"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    canvas_port: int | None = None
    video_defaults: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_VIDEO_PARAMS))
    # 规则 7：认证等待上限，要比 AI 工具单次调用的等待上限短（Codex 默认 60 秒）。
    certify_wait_seconds: float = 50.0
    certify_poll_seconds: float = 3.0
    # 规则 4：上传后大小差异在这个比例以内只提示，超过就报错。
    size_tolerance: float = 0.05
    http_timeout_seconds: float = 30.0
    upload_timeout_seconds: float = 900.0
    source: str = "默认值"
    warnings: list[str] = field(default_factory=list)


def _env_number(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"环境变量 {name} 应该是数字，现在是「{value}」")


def load_settings() -> Settings:
    settings = Settings()
    path = Path(os.environ["XUANSHANG_CANVAS_CONFIG"]) if os.environ.get("XUANSHANG_CANVAS_CONFIG") else default_config_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            settings.warnings.append(f"配置文件 {path} 读取失败，已改用默认值：{exc}")
            raw = {}
        if isinstance(raw, dict):
            settings.source = str(path)
            _apply(settings, raw)
        else:
            settings.warnings.append(f"配置文件 {path} 的内容应该是一个 JSON 对象，已忽略")

    try:
        port = os.environ.get("CANVAS_PORT")
        if port and port.strip():
            settings.canvas_port = int(port)
        number = _env_number("XUANSHANG_CERTIFY_WAIT_SECONDS")
        if number is not None:
            settings.certify_wait_seconds = number
    except ValueError as exc:
        settings.warnings.append(str(exc))
    return settings


def _apply(settings: Settings, raw: dict[str, Any]) -> None:
    for key, value in raw.items():
        if key == "video_defaults":
            if isinstance(value, dict):
                settings.video_defaults.update(value)
            else:
                settings.warnings.append("配置项 video_defaults 应该是对象，已忽略")
        elif key == "canvas_port":
            settings.canvas_port = int(value) if value not in (None, "") else None
        elif key in {
            "certify_wait_seconds",
            "certify_poll_seconds",
            "size_tolerance",
            "http_timeout_seconds",
            "upload_timeout_seconds",
        }:
            try:
                setattr(settings, key, float(value))
            except (TypeError, ValueError):
                settings.warnings.append(f"配置项 {key} 应该是数字，已忽略")
        elif key in OBSOLETE_KEYS:
            continue
        else:
            settings.warnings.append(f"不认识的配置项 {key}，已忽略")
