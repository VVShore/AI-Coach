"""
journal_loader.py
==================
Reads Daily Journal / Trade Journal markdown notes from the vault and
returns only the ones that fall inside the target WeekRange.

Date resolution strategy (in priority order) for each .md file:
  1. Filename starts with an ISO date, e.g. "2026-07-06.md" or
     "2026-07-06 Sunday.md".
  2. An ISO date appears anywhere in the filename, e.g.
     "Trade Log 2026-07-06.md".
  3. A YAML frontmatter `date:` field, e.g.
        ---
        date: 2026-07-06
        ---
  4. If none of the above yield a parseable date, the file is skipped
     and a warning is logged -- we never guess, since silently
     mis-dating a journal entry would corrupt the weekly analysis.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from models import JournalEntry, WeekRange

_FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_FRONTMATTER_DATE_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL
)
_FRONTMATTER_FIELD_DATE_RE = re.compile(
    r"^\s*date\s*:\s*[\"']?(\d{4}-\d{2}-\d{2})[\"']?\s*$", re.MULTILINE
)


def _extract_date_from_filename(path: Path) -> Optional[date]:
    match = _FILENAME_DATE_RE.search(path.stem)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_date_from_frontmatter(text: str) -> Optional[date]:
    fm_match = _FRONTMATTER_DATE_RE.match(text)
    if not fm_match:
        return None
    field_match = _FRONTMATTER_FIELD_DATE_RE.search(fm_match.group(1))
    if not field_match:
        return None
    try:
        return datetime.strptime(field_match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def resolve_entry_date(path: Path, raw_text: str) -> Optional[date]:
    """Public so tests / other tooling can reuse the exact same
    date-resolution rules the loader uses."""
    d = _extract_date_from_filename(path)
    if d is not None:
        return d
    return _extract_date_from_frontmatter(raw_text)


def _load_entries_from_dir(
    directory: Path, kind: str, week: WeekRange, logger: logging.Logger
) -> List[JournalEntry]:
    entries: List[JournalEntry] = []

    if not directory.exists():
        logger.warning("Journal directory does not exist, skipping: %s", directory)
        return entries

    for path in sorted(directory.glob("*.md")):
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            continue

        entry_date = resolve_entry_date(path, raw_text)
        if entry_date is None:
            logger.warning(
                "Skipping %s: could not resolve a date from filename or frontmatter", path
            )
            continue

        if not week.contains(entry_date):
            continue

        entries.append(
            JournalEntry(entry_date=entry_date, file_path=path, raw_text=raw_text, kind=kind)
        )

    entries.sort(key=lambda e: e.entry_date)
    logger.info("Loaded %d %s journal entr%s for %s", len(entries), kind, "y" if len(entries) == 1 else "ies", week)
    return entries


def load_daily_journal_entries(
    daily_journal_dir: Path, week: WeekRange, logger: logging.Logger
) -> List[JournalEntry]:
    return _load_entries_from_dir(daily_journal_dir, kind="daily", week=week, logger=logger)


def load_trade_journal_entries(
    trade_journal_dir: Path, week: WeekRange, logger: logging.Logger
) -> List[JournalEntry]:
    return _load_entries_from_dir(trade_journal_dir, kind="trade", week=week, logger=logger)


def format_entries_for_prompt(entries: List[JournalEntry]) -> str:
    """Render a list of JournalEntry objects into a single text block
    suitable for embedding in a prompt template. Each entry is clearly
    delimited so the LLM can attribute content to the correct date."""
    if not entries:
        return "(no entries found for this week)"

    blocks = []
    for entry in entries:
        blocks.append(
            f"--- {entry.kind.upper()} JOURNAL: {entry.entry_date.isoformat()} "
            f"({entry.file_path.name}) ---\n{entry.raw_text.strip()}\n"
        )
    return "\n".join(blocks)
