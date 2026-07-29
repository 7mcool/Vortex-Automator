# Poste de decoupage : telecharge un sermon, le decoupe ICI, envoie les extraits.
#
# Le VPS a 2 coeurs et environ 800 Mo de RAM libre : il ne decoupait pas assez
# vite, et 9,5 Go de sermons s y etaient accumules jusqu a saturer le disque a
# 99 %. Le PC traite une conference de 3 h 25 en deux heures et dispose de plus
# de 100 Go. On lui confie donc le gros oeuvre ; le serveur ne recoit que les
# extraits, cent fois plus legers que la source.
#
# Enchainement : yt-dlp (cookies Firefox) -> vortex clip -> scp des extraits.
# La source est effacee des qu elle est entierement decoupee.

[CmdletBinding()]
param(
    [string]$VpsHost = "187.127.235.148",
    [string]$VpsUser = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\vortex_vps",
    [int]$ScanLimit = 50,
    [int]$MaxSources = 1,          # sermons telecharges par passage
    [switch]$SkipDownload          # ne decouper que ce qui est deja la
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repoRoot "videos\sources"
$clipsDir = Join-Path $repoRoot "videos\clips_horizontaux"
$remoteDir = "/opt/vortex/repo/videos/hedjav"
$sshTarget = "$VpsUser@$VpsHost"

if (-not (Test-Path -LiteralPath $IdentityFile)) { throw "Cle SSH introuvable : $IdentityFile" }
New-Item -ItemType Directory -Force -Path $clipsDir | Out-Null

# Deux categories par chaine : les directs longs (/streams) et le hors-direct
# (/videos) a partir de trois minutes.
$channels = @("JACAMESSANLIVE", "lamaisondesagesse", "cfreresc",
              "EgliseGenerationDaniel", "EgliseVasesdHonneur")
$categories = @(
    @{ Tab = "streams"; MinSec = 1200 }
    @{ Tab = "videos";  MinSec = 180 }
)

function Get-SourceCount {
    (Get-ChildItem -LiteralPath $sourceRoot -Filter *.mp4 -Recurse -File -ErrorAction SilentlyContinue).Count
}

# ---------- 1. Telechargement ----------
if (-not $SkipDownload) {
    foreach ($chan in $channels) {
        if ((Get-SourceCount) -ge $MaxSources) {
            Write-Host "Assez de sources en attente de decoupage - telechargement suspendu"
            break
        }
        $dest = Join-Path $sourceRoot $chan
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        foreach ($cat in $categories) {
            if ((Get-SourceCount) -ge $MaxSources) { break }
            $url = "https://www.youtube.com/@$chan/$($cat.Tab)"
            Write-Host "--- @$chan/$($cat.Tab) (>= $($cat.MinSec)s) ---"
            $dlArgs = @(
                "-m", "yt_dlp",
                "--cookies-from-browser", "firefox",
                "--format", "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]",
                "--merge-output-format", "mp4",
                "--write-info-json",
                "--retries", "10", "--fragment-retries", "10",
                "--concurrent-fragments", "4",
                "--js-runtimes", "node",
                "--playlist-end", "$ScanLimit",
                "--max-downloads", "1",
                "--match-filter", "duration >= $($cat.MinSec) & live_status != is_live",
                "--download-archive", (Join-Path $dest ".archive.txt"),
                "--output", (Join-Path $dest "%(upload_date)s_%(id)s.%(ext)s"),
                "--no-progress", $url
            )
            & python @dlArgs
            # 101 = limite --max-downloads atteinte, c'est un succes normal.
            if ($LASTEXITCODE -notin @(0, 101)) {
                Write-Warning "yt-dlp a echoue pour @$chan/$($cat.Tab) (code $LASTEXITCODE)"
            }
        }
    }
}

# ---------- 2. Decoupage ----------
# `vortex clip` ne traite qu'une source par appel : on boucle tant qu'il en
# reste et que le compte diminue. Une source qui ne disparait pas a echoue et
# reviendrait indefiniment.
$restant = Get-SourceCount
while ($restant -gt 0) {
    Write-Host "Decoupage ($restant source(s) en attente)..."
    & python -m vortex clip
    $apres = Get-SourceCount
    if ($apres -ge $restant) {
        Write-Host "Aucune source resorbee a ce tour - arret du decoupage"
        break
    }
    $restant = $apres
}

# ---------- 3. Envoi des extraits ----------
$journal = Join-Path $clipsDir ".envoyes.txt"
$envoyes = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
if (Test-Path -LiteralPath $journal) {
    foreach ($l in [System.IO.File]::ReadAllLines($journal)) {
        if ($l.Trim()) { [void]$envoyes.Add($l.Trim()) }
    }
}

$aEnvoyer = Get-ChildItem -LiteralPath $clipsDir -Filter *.mp4 -File |
            Where-Object { -not $envoyes.Contains($_.Name) }
if (-not $aEnvoyer) {
    Write-Host "Aucun nouvel extrait a envoyer."
    return
}

ssh -i $IdentityFile -o IdentitiesOnly=yes $sshTarget "mkdir -p '$remoteDir'"
if ($LASTEXITCODE -ne 0) { throw "Dossier distant inaccessible (code $LASTEXITCODE)" }

foreach ($clip in $aEnvoyer) {
    # Le serveur est partage et frole souvent la saturation : on verifie avant
    # CHAQUE envoi plutot qu'une seule fois, sinon on le remplit d'un coup.
    $libreMo = ssh -i $IdentityFile -o IdentitiesOnly=yes $sshTarget "df -Pm / | awk 'NR==2{print `$4}'"
    if ([int]$libreMo -lt 4096) {
        Write-Warning "Seulement $libreMo Mo libres sur le serveur - envoi interrompu, reprise au prochain passage"
        break
    }

    Write-Host ("Envoi {0} ({1:N0} Mo, {2} Mo libres)" -f $clip.Name, ($clip.Length/1MB), $libreMo)
    scp -i $IdentityFile -o IdentitiesOnly=yes -- $clip.FullName "${sshTarget}:$remoteDir/"
    if ($LASTEXITCODE -ne 0) { Write-Warning "Envoi echoue : $($clip.Name)"; continue }

    $info = Join-Path $clipsDir "$($clip.BaseName).info.json"
    if (Test-Path -LiteralPath $info) {
        scp -i $IdentityFile -o IdentitiesOnly=yes -- $info "${sshTarget}:$remoteDir/"
    }
    [System.IO.File]::AppendAllText($journal, $clip.Name + [Environment]::NewLine,
                                    [System.Text.UTF8Encoding]::new($false))
    [void]$envoyes.Add($clip.Name)
    # L'extrait vit desormais sur le serveur : le garder ici doublerait
    # l'occupation sans servir a rien.
    Remove-Item -LiteralPath $clip.FullName -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $info) { Remove-Item -LiteralPath $info -Force -ErrorAction SilentlyContinue }
}

Write-Host "Decoupage et envoi termines."
