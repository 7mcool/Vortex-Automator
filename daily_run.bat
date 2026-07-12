@echo off
REM ============================================================
REM  Vortex Automator — routine quotidienne (5 publications/jour)
REM  Lancee par le Planificateur de taches Windows.
REM  Chaque etape est tolerante : disque debranche, quota, etc.
REM ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo [%date% %time%] === DEBUT ROUTINE QUOTIDIENNE === >> data\logs\daily.log

REM 1. Detecter les nouvelles videos (ignore les telechargements en cours)
python -m vortex scan >> data\logs\daily.log 2>&1

REM 2. Remettre en file les echecs recuperables (disque rebranche...)
python -m vortex retry >> data\logs\daily.log 2>&1

REM 3. Transcrire et preparer un lot (garde ~2 jours d'avance)
python -m vortex transcribe -n 8 >> data\logs\daily.log 2>&1
python -m vortex prepare -n 10 >> data\logs\daily.log 2>&1

REM 4. Publier 5 videos (privees, programmees aux creneaux du jour suivant)
python -m vortex publish -n 5 --live >> data\logs\daily.log 2>&1

REM 5. Engagement : constater les publications, commenter, repondre
python -m vortex engage >> data\logs\daily.log 2>&1

REM 6. Etat final
python -m vortex status >> data\logs\daily.log 2>&1
echo [%date% %time%] === FIN ROUTINE === >> data\logs\daily.log
