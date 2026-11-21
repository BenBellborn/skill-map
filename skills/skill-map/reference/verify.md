# Hint verifier
`/skill-map` agent brief: check each savings hint against skill's md before page shows it. Unchecked hint never shows.

## Input
- Per hint: `<key>`, `<skill>`, `<prompt>` (one `unchecked hint:` line of `render`).

## Check
- Read `~/.claude/skills/<skill>/SKILL.md`, each md prompt names, each reference file flow of named agent or md names.
  Agent type file: `~/.claude/agents/<type>.md`.
- `ok` only when both hold, each proved by quoted line:
  1. Premise true: number in prompt matches what files state (starts, read on every run, md read at start).
  2. Change possible and keeps same result: no rule in files forbids it, nothing it needs is lost.
- Doubt, or no line proves it: `wrong`. Never guess.

## Per hint kind
- **Agent starts N times, give each 2 items:** files must state one item per agent and N starts.
  - Count is cap on agents at once ("≤5 at once", "per message"): `wrong`.
  - Skill already batches (2+ items per agent, joins related items): `wrong`.
  - Skill names parallel run as wanted (wall time): `wrong`.
- **Agent reads md at start, brief digest:** agent needs only part of that md.
  - Agent must follow whole md: `wrong`.
- **SKILL.md read on every run, move detail:** SKILL.md holds detail used only under condition (arg, step, mode).
  All of it used every run: `wrong`.
- **Own md read on every run, load under condition:** md used only under condition files name. Used every run: `wrong`.

## Write
- `<script>`: skillmap.py path the brief names.
- `python <script> verdict <key> ok`
- `python <script> verdict <key> wrong <reason, ≤12 words>`

## Reply
- One line per hint: `<key> ok|wrong <reason>`. Nothing else.
