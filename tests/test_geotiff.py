import base64
import shutil
import zipfile
from pathlib import Path

import pytest

from geotiff_tricks import (
    convert_kmz_ground_overlay_to_geotiff,
    kmz_has_ground_overlay,
)
from utils import convert, output_format_dict

_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABPmXlYAAAAE0lEQVR42mP8z8BQz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC",
)

_GROUND_OVERLAY_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <GroundOverlay>
      <Icon>
        <href>files/overlay.png</href>
      </Icon>
      <gx:LatLonQuad>
        <coordinates>
          -122.42,37.80,0 -122.40,37.80,0 -122.40,37.82,0 -122.42,37.82,0
        </coordinates>
      </gx:LatLonQuad>
    </GroundOverlay>
  </Document>
</kml>
"""


def _build_overlay_kmz(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", _GROUND_OVERLAY_KML)
        archive.writestr("files/overlay.png", _MINIMAL_PNG)


@pytest.fixture
def overlay_kmz(tmp_path: Path) -> Path:
    kmz_path = tmp_path / "overlay.kmz"
    _build_overlay_kmz(kmz_path)
    return kmz_path


def test_kmz_has_ground_overlay_detects_overlay(overlay_kmz: Path) -> None:
    assert kmz_has_ground_overlay(overlay_kmz) is True


def test_kmz_has_ground_overlay_rejects_vector_kmz() -> None:
    vector_kmz = Path(__file__).parent / "test_data" / "test.kmz"
    assert kmz_has_ground_overlay(vector_kmz) is False


@pytest.mark.skipif(
    shutil.which("gdal_translate") is None,
    reason="GDAL command-line tools are required for GeoTIFF export",
)
def test_convert_kmz_ground_overlay_to_geotiff(
    overlay_kmz: Path,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "overlay.tif"
    convert_kmz_ground_overlay_to_geotiff(overlay_kmz, output_path)

    assert output_path.exists()
    assert output_path.stat().st_size > 0


@pytest.mark.skipif(
    shutil.which("gdal_translate") is None,
    reason="GDAL command-line tools are required for GeoTIFF export",
)
def test_utils_convert_geotiff_from_overlay_bytes(overlay_kmz: Path) -> None:
    kmz_bytes = overlay_kmz.read_bytes()
    file_ext, dl_ext, mimetype = output_format_dict["GeoTIFF"]

    converted = convert(
        gdf=None,
        output_name=f"overlay.{file_ext}",
        output_format="GeoTIFF",
        kmz_overlay=kmz_bytes,
        dst_srs="EPSG:4326",
    )

    assert isinstance(converted, (bytes, bytearray))
    assert len(converted) > 0
    assert mimetype == "image/tiff"
    assert dl_ext == "tif"


def test_utils_convert_geotiff_requires_overlay() -> None:
    with pytest.raises(ValueError, match="GroundOverlay"):
        convert(
            gdf=None,
            output_name="missing.tif",
            output_format="GeoTIFF",
        )
