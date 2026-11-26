"""Figures used in the notebooks (matplotlib only)."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch

INK, MUTED, GRID = "#2B2A28", "#77736C", "#E4E0D8"
# Exclusion reasons: legal first, technical in muted earth tones, eligible in amber.
CODE_COLORS = {0: "#E3A857", 1: "#5E7A4F", 2: "#A99C88", 3: "#7C6A58", 4: "#C9C2B4", 5: "#E9E4DA", 9: "#B04A3C"}
# Readiness: one hue, light to dark.
READY = ["#F1E8D6", "#E2C79D", "#C99A64", "#A0673A", "#6B3F22"]   # same ramp as the web page


def _clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)


def eligibility_map(code, profile, labels, ax=None):
    ax = ax or plt.subplots(figsize=(7, 7))[1]
    keys = sorted(CODE_COLORS)
    cmap = ListedColormap([CODE_COLORS[k] for k in keys])
    norm = BoundaryNorm([k - 0.5 for k in keys] + [keys[-1] + 0.5], cmap.N)
    t = profile["transform"]
    ext = [t.c, t.c + t.a * profile["width"], t.f + t.e * profile["height"], t.f]
    ax.imshow(np.ma.masked_invalid(code), cmap=cmap, norm=norm, extent=ext, interpolation="nearest")
    ax.set_axis_off()
    ax.legend(handles=[Patch(color=CODE_COLORS[k], label=labels[k]) for k in keys if k in labels],
              loc="lower left", fontsize=7, frameon=False)
    return ax


def supply_curves(curves: dict, ref_band=None, titles=None):
    """Small multiples, one per scenario: each has its own MW axis."""
    fig, axes = plt.subplots(1, len(curves), figsize=(4.2 * len(curves), 3.4), sharey=True)
    for ax, (sid, sc) in zip(np.atleast_1d(axes), curves.items()):
        _clean(ax)
        scale, unit = (1000, "GW") if len(sc) and sc["mw_to"].max() > 20000 else (1, "MW")
        if ref_band:
            ax.axhspan(*ref_band, color=GRID, zorder=0)
        if len(sc) > 150:   # many thin steps: draw the outline, not the bars
            x = np.r_[sc["mw_from"].values, sc["mw_to"].values[-1]] / scale
            y = np.r_[sc["lcoe"].values, sc["lcoe"].values[-1]]
            ax.fill_between(x, y, step="post", color="#A0673A", linewidth=0)
            ax.set_xlim(0, x[-1] * 1.02)
        elif len(sc):
            ax.bar(sc["mw_from"] / scale, sc["lcoe"], width=sc["alloc_mw"] / scale, align="edge",
                   color="#A0673A", edgecolor="white", linewidth=0.6)
            ax.set_xlim(0, sc["mw_to"].max() / scale * 1.02)
        else:
            ax.text(0.5, 0.5, "0 MW connectable", transform=ax.transAxes, ha="center", va="center",
                    color=INK, fontsize=11)
            ax.set_xticks([])
        ax.set_title((titles or {}).get(sid, sid), fontsize=9, color=INK, loc="left")
        ax.set_xlabel(f"Cumulative capacity ({unit})", fontsize=8, color=MUTED)
    np.atleast_1d(axes)[0].set_ylabel("Indicative LCOE (R/MWh, base costs)", fontsize=8, color=MUTED)
    fig.tight_layout()
    return fig


def zone_map(gdf, column, ax=None, title=None, background=None):
    ax = ax or plt.subplots(figsize=(7, 7))[1]
    if background is not None:
        background.plot(ax=ax, color="#F4F1EA", edgecolor="#D8D2C6", linewidth=0.4)
    cmap = ListedColormap(READY)
    gdf.plot(ax=ax, column=column, cmap=cmap, vmin=0, vmax=1, linewidth=0,
             missing_kwds={"color": "#D9D4CB", "hatch": "///"})
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=9, color=INK, loc="left")
    return ax
