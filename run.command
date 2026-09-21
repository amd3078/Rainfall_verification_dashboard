#!/usr/bin/env bash
# Double-click launcher (macOS). First run: auto-installs Miniconda if absent,
# builds the conda env, then starts the app and opens the browser. No manual setup.
set -e
cd "$(dirname "$0")"
# Never stop for an interactive prompt. Anaconda/Miniconda installs carry a
# Terms-of-Service plugin that otherwise aborts with CondaToSNonInteractiveError
# and the setup dies half way. Harmless where the plugin is absent (Miniforge).
export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
export CONDA_ALWAYS_YES=yes

ENV=rainfall-verif
MC="$HOME/miniconda3"

# ===========================================================================
#  ROUTE A - use an existing Python with pip (preferred: smaller, no conda)
#  Reads NetCDF *and* GRIB2; the eccodes wheel bundles the C library.
#  Falls through to the conda route below if no suitable Python is found.
# ===========================================================================
VENV="$PWD/.venv"                 # the script cd's to its own directory above
VPY="$VENV/bin/python"
CORE='import streamlit,xarray,scipy,plotly,pandas,netCDF4,shapely,numpy'

# Self-contained: this runs before the conda helpers further down are defined,
# so it must not call them.
open_url() {
  url="http://localhost:8501"
  if [ -n "${BROWSER:-}" ] && command -v "$BROWSER" >/dev/null 2>&1; then "$BROWSER" "$url" >/dev/null 2>&1 && return 0; fi
  for o in xdg-open open gnome-open kde-open wslview; do
    command -v "$o" >/dev/null 2>&1 && { "$o" "$url" >/dev/null 2>&1 && return 0; }
  done
  echo "  [run] could not open a browser automatically - go to $url"
}

launch_venv() {
  lsof -ti:8501 2>/dev/null | xargs kill -9 2>/dev/null || true
  [ -f .env ] && { set -a; . ./.env; set +a; }
  echo
  echo "  [run] starting - your browser will open at http://localhost:8501"
  echo "        keep this window open while you use the app; close it to stop."
  echo
  ( sleep 4; open_url ) &
  exec "$VPY" -m streamlit run app.py --server.port 8501 --server.headless true
}

# Already built? Start at once - the common case on every later run.
if [ -x "$VPY" ] && "$VPY" -c "$CORE" >/dev/null 2>&1; then
  launch_venv
fi

# Find any Python 3.10 or newer.
PYEXE=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  command -v "$c" >/dev/null 2>&1 || continue
  "$c" -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' >/dev/null 2>&1 && { PYEXE="$c"; break; }
done

if [ -n "$PYEXE" ]; then
  echo
  echo "  [setup] Found Python on this machine - using it. No conda needed."
  echo "          $("$PYEXE" -c 'import sys;print("Python "+sys.version.split()[0])')"
  echo
  echo "          Creating a private environment in:"
  echo "            $VENV"
  echo "          Downloads about 700 MB of scientific libraries from PyPI. One"
  echo "          time only; later launches start immediately. Everything stays"
  echo "          inside this folder - delete it and nothing is left behind."
  echo
  if [ ! -x "$VPY" ]; then "$PYEXE" -m venv "$VENV" || true; fi
  if [ -x "$VPY" ]; then
    "$VPY" -m pip install --upgrade pip --quiet || true
    if "$VPY" -m pip install -r requirements.txt && "$VPY" -c "$CORE" >/dev/null 2>&1; then
      if "$VPY" -c 'import cfgrib' >/dev/null 2>&1; then
        echo "  [setup] GRIB2 support: enabled"
      else
        echo "  [setup] GRIB2 support: unavailable - NetCDF still works"
      fi
      launch_venv
    fi
    echo "  [setup] pip setup did not complete - falling back to conda."
  else
    echo "  [setup] could not create the environment - falling back to conda."
  fi
fi

