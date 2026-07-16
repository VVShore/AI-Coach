# Coach AI

A local, Ollama-powered pipeline that reads your Obsidian Daily Journal
and Trade Journal for the previous week, runs a 6-stage LLM analysis
pipeline, updates a set of long-term "memory" markdown files, and
writes a Weekly Review markdown file. Not a chatbot — one script, run
once a week, no conversation.

## How it works

```
main.py
  -> journal_loader.py   reads last week's Daily Journal + Trade Journal notes
  -> memory_loader.py    reads AI/Memory/*.md into structured objects
  -> pipeline.py          runs Stages 1-6 against Ollama, validating every response
       stage1_summary.txt      -> Stage1Output   (daily summaries)
       stage2_behavior.txt     -> Stage2Output   (behavior patterns)
       stage3_identity.txt     -> Stage3Output   (identity observations)
       stage4_goals.txt        -> Stage4Output   (goal status updates)
       stage5_memory_update.txt-> Stage5Output   (JSON instructions for memory edits)
       stage6_weekly_review.txt-> WeeklyReviewOutput (the review content)
  -> markdown_writer.py   applies Stage 5's JSON to memory files, writes the review
```

The LLM **never** writes markdown directly. It only ever returns JSON,
which is validated against a Pydantic schema (`schemas.py`) before
Python touches any file. If a response fails validation, the pipeline
retries with the validation error appended to the prompt (up to
`MAX_JSON_RETRIES` times). If a stage exhausts its retries, the whole
run aborts *before* any memory file or weekly review is written — your
vault is never left in a half-updated state.

## Setup

1. Install [Ollama](https://ollama.com) and pull a model:
   ```
   ollama pull llama3.1:8b
   ollama serve
   ```

2. Install Python dependencies:
   ```
   pip install -r requirements.txt --break-system-packages
   ```

3. Point the script at your vault:
   ```
   export VAULT_ROOT="/path/to/Obsidian Vault"
   ```
   Your vault must contain (or the script will create default
   skeletons for the memory files on first run):
   ```
   Obsidian Vault/
     Daily Journal/        <- notes named like 2026-07-06.md
     Trade Journal/        <- notes named like 2026-07-06.md
     AI/
       Memory/
         identity_profile.md
         active_goals.md
         behavioral_hypotheses.md
         productive_patterns.md
         avoidance_patterns.md
         trader_profile.md
       Weekly Reviews/
     Templates/
   ```
   Daily/Trade journal notes are matched to a week by an ISO date
   (`YYYY-MM-DD`) in the filename, or a `date:` field in YAML
   frontmatter if the filename has no date. See `journal_loader.py`.

## Running it

Every Sunday:
```
python main.py
```

Useful flags:
```
python main.py --date 2026-07-20      # backfill: treat this date as "today"
python main.py --dry-run              # run the full pipeline, write nothing to the vault
```

## Configuration

Everything in `config.py` can be overridden via environment variables:

| Variable            | Default                  | Meaning                                |
|---------------------|---------------------------|-----------------------------------------|
| `VAULT_ROOT`         | `./Obsidian Vault`        | Path to your Obsidian vault             |
| `OLLAMA_HOST`        | `http://localhost:11434`  | Ollama server URL                        |
| `OLLAMA_MODEL`       | `llama3.1:8b`              | Model name to use for every stage        |
| `OLLAMA_NUM_CTX`     | `8192`                     | Context window size                      |
| `OLLAMA_TEMPERATURE` | `0.2`                      | Sampling temperature                     |
| `OLLAMA_TIMEOUT`     | `180`                      | Per-request timeout (seconds)            |
| `MAX_JSON_RETRIES`   | `3`                        | Retries per stage on invalid JSON        |
| `WEEK_STARTS_MONDAY` | `true`                     | `false` to treat weeks as Sun-Sat        |

## Logs & debugging

- Every run writes `logs/<timestamp>.log` with per-stage timing, token
  estimates, retry counts, and any errors.
- Every successful stage also writes its validated JSON to
  `logs/intermediate/<run_id>_stageN_<name>.json` as a checkpoint.
- If a stage fails all its retries, its last (invalid) raw response is
  also saved there for debugging prompt/model issues.

## Extending the pipeline

- **New memory file**: add it to `VaultConfig.all_memory_paths()` in
  `config.py`, add a default skeleton to `DEFAULT_MEMORY_TEMPLATES` in
  `memory_loader.py`, and add its identifier to `MEMORY_FILE_NAMES` in
  `schemas.py`.
- **New pipeline stage**: add a Pydantic output schema to
  `schemas.py`, a prompt template to `prompts/`, and a new stage block
  in `pipeline.run_pipeline`, following the pattern of the existing
  six stages.
- **Different LLM backend**: only `ollama_client.py` needs to change;
  everything else talks to it through the small `generate()` /
  `OllamaResponse` interface.
