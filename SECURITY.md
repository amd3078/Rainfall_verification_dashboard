# Security policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/amd3078/Rainfall_verification_dashboard/security/advisories/new)
rather than opening a public issue. Include what you did, what happened, and the
impact you believe it has. You can expect an acknowledgement within a week.

---

## Threat model — read this before deploying

The Rainfall Verification Dashboard is a **scientific analysis tool designed for a
trusted user**. It deliberately opens files by server-side path, because a
meteorologist verifying a season of forecasts needs to point it at an archive
directory rather than upload gigabytes through a browser.

That design is safe on your own machine and **unsafe on an open network**, because:

- **There is no authentication.** The application has no concept of users, logins,
  sessions or roles. Anyone who can reach the port can use every feature.
- **The sidebar accepts free-text server paths.** "Models base directory" and
  "Observation file" are opened server-side. Without `VERIF_ROOT` set (below), a
  user can enumerate directories and open any NetCDF or GRIB file the process can
  read.
- **Errors can reveal filesystem structure.** A path that fails to open produces a
  message naming it.

**Treat anyone who can reach the dashboard as having the read access of the account
running it.**

### Deployment guidance

| Deployment | Guidance |
|---|---|
| **Your own laptop** (the default) | Safe as designed. The bundled config binds `127.0.0.1`, so nothing is reachable from the network |
| **A shared workstation** | Set `VERIF_ROOT` to the data directory. Run as an account with no access to anything else |
| **A server, multiple users** | **Required:** put it behind a reverse proxy that authenticates (nginx with auth, an SSO proxy, or a VPN). **Required:** set `VERIF_ROOT`. Run as a dedicated unprivileged user with read-only access to the data |
| **The public internet** | Not supported. Do not do this |

### Hardening options

| Control | Default | What it does |
|---|---|---|
| `VERIF_ROOT` | unset (unrestricted) | Confines every path the application will open to one directory tree. Symlinks are resolved first, so a link inside the root pointing outside it is refused. The bundled demo data and browser uploads remain readable |
| `VERIF_MAX_SCAN_SUBDIRS` | `500` | Caps how many sub-directories one folder scan will stat, so pointing the sidebar at `/` cannot hang the server |
| `server.address` | `127.0.0.1` | Loopback only. Override explicitly (`--server.address=0.0.0.0`) when you intend network exposure; the Dockerfile does this because a container must |
| `server.maxUploadSize` | `500` MB | Bounds browser uploads |
| `server.enableXsrfProtection` | `true` | Leave enabled |

Example hardened launch:

```bash
export VERIF_ROOT=/data/verification        # confine all file access
export VERIF_DATA_DIR=/data/verification/forecasts
export VERIF_OBS=/data/verification/obs/imd_rf.nc
streamlit run app.py                        # binds 127.0.0.1 by default
# then expose it only through an authenticating reverse proxy
```

---

## What the application does with your data

- **Files are read, never modified.** The application opens observation and forecast
  files read-only. It does not write to your data directories.
- **Uploads** go to a freshly created private temporary directory, under a
  sanitised basename. They are not written into the project tree. Your operating
  system's temp cleaner removes them; delete them sooner if they are sensitive.
- **The audit log** (`logs/audit.jsonl`, or `VERIF_AUDIT`) records the timestamp,
  a random session id, the input file **paths**, the period, threshold, box and the
  resulting scores. It does not record file contents. If your file paths are
  themselves sensitive, point `VERIF_AUDIT` somewhere protected.
- **Firestore audit** (optional, off unless `VERIF_FIREBASE_CRED` is set) sends those
  same records to a cloud database you own. Leave it unset if you do not want that.
- **Nothing is sent anywhere else.** There is no telemetry;
  `browser.gatherUsageStats` is disabled in the bundled config.

## Secrets

Never commit credentials. The `.gitignore` blocks `.env`, `*serviceAccount*.json`,
`*firebase*.json`, `*credentials*.json`, `secrets.toml`, `*.pem`, `*.key` and
`id_rsa*`. A Firebase service-account key grants write access to your Firestore
project — store it outside the repository and point `VERIF_FIREBASE_CRED` at it.

## Dependencies

Runtime dependencies are pinned by lower bound in `requirements.txt` and checked with
`pip-audit` in CI. The application uses no `eval`, `exec`, `pickle`, `subprocess` or
`shell=True`.

## Supported versions

Security fixes are applied to the latest release only.
