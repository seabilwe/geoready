"""Optional QGIS hook.

In plain Jupyter this does nothing and returns False. Inside QGIS (for
example the QGIS Notebook plugin, which runs notebooks with QGIS's own
Python) it adds the run's layers to the open project, styled, so the same
notebook doubles as a QGIS workflow. A .qml file in styles/ with the layer's
name replaces the built-in style.
"""
from __future__ import annotations

from pathlib import Path

READY = ["#F1E8D6", "#E2C79D", "#C99A64", "#A0673A", "#6B3F22"]   # same ramp as the web page
CODES = [(0, "#E3A857", "Eligible"), (1, "#5E7A4F", "Protected area (legal)"),
         (2, "#A99C88", "Incompatible land cover"), (3, "#7C6A58", "Too steep"),
         (4, "#C9C2B4", "Weak solar resource"), (5, "#E9E4DA", "Too far from a substation"),
         (9, "#B04A3C", "Unknown (input missing)")]


def in_qgis() -> bool:
    try:
        from qgis.utils import iface
        return iface is not None
    except Exception:
        return False


def _style_zones(lyr, field):
    from qgis.core import (QgsClassificationRange, QgsGraduatedSymbolRenderer, QgsRendererRange,
                           QgsSymbol)
    from qgis.PyQt.QtGui import QColor
    ranges = []
    for i, c in enumerate(READY):
        lo, hi = i / 5, (i + 1) / 5
        s = QgsSymbol.defaultSymbol(lyr.geometryType())
        s.setColor(QColor(c))
        s.symbolLayer(0).setStrokeStyle(0)  # no outline
        ranges.append(QgsRendererRange(QgsClassificationRange(f"{lo:.1f}-{hi:.1f}", lo, hi), s))
    lyr.setRenderer(QgsGraduatedSymbolRenderer(field, ranges))


def _style_codes(lyr):
    from qgis.core import QgsPalettedRasterRenderer
    from qgis.PyQt.QtGui import QColor
    classes = [QgsPalettedRasterRenderer.Class(v, QColor(c), lab) for v, c, lab in CODES]
    lyr.setRenderer(QgsPalettedRasterRenderer(lyr.dataProvider(), 1, classes))


def show(gpkg, layers=None, rasters=(), styles_dir="styles", group="GeoReady",
         field="readiness_strengthened") -> bool:
    """Add GeoPackage layers (and optional rasters) to the current QGIS project."""
    if not in_qgis():
        return False
    from osgeo import ogr
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
    from qgis.utils import iface

    gpkg = str(Path(gpkg).resolve())
    if layers is None:
        ds = ogr.Open(gpkg)
        layers = [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]
        ds = None
    proj = QgsProject.instance()
    root = proj.layerTreeRoot()
    grp = root.findGroup(group) or root.insertGroup(0, group)
    added = []
    for name in layers:
        lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
        if lyr.isValid():
            if name == "zones" and lyr.fields().indexOf(field) >= 0:
                _style_zones(lyr, field)
            added.append(lyr)
    for r in rasters:
        lyr = QgsRasterLayer(str(Path(r).resolve()), Path(r).stem)
        if lyr.isValid():
            if Path(r).stem == "eligibility":
                _style_codes(lyr)
            added.append(lyr)
    for lyr in added:
        qml = Path(styles_dir) / f"{lyr.name()}.qml"
        if qml.exists():
            lyr.loadNamedStyle(str(qml.resolve()))
        proj.addMapLayer(lyr, False)
        grp.addLayer(lyr)
    if added:
        iface.mapCanvas().setExtent(added[0].extent())
    iface.mapCanvas().refreshAllLayers()
    return True
