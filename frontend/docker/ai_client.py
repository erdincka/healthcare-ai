"""Clients for the speech-to-text, TranslateGemma and MedGemma OpenAI-compatible endpoints."""

import base64
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
import structlog

from constants import DEFAULTS, STT_FORMAT_CHAT, STT_FORMAT_WHISPER
from llm_output import (
    TRIAGE_JSON_SCHEMA,
    LlmOutputError,
    extract_json_object,
    parse_triage_output,
    strip_reasoning,
)
from utils import (
    encode_image_to_base64,
    format_exception_details,
    get_iso_language_code,
    normalize_language_name,
)

logger = structlog.get_logger(__name__)

CHAT_COMPLETIONS_SUFFIX = "/v1/chat/completions"
TRANSCRIPTIONS_SUFFIX = "/v1/audio/transcriptions"
# MedGemma 1.5 reasons before it answers; give the answer room so it is never cut off.
TRIAGE_MAX_TOKENS = 2048
XRAY_MAX_TOKENS = 2048
# Enough for several minutes of speech.
STT_MAX_TOKENS = 4096
STT_TIMEOUT = 300.0

STT_SYSTEM_PROMPT = (
    "You are a speech-to-text engine. Transcribe the speech in the audio verbatim, "
    "in the language it is spoken. Do not translate, summarise, answer or comment."
)
STT_DETECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"language": {"type": "string"}, "text": {"type": "string"}},
    "required": ["language", "text"],
    "additionalProperties": False,
}

# Health-check clip: espeak-ng (en-gb voice) reading STT_CHECK_PHRASE, 16 kHz mono WAV.
STT_CHECK_AUDIO = Path(__file__).parent / "assets" / "stt_check.wav"
STT_CHECK_PHRASE = "The patient reports a mild headache since this morning."
# Share of the phrase's words the transcript must contain for the check to pass.
STT_CHECK_MIN_MATCH = 0.6

# Audio formats by file extension, with the content type sent to Whisper endpoints.
AUDIO_CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "m4a": "audio/mp4",
}


class TranscriptionError(RuntimeError):
    """The speech-to-text endpoint rejected the request or returned no transcript."""


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


def _audio_format(audio_path: str) -> str:
    """Return the audio format named by the file extension, defaulting to WAV."""
    ext = os.path.splitext(audio_path)[1].lower().lstrip(".")
    return ext if ext in AUDIO_CONTENT_TYPES else "wav"


def _raise_for_stt_status(response: httpx.Response) -> None:
    """Turn a non-2xx speech-to-text response into a ``TranscriptionError``."""
    if not response.is_success:
        raise TranscriptionError(
            f"speech-to-text API returned {response.status_code}: {_error_detail(response)}"
        )


