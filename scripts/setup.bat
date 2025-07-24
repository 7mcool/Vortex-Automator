@echo off
setlocal enabledelayedexpansion

:: ======================================================================
:: Vortex Automator - Script d'installation Windows
:: ======================================================================
:: Ce script configure l'environnement pour le robot YouTube Premium
:: ======================================================================

echo.
echo ======================================================================
echo 🤖 VORTEX AUTOMATOR - INSTALLATION
echo ======================================================================
echo.

:: ----------------------------------------------------------------------
:: Vérification de Python 3.10+
:: ----------------------------------------------------------------------
echo 🔍 Vérification de la version de Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERREUR: Python n'est pas installé ou n'est pas dans le PATH
    echo.
    echo 👉 Téléchargez Python 3.10+ depuis: 
    echo    https://www.python.org/downloads/
    echo 👉 Cochez "Add Python to PATH" pendant l'installation
    echo.
    pause
    exit /b 1
)

python -c "import sys; exit(0) if sys.version_info >= (3, 10) else exit(1)"
if %errorlevel% neq 0 (
    echo ❌ ERREUR: Version de Python trop ancienne (3.10+ requis)
    python --version
    echo.
    echo 👉 Mettez à jour Python depuis:
    echo    https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo ✅ Version Python compatible: 
python --version

:: ----------------------------------------------------------------------
:: Configuration des dossiers
:: ----------------------------------------------------------------------
echo.
echo 📁 Configuration des dossiers...
mkdir source_videos 2>nul
mkdir logs 2>nul
mkdir done_channel1 2>nul
mkdir done_channel2 2>nul
mkdir failed_uploads 2>nul
echo ✅ Structure de dossiers créée

:: ----------------------------------------------------------------------
:: Création de l'environnement virtuel
:: ----------------------------------------------------------------------
echo.
echo 🐍 Création de l'environnement virtuel...
python -m venv venv
if %errorlevel% neq 0 (
    echo ❌ ERREUR: Échec de la création de l'environnement virtuel
    echo 👉 Essayez d'installer virtualenv: python -m pip install virtualenv
    echo.
    pause
    exit /b 1
)
echo ✅ Environnement virtuel créé

:: ----------------------------------------------------------------------
:: Installation des dépendances
:: ----------------------------------------------------------------------
echo.
echo 📦 Installation des dépendances Python...
call venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ ERREUR: Échec de l'installation des dépendances
    echo 👉 Vérifiez votre connexion internet
    echo 👉 Essayez d'exécuter manuellement: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo ✅ Dépendances installées avec succès

:: ----------------------------------------------------------------------
:: Vérification de FFmpeg
:: ----------------------------------------------------------------------
echo.
echo 🎬 Vérification de FFmpeg...
ffprobe -version >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️ AVERTISSEMENT: FFmpeg n'est pas installé
    echo.
    echo 👉 Téléchargez FFmpeg depuis: 
    echo    https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z
    echo 👉 Extraire et ajouter le dossier 'bin' au PATH système
    echo.
    echo ⚠️ Le script continuera mais les fonctionnalités vidéo seront limitées
    echo.
    timeout /t 10 >nul
)

:: ----------------------------------------------------------------------
:: Création du script run.bat
:: ----------------------------------------------------------------------
echo.
echo 📝 Création du script d'exécution...
(
echo @echo off
echo setlocal
echo.
echo echo ======================================================================
echo echo 🤖 LANCEMENT DE VORTEX AUTOMATOR
echo echo ======================================================================
echo echo.
echo 
echo :: Vérification de l'environnement virtuel
echo if not exist "venv\Scripts\activate.bat" (
echo    echo ❌ ERREUR: Environnement virtuel introuvable
echo    echo.
echo    echo 👉 Exécutez d'abord le script d'installation: scripts\setup.bat
echo    echo.
echo    pause
echo    exit /b 1
echo )
echo 
echo :: Activation de l'environnement
echo call venv\Scripts\activate
echo 
echo :: Vérification du fichier principal
echo if not exist "src\main.py" (
echo    echo ❌ ERREUR: Fichier principal introuvable (src\main.py)
echo    echo.
echo    echo 👉 Vérifiez l'intégrité du projet
echo    echo.
echo    pause
echo    exit /b 1
echo )
echo 
echo :: Exécution du programme
echo python src\main.py
echo 
echo :: Fin du script
echo echo.
echo echo ======================================================================
echo echo FIN D'EXÉCUTION - Consultez les journaux dans logs\
echo echo ======================================================================
echo echo.
echo pause
) > run.bat

echo ✅ Script d'exécution créé: run.bat

:: ----------------------------------------------------------------------
:: Configuration initiale
:: ----------------------------------------------------------------------
echo.
echo ⚙️ Configuration initiale...
if not exist "client_secret.json" (
    echo ❗ IMPORTANT: Créez un fichier client_secret.json
    echo    à la racine du projet avec vos credentials Google
    echo.
    echo 👉 Consultez docs/SETUP.md pour les instructions
    echo.
)

echo.
echo ======================================================================
echo ✅✅✅ INSTALLATION RÉUSSIE ✅✅✅
echo ======================================================================
echo.
echo Prochaines étapes:
echo 1. Ajoutez vos vidéos dans le dossier 'source_videos'
echo 2. Configurez vos credentials Google (client_secret.json)
echo 3. Exécutez le robot avec:
echo.
echo    run.bat
echo.
echo Consultez la documentation dans docs\ pour plus d'informations
echo.
pause