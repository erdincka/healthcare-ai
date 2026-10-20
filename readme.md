# HealthcareAI

## Overview

HealthcareAI showcases a healthcare application built on HPE Private Cloud AI. It supports
clinicians with three AI-assisted workflows:

- **TranslationAI**: transcribe patient audio with a speech-to-text model and translate it with
  TranslateGemma.
- **TriageAI**: transcribe clinical notes, have MedGemma produce a structured triage record
  (severity, diagnosis, tests, treatment, follow-up, reasoning) and save it to PostgreSQL.
- **XrayAI**: radiology analysis of an uploaded X-ray with MedGemma.

<img width="2984" height="1400" alt="image" src="https://github.com/user-attachments/assets/cbfbdfad-cf3b-4cca-a903-949b84babff7" />

The frontend is a Gradio app (`frontend/docker`) packaged as a Helm chart (`frontend/helm`) and
imported into HPE Private Cloud AI as a framework. All endpoints, tokens, model names and the
database connection string are entered in the **Settings** tab and persisted on the app's
PersistentVolumeClaim. The Settings tab is deliberately open to every visitor so that demo users
can switch models and databases; do not use this app with real patient data.

## Model backends

Any OpenAI-compatible chat endpoint works. TriageAI requests grammar-constrained JSON through the
`response_format` field (`json_schema`), so the backend must support structured outputs. Ollama
(0.5+) and vLLM do; this keeps MedGemma 1.5's reasoning text out of the saved record.

### Ollama (as deployed on the garage cluster)

| Service | Model | Notes |
|---|---|---|
| MedGemma (triage and X-ray) | `medgemma1.5:4b` | Official Ollama library build, vision-capable |
| TranslateGemma | `translategemma:4b` | |
| Speech-to-text | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (NIM on MLIS) | API format **Chat completions** |

Point the MedGemma and TranslateGemma URLs at the Ollama base URL (for example
`https://ollama.<domain>`); the app appends `/v1/chat/completions`.

### Speech-to-text

The Settings tab's **API format** selects how audio is sent to the speech-to-text endpoint:

| API format | Endpoint | Suits |
|---|---|---|
| Whisper | `/v1/audio/transcriptions` (multipart upload) | Whisper on vLLM, OpenAI-compatible ASR servers |
| Chat completions | `/v1/chat/completions` with an `input_audio` part | Audio-capable LLMs such as Nemotron Nano Omni |

In chat mode the app asks for the bare transcript when the language is known and for JSON
(`language`, `text`) through `response_format` when it has to detect it. It also sends
`chat_template_kwargs: {"enable_thinking": false}` so reasoning models transcribe without a
thinking pass (vLLM and NIM read this field).

**Check Health** transcribes a bundled test clip (`frontend/docker/assets/stt_check.wav`, an
espeak-ng en-GB reading of "The patient reports a mild headache since this morning.") without a
language hint, and passes only if the transcript matches. A wrong API format, model ID or token
therefore fails the check instead of reporting a reachable port.

### MLIS with vLLM (alternative)

Deploy each model from the MLIS UI as a custom model:

```text
MedGemma:        image vllm/vllm-openai:<current>  args: --model google/medgemma-1.5-4b-it --port 8080
                 env: HUGGING_FACE_HUB_TOKEN=<token>
TranslateGemma:  image vllm/vllm-openai:<current>  args: --model google/translategemma-2-9b --port 8080
Whisper:         image davemcmahon/vllm-with-audio:latest  args: --model openai/whisper-large-v3 --port 8080
                 (API format Whisper)
```

## Deploying on HPE Private Cloud AI

1. In AI Essentials choose **Import Framework** and upload `healthcareai-0.3.3.tgz` (the packaged
   chart from `frontend/helm`). Use the name `healthcareai`, namespace `healthcareai`, the logo
   from `logo.png` at the repository root and the values block from `healthcare-ezapp.yaml`.
2. Open the app, go to **Settings**, enter the endpoints, tokens, model names and the PostgreSQL
   connection string, then **Check Health** and **Save Configuration**.
3. If the `triage` table does not exist, click **Initialize Database** to create it with 200
   realistic sample records.

The chart labels every resource with `hpe-ezua/app` and `hpe-ezua/type: vendor-service`, so the
platform attributes the pods to the framework without any Kyverno policy. The chart also sets
readiness and liveness probes, a non-root security context, and keeps the Settings volume across
reinstalls.

## Development

```bash
cp .env.example .env   # set DOMAIN, NAMESPACE and KUBE_CONTEXT for Tilt
tilt up                # builds the image, deploys the chart and hot-reloads code changes
```

The published image is production-only (`python app.py`); Tilt overrides the entrypoint with
Gradio's reload mode for development. Checks run inside a container built from the Dockerfile:

```bash
docker build -t healthcare-ai:dev frontend/docker
docker run --rm --user root -v "$PWD/frontend/docker:/app" -w /app healthcare-ai:dev sh -c \
  "uv pip install --system -r requirements-dev.txt && ruff check . && ruff format --check . \
   && mypy --strict llm_output.py ai_client.py db_client.py utils.py config_manager.py && pytest -q"
```

### Release

```bash
docker buildx build --platform linux/amd64 -t nexusglobal/triageai:1.2.3 -t nexusglobal/triageai:latest --push frontend/docker
helm package frontend/helm -d .
```

Then import the new `.tgz` through AI Essentials as described above.

## Dashboards

`superset/` holds Apache Superset dashboard exports built on the `triage` table.
