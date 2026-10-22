<#
.SYNOPSIS
  Stack the edit master (top) and an edited output (bottom) into one review video
  that plays the master's audio track. Both halves get a text label.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File make-compare.ps1 -Master master.mov -Edited edit.mp4 -Out compare.mp4 -TopLabel "master" -BottomLabel "edit pass 1"

.NOTES
  - Length = the shorter of the two clips (frame count), so both halves start on frame 0.
    Check the cut index of each file first if the output's frame count differs from the master.
  - Canvas size = the larger of the two inputs (by width); the other is scaled with lanczos.
  - Labels are written to UTF-8 (no BOM) text files and drawn with drawtext textfile=,
    which avoids command-line encoding problems with CJK text on Windows PowerShell 5.1.
  - Tested with ffmpeg 9.0.2 on Windows 10.
#>
param(
  [Parameter(Mandatory = $true)][string]$Master,
  [Parameter(Mandatory = $true)][string]$Edited,
  [Parameter(Mandatory = $true)][string]$Out,
  [string]$TopLabel = "Master",
  [string]$BottomLabel = "Edited",
  [string]$FontFile = "C:\Windows\Fonts\msyh.ttc",
  [int]$Crf = 18
)
$ErrorActionPreference = "Stop"

function Get-VideoInfo([string]$path) {
  $line = & ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=width,height,nb_read_frames,r_frame_rate -of csv=p=0 $path
  $p = $line.Trim().Split(',')
  $rate = $p[2].Split('/')
  [pscustomobject]@{ W = [int]$p[0]; H = [int]$p[1]; Fps = [double]$rate[0] / [double]$rate[1]; Frames = [int]$p[3] }
}

$m = Get-VideoInfo $Master
$e = Get-VideoInfo $Edited
$n = [math]::Min($m.Frames, $e.Frames)
if ($e.W -gt $m.W) { $w = $e.W; $h = $e.H } else { $w = $m.W; $h = $m.H }
if ($w % 2) { $w++ }
if ($h % 2) { $h++ }
$sec = "{0:F6}" -f ($n / $m.Fps)

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("cmp_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $tmp | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $tmp "top.txt"), $TopLabel, $utf8)
[IO.File]::WriteAllText((Join-Path $tmp "bot.txt"), $BottomLabel, $utf8)

function Esc([string]$p) { $p.Replace('\', '/').Replace(':', '\:') }
$fs = [int][math]::Max(18, [math]::Round($h / 20))
$pad = [int]($fs * 0.7)
$bw = [int][math]::Floor($pad / 2)
$draw = ""
if (Test-Path -LiteralPath $FontFile) {
  $draw = ",drawtext=fontfile='" + (Esc $FontFile) + "':fontsize=$($fs):fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=$($bw):x=$($pad):y=$($pad)"
} else {
  Write-Warning "Font not found: $FontFile - labels skipped."
}
$topDraw = if ($draw) { $draw + ":textfile='" + (Esc (Join-Path $tmp "top.txt")) + "'" } else { "" }
$botDraw = if ($draw) { $draw + ":textfile='" + (Esc (Join-Path $tmp "bot.txt")) + "'" } else { "" }

$fc = "[0:v]trim=end_frame=$n,setpts=PTS-STARTPTS,scale=$($w):$($h):flags=lanczos$topDraw[a];" +
      "[1:v]trim=end_frame=$n,setpts=PTS-STARTPTS,scale=$($w):$($h):flags=lanczos$botDraw[b];" +
      "[a][b]vstack=inputs=2[v];[0:a]atrim=end=$sec,asetpts=PTS-STARTPTS[au]"

& ffmpeg -hide_banner -loglevel error -y -i $Master -i $Edited -filter_complex $fc -map "[v]" -map "[au]" -c:v libx264 -crf $Crf -preset medium -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart $Out
Remove-Item -LiteralPath $tmp -Recurse -Force
if ($LASTEXITCODE -ne 0) { throw "ffmpeg failed ($LASTEXITCODE)" }

$o = Get-VideoInfo $Out
"{0}: {1}x{2}, {3} frames (master {4}, edited {5})" -f $Out, $o.W, $o.H, $o.Frames, $m.Frames, $e.Frames
