"""Turns unit fragments (skills, hooks, mods, plugins) into the nodes and edges the map draws."""
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from units import Unit, find_mcp_servers, is_known_mcp_server

HOME_PREFIX = "~/.claude/"
OUTSIDE_PREFIXES = ("builtin:", "project:", "mcp:", "tool:")
OPTIONAL_WHEN = "if installed"  # `when` of a tool ref the skill runs only when the tool is there
TOKEN_BYTES = 4
LIST_FIELDS = ("args", "agents")
REF_FIELDS = (("loads", "md"), ("calls", "skill"))
TEXT_KEYS = ("when", "callArgs", "loop", "type", "model", "effort", "count", "items", "modelArg")


@dataclass
class Ref:
    owner: str
    loader: str
    target: str
    kind: str
    entry: dict
    path: Path | None = None


def build_graph(root: Path, units: dict[str, Unit], fragments: dict[str, dict]) -> dict:
    builder = GraphBuilder(root, units, find_mcp_servers(root))
    for name, data in fragments.items():
        builder.add_fragment(name, data)
    builder.add_settings_facts()
    edges = builder.apply_links()
    return {"nodes": list(builder.nodes.values()), "edges": edges, "problems": builder.problems, "missing": builder.missing}


@dataclass
class GraphBuilder:
    root: Path
    units: dict[str, Unit]
    mcp_servers: set[str]
    nodes: dict[str, dict] = field(default_factory=dict)
    refs: list[Ref] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)
    # rule: a target that is gone is no fragment fault: kept apart from `problems`, so no re-read is forced.
    missing: list[dict] = field(default_factory=list)

    def add_fragment(self, name: str, data: dict) -> None:
        shape_problems = find_shape_problems(data)
        if shape_problems:
            self.problems += [(name, text) for text in shape_problems]
            return
        unit = self.units[name]
        self.nodes[unit.node_id] = build_unit_node(unit, data)
        self.add_refs(name, unit.node_id, data)
        for agent in data.get("agents", []):
            self.add_agent(name, unit.node_id, agent, data.get("args", []))

    def add_settings_facts(self) -> None:
        """settings.json facts need no agent: a hook that runs a tool gets a bare card, and an `mcp__<server>__` matcher an edge."""
        for unit in self.units.values():
            self.missing += [build_missing(unit.name, text, prompt, unit.node_id) for text, prompt in unit.missing]
            if not unit.files:
                self.nodes[unit.node_id] = {"id": unit.node_id, "kind": unit.kind, "label": unit.label,
                                            "summary": " · ".join(unit.events), "args": [], "mds": [], "tok": 0}
            if unit.node_id in self.nodes:
                for server in unit.mcp:
                    self.add_ref(Ref(unit.name, unit.node_id, f"mcp:{server}", "call", {"when": "matcher"}))
            self.add_plugin_edge(unit)

    def add_plugin_edge(self, unit: Unit) -> None:
        """A plugin's card links to each skill it ships."""
        plugin = self.units.get(unit.plugin)
        if plugin and plugin.node_id in self.nodes and unit.node_id in self.nodes:
            self.add_ref(Ref(plugin.name, plugin.node_id, unit.name, "call", {"when": "ships"}))

    def add_refs(self, owner: str, loader: str, data: dict) -> None:
        for entry in data.get("loads", []):
            self.add_ref(Ref(owner, loader, entry["md"], "load", entry))
        for entry in data.get("calls", []):
            self.add_ref(Ref(owner, loader, entry["skill"], "call", entry))

    def add_ref(self, ref: Ref) -> None:
        """`ref.target` comes in as the fragment's text and leaves as a node id."""
        ref.target, ref.path = self.resolve(ref.owner, ref.target)
        if ref.target:
            self.check_outside_target(ref)
            self.refs.append(ref)

    def resolve(self, owner: str, ref: str) -> tuple[str, Path | None]:
        if ref.startswith(OUTSIDE_PREFIXES):
            self.ensure_outside_node(ref)
            return ref, None
        if self.is_skill(ref):
            return f"skill:{ref}", None
        path = self.resolve_path(owner, ref)
        if not path.is_file():
            self.problems.append((owner, f"unknown {'md' if ref.endswith('.md') else 'skill'} {ref}"))
            return "", None
        return f"md:{path.relative_to(self.root).as_posix()}", path

    def check_outside_target(self, ref: Ref) -> None:
        """An MCP server no config lists, or a required CLI tool not on the PATH, is a missing target."""
        kind, _, name = ref.target.partition(":")
        user = f"`{self.units[ref.owner].label or ref.owner}`"
        if kind == "mcp" and not is_known_mcp_server(name, self.mcp_servers):
            self.add_missing(ref, f"unknown mcp server {name}",
                             f"{user} uses MCP server `{name}`, which no MCP config lists (~/.claude.json, a plugin's "
                             ".mcp.json). Add the server, or fix the name where it is used, then run /skill-map.")
        elif kind == "tool" and OPTIONAL_WHEN not in ref.entry.get("when", "") and not shutil.which(name):
            self.add_missing(ref, f"missing tool {name}",
                             f"{user} runs CLI tool `{name}`, which is not installed. Install it, or make the skill fall "
                             "back when it is missing, then run /skill-map.")

    def add_missing(self, ref: Ref, text: str, prompt: str) -> None:
        if not any(m["skill"] == ref.owner and m["text"] == text for m in self.missing):
            self.missing.append(build_missing(ref.owner, text, prompt, ref.target))

    def is_skill(self, ref: str) -> bool:
        return ref in self.units and self.units[ref].kind == "skill"

    def ensure_outside_node(self, ref: str) -> None:
        """A built-in command is a skill the user types, so its card reads `/<name>` like a command skill."""
        kind, name = ref.split(":", 1)
        label = f"/{name}" if kind == "builtin" else name
        self.nodes.setdefault(ref, {"id": ref, "kind": kind, "label": label, "mds": [], "args": [], "tok": 0})

    def resolve_path(self, owner: str, ref: str) -> Path:
        if ref.startswith(HOME_PREFIX):
            return self.root / ref[len(HOME_PREFIX):]
        return self.units[owner].folder / ref

    def add_agent(self, owner: str, skill_id: str, agent: dict, args: list[dict]) -> None:
        """`modelArg` names the owner's arg that sets the agent's model; the card shows that arg's label."""
        agent_id = f"agent:{owner}:{agent['id']}"
        node = build_agent_node(agent_id, agent, self.get_model_arg_label(owner, agent, args))
        self.nodes[agent_id] = node | {"tok": self.get_agent_tok(owner, agent)}
        self.refs.append(Ref(owner, skill_id, agent_id, "spawn", agent))
        self.add_refs(owner, agent_id, agent)

    def get_model_arg_label(self, owner: str, agent: dict, args: list[dict]) -> str:
        label = next((a.get("label") or a["id"] for a in args if a["id"] == agent.get("modelArg")), "")
        if agent.get("modelArg") and not label:
            self.problems.append((owner, f"agent {agent['id']} modelArg {agent['modelArg']} is no arg"))
        return label

    def get_agent_tok(self, owner: str, agent: dict) -> int:
        paths = [self.find_load_path(owner, entry["md"]) for entry in agent.get("loads", [])]
        paths.append(self.root / "agents" / f"{agent.get('type', '')}.md")
        return sum(get_file_bytes(p) for p in paths if p) // TOKEN_BYTES

    def find_load_path(self, owner: str, ref: str) -> Path | None:
        if ref.startswith(OUTSIDE_PREFIXES):
            return None
        if self.is_skill(ref):
            return self.units[ref].folder / "SKILL.md"
        return self.resolve_path(owner, ref)

    def apply_links(self) -> list[dict]:
        owners, edges = self.build_owners_by_target(), []
        for ref in self.refs:
            if self.is_own_md(ref, owners):
                self.nodes[ref.loader]["mds"].append(build_own_md_line(ref, self.units[ref.owner].folder))
                continue
            self.ensure_target_node(ref)
            edges.append(build_edge(len(edges), ref))
        for node_id, node in self.nodes.items():
            node["shared"] = len(owners.get(node_id, ())) >= 2
        return edges

    def build_owners_by_target(self) -> dict[str, set[str]]:
        owners: dict[str, set[str]] = {}
        for ref in self.refs:
            owners.setdefault(ref.target, set()).add(ref.owner)
        return owners

    def is_own_md(self, ref: Ref, owners: dict[str, set[str]]) -> bool:
        return ref.path is not None and len(owners[ref.target]) == 1 and ref.path.is_relative_to(self.units[ref.owner].folder)

    def ensure_target_node(self, ref: Ref) -> None:
        kind, label, tok = ("skill", ref.target[6:], 0) if ref.path is None else ("md", ref.target[3:], get_file_tok(ref.path))
        self.nodes.setdefault(ref.target, {"id": ref.target, "kind": kind, "label": label, "mds": [], "args": [], "tok": tok})


