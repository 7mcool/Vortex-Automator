[CmdletBinding()]
param(
    [string]$VpsHost = "187.127.235.148",
    [string]$VpsUser = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\vortex_vps",
    [int]$Batch = 1,
    [int]$ScanLimit = 50,
    [switch]$StartRemoteClip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repoRoot "videos\sources"
$remoteRoot = "/opt/vortex/repo/videos/sources"

if (-not (Test-Path -LiteralPath $IdentityFile)) {
    throw "Cle SSH introuvable : $IdentityFile"
}

# DEUX categories par chaine :
#   1. LONGS sermons (directs termines >= 20 min) -> /streams
#   2. COURTS enseignements (3-20 min) -> /videos
# Handles must match VPS fetch_youtube.sh directory names exactly
$channels = @(
    @{ Handle = "lamaisondesagesse" }
    @{ Handle = "cfreresc" }
    @{ Handle = "EgliseGenerationDaniel" }
    @{ Handle = "EgliseVasesdHonneur" }
)

$categories = @(
    @{ Tab = "streams"; MinSec = 1200; MaxSec = 0;    Label = "long" }
    @{ Tab = "videos";  MinSec = 180;  MaxSec = 1200; Label = "court" }
)

$commonArgs = @(
    "-m", "yt_dlp",
    "--format", "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]",
    "--merge-output-format", "mp4",
    "--write-info-json",
    "--retries", "10",
    "--fragment-retries", "10",
    "--concurrent-fragments", "4",
    "--js-runtimes", "node",
    "--playlist-end", "$ScanLimit",
    "--max-downloads", "$Batch"
)

foreach ($chan in $channels) {
    $handle = $chan.Handle
    foreach ($cat in $categories) {
        $tab = $cat.Tab
        $label = $cat.Label
        $destination = Join-Path $sourceRoot "$handle"
        New-Item -ItemType Directory -Force -Path $destination | Out-Null

        $archive = Join-Path $destination ".archive.txt"
        $output = Join-Path $destination "%(upload_date)s_%(id)s.%(ext)s"
        $url = "https://www.youtube.com/@$handle/$tab"

        $match = "duration >= $($cat.MinSec) & live_status != is_live"
        if ($cat.MaxSec -gt 0) {
            $match += " & duration <= $($cat.MaxSec)"
        }

        Write-Host "--- @$handle/$tab [$label] ($($cat.MinSec)s -> $($cat.MaxSec)s) ---"
        $dlArgs = $commonArgs + @(
            "--match-filter", $match,
            "--download-archive", $archive,
            "--output", $output,
            $url
        )
        & python @dlArgs
        if ($LASTEXITCODE -notin @(0, 101)) {
            Write-Warning "yt-dlp failed for @$handle/$tab (code $LASTEXITCODE) - continuing"
        }
    }

    # SCP to VPS (all new .mp4 for this channel)
    $uploadedFile = Join-Path $destination ".uploaded-to-vps.txt"
    $uploaded = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    if (Test-Path -LiteralPath $uploadedFile) {
        foreach ($line in [System.IO.File]::ReadAllLines($uploadedFile)) {
            if ($line.Trim()) { [void]$uploaded.Add($line.Trim()) }
        }
    }

    $remoteDir = "$remoteRoot/$handle"
    $sshTarget = "$VpsUser@$VpsHost"
    ssh -i $IdentityFile -o IdentitiesOnly=yes $sshTarget "mkdir -p '$remoteDir'"
    if ($LASTEXITCODE -ne 0) { throw "Cannot create remote directory: $remoteDir (code $LASTEXITCODE)" }

    foreach ($video in Get-ChildItem -LiteralPath $destination -Filter "*.mp4" -File) {
        if ($uploaded.Contains($video.Name)) { continue }

        Write-Host "Upload to VPS: $($video.Name)"
        scp -i $IdentityFile -o IdentitiesOnly=yes -- $video.FullName "${sshTarget}:$remoteDir/"
        if ($LASTEXITCODE -ne 0) { throw "SCP failed: $($video.Name) (code $LASTEXITCODE)" }

        $info = Join-Path $destination "$($video.BaseName).info.json"
        if (Test-Path -LiteralPath $info) {
            scp -i $IdentityFile -o IdentitiesOnly=yes -- $info "${sshTarget}:$remoteDir/"
            if ($LASTEXITCODE -ne 0) { throw "SCP metadata failed: $info (code $LASTEXITCODE)" }
        }

        [System.IO.File]::AppendAllText(
            $uploadedFile,
            $video.Name + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
        [void]$uploaded.Add($video.Name)
    }
}

if ($StartRemoteClip) {
    Write-Host "Starting clip on VPS..."
    ssh -i $IdentityFile -o IdentitiesOnly=yes "$VpsUser@$VpsHost" "cd /opt/vortex/repo; docker compose -f docker-compose.vps.yml run --rm --no-deps vortex python -m vortex clip"
    if ($LASTEXITCODE -ne 0) { throw "Remote clipping failed (code $LASTEXITCODE)" }
}

Write-Host "YouTube sync complete."
