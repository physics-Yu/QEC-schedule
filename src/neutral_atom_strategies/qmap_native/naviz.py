"""Strict NAViz reader and immutable author transport-block axis assignment.

Only syntax emitted by the pinned QMAP compiler is accepted. Unknown commands
are errors: this boundary must never drop measurements or gates.
"""
from dataclasses import dataclass
import re

NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
POINT = re.compile(rf'\(({NUMBER}),\s*({NUMBER})\)\s+(\w+)$')


@dataclass(frozen=True)
class Instruction:
    kind: str
    atoms: tuple[str, ...] = ()
    moves: tuple[tuple[str, tuple[float, float]], ...] = ()
    parameters: tuple[float, ...] = ()
    line: int = 0


def parse(code):
    initial, instructions = {}, []
    lines = iter(enumerate(code.splitlines(), 1))
    for number, raw in lines:
        line = raw.strip()
        if not line or line.startswith('//'):
            continue
        if line.startswith('atom '):
            m = POINT.fullmatch(line[5:])
            if not m or m[3] in initial:
                raise ValueError(f'Invalid atom declaration at {number}')
            initial[m[3]] = (float(m[1]), float(m[2]))
            continue
        if not line.startswith('@+ '):
            raise ValueError(f'Unsupported NAViz line {number}: {line}')
        kind, _, rest = line[3:].partition(' ')
        if kind not in {'load', 'move', 'store', 'cz', 'u', 'rz'}:
            raise ValueError(f'Unsupported NAViz operation {kind} at {number}')
        parameters = []
        for _ in range(3 if kind == 'u' else 1 if kind == 'rz' else 0):
            value, _, rest = rest.partition(' ')
            parameters.append(float(value))
        entries = [rest]
        if rest == '[':
            entries = []
            for _, value in lines:
                value = value.strip()
                if value == ']':
                    break
                entries.append(value)
            else:
                raise ValueError(f'Unclosed block at {number}')
        if kind == 'move':
            moves = []
            for value in entries:
                m = POINT.fullmatch(value)
                if not m or m[3] not in initial:
                    raise ValueError(f'Invalid move at {number}: {value}')
                moves.append((m[3], (float(m[1]), float(m[2]))))
            instructions.append(Instruction(kind, moves=tuple(moves), line=number))
        else:
            atoms = tuple(entries) if kind != 'cz' else ()
            if any(q not in initial for q in atoms):
                raise ValueError(f'Unknown or global atom target at {number}: {atoms}')
            instructions.append(Instruction(kind, atoms, parameters=tuple(parameters), line=number))
    if not initial:
        raise ValueError('NAViz has no initial atoms')
    return initial, tuple(instructions)


def transport_blocks(initial, instructions):
    """Analyze co-loaded coordinate equality/order once per author batch.

    Slots do not change while atoms are carried. This is a constraint adapter,
    not a new grouping/router: author's load/store/move sequence stays intact.
    """
    positions = dict(initial)
    loaded, snapshots, start = set(), [], None
    blocks = {}
    for index, op in enumerate(instructions):
        if op.kind == 'load':
            if not loaded:
                start, snapshots = index, []
            if loaded.intersection(op.atoms):
                raise ValueError('Author loaded an already carried atom')
            loaded.update(op.atoms)
        elif op.kind == 'move':
            if not set(dict(op.moves)).issubset(loaded):
                raise ValueError('Author moved an atom outside AOD')
            positions.update(op.moves)
        if loaded:
            snapshots.append({q: positions[q] for q in loaded})
        if op.kind == 'store':
            if not set(op.atoms).issubset(loaded):
                raise ValueError('Author stored an atom outside AOD')
            loaded.difference_update(op.atoms)
            if not loaded:
                axes = tuple(_assign_axis(snapshots, dimension) for dimension in (0, 1))
                for i in range(start, index + 1):
                    blocks[i] = axes
    if loaded:
        raise ValueError('Author output leaves AOD loaded')
    return blocks


def _assign_axis(snapshots, dimension):
    qs = sorted({q for snapshot in snapshots for q in snapshot})
    parent = {q: q for q in qs}
    def root(q):
        while parent[q] != q:
            parent[q] = parent[parent[q]]
            q = parent[q]
        return q
    for snapshot in snapshots:
        values = {}
        for q, point in snapshot.items():
            coordinate = point[dimension]
            if coordinate in values:
                parent[root(q)] = root(values[coordinate])
            else:
                values[coordinate] = q
    edges = {root(q): set() for q in qs}
    for snapshot in snapshots:
        groups = {}
        for q, point in snapshot.items():
            r, value = root(q), point[dimension]
            if r in groups and groups[r] != value:
                raise ValueError('Author move requires splitting a shared AOD axis')
            groups[r] = value
        ordered = sorted(groups, key=groups.get)
        for a, b in zip(ordered, ordered[1:]):
            edges[b].add(a)
    order = []
    while edges:
        ready = sorted(k for k, predecessors in edges.items() if not predecessors)
        if not ready:
            raise ValueError('Author batch crosses AOD axes')
        item = ready[0]
        order.append(item)
        del edges[item]
        for predecessors in edges.values():
            predecessors.discard(item)
    return {q: order.index(root(q)) for q in qs}


def capacity_projection(initial, instructions, rows, columns):
    """Project oversized author transport groups onto capacity-sized subgroups.

    No gate/endpoint is generated or changed. Each subgroup executes exactly
    the author's per-atom trajectory; the local environment must still validate
    its changed concurrency, incidental capture and all continuous sweeps.
    """
    positions, loaded, block, out, changes = dict(initial),set(),[],[],[]
    block_start = None
    def project(operations, subset):
        result=[]
        for op in operations:
            atoms=tuple(q for q in op.atoms if q in subset)
            moves=tuple((q,p) for q,p in op.moves if q in subset)
            if atoms or moves:
                result.append(Instruction(op.kind,atoms,moves,op.parameters,op.line))
        return tuple(result)
    def fits(operations):
        bindings=transport_blocks(block_start,operations)
        return all(len(set(x.values()))<=columns and len(set(y.values()))<=rows for x,y in bindings.values())
    for op in instructions:
        if op.kind=='load' and not loaded:
            block_start=dict(positions)
        if op.kind in {'load','move','store'}:
            block.append(op)
            if op.kind=='load':loaded.update(op.atoms)
            elif op.kind=='move':positions.update(op.moves)
            else:loaded.difference_update(op.atoms)
            if not loaded:
                if fits(tuple(block)):
                    out.extend(block)
                else:
                    names=list(dict.fromkeys(q for item in block if item.kind=='load' for q in item.atoms))
                    groups=[];current=[]
                    for q in names:
                        if current and not fits(project(block,set(current+[q]))):
                            groups.append(current);current=[]
                        current.append(q)
                    if current:groups.append(current)
                    for group in groups:out.extend(project(block,set(group)))
                    changes.append(dict(line=block[0].line,author_atoms=names,subgroups=groups,
                        reason='Configured AOD axis capacity; native endpoints and CZ layers unchanged'))
                block=[]
        else:
            if loaded:raise ValueError('Cannot split an author transport containing a gate')
            out.append(op)
    if loaded:raise ValueError('Incomplete author transport')
    return tuple(out),changes
