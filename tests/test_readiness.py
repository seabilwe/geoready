import numpy as np
import pandas as pd
import pytest

from geoready.readiness import normalise, readiness_class, score

CRIT = {
    "resource": {"column": "pvout", "weight": 0.5, "lo": 1800, "hi": 2200},
    "cost": {"column": "lcoe", "weight": 0.5, "lo": 400, "hi": 800, "higher_is_better": False},
}


def test_normalise_bounds_and_direction():
    assert list(normalise([1800, 2000, 2400], 1800, 2200)) == [0.0, 0.5, 1.0]
    assert list(normalise([400, 600], 400, 800, higher_is_better=False)) == [1.0, 0.5]


def test_score_by_hand():
    z = pd.DataFrame({"pvout": [2000.0], "lcoe": [500.0]})
    s = score(z, CRIT)
    assert s["readiness"].iloc[0] == pytest.approx(0.5 * 0.5 + 0.5 * 0.75)


def test_missing_is_unknown_not_low():
    z = pd.DataFrame({"pvout": [2000.0, np.nan], "lcoe": [500.0, 500.0]})
    s = score(z, CRIT)
    assert np.isnan(s["readiness"].iloc[1])
    assert s["missing"].iloc[1] == "resource"
    assert list(readiness_class(s["readiness"]))[1] == "Unknown"


def test_weights_must_sum_to_one():
    bad = {k: dict(v, weight=0.4) for k, v in CRIT.items()}
    with pytest.raises(ValueError):
        score(pd.DataFrame({"pvout": [2000.0], "lcoe": [500.0]}), bad)


def test_fixed_bounds_make_scores_comparable_across_scenarios():
    a = score(pd.DataFrame({"pvout": [2000.0], "lcoe": [500.0]}), CRIT)["readiness"].iloc[0]
    b = score(pd.DataFrame({"pvout": [2000.0, 2100.0], "lcoe": [500.0, 450.0]}), CRIT)["readiness"].iloc[0]
    assert a == b
