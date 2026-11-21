"""Places map cards in columns: one band of columns per kind, callers left of callees inside a band; then whole
columns stack under others while that makes edges flow left to right with shorter spans."""
COLUMN_WIDTH = 380
ROW_GAP = 28
CARD_BASE_HEIGHT = 64
LINE_HEIGHT = 18
# rule: commands own the far-left band. Hooks, mods and plugins sit after agents: they call shared skills, md and
# tools right of them; a mod's call into a command draws leftward. MCP servers are called only, so sit by CLI tools.
BANDS = (("command",), ("agent",), ("hook", "mod", "plugin"), ("shared",), ("skill",), ("md",), ("project",),
         ("builtin",), ("mcp",), ("tool",))
RELAX_SWEEPS = 40
FLAT_BANDS = {BANDS.index(("hook", "mod", "plugin")), BANDS.index(("mcp",))}  # one column each: inner edges set no layer
BACKWARD_COST = 30  # stack cost of an edge that runs leftward or stays in its column, on top of its column span


def apply_layout(data: dict) -> None:
    nodes = {n["id"]: n for n in data["nodes"]}
    children = build_children(data["edges"])
    set_back_edges(data["edges"], children, get_root_ids(nodes))
    layers = build_layers(nodes, data["edges"])
    columns = stack_columns(build_columns(layers, data["edges"]), nodes, data["edges"])
    for column, blocks in enumerate(columns):
        set_column_positions(column, [nodes[i] for block in blocks for i in block])
    pull_linked_cards(columns, nodes, data["edges"])


def get_root_ids(nodes: dict[str, dict]) -> list[str]:
    commands = sorted(i for i, n in nodes.items() if n["kind"] == "command")
    return commands + sorted(i for i in nodes if i not in commands)


def build_children(edges: list[dict]) -> dict[str, list[dict]]:
    children: dict[str, list[dict]] = {}
    for edge in edges:
        children.setdefault(edge["src"], []).append(edge)
    return children


def set_back_edges(edges: list[dict], children: dict[str, list[dict]], roots: list[str]) -> None:
    """Iterative DFS; an edge into a node still on the stack closes a cycle and is drawn as a loop back."""
    done: set[str] = set()
    for root in roots:
        if root in done:
            continue
        on_stack, stack = {root}, [(root, iter(children.get(root, [])))]
        while stack:
            node, pending = stack[-1]
            edge = next(pending, None)
            if edge is None:
                stack.pop()
                on_stack.discard(node)
                done.add(node)
                continue
            dst = edge["dst"]
            edge["back"] = dst in on_stack
            if dst not in on_stack and dst not in done:
                on_stack.add(dst)
                stack.append((dst, iter(children.get(dst, []))))


def build_layers(nodes: dict[str, dict], edges: list[dict]) -> dict[str, int]:
    """Kinds sit in bands, left to right in `BANDS`, so cards of one kind share columns; inside a band each card
    sits right of each caller in that band."""
    band = {i: get_band(n) for i, n in nodes.items()}
    layer = build_band_layers(nodes, [e for e in edges if band[e["src"]] == band[e["dst"]] not in FLAT_BANDS])
    offset, start = 0, {}
    for b in sorted(set(band.values())):
        start[b] = offset
        offset += 1 + max(layer[i] for i in nodes if band[i] == b)
    return {i: start[band[i]] + layer[i] for i in nodes}


def get_band(node: dict) -> int:
    return next((i for i, kinds in enumerate(BANDS) if node["kind"] in kinds), len(BANDS))


def build_band_layers(nodes: dict[str, dict], edges: list[dict]) -> dict[str, int]:
    """Longest path from the roots over forward edges."""
    forward = [e for e in edges if not e["back"]]
    layer = {i: 0 for i in nodes}
    for _ in range(len(nodes)):
        changed = False
        for edge in forward:
            if layer[edge["dst"]] <= layer[edge["src"]]:
                layer[edge["dst"]] = layer[edge["src"]] + 1
                changed = True
        if not changed:
            break
    return layer


def build_columns(layers: dict[str, int], edges: list[dict]) -> list[list[str]]:
    """One barycenter pass: a card sits near the mean row of the cards that point at it."""
    columns: list[list[str]] = [[] for _ in range(max(layers.values(), default=-1) + 1)]
    for node_id in sorted(layers):
        columns[layers[node_id]].append(node_id)
    row: dict[str, float] = {i: r for r, i in enumerate(columns[0])} if columns else {}
    for column in columns[1:]:
        column.sort(key=lambda i: get_mean_parent_row(i, edges, row))
        row.update({i: r for r, i in enumerate(column)})
    return columns


