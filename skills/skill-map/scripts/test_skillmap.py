"""Tests for skillmap.py: `python -m pytest -q skills/skill-map/scripts`."""
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import cost  # noqa: E402
import layout  # noqa: E402
import skillmap  # noqa: E402
import units  # noqa: E402
import usage  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_tree(tmp: Path) -> tuple[Path, Path]:
    root, cache = tmp / "claude", tmp / "cache"
    write(root / "skills/fix/SKILL.md", "fix skill")
    write(root / "skills/fix/reference/loop.md", "x" * 400)
    write(root / "skills/plan/SKILL.md", "plan skill")
    write(root / "skills/design-ext/SKILL.md", "y" * 800)
    write(root / "skills/.trash/old/SKILL.md", "gone")
    write(root / "reference/error-review.md", "z" * 120)
    write(root / "agents/fix-worker.md", "w" * 40)
    return root, cache


def fragment(cache: Path, skill: str, **fields) -> None:
    data = {"skill": skill, "kind": "command", "args": [], "loads": [], "calls": [], "agents": [], **fields}
    write(cache / "skills" / f"{skill}.json", json.dumps(data))


def default_fragments(cache: Path) -> None:
    fragment(cache, "fix",
             args=[{"id": "all", "label": "all", "note": "loop"}],
             loads=[{"md": "design-ext", "when": "always"},
                    {"md": "reference/loop.md", "when": "loop", "args": ["all"]},
                    {"md": "~/.claude/reference/error-review.md", "when": "end"}],
             calls=[{"skill": "plan", "callArgs": "3", "when": "task not planned"}],
             agents=[{"id": "worker", "type": "fix-worker", "model": "opus", "effort": "high", "count": "<=5",
                      "items": "1", "args": ["all"], "loads": [{"md": "design-ext"}, {"md": "reference/loop.md"}]}])
    fragment(cache, "plan",
             loads=[{"md": "design-ext", "when": "step 1"}, {"md": "~/.claude/reference/error-review.md"}],
             calls=[{"skill": "fix", "when": "nothing left"}])
    fragment(cache, "design-ext", kind="shared")


def run(*argv: str) -> int:
    return skillmap.run_cli(list(argv))


def scan(capsys, root: Path, cache: Path, *extra: str) -> list[str]:
    run("scan", "--root", str(root), "--cache", str(cache), *extra)
    return capsys.readouterr().out.splitlines()


def stamp(capsys, root: Path, cache: Path) -> None:
    """Acts as the agents: copies the `lwt` of each stale scan line into its fragment."""
    for line in scan(capsys, root, cache):
        name, lwt, _ = (line.split("\t") + ["", ""])[:3]
        path = cache / "skills" / f"{name}.json"
        if path.is_file():
            path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "lwt": lwt}), encoding="utf-8")


def render(capsys, root: Path, cache: Path, stamped: bool = True) -> tuple[int, str, dict]:
    if stamped:
        stamp(capsys, root, cache)
    code = run("render", "--root", str(root), "--cache", str(cache), "--no-open")
    out = capsys.readouterr().out
    html = (cache / "skill-map.html").read_text(encoding="utf-8")
    raw = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    return code, out, json.loads(raw)


def node(data: dict, node_id: str) -> dict:
    return next(n for n in data["nodes"] if n["id"] == node_id)


def extract(capsys, root: Path, cache: Path) -> None:
    default_fragments(cache)
    stamp(capsys, root, cache)


def touch_later(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))


def stale_names(capsys, root: Path, cache: Path) -> list[str]:
    return [line.split("\t")[0] for line in scan(capsys, root, cache)]


def test_scan_lists_every_skill_without_fragment(tmp_path, capsys):
    # SKILLMAP-1.1 SKILLMAP-3.4
    root, cache = make_tree(tmp_path)
    assert sorted(stale_names(capsys, root, cache)) == ["design-ext", "fix", "plan"]


def test_scan_skips_fresh_skill(tmp_path, capsys):
    # SKILLMAP-3.1
    root, cache = make_tree(tmp_path)
    extract(capsys, root, cache)
    render(capsys, root, cache)
    assert scan(capsys, root, cache) == ["none"]


def test_scan_lists_skill_whose_md_changed(tmp_path, capsys):
    # SKILLMAP-2.2
    root, cache = make_tree(tmp_path)
    extract(capsys, root, cache)
    touch_later(root / "skills/fix/reference/loop.md")
    assert stale_names(capsys, root, cache) == ["fix"]


def test_scan_skips_skill_whose_rebuild_spec_changed(tmp_path, capsys):
    # SKILLMAP-2.1
    root, cache = make_tree(tmp_path)
    extract(capsys, root, cache)
    render(capsys, root, cache)
    write(root / "skills/fix/SPEC.md", "rebuild spec")
    assert scan(capsys, root, cache) == ["none"]


def test_scan_lists_skill_whose_agent_file_changed(tmp_path, capsys):
    # SKILLMAP-3.2
    root, cache = make_tree(tmp_path)
    extract(capsys, root, cache)
    touch_later(root / "agents/fix-worker.md")
    assert stale_names(capsys, root, cache) == ["fix"]


def test_scan_keeps_skill_stale_when_agent_file_changes_during_extraction(tmp_path, capsys):
    # SKILLMAP-3.2
    root, cache = make_tree(tmp_path)
    extract(capsys, root, cache)
    touch_later(root / "skills/fix/reference/loop.md")
    lwt = next(line.split("\t")[1] for line in scan(capsys, root, cache) if line.startswith("fix\t"))
    agent = root / "agents/fix-worker.md"
    touch_later(agent)
    path = cache / "skills/fix.json"
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "lwt": lwt}), encoding="utf-8")
    later = agent.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(later, later))
    assert "fix" in stale_names(capsys, root, cache)


def test_first_extraction_of_skill_with_agents_is_fresh(tmp_path, capsys):
    # SKILLMAP-3.2
    root, cache = make_tree(tmp_path)
    lines = scan(capsys, root, cache)
    default_fragments(cache)
    for name, lwt, *_ in (line.split("\t") for line in lines):
        path = cache / "skills" / f"{name}.json"
        path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "lwt": lwt}), encoding="utf-8")
    code, out, _ = render(capsys, root, cache, stamped=False)
    assert (code, scan(capsys, root, cache)) == (0, ["none"])


def test_scan_relists_fragment_with_problems(tmp_path, capsys):
    # SKILLMAP-5.3
    root, cache = make_tree(tmp_path)
    extract(capsys, root, cache)
    plan = cache / "skills/plan.json"
    plan.write_text(json.dumps({**json.loads(plan.read_text(encoding="utf-8")), "calls": [{"skill": "nosuch"}]}),
                    encoding="utf-8")
    render(capsys, root, cache)
    assert stale_names(capsys, root, cache) == ["plan"]


def test_render_reports_malformed_fragment(tmp_path, capsys):
    # SKILLMAP-6.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", loads=[{"path": "x.md"}], agents=[{"type": "general-purpose"}])
    code, out, _ = render(capsys, root, cache)
    assert code == 1
    assert "problem: plan: load without md" in out and "problem: plan: agent without id" in out


def test_fragment_without_lwt_newer_than_its_files_gets_lwt(tmp_path, capsys):
    # SKILLMAP-5.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    code, out, _ = render(capsys, root, cache, stamped=False)
    lwt = json.loads((cache / "skills/fix.json").read_text(encoding="utf-8"))["lwt"]
    assert (code, lwt.split("@")[0], scan(capsys, root, cache)) == (0, skillmap.build_lwt(units.find_units(root)["fix"]), ["none"])


