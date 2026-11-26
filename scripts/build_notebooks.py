"""Write the GeoReady notebooks from this file, so their code stays reviewable
as plain Python. Run: python scripts/build_notebooks.py"""
from pathlib import Path

import nbformat as nbf

SETUP = '''import os, sys
from pathlib import Path
def _root():  # the geoready folder: from GEOREADY_ROOT, the working folder, or the QGIS Notebook plugin
    if os.environ.get("GEOREADY_ROOT"):
        return Path(os.environ["GEOREADY_ROOT"])
    starts = [Path.cwd()]
    try:
        from qgis.PyQt.QtCore import QSettings
        starts.append(Path(QSettings().value("QGISNotebook/last_directory", "") or "."))
    except ImportError:
        pass
    return next((p for s in starts for p in [s, *s.parents] if (p / "src" / "geoready").exists()), None)
ROOT = _root()
assert ROOT, "Open this notebook from inside the geoready folder, or set GEOREADY_ROOT"
os.chdir(ROOT); sys.path.insert(0, str(ROOT / "src"))
if "qgis" in sys.modules:          # inside QGIS: draw figures off-screen
    import matplotlib; matplotlib.use("Agg")
from geoready.nb import show
CONFIG = "config/northern_cape_pv.yaml"'''


def md(s):
    return nbf.v4.new_markdown_cell(s.strip())


def code(s):
    return nbf.v4.new_code_cell(s.strip())


NB = {}

NB["00_run_record"] = [
    md("""
# GeoReady 00 · Run record

GeoReady screens land for utility-scale solar PV and asks what stands between good sun and a
connectable project: eligible land, capacity, indicative cost, grid headroom and permitting.
This pilot covers the **Northern Cape**.

Every run gets a record (Implementation Guide p.3): a `run_id`, the model version, the
parameter file, checksums of every input, the software versions, timestamps, the QA report and
a manifest of outputs. Notebooks 01–04 write into `runs/<run_id>/`.

**What this model must not claim.** A readiness score is not an environmental authorisation,
land entitlement, engineering design or bankable feasibility study. Costs are indicative.
Grid headroom comes from a dated public assessment (NTCSA GCCA 2025) and is not a connection offer.
"""),
    code(SETUP),
    code('''from geoready.run import Run
import pandas as pd
run = Run(CONFIG)
print("run_id:", run.run_id)
show(pd.DataFrame(run.inputs).T)'''),
    md("""
## Parameters

All thresholds and assumptions live in the YAML file, with a source beside each value.
Change the file, rerun the notebooks, and the run id changes with it.
"""),
    code('''import yaml
print(yaml.safe_dump({k: run.cfg[k] for k in ["eligibility", "zones", "capacity"]}, sort_keys=False))'''),
]

NB["01_eligibility_zones"] = [
    md("""
# GeoReady 01 · Eligible land and candidate zones

1. Load the prepared 250 m grids.
2. Give every cell an exclusion reason. **Protected areas are a legal prohibition** and always win;
   land cover, slope, weak resource and distance to a substation are **editable technical
   thresholds**, reported separately so none is silently treated as law. A missing input is
   coded *unknown*, never *eligible*.
3. Cut eligible land into 10 km squares that never cross a GCCA substation zone, and keep
   pieces of at least 25 km² as candidate zones.
"""),
    code(SETUP),
    code('''import numpy as np, pandas as pd
from geoready.run import Run
from geoready import zones, plots
run = Run(CONFIG); cfg = run.cfg
g, profile = zones.load_grids(cfg)
# Legal exclusion from the polygons, every touched cell
g["protected"] = zones.rasterize_mask(cfg["vectors"], cfg["protected_layer"], profile).astype("float32")
cell_km2 = (profile["transform"].a / 1000) ** 2
code = zones.eligibility(g, cfg)'''),
    code('''summary = pd.DataFrame({"reason": zones.CODES}).assign(
    km2=[float((code == c).sum() * cell_km2) for c in zones.CODES])
summary["share"] = summary["km2"] / summary["km2"].sum()
show(summary.round({"km2": 0, "share": 3}))'''),
    code('''import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(7, 7))
plots.eligibility_map(code, profile, zones.CODES, ax=ax)
show(fig, save_as=run.path("eligibility_map.png"))'''),
    code('''lab = zones.zone_ids(code == 0, g["gcca_zone"], profile["transform"], cfg["zones"]["size_km"])
table, zone_grid = zones.zone_table(lab, g, cell_km2, cfg["zones"]["min_eligible_km2"])
print(len(table), "zones,", round(table["eligible_km2"].sum()), "km² of eligible land in zones")
show(table.describe().T[["min", "50%", "max"]].round(2))'''),
    md("Save the exclusion grid, the zone grid and the zone table for the next notebooks."),
    code('''import rasterio
p = profile.copy(); p.update(dtype="float32", nodata=-9999, compress="deflate")
with rasterio.open(run.path("eligibility.tif"), "w", **p) as ds:
    ds.write(np.where(np.isnan(code), -9999, code).astype("float32"), 1)
p.update(dtype="int32", nodata=0)
with rasterio.open(run.path("zone_id.tif"), "w", **p) as ds:
    ds.write(zone_grid.astype("int32"), 1)
p.update(dtype="uint8", nodata=None)
with rasterio.open(run.path("protected_mask.tif"), "w", **p) as ds:
    ds.write(g["protected"].astype("uint8"), 1)
fp = zones.footprints(zone_grid, profile["transform"], profile["crs"], list(table["zone_id"]))
fp.to_file(run.path("zones_footprint.gpkg"), layer="zones", driver="GPKG")
table.to_csv(run.path("zones_stage1.csv"), index=False)
summary.to_csv(run.path("eligibility_summary.csv"), index=False)'''),
]

