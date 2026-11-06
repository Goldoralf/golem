@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem GoleM - installer sous Windows depuis CE dossier (un clone ou une copie du depot) : double-clic.
rem Il lance provision\bootstrap.ps1 avec GOLEM_SRC = ce dossier (rien n'est telecharge pour GoleM),
rem qui trouve ou pose Python 3.12 puis ouvre l'installateur dans sa propre fenetre.
set "GOLEM_SRC=%~dp0"
if "%GOLEM_SRC:~-1%"=="\" set "GOLEM_SRC=%GOLEM_SRC:~0,-1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%GOLEM_SRC%\provision\bootstrap.ps1"
if errorlevel 1 pause
