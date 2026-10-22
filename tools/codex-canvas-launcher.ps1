# 上古影视工作流-FQLLG：给 Codex 用的画布工具启动器。
# 用法：复制到 %USERPROFILE%\.codex\shanggu-film-pipeline-fqllg\start-canvas.ps1，Codex 配置文件（~/.codex/config.toml）登记的是它。
# 为什么要它：Codex 的插件每次更新都装进一个新的版本文件夹，直接登记插件里的启动脚本，更新后路径就失效了。
# 它每次启动时去 Codex 的插件缓存里找版本号最大的那一版，再运行里面的 canvas-mcp\scripts\start-mcp.ps1。
# 依赖目录不用传：start-mcp.ps1 没收到 UV_PROJECT_ENVIRONMENT 时，默认用 %USERPROFILE%\.codex\shanggu-film-pipeline-fqllg\canvas-venv-<版本号>。
# 不放进 AppData：从 Claude 桌面版复制过去的文件会被系统存进 Claude 自己的私有文件夹，Codex 看不到（2026-10-22 实测）。

$cacheRoot = Join-Path $env:USERPROFILE '.codex\plugins\cache\shanggu-film\shanggu-film-pipeline-fqllg'
# 按版本号挑，不按修改时间：旧版本文件夹被别的程序碰过一下，修改时间就会变新。
$installed = @(Get-ChildItem -LiteralPath $cacheRoot -Directory -ErrorAction SilentlyContinue | Where-Object {
    Test-Path -LiteralPath (Join-Path $_.FullName 'canvas-mcp\scripts\start-mcp.ps1')
} | Sort-Object { $v = $null; if ([version]::TryParse($_.Name, [ref]$v)) { $v } else { [version]'0.0' } } -Descending)

if (-not $installed) {
    [Console]::Error.WriteLine("没找到 Codex 里装好的「上古影视工作流-FQLLG」插件（$cacheRoot）。请先在 Codex 里安装插件，再重启 Codex。")
    exit 1
}

& (Join-Path $installed[0].FullName 'canvas-mcp\scripts\start-mcp.ps1') @args
exit $LASTEXITCODE