# ===========================================================================
#  ROUTE B - conda (only when no usable Python was found)
# ===========================================================================
# 1. find conda/mamba, else auto-install Miniconda (no manual step)
CONDA=""
for c in mamba conda "$MC/bin/conda"; do command -v "$c" >/dev/null 2>&1 && { CONDA="$c"; break; }; done
if [ -z "$CONDA" ] && [ -x "$MC/bin/conda" ]; then CONDA="$MC/bin/conda"; fi
if [ -z "$CONDA" ]; then
  cat <<'BANNER'

 ============================================================
  FIRST-TIME SETUP - here is exactly what will be installed
 ============================================================

  This app runs on Python. No suitable Python was found, so setup
  needs to install one, plus the scientific libraries the app uses.
  Nothing else is installed or changed.

  1. Miniforge  (open-source Python distribution, BSD licence)
       download    ~80-120 MB
       installs to $HOME/miniforge3

  2. The app's libraries, from conda-forge
       numpy, scipy, pandas, xarray, netCDF4, plotly, streamlit,
       cartopy, shapely, cfgrib, eccodes
       about 1.2 GB on disk once built

  * Everything goes in your home folder. No sudo, no system files
    touched, nothing added to login items.
  * Nothing is sent anywhere. The app runs on this machine only, at
    http://localhost:8501, and is not reachable from the network.
  * To remove it all later, delete these two folders:
       $HOME/miniforge3
       the folder this app is in

  Already have Anaconda or Miniconda? Cancel, run it from your conda
  prompt instead, and nothing extra is downloaded.

BANNER
  printf "  Type Y then Enter to continue, or just Enter to cancel: "
  read -r OK </dev/tty || OK=""
  case "$OK" in
    [Yy]|[Yy][Ee][Ss]) : ;;
    *) echo; echo "  Cancelled. Nothing was downloaded or installed."; exit 0 ;;
  esac
  echo

  # Miniforge, not Miniconda: conda-forge by default, so repo.anaconda.com is
  # never consulted. Anaconda's channels now refuse non-interactive use until
  # their Terms of Service are accepted, and their licence requires payment for
  # larger organisations. Miniforge also ships mamba.
  echo "[setup] installing Miniforge (one time)…"
  # Pick the installer for THIS machine. Previously hard-coded to MacOSX, which
  # downloaded a macOS installer on Linux and failed.
  case "$(uname -s)" in
    Darwin) OSTAG="MacOSX" ;;
    Linux)  OSTAG="Linux"  ;;
    *) echo "[setup] unsupported OS $(uname -s) - install Miniconda manually: https://docs.conda.io/projects/miniconda/"; exit 1 ;;
  esac
  case "$(uname -m)" in
    arm64|aarch64) A=$( [ "$OSTAG" = "MacOSX" ] && echo arm64 || echo aarch64 ) ;;
    *)             A=x86_64 ;;
  esac
  URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$OSTAG-$A.sh"
  curl -L -o /tmp/miniconda.sh "$URL"
  bash /tmp/miniconda.sh -b -p "$MC"
  rm -f /tmp/miniconda.sh
  CONDA="$MC/bin/conda"
fi

# 1b. use the libmamba solver (C++): the classic solver can balloon and run OUT OF MEMORY
#     loading conda-forge repodata. mamba is already libmamba; for plain conda install the
#     plugin (one time) and pass --solver=libmamba.
SOLVER=""
case "$CONDA" in
  *mamba*) ;;
  *) "$CONDA" install -n base -y --override-channels -c conda-forge conda-libmamba-solver >/dev/null 2>&1 || true
     "$CONDA" config --set solver libmamba >/dev/null 2>&1 || true
     SOLVER="--solver=libmamba" ;;
esac

# 2. set up env ONLY if needed. The truth test is whether the env's python can import
#    everything (robust — never parse `env list` text, whose indentation varies by tool).
# If this machine already has Miniconda/Anaconda, accept its channel Terms of
# Service quietly so the solve cannot stop and ask. No-op on Miniforge, which has
# no such plugin, and on conda builds predating the `tos` subcommand.
for _c in main r msys2; do
  "$CONDA" tos accept --override-channels --channel "https://repo.anaconda.com/pkgs/$_c" >/dev/null 2>&1 || true
