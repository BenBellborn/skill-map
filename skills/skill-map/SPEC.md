---
spec: SKILLMAP
domain-terms: [sonnet, general-purpose, opus]
---

# Skill map

## Purpose

The skill map gives the user of a Claude Code setup one zoomable page that shows every user skill under
`~/.claude/skills`: which md files, other skills and agents each skill command pulls in, under which condition and
under which argument, plus agent model, effort, count and start context size. A scan step lists only skills whose md
files changed since their last extraction; agents read those skills and write one fragment per skill; a render step
checks the fragments, builds a graph, lays it out in columns and writes and opens one self-contained page. Hooks,
mods, enabled plugins and the MCP servers they or the skills use show on the same page (R18). The skill never changes
a skill file.

## Glossary

- **Root:** text, folder path. The Claude config folder; default `~/.claude` of the current user. Skills sit in
  `<root>/skills`, agent type files in `<root>/agents`.
- **Cache folder:** text, folder path. Default `<root>/cache/skill-map`. Holds the fragment folder `skills` and the
  page file `skill-map.html`.
- **Skill:** a folder `<root>/skills/<name>` that holds a file named exactly `SKILL.md`. A folder whose name starts
  with `.` or equals `synced` is no skill. Skill name: the folder name, case kept. Skills are taken in ascending order
  of folder path.
- **Skill md file:** each file whose name ends in `.md` at any depth in a skill folder, except files named `SPEC.md`
  (the rebuild spec, at any depth) and files with any path part, relative to the skill folder, that starts with `.`.
  Taken in ascending order of full path.
- **Agent type file:** `<root>/agents/<type>.md`, the definition of agent type `<type>`.
- **Unit:** one source an agent reads into one fragment: a skill, a hook, a mod or a plugin (R18). Unit name: the skill
  name, or `hook-<name>`, `mod-<name>`, `plugin-<name>`. Unit files: the skill md files of a skill, else the files R18
  names. A unit with no files (a hook that runs a tool) gets no fragment and is drawn from `settings.json` alone.
- **LWT:** text `<digest>@<scan time>`. Digest: 40 lowercase hex digits, the SHA-1 digest of the skill md files of one
  skill (see R2); it changes when any skill md file is added, removed, renamed, touched or resized. Scan time: the
  wall-clock time in integer nanoseconds when `scan` started. A value with no `@` part has no scan time.
- **Fragment:** record Fragment, stored as `<cache folder>/skills/<skill name>.json`. One per skill; written by an
  extraction agent.
- **Stale skill:** a skill whose fragment must be written again (see R3).
- **Problem:** text pair of skill name and problem text. Printed as `problem: <skill>: <text>`; on the page a fix item with a repair prompt.
- **Ref:** text in a fragment that names a load or call target: a skill name, a path relative to the skill folder, a
  path starting with `~/.claude/`, or a text starting with `builtin:`, `project:`, `mcp:` or `tool:`.
- **Outside ref:** a ref that starts with `builtin:` (a built-in skill or tool command), `project:` (a file of the
  repo the user works in) or `mcp:<server>` (an MCP server; `<server>` is the part between `mcp__` and the next `__`
  of its tool names) or `tool:<name>` (a CLI tool the unit runs that is not part of Claude Code; `when` `if installed`
  marks it optional).
- **Owner:** the skill whose fragment holds a ref. A ref in an agent entry has the skill of that fragment as owner.
- **Node:** record Node. One card on the page.
- **Edge:** record Edge. One line on the page from a loader node to a target node, kind `load`, `call` or `spawn`.
- **Loader:** the node a ref starts from: the skill node, or the agent node for refs inside an agent entry.
- **Own md:** a ref that resolves to a file inside the owner's skill folder and has exactly one owner over all refs.
  It is listed inside the loader card, not drawn as its own card.
- **Shared:** boolean on each node: true when refs from two or more different owners point at it.
- **Back edge:** an edge that closes a cycle in the graph; drawn dashed as a loop below the cards.
- **Tok:** integer. File size in bytes divided by 4, rounded down. Shown as `~<tok> tok md`.
- **Start ctx:** the tok of an agent: the summed bytes of all md files the agent loads plus its agent type file,
  divided by 4, rounded down.
- **Trace:** page state that highlights everything reachable from one card, or from one argument of one card.

## Interfaces

### Command `/skill-map`

- **Kind:** user command of the Claude Code session.
- **Inputs:**
  - `full`: optional word, default absent. Present: every skill is stale, so every skill is read again.
- **Output:** the page opens in the default browser. The reply names the page path, the stale skills read again,
  and the problems left (one line per skill whose problems stay after one rerun).
- **Errors:** problems after one rerun of the agent of that skill stay in the reply, one line per skill; no other
  error.
- **Example:** `/skill-map full`

### Command `scan`

- **Kind:** command of the map tool, first positional argument.
- **Inputs:**
  - `--root <path>`: optional text, default `~/.claude`.
  - `--cache <path>`: optional text, default empty, which means `<root>/cache/skill-map`.
  - `--full`: optional flag, default off. On: every skill is stale.
- **Output:** standard output. One line per stale unit with files, skills first in skill order, then hooks, mods and
  plugins: `<unit name>`, tab, `<lwt>`, tab, the unit file paths relative to the unit folder with `/` separators,
  joined by `,`, tab, the unit kind (`skill`, `hook`, `mod`, `plugin`), tab, the unit folder as an absolute path with
  `/` separators, tab, the unit's fragment file path with `/` separators. No stale unit: the single line `none`. Exit
  code 0. Side effect: each fragment file that is no unit's fragment file is deleted.
- **Errors:** an unknown first argument fails argument parsing with a usage message and exit code 2.
- **Example:**

```text
fix	3f2a9c1d0b7e4a5f6c8d9e0a1b2c3d4e5f607182@1763700000000000000	SKILL.md,reference/loop.md	skill	C:/Users/me/.claude/skills/fix
mod-clr	9a8b7c6d5e4f30211234567890abcdef12345678@1763700000000000000	.claude-plugin/plugin.json,hooks/register.tsx	mod	C:/Users/me/.claude/mods/clr
```

### Command `render`

- **Kind:** command of the map tool, first positional argument.
- **Inputs:**
  - `--root <path>`: optional text, default `~/.claude`.
  - `--cache <path>`: optional text, default empty, which means `<root>/cache/skill-map`.
  - `--no-open`: optional flag, default off. On: the page is written but not opened.
- **Output:** writes `<cache folder>/skill-map.html` (UTF-8), opens it in the default browser as a `file:` URI unless
  `--no-open`, prints the page path on one line, then one line `unchecked hint: <key>\t<skill>\t<prompt>` per hint
  that has no verdict (R17), then one line `problem: <skill>: <text>` per problem. Exit code 1 when any problem
  exists, else 0; unchecked hints never change it. The cache folder is created when missing.
- **Errors:** see section Errors for each problem text.
- **Example:**

