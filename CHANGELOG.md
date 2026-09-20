Rainfall Verification Dashboard
version: v5.0
build: 2026-08-20
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
