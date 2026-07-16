"""
utils.py
========
Small, dependency-light helpers shared across the codebase:
  - logging setup (one timestamped log file per run)
  - "previous week" date range calculation
  - robust JSON extraction from raw LLM text (LLMs love wrapping JSON
    in ```json fences or adding a stray sentence before/after it)
  - a Timer context manager for consistent duration logging
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from models import WeekRange

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging(logs_dir: Path, run_timestamp: Optional[datetime] = None) -> logging.Logger:
    """
    Create logs/<timestamp>.log and return a configured logger that
    writes to both that file and stdout.

    Every run gets its own file per the spec ("Every run creates
    timestamp.log"), so runs never clobber each other's history.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = run_timestamp or datetime.now()
    log_path = logs_dir / f"{ts.strftime('%Y-%m-%dT%H-%M-%S')}.log"

    logger = logging.getLogger("coach_ai")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # avoid duplicate handlers if setup_logging is called twice in a process

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    logger.info("Log file: %s", log_path)
    return logger


# ---------------------------------------------------------------------------
# Week range calculation
# ---------------------------------------------------------------------------


def get_previous_week_range(today: Optional[date] = None, week_starts_on_monday: bool = True) -> WeekRange:
    """
    Return the WeekRange for "last week" relative to `today` (defaults
    to the real current date).

    If week_starts_on_monday: weeks run Mon-Sun. "Previous week" is
    always the most recently *completed* Mon-Sun block, regardless of
    what day `today` falls on. Example: if today is Wednesday
    2026-07-15, the current week started Monday 2026-07-13, so the
    previous (completed) week is 2026-07-06 .. 2026-07-12.
    """
    today = today or date.today()
    weekday = today.weekday()  # Monday=0 .. Sunday=6

    if week_starts_on_monday:
        this_week_start = today - timedelta(days=weekday)
    else:
        # Week starts Sunday: Sunday=6 in weekday(), shift so Sunday=0
        shifted = (weekday + 1) % 7
        this_week_start = today - timedelta(days=shifted)

    previous_week_start = this_week_start - timedelta(days=7)
    previous_week_end = this_week_start - timedelta(days=1)
    return WeekRange(start=previous_week_start, end=previous_week_end)


# ---------------------------------------------------------------------------
# JSON extraction from raw LLM text
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_block(raw_text: str) -> str:
    """
    Best-effort extraction of a JSON object from raw LLM text.

    Handles the common failure modes:
      1. Clean JSON with nothing else -> returned as-is (stripped).
      2. JSON wrapped in a ```json ... ``` or ``` ... ``` fence -> the
         fenced content is extracted.
      3. JSON with leading/trailing prose ("Here is the JSON:\n{...}\n
         Let me know if...") -> we locate the first '{' and the
         matching last '}' via brace counting and slice between them.

    This function does NOT validate the JSON -- it only isolates the
    most likely candidate substring. Validation happens in
    json_validator.py, which is what actually decides pass/fail.
    """
    text = raw_text.strip()
    if not text:
        return text

    fence_match = _FENCE_RE.search(text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        if candidate:
            text = candidate

    first_brace = text.find("{")
    if first_brace == -1:
        return text  # no object found at all; let json.loads raise a clear error upstream

    # Walk forward counting brace depth to find the matching close,
    # respecting strings so braces inside quoted text don't confuse us.
    depth = 0
    in_string = False
    escape = False
    end_index = -1
    for i in range(first_brace, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_index = i
                break

    if end_index == -1:
        # Unbalanced braces -- return what we have; json.loads will
        # raise a descriptive error that the validator will surface.
        return text[first_brace:]

    return text[first_brace : end_index + 1]


def try_parse_json(raw_text: str):
    """Extract + parse. Returns (data_or_None, error_message_or_None)."""
    candidate = extract_json_block(raw_text)
    try:
        return json.loads(candidate), None
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: {exc}"


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


@contextmanager
def Timer() -> Iterator["_TimerResult"]:
    """Usage:
        with Timer() as t:
            do_work()
        print(t.duration_seconds)
    """
    result = _TimerResult()
    start = time.monotonic()
    try:
        yield result
    finally:
        result.duration_seconds = time.monotonic() - start


class _TimerResult:
    def __init__(self) -> None:
        self.duration_seconds: float = 0.0


def approx_token_count(text: str) -> int:
    """Rough token estimate (chars/4) used only for logging context-
    window usage -- not exact, Ollama doesn't expose a cheap tokenizer
    call before generation."""
    return max(1, len(text) // 4)
