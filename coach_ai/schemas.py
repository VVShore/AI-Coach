"""
schemas.py
==========
Pydantic models describing the EXACT JSON contract each pipeline stage
demands from the LLM. Nothing from Ollama is ever trusted until it has
been parsed and validated against one of these models.

Design notes:
- Every field the LLM must produce is required (no silent defaults for
  content fields) so a malformed/partial response fails validation and
  triggers a retry rather than silently corrupting memory.
- `extra = "forbid"` on every model means the LLM cannot smuggle in
  unexpected keys that Python would otherwise ignore -- if the prompt
  and the model's understanding of the schema drift, we find out via a
  validation error, not a silent bug three stages later.
- MEMORY_FILE_NAMES / MEMORY_SECTION_ACTIONS are shared vocabularies
  between this file, prompts, and markdown_writer.py -- keep them in
  sync if the memory file set ever changes.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# Canonical memory file identifiers. Must match config.VaultConfig.all_memory_paths().
# "observed_patterns" replaces the old "productive_patterns" name: the AI now
# records neutral observations instead of prematurely labeling a pattern as
# productive, per the evidence-collector philosophy. This tuple is what gets
# advertised to the LLM (e.g. in the Stage 5 prompt's valid-file-names list),
# so it only ever lists the current name.
MEMORY_FILE_NAMES = (
    "identity_profile",
    "active_goals",
    "behavioral_hypotheses",
    "observed_patterns",
    "avoidance_patterns",
    "trader_profile",
)

# MemoryFileName additionally accepts the retired "productive_patterns" value
# so that (a) any in-flight prompts/tests still referencing the old name
# don't fail validation, and (b) markdown_writer.py can normalize it via
# LEGACY_MEMORY_FILE_ALIASES below rather than rejecting it outright. New
# code should always use "observed_patterns".
MemoryFileName = Literal[
    "identity_profile",
    "active_goals",
    "behavioral_hypotheses",
    "observed_patterns",
    "productive_patterns",
    "avoidance_patterns",
    "trader_profile",
]

# Maps retired memory-file names to their current canonical name. Consulted
# by markdown_writer.apply_memory_updates before every file lookup so old
# and new names resolve to the same MemoryFile.
LEGACY_MEMORY_FILE_ALIASES = {
    "productive_patterns": "observed_patterns",
}


class StrictModel(BaseModel):
    """Base class: forbids unknown fields and strips leading/trailing
    whitespace from all string fields for consistent downstream use."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Stage 1 -- Daily Summaries
# ---------------------------------------------------------------------------
class DailySummaryItem(StrictModel):
    date: str = Field(..., description="ISO date YYYY-MM-DD this summary covers")
    summary: str = Field(..., min_length=1, description="2-5 sentence factual summary of the day")
    mood: str = Field(..., description="One or two word mood/emotional tone descriptor")
    key_events: List[str] = Field(default_factory=list, description="Notable discrete events")
    trading_notes: str = Field(
        default="", description="Summary of trading activity that day, empty string if none"
    )
    tags: List[str] = Field(default_factory=list, description="Short topical tags")


class Stage1Output(StrictModel):
    week_start: str = Field(..., description="ISO date of the Monday of the week covered")
    week_end: str = Field(..., description="ISO date of the Sunday of the week covered")
    daily_summaries: List[DailySummaryItem] = Field(..., min_length=1)
    week_overview: str = Field(..., min_length=1, description="3-6 sentence overview of the whole week")


# ---------------------------------------------------------------------------
# Stage 2 -- Behavior Analysis
# ---------------------------------------------------------------------------
class BehaviorPattern(StrictModel):
    pattern_name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    evidence: List[str] = Field(..., min_length=1, description="Direct evidence pulled from the summaries")
    category: Literal["productive", "avoidance", "neutral"]
    confidence: float = Field(..., ge=0.0, le=1.0)


class Stage2Output(StrictModel):
    patterns: List[BehaviorPattern] = Field(default_factory=list)
    summary: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Stage 3 -- Identity Analysis
# ---------------------------------------------------------------------------
class IdentityObservation(StrictModel):
    trait: str = Field(..., min_length=1, description="Short name of the identity trait or belief observed")
    description: str = Field(..., min_length=1)
    evidence: List[str] = Field(..., min_length=1)
    change_from_baseline: str = Field(
        default="", description="How this differs from the existing identity_profile, empty if unchanged"
    )


class Stage3Output(StrictModel):
    observations: List[IdentityObservation] = Field(default_factory=list)
    summary: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Stage 4 -- Goals Analysis
