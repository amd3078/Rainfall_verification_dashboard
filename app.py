"""Rainfall verification dashboard (Streamlit) — server/institutional deployment ready.

Scales to many years/months because it reads ONLY the viewed time-slice from disk
(lazy indexing), never the whole file. Two data modes:
  - Server folder  : point to a directory + glob (no upload; for large data on the server).
  - Upload         : small files via browser.

Features: obs + forecasts (files = lead times | models | ensemble members = models);
internal bilinear regrid to obs grid; draw-box on obs map OR numeric bounds (synced,
drawn on all panels); categorical scores POD/FAR/CSI/BIAS/ETS/HSS/PSS/ACC for the box;
scores vs lead (line) or across models (bars); default threshold 0.1 mm or user value.

Run:  streamlit run app.py    |   Self-test: python app.py --selftest
Config via env: VERIF_DATA_DIR (default folder shown in the UI).
"""
import os, re, glob, sys, json, uuid, datetime
import numpy as np, xarray as xr
from scipy.interpolate import RegularGridInterpolator
_trapz = getattr(np, "trapezoid", None) or np.trapz    # np.trapz removed in numpy 2.x

AUDIT_LOG   = os.environ.get("VERIF_AUDIT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "audit.jsonl"))
FB_CRED     = os.environ.get("VERIF_FIREBASE_CRED")                         # path to service-account JSON (optional)
FB_COLL     = os.environ.get("VERIF_FIREBASE_COLLECTION", "audit")         # Firestore collection name
_FS = {"client": None, "tried": False}

def _firestore():
    """Lazy Firestore client. Returns None if not configured / SDK missing."""
    if _FS["tried"]:
        return _FS["client"]
    _FS["tried"] = True
    if not FB_CRED:
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(FB_CRED))
        _FS["client"] = firestore.client()
    except Exception:
        _FS["client"] = None
    return _FS["client"]

def audit(record):
    """Record who/when + files + params + scores. Writes JSONL always; Firestore if configured. Never breaks UI."""
    record = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), **record}
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass
    db = _firestore()
    if db is not None:
        try:
            db.collection(FB_COLL).add(json.loads(json.dumps(record, default=str)))  # JSON-safe types
        except Exception:
            pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.join(_HERE, "demo_data"); _DEMO_OBS = os.path.join(_DEMO_DIR, "obs_demo.nc")
# Use VERIF_* if set AND present on THIS machine; otherwise fall back to bundled demo data,
# so a fresh copy (or a config pointing at paths that don't exist here) still opens on demo.
DEFAULT_DIR = os.environ.get("VERIF_DATA_DIR") or _DEMO_DIR
if not os.path.exists(DEFAULT_DIR): DEFAULT_DIR = _DEMO_DIR
DEFAULT_OBS = os.environ.get("VERIF_OBS") or _DEMO_OBS
if not os.path.exists(DEFAULT_OBS): DEFAULT_OBS = _DEMO_OBS
RAIN_VARS = ["rf", "APCP_24", "APCP_surface", "precip", "precipitation", "tp"]

import contextlib
def _nullctx(): return contextlib.nullcontext()

# Memoize slice/catalog reads across reruns AND users. No-op if streamlit absent (selftest).
try:
    import streamlit as _stc
    cache = _stc.cache_data(max_entries=4096, show_spinner=False)
except Exception:
    def cache(f): return f

def _coord(ds, names):
    for n in names:
        if n in ds.coords or n in ds.variables: return n
    for n in list(ds.coords) + list(ds.variables):
        if any(k in n.lower() for k in names): return n
    return None

_DSCACHE={}   # keep NetCDF files open across dates/reruns -> no repeated file-open cost
_TVCACHE={}   # cached datetime64[D] time axis per path

def _open(path):
    ds = _DSCACHE.get(path)
    if ds is None:
        ds = xr.open_dataset(path, decode_times=True); _DSCACHE[path] = ds   # lazy; not closed
    return ds, _coord(ds, ["lon","longitude"]), _coord(ds, ["lat","latitude"]), _coord(ds, ["time"])

def _timeaxis(ds, tname, path):
    tv = _TVCACHE.get(path)
    if tv is None:
        tv = np.array(ds[tname].values, dtype="datetime64[D]") if tname else np.array([np.datetime64("2000-01-01")])
        _TVCACHE[path] = tv
    return tv

def _clean(d):
    """Sentinel/fill (huge magnitude) -> NaN; small negatives (post-processed rainfall) -> 0.
    Avoids dropping models like UKMO whose bias-corrected fields have real small negatives."""
    d = np.asarray(d, dtype="float64")
    d = np.where(np.abs(d) > 1e6, np.nan, d)
    return np.clip(d, 0, None)

def _unit_factor(u):
    """Factor to convert a rainfall 'units' string to mm. None = unknown/missing."""
    if not u: return None
    s=str(u).strip().lower()
    if s.startswith(("mm","kg/m2","kg m-2","kg m^-2","kg/m^2","kg m -2")): return 1.0
    if s.startswith("cm"): return 10.0
    if s.startswith(("m/","m ","m3")) or s in ("m","meter","metre"): return 1000.0
    if "inch" in s or s=="in": return 25.4
    return None
@cache
def file_units(path):
    """Read the rainfall variable's units attribute -> factor to mm (None if absent/unknown)."""
    try:
        ds=open_any(path)
        var=next((v for v in RAIN_VARS if v in ds.data_vars),None) or [v for v in ds.data_vars if ds[v].ndim>=2][0]
        f=_unit_factor(ds[var].attrs.get("units")); ds.close(); return f
    except Exception:
        return None

def members_of(ds):
    return sorted([v for v in ds.data_vars if v.startswith("APCP_surface_")],
                  key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))

@cache
def catalog(path):
    """Cheap: grid + times + member list (no field data read)."""
    ds, lon, lat, tname = _open(path)
    lo = ds[lon].values; la = ds[lat].values
    tv = _timeaxis(ds, tname, path)
    return dict(lon=lo, lat=la, times=tv, members=members_of(ds), tname=tname)

@cache
def read_slice(path, date, member=None):
    """Read ONLY the 2-D field for `date` (lazy index -> load one slab). member=None => ensemble mean."""
    ds, lon, lat, tname = _open(path)
    if tname:
        tv = _timeaxis(ds, tname, path); ti = np.where(tv == date)[0]
        if not len(ti): return None
        ds = ds.isel({tname: int(ti[0])})
    mem = members_of(ds)
    if member is not None: da = ds[member]
    elif mem: da = sum(ds[v] for v in mem) / len(mem)
    else:
        var = next((v for v in RAIN_VARS if v in ds.data_vars), None) or list(ds.data_vars)[0]; da = ds[var]
    d = da.transpose(lat, lon).values                    # materialize just this slab
    return _clean(d)

@cache
def read_members(path, date):
    """Read ALL members for `date` -> (M,lat,lon) on native grid, or None if no members."""
    ds, lon, lat, tname = _open(path)
    if tname:
        tv = _timeaxis(ds, tname, path); ti = np.where(tv == date)[0]
        if not len(ti): return None
        ds = ds.isel({tname: int(ti[0])})
    mem = members_of(ds)
    if not mem: return None
    arr = np.stack([_clean(ds[v].transpose(lat, lon).values) for v in mem], 0)
    return arr.astype(np.float32)

def regrid(flon, flat, fslice, olon, olat):
    f = np.where(np.isfinite(fslice), fslice, np.nan).astype(float)
    nlon, nlat = len(flon), len(flat)
    # RegularGridInterpolator wants values shaped (nlon, nlat). Our readers always return (lat,lon),
    # so try that FIRST — critical for square grids (nlon==nlat) where both shapes match.
    if f.shape == (nlat, nlon):      vals = f.T          # (lat, lon) -> (lon, lat)   [readers emit this]
    elif f.shape == (nlon, nlat):    vals = f            # already (lon, lat)
    else:                            vals = f.T          # fallback
    rgi = RegularGridInterpolator((flon, flat), vals, bounds_error=False, fill_value=np.nan)
    LATg, LONg = np.meshgrid(olat, olon, indexing="ij")
    return rgi(np.stack([LONg.ravel(), LATg.ravel()], -1)).reshape(len(olat), len(olon))

