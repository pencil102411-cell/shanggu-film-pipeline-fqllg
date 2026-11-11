<#
深度视频工具（离线深度视频）的检查、安装和转换。

用法（普通 PowerShell 窗口，不用管理员）：
    depth-tool.ps1 check                          找本机有没有装工具（默认动作）
    depth-tool.ps1 check -ToolDir <文件夹>        工具装在别处时指给脚本，找到后会记住
    depth-tool.ps1 install                        只说明要装什么、多大、装到哪，不动手
    depth-tool.ps1 install -Yes                   用户同意后才加 -Yes，真正下载并安装
    depth-tool.ps1 install -Yes -PackagePath <压缩包>   用别人拷来的压缩包安装，不下载
    depth-tool.ps1 install -Yes -Force            本机已有但坏了时，再装一份到默认位置
    depth-tool.ps1 convert -Video <视频> [-Output <输出>] [-Start <秒>] [-Seconds <秒>]

退出码：0 正常；1 出错；2 本机没装工具；3 安装还没得到同意（没加 -Yes）。
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('check', 'install', 'convert')]
    [string]$Action = 'check',

    # convert：要转的视频、输出位置、从第几秒开始、转多少秒、深度图样式
    [string]$Video,
    [string]$Output,
    [double]$Start = 0,
    [double]$Seconds = 0,
    [ValidateSet('gray', 'turbo', 'magma', 'viridis', 'plasma', 'inferno', 'jet')]
    [string]$Colormap = 'gray',

    # 工具装在别处时手动指定
    [string]$ToolDir,

    # install：装到哪、用本地压缩包代替下载、用户已经同意、本机已有也再装一份（原来那份坏了时用）
    [string]$InstallDir,
    [string]$PackagePath,
    [switch]$Yes,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$toolName = '离线深度视频'
# 放在用户文件夹下，不放 AppData：从 Claude 桌面版运行时，AppData 里新建的文件会被存进 Claude 的私有文件夹，别的程序看不到。
$stateRoot = Join-Path $env:USERPROFILE '.shanggu-film-pipeline-fqllg'
$defaultInstallDir = Join-Path $stateRoot 'offline-video-depth'
$rememberFile = Join-Path $stateRoot 'depth-tool-path.txt'
$packageInfoPath = Join-Path $PSScriptRoot 'depth-tool-package.json'
$invariant = [Globalization.CultureInfo]::InvariantCulture

function Get-FullPath {
    param([Parameter(Mandatory)][string]$Path)
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path.Trim().Trim('"'))
}

# 一个文件夹算不算装好的工具：里面（或它的 engine* 子文件夹里）要有转换程序和模型
function Resolve-Tool {
    param([string]$Dir, [string]$FoundBy)

    if (-not $Dir) { return $null }
    $Dir = $Dir.Trim().Trim('"')
    if (-not (Test-Path -LiteralPath $Dir -PathType Container)) { return $null }

    $engines = @()
    if (Test-Path -LiteralPath (Join-Path $Dir 'depth-video.exe') -PathType Leaf) {
        $engines += (Get-Item -LiteralPath $Dir).FullName
    }
    $engines += @(Get-ChildItem -LiteralPath $Dir -Directory -Filter 'engine*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object FullName)

    foreach ($engine in $engines) {
        $exe = Join-Path $engine 'depth-video.exe'
        $model = Join-Path $engine 'model'
        if ((Test-Path -LiteralPath $exe -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $model 'config.json') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $model 'model.safetensors') -PathType Leaf)) {
            $ffmpeg = Join-Path $engine 'ffmpeg.exe'
            if (-not (Test-Path -LiteralPath $ffmpeg -PathType Leaf)) {
                $command = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
                $ffmpeg = if ($command) { $command.Source } else { '' }
            }
            return [pscustomobject]@{
                Root    = (Get-Item -LiteralPath $Dir).FullName
                Exe     = $exe
                Model   = $model
                Ffmpeg  = $ffmpeg
                FoundBy = $FoundBy
            }
        }
    }
    return $null
}

