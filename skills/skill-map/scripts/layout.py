"""Places map cards in columns: one band of columns per kind, callers left of callees inside a band; then whole
columns stack under others while that makes edges flow left to right with shorter spans; last, single cards leave
their band's column when that saves more flow cost than the cohesion they lose. Rubber bands then sort each column,
and each column becomes a packed stack (cards in order, gaps allowed, each near its wanted y) in the order that
scores best, with sweeps both ways."""
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
# Polish step gains, in px of edge height, per path.
# rule: page edges join points 18 px below both card tops: level edge = same top.
SIBLING_GAIN = 200  # gain per two neighbor cards in a column with a shared caller
SIBLING_FLOOR = 5000  # least gain of such two cards, so unused siblings still join their group
LEVEL_GAIN = 50  # gain per level edge between two columns
ORDER_COST = 10  # cost per path of difference when a less used card sits above a more used one with the same caller
CROSSING_COST = 100  # cost per crossing of two edges to one neighbor column, per path of both edges
POLISH_PASSES = 20  # most sweeps; the polish stops at the first sweep that changes no column


def apply_layout(data: dict) -> None:
    nodes = {n["id"]: n for n in data["nodes"]}
    children = build_children(data["edges"])
    set_back_edges(data["edges"], children, get_root_ids(nodes))
    layers = build_layers(nodes, data["edges"])
    columns = stack_columns(build_columns(layers, data["edges"]), nodes, data["edges"])
    columns = place_cards(columns, nodes, data["edges"])
    for column, blocks in enumerate(columns):
        set_column_positions(column, [nodes[i] for block in blocks for i in block])
    links = get_links(data["edges"])
    pull_linked_cards(columns, nodes, links)
    improve_columns(columns, nodes, data["edges"])
    set_top_to_zero(nodes)


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
    column = {i: c for c, blocks in enumerate(columns) for block in blocks for i in block}
    spans = [column[dst] - column[src] for src, dst in links]
    return sum(abs(s) + pass_cost * max(abs(s) - 1, 0) + (BACKWARD_COST if s <= 0 else 0) for s in spans)


def place_cards(columns: list[list[list[str]]], nodes: dict[str, dict], edges: list[dict]) -> list[list[list[str]]]:
    """Greedy: move the one card (never a command) to the other column that lowers flow cost less cohesion gain
    most, while no column grows past the tallest column; repeat until no move helps."""
    limit = max((get_stack_height(c, nodes) for c in columns), default=0)
    links = [(e["src"], e["dst"]) for e in edges if e["src"] != e["dst"]]
    band = {i: get_band(n) for i, n in nodes.items()}
    score = lambda cols: get_flow_cost(cols, links, PASS_COST) - COHESION_GAIN * get_cohesion(cols, band)
    while True:
        best, best_score = None, score(columns)
        for node_id in sorted(i for i, n in nodes.items() if n["kind"] != "command"):
            for target in range(len(columns)):
                trial = move_card(columns, node_id, target, links)
                if trial is None or get_stack_height(get_column_of(trial, node_id), nodes) > limit:
                    continue
                trial_score = score(trial)
                if trial_score < best_score:
                    best, best_score = trial, trial_score
        if best is None:
            return columns
        columns = best


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


def get_column_of(columns: list[list[list[str]]], node_id: str) -> list[list[str]]:
    return next(blocks for blocks in columns if any(node_id in block for block in blocks))


def set_column_positions(column: int, cards: list[dict]) -> None:
    y = 0
    for card in cards:
        card["x"], card["y"] = column * COLUMN_WIDTH, y
        y += get_card_height(card) + ROW_GAP


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
    for i, y in zip(ids, get_packed_ys([get_card_height(nodes[i]) for i in ids], [wanted[i] for i in ids])):
        nodes[i]["y"] = y


def improve_columns(columns: list[list[list[str]]], nodes: dict[str, dict], edges: list[dict]) -> None:
    """Each column becomes a packed stack; then sweeps alternate left to right and right to left until a sweep
    changes no column or the column orders repeat those after an earlier sweep the same way, each column taking its
    best order (`improve_column`)."""
    weights = get_link_weights(edges, get_edge_usage(nodes, edges))
    callers = get_callers(edges)
    scorers = [ColumnScorer(blocks, nodes, weights, callers) for blocks in columns]
    for blocks, scorer in zip(columns, scorers):
        scorer.start_turn()
        scorer.set_ys(blocks)
    sweep_columns(columns, scorers)


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
    """Greedy: move a run of neighbor cards to another place in their block when that lowers the column score most;
    repeat until no move helps. True when the column changed."""
    scorer.start_turn()
    start = best = [list(block) for block in blocks]
    while (found := find_better_order(best, scorer)) is not None:
        best = found
    blocks[:] = best
    scorer.set_ys(blocks)
    return best is not start


