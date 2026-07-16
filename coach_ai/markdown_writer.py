"""
markdown_writer.py
===================
The ONLY module allowed to write markdown files back to the vault.

Per the spec: "The AI never edits markdown. It ONLY returns JSON.
Python updates markdown." This module is where that JSON becomes
markdown, and it does so surgically:
  - Only the sections named in a Stage5Output update are touched.
  - Every other section, and the preamble, is preserved exactly as it
    was parsed by memory_loader.py.
  - Nothing is written to disk until every update for a file has been
    applied in memory and re-serialized successfully, so a bad update
    can never leave a file half-written.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict

from config import VaultConfig
from models import MemoryFile, MemorySection, WeekRange
from schemas import LEGACY_MEMORY_FILE_ALIASES, Stage5Output, WeeklyReviewOutput

# Matches a "- Key: Value" bullet line, the field format used by
# action='update_fields' (Change #6). Kept module-level so both the
# writer and (if ever needed) diagnostics can reuse the exact same
# pattern the parser uses.
_FIELD_LINE_RE = re.compile(r"^-\s*(.+?):\s*(.*)$")


def apply_memory_updates(
    memory_files: Dict[str, MemoryFile], stage5: Stage5Output, logger: logging.Logger
) -> Dict[str, MemoryFile]:
    """
    Apply every MemoryFieldUpdate in `stage5` to an in-memory deep copy
    of `memory_files`. Returns the updated copy -- the caller decides
    when/whether to actually persist it via write_memory_file, so a
    failure partway through building the weekly review never results
    in partially-applied memory on disk.
    """
    updated = deepcopy(memory_files)

    for update in stage5.updates:
        # Change #1 backward compatibility: an update may still name the
        # retired 'productive_patterns' file; resolve it to its current
        # canonical key before doing anything else.
        file_key = LEGACY_MEMORY_FILE_ALIASES.get(update.file, update.file)

        mem = updated.get(file_key)
        if mem is None:
            logger.error(
                "Stage 5 update referenced unknown memory file '%s', skipping", update.file
            )
            continue

        if update.action == "remove":
            if update.section in mem.sections:
                del mem.sections[update.section]
                mem.section_order = [h for h in mem.section_order if h != update.section]
                logger.info("Removed section '%s' from %s", update.section, file_key)
            else:
                logger.warning(
                    "Stage 5 tried to remove nonexistent section '%s' in %s",
                    update.section,
                    file_key,
                )
            continue

        section = mem.get_or_create_section(update.section)

        if update.action == "replace":
            section.set_text(update.content)
            logger.info("Replaced section '%s' in %s", update.section, file_key)

        elif update.action == "append":
            if update.history_limit is not None:
                _append_with_history_limit(section, update.content, update.history_limit)
                logger.info(
                    "Appended to section '%s' in %s (history_limit=%d)",
                    update.section, file_key, update.history_limit,
                )
            else:
                # Original, unbounded append behavior -- unchanged, for
                # full backward compatibility with existing callers/tests
                # that never pass history_limit.
                existing = section.as_text()
                combined = f"{existing}\n{update.content}".strip("\n") if existing.strip() else update.content
                section.set_text(combined)
                logger.info("Appended to section '%s' in %s", update.section, file_key)

        elif update.action == "update_fields":
            # Change #6: the preferred update mechanism -- touch only the
            # named "- Key: Value" bullet lines, preserve everything else
            # in the section verbatim.
            fields = update.fields or {}
            if not fields:
                logger.warning(
                    "Stage 5 update_fields on '%s' in %s had no fields, skipping",
                    update.section, file_key,
                )
                continue
            _apply_field_updates(section, fields)
            logger.info(
                "Updated fields %s in section '%s' of %s",
                list(fields.keys()), update.section, file_key,
            )

    return updated


def _apply_field_updates(section: MemorySection, fields: Dict[str, object]) -> None:
    """
    Update only the named "- Key: Value" bullet lines within a section,
    preserving every other line untouched. If the section doesn't yet
    contain any field-formatted lines (e.g. it still holds the default
    "(not yet established)" placeholder), it is initialized fresh with
    exactly the given fields rather than appending fields after a
    placeholder that no longer applies.
    """
    lines = list(section.body_lines)
    has_field_lines = any(_FIELD_LINE_RE.match(line) for line in lines)

    if not has_field_lines:
        section.body_lines = [f"- {key}: {value}" for key, value in fields.items()]
        return

    remaining = dict(fields)
    for i, line in enumerate(lines):
        match = _FIELD_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip()
        if key in remaining:
            lines[i] = f"- {key}: {remaining.pop(key)}"

    # Any requested fields that didn't already exist as a line become
    # new lines appended at the end of the section.
    for key, value in remaining.items():
        lines.append(f"- {key}: {value}")

    section.body_lines = lines


# Entries appended under a history_limit are separated by a horizontal
# rule so they can be told apart and trimmed. Plain (unlimited) appends
# never use this delimiter, so existing sections/tests are unaffected.
_HISTORY_ENTRY_DELIMITER = "---"


def _append_with_history_limit(section: MemorySection, new_content: str, history_limit: int) -> None:
    """
    Change #7: append `new_content` as a new delimited entry, then keep
    only the newest `history_limit` entries (oldest are discarded).
    """
    existing_text = section.as_text()
    if existing_text.strip():
        entries = [e.strip() for e in existing_text.split(_HISTORY_ENTRY_DELIMITER) if e.strip()]
    else:
        entries = []

    entries.append(new_content.strip())
    if len(entries) > history_limit:
        entries = entries[-history_limit:]

    section.set_text(f"\n\n{_HISTORY_ENTRY_DELIMITER}\n\n".join(entries))


def render_memory_file(mem: MemoryFile) -> str:
    """Reconstruct the full markdown text of a memory file from its
    preamble + ordered sections. This is the inverse of
    memory_loader.parse_memory_markdown."""
    parts = []
    if mem.preamble.strip():
        parts.append(mem.preamble.rstrip("\n"))

    for heading in mem.section_order:
        section = mem.sections.get(heading)
        if section is None:
            continue
        body = section.as_text()
        parts.append(f"## {heading}\n\n{body}" if body else f"## {heading}\n")

    text = "\n\n".join(p for p in parts if p is not None)
    return text.rstrip("\n") + "\n"


def write_memory_file(mem: MemoryFile, logger: logging.Logger) -> None:
    """Serialize and persist a single MemoryFile to disk."""
    text = render_memory_file(mem)
    mem.file_path.parent.mkdir(parents=True, exist_ok=True)
    mem.file_path.write_text(text, encoding="utf-8")
    logger.info("Wrote memory file: %s", mem.file_path)


def write_all_memory_files(memory_files: Dict[str, MemoryFile], logger: logging.Logger) -> None:
    for mem in memory_files.values():
        write_memory_file(mem, logger)


# ---------------------------------------------------------------------------
# Weekly review
# ---------------------------------------------------------------------------


def _render_bullet_list(items) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def _render_bullet_dict(mapping: Dict[str, object]) -> str:
    """Renders a name->value mapping (goal_momentum, goal_mention_frequency)
    as the same bullet-list style used elsewhere, so the review stays
    visually consistent without introducing a second rendering format."""
    if not mapping:
        return "- (none)"
    return "\n".join(f"- {name}: {value}" for name, value in mapping.items())


def render_weekly_review_markdown(week: WeekRange, review: WeeklyReviewOutput) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""# {review.title}

**Week:** {review.week_range}
**Generated:** {generated_at}
**Overall Momentum:** {review.overall_momentum}

## Overview

{review.overview}

## Key Wins

{_render_bullet_list(review.key_wins)}

## Key Struggles

{_render_bullet_list(review.key_struggles)}

## Behavioral Insights

{_render_bullet_list(review.behavioral_insights)}

## Identity Shifts

{_render_bullet_list(review.identity_shifts)}

## Goal Progress

{_render_bullet_list(review.goal_progress)}

## Goal Momentum

{_render_bullet_dict(review.goal_momentum)}

## Goal Mention Frequency

{_render_bullet_dict(review.goal_mention_frequency)}

## Trading Insights

{_render_bullet_list(review.trading_insights)}

## Biggest Contradictions

{_render_bullet_list(review.biggest_contradictions)}

## Behavioral Model Changes

**Strengthened:**
{_render_bullet_list(review.hypotheses_strengthened)}

**Weakened:**
{_render_bullet_list(review.hypotheses_weakened)}

**New:**
{_render_bullet_list(review.hypotheses_new)}

**Retired:**
{_render_bullet_list(review.hypotheses_retired)}

## Changes Since Last Week

{_render_bullet_list(review.changes_since_last_week)}

## Reflection Questions

{_render_bullet_list(review.reflection_questions)}

## Action Items For Next Week

{_render_bullet_list(review.action_items_next_week)}
"""


def write_weekly_review(
    vault: VaultConfig, week: WeekRange, review: WeeklyReviewOutput, logger: logging.Logger
) -> Path:
    vault.weekly_reviews_dir.mkdir(parents=True, exist_ok=True)
    out_path = vault.weekly_reviews_dir / f"{week.label()}_weekly_review.md"
    out_path.write_text(render_weekly_review_markdown(week, review), encoding="utf-8")
    logger.info("Wrote weekly review: %s", out_path)
    return out_path
