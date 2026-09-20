Rainfall Verification Dashboard
version: v5.1
build: 2026-09-20
includes: ensemble+deterministic, each single OR multiple (same engine, full parity);
  ensemble Mean / Probabilistic chosen right after model pick; split/together files;
  sub-folders/flat + top-level "files in this folder"; auto-units; nc+grib;
  categorical+continuous+probabilistic scores; extremal-dependence EDI/SEDI/EDS/SEDS + YuleQ;
  score maps (incl CRPS/BS/BSS);
  reliability/ROC/REV/rank/PIT/spread-skill/Taylor/QQ (per-model, with 95% CI bands);
  FSS+CRA (single & multiple, mean); bootstrap CIs (user N); CSV+figure export;
  India boundary; audit
changes since v2.2:
  - FIX: square-grid (nlon==nlat) forecasts were transposed in regrid -> maps AND scores
         shifted; now readers' (lat,lon) orientation is honoured first.
  - Ensemble Single now uses the same engine as Multiple: gains bootstrap, FSS/CRA,
         probabilistic + diagnostics (full parity).
  - Ensemble verification (Mean/Probabilistic) placed right after the model choice for
         both Single and Multiple; removed duplicate Single/Multiple radio and the
         unused "Members as models" option.
  - Single ensemble: model dropdown always shown (no longer hidden by a preset glob);
         lists sub-folder models + a "files in this folder" entry.
  - Clearer messages when forecast dates and the observation file's years don't overlap.
  - Added extremal-dependence scores for rare events: EDI, SEDI, EDS, SEDS (table, plots,
         per-cell score maps, bootstrap CIs).
  - Launchers force the libmamba conda solver (classic solver ran out of memory building
         the env on Windows) + clearer failure message.
  - Desktop/Start-Menu icon (Windows, auto-created first run) and Dock-able .app (Mac),
         both with a rain icon -> one double-click opens localhost:8501.
v4.0 (2026-08-19):
  - Mac first run also drops a "Rainfall Verification" Desktop icon (parity with Windows).
  - Launchers detect the env by an IMPORT check, not by parsing `conda env list` text
         (mamba indents lines, which caused a false "env not created" error after success).
  - Data defaults fall back to bundled demo_data when VERIF_DATA_DIR / VERIF_OBS are unset
         OR point at paths that don't exist on this machine -> a fresh copy always opens on demo.
v5.0 (2026-08-20):
  - Score selection split into separate Continuous and Categorical dropdowns (plots + maps),
         with a Basic set up front and Advanced (PSS/ACC/EDI/SEDI/EDS/SEDS/YuleQ) behind a toggle.
  - Colourful verification-themed app icon (score bars + magnifier + check).
  - Clean re-packaged build for a fresh install.

v5.1 (2026-09-20):
  - FIX: `--selftest` verified a fixed box (20-26N, 80-88E) at a fixed 5 mm threshold.
         On the bundled demo data that box peaks at 5.056 mm, so every score came out
         0/NaN while the test still printed "selftest OK" -- it could not fail.
         The box is now the middle half of the observation domain and the threshold is
         the upper quartile of the wet observed points, so events exist on both sides
         of it for any dataset. The scores are now asserted finite and in range, and
         the test exits non-zero on failure.
  - Add a test suite (92 tests) covering the scientific functions: categorical,
         extremal-dependence, continuous, probabilistic, FSS, CRA, bootstrap,
         regridding and unit conversion, including degenerate and missing-value cases.
  - FIX: `shapely` was missing from requirements.txt although `coastlines()` imports
         it unconditionally, so a pip-only install raised ModuleNotFoundError when the
         coastline overlay was enabled.
  - Add docs/METHODOLOGY.md (formulas, references, known caveats) and
         docs/DEMO_DATA.md (provenance, dimensions, units, conventions).
  - Add CONTRIBUTING.md, CITATION.cff, packages.txt and a GitHub Actions workflow.
  - Remove two byte-identical duplicates of app.py from version control.

v5.1.1 (2026-09-20):
  - FIX: `coastlines()` imported shapely outside its try block. Because the
         "Show coastlines / borders" checkbox defaults to on, a pip install without
         shapely did not merely lose the overlay -- EVERY verification run died with
         ModuleNotFoundError. The import now sits inside the try, so a missing
         optional geo dependency degrades to "no coastlines" as the docstring always
         claimed. (requirements.txt already pins shapely; this is the second line of
         defence, and it also covers a broken cartopy or an unreadable boundary file.)
  - Add tests/test_ui.py: 17 tests driving the real Streamlit script through the
         headless AppTest harness. Covers every mode end to end and cross-checks the
         UI's probabilistic scores against the scientific functions.
         Coverage of app.py: 35% -> 87%; _run_multimodel 0% -> 94%.

