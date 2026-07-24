[CmdletBinding()]
param(
    [string]$VpsHost = "187.127.235.148",
    [string]$VpsUser = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\vortex_vps",
    [int]$Batch = 1,
    [int]$MinimumMinutes = 20,
    [int]$ScanLimit = 50,
    [switch]$StartRemoteClip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repoRoot "videos\sources"
$remoteRoot = "/opt/vortex/repo/videos/sources"
$minimumSeconds = $MinimumMinutes * 60

if (-not (Test-Path -LiteralPath $IdentityFile)) {
    throw "Clé SSH introuvable : $IdentityFile"
}

# La chaîne principale demandée. Les sermons complets sont dans /streams,
# pas parmi les clips promotionnels de /videos.
$sources = @(
    @{
        Handle = "lamaisondesagesse"
        Url = "https://www.youtube.com/@lamaisondesagesse/streams"
    }
)

foreach ($source in $sources) {
    $handle = $source.Handle
    $destination = Join-Path $sourceRoot $handle
    New-Item -ItemType Directory -Force -Path $destination | Out-Null

    $archive = Join-Path $destination ".archive.txt"
    $output = Join-Path $destination "%(upload_date)s_%(id)s.%(ext)s"
    $downloadArgs = @(
        "-m", "yt_dlp",
        "--playlist-end", "$ScanLimit",
        "--max-downloads", "$Batch",
        "--match-filter", "duration >= $minimumSeconds & live_status != is_live",
        "--format", "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]",
        "--merge-output-format", "mp4",
        "--download-archive", $archive,
        "--write-info-json",
        "--retries", "10",
        "--fragment-retries", "10",
        "--concurrent-fragments", "4",
        "--js-runtimes", "node",
        "--output", $output,
        $source.Url
    )

    Write-Host "Recherche des sermons longs récents sur @$handle/streams..."
    & python @downloadArgs
    if ($LASTEXITCODE -notin @(0, 101)) {
        throw "yt-dlp a échoué pour @$handle (code $LASTEXITCODE)"
    }

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
    if ($LASTEXITCODE -ne 0) { throw "Création du dossier distant impossible" }

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
    Write-Host "Démarrage du découpage sur le VPS..."
    & ssh -i $IdentityFile -o IdentitiesOnly=yes "$VpsUser@$VpsHost" `
        "cd /opt/vortex/repo && docker compose -f docker-compose.vps.yml run --rm --no-deps vortex python -m vortex clip"
    if ($LASTEXITCODE -ne 0) { throw "Le découpage distant a échoué" }
}

Write-Host "Synchronisation YouTube terminée."
