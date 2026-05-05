# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /opt/app

RUN python -m venv "$VIRTUAL_ENV"

COPY README.md pyproject.toml ./
COPY geospatial-data-converter/ ./geospatial-data-converter/

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip && \
    python -m pip install .


FROM builder AS test

COPY tests/ ./tests/

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install ".[dev]"

CMD ["python", "-m", "pytest", "-q"]


FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ARG VERSION=dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

LABEL org.opencontainers.image.title="geospatial-data-converter" \
      org.opencontainers.image.description="Streamlit app for converting geospatial datasets between common formats." \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/joshuasundance-swca/geospatial-data-converter" \
      org.opencontainers.image.documentation="https://github.com/joshuasundance-swca/geospatial-data-converter/blob/main/README.md" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.created="$BUILD_DATE"

RUN adduser --uid 1000 --disabled-password --gecos "" appuser && \
    mkdir -p /workspace /opt/app /home/appuser/.streamlit && \
    chown -R appuser:appuser /workspace /opt/app /home/appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/app/geospatial-data-converter /opt/app/geospatial-data-converter

WORKDIR /workspace
USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/_stcore/health', timeout=5).read()"

ENTRYPOINT ["python", "-m", "streamlit", "run", "/opt/app/geospatial-data-converter/app.py"]
CMD ["--server.port=7860", "--server.address=0.0.0.0", "--server.enableXsrfProtection=false"]