def get_mean_parent_row(node_id: str, edges: list[dict], row: dict[str, float]) -> float:
    parents = [row[e["src"]] for e in edges if e["dst"] == node_id and e["src"] in row]
    return sum(parents) / len(parents) if parents else float("inf")


def stack_columns(columns: list[list[str]], nodes: dict[str, dict], edges: list[dict]) -> list[list[list[str]]]:
    """Greedy: move the whole column (a block of one band) under the other column that lowers the flow cost most,
    while no column grows past the tallest column; repeat until no move helps. The first column stays first."""
    stacked = [[ids] for ids in columns if ids]
    limit = max((get_stack_height(c, nodes) for c in stacked), default=0)
    links = [(e["src"], e["dst"]) for e in edges if e["src"] != e["dst"]]
    while True:
        best, best_cost = None, get_flow_cost(stacked, links)
        for j in range(1, len(stacked)):
            for i in range(len(stacked)):
                if i == j or get_stack_height(stacked[i] + stacked[j], nodes) > limit:
                    continue
                trial = [c + stacked[j] if k == i else c for k, c in enumerate(stacked) if k != j]
                cost = get_flow_cost(trial, links)
                if cost < best_cost:
                    best, best_cost = trial, cost
        if best is None:
            return stacked
        stacked = best


def get_stack_height(blocks: list[list[str]], nodes: dict[str, dict]) -> int:
    ids = [i for block in blocks for i in block]
    return sum(get_card_height(nodes[i]) for i in ids) + ROW_GAP * max(len(ids) - 1, 0)


def get_flow_cost(columns: list[list[list[str]]], links: list[tuple[str, str]]) -> int:
    column = {i: c for c, blocks in enumerate(columns) for block in blocks for i in block}
    spans = [column[dst] - column[src] for src, dst in links]
    return sum(abs(s) + (BACKWARD_COST if s <= 0 else 0) for s in spans)


def set_column_positions(column: int, cards: list[dict]) -> None:
    y = 0
    for card in cards:
        card["x"], card["y"] = column * COLUMN_WIDTH, y
        y += get_card_height(card) + ROW_GAP


def pull_linked_cards(columns: list[list[list[str]]], nodes: dict[str, dict], edges: list[dict]) -> None:
    """Rubber bands: each edge pulls the centers of its two cards toward the same height. Sweeps alternate left to
    right and right to left; each block re-sorts its cards by wanted y, blocks keep their stack order, then the column
    keeps the row gap. Top card ends at y 0."""
    links: dict[str, list[str]] = {}
    for edge in edges:
        if edge["src"] != edge["dst"]:
            links.setdefault(edge["src"], []).append(edge["dst"])
            links.setdefault(edge["dst"], []).append(edge["src"])
    center = lambda i: nodes[i]["y"] + get_card_height(nodes[i]) / 2
    for sweep in range(RELAX_SWEEPS):
        for blocks in columns if sweep % 2 == 0 else reversed(columns):
            ids = [i for block in blocks for i in block]
            wanted = {i: sum(map(center, links[i])) / len(links[i]) - get_card_height(nodes[i]) / 2 if i in links
                      else nodes[i]["y"] for i in ids}
            for block in blocks:
                block.sort(key=lambda i: wanted[i] + get_card_height(nodes[i]) / 2)
            ids = [i for block in blocks for i in block]
            for i, y in zip(ids, pack_column([get_card_height(nodes[i]) for i in ids], [wanted[i] for i in ids])):
                nodes[i]["y"] = y
    top = min((n["y"] for n in nodes.values()), default=0)
    for n in nodes.values():
        n["y"] = round(n["y"] - top)


def pack_column(heights: list[int], targets: list[float]) -> list[float]:
    """Least-squares y per card, in order, no overlap: a card that would overlap the one above joins its block, and
    a block sits at the mean of its cards' targets less their offsets in the block."""
    blocks: list[list[int]] = []  # card indexes, top block first
    offset = [0.0] * len(heights)
    def place(block: list[int]) -> float:
        return sum(targets[k] - offset[k] for k in block) / len(block)
    def bottom(block: list[int]) -> float:
        return place(block) + offset[block[-1]] + heights[block[-1]]
    for i in range(len(heights)):
        block = [i]
        while blocks and bottom(blocks[-1]) + ROW_GAP > place(block):
            above = blocks.pop()
            start = offset[above[-1]] + heights[above[-1]] + ROW_GAP
            for k in block:
                offset[k] += start
            block = above + block
        blocks.append(block)
    ys = [0.0] * len(heights)
    for block in blocks:
        for k in block:
            ys[k] = place(block) + offset[k]
    return ys


def get_card_height(card: dict) -> int:
    lines = len(card.get("mds", [])) + (1 if card.get("args") else 0) + (1 if card["kind"] == "agent" else 0)
    return CARD_BASE_HEIGHT + LINE_HEIGHT * lines