def test_fragment_without_lwt_older_than_its_md_stays_stale(tmp_path, capsys):
    # SKILLMAP-5.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    touch_later(root / "skills/fix/reference/loop.md")
    code, out, _ = render(capsys, root, cache, stamped=False)
    assert code == 1 and "problem: fix: changed since the map was drawn" in out
    assert "fix" in stale_names(capsys, root, cache)


def test_render_reports_wrong_field_types(tmp_path, capsys):
    # SKILLMAP-6.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", calls=[{"skill": "fix", "callArgs": ["a"], "args": "all"}],
             agents=[{"id": "w", "model": 5}])
    code, out, _ = render(capsys, root, cache)
    assert code == 1
    assert all(f"problem: plan: {text}" in out for text in ("callArgs not text", "args not a list of text", "model not text"))


def test_render_labels_skill_without_fragment_by_name(tmp_path, capsys):
    # SKILLMAP-7.3
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    (cache / "skills/plan.json").unlink()
    _, _, data = render(capsys, root, cache)
    assert node(data, "skill:plan")["label"] == "plan"


def test_scan_full_lists_fresh_skill(tmp_path, capsys):
    # SKILLMAP-3.3
    root, cache = make_tree(tmp_path)
    extract(capsys, root, cache)
    assert len(scan(capsys, root, cache, "--full")) == 3


def test_scan_drops_fragment_of_removed_skill(tmp_path, capsys):
    # SKILLMAP-4.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "deleted")
    scan(capsys, root, cache)
    assert not (cache / "skills/deleted.json").exists()


def test_render_marks_md_loaded_by_two_skills_shared(tmp_path, capsys):
    # SKILLMAP-8.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    _, _, data = render(capsys, root, cache)
    assert node(data, "md:reference/error-review.md")["shared"] is True
    assert node(data, "skill:design-ext")["shared"] is True


def test_render_lists_own_md_inside_skill_card(tmp_path, capsys):
    # SKILLMAP-8.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    _, _, data = render(capsys, root, cache)
    own = node(data, "skill:fix")["mds"]
    assert [(m["name"], m["args"]) for m in own] == [("reference/loop.md", ["all"])]
    assert not any(n["id"].endswith("loop.md") for n in data["nodes"])


def test_agent_start_ctx_sums_loaded_md_bytes(tmp_path, capsys):
    # SKILLMAP-9.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    _, _, data = render(capsys, root, cache)
    agent = node(data, "agent:fix:worker")
    assert agent["tok"] == (800 + 400 + 40) // 4
    assert agent["model"] == "opus:high"


def test_spawn_edge_carries_agent_args(tmp_path, capsys):
    # SKILLMAP-9.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    _, _, data = render(capsys, root, cache)
    spawn = next(e for e in data["edges"] if e["dst"] == "agent:fix:worker")
    assert spawn["kind"] == "spawn" and spawn["args"] == ["all"]


def test_agent_model_arg_shows_owner_arg_label(tmp_path, capsys):
    # SKILLMAP-9.3
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", args=[{"id": "model", "label": "model:effort"}],
             agents=[{"id": "finder", "model": "opus", "modelArg": "model"}])
    code, _, data = render(capsys, root, cache)
    assert code == 0 and node(data, "agent:plan:finder")["modelArg"] == "model:effort"


def test_agent_model_arg_without_owner_arg_is_problem(tmp_path, capsys):
    # SKILLMAP-9.4
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", agents=[{"id": "finder", "model": "opus", "modelArg": "model"}])
    code, out, _ = render(capsys, root, cache)
    assert code == 1 and "problem: plan: agent finder modelArg model is no arg" in out


def test_render_reports_unknown_md_path(tmp_path, capsys):
    # SKILLMAP-7.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", loads=[{"md": "reference/nope.md"}])
    code, out, _ = render(capsys, root, cache)
    assert code == 1
    assert "problem: plan: unknown md reference/nope.md" in out


def test_render_reports_skill_without_fragment(tmp_path, capsys):
    # SKILLMAP-5.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    (cache / "skills/plan.json").unlink()
    code, out, _ = render(capsys, root, cache)
    assert code == 1 and "problem: plan: no fragment" in out


def test_render_accepts_builtin_skill_call(tmp_path, capsys):
    # SKILLMAP-7.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", calls=[{"skill": "builtin:code-review"}], loads=[{"md": "project:CLAUDE.md"}])
    code, _, data = render(capsys, root, cache)
    builtin, project = node(data, "builtin:code-review"), node(data, "project:CLAUDE.md")
    assert (code, builtin["kind"], builtin["label"], project["label"]) == (0, "builtin", "/code-review", "CLAUDE.md")
    page = (cache / "skill-map.html").read_text(encoding="utf-8")
    assert ".k-builtin { --kind: var(--builtin); }" in page and '"builtin", "hook"' in page


def test_page_legend_kind_click_marks_cards(tmp_path, capsys):
    # SKILLMAP-13.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    render(capsys, root, cache)
    page = (cache / "skill-map.html").read_text(encoding="utf-8")
    kinds = ("k-command", "k-agent", "k-hook", "k-mod", "k-plugin", "k-shared", "k-md", "k-outside", "k-builtin", "k-mcp",
             "k-tool")
    places = [page.find(f'<button class="{k}" data-kind="{k}">') for k in kinds]
    assert -1 not in places and places == sorted(places)
    assert "card.classList.contains(button.dataset.kind)" in page and "highlightKind(b)" in page
    assert '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,' in page


def make_extras(root: Path, tmp: Path) -> None:
    """A script hook under an MCP matcher, a tool hook under two events, one mod and one enabled plugin."""
    write(root / "hooks/rules.py", "print('x')")
    write(root / "hooks/test_rules.py", "test")
    tool = "if command -v repowise-augment >/dev/null 2>&1; then exec repowise-augment; fi"
    hooks = {"PostToolUse": [{"matcher": "^mcp__codemap-mcp__.*", "hooks": [{"command": "python ~/.claude/hooks/rules.py"}]},
                             {"matcher": "Read", "hooks": [{"command": tool}]}],
             "SessionStart": [{"matcher": "startup", "hooks": [{"command": tool}]}]}
    write(root / "settings.json", json.dumps({"hooks": hooks, "enabledPlugins": {"ccm@market": True, "off@market": False}}))
    write(root / "mods/clr/.claude-plugin/plugin.json", "{}")
    write(root / "mods/clr/.claude-plugin/types/index.d.ts", "types")
    write(root / "mods/clr/hooks/register.tsx", "code")
    write(root / "mods/clr/clr.test.ts", "test")
    plugin = tmp / "plugin-ccm"
    write(plugin / "ccm.py", "code")
    write(plugin / "docs/notes.md", "docs")
    installed = {"ccm@market": [{"installPath": str(plugin)}], "off@market": [{"installPath": str(plugin)}]}
    write(root / "plugins/installed_plugins.json", json.dumps({"plugins": installed}))


def test_scan_lists_hook_mod_and_plugin_units(tmp_path, capsys):
    # SKILLMAP-18.1
    root, cache = make_tree(tmp_path)
    make_extras(root, tmp_path)
    lines = {line.split("\t")[0]: line.split("\t")[2:4] for line in scan(capsys, root, cache)}
    assert lines["hook-rules"] == ["rules.py", "hook"]
    assert lines["mod-clr"] == [".claude-plugin/plugin.json,hooks/register.tsx", "mod"]
    assert lines["plugin-ccm"] == ["ccm.py", "plugin"]
    assert "hook-repowise-augment" not in lines and "plugin-off" not in lines