function Find-Tool {
    if ($ToolDir) {
        $tool = Resolve-Tool $ToolDir '手动指定'
        if (-not $tool) {
            throw "在 $ToolDir 里没有找到转换程序 depth-video.exe 和模型文件，请确认这是「$toolName」的安装文件夹。"
        }
        New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
        Set-Content -LiteralPath $rememberFile -Value $tool.Root -Encoding UTF8
        return $tool
    }

    # 1. 上次记住的位置
    if (Test-Path -LiteralPath $rememberFile -PathType Leaf) {
        $remembered = (Get-Content -LiteralPath $rememberFile -Encoding UTF8 | Select-Object -First 1)
        $tool = Resolve-Tool $remembered '上次记住的位置'
        if ($tool) { return $tool }
    }

    # 2. 本脚本的默认安装位置
    $tool = Resolve-Tool $defaultInstallDir '本插件安装的位置'
    if ($tool) { return $tool }

    # 3. 系统里的安装登记（用安装包装的会有）
    $uninstallRoots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $uninstallRoots) {
        foreach ($key in @(Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
            try { $props = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction Stop } catch { continue }
            if (($props.DisplayName -eq $toolName -or $key.PSChildName -eq $toolName) -and $props.InstallLocation) {
                $tool = Resolve-Tool $props.InstallLocation '系统里的安装登记'
                if ($tool) { return $tool }
            }
        }
    }

    # 4. 桌面和开始菜单里指向这个工具的快捷方式
    try {
        $shell = New-Object -ComObject WScript.Shell
        $links = @()
        foreach ($folder in 'Desktop', 'CommonDesktopDirectory') {
            $path = [Environment]::GetFolderPath($folder)
            if ($path) { $links += @(Get-ChildItem -LiteralPath $path -Filter '*.lnk' -File -ErrorAction SilentlyContinue) }
        }
        foreach ($folder in 'Programs', 'CommonPrograms') {
            $path = [Environment]::GetFolderPath($folder)
            if ($path) { $links += @(Get-ChildItem -LiteralPath $path -Filter '*.lnk' -File -Recurse -ErrorAction SilentlyContinue) }
        }
        foreach ($link in $links) {
            try { $target = $shell.CreateShortcut($link.FullName).TargetPath } catch { continue }
            if ($target -and ((Split-Path -Leaf $target) -ieq 'offline_video_depth.exe')) {
                $tool = Resolve-Tool (Split-Path -Parent $target) "快捷方式 $($link.Name)"
                if ($tool) { return $tool }
            }
        }
    }
    catch { }

    # 5. 常见位置
    $common = @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) $toolName),
        (Join-Path $env:LOCALAPPDATA "Programs\$toolName"),
        (Join-Path $env:LOCALAPPDATA $toolName),
        (Join-Path $env:LOCALAPPDATA 'Programs\offline_video_depth'),
        (Join-Path $env:ProgramFiles $toolName),
        (Join-Path $env:ProgramFiles 'offline_video_depth')
    )
    foreach ($dir in $common) {
        $tool = Resolve-Tool $dir '常见安装位置'
        if ($tool) { return $tool }
    }
    return $null
}

function Show-Tool {
    param([Parameter(Mandatory)]$Tool)

    $version = '未知'
    $app = Join-Path $Tool.Root 'offline_video_depth.exe'
    if (Test-Path -LiteralPath $app -PathType Leaf) {
        $productVersion = (Get-Item -LiteralPath $app).VersionInfo.ProductVersion
        if ($productVersion) { $version = $productVersion }
    }
    Write-Host "状态: 已安装"
    Write-Host "版本: $version"
    Write-Host "工具文件夹: $($Tool.Root)"
    Write-Host "转换程序: $($Tool.Exe)"
    Write-Host "模型: $($Tool.Model)"
    Write-Host ("FFmpeg: " + $(if ($Tool.Ffmpeg) { $Tool.Ffmpeg } else { '没找到（不影响转换，但没法先量时长和截取片段）' }))
    Write-Host "怎么找到的: $($Tool.FoundBy)"
}

function Show-NotInstalled {
    Write-Host "状态: 未安装"
    Write-Host "本机没有找到「$toolName」。找过的地方：上次记住的位置、$defaultInstallDir、系统里的安装登记、桌面和开始菜单的快捷方式、常见安装位置。"
    Write-Host "已经装在别处的：运行 check -ToolDir <工具所在文件夹>，脚本会记住。"
    Write-Host "没装的：运行 install 看要装什么、多大、装到哪；用户同意后运行 install -Yes。"
}

function Invoke-Captured {
    param([Parameter(Mandatory)][string]$File, [Parameter(Mandatory)][string[]]$Arguments)

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $File
    $startInfo.Arguments = ($Arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    $process = [Diagnostics.Process]::Start($startInfo)
    $errorTask = $process.StandardError.ReadToEndAsync()
    $stdout = $process.StandardOutput.ReadToEnd()
    $process.WaitForExit()
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Text = $stdout + $errorTask.Result }
}

