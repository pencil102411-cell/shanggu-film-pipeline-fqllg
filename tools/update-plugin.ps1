[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$marketplaceName = 'shanggu-film'
$pluginName = 'shanggu-film-pipeline-fqllg'
# 放在 .codex 文件夹里，不放 AppData：从 Claude 桌面版运行时，AppData 里新建的文件会被存进 Claude 的私有文件夹。
$stateRoot = Join-Path $env:USERPROFILE ".codex\$pluginName"
$logPath = Join-Path $stateRoot 'update.log'

New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null

function Write-UpdateLog {
    param([Parameter(Mandatory)][string]$Message)

    if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -gt 1MB) {
        Move-Item -LiteralPath $logPath -Destination "$logPath.old" -Force
    }
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Get-CodexExecutable {
    $command = Get-Command codex.exe -ErrorAction SilentlyContinue
    if ($command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
        return $command.Source
    }

    $binRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'OpenAI\Codex\bin'
    $candidate = Get-ChildItem -LiteralPath $binRoot -Filter 'codex.exe' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }

    throw '找不到 codex.exe。请先安装或更新 Codex。'
}

try {
    $codexExecutable = Get-CodexExecutable

    $upgradeOutput = & $codexExecutable plugin marketplace upgrade $marketplaceName --json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "插件市场更新失败：$($upgradeOutput -join ' ')"
    }

    $marketplaceRoot = Join-Path $HOME ".codex\.tmp\marketplaces\$marketplaceName"
    $remoteManifest = Join-Path $marketplaceRoot "plugins\$pluginName\.codex-plugin\plugin.json"
    if (-not (Test-Path -LiteralPath $remoteManifest -PathType Leaf)) {
        throw "远程市场中找不到插件：$pluginName"
    }

    $remoteVersion = (Get-Content -LiteralPath $remoteManifest -Raw -Encoding UTF8 | ConvertFrom-Json).version
    $pluginList = (& $codexExecutable plugin list --json 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw "读取插件状态失败：$pluginList"
    }
    $installedPlugins = ($pluginList | ConvertFrom-Json).installed
    $targetId = "$pluginName@$marketplaceName"
    $installed = $installedPlugins | Where-Object pluginId -eq $targetId | Select-Object -First 1

    if (-not $installed) {
        $otherSource = $installedPlugins | Where-Object name -eq $pluginName | Select-Object -First 1
        if ($otherSource) {
            Write-UpdateLog "发现同名插件 $($otherSource.pluginId)，为避免重复安装，本次跳过。远程版本：$remoteVersion"
            return
        }
    }

    if ($installed -and $installed.version -eq $remoteVersion) {
        Write-UpdateLog "已是最新版：$remoteVersion"
        return
    }

    if ($CheckOnly) {
        $currentVersion = if ($installed) { $installed.version } else { '未安装' }
        Write-UpdateLog "检测到可安装版本。当前：$currentVersion；远程：$remoteVersion"
        return
    }

    $installOutput = & $codexExecutable plugin add $targetId --json 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "插件安装失败：$($installOutput -join ' ')"
    }
    Write-UpdateLog "更新完成：$remoteVersion。新建 Codex 任务后生效。"
}
catch {
    Write-UpdateLog "更新失败：$($_.Exception.Message)"
    exit 1
}