async def _transcribe_whisper(
    audio_path: str, language_code: str | None, url: str, token: str | None, model: str
) -> tuple[str, str]:
    """Transcribe through a Whisper-style ``/v1/audio/transcriptions`` endpoint."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with open(audio_path, "rb") as f:
        files: dict[str, Any] = {
            "file": (
                os.path.basename(audio_path),
                f,
                AUDIO_CONTENT_TYPES[_audio_format(audio_path)],
            ),
            "model": (None, model),
            "task": (None, "transcribe"),
        }
        if language_code:
            files["language"] = (None, language_code)

        api_url = _get_api_url(url, TRANSCRIPTIONS_SUFFIX)
        logger.info("requesting_transcription", url=api_url, api_format=STT_FORMAT_WHISPER)
        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(
                api_url, headers=headers, files=files, timeout=STT_TIMEOUT
            )

    _raise_for_stt_status(response)
    result = response.json()
    language = result.get("language") or result.get("detected_language") or "Unknown"
    return str(language), str(result.get("text") or "")


def _build_stt_chat_payload(
    audio_b64: str, audio_format: str, language_code: str | None, model: str
) -> dict[str, Any]:
    """Build the chat-completions request that transcribes an audio clip.

    Without a language the model also identifies it and answers in JSON
    (``response_format``); with one it returns the bare transcript.
    """
    if language_code:
        instruction = (
            "Transcribe this audio. The speaker uses "
            f"{normalize_language_name(language_code)}. Return only the transcript."
        )
    else:
        instruction = (
            'Transcribe this audio. Return JSON with "language" (the ISO 639-1 code of '
            'the spoken language) and "text" (the verbatim transcript).'
        )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": STT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": audio_format},
                    },
                    {"type": "text", "text": instruction},
                ],
            },
        ],
        "max_tokens": STT_MAX_TOKENS,
        "temperature": 0.0,
        # vLLM and NIM: skip the thinking pass of reasoning models such as Nemotron Nano Omni.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if not language_code:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "transcription", "schema": STT_DETECT_SCHEMA},
        }
    return payload


def _parse_stt_chat_answer(result: dict[str, Any], language_code: str | None) -> tuple[str, str]:
    """Return ``(language, text)`` from a chat-completions transcription response."""
    choices = result.get("choices") or []
    if not choices:
        raise TranscriptionError("the model returned no answer")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise TranscriptionError("the transcript was cut off at the token limit")
    content, _reasoning = strip_reasoning((choice.get("message") or {}).get("content") or "")

    if language_code:
        return language_code, content
    try:
        data = extract_json_object(content)
    except LlmOutputError:
        # The server ignored response_format; the answer is the transcript itself.
        return "Unknown", content
    return str(data.get("language") or "Unknown"), str(data.get("text") or "").strip()


async def _transcribe_chat(
    audio_path: str, language_code: str | None, url: str, token: str | None, model: str
) -> tuple[str, str]:
    """Transcribe by sending the audio to ``/v1/chat/completions`` as ``input_audio``."""
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")
    payload = _build_stt_chat_payload(audio_b64, _audio_format(audio_path), language_code, model)

    api_url = _get_api_url(url)
    logger.info("requesting_transcription", url=api_url, api_format=STT_FORMAT_CHAT, model=model)
    async with httpx.AsyncClient(verify=False) as client_http:
        response = await client_http.post(
            api_url, headers=_auth_headers(token), json=payload, timeout=STT_TIMEOUT
        )

    _raise_for_stt_status(response)
    return _parse_stt_chat_answer(response.json(), language_code)


async def request_transcription(
    audio_path: str,
    language_code: str | None,
    url: str,
    token: str | None,
    model_name: str | None = None,
    api_format: str = STT_FORMAT_WHISPER,
) -> tuple[str, str]:
    """Transcribe an audio file with the configured speech-to-text endpoint.

    Args:
        audio_path: Local audio file (WAV, MP3, FLAC, OGG, WebM or M4A).
        language_code: ISO code of the spoken language, or ``None`` to detect it.
        url: Base URL of the OpenAI-compatible endpoint.
        token: Optional bearer token.
        model_name: Model identifier; falls back to the configured default.
        api_format: ``"whisper"`` or ``"chat"`` (see ``constants.STT_API_FORMATS``).

    Returns:
        ``(language, text)``: the language as the server reports it (a code or a
        name, ``"Unknown"`` when it reports none) and the transcript.

    Raises:
        TranscriptionError: If the format is unknown, or the endpoint rejects the
            request or returns no transcript.
        httpx.HTTPError: On connection or timeout failures.
    """
    model = model_name or DEFAULTS["whisper"]["model"]
    if api_format == STT_FORMAT_CHAT:
        return await _transcribe_chat(audio_path, language_code, url, token, model)
    if api_format == STT_FORMAT_WHISPER:
        return await _transcribe_whisper(audio_path, language_code, url, token, model)
    raise TranscriptionError(f"unknown API format '{api_format}'")


async def transcribe_audio(
    audio_path: str,
    auto_detect: bool,
    expected_language: str,
    whisper_url: str,
    whisper_token: str,
    model_name: str | None = None,
    api_format: str = STT_FORMAT_WHISPER,
) -> tuple[str, str]:
    """Transcribe audio for the UI.

    Returns:
        ``(language, text)`` with the language as "Name (code)". On failure the
        language is ``"Unset"`` and the text explains the error.
    """
    if not whisper_url:
        return "Unset", "Speech-to-text URL not configured"

    language_code = None if auto_detect else get_iso_language_code(expected_language)
    try:
        language, text = await request_transcription(
            audio_path, language_code, whisper_url, whisper_token, model_name, api_format
        )
    except TranscriptionError as exc:
        logger.error("transcription_api_failed", error=str(exc), api_format=api_format)
        message = (
            f"Transcription failed ({exc}). Check the URL, token, model ID and API format "
            "in Settings."
        )
        return "Unset", message
    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("transcription_exception", error=err_detail, exc_info=True)
        return "Unset", f"Error: {err_detail}"
    return normalize_language_name(language), text


def transcript_matches(expected: str, heard: str, min_match: float = STT_CHECK_MIN_MATCH) -> bool:
    """Return whether ``heard`` contains at least ``min_match`` of the words in ``expected``."""
    expected_words = set(re.findall(r"\w+", expected.lower()))
    heard_words = set(re.findall(r"\w+", heard.lower()))
    return bool(expected_words) and (
        len(expected_words & heard_words) / len(expected_words) >= min_match
    )


async def check_stt(
    url: str, token: str | None, model_name: str | None, api_format: str
) -> tuple[bool, str]:
    """Health check: transcribe the bundled test clip and compare it with its script.

    The clip is sent without a language, so the check also covers language
    detection (the TranslationAI tab's default).
    """
    if not url:
        return False, "Speech-to-text URL is not configured"

    logger.info("checking_stt_health", url=url.rstrip("/"), api_format=api_format)
    started = time.perf_counter()
    try:
        language, text = await request_transcription(
            str(STT_CHECK_AUDIO), None, url, token, model_name, api_format
        )
    except TranscriptionError as exc:
        logger.error("stt_check_failed", error=str(exc), api_format=api_format)
        return (
            False,
            f"Transcription failed ({exc}). Check the URL, token, model ID and API format.",
        )
    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("stt_check_failed", error=err_detail, exc_info=True)
        return False, f"Speech-to-text API error: {err_detail}"
    elapsed = time.perf_counter() - started

    heard = text.strip()
    if not transcript_matches(STT_CHECK_PHRASE, heard):
        shown = f'"{heard[:120]}"' if heard else "no text"
        message = (
            f'Transcription of the test clip returned {shown}; expected "{STT_CHECK_PHRASE}". '
            "Check the model ID and API format."
        )
        return False, message
    detected = f", language {normalize_language_name(language)}" if language != "Unknown" else ""
    return True, f'Transcription works ({elapsed:.1f} s): heard "{heard}"{detected}'


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
) -> str:
    """Analyse an X-ray image with MedGemma.

    Returns:
        The analysis text. Any reasoning block the model might emit is
        stripped (none has been observed for vision prompts). Errors are
        returned as text.
    """
    if not medgemma_url:
        return "MedGemma URL not configured"

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
                analysis, _reasoning = strip_reasoning(content)
                return analysis

            logger.error("xray_analysis_failed", status=response.status_code)
            return f"Error: status {response.status_code}"

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("xray_analysis_exception", error=err_detail, exc_info=True)
        return f"Error: {err_detail}"


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


def _error_detail(response: httpx.Response) -> str:
    """Return the error message of a failed response, or the start of its body."""
    detail = response.text[:200]
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict) and error.get("message"):
            detail = str(error["message"])
        elif isinstance(error, str):
            detail = error
        elif isinstance(body, dict) and isinstance(body.get("message"), str):
            detail = body["message"]
        elif isinstance(body, dict) and isinstance(body.get("detail"), str):
            detail = body["detail"]
    except ValueError:
        pass
    return detail


def _raise_for_status(response: httpx.Response) -> None:
    """Turn a non-2xx response into a readable ``LlmOutputError``."""
    if response.is_success:
        return
    raise LlmOutputError(f"MedGemma API returned {response.status_code}: {_error_detail(response)}")


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
