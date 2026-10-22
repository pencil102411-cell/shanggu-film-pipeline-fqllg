"""自动找到本机正在运行的画布（计划第 5 节）。

做法：找命令行里带 apps\\server\\dist\\index.js 的 node.exe（画布的后台服务），
读它在 127.0.0.1 上监听的端口，再请求 GET /api/projects 验证。不写死安装路径和版本号。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .client import probe_canvas

SERVER_ENTRY = r"apps\server\dist\index.js"
# 进程信息拿不到时的兜底：画布启动器默认从 56888 开始找空闲端口，开发模式是 48051。
FALLBACK_PORTS = [*range(56888, 56888 + 20), 48051]

_PS_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$procs = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -like '*apps\server\dist\index.js*' })
$out = foreach ($p in $procs) {
  $ports = @(Get-NetTCPConnection -OwningProcess $p.ProcessId -State Listen | Where-Object { $_.LocalAddress -in @('127.0.0.1','0.0.0.0','::1','::') } | Select-Object -ExpandProperty LocalPort)
  $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)"
  $grand = $null
  if ($parent) { $grand = Get-CimInstance Win32_Process -Filter "ProcessId=$($parent.ParentProcessId)" }
  [pscustomobject]@{
    pid = $p.ProcessId
    cmd = $p.CommandLine
    ports = $ports
    parentExe = $parent.ExecutablePath
    launcherExe = $grand.ExecutablePath
  }
}
ConvertTo-Json -InputObject @($out) -Depth 4 -Compress
"""


@dataclass
class CanvasInstance:
    port: int
    pid: int | None = None
    app_name: str = "玄上画布"
    brand: str | None = None
    build: str | None = None
    server_entry: str | None = None
    launcher_exe: str | None = None
    found_by: str = "process"
    extra_ports: list[int] = field(default_factory=list)

    def describe(self) -> str:
        bits = [f"{self.app_name}（端口 {self.port}"]
        if self.build:
            bits.append(f"，构建号 {self.build}")
        bits.append("）")
        return "".join(bits)

    def to_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "brand": self.brand,
            "port": self.port,
            "pid": self.pid,
            "build": self.build,
            "found_by": {"process": "自动找到的画布进程", "env": "CANVAS_PORT 手动指定", "probe": "按常用端口探测到"}.get(
                self.found_by, self.found_by
            ),
        }


def _run_powershell(script: str, timeout: float = 20.0) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.decode("utf-8", errors="replace").strip()


def _netstat_ports(pid: int) -> list[int]:
    """Get-NetTCPConnection 用不了时，用 netstat 兜底查端口。"""
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    ports: list[int] = []
    for line in completed.stdout.decode("mbcs" if sys.platform == "win32" else "utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[-1] == str(pid) and "LISTEN" in parts[-2].upper():
            match = re.search(r":(\d+)$", parts[1])
            if match:
                ports.append(int(match.group(1)))
    return ports


def _entry_path(cmd: str) -> Path | None:
    match = re.search(r"([A-Za-z]:\\[^\"]*?apps\\server\\dist\\index\.js)", cmd or "")
    return Path(match.group(1)) if match else None


def _read_brand(entry: Path | None) -> dict:
    if not entry:
        return {}
    brand_file = entry.parents[3] / "brand.json"  # resources\app\brand.json
    try:
        return json.loads(brand_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _build_number(*paths: str | None) -> str | None:
    for path in paths:
        if path:
            match = re.search(r"(\d{14})", Path(path).name)
            if match:
                return match.group(1)
    return None


def find_instances() -> list[CanvasInstance]:
    """返回所有能连上的画布。一个都没有时返回空列表。"""
    instances: list[CanvasInstance] = []
    output = _run_powershell(_PS_SCRIPT)
    records: list[dict] = []
    if output:
        try:
            parsed = json.loads(output)
            records = parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            records = []

    for record in records:
        if not isinstance(record, dict):
            continue
        pid = record.get("pid")
        ports = [int(p) for p in (record.get("ports") or []) if str(p).isdigit()]
        if not ports and pid:
            ports = _netstat_ports(int(pid))
        entry = _entry_path(record.get("cmd") or "")
        brand = _read_brand(entry)
        verified = [p for p in sorted(set(ports)) if probe_canvas(p)]
        if not verified:
            continue
        instances.append(
            CanvasInstance(
                port=verified[0],
                pid=int(pid) if pid else None,
                app_name=brand.get("appName") or Path(record.get("parentExe") or "").stem or "玄上画布",
                brand=brand.get("brand"),
                build=_build_number(record.get("launcherExe"), record.get("parentExe")),
                server_entry=str(entry) if entry else None,
                launcher_exe=record.get("launcherExe"),
                found_by="process",
                extra_ports=verified[1:],
            )
        )

    if not instances:
        for port in FALLBACK_PORTS:
            if probe_canvas(port, timeout=0.6):
                instances.append(CanvasInstance(port=port, found_by="probe"))
    return instances


def instance_for_port(port: int) -> CanvasInstance | None:
    """CANVAS_PORT 手动指定端口时用。尽量补上程序名，补不上也能用。"""
    if not probe_canvas(port):
        return None
    for found in find_instances():
        if found.port == port or port in found.extra_ports:
            found.port = port
            found.found_by = "env"
            return found
    return CanvasInstance(port=port, found_by="env")
