import io
import json
import os
import shutil
import subprocess
import zipfile
from typing import BinaryIO

from defusedxml import ElementTree as ET

_KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
_GX_NAMESPACE = "http://www.google.com/kml/ext/2.2"


def _warp_creation_options(jpeg_quality: int = 50) -> list[str]:
    return [
        "TILED=YES",
        "COMPRESS=JPEG",
        f"JPEG_QUALITY={jpeg_quality}",
        "BIGTIFF=IF_SAFER",
        "BLOCKXSIZE=512",
        "BLOCKYSIZE=512",
    ]


def _require_gdal_cli() -> None:
    if shutil.which("gdal_translate") is None or shutil.which("gdalwarp") is None:
        raise RuntimeError(
            "GeoTIFF export requires GDAL command-line tools "
            "(gdal_translate and gdalwarp).",
        )


def _kml_tag(namespace: str, tag_name: str) -> str:
    return f"{{{namespace}}}{tag_name}"


def _extract_kmz_to_directory(kmz_source: str | BinaryIO, tmp_dir: str) -> str:
    if isinstance(kmz_source, (str, os.PathLike)):
        kmz_path = os.fspath(kmz_source)
        with zipfile.ZipFile(kmz_path, "r") as archive:
            archive.extractall(tmp_dir)
    else:
        if hasattr(kmz_source, "seek"):
            kmz_source.seek(0)
        with zipfile.ZipFile(kmz_source, "r") as archive:
            archive.extractall(tmp_dir)
    return tmp_dir


def _find_kml_path(extracted_dir: str) -> str:
    kml_files = [
        name
        for name in os.listdir(extracted_dir)
        if name.lower().endswith(".kml")
    ]
    if not kml_files:
        raise ValueError("KMZ does not contain a KML file.")
    return os.path.join(extracted_dir, kml_files[0])


def _parse_ground_overlay(kml_path: str) -> tuple[list[tuple[float, float]], str]:
    tree = ET.parse(kml_path)
    root = tree.getroot()

    latlon_quad = root.find(
        f".//{_kml_tag(_GX_NAMESPACE, 'LatLonQuad')}/"
        f"{_kml_tag(_KML_NAMESPACE, 'coordinates')}",
    )
    if latlon_quad is None or not (latlon_quad.text or "").strip():
        raise ValueError("KMZ does not contain a gx:LatLonQuad with coordinates.")

    coords = [
        tuple(map(float, part.split(",")))
        for part in latlon_quad.text.strip().split()
    ]
    if len(coords) != 4:
        raise ValueError("LatLonQuad must contain exactly four coordinate pairs.")

    ground_overlay = root.find(f".//{_kml_tag(_KML_NAMESPACE, 'GroundOverlay')}")
    if ground_overlay is None:
        raise ValueError("KMZ does not contain a GroundOverlay element.")

    icon = ground_overlay.find(
        f"{_kml_tag(_KML_NAMESPACE, 'Icon')}/{_kml_tag(_KML_NAMESPACE, 'href')}",
    )
    if icon is None or not (icon.text or "").strip():
        raise ValueError("GroundOverlay is missing an Icon href.")

    return coords, icon.text.strip()


def _resolve_overlay_image_path(extracted_dir: str, href: str) -> str:
    image_path = os.path.join(extracted_dir, href.replace("/", os.sep))
    if not os.path.exists(image_path):
        raise ValueError(f"GroundOverlay image file not found: {href}")
    return image_path


def _image_size(image_path: str) -> tuple[int, int]:
    result = subprocess.run(
        ["gdalinfo", "-json", image_path],
        check=True,
        capture_output=True,
        text=True,
    )
    info = json.loads(result.stdout)
    width, height = info["size"]
    return int(width), int(height)


def kmz_has_ground_overlay(kmz_source: str | BinaryIO) -> bool:
    """Return True when a KMZ contains a georeferenced GroundOverlay image."""
    try:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp_dir:
            extracted_dir = _extract_kmz_to_directory(kmz_source, tmp_dir)
            kml_path = _find_kml_path(extracted_dir)
            _parse_ground_overlay(kml_path)
        return True
    except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError, subprocess.CalledProcessError):
        return False


def convert_kmz_ground_overlay_to_geotiff(
    kmz_source: str | BinaryIO,
    output_path: str,
    dst_srs: str = "EPSG:4326",
    jpeg_quality: int = 50,
) -> None:
    """Convert a KMZ GroundOverlay image to a tiled, compressed GeoTIFF."""
    if jpeg_quality < 1 or jpeg_quality > 100:
        raise ValueError("JPEG quality must be between 1 and 100.")

    _require_gdal_cli()

    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp_dir:
        extracted_dir = _extract_kmz_to_directory(kmz_source, tmp_dir)
        kml_path = _find_kml_path(extracted_dir)
        coords, image_href = _parse_ground_overlay(kml_path)
        image_path = _resolve_overlay_image_path(extracted_dir, image_href)
        width, height = _image_size(image_path)

        gcp_pixels_lines = [
            (0, height),
            (width, height),
            (width, 0),
            (0, 0),
        ]
        gcp_args: list[str] = []
        for (lon, lat, *_rest), (pixel, line) in zip(coords, gcp_pixels_lines):
            gcp_args.extend(["-gcp", str(pixel), str(line), str(lon), str(lat), "0"])

        tmp_tif = os.path.join(tmp_dir, "with_gcps.tif")
        translate_cmd = [
            "gdal_translate",
            "-of",
            "GTiff",
            "-a_srs",
            dst_srs,
            *gcp_args,
            image_path,
            tmp_tif,
        ]
        subprocess.run(translate_cmd, check=True, capture_output=True, text=True)

        warp_options = _warp_creation_options(jpeg_quality)
        warp_cmd = [
            "gdalwarp",
            "-tps",
            "-t_srs",
            dst_srs,
            *[
                item
                for option in warp_options
                for item in ("-co", option)
            ],
            tmp_tif,
            output_path,
        ]
        subprocess.run(warp_cmd, check=True, capture_output=True, text=True)
