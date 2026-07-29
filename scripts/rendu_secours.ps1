# Renfort d'habillage : le PC prend du travail au serveur, quand il est allume.
#
# Le serveur met environ cinquante minutes a habiller un extrait ; le PC en met
# quelques-unes. Arrangement TEMPORAIRE demande par Michel : ce script ne fait
# rien passe la date limite ci-dessous, et rien non plus si le serveur n'a pas
# de retard. Le serveur reste autonome — le PC ne fait qu'accelerer.
#
# Astuce : on recree sur le PC l'arborescence du conteneur (C:\app\...), si
# bien que les chemins enregistres en base tombent juste et que `vortex render`
# tourne sans la moindre adaptation.

[CmdletBinding()]
param(
    [string]$VpsHost = "187.127.235.148",
    [string]$VpsUser = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\vortex_vps",
    [int]$Lot = 4,
    [datetime]$JusquAu = "2026-08-05",     # arrangement d'une semaine
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$ssh = @("-i", $IdentityFile, "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=20")
$cible = "$VpsUser@$VpsHost"
$distant = "/opt/vortex/repo"

if ((Get-Date) -gt $JusquAu -and -not $Force) {
    Write-Host "Arrangement termine (limite $($JusquAu.ToString('dd/MM'))) - le serveur habille seul."
    return
}
if (-not (Test-Path -LiteralPath $IdentityFile)) { throw "Cle SSH introuvable" }

# Arborescence miroir du conteneur : les chemins de la base y tombent juste.
$app = "C:\app"
foreach ($d in @("$app\data", "$app\data\exports", "$app\data\thumbs",
                 "$app\data\words", "$app\data\subtitles", "$app\videos\hedjav")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

Write-Host "Recuperation de l'etat du serveur..."
scp @ssh "${cible}:$distant/data/vortex.db" "$app\data\vortex.db"
if ($LASTEXITCODE -ne 0) { throw "Base inaccessible" }

# Quelles videos attendent leur habillage ? On interroge la copie locale.
$requete = @"
import sqlite3, json
db = sqlite3.connect(r'$app\data\vortex.db'); db.row_factory = sqlite3.Row
lignes = db.execute('''SELECT id, name, path FROM videos WHERE state = 'READY'
                       AND (render_path IS NULL OR render_path = '')
                       ORDER BY rowid DESC LIMIT $Lot''').fetchall()
print(json.dumps([dict(r) for r in lignes]))
"@
$attente = python -c $requete | ConvertFrom-Json
if (-not $attente) { Write-Host "Aucun habillage en attente - rien a faire."; return }
Write-Host "$($attente.Count) extrait(s) a habiller"

# Rapatrier les sources et leurs annexes (mots horodates pour les sous-titres).
foreach ($v in $attente) {
    $nom = Split-Path $v.path -Leaf
    $local = "$app\videos\hedjav\$nom"
    # La base garde les chemins vus DEPUIS le conteneur (/app/...). Sur l'hote
    # ils vivent sous /opt/vortex/repo/ : sans cette traduction, scp cherche un
    # /app inexistant.
    $surHote = $v.path -replace '^/app/', "$distant/"
    if (-not (Test-Path -LiteralPath $local)) {
        Write-Host "  <- $nom"
        scp @ssh "${cible}:$surHote" $local
        if ($LASTEXITCODE -ne 0) { Write-Warning "  source indisponible : $nom"; continue }
    }
    foreach ($annexe in @("words/$($v.name).json", "subtitles/$($v.name).srt")) {
        scp @ssh "${cible}:$distant/data/$annexe" "$app\data\$annexe" 2>$null
    }
}

# Config calquee sur celle du conteneur, pour que les chemins coincident.
# Ecrite SANS marque d'ordre : `Set-Content -Encoding utf8` en ajoute une sous
# PowerShell 5.1, et tomllib refuse alors le fichier des le premier caractere.
$conf = "$app\config.toml"
$contenu = @"
[paths]
source_dir = 'C:\app\videos\hedjav'
data_dir = 'C:\app\data'
tokkit_db = 'C:\app\data\inexistant.sqlite'
client_secret_file = '$repoRoot\secrets\client_secret.json'
token_file = '$repoRoot\secrets\youtube_token.json'
sources_dir = 'C:\app\videos\sources'
tiktok_queue_dir = 'C:\app\videos\tiktok_queue'

[publish]
hours = [3, 7, 11, 14, 17, 20]
daily_limit = 6
timezone = "Africa/Porto-Novo"

[whisper]
model = "small"
device = "cpu"
compute_type = "int8"

[seo]
channel_name = "Sophos PropheTikos"
known_speakers = ["Jacques Amessan", "Mohammed Sanogo", "Yannick Djatti", "Aimé Bodjiyé"]
"@
[System.IO.File]::WriteAllText($conf, $contenu, [System.Text.UTF8Encoding]::new($false))

Write-Host "Habillage sur le PC..."
$env:VORTEX_CONFIG = $conf
$env:PYTHONIOENCODING = "utf-8"
Push-Location $repoRoot
try {
    # Python journalise sur la sortie d'erreur. Avec ErrorActionPreference a
    # "Stop", PowerShell prend chacune de ces lignes pour une erreur fatale et
    # interrompt le script alors que l'habillage s'est bien passe. On relache
    # donc la regle le temps des appels, et on juge sur le code de retour.
    $ErrorActionPreference = "Continue"
    & python -m vortex render -n $Lot
    if ($LASTEXITCODE -ne 0) { Write-Warning "habillage : code $LASTEXITCODE" }
    & python -m vortex thumbs -n $Lot
    if ($LASTEXITCODE -ne 0) { Write-Warning "miniatures : code $LASTEXITCODE" }
} finally {
    $ErrorActionPreference = "Stop"
    Pop-Location
    Remove-Item Env:\VORTEX_CONFIG -ErrorAction SilentlyContinue
}

# Renvoyer les rendus, les miniatures, et METTRE A JOUR la base du serveur.
# On ne renvoie pas la base entiere : elle a pu changer entre-temps (des
# publications ont lieu pendant ce temps). Seules les deux colonnes concernees
# sont ecrites, video par video.
$lecture = @"
import sqlite3, json
db = sqlite3.connect(r'$app\data\vortex.db'); db.row_factory = sqlite3.Row
ids = [$([string]::Join(',', ($attente | ForEach-Object { $_.id })))]
q = 'SELECT id, name, render_path, thumb_path FROM videos WHERE id IN (%s)' % ','.join('?' * len(ids))
print(json.dumps([dict(r) for r in db.execute(q, ids)]))
"@
$faits = python -c $lecture | ConvertFrom-Json

$renvoyes = 0
foreach ($f in $faits) {
    if (-not $f.render_path) { continue }
    $rendu = $f.render_path
    if (-not (Test-Path -LiteralPath $rendu)) { continue }
    $nomRendu = Split-Path $rendu -Leaf
    Write-Host "  -> $nomRendu ($([math]::Round((Get-Item $rendu).Length/1MB)) Mo)"
    scp @ssh $rendu "${cible}:$distant/data/exports/"
    if ($LASTEXITCODE -ne 0) { Write-Warning "  envoi echoue : $nomRendu"; continue }

    $distRendu = "/app/data/exports/$nomRendu"
    $distThumb = ""
    if ($f.thumb_path -and (Test-Path -LiteralPath $f.thumb_path)) {
        $nomThumb = Split-Path $f.thumb_path -Leaf
        scp @ssh $f.thumb_path "${cible}:$distant/data/thumbs/"
        if ($LASTEXITCODE -eq 0) { $distThumb = "/app/data/thumbs/$nomThumb" }
    }
    # Un script cote serveur prend des arguments simples : empiler les
    # guillemets de PowerShell, de SSH, du shell distant et de Python cassait
    # systematiquement des qu'une parenthese apparaissait.
    $maj = "cd $distant; docker compose -f docker-compose.vps.yml run --rm --no-deps " +
           "vortex python3 /app/vps/maj_rendu.py $($f.id) '$distRendu' '$distThumb'"
    ssh @ssh $cible $maj | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "  base non mise a jour : $nomRendu"; continue }
    $renvoyes++

    # L'extrait vit desormais sur le serveur : inutile de le garder en double.
    Remove-Item -LiteralPath $rendu -Force -ErrorAction SilentlyContinue
}

Write-Host "$renvoyes habillage(s) renvoye(s) au serveur."
