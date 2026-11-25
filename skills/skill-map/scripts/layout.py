"""Places map cards in columns: one band of columns per kind, callers left of callees inside a band; then whole
columns stack under others while that makes edges flow left to right with shorter spans; last, single cards leave
their band's column when that saves more flow cost than the cohesion they lose. Rubber bands then sort each column,
and each column becomes a packed stack (cards in order, gaps allowed, colliding cards led by the highest-ranked
card's wanted y) in the order that scores best, with sweeps both ways; the polish ends with one pass of fresh
wishes, left to right (callers mostly sit left). Before the pull, an edge that skips columns gets a lane card per
passed column (shared per source; edges alone in their source's lane share one per target), so pull and polish keep
a free row for its line; lanes end up in edge `lanes`.
Polish moves a card with the lanes right under it as one unit, and each lane alone, so lanes add few moves."""
from collections import Counter
from typing import NamedTuple

from usage import get_edge_usage

COLUMN_WIDTH = 380
ROW_GAP = 8  # rule: same gap as the page's column stack
CARD_BASE_HEIGHT = 64
LINE_HEIGHT = 18
# rule: commands own the far-left band. Hooks, mods and plugins sit after agents: they call shared skills, md and
# tools right of them; a mod's call into a command draws leftward. MCP servers are called only, so sit by CLI tools.
BANDS = (("command",), ("agent",), ("hook", "mod", "plugin"), ("shared",), ("skill",), ("md",), ("project",),
         ("builtin",), ("mcp",), ("tool",))
RELAX_SWEEPS = 40
FLAT_BANDS = {BANDS.index(("hook", "mod", "plugin")), BANDS.index(("mcp",))}  # one column each: inner edges set no layer
BACKWARD_COST = 100  # cost of an edge that runs leftward or stays in its column, on top of its column span
# rule: place step only. In the stack step it packs whole bands into few columns, and edges turn backward.
PASS_COST = 15  # cost per column an edge passes between its two cards
# rule: below BACKWARD_COST, so one edge that runs back moves a card out of its band's column.
COHESION_GAIN = 30  # gain per card that shares a column with the rest of its band
GAIN_DIGITS = 9  # decimals kept of a place move's score change; float noise sits near 1e-14
# Polish step gains, in px of edge height, per path.
# rule: page edges join points 18 px below both card tops: level edge = same top.
SIBLING_GAIN = 200  # gain per two neighbor cards in a column with a shared caller
SIBLING_FLOOR = 5000  # least gain of such two cards, so unused siblings still join their group
LEVEL_GAIN = 50  # gain per level edge between two columns
ORDER_COST = 10  # cost per path of difference when a less used card sits above a more used one with the same caller
CROSSING_COST = 100  # cost per crossing of two edges to one neighbor column, per path of both edges
POLISH_PASSES = 20  # most sweeps; the polish stops at the first sweep that changes no column
# rule: above any card's use, so a card level with its single caller outranks every median card in a packed block.
LEVEL_RANK = 1_000_000
# rule: page line runs 18 px below lane top, like card edges: lane level with card at same y stays straight.
LANE_HEIGHT = 18  # row gap above, line at the lane bottom, row gap below
LANE_KIND = "lane"  # layout-only card, a slot of edges in a column they pass; never in data["nodes"]
# rule: tuples, not objects: hot path, the polish packs every order it scores.
# Packed block: first card, card count, highest rank, targets of cards of that rank less their offsets from the anchor
# card, count of those cards, anchor card.
Block = tuple[int, int, int, float, int, int]


class OrderFacts(NamedTuple):
    """Facts of the column order the polish moves from: its cards, index of the first card with a target, crossed
    cost, and the packed stack after each count of top cards."""
    ids: list[str]
    first_target: int
    crossed: float
    stacks: list[list[Block]]


def apply_layout(data: dict) -> None:
    nodes = {n["id"]: n for n in data["nodes"]}
    children = build_children(data["edges"])
    set_back_edges(data["edges"], children, get_root_ids(nodes))
    layers = build_layers(nodes, data["edges"])
    columns = stack_columns(build_columns(layers, data["edges"]), nodes, data["edges"])
    columns = place_cards(columns, nodes, data["edges"])
    for column, blocks in enumerate(columns):
        set_column_positions(column, [nodes[i] for block in blocks for i in block])
    set_rows(columns, nodes, data["edges"])


