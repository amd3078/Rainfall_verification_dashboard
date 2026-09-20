#!/usr/bin/env python
"""Generate small synthetic rainfall data so the dashboard runs out-of-the-box.

Writes demo_data/obs_demo.nc (gridded obs) and demo_data/day0{1..5}fcst_demo.nc
(23-member ensembles on a slightly different grid, to exercise regridding).
No real/private data — purely synthetic. Run once:  python make_demo_data.py
"""
import os, numpy as np, xarray as xr

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "demo_data")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(0)

# common time axis: 30 days
times = np.array([np.datetime64("2020-06-01") + np.timedelta64(d, "D") for d in range(30)])

# obs grid (fine) and forecast grid (coarser, shifted) -> regridding exercised
olon = np.linspace(70, 90, 41); olat = np.linspace(8, 30, 45)
flon = np.linspace(70, 90, 33); flat = np.linspace(8, 30, 35)

ENC = lambda v: {k: {"zlib": True, "complevel": 5} for k in v}   # compress on write

def rain_field(lon, lat, t, amp):
    """Smooth moving blobs + noise, non-negative rainfall (mm)."""
    LON, LAT = np.meshgrid(lon, lat)
    cx = 80 + 5*np.sin(t/6.0); cy = 18 + 4*np.cos(t/5.0)
    base = amp*np.exp(-((LON-cx)**2/8 + (LAT-cy)**2/8))
    return np.clip(base + rng.normal(0, 1.5, LON.shape), 0, None)

# ---- observations ----
obs = np.stack([rain_field(olon, olat, t, 30) for t in range(len(times))], 0)
ods = xr.Dataset({"rf": (("time","lat","lon"), obs.astype("float32"))},
                 coords={"time": times, "lat": olat, "lon": olon})
ods.to_netcdf(f"{OUT}/obs_demo.nc", encoding=ENC(ods.data_vars))

# ---- forecasts: 5 leads, 15 members, biased/spread vs obs ----
M = 15
for lead in range(1, 6):
    truth = np.stack([rain_field(flon, flat, t, 30) for t in range(len(times))], 0)
    dv = {}
    for m in range(1, M+1):
        # add lead-dependent bias + member spread
        ens = truth*(1.05 - 0.03*lead) + rng.normal(0, 2+0.6*lead, truth.shape)
        dv[f"APCP_surface_{m}"] = (("time","lat","lon"), np.clip(ens, 0, None).astype("float32"))
    fds = xr.Dataset(dv, coords={"time": times, "lat": flat, "lon": flon})
    fds.to_netcdf(f"{OUT}/day0{lead}fcst_demo.nc", encoding=ENC(fds.data_vars))
    print("wrote", f"day0{lead}fcst_demo.nc")

# ---- demo MODEL folders (for Deterministic > Multiple models) ----
# each model = a sub-folder of single-field daily files: <Model>-day<L>_<YYYYMMDD>.nc
# filename date = valid date, dayL = lead. Two models on different grids/bias.
def write_model(name, grid, bias, leads=(1,2,3)):
    d = os.path.join(OUT, name); os.makedirs(d, exist_ok=True)
    mlon = np.linspace(70, 90, grid[0]); mlat = np.linspace(8, 30, grid[1])
    for lead in leads:
        for t in range(len(times)):
            vd = str(times[t]).replace("-", "")            # YYYYMMDD (valid date)
            fld = np.clip(rain_field(mlon, mlat, t, 30)*bias + rng.normal(0, 1.5+0.4*lead, (grid[1],grid[0])), 0, None)
            ds = xr.Dataset({"APCP_surface": (("time","lat","lon"), fld[None].astype("float32"))},
                            coords={"time": np.array([times[t]]), "lat": mlat, "lon": mlon})
            ds.to_netcdf(f"{d}/{name}-day{lead}_{vd}.nc", encoding=ENC(ds.data_vars))
    print("wrote model folder", name, f"({len(leads)*len(times)} files)")

write_model("ModelA", (41,45), 1.00)
write_model("ModelB", (33,35), 0.85)

print("demo data ->", OUT)