# ---------------------------------------------------------------------------
class GoalUpdate(StrictModel):
    goal_name: str = Field(..., min_length=1)
    status: Literal["on_track", "at_risk", "achieved", "abandoned", "new"]
    progress_notes: str = Field(..., min_length=1)
    evidence: List[str] = Field(default_factory=list)


class Stage4Output(StrictModel):
    goal_updates: List[GoalUpdate] = Field(default_factory=list)
    new_goals: List[str] = Field(default_factory=list, description="Newly detected goals not yet tracked")
    summary: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Stage 5 -- Memory Updates
# ---------------------------------------------------------------------------
class MemoryFieldUpdate(StrictModel):
    file: MemoryFileName
    section: str = Field(..., min_length=1, description="The '## Heading' name to modify, without '## '")
    action: Literal["replace", "append", "remove", "update_fields"]
    content: str = Field(
        default="",
        description=(
            "New content for the section. Used by 'replace' and 'append'. "
            "Empty allowed when action is 'remove' or 'update_fields'."
        ),
    )
    # --- Extension for Change #6: field-level updates -----------------
    # When action == "update_fields", `fields` carries the specific
    # "- Key: Value" bullet lines to update within the section, leaving
    # every other line untouched. This is the preferred update
    # mechanism going forward, since it avoids clobbering an entire
    # section just to change one data point (e.g. a mention count).
    fields: Optional[Dict[str, Union[str, int, float]]] = Field(
        default=None,
        description="Used only when action='update_fields': key/value pairs to set within the section.",
    )
    # --- Extension for Change #7: bounded append history ---------------
    # When action == "append" and history_limit is set, only the newest
    # `history_limit` appended entries are kept (oldest are dropped) so
    # a frequently-appended section (e.g. a running log) doesn't grow
    # without bound. Omitted/None preserves the original unlimited-
    # append behavior for full backward compatibility.
    history_limit: Optional[int] = Field(
        default=None,
        ge=1,
        description="Used only when action='append': keep only the newest N appended entries.",
    )


class Stage5Output(StrictModel):
    updates: List[MemoryFieldUpdate] = Field(default_factory=list)
    rationale: str = Field(..., min_length=1, description="Why these specific updates were chosen")


# ---------------------------------------------------------------------------
# Stage 6 -- Weekly Review
# ---------------------------------------------------------------------------
class WeeklyReviewOutput(StrictModel):
    title: str = Field(..., min_length=1)
    week_range: str = Field(..., min_length=1)
    overview: str = Field(..., min_length=1)
    key_wins: List[str] = Field(default_factory=list)
    key_struggles: List[str] = Field(default_factory=list)
    behavioral_insights: List[str] = Field(default_factory=list)
    identity_shifts: List[str] = Field(default_factory=list)
    goal_progress: List[str] = Field(default_factory=list)
    trading_insights: List[str] = Field(default_factory=list)
    action_items_next_week: List[str] = Field(..., min_length=1)

    # --- Extension for Change #8: research-report fields ----------------
    # Added as plain fields on the existing model rather than as nested
    # sub-models -- keeps the schema flat, keeps LLM JSON output more
    # reliable (fewer nesting levels to get wrong), and keeps the render
    # logic in markdown_writer.py a simple extension of the existing
    # bullet-list rendering instead of a new code path.
    overall_momentum: str = Field(
        ..., min_length=1, description="Single 0-100 score with trend, e.g. '76 (+8)'"
    )
    goal_momentum: Dict[str, Literal["increasing", "stable", "decreasing"]] = Field(
        default_factory=dict, description="Major recurring goal name -> momentum direction"
    )
    biggest_contradictions: List[str] = Field(
        default_factory=list, description="Evidence-based inconsistencies, no judgement"
    )
    hypotheses_strengthened: List[str] = Field(default_factory=list)
    hypotheses_weakened: List[str] = Field(default_factory=list)
    hypotheses_new: List[str] = Field(default_factory=list)
    hypotheses_retired: List[str] = Field(default_factory=list)
    goal_mention_frequency: Dict[str, int] = Field(
        default_factory=dict, description="Recurring goal name -> number of mentions this week"
    )
    changes_since_last_week: List[str] = Field(
        default_factory=list, description="What actually changed, not what exists"
    )
    reflection_questions: List[str] = Field(
        ..., min_length=3, max_length=5, description="3-5 evidence-based, non-generic questions"
    )


# Registry so pipeline.py can look up "which schema validates stage N"
# by stage number instead of hardcoding imports at every call site.
STAGE_SCHEMAS = {
    1: Stage1Output,
    2: Stage2Output,
    3: Stage3Output,
    4: Stage4Output,
    5: Stage5Output,
    6: WeeklyReviewOutput,
}