```text
C:\Users\me\.claude\cache\skill-map\skill-map.html
unchecked hint: 3f2a9c1d0b7e	fix	~/.claude/skills/fix/SKILL.md is ~3.5k tok and read on every run of `fix`. Move detail ...
problem: plan: unknown md reference/nope.md
```

### Command `verdict`

- **Kind:** command of the map tool, first positional argument.
- **Inputs:** `<key>` then `ok`, or `<key>` then `wrong` and a reason of one or more words; `--root` and `--cache` as
  for `render`.
- **Output:** stores the verdict for that key in `<cache folder>/verdicts.json` (R17), prints nothing, exit code 0.
- **Errors:** fewer than 2 values, a second value other than `ok` or `wrong`, `ok` with a reason, or `wrong` without
  one: prints `usage: verdict <key> ok | verdict <key> wrong <reason>`, stores nothing, exit code 2.

### Extraction agent brief

- **Kind:** agent touchpoint. One brief per agent; the agent writes fragments and replies.
- **Inputs:**
  - unit name, text, required, one or more per brief.
  - `lwt`, text, required, the value the scan line printed for that unit.
  - unit kind and unit folder, the fourth and fifth scan columns, required.
  - file list, the third scan column, required.
  - output path `~/.claude/cache/skill-map/skills/<unit name>.json`, required.
  - problem lines of an earlier render, optional, only on a rerun.
  - last sentence, required: Read `<skill folder>/reference/extract.md` and follow it.
- **Output:** one fragment file per skill, and one reply line per skill: `ok <skill>` or `failed <skill>: <reason>`.
- **Errors:** `failed <skill>: <reason>` when the agent cannot write a valid fragment.
- **Example:** `ok fix`

### Page

- **Kind:** self-contained HTML page, no network access, data embedded.
- **Inputs:** pointer, wheel and key events of the viewer.
- **Output:** cards, edges, legend, zoom bar, problem list (see R12, R13).
- **Errors:** None.
- **Example:** the viewer clicks the `[all]` argument on the `/fix` card; every card, md line and edge reachable
  under `all` is highlighted and the traced edge labels show.

## Data shapes

### Fragment

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| skill | text | no | none | skill name | 1 | `fix` |
| kind | enum {command, shared} | no | `command` | `shared` when the skill description says to load it before work of other skills | 2 | `command` |
| summary | text | no | empty | 8 words or less | 3 | `builds TODO task, red test first` |
| lwt | text | yes for a fresh skill | none | value from the scan line, unchanged | 4 | `3f2a...` |
| args | list of FragmentArg | no | empty list | only args that change loads, calls, agents or loop | 5 | see FragmentArg |
| loads | list of Load | no | empty list | own flow of the skill only | 6 | see Load |
| calls | list of Call | no | empty list | own flow of the skill only | 7 | see Call |
| agents | list of AgentEntry | no | empty list | each distinct agent spawn | 8 | see AgentEntry |

### FragmentArg

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| id | text | yes | none | arg id; free text or number arg uses `n` | 1 | `all` |
| label | text | no | the id | shown on the arg button; free text or number arg uses `#` | 2 | `all` |
| note | text | no | empty | button tooltip | 3 | `queue, 5 workers max, loop` |

### Load

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| md | text | yes | none | a ref | 1 | `todo-ext` |
| when | text | no | empty | condition in 8 words or less; empty means always | 2 | `TODO source` |
| args | list of text | no | empty list | arg ids under which the load happens; empty means every arg | 3 | `["all"]` |

### Call

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| skill | text | yes | none | a ref | 1 | `review-ext` |
| callArgs | text | no | empty | args passed in the call, separated by spaces | 2 | `uncommitted bugs-only` |
| when | text | no | empty | condition in 8 words or less | 3 | `tests green` |
| args | list of text | no | empty list | arg ids under which the call happens | 4 | `[]` |
| loop | text | no | empty | loop text | 5 | `2 passes max` |

### AgentEntry

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| id | text | yes | none | short name, unique in the fragment | 1 | `worker` |
| type | text | no | empty | agent type of the spawn | 2 | `fix-worker` |
| model | text | no | empty | model name; unknown: empty | 3 | `opus` |
| effort | text | no | empty | effort level; unknown: empty | 4 | `high` |
| count | text | no | empty | how many agents; unknown: empty | 5 | `5 per batch max` |
| when | text | no | empty | condition | 6 | `step 2` |
| args | list of text | no | empty list | arg ids under which the spawn happens | 7 | `["all"]` |
| loop | text | no | empty | loop text | 8 | `until queue empty` |
| loads | list of Load | no | empty list | md files the agent reads at start | 9 | `[{"md": "design-ext", "when": ""}]` |
| calls | list of Call | no | empty list | skills the agent runs | 10 | `[]` |
| items | text | no | empty | work items one agent takes; unknown: empty | 11 | `2-4` |

### Node

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| id | text | yes | none | `skill:<name>`, `agent:<owner>:<agent id>`, `md:<path relative to root>`, `builtin:<name>`, `project:<path>` | 1 | `skill:fix` |
| kind | enum {command, shared, skill, agent, md, builtin, project} | yes | none | `skill`: skill target without a valid fragment | 2 | `command` |
| label | text | yes | none | `/<name>` for kind command and builtin; name for shared and skill; agent id; md path relative to root; text after the outside prefix | 3 | `/fix` |
| summary | text | no | absent | fragment summary; agent type for agents; absent on md, skill and outside nodes | 4 | `builds TODO task` |
| model | text | agents only | empty | model and effort joined by `:`, empty parts left out | 5 | `opus:high` |
| count | text | agents only | empty | agent count | 6 | `5 max` |
| args | list of FragmentArg | yes | empty list | fragment args for skill nodes, else empty | 7 | `[{"id": "all"}]` |
| mds | list of OwnMd | yes | empty list | own md lines of the loader | 8 | see OwnMd |
| tok | integer | yes | 0 | skill: tok of `SKILL.md`; agent: start ctx; md: tok of the file; skill target and outside: 0 | 9 | `310` |
| shared | boolean | yes | false | true when two or more owners point at the node | 10 | `true` |
| x | integer | yes | 0 | column times 380 | 11 | `380` |
| y | integer | yes | 0 | pixel row from the top of the column | 12 | `92` |
| runs | integer | agents only | 1 | first whole number in count, at least 1; 1 when count has no number | 13 | `5` |
| hints | list of Hint | yes | empty list | savings hints of the node (R16) | 14 | see Hint |
| items | text | agents only | empty | the agent entry `items` | 15 | `1` |

### OwnMd

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| name | text | yes | none | path relative to the owner skill folder, `/` separators | 1 | `reference/loop.md` |
| when | text | yes | empty | from the Load | 2 | `loop` |
| args | list of text | yes | empty list | from the Load | 3 | `["all"]` |
| tok | integer | yes | 0 | tok of the file | 4 | `100` |
| hints | list of Hint | yes | empty list | savings hints of the line (R16) | 5 | see Hint |

