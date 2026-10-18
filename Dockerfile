# Atlas — one image, the neutral theme, no bundled lab.
#
#   docker build -t atlas .
#
# A fresh install opens on an empty map and an invitation to chart it
# (ATLAS_FALLBACK=empty). Set ATLAS_FALLBACK=bundled to open on the demo lab
# instead, when this image carries one (Web/default-lab-data.json).
#
# Sign-in is on by default (ATLAS_AUTH_MODE=accounts): give the first admin a
# password with ATLAS_BOOTSTRAP_ADMIN_PASSWORD (compose.public.yaml passes its
# ATLAS_ADMIN_PASSWORD through). Without one the Atlas starts, says why in its
# log, and nobody can sign in until an admin exists.

FROM python:3.12-slim AS public

# non-root; /data is the volume the app writes (dataset, accounts, keys)
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin atlas \
 && mkdir -p /data && chown atlas:atlas /data

WORKDIR /app
COPY Web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
ENV ATLAS_THEME=plain
# a shipped image never serves the map without sign-in; standalone stays a
# choice the operator makes on purpose (docs/configuration.md)
ENV ATLAS_AUTH_MODE=accounts
# /metrics across both gunicorn workers: prometheus_client's multiprocess
# mode keeps per-process files here. 1777 so any `user:` a compose file picks
# can write it.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/atlas-metrics
RUN mkdir -p /tmp/atlas-metrics && chmod 1777 /tmp/atlas-metrics

COPY Web/ /app/
# the test suite and its fixtures are for CI, not for the running image
RUN rm -rf /app/tests

EXPOSE 5006
HEALTHCHECK --interval=60s --timeout=5s --retries=3 CMD \
  python -c "import urllib.request,sys; r=urllib.request.urlopen('http://localhost:5006/api/v2/health', timeout=3); sys.exit(0 if r.status==200 else 1)"

USER atlas
# --timeout 120: the real-world survey (geocode + map render) can legitimately
# take tens of seconds; everything else answers in milliseconds.
CMD ["gunicorn", "-c", "gunicorn.conf.py", \
     "--workers", "2", "--threads", "4", "--timeout", "120", \
     "--bind", "0.0.0.0:5006", \
     "--access-logfile", "-", "--error-logfile", "-", "app:app"]
