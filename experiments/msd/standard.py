"""User-selected MSD timing, vertical placement and unbounded-domain convention.

The physical compiler uses finite Region objects. A geometry-derived window is
therefore an execution representation, not a physical area/capacity budget.
Benchmark acceptance additionally checks invariance under window enlargement.
"""

import json
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any

from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import (
    Device,
    PairArray,
    Position,
    Region,
    SLMSite,
    Zone,
    loads_device,
)
from nadit_physical_compiler.serialization import encode_device, encode_layout
from nadit_physical_compiler.state import (
    AtomLayout,
    AtomState,
    SLMHolder,
    validate_layout,
)

from modules.codes.contracts.component import ComponentBinding
from modules.codes.rotated_surface import definition

STANDARD_ID = "nadit.msd.standard/2"
FACTORY_ROLES = ("W1", "W2", "W3", "W4", "W5", "R")
REFERENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "modules/codes/rotated_surface_d3/configs/nonzoned_cnot_reference.json"
)
SITE_PITCH_UM = 10.0
PAIR_SEPARATION_UM = 2.0
HALFPLANE_GAP_UM = 50.0


@dataclass(frozen=True)
class ExperimentSpec:
    """Independent distance/pipeline controls with explicit physical gaps.

    Odd distances and power-of-two pipeline counts are accepted. Gaps and window
    padding are positive micrometers. Resource limits belong to a run manifest.
    """

    distance: int = 3
    pipelines: int = 1
    patch_gap_um: float = 40.0
    factory_gap_um: float = 40.0
    window_padding_um: float = 20.0

    def __post_init__(self) -> None:
        if (
            type(self.distance) is not int
            or self.distance < 3
            or self.distance % 2 != 1
        ):
            raise ValueError("Distance must be an odd integer >= 3.")
        if (
            type(self.pipelines) is not int
            or self.pipelines < 1
            or self.pipelines & (self.pipelines - 1)
        ):
            raise ValueError("Pipeline count must be a positive power of two.")
        for name in ("patch_gap_um", "factory_gap_um", "window_padding_um"):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        if self.patch_gap_um % SITE_PITCH_UM:
            raise ValueError("Patch gap must be a multiple of the 10 um site pitch.")


@dataclass(frozen=True)
class FactoryPatch:
    """One explicitly placed code block and its retained atom identities."""

    factory_index: int
    role: str
    binding: ComponentBinding
    home_sites: tuple[str, ...]


@dataclass(frozen=True)
class ExperimentWorld:
    """An unprepared complete atom world; no parallel execution is implied."""

    spec: ExperimentSpec
    device: Device
    state: AtomLayout
    patches: tuple[FactoryPatch, ...]

    def patch(self, factory_index: int, role: str) -> FactoryPatch:
        """Return one patch; raise KeyError for an absent index/role."""
        for patch in self.patches:
            if (patch.factory_index, patch.role) == (factory_index, role):
                return patch
        raise KeyError((factory_index, role))

    def document(self) -> dict[str, Any]:
        """Export exact physical interfaces and the independent model convention."""
        return {
            "schema": "nadit.msd.world/1",
            "standard": STANDARD_ID,
            "parameters": asdict(self.spec),
            "domain": {
                "coordinates": "Cartesian y increases upward",
                "storage_and_gates": "y <= 0; x and negative y unbounded",
                "readout": "y >= 50 um; x and positive y unbounded",
                "gap_um": HALFPLANE_GAP_UM,
                "execution_window": "finite, geometry-derived; not a hardware budget",
                "readout_count_limit": None,
            },
            "reference_sha256": sha256(REFERENCE_PATH.read_bytes()).hexdigest(),
            "compiler": {"strategy": "nonzoned", "layout": "explicit"},
            "physical_execution": False,
            "device": encode_device(self.device),
            "entry_state": encode_layout(self.state),
            "patches": [asdict(patch) for patch in self.patches],
        }


def reference_device() -> Device:
    """Load the existing d3 CNOT reference without changing its parameters."""
    value = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    return loads_device(json.dumps(generate(value["family"], value["params"])))