### Hint

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| save | integer | yes | none | tokens the change would save in one run | 1 | `96620` |
| prompt | text | yes | none | names the file or agent and the change, so an AI given only this line knows what to edit (R16) | 2 | ``In skill `fix`, agent `worker` starts 3 times at ~54.0k tok each. Give each agent 2 items so it starts 2 times, with the same result.`` |
| key | text | yes | none | first 12 lowercase hex digits of the SHA-1 of the UTF-8 prompt (R17) | 3 | `3f2a9c1d0b7e` |

### Problem

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| skill | text | yes | none | unit name the problem belongs to | 1 | `plan` |
| text | text | yes | none | problem text, as the report line prints it after `<skill>: ` | 2 | `unknown md reference/nope.md` |
| prompt | text | yes | none | text `unknown <kind> <ref>`: ``Skill `<skill>` (~/.claude/skills/<skill>/) names <kind> `<ref>`, which does not exist. Fix that name in its md files so it points at an existing <file or skill>, then run /skill-map.``; a missing target: the prompt R18 names; any other text: ``Run /skill-map: the map data of skill `<skill>` is malformed (<text>); the run reads the skill again.`` | 3 | ``Run /skill-map: the map data of skill `plan` is malformed (agent without id); the run reads the skill again.`` |
| node | text | no | absent | missing target only: id of the card the problem marks; absent: `skill:<skill>` | 4 | `hook:gone` |

### Cost

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| agentBase | integer | yes | 48000 | tokens of one agent start before any md | 1 | `48000` |
| msPerTok | integer | yes | 2 | milliseconds of run time per context token | 2 | `2` |

### Edge

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| id | integer | yes | none | 0, 1, 2 in creation order | 1 | `0` |
| src | text | yes | none | loader node id | 2 | `skill:fix` |
| dst | text | yes | none | target node id | 3 | `skill:plan` |
| kind | enum {load, call, spawn} | yes | none | from Load, Call or AgentEntry | 4 | `call` |
| when | text | yes | empty | from the entry | 5 | `task not planned` |
| args | list of text | yes | empty list | from the entry | 6 | `["all"]` |
| callArgs | text | yes | empty | from the entry | 7 | `3` |
| loop | text | yes | empty | from the entry | 8 | `until queue empty` |
| count | text | yes | empty | agent count for spawn, else empty | 9 | `5 max` |
| back | boolean | yes | false | true for a back edge | 10 | `false` |

### PageData

| Name | Type | Required | Default | Values | Order | Example |
|---|---|---|---|---|---|---|
| nodes | list of Node | yes | empty list | creation order | 1 | see Node |
| edges | list of Edge | yes | empty list | creation order | 2 | see Edge |
| problems | list of Problem | yes | empty list | one per problem, in report order, except `no fragment, run scan` and `changed since the map was drawn`: `/skill-map` re-reads those skills before `render`, so the page never shows them | 3 | see Problem |
| cost | Cost | yes | see Cost | constants the Token saver & fix card uses | 4 | `{"agentBase": 48000, "msPerTok": 2}` |

## File formats

### Fragment file

- Path `<cache folder>/skills/<skill name>.json`, each `:` in the name written as `--` (Windows file names hold no
  `:`), UTF-8, one JSON object of record Fragment.
- A file that does not parse, or parses to anything other than an object, counts as no fragment.
- When render drops the `lwt` of a fragment, it writes the object again as JSON with 1-space indent, keys in their
  existing order, without `lwt`.

```json
{
  "skill": "fix",
  "kind": "command",
  "summary": "builds TODO task, red test first",
  "lwt": "3f2a9c1d0b7e4a5f6c8d9e0a1b2c3d4e5f607182@1763712000323456789",
  "args": [{"id": "all", "label": "all", "note": "queue, 5 workers max, loop"}],
  "loads": [{"md": "todo-ext", "when": "TODO source", "args": []}],
  "calls": [{"skill": "review-ext", "callArgs": "uncommitted bugs-only", "when": "tests green", "args": [], "loop": "2 passes max"}],
  "agents": [{"id": "worker", "type": "fix-worker", "model": "opus", "effort": "", "count": "5 per batch max", "when": "",
              "args": ["all"], "loop": "until queue empty", "loads": [{"md": "design-ext", "when": ""}], "calls": []}]
}
```

### Page file

- Path `<cache folder>/skill-map.html`, UTF-8, overwritten on each render.
- One HTML document; the PageData record is embedded as JSON text inside the element
  `<script id="data" type="application/json">`. In that JSON every `</` is written as `<\/`.
- Title `Skill Map`. No external resource.

```text
<script id="data" type="application/json">{"nodes": [{"id": "skill:fix", "kind": "command", "label": "/fix",
"summary": "", "args": [], "mds": [], "tok": 2, "shared": true, "x": 0, "y": 0}], "edges": [], "problems": []}</script>
```

### LWT input lines

- For each skill md file, in order: `<path relative to skill folder with / separators>|<modification time in
  integer nanoseconds>|<size in bytes>`, followed by a line feed. The LWT digest is the lowercase hex SHA-1 of the UTF-8
  bytes of all lines in order.

```text
SKILL.md|1763712000123456789|1946
reference/extract.md|1763712000223456789|3174
```

## Behavior rules

### R1 Skill discovery

A skill is each folder `<root>/skills/<name>` that holds `SKILL.md`, except names that start with `.` and the name
`synced`. Skills are listed in ascending folder path order.

- **SKILLMAP-1.1:** Given skills `fix`, `plan`, `design-ext` and `.trash/old`, each with `SKILL.md`, and no fragments,
  when `scan` runs, then it lists exactly `design-ext`, `fix` and `plan`.
- **SKILLMAP-1.2:** Given a folder `<root>/skills/synced` with `SKILL.md`, when `scan` runs, then no line names
  `synced`.

### R2 LWT

The LWT of a skill is the SHA-1 hex digest of one line per skill md file (path, modification time in nanoseconds,
size; see File formats). Files named `SPEC.md` and files under a path part that starts with `.` take no part.

- **SKILLMAP-2.1:** Given a fresh fragment for `fix`, when `<root>/skills/fix/SPEC.md` is written, then `scan` prints
  `none`.
- **SKILLMAP-2.2:** Given a fresh fragment for `fix`, when the modification time of `reference/loop.md` moves 5 s
  later, then `scan` lists only `fix`.

### R3 Stale skill

`scan` lists a skill when `--full` is on; or the fragment is missing or not a JSON object; or the digest of the
fragment `lwt` differs from the current digest; or an agent type file named by a text `type` in the fragment `agents`
exists and has a modification time later than the scan time of the fragment `lwt` (no scan time: any such file
counts). Each line carries the digest computed at scan time and that scan time, so an edit to a skill md file or an
agent type file made while the agent works keeps the skill stale, however late the agent writes the fragment.

A fragment that has no `lwt` key at all gets the current digest added, with the fragment file's modification time as
scan time, and is not stale, when every skill md file and every agent type file it names has a modification time at
or before the fragment file. `scan` and `render` both do this
before any other check. An `lwt` that is present but differs, the value `broken` included, is never replaced.

