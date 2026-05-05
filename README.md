---
title: Geospatial Data Converter
emoji: 🌎
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: true
tags: [geospatial, streamlit, docker]
---

# Geospatial Data Converter

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![python](https://img.shields.io/badge/Python-3.14-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
![GitHub tag (with filter)](https://img.shields.io/github/v/tag/joshuasundance-swca/geospatial-data-converter)

[![Push to Docker Hub](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/docker-hub.yml/badge.svg)](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/docker-hub.yml)
[![CI](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/ci.yml/badge.svg)](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/ci.yml)
[![Release Assets](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/release-assets.yml/badge.svg)](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/release-assets.yml)
[![Docker Image Size (tag)](https://img.shields.io/docker/image-size/joshuasundance/geospatial-data-converter/latest)](https://hub.docker.com/r/joshuasundance/geospatial-data-converter)

[![Push to HuggingFace Space](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/hf-space.yml/badge.svg)](https://github.com/joshuasundance-swca/geospatial-data-converter/actions/workflows/hf-space.yml)
[![Open HuggingFace Space](https://huggingface.co/datasets/huggingface/badges/raw/main/open-in-hf-spaces-sm.svg)](https://huggingface.co/spaces/joshuasundance/geospatial-data-converter)

![Code Climate maintainability](https://img.shields.io/codeclimate/maintainability/joshuasundance-swca/geospatial-data-converter)
![Code Climate issues](https://img.shields.io/codeclimate/issues/joshuasundance-swca/geospatial-data-converter)
![Code Climate technical debt](https://img.shields.io/codeclimate/tech-debt/joshuasundance-swca/geospatial-data-converter)

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v1.json)](https://github.com/charliermarsh/ruff)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
![Known Vulnerabilities](https://snyk.io/test/github/joshuasundance-swca/geospatial-data-converter/badge.svg)

This project showcases a simple geospatial data converter using [Streamlit](https://streamlit.io) and [GeoPandas](https://geopandas.org/).

# Features

## Input sources
- **File upload** (single or batch) — KML, KMZ, GeoJSON, Esri Feature JSON (.json), WKT, GPX, ZIP (shapefile or file geodatabase)
- **ArcGIS feature layer URL** — fetches directly from ArcGIS REST services
- **Paste WKT** — paste Well-Known Text geometries straight from a database query or clipboard

## Output formats
CSV, KML, GeoJSON, TopoJSON, WKT, EsriJSON, GPX, ESRI Shapefile, OpenFileGDB

KML exports preserve every selected attribute in both Google Earth-visible
description tables and KML `ExtendedData`, so polygon metadata survives export
and round-trips cleanly when the file is reloaded.

KML and KMZ imports also preserve typed `SimpleData` fields from Google Earth
schemas, so numeric attributes stay numeric when exported to ESRI Shapefile or
OpenFileGDB.

## Export options
- **Reproject** to a target CRS before export (WGS 84, Web Mercator, NAD83, auto UTM zone, or any custom EPSG code)
- **Select columns** to include in the output (single-file mode)
- **Fix invalid geometries** (`make_valid()`) so self-intersecting polygons don't break downstream tools

## Preview
- Interactive **map preview** with full polygon/line/point rendering (pydeck) and hover tooltips showing attribute values
- **Attribute table** with geometry omitted for display purposes
- Summary **metrics** (feature count, attribute count, CRS, geometry types)

## Batch mode
Upload multiple files at once, convert them all with shared settings, and download a single ZIP

# Deployment
`geospatial-data-converter` is deployed as a [Docker image](https://hub.docker.com/r/joshuasundance/geospatial-data-converter) based on the `python:3.14-slim-bookworm` image.

## With Docker (pull from Docker Hub)
1. Run in terminal:
`docker run -p 7860:7860 joshuasundance/geospatial-data-converter:latest`
2. Open http://localhost:7860 in your browser

## Docker Compose (build locally)
1. Clone the repo. Navigate to cloned repo directory
2. Run in terminal: `docker compose up`
3. Open http://localhost:7860 in your browser

## Run Tests (with local Docker container)
1. Run in terminal: `docker compose run --rm test`

# Release workflow

## Everyday validation
1. Push to any branch or open a pull request to run the `CI` workflow.
2. The CI workflow runs `pre-commit` across tracked files, executes `pytest`, builds wheel/sdist artifacts, runs `twine check`, and smoke-tests the Docker image.

## Dry runs before release
1. Run the `Release Assets` workflow with `dry_run=true` to build artifacts, validate metadata, and upload preview assets without creating a GitHub Release.
2. Run the `Docker Image` workflow with `publish=false` to build and smoke-test the container without logging in to Docker Hub or pushing tags.
3. Run the `Bump Version` workflow with `push_changes=false` to exercise the version-bump path, tests, and packaging checks without pushing the commit or tag.

## Shipping a release
1. Run `Bump Version` with the desired bump and `push_changes=true`.
2. Push or create the matching git tag if you did not let the workflow push it.
3. Let `Release Assets` create or update the draft GitHub Release with generated notes from GitHub and `.github/release.yml`.
4. Let the Docker workflow publish `joshuasundance/geospatial-data-converter:x.y.z` and `latest`.

# Links
- [Streamlit](https://streamlit.io)
- [GeoPandas](https://geopandas.org/)
- [Docker Hub](https://hub.docker.com/)
