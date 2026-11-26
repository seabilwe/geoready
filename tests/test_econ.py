import numpy as np
import pytest

from geoready import econ


def test_capacity_and_yield_by_hand():
    cap = econ.capacity_mw(10.0, 30.0)
    assert cap == pytest.approx(300.0)
    # 300 MW x 2,000 kWh/kWp = 600,000 MWh
    assert econ.annual_yield_mwh(cap, 2000.0) == pytest.approx(600_000.0)


def test_lcoe_zero_rate_is_simple_average():
    # r = 0, no degradation: (capex + n*opex) / (n*E)
    v = econ.lcoe(capex=1_000.0, opex_per_year=10.0, first_year_mwh=100.0, rate=0.0, lifetime=10)
    assert v == pytest.approx((1000 + 100) / 1000)


def test_lcoe_matches_annuity_formula():
    r, n = 0.08, 25
    crf = r * (1 + r) ** n / ((1 + r) ** n - 1)
    v = econ.lcoe(1e6, 2e4, 5e3, r, n)
    assert v == pytest.approx((1e6 * crf + 2e4) / 5e3, rel=1e-12)


def test_degradation_raises_lcoe():
    a = econ.lcoe(1e6, 0, 5e3, 0.08, 25, 0.0)
    b = econ.lcoe(1e6, 0, 5e3, 0.08, 25, 0.005)
    assert b > a


def test_zero_output_is_nan_not_zero():
    assert np.isnan(econ.lcoe(1e6, 0, 0.0, 0.08, 25))


def test_connection_cost():
    assert econ.connection_cost(10, 2.0, 5.0, route_factor=1.5) == pytest.approx(35.0)


def test_zone_costs_cases():
    e = {"capex_per_kw": {"low": 8000, "base": 10000, "high": 12000},
         "opex_per_kw_year": 150, "line_cost_per_km": 5e6, "connection_fixed_cost": 5e7,
         "route_factor": 1.2, "project_mw": 100, "discount_rate": 0.08, "lifetime_years": 25, "degradation": 0.005}
    lo = econ.zone_costs([100.0], [2100.0], [5.0], e, "low")["lcoe"][0]
    hi = econ.zone_costs([100.0], [2100.0], [5.0], e, "high")["lcoe"][0]
    assert lo < hi


def test_connection_scales_with_projects():
    e = {"capex_per_kw": 10000, "opex_per_kw_year": 0, "line_cost_per_km": 1e6,
         "connection_fixed_cost": 1e7, "route_factor": 1.0, "project_mw": 100,
         "discount_rate": 0.08, "lifetime_years": 25}
    r = econ.zone_costs([300.0], [2000.0], [10.0], e)
    # 3 projects x (10 km x R1m + R10m)
    assert r["connection_capex"][0] == pytest.approx(3 * 2e7)
