"""Fixed-pair placement and AOD readout placement for at most two atoms."""

from dataclasses import dataclass
from itertools import combinations, pairwise, product
from math import hypot

from ..contracts import GateLayer, PlacementPlan
from ..device import Device, Position, Region, SLMSite
from ..physical_ir import PhysicalDAG
from ..state import (
    COORDINATE_TOLERANCE,
    AODGrid,
    AODHolder,
    AODLine,
    AtomLayout,
    AtomState,
    SLMHolder,
)
from .global_rotation import global_rotation_assignments


@dataclass(frozen=True, slots=True)
class PairPlacer:
    """Place one atom pair on fixed SLM traps and read out atoms in an AOD.

    Args:
        aod_id: Transport device used to reach gate and readout positions.
    """

    aod_id: str

    def place(
        self,
        dag: PhysicalDAG,
        layer: GateLayer,
        layout: AtomLayout,
        device: Device,
        *,
        reuse_qubits: tuple[int, ...] = (),
        following: GateLayer | None = None,
        retained_atoms: tuple[AtomState, ...] = (),
    ) -> PlacementPlan:
        """Choose execution and exit positions for a homogeneous gate layer.

        Args:
            dag: Native physical operations.
            layer: Selected homogeneous operation IDs.
            layout: Current arrangement of at most two atoms.
            device: Geometry and operation capabilities.
            reuse_qubits: Accepted interface hint; this strategy retains gate
                positions whenever they remain useful without moving atoms.
            following: Accepted next-layer hint; this baseline uses current positions.
            retained_atoms: Accepted interface snapshots; this one-pair helper
                chooses positions directly.

        Returns:
            Execution and exit layouts. Readout returns atoms to their entry
            arrangement; gates retain their selected execution arrangement.

        Raises:
            ValueError: If the required capability or placement is unavailable.
        """
        if not layer.operation_ids:
            return PlacementPlan(layout, layout)
        operation = dag.nodes[layer.operation_ids[0]]
        if operation.name == "cz":
            atom_ids = tuple(layout.qubit_to_atom[q] for q in operation.qubits)
            execution = self._place_cz(layout, device, atom_ids)
        elif operation.name == "measure":
            atom_id = layout.qubit_to_atom[operation.qubits[0]]
            execution = self._place_measurement(layout, device, atom_id)
            return PlacementPlan(execution, layout)
        elif operation.name == "global_ry":
            replacements = global_rotation_assignments(
                dag, layer, layout, device, self.aod_id
            )
            execution = (
                self._replace_atoms(layout, replacements) if replacements else layout
            )
        elif operation.name in ("rx", "ry", "rz", "u", "reset"):
            execution = self._place_local(dag, layer, layout, device)
        else:
            raise ValueError(f"Unsupported placement operation {operation.name!r}.")
        return PlacementPlan(execution, execution)

    def _place_cz(
        self, layout: AtomLayout, device: Device, atom_ids: tuple[int, ...]
    ) -> AtomLayout:
        capability = device.cz
        if capability is None or ("slm", "slm") not in capability.holder_pairs:
            raise ValueError("Pair placement requires an SLM-SLM CZ capability.")
        workspace = device.aod(self.aod_id).workspace
        sites = [
            site
            for site in device.slm_sites
            if workspace.contains(site.position)
            and device.zones_at(site.position, "cz")
        ]
        candidates: list[tuple[float, str, str, SLMSite, SLMSite]] = []
        first, second = (layout.atom(atom_id) for atom_id in atom_ids)
        for left, right in combinations(sites, 2):
            if not 0 < _distance(left.position, right.position) <= capability.radius_um:
                continue
            if not any(
                "cz" in zone.operations
                and zone.bounds.contains(left.position)
                and zone.bounds.contains(right.position)
                for zone in device.zones
            ):
                continue
            for a, b in ((left, right), (right, left)):
                cost = _distance(first.position, a.position) + _distance(
                    second.position, b.position
                )
                candidates.append((cost, a.id, b.id, a, b))
        if not candidates:
            raise ValueError("No reachable SLM pair supports CZ in a common zone.")
        _, _, _, first_site, second_site = min(candidates, key=lambda item: item[:3])
        return self._replace_atoms(
            layout,
            {
                first.id: _at_site(first.id, first_site),
                second.id: _at_site(second.id, second_site),
            },
        )

    def _place_local(
        self, dag: PhysicalDAG, layer: GateLayer, layout: AtomLayout, device: Device
    ) -> AtomLayout:
        capability = device.local
        if capability is None:
            raise ValueError("A local-control capability is required.")
        workspace = device.aod(self.aod_id).workspace
        replacements: dict[int, AtomState] = {}
        for operation_id in layer.operation_ids:
            operation = dag.nodes[operation_id]
            atom_id = layout.qubit_to_atom[operation.qubits[0]]
            atom = layout.atom(atom_id)
            operation_name = "reset" if operation.name == "reset" else "rotate"
            holder_name = "slm" if isinstance(atom.holder, SLMHolder) else "aod"
            if holder_name in capability.holders and device.zones_at(
                atom.position, operation_name
            ):
                continue
            if "slm" not in capability.holders:
                raise ValueError("No supported SLM placement for local control.")
            occupied = {
                replacements.get(other.id, other).position
                for other in layout.atoms
                if other.id != atom_id
            }
            sites = [
                site
                for site in device.slm_sites
                if site.position not in occupied
                and workspace.contains(site.position)
                and device.zones_at(site.position, operation_name)
            ]
            if not sites:
                raise ValueError("No vacant SLM site permits the local operation.")
            selected = min(
                sites,
                key=lambda site: (_distance(atom.position, site.position), site.id),
            )
            replacements[atom_id] = _at_site(atom_id, selected)
        return self._replace_atoms(layout, replacements) if replacements else layout

    def _place_measurement(
        self, layout: AtomLayout, device: Device, atom_id: int
    ) -> AtomLayout:
        capability = device.readout
        if (
            capability is None
            or "aod" not in capability.holders
            or not capability.retain_atoms
        ):
            raise ValueError("This strategy requires retained-atom AOD readout.")
        workspace = device.aod(self.aod_id).workspace
        atom = layout.atom(atom_id)
        candidates: set[Position] = set()
        regions = []
        for zone in device.zones:
            if "measure" in zone.operations:
                bounds = _intersection(zone.bounds, workspace)
                if bounds is not None:
                    regions.append(bounds)
                    candidates.update(_readout_candidates(bounds, atom.position))
        stationary = tuple(
            other.position for other in layout.atoms if other.id != atom_id
        )
        candidates = {
            point
            for point in candidates
            if all(
                _distance(point, other) >= capability.min_spacing_um
                and _distance(point, other) > COORDINATE_TOLERANCE
                for other in stationary
            )
        }
        if not candidates:
            for bounds in regions:
                xs = _axis_options(
                    (atom.position.x,),
                    bounds.x_min,
                    bounds.x_max,
                    max(device.aod(self.aod_id).min_spacing, capability.min_spacing_um),
                    tuple(point.x for point in stationary),
                )
                ys = _axis_options(
                    (atom.position.y,),
                    bounds.y_min,
                    bounds.y_max,
                    max(device.aod(self.aod_id).min_spacing, capability.min_spacing_um),
                    tuple(point.y for point in stationary),
                )
                for x, y in product(xs, ys):
                    point = Position(x[0], y[0])
                    if all(
                        _distance(point, other) >= capability.min_spacing_um
                        and _distance(point, other) > COORDINATE_TOLERANCE
                        for other in stationary
                    ):
                        candidates.add(point)
        if not candidates:
            raise ValueError("No reachable readout position meets readout spacing.")
        target = min(
            candidates,
            key=lambda point: (_distance(atom.position, point), point.x, point.y),
        )
        grid = AODGrid(self.aod_id, (AODLine(0, target.y),), (AODLine(0, target.x),))
        return self._replace_atoms(
            layout,
            {atom_id: AtomState(atom_id, target, AODHolder(self.aod_id, 0, 0))},
            grid,
        )

    def _replace_atoms(
        self,
        layout: AtomLayout,
        replacements: dict[int, AtomState],
        grid: AODGrid | None = None,
    ) -> AtomLayout:
        atoms = tuple(replacements.get(atom.id, atom) for atom in layout.atoms)
        grids = list(layout.aod_grids)
        if grid is None and not any(
            isinstance(atom.holder, AODHolder) and atom.holder.aod_id == self.aod_id
            for atom in atoms
        ):
            grids = [
                AODGrid(self.aod_id) if item.aod_id == self.aod_id else item
                for item in grids
            ]
        elif grid is not None:
            grids = [item for item in grids if item.aod_id != self.aod_id] + [grid]
        return AtomLayout(atoms, tuple(grids), layout.qubit_to_atom)


