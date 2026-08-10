@echo off
REM ============================================================
REM  Miniatures a visage — LE ROLE DU PC
REM
REM  Michel, 10/08/2026 : « supprime les miniatures sans visage et qui sont
REM  uniquement du texte » — 109 videos de la chaine en portaient une — puis
REM  « que mon ordi soit allume ou pas tout doit passer, avec aussi mon PC ».
REM
REM  PARTAGE DU TRAVAIL
REM    Ce PC    : FABRIQUE les miniatures (il faut telecharger la video pour y
REM               prendre l'image), les DEPOSE sur le serveur, et en pose.
REM    Serveur  : POSE ce que le PC a depose, toutes les 3 h, PC eteint.
REM
REM  Le serveur ne peut pas fabriquer : YouTube lui refuse tout telechargement
REM  (« Sign in to confirm you're not a bot », verifie le 10/08 avec et sans
REM  cookies). C'est la meme raison que reperer_sermons.bat.
REM
REM  Les deux machines ne posent jamais deux fois la meme : avant d'envoyer,
REM  chacune regarde la miniature reellement en ligne.
REM
REM  POURQUOI SI PEU A LA FOIS
REM  YouTube limite le RYTHME de depot des miniatures, independamment du
REM  quota : au-dela de quelques envois rapproches il repond 429 « too many
REM  thumbnails recently », et chaque refus compte. On s'arrete donc au
REM  premier refus et on reprend a la passe suivante.
REM
REM  Planifie toutes les 3 heures dans le Planificateur de taches.
REM ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo [%date% %time%] === PASSE MINIATURES (PC) === >> data\logs\miniatures.log
python scripts\refaire_miniatures_youtube.py --preparer 12 --envoyer --poser 6 --pause 120 >> data\logs\miniatures.log 2>&1
echo [%date% %time%] === FIN PASSE === >> data\logs\miniatures.log