NB["02_capacity_cost"] = [
    md("""
# GeoReady 02 · Capacity and indicative cost

* **Technical capacity (MW)** = eligible km² × 87 MWdc/km² (fixed-tilt median, Bolinger & Bolinger 2022)
  × a land-use factor (the share of eligible land that could realistically be fenced; base 10%).
* **Annual yield (MWh)** = MW × PVOUT (Global Solar Atlas, which already includes system losses).
* **Connection cost** = per project (line length × route factor × R/km + on-site station and feeder bay),
  times the number of projects the zone could hold.
* **LCOE** = (CAPEX + present value of O&M) ÷ present value of output, real 2025 rand,
  for low, base and high cost cases.

The cost cases bundle optimistic or pessimistic values of every assumption; they are not
probabilities.
"""),
    code(SETUP),
    code('''import pandas as pd
from geoready.run import Run
from geoready import econ
run = Run(CONFIG); cfg = run.cfg
z = pd.read_csv(run.path("zones_stage1.csv"))
cap = cfg["capacity"]
z["capacity_mw"] = econ.capacity_mw(z["eligible_km2"], cap["density_mwdc_per_km2"] * cap["land_use_factor"]["base"])
for case in ("low", "base", "high"):
    r = econ.zone_costs(z["capacity_mw"], z["pvout"], z["grid_km"], cfg["economics"], case)
    z[f"lcoe_{case}"] = r["lcoe"]
    if case == "base":
        z["mwh_per_year"] = r["mwh_per_year"]
        z["connection_share"] = r["connection_capex"] / (r["plant_capex"] + r["connection_capex"])
show(z[["capacity_mw", "mwh_per_year", "connection_share", "lcoe_low", "lcoe_base", "lcoe_high"]].describe().round(2))'''),
    md("""
### Check against recent prices

REIPPPP Bid Window 7 solar PV preferred bidders were priced at about R500–514/MWh (July 2025).
The model's **low** case lands near those bids; the **base** case is well above them, because it
uses fixed-tilt yield (most new plants track the sun), a public-sector discount rate and
conservative CAPEX. Read the cost axis as relative: which zones are cheaper than others is more
robust than the rand level.
"""),
    code('''band = cfg["economics"]["reference_bids_r_per_mwh"]
show(pd.Series({f"{c} case, median R/MWh": round(z[f"lcoe_{c}"].median()) for c in ("low", "base", "high")}
               | {"BW7 bids, R/MWh": f"{band[0]}-{band[1]}"}))'''),
    code('''z.to_csv(run.path("zones_stage2.csv"), index=False)'''),
]

