"""
pipeline.py
===========
Orchestrates the six-stage LLM pipeline described in the project spec.
This is the only module that:
  - Loads prompt templates from prompts/.
  - Calls OllamaClient.
  - Retries a stage when the response fails JSON/schema validation,
    feeding the validation error back into the prompt so the model can
    self-correct.
  - Persists intermediate JSON after every successful stage (so a
    later failure never loses earlier work) and on final failure of a
    stage (so you can inspect exactly what the model produced).

Error handling contract (per spec: "If one stage fails, save
intermediate JSON, exit gracefully, never corrupt memory"):
  - PipelineStageError is raised when a stage exhausts its retries.
  - main.py catches this, logs it, and exits without touching memory
    or writing a weekly review -- partial pipeline runs never reach
    markdown_writer.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Type, TypeVar

from pydantic import BaseModel

from config import Config
from journal_loader import format_entries_for_prompt
from json_validator import validate_llm_json
from memory_loader import format_memory_for_prompt
from models import PipelineArtifacts
from ollama_client import OllamaClient, OllamaError
from schemas import (
    MEMORY_FILE_NAMES,
    Stage1Output,
    Stage2Output,
    Stage3Output,
    Stage4Output,
    Stage5Output,
    WeeklyReviewOutput,
)

T = TypeVar("T", bound=BaseModel)


class PipelineStageError(Exception):
    """Raised when a pipeline stage exhausts its retry budget without
    producing schema-valid JSON. Carries the stage number and the last
    error for logging/diagnostics."""

    def __init__(self, stage_num: int, stage_name: str, last_error: str, raw_text: str):
        self.stage_num = stage_num
        self.stage_name = stage_name
        self.last_error = last_error
        self.raw_text = raw_text
        super().__init__(
            f"Stage {stage_num} ({stage_name}) failed after retries: {last_error}"
        )


def _load_prompt_template(prompts_dir: Path, filename: str) -> Template:
    path = prompts_dir / filename
    return Template(path.read_text(encoding="utf-8"))


def _save_intermediate(
    intermediate_dir: Path, stage_num: int, stage_name: str, payload: dict, run_id: str
) -> Path:
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    out_path = intermediate_dir / f"{run_id}_stage{stage_num}_{stage_name}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out_path


def _run_stage(
    *,
    stage_num: int,
    stage_name: str,
    prompt_text: str,
    schema: Type[T],
    client: OllamaClient,
    max_retries: int,
    logger: logging.Logger,
    intermediate_dir: Path,
    run_id: str,
) -> T:
    """
    Generic single-stage runner: call the LLM, validate, retry with an
    error-augmented prompt on failure, up to max_retries attempts.
    Returns the validated Pydantic model on success. Raises
    PipelineStageError if every attempt fails.
    """
    current_prompt = prompt_text
    last_error = "unknown error"
    last_raw = ""

    for attempt in range(1, max_retries + 1):
        logger.info("Stage %d (%s): attempt %d/%d", stage_num, stage_name, attempt, max_retries)

        try:
            response = client.generate(current_prompt)
        except OllamaError as exc:
            # Transport-level failure is not something a retry-with-
            # different-prompt can fix -- fail the stage immediately.
            logger.error("Stage %d (%s): Ollama error: %s", stage_num, stage_name, exc)
            raise PipelineStageError(stage_num, stage_name, str(exc), "") from exc

        logger.info(
            "Stage %d (%s): received response in %.2fs (~%d prompt tokens, ~%d response tokens)",
            stage_num,
            stage_name,
            response.duration_seconds,
            response.prompt_tokens_est,
            response.response_tokens_est,
        )

        result = validate_llm_json(response.text, schema)
        if result.success:
            logger.info("Stage %d (%s): valid JSON on attempt %d", stage_num, stage_name, attempt)
            return result.data  # type: ignore[return-value]

        last_error = result.error or "unknown validation error"
        last_raw = response.text
        logger.warning(
            "Stage %d (%s): validation failed on attempt %d: %s",
            stage_num,
            stage_name,
            attempt,
            last_error,
        )

        # Augment the prompt with the failure so the model can
        # self-correct on the next attempt.
        current_prompt = (
            f"{prompt_text}\n\n"
            f"=== YOUR PREVIOUS RESPONSE WAS INVALID ===\n"
            f"Previous response:\n{response.text}\n\n"
            f"Validation error:\n{last_error}\n\n"
            f"Fix the JSON and respond again with ONLY the corrected JSON object."
        )

    _save_intermediate(
        intermediate_dir,
        stage_num,
        stage_name,
        {"error": last_error, "raw_text": last_raw, "attempts": max_retries},
        run_id,
    )
    raise PipelineStageError(stage_num, stage_name, last_error, last_raw)


def run_pipeline(
    config: Config,
    artifacts: PipelineArtifacts,
    client: OllamaClient,
    logger: logging.Logger,
) -> PipelineArtifacts:
    """
    Execute Stages 1-6 in order, mutating and returning `artifacts`.
    Each successful stage's output is saved to logs/intermediate/ as a
    checkpoint, and also stored on `artifacts` for the next stage /
    for main.py to hand to markdown_writer.py.
    """
    run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    prompts_dir = config.pipeline.prompts_dir
    intermediate_dir = config.pipeline.intermediate_dir
    max_retries = config.pipeline.max_json_retries

    def checkpoint(stage_num: int, stage_name: str, data: BaseModel) -> None:
        _save_intermediate(intermediate_dir, stage_num, stage_name, data.model_dump(), run_id)

    # ---------------- Stage 1: Daily Summaries ----------------
    stage1_template = _load_prompt_template(prompts_dir, "stage1_summary.txt")
    stage1_prompt = stage1_template.substitute(
        week_range=str(artifacts.week),
        daily_journal_text=format_entries_for_prompt(artifacts.daily_entries),
        trade_journal_text=format_entries_for_prompt(artifacts.trade_entries),
    )
    stage1: Stage1Output = _run_stage(
        stage_num=1,
        stage_name="summary",
        prompt_text=stage1_prompt,
        schema=Stage1Output,
        client=client,
        max_retries=max_retries,
        logger=logger,
        intermediate_dir=intermediate_dir,
        run_id=run_id,
    )
    artifacts.stage1_summary = stage1.model_dump()
    checkpoint(1, "summary", stage1)

    # ---------------- Stage 2: Behavior Analysis ----------------
    stage2_template = _load_prompt_template(prompts_dir, "stage2_behavior.txt")
    stage2_prompt = stage2_template.substitute(
        week_range=str(artifacts.week),
        stage1_json=json.dumps(artifacts.stage1_summary, indent=2),
        behavioral_memory=artifacts.memory_files["behavioral_hypotheses"].raw_text,
    )
    stage2: Stage2Output = _run_stage(
        stage_num=2,
        stage_name="behavior",
        prompt_text=stage2_prompt,
        schema=Stage2Output,
        client=client,
        max_retries=max_retries,
        logger=logger,
        intermediate_dir=intermediate_dir,
        run_id=run_id,
    )
    artifacts.stage2_behavior = stage2.model_dump()
    checkpoint(2, "behavior", stage2)

    # ---------------- Stage 3: Identity Analysis ----------------
    stage3_template = _load_prompt_template(prompts_dir, "stage3_identity.txt")
    stage3_prompt = stage3_template.substitute(
        week_range=str(artifacts.week),
        stage1_json=json.dumps(artifacts.stage1_summary, indent=2),
        identity_memory=artifacts.memory_files["identity_profile"].raw_text,
    )
    stage3: Stage3Output = _run_stage(
        stage_num=3,
        stage_name="identity",
        prompt_text=stage3_prompt,
        schema=Stage3Output,
        client=client,
        max_retries=max_retries,
        logger=logger,
        intermediate_dir=intermediate_dir,
        run_id=run_id,
    )
    artifacts.stage3_identity = stage3.model_dump()
    checkpoint(3, "identity", stage3)

    # ---------------- Stage 4: Goals Analysis ----------------
    stage4_template = _load_prompt_template(prompts_dir, "stage4_goals.txt")
    stage4_prompt = stage4_template.substitute(
        week_range=str(artifacts.week),
        stage1_json=json.dumps(artifacts.stage1_summary, indent=2),
        goals_memory=artifacts.memory_files["active_goals"].raw_text,
    )
    stage4: Stage4Output = _run_stage(
        stage_num=4,
        stage_name="goals",
        prompt_text=stage4_prompt,
        schema=Stage4Output,
        client=client,
        max_retries=max_retries,
        logger=logger,
        intermediate_dir=intermediate_dir,
        run_id=run_id,
    )
    artifacts.stage4_goals = stage4.model_dump()
    checkpoint(4, "goals", stage4)

    # ---------------- Stage 5: Memory Updates ----------------
    stage5_template = _load_prompt_template(prompts_dir, "stage5_memory_update.txt")
    stage5_prompt = stage5_template.substitute(
        week_range=str(artifacts.week),
        stage2_json=json.dumps(artifacts.stage2_behavior, indent=2),
        stage3_json=json.dumps(artifacts.stage3_identity, indent=2),
        stage4_json=json.dumps(artifacts.stage4_goals, indent=2),
        current_memory=format_memory_for_prompt(artifacts.memory_files),
        memory_file_names=", ".join(MEMORY_FILE_NAMES),
    )
    stage5: Stage5Output = _run_stage(
        stage_num=5,
        stage_name="memory_update",
        prompt_text=stage5_prompt,
        schema=Stage5Output,
        client=client,
        max_retries=max_retries,
        logger=logger,
        intermediate_dir=intermediate_dir,
        run_id=run_id,
    )
    artifacts.stage5_memory_updates = stage5.model_dump()
    checkpoint(5, "memory_update", stage5)

    # ---------------- Stage 6: Weekly Review ----------------
    stage6_template = _load_prompt_template(prompts_dir, "stage6_weekly_review.txt")
    stage6_prompt = stage6_template.substitute(
        week_range=str(artifacts.week),
        stage1_json=json.dumps(artifacts.stage1_summary, indent=2),
        stage2_json=json.dumps(artifacts.stage2_behavior, indent=2),
        stage3_json=json.dumps(artifacts.stage3_identity, indent=2),
        stage4_json=json.dumps(artifacts.stage4_goals, indent=2),
        stage5_json=json.dumps(artifacts.stage5_memory_updates, indent=2),
        # Change #8 ("Changes Since Last Week"): Stage 6 needs the
        # pre-update memory snapshot to compare against, otherwise it
        # can only describe current state, not what changed. This is
        # the same memory_files artifacts already loaded at startup --
        # apply_memory_updates() only ever operates on a deep copy, so
        # artifacts.memory_files is still the untouched "before" state
        # at this point in the run.
        current_memory=format_memory_for_prompt(artifacts.memory_files),
    )
    stage6: WeeklyReviewOutput = _run_stage(
        stage_num=6,
        stage_name="weekly_review",
        prompt_text=stage6_prompt,
        schema=WeeklyReviewOutput,
        client=client,
        max_retries=max_retries,
        logger=logger,
        intermediate_dir=intermediate_dir,
        run_id=run_id,
    )
    artifacts.stage6_weekly_review = stage6.model_dump()
    checkpoint(6, "weekly_review", stage6)

    logger.info("All 6 pipeline stages completed successfully.")
    return artifacts