def test_render_draws_hooks_mods_plugins_and_mcp(tmp_path, capsys):
    # SKILLMAP-18.2
    root, cache = make_tree(tmp_path)
    make_extras(root, tmp_path)
    default_fragments(cache)
    fragment(cache, "hook-rules", loads=[{"md": "~/.claude/reference/error-review.md"}])
    fragment(cache, "mod-clr", calls=[{"skill": "fix", "when": "typed"}])
    fragment(cache, "plugin-ccm", summary="session monitor")
    fragment(cache, "plan", calls=[{"skill": "mcp:lizard"}])
    code, _, data = render(capsys, root, cache)
    edges = {(e["src"], e["dst"]) for e in data["edges"]}
    hook, tool, mcp = node(data, "hook:rules"), node(data, "hook:repowise-augment"), node(data, "mcp:lizard")
    assert (code, hook["label"], hook["summary"], tool["summary"]) == (0, "rules.py", "PostToolUse", "PostToolUse · SessionStart")
    assert (node(data, "mod:clr")["kind"], node(data, "plugin:ccm")["label"], mcp["kind"], mcp["label"]) == ("mod", "ccm", "mcp", "lizard")
    assert {("hook:rules", "mcp:codemap-mcp"), ("mod:clr", "skill:fix"), ("skill:plan", "mcp:lizard")} <= edges
    x = lambda kinds: {n["x"] for n in data["nodes"] if n["kind"] in kinds}
    assert len(x(("hook", "mod", "plugin"))) == 1 and len(x(("mcp",))) == 1 and min(x(("command",))) == 0


def test_plugin_skill_is_its_own_command_card_linked_from_its_plugin(tmp_path, capsys):
    # SKILLMAP-18.5
    root, cache = make_tree(tmp_path)
    make_extras(root, tmp_path)
    plugin = tmp_path / "plugin-ccm"
    write(plugin / "skills/pane/SKILL.md", "pane skill")
    write(plugin / "skills/pane/reference/look.md", "look")
    write(plugin / "skills/pane/scripts/pane.py", "code")
    lines = {line.split("\t")[0]: line.split("\t") for line in scan(capsys, root, cache)}
    line = lines["ccm:pane"]
    assert lines["plugin-ccm"][2] == "ccm.py"
    assert line[2:4] == ["reference/look.md,SKILL.md", "skill"]
    assert line[5].endswith("/skills/ccm--pane.json")
    default_fragments(cache)
    for name in ("hook-rules", "mod-clr", "plugin-ccm"):
        fragment(cache, name)
    write(cache / "skills/ccm--pane.json", json.dumps({"skill": "ccm:pane", "kind": "command", "args": [], "loads": [],
                                                       "calls": [], "agents": []}))
    fragment(cache, "plan", calls=[{"skill": "ccm:pane"}])
    code, _, data = render(capsys, root, cache)
    edges = {(e["src"], e["dst"]) for e in data["edges"]}
    assert (code, node(data, "skill:ccm:pane")["label"]) == (0, "/ccm:pane")
    assert {("plugin:ccm", "skill:ccm:pane"), ("skill:plan", "skill:ccm:pane")} <= edges
    assert (cache / "skills/ccm--pane.json").is_file()


def test_render_lists_missing_hook_mod_plugin_and_mcp_targets(tmp_path, capsys):
    # SKILLMAP-18.3
    root, cache = make_tree(tmp_path)
    make_extras(root, tmp_path)
    settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
    settings["hooks"]["Stop"] = [{"hooks": [{"command": "python ~/.claude/hooks/gone.py"}, {"command": "python -V"}]}]
    settings["enabledPlugins"]["lost@market"] = True
    write(root / "settings.json", json.dumps(settings))
    write(root / "mods/clr/hooks/hooks.json", json.dumps({"modules": ["./register.tsx", "./gone.ts"]}))
    write(tmp_path / ".claude.json", json.dumps({"mcpServers": {"codemap-mcp": {}}, "projects": {"p": {"mcpServers": {"lizard": {}}}}}))
    default_fragments(cache)
    for name in ("hook-rules", "mod-clr", "plugin-ccm"):
        fragment(cache, name)
    fragment(cache, "plan", calls=[{"skill": "mcp:lizard"}, {"skill": "mcp:nope"}, {"skill": "mcp:claude_ai_Gmail"}])
    code, out, data = render(capsys, root, cache)
    missing = {(p["skill"], p["text"]): p for p in data["problems"] if "node" in p}
    assert set(missing) == {("hook-gone", "missing script ~/.claude/hooks/gone.py"),
                            ("hook-repowise-augment", "missing tool repowise-augment"),
                            ("mod-clr", "missing module ./gone.ts"), ("plugin-lost", "not installed"),
                            ("plan", "unknown mcp server nope")}
    assert missing[("plan", "unknown mcp server nope")]["node"] == "mcp:nope"
    assert missing[("plugin-lost", "not installed")]["node"] == "plugin:lost" and node(data, "plugin:lost")["kind"] == "plugin"
    assert code == 0 and "missing: mod-clr: missing module ./gone.ts" in out and "problem:" not in out
    assert "Fix these in my Claude Code setup (~/.claude)" in (cache / "skill-map.html").read_text(encoding="utf-8")


def test_render_lists_required_cli_tool_not_installed(tmp_path, capsys):
    # SKILLMAP-18.4
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", calls=[{"skill": "tool:python"}, {"skill": "tool:no-such-tool-x"},
                                   {"skill": "tool:no-such-tool-y", "when": "if installed"}])
    code, out, data = render(capsys, root, cache)
    missing = {(p["skill"], p["text"], p["node"]) for p in data["problems"] if "node" in p}
    tool = node(data, "tool:no-such-tool-y")
    assert missing == {("plan", "missing tool no-such-tool-x", "tool:no-such-tool-x")}
    assert (code, tool["kind"], tool["label"]) == (0, "tool", "no-such-tool-y")
    assert max(n["x"] for n in data["nodes"]) == node(data, "tool:python")["x"]


def test_layout_breaks_cycle_with_back_edge(tmp_path, capsys):
    # SKILLMAP-10.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    _, _, data = render(capsys, root, cache)
    calls = {(e["src"], e["dst"]): e for e in data["edges"] if e["kind"] == "call"}
    fix_plan, plan_fix = calls[("skill:fix", "skill:plan")], calls[("skill:plan", "skill:fix")]
    assert fix_plan["back"] is False and plan_fix["back"] is True
    assert node(data, "skill:plan")["x"] > node(data, "skill:fix")["x"]


def test_layout_puts_each_kind_in_its_own_band(tmp_path, capsys):
    # SKILLMAP-10.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", calls=[{"skill": "builtin:code-review"}])
    _, _, data = render(capsys, root, cache)
    xs = {n["kind"]: n["x"] for n in data["nodes"]}
    commands = [n["x"] for n in data["nodes"] if n["kind"] == "command"]
    assert max(commands) < xs["agent"] < xs["shared"] < xs["md"] < xs["builtin"]


def test_layout_keeps_commands_far_left_and_mcp_by_tools():
    # SKILLMAP-10.5
    kinds = {"c": "command", "a": "agent", "h": "hook", "m": "mod", "p": "plugin", "s": "shared", "b": "builtin",
             "x": "mcp", "y": "mcp", "t": "tool"}
    cards = {i: {"id": i, "kind": k, "mds": []} for i, k in kinds.items()}
    edges = [{"src": s, "dst": d, "back": False} for s, d in ("mc", "ca", "hs", "hx", "xy", "mp", "cb", "pt")]
    x = layout.build_layers(cards, edges)
    assert x["c"] < x["a"] < x["h"] == x["m"] == x["p"] < x["s"] < x["b"] < x["x"] == x["y"] < x["t"]


def stacked_cards(command_mds: int) -> dict[str, dict]:
    """Command `c` calls agent `a` and md `m`; `a` spawns shared `s`. Bands give columns c | a | s | m."""
    kinds = {"c": "command", "a": "agent", "s": "shared", "m": "md"}
    cards = {i: {"id": i, "kind": k, "mds": []} for i, k in kinds.items()}
    cards["c"]["mds"] = [{}] * command_mds
    edges = [{"src": s, "dst": d} for s, d in ("ca", "as", "cm")]
    layout.apply_layout({"nodes": list(cards.values()), "edges": edges})
    return cards


