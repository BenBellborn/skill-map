"""Token cost model of the map: agent runs, and hints that name where a flow could read fewer tokens."""
import math
import re

AGENT_BASE_TOK = 48_000  # system prompt and tools of one agent start; median of 8 low-tool runs in ~/.claude/projects: 50k
MS_PER_TOK = 2  # median duration per context token over 513 agent runs in ~/.claude/projects
SKILL_TOK_LIMIT = 2_000  # SKILL.md above ~8 KB: detail belongs in reference files
SKILL_TOK_TARGET = 1_000
ALWAYS_MD_TOK_LIMIT = 1_500  # own md read on every run, no condition
AGENT_CTX_TOK_LIMIT = 5_000  # md an agent reads at start, base left out
AGENT_CTX_TOK_TARGET = 2_000
MIN_SAVE_TOK = 2_000  # a smaller saving is not worth an edit: no hint, no red mark


def apply_cost(data: dict) -> None:
    """Adds `runs` to agents, `hints` to nodes and own md lines, and the page's cost constants to `data`."""
    for node in data["nodes"]:
        if node["kind"] == "agent":
            node["runs"] = parse_runs(node.get("count", ""))
        node["hints"] = keep_big_saves(find_node_hints(node))
        for md in node["mds"]:
            md["hints"] = keep_big_saves(find_md_hints(get_owner(node), md))
    data["cost"] = {"agentBase": AGENT_BASE_TOK, "msPerTok": MS_PER_TOK}


def keep_big_saves(hints: list[dict]) -> list[dict]:
    return [h for h in hints if h["save"] >= MIN_SAVE_TOK]


def parse_runs(count: str) -> int:
    """`≤5 per batch` runs 5 agents, `3` runs 3; no leading number runs 1 (`per unit >100 lines` is a size, not a count)."""
    m = re.match(r"\s*(?:≤|<=|up to)?\s*(\d+)", count)
    return max(1, int(m.group(1))) if m else 1


def get_owner(node: dict) -> str:
    """Skill folder name behind `skill:<name>` or `agent:<owner>:<id>`."""
    return node["id"].split(":")[1]


def find_node_hints(node: dict) -> list[dict]:
    if node["kind"] == "agent":
        return find_agent_hints(node)
    if node["kind"] in ("command", "shared") and node["tok"] > SKILL_TOK_LIMIT:
        name = get_owner(node)
        return [build_hint(node["tok"] - SKILL_TOK_TARGET,
                           f"~/.claude/skills/{name}/SKILL.md is ~{format_tok(node['tok'])} and read on every run of `{name}`. "
                           "Move detail into reference files loaded only under the condition that needs them.")]
    return []


def find_agent_hints(node: dict) -> list[dict]:
    runs, ctx, owner, agent = node["runs"], AGENT_BASE_TOK + node["tok"], get_owner(node), node["label"]
    hints = []
    if runs >= 2 and takes_one_item(node.get("items", "")):
        fewer = runs - math.ceil(runs / 2)
        hints.append(build_hint(fewer * ctx, f"In skill `{owner}`, agent `{agent}` starts {runs} times at ~{format_tok(ctx)} each. "
                                             f"Give each agent 2 items so it starts {runs - fewer} times, with the same result."))
    if node["tok"] > AGENT_CTX_TOK_LIMIT:
        hints.append(build_hint((node["tok"] - AGENT_CTX_TOK_TARGET) * runs,
                                f"In skill `{owner}`, agent `{agent}` reads ~{format_tok(node['tok'])} of md at start. "
                                "Brief it with a digest of what it needs, not whole md files."))
    return hints


def takes_one_item(items: str) -> bool:
    """Only an agent the skill states takes one item can batch more; `2-4` or unknown already batches or may."""
    numbers = re.findall(r"\d+", items)
    return bool(numbers) and int(numbers[-1]) == 1


def find_md_hints(owner: str, md: dict) -> list[dict]:
    if md["when"] or md["args"] or md["tok"] <= ALWAYS_MD_TOK_LIMIT:
        return []
    return [build_hint(md["tok"], f"~/.claude/skills/{owner}/{md['name']} (~{format_tok(md['tok'])}) is read on every run of "
                                  f"`{owner}`. Load it only under the condition that needs it.")]


def build_hint(save: int, prompt: str) -> dict:
    """`prompt` names the file and the change, so an AI given only this line knows what to edit."""
    return {"save": save, "prompt": prompt}


def format_tok(tok: int) -> str:
    return f"{tok / 1000:.1f}k tok" if tok >= 1000 else f"{tok} tok"
