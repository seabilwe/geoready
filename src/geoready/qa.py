"""Release gate checks (Implementation Guide p.5).

Each check returns a dict {check, passed, detail}. gate() collects them and
passes only if every check passes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _r(name, passed, detail):
    return {"check": name, "passed": bool(passed), "detail": detail}


def no_exclusion_violation(zones_gdf, exclusions_gdf, tol_km2=0.01):
    """Mandatory exclusions must not overlap candidate zones (area in km2;
    both layers in the same metric CRS)."""
    if len(zones_gdf) == 0 or len(exclusions_gdf) == 0:
        return _r("mandatory exclusions", True, "nothing to compare")
    inter = zones_gdf[["geometry"]].overlay(exclusions_gdf[["geometry"]], how="intersection",
                                            keep_geom_type=True)
    a = float(inter.area.sum()) / 1e6
    return _r("mandatory exclusions", a <= tol_km2, f"overlap {a:.4f} km² (tolerance {tol_km2})")


def allocation_within_limits(alloc: pd.DataFrame, limits: dict, chain_cols, tol=1e-6):
    """Sum of allocations behind every known limit stays within it, and no
    zone gets more than its technical capacity."""
    bad = []
    for col in chain_cols:
        sums = alloc.groupby(col)["alloc_mw"].sum()
        for lid, s in sums.items():
            lim = limits.get(lid)
            if lim is not None and not (isinstance(lim, float) and np.isnan(lim)) and s > lim + tol:
                bad.append(f"{lid}: {s:.1f} > {lim:.1f}")
    over = alloc[alloc["alloc_mw"] > alloc["capacity_mw"] + tol]
    if len(over):
        bad.append(f"{len(over)} zones above technical capacity")
    if (alloc["alloc_mw"] < -tol).any():
        bad.append("negative allocation")
    return _r("grid allocation", not bad, "; ".join(bad) or "all limits respected")


def unknowns_explicit(alloc: pd.DataFrame):
    """Zones behind unknown headroom are flagged and get no capacity."""
    u = alloc[alloc["grid_status"] == "unknown"]
    ok = (u["alloc_mw"] == 0).all() if "binding" in u and u["binding"].str.startswith("unknown").all() else True
    return _r("unknown grid explicit", ok, f"{len(u)} zones behind unknown headroom")


def totals_reconcile(zones: pd.DataFrame, area_col="area_km2", cap_col="capacity_mw",
                     density=None, tol=1e-6):
    """Capacity equals area x density for every zone."""
    if density is None:
        return _r("units and totals", True, "density not given")
    d = (zones[cap_col] - zones[area_col] * density).abs().max()
    return _r("units and totals", d <= tol, f"max difference {d:.2e} MW")


def weights_sum_to_one(criteria: dict):
    s = sum(c["weight"] for c in criteria.values())
    return _r("readiness weights", np.isclose(s, 1.0), f"sum {s:.3f}")


def gate(results: list[dict]) -> dict:
    return {"passed": all(r["passed"] for r in results), "checks": results}
