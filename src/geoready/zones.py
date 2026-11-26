"""Eligibility and candidate zones on the 250 m analysis grid.

All prepared grids share one grid (same shape, transform and CRS), built by
scripts/prepare_inputs_qgis.py. Arrays are NumPy; geometry comes only at the
end, when zones are turned into polygons.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio import features

# Exclusion codes. 1 is a legal prohibition; 2-5 are editable technical
# thresholds; 9 means an input was missing, which is never read as "fine".
CODES = {
    0: "eligible",
    1: "protected area (legal)",
    2: "incompatible land cover",
    3: "too steep",
    4: "weak solar resource",
    5: "too far from a substation",
    9: "unknown (input missing)",
}


def expand_codes(spec):
    """'14-24' style ranges and single ints -> set of ints."""
    out = set()
    for s in spec:
        if isinstance(s, str) and "-" in s:
            a, b = s.split("-")
            out |= set(range(int(a), int(b) + 1))
        else:
            out.add(int(s))
    return out


def load_grids(cfg, root="."):
    """Read every raster input named in cfg['grids'] into float arrays (NaN for nodata)."""
    root = Path(root)
    out, profile = {}, None
    for key, rel in cfg["grids"].items():
        with rasterio.open(root / rel) as ds:
            a = ds.read(1).astype("float32")
            if ds.nodata is not None:
                a[a == ds.nodata] = np.nan
            if profile is None:
                profile = ds.profile.copy()
            elif (ds.transform, ds.shape) != (profile["transform"], (profile["height"], profile["width"])):
                raise ValueError(f"{rel} is not on the analysis grid")
        out[key] = a
    return out, profile


def rasterize_mask(gpkg, layer, profile, all_touched=True):
    """Burn a polygon layer onto the analysis grid (1 inside, 0 outside).

    all_touched=True marks every cell the polygon touches, so a legal
    exclusion is never shaved at its edges by the cell-centre rule.
    """
    import geopandas as gpd
    gdf = gpd.read_file(gpkg, layer=layer).to_crs(profile["crs"])
    return features.rasterize(((geom, 1) for geom in gdf.geometry if geom is not None),
                              out_shape=(profile["height"], profile["width"]),
                              transform=profile["transform"], fill=0, all_touched=all_touched,
                              dtype="uint8")


def eligibility(g, cfg):
    """Return the exclusion code grid (NaN outside the study area).

    The first applicable reason wins, in code order, so a protected area that
    is also steep is reported as protected.
    """
    e = cfg["eligibility"]
    inside = g["study_area"] == 1
    code = np.full(inside.shape, np.nan, "float32")
    code[inside] = 0
    lc_ex = np.isin(g["landcover"], list(expand_codes(e["excluded_landcover_codes"])))
    far = g["dist_sub_m"] > e["max_grid_km"] * 1000
    weak = g["pvout"] < e["min_pvout"]
    steep = g["slope"] > e["max_slope_deg"]
    prot = g["protected"] == 1
    missing = np.isnan(g["pvout"]) | np.isnan(g["slope"]) | np.isnan(g["dist_sub_m"]) | (g["landcover"] == 0) \
        | np.isnan(g["landcover"])
    for c, m in [(5, far), (4, weak), (3, steep), (2, lc_ex), (9, missing), (1, prot)]:
        code[inside & m] = c   # later assignments win; protected always wins
    return code


def zone_ids(eligible, gcca_zone, transform, size_km):
    """Label eligible cells by (square of size_km) x (GCCA substation zone).

    A zone never crosses a GCCA zone, so each zone has exactly one chain of
    grid limits. Returns an int32 label grid (0 = not in a zone).
    """
    h, w = eligible.shape
    res = transform.a
    x0, y0 = transform.c, transform.f
    cols = ((x0 + (np.arange(w) + 0.5) * res) // (size_km * 1000)).astype(np.int64)
    rows = ((y0 - (np.arange(h) + 0.5) * res) // (size_km * 1000)).astype(np.int64)
    cx = cols - cols.min()
    cy = rows.max() - rows
    sq = cy[:, None] * (cx.max() + 1) + cx[None, :]
    gz = np.nan_to_num(gcca_zone, nan=0).astype(np.int64)
    key = np.where(eligible, sq * 10000 + gz, -1)
    uniq, inv = np.unique(key, return_inverse=True)
    lab = inv.reshape(key.shape).astype(np.int32)
    if uniq[0] != -1:      # every cell eligible: shift so 0 stays "no zone"
        lab = lab + 1
    return lab


def zone_table(lab, g, cell_km2, min_km2):
    """Per-zone statistics over eligible cells; drops zones below min_km2.

    Returns (table, relabelled grid) with zone ids 1..n in a stable order
    (north-west to south-east).
    """
    n = int(lab.max())
    flat = lab.ravel()
    cnt = np.bincount(flat, minlength=n + 1)

    def mean(a):
        a2 = np.nan_to_num(a, nan=0.0).ravel()
        return np.bincount(flat, weights=a2, minlength=n + 1) / np.maximum(cnt, 1)

    def share(mask):
        return np.bincount(flat, weights=mask.ravel().astype(float), minlength=n + 1) / np.maximum(cnt, 1)

    gz = np.nan_to_num(g["gcca_zone"], nan=0).astype(np.int64).ravel()
    gz_of = np.zeros(n + 1, np.int64)
    gz_of[flat] = gz
    ys, xs = np.indices(lab.shape)
    t = pd.DataFrame({
        "label": np.arange(n + 1),
        "eligible_km2": cnt * cell_km2,
        "pvout": mean(g["pvout"]),
        "slope_deg": mean(g["slope"]),
        "grid_km": mean(g["dist_sub_m"]) / 1000,
        "redz_share": share(g["redz_solar"] == 1),
        "eia_pv_share": share(g["eia_pv"] == 1),
        "gcca_fid": gz_of,
        "row": np.bincount(flat, weights=ys.ravel(), minlength=n + 1) / np.maximum(cnt, 1),
        "col": np.bincount(flat, weights=xs.ravel(), minlength=n + 1) / np.maximum(cnt, 1),
    }).iloc[1:]
    t = t[t["eligible_km2"] >= min_km2].sort_values(["row", "col"]).reset_index(drop=True)
    t["zone_id"] = [f"Z{i:04d}" for i in range(1, len(t) + 1)]
    remap = np.zeros(n + 1, np.int32)
    remap[t["label"].values] = np.arange(1, len(t) + 1)
    new = remap[lab]
    return t.drop(columns=["label", "row", "col"]), new


def footprints(lab, transform, crs, zone_ids_):
    """Polygons of each zone's eligible cells (one multipolygon per zone)."""
    import geopandas as gpd
    from shapely.geometry import shape
    geoms, ids = [], []
    for geom, v in features.shapes(lab, mask=lab > 0, transform=transform, connectivity=8):
        geoms.append(shape(geom))
        ids.append(int(v))
    gdf = gpd.GeoDataFrame({"z": ids}, geometry=geoms, crs=crs).dissolve(by="z")
    gdf["zone_id"] = [zone_ids_[i - 1] for i in gdf.index]
    return gdf.reset_index(drop=True)[["zone_id", "geometry"]]


