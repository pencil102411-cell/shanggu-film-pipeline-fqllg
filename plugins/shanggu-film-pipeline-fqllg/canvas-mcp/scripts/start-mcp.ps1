# 启动玄上画布插件的 MCP 服务（Claude Code、Codex 等都通过它启动）。
# 自己去 uv 的常见安装位置找，不依赖 PATH：Windows 上刚装好 uv 时，已经开着的程序看不到新的 PATH。
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File <插件文件夹>\canvas-mcp\scripts\start-mcp.ps1 [--check]

$root = Split-Path -Parent $PSScriptRoot
$found = Get-Command uv.exe -ErrorAction SilentlyContinue
$candidates = @(@(
    $(if ($found) { $found.Source }),
    (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'),
    (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\uv\uv.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })

if (-not $candidates) {
    [Console]::Error.WriteLine('没找到 uv。请先安装：在 PowerShell 里运行 winget install --id=astral-sh.uv -e ，装好后重新打开 AI 工具。')
    exit 1
}

# 依赖目录按版本分开（Claude Code 通过 UV_PROJECT_ENVIRONMENT 指定基础位置）。
# 原因：升级插件时，旧版本的会话可能还开着、占用着旧依赖目录里的文件，新版本如果用同一个目录就更新不了。
# 没指定时（比如在 Codex 里启动），默认放到 %LOCALAPPDATA%\shanggu-film-pipeline-fqllg\canvas-venv，
# 不放进插件文件夹：插件每次更新都会换一个新文件夹，依赖放在里面就得重新下载，Codex 启动会超时。
$base = $env:UV_PROJECT_ENVIRONMENT
if (-not $base) { $base = Join-Path $env:LOCALAPPDATA 'shanggu-film-pipeline-fqllg\canvas-venv' }
if ($base) {
    # Claude Code 传进来的是正斜杠路径，统一成 Windows 的完整写法，后面比较路径才不会出错。
    $base = [IO.Path]::GetFullPath($base).TrimEnd('\')
    $version = 'dev'
    $match = Select-String -LiteralPath (Join-Path $root 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($match) { $version = $match.Matches[0].Groups[1].Value }
    $current = "$base-$version"
    $env:UV_PROJECT_ENVIRONMENT = $current

    # 依赖目录被删了一半时（例如卸载或重装插件时，另一个会话还开着、占用着里面的文件），
    # 目录还在、但没有 pyvenv.cfg，uv 会直接用这个坏掉的环境，报「No module named 'xuanshang_canvas'」。
    # 这种情况先整个删掉，让 uv 重建；删不掉说明还有程序在用，提示用户关掉其他会话再试。
    if ((Test-Path -LiteralPath $current) -and -not (Test-Path -LiteralPath (Join-Path $current 'pyvenv.cfg'))) {
        # 也可能是另一个会话正在第一次建这个目录、pyvenv.cfg 还没写出来：等 3 秒再看一次，还是没有才删。
        Start-Sleep -Seconds 3
    }
    if ((Test-Path -LiteralPath $current) -and -not (Test-Path -LiteralPath (Join-Path $current 'pyvenv.cfg'))) {
        Remove-Item -LiteralPath $current -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $current) {
            [Console]::Error.WriteLine("画布工具的依赖目录不完整，而且正被别的程序占用，没法自动修复：$current 。请关掉其他正在用这个插件的会话，再重新打开。")
            exit 1
        }
    }

    # 清理旧版本的依赖目录。只删「没有任何正在运行的程序来自这个目录」的，正在用的绝不碰，下次再清。
    $parent = Split-Path -Parent $base
    $leaf = Split-Path -Leaf $base
    $old = @(Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -eq $leaf -or $_.Name -like "$leaf-*") -and -not $_.FullName.Equals($current, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($old.Count -gt 0) {
        $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object { $_.ExecutablePath } | Where-Object { $_ })
        foreach ($dir in $old) {
            # 0.3.1–0.4.1 的清理会先把目录改名（xxx.delete-数字），改名前启动的程序记的还是原名，所以原名也要查。
            $names = @($dir.FullName, ($dir.FullName -replace '(\.delete-\d+)+$', ''))
            $inUse = $false
            foreach ($name in $names) {
                $prefix = $name.TrimEnd('\') + '\'
                if ($running | Where-Object { $_.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) }) { $inUse = $true }
            }
            if (-not $inUse) {
                Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# --no-editable：把插件代码复制进依赖目录。不用「记路径」的方式，因为路径里有中文时，
# 中文版 Windows 上的 Python 会把记下的路径读成乱码，导致找不到插件代码。
# 用 python -m 启动（而不是依赖目录里的 exe），运行中的会话不会锁住需要更新的程序文件。
# 直接调用（不经过管道），uv 会继承本进程的输入输出，MCP 协议数据原样传递。
& $candidates[0] run --frozen --quiet --no-editable --project $root python -m xuanshang_canvas.mcp_server.server @args
exit $LASTEXITCODE