def build_world(spec: ExperimentSpec) -> ExperimentWorld:
    """Place N six-block factories from top to bottom below y=0.

    Retains existing 10 um grid, 2 um pairs, gate/reset/movement capabilities.
    Sets readout=100 us, feedback=0 us, LOAD=STORE=10 us. All atom states are
    unspecified until preparation; the world is not a factory execution result.
    """
    code = definition(spec.distance)
    size = 2 * spec.distance
    patch_pitch = size + int(spec.patch_gap_um / SITE_PITCH_UM)
    columns = 5 * patch_pitch + size + 1
    sites: list[SLMSite] = []
    arrays: list[PairArray] = []
    patches: list[FactoryPatch] = []
    atoms: list[AtomState] = []
    for factory_index in range(spec.pipelines):
        y_origin = -size * SITE_PITCH_UM - factory_index * (
            size * SITE_PITCH_UM + spec.factory_gap_um
        )
        left_rows, right_rows = [], []
        for row in range(size + 1):
            left: list[str] = []
            right: list[str] = []
            for col in range(columns):
                for prefix, shift, names in (
                    ("home", 0, left),
                    ("guest", PAIR_SEPARATION_UM, right),
                ):
                    name = f"{prefix}_f{factory_index}_r{row}_c{col}"
                    names.append(name)
                    sites.append(
                        SLMSite(
                            name,
                            Position(
                                col * SITE_PITCH_UM + shift,
                                y_origin + row * SITE_PITCH_UM,
                            ),
                        )
                    )
            left_rows.append(tuple(left))
            right_rows.append(tuple(right))
        arrays.append(
            PairArray(
                f"factory{factory_index}", "shared", tuple(left_rows), tuple(right_rows)
            )
        )
        for index, role in enumerate(FACTORY_ROLES):
            column = index * patch_pitch
            homes = tuple(
                f"home_f{factory_index}_r{y}_c{column + x}"
                for x, y in code.reference_coordinates
            )
            ids = tuple(range(len(atoms), len(atoms) + code.atom_count))
            origin = Position(column * SITE_PITCH_UM, y_origin)
            binding = ComponentBinding(
                f"factory{factory_index}/{role}", origin, ids, "transport"
            )
            patches.append(FactoryPatch(factory_index, role, binding, homes))
            for atom_id, home, (x, y) in zip(
                ids, homes, code.reference_coordinates, strict=True
            ):
                atoms.append(
                    AtomState(
                        atom_id,
                        Position(
                            origin.x + x * SITE_PITCH_UM, origin.y + y * SITE_PITCH_UM
                        ),
                        SLMHolder(home),
                    )
                )
    padding = spec.window_padding_um
    right_edge = max(site.position.x for site in sites) + padding
    bottom = min(site.position.y for site in sites) - padding
    # Enough distinct rows for every source row at readout spacing, even if an
    # entire array is measured together. The upper region initially has no atoms.
    reference = reference_device()
    assert reference.readout is not None
    row_spacing = max(reference.readout.min_spacing_um, reference.aods[0].min_spacing)
    top = HALFPLANE_GAP_UM + spec.pipelines * (size + 1) * row_spacing + padding
    device = replace(
        reference,
        name=f"msd-d{spec.distance}-n{spec.pipelines}-standard-v1",
        zones=(
            Zone(
                "shared",
                Region(-padding, bottom, right_edge, 0),
                ("cz", "rotate", "reset"),
            ),
            Zone(
                "readout",
                Region(-padding, HALFPLANE_GAP_UM, right_edge, top),
                ("measure",),
                "measurement",
            ),
        ),
        slm_sites=tuple(sites),
        pair_arrays=tuple(arrays),
        aods=(
            replace(
                reference.aods[0],
                id="transport",
                workspace=Region(-padding, bottom, right_edge, top),
            ),
        ),
        timing=replace(reference.timing, load_us=10, store_us=10),
        readout=replace(reference.readout, duration_us=100, latency_us=0),
    )
    state = AtomLayout(tuple(atoms), qubit_to_atom=tuple(a.id for a in atoms))
    validate_layout(device, state)
    return ExperimentWorld(spec, device, state, tuple(patches))