def _distance(first: Position, second: Position) -> float:
    return hypot(first.x - second.x, first.y - second.y)


def _at_site(atom_id: int, site: SLMSite) -> AtomState:
    return AtomState(atom_id, site.position, SLMHolder(site.id))


def _intersection(first: Region, second: Region) -> Region | None:
    x_min, y_min = max(first.x_min, second.x_min), max(first.y_min, second.y_min)
    x_max, y_max = min(first.x_max, second.x_max), min(first.y_max, second.y_max)
    return (
        Region(x_min, y_min, x_max, y_max)
        if x_min <= x_max and y_min <= y_max
        else None
    )


def _readout_candidates(bounds: Region, current: Position) -> tuple[Position, ...]:
    return (
        Position(
            min(max(current.x, bounds.x_min), bounds.x_max),
            min(max(current.y, bounds.y_min), bounds.y_max),
        ),
        Position(bounds.x_min, bounds.y_min),
        Position(bounds.x_min, bounds.y_max),
        Position(bounds.x_max, bounds.y_min),
        Position(bounds.x_max, bounds.y_max),
    )


def _axis_options(
    source: tuple[float, ...],
    low: float,
    high: float,
    spacing: float,
    obstacles: tuple[float, ...] = (),
) -> tuple[tuple[float, ...], ...]:
    """Return monotone axes from source coordinates and finite obstacle events.

    Candidate count depends on active axes and obstacles, never region extent.
    Translate both the source projection and a compact axis through boundaries,
    obstacle coordinates, and intervening free intervals. Endpoint occupancy and
    readout spacing are checked by the caller against the complete atom layout.
    """
    n = len(source)
    if (n - 1) * spacing > high - low + COORDINATE_TOLERANCE:
        return ()
    nearest: list[float] = []
    for index, value in enumerate(source):
        lower = nearest[-1] + spacing if nearest else low
        nearest.append(max(lower, min(value, high - (n - index - 1) * spacing)))
    options = {tuple(nearest), tuple(low + index * spacing for index in range(n))}
    for base in tuple(options):
        minimum, maximum = low - base[0], high - base[-1]
        events = {minimum, maximum, max(minimum, min(0.0, maximum))}
        for value in base:
            for obstacle in obstacles:
                for offset in (-spacing, 0.0, spacing):
                    shift = obstacle - value + offset
                    if minimum <= shift <= maximum:
                        events.add(shift)
        ordered = sorted(events)
        events.update(
            left + (right - left) / 2
            for left, right in pairwise(ordered)
            if right - left > 2 * COORDINATE_TOLERANCE
        )
        options.update(tuple(value + shift for value in base) for shift in events)
    return tuple(
        sorted(
            options,
            key=lambda axis: (
                max(
                    abs(value - origin)
                    for value, origin in zip(axis, source, strict=True)
                ),
                axis,
            ),
        )
    )
