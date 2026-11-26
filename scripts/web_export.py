"""Export a finished run for the web page (MapLibre + SVG charts).

    python scripts/web_export.py runs/<run_id> <site>/assets/models/geoready

Writes zones.geojson, gcca.geojson, exclusions.png and data.json. Geometry is
in EPSG:4326 with 4-decimal coordinates; the exclusion image is warped to
Web Mercator so it lines up with the basemap.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import shapely
from PIL import Image
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from geoready import zones, __version__  # noqa: E402
from geoready.run import load_config  # noqa: E402
from geoready.plots import CODE_COLORS  # noqa: E402

run_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
rec = json.load(open(run_dir / "run.json"))
cfg = load_config(ROOT / rec["parameter_file"])
z = pd.read_csv(run_dir / "zones.csv")
SC = list(cfg["grid"]["scenarios"])
r1 = lambda v: None if pd.isna(v) else round(float(v), 1)
r3 = lambda v: None if pd.isna(v) else round(float(v), 3)

# ---------------------------------------------------------------- zones
import os
os.chdir(ROOT)
g, prof = zones.load_grids(cfg)
with rasterio.open(run_dir / "zone_id.tif") as ds:
    zg = ds.read(1)
cells = zones.zone_cells(zg, g["study_area"], g["gcca_zone"], prof["transform"], prof["crs"],
                         cfg["zones"]["size_km"], list(z["zone_id"]))
cells = cells.merge(z, on="zone_id").to_crs(4326)
cells["geometry"] = shapely.set_precision(cells.geometry, 1e-4)
crit = list(cfg["readiness"])
props = []
for _, r in cells.iterrows():
    p = {"id": r.zone_id, "km2": r1(r.eligible_km2), "mw": round(r.capacity_mw), "pv": round(r.pvout),
         "sl": r1(r.slope_deg), "gk": r1(r.grid_km), "lc": round(r.lcoe_base), "lo": round(r.lcoe_low),
         "hi": round(r.lcoe_high), "rz": r3(r.redz_share), "eia": r3(r.eia_pv_share),
         "sub": r.substation, "la": r.local_area, "sa": r.supply_area,
         "lsub": r1(r.sub_limit_mw), "lloc": r1(r.local_limit_mw), "lsup": r1(r.supply_limit_mw)}
    for s in SC:
        p[f"a_{s[0]}"] = round(r[f"alloc_mw_{s}"])
        p[f"r_{s[0]}"] = r3(r[f"readiness_{s}"])
        p[f"b_{s[0]}"] = str(r[f"binding_{s}"])
    for c in crit:
        p[f"n_{c}"] = r3(r[f"n_{c}"])
    props.append(p)
fc = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": p, "geometry": shapely.geometry.mapping(geom)}
    for p, geom in zip(props, cells.geometry)]}
json.dump(fc, open(out / "zones.geojson", "w"), separators=(",", ":"))

# ---------------------------------------------------------------- GCCA zones and the province
gc = gpd.read_file(cfg["vectors"], layer="gcca_zones")
nc = gpd.read_file(cfg["vectors"], layer="nc").to_crs(gc.crs)
gc = gc.clip(nc)
gc = gc[gc.area > 50e6].copy()
agg = z.groupby("substation").agg(n=("zone_id", "count"), tech=("capacity_mw", "sum"),
                                  a_s=("alloc_mw_strengthened", "sum"), a_p=("alloc_mw_published", "sum"))
gc = gc.join(agg, on="substation")
gc["geometry"] = gc.geometry.simplify(800)
gc = gc.to_crs(4326)
gc["geometry"] = shapely.set_precision(gc.geometry, 1e-4)
keep = ["substation", "supply_area", "local_area", "sub_limit_mw", "local_limit_mw", "supply_limit_mw", "n", "tech", "a_s", "a_p", "geometry"]
gc[keep].to_file(out / "gcca.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)
ncw = nc.to_crs(4326)
ncw["geometry"] = shapely.set_precision(ncw.geometry.simplify(0.003), 1e-4)
ncw[["geometry"]].to_file(out / "province.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)

# ---------------------------------------------------------------- exclusion image (Web Mercator)
with rasterio.open(run_dir / "eligibility.tif") as src:
    dst_crs = "EPSG:3857"
    tr, w, h = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=500)
    arr = np.full((h, w), 255, np.uint8)
    a = src.read(1)
    a = np.where(np.isnan(a) | (a == src.nodata), 255, a).astype(np.uint8)
    reproject(a, arr, src_transform=src.transform, src_crs=src.crs, dst_transform=tr, dst_crs=dst_crs,
              resampling=Resampling.nearest, src_nodata=255, dst_nodata=255)
    pal = np.zeros((256, 4), np.uint8)
    for k, c in CODE_COLORS.items():
        if k == 0:
            continue                       # eligible: transparent, the zones show through
        rgb = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        pal[k] = (0, 0, 0, 0) if k == 5 else (*rgb, 235)   # "too far": left blank, no zones there
    Image.fromarray(pal[arr], "RGBA").save(out / "exclusions.png", optimize=True)
    w_, s_, e_, n_ = transform_bounds(dst_crs, "EPSG:4326", tr.c, tr.f + tr.e * h, tr.c + tr.a * w, tr.f)
    img_coords = [[w_, n_], [e_, n_], [e_, s_], [w_, s_]]

# ---------------------------------------------------------------- data.json
curves = {}
for s in SC:
    c = pd.read_csv(run_dir / f"supply_curve_{s}.csv").merge(z[["zone_id", "lcoe_low", "lcoe_high"]], on="zone_id")
    curves[s] = [[r.zone_id, round(r.mw_from, 1), round(r.mw_to, 1), round(r.lcoe), round(r.lcoe_low), round(r.lcoe_high)]
                 for r in c.itertuples()]
elig = pd.read_csv(run_dir / "eligibility_summary.csv")
sens = pd.read_csv(run_dir / "sensitivity.csv", index_col=0)
zero_sub = z["sub_limit_mw"] == 0
data = {
    "run_id": rec["run_id"], "model_version": __version__, "finished": rec["finished"],
    "qa": rec["qa"],
    "scenarios": {s: {"label": cfg["grid"]["scenarios"][s]["label"],
                      "mw": round(float(z[f"alloc_mw_{s}"].sum())),
                      "zones": int((z[f"alloc_mw_{s}"] > 0).sum()),
                      "median_readiness": r3(z[f"readiness_{s}"].median())} for s in SC},
    "eligibility": [{"code": int(r.reason_code) if "reason_code" in elig else int(i), "reason": r.reason, "km2": round(r.km2)}
                    for i, r in zip(zones.CODES, elig.itertuples())],
    "zones": {"n": len(z), "eligible_km2": round(z["eligible_km2"].sum()), "tech_mw": round(z["capacity_mw"].sum()),
              "zero_sub_share": round(float(z.loc[zero_sub, "capacity_mw"].sum() / z["capacity_mw"].sum()), 3),
              "zero_subs": sorted(z.loc[zero_sub, "substation"].unique().tolist()),
              "lcoe_median": {c: round(float(z[f"lcoe_{c}"].median())) for c in ("low", "base", "high")},
              "lcoe_base_p5_p95": [round(float(v)) for v in z["lcoe_base"].quantile([.05, .95])]},
    "reference_bids": cfg["economics"]["reference_bids_r_per_mwh"],
    "readiness": {k: {"weight": v["weight"], "lo": v["lo"], "hi": v["hi"],
                      "higher_is_better": v.get("higher_is_better", True)} for k, v in cfg["readiness"].items()},
    "sensitivity": {k: {"top50": float(v["top-50 overlap"]), "rho": float(v["Spearman rho"])} for k, v in sens.iterrows()},
    "curves": curves,
    "image": {"url": "exclusions.png", "coordinates": img_coords},
    "codes": {str(k): {"label": v, "color": CODE_COLORS[k]} for k, v in zones.CODES.items()},
}
json.dump(data, open(out / "data.json", "w"), separators=(",", ":"))
for f in sorted(out.iterdir()):
    print(f.name, round(f.stat().st_size / 1e3), "kB")