done

CHECK='import streamlit,xarray,scipy,plotly,pandas,netCDF4,shapely,cartopy,cfgrib'
have_env() { "$CONDA" run -n "$ENV" python -c "$CHECK" >/dev/null 2>&1; }
# loose match (env line may be indented and/or shown as a path) to decide update-vs-create
env_registered() { "$CONDA" env list | grep -qiE "(^|[ /])$ENV([ ]|/|\$)"; }
if have_env; then
  echo "[run] environment ready."
else
  if env_registered; then
    echo "[setup] updating env (a dependency is missing/changed)…"
    "$CONDA" env update -n "$ENV" -f environment.yml $SOLVER || true
    have_env || { "$CONDA" env remove -n "$ENV" -y; "$CONDA" env create -f environment.yml $SOLVER; }
  else
    echo "[setup] creating env '$ENV' (one time, downloads dependencies)…"
    echo
    echo "  [setup] Building the app's environment \"$ENV\". Downloads libraries"
    echo "          from conda-forge, about 1.2 GB on disk, inside your existing"
    echo "          conda install. One time only; later launches start at once."
    echo
    "$CONDA" env create -f environment.yml $SOLVER
  fi
  # guard on the IMPORT check, not on env-list text
  have_env || { echo "[ERROR] Env '$ENV' isn't working (see messages above). Re-run after closing other apps."; exit 1; }
fi

# 2b. put a clickable rain icon on the Desktop once (parity with the Windows shortcut).
#     It's a Finder alias to the .app, which itself opens this run.command.
APP="$PWD/Rainfall Verification.app"
if [ -d "$APP" ] && [ ! -e "$HOME/Desktop/Rainfall Verification" ] && [ ! -e "$HOME/Desktop/Rainfall Verification.app" ]; then
  osascript -e "tell application \"Finder\" to make alias file to (POSIX file \"$APP\") at (POSIX file \"$HOME/Desktop\")" >/dev/null 2>&1 \
    || ln -s "$APP" "$HOME/Desktop/Rainfall Verification.app" 2>/dev/null || true
  # Finder names the alias "... alias" — rename to a clean name so it looks like a normal app icon
  a=$(find "$HOME/Desktop" -maxdepth 1 -iname "Rainfall Verification*" 2>/dev/null | head -1)
  [ -n "$a" ] && [ "$a" != "$HOME/Desktop/Rainfall Verification" ] && mv "$a" "$HOME/Desktop/Rainfall Verification" 2>/dev/null || true
  echo "[setup] Added a 'Rainfall Verification' icon to your Desktop — double-click it any time."
fi

# 3. launch — free port 8501 first so a stale old instance can't shadow this one
lsof -ti:8501 2>/dev/null | xargs kill -9 2>/dev/null || true
[ -f .env ] && { set -a; . ./.env; set +a; }
echo "[run] opening http://localhost:8501"
# Open the user's DEFAULT browser - never a hard-coded one. `open` is macOS,
# `xdg-open` is the freedesktop standard on Linux, $BROWSER is the user override,
# and Python's webbrowser module is the last resort. If all fail, the URL is
# already printed above, so the user can click or paste it.
open_browser() {
  url="http://localhost:8501"
  if [ -n "${BROWSER:-}" ] && command -v "$BROWSER" >/dev/null 2>&1; then "$BROWSER" "$url" >/dev/null 2>&1 && return 0; fi
  for opener in xdg-open open gio\ open gnome-open kde-open wslview; do
    # shellcheck disable=SC2086
    command -v ${opener%% *} >/dev/null 2>&1 && { $opener "$url" >/dev/null 2>&1 && return 0; }
  done
  "$CONDA" run -n "$ENV" python -m webbrowser "$url" >/dev/null 2>&1 && return 0
  echo "[run] could not open a browser automatically - go to $url"
}
( sleep 4; open_browser ) &
"$CONDA" run -n "$ENV" streamlit run app.py --server.port 8501 --server.headless true
