#!/usr/bin/env python3
"""
main.py
=======
The single script you run every Sunday.

    python main.py

What it does, in order:
  1. Load configuration and ensure vault/log directories exist.
  2. Check Ollama is reachable (fail fast with a clear message if not).
  3. Compute the previous Mon-Sun week range.
  4. Load Daily Journal + Trade Journal entries for that week.
  5. Load all AI memory files (creating default skeletons if missing).
  6. Run the 6-stage pipeline (pipeline.py).
  7. Apply Stage 5's memory updates and write them to disk.
  8. Write the Weekly Review markdown file.

If any pipeline stage fails, the run exits before step 7/8 ever
happens -- memory and the weekly review are only written after every
stage has produced valid data, per the "never corrupt memory" rule in
the spec. Intermediate JSON from every successful stage (and the
failed stage's last raw output) is saved under logs/intermediate/ so
you can inspect or resume manually.

CLI flags:
  --date YYYY-MM-DD   Pretend "today" is this date (affects which
                       week is treated as "previous week"). Useful for
                       backfilling a missed Sunday.
  --dry-run            Run the full pipeline but do NOT write memory
                       files or the weekly review -- only write the
                       intermediate JSON checkpoints. Useful for
                       testing prompts/model changes safely.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from config import load_config
from journal_loader import load_daily_journal_entries, load_trade_journal_entries
from markdown_writer import apply_memory_updates, write_all_memory_files, write_weekly_review
from memory_loader import load_all_memory_files
from models import PipelineArtifacts
from ollama_client import OllamaClient
from pipeline import PipelineStageError, run_pipeline
from schemas import Stage5Output, WeeklyReviewOutput
from utils import get_previous_week_range, setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weekly AI coach pipeline over an Obsidian vault.")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Treat this YYYY-MM-DD date as 'today' when computing the previous week (for backfilling).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but do not write memory files or the weekly review.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    config.ensure_directories_exist()

    logger = setup_logging(config.pipeline.logs_dir)
    logger.info("=== Coach AI weekly run starting ===")
    logger.info("Vault root: %s", config.vault.vault_root)
    logger.info("Ollama model: %s (ctx=%d, temp=%.2f)",
                config.ollama.model, config.ollama.context_length, config.ollama.temperature)

    client = OllamaClient(config.ollama)
    if not client.check_connection():
        logger.error(
            "Could not reach Ollama at %s. Start it with `ollama serve` and ensure "
            "model '%s' is pulled (`ollama pull %s`).",
            config.ollama.host, config.ollama.model, config.ollama.model,
        )
        return 1

    if args.date:
        try:
            today = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error("--date must be in YYYY-MM-DD format, got: %s", args.date)
            return 1
    else:
        today = date.today()

    week = get_previous_week_range(today=today, week_starts_on_monday=config.pipeline.week_starts_on_monday)
    logger.info("Target week: %s", week)

    daily_entries = load_daily_journal_entries(config.vault.daily_journal_dir, week, logger)
    trade_entries = load_trade_journal_entries(config.vault.trade_journal_dir, week, logger)

    if not daily_entries and not trade_entries:
        logger.warning(
            "No journal entries found for %s. The pipeline will still run, but "
            "summaries will note that no data was available.",
            week,
        )

    memory_files = load_all_memory_files(config.vault, logger)

    artifacts = PipelineArtifacts(
        week=week,
        daily_entries=daily_entries,
        trade_entries=trade_entries,
        memory_files=memory_files,
    )

    try:
        artifacts = run_pipeline(config, artifacts, client, logger)
    except PipelineStageError as exc:
        logger.error(
            "Pipeline failed at stage %d (%s): %s",
            exc.stage_num, exc.stage_name, exc.last_error,
        )
        logger.error(
            "Memory and weekly review were NOT modified. Intermediate JSON for "
            "completed stages (and the failing stage's last raw output) was saved "
            "under %s.",
            config.pipeline.intermediate_dir,
        )
        return 1
    except Exception:  # noqa: BLE001 -- top-level safety net, never corrupt memory on unexpected errors
        logger.exception("Unexpected error during pipeline execution. Memory was NOT modified.")
        return 1

    if args.dry_run:
        logger.info("--dry-run set: skipping memory writes and weekly review. Pipeline output "
                    "was saved to logs/intermediate/.")
        logger.info("=== Coach AI weekly run finished (dry run) ===")
        return 0

    # Everything succeeded -- now, and only now, do we touch the vault.
    stage5 = Stage5Output.model_validate(artifacts.stage5_memory_updates)
    updated_memory = apply_memory_updates(artifacts.memory_files, stage5, logger)
    write_all_memory_files(updated_memory, logger)

    stage6 = WeeklyReviewOutput.model_validate(artifacts.stage6_weekly_review)
    review_path = write_weekly_review(config.vault, week, stage6, logger)

    logger.info("Weekly review written to: %s", review_path)
    logger.info("=== Coach AI weekly run finished successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
