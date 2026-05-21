@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY_VERSION=3.11.9"
set "PY_INSTALLER=python-%PY_VERSION%-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/%PY_INSTALLER%"
set "LOCAL_PY_DIR=%~dp0.python"
set "LOCAL_PY=%LOCAL_PY_DIR%\python.exe"

REM ============================================================
REM 1) Trouver un Python 3.11+ utilisable
REM ============================================================
set "PYTHON_BOOTSTRAP="

REM a) Python local deja installe par ce script ?
if exist "%LOCAL_PY%" (
    set "PYTHON_BOOTSTRAP=%LOCAL_PY%"
    goto :have_python
)

REM b) Python du systeme ?
where python >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%v in ('python -c "import sys; print(1 if sys.version_info >= (3,11) else 0)" 2^>nul') do set "PY_OK=%%v"
    if "!PY_OK!"=="1" (
        set "PYTHON_BOOTSTRAP=python"
        goto :have_python
    )
)

REM c) py launcher ?
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%v in ('py -3 -c "import sys; print(1 if sys.version_info >= (3,11) else 0)" 2^>nul') do set "PY_OK=%%v"
    if "!PY_OK!"=="1" (
        set "PYTHON_BOOTSTRAP=py -3"
        goto :have_python
    )
)

REM d) Installation automatique de Python pour l'utilisateur courant
echo [run] Aucun Python 3.11+ detecte. Installation de Python %PY_VERSION% en local ...
if not exist "%LOCAL_PY_DIR%" mkdir "%LOCAL_PY_DIR%"

set "INSTALLER_PATH=%TEMP%\%PY_INSTALLER%"
echo [run] Telechargement de %PY_URL% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%INSTALLER_PATH%'"
if errorlevel 1 (
    echo [run] ERREUR: telechargement de Python echoue.
    exit /b 1
)

echo [run] Installation silencieuse dans %LOCAL_PY_DIR% ...
"%INSTALLER_PATH%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 ^
    TargetDir="%LOCAL_PY_DIR%" AssociateFiles=0 Shortcuts=0 Include_doc=0
if errorlevel 1 (
    echo [run] ERREUR: installation de Python echouee.
    exit /b 1
)
del /q "%INSTALLER_PATH%" >nul 2>&1

if not exist "%LOCAL_PY%" (
    echo [run] ERREUR: python.exe introuvable apres installation.
    exit /b 1
)
set "PYTHON_BOOTSTRAP=%LOCAL_PY%"

:have_python

REM ============================================================
REM 2) Creer le venv si absent
REM ============================================================
if not exist ".venv\Scripts\python.exe" (
    echo [run] Creation de l'environnement virtuel .venv ...
    %PYTHON_BOOTSTRAP% -m venv .venv
    if errorlevel 1 (
        echo [run] ERREUR: creation du venv echouee.
        exit /b 1
    )
)

set "PYTHON=.venv\Scripts\python.exe"

REM ============================================================
REM 3) Installer / mettre a jour les dependances
REM ============================================================
set "STAMP=.venv\.requirements.stamp"
set "NEED_INSTALL=0"
if not exist "%STAMP%" (
    set "NEED_INSTALL=1"
) else (
    for /f %%i in ('powershell -NoProfile -Command "if ((Get-Item requirements.txt).LastWriteTime -gt (Get-Item '%STAMP%').LastWriteTime) { 'yes' }"') do set "NEED_INSTALL=1"
)

if "!NEED_INSTALL!"=="1" (
    echo [run] Installation des dependances depuis requirements.txt ...
    "%PYTHON%" -m pip install --upgrade pip >nul
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [run] ERREUR: installation des dependances echouee.
        exit /b 1
    )
    echo. > "%STAMP%"
)

REM ============================================================
REM 4) Lancement de l'app
REM ============================================================
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
"%PYTHON%" -m pzsavesync %*

endlocal
