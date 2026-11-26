import numpy as np
import pandas as pd
import pytest
from scipy.optimize import linprog

from geoready.allocate import allocate, supply_curve
from geoready import qa

CHAIN = ["sub", "local", "supply"]


def small_network():
    # Two substations in one local area in one supply area.
    zones = pd.DataFrame({
        "zone_id": ["a", "b", "c", "d"],
        "capacity_mw": [100.0, 80.0, 50.0, 60.0],
        "lcoe": [500.0, 450.0, 600.0, 400.0],
        "sub": ["S1", "S1", "S2", "S2"],
        "local": ["L", "L", "L", "L"],
        "supply": ["NC", "NC", "NC", "NC"],
    })
    return zones


def test_shared_substation_not_double_counted():
    z = small_network()
    out = allocate(z, {"S1": 120.0, "S2": 1000.0}, CHAIN)
    # b (450) first gets 80, then a gets the 40 left at S1
    assert out.set_index("zone_id").loc["b", "alloc_mw"] == 80
    assert out.set_index("zone_id").loc["a", "alloc_mw"] == 40
    assert out.loc[out["sub"] == "S1", "alloc_mw"].sum() == 120


def test_upper_level_binds():
    z = small_network()
    out = allocate(z, {"S1": 500.0, "S2": 500.0, "L": 100.0}, CHAIN)
    assert out["alloc_mw"].sum() == pytest.approx(100)
    # cheapest (d, 400) takes 60, then b (450) takes the remaining 40
    s = out.set_index("zone_id")["alloc_mw"]
    assert s["d"] == 60 and s["b"] == 40


def test_zero_supply_area_gives_zero():
    z = small_network()
    out = allocate(z, {"S1": 500.0, "S2": 500.0, "NC": 0.0}, CHAIN)
    assert out["alloc_mw"].sum() == 0
    assert (out["binding"] == "NC").all()


def test_unknown_headroom_not_available():
    z = small_network()
    out = allocate(z, {"S1": None, "S2": 500.0}, CHAIN)
    s = out.set_index("zone_id")
    assert s.loc["a", "alloc_mw"] == 0 and s.loc["a", "grid_status"] == "unknown"
    assert s.loc["d", "alloc_mw"] == 60
    assert qa.unknowns_explicit(out)["passed"]


def test_target_stops_early_cheapest_first():
    z = small_network()
    out = allocate(z, {}, CHAIN, target_mw=100)
    s = out.set_index("zone_id")["alloc_mw"]
    assert s["d"] == 60 and s["b"] == 40 and s["a"] == 0


def _lp(z, limits, target=None):
    n = len(z)
    A, b = [], []
    for col in CHAIN:
        for lid, idx in z.groupby(col).groups.items():
            if lid in limits:
                row = np.zeros(n)
                row[[z.index.get_loc(i) for i in idx]] = 1
                A.append(row)
                b.append(limits[lid])
    bounds = [(0, c) for c in z["capacity_mw"]]
    A = np.array(A) if A else None
    b = np.array(b) if b else None
    if target is None:
        r1 = linprog(-np.ones(n), A_ub=A, b_ub=b, bounds=bounds, method="highs")
        target = -r1.fun
    r2 = linprog(z["lcoe"].values, A_ub=A, b_ub=b, A_eq=np.ones((1, n)), b_eq=[target],
                 bounds=bounds, method="highs")
    return target, r2.fun


@pytest.mark.parametrize("seed", range(40))
def test_greedy_matches_linear_programme(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(5, 30))
    z = pd.DataFrame({
        "zone_id": [f"z{i}" for i in range(n)],
        "capacity_mw": rng.uniform(10, 300, n),
        "lcoe": rng.uniform(300, 900, n),
        "sub": [f"S{i}" for i in rng.integers(0, 6, n)],
    })
    z["local"] = z["sub"].map(lambda s: "L1" if int(s[1:]) < 3 else "L2")
    z["supply"] = "NC"
    limits = {f"S{i}": float(rng.uniform(0, 400)) for i in range(6)}
    limits["L1"] = float(rng.uniform(100, 700))
    limits["L2"] = float(rng.uniform(100, 700))
    if seed % 3 == 0:
        limits["NC"] = float(rng.uniform(100, 900))
    target = None if seed % 2 else float(rng.uniform(50, 400))
    out = allocate(z, limits, CHAIN, target_mw=target)
    total, cost = _lp(z, limits, target)
    if target is not None and out["alloc_mw"].sum() < target - 1e-6:
        # infeasible target: greedy must have reached the maximum instead
        total, cost = _lp(z, limits, None)
    assert out["alloc_mw"].sum() == pytest.approx(total, abs=1e-6)
    assert (out["alloc_mw"] * out["lcoe"]).sum() == pytest.approx(cost, rel=1e-9, abs=1e-6)
    assert qa.allocation_within_limits(out, limits, CHAIN)["passed"]


def test_supply_curve_steps():
    z = small_network()
    out = allocate(z, {}, CHAIN)
    sc = supply_curve(out)
    assert list(sc["zone_id"]) == ["d", "b", "a", "c"]
    assert sc["mw_to"].iloc[-1] == pytest.approx(290)
    assert (sc["mw_from"].iloc[1:].values == sc["mw_to"].iloc[:-1].values).all()
