"""
models.py
=========
Plain dataclasses that flow through the pipeline. These are the
internal domain objects built from files on disk. They are distinct
from schemas.py, which holds the Pydantic models used to validate
*LLM output*.

Keeping these separate matters: models.py can change shape freely as
the app grows (new fields, new file kinds) without touching the
contract the LLM is held to, and vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class WeekRange:
    """Inclusive Monday-Sunday (or configured start day) date range
    representing 'the previous week' the pipeline operates on."""

    start: date
    end: date

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def label(self) -> str:
        """Filesystem/markdown-safe label, e.g. '2026-07-06_to_2026-07-12'."""
        return f"{self.start.isoformat()}_to_{self.end.isoformat()}"

    def __str__(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


@dataclass
class JournalEntry:
    """A single daily-journal or trade-journal note pulled from the
    vault for the target week."""

    entry_date: date
    file_path: Path
    raw_text: str
    kind: str  # "daily" or "trade"


@dataclass
class MemorySection:
    """One '## Heading' section of a memory markdown file, stored as
    its raw body lines so we can reconstruct the file byte-for-byte
    when a section is untouched."""

    heading: str
    body_lines: List[str]

    def as_text(self) -> str:
        # Strip leading AND trailing blank lines (not internal ones):
        # the blank line immediately after a '## Heading' and the blank
        # line immediately before the next heading are structural
        # separators, not part of the section's actual content.
        return "\n".join(self.body_lines).strip("\n")

    def set_text(self, text: str) -> None:
        self.body_lines = text.rstrip("\n").split("\n")


@dataclass
class MemoryFile:
    """
    Parsed representation of a memory markdown file.

    We keep:
      - raw_text: exact original content, for safe fallback/debugging
      - preamble: any content before the first '## ' heading (title,
        frontmatter, intro sentence, etc.)
      - sections: ordered dict of heading -> MemorySection
      - section_order: explicit ordering, since dicts in older tooling
        or serialization can't always be trusted to preserve insertion
        order end-to-end; we track it defensively.

    Only sections named by a Stage 5 update are ever touched when
    writing back to disk -- everything else, including ordering and
    exact whitespace of untouched sections, is preserved.
    """

    name: str
    file_path: Path
    raw_text: str
    preamble: str
    sections: Dict[str, MemorySection] = field(default_factory=dict)
    section_order: List[str] = field(default_factory=list)

    def get_or_create_section(self, heading: str) -> MemorySection:
        if heading not in self.sections:
            self.sections[heading] = MemorySection(heading=heading, body_lines=[""])
            self.section_order.append(heading)
        return self.sections[heading]


@dataclass
class PipelineArtifacts:
    """
    Accumulates the output of every stage as the pipeline runs. This
    single object is threaded through pipeline.py so each stage has
    full visibility into everything produced before it, and main.py
    has one place to look for the final results.
    """

    week: WeekRange
    daily_entries: List[JournalEntry]
    trade_entries: List[JournalEntry]
    memory_files: Dict[str, MemoryFile]

    stage1_summary: Optional[dict] = None
    stage2_behavior: Optional[dict] = None
    stage3_identity: Optional[dict] = None
    stage4_goals: Optional[dict] = None
    stage5_memory_updates: Optional[dict] = None
    stage6_weekly_review: Optional[dict] = None