def test_layout_stacks_a_far_column_under_a_near_one_within_tallest_height():
    # SKILLMAP-10.6
    x = {i: c["x"] for i, c in stacked_cards(10).items()}
    assert x["c"] == 0 and x["m"] == x["a"] < x["s"] and len(set(x.values())) == 3
    x = {i: c["x"] for i, c in stacked_cards(0).items()}
    assert len(set(x.values())) == 4


def test_layout_moves_a_card_out_of_its_band_column_when_an_edge_runs_back():
    # SKILLMAP-10.7
    kinds = {"c": "command", "r": "command", "s": "shared", "a1": "agent", "a2": "agent", "a3": "agent"}
    cards = {i: {"id": i, "kind": k, "mds": []} for i, k in kinds.items()}
    links = [("c", "a1"), ("a1", "s")]
    columns = layout.place_cards([[["c"]], [["r"]], [["s"]], [["a1", "a2", "a3"]]], cards,
                                 [{"src": s, "dst": d} for s, d in links])
    assert columns == [[["c"]], [["r", "a1"]], [["s"]], [["a2", "a3"]]]


def test_layout_place_cards_move_gain_equals_full_rescore():
    kinds = {"c": "command", "a1": "agent", "a2": "agent", "s1": "shared", "s2": "shared", "s3": "shared",
             "m1": "md", "m2": "md"}
    cards = {i: {"id": i, "kind": k, "mds": []} for i, k in kinds.items()}
    cards["c"]["mds"] = [{}] * 6
    # m1 sits alone, so its moves empty a column; s1, s2 share a column in two blocks; a1 -> s1 twice
    columns = [[["c"]], [["a1", "a2"]], [["s1"], ["s2"]], [["m1"]], [["s3", "m2"]]]
    links = [("c", "a1"), ("a1", "s1"), ("a1", "s1"), ("a2", "s3"), ("s1", "m1"), ("m2", "s2"), ("c", "m2")]
    limit = max(layout.get_stack_height(c, cards) for c in columns)
    band = {i: layout.get_band(n) for i, n in cards.items()}
    score = lambda cols: (layout.get_flow_cost(cols, links, layout.PASS_COST)
                          - layout.COHESION_GAIN * layout.get_cohesion(cols, band))
    scorer = layout.MoveScorer(columns, cards, links, limit)
    allowed = 0
    for node_id in kinds:
        for target in range(len(columns)):
            trial = layout.move_card(columns, node_id, target, links)
            home = trial and next(c for c in trial if any(node_id in block for block in c))
            too_tall = trial is not None and layout.get_stack_height(home, cards) > limit
            expected = None if trial is None or too_tall else score(trial) - score(columns)
            gain = scorer.get_gain(node_id, target)
            assert gain == (None if expected is None else pytest.approx(expected)), (node_id, target)
            allowed += expected is not None
    assert 0 < allowed < len(kinds) * (len(columns) - 1)


def test_layout_place_cards_tie_goes_to_first_move_when_one_empties_a_column():
    # n0 leaving its lone column scores whole (float noise), n8 to column 0 by change: both gain -10
    kinds = {"n0": "tool", "n1": "shared", "n4": "tool", "n5": "skill", "n7": "skill", "n8": "tool", "n9": "skill",
             "n10": "hook", "n11": "tool", "n12": "shared", "n13": "hook", "n2": "command", "n3": "command",
             "n6": "hook"}
    mds = {"n0": 3, "n1": 1, "n2": 1, "n3": 3, "n5": 3, "n6": 1, "n7": 3, "n8": 1, "n9": 3, "n10": 2, "n11": 3,
           "n13": 1}
    cards = {i: {"id": i, "kind": k, "mds": [{}] * mds.get(i, 0)} for i, k in kinds.items()}
    columns = [[["n0"]], [["n11"]], [["n7"], ["n12", "n1", "n5"]], [["n4"]], [["n2", "n9"], ["n13"]],
               [["n3", "n6"], ["n8", "n10"]]]
    # place_cards keeps the limit of its start layout; this is the start layout two moves before `columns`
    limit = max(layout.get_stack_height(c, cards) for c in [[["n0"]], [["n5", "n11"]], [["n7"], ["n12"]],
                                                            [["n1", "n4"]], [["n2", "n9"], ["n13"]],
                                                            [["n3", "n6"], ["n8", "n10"]]])
    scorer = layout.MoveScorer(columns, cards, [], limit)
    assert scorer.get_gain("n0", 1) == scorer.get_gain("n8", 0) == -10
    assert scorer.get_best_move(sorted(i for i, k in kinds.items() if k != "command")) == ("n0", 1)


def test_layout_pulls_linked_cards_level_and_keeps_column_gaps():
    # SKILLMAP-10.3
    cards = {i: {"id": i, "kind": "skill", "mds": []} for i in "abcd"}
    data = {"nodes": list(cards.values()), "edges": [{"src": "c", "dst": "d", "kind": "call"}]}
    layout.apply_layout(data)
    assert cards["d"]["x"] > cards["c"]["x"] and cards["d"]["y"] == cards["c"]["y"]
    column = sorted((cards[i]["y"] for i in "abc"))
    assert [b - a for a, b in zip(column, column[1:])] == [64 + layout.ROW_GAP] * 2
    assert min(n["y"] for n in cards.values()) == 0


def test_layout_lets_rubber_bands_reorder_a_column():
    # SKILLMAP-10.4
    cards = {i: {"id": i, "kind": "skill", "mds": []} for i in "abcd"}
    columns = [[["a", "b"]], [["c", "d"]]]
    for x, blocks in enumerate(columns):
        layout.set_column_positions(x, [cards[i] for i in blocks[0]])
    edges = [{"src": "a", "dst": "d"}, {"src": "b", "dst": "c"}]
    layout.pull_linked_cards(columns, cards, layout.get_links(edges))
    y = {i: c["y"] for i, c in cards.items()}
    assert (y["a"] < y["b"]) == (y["d"] < y["c"]) and (y["d"], y["c"]) == (y["a"], y["b"])


def test_layout_polish_puts_cards_with_a_shared_caller_next_to_each_other():
    # SKILLMAP-10.8
    cards = {i: {"id": i, "kind": "agent", "mds": []} for i in ("p", "q", "a1", "b1", "a2", "b2")}
    columns = [[["p", "q"]], [["a1", "b1", "a2", "b2"]]]
    for x, blocks in enumerate(columns):
        layout.set_column_positions(x, [cards[i] for i in blocks[0]])
    edges = [{"src": s, "dst": d} for s, d in (("p", "a1"), ("p", "a2"), ("q", "b1"), ("q", "b2"))]
    layout.improve_columns(columns, cards, edges, usage.get_edge_usage(cards, edges))
    order = "".join(i[0] for i in columns[1][0])
    ys = sorted(cards[i]["y"] for i in columns[1][0])
    assert order in ("aabb", "bbaa")
    assert [b - a for a, b in zip(ys, ys[1:])] == [layout.get_card_height(cards["a1"]) + layout.ROW_GAP] * 3


