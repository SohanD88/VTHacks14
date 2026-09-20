# syntax=docker/dockerfile:1
# Fly Machines mount one persistent volume per Machine. Run the API and Blender
# worker together so scans, model cache, and worker jobs share that volume.
FROM ghcr.io/astral-sh/uv:0.10.12 AS uv
FROM python:3.11-slim-bookworm

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 \
    SPATIAL_DATA_DIR=/data/scans SPATIAL_MODEL_CACHE=/data/models \
    SPATIAL_BLENDER_TRANSPORT=container SPATIAL_BLENDER_JOBS_DIR=/jobs
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl xz-utils libx11-6 libxi6 libxfixes3 libxrender1 \
    libxkbcommon0 libsm6 libgl1 libegl1 libgomp1 libxext6 gosu tini \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --prune torch --prune torchvision -o /tmp/requirements.txt \
    && uv pip install --system torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu \
    && uv pip install --system --no-deps -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

ARG BLENDER_VERSION=5.1.2
ARG BLENDER_SHA256=aaccb355f50183979b698bcce7467103a76261b5fa59f4972295842662a285fb
# Some remote builders receive HTTP 403 from the primary download CDN.
# The mirror serves the same release; the pinned checksum still gates extraction.
RUN (curl --fail --show-error --location --retry 3 --connect-timeout 30 \
      "https://download.blender.org/release/Blender5.1/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
      -o /tmp/blender.tar.xz \
    || curl --fail --show-error --location --retry 3 --connect-timeout 30 \
      "https://mirrors.iu13.net/blender/release/Blender5.1/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
      -o /tmp/blender.tar.xz) \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum -c - \
    && mkdir /opt/blender && tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && ln -s /opt/blender/blender /usr/local/bin/blender && rm /tmp/blender.tar.xz

RUN groupadd -g 10001 spatial && useradd -u 10001 -g spatial spatial \
    && mkdir -p /data /worker && ln -s /data/jobs /jobs
COPY backend/app ./app
COPY backend/scripts/blender /worker
COPY deploy/start-fly.sh /usr/local/bin/start-fly
RUN chmod +x /usr/local/bin/start-fly

EXPOSE 8000
ENTRYPOINT ["tini", "--"]
CMD ["/usr/local/bin/start-fly"]
