@echo off
REM ===========================================================================
REM  Rainfall Verification Dashboard - Windows launcher (double-click this).
REM
REM  Route A (preferred): if Python 3.10+ is already on this PC, build a small
REM    local .venv with pip. No conda, nothing installed outside this folder.
REM    Reads NetCDF *and* GRIB2 - the eccodes wheel bundles the C library.
REM  Route B (fallback): if no suitable Python exists, offer Miniforge + conda.
REM    Needed only for cartopy (Natural Earth coastlines).
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM Never stop for an interactive conda prompt. Anaconda/Miniconda installs carry
REM a Terms-of-Service plugin that otherwise aborts with CondaToSNonInteractiveError
REM half way through setup. Harmless where the plugin is absent (Miniforge).
set CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
set CONDA_ALWAYS_YES=yes

set ENV=rainfall-verif
set MC=%USERPROFILE%\miniforge3
set VENV=%~dp0.venv
set VPY=%VENV%\Scripts\python.exe
set CORE=import streamlit,xarray,scipy,plotly,pandas,netCDF4,shapely,numpy

REM ===========================================================================
REM  ROUTE A - existing Python + pip
REM ===========================================================================

REM Already built? Launch straight away - the common case on every later run.
if exist "%VPY%" (
  "%VPY%" -c "%CORE%" >nul 2>&1 && goto :launch_venv
)

REM Find any Python 3.10 or newer. `py` is the Windows launcher; fall back to
REM whatever `python` / `python3` resolves to on PATH.
set "PYEXE="
py -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE python3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PYEXE=python3"
if not defined PYEXE goto :route_conda

echo.
echo  [setup] Found Python on this PC - using it. No conda needed.
for /f "delims=" %%V in ('%PYEXE% -c "import sys;print(sys.version.split()[0])"') do echo          Python %%V
echo.
echo          Creating a private environment in:
echo            %VENV%
echo          Downloads about 700 MB of scientific libraries from PyPI. One
echo          time only; later launches start immediately. Everything stays
echo          inside this folder - delete it and nothing is left behind.
echo.

if not exist "%VPY%" %PYEXE% -m venv "%VENV%"
if not exist "%VPY%" (
  echo  [setup] Could not create the environment. Falling back to conda.
  goto :route_conda
)

"%VPY%" -m pip install --upgrade pip --quiet
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  [setup] pip install failed - see the messages above. Trying conda instead.
  echo.
  goto :route_conda
)

"%VPY%" -c "%CORE%" >nul 2>&1
if errorlevel 1 (
  echo  [setup] The environment is incomplete. Falling back to conda.
  goto :route_conda
)

"%VPY%" -c "import cfgrib" >nul 2>&1 && (echo  [setup] GRIB2 support: enabled) || (echo  [setup] GRIB2 support: unavailable - NetCDF still works)
goto :launch_venv

REM ===========================================================================
REM  ROUTE B - conda (only when no usable Python was found)
REM ===========================================================================
:route_conda

set CONDA=
where mamba >nul 2>&1 && set "CONDA=mamba"
if not defined CONDA (where conda >nul 2>&1 && set "CONDA=conda")
if not defined CONDA if exist "%MC%\Scripts\conda.exe" set "CONDA=%MC%\Scripts\conda.exe"
if not defined CONDA if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if defined CONDA goto :have_conda

echo.
echo  ============================================================
echo   FIRST-TIME SETUP - here is exactly what will be installed
echo  ============================================================
echo.
echo   No Python was found on this PC, so setup needs to install
echo   one along with the libraries the app uses. Nothing else is
echo   installed or changed.
echo.
echo   1. Miniforge  ^(open-source Python distribution, BSD licence^)
echo        download    ~141 MB
echo        installs to %MC%
echo.
echo   2. The app's libraries, from conda-forge
echo        numpy, scipy, pandas, xarray, netCDF4, plotly, streamlit,
echo        cartopy, shapely, cfgrib, eccodes
echo        about 1.2 GB on disk once built
echo.
echo   * Everything goes in your own user folder. No admin rights,
echo     no system files touched, nothing added to startup.
echo   * Nothing is sent anywhere. The app runs on this PC only, at
echo     http://localhost:8501, not reachable from the network.
echo   * To remove it all later, delete these two folders:
echo        %MC%
echo        the folder this app is in
echo.
echo   Tip: installing Python from python.org first ^(about 30 MB^)
echo   lets this app use the much smaller pip route instead.
echo.
set "OK="
set /p OK="  Type Y then Enter to continue, or just Enter to cancel: "
if /i "%OK%"=="Y" goto :do_install
if /i "%OK%"=="YES" goto :do_install
echo.
echo  Cancelled. Nothing was downloaded or installed.
pause
exit /b 0

