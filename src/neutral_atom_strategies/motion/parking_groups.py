"""Exact minimum compatible-group partition for up to 16 source rows/columns.

0 is a wildcard, 2 must align, 1 must avoid alignment. A group is compatible
iff the union of its targets is disjoint from the union of its fixed atoms.
Minimum conflict-graph coloring minimizes captures within this template family.
"""


def compatible_groups(cells, rowwise=True):
    if (not isinstance(cells,list) or not 1<=len(cells)<=16 or not isinstance(cells[0],list)
        or not 1<=len(cells[0])<=16 or any(not isinstance(r,list) or len(r)!=len(cells[0])
        or any(type(v) is not int or v not in (0,1,2) for v in r) for r in cells)):
        raise ValueError('Compatible grouping requires a rectangular 1..16 by 1..16 ternary mask')
    lines = cells if rowwise else list(map(list, zip(*cells)))
    sources = [i for i, line in enumerate(lines) if 2 in line]
    if len(sources) > 16:
        raise ValueError('Exact compatible grouping supports at most 16 target lines')
    targets = [sum(1 << c for c, value in enumerate(lines[i]) if value == 2) for i in sources]
    fixed = [sum(1 << c for c, value in enumerate(lines[i]) if value == 1) for i in sources]
    n = len(sources)
    adjacency = [{j for j in range(n) if targets[i] & fixed[j] or targets[j] & fixed[i]} for i in range(n)]
    colors = [-1] * n
    def choose():
        return max((i for i in range(n) if colors[i] < 0),
                   key=lambda i: (len({colors[j] for j in adjacency[i] if colors[j] >= 0}), len(adjacency[i]), -i))
    for _ in range(n):
        i = choose(); used = {colors[j] for j in adjacency[i]}
        colors[i] = next(c for c in range(n) if c not in used)
    best = colors[:]; count = max(best, default=-1) + 1; nodes = 0
    colors = [-1] * n
    def search(done, used):
        nonlocal best, count, nodes
        nodes += 1
        if used >= count:
            return
        if done == n:
            best = colors[:]; count = used
            return
        i = choose(); forbidden = {colors[j] for j in adjacency[i]}
        for c in range(min(used + 1, count)):
            if c in forbidden:
                continue
            colors[i] = c
            search(done + 1, max(used, c + 1))
        colors[i] = -1
    if n:
        search(0, 0)
    groups = sorted(([sources[i] for i in range(n) if best[i] == c] for c in range(count)), key=lambda g: g[0])
    return {'groups': groups, 'batches': count, 'exact': True, 'search_nodes': nodes,
            'skipped': [i for i in range(len(lines)) if i not in sources]}


def analyze(cells):
    row = compatible_groups(cells, True); column = compatible_groups(cells, False)
    # Deterministic tie-break; no claim to minimizing transport among all colorings.
    selected = 'row' if row['batches'] <= column['batches'] else 'column'
    return {'row': row, 'column': column, 'selected_axis': selected,
            'objective': 'minimum captures; row first on ties; whole-line template only'}
