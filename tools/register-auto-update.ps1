[CmdletBinding()]
param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$pluginName = 'shanggu-film-pipeline-fqllg'
$taskName = 'Codex - 上古影视工作流-FQLLG 自动更新'
$stateRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "Codex\$pluginName"
$installedUpdater = Join-Path $stateRoot 'update-plugin.ps1'

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Host '自动更新任务已移除。'
    exit 0
}

$sourceUpdater = Join-Path $PSScriptRoot 'update-plugin.ps1'
if (-not (Test-Path -LiteralPath $sourceUpdater -PathType Leaf)) {
    throw "缺少更新脚本：$sourceUpdater"
}

New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
Copy-Item -LiteralPath $sourceUpdater -Destination $installedUpdater -Force

$powerShell = Get-Command powershell.exe -ErrorAction SilentlyContinue
if (-not $powerShell) {
    $powerShell = Get-Command pwsh.exe -ErrorAction Stop
}

$actionArgs = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$installedUpdater`""
$action = New-ScheduledTaskAction -Execute $powerShell.Source -Argument $actionArgs
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    New-ScheduledTaskTrigger -Daily -At '12:00'
)
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description '自动检查并安装横屏影视提示词 Agent 2.0 更新。' -Force | Out-Null

Write-Host "自动更新已启用：Windows 登录时和每天 12:00 检查。"
Write-Host "日志：$stateRoot\update.log"

& $installedUpdater
if ($LASTEXITCODE -ne 0) {
    throw '自动更新任务已创建，但首次更新检查失败。请查看日志。'
}