def zone_cells(zone_grid, study_area, gcca_zone, transform, crs, size_km, zone_ids_, simplify_m=400):
    """Whole zone squares for maps: every study-area cell of a zone's square
    (clipped to its GCCA zone), not only its eligible cells. The eligible
    area is the zone's eligible_km2; draw the exclusion grid on top to show
    what inside the square is excluded."""
    import geopandas as gpd
    from shapely.geometry import shape
    inside = study_area == 1
    lab_all = zone_ids(inside, gcca_zone, transform, size_km)
    m = zone_grid > 0
    lookup = np.zeros(lab_all.max() + 1, np.int32)
    lookup[lab_all[m]] = zone_grid[m]
    full = (lookup[lab_all] * inside).astype("int32")
    geoms, ids = [], []
    for geom, v in features.shapes(full, mask=full > 0, transform=transform, connectivity=4):
        geoms.append(shape(geom))
        ids.append(int(v))
    gdf = gpd.GeoDataFrame({"z": ids}, geometry=geoms, crs=crs).dissolve(by="z")
    gdf["geometry"] = gdf.geometry.simplify(simplify_m).buffer(0)
    gdf["zone_id"] = [zone_ids_[i - 1] for i in gdf.index]
    return gdf.reset_index(drop=True)[["zone_id", "geometry"]]
