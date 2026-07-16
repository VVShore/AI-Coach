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
    # Change #2: headings now reflect journal-derived evidence rather
    # than pre-baked conclusions -- what's actually been said/observed,
    # separated from what's merely desired, plus explicit space for
    # conflicting evidence instead of silently overwriting it.
    "identity_profile": (
        "# Identity Profile\n\n"
        "## Repeated Identity Statements\n\n(not yet established)\n\n"
        "## Desired Identity\n\n(not yet established)\n\n"
        "## Observed Identity\n\n(not yet established)\n\n"
        "## Identity Conflicts\n\n(none recorded yet)\n\n"
        "## Identity Changes\n\n(none recorded yet)\n"
    ),
    # Change #3: "recurring" replaces "current" -- a goal mentioned
    # repeatedly over many weeks is more diagnostically useful than a
    # goal that merely exists right now.
    "active_goals": (
        "# Active Goals\n\n"
        "## Recurring Goals\n\n(none recorded yet)\n\n"
        "## Emerging Goals\n\n(none yet)\n\n"
        "## Completed Goals\n\n(none yet)\n\n"
        "## Inactive Goals\n\n(none yet)\n"
    ),
    # Change #4: each hypothesis is its own '## H00N' section so it can
    # be updated individually (via action='update_fields') without
    # touching unrelated hypotheses. Field lines use the same
    # '- Key: Value' bullet format that update_fields parses, so the
    # default skeleton is itself a valid update_fields target.
    "behavioral_hypotheses": (
        "# Behavioral Hypotheses\n\n"
        "## H001\n\n"
        "- Statement: (no hypotheses recorded yet)\n"
        "- Confidence: 0.0\n"
        "- Supporting Evidence: (none yet)\n"
        "- Counter Evidence: (none yet)\n"
        "- Open Questions: (none yet)\n"
        "- Last Updated: (not yet updated)\n"
    ),
    # Change #1: renamed from productive_patterns. The AI records
    # neutral observations rather than pre-classifying a pattern as
    # productive or unproductive; that judgement, if warranted, belongs
    # in behavioral_hypotheses instead.
    "observed_patterns": (
        "# Observed Patterns\n\n"
        "## Identified Patterns\n\n(none recorded yet)\n\n"
        "## Conditions That Co-Occur\n\n(none recorded yet)\n"
    ),
    "avoidance_patterns": (
        "# Avoidance Patterns\n\n"
        "## Identified Patterns\n\n(none recorded yet)\n\n"
        "## Common Triggers\n\n(none recorded yet)\n"
    ),
    # Change #5: trading-specific vocabulary instead of the generic
    # strengths/weaknesses framing used elsewhere.
    "trader_profile": (
        "# Trader Profile\n\n"
        "## Execution\n\n(not yet established)\n\n"
        "## Psychology\n\n(not yet established)\n\n"
        "## Edge\n\n(not yet established)\n\n"
        "## Risk\n\n(not yet established)\n\n"
        "## Improvement Areas\n\n(none recorded yet)\n"
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