NB["03_grid_readiness"] = [
    md("""
# GeoReady 03 · Grid headroom, supply curves and readiness

Each zone sits behind three nested NTCSA GCCA 2025 limits: its **substation**, its **local area**
and its **supply area**. Limits are shared, so capacity is allocated cheapest-first and the
same MW are never counted twice (tests/test_allocate.py checks this against a linear programme).
Unknown headroom is not treated as available.

Three scenarios:

| scenario | limits applied |
|---|---|
| GCCA 2025 as published | substation, local area and supply area |
| Upstream strengthened | substation only, as if the backbone were reinforced |
| Technical potential | none |

Limits are shared with projects outside the province, which are not modelled, so every
allocation here is an upper bound.
"""),
    code(SETUP),
    code('''import pandas as pd
from geoready.run import Run
from geoready import grid, allocate as al, readiness, plots
run = Run(CONFIG); cfg = run.cfg
z = pd.read_csv(run.path("zones_stage2.csv"))
z = grid.attach_limits(z, grid.read_gcca(cfg["vectors"]))
scen = cfg["grid"]["scenarios"]
res = grid.run_scenarios(z, scen, unknown=cfg["grid"]["unknown_policy"])
show(pd.DataFrame({sid: {"connectable MW": round(a["alloc_mw"].sum()),
                    "zones with MW": int((a["alloc_mw"] > 0).sum()),
                    "zones behind unknown limits": int((a["grid_status"] == "unknown").sum())}
              for sid, a in res.items()}).T)'''),
    md("What stops each zone under the published limits:"),
    code('''show(res["published"]["binding"].value_counts().head(12))'''),
    code('''curves = {sid: al.supply_curve(a, cost_col="lcoe_base") for sid, a in res.items()}
fig = plots.supply_curves(curves, cfg["economics"]["reference_bids_r_per_mwh"],
                          {k: v["label"] for k, v in scen.items()})
fig.savefig(run.path("supply_curves.png"), dpi=160, bbox_inches="tight")
show(fig, save_as=run.path("supply_curves.png"))'''),
    md("""
### Readiness

A weighted sum of five criteria, each normalised to 0–1 with **fixed bounds** from the config,
so a score means the same in every scenario. Grid headroom is the share of a zone's technical
capacity that the scenario lets it connect; under the published GCCA it is zero everywhere.
"""),
    code('''crit = cfg["readiness"]
scored = {sid: readiness.score(a, crit) for sid, a in res.items()}
show(pd.DataFrame({sid: s["readiness"].describe()[["min", "50%", "max"]] for sid, s in scored.items()}).T.round(3))'''),
    md("### Sensitivity: does the top of the list survive other weights?"),
    code('''import numpy as np
base = scored["strengthened"].set_index("zone_id")["readiness"]
top = set(base.nlargest(50).index)
alts = {"resource-led": dict(resource=.4, cost=.2, grid_access=.1, grid_headroom=.2, permitting=.1),
        "grid-led": dict(resource=.1, cost=.2, grid_access=.25, grid_headroom=.35, permitting=.1),
        "permitting-led": dict(resource=.15, cost=.2, grid_access=.1, grid_headroom=.2, permitting=.35)}
rows = {}
for name, w in alts.items():
    c2 = {k: dict(v, weight=w[k]) for k, v in crit.items()}
    s2 = readiness.score(res["strengthened"], c2).set_index("zone_id")["readiness"]
    rows[name] = {"top-50 overlap": len(top & set(s2.nlargest(50).index)) / 50,
                  "Spearman rho": round(base.rank().corr(s2.rank()), 3)}
sens = pd.DataFrame(rows).T
sens.to_csv(run.path("sensitivity.csv"))
show(sens)'''),
    code('''out = z.copy()
for sid, s in scored.items():
    out[f"alloc_mw_{sid}"] = s["alloc_mw"].values
    out[f"binding_{sid}"] = s["binding"].values
    out[f"readiness_{sid}"] = s["readiness"].values
    out[f"headroom_share_{sid}"] = s["headroom_share"].values
for n in crit:
    out[f"n_{n}"] = scored["strengthened"][f"n_{n}"].values   # criteria shown for the strengthened case
out.to_csv(run.path("zones_stage3.csv"), index=False)
for sid, c in curves.items():
    c.to_csv(run.path(f"supply_curve_{sid}.csv"), index=False)'''),
]

