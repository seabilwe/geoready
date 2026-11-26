"""Capacity, yield, connection cost and levelised cost of electricity.

All money is in one currency and base year, set in the config. Every
function is plain arithmetic on numbers or NumPy arrays, so it can be
checked by hand (see tests/test_econ.py).
"""
from __future__ import annotations

import numpy as np


def capacity_mw(area_km2, density_mw_per_km2):
    """Technical capacity: usable eligible area x capacity density."""
    return np.asarray(area_km2, dtype=float) * density_mw_per_km2


def annual_yield_mwh(cap_mw, pvout_kwh_per_kwp):
    """First-year output.

    1 MW = 1,000 kWp, and kWh x 1,000 = MWh, so MW x (kWh/kWp/yr) gives MWh/yr
    directly. Global Solar Atlas PVOUT already includes typical system losses,
    so no further loss factor is applied here.
    """
    return np.asarray(cap_mw, dtype=float) * np.asarray(pvout_kwh_per_kwp, dtype=float)


def connection_cost(distance_km, cost_per_km, fixed_cost, route_factor=1.0):
    """Indicative connection cost.

    distance_km is straight-line distance to the linked substation, a lower
    bound on the real route; route_factor scales it up (1.0 = straight line).
    """
    d = np.asarray(distance_km, dtype=float)
    return d * route_factor * cost_per_km + fixed_cost


def discount_sums(rate, lifetime, degradation=0.0):
    """Return (sum of discount factors, sum of degraded discount factors).

    Years run 1..lifetime. The first sum discounts a constant annual cost;
    the second discounts output that falls by `degradation` a year.
    """
    t = np.arange(1, int(lifetime) + 1)
    df = (1.0 + rate) ** -t
    return df.sum(), (df * (1.0 - degradation) ** (t - 1)).sum()


def lcoe(capex, opex_per_year, first_year_mwh, rate, lifetime, degradation=0.0):
    """Levelised cost per MWh.

    LCOE = (CAPEX + PV of OPEX) / PV of electricity generated, with CAPEX
    paid at year 0 and costs and output at the end of years 1..lifetime.
    Returns NaN where output is zero or missing, never zero.
    """
    s_cost, s_energy = discount_sums(rate, lifetime, degradation)
    capex = np.asarray(capex, dtype=float)
    opex = np.asarray(opex_per_year, dtype=float)
    e = np.asarray(first_year_mwh, dtype=float)
    pv_energy = e * s_energy
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (capex + opex * s_cost) / pv_energy
    return np.where(pv_energy > 0, out, np.nan)


def zone_costs(cap_mw, pvout, distance_km, econ: dict, case: str = "base"):
    """Full cost chain for one cost case ('low', 'base' or 'high').

    econ is the `economics` block of the config. Returns a dict of arrays.
    """
    p = {k: (v[case] if isinstance(v, dict) and case in v else v) for k, v in econ.items()}
    cap_mw = np.asarray(cap_mw, dtype=float)
    plant_capex = cap_mw * 1000.0 * p["capex_per_kw"]
    # One line and one on-site station per project; a zone holds
    # capacity / project size projects (fractional, so cost scales with MW).
    per_project = connection_cost(distance_km, p["line_cost_per_km"], p["connection_fixed_cost"],
                                  p["route_factor"])
    conn = per_project * cap_mw / p["project_mw"]
    opex = cap_mw * 1000.0 * p["opex_per_kw_year"]
    mwh = annual_yield_mwh(cap_mw, pvout)
    return {
        "plant_capex": plant_capex,
        "connection_capex": conn,
        "opex_per_year": opex,
        "mwh_per_year": mwh,
        "lcoe": lcoe(plant_capex + conn, opex, mwh, p["discount_rate"], p["lifetime_years"],
                     p.get("degradation", 0.0)),
    }