def set_rows(columns: list[list[list[str]]], nodes: dict[str, dict], edges: list[dict]) -> None:
    """Y of each card and lane: lanes join the columns, then pull and polish run over edges split at their lanes."""
    # rule: usage before lanes: a lane card has callers, never is an entry, and runs no args.
    usage = get_edge_usage(nodes, edges)
    lanes = get_lane_ids(edges, get_passed_columns(columns, edges))
    add_lanes(columns, nodes, edges, lanes)
    links, link_usage = split_edges(edges, usage, lanes)
    pull_linked_cards(columns, nodes, get_links(links))
    improve_columns(columns, nodes, links, link_usage)
    set_top_to_zero(nodes)
    set_edge_lanes(edges, nodes, lanes)


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


def get_flow_cost(columns: list[list[list[str]]], links: list[tuple[str, str]], pass_cost: int = 0) -> int:
    column = get_column_index(columns)
    return sum(get_span_cost(column[dst] - column[src], pass_cost) for src, dst in links)


def get_column_index(columns: list[list[list[str]]]) -> dict[str, int]:
    return {i: c for c, blocks in enumerate(columns) for i in get_ids(blocks)}


def get_ids(blocks: list[list[str]]) -> list[str]:
    return [i for block in blocks for i in block]


def get_span_cost(span: int, pass_cost: int) -> int:
    return abs(span) + pass_cost * max(abs(span) - 1, 0) + (BACKWARD_COST if span <= 0 else 0)


def place_cards(columns: list[list[list[str]]], nodes: dict[str, dict], edges: list[dict]) -> list[list[list[str]]]:
    """Greedy: move the one card (never a command) to the other column that lowers flow cost less cohesion gain
    most, while no column grows past the tallest column; repeat until no move helps."""
    limit = max((get_stack_height(c, nodes) for c in columns), default=0)
    links = [(e["src"], e["dst"]) for e in edges if e["src"] != e["dst"]]
    movable = sorted(i for i, n in nodes.items() if n["kind"] != "command")
    while True:
        best = MoveScorer(columns, nodes, links, limit).get_best_move(movable)
        if best is None:
            return columns
        columns = move_card(columns, *best, links)


class MoveScorer:
    """Score change (flow cost less cohesion gain) of moving one card to another column of one layout. Only the
    card's links and its band's counts in both columns change, unless its column empties: then later columns shift,
    and the layout is scored whole."""

    def __init__(self, columns: list[list[list[str]]], nodes: dict[str, dict], links: list[tuple[str, str]],
                 limit: int):
        self.columns, self.nodes, self.links, self.limit = columns, nodes, links, limit
        self.band = {i: get_band(n) for i, n in nodes.items()}
        self.size = Counter(self.band.values())
        self.links_of = get_links_of(links)
        self.column = get_column_index(columns)
        self.counts = [Counter(self.band[i] for i in get_ids(blocks)) for blocks in columns]
        self.heights = [get_stack_height(blocks, nodes) for blocks in columns]
        self.current_score: float | None = None

    def get_best_move(self, movable: list[str]) -> tuple[str, int] | None:
        """(card, target) of the lowest score change below 0; the first such move wins a tie."""
        best, best_gain = None, 0
        moves = ((i, t) for i in movable for t in range(len(self.columns)))
        for node_id, target in moves:
            gain = self.get_gain(node_id, target)
            if gain is not None and gain < best_gain:
                best, best_gain = (node_id, target), gain
        return best

    def get_score(self, columns: list[list[list[str]]]) -> float:
        return get_flow_cost(columns, self.links, PASS_COST) - COHESION_GAIN * get_cohesion(columns, self.band)

    def get_gain(self, node_id: str, target: int) -> float | None:
        """None when the card already sits in the target column or the target grows past the limit."""
        source = self.column[node_id]
        if target == source or self.heights[target] + get_card_height(self.nodes[node_id]) + ROW_GAP > self.limit:
            return None
        if self.counts[source].total() == 1:
            gain = self.get_emptying_gain(node_id, target)
        else:
            gain = self.get_flow_change(node_id, target) - COHESION_GAIN * self.get_cohesion_change(node_id, target)
        # rule: rounded, so a whole-layout gain with float noise ties an equal change gain, and the first move wins.
        return round(gain, GAIN_DIGITS)

    def get_emptying_gain(self, node_id: str, target: int) -> float:
        if self.current_score is None:
            self.current_score = self.get_score(self.columns)
        return self.get_score(move_card(self.columns, node_id, target, self.links)) - self.current_score

    def get_flow_change(self, node_id: str, target: int) -> int:
        column = self.column
        change = 0
        for src, dst in self.links_of.get(node_id, []):
            new_src, new_dst = (target if i == node_id else column[i] for i in (src, dst))
            change += get_span_cost(new_dst - new_src, PASS_COST) - get_span_cost(column[dst] - column[src], PASS_COST)
        return change

    def get_cohesion_change(self, node_id: str, target: int) -> float:
        band = self.band[node_id]
        if self.size[band] == 1:
            return 0
        source = self.column[node_id]
        return (self.counts[target][band] - (self.counts[source][band] - 1)) / (self.size[band] - 1)