def find_better_order(current: list[list[str]], scorer: "ColumnScorer") -> list[list[str]] | None:
    found = min(get_run_moves(current), key=scorer.get_score, default=None)
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
        self.crossings: dict[tuple[str, str], float] = {
            (a, b): cost for a in self.neighbors for b in self.neighbors
            if a != b and (cost := self.get_crossing_cost(a, b))}

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
        """Cards in order, at least ROW_GAP apart, each as near its wanted y as the column allows (`get_packed_ys`)."""
        ids = [i for block in blocks for i in block]
        heights = [self.heights[i] for i in ids]
        return dict(zip(ids, get_packed_ys(heights, fill_targets(self.get_targets(ids), heights))))

    def get_targets(self, ids: list[str]) -> list[float | None]:
        """Wanted y per card: a card whose only caller sits in another column wants that caller's y, but only the
        first such card of that caller in column order; any other card with an edge to another column wants the
        weighted median y of those edges' cards; the rest want none."""
        targets: list[float | None] = []
        leveled: set[str] = set()
        for i in ids:
            caller = self.single_caller[i]
            targets.append(None if caller in leveled else self.wishes[i])
            if caller:
                leveled.add(caller)
        return targets

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
        """Crossing cost of each two cards, upper first."""
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


def get_run_moves(blocks: list[list[str]]):
    for b, block in enumerate(blocks):
        for start, end in ((s, e) for s in range(len(block)) for e in range(s + 1, len(block) + 1)):
            run, rest = block[start:end], block[:start] + block[end:]
            for place in (p for p in range(len(rest) + 1) if p != start):
                yield blocks[:b] + [rest[:place] + run + rest[place:]] + blocks[b + 1:]


def set_top_to_zero(nodes: dict[str, dict]) -> None:
    top = min((n["y"] for n in nodes.values()), default=0)
    for n in nodes.values():
        n["y"] = round(n["y"] - top)


def fill_targets(targets: list[float | None], heights: list[int]) -> list[float]:
    """A card that wants no y wants tight under the card above; above the first wanted y, tight over the card
    below. A column where no card wants a y starts at 0."""
    first = next((k for k, t in enumerate(targets) if t is not None), 0)
    filled = list(targets)
    if filled and filled[first] is None:
        filled[first] = 0.0
    for k in range(first, 0, -1):
        filled[k - 1] = filled[k] - heights[k - 1] - ROW_GAP
    for k in range(1, len(filled)):
        if filled[k] is None:
            filled[k] = filled[k - 1] + heights[k - 1] + ROW_GAP
    return filled


def get_tight_ys(heights: list[int]) -> list[int]:
    """Y of each card in a stack from 0 with ROW_GAP between cards."""
    tight = [0] * len(heights)
    for k in range(1, len(heights)):
        tight[k] = tight[k - 1] + heights[k - 1] + ROW_GAP
    return tight


def get_packed_ys(heights: list[int], targets: list[float]) -> list[float]:
    """Least-squares y per card, in order, no overlap: a card that would overlap the one above joins its block, and
    a block sits at the mean of its cards' targets less their offsets in the block."""
    # rule: polish packs per scored order, so merges move no card; offset in block = tight y less first card's.
    tight = get_tight_ys(heights)
    # per block, top block first: first card, sum of its cards' targets less their offsets, card count
    blocks: list[tuple[int, float, int]] = []
    for i, target in enumerate(targets):
        first, total, count = i, target, 1
        while blocks:
            above, above_total, above_count = blocks[-1]
            start = tight[first] - tight[above]
            if above_total / above_count + start <= total / count:
                break
            blocks.pop()
            first, total, count = above, above_total + total - start * count, above_count + count
        blocks.append((first, total, count))
    return [total / count + (tight[k] - tight[first])
            for first, total, count in blocks for k in range(first, first + count)]


def get_card_height(card: dict) -> int:
    lines = len(card.get("mds", [])) + (1 if card.get("args") else 0) + (1 if card["kind"] == "agent" else 0)
    return CARD_BASE_HEIGHT + LINE_HEIGHT * lines
