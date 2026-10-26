"""Static source contracts for joint factories, without timing or probabilities."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from modules.logical_compiler.src.placement import PlacementPlan, validate_plan

from .fast_factory import ROLES, entry_key, required_variants
from .geometry import geometry
from .joint_factory_source import factory_component_source

STATIC_SCHEMA = "nadit.joint_surface_factory_profile/1"


@dataclass(frozen=True)
class JointComponentContract:
    """Ordered participants and a code-owned source interface, never a cost."""

    key: str
    component_id: str
    participant_blocks: tuple[str, ...]
    result_count: int
    source_sha256: str
    wire_indices: tuple[int, ...]
    parameters: tuple[tuple[str, Any], ...]
    code_id: str
    distance: int

    @property
    def claim(self) -> Mapping[str, int]:
        """Expose only static result cardinality to scheduler declarations."""
        return MappingProxyType({"result_count": self.result_count})

    def to_dict(self, *, include_code_identity: bool = False) -> dict[str, Any]:
        """Serialize static identity; uniform documents retain their legacy shape."""
        return {
            "component_id": self.component_id,
            "participant_blocks": list(self.participant_blocks),
            "result_count": self.result_count,
            "source_sha256": self.source_sha256,
            "wire_indices": list(self.wire_indices),
            "parameters": dict(self.parameters),
            **(
                {"code_id": self.code_id, "distance": self.distance}
                if include_code_identity
                else {}
            ),
        }


def static_contracts(
    plan: PlacementPlan,
    additional_calls: Sequence[tuple[str, tuple[str, ...]]] = (),
) -> dict[str, JointComponentContract]:
    """Derive recipe contracts directly from code sources and an explicit plan.

    Additional calls name existing code components and ordered plan block IDs;
    they do not define new transfer, delivery, or maintenance protocols. Raises
    ValueError for incompatible code geometry, identities, or participant counts.
    No physical compiler, noise sampler, or default placement is invoked.
    """
    validate_plan(plan)
    if plan.geometries != {
        block.code: geometry(block.code, block.distance) for block in plan.blocks
    }:
        raise ValueError("JOINT_STATIC_CODE_GEOMETRY_MISMATCH")
    by_id = {block.block_id: block for block in plan.blocks}
    count, remainder = divmod(len(by_id), len(ROLES))
    if remainder or not count:
        raise ValueError("JOINT_STATIC_FACTORY_ROLES_MISMATCH")
    for factory in range(count):
        first = by_id.get(f"factory{factory}/W1")
        if first is None:
            raise ValueError("JOINT_STATIC_FACTORY_ROLES_MISMATCH")
        for role in ROLES:
            identity = f"factory{factory}/{role}"
            block = by_id.get(identity)
            if block is None or (
                block.code,
                block.distance,
                block.factory_id,
                block.role,
            ) != (first.code, first.distance, f"factory{factory}", role):
                raise ValueError("JOINT_STATIC_FACTORY_ROLES_MISMATCH")
    calls = {
        (component, tuple(f"factory{factory}/{role}" for role in roles))
        for factory in range(count)
        for component, roles in required_variants(
            by_id[f"factory{factory}/W1"].distance
        )
    }
    calls.update((component, tuple(blocks)) for component, blocks in additional_calls)
    result = {}
    for component, blocks in sorted(calls):
        if (
            len(set(blocks)) != len(blocks)
            or not set(blocks) <= by_id.keys()
            or len(blocks) != (2 if component == "transversal_cnot" else 1)
        ):
            raise ValueError("JOINT_STATIC_PARTICIPANTS_MISMATCH")
        first = by_id[blocks[0]]
        if any(
            (by_id[block].code, by_id[block].distance) != (first.code, first.distance)
            for block in blocks
        ):
            raise ValueError("JOINT_STATIC_PARTICIPANT_CODE_MISMATCH")
        source = factory_component_source(component, first.distance)
        key = entry_key(component, blocks)
        result[key] = JointComponentContract(
            key,
            component,
            blocks,
            source.result_count,
            sha256(source.source_qasm.encode("utf-8")).hexdigest(),
            source.wire_indices,
            (("injection_rounds", 3),) if component == "raw_t_postselection" else (),
            first.code,
            first.distance,
        )
    return result
