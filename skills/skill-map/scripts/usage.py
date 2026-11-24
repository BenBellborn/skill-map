"""Counts how often each edge is used: the paths from the entry cards that cross it, with the page trace's arg
rules."""
import re

# rule: same token rules as the page trace (template.html matchArg, nextState, argsMatch).
MODEL_TOKEN = re.compile(r"^(opus|sonnet|haiku|fable)(:[a-z]+)?$")


def get_edge_usage(nodes: dict[str, dict], edges: list[dict]) -> list[int]:
    """Per edge (list index), the paths that cross it. Paths start at each entry card (a command, or a card no edge
    points at), run bare and once with each of the card's own args. Loop-back and self edges are left out."""
    counter, usage = PathCounter(nodes, edges), [0] * len(edges)
    for entry, args in get_entry_runs(nodes, edges):
        for k, paths in counter.get_counts(entry, args).items():
            usage[k] += paths
    return usage


def get_entry_runs(nodes: dict[str, dict], edges: list[dict]) -> list[tuple[str, frozenset]]:
    targets = {edge["dst"] for edge in edges if edge["src"] != edge["dst"]}
    entries = [i for i, n in nodes.items() if n["kind"] == "command" or i not in targets]
    return [(i, args) for i in entries for args in [frozenset()] + [frozenset([a["id"]]) for a in nodes[i].get("args", [])]]


class PathCounter:
    """Counts paths per edge from a card run with a set of args; each card and args pair is counted once."""

    def __init__(self, nodes: dict[str, dict], edges: list[dict]):
        self.nodes, self.edges, self.memo = nodes, edges, {}
        self.out: dict[str, list[int]] = {}
        for k, edge in enumerate(edges):
            if not edge.get("back") and edge["src"] != edge["dst"]:
                self.out.setdefault(edge["src"], []).append(k)

    def get_counts(self, node_id: str, args: frozenset) -> dict[int, int]:
        """Per edge index, the paths from this card, run with these args, that end with that edge."""
        key = (node_id, args)
        if key not in self.memo:
            counts: dict[int, int] = {}
            for k in (k for k in self.out.get(node_id, []) if is_open(self.edges[k], args)):
                counts[k] = counts.get(k, 0) + 1
                self.add_counts(counts, self.edges[k], args)
            self.memo[key] = counts
        return self.memo[key]

    def add_counts(self, counts: dict[int, int], edge: dict, args: frozenset) -> None:
        for k, paths in self.get_counts(edge["dst"], get_next_args(edge, args, self.nodes)).items():
            counts[k] = counts.get(k, 0) + paths


def is_open(edge: dict, args: frozenset) -> bool:
    return not edge.get("args") or bool(args & set(edge["args"]))


def get_next_args(edge: dict, args: frozenset, nodes: dict[str, dict]) -> frozenset:
    """A spawned agent runs under its spawner's args; a called or loaded card only under the args the call passes."""
    if edge.get("kind") == "spawn":
        return args
    ids = {a["id"] for a in nodes[edge["dst"]].get("args", [])}
    return frozenset(filter(None, (find_arg(token, ids) for token in edge.get("callArgs", "").split())))


def find_arg(token: str, ids: set[str]) -> str | None:
    if token in ids:
        return token
    if MODEL_TOKEN.match(token):
        return "model" if "model" in ids else None
    prefix = token.split(":")[0]
    return prefix if ":" in token and prefix in ids else None
