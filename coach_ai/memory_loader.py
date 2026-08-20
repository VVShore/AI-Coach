"""
memory_loader.py
=================
Parses each AI/Memory/*.md file into a MemoryFile: a preamble (content
before the first '## ' heading) plus an ordered collection of
MemorySection objects keyed by heading text.

This parser is intentionally simple and format-strict, per the spec
("Every memory file follows the exact same structure"). It only
recognizes level-2 headings ('## Heading') as section boundaries --
this matches the structure produced by `markdown_writer.create_default_memory_files`
and is the contract the whole system is built around. If you use a
different heading level in your vault, update `_SECTION_HEADING_RE`
here (and nowhere else) to match.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict

from config import VaultConfig
from models import MemoryFile, MemorySection

_SECTION_HEADING_RE = re.compile(r"^##\s+(.*?)\s*$")

# Default skeletons written the first time a memory file doesn't exist
# yet, so a brand-new vault can run the pipeline immediately instead
# of crashing on FileNotFoundError. Content is intentionally minimal;
# Stage 5 fills these in over time.
DEFAULT_MEMORY_TEMPLATES: Dict[str, str] = {
    # v1 production design. Every section is either:
    #   (a) a fixed, evidence-based list category (identity_profile,
    #       observed_patterns) -- starts genuinely empty, grows via
    #       'append' (optionally bounded with 'history_limit'); or
    #   (b) a fixed set of '- Key: Value' fields (trader_profile) --
    #       pre-populated with hedged placeholder values so the very
    #       first Stage 5 update can already use 'update_fields'; or
    #   (c) a dynamic, per-entity section created on demand (active_goals,
    #       behavioral_hypotheses) -- the file ships with zero live
    #       sections; Stage 5 creates one named section per goal/
    #       hypothesis (e.g. a section titled 'Trading Bot' or 'H001')
    #       the first time it has evidence for it, exactly matching the
    #       field-level update example from the original spec.
    # All explanatory text lives in each file's preamble (before the
    # first '## ' heading), which no update action ever touches, so it
    # stays accurate regardless of how much data accumulates below it.
    "identity_profile": (
        "# Identity Profile\n"
        "\n"
        "Evidence-based record of identity signals drawn from journal entries: what is stated repeatedly, what is aspired to, what is actually observed in behavior, and where the two disagree. Entries are only added when there is direct journal evidence, and confidence is expected to shift gradually rather than jump. New observations are appended to the relevant section below (use `history_limit` on append if a section should only retain the most recent N entries); a whole section is only replaced outright when a correction is warranted, not as the default update path.\n"
        "\n"
        "## Repeated Identity Statements\n"
        "\n"
        "## Desired Identity\n"
        "\n"
        "## Observed Identity\n"
        "\n"
        "## Identity Conflicts\n"
        "\n"
        "## Identity Changes\n"
    ),
    "active_goals": (
        "# Active Goals\n"
        "\n"
        "Each tracked goal gets its own section below, named after the goal itself (for example a section titled `Trading Bot`), so its fields can be updated individually via `update_fields` without touching any other goal. A goal section is created the first time Stage 5 finds evidence for it, and typically carries these fields:\n"
        "\n"
        "- Status: recurring | emerging | completed | inactive\n"
        "- Mention Count: running count of journal mentions\n"
        "- Momentum: increasing | stable | decreasing\n"
        "- First Mentioned: ISO date\n"
        "- Last Mentioned: ISO date\n"
        "- Notes: short evidence-based context\n"
        "\n"
        "Goal sections are created and updated dynamically as evidence accumulates; this file may contain any number of them at any time.\n"
    ),
    "behavioral_hypotheses": (
        "# Behavioral Hypotheses\n"
        "\n"
        "Each hypothesis is tracked in its own section below, numbered sequentially (for example a section titled `H001`, then `H002`), so it can be refined over time via `update_fields` without disturbing any other hypothesis. A hypothesis section typically carries these fields:\n"
        "\n"
        "- Statement: the hypothesis itself, stated with appropriate hedging\n"
        "- Confidence: a 0.0-1.0 estimate, expected to move gradually as evidence accumulates\n"
        "- Supporting Evidence: short evidence-based points that strengthen the hypothesis\n"
        "- Counter Evidence: short evidence-based points that weaken or complicate it\n"
        "- Open Questions: what would need to be true to raise or lower confidence\n"
        "- Last Updated: ISO date of the most recent revision\n"
        "\n"
        "Hypothesis sections are created the first time Stage 5 proposes a new hypothesis, and are never silently deleted -- a hypothesis that stops being supported is marked accordingly rather than removed, so the reasoning trail stays intact.\n"
    ),
    "observed_patterns": (
        "# Observed Patterns\n"
        "\n"
        "Neutral, evidence-based record of recurring behavioral patterns noticed in journal entries. Patterns are recorded as observations, not judgements -- whether a pattern is ultimately helpful or harmful is a question for `behavioral_hypotheses.md`, not decided here. New observations are appended to the relevant section below; use `history_limit` on append if a section should only retain the most recent N entries.\n"
        "\n"
        "## Identified Patterns\n"
        "\n"
        "## Conditions That Co-Occur\n"
    ),
    "avoidance_patterns": (
        "# Avoidance Patterns\n\n"
        "## Identified Patterns\n\n(none recorded yet)\n\n"
        "## Common Triggers\n\n(none recorded yet)\n"
    ),
    "trader_profile": (
        "# Trader Profile\n"
        "\n"
        "Evidence-based assessment of trading behavior, updated incrementally via `update_fields` as new trade journal evidence accumulates. Each category below carries a `Confidence` field (0.0-1.0) and a `Last Updated` field alongside its content, so the assessment's certainty and recency are always visible. `Improvement Areas` is the exception: it is a running, evidence-based list rather than a fixed set of fields, and supports `append` with `history_limit`.\n"
        "\n"
        "## Execution\n"
        "\n"
        "- Entry Discipline: (not yet observed)\n"
        "- Exit Discipline: (not yet observed)\n"
        "- Position Sizing Consistency: (not yet observed)\n"
        "- Plan Adherence: (not yet observed)\n"
        "- Confidence: (not yet established)\n"
        "- Last Updated: (not yet updated)\n"
        "\n"
        "## Psychology\n"
        "\n"
        "- Emotional Regulation: (not yet observed)\n"
        "- Tilt Indicators: (not yet observed)\n"
        "- Confidence: (not yet established)\n"
        "- Last Updated: (not yet updated)\n"
        "\n"
        "## Edge\n"
        "\n"
        "- Stated Edge: (not yet observed)\n"
        "- Supporting Evidence: (none yet)\n"
        "- Counter Evidence: (none yet)\n"
        "- Confidence: (not yet established)\n"
        "- Last Updated: (not yet updated)\n"
        "\n"
        "## Risk\n"
        "\n"
        "- Typical Position Sizing: (not yet observed)\n"
        "- Stop-Loss Discipline: (not yet observed)\n"
        "- Max Observed Drawdown Behavior: (not yet observed)\n"
        "- Confidence: (not yet established)\n"
        "- Last Updated: (not yet updated)\n"
        "\n"
        "## Improvement Areas\n"
    ),
}


# Change #1 backward compatibility: if a vault still has the old
# productive_patterns.md file on disk and the new observed_patterns.md
# hasn't been created yet, we migrate by loading (and, on next write,
# saving to) the new path instead of silently ignoring pre-existing
# data. Keyed by the *new* canonical name.
LEGACY_MEMORY_FILENAMES: Dict[str, str] = {
    "observed_patterns": "productive_patterns.md",
}


def parse_memory_markdown(name: str, file_path: Path, raw_text: str) -> MemoryFile:
    """Pure parsing function (no disk I/O) so it's easily unit tested."""
    lines = raw_text.split("\n")

    preamble_lines = []
    sections: Dict[str, MemorySection] = {}
    section_order = []
    current_heading = None
    current_body: list = []

    def flush_current():
        nonlocal current_heading, current_body
        if current_heading is not None:
            sections[current_heading] = MemorySection(
                heading=current_heading, body_lines=current_body
            )
            section_order.append(current_heading)
        current_heading = None
        current_body = []

    for line in lines:
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match:
            flush_current()
            current_heading = heading_match.group(1)
            current_body = []
        elif current_heading is None:
            preamble_lines.append(line)
        else:
            current_body.append(line)

    flush_current()

    return MemoryFile(
        name=name,
        file_path=file_path,
        raw_text=raw_text,
        preamble="\n".join(preamble_lines).rstrip("\n"),
        sections=sections,
        section_order=section_order,
    )


