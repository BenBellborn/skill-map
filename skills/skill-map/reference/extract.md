# skill-map: fragment extraction
`/skill-map` agent brief. Unit: skill, hook, mod or plugin. Read each listed file: `rtk read <path>` when `rtk` is installed, else Read tool.

Write one JSON fragment to brief's output path. Never edit skill files.

Brief with several units: do each in turn, one fragment and one reply line per unit.

## Hook, mod, plugin units
- Files are code, not md. Fragment shows what code makes Claude read or run.
- `loads`: md files code reads into context (injects, prints, returns as context). `calls`: skills it types or runs
  (`/fix` -> `fix`), `builtin:<name>`, `mcp:<server>`. `agents`: agents code spawns.
- `kind`: unit kind from brief. `args`: `[]`. `skill`: unit name.
- File code only checks (lint of md, size cap): no load.

## Rules
- Only facts files state. Unknown model, effort, count, items: `""`. Never guess.
- `when`: condition in ≤8 words ("TODO source", "tests green", "step 4"). Always loaded: `""`.
- `args`: arg ids under which entry happens. Every arg: `[]`.
  - Arg only passed on in `callArgs` (`max` when given) never limits entry: call happens without it too, so `[]`.
- Own flow only: what another skill's md loads goes in that skill's fragment.
- Own `reference/*.md` files: list what they load too, under this skill.
- `lwt`: copy brief's value exactly. Scan uses it to skip fresh skills.
- Brief names problems (rerun): write whole fragment again, `lwt` from brief. Never patch old fragment; it holds `lwt` `broken`.

## Refs (`md` and `skill` values)
- Other user skill: its folder name (`design-ext`, `todo-ext`, `fix`). Plugin skill: `<plugin>:<name>` (`skill-map:skill-map`).
- File in this skill folder: relative path (`reference/loop.md`, `KNOWLEDGE.md`).
- Other file under `~/.claude`: `~/.claude/<path>` (`~/.claude/reference/error-review.md`,
  `~/.claude/skills/design-ext/reference/design-knowledge.md`). Agent type file: `~/.claude/agents/<type>.md`.
- Project file (cwd repo): `project:<path>` (`project:docs/KNOWLEDGE.md`, `project:docs/TODO.md`, `project:CLAUDE.md`).
- Built-in skill or tool command not under `~/.claude/skills` (`/code-review`, `/simplify`): `builtin:<name>`.
- MCP tool use: `mcp:<server>` in `calls`. `<server>`: part between `mcp__` and next `__` of tool name
  (`mcp__codemap-mcp__refs_find` -> `codemap-mcp`). Tool named in words ("CodeMap", "lizard gate"): server from your tool list.
- CLI tool md tells Claude or agent to run, not part of Claude Code (`rtk`, `gh`, `python`, `dotnet`, `jq`):
  `tool:<command name>` in `calls`. Text makes it optional ("when installed", "if present"): `when` `if installed`.
  Tool named in md an agent loads (its brief file): in that agent's `calls`.
- Path in text unclear (`reference/x.md` after "Load `design-ext`"): resolve to file that exists; check with `ls`.

## Schema
```json
{
  "skill": "fix",
  "kind": "command",
  "summary": "builds TODO task, red test first",
  "lwt": "<value from brief>",
  "args": [{"id": "all", "label": "all", "note": "queue, ≤5 workers, loop"}],
  "loads": [{"md": "todo-ext", "when": "TODO source", "args": []}],
  "calls": [{"skill": "review-ext", "callArgs": "uncommitted bugs-only", "when": "tests green", "args": [], "loop": "2 passes max"}],
  "agents": [{"id": "worker", "type": "fix-worker", "model": "opus", "effort": "", "count": "≤5 per batch",
              "items": "1-4", "when": "", "args": ["all"], "loop": "until queue empty", "loads": [{"md": "design-ext", "when": ""}], "calls": []}]
}
```
- `kind`: `shared` when description says load it before work of other skills (`design-ext`, `todo-ext`, `review-ext`); else `command`.
- `summary`: ≤8 words.
- `args`: only args that change loads, calls, agents or loop. None: `[]`.
- Free-text or number arg: one entry, `id` `n`, label `#`.
- Model arg (`[model:effort]`, sets agent model): `id` `model`, label `model:effort`. Agent it sets: `modelArg` `model`,
  `model`/`effort` the default.
- `callArgs`: args passed in call, space-separated, as typed (`sonnet:high bugs-only`, `todo:3`). Map follows token equal
  to callee arg id, `<id>:<value>`, or model value (callee arg `model`).
- `agents`: each distinct spawn (`Agent` tool, `subagent_type`, finder, verifier, worker).
  - `id`: short unique name. `type`: `subagent_type` value.
  - `count`: agents started (cap or number). `items`: work items one agent takes ("1", "2-4", "≤4 per batch").
    Batch hint fires only on `items` `1`.
  - `loads`: md agent reads at start, from brief or agent type file. `calls`: skills it runs.
- `loop`: loop text on call or agent ("until queue empty", "per part", "2 passes max"). None: `""`.

## Check before reply
- `python -c "import json,sys;json.load(open(sys.argv[1]))" <output>` passes.
- Every relative `md` exists in skill folder; every `~/.claude/` path exists.
- Reply: one line, `ok <skill>` or `failed <skill>: <reason>`.
