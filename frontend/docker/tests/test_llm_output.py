"""Unit tests for llm_output: reasoning stripping, JSON extraction and validation."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

import ai_client
from llm_output import (
    TRIAGE_JSON_SCHEMA,
    LlmOutputError,
    Severity,
    TriageResult,
    extract_json_object,
    parse_triage_output,
    strip_reasoning,
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_OUTPUT = (FIXTURES / "medgemma_thought_json.txt").read_text()
# The live failure mode: the reasoning consumed the token budget and the JSON was cut mid-string.
TRUNCATED_OUTPUT = REAL_OUTPUT[: REAL_OUTPUT.index('"Sputum culture"') + 6]

VALID_RECORD = {
    "patient_name": "Amira Haddad",
    "date_of_birth": "1978-03-14",
    "visit_time": "2026-10-09 09:30:00",
    "severity": "Moderate",
    "primary_diagnosis": "Community-acquired pneumonia",
    "secondary_diagnoses": ["Hypoxia"],
    "recommended_tests": ["Chest X-ray"],
    "recommended_treatment": ["Antibiotics"],
    "follow_up": "Review in 48 hours.",
    "medical_reasoning": "Fever and focal crackles.",
}


# --- strip_reasoning -------------------------------------------------------


def test_strip_reasoning_separates_medgemma_thought_block() -> None:
    visible, reasoning = strip_reasoning(REAL_OUTPUT)
    assert visible.startswith("```json")
    assert visible.rstrip().endswith("```")
    assert reasoning.startswith("The user wants me to analyze clinical notes")
    assert "<unused94>" not in visible and "<unused95>" not in visible
    assert "<unused94>" not in reasoning and "thought\n" not in reasoning[:10]


def test_strip_reasoning_unterminated_block_consumes_to_end() -> None:
    visible, reasoning = strip_reasoning("<unused94> thought\nstill thinking {")
    assert visible == ""
    assert reasoning == "still thinking {"


def test_strip_reasoning_handles_think_tags() -> None:
    visible, reasoning = strip_reasoning('<think>\nplan\n</think>\n{"a": 1}')
    assert visible == '{"a": 1}'
    assert reasoning == "plan"


def test_strip_reasoning_passthrough_without_markers() -> None:
    assert strip_reasoning('{"a": 1}') == ('{"a": 1}', "")


# --- extract_json_object ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',  # bare fence: the old implementation returned "" here
        'Here is the result:\n{"a": 1}\nLet me know if you need more.',
        '{"a": "value with } brace and \\" quote", "b": {"nested": [1, 2]}}',
    ],
)
def test_extract_json_object_finds_object(text: str) -> None:
    result = extract_json_object(text)
    assert result["a"] is not None


def test_extract_json_object_skips_earlier_invalid_candidates() -> None:
    text = 'Notes mention {not json} before the answer {"a": 1}'
    assert extract_json_object(text) == {"a": 1}


def test_extract_json_object_truncated_raises() -> None:
    with pytest.raises(LlmOutputError, match="cut off"):
        extract_json_object(TRUNCATED_OUTPUT)


def test_extract_json_object_without_object_raises() -> None:
    with pytest.raises(LlmOutputError, match="no JSON object"):
        extract_json_object("The patient should rest.")


def test_extract_json_object_rejects_json_array() -> None:
    with pytest.raises(LlmOutputError, match="no JSON object"):
        extract_json_object("[1, 2, 3]")


# --- parse_triage_output ---------------------------------------------------


def test_parse_triage_output_real_sample() -> None:
    result = parse_triage_output(REAL_OUTPUT)
    assert result.patient_name == "Amira Haddad"
    assert result.date_of_birth == date(1978, 3, 14)
    assert result.visit_time == datetime(2026, 10, 9, 9, 30)
    assert result.severity is Severity.MODERATE
    assert result.recommended_tests[0] == "Chest X-ray"
    assert len(result.recommended_treatment) == 4


def test_parse_triage_output_round_trips_pretty_json() -> None:
    first = parse_triage_output(REAL_OUTPUT)
    second = parse_triage_output(first.model_dump_json(indent=2))
    assert second == first


def test_parse_triage_output_truncated_raises() -> None:
    with pytest.raises(LlmOutputError, match="cut off"):
        parse_triage_output(TRUNCATED_OUTPUT)


def test_parse_triage_output_empty_raises() -> None:
    with pytest.raises(LlmOutputError, match="empty"):
        parse_triage_output("   ")


def test_parse_triage_output_names_invalid_fields() -> None:
    record = dict(VALID_RECORD, severity="Urgent")
    with pytest.raises(LlmOutputError, match="severity"):
        parse_triage_output(json.dumps(record))


# --- TriageResult ----------------------------------------------------------


@pytest.mark.parametrize("value", ["severe", "SEVERE", " Severe "])
def test_severity_is_case_insensitive(value: str) -> None:
    result = TriageResult.model_validate(dict(VALID_RECORD, severity=value))
    assert result.severity is Severity.SEVERE


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-09 09:30:00", datetime(2026, 10, 9, 9, 30)),
        ("2026-10-09T09:30:00", datetime(2026, 10, 9, 9, 30)),
        ("2026-10-09", datetime(2026, 10, 9)),
        ("", None),
        ("Unknown", None),
        ("N/A", None),
    ],
)
def test_visit_time_formats(value: str, expected: datetime | None) -> None:
    result = TriageResult.model_validate(dict(VALID_RECORD, visit_time=value))
    assert result.visit_time == expected


def test_date_of_birth_accepts_datetime_string() -> None:
    result = TriageResult.model_validate(dict(VALID_RECORD, date_of_birth="1978-03-14T00:00:00"))
    assert result.date_of_birth == date(1978, 3, 14)


def test_unparseable_date_is_reported() -> None:
    with pytest.raises(LlmOutputError, match="date_of_birth"):
        parse_triage_output(json.dumps(dict(VALID_RECORD, date_of_birth="14/03/1978")))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hypoxia", ["Hypoxia"]),
        (None, []),
        ("", []),
        (["Hypoxia", "", "  Sepsis "], ["Hypoxia", "Sepsis"]),
    ],
)
def test_list_fields_are_coerced(value: object, expected: list[str]) -> None:
    result = TriageResult.model_validate(dict(VALID_RECORD, secondary_diagnoses=value))
    assert result.secondary_diagnoses == expected


def test_extra_keys_are_ignored_and_primary_diagnosis_required() -> None:
    assert TriageResult.model_validate(dict(VALID_RECORD, confidence=0.9))
    with pytest.raises(LlmOutputError, match="primary_diagnosis"):
        parse_triage_output(json.dumps(dict(VALID_RECORD, primary_diagnosis="")))


def test_to_db_row_joins_lists_and_uses_null_for_empty() -> None:
    result = TriageResult.model_validate(
        dict(VALID_RECORD, secondary_diagnoses=[], follow_up="", recommended_tests=["A", "B"])
    )
    row = result.to_db_row()
    assert len(row) == 10
    assert row[3] == "Moderate"
    assert row[5] is None  # secondary_diagnoses
    assert row[6] == "A, B"  # recommended_tests
    assert row[8] is None  # follow_up


def test_schema_matches_model_fields() -> None:
    assert set(TRIAGE_JSON_SCHEMA["properties"]) == set(TriageResult.model_fields)
    assert set(TRIAGE_JSON_SCHEMA["required"]) == set(TriageResult.model_fields)
    assert TRIAGE_JSON_SCHEMA["properties"]["severity"]["enum"] == [s.value for s in Severity]


# --- ai_client helpers -----------------------------------------------------


def test_extract_choice_raises_when_output_was_cut_off() -> None:
    result = {"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}
    with pytest.raises(LlmOutputError, match="cut off"):
        ai_client._extract_choice(result)


def test_extract_choice_returns_content_and_reason() -> None:
    result = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    assert ai_client._extract_choice(result) == ("{}", "stop")


def test_build_triage_payload_requests_json_schema() -> None:
    payload = ai_client._build_triage_payload("notes", "medgemma1.5:4b")
    assert payload["model"] == "medgemma1.5:4b"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] is TRIAGE_JSON_SCHEMA
    assert payload["max_tokens"] >= 2048


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://ollama.example.com", "https://ollama.example.com/v1/chat/completions"),
        ("https://ollama.example.com/", "https://ollama.example.com/v1/chat/completions"),
        ("https://ollama.example.com/v1", "https://ollama.example.com/v1/chat/completions"),
        (
            "https://ollama.example.com/v1/chat/completions",
            "https://ollama.example.com/v1/chat/completions",
        ),
    ],
)
def test_get_api_url_handles_trailing_v1(base: str, expected: str) -> None:
    assert ai_client._get_api_url(base) == expected
    assert ai_client._get_api_url(base, "/v1/models") == expected.replace(
        "/chat/completions", "/models"
    )