def load_memory_file(name: str, file_path: Path, logger: logging.Logger) -> MemoryFile:
    if not file_path.exists():
        legacy_filename = LEGACY_MEMORY_FILENAMES.get(name)
        legacy_path = file_path.parent / legacy_filename if legacy_filename else None

        if legacy_path is not None and legacy_path.exists():
            # Change #1 backward compatibility: migrate the old file to
            # its new canonical name instead of orphaning it. We copy
            # the content as-is (headings will be modernized the next
            # time Stage 5 issues updates against it) and leave the old
            # file in place untouched, in case anything else still
            # expects it.
            logger.warning(
                "Migrating legacy memory file %s -> %s", legacy_path, file_path
            )
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(legacy_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            logger.warning(
                "Memory file %s does not exist, creating default skeleton: %s", name, file_path
            )
            file_path.parent.mkdir(parents=True, exist_ok=True)
            default_text = DEFAULT_MEMORY_TEMPLATES.get(name)
            if default_text is None:
                raise ValueError(f"No default template registered for unknown memory file: {name}")
            file_path.write_text(default_text, encoding="utf-8")

    raw_text = file_path.read_text(encoding="utf-8")
    return parse_memory_markdown(name, file_path, raw_text)


def load_all_memory_files(vault: VaultConfig, logger: logging.Logger) -> Dict[str, MemoryFile]:
    memory_files: Dict[str, MemoryFile] = {}
    for name, path in vault.all_memory_paths().items():
        memory_files[name] = load_memory_file(name, path, logger)
    logger.info("Loaded %d memory files", len(memory_files))
    return memory_files


def format_memory_for_prompt(memory_files: Dict[str, MemoryFile]) -> str:
    """Render all memory files into a single text block for embedding
    in prompts that need current-memory context (Stage 5, Stage 6)."""
    blocks = []
    for name, mem in memory_files.items():
        blocks.append(f"--- MEMORY FILE: {name} ---\n{mem.raw_text.strip()}\n")
    return "\n".join(blocks)