def find_shape_problems(data: dict) -> list[str]:
    """Agent-written JSON is untrusted: a fragment with a wrong shape is reported, never drawn."""
    problems = [f"{name} not a list" for name in LIST_FIELDS if not isinstance(data.get(name, []), list)]
    if problems:
        return problems
    problems += ["arg without id" for arg in data.get("args", []) if not has_text(arg, "id")]
    problems += find_ref_problems(data)
    for agent in data.get("agents", []):
        problems += find_ref_problems(agent) + find_type_problems(agent) if has_text(agent, "id") else ["agent without id"]
    return problems


def find_type_problems(entry: dict) -> list[str]:
    """The page and labels read these fields as text and arg lists; any other type breaks them."""
    problems = [f"{key} not text" for key in TEXT_KEYS if not isinstance(entry.get(key, ""), str)]
    args = entry.get("args", [])
    if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
        problems.append("args not a list of text")
    return problems


def has_text(entry: object, key: str) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get(key), str)


def find_ref_problems(data: dict) -> list[str]:
    problems = []
    for name, key in REF_FIELDS:
        entries = data.get(name, [])
        if not isinstance(entries, list):
            problems.append(f"{name} not a list")
            continue
        for entry in entries:
            problems += find_type_problems(entry) if has_text(entry, key) else [f"{name[:-1]} without {key}"]
    return problems


