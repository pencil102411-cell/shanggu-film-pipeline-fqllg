[CmdletBinding()]
param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$pluginName = 'shanggu-film-pipeline-fqllg'
$taskName = 'Codex - 上古影视工作流-FQLLG 自动更新'
# 放在 .codex 文件夹里，不放 AppData：从 Claude 桌面版运行时，复制到 AppData 的更新脚本会被存进 Claude 的私有文件夹，
# Windows 定时任务到点运行时看不到它。
$stateRoot = Join-Path $env:USERPROFILE ".codex\$pluginName"
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

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description '自动检查并安装上古影视工作流-FQLLG 更新。' -Force | Out-Null

Write-Host "自动更新已启用：Windows 登录时和每天 12:00 检查。"
Write-Host "日志：$stateRoot\update.log"

& $installedUpdater
if ($LASTEXITCODE -ne 0) {
    throw '自动更新任务已创建，但首次更新检查失败。请查看日志。'
}
