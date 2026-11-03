# HealthcareAI frontend (Gradio). Two targets: `dev` (the Tilt dev loop: restarts the app when synced source changes)
# and `prod` (the default, built last: the published image).
FROM python:3.12-slim-bookworm AS base

LABEL maintainer="HealthcareAI Team" \
      description="Frontend UI for the HealthcareAI demo on HPE Private Cloud AI"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    GRADIO_ANALYTICS_ENABLED=False

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv, pinned, copied from the official image (no installer script, no curl needed).
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

COPY requirements.txt .
RUN uv pip install --no-cache -r requirements.txt

RUN useradd -m -u 1000 appuser

EXPOSE 7860

# Dev only: the same `python app.py` as production (Gradio's own reload mode skips launch()'s theme and host), restarted
# by watchfiles when a .py file changes. Test tooling is installed so checks run in this image. appuser owns /app, as
# Tilt syncs files in as that user.
FROM base AS dev
COPY requirements-dev.txt .
RUN uv pip install --no-cache -r requirements-dev.txt && chown appuser:appuser /app
COPY --chown=appuser:appuser . .
USER appuser
CMD ["watchfiles", "--filter", "python", "--target-type", "command", "python app.py", "/app"]

FROM base AS prod
COPY --chown=appuser:appuser . .
USER appuser

# Kubernetes probes (see the Helm chart) replace a Docker HEALTHCHECK.
CMD ["python", "app.py"]
