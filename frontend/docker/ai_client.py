"""Clients for the Whisper, TranslateGemma and MedGemma OpenAI-compatible endpoints."""

import os
from typing import Any

import httpx
import structlog

from constants import DEFAULTS
from llm_output import TRIAGE_JSON_SCHEMA, LlmOutputError, parse_triage_output, strip_reasoning
from utils import (
    encode_image_to_base64,
    format_exception_details,
    get_iso_language_code,
    normalize_language_name,
)

logger = structlog.get_logger(__name__)

CHAT_COMPLETIONS_SUFFIX = "/v1/chat/completions"
# MedGemma 1.5 reasons before it answers; give the answer room so it is never cut off.
TRIAGE_MAX_TOKENS = 2048
XRAY_MAX_TOKENS = 2048

TRIAGE_SYSTEM_PROMPT = (
    "You are a highly skilled medical diagnostician. "
    "Analyse the clinical notes and return a structured diagnosis as a JSON object "
    "with exactly these keys: patient_name, date_of_birth (YYYY-MM-DD), "
    "visit_time (YYYY-MM-DD HH:MM:SS), severity (Mild, Moderate, Severe or Critical), "
    "primary_diagnosis, secondary_diagnoses, recommended_tests, recommended_treatment, "
    "follow_up, medical_reasoning. "
    "Use an empty string or an empty list when a value is not stated in the notes. "
    "Return only the JSON object, with no markdown and no commentary."
)


def _get_api_url(base_url: str, suffix: str = CHAT_COMPLETIONS_SUFFIX) -> str:
    """Build an OpenAI-compatible endpoint URL from a configured base URL.

    Accepts a bare host, a base ending in ``/v1`` or a full ``/v1/...`` endpoint
    path; anything from ``/v1`` onwards is replaced by ``suffix``.
    """
    base = base_url.rstrip("/")
    marker = base.find("/v1/")
    if marker != -1:
        base = base[:marker]
    elif base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}{suffix}"