v5.2 (2026-09-20) -- security hardening:
  - FIX (high): `_save()` built an upload path with os.path.join(tempdir, u.name).
         An absolute upload name discards tempdir entirely and '..' segments traverse
         out of it, so an uploaded file could be written anywhere the process could
         write -- including over app.py. Names are now reduced to a sanitised bare
         basename and written into a freshly created private temp directory.
  - FIX (high): added optional VERIF_ROOT confinement. The sidebar takes free-text
         server paths with no restriction, which on a shared deployment is an
         arbitrary file-read and directory-enumeration primitive. Setting VERIF_ROOT
         confines every path the app opens to one tree; symlinks are resolved before
         the check, so a link inside the root pointing out of it is refused. The
         guard sits at the two open chokepoints (_open, open_any) plus
         discover_models, not only at the UI inputs. Unset = previous behaviour.
  - FIX (high): the bundled config bound 0.0.0.0, exposing an unauthenticated
         dashboard on the network. It now binds 127.0.0.1. Docker and deploy.sh pass
         --server.address=0.0.0.0 explicitly, so intentional exposure still works,
         and deploy.sh now prints a warning naming the risk.
  - FIX (medium): folder scans are bounded by VERIF_MAX_SCAN_SUBDIRS (default 500).
         Pointing the sidebar at "/" previously walked the filesystem and hung the
         server -- reproduced, >120 s before being killed.
  - FIX (medium): server.maxUploadSize reduced from 2000 MB to 500 MB.
  - Add SECURITY.md: threat model, per-deployment guidance, hardening options, what
         the audit log records, and private vulnerability reporting.
  - Add tests/test_security.py (25 tests) covering upload-name sanitisation,
         VERIF_ROOT confinement including symlink escape and traversal, the scan cap
         and the shipped configuration.
  - CI: add a pip-audit dependency-vulnerability job.
         Audited at release: no known CVEs in any runtime dependency.
  Test suite: 109 -> 134, all passing. No verification formula was changed.

v5.2.1 (2026-09-20) -- launcher portability:
  - FIX: run.command opened the browser with `open`, which exists only on macOS.
         On Linux it failed silently (stderr was discarded), so no browser opened
         at all -- despite the README listing run.command as the macOS/Linux
         launcher. Now tries $BROWSER, then xdg-open/open/gio open/gnome-open/
         kde-open/wslview, then python -m webbrowser, and prints the URL if every
         option fails. Always the user's DEFAULT browser; none is hard-coded.
  - FIX: run.command hard-coded the macOS Miniconda installer
         (Miniconda3-latest-MacOSX-$ARCH.sh), so auto-install on Linux fetched a
         macOS installer and failed. The OS is now detected, and `aarch64` is
         mapped correctly (it previously fell through to x86_64 on ARM Linux).
         All four resulting URLs verified to return HTTP 200.
  - FIX: environment.yml never declared shapely; it arrived only via cartopy,
         leaving the conda path with the same latent breakage fixed for pip in
         v5.1.1. The launchers' env readiness check now tests shapely too.
  - .shortcut_done (written by run.bat on first run) added to .gitignore.

v5.2.2 (2026-09-20) -- one-double-click setup on a clean machine:
  - FIX: setup aborted on Windows with
           CondaToSNonInteractiveError: Terms of Service have not been accepted
           for the following channels: repo.anaconda.com/pkgs/{main,r,msys2}
         environment.yml asked for conda-forge, but conda APPENDS Anaconda's
         `defaults` channel unless told not to, and those channels now refuse
         non-interactive use. The env create failed, the retry failed the same way,
         and the launcher gave up -- a new user could not install the app at all.
         Three changes so it now completes in one go with no manual step:
           1. environment.yml pins `- nodefaults`, so Anaconda's channels are never
              consulted. Verified by a dry-run solve: 25 packages, all from
              conda-forge, 0 from pkgs/main, pkgs/r or pkgs/msys2.
           2. The launchers set CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes and
              CONDA_ALWAYS_YES=yes before any conda call, and quietly run
              `conda tos accept` for each Anaconda channel, so a machine that
              already has Miniconda/Anaconda never stops to ask.
           3. When no conda is present, the launchers now install Miniforge rather
              than Miniconda. Miniforge defaults to conda-forge, carries no
              Terms-of-Service plugin, ships mamba, and avoids Anaconda's paid
              licence requirement for larger organisations.
  - The failure message no longer blames low memory for every failure; it now names
         the likely cause (ToS, memory, or network) with the exact fix for each.
