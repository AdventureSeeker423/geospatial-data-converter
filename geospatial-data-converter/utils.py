import io
import json
import math
import os
import zipfile
from html import escape
import geopandas as gpd
import pandas as pd
import topojson
from defusedxml import ElementTree as ET
from pyogrio.errors import DataLayerError

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely import wkt as shapely_wkt
from shapely.geometry import (
    LineString,
    LinearRing,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.polygon import orient
from tempfile import TemporaryDirectory
from typing import BinaryIO
from kml_tricks import load_ge_data
from geotiff_tricks import convert_kmz_ground_overlay_to_geotiff

output_format_dict = {
    "CSV": ("csv", "csv", "text/csv"),
    "KML": ("kml", "kml", "application/vnd.google-earth.kml+xml"),
    "GeoJSON": ("geojson", "geojson", "application/geo+json"),
    "TopoJSON": ("topojson", "topojson", "application/json"),
    "WKT": ("wkt", "wkt", "text/plain"),
    "EsriJSON": ("json", "json", "application/json"),
    "GPX": ("gpx", "gpx", "application/gpx+xml"),
    "GeoTIFF": ("tif", "tif", "image/tiff"),
    "ESRI Shapefile": ("shp", "zip", "application/zip"),  # must be zipped
    "OpenFileGDB": ("gdb", "zip", "application/zip"),  # must be zipped
}


_ESRI_GEOMETRY_TYPES = {
    "Point": "esriGeometryPoint",
    "MultiPoint": "esriGeometryMultipoint",
    "LineString": "esriGeometryPolyline",
    "MultiLineString": "esriGeometryPolyline",
    "Polygon": "esriGeometryPolygon",
    "MultiPolygon": "esriGeometryPolygon",
}

_ESRI_WKID_ALIASES = {
    102100: 3857,
    102113: 3857,
}

_KML_NAMESPACE = "http://www.opengis.net/kml/2.2"


def auto_utm_epsg_for_gdf(gdf: gpd.GeoDataFrame) -> int:
    """Pick an appropriate UTM zone EPSG code for a GeoDataFrame's centroid."""
    src = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    if len(src) == 0:
        raise ValueError("Auto UTM zone requires at least one non-empty geometry.")
    if src.crs is None:
        raise ValueError("Auto UTM zone requires a dataset with a known CRS.")
    if src.crs.to_epsg() != 4326:
        src = src.to_crs(4326)
    minx, miny, maxx, maxy = src.total_bounds
    if any(math.isnan(value) for value in (minx, miny, maxx, maxy)):
        raise ValueError("Auto UTM zone could not be computed from the dataset bounds.")
    lon = (minx + maxx) / 2.0
    lat = (miny + maxy) / 2.0
    zone = int((lon + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))
    return (32600 if lat >= 0 else 32700) + zone


def _resolve_esri_crs(spatial_reference: dict[str, object]) -> CRS | None:
    """Resolve ArcGIS spatial references, including common Esri WKID aliases."""
    candidates: list[str | int] = []
    for key in ("wkt", "latestWkt"):
        value = spatial_reference.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)

    for key in ("latestWkid", "wkid"):
        wkid = spatial_reference.get(key)
        if wkid in (None, ""):
            continue
        if isinstance(wkid, int):
            candidates.append(wkid)
            alias = _ESRI_WKID_ALIASES.get(wkid)
            if alias is not None:
                candidates.append(alias)
            candidates.append(f"ESRI:{wkid}")
        elif isinstance(wkid, str):
            candidates.append(wkid)
            candidates.append(f"ESRI:{wkid}")

    if not candidates:
        candidates.append(4326)

    for candidate in candidates:
        try:
            return CRS.from_user_input(candidate)
        except CRSError, TypeError, ValueError:
            continue
    return None