def _auth_headers(token: str | None) -> dict[str, str]:
    """Return JSON request headers with an optional bearer token."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def check_model(
    model_type: str, url: str, token: str, model_name: str | None = None
) -> tuple[bool, str]:
    """Generic health check for model APIs."""
    if not url:
        return False, f"{model_type.capitalize()} URL is not configured"

    try:
        logger.info("checking_model_health", type=model_type, url=url.rstrip("/"))

        if model_type in ("medgemma", "triage"):  # triage/medgemma are the same
            return await check_triage_model(url, token, model_name)

        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.get(
                _get_api_url(url, "/v1/models"), headers=_auth_headers(token), timeout=10.0
            )
            if response.status_code == 200:
                data = response.json().get("data", [])
                if not data:
                    return (
                        False,
                        f"{model_type.capitalize()} API returned empty models list",
                    )

                if model_name:
                    model_ids = [m["id"] for m in data]
                    if model_name in model_ids:
                        return (
                            True,
                            f"{model_type.capitalize()} API is available and responding",
                        )
                    else:
                        return (
                            False,
                            f"Model '{model_name}' not found in {model_type.capitalize()} API",
                        )
                return (
                    True,
                    f"{model_type.capitalize()} API is available and responding",
                )
            else:
                return (
                    False,
                    f"{model_type.capitalize()} API returned status: {response.status_code}",
                )

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("model_check_failed", error=err_detail, model_type=model_type, exc_info=True)
        return False, f"{model_type.capitalize()} API error: {err_detail}"


async def check_triage_model(
    url: str, token: str | None = None, model_name: str | None = None
) -> tuple[bool, str]:
    """Health check specifically for MedGemma model."""
    try:
        payload = {
            "model": model_name or DEFAULTS["medgemma"]["model"],
            "messages": [
                {"role": "system", "content": "You are an elite radiologist."},
                {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            ],
            "max_tokens": 10,
            "temperature": 0.1,
        }

        api_url = _get_api_url(url)
        logger.info("checking_medgemma_health", url=api_url, model=payload["model"])

        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(
                api_url, headers=_auth_headers(token), json=payload, timeout=120.0
            )
            logger.info("medgemma_health_response", status=response.status_code)
            if response.status_code == 200:
                return True, "MedGemma API is available and responding"
            else:
                return (
                    False,
                    f"MedGemma API returned status: {response.status_code}: {response.text[:100]}",
                )

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("medgemma_check_failed", error=err_detail, exc_info=True)
        return False, f"MedGemma API error: {err_detail}"


async def transcribe_audio(
    audio_path: str,
    auto_detect: bool,
    expected_language: str,
    whisper_url: str,
    whisper_token: str,
    model_name: str | None = None,
) -> tuple[str, str]:
    """Transcribe audio using Whisper API."""
    if not whisper_url:
        return "Unset", "Whisper URL not configured"

    try:
        headers = {"Authorization": f"Bearer {whisper_token}"} if whisper_token else {}

        with open(audio_path, "rb") as f:
            files: dict[str, Any] = {"file": (os.path.basename(audio_path), f, "audio/wav")}
            if model_name:
                files["model"] = (None, model_name)
            else:
                files["model"] = (None, DEFAULTS["whisper"]["model"])

            files["task"] = (None, "transcribe")

            if not auto_detect:
                files["language"] = (None, get_iso_language_code(expected_language))

            api_url = f"{whisper_url.rstrip('/')}/v1/audio/transcriptions"
            logger.info("requesting_transcription", url=api_url)
            async with httpx.AsyncClient(verify=False) as client_http:
                response = await client_http.post(
                    api_url, headers=headers, files=files, timeout=300.0
                )

        if response.status_code == 200:
            result = response.json()
            det_lang = result.get("language") or result.get("detected_language") or "Unknown"
            text = result.get("text", "")
            return normalize_language_name(det_lang), text
        else:
            logger.error(
                "transcription_api_failed",
                status=response.status_code,
                text=response.text[:200],
            )
            return "Unset", f"Transcription failed ({response.status_code})"

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("transcription_exception", error=err_detail, exc_info=True)
        return "Unset", f"Error: {err_detail}"


async def translate_text(
    text: str,
    source_lang: str,
    target_lang: str,
    translategemma_url: str,
    translategemma_token: str | None = None,
    model_name: str | None = None,
) -> str:
    """Translate text using TranslateGemma API."""
    if not translategemma_url or not text.strip():
        return text

    try:
        # normalize_language_name already returns "Name (code)".
        s_lang_name = normalize_language_name(source_lang)
        t_lang_name = normalize_language_name(target_lang)

        system_msg = (
            f"You are a professional {s_lang_name} to {t_lang_name} translator. "
            f"Produce only the {t_lang_name} translation. \n\n{text}"
        )

        payload = {
            "model": model_name or DEFAULTS["translategemma"]["model"],
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": [{"type": "text", "text": text}]},
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
        }

        api_url = _get_api_url(translategemma_url)
        logger.info("requesting_translation", url=api_url, model=payload["model"])

        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(
                api_url, headers=_auth_headers(translategemma_token), json=payload, timeout=300.0
            )

        if response.status_code == 200:
            result = response.json()
            return (
                result["choices"][0]["message"]["content"] if "choices" in result else str(result)
            )

        logger.error("translation_api_failed", status=response.status_code)
        return f"Translation failed: {response.status_code}"

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("translation_exception", error=err_detail, exc_info=True)
        return f"Error: {err_detail}"


async def analyze_xray_with_medgemma(
    image_path: str,
    medgemma_url: str,
    medgemma_token: str | None = None,
    model_name: str | None = None,
) -> tuple[str, str]:
    """Analyse an X-ray image with MedGemma.

    Returns:
        ``(analysis, reasoning)``. ``reasoning`` holds the model's thinking
        block when it emitted one, otherwise an empty string. Errors are
        returned as the analysis text with empty reasoning.
    """
    if not medgemma_url:
        return "MedGemma URL not configured", ""

    try:
        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        mime_type = f"image/{ext}" if ext in ["png", "jpeg", "jpg", "webp"] else "image/png"
        if ext == "jpg":
            mime_type = "image/jpeg"

        base64_image = encode_image_to_base64(image_path)
        logger.info("requesting_xray_analysis", path=image_path)

        prompt = "Analyze this X-ray image. Provide a structured analysis."
        payload = {
            "model": model_name or DEFAULTS["medgemma"]["model"],
            "messages": [
                {"role": "system", "content": "You are an expert radiologist."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                        },
                    ],
                },
            ],
            "max_tokens": XRAY_MAX_TOKENS,
            "temperature": 0.1,
        }

        api_url = _get_api_url(medgemma_url)
        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(
                api_url, headers=_auth_headers(medgemma_token), json=payload, timeout=120.0
            )
            if response.status_code == 200:
                content, _ = _extract_choice(response.json())
                return strip_reasoning(content)

            logger.error("xray_analysis_failed", status=response.status_code)
            return f"Error: status {response.status_code}", ""

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("xray_analysis_exception", error=err_detail, exc_info=True)
        return f"Error: {err_detail}", ""


def _build_triage_payload(text: str, model: str) -> dict[str, Any]:
    """Build the chat-completions request for a triage analysis.

    ``response_format`` asks the backend for grammar-constrained JSON. Ollama
    and vLLM honour it, which keeps reasoning text out of the answer.
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyse these notes and return JSON: {text}"},
        ],
        "max_tokens": TRIAGE_MAX_TOKENS,
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "triage", "schema": TRIAGE_JSON_SCHEMA},
        },
    }