def _default_boundary():
    """Auto-use a boundary file bundled in ./boundary/ (shapefile or geojson) if present."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boundary")
    if os.path.isdir(d):
        for e in ("*.shp", "*.geojson", "*.json"):
            g = sorted(glob.glob(os.path.join(d, e)))
            if g: return g[0]
    return None
BOUNDARY_FILE = os.environ.get("VERIF_BOUNDARY") or _default_boundary()   # official boundary: env, else bundled ./boundary/
_COAST = {}

def _polylines(geoms, clip, xs, ys):
    """Append boundary polylines (clipped) of shapely geometries to xs/ys with None gaps."""
    from shapely.geometry import LineString, MultiLineString
    for g in geoms:
        try:
            b = g.boundary if g.geom_type in ("Polygon","MultiPolygon") else g
            b = b.intersection(clip).simplify(0.01)   # ~1 km: keeps shape, cuts point count
        except Exception:
            continue
        if b.is_empty: continue
        for p in getattr(b, "geoms", [b]):
            xy = getattr(p, "coords", None)
            if xy is None: continue
            a = np.asarray(list(xy))
            if a.ndim != 2 or len(a) < 2: continue
            xs.extend(a[:,0].tolist() + [None]); ys.extend(a[:,1].tolist() + [None])

def _read_boundary_geoms(path):
    """Read geometries from a GeoJSON (no extra deps) or shapefile (needs geopandas/fiona)."""
    from shapely.geometry import shape
    if path.lower().endswith((".geojson", ".json")):
        gj = json.load(open(path))
        feats = gj.get("features", [gj]) if isinstance(gj, dict) else []
        out = []
        for f in feats:
            geom = f.get("geometry", f) if isinstance(f, dict) else None
            if geom: out.append(shape(geom))
        return out
    try:
        import cartopy.io.shapereader as shpreader   # read .shp without geopandas
        return list(shpreader.Reader(path).geometries())
    except Exception:
        import geopandas as gpd                      # fallback: any OGR format
        return list(gpd.read_file(path).geometry)

def coastlines(lon0, lon1, lat0, lat1, res="50m"):
    """Boundary polylines within the extent, as (xs,ys) with None gaps.
    Prefers the official file in VERIF_BOUNDARY; else Natural Earth (cartopy). Safe no-op on failure."""
    key = (round(lon0,1), round(lon1,1), round(lat0,1), round(lat1,1), res, BOUNDARY_FILE or "ne")
    if key in _COAST:
        return _COAST[key]
    xs, ys = [], []
    try:
        # Inside the try: the overlay is decoration, so a missing optional geo
        # dependency must degrade to "no coastlines", never kill the whole run.
        from shapely.geometry import box as _box
        clip = _box(lon0, lat0, lon1, lat1)
        if BOUNDARY_FILE and os.path.exists(BOUNDARY_FILE):
            _polylines(_read_boundary_geoms(BOUNDARY_FILE), clip, xs, ys)
        else:
            import cartopy.feature as cfeature
            for feat in (cfeature.NaturalEarthFeature("physical","coastline",res),
                         cfeature.NaturalEarthFeature("cultural","admin_0_boundary_lines_land",res)):
                _polylines(list(feat.geometries()), clip, xs, ys)
    except Exception:
        xs, ys = [], []
    _COAST[key] = (xs, ys)
    return _COAST[key]

def counts(F, O, thr):
    """Contingency counts (a,b,c,d) for one field pair."""
    m = np.isfinite(F) & np.isfinite(O); f = (F[m] >= thr); o = (O[m] >= thr)
    return (int((f&o).sum()), int((f&~o).sum()), int((~f&o).sum()), int((~f&~o).sum()))

def scores_from_counts(a, b, c, d):
    N=a+b+c+d; s=lambda x,y: x/y if y else np.nan; ar=s((a+b)*(a+c),N)
    H=s(a,a+c); F=s(b,b+d)                                   # hit rate, false-alarm rate
    edi=sedi=eds=seds=np.nan                                 # extremal-dependence family (skill->1 as base rate->0)
    if 0<H<1 and 0<F<1:
        edi=(np.log(F)-np.log(H))/(np.log(F)+np.log(H))
        sedi=(np.log(F)-np.log(H)-np.log(1-F)+np.log(1-H))/(np.log(F)+np.log(H)+np.log(1-F)+np.log(1-H))
    if a>0 and N>0:
        lnaN=np.log(a/N)
        if lnaN!=0:
            if (a+c)>0: eds=2*np.log((a+c)/N)/lnaN-1
            if (a+b)>0 and (a+c)>0: seds=(np.log((a+b)/N)+np.log((a+c)/N))/lnaN-1
    yq=s(a*d-b*c, a*d+b*c)                                   # Yule's Q (odds-ratio skill)
    return dict(POD=H,FAR=s(b,a+b),CSI=s(a,a+b+c),BIAS=s(a+b,a+c),
                ETS=s(a-ar,a+b+c-ar),HSS=s(2*(a*d-b*c),(a+c)*(c+d)+(a+b)*(b+d)),
                PSS=H-F,ACC=s(a+d,N),EDI=edi,SEDI=sedi,EDS=eds,SEDS=seds,YuleQ=yq,N=N)

def scores(F, O, thr):
    return scores_from_counts(*counts(F, O, thr))

FSS_NS=[1,3,5,9,15,21,31]
def fss_accum(BF, BO, ns):
    """Per-neighbourhood FSS numerator/denominator for one date. BF,BO binary 2-D (box)."""
    from scipy.ndimage import uniform_filter
    out={}
    for n in ns:
        PF=uniform_filter(BF.astype(float),size=n,mode="constant")
        PO=uniform_filter(BO.astype(float),size=n,mode="constant")
        out[n]=(float(np.sum((PF-PO)**2)), float(np.sum(PF*PF+PO*PO)))
    return out
def cra_decomp(F, O, maxs=8, thr=0.1):
    """CRA (Ebert–McBride): optimal whole-field shift + MSE decomposition + descriptive stats."""
    F=np.where(np.isfinite(F),F,0.0); O=np.where(np.isfinite(O),O,0.0)
    def corr(a,bb):
        a=a.ravel(); bb=bb.ravel(); sa=a.std(); sb=bb.std()
        return float(((a-a.mean())*(bb-bb.mean())).mean()/(sa*sb)) if sa>0 and sb>0 else np.nan
    base=float(np.mean((F-O)**2)); best=base; bsh=(0,0)
    for dy in range(-maxs,maxs+1):
        for dx in range(-maxs,maxs+1):
            Fs=np.roll(np.roll(F,dy,0),dx,1); m=float(np.mean((Fs-O)**2))
            if m<best: best=m; bsh=(dy,dx)
    Fs=np.roll(np.roll(F,bsh[0],0),bsh[1],1)
    vol=float((F.mean()-O.mean())**2); disp=max(base-best,0.0); patt=max(best-vol,0.0)
    return dict(total=base,displacement=disp,volume=vol,pattern=patt,RMSE=float(np.sqrt(base)),
                CORR=corr(F,O),CORR_shift=corr(Fs,O),maxF=float(F.max()),maxO=float(O.max()),
                meanF=float(F.mean()),meanO=float(O.mean()),dx=float(bsh[1]),dy=float(bsh[0]),
                areaF=float((F>=thr).mean()),areaO=float((O>=thr).mean()))

def boot_metric(S, name):
    """Score(s) from summed per-date stats S (N,12): A,B,C,D,n,sF,sO,sF2,sO2,sFO,sae,sse."""
    A,B,C,D,n,sF,sO,sF2,sO2,sFO,sae,sse=[S[:,i] for i in range(12)]
    with np.errstate(divide="ignore",invalid="ignore"):
        if name=="POD": return A/(A+C)
        if name=="FAR": return B/(A+B)
        if name=="CSI": return A/(A+B+C)
        if name=="BIAS": return (A+B)/(A+C)
        if name=="ETS": ar=(A+B)*(A+C)/(A+B+C+D); return (A-ar)/(A+B+C-ar)
        if name=="HSS": return 2*(A*D-B*C)/((A+C)*(C+D)+(A+B)*(B+D))
        if name=="PSS": return A/(A+C)-B/(B+D)
        if name=="ACC": return (A+D)/(A+B+C+D)
        if name=="EDI":
            H=A/(A+C); F=B/(B+D); return (np.log(F)-np.log(H))/(np.log(F)+np.log(H))
        if name=="SEDI":
            H=A/(A+C); F=B/(B+D)
            return (np.log(F)-np.log(H)-np.log(1-F)+np.log(1-H))/(np.log(F)+np.log(H)+np.log(1-F)+np.log(1-H))
        if name=="EDS":
            Nn=A+B+C+D; return 2*np.log((A+C)/Nn)/np.log(A/Nn)-1
        if name=="SEDS":
            Nn=A+B+C+D; return (np.log((A+B)/Nn)+np.log((A+C)/Nn))/np.log(A/Nn)-1
        if name=="YuleQ": return (A*D-B*C)/(A*D+B*C)
        if name=="ME": return (sF-sO)/n
        if name=="MAE": return sae/n
        if name=="RMSE": return np.sqrt(sse/n)
        if name=="CORR":
            mF=sF/n; mO=sO/n; return (sFO/n-mF*mO)/np.sqrt((sF2/n-mF*mF)*(sO2/n-mO*mO))
    return np.full(S.shape[0], np.nan)
def prob_boot_ci(pr, name, nboot, ci=95, seed=0):
    """CI for Brier/BSS/CRPS by resampling dates (per-date values in pr)."""
    pdB=np.asarray(pr.get("pdB",[]),float); pdC=np.asarray(pr.get("pdC",[]),float); pdCl=np.asarray(pr.get("pdCl",[]),float)
    nd=len(pdB)
    if nd<2: return (np.nan,np.nan)
    rng=np.random.default_rng(seed); idx=rng.integers(0,nd,(int(nboot),nd))
    with np.errstate(divide="ignore",invalid="ignore"):
        if name=="Brier": v=pdB[idx].mean(1)
        elif name=="CRPS": v=pdC[idx].mean(1)
        elif name=="BSS":
            b=pdB[idx].mean(1); cl=pdCl[idx].mean(1); v=1-b/(cl*(1-cl))
        else: return (np.nan,np.nan)
    v=v[np.isfinite(v)]
    if v.size==0: return (np.nan,np.nan)
    lo=(100-ci)/2; return (float(np.percentile(v,lo)),float(np.percentile(v,100-lo)))
def boot_ci(perdate, name, nboot, ci=95, seed=0):
    """95% CI (lo,hi) of a score by resampling dates with replacement."""
    a=np.asarray(perdate,dtype=float)
    if a.ndim!=2 or len(a)<2: return (np.nan,np.nan)
    rng=np.random.default_rng(seed); idx=rng.integers(0,len(a),(int(nboot),len(a)))
    S=a[idx].sum(axis=1); v=boot_metric(S,name); v=v[np.isfinite(v)]
    if v.size==0: return (np.nan,np.nan)
    lo=(100-ci)/2; return (float(np.percentile(v,lo)), float(np.percentile(v,100-lo)))

def cellwise_cat(a,b,c,d):
    """Per-cell categorical scores from 2-D contingency arrays."""
    n=a+b+c+d
    with np.errstate(divide="ignore",invalid="ignore"):
        H=a/(a+c); F=b/(b+d); ar=(a+b)*(a+c)/n
        out=dict(POD=H,FAR=b/(a+b),CSI=a/(a+b+c),BIAS=(a+b)/(a+c),
                 ETS=(a-ar)/(a+b+c-ar),HSS=2*(a*d-b*c)/((a+c)*(c+d)+(a+b)*(b+d)),
                 PSS=H-F,ACC=(a+d)/n,EDI=(np.log(F)-np.log(H))/(np.log(F)+np.log(H)),
                 SEDI=(np.log(F)-np.log(H)-np.log(1-F)+np.log(1-H))/(np.log(F)+np.log(H)+np.log(1-F)+np.log(1-H)),
                 EDS=2*np.log((a+c)/n)/np.log(a/n)-1,
                 SEDS=(np.log((a+b)/n)+np.log((a+c)/n))/np.log(a/n)-1,
                 YuleQ=(a*d-b*c)/(a*d+b*c))
    return out
def cellwise_cont(cn,cF,cO,cF2,cO2,cFO,cae,cse):
    """Per-cell continuous scores from 2-D running sums."""
    with np.errstate(divide="ignore",invalid="ignore"):
        mF=cF/cn; mO=cO/cn; vF=cF2/cn-mF*mF; vO=cO2/cn-mO*mO; cov=cFO/cn-mF*mO
        return dict(ME=mF-mO,MAE=cae/cn,RMSE=np.sqrt(cse/cn),CORR=cov/np.sqrt(vF*vO))
def cell_maps(acc, minn=3):
    """Merge cell-wise categorical+continuous score maps; mask cells with <minn samples."""
    cn,cF,cO,cF2,cO2,cFO,cae,cse,ca,cb,cc,cd = acc
    m={**cellwise_cat(ca,cb,cc,cd), **cellwise_cont(cn,cF,cO,cF2,cO2,cFO,cae,cse)}
    bad=cn<minn
    for k in m: m[k]=np.where(bad,np.nan,m[k])
    return m

def crps_points(ens, y):
    """Mean CRPS over 1-D pooled points. ens (M,Npts), y (Npts)."""
    if ens is None or ens.size==0: return np.nan
    M=ens.shape[0]; xs=np.sort(ens,axis=0)
    t1=np.mean(np.abs(ens-y[None]),axis=0)
    i=np.arange(1,M+1)[:,None]
    t2=(2.0/M**2)*np.sum((2*i-M-1)*xs,axis=0)
    return float(np.nanmean(t1-0.5*t2))

def crps_ens(ens, y, mask):
    """ens (M,lat,lon), y (lat,lon); mean CRPS over mask (sorted-formula)."""
    M = ens.shape[0]; xs = np.sort(ens, axis=0)
    t1 = np.mean(np.abs(ens - y[None]), axis=0)
    i = np.arange(1, M+1)[:, None, None]
    t2 = (2.0/M**2) * np.sum((2*i - M - 1) * xs, axis=0)
    cr = t1 - 0.5*t2; return float(np.nanmean(cr[mask]))

def prob_scores(P, O, thr, mask, ens_obsgrid=None):
    obin = (O >= thr).astype(float)
    d = (P - obin)[mask]; d = d[np.isfinite(d)]
    bs = float(np.mean(d*d)); clim = float(np.mean(obin[mask]))
    bss = 1 - bs/(clim*(1-clim)) if 0 < clim < 1 else np.nan
    cr = crps_ens(ens_obsgrid, O, mask) if ens_obsgrid is not None else np.nan
    return dict(Brier=bs, BSS=bss, CRPS=cr, clim=clim)

def reliability_curve(p, obin, nb=10):
    """Binned forecast prob vs observed freq. Returns (mean_p, obs_freq, count) per non-empty bin."""
    edges=np.linspace(0,1,nb+1); idx=np.clip(np.digitize(p,edges)-1,0,nb-1)
    mp=[];of=[];n=[]
    for b in range(nb):
        s=idx==b
        if s.sum(): mp.append(p[s].mean()); of.append(obin[s].mean()); n.append(int(s.sum()))
    return np.array(mp),np.array(of),np.array(n)

def roc_curve(p, obin):
    """Hit rate vs false-alarm rate over prob thresholds. Returns (F,H,AUC)."""
    P=obin.sum(); N=len(obin)-P; th=np.unique(np.r_[0,np.sort(p),1.0001])
    H=[];F=[]
    for t in th[::-1]:
        d=p>=t; H.append((d&(obin==1)).sum()/max(P,1)); F.append((d&(obin==0)).sum()/max(N,1))
    F=np.array(F);H=np.array(H); return F,H,float(_trapz(H,F))

def rev_curve(p, obin, rs):
    """Relative economic value envelope vs cost/loss ratio rs (max over prob thresholds)."""
    s=obin.mean(); P=obin.sum(); N=len(obin)-P; pth=np.linspace(0.01,0.99,99)
    HH=[];FF=[]
    for t in pth:
        d=p>=t; HH.append((d&(obin==1)).sum()/max(P,1)); FF.append((d&(obin==0)).sum()/max(N,1))
    HH=np.array(HH);FF=np.array(FF); V=[]
    for r in rs:
        Ecl=min(r,s); Epf=s*r
        Efc=r*(HH*s+FF*(1-s))+(1-HH)*s
        V.append(float(np.nanmax((Ecl-Efc)/(Ecl-Epf+1e-12))))
    return np.array(V)

def pit_values(ens, obs):
    """Randomised PIT: forecast CDF evaluated at obs, in [0,1]. Uniform = calibrated."""
    M=ens.shape[0]
    below=(ens<obs[None]).sum(0); eq=(ens==obs[None]).sum(0)
    return (below + np.random.default_rng(0).random(len(obs))*(eq+1))/(M+1)
def crps_grid(ens, obs):
    """Per-cell CRPS. ens (M,ny,nx), obs (ny,nx) -> (ny,nx)."""
    M=ens.shape[0]; xs=np.sort(ens,axis=0)
    t1=np.mean(np.abs(ens-obs[None]),axis=0)
    i=np.arange(1,M+1)[:,None,None]
    t2=(2.0/M**2)*np.sum((2*i-M-1)*xs,axis=0)
    return t1-0.5*t2
def rank_hist(ens, obs):
    """Verification rank of obs among M members -> counts length M+1 (flat=well-calibrated)."""
    M=ens.shape[0]; rank=(ens<obs[None]).sum(0)
    ties=(ens==obs[None]).sum(0)
    rank=rank+(np.random.rand(len(obs))*(ties+1)).astype(int)  # randomize ties
    rank=np.clip(rank,0,M)
    return np.bincount(rank,minlength=M+1)

def spread_skill(ens, obs, nbin=8):
    """Bin points by ensemble spread; return (mean_spread, rmse) per bin + overall."""
    sd=ens.std(0,ddof=1); em=ens.mean(0); err=em-obs
    q=np.quantile(sd,np.linspace(0,1,nbin+1)); xs=[];ys=[]
    for b in range(nbin):
        m=(sd>=q[b])&(sd<=q[b+1]) if b==nbin-1 else (sd>=q[b])&(sd<q[b+1])
        if m.sum()>2: xs.append(sd[m].mean()); ys.append(np.sqrt(np.mean(err[m]**2)))
    return np.array(xs),np.array(ys),float(sd.mean()),float(np.sqrt(np.mean(err**2)))

def lead_from(p):
    m=re.search(r"day0?(\d+)", os.path.basename(p)); return int(m.group(1)) if m else None

# ================= generic multi-model deterministic ingestion (any format/grid) =================
GRIB_EXT=(".grib",".grib2",".grb",".grb2")
def _is_grib(p): return p.lower().endswith(GRIB_EXT)
def open_any(path):
    """Open NetCDF or GRIB2 transparently."""
    if _is_grib(path):
        return xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath":""})
    return xr.open_dataset(path)
def _has_fc(folder):
    return any(glob.glob(os.path.join(folder,e)) for e in ("*.nc","*.grib2","*.grb2","*.grib"))
def lead_of(path):
    b=os.path.basename(path)
    for pat in (r"day0?(\d+)", r"lead0?(\d+)", r"[_-]f(\d+)"):
        m=re.search(pat,b,re.I)
        if m: return int(m.group(1))
    return None
@cache
def _dates_of(path):
    """Valid dates in a file as [(YYYY-MM-DD, time_index), ...].
    Works for split files (one date) AND per-lead files with a full time axis (many dates)."""
    try:
        ds=open_any(path); tn=_coord(ds,["time","valid_time"])
        if tn is not None:
            tv=np.array(ds[tn].values).ravel().astype("datetime64[D]"); ds.close()
            return [(str(tv[i]), int(i)) for i in range(len(tv))]
        ds.close()
    except Exception:
        return []
    b=os.path.basename(path); m=re.search(r"(\d{8})", b)   # no time coord -> date from filename
    if m: return [(f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}", 0)]
    return []
@cache
def scan_model(folder):
    """List (path,lead,vdate,tidx) for every forecast in a model folder. Prefer NetCDF if present.
    A file may hold one date or a whole time axis — each date becomes one entry."""
    files=glob.glob(os.path.join(folder,"*.nc"))
    if not files:
        for e in ("*.grib2","*.grb2","*.grib"): files+=glob.glob(os.path.join(folder,e))
    out=[]
    for f in sorted(files):
        L=lead_of(f)
        if L is None: continue
        for vd,ti in _dates_of(f):
            out.append(dict(path=f, lead=L, vdate=vd, tidx=ti))
    return out
def _orient2d(da, lat, lon, lo, la):
    try: d=da.transpose(lat,lon).values
    except Exception:
        d=np.asarray(da.values)
        if d.shape==(len(lo),len(la)): d=d.T
    return d
def fc_read(path, tidx=0):
    """One 2-D rainfall field (time index tidx) + grid. If the file has ensemble members, returns their MEAN."""
    ds=open_any(path)
    lon=_coord(ds,["lon","longitude"]); lat=_coord(ds,["lat","latitude"]); tn=_coord(ds,["time","valid_time"])
    lo=np.asarray(ds[lon].values); la=np.asarray(ds[lat].values)
    mem=members_of(ds)
    if mem:
        acc=None
        for v in mem:
            da=ds[v]
            if tn is not None and tn in da.dims: da=da.isel({tn:int(tidx)})
            a=_orient2d(da.squeeze(),lat,lon,lo,la); acc=a if acc is None else acc+a
        d=acc/len(mem)
    else:
        var=next((v for v in RAIN_VARS if v in ds.data_vars),None) or [v for v in ds.data_vars if ds[v].ndim>=2][0]
        da=ds[var]
        if tn is not None and tn in da.dims: da=da.isel({tn:int(tidx)})
        d=_orient2d(da.squeeze(),lat,lon,lo,la)
    ds.close()
    return dict(field=_clean(d), lon=lo, lat=la)
def fc_members(path, tidx=0):
    """All members at time tidx -> (M,ny,nx) on native grid + grid. None if no members."""
    ds=open_any(path)
    lon=_coord(ds,["lon","longitude"]); lat=_coord(ds,["lat","latitude"]); tn=_coord(ds,["time","valid_time"])
    lo=np.asarray(ds[lon].values); la=np.asarray(ds[lat].values); mem=members_of(ds)
    if not mem: ds.close(); return None
    out=[]
    for v in mem:
        da=ds[v]
        if tn is not None and tn in da.dims: da=da.isel({tn:int(tidx)})
        out.append(_clean(_orient2d(da.squeeze(),lat,lon,lo,la)))
    ds.close()
    return dict(ens=np.stack(out,0), lon=lo, lat=la)

def _dl_table(st, df, key):
    c=st.columns(2)
    c[0].download_button("⬇ scores (CSV)", df.to_csv(index=False).encode(), file_name=f"{key}.csv", mime="text/csv", key=key+"_csv")
    c[1].download_button("⬇ scores (text)", df.to_string(index=False).encode(), file_name=f"{key}.txt", mime="text/plain", key=key+"_txt")
def _export_fig(st, fig, key):
    with st.expander("Export figure (PNG / JPEG / SVG / PDF)"):
        c=st.columns(4)
        fmt=c[0].selectbox("Format",["png","jpeg","svg","pdf"],key=key+"f")
        w=c[1].number_input("Width px",300,6000,1100,step=50,key=key+"w")
        h=c[2].number_input("Height px",300,6000,650,step=50,key=key+"h")
        scl=c[3].number_input("Scale (DPI = 96×)",1.0,6.0,3.0,step=0.5,key=key+"s")
        try:
            img=fig.to_image(format=fmt,width=int(w),height=int(h),scale=float(scl))
            st.download_button(f"⬇ download .{fmt}  (~{int(96*scl)} dpi)",img,file_name=f"{key}.{fmt}",mime="application/octet-stream",key=key+"dl")
        except Exception:
            st.caption("Figure export needs **kaleido** (`pip install kaleido` / it's in environment.yml). Meanwhile use the camera icon on the chart.")

def _fc_files(folder):
    f=glob.glob(os.path.join(folder,"*.nc"))
    if not f:
        for e in ("*.grib2","*.grb2","*.grib"): f+=glob.glob(os.path.join(folder,e))
    return sorted(f)
@cache
def scan_files(paths):
    """scan_model on an explicit file list (paths must be a tuple, for caching)."""
    out=[]
    for f in paths:
        L=lead_of(f)
        if L is None: continue
        for vd,ti in _dates_of(f): out.append(dict(path=f, lead=L, vdate=vd, tidx=ti))
    return out
def _model_name(fname):
    """Model name from a filename: text before 'dayN', with date/init/hour tokens removed.
    'NCUM_day1.nc'->NCUM ; 'ncum-rain-IC20250616-03z-day1.nc'->ncum-rain ; 'GFS-day1_20250617-03z.nc'->GFS"""
    s=re.split(r'[_-]?day\s*\d', fname, maxsplit=1, flags=re.I)[0]
    s=re.sub(r'IC\d{6,8}','',s,flags=re.I)          # init-date token
    s=re.sub(r'\d{6,8}','',s)                        # any date
    s=re.sub(r'\b\d{1,2}z\b','',s,flags=re.I)        # hour like 03z
    s=re.sub(r'[_\-.]+',' ',s).strip().replace(' ','_').strip('_')
    return s   # may be "" when the filename has no model token before dayN
def _group_by_model(files):
    g={}
    for f in files: g.setdefault(_model_name(os.path.basename(f)),[]).append(f)
    return g
def discover_models(base):
    """{model_name: (files,...)}. Sub-folders => one model each, BUT a folder whose files span
    several models (e.g. merged NCUM_day*/GFS_day*) is split into 'folder/MODEL'. A flat base
    (no sub-folders) is grouped by model name directly."""
    subs=[d for d in os.listdir(base) if os.path.isdir(os.path.join(base,d)) and _has_fc(os.path.join(base,d))]
    if subs:
        out={}
        for d in subs:
            files=_fc_files(os.path.join(base,d)); g=_group_by_model(files)
            named=[k for k in g if k]                                            # non-empty model tokens
            if len(named)<=1: out[d]=tuple(files)                                # one model -> folder name
            else:
                for gn,gf in g.items(): out[f"{d}/{gn}" if gn else d]=tuple(gf)  # split a genuinely-mixed folder
        return out
    return {(k or os.path.basename(base.rstrip("/")) or "model"): tuple(v) for k,v in _group_by_model(_fc_files(base)).items()}

def _run_multimodel(st, sb, submitted, ensemble=False, single=False):
    """Multi-model comparison: each sub-folder / filename-prefix = a model (any nc/grib2, any grid).
    ensemble=True => files carry members; the reader auto-averages them so this compares ensemble MEANS."""
    import math
    import plotly.graph_objects as go, pandas as pd
    from plotly.subplots import make_subplots
    if ensemble: sb.caption("Comparing **ensemble means** (members auto-averaged). Base dir = folder of ensemble models, e.g. …/ensemble with NEPS/, GEFS/.")
    base=sb.text_input("Models base directory", DEFAULT_DIR,
                       help="Either a folder with one sub-folder per model (NCUM/, GFS/), OR a flat folder of files named <MODEL>_dayN…")
    if not os.path.isdir(base): st.info("Enter a folder with model sub-folders, or a flat folder of <MODEL>_dayN files."); return
    obs_path=sb.text_input("Observation file", DEFAULT_OBS)          # always visible
    _uc=sb.columns(2); UOPT={"Auto (from file)":None,"mm":1.0,"cm":10.0,"m":1000.0,"inch":25.4}
    ffac=UOPT[_uc[0].selectbox("Forecast units", list(UOPT), 0, help="Auto reads each file's units attribute and converts to mm; pick manually if the file has none (e.g. cm).")]
    ofac=UOPT[_uc[1].selectbox("Obs units", list(UOPT), 0)]
    DUOPT={"mm":1.0,"cm":10.0,"m":1000.0,"inch":25.4}
    disp_unit=sb.selectbox("Display units", list(DUOPT), 0,
        help="Show rainfall amounts and continuous scores (ME/MAE/RMSE/CRPS) in this unit. Verification is computed in mm; the threshold you type stays in mm.")
    dfac=1.0/DUOPT[disp_unit]; UL=disp_unit          # mm -> display factor + label
    oscale = ofac if ofac is not None else (file_units(obs_path) or 1.0)
    if ofac is None and os.path.exists(obs_path) and file_units(obs_path) is None:
        sb.warning("⚠ Observation file has no *units* attribute — assuming **mm**. If it isn't mm, set **Obs units** manually.")
    if not os.path.exists(obs_path): st.info("Set a valid observation file."); return
    ocat=catalog(obs_path); olon,olat=ocat["lon"],ocat["lat"]
    MODELMAP=discover_models(base)
    if not MODELMAP: st.info(f"No .nc/.grib2 forecasts found under {base}."); return
    topf=tuple(f for f in _fc_files(base) if lead_from(f) is not None)     # dayN files directly in base
    if topf and not any(v and os.path.dirname(v[0])==os.path.abspath(base).rstrip("/") for v in MODELMAP.values()):
        MODELMAP={"· (files in this folder)":topf, **MODELMAP}             # keep top-level set selectable alongside sub-folders
    subs=sorted(MODELMAP, key=lambda d:(d[:1].isdigit(), d.lower()))  # named models first, date folders last
    mode = ("Single" if single else "Multiple") if ensemble else sb.radio("Models", ["Single","Multiple"], 1 if len(subs)>1 else 0, horizontal=True)
    named=[s for s in subs if not s[:1].isdigit()]
    dflt=named[:4] if named else subs[:min(2,len(subs))]
    models=[sb.selectbox("Model", subs)] if mode=="Single" else sb.multiselect("Models to compare", subs, default=dflt)
    if not models: st.info("Select the model(s) to compare (e.g. NCUM, GFS)."); return
    if ffac is None:                                  # Auto forecast units — warn if a file has no units attribute
        _samp=next((MODELMAP[m][0] for m in models if MODELMAP.get(m)), None)
        if _samp and file_units(_samp) is None:
            sb.warning("⚠ Forecast files have no *units* attribute — assuming **mm**. If they aren't mm, set **Forecast units** manually.")
    prob_mode=False; diag2=False    # ensemble Mean/Probabilistic choice — right after model pick (same spot as Single)
    if ensemble:
        prob_mode = sb.radio("Ensemble verification", ["Mean","Probabilistic"], 0, horizontal=True,
                             help="Mean: verify the ensemble mean (all deterministic scores + FSS/CRA). Probabilistic: Brier/BSS/CRPS + reliability/ROC/REV/PIT.")=="Probabilistic"
    MOD={}; leads=set(); vdset=set()
    for m in models:
        d={}
        for e in scan_files(MODELMAP[m]):
            d.setdefault(e["lead"],{})[e["vdate"]]=(e["path"], e.get("tidx",0)); leads.add(e["lead"]); vdset.add(e["vdate"])
        MOD[m]=d
    leads=sorted(leads); vdates=sorted(vdset)
    if not leads or not vdates: st.info("No datable forecast files in the selected models."); return
    ldsel=sb.multiselect("Lead times", leads, default=leads)
    thr=sb.number_input("Rain threshold (mm)", value=0.1, min_value=0.0, step=0.1)
    matched_only=sb.checkbox("Matched samples only (same dates across all models + obs)", value=True,
                             help="Fair comparison: for each lead, score every model on exactly the dates all selected models AND obs share.")
    spatial_on = (not prob_mode) and sb.checkbox("Spatial diagnostics (FSS + CRA)", value=False,
                           help="FSS vs neighbourhood + CRA (displacement/volume/pattern). Ensemble-mean / deterministic only.")
    if prob_mode:
        diag2 = sb.checkbox("Detailed diagnostics (reliability / ROC / REV / PIT / spread)", value=True)
    boot_on=sb.checkbox("Bootstrap confidence intervals", value=False,
                        help="Resample dates with replacement to put a CI on each score (error bars / bands).")
    n_boot=sb.number_input("Bootstrap samples", 100, 10000, 1000, step=100) if boot_on else 0
    period=sb.radio("Verification period", ["Daily","Seasonal"], 1 if len(vdates)>1 else 0)
    if period=="Seasonal":
        dr=sb.select_slider("Analysis date range", options=vdates, value=(vdates[0],vdates[-1]))
        i0,i1=sorted((vdates.index(dr[0]),vdates.index(dr[1]))); vuse=vdates[i0:i1+1]
        sb.info(f"{len(vuse)} valid dates ({dr[0]} … {dr[1]})")
    else:
        vuse=[sb.selectbox("Valid date", vdates, index=len(vdates)//2)]
    coast_on=sb.checkbox("Show coastlines / borders", value=True)
    d0=(float(np.floor(olon.min())),float(np.ceil(olon.max())),float(np.floor(olat.min())),float(np.ceil(olat.max())))
    for k,v in dict(bx0=d0[0],bx1=d0[1],by0=d0[2],by1=d0[3]).items(): st.session_state.setdefault(k,v)
    ev=st.session_state.get("maps")
    if ev and ev.get("selection",{}).get("box"):
        bx=ev["selection"]["box"][0]; xs=sorted(bx["x"]); ys=sorted(bx["y"])
        st.session_state.bx0,st.session_state.bx1=round(xs[0],2),round(xs[1],2); st.session_state.by0,st.session_state.by1=round(ys[0],2),round(ys[1],2)
    sb.header("Selection box (draw on obs map or type)")
    c1,c2=sb.columns(2); lon_min=c1.number_input("lon min",key="bx0"); lon_max=c2.number_input("lon max",key="bx1")
    lat_min=c1.number_input("lat min",key="by0"); lat_max=c2.number_input("lat max",key="by1")
    bi=(olon>=lon_min)&(olon<=lon_max); bj=(olat>=lat_min)&(olat<=lat_max)
    if submitted:
        Osl={}
        for vd in vuse:
            o=read_slice(obs_path, np.datetime64(vd))
            if o is not None: Osl[vd]=o*oscale
        vuse2=[v for v in vuse if v in Osl]
        if not vuse2:
            osp=(str(np.datetime64(ocat["times"].min(),"D")),str(np.datetime64(ocat["times"].max(),"D")))
            st.error(f"No observation for the selected forecast date(s) **{vuse[0]} … {vuse[-1]}**. "
                     f"The observation file **{os.path.basename(obs_path)}** only covers **{osp[0]} … {osp[1]}** — "
                     f"pick an obs file that overlaps the forecast years."); return
        Odisp=Osl[vuse2[0]] if len(vuse2)==1 else np.nanmean(np.stack([Osl[v] for v in vuse2],0),0)
        bb=np.zeros(Odisp.shape,bool); bb[np.ix_(bj,bi)]=True
        # matched valid dates per lead: intersection across selected models (∩ obs-present range)
        vset=set(vuse2); match_by_lead={}
        for L in ldsel:
            common=set.intersection(*[set(MOD[m].get(L,{}).keys()) for m in models]) if models else set()
            match_by_lead[L]=sorted(common & vset)
        nmatch={L:len(match_by_lead[L]) for L in ldsel}
        obs_series=[]
        for vd in vuse2:
            mo=bb & np.isfinite(Osl[vd]); obs_series.append(float(np.nanmean(Osl[vd][mo])) if mo.any() else np.nan)
        rows=[]; DISP2={m:{} for m in models}; SER={m:{} for m in models}; QSAMP={m:{} for m in models}; SCMAP={m:{} for m in models}
        FSSD={m:{} for m in models}; CRAD={m:{} for m in models}; PERDATE={m:{} for m in models}
        PROBD={m:{} for m in models}; PMAP={m:{} for m in models}
        with st.spinner(f"Reading {len(models)} model(s) × {len(ldsel)} lead(s) × {len(vuse2)} date(s)…"):
            for m in models:
                for L in ldsel:
                    mset=set(match_by_lead[L]) if matched_only else set(vuse2)
                    A=B=C=D=0; facc=None; nf=0; ser=[np.nan]*len(vuse2)
                    n=sF=sO=sF2=sO2=sFO=sae=sse=0.0                 # box continuous-metric accumulators
                    qf=[]; qo=[]; QCAP=6000; kk=max(1,QCAP//max(1,len(vuse2))); rng=np.random.default_rng(0)
                    Z=lambda: np.zeros(Odisp.shape)                 # per-cell (map) accumulators
                    cn=Z();cF=Z();cO=Z();cF2=Z();cO2=Z();cFO=Z();cae=Z();cse=Z();ca=Z();cb=Z();cc=Z();cd=Z()
                    FA={ns:[0.0,0.0] for ns in FSS_NS} if spatial_on else None; CRc={} if spatial_on else None
                    PD=[] if boot_on else None                      # per-date stats for bootstrap
                    PPr=[];POb=[];PEn=[];PYv=[];pdB=[];pdC=[];pdCl=[]   # prob pooled + per-date (CI)
                    pcn=Z();pBSc=Z();pObc=Z();pCRc=Z()                  # per-cell prob maps
                    for ix,vd in enumerate(vuse2):
                        pt=MOD[m].get(L,{}).get(vd)
                        if not pt: continue
                        ensg=None; fac=(ffac if ffac is not None else (file_units(pt[0]) or 1.0))
                        if prob_mode:
                            try: me=fc_members(pt[0],pt[1])
                            except Exception: me=None
                            if me is not None:
                                ensg=np.stack([regrid(me["lon"],me["lat"],me["ens"][mk],olon,olat) for mk in range(len(me["ens"]))],0)*fac
                                Fr=ensg.mean(0)
                        if ensg is None:
                            try: fl=fc_read(pt[0], pt[1])
                            except Exception: continue
                            Fr=regrid(fl["lon"],fl["lat"],fl["field"],olon,olat)*fac
                        Odt=Osl[vd]; mdt=bb & np.isfinite(Odt) & np.isfinite(Fr)
                        facc=Fr if facc is None else facc+Fr; nf+=1
                        if mdt.any(): ser[ix]=float(np.nanmean(Fr[mdt]))
                        if not (vd in mset and mdt.any()): continue
                        if prob_mode and ensg is not None:
                            prob=(ensg>=thr).mean(0); obinf=(Odt>=thr).astype(float)
                            pb=prob[mdt]; ob=obinf[mdt]; eb=ensg[:,mdt]; yb=Odt[mdt]
                            PPr.append(pb); POb.append(ob); PEn.append(eb); PYv.append(yb)
                            pdB.append(float(np.mean((pb-ob)**2))); pdC.append(crps_points(eb,yb)); pdCl.append(float(ob.mean()))
                            vf=np.isfinite(Odt)&np.isfinite(prob); pcn+=vf
                            pBSc+=np.where(vf,(prob-obinf)**2,0.0); pObc+=np.where(vf,obinf,0.0); pCRc+=np.where(vf,crps_grid(ensg,Odt),0.0)
                        else:
                            Fb=Fr[mdt]; Ob=Odt[mdt]
                            a,b,c,d=counts(Fb,Ob,thr); A+=a;B+=b;C+=c;D+=d
                            k=len(Fb); n+=k; dsF=Fb.sum(); dsO=Ob.sum(); dsF2=(Fb*Fb).sum(); dsO2=(Ob*Ob).sum()
                            dsFO=(Fb*Ob).sum(); dsae=np.abs(Fb-Ob).sum(); dsse=((Fb-Ob)**2).sum()
                            sF+=dsF; sO+=dsO; sF2+=dsF2; sO2+=dsO2; sFO+=dsFO; sae+=dsae; sse+=dsse
                            if boot_on: PD.append((a,b,c,d,k,dsF,dsO,dsF2,dsO2,dsFO,dsae,dsse))
                            if k>kk: j=rng.choice(k,kk,replace=False); qf.append(Fb[j]); qo.append(Ob[j])
                            else: qf.append(Fb); qo.append(Ob)
                            vf=np.isfinite(Fr)&np.isfinite(Odt); FF=np.where(vf,Fr,0.0); OO=np.where(vf,Odt,0.0)
                            cn+=vf; cF+=FF; cO+=OO; cF2+=FF*FF; cO2+=OO*OO; cFO+=FF*OO
                            de=np.where(vf,Fr-Odt,0.0); cae+=np.abs(de); cse+=de*de
                            fp=vf&(Fr>=thr); op=vf&(Odt>=thr)
                            ca+=fp&op; cb+=fp&~op&vf; cc+=~fp&op&vf; cd+=vf&~fp&~op
                            if spatial_on:
                                Fbx=Fr[np.ix_(bj,bi)]; Obx=Odt[np.ix_(bj,bi)]
                                for nsz,(nu,de) in fss_accum(Fbx>=thr,Obx>=thr,FSS_NS).items(): FA[nsz][0]+=nu; FA[nsz][1]+=de
                                cr=cra_decomp(Fbx,Obx,thr=thr)
                                for kk_,vv_ in cr.items(): CRc[kk_]=CRc.get(kk_,0.0)+vv_
                                CRc["_n"]=CRc.get("_n",0)+1
                    if prob_mode and PPr:
                        PROBD[m][L]=dict(prob=np.concatenate(PPr),obin=np.concatenate(POb),
                                         ens=np.concatenate(PEn,axis=1),y=np.concatenate(PYv),pdB=pdB,pdC=pdC,pdCl=pdCl)
                        if pcn.max()>0:
                            with np.errstate(divide="ignore",invalid="ignore"):
                                BSm=pBSc/pcn; clm=pObc/pcn; BSSm=1-BSm/(clm*(1-clm)); CRm=pCRc/pcn
                            bad=pcn<3; PMAP[m][L]={"BS":np.where(bad,np.nan,BSm),"BSS":np.where(bad,np.nan,BSSm),"CRPS":np.where(bad,np.nan,CRm)}
                    if nf: DISP2[m][L]=facc/nf
                    SER[m][L]=ser
                    if qf: QSAMP[m][L]=(np.concatenate(qf), np.concatenate(qo))
                    if cn.max()>0: SCMAP[m][L]=cell_maps((cn,cF,cO,cF2,cO2,cFO,cae,cse,ca,cb,cc,cd))
                    if spatial_on and CRc.get("_n"):
                        nnn=CRc.pop("_n")
                        FSSD[m][L]={ns:(1-nu/de if de>0 else np.nan) for ns,(nu,de) in FA.items()}
                        CRAD[m][L]={k:v/nnn for k,v in CRc.items()}
                    if boot_on and PD: PERDATE[m][L]=np.array(PD,dtype=float)
                    if prob_mode and (m in PROBD) and (L in PROBD[m]):
                        pr=PROBD[m][L]; P=pr["prob"]; ob=pr["obin"]
                        bs=float(np.mean((P-ob)**2)); clim=float(np.mean(ob))
                        bss=1-bs/(clim*(1-clim)) if 0<clim<1 else np.nan
                        rows.append(dict(model=m,lead=L,Brier=bs,BSS=bss,CRPS=crps_points(pr["ens"],pr["y"]),clim=clim))
                    elif not prob_mode and A+B+C+D>0:
                        sc=scores_from_counts(A,B,C,D)
                        if n>0:                                     # continuous metrics
                            vF=sF2/n-(sF/n)**2; vO=sO2/n-(sO/n)**2; cov=sFO/n-(sF/n)*(sO/n)
                            sc["ME"]=(sF-sO)/n; sc["MAE"]=sae/n; sc["RMSE"]=float(np.sqrt(sse/n))
                            sc["CORR"]=float(cov/np.sqrt(vF*vO)) if vF>0 and vO>0 else np.nan
                            sc["SDF"]=float(np.sqrt(vF)); sc["SDO"]=float(np.sqrt(vO))   # for Taylor later
                        sc["model"]=m; sc["lead"]=L; rows.append(sc)
        st.session_state["mm"]=dict(models=models,rows=rows,Odisp=Odisp,olon=olon,olat=olat,
            vuse=vuse2,abbr=[v[5:] for v in vuse2],period=period,thr=thr,
            box=(lon_min,lon_max,lat_min,lat_max),coast_on=coast_on,matched=matched_only,nmatch=nmatch,
            fspan=(str(vdates[0]),str(vdates[-1])),
            ospan=(str(np.datetime64(ocat["times"].min(),"D")),str(np.datetime64(ocat["times"].max(),"D"))),
            leads=sorted(ldsel),vmax=float(np.nanpercentile(Odisp,98) or 50) or 50,
            DISP2=DISP2,SER=SER,obs_series=obs_series,QSAMP=QSAMP,SCMAP=SCMAP,FSSD=FSSD,CRAD=CRAD,
            PERDATE=PERDATE,n_boot=int(n_boot),PROBD=PROBD,PMAP=PMAP,prob_mode=prob_mode,diag2=diag2)
        st.session_state.setdefault("_sid", uuid.uuid4().hex[:12])
        audit(dict(session=st.session_state["_sid"], mode="multimodel", models=models, threshold=thr,
                   period=period, box=[lon_min,lon_max,lat_min,lat_max], n_dates=len(vuse2), obs=os.path.basename(obs_path)))
    mm=st.session_state.get("mm")
    if not mm: st.info("Set options in the sidebar, then press ▶ **Run verification**."); return
    US={"ME","MAE","RMSE","CRPS"}                 # unit-bearing scores -> scaled to the display unit
    olon_r=mm["olon"]; olat_r=mm["olat"]; Odisp=mm["Odisp"]*dfac
    # box rectangle follows the LIVE sidebar/drawn box (lon_min.. from inputs above) so a fresh
    # draw shows immediately; scores/series below reflect the last Run's box until you press Run again.
    vmax=float(np.nanpercentile(Odisp,98) or 50) or 50
    cxs,cys=coastlines(float(olon_r.min()),float(olon_r.max()),float(olat_r.min()),float(olat_r.max())) if mm["coast_on"] else ([],[])
    lbl=("mean of %d dates"%len(mm["vuse"])) if mm["period"]=="Seasonal" else mm["vuse"][0]
    of=go.Figure(go.Heatmap(z=Odisp,x=olon_r,y=olat_r,colorscale="Blues",zmin=0,zmax=vmax,zsmooth="best",colorbar=dict(title=UL)))
    if cxs: of.add_trace(go.Scatter(x=cxs,y=cys,mode="lines",line=dict(color="black",width=0.8),showlegend=False,hoverinfo="skip"))
    of.add_shape(type="rect",x0=lon_min,x1=lon_max,y0=lat_min,y1=lat_max,line=dict(color="red",width=2))
    of.update_yaxes(scaleanchor="x"); of.update_layout(title=f"Observed rainfall — {lbl}",height=460,margin=dict(l=0,r=0,t=34,b=0),dragmode="select")
    series_ok=(mm["period"]=="Seasonal" and len(mm["vuse"])>1)
    def _ts_fig(m,h):
        LPAL=["#0072B2","#E69F00","#009E73","#CC79A7","#D55E00","#56B4E9","#999999"]
        xd=mm["vuse"]   # full ISO valid dates -> correct year on axis
        ts=go.Figure()
        ts.add_trace(go.Scatter(x=xd,y=[(v*dfac if v==v else v) for v in mm["obs_series"]],mode="lines+markers",name="Observed",line=dict(color="black",width=3),marker=dict(size=4)))
        for k,L in enumerate(mm["leads"]):
            s=mm["SER"].get(m,{}).get(L)
            if s is not None:
                ts.add_trace(go.Scatter(x=xd,y=[(v*dfac if v==v else v) for v in s],mode="lines+markers",name=f"L{L}",line=dict(color=LPAL[k%len(LPAL)],width=1.5),marker=dict(size=3)))
        ts.update_layout(title=f"{m}: box-mean vs valid date",height=h,margin=dict(l=0,r=0,t=26,b=0),
                         yaxis_title=UL,xaxis=dict(type="category",tickangle=-45,nticks=15),
                         legend=dict(font=dict(size=8),orientation="h",y=-0.2))
        return ts
    if series_ok:
        cL,cR=st.columns([3,2])
        with cL:
            st.caption("Draw box on the observed map (press **Run** to apply).")
            st.plotly_chart(of,use_container_width=True,on_select="rerun",selection_mode="box",key="maps")
        with cR:
            h=max(200,int(460/len(mm["models"])))
            for m in mm["models"]: st.plotly_chart(_ts_fig(m,h),use_container_width=True,key=f"ts_{m}")
    else:
        st.caption("Draw box on the observed map (press **Run** to apply).")
        st.plotly_chart(of,use_container_width=True,on_select="rerun",selection_mode="box",key="maps")
    df=pd.DataFrame(mm["rows"])
    if df.empty:
        fs=mm.get("fspan"); osp=mm.get("ospan"); msg="No matched forecast/obs for the selected date(s)/box."
        if fs and osp:
            msg+=f"  Forecast dates span **{fs[0]} … {fs[1]}**; the observation file covers **{osp[0]} … {osp[1]}**."
            if fs[1]<osp[0] or fs[0]>osp[1]: msg+="  ➜ These periods **don't overlap** — choose an observation file for the same years as the forecasts."
            else: msg+="  If using *Matched samples only* with several models, they may share no common date on the picked day — untick it or pick a Seasonal range."
        st.warning(msg); return
    # ---- forecast spatial maps: rows=models, cols=chosen leads (smooth, regridded, box) ----
    st.subheader("Forecast spatial maps")
    with st.container(border=True):
        mapL=st.multiselect("Leads to map", mm["leads"], default=mm["leads"][:min(3,len(mm["leads"]))],
                            help="Choose which lead times to display as maps.")
    if mapL:
        nrow=len(mm["models"]); ncol=len(mapL)
        figm=make_subplots(rows=nrow,cols=ncol,horizontal_spacing=0.03,vertical_spacing=0.10,
                           subplot_titles=[f"{m} · L{L}" for m in mm["models"] for L in mapL])
        for ri,m in enumerate(mm["models"]):
            for ci,L in enumerate(mapL):
                z=mm["DISP2"].get(m,{}).get(L)
                if z is None: continue
                figm.add_trace(go.Heatmap(z=z*dfac,x=olon_r,y=olat_r,colorscale="Blues",zmin=0,zmax=vmax,zsmooth="best",
                               showscale=(ri==0 and ci==0),colorbar=dict(title=UL,len=0.9)),row=ri+1,col=ci+1)
                if cxs: figm.add_trace(go.Scatter(x=cxs,y=cys,mode="lines",line=dict(color="black",width=0.7),
                                       showlegend=False,hoverinfo="skip"),row=ri+1,col=ci+1)
                figm.add_shape(type="rect",x0=lon_min,x1=lon_max,y0=lat_min,y1=lat_max,line=dict(color="red",width=1.6),row=ri+1,col=ci+1)
        figm.update_xaxes(matches="x"); figm.update_yaxes(matches="y")
        figm.update_layout(height=250*nrow,margin=dict(l=0,r=0,t=28,b=0))
        st.plotly_chart(figm,use_container_width=True,key="fmaps")
    # ---- verification (scores) ----
    mtxt = ("matched samples: "+", ".join(f"L{L}={n}" for L,n in mm.get("nmatch",{}).items())) if mm.get("matched") else "each model on its own available dates"
    st.subheader(f"Verification — scores  @ {mm['thr']} mm  ·  {mm['period']}  ·  box[{lon_min},{lon_max},{lat_min},{lat_max}]")
    st.caption(mtxt)
    pmode=mm.get("prob_mode",False)
    if pmode:
        METS=[x for x in ["Brier","BSS","CRPS"] if x in df.columns]
    else:
        CAT=["POD","FAR","CSI","BIAS","ETS","HSS","PSS","ACC","EDI","SEDI","EDS","SEDS","YuleQ"]; CON=["ME","MAE","RMSE","CORR"]
        METS=[x for x in CAT+CON if x in df.columns]
    dfx=df.copy()                                  # display copy: unit-bearing scores scaled to the display unit
    for c in US:
        if c in dfx.columns: dfx[c]=dfx[c]*dfac
    hdr={x:(f"{x} ({UL})" if x in US else x) for x in METS}
    st.dataframe(dfx[["model","lead"]+METS].rename(columns=hdr).sort_values(["model","lead"]).style.format({hdr[x]:"{:.3f}" for x in METS}),use_container_width=True)
    _dl_table(st, dfx[["model","lead"]+METS].rename(columns=hdr), "multimodel_scores")
    _unitnote=(f" · amounts/continuous scores shown in **{UL}**" if UL!="mm" else "")
    st.caption(("Probabilistic: Brier / BSS / CRPS." if pmode else f"Threshold @ {mm['thr']} mm: POD/FAR/CSI/BIAS/ETS/HSS/PSS/ACC/EDI/SEDI/EDS/SEDS/YuleQ · Continuous: ME/MAE/RMSE/CORR")+_unitnote)
    with st.container(border=True):
        if pmode:
            pick=st.multiselect("Scores to plot (x = lead time)",METS,default=METS)
        else:
            # split into Continuous vs Categorical, each Basic (default) + Advanced (opt-in)
            CON =[x for x in ["ME","MAE","RMSE","CORR"] if x in df.columns]     # continuous (all basic)
            CATB=[x for x in ["POD","FAR","CSI","BIAS","ETS","HSS"] if x in df.columns]        # categorical — basic
            CATA=[x for x in ["PSS","ACC","EDI","SEDI","EDS","SEDS","YuleQ"] if x in df.columns] # categorical — advanced
            bc=st.columns([3,3,2])
            con_pick=bc[0].multiselect("Continuous scores (mm)",CON,
                                     default=[x for x in ["RMSE","MAE","CORR"] if x in CON],key="pick_con",
                                     help="Basic error/agreement metrics: ME, MAE, RMSE, CORR.")
            adv=bc[2].checkbox("Show advanced",value=False,key="pick_cat_adv",
                             help="Adds skill/extremal categorical scores: PSS, ACC, EDI, SEDI, EDS, SEDS, Yule's Q.")
            cat_pick=bc[1].multiselect("Categorical scores (@ threshold)",CATB+(CATA if adv else []),
                                     default=[x for x in ["ETS","HSS"] if x in CATB],key="pick_cat",
                                     help="Basic: POD, FAR, CSI, BIAS, ETS, HSS. Tick 'Show advanced' for skill/extremal scores.")
            pick=con_pick+cat_pick
    PER=mm.get("PERDATE",{}); NB=mm.get("n_boot",0); PROBD=mm.get("PROBD",{})
    def _eb(m,leads,scn):                                   # bootstrap error bars for (model, leads, score)
        if not NB: return None
        if pmode:
            ci=[prob_boot_ci(PROBD.get(m,{}).get(int(L),{}),scn,NB) for L in leads]
        else:
            if not PER.get(m): return None
            ci=[boot_ci(PER[m].get(int(L)),scn,NB) for L in leads]
        return ci if any(np.isfinite(lo) for lo,hi in ci) else None
    if pick:
        PAL=["#000000","#0072B2","#E69F00","#CC79A7","#009E73","#D55E00","#56B4E9","#F0E442"]
        if len(mm["models"])==1:
            m=mm["models"][0]; d2=dfx[dfx["model"]==m].sort_values("lead"); Ls=d2["lead"].tolist()
            fig=go.Figure()
            for k,scn in enumerate(pick):
                y=d2[scn].tolist(); ci=_eb(m,Ls,scn)
                if ci and scn in US: ci=[(l*dfac,h*dfac) for (l,h) in ci]
                ey=dict(type="data",symmetric=False,array=[(h-v) for (l,h),v in zip(ci,y)],arrayminus=[(v-l) for (l,h),v in zip(ci,y)]) if ci else None
                fig.add_trace(go.Scatter(x=Ls,y=y,mode="lines+markers",name=scn,error_y=ey,
                              line=dict(color=PAL[k%len(PAL)],width=2),marker=dict(size=6)))
            fig.update_xaxes(title_text="Lead time (days)",tickmode="linear",dtick=1)
            fig.update_layout(title=f"{m} — scores vs lead"+(" (95% CI)" if NB else ""),yaxis_title="Score",height=430,
                              margin=dict(t=34),legend=dict(orientation="h",y=-0.15))
            st.plotly_chart(fig,use_container_width=True); _export_fig(st, fig, "scores_vs_lead")
        else:
            ncol=2; nrow=math.ceil(len(pick)/ncol)
            fig=make_subplots(rows=nrow,cols=ncol,subplot_titles=pick,vertical_spacing=0.16,horizontal_spacing=0.10)
            for i,scn in enumerate(pick):
                r=i//ncol+1; cc=i%ncol+1
                for j,m in enumerate(mm["models"]):
                    d2=dfx[dfx["model"]==m].sort_values("lead"); Ls=d2["lead"].tolist(); y=d2[scn].tolist(); ci=_eb(m,Ls,scn)
                    if ci and scn in US: ci=[(l*dfac,h*dfac) for (l,h) in ci]
                    ey=dict(type="data",symmetric=False,array=[(h-v) for (l,h),v in zip(ci,y)],arrayminus=[(v-l) for (l,h),v in zip(ci,y)]) if ci else None
                    fig.add_trace(go.Scatter(x=Ls,y=y,mode="lines+markers",name=m,legendgroup=m,error_y=ey,
                        showlegend=(i==0),line=dict(color=PAL[j%len(PAL)],width=2),marker=dict(size=6)),row=r,col=cc)
                fig.update_xaxes(title_text="Lead time (days)",tickmode="linear",dtick=1,row=r,col=cc)
            fig.update_layout(height=280*nrow,margin=dict(t=34),legend=dict(orientation="h",y=-0.08))
            st.plotly_chart(fig,use_container_width=True); _export_fig(st, fig, "scores_vs_lead")
        if NB: st.caption(f"Error bars = 95% CI from {NB} bootstrap resamples of the dates.")
    # ---- Taylor diagram + Q–Q plot (special plots) ----
    if {"CORR","SDF","SDO"} <= set(df.columns):
        st.subheader("Special plots")
        cT,cQ=st.columns(2)
        PAL=["#000000","#0072B2","#E69F00","#CC79A7","#009E73","#D55E00","#56B4E9","#F0E442"]
        with cT:
            # Taylor: radius = normalised std (SDF/SDO), angle = arccos(CORR); obs reference at (1,0)
            ft=go.Figure()
            ft.add_trace(go.Scatterpolar(r=[1],theta=[0],mode="markers",marker=dict(size=10,symbol="star",color="black"),name="Observed"))
            for j,m in enumerate(mm["models"]):
                d2=df[df["model"]==m].sort_values("lead"); sdo=d2["SDO"].replace(0,np.nan)
                r=(d2["SDF"]/sdo).clip(0,3); th=np.degrees(np.arccos(d2["CORR"].clip(-1,1)))
                ft.add_trace(go.Scatterpolar(r=r,theta=th,mode="markers+text",text=[f"L{int(x)}" for x in d2["lead"]],
                             textposition="top center",marker=dict(size=8,color=PAL[j%len(PAL)]),name=m))
            ft.update_layout(title="Taylor diagram (angle=corr, radius=σ_f/σ_o)",height=430,
                             polar=dict(angularaxis=dict(direction="counterclockwise",rotation=0,thetaunit="degrees"),
                                        radialaxis=dict(range=[0,2.2],title="σ_f / σ_o")),margin=dict(t=40))
            st.plotly_chart(ft,use_container_width=True); _export_fig(st, ft, "taylor")
        with cQ:
            # Q–Q: forecast vs obs quantiles from the pooled box samples
            QS=mm.get("QSAMP",{}); pr=np.linspace(0.01,0.99,49); fq=go.Figure(); mx=1.0
            for j,m in enumerate(mm["models"]):
                Lsel=sorted(QS.get(m,{}));
                if not Lsel: continue
                L0=Lsel[0]; F,O=QS[m][L0]
                qF=np.quantile(F,pr)*dfac; qO=np.quantile(O,pr)*dfac; mx=max(mx,float(qF.max()),float(qO.max()))
                fq.add_trace(go.Scatter(x=qO,y=qF,mode="lines+markers",name=f"{m} L{L0}",line=dict(color=PAL[j%len(PAL)]),marker=dict(size=4)))
            fq.add_trace(go.Scatter(x=[0,mx],y=[0,mx],mode="lines",line=dict(color="grey",dash="dot"),name="1:1"))
            fq.update_layout(title="Q–Q plot (forecast vs observed quantiles, lead 1)",xaxis_title=f"Observed ({UL})",
                             yaxis_title=f"Forecast ({UL})",height=430,margin=dict(t=40),legend=dict(font=dict(size=9)))
            st.plotly_chart(fq,use_container_width=True); _export_fig(st, fq, "qq")
    # ---- score maps (per grid cell): continuous/categorical (mean) OR BS/BSS/CRPS (probabilistic) ----
    SCM=mm.get("PMAP",{}) if pmode else mm.get("SCMAP",{})
    if any(SCM.get(m) for m in mm["models"]):
        st.subheader("Score maps (per grid cell)")
        with st.container(border=True):
            if pmode:
                bm=st.columns([2,3]); scsel=bm[0].selectbox("Score to map",["CRPS","BS","BSS"],index=0,key="scmap_sel")
                mapL2=bm[1].multiselect("Leads",mm["leads"],default=mm["leads"][:min(3,len(mm["leads"]))],key="scmap_leads")
            else:
                bm=st.columns([2,2,3])
                styp=bm[0].radio("Score type",["Continuous","Categorical"],0,key="scmap_type")
                madv=bm[0].checkbox("Show advanced",value=False,key="scmap_adv",
                                    help="Adds PSS, ACC, EDI, SEDI, EDS, SEDS, Yule's Q.") if styp=="Categorical" else False
                mopts=["RMSE","MAE","ME","CORR"] if styp=="Continuous" else \
                      ["POD","FAR","CSI","BIAS","ETS","HSS"]+(["PSS","ACC","EDI","SEDI","EDS","SEDS","YuleQ"] if madv else [])
                scsel=bm[1].selectbox(f"{styp} score",mopts,index=0,key="scmap_sel")
                mapL2=bm[2].multiselect("Leads",mm["leads"],default=mm["leads"][:min(3,len(mm["leads"]))],key="scmap_leads")
        DIVERGE={"ME","CORR","PSS","EDI","SEDI","EDS","SEDS","YuleQ","HSS","ETS","BSS"}; cs="RdBu" if scsel in DIVERGE else "Viridis"
        msf=dfac if scsel in US else 1.0                 # scale unit-bearing score maps (RMSE/MAE/ME/CRPS) to display unit
        mtitle=f"{scsel} ({UL})" if scsel in US else scsel
        if mapL2:
            vals=[SCM.get(m,{}).get(L,{}).get(scsel) for m in mm["models"] for L in mapL2]
            fin=[v[np.isfinite(v)] for v in vals if v is not None]; fin=(np.concatenate(fin) if fin else np.array([0.0,1.0]))*msf
            if scsel in DIVERGE: a=float(np.nanpercentile(np.abs(fin),98) or 1) or 1; zmin,zmax=-a,a
            else: zmin=float(np.nanpercentile(fin,2)); zmax=float(np.nanpercentile(fin,98)) or 1
            nrow=len(mm["models"]); ncol=len(mapL2)
            figs=make_subplots(rows=nrow,cols=ncol,horizontal_spacing=0.03,vertical_spacing=0.10,
                 subplot_titles=[f"{m} · L{L}" for m in mm["models"] for L in mapL2])
            for ri,m in enumerate(mm["models"]):
                for ci,L in enumerate(mapL2):
                    z=SCM.get(m,{}).get(L,{}).get(scsel)
                    if z is None: continue
                    figs.add_trace(go.Heatmap(z=z*msf,x=olon_r,y=olat_r,colorscale=cs,zmin=zmin,zmax=zmax,
                        showscale=(ri==0 and ci==0),colorbar=dict(title=mtitle,len=0.9)),row=ri+1,col=ci+1)
                    if cxs: figs.add_trace(go.Scatter(x=cxs,y=cys,mode="lines",line=dict(color="black",width=0.6),showlegend=False,hoverinfo="skip"),row=ri+1,col=ci+1)
                    figs.add_shape(type="rect",x0=lon_min,x1=lon_max,y0=lat_min,y1=lat_max,line=dict(color="red",width=1.2),row=ri+1,col=ci+1)
            figs.update_xaxes(matches="x"); figs.update_yaxes(matches="y")
            figs.update_layout(height=250*nrow,margin=dict(l=0,r=0,t=28,b=0))
            st.caption(f"{mtitle} per grid cell, over the selected dates (box shown for reference; maps are full-domain).")
            st.plotly_chart(figs,use_container_width=True,key="scoremaps"); _export_fig(st,figs,f"scoremap_{scsel}")
    # ---- spatial diagnostics: FSS + CRA (box, mean forecast) ----
    FS=mm.get("FSSD",{}); CR=mm.get("CRAD",{})
    if any(FS.get(m) for m in mm["models"]):
        st.subheader(f"Spatial diagnostics — FSS + CRA  @ {mm['thr']} mm")
        PAL=["#000000","#0072B2","#E69F00","#CC79A7","#009E73","#D55E00","#56B4E9","#F0E442"]
        cF,cC=st.columns(2)
        Lpick=cF.selectbox("Lead", mm["leads"], 0, key="fss_lead")
        # FSS vs neighbourhood
        ff=go.Figure()
        for j,m in enumerate(mm["models"]):
            d=FS.get(m,{}).get(Lpick)
            if not d: continue
            xs=sorted(d); ff.add_trace(go.Scatter(x=[x*0.25 for x in xs],y=[d[x] for x in xs],mode="lines+markers",name=m,line=dict(color=PAL[j%len(PAL)])))
        ff.update_layout(title=f"FSS vs neighbourhood (lead {Lpick})",xaxis_title="Neighbourhood width (°)",yaxis_title="FSS",height=380,yaxis_range=[0,1],margin=dict(t=34))
        cF.plotly_chart(ff,use_container_width=True); _export_fig(st,ff,"fss")
        # CRA decomposition (stacked) for the chosen lead
        comp=["displacement","volume","pattern"]; fc=go.Figure()
        for k,part in enumerate(comp):
            fc.add_trace(go.Bar(x=mm["models"],y=[ (CR.get(m,{}).get(Lpick,{}) or {}).get(part,np.nan) for m in mm["models"]],name=part))
        fc.update_layout(title=f"CRA MSE decomposition (lead {Lpick})",barmode="stack",yaxis_title="MSE (mm²)",height=380,margin=dict(t=34))
        cC.plotly_chart(fc,use_container_width=True); _export_fig(st,fc,"cra")
        # CRA stats table (usual format) — all models × leads
        crows=[]
        for m in mm["models"]:
            for L in mm["leads"]:
                s=CR.get(m,{}).get(L)
                if not s: continue
                tot=s.get("total",np.nan) or np.nan
                crows.append(dict(model=m,lead=L,RMSE=s.get("RMSE"),Corr=s.get("CORR"),Corr_shift=s.get("CORR_shift"),
                    maxF=s.get("maxF"),maxO=s.get("maxO"),meanF=s.get("meanF"),meanO=s.get("meanO"),
                    dx=s.get("dx"),dy=s.get("dy"),
                    disp_pct=100*s.get("displacement",0)/tot if tot else np.nan,
                    vol_pct=100*s.get("volume",0)/tot if tot else np.nan,
                    patt_pct=100*s.get("pattern",0)/tot if tot else np.nan))
        if crows:
            cdf=pd.DataFrame(crows)
            st.markdown("**CRA statistics** (per model × lead)")
            st.dataframe(cdf.style.format({c:"{:.2f}" for c in cdf.columns if c not in ("model","lead")}),use_container_width=True)
            _dl_table(st, cdf, "cra_stats")
        st.caption("FSS (Roberts & Lean): fractional exceedance in growing neighbourhoods; 1=perfect. CRA (Ebert–McBride): optimal shift (dx,dy) + MSE split — displacement (position) / volume (bias) / pattern (structure); Corr before & after the shift; maxF/maxO = peak rain.")
    # ---- probabilistic diagnostics: reliability / ROC / REV / PIT / spread–skill (overlaid per model) ----
    PRB=mm.get("PROBD",{})
    if pmode and mm.get("diag2") and any(PRB.get(m) for m in mm["models"]):
        st.subheader("Probabilistic diagnostics")
        Lp=st.selectbox("Lead", mm["leads"], 0, key="prob_diag_lead")
        PAL=["#000000","#0072B2","#E69F00","#CC79A7","#009E73","#D55E00","#56B4E9","#F0E442"]
        rs=np.linspace(0.01,0.99,99); edges=np.linspace(0,1,11); Fgrid=np.linspace(0,1,41)
        fR=go.Figure(); fO=go.Figure(); fV=go.Figure(); fP=go.Figure(); fS=go.Figure(); mxs=0.0
        fR.add_trace(go.Scatter(x=[0,1],y=[0,1],mode="lines",line=dict(color="grey",dash="dot"),showlegend=False))
        fO.add_trace(go.Scatter(x=[0,1],y=[0,1],mode="lines",line=dict(color="grey",dash="dot"),showlegend=False))
        for j,m in enumerate(mm["models"]):
            pr=PRB.get(m,{}).get(int(Lp))
            if not pr: continue
            prob=pr["prob"]; obin=pr["obin"]; ens=pr["ens"]; y=pr["y"]; col=PAL[j%len(PAL)]
            mp,of,_=reliability_curve(prob,obin); fR.add_trace(go.Scatter(x=mp,y=of,mode="lines+markers",name=m,line=dict(color=col)))
            F,H,auc=roc_curve(prob,obin); fO.add_trace(go.Scatter(x=F,y=H,mode="lines",name=f"{m} AUC={auc:.3f}",line=dict(color=col)))
            V=rev_curve(prob,obin,rs); fV.add_trace(go.Scatter(x=rs,y=V,mode="lines",name=m,line=dict(color=col)))
            pit=pit_values(ens,y); h,_=np.histogram(pit,bins=edges); h=h/h.sum(); fP.add_trace(go.Bar(x=edges[:-1]+0.05,y=h,name=m,marker_color=col))
            xs,ys,ms,mr=spread_skill(ens,y); xs=xs*dfac; ys=ys*dfac; fS.add_trace(go.Scatter(x=xs,y=ys,mode="lines+markers",name=f"{m}",line=dict(color=col)))
            mxs=max(mxs,float(np.nanmax(xs) if xs.size else 0),float(np.nanmax(ys) if ys.size else 0))
            if NB:   # CI bands via point bootstrap (reliability + ROC)
                rng=np.random.default_rng(0); nb=min(int(NB),300); N=len(prob)
                relb=[]; roch=[]
                for _ in range(nb):
                    s=rng.integers(0,N,N); p2=prob[s]; o2=obin[s]
                    idx=np.clip(np.digitize(p2,edges)-1,0,9); rb=[o2[idx==b].mean() if (idx==b).any() else np.nan for b in range(10)]; relb.append(rb)
                    P=o2.sum(); Ng=len(o2)-P; th=np.unique(np.r_[0,np.sort(p2),1.0001]); Hh=[];Ff=[]
                    for t in th[::-1]:
                        dd=p2>=t; Hh.append((dd&(o2==1)).sum()/max(P,1)); Ff.append((dd&(o2==0)).sum()/max(Ng,1))
                    roch.append(np.interp(Fgrid,np.array(Ff),np.array(Hh)))
                relb=np.array(relb,float); rl=np.nanpercentile(relb,2.5,0); rh=np.nanpercentile(relb,97.5,0)
                bc=edges[:-1]+0.05; good=np.isfinite(rl)&np.isfinite(rh)
                fR.add_trace(go.Scatter(x=np.r_[bc[good],bc[good][::-1]],y=np.r_[rh[good],rl[good][::-1]],fill="toself",fillcolor=col,opacity=0.12,line=dict(width=0),showlegend=False,hoverinfo="skip"))
                rc=np.array(roch); ql=np.nanpercentile(rc,2.5,0); qh=np.nanpercentile(rc,97.5,0)
                fO.add_trace(go.Scatter(x=np.r_[Fgrid,Fgrid[::-1]],y=np.r_[qh,ql[::-1]],fill="toself",fillcolor=col,opacity=0.12,line=dict(width=0),showlegend=False,hoverinfo="skip"))
        fR.update_layout(title="Reliability"+(" (95% band)" if NB else ""),xaxis_title="Forecast prob",yaxis_title="Obs freq",height=340,xaxis_range=[0,1],yaxis_range=[0,1],margin=dict(t=30))
        fO.update_layout(title="ROC"+(" (95% band)" if NB else ""),xaxis_title="False-alarm rate",yaxis_title="Hit rate",height=340,xaxis_range=[0,1],yaxis_range=[0,1],margin=dict(t=30))
        fV.update_layout(title="Relative economic value",xaxis_title="Cost/loss ratio",yaxis_title="REV",height=340,xaxis_range=[0,1],yaxis_range=[-0.05,1],margin=dict(t=30))
        cA,cB,cC=st.columns(3); cA.plotly_chart(fR,use_container_width=True); _export_fig(st,fR,"reliability"); cB.plotly_chart(fO,use_container_width=True); _export_fig(st,fO,"roc"); cC.plotly_chart(fV,use_container_width=True); _export_fig(st,fV,"rev")
        fP.add_hline(y=0.1,line=dict(color="grey",dash="dash")); fP.update_layout(title="PIT histogram (uniform=calibrated)",barmode="group",height=340,xaxis_range=[0,1],margin=dict(t=30))
        fS.add_trace(go.Scatter(x=[0,mxs],y=[0,mxs],mode="lines",line=dict(color="grey",dash="dot"),name="1:1"))
        fS.update_layout(title="Spread–skill",xaxis_title=f"Ensemble spread ({UL})",yaxis_title=f"RMSE ({UL})",height=340,margin=dict(t=30))
        cD,cE=st.columns(2); cD.plotly_chart(fP,use_container_width=True); _export_fig(st,fP,"pit"); cE.plotly_chart(fS,use_container_width=True); _export_fig(st,fS,"spread")

def _fail(msg):
    print(f"selftest FAILED: {msg}"); raise SystemExit(1)

def selftest():
    """Headless end-to-end check: lazy slice reads -> regrid -> scores.

    The verification box and the threshold are both derived from the data, so
    the test stays meaningful on whatever DEFAULT_DIR/DEFAULT_OBS point at. A
    hard-coded box and threshold can land on a dry corner, in which case every
    score is 0/NaN and the test passes without having exercised anything.
    """
    ocat = catalog(DEFAULT_OBS)
    ff = sorted(glob.glob(f"{DEFAULT_DIR}/day*fcst*.nc"))
    if not ff: _fail(f"no day*fcst*.nc forecast files under {DEFAULT_DIR}")
    fcat = catalog(ff[0]); common = np.intersect1d(fcat["times"], ocat["times"])
    if not len(common): _fail("no dates common to the observation and forecast files")
    date = common[len(common)//2]

    O = read_slice(DEFAULT_OBS, date)
    if O is None: _fail(f"could not read the observation slice for {date}")
    olon, olat = ocat["lon"], ocat["lat"]

    # Box = the middle half of the observation domain. Exercises the sub-setting
    # path without assuming where a given dataset puts its rainfall.
    (la0, la1), (lo0, lo1) = np.quantile(olat, [.25, .75]), np.quantile(olon, [.25, .75])
    bj = (olat >= la0) & (olat <= la1); bi = (olon >= lo0) & (olon <= lo1)
    Ob = O[np.ix_(bj, bi)]

    # Threshold = upper quartile of the wet observed points in the box, so events
    # exist on both sides of it and the contingency table is never degenerate.
    wet = Ob[np.isfinite(Ob) & (Ob > 0)]
    if wet.size == 0: _fail(f"no positive rainfall in the verification box on {date}")
    thr = float(np.quantile(wet, 0.75))

    print(f"date {date}  box {lo0:.1f}-{lo1:.1f}E {la0:.1f}-{la1:.1f}N  threshold {thr:.2f} mm")
    for f in ff:
        fs = read_slice(f, date)
        if fs is None: _fail(f"could not read a forecast slice for {date} from {os.path.basename(f)}")
        Fr = regrid(fcat["lon"], fcat["lat"], fs, olon, olat)
        s = scores(Fr[np.ix_(bj, bi)], Ob, thr)
        lead = lead_from(f)
        print(f"lead {lead} @{thr:.2f}mm: POD {s['POD']:.3f} FAR {s['FAR']:.3f} "
              f"CSI {s['CSI']:.3f} ETS {s['ETS']:.3f} HSS {s['HSS']:.3f} N={s['N']}")

        # The scores must actually be defined -- this is what the old fixed
        # threshold silently lost.
        if s["N"] == 0: _fail(f"lead {lead}: no valid forecast/observation pairs")
        for k in ("POD", "CSI", "ETS", "HSS"):
            if not np.isfinite(s[k]): _fail(f"lead {lead}: {k} is not finite (degenerate contingency table)")
        if not 0.0 <= s["POD"] <= 1.0: _fail(f"lead {lead}: POD {s['POD']} outside [0,1]")
        if not 0.0 <= s["CSI"] <= 1.0: _fail(f"lead {lead}: CSI {s['CSI']} outside [0,1]")
        if not -1.0 <= s["HSS"] <= 1.0: _fail(f"lead {lead}: HSS {s['HSS']} outside [-1,1]")
    print("selftest OK (lazy slice reads, regrid, scores)")

def run_app():
    import math, streamlit as st, plotly.graph_objects as go, pandas as pd
    from plotly.subplots import make_subplots
    st.set_page_config(layout="wide", page_title="Rainfall Verification Dashboard")
    hc1,hc2 = st.columns([5,1])
    hc1.title("Rainfall Verification Dashboard")
    submitted = hc2.button("▶ Run verification", type="primary", use_container_width=True)
    hc2.caption("Edits don't recompute until you press Run.")
    sb = st.sidebar
    sb.header("Data source")
    src_mode = sb.radio("Load from", ["Server folder", "Upload"], index=0)
    ftype = sb.radio("Forecast type", ["Ensemble", "Deterministic"], 0)
    if st.session_state.get("_ftype") != ftype:          # switching mode -> fresh box + clear old results
        for k in ("bx0","bx1","by0","by1","maps","mm","res"): st.session_state.pop(k, None)
        st.session_state["_ftype"] = ftype
    if ftype == "Ensemble":
        emode = sb.radio("Models", ["Single","Multiple"], 0, horizontal=True,
                         help="Single: verify one ensemble. Multiple: compare ensemble MODELS (NEPS, GEFS). Both get Mean/Probabilistic, FSS/CRA, bootstrap, diagnostics.")
        _run_multimodel(st, sb, submitted, ensemble=True, single=(emode=="Single")); return
    else:
        everify = "Deterministic"
        _run_multimodel(st, sb, submitted); return   # deterministic multi-model
    multi_ens = False
    arrange = "Lead times"   # (removed the confusing 'Forecast files represent' selector)
    as_members = (everify == "Members as models") and not multi_ens
    is_prob = (everify.startswith("Probabilistic"))
    ffac=1.0; oscale=1.0; MODELMAP=None; models_sel=None
    if src_mode == "Server folder":
        ddir = sb.text_input("Data directory", DEFAULT_DIR)
        obs_path = sb.text_input("Observation file", DEFAULT_OBS)
        _uc=sb.columns(2); UOPT={"Auto (from file)":None,"mm":1.0,"cm":10.0,"m":1000.0,"inch":25.4}
        ffac=UOPT[_uc[0].selectbox("Forecast units", list(UOPT), 0, key="ens_fu", help="Auto reads the file's units and converts to mm; pick manually if absent.")]
        ofac=UOPT[_uc[1].selectbox("Obs units", list(UOPT), 0, key="ens_ou")]
        oscale = ofac if ofac is not None else (file_units(obs_path) or 1.0)
        if multi_ens:
            MODELMAP=discover_models(ddir)
            if not MODELMAP: st.info(f"No model sub-folders / dayN files under {ddir}."); return
            subs=sorted(MODELMAP, key=lambda d:(d[:1].isdigit(), d.lower()))
            named=[s for s in subs if not s[:1].isdigit()]
            models_sel=sb.multiselect("Ensemble models to compare", subs, default=named[:4] if named else subs[:2])
            if not models_sel: st.info("Select ensemble model(s) to compare (e.g. NEPS, GEFS)."); return
            ffiles=[]
        else:
            with sb.expander("Advanced (optional file filter)"):
                pat = sb.text_input("Forecast glob", "",
                                    help="Leave blank — pick the model in the dropdown below. Only set this to force a filename filter instead.")
            if pat.strip():
                ffiles = sorted(glob.glob(os.path.join(ddir, pat)))
            else:
                # folder may hold ONE ensemble's dayN files directly AND/OR several ensembles as sub-folders.
                OPTS={}
                topf=[f for f in _fc_files(ddir) if lead_from(f) is not None]  # dayN files directly in ddir
                if topf: OPTS["· (files in this folder)"]=topf
                for k,v in discover_models(ddir).items():                       # sub-folder / prefix models
                    vv=[f for f in v if lead_from(f) is not None]
                    if vv and os.path.dirname(vv[0])!=os.path.abspath(ddir).rstrip("/"): OPTS[k]=vv
                if not OPTS: OPTS={"· (files in this folder)":topf}
                if len(OPTS)>1:                                                  # let user pick which ensemble
                    ok=sb.selectbox("Ensemble model", list(OPTS), 0,
                                    help="This folder holds several ensembles — pick one (match the obs year!). Use Multiple to compare 2+.")
                    ffiles=OPTS[ok]
                else:
                    ffiles=next(iter(OPTS.values()))
            if not ffiles: st.info("No dayN forecast files in the data directory (or set a matching glob)."); return
        if not os.path.exists(obs_path): st.info("Set a valid observation file."); return
    else:
        ou = sb.file_uploader("Observation NetCDF", ["nc"]); fu = sb.file_uploader("Forecast NetCDF(s)", ["nc"], accept_multiple_files=True)
        if not ou or not fu: st.info("Upload one observation file and one or more forecast files (small files only)."); return
        obs_path=_save(ou); ffiles=[_save(f) for f in fu]
    if as_members: ffiles = ffiles[:1]
    ocat = catalog(obs_path); olon, olat = ocat["lon"], ocat["lat"]
    # sources: each keeps a date->file map (file may have a time axis or be one date).
    SRC = {}
    if multi_ens:
        for model in models_sel:
            for e in scan_files(MODELMAP[model]):
                key=f"{model} L{e['lead']}"
                if key not in SRC:
                    fc=catalog(e["path"]); SRC[key]=dict(datemap={},member=None,lon=fc["lon"],lat=fc["lat"],lead=e["lead"],model=model)
                SRC[key]["datemap"][np.datetime64(e["vdate"])]=e["path"]
        for k in SRC: SRC[k]["times"]=np.array(sorted(SRC[k]["datemap"]))
    elif as_members:
        f=ffiles[0]; fc=catalog(f); dmap={np.datetime64(t,"D"):f for t in fc["times"]}
        for mv in fc["members"]:
            SRC[mv.replace("APCP_surface_","mem")] = dict(datemap=dict(dmap), member=mv, lon=fc["lon"], lat=fc["lat"], times=fc["times"], lead=lead_from(f), model=mv)
    else:
        for f in ffiles:
            fc = catalog(f); L = lead_from(f)
            key = f"lead {L}" if arrange=="Lead times" else os.path.basename(f)
            if key not in SRC:
                SRC[key] = dict(datemap={}, member=None, lon=fc["lon"], lat=fc["lat"], lead=L, model=None)
            for t in fc["times"]: SRC[key]["datemap"][np.datetime64(t,"D")] = f
        for k in SRC: SRC[k]["times"] = np.array(sorted(SRC[k]["datemap"]))
    anyt = next(iter(SRC.values()))["times"]; dates = np.intersect1d(anyt, ocat["times"])
    if len(dates)==0: st.error("No common dates between forecast and observation."); return
    period = sb.radio("Verification period", ["Daily","Seasonal"], 0,
                      help="Daily: all forecasts valid for one date. Seasonal: pool over all common dates in the files.")
    seasonal = (period=="Seasonal")
    if seasonal:
        dstr=[str(d) for d in dates]
        dr=sb.select_slider("Analysis date range", options=dstr, value=(dstr[0],dstr[-1]),
                            help="Pick start & end by actual date.")
        i0,i1=dstr.index(dr[0]),dstr.index(dr[1]); i0,i1=min(i0,i1),max(i0,i1)
        dates_use=list(dates[i0:i1+1]); date=dates_use[-1]
        sb.info(f"Seasonal: {len(dates_use)} dates ({dr[0]} … {dr[1]})")
    else:
        date = dates[0] if len(dates)==1 else np.datetime64(sb.selectbox("Date", [str(d) for d in dates], index=len(dates)//2))
        dates_use=[date]
        if len(dates)==1: sb.info(f"Single date: {date}")
    sel = sb.multiselect("Compare (models / leads)", list(SRC), default=list(SRC)[:min(4,len(SRC))])
    thr = sb.number_input("Rain threshold (mm)", value=0.1, min_value=0.0, step=0.1)
    diag_on = sb.checkbox("Ensemble diagnostics (reliability / ROC / REV / rank hist / spread-skill)", value=False,
                          help="Reads all members + regrids each — slower. Tick when you want the diagnostics panels.")
    dragsel = sb.radio("Map mouse drag", ["Draw box","Zoom","Pan"], 0, horizontal=True,
                       help="What click-drag does on the maps. Zoom/Pan/double-click-reset apply to all panels together (matched axes).")
    DRAG={"Draw box":"select","Zoom":"zoom","Pan":"pan"}[dragsel]
    coast_on = sb.checkbox("Show coastlines / country borders", value=True)
    # shared box (draw on map OR numeric, synced across panels)
    d0=(float(np.floor(olon.min())),float(np.ceil(olon.max())),float(np.floor(olat.min())),float(np.ceil(olat.max())))
    for k,v in dict(bx0=d0[0],bx1=d0[1],by0=d0[2],by1=d0[3]).items(): st.session_state.setdefault(k,v)
    ev = st.session_state.get("maps")
    if ev and ev.get("selection",{}).get("box"):
        bx=ev["selection"]["box"][0]; xs=sorted(bx["x"]); ys=sorted(bx["y"])
        st.session_state.bx0,st.session_state.bx1=round(xs[0],2),round(xs[1],2); st.session_state.by0,st.session_state.by1=round(ys[0],2),round(ys[1],2)
    sb.header("Selection box (draw on any map or type)")
    c1,c2=sb.columns(2); lon_min=c1.number_input("lon min",key="bx0"); lon_max=c2.number_input("lon max",key="bx1")
    lat_min=c1.number_input("lat min",key="by0"); lat_max=c2.number_input("lat max",key="by1")
    bi=(olon>=lon_min)&(olon<=lon_max); bj=(olat>=lat_min)&(olat<=lat_max)
    # ============ COMPUTE only on submit; otherwise re-render last results ============
    if submitted:
        Oslices={dt: (read_slice(obs_path, dt)*oscale if read_slice(obs_path, dt) is not None else None) for dt in dates_use}
        du=[dt for dt in dates_use if Oslices.get(dt) is not None]
        if not du:
            st.error("No observation for the selected date(s).")
        else:
            Odisp = Oslices[du[0]] if not seasonal else np.nanmean(np.stack([Oslices[dt] for dt in du],0),0)
            vmax=float(np.nanpercentile(Odisp,98) or 50) or 50
            bb2d=np.zeros(Odisp.shape,bool); bb2d[np.ix_(bj,bi)]=True
            # observed box-mean per valid date (time series)
            obs_series=[]
            for dt in du:
                mm=bb2d & np.isfinite(Oslices[dt])
                obs_series.append(float(np.nanmean(Oslices[dt][mm])) if mm.any() else np.nan)
            DISP={}; CNT={}; POOL={}; SER={}; SCMAP={}; CONT={}; PMAP={}
            with st.spinner(f"Processing {len(sel)} source(s) × {len(du)} date(s)…"):
             for name in sel:
                s=SRC[name]; dispacc=None; ndisp=0; A=B=C=D=0; pp=[]; oo=[]; ee=[]; yy=[]
                fser=[np.nan]*len(du); want_ens = is_prob or diag_on
                nn=sF=sO=sF2=sO2=sFO=sae=sse=0.0                    # box continuous (mean forecast)
                Z=lambda: np.zeros(bb2d.shape); cn=Z();cF=Z();cO=Z();cF2=Z();cO2=Z();cFO=Z();cae=Z();cse=Z();ca=Z();cb=Z();cc=Z();cd=Z()
                pcn=Z();pBS=Z();pOb=Z();pCR=Z()                     # per-cell probabilistic (Brier/BSS/CRPS)
                for ix,dt in enumerate(du):
                    Odt=Oslices[dt]; mdt=bb2d & np.isfinite(Odt)
                    fpath=s["datemap"].get(dt)                      # file holding this date for this source
                    if fpath is None: continue
                    ensg=None
                    if want_ens:
                        mem=read_members(fpath,dt)
                        if mem is not None:
                            ensg=np.stack([regrid(s["lon"],s["lat"],mem[k],olon,olat) for k in range(mem.shape[0])],0)*(ffac if ffac is not None else (file_units(fpath) or 1.0))
                    if ensg is not None:
                        rf=np.nanmean(ensg,0); fg=(ensg>=thr).mean(0) if is_prob else rf
                    else:
                        f=read_slice(fpath,dt,s["member"])
                        if f is None: continue
                        fg=regrid(s["lon"],s["lat"],f,olon,olat)*(ffac if ffac is not None else (file_units(fpath) or 1.0)); rf=fg
                    if mdt.any(): fser[ix]=float(np.nanmean(rf[mdt]))    # forecast box-mean rainfall this date
                    dispacc = fg if dispacc is None else dispacc+fg; ndisp+=1
                    if is_prob:
                        pp.append(fg[mdt]); oo.append((Odt[mdt]>=thr).astype(float))
                        if ensg is not None:                        # per-cell BS/BSS/CRPS maps
                            Pc=(ensg>=thr).mean(0); obc=(Odt>=thr).astype(float); vf=np.isfinite(Odt)&np.isfinite(Pc)
                            pcn+=vf; pBS+=np.where(vf,(Pc-obc)**2,0.0); pOb+=np.where(vf,obc,0.0)
                            pCR+=np.where(vf,crps_grid(ensg,Odt),0.0)
                    else:
                        a,b,c,d=counts(fg[mdt],Odt[mdt],thr); A+=a;B+=b;C+=c;D+=d
                        # box continuous + per-cell maps (mean-forecast vs obs)
                        Fb=rf[mdt]; Ob=Odt[mdt]; kk2=len(Fb); nn+=kk2
                        sF+=Fb.sum(); sO+=Ob.sum(); sF2+=(Fb*Fb).sum(); sO2+=(Ob*Ob).sum(); sFO+=(Fb*Ob).sum()
                        sae+=np.abs(Fb-Ob).sum(); sse+=((Fb-Ob)**2).sum()
                        vf=np.isfinite(rf)&np.isfinite(Odt); FF=np.where(vf,rf,0.0); OO=np.where(vf,Odt,0.0)
                        cn+=vf; cF+=FF; cO+=OO; cF2+=FF*FF; cO2+=OO*OO; cFO+=FF*OO
                        de=np.where(vf,rf-Odt,0.0); cae+=np.abs(de); cse+=de*de
                        fp=vf&(rf>=thr); op=vf&(Odt>=thr); ca+=fp&op; cb+=fp&~op&vf; cc+=~fp&op&vf; cd+=vf&~fp&~op
                    if ensg is not None:
                        ee.append(ensg[:,mdt]); yy.append(Odt[mdt])
                        if not is_prob: oo.append((Odt[mdt]>=thr).astype(float))
                if ndisp==0: continue
                DISP[name]=dispacc/ndisp; CNT[name]=(A,B,C,D); SER[name]=fser
                if not is_prob and nn>0:
                    vF=sF2/nn-(sF/nn)**2; vO=sO2/nn-(sO/nn)**2; cov=sFO/nn-(sF/nn)*(sO/nn)
                    CONT[name]=dict(ME=(sF-sO)/nn,MAE=sae/nn,RMSE=float(np.sqrt(sse/nn)),
                                    CORR=float(cov/np.sqrt(vF*vO)) if vF>0 and vO>0 else np.nan)
                    if cn.max()>0: SCMAP[name]=cell_maps((cn,cF,cO,cF2,cO2,cFO,cae,cse,ca,cb,cc,cd))
                if is_prob and pcn.max()>0:
                    with np.errstate(divide="ignore",invalid="ignore"):
                        BS=pBS/pcn; clim=pOb/pcn; BSS=1-BS/(clim*(1-clim)); CR=pCR/pcn
                    bad=pcn<3
                    PMAP[name]={"BS":np.where(bad,np.nan,BS),"BSS":np.where(bad,np.nan,BSS),"CRPS":np.where(bad,np.nan,CR)}
                POOL[name]=dict(prob=np.concatenate(pp) if pp else None,
                                obin=np.concatenate(oo) if oo else None,
                                ens=np.concatenate(ee,axis=1) if ee else None,
                                y=np.concatenate(yy) if yy else None)
            rsel=[n for n in sel if n in DISP]
            series=dict(dates=[str(x) for x in du], abbr=[str(x)[5:] for x in du],
                        obs=obs_series, sources={n:SER[n] for n in rsel})
            st.session_state["res"]=dict(DISP=DISP,CNT=CNT,POOL=POOL,Odisp=Odisp,vmax=vmax,
                olon=olon,olat=olat,sel=rsel,is_prob=is_prob,arrange=arrange,everify=everify,
                period=period,seasonal=seasonal,date=str(date),dates_use=[str(x) for x in du],
                thr=thr,box=(lon_min,lon_max,lat_min,lat_max),diag_on=diag_on,series=series,
                leads={n:SRC[n]["lead"] for n in rsel},SCMAP=SCMAP,CONT=CONT,PMAP=PMAP,
                olon_r=olon,olat_r=olat,src_model={n:SRC[n].get("model") for n in rsel},multi_ens=multi_ens)
            st.session_state.setdefault("_sid", uuid.uuid4().hex[:12])
            audit(dict(session=st.session_state["_sid"], src_mode=src_mode, ftype=ftype, everify=everify,
                       period=period, threshold=thr, box=[lon_min,lon_max,lat_min,lat_max],
                       n_dates=len(du), obs=os.path.basename(obs_path),
                       forecasts=sorted({os.path.basename(p) for n in rsel for p in SRC[n]["datemap"].values()}),
                       sources=rsel, scores="see table"))

    res=st.session_state.get("res")
    if not res:
        st.info("Set options in the sidebar, then press ▶ **Run verification**."); return
    # ---- unpack stored results (rendered every rerun, recomputed only on submit) ----
    DISP=res["DISP"]; CNT=res["CNT"]; POOL=res["POOL"]; Odisp=res["Odisp"]; vmax=res["vmax"]
    olon_r=res["olon"]; olat_r=res["olat"]; rsel=res["sel"]; is_prob=res["is_prob"]; arrange=res["arrange"]
    everify=res["everify"]; period=res["period"]; seasonal=res["seasonal"]; thr=res["thr"]
    lon_min,lon_max,lat_min,lat_max=res["box"]; leads=res["leads"]
    if not rsel: st.warning("No source produced data for the selected box/date(s). Adjust and press Run."); return
    # coastline + box overlay helper
    cxs,cys = coastlines(float(olon_r.min()),float(olon_r.max()),float(olat_r.min()),float(olat_r.max())) if coast_on else ([],[])
    def add_coast_box(fig,row=None,col=None):
        if cxs: fig.add_trace(go.Scatter(x=cxs,y=cys,mode="lines",line=dict(color="black",width=0.8),
                              showlegend=False,hoverinfo="skip"),row=row,col=col)
        fig.add_shape(type="rect",x0=lon_min,x1=lon_max,y0=lat_min,y1=lat_max,
                      line=dict(color="red",width=2),row=row,col=col)
    ndt=len(res["dates_use"]); lbl=(f"mean of {ndt} dates" if seasonal else res["date"])
    # ---- (1) BIG observed map, smooth shading (zsmooth) even on coarse grids ----
    obsfig=go.Figure(go.Heatmap(z=Odisp,x=olon_r,y=olat_r,colorscale="Blues",zmin=0,zmax=vmax,
                     zsmooth="best",colorbar=dict(title="mm")))
    add_coast_box(obsfig); obsfig.update_yaxes(scaleanchor="x")
    obsfig.update_layout(title=f"Observed rainfall — {lbl}",height=500,margin=dict(l=0,r=0,t=34,b=0),dragmode=DRAG)
    series=res.get("series")
    have_ts = seasonal and series and len(series["abbr"])>1
    if have_ts:
        cL,cR=st.columns([3,2])
        with cL:
            st.caption("Draw box here (press **Run** to apply). Zoom/pan via toolbar.")
            st.plotly_chart(obsfig,use_container_width=True,on_select="rerun",selection_mode="box",key="maps")
        with cR:
            # ---- (2) box-mean rainfall vs valid date: obs bold black + each selected lead ----
            xd=series["dates"]   # full ISO dates -> correct year on axis
            ts=go.Figure()
            ts.add_trace(go.Scatter(x=xd,y=series["obs"],mode="lines+markers",
                         name="Observed",line=dict(color="black",width=3),marker=dict(size=5)))
            for nm in rsel:
                ts.add_trace(go.Scatter(x=xd,y=series["sources"][nm],mode="lines+markers",
                             name=nm,line=dict(width=1.8),marker=dict(size=4)))
            ts.update_layout(title="Box-mean rainfall vs valid date",xaxis_title="Valid date",
                             yaxis_title="Rain (mm)",height=500,margin=dict(t=34),
                             xaxis=dict(type="category",tickangle=-45,nticks=15),
                             legend=dict(font=dict(size=9),orientation="h",y=-0.18))
            st.plotly_chart(ts,use_container_width=True,key="tseries")
    else:
        st.caption("Draw box on the observed map (press **Run** to apply). Zoom/pan via toolbar.")
        st.plotly_chart(obsfig,use_container_width=True,on_select="rerun",selection_mode="box",key="maps")
    # ---- forecast panels (smooth), matched axes for synced zoom/pan ----
    if rsel:
        n=len(rsel); ncol=min(n,3); nrow=math.ceil(n/ncol)
        figm=make_subplots(rows=nrow,cols=ncol,subplot_titles=rsel,horizontal_spacing=0.04,vertical_spacing=0.12)
        for idx,name in enumerate(rsel):
            r=idx//ncol+1; cc=idx%ncol+1
            figm.add_trace(go.Heatmap(z=DISP[name],x=olon_r,y=olat_r,colorscale=("YlOrRd" if is_prob else "Blues"),
                           zmin=0,zmax=(1.0 if is_prob else vmax),zsmooth="best",showscale=(idx==0),
                           colorbar=dict(title=("prob" if is_prob else "mm"),len=0.9)),row=r,col=cc)
            add_coast_box(figm,r,cc)
        figm.update_xaxes(matches="x"); figm.update_yaxes(matches="y")
        figm.update_layout(height=300*nrow,margin=dict(l=0,r=0,t=30,b=0),dragmode=DRAG)
        st.caption("Forecast panels — zoom/pan/double-click reset apply to all together." + (" Prob panels 0–1." if is_prob else ""))
        st.plotly_chart(figm,use_container_width=True,key="fmaps")
    rng=f"{res['dates_use'][0]}…{res['dates_use'][-1]} ({len(res['dates_use'])} dates)" if seasonal else res["date"]
    st.subheader(f"Scores  lon[{lon_min},{lon_max}] lat[{lat_min},{lat_max}]  @ {thr} mm  ·  {everify}  ·  {period}: {rng}")
    rows=[]
    for name in rsel:
        if name not in POOL: continue
        if is_prob:
            P=POOL[name]["prob"]; ob=POOL[name]["obin"]
            if P is None or ob is None or P.size==0: continue
            bs=float(np.mean((P-ob)**2)); clim=float(np.mean(ob))
            bss=1-bs/(clim*(1-clim)) if 0<clim<1 else np.nan
            sc=dict(Brier=bs,BSS=bss,CRPS=crps_points(POOL[name]["ens"],POOL[name]["y"]),clim=clim)
        else:
            sc=scores_from_counts(*CNT[name])
            sc.update(res.get("CONT",{}).get(name,{}))       # ME/MAE/RMSE/CORR
        sc["source"]=name; sc["lead"]=leads.get(name); sc["model"]=res.get("src_model",{}).get(name); rows.append(sc)
    if not rows: st.warning("No overlap in box/date(s)."); return
    df=pd.DataFrame(rows)
    if is_prob: order=["source","lead","Brier","BSS","CRPS","clim"]
    else: order=["source","lead","POD","FAR","CSI","BIAS","ETS","HSS","PSS","ACC","EDI","SEDI","EDS","SEDS","YuleQ","ME","MAE","RMSE","CORR"]
    show=[c for c in order if c in df]
    st.dataframe(df[show].style.format({c:"{:.4f}" for c in show if c not in ("source","lead")}),use_container_width=True)
    _dl_table(st, df[show], "ensemble_scores")
    metopts=["Brier","BSS","CRPS"] if is_prob else [x for x in ["POD","FAR","CSI","BIAS","ETS","HSS","PSS","ACC","EDI","SEDI","EDS","SEDS","YuleQ","ME","MAE","RMSE","CORR"] if x in df.columns]
    mets=st.multiselect("Plot metrics",metopts,default=metopts[:3] if is_prob else [x for x in ["POD","FAR","ETS","HSS"] if x in metopts])
    modset=sorted({m for m in df["model"].tolist() if m}) if "model" in df else []
    if mets and len(modset)>1 and df["lead"].notna().all():
        # multi-model: one panel per metric, one line per model, x = lead
        PAL=["#000000","#0072B2","#E69F00","#CC79A7","#009E73","#D55E00","#56B4E9","#F0E442"]
        ncol=2; nrow=math.ceil(len(mets)/ncol)
        fig=make_subplots(rows=nrow,cols=ncol,subplot_titles=mets,vertical_spacing=0.16,horizontal_spacing=0.10)
        for i,mt in enumerate(mets):
            r=i//ncol+1; cc=i%ncol+1
            for j,mo in enumerate(modset):
                d2=df[df["model"]==mo].sort_values("lead")
                fig.add_trace(go.Scatter(x=d2["lead"],y=d2[mt],mode="lines+markers",name=mo,legendgroup=mo,
                    showlegend=(i==0),line=dict(color=PAL[j%len(PAL)],width=2),marker=dict(size=6)),row=r,col=cc)
            fig.update_xaxes(title_text="Lead time (days)",tickmode="linear",dtick=1,row=r,col=cc)
        fig.update_layout(height=280*nrow,margin=dict(t=34),legend=dict(orientation="h",y=-0.08))
    else:
        fig=go.Figure()
        if df["lead"].notna().all() and len(df)>1:
            d2=df.sort_values("lead")
            for m in mets: fig.add_trace(go.Scatter(x=d2["lead"],y=d2[m],mode="lines+markers",name=m))
            fig.update_layout(xaxis_title="Lead time (days)"); fig.update_xaxes(tickmode="linear",dtick=1,tick0=1)
        else:
            for m in mets: fig.add_trace(go.Bar(x=df["source"],y=df[m],name=m))
            fig.update_layout(barmode="group",xaxis_title="Source")
        fig.update_layout(title="Scores",yaxis_title="Score",height=430)
    st.plotly_chart(fig,use_container_width=True); _export_fig(st, fig, "ensemble_scores_plot")
    # ---- score maps (per grid cell) — ensemble Mean (cat+continuous) OR probabilistic (BS/BSS/CRPS) ----
    SCM=res.get("SCMAP",{}); PM=res.get("PMAP",{})
    _sm_src = SCM if not is_prob else PM
    if any(_sm_src.get(n) for n in rsel):
        st.subheader("Score maps (per grid cell)")
        olo=np.asarray(res["olon"]); ola=np.asarray(res["olat"])
        cxs2,cys2=coastlines(float(olo.min()),float(olo.max()),float(ola.min()),float(ola.max()))
        ALLSC=["CRPS","BS","BSS"] if is_prob else ["RMSE","MAE","ME","CORR","POD","FAR","CSI","BIAS","ETS","HSS","PSS","ACC","EDI","SEDI","EDS","SEDS","YuleQ"]
        c1,c2=st.columns([1,3]); scsel=c1.selectbox("Score to map",ALLSC,0,key="ens_scmap")
        srcs=c2.multiselect("Sources",rsel,default=rsel[:min(3,len(rsel))],key="ens_scmap_src")
        DIV={"ME","CORR","PSS","EDI","SEDI","EDS","SEDS","YuleQ","HSS","ETS","BSS"}; cs="RdBu" if scsel in DIV else "Viridis"
        if srcs:
            vals=[_sm_src.get(n,{}).get(scsel) for n in srcs]; fin=[v[np.isfinite(v)] for v in vals if v is not None]
            fin=np.concatenate(fin) if fin else np.array([0.,1.])
            if scsel in DIV: a=float(np.nanpercentile(np.abs(fin),98) or 1) or 1; zmin,zmax=-a,a
            else: zmin=float(np.nanpercentile(fin,2)); zmax=float(np.nanpercentile(fin,98)) or 1
            nc=min(len(srcs),3); nr=math.ceil(len(srcs)/nc)
            fmp=make_subplots(rows=nr,cols=nc,subplot_titles=srcs,horizontal_spacing=0.04,vertical_spacing=0.12)
            for i,nme in enumerate(srcs):
                z=_sm_src.get(nme,{}).get(scsel); r=i//nc+1; cc=i%nc+1
                if z is None: continue
                fmp.add_trace(go.Heatmap(z=z,x=olo,y=ola,colorscale=cs,zmin=zmin,zmax=zmax,showscale=(i==0),colorbar=dict(title=scsel,len=0.9)),row=r,col=cc)
                if cxs2: fmp.add_trace(go.Scatter(x=cxs2,y=cys2,mode="lines",line=dict(color="black",width=0.6),showlegend=False,hoverinfo="skip"),row=r,col=cc)
            fmp.update_xaxes(matches="x"); fmp.update_yaxes(matches="y"); fmp.update_layout(height=250*nr,margin=dict(l=0,r=0,t=28,b=0))
            st.caption(f"{scsel} per grid cell over the selected dates (ensemble-mean forecast).")
            st.plotly_chart(fmp,use_container_width=True,key="ens_scoremaps"); _export_fig(st,fmp,f"ens_scoremap_{scsel}")

    # ---------- ensemble diagnostics (need members; pooled over box points across the period) ----------
    if res["diag_on"]:
        st.subheader(f"Ensemble diagnostics  ·  box lon[{lon_min},{lon_max}] lat[{lat_min},{lat_max}]  @ {thr} mm  ·  {period}: {rng}")
        ENS={name:POOL[name]["ens"] for name in rsel if name in POOL and POOL[name].get("ens") is not None}
        Y  ={name:POOL[name]["y"]   for name in ENS}
        npts=min((v.shape[1] for v in ENS.values()), default=0)
        if not ENS:
            st.info("No ensemble members in the selected sources — diagnostics need members (APCP_surface_*).")
        elif npts<20:
            st.info("Box too small for stable diagnostics — enlarge the box.")
        else:
            rs=np.linspace(0.01,0.99,99); COL=["#000000","#0072B2","#E69F00","#CC79A7","#009E73","#D55E00"]
            cA,cB,cC=st.columns(3)
            fR=go.Figure(); fO=go.Figure(); fV=go.Figure()
            fR.add_trace(go.Scatter(x=[0,1],y=[0,1],mode="lines",line=dict(color="grey",dash="dot"),showlegend=False))
            fO.add_trace(go.Scatter(x=[0,1],y=[0,1],mode="lines",line=dict(color="grey",dash="dot"),showlegend=False))
            fV.add_trace(go.Scatter(x=[0,1],y=[0,0],mode="lines",line=dict(color="grey",dash="dot"),showlegend=False))
            obar=0.0
            for i,(name,ens) in enumerate(ENS.items()):
                col=COL[i%len(COL)]; obsb=Y[name]; prob=(ens>=thr).mean(0); obin=(obsb>=thr).astype(float)
                obar=float(obin.mean())
                mp,of,n=reliability_curve(prob,obin); fR.add_trace(go.Scatter(x=mp,y=of,mode="lines+markers",name=name,line=dict(color=col)))
                F,H,auc=roc_curve(prob,obin); fO.add_trace(go.Scatter(x=F,y=H,mode="lines",name=f"{name} AUC={auc:.3f}",line=dict(color=col)))
                V=rev_curve(prob,obin,rs); fV.add_trace(go.Scatter(x=rs,y=V,mode="lines",name=name,line=dict(color=col)))
            fR.add_hline(y=obar,line=dict(color="grey",dash="dash"))
            fR.update_layout(title="Reliability",xaxis_title="Forecast prob",yaxis_title="Obs freq",height=340,xaxis_range=[0,1],yaxis_range=[0,1],margin=dict(t=30))
            fO.update_layout(title="ROC",xaxis_title="False-alarm rate",yaxis_title="Hit rate",height=340,xaxis_range=[0,1],yaxis_range=[0,1],margin=dict(t=30))
            fV.update_layout(title="Relative economic value",xaxis_title="Cost/loss ratio",yaxis_title="REV",height=340,xaxis_range=[0,1],yaxis_range=[-0.05,1],margin=dict(t=30))
            cA.plotly_chart(fR,use_container_width=True); cB.plotly_chart(fO,use_container_width=True); cC.plotly_chart(fV,use_container_width=True)
            cD,cE=st.columns(2)
            fH=go.Figure()
            for i,(name,ens) in enumerate(ENS.items()):
                cnt=rank_hist(ens,Y[name]); cnt=cnt/cnt.sum()
                fH.add_trace(go.Bar(x=np.arange(len(cnt)),y=cnt,name=name,marker_color=COL[i%len(COL)]))
            fH.add_hline(y=1.0/(list(ENS.values())[0].shape[0]+1),line=dict(color="grey",dash="dash"))
            fH.update_layout(title="Rank histogram (flat = calibrated)",xaxis_title="Rank of obs",yaxis_title="Rel. freq.",barmode="group",height=360,margin=dict(t=30))
            cD.plotly_chart(fH,use_container_width=True); _export_fig(st,fH,"rank_hist")
            # ---- separate PIT histogram ----
            fP=go.Figure(); edges=np.linspace(0,1,11)
            for i,(name,ens) in enumerate(ENS.items()):
                pit=pit_values(ens,Y[name]); h,_=np.histogram(pit,bins=edges); h=h/h.sum()
                fP.add_trace(go.Bar(x=(edges[:-1]+0.05),y=h,name=name,marker_color=COL[i%len(COL)]))
            fP.add_hline(y=0.1,line=dict(color="grey",dash="dash"))
            fP.update_layout(title="PIT histogram (uniform = calibrated)",xaxis_title="PIT value",yaxis_title="Rel. freq.",barmode="group",height=360,xaxis_range=[0,1],margin=dict(t=30))
            cE.plotly_chart(fP,use_container_width=True); _export_fig(st,fP,"pit")
            cE2,cF2b=st.columns(2)
            fS=go.Figure(); mx=0
            for i,(name,ens) in enumerate(ENS.items()):
                xs,ys,ms,mr=spread_skill(ens,Y[name]); col=COL[i%len(COL)]
                fS.add_trace(go.Scatter(x=xs,y=ys,mode="lines+markers",name=f"{name} (sprd={ms:.2f},rmse={mr:.2f})",line=dict(color=col)))
                mx=max(mx,float(np.nanmax(xs) if xs.size else 0),float(np.nanmax(ys) if ys.size else 0))
            fS.add_trace(go.Scatter(x=[0,mx],y=[0,mx],mode="lines",line=dict(color="grey",dash="dot"),name="1:1"))
            fS.update_layout(title="Spread–skill (RMSE of ens-mean vs ensemble spread)",xaxis_title="Ensemble spread (std, mm)",yaxis_title="RMSE (mm)",height=360,margin=dict(t=30))
            cE2.plotly_chart(fS,use_container_width=True); _export_fig(st,fS,"spread_skill")
            st.caption("Reliability/ROC/REV use exceedance prob at the threshold. Rank histogram & spread–skill use raw member values. All pooled over grid points inside the box for the selected date.")

def _save(u):
    import tempfile; p=os.path.join(tempfile.gettempdir(),u.name); buf=u.getbuffer(); open(p,"wb").write(buf)
    audit(dict(event="upload", file=u.name, bytes=int(getattr(buf,"nbytes",len(buf)))))
    return p

if __name__=="__main__":
    selftest() if "--selftest" in sys.argv else run_app()