def _group_esri_rings(rings: list[list[tuple[float, float]]]) -> list[Polygon]:
    """Build polygons from Esri rings using orientation first, then containment."""
    shells: list[list[tuple[float, float]]] = []
    holes: list[list[tuple[float, float]]] = []
    for ring in rings:
        if len(ring) < 4:
            continue
        if LinearRing(ring).is_ccw:
            holes.append(ring)
        else:
            shells.append(ring)

    if not shells and holes:
        fallback_shell = max(holes, key=lambda ring: abs(Polygon(ring).area))
        shells.append(fallback_shell)
        holes = [ring for ring in holes if ring is not fallback_shell]

    polygons = []
    unassigned_holes = holes[:]
    for shell in shells:
        shell_polygon = Polygon(shell)
        shell_holes = []
        remaining_holes = []
        for hole in unassigned_holes:
            hole_polygon = Polygon(hole)
            if shell_polygon.covers(hole_polygon.representative_point()):
                shell_holes.append(hole)
            else:
                remaining_holes.append(hole)
        polygons.append(orient(Polygon(shell, shell_holes), sign=1.0))
        unassigned_holes = remaining_holes

    for ring in unassigned_holes:
        polygons.append(orient(Polygon(ring), sign=1.0))

    return polygons


def _shapely_to_esri_geometry(geom, sr: dict[str, object]) -> dict[str, object] | None:
    """Convert a shapely geometry to an Esri JSON geometry dict."""
    if geom is None:
        return None
    if isinstance(geom, Point):
        return {"x": geom.x, "y": geom.y, "spatialReference": sr}
    if isinstance(geom, MultiPoint):
        return {
            "points": [[pt.x, pt.y] for pt in geom.geoms],
            "spatialReference": sr,
        }
    if isinstance(geom, LineString):
        return {"paths": [list(map(list, geom.coords))], "spatialReference": sr}
    if isinstance(geom, MultiLineString):
        return {
            "paths": [list(map(list, line.coords)) for line in geom.geoms],
            "spatialReference": sr,
        }
    if isinstance(geom, Polygon):
        rings = [list(map(list, geom.exterior.coords))]
        rings.extend(list(map(list, ring.coords)) for ring in geom.interiors)
        return {"rings": rings, "spatialReference": sr}
    if isinstance(geom, MultiPolygon):
        rings = []
        for poly in geom.geoms:
            rings.append(list(map(list, poly.exterior.coords)))
            rings.extend(list(map(list, ring.coords)) for ring in poly.interiors)
        return {"rings": rings, "spatialReference": sr}
    raise ValueError(f"Unsupported geometry type for EsriJSON: {geom.geom_type}")


def gdf_to_esrijson(gdf: gpd.GeoDataFrame) -> str:
    """Serialize a GeoDataFrame to an Esri Feature JSON (FeatureSet) string."""
    wkid = None
    if gdf.crs is not None:
        try:
            wkid = gdf.crs.to_epsg()
        except Exception:
            wkid = None
    sr: dict[str, object] = {"wkid": wkid} if wkid else {"wkid": 4326}

    geom_type = None
    for g in gdf.geometry:
        if g is not None:
            geom_type = _ESRI_GEOMETRY_TYPES.get(g.geom_type)
            break

    features = []
    attrs_df = gdf.drop(columns=[gdf.geometry.name])
    for geom, (_, row) in zip(gdf.geometry, attrs_df.iterrows()):
        attributes: dict[str, object | None] = {}
        for col, val in row.items():
            if pd.isna(val):
                attributes[col] = None
            elif hasattr(val, "item"):
                attributes[col] = val.item()
            else:
                attributes[col] = val
        features.append(
            {
                "attributes": attributes,
                "geometry": _shapely_to_esri_geometry(geom, sr),
            },
        )

    feature_set = {
        "geometryType": geom_type,
        "spatialReference": sr,
        "features": features,
    }
    return json.dumps(feature_set, default=str)


def read_wkt_text(text: str) -> gpd.GeoDataFrame:
    """Parse WKT text (one geometry per line) into a GeoDataFrame.

    Blank lines and lines starting with '#' are ignored. The resulting
    GeoDataFrame uses EPSG:4326 as its CRS.
    """
    geometries = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        geometries.append(shapely_wkt.loads(stripped))
    return gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")