- **SKILLMAP-3.1:** Given fragments with the current LWT for every skill, when `scan` runs, then it prints `none`.
- **SKILLMAP-3.2:** Given fresh fragments and a `fix` fragment with an agent of type `fix-worker`, when
  `<root>/agents/fix-worker.md` gets a modification time 5 s later, then `scan` lists only `fix`. Given a `fix` scan
  line, when `fix-worker.md` changes and then the agent writes the `fix` fragment with that line's LWT, then the next
  `scan` lists `fix`. Given no fragments, when the agents write fragments that name agent types with the LWT of each
  scan line, then `render` exits 0 and `scan` prints `none`.
- **SKILLMAP-3.3:** Given fresh fragments for 3 skills, when `scan --full` runs, then it prints 3 lines.
- **SKILLMAP-3.4:** Given no fragments, when `scan` runs, then each skill gets a line
  `<name>\t<lwt>\t<md files joined by ,>`.

### R4 Removed skill

`scan` deletes each fragment file in `<cache folder>/skills` whose name without `.json` names no skill.

- **SKILLMAP-4.1:** Given a fragment `deleted.json` and no skill folder `deleted`, when `scan` runs, then
  `deleted.json` does not exist.

### R5 Fragment loading in render

For each skill in order: no readable fragment gives problem `no fragment, run scan` and the skill has no fragment in
the graph. A fragment whose `lwt` digest differs from the current digest, after the missing-`lwt` step of R3, gives problem
`changed since the map was drawn` and is still drawn. After the graph is built, each fragment of a skill with any
problem gets `lwt` `broken` (file written again only when it held another value), so the next `scan` lists that
skill and no missing-`lwt` step can mark it fresh.

- **SKILLMAP-5.1:** Given fragments for `fix` and `design-ext` but none for `plan`, when `render` runs, then it exits 1
  and prints `problem: plan: no fragment, run scan`.
- **SKILLMAP-5.2:** Given fragments without `lwt` written after every md file, when `render` runs, then it exits 0,
  the `fix` fragment holds the current LWT and `scan` prints `none`. Given the same, but `fix/reference/loop.md` is
  5 s later than the fragment, then `render` prints `problem: fix: changed since the map was drawn` and `scan` lists
  `fix`.
- **SKILLMAP-5.3:** Given fresh fragments where `plan` calls skill `nosuch`, when `render` runs and then `scan` runs,
  then `scan` lists only `plan`.

### R6 Fragment shape check

A fragment with a shape problem gives each problem text and is not drawn as a skill node. Checks run in this order:
1. `args` or `agents` not a list: `args not a list` or `agents not a list`; no further checks.
1. Each top-level arg that is not an object with a text `id`: `arg without id`.
1. `loads` or `calls` not a list: `loads not a list` or `calls not a list`. Each entry that is not an object with a
   text `md` (loads) or `skill` (calls): `load without md` or `call without skill`. Each valid entry gets the field
   type check.
1. Each agent that is not an object with a text `id`: `agent without id`. Else its `loads` and `calls` get the checks
   of step 3, then the agent gets the field type check.

Field type check: each present key of `when`, `callArgs`, `loop`, `type`, `model`, `effort`, `count`, `items` that is
not text gives `<key> not text`; an `args` that is not a list of text gives `args not a list of text`.

- **SKILLMAP-6.1:** Given `plan` with loads `[{"path": "x.md"}]` and agents `[{"type": "general-purpose"}]`, when
  `render` runs, then it exits 1 and prints `problem: plan: load without md` and `problem: plan: agent without id`.
- **SKILLMAP-6.2:** Given `plan` with calls `[{"skill": "fix", "callArgs": ["a"], "args": "all"}]` and agents
  `[{"id": "w", "model": 5}]`, when `render` runs, then it exits 1 and prints `problem: plan: callArgs not text`,
  `problem: plan: args not a list of text` and `problem: plan: model not text`.

### R7 Ref resolution

A ref resolves in this order:
1. Outside ref: node id is the ref; node kind is the prefix (`builtin` or `project`), label the text after the first
   `:` (for `builtin` with `/` in front, as a command reads), tok 0. Created once.
1. Ref equal to a skill name: node id `skill:<name>`.
1. Else a path: a ref starting with `~/.claude/` is `<root>/<rest>`, any other ref is relative to the owner skill
   folder. An existing file gets node id `md:<path relative to root, / separators>`. A missing file gives problem
   `unknown md <ref>` when the ref ends in `.md`, else `unknown skill <ref>`, and the ref is dropped.

A skill target with no valid fragment gets node kind `skill`, label the bare name, tok 0.

- **SKILLMAP-7.1:** Given `plan` with loads `[{"md": "reference/nope.md"}]` and no such file, when `render` runs, then
  it exits 1 and prints `problem: plan: unknown md reference/nope.md`.
- **SKILLMAP-7.2:** Given `plan` with calls `[{"skill": "builtin:code-review"}]` and all else valid, when `render`
  runs, then it exits 0, node `builtin:code-review` has kind `builtin`, label `/code-review` and the builtin colour,
  and a load of `project:CLAUDE.md` gives label `CLAUDE.md`.
- **SKILLMAP-7.3:** Given `fix` calls `plan` and `plan` has no fragment, when `render` runs, then node `skill:plan`
  has label `plan`.

### R8 Own md and shared nodes

Owners of a target: the set of distinct owner skills over all refs to it, spawns included. A ref that resolves to a
file inside the owner skill folder and whose target has exactly one owner is an own md: it becomes an OwnMd line on
the loader node (name relative to the owner skill folder, `when`, `args`, tok) and gets no node and no edge. Every
other ref becomes an edge, and its target node is created when missing. Each node gets `shared` true when it has two
or more owners.

- **SKILLMAP-8.1:** Given `fix` loads `reference/loop.md` with args `["all"]` and no other skill loads it, when `render`
  runs, then the `skill:fix` node has mds `[("reference/loop.md", ["all"])]` and no node id ends in `loop.md`.
- **SKILLMAP-8.2:** Given `fix` and `plan` both load `~/.claude/reference/error-review.md` and `design-ext`, when
  `render` runs, then nodes `md:reference/error-review.md` and `skill:design-ext` have `shared` true.

### R9 Agent nodes

Each agent entry becomes node `agent:<owner>:<id>` of kind `agent`, label the id, summary the `type`, model the
`model` and `effort` joined by `:` with empty parts left out, count and items. Its tok is the start ctx: the bytes of each
load target (a skill name counts its `SKILL.md`, an outside ref counts 0, a missing file counts 0) plus the bytes of
`<root>/agents/<type>.md`, divided by 4, rounded down. A spawn edge goes from the skill node to the agent node and
carries the agent `when`, `args`, `loop` and `count`. The agent loads and calls get the agent node as loader.

- **SKILLMAP-9.1:** Given agent `worker` of `fix` with type `fix-worker` (40 bytes), model `opus`, effort `high`,
  loading `design-ext` (`SKILL.md` 800 bytes) and `reference/loop.md` (400 bytes), when `render` runs, then node
  `agent:fix:worker` has tok 310 and model `opus:high`.
