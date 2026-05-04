import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from defusedxml import ElementTree as ET
from shapely.geometry import Point, Polygon

from utils import (
    auto_utm_epsg_for_gdf,
    convert,
    output_format_dict,
    read_esrijson,
    read_file,
)

input_exts = ["kml", "kmz", "geojson", "json", "zip", "wkt", "gpx"]
output_exts = output_format_dict.keys()

# Pairs with fundamental format-level incompatibility (not bugs in the
# converter): GPX can't represent polygons, and TopoJSON's serializer
# doesn't handle the datetime fields GPX waypoints emit.
INCOMPATIBLE = {
    ("kml", "GPX"),  # test.kml contains polygons
    ("geojson", "GPX"),  # test.geojson contains polygons
    ("zip", "GPX"),  # test.zip is a shapefile of polygons
    ("gpx", "TopoJSON"),  # GPX waypoint datetime columns break topojson
}


@pytest.mark.parametrize("in_ext", input_exts)
@pytest.mark.parametrize("out_ext", output_exts)
def test_conversion(in_ext: str, out_ext: str, tmp_path: Path) -> None:
    if (in_ext, out_ext) in INCOMPATIBLE:
        pytest.skip(f"{in_ext} -> {out_ext} is a known format-level incompatibility")
    test_file_path = Path(__file__).parent / "test_data" / f"test.{in_ext}"
    with test_file_path.open("rb") as f:
        gdf = read_file(f)

    file_ext, dl_ext, _mimetype = output_format_dict[out_ext]
    output_name = f"test.{file_ext}"

    converted_data = convert(gdf, output_name, out_ext)

    assert isinstance(converted_data, (bytes, bytearray))
    assert len(converted_data) > 0

    artifact_path = tmp_path / f"test.{dl_ext}"
    artifact_path.write_bytes(converted_data)

    if out_ext in ("ESRI Shapefile", "OpenFileGDB"):
        assert zipfile.is_zipfile(io.BytesIO(converted_data))


def test_read_esrijson_maps_common_esri_wkids() -> None:
    gdf = read_esrijson(
        {
            "spatialReference": {"wkid": 102100},
            "features": [
                {
                    "attributes": {"id": 1},
                    "geometry": {"x": 0, "y": 0},
                },
            ],
        },
    )

    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 3857


def test_read_esrijson_respects_esri_ring_orientation() -> None:
    outer_ring = [(0, 0), (0, 4), (4, 4), (4, 0), (0, 0)]
    hole_ring = [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]

    gdf = read_esrijson(
        {
            "spatialReference": {"wkid": 4326},
            "features": [
                {
                    "attributes": {"id": 1},
                    "geometry": {"rings": [outer_ring, hole_ring]},
                },
            ],
        },
    )

    polygon = gdf.geometry.iloc[0]
    assert isinstance(polygon, Polygon)
    assert len(polygon.interiors) == 1
    assert polygon.area == pytest.approx(12.0)


def test_auto_utm_epsg_for_gdf_returns_expected_zone() -> None:
    gdf = gpd.GeoDataFrame(
        geometry=[Point(-122.33, 47.60)],
        crs="EPSG:4326",
    )

    assert auto_utm_epsg_for_gdf(gdf) == 32610


def test_auto_utm_epsg_for_gdf_rejects_empty_geometry_frames() -> None:
    gdf = gpd.GeoDataFrame(geometry=[None], crs="EPSG:4326")

    with pytest.raises(ValueError, match="at least one non-empty geometry"):
        auto_utm_epsg_for_gdf(gdf)


def test_kml_conversion_preserves_all_attributes() -> None:
    gdf = gpd.GeoDataFrame(
        [
            {
                "alpha": "A",
                "beta": "B",
                "gamma": 3,
                "geometry": Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
            },
        ],
        crs="EPSG:4326",
    )

    converted = convert(gdf, "issue54.kml", "KML")
    root = ET.fromstring(converted)
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}

    simple_fields = {
        field.attrib["name"] for field in root.findall(".//kml:SimpleField", namespace)
    }
    assert simple_fields == {"alpha", "beta", "gamma"}

    simple_data = {
        field.attrib["name"]: field.text
        for field in root.findall(".//kml:SimpleData", namespace)
    }
    assert simple_data == {"alpha": "A", "beta": "B", "gamma": "3"}

    description = root.findtext(
        ".//kml:Placemark/kml:description",
        namespaces=namespace,
    )
    assert description is not None
    for token in ("alpha", "A", "beta", "B", "gamma", "3"):
        assert token in description


def test_exported_kml_round_trips_all_attributes(tmp_path: Path) -> None:
    original = gpd.GeoDataFrame(
        [
            {
                "alpha": "A",
                "beta": "B",
                "gamma": 3,
                "geometry": Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
            },
        ],
        crs="EPSG:4326",
    )

    output_path = tmp_path / "issue54.kml"
    output_path.write_bytes(convert(original, output_path.name, "KML"))

    with output_path.open("rb") as exported:
        reloaded = read_file(exported)

    assert reloaded.loc[0, "alpha"] == "A"
    assert reloaded.loc[0, "beta"] == "B"
    assert str(reloaded.loc[0, "gamma"]) == "3"


def test_kmz_numeric_attributes_round_trip_to_shapefile(tmp_path: Path) -> None:
    kmz_path = tmp_path / "numeric-fields.kmz"
    kmz_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\">
    <Document>
        <Schema id=\"parcel\">
            <SimpleField name=\"acreage\" type=\"double\"/>
            <SimpleField name=\"unit_count\" type=\"int\"/>
            <SimpleField name=\"label\" type=\"string\"/>
        </Schema>
        <Placemark>
            <name>parcel-a</name>
            <ExtendedData>
                <SchemaData schemaUrl=\"#parcel\">
                    <SimpleData name=\"acreage\">12.5</SimpleData>
                    <SimpleData name=\"unit_count\">3</SimpleData>
                    <SimpleData name=\"label\">north</SimpleData>
                </SchemaData>
            </ExtendedData>
            <Point><coordinates>-122.33,47.60,0</coordinates></Point>
        </Placemark>
    </Document>
</kml>
"""

    with zipfile.ZipFile(kmz_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kmz_xml)

    with kmz_path.open("rb") as uploaded:
        loaded = read_file(uploaded)

    assert loaded.loc[0, "label"] == "north"
    assert pd.api.types.is_float_dtype(loaded["acreage"])
    assert pd.api.types.is_integer_dtype(loaded["unit_count"])
    assert loaded.loc[0, "acreage"] == pytest.approx(12.5)
    assert loaded.loc[0, "unit_count"] == 3

    converted = convert(loaded, "numeric-fields.shp", "ESRI Shapefile")
    extracted_dir = tmp_path / "shapefile"
    extracted_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(converted)) as archive:
        archive.extractall(extracted_dir)

    shapefile = next(extracted_dir.glob("*.shp"))
    round_tripped = gpd.read_file(shapefile, engine="pyogrio")

    assert round_tripped.loc[0, "label"] == "north"
    assert pd.api.types.is_float_dtype(round_tripped["acreage"])
    assert pd.api.types.is_integer_dtype(round_tripped["unit_count"])
    assert round_tripped.loc[0, "acreage"] == pytest.approx(12.5)
    assert round_tripped.loc[0, "unit_count"] == 3