def test_layout_polish_puts_the_most_used_card_level_with_its_caller():
    # SKILLMAP-10.9
    cards = {"c": {"id": "c", "kind": "command", "mds": [], "args": []},
             "s": {"id": "s", "kind": "shared", "mds": [], "args": [{"id": "max"}]}}
    cards |= {i: {"id": i, "kind": "agent", "mds": []} for i in ("w", "f")}
    columns = [[["c"]], [["s"]], [["w", "f"]]]
    for x, blocks in enumerate(columns):
        layout.set_column_positions(x, [cards[i] for i in blocks[0]])
    edges = [{"src": "c", "dst": "s", "kind": "call", "callArgs": "opus"},
             {"src": "s", "dst": "w", "kind": "spawn", "args": ["max"]},
             {"src": "s", "dst": "f", "kind": "spawn"}]
    assert usage.get_edge_usage(cards, edges) == [1, 0, 1]
    layout.improve_columns(columns, cards, edges, usage.get_edge_usage(cards, edges))
    assert columns[2] == [["f", "w"]] and cards["f"]["y"] == cards["s"]["y"]
    assert cards["w"]["y"] == cards["f"]["y"] + layout.get_card_height(cards["f"]) + layout.ROW_GAP


def test_layout_puts_a_card_with_a_single_caller_level_with_it_past_a_filler_card():
    # SKILLMAP-10.11
    cards = {i: {"id": i, "kind": "skill", "mds": []} for i in ("r", "q", "x", "c", "f1", "f2", "s", "a")}
    cards["x"]["mds"] = [{}] * 5
    links = (("r", "x"), ("q", "x"), ("r", "c"), ("x", "f1"), ("f1", "f2"), ("c", "s"), ("s", "a"))
    layout.apply_layout({"nodes": list(cards.values()), "edges": [{"src": s, "dst": d} for s, d in links]})
    y = {i: c["y"] for i, c in cards.items()}
    assert y["x"] < y["c"] and y["f1"] < y["s"] and y["f2"] < y["a"]
    assert y["s"] == y["c"] and y["a"] == y["s"]


def count_crossings(cards: dict[str, dict], edges: list[dict]) -> int:
    """Two edges with four distinct cards cross when their ends sit in opposite order."""
    pairs = [(e, f) for k, e in enumerate(edges) for f in edges[k + 1:]
             if len({e["src"], e["dst"], f["src"], f["dst"]}) == 4]
    return sum((cards[e["src"]]["y"] - cards[f["src"]]["y"]) * (cards[e["dst"]]["y"] - cards[f["dst"]]["y"]) < 0
               for e, f in pairs)


def test_layout_polish_uncrosses_edges_between_neighbour_columns():
    # SKILLMAP-10.10
    cards = {i: {"id": i, "kind": "skill", "mds": []} for i in ("p", "q", "r", "a", "b")}
    cards["r"]["mds"] = [{}] * 3
    columns = [[["p", "q", "r"]], [["a", "b"]]]
    for x, blocks in enumerate(columns):
        layout.set_column_positions(x, [cards[i] for i in blocks[0]])
    edges = [{"src": s, "dst": d} for s, d in (("p", "a"), ("q", "b"), ("r", "a"), ("r", "b"))]
    layout.improve_columns(columns, cards, edges, usage.get_edge_usage(cards, edges))
    assert count_crossings(cards, edges) == 0


def test_layout_polish_counts_only_crossings_into_a_neighbour_column_with_four_cards():
    # SKILLMAP-10.10
    xs = {"l1": 0, "l2": 0, "m1": 1, "m2": 1, "r1": 2, "f1": 3, "f2": 3}
    cards = {i: {"id": i, "kind": "skill", "mds": [], "x": x * layout.COLUMN_WIDTH, "y": i.endswith("2") * 100}
             for i, x in xs.items()}
    links = (("m1", "l2"), ("m2", "l1"), ("m1", "r1"), ("m2", "r1"), ("m1", "f2"), ("m2", "f1"))
    weights: dict[str, dict[str, int]] = {}
    for a, b in links:
        weights.setdefault(a, {})[b] = weights.setdefault(b, {})[a] = 1
    scorer = layout.ColumnScorer([["m1", "m2"]], cards, weights, {})
    assert scorer.crossings == {("m1", "m2"): 2 * layout.CROSSING_COST}


def test_layout_packed_level_card_sits_exactly_on_its_caller_y():
    # SKILLMAP-10.9
    heights, wanted = [154, 82, 136], -28.01010816680211
    ys = layout.get_packed_ys(heights, layout.fill_targets([wanted, None, None], heights), [0, -1, -1])
    assert ys[0] == wanted
    rng = random.Random(1)  # a wanted card with fillers above it is as exact
    for _ in range(2000):
        heights, wanted = [rng.randint(40, 200) for _ in range(3)], rng.uniform(-300, 300)
        ys = layout.get_packed_ys(heights, layout.fill_targets([None, None, wanted], heights), [-1, -1, 0])
        assert ys[2] == wanted


def test_layout_packed_block_sits_on_its_highest_ranked_card():
    # SKILLMAP-10.12
    assert layout.get_packed_ys([80, 80], [0, 10], [0, 1]) == [-78, 10]
    assert layout.get_packed_ys([80, 80], [0, 10], [1, 0]) == [0, 88]
    assert layout.get_packed_ys([80, 80], [0, 10], [1, 1]) == [-39, 49]
    assert layout.get_packed_ys([80, 80, 80], [0, 100, 30], [0, 0, 5]) == [-146, -58, 30]
    rng = random.Random(2)  # a pinned card below the block's first card lands exactly on a float target
    for _ in range(2000):
        n, wanted = rng.randint(2, 4), rng.uniform(-300, 300)
        ys = layout.get_packed_ys([rng.randint(40, 200) for _ in range(n)], [wanted] * n, [0] * (n - 1) + [1])
        assert ys[-1] == wanted


def test_layout_ranks_a_single_caller_card_above_a_more_used_median_card_above_a_card_with_no_target():
    # SKILLMAP-10.12
    cards = {i: {"id": i, "kind": "skill", "mds": [], "x": 0, "y": 0} for i in ("p", "q", "r")}
    cards |= {i: {"id": i, "kind": "skill", "mds": [], "x": layout.COLUMN_WIDTH, "y": 0} for i in ("a", "m", "f")}
    weights = {"p": {"a": 2, "f": 20}, "a": {"p": 2}, "f": {"p": 20}, "q": {"m": 5}, "r": {"m": 5}, "m": {"q": 5, "r": 5}}
    scorer = layout.ColumnScorer([["a", "m", "f"]], cards, weights, {"a": {"p"}, "f": {"p"}, "m": {"q", "r"}})
    ids = ["a", "m", "f"]
    ranks = scorer.get_ranks(ids, scorer.get_targets(ids))
    assert ranks[0] > ranks[1] > ranks[2] == -1


def test_layout_polish_ends_with_single_caller_cards_level_with_their_callers_final_y(monkeypatch):
    # SKILLMAP-10.12
    cards = {i: {"id": i, "kind": "skill", "mds": []} for i in "epa"}
    columns = [[["e"]], [["p"]], [["a"]]]
    for x, blocks in enumerate(columns):
        layout.set_column_positions(x, [cards[i] for i in blocks[0]])

    def move_callers(columns, scorers):
        cards["e"]["y"] += 30.5
        cards["p"]["y"] += 30.5

    monkeypatch.setattr(layout, "sweep_columns", move_callers)
    layout.improve_columns(columns, cards, [{"src": "e", "dst": "p"}, {"src": "p", "dst": "a"}], [0, 0])
    assert cards["a"]["y"] == cards["p"]["y"] == cards["e"]["y"] == 30.5


@pytest.mark.parametrize("use_a, use_b, level", [(1, 3, "b"), (3, 1, "a")])
def test_layout_polish_leaves_the_more_used_of_two_colliding_single_caller_cards_level(use_a, use_b, level):
    # SKILLMAP-10.12
    cards = {"p": {"id": "p", "kind": "skill", "mds": [], "x": 0, "y": 0},
             "q": {"id": "q", "kind": "skill", "mds": [], "x": 0, "y": 40}}
    cards |= {i: {"id": i, "kind": "skill", "mds": [{}] * 4, "x": layout.COLUMN_WIDTH, "y": 0} for i in "ab"}
    weights = {"p": {"a": use_a}, "a": {"p": use_a}, "q": {"b": use_b}, "b": {"q": use_b}}
    blocks = [["a", "b"]]
    layout.improve_column(blocks, layout.ColumnScorer(blocks, cards, weights, {"a": {"p"}, "b": {"q"}}))
    caller = {"a": "p", "b": "q"}[level]
    assert layout.get_card_height(cards["a"]) == 136 and blocks == [["a", "b"]]
    assert cards[level]["y"] == cards[caller]["y"] and cards["b"]["y"] - cards["a"]["y"] == 136 + layout.ROW_GAP