- **SKILLMAP-9.2:** Given the agent `worker` with args `["all"]`, when `render` runs, then the edge into
  `agent:fix:worker` has kind `spawn` and args `["all"]`.

### R10 Layout

1. Root order: node ids of kind `command` in ascending order, then all other node ids in ascending order.
1. Back edges: a depth-first walk from each root not yet done, following edges in creation order. An edge whose
   target is on the current walk path gets `back` true; every other edge gets `back` false.
1. Bands: left to right `command`, `agent`, then `hook`, `mod` and `plugin` together, then `shared`, `skill`, `md`,
   `project`, `builtin`, `mcp`, `tool`, then any other kind. Only bands that hold a node take columns. The hook, mod and
   plugin band and the `mcp` band are one column each: no edge inside them sets a layer. Commands own the far left; a
   mod's edge into a command is drawn leftward.
1. Layers: inside each band, every node starts at layer 0; over forward edges whose source and target sit in that
   band, the target layer becomes source layer plus 1 whenever it is not greater, repeated until nothing changes or as
   many passes as nodes. The column of a node is the sum of the column counts of the bands left of it, plus its layer;
   a band's column count is its largest layer plus 1.
1. Columns: one per layer; inside a column ids in ascending order. Column 0 keeps that order. Each later column is
   sorted, stable, by the mean row of the sources of edges into each node that sit in earlier columns; a node without
   such source goes last.
1. Stack: each column becomes one block. Limit is the height of the tallest column: its cards' heights plus 28
   between cards. Flow cost: each edge between two nodes costs its column span (target column minus source column,
   as an absolute number), plus 100 when the span is 0 or less. Repeat: over every pair of a column that is not the
   first and another column, try moving all blocks of the first under the blocks of the second, when the joined
   height stays within the limit; empty columns close up. Keep the try with the lowest cost when it is lower than the
   current cost, the first such try on a tie in order of moved column, then target column; stop when no try lowers
   the cost.
1. Place: limit as in Stack. Score: flow cost plus 15 per column an edge passes (its absolute span less 1), less 30
   times cohesion. Cohesion: per band with 2 or more nodes, the
   pairs of its nodes that share a column, divided by its node count less 1; a node that leaves a column holding all
   the rest of its band so loses 1. A backward edge (100) costs more than that (30), so it moves a node out of its
   band's column. Repeat: over every node that is not a command, in ascending id order, and every column it does not
   sit in, try moving it into the block of that column that holds a node it shares an edge with, else the last block,
   when that column stays within the limit; empty blocks and columns close up. Keep the try with the lowest score
   when it is lower than the current score, the first such try on a tie; stop when no try lowers the score.
1. Positions: x is column times 380. y starts at 0 per column; each card, block after block, adds its height plus 28.
   Height is 64 plus
   18 per OwnMd line, plus 18 when the node has args, plus 18 for an agent.
1. Pull: then 40 sweeps over the columns, left to right on even sweeps and right to left on odd ones. In each column
   every card linked by an edge (either way, self edges left out) wants its center at the mean center of its linked
   cards; a card with no link wants its current y. Each block re-sorts its cards, stable, by wanted center; blocks
   keep their stack order. The column then takes the y values closest to those wishes in least squares that keep that
   order and at least 28 between cards. Last, all y values shift so the top card sits at 0, rounded to whole pixels.

- **SKILLMAP-10.1:** Given `fix` calls `plan` and `plan` calls `fix`, when `render` runs, then edge fix to plan has
  `back` false, edge plan to fix has `back` true, and the `skill:plan` x is greater than the `skill:fix` x.
- **SKILLMAP-10.2:** Given `fix` spawns an agent, loads a shared md and calls `builtin:code-review`, and `plan` is a
  command, when `render` runs, then x grows from command cards to the agent, shared skill, md and builtin cards.
- **SKILLMAP-10.3:** Given cards `a`, `b`, `c` in one column and an edge from `c` to `d`, when the layout runs,
  then `d` sits right of `c` at the same y, `a`, `b` and `c` stay 92 apart, and the top card sits at y 0.
- **SKILLMAP-10.4:** Given column `a`, `b`, column `c`, `d` and edges `a` to `d` and `b` to `c`, when the pull runs,
  then the two edges no longer cross: `d` sits level with `a` and `c` level with `b`.
- **SKILLMAP-10.5:** Given one card of each kind command, agent, hook, mod, plugin, shared, builtin, tool and two mcp
  cards linked to each other, when the layers are built, then the layer grows command, agent, the hook-mod-plugin
  column, shared, builtin, the mcp column, tool.
- **SKILLMAP-10.6:** Given command `c` with 10 OwnMd lines that calls agent `a` and md `m`, and `a` spawns shared `s`,
  when the layout runs, then `c` stays at x 0, `m` stacks under `a` in one column, and `s` sits right of them: 3
  columns. With no OwnMd lines on `c` the tallest column is too short for any stack: 4 columns.

- **SKILLMAP-10.7:** Given columns `c` | `r` | `s` | `a1`, `a2`, `a3` (commands, shared, agents) and edges `c` to
  `a1` and `a1` to `s`, when the place step runs, then `a1` moves under `r`, left of `s`, and `a2`, `a3` stay in
  their column.

### R11 Page writing

`render` embeds the PageData as JSON in the page template, writes it to `<cache folder>/skill-map.html`, opens it
unless `--no-open`, prints the path, then the problem lines. Problems from fragment loading come first in skill
order, then problems from the graph.

- **SKILLMAP-11.1:** Given a summary that holds `</script>`, when `render` runs, then the page JSON holds
  `<\/script>` and the page still parses.

### R12 Page cards and edges

- Card colour by kind: command, shared, agent, md, builtin, hook, mod, plugin, mcp, tool; every other kind uses the
  outside colour. An md node with `shared`
  true has a dashed border.
- Card head: label, and a tag: for an agent the model and count joined by ` · `; for md `shared md` or `md`; for a
  skill target `skill`; else the kind.
- Meta line: summary and `~<tok> tok md` (when tok is not 0) joined by ` · `.
- OwnMd lines: `<name> ~<tok>` and the `when` text right-aligned; tooltip the `when`.
- Arg buttons: `[<label or id>]`, tooltip the note.
- Before edges are drawn, cards in one column (same x) are sorted by y and stacked from the top, 8 px apart: each card
  starts 8 px below the bottom of the card above it, the first at y 0.
- Every edge leaves the right side of the source card and enters the left side of the target, both 18 px below the
  card top. Target right of the source: curve between those points. Target in the same column or a column further left:
  dashed loop that bends out right of the source, runs left 40 px below the lower card, and bends into the left side of
  the target. Back edges are dashed. Edges have no arrow head: the left side of a card is in, the right side is out.
- Edge label: `spawn <count>` for spawn (or `spawn` when count is empty), else the kind, then `callArgs`, `when`,
  `loop`, non-empty parts joined by ` · `. Longer than 60 characters: first 57 plus `...`; full text as tooltip.
  Labels show only on traced edges.
- The Token saver & fix card (R16) shows top left; problems show only in it, as fix items. Legend at the bottom
  left.
