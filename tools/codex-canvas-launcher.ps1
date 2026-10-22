# 上古影视工作流-FQLLG：给 Codex 用的画布工具启动器。
# 用法：复制到 %LOCALAPPDATA%\shanggu-film-pipeline-fqllg\start-canvas.ps1，Codex 配置文件（~/.codex/config.toml）登记的是它。
# 为什么要它：Codex 的插件每次更新都装进一个新的版本文件夹，直接登记插件里的启动脚本，更新后路径就失效了。
# 它每次启动时去 Codex 的插件缓存里找最新装好的那一版，再运行里面的 canvas-mcp\scripts\start-mcp.ps1。
# 依赖目录不用传：start-mcp.ps1 没收到 UV_PROJECT_ENVIRONMENT 时，默认用 %LOCALAPPDATA%\shanggu-film-pipeline-fqllg\canvas-venv-<版本号>。

$cacheRoot = Join-Path $env:USERPROFILE '.codex\plugins\cache\shanggu-film\shanggu-film-pipeline-fqllg'
$installed = @(Get-ChildItem -LiteralPath $cacheRoot -Directory -ErrorAction SilentlyContinue | Where-Object {
    Test-Path -LiteralPath (Join-Path $_.FullName 'canvas-mcp\scripts\start-mcp.ps1')
} | Sort-Object LastWriteTime -Descending)

if (-not $installed) {
    [Console]::Error.WriteLine("没找到 Codex 里装好的「上古影视工作流-FQLLG」插件（$cacheRoot）。请先在 Codex 里安装插件，再重启 Codex。")
    exit 1
}

& (Join-Path $installed[0].FullName 'canvas-mcp\scripts\start-mcp.ps1') @args
exit $LASTEXITCODE
