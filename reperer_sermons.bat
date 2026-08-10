@echo off
REM ============================================================
REM  Reperage de la predication — A LANCER SUR LE PC
REM
REM  POURQUOI SUR LE PC ET PAS SUR LE SERVEUR (constate le 10/08/2026)
REM  YouTube bloque l'adresse du serveur (« Sign in to confirm you're not
REM  a bot »). Les memes cookies fonctionnent depuis cette machine. Le
REM  serveur ne peut donc ni lire les sous-titres, ni telecharger l'audio.
REM
REM  Ce script fait le travail ici et depose la fenetre de predication dans
REM  la base du serveur. Sans lui, le serveur devine la position du sermon
REM  (regle des 69 %) et n'ose pas lancer le decoupage tout seul.
REM
REM  A planifier toutes les 2 heures dans le Planificateur de taches.
REM ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo [%date% %time%] === REPERAGE SERMONS === >> data\logs\reperage.log
python scripts\reperer_pour_vps.py >> data\logs\reperage.log 2>&1
echo [%date% %time%] === FIN REPERAGE === >> data\logs\reperage.log