- A card of node `skill:<skill>` with one or more problems shows a small red `!` badge after its label; its tooltip
  holds the `prompt` of each problem, one per line. A problem whose skill has no card shows only in the Token saver &
  fix card.
- Colours follow the light or dark system scheme; an attribute `data-theme` of `light` or `dark` on the root element
  forces one. The trace highlight is teal, never red: red marks only savings hints and problems.

- **SKILLMAP-12.1:** Given an agent node with model `opus:high` and count `5 max`, when the page loads, then its tag
  reads `opus:high · 5 max`.
- **SKILLMAP-12.2:** Given `plan` loads a missing `reference/nope.md`, `design-ext` has no fragment and `fix` changed
  since its fragment, when `render` runs, then the page problems hold only the `plan` problem, with the prompt that
  names `reference/nope.md`; the report still prints the `design-ext` and `fix` lines.

### R13 Page trace and view

- Click on a card: trace from that node with no arg. Click on an arg button: trace from that node under that arg;
  the button is highlighted.
- Trace: breadth-first over pairs of node and arg, each pair once. An edge from the node matches when the arg is
  none, the edge args are empty, or the edge args hold the arg. Each matching edge and its label are highlighted;
  the next arg for the target is each token of `callArgs` (split on spaces) that is an arg id of the target node, or
  none when no token is. Each reached card is highlighted, and in it each OwnMd line whose args are empty, hold the
  arg, or when the arg is none. All else is dimmed.
- Hover on a card: its top, right and bottom border and its edges (either way, 2 px) turn white in dark theme, text
  color in light theme. Hover color wins over trace color: a traced edge turns that color too, and a traced or caller
  card's ring as well. Dimming wins over hover: a dimmed card or edge stays dimmed. Leaving the card removes both.
  A hovered card sits above other cards, and its edges move to the top of the edge layer, above all other edges.
- Text in the map (cards, edge labels) cannot be selected; the problem list and legend can.
- Callers: after the trace, every node that reaches the start node over edges, followed backward breadth-first with
  each node once, is shown as a caller card, and each edge on those paths with its label is shown as a caller edge.
  Caller cards and edges are not dimmed and are drawn dashed in the trace color. They are context only: the token
  total, time, fix items and savings hints of the trace count only the traced cards.
- The page head holds an inline SVG favicon (a `data:` URL, no network): a dark rounded square with a blue card
  on the left linked to an orange and a green card on the right.
- The legend lists the kinds in band order (R10): command skill, agent, hook, mod, plugin, shared skill, md,
  project file, builtin, MCP, CLI tool.
- Click on a kind in the legend: every card of that kind is highlighted, the kind is marked, all else is dimmed. A
  second click on the same kind clears it.
- A click on empty space without drag, or the key Escape, clears the trace.
- Pointer drag over 4 px pans the view; the pointer click that ends a pan does not trace. A keyboard click always
  traces.
- Wheel zooms around the pointer by 1.1 per step; buttons `+` and the minus button zoom by 1.2 around the window
  middle. Scale stays from 0.15 to 3.
- Fit (button, key `0`, and on each load or reload): top is the larger of 60 px and the bottom of the Token saver & fix
  card plus 12 px; bottom is the top of the legend minus 12 px. Scale is the smaller of
  `(window width - 80) / content width` and `(bottom - top) / (content height + 60)`, held from 0.05 to 1.2; offset
  40 px left, top px from the top. So every card shows between the top bar and the legend.

- **SKILLMAP-13.1:** Given `fix` with arg `all` calls `plan` with `callArgs` `3` and `plan` has no arg `3`, when the
  viewer clicks `[all]` on `/fix`, then the call edge and the `/plan` card are highlighted and the trace continues
  from `plan` with no arg.
- **SKILLMAP-13.2:** Given a map with agent cards, when the viewer clicks `agent` in the legend, then every agent card
  is highlighted and every other card is dimmed; a second click clears it.

### R14 Command flow

1. `scan` runs, with `--full` when the `full` argument is present.
1. Stale lines go to extraction agents of type `general-purpose`, model `sonnet`, effort `medium`. Each agent takes at
   least 2 skills, since each start costs about 48k tokens: skills with any md over 15 KB go 2 per agent, smaller
   skills up to 4 per agent, and only a lone skill left over gets an agent of its own. At most 3 agents start per
   message; the next 3 start after those finish. Each agent still writes one fragment per skill, so the result is the
   same as with one agent per skill.
1. `render` runs.
1. For each skill with problems, its agent runs once more with those problems added to the brief, then `render` runs
   again. Problems still left: one reply line per skill.
1. Unchecked hint lines go to verifier agents of type `general-purpose`, model `sonnet`, effort `medium`, up to 5
   hints per agent and at most 3 agents per message. Each agent follows R17 and stores one verdict per hint. Then
   `render` runs again.
1. The reply names the page path, the stale skills read again, the hints checked (ok, or wrong with the reason), and
   the problems left.

The command never changes a skill file, and the main session never reads a skill file.

- **SKILLMAP-14.1:** Given `scan` prints `none`, when the command runs, then no agent starts and `render` runs once.

### R15 Fragment extraction

The extraction agent reads each listed md of the skill and writes one fragment:
- Only facts the files state. Unknown model, effort or count: empty text.
- `when`: condition in 8 words or less; empty when always loaded. `args`: arg ids under which the entry happens;
  empty list for every arg. An arg the entry only passes on in `callArgs` does not limit it: empty list.
- Own flow only: what another skill loads goes in that skill's fragment. Own `reference` md files: what they load is
  listed under this skill.
- `lwt` is the brief value, unchanged.
- Refs: another user skill by folder name; a file in the skill folder by relative path; another file under
  `~/.claude` as `~/.claude/<path>`; an agent type file as `~/.claude/agents/<type>.md`; a project file as
  `project:<path>`; a built-in skill or tool command as `builtin:<name>`. An unclear path resolves to a file that
  exists.
- `callArgs`: a token equal to an arg id of the callee lets the trace follow that arg.
- Before the reply: the fragment parses as JSON, every relative `md` exists in the skill folder and every
  `~/.claude/` path exists. Reply `ok <skill>` or `failed <skill>: <reason>`.

- **SKILLMAP-15.1:** Given a skill text that loads `design-ext` before work, when the agent writes the fragment, then
  `loads` holds `{"md": "design-ext", "when": "", "args": []}`.

### R16 Token cost and the Token saver & fix card

The page data gets each agent's runs, the savings hints of each node and OwnMd line, and the Cost constants. Token
counts in hint text show as `<n> tok` below 1000 and as `<n/1000 with one decimal>k tok` from 1000 on.
- Agent with runs of 2 or more whose `items` holds a whole number and the last one is 1 (it takes one item): one
  hint. An `items` of `2-4`, `≤4 per batch` or empty gives no hint: the agent batches already, or the skill does not
  say. Its start ctx is agentBase plus the agent tok; fewer is runs minus runs/2
  rounded up; save is fewer times the start ctx; prompt ``In skill `<owner>`, agent `<label>` starts <runs> times at
  ~<start ctx> each. Give each agent 2 items so it starts <runs - fewer> times, with the same result.``
