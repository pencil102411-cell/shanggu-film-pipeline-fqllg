"""给使用者看的错误。消息一律写中文，说清楚哪里不对、下一步怎么办。"""

from __future__ import annotations

from typing import Any


class CanvasError(Exception):
    """可预期的失败：画布没开、参数不对、规则不允许等。"""

    def __init__(self, message: str, *, code: str | None = None, detail: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail


class RuleViolation(CanvasError):
    """请求违反了第 6 节的操作规则，插件拒绝执行。"""


class CanvasConnectionError(CanvasError):
    """连不上画布。"""


class CanvasApiError(CanvasError):
    """画布接口返回了错误。保留原始错误信息，方便画布升级后快速定位。"""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None, raw: Any = None):
        super().__init__(message, code=code, detail=raw)
        self.status = status
        self.raw = raw

    @classmethod
    def from_response(cls, status: int, body: Any, path: str) -> "CanvasApiError":
        code = None
        parts: list[str] = []
        if isinstance(body, dict):
            code = body.get("code")
            if body.get("error"):
                parts.append(str(body["error"]))
            for item in body.get("errors") or []:
                if isinstance(item, dict):
                    text = item.get("message") or ""
                    if item.get("code"):
                        text = f"{text}（{item['code']}）"
                    if text:
                        parts.append(text)
                elif item:
                    parts.append(str(item))
        elif body:
            parts.append(str(body)[:500])
        reason = "；".join(parts) or "没有附带错误说明"
        label = f"HTTP {status}" + (f"，{code}" if code else "")
        return cls(f"画布返回错误（{label}，接口 {path}）：{reason}", status=status, code=code, raw=body)
