# HealthcareAI

Coding standards: `CODING_STANDARDS.md`. Overview, deployment and release: `readme.md`.

## Dev loop (pcai-dev-loop)

- Develop with Tilt in namespace `dev`, at `https://healthcareai-dev.<PCAI domain>`, following the `pcai-dev-loop`
  skill. Settings are in `tilt_config.json` (git-ignored; copy `tilt_config.example.json`). Run
  `tilt up --context <context>`; never switch the current kube context.
- Never deploy into `healthcareai` or any namespace a PCAI app is installed in, with Tilt or Helm. Never edit the
  Tiltfile's guards out.
- Dev-only settings live in the Dockerfile's `dev` target and `dev-values.yaml`; the chart's `values.yaml` is the
  production default. The `dev` target runs `python app.py` under `watchfiles`: Gradio's own reload mode skips
  `launch()`'s theme, host and allowed paths.
- The dev copy keeps its own Settings (endpoints, tokens, database) on its own volume. Never copy production tokens or
  the production database connection into it.
- Run checks in the `dev` image, as in the readme's Development section (ruff, mypy, pytest).
- Release as in the readme's Release section: a new image tag (never a Tilt or `dev` image), a chart version bump,
  then the new chart through AI Essentials' Import Framework.