def build_missing(owner: str, text: str, prompt: str, node_id: str) -> dict:
    return {"skill": owner, "text": text, "prompt": prompt, "node": node_id}


def build_unit_node(unit: Unit, data: dict) -> dict:
    skill = unit.kind == "skill"
    return {"id": unit.node_id, "kind": data.get("kind", "command") if skill else unit.kind,
            "label": format_skill_label(unit.name, data) if skill else unit.label,
            "summary": " · ".join(filter(None, unit.events + [data.get("summary", "")])),
            "args": data.get("args", []), "mds": [], "tok": get_file_tok(unit.folder / "SKILL.md") if skill else 0}


def build_agent_node(agent_id: str, agent: dict, model_arg: str) -> dict:
    model = ":".join(part for part in (agent.get("model", ""), agent.get("effort", "")) if part)
    return {"id": agent_id, "kind": "agent", "label": agent["id"], "summary": agent.get("type", ""), "model": model,
            "modelArg": model_arg, "count": agent.get("count", ""), "items": agent.get("items", ""), "mds": [],
            "args": []}


def format_skill_label(name: str, data: dict) -> str:
    return f"/{name}" if data.get("kind", "command") == "command" else name


def get_file_tok(path: Path) -> int:
    return get_file_bytes(path) // TOKEN_BYTES


def get_file_bytes(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def build_own_md_line(ref: Ref, folder: Path) -> dict:
    return {"name": ref.path.relative_to(folder).as_posix(), "when": ref.entry.get("when", ""),
            "args": ref.entry.get("args", []), "tok": get_file_tok(ref.path)}


def build_edge(index: int, ref: Ref) -> dict:
    entry = ref.entry
    return {"id": index, "src": ref.loader, "dst": ref.target, "kind": ref.kind, "when": entry.get("when", ""),
            "args": entry.get("args", []), "callArgs": entry.get("callArgs", ""), "loop": entry.get("loop", ""),
            "count": entry.get("count", "") if ref.kind == "spawn" else "", "back": False}
