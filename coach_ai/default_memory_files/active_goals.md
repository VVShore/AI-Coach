# Active Goals

Each tracked goal gets its own section below, named after the goal itself (for example a section titled `Trading Bot`), so its fields can be updated individually via `update_fields` without touching any other goal. A goal section is created the first time Stage 5 finds evidence for it, and typically carries these fields:

- Status: recurring | emerging | completed | inactive
- Mention Count: running count of journal mentions
- Momentum: increasing | stable | decreasing
- First Mentioned: ISO date
- Last Mentioned: ISO date
- Notes: short evidence-based context

Goal sections are created and updated dynamically as evidence accumulates; this file may contain any number of them at any time.