def read_wkt(file: BinaryIO) -> gpd.GeoDataFrame:
    """Read a WKT file and return a GeoDataFrame."""
    raw_content = file.read()
    if isinstance(raw_content, bytes):
        content = raw_content.decode("utf-8")
    else:
        content = raw_content
    return read_wkt_text(content)


def read_gpx(file_path: str) -> gpd.GeoDataFrame:
    """Read a GPX file, returning the first non-empty standard layer.

    GPX files can contain multiple layers (waypoints, routes, tracks,
    track_points, route_points). We try them in a sensible order and
    return whichever has features.
    """
    for layer in ("waypoints", "tracks", "routes", "track_points", "route_points"):
        try:
            gdf = gpd.read_file(file_path, layer=layer, engine="pyogrio")
        except DataLayerError:
            continue
        if len(gdf) > 0:
            return gdf
    # Fall back to driver default
    return gpd.read_file(file_path, engine="pyogrio")


def write_gpx(gdf: gpd.GeoDataFrame, out_path: str) -> None:
    """Write a GeoDataFrame to GPX, choosing a layer based on geometry type."""
    if len(gdf) == 0:
        raise ValueError("Cannot write an empty GeoDataFrame to GPX.")

    # GPX is strictly WGS 84.
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    geom_types = set(gdf.geometry.geom_type.dropna().unique())
    if geom_types <= {"Point"}:
        layer = "waypoints"
    elif geom_types <= {"LineString", "MultiLineString"}:
        layer = "tracks"
    else:
        raise ValueError(
            "GPX only supports Point or LineString/MultiLineString geometries; "
            f"got {sorted(geom_types)}.",
        )

    # GPX has a fixed schema (ele, time, name, cmt, desc, sym, type, ...).
    # Dropping fields outside that schema is the most reliable way to
    # produce a valid GPX file across GDAL versions; otherwise the driver
    # errors on unknown fields. Preserve 'name' since it's the primary
    # waypoint/track label users expect to see.
    _GPX_STANDARD_FIELDS = {
        "ele",
        "time",
        "magvar",
        "geoidheight",
        "name",
        "cmt",
        "desc",
        "src",
        "sym",
        "type",
        "fix",
        "sat",
        "hdop",
        "vdop",
        "pdop",
        "ageofdgpsdata",
        "dgpsid",
    }
    geom_col = gdf.geometry.name
    keep_cols = [
        c
        for c in gdf.columns
        if c == geom_col or str(c).lower() in _GPX_STANDARD_FIELDS
    ]
    gdf.loc[:, keep_cols].to_file(
        out_path,
        driver="GPX",
        engine="pyogrio",
        layer=layer,
    )


def _kml_tag(tag_name: str) -> str:
    return f"{{{_KML_NAMESPACE}}}{tag_name}"


def _stringify_kml_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if hasattr(value, "item"):
        value = value.item()
    return str(value)


def _kml_field_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_integer_dtype(series):
        return "int"
    if pd.api.types.is_float_dtype(series):
        return "double"
    return "string"


def _kml_description_table(attributes: dict[str, str]) -> str:
    rows = "".join(
        ("<tr>" f"<th>{escape(name)}</th>" f"<td>{escape(value)}</td>" "</tr>")
        for name, value in attributes.items()
    )
    return (
        '<table border="1" cellspacing="0" cellpadding="2">'
        "<tbody>"
        f"{rows}"
        "</tbody></table>"
    )


