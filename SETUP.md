# Setup Guide

This walks through setting up a fresh Obsidian vault to work with Coach AI: the
required folder structure, the plugins that make journaling smooth (Templater
for templates, AI Tagger Universe for auto-tagging, Image Toolkit for viewing
embedded screenshots), and the Python pipeline itself.

None of the plugins are strictly required for Coach AI to run — the pipeline
only needs plain markdown files with resolvable dates. They're included here
because they're what makes the day-to-day journaling experience good, and
because auto-dating via Templater in particular avoids a common failure mode
(notes the pipeline can't date, and therefore silently skips).

---

## 1. Prerequisites

- **Obsidian** — [obsidian.md](https://obsidian.md)
- **Python 3.10+** — [python.org](https://www.python.org/downloads/)
- **Ollama**, with a model pulled — [ollama.com](https://ollama.com)
  ```
  ollama pull qwen2.5:7b-instruct
  ollama serve
  ```
  (Model choice matters more than it might seem — see the note at the end of
  this guide on picking a model that actually fits your hardware.)

---

## 2. Vault folder structure

Coach AI expects two folders **directly under your vault root**, with these
**exact, literal names**:

```
Your Vault/
  Daily Journal/
  Trade Journal/
  AI/
    Memory/
    Weekly Reviews/
  Templates/
```

`Daily Journal` and `Trade Journal` are not currently configurable beyond
their parent folder (`VAULT_ROOT`) — the pipeline looks for those two names
specifically. If you like organizing your vault with numeric prefixes (e.g.
`3 - Daily Journal`) for your own sorting purposes, that's fine for the rest
of your vault, but these two folders need to exist with the plain names
above for the pipeline to find them. (Files can be nested in subfolders
within them without any issue — e.g. `Daily Journal/2026/07/2026-07-06.md`
works fine, the loader searches recursively.)

`AI/Memory/` will be auto-populated with default files the first time you
run the pipeline, so you don't need to create those by hand.

---

## 3. Install the plugins

All three are community plugins — in Obsidian: **Settings → Community
Plugins → Browse**, search by name, install, and enable. If a plugin isn't
in the community directory yet, install manually from its GitHub repo per
that plugin's own README:

| Plugin | Purpose | Repo |
|---|---|---|
| **Templater** | Runs the scripting (`<% %>` syntax) that auto-dates new notes | [SilentVoid13/Templater](https://github.com/SilentVoid13/Templater) |
| **AI Tagger Universe** | Auto-suggests tags for notes using a local or cloud LLM | [Agents365-ai/obsidian-ai-tagger-universe](https://github.com/Agents365-ai/obsidian-ai-tagger-universe) |
| **Image Toolkit** | Better viewing for embedded images (e.g. trade screenshots) | [sissilab/obsidian-image-toolkit](https://github.com/sissilab/obsidian-image-toolkit) |

---

## 4. Set up Templater

1. **Settings → Templater → Template folder location** — point this at your
   `Templates/` folder.
2. Copy `templates/Daily Journal.md` from this repo into that folder.
3. **This is the part people get wrong:** to actually create a new dated
   note from the template, use the command palette (**Ctrl/Cmd + P**) and
   run **"Templater: Insert Template"** — *not* Obsidian's own built-in
   "Insert template" command. Only Templater's version executes the
   `<% %>` scripting that renames the file to today's date and fills in the
   frontmatter. Obsidian's core command will just paste the raw template
   text, tags and all, without running any of it.
4. Optional but recommended: **Settings → Hotkeys**, search "Templater:
   Insert Template", and bind it to something memorable so you're not
   digging through the command palette every day.

You're welcome to build your own Trade Journal template (or any other note
type) the same way — see the "Bring your own templates" note below for what
the pipeline actually needs from a template to work correctly.

---

## 5. Set up AI Tagger Universe (optional, but recommended)

This is entirely optional — Coach AI's pipeline doesn't currently read tags
at all, it works directly from raw journal text. Tagging is purely for your
own note-discoverability inside Obsidian.

**Settings → AI Tagger Universe.** A reasonable starting configuration:

- **Service type:** Local
- **Local endpoint:** `http://localhost:11434` (your Ollama server)
- **Local model:** whatever Ollama model you're running
- **Tagging mode:** Hybrid (blends a fixed vocabulary with freely generated
  tags)
- **Tag format:** kebab-case
- **Enable nested tags:** on, if you want `parent/child` tag hierarchies

There's no automatic trigger by default — tagging runs on a manual command,
which you can bind to a hotkey the same way as Templater's insert command if
you want a fast per-note keystroke.

If you want the tagger to reason about *why* it's picking tags rather than
just pattern-matching keywords, a custom prompt helps. A starting point:

```
You are tagging notes in a personal knowledge base that captures everything
from learning notes to journal reflections, quotes, reminders, poems, and
fleeting thoughts.

First, identify what type of note this is:
- Learning/concept note: focus on domain and specific idea
- Journal/reflection: focus on themes, emotions, or life areas being touched on
- Quote or lyric: focus on the underlying theme or feeling it represents
- Reminder/to-do: use practical, action-oriented tags
- Mixed/other: use whatever best captures the core of what's written

Then generate tags that:
- Connect this note to related notes on similar themes or feelings
- Reflect the domain, life area, or concept (e.g. psychology, career,
  gratitude, creativity, trading, health, relationships)
- Would make this note discoverable when you're in a related headspace later

Avoid tags that:
- Are so specific they only apply to this single note
- Simply restate the title or first line
- Are too vague to be useful (e.g. "thoughts", "misc")

Use kebab-case for multi-word tags. If nested tags are enabled, use
parent/child format where parent is the broad life area and child is
the specific concept or emotion.
```

---

## 6. Set up Image Toolkit

No special configuration needed — install, enable, and it improves how
embedded images (screenshots pasted into Trade Journal entries, for example)
render and can be viewed/zoomed.

---

## 7. Set up the Python pipeline

```
pip install -r requirements.txt --break-system-packages
```

Point the pipeline at your vault by setting `VAULT_ROOT`. On Windows
(PowerShell):

```powershell
$env:VAULT_ROOT = "C:\path\to\your\vault"
```

On macOS/Linux:

```bash
export VAULT_ROOT="/path/to/your/vault"
```

Set this once per terminal session, or add it to your shell profile /
Windows environment variables permanently so you don't need to re-set it
every time.

---

## 8. First run

Do a dry run first — it runs the full pipeline but writes nothing to your
vault, so you can confirm everything is wired up correctly before touching
real data:

```
python main.py --dry-run
```

Check `logs/<timestamp>.log` for what it found. You're looking for lines
like:

```
Loaded 5 daily journal entries for 2026-07-06 to 2026-07-12
Loaded 6 memory files
```

If it says `Loaded 0 daily journal entries`, double check step 2 — the
folder names and location are the most common culprit.

Once a dry run looks right, drop `--dry-run` for a real run that updates
your memory files and writes a weekly review to `AI/Weekly Reviews/`.

---

## Bring your own templates

You don't have to use the exact Daily Journal template shipped here. The
pipeline only actually requires two things from any note, regardless of what
template (if any) produced it:

1. **A resolvable date** — either in the filename as `YYYY-MM-DD` (which is
   what the shipped template's auto-rename script does for you), or as a
   `date:` field in YAML frontmatter (matched case-insensitively, so `Date:`
   works too).
2. **Plain readable text content.** Whatever structure, headings, or fields
   your template uses get passed to the LLM as-is — there's no required
   format beyond that.

Everything else — section headers, mood trackers, tag fields, whatever you
want to add — is free-form and safe to customize.

---

## A note on model choice

The pipeline's heaviest prompt (Stage 1) sends a full week of raw journal
text to your local model, so model size vs. your hardware matters more here
than in typical chat use. If you're unsure what fits:

```
ollama run <model-name> "Say hello in one sentence."
```

Time it, and check `ollama ps` afterward — the `PROCESSOR` column tells you
whether the model ran on GPU, CPU, or a split of both. A model that doesn't
fully fit in VRAM (a CPU/GPU split, or worse, majority-CPU) will be
dramatically slower than one that does. If Stage 1 is timing out even with
`OLLAMA_TIMEOUT` raised generously, that's the first thing to check — try a
smaller model and re-run the same test until you find one your hardware runs
at (close to) 100% GPU.
