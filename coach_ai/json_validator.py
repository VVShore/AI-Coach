"""
json_validator.py
==================
The trust boundary between the LLM and the rest of the system.

Nothing downstream (pipeline.py, markdown_writer.py) is allowed to
touch raw text from Ollama. Everything must pass through
`validate_llm_json`, which:
  1. Extracts a JSON object from the raw text (handles fences/prose).
  2. Parses it.
  3. Validates it against the Pydantic schema for the current stage.

Any failure at any step returns a ValidationResult with success=False
and a human-readable error the pipeline can feed back into a retry
prompt ("Your last response was invalid because: ...").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from utils import try_parse_json

T = TypeVar("T", bound=BaseModel)


@dataclass
class ValidationResult:
    success: bool
    data: Optional[BaseModel]
    error: Optional[str]
    raw_text: str


def validate_llm_json(raw_text: str, schema: Type[T]) -> ValidationResult:
    """
    Attempt to extract, parse, and validate `raw_text` against
    `schema`. Never raises -- all failure modes are captured in the
    returned ValidationResult so callers can decide whether to retry.
    """
    parsed, parse_error = try_parse_json(raw_text)
    if parse_error is not None:
        return ValidationResult(
            success=False,
            data=None,
            error=f"Could not parse JSON from model output: {parse_error}",
            raw_text=raw_text,
        )

    if not isinstance(parsed, dict):
        return ValidationResult(
            success=False,
            data=None,
            error=(
                "Model output parsed as JSON but was not a JSON object "
                f"(got {type(parsed).__name__}). Expected a single JSON object."
            ),
            raw_text=raw_text,
        )

    try:
        validated = schema.model_validate(parsed)
    except ValidationError as exc:
        return ValidationResult(
            success=False,
            data=None,
            error=_format_pydantic_error(exc),
            raw_text=raw_text,
        )

    return ValidationResult(success=True, data=validated, error=None, raw_text=raw_text)


def _format_pydantic_error(exc: ValidationError) -> str:
    """Turn a pydantic ValidationError into a compact, LLM-readable
    bullet list -- this text gets re-injected into the retry prompt,
    so it needs to be short and specific, not a giant stack trace."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"- field '{loc}': {err['msg']}")
    return "Schema validation failed:\n" + "\n".join(lines)