:do_install
REM Miniforge, not Miniconda: it defaults to conda-forge, so repo.anaconda.com is
REM never consulted. Anaconda's channels refuse non-interactive use until their
REM Terms of Service are accepted, and their licence requires payment for larger
REM organisations. Miniforge also ships mamba, which solves faster.
echo.
echo [setup] installing Miniforge ^(one time^)...
curl -L -o "%TEMP%\miniforge.exe" https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe
start /wait "" "%TEMP%\miniforge.exe" /InstallationType=JustMe /RegisterPython=0 /S /D=%MC%
del "%TEMP%\miniforge.exe"
set "CONDA=%MC%\Scripts\conda.exe"

:have_conda

REM A pre-existing Anaconda/Miniconda gates its `defaults` channel behind a
REM Terms-of-Service acceptance. environment.yml pins `nodefaults` so those
REM channels are never used; accept quietly as a second line of defence.
REM No-op on Miniforge and on conda builds predating the `tos` subcommand.
for %%C in (main r msys2) do (
  "%CONDA%" tos accept --override-channels --channel https://repo.anaconda.com/pkgs/%%C >nul 2>&1
)

REM The classic solver can run OUT OF MEMORY loading conda-forge repodata on
REM low-RAM machines. mamba is already libmamba; for plain conda, add the plugin.
REM Pinned to conda-forge: with no -c this resolves against repo.anaconda.com,
REM the very channels behind the ToS gate.
set SOLVER=
echo %CONDA% | findstr /i "mamba" >nul || (
  "%CONDA%" install -n base -y --override-channels -c conda-forge conda-libmamba-solver >nul 2>&1
  "%CONDA%" config --set solver libmamba >nul 2>&1
  set "SOLVER=--solver=libmamba"
)

REM Build the env only if needed. The truth test is whether the env's python can
REM import everything - never parse `env list` text, whose indentation varies.
set CHECK=%CORE%,cartopy,cfgrib
set NEED=1
"%CONDA%" run -n %ENV% python -c "%CHECK%" >nul 2>&1 && set NEED=0
if "%NEED%"=="1" ( "%CONDA%" env list | findstr /i "%ENV%" >nul 2>&1 && set NEED=2 )
if "%NEED%"=="1" (
  echo.
  echo  [setup] Building the app's environment "%ENV%" - about 1.2 GB on disk.
  echo          One time only; later launches start immediately.
  echo.
  "%CONDA%" env create -f environment.yml %SOLVER% || ( echo [setup] retrying... & "%CONDA%" env remove -n %ENV% -y >nul 2>&1 & "%CONDA%" env create -f environment.yml %SOLVER% )
) else if "%NEED%"=="2" (
  echo [setup] updating env ^(a dependency is missing/changed^)...
  "%CONDA%" env update -n %ENV% -f environment.yml %SOLVER%
  "%CONDA%" run -n %ENV% python -c "%CHECK%" >nul 2>&1 || ( "%CONDA%" env remove -n %ENV% -y & "%CONDA%" env create -f environment.yml %SOLVER% )
) else (
  echo [run] environment ready.
)

"%CONDA%" run -n %ENV% python -c "%CHECK%" >nul 2>&1 || (
  echo.
  echo  [ERROR] The environment "%ENV%" could not be created. Check the messages above.
  echo.
  echo    * "CondaToSNonInteractiveError / Terms of Service have not been accepted"
  echo        An existing Anaconda/Miniconda install is blocking. Run these once,
  echo        then re-run this launcher:
  echo          conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
  echo          conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
  echo          conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2
  echo.
  echo    * "Killed" or the solve stops with no message
  echo        Low memory. Close other applications and re-run.
  echo.
  echo    * "CondaHTTPError" or connection failures
  echo        Network or proxy problem reaching conda-forge.
  echo.
  pause & exit /b 1
)

call :shortcut
call :freeport
echo.
echo  [run] starting - your browser will open at http://localhost:8501
echo        keep this window open while you use the app; close it to stop.
echo.
start "" http://localhost:8501
"%CONDA%" run -n %ENV% streamlit run app.py --server.port 8501
pause
exit /b 0

REM ===========================================================================
:launch_venv
call :shortcut
call :freeport
echo.
echo  [run] starting - your browser will open at http://localhost:8501
echo        keep this window open while you use the app; close it to stop.
echo.
start "" http://localhost:8501
"%VPY%" -m streamlit run app.py --server.port 8501
pause
exit /b 0

REM ===========================================================================
:shortcut
REM Create a Desktop / Start-Menu icon once, so later launches are one click.
if not exist "%~dp0.shortcut_done" (
  call "%~dp0Create Shortcut.bat" >nul 2>&1
  echo done> "%~dp0.shortcut_done"
)
goto :eof

:freeport
REM Free port 8501 so a stale instance cannot shadow this one.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
goto :eof
