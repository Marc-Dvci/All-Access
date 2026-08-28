# All-Access — application plane.
#
# Serves the FastAPI application and the web client. The image carries the
# offline reasoning plane and the in-process event bus, so a container with no
# credentials at all still runs the full closed loop and the demonstration — the
# `AA_*` variables below switch it onto Confluent Cloud and Vertex AI without a
# rebuild.
#
# Multi-stage so the runtime layer has no build toolchain in it, and non-root
# because the process has no reason to be root and Cloud Run will not give it a
# reason.

# ---- build ----------------------------------------------------------------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Dependency metadata first, so the wheel layer is cached across source edits.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install .

# ---- runtime --------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Defaults are the fully offline plane. Both are overridden by environment
    # at deploy time; neither carries a credential.
    AA_REASONING_MODE=offline \
    AA_EVENT_BACKBONE=local \
    PORT=8080

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY --from=build /build/src /app/src
COPY LICENSE README.md /app/
# The evidence travels with the image: /api/about and the benchmark tab read
# these, and an image that reports numbers it does not carry is not evidence.
COPY bench/results /app/bench/results
COPY docs /app/docs

# Runtime state lives here and is writable; everything else is read-only to the
# application user.
RUN useradd --system --uid 10001 --home /app pulse \
 && mkdir -p /app/var \
 && chown -R pulse:pulse /app/var
USER pulse

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request;\
urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8080')}/healthz\",timeout=4)"

# Shell form so $PORT is expanded — Cloud Run assigns it and does not promise 8080.
CMD exec uvicorn allaccess.api:app --host 0.0.0.0 --port ${PORT}