- Agent with tok over 5000: one hint after that one. Save is (tok minus 2000) times runs; prompt ``In skill
  `<owner>`, agent `<label>` reads ~<tok> of md at start. Brief it with a digest of what it needs, not whole md
  files.``
- Node of kind command or shared with tok over 2000: one hint. Save is tok minus 1000; prompt
  ``~/.claude/skills/<name>/SKILL.md is ~<tok> and read on every run of `<name>`. Move detail into reference files
  loaded only under the condition that needs them.``
- OwnMd line with empty `when`, empty args and tok over 1500: one hint. Save is its tok; prompt
  ``~/.claude/skills/<owner>/<md name> (~<tok>) is read on every run of `<owner>`. Load it only under the condition
  that needs it.`` Owner is the skill of the loader node.
- Every other node and line: no hint. Owner and name come from the node id: `skill:<name>` or
  `agent:<owner>:<agent id>`.
- A hint that saves under 2000 tok is dropped: it shows in no save item and gets no red mark.

The Token saver & fix card sits at the top left, beside the zoom buttons, at most 900 px wide and 40% of the window
high (it scrolls inside). Its head is `Token saver & fix`, with a `Copy all` button when it lists any item. Below it:
1. With no trace: `Whole map · click a card or arg for its tokens, time and fixes`. With a trace:
   `<label>: ~<total> tok read · est. <time>`, then ` · <starts> agent starts` when starts is not 0. Label is the
   card label, plus ` [<arg>]` for a trace from an arg. Its tooltip names agentBase, msPerTok and that parallel
   runs count once.
1. Fix items: one per problem, in report order. With a trace, only the problems whose skill card is highlighted. Head
   `fix · <skill>: <text>` in red.
1. Save items: up to 5 hints, largest save first. With a trace, only the hints of highlighted cards and highlighted
   OwnMd lines; with no trace, the hints of every card and line. Head `save ~<save> tok · <node label>` in red.
1. No items: `Nothing to save or fix here`.

Each item shows its head, its `prompt` below in normal text, and a `Copy` button that copies the prompt. `Copy all`
copies `Fix these in my Claude Code setup (~/.claude):` and then one line `<n>. <prompt>` per listed item,
numbered from 1. A copy button reads `Copied` (or `Copy failed`) for 1.5 s. The card of each fix item's skill, and the
card or OwnMd line of each save item, get a red outline or red text; each redraw clears the old red marks first.

Total: each highlighted agent adds runs times its start ctx and its runs to starts. Each other highlighted node adds
its tok and the tok of its highlighted OwnMd lines, unless every highlighted edge into it is a load from an agent: the
agent tok already holds that md. Time: (agentBase plus the tokens the main session adds) times msPerTok, plus each
highlighted agent's start ctx times msPerTok once. Time shows as `~<n> min` (rounded) from 60 seconds on, else
`~<n> s` with at least 1. Clearing the trace shows the whole-map view again.

- **SKILLMAP-16.1:** Given an agent with count `<=5`, items `1` and tok 310, when `render` runs, then its runs is 5
  and its one hint saves 2 times 48310; given count empty, then runs is 1 and it has no hint; given count `<=5` and
  items `2-4`, `≤4 per batch` or empty, then runs is 5 and it has no hint.
- **SKILLMAP-16.2:** Given a command skill with tok 3500, a shared skill with tok 2000 and an agent with count `3` and
  tok 6000, when `render` runs, then the hints save 2500; none; 54000 and 12000.
- **SKILLMAP-16.3:** Given OwnMd lines of tok 2000 with `when` empty, with `when` `loop`, with args `all`, and one of
  tok 1500, when `render` runs, then only the first line has a hint, saving 2000.
- **SKILLMAP-16.4:** Given the viewer clicks `/skill-map` whose one agent has runs 5, when the trace ends, then the
  Token saver & fix card shows the total with `5 agent starts` and one save item with a `Copy` button for that
  agent.
- **SKILLMAP-16.5:** Given command skills with tok 2999 and 3000 and OwnMd lines of tok 1999 and 2000 read on every
  run, when `render` runs, then only the skill with tok 3000 and the line of tok 2000 have a hint, each saving 2000.

### R17 Hint check before the page shows it

A savings hint is a claim about a skill; a wrong one costs the reader's trust in every other hint. So no hint reaches
the page until a verifier agent has checked it against the skill's md files.
- Each hint R16 makes gets `key`, the first 12 hex digits of the SHA-1 of its prompt. New numbers in the prompt give a
  new key, so a changed hint is checked again.
- `<cache folder>/verdicts.json` holds one JSON object: key to `ok` or `wrong: <reason>`. A missing or unreadable
  file counts as empty.
- `render` keeps on each node and OwnMd line only the hints with verdict `ok`. A hint with no verdict prints one
  `unchecked hint:` line, once per key; a hint with `wrong` stays hidden and prints nothing.
- After the check, `render` writes `verdicts.json` again with only the keys of hints it made this run.
- The verifier reads the skill's `SKILL.md` and every md the prompt or the named agent's flow names. It stores `ok`
  only when a quoted line proves the premise (the number of starts, a read on every run, an md read at start) and the
  change keeps the same result. A cap on agents running at once is no start count, and a skill that already batches
  gets `wrong`. Doubt gives `wrong`.

- **SKILLMAP-17.1:** Given the `fix` worker hint with no verdict, when `render` runs, then the page shows no hint for
  it and one `unchecked hint:` line names it; after `verdict <key> wrong <reason>`, then neither the page nor the
  output shows it; after `verdict <key> ok`, then the page shows it.
- **SKILLMAP-17.2:** Given `verdicts.json` holds a key no hint makes, when `render` runs, then the file holds `{}`.

### R18 Hooks, mods, plugins and MCP servers

- Hooks come from `<root>/settings.json` key `hooks`: event, then groups with `matcher` and `hooks`, each with a
  `command`. A command naming `~/.claude/hooks/<file>` (`.py`, `.sh`, `.js`, `.ts`) is unit `hook-<file stem>`, label
  the file name, files that file when it exists. Any other command is unit `hook-<tool>`, `<tool>` the name after
  `command -v`, else the first 2 words; label `<tool>`; no files. One command under several events is one unit.
- A hook node summary is its events in first-seen order, then the fragment summary, joined by ` · `.
- Each `mcp__<server>__` in a hook's matcher adds a call edge from the hook to node `mcp:<server>`, `when` `matcher`.
- Mods: each `<root>/mods/<name>` that holds `.claude-plugin/plugin.json` is unit `mod-<name>`, label `<name>`.
- Plugins: each key `<name>@<market>` of `enabledPlugins` in `settings.json` with value true, whose first entry in
  `<root>/plugins/installed_plugins.json` key `plugins` names an existing `installPath`, is unit `plugin-<name>`,
  label `<name>`, folder that path.