def _extract_choice(result: dict[str, Any]) -> tuple[str, str]:
    """Return ``(content, finish_reason)`` of the first chat-completion choice.

    Raises:
        LlmOutputError: If the response has no choice or the output was cut off
            by the token limit.
    """
    choices = result.get("choices") or []
    if not choices:
        raise LlmOutputError("The model returned no answer.")
    choice = choices[0]
    content = (choice.get("message") or {}).get("content") or ""
    finish_reason = choice.get("finish_reason") or ""
    if finish_reason == "length":
        raise LlmOutputError(
            "The model output was cut off before it finished. "
            "Run the analysis again, or shorten the notes."
        )
    return content, finish_reason


def _raise_for_status(response: httpx.Response) -> None:
    """Turn a non-2xx response into a readable ``LlmOutputError``."""
    if response.is_success:
        return
    detail = response.text[:200]
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict) and error.get("message"):
            detail = str(error["message"])
        elif isinstance(error, str):
            detail = error
    except ValueError:
        pass
    raise LlmOutputError(f"MedGemma API returned {response.status_code}: {detail}")


async def analyze_text_with_medgemma(
    text: str,
    medgemma_url: str,
    medgemma_token: str | None = None,
    model_name: str | None = None,
) -> str:
    """Analyse clinical notes with MedGemma and return a validated triage record.

    Args:
        text: The clinician's notes.
        medgemma_url: Base URL of the OpenAI-compatible endpoint.
        medgemma_token: Optional bearer token.
        model_name: Model identifier; falls back to the configured default.

    Returns:
        The triage record as pretty-printed JSON, ready to display and to save.

    Raises:
        LlmOutputError: If the endpoint is not configured, returns an error, or
            its output is not a valid triage record.
        httpx.HTTPError: On connection or timeout failures.
    """
    if not medgemma_url:
        raise LlmOutputError("MedGemma URL is not configured. Set it in Settings.")

    payload = _build_triage_payload(text, model_name or DEFAULTS["medgemma"]["model"])
    api_url = _get_api_url(medgemma_url)
    logger.info("requesting_text_analysis", url=api_url, model=payload["model"])

    async with httpx.AsyncClient(verify=False) as client_http:
        response = await client_http.post(
            api_url, headers=_auth_headers(medgemma_token), json=payload, timeout=180.0
        )
    _raise_for_status(response)

    result = response.json()
    content, finish_reason = _extract_choice(result)
    triage = parse_triage_output(content)
    logger.info(
        "text_analysis_completed",
        model=payload["model"],
        finish_reason=finish_reason,
        usage=result.get("usage"),
    )
    return triage.model_dump_json(indent=2)