NB["04_qa_publish"] = [
    md("""
# GeoReady 04 · QA gate and outputs

The release gate from the Implementation Guide (p.5): zero mandatory-exclusion violations, grid
allocation within every known limit, unknown grid explicit, totals and units reconciling,
readiness weights summing to one, and the unit tests passing. Outputs are written only if the
gate passes.
"""),
    code(SETUP),
    code('''import numpy as np, pandas as pd, geopandas as gpd, rasterio
from geoready.run import Run
from geoready import qa, grid, zones, nb
run = Run(CONFIG); cfg = run.cfg
z = pd.read_csv(run.path("zones_stage3.csv"))
fp = gpd.read_file(run.path("zones_footprint.gpkg"), layer="zones")
gdf = fp.merge(z, on="zone_id", how="inner")
with rasterio.open(run.path("eligibility.tif")) as ds:
    code = ds.read(1)
with rasterio.open(run.path("protected_mask.tif")) as ds:
    prot = ds.read(1) == 1'''),
    code('''checks = []
# 1 mandatory exclusions, on the grid and on the polygons
n_bad = int(((code == 0) & prot).sum())
checks.append({"check": "mandatory exclusions (grid)", "passed": n_bad == 0, "detail": f"{n_bad} eligible cells touch protected areas"})
pa = gpd.read_file(cfg["vectors"], layer="protected").to_crs(gdf.crs)
pa = pa[pa.intersects(gdf.union_all().envelope)]
checks.append(qa.no_exclusion_violation(gdf, pa, tol_km2=0.01))
# 2 grid allocation, per scenario
chain = ["sub", "local", "supply"]
for sid, sc in cfg["grid"]["scenarios"].items():
    a = z.rename(columns={f"alloc_mw_{sid}": "alloc_mw"}).assign(grid_status="known", binding=z[f"binding_{sid}"])
    r = qa.allocation_within_limits(a, grid.limits_for(z, sc["use"]), chain)
    r["check"] += f" ({sid})"; checks.append(r)
# 3 unknown grid explicit
a = z.assign(alloc_mw=z["alloc_mw_published"], binding=z["binding_published"],
             grid_status=np.where(z["binding_published"].astype(str).str.startswith("unknown"), "unknown", "known"))
checks.append(qa.unknowns_explicit(a))
# 4 totals and units
cap = cfg["capacity"]
checks.append(qa.totals_reconcile(z, "eligible_km2", "capacity_mw", cap["density_mwdc_per_km2"] * cap["land_use_factor"]["base"]))
# 5 weights
checks.append(qa.weights_sum_to_one(cfg["readiness"]))
# 6 unit tests
checks.append(nb.run_tests("tests"))
report = qa.gate(checks)
show(pd.DataFrame(report["checks"]))'''),
    code('''assert report["passed"], "QA gate failed: outputs not written"
gpkg = run.path("geoready.gpkg")
gdf.to_file(gpkg, layer="zones", driver="GPKG")
run.add_output("geoready.gpkg", "candidate zones with capacity, cost, grid allocation and readiness by scenario")
z.to_csv(run.path("zones.csv"), index=False); run.add_output("zones.csv", "zone table (no geometry)")
for f in ["eligibility.tif", "supply_curve_published.csv", "supply_curve_strengthened.csv",
          "supply_curve_unconstrained.csv", "eligibility_summary.csv", "supply_curves.png"]:
    run.add_output(f)
# OSeMOSYS-style adapter table: capacity and cost bands by GCCA supply area
bands = pd.cut(z["lcoe_base"], [0, 775, 800, 825, 1e9], labels=["<775", "775-800", "800-825", ">825"])
adapter = (z.assign(band=bands).groupby(["supply_area", "band"], observed=True)
             .agg(tech_mw=("capacity_mw", "sum"), mw_strengthened=("alloc_mw_strengthened", "sum"),
                  mw_published=("alloc_mw_published", "sum"), lcoe_base_mean=("lcoe_base", "mean")).round(1).reset_index())
adapter.to_csv(run.path("adapter_regional_bands.csv"), index=False); run.add_output("adapter_regional_bands.csv")
record = run.finish(report)
print(run.run_id, "outputs:", list(record["outputs"]))'''),
    md("""
## Open the results in QGIS

In plain Jupyter the next cell does nothing. Run inside QGIS (for example with the
**QGIS Notebook** plugin) and it adds the zones and the eligibility grid to your map, styled.
"""),
    code('''from geoready import qgis
qgis.show(run.path("geoready.gpkg"), rasters=[run.path("eligibility.tif")])'''),
]

out = Path(__file__).resolve().parents[1] / "notebooks"
out.mkdir(exist_ok=True)
for name, cells in NB.items():
    nb = nbf.v4.new_notebook()
    nb.cells = cells
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nbf.write(nb, out / f"{name}.ipynb")
    print("wrote", name)
