---
name: skill-map
description: Draws a zoomable HTML map of every user skill in ~/.claude/skills - the md files, sub-skills and agents (model:effort, count, start ctx) each command pulls in, under which condition and argument - and opens it in the default browser. Caches each skill's LWT, so only changed skills are read again. Use for /skill-map, "show skill map", "how does /fix branch out", "which md files does a skill load". Arg `full` re-reads every skill.
argument-hint: "[full]"
---

Read-only on skills. Scripts do scan, cache, layout, HTML; agents read changed skills; main session never reads skill files.
Script: `python ${CLAUDE_SKILL_DIR}/scripts/skillmap.py`.
Cache: `~/.claude/cache/skill-map/` (`skills/<name>.json`, `skill-map.html`).

## Steps
1. `skillmap.py scan` (`full` arg: add `--full`). Prints `<unit>\t<lwt>\t<files>\t<kind>\t<folder>\t<output>` per stale unit,
   or `none`.
   - Units: skills, hooks (`settings.json`), mods (`mods/*/`), enabled plugins; kind `skill`, `hook`, `mod`, `plugin`.
   - Plugin skill (`<plugin>/skills/<name>/SKILL.md`): own skill unit `<plugin>:<name>`; plugin unit keeps other files.
   - Stale: no fragment; `lwt` digest differs from skill folder md mtimes and sizes; or agent type file newer than `lwt` scan time.
   - No `lwt` key, fragment newer than its md and agent files: script adds current digest, fragment mtime as scan time; not stale.
   - Removed skill: fragment deleted.
2. Stale lines go to agents, `subagent_type: "general-purpose"`, `model: "sonnet"`, `effort: "medium"`.
   - Each agent takes 2+ skills (start ~48k tok). Md over 15 KB: 2 per agent; smaller: up to 4.
   - Lone skill left: own agent.
   - At most 3 agents per message; next 3 after those finish.
   - Brief: unit name, `lwt`, kind, folder, file list, output path (scan columns).
   - Brief ends: "Read `${CLAUDE_SKILL_DIR}/reference/extract.md` and follow it."
3. `skillmap.py render`: checks fragment shape and refs, writes and opens `skill-map.html`, prints path.
   - Page: Savings card (no title), top left: total tok, est. time, skill fixes, top 5 token savings (`scripts/cost.py`).
   - Each item: copyable AI prompt; red marks its card. Click card or arg: that flow plus callers (dashed); no trace: whole map.
   - Then one `problem: <skill>: <text>` line per fault (exit 1); faulty fragment gets `lwt` `broken`, so next scan lists it.
   - Page shows only hints a verifier marked `ok` (`verdicts.json`). One `unchecked hint: <key>\t<skill>\t<prompt>` line per
     hint never checked; `wrong` hints stay hidden.
4. Problem lines: rerun that skill's agent once, its problems added to brief; render again. Still failing: reply names that skill.
   - `missing: <unit>: <text>` lines (hook script or tool, mod module, plugin, MCP server gone): no rerun; page lists
     them as fix items; reply names them.
5. Unchecked hint lines go to verifier agents, `general-purpose`, `sonnet`, `medium`. Up to 5 hints per agent.
   - At most 3 agents per message. Brief: the lines, script path
     `${CLAUDE_SKILL_DIR}/scripts/skillmap.py`, then "Read `${CLAUDE_SKILL_DIR}/reference/verify.md` and follow it."
   - Then render again.
6. Reply: page path, stale skills re-read, hints checked (ok, wrong with reason), problems left.
