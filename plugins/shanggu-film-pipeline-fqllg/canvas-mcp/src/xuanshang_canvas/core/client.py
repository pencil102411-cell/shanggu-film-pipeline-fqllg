"""画布本地接口的 HTTP 客户端。只连 127.0.0.1，不走代理。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx2 as httpx

from .errors import CanvasApiError, CanvasConnectionError, CanvasError


class CanvasClient:
    def __init__(self, port: int, *, timeout: float = 30.0, upload_timeout: float = 900.0):
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.timeout = timeout
        self.upload_timeout = upload_timeout
        # 本机接口不能走系统代理，否则开了代理软件的电脑会连不上。
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float | None = None,
        unwrap: bool = True,
    ) -> Any:
        try:
            response = self._http.request(
                method,
                path,
                json=json,
                params=params,
                data=data,
                files=files,
                timeout=timeout or self.timeout,
            )
        except httpx.ConnectError as exc:
            raise CanvasConnectionError(
                f"连不上画布（端口 {self.port}）。画布可能已经关掉，或者重启后换了端口。"
                "请确认画布开着，再调用一次 canvas_status。"
            ) from exc
        except httpx.TimeoutException as exc:
            raise CanvasError(
                f"画布在 {timeout or self.timeout:.0f} 秒内没有响应（接口 {path}）。画布可能正忙，稍后再试。"
            ) from exc
        except httpx.HTTPError as exc:
            raise CanvasError(f"请求画布失败（接口 {path}）：{exc}") from exc

        try:
            body = response.json()
        except ValueError:
            snippet = response.text[:300]
            if response.status_code >= 400:
                raise CanvasApiError(
                    f"画布返回错误（HTTP {response.status_code}，接口 {path}）：{snippet}",
                    status=response.status_code,
                    raw=snippet,
                )
            raise CanvasApiError(
                f"画布返回了看不懂的内容（接口 {path}）：{snippet}", status=response.status_code, raw=snippet
            )

        if response.status_code >= 400 or (isinstance(body, dict) and body.get("success") is False):
            raise CanvasApiError.from_response(response.status_code, body, path)
        if unwrap and isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json=body if body is not None else {}, **kwargs)

    def raw_post(self, path: str, body: Any) -> tuple[int, Any]:
        """兼容性检查用：不把错误当异常，原样返回状态码和内容。"""
        try:
            response = self._http.post(path, json=body)
        except httpx.HTTPError as exc:
            raise CanvasConnectionError(f"连不上画布（端口 {self.port}）：{exc}") from exc
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text[:300]

    def raw_get(self, path: str) -> tuple[int, Any]:
        try:
            response = self._http.get(path)
        except httpx.HTTPError as exc:
            raise CanvasConnectionError(f"连不上画布（端口 {self.port}）：{exc}") from exc
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text[:300]

    def upload(
        self,
        path: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        transfer_name: str,
        mime: str,
    ) -> Any:
        # 画布要求表单字段排在文件前面；httpx 先写 data 再写 files，顺序正好。
        with open(file_path, "rb") as handle:
            return self.request(
                "POST",
                path,
                data=fields,
                files={"file": (transfer_name, handle, mime)},
                timeout=self.upload_timeout,
            )


def probe_canvas(port: int, timeout: float = 1.5) -> bool:
    """这个端口上是不是画布：请求 GET /api/projects 能拿到 success=true 就算。"""
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as http:
            response = http.get(f"http://127.0.0.1:{port}/api/projects")
            body = response.json()
            return response.status_code == 200 and isinstance(body, dict) and body.get("success") is True
    except Exception:
        return False