def write_kml(gdf: gpd.GeoDataFrame, out_path: str) -> None:
    gdf.to_file(out_path, driver="KML", engine="pyogrio")

    geometry_column = gdf.geometry.name
    attribute_columns = [column for column in gdf.columns if column != geometry_column]
    if not attribute_columns:
        return

    tree = ET.parse(out_path)
    root = tree.getroot()
    document = root.find(_kml_tag("Document"))
    if document is None:
        raise ValueError("Generated KML is missing a Document element.")

    schema = document.find(_kml_tag("Schema"))
    if schema is None:
        schema_name = os.path.splitext(os.path.basename(out_path))[0]
        schema = document.makeelement(
            _kml_tag("Schema"),
            {"name": schema_name, "id": schema_name},
        )
        document.append(schema)

    for child in list(schema):
        if child.tag == _kml_tag("SimpleField"):
            schema.remove(child)

    for column in attribute_columns:
        simple_field = schema.makeelement(
            _kml_tag("SimpleField"),
            {"name": str(column), "type": _kml_field_type(gdf[column])},
        )
        schema.append(simple_field)

    placemarks = root.findall(f".//{_kml_tag('Placemark')}")
    if len(placemarks) != len(gdf):
        raise ValueError(
            "Generated KML placemark count does not match the exported rows.",
        )

    for placemark, (_, row) in zip(
        placemarks,
        gdf.loc[:, attribute_columns].iterrows(),
    ):
        attributes = {
            str(column): _stringify_kml_value(value) for column, value in row.items()
        }

        description = placemark.find(_kml_tag("description"))
        if description is None:
            description = placemark.makeelement(_kml_tag("description"), {})
            placemark.append(description)
        description.text = _kml_description_table(attributes)

        extended_data = placemark.find(_kml_tag("ExtendedData"))
        if extended_data is None:
            extended_data = placemark.makeelement(_kml_tag("ExtendedData"), {})
            placemark.append(extended_data)
        for child in list(extended_data):
            extended_data.remove(child)

        schema_data = extended_data.makeelement(
            _kml_tag("SchemaData"),
            {"schemaUrl": f"#{schema.attrib.get('id', 'schema')}"},
        )
        extended_data.append(schema_data)
        for name, value in attributes.items():
            simple_data = schema_data.makeelement(
                _kml_tag("SimpleData"),
                {"name": name},
            )
            simple_data.text = value
            schema_data.append(simple_data)

    tree.write(out_path, encoding="utf-8", xml_declaration=True)


def _esri_geometry_to_shapely(geom: dict):
    """Convert an Esri JSON geometry dict to a shapely geometry."""
    if geom is None:
        return None
    if "x" in geom and "y" in geom:
        return Point(geom["x"], geom["y"])
    if "points" in geom:
        return MultiPoint(geom["points"])
    if "paths" in geom:
        paths = geom["paths"]
        if len(paths) == 1:
            return LineString(paths[0])
        return MultiLineString(paths)
    if "rings" in geom:
        rings = [[(pt[0], pt[1]) for pt in ring] for ring in geom["rings"]]
        polygons = _group_esri_rings(rings)
        if len(polygons) == 1:
            return polygons[0]
        return MultiPolygon(polygons)
    raise ValueError(f"Unrecognized Esri JSON geometry: {list(geom)}")


def read_esrijson(feature_set: dict) -> gpd.GeoDataFrame:
    """Convert a parsed Esri Feature JSON dict to a GeoDataFrame."""
    features = feature_set.get("features", [])
    sr = feature_set.get("spatialReference") or {}
    crs = _resolve_esri_crs(sr)

    records = []
    geometries = []
    for feat in features:
        records.append(feat.get("attributes") or {})
        geometries.append(_esri_geometry_to_shapely(feat.get("geometry")))

    return gpd.GeoDataFrame(records, geometry=geometries, crs=crs)


