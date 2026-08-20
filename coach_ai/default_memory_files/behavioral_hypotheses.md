# Behavioral Hypotheses

Each hypothesis is tracked in its own section below, numbered sequentially (for example a section titled `H001`, then `H002`), so it can be refined over time via `update_fields` without disturbing any other hypothesis. A hypothesis section typically carries these fields:

- Statement: the hypothesis itself, stated with appropriate hedging
- Confidence: a 0.0-1.0 estimate, expected to move gradually as evidence accumulates
- Supporting Evidence: short evidence-based points that strengthen the hypothesis
- Counter Evidence: short evidence-based points that weaken or complicate it
- Open Questions: what would need to be true to raise or lower confidence
- Last Updated: ISO date of the most recent revision

Hypothesis sections are created the first time Stage 5 proposes a new hypothesis, and are never silently deleted -- a hypothesis that stops being supported is marked accordingly rather than removed, so the reasoning trail stays intact.
