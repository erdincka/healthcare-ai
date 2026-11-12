"""Unit tests for speech-to-text: request building, answer parsing and the health check."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

import ai_client
import config_manager
from constants import STT_FORMAT_CHAT, STT_FORMAT_WHISPER

CHAT_URL = "https://nemotron-nano.example.com"
NEMOTRON = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"


def _chat_result(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


# --- Request building --------------------------------------------------------


def test_chat_payload_with_language_asks_for_plain_transcript() -> None:
    payload = ai_client._build_stt_chat_payload("QUJD", "wav", "es", NEMOTRON)
    user_parts = payload["messages"][1]["content"]
    assert user_parts[0] == {
        "type": "input_audio",
        "input_audio": {"data": "QUJD", "format": "wav"},
    }
    assert "Spanish (es)" in user_parts[1]["text"]
    assert "response_format" not in payload
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["model"] == NEMOTRON


def test_chat_payload_without_language_requests_json() -> None:
    payload = ai_client._build_stt_chat_payload("QUJD", "mp3", None, NEMOTRON)
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["language", "text"]
    assert payload["messages"][1]["content"][0]["input_audio"]["format"] == "mp3"


@pytest.mark.parametrize(
    ("path", "expected"),
    [("a.wav", "wav"), ("b.MP3", "mp3"), ("c.webm", "webm"), ("d.aiff", "wav"), ("e", "wav")],
)
def test_audio_format_from_extension(path: str, expected: str) -> None:
    assert ai_client._audio_format(path) == expected


# --- Answer parsing ----------------------------------------------------------


def test_parse_detected_language_and_text() -> None:
    result = _chat_result('{"language": "de", "text": "Ich habe Fieber."}')
    assert ai_client._parse_stt_chat_answer(result, None) == ("de", "Ich habe Fieber.")


def test_parse_plain_answer_when_server_ignores_response_format() -> None:
    result = _chat_result("I have had a fever since yesterday.")
    assert ai_client._parse_stt_chat_answer(result, None) == (
        "Unknown",
        "I have had a fever since yesterday.",
    )


def test_parse_known_language_strips_reasoning() -> None:
    result = _chat_result("<think>Spanish speech.</think>\nMe duele la cabeza.")
    assert ai_client._parse_stt_chat_answer(result, "es") == ("es", "Me duele la cabeza.")


def test_parse_rejects_cut_off_transcript() -> None:
    with pytest.raises(ai_client.TranscriptionError, match="cut off"):
        ai_client._parse_stt_chat_answer(_chat_result("Patient is", "length"), "en")


def test_parse_rejects_empty_choices() -> None:
    with pytest.raises(ai_client.TranscriptionError, match="no answer"):
        ai_client._parse_stt_chat_answer({"choices": []}, "en")


# --- Requests on the wire ----------------------------------------------------


def test_chat_transcription_request(fake_server: Callable[..., list[httpx.Request]]) -> None:
    captured = fake_server(200, _chat_result('{"language": "en", "text": "Hello."}'))
    language, text = asyncio.run(
        ai_client.request_transcription(
            str(ai_client.STT_CHECK_AUDIO), None, f"{CHAT_URL}/v1", "tok", NEMOTRON, "chat"
        )
    )
    assert (language, text) == ("en", "Hello.")
    request = captured[0]
    assert str(request.url) == f"{CHAT_URL}/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer tok"
    body = json.loads(request.content)
    assert body["messages"][1]["content"][0]["input_audio"]["format"] == "wav"


def test_whisper_transcription_request(fake_server: Callable[..., list[httpx.Request]]) -> None:
    captured = fake_server(200, {"text": "Hello.", "language": "english"})
    language, text = asyncio.run(
        ai_client.request_transcription(
            str(ai_client.STT_CHECK_AUDIO), "en", "https://whisper.example.com", "", None
        )
    )
    assert (language, text) == ("english", "Hello.")
    request = captured[0]
    assert str(request.url) == "https://whisper.example.com/v1/audio/transcriptions"
    assert "Authorization" not in request.headers
    body = request.content.decode("latin-1")
    assert 'name="language"\r\n\r\nen' in body
    assert "Content-Type: audio/wav" in body
    assert "openai/whisper-large-v3" in body  # default model


def test_error_message_from_server_is_shown(
    fake_server: Callable[..., list[httpx.Request]],
) -> None:
    fake_server(403, {"message": "Forbidden :user is not allowed to access the resource"})
    language, text = asyncio.run(
        ai_client.transcribe_audio(
            str(ai_client.STT_CHECK_AUDIO), True, "", CHAT_URL, "tok", NEMOTRON, "chat"
        )
    )
    assert language == "Unset"
    assert "403: Forbidden :user is not allowed" in text
    assert "API format" in text


def test_whisper_route_missing_is_reported(
    fake_server: Callable[..., list[httpx.Request]],
) -> None:
    fake_server(404, {"detail": "Not Found"})
    _, text = asyncio.run(
        ai_client.transcribe_audio(
            str(ai_client.STT_CHECK_AUDIO), False, "English (en)", CHAT_URL, "", None
        )
    )
    assert "returned 404: Not Found" in text


def test_unknown_api_format_is_rejected() -> None:
    with pytest.raises(ai_client.TranscriptionError, match="unknown API format"):
        asyncio.run(ai_client.request_transcription("a.wav", None, CHAT_URL, None, None, "grpc"))


# --- Health check ------------------------------------------------------------


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("The patient reports a mild headache since this morning.", True),
        ("the patient reported a mild head ache since this morning", True),
        ("Thank you for watching.", False),
        ("", False),
    ],
)
def test_transcript_matches(heard: str, expected: bool) -> None:
    assert ai_client.transcript_matches(ai_client.STT_CHECK_PHRASE, heard) is expected


def test_check_clip_is_bundled() -> None:
    assert ai_client.STT_CHECK_AUDIO.read_bytes()[:4] == b"RIFF"


def _fake_transcription(
    monkeypatch: pytest.MonkeyPatch, result: tuple[str, str] | Exception
) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    async def fake(*args: Any) -> tuple[str, str]:
        calls.append(args)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(ai_client, "request_transcription", fake)
    return calls


def test_check_stt_passes_on_matching_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_transcription(monkeypatch, ("en", ai_client.STT_CHECK_PHRASE))
    ok, message = asyncio.run(ai_client.check_stt(CHAT_URL, "tok", NEMOTRON, STT_FORMAT_CHAT))
    assert ok
    assert "Transcription works" in message
    assert "English (en)" in message
    # The clip is sent without a language so detection is checked too.
    assert calls[0][1] is None
    assert calls[0][5] == STT_FORMAT_CHAT


def test_check_stt_fails_on_wrong_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_transcription(monkeypatch, ("Unknown", "Thank you for watching."))
    ok, message = asyncio.run(ai_client.check_stt(CHAT_URL, "", NEMOTRON, STT_FORMAT_WHISPER))
    assert not ok
    assert '"Thank you for watching."' in message


def test_check_stt_fails_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_transcription(monkeypatch, ai_client.TranscriptionError("API returned 415"))
    ok, message = asyncio.run(ai_client.check_stt(CHAT_URL, "", NEMOTRON, STT_FORMAT_WHISPER))
    assert not ok
    assert "415" in message


def test_check_stt_needs_url() -> None:
    ok, message = asyncio.run(ai_client.check_stt("", "", NEMOTRON, STT_FORMAT_CHAT))
    assert not ok
    assert "not configured" in message


# --- Configuration -----------------------------------------------------------


def test_saved_config_without_api_format_gets_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "api_config.json"
    config_file.write_text(
        json.dumps({"whisper": {"url": CHAT_URL, "token": "t", "model": NEMOTRON}})
    )
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))
    config = config_manager.load_config()
    assert config["whisper"]["api_format"] == STT_FORMAT_WHISPER
    assert config["whisper"]["model"] == NEMOTRON
    assert config["medgemma"]["model"] == "google/medgemma-4b-it"