# 用 FFmpeg 读视频的时长、尺寸、帧率；读不出来的项是 0
function Get-VideoInfo {
    param([Parameter(Mandatory)][string]$Ffmpeg, [Parameter(Mandatory)][string]$Path)

    $text = (Invoke-Captured $Ffmpeg @('-hide_banner', '-i', $Path)).Text
    $info = [pscustomobject]@{ Duration = 0.0; Width = 0; Height = 0; Fps = 0.0; HasAudio = $false }
    if ($text -match 'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)') {
        $info.Duration = [int]$Matches[1] * 3600 + [int]$Matches[2] * 60 + [double]::Parse($Matches[3], $invariant)
    }
    $videoLine = ($text -split "`n" | Where-Object { $_ -match 'Stream #.*Video:' } | Select-Object -First 1)
    if ($videoLine) {
        if ($videoLine -match '\b(\d{2,5})x(\d{2,5})\b') { $info.Width = [int]$Matches[1]; $info.Height = [int]$Matches[2] }
        if ($videoLine -match '([\d.]+)\s*fps') { $info.Fps = [double]::Parse($Matches[1], $invariant) }
    }
    $info.HasAudio = [bool]($text -split "`n" | Where-Object { $_ -match 'Stream #.*Audio:' } | Select-Object -First 1)
    return $info
}

function Format-Number {
    param([double]$Value, [int]$Digits = 2)
    return [Math]::Round($Value, $Digits).ToString($invariant)
}

function Invoke-Check {
    $tool = Find-Tool
    if (-not $tool) {
        Show-NotInstalled
        exit 2
    }
    Show-Tool $tool
}

function Invoke-Install {
    $tool = if ($Force) { $null } else { Find-Tool }
    if ($tool) {
        Write-Host '本机已经有这个工具，不重复安装。'
        Show-Tool $tool
        return
    }

    if (-not (Test-Path -LiteralPath $packageInfoPath -PathType Leaf)) {
        throw "找不到安装包信息文件：$packageInfoPath"
    }
    $package = Get-Content -LiteralPath $packageInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $target = if ($InstallDir) { Get-FullPath $InstallDir } else { $defaultInstallDir }
    if ((Test-Path -LiteralPath $target) -and (Get-ChildItem -LiteralPath $target -Force | Select-Object -First 1)) {
        throw "安装位置里已经有别的东西，不覆盖：$target。换一个位置（-InstallDir），或先看看里面是什么。"
    }

    $downloadMb = [Math]::Ceiling($package.download_bytes / 1MB)
    Write-Host "要装的东西: $($package.name) $($package.version)（把视频转成深度视频的离线工具，自带模型和 FFmpeg）"
    if ($PackagePath) {
        Write-Host "来源: 本地压缩包 $PackagePath（不下载）"
    }
    else {
        Write-Host "来源: $($package.url)"
        Write-Host "下载大小: 约 $downloadMb MB"
    }
    Write-Host "装好后占用: 约 $($package.unpacked_mb) MB"
    Write-Host "装到: $target"
    Write-Host '安装方式: 解压到上面的文件夹，不写注册表、不建快捷方式；不想要了直接删掉这个文件夹。'

    if (-not $Yes) {
        Write-Host '还没有开始安装。把上面这些告诉用户，用户同意后加 -Yes 再运行一次。'
        exit 3
    }
    if (-not $package.sha256) {
        throw '安装包的校验指纹还没登记（depth-tool-package.json 里的 sha256 是空的），不能安装。'
    }

    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    try {
        $free = (Get-PSDrive -Name $target.Substring(0, 1) -ErrorAction Stop).Free
        $need = [long]$package.unpacked_mb * 1MB + 200MB
        if (-not $PackagePath) { $need += [long]$package.download_bytes }
        if ($free -lt $need) {
            throw "磁盘空间不够：需要约 $([Math]::Ceiling($need / 1MB)) MB，$($target.Substring(0, 2)) 盘只剩 $([Math]::Floor($free / 1MB)) MB。"
        }
    }
    catch [System.Management.Automation.DriveNotFoundException] { }

    if ($PackagePath) {
        $zip = (Resolve-Path -LiteralPath (Get-FullPath $PackagePath)).Path
    }
    else {
        $zip = Join-Path $parent "$($package.file).part"
        $ready = (Test-Path -LiteralPath $zip -PathType Leaf) -and
            ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ieq $package.sha256)
        if (-not $ready) {
            Write-Host "正在下载（约 $downloadMb MB，中断后重新运行会接着下）……"
            $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
            if ($curl) {
                & $curl.Source -L --fail -sS --retry 3 -C - -o $zip $package.url
                if ($LASTEXITCODE -ne 0) {
                    throw "下载失败（curl 退出码 $LASTEXITCODE）。可能是网络问题，或下载地址上还没有这个文件：$($package.url)"
                }
            }
            else {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest -Uri $package.url -OutFile $zip -UseBasicParsing
            }
        }
    }

    Write-Host '正在核对安装包……'
    $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $package.sha256.ToLower()) {
        if (-not $PackagePath) { Remove-Item -LiteralPath $zip -Force }
        throw "安装包和登记的指纹对不上，没有安装。登记的是 $($package.sha256)，实际是 $actual。"
    }

    Write-Host '正在解压（几千个文件，要一两分钟）……'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $staging = "$target.unpacking"
    # Windows 自带的 PowerShell 解不开总长超过 260 个字符的路径，先量一下，免得解到一半才失败
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try { $longest = ($archive.Entries | ForEach-Object { $_.FullName.Length } | Measure-Object -Maximum).Maximum }
    finally { $archive.Dispose() }
    if ($staging.Length + 1 + $longest -ge 260) {
        throw "安装位置的路径太长（包里最长的文件路径有 $longest 个字符，加上安装位置超过了 Windows 的 260 个字符上限）。用 -InstallDir 换一个短一点的位置，比如 D:\offline-video-depth。"
    }
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, $staging)
    if (-not (Resolve-Tool $staging '解压检查')) {
        Remove-Item -LiteralPath $staging -Recurse -Force
        throw '解压出来的内容不完整（没有转换程序或模型），没有安装。'
    }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
    Move-Item -LiteralPath $staging -Destination $target
    if (-not $PackagePath) { Remove-Item -LiteralPath $zip -Force }

    Write-Host '安装完成。'
    $installed = Resolve-Tool $target '本插件安装的位置'
    if ($InstallDir) {
        New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
        Set-Content -LiteralPath $rememberFile -Value $installed.Root -Encoding UTF8
    }
    Show-Tool $installed
}