def read_file(file: BinaryIO, *args, **kwargs) -> gpd.GeoDataFrame:
    """Read a file and return a GeoDataFrame"""
    basename, ext = os.path.splitext(os.path.basename(file.name))
    ext = ext.lower().strip(".")
    if ext == "zip":
        with TemporaryDirectory() as tmp_dir:
            tmp_file_path = os.path.join(tmp_dir, f"{basename}.{ext}")
            with open(tmp_file_path, "wb") as tmp_file:
                tmp_file.write(file.read())
            return gpd.read_file(
                f"zip://{tmp_file_path}",
                *args,
                engine="pyogrio",
                **kwargs,
            )
    elif ext in ("kml", "kmz"):
        with TemporaryDirectory() as tmp_dir:
            tmp_file_path = os.path.join(tmp_dir, f"{basename}.{ext}")
            with open(tmp_file_path, "wb") as tmp_file:
                tmp_file.write(file.read())
            return load_ge_data(tmp_file_path)
    elif ext == "wkt":
        return read_wkt(file)
    elif ext == "gpx":
        with TemporaryDirectory() as tmp_dir:
            tmp_file_path = os.path.join(tmp_dir, f"{basename}.{ext}")
            with open(tmp_file_path, "wb") as tmp_file:
                tmp_file.write(file.read())
            return read_gpx(tmp_file_path)
    elif ext in ("json", "geojson"):
        # Handle both GeoJSON and Esri Feature JSON (as produced by ArcGIS REST).
        data = file.read()
        try:
            parsed = json.loads(data)
        except ValueError, TypeError:
            parsed = None
        if isinstance(parsed, dict) and (
            "features" in parsed
            and parsed.get("features")
            and isinstance(parsed["features"][0], dict)
            and "attributes" in parsed["features"][0]
        ):
            return read_esrijson(parsed)
        # Fall back to pyogrio for GeoJSON and other JSON-based formats.
        with TemporaryDirectory() as tmp_dir:
            tmp_file_path = os.path.join(tmp_dir, f"{basename}.{ext}")
            with open(tmp_file_path, "wb") as tmp_file:
                tmp_file.write(data)
            return gpd.read_file(
                tmp_file_path,
                *args,
                engine="pyogrio",
                **kwargs,
            )
    return gpd.read_file(file, *args, engine="pyogrio", **kwargs)


def zip_dir(directory: str) -> bytes:
    """Zip a directory and return the bytes"""
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(directory):
            for file in files:
                new_member = os.path.join(root, file)
                zipf.write(
                    new_member,
                    os.path.relpath(new_member, directory),
                )

    return zip_buffer.getvalue()


def convert(
    gdf: gpd.GeoDataFrame | None,
    output_name: str,
    output_format: str,
    *,
    kmz_overlay: bytes | None = None,
    dst_srs: str | None = None,
) -> bytes:
    """Convert a GeoDataFrame or KMZ GroundOverlay to the specified format."""
    if output_format == "GeoTIFF":
        if kmz_overlay is None:
            raise ValueError(
                "GeoTIFF export is supported for KMZ files that contain a "
                "GroundOverlay image with gx:LatLonQuad georeferencing.",
            )
        with TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, output_name)
            convert_kmz_ground_overlay_to_geotiff(
                io.BytesIO(kmz_overlay),
                out_path,
                dst_srs=dst_srs or "EPSG:4326",
            )
            with open(out_path, "rb") as geotiff_file:
                return geotiff_file.read()

    if gdf is None:
        raise ValueError("No vector data is available for conversion.")

    with TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, output_name)
        if output_format == "CSV":
            gdf.to_csv(out_path)
        elif output_format == "TopoJSON":
            topojson_data = topojson.Topology(gdf)
            topojson_data.to_json(out_path)
        elif output_format == "WKT":
            with open(out_path, "w", encoding="utf-8") as wkt_file:
                wkt_file.write(
                    "\n".join(
                        "" if geom is None else geom.wkt for geom in gdf.geometry
                    ),
                )
        elif output_format == "EsriJSON":
            with open(out_path, "w", encoding="utf-8") as esri_file:
                esri_file.write(gdf_to_esrijson(gdf))
        elif output_format == "GPX":
            write_gpx(gdf, out_path)
        elif output_format == "KML":
            write_kml(gdf, out_path)
        else:
            gdf.to_file(out_path, driver=output_format, engine="pyogrio")

        if output_format in ("ESRI Shapefile", "OpenFileGDB"):
            output_bytes = zip_dir(tmpdir)
        else:
            with open(out_path, "rb") as f:
                output_bytes = f.read()

        return output_bytes
