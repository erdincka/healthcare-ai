"""Unit tests for TranslateGemma: request format, error reporting and the health check."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

import ai_client

LITELLM_URL = "https://litellm.example.com"
# The error vLLM's TranslateGemma template raised for the old system + user request.
VLLM_TEMPLATE_ERROR = {
    "error": {
        "message": "litellm.BadRequestError: Hosted_vllmException - Conversations must start "
        "with a user prompt.",
        "type": "invalid_request_error",
        "code": "400",
    }
}


def _chat_result(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


def test_payload_is_one_user_message_with_language_markers() -> None:
    payload = ai_client._build_translation_payload(
        "Me duele la cabeza.", "es", "en", "translategemma:4b"
    )
    assert payload["messages"] == [
        {"role": "user", "content": "<<<source>>>es<<<target>>>en<<<text>>>Me duele la cabeza."}
    ]
    assert payload["model"] == "translategemma:4b"


def test_translation_request(fake_server: Callable[..., list[httpx.Request]]) -> None:
    captured = fake_server(200, _chat_result("I have had a headache since yesterday.\n"))
    translation = asyncio.run(
        ai_client.translate_text(
            "Me duele la cabeza desde ayer.", "es", "en", f"{LITELLM_URL}/v1", "sk-key"
        )
    )
    assert translation == "I have had a headache since yesterday."
    request = captured[0]
    assert str(request.url) == f"{LITELLM_URL}/v1/chat/completions"
    body = json.loads(request.content)
    assert body["messages"][0]["content"].startswith("<<<source>>>es<<<target>>>en<<<text>>>")
    assert body["model"] == "translategemma:4b"  # default model


def test_translation_error_shows_server_message(
    fake_server: Callable[..., list[httpx.Request]],
) -> None:
    fake_server(400, VLLM_TEMPLATE_ERROR)
    result = asyncio.run(
        ai_client.translate_text("Hola.", "es", "en", LITELLM_URL, "sk-key", "translategemma:4b")
    )
    assert result.startswith("Translation failed (TranslateGemma API returned 400: ")
    assert "Conversations must start with a user prompt" in result
    assert "Settings" in result


def test_cut_off_translation_is_reported(fake_server: Callable[..., list[httpx.Request]]) -> None:
    fake_server(200, _chat_result("I have had", "length"))
    result = asyncio.run(ai_client.translate_text("Hola.", "es", "en", LITELLM_URL))
    assert "cut off" in result


def test_empty_text_is_returned_unchanged() -> None:
    assert asyncio.run(ai_client.translate_text("  ", "es", "en", LITELLM_URL)) == "  "


def test_check_translation_passes(fake_server: Callable[..., list[httpx.Request]]) -> None:
    captured = fake_server(200, _chat_result("My head has hurt since yesterday."))
    ok, message = asyncio.run(ai_client.check_translation(LITELLM_URL, "sk-key", None))
    assert ok
    assert "Translation works" in message
    content = json.loads(captured[0].content)["messages"][0]["content"]
    assert content == f"<<<source>>>es<<<target>>>en<<<text>>>{ai_client.TRANSLATION_CHECK_TEXT}"


def test_check_translation_fails_on_api_error(
    fake_server: Callable[..., list[httpx.Request]],
) -> None:
    fake_server(400, VLLM_TEMPLATE_ERROR)
    ok, message = asyncio.run(ai_client.check_translation(LITELLM_URL, "sk-key", None))
    assert not ok
    assert "400" in message


def test_check_translation_fails_on_untranslated_answer(
    fake_server: Callable[..., list[httpx.Request]],
) -> None:
    fake_server(200, _chat_result("Me duele la cabeza desde ayer."))
    ok, message = asyncio.run(ai_client.check_translation(LITELLM_URL, "sk-key", None))
    assert not ok
    assert "expected English" in message


def test_check_translation_needs_url() -> None:
    ok, message = asyncio.run(ai_client.check_translation("", "", None))
    assert not ok
    assert "not configured" in message