def test_layout_gives_an_edge_that_skips_columns_a_lane_in_each_passed_column_shared_per_source():
    # SKILLMAP-10.13
    cards = {i: {"id": i, "kind": "skill", "mds": [{}] * (len(i) - 1)} for i in ("s", "a", "aa", "b", "bbb", "c", "e")}
    cards["s"]["kind"] = "command"
    calls = [("s", "a"), ("s", "aa"), ("a", "b"), ("aa", "bbb"), ("b", "c"), ("b", "e"), ("s", "c"), ("s", "e")]
    edges = [{"src": s, "dst": d, "kind": "call"} for s, d in calls] + [{"src": "c", "dst": "s", "kind": "call"}]
    data = {"nodes": list(cards.values()), "edges": edges}
    layout.apply_layout(data)
    lanes = {(e["src"], e["dst"]): e.get("lanes") for e in edges}
    assert [cards[i]["x"] // layout.COLUMN_WIDTH for i in ("s", "a", "b", "c", "e")] == [0, 1, 2, 3, 3]
    assert len(lanes["s", "c"]) == 2 and lanes["s", "e"] == lanes["s", "c"]
    assert lanes["s", "a"] is None and lanes["b", "c"] is None and lanes["c", "s"] is None  # one column apart, loop back
    for k, top in enumerate(lanes["s", "c"]):
        line = top + layout.LANE_HEIGHT  # the page line runs 18 px below the lane top, like an edge into a card
        passed = [n for n in cards.values() if n["x"] == (k + 1) * layout.COLUMN_WIDTH]
        assert len(passed) == 2 and all(
            line <= n["y"] - layout.ROW_GAP or line >= n["y"] + layout.get_card_height(n) + layout.ROW_GAP for n in passed)
    assert data["nodes"] == list(cards.values()) and len(cards) == 7
    assert min([n["y"] for n in cards.values()] + lanes["s", "c"]) == 0


def test_layout_lane_joins_the_nearest_block_of_its_column_and_the_first_on_a_tie():
    # SKILLMAP-10.13
    nodes = {i: {"id": i, "kind": "skill", "mds": [], "x": 0, "y": y} for i, y in (("a", 0), ("b", 200))}
    for y, block in ((150, 1), (132, 0), (30, 0)):  # distances 50 and 86; 68 and 68; 0 inside the first block
        blocks = [["a"], ["b"]]
        layout.add_lane(blocks, nodes, "lane", y)
        assert blocks[block][-1] == "lane" and nodes["lane"]["kind"] == layout.LANE_KIND


def test_layout_keeps_a_direct_child_level_with_its_source_when_a_lane_of_that_source_shares_the_column():
    # SKILLMAP-10.14
    cards = {i: {"id": i, "kind": "skill", "mds": []} for i in ("s", "a", "x0")}
    cards["s"]["kind"] = "command"
    edges = [{"src": s, "dst": d, "kind": "call"} for s, d in (("s", "a"), ("a", "x0"), ("s", "x0"))]
    layout.apply_layout({"nodes": list(cards.values()), "edges": edges})
    assert edges[2]["lanes"] and cards["a"]["y"] == cards["s"]["y"]


@pytest.mark.parametrize("ids, wanted", [(["lane", "a"], [None, 0]), (["a", "lane"], [0, None]), (["lane"], [0])])
def test_layout_gives_the_level_target_to_a_real_card_before_a_lane_of_the_same_caller(ids, wanted):
    # SKILLMAP-10.14
    cards = {"s": {"id": "s", "kind": "command", "mds": [], "x": 0, "y": 0}, "a": {"id": "a", "kind": "skill", "mds": [],
             "x": layout.COLUMN_WIDTH, "y": 30}, "lane": {"id": "lane", "kind": layout.LANE_KIND, "mds": [],
                                                  "x": layout.COLUMN_WIDTH, "y": 0}}
    scorer = layout.ColumnScorer([ids], cards, {i: {"s": 1} for i in ids}, {i: {"s"} for i in ids})
    assert scorer.get_targets(ids) == wanted


@pytest.mark.parametrize("p_also_calls_u", [False, True])
def test_layout_edges_into_one_target_share_a_lane_where_each_is_alone_in_its_source_lane(p_also_calls_u):
    # SKILLMAP-10.15
    cards = {i: {"id": i, "kind": "command" if i in "pq" else "skill", "mds": []} for i in ("p", "q", "m", "t", "u")}
    calls = [("p", "m"), ("m", "t"), ("m", "u"), ("p", "t"), ("q", "t")] + [("p", "u")] * p_also_calls_u
    edges = [{"src": s, "dst": d, "kind": "call"} for s, d in calls]
    layout.apply_layout({"nodes": list(cards.values()), "edges": edges})
    lanes = {(e["src"], e["dst"]): e.get("lanes") for e in edges}
    assert [cards[i]["x"] // layout.COLUMN_WIDTH for i in ("p", "q", "m", "t", "u")] == [0, 0, 1, 2, 2]
    if p_also_calls_u:  # source sharing wins: p's two edges keep one lane, q's edge has its own
        assert lanes["p", "t"] == lanes["p", "u"] and lanes["q", "t"] != lanes["p", "t"]
    else:
        assert len(lanes["p", "t"]) == 1 and lanes["q", "t"] == lanes["p", "t"]


# Stub DOM for the page script: a card is 300 wide (`.card` CSS) and 40 high; offsetTop and offsetLeft follow style.
PAGE_STUB = """
const any = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => 0 : any, apply: () => any });
class El {
  constructor(tag) { this.tag = tag; this.style = {}; this.attrs = {}; this.children = []; this.dataset = {}; }
  get classList() { return any; }
  get offsetTop() { return parseFloat(this.style.top) || 0; }
  get offsetLeft() { return parseFloat(this.style.left) || 0; }
  get offsetWidth() { return 300; }
  get offsetHeight() { return 40; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren() { this.children = []; }
  querySelectorAll() { return []; }
  addEventListener() {}
  getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; }
}
const byId = new Map();
globalThis.document = {
  getElementById: id => id === "data" ? { textContent: DATA } : byId.get(id) || byId.set(id, new El(id)).get(id),
  createElement: tag => new El(tag), createElementNS: (ns, tag) => new El(tag),
  body: new El("body"), documentElement: new El("html"), querySelectorAll: () => [],
};
Object.assign(globalThis, { getComputedStyle: () => ({ getPropertyValue: () => "" }), addEventListener() {},
  innerWidth: 1000, innerHeight: 800 });
"""
PAGE_DUMP = """
const svg = byId.get("edges").children;
console.log(JSON.stringify({ tops: byId.get("world").children.map(c => c.style.top),
  paths: svg.filter(c => c.tag === "path").map(c => c.attrs.d),
  labels: svg.filter(c => c.tag === "text").map(c => [c.attrs.x, c.attrs.y]) }));
"""


def run_page(nodes: list[dict], edges: list[dict]) -> dict:
    """Runs the page script in node on a stub DOM; returns card tops, path `d` values and label x, y per edge."""
    nodes = [{"label": n["id"], "kind": "skill", "mds": [], "args": [], "summary": "", "tok": 0, "hints": [], **n}
             for n in nodes]
    edges = [{"id": f"{e['src']}>{e['dst']}", "kind": "call", **e} for e in edges]
    data = {"nodes": nodes, "edges": edges, "problems": [], "cost": {"agentBase": 1, "msPerTok": 1}}
    script = skillmap.TEMPLATE.read_text(encoding="utf-8").split("<script>")[-1].split("</script>")[0]
    source = f"const DATA = {json.dumps(json.dumps(data))};{PAGE_STUB}{script}{PAGE_DUMP}"
    run = subprocess.run(["node", "-"], input=source, capture_output=True, text=True, encoding="utf-8", check=False)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@needs_node
def test_page_lane_slot_is_shared_per_x_and_y_and_moves_below_a_card_with_every_edge_that_uses_it():
    # SKILLMAP-12.3
    w = layout.COLUMN_WIDTH
    nodes = [{"id": "s", "x": 0, "y": 0}, {"id": "q", "x": 0, "y": 200}, {"id": "c", "x": w, "y": 0},
             {"id": "t1", "x": 2 * w, "y": 0}, {"id": "t2", "x": 2 * w, "y": 100}]
    edges = [{"src": "s", "dst": "t1", "lanes": [10]}, {"src": "s", "dst": "t2", "lanes": [10]},
             {"src": "q", "dst": "t1", "lanes": [60]}]
    page = run_page(nodes, edges)
    lines = [re.search(r"C[^L]* L([\d.]+),([\d.]+)", d).groups() for d in page["paths"]]  # past any stub
    # slot 10 moves 8 below card c (0 to 40), slot 60 moves 8 below that slot (48 to 66); each line runs 18 below its slot
    assert lines == [(str(w + 300), "66"), (str(w + 300), "66"), (str(w + 300), "92")]
    assert page["tops"] == ["0px", "200px", "0px", "0px", "100px"]


@needs_node
def test_page_lane_path_curves_into_each_lane_line_runs_across_the_column_and_curves_into_the_target():
    # SKILLMAP-12.4
    w = layout.COLUMN_WIDTH
    nodes = [{"id": "s", "x": 0, "y": 0}, {"id": "t", "x": 3 * w, "y": 200}]
    page = run_page(nodes, [{"src": "s", "dst": "t", "lanes": [100, 150]}])
    assert page["paths"] == [f"M300,18 C340,18 340,118 {w},118 L{w + 300},118 C{w + 340},118 {w + 340},168 {2 * w},168"
                             f" L{2 * w + 300},168 C{2 * w + 340},168 {2 * w + 340},218 {3 * w},218"]
    assert page["labels"] == [[w + 150, 114]]  # middle lane: index (2 - 1) // 2 = 0, 4 above its line


@needs_node
def test_page_edge_runs_a_20_px_stub_out_of_a_card_with_2_out_edges_and_into_a_card_with_2_in_edges():
    # SKILLMAP-12.5
    w = layout.COLUMN_WIDTH
    nodes = [{"id": "s", "x": 0, "y": 0}, {"id": "q", "x": 0, "y": 100}, {"id": "t1", "x": w, "y": 0},
             {"id": "t2", "x": w, "y": 100}, {"id": "t3", "x": 2 * w, "y": 0}]
    edges = [{"src": "s", "dst": "t1"}, {"src": "s", "dst": "t2"}, {"src": "q", "dst": "t1"},
             {"src": "s", "dst": "t3", "lanes": [50]}]
    page = run_page(nodes, edges)
    assert page["paths"] == [
        f"M300,18 L320,18 C360,18 {w - 60},18 {w - 20},18 L{w},18",  # 3 out and 2 in: stub at both ends
        f"M300,18 L320,18 C360,18 {w - 40},118 {w},118",  # 3 out, 1 in: stub at the start only
        f"M300,118 C340,118 {w - 60},18 {w - 20},18 L{w},18",  # 1 out, 2 in: stub at the end only
        f"M300,18 L320,18 C360,18 {w - 40},68 {w},68 L{w + 300},68 C{w + 340},68 {2 * w - 40},18 {2 * w},18"]


@needs_node
def test_page_self_edge_counts_for_no_stub_and_a_loop_path_holds_no_stub():
    # SKILLMAP-12.5
    w = layout.COLUMN_WIDTH
    nodes = [{"id": "s", "x": 0, "y": 0}, {"id": "t", "x": w, "y": 0}, {"id": "u", "x": w, "y": 100},
             {"id": "p", "x": 0, "y": 200}, {"id": "v", "x": 2 * w, "y": 0}]
    one_out = run_page(nodes[:2], [{"src": "s", "dst": "s"}, {"src": "s", "dst": "t"}])
    assert one_out["paths"][1] == f"M300,18 C340,18 {w - 40},18 {w},18"  # self edge is no second out edge: no stub
    loop = run_page(nodes, [{"src": "s", "dst": "t"}, {"src": "s", "dst": "u"}, {"src": "t", "dst": "p"},
                                  {"src": "t", "dst": "v"}])
    # t has 2 out edges, yet its loop to p runs no stub
    assert loop["paths"][2] == f"M{w + 300},18 C{w + 340},18 {w + 340},280 {w + 300},280 L0,280 C-40,280 -40,218 0,218"
    assert loop["paths"][0].startswith("M300,18 L320,18 ")  # the two real out edges of s keep their stub


def test_layout_fill_targets_stacks_cards_without_a_target_up_from_the_first_wanted_card():
    # SKILLMAP-10.9
    assert layout.fill_targets([None, None, 50.0, None], [10, 20, 30, 5]) == [
        50.0 - 20 - 10 - 2 * layout.ROW_GAP, 50.0 - 20 - layout.ROW_GAP, 50.0, 50.0 + 30 + layout.ROW_GAP]


def test_layout_polish_stops_when_column_orders_repeat_before_the_sweep_cap(monkeypatch):
    # SKILLMAP-10.10
    columns, calls = [[["a", "b"]]], []

    def flip(blocks, scorer):
        calls.append(1)
        blocks[0].reverse()
        return True

    monkeypatch.setattr(layout, "improve_column", flip)
    layout.sweep_columns(columns, [None])
    assert len(calls) == 3 < layout.POLISH_PASSES


def test_agent_runs_come_from_count_and_many_runs_get_batch_hint(tmp_path, capsys):
    # SKILLMAP-16.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    _, out, _ = render(capsys, root, cache)
    for key in unchecked_keys(out):
        run("verdict", key, "ok", "--root", str(root), "--cache", str(cache))
    _, _, data = render(capsys, root, cache)
    agent = node(data, "agent:fix:worker")
    assert (agent["runs"], [h["save"] for h in agent["hints"]]) == (5, [2 * (48_000 + 310)])
    assert data["cost"] == {"agentBase": 48_000, "msPerTok": 2}


def unchecked_keys(out: str) -> list[str]:
    return [line.split("\t")[0].removeprefix("unchecked hint: ") for line in out.splitlines()
            if line.startswith("unchecked hint: ")]


def test_hint_shows_only_after_verifier_confirms_it(tmp_path, capsys):
    # SKILLMAP-17.1
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    _, out, data = render(capsys, root, cache)
    keys = unchecked_keys(out)
    assert node(data, "agent:fix:worker")["hints"] == [] and len(keys) == 1
    assert "\tfix\tIn skill `fix`, agent `worker` starts 5 times" in out
    run("verdict", keys[0], "wrong", "count is a cap, not starts", "--root", str(root), "--cache", str(cache))
    _, out, data = render(capsys, root, cache)
    assert (node(data, "agent:fix:worker")["hints"], unchecked_keys(out)) == ([], [])
    run("verdict", keys[0], "ok", "--root", str(root), "--cache", str(cache))
    _, out, data = render(capsys, root, cache)
    assert (len(node(data, "agent:fix:worker")["hints"]), unchecked_keys(out)) == (1, [])


def test_verdict_of_hint_no_longer_made_is_dropped(tmp_path, capsys):
    # SKILLMAP-17.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    run("verdict", "abc123abc123", "ok", "--root", str(root), "--cache", str(cache))
    render(capsys, root, cache)
    assert json.loads((cache / "verdicts.json").read_text(encoding="utf-8")) == {}


def test_single_agent_run_gets_no_batch_hint():
    # SKILLMAP-16.1
    agent = {"id": "agent:fix:worker", "label": "worker", "kind": "agent", "count": "", "tok": 100, "mds": []}
    cost.apply_cost({"nodes": [agent]})
    assert (agent["runs"], agent["hints"]) == (1, [])


def test_agent_that_takes_several_items_or_unknown_items_gets_no_batch_hint():
    # SKILLMAP-16.1
    agents = [{"id": "agent:fix:worker", "label": "worker", "kind": "agent", "count": "<=5", "items": items, "tok": 100, "mds": []}
              for items in ("2-4", "≤4 per batch", "")]
    cost.apply_cost({"nodes": agents})
    assert [(a["runs"], a["hints"]) for a in agents] == [(5, [])] * 3


def test_number_after_count_text_is_no_run_count():
    # SKILLMAP-16.1
    assert [cost.parse_runs(c) for c in ("per edit unit >100 lines", "up to 5 at once", "≤3 (max 10)", "1 per 4 batches")] == [1, 5, 3, 1]


def test_big_skill_md_and_big_agent_ctx_get_hints():
    # SKILLMAP-16.2
    skill = {"id": "skill:fix", "kind": "command", "tok": 3_500, "mds": []}
    small = {"id": "skill:todo-ext", "kind": "shared", "tok": 2_000, "mds": []}
    agent = {"id": "agent:fix:worker", "label": "worker", "kind": "agent", "count": "3", "items": "1", "tok": 6_000, "mds": []}
    cost.apply_cost({"nodes": [skill, small, agent]})
    saves = [[h["save"] for h in n["hints"]] for n in (skill, small, agent)]
    assert saves == [[2_500], [], [3 * 54_000 - 2 * 54_000, 3 * 4_000]]
    assert [h["prompt"] for h in agent["hints"]] == [
        "In skill `fix`, agent `worker` starts 3 times at ~54.0k tok each. Give each agent 2 items so it starts 2 times, "
        "with the same result.",
        "In skill `fix`, agent `worker` reads ~6.0k tok of md at start. Brief it with a digest of what it needs, not whole md files."]
    assert skill["hints"][0]["prompt"].startswith("~/.claude/skills/fix/SKILL.md is ~3.5k tok and read on every run of `fix`.")


def test_hint_saving_under_2k_tok_is_omitted():
    # SKILLMAP-16.5
    under = {"id": "skill:fix", "kind": "command", "tok": 2_999, "mds": []}
    at = {"id": "skill:plan", "kind": "command", "tok": 3_000, "mds": []}
    mds = [{"name": "a.md", "when": "", "args": [], "tok": 1_999}, {"name": "b.md", "when": "", "args": [], "tok": 2_000}]
    agent = {"id": "agent:fix:worker", "label": "worker", "kind": "agent", "count": "", "tok": 10, "mds": mds}
    cost.apply_cost({"nodes": [under, at, agent]})
    saves = [[h["save"] for h in n["hints"]] for n in (under, at, agent, *mds)]
    assert saves == [[], [2_000], [], [], [2_000]]


def test_own_md_read_on_every_run_gets_hint_unless_conditional():
    # SKILLMAP-16.3
    mds = [{"name": "a.md", "when": "", "args": [], "tok": 2_000}, {"name": "b.md", "when": "loop", "args": [], "tok": 2_000},
           {"name": "c.md", "when": "", "args": ["all"], "tok": 2_000}, {"name": "d.md", "when": "", "args": [], "tok": 1_500}]
    cost.apply_cost({"nodes": [{"id": "agent:fix:worker", "label": "worker", "kind": "agent", "count": "", "tok": 10, "mds": mds}]})
    assert [[h["save"] for h in md["hints"]] for md in mds] == [[2_000], [], [], []]
    assert mds[0]["hints"][0]["prompt"].startswith("~/.claude/skills/fix/a.md (~2.0k tok) is read on every run of `fix`.")


def test_page_problem_holds_repair_prompt_and_skips_stale_skill(tmp_path, capsys):
    # SKILLMAP-12.2
    root, cache = make_tree(tmp_path)
    default_fragments(cache)
    fragment(cache, "plan", loads=[{"md": "reference/nope.md"}])
    (cache / "skills" / "design-ext.json").unlink()
    touch_later(root / "skills/fix/reference/loop.md")
    _, out, data = render(capsys, root, cache, stamped=False)
    prompts = {(p["skill"], p["text"]): p["prompt"] for p in data["problems"]}
    assert prompts == {
        ("plan", "unknown md reference/nope.md"): "Skill `plan` (~/.claude/skills/plan/) names md `reference/nope.md`, which does "
                                                  "not exist. Fix that name in its md files so it points at an existing file, "
                                                  "then run /skill-map."}
    assert "problem: design-ext: no fragment, run scan" in out and "problem: fix: changed since the map was drawn" in out


def test_layout_run_moves_keep_each_card_with_the_lanes_under_it_except_one_lane_moved_alone():
    # SKILLMAP-10.16
    kinds = {"a": "skill", "b": "skill", "c": "skill", "l1": layout.LANE_KIND, "l2": layout.LANE_KIND,
             "l3": layout.LANE_KIND}
    nodes = {i: {"id": i, "kind": kind, "mds": []} for i, kind in kinds.items()}
    units = [["l0"], ["a", "l1"], ["b", "l2", "l3"], ["c"]]
    nodes.update({i: {"id": i, "kind": k, "mds": []} for i, k in (("l0", layout.LANE_KIND), ("z", "skill"))})
    block = [i for unit in units for i in unit]
    moves = [m[0] for m in layout.get_run_moves([block, ["z"]], nodes)]
    assert moves and all(len(m) == len(block) and sorted(m) == sorted(block) for m in moves)

    def get_units(order):
        found = []
        for i in order:
            if found and nodes[i]["kind"] == layout.LANE_KIND:
                found[-1].append(i)
            else:
                found.append([i])
        return found

    def is_whole(order, alone=None):
        return all(unit in [[i for i in u if i != alone] for u in units] for unit in get_units(order))

    lanes = [i for i in block if nodes[i]["kind"] == layout.LANE_KIND]
    assert all(is_whole(m) or any(is_whole([i for i in m if i != lane], lane) for lane in lanes) for m in moves)
    assert len(moves) < 80  # units and lanes alone: far fewer than every run of the 8 ids
    small = {i: {"id": i, "kind": layout.LANE_KIND if i == "l1" else "skill", "mds": []} for i in ("a", "l1", "b")}
    tried = list(layout.get_block_moves(["a", "l1", "b"], small))
    assert ["b", "a", "l1"] in tried and ["l1", "a", "b"] in tried and ["a", "b", "l1"] in tried
    assert ["l1", "b", "a"] not in tried


def test_layout_get_units_joins_lanes_in_a_row_at_the_block_top_into_one_unit():
    # SKILLMAP-10.16
    nodes = {i: {"id": i, "kind": layout.LANE_KIND if i.startswith("l") else "skill", "mds": []}
             for i in ("l0", "l0b", "a", "l1", "b")}
    assert layout.get_units(["l0", "l0b", "a", "l1", "b"], nodes) == [["l0", "l0b"], ["a", "l1"], ["b"]]
    assert ["l0", "b", "l0b", "a"] not in list(layout.get_block_moves(["l0", "l0b", "a", "b"], nodes))
