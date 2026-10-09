"""Parsing and validation of MedGemma output for the TriageAI feature.

This module is pure: it imports no Gradio, httpx or logging code so that it
can be unit-tested without the application running.

MedGemma 1.5 served through Ollama's stock template emits its internal
reasoning as plain text (``<unused94> thought ... <unused95>``) before the
answer. The request side avoids that with a JSON-schema ``response_format``;
this module is the safety net for backends that ignore it.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class LlmOutputError(ValueError):
    """Raised when model output cannot be turned into a valid triage record.

    The message is written for the person using the UI.
    """


class Severity(StrEnum):
    """Triage severity levels accepted by the ``triage`` table."""

    MILD = "Mild"
    MODERATE = "Moderate"
    SEVERE = "Severe"
    CRITICAL = "Critical"


_LIST_FIELDS = ("secondary_diagnoses", "recommended_tests", "recommended_treatment")
_OPTIONAL_TEXT_FIELDS = (
    "patient_name",
    "date_of_birth",
    "visit_time",
    "follow_up",
    "medical_reasoning",
)
_UNKNOWN_VALUES = frozenset({"", "unknown", "n/a", "na", "none", "null", "not stated"})

TRIAGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "patient_name": {
            "type": "string",
            "description": "Full name of the patient, or an empty string if not stated.",
        },
        "date_of_birth": {
            "type": "string",
            "description": "Date of birth as YYYY-MM-DD, or an empty string if unknown.",
        },
        "visit_time": {
            "type": "string",
            "description": "Visit time as YYYY-MM-DD HH:MM:SS, or an empty string if unknown.",
        },
        "severity": {"type": "string", "enum": [level.value for level in Severity]},
        "primary_diagnosis": {"type": "string"},
        "secondary_diagnoses": {"type": "array", "items": {"type": "string"}},
        "recommended_tests": {"type": "array", "items": {"type": "string"}},
        "recommended_treatment": {"type": "array", "items": {"type": "string"}},
        "follow_up": {"type": "string"},
        "medical_reasoning": {"type": "string"},
    },
    "required": [
        "patient_name",
        "date_of_birth",
        "visit_time",
        "severity",
        "primary_diagnosis",
        "secondary_diagnoses",
        "recommended_tests",
        "recommended_treatment",
        "follow_up",
        "medical_reasoning",
    ],
    "additionalProperties": False,
}

# Reasoning blocks as emitted by Gemma-family models (MedGemma 1.5) and by
# models that use <think> tags. An unterminated block runs to the end of text.
_REASONING_PATTERNS = (
    re.compile(r"<unused94>.*?(?:<unused95>|\Z)", re.DOTALL),
    re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL),
)
_REASONING_MARKERS = re.compile(r"<unused94>\s*thought\s*|<unused94>|<unused95>|</?think>")


def strip_reasoning(text: str) -> tuple[str, str]:
    """Separate reasoning blocks from the visible answer.

    Args:
        text: Raw assistant content.

    Returns:
        A ``(visible, reasoning)`` pair. ``reasoning`` is empty when the text
        contains no reasoning block.
    """
    reasoning_parts: list[str] = []
    visible = text
    for pattern in _REASONING_PATTERNS:
        for match in pattern.finditer(visible):
            cleaned = _REASONING_MARKERS.sub("", match.group(0)).strip()
            if cleaned:
                reasoning_parts.append(cleaned)
        visible = pattern.sub("", visible)
    return visible.strip(), "\n\n".join(reasoning_parts)


def extract_json_object(text: str) -> dict[str, Any]:
    """Return the first complete JSON object found in ``text``.

    Markdown fences and surrounding prose are ignored because the scan starts
    at each ``{`` and tracks brace depth while respecting string literals.

    Args:
        text: Text that should contain a JSON object.

    Returns:
        The decoded object.

    Raises:
        LlmOutputError: If no object is found, the object is truncated, or it
            is not valid JSON.
    """
    truncated = False
    last_error: str | None = None
    start = text.find("{")
    while start != -1:
        end = _find_matching_brace(text, start)
        if end is None:
            truncated = True
            break
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = f"{exc.msg} (line {exc.lineno}, column {exc.colno})"
        else:
            if isinstance(parsed, dict):
                return parsed
            last_error = "the JSON value is not an object"
        start = text.find("{", start + 1)

    if truncated:
        raise LlmOutputError(
            "The model response was cut off before the JSON object was complete. "
            "Run the analysis again."
        )
    if last_error is not None:
        raise LlmOutputError(f"The model response is not valid JSON: {last_error}.")
    raise LlmOutputError("The model response contains no JSON object.")


def _find_matching_brace(text: str, start: int) -> int | None:
    """Return the index of the brace closing the object opened at ``start``."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


class TriageResult(BaseModel):
    """A validated triage record, as stored in the ``triage`` table."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    patient_name: str | None = None
    date_of_birth: date | None = None
    visit_time: datetime | None = None
    severity: Severity
    primary_diagnosis: str = Field(min_length=1)
    secondary_diagnoses: list[str] = Field(default_factory=list)
    recommended_tests: list[str] = Field(default_factory=list)
    recommended_treatment: list[str] = Field(default_factory=list)
    follow_up: str | None = None
    medical_reasoning: str | None = None

    @field_validator(*_OPTIONAL_TEXT_FIELDS, mode="before")
    @classmethod
    def _unknown_to_none(cls, value: object) -> object:
        """Map placeholder strings such as "" or "Unknown" to ``None``."""
        if isinstance(value, str) and value.strip().lower() in _UNKNOWN_VALUES:
            return None
        return value

    @field_validator("severity", mode="before")
    @classmethod
    def _normalise_severity(cls, value: object) -> object:
        """Accept any capitalisation of the four severity levels."""
        if isinstance(value, str):
            wanted = value.strip().lower()
            for level in Severity:
                if level.value.lower() == wanted:
                    return level
        return value

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> object:
        """Accept ISO dates and date-times for the date of birth."""
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.strip()).date()
            except ValueError:
                return value
        return value

    @field_validator("visit_time", mode="before")
    @classmethod
    def _parse_datetime(cls, value: object) -> object:
        """Accept ``YYYY-MM-DD HH:MM:SS``, ISO 8601 and date-only strings."""
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.strip())
            except ValueError:
                return value
        return value

    @field_validator(*_LIST_FIELDS, mode="before")
    @classmethod
    def _coerce_list(cls, value: object) -> object:
        """Accept a single string or ``None`` where a list is expected."""
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [] if text.lower() in _UNKNOWN_VALUES else [text]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return value

    def to_db_row(
        self,
    ) -> tuple[
        str | None,
        date | None,
        datetime | None,
        str,
        str,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
    ]:
        """Return the record as positional parameters for the ``triage`` INSERT.

        Lists are joined with commas; empty values become ``None`` (SQL NULL).
        """
        return (
            self.patient_name,
            self.date_of_birth,
            self.visit_time,
            self.severity.value,
            self.primary_diagnosis,
            _join(self.secondary_diagnoses),
            _join(self.recommended_tests),
            _join(self.recommended_treatment),
            self.follow_up,
            self.medical_reasoning,
        )


def _join(items: list[str]) -> str | None:
    """Join list items for a TEXT column, or ``None`` when the list is empty."""
    return ", ".join(items) if items else None


def parse_triage_output(raw: str) -> TriageResult:
    """Turn raw model output into a validated :class:`TriageResult`.

    Reasoning blocks are removed, the first JSON object is extracted and the
    result is validated. The function is idempotent on the pretty-printed JSON
    produced by :meth:`TriageResult.model_dump_json`.

    Args:
        raw: Assistant content, or text pasted into the UI.

    Returns:
        The validated triage record.

    Raises:
        LlmOutputError: If the text holds no usable triage record.
    """
    if not raw or not raw.strip():
        raise LlmOutputError("The model returned an empty response.")
    visible, _ = strip_reasoning(raw)
    data = extract_json_object(visible or raw)
    try:
        return TriageResult.model_validate(data)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error.get("loc")})
        raise LlmOutputError(
            "The model response has missing or invalid fields: " + ", ".join(fields) + "."
        ) from exc
