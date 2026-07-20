# Sidecar for cluster/services/songhub.yaml: converts SongHub's saved
# *.ultimatetab.json tabs to PDF and pushes them to reMarkable Cloud via
# rmapi. See cluster/Dockerfiles/remarkable-sync/sync.py for the loop.

FROM golang:1.22-alpine AS rmapi-builder

# Pinned upstream ref, bumped deliberately via workflow_dispatch input in
# .github/workflows/build-remarkable-sync-image.yaml. ddvk/rmapi is the
# maintained fork; upstream juruen/rmapi is archived.
ARG RMAPI_REF=v0.0.34

RUN apk add --no-cache git
RUN git clone --branch "${RMAPI_REF}" --depth 1 https://github.com/ddvk/rmapi /src/rmapi \
    && cd /src/rmapi \
    && go build -o /out/rmapi .

FROM python:3.12-slim-bookworm

# weasyprint's native rendering deps + a monospace font for tab alignment.
# Package names (esp. libgdk-pixbuf) are Debian-release-specific, hence the
# pinned -bookworm base above rather than the floating python:3.12-slim tag.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir weasyprint==69.0

COPY --from=rmapi-builder /out/rmapi /usr/local/bin/rmapi
COPY sync.py /app/sync.py

RUN useradd --create-home --uid 1000 sync
USER sync
WORKDIR /app

ENV TAB_DIR=/app/saved-tabs \
    SYNC_INTERVAL_SECONDS=1800 \
    REMARKABLE_TARGET_FOLDER=SongHub \
    HEARTBEAT_FILE=/tmp/heartbeat \
    RMAPI_CONFIG=/secrets/rmapi/rmapi.conf

ENTRYPOINT ["python3", "/app/sync.py"]
