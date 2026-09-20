@echo off
REM Double-click launcher (Windows). First run: auto-installs Miniconda if absent,
REM builds the conda env, then starts the app and opens the browser. No manual setup.
setlocal
cd /d "%~dp0"
set ENV=rainfall-verif
set MC=%USERPROFILE%\miniconda3

REM 1. find conda/mamba, else auto-install Miniconda
set CONDA=
where mamba >nul 2>&1 && set "CONDA=mamba"
if not defined CONDA (where conda >nul 2>&1 && set "CONDA=conda")
if not defined CONDA if exist "%MC%\Scripts\conda.exe" set "CONDA=%MC%\Scripts\conda.exe"

if not defined CONDA (
  echo [setup] Miniconda not found - installing it ^(one time^)...
  curl -L -o "%TEMP%\miniconda.exe" https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
  start /wait "" "%TEMP%\miniconda.exe" /InstallationType=JustMe /RegisterPython=0 /S /D=%MC%
  del "%TEMP%\miniconda.exe"
  set "CONDA=%MC%\Scripts\conda.exe"
)

REM 1b. use the libmamba solver (C++): the classic solver runs OUT OF MEMORY loading
REM     conda-forge repodata on low-RAM machines. mamba is already libmamba; for plain
REM     conda, install the plugin (one time) and pass --solver=libmamba.
set SOLVER=
echo %CONDA% | findstr /i "mamba" >nul || (
  "%CONDA%" install -n base -y conda-libmamba-solver >nul 2>&1
  "%CONDA%" config --set solver libmamba >nul 2>&1
  set "SOLVER=--solver=libmamba"
)

REM 2. set up env ONLY if needed. Truth test = can the env's python import everything?
REM     (Never rely on `env list` text — its indentation varies by conda/mamba version.)
set CHECK=import streamlit,xarray,scipy,plotly,pandas,netCDF4,shapely,cartopy,cfgrib
set NEED=1
"%CONDA%" run -n %ENV% python -c "%CHECK%" >nul 2>&1 && set NEED=0
if "%NEED%"=="1" ( "%CONDA%" env list | findstr /i "%ENV%" >nul 2>&1 && set NEED=2 )
if "%NEED%"=="1" (
  echo [setup] creating env "%ENV%" ^(one time, downloads dependencies^)...
  "%CONDA%" env create -f environment.yml %SOLVER% || ( echo [setup] retrying... & "%CONDA%" env remove -n %ENV% -y >nul 2>&1 & "%CONDA%" env create -f environment.yml %SOLVER% )
) else if "%NEED%"=="2" (
  echo [setup] updating env ^(a dependency is missing/changed^)...
  "%CONDA%" env update -n %ENV% -f environment.yml %SOLVER%
  "%CONDA%" run -n %ENV% python -c "%CHECK%" >nul 2>&1 || ( "%CONDA%" env remove -n %ENV% -y & "%CONDA%" env create -f environment.yml %SOLVER% )
) else (
  echo [run] environment ready.
)
REM guard on the IMPORT check (not env-list text): stop clearly only if the env truly can't import
"%CONDA%" run -n %ENV% python -c "%CHECK%" >nul 2>&1 || ( echo [ERROR] Env "%ENV%" isn't working ^(see messages above - often low memory during solve^). Close other apps and re-run. & pause & exit /b 1 )

REM 2b. create a Desktop / Start-Menu icon once, so future launches are a single double-click
if not exist "%~dp0.shortcut_done" (
  call "%~dp0Create Shortcut.bat" >nul 2>&1
  echo done> "%~dp0.shortcut_done"
)

REM 3. launch - free port 8501 first so a stale old instance can't shadow this one
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
start "" http://localhost:8501
"%CONDA%" run -n %ENV% streamlit run app.py --server.port 8501
pause
