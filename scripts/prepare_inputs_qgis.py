"""
Input preparation for GeoReady (from RE-SITE ZA, same author, MIT licence).

Builds data/prepared/: the 250 m analysis grids and re_site_za.gpkg, from the
raw downloads listed in data/README.md. Runs inside QGIS (PyQGIS + GDAL):

    import os; os.environ["GEOREADY_PREP"] = r"<path to the geoready folder>"
    exec(open(r"<geoready>/scripts/prepare_inputs_qgis.py", encoding="utf-8").read())
    prep_vectors()        # vector layers into data/prepared/re_site_za.gpkg
    prep_rasters(250)     # 250 m grids into data/prepared/

The GeoReady notebooks themselves need only plain Python.
"""
import os, json, glob, math, time, collections
import numpy as np
from osgeo import gdal, ogr, osr
from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsFields, QgsField,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsVectorFileWriter,
                       QgsFeatureRequest, QgsSpatialIndex, QgsRectangle, QgsWkbTypes)
from qgis.PyQt.QtCore import QVariant

gdal.UseExceptions()
P = os.environ["GEOREADY_PREP"].replace("\\", "/")   # set this first (see above)
RAW, DATA = P + "/data/raw", P + "/data"
GPKG = DATA + "/prepared/re_site_za.gpkg"
WDPA = RAW + "/wdpa"   # WDPA_<Mon><Year>_Public_shp folder contents
PVOUT = glob.glob(RAW + "/solar/**/PVOUT.tif", recursive=True)
GHI = glob.glob(RAW + "/solar/**/GHI.tif", recursive=True)
NC_PROJ = ("+proj=aea +lat_0=-29 +lon_0=21.5 +lat_1=-25.5 +lat_2=-31.5 +x_0=0 +y_0=0 "
           "+datum=WGS84 +units=m +no_defs")
CRS = QgsCoordinateReferenceSystem.fromProj(NC_PROJ)
SRS = osr.SpatialReference(); SRS.ImportFromProj4(NC_PROJ)
SRS.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
WKT = SRS.ExportToWkt()
WGS = QgsCoordinateReferenceSystem("EPSG:4326")
PRJ = QgsProject.instance()
os.makedirs(DATA, exist_ok=True)

