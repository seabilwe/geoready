"""Join zones to NTCSA GCCA 2025 limits and run the allocation scenarios."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyogrio

from .allocate import allocate

LEVEL_KEYS = {"sub_limit_mw": "sub", "local_limit_mw": "local", "supply_limit_mw": "supply"}


def read_gcca(gpkg, layer="gcca_zones"):
    """GCCA substation zones keyed by the fid used in the gcca_zone grid."""
    df = pyogrio.read_dataframe(gpkg, layer=layer, fid_as_index=True, read_geometry=False)
    df.index.name = "gcca_fid"
    return df


def attach_limits(zones: pd.DataFrame, gcca: pd.DataFrame) -> pd.DataFrame:
    """Add the GCCA zone fields and one limit id per level to every zone.

    Ids make shared limits explicit: all zones behind the same substation
    get the same 'sub:' id, all in the same local area the same 'local:' id.
    """
    z = zones.join(gcca[["substation", "supply_area", "local_area", "sub_limit_mw",
                         "local_limit_mw", "supply_limit_mw", "in_table"]], on="gcca_fid")
    z["sub"] = "sub:" + z["substation"].astype(str)
    z["local"] = "local:" + z["supply_area"].astype(str) + "/" + z["local_area"].astype(str)
    z["supply"] = "supply:" + z["supply_area"].astype(str)
    return z


def limits_for(z: pd.DataFrame, use: list[str]) -> dict:
    """{limit_id: MW or None} for the levels a scenario uses. Missing values
    (substation not in the GCCA table) become None = unknown."""
    out = {}
    for col in use:
        key = LEVEL_KEYS[col]
        for lid, v in z.groupby(key)[col].first().items():
            out[lid] = None if pd.isna(v) else float(v)
    return out


def run_scenarios(z: pd.DataFrame, scenarios: dict, cost_col="lcoe_base",
                  unknown="zero") -> dict[str, pd.DataFrame]:
    chain = list(LEVEL_KEYS.values())
    out = {}
    for sid, sc in scenarios.items():
        lim = limits_for(z, sc["use"])
        a = allocate(z, lim, chain, cost_col=cost_col, cap_col="capacity_mw", unknown=unknown)
        a["headroom_share"] = np.where(a["capacity_mw"] > 0, a["alloc_mw"] / a["capacity_mw"], np.nan)
        out[sid] = a
    return out
