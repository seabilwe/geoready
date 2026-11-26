"""Grid-constrained allocation of capacity to zones.

Each zone connects through a chain of grid limits, for example,
substation -> local area -> supply area (the GCCA hierarchy). Limits are
shared: every zone behind a substation draws on the same headroom, so the
same MW are never counted twice.

Because each zone sits in exactly one chain and the chains nest (a laminar
family), filling zones cheapest-first up to whatever headroom is left at
every level gives the least-cost allocation for any target, and the
maximum connectable capacity when there is no target. tests/test_allocate.py
checks this against a linear programme on random networks.

Unknown headroom is not treated as available: a zone behind a limit of
unknown size gets 0 MW and is flagged 'unknown', unless policy='ignore'.
"""
from __future__ import annotations

import math

import pandas as pd


def allocate(zones: pd.DataFrame, limits: dict, chain_cols: list[str],
             cost_col: str = "lcoe", cap_col: str = "capacity_mw",
             target_mw: float | None = None, unknown: str = "zero") -> pd.DataFrame:
    """Allocate capacity cheapest-first under shared, nested limits.

    zones      one row per zone, with capacity, cost and the id of each limit
               it sits behind (one column per level, named in chain_cols).
    limits     {limit_id: MW}; None or NaN means unknown. A limit id that is
               absent from the dict means that level does not constrain.
    target_mw  stop once this much is allocated (None = as much as fits).
    unknown    'zero' (default) or 'ignore' for limits of unknown size.

    Returns a copy of zones with: alloc_mw, binding (the limit that stopped
    it, or 'capacity' / 'target' / 'unknown:<id>'), and grid_status.
    """
    if unknown not in ("zero", "ignore"):
        raise ValueError("unknown must be 'zero' or 'ignore'")
    left = {}
    for k, v in limits.items():
        left[k] = None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
    out = zones.copy()
    out["alloc_mw"] = 0.0
    out["binding"] = ""
    out["grid_status"] = "known"
    remaining_target = math.inf if target_mw is None else float(target_mw)

    # Cheapest first; zones with no cost go last and stay unallocated.
    order = out[cost_col].fillna(math.inf).sort_values(kind="mergesort").index
    for i in order:
        cap = float(out.at[i, cap_col])
        if not math.isfinite(out.at[i, cost_col]) or cap <= 0:
            out.at[i, "binding"] = "no cost" if cap > 0 else "capacity"
            continue
        room, why = cap, "capacity"
        ids = [out.at[i, c] for c in chain_cols]
        blocked = False
        for lid in ids:
            if lid is None or (isinstance(lid, float) and math.isnan(lid)) or lid not in left:
                continue
            if left[lid] is None:
                out.at[i, "grid_status"] = "unknown"
                if unknown == "zero":
                    out.at[i, "binding"] = f"unknown:{lid}"
                    blocked = True
                    break
                continue
            if left[lid] < room:
                room, why = left[lid], lid
        if blocked:
            continue
        if remaining_target < room:
            room, why = remaining_target, "target"
        room = max(room, 0.0)
        out.at[i, "alloc_mw"] = room
        out.at[i, "binding"] = why
        for lid in ids:
            if lid in left and left[lid] is not None:
                left[lid] -= room
        remaining_target -= room
    return out


def supply_curve(alloc: pd.DataFrame, cost_col: str = "lcoe", mw_col: str = "alloc_mw",
                 id_col: str = "zone_id") -> pd.DataFrame:
    """Stepped supply curve: zones sorted by cost with cumulative MW."""
    s = alloc.loc[alloc[mw_col] > 0, [id_col, cost_col, mw_col]].sort_values(cost_col)
    s = s.rename(columns={cost_col: "lcoe", mw_col: "alloc_mw"})
    s["mw_from"] = s["alloc_mw"].cumsum() - s["alloc_mw"]
    s["mw_to"] = s["alloc_mw"].cumsum()
    return s.reset_index(drop=True)