def get_links_of(links: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Per card: each link it ends, once per end it holds."""
    links_of: dict[str, list[tuple[str, str]]] = {}
    for link in links:
        for end in link:
            links_of.setdefault(end, []).append(link)
    return links_of


def get_cohesion(columns: list[list[list[str]]], band: dict[str, int]) -> float:
    """Per band: pairs of its cards that share a column, over its size less 1, so a card that leaves a column
    holding all the rest of its band costs 1."""
    size: dict[int, int] = {}
    for b in band.values():
        size[b] = size.get(b, 0) + 1
    total = 0.0
    for blocks in columns:
        count: dict[int, int] = {}
        for i in (i for block in blocks for i in block):
            count[band[i]] = count.get(band[i], 0) + 1
        total += sum(n * (n - 1) / 2 / (size[b] - 1) for b, n in count.items() if size[b] > 1)
    return total


def move_card(columns: list[list[list[str]]], node_id: str, target: int,
              links: list[tuple[str, str]]) -> list[list[list[str]]] | None:
    """Copy with the card moved into the target column's block that holds a linked card, else its last block;
    None when the card already sits there. Empty blocks and columns close up."""
    if any(node_id in block for block in columns[target]):
        return None
    linked = {d if s == node_id else s for s, d in links if node_id in (s, d)}
    trial = drop_card(columns, node_id)
    home = next((block for block in trial[target] if linked & set(block)), trial[target][-1])
    home.append(node_id)
    return close_up(trial)


def drop_card(columns: list[list[list[str]]], node_id: str) -> list[list[list[str]]]:
    return [[[i for i in block if i != node_id] for block in blocks] for blocks in columns]


def close_up(columns: list[list[list[str]]]) -> list[list[list[str]]]:
    kept = ([block for block in blocks if block] for blocks in columns)
    return [blocks for blocks in kept if blocks]


def set_column_positions(column: int, cards: list[dict]) -> None:
    y = 0
    for card in cards:
        card["x"], card["y"] = column * COLUMN_WIDTH, y
        y += get_card_height(card) + ROW_GAP


def get_passed_columns(columns: list[list[list[str]]], edges: list[dict]) -> list[list[int]]:
    """Per edge, the columns it passes on its way right, left to right; none for a loop back."""
    column = {i: c for c, blocks in enumerate(columns) for block in blocks for i in block}
    return [[] if edge["back"] else list(range(column[edge["src"]] + 1, column[edge["dst"]])) for edge in edges]


def get_lane_id(src: str, column: int) -> str:
    return f"{LANE_KIND}:{column}:{src}"


def get_join_lane_id(dst: str, column: int) -> str:
    return f"{LANE_KIND}-in:{column}:{dst}"


def get_lane_ids(edges: list[dict], passed: list[list[int]]) -> list[list[str]]:
    """Per edge, its lane id per passed column, left to right: its source's lane, shared by the source's edges there.
    Edges into one target that are each alone in their source's lane there share one lane instead."""
    # rule: source sharing wins: an edge leaves its source's lane only where no other edge of that source uses it.
    per_source = count_lane_users(edges, passed, "src")
    alone = [{c for c in columns_passed if per_source[edge["src"], c] == 1}
             for edge, columns_passed in zip(edges, passed)]
    per_target = count_lane_users(edges, alone, "dst")
    return [[get_join_lane_id(edge["dst"], c) if c in solo and per_target[edge["dst"], c] > 1
             else get_lane_id(edge["src"], c) for c in columns_passed]
            for edge, columns_passed, solo in zip(edges, passed, alone)]


def count_lane_users(edges: list[dict], columns: list, end: str) -> Counter:
    """Per edge end (`src` or `dst`) id and column, the count of edges with that end that pass that column."""
    return Counter((edge[end], c) for edge, edge_columns in zip(edges, columns) for c in edge_columns)


def get_lane_column(lane_id: str) -> int:
    return int(lane_id.split(":")[1])


def add_lanes(columns: list[list[list[str]]], nodes: dict[str, dict], edges: list[dict],
              lanes: list[list[str]]) -> None:
    """A lane card per lane id, at the mean of its edges' mean source y and mean target y."""
    ends: dict[str, tuple[list[str], list[str]]] = {}
    for edge, lane_ids in zip(edges, lanes):
        for lane_id in lane_ids:
            srcs, dsts = ends.setdefault(lane_id, ([], []))
            srcs.append(edge["src"])
            dsts.append(edge["dst"])
    for lane_id, (srcs, dsts) in ends.items():
        add_lane(columns[get_lane_column(lane_id)], nodes, lane_id,
                 (get_mean_y(nodes, srcs) + get_mean_y(nodes, dsts)) / 2)


def split_edges(edges: list[dict], usage: list[int], lanes: list[list[str]]) -> tuple[list[dict], list[int]]:
    """Each edge as links from its source through its lanes to its target, each link with the edge's usage."""
    links: list[dict] = []
    link_usage: list[int] = []
    for edge, paths, lane_ids in zip(edges, usage, lanes):
        points = [edge["src"], *lane_ids, edge["dst"]]
        links += [{"src": a, "dst": b} for a, b in zip(points, points[1:])]
        link_usage += [paths] * (len(points) - 1)
    return links, link_usage


def get_mean_y(nodes: dict[str, dict], ids: list[str]) -> float:
    return sum(nodes[i]["y"] for i in ids) / len(ids)


def add_lane(blocks: list[list[str]], nodes: dict[str, dict], lane_id: str, y: float) -> None:
    """The lane joins the block whose cards sit nearest its y, the first on a tie; the pull then sorts it in."""
    distance = {k: get_block_distance([nodes[i] for i in block], y) for k, block in enumerate(blocks)}
    x = nodes[blocks[0][0]]["x"]
    nodes[lane_id] = {"id": lane_id, "kind": LANE_KIND, "mds": [], "x": x, "y": y}
    blocks[min(distance, key=distance.get)].append(lane_id)


def get_block_distance(cards: list[dict], y: float) -> float:
    """0 when y lies between the block's highest top and lowest bottom, else the distance to the nearer."""
    top = min(card["y"] for card in cards)
    bottom = max(card["y"] + get_card_height(card) for card in cards)
    return max(top - y, y - bottom, 0)


def get_links(edges: list[dict]) -> dict[str, list[str]]:
    """Linked cards per card, both edge ways, self edges left out."""
    links: dict[str, list[str]] = {}
    for edge in edges:
        if edge["src"] != edge["dst"]:
            links.setdefault(edge["src"], []).append(edge["dst"])
            links.setdefault(edge["dst"], []).append(edge["src"])
    return links


def get_callers(edges: list[dict]) -> dict[str, set[str]]:
    callers: dict[str, set[str]] = {}
    for edge in edges:
        if edge["src"] != edge["dst"]:
            callers.setdefault(edge["dst"], set()).add(edge["src"])
    return callers


def pull_linked_cards(columns: list[list[list[str]]], nodes: dict[str, dict], links: dict[str, list[str]]) -> None:
    """Rubber bands: each edge pulls the tops of its two cards toward the same height. Sweeps alternate left to
    right and right to left; each block re-sorts its cards by wanted y, blocks keep their stack order, then the column
    keeps the row gap."""
    for sweep in range(RELAX_SWEEPS):
        for blocks in columns if sweep % 2 == 0 else reversed(columns):
            ids = [i for block in blocks for i in block]
            wanted = {i: sum(nodes[j]["y"] for j in links[i]) / len(links[i]) if i in links else nodes[i]["y"]
                      for i in ids}
            for block in blocks:
                block.sort(key=lambda i: wanted[i])
            set_column_ys(blocks, nodes, wanted)


def set_column_ys(blocks: list[list[str]], nodes: dict[str, dict], wanted: dict[str, float]) -> None:
    ids = [i for block in blocks for i in block]
    heights = [get_card_height(nodes[i]) for i in ids]
    for i, y in zip(ids, get_packed_ys(heights, [wanted[i] for i in ids], [0] * len(ids))):
        nodes[i]["y"] = y


def improve_columns(columns: list[list[list[str]]], nodes: dict[str, dict], edges: list[dict],
                    usage: list[int]) -> None:
    """Each column becomes a packed stack; then sweeps alternate left to right and right to left until a sweep
    changes no column or the column orders repeat those after an earlier sweep the same way, each column taking its
    best order (`improve_column`); last, each column packs once more on fresh wishes. `usage`: paths per edge."""
    weights = get_link_weights(edges, usage)
    callers = get_callers(edges)
    scorers = [ColumnScorer(blocks, nodes, weights, callers) for blocks in columns]
    refresh_ys(columns, scorers)
    sweep_columns(columns, scorers)
    refresh_ys(columns, scorers)


def refresh_ys(columns: list[list[list[str]]], scorers: list["ColumnScorer"]) -> None:
    """Left to right, each column packs its order on the wishes of the other columns' current ys."""
    # rule: left to right: a single caller left of its card packs first. One right of it (mod calls command) can
    # still move after; accepted, one pass only.
    for blocks, scorer in zip(columns, scorers):
        scorer.start_turn()
        scorer.set_ys(blocks)


def sweep_columns(columns: list[list[list[str]]], scorers: list["ColumnScorer"]) -> None:
    pairs, seen = list(zip(columns, scorers)), set()
    for sweep in range(POLISH_PASSES):
        if not any([improve_column(blocks, scorer) for blocks, scorer in (pairs if sweep % 2 == 0 else pairs[::-1])]):
            return
        # rule: packed stacks move cards between sweeps, so orders can cycle; a repeat only repeats work.
        state = (sweep % 2, str(columns))
        if state in seen:
            return
        seen.add(state)


def get_link_weights(edges: list[dict], usage: list[int]) -> dict[str, dict[str, int]]:
    """Per card, per linked card: the paths that cross the edges between them, plus 1 per edge so an unused edge
    still pulls."""
    weights: dict[str, dict[str, int]] = {}
    for edge, paths in zip(edges, usage):
        if edge["src"] != edge["dst"]:
            for a, b in ((edge["src"], edge["dst"]), (edge["dst"], edge["src"])):
                weights.setdefault(a, {})[b] = weights.get(a, {}).get(b, 0) + paths + 1
    return weights


def improve_column(blocks: list[list[str]], scorer: "ColumnScorer") -> bool:
    """Greedy: move a run of neighbor cards (with the lanes under them) or one lane to another place in its block
    when that lowers the column score most; repeat until no move helps. True when the column changed."""
    scorer.start_turn()
    start = best = [list(block) for block in blocks]
    while True:
        scorer.set_current(best)
        if (found := find_better_order(best, scorer)) is None:
            break
        best = found
    blocks[:] = best
    scorer.set_ys(blocks)
    return best is not start


def find_better_order(current: list[list[str]], scorer: "ColumnScorer") -> list[list[str]] | None:
    found = min(get_run_moves(current, scorer.nodes), key=scorer.get_score, default=None)
    return found if found and scorer.get_score(found) < scorer.get_score(current) - 0.5 else None


class ColumnScorer:
    """Scores card orders of one packed column against the cards of other columns, which stay put. Every term counts
    once per path that crosses it, so often used edges weigh most."""

    def __init__(self, blocks: list[list[str]], nodes: dict[str, dict], weights: dict[str, dict[str, int]],
                 callers: dict[str, set[str]]):
        self.nodes, self.callers = nodes, callers
        ids = [i for block in blocks for i in block]
        self.outside = {i: get_outside_links(weights.get(i, {}), ids) for i in ids}
        self.neighbors = {i: self.get_neighbor_links(i) for i in ids}
        self.use = {i: get_use(weights.get(i, {}), callers.get(i, set())) for i in ids}
        self.set_pack_facts(ids)
        self.start_turn()

    def set_pack_facts(self, ids: list[str]) -> None:
        """Facts no turn changes: single callers, heights, and order ranks and sibling gains of each two cards with
        a shared caller."""
        self.single_caller = {i: self.get_outside_single_caller(i, ids) for i in ids}
        self.heights = {i: get_card_height(self.nodes[i]) for i in ids}
        self.ranked = self.get_ranked_pairs(ids)
        self.sibling_gains = self.get_sibling_gains(ids)

    def get_neighbor_links(self, node_id: str) -> list[tuple[str, int]]:
        """Links to cards in the column right next to this one, left or right."""
        x = self.nodes[node_id]["x"]
        return [(j, w) for j, w in self.outside[node_id] if abs(self.nodes[j]["x"] - x) == COLUMN_WIDTH]

    def start_turn(self) -> None:
        """Scores, crossing costs and median wishes hold the other columns' y values of this turn only."""
        self.scores: dict[tuple[str, ...], float] = {}
        self.outside_ys = {i: [(self.nodes[j]["y"], w) for j, w in links] for i, links in self.outside.items()}
        self.wishes = {i: self.nodes[c]["y"] if (c := self.single_caller[i]) else
                       get_weighted_median(wishes) if wishes else None for i, wishes in self.outside_ys.items()}
        self.set_crossings()
        self.current: OrderFacts | None = None

    def set_crossings(self) -> None:
        """Crossing cost of each two cards, upper first: as pairs that cost, and as a full table by upper card."""
        self.crossings: dict[tuple[str, str], float] = {
            (a, b): cost for a in self.neighbors for b in self.neighbors
            if a != b and (cost := self.get_crossing_cost(a, b))}
        self.crossings_with = {a: {b: self.crossings.get((a, b), 0) for b in self.neighbors} for a in self.neighbors}

    def set_current(self, blocks: list[list[str]]) -> None:
        """Later scores pack and count crossings only from where an order first differs from this one."""
        ids = get_ids(blocks)
        targets, ranks, tight = self.get_pack_inputs(ids)
        stacks: list[list[Block]] = [[]]
        for k in range(len(ids)):
            stacks.append(pack_blocks(stacks[-1], range(k, k + 1), targets, ranks, tight))
        first_target = next((k for k, t in enumerate(self.get_targets(ids)) if t is not None), len(ids))
        self.current = OrderFacts(ids, first_target, self.get_full_crossed_cost(ids), stacks)

    def get_crossing_cost(self, upper: str, lower: str) -> float:
        """CROSSING_COST per path of both edges, per two edges to cards in one neighbor column that cross when
        `upper` sits above `lower`: the other end of the upper card's edge sits lower. Edges that share a card never
        cross."""
        return sum(CROSSING_COST * (w + v) for j, w in self.neighbors[upper] for k, v in self.neighbors[lower]
                   if j != k and self.nodes[j]["x"] == self.nodes[k]["x"] and self.nodes[j]["y"] > self.nodes[k]["y"])

    def get_ranked_pairs(self, ids: list[str]) -> list[tuple[str, str, int]]:
        """Each two cards with a shared caller, more used first, with their use difference."""
        return [(a, b, self.use[a] - self.use[b]) for a in ids for b in ids
                if self.use[a] > self.use[b] and self.share_caller(a, b)]

    def set_ys(self, blocks: list[list[str]]) -> None:
        for node_id, y in self.get_ys(blocks).items():
            self.nodes[node_id]["y"] = y

    def get_ys(self, blocks: list[list[str]]) -> dict[str, float]:
        """Cards in order, at least ROW_GAP apart; where cards collide, the highest-ranked sits on its wanted y
        (`get_ranks`, `get_packed_ys`)."""
        ids = get_ids(blocks)
        targets, ranks, tight = self.get_pack_inputs(ids)
        start = self.get_pack_start(ids)
        stack = self.current.stacks[start] if start else []
        return dict(zip(ids, get_block_ys(pack_blocks(stack, range(start, len(ids)), targets, ranks, tight), tight)))

    def get_pack_inputs(self, ids: list[str]) -> tuple[list[float], list[int], list[int]]:
        """Filled targets, ranks and tight ys of the cards in order."""
        heights = [self.heights[i] for i in ids]
        targets = self.get_targets(ids)
        return fill_targets(targets, heights), self.get_ranks(ids, targets), get_tight_ys(heights)

    def get_pack_start(self, ids: list[str]) -> int:
        """Count of top cards that pack as in the current order: those before the first change, when a card above
        the change has a target; otherwise the change back-fills their targets (`fill_targets`). 0 with no current
        order."""
        if self.current is None:
            return 0
        start = get_changed_range(self.current.ids, ids).start
        return start if self.current.first_target < start else 0

    def get_ranks(self, ids: list[str], targets: list[float | None]) -> list[int]:
        """Rank per card in a packed block: -1 with no target; a card level with its single caller above every
        median card, then by use; a median card by use."""
        return [-1 if target is None else self.use[i] + (LEVEL_RANK if self.single_caller[i] else 0)
                for i, target in zip(ids, targets)]

    def get_targets(self, ids: list[str]) -> list[float | None]:
        """Wanted y per card: a card whose only caller sits in another column wants that caller's y, but only the
        first such card of that caller in column order, a real card before a lane; a later such card of that caller
        wants none and packs tight under the card above; any other card with an edge to another column wants the
        weighted median y of those edges' cards; the rest want none."""
        level: dict[str, str] = {}
        # rule: a lane never takes the level slot from a real card of its source, so a short edge stays straight.
        for i in sorted(ids, key=lambda i: self.nodes[i]["kind"] == LANE_KIND):
            if caller := self.single_caller[i]:
                level.setdefault(caller, i)
        return [self.wishes[i] if level.get(self.single_caller[i], i) == i else None for i in ids]

    def get_outside_single_caller(self, node_id: str, ids: list[str]) -> str | None:
        """The only caller of the card when it sits in another column, else None."""
        callers = self.callers.get(node_id, set())
        return next(iter(callers)) if len(callers) == 1 and callers.isdisjoint(ids) else None

    def get_score(self, blocks: list[list[str]]) -> float:
        order = tuple(i for block in blocks for i in block)
        if order not in self.scores:
            self.scores[order] = self.get_order_score(blocks)
        return self.scores[order]

    def get_order_score(self, blocks: list[list[str]]) -> float:
        """Per edge to another column, its height less LEVEL_GAIN when level; less the sibling gain of each two
        neighbor cards with a shared caller; plus ORDER_COST per path of difference where a less used card sits above
        a more used one with the same caller; plus the crossing cost of each two cards, upper first. Edge terms count
        per crossing path."""
        ys = self.get_ys(blocks)
        edges = sum(w * (abs(y - v) or -LEVEL_GAIN) for i, y in ys.items() for v, w in self.outside_ys[i])
        ids = list(ys)
        siblings = sum(self.sibling_gains.get(pair, 0) for pair in zip(ids, ids[1:]))
        flipped = sum(diff for a, b, diff in self.ranked if ys[a] > ys[b])
        return edges - siblings + ORDER_COST * flipped + self.get_crossed_cost(ids)

    def get_crossed_cost(self, ids: list[str]) -> float:
        """Crossing cost of each two cards, upper first. An order that swaps two neighbor parts of the current order
        (each polish move) changes only the pairs of one card from each part."""
        parts = self.get_swapped_parts(ids)
        if parts is None:
            return self.get_full_crossed_cost(ids)
        upper, lower = parts
        crossings = self.crossings_with
        return self.current.crossed + sum(crossings[b][a] - crossings[a][b] for a in upper for b in lower)

    def get_swapped_parts(self, ids: list[str]) -> tuple[list[str], list[str]] | None:
        """The upper and lower part of the current order that swap places in this order; None with no current
        order or another change."""
        if self.current is None:
            return None
        old, window = self.current.ids, get_changed_range(self.current.ids, ids)
        split = old.index(ids[window.start], window.start, window.stop) if window else window.start
        upper, lower = old[window.start:split], old[split:window.stop]
        return (upper, lower) if ids[window.start:window.stop] == lower + upper else None

    def get_full_crossed_cost(self, ids: list[str]) -> float:
        place = {i: k for k, i in enumerate(ids)}
        return sum(cost for (a, b), cost in self.crossings.items() if place[a] < place[b])

    def get_sibling_gains(self, ids: list[str]) -> dict[tuple[str, str], float]:
        """Sibling gain of each two cards with a shared caller, both ways."""
        return {(a, b): self.get_sibling_gain(a, b) for a in ids for b in ids if a != b and self.share_caller(a, b)}

    def get_sibling_gain(self, a: str, b: str) -> float:
        """SIBLING_GAIN per path into the less used card, at least SIBLING_FLOOR."""
        return max(SIBLING_GAIN * min(self.use[a], self.use[b]), SIBLING_FLOOR)

    def share_caller(self, a: str, b: str) -> bool:
        return bool(self.callers.get(a, set()) & self.callers.get(b, set()))


def get_outside_links(weights: dict[str, int], ids: list[str]) -> list[tuple[str, int]]:
    """Linked cards outside the column, with their weights."""
    return [(j, w) for j, w in weights.items() if j not in ids]


def get_use(weights: dict[str, int], callers: set[str]) -> int:
    """Weights of the edges into a card from its callers."""
    return sum(weights.get(c, 0) for c in callers)


def get_weighted_median(wishes: list[tuple[float, int]]) -> float:
    """First value at which the weights reach half the total; 0 for no wishes."""
    half, total = sum(w for _, w in wishes) / 2, 0
    for value, weight in sorted(wishes):
        total += weight
        if total >= half:
            return value
    return 0


def get_run_moves(blocks: list[list[str]], nodes: dict[str, dict]):
    """Orders with one change in one block: a run of neighbor units (a card plus the lanes right under it; lanes in a
    row at the block top are one unit) at another place, or one lane alone at another place. Units keep the run
    moves to the count of cards, not of cards and lanes."""
    for b, block in enumerate(blocks):
        for order in get_block_moves(block, nodes):
            yield blocks[:b] + [order] + blocks[b + 1:]


def get_block_moves(block: list[str], nodes: dict[str, dict]):
    units = get_units(block, nodes)
    for start, end in ((s, e) for s in range(len(units)) for e in range(s + 1, len(units) + 1)):
        for moved in get_moved(units, start, end):
            yield [i for unit in moved for i in unit]
    for k, lane in enumerate(block):
        if nodes[lane]["kind"] == LANE_KIND:
            for moved in get_moved(block, k, k + 1):
                yield moved


def get_moved(items: list, start: int, end: int):
    """Each order of `items` with the run `start`..`end` at another place."""
    run, rest = items[start:end], items[:start] + items[end:]
    return (rest[:place] + run + rest[place:] for place in range(len(rest) + 1) if place != start)


def get_units(block: list[str], nodes: dict[str, dict]) -> list[list[str]]:
    """A card and the lanes right under it as one unit; lanes in a row at the block top form one unit. Each lane still
    moves alone (get_block_moves), and fewer units keep the move count low."""
    units: list[list[str]] = []
    for i in block:
        if units and nodes[i]["kind"] == LANE_KIND:
            units[-1].append(i)
        else:
            units.append([i])
    return units


def set_top_to_zero(nodes: dict[str, dict]) -> None:
    top = min((n["y"] for n in nodes.values()), default=0)
    for n in nodes.values():
        n["y"] = round(n["y"] - top)


def set_edge_lanes(edges: list[dict], nodes: dict[str, dict], lanes: list[list[str]]) -> None:
    """Each edge that passes columns gets `lanes`: its lane y per passed column, left to right."""
    for edge, lane_ids in zip(edges, lanes):
        if lane_ids:
            edge["lanes"] = [nodes[lane_id]["y"] for lane_id in lane_ids]


def fill_targets(targets: list[float | None], heights: list[int]) -> list[float]:
    """A card that wants no y wants tight under the card above; above the first wanted y, tight over the card
    below. A column where no card wants a y starts at 0."""
    first = next((k for k, t in enumerate(targets) if t is not None), 0)
    filled = list(targets)
    if filled and filled[first] is None:
        filled[first] = 0.0
    for k in range(first, 0, -1):
        filled[k - 1] = filled[k] - (heights[k - 1] + ROW_GAP)
    for k in range(1, len(filled)):
        if filled[k] is None:
            filled[k] = filled[k - 1] + (heights[k - 1] + ROW_GAP)
    return filled


def get_tight_ys(heights: list[int]) -> list[int]:
    """Y of each card in a stack from 0 with ROW_GAP between cards."""
    tight = [0] * len(heights)
    for k in range(1, len(heights)):
        tight[k] = tight[k - 1] + heights[k - 1] + ROW_GAP
    return tight


def is_clear(above_y: float, y: float, gap: float) -> bool:
    """True when a card at y sits at least gap below the one at above_y."""
    # rule: `fill_targets` adds or subtracts the same gap, so test both forms; one rounding must not merge touching cards.
    return above_y + gap <= y or above_y <= y - gap


def get_packed_ys(heights: list[int], targets: list[float], ranks: list[int]) -> list[float]:
    """Y per card, in order, no overlap: a card that would overlap the one above joins its block, and a block sits
    at the mean of its highest-ranked cards' targets less their offsets in the block; equal ranks give least squares."""
    # rule: polish packs per scored order, so merges move no card; offset in block = tight y less anchor card's.
    # rule: anchor = a top-ranked card: a lone top card lands exactly on its target, a level edge stays level.
    tight = get_tight_ys(heights)
    return get_block_ys(pack_blocks([], range(len(heights)), targets, ranks, tight), tight)


def pack_blocks(stack: list[Block], cards: range, targets: list[float], ranks: list[int], tight: list[int]) -> list[Block]:
    """The stack of packed blocks after the cards are added under `stack`, the packed blocks of the cards above."""
    # rule: a card merges only upward, so the stack after the first k cards depends on those cards alone.
    blocks = list(stack)
    for i in cards:
        add_block(blocks, (i, 1, ranks[i], targets[i], 1, i), tight)
    return blocks


def get_block_ys(blocks: list[Block], tight: list[int]) -> list[float]:
    return [total / top + (tight[k] - tight[anchor])
            for first, count, _, total, top, anchor in blocks for k in range(first, first + count)]


def get_changed_range(old: list[str], new: list[str]) -> range:
    """Indexes from the first to the last place where two orders of the same cards differ; empty when equal."""
    lo = next((k for k, (a, b) in enumerate(zip(old, new)) if a != b), len(new))
    if lo == len(new):
        return range(lo, lo)
    hi = next(k for k in range(len(new) - 1, lo - 1, -1) if old[k] != new[k])
    return range(lo, hi + 1)


def add_block(blocks: list[Block], block: Block, tight: list[int]) -> None:
    """Adds the block under the others; it merges with each block above that it would overlap."""
    while blocks:
        above = blocks[-1]
        start = tight[block[5]] - tight[above[5]]
        if is_clear(above[3] / above[4], block[3] / block[4], start):
            break
        block = merge_blocks(blocks.pop(), block, start)
    blocks.append(block)


def merge_blocks(above: Block, below: Block, start: float) -> Block:
    """One block of two packed blocks; the anchor of `below` sits `start` under the anchor of `above`."""
    first, count, rank, total, top, anchor = above
    _, below_count, below_rank, below_total, below_top, below_anchor = below
    if below_rank > rank:
        total, top, anchor = below_total, below_top, below_anchor
    elif below_rank == rank:
        total, top = total + below_total - start * below_top, top + below_top
    return first, count + below_count, max(rank, below_rank), total, top, anchor


def get_card_height(card: dict) -> int:
    if card["kind"] == LANE_KIND:
        return LANE_HEIGHT
    lines = len(card.get("mds", [])) + (1 if card.get("args") else 0) + (1 if card["kind"] == "agent" else 0)
    return CARD_BASE_HEIGHT + LINE_HEIGHT * lines
