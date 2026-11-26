"""Readiness score: weighted sum of criteria normalised to 0-1.

Normalisation bounds are fixed in the config, not taken from the data, so a
score means the same thing in every scenario and every run. A zone missing
any criterion gets no score (NaN), never a low one; the missing criteria are
listed so the gap stays visible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def normalise(values, lo, hi, higher_is_better=True):
    v = np.asarray(values, dtype=float)
    x = np.clip((v - lo) / (hi - lo), 0.0, 1.0)
    return x if higher_is_better else 1.0 - x


def score(zones: pd.DataFrame, criteria: dict) -> pd.DataFrame:
    """criteria: {name: {column, weight, lo, hi, higher_is_better}}.

    Adds n_<name> (0-1) per criterion, readiness (0-1 or NaN) and missing
    (comma-separated names).
    """
    w = np.array([c["weight"] for c in criteria.values()], dtype=float)
    if not np.isclose(w.sum(), 1.0):
        raise ValueError(f"readiness weights sum to {w.sum():.3f}, not 1")
    out = zones.copy()
    parts = []
    for name, c in criteria.items():
        col = f"n_{name}"
        out[col] = normalise(out[c["column"]], c["lo"], c["hi"], c.get("higher_is_better", True))
        parts.append(out[col] * c["weight"])
    total = sum(parts)
    ncols = [f"n_{n}" for n in criteria]
    miss = out[ncols].isna()
    out["missing"] = miss.apply(lambda r: ",".join(n[2:] for n, m in r.items() if m), axis=1)
    out["readiness"] = np.where(miss.any(axis=1), np.nan, total)
    return out


def readiness_class(r):
    """Five plain-language classes for maps; NaN stays 'Unknown'."""
    bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    labels = ["Very low", "Low", "Moderate", "High", "Very high"]
    c = pd.cut(pd.Series(r, dtype=float), bins=bins, labels=labels, right=False, include_lowest=True)
    return c.cat.add_categories("Unknown").fillna("Unknown")