- Plugin skills: each `<installPath>/skills/<skill>/SKILL.md` is its own skill unit `<name>:<skill>`, folder that
  skill folder, files its md files as for a skill; other skills and fragments name it that way. The plugin unit's files
  leave out every file under such a skill folder. When both nodes exist, the plugin node gets a call edge to the skill
  node, `when` `ships`.
- Mod and plugin files: every file ending in `.py`, `.ts`, `.tsx`, `.js`, `.mjs`, `.cjs`, `.sh`, `.json` or `.md`,
  except names starting with `test_` or holding `.test.`, the names `tsconfig.json`, `package.json` and
  `package-lock.json`, and files under a folder named `node_modules`, `types`,
  `docs`, `__pycache__`, or starting with `.` other than `.claude-plugin`.
- Node id `<kind>:<name>`; kind `hook`, `mod` or `plugin`; tok 0. An `mcp:<server>` ref gets node kind `mcp`, label
  `<server>`.

- Missing targets: each is one Problem with `node`, listed as a fix item and marking that card, printed by `render`
  as `missing: <unit>: <text>`. It never sets the exit code and never sets `lwt` `broken`: a re-read cannot fix it.
  - Hook script that does not exist: text `missing script ~/.claude/<path>`, node the hook.
  - Hook tool (the name after `command -v`, else the first word) not on the PATH: text `missing tool <tool>`.
  - Mod module, each entry of `modules` in `hooks/hooks.json`, not a file under the mod's `hooks` folder: text
    `missing module <entry>`.
  - Enabled plugin with no install entry or no install folder: text `not installed`; the plugin gets a bare card.
  - `mcp:<server>` ref whose server is in no `mcpServers` of `<root>/../.claude.json` (top level or any project), no
    plugin `.mcp.json`, and does not start with `claude_ai_` or `plugin_`: text `unknown mcp server <server>`,
    unit the ref owner, node `mcp:<server>`, once per owner and server.
  - `tool:<name>` ref whose `when` does not hold `if installed` and whose name is not on the PATH: text
    `missing tool <name>`, unit the ref owner, node `tool:<name>`, once per owner and tool. Prompt ``\`<owner label>\`
    runs CLI tool `<name>`, which is not installed. Install it, or make the skill fall back when it is missing, then
    run /skill-map.``
  - Prompts: hook ``Hook `<label>` in ~/.claude/settings.json runs `<target>`, which does not exist, so the hook never
    does anything. Remove that hook from settings.json, or restore the file or install the tool, then run
    /skill-map.``; mod ``Mod `<name>` (~/.claude/mods/<name>/) lists module `<entry>` in hooks/hooks.json, which does
    not exist, so the mod never loads it. Fix the list or restore the file, then run /skill-map.``; plugin ``Plugin
    `<key>` is enabled in ~/.claude/settings.json but not installed, so it never runs. Install it, or remove it from
    enabledPlugins, then run /skill-map.``; MCP ``\`<owner label>\` uses MCP server `<server>`, which no MCP config
    lists (~/.claude.json, a plugin's .mcp.json). Add the server, or fix the name where it is used, then run
    /skill-map.``

- **SKILLMAP-18.1:** Given a script hook, a tool hook under two events, a mod with a test file and a type stub, and
  one enabled and one disabled plugin, when `scan` runs, then it lists `hook-rules` with `rules.py`, `mod-clr` with
  `.claude-plugin/plugin.json,hooks/register.tsx`, `plugin-ccm` with `ccm.py`, and no line for the tool hook or the
  disabled plugin.
- **SKILLMAP-18.2:** Given those units with fragments, the hook matcher `^mcp__codemap-mcp__.*`, the mod calling `fix`
  and `plan` calling `mcp:lizard`, when `render` runs, then the tool hook card has summary
  `PostToolUse · SessionStart`, the edges hook to `mcp:codemap-mcp`, mod to `skill:fix` and plan to `mcp:lizard`
  exist, hook, mod and plugin cards share one x, mcp cards share one x, and the leftmost command card sits at x 0.
- **SKILLMAP-18.3:** Given a hook script that is gone, a hook tool not installed, a mod module that is gone, an enabled
  plugin with no install, and `plan` using MCP servers `lizard` (in a project config), `nope` and `claude_ai_Gmail`,
  when `render` runs, then exactly those 5 missing targets are fix items with their nodes (`mcp:nope` for the MCP one),
  each prints a `missing:` line, no `problem:` line shows, and the exit code is 0.
- **SKILLMAP-18.4:** Given `plan` calls `tool:python`, `tool:no-such-tool-x`, and `tool:no-such-tool-y` with `when`
  `if installed`, when `render` runs, then only `missing tool no-such-tool-x` is a fix item, the optional tool still
  gets a card of kind `tool`, and tool cards sit in the rightmost column.
- **SKILLMAP-18.5:** Given enabled plugin `ccm` with `ccm.py` and skill folder `skills/pane` (`SKILL.md`,
  `reference/look.md`, `scripts/pane.py`), and `plan` calls `ccm:pane`, when `scan` runs, then unit `ccm:pane` (kind
  `skill`, files `reference/look.md,SKILL.md`, fragment file `ccm--pane.json`) is listed and `plugin-ccm` keeps only
  `ccm.py`; when `render` runs, then card `skill:ccm:pane` reads `/ccm:pane`, with edges from `plugin:ccm` and
  `skill:plan`.

## Errors

| Trigger | Text | Exit code | What stays changed |
|---|---|---|---|
| render: skill has no readable fragment | `problem: <skill>: no fragment, run scan` | 1 | page written |
| render: fragment `lwt` digest differs from the current digest after the missing-`lwt` step | `problem: <skill>: changed since the map was drawn` | 1 | page written; fragment gets `lwt` `broken` |
| render: `args` or `agents` not a list | `problem: <skill>: args not a list` or `agents not a list` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: `loads` or `calls` not a list | `problem: <skill>: loads not a list` or `calls not a list` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: arg without text id | `problem: <skill>: arg without id` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: load without text md | `problem: <skill>: load without md` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: call without text skill | `problem: <skill>: call without skill` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: agent without text id | `problem: <skill>: agent without id` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: text field of another type | `problem: <skill>: <key> not text` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: `args` of entry not a list of text | `problem: <skill>: args not a list of text` | 1 | fragment gets `lwt` `broken`; skill not drawn |
| render: md ref to missing file | `problem: <skill>: unknown md <ref>` | 1 | fragment gets `lwt` `broken`; ref dropped, rest drawn |
| render: skill ref to no skill and no file | `problem: <skill>: unknown skill <ref>` | 1 | fragment gets `lwt` `broken`; ref dropped, rest drawn |
| scan or render: unknown command word | usage message on standard error | 2 | nothing |

## Non-goals

- Never changes, moves or deletes a skill md file or agent type file.
- Never reads skill files in the main session; only extraction agents read them.
- Never guesses model, effort, count or conditions the skill files do not state.
- Never draws a fragment with a shape problem as a skill node.
- Never loads a resource from the network in the page.
- Never treats `SPEC.md` as a skill md file.
- Never changes a hook, mod or plugin file, or `settings.json`.
