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
    throw "Clé SSH introuvable : $IdentityFile"
}

# DEUX catégories par chaîne :
#   1. LONGS sermons (directs terminés ≥20 min) → /streams
#   2. COURTS enseignements (3-20 min) → /videos
$channels = @(
    @{ Handle = "lamaisondesagesse" }
    @{ Handle = "cfrèresc" }
    @{ Handle = "EgliseGénérationDaniel" }
    @{ Handle = "ÉgliseVasesdHonneur" }
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

        Write-Host "--- @$handle/$tab [$label] ($($cat.MinSec)s → $($cat.MaxSec)s) ---"
        $args = $commonArgs + @(
            "--match-filter", $match,
            "--download-archive", $archive,
            "--output", $output,
            $url
        )
        & python @args
        if ($LASTEXITCODE -notin @(0, 101)) {
            Write-Warning "yt-dlp a échoué pour @$handle/$tab (code $LASTEXITCODE) — on continue"
        }
    }

    # SCP vers le VPS (tous les nouveaux .mp4 de la chaîne)
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
    & ssh -i $IdentityFile -o IdentitiesOnly=yes $sshTarget "mkdir -p '$remoteDir'"
    if ($LASTEXITCODE -ne 0) { throw "Création du dossier distant $remoteDir impossible" }

    foreach ($video in Get-ChildItem -LiteralPath $destination -Filter "*.mp4" -File) {
        if ($uploaded.Contains($video.Name)) { continue }

        Write-Host "Envoi HD vers le VPS : $($video.Name)"
        & scp -i $IdentityFile -o IdentitiesOnly=yes -- $video.FullName "${sshTarget}:$remoteDir/"
        if ($LASTEXITCODE -ne 0) { throw "Envoi impossible : $($video.Name)" }

        $info = Join-Path $destination "$($video.BaseName).info.json"
        if (Test-Path -LiteralPath $info) {
            & scp -i $IdentityFile -o IdentitiesOnly=yes -- $info "${sshTarget}:$remoteDir/"
            if ($LASTEXITCODE -ne 0) { throw "Envoi des métadonnées impossible : $info" }
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
    Write-Host "Demarrage du decoupage sur le VPS..."
    $remoteCmd = "cd /opt/vortex/repo; docker compose -f docker-compose.vps.yml run --rm --no-deps vortex python -m vortex clip"
    ssh -i $IdentityFile -o IdentitiesOnly=yes "$VpsUser@$VpsHost" $remoteCmd
    if ($LASTEXITCODE -ne 0) { throw "Le decoupage distant a echoue (code $LASTEXITCODE)" }
}

Write-Host "Synchronisation YouTube terminee."
