@echo off
REM ============================================================
REM  Remplacement des miniatures TOUT-TEXTE — A LANCER SUR LE PC
REM
REM  Michel, 10/08/2026 : « supprime les miniatures sans visage et qui sont
REM  uniquement du texte ». 109 videos de la chaine en portaient une.
REM
REM  POURQUOI PAR PETITES PASSES REPETEES
REM  YouTube limite le RYTHME de depot des miniatures, independamment du
REM  quota : au-dela de quelques envois rapproches il repond 429 « The user
REM  has uploaded too many thumbnails recently », et chaque refus compte.
REM  Les 4 publications quotidiennes du serveur consomment deja cette
REM  reserve. Le script s'arrete donc net au premier refus et reprend a la
REM  passe suivante — le journal data\miniatures_refaites.json retient ce
REM  qui est fait.
REM
REM  POURQUOI SUR LE PC ET PAS SUR LE SERVEUR
REM  Meme raison que reperer_sermons.bat : YouTube bloque l'adresse du
REM  serveur, il faut telecharger la video pour y prendre l'image.
REM
REM  A planifier toutes les 3 heures dans le Planificateur de taches.
REM ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo [%date% %time%] === PASSE MINIATURES === >> data\logs\miniatures.log
python scripts\refaire_miniatures_youtube.py --limite 6 --pause 120 >> data\logs\miniatures.log 2>&1
echo [%date% %time%] === FIN PASSE === >> data\logs\miniatures.log
