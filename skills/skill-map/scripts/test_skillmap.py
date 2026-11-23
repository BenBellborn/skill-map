"""Tests for skillmap.py: `python -m pytest -q skills/skill-map/scripts`."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cost  # noqa: E402
import layout  # noqa: E402
import skillmap  # noqa: E402
import units  # noqa: E402


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
    layout.pull_linked_cards(columns, cards, edges)
    y = {i: c["y"] for i, c in cards.items()}
    assert (y["a"] < y["b"]) == (y["d"] < y["c"]) and (y["d"], y["c"]) == (y["a"], y["b"])


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
