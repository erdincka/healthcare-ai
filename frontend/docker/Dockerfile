# Production image for the HealthcareAI frontend (Gradio).
# Development hot-reload is provided by the Tiltfile, not by this image.
FROM python:3.12-slim-bookworm

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
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 7860

# Kubernetes probes (see the Helm chart) replace a Docker HEALTHCHECK.
CMD ["python", "app.py"]