function Invoke-Convert {
    if (-not $Video) { throw '缺少 -Video：要转成深度视频的文件。' }
    $tool = Find-Tool
    if (-not $tool) {
        Show-NotInstalled
        exit 2
    }

    $source = Get-FullPath $Video
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "找不到要转的视频：$source" }
    if (-not $Output) {
        $Output = Join-Path (Split-Path -Parent $source) ([IO.Path]::GetFileNameWithoutExtension($source) + '_深度.mp4')
    }
    $target = Get-FullPath $Output
    if (Test-Path -LiteralPath $target) { throw "输出文件已经存在，不覆盖：$target。换一个文件名再转。" }
    if ($Start -lt 0 -or $Seconds -lt 0) { throw '-Start 和 -Seconds 不能是负数。' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null

    $length = $Seconds
    if ($tool.Ffmpeg) {
        $info = Get-VideoInfo $tool.Ffmpeg $source
        Write-Host "原视频: $source"
        Write-Host ("原视频信息: 时长 {0} 秒，{1}×{2}，{3} 帧/秒，{4}" -f (Format-Number $info.Duration), $info.Width, $info.Height,
            (Format-Number $info.Fps 3), $(if ($info.HasAudio) { '有声音' } else { '没有声音' }))
        if ($info.Duration -gt 0) {
            if ($Start -ge $info.Duration) { throw "-Start（$Start 秒）已经超过原视频时长（$(Format-Number $info.Duration) 秒）。" }
            $rest = $info.Duration - $Start
            if ($length -le 0 -or $length -gt $rest) { $length = $rest }
            if ($info.Fps -gt 0) {
                $frames = [Math]::Ceiling($length * $info.Fps)
                # 每秒约 1.4 帧是一台电脑上只用 CPU、1470×630 时实测的速度，只用来给个大概
                Write-Host ("要转的范围: 从第 {0} 秒起，共 {1} 秒，约 {2} 帧" -f (Format-Number $Start), (Format-Number $length), $frames)
                Write-Host ("预计耗时: 约 {0} 分钟（按每秒处理 1.4 帧估算，电脑不同差别很大）" -f [Math]::Max(1, [Math]::Ceiling($frames / 1.4 / 60)))
            }
        }
    }
    elseif ($Start -gt 0) {
        throw '没有找到 FFmpeg，没法从中间截取片段。可以只用 -Seconds 转开头的一段。'
    }

    $engineInput = $source
    $engineArgs = @()
    $cut = ''
    if ($Start -gt 0) {
        # 从中间取一段：先用 FFmpeg 按帧精确截出来（高质量重新编码，不带声音），再转深度
        $cut = "$target.cut.mp4"
        $cutArgs = @('-hide_banner', '-loglevel', 'error', '-y', '-ss', $Start.ToString($invariant))
        if ($length -gt 0) { $cutArgs += @('-t', $length.ToString($invariant)) }
        $cutArgs += @('-i', $source, '-an', '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', $cut)
        $result = Invoke-Captured $tool.Ffmpeg $cutArgs
        if ($result.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $cut -PathType Leaf)) {
            throw "截取片段失败：$($result.Text.Trim())"
        }
        $engineInput = $cut
    }
    elseif ($Seconds -gt 0) {
        $engineArgs += @('--seconds', $Seconds.ToString($invariant))
    }

    Write-Host '正在转换……'
    try {
        & $tool.Exe $engineInput -o $target --model $tool.Model --colormap $Colormap @engineArgs
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($cut -and (Test-Path -LiteralPath $cut)) { Remove-Item -LiteralPath $cut -Force }
    }
    if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "转换失败（转换程序退出码 $exitCode），没有生成深度视频。"
    }

    # 转换程序会在输出旁边写一份 .json，记着帧数、帧率、尺寸、时长
    $meta = $null
    $metaPath = "$target.json"
    if (Test-Path -LiteralPath $metaPath -PathType Leaf) {
        $meta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    elseif ($tool.Ffmpeg) {
        $probe = Get-VideoInfo $tool.Ffmpeg $target
        $meta = [pscustomobject]@{ duration_seconds = $probe.Duration; width = $probe.Width; height = $probe.Height; fps = $probe.Fps; frames = 0 }
    }
    $sizeMb = (Get-Item -LiteralPath $target).Length / 1MB

    Write-Host "深度视频: $target"
    Write-Host "样式: $Colormap；没有声音（转换程序不带原视频的声音）"
    if (-not $meta) {
        Write-Host ("文件大小: {0} MB。没读到时长和尺寸，请另行核对。" -f (Format-Number $sizeMb))
        return
    }
    Write-Host ("信息: 时长 {0} 秒，{1}×{2}，{3} 帧/秒，共 {4} 帧，{5} MB" -f (Format-Number $meta.duration_seconds), $meta.width, $meta.height,
        (Format-Number $meta.fps 3), $meta.frames, (Format-Number $sizeMb))

    # 平台对参考视频的要求。数值来自 shared/Seedance平台.md「一、能力和上限」，那边改了这里要同步。
    $problems = @()
    if ($meta.duration_seconds -lt 4) { $problems += '时长不足 4 秒，不能单独当参考视频' }
    if ($meta.duration_seconds -gt 30) { $problems += '时长超过 30 秒，要先截短' }
    if ($meta.fps -lt 24 -or $meta.fps -gt 60) { $problems += '帧率不在 24–60 之间' }
    if ($sizeMb -gt 200) { $problems += '文件超过 200 MB' }
    if ($meta.width -gt 0 -and $meta.height -gt 0) {
        $ratio = $meta.width / $meta.height
        $pixels = [long]$meta.width * $meta.height
        if ([Math]::Min($meta.width, $meta.height) -lt 300 -or [Math]::Max($meta.width, $meta.height) -gt 6000) { $problems += '边长不在 300–6000 像素之间' }
        if ($ratio -lt 0.4 -or $ratio -gt 2.5) { $problems += '宽高比不在 0.4–2.5 之间' }
        if ($pixels -lt 407696 -or $pixels -gt 8295044) { $problems += '总像素不在 407,696–8,295,044 之间' }
    }
    if ($problems.Count -eq 0) {
        Write-Host '对照平台要求: 时长、帧率、尺寸、大小都符合，可以当参考视频。'
    }
    else {
        Write-Host ('对照平台要求: 不符合——' + ($problems -join '；') + '。')
    }
}

try {
    switch ($Action) {
        'check' { Invoke-Check }
        'install' { Invoke-Install }
        'convert' { Invoke-Convert }
    }
}
catch {
    Write-Host "出错：$($_.Exception.Message)"
    exit 1
}
