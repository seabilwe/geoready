# Data

Nothing under `data/` is committed. Some sources forbid redistribution (WDPA)
or carry share-alike terms (OpenStreetMap), so each user downloads the raw
data and builds the prepared grids locally.

## 1. Download into `data/raw/`

| Folder | Source | Licence / terms |
|---|---|---|
| `boundaries/` | geoBoundaries ZAF ADM1–ADM3 (GeoJSON), geoboundaries.org | CC BY 4.0 |
| `solar/` | Global Solar Atlas 2.0, South Africa GIS data (LTAym yearly totals); unzip so `PVOUT.tif` is inside | CC BY 4.0, World Bank Group / Solargis |
| `dem/` | Copernicus DEM GLO-90 tiles covering 16–26°E, 24–34°S | Copernicus DEM licence |
| `sanlc_2022/` | DFFE South African National Land-Cover 2022 (`SA_NLC_2022_GEO.tif`) | DFFE terms |
| `wdpa/` | WDPA public shapefile (the `WDPA_*_Public_shp_*` folders), protectedplanet.net | non-commercial; no redistribution |
| `csir/` | DFFE/CSIR REDZ phase 1 and 2, power corridors, renewable energy EIA applications | DFFE terms |
| `gcca_2025/` | NTCSA Generation Connection Capacity Assessment 2025: `GCCA_2025_Results_Report.xlsx` and the `GCCA 2025 GIS` shapefiles | NTCSA, public |
| `osm/` | Overpass extracts as JSON: `substations`, `power_lines`, `roads`, `places` | ODbL, © OpenStreetMap contributors |

## 2. Prepare the 250 m grids (in QGIS)

```python
import os; os.environ["GEOREADY_PREP"] = r"C:\path\to\geoready"
exec(open(r"C:\path\to\geoready\scripts\prepare_inputs_qgis.py", encoding="utf-8").read())
prep_vectors()
prep_rasters(250)
```

This writes `data/prepared/*.tif` and `data/prepared/re_site_za.gpkg`, the
inputs named in `config/northern_cape_pv.yaml`. The preparation code is the
same as RE-SITE ZA's, so both projects share one analysis grid
(Albers equal-area centred on the Northern Cape, 250 m cells).

## 3. Run the notebooks

See the main README. Notebook 00 records a SHA-256 checksum of every prepared
input in `runs/<run_id>/run.json`, so a rerun on different data shows up.
