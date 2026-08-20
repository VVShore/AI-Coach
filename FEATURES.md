# Features

This project touches three separate systems that can be easy to conflate
since they all live inside the same Obsidian vault. This page explains what
each one actually does, and — more importantly — where they don't overlap.

## The three systems

### 1. Templater — note creation

Templater's job ends the moment a note is created. It runs a script
(`<%* %>` blocks) that renames the file to today's date and fills in
frontmatter/heading placeholders (`<% %>` blocks), then gets out of the way.
It never touches a note again after that.

It has no awareness of Coach AI, tags, or anything else — it's purely a
"stamp today's date and a blank structure onto a new file" tool.

### 2. AI Tagger Universe — note discoverability

This reads a note's content and suggests tags, written into YAML
frontmatter (`tags: [...]`). It's for *you*, browsing your own vault later —
tags make related notes surface together in Obsidian's search and graph
view.

**It is completely disconnected from Coach AI.** The pipeline does not read,
use, or depend on tags in any way today — Stage 1 reads the raw text of a
journal entry, tags and all, but never specifically looks for or acts on a
`tags:` field. Running the tagger (or not) has zero effect on what Coach AI
produces. Think of it as a parallel, optional layer for your own use of the
vault, not a component of the pipeline.

### 3. Coach AI — the weekly pipeline

The only one of the three that reads a *week's worth* of notes at once
rather than one note at a time. It doesn't create or tag notes — it reads
what's already there (Daily Journal + Trade Journal entries for the past
week), runs them through six analysis stages, and writes two kinds of output
back to the vault:

- **Memory files** (`AI/Memory/*.md`) — long-term, evidence-based
  observations that accumulate and get refined week over week
- **A weekly review** (`AI/Weekly Reviews/*.md`) — a single research-report
  style document for that week

## Why this separation matters

Because these three are independent, you can freely:

- Skip AI Tagger Universe entirely and Coach AI works identically
- Write your own template (skip Templater's specific structure) as long as
  notes still end up with a resolvable date (see `docs/SETUP.md` → "Bring
  your own templates")
- Run Coach AI against notes that were never tagged, or tagged with a
  completely different taxonomy than the example in `docs/SETUP.md`

The only hard dependency running *between* these systems is: Templater's
auto-rename behavior (stamping the filename as `YYYY-MM-DD`) is what makes
Coach AI's date resolution trivially reliable. You could skip Templater too
and just name files by hand — the pipeline doesn't care how a filename got
its date, only that a date is resolvable from it (or from frontmatter).

## How a week actually flows through the pipeline

Once a week's worth of Daily Journal / Trade Journal notes exist (by
whatever means — templated, tagged, hand-written, doesn't matter), running
`python main.py` does this, in order:

1. **Stage 1 — Summary.** Reads the raw text of every note from the past
   week and produces a factual, per-day summary. No interpretation yet.
2. **Stage 2 — Behavior.** Looks across those summaries for evidence-backed
   patterns — prioritizing implementation gaps (something mentioned
   repeatedly but rarely acted on), contradictions, and emerging trends over
   generic observations.
3. **Stage 3 — Identity.** Same evidence-first approach, but specifically
   for the gap between what's *stated* (repeated claims about who you are or
   want to be), what's *desired* (aspirations), and what's *observed*
   (actual behavior).
4. **Stage 4 — Goals.** Tracks mention-vs-action gaps for goals already in
   memory, and flags newly recurring goals not yet tracked.
5. **Stage 5 — Memory update.** Decides, conservatively, what from Stages
   2-4 is solid enough evidence to actually persist into the long-term
   memory files — and how (a full section rewrite, an appended log entry, or
   a targeted update to just one or two fields).
6. **Stage 6 — Weekly review.** Synthesizes everything into the final
   research-report style document, explicitly separating what *happened*
   (observations), what it might *mean* (hedged hypotheses), and what's
   worth paying attention to *next week* (coaching implications) — never
   blending the three into vague, unsupported advice.

Every stage only ever returns structured JSON, validated against a strict
schema before Python touches any file — the model never writes markdown
directly, and a stage that produces invalid output retries automatically
rather than corrupting anything.
